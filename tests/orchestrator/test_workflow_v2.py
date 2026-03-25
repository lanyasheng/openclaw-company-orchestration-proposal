"""Tests for v2 unified main chain: workflow_state, task_planner, batch_reviewer, workflow_graph."""

import json
import os
import tempfile

import pytest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'runtime', 'orchestrator'))

from workflow_state import (
    WorkflowState,
    BatchEntry,
    TaskEntry,
    ContinuationDecision,
    create_workflow,
    save_workflow_state,
    load_workflow_state,
    get_current_batch,
    get_next_batch,
    dependencies_met,
    update_context_summary,
)
from task_planner import TaskPlanner
from batch_reviewer import BatchReviewer


# ─── WorkflowState ───────────────────────────────────────────────────

class TestWorkflowState:
    def test_create_workflow(self):
        state = create_workflow("wf_test", "Test workflow", [
            {"batch_id": "b0", "label": "Step 1", "tasks": [
                {"task_id": "t1", "label": "Task 1"},
            ]},
        ])
        assert state.workflow_id == "wf_test"
        assert state.status == "pending"
        assert len(state.batches) == 1
        assert state.batches[0].tasks[0].task_id == "t1"

    def test_save_load_roundtrip(self, tmp_path):
        state = create_workflow("wf_rt", "Roundtrip", [
            {"batch_id": "b0", "label": "S1", "tasks": [
                {"task_id": "t1", "label": "T1"},
            ]},
        ])
        path = tmp_path / "state.json"
        save_workflow_state(state, path)
        loaded = load_workflow_state(path)
        assert loaded.workflow_id == "wf_rt"
        assert len(loaded.batches) == 1
        assert loaded.batches[0].tasks[0].task_id == "t1"

    def test_load_nonexistent_raises(self):
        with pytest.raises(FileNotFoundError):
            load_workflow_state("/nonexistent/path.json")

    def test_get_current_batch(self):
        state = create_workflow("wf", "Test", [
            {"batch_id": "b0", "label": "S0", "tasks": []},
            {"batch_id": "b1", "label": "S1", "tasks": []},
        ])
        batch = get_current_batch(state)
        assert batch.batch_id == "b0"

    def test_get_current_batch_out_of_range(self):
        state = create_workflow("wf", "Test", [
            {"batch_id": "b0", "label": "S0", "tasks": []},
        ])
        state.plan["current_batch_index"] = 5
        assert get_current_batch(state) is None

    def test_get_next_batch(self):
        state = create_workflow("wf", "Test", [
            {"batch_id": "b0", "label": "S0", "tasks": []},
            {"batch_id": "b1", "label": "S1", "tasks": []},
        ])
        assert get_next_batch(state).batch_id == "b1"

    def test_get_next_batch_at_end(self):
        state = create_workflow("wf", "Test", [
            {"batch_id": "b0", "label": "S0", "tasks": []},
        ])
        assert get_next_batch(state) is None

    def test_dependencies_met_no_deps(self):
        state = create_workflow("wf", "Test", [
            {"batch_id": "b0", "label": "S0", "tasks": [], "depends_on": []},
        ])
        assert dependencies_met(state, state.batches[0]) is True

    def test_dependencies_met_incomplete(self):
        state = create_workflow("wf", "Test", [
            {"batch_id": "b0", "label": "S0", "tasks": []},
            {"batch_id": "b1", "label": "S1", "tasks": [], "depends_on": ["b0"]},
        ])
        assert dependencies_met(state, state.batches[1]) is False

    def test_dependencies_met_complete(self):
        state = create_workflow("wf", "Test", [
            {"batch_id": "b0", "label": "S0", "tasks": []},
            {"batch_id": "b1", "label": "S1", "tasks": [], "depends_on": ["b0"]},
        ])
        state.batches[0].status = "completed"
        assert dependencies_met(state, state.batches[1]) is True

    def test_update_context_summary(self):
        state = create_workflow("wf", "Test", [
            {"batch_id": "b0", "label": "S0", "tasks": [
                {"task_id": "t1", "label": "T1"},
            ]},
        ])
        state.batches[0].tasks[0].status = "completed"
        state.batches[0].tasks[0].result_summary = "done"
        update_context_summary(state)
        assert "done" in state.context_summary
        assert "completed" in state.context_summary

    def test_task_entry_serialization(self):
        entry = TaskEntry(task_id="t1", label="Test", subagent_task_id="sub_123")
        d = entry.to_dict()
        loaded = TaskEntry.from_dict(d)
        assert loaded.subagent_task_id == "sub_123"

    def test_continuation_decision_serialization(self):
        dec = ContinuationDecision(
            stopped_because="all done",
            decision="proceed",
            next_batch="b1",
            decided_at="2026-03-25T10:00:00Z",
        )
        d = dec.to_dict()
        loaded = ContinuationDecision.from_dict(d)
        assert loaded.decision == "proceed"
        assert loaded.next_batch == "b1"

    def test_atomic_write(self, tmp_path):
        path = tmp_path / "state.json"
        state = create_workflow("wf", "Test", [
            {"batch_id": "b0", "label": "S0", "tasks": []},
        ])
        save_workflow_state(state, path)
        assert not (tmp_path / "state.json.tmp").exists()
        assert path.exists()


