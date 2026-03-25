#!/usr/bin/env python3
"""
test_lineage.py — Lineage 数据结构 + 最小接线测试

测试覆盖：
1. LineageRecord 数据结构测试（序列化/反序列化）
2. LineageStore CRUD 测试
3. 最小接线测试（sessions_spawn_bridge 集成）
4. 回归测试（不破坏现有 contract）
"""

import json
import os
import sys
import tempfile
import shutil
from pathlib import Path
from datetime import datetime

# 添加 orchestrator 目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "orchestrator"))

from lineage import (
    LineageRecord,
    LineageStore,
    create_lineage_record,
    list_lineage_records,
    get_lineage_record,
    get_lineage_by_parent,
    get_lineage_by_child,
    get_lineage_by_batch,
    LINEAGE_VERSION,
    LINEAGE_STORE_DIR,
    _ensure_lineage_dir,
    _load_lineage_index,
    _save_lineage_index,
)


def test_lineage_record_serialization():
    """测试 LineageRecord 序列化/反序列化"""
    print("Test 1: LineageRecord serialization/deserialization...")
    
    # 创建 record
    record = LineageRecord(
        lineage_id="lineage_test123",
        parent_id="dispatch_abc123",
        child_id="task_xyz789",
        batch_id="batch_001",
        relation_type="spawn",
        metadata={"source": "test", "scenario": "testing"},
    )
    
    # 序列化
    data = record.to_dict()
    assert data["lineage_id"] == "lineage_test123"
    assert data["parent_id"] == "dispatch_abc123"
    assert data["child_id"] == "task_xyz789"
    assert data["batch_id"] == "batch_001"
    assert data["relation_type"] == "spawn"
    assert data["version"] == LINEAGE_VERSION
    assert "created_at" in data
    assert data["metadata"]["source"] == "test"
    
    # 反序列化
    record2 = LineageRecord.from_dict(data)
    assert record2.lineage_id == record.lineage_id
    assert record2.parent_id == record.parent_id
    assert record2.child_id == record.child_id
    assert record2.batch_id == record.batch_id
    assert record2.relation_type == record.relation_type
    assert record2.metadata == record.metadata
    
    # JSON 序列化/反序列化
    json_str = record.to_json()
    record3 = LineageRecord.from_json(json_str)
    assert record3.lineage_id == record.lineage_id
    assert record3.parent_id == record.parent_id
    
    print("  ✓ PASS: LineageRecord serialization/deserialization")
    return True


def test_lineage_record_defaults():
    """测试 LineageRecord 默认值"""
    print("Test 2: LineageRecord default values...")
    
    record = LineageRecord(
        lineage_id="lineage_default",
        parent_id="parent_123",
        child_id="child_456",
    )
    
    assert record.batch_id is None
    assert record.relation_type == "spawn"
    assert record.metadata == {}
    assert len(record.created_at) > 0  # created_at is a string
    
    print("  ✓ PASS: LineageRecord default values")
    return True


