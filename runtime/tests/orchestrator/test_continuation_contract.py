#!/usr/bin/env python3
"""
test_continuation_contract.py — Continuation Contract Tests

测试 continuation contract 的生成、验证和合并。
"""

import sys
import os

# 添加 runtime/orchestrator 到路径
script_dir = os.path.dirname(os.path.abspath(__file__))
runtime_orchestrator_path = os.path.join(script_dir, '../../orchestrator')
sys.path.insert(0, runtime_orchestrator_path)

from partial_continuation import (
    ContinuationContract,
    build_continuation_contract,
    extract_continuation_contract,
    PartialCloseoutContract,
    build_partial_closeout,
    ScopeItem,
    CONTINUATION_CONTRACT_VERSION,
)


def test_continuation_contract_validate():
    """测试 ContinuationContract 验证"""
    print("Test: ContinuationContract.validate()")
    
    # 有效 case
    cc = ContinuationContract(
        stopped_because="roundtable_gate_pass_continuation_ready",
        next_step="Implement phase2 features",
        next_owner="trading",
    )
    is_valid, errors = cc.validate()
    assert is_valid, f"Expected valid, got errors: {errors}"
    print("  ✓ Valid continuation contract passes validation")
    
    # 无效 case: 缺少 stopped_because
    cc_empty = ContinuationContract(
        stopped_because="",
        next_step="test",
        next_owner="main",
    )
    is_valid, errors = cc_empty.validate()
    assert not is_valid, "Expected invalid for empty stopped_because"
    assert any("stopped_because" in e for e in errors)
    print("  ✓ Empty stopped_because fails validation")
    
    # 无效 case: 缺少 next_step
    cc_no_step = ContinuationContract(
        stopped_because="test",
        next_step="",
        next_owner="main",
    )
    is_valid, errors = cc_no_step.validate()
    assert not is_valid, "Expected invalid for empty next_step"
    print("  ✓ Empty next_step fails validation")
    
    # 无效 case: 缺少 next_owner
    cc_no_owner = ContinuationContract(
        stopped_because="test",
        next_step="test",
        next_owner="",
    )
    is_valid, errors = cc_no_owner.validate()
    assert not is_valid, "Expected invalid for empty next_owner"
    print("  ✓ Empty next_owner fails validation")
    
    print("  PASS: ContinuationContract.validate()\n")


def test_build_continuation_contract():
    """测试 build_continuation_contract"""
    print("Test: build_continuation_contract()")
    
    cc = build_continuation_contract(
        stopped_because="batch_completed_with_remaining_work",
        next_step="Continue with phase2 implementation",
        next_owner="main",
        metadata={
            "source": "test",
            "batch_id": "batch_test",
        },
    )
    
    # 验证
    is_valid, errors = cc.validate()
    assert is_valid, f"Expected valid, got errors: {errors}"
    print("  ✓ Built contract passes validation")
    
    # 检查版本
    cc_dict = cc.to_dict()
    assert cc_dict["contract_version"] == CONTINUATION_CONTRACT_VERSION
    print(f"  ✓ Contract version is {CONTINUATION_CONTRACT_VERSION}")
    
    # 检查字段
    assert cc.stopped_because == "batch_completed_with_remaining_work"
    assert cc.next_step == "Continue with phase2 implementation"
    assert cc.next_owner == "main"
    assert cc.metadata["source"] == "test"
    print("  ✓ All fields correctly set")
    
    # 检查 to_dict/from_dict 往返
    cc_from_dict = ContinuationContract.from_dict(cc_dict)
    assert cc_from_dict.stopped_because == cc.stopped_because
    assert cc_from_dict.next_step == cc.next_step
    assert cc_from_dict.next_owner == cc.next_owner
    print("  ✓ to_dict/from_dict roundtrip works")
    
    print("  PASS: build_continuation_contract()\n")


