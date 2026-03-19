from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from orchestration_runtime.task_registry import (
    FileTaskRegistry,
    TERMINAL_STATES,
    load_json_file,
    write_json_atomic,
)


CALLBACK_DEFAULT_SUMMARIES = {
    "final_callback_sent": "final callback sent",
    "callback_receipt_acked": "callback receipt acknowledged",
    "final_callback_failed": "final callback failed",
}
CALLBACK_TRANSITIONS = {
    ("pending", "final_callback_sent"): "sent",
    ("sent", "callback_receipt_acked"): "acked",
    ("pending", "final_callback_failed"): "failed",
}


def dump_json(path: Path, payload: Dict[str, Any]) -> None:
    write_json_atomic(path, payload)



def load_json(path: Path) -> Dict[str, Any]:
    return load_json_file(path)



def child_session_filename(child_session_key: str) -> str:
    return child_session_key.replace(":", "__").replace("/", "__") + ".json"



def terminal_to_registry_state(terminal_state: str) -> str:
    mapping = {
        "completed": "completed",
        "failed": "failed",
        "timeout_total": "failed",
        "timeout_stall": "failed",
        "process_exit": "failed",
        "degraded": "degraded",
    }
    return mapping.get(terminal_state, "degraded")



def next_callback_status(current_status: str, stage: str, state: str) -> str:
    if state not in TERMINAL_STATES:
        raise ValueError(f"callback stage requires terminal task state, got {state}")

    next_status = CALLBACK_TRANSITIONS.get((current_status, stage))
    if next_status is None:
        raise ValueError(f"illegal callback transition: {current_status} --{stage}--> ?")
    return next_status


