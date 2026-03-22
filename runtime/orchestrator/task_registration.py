#!/usr/bin/env python3
"""
task_registration.py — Universal Task Registration Layer (v2)

目标：把 next_task_registration payload 变成真实可落盘的注册记录，
并提供统一的 task registry / ledger 供 operator/main 消费。

核心概念：
- TaskRegistrationRecord: 真实注册记录（可落盘）
- TaskRegistry: 统一任务注册表（ledger）
- registration_status: registered | skipped | blocked
- truth_anchor: 稳定的 source linkage（source_task_id / source_batch_id / new_task_id）

这是通用 kernel，不绑定任何特定场景。trading/channel 等场景可以 plug-in 使用。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

__all__ = [
    "RegistrationStatus",
    "TaskRegistrationRecord",
    "TaskRegistry",
    "register_task",
    "get_registration",
    "list_registrations",
    "get_registrations_by_source",
    "TASK_REGISTRY_VERSION",
]

TASK_REGISTRY_VERSION = "task_registration_v1"

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
    return datetime.now().isoformat()


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
        
        # 写入单个记录文件
        record_file = _registration_file(record.registration_id)
        tmp_file = record_file.with_suffix(".tmp")
        with open(tmp_file, "w") as f:
            json.dump(record.to_dict(), f, indent=2)
        tmp_file.replace(record_file)
        
        # 追加到注册表
        records = self._read_registry()
        records.append(record.to_dict())
        self._write_registry(records)
        
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
        
        # 按注册时间倒序
        result.sort(
            key=lambda r: r.metadata.get("registered_at", ""),
            reverse=True,
        )
        
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
    
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
