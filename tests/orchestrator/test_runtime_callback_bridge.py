from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ORCHESTRATOR_DIR = REPO_ROOT / "runtime" / "orchestrator"
SCRIPT_PATH = REPO_ROOT / "runtime" / "scripts" / "orchestrator_callback_bridge.py"
if str(ORCHESTRATOR_DIR) not in sys.path:
    sys.path.insert(0, str(ORCHESTRATOR_DIR))

from contracts import (  # type: ignore
    TASK_TIER_ORCHESTRATED,
    TASK_TIER_TRACKED,
    build_canonical_callback_envelope,
    classify_callback_payload,
    normalize_callback_payload,
    resolve_orchestration_contract,
)
from entry_defaults import build_default_entry_contract  # type: ignore
from state_machine import create_task  # type: ignore


@pytest.fixture()
def isolated_state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    state_dir = tmp_path / "shared-context" / "job-status"
    monkeypatch.setenv("OPENCLAW_STATE_DIR", str(state_dir))
    monkeypatch.setenv("OPENCLAW_ACK_GUARD_DISABLE_DELIVERY", "1")
    return state_dir


@pytest.fixture(autouse=True)
def reload_modules(isolated_state_dir: Path):
    import importlib

    for module_name in [
        "state_machine",
        "batch_aggregator",
        "orchestrator",
        "continuation_backends",
        "contracts",
        "trading_roundtable",
        "channel_roundtable",
    ]:
        if module_name in sys.modules:
            importlib.reload(sys.modules[module_name])

    yield


def _tracked_result(*, conclusion: str, blocker: str, next_step: str) -> dict:
    return {
        "summary": "runtime callback bridge smoke",
        "verdict": "PASS" if conclusion == "PASS" else "FAIL",
        "trading_roundtable": {
            "packet": {
                "packet_version": "trading_phase1_packet_v1",
                "phase_id": "trading_phase1",
                "candidate_id": "rs_canonical_e2e_demo_clean_pass",
                "run_label": "rs_canonical_e2e_demo_clean_pass_tmux_demo_20260320",
                "input_config_path": "workspace-trading/research/v2_portfolio/basket_configs/rs_canonical_e2e_demo.json",
                "generated_at": "2026-03-20T22:00:00+08:00",
                "owner": "trading",
                "overall_gate": conclusion,
                "primary_blocker": blocker,
                "artifact": {
                    "path": "workspace-trading/artifacts/acceptance/2026-03-20/acceptance_harness_rs_canonical_e2e_demo_20260320.json",
                    "exists": True,
                },
                "report": {
                    "path": "workspace-trading/reports/acceptance/2026-03-20/acceptance_harness_rs_canonical_e2e_demo_20260320.md",
                    "exists": True,
                },
                "commit": {
                    "repo": "workspace-trading",
                    "git_commit": "3ea9378",
                },
                "test": {
                    "commands": [
                        "python3 -m pytest tests/v2_portfolio/test_acceptance_harness.py tests/v2_portfolio/test_rs_canonical_validation.py -q"
                    ],
                    "summary": "36 passed in 0.41s",
                },
                "repro": {
                    "commands": [
                        "python3 research/run_acceptance_harness.py --input research/v2_portfolio/basket_configs/rs_canonical_e2e_demo.json",
                        "python3 scripts/run_rs_canonical_e2e_demo.py",
                    ],
                    "notes": "requires canonical config and tracked dataset snapshot",
                },
                "tradability": {
                    "annual_turnover": 1.82,
                    "liquidity_flags": [],
                    "gross_return": 0.21,
                    "net_return": 0.19,
                    "benchmark_return": 0.05,
                    "scenario_verdict": "PASS" if blocker == "none" else "FAIL",
                    "turnover_failure_reasons": [] if blocker == "none" else ["annual_turnover_exceeds_hard_limit"],
                    "liquidity_failure_reasons": [],
                    "net_vs_gross_failure_reasons": [],
                    "summary": "clean pass candidate" if blocker == "none" else "turnover remains the primary blocker",
                },
            },
            "roundtable": {
                "conclusion": conclusion,
                "blocker": blocker,
                "owner": "trading",
                "next_step": next_step,
                "completion_criteria": "phase1 packet v1 exists with artifact/report/commit/test/repro truth paths",
            },
        },
    }


