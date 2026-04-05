#!/usr/bin/env python3
"""
hook_integrations.py — Observability Batch 2 钩子集成点

将行为约束钩子集成到 orchestrator 关键路径：
1. auto_dispatch.py: dispatch 前验证锚点
2. completion_receipt.py: receipt 创建后强制翻译汇报

使用示例：
```python
# auto_dispatch.py 中
from hook_integrations import verify_dispatch_promise_anchor

# dispatch 前验证锚点
anchor_ok, anchor_reason = verify_dispatch_promise_anchor(record, dispatch_artifact)
if not anchor_ok:
    # 拦截 dispatch
    log_anchor_violation(record.task_id, anchor_reason)
```
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    # Promise anchor verification (auto_dispatch integration)
    "verify_dispatch_promise_anchor",
    "log_anchor_violation",
    "check_promise_timeout",
    # Completion translation (completion_receipt integration)
    "enforce_completion_translation",
    "log_translation_violation",
    "check_pending_translations",
    # Dispatcher auto-registration
    "auto_register",
    # Audit directories
    "HOOK_VIOLATIONS_DIR",
]

# Hook violations audit directory
HOOK_VIOLATIONS_DIR = Path(
    os.environ.get(
        "OPENCLAW_HOOK_VIOLATIONS_DIR",
        Path.home() / ".openclaw" / "shared-context" / "hook_violations",
    )
)


def _ensure_violations_dir() -> None:
    """确保 violations 目录存在"""
    HOOK_VIOLATIONS_DIR.mkdir(parents=True, exist_ok=True)


def _iso_now() -> str:
    """返回当前 ISO-8601 时间戳"""
    return datetime.now(timezone.utc).isoformat()


def _generate_violation_id() -> str:
    """生成 stable violation ID"""
    import uuid
    return f"hook_violation_{uuid.uuid4().hex[:12]}"


# =============================================================================
# Promise Anchor Verification (auto_dispatch integration)
# =============================================================================

def verify_dispatch_promise_anchor(
    record: Any,
    dispatch_artifact: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str]:
    """
    验证 dispatch 是否包含有效承诺锚点。
    
    集成点：auto_dispatch.py - DispatchExecutor.generate_dispatch_artifact()
    
    规则：
    1. record 必须有 truth_anchor
    2. dispatch_artifact 必须有 execution_intent 包含 anchor
    3. anchor_type 和 anchor_value 必须有效
    
    Args:
        record: TaskRegistrationRecord
        dispatch_artifact: Dispatch artifact（可选，创建后验证）
    
    Returns:
        (是否有效，原因)
    """
    # Check 1: record 必须有 truth_anchor
    if not hasattr(record, 'truth_anchor') or not record.truth_anchor:
        return False, "Missing truth_anchor in task registration"
    
    anchor_type = record.truth_anchor.anchor_type if hasattr(record.truth_anchor, 'anchor_type') else ""
    anchor_value = record.truth_anchor.anchor_value if hasattr(record.truth_anchor, 'anchor_value') else ""
    
    # Check 2: anchor_value 必须非空
    if not anchor_value or anchor_value.strip() == "":
        return False, "Anchor value is empty"
    
    # Check 3: 验证 anchor 格式（如果提供了 dispatch_artifact）
    if dispatch_artifact:
        execution_intent = dispatch_artifact.get("execution_intent", {})
        if execution_intent:
            recommended_spawn = execution_intent.get("recommended_spawn", {})
            spawn_anchor = recommended_spawn.get("anchor", {})
            
            # 验证 spawn anchor 与 truth_anchor 一致
            if spawn_anchor:
                spawn_anchor_type = spawn_anchor.get("anchor_type", "")
                spawn_anchor_value = spawn_anchor.get("anchor_value", "")
                
                if spawn_anchor_value and spawn_anchor_value != anchor_value:
                    return False, f"Anchor mismatch: truth={anchor_value}, spawn={spawn_anchor_value}"
    
    return True, "Anchor verified"


def log_anchor_violation(
    task_id: str,
    violation_reason: str,
    record_metadata: Optional[Dict[str, Any]] = None,
) -> Path:
    """
    记录锚点违规审计日志。
    
    Args:
        task_id: 任务 ID
        violation_reason: 违规原因
        record_metadata: 记录元数据（可选）
    
    Returns:
        审计日志文件路径
    """
    _ensure_violations_dir()
    
    violation_id = _generate_violation_id()
    timestamp = _iso_now()
    
    violation_record = {
        "violation_id": violation_id,
        "timestamp": timestamp,
        "violation_type": "anchor_missing",
        "task_id": task_id,
        "reason": violation_reason,
        "metadata": record_metadata or {},
    }
    
    # 原子写入
    violation_file = HOOK_VIOLATIONS_DIR / f"{violation_id}.json"
    tmp_file = violation_file.with_suffix(".tmp")
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(violation_record, f, indent=2, ensure_ascii=False)
    tmp_file.replace(violation_file)
    
    return violation_file


def check_promise_timeout(
    promise_anchor: Dict[str, Any],
    threshold_minutes: int = 30,
) -> Tuple[bool, str]:
    """
    检查承诺是否超时。
    
    集成点：watchdog.py - 定期巡检
    
    Args:
        promise_anchor: 承诺锚点（包含 promised_eta）
        threshold_minutes: 超时阈值（分钟）
    
    Returns:
        (是否超时，超时信息)
    """
    promised_eta = promise_anchor.get("promised_eta", "")
    if not promised_eta:
        return False, "No promised_eta field"
    
    try:
        eta_dt = datetime.fromisoformat(promised_eta)
        now_dt = datetime.now()
        delta = now_dt - eta_dt
        
        if delta.total_seconds() > threshold_minutes * 60:
            return True, f"超时 {int(delta.total_seconds() / 60)} 分钟（阈值：{threshold_minutes} 分钟）"
        else:
            return False, "未超时"
    except (ValueError, TypeError) as e:
        return False, f"解析 promised_eta 失败：{e}"


# =============================================================================
# Completion Translation (completion_receipt integration)
# =============================================================================

def enforce_completion_translation(
    receipt: Dict[str, Any],
    task_context: Dict[str, Any],
    enforce_mode_override: Optional[str] = None,
) -> Tuple[bool, str, Optional[str]]:
    """
    强制 completion receipt 包含翻译汇报。
    
    集成点：completion_receipt.py - CompletionReceiptKernel.create_receipt()
    
    规则：
    1. receipt_status 为 completed/failed 时必须有人话汇报
    2. 汇报必须包含 结论/证据/动作 三层结构
    3. 无汇报则自动生成并记录违规
    
    Args:
        receipt: Completion receipt artifact（字典形式）
        task_context: 任务上下文（scenario/label/task_id 等）
        enforce_mode_override: 可选的 enforce mode 覆盖（"audit"/"warn"/"enforce"）
    
    Returns:
        (是否需要翻译，原因，翻译文本)
    
    Raises:
        HookViolationError: enforce 模式下无法生成翻译时抛出
    """
    # 导入钩子模块
    try:
        from hooks.post_completion_translate_hook import (
            PostCompletionTranslateHook,
            check_completion_requires_translation,
            enforce_translation,
        )
        from hooks.hook_exceptions import HookViolationError
    except ImportError:
        return False, "Hook module not available", None
    
    hook = PostCompletionTranslateHook()
    
    # 检查是否需要翻译
    requirement = hook.check(receipt, task_context)
    
    if not requirement.requires_translation:
        return False, requirement.reason, None
    
    # 强制生成翻译（支持 enforce mode）
    translation = hook.enforce(receipt, task_context, enforce_mode_override=enforce_mode_override)
    
    # 验证翻译质量
    if translation:
        passed, missing = hook.validate(translation)
        if not passed:
            # 翻译质量不达标，记录违规
            return True, f"Translation quality issue: {missing}", translation
    
    return True, "Translation enforced", translation


def log_translation_violation(
    receipt_id: str,
    task_id: str,
    violation_reason: str,
    receipt_metadata: Optional[Dict[str, Any]] = None,
) -> Path:
    """
    记录翻译违规审计日志。
    
    Args:
        receipt_id: Receipt ID
        task_id: 任务 ID
        violation_reason: 违规原因
        receipt_metadata: Receipt 元数据（可选）
    
    Returns:
        审计日志文件路径
    """
    _ensure_violations_dir()
    
    violation_id = _generate_violation_id()
    timestamp = _iso_now()
    
    violation_record = {
        "violation_id": violation_id,
        "timestamp": timestamp,
        "violation_type": "translation_missing",
        "receipt_id": receipt_id,
        "task_id": task_id,
        "reason": violation_reason,
        "metadata": receipt_metadata or {},
    }
    
    # 原子写入
    violation_file = HOOK_VIOLATIONS_DIR / f"{violation_id}.json"
    tmp_file = violation_file.with_suffix(".tmp")
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(violation_record, f, indent=2, ensure_ascii=False)
    tmp_file.replace(violation_file)
    
    return violation_file


def check_pending_translations(
    receipts_dir: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """
    检查所有 pending translation 的 receipts。
    
    集成点：watchdog.py - 定期巡检
    
    Args:
        receipts_dir: Completion receipts 目录（可选）
    
    Returns:
        pending translations 列表
    """
    from hooks.post_completion_translate_hook import check_completion_requires_translation
    
    pending = []
    
    # 默认 receipts 目录
    if receipts_dir is None:
        receipts_dir = Path.home() / ".openclaw" / "shared-context" / "completion_receipts"
    
    if not receipts_dir.exists():
        return pending
    
    for receipt_file in receipts_dir.glob("*.json"):
        if receipt_file.name == "receipt_index.json":
            continue
        
        try:
            with open(receipt_file, "r", encoding="utf-8") as f:
                receipt = json.load(f)
            
            # 检查是否需要翻译
            task_context = {
                "scenario": receipt.get("metadata", {}).get("scenario", ""),
                "label": receipt.get("metadata", {}).get("label", ""),
                "task_id": receipt.get("source_task_id", ""),
            }
            
            requirement = check_completion_requires_translation(receipt, task_context)
            
            if requirement.requires_translation:
                pending.append({
                    "receipt_id": receipt.get("receipt_id", ""),
                    "task_id": receipt.get("source_task_id", ""),
                    "reason": requirement.reason,
                    "receipt_status": receipt.get("receipt_status", ""),
                })
        except (json.JSONDecodeError, KeyError):
            continue
    
    return pending


# =============================================================================
# Dispatcher auto-registration
# =============================================================================

def auto_register(dispatcher) -> None:
    """Register all built-in hooks with the centralized dispatcher.

    Wraps the existing ``PostPromiseVerifyHook`` and
    ``PostCompletionTranslateHook`` so they conform to the dispatcher's
    ``(event, context) -> HookResult`` signature.

    Args:
        dispatcher: A ``HookDispatcher`` instance.
    """
    from .hook_dispatcher import HookResult
    from .post_promise_verify_hook import PostPromiseVerifyHook
    from .post_completion_translate_hook import PostCompletionTranslateHook

    # -- PostPromiseVerifyHook on "pre_reply" ---------------------------------

    _promise_hook = PostPromiseVerifyHook()

    def _promise_verify_adapter(event: str, context: Dict[str, Any]) -> HookResult:
        """Adapter: run promise-anchor verification on pre_reply."""
        task_context = context.get("task_context", context)
        check = _promise_hook.verify_anchor(task_context)
        if check.has_anchor:
            return HookResult(action="continue", reason="anchor_verified")
        return HookResult(
            action="block",
            reason=check.missing_reason,
            metadata=check.to_dict(),
        )

    dispatcher.register(
        "pre_reply",
        _promise_verify_adapter,
        priority=10,
        name="post_promise_verify",
    )

    # -- PostCompletionTranslateHook on "post_completion" ---------------------

    _translate_hook = PostCompletionTranslateHook()

    def _completion_translate_adapter(event: str, context: Dict[str, Any]) -> HookResult:
        """Adapter: check/enforce completion translation on post_completion."""
        receipt = context.get("completion_receipt")
        task_ctx = context.get("task_context", {})

        requirement = _translate_hook.check(receipt, task_ctx)
        if not requirement.requires_translation:
            return HookResult(action="continue", reason=requirement.reason)

        translation = _translate_hook.enforce(receipt or {}, task_ctx)
        if translation:
            return HookResult(
                action="modify",
                reason="translation_generated",
                metadata={"translation": translation},
            )
        return HookResult(
            action="block",
            reason="translation_required_but_failed",
            metadata=requirement.to_dict(),
        )

    dispatcher.register(
        "post_completion",
        _completion_translate_adapter,
        priority=10,
        name="post_completion_translate",
    )


# =============================================================================
# Integration Examples
# =============================================================================

"""
集成示例：

