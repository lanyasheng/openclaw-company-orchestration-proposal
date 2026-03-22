from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ORCHESTRATOR_DIR = REPO_ROOT / "runtime" / "orchestrator"
EXAMPLES_DIR = ORCHESTRATOR_DIR / "examples"
if str(ORCHESTRATOR_DIR) not in sys.path:
    sys.path.insert(0, str(ORCHESTRATOR_DIR))

from orchestrator import Orchestrator, Decision  # type: ignore
from state_machine import create_task, get_state, mark_failed, mark_timeout  # type: ignore
from continuation_backends import decide_watchdog_action  # type: ignore
from trading_roundtable import process_trading_roundtable_callback  # type: ignore
from channel_roundtable import process_channel_roundtable_callback  # type: ignore


@pytest.fixture()
def isolated_state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    state_dir = tmp_path / "shared-context" / "job-status"
    monkeypatch.setenv("OPENCLAW_STATE_DIR", str(state_dir))
    monkeypatch.setenv("OPENCLAW_ACK_GUARD_DISABLE_DELIVERY", "1")
    return state_dir


@pytest.fixture(autouse=True)
def reload_modules(isolated_state_dir: Path):
    import importlib

    for module_name in ["state_machine", "batch_aggregator", "orchestrator", "continuation_backends", "trading_roundtable", "channel_roundtable"]:
        if module_name in sys.modules:
            importlib.reload(sys.modules[module_name])

    yield


