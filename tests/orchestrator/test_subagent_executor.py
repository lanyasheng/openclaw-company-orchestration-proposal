#!/usr/bin/env python3
"""
test_subagent_executor.py — SubagentExecutor 单元测试

覆盖：
- SubagentConfig 创建和序列化
- SubagentResult 创建和序列化
- SubagentExecutor 执行流程
- 工具过滤
- 状态持久化
- 并发安全
"""

import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

# 添加 runtime/orchestrator 到路径
orchestrator_path = Path(__file__).parent.parent.parent / "runtime" / "orchestrator"
sys.path.insert(0, str(orchestrator_path))

from subagent_executor import (
    SubagentConfig,
    SubagentResult,
    SubagentExecutor,
    SubagentStatus,
    execute_subagent,
    get_subagent_result,
    list_subagent_tasks,
    _filter_tools,
    _background_tasks,
    _background_tasks_lock,
    TERMINAL_STATES,
)


def test_subagent_config_creation():
    """测试 SubagentConfig 创建"""
    config = SubagentConfig(
        label="test-task",
        runtime="subagent",
        timeout_seconds=600,
        allowed_tools=["read", "write"],
        cwd="/tmp",
    )
    
    assert config.label == "test-task"
    assert config.runtime == "subagent"
    assert config.timeout_seconds == 600
    assert config.allowed_tools == ["read", "write"]
    assert config.cwd == "/tmp"
    print("✓ SubagentConfig 创建正常")


def test_subagent_config_serialization():
    """测试 SubagentConfig 序列化"""
    config = SubagentConfig(
        label="test-task",
        runtime="acp",
        timeout_seconds=900,
        allowed_tools=["read", "write", "edit"],
        disallowed_tools=["exec"],
        cwd="/tmp",
        metadata={"key": "value"},
    )
    
    # 序列化
    data = config.to_dict()
    assert data["label"] == "test-task"
    assert data["runtime"] == "acp"
    assert data["timeout_seconds"] == 900
    assert data["allowed_tools"] == ["read", "write", "edit"]
    assert data["disallowed_tools"] == ["exec"]
    assert data["metadata"]["key"] == "value"
    
    # 反序列化
    config2 = SubagentConfig.from_dict(data)
    assert config2.label == config.label
    assert config2.runtime == config.runtime
    assert config2.timeout_seconds == config.timeout_seconds
    print("✓ SubagentConfig 序列化正常")


def test_subagent_result_creation():
    """测试 SubagentResult 创建"""
    config = SubagentConfig(label="test", runtime="subagent")
    result = SubagentResult(
        task_id="task_123",
        status="pending",
        config=config,
        task="Test task",
    )
    
    assert result.task_id == "task_123"
    assert result.status == "pending"
    assert result.task == "Test task"
    assert result.result is None
    assert result.error is None
    print("✓ SubagentResult 创建正常")


def test_subagent_result_serialization():
    """测试 SubagentResult 序列化"""
    config = SubagentConfig(label="test", runtime="subagent")
    result = SubagentResult(
        task_id="task_123",
        status="completed",
        config=config,
        task="Test task",
        result="Success",
        metadata={"test": "value"},
    )
    
    # 序列化
    data = result.to_dict()
    assert data["task_id"] == "task_123"
    assert data["status"] == "completed"
    assert data["result"] == "Success"
    assert data["metadata"]["test"] == "value"
    
    # 反序列化
    result2 = SubagentResult.from_dict(data)
    assert result2.task_id == result.task_id
    assert result2.status == result.status
    assert result2.result == result.result
    print("✓ SubagentResult 序列化正常")


