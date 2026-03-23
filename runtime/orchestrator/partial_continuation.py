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
    "RegistrationStatus",
    "PartialCloseoutContract",
    "NextTaskCandidate",
    "NextTaskRegistrationPayload",
    "NextTaskRegistrationWithStatus",
    "ContinuationContract",
    "build_partial_closeout",
    "auto_replan",
    "build_next_task_registration",
    "generate_next_registrations_for_closeout",
    "generate_registered_registrations_for_closeout",
    "adapt_closeout_for_trading",
    "adapt_closeout_for_channel",
    "build_continuation_contract",
    "extract_continuation_contract",
    "PARTIAL_CLOSEOUT_VERSION",
    "CONTINUATION_CONTRACT_VERSION",
]

PARTIAL_CLOSEOUT_VERSION = "partial_closeout_v1"
CONTINUATION_CONTRACT_VERSION = "continuation_contract_v1"

# ============ Unified Continuation Contract (P0-1 Batch 1) ============
# 统一 continuation contract 的最小核心字段与流转语义
# 让 closeout / callback / task registration / dispatch plan 使用同一套 continuation 语义


@dataclass
class ContinuationContract:
    """
    Unified Continuation Contract — 统一 continuation 语义的最小核心字段。
    
    核心字段：
    - stopped_because: 任务停止原因（机器可读 + 人类可读）
    - next_step: 下一步行动描述（人类可读的行动指南）
    - next_owner: 下一步负责人/角色（如 "main", "trading", "channel"）
    
    这是通用 contract，不绑定任何特定场景。
    用于 closeout / callback / task registration / dispatch plan 的统一 continuation 语义。
    
    设计原则：
    - 最小核心：只包含三个必需字段
    - 向后兼容：不破坏现有 callback payload / receipt
    - 场景可扩展：通过 metadata 支持场景特定字段
    """
    stopped_because: str
    next_step: str
    next_owner: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def validate(self) -> tuple[bool, List[str]]:
        """
        验证 contract 是否符合规则。
        
        返回：(is_valid, errors)
        """
        errors: List[str] = []
        
        # 规则 1: stopped_because 不能为空
        if not self.stopped_because or not self.stopped_because.strip():
            errors.append("stopped_because is required and cannot be empty")
        
        # 规则 2: next_step 不能为空
        if not self.next_step or not self.next_step.strip():
            errors.append("next_step is required and cannot be empty")
        
        # 规则 3: next_owner 不能为空
        if not self.next_owner or not self.next_owner.strip():
            errors.append("next_owner is required and cannot be empty")
        
        return len(errors) == 0, errors
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "contract_version": CONTINUATION_CONTRACT_VERSION,
            "stopped_because": self.stopped_because,
            "next_step": self.next_step,
            "next_owner": self.next_owner,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ContinuationContract":
        return cls(
            stopped_because=data.get("stopped_because", ""),
            next_step=data.get("next_step", ""),
            next_owner=data.get("next_owner", ""),
            metadata=data.get("metadata", {}),
        )
    
    def merge_into_closeout(self, closeout: "PartialCloseoutContract") -> "PartialCloseoutContract":
        """
        将 continuation contract 合并到 partial closeout contract。
        
        这是 convenience method，用于把统一的 continuation 语义注入到 closeout。
        """
        # 合并到 closeout metadata
        closeout.metadata["continuation_contract"] = self.to_dict()
        closeout.metadata["stopped_because"] = self.stopped_because
        closeout.metadata["next_step"] = self.next_step
        closeout.metadata["next_owner"] = self.next_owner
        
        # 如果 closeout 没有 stop_reason，从 stopped_because 推导
        if closeout.stop_reason == "completed_all" and self.stopped_because:
            # 尝试从 stopped_because 映射到 stop_reason
            if "blocked" in self.stopped_because.lower():
                closeout.stop_reason = "blocked"
            elif "failed" in self.stopped_because.lower():
                closeout.stop_reason = "failed"
            elif "partial" in self.stopped_because.lower():
                closeout.stop_reason = "partial_completed"
        
        return closeout
    
    @classmethod
    def from_closeout(cls, closeout: "PartialCloseoutContract") -> "ContinuationContract":
        """
        从 partial closeout contract 提取 continuation contract。
        
        这是 convenience method，用于从 closeout 中提取统一的 continuation 语义。
        """
        # 优先从 metadata 中提取
        stopped_because = (
            closeout.metadata.get("stopped_because") or
            closeout.metadata.get("stop_reason") or
            closeout.stop_reason
        )
        
        next_step = closeout.metadata.get("next_step", "")
        if not next_step and closeout.remaining_scope:
            # 从 remaining_scope 推导 next_step
            next_step = closeout.remaining_scope[0].description
        
        next_owner = closeout.metadata.get("next_owner", "main")
        
        return cls(
            stopped_because=str(stopped_because),
            next_step=str(next_step),
            next_owner=str(next_owner),
            metadata={
                "source": "partial_closeout",
                "original_stop_reason": closeout.stop_reason,
                "has_remaining_work": closeout.has_remaining_work(),
                "dispatch_readiness": closeout.dispatch_readiness,
            },
        )


