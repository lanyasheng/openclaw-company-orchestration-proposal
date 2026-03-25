"""End-to-end workflow tests.

These tests validate the FULL orchestration pipeline:
  plan → run → (subagent executes) → monitor → review → advance → completed

They use a real stub runner script that writes a result file, proving
the entire chain works without simulation or mocked internals.
"""

import json
import os
import stat
import sys
import textwrap
import time
from pathlib import Path

import pytest

ORCH_DIR = Path(__file__).resolve().parent.parent.parent / "runtime" / "orchestrator"
sys.path.insert(0, str(ORCH_DIR))

from workflow_state import (
    WorkflowState,
    create_workflow,
    save_workflow_state,
    load_workflow_state,
)
from task_planner import TaskPlanner
from workflow_loop import WorkflowLoop


@pytest.fixture
def workspace(tmp_path):
    """Create a workspace with a stub runner script that writes result JSON."""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    runner = scripts_dir / "run_subagent_claude_v1.sh"
    runner.write_text(textwrap.dedent("""\
        #!/usr/bin/env bash
        set -euo pipefail
        TASK_ID="${OPENCLAW_TASK_ID:?}"
        STATE_DIR="${OPENCLAW_SUBAGENT_STATE_DIR:?}"
        mkdir -p "$STATE_DIR"
        python3 -c "
import json, os
task_id = os.environ['OPENCLAW_TASK_ID']
state_dir = os.environ['OPENCLAW_SUBAGENT_STATE_DIR']
result = {
    'task_id': task_id,
    'status': 'completed',
    'result': 'stub runner output for ' + task_id,
    'task': '',
    'config': {'label': 'test', 'runtime': 'subagent', 'timeout_seconds': 900},
}
with open(os.path.join(state_dir, task_id + '.json'), 'w') as f:
    json.dump(result, f)
"
    """))
    runner.chmod(runner.stat().st_mode | stat.S_IEXEC)

    state_dir = tmp_path / "subagent_states"
    state_dir.mkdir()
    return tmp_path, state_dir


@pytest.fixture
def failing_workspace(tmp_path):
    """Create a workspace with a runner script that always fails."""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    runner = scripts_dir / "run_subagent_claude_v1.sh"
    runner.write_text(textwrap.dedent("""\
        #!/usr/bin/env bash
        set -euo pipefail
        TASK_ID="${OPENCLAW_TASK_ID:?}"
        STATE_DIR="${OPENCLAW_SUBAGENT_STATE_DIR:?}"
        mkdir -p "$STATE_DIR"
        python3 -c "
import json, os
task_id = os.environ['OPENCLAW_TASK_ID']
state_dir = os.environ['OPENCLAW_SUBAGENT_STATE_DIR']
result = {
    'task_id': task_id,
    'status': 'failed',
    'error': 'deliberate failure for testing',
    'task': '',
    'config': {'label': 'test', 'runtime': 'subagent', 'timeout_seconds': 900},
}
with open(os.path.join(state_dir, task_id + '.json'), 'w') as f:
    json.dump(result, f)
"
        exit 1
    """))
    runner.chmod(runner.stat().st_mode | stat.S_IEXEC)

    state_dir = tmp_path / "subagent_states"
    state_dir.mkdir()
    return tmp_path, state_dir


class TestE2ESingleBatch:
    """Single batch with 2 tasks — the simplest happy path."""

    def test_plan_run_completed(self, workspace, monkeypatch):
        ws_dir, state_dir = workspace
        monkeypatch.setenv("OPENCLAW_SUBAGENT_STATE_DIR", str(state_dir))

        config = [
            {
                "batch_id": "b1",
                "label": "Step 1",
                "tasks": [
                    {"task_id": "t1", "label": "Task A"},
                    {"task_id": "t2", "label": "Task B"},
                ],
            },
        ]

        planner = TaskPlanner()
        state = planner.plan("E2E single batch test", config)
        state_path = ws_dir / "workflow_state.json"
        save_workflow_state(state, state_path)

        assert state.status == "pending"
        assert len(state.batches) == 1
        assert len(state.batches[0].tasks) == 2

        loop = WorkflowLoop(str(ws_dir), timeout_seconds=30, poll_interval=0.5)
        result = loop.run(str(state_path))

        assert result.status == "completed", (
            f"Expected completed but got {result.status}. "
            f"Tasks: {[(t.task_id, t.status, t.error) for t in result.batches[0].tasks]}"
        )
        assert result.batches[0].status == "completed"
        for task in result.batches[0].tasks:
            assert task.status == "completed", f"Task {task.task_id}: {task.error}"
            assert "stub runner output" in (task.result_summary or "")

        reloaded = load_workflow_state(state_path)
        assert reloaded.status == "completed"


