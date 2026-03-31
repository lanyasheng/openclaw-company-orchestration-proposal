#!/usr/bin/env python3
"""
test_completion_backwrite.py — Tests for Completion Backwrite Bridge

测试 completion backwrite 模块，验证 ad-hoc trading tasks completion 结果
能自动回写到三个控制面系统：
1. task_registration.status -> completed/blocked/failed
2. state_machine.state -> callback_received/failed
3. observability_card.stage -> callback_received/failed
"""

import json
import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

import pytest

# 添加 orchestrator 目录到 Python 路径
ORCHESTRATOR_DIR = Path(__file__).parent.parent / "orchestrator"
if str(ORCHESTRATOR_DIR) not in sys.path:
    sys.path.insert(0, str(ORCHESTRATOR_DIR))

# 设置测试环境变量（隔离测试）
TEST_DIR = Path(tempfile.mkdtemp(prefix="test_backwrite_"))
os.environ["OPENCLAW_STATE_DIR"] = str(TEST_DIR / "state")
os.environ["OPENCLAW_REGISTRY_DIR"] = str(TEST_DIR / "registry")
os.environ["OPENCLAW_OBSERVABILITY_DIR"] = str(TEST_DIR / "observability")
os.environ["OPENCLAW_COMPLETION_RECEIPT_DIR"] = str(TEST_DIR / "receipts")
os.environ["OPENCLAW_SPAWN_EXECUTION_DIR"] = str(TEST_DIR / "executions")
os.environ["OPENCLAW_DISPATCH_DIR"] = str(TEST_DIR / "dispatches")
os.environ["OPENCLAW_SPAWN_REQUEST_DIR"] = str(TEST_DIR / "spawn_requests")


from completion_receipt import (
    CompletionReceiptArtifact,
    CompletionReceiptKernel,
    ReceiptStatus,
)
from completion_backwrite import (
    backwrite_completion,
    backwrite_to_task_registration,
    backwrite_to_state_machine,
    backwrite_to_observability_card,
    BackwriteResult,
)
from task_registration import TaskRegistry, register_task, get_registration
from state_machine import get_state, create_task, TaskState
from observability_card import get_card, ObservabilityCardManager


@pytest.fixture(scope="module", autouse=True)
def cleanup_test_dir():
    """测试完成后清理临时目录"""
    yield
    if TEST_DIR.exists():
        shutil.rmtree(TEST_DIR, ignore_errors=True)


def _create_test_receipt(
    receipt_status: ReceiptStatus = "completed",
    task_id: str = "test_task_001",
    registration_id: str = "reg_test_001",
) -> CompletionReceiptArtifact:
    """创建测试用的 receipt artifact"""
    return CompletionReceiptArtifact(
        receipt_id=f"receipt_{task_id}",
        source_spawn_execution_id=f"exec_{task_id}",
        source_spawn_id=f"spawn_{task_id}",
        source_dispatch_id=f"dispatch_{task_id}",
        source_registration_id=registration_id,
        source_task_id=task_id,
        receipt_status=receipt_status,
        receipt_reason=f"Test {receipt_status} for task {task_id}",
        receipt_time=datetime.now().isoformat(),
        result_summary=f"Test task {task_id} {receipt_status} successfully",
        dedupe_key=f"dedupe_{task_id}",
        metadata={
            "scenario": "trading_roundtable_phase1",
            "owner": "trading",
            "executor": "subagent",
            "continuation_contract": {
                "next_step": "Test next step",
                "next_owner": "trading",
                "stopped_because": f"Test {receipt_status}",
            },
        },
    )


