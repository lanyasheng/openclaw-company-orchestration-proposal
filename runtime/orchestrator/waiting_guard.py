#!/usr/bin/env python3
"""Minimal waiting-integrity guard for orchestrator callback paths.

This helper is intentionally small and local to the workspace-side runtime.
It does not try to own heartbeat semantics globally; it only prevents callback/
continuation code from treating obviously dead leaf runs as healthy waiting.

HEARTBEAT BOUNDARY POLICY (P0-2 Batch 2):
- This module is an OBSERVER / SIGNALER, not an ACTOR / OWNER / DECIDER.
- It DETECTS anomalies and PREPARES closeout data, but does NOT directly:
  - Write terminal truth (completed/failed states) without owner context
  - Dispatch next tasks (that's dispatch_planner's responsibility)
  - Override gate decisions (that's roundtable/decision maker's responsibility)
- All state modifications must be initiated by workflow owner, not heartbeat.

See: docs/policies/heartbeat-boundary-policy.md
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from state_machine import TaskState, _iso_now, get_batch_tasks, get_state, update_state

# ========== HEARTBEAT BOUNDARY GUARD (P0-2 Batch 2) ==========
# These flags enforce the heartbeat boundary policy at runtime.
# They prevent heartbeat paths from directly performing owner-level actions.

_HEARTBEAT_BOUNDARY_ENFORCED = True
"""If True, heartbeat paths cannot directly call owner-level functions."""

_ALLOWED_HEARTBEAT_ACTIONS = {
    "detect_anomaly",
    "probe_evidence",
    "prepare_closeout_data",
    "return_anomaly_list",
}
"""Actions that heartbeat IS allowed to perform."""

_DENIED_HEARTBEAT_ACTIONS = {
    "write_terminal_truth_directly",
    "dispatch_next_task",
    "override_gate_decision",
    "write_continuation_contract",
}
"""Actions that heartbeat is NOT allowed to perform."""

NON_TERMINAL_TASK_STATES = {
    TaskState.PENDING.value,
    TaskState.RUNNING.value,
    TaskState.RETRYING.value,
}

TERMINAL_RUN_STATES = {
    "completed",
    "failed",
    "timeout",
    "timed_out",
    "cancelled",
    "canceled",
    "dropped",
    "rejected",
    "closed",
    "exited",
}

FAILED_WAITING_RUN_STATES = TERMINAL_RUN_STATES - {"completed"}
HEARTBEAT_STALE_SECONDS = 600


def reconcile_batch_waiting_anomalies(
    *,
    batch_id: str,
    next_owner: str,
    next_step: str,
    artifact_hint: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Hard-close obviously invalid waiting tasks inside a batch.

    HEARTBEAT BOUNDARY GUARD (P0-2 Batch 2):
    - This function DETECTS anomalies and PREPARES closeout data.
    - It does NOT directly write terminal truth or dispatch next tasks.
    - The caller (workflow owner) is responsible for applying the closeout.
    - next_owner and next_step MUST be provided by the caller, not decided here.
    
    See: docs/policies/heartbeat-boundary-policy.md (Allow List: A1-A7, Deny List: D1-D6)

    Only tasks that still look non-terminal are considered. When a task has
    bound runtime evidence (status file / run dir) and that evidence shows the
    waiter is gone, stale, terminal, or missing, the task is moved to FAILED
    with explicit closeout fields so the batch can stop pretending it is still
    waiting.
    
    Args:
        batch_id: Batch identifier
        next_owner: Workflow owner who will apply the closeout (NOT decided by heartbeat)
        next_step: Next step defined by workflow owner (NOT decided by heartbeat)
        artifact_hint: Optional artifact path hint for completion check
    
    Returns:
        List of anomaly records. Caller decides whether to apply closeout.
    
    Raises:
        ValueError: If called without proper owner context (heartbeat boundary guard)
    """
    # HEARTBEAT BOUNDARY GUARD: Ensure owner context is provided
    if _HEARTBEAT_BOUNDARY_ENFORCED:
        if not next_owner or not next_step:
            raise ValueError(
                "Heartbeat boundary violation: reconcile_batch_waiting_anomalies() "
                "cannot be called without explicit owner context. "
                "Heartbeat is an observer, not an owner. "
                "See: docs/policies/heartbeat-boundary-policy.md"
            )

    anomalies: List[Dict[str, Any]] = []
    for task in get_batch_tasks(batch_id):
        if str(task.get("state") or "") not in NON_TERMINAL_TASK_STATES:
            continue
        anomaly = detect_waiting_task_anomaly(task, artifact_hint=artifact_hint)
        if anomaly is None:
            continue
        closeout = {
            "stopped_because": anomaly["code"],
            "next_step": next_step,
            "next_owner": next_owner,
            "dispatch_readiness": "blocked",
        }
        summary = str(anomaly.get("summary") or anomaly["code"])
        result = {
            "verdict": "FAIL",
            "summary": summary,
            "error": summary,
            "closeout": closeout,
            "waiting_guard": {
                "status": "hard_closed",
                "checked_at": _iso_now(),
                "anomaly_code": anomaly["code"],
                **anomaly,
                "closeout": closeout,
            },
        }
        update_state(task["task_id"], TaskState.FAILED, result=result)
        anomalies.append({
            "task_id": task["task_id"],
            "code": anomaly["code"],
            "summary": summary,
            "closeout": closeout,
        })
    return anomalies


