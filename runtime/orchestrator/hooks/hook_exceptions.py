#!/usr/bin/env python3
"""
hook_exceptions.py — 钩子违规异常

核心异常：
- HookViolationError: 钩子违规，enforce 模式下抛出

使用示例：
```python
from hooks.hook_exceptions import HookViolationError
from hooks.hook_config import get_hook_enforce_mode

mode = get_hook_enforce_mode("post_promise_verify")

if mode == "enforce" and not check_passed:
    raise HookViolationError(
        f"违规原因：{reason}",
        hook_name="post_promise_verify",
        metadata={"task_id": task_id}
    )
```
"""

from __future__ import annotations

from typing import Any, Dict, Optional

__all__ = [
    "HookViolationError",
]


class HookViolationError(Exception):
    """
    钩子违规异常
    
    在 enforce 模式下，当钩子检查失败时抛出此异常，阻断主流程。
    
    属性：
        hook_name: 触发违规的钩子名称
        message: 违规原因描述
        metadata: 附加元数据（task_id, receipt_id 等）
    
    使用示例：
    ```python
    try:
        # 钩子检查
        if not anchor_ok:
            raise HookViolationError(
                "承诺必须有执行锚点",
                hook_name="post_promise_verify",
                metadata={"task_id": "task_001"}
            )
    except HookViolationError as e:
        # 处理违规：记录日志/发送告警/阻断流程
        log_violation(e)
        raise  # 继续向上传播，阻断主流程
    ```
    """
    
    def __init__(
        self,
        message: str,
        hook_name: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """
        初始化钩子违规异常
        
        Args:
            message: 违规原因描述
            hook_name: 触发违规的钩子名称
            metadata: 附加元数据（可选）
        """
        super().__init__(message)
        self.hook_name = hook_name
        self.metadata = metadata or {}
        self.message = message
    
    def __str__(self) -> str:
        """返回人类可读的异常描述"""
        if self.hook_name:
            return f"[{self.hook_name}] {self.message}"
        return self.message
    
    def __repr__(self) -> str:
        """返回调试表示"""
        return (
            f"HookViolationError("
            f"message={self.message!r}, "
            f"hook_name={self.hook_name!r}, "
            f"metadata={self.metadata!r})"
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """
        序列化为字典
        
        Returns:
            包含异常信息的字典
        """
        return {
            "error_type": "HookViolationError",
            "hook_name": self.hook_name,
            "message": self.message,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HookViolationError":
        """
        从字典反序列化
        
        Args:
            data: 包含异常信息的字典
        
        Returns:
            HookViolationError 实例
        """
        return cls(
            message=data.get("message", ""),
            hook_name=data.get("hook_name", ""),
            metadata=data.get("metadata"),
        )
