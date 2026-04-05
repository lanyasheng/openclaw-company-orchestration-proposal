#!/usr/bin/env python3
"""
post_promise_verify_hook.py — 主 agent 宣称"进行中"时验证执行锚点钩子

目标：解决"空承诺"问题，确保主 agent 宣称任务"进行中"时必须有真实的
执行锚点（dispatch_id / session_id / tmux_session），而不是口头承诺。

核心规则：
1. 主 agent 宣称"进行中/processing/running"时，必须有对应的执行锚点
2. 锚点必须是真实的 artifact（dispatch / session / tmux）
3. 无锚点则标记为"empty_promise"，触发告警并拦截回复

集成点：
- orchestrator.py: 会话回复前验证
- auto_dispatch.py: dispatch 创建后验证
- watchdog.py: 定期巡检承诺状态

使用示例：
```python
from hooks.post_promise_verify_hook import (
    verify_promise_has_anchor,
    validate_promise_anchor,
)

# 验证承诺是否有锚点
result = verify_promise_has_anchor(session_context, task_registry)
if not result.has_anchor:
    # 拦截回复，要求补充锚点
    block_reply(f"承诺必须有执行锚点：{result.missing_reason}")
```
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

__all__ = [
    "HOOK_VERSION",
    "AnchorStatus",
    "PromiseAnchorCheck",
    "PostPromiseVerifyHook",
    "verify_promise_has_anchor",
    "validate_promise_anchor",
    "PROMISE_AUDIT_DIR",
]

HOOK_VERSION = "post_promise_verify_v1"

AnchorStatus = Literal[
    "anchor_verified",          # 锚点已验证
    "anchor_missing",          # 缺少锚点
    "anchor_invalid",          # 锚点无效
    "anchor_expired",          # 锚点过期
    "promise_not_detected",    # 未检测到承诺
]

# Audit 日志目录
PROMISE_AUDIT_DIR = Path(
    os.environ.get(
        "OPENCLAW_PROMISE_AUDIT_DIR",
        Path.home() / ".openclaw" / "shared-context" / "promise_audits",
    )
)


def _ensure_audit_dir() -> None:
    """确保 audit 目录存在"""
    PROMISE_AUDIT_DIR.mkdir(parents=True, exist_ok=True)


def _iso_now() -> str:
    """返回当前 ISO-8601 时间戳"""
    return datetime.now(timezone.utc).isoformat()


def _generate_audit_id() -> str:
    """生成 stable audit ID"""
    import uuid
    return f"promise_audit_{uuid.uuid4().hex[:12]}"


@dataclass
class PromiseAnchorCheck:
    """
    承诺锚点检查结果
    
    核心字段：
    - has_anchor: 是否有有效锚点
    - status: 锚点状态
    - anchor_type: 锚点类型
    - anchor_value: 锚点值
    - promise_detected: 是否检测到承诺语句
    - missing_reason: 缺失原因
    - suggested_fix: 建议修复方案
    """
    has_anchor: bool
    status: AnchorStatus
    anchor_type: Optional[str] = None
    anchor_value: Optional[str] = None
    promise_detected: bool = False
    promise_text: str = ""
    missing_reason: str = ""
    suggested_fix: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "has_anchor": self.has_anchor,
            "status": self.status,
            "anchor_type": self.anchor_type,
            "anchor_value": self.anchor_value,
            "promise_detected": self.promise_detected,
            "promise_text": self.promise_text,
            "missing_reason": self.missing_reason,
            "suggested_fix": self.suggested_fix,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PromiseAnchorCheck":
        return cls(
            has_anchor=data.get("has_anchor", False),
            status=data.get("status", "anchor_missing"),
            anchor_type=data.get("anchor_type"),
            anchor_value=data.get("anchor_value"),
            promise_detected=data.get("promise_detected", False),
            promise_text=data.get("promise_text", ""),
            missing_reason=data.get("missing_reason", ""),
            suggested_fix=data.get("suggested_fix", ""),
            metadata=data.get("metadata", {}),
        )


@dataclass
class PostPromiseVerifyHook:
    """
    承诺验证钩子
    
    核心方法：
    - detect_promise(): 检测会话中是否包含承诺语句
    - verify_anchor(): 验证承诺是否有对应锚点
    - validate_anchor_format(): 验证锚点格式
    - audit(): 记录审计日志
    """
    
    # 承诺关键词（中文）
    PROMISE_KEYWORDS_CN = [
        "进行中",
        "正在处理",
        "执行中",
        "开始做",
        "已启动",
        "推进中",
        "处理中",
        "running",
        "processing",
        "in progress",
        "working on",
        "started",
    ]
    
    # 承诺关键词（英文）
    PROMISE_KEYWORDS_EN = [
        "running",
        "processing",
        "in progress",
        "working on",
        "started",
        "executing",
    ]
    
    # 有效锚点类型
    VALID_ANCHOR_TYPES = [
        "dispatch_id",
        "session_id",
        "tmux_session",
        "subagent_id",
        "task_id",
    ]
    
    # 锚点值格式验证正则
    ANCHOR_PATTERNS = {
        "dispatch_id": r"^dispatch_[a-f0-9]{12}$",
        "session_id": r"^[a-f0-9-]{36}$|^[a-z0-9-]+$",
        "tmux_session": r"^cc-[a-z0-9-]+$",
        "subagent_id": r"^[a-f0-9-]{36}$",
        "task_id": r"^task_[a-zA-Z0-9_-]+$",
    }
    
    def detect_promise(
        self,
        session_messages: List[Dict[str, Any]],
        lookback: int = 5,
    ) -> Tuple[bool, str]:
        """
        检测会话中是否包含承诺语句
        
        Args:
            session_messages: 会话消息列表
            lookback: 回看消息数量
        
        Returns:
            (是否检测到承诺，承诺文本)
        """
        recent_messages = session_messages[-lookback:] if len(session_messages) >= lookback else session_messages
        
        for msg in reversed(recent_messages):
            content = msg.get("content", "") or ""
            role = msg.get("role", "")
            
            # 只检查 assistant 的消息
            if role != "assistant":
                continue
            
            # 检查是否包含承诺关键词
            for keyword in self.PROMISE_KEYWORDS_CN + self.PROMISE_KEYWORDS_EN:
                if keyword.lower() in content.lower():
                    # 排除否定句
                    if "不" in content or "no" in content.lower() or "not" in content.lower():
                        continue
                    return True, content[:200]  # 截取前 200 字符
        
        return False, ""
    
    def verify_anchor(
        self,
        task_context: Dict[str, Any],
        dispatch_registry: Optional[Dict[str, Any]] = None,
        session_registry: Optional[Dict[str, Any]] = None,
        enforce_mode_override: Optional[str] = None,
    ) -> PromiseAnchorCheck:
        """
        验证承诺是否有对应锚点
        
        Args:
            task_context: 任务上下文（包含 promise_anchor 字段）
            dispatch_registry: Dispatch 注册表（用于验证 dispatch_id）
            session_registry: Session 注册表（用于验证 session_id）
            enforce_mode_override: 可选的 enforce mode 覆盖（"audit"/"warn"/"enforce"）
        
        Returns:
            PromiseAnchorCheck 检查结果
        
        Raises:
            HookViolationError: enforce 模式下锚点验证失败时抛出
        """
        # 导入配置和异常模块（延迟导入，避免循环依赖）
        from .hook_config import get_hook_enforce_mode
        from .hook_exceptions import HookViolationError
        
        # 获取 enforce mode（支持覆盖）
        mode = enforce_mode_override if enforce_mode_override in ["audit", "warn", "enforce"] else get_hook_enforce_mode("post_promise_verify")
        
        promise_anchor = task_context.get("promise_anchor", {})
        
        # Check 1: 是否有 promise_anchor
        if not promise_anchor:
            result = PromiseAnchorCheck(
                has_anchor=False,
                status="anchor_missing",
                missing_reason="缺少 promise_anchor 字段",
                suggested_fix="在 task_context 中添加 promise_anchor，包含 anchor_type 和 anchor_value",
            )
            # Enforce mode 处理
            self._handle_violation(mode, result, task_context)
            return result
        
        anchor_type = promise_anchor.get("anchor_type", "")
        anchor_value = promise_anchor.get("anchor_value", "")
        
        # Check 2: anchor_type 是否有效
        if anchor_type not in self.VALID_ANCHOR_TYPES:
            result = PromiseAnchorCheck(
                has_anchor=False,
                status="anchor_invalid",
                anchor_type=anchor_type,
                anchor_value=anchor_value,
                missing_reason=f"无效的锚点类型：{anchor_type}",
                suggested_fix=f"使用有效的锚点类型：{self.VALID_ANCHOR_TYPES}",
            )
            # Enforce mode 处理
            self._handle_violation(mode, result, task_context)
            return result
        
        # Check 3: anchor_value 是否非空
        if not anchor_value or anchor_value.strip() == "":
            result = PromiseAnchorCheck(
                has_anchor=False,
                status="anchor_missing",
                anchor_type=anchor_type,
                missing_reason="锚点值为空",
                suggested_fix="提供非空的 anchor_value",
            )
            # Enforce mode 处理
            self._handle_violation(mode, result, task_context)
            return result
        
        # Check 4: 锚点格式验证
        format_ok, format_reason = self._validate_anchor_format(anchor_type, anchor_value)
        if not format_ok:
            result = PromiseAnchorCheck(
                has_anchor=False,
                status="anchor_invalid",
                anchor_type=anchor_type,
                anchor_value=anchor_value,
                missing_reason=f"锚点格式无效：{format_reason}",
                suggested_fix=f"锚点值必须符合 {anchor_type} 的格式规范",
            )
            # Enforce mode 处理
            self._handle_violation(mode, result, task_context)
            return result
        
        # Check 5: 验证锚点是否存在于注册表中（可选）
        registry_ok = True
        registry_reason = ""
        
        if anchor_type == "dispatch_id" and dispatch_registry:
            registry_ok = anchor_value in dispatch_registry
            registry_reason = f"Dispatch {anchor_value} 不存在于注册表" if not registry_ok else ""
        elif anchor_type == "session_id" and session_registry:
            registry_ok = anchor_value in session_registry
            registry_reason = f"Session {anchor_value} 不存在于注册表" if not registry_ok else ""
        
        if not registry_ok:
            result = PromiseAnchorCheck(
                has_anchor=False,
                status="anchor_missing",
                anchor_type=anchor_type,
                anchor_value=anchor_value,
                missing_reason=registry_reason,
                suggested_fix="确保锚点对应的 artifact 已创建并注册",
            )
            # Enforce mode 处理
            self._handle_violation(mode, result, task_context)
            return result
        
        # 所有检查通过
        return PromiseAnchorCheck(
            has_anchor=True,
            status="anchor_verified",
            anchor_type=anchor_type,
            anchor_value=anchor_value,
            metadata={
                "promised_at": promise_anchor.get("promised_at", ""),
                "promised_eta": promise_anchor.get("promised_eta", ""),
            },
        )
    
    def _handle_violation(
        self,
        mode: str,
        result: PromiseAnchorCheck,
        task_context: Dict[str, Any],
    ) -> None:
        """
        处理锚点违规
        
        Args:
            mode: enforce mode ("audit"/"warn"/"enforce")
            result: 锚点检查结果
            task_context: 任务上下文
        
        Raises:
            HookViolationError: enforce 模式下抛出
        """
        from .hook_exceptions import HookViolationError
        from .hook_integrations import log_anchor_violation
        
        task_id = task_context.get("task_id", "unknown")
        
        if mode == "enforce":
            # 抛出异常，阻断主流程
            raise HookViolationError(
                f"承诺必须有执行锚点：{result.missing_reason}",
                hook_name="post_promise_verify",
                metadata={
                    "task_id": task_id,
                    "anchor_type": result.anchor_type,
                    "anchor_value": result.anchor_value,
                    "status": result.status,
                },
            )
        elif mode == "warn":
            # 记录告警（不阻断）
            import warnings
            warnings.warn(f"⚠️ 空承诺检测 [{task_id}]: {result.missing_reason}")
        
        # mode == "audit": 只记录审计日志（现有行为）
        # 调用现有审计日志记录
        log_anchor_violation(task_id, result.missing_reason, {
            "anchor_type": result.anchor_type,
            "anchor_value": result.anchor_value,
            "status": result.status,
        })
    
    def _validate_anchor_format(
        self,
        anchor_type: str,
        anchor_value: str,
    ) -> Tuple[bool, str]:
        """
        验证锚点值格式
        
        Args:
            anchor_type: 锚点类型
            anchor_value: 锚点值
        
        Returns:
            (是否有效，原因)
        """
        pattern = self.ANCHOR_PATTERNS.get(anchor_type)
        if not pattern:
            return True, ""  # 未知类型，跳过格式验证
        
        if re.match(pattern, anchor_value):
            return True, ""
        else:
            return False, f"不符合 {anchor_type} 的格式模式"
    
    def check_promise_timeout(
        self,
        promise_anchor: Dict[str, Any],
        threshold_minutes: int = 30,
    ) -> Tuple[bool, str]:
        """
        检查承诺是否超时
        
        Args:
            promise_anchor: 承诺锚点（包含 promised_eta）
            threshold_minutes: 超时阈值（分钟）
        
        Returns:
            (是否超时，超时信息)
        """
        promised_eta = promise_anchor.get("promised_eta", "")
        if not promised_eta:
            return False, "无 promised_eta 字段"
        
        try:
            eta_dt = datetime.fromisoformat(promised_eta)
            now_dt = datetime.now()
            delta = now_dt - eta_dt
            
            if delta.total_seconds() > threshold_minutes * 60:
                return True, f"已超时 {int(delta.total_seconds() / 60)} 分钟（阈值：{threshold_minutes} 分钟）"
            else:
                return False, "未超时"
        except (ValueError, TypeError) as e:
            return False, f"解析 promised_eta 失败：{e}"
    
    def audit(
        self,
        task_id: str,
        check_result: PromiseAnchorCheck,
        session_messages: Optional[List[Dict[str, Any]]] = None,
    ) -> Path:
        """
        记录审计日志
        
        Args:
            task_id: 任务 ID
            check_result: 锚点检查结果
            session_messages: 会话消息（可选）
        
        Returns:
            审计日志文件路径
        """
        _ensure_audit_dir()
        
        audit_id = _generate_audit_id()
        timestamp = _iso_now()
        
        audit_record = {
            "audit_id": audit_id,
            "timestamp": timestamp,
            "task_id": task_id,
            "check_result": check_result.to_dict(),
            "session_message_count": len(session_messages) if session_messages else 0,
        }
        
        # 原子写入
        audit_file = PROMISE_AUDIT_DIR / f"{audit_id}.json"
        tmp_file = audit_file.with_suffix(".tmp")
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(audit_record, f, indent=2, ensure_ascii=False)
        tmp_file.replace(audit_file)
        
        return audit_file


# 便捷函数

def verify_promise_has_anchor(
    task_context: Dict[str, Any],
    dispatch_registry: Optional[Dict[str, Any]] = None,
    session_registry: Optional[Dict[str, Any]] = None,
) -> PromiseAnchorCheck:
    """
    验证承诺是否有对应锚点
    
    Args:
        task_context: 任务上下文（包含 promise_anchor 字段）
        dispatch_registry: Dispatch 注册表
        session_registry: Session 注册表
    
    Returns:
        PromiseAnchorCheck 检查结果
    """
    hook = PostPromiseVerifyHook()
    return hook.verify_anchor(task_context, dispatch_registry, session_registry)


def validate_promise_anchor(
    anchor_type: str,
    anchor_value: str,
) -> Tuple[bool, str]:
    """
    验证锚点格式
    
    Args:
        anchor_type: 锚点类型
        anchor_value: 锚点值
    
    Returns:
        (是否有效，原因)
    """
    hook = PostPromiseVerifyHook()
    return hook._validate_anchor_format(anchor_type, anchor_value)


def detect_promise_in_session(
    session_messages: List[Dict[str, Any]],
    lookback: int = 5,
) -> Tuple[bool, str]:
    """
    检测会话中是否包含承诺语句
    
    Args:
        session_messages: 会话消息列表
        lookback: 回看消息数量
    
    Returns:
        (是否检测到承诺，承诺文本)
    """
    hook = PostPromiseVerifyHook()
    return hook.detect_promise(session_messages, lookback)


def log_promise_audit(
    task_id: str,
    check_result: PromiseAnchorCheck,
    session_messages: Optional[List[Dict[str, Any]]] = None,
) -> Path:
    """
    记录承诺审计日志
    
    Args:
        task_id: 任务 ID
        check_result: 锚点检查结果
        session_messages: 会话消息
    
    Returns:
        审计日志文件路径
    """
    hook = PostPromiseVerifyHook()
    return hook.audit(task_id, check_result, session_messages)
