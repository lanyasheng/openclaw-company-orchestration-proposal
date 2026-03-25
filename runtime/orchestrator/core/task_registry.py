#!/usr/bin/env python3
"""
task_registry.py — Structured Task Registry (core layer)

Structured in-memory task registry for batch-aggregator and
orchestrator rule-chain consumption. This is the **core layer**
registry used by the callback-driven path (Layer 1).

Boundary note:
  - THIS module (core/task_registry.py): in-memory TaskRegistry with
    dataclass-based TaskRegistration, used by orchestrator.py and
    batch_aggregator.py for structured fan-in / rule evaluation.
  - task_registration.py (top-level): JSONL-based ledger used by the
    Continuation Kernel (Layer 2) for persistent registration records
    and artifact linkage (registration_id → dispatch_id → ...).
  Both coexist intentionally — they serve different layers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from enum import Enum

__all__ = [
    "TaskStatus",
    "TaskRegistration",
    "TaskRegistry",
    "TASK_REGISTRY_VERSION",
]

TASK_REGISTRY_VERSION = "task_registry_v1"


class TaskStatus(str, Enum):
    """任务状态"""
    REGISTERED = "registered"
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


@dataclass
class TaskRegistration:
    """
    任务注册记录
    
    包含任务的完整注册信息，用于追踪和审计。
    """
    task_id: str
    adapter: str
    scenario: str
    batch_id: Optional[str] = None
    status: TaskStatus = TaskStatus.REGISTERED
    
    # 任务定义
    task_type: Optional[str] = None
    description: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    
    # 依赖关系
    dependencies: List[str] = field(default_factory=list)
    dependents: List[str] = field(default_factory=list)
    
    # 执行配置
    timeout_seconds: int = 3600
    max_retries: int = 3
    priority: int = 0
    
    # 状态追踪
    registered_at: str = field(default_factory=lambda: datetime.now().isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    retry_count: int = 0
    
    # 结果
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    
    # 元数据
    owner: Optional[str] = None
    labels: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "adapter": self.adapter,
            "scenario": self.scenario,
            "batch_id": self.batch_id,
            "status": self.status.value,
            "task_type": self.task_type,
            "description": self.description,
            "payload": self.payload,
            "dependencies": self.dependencies,
            "dependents": self.dependents,
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
            "priority": self.priority,
            "registered_at": self.registered_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "retry_count": self.retry_count,
            "result": self.result,
            "error": self.error,
            "owner": self.owner,
            "labels": self.labels,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskRegistration":
        return cls(
            task_id=data.get("task_id", ""),
            adapter=data.get("adapter", ""),
            scenario=data.get("scenario", ""),
            batch_id=data.get("batch_id"),
            status=TaskStatus(data.get("status", "registered")),
            task_type=data.get("task_type"),
            description=data.get("description", ""),
            payload=data.get("payload", {}),
            dependencies=data.get("dependencies", []),
            dependents=data.get("dependents", []),
            timeout_seconds=data.get("timeout_seconds", 3600),
            max_retries=data.get("max_retries", 3),
            priority=data.get("priority", 0),
            registered_at=data.get("registered_at", datetime.now().isoformat()),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            retry_count=data.get("retry_count", 0),
            result=data.get("result"),
            error=data.get("error"),
            owner=data.get("owner"),
            labels=data.get("labels", []),
            metadata=data.get("metadata", {}),
        )
    
    def update_status(self, status: TaskStatus, result: Optional[Dict[str, Any]] = None, error: Optional[str] = None):
        """更新任务状态"""
        self.status = status
        now = datetime.now().isoformat()
        
        if status == TaskStatus.RUNNING:
            self.started_at = now
        elif status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.TIMEOUT, TaskStatus.CANCELLED):
            self.completed_at = now
        
        if result:
            self.result = result
        if error:
            self.error = error
    
    def add_dependency(self, task_id: str):
        """添加依赖"""
        if task_id not in self.dependencies:
            self.dependencies.append(task_id)
    
    def add_dependent(self, task_id: str):
        """添加依赖于此任务的任务"""
        if task_id not in self.dependents:
            self.dependents.append(task_id)


class TaskRegistry:
    """
    统一任务注册表
    
    管理所有任务的注册、查询和状态追踪。
    """
    
    def __init__(self, storage_path: Optional[Path] = None):
        self.storage_path = storage_path
        self.tasks: Dict[str, TaskRegistration] = {}
        self.batches: Dict[str, Set[str]] = {}  # batch_id -> task_ids
        self.index_by_adapter: Dict[str, Set[str]] = {}  # adapter -> task_ids
        self.index_by_scenario: Dict[str, Set[str]] = {}  # scenario -> task_ids
        self.index_by_status: Dict[TaskStatus, Set[str]] = {s: set() for s in TaskStatus}
        self.created_at = datetime.now().isoformat()
        
        # 加载已有数据
        if storage_path and storage_path.exists():
            self.load(storage_path)
    
    def register(self, task: TaskRegistration) -> TaskRegistration:
        """
        注册任务
        
        Args:
            task: 任务注册记录
        
        Returns:
            注册后的任务
        """
        # 检查是否已存在
        if task.task_id in self.tasks:
            raise ValueError(f"Task {task.task_id} already registered")
        
        # 注册任务
        self.tasks[task.task_id] = task
        
        # 更新索引
        self.index_by_adapter.setdefault(task.adapter, set()).add(task.task_id)
        self.index_by_scenario.setdefault(task.scenario, set()).add(task.task_id)
        self.index_by_status[task.status].add(task.task_id)
        
        # 更新批次
        if task.batch_id:
            self.batches.setdefault(task.batch_id, set()).add(task.task_id)
        
        # 更新依赖关系
        for dep_id in task.dependencies:
            if dep_id in self.tasks:
                self.tasks[dep_id].add_dependent(task.task_id)
        
        # 持久化
        self._save_if_configured()
        
        return task
    
    def get(self, task_id: str) -> Optional[TaskRegistration]:
        """获取任务"""
        return self.tasks.get(task_id)
    
    def update_status(
        self,
        task_id: str,
        status: TaskStatus,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> Optional[TaskRegistration]:
        """
        更新任务状态
        
        Args:
            task_id: 任务 ID
            status: 新状态
            result: 执行结果
            error: 错误信息
        
        Returns:
            更新后的任务，不存在则返回 None
        """
        task = self.get(task_id)
        if not task:
            return None
        
        # 从旧状态索引中移除
        self.index_by_status[task.status].discard(task_id)
        
        # 更新状态
        old_status = task.status
        task.update_status(status, result, error)
        
        # 添加到新状态索引
        self.index_by_status[task.status].add(task_id)
        
        # 持久化
        self._save_if_configured()
        
        return task
    
    def list_tasks(
        self,
        adapter: Optional[str] = None,
        scenario: Optional[str] = None,
        status: Optional[TaskStatus] = None,
        batch_id: Optional[str] = None,
        owner: Optional[str] = None,
    ) -> List[TaskRegistration]:
        """
        列出任务（支持过滤）
        
        Args:
            adapter: 按 adapter 过滤
            scenario: 按 scenario 过滤
            status: 按状态过滤
            batch_id: 按批次过滤
            owner: 按所有者过滤
        
        Returns:
            任务列表
        """
        task_ids: Optional[Set[str]] = None
        
        if adapter:
            task_ids = self.index_by_adapter.get(adapter, set()).copy()
        if scenario:
            scenario_ids = self.index_by_scenario.get(scenario, set())
            task_ids = task_ids & scenario_ids if task_ids else scenario_ids.copy()
        if status:
            status_ids = self.index_by_status.get(status, set())
            task_ids = task_ids & status_ids if task_ids else status_ids.copy()
        if batch_id:
            batch_ids = self.batches.get(batch_id, set())
            task_ids = task_ids & batch_ids if task_ids else batch_ids.copy()
        
        if task_ids is None:
            task_ids = set(self.tasks.keys())
        
        tasks = [self.tasks[tid] for tid in task_ids if tid in self.tasks]
        
        if owner:
            tasks = [t for t in tasks if t.owner == owner]
        
        return tasks
    
    def get_batch_tasks(self, batch_id: str) -> List[TaskRegistration]:
        """获取批次下所有任务"""
        task_ids = self.batches.get(batch_id, set())
        return [self.tasks[tid] for tid in task_ids if tid in self.tasks]
    
    def get_batch_summary(self, batch_id: str) -> Dict[str, Any]:
        """获取批次汇总"""
        tasks = self.get_batch_tasks(batch_id)
        
        summary = {
            "batch_id": batch_id,
            "total": len(tasks),
            "registered": 0,
            "pending": 0,
            "running": 0,
            "completed": 0,
            "failed": 0,
            "timeout": 0,
            "cancelled": 0,
            "blocked": 0,
        }
        
        for task in tasks:
            status_key = task.status.value
            if status_key in summary:
                summary[status_key] += 1
        
        summary["complete"] = all(
            t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.TIMEOUT, TaskStatus.CANCELLED)
            for t in tasks
        )
        
        return summary
    
    def is_batch_complete(self, batch_id: str) -> bool:
        """检查批次是否完成"""
        summary = self.get_batch_summary(batch_id)
        return summary["complete"]
    
    def get_dependent_tasks(self, task_id: str) -> List[TaskRegistration]:
        """获取依赖于此任务的所有任务"""
        task = self.get(task_id)
        if not task:
            return []
        return [self.tasks[tid] for tid in task.dependents if tid in self.tasks]
    
    def get_dependencies(self, task_id: str) -> List[TaskRegistration]:
        """获取任务的所有依赖"""
        task = self.get(task_id)
        if not task:
            return []
        return [self.tasks[tid] for tid in task.dependencies if tid in self.tasks]
    
    def can_start(self, task_id: str) -> bool:
        """检查任务是否可以开始（所有依赖已完成）"""
        task = self.get(task_id)
        if not task:
            return False
        
        for dep_id in task.dependencies:
            dep = self.get(dep_id)
            if not dep or dep.status != TaskStatus.COMPLETED:
                return False
        
        return True
    
    def get_ready_tasks(self, status: TaskStatus = TaskStatus.PENDING) -> List[TaskRegistration]:
        """获取所有可以开始的任务（依赖已满足）"""
        ready = []
        for task in self.list_tasks(status=status):
            if self.can_start(task.task_id):
                ready.append(task)
        return ready
    
    def delete(self, task_id: str) -> bool:
        """
        删除任务
        
        Args:
            task_id: 任务 ID
        
        Returns:
            True 如果删除成功
        """
        task = self.get(task_id)
        if not task:
            return False
        
        # 从索引中移除
        self.index_by_adapter.get(task.adapter, set()).discard(task_id)
        self.index_by_scenario.get(task.scenario, set()).discard(task_id)
        self.index_by_status[task.status].discard(task_id)
        
        if task.batch_id:
            self.batches.get(task.batch_id, set()).discard(task_id)
        
        # 删除任务
        del self.tasks[task_id]
        
        # 持久化
        self._save_if_configured()
        
        return True
    
    def _save_if_configured(self):
        """如果配置了存储路径则保存"""
        if self.storage_path:
            self.save(self.storage_path)
    
    def save(self, path: Path):
        """保存注册表到文件"""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".tmp")
        
        data = {
            "version": TASK_REGISTRY_VERSION,
            "created_at": self.created_at,
            "tasks": {tid: t.to_dict() for tid, t in self.tasks.items()},
            "batches": {bid: list(tids) for bid, tids in self.batches.items()},
            "indexes": {
                "by_adapter": {k: list(v) for k, v in self.index_by_adapter.items()},
                "by_scenario": {k: list(v) for k, v in self.index_by_scenario.items()},
                "by_status": {k.value: list(v) for k, v in self.index_by_status.items()},
            },
        }
        
        with open(tmp_path, "w") as f:
            json.dump(data, f, indent=2)
        
        tmp_path.replace(path)
    
    @classmethod
    def load(cls, path: Path) -> "TaskRegistry":
        """从文件加载注册表"""
        with open(path, "r") as f:
            data = json.load(f)
        
        registry = cls(storage_path=path)
        registry.created_at = data.get("created_at", datetime.now().isoformat())
        
        # 加载任务
        for task_id, task_data in data.get("tasks", {}).items():
            task = TaskRegistration.from_dict(task_data)
            registry.tasks[task_id] = task
            
            # 重建索引
            registry.index_by_adapter.setdefault(task.adapter, set()).add(task_id)
            registry.index_by_scenario.setdefault(task.scenario, set()).add(task_id)
            registry.index_by_status[task.status].add(task_id)
            
            if task.batch_id:
                registry.batches.setdefault(task.batch_id, set()).add(task_id)
        
        # 加载批次
        for batch_id, task_ids in data.get("batches", {}).items():
            registry.batches[batch_id] = set(task_ids)
        
        return registry
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化注册表"""
        return {
            "version": TASK_REGISTRY_VERSION,
            "created_at": self.created_at,
            "task_count": len(self.tasks),
            "batch_count": len(self.batches),
            "tasks": {tid: t.to_dict() for tid, t in self.tasks.items()},
        }


# 全局默认注册表实例
_default_registry: Optional[TaskRegistry] = None


def get_default_registry() -> TaskRegistry:
    """获取默认注册表实例"""
    global _default_registry
    if _default_registry is None:
        _default_registry = TaskRegistry()
    return _default_registry


def set_default_registry(registry: TaskRegistry):
    """设置默认注册表实例"""
    global _default_registry
    _default_registry = registry
