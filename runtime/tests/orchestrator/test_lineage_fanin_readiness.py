#!/usr/bin/env python3
"""
test_lineage_fanin_readiness.py — Fan-in Readiness Check Tests

测试 fan-in readiness check 功能：
1. readiness 判定通过/不通过
2. 最小接线测试
3. 抽样回归测试
"""

import json
import os
import sys
import tempfile
from pathlib import Path
from datetime import datetime

# 添加 orchestrator 目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "orchestrator"))

from lineage import (
    LineageRecord,
    LineageStore,
    create_lineage_record,
    get_lineage_by_batch,
    check_fanin_readiness,
    _get_default_store,
)


def test_fanin_readiness_no_lineage():
    """测试：没有 lineage records 时返回 not ready"""
    print("Test 1: Fan-in readiness with no lineage records...")
    
    result = check_fanin_readiness("nonexistent_batch")
    
    assert result["ready"] is False
    assert result["reason"] == "No lineage records found for batch"
    assert result["total_children"] == 0
    assert result["completed_children"] == 0
    assert result["pending_children"] == []
    
    print("  ✓ PASS: No lineage records returns not ready")


def test_fanin_readiness_all_completed():
    """测试：所有 child 都完成时返回 ready"""
    print("Test 2: Fan-in readiness with all children completed...")
    
    import lineage as lineage_module
    import closeout_tracker as closeout_module
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # 临时覆盖 lineage 和 closeout 目录
        original_lineage_dir = lineage_module.LINEAGE_STORE_DIR
        original_closeout_dir = closeout_module.CLOSEOUT_DIR
        
        lineage_module.LINEAGE_STORE_DIR = Path(tmpdir) / "lineage"
        closeout_module.CLOSEOUT_DIR = Path(tmpdir) / "closeout"
        
        # 清空索引
        lineage_module._save_lineage_index({})
        
        try:
            # 创建 lineage records
            batch_id = "batch_test_complete"
            store = _get_default_store()
            
            # 创建 3 个 child
            for i in range(3):
                store.create_record(
                    parent_id="dispatch_parent",
                    child_id=f"child_{i}",
                    batch_id=batch_id,
                    relation_type="spawn",
                )
            
            # 创建 complete 状态的 closeout
            from closeout_tracker import create_closeout, ContinuationContract
            
            for i in range(3):
                create_closeout(
                    batch_id=f"child_{i}",
                    scenario="test",
                    continuation=ContinuationContract(
                        stopped_because="test_complete",
                        next_step="done",
                        next_owner="test",
                    ),
                    has_remaining_work=False,
                    artifacts={},
                )
            
            # 检查 readiness
            result = check_fanin_readiness(batch_id)
            
            assert result["ready"] is True, f"Expected ready=True, got {result}"
            assert result["reason"] == "All 3 children completed"
            assert result["total_children"] == 3
            assert result["completed_children"] == 3
            assert result["pending_children"] == []
            
            print("  ✓ PASS: All children completed returns ready")
            
        finally:
            lineage_module.LINEAGE_STORE_DIR = original_lineage_dir
            closeout_module.CLOSEOUT_DIR = original_closeout_dir


def test_fanin_readiness_partial_completed():
    """测试：部分 child 完成时返回 not ready"""
    print("Test 3: Fan-in readiness with partial children completed...")
    
    import lineage as lineage_module
    import closeout_tracker as closeout_module
    
    with tempfile.TemporaryDirectory() as tmpdir:
        original_lineage_dir = lineage_module.LINEAGE_STORE_DIR
        original_closeout_dir = closeout_module.CLOSEOUT_DIR
        
        lineage_module.LINEAGE_STORE_DIR = Path(tmpdir) / "lineage"
        closeout_module.CLOSEOUT_DIR = Path(tmpdir) / "closeout"
        
        lineage_module._save_lineage_index({})
        
        try:
            batch_id = "batch_test_partial"
            store = _get_default_store()
            
            # 创建 3 个 child
            for i in range(3):
                store.create_record(
                    parent_id="dispatch_parent",
                    child_id=f"child_{i}",
                    batch_id=batch_id,
                    relation_type="spawn",
                )
            
            # 只创建 2 个 complete closeout
            from closeout_tracker import create_closeout, ContinuationContract
            
            for i in range(2):
                create_closeout(
                    batch_id=f"child_{i}",
                    scenario="test",
                    continuation=ContinuationContract(
                        stopped_because="test_complete",
                        next_step="done",
                        next_owner="test",
                    ),
                    has_remaining_work=False,
                    artifacts={},
                )
            
            # child_2 没有 closeout
            
            # 检查 readiness
            result = check_fanin_readiness(batch_id)
            
            assert result["ready"] is False
            assert "2/3 children pending" in result["reason"] or "1/3 children pending" in result["reason"]
            assert result["total_children"] == 3
            assert result["completed_children"] == 2
            assert len(result["pending_children"]) == 1
            assert "child_2" in result["pending_children"]
            
            print("  ✓ PASS: Partial children completed returns not ready")
            
        finally:
            lineage_module.LINEAGE_STORE_DIR = original_lineage_dir
            closeout_module.CLOSEOUT_DIR = original_closeout_dir


