#!/usr/bin/env python3
"""
test_completion_receipt_continuation.py — P0-1 Batch 5

测试 ContinuationContract 在 completion_receipt 中的集成。

覆盖：
- build_receipt_continuation_contract 函数
- CompletionReceiptKernel.create_receipt 包含 ContinuationContract
- receipt metadata 包含 continuation 语义
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

from completion_receipt import (
    CompletionReceiptArtifact,
    CompletionReceiptKernel,
    build_receipt_continuation_contract,
    RECEIPT_VERSION,
    COMPLETION_RECEIPT_DIR,
    _completion_receipt_file,
)

from spawn_execution import (
    SpawnExecutionArtifact,
    SPAWN_EXECUTION_DIR,
)


@pytest.fixture
def temp_receipt_dir(tmp_path):
    """临时 receipt 目录"""
    receipt_dir = tmp_path / "completion_receipts"
    receipt_dir.mkdir()
    
    # 临时覆盖环境变量
    old_env = os.environ.get("OPENCLAW_COMPLETION_RECEIPT_DIR")
    os.environ["OPENCLAW_COMPLETION_RECEIPT_DIR"] = str(receipt_dir)
    
    yield receipt_dir
    
    # 恢复
    if old_env:
        os.environ["OPENCLAW_COMPLETION_RECEIPT_DIR"] = old_env
    else:
        os.environ.pop("OPENCLAW_COMPLETION_RECEIPT_DIR", None)


@pytest.fixture
def sample_spawn_execution() -> SpawnExecutionArtifact:
    """样本 spawn execution"""
    return SpawnExecutionArtifact(
        execution_id="exec_test_001",
        spawn_id="spawn_test_001",
        dispatch_id="dispatch_test_001",
        registration_id="reg_test_001",
        task_id="task_test_001",
        spawn_execution_status="started",
        spawn_execution_reason="Execution started successfully",
        spawn_execution_time=datetime.now().isoformat(),
        spawn_execution_target={
            "scenario": "test_scenario",
            "owner": "test_owner",
            "next_step": "Continue with next phase",
        },
        dedupe_key="dedupe_exec_test_001",
        execution_payload={
            "metadata": {
                "test": "data",
            },
        },
        execution_result={
            "execution_mode": "simulated",
            "ready_for_downstream": True,
        },
        metadata={
            "source_spawn_status": "emitted",
            "truth_anchor": "test_anchor",
        },
    )


class TestBuildReceiptContinuationContract:
    """测试 build_receipt_continuation_contract 函数"""
    
    def test_build_continuation_contract_completed(self, sample_spawn_execution):
        """测试 completed receipt 的 ContinuationContract"""
        cont = build_receipt_continuation_contract(
            execution=sample_spawn_execution,
            receipt_status="completed",
            receipt_reason="Execution completed successfully",
        )
        
        assert cont.stopped_because == "receipt_completed"
        # next_step comes from execution metadata if available, otherwise derived
        assert cont.next_step == "Continue with next phase"  # From sample_spawn_execution
        assert cont.next_owner == "test_owner"
        assert cont.metadata["source"] == "completion_receipt"
        assert cont.metadata["receipt_status"] == "completed"
        assert cont.metadata["execution_id"] == "exec_test_001"
    
    def test_build_continuation_contract_failed(self, sample_spawn_execution):
        """测试 failed receipt 的 ContinuationContract"""
        cont = build_receipt_continuation_contract(
            execution=sample_spawn_execution,
            receipt_status="failed",
            receipt_reason="Execution failed due to timeout",
        )
        
        assert "receipt_failed" in cont.stopped_because
        # next_step comes from execution metadata if available
        assert cont.next_step == "Continue with next phase"
        assert cont.next_owner == "test_owner"
        assert cont.metadata["receipt_status"] == "failed"
    
    def test_build_continuation_contract_missing(self, sample_spawn_execution):
        """测试 missing receipt 的 ContinuationContract"""
        cont = build_receipt_continuation_contract(
            execution=sample_spawn_execution,
            receipt_status="missing",
            receipt_reason="Execution was skipped",
        )
        
        assert "receipt_missing" in cont.stopped_because
        # next_step comes from execution metadata if available
        assert cont.next_step == "Continue with next phase"
    
    def test_build_continuation_contract_default_next_step(self):
        """测试没有 next_step 时使用默认值"""
        execution = SpawnExecutionArtifact(
            execution_id="exec_test_002",
            spawn_id="spawn_test_002",
            dispatch_id="dispatch_test_002",
            registration_id="reg_test_002",
            task_id="task_test_002",
            spawn_execution_status="started",
            spawn_execution_reason="Test",
            spawn_execution_time=datetime.now().isoformat(),
            spawn_execution_target={
                "scenario": "test",
                "owner": "main",
                # No next_step
            },
            dedupe_key="dedupe_exec_test_002",
            metadata={},
        )
        
        cont = build_receipt_continuation_contract(
            execution=execution,
            receipt_status="completed",
            receipt_reason="Test completed",
        )
        
        assert cont.next_owner == "main"
        assert cont.next_step is not None
        assert len(cont.next_step) > 0


class TestCompletionReceiptKernelContinuation:
    """测试 CompletionReceiptKernel 中的 ContinuationContract 集成"""
    
    def test_create_receipt_includes_continuation_contract(self, temp_receipt_dir, sample_spawn_execution):
        """测试 create_receipt 生成的 receipt 包含 ContinuationContract"""
        kernel = CompletionReceiptKernel()
        receipt = kernel.create_receipt(sample_spawn_execution)
        
        # 验证 metadata 包含 continuation_contract
        assert "continuation_contract" in receipt.metadata
        assert "stopped_because" in receipt.metadata
        assert "next_step" in receipt.metadata
        assert "next_owner" in receipt.metadata
        
        # 验证 continuation_contract 结构
        cont_dict = receipt.metadata["continuation_contract"]
        assert "contract_version" in cont_dict
        assert "stopped_because" in cont_dict
        assert "next_step" in cont_dict
        assert "next_owner" in cont_dict
        
        # 验证值一致
        assert receipt.metadata["stopped_because"] == cont_dict["stopped_because"]
        assert receipt.metadata["next_step"] == cont_dict["next_step"]
        assert receipt.metadata["next_owner"] == cont_dict["next_owner"]
    
    def test_emit_receipt_includes_continuation_contract(self, temp_receipt_dir, sample_spawn_execution):
        """测试 emit_receipt 写入的 receipt 包含 ContinuationContract"""
        kernel = CompletionReceiptKernel()
        receipt = kernel.emit_receipt(sample_spawn_execution)
        
        # 验证 receipt 已写入文件
        receipt_file = _completion_receipt_file(receipt.receipt_id)
        assert receipt_file.exists()
        
        # 读取文件验证
        with open(receipt_file, "r") as f:
            data = json.load(f)
        
        assert "metadata" in data
        assert "continuation_contract" in data["metadata"]
        assert "stopped_because" in data["metadata"]
    
    def test_receipt_continuation_contract_roundtrip(self, temp_receipt_dir, sample_spawn_execution):
        """测试 ContinuationContract 在 receipt 序列化/反序列化中的完整性"""
        kernel = CompletionReceiptKernel()
        receipt = kernel.emit_receipt(sample_spawn_execution)
        
        # 序列化
        data = receipt.to_dict()
        
        # 反序列化
        receipt2 = CompletionReceiptArtifact.from_dict(data)
        
        # 验证 ContinuationContract 保持一致
        assert receipt2.metadata["continuation_contract"] == receipt.metadata["continuation_contract"]
        assert receipt2.metadata["stopped_because"] == receipt.metadata["stopped_because"]
        assert receipt2.metadata["next_step"] == receipt.metadata["next_step"]
        assert receipt2.metadata["next_owner"] == receipt.metadata["next_owner"]


class TestBackwardCompatibility:
    """测试向后兼容性"""
    
    def test_receipt_without_continuation_contract_still_works(self):
        """测试没有 continuation_contract 的 receipt 仍然可以反序列化"""
        # 模拟旧版本 receipt 数据（没有 continuation_contract）
        old_data = {
            "receipt_version": RECEIPT_VERSION,
            "receipt_id": "receipt_old_001",
            "source_spawn_execution_id": "exec_old_001",
            "source_spawn_id": "spawn_old_001",
            "source_dispatch_id": "dispatch_old_001",
            "source_registration_id": "reg_old_001",
            "source_task_id": "task_old_001",
            "receipt_status": "completed",
            "receipt_reason": "Old receipt",
            "receipt_time": datetime.now().isoformat(),
            "result_summary": "Old summary",
            "dedupe_key": "dedupe_old_001",
            "metadata": {
                "scenario": "old_scenario",
            },
        }
        
        # 应该可以反序列化
        receipt = CompletionReceiptArtifact.from_dict(old_data)
        assert receipt.receipt_id == "receipt_old_001"
        assert receipt.receipt_status == "completed"
        
        # metadata 可能没有 continuation_contract（旧版本）
        assert "continuation_contract" not in receipt.metadata


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
