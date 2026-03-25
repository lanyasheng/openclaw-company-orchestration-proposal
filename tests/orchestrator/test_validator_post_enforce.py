#!/usr/bin/env python3
"""
test_validator_post_enforce.py — Validator Post-Enforce 调优测试

覆盖：
- format_decision_reason 函数
- generate_audit_summary 函数
- 结构化 decision reason 输出
- 审计样本汇总
"""

import json
import os
import sys
from pathlib import Path

# 添加 runtime 路径
sys.path.insert(0, str(Path(__file__).parent.parent / "runtime" / "orchestrator"))

from completion_validator_rules import (
    format_decision_reason,
    generate_audit_summary,
    BLOCK_RULE_DESCRIPTIONS,
    THROUGH_RULE_DESCRIPTIONS,
    GATE_RULE_DESCRIPTIONS,
)


def test_format_decision_reason_blocked():
    """测试格式化 blocked decision reason"""
    metadata = {
        "blocked": True,
        "block_reason": "B1_pure_directory_listing",
        "block_details": ["B1"],
    }
    
    result = format_decision_reason(
        status="blocked",
        reason="B1_pure_directory_listing",
        metadata=metadata,
    )
    
    assert result["status"] == "blocked"
    assert result["reason_code"] == "B1_pure_directory_listing"
    assert "目录列表" in result["reason_human"]
    assert result["rule_type"] == "block"
    assert len(result["rule_details"]) == 1
    assert result["rule_details"][0]["rule_id"] == "B1"
    assert len(result["suggestions"]) > 0
    assert "添加实际交付物" in result["suggestions"][0]
    
    print("✓ 格式化 blocked decision reason 正常")


def test_format_decision_reason_accepted():
    """测试格式化 accepted decision reason"""
    metadata = {
        "accepted": True,
        "through_score": 5,
        "through_threshold": 3,
        "through_details": ["T1", "T2", "T3"],
    }
    
    result = format_decision_reason(
        status="accepted",
        reason="",
        metadata=metadata,
    )
    
    assert result["status"] == "accepted"
    assert result["rule_type"] == "through"
    assert len(result["rule_details"]) == 3
    assert result["metadata_summary"]["score"] == 5
    assert result["metadata_summary"]["threshold"] == 3
    
    print("✓ 格式化 accepted decision reason 正常")


def test_format_decision_reason_gate():
    """测试格式化 gate decision reason"""
    metadata = {
        "gate": True,
        "gate_reason": "G1_boundary_case",
        "through_score": 2,
        "through_threshold": 3,
    }
    
    result = format_decision_reason(
        status="gate",
        reason="G1_boundary_case",
        metadata=metadata,
    )
    
    assert result["status"] == "gate"
    assert result["reason_code"] == "G1_boundary_case"
    assert result["rule_type"] == "gate"
    assert "边界" in result["reason_human"] or "审查" in result["reason_human"]
    assert "人工审查" in result["suggestions"][0]
    
    print("✓ 格式化 gate decision reason 正常")


def test_format_decision_reason_whitelisted():
    """测试格式化 whitelisted decision reason"""
    metadata = {
        "whitelisted": True,
        "whitelist_label": "explore",
        "whitelist_min_checks_passed": True,
    }
    
    result = format_decision_reason(
        status="accepted",
        reason="whitelisted",
        metadata=metadata,
    )
    
    assert result["status"] == "accepted"
    assert result["reason_code"] == "whitelisted"
    assert "白名单" in result["reason_human"]
    assert result["metadata_summary"]["whitelisted"] is True
    
    print("✓ 格式化 whitelisted decision reason 正常")


def test_format_decision_reason_error():
    """测试格式化 error decision reason"""
    metadata = {
        "error": True,
        "error_message": "Test error",
    }
    
    result = format_decision_reason(
        status="error",
        reason="Test error",
        metadata=metadata,
    )
    
    assert result["status"] == "error"
    assert result["rule_type"] == "error"
    assert "Validator 内部错误" in result["reason_human"]
    
    print("✓ 格式化 error decision reason 正常")


def test_format_decision_reason_multiple_blocks():
    """测试格式化多个 block 规则的 decision reason"""
    metadata = {
        "blocked": True,
        "block_reason": "B1_pure_directory_listing+B2",
        "block_details": ["B1", "B2"],
    }
    
    result = format_decision_reason(
        status="blocked",
        reason="B1_pure_directory_listing+B2",
        metadata=metadata,
    )
    
    assert result["status"] == "blocked"
    assert len(result["rule_details"]) == 2
    assert result["rule_details"][0]["rule_id"] == "B1"
    assert result["rule_details"][1]["rule_id"] == "B2"
    
    print("✓ 格式化多个 block 规则 decision reason 正常")


def test_generate_audit_summary_empty():
    """测试空审计汇总"""
    result = generate_audit_summary([])
    
    assert result["total"] == 0
    assert result["by_group"] == {}
    assert result["blocked_rate"] == 0.0
    assert result["gate_rate"] == 0.0
    assert result["common_block_reasons"] == []
    assert result["common_gate_reasons"] == []
    
    print("✓ 空审计汇总正常")