class TestBackwriteToTaskRegistration:
    """测试回写到 task_registration"""
    
    def test_backwrite_completed_status(self):
        """测试 completed 状态回写"""
        # 创建测试 registration
        record = register_task(
            proposed_task={"test": "task"},
            registration_status="registered",
            registration_reason="Test registration",
            ready_for_auto_dispatch=True,
        )
        
        # 执行 backwrite
        result = backwrite_to_task_registration(
            registration_id=record.registration_id,
            task_id=record.task_id,
            receipt_status="completed",
            result_summary="Task completed successfully",
        )
        
        # 验证
        assert result is True
        updated_record = get_registration(record.registration_id)
        assert updated_record is not None
        assert updated_record.status == "completed"
        assert updated_record.metadata.get("completion_receipt_status") == "completed"
    
    def test_backwrite_failed_status(self):
        """测试 failed 状态回写"""
        record = register_task(
            proposed_task={"test": "task"},
            registration_status="registered",
            registration_reason="Test registration",
        )
        
        result = backwrite_to_task_registration(
            registration_id=record.registration_id,
            task_id=record.task_id,
            receipt_status="failed",
            result_summary="Task failed",
        )
        
        assert result is True
        updated_record = get_registration(record.registration_id)
        assert updated_record is not None
        assert updated_record.status == "failed"
    
    def test_backwrite_missing_registration(self):
        """测试 registration 不存在时的处理"""
        result = backwrite_to_task_registration(
            registration_id="nonexistent_reg",
            task_id="nonexistent_task",
            receipt_status="completed",
            result_summary="Test",
        )
        
        assert result is False


class TestBackwriteToStateMachine:
    """测试回写到 state_machine"""
    
    def test_backwrite_completed_state(self):
        """测试 completed 状态回写"""
        task_id = "test_sm_completed_001"
        
        # 先创建 state_machine 记录
        create_task(task_id, timeout_seconds=3600)
        
        # 执行 backwrite
        result = backwrite_to_state_machine(
            task_id=task_id,
            receipt_status="completed",
            result={"receipt_id": "test_receipt", "receipt_status": "completed"},
        )
        
        # 验证
        assert result is True
        state = get_state(task_id)
        assert state is not None
        assert state["state"] == "callback_received"
        assert state["callback_received_at"] is not None
    
    def test_backwrite_failed_state(self):
        """测试 failed 状态回写"""
        task_id = "test_sm_failed_001"
        
        create_task(task_id, timeout_seconds=3600)
        
        result = backwrite_to_state_machine(
            task_id=task_id,
            receipt_status="failed",
            result={"receipt_reason": "Test failure"},
        )
        
        assert result is True
        state = get_state(task_id)
        assert state is not None
        assert state["state"] == "failed"
    
    def test_backwrite_creates_if_missing(self):
        """测试 state_machine 记录不存在时自动创建"""
        task_id = "test_sm_auto_create_001"
        
        # 不预先创建，直接 backwrite
        result = backwrite_to_state_machine(
            task_id=task_id,
            receipt_status="completed",
            result={"receipt_id": "test_receipt"},
        )
        
        # 应该自动创建并更新
        assert result is True
        state = get_state(task_id)
        assert state is not None


class TestBackwriteToObservabilityCard:
    """测试回写到 observability_card"""
    
    def test_backwrite_completed_card(self):
        """测试 completed 状态回写"""
        task_id = "test_obs_completed_001"
        
        # 先创建卡片
        manager = ObservabilityCardManager()
        manager.create_card(
            task_id=task_id,
            scenario="custom",
            owner="test",
            executor="subagent",
            stage="dispatch",
            promised_eta=datetime.now().isoformat(),
            anchor_type="test",
            anchor_value="test",
        )
        
        # 执行 backwrite
        result = backwrite_to_observability_card(
            task_id=task_id,
            receipt_status="completed",
            result_summary="Task completed",
            metadata={"scenario": "custom", "owner": "test"},
        )
        
        # 验证
        assert result is True
        card = get_card(task_id)
        assert card is not None
        assert card.stage == "callback_received"
        assert card.metadata.get("completion_receipt_status") == "completed"
    
    def test_backwrite_failed_card(self):
        """测试 failed 状态回写"""
        task_id = "test_obs_failed_001"
        
        manager = ObservabilityCardManager()
        manager.create_card(
            task_id=task_id,
            scenario="custom",
            owner="test",
            executor="subagent",
            stage="running",
            promised_eta=datetime.now().isoformat(),
            anchor_type="test",
            anchor_value="test",
        )
        
        result = backwrite_to_observability_card(
            task_id=task_id,
            receipt_status="failed",
            result_summary="Task failed",
            metadata={"scenario": "custom", "owner": "test"},
        )
        
        assert result is True
        card = get_card(task_id)
        assert card is not None
        assert card.stage == "failed"
    
    def test_backwrite_creates_card_if_missing(self):
        """测试卡片不存在时自动创建"""
        task_id = "test_obs_auto_create_001"
        
        # 不预先创建，直接 backwrite
        result = backwrite_to_observability_card(
            task_id=task_id,
            receipt_status="completed",
            result_summary="Test",
            metadata={
                "scenario": "custom",
                "owner": "test",
                "executor": "subagent",
                "promised_eta": datetime.now().isoformat(),
                "receipt_id": "test_receipt",
            },
        )
        
        # 应该自动创建
        assert result is True
        card = get_card(task_id)
        assert card is not None
        assert card.stage == "callback_received"


