#!/usr/bin/env python3
"""
test_push_consumer.py — Tests for P0-4 Final Mile: Push Consumer / Status Backfill

测试 push consumer 和 status backfill 机制，确保：
1. push action 能正确 emit/consume
2. push status 能正确回填
3. 模拟 push 成功用于测试闭环
4. 状态区分清晰（emitted/consumed/executed/failed/blocked）

这是 P0-4 Final Mile 的测试覆盖。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

import pytest

# Add orchestrator to path
ORCHESTRATOR_DIR = Path(__file__).resolve().parents[2] / "orchestrator"
if str(ORCHESTRATOR_DIR) not in sys.path:
    sys.path.insert(0, str(ORCHESTRATOR_DIR))

from closeout_tracker import (
    CloseoutTracker,
    create_closeout,
    get_closeout,
    ContinuationContract,
    # P0-4 Final Mile
    emit_push_action,
    consume_push_action,
    update_push_status,
    simulate_push_success,
    get_push_action,
    check_push_consumer_status,
    CLOSEOUT_DIR,
    _ensure_closeout_dir,
)


@pytest.fixture(autouse=True)
def clean_closeout_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """使用临时 closeout 目录，避免污染真实数据"""
    import importlib
    import closeout_tracker
    
    # 设置临时目录
    CLOSEOUT_DIR = tmp_path / "closeouts"
    CLOSEOUT_DIR.mkdir(parents=True, exist_ok=True)
    closeout_tracker.CLOSEOUT_DIR = CLOSEOUT_DIR
    
    yield
    
    # 清理
    import shutil
    if tmp_path.exists():
        shutil.rmtree(tmp_path)


class TestPushAction:
    """测试 PushAction 数据类"""
    
    def test_push_action_to_dict(self):
        """测试 PushAction 序列化"""
        from closeout_tracker import PushAction
        
        action = PushAction(
            action_id="push_test123",
            batch_id="batch_001",
            closeout_id="closeout_abc",
            status="emitted",
            intent="Test push action",
            metadata={"test": "value"},
        )
        
        d = action.to_dict()
        assert d["action_id"] == "push_test123"
        assert d["batch_id"] == "batch_001"
        assert d["status"] == "emitted"
        assert d["intent"] == "Test push action"
        assert d["metadata"]["test"] == "value"
    
    def test_push_action_from_dict(self):
        """测试 PushAction 反序列化"""
        from closeout_tracker import PushAction
        
        data = {
            "action_id": "push_test456",
            "batch_id": "batch_002",
            "closeout_id": "closeout_def",
            "status": "consumed",
            "intent": "Another test",
            "executed_at": "2026-03-24T12:00:00Z",
            "metadata": {"key": "value"},
        }
        
        action = PushAction.from_dict(data)
        assert action.action_id == "push_test456"
        assert action.status == "consumed"
        assert action.executed_at == "2026-03-24T12:00:00Z"


class TestEmitPushAction:
    """测试 emit_push_action 函数"""
    
    def test_emit_push_action_creates_action(self):
        """测试 emit push action 创建 action 记录"""
        # 先创建 closeout
        continuation = ContinuationContract(
            stopped_because="roundtable_gate_pass",
            next_step="Proceed",
            next_owner="trading",
        )
        
        closeout = create_closeout(
            batch_id="batch_001",
            scenario="trading_roundtable",
            continuation=continuation,
            has_remaining_work=False,
            metadata={"packet": {"overall_gate": "PASS"}},
        )
        
        # Emit push action
        action = emit_push_action(
            batch_id="batch_001",
            closeout_id=closeout.closeout_id,
            intent="Test push for batch_001",
        )
        
        # 验证 action 已创建
        assert action.action_id.startswith("push_")
        assert action.batch_id == "batch_001"
        assert action.closeout_id == closeout.closeout_id
        assert action.status == "emitted"
        assert action.intent == "Test push for batch_001"
        
        # 验证 action 文件已写入
        stored_action = get_push_action("batch_001")
        assert stored_action is not None
        assert stored_action.action_id == action.action_id
        
        # 验证 closeout 已更新 push_action 引用
        updated_closeout = get_closeout("batch_001")
        assert updated_closeout.push_action is not None
        assert updated_closeout.push_action.action_id == action.action_id
    
    def test_emit_push_action_default_intent(self):
        """测试 emit push action 使用默认 intent"""
        continuation = ContinuationContract(
            stopped_because="roundtable_gate_pass",
            next_step="Proceed",
            next_owner="trading",
        )
        
        closeout = create_closeout(
            batch_id="batch_002",
            scenario="trading_roundtable",
            continuation=continuation,
            has_remaining_work=False,
        )
        
        action = emit_push_action(
            batch_id="batch_002",
            closeout_id=closeout.closeout_id,
            # 不提供 intent，使用默认
        )
        
        assert "batch_002" in action.intent
        assert "push" in action.intent.lower()


class TestConsumePushAction:
    """测试 consume_push_action 函数"""
    
    def test_consume_push_action_updates_status(self):
        """测试 consume push action 更新状态"""
        # 创建 closeout 和 push action
        continuation = ContinuationContract(
            stopped_because="roundtable_gate_pass",
            next_step="Proceed",
            next_owner="trading",
        )
        
        closeout = create_closeout(
            batch_id="batch_003",
            scenario="trading_roundtable",
            continuation=continuation,
            has_remaining_work=False,
        )
        
        emit_push_action(batch_id="batch_003", closeout_id=closeout.closeout_id)
        
        # Consume push action
        action = consume_push_action(batch_id="batch_003")
        
        # 验证状态已更新
        assert action.status == "consumed"
        
        # 验证存储的状态
        stored_action = get_push_action("batch_003")
        assert stored_action.status == "consumed"
    
    def test_consume_push_action_fails_if_not_emitted(self):
        """测试 consume push action 在非 emitted 状态下失败"""
        # 创建 closeout 和 push action
        continuation = ContinuationContract(
            stopped_because="roundtable_gate_pass",
            next_step="Proceed",
            next_owner="trading",
        )
        
        closeout = create_closeout(
            batch_id="batch_004",
            scenario="trading_roundtable",
            continuation=continuation,
            has_remaining_work=False,
        )
        
        emit_push_action(batch_id="batch_004", closeout_id=closeout.closeout_id)
        
        # 先手动更新为 consumed（模拟已消费）
        update_push_status(
            batch_id="batch_004",
            new_status="pending",
            push_action_status="consumed",
        )
        
        # 再次 consume 应该失败
        import pytest
        with pytest.raises(ValueError, match="status is consumed"):
            consume_push_action(batch_id="batch_004")
    
    def test_consume_push_action_fails_if_not_exists(self):
        """测试 consume push action 在不存在时失败"""
        import pytest
        with pytest.raises(ValueError, match="not found"):
            consume_push_action(batch_id="batch_nonexistent")


class TestUpdatePushStatus:
    """测试 update_push_status 函数"""
    
    def test_update_push_status_to_pushed(self):
        """测试更新 push status 为 pushed"""
        # 创建 closeout
        continuation = ContinuationContract(
            stopped_because="roundtable_gate_pass",
            next_step="Proceed",
            next_owner="trading",
        )
        
        closeout = create_closeout(
            batch_id="batch_005",
            scenario="trading_roundtable",
            continuation=continuation,
            has_remaining_work=False,
        )
        
        # 初始状态应该是 pending
        assert closeout.push_status == "pending"
        
        # 更新为 pushed
        updated = update_push_status(
            batch_id="batch_005",
            new_status="pushed",
            metadata={"test": "update"},
        )
        
        # 验证状态已更新
        assert updated.push_status == "pushed"
        assert updated.metadata["push_status_new"] == "pushed"
        assert updated.metadata["push_status_old"] == "pending"
        assert updated.metadata["test"] == "update"
        
        # 验证存储的状态
        stored = get_closeout("batch_005")
        assert stored.push_status == "pushed"
    
    def test_update_push_status_with_error(self):
        """测试更新 push status 为 failed（带错误信息）"""
        continuation = ContinuationContract(
            stopped_because="roundtable_gate_pass",
            next_step="Proceed",
            next_owner="trading",
        )
        
        closeout = create_closeout(
            batch_id="batch_006",
            scenario="trading_roundtable",
            continuation=continuation,
            has_remaining_work=False,
        )
        
        updated = update_push_status(
            batch_id="batch_006",
            new_status="failed",
            error="Test error message",
        )
        
        assert updated.push_status == "failed"
        assert updated.metadata["push_error"] == "Test error message"
    
    def test_update_push_status_updates_push_action(self):
        """测试更新 push status 同时更新 push action"""
        # 创建 closeout 和 push action
        continuation = ContinuationContract(
            stopped_because="roundtable_gate_pass",
            next_step="Proceed",
            next_owner="trading",
        )
        
        closeout = create_closeout(
            batch_id="batch_007",
            scenario="trading_roundtable",
            continuation=continuation,
            has_remaining_work=False,
        )
        
        emit_push_action(batch_id="batch_007", closeout_id=closeout.closeout_id)
        consume_push_action(batch_id="batch_007")
        
        # 更新为 pushed
        updated = update_push_status(
            batch_id="batch_007",
            new_status="pushed",
            push_action_status="executed",
        )
        
        # 验证 push action 已更新
        assert updated.push_action is not None
        assert updated.push_action.status == "executed"
        assert updated.push_action.executed_at is not None


class TestSimulatePushSuccess:
    """测试 simulate_push_success 函数"""
    
    def test_simulate_push_success_updates_status(self):
        """测试模拟 push 成功更新状态"""
        # 创建 closeout
        continuation = ContinuationContract(
            stopped_because="roundtable_gate_pass",
            next_step="Proceed",
            next_owner="trading",
        )
        
        closeout = create_closeout(
            batch_id="batch_008",
            scenario="trading_roundtable",
            continuation=continuation,
            has_remaining_work=False,
        )
        
        # 模拟 push 成功
        updated = simulate_push_success(batch_id="batch_008")
        
        # 验证状态已更新
        assert updated.push_status == "pushed"
        assert updated.metadata["simulated"] is True
        assert "simulated_at" in updated.metadata
        assert "simulation_note" in updated.metadata
    
    def test_simulate_push_success_with_push_action(self):
        """测试模拟 push 成功同时更新 push action"""
        # 创建 closeout 和 push action
        continuation = ContinuationContract(
            stopped_because="roundtable_gate_pass",
            next_step="Proceed",
            next_owner="trading",
        )
        
        closeout = create_closeout(
            batch_id="batch_009",
            scenario="trading_roundtable",
            continuation=continuation,
            has_remaining_work=False,
        )
        
        emit_push_action(batch_id="batch_009", closeout_id=closeout.closeout_id)
        consume_push_action(batch_id="batch_009")
        
        # 模拟 push 成功
        updated = simulate_push_success(batch_id="batch_009")
        
        # 验证 push action 已更新
        assert updated.push_action is not None
        assert updated.push_action.status == "executed"
        assert updated.push_action.executed_at is not None
    
    def test_simulate_push_success_fails_if_already_pushed(self):
        """测试模拟 push 成功在已 pushed 状态下失败"""
        # 创建 closeout 并直接设置为 pushed
        continuation = ContinuationContract(
            stopped_because="roundtable_gate_pass",
            next_step="Proceed",
            next_owner="trading",
        )
        
        closeout = create_closeout(
            batch_id="batch_010",
            scenario="trading_roundtable",
            continuation=continuation,
            has_remaining_work=False,
        )
        
        # 先模拟一次成功
        simulate_push_success(batch_id="batch_010")
        
        # 再次模拟应该失败
        import pytest
        with pytest.raises(ValueError, match="Cannot simulate"):
            simulate_push_success(batch_id="batch_010")


class TestCheckPushConsumerStatus:
    """测试 check_push_consumer_status 函数"""
    
    def test_check_status_no_closeout(self):
        """测试没有 closeout 时的状态"""
        result = check_push_consumer_status("batch_nonexistent")
        
        assert result["closeout_status"] == "incomplete"
        assert result["push_required"] is False
        assert result["can_auto_continue"] is True
        assert result["blocker"] is None
    
    def test_check_status_blocked_closeout(self):
        """测试 blocked closeout 的状态"""
        continuation = ContinuationContract(
            stopped_because="roundtable_gate_fail",
            next_step="Fix blocker",
            next_owner="trading",
        )
        
        create_closeout(
            batch_id="batch_011",
            scenario="trading_roundtable",
            continuation=continuation,
            has_remaining_work=True,
            metadata={
                "packet": {"overall_gate": "FAIL"},
                "roundtable": {"conclusion": "FAIL", "blocker": "test_blocker"},
            },
        )
        
        result = check_push_consumer_status("batch_011")
        
        assert result["closeout_status"] == "blocked"
        assert result["can_auto_continue"] is False
        assert result["blocker"] is not None
        assert "blocked" in result["blocker"].lower()
    
    def test_check_status_push_pending(self):
        """测试 push pending 状态"""
        continuation = ContinuationContract(
            stopped_because="roundtable_gate_pass",
            next_step="Proceed",
            next_owner="trading",
        )
        
        create_closeout(
            batch_id="batch_012",
            scenario="trading_roundtable",
            continuation=continuation,
            has_remaining_work=False,
        )
        
        result = check_push_consumer_status("batch_012")
        
        assert result["closeout_status"] == "complete"
        assert result["push_required"] is True
        assert result["push_status"] == "pending"
        assert result["can_auto_continue"] is False
        assert "push" in result["blocker"].lower()
    
    def test_check_status_pushed(self):
        """测试 push 已完成的状态"""
        continuation = ContinuationContract(
            stopped_because="roundtable_gate_pass",
            next_step="Proceed",
            next_owner="trading",
        )
        
        closeout = create_closeout(
            batch_id="batch_013",
            scenario="trading_roundtable",
            continuation=continuation,
            has_remaining_work=False,
        )
        
        # 模拟 push 成功
        simulate_push_success(batch_id="batch_013")
        
        result = check_push_consumer_status("batch_013")
        
        assert result["closeout_status"] == "complete"
        assert result["push_status"] == "pushed"
        assert result["can_auto_continue"] is True
        assert result["blocker"] is None
    
    def test_check_status_with_push_action(self):
        """测试包含 push action 的状态"""
        continuation = ContinuationContract(
            stopped_because="roundtable_gate_pass",
            next_step="Proceed",
            next_owner="trading",
        )
        
        closeout = create_closeout(
            batch_id="batch_014",
            scenario="trading_roundtable",
            continuation=continuation,
            has_remaining_work=False,
        )
        
        emit_push_action(batch_id="batch_014", closeout_id=closeout.closeout_id)
        consume_push_action(batch_id="batch_014")
        
        result = check_push_consumer_status("batch_014")
        
        assert result["push_action_exists"] is True
        assert result["push_action_status"] == "consumed"


class TestPushConsumerIntegration:
    """测试 push consumer 完整流程集成"""
    
    def test_full_push_consumer_lifecycle(self):
        """测试完整的 push consumer 生命周期"""
        # 1. 创建 closeout
        continuation = ContinuationContract(
            stopped_because="roundtable_gate_pass",
            next_step="Proceed to next batch",
            next_owner="trading",
        )
        
        closeout = create_closeout(
            batch_id="batch_lifecycle",
            scenario="trading_roundtable",
            continuation=continuation,
            has_remaining_work=False,
            metadata={"packet": {"overall_gate": "PASS"}},
        )
        
        # 初始状态
        assert closeout.closeout_status == "complete"
        assert closeout.push_required is True
        assert closeout.push_status == "pending"
        
        # 2. Emit push action
        action = emit_push_action(
            batch_id="batch_lifecycle",
            closeout_id=closeout.closeout_id,
            intent="Git push for lifecycle test",
        )
        assert action.status == "emitted"
        
        # 检查状态
        status = check_push_consumer_status("batch_lifecycle")
        assert status["push_action_status"] == "emitted"
        assert status["can_auto_continue"] is False  # push 还未执行
        
        # 3. Consume push action
        action = consume_push_action(batch_id="batch_lifecycle")
        assert action.status == "consumed"
        
        # 检查状态
        status = check_push_consumer_status("batch_lifecycle")
        assert status["push_action_status"] == "consumed"
        assert status["can_auto_continue"] is False  # push 还未执行
        
        # 4. Simulate push success（受控模拟，不真实 push）
        updated_closeout = simulate_push_success(batch_id="batch_lifecycle")
        assert updated_closeout.push_status == "pushed"
        assert updated_closeout.push_action.status == "executed"
        
        # 检查状态
        status = check_push_consumer_status("batch_lifecycle")
        assert status["push_status"] == "pushed"
        assert status["push_action_status"] == "executed"
        assert status["can_auto_continue"] is True  # 现在可以自动继续
        assert status["blocker"] is None
        
        # 5. 验证 closeout gate 会允许下一批
        from closeout_tracker import check_closeout_gate
        
        gate_result = check_closeout_gate(
            batch_id="batch_next",
            scenario="trading_roundtable",
        )
        
        assert gate_result.allowed is True
        assert gate_result.previous_batch_id == "batch_lifecycle"
        assert gate_result.previous_push_status == "pushed"
    
    def test_push_consumer_state_transitions(self):
        """测试 push consumer 状态流转"""
        # 创建 closeout
        continuation = ContinuationContract(
            stopped_because="roundtable_gate_pass",
            next_step="Proceed",
            next_owner="trading",
        )
        
        closeout = create_closeout(
            batch_id="batch_transitions",
            scenario="trading_roundtable",
            continuation=continuation,
            has_remaining_work=False,
        )
        
        # 状态流转：
        # 1. closeout complete, push pending (初始)
        assert closeout.push_status == "pending"
        assert closeout.push_action is None
        
        # 2. emit -> push_action emitted
        action = emit_push_action(batch_id="batch_transitions", closeout_id=closeout.closeout_id)
        assert action.status == "emitted"
        
        closeout = get_closeout("batch_transitions")
        assert closeout.push_action is not None
        assert closeout.push_action.status == "emitted"
        assert closeout.push_status == "pending"  # push_status 不变
        
        # 3. consume -> push_action consumed
        action = consume_push_action(batch_id="batch_transitions")
        assert action.status == "consumed"
        
        closeout = get_closeout("batch_transitions")
        assert closeout.push_action.status == "consumed"
        assert closeout.push_status == "pending"  # push_status 仍不变
        
        # 4. simulate success -> push_action executed, push_status pushed
        updated = simulate_push_success(batch_id="batch_transitions")
        assert updated.push_status == "pushed"
        assert updated.push_action.status == "executed"
        
        # 验证状态区分清晰
        # - closeout complete but push pending: 步骤 1
        # - push action emitted/consumed but not executed: 步骤 2-3
        # - push executed and status backfilled to pushed: 步骤 4


class TestPushConsumerEdgeCases:
    """测试 push consumer 边界情况"""
    
    def test_non_trading_scenario_push_not_required(self):
        """测试非 trading 场景 push_not_required"""
        continuation = ContinuationContract(
            stopped_because="callback_closed",
            next_step="Review",
            next_owner="main",
        )
        
        closeout = create_closeout(
            batch_id="batch_non_trading",
            scenario="channel_roundtable",
            continuation=continuation,
            has_remaining_work=False,
            metadata={"packet": {}},  # 没有 git commit
        )
        
        assert closeout.push_required is False
        assert closeout.push_status == "not_required"
        
        # 非 trading 场景不应该 emit push action
        # （但技术上仍然可以，只是不会阻塞 closeout gate）
    
    def test_incomplete_closeout_push_blocked(self):
        """测试 incomplete closeout 的 push blocked 状态"""
        continuation = ContinuationContract(
            stopped_because="follow_up_partial_completed",
            next_step="Complete remaining work",
            next_owner="trading",
        )
        
        closeout = create_closeout(
            batch_id="batch_incomplete",
            scenario="trading_roundtable",
            continuation=continuation,
            has_remaining_work=True,  # 有剩余工作
        )
        
        assert closeout.closeout_status == "incomplete"
        assert closeout.push_status == "blocked"
        
        # incomplete closeout 不应该允许 emit push action
        # （但技术上仍然可以，只是不会改变 blocked 状态）
        
        status = check_push_consumer_status("batch_incomplete")
        assert status["can_auto_continue"] is False
        assert status["blocker"] is not None


def run_tests():
    """运行所有测试"""
    import unittest
    
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # 添加测试类
    test_classes = [
        TestPushAction,
        TestEmitPushAction,
        TestConsumePushAction,
        TestUpdatePushStatus,
        TestSimulatePushSuccess,
        TestCheckPushConsumerStatus,
        TestPushConsumerIntegration,
        TestPushConsumerEdgeCases,
    ]
    
    for test_class in test_classes:
        suite.addTests(loader.loadTestsFromTestCase(test_class))
    
    # 运行测试
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