def build_continuation_contract(
    *,
    stopped_because: str,
    next_step: str,
    next_owner: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> ContinuationContract:
    """
    构建一个 continuation contract。
    
    参数：
    - stopped_because: 任务停止原因
    - next_step: 下一步行动描述
    - next_owner: 下一步负责人/角色
    - metadata: 额外元数据
    
    返回：ContinuationContract
    """
    contract = ContinuationContract(
        stopped_because=stopped_because,
        next_step=next_step,
        next_owner=next_owner,
        metadata=metadata or {},
    )
    
    is_valid, errors = contract.validate()
    if not is_valid:
        contract.metadata["validation_warnings"] = errors
    
    return contract


def extract_continuation_contract(
    payload: Dict[str, Any],
    source: str = "unknown",
) -> Optional[ContinuationContract]:
    """
    从 payload 中提取 continuation contract。
    
    支持从多种来源提取：
    - closeout metadata
    - tmux_terminal_receipt
    - callback envelope
    - dispatch plan continuation
    
    参数：
    - payload: 包含 continuation 信息的 payload
    - source: 来源标识（用于调试）
    
    返回：ContinuationContract 或 None
    """
    # 尝试从 closeout metadata 提取
    if isinstance(payload.get("closeout"), dict):
        closeout = payload["closeout"]
        if closeout.get("stopped_because") or closeout.get("next_step") or closeout.get("next_owner"):
            return ContinuationContract(
                stopped_because=closeout.get("stopped_because", ""),
                next_step=closeout.get("next_step", ""),
                next_owner=closeout.get("next_owner", ""),
                metadata={"source": f"closeout:{source}"},
            )
    
    # 尝试从 tmux_terminal_receipt 提取
    if isinstance(payload.get("tmux_terminal_receipt"), dict):
        receipt = payload["tmux_terminal_receipt"]
        if receipt.get("stopped_because") or receipt.get("next_step") or receipt.get("next_owner"):
            return ContinuationContract(
                stopped_because=receipt.get("stopped_because", ""),
                next_step=receipt.get("next_step", ""),
                next_owner=receipt.get("next_owner", ""),
                metadata={"source": f"tmux_receipt:{source}"},
            )
    
    # 尝试从 continuation_contract 直接提取
    if isinstance(payload.get("continuation_contract"), dict):
        return ContinuationContract.from_dict(payload["continuation_contract"])
    
    # 尝试从 metadata 提取
    if isinstance(payload.get("metadata"), dict):
        metadata = payload["metadata"]
        if metadata.get("stopped_because") or metadata.get("next_step") or metadata.get("next_owner"):
            return ContinuationContract(
                stopped_because=metadata.get("stopped_because", ""),
                next_step=metadata.get("next_step", ""),
                next_owner=metadata.get("next_owner", ""),
                metadata={"source": f"metadata:{source}"},
            )
    
    return None


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

RegistrationStatus = Literal["registered", "skipped", "blocked"]


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


@dataclass
class NextTaskRegistrationWithStatus:
    """
    Next task registration with status — v2 扩展，增加 registration_status / truth_anchor。
    
    核心字段：
    - registration: 原始 NextTaskRegistrationPayload
    - registration_status: registered | skipped | blocked
    - registration_reason: 注册/跳过/阻止的原因
    - truth_anchor: 稳定的 source linkage（source_task_id / source_batch_id / new_task_id）
    - ready_for_auto_dispatch: 是否准备好自动 dispatch
    
    这是 v2 新增的 canonical artifact，operator/main 可以继续消费。
    """
    registration: NextTaskRegistrationPayload
    registration_status: RegistrationStatus
    registration_reason: str
    truth_anchor: Dict[str, Any]  # {anchor_type, anchor_value, metadata}
    ready_for_auto_dispatch: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "registration_version": "next_task_registration_with_status_v2",
            "registration": self.registration.to_dict(),
            "registration_status": self.registration_status,
            "registration_reason": self.registration_reason,
            "truth_anchor": self.truth_anchor,
            "ready_for_auto_dispatch": self.ready_for_auto_dispatch,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NextTaskRegistrationWithStatus":
        return cls(
            registration=NextTaskRegistrationPayload.from_dict(data.get("registration", {})),
            registration_status=data.get("registration_status", "registered"),
            registration_reason=data.get("registration_reason", ""),
            truth_anchor=data.get("truth_anchor", {}),
            ready_for_auto_dispatch=data.get("ready_for_auto_dispatch", False),
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


# ============ v2: Auto-Registration Layer ============

def generate_registered_registrations_for_closeout(
    closeout: PartialCloseoutContract,
    *,
    adapter: Optional[str] = None,
    scenario: Optional[str] = None,
    max_candidates: int = 3,
    context: Optional[Dict[str, Any]] = None,
    auto_register: bool = True,
    batch_id: Optional[str] = None,
    owner: Optional[str] = None,
) -> List[NextTaskRegistrationWithStatus]:
    """
    为一个 partial closeout contract 生成所有 next task registrations with status（v2）。
    
    这是 v2 新增的 convenience function，组合了：
    1. auto_replan: 生成 next candidates
    2. build_next_task_registration: 构建 registration payload
    3. 自动决定 registration_status（registered | skipped | blocked）
    4. 生成 truth_anchor（stable source linkage）
    5. 可选：直接注册到 task registry（auto_register=True）
    
    参数：
    - closeout: partial closeout contract
    - adapter: 场景 adapter（可选）
    - scenario: 场景名称（可选）
    - max_candidates: 最多生成的 candidate 数量
    - context: 额外上下文
    - auto_register: 是否自动注册到 task registry（默认 True）
    - batch_id: 所属批次 ID（可选）
    - owner: 任务所有者（可选）
    
    返回：NextTaskRegistrationWithStatus 列表
    """
    if not closeout.should_generate_next_registration():
        # 没有剩余工作或 blocked，返回空列表
        return []
    
    candidates = auto_replan(closeout, max_candidates=max_candidates, context=context)
    
    registrations_with_status: List[NextTaskRegistrationWithStatus] = []
    
    for candidate in candidates:
        # 构建 registration payload
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
        
        # 决定 registration_status
        registration_status: RegistrationStatus = "registered"
        registration_reason = "Auto-generated from partial closeout"
        
        if closeout.dispatch_readiness == "blocked":
            registration_status = "blocked"
            registration_reason = f"Closeout dispatch_readiness is blocked (stop_reason={closeout.stop_reason})"
        elif candidate.metadata.get("source_scope_status") == "blocked":
            registration_status = "blocked"
            registration_reason = "Candidate scope item is blocked"
        
        # 生成 truth_anchor
        truth_anchor = {
            "anchor_type": "batch_id" if batch_id else "task_id",
            "anchor_value": batch_id or closeout.original_task_id or closeout.original_batch_id or "",
            "metadata": {
                "source_closeout_registration_id": registration.registration_id,
                "source_candidate_id": candidate.candidate_id,
                "source_task_id": closeout.original_task_id,
                "source_batch_id": closeout.original_batch_id,
                "adapter": adapter,
                "scenario": scenario,
            },
        }
        
        # 决定 ready_for_auto_dispatch
        ready_for_auto_dispatch = (
            registration_status == "registered" and
            closeout.dispatch_readiness == "ready" and
            candidate.priority == 1
        )
        
        # 构建 result
        result = NextTaskRegistrationWithStatus(
            registration=registration,
            registration_status=registration_status,
            registration_reason=registration_reason,
            truth_anchor=truth_anchor,
            ready_for_auto_dispatch=ready_for_auto_dispatch,
            metadata={
                "batch_id": batch_id,
                "owner": owner,
                "adapter": adapter,
                "scenario": scenario,
            },
        )
        
        # 可选：自动注册到 task registry
        if auto_register and registration_status == "registered":
            try:
                from task_registration import register_next_task_from_payload, TaskRegistrationRecord
                record = register_next_task_from_payload(
                    registration_payload=registration.to_dict(),
                    registration_status=registration_status,
                    registration_reason=registration_reason,
                    batch_id=batch_id,
                    owner=owner,
                    ready_for_auto_dispatch=ready_for_auto_dispatch,
                )
                result.metadata["task_registry_record"] = {
                    "registration_id": record.registration_id,
                    "task_id": record.task_id,
                }
                result.truth_anchor["anchor_type"] = "task_id"
                result.truth_anchor["anchor_value"] = record.task_id
            except ImportError:
                # task_registration 模块不可用时，跳过注册
                pass
        
        registrations_with_status.append(result)
    
    return registrations_with_status
