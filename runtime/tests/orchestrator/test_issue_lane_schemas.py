#!/usr/bin/env python3
"""
test_issue_lane_schemas.py — Issue Lane Schema Tests

测试 issue lane 的核心 schema 和最小链路。
这是 P0 Batch 3: Coding Issue Lane Baseline 的测试套件。

测试覆盖：
1. Schema/contract 测试
2. 最小链路测试 (input -> planning -> execution -> closeout)
3. backward compatibility / non-breaking 检查
"""

import sys
import os
from datetime import datetime

# 添加 runtime/orchestrator 到路径
script_dir = os.path.dirname(os.path.abspath(__file__))
runtime_orchestrator_path = os.path.join(script_dir, '../../orchestrator')
sys.path.insert(0, runtime_orchestrator_path)

from issue_lane_schemas import (
    ISSUE_LANE_SCHEMA_VERSION,
    IssueInput,
    IssueSource,
    GitHubIssueRef,
    PlanningOutput,
    ExecutionOutput,
    PatchArtifact,
    PRDescription,
    CloseoutOutput,
    IssueLaneContract,
    validate_github_issue_url,
    parse_github_issue_url,
    build_issue_input,
    build_issue_lane_contract,
)


# =============================================================================
# Schema Validation Tests
# =============================================================================

def test_github_issue_url_validation():
    """测试 GitHub issue URL 验证"""
    print("Test: GitHub issue URL validation")
    
    # 有效 URL
    valid_urls = [
        "https://github.com/owner/repo/issues/123",
        "https://www.github.com/owner/repo/issues/456",
        "http://github.com/owner/repo/issues/789",
    ]
    for url in valid_urls:
        assert validate_github_issue_url(url), f"Expected {url} to be valid"
    print("  ✓ Valid GitHub issue URLs pass validation")
    
    # 无效 URL
    invalid_urls = [
        "https://github.com/owner/repo",  # 缺少 issues/number
        "https://github.com/owner/repo/issues/",  # 缺少 number
        "https://github.com/owner/repo/issues/abc",  # number 不是整数
        "https://gitlab.com/owner/repo/issues/123",  # 不是 GitHub
        "not a url",
    ]
    for url in invalid_urls:
        assert not validate_github_issue_url(url), f"Expected {url} to be invalid"
    print("  ✓ Invalid URLs fail validation")
    
    print("  PASS: GitHub issue URL validation\n")


def test_parse_github_issue_url():
    """测试 GitHub issue URL 解析"""
    print("Test: parse_github_issue_url()")
    
    url = "https://github.com/openclaw/openclaw-company-orchestration-proposal/issues/42"
    ref = parse_github_issue_url(url)
    
    assert ref is not None, "Expected valid ref"
    assert ref.owner == "openclaw"
    assert ref.repo == "openclaw-company-orchestration-proposal"
    assert ref.issue_number == 42
    assert ref.url == url
    assert "api.github.com" in ref.api_url
    assert "github.com" in ref.html_url
    print("  ✓ GitHub issue URL parsed correctly")
    
    # 无效 URL 返回 None
    invalid_ref = parse_github_issue_url("https://github.com/invalid")
    assert invalid_ref is None, "Expected None for invalid URL"
    print("  ✓ Invalid URL returns None")
    
    print("  PASS: parse_github_issue_url()\n")


