"""
post_completion_replan.py — 任务完成后的 follow-up registration contract

目标：当一个任务完成后，若要继续一个**不在原 dispatch plan 内**的新后续工作，
必须显式进入一个结构化状态，而不是口头继续。

核心概念：
- followup_mode: existing_dispatch | pending_registration
- truth_anchor_type: task_id | batch_id | branch | commit | push | none
- allowed_status_phrase: in_progress | pending_registration
- 没 anchor 时默认只能是 pending_registration
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

__all__ = [
    "FollowUpMode",
    "TruthAnchorType",
    "StatusPhrase",
    "PostCompletionReplanContract",
    "validate_followup_status",
    "build_replan_contract",
    "REPLAN_CONTRACT_VERSION",
]

REPLAN_CONTRACT_VERSION = "post_completion_replan_v1"

FollowUpMode = Literal["existing_dispatch", "pending_registration"]
TruthAnchorType = Literal["task_id", "batch_id", "branch", "commit", "push", "none"]
StatusPhrase = Literal["in_progress", "pending_registration"]


@dataclass
class TruthAnchor:
    """
    真值锚点：用于标识 follow-up 工作是否已在系统中有注册记录。
    
    有 anchor 的工作可以标成 in_progress；
    无 anchor 的工作只能标成 pending_registration。
    """
    anchor_type: TruthAnchorType
    anchor_value: Optional[str] = None
    anchor_metadata: Dict[str, Any] = field(default_factory=dict)
    
    def has_anchor(self) -> bool:
        """是否有有效的真值锚点"""
        return self.anchor_type != "none" and bool(self.anchor_value)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "anchor_type": self.anchor_type,
            "anchor_value": self.anchor_value,
            "anchor_metadata": self.anchor_metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TruthAnchor":
        return cls(
            anchor_type=data.get("anchor_type", "none"),
            anchor_value=data.get("anchor_value"),
            anchor_metadata=data.get("anchor_metadata", {}),
        )


@dataclass
class PostCompletionReplanContract:
    """
    任务完成后的 follow-up registration contract。
    
    用于显式区分：
    1) 已注册 continuation（有 task/batch/dispatch anchor）
    2) 待注册新任务（planned but not started）
    """
    followup_mode: FollowUpMode
    truth_anchor: TruthAnchor
    status_phrase: StatusPhrase
    followup_description: str = ""
    original_task_id: Optional[str] = None
    original_batch_id: Optional[str] = None
    continuation_whitelist_checked: bool = False
    gate_policy_override: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def validate(self) -> tuple[bool, List[str]]:
        """
        验证 contract 是否符合规则。
        
        核心规则：
        - 没 anchor 时，followup_mode 只能是 pending_registration
        - 没 anchor 时，status_phrase 只能是 pending_registration
        - 有 anchor 时，才允许 in_progress
        """
        errors: List[str] = []
        
        # 规则 1: 没 anchor 时，followup_mode 只能是 pending_registration
        if not self.truth_anchor.has_anchor() and self.followup_mode != "pending_registration":
            errors.append(
                f"Invalid: no truth_anchor but followup_mode={self.followup_mode!r}. "
                "Must be 'pending_registration' when anchor is missing."
            )
        
        # 规则 2: 没 anchor 时，status_phrase 只能是 pending_registration
        if not self.truth_anchor.has_anchor() and self.status_phrase != "pending_registration":
            errors.append(
                f"Invalid: no truth_anchor but status_phrase={self.status_phrase!r}. "
                "Must be 'pending_registration' when anchor is missing."
            )
        
        # 规则 3: 有 anchor 时，followup_mode 应该与 anchor 类型一致
        if self.truth_anchor.has_anchor():
            if self.followup_mode == "pending_registration":
                # 这是一个警告，不是错误：有 anchor 但仍然选择 pending_registration 是允许的
                # （例如：anchor 存在但需要人工确认）
                pass
            elif self.followup_mode == "existing_dispatch":
                # 有效状态
                pass
        
        # 规则 4: status_phrase 必须与 followup_mode 一致
        if self.followup_mode == "existing_dispatch" and self.status_phrase == "pending_registration":
            # 这是一个警告：已有 dispatch 但仍然 pending，可能是 gate 拦住
            pass
        elif self.followup_mode == "pending_registration" and self.status_phrase == "in_progress":
            errors.append(
                f"Invalid: followup_mode={self.followup_mode!r} but status_phrase={self.status_phrase!r}. "
                "Cannot be 'in_progress' without existing_dispatch."
            )
        
        return len(errors) == 0, errors
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "contract_version": REPLAN_CONTRACT_VERSION,
            "followup_mode": self.followup_mode,
            "truth_anchor": self.truth_anchor.to_dict(),
            "status_phrase": self.status_phrase,
            "followup_description": self.followup_description,
            "original_task_id": self.original_task_id,
            "original_batch_id": self.original_batch_id,
            "continuation_whitelist_checked": self.continuation_whitelist_checked,
            "gate_policy_override": self.gate_policy_override,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PostCompletionReplanContract":
        return cls(
            followup_mode=data.get("followup_mode", "pending_registration"),
            truth_anchor=TruthAnchor.from_dict(data.get("truth_anchor", {})),
            status_phrase=data.get("status_phrase", "pending_registration"),
            followup_description=data.get("followup_description", ""),
            original_task_id=data.get("original_task_id"),
            original_batch_id=data.get("original_batch_id"),
            continuation_whitelist_checked=data.get("continuation_whitelist_checked", False),
            gate_policy_override=data.get("gate_policy_override"),
            metadata=data.get("metadata", {}),
        )


def validate_followup_status(
    *,
    followup_mode: FollowUpMode,
    anchor_type: TruthAnchorType,
    anchor_value: Optional[str] = None,
    status_phrase: Optional[StatusPhrase] = None,
) -> tuple[bool, StatusPhrase, List[str]]:
    """
    验证 follow-up 状态是否符合规则。
    
    返回：(is_valid, resolved_status_phrase, errors)
    
    核心规则：
    - 没 anchor 时，status_phrase 只能是 pending_registration
    - 有 anchor 时，才允许 in_progress
    """
    errors: List[str] = []
    has_anchor = anchor_type != "none" and bool(anchor_value)
    
    # 确定 status_phrase
    if status_phrase is None:
        # 默认推导
        if has_anchor and followup_mode == "existing_dispatch":
            resolved_status = "in_progress"
        else:
            resolved_status = "pending_registration"
    else:
        resolved_status = status_phrase
    
    # 验证规则
    if not has_anchor:
        if followup_mode != "pending_registration":
            errors.append(
                f"Invalid: no anchor but followup_mode={followup_mode!r}. "
                "Must be 'pending_registration'."
            )
        if resolved_status != "pending_registration":
            errors.append(
                f"Invalid: no anchor but status_phrase={resolved_status!r}. "
                "Must be 'pending_registration'."
            )
            resolved_status = "pending_registration"  # 强制修正
    
    if has_anchor and followup_mode == "pending_registration" and resolved_status == "in_progress":
        errors.append(
            f"Invalid: followup_mode={followup_mode!r} but status_phrase={resolved_status!r}. "
            "Cannot be 'in_progress' without existing_dispatch."
        )
        resolved_status = "pending_registration"  # 强制修正
    
    return len(errors) == 0, resolved_status, errors


def build_replan_contract(
    *,
    followup_description: str,
    original_task_id: Optional[str] = None,
    original_batch_id: Optional[str] = None,
    anchor_type: Optional[TruthAnchorType] = None,
    anchor_value: Optional[str] = None,
    anchor_metadata: Optional[Dict[str, Any]] = None,
    force_pending: bool = False,
    continuation_whitelist_checked: bool = False,
    metadata: Optional[Dict[str, Any]] = None,
) -> PostCompletionReplanContract:
    """
    构建一个 post-completion replan contract。
    
    参数：
    - followup_description: follow-up 工作的描述
    - original_task_id: 原始任务 ID（可选）
    - original_batch_id: 原始 batch ID（可选）
    - anchor_type: 锚点类型（task_id | batch_id | branch | commit | push | none）
    - anchor_value: 锚点值
    - anchor_metadata: 锚点元数据
    - force_pending: 强制设为 pending_registration（即使有 anchor）
    - continuation_whitelist_checked: 是否已检查 continuation whitelist
    - metadata: 额外元数据
    
    返回：PostCompletionReplanContract
    """
    # 确定 anchor
    if anchor_type is None or anchor_type == "none" or not anchor_value:
        truth_anchor = TruthAnchor(anchor_type="none")
        followup_mode = "pending_registration"
        status_phrase = "pending_registration"
    elif force_pending:
        truth_anchor = TruthAnchor(
            anchor_type=anchor_type,
            anchor_value=anchor_value,
            anchor_metadata=anchor_metadata or {},
        )
        followup_mode = "pending_registration"
        status_phrase = "pending_registration"
    else:
        truth_anchor = TruthAnchor(
            anchor_type=anchor_type,
            anchor_value=anchor_value,
            anchor_metadata=anchor_metadata or {},
        )
        followup_mode = "existing_dispatch"
        status_phrase = "in_progress"
    
    contract = PostCompletionReplanContract(
        followup_mode=followup_mode,
        truth_anchor=truth_anchor,
        status_phrase=status_phrase,
        followup_description=followup_description,
        original_task_id=original_task_id,
        original_batch_id=original_batch_id,
        continuation_whitelist_checked=continuation_whitelist_checked,
        metadata=metadata or {},
    )
    
    is_valid, errors = contract.validate()
    if not is_valid:
        raise ValueError(f"Invalid replan contract: {'; '.join(errors)}")
    
    return contract


def check_continuation_in_original_dispatch(
    *,
    original_dispatch_plan: Optional[Dict[str, Any]],
    followup_description: str,
) -> tuple[bool, Optional[TruthAnchorType], Optional[str]]:
    """
    检查 follow-up 是否在原始 dispatch plan 中已注册。
    
    返回：(is_in_original_plan, anchor_type, anchor_value)
    
    如果 follow-up 在原 plan 中，返回对应的 anchor 类型和值；
    否则返回 (False, None, None)。
    """
    if not original_dispatch_plan:
        return False, None, None
    
    # 检查 dispatch plan 中的 next_steps / continuations
    next_steps = original_dispatch_plan.get("next_steps", [])
    continuations = original_dispatch_plan.get("continuations", [])
    
    all_planned = next_steps + continuations
    
    for step in all_planned:
        step_desc = step.get("description", "") or step.get("name", "")
        if followup_description.lower() in step_desc.lower():
            # 找到匹配的 planned step
            anchor_type = step.get("anchor_type", "task_id")
            anchor_value = step.get("anchor_value") or step.get("task_id")
            if anchor_value:
                return True, anchor_type, anchor_value
    
    return False, None, None
