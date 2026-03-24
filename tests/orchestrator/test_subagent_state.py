#!/usr/bin/env python3
"""
test_subagent_state.py — SubagentStateManager 单元测试

覆盖：
- SubagentState 创建和序列化
- SubagentStateManager 基本操作
- 内存缓存 + 文件持久化混合
- 并发安全
- 磁盘恢复
- 统计功能
"""

import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

# 添加 runtime/orchestrator 到路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "runtime" / "orchestrator"))

from subagent_state import (
    SubagentState,
    SubagentStateManager,
    SubagentStateStatus,
    TERMINAL_STATES,
    create_state,
    get_state,
    update_status,
    list_states,
    cleanup,
    get_manager,
)


def test_subagent_state_creation():
    """测试 SubagentState 创建"""
    state = SubagentState(
        task_id="test_123",
        status="pending",
        created_at="2026-03-24T00:00:00",
        updated_at="2026-03-24T00:00:00",
        metadata={"key": "value"},
    )
    
    assert state.task_id == "test_123"
    assert state.status == "pending"
    assert state.metadata["key"] == "value"
    assert state.started_at is None
    assert state.completed_at is None
    print("✓ SubagentState 创建正常")


def test_subagent_state_serialization():
    """测试 SubagentState 序列化"""
    state = SubagentState(
        task_id="test_123",
        status="completed",
        created_at="2026-03-24T00:00:00",
        updated_at="2026-03-24T00:00:01",
        started_at="2026-03-24T00:00:00",
        completed_at="2026-03-24T00:00:01",
        metadata={"key": "value"},
        payload={"task": "test"},
        result={"output": "success"},
    )
    
    # 序列化
    data = state.to_dict()
    assert data["task_id"] == "test_123"
    assert data["status"] == "completed"
    assert data["metadata"]["key"] == "value"
    assert data["payload"]["task"] == "test"
    assert data["result"]["output"] == "success"
    
    # 反序列化
    state2 = SubagentState.from_dict(data)
    assert state2.task_id == state.task_id
    assert state2.status == state.status
    assert state2.result == state.result
    print("✓ SubagentState 序列化正常")


def test_manager_creation():
    """测试 SubagentStateManager 创建"""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = SubagentStateManager(state_dir=Path(tmpdir))
        
        assert manager.state_dir == Path(tmpdir)
        assert len(manager._cache) == 0
        print("✓ SubagentStateManager 创建正常")


def test_manager_create_state():
    """测试创建状态"""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = SubagentStateManager(state_dir=Path(tmpdir))
        
        state = manager.create_state(
            task_id="test_123",
            status="pending",
            payload={"task": "test"},
            metadata={"key": "value"},
        )
        
        assert state.task_id == "test_123"
        assert state.status == "pending"
        assert state.payload["task"] == "test"
        assert state.metadata["key"] == "value"
        assert state.created_at is not None
        
        # 验证文件已创建
        state_file = manager._state_file("test_123")
        assert state_file.exists()
        
        print("✓ 创建状态正常")


def test_manager_get_state():
    """测试获取状态"""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = SubagentStateManager(state_dir=Path(tmpdir))
        
        # 创建状态
        manager.create_state("test_123", "pending")
        
        # 获取状态（从内存）
        state = manager.get_state("test_123")
        assert state is not None
        assert state.task_id == "test_123"
        
        print("✓ 获取状态正常（内存）")


def test_manager_get_state_from_disk():
    """测试从磁盘获取状态"""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager1 = SubagentStateManager(state_dir=Path(tmpdir))
        manager1.create_state("test_123", "completed")
        
        # 创建新管理器（模拟重启）
        manager2 = SubagentStateManager(state_dir=Path(tmpdir))
        
        # 获取状态（从磁盘恢复）
        state = manager2.get_state("test_123")
        assert state is not None
        assert state.task_id == "test_123"
        assert state.status == "completed"
        
        print("✓ 获取状态正常（磁盘恢复）")


def test_manager_update_status():
    """测试更新状态"""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = SubagentStateManager(state_dir=Path(tmpdir))
        
        # 创建状态
        manager.create_state("test_123", "pending")
        
        # 更新为 running
        state = manager.update_status("test_123", "running")
        assert state is not None
        assert state.status == "running"
        assert state.started_at is not None
        
        # 更新为 completed
        state = manager.update_status(
            "test_123",
            "completed",
            result={"output": "success"},
        )
        assert state is not None
        assert state.status == "completed"
        assert state.completed_at is not None
        assert state.result["output"] == "success"
        
        print("✓ 更新状态正常")


def test_manager_update_metadata():
    """测试更新元数据"""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = SubagentStateManager(state_dir=Path(tmpdir))
        
        manager.create_state(
            "test_123",
            "pending",
            metadata={"key1": "value1"},
        )
        
        # 更新 metadata（合并）
        # 注意：dict 类型的值会被展开合并，而不是嵌套
        state = manager.update_status(
            "test_123",
            "running",
            key2="value2",
            **{"key3": "value3"},  # 展开合并
        )
        
        assert state is not None
        assert state.metadata["key1"] == "value1"
        assert state.metadata["key2"] == "value2"
        assert state.metadata["key3"] == "value3"
        
        print("✓ 更新元数据正常（合并）")


