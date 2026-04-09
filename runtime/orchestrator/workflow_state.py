from __future__ import annotations

import json
import logging as _logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

class ValidationError(ValueError):
    """Validation error for workflow state data."""
    pass

def validate_required(data: dict, fields: list) -> list:
    """Return list of missing required fields."""
    return [f for f in fields if f not in data or data[f] is None]

def validate_enum_value(value, allowed, field_name="field"):
    """Validate value is in allowed set, raise ValidationError if not."""
    if value not in allowed:
        raise ValidationError(f"{field_name} must be one of {allowed}, got {value!r}")

_log = _logging.getLogger(__name__)

WorkflowStatus = Literal["pending", "running", "completed", "failed", "gate_blocked", "timed_out", "stalled_unrecoverable"]
BatchStatus = Literal["pending", "running", "completed", "failed"]
TaskStatus = Literal["pending", "running", "completed", "failed", "timeout", "timed_out"]
FanInPolicy = Literal["all_success", "any_success", "majority"]
ContinuationAction = Literal["proceed", "gate", "stop"]

__all__ = [
    "WorkflowStatus",
    "BatchStatus",
    "TaskStatus",
    "FanInPolicy",
    "ContinuationAction",
    "ContinuationDecision",
    "TaskEntry",
    "BatchEntry",
    "WorkflowState",
    "load_workflow_state",
    "save_workflow_state",
    "get_current_batch",
    "get_next_batch",
    "dependencies_met",
    "update_context_summary",
    "create_workflow",
]


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ContinuationDecision:
    stopped_because: str
    decision: ContinuationAction
    next_batch: Optional[str]
    decided_at: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stopped_because": self.stopped_because,
            "decision": self.decision,
            "next_batch": self.next_batch,
            "decided_at": self.decided_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ContinuationDecision:
        return cls(
            stopped_because=str(data["stopped_because"]),
            decision=data["decision"],  # type: ignore[arg-type]
            next_batch=data.get("next_batch"),
            decided_at=str(data["decided_at"]),
        )


@dataclass
class TaskEntry:
    task_id: str
    label: str
    executor: str = "subagent"
    status: TaskStatus = "pending"
    result_summary: Optional[str] = None
    subagent_pid: Optional[int] = None
    subagent_task_id: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None
    max_retries: int = 0
    retry_count: int = 0
    callback_result: Optional[Dict[str, Any]] = None
    execution_metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "task_id": self.task_id,
            "label": self.label,
            "executor": self.executor,
            "status": self.status,
            "result_summary": self.result_summary,
            "subagent_pid": self.subagent_pid,
            "subagent_task_id": self.subagent_task_id,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error,
            "max_retries": self.max_retries,
            "retry_count": self.retry_count,
        }
        if self.callback_result:
            d["callback_result"] = self.callback_result
        if self.execution_metadata:
            d["execution_metadata"] = self.execution_metadata
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TaskEntry:
        missing = validate_required(data, ["task_id"])
        if missing:
            raise ValidationError(
                [f"missing required field: {f}" for f in missing],
                source="TaskEntry.from_dict",
            )
        # Warn on missing optional fields that callers usually provide
        soft_missing = validate_required(data, ["label"])
        if soft_missing:
            _log.debug("TaskEntry.from_dict: optional fields missing: %s", soft_missing)
        pid = data.get("subagent_pid")
        return cls(
            task_id=str(data["task_id"]),
            label=str(data.get("label", data["task_id"])),
            executor=str(data.get("executor", "subagent")),
            status=data.get("status", "pending"),  # type: ignore[arg-type]
            result_summary=data.get("result_summary"),
            subagent_pid=int(pid) if pid is not None else None,
            subagent_task_id=data.get("subagent_task_id"),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            error=data.get("error"),
            max_retries=int(data.get("max_retries", 0)),
            retry_count=int(data.get("retry_count", 0)),
            callback_result=data.get("callback_result"),
            execution_metadata=dict(data.get("execution_metadata") or {}),
        )


@dataclass
class BatchEntry:
    batch_id: str
    label: str
    status: BatchStatus = "pending"
    depends_on: List[str] = field(default_factory=list)
    fan_in_policy: FanInPolicy = "all_success"
    tasks: List[TaskEntry] = field(default_factory=list)
    continuation: Optional[ContinuationDecision] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "batch_id": self.batch_id,
            "label": self.label,
            "status": self.status,
            "depends_on": list(self.depends_on),
            "fan_in_policy": self.fan_in_policy,
            "tasks": [t.to_dict() for t in self.tasks],
            "continuation": self.continuation.to_dict() if self.continuation else None,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> BatchEntry:
        missing = validate_required(data, ["batch_id"])
        if missing:
            raise ValidationError(
                [f"missing required field: {f}" for f in missing],
                source="BatchEntry.from_dict",
            )
        cont = data.get("continuation")
        return cls(
            batch_id=str(data["batch_id"]),
            label=str(data.get("label", data["batch_id"])),
            status=data.get("status", "pending"),  # type: ignore[arg-type]
            depends_on=list(data.get("depends_on") or []),
            fan_in_policy=data.get("fan_in_policy", "all_success"),  # type: ignore[arg-type]
            tasks=[TaskEntry.from_dict(t) for t in (data.get("tasks") or [])],
            continuation=ContinuationDecision.from_dict(cont) if cont else None,
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
        )