def test_issue_input_validation():
    """测试 IssueInput 验证"""
    print("Test: IssueInput.validate()")
    
    # 有效 input (github_url source)
    issue_ref = GitHubIssueRef(
        owner="openclaw",
        repo="openclaw-company-orchestration-proposal",
        issue_number=42,
        url="https://github.com/openclaw/openclaw-company-orchestration-proposal/issues/42",
    )
    valid_input = IssueInput(
        issue_id="issue-001",
        source="github_url",
        source_url="https://github.com/openclaw/openclaw-company-orchestration-proposal/issues/42",
        issue_ref=issue_ref,
        title="Implement feature X",
        body="Description of feature X",
        labels=["enhancement", "P0"],
        assignee="zoe",
        state="open",
        executor_preference="claude_code",
        backend_preference="subagent",
        owner="main",
    )
    is_valid, errors = valid_input.validate()
    assert is_valid, f"Expected valid, got errors: {errors}"
    print("  ✓ Valid IssueInput passes validation")
    
    # 无效 case: 缺少 issue_id
    invalid_no_id = IssueInput(
        issue_id="",
        source="manual",
        title="Test",
    )
    is_valid, errors = invalid_no_id.validate()
    assert not is_valid, "Expected invalid for empty issue_id"
    assert any("issue_id" in e for e in errors)
    print("  ✓ Empty issue_id fails validation")
    
    # 无效 case: 缺少 title
    invalid_no_title = IssueInput(
        issue_id="issue-002",
        source="manual",
        title="",
    )
    is_valid, errors = invalid_no_title.validate()
    assert not is_valid, "Expected invalid for empty title"
    print("  ✓ Empty title fails validation")
    
    # 无效 case: github_url source 缺少 source_url
    invalid_no_url = IssueInput(
        issue_id="issue-003",
        source="github_url",
        title="Test",
    )
    is_valid, errors = invalid_no_url.validate()
    assert not is_valid, "Expected invalid for github_url without source_url"
    assert any("source_url" in e for e in errors)
    print("  ✓ github_url source without source_url fails validation")
    
    print("  PASS: IssueInput.validate()\n")


def test_issue_input_serialization():
    """测试 IssueInput 序列化/反序列化"""
    print("Test: IssueInput serialization")
    
    issue_ref = GitHubIssueRef(
        owner="openclaw",
        repo="test-repo",
        issue_number=100,
        url="https://github.com/openclaw/test-repo/issues/100",
    )
    original = IssueInput(
        issue_id="issue-004",
        source="github_url",
        source_url="https://github.com/openclaw/test-repo/issues/100",
        issue_ref=issue_ref,
        title="Serialization Test",
        body="Test body",
        labels=["test"],
        assignee="tester",
        executor_preference="subagent",
        backend_preference="tmux",
        owner="ainews",
        metadata={"custom": "value"},
    )
    
    # 序列化
    data = original.to_dict()
    assert data["issue_id"] == "issue-004"
    assert data["source"] == "github_url"
    assert data["issue_ref"]["owner"] == "openclaw"
    assert data["issue_ref"]["issue_number"] == 100
    print("  ✓ to_dict() works correctly")
    
    # 反序列化
    restored = IssueInput.from_dict(data)
    assert restored.issue_id == original.issue_id
    assert restored.source == original.source
    assert restored.title == original.title
    assert restored.issue_ref.owner == original.issue_ref.owner
    assert restored.metadata == original.metadata
    print("  ✓ from_dict() works correctly")
    
    print("  PASS: IssueInput serialization\n")


def test_planning_output_validation():
    """测试 PlanningOutput 验证"""
    print("Test: PlanningOutput.validate()")
    
    valid_planning = PlanningOutput(
        planning_id="plan-001",
        issue_id="issue-001",
        problem_reframing="Problem statement",
        scope="Scope definition",
        engineering_review="Technical review",
        execution_plan="Step by step plan",
        acceptance_criteria=["Criterion 1", "Criterion 2"],
        estimated_effort="M",
        risks=["Risk 1"],
    )
    is_valid, errors = valid_planning.validate()
    assert is_valid, f"Expected valid, got errors: {errors}"
    print("  ✓ Valid PlanningOutput passes validation")
    
    # 无效 case: 缺少 planning_id
    invalid_no_id = PlanningOutput(
        planning_id="",
        issue_id="issue-001",
        problem_reframing="Test",
        scope="Test",
        engineering_review="Test",
        execution_plan="Test",
    )
    is_valid, errors = invalid_no_id.validate()
    assert not is_valid, "Expected invalid for empty planning_id"
    print("  ✓ Empty planning_id fails validation")
    
    # 无效 case: 缺少 execution_plan
    invalid_no_plan = PlanningOutput(
        planning_id="plan-002",
        issue_id="issue-001",
        problem_reframing="Test",
        scope="Test",
        engineering_review="Test",
        execution_plan="",
    )
    is_valid, errors = invalid_no_plan.validate()
    assert not is_valid, "Expected invalid for empty execution_plan"
    print("  ✓ Empty execution_plan fails validation")
    
    print("  PASS: PlanningOutput.validate()\n")


