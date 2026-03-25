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


class WorkflowStateStore:
    """Thread-safe singleton for active workflow state access."""

    _instance: Optional[WorkflowStateStore] = None
    _lock = threading.Lock()

    def __new__(cls) -> WorkflowStateStore:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._active_path: Optional[Path] = None
                cls._instance._rw_lock = threading.RLock()
            return cls._instance

    def set_active(self, path: str | Path) -> None:
        with self._rw_lock:
            self._active_path = Path(path)

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
        """Update a task in the active WorkflowState. Returns True if found and updated."""
        with self._rw_lock:
            path = self.active_path
            if not path:
                return False
            try:
                from workflow_state import load_workflow_state, save_workflow_state
                ws = load_workflow_state(path)
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
                            save_workflow_state(ws, path)
                            return True
            except Exception as exc:
                logger.debug("workflow_state update failed: %s", exc)
            return False

    def update_batch(
        self,
        batch_id: str,
        status: Optional[str] = None,
        continuation: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Update a batch in the active WorkflowState."""
        with self._rw_lock:
            path = self.active_path
            if not path:
                return False
            try:
                from workflow_state import (
                    load_workflow_state,
                    save_workflow_state,
                    ContinuationDecision,
                )
                ws = load_workflow_state(path)
                for batch in ws.batches:
                    if batch.batch_id == batch_id:
                        if status is not None:
                            batch.status = status
                        if continuation is not None:
                            batch.continuation = ContinuationDecision.from_dict(continuation)
                        save_workflow_state(ws, path)
                        return True
            except Exception as exc:
                logger.debug("workflow_state batch update failed: %s", exc)
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
            pass
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
            pass
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