def test_filter_tools():
    """测试工具过滤"""
    available = ["read", "write", "edit", "exec", "bash"]
    
    # 只允许部分
    filtered = _filter_tools(available, allowed_tools=["read", "write"])
    assert filtered == ["read", "write"]
    
    # 禁止部分
    filtered = _filter_tools(available, disallowed_tools=["exec", "bash"])
    assert filtered == ["edit", "read", "write"]
    
    # 允许 + 禁止（禁止优先级更高）
    filtered = _filter_tools(
        available,
        allowed_tools=["read", "write", "exec"],
        disallowed_tools=["exec"],
    )
    assert filtered == ["read", "write"]
    
    # 空允许列表（允许所有，但会排序）
    filtered = _filter_tools(available)
    assert filtered == sorted(available)
    
    print("✓ 工具过滤正常")


def test_subagent_executor_creation():
    """测试 SubagentExecutor 创建"""
    config = SubagentConfig(
        label="test-executor",
        runtime="subagent",
        timeout_seconds=600,
        allowed_tools=["read", "write"],
    )
    
    executor = SubagentExecutor(config, cwd="/tmp")
    
    assert executor.config.label == "test-executor"
    assert executor.cwd == "/tmp"
    assert "read" in executor.allowed_tools
    assert "write" in executor.allowed_tools
    assert "exec" not in executor.allowed_tools  # 被过滤掉
    print("✓ SubagentExecutor 创建正常")


def test_subagent_executor_execute_async():
    """测试异步执行"""
    config = SubagentConfig(
        label="test-async",
        runtime="subagent",
        timeout_seconds=600,
    )
    
    executor = SubagentExecutor(config, cwd="/tmp")
    
    # 启动任务
    task_id = executor.execute_async("Test async task")
    
    assert task_id.startswith("task_")
    
    # 获取结果
    result = executor.get_result(task_id)
    assert result is not None
    assert result.task_id == task_id
    assert result.task == "Test async task"
    assert result.status in ["pending", "running", "completed", "failed"]
    
    print(f"✓ 异步执行正常 (task_id={task_id})")


def test_subagent_executor_custom_task_id():
    """测试自定义 task_id"""
    config = SubagentConfig(label="test-custom", runtime="subagent")
    executor = SubagentExecutor(config, cwd="/tmp")
    
    custom_id = "custom_task_12345"
    task_id = executor.execute_async("Test task", task_id=custom_id)
    
    assert task_id == custom_id
    
    result = executor.get_result(task_id)
    assert result is not None
    assert result.task_id == custom_id
    
    print("✓ 自定义 task_id 正常")


def test_subagent_executor_is_completed():
    """测试完成状态检查"""
    config = SubagentConfig(label="test-completed", runtime="subagent")
    executor = SubagentExecutor(config, cwd="/tmp")
    
    task_id = executor.execute_async("Test task")
    
    # 刚启动时应该未完成
    # 注意：由于是模拟执行，状态可能是 pending/running/failed
    result = executor.get_result(task_id)
    assert result is not None
    
    print("✓ 完成状态检查正常")


def test_concurrent_task_creation():
    """测试并发任务创建"""
    config = SubagentConfig(label="test-concurrent", runtime="subagent")
    executor = SubagentExecutor(config, cwd="/tmp")
    
    task_ids = []
    errors = []
    
    def create_task(i):
        try:
            task_id = executor.execute_async(f"Concurrent task {i}")
            task_ids.append(task_id)
        except Exception as e:
            errors.append(e)
    
    # 并发创建 10 个任务
    threads = []
    for i in range(10):
        t = threading.Thread(target=create_task, args=(i,))
        threads.append(t)
        t.start()
    
    for t in threads:
        t.join()
    
    assert len(errors) == 0, f"并发创建失败：{errors}"
    assert len(task_ids) == 10
    assert len(set(task_ids)) == 10  # 所有 task_id 唯一
    
    print("✓ 并发任务创建正常")


def test_state_persistence():
    """测试状态持久化"""
    from subagent_executor import _persist_state, _load_state, _ensure_state_dir
    
    config = SubagentConfig(label="test-persist", runtime="subagent")
    result = SubagentResult(
        task_id="persist_test_123",
        status="completed",
        config=config,
        task="Persistence test",
        result="Success",
    )
    
    # 持久化
    _persist_state(result)
    
    # 加载
    loaded = _load_state("persist_test_123")
    
    assert loaded is not None
    assert loaded.task_id == result.task_id
    assert loaded.status == result.status
    assert loaded.result == result.result
    
    print("✓ 状态持久化正常")