def test_execution_output_validation():
    """测试 ExecutionOutput 验证"""
    print("Test: ExecutionOutput.validate()")
    
    patch = PatchArtifact(
        patch_id="patch-001",
        issue_id="issue-001",
        files_changed=["file1.py", "file2.py"],
        diff_summary="2 files changed, 10 insertions",
        pr_ready=True,
    )
    
    valid_execution = ExecutionOutput(
        execution_id="exec-001",
        issue_id="issue-001",
        planning_id="plan-001",
        executor="claude_code",
        backend="subagent",
        status="success",
        patch=patch,
        execution_summary="Successfully implemented feature",
        test_results={"passed": 10, "failed": 0},
    )
    is_valid, errors = valid_execution.validate()
    assert is_valid, f"Expected valid, got errors: {errors}"
    print("  ✓ Valid ExecutionOutput passes validation")
    
    # 无效 case: 缺少 execution_id
    invalid_no_id = ExecutionOutput(
        execution_id="",
        issue_id="issue-001",
    )
    is_valid, errors = invalid_no_id.validate()
    assert not is_valid, "Expected invalid for empty execution_id"
    print("  ✓ Empty execution_id fails validation")
    
    print("  PASS: ExecutionOutput.validate()\n")


def test_closeout_output_validation():
    """测试 CloseoutOutput 验证"""
    print("Test: CloseoutOutput.validate()")
    
    valid_closeout = CloseoutOutput(
        closeout_id="closeout-001",
        issue_id="issue-001",
        execution_id="exec-001",
        stopped_because="Implementation complete, awaiting review",
        next_step="Code review and merge",
        next_owner="main",
        dispatch_readiness="pending_review",
        summary="Feature implemented successfully",
        artifacts=["patch-001"],
    )
    is_valid, errors = valid_closeout.validate()
    assert is_valid, f"Expected valid, got errors: {errors}"
    print("  ✓ Valid CloseoutOutput passes validation")
    
    # 无效 case: 缺少 stopped_because
    invalid_no_reason = CloseoutOutput(
        closeout_id="closeout-002",
        issue_id="issue-001",
        stopped_because="",
        next_step="Test",
        next_owner="main",
    )
    is_valid, errors = invalid_no_reason.validate()
    assert not is_valid, "Expected invalid for empty stopped_because"
    print("  ✓ Empty stopped_because fails validation")
    
    # 无效 case: dispatch_readiness=ready 但缺少 next_owner
    invalid_ready_no_owner = CloseoutOutput(
        closeout_id="closeout-003",
        issue_id="issue-001",
        stopped_because="Test",
        next_step="Test",
        next_owner="",
        dispatch_readiness="ready",
    )
    is_valid, errors = invalid_ready_no_owner.validate()
    assert not is_valid, "Expected invalid for ready without next_owner"
    print("  ✓ dispatch_readiness=ready without next_owner fails validation")
    
    print("  PASS: CloseoutOutput.validate()\n")


# =============================================================================
# Minimal Link Tests (End-to-End)
# =============================================================================

