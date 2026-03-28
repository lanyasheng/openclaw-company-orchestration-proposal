#!/usr/bin/env python3
"""
test_hooks.py — Observability Batch 2 行为约束钩子测试

测试范围：
1. post_completion_translate_hook: 子任务完成后强制翻译汇报
2. post_promise_verify_hook: 承诺验证执行锚点

验收标准：
- ✅ 无翻译汇报的 completion 被检测
- ✅ 无锚点的承诺被拦截
- ✅ 测试通过率 100%

运行方式：
```bash
cd /Users/study/.openclaw/workspace/repos/openclaw-company-orchestration-proposal
python runtime/tests/orchestrator/observability/test_hooks.py
```
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta

# 添加 runtime/orchestrator 到路径
# 路径结构：runtime/tests/orchestrator/observability/test_hooks.py
# 需要添加：runtime/orchestrator
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "orchestrator"))

# 现在可以正常导入 hooks 模块
from hooks.post_completion_translate_hook import (
    PostCompletionTranslateHook,
    TranslationRequirement,
    check_completion_requires_translation,
    enforce_translation,
    log_translation_audit,
    TRANSLATION_AUDIT_DIR,
)

from hooks.post_promise_verify_hook import (
    PostPromiseVerifyHook,
    PromiseAnchorCheck,
    verify_promise_has_anchor,
    validate_promise_anchor,
    detect_promise_in_session,
    log_promise_audit,
    PROMISE_AUDIT_DIR,
)


def test_check_requires_translation_completed_receipt():
    """测试：已完成的 receipt 需要翻译汇报"""
    hook = PostCompletionTranslateHook()
    
    receipt = {
        "receipt_id": "receipt_abc123",
        "receipt_status": "completed",
        "receipt_reason": "Task completed successfully",
        "result_summary": "Fixed the bug in trading adapter",
    }
    
    task_context = {
        "scenario": "trading_roundtable",
        "label": "fix-trading-bug",
        "task_id": "task_001",
    }
    
    result = hook.check(receipt, task_context)
    
    assert result.requires_translation is True, f"Expected requires_translation=True, got {result.requires_translation}"
    assert result.reason == "completion_without_translation"
    assert "结论" in result.required_sections
    assert "证据" in result.required_sections
    assert "动作" in result.required_sections
    print("✅ test_check_requires_translation_completed_receipt PASSED")


def test_check_translation_already_provided():
    """测试：已有翻译汇报则不需要"""
    hook = PostCompletionTranslateHook()
    
    receipt = {
        "receipt_id": "receipt_abc123",
        "receipt_status": "completed",
        "receipt_reason": "Task completed",
        "result_summary": "Summary here",
        "human_translation": "## 结论\n已完成\n\n## 证据\n...\n\n## 动作\n...",
    }
    
    task_context = {
        "scenario": "trading_roundtable",
        "label": "fix-trading-bug",
    }
    
    result = hook.check(receipt, task_context)
    
    assert result.requires_translation is False
    assert result.reason == "translation_already_provided"
    print("✅ test_check_translation_already_provided PASSED")


def test_check_no_receipt():
    """测试：无 receipt 则不需要翻译"""
    hook = PostCompletionTranslateHook()
    
    result = hook.check(None, {})
    
    assert result.requires_translation is False
    assert result.reason == "no_completion_receipt"
    print("✅ test_check_no_receipt PASSED")


def test_enforce_translation_generates_report():
    """测试：强制生成翻译汇报"""
    hook = PostCompletionTranslateHook()
    
    receipt = {
        "receipt_id": "receipt_abc123",
        "receipt_status": "completed",
        "receipt_reason": "All tests passed",
        "result_summary": "Fixed the bug and added tests",
    }
    
    task_context = {
        "task_id": "task_001",
        "label": "fix-trading-bug",
        "scenario": "trading_roundtable",
    }
    
    translation = hook.enforce(receipt, task_context)
    
    assert "任务 ID" in translation
    assert "task_001" in translation
    assert "fix-trading-bug" in translation
    assert "结论" in translation
    assert "证据" in translation
    assert "动作" in translation
    assert "✅ 已完成" in translation
    print("✅ test_enforce_translation_generates_report PASSED")


def test_validate_translation_quality():
    """测试：验证翻译汇报质量"""
    hook = PostCompletionTranslateHook()
    
    # 合格的汇报
    good_translation = """
    ## 结论
    任务已完成
    
    ## 证据
    - 测试通过
    - 代码审查通过
    
    ## 动作
    - 等待下一步指示
    """
    
    passed, missing = hook.validate(good_translation)
    assert passed is True, f"Expected validation to pass, missing: {missing}"
    assert len(missing) == 0
    
    # 不合格的汇报（缺少章节）
    bad_translation = "任务做完了"
    
    passed, missing = hook.validate(bad_translation)
    assert passed is False
    assert len(missing) > 0
    print("✅ test_validate_translation_quality PASSED")


def test_verify_anchor_present():
    """测试：锚点存在且有效"""
    hook = PostPromiseVerifyHook()
    
    task_context = {
        "task_id": "task_001",
        "promise_anchor": {
            "anchor_type": "dispatch_id",
            "anchor_value": "dispatch_abc123def456",
            "promised_at": "2026-03-28T15:00:00",
            "promised_eta": "2026-03-28T16:00:00",
        },
    }
    
    result = hook.verify_anchor(task_context)
    
    assert result.has_anchor is True
    assert result.status == "anchor_verified"
    assert result.anchor_type == "dispatch_id"
    assert result.anchor_value == "dispatch_abc123def456"
    print("✅ test_verify_anchor_present PASSED")


def test_verify_anchor_missing():
    """测试：缺少锚点"""
    hook = PostPromiseVerifyHook()
    
    task_context = {
        "task_id": "task_001",
        # 缺少 promise_anchor
    }
    
    result = hook.verify_anchor(task_context)
    
    assert result.has_anchor is False
    assert result.status == "anchor_missing"
    assert "缺少" in result.missing_reason
    print("✅ test_verify_anchor_missing PASSED")


def test_verify_anchor_invalid_type():
    """测试：无效的锚点类型"""
    hook = PostPromiseVerifyHook()
    
    task_context = {
        "promise_anchor": {
            "anchor_type": "invalid_type",
            "anchor_value": "some_value",
        },
    }
    
    result = hook.verify_anchor(task_context)
    
    assert result.has_anchor is False
    assert result.status == "anchor_invalid"
    assert "无效" in result.missing_reason
    print("✅ test_verify_anchor_invalid_type PASSED")


def test_validate_anchor_format_dispatch_id():
    """测试：验证 dispatch_id 格式"""
    # 有效格式
    valid, reason = validate_promise_anchor("dispatch_id", "dispatch_abc123def456")
    assert valid is True, f"Expected valid=True, got {valid}, reason: {reason}"
    
    # 无效格式
    valid, reason = validate_promise_anchor("dispatch_id", "invalid")
    assert valid is False, f"Expected valid=False for invalid format"
    print("✅ test_validate_anchor_format_dispatch_id PASSED")


def test_validate_anchor_format_tmux_session():
    """测试：验证 tmux_session 格式"""
    # 有效格式
    valid, reason = validate_promise_anchor("tmux_session", "cc-feature-xxx")
    assert valid is True
    
    # 无效格式
    valid, reason = validate_promise_anchor("tmux_session", "invalid_session")
    assert valid is False
    print("✅ test_validate_anchor_format_tmux_session PASSED")


def test_detect_promise_in_session():
    """测试：检测会话中的承诺语句"""
    hook = PostPromiseVerifyHook()
    
    # 包含承诺的会话
    messages_with_promise = [
        {"role": "user", "content": "请修复这个 bug"},
        {"role": "assistant", "content": "好的，我正在处理这个任务"},
    ]
    
    detected, text = hook.detect_promise(messages_with_promise)
    assert detected is True, f"Expected promise detected, got {detected}"
    assert "正在处理" in text
    
    # 不包含承诺的会话
    messages_without_promise = [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "有什么可以帮助你的？"},
    ]
    
    detected, text = hook.detect_promise(messages_without_promise)
    assert detected is False
    print("✅ test_detect_promise_in_session PASSED")


def test_check_promise_timeout():
    """测试：检查承诺超时"""
    hook = PostPromiseVerifyHook()
    
    # 已过期的承诺
    expired_anchor = {
        "promised_eta": (datetime.now() - timedelta(minutes=60)).isoformat(),
    }
    
    is_timeout, reason = hook.check_promise_timeout(expired_anchor, threshold_minutes=30)
    assert is_timeout is True, f"Expected timeout, got {is_timeout}, reason: {reason}"
    assert "已超时" in reason
    
    # 未过期的承诺
    future_anchor = {
        "promised_eta": (datetime.now() + timedelta(minutes=30)).isoformat(),
    }
    
    is_timeout, reason = hook.check_promise_timeout(future_anchor, threshold_minutes=30)
    assert is_timeout is False
    print("✅ test_check_promise_timeout PASSED")


def test_audit_logging():
    """测试：审计日志记录"""
    # 翻译审计
    hook_translate = PostCompletionTranslateHook()
    receipt = {
        "receipt_id": "receipt_audit_test",
        "receipt_status": "completed",
        "result_summary": "Test summary",
    }
    task_context = {"task_id": "task_audit", "label": "test"}
    requirement = hook_translate.check(receipt, task_context)
    translation = hook_translate.enforce(receipt, task_context)
    audit_file = hook_translate.audit("receipt_audit_test", requirement, translation)
    assert audit_file.exists(), f"Audit file should exist: {audit_file}"
    
    # 承诺审计
    hook_promise = PostPromiseVerifyHook()
    task_context = {
        "task_id": "task_promise_audit",
        "promise_anchor": {
            "anchor_type": "dispatch_id",
            "anchor_value": "dispatch_audit123456",
        },
    }
    result = hook_promise.verify_anchor(task_context)
    promise_audit_file = hook_promise.audit("task_promise_audit", result)
    assert promise_audit_file.exists(), f"Promise audit file should exist: {promise_audit_file}"
    
    print("✅ test_audit_logging PASSED")


def test_convenience_functions():
    """测试：便捷函数"""
    # 翻译便捷函数
    receipt = {
        "receipt_id": "receipt_conv",
        "receipt_status": "completed",
        "result_summary": "Summary",
    }
    task_context = {"scenario": "trading_roundtable", "label": "test"}
    
    result = check_completion_requires_translation(receipt, task_context)
    assert isinstance(result, TranslationRequirement)
    assert result.requires_translation is True
    
    translation = enforce_translation(receipt, task_context)
    assert len(translation) > 50
    
    # 承诺便捷函数
    task_context = {
        "promise_anchor": {
            "anchor_type": "session_id",
            "anchor_value": "cc-test-session",
        },
    }
    result = verify_promise_has_anchor(task_context)
    assert isinstance(result, PromiseAnchorCheck)
    assert result.has_anchor is True
    
    # 检测承诺
    messages = [{"role": "assistant", "content": "进行中"}]
    detected, text = detect_promise_in_session(messages)
    assert detected is True
    
    print("✅ test_convenience_functions PASSED")


def test_integration_completion_without_translation_blocked():
    """集成测试：无翻译的完成被拦截"""
    receipt = {
        "receipt_id": "receipt_integration",
        "receipt_status": "completed",
        "result_summary": "Done",
    }
    task_context = {
        "scenario": "trading_roundtable",
        "label": "fix-bug",
        "task_id": "task_integration",
    }
    
    requirement = check_completion_requires_translation(receipt, task_context)
    assert requirement.requires_translation is True
    
    translation = enforce_translation(receipt, task_context)
    
    hook = PostCompletionTranslateHook()
    passed, missing = hook.validate(translation)
    assert passed is True
    
    print("✅ test_integration_completion_without_translation_blocked PASSED")


def test_integration_promise_without_anchor_blocked():
    """集成测试：无锚点的承诺被拦截"""
    task_context = {
        "task_id": "task_empty_promise",
    }
    
    result = verify_promise_has_anchor(task_context)
    assert result.has_anchor is False
    assert result.status == "anchor_missing"
    assert result.suggested_fix != ""
    
    audit_file = log_promise_audit("task_empty_promise", result)
    assert audit_file.exists()
    
    print("✅ test_integration_promise_without_anchor_blocked PASSED")


def run_all_tests():
    """运行所有测试"""
    tests = [
        test_check_requires_translation_completed_receipt,
        test_check_translation_already_provided,
        test_check_no_receipt,
        test_enforce_translation_generates_report,
        test_validate_translation_quality,
        test_verify_anchor_present,
        test_verify_anchor_missing,
        test_verify_anchor_invalid_type,
        test_validate_anchor_format_dispatch_id,
        test_validate_anchor_format_tmux_session,
        test_detect_promise_in_session,
        test_check_promise_timeout,
        test_audit_logging,
        test_convenience_functions,
        test_integration_completion_without_translation_blocked,
        test_integration_promise_without_anchor_blocked,
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
            failed += 1
    
    print(f"\n{'='*60}")
    print(f"Tests: {passed + failed} | Passed: {passed} | Failed: {failed}")
    print(f"{'='*60}")
    
    if failed == 0:
        print("✅ All tests PASSED!")
        return 0
    else:
        print(f"❌ {failed} test(s) FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
