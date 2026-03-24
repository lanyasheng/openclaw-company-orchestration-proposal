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
]

CLOSEOUT_TRACKER_VERSION = "closeout_tracker_v1"

# Closeout 存储目录
CLOSEOUT_DIR = STATE_DIR.parent / "orchestrator" / "closeouts"

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
    - metadata: 额外元数据
    """
    closeout_id: str
    batch_id: str
    closeout_status: CloseoutStatus
    push_status: PushStatus
    push_required: bool
    continuation_contract: ContinuationContract
    artifacts: Dict[str, str] = field(default_factory=dict)
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
            "metadata": self.metadata,
            "created_at": self.created_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CloseoutArtifact":
        return cls(
            closeout_id=data.get("closeout_id", ""),
            batch_id=data.get("batch_id", ""),
            closeout_status=data.get("closeout_status", "incomplete"),
            push_status=data.get("push_status", "pending"),
            push_required=data.get("push_required", False),
            continuation_contract=ContinuationContract.from_dict(data.get("continuation_contract", {})),
            artifacts=data.get("artifacts", {}),
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


# CLI 入口
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python closeout_tracker.py get <batch_id>")
        print("  python closeout_tracker.py check-push <batch_id>")
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
