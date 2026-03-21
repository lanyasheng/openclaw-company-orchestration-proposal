from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

REQUIRED_FIELDS = (
    "task_id",
    "owner",
    "runtime",
    "state",
    "evidence",
    "callback_status",
)
CONTINUATION_FIELDS = (
    "next_step",
    "next_owner",
    "next_backend",
    "auto_continue_if",
    "stop_if",
    "stopped_because",
)
ALLOWED_RUNTIMES = {"lobster", "subagent", "human"}
ALLOWED_STATES = {"queued", "running", "waiting_human", "completed", "failed", "degraded"}
ALLOWED_CALLBACK_STATUSES = {"pending", "sent", "acked", "failed"}
TERMINAL_STATES = {"completed", "failed", "degraded"}


class TaskRegistryError(ValueError):
    pass


def load_json_file(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(path)


def deep_merge(base: Any, patch: Any) -> Any:
    if isinstance(base, dict) and isinstance(patch, dict):
        merged = dict(base)
        for key, value in patch.items():
            if key in merged:
                merged[key] = deep_merge(merged[key], value)
            else:
                merged[key] = value
        return merged
    return patch


def _validate_evidence(evidence: Any) -> None:
    if isinstance(evidence, str):
        if not evidence:
            raise TaskRegistryError("evidence 字符串不能为空")
        return
    if isinstance(evidence, dict):
        return
    raise TaskRegistryError("evidence 只允许 string 或 object")


def _normalize_optional_string(value: Any, *, field_name: str) -> Optional[str]:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    return normalized


def _normalize_condition_list(value: Any, *, field_name: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, list):
        items = value
    else:
        raise TaskRegistryError(f"continuation.{field_name} 必须是 string[] 或 string")

    normalized: list[str] = []
    for item in items:
        text = str(item).strip()
        if text:
            normalized.append(text)
    return normalized


def normalize_continuation_contract(value: Any) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TaskRegistryError("continuation 必须是 object")

    missing = [field for field in CONTINUATION_FIELDS if field not in value]
    if missing:
        raise TaskRegistryError(f"continuation 缺少字段: {', '.join(missing)}")

    stopped_because = _normalize_optional_string(value.get("stopped_because"), field_name="stopped_because")
    if stopped_because is None:
        raise TaskRegistryError("continuation.stopped_because 不能为空")

    return {
        "next_step": _normalize_optional_string(value.get("next_step"), field_name="next_step"),
        "next_owner": _normalize_optional_string(value.get("next_owner"), field_name="next_owner"),
        "next_backend": _normalize_optional_string(value.get("next_backend"), field_name="next_backend"),
        "auto_continue_if": _normalize_condition_list(
            value.get("auto_continue_if"),
            field_name="auto_continue_if",
        ),
        "stop_if": _normalize_condition_list(value.get("stop_if"), field_name="stop_if"),
        "stopped_because": stopped_because,
    }


def build_continuation_contract(
    *,
    next_step: Optional[str],
    next_owner: Optional[str],
    next_backend: Optional[str],
    auto_continue_if: Optional[list[str]] = None,
    stop_if: Optional[list[str]] = None,
    stopped_because: str,
) -> Dict[str, Any]:
    return normalize_continuation_contract(
        {
            "next_step": next_step,
            "next_owner": next_owner,
            "next_backend": next_backend,
            "auto_continue_if": list(auto_continue_if or []),
            "stop_if": list(stop_if or []),
            "stopped_because": stopped_because,
        }
    )


def validate_record(record: Mapping[str, Any]) -> Dict[str, Any]:
    missing = [field for field in REQUIRED_FIELDS if field not in record]
    if missing:
        raise TaskRegistryError(f"缺少必填字段: {', '.join(missing)}")

    task_id = str(record["task_id"])
    owner = str(record["owner"])
    runtime = str(record["runtime"])
    state = str(record["state"])
    callback_status = str(record["callback_status"])
    evidence = record["evidence"]

    if not task_id.startswith("tsk_"):
        raise TaskRegistryError("task_id 必须以 tsk_ 开头")
    if not owner:
        raise TaskRegistryError("owner 不能为空")
    if runtime not in ALLOWED_RUNTIMES:
        raise TaskRegistryError(f"runtime 不合法: {runtime}")
    if state not in ALLOWED_STATES:
        raise TaskRegistryError(f"state 不合法: {state}")
    if callback_status not in ALLOWED_CALLBACK_STATUSES:
        raise TaskRegistryError(f"callback_status 不合法: {callback_status}")
    _validate_evidence(evidence)

    normalized = {
        "task_id": task_id,
        "owner": owner,
        "runtime": runtime,
        "state": state,
        "evidence": evidence,
        "callback_status": callback_status,
    }
    if "continuation" in record and record["continuation"] is not None:
        normalized["continuation"] = normalize_continuation_contract(record["continuation"])
    return normalized


def build_task_record(
    *,
    task_id: str,
    owner: str,
    runtime: str = "lobster",
    state: str = "queued",
    evidence: Optional[Dict[str, Any]] = None,
    callback_status: str = "pending",
    continuation: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "task_id": task_id,
        "owner": owner,
        "runtime": runtime,
        "state": state,
        "evidence": evidence or {},
        "callback_status": callback_status,
    }
    if continuation is not None:
        payload["continuation"] = dict(continuation)
    return validate_record(payload)


class FileTaskRegistry:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir
        self.tasks_dir = self.root_dir / "tasks"
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def task_path(self, task_id: str) -> Path:
        return self.tasks_dir / f"{task_id}.json"

    def exists(self, task_id: str) -> bool:
        return self.task_path(task_id).exists()

    def upsert(self, record: Mapping[str, Any]) -> Dict[str, Any]:
        normalized = validate_record(record)
        with self._lock:
            write_json_atomic(self.task_path(normalized["task_id"]), normalized)
        return normalized

    def load(self, task_id: str) -> Dict[str, Any]:
        path = self.task_path(task_id)
        if not path.exists():
            raise FileNotFoundError(f"task 不存在: {task_id}")
        return validate_record(load_json_file(path))

    def ensure(
        self,
        *,
        task_id: str,
        owner: str,
        runtime: str = "lobster",
        state: str = "queued",
        evidence: Optional[Dict[str, Any]] = None,
        callback_status: str = "pending",
        continuation: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        if self.exists(task_id):
            return self.load(task_id)
        return self.upsert(
            build_task_record(
                task_id=task_id,
                owner=owner,
                runtime=runtime,
                state=state,
                evidence=evidence,
                callback_status=callback_status,
                continuation=continuation,
            )
        )

    def patch(
        self,
        task_id: str,
        *,
        state: Optional[str] = None,
        runtime: Optional[str] = None,
        evidence_merge: Optional[Mapping[str, Any]] = None,
        evidence_replace: Optional[Any] = None,
        callback_status: Optional[str] = None,
        continuation: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            record = self.load(task_id)
            if state is not None:
                record["state"] = state
            if runtime is not None:
                record["runtime"] = runtime
            if evidence_replace is not None:
                record["evidence"] = evidence_replace
            elif evidence_merge is not None:
                current = record.get("evidence", {})
                if not isinstance(current, dict):
                    raise TaskRegistryError("当前 evidence 不是 object，不能做 merge")
                record["evidence"] = deep_merge(current, dict(evidence_merge))
            if callback_status is not None:
                record["callback_status"] = callback_status
            if continuation is not None:
                record["continuation"] = dict(continuation)
            normalized = validate_record(record)
            write_json_atomic(self.task_path(task_id), normalized)
            return normalized
