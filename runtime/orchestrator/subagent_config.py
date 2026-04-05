#!/usr/bin/env python3
"""
subagent_config.py — Subagent configuration, result types, and shared helpers.

Extracted from subagent_executor.py to reduce module size.
All constants, dataclasses (SubagentConfig, SubagentResult), type aliases,
and low-level helper functions live here.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "EXECUTOR_VERSION",
    "MAX_CONCURRENT_SUBAGENTS",
    "MAX_SPAWN_DEPTH",
    "SPAWN_DEPTH_ENV_KEY",
    "BYPASS_FORK_GUARD",
    "SubagentStatus",
    "TERMINAL_STATES",
    "QUEUED_TIMEOUT_SECONDS",
    "CleanupStatus",
    "CLEANUP_COMPLETE_STATES",
    "SubagentConfig",
    "SubagentResult",
    "SUBAGENT_STATE_DIR",
    "RUNNER_SCRIPT_NAME",
    "RUNNER_SCRIPT_ENV_KEYS",
    "WORKSPACE_ROOT_ENV_KEYS",
    # Helper functions
    "_iso_now",
    "_ensure_state_dir",
    "_state_file",
    "_pid_exists",
    "_get_current_spawn_depth",
    "_count_system_claude_processes",
]

EXECUTOR_VERSION = "subagent_executor_v1"

# ============ 全局并发控制（防 fork 炸弹） ============

MAX_CONCURRENT_SUBAGENTS = int(os.environ.get("OPENCLAW_MAX_CONCURRENT_SUBAGENTS", "15"))
MAX_SPAWN_DEPTH = int(os.environ.get("OPENCLAW_MAX_SPAWN_DEPTH", "2"))
SPAWN_DEPTH_ENV_KEY = "OPENCLAW_SPAWN_DEPTH"
# 测试模式：bypass fork guard（仅在受控测试环境使用）
BYPASS_FORK_GUARD = os.environ.get("OPENCLAW_BYPASS_FORK_GUARD", "0") == "1"


def _get_current_spawn_depth() -> int:
    """读取当前递归 spawn 深度（从环境变量）"""
    try:
        return int(os.environ.get(SPAWN_DEPTH_ENV_KEY, "0"))
    except (ValueError, TypeError):
        return 0


def _count_system_claude_processes() -> int:
    """统计系统中活跃的 claude 进程数（防止跨 executor 实例的进程累积）"""
    import subprocess
    try:
        result = subprocess.run(
            ["pgrep", "-cf", "claude"],
            capture_output=True, text=True, timeout=5,
        )
        return int(result.stdout.strip()) if result.returncode == 0 else 0
    except (subprocess.SubprocessError, OSError, ValueError):
        return 0


# ============ 状态定义 ============

SubagentStatus = Literal[
    "pending", "running", "completed", "failed", "timed_out", "cancelled",
    "dead_process_reconciled", "queued_launch_missed"
]

TERMINAL_STATES = {
    "completed", "failed", "timed_out", "cancelled",
    "dead_process_reconciled", "queued_launch_missed"
}

# P0-Hotfix (2026-03-31): Queued launch timeout threshold
# Tasks stuck in pending state for longer than this will be reconciled to queued_launch_missed
QUEUED_TIMEOUT_SECONDS = int(os.environ.get("OPENCLAW_QUEUED_TIMEOUT_SECONDS", "300"))  # Default: 5 minutes

# ============ Cleanup 状态定义 ============

CleanupStatus = Literal["pending", "process_killed", "session_cleaned", "ui_cleanup_unknown", "cleanup_failed"]

CLEANUP_COMPLETE_STATES = {"process_killed", "session_cleaned", "ui_cleanup_unknown"}

# ============ 配置定义 ============


@dataclass
class SubagentConfig:
    """
    Subagent 配置 — 定义 subagent 的执行参数。

    核心字段：
    - label: 任务标签（用于 session 命名和日志）
    - runtime: 运行时类型（subagent | acp）
    - timeout_seconds: 超时时间（秒）
    - allowed_tools: 允许使用的工具列表
    - disallowed_tools: 禁止使用的工具列表
    - cwd: 工作目录
    - metadata: 额外元数据
    """
    label: str
    runtime: Literal["subagent", "acp"] = "subagent"
    timeout_seconds: int = 900
    allowed_tools: Optional[List[str]] = None
    disallowed_tools: Optional[List[str]] = None
    cwd: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "runtime": self.runtime,
            "timeout_seconds": self.timeout_seconds,
            "allowed_tools": self.allowed_tools,
            "disallowed_tools": self.disallowed_tools,
            "cwd": self.cwd,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SubagentConfig":
        return cls(
            label=data.get("label", ""),
            runtime=data.get("runtime", "subagent"),
            timeout_seconds=data.get("timeout_seconds", 900),
            allowed_tools=data.get("allowed_tools"),
            disallowed_tools=data.get("disallowed_tools"),
            cwd=data.get("cwd", ""),
            metadata=data.get("metadata", {}),
        )


# ============ 结果定义 ============


@dataclass
class SubagentResult:
    """
    Subagent 执行结果 — 记录任务状态和输出。

    核心字段：
    - task_id: 任务 ID
    - status: 执行状态
    - config: 执行配置
    - task: 任务描述
    - result: 执行结果（完成后填充）
    - error: 错误信息（失败时填充）
    - started_at: 开始时间
    - completed_at: 完成时间
    - pid: 进程 ID（如果已启动）
    - pgid: 进程组 ID（如果已启动 session）
    - cleanup_status: 清理状态（pending | process_killed | session_cleaned | ui_cleanup_unknown | cleanup_failed）
    - cleanup_metadata: 清理元数据（记录清理动作和结果）
    - metadata: 额外元数据
    """
    task_id: str
    status: SubagentStatus
    config: SubagentConfig
    task: str
    result: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    pid: Optional[int] = None
    pgid: Optional[int] = None
    cleanup_status: Optional[CleanupStatus] = None
    cleanup_metadata: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "executor_version": EXECUTOR_VERSION,
            "task_id": self.task_id,
            "status": self.status,
            "config": self.config.to_dict(),
            "task": self.task,
            "result": self.result,
            "error": self.error,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "pid": self.pid,
            "pgid": self.pgid,
            "cleanup_status": self.cleanup_status,
            "cleanup_metadata": self.cleanup_metadata,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SubagentResult":
        config_data = data.get("config", {})
        return cls(
            task_id=data.get("task_id", ""),
            status=data.get("status", "pending"),
            config=SubagentConfig.from_dict(config_data),
            task=data.get("task", ""),
            result=data.get("result"),
            error=data.get("error"),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            pid=data.get("pid"),
            pgid=data.get("pgid"),
            cleanup_status=data.get("cleanup_status"),
            cleanup_metadata=data.get("cleanup_metadata", {}),
            metadata=data.get("metadata", {}),
        )


# ============ 持久化目录 ============

SUBAGENT_STATE_DIR = Path(
    os.environ.get(
        "OPENCLAW_SUBAGENT_STATE_DIR",
        Path.home() / ".openclaw" / "shared-context" / "subagent_states",
    )
)


def _ensure_state_dir():
    """确保状态目录存在"""
    SUBAGENT_STATE_DIR.mkdir(parents=True, exist_ok=True)


def _state_file(task_id: str) -> Path:
    """返回状态文件路径"""
    return SUBAGENT_STATE_DIR / f"{task_id}.json"


def _iso_now() -> str:
    """返回 ISO-8601 时间戳"""
    return datetime.now(timezone.utc).isoformat()


def _pid_exists(pid: int) -> bool:
    """
    检查进程是否存在。

    Args:
        pid: 进程 ID

    Returns:
        True 如果进程存在
    """
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


# ============ Runner script 常量 ============

RUNNER_SCRIPT_NAME = "run_subagent_claude_v1.sh"
RUNNER_SCRIPT_ENV_KEYS = ("OPENCLAW_SUBAGENT_RUNNER", "OPENCLAW_RUNNER_SCRIPT")
WORKSPACE_ROOT_ENV_KEYS = ("OPENCLAW_WORKSPACE_ROOT",)
