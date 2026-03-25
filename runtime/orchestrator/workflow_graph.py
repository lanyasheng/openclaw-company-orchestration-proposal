"""LangGraph-based workflow orchestration.

Replaces the polling-based WorkflowLoop with a LangGraph StateGraph that
provides automatic checkpointing, conditional routing, and interrupt/resume.

Graph structure:

    __start__ → check_batch → dispatch → monitor → review → advance
                     ↑                                         │
                     └─────────────────────────────────────────┘
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

try:
    from langgraph.checkpoint.sqlite import SqliteSaver
    _HAS_SQLITE_SAVER = True
except ImportError:
    _HAS_SQLITE_SAVER = False

from workflow_state import (
    WorkflowState,
    dependencies_met,
    get_current_batch,
    get_next_batch,
    save_workflow_state,
    update_context_summary,
    load_workflow_state,
)
from batch_executor import BatchExecutor
from batch_reviewer import BatchReviewer

__all__ = [
    "build_workflow_graph",
    "run_workflow",
    "resume_workflow",
    "GraphState",
]

logger = logging.getLogger(__name__)


class GraphState(TypedDict, total=False):
    workflow: Dict[str, Any]
    state_path: Optional[str]
    workspace_dir: str
    timeout_seconds: int
    status: str


def _load_state(gs: GraphState) -> WorkflowState:
    return WorkflowState.from_dict(gs["workflow"])


def _persist(gs: GraphState, state: WorkflowState) -> Dict[str, Any]:
    update_context_summary(state)
    updates: Dict[str, Any] = {"workflow": state.to_dict()}
    path = gs.get("state_path")
    if path:
        save_workflow_state(state, path)
    return updates


def node_check_batch(gs: GraphState) -> Dict[str, Any]:
    state = _load_state(gs)
    batch = get_current_batch(state)

    if batch is None:
        state.status = "completed"
        result = _persist(gs, state)
        result["status"] = "completed"
        return result

    if batch.status == "pending":
        if not dependencies_met(state, batch):
            result = _persist(gs, state)
            result["status"] = "blocked_dependency"
            return result
        result = _persist(gs, state)
        result["status"] = "ready_to_dispatch"
        return result

    if batch.status == "running":
        result = _persist(gs, state)
        result["status"] = "monitoring"
        return result

    if batch.status in ("completed", "failed"):
        result = _persist(gs, state)
        result["status"] = "ready_to_review"
        return result

    result = _persist(gs, state)
    result["status"] = "ready_to_dispatch"
    return result


def node_dispatch(gs: GraphState) -> Dict[str, Any]:
    state = _load_state(gs)
    batch = get_current_batch(state)
    if batch is None or batch.status != "pending":
        return {"status": "monitoring"}

    workspace = gs.get("workspace_dir", ".")
    timeout = gs.get("timeout_seconds", 900)
    executor = BatchExecutor(workspace, timeout)
    state.status = "running"
    executor.execute_batch(batch, state)
    logger.info("dispatched batch %s (%d tasks)", batch.batch_id, len(batch.tasks))
    result = _persist(gs, state)
    result["status"] = "monitoring"
    return result


def node_monitor(gs: GraphState) -> Dict[str, Any]:
    state = _load_state(gs)
    batch = get_current_batch(state)
    if batch is None or batch.status != "running":
        return {"status": "ready_to_review"}

    workspace = gs.get("workspace_dir", ".")
    timeout = gs.get("timeout_seconds", 900)
    executor = BatchExecutor(workspace, timeout)
    completed = executor.monitor_batch(batch)

    result = _persist(gs, state)
    result["status"] = "ready_to_review" if completed else "monitoring"
    return result


def node_review(gs: GraphState) -> Dict[str, Any]:
    state = _load_state(gs)
    batch = get_current_batch(state)
    if batch is None:
        result = _persist(gs, state)
        result["status"] = "completed"
        return result

    reviewer = BatchReviewer()
    decision = reviewer.review(batch, state)
    batch.continuation = decision
    logger.info("batch %s: %s (%s)", batch.batch_id, decision.decision, decision.stopped_because)
    result = _persist(gs, state)
    result["status"] = f"reviewed_{decision.decision}"
    return result


def node_advance(gs: GraphState) -> Dict[str, Any]:
    state = _load_state(gs)
    batch = get_current_batch(state)
    if batch is None or batch.continuation is None:
        state.status = "completed"
        result = _persist(gs, state)
        result["status"] = "completed"
        return result

    decision = batch.continuation.decision

    if decision == "proceed":
        next_b = get_next_batch(state)
        if next_b is None:
            state.status = "completed"
            result = _persist(gs, state)
            result["status"] = "completed"
            return result
        state.plan["current_batch_index"] = state.plan.get("current_batch_index", 0) + 1
        result = _persist(gs, state)
        result["status"] = "next_batch"
        return result

    if decision == "gate":
        state.status = "gate_blocked"
        result = _persist(gs, state)
        result["status"] = "gate_blocked"
        return result

    state.status = "failed"
    result = _persist(gs, state)
    result["status"] = "failed"
    return result


def _route_after_check(gs: GraphState) -> str:
    status = gs.get("status", "")
    if status in ("completed", "blocked_dependency"):
        return END
    if status == "ready_to_dispatch":
        return "dispatch"
    if status == "monitoring":
        return "monitor"
    if status == "ready_to_review":
        return "review"
    return END


def _route_after_monitor(gs: GraphState) -> str:
    if gs.get("status") == "monitoring":
        return "monitor"
    return "review"


def _route_after_advance(gs: GraphState) -> str:
    if gs.get("status") == "next_batch":
        return "check_batch"
    return END


def _default_checkpointer(db_path: str | None = None):
    if db_path and _HAS_SQLITE_SAVER:
        return SqliteSaver.from_conn_string(db_path)
    return MemorySaver()


def build_workflow_graph(checkpointer=None, db_path: str | None = None):
    if checkpointer is None:
        checkpointer = _default_checkpointer(db_path)

    graph = StateGraph(GraphState)
    graph.add_node("check_batch", node_check_batch)
    graph.add_node("dispatch", node_dispatch)
    graph.add_node("monitor", node_monitor)
    graph.add_node("review", node_review)
    graph.add_node("advance", node_advance)

    graph.set_entry_point("check_batch")
    graph.add_conditional_edges("check_batch", _route_after_check)
    graph.add_edge("dispatch", "monitor")
    graph.add_conditional_edges("monitor", _route_after_monitor)
    graph.add_edge("review", "advance")
    graph.add_conditional_edges("advance", _route_after_advance)

    return graph.compile(checkpointer=checkpointer)


def run_workflow(
    workflow_state: WorkflowState,
    state_path: str | None = None,
    workspace_dir: str = ".",
    timeout_seconds: int = 900,
    thread_id: str = "default",
    checkpoint_db: str | None = None,
) -> WorkflowState:
    if state_path:
        save_workflow_state(workflow_state, state_path)

    if checkpoint_db is None and state_path:
        checkpoint_db = str(Path(state_path).with_suffix(".checkpoint.db"))

    graph = build_workflow_graph(db_path=checkpoint_db)
    initial: GraphState = {
        "workflow": workflow_state.to_dict(),
        "state_path": state_path,
        "workspace_dir": workspace_dir,
        "timeout_seconds": timeout_seconds,
        "status": "pending",
    }
    config = {"configurable": {"thread_id": thread_id}}
    result = graph.invoke(initial, config=config)
    return WorkflowState.from_dict(result["workflow"])


def resume_workflow(
    state_path: str,
    workspace_dir: str = ".",
    timeout_seconds: int = 900,
    thread_id: str = "default",
) -> WorkflowState:
    ws = load_workflow_state(state_path)
    if ws.status == "gate_blocked":
        ws.status = "running"
    return run_workflow(ws, state_path, workspace_dir, timeout_seconds, thread_id)