def _orchestrated_result(*, backend_preference: str = "tmux") -> dict:
    payload = _tracked_result(
        conclusion="PASS",
        blocker="none",
        next_step="freeze intake and open the next minimal wiring task",
    )
    payload["orchestration"] = {
        "enabled": True,
        "adapter": "trading_roundtable",
        "scenario": "trading_roundtable_phase1",
        "batch_key": "batch_runtime_callback_contract_auto",
        "owner": "trading",
        "backend_preference": backend_preference,
        "callback_payload_schema": "trading_roundtable.v1.callback",
        "channel": {
            "id": "discord:channel:1483883339701158102",
            "name": "trading-roundtable",
        },
        "session": {
            "requester_session_key": "agent:main:discord:channel:1483883339701158102",
        },
        "metadata": {
            "flow_id": "flow_trading_roundtable_phase1_demo",
        },
    }
    return payload


def _orchestrated_envelope_result() -> dict:
    business_payload = _orchestrated_result()
    orchestration = dict(business_payload["orchestration"])
    return {
        "callback_envelope": build_canonical_callback_envelope(
            adapter="trading_roundtable",
            scenario="trading_roundtable_phase1",
            batch_id="batch_runtime_callback_contract_auto",
            backend_terminal_receipt={
                "receipt_version": "tmux_terminal_receipt.v1",
                "backend": "tmux",
                "terminal_state": "completed",
                "dispatch_readiness": "ready",
            },
            business_callback_payload=business_payload,
            orchestration_contract=orchestration,
            business_payload_source="test:envelope_only",
            callback_payload_schema="trading_roundtable.v1.callback",
            metadata={
                "bridge": "tests/test_runtime_callback_bridge.py",
            },
        )
    }


def test_contract_helper_distinguishes_tracked_and_orchestrated_payloads():
    tracked_payload = _tracked_result(
        conclusion="PASS",
        blocker="none",
        next_step="freeze intake and open the next minimal wiring task",
    )
    orchestrated_payload = _orchestrated_result()

    assert classify_callback_payload(tracked_payload) == TASK_TIER_TRACKED
    assert classify_callback_payload(orchestrated_payload) == TASK_TIER_ORCHESTRATED

    resolved = resolve_orchestration_contract(orchestrated_payload, default_backend="subagent")
    assert resolved["enabled"] is True
    assert resolved["adapter"] == "trading_roundtable"
    assert resolved["scenario"] == "trading_roundtable_phase1"
    assert resolved["batch_key"] == "batch_runtime_callback_contract_auto"
    assert resolved["backend_preference"] == "tmux"
    assert resolved["callback_payload_schema"] == "trading_roundtable.v1.callback"


def test_resolve_orchestration_contract_normalizes_channel_aliases_from_generic_payload():
    payload = {
        "summary": "generic channel callback",
        "orchestration": {
            "enabled": True,
            "adapter": "channel_roundtable",
            "scenario": "product_launch_roundtable",
            "batch_key": "batch_product_launch_roundtable",
            "owner": "content",
            "backend_preference": "tmux",
            "callback_payload_schema": "channel_roundtable.v1.callback",
            "channel": {
                "id": "discord:channel:4242",
                "name": "product-launch-review",
                "topic": "Product Launch Review",
            },
        },
        "generic_roundtable": {
            "packet": {
                "packet_version": "channel_roundtable_v1",
                "scenario": "product_launch_roundtable",
                "channel_id": "discord:channel:4242",
                "channel_name": "product-launch-review",
                "topic": "Product Launch Review",
                "owner": "content",
                "generated_at": "2026-03-22T00:10:00+08:00",
            },
            "roundtable": {
                "conclusion": "PASS",
                "blocker": "none",
                "owner": "content",
                "next_step": "ship the smallest follow-up",
                "completion_criteria": "channel packet exists with minimal truth",
            },
        },
    }

    resolved = resolve_orchestration_contract(payload, default_backend="subagent")

    assert resolved["enabled"] is True
    assert resolved["adapter"] == "channel_roundtable"
    assert resolved["scenario"] == "product_launch_roundtable"
    assert resolved["channel"]["id"] == "discord:channel:4242"
    assert resolved["channel"]["channel_id"] == "discord:channel:4242"
    assert resolved["channel"]["name"] == "product-launch-review"
    assert resolved["channel"]["channel_name"] == "product-launch-review"
    assert resolved["channel"]["topic"] == "Product Launch Review"


