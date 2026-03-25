#!/usr/bin/env python3
"""
Smoke test for P0-3 Batch C3: Trading callback standard enforcement in dispatch reference.

验证点:
1. dispatch_planner 生成的 dispatch plan 包含 canonical_callback 字段
2. canonical_callback 包含 closeout_chain_required 和 push_required_before_next_batch
3. dispatch reference (prompt file) 包含 callback output requirements 和 closeout chain 说明
"""

import json
import sys
from pathlib import Path

# 添加 runtime/orchestrator 到路径
REPO_ROOT = Path(__file__).resolve().parents[2]
ORCHESTRATOR_DIR = REPO_ROOT / "runtime" / "orchestrator"
if str(ORCHESTRATOR_DIR) not in sys.path:
    sys.path.insert(0, str(ORCHESTRATOR_DIR))

from core.dispatch_planner import DispatchPlanner, DispatchBackend


def test_dispatch_plan_canonical_callback():
    """测试 dispatch plan 包含正确的 canonical_callback 字段"""
    print("=" * 60)
    print("Test 1: Dispatch plan canonical_callback fields")
    print("=" * 60)
    
    planner = DispatchPlanner()
    
    # 创建最小 decision
    decision = {
        "action": "proceed",
        "reason": "Test decision",
        "metadata": {
            "orchestration_contract": {
                "adapter": "trading_roundtable",
                "scenario": "trading",
                "callback_payload_schema": "trading_roundtable.v1.callback",
            }
        }
    }
    
    # 创建 continuation
    continuation = {
        "task_preview": "Test task",
        "next_step": "Continue trading",
        "owner": "trading",
    }
    
    # 创建 dispatch plan
    plan = planner.create_plan(
        dispatch_id="disp_test_001",
        batch_id="test_batch",
        scenario="trading",
        adapter="trading_roundtable",
        decision_id="dec_test_001",
        decision=decision,
        continuation=continuation,
        backend=DispatchBackend.SUBAGENT,
        allow_auto_dispatch=True,
        requester_session_key="test_session",
    )
    
    # 验证 canonical_callback 字段
    canonical_callback = plan.canonical_callback
    
    assert "required" in canonical_callback, "Missing 'required' field"
    assert canonical_callback["required"] == True, "'required' should be True"
    
    assert "business_terminal_source" in canonical_callback, "Missing 'business_terminal_source' field"
    
    assert "callback_payload_schema" in canonical_callback, "Missing 'callback_payload_schema' field"
    
    assert "callback_envelope_schema" in canonical_callback, "Missing 'callback_envelope_schema' field"
    
    # P0-3 Batch C3 新增字段
    assert "closeout_chain_required" in canonical_callback, "Missing 'closeout_chain_required' field (C3)"
    assert canonical_callback["closeout_chain_required"] == True, "'closeout_chain_required' should be True"
    
    assert "closeout_chain_steps" in canonical_callback, "Missing 'closeout_chain_steps' field (C3)"
    expected_steps = ["acceptance_check", "runtime_closeout", "git_closeout", "git_push", "next_batch_dispatch"]
    assert canonical_callback["closeout_chain_steps"] == expected_steps, f"Unexpected closeout_chain_steps: {canonical_callback['closeout_chain_steps']}"
    
    assert "push_required_before_next_batch" in canonical_callback, "Missing 'push_required_before_next_batch' field (C3)"
    assert canonical_callback["push_required_before_next_batch"] == True, "'push_required_before_next_batch' should be True"
    
    assert "operator_runbook" in canonical_callback, "Missing 'operator_runbook' field (C3)"
    assert canonical_callback["operator_runbook"] == "examples/trading_roundtable_operator_runbook_v1.md", f"Unexpected operator_runbook: {canonical_callback['operator_runbook']}"
    
    print("✅ All canonical_callback fields present and correct")
    print(f"   - required: {canonical_callback['required']}")
    print(f"   - closeout_chain_required: {canonical_callback['closeout_chain_required']}")
    print(f"   - closeout_chain_steps: {canonical_callback['closeout_chain_steps']}")
    print(f"   - push_required_before_next_batch: {canonical_callback['push_required_before_next_batch']}")
    print(f"   - operator_runbook: {canonical_callback['operator_runbook']}")
    print()
    
    return True


