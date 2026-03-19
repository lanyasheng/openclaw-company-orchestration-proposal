from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional

from .task_registry import FileTaskRegistry, TERMINAL_STATES


StepHandler = Callable[["StepContext"], "StepOutcome"]


class WorkflowDispatchError(RuntimeError):
    pass


@dataclass
class StepContext:
    workflow: Dict[str, Any]
    step: Dict[str, Any]
    task_id: str
    request: Dict[str, Any]
    signal: Optional[Dict[str, Any]]
    record: Dict[str, Any]
    scheduler: Dict[str, Any]
    step_outputs: Dict[str, Any]


@dataclass
class StepOutcome:
    kind: str
    state: Optional[str] = None
    runtime: Optional[str] = None
    callback_status: Optional[str] = None
    evidence_merge: Dict[str, Any] = field(default_factory=dict)
    step_output: Any = None
    wait_kind: Optional[str] = None
    summary: Optional[str] = None


@dataclass
class DispatchResult:
    task_id: str
    status: str
    record: Dict[str, Any]
    executed_steps: List[str] = field(default_factory=list)
    current_step_id: Optional[str] = None
    waiting_for: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "executed_steps": self.executed_steps,
            "current_step_id": self.current_step_id,
            "waiting_for": self.waiting_for,
            "error": self.error,
            "record": self.record,
        }


