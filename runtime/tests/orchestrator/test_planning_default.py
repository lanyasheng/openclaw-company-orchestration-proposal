#!/usr/bin/env python3
"""
test_planning_default.py — Planning Artifact Tests

测试 planning artifact 的生成、提取和验证。
"""

import sys
import os

# 添加 runtime/orchestrator 到路径
script_dir = os.path.dirname(os.path.abspath(__file__))
runtime_orchestrator_path = os.path.join(script_dir, '../../orchestrator')
sys.path.insert(0, runtime_orchestrator_path)

from planning_default import (
    PlanningArtifact,
    ProblemReframing,
    ScopeReview,
    EngineeringReview,
    ExecutionPlan,
    build_planning_artifact,
    extract_planning_artifact,
    validate_planning_artifact,
    merge_planning_into_dispatch,
    PLANNING_ARTIFACT_VERSION,
)


def test_problem_reframing_validate():
    """测试 ProblemReframing 验证"""
    print("Test: ProblemReframing.validate()")
    
    # 有效 case
    pr = ProblemReframing(
        problem_statement="Fix trading roundtable callback handling",
        success_criteria=["Callback processed", "Decision persisted"],
    )
    is_valid, errors = pr.validate()
    assert is_valid, f"Expected valid, got errors: {errors}"
    print("  ✓ Valid problem reframing passes validation")
    
    # 无效 case: 缺少 problem_statement
    pr_empty = ProblemReframing(
        problem_statement="",
        success_criteria=["test"],
    )
    is_valid, errors = pr_empty.validate()
    assert not is_valid, "Expected invalid for empty problem_statement"
    assert any("problem_statement" in e for e in errors)
    print("  ✓ Empty problem_statement fails validation")
    
    # 无效 case: 缺少 success_criteria
    pr_no_criteria = ProblemReframing(
        problem_statement="Test problem",
        success_criteria=[],
    )
    is_valid, errors = pr_no_criteria.validate()
    assert not is_valid, "Expected invalid for empty success_criteria"
    print("  ✓ Empty success_criteria fails validation")
    
    print("  PASS: ProblemReframing.validate()\n")


def test_scope_review_validate():
    """测试 ScopeReview 验证"""
    print("Test: ScopeReview.validate()")
    
    # 有效 case
    sr = ScopeReview(
        in_scope=["Implement feature X", "Write tests"],
    )
    is_valid, errors = sr.validate()
    assert is_valid, f"Expected valid, got errors: {errors}"
    print("  ✓ Valid scope review passes validation")
    
    # 无效 case: 缺少 in_scope
    sr_empty = ScopeReview(
        in_scope=[],
    )
    is_valid, errors = sr_empty.validate()
    assert not is_valid, "Expected invalid for empty in_scope"
    print("  ✓ Empty in_scope fails validation")
    
    print("  PASS: ScopeReview.validate()\n")


def test_build_planning_artifact():
    """测试 build_planning_artifact"""
    print("Test: build_planning_artifact()")
    
    artifact = build_planning_artifact(
        problem_statement="Implement continuation contract v1",
        in_scope=[
            "Define ContinuationContract schema",
            "Inject into closeout/completion链路",
            "Write tests",
        ],
        success_criteria=[
            "ContinuationContract fields frozen",
            "Backward compatible with old artifacts",
            "Tests pass",
        ],
        root_cause="Missing unified continuation semantics",
        context="P0-1 Batch 1 planning default + continuation contract",
        out_of_scope=["Refactor entire orchestrator"],
        dependencies=["partial_continuation.py", "closeout_tracker.py"],
        constraints=["Must be backward compatible"],
        technical_approach="Add ContinuationContract to existing artifacts",
        architecture_changes=["Add continuation_contract field to DispatchPlan"],
        risk_assessment=[
            {"risk": "Breaking changes", "impact": "high", "mitigation": "Keep old fields"},
        ],
        testing_strategy="Unit tests + integration test with trading_roundtable",
        rollback_plan="Revert commit if issues found",
        phases=[
            {"phase": "1", "description": "Define schema", "deliverable": "ContinuationContract class"},
            {"phase": "2", "description": "Inject into链路", "deliverable": "Updated dispatch/closeout"},
            {"phase": "3", "description": "Tests", "deliverable": "Test files"},
        ],
        milestones=["Schema defined", "Injection complete", "Tests passing"],
        estimated_duration="2h",
        owner="main",
    )
    
    # 验证 artifact
    is_valid, errors = artifact.validate()
    assert is_valid, f"Expected valid artifact, got errors: {errors}"
    print("  ✓ Built artifact passes validation")
    
    # 检查版本
    artifact_dict = artifact.to_dict()
    assert artifact_dict["artifact_version"] == PLANNING_ARTIFACT_VERSION
    print(f"  ✓ Artifact version is {PLANNING_ARTIFACT_VERSION}")
    
    # 检查必需字段
    assert artifact.problem_reframing.problem_statement != ""
    assert len(artifact.scope_review.in_scope) > 0
    assert artifact.engineering_review is not None
    assert artifact.execution_plan is not None
    print("  ✓ All required fields present")
    
    # 检查 to_dict/from_dict 往返
    artifact_from_dict = PlanningArtifact.from_dict(artifact_dict)
    assert artifact_from_dict.artifact_id == artifact.artifact_id
    assert artifact_from_dict.problem_reframing.problem_statement == artifact.problem_reframing.problem_statement
    print("  ✓ to_dict/from_dict roundtrip works")
    
    print("  PASS: build_planning_artifact()\n")


