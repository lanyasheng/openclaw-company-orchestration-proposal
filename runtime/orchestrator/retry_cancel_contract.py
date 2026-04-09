#!/usr/bin/env python3
"""
retry_cancel_contract.py — Retry/Cancel Contract for Workflow Execution

目标：提供统一的 retry/cancel 语义，与 ContinuationContract 对齐。

这是 Deer-Flow 借鉴线 Batch E 的实现：
- RetryContract: 定义重试策略（次数/间隔/条件）
- CancelContract: 定义取消语义（原因/清理动作）
- RetryCancelManager: 管理 retry/cancel 状态

设计原则：
1. 与 ContinuationContract 语义对齐
2. 不破坏现有执行路径
3. 支持声明式配置
4. 可观测、可审计

使用示例：
```python
from retry_cancel_contract import RetryContract, CancelContract, RetryCancelManager

# 创建 retry contract
retry = RetryContract(
    task_id="task_123",
    max_retries=3,
    retry_delay_seconds=60,
    retry_on=["timeout", "transient_error"],
)

# 创建 cancel contract
cancel = CancelContract(
    task_id="task_123",
    reason="user_requested",
    cleanup_actions=["notify_upstream", "archive_state"],
)

# 管理 retry/cancel 状态
manager = RetryCancelManager()
manager.register_retry(retry)
manager.register_cancel(cancel)

# 检查是否可以重试
can_retry, reason = manager.can_retry("task_123")
if can_retry:
    manager.record_retry("task_123")
```
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Set, Tuple

__all__ = [
    "RETRY_CANCEL_CONTRACT_VERSION",
    "RetryReason",
    "CancelReason",
    "RetryContract",
    "CancelContract",
    "RetryCancelState",
    "RetryCancelManager",
    "create_retry_contract",
    "create_cancel_contract",
    "get_retry_cancel_state",
    "can_retry_task",
    "cancel_task",
]

RETRY_CANCEL_CONTRACT_VERSION = "retry_cancel_contract_v1"


# ============ 枚举定义 ============


class RetryReason(str, Enum):
    """重试原因"""
    TIMEOUT = "timeout"
    TRANSIENT_ERROR = "transient_error"
    RATE_LIMITED = "rate_limited"
    NETWORK_ERROR = "network_error"
    RESOURCE_UNAVAILABLE = "resource_unavailable"
    MANUAL_RETRY = "manual_retry"
    CUSTOM = "custom"


class CancelReason(str, Enum):
    """取消原因"""
    USER_REQUESTED = "user_requested"
    UPSTREAM_FAILED = "upstream_failed"
    DEPENDENCY_FAILED = "dependency_failed"
    TIMEOUT_EXCEEDED = "timeout_exceeded"
    RESOURCE_EXHAUSTED = "resource_exhausted"
    POLICY_VIOLATION = "policy_violation"
    MANUAL_CANCEL = "manual_cancel"
    CUSTOM = "custom"


class RetryCancelStatus(str, Enum):
    """Retry/Cancel 状态"""
    PENDING = "pending"
    RETRYING = "retrying"
    CANCELLED = "cancelled"
    EXHAUSTED = "exhausted"  # 重试次数用尽
    COMPLETED = "completed"


# ============ Retry Contract ============


@dataclass
class RetryContract:
    """
    重试契约 — 定义任务的重试策略。
    
    核心字段：
    - task_id: 任务 ID
    - max_retries: 最大重试次数
    - retry_delay_seconds: 重试间隔（秒）
    - retry_on: 触发重试的错误类型列表
    - exponential_backoff: 是否使用指数退避
    - backoff_multiplier: 退避倍数（默认 2.0）
    - max_delay_seconds: 最大延迟（秒）
    - metadata: 额外元数据
    
    重试条件：
    - retry_count < max_retries
    - 错误类型在 retry_on 列表中
    - 未超过 max_delay_seconds
    """
    task_id: str
    max_retries: int = 3
    retry_delay_seconds: int = 60
    retry_on: List[RetryReason] = field(default_factory=lambda: [RetryReason.TIMEOUT, RetryReason.TRANSIENT_ERROR])
    exponential_backoff: bool = True
    backoff_multiplier: float = 2.0
    max_delay_seconds: int = 3600
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        # 转换字符串为枚举
        self.retry_on = [
            RetryReason(r) if isinstance(r, str) else r
            for r in self.retry_on
        ]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "contract_version": RETRY_CANCEL_CONTRACT_VERSION,
            "task_id": self.task_id,
            "max_retries": self.max_retries,
            "retry_delay_seconds": self.retry_delay_seconds,
            "retry_on": [r.value for r in self.retry_on],
            "exponential_backoff": self.exponential_backoff,
            "backoff_multiplier": self.backoff_multiplier,
            "max_delay_seconds": self.max_delay_seconds,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RetryContract":
        retry_on = data.get("retry_on", [])
        return cls(
            task_id=data.get("task_id", ""),
            max_retries=data.get("max_retries", 3),
            retry_delay_seconds=data.get("retry_delay_seconds", 60),
            retry_on=retry_on,
            exponential_backoff=data.get("exponential_backoff", True),
            backoff_multiplier=data.get("backoff_multiplier", 2.0),
            max_delay_seconds=data.get("max_delay_seconds", 3600),
            metadata=data.get("metadata", {}),
        )
    
    def get_retry_delay(self, retry_count: int) -> int:
        """
        计算重试延迟。
        
        Args:
            retry_count: 当前重试次数
        
        Returns:
            延迟秒数
        """
        if self.exponential_backoff:
            delay = self.retry_delay_seconds * (self.backoff_multiplier ** retry_count)
            return min(int(delay), self.max_delay_seconds)
        else:
            return self.retry_delay_seconds
    
    def should_retry(self, error_reason: RetryReason, retry_count: int) -> bool:
        """
        判断是否应该重试。
        
        Args:
            error_reason: 错误原因
            retry_count: 当前重试次数
        
        Returns:
            True 如果应该重试
        """
        if retry_count >= self.max_retries:
            return False
        
        return error_reason in self.retry_on


# ============ Cancel Contract ============


@dataclass
class CancelContract:
    """
    取消契约 — 定义任务的取消语义。
    
    核心字段：
    - task_id: 任务 ID
    - reason: 取消原因
    - message: 取消消息（人类可读）
    - cleanup_actions: 清理动作列表
    - notify: 通知列表（上游/下游/所有者）
    - cascade: 是否级联取消子任务
    - metadata: 额外元数据
    
    清理动作：
    - archive_state: 归档状态
    - release_resources: 释放资源
    - notify_upstream: 通知上游
    - notify_downstream: 通知下游
    - rollback_changes: 回滚变更
    """
    task_id: str
    reason: CancelReason
    message: str = ""
    cleanup_actions: List[str] = field(default_factory=list)
    notify: List[str] = field(default_factory=list)
    cascade: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        # 转换字符串为枚举
        if isinstance(self.reason, str):
            self.reason = CancelReason(self.reason)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "contract_version": RETRY_CANCEL_CONTRACT_VERSION,
            "task_id": self.task_id,
            "reason": self.reason.value,
            "message": self.message,
            "cleanup_actions": self.cleanup_actions,
            "notify": self.notify,
            "cascade": self.cascade,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CancelContract":
        reason = data.get("reason", CancelReason.MANUAL_CANCEL)
        return cls(
            task_id=data.get("task_id", ""),
            reason=CancelReason(reason) if isinstance(reason, str) else reason,
            message=data.get("message", ""),
            cleanup_actions=data.get("cleanup_actions", []),
            notify=data.get("notify", []),
            cascade=data.get("cascade", False),
            metadata=data.get("metadata", {}),
        )


# ============ RetryCancel State ============


@dataclass
class RetryCancelState:
    """
    Retry/Cancel 状态 — 记录任务的 retry/cancel 历史。
    
    核心字段：
    - task_id: 任务 ID
    - status: 当前状态
    - retry_contract: 重试契约（如果有）
    - cancel_contract: 取消契约（如果有）
    - retry_count: 当前重试次数
    - retry_history: 重试历史记录
    - cancelled_at: 取消时间
    - created_at: 创建时间
    - updated_at: 更新时间
    """
    task_id: str
    status: RetryCancelStatus = RetryCancelStatus.PENDING
    retry_contract: Optional[RetryContract] = None
    cancel_contract: Optional[CancelContract] = None
    retry_count: int = 0
    retry_history: List[Dict[str, Any]] = field(default_factory=list)
    cancelled_at: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "state_version": RETRY_CANCEL_CONTRACT_VERSION,
            "task_id": self.task_id,
            "status": self.status.value,
            "retry_contract": self.retry_contract.to_dict() if self.retry_contract else None,
            "cancel_contract": self.cancel_contract.to_dict() if self.cancel_contract else None,
            "retry_count": self.retry_count,
            "retry_history": self.retry_history,
            "cancelled_at": self.cancelled_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RetryCancelState":
        retry_contract_data = data.get("retry_contract")
        cancel_contract_data = data.get("cancel_contract")
        
        return cls(
            task_id=data.get("task_id", ""),
            status=RetryCancelStatus(data.get("status", "pending")),
            retry_contract=RetryContract.from_dict(retry_contract_data) if retry_contract_data else None,
            cancel_contract=CancelContract.from_dict(cancel_contract_data) if cancel_contract_data else None,
            retry_count=data.get("retry_count", 0),
            retry_history=data.get("retry_history", []),
            cancelled_at=data.get("cancelled_at"),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )


# ============ RetryCancel Manager ============


class RetryCancelManager:
    """
    Retry/Cancel 管理器 — 管理任务的 retry/cancel 状态。
    
    核心方法：
    - register_retry(contract): 注册重试契约
    - register_cancel(contract): 注册取消契约
    - can_retry(task_id, error_reason): 检查是否可以重试
    - record_retry(task_id, error_reason, message): 记录重试
    - cancel(task_id, reason, message): 取消任务
    - get_state(task_id): 获取状态
    - cleanup(task_id): 清理状态
    
    设计原则：
    - 与 ContinuationContract 语义对齐
    - 线程安全
    - 支持持久化
    """
    
    def __init__(self, state_dir: Optional[Path] = None):
        """
        初始化管理器。
        
        Args:
            state_dir: 状态文件目录（默认：~/.openclaw/shared-context/retry_cancel_states）
        """
        self.state_dir = state_dir or Path.home() / ".openclaw" / "shared-context" / "retry_cancel_states"
        self._ensure_state_dir()
        
        # 内存缓存
        self._cache: Dict[str, RetryCancelState] = {}
        self._lock = threading.Lock()
    
    def _ensure_state_dir(self):
        """确保状态目录存在"""
        self.state_dir.mkdir(parents=True, exist_ok=True)
    
    def _state_file(self, task_id: str) -> Path:
        """返回状态文件路径"""
        return self.state_dir / f"{task_id}.json"
    
    def _iso_now(self) -> str:
        """返回 ISO-8601 时间戳"""
        return datetime.now(timezone.utc).isoformat()
    
    def _persist_state(self, state: RetryCancelState):
        """持久化状态到文件"""
        state_path = self._state_file(state.task_id)
        tmp_path = state_path.with_suffix(".tmp")
        with open(tmp_path, "w") as f:
            json.dump(state.to_dict(), f, indent=2)
        tmp_path.replace(state_path)
    
    def _load_state(self, task_id: str) -> Optional[RetryCancelState]:
        """从文件加载状态"""
        state_path = self._state_file(task_id)
        if not state_path.exists():
            return None
        
        try:
            with open(state_path, "r") as f:
                data = json.load(f)
            return RetryCancelState.from_dict(data)
        except (json.JSONDecodeError, KeyError):
            return None
    
    def register_retry(self, contract: RetryContract) -> RetryCancelState:
        """
        注册重试契约。
        
        Args:
            contract: 重试契约
        
        Returns:
            RetryCancelState
        """
        now = self._iso_now()
        state = RetryCancelState(
            task_id=contract.task_id,
            status=RetryCancelStatus.PENDING,
            retry_contract=contract,
            created_at=now,
            updated_at=now,
        )
        
        with self._lock:
            self._cache[contract.task_id] = state
        
        self._persist_state(state)
        return state
    
    def register_cancel(self, contract: CancelContract) -> RetryCancelState:
        """
        注册取消契约。
        
        Args:
            contract: 取消契约
        
        Returns:
            RetryCancelState
        """
        with self._lock:
            state = self._cache.get(contract.task_id)
            if not state:
                state = self._load_state(contract.task_id)
            
            if not state:
                now = self._iso_now()
                state = RetryCancelState(
                    task_id=contract.task_id,
                    status=RetryCancelStatus.CANCELLED,
                    cancel_contract=contract,
                    cancelled_at=now,
                    created_at=now,
                    updated_at=now,
                )
            else:
                state.status = RetryCancelStatus.CANCELLED
                state.cancel_contract = contract
                state.cancelled_at = self._iso_now()
                state.updated_at = state.cancelled_at
            
            self._cache[contract.task_id] = state
        
        self._persist_state(state)
        return state
    
    def can_retry(self, task_id: str, error_reason: Optional[RetryReason] = None) -> Tuple[bool, str]:
        """
        检查是否可以重试。
        
        Args:
            task_id: 任务 ID
            error_reason: 错误原因（可选）
        
        Returns:
            (can_retry, reason) 元组
        """
        state = self._get_state(task_id)
        if not state:
            return False, "No retry contract found"
        
        if state.status == RetryCancelStatus.CANCELLED:
            return False, "Task is cancelled"
        
        if state.status == RetryCancelStatus.EXHAUSTED:
            return False, "Retry count exhausted"
        
        if state.status == RetryCancelStatus.COMPLETED:
            return False, "Task is completed"
        
        if not state.retry_contract:
            return False, "No retry contract registered"
        
        if error_reason and not state.retry_contract.should_retry(error_reason, state.retry_count):
            return False, f"Error reason {error_reason.value} not in retry list or max retries reached"
        
        return True, "Can retry"
    
    def record_retry(
        self,
        task_id: str,
        error_reason: RetryReason,
        message: str = "",
    ) -> Optional[RetryCancelState]:
        """
        记录重试。
        
        Args:
            task_id: 任务 ID
            error_reason: 错误原因
            message: 重试消息
        
        Returns:
            更新后的状态，不存在则返回 None
        """
        with self._lock:
            state = self._cache.get(task_id)
            if not state:
                state = self._load_state(task_id)
            
            if not state or not state.retry_contract:
                return None
            
            # 更新状态
            state.status = RetryCancelStatus.RETRYING
            state.retry_count += 1
            state.retry_history.append({
                "retry_count": state.retry_count,
                "error_reason": error_reason.value,
                "message": message,
                "timestamp": self._iso_now(),
                "next_delay_seconds": state.retry_contract.get_retry_delay(state.retry_count),
            })
            state.updated_at = self._iso_now()
            
            # 检查是否用尽重试次数
            if state.retry_count >= state.retry_contract.max_retries:
                state.status = RetryCancelStatus.EXHAUSTED
            
            self._cache[task_id] = state
        
        self._persist_state(state)
        return state
    
    def cancel(
        self,
        task_id: str,
        reason: CancelReason,
        message: str = "",
        cleanup_actions: Optional[List[str]] = None,
    ) -> Optional[RetryCancelState]:
        """
        取消任务。
        
        Args:
            task_id: 任务 ID
            reason: 取消原因
            message: 取消消息
            cleanup_actions: 清理动作列表
        
        Returns:
            更新后的状态，不存在则返回 None
        """
        contract = CancelContract(
            task_id=task_id,
            reason=reason,
            message=message,
            cleanup_actions=cleanup_actions or [],
        )
        return self.register_cancel(contract)
    
    def get_state(self, task_id: str) -> Optional[RetryCancelState]:
        """
        获取状态（优先内存，回退文件）。
        
        Args:
            task_id: 任务 ID
        
        Returns:
            RetryCancelState，不存在则返回 None
        """
        return self._get_state(task_id)
    
    def _get_state(self, task_id: str) -> Optional[RetryCancelState]:
        """内部获取状态方法"""
        with self._lock:
            if task_id in self._cache:
                return self._cache[task_id]
        
        return self._load_state(task_id)
    
    def cleanup(self, task_id: str) -> bool:
        """
        清理状态（从内存移除，保留文件）。
        
        Args:
            task_id: 任务 ID
        
        Returns:
            True 如果清理成功
        """
        with self._lock:
            state = self._cache.get(task_id)
            if not state or state.status not in (RetryCancelStatus.CANCELLED, RetryCancelStatus.EXHAUSTED, RetryCancelStatus.COMPLETED):
                return False
            
            del self._cache[task_id]
            return True
    
    def list_states(
        self,
        status: Optional[RetryCancelStatus] = None,
        limit: int = 100,
    ) -> List[RetryCancelState]:
        """
        列出状态。
        
        Args:
            status: 按状态过滤
            limit: 最大返回数量
        
        Returns:
            RetryCancelState 列表
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