# ─── TaskPlanner ─────────────────────────────────────────────────────

class TestTaskPlanner:
    def test_plan_basic(self):
        planner = TaskPlanner()
        state = planner.plan("Test", [
            {"batch_id": "b0", "label": "S0", "tasks": [{"task_id": "t1", "label": "T1"}], "depends_on": []},
        ])
        assert len(state.batches) == 1
        assert state.plan["total_batches"] == 1

    def test_plan_with_dependencies(self):
        planner = TaskPlanner()
        state = planner.plan("Test", [
            {"batch_id": "b0", "label": "S0", "tasks": [{"task_id": "t1", "label": "T1"}], "depends_on": []},
            {"batch_id": "b1", "label": "S1", "tasks": [{"task_id": "t2", "label": "T2"}], "depends_on": ["b0"]},
        ])
        assert len(state.batches) == 2

    def test_plan_rejects_cycle(self):
        planner = TaskPlanner()
        with pytest.raises(ValueError, match="cycle"):
            planner.plan("Cycle", [
                {"batch_id": "a", "label": "A", "tasks": [{"task_id": "t1", "label": "T1"}], "depends_on": ["b"]},
                {"batch_id": "b", "label": "B", "tasks": [{"task_id": "t2", "label": "T2"}], "depends_on": ["a"]},
            ])

    def test_plan_rejects_unknown_dep(self):
        planner = TaskPlanner()
        with pytest.raises(ValueError, match="unknown"):
            planner.plan("Bad", [
                {"batch_id": "a", "label": "A", "tasks": [{"task_id": "t1", "label": "T1"}], "depends_on": ["nonexistent"]},
            ])

    def test_plan_rejects_duplicate_ids(self):
        planner = TaskPlanner()
        with pytest.raises(ValueError, match="duplicate"):
            planner.plan("Dup", [
                {"batch_id": "a", "label": "A", "tasks": [{"task_id": "t1", "label": "T1"}], "depends_on": []},
                {"batch_id": "a", "label": "A2", "tasks": [{"task_id": "t2", "label": "T2"}], "depends_on": []},
            ])

    def test_topological_sort(self):
        planner = TaskPlanner()
        order = planner.topological_sort([
            {"batch_id": "c", "label": "C", "tasks": [], "depends_on": ["a", "b"]},
            {"batch_id": "a", "label": "A", "tasks": [], "depends_on": []},
            {"batch_id": "b", "label": "B", "tasks": [], "depends_on": ["a"]},
        ])
        assert order.index("a") < order.index("b")
        assert order.index("a") < order.index("c")
        assert order.index("b") < order.index("c")

    def test_validate_dag_valid(self):
        planner = TaskPlanner()
        assert planner.validate_dag([
            {"batch_id": "a", "depends_on": []},
            {"batch_id": "b", "depends_on": ["a"]},
        ]) is True

    def test_validate_dag_cycle(self):
        planner = TaskPlanner()
        assert planner.validate_dag([
            {"batch_id": "a", "depends_on": ["b"]},
            {"batch_id": "b", "depends_on": ["a"]},
        ]) is False


