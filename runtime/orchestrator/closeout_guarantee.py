#!/usr/bin/env python3
"""
closeout_guarantee.py — User-Visible Closeout Guarantee

目标：解决"子任务完成了，但老板/父会话没有及时收到统一汇报"的 last-mile 问题。

核心设计：
1. 区分 internal completion 与 user-visible closeout
2. completion 到达后，如果父层没有在约定条件下形成 final closeout，生成可审计的兜底 receipt
3. 明确的状态位，避免把"完成事件已到达"误判成"用户已感知完成"

这是薄层、可回退的改法，不大拆架构。

状态定义：
- internal_completed: 内部完成事件已到达（callback 已处理）
- ack_delivered: ack message 已发送（Discord 消息已投递）
- user_visible_closeout: 用户可见闭环已形成（用户已感知完成）

兜底规则：
- 如果 ack_status != "sent" 且 dispatch_status != "triggered"，生成兜底 receipt
- 兜底 receipt 包含明确的 blocker 和 next_action
- 兜底 receipt 落盘到 closeout_guarantee 目录，可审计
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Literal, Optional

from state_machine import STATE_DIR, _iso_now

__all__ = [
    "CloseoutGuaranteeStatus",
    "CloseoutGuaranteeArtifact",
    "CloseoutGuaranteeKernel",
    "check_closeout_guarantee",
    "emit_closeout_guarantee",
    "GUARANTEE_VERSION",
]

GUARANTEE_VERSION = "closeout_guarantee_v1"

CloseoutGuaranteeStatus = Literal[
    "guaranteed",       # 兜底已生成（用户可见闭环已形成）
    "pending",          # 等待父层 closeout
    "fallback_needed",  # 需要兜底（父层未及时 closeout）
    "blocked",          # 兜底被阻止
]

# Closeout guarantee 存储目录
CLOSEOUT_GUARANTEE_DIR = Path(
    os.environ.get(
        "OPENCLAW_CLOSEOUT_GUARANTEE_DIR",
        STATE_DIR.parent / "orchestrator" / "closeout_guarantees",
    )
)

# Guarantee index（支持查询）
GUARANTEE_INDEX_FILE = CLOSEOUT_GUARANTEE_DIR / "guarantee_index.json"


def _ensure_guarantee_dir() -> None:
    """确保 guarantee 目录存在"""
    CLOSEOUT_GUARANTEE_DIR.mkdir(parents=True, exist_ok=True)


def _guarantee_file(batch_id: str) -> Path:
    """返回 guarantee artifact 文件路径"""
    safe_batch_id = batch_id.replace("/", "_").replace(" ", "_")
    return CLOSEOUT_GUARANTEE_DIR / f"guarantee-{safe_batch_id}.json"


def _atomic_json_write(file_path: Path, payload: Dict[str, Any]) -> None:
    """原子写入 JSON 文件"""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_file = file_path.with_suffix(file_path.suffix + ".tmp")
    with open(tmp_file, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    tmp_file.replace(file_path)


def _generate_guarantee_id() -> str:
    """生成 stable guarantee ID"""
    import uuid
    return f"guarantee_{uuid.uuid4().hex[:12]}"


def _load_guarantee_index() -> Dict[str, str]:
    """加载 guarantee index（batch_id -> guarantee_id 映射）"""
    _ensure_guarantee_dir()
    if not GUARANTEE_INDEX_FILE.exists():
        return {}
    
    try:
        with open(GUARANTEE_INDEX_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, KeyError):
        return {}


def _save_guarantee_index(index: Dict[str, str]) -> None:
    """保存 guarantee index"""
    _ensure_guarantee_dir()
    tmp_file = GUARANTEE_INDEX_FILE.with_suffix(".tmp")
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    tmp_file.replace(GUARANTEE_INDEX_FILE)


@dataclass
class CloseoutGuaranteeArtifact:
    """
    Closeout guarantee artifact — 记录 user-visible closeout 保证状态。
    
    核心字段：
    - guarantee_id: Guarantee ID
    - batch_id: 批次 ID
    - guarantee_status: guarantee 状态
    - internal_completed: 内部完成事件是否已到达
    - ack_delivered: ack message 是否已发送
    - user_visible_closeout: 用户可见闭环是否已形成
    - fallback_triggered: 是否触发了兜底机制
    - fallback_reason: 兜底触发原因
    - artifacts: 相关 artifact 路径（ack_receipt/closeout_artifact 等）
    - metadata: 额外元数据
    
    P0-4 Batch 4: Failure Closeout Guarantee 新增字段（通过 metadata 传递）：
    - failure_summary: 失败摘要（人类可读）
    - failure_stage: 失败阶段（planning | execution | closeout | callback）
    - truth_anchor: 真值锚点（机器可读的状态证据）
    - fallback_action: 兜底行动建议
    - user_visible_failure_closeout: 用户是否已感知失败（区分于成功场景的 user_visible_closeout）
    """
    guarantee_id: str
    batch_id: str
    guarantee_status: CloseoutGuaranteeStatus
    internal_completed: bool
    ack_delivered: bool
    user_visible_closeout: bool
    fallback_triggered: bool = False
    fallback_reason: Optional[str] = None
    artifacts: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: _iso_now())
    
    # ========== P0-4 Batch 4: Failure Closeout Fields (via metadata) ==========
    @property
    def failure_summary(self) -> Optional[str]:
        """失败摘要（人类可读）"""
        return self.metadata.get("failure_summary")
    
    @property
    def failure_stage(self) -> Optional[str]:
        """失败阶段（planning | execution | closeout | callback）"""
        return self.metadata.get("failure_stage")
    
    @property
    def truth_anchor(self) -> Optional[str]:
        """真值锚点（机器可读的状态证据）"""
        return self.metadata.get("truth_anchor")
    
    @property
    def fallback_action(self) -> Optional[str]:
        """兜底行动建议"""
        return self.metadata.get("fallback_action")
    
    @property
    def user_visible_failure_closeout(self) -> bool:
        """用户是否已感知失败（区分于成功场景的 user_visible_closeout）"""
        return self.metadata.get("user_visible_failure_closeout", False)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "guarantee_version": GUARANTEE_VERSION,
            "guarantee_id": self.guarantee_id,
            "batch_id": self.batch_id,
            "guarantee_status": self.guarantee_status,
            "internal_completed": self.internal_completed,
            "ack_delivered": self.ack_delivered,
            "user_visible_closeout": self.user_visible_closeout,
            "fallback_triggered": self.fallback_triggered,
            "fallback_reason": self.fallback_reason,
            "artifacts": self.artifacts,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CloseoutGuaranteeArtifact":
        return cls(
            guarantee_id=data.get("guarantee_id", ""),
            batch_id=data.get("batch_id", ""),
            guarantee_status=data.get("guarantee_status", "pending"),
            internal_completed=data.get("internal_completed", False),
            ack_delivered=data.get("ack_delivered", False),
            user_visible_closeout=data.get("user_visible_closeout", False),
            fallback_triggered=data.get("fallback_triggered", False),
            fallback_reason=data.get("fallback_reason"),
            artifacts=data.get("artifacts", {}),
            metadata=data.get("metadata", {}),
            created_at=data.get("created_at", _iso_now()),
        )
    
    def write(self) -> Path:
        _ensure_guarantee_dir()
        guarantee_path = _guarantee_file(self.batch_id)
        _atomic_json_write(guarantee_path, self.to_dict())

        index = _load_guarantee_index()
        index[self.batch_id] = self.guarantee_id
        _save_guarantee_index(index)

        try:
            from workflow_state_store import get_store
            store = get_store()
            if store.is_active:
                store.update_batch(self.batch_id, continuation={
                    "stopped_because": f"guarantee_{self.guarantee_status}",
                    "decision": "stop" if self.guarantee_status == "fallback_needed" else "proceed",
                    "next_batch": None,
                    "decided_at": self.guarantee_time,
                })
        except Exception:
            pass

        return guarantee_path


class CloseoutGuaranteeKernel:
    """
    Closeout guarantee kernel — 管理 user-visible closeout 保证。
    
    提供：
    - check_guarantee(): 检查 guarantee 状态
    - emit_guarantee(): emit guarantee artifact
    - update_guarantee(): 更新 guarantee 状态
    """
    
    def __init__(self):
        pass
    
    def _determine_guarantee_status(
        self,
        ack_status: str,
        delivery_status: str,
        dispatch_status: str,
        has_user_visible_closeout: bool,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> tuple[CloseoutGuaranteeStatus, str]:
        """
        根据 ack/delivery/dispatch 状态决定 guarantee status。
        
        规则：
        1. 如果 user_visible_closeout=True，返回 "guaranteed"
        2. 如果 ack_status="sent" 且 delivery_status="sent"，返回 "pending"（等待用户确认）
        3. 如果 ack_status!="sent" 且 dispatch_status!="triggered"，返回 "fallback_needed"
        4. 其他情况返回 "pending"
        
        P0-4 Batch 4: Failure Closeout Guarantee 增强：
        - 区分"任务失败已知"与"用户已感知失败"
        - 支持 failure_summary / failure_stage / truth_anchor / fallback_action 字段
        
        Returns:
            (guarantee_status, guarantee_reason)
        """
        metadata = metadata or {}
        
        # 用户可见闭环已形成（成功或失败场景都适用）
        if has_user_visible_closeout:
            # 检查是否是失败场景
            if metadata.get("failure_summary") or ack_status in ("fallback_recorded", "failed", "timeout"):
                return "guaranteed", "User-visible failure closeout confirmed"
            return "guaranteed", "User-visible closeout confirmed"
        
        # ack 已成功发送
        if ack_status == "sent" and delivery_status == "sent":
            return "pending", "Ack delivered; awaiting user confirmation"
        
        # dispatch 已触发，等待 continuation（不误报）
        if dispatch_status == "triggered":
            return "pending", "Dispatch triggered; awaiting continuation callback"
        
        # ========== P0-4 Batch 4: Failure Closeout Guarantee ==========
        # 需要兜底：ack 未发送 且 dispatch 未触发
        # 这包括：任务失败但用户未收到通知、subagent 崩溃、超时等场景
        if ack_status != "sent" and dispatch_status != "triggered":
            # 构建详细的 failure summary
            failure_summary = metadata.get("failure_summary")
            if failure_summary:
                return "fallback_needed", f"Failure closeout needed: {failure_summary}"
            
            # 默认 fallback reason
            return "fallback_needed", f"Ack not delivered (ack_status={ack_status}, dispatch_status={dispatch_status})"
        
        # 其他情况：ack 可能 fallback_recorded
        if ack_status == "fallback_recorded":
            failure_summary = metadata.get("failure_summary")
            if failure_summary:
                return "fallback_needed", f"Failure closeout needed: {failure_summary}"
            return "fallback_needed", "Ack fallback recorded; user-visible closeout not confirmed"
        
        # 默认 pending
        return "pending", f"Awaiting closeout confirmation (ack={ack_status}, delivery={delivery_status}, dispatch={dispatch_status})"
    
    def check_guarantee(
        self,
        batch_id: str,
        ack_status: Optional[str] = None,
        delivery_status: Optional[str] = None,
        dispatch_status: Optional[str] = None,
        has_user_visible_closeout: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> CloseoutGuaranteeArtifact:
        """
        检查 guarantee 状态。
        
        Args:
            batch_id: 批次 ID
            ack_status: ack 状态（可选）
            delivery_status: delivery 状态（可选）
            dispatch_status: dispatch 状态（可选）
            has_user_visible_closeout: 是否已有用户可见闭环
            metadata: 额外元数据（P0-4 Batch 4: 支持 failure_summary / failure_stage / truth_anchor / fallback_action）
        
        Returns:
            CloseoutGuaranteeArtifact
        """
        metadata = metadata or {}
        
        # 检查是否已存在 guarantee
        existing = self.get_guarantee(batch_id)
        
        if existing:
            # 如果已有 guarantee 且状态是 guaranteed，直接返回
            if existing.guarantee_status == "guaranteed":
                return existing
            
            # 否则更新状态
            if has_user_visible_closeout:
                existing.guarantee_status = "guaranteed"
                existing.user_visible_closeout = True
                existing.metadata["guaranteed_at"] = _iso_now()
                # 合并新 metadata
                existing.metadata.update(metadata)
                existing.write()
                return existing
        
        # 决定 guarantee status（传入 metadata）
        guarantee_status, guarantee_reason = self._determine_guarantee_status(
            ack_status=ack_status or "unknown",
            delivery_status=delivery_status or "unknown",
            dispatch_status=dispatch_status or "unknown",
            has_user_visible_closeout=has_user_visible_closeout,
            metadata=metadata,
        )
        
        # 创建新的 guarantee artifact
        guarantee_id = _generate_guarantee_id()
        
        # 构建完整的 metadata
        full_metadata = {
            "ack_status": ack_status,
            "delivery_status": delivery_status,
            "dispatch_status": dispatch_status,
            "guarantee_reason": guarantee_reason,
            **metadata,
        }
        
        artifact = CloseoutGuaranteeArtifact(
            guarantee_id=guarantee_id,
            batch_id=batch_id,
            guarantee_status=guarantee_status,
            internal_completed=True,  # 能调用 check_guarantee 说明 internal completion 已到达
            ack_delivered=(ack_status == "sent" and delivery_status == "sent"),
            user_visible_closeout=has_user_visible_closeout,
            fallback_triggered=(guarantee_status == "fallback_needed"),
            fallback_reason=guarantee_reason if guarantee_status == "fallback_needed" else None,
            metadata=full_metadata,
        )
        
        return artifact
    
    def emit_guarantee(
        self,
        batch_id: str,
        ack_status: str,
        delivery_status: str,
        dispatch_status: str,
        has_user_visible_closeout: bool = False,
        artifacts: Optional[Dict[str, str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> CloseoutGuaranteeArtifact:
        """
        Emit guarantee：创建 artifact -> 写入文件。
        
        Args:
            batch_id: 批次 ID
            ack_status: ack 状态
            delivery_status: delivery 状态
            dispatch_status: dispatch 状态
            has_user_visible_closeout: 是否已有用户可见闭环
            artifacts: artifact 路径字典
            metadata: 额外元数据（P0-4 Batch 4: 支持 failure_summary / failure_stage / truth_anchor / fallback_action）
        
        Returns:
            CloseoutGuaranteeArtifact（已写入文件）
        """
        artifact = self.check_guarantee(
            batch_id=batch_id,
            ack_status=ack_status,
            delivery_status=delivery_status,
            dispatch_status=dispatch_status,
            has_user_visible_closeout=has_user_visible_closeout,
            metadata=metadata,
        )
        
        # 更新 artifacts 和 metadata（check_guarantee 已经合并了 metadata）
        if artifacts:
            artifact.artifacts = {**artifact.artifacts, **artifacts}
        
        # 写入文件
        artifact.write()
        
        return artifact
    
    def get_guarantee(self, batch_id: str) -> Optional[CloseoutGuaranteeArtifact]:
        """
        获取已存在的 guarantee artifact。
        
        Args:
            batch_id: 批次 ID
        
        Returns:
            CloseoutGuaranteeArtifact，不存在则返回 None
        """
        guarantee_path = _guarantee_file(batch_id)
        if not guarantee_path.exists():
            return None
        
        with open(guarantee_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        return CloseoutGuaranteeArtifact.from_dict(data)
    
    def update_guarantee(
        self,
        batch_id: str,
        user_visible_closeout: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> CloseoutGuaranteeArtifact:
        """
        更新 guarantee 状态（标记用户可见闭环已形成）。
        
        Args:
            batch_id: 批次 ID
            user_visible_closeout: 是否形成用户可见闭环
            metadata: 额外元数据
        
        Returns:
            CloseoutGuaranteeArtifact（已更新）
        
        Raises:
            ValueError: 如果 guarantee 不存在
        """
        artifact = self.get_guarantee(batch_id)
        if not artifact:
            raise ValueError(f"Guarantee for batch {batch_id} not found")
        
        artifact.user_visible_closeout = user_visible_closeout
        if user_visible_closeout:
            artifact.guarantee_status = "guaranteed"
            artifact.metadata["guaranteed_at"] = _iso_now()
        
        if metadata:
            artifact.metadata = {**artifact.metadata, **metadata}
        
        artifact.write()
        return artifact


def check_closeout_guarantee(
    batch_id: str,
    ack_status: Optional[str] = None,
    delivery_status: Optional[str] = None,
    dispatch_status: Optional[str] = None,
    has_user_visible_closeout: bool = False,
    metadata: Optional[Dict[str, Any]] = None,
) -> CloseoutGuaranteeArtifact:
    """
    Convenience function: 检查 guarantee 状态。
    
    Args:
        batch_id: 批次 ID
        ack_status: ack 状态
        delivery_status: delivery 状态
        dispatch_status: dispatch 状态
        has_user_visible_closeout: 是否已有用户可见闭环
        metadata: 额外元数据（P0-4 Batch 4: 支持 failure_summary / failure_stage / truth_anchor / fallback_action）
    
    Returns:
        CloseoutGuaranteeArtifact
    """
    kernel = CloseoutGuaranteeKernel()
    return kernel.check_guarantee(
        batch_id=batch_id,
        ack_status=ack_status,
        delivery_status=delivery_status,
        dispatch_status=dispatch_status,
        has_user_visible_closeout=has_user_visible_closeout,
        metadata=metadata,
    )


def emit_closeout_guarantee(
    batch_id: str,
    ack_status: str,
    delivery_status: str,
    dispatch_status: str,
    has_user_visible_closeout: bool = False,
    artifacts: Optional[Dict[str, str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> CloseoutGuaranteeArtifact:
    """
    Convenience function: Emit guarantee artifact。
    
    Args:
        batch_id: 批次 ID
        ack_status: ack 状态
        delivery_status: delivery 状态
        dispatch_status: dispatch 状态
        has_user_visible_closeout: 是否已有用户可见闭环
        artifacts: artifact 路径字典
        metadata: 额外元数据
    
    Returns:
        CloseoutGuaranteeArtifact（已写入文件）
    """
    kernel = CloseoutGuaranteeKernel()
    return kernel.emit_guarantee(
        batch_id=batch_id,
        ack_status=ack_status,
        delivery_status=delivery_status,
        dispatch_status=dispatch_status,
        has_user_visible_closeout=has_user_visible_closeout,
        artifacts=artifacts,
        metadata=metadata,
    )


def get_closeout_guarantee(batch_id: str) -> Optional[CloseoutGuaranteeArtifact]:
    """
    Convenience function: 获取 guarantee artifact。
    
    Args:
        batch_id: 批次 ID
    
    Returns:
        CloseoutGuaranteeArtifact，不存在则返回 None
    """
    kernel = CloseoutGuaranteeKernel()
    return kernel.get_guarantee(batch_id)


def update_closeout_guarantee(
    batch_id: str,
    user_visible_closeout: bool = True,
    metadata: Optional[Dict[str, Any]] = None,
) -> CloseoutGuaranteeArtifact:
    """
    Convenience function: 更新 guarantee 状态。
    
    Args:
        batch_id: 批次 ID
        user_visible_closeout: 是否形成用户可见闭环
        metadata: 额外元数据
    
    Returns:
        CloseoutGuaranteeArtifact（已更新）
    """
    kernel = CloseoutGuaranteeKernel()
    return kernel.update_guarantee(
        batch_id=batch_id,
        user_visible_closeout=user_visible_closeout,
        metadata=metadata,
    )


# CLI 入口
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python closeout_guarantee.py check <batch_id> [--ack <status>] [--delivery <status>] [--dispatch <status>]")
        print("  python closeout_guarantee.py emit <batch_id> --ack <status> --delivery <status> --dispatch <status>")
        print("  python closeout_guarantee.py update <batch_id> --user-visible-closeout true")
        print("  python closeout_guarantee.py get <batch_id>")
        print("  python closeout_guarantee.py list")
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == "check":
        if len(sys.argv) < 3:
            print("Error: missing batch_id")
            sys.exit(1)
        
        batch_id = sys.argv[2]
        ack_status = None
        delivery_status = None
        dispatch_status = None
        
        i = 3
        while i < len(sys.argv):
            if sys.argv[i] == "--ack" and i + 1 < len(sys.argv):
                ack_status = sys.argv[i + 1]
                i += 2
            elif sys.argv[i] == "--delivery" and i + 1 < len(sys.argv):
                delivery_status = sys.argv[i + 1]
                i += 2
            elif sys.argv[i] == "--dispatch" and i + 1 < len(sys.argv):
                dispatch_status = sys.argv[i + 1]
                i += 2
            else:
                i += 1
        
        artifact = check_closeout_guarantee(
            batch_id=batch_id,
            ack_status=ack_status,
            delivery_status=delivery_status,
            dispatch_status=dispatch_status,
        )
        print(json.dumps(artifact.to_dict(), indent=2))
    
    elif cmd == "emit":
        if len(sys.argv) < 7:
            print("Error: missing required arguments")
            print("Usage: python closeout_guarantee.py emit <batch_id> --ack <status> --delivery <status> --dispatch <status>")
            sys.exit(1)
        
        batch_id = sys.argv[2]
        ack_status = None
        delivery_status = None
        dispatch_status = None
        
        i = 3
        while i < len(sys.argv):
            if sys.argv[i] == "--ack" and i + 1 < len(sys.argv):
                ack_status = sys.argv[i + 1]
                i += 2
            elif sys.argv[i] == "--delivery" and i + 1 < len(sys.argv):
                delivery_status = sys.argv[i + 1]
                i += 2
            elif sys.argv[i] == "--dispatch" and i + 1 < len(sys.argv):
                dispatch_status = sys.argv[i + 1]
                i += 2
            else:
                i += 1
        
        if not all([ack_status, delivery_status, dispatch_status]):
            print("Error: --ack, --delivery, and --dispatch are required")
            sys.exit(1)
        
        artifact = emit_closeout_guarantee(
            batch_id=batch_id,
            ack_status=ack_status,
            delivery_status=delivery_status,
            dispatch_status=dispatch_status,
        )
        print(json.dumps(artifact.to_dict(), indent=2))
    
    elif cmd == "update":
        if len(sys.argv) < 3:
            print("Error: missing batch_id")
            sys.exit(1)
        
        batch_id = sys.argv[2]
        user_visible_closeout = True
        
        i = 3
        while i < len(sys.argv):
            if sys.argv[i] == "--user-visible-closeout" and i + 1 < len(sys.argv):
                user_visible_closeout = sys.argv[i + 1].lower() in ("true", "1", "yes")
                i += 2
            else:
                i += 1
        
        try:
            artifact = update_closeout_guarantee(
                batch_id=batch_id,
                user_visible_closeout=user_visible_closeout,
            )
            print(json.dumps(artifact.to_dict(), indent=2))
        except ValueError as e:
            print(f"Error: {e}")
            sys.exit(1)
    
    elif cmd == "get":
        if len(sys.argv) < 3:
            print("Error: missing batch_id")
            sys.exit(1)
        
        batch_id = sys.argv[2]
        artifact = get_closeout_guarantee(batch_id)
        if artifact:
            print(json.dumps(artifact.to_dict(), indent=2))
        else:
            print(f"Guarantee for batch {batch_id} not found")
            sys.exit(1)
    
    elif cmd == "list":
        _ensure_guarantee_dir()
        guarantees = []
        for guarantee_file in CLOSEOUT_GUARANTEE_DIR.glob("guarantee-*.json"):
            with open(guarantee_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            guarantees.append({
                "batch_id": data.get("batch_id"),
                "guarantee_id": data.get("guarantee_id"),
                "guarantee_status": data.get("guarantee_status"),
                "user_visible_closeout": data.get("user_visible_closeout"),
                "fallback_triggered": data.get("fallback_triggered"),
                "created_at": data.get("created_at"),
            })
        
        print(json.dumps(guarantees, indent=2))
    
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
