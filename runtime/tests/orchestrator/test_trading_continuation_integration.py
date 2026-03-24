#!/usr/bin/env python3
"""
test_trading_continuation_integration.py — Trading Continuation Integration Tests

测试 trading roundtable 中 planning artifact 和 continuation contract 的完整链路。

这是 P0-1 Batch 1 的回归测试，验证：
1. Planning artifact 在 dispatch plan 中生成
2. Continuation contract 在 closeout 中注入
3. 完整 trading 链路正常工作
"""

import sys
import os

# 添加 runtime/orchestrator 到路径
script_dir = os.path.dirname(os.path.abspath(__file__))
runtime_orchestrator_path = os.path.join(script_dir, '../../orchestrator')
sys.path.insert(0, runtime_orchestrator_path)
sys.path.insert(0, script_dir)

# 添加 core 路径
core_path = os.path.join(runtime_orchestrator_path, 'core')
sys.path.insert(0, core_path)

from partial_continuation import (
    ContinuationContract,
    build_continuation_contract,
    CONTINUATION_CONTRACT_VERSION,
)
from planning_default import (
    PlanningArtifact,
    build_planning_artifact,
    extract_planning_artifact,
)
from dispatch_planner import (
    DispatchPlanner,
    DispatchBackend,
    DispatchStatus,
)


def test_dispatch_plan_includes_continuation_contract():
    """测试 dispatch plan 包含 continuation contract"""
    print("Test: DispatchPlan includes continuation_contract")
    
    planner = DispatchPlanner()
    
    # 模拟 decision 和 continuation 数据
    decision = {
        "action": "proceed",
        "reason": "Roundtable gate is PASS",
        "metadata": {
            "orchestration_contract": {
                "adapter": "trading_roundtable",
                "scenario": "trading_roundtable_phase1",
                "owner": "trading",
            },
        },
    }
    
    continuation = {
        "stopped_because": "roundtable_gate_pass_continuation_ready",
        "next_step": "Implement phase2 features",
        "next_owner": "trading",
        "task_preview": "Phase2 implementation",
    }
    
    # 创建 dispatch plan
    plan = planner.create_plan(
        dispatch_id="disp_test_001",
        batch_id="batch_test_001",
        scenario="trading_roundtable_phase1",
        adapter="trading_roundtable",
        decision_id="dec_test_001",
        decision=decision,
        continuation=continuation,
        backend=DispatchBackend.SUBAGENT,
        allow_auto_dispatch=True,
        auto_dispatch_source="test",
        readiness={"eligible": True, "status": "ready"},
        validation={"complete": True},
        roundtable={"conclusion": "PASS", "blocker": "none", "owner": "trading"},
        packet={"overall_gate": "PASS"},
    )
    
    # 检查 continuation_contract
    assert plan.continuation_contract is not None, "continuation_contract should not be None"
    print("  ✓ DispatchPlan has continuation_contract")
    
    assert plan.continuation_contract.stopped_because == "roundtable_gate_pass_continuation_ready"
    assert "Implement phase2" in plan.continuation_contract.next_step
    assert plan.continuation_contract.next_owner == "trading"
    print("  ✓ ContinuationContract fields correctly populated")
    
    # 检查版本
    cc_dict = plan.continuation_contract.to_dict()
    assert cc_dict["contract_version"] == CONTINUATION_CONTRACT_VERSION
    print(f"  ✓ ContinuationContract version is {CONTINUATION_CONTRACT_VERSION}")
    
    # 检查 to_dict 输出
    plan_dict = plan.to_dict()
    assert "continuation_contract" in plan_dict
    assert plan_dict["continuation_contract"] is not None
    print("  ✓ ContinuationContract included in to_dict()")
    
    print("  PASS: DispatchPlan includes continuation_contract\n")


