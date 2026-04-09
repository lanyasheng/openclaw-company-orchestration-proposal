#!/usr/bin/env python3
"""
task_registration.py — Continuation Kernel Registration Ledger (Layer 2)

JSONL-based persistent registration ledger for the Continuation Kernel.
Records registration → dispatch → spawn → receipt → callback linkage.

Boundary note:
  - THIS module: JSONL ledger for Continuation Kernel artifact chain.
    Used by auto_dispatch, spawn_closure, completion_receipt, etc.
  - core/task_registry.py: in-memory structured registry for Layer 1
    (callback-driven orchestrator rule chain / batch_aggregator).
  Both coexist intentionally — they serve different layers.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

__all__ = [
    "RegistrationStatus",
    "TaskRegistrationRecord",
    "TaskRegistry",
    "RegistrationLedger",
    "register_task",
    "get_registration",
    "list_registrations",
    "get_registrations_by_source",
    "get_registrations_by_readiness",
    "get_registrations_by_truth_anchor",
    "register_from_handoff",
    "TASK_REGISTRY_VERSION",
]

TASK_REGISTRY_VERSION = "task_registration_v1"

# P0-2 Batch 1: 导入 handoff schema helper (lazy import to avoid circular dependency)
def _get_handoff_helpers():
    """Lazy import helper to avoid circular dependency issues"""
    from core.handoff_schema import RegistrationHandoff, handoff_to_task_registration
    return RegistrationHandoff, handoff_to_task_registration

RegistrationStatus = Literal["registered", "skipped", "blocked"]

# 注册表存储目录
REGISTRY_DIR = Path(
    os.environ.get(
        "OPENCLAW_REGISTRY_DIR",
        Path.home() / ".openclaw" / "shared-context" / "task-registry",
    )
)


def _ensure_registry_dir():
    """确保注册表目录存在"""
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)


def _registry_file() -> Path:
    """返回注册表文件路径"""
    return REGISTRY_DIR / "registry.jsonl"


def _registration_file(registration_id: str) -> Path:
    """返回单个注册记录文件路径"""
    return REGISTRY_DIR / f"{registration_id}.json"


def _iso_now() -> str:
    """返回当前 ISO-8601 时间戳"""
    return datetime.now(timezone.utc).isoformat()


def _generate_task_id(prefix: str = "task") -> str:
    """生成稳定 task ID"""
    import uuid
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _generate_batch_id() -> str:
    """生成稳定 batch ID"""
    import uuid
    return f"batch_{uuid.uuid4().hex[:12]}"


@dataclass
class TruthAnchor:
    """
    真值锚点：用于标识注册记录的来源 linkage。
    
    核心字段：
    - anchor_type: task_id | batch_id | branch | commit | push
    - anchor_value: 锚点值
    - metadata: 额外元数据
    """
    anchor_type: Literal["task_id", "batch_id", "branch", "commit", "push"]
    anchor_value: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "anchor_type": self.anchor_type,
            "anchor_value": self.anchor_value,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TruthAnchor":
        return cls(
            anchor_type=data.get("anchor_type", "task_id"),
            anchor_value=data.get("anchor_value", ""),
            metadata=data.get("metadata", {}),
        )


@dataclass
class TaskRegistrationRecord:
    """
    Task registration record — 真实注册记录（可落盘）。
    
    核心字段：
    - registration_id: 注册记录 ID
    - task_id: 新生成的任务 ID（稳定）
    - batch_id: 所属批次 ID（可选）
    - registration_status: registered | skipped | blocked
    - registration_reason: 注册/跳过/阻止的原因
    - truth_anchor: 来源 linkage（source task/batch）
    - owner: 任务所有者（可选）
    - status: 任务状态（pending | in_progress | completed | blocked）
    - source_closeout: 来源 partial closeout contract（可选）
    - proposed_task: 提议的任务内容
    - metadata: 额外元数据
    
    这是 canonical artifact，operator/main 可以继续消费。
    """
    registration_id: str
    task_id: str
    batch_id: Optional[str]
    registration_status: RegistrationStatus
    registration_reason: str
    truth_anchor: Optional[TruthAnchor]
    owner: Optional[str]
    status: Literal["pending", "in_progress", "completed", "blocked"]
    source_closeout: Optional[Dict[str, Any]]
    proposed_task: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "registry_version": TASK_REGISTRY_VERSION,
            "registration_id": self.registration_id,
            "task_id": self.task_id,
            "batch_id": self.batch_id,
            "registration_status": self.registration_status,
            "registration_reason": self.registration_reason,
            "truth_anchor": self.truth_anchor.to_dict() if self.truth_anchor else None,
            "owner": self.owner,
            "status": self.status,
            "source_closeout": self.source_closeout,
            "proposed_task": self.proposed_task,
            "metadata": self.metadata,
            "registered_at": self.metadata.get("registered_at"),
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskRegistrationRecord":
        return cls(
            registration_id=data.get("registration_id", ""),
            task_id=data.get("task_id", ""),
            batch_id=data.get("batch_id"),
            registration_status=data.get("registration_status", "registered"),
            registration_reason=data.get("registration_reason", ""),
            truth_anchor=(
                TruthAnchor.from_dict(data.get("truth_anchor"))
                if data.get("truth_anchor")
                else None
            ),
            owner=data.get("owner"),
            status=data.get("status", "pending"),
            source_closeout=data.get("source_closeout"),
            proposed_task=data.get("proposed_task", {}),
            metadata=data.get("metadata", {}),
        )
    
    @property
    def ready_for_auto_dispatch(self) -> bool:
        """
        是否准备好自动 dispatch。
        
        规则：
        - registration_status = registered AND
        - status = pending AND
        - metadata.ready_for_auto_dispatch = true (可选)
        """
        if self.registration_status != "registered":
            return False
        if self.status != "pending":
            return False
        return self.metadata.get("ready_for_auto_dispatch", False)


class TaskRegistry:
    """
    Task registry — 统一任务注册表（ledger）。
    
    提供：
    - register(): 注册新任务
    - get(): 获取注册记录
    - list(): 列出注册记录
    - get_by_source(): 按来源查询
    - update_status(): 更新任务状态
    """
    
    def __init__(self):
        _ensure_registry_dir()
    
    def _read_registry(self) -> List[Dict[str, Any]]:
        """读取注册表（JSONL 格式）"""
        registry_file = _registry_file()
        if not registry_file.exists():
            return []
        
        records = []
        with open(registry_file, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return records
    
    def _write_registry(self, records: List[Dict[str, Any]]):
        """写入注册表（原子写入）"""
        registry_file = _registry_file()
        tmp_file = registry_file.with_suffix(".tmp")
        
        with open(tmp_file, "w") as f:
            for record in records:
                f.write(json.dumps(record) + "\n")
        
        tmp_file.replace(registry_file)
    
    def register(
        self,
        record: TaskRegistrationRecord,
    ) -> TaskRegistrationRecord:
        """
        注册新任务记录。
        
        Args:
            record: 注册记录
        
        Returns:
            注册记录（含 updated metadata）
        """
        # 添加注册时间戳
        record.metadata["registered_at"] = _iso_now()
        
        record_file = _registration_file(record.registration_id)
        tmp_file = record_file.with_suffix(".tmp")
        with open(tmp_file, "w") as f:
            json.dump(record.to_dict(), f, indent=2)
        tmp_file.replace(record_file)

        records = self._read_registry()
        records.append(record.to_dict())
        self._write_registry(records)

        try:
            from workflow_state_store import get_store
            store = get_store()
            if store.is_active and record.task_id:
                store.update_task(
                    record.task_id,
                    execution_metadata={
                        "registration_id": record.registration_id,
                        "registration_status": record.registration_status,
                    },
                )
        except Exception:
            pass

        return record
    
    def get(self, registration_id: str) -> Optional[TaskRegistrationRecord]:
        """
        获取注册记录。
        
        Args:
            registration_id: 注册记录 ID
        
        Returns:
            注册记录，不存在则返回 None
        """
        record_file = _registration_file(registration_id)
        if not record_file.exists():
            return None
        
        with open(record_file, "r") as f:
            data = json.load(f)
        
        return TaskRegistrationRecord.from_dict(data)
    
    def list(
        self,
        status: Optional[str] = None,
        registration_status: Optional[str] = None,
        batch_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[TaskRegistrationRecord]:
        """
        列出注册记录。
        
        Args:
            status: 按任务状态过滤（pending | in_progress | completed | blocked）
            registration_status: 按注册状态过滤（registered | skipped | blocked）
            batch_id: 按批次 ID 过滤
            limit: 最大返回数量
        
        Returns:
            注册记录列表
        """
        records = self._read_registry()
        
        # 过滤
        result = []
        for data in records:
            if status and data.get("status") != status:
                continue
            if registration_status and data.get("registration_status") != registration_status:
                continue
            if batch_id and data.get("batch_id") != batch_id:
                continue
            result.append(TaskRegistrationRecord.from_dict(data))
        
        # 按注册时间倒序（normalize to UTC epoch for consistent sort
        # across naive and timezone-aware timestamps）
        def _sort_key(r: TaskRegistrationRecord) -> float:
            ts = r.metadata.get("registered_at", "")
            try:
                dt = datetime.fromisoformat(ts)
                if dt.tzinfo is None:
                    # Treat naive timestamps as local time (legacy behavior)
                    dt = dt.astimezone()
                return dt.timestamp()
            except (ValueError, TypeError):
                return 0.0
        result.sort(key=_sort_key, reverse=True)
        
        return result[:limit]
    
    def get_by_source(
        self,
        source_task_id: Optional[str] = None,
        source_batch_id: Optional[str] = None,
    ) -> List[TaskRegistrationRecord]:
        """
        按来源查询注册记录。
        
        Args:
            source_task_id: 来源任务 ID
            source_batch_id: 来源批次 ID
        
        Returns:
            注册记录列表
        """
        records = self._read_registry()
        
        result = []
        for data in records:
            source_closeout = data.get("source_closeout") or {}
            if source_task_id and source_closeout.get("original_task_id") == source_task_id:
                result.append(TaskRegistrationRecord.from_dict(data))
            elif source_batch_id and source_closeout.get("original_batch_id") == source_batch_id:
                result.append(TaskRegistrationRecord.from_dict(data))
        
        return result
    
    def update_status(
        self,
        registration_id: str,
        new_status: Literal["pending", "in_progress", "completed", "blocked"],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[TaskRegistrationRecord]:
        """
        更新任务状态。
        
        Args:
            registration_id: 注册记录 ID
            new_status: 新状态
            metadata: 额外元数据（可选）
        
        Returns:
            更新后的注册记录，不存在则返回 None
        """
        record = self.get(registration_id)
        if not record:
            return None
        
        record.status = new_status
        if metadata:
            record.metadata.update(metadata)
        
        # 重写记录文件
        record_file = _registration_file(registration_id)
        tmp_file = record_file.with_suffix(".tmp")
        with open(tmp_file, "w") as f:
            json.dump(record.to_dict(), f, indent=2)
        tmp_file.replace(record_file)
        
        # 更新注册表（需要重写整个文件）
        records = self._read_registry()
        for i, data in enumerate(records):
            if data.get("registration_id") == registration_id:
                records[i] = record.to_dict()
                break
        self._write_registry(records)
        
        return record


def register_task(
    *,
    proposed_task: Dict[str, Any],
    source_closeout: Optional[Dict[str, Any]] = None,
    registration_status: RegistrationStatus = "registered",
    registration_reason: str = "",
    batch_id: Optional[str] = None,
    owner: Optional[str] = None,
    ready_for_auto_dispatch: bool = False,
    metadata: Optional[Dict[str, Any]] = None,
) -> TaskRegistrationRecord:
    """
    注册新任务（convenience function）。
    
    Args:
        proposed_task: 提议的任务内容
        source_closeout: 来源 partial closeout contract（可选）
        registration_status: 注册状态（registered | skipped | blocked）
        registration_reason: 注册/跳过/阻止的原因
        batch_id: 所属批次 ID（可选）
        owner: 任务所有者（可选）
        ready_for_auto_dispatch: 是否准备好自动 dispatch
        metadata: 额外元数据
    
    Returns:
        TaskRegistrationRecord
    """
    # 生成稳定 ID
    registration_id = _generate_task_id("reg")
    task_id = _generate_task_id("task")
    
    # 构建 truth anchor
    truth_anchor = None
    if source_closeout:
        source_batch_id = source_closeout.get("original_batch_id")
        source_task_id = source_closeout.get("original_task_id")
        if source_batch_id:
            truth_anchor = TruthAnchor(
                anchor_type="batch_id",
                anchor_value=source_batch_id,
                metadata={"source": "partial_closeout"},
            )
        elif source_task_id:
            truth_anchor = TruthAnchor(
                anchor_type="task_id",
                anchor_value=source_task_id,
                metadata={"source": "partial_closeout"},
            )
    
    # 构建 metadata
    full_metadata = metadata or {}
    full_metadata["ready_for_auto_dispatch"] = ready_for_auto_dispatch
    full_metadata["source_type"] = "partial_continuation"
    
    record = TaskRegistrationRecord(
        registration_id=registration_id,
        task_id=task_id,
        batch_id=batch_id,
        registration_status=registration_status,
        registration_reason=registration_reason,
        truth_anchor=truth_anchor,
        owner=owner,
        status="pending",
        source_closeout=source_closeout,
        proposed_task=proposed_task,
        metadata=full_metadata,
    )
    
    # 注册
    registry = TaskRegistry()
    registry.register(record)
    
    return record


def get_registration(registration_id: str) -> Optional[TaskRegistrationRecord]:
    """获取注册记录"""
    registry = TaskRegistry()
    return registry.get(registration_id)


def list_registrations(
    status: Optional[str] = None,
    registration_status: Optional[str] = None,
    batch_id: Optional[str] = None,
    limit: int = 100,
) -> List[TaskRegistrationRecord]:
    """列出注册记录"""
    registry = TaskRegistry()
    return registry.list(
        status=status,
        registration_status=registration_status,
        batch_id=batch_id,
        limit=limit,
    )


def get_registrations_by_source(
    source_task_id: Optional[str] = None,
    source_batch_id: Optional[str] = None,
) -> List[TaskRegistrationRecord]:
    """按来源查询注册记录"""
    registry = TaskRegistry()
    return registry.get_by_source(
        source_task_id=source_task_id,
        source_batch_id=source_batch_id,
    )


def register_next_task_from_payload(
    *,
    registration_payload: Dict[str, Any],
    registration_status: RegistrationStatus = "registered",
    registration_reason: str = "",
    batch_id: Optional[str] = None,
    owner: Optional[str] = None,
    ready_for_auto_dispatch: bool = False,
) -> TaskRegistrationRecord:
    """
    从 next_task_registration payload 注册新任务。
    
    这是 convenience function，用于把 partial_continuation 生成的
    NextTaskRegistrationPayload 转换成真实注册记录。
    
    Args:
        registration_payload: NextTaskRegistrationPayload.to_dict()
        registration_status: 注册状态
        registration_reason: 注册原因
        batch_id: 所属批次 ID
        owner: 任务所有者
        ready_for_auto_dispatch: 是否准备好自动 dispatch
    
    Returns:
        TaskRegistrationRecord
    """
    # 从 payload 中提取信息
    proposed_task = registration_payload.get("proposed_task", {})
    source_closeout = registration_payload.get("source_closeout")
    
    # 合并 metadata
    payload_metadata = registration_payload.get("metadata", {})
    
    return register_task(
        proposed_task=proposed_task,
        source_closeout=source_closeout,
        registration_status=registration_status,
        registration_reason=registration_reason,
        batch_id=batch_id,
        owner=owner,
        ready_for_auto_dispatch=ready_for_auto_dispatch,
        metadata={
            **payload_metadata,
            "source_registration_id": registration_payload.get("registration_id"),
        },
    )


def register_from_handoff(handoff) -> TaskRegistrationRecord:
    """
    P0-2 Batch 1: 从 RegistrationHandoff 注册新任务。
    
    这是 handoff schema 的统一入口，用于把 planning handoff 转换成真实注册记录。
    直接使用 handoff 中的 IDs，不重新生成。
    
    P0-2 Batch 4: 同时保存 readiness 状态到 metadata，供 ledger 查询。
    
    Args:
        handoff: RegistrationHandoff (from core.handoff_schema)
    
    Returns:
        TaskRegistrationRecord
    """
    # 构建 TruthAnchor
    truth_anchor = None
    if handoff.truth_anchor:
        truth_anchor = TruthAnchor.from_dict(handoff.truth_anchor)
    
    # P0-2 Batch 4: 构建 readiness metadata
    readiness_meta = {}
    if handoff.readiness:
        readiness_meta = handoff.readiness.to_dict()
    
    # 创建记录
    record = TaskRegistrationRecord(
        registration_id=handoff.registration_id,  # 使用 handoff 中的 ID
        task_id=handoff.task_id,  # 使用 handoff 中的 ID
        batch_id=handoff.batch_id,
        registration_status=handoff.registration_status,
        registration_reason=f"Handoff from {handoff.handoff_id}",
        truth_anchor=truth_anchor,
        owner=handoff.proposed_task.get("owner"),
        status="pending",
        source_closeout=handoff.source_closeout,
        proposed_task=handoff.proposed_task,
        metadata={
            **handoff.metadata,
            "handoff_id": handoff.handoff_id,
            "truth_anchor": handoff.truth_anchor,
            "ready_for_auto_dispatch": handoff.ready_for_auto_dispatch,
            "readiness": readiness_meta,  # P0-2 Batch 4
        },
    )
    
    # 注册到 registry
    registry = TaskRegistry()
    registry.register(record)
    
    return record


# P0-2 Batch 4: Registration Ledger for queryable/traceable semantics

@dataclass
class LedgerEntry:
    """
    Ledger Entry — 注册账簿条目（P0-2 Batch 4）。
    
    核心字段：
    - registration_id: 注册 ID
    - task_id: 任务 ID
    - handoff_id: 关联 handoff ID
    - truth_anchor: 真值锚点
    - registration_status: registered | skipped | blocked
    - ready_for_auto_dispatch: 是否准备好自动 dispatch
    - readiness_status: ready | not_ready | blocked
    - readiness_blockers: 阻塞原因列表
    - registered_at: 注册时间戳
    
    这是可查询、可追溯的 registration ledger 语义。
    """
    registration_id: str
    task_id: str
    handoff_id: Optional[str]
    truth_anchor: Optional[Dict[str, Any]]
    registration_status: RegistrationStatus
    ready_for_auto_dispatch: bool
    readiness_status: Optional[str]
    readiness_blockers: List[str]
    registered_at: Optional[str]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "registration_id": self.registration_id,
            "task_id": self.task_id,
            "handoff_id": self.handoff_id,
            "truth_anchor": self.truth_anchor,
            "registration_status": self.registration_status,
            "ready_for_auto_dispatch": self.ready_for_auto_dispatch,
            "readiness_status": self.readiness_status,
            "readiness_blockers": self.readiness_blockers,
            "registered_at": self.registered_at,
        }
    
    @classmethod
    def from_record(cls, record: TaskRegistrationRecord) -> "LedgerEntry":
        """从 TaskRegistrationRecord 构建 LedgerEntry"""
        handoff_id = record.metadata.get("handoff_id")
        readiness = record.metadata.get("readiness") or {}
        
        return cls(
            registration_id=record.registration_id,
            task_id=record.task_id,
            handoff_id=handoff_id,
            truth_anchor=record.truth_anchor.to_dict() if record.truth_anchor else None,
            registration_status=record.registration_status,
            ready_for_auto_dispatch=record.ready_for_auto_dispatch,
            readiness_status=readiness.get("status"),
            readiness_blockers=readiness.get("blockers", []),
            registered_at=record.metadata.get("registered_at"),
        )


class RegistrationLedger:
    """
    Registration Ledger — 可查询、可追溯的注册账簿（P0-2 Batch 4）。
    
    提供：
    - list_entries(): 列出 ledger 条目
    - get_by_handoff(): 按 handoff_id 查询
    - get_by_truth_anchor(): 按 truth_anchor 查询
    - get_ready_for_dispatch(): 获取准备好 auto-dispatch 的注册
    - get_blocked(): 获取被阻塞的注册
    - trace_lineage(): 追溯注册来源 lineage
    """
    
    def __init__(self):
        self.registry = TaskRegistry()
    
    def list_entries(
        self,
        registration_status: Optional[str] = None,
        readiness_status: Optional[str] = None,
        limit: int = 100,
    ) -> List[LedgerEntry]:
        """
        列出 ledger 条目。
        
        Args:
            registration_status: 按注册状态过滤
            readiness_status: 按就绪状态过滤
            limit: 最大返回数量
        
        Returns:
            LedgerEntry 列表
        """
        records = self.registry.list(
            registration_status=registration_status,
            limit=limit,
        )
        
        entries = []
        for record in records:
            entry = LedgerEntry.from_record(record)
            
            # 按 readiness_status 过滤
            if readiness_status and entry.readiness_status != readiness_status:
                continue
            
            entries.append(entry)
        
        return entries
    
    def get_by_handoff(self, handoff_id: str) -> List[LedgerEntry]:
        """
        按 handoff_id 查询 ledger 条目。
        
        Args:
            handoff_id: handoff ID
        
        Returns:
            LedgerEntry 列表
        """
        records = self.registry.list(limit=1000)
        entries = []
        
        for record in records:
            if record.metadata.get("handoff_id") == handoff_id:
                entries.append(LedgerEntry.from_record(record))
        
        return entries
    
    def get_by_truth_anchor(
        self,
        anchor_type: Optional[str] = None,
        anchor_value: Optional[str] = None,
    ) -> List[LedgerEntry]:
        """
        按 truth_anchor 查询 ledger 条目。
        
        Args:
            anchor_type: 锚点类型 (task_id | batch_id | handoff_id)
            anchor_value: 锚点值
        
        Returns:
            LedgerEntry 列表
        """
        records = self.registry.list(limit=1000)
        entries = []
        
        for record in records:
            if not record.truth_anchor:
                continue
            
            if anchor_type and record.truth_anchor.anchor_type != anchor_type:
                continue
            
            if anchor_value and record.truth_anchor.anchor_value != anchor_value:
                continue
            
            entries.append(LedgerEntry.from_record(record))
        
        return entries
    
    def get_ready_for_dispatch(self, limit: int = 100) -> List[LedgerEntry]:
        """
        获取准备好 auto-dispatch 的注册。
        
        Args:
            limit: 最大返回数量
        
        Returns:
            LedgerEntry 列表
        """
        # Don't limit registry.list() since we filter further below;
        # apply limit only to the final result.
        records = self.registry.list(
            registration_status="registered",
            limit=10000,
        )

        entries = []
        for record in records:
            if record.ready_for_auto_dispatch:
                entry = LedgerEntry.from_record(record)
                if entry.readiness_status == "ready":
                    entries.append(entry)
                    if len(entries) >= limit:
                        break

        return entries
    
    def get_blocked(self, limit: int = 100) -> List[LedgerEntry]:
        """
        获取被阻塞的注册。
        
        Args:
            limit: 最大返回数量
        
        Returns:
            LedgerEntry 列表
        """
        records = self.registry.list(limit=limit)
        entries = []
        
        for record in records:
            entry = LedgerEntry.from_record(record)
            if entry.registration_status == "blocked" or entry.readiness_status == "blocked":
                entries.append(entry)
        
        return entries
    
    def trace_lineage(self, registration_id: str) -> List[Dict[str, Any]]:
        """
        追溯注册来源 lineage。
        
        Args:
            registration_id: 注册 ID
        
        Returns:
            lineage 列表（从当前注册到源头）
        """
        record = self.registry.get(registration_id)
        if not record:
            return []
        
        lineage = []
        current = record
        seen_ids = set()  # 防止死循环
        
        while current and current.registration_id not in seen_ids:
            seen_ids.add(current.registration_id)
            
            lineage.append({
                "registration_id": current.registration_id,
                "task_id": current.task_id,
                "truth_anchor": current.truth_anchor.to_dict() if current.truth_anchor else None,
                "registration_status": current.registration_status,
            })
            
            # 查找上一个来源
            if not current.truth_anchor:
                break
            
            prev_records = self.registry.get_by_source(
                source_task_id=current.truth_anchor.anchor_value
                if current.truth_anchor.anchor_type == "task_id"
                else None,
                source_batch_id=current.truth_anchor.anchor_value
                if current.truth_anchor.anchor_type == "batch_id"
                else None,
            )
            
            # 排除当前记录本身，避免死循环
            prev_records = [
                r for r in prev_records 
                if r.registration_id != current.registration_id
            ]
            
            current = prev_records[0] if prev_records else None
        
        return lineage
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化 ledger 状态"""
        entries = self.list_entries(limit=1000)
        return {
            "ledger_version": TASK_REGISTRY_VERSION,
            "entry_count": len(entries),
            "entries": [e.to_dict() for e in entries],
        }


