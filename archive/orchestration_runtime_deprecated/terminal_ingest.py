from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from .task_registry import FileTaskRegistry, load_json_file, write_json_atomic


TERMINAL_TO_REGISTRY_STATE = {
    "completed": "completed",
    "failed": "failed",
    "timeout": "failed",
    "timeout_total": "failed",
    "timeout_stall": "failed",
    "cancelled": "failed",
    "process_exit": "failed",
    "degraded": "degraded",
}


class TerminalIngestError(ValueError):
    pass


class SubagentTerminalIngest:
    def __init__(self, registry: FileTaskRegistry) -> None:
        self.registry = registry
        self.root_dir = registry.root_dir
        self.by_child_session_dir = self.root_dir / "by-child-session"
        self.events_dir = self.root_dir / "events"
        self.waiters_dir = self.root_dir / "waiters"
        self.by_child_session_dir.mkdir(parents=True, exist_ok=True)
        self.events_dir.mkdir(parents=True, exist_ok=True)
        self.waiters_dir.mkdir(parents=True, exist_ok=True)

    def register_child_session(self, task_id: str, child_session_key: str) -> Path:
        path = self.by_child_session_path(child_session_key)
        write_json_atomic(path, {"task_id": task_id, "child_session_key": child_session_key})
        return path

    def by_child_session_path(self, child_session_key: str) -> Path:
        normalized = child_session_key.replace(":", "__").replace("/", "__")
        return self.by_child_session_dir / f"{normalized}.json"

    def waiter_path(self, task_id: str) -> Path:
        return self.waiters_dir / f"{task_id}.terminal.json"

    def event_path(self, task_id: str) -> Path:
        return self.events_dir / f"{task_id}.terminal.json"

    def load_waiter(self, task_id: str) -> Optional[Dict[str, Any]]:
        path = self.waiter_path(task_id)
        if not path.exists():
            return None
        return load_json_file(path)

    def ingest(self, raw_event: Dict[str, Any]) -> Dict[str, Any]:
        task_id = self._resolve_task_id(raw_event)
        child_session_key = self._extract_child_session_key(raw_event)
        terminal_state = self._extract_terminal_state(raw_event)
        registry_state = TERMINAL_TO_REGISTRY_STATE.get(terminal_state, "degraded")
        event_path = self.event_path(task_id)
        normalized = {
            "task_id": task_id,
            "child_session_key": child_session_key,
            "state": registry_state,
            "terminal_state": terminal_state,
            "completed_at": self._first_non_empty(
                raw_event.get("completed_at"),
                raw_event.get("ended_at"),
                raw_event.get("finished_at"),
                raw_event.get("timestamp"),
            ),
            "summary": self._build_summary(raw_event, terminal_state),
            "artifacts": self._extract_artifacts(raw_event),
            "exit_code": raw_event.get("exit_code", raw_event.get("exitCode")),
            "stdout_tail": self._first_non_empty(raw_event.get("stdout_tail"), raw_event.get("stdoutTail")),
            "stderr_tail": self._first_non_empty(raw_event.get("stderr_tail"), raw_event.get("stderrTail")),
            "source": self._first_non_empty(raw_event.get("source"), raw_event.get("event"), "subagent_terminal"),
            "raw_event_ref": str(event_path.relative_to(self.root_dir)),
        }
        write_json_atomic(event_path, {"raw_event": raw_event, "normalized": normalized})
        self.registry.patch(
            task_id,
            state=registry_state,
            runtime="subagent",
            evidence_merge={
                "child_session_key": child_session_key,
                "terminal_state": terminal_state,
                "completed_at": normalized["completed_at"],
                "summary": normalized["summary"],
                "artifacts": normalized["artifacts"],
                "terminal": {
                    "source": normalized["source"],
                    "exit_code": normalized["exit_code"],
                    "stdout_tail": normalized["stdout_tail"],
                    "stderr_tail": normalized["stderr_tail"],
                },
                "raw_event_ref": normalized["raw_event_ref"],
            },
            callback_status="pending",
        )
        write_json_atomic(self.waiter_path(task_id), normalized)
        return normalized

    def _resolve_task_id(self, raw_event: Dict[str, Any]) -> str:
        task_id = raw_event.get("task_id")
        if task_id:
            return str(task_id)
        child_session_key = self._extract_child_session_key(raw_event)
        mapping_path = self.by_child_session_path(child_session_key)
        if not mapping_path.exists():
            raise TerminalIngestError(f"未找到 child_session_key 对应 task_id: {child_session_key}")
        mapping = load_json_file(mapping_path)
        return str(mapping["task_id"])

    def _extract_child_session_key(self, raw_event: Dict[str, Any]) -> str:
        candidates = [
            raw_event.get("child_session_key"),
            raw_event.get("childSessionKey"),
            raw_event.get("session_key"),
            raw_event.get("sessionKey"),
        ]
        session = raw_event.get("session")
        if isinstance(session, dict):
            candidates.extend(
                [
                    session.get("child_session_key"),
                    session.get("childSessionKey"),
                    session.get("key"),
                    session.get("session_key"),
                    session.get("sessionKey"),
                ]
            )
        metadata = raw_event.get("metadata")
        if isinstance(metadata, dict):
            candidates.extend(
                [
                    metadata.get("child_session_key"),
                    metadata.get("session_key"),
                    metadata.get("sessionKey"),
                ]
            )
        value = self._first_non_empty(*candidates)
        if value is None:
            raise TerminalIngestError("terminal event 缺少 child/session key")
        return str(value)

    def _extract_terminal_state(self, raw_event: Dict[str, Any]) -> str:
        state = self._first_non_empty(
            raw_event.get("terminal_state"),
            raw_event.get("terminalState"),
            raw_event.get("state"),
            raw_event.get("status"),
            raw_event.get("final_state"),
            raw_event.get("finalState"),
        )
        if state is None:
            return "degraded"
        return str(state)

    def _build_summary(self, raw_event: Dict[str, Any], terminal_state: str) -> str:
        summary = self._first_non_empty(raw_event.get("summary"), raw_event.get("message"), raw_event.get("note"))
        if summary is not None:
            return str(summary)
        return f"subagent terminal observed: {terminal_state}"

    def _extract_artifacts(self, raw_event: Dict[str, Any]) -> Dict[str, Any]:
        artifacts = raw_event.get("artifacts")
        if isinstance(artifacts, dict):
            merged = dict(artifacts)
        else:
            merged = {}
        inline = {
            "final_summary_path": self._first_non_empty(raw_event.get("final_summary_path"), raw_event.get("finalSummaryPath"), raw_event.get("summary_path")),
            "final_report_path": self._first_non_empty(raw_event.get("final_report_path"), raw_event.get("finalReportPath"), raw_event.get("report_path")),
        }
        for key, value in inline.items():
            if value is not None and key not in merged:
                merged[key] = value
        merged.setdefault("final_summary_path", None)
        merged.setdefault("final_report_path", None)
        return merged

    @staticmethod
    def _first_non_empty(*values: Any) -> Optional[Any]:
        for value in values:
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            return value
        return None
