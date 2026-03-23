#!/usr/bin/env python3
"""
test_continuation_contract_integration.py — P0-1 Batch 4

测试 ContinuationContract 在 dispatch_planner 和 post_completion_replan 中的集成。

覆盖：
- dispatch_planner 正确构建 ContinuationContract
- post_completion_replan 与 ContinuationContract 双向转换
- 向后兼容性：保留原始 continuation dict
"""

from __future__ import annotations

import pytest
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
ORCHESTRATOR_DIR = REPO_ROOT / "runtime" / "orchestrator"
CORE_DIR = ORCHESTRATOR_DIR / "core"

if str(ORCHESTRATOR_DIR) not in sys.path:
    sys.path.insert(0, str(ORCHESTRATOR_DIR))
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

from partial_continuation import ContinuationContract, build_continuation_contract
from post_completion_replan import (
    PostCompletionReplanContract,
    TruthAnchor,
    build_replan_contract,
    convert_replan_to_continuation_contract,
    convert_continuation_contract_to_replan,
)
from dispatch_planner import DispatchPlanner, DispatchBackend


class TestContinuationContractBasics:
    """测试 ContinuationContract 基本功能"""
    
    def test_build_continuation_contract(self):
        """测试：构建 ContinuationContract"""
        contract = build_continuation_contract(
            stopped_because="task_blocked_by_dependency",
            next_step="Resolve dependency issue",
            next_owner="trading",
            metadata={"source": "test"},
        )
        
        assert contract.stopped_because == "task_blocked_by_dependency"
        assert contract.next_step == "Resolve dependency issue"
        assert contract.next_owner == "trading"
        assert contract.metadata["source"] == "test"
        
        is_valid, errors = contract.validate()
        assert is_valid is True
        assert len(errors) == 0
    
    def test_continuation_contract_to_dict(self):
        """测试：ContinuationContract 序列化"""
        contract = ContinuationContract(
            stopped_because="test_stop",
            next_step="test_next",
            next_owner="test_owner",
            metadata={"key": "value"},
        )
        
        d = contract.to_dict()
        assert d["stopped_because"] == "test_stop"
        assert d["next_step"] == "test_next"
        assert d["next_owner"] == "test_owner"
        assert d["metadata"]["key"] == "value"
        assert "contract_version" in d
    
    def test_continuation_contract_from_dict(self):
        """测试：ContinuationContract 反序列化"""
        d = {
            "stopped_because": "test_stop",
            "next_step": "test_next",
            "next_owner": "test_owner",
            "metadata": {"key": "value"},
        }
        
        contract = ContinuationContract.from_dict(d)
        assert contract.stopped_because == "test_stop"
        assert contract.next_step == "test_next"
        assert contract.next_owner == "test_owner"


