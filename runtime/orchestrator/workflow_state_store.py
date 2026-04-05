"""Singleton store for the active WorkflowState file.

All modules that need to read/write workflow state should go through this
store instead of maintaining their own scattered files. The store provides
a thread-safe interface to update task and batch state in the single
workflow_state JSON file.

Usage:
    from workflow_state_store import get_store

    store = get_store()
    store.set_active(path="/path/to/workflow_state_wf_xxx.json")
    store.update_task("t1", status="completed", result={"verdict": "PASS"})
    task = store.get_task("t1")
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


_MAX_STALE_RETRIES = 3


class WorkflowStateStore:
    """Thread-safe singleton for active workflow state access.

    Includes stale-write detection: before saving, the store checks whether
    the file's mtime has changed since it was loaded. If another process
    modified the file in the meantime, the store reloads, re-applies the
    mutation, and retries (up to ``_MAX_STALE_RETRIES`` times).
    """

    _instance: Optional[WorkflowStateStore] = None
    _lock = threading.Lock()

    def __new__(cls) -> WorkflowStateStore:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._active_path: Optional[Path] = None
                cls._instance._rw_lock = threading.RLock()
                cls._instance._cached_mtime: Optional[float] = None
            return cls._instance

    def set_active(self, path: str | Path) -> None:
        with self._rw_lock:
            self._active_path = Path(path)
            self._cached_mtime = None

    @property
    def active_path(self) -> Optional[Path]:
        if self._active_path and self._active_path.is_file():
            return self._active_path
        env_path = os.environ.get("OPENCLAW_WORKFLOW_STATE_PATH")
        if env_path:
            p = Path(env_path)
            if p.is_file():
                return p
        return None

    @property
    def is_active(self) -> bool:
        return self.active_path is not None

    def _load_with_mtime(self, path: Path):
        """Load workflow state and cache the file's mtime for staleness detection."""
        from workflow_state import load_workflow_state
        mtime = path.stat().st_mtime
        ws = load_workflow_state(path)
        self._cached_mtime = mtime
        return ws

    def _save_with_mtime_check(self, ws, path: Path) -> bool:
        """Save workflow state, checking mtime first. Returns False if stale."""
        from workflow_state import save_workflow_state
        if self._cached_mtime is not None:
            try:
                current_mtime = path.stat().st_mtime
                if current_mtime != self._cached_mtime:
                    return False  # stale
            except OSError:
                pass  # file may not exist yet
        save_workflow_state(ws, path)
        self._cached_mtime = path.stat().st_mtime
        return True

    def update_task(
        self,
        task_id: str,
        status: Optional[str] = None,
        result_summary: Optional[str] = None,
        error: Optional[str] = None,
        callback_result: Optional[Dict[str, Any]] = None,
        execution_metadata: Optional[Dict[str, Any]] = None,
        subagent_task_id: Optional[str] = None,
    ) -> bool:
        """Update a task in the active WorkflowState. Returns True if found and updated.

        Uses mtime-based stale write detection: if the file was modified by
        another process since we last loaded it, we reload and retry.
        """
        with self._rw_lock:
            path = self.active_path
            if not path:
                return False
            for attempt in range(_MAX_STALE_RETRIES):
                try:
                    ws = self._load_with_mtime(path)
                    for batch in ws.batches:
                        for task in batch.tasks:
                            if task.task_id == task_id:
                                if status is not None:
                                    task.status = status
                                if result_summary is not None:
                                    task.result_summary = result_summary
                                if error is not None:
                                    task.error = error
                                if callback_result is not None:
                                    task.callback_result = callback_result
                                if execution_metadata is not None:
                                    task.execution_metadata.update(execution_metadata)
                                if subagent_task_id is not None:
                                    task.subagent_task_id = subagent_task_id
                                if self._save_with_mtime_check(ws, path):
                                    return True
                                # Stale — retry
                                logger.warning(
                                    "Stale write detected for task %s (attempt %d/%d), retrying",
                                    task_id, attempt + 1, _MAX_STALE_RETRIES,
                                )
                                break  # break inner loops, retry outer
                    else:
                        return False  # task_id not found
                except Exception:
                    logger.exception("workflow_state update failed for task %s", task_id)
                    return False
            logger.error("Stale write retries exhausted for task %s", task_id)
            return False

    def update_batch(
        self,
        batch_id: str,
        status: Optional[str] = None,
        continuation: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Update a batch in the active WorkflowState.

        Uses mtime-based stale write detection with retry.
        """
        with self._rw_lock:
            path = self.active_path
            if not path:
                return False
            for attempt in range(_MAX_STALE_RETRIES):
                try:
                    from workflow_state import ContinuationDecision
                    ws = self._load_with_mtime(path)
                    for batch in ws.batches:
                        if batch.batch_id == batch_id:
                            if status is not None:
                                batch.status = status
                            if continuation is not None:
                                batch.continuation = ContinuationDecision.from_dict(continuation)
                            if self._save_with_mtime_check(ws, path):
                                return True
                            logger.warning(
                                "Stale write detected for batch %s (attempt %d/%d), retrying",
                                batch_id, attempt + 1, _MAX_STALE_RETRIES,
                            )
                            break
                    else:
                        return False  # batch_id not found
                except Exception:
                    logger.exception("workflow_state batch update failed for batch %s", batch_id)
                    return False
            logger.error("Stale write retries exhausted for batch %s", batch_id)
            return False

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get task data from active WorkflowState."""
        path = self.active_path
        if not path:
            return None
        try:
            from workflow_state import load_workflow_state
            ws = load_workflow_state(path)
            for batch in ws.batches:
                for task in batch.tasks:
                    if task.task_id == task_id:
                        return task.to_dict()
        except Exception:
            logger.exception("workflow_state get_task failed for task %s", task_id)
        return None

    def get_batch(self, batch_id: str) -> Optional[Dict[str, Any]]:
        """Get batch data from active WorkflowState."""
        path = self.active_path
        if not path:
            return None
        try:
            from workflow_state import load_workflow_state
            ws = load_workflow_state(path)
            for batch in ws.batches:
                if batch.batch_id == batch_id:
                    return batch.to_dict()
        except Exception:
            logger.exception("workflow_state get_batch failed for batch %s", batch_id)
        return None

    def record_artifact(self, task_id: str, artifact_type: str, artifact_id: str) -> bool:
        """Record an artifact reference in the task's execution_metadata."""
        return self.update_task(
            task_id,
            execution_metadata={f"{artifact_type}_id": artifact_id},
        )


def get_store() -> WorkflowStateStore:
    """Get the global WorkflowStateStore singleton."""
    return WorkflowStateStore()