def test_build_issue_input_helper():
    """测试 build_issue_input 便捷函数"""
    print("Test: build_issue_input()")
    
    # GitHub URL source
    issue_input = build_issue_input(
        issue_id="issue-005",
        source="github_url",
        source_url="https://github.com/openclaw/test-repo/issues/99",
        title="Test Issue",
        body="Test body",
        labels=["bug", "P1"],
        assignee="developer",
        executor_preference="claude_code",
        backend_preference="subagent",
        owner="trading",
    )
    
    assert issue_input.issue_id == "issue-005"
    assert issue_input.source == "github_url"
    assert issue_input.issue_ref is not None
    assert issue_input.issue_ref.owner == "openclaw"
    assert issue_input.issue_ref.issue_number == 99
    assert issue_input.executor_preference == "claude_code"
    assert issue_input.owner == "trading"
    print("  ✓ build_issue_input() works for github_url source")
    
    # Manual source (不需要 URL)
    manual_input = build_issue_input(
        issue_id="issue-006",
        source="manual",
        title="Manual Issue",
        body="Manually created",
        executor_preference="subagent",
    )
    assert manual_input.source == "manual"
    assert manual_input.issue_ref is None
    print("  ✓ build_issue_input() works for manual source")
    
    print("  PASS: build_issue_input()\n")


def test_minimal_link_issue_to_closeout():
    """测试最小链路：issue input -> planning -> execution -> closeout"""
    print("Test: Minimal link (issue -> planning -> execution -> closeout)")
    
    # Step 1: Create IssueInput
    issue_input = build_issue_input(
        issue_id="issue-link-001",
        source="github_url",
        source_url="https://github.com/openclaw/test-repo/issues/1",
        title="Implement minimal issue lane link",
        body="This is a test issue for validating the minimal link",
        labels=["test", "P0"],
        executor_preference="claude_code",
        backend_preference="subagent",
        owner="main",
    )
    is_valid, errors = issue_input.validate()
    assert is_valid, f"IssueInput validation failed: {errors}"
    print("  ✓ Step 1: IssueInput created and validated")
    
    # Step 2: Create PlanningOutput
    planning = PlanningOutput(
        planning_id="plan-link-001",
        issue_id="issue-link-001",
        problem_reframing="Need to implement and validate the minimal issue lane link",
        scope="Create schema, write tests, validate end-to-end flow",
        engineering_review="Using dataclasses for schema, pytest for tests",
        execution_plan="1. Define schemas 2. Write tests 3. Run tests 4. Commit",
        acceptance_criteria=[
            "All schema validations pass",
            "End-to-end link test passes",
            "Tests are executable",
        ],
        estimated_effort="S",
    )
    is_valid, errors = planning.validate()
    assert is_valid, f"PlanningOutput validation failed: {errors}"
    print("  ✓ Step 2: PlanningOutput created and validated")
    
    # Step 3: Create ExecutionOutput
    patch = PatchArtifact(
        patch_id="patch-link-001",
        issue_id="issue-link-001",
        planning_id="plan-link-001",
        files_changed=[
            "runtime/orchestrator/issue_lane_schemas.py",
            "runtime/tests/orchestrator/test_issue_lane_schemas.py",
        ],
        diff_summary="2 files added: schema definition + tests",
        pr_ready=True,
        branch_name="feature/issue-lane-baseline",
        commit_message="P0 Batch 3: Issue lane baseline schema and tests",
    )
    
    pr_desc = PRDescription(
        pr_id="pr-link-001",
        issue_id="issue-link-001",
        patch_id="patch-link-001",
        title="Implement issue lane baseline schema",
        body="This PR implements the minimal issue lane schema and tests.",
        base_branch="main",
        head_branch="feature/issue-lane-baseline",
        labels=["P0", "enhancement"],
        linked_issues=["issue-link-001"],
        checklist=[
            "- [ ] Schema validated",
            "- [ ] Tests pass",
            "- [ ] Documentation updated",
        ],
    )
    
    execution = ExecutionOutput(
        execution_id="exec-link-001",
        issue_id="issue-link-001",
        planning_id="plan-link-001",
        executor="claude_code",
        backend="subagent",
        status="success",
        patch=patch,
        pr_description=pr_desc,
        execution_summary="Successfully implemented issue lane baseline",
        test_results={"passed": 12, "failed": 0, "total": 12},
    )
    is_valid, errors = execution.validate()
    assert is_valid, f"ExecutionOutput validation failed: {errors}"
    print("  ✓ Step 3: ExecutionOutput created and validated")
    
    # Step 4: Create CloseoutOutput
    closeout = CloseoutOutput(
        closeout_id="closeout-link-001",
        issue_id="issue-link-001",
        execution_id="exec-link-001",
        planning_id="plan-link-001",
        stopped_because="Implementation complete, tests passing",
        next_step="Code review and merge to main",
        next_owner="main",
        dispatch_readiness="pending_review",
        summary="Issue lane baseline successfully implemented",
        artifacts=["patch-link-001", "pr-link-001"],
        artifact_paths=[
            "runtime/orchestrator/issue_lane_schemas.py",
            "runtime/tests/orchestrator/test_issue_lane_schemas.py",
        ],
    )
    is_valid, errors = closeout.validate()
    assert is_valid, f"CloseoutOutput validation failed: {errors}"
    print("  ✓ Step 4: CloseoutOutput created and validated")
    
    print("  PASS: Minimal link (issue -> planning -> execution -> closeout)\n")


