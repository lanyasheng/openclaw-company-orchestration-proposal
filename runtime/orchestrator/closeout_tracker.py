#!/usr/bin/env python3
"""
closeout_tracker.py — Closeout State Tracker

跟踪 batch 完成后的 closeout 状态，显式标记：
1. closeout_status: 是否已前进到最新批次
2. push_required: 是否需要 git push 收口
3. closeout_artifact_path: closeout artifact 路径

这是最小可行修复，用于解决"batch 完成后 closeout 链路缺失"问题。

核心设计：
- 不自动 push（那是上层 glue 的职责）
- 但显式输出 push_required 状态信号，让主流程不再无声停住
- closeout artifact 包含 continuation_contract，统一 continuation 语义
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from state_machine import STATE_DIR, _iso_now, get_batch_tasks, get_state
from partial_continuation import ContinuationContract, build_continuation_contract

__all__ = [
    "CloseoutStatus",
    "CloseoutArtifact",
    "CloseoutTracker",
    "CLOSEOUT_TRACKER_VERSION",
    "CloseoutGateResult",
    "check_closeout_gate",
    # P0-4 Final Mile: Push Consumer / Status Backfill
    "PushStatus",
    "PushActionStatus",
    "PushAction",
    "emit_push_action",
    "consume_push_action",
    "update_push_status",
    "simulate_push_success",
    "get_push_action",
]

CLOSEOUT_TRACKER_VERSION = "closeout_tracker_v1"

# Closeout 存储目录（支持 OPENCLAW_CLOSEOUT_DIR 环境变量用于测试隔离）
CLOSEOUT_DIR = Path(os.environ.get("OPENCLAW_CLOSEOUT_DIR", str(STATE_DIR.parent / "orchestrator" / "closeouts")))

# Push status
PushStatus = Literal["pending", "pushed", "not_required", "blocked"]

# Closeout status
CloseoutStatus = Literal[
    "complete",           # closeout 已完成，所有状态一致
    "pending_push",       # closeout 已完成，等待 push
    "incomplete",         # closeout 未完成（仍有 remaining work）
    "blocked",            # closeout 被 blocker 阻止
    "stale",              # closeout 状态落后于最新 batch
]

# P0-4 Final Mile: Push Action Status
PushActionStatus = Literal[
    "emitted",            # push action 已生成，等待消费
    "consumed",           # push action 已消费（intent 记录），等待执行
    "executed",           # push 已执行（本地 commit 完成）
    "failed",             # push 执行失败
    "blocked",            # push 被阻止
]


def _ensure_closeout_dir() -> None:
    """确保 closeout 目录存在"""
    CLOSEOUT_DIR.mkdir(parents=True, exist_ok=True)


def _closeout_file(batch_id: str) -> Path:
    """返回 closeout artifact 文件路径"""
    safe_batch_id = batch_id.replace("/", "_").replace(" ", "_")
    return CLOSEOUT_DIR / f"closeout-{safe_batch_id}.json"


def _atomic_json_write(file_path: Path, payload: Dict[str, Any]) -> None:
    """原子写入 JSON 文件"""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_file = file_path.with_suffix(file_path.suffix + ".tmp")
    with open(tmp_file, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    tmp_file.replace(file_path)


@dataclass
class PushAction:
    """
    P0-4 Final Mile: Push Action — 标准化的 push action 记录。
    
    用于跟踪 push 动作的生命周期：
    1. emitted: push action 已生成，等待消费
    2. consumed: push action 已消费（intent 记录），等待执行
    3. executed: push 已执行（本地 commit 完成）
    4. failed: push 执行失败
    5. blocked: push 被阻止
    
    核心设计：
    - 不真实 push 远端（除非显式调用真实 push 函数）
    - 受控模拟 push 成功用于测试闭环
    - 状态必须诚实，不能伪造"已 push"
    """
    action_id: str
    batch_id: str
    closeout_id: str
    status: PushActionStatus
    intent: str  # push 意图描述
    executed_at: Optional[str] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: _iso_now())
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_id": self.action_id,
            "batch_id": self.batch_id,
            "closeout_id": self.closeout_id,
            "status": self.status,
            "intent": self.intent,
            "executed_at": self.executed_at,
            "error": self.error,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PushAction":
        return cls(
            action_id=data.get("action_id", ""),
            batch_id=data.get("batch_id", ""),
            closeout_id=data.get("closeout_id", ""),
            status=data.get("status", "emitted"),
            intent=data.get("intent", ""),
            executed_at=data.get("executed_at"),
            error=data.get("error"),
            metadata=data.get("metadata", {}),
            created_at=data.get("created_at", _iso_now()),
        )


@dataclass
class CloseoutArtifact:
    """
    Closeout artifact — 记录 batch 完成后的 closeout 状态。
    
    核心字段：
    - closeout_id: Closeout ID
    - batch_id: 批次 ID
    - closeout_status: closeout 状态
    - push_status: git push 状态
    - push_required: 是否需要 push
    - continuation_contract: 统一的 continuation 语义
    - artifacts: 相关 artifact 路径（summary/decision/dispatch）
    - push_action: push action 记录（P0-4 Final Mile）
    - metadata: 额外元数据
    """
    closeout_id: str
    batch_id: str
    closeout_status: CloseoutStatus
    push_status: PushStatus
    push_required: bool
    continuation_contract: ContinuationContract
    artifacts: Dict[str, str] = field(default_factory=dict)
    push_action: Optional[PushAction] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: _iso_now())
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "closeout_version": CLOSEOUT_TRACKER_VERSION,
            "closeout_id": self.closeout_id,
            "batch_id": self.batch_id,
            "closeout_status": self.closeout_status,
            "push_status": self.push_status,
            "push_required": self.push_required,
            "continuation_contract": self.continuation_contract.to_dict(),
            "artifacts": self.artifacts,
            "push_action": self.push_action.to_dict() if self.push_action else None,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CloseoutArtifact":
        push_action_data = data.get("push_action")
        push_action = PushAction.from_dict(push_action_data) if push_action_data else None
        
        return cls(
            closeout_id=data.get("closeout_id", ""),
            batch_id=data.get("batch_id", ""),
            closeout_status=data.get("closeout_status", "incomplete"),
            push_status=data.get("push_status", "pending"),
            push_required=data.get("push_required", False),
            continuation_contract=ContinuationContract.from_dict(data.get("continuation_contract", {})),
            artifacts=data.get("artifacts", {}),
            push_action=push_action,
            metadata=data.get("metadata", {}),
            created_at=data.get("created_at", _iso_now()),
        )
    
    def write(self) -> Path:
        """写入 closeout artifact 到文件"""
        _ensure_closeout_dir()
        closeout_path = _closeout_file(self.batch_id)
        _atomic_json_write(closeout_path, self.to_dict())
        return closeout_path


class CloseoutTracker:
    """
    Closeout tracker — 跟踪 batch 完成后的 closeout 状态。
    
    提供：
    - create_closeout(): 创建 closeout artifact
    - emit_closeout(): emit closeout（写入 artifact）
    - get_closeout(): 获取已存在的 closeout
    - check_push_required(): 检查是否需要 push
    """
    
    def __init__(self):
        pass
    
    def _determine_closeout_status(
        self,
        batch_id: str,
        continuation: ContinuationContract,
        has_remaining_work: bool,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> tuple[CloseoutStatus, str]:
        """
        根据 continuation 和 remaining work 决定 closeout status。
        
        Returns:
            (closeout_status, closeout_reason)
        """
        metadata = metadata or {}
        roundtable = metadata.get("roundtable", {})
        packet = metadata.get("packet", {})
        
        # 优先检查 roundtable conclusion 和 packet overall_gate
        conclusion = str(roundtable.get("conclusion") or packet.get("overall_gate") or "").upper()
        blocker = str(roundtable.get("blocker") or packet.get("primary_blocker") or "").lower()
        
        # FAIL 结论 -> blocked
        if conclusion == "FAIL" or (blocker and blocker != "none"):
            return "blocked", f"Closeout blocked: conclusion={conclusion}, blocker={blocker}"
        
        # 检查是否有 remaining work
        if has_remaining_work:
            return "incomplete", f"Closeout has remaining work: {continuation.next_step}"
        
        # 检查 continuation 的 stopped_because
        stopped_because = continuation.stopped_because.lower()
        
        if "blocked" in stopped_because or "failed" in stopped_because:
            return "blocked", f"Closeout blocked: {continuation.stopped_because}"
        
        if "partial" in stopped_because:
            return "incomplete", f"Closeout partial: {continuation.stopped_because}"
        
        # 默认：complete，但需要 push
        return "complete", "Closeout complete; awaiting git push"
    
    def _determine_push_required(
        self,
        batch_id: str,
        scenario: str,
        metadata: Dict[str, Any],
    ) -> tuple[bool, str]:
        """
        判断是否需要 git push。
        
        规则：
        - trading 场景默认需要 push（因为涉及代码/配置变更）
        - 如果 metadata 中明确标记 push_not_required=True，则不需要
        - 如果有 git_commit 但未 push，则需要 push
        
        Returns:
            (push_required, push_reason)
        """
        # 检查是否显式禁用 push
        if metadata.get("push_not_required"):
            return False, "Push explicitly disabled by metadata"
        
        # trading 场景默认需要 push
        if "trading" in scenario.lower():
            return True, "Trading scenario requires git push by default"
        
        # 检查是否有 git commit
        packet = metadata.get("packet", {})
        commit = packet.get("commit", {})
        if commit.get("git_commit"):
            return True, "Git commit detected; push required"
        
        # 默认不需要 push
        return False, "No git commit detected; push not required"
    
    def create_closeout(
        self,
        batch_id: str,
        scenario: str,
        continuation: ContinuationContract,
        has_remaining_work: bool,
        artifacts: Optional[Dict[str, str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> CloseoutArtifact:
        """
        创建 closeout artifact。
        
        Args:
            batch_id: 批次 ID
            scenario: 场景名称
            continuation: continuation contract
            has_remaining_work: 是否有剩余工作
            artifacts: artifact 路径字典（summary_path/decision_path/dispatch_path）
            metadata: 额外元数据（packet/roundtable 等）
        
        Returns:
            CloseoutArtifact
        """
        # 决定 closeout status
        closeout_status, closeout_reason = self._determine_closeout_status(
            batch_id=batch_id,
            continuation=continuation,
            has_remaining_work=has_remaining_work,
            metadata=metadata,
        )
        
        # 决定 push_required
        push_required, push_reason = self._determine_push_required(
            batch_id=batch_id,
            scenario=scenario,
            metadata=metadata or {},
        )
        
        # 决定 push status
        if not push_required:
            push_status: PushStatus = "not_required"
        elif closeout_status in ("blocked", "incomplete"):
            push_status = "blocked"
        else:
            push_status = "pending"
        
        # 生成 closeout ID
        import uuid
        closeout_id = f"closeout_{uuid.uuid4().hex[:12]}"
        
        # 构建 metadata
        full_metadata = metadata or {}
        full_metadata["closeout_reason"] = closeout_reason
        full_metadata["push_reason"] = push_reason
        full_metadata["scenario"] = scenario
        
        artifact = CloseoutArtifact(
            closeout_id=closeout_id,
            batch_id=batch_id,
            closeout_status=closeout_status,
            push_status=push_status,
            push_required=push_required,
            continuation_contract=continuation,
            artifacts=artifacts or {},
            metadata=full_metadata,
        )
        
        return artifact
    
    def emit_closeout(
        self,
        batch_id: str,
        scenario: str,
        continuation: ContinuationContract,
        has_remaining_work: bool,
        artifacts: Optional[Dict[str, str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> CloseoutArtifact:
        """
        Emit closeout：创建 artifact -> 写入文件。
        
        Args:
            batch_id: 批次 ID
            scenario: 场景名称
            continuation: continuation contract
            has_remaining_work: 是否有剩余工作
            artifacts: artifact 路径字典
            metadata: 额外元数据
        
        Returns:
            CloseoutArtifact（已写入文件）
        """
        # 创建 artifact
        artifact = self.create_closeout(
            batch_id=batch_id,
            scenario=scenario,
            continuation=continuation,
            has_remaining_work=has_remaining_work,
            artifacts=artifacts,
            metadata=metadata,
        )
        
        # 写入文件
        artifact.write()
        
        return artifact
    
    def get_closeout(self, batch_id: str) -> Optional[CloseoutArtifact]:
        """
        获取已存在的 closeout artifact。
        
        Args:
            batch_id: 批次 ID
        
        Returns:
            CloseoutArtifact，不存在则返回 None
        """
        closeout_path = _closeout_file(batch_id)
        if not closeout_path.exists():
            return None
        
        with open(closeout_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        return CloseoutArtifact.from_dict(data)
    
    def check_push_required(self, batch_id: str) -> Dict[str, Any]:
        """
        检查 batch 是否需要 push。
        
        Args:
            batch_id: 批次 ID
        
        Returns:
            {
                "push_required": bool,
                "push_status": PushStatus,
                "closeout_status": CloseoutStatus,
                "reason": str,
            }
        """
        closeout = self.get_closeout(batch_id)
        
        if not closeout:
            return {
                "push_required": False,
                "push_status": "not_required",
                "closeout_status": "incomplete",
                "reason": "Closeout artifact not found",
            }
        
        return {
            "push_required": closeout.push_required,
            "push_status": closeout.push_status,
            "closeout_status": closeout.closeout_status,
            "reason": closeout.metadata.get("push_reason", ""),
            "closeout_id": closeout.closeout_id,
        }


def create_closeout(
    batch_id: str,
    scenario: str,
    continuation: ContinuationContract,
    has_remaining_work: bool,
    artifacts: Optional[Dict[str, str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> CloseoutArtifact:
    """
    Convenience function: 创建并 emit closeout artifact。
    
    Args:
        batch_id: 批次 ID
        scenario: 场景名称
        continuation: continuation contract
        has_remaining_work: 是否有剩余工作
        artifacts: artifact 路径字典
        metadata: 额外元数据
    
    Returns:
        CloseoutArtifact（已写入文件）
    """
    tracker = CloseoutTracker()
    return tracker.emit_closeout(
        batch_id=batch_id,
        scenario=scenario,
        continuation=continuation,
        has_remaining_work=has_remaining_work,
        artifacts=artifacts,
        metadata=metadata,
    )


def get_closeout(batch_id: str) -> Optional[CloseoutArtifact]:
    """
    Convenience function: 获取 closeout artifact。
    
    Args:
        batch_id: 批次 ID
    
    Returns:
        CloseoutArtifact，不存在则返回 None
    """
    tracker = CloseoutTracker()
    return tracker.get_closeout(batch_id)


def check_push_required(batch_id: str) -> Dict[str, Any]:
    """
    Convenience function: 检查是否需要 push。
    
    Args:
        batch_id: 批次 ID
    
    Returns:
        push status 字典
    """
    tracker = CloseoutTracker()
    return tracker.check_push_required(batch_id)


# ========== P0-4 Batch 2: Closeout Gate Glue ==========
# 最小 closeout gate glue：检查前一批 closeout 状态，决定是否允许下一批继续

@dataclass
class CloseoutGateResult:
    """
    Closeout gate 检查结果
    
    用于在 batch 开始前检查前一批的 closeout 状态。
    """
    allowed: bool
    reason: str
    previous_batch_id: Optional[str] = None
    previous_closeout_status: Optional[CloseoutStatus] = None
    previous_push_status: Optional[PushStatus] = None
    previous_push_required: Optional[bool] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "previous_batch_id": self.previous_batch_id,
            "previous_closeout_status": self.previous_closeout_status,
            "previous_push_status": self.previous_push_status,
            "previous_push_required": self.previous_push_required,
        }


def check_closeout_gate(
    batch_id: str,
    scenario: str,
    require_push_complete: bool = True,
) -> CloseoutGateResult:
    """
    检查 closeout gate：在 batch 开始前检查前一批的 closeout 状态。
    
    这是最小 closeout gate glue，用于确保：
    1. 前一批 closeout 已完成（或至少不是 blocked）
    2. 如果需要 push，前一批 push 已执行
    
    Args:
        batch_id: 当前批次 ID
        scenario: 场景名称
        require_push_complete: 是否要求 push 已完成（trading 场景默认 True）
    
    Returns:
        CloseoutGateResult: 检查结果
    
    注意：
    - 这个函数不会自动阻止 batch 开始，只是返回检查结果
    - 调用方需要根据结果决定是否阻止 batch 开始
    - 这是最小 glue，不是强制 gate；强制 gate 需要在 entry point 集成
    """
    # 对于 trading 场景，默认要求 push complete
    if "trading" in scenario.lower():
        require_push_complete = True
    
    # 查找前一批 closeout（通过遍历 closeout 目录）
    _ensure_closeout_dir()
    
    previous_closeout: Optional[CloseoutArtifact] = None
    previous_batch_id: Optional[str] = None
    
    # 简单策略：查找所有 closeout 文件，找到最新的（按 created_at）
    # 注意：这是简化实现，生产环境可能需要更复杂的逻辑来识别"前一批"
    for closeout_file in CLOSEOUT_DIR.glob("closeout-*.json"):
        with open(closeout_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        # 跳过当前 batch
        if data.get("batch_id") == batch_id:
            continue
        
        artifact = CloseoutArtifact.from_dict(data)
        
        # 找到最新的 closeout
        if previous_closeout is None or artifact.created_at > previous_closeout.created_at:
            previous_closeout = artifact
            previous_batch_id = artifact.batch_id
    
    # 如果没有前一批 closeout，允许继续（首次运行）
    if previous_closeout is None:
        return CloseoutGateResult(
            allowed=True,
            reason="No previous closeout found; first run allowed",
        )
    
    # 检查前一批 closeout 状态
    if previous_closeout.closeout_status == "blocked":
        return CloseoutGateResult(
            allowed=False,
            reason=f"Previous batch {previous_batch_id} closeout is blocked: {previous_closeout.metadata.get('closeout_reason', 'unknown')}",
            previous_batch_id=previous_batch_id,
            previous_closeout_status=previous_closeout.closeout_status,
            previous_push_status=previous_closeout.push_status,
            previous_push_required=previous_closeout.push_required,
        )
    
    # 如果要求 push complete，检查 push 状态
    if require_push_complete and previous_closeout.push_required:
        if previous_closeout.push_status != "pushed":
            return CloseoutGateResult(
                allowed=False,
                reason=f"Previous batch {previous_batch_id} requires push but push_status={previous_closeout.push_status}",
                previous_batch_id=previous_batch_id,
                previous_closeout_status=previous_closeout.closeout_status,
                previous_push_status=previous_closeout.push_status,
                previous_push_required=previous_closeout.push_required,
            )
    
    # 检查通过，允许继续
    return CloseoutGateResult(
        allowed=True,
        reason=f"Previous batch {previous_batch_id} closeout gate passed",
        previous_batch_id=previous_batch_id,
        previous_closeout_status=previous_closeout.closeout_status,
        previous_push_status=previous_closeout.push_status,
        previous_push_required=previous_closeout.push_required,
    )
# ========== End P0-4 Batch 2 ==========


# ========== P0-4 Final Mile: Push Consumer / Status Backfill ==========
# 补上 push consumer 和 push_status 自动回填机制

def _push_action_file(batch_id: str) -> Path:
    """返回 push action 文件路径"""
    safe_batch_id = batch_id.replace("/", "_").replace(" ", "_")
    return CLOSEOUT_DIR / f"push-action-{safe_batch_id}.json"


def emit_push_action(
    batch_id: str,
    closeout_id: str,
    intent: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> PushAction:
    """
    P0-4 Final Mile: Emit Push Action
    
    当 closeout_status=complete 且 push_required=true 时，生成标准化的 push action。
    
    Args:
        batch_id: 批次 ID
        closeout_id: closeout ID
        intent: push 意图描述（默认根据场景生成）
        metadata: 额外元数据
    
    Returns:
        PushAction（已写入文件）
    
    状态流转：
    - emitted: push action 已生成，等待消费
    - 此时 closeout.push_status 仍为 "pending"
    
    注意：
    - 这只是生成 push action 记录，不执行真实 push
    - 真实 push 由上层 consumer 调用 execute_push 或 simulate_push_success
    """
    _ensure_closeout_dir()
    
    # 生成 action ID
    import uuid
    action_id = f"push_{uuid.uuid4().hex[:12]}"
    
    # 默认 intent
    if not intent:
        intent = f"Git push for batch {batch_id} closeout"
    
    # 创建 push action
    push_action = PushAction(
        action_id=action_id,
        batch_id=batch_id,
        closeout_id=closeout_id,
        status="emitted",
        intent=intent,
        metadata=metadata or {},
    )
    
    # 写入文件
    action_path = _push_action_file(batch_id)
    _atomic_json_write(action_path, push_action.to_dict())
    
    # 更新 closeout artifact 中的 push_action 引用
    closeout = get_closeout(batch_id)
    if closeout:
        closeout.push_action = push_action
        closeout.write()
    
    return push_action


def consume_push_action(
    batch_id: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> PushAction:
    """
    P0-4 Final Mile: Consume Push Action
    
    消费 push action，记录 intent（表示已准备执行，但尚未执行）。
    
    Args:
        batch_id: 批次 ID
        metadata: 额外元数据
    
    Returns:
        PushAction（已更新状态）
    
    状态流转：
    - emitted -> consumed: push action 已消费，intent 已记录
    - 此时 closeout.push_status 仍为 "pending"
    
    注意：
    - 这只是记录消费 intent，不执行真实 push
    - 真实 push 需要调用 execute_push 或 simulate_push_success
    """
    # 读取 push action
    action_path = _push_action_file(batch_id)
    if not action_path.exists():
        raise ValueError(f"Push action for batch {batch_id} not found")
    
    with open(action_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    push_action = PushAction.from_dict(data)
    
    # 检查状态
    if push_action.status != "emitted":
        raise ValueError(f"Push action status is {push_action.status}, expected 'emitted'")
    
    # 更新状态为 consumed
    push_action.status = "consumed"
    push_action.metadata = {**push_action.metadata, **(metadata or {})}
    
    # 写入文件
    _atomic_json_write(action_path, push_action.to_dict())
    
    # 更新 closeout artifact
    closeout = get_closeout(batch_id)
    if closeout:
        closeout.push_action = push_action
        closeout.write()
    
    return push_action


def update_push_status(
    batch_id: str,
    new_status: PushStatus,
    push_action_status: Optional[PushActionStatus] = None,
    error: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> CloseoutArtifact:
    """
    P0-4 Final Mile: Update Push Status
    
    更新 closeout 的 push_status（回填机制）。
    
    Args:
        batch_id: 批次 ID
        new_status: 新的 push status
        push_action_status: 同时更新 push action 状态（可选）
        error: 错误信息（如果失败）
        metadata: 额外元数据
    
    Returns:
        CloseoutArtifact（已更新）
    
    状态流转：
    - pending -> pushed: push 成功，状态回填
    - pending -> blocked: push 被阻止
    - pending -> failed: push 失败
    
    注意：
    - 这是受控回填函数，不执行真实 push
    - 真实 push 成功后调用此函数回填状态
    - 也可以用于模拟 push 成功（测试用）
    """
    # 读取 closeout
    closeout = get_closeout(batch_id)
    if not closeout:
        raise ValueError(f"Closeout for batch {batch_id} not found")
    
    # 更新 push status
    old_status = closeout.push_status
    closeout.push_status = new_status
    
    # 更新 push action（如果有）
    if closeout.push_action:
        if push_action_status:
            closeout.push_action.status = push_action_status
        if error:
            closeout.push_action.error = error
        if new_status == "pushed":
            closeout.push_action.executed_at = _iso_now()
        closeout.push_action.metadata = {**closeout.push_action.metadata, **(metadata or {})}
    
    # 更新 metadata
    closeout.metadata["push_status_updated_at"] = _iso_now()
    closeout.metadata["push_status_old"] = old_status
    closeout.metadata["push_status_new"] = new_status
    if error:
        closeout.metadata["push_error"] = error
    if metadata:
        closeout.metadata.update(metadata)
    
    # 写入文件
    closeout.write()
    
    # 更新 push action 文件（如果有）
    if closeout.push_action:
        action_path = _push_action_file(batch_id)
        _atomic_json_write(action_path, closeout.push_action.to_dict())
    
    return closeout


def simulate_push_success(
    batch_id: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> CloseoutArtifact:
    """
    P0-4 Final Mile: Simulate Push Success
    
    受控模拟 push 成功，用于测试闭环（不真实 push 远端）。
    
    Args:
        batch_id: 批次 ID
        metadata: 额外元数据
    
    Returns:
        CloseoutArtifact（已更新为 pushed 状态）
    
    状态流转：
    - push_status: pending -> pushed
    - push_action: emitted/consumed -> executed
    
    注意：
    - 这只是模拟 push 成功，不执行真实 git push
    - 用于测试内部自动推进闭环
    - 状态必须诚实：metadata 中会标记 "simulated": true
    """
    # 读取 closeout
    closeout = get_closeout(batch_id)
    if not closeout:
        raise ValueError(f"Closeout for batch {batch_id} not found")
    
    # 检查是否允许模拟（只有 pending 状态才能模拟）
    if closeout.push_status not in ("pending", "consumed"):
        raise ValueError(f"Cannot simulate push: current status is {closeout.push_status}")
    
    # 准备 metadata（标记为模拟）
    sim_metadata = metadata or {}
    sim_metadata["simulated"] = True
    sim_metadata["simulated_at"] = _iso_now()
    sim_metadata["simulation_note"] = "This is a simulated push success for testing; no real git push was performed"
    
    # 更新状态
    return update_push_status(
        batch_id=batch_id,
        new_status="pushed",
        push_action_status="executed",
        metadata=sim_metadata,
    )


def get_push_action(batch_id: str) -> Optional[PushAction]:
    """
    P0-4 Final Mile: Get Push Action
    
    获取 batch 的 push action 记录。
    
    Args:
        batch_id: 批次 ID
    
    Returns:
        PushAction，不存在则返回 None
    """
    action_path = _push_action_file(batch_id)
    if not action_path.exists():
        return None
    
    with open(action_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    return PushAction.from_dict(data)


def check_push_consumer_status(batch_id: str) -> Dict[str, Any]:
    """
    P0-4 Final Mile: Check Push Consumer Status
    
    检查 push consumer 的完整状态（closeout + push action）。
    
    Args:
        batch_id: 批次 ID
    
    Returns:
        {
            "closeout_status": CloseoutStatus,
            "push_status": PushStatus,
            "push_required": bool,
            "push_action_status": PushActionStatus | None,
            "push_action_exists": bool,
            "can_auto_continue": bool,  # 是否允许自动继续
            "blocker": str | None,
        }
    """
    closeout = get_closeout(batch_id)
    
    if not closeout:
        return {
            "closeout_status": "incomplete",
            "push_status": "not_required",
            "push_required": False,
            "push_action_status": None,
            "push_action_exists": False,
            "can_auto_continue": True,  # 没有 closeout 视为首次运行
            "blocker": None,
        }
    
    push_action = closeout.push_action
    push_action_status = push_action.status if push_action else None
    
    # 判断是否允许自动继续
    can_auto_continue = False
    blocker = None
    
    if closeout.closeout_status == "blocked":
        blocker = f"Closeout blocked: {closeout.metadata.get('closeout_reason', 'unknown')}"
    elif closeout.closeout_status == "incomplete":
        blocker = f"Closeout incomplete: {closeout.metadata.get('closeout_reason', 'unknown')}"
    elif closeout.push_required and closeout.push_status != "pushed":
        blocker = f"Push required but status={closeout.push_status}"
    else:
        can_auto_continue = True
    
    return {
        "closeout_status": closeout.closeout_status,
        "push_status": closeout.push_status,
        "push_required": closeout.push_required,
        "push_action_status": push_action_status,
        "push_action_exists": push_action is not None,
        "can_auto_continue": can_auto_continue,
        "blocker": blocker,
        "closeout_id": closeout.closeout_id,
        "push_action_id": push_action.action_id if push_action else None,
    }


# ========== End P0-4 Final Mile ==========


# CLI 入口
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python closeout_tracker.py get <batch_id>")
        print("  python closeout_tracker.py check-push <batch_id>")
        print("  python closeout_tracker.py check-consumer <batch_id>")
        print("  python closeout_tracker.py emit-push <batch_id>")
        print("  python closeout_tracker.py consume-push <batch_id>")
        print("  python closeout_tracker.py simulate-push <batch_id>")
        print("  python closeout_tracker.py list")
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == "get":
        if len(sys.argv) < 3:
            print("Error: missing batch_id")
            sys.exit(1)
        
        batch_id = sys.argv[2]
        artifact = get_closeout(batch_id)
        if artifact:
            print(json.dumps(artifact.to_dict(), indent=2))
        else:
            print(f"Closeout for batch {batch_id} not found")
            sys.exit(1)
    
    elif cmd == "check-push":
        if len(sys.argv) < 3:
            print("Error: missing batch_id")
            sys.exit(1)
        
        batch_id = sys.argv[2]
        result = check_push_required(batch_id)
        print(json.dumps(result, indent=2))
    
    elif cmd == "check-consumer":
        # P0-4 Final Mile: Check push consumer status
        if len(sys.argv) < 3:
            print("Error: missing batch_id")
            sys.exit(1)
        
        batch_id = sys.argv[2]
        result = check_push_consumer_status(batch_id)
        print(json.dumps(result, indent=2))
    
    elif cmd == "emit-push":
        # P0-4 Final Mile: Emit push action
        if len(sys.argv) < 3:
            print("Error: missing batch_id")
            sys.exit(1)
        
        batch_id = sys.argv[2]
        closeout = get_closeout(batch_id)
        if not closeout:
            print(f"Closeout for batch {batch_id} not found")
            sys.exit(1)
        
        action = emit_push_action(batch_id, closeout.closeout_id)
        print(json.dumps(action.to_dict(), indent=2))
    
    elif cmd == "consume-push":
        # P0-4 Final Mile: Consume push action
        if len(sys.argv) < 3:
            print("Error: missing batch_id")
            sys.exit(1)
        
        batch_id = sys.argv[2]
        try:
            action = consume_push_action(batch_id)
            print(json.dumps(action.to_dict(), indent=2))
        except ValueError as e:
            print(f"Error: {e}")
            sys.exit(1)
    
    elif cmd == "simulate-push":
        # P0-4 Final Mile: Simulate push success (for testing)
        if len(sys.argv) < 3:
            print("Error: missing batch_id")
            sys.exit(1)
        
        batch_id = sys.argv[2]
        try:
            closeout = simulate_push_success(batch_id)
            print(json.dumps(closeout.to_dict(), indent=2))
        except ValueError as e:
            print(f"Error: {e}")
            sys.exit(1)
    
    elif cmd == "list":
        _ensure_closeout_dir()
        closeouts = []
        for closeout_file in CLOSEOUT_DIR.glob("closeout-*.json"):
            with open(closeout_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            closeouts.append({
                "batch_id": data.get("batch_id"),
                "closeout_status": data.get("closeout_status"),
                "push_status": data.get("push_status"),
                "push_required": data.get("push_required"),
                "created_at": data.get("created_at"),
            })
        
        print(json.dumps(closeouts, indent=2))
    
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