def test_generate_audit_summary_by_status():
    """测试按 status 分组的审计汇总"""
    audits = [
        {"audit_id": "1", "status": "accepted_completion", "reason": "", "label": "task1", "timestamp": "2026-03-25T12:00:00"},
        {"audit_id": "2", "status": "blocked_completion", "reason": "B1_pure_directory_listing", "label": "task2", "timestamp": "2026-03-25T12:01:00"},
        {"audit_id": "3", "status": "blocked_completion", "reason": "B1_pure_directory_listing", "label": "task3", "timestamp": "2026-03-25T12:02:00"},
        {"audit_id": "4", "status": "gate_required", "reason": "G1_boundary_case", "label": "task4", "timestamp": "2026-03-25T12:03:00"},
        {"audit_id": "5", "status": "accepted_completion", "reason": "", "label": "task5", "timestamp": "2026-03-25T12:04:00"},
    ]
    
    result = generate_audit_summary(audits, group_by="status")
    
    assert result["total"] == 5
    assert result["by_group"]["accepted_completion"] == 2
    assert result["by_group"]["blocked_completion"] == 2
    assert result["by_group"]["gate_required"] == 1
    assert result["blocked_rate"] == 0.4  # 2/5
    assert result["gate_rate"] == 0.2  # 1/5
    assert len(result["common_block_reasons"]) > 0
    assert result["common_block_reasons"][0]["reason"] == "B1_pure_directory_listing"
    assert result["common_block_reasons"][0]["count"] == 2
    
    print("✓ 按 status 分组的审计汇总正常")


def test_generate_audit_summary_by_label():
    """测试按 label 分组的审计汇总"""
    audits = [
        {"audit_id": "1", "status": "accepted_completion", "reason": "", "label": "coding", "timestamp": "2026-03-25T12:00:00"},
        {"audit_id": "2", "status": "blocked_completion", "reason": "B1", "label": "coding", "timestamp": "2026-03-25T12:01:00"},
        {"audit_id": "3", "status": "blocked_completion", "reason": "B1", "label": "explore", "timestamp": "2026-03-25T12:02:00"},
    ]
    
    result = generate_audit_summary(audits, group_by="label")
    
    assert result["total"] == 3
    assert result["by_group"]["coding"] == 2
    assert result["by_group"]["explore"] == 1
    
    print("✓ 按 label 分组的审计汇总正常")


def test_generate_audit_summary_by_date():
    """测试按 date 分组的审计汇总"""
    audits = [
        {"audit_id": "1", "status": "accepted_completion", "reason": "", "label": "task1", "timestamp": "2026-03-25T12:00:00"},
        {"audit_id": "2", "status": "blocked_completion", "reason": "B1", "label": "task2", "timestamp": "2026-03-25T13:00:00"},
        {"audit_id": "3", "status": "blocked_completion", "reason": "B1", "label": "task3", "timestamp": "2026-03-26T12:00:00"},
    ]
    
    result = generate_audit_summary(audits, group_by="date")
    
    assert result["total"] == 3
    assert result["by_group"]["2026-03-25"] == 2
    assert result["by_group"]["2026-03-26"] == 1
    
    print("✓ 按 date 分组的审计汇总正常")


def test_generate_audit_summary_samples():
    """测试审计汇总样本"""
    audits = [
        {"audit_id": f"audit_{i}", "status": "blocked_completion", "reason": "B1", "label": f"task{i}", "timestamp": f"2026-03-25T12:{i:02d}:00"}
        for i in range(10)
    ]
    
    result = generate_audit_summary(audits, group_by="status")
    
    assert result["total"] == 10
    assert "blocked_completion" in result["samples"]
    # 每个分组最多 5 个样本
    assert len(result["samples"]["blocked_completion"]) <= 5
    
    print("✓ 审计汇总样本正常")


def test_block_rule_descriptions():
    """测试 Block 规则描述"""
    assert "B1_pure_directory_listing" in BLOCK_RULE_DESCRIPTIONS
    assert "B2_pure_code_snippet" in BLOCK_RULE_DESCRIPTIONS
    assert "B3_intermediate_state" in BLOCK_RULE_DESCRIPTIONS
    assert "B4_unhandled_error" in BLOCK_RULE_DESCRIPTIONS
    assert "B5_nonzero_exit" in BLOCK_RULE_DESCRIPTIONS
    assert "B6_empty_output" in BLOCK_RULE_DESCRIPTIONS
    
    print("✓ Block 规则描述正常")


def test_through_rule_descriptions():
    """测试 Through 规则描述"""
    assert "T1" in THROUGH_RULE_DESCRIPTIONS
    assert "T2" in THROUGH_RULE_DESCRIPTIONS
    assert "T3" in THROUGH_RULE_DESCRIPTIONS
    assert "T4" in THROUGH_RULE_DESCRIPTIONS
    assert "T5" in THROUGH_RULE_DESCRIPTIONS
    assert "T6" in THROUGH_RULE_DESCRIPTIONS
    
    print("✓ Through 规则描述正常")


def test_gate_rule_descriptions():
    """测试 Gate 规则描述"""
    assert "G1_boundary_case" in GATE_RULE_DESCRIPTIONS
    assert "G2_blocked_with_explanation" in GATE_RULE_DESCRIPTIONS
    
    print("✓ Gate 规则描述正常")


def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("Validator Post-Enforce 调优测试")
    print("=" * 60)
    
    tests = [
        test_format_decision_reason_blocked,
        test_format_decision_reason_accepted,
        test_format_decision_reason_gate,
        test_format_decision_reason_whitelisted,
        test_format_decision_reason_error,
        test_format_decision_reason_multiple_blocks,
        test_generate_audit_summary_empty,
        test_generate_audit_summary_by_status,
        test_generate_audit_summary_by_label,
        test_generate_audit_summary_by_date,
        test_generate_audit_summary_samples,
        test_block_rule_descriptions,
        test_through_rule_descriptions,
        test_gate_rule_descriptions,
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