def test_issue_lane_contract_integration():
    """测试 IssueLaneContract 完整集成"""
    print("Test: IssueLaneContract integration")
    
    # 创建完整的 contract
    issue_input = build_issue_input(
        issue_id="contract-001",
        source="github_url",
        source_url="https://github.com/openclaw/test-repo/issues/42",
        title="Contract Integration Test",
        executor_preference="claude_code",
    )
    
    planning = PlanningOutput(
        planning_id="plan-contract-001",
        issue_id="contract-001",
        problem_reframing="Test problem",
        scope="Test scope",
        engineering_review="Test review",
        execution_plan="Test plan",
    )
    
    execution = ExecutionOutput(
        execution_id="exec-contract-001",
        issue_id="contract-001",
        planning_id="plan-contract-001",
        status="success",
        execution_summary="Test execution",
    )
    
    closeout = CloseoutOutput(
        closeout_id="closeout-contract-001",
        issue_id="contract-001",
        execution_id="exec-contract-001",
        planning_id="plan-contract-001",
        stopped_because="Test complete",
        next_step="Test next step",
        next_owner="main",
        dispatch_readiness="ready",
    )
    
    contract = build_issue_lane_contract(
        contract_id="contract-001",
        issue_input=issue_input,
        planning=planning,
        execution=execution,
        closeout=closeout,
        metadata={"test": "integration"},
    )
    
    # 验证完整 contract
    is_valid, errors = contract.validate()
    assert is_valid, f"IssueLaneContract validation failed: {errors}"
    print("  ✓ IssueLaneContract validates successfully")
    
    # 验证版本
    assert contract.version == ISSUE_LANE_SCHEMA_VERSION
    print(f"  ✓ Contract version: {contract.version}")
    
    # 序列化
    data = contract.to_dict()
    assert data["contract_id"] == "contract-001"
    assert data["input"] is not None
    assert data["planning"] is not None
    assert data["execution"] is not None
    assert data["closeout"] is not None
    print("  ✓ Contract serialization works")
    
    # 部分 contract (只有 input)
    partial_contract = IssueLaneContract(
        contract_id="partial-001",
        input=issue_input,
    )
    is_valid, errors = partial_contract.validate()
    assert is_valid, "Partial contract should be valid"
    print("  ✓ Partial contract (input only) is valid")
    
    print("  PASS: IssueLaneContract integration\n")


