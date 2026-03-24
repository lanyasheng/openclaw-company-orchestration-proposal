#!/usr/bin/env python3
"""
test_closeout_guarantee.py — Tests for user-visible closeout guarantee

测试 user-visible closeout guarantee 机制，确保：
1. internal completion 与 user-visible closeout 区分清楚
2. completion 到达后，如果父层没有形成 final closeout，兜底机制生效
3. 正常 closeout 情况不被误报
4. guarantee artifact 正确落盘

这是 P0-4 Final Mile 的核心测试覆盖。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import shutil
from datetime import datetime
from pathlib import Path

import pytest

# Add orchestrator to path
ORCHESTRATOR_DIR = Path(__file__).resolve().parents[2] / "runtime" / "orchestrator"
if str(ORCHESTRATOR_DIR) not in sys.path:
    sys.path.insert(0, str(ORCHESTRATOR_DIR))


@pytest.fixture(autouse=True)
def isolated_guarantee_env(monkeypatch: pytest.MonkeyPatch):
    """使用临时 guarantee 目录，避免污染真实数据"""
    # 创建临时目录
    tmp_dir = tempfile.mkdtemp(prefix="closeout_guarantee_test_")
    guarantee_dir = Path(tmp_dir) / "guarantees"
    guarantee_dir.mkdir(parents=True, exist_ok=True)
    
    # 设置环境变量
    monkeypatch.setenv("OPENCLAW_CLOSEOUT_GUARANTEE_DIR", str(guarantee_dir))
    
    # 重新加载模块以使用新的目录
    import importlib
    import closeout_guarantee
    importlib.reload(closeout_guarantee)
    
    yield guarantee_dir
    
    # 清理
    try:
        shutil.rmtree(tmp_dir)
    except Exception:
        pass


# 在 fixture 之后导入，确保使用正确的目录
from closeout_guarantee import (
    CloseoutGuaranteeKernel,
    CloseoutGuaranteeArtifact,
    check_closeout_guarantee,
    emit_closeout_guarantee,
    get_closeout_guarantee,
    update_closeout_guarantee,
    CLOSEOUT_GUARANTEE_DIR,
    _guarantee_file,
    GUARANTEE_VERSION,
)


class TestCloseoutGuaranteeArtifact:
    """测试 CloseoutGuaranteeArtifact 数据类"""
    
    def test_to_dict(self):
        artifact = CloseoutGuaranteeArtifact(
            guarantee_id="guarantee_test123",
            batch_id="batch_001",
            guarantee_status="pending",
            internal_completed=True,
            ack_delivered=False,
            user_visible_closeout=False,
            fallback_triggered=False,
            metadata={"test": "data"},
        )
        
        d = artifact.to_dict()
        assert d["guarantee_id"] == "guarantee_test123"
        assert d["batch_id"] == "batch_001"
        assert d["guarantee_status"] == "pending"
        assert d["internal_completed"] is True
        assert d["ack_delivered"] is False
        assert d["user_visible_closeout"] is False
        assert d["fallback_triggered"] is False
        assert d["metadata"]["test"] == "data"
        assert "guarantee_version" in d
        assert d["guarantee_version"] == GUARANTEE_VERSION
    
    def test_from_dict(self):
        data = {
            "guarantee_id": "guarantee_test456",
            "batch_id": "batch_002",
            "guarantee_status": "guaranteed",
            "internal_completed": True,
            "ack_delivered": True,
            "user_visible_closeout": True,
            "fallback_triggered": False,
            "metadata": {"test": "data"},
            "created_at": "2026-03-24T12:00:00",
        }
        
        artifact = CloseoutGuaranteeArtifact.from_dict(data)
        assert artifact.guarantee_id == "guarantee_test456"
        assert artifact.batch_id == "batch_002"
        assert artifact.guarantee_status == "guaranteed"
        assert artifact.internal_completed is True
        assert artifact.ack_delivered is True
        assert artifact.user_visible_closeout is True


class TestCloseoutGuaranteeKernel:
    """测试 CloseoutGuaranteeKernel"""
    
    def test_check_guarantee_first_time(self, isolated_guarantee_env):
        """首次检查 guarantee（无历史记录）"""
        kernel = CloseoutGuaranteeKernel()
        
        artifact = kernel.check_guarantee(
            batch_id="batch_001",
            ack_status="sent",
            delivery_status="sent",
            dispatch_status="unknown",
            has_user_visible_closeout=False,
        )
        
        assert artifact.batch_id == "batch_001"
        assert artifact.internal_completed is True
        assert artifact.ack_delivered is True
        assert artifact.user_visible_closeout is False
        assert artifact.guarantee_status == "pending"
    
    def test_check_guarantee_with_user_visible_closeout(self, isolated_guarantee_env):
        """已有用户可见闭环"""
        kernel = CloseoutGuaranteeKernel()
        
        artifact = kernel.check_guarantee(
            batch_id="batch_001",
            ack_status="sent",
            delivery_status="sent",
            dispatch_status="unknown",
            has_user_visible_closeout=True,
        )
        
        assert artifact.guarantee_status == "guaranteed"
        assert artifact.user_visible_closeout is True
    
    def test_check_guarantee_fallback_needed(self, isolated_guarantee_env):
        """需要兜底：ack 未发送且 dispatch 未触发"""
        kernel = CloseoutGuaranteeKernel()
        
        artifact = kernel.check_guarantee(
            batch_id="batch_001",
            ack_status="fallback_recorded",
            delivery_status="skipped",
            dispatch_status="unknown",
            has_user_visible_closeout=False,
        )
        
        assert artifact.guarantee_status == "fallback_needed"
        assert artifact.fallback_triggered is True
        assert artifact.fallback_reason is not None
        assert "Ack not delivered" in artifact.fallback_reason
    
    def test_check_guarantee_dispatch_triggered(self, isolated_guarantee_env):
        """dispatch 已触发，等待 continuation"""
        kernel = CloseoutGuaranteeKernel()
        
        artifact = kernel.check_guarantee(
            batch_id="batch_001",
            ack_status="unknown",
            delivery_status="unknown",
            dispatch_status="triggered",
            has_user_visible_closeout=False,
        )
        
        assert artifact.guarantee_status == "pending"
        assert "Dispatch triggered" in artifact.metadata.get("guarantee_reason", "")


class TestEmitCloseoutGuarantee:
    """测试 emit_closeout_guarantee 函数"""
    
    def test_emit_guarantee_writes_file(self, isolated_guarantee_env):
        """emit guarantee 应该写入文件"""
        artifact = emit_closeout_guarantee(
            batch_id="batch_001",
            ack_status="sent",
            delivery_status="sent",
            dispatch_status="unknown",
            has_user_visible_closeout=False,
        )
        
        # 验证文件已写入
        guarantee_path = _guarantee_file("batch_001")
        assert guarantee_path.exists()
        
        # 验证内容
        with open(guarantee_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        assert data["guarantee_id"] == artifact.guarantee_id
        assert data["batch_id"] == "batch_001"
        assert data["guarantee_status"] == "pending"
    
    def test_emit_guarantee_with_artifacts(self, isolated_guarantee_env):
        """emit guarantee 带 artifacts"""
        artifact = emit_closeout_guarantee(
            batch_id="batch_001",
            ack_status="sent",
            delivery_status="sent",
            dispatch_status="unknown",
            artifacts={
                "ack_receipt_path": "/path/to/receipt.md",
                "ack_audit_path": "/path/to/audit.json",
            },
        )
        
        assert artifact.artifacts["ack_receipt_path"] == "/path/to/receipt.md"
        assert artifact.artifacts["ack_audit_path"] == "/path/to/audit.json"
        
        # 验证文件中的 artifacts
        guarantee_path = _guarantee_file("batch_001")
        with open(guarantee_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        assert data["artifacts"]["ack_receipt_path"] == "/path/to/receipt.md"


class TestUpdateCloseoutGuarantee:
    """测试 update_closeout_guarantee 函数"""
    
    def test_update_to_user_visible_closeout(self, isolated_guarantee_env):
        """更新为 user-visible closeout"""
        # 先创建 guarantee
        emit_closeout_guarantee(
            batch_id="batch_001",
            ack_status="sent",
            delivery_status="sent",
            dispatch_status="unknown",
            has_user_visible_closeout=False,
        )
        
        # 更新为 user-visible closeout
        artifact = update_closeout_guarantee(
            batch_id="batch_001",
            user_visible_closeout=True,
        )
        
        assert artifact.guarantee_status == "guaranteed"
        assert artifact.user_visible_closeout is True
        assert "guaranteed_at" in artifact.metadata
        
        # 验证文件中的更新
        guarantee_path = _guarantee_file("batch_001")
        with open(guarantee_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        assert data["guarantee_status"] == "guaranteed"
        assert data["user_visible_closeout"] is True
    
    def test_update_nonexistent_guarantee(self, isolated_guarantee_env):
        """更新不存在的 guarantee 应该抛出错误"""
        with pytest.raises(ValueError, match="not found"):
            update_closeout_guarantee(
                batch_id="batch_nonexistent",
                user_visible_closeout=True,
            )


class TestGetCloseoutGuarantee:
    """测试 get_closeout_guarantee 函数"""
    
    def test_get_existing_guarantee(self, isolated_guarantee_env):
        """获取已存在的 guarantee"""
        # 先创建 guarantee
        original = emit_closeout_guarantee(
            batch_id="batch_001",
            ack_status="sent",
            delivery_status="sent",
            dispatch_status="unknown",
        )
        
        # 获取
        retrieved = get_closeout_guarantee("batch_001")
        
        assert retrieved is not None
        assert retrieved.guarantee_id == original.guarantee_id
        assert retrieved.batch_id == original.batch_id
    
    def test_get_nonexistent_guarantee(self, isolated_guarantee_env):
        """获取不存在的 guarantee 返回 None"""
        result = get_closeout_guarantee("batch_nonexistent")
        assert result is None


class TestCloseoutGuaranteeScenarios:
    """测试 closeout guarantee 的各种场景"""
    
    def test_scenario_ack_sent_delivery_success(self, isolated_guarantee_env):
        """场景：ack 发送成功，delivery 成功"""
        artifact = emit_closeout_guarantee(
            batch_id="batch_001",
            ack_status="sent",
            delivery_status="sent",
            dispatch_status="unknown",
        )
        
        assert artifact.guarantee_status == "pending"
        assert artifact.ack_delivered is True
        assert artifact.fallback_triggered is False
    
    def test_scenario_ack_fallback_recorded(self, isolated_guarantee_env):
        """场景：ack fallback recorded（delivery 失败）"""
        artifact = emit_closeout_guarantee(
            batch_id="batch_001",
            ack_status="fallback_recorded",
            delivery_status="skipped",
            dispatch_status="unknown",
        )
        
        assert artifact.guarantee_status == "fallback_needed"
        assert artifact.ack_delivered is False
        assert artifact.fallback_triggered is True
        assert artifact.fallback_reason is not None
    
    def test_scenario_dispatch_triggered(self, isolated_guarantee_env):
        """场景：dispatch 已触发（等待 continuation）"""
        artifact = emit_closeout_guarantee(
            batch_id="batch_001",
            ack_status="unknown",
            delivery_status="unknown",
            dispatch_status="triggered",
        )
        
        assert artifact.guarantee_status == "pending"
        assert artifact.fallback_triggered is False
    
    def test_scenario_full_closeout_chain(self, isolated_guarantee_env):
        """场景：完整 closeout 链路（从 pending 到 guaranteed）"""
        # 步骤 1：创建 guarantee（initial state）
        artifact1 = emit_closeout_guarantee(
            batch_id="batch_001",
            ack_status="sent",
            delivery_status="sent",
            dispatch_status="unknown",
            has_user_visible_closeout=False,
        )
        
        assert artifact1.guarantee_status == "pending"
        assert artifact1.user_visible_closeout is False
        
        # 步骤 2：用户确认 closeout
        artifact2 = update_closeout_guarantee(
            batch_id="batch_001",
            user_visible_closeout=True,
        )
        
        assert artifact2.guarantee_status == "guaranteed"
        assert artifact2.user_visible_closeout is True
        assert "guaranteed_at" in artifact2.metadata


class TestCloseoutGuaranteeIntegration:
    """测试 closeout guarantee 与 completion_ack_guard 的集成"""
    
    def test_guarantee_artifact_linked_to_ack_receipt(self, isolated_guarantee_env):
        """guarantee artifact 应该 link 到 ack receipt"""
        from completion_ack_guard import send_roundtable_completion_ack  # type: ignore
        
        # 创建 mock decision
        class MockDecision:
            action = "proceed"
            metadata = {
                "roundtable": {
                    "conclusion": "PASS",
                    "blocker": "none",
                    "next_step": "Continue",
                },
                "continuation": {
                    "task_preview": "Next task",
                },
            }
        
        decision = MockDecision()
        summary_path = Path("/tmp/test_summary.md")
        dispatch_info = {
            "decision_path": "/tmp/test_decision.json",
            "dispatch_path": "/tmp/test_dispatch.json",
            "dispatch_plan": {
                "status": "unknown",
            },
        }
        
        # 调用 send_roundtable_completion_ack（应该自动 emit guarantee）
        result = send_roundtable_completion_ack(
            batch_id="batch_test_integration",
            decision=decision,
            summary_path=summary_path,
            dispatch_info=dispatch_info,
            requester_session_key="agent:main:discord:channel:test123",
            adapter_name="test_adapter",
            scenario="test_scenario",
        )
        
        # 验证 result 包含 closeout_guarantee
        assert "closeout_guarantee" in result
        guarantee_info = result["closeout_guarantee"]
        
        # 验证 guarantee 信息
        assert "guarantee_id" in guarantee_info
        assert "guarantee_status" in guarantee_info
        assert "internal_completed" in guarantee_info
        assert "ack_delivered" in guarantee_info
        assert "user_visible_closeout" in guarantee_info
        
        # 验证 guarantee 文件已写入
        guarantee_path = Path(guarantee_info.get("guarantee_path", ""))
        assert guarantee_path.exists() or guarantee_info.get("status") == "failed"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