def test_validate_planning_artifact():
    """测试 validate_planning_artifact"""
    print("Test: validate_planning_artifact()")
    
    # 基本 artifact（没有 engineering_review）
    # 注意：execution_plan 会因为默认 owner="main" 而自动创建
    # 所以这里只测试 engineering_review 的情况
    artifact = build_planning_artifact(
        problem_statement="Test problem",
        in_scope=["task1"],
        success_criteria=["Test passes"],
    )
    
    # 默认验证（不要求可选字段）
    is_valid, errors = validate_planning_artifact(artifact)
    assert is_valid, f"Expected valid, got errors: {errors}"
    print("  ✓ Basic artifact passes default validation")
    
    # 要求 engineering_review
    is_valid, errors = validate_planning_artifact(artifact, require_engineering_review=True)
    assert not is_valid, "Expected invalid when requiring engineering_review"
    print("  ✓ Basic artifact fails when requiring engineering_review")
    
    # 注意：execution_plan 会因默认 owner="main" 而自动创建
    # 所以 require_execution_plan=True 会通过验证
    is_valid, errors = validate_planning_artifact(artifact, require_execution_plan=True)
    assert is_valid, f"Expected valid (execution_plan auto-created), got errors: {errors}"
    print("  ✓ Basic artifact passes when requiring execution_plan (auto-created)")
    
    print("  PASS: validate_planning_artifact()\n")


def test_extract_planning_artifact():
    """测试 extract_planning_artifact"""
    print("Test: extract_planning_artifact()")
    
    # 创建 artifact
    artifact = build_planning_artifact(
        problem_statement="Test extraction",
        in_scope=["extract test"],
        owner="test",
    )
    
    # 从 planning_artifact 字段提取
    payload1 = {"planning_artifact": artifact.to_dict()}
    extracted = extract_planning_artifact(payload1, source="direct")
    assert extracted is not None
    assert extracted.artifact_id == artifact.artifact_id
    print("  ✓ Extract from direct planning_artifact field works")
    
    # 从 dispatch_plan.metadata 提取
    payload2 = {"dispatch_plan": {"metadata": {"planning_artifact": artifact.to_dict()}}}
    extracted = extract_planning_artifact(payload2, source="dispatch_plan")
    assert extracted is not None
    print("  ✓ Extract from dispatch_plan.metadata works")
    
    # 从 decision.metadata 提取
    payload3 = {"decision": {"metadata": {"planning_artifact": artifact.to_dict()}}}
    extracted = extract_planning_artifact(payload3, source="decision")
    assert extracted is not None
    print("  ✓ Extract from decision.metadata works")
    
    # 不存在的 artifact
    payload4 = {"other": "data"}
    extracted = extract_planning_artifact(payload4, source="unknown")
    assert extracted is None
    print("  ✓ Returns None when artifact not present")
    
    print("  PASS: extract_planning_artifact()\n")


def test_merge_planning_into_dispatch():
    """测试 merge_planning_into_dispatch"""
    print("Test: merge_planning_into_dispatch()")
    
    artifact = build_planning_artifact(
        problem_statement="Test merge",
        in_scope=["merge test"],
        owner="main",
    )
    
    dispatch_plan = {
        "dispatch_id": "disp_test",
        "batch_id": "batch_test",
        "status": "triggered",
    }
    
    merged = merge_planning_into_dispatch(dispatch_plan, artifact)
    
    assert "planning_artifact" in merged["metadata"]
    assert "planning_artifact_id" in merged["metadata"]
    assert merged["metadata"]["planning_artifact_id"] == artifact.artifact_id
    print("  ✓ Planning artifact merged into dispatch plan metadata")
    
    # 检查原始 dispatch_plan 字段保留
    assert merged["dispatch_id"] == "disp_test"
    assert merged["batch_id"] == "batch_test"
    print("  ✓ Original dispatch plan fields preserved")
    
    print("  PASS: merge_planning_into_dispatch()\n")


def test_planning_artifact_write_read():
    """测试 planning artifact 文件读写"""
    print("Test: PlanningArtifact.write() / get_planning_artifact()")
    
    from planning_default import get_planning_artifact, _planning_file
    
    artifact = build_planning_artifact(
        problem_statement="Test file I/O",
        in_scope=["file test"],
        owner="main",
    )
    
    # 写入文件
    file_path = artifact.write()
    assert file_path.exists(), f"File not created: {file_path}"
    print(f"  ✓ Artifact written to {file_path}")
    
    # 读取文件
    loaded = get_planning_artifact(artifact.artifact_id)
    assert loaded is not None
    assert loaded.artifact_id == artifact.artifact_id
    print("  ✓ Artifact loaded from file")
    
    print("  PASS: PlanningArtifact.write() / get_planning_artifact()\n")


def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("Planning Default Tests")
    print("=" * 60 + "\n")
    
    test_problem_reframing_validate()
    test_scope_review_validate()
    test_build_planning_artifact()
    test_validate_planning_artifact()
    test_extract_planning_artifact()
    test_merge_planning_into_dispatch()
    test_planning_artifact_write_read()
    
    print("=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    run_all_tests()