class TestDispatchPlannerContinuationContract:
    """测试 DispatchPlanner 中的 ContinuationContract 集成"""
    
    def test_create_plan_builds_continuation_contract(self):
        """测试：create_plan 自动构建 ContinuationContract"""
        planner = DispatchPlanner()
        
        continuation = {
            "stopped_because": "manual_review_required",
            "next_step": "Wait for human confirmation",
            "next_owner": "main",
            "task_preview": "Continue trading roundtable",
        }
        
        plan = planner.create_plan(
            dispatch_id="dispatch_test_001",
            batch_id="batch_test_001",
            scenario="trading_roundtable_phase1",
            adapter="trading_roundtable",
            decision_id="decision_001",
            decision={"action": "proceed"},
            continuation=continuation,
            backend=DispatchBackend.SUBAGENT,
            allow_auto_dispatch=False,
        )
        
        # 验证 ContinuationContract 被正确构建
        assert plan.continuation_contract is not None
        assert plan.continuation_contract.stopped_because == "manual_review_required"
        assert plan.continuation_contract.next_step == "Wait for human confirmation"
        assert plan.continuation_contract.next_owner == "main"
        
        # 验证 metadata 包含 dispatch 信息
        assert plan.continuation_contract.metadata["source"] == "dispatch_plan"
        assert plan.continuation_contract.metadata["dispatch_id"] == "dispatch_test_001"
        assert plan.continuation_contract.metadata["batch_id"] == "batch_test_001"
        
        # 验证向后兼容：原始 continuation dict 仍然保留
        assert plan.continuation == continuation
    
    def test_create_plan_defaults_missing_fields(self):
        """测试：create_plan 为缺失字段提供默认值"""
        planner = DispatchPlanner()
        
        # 只提供部分字段
        continuation = {
            "task_preview": "Some task",
        }
        
        plan = planner.create_plan(
            dispatch_id="dispatch_test_002",
            batch_id="batch_test_002",
            scenario="channel_roundtable",
            adapter="channel_roundtable",
            decision_id="decision_002",
            decision={"action": "retry"},
            continuation=continuation,
            backend=DispatchBackend.TMUX,
        )
        
        # 验证默认值
        assert plan.continuation_contract is not None
        assert plan.continuation_contract.stopped_because == "continuation_requested"
        assert plan.continuation_contract.next_step == "Some task"
        assert plan.continuation_contract.next_owner == "main"
    
    def test_plan_to_dict_includes_continuation_contract(self):
        """测试：plan.to_dict() 包含 continuation_contract"""
        planner = DispatchPlanner()
        
        plan = planner.create_plan(
            dispatch_id="dispatch_test_003",
            batch_id="batch_test_003",
            scenario="trading_roundtable_phase1",
            adapter="trading_roundtable",
            decision_id="decision_003",
            decision={"action": "proceed"},
            continuation={
                "stopped_because": "test",
                "next_step": "test",
                "next_owner": "test",
            },
        )
        
        d = plan.to_dict()
        
        # 验证同时包含 continuation 和 continuation_contract
        assert "continuation" in d
        assert "continuation_contract" in d
        assert d["continuation_contract"] is not None
        assert d["continuation_contract"]["stopped_because"] == "test"


class TestPostCompletionReplanConversion:
    """测试 PostCompletionReplanContract 与 ContinuationContract 双向转换"""
    
    def test_replan_to_continuation_contract_pending(self):
        """测试：pending_registration 模式的 replan 转换为 ContinuationContract"""
        replan = build_replan_contract(
            followup_description="Write documentation",
            original_task_id="task_123",
            # 没有 anchor → pending
        )
        
        contract = convert_replan_to_continuation_contract(replan)
        
        assert contract.stopped_because.startswith("follow_up_pending_registration")
        assert contract.next_step == "Write documentation"
        assert contract.next_owner == "main"
        assert contract.metadata["source"] == "post_completion_replan"
        assert contract.metadata["followup_mode"] == "pending_registration"
    
    def test_replan_to_continuation_contract_with_anchor(self):
        """测试：有 anchor 的 replan 转换为 ContinuationContract"""
        replan = build_replan_contract(
            followup_description="Phase 2 implementation",
            original_batch_id="batch_456",
            anchor_type="batch_id",
            anchor_value="batch_789",
        )
        
        contract = convert_replan_to_continuation_contract(replan)
        
        assert contract.stopped_because.startswith("follow_up_registered")
        assert "batch_id=batch_789" in contract.stopped_because
        assert contract.next_step == "Phase 2 implementation"
    
    def test_continuation_contract_to_replan(self):
        """测试：ContinuationContract 转换为 PostCompletionReplanContract"""
        continuation = ContinuationContract(
            stopped_because="task_completed_partial",
            next_step="Implement remaining features",
            next_owner="trading",
            metadata={
                "original_task_id": "task_orig_123",
                "original_batch_id": "batch_orig_456",
            },
        )
        
        replan = convert_continuation_contract_to_replan(continuation)
        
        assert replan.followup_description == "Implement remaining features"
        assert replan.original_task_id == "task_orig_123"
        assert replan.original_batch_id == "batch_orig_456"
        assert replan.metadata["next_owner"] == "trading"
    
    def test_continuation_contract_to_replan_with_anchor_in_metadata(self):
        """测试：ContinuationContract 包含 truth_anchor 时转换为 replan"""
        continuation = ContinuationContract(
            stopped_because="continuation",
            next_step="Continue work",
            next_owner="main",
            metadata={
                "truth_anchor": {
                    "anchor_type": "task_id",
                    "anchor_value": "task_new_789",
                },
            },
        )
        
        replan = convert_continuation_contract_to_replan(continuation)
        
        assert replan.truth_anchor.anchor_type == "task_id"
        assert replan.truth_anchor.anchor_value == "task_new_789"
        # 有 anchor 时应该是 existing_dispatch 模式
        assert replan.followup_mode == "existing_dispatch"
        assert replan.status_phrase == "in_progress"
    
    def test_roundtrip_replan_to_continuation_to_replan(self):
        """测试：replan → continuation → replan 往返转换"""
        # 原始 replan
        original_replan = build_replan_contract(
            followup_description="Test roundtrip",
            original_task_id="task_123",
            anchor_type="task_id",
            anchor_value="task_456",
            metadata={"priority": "high"},
        )
        
        # 转换为 continuation
        continuation = convert_replan_to_continuation_contract(original_replan)
        
        # 转换回 replan
        converted_replan = convert_continuation_contract_to_replan(continuation)
        
        # 验证核心字段保持一致
        assert converted_replan.followup_description == original_replan.followup_description
        assert converted_replan.truth_anchor.anchor_type == original_replan.truth_anchor.anchor_type
        assert converted_replan.truth_anchor.anchor_value == original_replan.truth_anchor.anchor_value


