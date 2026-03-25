"""State synchronization bridge between WorkflowState and state_machine.

Ensures both DAG workflow and callback-driven paths reflect changes
in a single, consistent view. WorkflowState is the canonical truth;
state_machine per-task files are kept in sync for backward compatibility
with existing callback/continuation kernel infrastructure.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_STATUS_MAP_TO_STATE_MACHINE = {
    "pending": "pending",
    "running": "running",
    "completed": "callback_received",
    "failed": "failed",
}

_STATUS_MAP_FROM_STATE_MACHINE = {
    "pending": "pending",
    "running": "running",
    "callback_received": "completed",
    "next_task_dispatched": "completed",
    "final_closed": "completed",
    "timeout": "failed",
    "failed": "failed",
    "retrying": "running",
}


def sync_task_to_state_machine(
    task_id: str,
    batch_id: str,
    status: str,
    result: Optional[dict] = None,
    timeout_seconds: int = 3600,
) -> None:
    """Sync a WorkflowState task change into state_machine per-task JSON.

    Called by batch_executor when task status changes, so callback-driven
    infrastructure (auto_dispatch, continuation kernel, etc.) can see it.
    """
    try:
        from state_machine import (
            create_task,
            get_state,
            mark_callback_received,
            mark_failed,
            mark_timeout,
        )
    except ImportError:
        logger.debug("state_machine not available, skipping sync")
        return

    existing = get_state(task_id)

    if existing is None and status == "running":
        create_task(task_id, batch_id=batch_id, timeout_seconds=timeout_seconds)
        return

    if existing is None:
        create_task(task_id, batch_id=batch_id, timeout_seconds=timeout_seconds)

    if status == "completed":
        mark_callback_received(task_id, result or {"status": "completed"})
    elif status == "failed":
        mark_failed(task_id, error=str(result) if result else "task failed")
    elif status == "timed_out":
        mark_timeout(task_id)


def sync_callback_to_workflow_state(
    workflow_state_path: str | Path,
    task_id: str,
    status: str,
    result: Optional[dict] = None,
) -> bool:
    """Sync a state_machine callback into WorkflowState.

    Called by orchestrator.process_batch_callback so that DAG workflow
    view stays current. Returns True if the update was applied.
    """
    try:
        from workflow_state import load_workflow_state, save_workflow_state
    except ImportError:
        logger.debug("workflow_state not available, skipping sync")
        return False

    path = Path(workflow_state_path)
    if not path.is_file():
        return False

    try:
        ws = load_workflow_state(path)
    except Exception:
        return False

    mapped_status = _STATUS_MAP_FROM_STATE_MACHINE.get(status, status)

    for batch in ws.batches:
        for task in batch.tasks:
            if task.task_id == task_id:
                task.status = mapped_status
                if mapped_status == "completed" and result:
                    task.result_summary = str(result.get("verdict", result))[:200]
                elif mapped_status == "failed" and result:
                    task.error = str(result.get("error", result))[:200]
                save_workflow_state(ws, path)
                logger.debug(
                    "synced callback %s → workflow_state %s",
                    task_id,
                    mapped_status,
                )
                return True

    return False


def find_active_workflow_state(search_dir: str | Path = ".") -> Optional[Path]:
    """Find the most recently updated active workflow_state file."""
    search = Path(search_dir)
    candidates = sorted(
        search.glob("workflow_state_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for c in candidates:
        try:
            from workflow_state import load_workflow_state
            ws = load_workflow_state(c)
            if ws.status in ("pending", "running", "gate_blocked"):
                return c
        except Exception:
            continue
    return None
