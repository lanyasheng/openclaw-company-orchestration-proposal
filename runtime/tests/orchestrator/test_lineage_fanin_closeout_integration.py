#!/usr/bin/env python3
"""
test_lineage_fanin_closeout_integration.py — Parent-Child / Fan-in / Closeout Integration Tests

这是 P0 中等批次整合点 (batch-b-parent-child-fanin-closeout-integration) 的集成测试。

测试覆盖：
1. Happy path: 所有 children 完成，可以 fan-in
2. Not-ready path: 有 pending children，不能 fan-in
3. No lineage path: 没有 lineage records
4. 抽样回归测试

运行：
```bash
cd <repo-root>
python3 runtime/tests/orchestrator/test_lineage_fanin_closeout_integration.py
```
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from datetime import datetime

# 添加 orchestrator 目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "orchestrator"))

from lineage import (
    LineageStore,
    build_fanin_closeout_context,
    FaninCloseoutContext,
    _get_default_store,
    _save_lineage_index,
    LINEAGE_STORE_DIR,
)


# 测试计数器
passed = 0
failed = 0


def setup_temp_dirs(tmpdir: str):
    """设置临时目录用于测试隔离"""
    import lineage as lineage_module
    import closeout_tracker as closeout_module
    import completion_receipt as receipt_module
    
    # 临时覆盖存储目录
    lineage_module.LINEAGE_STORE_DIR = Path(tmpdir) / "lineage"
    closeout_module.CLOSEOUT_DIR = Path(tmpdir) / "closeout"
    receipt_module.COMPLETION_RECEIPT_DIR = Path(tmpdir) / "receipts"
    
    # 清空索引
    _save_lineage_index({})
    
    return lineage_module, closeout_module, receipt_module


def test_integration_happy_path_all_completed():
    """测试：Happy path - 所有 children 完成，可以 fan-in"""
    global passed, failed
    print("Test 1: Happy path - all children completed...")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        lineage_module, closeout_module, receipt_module = setup_temp_dirs(tmpdir)
        
        try:
            # 创建 lineage records
            batch_id = "batch_integration_happy"
            store = _get_default_store()
            
            # 创建 3 个 children
            for i in range(3):
                store.create_record(
                    parent_id="dispatch_parent_happy",
                    child_id=f"child_happy_{i}",
                    batch_id=batch_id,
                    relation_type="spawn",
                )
            
            # 为每个 child 创建 complete 状态的 closeout
            from closeout_tracker import create_closeout, ContinuationContract
            
            for i in range(3):
                create_closeout(
                    batch_id=f"child_happy_{i}",
                    scenario="integration_test",
                    continuation=ContinuationContract(
                        stopped_because="test_complete",
                        next_step="fan-in",
                        next_owner="main",
                    ),
                    has_remaining_work=False,
                    artifacts={},
                )
            
            # 构建整合上下文
            ctx = build_fanin_closeout_context(batch_id)
            
            # 验证
            assert isinstance(ctx, FaninCloseoutContext), f"Expected FaninCloseoutContext, got {type(ctx)}"
            assert ctx.batch_id == batch_id
            assert ctx.ready_to_fanin is True, f"Expected ready_to_fanin=True, got {ctx.ready_to_fanin}"
            assert ctx.fanin_decision == "proceed", f"Expected decision='proceed', got '{ctx.fanin_decision}'"
            assert ctx.readiness["ready"] is True
            assert ctx.readiness["total_children"] == 3
            assert ctx.readiness["completed_children"] == 3
            assert len(ctx.readiness["pending_children"]) == 0
            assert len(ctx.children) == 3
            
            # 验证每个 child 的 glue 数据
            for child_glue in ctx.children:
                assert child_glue["glue_available"] is True
                assert child_glue["status"] == "complete"
                assert "closeout_id" in child_glue
            
            passed += 1
            print("  ✓ PASS: Happy path - all children completed")
            
        finally:
            # 恢复原始目录
            lineage_module.LINEAGE_STORE_DIR = LINEAGE_STORE_DIR


def test_integration_not_ready_partial_completed():
    """测试：Not-ready path - 部分 children 完成，不能 fan-in"""
    global passed, failed
    print("Test 2: Not-ready path - partial children completed...")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        lineage_module, closeout_module, receipt_module = setup_temp_dirs(tmpdir)
        
        try:
            batch_id = "batch_integration_partial"
            store = _get_default_store()
            
            # 创建 3 个 children
            for i in range(3):
                store.create_record(
                    parent_id="dispatch_parent_partial",
                    child_id=f"child_partial_{i}",
                    batch_id=batch_id,
                    relation_type="spawn",
                )
            
            # 只为 2 个 child 创建 closeout
            from closeout_tracker import create_closeout, ContinuationContract
            
            for i in range(2):
                create_closeout(
                    batch_id=f"child_partial_{i}",
                    scenario="integration_test",
                    continuation=ContinuationContract(
                        stopped_because="test_complete",
                        next_step="fan-in",
                        next_owner="main",
                    ),
                    has_remaining_work=False,
                    artifacts={},
                )
            
            # child_partial_2 没有 closeout
            
            # 构建整合上下文
            ctx = build_fanin_closeout_context(batch_id)
            
            # 验证
            assert ctx.ready_to_fanin is False, f"Expected ready_to_fanin=False, got {ctx.ready_to_fanin}"
            assert ctx.fanin_decision == "wait", f"Expected decision='wait', got '{ctx.fanin_decision}'"
            assert ctx.readiness["ready"] is False
            assert ctx.readiness["total_children"] == 3
            assert ctx.readiness["completed_children"] == 2
            assert len(ctx.readiness["pending_children"]) == 1
            assert "child_partial_2" in ctx.readiness["pending_children"]
            
            # 验证 children glue 数据
            assert len(ctx.children) == 3
            
            # 找到 pending child 的 glue 数据
            pending_glue = [c for c in ctx.children if c["child_id"] == "child_partial_2"][0]
            assert pending_glue["glue_available"] is False
            assert pending_glue["status"] == "no_closeout"
            
            passed += 1
            print("  ✓ PASS: Not-ready path - partial children completed")
            
        finally:
            lineage_module.LINEAGE_STORE_DIR = LINEAGE_STORE_DIR


def test_integration_no_lineage():
    """测试：No lineage path - 没有 lineage records"""
    global passed, failed
    print("Test 3: No lineage path - no lineage records...")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        lineage_module, closeout_module, receipt_module = setup_temp_dirs(tmpdir)
        
        try:
            batch_id = "batch_no_lineage"
            
            # 不创建任何 lineage records
            
            # 构建整合上下文
            ctx = build_fanin_closeout_context(batch_id)
            
            # 验证
            assert ctx.ready_to_fanin is False
            assert ctx.fanin_decision == "review", f"Expected decision='review', got '{ctx.fanin_decision}'"
            assert ctx.readiness["ready"] is False
            assert ctx.readiness["total_children"] == 0
            assert ctx.readiness["details"]["error"] == "no_lineage"
            assert len(ctx.children) == 0
            
            passed += 1
            print("  ✓ PASS: No lineage path - no lineage records")
            
        finally:
            lineage_module.LINEAGE_STORE_DIR = LINEAGE_STORE_DIR


def test_integration_incomplete_closeout():
    """测试：Incomplete closeout - closeout 存在但未完成"""
    global passed, failed
    print("Test 4: Incomplete closeout - closeout exists but not complete...")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        lineage_module, closeout_module, receipt_module = setup_temp_dirs(tmpdir)
        
        try:
            batch_id = "batch_incomplete"
            store = _get_default_store()
            
            # 创建 2 个 children
            for i in range(2):
                store.create_record(
                    parent_id="dispatch_parent_incomplete",
                    child_id=f"child_incomplete_{i}",
                    batch_id=batch_id,
                    relation_type="spawn",
                )
            
            # child_0: complete
            # child_1: incomplete
            from closeout_tracker import create_closeout, ContinuationContract
            
            create_closeout(
                batch_id="child_incomplete_0",
                scenario="integration_test",
                continuation=ContinuationContract(
                    stopped_because="test_complete",
                    next_step="fan-in",
                    next_owner="main",
                ),
                has_remaining_work=False,
                artifacts={},
            )
            
            create_closeout(
                batch_id="child_incomplete_1",
                scenario="integration_test",
                continuation=ContinuationContract(
                    stopped_because="test_incomplete",
                    next_step="more work",
                    next_owner="main",
                ),
                has_remaining_work=True,
                artifacts={},
            )
            
            # 构建整合上下文
            ctx = build_fanin_closeout_context(batch_id)
            
            # 验证
            assert ctx.ready_to_fanin is False
            assert ctx.fanin_decision == "wait"
            assert ctx.readiness["ready"] is False
            assert ctx.readiness["completed_children"] == 1
            assert len(ctx.readiness["pending_children"]) == 1
            assert "child_incomplete_1" in ctx.readiness["pending_children"]
            
            # 验证 incomplete child 的状态
            incomplete_glue = [c for c in ctx.children if c["child_id"] == "child_incomplete_1"][0]
            assert incomplete_glue["status"] == "incomplete"
            assert incomplete_glue["closeout_status"] == "incomplete"
            
            passed += 1
            print("  ✓ PASS: Incomplete closeout - closeout exists but not complete")
            
        finally:
            lineage_module.LINEAGE_STORE_DIR = LINEAGE_STORE_DIR


def test_integration_context_serialization():
    """测试：FaninCloseoutContext 序列化"""
    global passed, failed
    print("Test 5: FaninCloseoutContext serialization...")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        lineage_module, closeout_module, receipt_module = setup_temp_dirs(tmpdir)
        
        try:
            batch_id = "batch_serialization"
            store = _get_default_store()
            
            # 创建 1 个 child
            store.create_record(
                parent_id="dispatch_parent_serialization",
                child_id="child_serialization",
                batch_id=batch_id,
                relation_type="spawn",
            )
            
            # 创建 closeout
            from closeout_tracker import create_closeout, ContinuationContract
            
            create_closeout(
                batch_id="child_serialization",
                scenario="integration_test",
                continuation=ContinuationContract(
                    stopped_because="test_complete",
                    next_step="fan-in",
                    next_owner="main",
                ),
                has_remaining_work=False,
                artifacts={},
            )
            
            # 构建整合上下文
            ctx = build_fanin_closeout_context(batch_id)
            
            # 序列化
            data = ctx.to_dict()
            
            # 验证序列化数据
            assert data["batch_id"] == batch_id
            assert data["ready_to_fanin"] is True
            assert data["fanin_decision"] == "proceed"
            assert "readiness" in data
            assert "children" in data
            assert "metadata" in data
            assert "integration_version" in data["metadata"]
            
            passed += 1
            print("  ✓ PASS: FaninCloseoutContext serialization")
            
        finally:
            lineage_module.LINEAGE_STORE_DIR = LINEAGE_STORE_DIR


def test_integration_regression_empty_batch():
    """回归测试：Empty batch - 有 lineage 但没有 closeout"""
    global passed, failed
    print("Test 6: Regression - empty batch (lineage exists, no closeout)...")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        lineage_module, closeout_module, receipt_module = setup_temp_dirs(tmpdir)
        
        try:
            batch_id = "batch_regression_empty"
            store = _get_default_store()
            
            # 创建 lineage 但不创建 closeout
            store.create_record(
                parent_id="dispatch_parent_regression",
                child_id="child_no_closeout",
                batch_id=batch_id,
                relation_type="spawn",
            )
            
            # 构建整合上下文
            ctx = build_fanin_closeout_context(batch_id)
            
            # 验证
            assert ctx.ready_to_fanin is False
            assert ctx.fanin_decision == "wait"
            assert ctx.readiness["ready"] is False
            assert ctx.readiness["total_children"] == 1
            assert ctx.readiness["completed_children"] == 0
            assert len(ctx.readiness["pending_children"]) == 1
            
            # 验证 child glue 数据
            assert len(ctx.children) == 1
            child_glue = ctx.children[0]
            assert child_glue["glue_available"] is False
            assert child_glue["status"] == "no_closeout"
            
            passed += 1
            print("  ✓ PASS: Regression - empty batch (lineage exists, no closeout)")
            
        finally:
            lineage_module.LINEAGE_STORE_DIR = LINEAGE_STORE_DIR


def run_all_tests():
    """运行所有测试"""
    global passed, failed
    
    print("=" * 70)
    print("Parent-Child / Fan-in / Closeout Integration Tests")
    print("P0 Batch-B: Parent-Child / Fan-in / Closeout Integration")
    print("=" * 70)
    
    tests = [
        test_integration_happy_path_all_completed,
        test_integration_not_ready_partial_completed,
        test_integration_no_lineage,
        test_integration_incomplete_closeout,
        test_integration_context_serialization,
        test_integration_regression_empty_batch,
    ]
    
    for test in tests:
        try:
            test()
        except AssertionError as e:
            failed += 1
            print(f"  ✗ FAIL: {test.__name__}: {e}")
            import traceback
            traceback.print_exc()
        except Exception as e:
            failed += 1
            print(f"  ✗ ERROR: {test.__name__}: {e}")
            import traceback
            traceback.print_exc()
    
    print("=" * 70)
    print(f"测试结果：{passed} passed, {failed} failed")
    print("=" * 70)
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