def detect_waiting_task_anomaly(
    task: Mapping[str, Any],
    *,
    artifact_hint: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    state = str(task.get("state") or "").strip().lower()
    if state not in NON_TERMINAL_TASK_STATES:
        return None

    status_probe = _probe_status_evidence(task)
    if status_probe is None:
        return None
    if status_probe.get("missing"):
        checked_paths = status_probe.get("checked_paths") or []
        return {
            "code": "subagent_waiting_without_status_artifact",
            "summary": "waiting task has no readable runtime status artifact, so waiting can no longer be trusted",
            "checked_paths": checked_paths,
        }

    callback_status = status_probe.get("callback_status") or {}
    runner_status = status_probe.get("runner_status") or {}
    observed_state = _normalize_state(
        runner_status.get("state")
        or callback_status.get("state")
    )
    active_task_count = _coerce_optional_int(
        _first_non_empty(
            runner_status.get("active_task_count"),
            callback_status.get("active_task_count"),
        )
    )
    if active_task_count is not None and active_task_count <= 0:
        return {
            "code": "subagent_waiting_without_active_execution",
            "summary": f"waiting task reports active_task_count={active_task_count}, so there is no active execution left to wait on",
            "active_task_count": active_task_count,
            **_status_evidence_payload(status_probe, observed_state),
        }

    if observed_state in FAILED_WAITING_RUN_STATES:
        return {
            "code": f"subagent_waiting_after_{observed_state}",
            "summary": f"waiting task runtime already moved to terminal failure state={observed_state}",
            **_status_evidence_payload(status_probe, observed_state),
        }

    if observed_state == "completed":
        artifact_exists = _has_completion_artifact(callback_status, status_probe.get("base_dir"), artifact_hint)
        if artifact_exists:
            summary = "waiting task runtime already completed, but callback/closeout did not consume the terminal artifact"
            code = "subagent_waiting_after_completed"
        else:
            summary = "waiting task runtime is terminal but no completion artifact is available"
            code = "subagent_waiting_without_artifact"
        return {
            "code": code,
            "summary": summary,
            **_status_evidence_payload(status_probe, observed_state),
        }

    last_heartbeat_at = _first_non_empty(
        runner_status.get("lastHeartbeatAt"),
        runner_status.get("last_heartbeat_at"),
        callback_status.get("lastHeartbeatAt"),
        callback_status.get("last_heartbeat_at"),
    )
    if not last_heartbeat_at:
        return {
            "code": "subagent_waiting_without_heartbeat",
            "summary": "waiting task has no heartbeat evidence in runtime status, so active waiting cannot be verified",
            **_status_evidence_payload(status_probe, observed_state),
        }

    heartbeat_age_seconds = _seconds_since(last_heartbeat_at)
    if heartbeat_age_seconds is not None and heartbeat_age_seconds > HEARTBEAT_STALE_SECONDS:
        return {
            "code": "subagent_waiting_without_heartbeat",
            "summary": f"waiting task heartbeat is stale ({heartbeat_age_seconds}s > {HEARTBEAT_STALE_SECONDS}s)",
            "heartbeat_age_seconds": heartbeat_age_seconds,
            **_status_evidence_payload(status_probe, observed_state),
        }

    return None


def _probe_status_evidence(task: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    metadata = task.get("metadata") if isinstance(task.get("metadata"), Mapping) else {}
    candidate_paths = _candidate_status_paths(metadata)
    if not candidate_paths:
        return None

    callback_path = None
    runner_path = None
    callback_status = None
    runner_status = None

    for path in candidate_paths:
        if not path.exists() or not path.is_file():
            continue
        payload = _load_json(path)
        if payload is None:
            continue
        if path.name == "status.json":
            runner_path = runner_path or path
            runner_status = runner_status or payload
        else:
            callback_path = callback_path or path
            callback_status = callback_status or payload

    base_dir = None
    for raw_path in [runner_path, callback_path]:
        if raw_path is None:
            continue
        base_dir = raw_path.parent
        break
    if base_dir is None:
        run_dir = metadata.get("run_dir")
        if run_dir:
            base_dir = Path(str(run_dir)).expanduser().resolve()

    if callback_status is None and runner_status is None:
        return {
            "missing": True,
            "checked_paths": [str(path) for path in candidate_paths],
        }

    return {
        "missing": False,
        "checked_paths": [str(path) for path in candidate_paths],
        "callback_status_path": str(callback_path) if callback_path else None,
        "runner_status_path": str(runner_path) if runner_path else None,
        "callback_status": callback_status or {},
        "runner_status": runner_status or {},
        "base_dir": base_dir,
    }


def _candidate_status_paths(metadata: Mapping[str, Any]) -> List[Path]:
    candidates: List[Path] = []

    def add(raw: Any) -> None:
        if raw in (None, ""):
            return
        path = Path(str(raw)).expanduser()
        if not path.is_absolute():
            path = path.resolve()
        if path not in candidates:
            candidates.append(path)

    run_dir = metadata.get("run_dir")
    if run_dir not in (None, ""):
        run_dir_path = Path(str(run_dir)).expanduser()
        if not run_dir_path.is_absolute():
            run_dir_path = run_dir_path.resolve()
        add(run_dir_path / "status.json")
        add(run_dir_path / "callback-status.json")

    for key in (
        "status_file",
        "status_path",
        "callback_status",
        "callback_status_path",
    ):
        add(metadata.get(key))

    return candidates


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _normalize_state(value: Any) -> str:
    return str(value or "").strip().lower()


def _coerce_optional_int(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _first_non_empty(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def _seconds_since(raw_timestamp: Any) -> Optional[int]:
    if raw_timestamp in (None, ""):
        return None
    try:
        text = str(raw_timestamp).strip().replace("Z", "+00:00")
        seen_at = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    delta = datetime.now(seen_at.tzinfo) - seen_at if seen_at.tzinfo else datetime.now() - seen_at
    return max(int(delta.total_seconds()), 0)


def _status_evidence_payload(status_probe: Mapping[str, Any], observed_state: str) -> Dict[str, Any]:
    callback_status = status_probe.get("callback_status") or {}
    runner_status = status_probe.get("runner_status") or {}
    return {
        "observed_state": observed_state or "unknown",
        "callback_status_path": status_probe.get("callback_status_path"),
        "runner_status_path": status_probe.get("runner_status_path"),
        "checked_paths": status_probe.get("checked_paths") or [],
        "last_heartbeat_at": _first_non_empty(
            runner_status.get("lastHeartbeatAt"),
            runner_status.get("last_heartbeat_at"),
            callback_status.get("lastHeartbeatAt"),
            callback_status.get("last_heartbeat_at"),
        ),
    }


def _has_completion_artifact(
    callback_status: Mapping[str, Any],
    base_dir: Optional[Path],
    artifact_hint: Optional[str],
) -> bool:
    candidates: List[Any] = []
    if artifact_hint:
        candidates.append(artifact_hint)
    for key in (
        "report_file",
        "launcher_summary_path",
        "final_summary_path",
        "final_report_path",
        "discord_message_file",
    ):
        candidates.append(callback_status.get(key))
    candidates.extend(callback_status.get("artifacts") or [])

    for raw in candidates:
        if raw in (None, ""):
            continue
        path = Path(str(raw)).expanduser()
        if not path.is_absolute() and base_dir is not None:
            path = (base_dir / path).resolve()
        elif not path.is_absolute():
            path = path.resolve()
        if path.exists():
            return True
    return False


# ========== HEARTBEAT BOUNDARY GUARD HELPERS (P0-2 Batch 2) ==========
# These helpers enforce the heartbeat boundary policy at runtime.
# See: docs/policies/heartbeat-boundary-policy.md


def assert_heartbeat_boundary(action: str) -> None:
    """
    Assert that a heartbeat action is within allowed boundaries.
    
    HEARTBEAT BOUNDARY GUARD (P0-2 Batch 2):
    - This function checks if an action is allowed for heartbeat paths.
    - If the action is denied, raises ValueError.
    
    Args:
        action: The action being attempted by heartbeat path
    
    Raises:
        ValueError: If the action is denied for heartbeat paths
    
    Example:
        >>> assert_heartbeat_boundary("detect_anomaly")  # OK
        >>> assert_heartbeat_boundary("write_terminal_truth_directly")  # Raises ValueError
    """
    if not _HEARTBEAT_BOUNDARY_ENFORCED:
        return
    
    if action in _DENIED_HEARTBEAT_ACTIONS:
        raise ValueError(
            f"Heartbeat boundary violation: action '{action}' is denied for heartbeat paths. "
            f"Heartbeat is an observer, not an owner/decider. "
            f"Allowed actions: {_ALLOWED_HEARTBEAT_ACTIONS}. "
            f"Denied actions: {_DENIED_HEARTBEAT_ACTIONS}. "
            f"See: docs/policies/heartbeat-boundary-policy.md"
        )
    
    if action not in _ALLOWED_HEARTBEAT_ACTIONS:
        # Unknown action - warn but don't block (for backward compatibility)
        import warnings
        warnings.warn(
            f"Heartbeat action '{action}' is not in allowed list. "
            f"Consider adding it to _ALLOWED_HEARTBEAT_ACTIONS or using an existing allowed action. "
            f"See: docs/policies/heartbeat-boundary-policy.md"
        )


def heartbeat_may_detect_anomaly() -> bool:
    """
    Check if heartbeat path is allowed to detect anomalies.
    
    Returns:
        True if heartbeat boundary enforcement is enabled (default)
    """
    return _HEARTBEAT_BOUNDARY_ENFORCED


def heartbeat_may_prepare_closeout_data() -> bool:
    """
    Check if heartbeat path is allowed to prepare closeout data.
    
    Returns:
        True if heartbeat boundary enforcement is enabled (default)
    """
    return _HEARTBEAT_BOUNDARY_ENFORCED


def set_heartbeat_boundary_enforcement(enabled: bool) -> None:
    """
    Enable or disable heartbeat boundary enforcement.
    
    WARNING: Only use this for testing or emergency rollback.
    In production, heartbeat boundary enforcement should always be enabled.
    
    Args:
        enabled: True to enforce boundaries, False to disable (NOT RECOMMENDED)
    """
    global _HEARTBEAT_BOUNDARY_ENFORCED
    _HEARTBEAT_BOUNDARY_ENFORCED = enabled