class SubagentBridgeSimulator:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir
        self.registry = FileTaskRegistry(root_dir / "runtime")
        self.by_child_session_dir = self.registry.root_dir / "by-child-session"
        self.events_dir = self.registry.root_dir / "events"
        self.waiters_dir = self.registry.root_dir / "waiters"
        self.outputs_dir = root_dir / "output"
        self.by_child_session_dir.mkdir(parents=True, exist_ok=True)
        self.events_dir.mkdir(parents=True, exist_ok=True)
        self.waiters_dir.mkdir(parents=True, exist_ok=True)
        self.outputs_dir.mkdir(parents=True, exist_ok=True)
        self._waiter_events: Dict[str, threading.Event] = {}

    def _waiter_event(self, task_id: str) -> threading.Event:
        event = self._waiter_events.get(task_id)
        if event is None:
            event = threading.Event()
            self._waiter_events[task_id] = event
        return event

    def _by_child_session_path(self, child_session_key: str) -> Path:
        return self.by_child_session_dir / child_session_filename(child_session_key)

    def _resolve_task_id(self, raw_event: Dict[str, Any]) -> str:
        task_id = raw_event.get("task_id")
        if task_id:
            return task_id

        child_session_key = raw_event.get("child_session_key")
        if not child_session_key:
            raise KeyError("callback event requires task_id or child_session_key")
        mapping = load_json(self._by_child_session_path(child_session_key))
        return mapping["task_id"]

    def _callback_event_path(self, task_id: str, stage: str) -> Path:
        return self.events_dir / f"{task_id}.{stage}.json"

    def _build_callback_evidence(
        self,
        record: Dict[str, Any],
        normalized: Dict[str, Any],
    ) -> Dict[str, Any]:
        callback_evidence = dict(record.get("evidence", {}).get("callback", {}))
        history = list(callback_evidence.get("history", []))

        history_entry = {
            "stage": normalized["stage"],
            "callback_status": normalized["callback_status"],
            "occurred_at": normalized["occurred_at"],
            "summary": normalized["summary"],
            "raw_event_ref": normalized["raw_event_ref"],
        }
        if normalized.get("delivery") is not None:
            history_entry["delivery"] = normalized["delivery"]
        if normalized.get("receipt") is not None:
            history_entry["receipt"] = normalized["receipt"]
        if normalized.get("error") is not None:
            history_entry["error"] = normalized["error"]
        history.append(history_entry)

        callback_evidence.update(
            {
                "last_stage": normalized["stage"],
                "last_updated_at": normalized["occurred_at"],
                "history": history,
            }
        )
        if normalized.get("delivery") is not None:
            callback_evidence["delivery"] = normalized["delivery"]
        if normalized.get("receipt") is not None:
            callback_evidence["receipt"] = normalized["receipt"]
        if normalized.get("error") is not None:
            callback_evidence["error"] = normalized["error"]
        return callback_evidence

    def subagent_spawn(self, request: Dict[str, Any]) -> Dict[str, Any]:
        task_id = request["task_id"]
        owner = request.get("owner", "lobster")
        workflow = request.get("workflow", "subagent-handoff-basic")
        child_session_key = request.get("simulated_child_session_key", f"agent:main:subagent:{task_id}")
        spawned_at = request.get("spawned_at", "2026-03-19T08:00:00Z")

        self.registry.upsert(
            {
                "task_id": task_id,
                "owner": owner,
                "runtime": "lobster",
                "state": "queued",
                "evidence": {"workflow": workflow},
                "callback_status": "pending",
            }
        )
        registry = self.registry.patch(
            task_id,
            state="running",
            runtime="subagent",
            evidence_merge={
                "workflow": workflow,
                "child_session_key": child_session_key,
                "spawned_at": spawned_at,
                "spawn_request": {
                    "label": request.get("label"),
                    "cwd": request.get("cwd"),
                    "task": request.get("task"),
                    "timeout_ms": request.get("timeout_ms"),
                },
            },
            callback_status="pending",
        )
        dump_json(
            self._by_child_session_path(child_session_key),
            {"task_id": task_id, "child_session_key": child_session_key},
        )
        response = {
            "accepted": True,
            "task_id": task_id,
            "child_session_key": child_session_key,
            "state": registry["state"],
            "callback_status": registry["callback_status"],
        }
        dump_json(self.outputs_dir / "spawn-response.json", response)
        return response

    def ingest_subagent_terminal(self, raw_event: Dict[str, Any]) -> Dict[str, Any]:
        child_session_key = raw_event["child_session_key"]
        mapping = load_json(self._by_child_session_path(child_session_key))
        task_id = mapping["task_id"]
        terminal_state = raw_event.get("terminal_state", raw_event.get("state", "degraded"))
        registry_state = terminal_to_registry_state(terminal_state)
        task_event_path = self.events_dir / f"{task_id}.terminal.json"
        normalized = {
            "task_id": task_id,
            "child_session_key": child_session_key,
            "state": registry_state,
            "terminal_state": terminal_state,
            "completed_at": raw_event.get("completed_at"),
            "summary": raw_event.get("summary", "subagent terminal event received"),
            "artifacts": raw_event.get(
                "artifacts",
                {"final_summary_path": None, "final_report_path": None},
            ),
            "raw_event_ref": str(task_event_path.relative_to(self.root_dir)),
        }
        dump_json(task_event_path, {"raw_event": raw_event, "normalized": normalized})
        self.registry.patch(
            task_id,
            state=registry_state,
            runtime="subagent",
            evidence_merge={
                "terminal_state": terminal_state,
                "completed_at": normalized["completed_at"],
                "summary": normalized["summary"],
                "artifacts": normalized["artifacts"],
                "raw_event_ref": normalized["raw_event_ref"],
            },
            callback_status="pending",
        )
        dump_json(self.waiters_dir / f"{task_id}.terminal.json", normalized)
        dump_json(self.outputs_dir / "terminal-envelope.json", normalized)
        self._waiter_event(task_id).set()
        return normalized

    def ingest_callback_stage(self, raw_event: Dict[str, Any]) -> Dict[str, Any]:
        task_id = self._resolve_task_id(raw_event)
        record = self.registry.load(task_id)
        stage = raw_event["stage"]
        next_status = next_callback_status(record["callback_status"], stage, record["state"])
        callback_event_path = self._callback_event_path(task_id, stage)
        normalized = {
            "task_id": task_id,
            "stage": stage,
            "state": record["state"],
            "previous_callback_status": record["callback_status"],
            "callback_status": next_status,
            "occurred_at": raw_event.get("occurred_at"),
            "summary": raw_event.get("summary", CALLBACK_DEFAULT_SUMMARIES.get(stage, stage)),
            "delivery": raw_event.get("delivery"),
            "receipt": raw_event.get("receipt"),
            "error": raw_event.get("error"),
            "raw_event_ref": str(callback_event_path.relative_to(self.root_dir)),
        }
        dump_json(callback_event_path, {"raw_event": raw_event, "normalized": normalized})
        callback_evidence = self._build_callback_evidence(record, normalized)
        self.registry.patch(
            task_id,
            runtime="subagent",
            evidence_merge={"callback": callback_evidence},
            callback_status=next_status,
        )
        dump_json(self.outputs_dir / f"callback-envelope.{stage}.json", normalized)
        return normalized

    def await_terminal(self, task_id: str, child_session_key: str, timeout_ms: int) -> Dict[str, Any]:
        waiter_path = self.waiters_dir / f"{task_id}.terminal.json"
        if waiter_path.exists():
            envelope = load_json(waiter_path)
            dump_json(self.outputs_dir / "await-terminal.json", envelope)
            return envelope

        self._waiter_event(task_id).wait(timeout_ms / 1000)
        if waiter_path.exists():
            envelope = load_json(waiter_path)
            dump_json(self.outputs_dir / "await-terminal.json", envelope)
            return envelope

        degraded = {
            "task_id": task_id,
            "child_session_key": child_session_key,
            "state": "degraded",
            "terminal_state": "missing",
            "completed_at": None,
            "summary": "await terminal timeout: no terminal event observed",
            "artifacts": {"final_summary_path": None, "final_report_path": None},
            "raw_event_ref": None,
        }
        self.registry.patch(
            task_id,
            state="degraded",
            runtime="subagent",
            evidence_merge={
                "await_timeout": True,
                "failed_at_stage": "await_terminal",
                "summary": degraded["summary"],
                "child_session_key": child_session_key,
            },
            callback_status="pending",
        )
        dump_json(waiter_path, degraded)
        dump_json(self.outputs_dir / "await-terminal.json", degraded)
        return degraded

    def load_registry(self, task_id: str) -> Dict[str, Any]:
        return self.registry.load(task_id)

    def run_simulation(
        self,
        spawn_request: Dict[str, Any],
        terminal_event: Dict[str, Any],
        *,
        callback_events: Optional[List[Dict[str, Any]]] = None,
        await_timeout_ms: int = 1_000,
    ) -> Dict[str, Any]:
        spawn_response = self.subagent_spawn(spawn_request)
        task_id = spawn_response["task_id"]
        child_session_key = spawn_response["child_session_key"]

        awaited: Dict[str, Any] = {}

        def wait_for_terminal() -> None:
            awaited.update(self.await_terminal(task_id, child_session_key, await_timeout_ms))

        waiter_thread = threading.Thread(target=wait_for_terminal, name=f"await-{task_id}")
        waiter_thread.start()
        terminal_envelope = self.ingest_subagent_terminal(terminal_event)
        waiter_thread.join(timeout=max(await_timeout_ms / 1000, 1.0))
        if waiter_thread.is_alive():
            raise RuntimeError("await_terminal 未在 ingest_subagent_terminal 后解阻")

        callback_envelopes: List[Dict[str, Any]] = []
        for raw_event in callback_events or []:
            callback_event = dict(raw_event)
            callback_event.setdefault("task_id", task_id)
            callback_envelopes.append(self.ingest_callback_stage(callback_event))

        if callback_envelopes:
            dump_json(
                self.outputs_dir / "callback-sequence.json",
                {"task_id": task_id, "events": callback_envelopes},
            )

        registry = self.load_registry(task_id)
        dump_json(self.outputs_dir / "registry.patched.json", registry)
        return {
            "spawn_response": spawn_response,
            "await_terminal": awaited,
            "terminal_envelope": terminal_envelope,
            "callback_envelopes": callback_envelopes,
            "registry": registry,
        }
