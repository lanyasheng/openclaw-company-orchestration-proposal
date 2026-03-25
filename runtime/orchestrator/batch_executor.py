from __future__ import annotations

import json
from datetime import datetime

from workflow_state import WorkflowState, BatchEntry, TaskEntry
from subagent_executor import SubagentExecutor, SubagentConfig, TERMINAL_STATES

__all__ = ["BatchExecutor"]


def _iso_now() -> str:
    return datetime.now().isoformat()


class BatchExecutor:
    def __init__(self, workspace_dir: str, timeout_seconds: int = 900):
        self.workspace_dir = workspace_dir
        self.timeout_seconds = timeout_seconds

    def _create_executor(self) -> SubagentExecutor:
        config = SubagentConfig(
            label="batch-task",
            runtime="subagent",
            timeout_seconds=self.timeout_seconds,
        )
        return SubagentExecutor(config=config, cwd=self.workspace_dir)

    def execute_batch(self, batch: BatchEntry, workflow_state: WorkflowState) -> None:
        _ = workflow_state
        batch.status = "running"
        batch.started_at = _iso_now()
        executor = self._create_executor()
        for task in batch.tasks:
            if task.status != "pending":
                continue
            task.status = "running"
            task.started_at = _iso_now()
            try:
                sub_id = executor.execute_async(task.label)
                task.subagent_task_id = sub_id
            except Exception as e:
                task.status = "failed"
                task.error = str(e)
                task.completed_at = _iso_now()

    def monitor_batch(self, batch: BatchEntry) -> bool:
        if not any(t.status == "running" for t in batch.tasks):
            if batch.status == "running":
                batch.status = "completed"
                batch.completed_at = _iso_now()
            return True

        executor = self._create_executor()
        for task in batch.tasks:
            if task.status != "running" or not task.subagent_task_id:
                continue
            try:
                result = executor.get_result(task.subagent_task_id)
            except Exception as e:
                task.status = "failed"
                task.error = str(e)
                task.completed_at = _iso_now()
                continue
            if result is None:
                continue
            if result.status in TERMINAL_STATES:
                task.completed_at = _iso_now()
                if result.status == "completed":
                    task.status = "completed"
                    task.result_summary = (
                        result.result if isinstance(result.result, str)
                        else json.dumps(result.result) if result.result else ""
                    )
                else:
                    task.status = "failed"
                    task.error = result.error or result.status

        all_done = all(t.status != "running" for t in batch.tasks)
        if all_done and batch.status == "running":
            batch.status = "completed"
            batch.completed_at = _iso_now()
        return all_done
