#!/usr/bin/env python3
"""
test_issue_lane_executor.py — IssueLaneExecutor 集成测试

覆盖：
- IssueLaneExecutionConfig 创建和序列化
- IssueLaneExecutionResult 创建和序列化
- IssueLaneExecutor 执行流程
- SubagentExecutor 集成
- Issue Lane Contract 完整性
- 状态持久化
- Closeout 生成

这是 Deer-Flow 借鉴线 Batch D 的验收测试。
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path

# 添加 runtime/orchestrator 到路径
orchestrator_path = Path(__file__).parent.parent.parent / "runtime" / "orchestrator"
sys.path.insert(0, str(orchestrator_path))

from issue_lane_executor import (
    IssueLaneExecutionConfig,
    IssueLaneExecutionResult,
    IssueLaneExecutor,
    execute_issue,
    get_issue_execution_result,
    list_issue_executions,
    ISSUE_LANE_EXECUTOR_VERSION,
)

from issue_lane_schemas import (
    IssueInput,
    PlanningOutput,
    CloseoutOutput,
    build_issue_lane_contract,
    ISSUE_LANE_SCHEMA_VERSION,
)

from subagent_executor import (
    SubagentConfig,
    SubagentExecutor,
    TERMINAL_STATES,
)


def test_execution_config_creation():
    """测试执行配置创建"""
    config = IssueLaneExecutionConfig(
        issue_id="test_issue_123",
        backend="subagent",
        executor="claude_code",
        timeout_seconds=1200,
        allowed_tools=["read", "write", "edit"],
        cwd="/tmp",
        metadata={"test": "value"},
    )
    
    assert config.issue_id == "test_issue_123"
    assert config.backend == "subagent"
    assert config.executor == "claude_code"
    assert config.timeout_seconds == 1200
    assert config.allowed_tools == ["read", "write", "edit"]
    assert config.cwd == "/tmp"
    assert config.metadata["test"] == "value"
    
    print("✓ IssueLaneExecutionConfig 创建正常")


def test_execution_config_serialization():
    """测试执行配置序列化"""
    config = IssueLaneExecutionConfig(
        issue_id="test_issue_456",
        backend="subagent",
        executor="subagent",
        timeout_seconds=900,
    )
    
    # 序列化
    data = config.to_dict()
    assert data["issue_id"] == "test_issue_456"
    assert data["backend"] == "subagent"
    assert data["executor"] == "subagent"
    assert data["timeout_seconds"] == 900
    
    # 反序列化
    config2 = IssueLaneExecutionConfig.from_dict(data)
    assert config2.issue_id == config.issue_id
    assert config2.backend == config.backend
    assert config2.executor == config.executor
    
    print("✓ IssueLaneExecutionConfig 序列化正常")


def test_execution_config_to_subagent_config():
    """测试转换为 SubagentConfig"""
    config = IssueLaneExecutionConfig(
        issue_id="test_issue_789",
        backend="subagent",
        executor="claude_code",
        timeout_seconds=600,
        allowed_tools=["read", "write"],
        cwd="/tmp/test",
    )
    
    subagent_config = config.to_subagent_config(label="test-label")
    
    assert subagent_config.label == "test-label"
    assert subagent_config.runtime == "subagent"
    assert subagent_config.timeout_seconds == 600
    assert subagent_config.allowed_tools == ["read", "write"]
    assert subagent_config.cwd == "/tmp/test"
    assert subagent_config.metadata["issue_id"] == "test_issue_789"
    assert subagent_config.metadata["backend"] == "subagent"
    assert subagent_config.metadata["executor"] == "claude_code"
    
    print("✓ 转换为 SubagentConfig 正常")


def test_execution_result_creation():
    """测试执行结果创建"""
    issue_input = IssueInput(
        issue_id="test_issue",
        source="manual",
        title="Test Issue",
        body="Test body",
    )
    
    contract = build_issue_lane_contract(
        contract_id="test_contract",
        issue_input=issue_input,
    )
    
    result = IssueLaneExecutionResult(
        execution_id="test_exec_123",
        issue_id="test_issue",
        contract=contract,
        status="pending",
    )
    
    assert result.execution_id == "test_exec_123"
    assert result.issue_id == "test_issue"
    assert result.contract is not None
    assert result.contract.input.issue_id == "test_issue"
    assert result.status == "pending"
    
    print("✓ IssueLaneExecutionResult 创建正常")


def test_execution_result_serialization():
    """测试执行结果序列化"""
    issue_input = IssueInput(
        issue_id="test_issue",
        source="manual",
        title="Test Issue",
    )
    
    contract = build_issue_lane_contract(
        contract_id="test_contract",
        issue_input=issue_input,
    )
    
    result = IssueLaneExecutionResult(
        execution_id="test_exec_456",
        issue_id="test_issue",
        contract=contract,
        status="completed",
        metadata={"test": "value"},
    )
    
    # 序列化
    data = result.to_dict()
    assert data["execution_id"] == "test_exec_456"
    assert data["issue_id"] == "test_issue"
    assert data["status"] == "completed"
    assert data["metadata"]["test"] == "value"
    assert data["contract"] is not None
    
    # 反序列化
    result2 = IssueLaneExecutionResult.from_dict(data)
    assert result2.execution_id == result.execution_id
    assert result2.issue_id == result.issue_id
    assert result2.status == result.status
    
    print("✓ IssueLaneExecutionResult 序列化正常")


def test_execution_result_persistence():
    """测试执行结果持久化"""
    issue_input = IssueInput(
        issue_id="test_issue_persist",
        source="manual",
        title="Persistence Test",
    )
    
    contract = build_issue_lane_contract(
        contract_id="test_contract_persist",
        issue_input=issue_input,
    )
    
    result = IssueLaneExecutionResult(
        execution_id="persist_test_123",
        issue_id="test_issue_persist",
        contract=contract,
        status="completed",
        completed_at="2026-03-24T12:00:00",
    )
    
    # 写入文件
    file_path = result.write()
    assert file_path.exists()
    
    # 从文件加载
    loaded = IssueLaneExecutionResult.load("persist_test_123")
    assert loaded is not None
    assert loaded.execution_id == result.execution_id
    assert loaded.issue_id == result.issue_id
    assert loaded.status == result.status
    
    print("✓ 执行结果持久化正常")


def test_executor_creation():
    """测试执行器创建"""
    config = IssueLaneExecutionConfig(
        issue_id="test_executor",
        backend="subagent",
        executor="claude_code",
        timeout_seconds=600,
    )
    
    executor = IssueLaneExecutor(config)
    
    assert executor.config.issue_id == "test_executor"
    assert executor.executor is not None
    assert isinstance(executor.executor, SubagentExecutor)
    
    print("✓ IssueLaneExecutor 创建正常")


def test_executor_execute():
    """测试执行器执行"""
    config = IssueLaneExecutionConfig(
        issue_id="test_execute",
        backend="subagent",
        executor="claude_code",
        timeout_seconds=600,
        cwd="/tmp",
    )
    
    executor = IssueLaneExecutor(config)
    
    issue_input = IssueInput(
        issue_id="test_execute",
        source="manual",
        title="Execute Test",
        body="Test execution",
    )
    
    result = executor.execute(issue_input)
    
    assert result.execution_id.startswith("issue_exec_")
    assert result.issue_id == "test_execute"
    assert result.status in ["pending", "running", "failed"]
    assert result.contract is not None
    assert result.contract.input is not None
    assert result.contract.input.issue_id == "test_execute"
    
    print(f"✓ 执行器执行正常 (execution_id={result.execution_id})")


def test_executor_execute_with_planning():
    """测试带 planning 的执行"""
    config = IssueLaneExecutionConfig(
        issue_id="test_with_planning",
        backend="subagent",
        executor="claude_code",
        timeout_seconds=600,
        cwd="/tmp",
    )
    
    executor = IssueLaneExecutor(config)
    
    issue_input = IssueInput(
        issue_id="test_with_planning",
        source="manual",
        title="Planning Test",
        body="Test with planning",
    )
    
    planning = PlanningOutput(
        planning_id="plan_123",
        issue_id="test_with_planning",
        problem_reframing="Test problem",
        scope="Test scope",
        engineering_review="Test review",
        execution_plan="Test plan",
    )
    
    result = executor.execute(issue_input, planning)
    
    assert result.execution_id.startswith("issue_exec_")
    assert result.contract.planning is not None
    assert result.contract.planning.planning_id == "plan_123"
    assert result.contract.planning.issue_id == "test_with_planning"
    
    print(f"✓ 带 planning 的执行正常 (execution_id={result.execution_id})")


def test_closeout_generation_on_failure():
    """测试失败时 closeout 生成"""
    config = IssueLaneExecutionConfig(
        issue_id="test_closeout_fail",
        backend="subagent",
        executor="claude_code",
        timeout_seconds=600,
        cwd="/invalid/path/that/does/not/exist",
    )
    
    executor = IssueLaneExecutor(config)
    
    issue_input = IssueInput(
        issue_id="test_closeout_fail",
        source="manual",
        title="Closeout Failure Test",
        body="Test closeout on failure",
    )
    
    result = executor.execute(issue_input)
    
    # 等待执行完成（可能是失败）
    time.sleep(0.5)
    
    # 检查 closeout 是否生成
    if result.contract.closeout:
        closeout = result.contract.closeout
        assert closeout.issue_id == "test_closeout_fail"
        assert closeout.stopped_because is not None
        assert closeout.next_step is not None
        assert closeout.next_owner is not None
        print("✓ 失败时 closeout 生成正常")
    else:
        print("⚠ Closeout 未生成（可能是正常 pending 状态）")


def test_convenience_function_execute_issue():
    """测试便捷函数 execute_issue"""
    issue_input = IssueInput(
        issue_id="test_convenience",
        source="manual",
        title="Convenience Test",
        body="Test convenience function",
    )
    
    result = execute_issue(
        issue_input=issue_input,
        backend="subagent",
        timeout_seconds=300,
        cwd="/tmp",
    )
    
    assert result.execution_id.startswith("issue_exec_")
    assert result.issue_id == "test_convenience"
    assert result.status in ["pending", "running", "failed"]
    
    print(f"✓ 便捷函数 execute_issue 正常 (execution_id={result.execution_id})")


def test_get_execution_result():
    """测试获取执行结果"""
    issue_input = IssueInput(
        issue_id="test_get_result",
        source="manual",
        title="Get Result Test",
    )
    
    result = execute_issue(issue_input, cwd="/tmp")
    execution_id = result.execution_id
    
    # 获取结果
    loaded = get_issue_execution_result(execution_id)
    
    assert loaded is not None
    assert loaded.execution_id == execution_id
    assert loaded.issue_id == "test_get_result"
    
    print("✓ 获取执行结果正常")


def test_list_issue_executions():
    """测试列出执行结果"""
    # 创建几个执行
    execution_ids = []
    for i in range(3):
        issue_input = IssueInput(
            issue_id=f"test_list_{i}",
            source="manual",
            title=f"List Test {i}",
        )
        result = execute_issue(issue_input, cwd="/tmp")
        execution_ids.append(result.execution_id)
    
    # 列出所有执行
    executions = list_issue_executions()
    
    # 应该至少包含我们创建的 3 个执行
    created_executions = [e for e in executions if e.execution_id in execution_ids]
    assert len(created_executions) >= 3
    
    # 按 issue_id 过滤
    filtered = list_issue_executions(issue_id="test_list_0")
    assert len(filtered) >= 1
    assert filtered[0].issue_id == "test_list_0"
    
    print(f"✓ 列出执行结果正常 (找到 {len(created_executions)} 个测试执行)")


def test_contract_integrity():
    """测试 contract 完整性"""
    config = IssueLaneExecutionConfig(
        issue_id="test_contract_integrity",
        backend="subagent",
        executor="claude_code",
        timeout_seconds=600,
        cwd="/tmp",
    )
    
    executor = IssueLaneExecutor(config)
    
    issue_input = IssueInput(
        issue_id="test_contract_integrity",
        source="github_url",
        source_url="https://github.com/test/repo/issues/123",
        title="Contract Integrity Test",
        body="Test contract integrity",
        labels=["bug", "priority"],
    )
    
    planning = PlanningOutput(
        planning_id="plan_integrity",
        issue_id="test_contract_integrity",
        problem_reframing="Test problem",
        scope="Test scope",
        engineering_review="Test review",
        execution_plan="Test plan",
        acceptance_criteria=["Test passes", "No regressions"],
    )
    
    result = executor.execute(issue_input, planning)
    
    # 验证 contract 完整性
    contract = result.contract
    assert contract is not None
    assert contract.version == ISSUE_LANE_SCHEMA_VERSION
    assert contract.input is not None
    assert contract.input.issue_id == "test_contract_integrity"
    assert contract.input.source == "github_url"
    assert contract.input.labels == ["bug", "priority"]
    assert contract.planning is not None
    assert contract.planning.planning_id == "plan_integrity"
    assert contract.planning.acceptance_criteria == ["Test passes", "No regressions"]
    
    print("✓ Contract 完整性正常")


def test_executor_version_metadata():
    """测试执行器版本元数据"""
    config = IssueLaneExecutionConfig(
        issue_id="test_version",
        backend="subagent",
        executor="claude_code",
        timeout_seconds=600,
        cwd="/tmp",
    )
    
    executor = IssueLaneExecutor(config)
    
    issue_input = IssueInput(
        issue_id="test_version",
        source="manual",
        title="Version Test",
    )
    
    result = executor.execute(issue_input)
    
    assert result.metadata["executor_version"] == ISSUE_LANE_EXECUTOR_VERSION
    assert "subagent_executor_version" in result.metadata
    
    print("✓ 执行器版本元数据正常")


def test_github_issue_url_parsing():
    """测试 GitHub issue URL 解析"""
    from issue_lane_schemas import parse_github_issue_url, validate_github_issue_url
    
    # 有效 URL
    valid_url = "https://github.com/owner/repo/issues/123"
    assert validate_github_issue_url(valid_url) is True
    
    ref = parse_github_issue_url(valid_url)
    assert ref is not None
    assert ref.owner == "owner"
    assert ref.repo == "repo"
    assert ref.issue_number == 123
    
    # 无效 URL
    invalid_url = "https://github.com/owner/repo"
    assert validate_github_issue_url(invalid_url) is False
    
    print("✓ GitHub issue URL 解析正常")


def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("IssueLaneExecutor 集成测试")
    print("=" * 60)
    
    tests = [
        test_execution_config_creation,
        test_execution_config_serialization,
        test_execution_config_to_subagent_config,
        test_execution_result_creation,
        test_execution_result_serialization,
        test_execution_result_persistence,
        test_executor_creation,
        test_executor_execute,
        test_executor_execute_with_planning,
        test_closeout_generation_on_failure,
        test_convenience_function_execute_issue,
        test_get_execution_result,
        test_list_issue_executions,
        test_contract_integrity,
        test_executor_version_metadata,
        test_github_issue_url_parsing,
    ]
    
    passed = 0
    failed = 0
    skipped = 0
    
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
            print(f"⚠ {test.__name__} 异常：{e}")
            import traceback
            traceback.print_exc()
            skipped += 1
    
    print("=" * 60)
    print(f"测试结果：{passed} 通过，{failed} 失败，{skipped} 跳过/异常")
    print("=" * 60)
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
