from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

from workflow_state import (
    WorkflowState,
    BatchEntry,
    load_workflow_state,
    save_workflow_state,
    get_current_batch,
    get_next_batch,
    dependencies_met,
    update_context_summary,
)
from batch_executor import BatchExecutor
from batch_reviewer import BatchReviewer

__all__ = ["WorkflowLoop"]

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL = 5.0


class WorkflowLoop:
    """Main orchestration loop: plan → execute → review → advance → repeat"""

    def __init__(
        self,
        workspace_dir: str,
        timeout_seconds: int = 900,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        backend: str = "auto",
        max_runtime_seconds: int = 86400,
    ):
        executor = None
        if backend == "tmux":
            from tmux_executor import TmuxTaskExecutor
            executor = TmuxTaskExecutor(workspace_dir, timeout_seconds)
        elif backend == "auto":
            import shutil
            if shutil.which("tmux"):
                from tmux_executor import TmuxTaskExecutor
                executor = TmuxTaskExecutor(workspace_dir, timeout_seconds)
        # else: default SubagentTaskExecutor via BatchExecutor
        self.executor = BatchExecutor(workspace_dir, timeout_seconds, executor=executor)
        # WorkflowLoop._save() is the single writer for workflow_state.
        # Disable state_machine sync in BatchExecutor to prevent cascading
        # writes to the same file (lost-update race condition).
        self.executor.skip_store_sync = True
        self.reviewer = BatchReviewer()
        self.poll_interval = poll_interval
        self.max_runtime_seconds = max_runtime_seconds

    def run(self, workflow_state_path: str | Path) -> WorkflowState:
        state = load_workflow_state(workflow_state_path)
        if state.status in ("completed", "failed"):
            logger.info("workflow %s already %s", state.workflow_id, state.status)
            return state

        state.status = "running"
        self._save(state, workflow_state_path)

        run_start = time.monotonic()

        while state.status == "running":
            try:
                # ── Global workflow timeout ───────────────────────────────
                elapsed = time.monotonic() - run_start
                if elapsed > self.max_runtime_seconds:
                    logger.error(
                        "workflow %s timed out after %.0fs (limit %ds)",
                        state.workflow_id, elapsed, self.max_runtime_seconds,
                    )
                    state.status = "timed_out"
                    self._save(state, workflow_state_path)
                    break
                batch = get_current_batch(state)
                if batch is None:
                    state.status = "completed"
                    break

                if batch.status == "pending":
                    if not dependencies_met(state, batch):
                        logger.warning(
                            "batch %s dependencies not met — this indicates a DAG ordering issue",
                            batch.batch_id,
                        )
                        state.status = "failed"
                        break

                    logger.info("dispatching batch %s", batch.batch_id)
                    self.executor.execute_batch(batch, state)
                    self._save(state, workflow_state_path)

                if batch.status == "running":
                    completed = self.executor.monitor_batch(batch)
                    self._save(state, workflow_state_path)
                    if not completed:
                        time.sleep(self.poll_interval)
                        continue

                if batch.status in ("completed", "failed"):
                    continuation = self.reviewer.review(batch, state)
                    batch.continuation = continuation
                    logger.info(
                        "batch %s reviewed: %s (%s)",
                        batch.batch_id,
                        continuation.decision,
                        continuation.stopped_because,
                    )

                    if continuation.decision == "proceed":
                        next_b = get_next_batch(state)
                        if next_b is None:
                            state.status = "completed"
                        else:
                            state.plan["current_batch_index"] = state.plan.get("current_batch_index", 0) + 1
                    elif continuation.decision == "gate":
                        state.status = "gate_blocked"
                    elif continuation.decision == "stop":
                        state.status = "failed"

                    self._save(state, workflow_state_path)
            except Exception:
                logger.exception("workflow %s crashed in main loop", state.workflow_id)
                state.status = "failed"
                self._save(state, workflow_state_path)
                break

        update_context_summary(state)
        self._save(state, workflow_state_path)
        logger.info("workflow %s finished with status: %s", state.workflow_id, state.status)
        return state

    def resume(self, workflow_state_path: str | Path) -> WorkflowState:
        state = load_workflow_state(workflow_state_path)
        if state.status == "gate_blocked":
            state.status = "running"
            save_workflow_state(state, workflow_state_path)
        return self.run(workflow_state_path)

    def _save(self, state: WorkflowState, path: str | Path) -> None:
        update_context_summary(state)
        save_workflow_state(state, path)