def _tracked_result(*, conclusion: str, blocker: str, next_step: str) -> dict:
    return {
        "verdict": "PASS" if conclusion == "PASS" else "FAIL",
        "trading_roundtable": {
            "packet": {
                "packet_version": "trading_phase1_packet_v1",
                "phase_id": "trading_phase1",
                "candidate_id": "rs_canonical_e2e_demo",
                "run_label": "run_2026_03_20_rerun",
                "input_config_path": "workspace-trading/research/v2_portfolio/basket_configs/rs_canonical_e2e_demo.json",
                "generated_at": "2026-03-20T18:00:00+08:00",
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
                    "annual_turnover": 489.5588990351338,
                    "liquidity_flags": [],
                    "gross_return": 0.12,
                    "net_return": 0.12,
                    "benchmark_return": 0.05,
                    "scenario_verdict": "FAIL" if blocker == "tradability" else "PASS",
                    "turnover_failure_reasons": ["annual_turnover_exceeds_hard_limit"] if blocker == "tradability" else [],
                    "liquidity_failure_reasons": [],
                    "net_vs_gross_failure_reasons": [],
                    "summary": "turnover remains the primary blocker" if blocker == "tradability" else "tradability evidence is acceptable",
                },
                "macro": {
                    "enabled": False,
                    "event_state": None,
                    "regime_snapshot_id": None,
                    "fallback": None,
                    "summary": None,
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


def _current_channel_roundtable_result() -> dict:
    return json.loads((EXAMPLES_DIR / "current_channel_temporal_vs_langgraph_payload.json").read_text())


def _non_whitelisted_channel_roundtable_result() -> dict:
    payload = _current_channel_roundtable_result()
    payload["channel_roundtable"]["packet"].update(
        {
            "scenario": "non_whitelisted_architecture_roundtable",
            "channel_id": "discord:channel:999999999999999999",
            "channel_name": "other-architecture-channel",
            "topic": "Other architecture discussion",
        }
    )
    payload["summary"] = "非白名单频道样例。"
    payload["channel_roundtable"]["summary"] = "非白名单频道样例。"
    return payload


def _latest_json(dir_path: Path, prefix: str) -> dict:
    candidates = sorted(dir_path.glob(f"{prefix}*.json"))
    assert candidates, f"no files with prefix {prefix} in {dir_path}"
    return json.loads(candidates[-1].read_text())


def test_generic_orchestrator_dispatch_persists_decision_id(isolated_state_dir: Path):
    batch_id = "batch_generic_trace"
    create_task("tsk_generic_trace_001", batch_id=batch_id)

    orchestrator = Orchestrator()
    orchestrator.register_rule(
        lambda _batch_id, _analysis: Decision(
            action="proceed",
            reason="generic traceability check",
            next_tasks=[{"type": "followup", "task": "continue"}],
        )
    )
    orchestrator.set_dispatch_callback(lambda task: f"tsk_dispatched_{task['type']}")

    dispatch_id = orchestrator.process_batch_callback(
        batch_id=batch_id,
        task_id="tsk_generic_trace_001",
        result={"verdict": "PASS"},
    )

    assert dispatch_id is not None
    dispatch_dir = isolated_state_dir.parent / "orchestrator" / "dispatches"
    dispatch_payload = json.loads((dispatch_dir / f"{dispatch_id}.json").read_text())
    assert dispatch_payload["decision_id"], "dispatch should point back to persisted decision"


def test_channel_roundtable_current_architecture_channel_defaults_to_triggered_auto_dispatch(isolated_state_dir: Path):
    batch_id = "batch_current_channel_temporal_vs_langgraph"
    create_task("tsk_current_channel_architecture_001", batch_id=batch_id)
    create_task("tsk_current_channel_architecture_002", batch_id=batch_id)

    payload = _current_channel_roundtable_result()

    first = process_channel_roundtable_callback(
        batch_id=batch_id,
        task_id="tsk_current_channel_architecture_001",
        result=payload,
    )
    assert first["status"] == "pending"

    final = process_channel_roundtable_callback(
        batch_id=batch_id,
        task_id="tsk_current_channel_architecture_002",
        result=payload,
        requester_session_key="agent:main:discord:channel:1483883339701158102",
    )

    assert final["status"] == "processed"
    assert final["dispatch_plan"]["status"] == "triggered"
    assert "manual confirmation required" not in final["dispatch_plan"]["reason"]
    assert "AUTO_DISPATCH_REQUEST" in final["dispatch_plan"]["parent_message"]

    summary_path = Path(final["summary_path"])
    assert summary_path.exists()
    summary_text = summary_path.read_text()
    assert "Channel Roundtable Continuation Summary" in summary_text
    assert "current_channel_architecture_roundtable" in summary_text
    assert "Temporal vs LangGraph｜OpenClaw 公司级编排架构" in summary_text
    assert "不把 LangGraph 用作 OpenClaw 公司级编排底座" in summary_text
    assert "OpenClaw native + thin orchestration" in summary_text

    decision_payload = json.loads(Path(final["decision_path"]).read_text())
    assert decision_payload["action"] == "proceed"
    assert decision_payload["adapter"] == "channel_roundtable"
    assert decision_payload["metadata"]["scenario"] == "current_channel_architecture_roundtable"
    assert decision_payload["metadata"]["packet_validation"]["complete"] is True
    assert decision_payload["metadata"]["roundtable"]["conclusion"] == "PASS"

    dispatch_payload = json.loads(Path(final["dispatch_path"]).read_text())
    assert dispatch_payload["adapter"] == "channel_roundtable"
    assert dispatch_payload["decision_id"] == decision_payload["decision_id"]
    assert dispatch_payload["recommended_spawn"]["runtime"] == "subagent"
    assert "先在当前频道跑通 summary/decision/dispatch-plan" in dispatch_payload["recommended_spawn"]["task"]
    assert dispatch_payload["safety_gates"]["allow_auto_dispatch"] is True
    assert dispatch_payload["safety_gates"]["auto_dispatch_source"] == "whitelist_default"
    assert dispatch_payload["safety_gates"]["whitelist_match"] is True

    ack_result = final["ack_result"]
    assert ack_result["ack_status"] == "fallback_recorded"
    assert ack_result["delivery_status"] == "skipped"
    receipt_text = Path(ack_result["receipt_path"]).read_text()
    assert "Requester-visible completion trace" in receipt_text
    assert f"- Summary: `{final['summary_path']}`" in receipt_text
    assert f"- Decision File: `{final['decision_path']}`" in receipt_text
    assert f"- Dispatch Plan: `{final['dispatch_path']}`" in receipt_text
    assert "- Next Step: 先在当前频道跑通 summary/decision/dispatch-plan" in receipt_text

    state_one = get_state("tsk_current_channel_architecture_001")
    state_two = get_state("tsk_current_channel_architecture_002")
    assert state_one["state"] == "next_task_dispatched"
    assert state_two["state"] == "next_task_dispatched"


def test_channel_roundtable_non_whitelisted_channel_stays_skipped_by_default(isolated_state_dir: Path):
    batch_id = "batch_other_channel_architecture"
    create_task("tsk_other_channel_architecture_001", batch_id=batch_id)
    create_task("tsk_other_channel_architecture_002", batch_id=batch_id)

    payload = _non_whitelisted_channel_roundtable_result()

    process_channel_roundtable_callback(
        batch_id=batch_id,
        task_id="tsk_other_channel_architecture_001",
        result=payload,
    )
    final = process_channel_roundtable_callback(
        batch_id=batch_id,
        task_id="tsk_other_channel_architecture_002",
        result=payload,
        requester_session_key="agent:main:discord:channel:999999999999999999",
    )

    assert final["status"] == "processed"
    assert final["dispatch_plan"]["status"] == "skipped"
    assert "manual confirmation required" in final["dispatch_plan"]["reason"]
    assert final["dispatch_plan"]["safety_gates"]["allow_auto_dispatch"] is False
    assert final["dispatch_plan"]["safety_gates"]["auto_dispatch_source"] == "default_deny"
    assert final["dispatch_plan"]["safety_gates"]["whitelist_match"] is False

    state_one = get_state("tsk_other_channel_architecture_001")
    state_two = get_state("tsk_other_channel_architecture_002")
    assert state_one["state"] == "final_closed"
    assert state_two["state"] == "final_closed"


def test_channel_roundtable_explicit_false_overrides_whitelist_default(isolated_state_dir: Path):
    batch_id = "batch_current_channel_manual_override"
    create_task("tsk_current_channel_manual_override_001", batch_id=batch_id)

    result = process_channel_roundtable_callback(
        batch_id=batch_id,
        task_id="tsk_current_channel_manual_override_001",
        result=_current_channel_roundtable_result(),
        allow_auto_dispatch=False,
        requester_session_key="agent:main:discord:channel:1483883339701158102",
    )

    assert result["status"] == "processed"
    assert result["dispatch_plan"]["status"] == "skipped"
    assert "manual confirmation required" in result["dispatch_plan"]["reason"]
    assert result["dispatch_plan"]["safety_gates"]["allow_auto_dispatch"] is False
    assert result["dispatch_plan"]["safety_gates"]["auto_dispatch_source"] == "explicit"
    assert result["dispatch_plan"]["safety_gates"]["whitelist_match"] is True

    state_one = get_state("tsk_current_channel_manual_override_001")
    assert state_one["state"] == "final_closed"


def test_trading_roundtable_default_safe_mode_persists_skip_dispatch_plan(isolated_state_dir: Path):
    batch_id = "batch_trading_roundtable_conditional"
    create_task("tsk_roundtable_conditional_001", batch_id=batch_id)
    create_task("tsk_roundtable_conditional_002", batch_id=batch_id)

    first = process_trading_roundtable_callback(
        batch_id=batch_id,
        task_id="tsk_roundtable_conditional_001",
        result=_tracked_result(
            conclusion="CONDITIONAL",
            blocker="tradability",
            next_step="freeze phase1 packet v1 and attach turnover/liquidity/net_vs_gross reasons",
        ),
    )
    assert first["status"] == "pending"

    final = process_trading_roundtable_callback(
        batch_id=batch_id,
        task_id="tsk_roundtable_conditional_002",
        result=_tracked_result(
            conclusion="CONDITIONAL",
            blocker="tradability",
            next_step="freeze phase1 packet v1 and attach turnover/liquidity/net_vs_gross reasons",
        ),
    )

    assert final["status"] == "processed"
    assert final["dispatch_plan"]["status"] == "skipped"
    assert "manual" in final["dispatch_plan"]["reason"].lower() or "not auto-dispatchable" in final["dispatch_plan"]["reason"].lower()

    summary_path = Path(final["summary_path"])
    assert summary_path.exists()
    summary_text = summary_path.read_text()
    assert "Trading Roundtable Continuation Summary" in summary_text
    assert "CONDITIONAL" in summary_text
    assert "tradability" in summary_text
    assert "annual_turnover_exceeds_hard_limit" in summary_text

    decision_path = Path(final["decision_path"])
    decision_payload = json.loads(decision_path.read_text())
    assert decision_payload["action"] == "fix_blocker"
    assert decision_payload["metadata"]["packet_validation"]["complete"] is True
    assert decision_payload["metadata"]["roundtable"]["conclusion"] == "CONDITIONAL"

    dispatch_payload = json.loads(Path(final["dispatch_path"]).read_text())
    assert dispatch_payload["decision_id"] == decision_payload["decision_id"]
    assert dispatch_payload["recommended_spawn"]["runtime"] == "subagent"
    assert "freeze phase1 packet v1" in dispatch_payload["recommended_spawn"]["task"]
    assert dispatch_payload["continuation"]["mode"] == "packet_freeze"
    assert dispatch_payload["safety_gates"]["default_auto_dispatch_eligible"] is False
    assert "decision_fix_blocker_requires_manual_gate" in dispatch_payload["safety_gates"]["default_auto_dispatch_blockers"]

    ack_result = final["ack_result"]
    assert ack_result["ack_status"] == "fallback_recorded"
    assert ack_result["delivery_status"] == "skipped"
    receipt_text = Path(ack_result["receipt_path"]).read_text()
    assert "Delivery Reason: missing_requester_channel_id" in receipt_text
    assert "- Next Step: freeze phase1 packet v1 and attach turnover/liquidity/net_vs_gross reasons" in receipt_text

    state_one = get_state("tsk_roundtable_conditional_001")
    state_two = get_state("tsk_roundtable_conditional_002")
    assert state_one["state"] == "final_closed"
    assert state_two["state"] == "final_closed"


def test_trading_roundtable_clean_pass_defaults_to_triggered_whitelist_auto_dispatch(isolated_state_dir: Path):
    batch_id = "batch_trading_roundtable_pass_whitelist_default"
    create_task("tsk_roundtable_pass_whitelist_default_001", batch_id=batch_id)

    result = process_trading_roundtable_callback(
        batch_id=batch_id,
        task_id="tsk_roundtable_pass_whitelist_default_001",
        result=_tracked_result(
            conclusion="PASS",
            blocker="none",
            next_step="freeze intake and open the next minimal wiring task",
        ),
        requester_session_key="agent:main:discord:channel:123",
    )

    assert result["status"] == "processed"
    assert result["dispatch_plan"]["status"] == "triggered"
    assert result["dispatch_plan"]["continuation"]["mode"] == "advance_phase_handoff"
    assert result["dispatch_plan"]["safety_gates"]["allow_auto_dispatch"] is True
    assert result["dispatch_plan"]["safety_gates"]["auto_dispatch_source"] == "whitelist_default"
    assert result["dispatch_plan"]["safety_gates"]["default_auto_dispatch_eligible"] is True
    assert result["dispatch_plan"]["safety_gates"]["default_auto_dispatch_status"] == "eligible_for_default_whitelist"
    assert result["dispatch_plan"]["skip_reasons"] == []
    assert "AUTO_DISPATCH_REQUEST" in result["dispatch_plan"]["parent_message"]

    criteria = result["dispatch_plan"]["safety_gates"]["default_auto_dispatch_criteria"]
    assert any(item["field"] == "roundtable.conclusion" and item["passed"] is True for item in criteria)
    assert any(item["field"] == "packet.overall_gate" and item["passed"] is True for item in criteria)
    assert any(item["field"] == "packet.tradability.scenario_verdict" and item["passed"] is True for item in criteria)
    assert any(item["field"] == "continuation.mode" and item["actual"] == "advance_phase_handoff" for item in criteria)

    summary_text = Path(result["summary_path"]).read_text()
    assert "Default Auto-Dispatch Readiness" in summary_text
    assert "Eligible Now: yes" in summary_text
    assert "## Default Auto-Dispatch Criteria" in summary_text
    assert "roundtable.conclusion: expected=PASS actual=PASS passed=yes" in summary_text
    assert "continuation.mode: expected=advance_phase_handoff actual=advance_phase_handoff passed=yes" in summary_text

    ack_result = result["ack_result"]
    assert ack_result["ack_status"] == "fallback_recorded"
    assert ack_result["delivery_status"] == "skipped"
    receipt_text = Path(ack_result["receipt_path"]).read_text()
    assert "Requester-visible completion trace" in receipt_text
    assert f"- Summary: `{result['summary_path']}`" in receipt_text
    assert f"- Decision File: `{result['decision_path']}`" in receipt_text
    assert f"- Dispatch Plan: `{result['dispatch_path']}`" in receipt_text
    assert "- Next Step: freeze intake and open the next minimal wiring task" in receipt_text

    state_one = get_state("tsk_roundtable_pass_whitelist_default_001")
    assert state_one["state"] == "next_task_dispatched"


def test_trading_roundtable_timeout_batch_forces_skipped_artifact_rerun_even_with_explicit_allow(isolated_state_dir: Path):
    batch_id = "batch_trading_roundtable_timeout"
    create_task("tsk_roundtable_timeout_001", batch_id=batch_id)
    create_task("tsk_roundtable_timeout_002", batch_id=batch_id)
    mark_timeout("tsk_roundtable_timeout_001")

    result = process_trading_roundtable_callback(
        batch_id=batch_id,
        task_id="tsk_roundtable_timeout_002",
        result=_tracked_result(
            conclusion="PASS",
            blocker="none",
            next_step="freeze intake and open the next minimal wiring task",
        ),
        allow_auto_dispatch=True,
        requester_session_key="agent:main:discord:channel:123",
    )

    assert result["status"] == "processed"
    assert result["dispatch_plan"]["status"] == "skipped"
    assert result["dispatch_plan"]["continuation"]["mode"] == "artifact_rerun"
    assert result["dispatch_plan"]["safety_gates"]["batch_timeout_count"] == 1
    assert "batch_has_timeout_tasks" in {item["code"] for item in result["dispatch_plan"]["skip_reasons"]}
    assert "rerun timeout/failed artifacts" in result["dispatch_plan"]["recommended_spawn"]["task"]

    summary_text = Path(result["summary_path"]).read_text()
    assert "Timeout Tasks: 1" in summary_text
    assert "Mode: artifact_rerun" in summary_text

    state_one = get_state("tsk_roundtable_timeout_001")
    state_two = get_state("tsk_roundtable_timeout_002")
    assert state_one["state"] == "final_closed"
    assert state_two["state"] == "final_closed"


def test_trading_roundtable_failed_batch_forces_skipped_artifact_rerun_even_with_explicit_allow(isolated_state_dir: Path):
    batch_id = "batch_trading_roundtable_failed"
    create_task("tsk_roundtable_failed_001", batch_id=batch_id)
    create_task("tsk_roundtable_failed_002", batch_id=batch_id)
    mark_failed("tsk_roundtable_failed_001", error="acceptance harness crashed")

    result = process_trading_roundtable_callback(
        batch_id=batch_id,
        task_id="tsk_roundtable_failed_002",
        result=_tracked_result(
            conclusion="PASS",
            blocker="none",
            next_step="freeze intake and open the next minimal wiring task",
        ),
        allow_auto_dispatch=True,
        requester_session_key="agent:main:discord:channel:123",
    )

    assert result["status"] == "processed"
    assert result["dispatch_plan"]["status"] == "skipped"
    assert result["dispatch_plan"]["continuation"]["mode"] == "artifact_rerun"
    assert result["dispatch_plan"]["safety_gates"]["batch_failed_count"] == 1
    assert "batch_has_failed_tasks" in {item["code"] for item in result["dispatch_plan"]["skip_reasons"]}
    assert "rerun timeout/failed artifacts" in result["dispatch_plan"]["recommended_spawn"]["task"]

    summary_text = Path(result["summary_path"]).read_text()
    assert "Failed Tasks: 1" in summary_text
    assert "Mode: artifact_rerun" in summary_text

    state_one = get_state("tsk_roundtable_failed_001")
    state_two = get_state("tsk_roundtable_failed_002")
    assert state_one["state"] == "final_closed"
    assert state_two["state"] == "final_closed"



def test_trading_roundtable_explicit_auto_dispatch_emits_runtime_compatible_plan(isolated_state_dir: Path):
    batch_id = "batch_trading_roundtable_pass"
    create_task("tsk_roundtable_pass_001", batch_id=batch_id)

    result = process_trading_roundtable_callback(
        batch_id=batch_id,
        task_id="tsk_roundtable_pass_001",
        result=_tracked_result(
            conclusion="PASS",
            blocker="none",
            next_step="freeze intake and open the next minimal wiring task",
        ),
        allow_auto_dispatch=True,
        requester_session_key="agent:main:discord:channel:123",
    )

    assert result["status"] == "processed"
    assert result["dispatch_plan"]["status"] == "triggered"
    assert result["dispatch_plan"]["backend"] == "subagent"
    assert "AUTO_DISPATCH_REQUEST" in result["dispatch_plan"]["parent_message"]
    assert result["dispatch_plan"]["recommended_spawn"]["runtime"] == "subagent"
    assert result["dispatch_plan"]["continuation"]["mode"] == "advance_phase_handoff"
    assert result["dispatch_plan"]["safety_gates"]["auto_dispatch_source"] == "explicit"
    assert result["dispatch_plan"]["safety_gates"]["default_auto_dispatch_eligible"] is True

    state_one = get_state("tsk_roundtable_pass_001")
    assert state_one["state"] == "next_task_dispatched"


def test_trading_roundtable_tmux_backend_marks_backend_state_as_diagnostic_only(isolated_state_dir: Path):
    batch_id = "batch_trading_roundtable_tmux_backend"
    create_task("tsk_trading_roundtable_tmux_backend_001", batch_id=batch_id)

    result = process_trading_roundtable_callback(
        batch_id=batch_id,
        task_id="tsk_trading_roundtable_tmux_backend_001",
        result=_tracked_result(
            conclusion="PASS",
            blocker="none",
            next_step="freeze intake and open the next minimal wiring task",
        ),
        backend="tmux",
        requester_session_key="agent:main:discord:channel:1483883339701158102",
    )

    assert result["status"] == "processed"
    dispatch_plan = result["dispatch_plan"]
    assert dispatch_plan["status"] == "triggered"
    assert dispatch_plan["backend"] == "tmux"
    assert dispatch_plan["canonical_callback"]["required"] is True
    assert dispatch_plan["canonical_callback"]["business_terminal_source"] == "scripts/orchestrator_callback_bridge.py complete"
    assert dispatch_plan["canonical_callback"]["callback_payload_schema"] == "trading_roundtable.v1.callback"
    assert dispatch_plan["canonical_callback"]["backend_terminal_role"] == "diagnostic_only"
    assert dispatch_plan["canonical_callback"]["report_role"] == "evidence_only_until_callback"
    assert dispatch_plan["safety_gates"]["business_terminal_source"] == "canonical_callback"
    assert dispatch_plan["safety_gates"]["backend_terminal_role"] == "diagnostic_only"
    assert "backend=tmux" in dispatch_plan["parent_message"]
    assert "canonical callback" in dispatch_plan["parent_message"]
    assert any("diagnostic only" in note for note in dispatch_plan["backend_plan"]["notes"])

    summary_text = Path(result["summary_path"]).read_text()
    assert "## Business Terminal Contract" in summary_text
    assert "canonical callback" in summary_text
    assert "diagnostic evidence only" in summary_text

    receipt_text = Path(result["ack_result"]["receipt_path"]).read_text()
    assert "roundtable advances only after the canonical callback is bridged" in receipt_text



def test_channel_roundtable_tmux_backend_exposes_bridge_commands(isolated_state_dir: Path):
    batch_id = "batch_current_channel_tmux_backend"
    create_task("tsk_current_channel_tmux_backend_001", batch_id=batch_id)

    result = process_channel_roundtable_callback(
        batch_id=batch_id,
        task_id="tsk_current_channel_tmux_backend_001",
        result=_current_channel_roundtable_result(),
        backend="tmux",
        requester_session_key="agent:main:discord:channel:1483883339701158102",
    )

    assert result["status"] == "processed"
    dispatch_plan = result["dispatch_plan"]
    assert dispatch_plan["status"] == "triggered"
    assert dispatch_plan["backend"] == "tmux"
    assert dispatch_plan["backend_plan"]["backend"] == "tmux"
    assert dispatch_plan["backend_plan"]["observable_intermediate_state"] is True
    assert dispatch_plan["backend_plan"]["commands"]["start"].startswith(
        "python3 scripts/orchestrator_dispatch_bridge.py start --dispatch "
    )
    assert dispatch_plan["backend_plan"]["commands"]["status"].startswith(
        "python3 scripts/orchestrator_dispatch_bridge.py status --dispatch "
    )
    assert "backend=tmux" in dispatch_plan["parent_message"]
    assert dispatch_plan["timeout_policy"]["backend"] == "tmux"


def test_tmux_watchdog_retries_once_then_requires_manual_takeover():
    first = decide_watchdog_action(
        backend="tmux",
        status="stuck",
        retry_count=0,
        elapsed_total_seconds=120,
        elapsed_idle_seconds=120,
        report_exists=False,
    )
    assert first["action"] == "retry_once"
    assert first["reason"] == "status_stuck_or_dead"

    second = decide_watchdog_action(
        backend="tmux",
        status="stuck",
        retry_count=1,
        elapsed_total_seconds=240,
        elapsed_idle_seconds=240,
        report_exists=False,
    )
    assert second["action"] == "manual_takeover"
    assert second["reason"] == "status_stuck_or_dead_after_retry_limit"

    artifact_ready = decide_watchdog_action(
        backend="tmux",
        status="likely_done",
        retry_count=0,
        elapsed_total_seconds=240,
        elapsed_idle_seconds=0,
        report_exists=True,
    )
    assert artifact_ready["action"] == "await_canonical_callback"
    assert artifact_ready["reason"] == "completion_artifact_ready_but_canonical_callback_required"

    backend_done_only = decide_watchdog_action(
        backend="tmux",
        status="likely_done",
        retry_count=0,
        elapsed_total_seconds=240,
        elapsed_idle_seconds=0,
        report_exists=False,
    )
    assert backend_done_only["action"] == "await_completion_artifact"
    assert backend_done_only["reason"] == "backend_reports_done_but_no_completion_artifact"

    overtime = decide_watchdog_action(
        backend="tmux",
        status="running",
        retry_count=0,
        elapsed_total_seconds=31 * 60,
        elapsed_idle_seconds=0,
        report_exists=False,
    )
    assert overtime["action"] == "manual_takeover"
    assert overtime["reason"] == "timeout_total_exceeded"
