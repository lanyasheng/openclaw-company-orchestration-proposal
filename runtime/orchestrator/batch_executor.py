from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

from workflow_state import WorkflowState, BatchEntry, TaskEntry
from executor_interface import TaskExecutorBase, SubagentTaskExecutor, TaskResult

__all__ = ["BatchExecutor"]

logger = logging.getLogger(__name__)

_TERMINAL_RESULT_STATUSES = {"completed", "failed", "timed_out"}


def _iso_now() -> str:
    return datetime.now().isoformat()


class BatchExecutor:
    """Executes and monitors a batch of tasks using a pluggable executor.

    By default uses ``SubagentTaskExecutor``.  Pass a custom
    ``TaskExecutorBase`` via *executor_factory* to use a different backend
    (HTTP workers, LangChain agents, etc.).
    """

    def __init__(
        self,
        workspace_dir: str,
        timeout_seconds: int = 900,
        executor: Optional[TaskExecutorBase] = None,
    ):
        self.workspace_dir = workspace_dir
        self.timeout_seconds = timeout_seconds
        self._executor: TaskExecutorBase = executor or SubagentTaskExecutor(
            workspace_dir, timeout_seconds
        )

    def execute_batch(self, batch: BatchEntry, workflow_state: WorkflowState) -> None:
        batch.status = "running"
        batch.started_at = _iso_now()
        for task in batch.tasks:
            if task.status != "pending":
                continue
            task.status = "running"
            task.started_at = _iso_now()
            self._sync_to_state_machine(task.task_id, batch.batch_id, "running")
            try:
                handle = self._executor.execute(
                    task.task_id, task.label, {"batch_id": batch.batch_id}
                )
                task.subagent_task_id = handle
            except Exception as e:
                task.status = "failed"
                task.error = str(e)
                task.completed_at = _iso_now()
                self._sync_to_state_machine(task.task_id, batch.batch_id, "failed")

    def monitor_batch(self, batch: BatchEntry) -> bool:
        if not any(t.status == "running" for t in batch.tasks):
            pending_retries = [t for t in batch.tasks if t.status == "pending"]
            if pending_retries:
                self._redispatch_pending(pending_retries, batch)
                return False
            if batch.status == "running":
                batch.status = "completed"
                batch.completed_at = _iso_now()
            return True

        for task in batch.tasks:
            if task.status != "running" or not task.subagent_task_id:
                continue
            try:
                tr: TaskResult = self._executor.poll(task.subagent_task_id)
            except Exception as e:
                task.status = "failed"
                task.error = str(e)
                task.completed_at = _iso_now()
                continue
            if tr.status == "completed":
                task.status = "completed"
                task.completed_at = _iso_now()
                task.result_summary = tr.output or ""
                task.callback_result = {"verdict": "PASS", "raw": tr.output}
                task.execution_metadata["completed_by"] = "executor"
                task.execution_metadata["executor_status"] = tr.status
                self._sync_to_state_machine(
                    task.task_id, batch.batch_id, "completed",
                    result={"verdict": "PASS", "summary": task.result_summary},
                )
            elif tr.status in ("failed", "timed_out"):
                if task.retry_count < task.max_retries:
                    task.retry_count += 1
                    task.status = "pending"
                    task.error = None
                    task.subagent_task_id = None
                else:
                    task.status = "failed"
                    task.completed_at = _iso_now()
                    task.error = tr.error or tr.status
                    task.callback_result = {"verdict": "FAIL", "error": task.error}
                    task.execution_metadata["completed_by"] = "executor"
                    task.execution_metadata["executor_status"] = tr.status
                    self._sync_to_state_machine(
                        task.task_id, batch.batch_id, "failed",
                        result={"error": task.error},
                    )

        has_running = any(t.status == "running" for t in batch.tasks)
        has_pending = any(t.status == "pending" for t in batch.tasks)
        if not has_running and has_pending:
            self._redispatch_pending(
                [t for t in batch.tasks if t.status == "pending"], batch
            )
            return False

        all_done = not has_running and not has_pending
        if all_done and batch.status == "running":
            batch.status = "completed"
            batch.completed_at = _iso_now()
        return all_done

    def _redispatch_pending(self, tasks: list[TaskEntry], batch: BatchEntry) -> None:
        """Re-dispatch tasks that were reset to pending after a retry."""
        for task in tasks:
            task.status = "running"
            task.started_at = _iso_now()
            try:
                handle = self._executor.execute(
                    task.task_id, task.label, {"batch_id": batch.batch_id}
                )
                task.subagent_task_id = handle
            except Exception as e:
                task.status = "failed"
                task.error = str(e)
                task.completed_at = _iso_now()

    @staticmethod
    def _sync_to_state_machine(
        task_id: str, batch_id: str, status: str, result: dict | None = None
    ) -> None:
        try:
            from state_sync import sync_task_to_state_machine
            sync_task_to_state_machine(task_id, batch_id, status, result)
        except Exception:
            logger.debug("state_machine sync skipped for %s", task_id, exc_info=True)