def test_contract_helper_normalizes_envelope_only_payload():
    envelope_payload = _orchestrated_envelope_result()

    assert classify_callback_payload(envelope_payload) == TASK_TIER_ORCHESTRATED

    resolved = resolve_orchestration_contract(envelope_payload, default_backend="subagent")
    normalized = normalize_callback_payload(envelope_payload)

    assert resolved["enabled"] is True
    assert resolved["adapter"] == "trading_roundtable"
    assert resolved["scenario"] == "trading_roundtable_phase1"
    assert resolved["callback_payload_schema"] == "trading_roundtable.v1.callback"
    assert normalized["trading_roundtable"]["packet"]["candidate_id"] == "rs_canonical_e2e_demo_clean_pass"
    assert normalized["tmux_terminal_receipt"]["backend"] == "tmux"
    assert normalized["callback_envelope"]["source"]["business_payload_source"] == "test:envelope_only"


def test_runtime_callback_bridge_auto_mode_processes_enabled_contract(isolated_state_dir: Path, tmp_path: Path):
    batch_id = "batch_runtime_callback_contract_auto"
    task_id = "tsk_runtime_callback_contract_auto_001"
    create_task(task_id, batch_id=batch_id)

    payload_path = tmp_path / "payload-contract.json"
    payload_path.write_text(json.dumps(_orchestrated_result(), ensure_ascii=False, indent=2), encoding="utf-8")

    env = {**os.environ, "OPENCLAW_STATE_DIR": str(isolated_state_dir)}
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "complete",
            "--task-id",
            task_id,
            "--payload",
            str(payload_path),
            "--runtime",
            "subagent",
            "--requester-session-key",
            "agent:main:discord:channel:1483883339701158102",
        ],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )

    result = json.loads(proc.stdout)
    assert result["status"] == "processed"
    assert result["dispatch_plan"]["status"] == "triggered"
    assert result["dispatch_plan"]["backend"] == "tmux"
    assert result["contract_resolution"]["task_tier"] == TASK_TIER_ORCHESTRATED
    assert result["contract_resolution"]["batch_key"] == batch_id
    assert result["contract_resolution"]["backend_preference"] == "tmux"
    assert result["dispatch_plan"]["orchestration_contract"]["enabled"] is True
    assert result["ack_guard"]["status"] == "present"
    assert Path(result["ack_result"]["receipt_path"]).exists()


def test_runtime_callback_bridge_auto_mode_processes_envelope_only_contract(isolated_state_dir: Path, tmp_path: Path):
    batch_id = "batch_runtime_callback_contract_auto"
    task_id = "tsk_runtime_callback_contract_auto_envelope_001"
    create_task(task_id, batch_id=batch_id)

    payload_path = tmp_path / "payload-envelope-contract.json"
    payload_path.write_text(json.dumps(_orchestrated_envelope_result(), ensure_ascii=False, indent=2), encoding="utf-8")

    env = {**os.environ, "OPENCLAW_STATE_DIR": str(isolated_state_dir)}
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "complete",
            "--task-id",
            task_id,
            "--payload",
            str(payload_path),
            "--runtime",
            "subagent",
            "--requester-session-key",
            "agent:main:discord:channel:1483883339701158102",
        ],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )

    result = json.loads(proc.stdout)
    assert result["status"] == "processed"
    assert result["contract_resolution"]["source"] in {"envelope:callback_envelope", "explicit:orchestration"}
    assert result["contract_resolution"]["task_tier"] == TASK_TIER_ORCHESTRATED
    assert result["dispatch_plan"]["backend"] == "tmux"
    assert result["ack_guard"]["status"] == "present"


