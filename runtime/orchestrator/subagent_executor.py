#!/usr/bin/env python3
"""
subagent_executor.py — Deer-Flow 借鉴线 Batch A

目标：封装 subagent 执行细节，提供统一的 SubagentExecutor 接口。

借鉴 Deer-Flow 的 SubagentExecutor 设计：
- 统一 task_id / timeout / status / result handle
- 工具权限隔离（tool allowlist）
- 状态继承（sandbox_state / thread_data 思路）

适配 OpenClaw 架构：
- 基于现有 sessions_spawn API
- 使用 shared-context 文件系统持久化
- 不引入双线程池（Python GIL 限制）

核心类：
- SubagentConfig: subagent 配置
- SubagentResult: 执行结果
- SubagentExecutor: 执行引擎

使用示例：
```python
executor = SubagentExecutor(
    config=SubagentConfig(
        label="coding-task",
        runtime="subagent",
        timeout_seconds=900,
        allowed_tools=["read", "write", "edit", "exec"],
    ),
    cwd="/Users/study/.openclaw/workspace",
)

task_id = executor.execute_async("实现 XXX 功能")
result = executor.get_result(task_id)
```
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

__all__ = [
    "SubagentStatus",
    "SubagentConfig",
    "SubagentResult",
    "SubagentExecutor",
    "execute_subagent",
    "get_subagent_result",
    "list_subagent_tasks",
    "EXECUTOR_VERSION",
]

EXECUTOR_VERSION = "subagent_executor_v1"

# ============ 全局并发控制（防 fork 炸弹） ============

MAX_CONCURRENT_SUBAGENTS = int(os.environ.get("OPENCLAW_MAX_CONCURRENT_SUBAGENTS", "15"))
MAX_SPAWN_DEPTH = int(os.environ.get("OPENCLAW_MAX_SPAWN_DEPTH", "2"))
SPAWN_DEPTH_ENV_KEY = "OPENCLAW_SPAWN_DEPTH"

_global_semaphore = threading.Semaphore(MAX_CONCURRENT_SUBAGENTS)
_active_subagent_count = 0
_active_subagent_count_lock = threading.Lock()


def _get_current_spawn_depth() -> int:
    """读取当前递归 spawn 深度（从环境变量）"""
    try:
        return int(os.environ.get(SPAWN_DEPTH_ENV_KEY, "0"))
    except (ValueError, TypeError):
        return 0


def _count_system_claude_processes() -> int:
    """统计系统中活跃的 claude 进程数（防止跨 executor 实例的进程累积）"""
    try:
        result = subprocess.run(
            ["pgrep", "-cf", "claude"],
            capture_output=True, text=True, timeout=5,
        )
        return int(result.stdout.strip()) if result.returncode == 0 else 0
    except Exception:
        return 0


# ============ 状态定义 ============

SubagentStatus = Literal["pending", "running", "completed", "failed", "timed_out", "cancelled"]

TERMINAL_STATES = {"completed", "failed", "timed_out", "cancelled"}

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
            metadata=data.get("metadata", {}),
        )


# ============ 全局状态存储 ============

# 内存缓存（热状态，重启会丢）
_background_tasks: Dict[str, SubagentResult] = {}
_background_tasks_lock = threading.Lock()

# 持久化目录
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
    return datetime.now().isoformat()


def _persist_state(result: SubagentResult):
    """持久化状态到文件"""
    _ensure_state_dir()
    state_path = _state_file(result.task_id)
    tmp_path = state_path.with_suffix(".tmp")
    with open(tmp_path, "w") as f:
        json.dump(result.to_dict(), f, indent=2)
    tmp_path.replace(state_path)


def _load_state(task_id: str) -> Optional[SubagentResult]:
    """从文件加载状态"""
    state_path = _state_file(task_id)
    if not state_path.exists():
        return None
    
    try:
        with open(state_path, "r") as f:
            data = json.load(f)
        return SubagentResult.from_dict(data)
    except (json.JSONDecodeError, KeyError):
        return None


def _register_task(result: SubagentResult):
    """注册任务到内存缓存 + 持久化"""
    with _background_tasks_lock:
        _background_tasks[result.task_id] = result
    _persist_state(result)


def _update_task_status(task_id: str, status: SubagentStatus, **kwargs):
    """更新任务状态"""
    with _background_tasks_lock:
        result = _background_tasks.get(task_id)
        if result:
            result.status = status
            if status == "running" and not result.started_at:
                result.started_at = _iso_now()
            elif status in TERMINAL_STATES and not result.completed_at:
                result.completed_at = _iso_now()
            for key, value in kwargs.items():
                if hasattr(result, key):
                    # 特殊处理 metadata：合并而不是覆盖
                    if key == "metadata" and isinstance(value, dict):
                        result.metadata.update(value)
                    else:
                        setattr(result, key, value)
            _persist_state(result)


def _get_task(task_id: str) -> Optional[SubagentResult]:
    """获取任务状态（优先内存，回退文件）"""
    with _background_tasks_lock:
        result = _background_tasks.get(task_id)
        if result:
            return result
    
    # 回退到文件
    return _load_state(task_id)


# ============ 工具过滤 ============


def _filter_tools(
    available_tools: List[str],
    allowed_tools: Optional[List[str]] = None,
    disallowed_tools: Optional[List[str]] = None,
) -> List[str]:
    """
    过滤工具列表。
    
    规则：
    1. 如果 allowed_tools 为空，默认允许所有
    2. disallowed_tools 优先级更高
    """
    tools = set(available_tools)
    
    if allowed_tools:
        tools = tools.intersection(set(allowed_tools))
    
    if disallowed_tools:
        tools = tools - set(disallowed_tools)
    
    return sorted(tools)


# ============ SubagentExecutor ============


class SubagentExecutor:
    """
    Subagent 执行引擎 — 封装 subagent 启动、监控、结果获取。
    
    核心方法：
    - execute_async(task): 异步启动 subagent，返回 task_id
    - get_result(task_id): 获取任务结果
    - cleanup(task_id): 清理已完成任务
    
    设计借鉴 Deer-Flow SubagentExecutor：
    - 统一 task_id / timeout / status / result handle
    - 工具权限隔离
    - 状态继承思路
    
    适配 OpenClaw：
    - 基于 sessions_spawn API
    - shared-context 持久化
    - 不引入双线程池
    """
    
    # 默认可用工具列表
    DEFAULT_AVAILABLE_TOOLS = [
        "read", "write", "edit", "exec",
        "sessions_spawn", "subagents",
        "bash", "python", "node",
    ]
    
    def __init__(
        self,
        config: SubagentConfig,
        cwd: Optional[str] = None,
    ):
        """
        初始化 SubagentExecutor。
        
        Args:
            config: Subagent 配置
            cwd: 工作目录（覆盖 config.cwd）
        """
        self.config = config
        self.cwd = cwd or config.cwd or os.getcwd()
        
        # 工具过滤
        self.allowed_tools = _filter_tools(
            self.DEFAULT_AVAILABLE_TOOLS,
            config.allowed_tools,
            config.disallowed_tools,
        )
    
    def execute_async(self, task: str, task_id: Optional[str] = None) -> str:
        """
        异步启动 subagent。
        
        三层防护:
        1. 递归深度检测 (OPENCLAW_SPAWN_DEPTH > MAX_SPAWN_DEPTH → 拒绝)
        2. 系统级进程数熔断 (pgrep claude > MAX_CONCURRENT_SUBAGENTS → 拒绝)
        3. 进程内信号量 (跨线程并发保护)
        """
        if not task_id:
            task_id = f"task_{uuid.uuid4().hex[:12]}"
        
        depth = _get_current_spawn_depth()
        if depth >= MAX_SPAWN_DEPTH:
            result = SubagentResult(
                task_id=task_id, status="failed", config=self.config, task=task,
                error=(f"Spawn depth {depth} >= MAX_SPAWN_DEPTH {MAX_SPAWN_DEPTH}. "
                       f"Recursive fork bomb prevented."),
                metadata={"executor_version": EXECUTOR_VERSION,
                          "rejected_reason": "spawn_depth_exceeded"},
            )
            _register_task(result)
            return task_id
        
        system_count = _count_system_claude_processes()
        if system_count >= MAX_CONCURRENT_SUBAGENTS:
            result = SubagentResult(
                task_id=task_id, status="failed", config=self.config, task=task,
                error=(f"System claude process count {system_count} >= limit "
                       f"{MAX_CONCURRENT_SUBAGENTS}. Global circuit breaker triggered."),
                metadata={"executor_version": EXECUTOR_VERSION,
                          "rejected_reason": "system_overload"},
            )
            _register_task(result)
            return task_id
        
        acquired = _global_semaphore.acquire(blocking=False)
        if not acquired:
            result = SubagentResult(
                task_id=task_id, status="failed", config=self.config, task=task,
                error=(f"Concurrency limit reached (max={MAX_CONCURRENT_SUBAGENTS}). "
                       f"Try again later."),
                metadata={"executor_version": EXECUTOR_VERSION,
                          "rejected_reason": "concurrency_limit"},
            )
            _register_task(result)
            return task_id
        
        with _active_subagent_count_lock:
            global _active_subagent_count
            _active_subagent_count += 1
        
        result = SubagentResult(
            task_id=task_id, status="pending", config=self.config, task=task,
            metadata={
                "executor_version": EXECUTOR_VERSION,
                "allowed_tools": self.allowed_tools,
                "spawn_depth": depth,
            },
        )
        _register_task(result)
        self._start_subagent_process(task_id, task)
        
        return task_id
    
    def _start_subagent_process(self, task_id: str, task: str):
        """
        启动 subagent 进程，注入 OPENCLAW_SPAWN_DEPTH 环境变量。
        失败时释放全局信号量。
        """
        runner_script = Path(self.cwd) / "scripts" / "run_subagent_claude_v1.sh"
        
        if not runner_script.exists():
            cmd = [
                sys.executable, "-c",
                f"print('Simulated subagent execution for task: {task}')"
            ]
        else:
            cmd = [
                "bash", str(runner_script),
                task,
                self.config.label,
            ]
        
        child_env = os.environ.copy()
        current_depth = _get_current_spawn_depth()
        child_env[SPAWN_DEPTH_ENV_KEY] = str(current_depth + 1)
        
        try:
            process = subprocess.Popen(
                cmd,
                cwd=self.cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
                env=child_env,
            )
            
            _update_task_status(
                task_id, "running", pid=process.pid,
                metadata={"process_started": True, "spawn_depth": current_depth + 1},
            )
            
        except Exception as e:
            _global_semaphore.release()
            with _active_subagent_count_lock:
                global _active_subagent_count
                _active_subagent_count -= 1
            _update_task_status(
                task_id, "failed",
                error=f"Failed to start subagent process: {str(e)}",
            )
    
    def get_result(self, task_id: str) -> Optional[SubagentResult]:
        """
        获取任务结果（带超时自动检查）。
        
        Args:
            task_id: 任务 ID
        
        Returns:
            SubagentResult，如果任务不存在则返回 None
        """
        result = _get_task(task_id)
        if not result:
            return None
        
        # 超时自动检查（Batch F 增强）
        if result.status == "running" and result.started_at:
            if self._is_timed_out(result):
                _update_task_status(
                    task_id,
                    "timed_out",
                    error=f"Task timed out after {self.config.timeout_seconds} seconds",
                )
                result = _get_task(task_id)
        
        return result
    
    def _is_timed_out(self, result: SubagentResult) -> bool:
        """
        检查任务是否超时。
        
        Args:
            result: 任务结果
        
        Returns:
            True 如果任务已超时
        """
        if not result.started_at:
            return False
        
        try:
            started = datetime.fromisoformat(result.started_at)
            elapsed = (datetime.now() - started).total_seconds()
            return elapsed > self.config.timeout_seconds
        except (ValueError, TypeError):
            return False
    
    def is_completed(self, task_id: str) -> bool:
        """
        检查任务是否完成。
        
        Args:
            task_id: 任务 ID
        
        Returns:
            True 如果任务已完成（终端状态）
        """
        result = _get_task(task_id)
        return result is not None and result.status in TERMINAL_STATES
    
    def cleanup(self, task_id: str) -> bool:
        """
        清理已完成任务（从内存缓存移除，保留文件）。
        
        Args:
            task_id: 任务 ID
        
        Returns:
            True 如果清理成功
        """
        result = _get_task(task_id)
        if not result or result.status not in TERMINAL_STATES:
            return False
        
        with _background_tasks_lock:
            if task_id in _background_tasks:
                del _background_tasks[task_id]
        
        return True


# ============ 便捷函数 ============


def execute_subagent(
    task: str,
    label: str = "default",
    runtime: Literal["subagent", "acp"] = "subagent",
    timeout_seconds: int = 900,
    allowed_tools: Optional[List[str]] = None,
    cwd: Optional[str] = None,
) -> str:
    """
    便捷函数：执行 subagent。
    
    Args:
        task: 任务描述
        label: 任务标签
        runtime: 运行时类型
        timeout_seconds: 超时时间
        allowed_tools: 允许的工具列表
        cwd: 工作目录
    
    Returns:
        task_id: 任务 ID
    """
    config = SubagentConfig(
        label=label,
        runtime=runtime,
        timeout_seconds=timeout_seconds,
        allowed_tools=allowed_tools,
        cwd=cwd or "",
    )
    
    executor = SubagentExecutor(config, cwd=cwd)
    return executor.execute_async(task)


def get_subagent_result(task_id: str) -> Optional[SubagentResult]:
    """
    便捷函数：获取 subagent 结果。
    
    Args:
        task_id: 任务 ID
    
    Returns:
        SubagentResult
    """
    return _get_task(task_id)


def list_subagent_tasks(
    status: Optional[SubagentStatus] = None,
    limit: int = 100,
) -> List[SubagentResult]:
    """
    列出 subagent 任务。
    
    Args:
        status: 按状态过滤
        limit: 最大返回数量
    
    Returns:
        SubagentResult 列表
    """
    _ensure_state_dir()
    
    tasks = []
    for state_file in SUBAGENT_STATE_DIR.glob("*.json"):
        try:
            result = _load_state(state_file.stem)
            if result:
                if status is None or result.status == status:
                    tasks.append(result)
        except Exception:
            pass
    
    # 按 started_at 排序
    tasks.sort(key=lambda t: t.started_at or "", reverse=True)
    
    return tasks[:limit]


# ============ CLI 入口 ============

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python subagent_executor.py execute <task> [label]")
        print("  python subagent_executor.py get <task_id>")
        print("  python subagent_executor.py list [--status <status>]")
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == "execute":
        if len(sys.argv) < 3:
            print("Error: missing task")
            sys.exit(1)
        
        task = sys.argv[2]
        label = sys.argv[3] if len(sys.argv) > 3 else "default"
        
        task_id = execute_subagent(task, label=label)
        print(f"Task started: {task_id}")
        print(f"Label: {label}")
        print(f"Check status with: python subagent_executor.py get {task_id}")
    
    elif cmd == "get":
        if len(sys.argv) < 3:
            print("Error: missing task_id")
            sys.exit(1)
        
        task_id = sys.argv[2]
        result = get_subagent_result(task_id)
        
        if result:
            print(json.dumps(result.to_dict(), indent=2))
        else:
            print(f"Task not found: {task_id}")
            sys.exit(1)
    
    elif cmd == "list":
        status = None
        if "--status" in sys.argv:
            idx = sys.argv.index("--status")
            if idx + 1 < len(sys.argv):
                status = sys.argv[idx + 1]
        
        tasks = list_subagent_tasks(status=status)
        print(json.dumps([t.to_dict() for t in tasks], indent=2))
    
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
