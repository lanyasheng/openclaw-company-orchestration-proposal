#!/usr/bin/env python3
"""
test_callback_auto_close.py — Tests for Universal Partial-Completion Continuation Framework v6

测试 callback_auto_close 模块（通用 callback auto-close bridge）。

覆盖：
- receipt 后生成 auto-close artifact
- linkage 包含所有关键 ID
- closed / pending / blocked / partial 状态
- 通用 kernel（不绑定 trading）
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from datetime import datetime

import pytest

# 添加 orchestrator 到路径
ORCHESTRATOR_PATH = Path(__file__).parent.parent.parent / "runtime" / "orchestrator"
sys.path.insert(0, str(ORCHESTRATOR_PATH))

from callback_auto_close import (
    CallbackAutoCloseArtifact,
    CallbackCloseKernel,
    create_auto_close,
    list_auto_closes,
    get_auto_close,
    find_close_by_linkage,
    build_close_summary,
    CLOSE_VERSION,
    CALLBACK_CLOSE_DIR,
    CLOSE_LINKAGE_INDEX,
    _load_linkage_index,
)

from completion_receipt import (
    CompletionReceiptArtifact,
    ReceiptStatus,
    COMPLETION_RECEIPT_DIR,
    _completion_receipt_file,
)

from sessions_spawn_request import (
    SessionsSpawnRequest,
    SpawnRequestStatus,
    SPAWN_REQUEST_DIR,
    _spawn_request_file,
)


@pytest.fixture
def temp_close_dir(tmp_path):
    """临时 close 目录"""
    close_dir = tmp_path / "callback_closes"
    close_dir.mkdir()
    
    # 临时覆盖环境变量
    old_env = os.environ.get("OPENCLAW_CALLBACK_CLOSE_DIR")
    os.environ["OPENCLAW_CALLBACK_CLOSE_DIR"] = str(close_dir)
    
    yield close_dir
    
    # 恢复
    if old_env:
        os.environ["OPENCLAW_CALLBACK_CLOSE_DIR"] = old_env
    else:
        os.environ.pop("OPENCLAW_CALLBACK_CLOSE_DIR", None)


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
def sample_request(sample_receipt) -> SessionsSpawnRequest:
    """样本 spawn request（与 sample_receipt 关联）"""
    return SessionsSpawnRequest(
        request_id=f"req_{sample_receipt.receipt_id.split('_')[1]}",
        source_receipt_id=sample_receipt.receipt_id,
        source_execution_id=sample_receipt.source_spawn_execution_id,
        source_spawn_id=sample_receipt.source_spawn_id,
        source_dispatch_id=sample_receipt.source_dispatch_id,
        source_registration_id=sample_receipt.source_registration_id,
        source_task_id=sample_receipt.source_task_id,
        spawn_request_status="prepared",
        spawn_request_reason="Policy evaluation passed",
        spawn_request_time=datetime.now().isoformat(),
        sessions_spawn_params={"runtime": "subagent"},
        dedupe_key=f"dedupe_{sample_receipt.receipt_id.split('_')[1]}",
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


class TestCallbackAutoCloseArtifact:
    """测试 CallbackAutoCloseArtifact 数据类"""
    
    def test_create_close(self, sample_receipt):
        """测试创建 close"""
        close = CallbackAutoCloseArtifact(
            close_id="close_test123",
            source_receipt_id=sample_receipt.receipt_id,
            source_execution_id=sample_receipt.source_spawn_execution_id,
            source_spawn_id=sample_receipt.source_spawn_id,
            source_dispatch_id=sample_receipt.source_dispatch_id,
            source_registration_id=sample_receipt.source_registration_id,
            source_task_id=sample_receipt.source_task_id,
            close_status="closed",
            close_reason="Full close",
            close_time=datetime.now().isoformat(),
            linkage={
                "dispatch_id": sample_receipt.source_dispatch_id,
                "spawn_id": sample_receipt.source_spawn_id,
                "execution_id": sample_receipt.source_spawn_execution_id,
                "receipt_id": sample_receipt.receipt_id,
            },
            close_summary="Test close summary",
        )
        
        assert close.close_id == "close_test123"
        assert close.close_status == "closed"
        assert len(close.linkage) == 4
    
    def test_to_dict(self, sample_receipt):
        """测试 to_dict 序列化"""
        close = CallbackAutoCloseArtifact(
            close_id="close_test123",
            source_receipt_id=sample_receipt.receipt_id,
            source_execution_id=sample_receipt.source_spawn_execution_id,
            source_spawn_id=sample_receipt.source_spawn_id,
            source_dispatch_id=sample_receipt.source_dispatch_id,
            source_registration_id=sample_receipt.source_registration_id,
            source_task_id=sample_receipt.source_task_id,
            close_status="closed",
            close_reason="Full close",
            close_time=datetime.now().isoformat(),
            linkage={"dispatch_id": "d1"},
            close_summary="Summary",
        )
        
        data = close.to_dict()
        assert data["close_version"] == CLOSE_VERSION
        assert data["close_id"] == "close_test123"
        assert data["close_status"] == "closed"
    
    def test_from_dict(self, sample_receipt):
        """测试 from_dict 反序列化"""
        data = {
            "close_version": CLOSE_VERSION,
            "close_id": "close_test123",
            "source_receipt_id": sample_receipt.receipt_id,
            "source_execution_id": sample_receipt.source_spawn_execution_id,
            "source_spawn_id": sample_receipt.source_spawn_id,
            "source_dispatch_id": sample_receipt.source_dispatch_id,
            "source_registration_id": sample_receipt.source_registration_id,
            "source_task_id": sample_receipt.source_task_id,
            "close_status": "closed",
            "close_reason": "Full close",
            "close_time": datetime.now().isoformat(),
            "linkage": {"dispatch_id": "d1"},
            "close_summary": "Summary",
        }
        
        close = CallbackAutoCloseArtifact.from_dict(data)
        assert close.close_id == "close_test123"
        assert close.close_status == "closed"


class TestCallbackCloseKernel:
    """测试 CallbackCloseKernel"""
    
    def test_determine_close_status_closed_with_request(self, sample_receipt):
        """测试 close status: closed（有 request）"""
        kernel = CallbackCloseKernel()
        status, reason = kernel._determine_close_status("completed", "prepared")
        
        assert status == "closed"
        assert "full close" in reason.lower()
    
    def test_determine_close_status_partial_no_request(self, sample_receipt):
        """测试 close status: partial（无 request）"""
        kernel = CallbackCloseKernel()
        status, reason = kernel._determine_close_status("completed", None)
        
        assert status == "partial"
        assert "partial" in reason.lower()
    
    def test_determine_close_status_blocked(self, sample_receipt):
        """测试 close status: blocked"""
        kernel = CallbackCloseKernel()
        status, reason = kernel._determine_close_status("failed", None)
        
        assert status == "blocked"
        assert "failed" in reason.lower()
    
    def test_build_linkage(self, sample_receipt):
        """测试构建 linkage"""
        kernel = CallbackCloseKernel()
        linkage = kernel._build_linkage(
            receipt_id=sample_receipt.receipt_id,
            execution_id=sample_receipt.source_spawn_execution_id,
            spawn_id=sample_receipt.source_spawn_id,
            dispatch_id=sample_receipt.source_dispatch_id,
            registration_id=sample_receipt.source_registration_id,
            request_id="req_test123",
        )
        
        assert linkage["dispatch_id"] == sample_receipt.source_dispatch_id
        assert linkage["spawn_id"] == sample_receipt.source_spawn_id
        assert linkage["execution_id"] == sample_receipt.source_spawn_execution_id
        assert linkage["receipt_id"] == sample_receipt.receipt_id
        assert linkage["request_id"] == "req_test123"
    
    def test_build_close_summary(self, sample_receipt):
        """测试构建 close summary"""
        kernel = CallbackCloseKernel()
        summary = kernel._build_close_summary(
            task_id=sample_receipt.source_task_id,
            scenario="test_scenario",
            close_status="closed",
            request_status="prepared",
        )
        
        assert sample_receipt.source_task_id in summary
        assert "test_scenario" in summary
        assert "closed" in summary.lower()
    
    def test_create_close_with_request(self, temp_close_dir, sample_receipt, sample_request):
        """测试创建 close（有 request）"""
        # 重新加载模块以使用新的环境变量
        import importlib
        import callback_auto_close as cac
        import completion_receipt as cr
        import sessions_spawn_request as ssr
        importlib.reload(cr)
        importlib.reload(ssr)
        importlib.reload(cac)
        
        # 先写入 receipt
        cr.COMPLETION_RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
        receipt_file = cr._completion_receipt_file(sample_receipt.receipt_id)
        with open(receipt_file, "w") as f:
            json.dump(sample_receipt.to_dict(), f)
        
        # 写入 request（这样 get_spawn_request 才能找到）
        ssr.SPAWN_REQUEST_DIR.mkdir(parents=True, exist_ok=True)
        request_file = ssr._spawn_request_file(sample_request.request_id)
        with open(request_file, "w") as f:
            json.dump(sample_request.to_dict(), f)
        
        try:
            kernel = cac.CallbackCloseKernel()
            close = kernel.create_close(sample_receipt.receipt_id, sample_request.request_id)
            
            assert close.close_status == "closed"
            assert close.source_request_id == sample_request.request_id
            assert len(close.linkage) >= 5  # 包含 request_id
            assert "closed" in close.close_summary.lower()
        finally:
            receipt_file.unlink()
            request_file.unlink()
    
    def test_create_close_without_request(self, temp_close_dir, sample_receipt):
        """测试创建 close（无 request）"""
        # 先写入 receipt
        COMPLETION_RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
        receipt_file = _completion_receipt_file(sample_receipt.receipt_id)
        with open(receipt_file, "w") as f:
            json.dump(sample_receipt.to_dict(), f)
        
        try:
            kernel = CallbackCloseKernel()
            close = kernel.create_close(sample_receipt.receipt_id, None)
            
            assert close.close_status == "partial"
            assert close.source_request_id is None
            assert "partially closed" in close.close_summary.lower() or "partial" in close.close_summary.lower()
        finally:
            receipt_file.unlink()
    
    def test_emit_close_writes_file(self, temp_close_dir, sample_receipt):
        """测试 emit close 写入文件"""
        # 重新加载模块以使用新的环境变量
        import importlib
        import callback_auto_close as cac
        import completion_receipt as cr
        importlib.reload(cr)
        importlib.reload(cac)
        
        # 先写入 receipt
        cr.COMPLETION_RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
        receipt_file = cr._completion_receipt_file(sample_receipt.receipt_id)
        with open(receipt_file, "w") as f:
            json.dump(sample_receipt.to_dict(), f)
        
        try:
            kernel = cac.CallbackCloseKernel()
            close = kernel.emit_close(sample_receipt.receipt_id)
            
            # 检查文件是否存在（使用重新加载后的模块路径）
            close_file = cac._callback_close_file(close.close_id)
            assert close_file.exists()
            
            # 检查内容
            with open(close_file) as f:
                data = json.load(f)
            assert data["close_id"] == close.close_id
        finally:
            receipt_file.unlink()
    
    def test_emit_close_records_linkage(self, temp_close_dir, sample_receipt):
        """测试 emit close 记录 linkage"""
        # 先写入 receipt
        COMPLETION_RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
        receipt_file = _completion_receipt_file(sample_receipt.receipt_id)
        with open(receipt_file, "w") as f:
            json.dump(sample_receipt.to_dict(), f)
        
        try:
            kernel = CallbackCloseKernel()
            close = kernel.emit_close(sample_receipt.receipt_id)
            
            # 检查 index 文件
            index = _load_linkage_index()
            
            # 检查各个 linkage key
            assert f"by_receipt:{sample_receipt.receipt_id}" in index
            assert f"by_execution:{sample_receipt.source_spawn_execution_id}" in index
            assert f"by_spawn:{sample_receipt.source_spawn_id}" in index
            assert f"by_dispatch:{sample_receipt.source_dispatch_id}" in index
        finally:
            receipt_file.unlink()


class TestConvenienceFunctions:
    """测试便利函数"""
    
    def test_create_auto_close(self, temp_close_dir, sample_receipt):
        """测试 create_auto_close"""
        # 先写入 receipt
        COMPLETION_RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
        receipt_file = _completion_receipt_file(sample_receipt.receipt_id)
        with open(receipt_file, "w") as f:
            json.dump(sample_receipt.to_dict(), f)
        
        try:
            close = create_auto_close(sample_receipt.receipt_id)
            assert close is not None
            assert close.close_status in ["closed", "partial"]
        finally:
            receipt_file.unlink()
    
    def test_list_auto_closes(self, temp_close_dir, sample_receipt):
        """测试 list_auto_closes"""
        # 先写入 receipt
        COMPLETION_RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
        receipt_file = _completion_receipt_file(sample_receipt.receipt_id)
        with open(receipt_file, "w") as f:
            json.dump(sample_receipt.to_dict(), f)
        
        try:
            # 创建 close
            close = create_auto_close(sample_receipt.receipt_id)
            
            # 列出所有 closes
            closes = list_auto_closes()
            assert len(closes) >= 1
            
            # 按 receipt_id 过滤
            closes = list_auto_closes(receipt_id=sample_receipt.receipt_id)
            assert len(closes) >= 1
            assert any(c.close_id == close.close_id for c in closes)
        finally:
            receipt_file.unlink()
    
    def test_get_auto_close(self, temp_close_dir, sample_receipt):
        """测试 get_auto_close"""
        # 先写入 receipt
        COMPLETION_RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
        receipt_file = _completion_receipt_file(sample_receipt.receipt_id)
        with open(receipt_file, "w") as f:
            json.dump(sample_receipt.to_dict(), f)
        
        try:
            close = create_auto_close(sample_receipt.receipt_id)
            
            # 获取 close
            retrieved = get_auto_close(close.close_id)
            assert retrieved is not None
            assert retrieved.close_id == close.close_id
            
            # 获取不存在的 close
            not_found = get_auto_close("close_nonexistent")
            assert not_found is None
        finally:
            receipt_file.unlink()
    
    def test_find_close_by_linkage(self, temp_close_dir, sample_receipt):
        """测试 find_close_by_linkage"""
        # 先写入 receipt
        COMPLETION_RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
        receipt_file = _completion_receipt_file(sample_receipt.receipt_id)
        with open(receipt_file, "w") as f:
            json.dump(sample_receipt.to_dict(), f)
        
        try:
            close = create_auto_close(sample_receipt.receipt_id)
            
            # 按 receipt_id 查找
            found = find_close_by_linkage(receipt_id=sample_receipt.receipt_id)
            assert found is not None
            assert found.close_id == close.close_id
            
            # 按 dispatch_id 查找
            found = find_close_by_linkage(dispatch_id=sample_receipt.source_dispatch_id)
            assert found is not None
        finally:
            receipt_file.unlink()
    
    def test_build_close_summary(self, temp_close_dir, sample_receipt):
        """测试 build_close_summary"""
        # 先写入 receipt
        COMPLETION_RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
        receipt_file = _completion_receipt_file(sample_receipt.receipt_id)
        with open(receipt_file, "w") as f:
            json.dump(sample_receipt.to_dict(), f)
        
        try:
            close = create_auto_close(sample_receipt.receipt_id)
            
            summary = build_close_summary()
            assert "total_closes" in summary
            assert "by_status" in summary
            assert "recent_closes" in summary
            assert summary["total_closes"] >= 1
        finally:
            receipt_file.unlink()


class TestCallbackAutoCloseIntegration:
    """集成测试"""
    
    def test_full_close_pipeline(self, temp_close_dir, sample_receipt):
        """测试完整 pipeline：receipt -> close"""
        # 先写入 receipt
        COMPLETION_RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
        receipt_file = _completion_receipt_file(sample_receipt.receipt_id)
        with open(receipt_file, "w") as f:
            json.dump(sample_receipt.to_dict(), f)
        
        try:
            # 创建 close
            close = create_auto_close(sample_receipt.receipt_id)
            
            assert close is not None
            assert close.source_receipt_id == sample_receipt.receipt_id
            assert close.close_status in ["closed", "partial"]
            
            # 验证 linkage
            assert close.linkage["dispatch_id"] == sample_receipt.source_dispatch_id
            assert close.linkage["spawn_id"] == sample_receipt.source_spawn_id
            assert close.linkage["execution_id"] == sample_receipt.source_spawn_execution_id
            assert close.linkage["receipt_id"] == sample_receipt.receipt_id
            
            # 验证 metadata
            assert close.metadata["scenario"] == "test_scenario"
        finally:
            receipt_file.unlink()
    
    def test_close_with_blocked_receipt(self, temp_close_dir, sample_receipt_failed):
        """测试 blocked receipt 的 close"""
        # 重新加载模块以使用新的环境变量
        import importlib
        import callback_auto_close as cac
        import completion_receipt as cr
        importlib.reload(cr)
        importlib.reload(cac)
        
        # 先写入 receipt
        cr.COMPLETION_RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
        receipt_file = cr._completion_receipt_file(sample_receipt_failed.receipt_id)
        with open(receipt_file, "w") as f:
            json.dump(sample_receipt_failed.to_dict(), f)
        
        try:
            close = cac.create_auto_close(sample_receipt_failed.receipt_id)
            
            assert close.close_status == "blocked"
            assert "blocked" in close.close_status or "failed" in close.close_reason.lower()
        finally:
            receipt_file.unlink()


class TestContinuationContractIntegration:
    """测试 P0-1 Batch 5: ContinuationContract 集成"""
    
    def test_build_close_continuation_contract(self):
        """测试 build_close_continuation_contract 函数"""
        from callback_auto_close import build_close_continuation_contract
        
        # Test closed status
        cont = build_close_continuation_contract(
            receipt_status="completed",
            request_status="prepared",
            close_status="closed",
            task_id="task_123",
            scenario="test_scenario",
        )
        
        assert cont.stopped_because == "callback_closed_full_completion"
        assert "ready for operator review" in cont.next_step.lower()
        assert cont.next_owner == "main"
        assert cont.metadata["source"] == "callback_auto_close"
        assert cont.metadata["close_status"] == "closed"
    
    def test_build_close_continuation_contract_partial(self):
        """测试 partial close 的 ContinuationContract"""
        from callback_auto_close import build_close_continuation_contract
        
        cont = build_close_continuation_contract(
            receipt_status="completed",
            request_status=None,
            close_status="partial",
            task_id="task_123",
            scenario="test_scenario",
        )
        
        assert cont.stopped_because == "callback_partial_awaiting_spawn_request"
        assert "awaiting spawn request" in cont.next_step.lower()
    
    def test_build_close_continuation_contract_blocked(self):
        """测试 blocked close 的 ContinuationContract"""
        from callback_auto_close import build_close_continuation_contract
        
        cont = build_close_continuation_contract(
            receipt_status="failed",
            request_status=None,
            close_status="blocked",
            task_id="task_123",
            scenario="test_scenario",
        )
        
        assert "blocked" in cont.stopped_because
        assert "resolve blocker" in cont.next_step.lower()
    
    def test_create_close_includes_continuation_contract(self, temp_close_dir, sample_receipt):
        """测试 create_close 生成的 artifact 包含 ContinuationContract"""
        from callback_auto_close import CallbackCloseKernel
        
        # 先写入 receipt
        COMPLETION_RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
        receipt_file = _completion_receipt_file(sample_receipt.receipt_id)
        with open(receipt_file, "w") as f:
            json.dump(sample_receipt.to_dict(), f)
        
        try:
            kernel = CallbackCloseKernel()
            close = kernel.create_close(sample_receipt.receipt_id)
            
            # 验证 metadata 包含 continuation_contract
            assert "continuation_contract" in close.metadata
            assert "stopped_because" in close.metadata
            assert "next_step" in close.metadata
            assert "next_owner" in close.metadata
            
            # 验证 continuation_contract 结构
            cont_dict = close.metadata["continuation_contract"]
            assert "contract_version" in cont_dict
            assert "stopped_because" in cont_dict
            assert "next_step" in cont_dict
            assert "next_owner" in cont_dict
            
            # 验证值一致
            assert close.metadata["stopped_because"] == cont_dict["stopped_because"]
            assert close.metadata["next_step"] == cont_dict["next_step"]
            assert close.metadata["next_owner"] == cont_dict["next_owner"]
        finally:
            receipt_file.unlink()
    
    def test_close_summary_uses_continuation_contract(self, temp_close_dir, sample_receipt):
        """测试 close summary 使用 ContinuationContract 生成"""
        from callback_auto_close import CallbackCloseKernel
        
        # 先写入 receipt
        COMPLETION_RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
        receipt_file = _completion_receipt_file(sample_receipt.receipt_id)
        with open(receipt_file, "w") as f:
            json.dump(sample_receipt.to_dict(), f)
        
        try:
            kernel = CallbackCloseKernel()
            close = kernel.create_close(sample_receipt.receipt_id)
            
            # 验证 summary 包含 continuation 语义
            assert close.close_summary is not None
            assert len(close.close_summary) > 0
            
            # Summary should use unified format with continuation semantics
            assert close.metadata["stopped_because"] in close.close_summary or \
                   close.metadata["next_step"] in close.close_summary or \
                   close.metadata["next_owner"] in close.close_summary
        finally:
            receipt_file.unlink()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