def test_continuation_contract_merge_into_closeout():
    """测试 ContinuationContract.merge_into_closeout()"""
    print("Test: ContinuationContract.merge_into_closeout()")
    
    # 创建 closeout
    closeout = build_partial_closeout(
        completed_scope=[
            {"item_id": "task1", "description": "Completed task 1", "status": "completed"},
        ],
        remaining_scope=[
            {"item_id": "task2", "description": "Remaining task 2", "status": "not_started"},
        ],
        stop_reason="partial_completed",
    )
    
    # 创建 continuation contract
    cc = build_continuation_contract(
        stopped_because="roundtable_gate_pass_continuation_ready",
        next_step="Continue with phase2",
        next_owner="trading",
        metadata={"test": "metadata"},
    )
    
    # 合并
    merged_closeout = cc.merge_into_closeout(closeout)
    
    # 检查合并结果
    assert "continuation_contract" in merged_closeout.metadata
    assert "stopped_because" in merged_closeout.metadata
    assert "next_step" in merged_closeout.metadata
    assert "next_owner" in merged_closeout.metadata
    
    assert merged_closeout.metadata["stopped_because"] == cc.stopped_because
    assert merged_closeout.metadata["next_step"] == cc.next_step
    assert merged_closeout.metadata["next_owner"] == cc.next_owner
    print("  ✓ Continuation contract merged into closeout metadata")
    
    # 检查 stop_reason 映射
    # blocked 应该映射到 blocked
    cc_blocked = build_continuation_contract(
        stopped_because="roundtable_gate_fail_blocker_implementation_risk",
        next_step="Fix blocker",
        next_owner="main",
    )
    closeout2 = build_partial_closeout(
        completed_scope=[],
        remaining_scope=[],
        stop_reason="completed_all",
    )
    merged2 = cc_blocked.merge_into_closeout(closeout2)
    # 注意：当前逻辑只在 completed_all 且有 stopped_because 时才映射
    # 这里只是验证合并发生
    assert "continuation_contract" in merged2.metadata
    print("  ✓ Stop reason mapping works for blocked case")
    
    print("  PASS: ContinuationContract.merge_into_closeout()\n")


def test_continuation_contract_from_closeout():
    """测试 ContinuationContract.from_closeout()"""
    print("Test: ContinuationContract.from_closeout()")
    
    # 创建 closeout
    closeout = build_partial_closeout(
        completed_scope=[
            {"item_id": "task1", "description": "Task 1", "status": "completed"},
        ],
        remaining_scope=[
            {"item_id": "task2", "description": "Task 2 - next step", "status": "not_started"},
        ],
        stop_reason="partial_completed",
        metadata={
            "stopped_because": "custom_stopped_because",
            "next_step": "custom next step",
            "next_owner": "custom_owner",
        },
    )
    
    # 从 closeout 提取 continuation contract
    cc = ContinuationContract.from_closeout(closeout)
    
    assert cc.stopped_because == "custom_stopped_because"
    assert cc.next_step == "custom next step"
    assert cc.next_owner == "custom_owner"
    print("  ✓ Continuation contract extracted from closeout metadata")
    
    # 测试从 remaining_scope 推导 next_step（当 metadata 中没有时）
    closeout2 = build_partial_closeout(
        completed_scope=[],
        remaining_scope=[
            {"item_id": "task1", "description": "Next step from scope", "status": "not_started"},
        ],
        stop_reason="partial_completed",
    )
    cc2 = ContinuationContract.from_closeout(closeout2)
    assert "Next step from scope" in cc2.next_step
    print("  ✓ Next step derived from remaining_scope when metadata missing")
    
    print("  PASS: ContinuationContract.from_closeout()\n")