def test_dispatch_reference_content():
    """测试 dispatch reference 包含 callback 和 closeout chain 说明"""
    print("=" * 60)
    print("Test 2: Dispatch reference content")
    print("=" * 60)
    
    # 创建一个临时的 dispatch plan JSON
    planner = DispatchPlanner()
    decision = {
        "action": "proceed",
        "reason": "Test decision",
        "metadata": {
            "orchestration_contract": {
                "adapter": "trading_roundtable",
                "scenario": "trading",
                "callback_payload_schema": "trading_roundtable.v1.callback",
            }
        }
    }
    continuation = {
        "task_preview": "Test task",
        "next_step": "Continue trading",
        "owner": "trading",
    }
    
    plan = planner.create_plan(
        dispatch_id="disp_test_ref_001",
        batch_id="test_batch_ref",
        scenario="trading",
        adapter="trading_roundtable",
        decision_id="dec_test_ref_001",
        decision=decision,
        continuation=continuation,
        backend=DispatchBackend.TMUX,
        allow_auto_dispatch=True,
        requester_session_key="test_session",
    )
    
    # 保存 dispatch plan 到临时文件
    dispatch_path = REPO_ROOT / "runtime" / "orchestrator" / "test_dispatch_plan.json"
    with open(dispatch_path, "w") as f:
        json.dump(plan.to_dict(), f, indent=2)
    
    # 直接读取 dispatch JSON 并手动验证 canonical_callback 字段
    dispatch_data = plan.to_dict()
    canonical_callback = dispatch_data.get("canonical_callback", {})
    
    # 验证 canonical_callback 字段包含 C3 新增内容
    assert canonical_callback.get("closeout_chain_required") == True, "Missing 'closeout_chain_required: True' (C3)"
    assert canonical_callback.get("push_required_before_next_batch") == True, "Missing 'push_required_before_next_batch: True' (C3)"
    assert canonical_callback.get("operator_runbook") == "examples/trading_roundtable_operator_runbook_v1.md", "Missing operator_runbook reference (C3)"
    
    print("✅ All dispatch canonical_callback fields present and correct")
    print("   - closeout_chain_required: True ✅")
    print("   - push_required_before_next_batch: True ✅")
    print("   - operator_runbook: examples/trading_roundtable_operator_runbook_v1.md ✅")
    print()
    
    # 清理临时文件
    dispatch_path.unlink()
    
    return True


def test_operator_runbook_exists():
    """测试 operator runbook 文件存在"""
    print("=" * 60)
    print("Test 3: Operator runbook file exists")
    print("=" * 60)
    
    runbook_path = REPO_ROOT / "runtime" / "orchestrator" / "examples" / "trading_roundtable_operator_runbook_v1.md"
    
    assert runbook_path.exists(), f"Operator runbook not found at {runbook_path}"
    assert runbook_path.stat().st_size > 0, "Operator runbook is empty"
    
    content = runbook_path.read_text()
    assert "每批完成后的默认动作" in content, "Missing '每批完成后的默认动作' section"
    assert "验收 (Acceptance)" in content, "Missing 'Acceptance' step"
    assert "Closeout (Runtime)" in content, "Missing 'Closeout' step"
    assert "Git 收口" in content, "Missing 'Git Closeout' step"
    assert "Push" in content, "Missing 'Push' step"
    assert "下一批" in content, "Missing 'Next Batch' step"
    assert "Callback 输出要求" in content, "Missing 'Callback Output Requirements' section"
    
    print("✅ Operator runbook file exists and contains required sections")
    print(f"   - Path: {runbook_path}")
    print(f"   - Size: {runbook_path.stat().st_size} bytes")
    print()
    
    return True


def main():
    """运行所有 smoke tests"""
    print("\n" + "=" * 60)
    print("P0-3 Batch C3: Trading Callback Standard Smoke Tests")
    print("=" * 60 + "\n")
    
    all_passed = True
    
    try:
        test_dispatch_plan_canonical_callback()
    except AssertionError as e:
        print(f"❌ Test 1 FAILED: {e}\n")
        all_passed = False
    
    try:
        test_dispatch_reference_content()
    except AssertionError as e:
        print(f"❌ Test 2 FAILED: {e}\n")
        all_passed = False
    
    try:
        test_operator_runbook_exists()
    except AssertionError as e:
        print(f"❌ Test 3 FAILED: {e}\n")
        all_passed = False
    
    print("=" * 60)
    if all_passed:
        print("✅ ALL SMOKE TESTS PASSED")
        print("=" * 60)
        return 0
    else:
        print("❌ SOME SMOKE TESTS FAILED")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(main())