def get_registrations_by_readiness(
    readiness_status: str,
    limit: int = 100,
) -> List[TaskRegistrationRecord]:
    """
    P0-2 Batch 4: 按 readiness 状态查询注册记录。
    
    Args:
        readiness_status: ready | not_ready | blocked
        limit: 最大返回数量
    
    Returns:
        TaskRegistrationRecord 列表
    """
    ledger = RegistrationLedger()
    entries = ledger.list_entries(readiness_status=readiness_status, limit=limit)
    
    # 转换回 TaskRegistrationRecord
    records = []
    for entry in entries:
        record = ledger.registry.get(entry.registration_id)
        if record:
            records.append(record)
    
    return records


def get_registrations_by_truth_anchor(
    anchor_type: Optional[str] = None,
    anchor_value: Optional[str] = None,
) -> List[TaskRegistrationRecord]:
    """
    P0-2 Batch 4: 按 truth_anchor 查询注册记录。
    
    Args:
        anchor_type: 锚点类型 (task_id | batch_id | handoff_id)
        anchor_value: 锚点值
    
    Returns:
        TaskRegistrationRecord 列表
    """
    ledger = RegistrationLedger()
    entries = ledger.get_by_truth_anchor(
        anchor_type=anchor_type,
        anchor_value=anchor_value,
    )
    
    # 转换回 TaskRegistrationRecord
    records = []
    for entry in entries:
        record = ledger.registry.get(entry.registration_id)
        if record:
            records.append(record)
    
    return records


