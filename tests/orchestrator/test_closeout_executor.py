#!/usr/bin/env python3
"""
test_closeout_executor.py — Closeout Executor 测试

覆盖：
- CloseoutExecutionConfig 数据结构
- CloseoutExecutionResult 数据结构
- CloseoutExecutor 执行流程
- Fan-in readiness 集成
- Closeout artifact 生成
- SubagentExecutor 集成
"""

import json
import os
import sys
import tempfile
import shutil
from pathlib import Path
from datetime import datetime

# 添加 runtime/orchestrator 路径
sys.path.insert(0, str(Path(__file__).parent.parent / "runtime" / "orchestrator"))

from closeout_executor import (
    CloseoutExecutionConfig,
    CloseoutExecutionResult,
    CloseoutExecutor,
    execute_closeout,
    get_closeout_execution_result,
    list_closeout_executions,
    CLOSEOUT_EXECUTOR_VERSION,
    CLOSEOUT_EXECUTOR_DIR,
    _execution_file,
    _generate_execution_id,
    _ensure_executor_dir,
)

from closeout_tracker import CloseoutArtifact


def test_closeout_execution_config():
    """测试 CloseoutExecutionConfig 数据结构"""
    config = CloseoutExecutionConfig(
        batch_id="batch_123",
        timeout_seconds=600,
        allowed_tools=["read", "write"],
        cwd="/tmp/test",
        metadata={"test": "value"},
    )
    
    assert config.batch_id == "batch_123"
    assert config.timeout_seconds == 600
    assert config.allowed_tools == ["read", "write"]
    assert config.cwd == "/tmp/test"
    assert config.metadata == {"test": "value"}
    
    # 序列化/反序列化
    data = config.to_dict()
    config2 = CloseoutExecutionConfig.from_dict(data)
    
    assert config2.batch_id == config.batch_id
    assert config2.timeout_seconds == config.timeout_seconds
    assert config2.allowed_tools == config.allowed_tools
    assert config2.cwd == config.cwd
    assert config2.metadata == config.metadata
    
    print("✓ CloseoutExecutionConfig 数据结构正常")


def test_closeout_execution_result():
    """测试 CloseoutExecutionResult 数据结构"""
    result = CloseoutExecutionResult(
        execution_id="closeout_exec_test123",
        batch_id="batch_123",
        status="completed",
        subagent_task_id="task_abc",
        fanin_readiness={"ready": True, "children_count": 3},
        metadata={"test": "value"},
    )
    
    assert result.execution_id == "closeout_exec_test123"
    assert result.batch_id == "batch_123"
    assert result.status == "completed"
    assert result.subagent_task_id == "task_abc"
    assert result.fanin_readiness["ready"] is True
    
    # 序列化/反序列化
    data = result.to_dict()
    result2 = CloseoutExecutionResult.from_dict(data)
    
    assert result2.execution_id == result.execution_id
    assert result2.batch_id == result.batch_id
    assert result2.status == result.status
    assert result2.subagent_task_id == result.subagent_task_id
    
    print("✓ CloseoutExecutionResult 数据结构正常")


def test_closeout_executor_initialization():
    """测试 CloseoutExecutor 初始化"""
    config = CloseoutExecutionConfig(
        batch_id="batch_123",
        timeout_seconds=300,
    )
    
    executor = CloseoutExecutor(config)
    
    assert executor.config.batch_id == "batch_123"
    assert executor.config.timeout_seconds == 300
    assert executor.allowed_tools == ["read", "write", "edit", "exec"]  # 默认工具
    
    print("✓ CloseoutExecutor 初始化正常")


def test_closeout_executor_with_custom_tools():
    """测试 CloseoutExecutor 自定义工具列表"""
    config = CloseoutExecutionConfig(
        batch_id="batch_123",
        timeout_seconds=300,
        allowed_tools=["read", "write"],
    )
    
    executor = CloseoutExecutor(config)
    
    assert executor.allowed_tools == ["read", "write"]
    
    print("✓ CloseoutExecutor 自定义工具列表正常")


