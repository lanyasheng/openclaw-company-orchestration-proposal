#!/usr/bin/env python3
"""
callback_router.py — Callback Router

回调路由器，管理事件订阅、回调链执行和事件日志。

核心功能：
- 支持事件订阅、过滤
- 回调链执行、错误处理
- 事件日志持久化

这是通用 kernel，不绑定任何业务场景。
增强版：相比 phase_engine.py 中的基础版本，增加了过滤器、优先级、持久化支持。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Callable, Set
from pathlib import Path
import json

__all__ = [
    "CallbackEvent",
    "CallbackHandler",
    "CallbackRouter",
    "CALLBACK_ROUTER_VERSION",
]

CALLBACK_ROUTER_VERSION = "callback_router_v1"


@dataclass
class CallbackEvent:
    """
    回调事件
    
    表示一个可触发回调的事件。
    """
    event_type: str
    payload: Dict[str, Any]
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    source: Optional[str] = None
    event_id: str = field(default_factory=lambda: f"evt_{datetime.now().strftime('%Y%m%d%H%M%S%f')}")
    priority: int = 0  # 优先级，越高越先处理
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": self.event_type,
            "payload": self.payload,
            "timestamp": self.timestamp,
            "source": self.source,
            "event_id": self.event_id,
            "priority": self.priority,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CallbackEvent":
        return cls(
            event_type=data.get("event_type", ""),
            payload=data.get("payload", {}),
            timestamp=data.get("timestamp", datetime.now().isoformat()),
            source=data.get("source"),
            event_id=data.get("event_id", f"evt_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"),
            priority=data.get("priority", 0),
        )


@dataclass
class CallbackHandler:
    """
    回调处理器
    
    封装回调函数及其配置。
    """
    handler_id: str
    event_type: str
    handler: Callable[[CallbackEvent], None]
    priority: int = 0  # 优先级，越高越先执行
    filter_fn: Optional[Callable[[CallbackEvent], bool]] = None  # 过滤器
    once: bool = False  # 是否只执行一次
    enabled: bool = True  # 是否启用
    
    # 执行追踪
    executed_count: int = 0
    last_executed_at: Optional[str] = None
    error_count: int = 0
    
    def should_execute(self, event: CallbackEvent) -> bool:
        """检查是否应该执行此处理器"""
        if not self.enabled:
            return False
        if self.event_type != "*" and self.event_type != event.event_type:
            return False
        if self.filter_fn and not self.filter_fn(event):
            return False
        return True
    
    def execute(self, event: CallbackEvent) -> bool:
        """
        执行回调
        
        Returns:
            True 如果执行成功
        """
        if not self.should_execute(event):
            return False
        
        try:
            self.handler(event)
            self.executed_count += 1
            self.last_executed_at = datetime.now().isoformat()
            return True
        except Exception as e:
            self.error_count += 1
            print(f"Callback handler {self.handler_id} failed: {e}")
            return False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "handler_id": self.handler_id,
            "event_type": self.event_type,
            "priority": self.priority,
            "filter_fn": self.filter_fn.__name__ if self.filter_fn else None,
            "once": self.once,
            "enabled": self.enabled,
            "executed_count": self.executed_count,
            "last_executed_at": self.last_executed_at,
            "error_count": self.error_count,
        }


class CallbackRouter:
    """
    回调路由器
    
    管理回调处理器的注册、注销和事件分发。
    """
    
    def __init__(self, router_id: str = "default"):
        self.router_id = router_id
        self._handlers: Dict[str, List[CallbackHandler]] = {}  # event_type -> handlers
        self._event_log: List[CallbackEvent] = []
        self._max_log_size: int = 1000
        self.context: Dict[str, Any] = {}
        self.created_at = datetime.now().isoformat()
    
    def register(
        self,
        event_type: str,
        handler: Callable[[CallbackEvent], None],
        handler_id: Optional[str] = None,
        priority: int = 0,
        filter_fn: Optional[Callable[[CallbackEvent], bool]] = None,
        once: bool = False,
    ) -> str:
        """
        注册回调处理器
        
        Args:
            event_type: 事件类型（支持 "*" 通配符）
            handler: 回调函数
            handler_id: 处理器 ID（可选，默认自动生成）
            priority: 优先级（越高越先执行）
            filter_fn: 过滤器函数
            once: 是否只执行一次
        
        Returns:
            handler_id: 处理器 ID
        """
        if handler_id is None:
            handler_id = f"handler_{event_type}_{len(self._handlers.get(event_type, []))}"
        
        callback_handler = CallbackHandler(
            handler_id=handler_id,
            event_type=event_type,
            handler=handler,
            priority=priority,
            filter_fn=filter_fn,
            once=once,
        )
        
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        
        self._handlers[event_type].append(callback_handler)
        # 按优先级排序
        self._handlers[event_type].sort(key=lambda h: h.priority, reverse=True)
        
        return handler_id
    
    def unregister(self, handler_id: str, event_type: Optional[str] = None) -> bool:
        """
        注销回调处理器
        
        Args:
            handler_id: 处理器 ID
            event_type: 事件类型（可选，用于加速查找）
        
        Returns:
            True 如果注销成功
        """
        if event_type:
            types_to_check = [event_type]
        else:
            types_to_check = list(self._handlers.keys())
        
        for et in types_to_check:
            handlers = self._handlers.get(et, [])
            for i, h in enumerate(handlers):
                if h.handler_id == handler_id:
                    del handlers[i]
                    return True
        
        return False
    
    def enable(self, handler_id: str, enabled: bool = True) -> bool:
        """启用/禁用处理器"""
        for handlers in self._handlers.values():
            for h in handlers:
                if h.handler_id == handler_id:
                    h.enabled = enabled
                    return True
        return False
    
    def emit(self, event: CallbackEvent) -> Dict[str, Any]:
        """
        触发回调
        
        Args:
            event: 事件
        
        Returns:
            执行结果统计
        """
        # 记录事件
        self._log_event(event)
        
        # 收集所有匹配的处理器
        matching_handlers: List[CallbackHandler] = []
        
        # 特定事件类型的处理器
        for handler in self._handlers.get(event.event_type, []):
            if handler.should_execute(event):
                matching_handlers.append(handler)
        
        # 通配符处理器
        for handler in self._handlers.get("*", []):
            if handler.should_execute(event):
                matching_handlers.append(handler)
        
        # 按优先级排序
        matching_handlers.sort(key=lambda h: h.priority, reverse=True)
        
        # 执行回调
        executed = 0
        failed = 0
        removed_once = []
        
        for handler in matching_handlers:
            success = handler.execute(event)
            if success:
                executed += 1
                if handler.once:
                    removed_once.append(handler)
            else:
                failed += 1
        
        # 移除 once 处理器
        for handler in removed_once:
            self.unregister(handler.handler_id, handler.event_type)
        
        return {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "executed": executed,
            "failed": failed,
        }
    
    def _log_event(self, event: CallbackEvent):
        """记录事件到日志"""
        self._event_log.append(event)
        
        # 限制日志大小
        if len(self._event_log) > self._max_log_size:
            self._event_log = self._event_log[-self._max_log_size:]
    
    def get_event_log(
        self,
        event_type: Optional[str] = None,
        source: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        获取事件日志
        
        Args:
            event_type: 按事件类型过滤
            source: 按来源过滤
            limit: 返回数量限制
        
        Returns:
            事件日志列表
        """
        events = self._event_log
        
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        if source:
            events = [e for e in events if e.source == source]
        
        # 返回最新的
        events = events[-limit:]
        
        return [e.to_dict() for e in events]
    
    def clear_log(self, event_type: Optional[str] = None):
        """
        清空事件日志
        
        Args:
            event_type: 如果指定，只清空该类型的事件
        """
        if event_type:
            self._event_log = [e for e in self._event_log if e.event_type != event_type]
        else:
            self._event_log = []
    
    def list_handlers(self, event_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        列出处理器
        
        Args:
            event_type: 按事件类型过滤
        
        Returns:
            处理器列表
        """
        if event_type:
            handlers = self._handlers.get(event_type, [])
        else:
            handlers = []
            for h_list in self._handlers.values():
                handlers.extend(h_list)
        
        return [h.to_dict() for h in handlers]
    
    def get_handler_stats(self) -> Dict[str, Any]:
        """获取处理器统计"""
        total_handlers = sum(len(h) for h in self._handlers.values())
        total_executions = sum(
            h.executed_count
            for handlers in self._handlers.values()
            for h in handlers
        )
        total_errors = sum(
            h.error_count
            for handlers in self._handlers.values()
            for h in handlers
        )
        
        return {
            "total_handlers": total_handlers,
            "total_executions": total_executions,
            "total_errors": total_errors,
            "event_types": list(self._handlers.keys()),
        }
    
    def set_context(self, key: str, value: Any):
        """设置上下文"""
        self.context[key] = value
    
    def get_context(self, key: str, default: Any = None) -> Any:
        """获取上下文"""
        return self.context.get(key, default)
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化路由器状态"""
        return {
            "router_id": self.router_id,
            "created_at": self.created_at,
            "handlers": self.list_handlers(),
            "event_log": [e.to_dict() for e in self._event_log[-100:]],
            "context": self.context,
            "stats": self.get_handler_stats(),
        }
    
    def save(self, path: Path):
        """保存状态到文件"""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".tmp")
        with open(tmp_path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
        tmp_path.replace(path)
    
    @classmethod
    def load(cls, path: Path) -> "CallbackRouter":
        """从文件加载状态"""
        with open(path, "r") as f:
            data = json.load(f)
        
        router = cls(router_id=data.get("router_id", "default"))
        router.created_at = data.get("created_at", datetime.now().isoformat())
        router.context = data.get("context", {})
        
        # 注意：handler 函数无法从 JSON 恢复，只恢复元数据
        # 实际使用时需要重新注册 handler 函数
        
        return router


# ============== 预定义回调事件类型 ==============

class EventType:
    """预定义事件类型"""
    PHASE_TRANSITION = "phase_transition"
    TASK_STARTED = "task_started"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    GATE_PASSED = "gate_passed"
    GATE_FAILED = "gate_failed"
    DISPATCH_REQUESTED = "dispatch_requested"
    CALLBACK_RECEIVED = "callback_received"
    ACK_SENT = "ack_sent"
    ERROR = "error"


def create_default_router() -> CallbackRouter:
    """创建默认路由器"""
    return CallbackRouter()
