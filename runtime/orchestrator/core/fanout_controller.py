#!/usr/bin/env python3
"""
fanout_controller.py — Fan-Out Execution Controller

Fan-out 执行控制器，管理子任务的并行/顺序执行和聚合。

核心功能：
- 支持 sequential/parallel/batched 模式
- 子任务状态追踪、聚合
- Fan-in 条件评估

这是通用 kernel，不绑定任何业务场景。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Callable
from pathlib import Path
import json

from core.types import FanOutMode, FanInMode  # noqa: F811

__all__ = [
    "FanOutMode",
    "FanInMode",
    "SubTask",
    "FanOutController",
    "FANOUT_CONTROLLER_VERSION",
]

FANOUT_CONTROLLER_VERSION = "fanout_controller_v1"


class SubTaskStatus(str, Enum):
    """子任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class SubTask:
    """
    子任务定义
    
    表示 fan-out 中的一个子任务单元。
    """
    task_id: str
    name: str
    status: SubTaskStatus = SubTaskStatus.PENDING
    payload: Dict[str, Any] = field(default_factory=dict)
    
    # 执行追踪
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    
    # 重试
    retry_count: int = 0
    max_retries: int = 3
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "name": self.name,
            "status": self.status.value,
            "payload": self.payload,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "result": self.result,
            "error": self.error,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SubTask":
        return cls(
            task_id=data.get("task_id", ""),
            name=data.get("name", ""),
            status=SubTaskStatus(data.get("status", "pending")),
            payload=data.get("payload", {}),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            result=data.get("result"),
            error=data.get("error"),
            retry_count=data.get("retry_count", 0),
            max_retries=data.get("max_retries", 3),
        )
    
    def mark_running(self):
        """标记为运行中"""
        self.status = SubTaskStatus.RUNNING
        self.started_at = datetime.now().isoformat()
    
    def mark_completed(self, result: Optional[Dict[str, Any]] = None):
        """标记为完成"""
        self.status = SubTaskStatus.COMPLETED
        self.completed_at = datetime.now().isoformat()
        self.result = result
    
    def mark_failed(self, error: str):
        """标记为失败"""
        self.status = SubTaskStatus.FAILED
        self.completed_at = datetime.now().isoformat()
        self.error = error
    
    def mark_timeout(self):
        """标记为超时"""
        self.status = SubTaskStatus.TIMEOUT
        self.completed_at = datetime.now().isoformat()
    
    def can_retry(self) -> bool:
        """检查是否可以重试"""
        return self.retry_count < self.max_retries
    
    def retry(self):
        """重置任务以重试"""
        self.retry_count += 1
        self.status = SubTaskStatus.PENDING
        self.started_at = None
        self.completed_at = None
        self.result = None
        self.error = None


@dataclass
class FanOutPlan:
    """
    Fan-out 执行计划
    
    定义如何执行一组子任务。
    """
    plan_id: str
    mode: FanOutMode
    sub_tasks: List[SubTask] = field(default_factory=list)
    
    # 批次配置（用于 batched 模式）
    batch_size: int = 1
    
    # 状态追踪
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    
    # 聚合配置
    fan_in_mode: FanInMode = FanInMode.ALL_SUCCESS
    custom_aggregator: Optional[Callable[[List[SubTask]], bool]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "mode": self.mode.value,
            "sub_tasks": [t.to_dict() for t in self.sub_tasks],
            "batch_size": self.batch_size,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "fan_in_mode": self.fan_in_mode.value,
        }


