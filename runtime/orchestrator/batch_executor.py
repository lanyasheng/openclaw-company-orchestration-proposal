from __future__ import annotations

import json
import logging
from datetime import datetime

from workflow_state import WorkflowState, BatchEntry, TaskEntry
from subagent_executor import SubagentExecutor, SubagentConfig, TERMINAL_STATES

__all__ = ["BatchExecutor"]

logger = logging.getLogger(__name__)


def _iso_now() -> str:
    return datetime.now().isoformat()


class BatchExecutor:
    def __init__(self, workspace_dir: str, timeout_seconds: int = 900):
        self.workspace_dir = workspace_dir
        self.timeout_seconds = timeout_seconds
        self._executor: SubagentExecutor | None = None

    @property
    def executor(self) -> SubagentExecutor:
        if self._executor is None:
            config = SubagentConfig(
                label="batch-task",
                runtime="subagent",
                timeout_seconds=self.timeout_seconds,
            )
            self._executor = SubagentExecutor(config=config, cwd=self.workspace_dir)
        return self._executor

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
                sub_id = self.executor.execute_async(task.label)
                task.subagent_task_id = sub_id
            except Exception as e:
                task.status = "failed"
                task.error = str(e)
                task.completed_at = _iso_now()
                self._sync_to_state_machine(task.task_id, batch.batch_id, "failed")

    def monitor_batch(self, batch: BatchEntry) -> bool:
        if not any(t.status == "running" for t in batch.tasks):
            if batch.status == "running":
                batch.status = "completed"
                batch.completed_at = _iso_now()
            return True

        for task in batch.tasks:
            if task.status != "running" or not task.subagent_task_id:
                continue
            try:
                result = self.executor.get_result(task.subagent_task_id)
            except Exception as e:
                task.status = "failed"
                task.error = str(e)
                task.completed_at = _iso_now()
                continue
            if result is None:
                continue
            if result.status in TERMINAL_STATES:
                if result.status == "completed":
                    task.status = "completed"
                    task.completed_at = _iso_now()
                    task.result_summary = (
                        result.result if isinstance(result.result, str)
                        else json.dumps(result.result) if result.result else ""
                    )
                    task.callback_result = {
                        "verdict": "PASS",
                        "raw": result.result,
                    }
                    task.execution_metadata["completed_by"] = "subagent"
                    task.execution_metadata["subagent_status"] = result.status
                    self._sync_to_state_machine(
                        task.task_id, batch.batch_id, "completed",
                        result={"verdict": "PASS", "summary": task.result_summary},
                    )
                elif task.retry_count < task.max_retries:
                    task.retry_count += 1
                    task.status = "pending"
                    task.error = None
                    task.subagent_task_id = None
                else:
                    task.status = "failed"
                    task.completed_at = _iso_now()
                    task.error = result.error or result.status
                    task.callback_result = {
                        "verdict": "FAIL",
                        "error": task.error,
                    }
                    task.execution_metadata["completed_by"] = "subagent"
                    task.execution_metadata["subagent_status"] = result.status
                    self._sync_to_state_machine(
                        task.task_id, batch.batch_id, "failed",
                        result={"error": task.error},
                    )

        all_done = all(t.status != "running" for t in batch.tasks)
        if all_done and batch.status == "running":
            batch.status = "completed"
            batch.completed_at = _iso_now()
        return all_done

    @staticmethod
    def _sync_to_state_machine(
        task_id: str, batch_id: str, status: str, result: dict | None = None
    ) -> None:
        try:
            from state_sync import sync_task_to_state_machine
            sync_task_to_state_machine(task_id, batch_id, status, result)
        except Exception:
            logger.debug("state_machine sync skipped for %s", task_id, exc_info=True)