1. auto_dispatch.py 集成：

```python
from hook_integrations import verify_dispatch_promise_anchor, log_anchor_violation

class DispatchExecutor:
    def generate_dispatch_artifact(self, record, policy_evaluation):
        # ... 现有逻辑 ...
        
        # Batch 2: 验证承诺锚点
        anchor_ok, anchor_reason = verify_dispatch_promise_anchor(record, artifact.to_dict())
        if not anchor_ok:
            # 记录违规但不阻止 dispatch（audit-only 模式）
            log_anchor_violation(record.task_id, anchor_reason, {
                "registration_id": record.registration_id,
                "dispatch_id": artifact.dispatch_id,
            })
            # 可以在这里选择阻止 dispatch 或仅记录
            # artifact.dispatch_status = "blocked"
            # artifact.dispatch_reason = anchor_reason
        
        return artifact
```

2. completion_receipt.py 集成：

```python
from hook_integrations import enforce_completion_translation, log_translation_violation

class CompletionReceiptKernel:
    def create_receipt(self, execution):
        # ... 现有逻辑 ...
        
        # Batch 2: 强制翻译汇报
        receipt_dict = {
            "receipt_id": receipt_id,
            "receipt_status": receipt_status,
            "receipt_reason": receipt_reason,
            "result_summary": result_summary,
            "metadata": metadata,
        }
        
        task_context = {
            "scenario": metadata.get("scenario", ""),
            "label": metadata.get("label", ""),
            "task_id": execution.task_id,
        }
        
        translation_required, translation_reason, translation = enforce_completion_translation(
            receipt_dict, task_context
        )
        
        if translation_required and translation:
            # 将翻译添加到 receipt metadata
            metadata["human_translation"] = translation
            metadata["translation_enforced"] = True
        elif translation_required and not translation:
            # 记录违规
            log_translation_violation(receipt_id, execution.task_id, translation_reason, metadata)
        
        # ... 继续创建 receipt ...
```

3. watchdog.py 集成：

```python
from hook_integrations import check_pending_translations, check_promise_timeout

def periodic_hook_check():
    # 检查 pending translations
    pending = check_pending_translations()
    if pending:
        print(f"⚠️ {len(pending)} receipts pending translation")
        for p in pending[:5]:  # 只显示前 5 个
            print(f"  - {p['task_id']}: {p['reason']}")
    
    # 检查承诺超时
    # ... 从 observability cards 读取 promise_anchor ...
```
"""