# CLI 入口
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python task_registration.py register <task_json_file>")
        print("  python task_registration.py get <registration_id>")
        print("  python task_registration.py list [--status <status>] [--batch <batch_id>]")
        print("  python task_registration.py by-source [--task <task_id>] [--batch <batch_id>]")
        print("  python task_registration.py update <registration_id> <new_status>")
        print("  python task_registration.py ledger [--readiness <status>]")
        print("  python task_registration.py by-anchor [--type <type>] [--value <value>]")
        print("  python task_registration.py ready-for-dispatch")
        print("  python task_registration.py blocked")
        print("  python task_registration.py lineage <registration_id>")
        sys.exit(1)
    
    cmd = sys.argv[1]
    registry = TaskRegistry()
    
    if cmd == "register":
        if len(sys.argv) < 3:
            print("Error: missing task_json_file")
            sys.exit(1)
        json_file = sys.argv[2]
        with open(json_file, "r") as f:
            data = json.load(f)
        record = register_task(
            proposed_task=data.get("proposed_task", {}),
            source_closeout=data.get("source_closeout"),
            registration_status=data.get("registration_status", "registered"),
            registration_reason=data.get("registration_reason", ""),
            batch_id=data.get("batch_id"),
            owner=data.get("owner"),
            ready_for_auto_dispatch=data.get("ready_for_auto_dispatch", False),
        )
        print(json.dumps(record.to_dict(), indent=2))
    
    elif cmd == "get":
        if len(sys.argv) < 3:
            print("Error: missing registration_id")
            sys.exit(1)
        registration_id = sys.argv[2]
        record = registry.get(registration_id)
        if record:
            print(json.dumps(record.to_dict(), indent=2))
        else:
            print(f"Registration {registration_id} not found")
            sys.exit(1)
    
    elif cmd == "list":
        status = None
        batch_id = None
        registration_status = None
        if "--status" in sys.argv:
            idx = sys.argv.index("--status")
            if idx + 1 < len(sys.argv):
                status = sys.argv[idx + 1]
        if "--batch" in sys.argv:
            idx = sys.argv.index("--batch")
            if idx + 1 < len(sys.argv):
                batch_id = sys.argv[idx + 1]
        if "--registration-status" in sys.argv:
            idx = sys.argv.index("--registration-status")
            if idx + 1 < len(sys.argv):
                registration_status = sys.argv[idx + 1]
        records = registry.list(
            status=status,
            registration_status=registration_status,
            batch_id=batch_id,
        )
        print(json.dumps([r.to_dict() for r in records], indent=2))
    
    elif cmd == "by-source":
        source_task_id = None
        source_batch_id = None
        if "--task" in sys.argv:
            idx = sys.argv.index("--task")
            if idx + 1 < len(sys.argv):
                source_task_id = sys.argv[idx + 1]
        if "--batch" in sys.argv:
            idx = sys.argv.index("--batch")
            if idx + 1 < len(sys.argv):
                source_batch_id = sys.argv[idx + 1]
        records = registry.get_by_source(
            source_task_id=source_task_id,
            source_batch_id=source_batch_id,
        )
        print(json.dumps([r.to_dict() for r in records], indent=2))
    
    elif cmd == "update":
        if len(sys.argv) < 4:
            print("Error: missing registration_id or new_status")
            sys.exit(1)
        registration_id = sys.argv[2]
        new_status = sys.argv[3]
        record = registry.update_status(registration_id, new_status)
        if record:
            print(json.dumps(record.to_dict(), indent=2))
        else:
            print(f"Registration {registration_id} not found")
            sys.exit(1)
    
    # P0-2 Batch 4: Ledger commands
    elif cmd == "ledger":
        ledger = RegistrationLedger()
        readiness_status = None
        if "--readiness" in sys.argv:
            idx = sys.argv.index("--readiness")
            if idx + 1 < len(sys.argv):
                readiness_status = sys.argv[idx + 1]
        entries = ledger.list_entries(readiness_status=readiness_status)
        print(json.dumps([e.to_dict() for e in entries], indent=2))
    
    elif cmd == "by-anchor":
        anchor_type = None
        anchor_value = None
        if "--type" in sys.argv:
            idx = sys.argv.index("--type")
            if idx + 1 < len(sys.argv):
                anchor_type = sys.argv[idx + 1]
        if "--value" in sys.argv:
            idx = sys.argv.index("--value")
            if idx + 1 < len(sys.argv):
                anchor_value = sys.argv[idx + 1]
        records = get_registrations_by_truth_anchor(
            anchor_type=anchor_type,
            anchor_value=anchor_value,
        )
        print(json.dumps([r.to_dict() for r in records], indent=2))
    
    elif cmd == "ready-for-dispatch":
        ledger = RegistrationLedger()
        entries = ledger.get_ready_for_dispatch()
        print(json.dumps([e.to_dict() for e in entries], indent=2))
    
    elif cmd == "blocked":
        ledger = RegistrationLedger()
        entries = ledger.get_blocked()
        print(json.dumps([e.to_dict() for e in entries], indent=2))
    
    elif cmd == "lineage":
        if len(sys.argv) < 3:
            print("Error: missing registration_id")
            sys.exit(1)
        registration_id = sys.argv[2]
        ledger = RegistrationLedger()
        lineage = ledger.trace_lineage(registration_id)
        print(json.dumps(lineage, indent=2))
    
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
