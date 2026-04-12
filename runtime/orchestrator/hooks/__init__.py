#!/usr/bin/env python3
"""
hooks/__init__.py — 行为约束钩子

两个活跃钩子:
- post_promise_verify_hook: 验证派发是否有真实执行锚点
- post_completion_translate_hook: 强制完成报告包含结构化翻译

集成点 (hook_integrations):
- auto_dispatch.py: dispatch 前验证锚点
- completion_receipt.py: receipt 创建后强制翻译

Enforce mode 通过 OPENCLAW_HOOK_ENFORCE_MODE 环境变量控制:
- audit: 只记录（默认）
- warn: 记录 + 写入 metadata
- enforce: 阻塞操作
"""

from .post_completion_translate_hook import (
    PostCompletionTranslateHook,
    TranslationRequirement,
    check_completion_requires_translation,
    enforce_translation,
)

from .post_promise_verify_hook import (
    PostPromiseVerifyHook,
    PromiseAnchorCheck,
    verify_promise_has_anchor,
    validate_promise_anchor,
)

from .hook_integrations import (
    verify_dispatch_promise_anchor,
    log_anchor_violation,
    check_promise_timeout,
    enforce_completion_translation,
    log_translation_violation,
    check_pending_translations,
    auto_register,
    HOOK_VIOLATIONS_DIR,
)

__all__ = [
    "PostCompletionTranslateHook",
    "TranslationRequirement",
    "check_completion_requires_translation",
    "enforce_translation",
    "PostPromiseVerifyHook",
    "PromiseAnchorCheck",
    "verify_promise_has_anchor",
    "validate_promise_anchor",
    "verify_dispatch_promise_anchor",
    "log_anchor_violation",
    "check_promise_timeout",
    "enforce_completion_translation",
    "log_translation_violation",
    "check_pending_translations",
    "auto_register",
    "HOOK_VIOLATIONS_DIR",
]