class TestE2EMultiBatch:
    """Two sequential batches — verifies auto-advance to next batch."""

    def test_two_batches_auto_advance(self, workspace, monkeypatch):
        ws_dir, state_dir = workspace
        monkeypatch.setenv("OPENCLAW_SUBAGENT_STATE_DIR", str(state_dir))

        config = [
            {
                "batch_id": "b1",
                "label": "Phase 1",
                "tasks": [{"task_id": "t1", "label": "First task"}],
            },
            {
                "batch_id": "b2",
                "label": "Phase 2",
                "depends_on": ["b1"],
                "tasks": [{"task_id": "t2", "label": "Second task"}],
            },
        ]

        planner = TaskPlanner()
        state = planner.plan("E2E multi-batch test", config)
        state_path = ws_dir / "workflow_state.json"
        save_workflow_state(state, state_path)

        loop = WorkflowLoop(str(ws_dir), timeout_seconds=30, poll_interval=0.5)
        result = loop.run(str(state_path))

        assert result.status == "completed", (
            f"Expected completed, got {result.status}. "
            f"Batch statuses: {[(b.batch_id, b.status) for b in result.batches]}"
        )
        for batch in result.batches:
            assert batch.status == "completed"
            for task in batch.tasks:
                assert task.status == "completed", f"{task.task_id}: {task.error}"

        assert result.batches[0].continuation is not None
        assert result.batches[0].continuation.decision == "proceed"


class TestE2EFailureHandling:
    """Verify the workflow stops correctly when a task fails."""

    def test_failed_task_stops_workflow(self, failing_workspace, monkeypatch):
        ws_dir, state_dir = failing_workspace
        monkeypatch.setenv("OPENCLAW_SUBAGENT_STATE_DIR", str(state_dir))

        config = [
            {
                "batch_id": "b1",
                "label": "Will fail",
                "fan_in_policy": "all_success",
                "tasks": [{"task_id": "t_fail", "label": "Failing task"}],
            },
        ]

        planner = TaskPlanner()
        state = planner.plan("E2E failure test", config)
        state_path = ws_dir / "workflow_state.json"
        save_workflow_state(state, state_path)

        loop = WorkflowLoop(str(ws_dir), timeout_seconds=30, poll_interval=0.5)
        result = loop.run(str(state_path))

        assert result.status == "failed"
        assert result.batches[0].tasks[0].status == "failed"


class TestE2ERetry:
    """Verify task retry works before failing permanently."""

    def test_retry_then_fail(self, failing_workspace, monkeypatch):
        ws_dir, state_dir = failing_workspace
        monkeypatch.setenv("OPENCLAW_SUBAGENT_STATE_DIR", str(state_dir))

        config = [
            {
                "batch_id": "b1",
                "label": "Retry test",
                "fan_in_policy": "all_success",
                "tasks": [{"task_id": "t_retry", "label": "Retryable task"}],
            },
        ]

        state = create_workflow("wf_retry", "Retry test", config)
        state.batches[0].tasks[0].max_retries = 1
        state_path = ws_dir / "workflow_state.json"
        save_workflow_state(state, state_path)

        loop = WorkflowLoop(str(ws_dir), timeout_seconds=30, poll_interval=0.5)
        result = loop.run(str(state_path))

        task = result.batches[0].tasks[0]
        assert task.status == "failed"
        assert task.retry_count == 1, "Should have retried once before failing"


class TestE2ETestMode:
    """Verify test mode works without a runner script."""

    def test_test_mode_completes(self, tmp_path, monkeypatch):
        state_dir = tmp_path / "subagent_states"
        state_dir.mkdir()
        monkeypatch.setenv("OPENCLAW_SUBAGENT_STATE_DIR", str(state_dir))
        monkeypatch.setenv("OPENCLAW_TEST_MODE", "1")

        config = [
            {
                "batch_id": "b1",
                "label": "Test mode batch",
                "tasks": [{"task_id": "t_test", "label": "Test task"}],
            },
        ]

        planner = TaskPlanner()
        state = planner.plan("Test mode E2E", config)
        state_path = tmp_path / "workflow_state.json"
        save_workflow_state(state, state_path)

        loop = WorkflowLoop(str(tmp_path), timeout_seconds=30, poll_interval=0.5)
        result = loop.run(str(state_path))

        assert result.status == "completed", (
            f"Test mode should complete, got {result.status}. "
            f"Task: {result.batches[0].tasks[0].status} / {result.batches[0].tasks[0].error}"
        )


class TestE2EPluggableExecutor:
    """Verify custom executor works via TaskExecutorBase."""

    def test_custom_executor(self, tmp_path):
        from executor_interface import TaskExecutorBase, TaskResult

        class InMemoryExecutor(TaskExecutorBase):
            def __init__(self):
                self._tasks = {}

            def execute(self, task_id, label, context):
                self._tasks[task_id] = TaskResult(
                    status="completed", output=f"in-memory result for {label}"
                )
                return task_id

            def poll(self, handle):
                return self._tasks.get(handle, TaskResult(status="pending"))

        from batch_executor import BatchExecutor

        config = [
            {
                "batch_id": "b1",
                "label": "Custom executor batch",
                "tasks": [
                    {"task_id": "t1", "label": "Custom A"},
                    {"task_id": "t2", "label": "Custom B"},
                ],
            },
        ]

        state = create_workflow("wf_custom", "Custom executor test", config)
        state_path = tmp_path / "workflow_state.json"
        save_workflow_state(state, state_path)

        custom_exec = InMemoryExecutor()
        batch_exec = BatchExecutor(str(tmp_path), executor=custom_exec)

        batch = state.batches[0]
        batch_exec.execute_batch(batch, state)

        assert all(t.subagent_task_id is not None for t in batch.tasks)

        done = batch_exec.monitor_batch(batch)

        assert done is True
        assert batch.status == "completed"
        for task in batch.tasks:
            assert task.status == "completed"
            assert "in-memory result" in task.result_summary