def test_runtime_callback_bridge_current_trading_channel_contract_auto_dispatches_when_gate_passes(
    isolated_state_dir: Path,
    tmp_path: Path,
):
    batch_id = "batch_current_trading_channel_contract_auto"
    task_id = "tsk_current_trading_channel_contract_auto_001"
    create_task(task_id, batch_id=batch_id)

    contract = build_default_entry_contract(
        channel_id="discord:channel:1483138253539250217",
        channel_name="交易策略优化圆桌｜续线｜2026-03-17",
        topic="A 股策略主线修复与盘中监控推进",
        requester_session_key="agent:main:discord:channel:1483138253539250217",
        batch_key=batch_id,
        auto_execute=True,
    )
    payload = _tracked_result(
        conclusion="PASS",
        blocker="none",
        next_step="freeze intake and open the next minimal wiring task",
    )
    payload["orchestration"] = contract["orchestration"]

    payload_path = tmp_path / "payload-current-trading-channel-contract.json"
    payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    registry_dir = tmp_path / "task-registry"
    env = {
        **os.environ,
        "OPENCLAW_STATE_DIR": str(isolated_state_dir),
        "OPENCLAW_REGISTRY_DIR": str(registry_dir),
    }
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "complete",
            "--task-id",
            task_id,
            "--payload",
            str(payload_path),
            "--runtime",
            "subagent",
            "--requester-session-key",
            "agent:main:discord:channel:1483138253539250217",
        ],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )

    result = json.loads(proc.stdout)
    assert result["status"] == "processed"
    assert result["dispatch_plan"]["status"] == "triggered"
    assert result["contract_resolution"]["adapter"] == "trading_roundtable"
    assert result["contract_resolution"]["channel"]["channel_id"] == "discord:channel:1483138253539250217"
    assert Path(result["summary_path"]).exists()
    assert Path(result["decision_path"]).exists()
    assert Path(result["dispatch_path"]).exists()
    assert result["ack_result"]["channel_id"] == "1483138253539250217"
    assert Path(result["ack_result"]["receipt_path"]).exists()

    registry_path = registry_dir / "registry.jsonl"
    assert registry_path.exists()
    registry_lines = [json.loads(line) for line in registry_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    current_entries = [item for item in registry_lines if item.get("batch_id") == batch_id]
    assert current_entries
    assert any(item.get("registration_status") == "registered" for item in current_entries)


def test_runtime_callback_bridge_auto_mode_rejects_payload_without_enabled_contract(isolated_state_dir: Path, tmp_path: Path):
    batch_id = "batch_runtime_callback_contract_missing"
    task_id = "tsk_runtime_callback_contract_missing_001"
    create_task(task_id, batch_id=batch_id)

    payload_path = tmp_path / "payload-tracked.json"
    payload_path.write_text(
        json.dumps(
            _tracked_result(
                conclusion="PASS",
                blocker="none",
                next_step="freeze intake and open the next minimal wiring task",
            ),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    env = {**os.environ, "OPENCLAW_STATE_DIR": str(isolated_state_dir)}
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "complete",
            "--task-id",
            task_id,
            "--payload",
            str(payload_path),
            "--runtime",
            "subagent",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert proc.returncode != 0
    assert "payload is not orchestrated" in proc.stderr
    assert "task_tier=tracked" in proc.stderr


def test_runtime_callback_bridge_processes_trading_payload_and_emits_dispatch(isolated_state_dir: Path, tmp_path: Path):
    batch_id = "batch_runtime_callback_bridge"
    task_id = "tsk_runtime_callback_bridge_001"
    create_task(task_id, batch_id=batch_id)

    payload_path = tmp_path / "payload.json"
    payload_path.write_text(
        json.dumps(
            _tracked_result(
                conclusion="PASS",
                blocker="none",
                next_step="freeze intake and open the next minimal wiring task",
            ),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    env = {**os.environ, "OPENCLAW_STATE_DIR": str(isolated_state_dir)}
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "complete",
            "--adapter",
            "trading_roundtable",
            "--task-id",
            task_id,
            "--batch-id",
            batch_id,
            "--payload",
            str(payload_path),
            "--runtime",
            "subagent",
            "--backend",
            "tmux",
            "--requester-session-key",
            "agent:main:discord:channel:1483883339701158102",
        ],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )

    result = json.loads(proc.stdout)
    assert result["status"] == "processed"
    assert result["dispatch_plan"]["status"] == "triggered"
    assert result["dispatch_plan"]["backend"] == "tmux"
    assert result["dispatch_plan"]["backend_plan"]["backend"] == "tmux"
    assert result["contract_resolution"]["task_tier"] == TASK_TIER_TRACKED
    assert Path(result["summary_path"]).exists()
    assert Path(result["decision_path"]).exists()
    assert Path(result["dispatch_path"]).exists()
    assert result["ack_guard"]["status"] == "present"
    assert result["ack_result"]["ack_status"] == "fallback_recorded"
    assert Path(result["ack_result"]["receipt_path"]).exists()


def test_runtime_callback_bridge_synthesizes_ack_when_handler_omits_it(
    isolated_state_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import importlib.util
    from types import SimpleNamespace

    spec = importlib.util.spec_from_file_location("orchestrator_callback_bridge_test", SCRIPT_PATH)
    assert spec and spec.loader
    bridge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bridge)

    batch_id = "batch_runtime_callback_bridge_missing_ack"
    task_id = "tsk_runtime_callback_bridge_missing_ack_001"
    create_task(task_id, batch_id=batch_id)

    payload_path = tmp_path / "payload-missing-ack.json"
    payload_path.write_text(
        json.dumps(
            _tracked_result(
                conclusion="PASS",
                blocker="none",
                next_step="freeze intake and open the next minimal wiring task",
            ),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    summary_path = tmp_path / "summary.md"
    decision_path = tmp_path / "decision.json"
    dispatch_path = tmp_path / "dispatch.json"
    summary_path.write_text("summary", encoding="utf-8")
    decision_path.write_text("{}", encoding="utf-8")
    dispatch_path.write_text("{}", encoding="utf-8")

    def fake_handler(**_: object) -> dict:
        return {
            "status": "processed",
            "batch_id": batch_id,
            "task_id": task_id,
            "summary_path": str(summary_path),
            "decision_path": str(decision_path),
            "dispatch_path": str(dispatch_path),
            "dispatch_plan": {
                "status": "skipped",
                "reason": "manual confirmation required",
                "backend": "subagent",
            },
        }

    monkeypatch.setattr(bridge, "_adapter_registry", lambda: {"trading_roundtable": fake_handler})

    args = SimpleNamespace(
        adapter="trading_roundtable",
        task_id=task_id,
        batch_id=batch_id,
        payload=str(payload_path),
        runtime="subagent",
        backend="subagent",
        requester_session_key="agent:main:discord:channel:1483883339701158102",
        allow_auto_dispatch="auto",
    )

    result = bridge._handle_complete(args)
    assert result["ack_guard"]["status"] == "synthesized_fallback"
    assert result["ack_result"]["ack_status"] == "fallback_recorded"
    receipt_text = Path(result["ack_result"]["receipt_path"]).read_text()
    assert f"- Summary: `{summary_path}`" in receipt_text
    assert f"- Decision File: `{decision_path}`" in receipt_text
    assert f"- Dispatch Plan: `{dispatch_path}`" in receipt_text