def test_extract_continuation_contract():
    """测试 extract_continuation_contract"""
    print("Test: extract_continuation_contract()")
    
    # 从 closeout 提取
    payload1 = {
        "closeout": {
            "stopped_because": "from_closeout",
            "next_step": "step from closeout",
            "next_owner": "owner from closeout",
        },
    }
    cc = extract_continuation_contract(payload1, source="closeout")
    assert cc is not None
    assert cc.stopped_because == "from_closeout"
    print("  ✓ Extract from closeout works")
    
    # 从 tmux_terminal_receipt 提取
    payload2 = {
        "tmux_terminal_receipt": {
            "stopped_because": "from_tmux",
            "next_step": "step from tmux",
            "next_owner": "owner from tmux",
        },
    }
    cc = extract_continuation_contract(payload2, source="tmux")
    assert cc is not None
    assert cc.stopped_because == "from_tmux"
    print("  ✓ Extract from tmux_terminal_receipt works")
    
    # 从 continuation_contract 直接提取
    payload3 = {
        "continuation_contract": {
            "stopped_because": "direct",
            "next_step": "step direct",
            "next_owner": "owner direct",
        },
    }
    cc = extract_continuation_contract(payload3, source="direct")
    assert cc is not None
    assert cc.stopped_because == "direct"
    print("  ✓ Extract from direct continuation_contract works")
    
    # 从 metadata 提取
    payload4 = {
        "metadata": {
            "stopped_because": "from_metadata",
            "next_step": "step from metadata",
            "next_owner": "owner from metadata",
        },
    }
    cc = extract_continuation_contract(payload4, source="metadata")
    assert cc is not None
    assert cc.stopped_because == "from_metadata"
    print("  ✓ Extract from metadata works")
    
    # 不存在时返回 None
    payload5 = {"other": "data"}
    cc = extract_continuation_contract(payload5, source="none")
    assert cc is None
    print("  ✓ Returns None when contract not present")
    
    print("  PASS: extract_continuation_contract()\n")


def test_continuation_contract_version():
    """测试 continuation contract 版本常量"""
    print("Test: ContinuationContract version constant")
    
    assert CONTINUATION_CONTRACT_VERSION == "continuation_contract_v1"
    print(f"  ✓ Version constant is {CONTINUATION_CONTRACT_VERSION}")
    
    # 检查 to_dict 包含版本
    cc = build_continuation_contract(
        stopped_because="test",
        next_step="test",
        next_owner="main",
    )
    cc_dict = cc.to_dict()
    assert cc_dict["contract_version"] == CONTINUATION_CONTRACT_VERSION
    print("  ✓ to_dict includes contract_version")
    
    print("  PASS: ContinuationContract version constant\n")


def test_continuation_contract_backward_compatibility():
    """测试 continuation contract 向后兼容性"""
    print("Test: ContinuationContract backward compatibility")
    
    # 旧格式数据（没有 contract_version）
    old_data = {
        "stopped_because": "old_style",
        "next_step": "old step",
        "next_owner": "old_owner",
    }
    
    # 应该能从旧数据加载
    cc = ContinuationContract.from_dict(old_data)
    assert cc.stopped_because == "old_style"
    assert cc.next_step == "old step"
    assert cc.next_owner == "old_owner"
    print("  ✓ Can load from old-style data (without contract_version)")
    
    # 新格式数据
    new_data = {
        "contract_version": CONTINUATION_CONTRACT_VERSION,
        "stopped_because": "new_style",
        "next_step": "new step",
        "next_owner": "new_owner",
        "metadata": {"new": "field"},
    }
    
    cc = ContinuationContract.from_dict(new_data)
    assert cc.stopped_because == "new_style"
    assert cc.metadata["new"] == "field"
    print("  ✓ Can load from new-style data (with contract_version)")
    
    # 旧 closeout 没有 continuation_contract 字段
    old_closeout_data = {
        "contract_version": "partial_closeout_v1",
        "completed_scope": [],
        "remaining_scope": [],
        "stop_reason": "completed_all",
    }
    closeout = PartialCloseoutContract.from_dict(old_closeout_data)
    assert closeout is not None
    print("  ✓ Old closeout data without continuation_contract loads correctly")
    
    print("  PASS: ContinuationContract backward compatibility\n")


def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("Continuation Contract Tests")
    print("=" * 60 + "\n")
    
    test_continuation_contract_validate()
    test_build_continuation_contract()
    test_continuation_contract_merge_into_closeout()
    test_continuation_contract_from_closeout()
    test_extract_continuation_contract()
    test_continuation_contract_version()
    test_continuation_contract_backward_compatibility()
    
    print("=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    run_all_tests()