def test_lineage_store_crud():
    """测试 LineageStore CRUD 操作"""
    print("Test 3: LineageStore CRUD operations...")
    
    import lineage as lineage_module
    
    # 使用临时目录
    with tempfile.TemporaryDirectory() as tmpdir:
        # 临时覆盖 LINEAGE_STORE_DIR
        original_dir = lineage_module.LINEAGE_STORE_DIR
        lineage_module.LINEAGE_STORE_DIR = Path(tmpdir)
        # 清空索引
        lineage_module._save_lineage_index({})
        
        try:
            store = LineageStore()
            
            # Create
            record1 = store.create_record(
                parent_id="parent_1",
                child_id="child_1",
                batch_id="batch_A",
                relation_type="spawn",
                metadata={"test": "create"},
            )
            assert record1.lineage_id.startswith("lineage_")
            assert record1.parent_id == "parent_1"
            assert record1.child_id == "child_1"
            
            # Read
            record_read = store.get_record(record1.lineage_id)
            assert record_read is not None
            assert record_read.lineage_id == record1.lineage_id
            
            # List (no filter)
            all_records = store.list_records()
            assert len(all_records) == 1
            
            # List (with filter)
            by_parent = store.list_records(parent_id="parent_1")
            assert len(by_parent) == 1
            assert by_parent[0].child_id == "child_1"
            
            by_child = store.list_records(child_id="child_1")
            assert len(by_child) == 1
            assert by_child[0].parent_id == "parent_1"
            
            by_batch = store.list_records(batch_id="batch_A")
            assert len(by_batch) == 1
            
            # Create more records
            record2 = store.create_record(
                parent_id="parent_1",
                child_id="child_2",
                batch_id="batch_A",
                relation_type="continuation",
            )
            
            record3 = store.create_record(
                parent_id="parent_2",
                child_id="child_3",
                batch_id="batch_B",
                relation_type="retry",
            )
            
            # List with filters
            parent1_children = store.list_records(parent_id="parent_1")
            assert len(parent1_children) == 2
            
            batch_a_records = store.list_records(batch_id="batch_A")
            assert len(batch_a_records) == 2
            
            spawn_records = store.list_records(relation_type="spawn")
            assert len(spawn_records) == 1  # record1 only (record2 is continuation)
            
            # Get by parent/child/batch helpers
            by_parent_helper = store.get_by_parent("parent_1")
            assert len(by_parent_helper) == 2
            
            by_child_helper = store.get_by_child("child_3")
            assert len(by_child_helper) == 1
            
            by_batch_helper = store.get_by_batch("batch_B")
            assert len(by_batch_helper) == 1
            
            print("  ✓ PASS: LineageStore CRUD operations")
            return True
            
        finally:
            # 恢复原始目录
            lineage_module.LINEAGE_STORE_DIR = original_dir


def test_lineage_convenience_functions():
    """测试便捷函数"""
    print("Test 4: Lineage convenience functions...")
    
    import lineage as lineage_module
    
    with tempfile.TemporaryDirectory() as tmpdir:
        original_dir = lineage_module.LINEAGE_STORE_DIR
        lineage_module.LINEAGE_STORE_DIR = Path(tmpdir)
        
        try:
            # Create using convenience function
            record = lineage_module.create_lineage_record(
                parent_id="dispatch_test",
                child_id="task_test",
                batch_id="batch_test",
                relation_type="followup",
                metadata={"convenience": "test"},
            )
            
            # Get using convenience function
            retrieved = lineage_module.get_lineage_record(record.lineage_id)
            assert retrieved is not None
            assert retrieved.lineage_id == record.lineage_id
            
            # List using convenience functions
            by_parent = lineage_module.get_lineage_by_parent("dispatch_test")
            assert len(by_parent) == 1
            
            by_child = lineage_module.get_lineage_by_child("task_test")
            assert len(by_child) == 1
            
            by_batch = lineage_module.get_lineage_by_batch("batch_test")
            assert len(by_batch) == 1
            
            print("  ✓ PASS: Lineage convenience functions")
            return True
            
        finally:
            lineage_module.LINEAGE_STORE_DIR = original_dir


def test_lineage_relation_types():
    """测试所有 relation_type 值"""
    print("Test 5: Lineage relation types...")
    
    relation_types = ["spawn", "continuation", "followup", "retry", "fanin", "other"]
    
    for rel_type in relation_types:
        record = LineageRecord(
            lineage_id=f"lineage_{rel_type}",
            parent_id="parent",
            child_id="child",
            relation_type=rel_type,  # type: ignore
        )
        assert record.relation_type == rel_type
    
    print("  ✓ PASS: Lineage relation types")
    return True