def test_fanin_readiness_incomplete_closeout():
    """测试：closeout 存在但未完成时返回 not ready"""
    print("Test 4: Fan-in readiness with incomplete closeout...")
    
    import lineage as lineage_module
    import closeout_tracker as closeout_module
    
    with tempfile.TemporaryDirectory() as tmpdir:
        original_lineage_dir = lineage_module.LINEAGE_STORE_DIR
        original_closeout_dir = closeout_module.CLOSEOUT_DIR
        
        lineage_module.LINEAGE_STORE_DIR = Path(tmpdir) / "lineage"
        closeout_module.CLOSEOUT_DIR = Path(tmpdir) / "closeout"
        
        lineage_module._save_lineage_index({})
        
        try:
            batch_id = "batch_test_incomplete"
            store = _get_default_store()
            
            # 创建 2 个 child
            for i in range(2):
                store.create_record(
                    parent_id="dispatch_parent",
                    child_id=f"child_{i}",
                    batch_id=batch_id,
                    relation_type="spawn",
                )
            
            # 创建 1 个 complete，1 个 incomplete
            from closeout_tracker import create_closeout, ContinuationContract
            
            # child_0: complete
            create_closeout(
                batch_id="child_0",
                scenario="test",
                continuation=ContinuationContract(
                    stopped_because="test_complete",
                    next_step="done",
                    next_owner="test",
                ),
                has_remaining_work=False,
                artifacts={},
            )
            
            # child_1: incomplete
            create_closeout(
                batch_id="child_1",
                scenario="test",
                continuation=ContinuationContract(
                    stopped_because="test_incomplete",
                    next_step="more work",
                    next_owner="test",
                ),
                has_remaining_work=True,
                artifacts={},
            )
            
            # 检查 readiness
            result = check_fanin_readiness(batch_id)
            
            assert result["ready"] is False
            assert result["total_children"] == 2
            assert result["completed_children"] == 1
            assert len(result["pending_children"]) == 1
            assert "child_1" in result["pending_children"]
            
            # 验证 details 中包含 closeout 状态
            assert result["details"]["children"]["child_1"]["status"] == "incomplete"
            
            print("  ✓ PASS: Incomplete closeout returns not ready")
            
        finally:
            lineage_module.LINEAGE_STORE_DIR = original_lineage_dir
            closeout_module.CLOSEOUT_DIR = original_closeout_dir


def test_fanin_readiness_minimal_wiring():
    """测试：最小接线到 lineage 模块"""
    print("Test 5: Minimal wiring to lineage module...")
    
    # 验证 check_fanin_readiness 函数存在并可调用
    import inspect
    
    sig = inspect.signature(check_fanin_readiness)
    params = list(sig.parameters.keys())
    assert params == ["batch_id"], f"Expected ['batch_id'], got {params}"
    
    # 验证返回值类型
    result = check_fanin_readiness("test_batch")
    assert isinstance(result, dict)
    assert "ready" in result
    assert "reason" in result
    assert "total_children" in result
    assert "completed_children" in result
    assert "pending_children" in result
    assert "details" in result
    
    print("  ✓ PASS: Minimal wiring to lineage module")


def test_fanin_readiness_regression_empty_batch():
    """回归测试：空 batch 的处理"""
    print("Test 6: Regression test - empty batch...")
    
    import lineage as lineage_module
    import closeout_tracker as closeout_module
    
    with tempfile.TemporaryDirectory() as tmpdir:
        original_lineage_dir = lineage_module.LINEAGE_STORE_DIR
        original_closeout_dir = closeout_module.CLOSEOUT_DIR
        
        lineage_module.LINEAGE_STORE_DIR = Path(tmpdir) / "lineage"
        closeout_module.CLOSEOUT_DIR = Path(tmpdir) / "closeout"
        
        lineage_module._save_lineage_index({})
        
        try:
            # 创建 lineage record 但没有 closeout
            batch_id = "batch_empty"
            store = _get_default_store()
            
            store.create_record(
                parent_id="dispatch_parent",
                child_id="child_no_closeout",
                batch_id=batch_id,
                relation_type="spawn",
            )
            
            # 不创建 closeout
            
            result = check_fanin_readiness(batch_id)
            
            assert result["ready"] is False
            assert result["total_children"] == 1
            assert result["completed_children"] == 0
            assert len(result["pending_children"]) == 1
            
            # 验证 details 中包含 no_closeout 状态
            assert result["details"]["children"]["child_no_closeout"]["status"] == "no_closeout"
            
            print("  ✓ PASS: Empty batch (no closeout) handled correctly")
            
        finally:
            lineage_module.LINEAGE_STORE_DIR = original_lineage_dir
            closeout_module.CLOSEOUT_DIR = original_closeout_dir


def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("Fan-in Readiness Check Tests")
    print("=" * 60)
    
    tests = [
        test_fanin_readiness_no_lineage,
        test_fanin_readiness_all_completed,
        test_fanin_readiness_partial_completed,
        test_fanin_readiness_incomplete_closeout,
        test_fanin_readiness_minimal_wiring,
        test_fanin_readiness_regression_empty_batch,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"  ✗ FAIL: {test.__name__}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print("=" * 60)
    print(f"测试结果：{passed} passed, {failed} failed")
    print("=" * 60)
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