def test_dispatch_plan_includes_planning_artifact():
    """测试 dispatch plan 包含 planning artifact"""
    print("Test: DispatchPlan includes planning_artifact")
    
    planner = DispatchPlanner()
    
    decision = {
        "action": "fix_blocker",
        "reason": "Packet incomplete, missing artifact path",
        "metadata": {
            "orchestration_contract": {
                "adapter": "trading_roundtable",
                "scenario": "trading_roundtable_phase1",
                "owner": "main",
            },
        },
    }
    
    continuation = {
        "stopped_because": "roundtable_gate_conditional_blocker_missing_artifact",
        "next_step": "Add artifact path and report to packet",
        "next_owner": "main",
    }
    
    plan = planner.create_plan(
        dispatch_id="disp_test_002",
        batch_id="batch_test_002",
        scenario="trading_roundtable_phase1",
        adapter="trading_roundtable",
        decision_id="dec_test_002",
        decision=decision,
        continuation=continuation,
        backend=DispatchBackend.SUBAGENT,
        allow_auto_dispatch=False,
        readiness={"eligible": False, "status": "not_ready"},
        validation={"complete": False},
        roundtable={"conclusion": "CONDITIONAL", "blocker": "missing_artifact"},
        packet={"overall_gate": "FAIL"},
    )
    
    # 检查 planning_artifact
    assert plan.planning_artifact is not None, "planning_artifact should not be None for non-trivial task"
    print("  ✓ DispatchPlan has planning_artifact")
    
    # 检查 planning artifact 字段
    assert plan.planning_artifact.problem_reframing.problem_statement != ""
    assert len(plan.planning_artifact.scope_review.in_scope) > 0
    print("  ✓ PlanningArtifact has required fields")
    
    # 检查 problem statement 包含 decision 信息
    problem = plan.planning_artifact.problem_reframing.problem_statement
    # problem statement 应该包含 next_step 或 reason 的内容
    assert len(problem) > 0, "Problem statement should not be empty"
    # in_scope 应该包含 blocker 信息
    in_scope_str = " ".join([s.lower() for s in plan.planning_artifact.scope_review.in_scope])
    assert "blocker" in in_scope_str or "fix" in in_scope_str, f"in_scope should mention blocker: {plan.planning_artifact.scope_review.in_scope}"
    print(f"  ✓ Problem statement reflects decision: {problem[:80]}...")
    
    # 检查 to_dict 输出
    plan_dict = plan.to_dict()
    assert "planning_artifact" in plan_dict
    assert plan_dict["planning_artifact"] is not None
    print("  ✓ PlanningArtifact included in to_dict()")
    
    print("  PASS: DispatchPlan includes planning_artifact\n")


def test_continuation_contract_in_closeout():
    """测试 continuation contract 在 closeout 中的注入"""
    print("Test: ContinuationContract in closeout")
    
    from closeout_tracker import CloseoutTracker, create_closeout
    
    tracker = CloseoutTracker()
    
    # 创建 continuation contract
    cc = build_continuation_contract(
        stopped_because="roundtable_gate_pass_continuation_ready",
        next_step="Continue with phase2 implementation",
        next_owner="trading",
        metadata={
            "source": "test_closeout",
            "batch_id": "batch_test_003",
        },
    )
    
    # 创建 closeout
    closeout = tracker.create_closeout(
        batch_id="batch_test_003",
        scenario="trading_roundtable_phase1",
        continuation=cc,
        has_remaining_work=True,
        artifacts={
            "summary_path": "/tmp/test_summary.md",
            "decision_path": "/tmp/test_decision.json",
        },
        metadata={
            "roundtable": {"conclusion": "PASS", "blocker": "none"},
            "packet": {"overall_gate": "PASS"},
        },
    )
    
    # 检查 closeout 包含 continuation_contract
    assert closeout.continuation_contract is not None
    print("  ✓ CloseoutArtifact has continuation_contract")
    
    # 检查字段一致
    assert closeout.continuation_contract.stopped_because == cc.stopped_because
    assert closeout.continuation_contract.next_step == cc.next_step
    assert closeout.continuation_contract.next_owner == cc.next_owner
    print("  ✓ ContinuationContract fields match source")
    
    # 检查 to_dict 输出
    closeout_dict = closeout.to_dict()
    assert "continuation_contract" in closeout_dict
    assert closeout_dict["continuation_contract"]["contract_version"] == CONTINUATION_CONTRACT_VERSION
    print("  ✓ ContinuationContract included in closeout to_dict()")
    
    print("  PASS: ContinuationContract in closeout\n")


def test_planning_artifact_extraction_from_dispatch():
    """测试从 dispatch plan 中提取 planning artifact"""
    print("Test: PlanningArtifact extraction from dispatch plan")
    
    planner = DispatchPlanner()
    
    decision = {
        "action": "proceed",
        "reason": "Test decision",
        "metadata": {},
    }
    
    continuation = {
        "stopped_because": "test",
        "next_step": "Test step",
        "next_owner": "main",
    }
    
    plan = planner.create_plan(
        dispatch_id="disp_test_004",
        batch_id="batch_test_004",
        scenario="trading_roundtable_phase1",
        adapter="trading_roundtable",
        decision_id="dec_test_004",
        decision=decision,
        continuation=continuation,
        backend=DispatchBackend.SUBAGENT,
        allow_auto_dispatch=True,
        readiness={"eligible": True},
        validation={"complete": True},
        roundtable={"conclusion": "PASS", "blocker": "none"},
        packet={"overall_gate": "PASS"},
    )
    
    # 从 dispatch plan dict 中提取 planning artifact
    plan_dict = plan.to_dict()
    payload = {"dispatch_plan": plan_dict}
    
    extracted = extract_planning_artifact(payload, source="dispatch_plan")
    
    assert extracted is not None, "Should extract planning artifact from dispatch plan"
    print("  ✓ PlanningArtifact extracted from dispatch plan")
    
    # 验证提取的 artifact
    assert extracted.artifact_id == plan.planning_artifact.artifact_id
    print("  ✓ Extracted artifact ID matches")
    
    print("  PASS: PlanningArtifact extraction from dispatch plan\n")