class TestBackwriteCompletion:
    """测试完整的 backwrite_completion 函数"""
    
    def test_full_backwrite_completed(self):
        """测试完整的 completed backwrite 流程"""
        # 创建 registration
        record = register_task(
            proposed_task={"test": "task"},
            registration_status="registered",
            registration_reason="Test",
        )
        
        # 创建 receipt
        receipt = _create_test_receipt(
            receipt_status="completed",
            task_id=record.task_id,
            registration_id=record.registration_id,
        )
        
        # 执行完整 backwrite
        result = backwrite_completion(receipt=receipt)
        
        # 验证三个系统都被更新
        assert result.task_registration_updated is True
        assert result.state_machine_updated is True
        assert result.observability_card_updated is True
        assert len(result.errors) == 0
        
        # 验证具体状态
        updated_record = get_registration(record.registration_id)
        assert updated_record.status == "completed"
        
        state = get_state(record.task_id)
        assert state["state"] == "callback_received"
        
        card = get_card(record.task_id)
        assert card.stage == "callback_received"
    
    def test_full_backwrite_failed(self):
        """测试完整的 failed backwrite 流程"""
        record = register_task(
            proposed_task={"test": "task"},
            registration_status="registered",
            registration_reason="Test",
        )
        
        receipt = _create_test_receipt(
            receipt_status="failed",
            task_id=record.task_id,
            registration_id=record.registration_id,
        )
        
        result = backwrite_completion(receipt=receipt)
        
        # 验证三个系统都被更新
        assert result.task_registration_updated is True
        assert result.state_machine_updated is True
        assert result.observability_card_updated is True
        
        # 验证具体状态
        updated_record = get_registration(record.registration_id)
        assert updated_record.status == "failed"
        
        state = get_state(record.task_id)
        assert state["state"] == "failed"
        
        card = get_card(record.task_id)
        assert card.stage == "failed"
    
    def test_backwrite_missing_registration_id(self):
        """测试缺少 registration_id 时的处理"""
        receipt = _create_test_receipt(
            receipt_status="completed",
            task_id="test_no_reg",
            registration_id="",  # 空的 registration_id
        )
        
        result = backwrite_completion(receipt=receipt)
        
        # task_registration 应该失败，但其他两个应该成功
        assert result.task_registration_updated is False
        assert result.state_machine_updated is True
        assert result.observability_card_updated is True
        assert any("registration_id" in err for err in result.errors)


class TestBackwriteResult:
    """测试 BackwriteResult 数据类"""
    
    def test_to_dict(self):
        """测试 to_dict 方法"""
        result = BackwriteResult(
            task_registration_updated=True,
            state_machine_updated=True,
            observability_card_updated=False,
            errors=["Test error"],
            metadata={"test": "value"},
        )
        
        result_dict = result.to_dict()
        
        assert result_dict["task_registration_updated"] is True
        assert result_dict["state_machine_updated"] is True
        assert result_dict["observability_card_updated"] is False
        assert result_dict["errors"] == ["Test error"]
        assert result_dict["metadata"]["test"] == "value"
        assert result_dict["success"] is True  # 至少有一个成功
    
    def test_success_all_failed(self):
        """测试全部失败时的 success 字段"""
        result = BackwriteResult(
            task_registration_updated=False,
            state_machine_updated=False,
            observability_card_updated=False,
        )
        
        assert result.to_dict()["success"] is False


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