# ============ 便捷函数 ============

_default_manager: Optional[RetryCancelManager] = None


def get_manager() -> RetryCancelManager:
    """获取默认管理器（单例）"""
    global _default_manager
    if _default_manager is None:
        _default_manager = RetryCancelManager()
    return _default_manager


def create_retry_contract(
    task_id: str,
    max_retries: int = 3,
    retry_delay_seconds: int = 60,
    retry_on: Optional[List[str]] = None,
    exponential_backoff: bool = True,
) -> RetryContract:
    """便捷函数：创建重试契约"""
    return RetryContract(
        task_id=task_id,
        max_retries=max_retries,
        retry_delay_seconds=retry_delay_seconds,
        retry_on=retry_on or ["timeout", "transient_error"],
        exponential_backoff=exponential_backoff,
    )


def create_cancel_contract(
    task_id: str,
    reason: str = "manual_cancel",
    message: str = "",
    cleanup_actions: Optional[List[str]] = None,
) -> CancelContract:
    """便捷函数：创建取消契约"""
    return CancelContract(
        task_id=task_id,
        reason=CancelReason(reason),
        message=message,
        cleanup_actions=cleanup_actions or [],
    )


def get_retry_cancel_state(task_id: str) -> Optional[RetryCancelState]:
    """便捷函数：获取状态"""
    return get_manager().get_state(task_id)


