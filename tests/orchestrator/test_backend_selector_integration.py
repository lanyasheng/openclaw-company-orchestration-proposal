#!/usr/bin/env python3
"""
test_backend_selector_integration.py — Backend Selector Integration Tests

P0-3 Batch 7 (2026-03-30): Test backend_selector integration into dispatch_planner.

Test Coverage:
1. Explicit backend_preference is NOT overridden by auto-recommendation
2. Auto-recommendation is called when backend_preference is not specified
3. Long tasks (>30min) recommend tmux
4. Short tasks (<30min) recommend subagent
5. Coding tasks with monitoring keywords recommend tmux
6. Documentation tasks recommend subagent
7. Backend selection metadata is recorded in orchestration_contract
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict

# Add orchestrator to path
ORCHESTRATOR_DIR = Path(__file__).resolve().parents[2] / "runtime" / "orchestrator"
if str(ORCHESTRATOR_DIR) not in sys.path:
    sys.path.insert(0, str(ORCHESTRATOR_DIR))

from core.dispatch_planner import DispatchPlanner, DispatchBackend
from backend_selector import BackendSelector, recommend_backend


def test_explicit_backend_preference_not_overridden():
    """
    Test: Explicit backend_preference should NOT be overridden by auto-recommendation.
    
    Scenario: User explicitly specifies backend_preference="subagent" for a long task.
    Expected: backend remains "subagent" despite auto-recommendation suggesting "tmux".
    """
    print("Test 1: Explicit backend_preference is NOT overridden...")
    
    planner = DispatchPlanner()
    
    # Create a decision with explicit backend_preference
    decision = {
        "action": "proceed",
        "reason": "Continue with task",
        "metadata": {
            "orchestration_contract": {
                "backend_preference": "subagent",  # Explicit preference
            },
        },
    }
    
    # Create a continuation that would normally trigger tmux recommendation
    continuation = {
        "task_preview": "重构认证模块，预计 1 小时，需要监控中间过程",
        "next_step": "Refactor authentication module",
        "next_owner": "main",
    }
    
    # Create dispatch plan
    plan = planner.create_plan(
        dispatch_id="dispatch_test_001",
        batch_id="batch_test_001",
        scenario="test_scenario",
        adapter="test_adapter",
        decision_id="decision_001",
        decision=decision,
        continuation=continuation,
        backend=DispatchBackend.SUBAGENT,  # Default
        allow_auto_dispatch=True,
        requester_session_key="agent:test",
    )
    
    # Verify: backend should remain subagent (explicit preference)
    assert plan.backend == DispatchBackend.SUBAGENT, (
        f"Expected backend=SUBAGENT (explicit preference), got {plan.backend}"
    )
    
    # Verify: backend_selection metadata should indicate explicit override
    backend_selection = plan.orchestration_contract.get("backend_selection", {})
    assert backend_selection.get("explicit_override") is True, (
        "Expected explicit_override=True in backend_selection metadata"
    )
    assert backend_selection.get("auto_recommended") is False, (
        "Expected auto_recommended=False when explicit preference exists"
    )
    
    print("  ✓ PASS: Explicit backend_preference is NOT overridden")
    print(f"    - Applied backend: {plan.backend.value}")
    print(f"    - Explicit override: {backend_selection.get('explicit_override')}")
    print()


def test_auto_recommendation_called_when_not_specified():
    """
    Test: Auto-recommendation should be called when backend_preference is not specified.
    
    Scenario: No explicit backend_preference is set.
    Expected: backend_selector is called and recommendation is applied.
    """
    print("Test 2: Auto-recommendation is called when not specified...")
    
    planner = DispatchPlanner()
    
    # Create a decision WITHOUT explicit backend_preference
    decision = {
        "action": "proceed",
        "reason": "Continue with task",
        "metadata": {
            "orchestration_contract": {},  # No backend_preference
        },
    }
    
    # Create a continuation
    continuation = {
        "task_preview": "简单的数据查询任务",
        "next_step": "Query data",
        "next_owner": "main",
    }
    
    # Create dispatch plan
    plan = planner.create_plan(
        dispatch_id="dispatch_test_002",
        batch_id="batch_test_002",
        scenario="test_scenario",
        adapter="test_adapter",
        decision_id="decision_002",
        decision=decision,
        continuation=continuation,
        backend=DispatchBackend.SUBAGENT,  # Default
        allow_auto_dispatch=True,
        requester_session_key="agent:test",
    )
    
    # Verify: backend_selection metadata exists
    backend_selection = plan.orchestration_contract.get("backend_selection", {})
    assert backend_selection, "Expected backend_selection metadata to exist"
    assert backend_selection.get("auto_recommended") is True, (
        "Expected auto_recommended=True when no explicit preference"
    )
    
    print("  ✓ PASS: Auto-recommendation is called when not specified")
    print(f"    - Auto recommended: {backend_selection.get('auto_recommended')}")
    print(f"    - Recommended backend: {backend_selection.get('recommended_backend')}")
    print(f"    - Applied backend: {backend_selection.get('applied_backend')}")
    print()


def test_long_task_recommends_tmux():
    """
    Test: Long tasks (>30min) should recommend tmux backend.
    
    Scenario: Task with estimated_duration_minutes=60.
    Expected: backend_selector recommends tmux.
    """
    print("Test 3: Long task (>30min) recommends tmux...")
    
    planner = DispatchPlanner()
    
    decision = {
        "action": "proceed",
        "reason": "Long running task",
        "metadata": {
            "orchestration_contract": {},
            "estimated_duration_minutes": 60,  # Long task
        },
    }
    
    continuation = {
        "task_preview": "重构核心模块，预计 1 小时完成",
        "next_step": "Refactor core module",
        "next_owner": "main",
    }
    
    plan = planner.create_plan(
        dispatch_id="dispatch_test_003",
        batch_id="batch_test_003",
        scenario="test_scenario",
        adapter="test_adapter",
        decision_id="decision_003",
        decision=decision,
        continuation=continuation,
        backend=DispatchBackend.SUBAGENT,
        allow_auto_dispatch=True,
        requester_session_key="agent:test",
    )
    
    # Verify: backend should be tmux for long tasks
    backend_selection = plan.orchestration_contract.get("backend_selection", {})
    assert backend_selection.get("recommended_backend") == "tmux", (
        f"Expected recommended_backend=tmux for long task, got {backend_selection.get('recommended_backend')}"
    )
    assert plan.backend == DispatchBackend.TMUX, (
        f"Expected backend=TMUX for long task, got {plan.backend}"
    )
    
    print("  ✓ PASS: Long task recommends tmux")
    print(f"    - Recommended backend: {backend_selection.get('recommended_backend')}")
    print(f"    - Applied backend: {plan.backend.value}")
    print(f"    - Reason: {backend_selection.get('reason')}")
    print()


def test_short_task_recommends_subagent():
    """
    Test: Short tasks (<30min) should recommend subagent backend.
    
    Scenario: Task with estimated_duration_minutes=15.
    Expected: backend_selector recommends subagent.
    """
    print("Test 4: Short task (<30min) recommends subagent...")
    
    planner = DispatchPlanner()
    
    decision = {
        "action": "proceed",
        "reason": "Short task",
        "metadata": {
            "orchestration_contract": {},
            "estimated_duration_minutes": 15,  # Short task
        },
    }
    
    continuation = {
        "task_preview": "写一个 README 文档",
        "next_step": "Write README",
        "next_owner": "main",
    }
    
    plan = planner.create_plan(
        dispatch_id="dispatch_test_004",
        batch_id="batch_test_004",
        scenario="test_scenario",
        adapter="test_adapter",
        decision_id="decision_004",
        decision=decision,
        continuation=continuation,
        backend=DispatchBackend.SUBAGENT,
        allow_auto_dispatch=True,
        requester_session_key="agent:test",
    )
    
    # Verify: backend should remain subagent for short tasks
    backend_selection = plan.orchestration_contract.get("backend_selection", {})
    assert backend_selection.get("recommended_backend") == "subagent", (
        f"Expected recommended_backend=subagent for short task, got {backend_selection.get('recommended_backend')}"
    )
    assert plan.backend == DispatchBackend.SUBAGENT, (
        f"Expected backend=SUBAGENT for short task, got {plan.backend}"
    )
    
    print("  ✓ PASS: Short task recommends subagent")
    print(f"    - Recommended backend: {backend_selection.get('recommended_backend')}")
    print(f"    - Applied backend: {plan.backend.value}")
    print()


def test_coding_task_with_monitoring_recommends_tmux():
    """
    Test: Coding tasks with monitoring keywords should recommend tmux.
    
    Scenario: Task description contains coding + monitoring keywords.
    Expected: backend_selector recommends tmux.
    """
    print("Test 5: Coding task with monitoring recommends tmux...")
    
    planner = DispatchPlanner()
    
    decision = {
        "action": "proceed",
        "reason": "Debug task",
        "metadata": {
            "orchestration_contract": {},
        },
    }
    
    # Task with coding + monitoring keywords
    continuation = {
        "task_preview": "调试一个偶发的 bug，需要监控中间过程，观察状态",
        "next_step": "Debug intermittent bug",
        "next_owner": "main",
    }
    
    plan = planner.create_plan(
        dispatch_id="dispatch_test_005",
        batch_id="batch_test_005",
        scenario="test_scenario",
        adapter="test_adapter",
        decision_id="decision_005",
        decision=decision,
        continuation=continuation,
        backend=DispatchBackend.SUBAGENT,
        allow_auto_dispatch=True,
        requester_session_key="agent:test",
    )
    
    # Verify: backend should be tmux for monitoring tasks
    backend_selection = plan.orchestration_contract.get("backend_selection", {})
    assert backend_selection.get("recommended_backend") == "tmux", (
        f"Expected recommended_backend=tmux for monitoring task, got {backend_selection.get('recommended_backend')}"
    )
    assert plan.backend == DispatchBackend.TMUX, (
        f"Expected backend=TMUX for monitoring task, got {plan.backend}"
    )
    
    # Verify: factors include monitoring_keywords
    factors = backend_selection.get("factors", {})
    assert factors.get("monitoring_keywords", 0) > 0 or factors.get("monitoring_required"), (
        "Expected monitoring-related factors in backend_selection"
    )
    
    print("  ✓ PASS: Coding task with monitoring recommends tmux")
    print(f"    - Recommended backend: {backend_selection.get('recommended_backend')}")
    print(f"    - Applied backend: {plan.backend.value}")
    print(f"    - Reason: {backend_selection.get('reason')}")
    print()


def test_documentation_task_recommends_subagent():
    """
    Test: Documentation tasks should recommend subagent.
    
    Scenario: Task description contains documentation keywords.
    Expected: backend_selector recommends subagent.
    """
    print("Test 6: Documentation task recommends subagent...")
    
    planner = DispatchPlanner()
    
    decision = {
        "action": "proceed",
        "reason": "Documentation task",
        "metadata": {
            "orchestration_contract": {},
            "estimated_duration_minutes": 15,  # Short doc task → subagent path
        },
    }

    # Task with documentation keywords
    continuation = {
        "task_preview": "编写 API 文档，添加注释和说明",
        "next_step": "Write API documentation",
        "next_owner": "main",
    }

    plan = planner.create_plan(
        dispatch_id="dispatch_test_006",
        batch_id="batch_test_006",
        scenario="test_scenario",
        adapter="test_adapter",
        decision_id="decision_006",
        decision=decision,
        continuation=continuation,
        backend=DispatchBackend.SUBAGENT,
        allow_auto_dispatch=True,
        requester_session_key="agent:test",
    )
    
    # Verify: backend should remain subagent for documentation tasks
    backend_selection = plan.orchestration_contract.get("backend_selection", {})
    assert backend_selection.get("recommended_backend") == "subagent", (
        f"Expected recommended_backend=subagent for documentation task, got {backend_selection.get('recommended_backend')}"
    )
    assert plan.backend == DispatchBackend.SUBAGENT, (
        f"Expected backend=SUBAGENT for documentation task, got {plan.backend}"
    )
    
    print("  ✓ PASS: Documentation task recommends subagent")
    print(f"    - Recommended backend: {backend_selection.get('recommended_backend')}")
    print(f"    - Applied backend: {plan.backend.value}")
    print()


def test_backend_selection_metadata_recorded():
    """
    Test: Backend selection metadata should be recorded in orchestration_contract.
    
    Scenario: Any dispatch plan creation.
    Expected: orchestration_contract.backend_selection contains reason/factors.
    """
    print("Test 7: Backend selection metadata is recorded...")
    
    planner = DispatchPlanner()
    
    decision = {
        "action": "proceed",
        "reason": "Test task",
        "metadata": {
            "orchestration_contract": {},
        },
    }
    
    continuation = {
        "task_preview": "Test task for metadata verification",
        "next_step": "Verify metadata",
        "next_owner": "main",
    }
    
    plan = planner.create_plan(
        dispatch_id="dispatch_test_007",
        batch_id="batch_test_007",
        scenario="test_scenario",
        adapter="test_adapter",
        decision_id="decision_007",
        decision=decision,
        continuation=continuation,
        backend=DispatchBackend.SUBAGENT,
        allow_auto_dispatch=True,
        requester_session_key="agent:test",
    )
    
    # Verify: backend_selection metadata exists and has required fields
    backend_selection = plan.orchestration_contract.get("backend_selection", {})
    
    assert "recommended_backend" in backend_selection, (
        "Missing 'recommended_backend' in backend_selection"
    )
    assert "reason" in backend_selection, (
        "Missing 'reason' in backend_selection"
    )
    assert "factors" in backend_selection, (
        "Missing 'factors' in backend_selection"
    )
    assert "confidence" in backend_selection, (
        "Missing 'confidence' in backend_selection"
    )
    
    # Verify: factors is a dict with meaningful content
    factors = backend_selection.get("factors", {})
    assert isinstance(factors, dict), "Expected factors to be a dict"
    
    print("  ✓ PASS: Backend selection metadata is recorded")
    print(f"    - Recommended backend: {backend_selection.get('recommended_backend')}")
    print(f"    - Reason: {backend_selection.get('reason')}")
    print(f"    - Confidence: {backend_selection.get('confidence')}")
    print(f"    - Factors: {json.dumps(factors, indent=6)}")
    print()


def test_backend_selector_direct_api():
    """
    Test: Direct backend_selector API tests (unit tests for the selector itself).
    
    Scenario: Various task descriptions.
    Expected: Correct recommendations based on task characteristics.
    """
    print("Test 8: Backend selector direct API tests...")
    
    selector = BackendSelector()
    
    test_cases = [
        {
            "name": "Long coding task",
            "task": "重构认证模块，预计 1 小时",
            "estimated_duration_minutes": 60,
            "expected": "tmux",
        },
        {
            "name": "Short documentation task",
            "task": "写一个 README 文档",
            "estimated_duration_minutes": 15,
            "expected": "subagent",
        },
        {
            "name": "Debugging with monitoring",
            "task": "调试 bug，需要监控",
            "requires_monitoring": True,
            "expected": "tmux",
        },
        {
            "name": "Simple query",
            "task": "简单的数据查询",
            "estimated_duration_minutes": 5,
            "expected": "subagent",
        },
        {
            "name": "User preference override",
            "task": "长任务但用户指定 subagent",
            "estimated_duration_minutes": 60,
            "user_preference": "subagent",
            "expected": "subagent",
        },
    ]
    
    for case in test_cases:
        rec = selector.recommend(
            task_description=case["task"],
            estimated_duration_minutes=case.get("estimated_duration_minutes"),
            requires_monitoring=case.get("requires_monitoring"),
            user_preference=case.get("user_preference"),
        )
        
        assert rec.backend == case["expected"], (
            f"Test '{case['name']}': Expected {case['expected']}, got {rec.backend}"
        )
        
        print(f"  ✓ {case['name']}: {rec.backend} (confidence={rec.confidence:.2f})")
    
    print("  ✓ PASS: All backend selector direct API tests passed")
    print()


def run_all_tests():
    """Run all tests."""
    print("=" * 70)
    print("Backend Selector Integration Tests")
    print("P0-3 Batch 7 (2026-03-30)")
    print("=" * 70)
    print()
    
    tests = [
        test_explicit_backend_preference_not_overridden,
        test_auto_recommendation_called_when_not_specified,
        test_long_task_recommends_tmux,
        test_short_task_recommends_subagent,
        test_coding_task_with_monitoring_recommends_tmux,
        test_documentation_task_recommends_subagent,
        test_backend_selection_metadata_recorded,
        test_backend_selector_direct_api,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"  ✗ FAIL: {e}\n")
            failed += 1
        except Exception as e:
            print(f"  ✗ ERROR: {e}\n")
            failed += 1
    
    print("=" * 70)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 70)
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
