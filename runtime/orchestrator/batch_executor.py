from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
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
        batch_timeout: int = 7200,
        default_max_retries: int = 3,
    ):
        self.workspace_dir = workspace_dir
        self.timeout_seconds = timeout_seconds
        self.batch_timeout = batch_timeout
        self.default_max_retries = default_max_retries
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

    def _batch_elapsed_seconds(self, batch: BatchEntry) -> float:
        """Return seconds since batch started, or 0 if not started."""
        if not batch.started_at:
            return 0.0
        try:
            started = datetime.fromisoformat(batch.started_at)
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            return max((now - started).total_seconds(), 0.0)
        except (ValueError, TypeError):
            return 0.0

    def _apply_retry_or_fail(self, task: TaskEntry, batch: BatchEntry, error: str) -> None:
        """Mark task for retry if retries remain, otherwise mark failed."""
        effective_max = task.max_retries if task.max_retries > 0 else self.default_max_retries
        if task.retry_count < effective_max:
            task.retry_count += 1
            task.status = "pending"
            task.error = None
            task.subagent_task_id = None
            logger.info(
                "task %s retry %d/%d after: %s",
                task.task_id, task.retry_count, effective_max, error,
            )
        else:
            task.status = "failed"
            task.completed_at = _iso_now()
            task.error = error
            task.callback_result = {"verdict": "FAIL", "error": error}
            task.execution_metadata["completed_by"] = "executor"
            task.execution_metadata["executor_status"] = "failed"
            self._sync_to_state_machine(
                task.task_id, batch.batch_id, "failed",
                result={"error": error},
            )

    def monitor_batch(self, batch: BatchEntry) -> bool:
        # ── Hard batch timeout ───────────────────────────────────────
        elapsed = self._batch_elapsed_seconds(batch)
        if elapsed > self.batch_timeout:
            logger.warning(
                "batch %s hard timeout after %.0fs (limit %ds)",
                batch.batch_id, elapsed, self.batch_timeout,
            )
            for task in batch.tasks:
                if task.status == "running":
                    task.status = "timed_out"
                    task.error = f"batch hard timeout after {int(elapsed)}s"
                    task.completed_at = _iso_now()
                    # Attempt retry for timed-out tasks
                    self._apply_retry_or_fail(
                        task, batch,
                        f"batch hard timeout after {int(elapsed)}s",
                    )

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
                self._apply_retry_or_fail(task, batch, str(e))
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
                self._apply_retry_or_fail(
                    task, batch, tr.error or tr.status,
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
