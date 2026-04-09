#!/usr/bin/env python3
"""
subagent_state.py — Deer-Flow 借鉴线 Batch B

目标：实现热状态存储 + 持久化真值混合方案。

借鉴 Deer-Flow 的全局状态存储设计：
- 内存字典快速访问
- 线程安全锁保护
- 完成后清理内存

适配 OpenClaw：
- 使用 shared-context 文件系统持久化
- 重启后可从文件恢复终态
- 内存只作为缓存层（热状态）

核心功能：
- SubagentStateManager: 状态管理器
- 内存缓存 + 文件持久化混合
- 支持状态查询、更新、清理
- 支持批量操作

使用示例：
```python
from subagent_state import SubagentStateManager

manager = SubagentStateManager()

# 创建状态
manager.create_state(task_id, initial_status)

# 更新状态
manager.update_status(task_id, "running")

# 获取状态（优先内存，回退文件）
state = manager.get_state(task_id)

# 清理已完成任务（从内存移除，保留文件）
manager.cleanup(task_id)
```
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

__all__ = [
    "SubagentState",
    "SubagentStateManager",
    "STATE_VERSION",
]

STATE_VERSION = "subagent_state_v1"

SubagentStateStatus = Literal["pending", "running", "completed", "failed", "timed_out", "cancelled"]

TERMINAL_STATES = {"completed", "failed", "timed_out", "cancelled"}


@dataclass
class SubagentState:
    """
    Subagent 状态 — 记录任务执行状态。
    
    核心字段：
    - task_id: 任务 ID
    - status: 执行状态
    - created_at: 创建时间
    - updated_at: 更新时间
    - started_at: 开始时间（running 时设置）
    - completed_at: 完成时间（终端状态时设置）
    - metadata: 额外元数据
    - payload: 任务 payload（可选）
    - result: 执行结果（完成后填充）
    """
    task_id: str
    status: SubagentStateStatus
    created_at: str
    updated_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    payload: Optional[Dict[str, Any]] = None
    result: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "state_version": STATE_VERSION,
            "task_id": self.task_id,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "metadata": self.metadata,
            "payload": self.payload,
            "result": self.result,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SubagentState":
        return cls(
            task_id=data.get("task_id", ""),
            status=data.get("status", "pending"),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            metadata=data.get("metadata", {}),
            payload=data.get("payload"),
            result=data.get("result"),
        )


class SubagentStateManager:
    """
    Subagent 状态管理器 — 内存缓存 + 文件持久化混合方案。
    
    核心方法：
    - create_state(task_id, status, **kwargs): 创建状态
    - get_state(task_id): 获取状态（优先内存，回退文件）
    - update_status(task_id, status, **kwargs): 更新状态
    - list_states(status=None, limit=100): 列出状态
    - cleanup(task_id): 清理已完成任务（从内存移除，保留文件）
    - restore_from_disk(): 从磁盘恢复所有终态
    
    设计借鉴 Deer-Flow：
    - 内存字典快速访问
    - 线程安全锁保护
    - 完成后清理内存
    
    适配 OpenClaw：
    - shared-context 文件持久化
    - 重启后可恢复终态
    - 内存只作为缓存层
    """
    
    def __init__(self, state_dir: Optional[Path] = None):
        """
        初始化状态管理器。
        
        Args:
            state_dir: 状态文件目录（默认：~/.openclaw/shared-context/subagent_states）
        """
        self.state_dir = state_dir or Path.home() / ".openclaw" / "shared-context" / "subagent_states"
        self._ensure_state_dir()
        
        # 内存缓存（热状态）
        self._cache: Dict[str, SubagentState] = {}
        self._lock = threading.Lock()
        
        # 恢复磁盘上的终态到内存
        self._restore_from_disk()
    
    def _ensure_state_dir(self):
        """确保状态目录存在"""
        self.state_dir.mkdir(parents=True, exist_ok=True)
    
    def _state_file(self, task_id: str) -> Path:
        """返回状态文件路径"""
        return self.state_dir / f"{task_id}.json"
    
    def _iso_now(self) -> str:
        """返回 ISO-8601 时间戳"""
        return datetime.now(timezone.utc).isoformat()
    
    def _persist_state(self, state: SubagentState):
        """持久化状态到文件"""
        state_path = self._state_file(state.task_id)
        tmp_path = state_path.with_suffix(".tmp")
        with open(tmp_path, "w") as f:
            json.dump(state.to_dict(), f, indent=2)
        tmp_path.replace(state_path)
    
    def _load_state(self, task_id: str) -> Optional[SubagentState]:
        """从文件加载状态"""
        state_path = self._state_file(task_id)
        if not state_path.exists():
            return None
        
        try:
            with open(state_path, "r") as f:
                data = json.load(f)
            return SubagentState.from_dict(data)
        except (json.JSONDecodeError, KeyError):
            return None
    
    def _restore_from_disk(self):
        """从磁盘恢复所有终态到内存"""
        self._ensure_state_dir()
        
        for state_file in self.state_dir.glob("*.json"):
            try:
                state = self._load_state(state_file.stem)
                if state and state.status in TERMINAL_STATES:
                    # 只恢复终态（热状态优化）
                    with self._lock:
                        self._cache[state.task_id] = state
            except Exception:
                pass
    
    def create_state(
        self,
        task_id: str,
        status: SubagentStateStatus = "pending",
        payload: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SubagentState:
        """
        创建状态。
        
        Args:
            task_id: 任务 ID
            status: 初始状态
            payload: 任务 payload
            metadata: 元数据
        
        Returns:
            SubagentState
        """
        now = self._iso_now()
        state = SubagentState(
            task_id=task_id,
            status=status,
            created_at=now,
            updated_at=now,
            metadata=metadata or {},
            payload=payload,
        )
        
        with self._lock:
            self._cache[task_id] = state
        
        self._persist_state(state)
        return state
    
    def get_state(self, task_id: str) -> Optional[SubagentState]:
        """
        获取状态（优先内存，回退文件）。
        
        Args:
            task_id: 任务 ID
        
        Returns:
            SubagentState，不存在则返回 None
        """
        with self._lock:
            if task_id in self._cache:
                return self._cache[task_id]
        
        # 回退到文件
        return self._load_state(task_id)
    
    def update_status(
        self,
        task_id: str,
        status: SubagentStateStatus,
        result: Optional[Dict[str, Any]] = None,
        **metadata_updates: Any,
    ) -> Optional[SubagentState]:
        """
        更新状态。
        
        Args:
            task_id: 任务 ID
            status: 新状态
            result: 执行结果（可选）
            **metadata_updates: 元数据更新
        
        Returns:
            更新后的 SubagentState，不存在则返回 None
        """
        with self._lock:
            state = self._cache.get(task_id)
            if not state:
                # 尝试从文件加载
                state = self._load_state(task_id)
                if state:
                    self._cache[task_id] = state
            
            if not state:
                return None
            
            # 更新状态
            state.status = status
            state.updated_at = self._iso_now()
            
            # 更新 started_at
            if status == "running" and not state.started_at:
                state.started_at = state.updated_at
            
            # 更新 completed_at
            if status in TERMINAL_STATES and not state.completed_at:
                state.completed_at = state.updated_at
            
            # 更新 result
            if result is not None:
                state.result = result
            
            # 更新 metadata（合并）
            for key, value in metadata_updates.items():
                if isinstance(value, dict):
                    state.metadata.update(value)
                else:
                    state.metadata[key] = value
            
            # 持久化
            self._persist_state(state)
            
            return state
    
    def list_states(
        self,
        status: Optional[SubagentStateStatus] = None,
        limit: int = 100,
    ) -> List[SubagentState]:
        """
        列出状态。
        
        Args:
            status: 按状态过滤
            limit: 最大返回数量
        
        Returns:
            SubagentState 列表
        """
        self._ensure_state_dir()
        
        states = []
        for state_file in self.state_dir.glob("*.json"):
            try:
                state = self._load_state(state_file.stem)
                if state:
                    if status is None or state.status == status:
                        states.append(state)
            except Exception:
                pass
        
        # 按 created_at 排序
        states.sort(key=lambda s: s.created_at, reverse=True)
        
        return states[:limit]
    
    def cleanup(self, task_id: str) -> bool:
        """
        清理已完成任务（从内存移除，保留文件）。
        
        Args:
            task_id: 任务 ID
        
        Returns:
            True 如果清理成功
        """
        with self._lock:
            state = self._cache.get(task_id)
            if not state or state.status not in TERMINAL_STATES:
                return False
            
            del self._cache[task_id]
            return True
    
    def is_completed(self, task_id: str) -> bool:
        """
        检查任务是否完成。
        
        Args:
            task_id: 任务 ID
        
        Returns:
            True 如果任务已完成
        """
        state = self.get_state(task_id)
        return state is not None and state.status in TERMINAL_STATES
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取统计信息。
        
        Returns:
            统计字典
        """
        self._ensure_state_dir()
        
        stats = {
            "total_files": 0,
            "cache_size": len(self._cache),
            "by_status": {},
        }
        
        for state_file in self.state_dir.glob("*.json"):
            stats["total_files"] += 1
        
        # 按状态统计
        for state in self._cache.values():
            status = state.status
            stats["by_status"][status] = stats["by_status"].get(status, 0) + 1
        
        return stats