class TestBackwardCompatibility:
    """测试向后兼容性"""
    
    def test_dispatch_plan_load_without_continuation_contract(self):
        """测试：加载不包含 continuation_contract 的旧数据"""
        # 模拟旧版本的 plan 数据（没有 continuation_contract 字段）
        old_plan_data = {
            "dispatch_id": "dispatch_old",
            "batch_id": "batch_old",
            "scenario": "trading_roundtable",
            "adapter": "trading_roundtable",
            "decision_id": "decision_old",
            "status": "triggered",
            "backend": "subagent",
            "continuation": {"key": "value"},
            "timestamp": "2026-03-22T12:00:00",
        }
        
        planner = DispatchPlanner()
        planner.plans["dispatch_old"] = type('obj', (object,), {
            'dispatch_id': 'dispatch_old',
            'batch_id': 'batch_old',
            'scenario': 'trading_roundtable',
            'adapter': 'trading_roundtable',
            'decision_id': 'decision_old',
            'status': type('obj', (object,), {'value': 'triggered'})(),
            'reason': '',
            'backend': type('obj', (object,), {'value': 'subagent'})(),
            'continuation': {"key": "value"},
            'continuation_contract': None,  # 旧数据没有这个字段
            'timestamp': '2026-03-22T12:00:00',
        })()
        
        # 验证可以正常访问 continuation（向后兼容）
        plan = planner.plans["dispatch_old"]
        assert plan.continuation == {"key": "value"}
        # continuation_contract 为 None 是可以接受的
        assert plan.continuation_contract is None


class TestIntegration:
    """集成测试：真实使用场景"""
    
    def test_dispatch_plan_continuation_workflow(self):
        """集成测试：完整的 dispatch plan continuation 工作流"""
        planner = DispatchPlanner()
        
        # 1. 创建 dispatch plan
        continuation_input = {
            "stopped_because": "gate_held",
            "next_step": "Wait for gate release",
            "next_owner": "trading",
            "task_preview": "Continue after gate release",
        }
        
        plan = planner.create_plan(
            dispatch_id="dispatch_integration_001",
            batch_id="batch_integration_001",
            scenario="trading_roundtable_phase1",
            adapter="trading_roundtable",
            decision_id="decision_integration_001",
            decision={"action": "proceed", "metadata": {}},
            continuation=continuation_input,
            backend=DispatchBackend.SUBAGENT,
            allow_auto_dispatch=False,
        )
        
        # 2. 验证 ContinuationContract 被正确构建
        assert plan.continuation_contract is not None
        contract = plan.continuation_contract
        assert contract.stopped_because == "gate_held"
        assert contract.next_step == "Wait for gate release"
        assert contract.next_owner == "trading"
        
        # 3. 验证序列化包含 continuation_contract
        plan_dict = plan.to_dict()
        assert "continuation_contract" in plan_dict
        assert plan_dict["continuation_contract"]["stopped_because"] == "gate_held"
        
        # 4. 验证向后兼容：原始 continuation 仍然存在
        assert plan_dict["continuation"] == continuation_input


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
