"""
post_completion_replan.py — 任务完成后的 follow-up registration contract

目标：当一个任务完成后，若要继续一个**不在原 dispatch plan 内**的新后续工作，
必须显式进入一个结构化状态，而不是口头继续。

核心概念：
- followup_mode: existing_dispatch | pending_registration
- truth_anchor_type: task_id | batch_id | branch | commit | push | none
- allowed_status_phrase: in_progress | pending_registration
- 没 anchor 时默认只能是 pending_registration

P0-1 Batch 4: 集成 ContinuationContract，统一 continuation 语义
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
    "convert_replan_to_continuation_contract",
    "convert_continuation_contract_to_replan",
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


# ============ P0-1 Batch 4: ContinuationContract Integration ============

def convert_replan_to_continuation_contract(
    replan: PostCompletionReplanContract,
) -> "ContinuationContract":
    """
    将 PostCompletionReplanContract 转换为 ContinuationContract。
    
    这是 P0-1 Batch 4 统一 continuation 语义的一部分。
    
    映射规则：
    - stopped_because: 从 followup_description + status_phrase 推导
    - next_step: followup_description
    - next_owner: 从 metadata 或 truth_anchor.metadata 中提取
    
    参数：
    - replan: PostCompletionReplanContract
    
    返回：ContinuationContract
    """
    # 延迟导入，避免循环依赖
    from partial_continuation import ContinuationContract
    
    # 推导 stopped_because
    if replan.followup_mode == "pending_registration":
        stopped_because = f"follow_up_pending_registration: {replan.followup_description}"
    elif replan.truth_anchor.has_anchor():
        stopped_because = f"follow_up_registered ({replan.truth_anchor.anchor_type}={replan.truth_anchor.anchor_value}): {replan.followup_description}"
    else:
        stopped_because = f"follow_up_{replan.status_phrase}: {replan.followup_description}"
    
    # next_step 直接使用 followup_description
    next_step = replan.followup_description
    
    # next_owner 从 metadata 中提取
    next_owner = (
        replan.metadata.get("next_owner") or
        replan.truth_anchor.anchor_metadata.get("owner") or
        "main"
    )
    
    return ContinuationContract(
        stopped_because=stopped_because,
        next_step=next_step,
        next_owner=next_owner,
        metadata={
            "source": "post_completion_replan",
            "replan_contract_version": REPLAN_CONTRACT_VERSION,
            "followup_mode": replan.followup_mode,
            "truth_anchor": replan.truth_anchor.to_dict(),
            "status_phrase": replan.status_phrase,
            "original_task_id": replan.original_task_id,
            "original_batch_id": replan.original_batch_id,
        },
    )


def convert_continuation_contract_to_replan(
    continuation: "ContinuationContract",
    *,
    followup_mode: Optional[FollowUpMode] = None,
    anchor_type: Optional[TruthAnchorType] = None,
    anchor_value: Optional[str] = None,
    force_pending: bool = False,
) -> PostCompletionReplanContract:
    """
    将 ContinuationContract 转换为 PostCompletionReplanContract。
    
    这是 P0-1 Batch 4 统一 continuation 语义的一部分。
    
    映射规则：
    - followup_description: 从 next_step 提取
    - followup_mode: 根据 anchor 或显式指定
    - truth_anchor: 从 continuation.metadata 或显式指定构建
    - status_phrase: 根据 followup_mode 和 anchor 自动推导
    
    参数：
    - continuation: ContinuationContract
    - followup_mode: 可选，显式指定 followup_mode
    - anchor_type: 可选，显式指定 anchor 类型
    - anchor_value: 可选，显式指定 anchor 值
    - force_pending: 是否强制设为 pending_registration
    
    返回：PostCompletionReplanContract
    """
    # 延迟导入，避免循环依赖
    from partial_continuation import ContinuationContract
    
    # 从 continuation 中提取信息
    followup_description = continuation.next_step
    
    # 尝试从 metadata 中提取 anchor
    metadata = continuation.metadata or {}
    if anchor_type is None:
        anchor_type = metadata.get("truth_anchor", {}).get("anchor_type")
    if anchor_value is None:
        anchor_value = metadata.get("truth_anchor", {}).get("anchor_value")
    
    # 如果没有显式指定 anchor，尝试从其他 metadata 字段推导
    if anchor_type is None:
        if metadata.get("original_task_id"):
            anchor_type = "task_id"
            anchor_value = metadata["original_task_id"]
        elif metadata.get("original_batch_id"):
            anchor_type = "batch_id"
            anchor_value = metadata["original_batch_id"]
    
    # 构建 replan contract
    return build_replan_contract(
        followup_description=followup_description,
        original_task_id=metadata.get("original_task_id"),
        original_batch_id=metadata.get("original_batch_id"),
        anchor_type=anchor_type,
        anchor_value=anchor_value,
        anchor_metadata={
            "source": "continuation_contract",
            "stopped_because": continuation.stopped_because,
            "next_owner": continuation.next_owner,
        },
        force_pending=force_pending,
        metadata={
            "source": "continuation_contract",
            "continuation_contract_version": continuation.__class__.__dict__.get("CONTINUATION_CONTRACT_VERSION", "unknown"),
            "stopped_because": continuation.stopped_because,
            "next_owner": continuation.next_owner,
        },
    )
