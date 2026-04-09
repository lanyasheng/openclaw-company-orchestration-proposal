#!/usr/bin/env python3
"""
subagent_reconciler.py — Reconciliation and listing functions for subagent tasks.

Extracted from subagent_executor.py to reduce module size.
Contains:
- list_subagent_tasks()
- reconcile_dead_processes()
- reconcile_orphan_completions()
- reconcile_queued_tasks()
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from subagent_config import (
    QUEUED_TIMEOUT_SECONDS,
    SUBAGENT_STATE_DIR,
    SubagentResult,
    SubagentStatus,
    TERMINAL_STATES,
    _ensure_state_dir,
    _iso_now,
    _pid_exists,
    _state_file,
)

logger = logging.getLogger(__name__)

__all__ = [
    "list_subagent_tasks",
    "reconcile_dead_processes",
    "reconcile_orphan_completions",
    "reconcile_queued_tasks",
]


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


def _update_task_status_for_reconciliation(task_id: str, status: SubagentStatus, **kwargs):
    """Update task status during reconciliation (file-only, no in-memory cache).

    This is a local helper that writes directly to the state file,
    avoiding circular imports with subagent_executor's _update_task_status
    which manages the in-memory cache.
    """
    import fcntl
    import os

    result = _load_state(task_id)
    if not result:
        return

    result.status = status
    if status in TERMINAL_STATES and not result.completed_at:
        result.completed_at = _iso_now()
    for key, value in kwargs.items():
        if hasattr(result, key):
            if key == "metadata" and isinstance(value, dict):
                result.metadata.update(value)
            else:
                setattr(result, key, value)

    # Persist with flock (same logic as subagent_executor._persist_state)
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
        logger.warning("Failed to acquire state lock for %s: %s", result.task_id, e)
        tmp_path = state_path.with_suffix(".tmp")
        with open(tmp_path, "w") as f:
            json.dump(result.to_dict(), f, indent=2)
        tmp_path.replace(state_path)


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
        except (json.JSONDecodeError, KeyError, OSError) as exc:
            logger.warning(
                "failed to load subagent state from %s: %s", state_file, exc,
            )

    # 按 started_at 排序
    tasks.sort(key=lambda t: t.started_at or "", reverse=True)

    return tasks[:limit]


def reconcile_dead_processes(
    *,
    status_filter: Optional[SubagentStatus] = "running",
    limit: int = 1000,
) -> List[Dict[str, Any]]:
    """
    批量回收已死进程的任务（orphan reconciliation）。

    扫描所有状态为 running 的任务，检查 pid 是否存在。
    如果 pid 不存在，将状态更新为 dead_process_reconciled。

    Args:
        status_filter: 状态过滤（默认只检查 running）
        limit: 最大检查数量

    Returns:
        被回收的任务列表，每个元素包含：
        - task_id: 任务 ID
        - dead_pid: 已死的进程 ID
        - started_at: 任务开始时间
        - reconciled_at: 回收时间

    使用场景：
    - 定期 cron job 清理 orphan tasks
    - roundtable / dashboard 启动时检查
    - 用户报告"假派发卡死"时手动触发
    """
    reconciled = []

    tasks = list_subagent_tasks(status=status_filter, limit=limit)

    for task in tasks:
        # 只处理有 pid 的 running 任务
        if task.status != "running" or not task.pid:
            continue

        # 检查 pid 是否存在
        if not _pid_exists(task.pid):
            # 更新状态为 dead_process_reconciled
            _update_task_status_for_reconciliation(
                task.task_id,
                "dead_process_reconciled",
                error=f"Process {task.pid} no longer exists. Reconciled by batch reconciliation.",
                cleanup_status="session_cleaned",
                cleanup_metadata={
                    "action": "dead_process_reconciled",
                    "dead_pid": task.pid,
                    "reconciled_at": _iso_now(),
                    "reason": "pid_not_found",
                    "reconciliation_batch": True,
                },
            )

            reconciled.append({
                "task_id": task.task_id,
                "dead_pid": task.pid,
                "started_at": task.started_at,
                "reconciled_at": _iso_now(),
                "label": task.config.label,
            })

    return reconciled


def reconcile_queued_tasks(
    *,
    status_filter: Optional[SubagentStatus] = "pending",
    timeout_seconds: Optional[int] = None,
    limit: int = 1000,
) -> List[Dict[str, Any]]:
    """
    批量回收长时间停留在 pending 状态的任务（queued->launch handoff 失败）。

    P0-Hotfix (2026-03-31): 修复并发 leaf tasks 在 queued->launch handoff 阶段丢失的问题。

    扫描所有状态为 pending 的任务，检查是否超过 QUEUED_TIMEOUT_SECONDS。
    如果任务在 pending 状态停留时间超过阈值且没有 pid，
    将状态更新为 queued_launch_missed。

    Args:
        status_filter: 状态过滤（默认只检查 pending）
        timeout_seconds: 超时阈值（秒），默认使用 QUEUED_TIMEOUT_SECONDS（300 秒=5 分钟）
        limit: 最大检查数量

    Returns:
        被回收的任务列表
    """
    timeout_seconds = timeout_seconds or QUEUED_TIMEOUT_SECONDS
    reconciled = []
    now = datetime.now(timezone.utc)

    tasks = list_subagent_tasks(status=status_filter, limit=limit)

    for task in tasks:
        # 只处理 pending 状态且没有 pid 的任务
        if task.status != "pending" or task.pid:
            continue

        # 计算任务在 pending 状态停留的时间
        pending_since_str = (
            task.metadata.get("spawned_at") or
            task.metadata.get("registered_at") or
            (task.to_dict().get("created_at") if hasattr(task, 'to_dict') else None)
        )

        if not pending_since_str:
            continue

        try:
            pending_since_str = str(pending_since_str).replace('Z', '+00:00')
            pending_since = datetime.fromisoformat(pending_since_str)

            if pending_since.tzinfo is None:
                pending_since = pending_since.replace(tzinfo=now.tzinfo)

            age_seconds = (now - pending_since).total_seconds()
        except (ValueError, TypeError):
            continue

        if age_seconds < timeout_seconds:
            continue

        _update_task_status_for_reconciliation(
            task.task_id,
            "queued_launch_missed",
            error=(
                f"Task stuck in pending state for {age_seconds:.0f}s (threshold={timeout_seconds}s). "
                f"Queued->launch handoff failed. No process was started."
            ),
            cleanup_status="session_cleaned",
            cleanup_metadata={
                "action": "queued_launch_missed_reconciled",
                "pending_since": pending_since_str,
                "timeout_seconds": timeout_seconds,
                "age_seconds": round(age_seconds, 2),
                "reconciled_at": _iso_now(),
                "reason": "queued_launch_handoff_failed",
                "reconciliation_batch": True,
                "missing_signals": {
                    "pid": task.pid is None,
                    "status_file": not _state_file(task.task_id).exists() if not task.pid else False,
                },
            },
        )

        reconciled.append({
            "task_id": task.task_id,
            "pending_since": pending_since_str,
            "timeout_seconds": timeout_seconds,
            "age_seconds": round(age_seconds, 2),
            "reconciled_at": _iso_now(),
            "label": task.config.label,
            "reason": "queued_launch_handoff_failed",
        })

    return reconciled


def reconcile_orphan_completions(
    timeout_seconds: int = 600,
    limit: int = 1000,
) -> List[Dict[str, Any]]:
    """Reconcile tasks whose process exited but state still shows 'running'.

    This catches the case where _monitor_process_and_release succeeded in
    detecting process exit but the state file write failed silently (e.g.,
    disk full, race condition). Without this, such tasks remain stuck in
    'running' forever.

    Returns list of reconciled task dicts.
    """
    reconciled: List[Dict[str, Any]] = []
    now = datetime.now(timezone.utc)

    tasks = list_subagent_tasks(status="running", limit=limit)

    for task in tasks:
        if not task.pid:
            continue

        # If process is still alive, skip
        if _pid_exists(task.pid):
            continue

        # Process is dead but state says running — orphan completion
        logger.warning(
            "Orphan completion detected: task %s has dead pid %d but status is 'running'",
            task.task_id,
            task.pid,
        )

        _update_task_status_for_reconciliation(
            task.task_id,
            "failed",
            error=(
                f"Process {task.pid} exited but state was not updated "
                f"(orphan completion). Reconciled by watchdog."
            ),
            cleanup_status="orphan_reconciled",
            cleanup_metadata={
                "action": "orphan_completion_reconciled",
                "dead_pid": task.pid,
                "reconciled_at": _iso_now(),
                "original_status": task.status,
            },
        )

        reconciled.append({
            "task_id": task.task_id,
            "dead_pid": task.pid,
            "reconciled_at": _iso_now(),
            "label": task.config.label if task.config else "",
        })

    if reconciled:
        logger.info("Reconciled %d orphan completions", len(reconciled))

    return reconciled
