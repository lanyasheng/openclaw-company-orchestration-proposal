#!/usr/bin/env python3
"""
lineage.py — Minimal Parent-Child Lineage Tracking

目标：提供最小的 lineage 数据结构，用于追踪任务之间的父子关系。

核心字段：
- lineage_id: 唯一标识
- parent_id: 父任务 ID (dispatch_id / spawn_id / execution_id 等)
- child_id: 子任务 ID
- batch_id: 批次 ID (可选，用于 grouping)
- relation_type: 关系类型 (spawn / continuation / followup / retry / fanin)
- created_at: 创建时间戳
- metadata: 额外元数据 (可选)

当前阶段：最小数据结构 + 序列化/反序列化 + 最小接线到 sessions_spawn_bridge

这是极小切片实现，不做完整的 fan-in / parent-child helper。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

__all__ = [
    "LINEAGE_VERSION",
    "RelationType",
    "LineageRecord",
    "LineageStore",
    "create_lineage_record",
    "list_lineage_records",
    "get_lineage_record",
    "get_lineage_by_parent",
    "get_lineage_by_child",
    "get_lineage_by_batch",
    "LINEAGE_STORE_DIR",
]

LINEAGE_VERSION = "lineage_v1"

RelationType = Literal["spawn", "continuation", "followup", "retry", "fanin", "other"]

# Lineage store 存储目录
LINEAGE_STORE_DIR = Path(
    os.environ.get(
        "OPENCLAW_LINEAGE_STORE_DIR",
        Path.home() / ".openclaw" / "shared-context" / "lineage",
    )
)

# Lineage index 文件
LINEAGE_INDEX_FILE = LINEAGE_STORE_DIR / "lineage_index.json"


def _ensure_lineage_dir():
    """确保 lineage 目录存在"""
    LINEAGE_STORE_DIR.mkdir(parents=True, exist_ok=True)


def _lineage_file(lineage_id: str) -> Path:
    """返回 lineage record 文件路径"""
    return LINEAGE_STORE_DIR / f"{lineage_id}.json"


def _iso_now() -> str:
    """返回当前 ISO-8601 时间戳"""
    return datetime.now().isoformat()


def _generate_lineage_id() -> str:
    """生成稳定 lineage ID"""
    import uuid
    return f"lineage_{uuid.uuid4().hex[:12]}"


@dataclass
class LineageRecord:
    """
    Lineage record — 最小父子关系追踪
    
    核心字段：
    - lineage_id: 唯一标识
    - parent_id: 父任务 ID
    - child_id: 子任务 ID
    - batch_id: 批次 ID (可选)
    - relation_type: 关系类型
    - created_at: 创建时间戳
    - metadata: 额外元数据 (可选)
    """
    lineage_id: str
    parent_id: str
    child_id: str
    batch_id: Optional[str] = None
    relation_type: RelationType = "spawn"
    created_at: str = field(default_factory=_iso_now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "lineage_id": self.lineage_id,
            "parent_id": self.parent_id,
            "child_id": self.child_id,
            "batch_id": self.batch_id,
            "relation_type": self.relation_type,
            "created_at": self.created_at,
            "metadata": self.metadata,
            "version": LINEAGE_VERSION,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LineageRecord":
        """从字典反序列化"""
        return cls(
            lineage_id=data.get("lineage_id", ""),
            parent_id=data.get("parent_id", ""),
            child_id=data.get("child_id", ""),
            batch_id=data.get("batch_id"),
            relation_type=data.get("relation_type", "spawn"),
            created_at=data.get("created_at", _iso_now()),
            metadata=data.get("metadata", {}),
        )
    
    def to_json(self, indent: int = 2) -> str:
        """序列化为 JSON 字符串"""
        return json.dumps(self.to_dict(), indent=indent)
    
    @classmethod
    def from_json(cls, json_str: str) -> "LineageRecord":
        """从 JSON 字符串反序列化"""
        return cls.from_dict(json.loads(json_str))


def _load_lineage_index() -> Dict[str, str]:
    """
    加载 lineage index（lineage_id -> file_path 映射）。
    
    用于快速查询。
    """
    _ensure_lineage_dir()
    if not LINEAGE_INDEX_FILE.exists():
        return {}
    
    try:
        with open(LINEAGE_INDEX_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, KeyError):
        return {}


def _save_lineage_index(index: Dict[str, str]):
    """保存 lineage index"""
    _ensure_lineage_dir()
    tmp_file = LINEAGE_INDEX_FILE.with_suffix(".tmp")
    with open(tmp_file, "w") as f:
        json.dump(index, f, indent=2)
    tmp_file.replace(LINEAGE_INDEX_FILE)


def _record_lineage_index(lineage_id: str, file_path: Path):
    """记录 lineage index"""
    index = _load_lineage_index()
    index[lineage_id] = str(file_path)
    _save_lineage_index(index)


@dataclass
class LineageStore:
    """
    Lineage store — lineage record 存储管理器
    
    提供 CRUD 操作和查询接口。
    """
    
    def create_record(
        self,
        parent_id: str,
        child_id: str,
        batch_id: Optional[str] = None,
        relation_type: RelationType = "spawn",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> LineageRecord:
        """
        创建新的 lineage record
        
        Args:
            parent_id: 父任务 ID
            child_id: 子任务 ID
            batch_id: 批次 ID (可选)
            relation_type: 关系类型
            metadata: 额外元数据
        
        Returns:
            LineageRecord: 创建的 record
        """
        record = LineageRecord(
            lineage_id=_generate_lineage_id(),
            parent_id=parent_id,
            child_id=child_id,
            batch_id=batch_id,
            relation_type=relation_type,
            metadata=metadata or {},
        )
        
        # 保存到文件
        file_path = _lineage_file(record.lineage_id)
        _ensure_lineage_dir()
        with open(file_path, "w") as f:
            f.write(record.to_json())
        
        # 更新索引
        _record_lineage_index(record.lineage_id, file_path)
        
        return record
    
    def get_record(self, lineage_id: str) -> Optional[LineageRecord]:
        """
        获取 lineage record
        
        Args:
            lineage_id: lineage ID
        
        Returns:
            LineageRecord 或 None
        """
        file_path = _lineage_file(lineage_id)
        if not file_path.exists():
            return None
        
        with open(file_path, "r") as f:
            return LineageRecord.from_json(f.read())
    
    def list_records(
        self,
        parent_id: Optional[str] = None,
        child_id: Optional[str] = None,
        batch_id: Optional[str] = None,
        relation_type: Optional[RelationType] = None,
    ) -> List[LineageRecord]:
        """
        查询 lineage record 列表
        
        Args:
            parent_id: 按父 ID 过滤
            child_id: 按子 ID 过滤
            batch_id: 按批次 ID 过滤
            relation_type: 按关系类型过滤
        
        Returns:
            LineageRecord 列表
        """
        records = []
        
        for lineage_id in _load_lineage_index().keys():
            record = self.get_record(lineage_id)
            if record is None:
                continue
            
            # 应用过滤器
            if parent_id and record.parent_id != parent_id:
                continue
            if child_id and record.child_id != child_id:
                continue
            if batch_id and record.batch_id != batch_id:
                continue
            if relation_type and record.relation_type != relation_type:
                continue
            
            records.append(record)
        
        return records
    
    def get_by_parent(self, parent_id: str) -> List[LineageRecord]:
        """获取指定父任务的所有子任务"""
        return self.list_records(parent_id=parent_id)
    
    def get_by_child(self, child_id: str) -> List[LineageRecord]:
        """获取指定子任务的所有父任务"""
        return self.list_records(child_id=child_id)
    
    def get_by_batch(self, batch_id: str) -> List[LineageRecord]:
        """获取指定批次的所有 lineage"""
        return self.list_records(batch_id=batch_id)


# 全局 store 实例
_default_store: Optional[LineageStore] = None


def _get_default_store() -> LineageStore:
    """获取默认 store 实例"""
    global _default_store
    if _default_store is None:
        _default_store = LineageStore()
    return _default_store


def create_lineage_record(
    parent_id: str,
    child_id: str,
    batch_id: Optional[str] = None,
    relation_type: RelationType = "spawn",
    metadata: Optional[Dict[str, Any]] = None,
) -> LineageRecord:
    """
    创建 lineage record (便捷函数)
    
    Args:
        parent_id: 父任务 ID
        child_id: 子任务 ID
        batch_id: 批次 ID (可选)
        relation_type: 关系类型
        metadata: 额外元数据
    
    Returns:
        LineageRecord: 创建的 record
    """
    return _get_default_store().create_record(
        parent_id=parent_id,
        child_id=child_id,
        batch_id=batch_id,
        relation_type=relation_type,
        metadata=metadata,
    )


def list_lineage_records(
    parent_id: Optional[str] = None,
    child_id: Optional[str] = None,
    batch_id: Optional[str] = None,
    relation_type: Optional[RelationType] = None,
) -> List[LineageRecord]:
    """
    查询 lineage record 列表 (便捷函数)
    
    Args:
        parent_id: 按父 ID 过滤
        child_id: 按子 ID 过滤
        batch_id: 按批次 ID 过滤
        relation_type: 按关系类型过滤
    
    Returns:
        LineageRecord 列表
    """
    return _get_default_store().list_records(
        parent_id=parent_id,
        child_id=child_id,
        batch_id=batch_id,
        relation_type=relation_type,
    )


def get_lineage_record(lineage_id: str) -> Optional[LineageRecord]:
    """
    获取 lineage record (便捷函数)
    
    Args:
        lineage_id: lineage ID
    
    Returns:
        LineageRecord 或 None
    """
    return _get_default_store().get_record(lineage_id)


def get_lineage_by_parent(parent_id: str) -> List[LineageRecord]:
    """
    获取指定父任务的所有 lineage (便捷函数)
    
    Args:
        parent_id: 父任务 ID
    
    Returns:
        LineageRecord 列表
    """
    return _get_default_store().get_by_parent(parent_id)


def get_lineage_by_child(child_id: str) -> List[LineageRecord]:
    """
    获取指定子任务的所有 lineage (便捷函数)
    
    Args:
        child_id: 子任务 ID
    
    Returns:
        LineageRecord 列表
    """
    return _get_default_store().get_by_child(child_id)


def get_lineage_by_batch(batch_id: str) -> List[LineageRecord]:
    """
    获取指定批次的所有 lineage (便捷函数)
    
    Args:
        batch_id: 批次 ID
    
    Returns:
        LineageRecord 列表
    """
    return _get_default_store().get_by_batch(batch_id)


# CLI 入口
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python lineage.py <command> [args]")
        print("Commands:")
        print("  create <parent_id> <child_id> [batch_id] [relation_type]")
        print("  get <lineage_id>")
        print("  list [--parent <id>] [--child <id>] [--batch <id>]")
        sys.exit(1)
    
    cmd = sys.argv[1]
    store = _get_default_store()
    
    if cmd == "create":
        if len(sys.argv) < 4:
            print("Usage: python lineage.py create <parent_id> <child_id> [batch_id] [relation_type]")
            sys.exit(1)
        parent_id = sys.argv[2]
        child_id = sys.argv[3]
        batch_id = sys.argv[4] if len(sys.argv) > 4 else None
        relation_type = sys.argv[5] if len(sys.argv) > 5 else "spawn"
        
        record = store.create_record(
            parent_id=parent_id,
            child_id=child_id,
            batch_id=batch_id,
            relation_type=relation_type,  # type: ignore
        )
        print(record.to_json())
    
    elif cmd == "get":
        if len(sys.argv) < 3:
            print("Usage: python lineage.py get <lineage_id>")
            sys.exit(1)
        lineage_id = sys.argv[2]
        record = store.get_record(lineage_id)
        if record:
            print(record.to_json())
        else:
            print(f"Lineage record {lineage_id} not found")
            sys.exit(1)
    
    elif cmd == "list":
        parent_id = None
        child_id = None
        batch_id = None
        
        i = 2
        while i < len(sys.argv):
            if sys.argv[i] == "--parent" and i + 1 < len(sys.argv):
                parent_id = sys.argv[i + 1]
                i += 2
            elif sys.argv[i] == "--child" and i + 1 < len(sys.argv):
                child_id = sys.argv[i + 1]
                i += 2
            elif sys.argv[i] == "--batch" and i + 1 < len(sys.argv):
                batch_id = sys.argv[i + 1]
                i += 2
            else:
                i += 1
        
        records = store.list_records(
            parent_id=parent_id,
            child_id=child_id,
            batch_id=batch_id,
        )
        print(json.dumps([r.to_dict() for r in records], indent=2))
    
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
