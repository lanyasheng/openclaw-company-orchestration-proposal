#!/usr/bin/env python3
"""
closeout_state.py — Closeout data types and file I/O helpers.

Extracted from closeout_tracker.py to reduce module size.
Contains:
- Type aliases (CloseoutStatus, PushStatus, PushActionStatus)
- Dataclasses (PushAction, CloseoutArtifact, CloseoutGateResult)
- File I/O helpers (_ensure_closeout_dir, _closeout_file, _atomic_json_write, etc.)
- Heartbeat boundary guard functions
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Literal, Optional

from state_machine import STATE_DIR, _iso_now

__all__ = [
    "CLOSEOUT_TRACKER_VERSION",
    "CLOSEOUT_DIR",
    "CloseoutStatus",
    "PushStatus",
    "PushActionStatus",
    "PushAction",
    "CloseoutArtifact",
    "CloseoutGateResult",
    # File I/O helpers
    "_ensure_closeout_dir",
    "_closeout_file",
    "_atomic_json_write",
    "_push_action_file",
    # Heartbeat boundary guard
    "_CLOSEOUT_EMIT_CALLER_ALLOWLIST",
    "_assert_closeout_emit_allowed",
    "_get_caller_module",
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


# ========== HEARTBEAT BOUNDARY GUARD (P0-2 Batch 2) ==========

_CLOSEOUT_EMIT_CALLER_ALLOWLIST = {
    "trading_roundtable",
    "channel_roundtable",
    "orchestrator",
    "closeout_generator",
    "closeout_tracker",  # This module itself
    "partial_continuation",
    "test_",  # Test modules are allowed
}
"""
Modules that are allowed to call emit_closeout() and create_closeout().
Heartbeat paths (waiting_guard, heartbeat, liveness, guardian) are NOT in this list.
"""


def _assert_closeout_emit_allowed(caller_module: str) -> None:
    """
    Assert that the caller module is allowed to emit closeout.

    HEARTBEAT BOUNDARY GUARD (P0-2 Batch 2):
    - This function checks if the caller is in the allowlist.
    - Heartbeat paths are NOT allowed to emit closeout directly.

    Args:
        caller_module: The name of the calling module

    Raises:
        ValueError: If the caller is not in the allowlist
    """
    for allowed in _CLOSEOUT_EMIT_CALLER_ALLOWLIST:
        if allowed in caller_module:
            return

    raise ValueError(
        f"Heartbeat boundary violation: module '{caller_module}' is not allowed to emit closeout. "
        f"Heartbeat paths can only DETECT anomalies and NUDGE owners to emit closeout. "
        f"Allowed modules: {_CLOSEOUT_EMIT_CALLER_ALLOWLIST}. "
        f"See: docs/policies/heartbeat-boundary-policy.md"
    )


def _get_caller_module(level: int = 2) -> str:
    """
    Get the name of the calling module.

    Args:
        level: Stack level to inspect (default: 2 = direct caller)

    Returns:
        Module name of the caller
    """
    import inspect
    frame = inspect.stack()[level]
    module = inspect.getmodule(frame[0])
    return module.__name__ if module else "unknown"


# ========== File I/O helpers ==========


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


def _push_action_file(batch_id: str) -> Path:
    """返回 push action 文件路径"""
    safe_batch_id = batch_id.replace("/", "_").replace(" ", "_")
    return CLOSEOUT_DIR / f"push-action-{safe_batch_id}.json"


# ========== Dataclasses ==========


@dataclass
class PushAction:
    """
    P0-4 Final Mile: Push Action — 标准化的 push action 记录。
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
    """
    closeout_id: str
    batch_id: str
    closeout_status: CloseoutStatus
    push_status: PushStatus
    push_required: bool
    continuation_contract: Any  # ContinuationContract (avoid circular import)
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
        from partial_continuation import ContinuationContract
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
        _ensure_closeout_dir()
        closeout_path = _closeout_file(self.batch_id)
        _atomic_json_write(closeout_path, self.to_dict())
        try:
            from workflow_state_store import get_store
            store = get_store()
            if store.is_active:
                store.update_batch(self.batch_id, continuation={
                    "stopped_because": f"closeout_{self.closeout_status}",
                    "decision": "proceed" if self.closeout_status == "completed" else "stop",
                    "next_batch": None,
                    "decided_at": self.closeout_time,
                })
        except Exception:
            import logging as _logging
            _logging.getLogger(__name__).warning(
                "workflow_state_store sync failed for batch %s", self.batch_id, exc_info=True,
            )
        return closeout_path


@dataclass
class CloseoutGateResult:
    """
    Closeout gate 检查结果
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