# ─── BatchReviewer ───────────────────────────────────────────────────

class TestBatchReviewer:
    def _make_state(self, fan_in="all_success"):
        return create_workflow("wf", "Test", [
            {"batch_id": "b0", "label": "S0", "tasks": [
                {"task_id": "t1", "label": "T1"},
                {"task_id": "t2", "label": "T2"},
            ], "depends_on": [], "fan_in_policy": fan_in},
            {"batch_id": "b1", "label": "S1", "tasks": [
                {"task_id": "t3", "label": "T3"},
            ], "depends_on": ["b0"]},
        ])

    def test_all_success_proceed(self):
        state = self._make_state()
        for t in state.batches[0].tasks:
            t.status = "completed"
            t.result_summary = "ok"
        state.batches[0].status = "completed"
        dec = BatchReviewer().review(state.batches[0], state)
        assert dec.decision == "proceed"
        assert dec.next_batch == "b1"

    def test_all_success_with_failure_stops(self):
        state = self._make_state()
        state.batches[0].tasks[0].status = "completed"
        state.batches[0].tasks[1].status = "failed"
        state.batches[0].status = "completed"
        dec = BatchReviewer().review(state.batches[0], state)
        assert dec.decision == "stop"

    def test_any_success_with_one_fail(self):
        state = self._make_state("any_success")
        state.batches[0].tasks[0].status = "completed"
        state.batches[0].tasks[0].result_summary = "ok"
        state.batches[0].tasks[1].status = "failed"
        state.batches[0].status = "completed"
        dec = BatchReviewer().review(state.batches[0], state)
        assert dec.decision == "proceed"

    def test_majority_success(self):
        state = create_workflow("wf", "Test", [
            {"batch_id": "b0", "label": "S0", "tasks": [
                {"task_id": "t1", "label": "T1"},
                {"task_id": "t2", "label": "T2"},
                {"task_id": "t3", "label": "T3"},
            ], "depends_on": [], "fan_in_policy": "majority"},
        ])
        state.batches[0].tasks[0].status = "completed"
        state.batches[0].tasks[0].result_summary = "ok"
        state.batches[0].tasks[1].status = "completed"
        state.batches[0].tasks[1].result_summary = "ok"
        state.batches[0].tasks[2].status = "failed"
        state.batches[0].status = "completed"
        dec = BatchReviewer().review(state.batches[0], state)
        assert dec.decision == "proceed"

    def test_majority_insufficient(self):
        state = self._make_state("majority")
        state.batches[0].tasks[0].status = "completed"
        state.batches[0].tasks[0].result_summary = "ok"
        state.batches[0].tasks[1].status = "failed"
        state.batches[0].status = "completed"
        dec = BatchReviewer().review(state.batches[0], state)
        assert dec.decision == "stop"

    def test_gate_on_needs_review(self):
        state = self._make_state()
        for t in state.batches[0].tasks:
            t.status = "completed"
            t.result_summary = "ok"
        state.batches[0].tasks[0].result_summary = "NEEDS_REVIEW: anomaly"
        state.batches[0].status = "completed"
        dec = BatchReviewer().review(state.batches[0], state)
        assert dec.decision == "gate"

    def test_empty_batch_stops(self):
        state = create_workflow("wf", "Test", [
            {"batch_id": "b0", "label": "S0", "tasks": [], "depends_on": []},
        ])
        state.batches[0].status = "completed"
        dec = BatchReviewer().review(state.batches[0], state)
        assert dec.decision == "stop"

    def test_last_batch_next_is_none(self):
        state = create_workflow("wf", "Test", [
            {"batch_id": "b0", "label": "S0", "tasks": [{"task_id": "t1", "label": "T1"}], "depends_on": []},
        ])
        state.batches[0].tasks[0].status = "completed"
        state.batches[0].tasks[0].result_summary = "ok"
        state.batches[0].status = "completed"
        dec = BatchReviewer().review(state.batches[0], state)
        assert dec.decision == "proceed"
        assert dec.next_batch is None