def test_closeout_executor_persist_result():
    """测试 CloseoutExecutor 持久化结果"""
    # 创建临时目录
    temp_dir = tempfile.mkdtemp()
    original_dir = CLOSEOUT_EXECUTOR_DIR
    
    try:
        # 临时替换目录
        import closeout_executor
        closeout_executor.CLOSEOUT_EXECUTOR_DIR = Path(temp_dir)
        
        config = CloseoutExecutionConfig(
            batch_id="batch_123",
            timeout_seconds=300,
        )
        
        executor = CloseoutExecutor(config)
        
        # 创建测试结果
        result = CloseoutExecutionResult(
            execution_id="closeout_exec_test_persist",
            batch_id="batch_123",
            status="pending",
        )
        
        # 持久化
        executor._persist_result(result)
        
        # 验证文件存在
        exec_file = _execution_file("closeout_exec_test_persist")
        assert exec_file.exists()
        
        # 验证内容
        with open(exec_file, "r") as f:
            data = json.load(f)
        
        assert data["execution_id"] == "closeout_exec_test_persist"
        assert data["batch_id"] == "batch_123"
        assert data["status"] == "pending"
        
        print("✓ CloseoutExecutor 持久化结果正常")
    
    finally:
        # 恢复原目录
        closeout_executor.CLOSEOUT_EXECUTOR_DIR = original_dir
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_closeout_executor_get_result():
    """测试 CloseoutExecutor 获取结果"""
    # 创建临时目录
    temp_dir = tempfile.mkdtemp()
    original_dir = CLOSEOUT_EXECUTOR_DIR
    
    try:
        # 临时替换目录
        import closeout_executor
        closeout_executor.CLOSEOUT_EXECUTOR_DIR = Path(temp_dir)
        
        config = CloseoutExecutionConfig(
            batch_id="batch_123",
            timeout_seconds=300,
        )
        
        executor = CloseoutExecutor(config)
        
        # 创建并持久化测试结果
        result = CloseoutExecutionResult(
            execution_id="closeout_exec_test_get",
            batch_id="batch_123",
            status="completed",
            metadata={"test": "value"},
        )
        
        executor._persist_result(result)
        
        # 获取结果
        retrieved = executor.get_result("closeout_exec_test_get")
        
        assert retrieved is not None
        assert retrieved.execution_id == "closeout_exec_test_get"
        assert retrieved.status == "completed"
        assert retrieved.metadata["test"] == "value"
        
        # 测试不存在的情况
        not_found = executor.get_result("closeout_exec_not_exist")
        assert not_found is None
        
        print("✓ CloseoutExecutor 获取结果正常")
    
    finally:
        # 恢复原目录
        closeout_executor.CLOSEOUT_EXECUTOR_DIR = original_dir
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_closeout_executor_build_closeout_task():
    """测试 CloseoutExecutor 构建任务 prompt"""
    config = CloseoutExecutionConfig(
        batch_id="batch_123",
        timeout_seconds=300,
    )
    
    executor = CloseoutExecutor(config)
    
    remaining_work = ["task1", "task2"]
    task = executor._build_closeout_task(remaining_work)
    
    assert "batch_123" in task
    assert "task1" in task
    assert "task2" in task
    assert "closeout artifact" in task.lower()
    
    print("✓ CloseoutExecutor 构建任务 prompt 正常")


def test_list_closeout_executions():
    """测试列出 closeout 执行记录"""
    # 创建临时目录
    temp_dir = tempfile.mkdtemp()
    original_dir = CLOSEOUT_EXECUTOR_DIR
    
    try:
        # 临时替换目录
        import closeout_executor
        closeout_executor.CLOSEOUT_EXECUTOR_DIR = Path(temp_dir)
        
        # 创建多个测试记录
        for i in range(3):
            result = CloseoutExecutionResult(
                execution_id=f"closeout_exec_list_{i}",
                batch_id=f"batch_{i}",
                status="completed" if i % 2 == 0 else "failed",
            )
            
            exec_file = _execution_file(result.execution_id)
            _ensure_executor_dir()
            
            from closeout_executor import _atomic_json_write
            _atomic_json_write(exec_file, result.to_dict())
        
        # 列出所有
        all_executions = list_closeout_executions()
        assert len(all_executions) == 3
        
        # 按 batch_id 过滤
        batch_filtered = list_closeout_executions(batch_id="batch_0")
        assert len(batch_filtered) == 1
        assert batch_filtered[0].batch_id == "batch_0"
        
        # 按状态过滤
        status_filtered = list_closeout_executions(status="completed")
        assert len(status_filtered) == 2  # batch_0 and batch_2
        
        print("✓ 列出 closeout 执行记录正常")
    
    finally:
        # 恢复原目录
        closeout_executor.CLOSEOUT_EXECUTOR_DIR = original_dir
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_closeout_executor_version():
    """测试版本号"""
    assert CLOSEOUT_EXECUTOR_VERSION == "closeout_executor_v1"
    print("✓ CloseoutExecutor 版本号正常")


def test_closeout_executor_metadata():
    """测试 CloseoutExecutor 元数据"""
    config = CloseoutExecutionConfig(
        batch_id="batch_123",
        timeout_seconds=300,
        metadata={"source": "test", "custom": "value"},
    )
    
    executor = CloseoutExecutor(config)
    
    result = CloseoutExecutionResult(
        execution_id="closeout_exec_meta",
        batch_id="batch_123",
        status="pending",
        metadata={"test": "value"},
    )
    
    # 验证 executor 版本常量存在
    assert CLOSEOUT_EXECUTOR_VERSION == "closeout_executor_v1"
    
    # 验证结果可以序列化并包含版本信息
    data = result.to_dict()
    assert data["executor_version"] == "closeout_executor_v1"
    
    print("✓ CloseoutExecutor 元数据正常")


def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("Closeout Executor 测试")
    print("=" * 60)
    
    tests = [
        test_closeout_execution_config,
        test_closeout_execution_result,
        test_closeout_executor_initialization,
        test_closeout_executor_with_custom_tools,
        test_closeout_executor_persist_result,
        test_closeout_executor_get_result,
        test_closeout_executor_build_closeout_task,
        test_list_closeout_executions,
        test_closeout_executor_version,
        test_closeout_executor_metadata,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"✗ {test.__name__} 失败：{e}")
            failed += 1
        except Exception as e:
            print(f"✗ {test.__name__} 错误：{e}")
            failed += 1
    
    print("=" * 60)
    print(f"测试结果：{passed} 通过，{failed} 失败")
    print("=" * 60)
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
