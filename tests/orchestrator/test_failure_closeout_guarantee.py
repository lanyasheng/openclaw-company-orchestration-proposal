#!/usr/bin/env python3
"""
test_failure_closeout_guarantee.py — Tests for failure closeout guarantee

测试失败场景的 closeout guarantee 机制，确保：
1. 任务失败但未形成用户可见失败回报时，产生 fallback_needed / failure guarantee artifact
2. 失败回报已送达时，不误报
3. 成功路径不被回归破坏

这是 P0-4 Batch 4: Failure Closeout Guarantee 的核心测试覆盖。
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

# Also add runtime root to path for state_machine import
RUNTIME_DIR = Path(__file__).resolve().parents[2] / "runtime"
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))


@pytest.fixture(autouse=True)
def isolated_guarantee_env(monkeypatch: pytest.MonkeyPatch):
    """使用临时 guarantee 目录，避免污染真实数据"""
    tmp_dir = tempfile.mkdtemp(prefix="failure_closeout_test_")
    guarantee_dir = Path(tmp_dir) / "guarantees"
    guarantee_dir.mkdir(parents=True, exist_ok=True)
    
    monkeypatch.setenv("OPENCLAW_CLOSEOUT_GUARANTEE_DIR", str(guarantee_dir))
    
    # 重新加载模块以使用新的目录
    import importlib
    sys.path.insert(0, str(ORCHESTRATOR_DIR))
    import closeout_guarantee
    importlib.reload(closeout_guarantee)
    
    yield guarantee_dir
    
    try:
        shutil.rmtree(tmp_dir)
    except Exception:
        pass


# 在 fixture 之后导入，确保使用正确的目录
from closeout_guarantee import (  # type: ignore
    CloseoutGuaranteeKernel,
    CloseoutGuaranteeArtifact,
    check_closeout_guarantee,
    emit_closeout_guarantee,
    get_closeout_guarantee,
    update_closeout_guarantee,
    GUARANTEE_VERSION,
)


class TestFailureCloseoutScenarios:
    """测试失败场景的 closeout guarantee"""
    
    def test_failure_scenario_task_failed_no_user_notification(self, isolated_guarantee_env):
        """失败场景：任务失败但用户未收到通知"""
        kernel = CloseoutGuaranteeKernel()
        
        artifact = kernel.check_guarantee(
            batch_id="batch_failed_001",
            ack_status="fallback_recorded",
            delivery_status="failed",
            dispatch_status="not_triggered",
            has_user_visible_closeout=False,
        )
        
        # 验证：应该触发 fallback_needed
        assert artifact.guarantee_status == "fallback_needed"
        assert artifact.fallback_triggered is True
        assert artifact.internal_completed is True  # 系统内部知道失败
        assert artifact.ack_delivered is False  # 但用户未收到通知
        assert artifact.user_visible_closeout is False
        
        # 验证 failure 相关字段（guarantee_reason 总是存在）
        assert "guarantee_reason" in artifact.metadata
        assert "Ack not delivered" in artifact.metadata["guarantee_reason"]
    
    def test_failure_scenario_subagent_crashed(self, isolated_guarantee_env):
        """失败场景：subagent 崩溃，无 completion callback"""
        kernel = CloseoutGuaranteeKernel()
        
        artifact = kernel.check_guarantee(
            batch_id="batch_crashed_001",
            ack_status="unknown",
            delivery_status="skipped",
            dispatch_status="not_triggered",
            has_user_visible_closeout=False,
        )
        
        # 验证：应该触发 fallback_needed（因为没有任何完成信号）
        assert artifact.guarantee_status == "fallback_needed"
        assert artifact.fallback_triggered is True
        assert "Ack not delivered" in artifact.fallback_reason
    
    def test_failure_scenario_timeout_without_notification(self, isolated_guarantee_env):
        """失败场景：任务超时，但用户未收到超时通知"""
        kernel = CloseoutGuaranteeKernel()
        
        artifact = kernel.check_guarantee(
            batch_id="batch_timeout_001",
            ack_status="timeout",
            delivery_status="skipped",
            dispatch_status="not_triggered",
            has_user_visible_closeout=False,
        )
        
        # 验证：应该触发 fallback_needed
        assert artifact.guarantee_status == "fallback_needed"
        assert artifact.fallback_triggered is True
    
    def test_failure_scenario_error_with_fallback_notification_sent(self, isolated_guarantee_env):
        """失败场景：任务失败，但失败通知已送达"""
        kernel = CloseoutGuaranteeKernel()
        
        artifact = kernel.check_guarantee(
            batch_id="batch_failed_notified_001",
            ack_status="sent",
            delivery_status="sent",
            dispatch_status="not_triggered",
            has_user_visible_closeout=False,
            # 注意：这里 ack 已发送，所以不会触发 fallback_needed
        )
        
        # 验证：ack 已发送，状态为 pending（等待用户确认）
        assert artifact.guarantee_status == "pending"
        assert artifact.fallback_triggered is False
        assert artifact.ack_delivered is True
    
    def test_failure_scenario_error_user_confirmed(self, isolated_guarantee_env):
        """失败场景：任务失败，用户已确认收到失败通知"""
        kernel = CloseoutGuaranteeKernel()
        
        artifact = kernel.check_guarantee(
            batch_id="batch_failed_confirmed_001",
            ack_status="sent",
            delivery_status="sent",
            dispatch_status="not_triggered",
            has_user_visible_closeout=True,  # 用户已感知失败
        )
        
        # 验证：用户已确认，状态为 guaranteed
        assert artifact.guarantee_status == "guaranteed"
        assert artifact.user_visible_closeout is True
        assert artifact.fallback_triggered is False


class TestFailureCloseoutEmitAndWrite:
    """测试失败场景的 guarantee emit 和写入"""
    
    def test_emit_failure_guarantee_with_failure_metadata(self, isolated_guarantee_env):
        """emit 失败 guarantee，带 failure 元数据"""
        artifact = emit_closeout_guarantee(
            batch_id="batch_failure_001",
            ack_status="fallback_recorded",
            delivery_status="failed",
            dispatch_status="not_triggered",
            has_user_visible_closeout=False,
            metadata={
                "failure_summary": "Subagent crashed without completion callback",
                "failure_stage": "execution",
                "truth_anchor": "status.json shows state=failed",
                "fallback_action": "Notify user and suggest retry with different backend",
            },
        )
        
        # 验证 guarantee 状态
        assert artifact.guarantee_status == "fallback_needed"
        assert artifact.fallback_triggered is True
        
        # 验证 failure 元数据
        assert artifact.metadata["failure_summary"] == "Subagent crashed without completion callback"
        assert artifact.metadata["failure_stage"] == "execution"
        assert artifact.metadata["truth_anchor"] == "status.json shows state=failed"
        assert artifact.metadata["fallback_action"] == "Notify user and suggest retry with different backend"
        
        # 验证文件已写入
        from closeout_guarantee import _guarantee_file
        guarantee_path = _guarantee_file("batch_failure_001")
        assert guarantee_path.exists()
        
        # 验证文件内容
        with open(guarantee_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        assert data["guarantee_status"] == "fallback_needed"
        assert data["metadata"]["failure_summary"] == "Subagent crashed without completion callback"
    
    def test_update_failure_guarantee_to_user_notified(self, isolated_guarantee_env):
        """更新失败 guarantee：用户已收到失败通知"""
        # 先创建失败 guarantee
        emit_closeout_guarantee(
            batch_id="batch_failure_002",
            ack_status="fallback_recorded",
            delivery_status="failed",
            dispatch_status="not_triggered",
            has_user_visible_closeout=False,
            metadata={
                "failure_summary": "Task failed",
                "fallback_action": "Notify user",
            },
        )
        
        # 验证初始状态
        artifact1 = get_closeout_guarantee("batch_failure_002")
        assert artifact1 is not None
        assert artifact1.guarantee_status == "fallback_needed"
        assert artifact1.user_visible_closeout is False
        
        # 更新：用户已收到通知
        artifact2 = update_closeout_guarantee(
            batch_id="batch_failure_002",
            user_visible_closeout=True,
            metadata={
                "notified_at": "2026-03-24T12:00:00",
                "notification_channel": "discord",
            },
        )
        
        # 验证更新后状态
        assert artifact2.guarantee_status == "guaranteed"
        assert artifact2.user_visible_closeout is True
        assert "guaranteed_at" in artifact2.metadata
        assert artifact2.metadata["notified_at"] == "2026-03-24T12:00:00"


class TestFailureCloseoutNoFalsePositives:
    """测试失败场景不误报"""
    
    def test_no_false_positive_dispatch_triggered(self, isolated_guarantee_env):
        """不误报：dispatch 已触发，等待 continuation"""
        kernel = CloseoutGuaranteeKernel()
        
        artifact = kernel.check_guarantee(
            batch_id="batch_dispatch_001",
            ack_status="unknown",
            delivery_status="unknown",
            dispatch_status="triggered",
            has_user_visible_closeout=False,
        )
        
        # 验证：dispatch 已触发，不应该触发 fallback
        assert artifact.guarantee_status == "pending"
        assert artifact.fallback_triggered is False
    
    def test_no_false_positive_ack_sent(self, isolated_guarantee_env):
        """不误报：ack 已发送，等待 delivery"""
        kernel = CloseoutGuaranteeKernel()
        
        artifact = kernel.check_guarantee(
            batch_id="batch_ack_sent_001",
            ack_status="sent",
            delivery_status="pending",
            dispatch_status="unknown",
            has_user_visible_closeout=False,
        )
        
        # 验证：ack 已发送，不应该触发 fallback
        assert artifact.guarantee_status == "pending"
        assert artifact.fallback_triggered is False


class TestSuccessPathNotRegressed:
    """测试成功路径不被回归破坏"""
    
    def test_success_path_happy_case(self, isolated_guarantee_env):
        """成功路径：正常完成，用户已确认"""
        kernel = CloseoutGuaranteeKernel()
        
        artifact = kernel.check_guarantee(
            batch_id="batch_success_001",
            ack_status="sent",
            delivery_status="sent",
            dispatch_status="triggered",
            has_user_visible_closeout=True,
        )
        
        # 验证：成功路径正常工作
        assert artifact.guarantee_status == "guaranteed"
        assert artifact.user_visible_closeout is True
        assert artifact.fallback_triggered is False
    
    def test_success_path_pending_confirmation(self, isolated_guarantee_env):
        """成功路径：完成但等待用户确认"""
        kernel = CloseoutGuaranteeKernel()
        
        artifact = kernel.check_guarantee(
            batch_id="batch_success_002",
            ack_status="sent",
            delivery_status="sent",
            dispatch_status="triggered",
            has_user_visible_closeout=False,
        )
        
        # 验证：等待确认，不触发 fallback
        assert artifact.guarantee_status == "pending"
        assert artifact.fallback_triggered is False
        assert artifact.ack_delivered is True


class TestFailureCloseoutFields:
    """测试失败 closeout 字段"""
    
    def test_failure_summary_field(self, isolated_guarantee_env):
        """测试 failure_summary 字段"""
        artifact = emit_closeout_guarantee(
            batch_id="batch_fields_001",
            ack_status="fallback_recorded",
            delivery_status="failed",
            dispatch_status="not_triggered",
            metadata={
                "failure_summary": "Detailed failure description",
            },
        )
        
        assert artifact.metadata["failure_summary"] == "Detailed failure description"
    
    def test_failure_stage_field(self, isolated_guarantee_env):
        """测试 failure_stage 字段"""
        artifact = emit_closeout_guarantee(
            batch_id="batch_fields_002",
            ack_status="fallback_recorded",
            delivery_status="failed",
            dispatch_status="not_triggered",
            metadata={
                "failure_stage": "planning",  # planning | execution | closeout
            },
        )
        
        assert artifact.metadata["failure_stage"] == "planning"
    
    def test_truth_anchor_field(self, isolated_guarantee_env):
        """测试 truth_anchor 字段"""
        artifact = emit_closeout_guarantee(
            batch_id="batch_fields_003",
            ack_status="fallback_recorded",
            delivery_status="failed",
            dispatch_status="not_triggered",
            metadata={
                "truth_anchor": "status.json:state=failed|exit_code=1",
            },
        )
        
        assert artifact.metadata["truth_anchor"] == "status.json:state=failed|exit_code=1"
    
    def test_fallback_action_field(self, isolated_guarantee_env):
        """测试 fallback_action 字段"""
        artifact = emit_closeout_guarantee(
            batch_id="batch_fields_004",
            ack_status="fallback_recorded",
            delivery_status="failed",
            dispatch_status="not_triggered",
            metadata={
                "fallback_action": "Retry with subagent backend instead of tmux",
            },
        )
        
        assert artifact.metadata["fallback_action"] == "Retry with subagent backend instead of tmux"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
