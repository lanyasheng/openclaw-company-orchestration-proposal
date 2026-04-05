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
    cwd="<REPO_ROOT>/../../..",  # Or use Path.home() / ".openclaw/workspace"
)

task_id = executor.execute_async("实现 XXX 功能")
result = executor.get_result(task_id)
```
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import threading
import uuid

logger = logging.getLogger(__name__)
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

# ============ Re-exports from subagent_config ============
from subagent_config import (
    BYPASS_FORK_GUARD,
    CLEANUP_COMPLETE_STATES,
    CleanupStatus,
    EXECUTOR_VERSION,
    MAX_CONCURRENT_SUBAGENTS,
    MAX_SPAWN_DEPTH,
    QUEUED_TIMEOUT_SECONDS,
    RUNNER_SCRIPT_ENV_KEYS,
    RUNNER_SCRIPT_NAME,
    SPAWN_DEPTH_ENV_KEY,
    SUBAGENT_STATE_DIR,
    SubagentConfig,
    SubagentResult,
    SubagentStatus,
    TERMINAL_STATES,
    WORKSPACE_ROOT_ENV_KEYS,
    _count_system_claude_processes,
    _ensure_state_dir,
    _get_current_spawn_depth,
    _iso_now,
    _pid_exists,
    _state_file,
)

# ============ Re-exports from subagent_reconciler ============
from subagent_reconciler import (
    list_subagent_tasks,
    reconcile_dead_processes,
    reconcile_orphan_completions,
    reconcile_queued_tasks,
)

__all__ = [
    "SubagentStatus",
    "SubagentConfig",
    "SubagentResult",
    "SubagentExecutor",
    "CleanupStatus",
    "CLEANUP_COMPLETE_STATES",
    "TERMINAL_STATES",
    "QUEUED_TIMEOUT_SECONDS",
    "execute_subagent",
    "get_subagent_result",
    "list_subagent_tasks",
    "reconcile_dead_processes",
    "reconcile_queued_tasks",
    "reconcile_orphan_completions",
    "EXECUTOR_VERSION",
    # Re-exported from subagent_config for backward compatibility
    "MAX_CONCURRENT_SUBAGENTS",
    "MAX_SPAWN_DEPTH",
    "SPAWN_DEPTH_ENV_KEY",
    "BYPASS_FORK_GUARD",
    "SUBAGENT_STATE_DIR",
    "RUNNER_SCRIPT_NAME",
    "RUNNER_SCRIPT_ENV_KEYS",
    "WORKSPACE_ROOT_ENV_KEYS",
    "_iso_now",
    "_ensure_state_dir",
    "_state_file",
    "_pid_exists",
    "_get_current_spawn_depth",
    "_count_system_claude_processes",
    # Internal state management (used by tests)
    "_persist_state",
    "_load_state",
    "_register_task",
    "_update_task_status",
    "_get_task",
    "_background_tasks",
    "_background_tasks_lock",
]


# ============ 全局并发控制 ============

_global_semaphore = threading.Semaphore(MAX_CONCURRENT_SUBAGENTS)
_active_subagent_count = 0
_active_subagent_count_lock = threading.Lock()
# 跟踪已获取信号量的任务，用于进程结束时释放
_semaphore_holders: Dict[str, bool] = {}
_semaphore_holders_lock = threading.Lock()


# ============ 全局状态存储 ============

# 内存缓存（热状态，重启会丢）
_background_tasks: Dict[str, SubagentResult] = {}
_background_tasks_lock = threading.Lock()


def _persist_state(result: SubagentResult):
    """持久化状态到文件（文件级锁防并发写入冲突）"""
    import fcntl
    _ensure_state_dir()
    state_path = _state_file(result.task_id)
    lock_path = state_path.with_suffix(".lock")
    try:
        lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            tmp_path = state_path.with_suffix(".tmp")
            with open(tmp_path, "w") as f:
                json.dump(result.to_dict(), f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            tmp_path.replace(state_path)
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
    except OSError as e:
        # Fallback: write without lock if locking fails (e.g., NFS)
        logger.warning("Failed to acquire state lock for %s: %s", result.task_id, e)
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
    """更新任务状态（内存缓存 + 文件持久化）"""
    with _background_tasks_lock:
        result = _background_tasks.get(task_id)

        # 如果不在内存缓存中，尝试从文件加载
        if not result:
            result = _load_state(task_id)
            if result:
                _background_tasks[task_id] = result

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


def _resolve_runner_script(cwd: str) -> tuple[Optional[Path], List[str]]:
    """解析 subagent runner 脚本路径。

    历史实现默认假设 runner 总在 ``<workdir>/scripts``，
    但 trading lane 的 workdir 可能是业务 repo（例如 workspace-trading），
    真正的 canonical runner 实际位于全局 workspace/scripts 下。

    解析顺序：
    1. 显式环境变量（OPENCLAW_SUBAGENT_RUNNER / OPENCLAW_RUNNER_SCRIPT）
    2. 显式 workspace root 环境变量（OPENCLAW_WORKSPACE_ROOT）
    3. 任务 workdir 及其祖先目录
    4. 当前模块所在 repo 的祖先目录（可覆盖 monorepo -> workspace 场景）
    5. 默认全局 workspace: ~/.openclaw/workspace
    """
    searched: List[str] = []
    seen: set[str] = set()

    def _normalize(path: Path) -> Path:
        try:
            return path.expanduser().resolve()
        except FileNotFoundError:
            return path.expanduser()

    def _record(path: Path) -> Optional[Path]:
        normalized = _normalize(path)
        text = str(normalized)
        if text in seen:
            return None
        seen.add(text)
        searched.append(text)
        if normalized.exists():
            return normalized
        return None

    for env_key in RUNNER_SCRIPT_ENV_KEYS:
        raw = os.environ.get(env_key)
        if not raw:
            continue
        resolved = _record(Path(raw))
        if resolved is not None:
            return resolved, searched

    candidate_roots: List[Path] = []
    for env_key in WORKSPACE_ROOT_ENV_KEYS:
        raw = os.environ.get(env_key)
        if raw:
            candidate_roots.append(Path(raw))

    cwd_path = Path(cwd).expanduser()
    candidate_roots.append(cwd_path)
    candidate_roots.extend(cwd_path.parents)

    module_path = Path(__file__).resolve()
    candidate_roots.extend(module_path.parents)
    candidate_roots.append(Path.home() / ".openclaw" / "workspace")

    for root in candidate_roots:
        resolved = _record(_normalize(root) / "scripts" / RUNNER_SCRIPT_NAME)
        if resolved is not None:
            return resolved, searched

    return None, searched


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
        1. 递归深度检测 (OPENCLAW_SPAWN_DEPTH > MAX_SPAWN_DEPTH -> 拒绝)
        2. 系统级进程数熔断 (pgrep claude > MAX_CONCURRENT_SUBAGENTS -> 拒绝)
        3. 进程内信号量 (跨线程并发保护)

        测试模式 (OPENCLAW_BYPASS_FORK_GUARD=1): 跳过所有 guard 检查
        """
        if not task_id:
            task_id = f"task_{uuid.uuid4().hex[:12]}"

        # 测试模式：bypass 所有 fork guard
        if not BYPASS_FORK_GUARD:
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

            # 记录信号量持有者，用于后续释放
            with _semaphore_holders_lock:
                _semaphore_holders[task_id] = True

        with _active_subagent_count_lock:
            global _active_subagent_count
            _active_subagent_count += 1

        # P0-Hotfix (2026-03-31): Record registration timestamp for queued timeout reconciliation
        registered_at = _iso_now()

        result = SubagentResult(
            task_id=task_id, status="pending", config=self.config, task=task,
            metadata={
                "executor_version": EXECUTOR_VERSION,
                "allowed_tools": self.allowed_tools,
                "spawn_depth": _get_current_spawn_depth() if not BYPASS_FORK_GUARD else 0,
                "registered_at": registered_at,
                "spawned_at": registered_at,  # Alias for compatibility with orchestration_runtime
            },
        )
        _register_task(result)

        # P0-Hotfix (2026-03-31): Launch confirmation
        self._start_subagent_process(task_id, task)

        return task_id

    def _start_subagent_process(self, task_id: str, task: str):
        """
        启动 subagent 进程，注入 OPENCLAW_SPAWN_DEPTH 环境变量。
        失败时释放全局信号量。

        使用 start_new_session=True 创建新会话，进程组 ID = pid。
        """
        global _active_subagent_count

        runner_script, searched_runner_paths = _resolve_runner_script(self.cwd)

        test_mode = os.environ.get("OPENCLAW_TEST_MODE", "0") == "1" or BYPASS_FORK_GUARD

        if runner_script is None:
            if test_mode:
                state_dir = str(SUBAGENT_STATE_DIR)
                cmd = [
                    sys.executable, "-c",
                    (
                        "import json,os,pathlib,sys;"
                        f"d=pathlib.Path({state_dir!r});"
                        "d.mkdir(parents=True,exist_ok=True);"
                        f"f=d/'{task_id}.json';"
                        "f.write_text(json.dumps("
                        "{'status':'completed','result':'test_ok',"
                        f"'task_id':'{task_id}','task':'',"
                        "'config':{'label':'test','runtime':'subagent',"
                        "'timeout_seconds':900}}))"
                    ),
                ]
            else:
                _update_task_status(
                    task_id, "failed",
                    error=(
                        f"Runner script not found. searched={searched_runner_paths}. "
                        f"Set OPENCLAW_TEST_MODE=1 for test simulation."
                    ),
                    metadata={
                        "runner_script": None,
                        "runner_search_paths": searched_runner_paths,
                    },
                )
                with _active_subagent_count_lock:
                    _active_subagent_count -= 1
                if not BYPASS_FORK_GUARD:
                    _global_semaphore.release()
                    with _semaphore_holders_lock:
                        _semaphore_holders.pop(task_id, None)
                return
        else:
            cmd = [
                "bash", str(runner_script),
                task,
                self.config.label,
            ]

        child_env = os.environ.copy()
        current_depth = _get_current_spawn_depth()
        child_env[SPAWN_DEPTH_ENV_KEY] = str(current_depth + 1)
        child_env["OPENCLAW_SUBAGENT_STATE_DIR"] = str(SUBAGENT_STATE_DIR)
        child_env["OPENCLAW_TASK_ID"] = task_id

        try:
            process = subprocess.Popen(
                cmd,
                cwd=self.cwd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                env=child_env,
            )

            pgid = process.pid

            _update_task_status(
                task_id, "running", pid=process.pid, pgid=pgid,
                metadata={
                    "process_started": True,
                    "spawn_depth": current_depth + 1,
                    "process_group_id": pgid,
                    "runner_script": str(runner_script) if runner_script is not None else None,
                    "runner_search_paths": searched_runner_paths,
                },
            )

            if not BYPASS_FORK_GUARD:
                threading.Thread(
                    target=self._monitor_process_and_release,
                    args=(task_id, process),
                    daemon=True,
                ).start()

        except (OSError, ValueError) as e:
            if not BYPASS_FORK_GUARD:
                _global_semaphore.release()
                with _semaphore_holders_lock:
                    _semaphore_holders.pop(task_id, None)
            with _active_subagent_count_lock:
                _active_subagent_count -= 1
            _update_task_status(
                task_id, "failed",
                error=f"Failed to start subagent process: {str(e)}",
            )

    def _monitor_process_and_release(self, task_id: str, process):
        """
        监控子进程结束，释放信号量。
        在进程结束时根据退出码和状态文件推断终端态。

        终端态判定优先级：
        1. 子进程写入的状态文件（runner 或 test-mode 脚本负责写）
        2. 退出码 0 -> completed, 非 0 -> failed
        """
        try:
            exit_code = process.wait()

            result = _get_task(task_id)
            if result is None:
                return

            persisted = _load_state(task_id)
            if persisted and persisted.status in TERMINAL_STATES:
                if result.status not in TERMINAL_STATES:
                    _update_task_status(
                        task_id,
                        persisted.status,
                        result=persisted.result,
                        error=persisted.error,
                        cleanup_status="session_cleaned",
                        cleanup_metadata={
                            "action": "process_exited_state_file",
                            "exit_code": exit_code,
                            "timestamp": _iso_now(),
                        },
                    )
                return

            if result.status not in TERMINAL_STATES:
                if exit_code == 0:
                    _update_task_status(
                        task_id, "completed",
                        result="process exited successfully",
                        cleanup_status="session_cleaned",
                        cleanup_metadata={
                            "action": "process_exited_zero",
                            "exit_code": 0,
                            "timestamp": _iso_now(),
                        },
                    )
                else:
                    _update_task_status(
                        task_id, "failed",
                        error=f"process exited with code {exit_code}",
                        cleanup_status="session_cleaned",
                        cleanup_metadata={
                            "action": "process_exited_nonzero",
                            "exit_code": exit_code,
                            "timestamp": _iso_now(),
                        },
                    )
            elif result.cleanup_status is None:
                _update_task_status(
                    task_id,
                    result.status,
                    cleanup_status="session_cleaned",
                    cleanup_metadata={
                        "action": "process_exited_naturally",
                        "exit_code": exit_code,
                        "timestamp": _iso_now(),
                    },
                )
        except Exception:
            import logging as _logging
            _logging.getLogger(__name__).exception(
                "unexpected error monitoring subagent process for task %s", task_id,
            )
        finally:
            _global_semaphore.release()
            with _semaphore_holders_lock:
                _semaphore_holders.pop(task_id, None)
            with _active_subagent_count_lock:
                global _active_subagent_count
                _active_subagent_count -= 1

    def get_result(self, task_id: str) -> Optional[SubagentResult]:
        """
        获取任务结果（带超时自动检查 + dead process reconciliation）。

        检测逻辑：
        1. 超时检查：如果 started_at 存在且超过 timeout_seconds，标记为 timed_out
        2. Dead process 检查：如果状态是 running 但 pid 不存在，标记为 dead_process_reconciled

        Args:
            task_id: 任务 ID

        Returns:
            SubagentResult，如果任务不存在则返回 None
        """
        result = _get_task(task_id)
        if not result:
            return None

        # 只对非终端状态进行检测
        if result.status in TERMINAL_STATES:
            return result

        # 1. 超时自动检查（Batch F 增强）
        if result.status == "running" and result.started_at:
            if self._is_timed_out(result):
                _update_task_status(
                    task_id,
                    "timed_out",
                    error=f"Task timed out after {self.config.timeout_seconds} seconds",
                )
                # 超时自动 cleanup（杀死进程组）
                if result.pid:
                    self._kill_process_group(result)
                result = _get_task(task_id)
                return result

        # 2. Dead process reconciliation
        if result.status == "running" and result.pid:
            if not _pid_exists(result.pid):
                _update_task_status(
                    task_id,
                    "dead_process_reconciled",
                    error=f"Process {result.pid} no longer exists, but state was still 'running'. Reconciled to terminal state.",
                    cleanup_status="session_cleaned",
                    cleanup_metadata={
                        "action": "dead_process_reconciled",
                        "dead_pid": result.pid,
                        "reconciled_at": _iso_now(),
                        "reason": "pid_not_found",
                    },
                )
                result = _get_task(task_id)

        return result

    def _is_timed_out(self, result: SubagentResult) -> bool:
        """
        检查任务是否超时。
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
        """
        result = _get_task(task_id)
        return result is not None and result.status in TERMINAL_STATES

    def cleanup(self, task_id: str, kill_process: bool = True) -> bool:
        """
        清理已完成任务（从内存缓存移除，保留文件）。
        """
        result = _get_task(task_id)
        if not result or result.status not in TERMINAL_STATES:
            return False

        # Session/process cleanup
        if kill_process and result.pid:
            self._kill_process_group(result)

        # 从内存缓存移除（保留文件持久化）
        with _background_tasks_lock:
            if task_id in _background_tasks:
                del _background_tasks[task_id]

        return True

    def _kill_process_group(self, result: SubagentResult) -> None:
        """
        杀死进程组（timeout / cancel / terminal 时调用）。
        """
        if not result.pid:
            return

        pgid = result.pgid or result.pid

        try:
            os.killpg(pgid, signal.SIGTERM)
            _update_task_status(
                result.task_id,
                result.status,
                cleanup_status="process_killed",
                cleanup_metadata={
                    "action": "kill_process_group",
                    "pgid": pgid,
                    "signal": "SIGTERM",
                    "timestamp": _iso_now(),
                    "ui_cleanup": "unknown",
                },
            )
        except ProcessLookupError:
            _update_task_status(
                result.task_id,
                result.status,
                cleanup_status="session_cleaned",
                cleanup_metadata={
                    "action": "process_already_exited",
                    "pgid": pgid,
                    "timestamp": _iso_now(),
                },
            )
        except OSError as e:
            _update_task_status(
                result.task_id,
                result.status,
                cleanup_status="cleanup_failed",
                cleanup_metadata={
                    "action": "kill_process_group_failed",
                    "pgid": pgid,
                    "error": str(e),
                    "timestamp": _iso_now(),
                },
            )

    def cancel(self, task_id: str) -> bool:
        """
        取消运行中的任务（杀死进程组 + 标记为 cancelled）。
        """
        result = _get_task(task_id)
        if not result or result.status not in ("pending", "running"):
            return False

        _update_task_status(task_id, "cancelled")

        if result.pid:
            self._kill_process_group(result)

        return True

    def force_cleanup(self, task_id: str) -> Dict[str, Any]:
        """
        强制清理任务（无论状态如何）。
        """
        result = _get_task(task_id)

        if not result:
            return {
                "success": False,
                "reason": "task_not_found",
                "task_id": task_id,
            }

        if result.status == "running":
            self.cancel(task_id)
            result = _get_task(task_id)

        if result.status not in TERMINAL_STATES:
            _update_task_status(
                task_id, "failed",
                error="Force cleaned: task was not in terminal state",
            )
            result = _get_task(task_id)

        self.cleanup(task_id, kill_process=True)

        return {
            "success": True,
            "task_id": task_id,
            "final_status": result.status,
            "cleanup_status": result.cleanup_status,
            "cleanup_metadata": result.cleanup_metadata,
        }


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
    """
    return _get_task(task_id)


# ============ CLI 入口 ============

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python subagent_executor.py execute <task> [label]")
        print("  python subagent_executor.py get <task_id>")
        print("  python subagent_executor.py list [--status <status>]")
        print("  python subagent_executor.py reconcile [--limit 1000]")
        print("  python subagent_executor.py reconcile-queued [--timeout 300] [--limit 1000]")
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

    elif cmd == "reconcile":
        limit = 1000
        if "--limit" in sys.argv:
            idx = sys.argv.index("--limit")
            if idx + 1 < len(sys.argv):
                limit = int(sys.argv[idx + 1])

        reconciled = reconcile_dead_processes(limit=limit)
        print(json.dumps({
            "reconciled_count": len(reconciled),
            "reconciled_tasks": reconciled,
        }, indent=2))

    elif cmd == "reconcile-queued":
        timeout = QUEUED_TIMEOUT_SECONDS
        limit = 1000
        if "--timeout" in sys.argv:
            idx = sys.argv.index("--timeout")
            if idx + 1 < len(sys.argv):
                timeout = int(sys.argv[idx + 1])
        if "--limit" in sys.argv:
            idx = sys.argv.index("--limit")
            if idx + 1 < len(sys.argv):
                limit = int(sys.argv[idx + 1])

        reconciled = reconcile_queued_tasks(timeout_seconds=timeout, limit=limit)
        print(json.dumps({
            "reconciled_count": len(reconciled),
            "timeout_seconds": timeout,
            "reconciled_tasks": reconciled,
        }, indent=2))

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