# ─── LangGraph Integration ──────────────────────────────────────────

class TestWorkflowGraph:
    @pytest.fixture
    def graph(self):
        try:
            from workflow_graph import build_workflow_graph
            return build_workflow_graph()
        except ImportError:
            pytest.skip("langgraph not installed")

    def _completed_state(self, batches_config):
        planner = TaskPlanner()
        state = planner.plan("Test", batches_config)
        state.status = "running"
        for b in state.batches:
            b.status = "completed"
            for t in b.tasks:
                t.status = "completed"
                t.result_summary = "ok"
        return state

    def test_two_batches_proceed(self, graph):
        from workflow_state import WorkflowState
        state = self._completed_state([
            {"batch_id": "b0", "label": "S1", "tasks": [{"task_id": "t1", "label": "T1"}], "depends_on": []},
            {"batch_id": "b1", "label": "S2", "tasks": [{"task_id": "t2", "label": "T2"}], "depends_on": ["b0"]},
        ])
        result = graph.invoke(
            {"workflow": state.to_dict(), "status": "pending"},
            {"configurable": {"thread_id": "test_proceed"}},
        )
        final = WorkflowState.from_dict(result["workflow"])
        assert final.status == "completed"

    def test_three_batches_chain(self, graph):
        from workflow_state import WorkflowState
        state = self._completed_state([
            {"batch_id": "b0", "label": "S1", "tasks": [{"task_id": "t1", "label": "T1"}], "depends_on": []},
            {"batch_id": "b1", "label": "S2", "tasks": [{"task_id": "t2", "label": "T2"}], "depends_on": ["b0"]},
            {"batch_id": "b2", "label": "S3", "tasks": [{"task_id": "t3", "label": "T3"}], "depends_on": ["b1"]},
        ])
        result = graph.invoke(
            {"workflow": state.to_dict(), "status": "pending"},
            {"configurable": {"thread_id": "test_chain"}},
        )
        final = WorkflowState.from_dict(result["workflow"])
        assert final.status == "completed"

    def test_gate_blocks(self, graph):
        from workflow_state import WorkflowState
        state = self._completed_state([
            {"batch_id": "b0", "label": "S1", "tasks": [{"task_id": "t1", "label": "T1"}], "depends_on": []},
        ])
        state.batches[0].tasks[0].result_summary = "NEEDS_REVIEW: check"
        result = graph.invoke(
            {"workflow": state.to_dict(), "status": "pending"},
            {"configurable": {"thread_id": "test_gate"}},
        )
        final = WorkflowState.from_dict(result["workflow"])
        assert final.status == "gate_blocked"

    def test_failure_stops(self, graph):
        from workflow_state import WorkflowState
        planner = TaskPlanner()
        state = planner.plan("Fail", [
            {"batch_id": "b0", "label": "S1", "tasks": [{"task_id": "t1", "label": "T1"}], "depends_on": []},
        ])
        state.status = "running"
        state.batches[0].status = "completed"
        state.batches[0].tasks[0].status = "failed"
        state.batches[0].tasks[0].error = "timeout"
        result = graph.invoke(
            {"workflow": state.to_dict(), "status": "pending"},
            {"configurable": {"thread_id": "test_fail"}},
        )
        final = WorkflowState.from_dict(result["workflow"])
        assert final.status == "failed"
