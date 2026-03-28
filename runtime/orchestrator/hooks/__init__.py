#!/usr/bin/env python3
"""
hooks/__init__.py — Observability 行为约束钩子包

导出所有钩子函数供 orchestrator / auto_dispatch 使用。
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
    HOOK_VIOLATIONS_DIR,
)

__all__ = [
    # Post-completion translation hook
    "PostCompletionTranslateHook",
    "TranslationRequirement",
    "check_completion_requires_translation",
    "enforce_translation",
    # Post-promise verification hook
    "PostPromiseVerifyHook",
    "PromiseAnchorCheck",
    "verify_promise_has_anchor",
    "validate_promise_anchor",
    # Hook integrations
    "verify_dispatch_promise_anchor",
    "log_anchor_violation",
    "check_promise_timeout",
    "enforce_completion_translation",
    "log_translation_violation",
    "check_pending_translations",
    "HOOK_VIOLATIONS_DIR",
]