class WorkflowDispatcher:
    def __init__(self, registry: FileTaskRegistry, step_handlers: Mapping[str, StepHandler]) -> None:
        self.registry = registry
        self.step_handlers = dict(step_handlers)

    def dispatch(
        self,
        workflow: Mapping[str, Any],
        *,
        task_id: str,
        request: Dict[str, Any],
        signal: Optional[Dict[str, Any]] = None,
    ) -> DispatchResult:
        normalized_workflow = self._normalize_workflow(workflow)
        record = self.registry.ensure(
            task_id=task_id,
            owner=normalized_workflow.get("owner", "zoe"),
            runtime="lobster",
            state="queued",
            evidence={
                "workflow": {
                    "workflow_id": normalized_workflow["workflow_id"],
                    "mode": normalized_workflow.get("mode", "chain-basic"),
                }
            },
            callback_status="pending",
        )
        scheduler = self._ensure_scheduler_state(record, normalized_workflow)
        record = self.registry.patch(task_id, evidence_merge={"scheduler": scheduler})

        if scheduler["cursor"] >= len(normalized_workflow["steps"]):
            return DispatchResult(
                task_id=task_id,
                status=record["state"],
                record=record,
                current_step_id=None,
                waiting_for=None,
            )

        if scheduler.get("waiting_for") and signal is None:
            return DispatchResult(
                task_id=task_id,
                status="waiting",
                record=record,
                current_step_id=scheduler.get("current_step_id"),
                waiting_for=scheduler.get("waiting_for"),
            )

        executed_steps: List[str] = []
        steps = normalized_workflow["steps"]

        while scheduler["cursor"] < len(steps):
            step = steps[scheduler["cursor"]]
            step_id = step["id"]
            scheduler["current_step_id"] = step_id
            scheduler["status"] = "running"
            handler = self.step_handlers.get(step["type"])
            if handler is None:
                raise WorkflowDispatchError(f"未注册的 step handler: {step['type']}")

            context = StepContext(
                workflow=normalized_workflow,
                step=step,
                task_id=task_id,
                request=request,
                signal=signal,
                record=record,
                scheduler=scheduler,
                step_outputs=dict(scheduler.get("outputs", {})),
            )

            try:
                outcome = handler(context)
            except Exception as exc:  # noqa: BLE001 - 这里需要把失败收敛进 registry
                scheduler["status"] = "failed"
                scheduler["timeline"].append(
                    {
                        "step_id": step_id,
                        "event": "failed",
                        "at": _now_iso(),
                        "summary": str(exc),
                    }
                )
                scheduler["steps"][step_id] = {
                    "status": "failed",
                    "last_updated_at": _now_iso(),
                    "summary": str(exc),
                }
                record = self.registry.patch(
                    task_id,
                    state="failed",
                    runtime="lobster",
                    evidence_merge={
                        "scheduler": scheduler,
                        "failure": {
                            "failed_step": step_id,
                            "error": str(exc),
                        },
                    },
                )
                return DispatchResult(
                    task_id=task_id,
                    status="failed",
                    record=record,
                    executed_steps=executed_steps,
                    current_step_id=step_id,
                    error=str(exc),
                )

            executed_steps.append(step_id)
            if outcome.step_output is not None:
                scheduler.setdefault("outputs", {})[step_id] = outcome.step_output
            scheduler.setdefault("steps", {})[step_id] = {
                "status": "waiting" if outcome.kind == "waiting" else "completed",
                "last_updated_at": _now_iso(),
                "summary": outcome.summary,
            }
            if outcome.step_output is not None:
                scheduler["steps"][step_id]["output_ref"] = f"evidence.scheduler.outputs.{step_id}"

            scheduler["timeline"].append(
                {
                    "step_id": step_id,
                    "event": outcome.kind,
                    "at": _now_iso(),
                    "summary": outcome.summary,
                    "wait_kind": outcome.wait_kind,
                }
            )

            if outcome.kind == "waiting":
                waiting_for = {
                    "step_id": step_id,
                    "kind": outcome.wait_kind or "external",
                }
                scheduler["status"] = "waiting"
                scheduler["waiting_for"] = waiting_for
                wait_state = outcome.state or ("waiting_human" if outcome.wait_kind == "human" else "running")
                wait_runtime = outcome.runtime or ("human" if outcome.wait_kind == "human" else "subagent")
                record = self.registry.patch(
                    task_id,
                    state=wait_state,
                    runtime=wait_runtime,
                    evidence_merge=self._build_evidence_merge(scheduler, outcome),
                    callback_status=outcome.callback_status,
                )
                return DispatchResult(
                    task_id=task_id,
                    status="waiting",
                    record=record,
                    executed_steps=executed_steps,
                    current_step_id=step_id,
                    waiting_for=waiting_for,
                )

            scheduler["cursor"] += 1
            scheduler["waiting_for"] = None
            scheduler["current_step_id"] = None

            next_state = outcome.state or record["state"]
            if scheduler["cursor"] < len(steps) and next_state not in TERMINAL_STATES:
                next_state = outcome.state or "running"
            next_runtime = outcome.runtime or "lobster"
            scheduler["status"] = next_state if next_state in TERMINAL_STATES else "running"

            record = self.registry.patch(
                task_id,
                state=next_state,
                runtime=next_runtime,
                evidence_merge=self._build_evidence_merge(scheduler, outcome),
                callback_status=outcome.callback_status,
            )

        final_status = record["state"] if record["state"] in TERMINAL_STATES else "completed"
        if record["state"] != final_status:
            scheduler["status"] = final_status
            record = self.registry.patch(task_id, state=final_status, evidence_merge={"scheduler": scheduler})
        return DispatchResult(
            task_id=task_id,
            status=final_status,
            record=record,
            executed_steps=executed_steps,
            current_step_id=None,
            waiting_for=None,
        )

    def _normalize_workflow(self, workflow: Mapping[str, Any]) -> Dict[str, Any]:
        workflow_id = str(workflow.get("workflow_id") or workflow.get("id") or "").strip()
        if not workflow_id:
            raise WorkflowDispatchError("workflow_id 不能为空")
        raw_steps = workflow.get("steps")
        if not isinstance(raw_steps, list) or not raw_steps:
            raise WorkflowDispatchError("workflow.steps 必须是非空列表")

        seen_ids = set()
        steps: List[Dict[str, Any]] = []
        for raw_step in raw_steps:
            if not isinstance(raw_step, Mapping):
                raise WorkflowDispatchError("workflow step 必须是 object")
            step_id = str(raw_step.get("id") or "").strip()
            step_type = str(raw_step.get("type") or "").strip()
            if not step_id or not step_type:
                raise WorkflowDispatchError("每个 step 都必须有 id 和 type")
            if step_id in seen_ids:
                raise WorkflowDispatchError(f"step id 重复: {step_id}")
            seen_ids.add(step_id)
            steps.append(dict(raw_step))

        normalized = dict(workflow)
        normalized["workflow_id"] = workflow_id
        normalized["steps"] = steps
        return normalized

    def _ensure_scheduler_state(self, record: Dict[str, Any], workflow: Dict[str, Any]) -> Dict[str, Any]:
        evidence = record.get("evidence", {})
        if not isinstance(evidence, dict):
            raise WorkflowDispatchError("scheduler 只支持 object evidence")
        scheduler = evidence.get("scheduler")
        if isinstance(scheduler, dict) and scheduler.get("workflow_id") == workflow["workflow_id"]:
            scheduler.setdefault("cursor", 0)
            scheduler.setdefault("status", "queued")
            scheduler.setdefault("current_step_id", None)
            scheduler.setdefault("waiting_for", None)
            scheduler.setdefault("steps", {})
            scheduler.setdefault("outputs", {})
            scheduler.setdefault("timeline", [])
            return scheduler
        return {
            "workflow_id": workflow["workflow_id"],
            "mode": workflow.get("mode", "chain-basic"),
            "cursor": 0,
            "status": "queued",
            "current_step_id": None,
            "waiting_for": None,
            "steps": {},
            "outputs": {},
            "timeline": [],
        }

    def _build_evidence_merge(self, scheduler: Dict[str, Any], outcome: StepOutcome) -> Dict[str, Any]:
        evidence_merge = dict(outcome.evidence_merge)
        evidence_merge["scheduler"] = scheduler
        return evidence_merge


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
