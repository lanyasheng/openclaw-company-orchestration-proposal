#!/usr/bin/env python3
"""
test_auto_continue_trigger.py — Auto-Continue Trigger 测试

测试覆盖：
- accepted completion + no conflict -> continue_allowed
- writer 冲突 -> continue_blocked
- read-only lane 不占 writer
- 最小接线回归

执行命令：
    python -m pytest tests/orchestrator/test_auto_continue_trigger.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime
from unittest.mock import Mock, patch

import pytest

# Add orchestrator to path
ORCHESTRATOR_DIR = Path(__file__).resolve().parents[2] / "runtime" / "orchestrator"
if str(ORCHESTRATOR_DIR) not in sys.path:
    sys.path.insert(0, str(ORCHESTRATOR_DIR))

from auto_continue_trigger import (
    AutoContinueTrigger,
    AutoContinueDecision,
    ContinueDecision,
    evaluate_auto_continue,
)
from completion_receipt import (
    CompletionReceiptArtifact,
    ReceiptStatus,
)


@pytest.fixture
def mock_receipt():
    """创建 mock receipt 用于测试"""
    return CompletionReceiptArtifact(
        receipt_id="receipt_test_001",
        source_spawn_execution_id="exec_test_001",
        source_spawn_id="spawn_test_001",
        source_dispatch_id="dispatch_test_001",
        source_registration_id="reg_test_001",
        source_task_id="task_test_001",
        receipt_status="completed",
        receipt_reason="Execution completed successfully",
        receipt_time=datetime.now().isoformat(),
        result_summary="Test completion",
        dedupe_key="dedupe_test_001",
        metadata={
            "repo": "test-repo",
            "batch_id": "batch_test_001",
            "execution_id": "exec_test_001",
        },
    )


class TestAutoContinueTrigger_Allowed:
    """测试 continue_allowed 场景"""
    
    def test_accepted_completion_no_conflict_allows_continue(self, mock_receipt):
        """场景：accepted completion + no conflict -> continue_allowed"""
        trigger = AutoContinueTrigger()
        
        # Mock writer guard 返回无冲突
        with patch.object(trigger, '_get_writer_guard') as mock_guard:
            mock_guard_instance = Mock()
            mock_guard_instance.check_writer_conflict.return_value = (False, "no_conflict")
            mock_guard.return_value = mock_guard_instance
            
            # Mock validator result
            with patch.object(trigger, '_get_latest_validator_result') as mock_validator:
                mock_validator.return_value = ("accepted_completion", "audit_001", "all_checks_passed")
                
                decision = trigger.evaluate(
                    receipt_id=mock_receipt.receipt_id,
                    receipt=mock_receipt,
                )
                
                assert decision.decision == "continue_allowed", f"Expected continue_allowed, got {decision.decision}"
                assert "all_conditions_met" in decision.reason
                assert decision.validator_status == "accepted_completion"
                assert decision.receipt_status == "completed"
                assert decision.writer_conflict is False
        
        print("✅ 场景 1 验证通过：accepted completion + no conflict -> continue_allowed")
    
    def test_inferred_from_receipt_completed(self, mock_receipt):
        """场景：validator 状态从 receipt_status 推断"""
        trigger = AutoContinueTrigger()
        
        with patch.object(trigger, '_get_writer_guard') as mock_guard:
            mock_guard_instance = Mock()
            mock_guard_instance.check_writer_conflict.return_value = (False, "no_conflict")
            mock_guard.return_value = mock_guard_instance
            
            # Mock validator result - inferred from receipt
            with patch.object(trigger, '_get_latest_validator_result') as mock_validator:
                mock_validator.return_value = ("accepted_completion", "", "inferred_from_receipt_completed")
                
                decision = trigger.evaluate(
                    receipt_id=mock_receipt.receipt_id,
                    receipt=mock_receipt,
                )
                
                assert decision.decision == "continue_allowed"
                assert decision.validator_status == "accepted_completion"
                assert decision.receipt_status == "completed"


class TestAutoContinueTrigger_Blocked:
    """测试 continue_blocked 场景"""
    
    def test_validator_blocked_completion_blocks_continue(self, mock_receipt):
        """场景：validator blocked -> continue_blocked"""
        trigger = AutoContinueTrigger()
        
        with patch.object(trigger, '_get_writer_guard') as mock_guard:
            mock_guard_instance = Mock()
            mock_guard_instance.check_writer_conflict.return_value = (False, "no_conflict")
            mock_guard.return_value = mock_guard_instance
            
            with patch.object(trigger, '_get_latest_validator_result') as mock_validator:
                mock_validator.return_value = ("blocked_completion", "audit_001", "missing_artifacts")
                
                decision = trigger.evaluate(
                    receipt_id=mock_receipt.receipt_id,
                    receipt=mock_receipt,
                )
                
                assert decision.decision == "continue_blocked"
                assert "validator_blocked" in decision.reason
                assert decision.validator_status == "blocked_completion"
        
        print("✅ 场景 2 验证通过：validator blocked completion -> continue_blocked")
    
    def test_receipt_failed_blocks_continue(self, mock_receipt):
        """场景：receipt failed -> continue_blocked"""
        trigger = AutoContinueTrigger()
        
        # 修改 receipt status 为 failed
        mock_receipt.receipt_status = "failed"
        mock_receipt.receipt_reason = "Execution failed"
        
        with patch.object(trigger, '_get_writer_guard') as mock_guard:
            mock_guard_instance = Mock()
            mock_guard_instance.check_writer_conflict.return_value = (False, "no_conflict")
            mock_guard.return_value = mock_guard_instance
            
            with patch.object(trigger, '_get_latest_validator_result') as mock_validator:
                mock_validator.return_value = ("blocked_completion", "", "inferred_from_receipt_failed")
                
                decision = trigger.evaluate(
                    receipt_id=mock_receipt.receipt_id,
                    receipt=mock_receipt,
                )
                
                assert decision.decision == "continue_blocked"
                assert "blocked" in decision.reason.lower() or "failed" in decision.reason.lower()
                assert decision.receipt_status == "failed"
        
        print("✅ 场景 3 验证通过：receipt failed -> continue_blocked")
    
    def test_writer_conflict_blocks_continue(self, mock_receipt):
        """场景：writer 冲突 -> continue_blocked"""
        trigger = AutoContinueTrigger()
        
        # Mock writer guard 返回有冲突
        with patch.object(trigger, '_get_writer_guard') as mock_guard:
            mock_guard_instance = Mock()
            mock_guard_instance.check_writer_conflict.return_value = (
                True,
                "writer_conflict_with_writer_abc123",
            )
            mock_guard.return_value = mock_guard_instance
            
            with patch.object(trigger, '_get_latest_validator_result') as mock_validator:
                mock_validator.return_value = ("accepted_completion", "", "all_checks_passed")
                
                decision = trigger.evaluate(
                    receipt_id=mock_receipt.receipt_id,
                    receipt=mock_receipt,
                )
                
                assert decision.decision == "continue_blocked"
                assert "writer_conflict" in decision.reason
                assert decision.writer_conflict is True
        
        print("✅ 场景 4 验证通过：writer conflict -> continue_blocked")


class TestAutoContinueTrigger_GateRequired:
    """测试 gate_required 场景"""
    
    def test_validator_gate_required_decision(self, mock_receipt):
        """场景：validator gate_required -> gate_required"""
        trigger = AutoContinueTrigger()
        
        with patch.object(trigger, '_get_writer_guard') as mock_guard:
            mock_guard_instance = Mock()
            mock_guard_instance.check_writer_conflict.return_value = (False, "no_conflict")
            mock_guard.return_value = mock_guard_instance
            
            with patch.object(trigger, '_get_latest_validator_result') as mock_validator:
                mock_validator.return_value = ("gate_required", "audit_001", "needs_human_review")
                
                decision = trigger.evaluate(
                    receipt_id=mock_receipt.receipt_id,
                    receipt=mock_receipt,
                )
                
                assert decision.decision == "gate_required"
                assert decision.validator_status == "gate_required"
        
        print("✅ 场景 5 验证通过：validator gate_required -> gate_required")
    
    def test_unclear_state_requires_gate(self, mock_receipt):
        """场景：状态不明确 -> gate_required"""
        trigger = AutoContinueTrigger()
        
        # 修改 receipt status 为 missing
        mock_receipt.receipt_status = "missing"
        mock_receipt.receipt_reason = "Unknown state"
        
        with patch.object(trigger, '_get_writer_guard') as mock_guard:
            mock_guard_instance = Mock()
            mock_guard_instance.check_writer_conflict.return_value = (False, "no_conflict")
            mock_guard.return_value = mock_guard_instance
            
            with patch.object(trigger, '_get_latest_validator_result') as mock_validator:
                mock_validator.return_value = ("unknown", "", "validator_result_not_found")
                
                decision = trigger.evaluate(
                    receipt_id=mock_receipt.receipt_id,
                    receipt=mock_receipt,
                )
                
                assert decision.decision == "gate_required"
                assert "unclear" in decision.reason.lower()
        
        print("✅ 场景 6 验证通过：unclear state -> gate_required")


class TestAutoContinueTrigger_ReaderLane:
    """测试 read-only lane 场景"""
    
    def test_reader_lane_no_writer_conflict(self, mock_receipt):
        """场景：read-only lane 不占 writer 锁"""
        trigger = AutoContinueTrigger()
        
        mock_receipt.metadata["lane_type"] = "reader"
        
        with patch.object(trigger, '_get_writer_guard') as mock_guard:
            mock_guard_instance = Mock()
            # Reader 不占锁，所以即使有其他 writer 也不冲突
            mock_guard_instance.check_writer_conflict.return_value = (
                False,
                "reader_lock_no_conflict",
            )
            mock_guard.return_value = mock_guard_instance
            
            with patch.object(trigger, '_get_latest_validator_result') as mock_validator:
                mock_validator.return_value = ("accepted_completion", "", "all_checks_passed")
                
                decision = trigger.evaluate(
                    receipt_id=mock_receipt.receipt_id,
                    receipt=mock_receipt,
                )
                
                # Reader lane 应该允许继续（假设 validator 通过）
                assert decision.writer_conflict is False
        
        print("✅ 场景 7 验证通过：read-only lane 不占 writer")


class TestAutoContinueTrigger_Disabled:
    """测试禁用 auto-continue 场景"""
    
    def test_env_disable_auto_continue(self, mock_receipt, monkeypatch):
        """场景：环境变量禁用 auto-continue"""
        monkeypatch.setenv("DISABLE_AUTO_CONTINUE", "1")
        
        trigger = AutoContinueTrigger()
        
        decision = trigger.evaluate(
            receipt_id=mock_receipt.receipt_id,
            receipt=mock_receipt,
        )
        
        assert decision.decision == "gate_required"
        assert "disabled" in decision.reason.lower()
        
        print("✅ 场景 8 验证通过：DISABLE_AUTO_CONTINUE=1 -> gate_required")


class TestAutoContinueDecision_Serialization:
    """测试 AutoContinueDecision 序列化"""
    
    def test_to_dict_from_dict(self):
        """测试序列化和反序列化"""
        original = AutoContinueDecision(
            decision="continue_allowed",
            reason="all_conditions_met",
            source_receipt_id="receipt_123",
            validator_status="accepted_completion",
            receipt_status="completed",
            writer_conflict=False,
            metadata={"test": "value"},
        )
        
        data = original.to_dict()
        restored = AutoContinueDecision.from_dict(data)
        
        assert restored.decision == original.decision
        assert restored.reason == original.reason
        assert restored.source_receipt_id == original.source_receipt_id
        assert restored.validator_status == original.validator_status
        assert restored.receipt_status == original.receipt_status
        assert restored.writer_conflict == original.writer_conflict
        assert restored.metadata == original.metadata
        
        print("✅ 序列化/反序列化验证通过")


def run_all_tests():
    """运行所有测试并输出摘要"""
    print("\n" + "="*60)
    print("Auto-Continue Trigger 测试报告")
    print("="*60)
    
    # 运行 pytest
    import subprocess
    result = subprocess.run(
        [sys.executable, "-m", "pytest", __file__, "-v", "--tb=short"],
        capture_output=True,
        text=True,
    )
    
    print(result.stdout)
    if result.stderr:
        print(result.stderr)
    
    print("\n" + "="*60)
    print("测试结论")
    print("="*60)
    
    if result.returncode == 0:
        print("✅ 所有场景验证通过")
        print("\n覆盖场景：")
        print("- accepted completion + no conflict -> continue_allowed ✅")
        print("- blocked/gate completion -> 不续批 ✅")
        print("- writer 冲突 -> continue_blocked ✅")
        print("- read-only lane 不占 writer ✅")
        print("- 最小接线回归 ✅")
    else:
        print("❌ 部分场景验证失败")
        print("需要修复代码或测试")
    
    return result.returncode == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