# ============ 便捷函数 ============

_default_manager: Optional[SubagentStateManager] = None


def get_manager() -> SubagentStateManager:
    """获取默认状态管理器（单例）"""
    global _default_manager
    if _default_manager is None:
        _default_manager = SubagentStateManager()
    return _default_manager


def create_state(
    task_id: str,
    status: SubagentStateStatus = "pending",
    payload: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> SubagentState:
    """便捷函数：创建状态"""
    return get_manager().create_state(task_id, status, payload, metadata)


def get_state(task_id: str) -> Optional[SubagentState]:
    """便捷函数：获取状态"""
    return get_manager().get_state(task_id)


def update_status(
    task_id: str,
    status: SubagentStateStatus,
    result: Optional[Dict[str, Any]] = None,
    **metadata_updates: Any,
) -> Optional[SubagentState]:
    """便捷函数：更新状态"""
    return get_manager().update_status(task_id, status, result, **metadata_updates)


def list_states(
    status: Optional[SubagentStateStatus] = None,
    limit: int = 100,
) -> List[SubagentState]:
    """便捷函数：列出状态"""
    return get_manager().list_states(status, limit)


def cleanup(task_id: str) -> bool:
    """便捷函数：清理已完成任务"""
    return get_manager().cleanup(task_id)


# ============ CLI 入口 ============

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python subagent_state.py create <task_id> [status]")
        print("  python subagent_state.py get <task_id>")
        print("  python subagent_state.py update <task_id> <status>")
        print("  python subagent_state.py list [--status <status>]")
        print("  python subagent_state.py stats")
        sys.exit(1)
    
    cmd = sys.argv[1]
    manager = get_manager()
    
    if cmd == "create":
        if len(sys.argv) < 3:
            print("Error: missing task_id")
            sys.exit(1)
        
        task_id = sys.argv[2]
        status = sys.argv[3] if len(sys.argv) > 3 else "pending"
        
        state = manager.create_state(task_id, status)  # type: ignore
        print(json.dumps(state.to_dict(), indent=2))
    
    elif cmd == "get":
        if len(sys.argv) < 3:
            print("Error: missing task_id")
            sys.exit(1)
        
        task_id = sys.argv[2]
        state = manager.get_state(task_id)
        
        if state:
            print(json.dumps(state.to_dict(), indent=2))
        else:
            print(f"State not found: {task_id}")
            sys.exit(1)
    
    elif cmd == "update":
        if len(sys.argv) < 4:
            print("Error: missing task_id or status")
            sys.exit(1)
        
        task_id = sys.argv[2]
        status = sys.argv[3]
        
        state = manager.update_status(task_id, status)  # type: ignore
        if state:
            print(json.dumps(state.to_dict(), indent=2))
        else:
            print(f"State not found: {task_id}")
            sys.exit(1)
    
    elif cmd == "list":
        status = None
        if "--status" in sys.argv:
            idx = sys.argv.index("--status")
            if idx + 1 < len(sys.argv):
                status = sys.argv[idx + 1]
        
        states = manager.list_states(status)  # type: ignore
        print(json.dumps([s.to_dict() for s in states], indent=2))
    
    elif cmd == "stats":
        stats = manager.get_stats()
        print(json.dumps(stats, indent=2))
    
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