def test_backward_compatibility():
    """测试向后兼容性"""
    print("Test: Backward compatibility / non-breaking")
    
    # 测试旧版本数据能否被解析
    # 模拟一个只有必需字段的简化 input
    minimal_data = {
        "issue_id": "minimal-001",
        "source": "manual",
        "title": "Minimal Issue",
    }
    minimal_input = IssueInput.from_dict(minimal_data)
    assert minimal_input.issue_id == "minimal-001"
    assert minimal_input.source == "manual"
    assert minimal_input.title == "Minimal Issue"
    assert minimal_input.executor_preference == "claude_code"  # 默认值
    assert minimal_input.backend_preference == "subagent"  # 默认值
    assert minimal_input.owner == "main"  # 默认值
    print("  ✓ Minimal data with defaults works")
    
    # 测试新增字段不影响旧数据
    # 旧数据没有 metadata 字段
    old_style_data = {
        "issue_id": "old-001",
        "source": "manual",
        "title": "Old Style Issue",
        # 没有 metadata, executor_preference 等新增字段
    }
    old_input = IssueInput.from_dict(old_style_data)
    assert old_input.metadata == {}  # 默认空字典
    print("  ✓ Old-style data without new fields works")
    
    # 测试 schema 版本
    assert ISSUE_LANE_SCHEMA_VERSION == "issue_lane_v1"
    print(f"  ✓ Schema version frozen: {ISSUE_LANE_SCHEMA_VERSION}")
    
    print("  PASS: Backward compatibility\n")


def test_patch_artifact_and_pr_description():
    """测试 PatchArtifact 和 PRDescription"""
    print("Test: PatchArtifact and PRDescription")
    
    patch = PatchArtifact(
        patch_id="patch-002",
        issue_id="issue-002",
        planning_id="plan-002",
        repo_path="/Users/study/.openclaw/workspace/repos/test",
        files_changed=["src/main.py", "tests/test_main.py"],
        diff_summary="2 files changed, 50 insertions(+), 10 deletions(-)",
        diff_content="diff --git a/src/main.py b/src/main.py...",
        commit_message="feat: implement new feature",
        branch_name="feature/new-feature",
        pr_ready=True,
        metadata={"lines_added": 50, "lines_deleted": 10},
    )
    
    patch_data = patch.to_dict()
    assert patch_data["patch_id"] == "patch-002"
    assert len(patch_data["files_changed"]) == 2
    assert patch_data["pr_ready"] is True
    print("  ✓ PatchArtifact serialization works")
    
    pr_desc = PRDescription(
        pr_id="pr-002",
        issue_id="issue-002",
        patch_id="patch-002",
        title="feat: implement new feature",
        body="This PR implements the new feature.\n\nCloses #2",
        base_branch="main",
        head_branch="feature/new-feature",
        labels=["enhancement", "P0"],
        reviewers=["zoe", "reviewer2"],
        linked_issues=["issue-002"],
        checklist=[
            "- [x] Tests pass",
            "- [x] Linting passes",
            "- [ ] Documentation updated",
        ],
    )
    
    pr_data = pr_desc.to_dict()
    assert pr_data["pr_id"] == "pr-002"
    assert len(pr_data["reviewers"]) == 2
    assert "Closes #2" in pr_data["body"]
    print("  ✓ PRDescription serialization works")
    
    print("  PASS: PatchArtifact and PRDescription\n")


# =============================================================================
# Test Runner
# =============================================================================

def run_all_tests():
    """运行所有测试"""
    print("=" * 70)
    print("P0 Batch 3: Issue Lane Baseline Schema Tests")
    print(f"Schema Version: {ISSUE_LANE_SCHEMA_VERSION}")
    print(f"Run Date: {datetime.now().isoformat()}")
    print("=" * 70)
    print()
    
    tests = [
        # Schema validation tests
        test_github_issue_url_validation,
        test_parse_github_issue_url,
        test_issue_input_validation,
        test_issue_input_serialization,
        test_planning_output_validation,
        test_execution_output_validation,
        test_closeout_output_validation,
        
        # Helper functions
        test_build_issue_input_helper,
        
        # End-to-end tests
        test_minimal_link_issue_to_closeout,
        test_issue_lane_contract_integration,
        
        # Compatibility
        test_backward_compatibility,
        
        # Artifact tests
        test_patch_artifact_and_pr_description,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            failed += 1
            print(f"  ✗ FAILED: {e}\n")
        except Exception as e:
            failed += 1
            print(f"  ✗ ERROR: {e}\n")
    
    print("=" * 70)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 70)
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
