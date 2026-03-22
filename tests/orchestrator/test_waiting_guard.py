"""Tests for waiting-integrity guard in orchestrator callback paths."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ORCHESTRATOR_DIR = REPO_ROOT / "orchestrator"
if str(ORCHESTRATOR_DIR) not in sys.path:
    sys.path.insert(0, str(ORCHESTRATOR_DIR))

from state_machine import TaskState, create_task, get_state  # type: ignore
from waiting_guard import (  # type: ignore
    HEARTBEAT_STALE_SECONDS,
    detect_waiting_task_anomaly,
    reconcile_batch_waiting_anomalies,
    _candidate_status_paths,
    _has_completion_artifact,
    _probe_status_evidence,
    _seconds_since,
)


@pytest.fixture()
def isolated_state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    state_dir = tmp_path / "shared-context" / "job-status"
    monkeypatch.setenv("OPENCLAW_STATE_DIR", str(state_dir))
    return state_dir


@pytest.fixture(autouse=True)
def reload_modules(isolated_state_dir: Path):
    import importlib

    for module_name in ["state_machine", "waiting_guard"]:
        if module_name in sys.modules:
            importlib.reload(sys.modules[module_name])

    yield


def _create_task_with_metadata(
    task_id: str,
    batch_id: str,
    metadata: Dict[str, Any],
    state: TaskState = TaskState.RUNNING,
) -> Dict[str, Any]:
    task = create_task(task_id, batch_id=batch_id, metadata=metadata)
    if state != TaskState.PENDING:
        from state_machine import update_state  # type: ignore

        update_state(task_id, state)
    return task


def _write_status_file(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


class TestWaitingGuardHelpers:
    def test_seconds_since_with_iso_timestamp(self):
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        past = now - timedelta(seconds=700)
        result = _seconds_since(past.isoformat())
        assert result is not None
        assert result >= 699 and result <= 701

    def test_seconds_since_returns_none_for_invalid(self):
        assert _seconds_since(None) is None
        assert _seconds_since("") is None
        assert _seconds_since("not-a-timestamp") is None

    def test_candidate_status_paths_from_run_dir(self):
        metadata = {"run_dir": "/tmp/test-run-123"}
        candidates = _candidate_status_paths(metadata)
        assert len(candidates) == 2
        assert any("status.json" in str(c) for c in candidates)
        assert any("callback-status.json" in str(c) for c in candidates)

    def test_candidate_status_paths_from_explicit_files(self):
        metadata = {
            "run_dir": "/tmp/test-run",
            "status_file": "/explicit/status.json",
            "callback_status": "/explicit/callback-status.json",
        }
        candidates = _candidate_status_paths(metadata)
        assert len(candidates) >= 2
        paths_str = [str(c) for c in candidates]
        assert "/explicit/status.json" in paths_str
        assert "/explicit/callback-status.json" in paths_str

    def test_has_completion_artifact_from_callback_status(self):
        callback_status = {"report_file": "/tmp/report.md"}
        assert _has_completion_artifact(callback_status, None, None) is False

        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            temp_path = f.name
        try:
            callback_status = {"report_file": temp_path}
            assert _has_completion_artifact(callback_status, None, None) is True
        finally:
            import os

            os.unlink(temp_path)

    def test_has_completion_artifact_from_artifacts_list(self):
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            temp_path = f.name
        try:
            callback_status = {"artifacts": [temp_path, "/nonexistent.md"]}
            assert _has_completion_artifact(callback_status, None, None) is True
        finally:
            import os

            os.unlink(temp_path)


class TestDetectWaitingTaskAnomaly:
    def test_anomaly_when_status_missing(self, isolated_state_dir: Path, tmp_path: Path):
        task = _create_task_with_metadata(
            "tsk_no_status",
            "batch_no_status",
            metadata={"run_dir": str(tmp_path / "nonexistent-run")},
        )
        anomaly = detect_waiting_task_anomaly(task)
        assert anomaly is not None
        assert anomaly["code"] == "subagent_waiting_without_status_artifact"

    def test_anomaly_when_status_missing_but_expected(self, isolated_state_dir: Path, tmp_path: Path):
        status_path = tmp_path / "status.json"
        task = _create_task_with_metadata(
            "tsk_missing_status",
            "batch_missing_status",
            metadata={"status_file": str(status_path)},
        )
        anomaly = detect_waiting_task_anomaly(task)
        assert anomaly is not None
        assert anomaly["code"] == "subagent_waiting_without_status_artifact"
        assert str(status_path) in anomaly["checked_paths"]

    def test_anomaly_active_task_count_zero(self, isolated_state_dir: Path, tmp_path: Path):
        status_path = tmp_path / "status.json"
        _write_status_file(status_path, {"state": "running", "active_task_count": 0})
        task = _create_task_with_metadata(
            "tsk_zero_active",
            "batch_zero_active",
            metadata={"status_file": str(status_path)},
        )
        anomaly = detect_waiting_task_anomaly(task)
        assert anomaly is not None
        assert anomaly["code"] == "subagent_waiting_without_active_execution"
        assert anomaly["active_task_count"] == 0

    def test_anomaly_terminal_failed_state(self, isolated_state_dir: Path, tmp_path: Path):
        status_path = tmp_path / "status.json"
        _write_status_file(status_path, {"state": "failed", "active_task_count": 1})
        task = _create_task_with_metadata(
            "tsk_failed",
            "batch_failed",
            metadata={"status_file": str(status_path)},
        )
        anomaly = detect_waiting_task_anomaly(task)
        assert anomaly is not None
        assert anomaly["code"] == "subagent_waiting_after_failed"

    def test_anomaly_terminal_timeout_state(self, isolated_state_dir: Path, tmp_path: Path):
        status_path = tmp_path / "status.json"
        _write_status_file(status_path, {"state": "timeout", "active_task_count": 1})
        task = _create_task_with_metadata(
            "tsk_timeout",
            "batch_timeout",
            metadata={"status_file": str(status_path)},
        )
        anomaly = detect_waiting_task_anomaly(task)
        assert anomaly is not None
        assert anomaly["code"] == "subagent_waiting_after_timeout"

    def test_anomaly_completed_with_artifact(self, isolated_state_dir: Path, tmp_path: Path):
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            report_path = f.name
        try:
            status_path = tmp_path / "status.json"
            callback_path = tmp_path / "callback-status.json"
            _write_status_file(
                status_path,
                {"state": "completed", "active_task_count": 1},
            )
            _write_status_file(
                callback_path,
                {"state": "completed", "active_task_count": 1, "report_file": report_path},
            )
            task = _create_task_with_metadata(
                "tsk_completed_with_artifact",
                "batch_completed_artifact",
                metadata={"status_file": str(status_path), "callback_status": str(callback_path)},
            )
            anomaly = detect_waiting_task_anomaly(task)
            assert anomaly is not None
            assert anomaly["code"] == "subagent_waiting_after_completed"
            assert "callback did not consume" in anomaly["summary"] or "terminal" in anomaly["summary"]
        finally:
            import os

            os.unlink(report_path)

    def test_anomaly_completed_without_artifact(self, isolated_state_dir: Path, tmp_path: Path):
        status_path = tmp_path / "status.json"
        _write_status_file(status_path, {"state": "completed", "active_task_count": 1})
        task = _create_task_with_metadata(
            "tsk_completed_no_artifact",
            "batch_completed_no_artifact",
            metadata={"status_file": str(status_path)},
        )
        anomaly = detect_waiting_task_anomaly(task)
        assert anomaly is not None
        assert anomaly["code"] == "subagent_waiting_without_artifact"

    def test_anomaly_stale_heartbeat(self, isolated_state_dir: Path, tmp_path: Path):
        from datetime import datetime, timedelta, timezone

        stale_time = datetime.now(timezone.utc) - timedelta(seconds=HEARTBEAT_STALE_SECONDS + 120)
        status_path = tmp_path / "status.json"
        _write_status_file(
            status_path,
            {"state": "running", "active_task_count": 1, "lastHeartbeatAt": stale_time.isoformat()},
        )
        task = _create_task_with_metadata(
            "tsk_stale_heartbeat",
            "batch_stale_heartbeat",
            metadata={"status_file": str(status_path)},
        )
        anomaly = detect_waiting_task_anomaly(task)
        assert anomaly is not None
        assert anomaly["code"] == "subagent_waiting_without_heartbeat"
        assert "stale" in anomaly["summary"]

    def test_no_anomaly_healthy_running_task(self, isolated_state_dir: Path, tmp_path: Path):
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        status_path = tmp_path / "status.json"
        _write_status_file(
            status_path,
            {"state": "running", "active_task_count": 1, "lastHeartbeatAt": now},
        )
        task = _create_task_with_metadata(
            "tsk_healthy",
            "batch_healthy",
            metadata={"status_file": str(status_path)},
        )
        anomaly = detect_waiting_task_anomaly(task)
        assert anomaly is None


class TestReconcileBatchWaitingAnomalies:
    def test_reconcile_hard_closes_anomalous_tasks(self, isolated_state_dir: Path, tmp_path: Path):
        status_path = tmp_path / "status.json"
        _write_status_file(status_path, {"state": "failed", "active_task_count": 1})

        batch_id = "batch_reconcile_test"
        _create_task_with_metadata(
            "tsk_anomalous_001",
            batch_id,
            metadata={"status_file": str(status_path)},
        )
        _create_task_with_metadata(
            "tsk_anomalous_002",
            batch_id,
            metadata={"status_file": str(status_path)},
        )

        anomalies = reconcile_batch_waiting_anomalies(
            batch_id=batch_id,
            next_owner="main",
            next_step="inspect and rerun dropped leaf task",
        )

        assert len(anomalies) == 2
        for anomaly in anomalies:
            assert anomaly["code"] == "subagent_waiting_after_failed"
            assert anomaly["closeout"]["stopped_because"] == "subagent_waiting_after_failed"
            assert anomaly["closeout"]["next_owner"] == "main"
            assert anomaly["closeout"]["dispatch_readiness"] == "blocked"

        for task_id in ["tsk_anomalous_001", "tsk_anomalous_002"]:
            state = get_state(task_id)
            assert state["state"] == TaskState.FAILED.value
            result = state.get("result", {})
            assert result.get("verdict") == "FAIL"
            assert "closeout" in result
            assert "waiting_guard" in result

    def test_reconcile_skips_healthy_tasks(self, isolated_state_dir: Path, tmp_path: Path):
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        status_path = tmp_path / "status.json"
        _write_status_file(
            status_path,
            {"state": "running", "active_task_count": 1, "lastHeartbeatAt": now},
        )

        batch_id = "batch_healthy_test"
        _create_task_with_metadata(
            "tsk_healthy_001",
            batch_id,
            metadata={"status_file": str(status_path)},
        )

        anomalies = reconcile_batch_waiting_anomalies(
            batch_id=batch_id,
            next_owner="main",
            next_step="continue normal operation",
        )

        assert len(anomalies) == 0
        state = get_state("tsk_healthy_001")
        assert state["state"] == TaskState.RUNNING.value

    def test_reconcile_skips_already_terminal_tasks(self, isolated_state_dir: Path, tmp_path: Path):
        batch_id = "batch_terminal_test"
        from state_machine import update_state  # type: ignore

        task = create_task("tsk_already_failed", batch_id=batch_id)
        update_state("tsk_already_failed", TaskState.FAILED, result={"error": "pre-existing failure"})

        anomalies = reconcile_batch_waiting_anomalies(
            batch_id=batch_id,
            next_owner="main",
            next_step="nothing to do",
        )

        assert len(anomalies) == 0