def test_lineage_minimal_wiring():
    """测试最小接线（sessions_spawn_bridge 集成）"""
    print("Test 6: Minimal wiring to sessions_spawn_bridge...")
    
    # 这个测试验证 lineage 模块可以正确导入和集成
    # 实际集成测试在 test_sessions_spawn_bridge_lineage_integration.py
    
    try:
        from sessions_spawn_bridge import SessionsSpawnBridge, SessionsSpawnAPIExecution
        
        # 验证 SessionsSpawnAPIExecution 有 lineage_id 字段
        import inspect
        sig = inspect.signature(SessionsSpawnAPIExecution.__init__)
        params = list(sig.parameters.keys())
        assert "lineage_id" in params, "SessionsSpawnAPIExecution should have lineage_id parameter"
        
        # 验证可以创建包含 lineage_id 的实例
        from datetime import datetime
        
        def _iso_now():
            return datetime.now().isoformat()
        
        artifact = SessionsSpawnAPIExecution(
            execution_id="exec_test",
            source_request_id="req_test",
            source_receipt_id="receipt_test",
            source_execution_id="exec_source_test",
            source_spawn_id="spawn_test",
            source_dispatch_id="dispatch_test",
            source_registration_id="reg_test",
            source_task_id="task_test",
            api_execution_status="started",
            api_execution_reason="test",
            api_execution_time=_iso_now(),
            lineage_id="lineage_test123",
        )
        
        assert artifact.lineage_id == "lineage_test123"
        
        # 验证序列化包含 lineage_id
        data = artifact.to_dict()
        assert "lineage_id" in data
        assert data["lineage_id"] == "lineage_test123"
        
        # 验证反序列化
        artifact2 = SessionsSpawnAPIExecution.from_dict(data)
        assert artifact2.lineage_id == "lineage_test123"
        
        print("  ✓ PASS: Minimal wiring to sessions_spawn_bridge")
        return True
        
    except ImportError as e:
        print(f"  ✗ FAIL: Cannot import sessions_spawn_bridge: {e}")
        return False


def test_lineage_backward_compatibility():
    """测试向后兼容性（lineage_id 为 None 时正常工作）"""
    print("Test 7: Backward compatibility (lineage_id=None)...")
    
    from datetime import datetime
    
    def _iso_now():
        return datetime.now().isoformat()
    
    from sessions_spawn_bridge import SessionsSpawnAPIExecution
    
    # 创建不包含 lineage_id 的 artifact（向后兼容）
    artifact = SessionsSpawnAPIExecution(
        execution_id="exec_compat",
        source_request_id="req_compat",
        source_receipt_id="receipt_compat",
        source_execution_id="exec_source_compat",
        source_spawn_id="spawn_compat",
        source_dispatch_id="dispatch_compat",
        source_registration_id="reg_compat",
        source_task_id="task_compat",
        api_execution_status="pending",
        api_execution_reason="compat test",
        api_execution_time=_iso_now(),
        # lineage_id 不传（None）
    )
    
    assert artifact.lineage_id is None
    
    # 序列化
    data = artifact.to_dict()
    assert "lineage_id" in data
    assert data["lineage_id"] is None
    
    # 反序列化（从旧数据，没有 lineage_id 字段）
    old_data = {
        "execution_id": "exec_old",
        "source_request_id": "req_old",
        "source_receipt_id": "receipt_old",
        "source_execution_id": "exec_source_old",
        "source_spawn_id": "spawn_old",
        "source_dispatch_id": "dispatch_old",
        "source_registration_id": "reg_old",
        "source_task_id": "task_old",
        "api_execution_status": "blocked",
        "api_execution_reason": "old data",
        "api_execution_time": _iso_now(),
        # 没有 lineage_id 字段
    }
    
    artifact_old = SessionsSpawnAPIExecution.from_dict(old_data)
    assert artifact_old.lineage_id is None
    
    print("  ✓ PASS: Backward compatibility (lineage_id=None)")
    return True


def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("Lineage 数据结构 + 最小接线测试")
    print("=" * 60)
    
    tests = [
        test_lineage_record_serialization,
        test_lineage_record_defaults,
        test_lineage_store_crud,
        test_lineage_convenience_functions,
        test_lineage_relation_types,
        test_lineage_minimal_wiring,
        test_lineage_backward_compatibility,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            if test():
                passed += 1
            else:
                failed += 1
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