class FanOutController:
    """
    Fan-out 执行控制器
    
    管理子任务的执行、状态追踪和聚合。
    """
    
    def __init__(self, controller_id: str = "default"):
        self.controller_id = controller_id
        self.plans: Dict[str, FanOutPlan] = {}
        self.context: Dict[str, Any] = {}
        self.created_at = datetime.now().isoformat()
    
    def create_plan(
        self,
        plan_id: str,
        mode: FanOutMode,
        sub_tasks: List[SubTask],
        batch_size: int = 1,
        fan_in_mode: FanInMode = FanInMode.ALL_SUCCESS,
    ) -> FanOutPlan:
        """
        创建 fan-out 计划
        
        Args:
            plan_id: 计划 ID
            mode: fan-out 模式
            sub_tasks: 子任务列表
            batch_size: 批次大小（用于 batched 模式）
            fan_in_mode: fan-in 聚合模式
        
        Returns:
            FanOutPlan: 创建的计划
        """
        plan = FanOutPlan(
            plan_id=plan_id,
            mode=mode,
            sub_tasks=sub_tasks,
            batch_size=batch_size,
            fan_in_mode=fan_in_mode,
        )
        self.plans[plan_id] = plan
        return plan
    
    def get_plan(self, plan_id: str) -> Optional[FanOutPlan]:
        """获取计划"""
        return self.plans.get(plan_id)
    
    def start_plan(self, plan_id: str) -> bool:
        """
        启动计划
        
        Returns:
            True 如果启动成功
        """
        plan = self.get_plan(plan_id)
        if not plan:
            return False
        
        plan.started_at = datetime.now().isoformat()
        
        # 根据模式启动子任务
        if plan.mode == FanOutMode.PARALLEL:
            # 并行模式：所有子任务同时启动
            for task in plan.sub_tasks:
                if task.status == SubTaskStatus.PENDING:
                    task.mark_running()
        elif plan.mode == FanOutMode.SEQUENTIAL:
            # 顺序模式：只启动第一个子任务
            if plan.sub_tasks and plan.sub_tasks[0].status == SubTaskStatus.PENDING:
                plan.sub_tasks[0].mark_running()
        elif plan.mode == FanOutMode.BATCHED:
            # 批次模式：启动第一批子任务
            batch = plan.sub_tasks[:plan.batch_size]
            for task in batch:
                if task.status == SubTaskStatus.PENDING:
                    task.mark_running()
        
        return True
    
    def update_sub_task(
        self,
        plan_id: str,
        task_id: str,
        status: SubTaskStatus,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> bool:
        """
        更新子任务状态
        
        Args:
            plan_id: 计划 ID
            task_id: 子任务 ID
            status: 新状态
            result: 执行结果
            error: 错误信息
        
        Returns:
            True 如果更新成功
        """
        plan = self.get_plan(plan_id)
        if not plan:
            return False
        
        task = next((t for t in plan.sub_tasks if t.task_id == task_id), None)
        if not task:
            return False
        
        if status == SubTaskStatus.COMPLETED:
            task.mark_completed(result)
        elif status == SubTaskStatus.FAILED:
            task.mark_failed(error or "Unknown error")
        elif status == SubTaskStatus.TIMEOUT:
            task.mark_timeout()
        elif status == SubTaskStatus.RUNNING:
            task.mark_running()
        
        # 根据模式处理后续任务
        self._advance_plan(plan)
        
        return True
    
    def _advance_plan(self, plan: FanOutPlan):
        """根据模式推进计划"""
        if plan.mode == FanOutMode.SEQUENTIAL:
            # 顺序模式：找到下一个 pending 任务
            for i, task in enumerate(plan.sub_tasks):
                if task.status in (SubTaskStatus.COMPLETED, SubTaskStatus.FAILED, SubTaskStatus.TIMEOUT):
                    # 启动下一个任务
                    if i + 1 < len(plan.sub_tasks):
                        next_task = plan.sub_tasks[i + 1]
                        if next_task.status == SubTaskStatus.PENDING:
                            next_task.mark_running()
                            break
        
        elif plan.mode == FanOutMode.BATCHED:
            # 批次模式：检查当前批次是否完成
            completed_count = sum(
                1 for t in plan.sub_tasks
                if t.status in (SubTaskStatus.COMPLETED, SubTaskStatus.FAILED, SubTaskStatus.TIMEOUT)
            )
            
            # 启动下一批
            next_batch_start = completed_count
            next_batch_end = min(next_batch_start + plan.batch_size, len(plan.sub_tasks))
            
            for i in range(next_batch_start, next_batch_end):
                task = plan.sub_tasks[i]
                if task.status == SubTaskStatus.PENDING:
                    task.mark_running()
    
    def is_plan_complete(self, plan_id: str) -> bool:
        """检查计划是否完成"""
        plan = self.get_plan(plan_id)
        if not plan:
            return False
        
        return all(
            t.status in (SubTaskStatus.COMPLETED, SubTaskStatus.FAILED, SubTaskStatus.TIMEOUT, SubTaskStatus.CANCELLED)
            for t in plan.sub_tasks
        )
    
    def evaluate_fan_in(self, plan_id: str) -> Dict[str, Any]:
        """
        评估 fan-in 条件是否满足
        
        Args:
            plan_id: 计划 ID
        
        Returns:
            评估结果
        """
        plan = self.get_plan(plan_id)
        if not plan:
            return {"passed": False, "error": "Plan not found"}
        
        sub_tasks = plan.sub_tasks
        if not sub_tasks:
            return {"passed": True, "message": "No sub-tasks"}
        
        completed = [t for t in sub_tasks if t.status == SubTaskStatus.COMPLETED]
        failed = [t for t in sub_tasks if t.status in (SubTaskStatus.FAILED, SubTaskStatus.TIMEOUT)]
        
        passed = False
        reason = ""
        
        if plan.fan_in_mode == FanInMode.ALL_SUCCESS:
            passed = len(completed) == len(sub_tasks)
            reason = f"{len(completed)}/{len(sub_tasks)} completed" if not passed else "All sub-tasks completed"
        
        elif plan.fan_in_mode == FanInMode.ANY_SUCCESS:
            passed = len(completed) > 0
            reason = "At least one sub-task completed" if passed else "No sub-task completed"
        
        elif plan.fan_in_mode == FanInMode.MAJORITY:
            passed = len(completed) > len(sub_tasks) / 2
            reason = f"Majority ({len(completed)}/{len(sub_tasks)}) completed" if passed else "Majority not completed"
        
        elif plan.fan_in_mode == FanInMode.CUSTOM:
            if plan.custom_aggregator:
                passed = plan.custom_aggregator(sub_tasks)
                reason = "Custom aggregation"
            else:
                reason = "No custom aggregator configured"
        
        return {
            "passed": passed,
            "reason": reason,
            "fan_in_mode": plan.fan_in_mode.value,
            "total": len(sub_tasks),
            "completed": len(completed),
            "failed": len(failed),
            "pending": len([t for t in sub_tasks if t.status == SubTaskStatus.PENDING]),
            "running": len([t for t in sub_tasks if t.status == SubTaskStatus.RUNNING]),
        }
    
    def retry_failed(self, plan_id: str) -> int:
        """
        重试失败的子任务
        
        Returns:
            重试的任务数量
        """
        plan = self.get_plan(plan_id)
        if not plan:
            return 0
        
        retried = 0
        for task in plan.sub_tasks:
            if task.status in (SubTaskStatus.FAILED, SubTaskStatus.TIMEOUT):
                if task.can_retry():
                    task.retry()
                    retried += 1
        
        return retried
    
    def get_plan_summary(self, plan_id: str) -> Dict[str, Any]:
        """获取计划摘要"""
        plan = self.get_plan(plan_id)
        if not plan:
            return {"error": "Plan not found"}
        
        status_counts = {}
        for task in plan.sub_tasks:
            status_counts[task.status.value] = status_counts.get(task.status.value, 0) + 1
        
        return {
            "plan_id": plan_id,
            "mode": plan.mode.value,
            "fan_in_mode": plan.fan_in_mode.value,
            "total": len(plan.sub_tasks),
            "status_counts": status_counts,
            "is_complete": self.is_plan_complete(plan_id),
            "fan_in_ready": self.evaluate_fan_in(plan_id)["passed"],
        }
    
    def set_context(self, key: str, value: Any):
        """设置上下文"""
        self.context[key] = value
    
    def get_context(self, key: str, default: Any = None) -> Any:
        """获取上下文"""
        return self.context.get(key, default)
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化控制器状态"""
        return {
            "controller_id": self.controller_id,
            "created_at": self.created_at,
            "plans": {pid: p.to_dict() for pid, p in self.plans.items()},
            "context": self.context,
        }
    
    def save(self, path: Path):
        """保存状态到文件"""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".tmp")
        with open(tmp_path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
        tmp_path.replace(path)
    
    @classmethod
    def load(cls, path: Path) -> "FanOutController":
        """从文件加载状态"""
        with open(path, "r") as f:
            data = json.load(f)
        
        controller = cls(controller_id=data.get("controller_id", "default"))
        controller.created_at = data.get("created_at", datetime.now().isoformat())
        controller.context = data.get("context", {})
        
        for plan_id, plan_data in data.get("plans", {}).items():
            plan = FanOutPlan(
                plan_id=plan_data["plan_id"],
                mode=FanOutMode(plan_data["mode"]),
                batch_size=plan_data.get("batch_size", 1),
                fan_in_mode=FanInMode(plan_data.get("fan_in_mode", "all_success")),
                created_at=plan_data.get("created_at", datetime.now().isoformat()),
                started_at=plan_data.get("started_at"),
                completed_at=plan_data.get("completed_at"),
            )
            for task_data in plan_data.get("sub_tasks", []):
                plan.sub_tasks.append(SubTask.from_dict(task_data))
            controller.plans[plan_id] = plan
        
        return controller
