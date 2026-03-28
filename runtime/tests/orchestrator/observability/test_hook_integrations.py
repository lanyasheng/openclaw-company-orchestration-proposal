#!/usr/bin/env python3
"""
test_hook_integrations.py — Observability Batch 2 钩子集成测试

测试范围：
1. auto_dispatch.py 集成：dispatch 时验证锚点
2. completion_receipt.py 集成：receipt 创建时强制翻译

验收标准：
- ✅ 钩子集成不破坏现有流程
- ✅ 违规行为被记录到审计日志
- ✅ 测试通过率 100%

运行方式：
```bash
cd /Users/study/.openclaw/workspace/repos/openclaw-company-orchestration-proposal
python runtime/tests/orchestrator/observability/test_hook_integrations.py
```
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta

# 添加 runtime/orchestrator 到路径
# 路径结构：runtime/tests/orchestrator/observability/test_hook_integrations.py
# 需要添加：runtime/orchestrator
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "orchestrator"))

from hooks.hook_integrations import (
    verify_dispatch_promise_anchor,
    log_anchor_violation,
    check_promise_timeout,
    enforce_completion_translation,
    log_translation_violation,
    check_pending_translations,
    HOOK_VIOLATIONS_DIR,
)


class MockTruthAnchor:
    """Mock truth anchor for testing"""
    def __init__(self, anchor_type: str, anchor_value: str):
        self.anchor_type = anchor_type
        self.anchor_value = anchor_value
    
    def to_dict(self):
        return {
            "anchor_type": self.anchor_type,
            "anchor_value": self.anchor_value,
        }


class MockTaskRegistrationRecord:
    """Mock task registration record for testing"""
    def __init__(
        self,
        task_id: str,
        registration_id: str,
        truth_anchor: MockTruthAnchor,
        metadata: dict = None,
    ):
        self.task_id = task_id
        self.registration_id = registration_id
        self.truth_anchor = truth_anchor
        self.metadata = metadata or {}
        self.batch_id = "batch_test"
        self.owner = "test"
        self.proposed_task = {
            "task_type": "continuation",
            "title": "Test task",
            "description": "Test description",
        }


def test_verify_dispatch_promise_anchor_valid():
    """测试：验证有效的 dispatch 锚点"""
    anchor = MockTruthAnchor("dispatch_id", "dispatch_abc123def456")
    record = MockTaskRegistrationRecord(
        task_id="task_test",
        registration_id="reg_test",
        truth_anchor=anchor,
    )
    
    dispatch_artifact = {
        "dispatch_id": "dispatch_test",
        "execution_intent": {
            "recommended_spawn": {
                "anchor": {
                    "anchor_type": "dispatch_id",
                    "anchor_value": "dispatch_abc123def456",
                }
            }
        }
    }
    
    anchor_ok, anchor_reason = verify_dispatch_promise_anchor(record, dispatch_artifact)
    
    assert anchor_ok is True, f"Expected anchor_ok=True, got {anchor_ok}, reason: {anchor_reason}"
    assert "verified" in anchor_reason.lower()
    print("✅ test_verify_dispatch_promise_anchor_valid PASSED")


def test_verify_dispatch_promise_anchor_missing():
    """测试：验证缺少锚点的 dispatch"""
    record = MockTaskRegistrationRecord(
        task_id="task_test",
        registration_id="reg_test",
        truth_anchor=None,  # 缺少锚点
    )
    
    anchor_ok, anchor_reason = verify_dispatch_promise_anchor(record)
    
    assert anchor_ok is False, f"Expected anchor_ok=False, got {anchor_ok}"
    assert "Missing" in anchor_reason or "missing" in anchor_reason
    print("✅ test_verify_dispatch_promise_anchor_missing PASSED")


def test_verify_dispatch_promise_anchor_empty_value():
    """测试：验证锚点值为空的 dispatch"""
    anchor = MockTruthAnchor("dispatch_id", "")  # 空值
    record = MockTaskRegistrationRecord(
        task_id="task_test",
        registration_id="reg_test",
        truth_anchor=anchor,
    )
    
    anchor_ok, anchor_reason = verify_dispatch_promise_anchor(record)
    
    assert anchor_ok is False
    assert "empty" in anchor_reason.lower()
    print("✅ test_verify_dispatch_promise_anchor_empty_value PASSED")


def test_log_anchor_violation():
    """测试：记录锚点违规审计日志"""
    violation_file = log_anchor_violation(
        task_id="task_violation_test",
        violation_reason="Test violation reason",
        record_metadata={"test": "metadata"},
    )
    
    assert violation_file.exists(), f"Violation file should exist: {violation_file}"
    
    # 验证审计内容
    with open(violation_file, "r", encoding="utf-8") as f:
        violation_data = json.load(f)
    
    assert violation_data["task_id"] == "task_violation_test"
    assert violation_data["reason"] == "Test violation reason"
    assert violation_data["violation_type"] == "anchor_missing"
    assert "violation_id" in violation_data
    
    print("✅ test_log_anchor_violation PASSED")


def test_check_promise_timeout_expired():
    """测试：检查已过期的承诺"""
    promise_anchor = {
        "promised_eta": (datetime.now() - timedelta(minutes=60)).isoformat(),
    }
    
    is_timeout, reason = check_promise_timeout(promise_anchor, threshold_minutes=30)
    
    assert is_timeout is True, f"Expected timeout, got {is_timeout}, reason: {reason}"
    assert "超时" in reason
    print("✅ test_check_promise_timeout_expired PASSED")


def test_check_promise_timeout_not_expired():
    """测试：检查未过期的承诺"""
    promise_anchor = {
        "promised_eta": (datetime.now() + timedelta(minutes=30)).isoformat(),
    }
    
    is_timeout, reason = check_promise_timeout(promise_anchor, threshold_minutes=30)
    
    assert is_timeout is False
    print("✅ test_check_promise_timeout_not_expired PASSED")


def test_enforce_completion_translation_required():
    """测试：强制需要翻译的 completion"""
    receipt = {
        "receipt_id": "receipt_test",
        "receipt_status": "completed",
        "receipt_reason": "Task completed",
        "result_summary": "Test summary",
    }
    
    task_context = {
        "scenario": "trading_roundtable",
        "label": "fix-bug",
        "task_id": "task_test",
    }
    
    translation_required, translation_reason, translation = enforce_completion_translation(
        receipt, task_context
    )
    
    assert translation_required is True, f"Expected translation_required=True, got {translation_required}"
    assert translation is not None, "Translation should be generated"
    assert "结论" in translation, "Translation should contain required sections"
    assert "证据" in translation
    assert "动作" in translation
    
    print("✅ test_enforce_completion_translation_required PASSED")


def test_enforce_completion_translation_not_required():
    """测试：不需要翻译的 completion"""
    receipt = {
        "receipt_id": "receipt_test",
        "receipt_status": "pending",  # 非终态
        "result_summary": "Still working",
    }
    
    task_context = {
        "scenario": "trading_roundtable",
        "label": "test",
        "task_id": "task_test",
    }
    
    translation_required, translation_reason, translation = enforce_completion_translation(
        receipt, task_context
    )
    
    assert translation_required is False
    print("✅ test_enforce_completion_translation_not_required PASSED")


def test_log_translation_violation():
    """测试：记录翻译违规审计日志"""
    violation_file = log_translation_violation(
        receipt_id="receipt_violation_test",
        task_id="task_violation_test",
        violation_reason="Test translation violation",
        receipt_metadata={"test": "metadata"},
    )
    
    assert violation_file.exists(), f"Violation file should exist: {violation_file}"
    
    # 验证审计内容
    with open(violation_file, "r", encoding="utf-8") as f:
        violation_data = json.load(f)
    
    assert violation_data["receipt_id"] == "receipt_violation_test"
    assert violation_data["task_id"] == "task_violation_test"
    assert violation_data["violation_type"] == "translation_missing"
    
    print("✅ test_log_translation_violation PASSED")


def test_check_pending_translations_empty():
    """测试：检查 pending translations（空目录）"""
    # 使用临时目录
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        pending = check_pending_translations(Path(tmpdir))
        assert pending == [], f"Expected empty list, got {pending}"
    
    print("✅ test_check_pending_translations_empty PASSED")


def test_integration_anchor_violation_workflow():
    """集成测试：锚点违规工作流"""
    # 1. 创建缺少锚点的记录
    record = MockTaskRegistrationRecord(
        task_id="task_integration",
        registration_id="reg_integration",
        truth_anchor=None,
    )
    
    # 2. 验证锚点
    anchor_ok, anchor_reason = verify_dispatch_promise_anchor(record)
    assert anchor_ok is False
    
    # 3. 记录违规
    violation_file = log_anchor_violation(
        task_id="task_integration",
        violation_reason=anchor_reason,
        record_metadata={"registration_id": "reg_integration"},
    )
    assert violation_file.exists()
    
    # 4. 验证违规记录
    with open(violation_file, "r", encoding="utf-8") as f:
        violation_data = json.load(f)
    
    assert violation_data["task_id"] == "task_integration"
    assert violation_data["violation_type"] == "anchor_missing"
    
    print("✅ test_integration_anchor_violation_workflow PASSED")


def test_integration_translation_enforcement_workflow():
    """集成测试：翻译强制执行工作流"""
    # 1. 创建需要翻译的 receipt
    receipt = {
        "receipt_id": "receipt_integration",
        "receipt_status": "completed",
        "result_summary": "Integration test summary",
    }
    
    task_context = {
        "scenario": "trading_roundtable",
        "label": "integration-test",
        "task_id": "task_integration",
    }
    
    # 2. 强制翻译
    translation_required, translation_reason, translation = enforce_completion_translation(
        receipt, task_context
    )
    assert translation_required is True
    assert translation is not None
    
    # 3. 验证翻译包含必需章节
    assert "结论" in translation
    assert "证据" in translation
    assert "动作" in translation
    
    # 4. 将翻译添加到 receipt
    receipt["human_translation"] = translation
    
    # 5. 再次检查，应该不需要翻译了
    translation_required2, _, _ = enforce_completion_translation(receipt, task_context)
    assert translation_required2 is False
    
    print("✅ test_integration_translation_enforcement_workflow PASSED")


def run_all_tests():
    """运行所有测试"""
    tests = [
        test_verify_dispatch_promise_anchor_valid,
        test_verify_dispatch_promise_anchor_missing,
        test_verify_dispatch_promise_anchor_empty_value,
        test_log_anchor_violation,
        test_check_promise_timeout_expired,
        test_check_promise_timeout_not_expired,
        test_enforce_completion_translation_required,
        test_enforce_completion_translation_not_required,
        test_log_translation_violation,
        test_check_pending_translations_empty,
        test_integration_anchor_violation_workflow,
        test_integration_translation_enforcement_workflow,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"❌ {test.__name__} FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"❌ {test.__name__} ERROR: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print(f"\n{'='*60}")
    print(f"Tests: {passed + failed} | Passed: {passed} | Failed: {failed}")
    print(f"{'='*60}")
    
    if failed == 0:
        print("✅ All integration tests PASSED!")
        return 0
    else:
        print(f"❌ {failed} test(s) FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