def can_retry_task(task_id: str, error_reason: str = "timeout") -> Tuple[bool, str]:
    """便捷函数：检查是否可以重试"""
    return get_manager().can_retry(task_id, RetryReason(error_reason))


def cancel_task(
    task_id: str,
    reason: str = "manual_cancel",
    message: str = "",
    cleanup_actions: Optional[List[str]] = None,
) -> Optional[RetryCancelState]:
    """便捷函数：取消任务"""
    return get_manager().cancel(task_id, CancelReason(reason), message, cleanup_actions)


# ============ CLI 入口 ============

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python retry_cancel_contract.py retry <task_id> [max_retries] [delay_seconds]")
        print("  python retry_cancel_contract.py cancel <task_id> [reason] [message]")
        print("  python retry_cancel_contract.py get <task_id>")
        print("  python retry_cancel_contract.py can-retry <task_id> [error_reason]")
        print("  python retry_cancel_contract.py list [--status <status>]")
        sys.exit(1)
    
    cmd = sys.argv[1]
    manager = get_manager()
    
    if cmd == "retry":
        if len(sys.argv) < 3:
            print("Error: missing task_id")
            sys.exit(1)
        
        task_id = sys.argv[2]
        max_retries = int(sys.argv[3]) if len(sys.argv) > 3 else 3
        delay_seconds = int(sys.argv[4]) if len(sys.argv) > 4 else 60
        
        contract = create_retry_contract(task_id, max_retries, delay_seconds)
        state = manager.register_retry(contract)
        print(json.dumps(state.to_dict(), indent=2))
    
    elif cmd == "cancel":
        if len(sys.argv) < 3:
            print("Error: missing task_id")
            sys.exit(1)
        
        task_id = sys.argv[2]
        reason = sys.argv[3] if len(sys.argv) > 3 else "manual_cancel"
        message = sys.argv[4] if len(sys.argv) > 4 else ""
        
        state = manager.cancel(task_id, CancelReason(reason), message)
        if state:
            print(json.dumps(state.to_dict(), indent=2))
        else:
            print(f"Task not found: {task_id}")
            sys.exit(1)
    
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
    
    elif cmd == "can-retry":
        if len(sys.argv) < 3:
            print("Error: missing task_id")
            sys.exit(1)
        
        task_id = sys.argv[2]
        error_reason = sys.argv[3] if len(sys.argv) > 3 else "timeout"
        
        can_retry, reason = manager.can_retry(task_id, RetryReason(error_reason))
        print(json.dumps({
            "task_id": task_id,
            "can_retry": can_retry,
            "reason": reason,
        }, indent=2))
    
    elif cmd == "list":
        status = None
        if "--status" in sys.argv:
            idx = sys.argv.index("--status")
            if idx + 1 < len(sys.argv):
                status = RetryCancelStatus(sys.argv[idx + 1])
        
        states = manager.list_states(status)
        print(json.dumps([s.to_dict() for s in states], indent=2))
    
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
