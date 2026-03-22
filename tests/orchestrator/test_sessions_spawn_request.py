#!/usr/bin/env python3
"""
test_sessions_spawn_request.py — Tests for Universal Partial-Completion Continuation Framework v6

测试 sessions_spawn_request 模块（通用 sessions_spawn-compatible request interface）。

覆盖：
- happy path: 生成 sessions_spawn-compatible request
- blocked / duplicate / missing payload 不生成 request
- receipt 后生成 auto-close artifact
- 通用 kernel（不绑定 trading）
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from datetime import datetime

import pytest

# 添加 orchestrator 到路径
ORCHESTRATOR_PATH = Path(__file__).parent.parent.parent / "runtime" / "orchestrator"
sys.path.insert(0, str(ORCHESTRATOR_PATH))

from sessions_spawn_request import (
    SessionsSpawnRequest,
    SpawnRequestPolicy,
    SpawnRequestKernel,
    prepare_spawn_request,
    list_spawn_requests,
    get_spawn_request,
    REQUEST_VERSION,
    SPAWN_REQUEST_DIR,
    REQUEST_INDEX_FILE,
    _load_request_index,
    _save_request_index,
    _generate_request_dedupe_key,
)

from completion_receipt import (
    CompletionReceiptArtifact,
    ReceiptStatus,
)


@pytest.fixture
def temp_request_dir(tmp_path):
    """临时 request 目录"""
    request_dir = tmp_path / "spawn_requests"
    request_dir.mkdir()
    
    # 临时覆盖环境变量
    old_env = os.environ.get("OPENCLAW_SPAWN_REQUEST_DIR")
    os.environ["OPENCLAW_SPAWN_REQUEST_DIR"] = str(request_dir)
    
    yield request_dir
    
    # 恢复
    if old_env:
        os.environ["OPENCLAW_SPAWN_REQUEST_DIR"] = old_env
    else:
        os.environ.pop("OPENCLAW_SPAWN_REQUEST_DIR", None)


@pytest.fixture
def sample_receipt(tmp_path) -> CompletionReceiptArtifact:
    """样本 completion receipt（唯一 ID）"""
    import uuid
    suffix = uuid.uuid4().hex[:6]
    return CompletionReceiptArtifact(
        receipt_id=f"receipt_{suffix}",
        source_spawn_execution_id=f"exec_{suffix}",
        source_spawn_id=f"spawn_{suffix}",
        source_dispatch_id=f"dispatch_{suffix}",
        source_registration_id=f"reg_{suffix}",
        source_task_id=f"task_{suffix}",
        receipt_status="completed",
        receipt_reason="Execution completed successfully",
        receipt_time=datetime.now().isoformat(),
        result_summary="Test execution completed",
        dedupe_key=f"dedupe_{suffix}",
        business_result={"test": "data"},
        metadata={
            "source_execution_status": "started",
            "scenario": "test_scenario",
            "owner": "test_owner",
            "truth_anchor": "test_anchor",
        },
    )


@pytest.fixture
def sample_receipt_failed(tmp_path) -> CompletionReceiptArtifact:
    """样本 failed receipt（唯一 ID）"""
    import uuid
    suffix = uuid.uuid4().hex[:6]
    return CompletionReceiptArtifact(
        receipt_id=f"receipt_failed_{suffix}",
        source_spawn_execution_id=f"exec_failed_{suffix}",
        source_spawn_id=f"spawn_failed_{suffix}",
        source_dispatch_id=f"dispatch_failed_{suffix}",
        source_registration_id=f"reg_failed_{suffix}",
        source_task_id=f"task_failed_{suffix}",
        receipt_status="failed",
        receipt_reason="Execution failed",
        receipt_time=datetime.now().isoformat(),
        result_summary="Test execution failed",
        dedupe_key=f"dedupe_failed_{suffix}",
        metadata={
            "source_execution_status": "failed",
            "scenario": "test_scenario",
        },
    )


class TestSessionsSpawnRequest:
    """测试 SessionsSpawnRequest 数据类"""
    
    def test_create_request(self, sample_receipt):
        """测试创建 request"""
        request = SessionsSpawnRequest(
            request_id="req_test123",
            source_receipt_id=sample_receipt.receipt_id,
            source_execution_id=sample_receipt.source_spawn_execution_id,
            source_spawn_id=sample_receipt.source_spawn_id,
            source_dispatch_id=sample_receipt.source_dispatch_id,
            source_registration_id=sample_receipt.source_registration_id,
            source_task_id=sample_receipt.source_task_id,
            spawn_request_status="prepared",
            spawn_request_reason="Test reason",
            spawn_request_time=datetime.now().isoformat(),
            sessions_spawn_params={
                "runtime": "subagent",
                "cwd": "/test",
                "task": "Test task",
                "label": "test-label",
            },
            dedupe_key="dedupe_test",
        )
        
        assert request.request_id == "req_test123"
        assert request.spawn_request_status == "prepared"
        assert request.sessions_spawn_params["runtime"] == "subagent"
    
    def test_to_dict(self, sample_receipt):
        """测试 to_dict 序列化"""
        request = SessionsSpawnRequest(
            request_id="req_test123",
            source_receipt_id=sample_receipt.receipt_id,
            source_execution_id=sample_receipt.source_spawn_execution_id,
            source_spawn_id=sample_receipt.source_spawn_id,
            source_dispatch_id=sample_receipt.source_dispatch_id,
            source_registration_id=sample_receipt.source_registration_id,
            source_task_id=sample_receipt.source_task_id,
            spawn_request_status="prepared",
            spawn_request_reason="Test reason",
            spawn_request_time=datetime.now().isoformat(),
            sessions_spawn_params={"runtime": "subagent"},
            dedupe_key="dedupe_test",
        )
        
        data = request.to_dict()
        assert data["request_version"] == REQUEST_VERSION
        assert data["request_id"] == "req_test123"
        assert data["spawn_request_status"] == "prepared"
    
    def test_from_dict(self, sample_receipt):
        """测试 from_dict 反序列化"""
        data = {
            "request_version": REQUEST_VERSION,
            "request_id": "req_test123",
            "source_receipt_id": sample_receipt.receipt_id,
            "source_execution_id": sample_receipt.source_spawn_execution_id,
            "source_spawn_id": sample_receipt.source_spawn_id,
            "source_dispatch_id": sample_receipt.source_dispatch_id,
            "source_registration_id": sample_receipt.source_registration_id,
            "source_task_id": sample_receipt.source_task_id,
            "spawn_request_status": "prepared",
            "spawn_request_reason": "Test reason",
            "spawn_request_time": datetime.now().isoformat(),
            "sessions_spawn_params": {"runtime": "subagent"},
            "dedupe_key": "dedupe_test",
        }
        
        request = SessionsSpawnRequest.from_dict(data)
        assert request.request_id == "req_test123"
        assert request.spawn_request_status == "prepared"
    
    def test_to_sessions_spawn_call(self, sample_receipt):
        """测试转换为 sessions_spawn 调用参数"""
        request = SessionsSpawnRequest(
            request_id="req_test123",
            source_receipt_id=sample_receipt.receipt_id,
            source_execution_id=sample_receipt.source_spawn_execution_id,
            source_spawn_id=sample_receipt.source_spawn_id,
            source_dispatch_id=sample_receipt.source_dispatch_id,
            source_registration_id=sample_receipt.source_registration_id,
            source_task_id=sample_receipt.source_task_id,
            spawn_request_status="prepared",
            spawn_request_reason="Test reason",
            spawn_request_time=datetime.now().isoformat(),
            sessions_spawn_params={
                "runtime": "subagent",
                "cwd": "/test/path",
                "task": "Test task",
                "label": "test-label",
                "metadata": {"custom": "data"},
            },
            dedupe_key="dedupe_test",
        )
        
        params = request.to_sessions_spawn_call()
        
        assert params["runtime"] == "subagent"
        assert params["cwd"] == "/test/path"
        assert params["task"] == "Test task"
        assert params["label"] == "test-label"
        assert params["metadata"]["custom"] == "data"
        assert params["metadata"]["request_id"] == "req_test123"
        assert params["metadata"]["orchestration_version"] == REQUEST_VERSION


class TestSpawnRequestPolicy:
    """测试 SpawnRequestPolicy"""
    
    def test_default_policy(self):
        """测试默认 policy"""
        policy = SpawnRequestPolicy()
        
        assert policy.require_receipt_status == "completed"
        assert policy.require_execution_payload is True
        assert policy.prevent_duplicate is True
        assert policy.prepare_only is True
    
    def test_custom_policy(self):
        """测试自定义 policy"""
        policy = SpawnRequestPolicy(
            require_receipt_status="completed",
            require_execution_payload=False,
            prevent_duplicate=False,
            prepare_only=False,
        )
        
        assert policy.require_receipt_status == "completed"
        assert policy.require_execution_payload is False
        assert policy.prevent_duplicate is False
        assert policy.prepare_only is False
    
    def test_to_dict(self):
        """测试 to_dict 序列化"""
        policy = SpawnRequestPolicy(
            require_receipt_status="completed",
            require_execution_payload=True,
        )
        
        data = policy.to_dict()
        assert data["require_receipt_status"] == "completed"
        assert data["require_execution_payload"] is True
    
    def test_from_dict(self):
        """测试 from_dict 反序列化"""
        data = {
            "require_receipt_status": "completed",
            "require_execution_payload": False,
            "prevent_duplicate": False,
            "prepare_only": False,
        }
        
        policy = SpawnRequestPolicy.from_dict(data)
        assert policy.require_receipt_status == "completed"
        assert policy.require_execution_payload is False


class TestSpawnRequestKernel:
    """测试 SpawnRequestKernel"""
    
    def test_evaluate_policy_passed(self, sample_receipt):
        """测试 policy 评估通过"""
        kernel = SpawnRequestKernel()
        evaluation = kernel.evaluate_policy(sample_receipt)
        
        assert evaluation["eligible"] is True
        assert len(evaluation["blocked_reasons"]) == 0
        assert len(evaluation["checks"]) > 0
        
        # 检查各个 check
        check_names = [c["name"] for c in evaluation["checks"]]
        assert "receipt_status" in check_names
        assert "execution_payload_required" in check_names
        assert "prevent_duplicate_request" in check_names
    
    def test_evaluate_policy_blocked_receipt_status(self, sample_receipt_failed):
        """测试 policy 评估被阻塞（receipt status 不符）"""
        kernel = SpawnRequestKernel()
        evaluation = kernel.evaluate_policy(sample_receipt_failed)
        
        assert evaluation["eligible"] is False
        assert len(evaluation["blocked_reasons"]) > 0
        assert any("Receipt status" in r for r in evaluation["blocked_reasons"])
    
    def test_create_request_prepared(self, sample_receipt):
        """测试创建 prepared request"""
        kernel = SpawnRequestKernel()
        evaluation = kernel.evaluate_policy(sample_receipt)
        request = kernel.create_request(sample_receipt, evaluation)
        
        assert request.spawn_request_status == "prepared"
        assert "Policy evaluation passed" in request.spawn_request_reason
        assert request.sessions_spawn_params is not None
        assert request.sessions_spawn_params["runtime"] == "subagent"
    
    def test_create_request_blocked(self, sample_receipt_failed):
        """测试创建 blocked request"""
        kernel = SpawnRequestKernel()
        evaluation = kernel.evaluate_policy(sample_receipt_failed)
        request = kernel.create_request(sample_receipt_failed, evaluation)
        
        assert request.spawn_request_status == "blocked"
    
    def test_emit_request_writes_file(self, temp_request_dir, sample_receipt):
        """测试 emit request 写入文件"""
        # 重新加载模块以使用新的环境变量
        import importlib
        import sessions_spawn_request as ssr
        importlib.reload(ssr)
        
        kernel = ssr.SpawnRequestKernel()
        request = kernel.emit_request(sample_receipt)
        
        # 检查文件是否存在（使用重新加载后的模块路径）
        request_file = ssr._spawn_request_file(request.request_id)
        assert request_file.exists()
        
        # 检查内容
        with open(request_file) as f:
            data = json.load(f)
        assert data["request_id"] == request.request_id
        assert data["spawn_request_status"] == "prepared"
    
    def test_emit_request_records_dedupe(self, temp_request_dir, sample_receipt):
        """测试 emit request 记录 dedupe"""
        # 重新加载模块以使用新的环境变量
        import importlib
        import sessions_spawn_request as ssr
        importlib.reload(ssr)
        
        kernel = ssr.SpawnRequestKernel()
        request = kernel.emit_request(sample_receipt)
        
        # 检查 index 文件
        assert ssr.REQUEST_INDEX_FILE.exists()
        
        index = ssr._load_request_index()
        dedupe_key = ssr._generate_request_dedupe_key(
            sample_receipt.receipt_id,
            sample_receipt.source_spawn_execution_id,
        )
        assert dedupe_key in index
        assert index[dedupe_key] == request.request_id
    
    def test_duplicate_prevention(self, temp_request_dir, sample_receipt):
        """测试重复创建防止"""
        # 重新加载模块以使用新的环境变量
        import importlib
        import sessions_spawn_request as ssr
        importlib.reload(ssr)
        
        kernel = ssr.SpawnRequestKernel()
        
        # 第一次创建
        request1 = kernel.emit_request(sample_receipt)
        assert request1.spawn_request_status == "prepared"
        
        # 第二次创建（应该被阻塞）
        request2 = kernel.emit_request(sample_receipt)
        assert request2.spawn_request_status == "blocked"
        assert "Duplicate request" in request2.spawn_request_reason


class TestConvenienceFunctions:
    """测试便利函数"""
    
    def test_prepare_spawn_request(self, temp_request_dir, sample_receipt):
        """测试 prepare_spawn_request"""
        # 重新加载模块以使用新的环境变量
        import importlib
        import sessions_spawn_request as ssr
        import completion_receipt as cr
        importlib.reload(cr)
        importlib.reload(ssr)
        
        # 先写入 receipt
        cr.COMPLETION_RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
        receipt_file = cr._completion_receipt_file(sample_receipt.receipt_id)
        with open(receipt_file, "w") as f:
            json.dump(sample_receipt.to_dict(), f)
        
        try:
            request = ssr.prepare_spawn_request(sample_receipt.receipt_id)
            assert request is not None
            assert request.spawn_request_status == "prepared"
        finally:
            # 清理
            receipt_file.unlink()
    
    def test_list_spawn_requests(self, temp_request_dir, sample_receipt):
        """测试 list_spawn_requests"""
        # 重新加载模块以使用新的环境变量
        import importlib
        import sessions_spawn_request as ssr
        importlib.reload(ssr)
        
        kernel = ssr.SpawnRequestKernel()
        request = kernel.emit_request(sample_receipt)
        
        # 列出所有 requests
        requests = ssr.list_spawn_requests()
        assert len(requests) >= 1
        
        # 按 receipt_id 过滤
        requests = ssr.list_spawn_requests(receipt_id=sample_receipt.receipt_id)
        assert len(requests) >= 1
        assert any(r.request_id == request.request_id for r in requests)
    
    def test_get_spawn_request(self, temp_request_dir, sample_receipt):
        """测试 get_spawn_request"""
        # 重新加载模块以使用新的环境变量
        import importlib
        import sessions_spawn_request as ssr
        importlib.reload(ssr)
        
        kernel = ssr.SpawnRequestKernel()
        request = kernel.emit_request(sample_receipt)
        
        # 获取 request
        retrieved = ssr.get_spawn_request(request.request_id)
        assert retrieved is not None
        assert retrieved.request_id == request.request_id
        
        # 获取不存在的 request
        not_found = ssr.get_spawn_request("req_nonexistent")
        assert not_found is None


class TestSessionsSpawnRequestIntegration:
    """集成测试"""
    
    def test_full_pipeline(self, temp_request_dir, sample_receipt):
        """测试完整 pipeline：receipt -> request"""
        # 重新加载模块以使用新的环境变量
        import importlib
        import sessions_spawn_request as ssr
        import completion_receipt as cr
        importlib.reload(cr)
        importlib.reload(ssr)
        
        # 先写入 receipt
        cr.COMPLETION_RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
        receipt_file = cr._completion_receipt_file(sample_receipt.receipt_id)
        with open(receipt_file, "w") as f:
            json.dump(sample_receipt.to_dict(), f)
        
        try:
            # 准备 request
            request = ssr.prepare_spawn_request(sample_receipt.receipt_id)
            
            assert request is not None
            assert request.spawn_request_status == "prepared"
            assert request.source_receipt_id == sample_receipt.receipt_id
            
            # 验证 sessions_spawn params
            params = request.sessions_spawn_params
            assert params["runtime"] == "subagent"
            assert "metadata" in params
            assert params["metadata"]["dispatch_id"] == sample_receipt.source_dispatch_id
        finally:
            # 清理
            receipt_file.unlink()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