def test_manager_list_states():
    """测试列出状态"""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = SubagentStateManager(state_dir=Path(tmpdir))
        
        # 创建多个状态
        for i in range(5):
            manager.create_state(f"test_{i}", "pending")
        
        # 列出所有
        states = manager.list_states()
        assert len(states) == 5
        
        # 按状态过滤
        pending_states = manager.list_states(status="pending")
        assert len(pending_states) == 5
        
        # 限制数量
        limited = manager.list_states(limit=3)
        assert len(limited) == 3
        
        print("✓ 列出状态正常")


def test_manager_cleanup():
    """测试清理"""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = SubagentStateManager(state_dir=Path(tmpdir))
        
        # 创建并完成状态
        manager.create_state("test_123", "pending")
        manager.update_status("test_123", "completed")
        
        # 清理（应该成功）
        cleaned = manager.cleanup("test_123")
        assert cleaned is True
        
        # 从内存移除，但文件仍存在
        assert "test_123" not in manager._cache
        assert manager._state_file("test_123").exists()
        
        # 未完成的状态不能清理
        manager.create_state("test_456", "pending")
        cleaned = manager.cleanup("test_456")
        assert cleaned is False
        
        print("✓ 清理正常")


def test_manager_is_completed():
    """测试完成状态检查"""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = SubagentStateManager(state_dir=Path(tmpdir))
        
        manager.create_state("test_123", "pending")
        assert manager.is_completed("test_123") is False
        
        manager.update_status("test_123", "completed")
        assert manager.is_completed("test_123") is True
        
        print("✓ 完成状态检查正常")


def test_manager_stats():
    """测试统计功能"""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = SubagentStateManager(state_dir=Path(tmpdir))
        
        # 创建多个状态
        for i in range(3):
            manager.create_state(f"test_{i}", "pending")
        for i in range(2):
            state = manager.create_state(f"done_{i}", "pending")
            manager.update_status(f"done_{i}", "completed")
        
        stats = manager.get_stats()
        
        assert stats["total_files"] == 5
        assert stats["cache_size"] >= 2  # 至少包含终态
        assert "pending" in stats["by_status"]
        assert "completed" in stats["by_status"]
        
        print("✓ 统计功能正常")


def test_concurrent_operations():
    """测试并发操作"""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = SubagentStateManager(state_dir=Path(tmpdir))
        
        errors = []
        
        def create_and_update(i):
            try:
                task_id = f"concurrent_{i}"
                manager.create_state(task_id, "pending")
                time.sleep(0.01)
                manager.update_status(task_id, "completed")
            except Exception as e:
                errors.append(e)
        
        # 并发创建和更新
        threads = []
        for i in range(10):
            t = threading.Thread(target=create_and_update, args=(i,))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        assert len(errors) == 0, f"并发操作失败：{errors}"
        
        # 验证所有状态
        states = manager.list_states()
        assert len(states) == 10
        
        print("✓ 并发操作正常")


def test_terminal_states():
    """测试终端状态定义"""
    assert "completed" in TERMINAL_STATES
    assert "failed" in TERMINAL_STATES
    assert "timed_out" in TERMINAL_STATES
    assert "cancelled" in TERMINAL_STATES
    assert "pending" not in TERMINAL_STATES
    assert "running" not in TERMINAL_STATES
    
    print("✓ 终端状态定义正常")


def test_restore_from_disk():
    """测试磁盘恢复"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # 创建管理器并添加状态
        manager1 = SubagentStateManager(state_dir=Path(tmpdir))
        manager1.create_state("test_1", "pending")
        manager1.update_status("test_1", "completed")
        manager1.create_state("test_2", "pending")
        manager1.update_status("test_2", "failed")
        
        # 清空内存（模拟重启）
        manager1._cache.clear()
        
        # 手动恢复
        manager1._restore_from_disk()
        
        # 验证终态已恢复
        assert "test_1" in manager1._cache
        assert "test_2" in manager1._cache
        assert manager1._cache["test_1"].status == "completed"
        assert manager1._cache["test_2"].status == "failed"
        
        print("✓ 磁盘恢复正常")


def test_convenience_functions():
    """测试便捷函数"""
    # 使用默认管理器
    state = create_state("convenience_test", "pending")
    assert state.task_id == "convenience_test"
    
    state = get_state("convenience_test")
    assert state is not None
    
    state = update_status("convenience_test", "completed")
    assert state is not None
    assert state.status == "completed"
    
    states = list_states(limit=10)
    assert len(states) > 0
    
    cleaned = cleanup("convenience_test")
    assert cleaned is True
    
    print("✓ 便捷函数正常")


def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("SubagentStateManager 单元测试")
    print("=" * 60)
    
    tests = [
        test_subagent_state_creation,
        test_subagent_state_serialization,
        test_manager_creation,
        test_manager_create_state,
        test_manager_get_state,
        test_manager_get_state_from_disk,
        test_manager_update_status,
        test_manager_update_metadata,
        test_manager_list_states,
        test_manager_cleanup,
        test_manager_is_completed,
        test_manager_stats,
        test_concurrent_operations,
        test_terminal_states,
        test_restore_from_disk,
        test_convenience_functions,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"✗ {test.__name__} 失败：{e}")
            import traceback
            traceback.print_exc()
            failed += 1
        except Exception as e:
            print(f"✗ {test.__name__} 异常：{e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print("=" * 60)
    print(f"测试结果：{passed} 通过，{failed} 失败")
    print("=" * 60)
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