@dataclass
class WorkflowState:
    workflow_id: str
    status: WorkflowStatus = "pending"
    owner: str = "main"
    created_at: str = field(default_factory=_iso_now)
    updated_at: str = field(default_factory=_iso_now)
    plan: Dict[str, Any] = field(default_factory=dict)
    batches: List[BatchEntry] = field(default_factory=list)
    context_summary: str = ""
    artifact_chain: Dict[str, List[str]] = field(default_factory=dict)
    resume_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "workflow_id": self.workflow_id,
            "status": self.status,
            "owner": self.owner,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "plan": dict(self.plan),
            "batches": [b.to_dict() for b in self.batches],
            "context_summary": self.context_summary,
            "artifact_chain": {k: list(v) for k, v in self.artifact_chain.items()},
        }
        if self.resume_count:
            d["resume_count"] = self.resume_count
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> WorkflowState:
        missing = validate_required(data, ["workflow_id"])
        if missing:
            raise ValidationError(
                [f"missing required field: {f}" for f in missing],
                source="WorkflowState.from_dict",
            )
        ac = data.get("artifact_chain") or {}
        artifact_chain = {str(k): list(v) for k, v in ac.items()}
        return cls(
            workflow_id=str(data["workflow_id"]),
            status=data.get("status", "pending"),  # type: ignore[arg-type]
            owner=str(data.get("owner", "main")),
            created_at=str(data.get("created_at", _iso_now())),
            updated_at=str(data.get("updated_at", _iso_now())),
            plan=dict(data.get("plan") or {}),
            batches=[BatchEntry.from_dict(b) for b in (data.get("batches") or [])],
            context_summary=str(data.get("context_summary", "")),
            artifact_chain=artifact_chain,
            resume_count=int(data.get("resume_count", 0)),
        )


def load_workflow_state(path: str | Path) -> WorkflowState:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(str(p))
    with p.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    return WorkflowState.from_dict(raw)


def save_workflow_state(state: WorkflowState, path: str | Path) -> None:
    p = Path(path)
    state.updated_at = _iso_now()
    payload = state.to_dict()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)


def get_current_batch(state: WorkflowState) -> Optional[BatchEntry]:
    idx = int(state.plan.get("current_batch_index", 0))
    if idx < 0 or idx >= len(state.batches):
        return None
    return state.batches[idx]


def get_next_batch(state: WorkflowState) -> Optional[BatchEntry]:
    idx = int(state.plan.get("current_batch_index", 0)) + 1
    if idx < 0 or idx >= len(state.batches):
        return None
    return state.batches[idx]


def dependencies_met(state: WorkflowState, batch: BatchEntry) -> bool:
    by_id = {b.batch_id: b for b in state.batches}
    for dep in batch.depends_on:
        b = by_id.get(dep)
        if b is None or b.status != "completed":
            return False
    return True


def update_context_summary(state: WorkflowState) -> None:
    desc = str(state.plan.get("description", "")).strip()
    goal = desc if desc else f"workflow {state.workflow_id}"
    lines: List[str] = [f"Goal: {goal}", f"Workflow status: {state.status}", "Batches:"]
    for b in state.batches:
        parts = [f"[{b.batch_id}] {b.label}: {b.status}"]
        for t in b.tasks:
            rs = (t.result_summary or "").strip()
            if rs:
                parts.append(f"  task {t.task_id} ({t.status}): {rs}")
            else:
                parts.append(f"  task {t.task_id}: {t.status}")
        lines.append("\n".join(parts))
    state.context_summary = "\n".join(lines)


def create_workflow(
    workflow_id: str,
    description: str,
    batches_config: List[Dict[str, Any]],
) -> WorkflowState:
    now = _iso_now()
    batches: List[BatchEntry] = []
    for cfg in batches_config:
        tasks_raw = cfg.get("tasks") or []
        task_entries: List[TaskEntry] = []
        for td in tasks_raw:
            task_entries.append(
                TaskEntry(
                    task_id=str(td["task_id"]),
                    label=str(td.get("label", td["task_id"])),
                    executor=str(td.get("executor", "subagent")),
                    status=td.get("status", "pending"),  # type: ignore[arg-type]
                    result_summary=td.get("result_summary"),
                    subagent_pid=td.get("subagent_pid"),
                    started_at=td.get("started_at"),
                    completed_at=td.get("completed_at"),
                    error=td.get("error"),
                )
            )
        batches.append(
            BatchEntry(
                batch_id=str(cfg["batch_id"]),
                label=str(cfg.get("label", cfg["batch_id"])),
                status=cfg.get("status", "pending"),  # type: ignore[arg-type]
                depends_on=list(cfg.get("depends_on") or []),
                fan_in_policy=cfg.get("fan_in_policy", "all_success"),  # type: ignore[arg-type]
                tasks=task_entries,
                continuation=None,
                started_at=cfg.get("started_at"),
                completed_at=cfg.get("completed_at"),
            )
        )
    plan: Dict[str, Any] = {
        "total_batches": len(batches),
        "current_batch_index": 0,
        "description": description,
    }
    return WorkflowState(
        workflow_id=workflow_id,
        status="pending",
        owner="main",
        created_at=now,
        updated_at=now,
        plan=plan,
        batches=batches,
        context_summary="",
        artifact_chain={},
    )
