#!/usr/bin/env python3
"""
partial_continuation.py — Universal Partial-Completion Continuation Framework (v1)

目标：提供通用的 partial closeout / auto-replan / next-task registration 能力，
不绑定到任何特定场景（trading/channel 等），作为通用 kernel 供各场景 plug-in 使用。

核心概念：
- partial closeout contract: 描述任务部分完成后的状态（completed_scope / remaining_scope / stop_reason）
- auto-replan helper: 基于 remaining_scope 自动生成 next task candidates
- next-task registration draft: 生成结构化的 next task registration payload

这是通用能力，不是 trading 私货。trading/channel 等场景可以 later plug-in 使用。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional
from datetime import datetime

__all__ = [
    "StopReason",
    "DispatchReadiness",
    "PartialCloseoutContract",
    "NextTaskCandidate",
    "NextTaskRegistrationPayload",
    "build_partial_closeout",
    "auto_replan",
    "build_next_task_registration",
    "PARTIAL_CLOSEOUT_VERSION",
]

PARTIAL_CLOSEOUT_VERSION = "partial_closeout_v1"

StopReason = Literal[
    "completed_all",
    "partial_completed",
    "blocked",
    "timeout",
    "failed",
    "gate_held",
    "manual_stop",
    "scope_change",
]

DispatchReadiness = Literal[
    "ready",
    "needs_review",
    "blocked",
    "not_applicable",
]


@dataclass
class ScopeItem:
    """
    描述一个工作项的范围。
    
    用于 completed_scope 和 remaining_scope。
    """
    item_id: str
    description: str
    status: Literal["completed", "partial", "not_started", "blocked"] = "not_started"
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "item_id": self.item_id,
            "description": self.description,
            "status": self.status,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScopeItem":
        return cls(
            item_id=data.get("item_id", ""),
            description=data.get("description", ""),
            status=data.get("status", "not_started"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class PartialCloseoutContract:
    """
    Partial closeout contract — 描述任务部分完成后的状态。
    
    核心字段：
    - completed_scope: 已完成的工作范围
    - remaining_scope: 剩余的工作范围
    - stop_reason: 停止原因
    - dispatch_readiness: 是否准备好 dispatch 下一跳
    - next_candidates: 自动生成的 next task candidates
    
    这是通用 contract，不绑定任何特定场景。
    """
    completed_scope: List[ScopeItem] = field(default_factory=list)
    remaining_scope: List[ScopeItem] = field(default_factory=list)
    stop_reason: StopReason = "completed_all"
    dispatch_readiness: DispatchReadiness = "not_applicable"
    next_candidates: List[Dict[str, Any]] = field(default_factory=list)
    original_task_id: Optional[str] = None
    original_batch_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def has_remaining_work(self) -> bool:
        """是否有剩余工作"""
        return len(self.remaining_scope) > 0
    
    def is_fully_completed(self) -> bool:
        """是否全部完成"""
        return (
            len(self.remaining_scope) == 0 and
            self.stop_reason == "completed_all"
        )
    
    def should_generate_next_registration(self) -> bool:
        """
        是否应该生成 next task registration。
        
        规则：
        - 有 remaining_scope 且 dispatch_readiness != "blocked" 时生成
        - 全部完成时不生成
        """
        if self.is_fully_completed():
            return False
        if not self.has_remaining_work():
            return False
        if self.dispatch_readiness == "blocked":
            return False
        return True
    
    def validate(self) -> tuple[bool, List[str]]:
        """
        验证 contract 是否符合规则。
        
        返回：(is_valid, errors)
        """
        errors: List[str] = []
        
        # 规则 1: stop_reason 必须与 completed_scope/remaining_scope 一致
        if self.stop_reason == "completed_all" and self.has_remaining_work():
            errors.append(
                f"Inconsistent: stop_reason='completed_all' but has {len(self.remaining_scope)} remaining items"
            )
        
        # 规则 2: 如果没有 completed_scope 且没有 remaining_scope，stop_reason 应该是 completed_all 或 manual_stop
        if not self.completed_scope and not self.remaining_scope:
            if self.stop_reason not in ("completed_all", "manual_stop"):
                errors.append(
                    f"Inconsistent: empty scopes but stop_reason={self.stop_reason!r}"
                )
        
        # 规则 3: dispatch_readiness 必须与 stop_reason 一致
        if self.stop_reason in ("blocked", "failed", "gate_held"):
            if self.dispatch_readiness == "ready":
                errors.append(
                    f"Inconsistent: stop_reason={self.stop_reason!r} but dispatch_readiness='ready'"
                )
        
        # 规则 4: next_candidates 应该与 remaining_scope 对应
        if self.next_candidates and not self.remaining_scope:
            # 这是一个警告，不是错误：有时 next_candidates 可能是全新的工作，不是 remaining_scope 的直接映射
            pass
        
        return len(errors) == 0, errors
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "contract_version": PARTIAL_CLOSEOUT_VERSION,
            "completed_scope": [item.to_dict() for item in self.completed_scope],
            "remaining_scope": [item.to_dict() for item in self.remaining_scope],
            "stop_reason": self.stop_reason,
            "dispatch_readiness": self.dispatch_readiness,
            "next_candidates": self.next_candidates,
            "original_task_id": self.original_task_id,
            "original_batch_id": self.original_batch_id,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PartialCloseoutContract":
        return cls(
            completed_scope=[
                ScopeItem.from_dict(item) for item in data.get("completed_scope", [])
            ],
            remaining_scope=[
                ScopeItem.from_dict(item) for item in data.get("remaining_scope", [])
            ],
            stop_reason=data.get("stop_reason", "completed_all"),
            dispatch_readiness=data.get("dispatch_readiness", "not_applicable"),
            next_candidates=data.get("next_candidates", []),
            original_task_id=data.get("original_task_id"),
            original_batch_id=data.get("original_batch_id"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class NextTaskCandidate:
    """
    Next task candidate — 自动生成的下一跳任务候选。
    
    由 auto-replan 基于 remaining_scope 生成。
    """
    candidate_id: str
    title: str
    description: str
    priority: int = 1  # 1 = highest
    estimated_scope: str = "single_step"  # single_step | multi_step | unknown
    dependencies: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "title": self.title,
            "description": self.description,
            "priority": self.priority,
            "estimated_scope": self.estimated_scope,
            "dependencies": self.dependencies,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NextTaskCandidate":
        return cls(
            candidate_id=data.get("candidate_id", ""),
            title=data.get("title", ""),
            description=data.get("description", ""),
            priority=data.get("priority", 1),
            estimated_scope=data.get("estimated_scope", "single_step"),
            dependencies=data.get("dependencies", []),
            metadata=data.get("metadata", {}),
        )


@dataclass
class NextTaskRegistrationPayload:
    """
    Next task registration payload — 用于注册新任务的结构化 payload。
    
    这是 canonical artifact，operator/main 可以继续消费。
    当前版本不直接写入 state machine，但提供完整可用的结构。
    """
    registration_id: str
    source_closeout: Dict[str, Any]  # PartialCloseoutContract.to_dict()
    candidate: Dict[str, Any]  # NextTaskCandidate.to_dict()
    proposed_task: Dict[str, Any]
    requires_manual_approval: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "registration_version": "next_task_registration_v1",
            "registration_id": self.registration_id,
            "source_closeout": self.source_closeout,
            "candidate": self.candidate,
            "proposed_task": self.proposed_task,
            "requires_manual_approval": self.requires_manual_approval,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NextTaskRegistrationPayload":
        return cls(
            registration_id=data.get("registration_id", ""),
            source_closeout=data.get("source_closeout", {}),
            candidate=data.get("candidate", {}),
            proposed_task=data.get("proposed_task", {}),
            requires_manual_approval=data.get("requires_manual_approval", True),
            metadata=data.get("metadata", {}),
        )


def _iso_now() -> str:
    """返回当前 ISO-8601 时间戳"""
    return datetime.now().isoformat()


def _generate_id(prefix: str) -> str:
    """生成 ID"""
    import uuid
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def build_partial_closeout(
    *,
    completed_scope: Optional[List[Dict[str, Any]]] = None,
    remaining_scope: Optional[List[Dict[str, Any]]] = None,
    stop_reason: StopReason = "completed_all",
    dispatch_readiness: DispatchReadiness = "not_applicable",
    original_task_id: Optional[str] = None,
    original_batch_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> PartialCloseoutContract:
    """
    构建一个 partial closeout contract。
    
    参数：
    - completed_scope: 已完成的工作项列表，每项包含 {item_id, description, status, metadata} 或 ScopeItem
    - remaining_scope: 剩余的工作项列表
    - stop_reason: 停止原因
    - dispatch_readiness: 是否准备好 dispatch
    - original_task_id: 原始任务 ID（可选）
    - original_batch_id: 原始 batch ID（可选）
    - metadata: 额外元数据
    
    返回：PartialCloseoutContract
    """
    def _to_scope_item(item, default_status: str) -> ScopeItem:
        """Convert dict or ScopeItem to ScopeItem"""
        if isinstance(item, ScopeItem):
            return item
        return ScopeItem(
            item_id=item.get("item_id", _generate_id("scope")),
            description=item.get("description", ""),
            status=item.get("status", default_status),
            metadata=item.get("metadata", {}),
        )
    
    completed = [_to_scope_item(item, "completed") for item in (completed_scope or [])]
    remaining = [_to_scope_item(item, "not_started") for item in (remaining_scope or [])]
    
    # 自动推导 dispatch_readiness
    resolved_readiness = dispatch_readiness
    if resolved_readiness == "not_applicable":
        if stop_reason == "completed_all":
            resolved_readiness = "not_applicable"
        elif stop_reason in ("blocked", "failed", "gate_held"):
            resolved_readiness = "blocked"
        elif remaining and stop_reason == "partial_completed":
            resolved_readiness = "needs_review"
        else:
            resolved_readiness = "ready"
    
    contract = PartialCloseoutContract(
        completed_scope=completed,
        remaining_scope=remaining,
        stop_reason=stop_reason,
        dispatch_readiness=resolved_readiness,
        original_task_id=original_task_id,
        original_batch_id=original_batch_id,
        metadata=metadata or {},
    )
    
    is_valid, errors = contract.validate()
    if not is_valid:
        # 记录警告但不阻止返回
        contract.metadata["validation_warnings"] = errors
    
    return contract


def auto_replan(
    closeout: PartialCloseoutContract,
    *,
    max_candidates: int = 3,
    context: Optional[Dict[str, Any]] = None,
) -> List[NextTaskCandidate]:
    """
    基于 partial closeout contract 自动生成 next task candidates。
    
    这是 auto-replan helper 的核心逻辑。
    
    参数：
    - closeout: partial closeout contract
    - max_candidates: 最多生成的 candidate 数量
    - context: 额外上下文（可选），可包含场景特定信息
    
    返回：NextTaskCandidate 列表
    """
    if not closeout.has_remaining_work():
        return []
    
    candidates: List[NextTaskCandidate] = []
    context = context or {}
    
    # 策略：按 remaining_scope 的顺序生成 candidates
    # 每个 remaining_scope item 可以映射到一个 candidate
    for i, scope_item in enumerate(closeout.remaining_scope[:max_candidates]):
        candidate_id = _generate_id("cand")
        
        # 从 scope item 推导 candidate
        title = scope_item.description[:50] + ("..." if len(scope_item.description) > 50 else "")
        description = scope_item.description
        
        # 根据 status 调整 priority
        priority = 1
        if scope_item.status == "blocked":
            priority = 2  # blocked 的任务优先级稍低，需要先解决 blocker
        elif scope_item.status == "partial":
            priority = 1  # partial 完成的任务优先级最高
        
        # 从 metadata 中提取依赖
        dependencies = scope_item.metadata.get("dependencies", [])
        
        candidate = NextTaskCandidate(
            candidate_id=candidate_id,
            title=title,
            description=description,
            priority=priority,
            estimated_scope="single_step",  # 默认假设是单步任务
            dependencies=dependencies,
            metadata={
                "source_scope_item_id": scope_item.item_id,
                "source_scope_status": scope_item.status,
                "closeout_stop_reason": closeout.stop_reason,
                "generated_at": _iso_now(),
                **context,
            },
        )
        
        candidates.append(candidate)
    
    # 按优先级排序
    candidates.sort(key=lambda c: c.priority)
    
    return candidates


def build_next_task_registration(
    *,
    closeout: PartialCloseoutContract,
    candidate: NextTaskCandidate,
    adapter: Optional[str] = None,
    scenario: Optional[str] = None,
    requires_manual_approval: bool = True,
    metadata: Optional[Dict[str, Any]] = None,
) -> NextTaskRegistrationPayload:
    """
    构建 next task registration payload。
    
    这是 canonical artifact，operator/main 可以继续消费。
    
    参数：
    - closeout: partial closeout contract（来源）
    - candidate: next task candidate
    - adapter: 场景 adapter（可选），如 "trading_roundtable" / "channel_roundtable"
    - scenario: 场景名称（可选）
    - requires_manual_approval: 是否需要人工审批（默认 True）
    - metadata: 额外元数据
    
    返回：NextTaskRegistrationPayload
    """
    registration_id = _generate_id("reg")
    
    # 构建 proposed task
    proposed_task = {
        "task_type": "continuation",
        "title": candidate.title,
        "description": candidate.description,
        "priority": candidate.priority,
        "dependencies": candidate.dependencies,
        "estimated_scope": candidate.estimated_scope,
        "source": {
            "closeout_registration_id": registration_id,
            "candidate_id": candidate.candidate_id,
            "original_task_id": closeout.original_task_id,
            "original_batch_id": closeout.original_batch_id,
        },
        "context": {
            "adapter": adapter,
            "scenario": scenario,
            "stop_reason": closeout.stop_reason,
            "dispatch_readiness": closeout.dispatch_readiness,
        },
        "payload": {
            # 这里可以填充场景特定的 payload
            # 例如 trading_roundtable 可以填充 packet/roundtable 信息
            **candidate.metadata,
        },
    }
    
    return NextTaskRegistrationPayload(
        registration_id=registration_id,
        source_closeout=closeout.to_dict(),
        candidate=candidate.to_dict(),
        proposed_task=proposed_task,
        requires_manual_approval=requires_manual_approval,
        metadata=metadata or {},
    )


def generate_next_registrations_for_closeout(
    closeout: PartialCloseoutContract,
    *,
    adapter: Optional[str] = None,
    scenario: Optional[str] = None,
    max_candidates: int = 3,
    context: Optional[Dict[str, Any]] = None,
) -> List[NextTaskRegistrationPayload]:
    """
    为一个 partial closeout contract 生成所有 next task registrations。
    
    这是 convenience function，组合了 auto_replan + build_next_task_registration。
    
    参数：
    - closeout: partial closeout contract
    - adapter: 场景 adapter（可选）
    - scenario: 场景名称（可选）
    - max_candidates: 最多生成的 candidate 数量
    - context: 额外上下文
    
    返回：NextTaskRegistrationPayload 列表
    """
    if not closeout.should_generate_next_registration():
        return []
    
    candidates = auto_replan(closeout, max_candidates=max_candidates, context=context)
    
    registrations = []
    for candidate in candidates:
        registration = build_next_task_registration(
            closeout=closeout,
            candidate=candidate,
            adapter=adapter,
            scenario=scenario,
            requires_manual_approval=(closeout.dispatch_readiness != "ready"),
            metadata={
                "auto_generated": True,
                "generation_timestamp": _iso_now(),
            },
        )
        registrations.append(registration)
    
    return registrations


# ============ 场景适配 helper ============

def adapt_closeout_for_trading(
    closeout: PartialCloseoutContract,
    *,
    packet: Optional[Dict[str, Any]] = None,
    roundtable: Optional[Dict[str, Any]] = None,
) -> PartialCloseoutContract:
    """
    为 trading_roundtable 场景适配 closeout contract。
    
    这是场景特定的 helper，把通用 contract 与 trading 特定信息结合。
    """
    closeout.metadata["adapter"] = "trading_roundtable"
    if packet:
        closeout.metadata["trading_packet"] = packet
    if roundtable:
        closeout.metadata["trading_roundtable"] = roundtable
    
    # 根据 trading 特定逻辑调整 dispatch_readiness
    if roundtable:
        conclusion = str(roundtable.get("conclusion") or "").upper()
        blocker = str(roundtable.get("blocker") or "").lower()
        
        if conclusion == "PASS" and blocker == "none":
            closeout.dispatch_readiness = "ready"
        elif conclusion == "CONDITIONAL":
            closeout.dispatch_readiness = "needs_review"
        elif conclusion == "FAIL" or blocker != "none":
            closeout.dispatch_readiness = "blocked"
    
    return closeout


def adapt_closeout_for_channel(
    closeout: PartialCloseoutContract,
    *,
    channel_packet: Optional[Dict[str, Any]] = None,
    roundtable: Optional[Dict[str, Any]] = None,
) -> PartialCloseoutContract:
    """
    为 channel_roundtable 场景适配 closeout contract。
    
    这是场景特定的 helper，把通用 contract 与 channel 特定信息结合。
    """
    closeout.metadata["adapter"] = "channel_roundtable"
    if channel_packet:
        closeout.metadata["channel_packet"] = channel_packet
    if roundtable:
        closeout.metadata["channel_roundtable"] = roundtable
    
    # 根据 channel 特定逻辑调整 dispatch_readiness
    if roundtable:
        conclusion = str(roundtable.get("conclusion") or "").upper()
        blocker = str(roundtable.get("blocker") or "").lower()
        
        if conclusion == "PASS" and blocker == "none":
            closeout.dispatch_readiness = "ready"
        elif conclusion == "CONDITIONAL":
            closeout.dispatch_readiness = "needs_review"
        elif conclusion == "FAIL" or blocker != "none":
            closeout.dispatch_readiness = "blocked"
    
    return closeout
