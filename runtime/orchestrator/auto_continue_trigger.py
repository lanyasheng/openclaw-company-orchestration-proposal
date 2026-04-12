#!/usr/bin/env python3
"""
auto_continue_trigger.py — Auto-Continue Trigger (Minimal Implementation)

目标：实现最小自动续批触发器，基于真值条件决定是否允许自动续批。

核心规则：
1. 只有在满足真值条件时才允许自动续批：
   - validator accepted / 或明确可接受状态
   - 测试通过 / 或有明确 gate 报告
   - 无 single-writer 冲突
2. 输出明确决策：
   - `continue_allowed`: 允许自动续批
   - `continue_blocked`: 阻止自动续批（有冲突/失败）
   - `gate_required`: 需要人工审查

这是 P0-4 Auto-Continue Trigger 的核心实现，依赖：
- completion_validator.py (validator 结果)
- completion_receipt.py (receipt status)
- single_writer_guard.py (writer 冲突检查)

设计原则：
1. 默认安全（auto_continue=false，除非显式检查通过）
2. 真值驱动（基于 artifact 状态，不是口头承诺）
3. 最小接线（不重写整个 orchestration）
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from completion_validator import (
    CompletionValidationResult,
    load_validation_audit,
    list_validation_audits,
    VALIDATOR_AUDIT_DIR,
)
from completion_receipt import (
    CompletionReceiptArtifact,
    ReceiptStatus,
    get_completion_receipt,
    list_completion_receipts,
)

__all__ = [
    "ContinueDecision",
    "AutoContinueDecision",
    "AutoContinueTrigger",
    "evaluate_auto_continue",
    "AUTO_CONTINUE_TRIGGER_VERSION",
]

AUTO_CONTINUE_TRIGGER_VERSION = "auto_continue_trigger_v1"

ContinueDecision = Literal["continue_allowed", "continue_blocked", "gate_required"]


@dataclass
class AutoContinueDecision:
    """
    Auto-continue decision — 自动续批决策结果。
    
    核心字段：
    - decision: 决策结果 (continue_allowed / continue_blocked / gate_required)
    - reason: 决策原因
    - source_receipt_id: 来源 receipt ID
    - source_validation_audit_id: 来源 validation audit ID
    - validator_status: validator 状态
    - receipt_status: receipt 状态
    - writer_conflict: 是否有 writer 冲突
    - gate_report: gate 报告（如果有）
    - metadata: 额外元数据
    """
    decision: ContinueDecision
    reason: str
    source_receipt_id: str = ""
    source_validation_audit_id: str = ""
    validator_status: str = ""
    receipt_status: str = ""
    writer_conflict: bool = False
    gate_report: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "trigger_version": AUTO_CONTINUE_TRIGGER_VERSION,
            "decision": self.decision,
            "reason": self.reason,
            "source_receipt_id": self.source_receipt_id,
            "source_validation_audit_id": self.source_validation_audit_id,
            "validator_status": self.validator_status,
            "receipt_status": self.receipt_status,
            "writer_conflict": self.writer_conflict,
            "gate_report": self.gate_report,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AutoContinueDecision":
        return cls(
            decision=data.get("decision", "gate_required"),
            reason=data.get("reason", ""),
            source_receipt_id=data.get("source_receipt_id", ""),
            source_validation_audit_id=data.get("source_validation_audit_id", ""),
            validator_status=data.get("validator_status", ""),
            receipt_status=data.get("receipt_status", ""),
            writer_conflict=data.get("writer_conflict", False),
            gate_report=data.get("gate_report"),
            metadata=data.get("metadata", {}),
        )


class AutoContinueTrigger:
    """
    Auto-Continue Trigger — 评估是否允许自动续批。
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self._writer_guard = None
    
    def _get_writer_guard(self):
        """Lazy import writer guard to avoid circular dependency"""
        if self._writer_guard is None:
            try:
                from single_writer_guard import SingleWriterGuard
                self._writer_guard = SingleWriterGuard()
            except ImportError:
                self._writer_guard = None
        return self._writer_guard
    
    def _get_latest_validator_result(self, receipt: CompletionReceiptArtifact) -> tuple[str, str, str]:
        """
        从 validator audit 目录获取最新的验证结果。
        
        Returns:
            (validator_status, audit_id, reason)
        """
        # 尝试从 receipt metadata 获取 audit_id
        metadata = receipt.metadata or {}
        validator_result = metadata.get("validator_result")
        
        if validator_result and isinstance(validator_result, dict):
            status = validator_result.get("status", "unknown")
            audit_id = validator_result.get("audit_id", "")
            reason = validator_result.get("reason", "")
            # 规范化状态
            if status == "accepted":
                status = "accepted_completion"
            return status, audit_id, reason
        
        # 从 audit 目录查找最新的验证记录
        try:
            audits = list_validation_audits(limit=10)
            for audit in audits:
                # 查找与当前 receipt 相关的 audit
                if audit.get("execution_id") == receipt.source_spawn_execution_id:
                    status = audit.get("status", "unknown")
                    if status == "accepted":
                        status = "accepted_completion"
                    return status, audit.get("audit_id", ""), audit.get("reason", "")
        except Exception:
            pass
        
        # 从 receipt_status 推断
        if receipt.receipt_status == "completed":
            return "accepted_completion", "", "inferred_from_receipt_completed"
        elif receipt.receipt_status == "failed":
            return "blocked_completion", "", "inferred_from_receipt_failed"
        
        return "unknown", "", "validator_result_not_found"
    
    def _check_writer_conflict(
        self,
        receipt: CompletionReceiptArtifact,
    ) -> tuple[bool, str]:
        """检查 writer 冲突"""
        writer_guard = self._get_writer_guard()
        
        if writer_guard is None:
            return False, "writer_guard_not_available"
        
        metadata = receipt.metadata or {}
        repo = metadata.get("repo", "")
        batch_id = metadata.get("batch_id", "")
        
        if not repo and not batch_id:
            return False, "no_repo_or_batch_id"
        
        current_writer_id = metadata.get("execution_id", receipt.receipt_id)
        
        has_conflict, reason = writer_guard.check_writer_conflict(
            repo=repo,
            batch_id=batch_id,
            current_writer_id=current_writer_id,
        )
        
        return has_conflict, reason
    
    def _determine_decision(
        self,
        validator_status: str,
        receipt_status: str,
        has_writer_conflict: bool,
    ) -> tuple[ContinueDecision, str]:
        """综合决策"""
        # 优先级 1: writer 冲突
        if has_writer_conflict:
            return "continue_blocked", "writer_conflict_detected"
        
        # 优先级 2: validator blocked
        if validator_status in ("blocked_completion", "blocked"):
            return "continue_blocked", "validator_blocked_completion"
        
        # 优先级 3: receipt failed
        if receipt_status == "failed":
            return "continue_blocked", "receipt_failed"
        
        # 优先级 4: validator gate_required
        if validator_status in ("gate_required", "gate"):
            return "gate_required", "validator_gate_required"
        
        # 优先级 5: validator accepted + receipt completed
        if validator_status in ("accepted_completion", "accepted") and receipt_status == "completed":
            return "continue_allowed", "all_conditions_met"
        
        # 默认：需要 gate
        return "gate_required", "unclear_state_requires_gate"
    
    def _check_rate_limit(self) -> tuple[bool, str]:
        """Check auto-continue rate limit to prevent runaway loops.

        Limits: MAX_PER_HOUR (default 20) and MAX_PER_DAY (default 100).
        Counts recent decisions from the decisions directory.
        """
        max_per_hour = int(os.environ.get("OPENCLAW_MAX_CONTINUE_PER_HOUR", "20"))
        max_per_day = int(os.environ.get("OPENCLAW_MAX_CONTINUE_PER_DAY", "100"))

        from datetime import timedelta
        now = datetime.now(timezone.utc)
        hour_ago = now - timedelta(hours=1)
        day_ago = now - timedelta(days=1)

        hour_count = 0
        day_count = 0
        from completion_receipt import COMPLETION_RECEIPT_DIR
        decisions_dir = COMPLETION_RECEIPT_DIR
        if decisions_dir.is_dir():
            for f in decisions_dir.glob("*.json"):
                try:
                    mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
                    if mtime > day_ago:
                        day_count += 1
                    if mtime > hour_ago:
                        hour_count += 1
                except OSError:
                    pass

        if hour_count >= max_per_hour:
            return True, f"rate_limit_hourly_{hour_count}/{max_per_hour}"
        if day_count >= max_per_day:
            return True, f"rate_limit_daily_{day_count}/{max_per_day}"
        return False, ""

    def evaluate(
        self,
        receipt_id: str,
        receipt: Optional[CompletionReceiptArtifact] = None,
    ) -> AutoContinueDecision:
        """评估自动续批条件"""
        if os.environ.get("DISABLE_AUTO_CONTINUE") == "1":
            return AutoContinueDecision(
                decision="gate_required",
                reason="auto_continue_disabled_by_env",
                source_receipt_id=receipt_id,
            )

        # Rate limit check — prevent runaway continuation loops
        rate_limited, rate_reason = self._check_rate_limit()
        if rate_limited:
            return AutoContinueDecision(
                decision="continue_blocked",
                reason=rate_reason,
                source_receipt_id=receipt_id,
            )
        
        if receipt is None:
            receipt = get_completion_receipt(receipt_id)
        
        if receipt is None:
            return AutoContinueDecision(
                decision="gate_required",
                reason="receipt_not_found",
                source_receipt_id=receipt_id,
            )
        
        # 获取 validator 结果
        validator_status, audit_id, validator_reason = self._get_latest_validator_result(receipt)
        
        # 检查 writer 冲突
        has_writer_conflict, writer_reason = self._check_writer_conflict(receipt)
        
        # 综合决策
        decision, reason = self._determine_decision(
            validator_status=validator_status,
            receipt_status=receipt.receipt_status,
            has_writer_conflict=has_writer_conflict,
        )
        
        return AutoContinueDecision(
            decision=decision,
            reason=reason,
            source_receipt_id=receipt_id,
            source_validation_audit_id=audit_id,
            validator_status=validator_status,
            receipt_status=receipt.receipt_status,
            writer_conflict=has_writer_conflict,
            metadata={
                "validator_reason": validator_reason,
                "receipt_reason": receipt.receipt_reason or "",
                "writer_reason": writer_reason,
            },
        )


def evaluate_auto_continue(
    receipt_id: str,
    receipt: Optional[CompletionReceiptArtifact] = None,
    config: Optional[Dict[str, Any]] = None,
) -> AutoContinueDecision:
    """便捷函数：评估自动续批条件"""
    trigger = AutoContinueTrigger(config=config)
    return trigger.evaluate(receipt_id=receipt_id, receipt=receipt)


def list_auto_continue_decisions(
    limit: int = 100,
    decision_filter: Optional[ContinueDecision] = None,
) -> List[AutoContinueDecision]:
    """列出自动续批决策记录"""
    receipts = list_completion_receipts(limit=limit)
    
    decisions = []
    for receipt_data in receipts:
        receipt_id = receipt_data.get("receipt_id", "")
        if not receipt_id:
            continue
        
        metadata = receipt_data.get("metadata", {})
        auto_continue = metadata.get("auto_continue")
        
        if auto_continue and isinstance(auto_continue, dict):
            decision = AutoContinueDecision.from_dict(auto_continue)
            
            if decision_filter and decision.decision != decision_filter:
                continue
            
            decisions.append(decision)
    
    return decisions
