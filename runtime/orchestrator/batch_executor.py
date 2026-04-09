from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import subprocess

from workflow_state import WorkflowState, BatchEntry, TaskEntry
from executor_interface import TaskExecutorBase, SubagentTaskExecutor, TaskResult

__all__ = ["BatchExecutor"]

logger = logging.getLogger(__name__)

_TERMINAL_RESULT_STATUSES = {"completed", "failed", "timed_out"}


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
        # When True, _sync_to_state_machine becomes a no-op.
        # Set by WorkflowLoop to prevent concurrent file writes:
        # WorkflowLoop._save() is the single writer for workflow_state
        # during loop execution; state_machine sync would trigger
        # cascading writes to the same file, causing lost updates.
        self.skip_store_sync = False

    @staticmethod
    def _tmux_session_exists(session_name: str) -> bool:
        """Check whether a tmux session with the given name is already alive."""
        try:
            ret = subprocess.run(
                ["tmux", "has-session", "-t", session_name],
                capture_output=True, timeout=5,
            )
            return ret.returncode == 0
        except (subprocess.SubprocessError, OSError):
            return False

    def execute_batch(self, batch: BatchEntry, workflow_state: WorkflowState) -> None:
        batch.status = "running"
        batch.started_at = _iso_now()
        for task in batch.tasks:
            if task.status != "pending":
                continue
            # Bug-2 guard: skip if a tmux session for this task already exists
            if task.subagent_task_id and self._tmux_session_exists(task.subagent_task_id):
                logger.info(
                    "task %s already has live tmux session %s — skipping dispatch",
                    task.task_id, task.subagent_task_id,
                )
                task.status = "running"
                continue
            task.status = "running"
            task.started_at = _iso_now()
            self._sync_to_state_machine(task.task_id, batch.batch_id, "running")
            try:
                handle = self._executor.execute(
                    task.task_id, task.label, {"batch_id": batch.batch_id}
                )
                task.subagent_task_id = handle
            except (OSError, RuntimeError, subprocess.SubprocessError) as e:
                logger.exception("failed to execute task %s", task.task_id)
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

    @staticmethod
    def _is_capacity_error(error: str) -> bool:
        """Detect MAX_SESSIONS capacity-full errors (should not consume retry budget)."""
        err_lower = error.lower()
        return ("active" in err_lower and "max" in err_lower) or \
               ("sessions" in err_lower and ("max" in err_lower or "limit" in err_lower))

    def _apply_retry_or_fail(self, task: TaskEntry, batch: BatchEntry, error: str) -> None:
        """Mark task for retry if retries remain, otherwise mark failed."""
        # Capacity-full is a transient condition — reset to pending without
        # consuming retry budget so queued tasks aren't falsely exhausted.
        if self._is_capacity_error(error):
            task.status = "pending"
            task.error = None
            task.subagent_task_id = None
            logger.info(
                "task %s capacity-full, pending without consuming retry budget",
                task.task_id,
            )
            return
        # max_retries: -1 = use default, 0 = no retries, >0 = that many retries
        effective_max = task.max_retries if task.max_retries >= 0 else self.default_max_retries
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
            # Clean up external state on permanent failure
            if task.subagent_task_id:
                try:
                    self._executor.cleanup(task.subagent_task_id)
                except (OSError, RuntimeError) as exc:
                    logger.warning("cleanup failed for subagent %s: %s", task.subagent_task_id, exc)

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
                    # Cancel the running executor before marking timed_out
                    if task.subagent_task_id:
                        try:
                            self._executor.cancel(task.subagent_task_id)
                            self._executor.cleanup(task.subagent_task_id)
                        except Exception:
                            logger.debug("cancel/cleanup failed for %s on timeout", task.subagent_task_id)
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
            except (OSError, RuntimeError, subprocess.SubprocessError) as e:
                logger.warning("poll failed for task %s: %s", task.task_id, e)
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
                # Light cleanup: remove in-memory tracking only.
                # Don't call cleanup() (which kills tmux) — let the session
                # die naturally so on-session-end.sh has time to run
                # (update reviewed-mrs.json, clean worktree, send notification).
                if hasattr(self._executor, '_task_session_map'):
                    self._executor._task_session_map.pop(task.subagent_task_id, None)
                    self._executor._start_times.pop(task.subagent_task_id, None)
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
            # Bug-2 guard: skip if a tmux session for this task already exists
            if task.subagent_task_id and self._tmux_session_exists(task.subagent_task_id):
                logger.info(
                    "task %s already has live tmux session %s — skipping redispatch",
                    task.task_id, task.subagent_task_id,
                )
                task.status = "running"
                continue
            task.status = "running"
            task.started_at = _iso_now()
            try:
                handle = self._executor.execute(
                    task.task_id, task.label, {"batch_id": batch.batch_id}
                )
                task.subagent_task_id = handle
            except (OSError, RuntimeError, subprocess.SubprocessError) as e:
                logger.exception("failed to redispatch task %s", task.task_id)
                self._apply_retry_or_fail(task, batch, str(e))

    def _sync_to_state_machine(
        self, task_id: str, batch_id: str, status: str, result: dict | None = None
    ) -> None:
        if self.skip_store_sync:
            return
        try:
            from state_sync import sync_task_to_state_machine
            sync_task_to_state_machine(task_id, batch_id, status, result)
        except Exception:
            logger.warning("state_machine sync skipped for %s", task_id, exc_info=True)
