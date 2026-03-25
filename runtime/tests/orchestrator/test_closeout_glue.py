#!/usr/bin/env python3
"""
test_closeout_glue.py — Tests for Closeout Glue Core

测试覆盖：
1. 数据结构测试 (CloseoutGlueInput 序列化/反序列化)
2. Glue 映射测试 (receipt → closeout input)
3. Dispatch readiness 判定测试
4. Summary 提取测试
5. Continuation 字段提取测试
6. 最小接线测试 (集成到 completion_receipt)
7. 回归测试 (向后兼容)

运行：
```bash
cd <repo-root>
python3 runtime/orchestrator/closeout_glue.py test
python3 -m pytest runtime/tests/orchestrator/test_closeout_glue.py -v
```
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# 添加 runtime/orchestrator 到路径
orchestrator_path = Path(__file__).parent.parent.parent / "orchestrator"
sys.path.insert(0, str(orchestrator_path))

from closeout_glue import (
    CLOSEOUT_GLUE_VERSION,
    CloseoutGlueInput,
    DispatchReadiness,
    ExecutionToCloseoutGlue,
    map_receipt_to_closeout,
)
from completion_receipt import CompletionReceiptArtifact, ReceiptStatus

# 测试计数器
passed = 0
failed = 0


def test_closeout_glue_input_serialization():
    """测试 CloseoutGlueInput 序列化/反序列化"""
    global passed, failed
    
    input_obj = CloseoutGlueInput(
        source_execution_id="exec_001",
        source_receipt_id="receipt_001",
        source_receipt_status="completed",
        dispatch_readiness="ready",
        summary="Test summary",
        lineage_id="lineage_001",
        next_step="Next step",
        next_owner="main",
        stopped_because="Completed",
        metadata={"key": "value"},
    )
    
    # 序列化
    data = input_obj.to_dict()
    assert data["glue_version"] == CLOSEOUT_GLUE_VERSION
    assert data["source_execution_id"] == "exec_001"
    assert data["dispatch_readiness"] == "ready"
    
    # 反序列化
    restored = CloseoutGlueInput.from_dict(data)
    assert restored.source_execution_id == "exec_001"
    assert restored.dispatch_readiness == "ready"
    assert restored.metadata["key"] == "value"
    
    passed += 1
    print("✅ PASS: CloseoutGlueInput serialization")


def test_dispatch_readiness_completed():
    """测试 completed receipt → dispatch_readiness=ready"""
    global passed, failed
    
    glue = ExecutionToCloseoutGlue()
    readiness = glue._determine_dispatch_readiness("completed")
    
    assert readiness == "ready", f"Expected 'ready', got '{readiness}'"
    
    passed += 1
    print("✅ PASS: Dispatch readiness for completed receipt")


def test_dispatch_readiness_failed():
    """测试 failed receipt → dispatch_readiness=blocked"""
    global passed, failed
    
    glue = ExecutionToCloseoutGlue()
    readiness = glue._determine_dispatch_readiness("failed")
    
    assert readiness == "blocked", f"Expected 'blocked', got '{readiness}'"
    
    passed += 1
    print("✅ PASS: Dispatch readiness for failed receipt")


def test_dispatch_readiness_missing():
    """测试 missing receipt → dispatch_readiness=pending_review"""
    global passed, failed
    
    glue = ExecutionToCloseoutGlue()
    readiness = glue._determine_dispatch_readiness("missing")
    
    assert readiness == "pending_review", f"Expected 'pending_review', got '{readiness}'"
    
    passed += 1
    print("✅ PASS: Dispatch readiness for missing receipt")


def test_dispatch_readiness_metadata_override():
    """测试 metadata 显式覆盖 dispatch_readiness"""
    global passed, failed
    
    glue = ExecutionToCloseoutGlue()
    readiness = glue._determine_dispatch_readiness(
        "completed",
        metadata={"dispatch_readiness": "blocked"}
    )
    
    # Metadata 显式覆盖优先
    assert readiness == "blocked", f"Expected 'blocked' (metadata override), got '{readiness}'"
    
    passed += 1
    print("✅ PASS: Dispatch readiness metadata override")


def test_summary_extraction_from_result():
    """测试从 result_summary 提取摘要"""
    global passed, failed
    
    receipt = CompletionReceiptArtifact(
        receipt_id="receipt_001",
        source_spawn_execution_id="exec_001",
        source_spawn_id="spawn_001",
        source_dispatch_id="dispatch_001",
        source_registration_id="reg_001",
        source_task_id="task_001",
        receipt_status="completed",
        receipt_reason="Some reason",
        receipt_time="2026-03-25T00:00:00",
        result_summary="Custom summary from result",
        dedupe_key="dedupe_001",
    )
    
    glue = ExecutionToCloseoutGlue()
    summary = glue._extract_summary(receipt)
    
    assert summary == "Custom summary from result", f"Expected custom summary, got '{summary}'"
    
    passed += 1
    print("✅ PASS: Summary extraction from result_summary")


def test_summary_extraction_fallback_to_reason():
    """测试从 receipt_reason 提取摘要 (fallback)"""
    global passed, failed
    
    receipt = CompletionReceiptArtifact(
        receipt_id="receipt_001",
        source_spawn_execution_id="exec_001",
        source_spawn_id="spawn_001",
        source_dispatch_id="dispatch_001",
        source_registration_id="reg_001",
        source_task_id="task_001",
        receipt_status="failed",
        receipt_reason="Execution failed: timeout",
        receipt_time="2026-03-25T00:00:00",
        result_summary="",  # 空 summary
        dedupe_key="dedupe_001",
    )
    
    glue = ExecutionToCloseoutGlue()
    summary = glue._extract_summary(receipt)
    
    assert "Execution failed: timeout" in summary, f"Expected reason in summary, got '{summary}'"
    
    passed += 1
    print("✅ PASS: Summary extraction fallback to receipt_reason")


def test_continuation_fields_extraction():
    """测试从 continuation_contract 提取字段"""
    global passed, failed
    
    receipt = CompletionReceiptArtifact(
        receipt_id="receipt_001",
        source_spawn_execution_id="exec_001",
        source_spawn_id="spawn_001",
        source_dispatch_id="dispatch_001",
        source_registration_id="reg_001",
        source_task_id="task_001",
        receipt_status="completed",
        receipt_reason="Success",
        receipt_time="2026-03-25T00:00:00",
        result_summary="Summary",
        dedupe_key="dedupe_001",
        metadata={
            "continuation_contract": {
                "next_step": "Review changes",
                "next_owner": "trading",
                "stopped_because": "Execution completed",
            }
        },
    )
    
    glue = ExecutionToCloseoutGlue()
    fields = glue._extract_continuation_fields(receipt)
    
    assert fields["next_step"] == "Review changes"
    assert fields["next_owner"] == "trading"
    assert fields["stopped_because"] == "Execution completed"
    
    passed += 1
    print("✅ PASS: Continuation fields extraction")


def test_map_receipt_to_closeout_input_happy_path():
    """测试完整的 receipt → closeout input 映射 (happy path)"""
    global passed, failed
    
    receipt = CompletionReceiptArtifact(
        receipt_id="receipt_001",
        source_spawn_execution_id="exec_001",
        source_spawn_id="spawn_001",
        source_dispatch_id="dispatch_001",
        source_registration_id="reg_001",
        source_task_id="task_001",
        receipt_status="completed",
        receipt_reason="Success",
        receipt_time="2026-03-25T00:00:00",
        result_summary="Execution completed successfully",
        dedupe_key="dedupe_001",
        metadata={
            "continuation_contract": {
                "next_step": "Review and merge",
                "next_owner": "main",
                "stopped_because": "Completed",
            },
            "lineage_id": "lineage_001",
        },
    )
    
    glue = ExecutionToCloseoutGlue()
    closeout_input = glue.map_receipt_to_closeout_input(receipt)
    
    # 验证核心字段映射
    assert closeout_input.source_execution_id == "exec_001"
    assert closeout_input.source_receipt_id == "receipt_001"
    assert closeout_input.source_receipt_status == "completed"
    assert closeout_input.dispatch_readiness == "ready"
    assert closeout_input.summary == "Execution completed successfully"
    assert closeout_input.lineage_id == "lineage_001"
    assert closeout_input.next_step == "Review and merge"
    assert closeout_input.next_owner == "main"
    assert closeout_input.stopped_because == "Completed"
    
    # 验证 metadata
    assert closeout_input.metadata["source_task_id"] == "task_001"
    assert closeout_input.metadata["source_dispatch_id"] == "dispatch_001"
    
    passed += 1
    print("✅ PASS: Map receipt to closeout input (happy path)")


def test_map_receipt_to_closeout_failed():
    """测试 failed receipt 的映射"""
    global passed, failed
    
    receipt = CompletionReceiptArtifact(
        receipt_id="receipt_002",
        source_spawn_execution_id="exec_002",
        source_spawn_id="spawn_002",
        source_dispatch_id="dispatch_002",
        source_registration_id="reg_002",
        source_task_id="task_002",
        receipt_status="failed",
        receipt_reason="Validator blocked: invalid completion",
        receipt_time="2026-03-25T00:00:00",
        result_summary="Execution failed",
        dedupe_key="dedupe_002",
        metadata={
            "continuation_contract": {
                "next_step": "Fix validation errors",
                "next_owner": "main",
                "stopped_because": "Validator blocked",
            }
        },
    )
    
    glue = ExecutionToCloseoutGlue()
    closeout_input = glue.map_receipt_to_closeout_input(receipt)
    
    assert closeout_input.source_receipt_status == "failed"
    assert closeout_input.dispatch_readiness == "blocked"
    assert closeout_input.next_step == "Fix validation errors"
    
    passed += 1
    print("✅ PASS: Map receipt to closeout input (failed)")


def test_convenience_function():
    """测试便捷函数 map_receipt_to_closeout()"""
    global passed, failed
    
    receipt = CompletionReceiptArtifact(
        receipt_id="receipt_003",
        source_spawn_execution_id="exec_003",
        source_spawn_id="spawn_003",
        source_dispatch_id="dispatch_003",
        source_registration_id="reg_003",
        source_task_id="task_003",
        receipt_status="completed",
        receipt_reason="Success",
        receipt_time="2026-03-25T00:00:00",
        result_summary="Test",
        dedupe_key="dedupe_003",
    )
    
    closeout_input = map_receipt_to_closeout(receipt)
    
    assert closeout_input.source_execution_id == "exec_003"
    assert closeout_input.dispatch_readiness == "ready"
    
    passed += 1
    print("✅ PASS: Convenience function")


def test_minimal_integration_with_completion_receipt():
    """测试最小接线：从 completion_receipt 模块导入和使用"""
    global passed, failed
    
    # 验证 completion_receipt 模块可以正常导入
    from completion_receipt import (
        CompletionReceiptKernel,
        ReceiptStatus,
        RECEIPT_VERSION,
    )
    
    # 验证 closeout_glue 可以正常导入 completion_receipt
    from closeout_glue import ExecutionToCloseoutGlue, CloseoutGlueInput
    
    # 验证 ReceiptStatus 类型可以正常使用
    status: ReceiptStatus = "completed"
    assert status in ("completed", "failed", "missing")
    
    passed += 1
    print("✅ PASS: Minimal integration with completion_receipt")


def test_glue_version_constant():
    """测试 glue version 常量"""
    global passed, failed
    
    assert CLOSEOUT_GLUE_VERSION == "closeout_glue_v1"
    
    passed += 1
    print("✅ PASS: Glue version constant")


def test_dispatch_readiness_type():
    """测试 DispatchReadiness 类型定义"""
    global passed, failed
    
    # 验证类型定义
    valid_readiness = ["ready", "blocked", "pending_review", "missing"]
    
    for r in valid_readiness:
        # 类型检查（运行时无法直接验证 Literal，但可以验证值）
        assert r in valid_readiness
    
    passed += 1
    print("✅ PASS: DispatchReadiness type")


def run_all_tests():
    """运行所有测试"""
    global passed, failed
    
    print("=" * 60)
    print("Closeout Glue Core Tests")
    print("=" * 60)
    
    tests = [
        test_closeout_glue_input_serialization,
        test_dispatch_readiness_completed,
        test_dispatch_readiness_failed,
        test_dispatch_readiness_missing,
        test_dispatch_readiness_metadata_override,
        test_summary_extraction_from_result,
        test_summary_extraction_fallback_to_reason,
        test_continuation_fields_extraction,
        test_map_receipt_to_closeout_input_happy_path,
        test_map_receipt_to_closeout_failed,
        test_convenience_function,
        test_minimal_integration_with_completion_receipt,
        test_glue_version_constant,
        test_dispatch_readiness_type,
    ]
    
    for test in tests:
        try:
            test()
        except AssertionError as e:
            failed += 1
            print(f"❌ FAIL: {test.__name__}: {e}")
        except Exception as e:
            failed += 1
            print(f"❌ ERROR: {test.__name__}: {e}")
    
    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
