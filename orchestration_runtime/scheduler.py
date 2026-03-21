from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional

from .context_render import render_context_value
from .task_registry import (
    FileTaskRegistry,
    TERMINAL_STATES,
    build_continuation_contract,
    deep_merge,
    normalize_continuation_contract,
)


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
    registry: FileTaskRegistry
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
    continuation: Optional[Dict[str, Any]] = None


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
            waiting_for = scheduler.get("waiting_for")
            if not self._can_resume_without_signal(task_id, waiting_for):
                anomaly = self._detect_waiting_anomaly(record, scheduler, waiting_for)
                if anomaly is not None:
                    return self._hard_close_waiting_anomaly(
                        task_id=task_id,
                        record=record,
                        scheduler=scheduler,
                        waiting_for=waiting_for,
                        anomaly=anomaly,
                    )
                return DispatchResult(
                    task_id=task_id,
                    status="waiting",
                    record=record,
                    current_step_id=scheduler.get("current_step_id"),
                    waiting_for=waiting_for,
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
                registry=self.registry,
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
                continuation = self._build_failure_continuation(step_id, str(exc))
                evidence_merge = {
                    "scheduler": scheduler,
                    "failure": {
                        "failed_step": step_id,
                        "error": str(exc),
                    },
                }
                evidence_merge = self._attach_closeout_evidence(
                    evidence_merge,
                    record={**record, "state": "failed", "runtime": "lobster"},
                    continuation=continuation,
                )
                record = self.registry.patch(
                    task_id,
                    state="failed",
                    runtime="lobster",
                    evidence_merge=evidence_merge,
                    continuation=continuation,
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
                preview_context = self._build_preview_context(
                    workflow=normalized_workflow,
                    step=step,
                    task_id=task_id,
                    request=request,
                    signal=signal,
                    record=record,
                    scheduler=scheduler,
                    outcome=outcome,
                    next_state=wait_state,
                    next_runtime=wait_runtime,
                    next_callback_status=outcome.callback_status,
                )
                continuation = self._resolve_continuation(preview_context, outcome)
                anomaly = self._detect_waiting_anomaly(preview_context.record, scheduler, waiting_for)
                if anomaly is not None:
                    return self._hard_close_waiting_anomaly(
                        task_id=task_id,
                        record=record,
                        scheduler=scheduler,
                        waiting_for=waiting_for,
                        anomaly=anomaly,
                        executed_steps=executed_steps,
                    )
                evidence_merge = self._attach_closeout_evidence(
                    self._build_evidence_merge(scheduler, outcome),
                    record=preview_context.record,
                    continuation=continuation,
                )
                record = self.registry.patch(
                    task_id,
                    state=wait_state,
                    runtime=wait_runtime,
                    evidence_merge=evidence_merge,
                    callback_status=outcome.callback_status,
                    continuation=continuation,
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

            preview_context = self._build_preview_context(
                workflow=normalized_workflow,
                step=step,
                task_id=task_id,
                request=request,
                signal=signal,
                record=record,
                scheduler=scheduler,
                outcome=outcome,
                next_state=next_state,
                next_runtime=next_runtime,
                next_callback_status=outcome.callback_status,
            )
            continuation = self._resolve_continuation(preview_context, outcome)
            evidence_merge = self._attach_closeout_evidence(
                self._build_evidence_merge(scheduler, outcome),
                record=preview_context.record,
                continuation=continuation,
            )
            record = self.registry.patch(
                task_id,
                state=next_state,
                runtime=next_runtime,
                evidence_merge=evidence_merge,
                callback_status=outcome.callback_status,
                continuation=continuation,
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

    def _can_resume_without_signal(self, task_id: str, waiting_for: Any) -> bool:
        if not isinstance(waiting_for, dict):
            return False
        if waiting_for.get("kind") != "subagent_terminal":
            return False
        try:
            from .terminal_ingest import SubagentTerminalIngest

            return SubagentTerminalIngest(self.registry).load_waiter(task_id) is not None
        except Exception:
            return False

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

    def _attach_closeout_evidence(
        self,
        evidence_merge: Dict[str, Any],
        *,
        record: Dict[str, Any],
        continuation: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        merged = dict(evidence_merge)
        closeout = self._build_closeout_payload(record, continuation)
        if closeout is not None:
            merged["closeout"] = closeout
        return merged

    def _build_closeout_payload(
        self,
        record: Mapping[str, Any],
        continuation: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        if not isinstance(continuation, Mapping):
            return None
        stopped_because = str(continuation.get("stopped_because") or "").strip()
        if not stopped_because:
            return None

        state = str(record.get("state") or "").strip()
        next_owner = continuation.get("next_owner")
        next_backend = continuation.get("next_backend")
        dispatch_readiness = "not_applicable"

        if state == "waiting_human" or next_owner == "human" or next_backend == "human":
            dispatch_readiness = "human_gate"
        elif stopped_because.startswith("waiting_for_"):
            dispatch_readiness = "blocked"
        elif stopped_because == "final_callback_delivery_failed":
            dispatch_readiness = "blocked"
        elif stopped_because.startswith("step_failed:") or state in {"failed", "degraded"}:
            dispatch_readiness = "blocked"
        elif state == "completed":
            dispatch_readiness = "ready" if continuation.get("next_step") else "not_applicable"
        elif state in {"queued", "running"}:
            dispatch_readiness = "blocked"

        return {
            "stopped_because": stopped_because,
            "next_step": continuation.get("next_step"),
            "next_owner": next_owner,
            "dispatch_readiness": dispatch_readiness,
        }

    def _detect_waiting_anomaly(
        self,
        record: Mapping[str, Any],
        scheduler: Mapping[str, Any],
        waiting_for: Any,
    ) -> Optional[Dict[str, Any]]:
        if not isinstance(waiting_for, Mapping):
            return None
        if waiting_for.get("kind") != "subagent_terminal":
            return None

        evidence = record.get("evidence")
        if not isinstance(evidence, Mapping):
            return {
                "code": "subagent_waiting_without_evidence",
                "resolution": "dropped",
                "summary": "waiting_for=subagent_terminal but evidence is missing, so waiting cannot be trusted",
            }

        step_id = str(waiting_for.get("step_id") or scheduler.get("current_step_id") or "await_terminal")
        step_evidence = evidence.get(step_id)
        child_session_key = None
        if isinstance(step_evidence, Mapping):
            raw_child_session_key = step_evidence.get("child_session_key")
            if raw_child_session_key is not None:
                child_session_key = str(raw_child_session_key)
        if child_session_key is None and evidence.get("child_session_key") is not None:
            child_session_key = str(evidence.get("child_session_key"))

        if not child_session_key:
            return {
                "code": "subagent_waiting_without_child_session_key",
                "resolution": "dropped",
                "summary": "waiting_for=subagent_terminal but child_session_key is missing, so there is no bound execution to wait on",
            }

        dispatch_handle = self._find_subagent_dispatch_handle(evidence, child_session_key)
        if dispatch_handle is None:
            return {
                "code": "subagent_waiting_without_dispatch_evidence",
                "resolution": "dropped",
                "summary": f"waiting_for=subagent_terminal for {child_session_key} but no dispatch/run_handle evidence remains",
                "child_session_key": child_session_key,
            }

        run_handle = dispatch_handle.get("run_handle") if isinstance(dispatch_handle.get("run_handle"), Mapping) else {}
        active_task_count = self._coerce_optional_int(
            self._first_non_empty(
                run_handle.get("active_task_count"),
                dispatch_handle.get("active_task_count"),
                self._nested_get(dispatch_handle, "dispatch_evidence", "active_task_count"),
                self._nested_get(dispatch_handle, "dispatch_evidence", "response_excerpt", "active_task_count"),
            )
        )
        if active_task_count is not None and active_task_count <= 0:
            return {
                "code": "subagent_waiting_without_active_execution",
                "resolution": "dropped",
                "summary": f"waiting_for=subagent_terminal for {child_session_key} but active_task_count={active_task_count}",
                "child_session_key": child_session_key,
                "active_task_count": active_task_count,
            }

        run_status = str(
            self._first_non_empty(
                run_handle.get("status"),
                dispatch_handle.get("status"),
                self._nested_get(dispatch_handle, "dispatch_evidence", "response_excerpt", "status"),
            )
            or ""
        ).strip().lower()
        if run_status in {"failed", "timeout", "timed_out", "cancelled", "canceled", "dropped", "rejected", "closed", "exited"}:
            return {
                "code": f"subagent_waiting_after_{run_status}",
                "resolution": "dropped",
                "summary": f"waiting_for=subagent_terminal for {child_session_key} but run_handle.status={run_status}",
                "child_session_key": child_session_key,
                "run_status": run_status,
            }

        return None

    def _hard_close_waiting_anomaly(
        self,
        *,
        task_id: str,
        record: Dict[str, Any],
        scheduler: Dict[str, Any],
        waiting_for: Mapping[str, Any],
        anomaly: Mapping[str, Any],
        executed_steps: Optional[List[str]] = None,
    ) -> DispatchResult:
        step_id = str(waiting_for.get("step_id") or scheduler.get("current_step_id") or "await_terminal")
        summary = str(anomaly.get("summary") or anomaly.get("code") or "waiting anomaly hard-closed")
        scheduler["status"] = "failed"
        scheduler["waiting_for"] = None
        scheduler["current_step_id"] = None
        scheduler.setdefault("timeline", []).append(
            {
                "step_id": step_id,
                "event": "hard_closed",
                "at": _now_iso(),
                "summary": summary,
                "reason_code": anomaly.get("code"),
            }
        )
        scheduler.setdefault("steps", {})[step_id] = {
            "status": str(anomaly.get("resolution") or "dropped"),
            "last_updated_at": _now_iso(),
            "summary": summary,
            "anomaly": dict(anomaly),
        }

        continuation = build_continuation_contract(
            next_step="rerun_subagent_dispatch_with_fresh_session",
            next_owner="main",
            next_backend="manual",
            auto_continue_if=["operator_confirms_rerun"],
            stop_if=["manual_closeout", "accept_missing_artifact"],
            stopped_because=str(anomaly.get("code") or "subagent_waiting_without_active_execution"),
        )
        evidence_merge = {
            "scheduler": scheduler,
            "waiting_anomaly": dict(anomaly),
        }
        preview_record = {**record, "state": "failed", "runtime": "lobster"}
        evidence_merge = self._attach_closeout_evidence(
            evidence_merge,
            record=preview_record,
            continuation=continuation,
        )
        patched = self.registry.patch(
            task_id,
            state="failed",
            runtime="lobster",
            evidence_merge=evidence_merge,
            continuation=continuation,
        )
        return DispatchResult(
            task_id=task_id,
            status="failed",
            record=patched,
            executed_steps=list(executed_steps or []),
            current_step_id=None,
            waiting_for=None,
            error=summary,
        )

    @staticmethod
    def _find_subagent_dispatch_handle(evidence: Mapping[str, Any], child_session_key: str) -> Optional[Dict[str, Any]]:
        top_level_run_handle = evidence.get("run_handle")
        if isinstance(top_level_run_handle, Mapping) and evidence.get("child_session_key") == child_session_key:
            return {
                "child_session_key": child_session_key,
                "run_handle": dict(top_level_run_handle),
            }

        for value in evidence.values():
            if not isinstance(value, Mapping):
                continue
            candidate_child_session_key = value.get("child_session_key")
            if candidate_child_session_key is not None and str(candidate_child_session_key) != child_session_key:
                continue
            if isinstance(value.get("run_handle"), Mapping) or isinstance(value.get("dispatch_evidence"), Mapping):
                return dict(value)
        return None

    @staticmethod
    def _nested_get(value: Any, *path: str) -> Any:
        current = value
        for segment in path:
            if not isinstance(current, Mapping):
                return None
            current = current.get(segment)
        return current

    @staticmethod
    def _first_non_empty(*values: Any) -> Any:
        for value in values:
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            return value
        return None

    @staticmethod
    def _coerce_optional_int(value: Any) -> Optional[int]:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _build_preview_context(
        self,
        *,
        workflow: Dict[str, Any],
        step: Dict[str, Any],
        task_id: str,
        request: Dict[str, Any],
        signal: Optional[Dict[str, Any]],
        record: Dict[str, Any],
        scheduler: Dict[str, Any],
        outcome: StepOutcome,
        next_state: str,
        next_runtime: str,
        next_callback_status: Optional[str],
    ) -> StepContext:
        preview_record = dict(record)
        preview_record["state"] = next_state
        preview_record["runtime"] = next_runtime
        if next_callback_status is not None:
            preview_record["callback_status"] = next_callback_status
        preview_record["evidence"] = deep_merge(record.get("evidence", {}), self._build_evidence_merge(scheduler, outcome))

        preview_outputs = dict(scheduler.get("outputs", {}))
        if outcome.step_output is not None:
            preview_outputs[step["id"]] = outcome.step_output

        return StepContext(
            workflow=workflow,
            step=step,
            task_id=task_id,
            request=request,
            signal=signal,
            record=preview_record,
            registry=self.registry,
            scheduler=scheduler,
            step_outputs=preview_outputs,
        )

    def _resolve_continuation(self, context: StepContext, outcome: StepOutcome) -> Optional[Dict[str, Any]]:
        if outcome.continuation is not None:
            return normalize_continuation_contract(outcome.continuation)

        configured = context.step.get("continuation")
        if isinstance(configured, Mapping):
            rendered = render_context_value(configured, context)
            return normalize_continuation_contract(rendered)

        if outcome.kind == "waiting":
            return self._build_waiting_continuation(context, outcome)

        callback_status = context.record.get("callback_status")
        if callback_status == "failed":
            return build_continuation_contract(
                next_step="retry_final_callback_delivery",
                next_owner="callback_plane",
                next_backend="callback",
                auto_continue_if=["callback_transport_recovered", "manual_retry_requested"],
                stop_if=["manual_abort", "task_cancelled"],
                stopped_because="final_callback_delivery_failed",
            )

        state = context.record.get("state")
        if state == "completed":
            return build_continuation_contract(
                next_step="review_result_and_decide_followup_dispatch",
                next_owner="main",
                next_backend="manual",
                auto_continue_if=[],
                stop_if=["no_follow_up_needed", "manual_closeout"],
                stopped_because="workflow_completed",
            )
        if state == "degraded":
            return build_continuation_contract(
                next_step="review_degraded_result_and_decide_retry_or_fallback",
                next_owner="main",
                next_backend="manual",
                auto_continue_if=["operator_confirms_retry", "operator_confirms_followup_dispatch"],
                stop_if=["manual_closeout", "accept_degraded_outcome"],
                stopped_because="workflow_degraded",
            )
        if state == "failed":
            return build_continuation_contract(
                next_step="triage_failure_and_decide_retry_or_fallback",
                next_owner="main",
                next_backend="manual",
                auto_continue_if=["operator_confirms_retry", "operator_confirms_fallback_dispatch"],
                stop_if=["manual_closeout", "cancel_task"],
                stopped_because="workflow_failed",
            )
        return None

    def _build_waiting_continuation(self, context: StepContext, outcome: StepOutcome) -> Dict[str, Any]:
        wait_kind = outcome.wait_kind or "external"
        if wait_kind == "human":
            return build_continuation_contract(
                next_step=context.step["id"],
                next_owner="human",
                next_backend="human",
                auto_continue_if=["human_decision_received"],
                stop_if=["decision_timeout", "manual_abort"],
                stopped_because="waiting_for_human_decision",
            )
        if wait_kind == "subagent_terminal":
            return build_continuation_contract(
                next_step=context.step["id"],
                next_owner="subagent",
                next_backend="subagent",
                auto_continue_if=["subagent_terminal_received"],
                stop_if=["subagent_timeout", "manual_abort"],
                stopped_because="waiting_for_subagent_terminal",
            )
        return build_continuation_contract(
            next_step=context.step["id"],
            next_owner=context.workflow.get("owner", "main"),
            next_backend="manual",
            auto_continue_if=[f"{wait_kind}_signal_received"],
            stop_if=["manual_abort"],
            stopped_because=f"waiting_for_{wait_kind}",
        )

    @staticmethod
    def _build_failure_continuation(step_id: str, error: str) -> Dict[str, Any]:
        return build_continuation_contract(
            next_step="triage_failure_and_decide_retry_or_fallback",
            next_owner="main",
            next_backend="manual",
            auto_continue_if=["operator_confirms_retry", "operator_confirms_fallback_dispatch"],
            stop_if=["manual_closeout", "cancel_task"],
            stopped_because=f"step_failed:{step_id}:{error}",
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
