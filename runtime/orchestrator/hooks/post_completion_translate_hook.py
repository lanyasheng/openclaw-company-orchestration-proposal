#!/usr/bin/env python3
"""
post_completion_translate_hook.py — 子任务完成后强制主 agent 翻译人话汇报钩子

目标：解决"做完了不汇报"问题，确保 subagent/子任务完成后，主 agent 必须
将技术性完成状态翻译为人类可读的汇报，而不是静默等待。

核心规则：
1. 子任务完成后（completion receipt / subagent_ended），主 agent 必须生成人话汇报
2. 汇报必须包含：结论/证据/动作 三层结构
3. 无汇报则标记为"pending_translation"，触发告警

集成点：
- completion_receipt.py: 创建 receipt 后调用 check
- orchestrator.py: 会话回复前验证
- watchdog.py: 定期巡检 pending 任务

使用示例：
```python
from hooks.post_completion_translate_hook import (
    check_completion_requires_translation,
    enforce_translation,
)

# 检查是否需要翻译汇报
result = check_completion_requires_translation(receipt, session_context)
if result.requires_translation:
    # 强制生成汇报
    translation = enforce_translation(receipt, task_context)
    # 发送给用户
    send_to_user(translation)
```
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

__all__ = [
    "HOOK_VERSION",
    "TranslationStatus",
    "TranslationRequirement",
    "PostCompletionTranslateHook",
    "check_completion_requires_translation",
    "enforce_translation",
    "TRANSLATION_AUDIT_DIR",
]

HOOK_VERSION = "post_completion_translate_v1"

TranslationStatus = Literal[
    "translation_provided",      # 已提供翻译汇报
    "pending_translation",       # 等待翻译
    "translation_blocked",       # 翻译被拦截（质量不达标）
    "translation_error",         # 翻译过程出错
]

# Audit 日志目录
TRANSLATION_AUDIT_DIR = Path(
    os.environ.get(
        "OPENCLAW_TRANSLATION_AUDIT_DIR",
        Path.home() / ".openclaw" / "shared-context" / "translation_audits",
    )
)


def _ensure_audit_dir() -> None:
    """确保 audit 目录存在"""
    TRANSLATION_AUDIT_DIR.mkdir(parents=True, exist_ok=True)


def _iso_now() -> str:
    """返回当前 ISO-8601 时间戳"""
    return datetime.now().isoformat()


def _generate_audit_id() -> str:
    """生成 stable audit ID"""
    import uuid
    return f"translation_audit_{uuid.uuid4().hex[:12]}"


@dataclass
class TranslationRequirement:
    """
    翻译需求评估结果
    
    核心字段：
    - requires_translation: 是否需要翻译汇报
    - reason: 原因/规则 ID
    - confidence: 置信度 (0-100)
    - required_sections: 必需的汇报章节
    - blocking_reasons: 阻止汇报的因素
    """
    requires_translation: bool
    reason: str
    confidence: int = 100
    required_sections: List[str] = field(default_factory=list)
    blocking_reasons: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "requires_translation": self.requires_translation,
            "reason": self.reason,
            "confidence": self.confidence,
            "required_sections": self.required_sections,
            "blocking_reasons": self.blocking_reasons,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TranslationRequirement":
        return cls(
            requires_translation=data.get("requires_translation", False),
            reason=data.get("reason", ""),
            confidence=data.get("confidence", 100),
            required_sections=data.get("required_sections", []),
            blocking_reasons=data.get("blocking_reasons", []),
            metadata=data.get("metadata", {}),
        )


@dataclass
class PostCompletionTranslateHook:
    """
    子任务完成翻译钩子
    
    核心方法：
    - check(): 检查是否需要翻译汇报
    - enforce(): 强制生成汇报
    - validate(): 验证汇报质量
    - audit(): 记录审计日志
    """
    
    # 必需的汇报章节
    REQUIRED_SECTIONS = ["结论", "证据", "动作"]
    
    # 触发翻译的场景白名单
    TRANSLATION_REQUIRED_SCENARIOS = [
        "trading_roundtable",
        "channel_roundtable",
        "coding_issue",
        "workflow_dag",
    ]
    
    # 触发翻译的任务标签关键词
    TRANSLATION_TRIGGER_KEYWORDS = [
        "fix",
        "implement",
        "feature",
        "bug",
        "issue",
        "task",
        "batch",
        "phase",
    ]
    
    def check(
        self,
        completion_receipt: Optional[Dict[str, Any]] = None,
        task_context: Optional[Dict[str, Any]] = None,
        session_context: Optional[Dict[str, Any]] = None,
    ) -> TranslationRequirement:
        """
        检查子任务完成后是否需要翻译汇报
        
        Args:
            completion_receipt: Completion receipt artifact
            task_context: 任务上下文（scenario/label/owner 等）
            session_context: 会话上下文（用户消息/历史等）
        
        Returns:
            TranslationRequirement 评估结果
        """
        required_sections = self.REQUIRED_SECTIONS[:]
        blocking_reasons: List[str] = []
        
        # Check 1: 是否有 completion receipt
        has_receipt = completion_receipt is not None
        if not has_receipt:
            return TranslationRequirement(
                requires_translation=False,
                reason="no_completion_receipt",
                confidence=100,
                blocking_reasons=["Missing completion receipt"],
            )
        
        # Check 2: receipt 状态是否为 completed
        receipt_status = completion_receipt.get("receipt_status", "")
        if receipt_status not in ["completed", "failed"]:
            return TranslationRequirement(
                requires_translation=False,
                reason="receipt_not_terminal",
                confidence=90,
                blocking_reasons=[f"Receipt status is '{receipt_status}', not terminal"],
            )
        
        # Check 3: 场景是否在白名单
        scenario = (task_context or {}).get("scenario", "")
        scenario_ok = scenario in self.TRANSLATION_REQUIRED_SCENARIOS or scenario == ""
        if not scenario_ok:
            return TranslationRequirement(
                requires_translation=False,
                reason="scenario_not_in_allowlist",
                confidence=80,
                blocking_reasons=[f"Scenario '{scenario}' not in translation allowlist"],
            )
        
        # Check 4: 任务标签是否包含触发关键词
        label = (task_context or {}).get("label", "")
        has_trigger_keyword = any(kw in label.lower() for kw in self.TRANSLATION_TRIGGER_KEYWORDS)
        
        # Check 5: 是否已有翻译汇报
        has_translation = completion_receipt.get("human_translation", "") != ""
        if has_translation:
            return TranslationRequirement(
                requires_translation=False,
                reason="translation_already_provided",
                confidence=100,
                metadata={"translation_length": len(completion_receipt.get("human_translation", ""))},
            )
        
        # Check 6: receipt 是否有 result_summary
        has_summary = completion_receipt.get("result_summary", "") != ""
        
        # 综合判断
        requires_translation = (
            has_receipt and
            receipt_status in ["completed", "failed"] and
            not has_translation
        )
        
        reason = "completion_without_translation" if requires_translation else "no_translation_needed"
        confidence = 95 if requires_translation else 70
        
        if requires_translation:
            required_sections = self.REQUIRED_SECTIONS[:]
            if not has_summary:
                blocking_reasons.append("Missing result_summary in receipt")
        
        return TranslationRequirement(
            requires_translation=requires_translation,
            reason=reason,
            confidence=confidence,
            required_sections=required_sections,
            blocking_reasons=blocking_reasons,
            metadata={
                "receipt_status": receipt_status,
                "scenario": scenario,
                "label": label,
                "has_summary": has_summary,
            },
        )
    
    def enforce(
        self,
        completion_receipt: Dict[str, Any],
        task_context: Dict[str, Any],
        template: Optional[str] = None,
        enforce_mode_override: Optional[str] = None,
    ) -> str:
        """
        强制生成翻译汇报
        
        Args:
            completion_receipt: Completion receipt artifact
            task_context: 任务上下文
            template: 可选的汇报模板
            enforce_mode_override: 可选的 enforce mode 覆盖（"audit"/"warn"/"enforce"）
        
        Returns:
            人话汇报文本
        
        Raises:
            HookViolationError: enforce 模式下无法生成翻译时抛出
        """
        # 导入配置和异常模块（延迟导入，避免循环依赖）
        from .hook_config import get_hook_enforce_mode
        from .hook_exceptions import HookViolationError
        
        # 获取 enforce mode（支持覆盖）
        mode = enforce_mode_override if enforce_mode_override in ["audit", "warn", "enforce"] else get_hook_enforce_mode("post_completion_translate")
        
        # 先检查是否需要翻译
        requirement = self.check(completion_receipt, task_context)
        
        if not requirement.requires_translation:
            # 不需要翻译，直接返回空
            return ""
        
        # 尝试生成翻译
        translation = self._generate_translation_safe(completion_receipt, task_context, template)
        
        # 验证翻译质量
        if translation:
            passed, missing = self.validate(translation)
            if not passed:
                # 翻译质量不达标
                if mode == "enforce":
                    raise HookViolationError(
                        f"翻译汇报质量不达标：{missing}",
                        hook_name="post_completion_translate",
                        metadata={
                            "receipt_id": completion_receipt.get("receipt_id", ""),
                            "task_id": task_context.get("task_id", ""),
                            "missing_sections": missing,
                        },
                    )
                elif mode == "warn":
                    import warnings
                    warnings.warn(f"⚠️ 翻译质量不达标 [{task_context.get('task_id', '')}]: {missing}")
                # mode == "audit": 只记录审计日志（现有行为）
        
        # 如果无法生成翻译
        if not translation:
            if mode == "enforce":
                raise HookViolationError(
                    "完成汇报必须包含翻译，但无法生成",
                    hook_name="post_completion_translate",
                    metadata={
                        "receipt_id": completion_receipt.get("receipt_id", ""),
                        "task_id": task_context.get("task_id", ""),
                        "reason": requirement.reason,
                    },
                )
            elif mode == "warn":
                import warnings
                task_id = task_context.get("task_id", "unknown")
                warnings.warn(f"⚠️ 缺少翻译汇报 [{task_id}]: {requirement.reason}")
            # mode == "audit": 只记录审计日志（现有行为）
        
        return translation
    
    def _generate_translation_safe(
        self,
        completion_receipt: Dict[str, Any],
        task_context: Dict[str, Any],
        template: Optional[str] = None,
    ) -> str:
        """
        安全生成翻译汇报（不抛异常）
        
        Args:
            completion_receipt: Completion receipt artifact
            task_context: 任务上下文
            template: 可选的汇报模板
        
        Returns:
            人话汇报文本（可能为空）
        """
        try:
            return self._generate_translation(completion_receipt, task_context, template)
        except Exception:
            # 捕获所有异常，返回空字符串
            return ""
    
    def _generate_translation(
        self,
        completion_receipt: Dict[str, Any],
        task_context: Dict[str, Any],
        template: Optional[str] = None,
    ) -> str:
        """
        生成翻译汇报（内部实现）
        
        Args:
            completion_receipt: Completion receipt artifact
            task_context: 任务上下文
            template: 可选的汇报模板
        
        Returns:
            人话汇报文本
        """
        # 提取关键信息
        receipt_id = completion_receipt.get("receipt_id", "unknown")
        receipt_status = completion_receipt.get("receipt_status", "unknown")
        result_summary = completion_receipt.get("result_summary", "无摘要")
        receipt_reason = completion_receipt.get("receipt_reason", "")
        
        scenario = task_context.get("scenario", "custom")
        label = task_context.get("label", "unnamed")
        task_id = task_context.get("task_id", "unknown")
        
        # 使用默认模板或自定义模板
        if template is None:
            template = self._default_template()
        
        # 生成汇报
        translation = template.format(
            task_id=task_id,
            label=label,
            scenario=scenario,
            status=self._status_to_chinese(receipt_status),
            summary=result_summary,
            reason=receipt_reason,
            timestamp=_iso_now(),
            receipt_id=receipt_id,
        )
        
        return translation
    
    def validate(
        self,
        translation: str,
        required_sections: Optional[List[str]] = None,
    ) -> tuple[bool, List[str]]:
        """
        验证翻译汇报质量
        
        Args:
            translation: 翻译汇报文本
            required_sections: 必需的章节列表
        
        Returns:
            (是否通过，缺失的章节列表)
        """
        sections = required_sections or self.REQUIRED_SECTIONS
        missing_sections: List[str] = []
        
        for section in sections:
            # 检查章节标题是否存在
            if section not in translation:
                missing_sections.append(section)
        
        # 检查最小长度（至少 50 字符）
        if len(translation.strip()) < 50:
            missing_sections.append("内容过短（至少 50 字符）")
        
        passed = len(missing_sections) == 0
        return passed, missing_sections
    
    def audit(
        self,
        receipt_id: str,
        requirement: TranslationRequirement,
        translation: Optional[str] = None,
        validation_result: Optional[tuple[bool, List[str]]] = None,
    ) -> Path:
        """
        记录审计日志
        
        Args:
            receipt_id: Receipt ID
            requirement: 翻译需求评估结果
            translation: 翻译汇报文本（可选）
            validation_result: 验证结果（可选）
        
        Returns:
            审计日志文件路径
        """
        _ensure_audit_dir()
        
        audit_id = _generate_audit_id()
        timestamp = _iso_now()
        
        audit_record = {
            "audit_id": audit_id,
            "timestamp": timestamp,
            "receipt_id": receipt_id,
            "requirement": requirement.to_dict(),
            "translation_provided": translation is not None,
            "translation_length": len(translation) if translation else 0,
            "validation_passed": validation_result[0] if validation_result else None,
            "validation_missing": validation_result[1] if validation_result else None,
        }
        
        # 原子写入
        audit_file = TRANSLATION_AUDIT_DIR / f"{audit_id}.json"
        tmp_file = audit_file.with_suffix(".tmp")
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(audit_record, f, indent=2, ensure_ascii=False)
        tmp_file.replace(audit_file)
        
        return audit_file
    
    def _default_template(self) -> str:
        """返回默认汇报模板"""
        return """## 任务完成汇报