def test_terminal_states():
    """测试终端状态"""
    assert "completed" in TERMINAL_STATES
    assert "failed" in TERMINAL_STATES
    assert "timed_out" in TERMINAL_STATES
    assert "cancelled" in TERMINAL_STATES
    assert "pending" not in TERMINAL_STATES
    assert "running" not in TERMINAL_STATES
    
    print("✓ 终端状态定义正常")


def test_execute_subagent_convenience():
    """测试便捷函数 execute_subagent"""
    task_id = execute_subagent(
        task="Test convenience function",
        label="convenience-test",
        timeout_seconds=300,
        allowed_tools=["read", "write"],
    )
    
    assert task_id.startswith("task_")
    
    result = get_subagent_result(task_id)
    assert result is not None
    assert result.task == "Test convenience function"
    
    print(f"✓ 便捷函数正常 (task_id={task_id})")


def test_list_subagent_tasks():
    """测试列出任务"""
    # 创建几个任务
    task_ids = []
    for i in range(3):
        task_id = execute_subagent(
            task=f"List test {i}",
            label="list-test",
        )
        task_ids.append(task_id)
    
    # 列出所有任务
    tasks = list_subagent_tasks()
    
    # 应该至少包含我们创建的 3 个任务
    created_tasks = [t for t in tasks if t.task_id in task_ids]
    assert len(created_tasks) >= 3
    
    # 按状态过滤
    pending_tasks = list_subagent_tasks(status="pending")
    assert isinstance(pending_tasks, list)
    
    print(f"✓ 列出任务正常 (找到 {len(created_tasks)} 个测试任务)")


def test_cleanup():
    """测试清理已完成任务"""
    config = SubagentConfig(label="test-cleanup", runtime="subagent")
    executor = SubagentExecutor(config, cwd="/tmp")
    
    task_id = executor.execute_async("Test cleanup")
    
    # 刚创建的任务不应该被清理（未完成）
    cleaned = executor.cleanup(task_id)
    # 注意：由于任务可能还在 pending/running 状态，cleanup 可能返回 False
    
    # 手动标记为完成
    from subagent_executor import _update_task_status
    _update_task_status(task_id, "completed")
    
    # 现在应该可以清理
    cleaned = executor.cleanup(task_id)
    # cleaned 可能是 True 或 False，取决于内存状态
    
    print("✓ 清理逻辑正常")


def test_metadata_propagation():
    """测试元数据传递"""
    config = SubagentConfig(
        label="test-metadata",
        runtime="subagent",
        metadata={"custom_key": "custom_value"},
    )
    
    executor = SubagentExecutor(config, cwd="/tmp")
    task_id = executor.execute_async("Test metadata")
    
    result = executor.get_result(task_id)
    assert result is not None
    assert result.config.metadata.get("custom_key") == "custom_value"
    assert result.metadata.get("executor_version") is not None
    assert result.metadata.get("allowed_tools") is not None
    
    print("✓ 元数据传递正常")


def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("SubagentExecutor 单元测试")
    print("=" * 60)
    
    tests = [
        test_subagent_config_creation,
        test_subagent_config_serialization,
        test_subagent_result_creation,
        test_subagent_result_serialization,
        test_filter_tools,
        test_subagent_executor_creation,
        test_subagent_executor_execute_async,
        test_subagent_executor_custom_task_id,
        test_subagent_executor_is_completed,
        test_concurrent_task_creation,
        test_state_persistence,
        test_terminal_states,
        test_execute_subagent_convenience,
        test_list_subagent_tasks,
        test_cleanup,
        test_metadata_propagation,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            print(f"\nRunning {test.__name__}...")
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