def test_trading_action_scenarios():
    """测试不同 trading decision action 场景"""
    print("Test: Trading decision action scenarios")
    
    planner = DispatchPlanner()
    
    # 场景 1: proceed
    decision_proceed = {
        "action": "proceed",
        "reason": "Roundtable PASS, continue",
        "metadata": {"orchestration_contract": {"owner": "trading"}},
    }
    continuation_proceed = {
        "stopped_because": "roundtable_gate_pass_continuation_ready",
        "next_step": "Implement phase2",
        "next_owner": "trading",
    }
    
    plan_proceed = planner.create_plan(
        dispatch_id="disp_proceed",
        batch_id="batch_proceed",
        scenario="trading_roundtable_phase1",
        adapter="trading_roundtable",
        decision_id="dec_proceed",
        decision=decision_proceed,
        continuation=continuation_proceed,
        backend=DispatchBackend.SUBAGENT,
        allow_auto_dispatch=True,
        readiness={"eligible": True},
        validation={"complete": True},
        roundtable={"conclusion": "PASS", "blocker": "none"},
        packet={"overall_gate": "PASS"},
        requester_session_key="test_session",
    )
    
    assert plan_proceed.planning_artifact is not None
    assert plan_proceed.continuation_contract is not None
    assert plan_proceed.status == DispatchStatus.TRIGGERED
    print("  ✓ Proceed scenario: planning artifact and continuation contract present")
    
    # 场景 2: fix_blocker
    decision_fix = {
        "action": "fix_blocker",
        "reason": "Packet incomplete",
        "metadata": {"orchestration_contract": {"owner": "main"}},
    }
    continuation_fix = {
        "stopped_because": "roundtable_gate_conditional_blocker_missing_fields",
        "next_step": "Fix missing packet fields",
        "next_owner": "main",
    }
    
    plan_fix = planner.create_plan(
        dispatch_id="disp_fix",
        batch_id="batch_fix",
        scenario="trading_roundtable_phase1",
        adapter="trading_roundtable",
        decision_id="dec_fix",
        decision=decision_fix,
        continuation=continuation_fix,
        backend=DispatchBackend.SUBAGENT,
        allow_auto_dispatch=False,
        readiness={"eligible": False},
        validation={"complete": False},
        roundtable={"conclusion": "CONDITIONAL", "blocker": "missing_fields"},
        packet={"overall_gate": "FAIL"},
        requester_session_key="test_session",
    )
    
    assert plan_fix.planning_artifact is not None
    assert plan_fix.continuation_contract is not None
    assert plan_fix.status == DispatchStatus.SKIPPED
    print("  ✓ Fix_blocker scenario: planning artifact and continuation contract present")
    
    # 场景 3: abort
    decision_abort = {
        "action": "abort",
        "reason": "Critical blocker",
        "metadata": {"orchestration_contract": {"owner": "main"}},
    }
    continuation_abort = {
        "stopped_because": "roundtable_gate_fail_blocker_critical",
        "next_step": "Document learnings and abort",
        "next_owner": "main",
    }
    
    plan_abort = planner.create_plan(
        dispatch_id="disp_abort",
        batch_id="batch_abort",
        scenario="trading_roundtable_phase1",
        adapter="trading_roundtable",
        decision_id="dec_abort",
        decision=decision_abort,
        continuation=continuation_abort,
        backend=DispatchBackend.SUBAGENT,
        allow_auto_dispatch=False,
        readiness={"eligible": False},
        validation={"complete": False},
        roundtable={"conclusion": "FAIL", "blocker": "critical"},
        packet={"overall_gate": "FAIL"},
        requester_session_key="test_session",
    )
    
    assert plan_abort.planning_artifact is not None
    assert plan_abort.continuation_contract is not None
    assert plan_abort.status == DispatchStatus.SKIPPED
    print("  ✓ Abort scenario: planning artifact and continuation contract present")
    
    print("  PASS: Trading decision action scenarios\n")


def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("Trading Continuation Integration Tests")
    print("=" * 60 + "\n")
    
    test_dispatch_plan_includes_continuation_contract()
    test_dispatch_plan_includes_planning_artifact()
    test_continuation_contract_in_closeout()
    test_planning_artifact_extraction_from_dispatch()
    test_trading_action_scenarios()
    
    print("=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    run_all_tests()