**任务 ID**: {task_id}
**标签**: {label}
**场景**: {scenario}
**状态**: {status}
**时间**: {timestamp}

---

### 结论

{summary}

### 证据

- Receipt 状态：{status}
- Receipt 原因：{reason}

### 动作

- 任务已完成，等待下一步指示
- 查看详细 receipt: {receipt_id}
""".strip()
    
    def _status_to_chinese(self, status: str) -> str:
        """将 receipt 状态翻译为中文"""
        status_map = {
            "completed": "✅ 已完成",
            "failed": "❌ 失败",
            "missing": "⚠️ 丢失",
            "unknown": "❓ 未知",
        }
        return status_map.get(status, status)


# 便捷函数

def check_completion_requires_translation(
    completion_receipt: Optional[Dict[str, Any]] = None,
    task_context: Optional[Dict[str, Any]] = None,
    session_context: Optional[Dict[str, Any]] = None,
) -> TranslationRequirement:
    """
    检查子任务完成后是否需要翻译汇报
    
    Args:
        completion_receipt: Completion receipt artifact
        task_context: 任务上下文
        session_context: 会话上下文
    
    Returns:
        TranslationRequirement 评估结果
    """
    hook = PostCompletionTranslateHook()
    return hook.check(completion_receipt, task_context, session_context)


def enforce_translation(
    completion_receipt: Dict[str, Any],
    task_context: Dict[str, Any],
    template: Optional[str] = None,
) -> str:
    """
    强制生成翻译汇报
    
    Args:
        completion_receipt: Completion receipt artifact
        task_context: 任务上下文
        template: 可选的汇报模板
    
    Returns:
        人话汇报文本
    """
    hook = PostCompletionTranslateHook()
    return hook.enforce(completion_receipt, task_context, template)


def log_translation_audit(
    receipt_id: str,
    requirement: TranslationRequirement,
    translation: Optional[str] = None,
) -> Path:
    """
    记录翻译审计日志
    
    Args:
        receipt_id: Receipt ID
        requirement: 翻译需求评估结果
        translation: 翻译汇报文本
    
    Returns:
        审计日志文件路径
    """
    hook = PostCompletionTranslateHook()
    return hook.audit(receipt_id, requirement, translation)
