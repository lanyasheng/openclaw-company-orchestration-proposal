from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ORCHESTRATOR_DIR = REPO_ROOT / "orchestrator"
SCRIPT_PATH = REPO_ROOT / "scripts" / "orchestrator_dispatch_bridge.py"
if str(ORCHESTRATOR_DIR) not in sys.path:
    sys.path.insert(0, str(ORCHESTRATOR_DIR))

from state_machine import create_task, get_state  # type: ignore
from tmux_terminal_receipts import (  # type: ignore
    build_callback_payload_from_tmux_receipt,
    build_tmux_terminal_receipt,
    receipt_lifecycle_paths,
)


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
        "tmux_terminal_receipts",
    ]:
        if module_name in sys.modules:
            importlib.reload(sys.modules[module_name])

    yield


def _dispatch_payload(*, dispatch_path: Path, batch_id: str, requester_session_key: str) -> dict:
    orchestrator_dir = dispatch_path.parent.parent
    summary_path = orchestrator_dir / "summaries" / f"batch-{batch_id}-summary.md"
    decision_path = orchestrator_dir / "decisions" / f"dec_{batch_id}_001.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    decision_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text("summary", encoding="utf-8")
    decision_path.write_text("{}", encoding="utf-8")

    return {
        "dispatch_id": dispatch_path.stem,
        "batch_id": batch_id,
        "scenario": "trading_roundtable_phase1",
        "adapter": "trading_roundtable",
        "decision_id": f"dec_{batch_id}_001",
        "status": "triggered",
        "reason": "trading roundtable proceed can continue via backend=tmux",
        "backend": "tmux",
        "continuation": {
            "mode": "advance_phase_handoff",
            "task_preview": "freeze intake and open the next minimal wiring task",
            "next_round_goal": "freeze this passing gate and open exactly one minimal next-round trading continuation",
            "completion_criteria": "phase1 packet v1 exists with artifact/report/commit/test/repro truth paths",
            "review_required": False,
        },
        "orchestration_contract": {
            "enabled": True,
            "adapter": "trading_roundtable",
            "scenario": "trading_roundtable_phase1",
            "batch_key": batch_id,
            "owner": "trading",
            "backend_preference": "tmux",
            "callback_payload_schema": "trading_roundtable.v1.callback",
            "session": {
                "requester_session_key": requester_session_key,
            },
        },
        "artifacts": {
            "batch_summary": str(summary_path),
            "decision_file": str(decision_path),
        },
        "backend_plan": {
            "backend": "tmux",
            "label": "trading-roundtable-tmux-bridge-smoke",
            "session": "cc-trading-roundtable-tmux-bridge-smoke",
            "workdir": str(REPO_ROOT),
            "prompt_file": "/tmp/cc-trading-roundtable-tmux-bridge-smoke-dispatch-ref.md",
            "scripts": {},
            "commands": {},
        },
    }


def _real_trading_business_payload() -> dict:
    return {
        "summary": "tmux trading business payload preserved real phase1 truth",
        "verdict": "PASS",
        "trading_roundtable": {
            "packet": {
                "packet_version": "trading_phase1_packet_v1",
                "phase_id": "trading_phase1",
                "candidate_id": "rs_canonical_e2e_demo",
                "run_label": "run_2026_03_20_rerun",
                "input_config_path": "workspace-trading/research/v2_portfolio/basket_configs/rs_canonical_e2e_demo.json",
                "generated_at": "2026-03-20T18:00:00+08:00",
                "owner": "trading",
                "overall_gate": "PASS",
                "primary_blocker": "none",
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
                        "python3 research/run_acceptance_harness.py --input research/v2_portfolio/basket_configs/rs_canonical_e2e_demo.json"
                    ],
                    "notes": "requires canonical config and tracked dataset snapshot",
                },
                "tradability": {
                    "annual_turnover": 1.82,
                    "liquidity_flags": [],
                    "gross_return": 0.21,
                    "net_return": 0.19,
                    "benchmark_return": 0.05,
                    "scenario_verdict": "PASS",
                    "turnover_failure_reasons": [],
                    "liquidity_failure_reasons": [],
                    "net_vs_gross_failure_reasons": [],
                    "summary": "clean pass candidate",
                },
            },
            "roundtable": {
                "conclusion": "PASS",
                "blocker": "none",
                "owner": "trading",
                "next_step": "freeze intake and open the next minimal wiring task",
                "completion_criteria": "phase1 packet v1 exists with artifact/report/commit/test/repro truth paths",
            },
        },
    }


def _channel_dispatch_payload(*, dispatch_path: Path, batch_id: str, requester_session_key: str) -> dict:
    orchestrator_dir = dispatch_path.parent.parent
    summary_path = orchestrator_dir / "summaries" / f"batch-{batch_id}-summary.md"
    decision_path = orchestrator_dir / "decisions" / f"dec_{batch_id}_001.json"
    prompt_file = dispatch_path.parent.parent / "tmux_receipts" / f"{dispatch_path.stem}.dispatch-ref.md"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    decision_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text("summary", encoding="utf-8")
    decision_path.write_text("{}", encoding="utf-8")

    return {
        "dispatch_id": dispatch_path.stem,
        "batch_id": batch_id,
        "scenario": "current_channel_architecture_roundtable",
        "adapter": "channel_roundtable",
        "decision_id": f"dec_{batch_id}_001",
        "status": "triggered",
        "reason": "channel roundtable proceed can continue via backend=tmux",
        "backend": "tmux",
        "continuation": {
            "mode": "channel_roundtable_followup",
            "task_preview": "freeze the architecture decision and open one focused follow-up thread",
            "next_round_goal": "carry the current architecture roundtable to one clean next step",
            "completion_criteria": "channel roundtable packet v1 exists with conclusion/blocker/next_step truth",
            "review_required": False,
        },
        "orchestration_contract": {
            "enabled": True,
            "adapter": "channel_roundtable",
            "scenario": "current_channel_architecture_roundtable",
            "batch_key": batch_id,
            "owner": "main",
            "backend_preference": "tmux",
            "callback_payload_schema": "channel_roundtable.v1.callback",
            "channel": {
                "channel_id": "discord:channel:1483883339701158102",
                "channel_name": "temporal-vs-langgraph",
                "topic": "Temporal vs LangGraph｜OpenClaw 公司级编排架构",
            },
            "session": {
                "requester_session_key": requester_session_key,
            },
        },
        "artifacts": {
            "batch_summary": str(summary_path),
            "decision_file": str(decision_path),
        },
        "backend_plan": {
            "backend": "tmux",
            "label": "channel-roundtable-tmux-bridge-smoke",
            "session": "cc-channel-roundtable-tmux-bridge-smoke",
            "workdir": str(REPO_ROOT),
            "prompt_file": str(prompt_file),
            "scripts": {},
            "commands": {},
        },
    }


def _real_channel_business_payload() -> dict:
    return {
        "summary": "tmux channel business payload preserved architecture decision",
        "verdict": "PASS",
        "channel_roundtable": {
            "packet": {
                "packet_version": "channel_roundtable_v1",
                "scenario": "current_channel_architecture_roundtable",
                "channel_id": "discord:channel:1483883339701158102",
                "channel_name": "temporal-vs-langgraph",
                "topic": "Temporal vs LangGraph｜OpenClaw 公司级编排架构",
                "owner": "main",
                "generated_at": "2026-03-22T00:10:00+08:00",
                "artifact": {
                    "path": "docs/architecture/2026-03-21-orchestration-skill-and-command-defaults.md",
                    "exists": True,
                },
            },
            "roundtable": {
                "conclusion": "PASS",
                "blocker": "none",
                "owner": "main",
                "next_step": "freeze the architecture decision and open one focused follow-up thread",
                "completion_criteria": "channel roundtable packet v1 exists with conclusion/blocker/next_step truth",
            },
        },
    }


def test_build_tmux_terminal_receipt_success_ready(tmp_path: Path):
    dispatch_dir = tmp_path / "state" / "orchestrator" / "dispatches"
    dispatch_dir.mkdir(parents=True, exist_ok=True)
    dispatch_path = dispatch_dir / "disp_batch_tmux_receipt_ready.json"
    batch_id = "batch_tmux_receipt_ready"
    dispatch = _dispatch_payload(
        dispatch_path=dispatch_path,
        batch_id=batch_id,
        requester_session_key="agent:main:discord:channel:1483883339701158102",
    )
    dispatch_path.write_text(json.dumps(dispatch, ensure_ascii=False, indent=2), encoding="utf-8")

    report_json = tmp_path / "report.json"
    report_md = tmp_path / "report.md"
    report_json.write_text(
        json.dumps(
            {
                "label": "tmux-bridge-smoke",
                "workdir": str(REPO_ROOT),
                "changedFiles": ["orchestrator/file.py"],
                "diffStat": "1 file changed, 5 insertions(+)",
                "lint": {"ok": True, "summary": "ok"},
                "build": {"ok": True, "summary": "ok"},
                "risk": "low",
                "scopeDrift": False,
                "recommendation": "keep",
                "notes": "tmux bridge smoke completed cleanly",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    report_md.write_text("# report", encoding="utf-8")

    receipt = build_tmux_terminal_receipt(
        dispatch=dispatch,
        dispatch_path=dispatch_path,
        tmux_status="likely_done",
        report_json_path=report_json,
        report_md_path=report_md,
    )

    assert receipt["backend"] == "tmux"
    assert receipt["terminal_state"] == "completed"
    assert receipt["summary"] == "tmux bridge smoke completed cleanly"
    assert receipt["stopped_because"] == "tmux_completion_report_ready"
    assert receipt["next_step"] == "freeze intake and open the next minimal wiring task"
    assert receipt["next_owner"] == "trading"
    assert receipt["dispatch_readiness"] == "ready"
    assert receipt["artifact_paths"]["report_json"] == str(report_json)
    assert receipt["artifact_paths"]["report_md"] == str(report_md)


def test_tmux_callback_payload_prefers_real_business_payload(tmp_path: Path):
    dispatch_dir = tmp_path / "state" / "orchestrator" / "dispatches"
    dispatch_dir.mkdir(parents=True, exist_ok=True)
    dispatch_path = dispatch_dir / "disp_batch_tmux_real_business_payload.json"
    batch_id = "batch_tmux_real_business_payload"
    dispatch = _dispatch_payload(
        dispatch_path=dispatch_path,
        batch_id=batch_id,
        requester_session_key="agent:main:discord:channel:1483883339701158102",
    )
    dispatch_path.write_text(json.dumps(dispatch, ensure_ascii=False, indent=2), encoding="utf-8")

    report_json = tmp_path / "report.json"
    report_md = tmp_path / "report.md"
    report_json.write_text(
        json.dumps(
            {
                "label": "tmux-bridge-smoke",
                "workdir": str(REPO_ROOT),
                "changedFiles": ["orchestrator/file.py"],
                "diffStat": "1 file changed, 5 insertions(+)",
                "lint": {"ok": True, "summary": "ok"},
                "build": {"ok": True, "summary": "ok"},
                "risk": "low",
                "scopeDrift": False,
                "recommendation": "keep",
                "notes": "tmux bridge smoke completed cleanly",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    report_md.write_text("# report", encoding="utf-8")

    lifecycle_paths = receipt_lifecycle_paths(dispatch_path)
    lifecycle_paths["business_payload_path"].write_text(
        json.dumps(_real_trading_business_payload(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    receipt = build_tmux_terminal_receipt(
        dispatch=dispatch,
        dispatch_path=dispatch_path,
        tmux_status="likely_done",
        report_json_path=report_json,
        report_md_path=report_md,
    )
    callback_payload = build_callback_payload_from_tmux_receipt(dispatch, receipt)

    assert receipt["business_callback"]["detected"] is True
    assert callback_payload["summary"] == "tmux trading business payload preserved real phase1 truth"
    assert callback_payload["closeout"]["business_payload_source"].startswith("business_payload_path:")
    assert callback_payload["trading_roundtable"]["packet"]["candidate_id"] == "rs_canonical_e2e_demo"
    assert callback_payload["trading_roundtable"]["packet"]["tradability"]["scenario_verdict"] == "PASS"
    assert callback_payload["trading_roundtable"]["roundtable"]["conclusion"] == "PASS"
    assert callback_payload["backend_terminal_receipt"]["backend"] == "tmux"
    assert callback_payload["callback_envelope"]["adapter"] == "trading_roundtable"
    assert callback_payload["callback_envelope"]["backend_terminal_receipt"]["terminal_state"] == "completed"
    assert callback_payload["callback_envelope"]["adapter_scoped_payload"]["payload"]["packet"]["candidate_id"] == "rs_canonical_e2e_demo"


def test_tmux_callback_payload_prefers_real_channel_business_payload(tmp_path: Path):
    dispatch_dir = tmp_path / "state" / "orchestrator" / "dispatches"
    dispatch_dir.mkdir(parents=True, exist_ok=True)
    dispatch_path = dispatch_dir / "disp_batch_tmux_real_channel_business_payload.json"
    batch_id = "batch_tmux_real_channel_business_payload"
    dispatch = _channel_dispatch_payload(
        dispatch_path=dispatch_path,
        batch_id=batch_id,
        requester_session_key="agent:main:discord:channel:1483883339701158102",
    )
    dispatch_path.write_text(json.dumps(dispatch, ensure_ascii=False, indent=2), encoding="utf-8")

    report_json = tmp_path / "report.json"
    report_md = tmp_path / "report.md"
    report_json.write_text(
        json.dumps(
            {
                "label": "tmux-channel-bridge-smoke",
                "workdir": str(REPO_ROOT),
                "changedFiles": ["docs/architecture/channel.md"],
                "diffStat": "1 file changed, 5 insertions(+)",
                "lint": {"ok": True, "summary": "ok"},
                "build": {"ok": True, "summary": "ok"},
                "risk": "low",
                "scopeDrift": False,
                "recommendation": "keep",
                "notes": "tmux channel bridge smoke completed cleanly",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    report_md.write_text("# report", encoding="utf-8")

    lifecycle_paths = receipt_lifecycle_paths(dispatch_path)
    lifecycle_paths["business_payload_path"].write_text(
        json.dumps(_real_channel_business_payload(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    receipt = build_tmux_terminal_receipt(
        dispatch=dispatch,
        dispatch_path=dispatch_path,
        tmux_status="likely_done",
        report_json_path=report_json,
        report_md_path=report_md,
    )
    callback_payload = build_callback_payload_from_tmux_receipt(dispatch, receipt)

    assert receipt["business_callback"]["detected"] is True
    assert callback_payload["summary"] == "tmux channel business payload preserved architecture decision"
    assert callback_payload["closeout"]["business_payload_source"].startswith("business_payload_path:")
    assert callback_payload["channel_roundtable"]["packet"]["packet_version"] == "channel_roundtable_v1"
    assert callback_payload["channel_roundtable"]["packet"]["topic"] == "Temporal vs LangGraph｜OpenClaw 公司级编排架构"
    assert callback_payload["channel_roundtable"]["roundtable"]["conclusion"] == "PASS"
    assert callback_payload["channel_roundtable"]["roundtable"]["next_step"] == "freeze the architecture decision and open one focused follow-up thread"


def test_dispatch_bridge_prepare_channel_reference_mentions_channel_contract(tmp_path: Path):
    dispatch_dir = tmp_path / "state" / "orchestrator" / "dispatches"
    dispatch_dir.mkdir(parents=True, exist_ok=True)
    dispatch_path = dispatch_dir / "disp_batch_tmux_channel_prepare.json"
    batch_id = "batch_tmux_channel_prepare"
    dispatch = _channel_dispatch_payload(
        dispatch_path=dispatch_path,
        batch_id=batch_id,
        requester_session_key="agent:main:discord:channel:1483883339701158102",
    )
    dispatch_path.write_text(json.dumps(dispatch, ensure_ascii=False, indent=2), encoding="utf-8")

    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "prepare",
            "--dispatch",
            str(dispatch_path),
        ],
        capture_output=True,
        text=True,
        check=True,
        env=os.environ,
    )

    payload = json.loads(proc.stdout)
    prompt_text = Path(payload["prompt_file"]).read_text(encoding="utf-8")
    assert payload["backend"] == "tmux"
    assert "channel path: channel_roundtable.packet + channel_roundtable.roundtable" in prompt_text
    assert "do not by themselves advance channel_roundtable business state" in prompt_text
    assert "trading roundtable business state" not in prompt_text


def test_tmux_callback_payload_generates_blocked_trading_packet_without_business_payload(tmp_path: Path):
    dispatch_dir = tmp_path / "state" / "orchestrator" / "dispatches"
    dispatch_dir.mkdir(parents=True, exist_ok=True)
    dispatch_path = dispatch_dir / "disp_batch_tmux_blocked_business_payload.json"
    batch_id = "batch_tmux_blocked_business_payload"
    dispatch = _dispatch_payload(
        dispatch_path=dispatch_path,
        batch_id=batch_id,
        requester_session_key="agent:main:discord:channel:1483883339701158102",
    )
    dispatch_path.write_text(json.dumps(dispatch, ensure_ascii=False, indent=2), encoding="utf-8")

    report_json = tmp_path / "report.json"
    report_md = tmp_path / "report.md"
    report_json.write_text(
        json.dumps(
            {
                "label": "tmux-bridge-smoke",
                "workdir": str(REPO_ROOT),
                "changedFiles": ["orchestrator/file.py"],
                "diffStat": "1 file changed, 5 insertions(+)",
                "lint": {"ok": True, "summary": "ok"},
                "build": {"ok": True, "summary": "ok"},
                "risk": "low",
                "scopeDrift": False,
                "recommendation": "keep",
                "notes": "tmux bridge smoke completed cleanly",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    report_md.write_text("# report", encoding="utf-8")

    receipt = build_tmux_terminal_receipt(
        dispatch=dispatch,
        dispatch_path=dispatch_path,
        tmux_status="likely_done",
        report_json_path=report_json,
        report_md_path=report_md,
    )
    callback_payload = build_callback_payload_from_tmux_receipt(dispatch, receipt)

    assert receipt["business_callback"]["detected"] is False
    assert callback_payload["verdict"] == "FAIL"
    assert callback_payload["closeout"]["business_payload_source"] == "generated_blocked_payload"
    assert callback_payload["trading_roundtable"]["packet"]["packet_version"] == "trading_phase1_packet_v1"
    assert callback_payload["trading_roundtable"]["packet"]["phase_id"] == "trading_phase1"
    assert callback_payload["trading_roundtable"]["packet"]["tmux_bridge"]["status"] == "blocked"
    assert "candidate_id" in callback_payload["trading_roundtable"]["packet"]["tmux_bridge"]["missing_business_fields"]
    assert callback_payload["trading_roundtable"]["roundtable"]["blocker"] == "tmux_completion_report_ready"
    assert callback_payload["callback_envelope"]["source"]["business_payload_source"] == "generated_blocked_payload"


def test_tmux_callback_payload_wraps_channel_business_payload_in_canonical_envelope(tmp_path: Path):
    dispatch_dir = tmp_path / "state" / "orchestrator" / "dispatches"
    dispatch_dir.mkdir(parents=True, exist_ok=True)
    dispatch_path = dispatch_dir / "disp_batch_tmux_channel_business_payload.json"
    batch_id = "batch_tmux_channel_business_payload"
    dispatch = _channel_dispatch_payload(
        dispatch_path=dispatch_path,
        batch_id=batch_id,
        requester_session_key="agent:main:discord:channel:1483883339701158102",
    )
    dispatch_path.write_text(json.dumps(dispatch, ensure_ascii=False, indent=2), encoding="utf-8")

    report_json = tmp_path / "report.json"
    report_md = tmp_path / "report.md"
    report_json.write_text(
        json.dumps(
            {
                "label": "channel-tmux-bridge-smoke",
                "workdir": str(REPO_ROOT),
                "changedFiles": ["docs/architecture/2026-03-21-orchestration-skill-and-command-defaults.md"],
                "diffStat": "1 file changed, 12 insertions(+)",
                "lint": {"ok": True, "summary": "ok"},
                "build": {"ok": True, "summary": "ok"},
                "risk": "low",
                "scopeDrift": False,
                "recommendation": "keep",
                "notes": "tmux channel bridge completed cleanly",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    report_md.write_text("# report", encoding="utf-8")

    lifecycle_paths = receipt_lifecycle_paths(dispatch_path)
    lifecycle_paths["business_payload_path"].write_text(
        json.dumps(_real_channel_business_payload(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    receipt = build_tmux_terminal_receipt(
        dispatch=dispatch,
        dispatch_path=dispatch_path,
        tmux_status="likely_done",
        report_json_path=report_json,
        report_md_path=report_md,
    )
    callback_payload = build_callback_payload_from_tmux_receipt(dispatch, receipt)

    assert callback_payload["summary"] == "tmux channel business payload preserved architecture decision"
    assert callback_payload["channel_roundtable"]["packet"]["channel_id"] == "discord:channel:1483883339701158102"
    assert callback_payload["channel_roundtable"]["roundtable"]["conclusion"] == "PASS"
    assert callback_payload["backend_terminal_receipt"]["backend"] == "tmux"
    assert callback_payload["callback_envelope"]["adapter"] == "channel_roundtable"
    assert callback_payload["callback_envelope"]["source"]["business_payload_source"].startswith("business_payload_path:")
    assert callback_payload["callback_envelope"]["adapter_scoped_payload"]["payload"]["roundtable"]["conclusion"] == "PASS"


def test_tmux_callback_payload_preserves_channel_aliases_from_contract(tmp_path: Path):
    dispatch_dir = tmp_path / "state" / "orchestrator" / "dispatches"
    dispatch_dir.mkdir(parents=True, exist_ok=True)
    dispatch_path = dispatch_dir / "disp_batch_tmux_real_channel_business_payload.json"
    batch_id = "batch_tmux_real_channel_business_payload"
    dispatch = _channel_dispatch_payload(
        dispatch_path=dispatch_path,
        batch_id=batch_id,
        requester_session_key="agent:main:discord:channel:1483883339701158102",
    )
    dispatch["orchestration_contract"]["channel"] = {
        "id": "discord:channel:1483883339701158102",
        "name": "temporal-vs-langgraph",
        "topic": "Temporal vs LangGraph｜OpenClaw 公司级编排架构",
    }
    dispatch_path.write_text(json.dumps(dispatch, ensure_ascii=False, indent=2), encoding="utf-8")

    report_json = tmp_path / "channel-report.json"
    report_md = tmp_path / "channel-report.md"
    report_json.write_text(
        json.dumps(
            {
                "label": "channel-tmux-bridge-smoke",
                "workdir": str(REPO_ROOT),
                "changedFiles": ["docs/architecture/file.md"],
                "diffStat": "1 file changed, 5 insertions(+)",
                "lint": {"ok": True, "summary": "ok"},
                "build": {"ok": True, "summary": "ok"},
                "risk": "low",
                "scopeDrift": False,
                "recommendation": "keep",
                "notes": "channel tmux bridge smoke completed cleanly",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    report_md.write_text("# channel report", encoding="utf-8")

    lifecycle_paths = receipt_lifecycle_paths(dispatch_path)
    lifecycle_paths["business_payload_path"].write_text(
        json.dumps(_real_channel_business_payload(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    receipt = build_tmux_terminal_receipt(
        dispatch=dispatch,
        dispatch_path=dispatch_path,
        tmux_status="likely_done",
        report_json_path=report_json,
        report_md_path=report_md,
    )
    callback_payload = build_callback_payload_from_tmux_receipt(dispatch, receipt)

    assert receipt["business_callback"]["detected"] is True
    assert callback_payload["channel_roundtable"]["packet"]["packet_version"] == "channel_roundtable_v1"
    assert callback_payload["channel_roundtable"]["packet"]["channel_id"] == "discord:channel:1483883339701158102"
    assert callback_payload["channel_roundtable"]["packet"]["topic"] == "Temporal vs LangGraph｜OpenClaw 公司级编排架构"
    assert callback_payload["generic_roundtable"]["packet"]["channel_name"] == "temporal-vs-langgraph"
    assert callback_payload["closeout"]["business_payload_source"].startswith("business_payload_path:")


def test_tmux_callback_payload_generates_minimal_valid_channel_packet_without_business_payload(tmp_path: Path):
    dispatch_dir = tmp_path / "state" / "orchestrator" / "dispatches"
    dispatch_dir.mkdir(parents=True, exist_ok=True)
    dispatch_path = dispatch_dir / "disp_batch_tmux_generated_channel_payload.json"
    batch_id = "batch_tmux_generated_channel_payload"
    dispatch = _channel_dispatch_payload(
        dispatch_path=dispatch_path,
        batch_id=batch_id,
        requester_session_key="agent:main:discord:channel:1483883339701158102",
    )
    dispatch["orchestration_contract"]["channel"] = {
        "id": "discord:channel:1483883339701158102",
        "name": "temporal-vs-langgraph",
        "topic": "Temporal vs LangGraph｜OpenClaw 公司级编排架构",
    }
    dispatch_path.write_text(json.dumps(dispatch, ensure_ascii=False, indent=2), encoding="utf-8")

    report_json = tmp_path / "channel-generated-report.json"
    report_md = tmp_path / "channel-generated-report.md"
    report_json.write_text(
        json.dumps(
            {
                "label": "channel-tmux-bridge-generated",
                "workdir": str(REPO_ROOT),
                "changedFiles": ["docs/architecture/file.md"],
                "diffStat": "1 file changed, 3 insertions(+)",
                "lint": {"ok": True, "summary": "ok"},
                "build": {"ok": True, "summary": "ok"},
                "risk": "low",
                "scopeDrift": False,
                "recommendation": "keep",
                "notes": "channel tmux bridge finished without a dedicated business callback payload",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    report_md.write_text("# generated channel report", encoding="utf-8")

    receipt = build_tmux_terminal_receipt(
        dispatch=dispatch,
        dispatch_path=dispatch_path,
        tmux_status="likely_done",
        report_json_path=report_json,
        report_md_path=report_md,
    )
    callback_payload = build_callback_payload_from_tmux_receipt(dispatch, receipt)

    assert receipt["business_callback"]["detected"] is False
    assert callback_payload["channel_roundtable"]["packet"]["packet_version"] == "channel_roundtable_v1"
    assert callback_payload["channel_roundtable"]["packet"]["channel_id"] == "discord:channel:1483883339701158102"
    assert callback_payload["channel_roundtable"]["packet"]["channel_name"] == "temporal-vs-langgraph"
    assert callback_payload["channel_roundtable"]["packet"]["topic"] == "Temporal vs LangGraph｜OpenClaw 公司级编排架构"
    assert callback_payload["generic_roundtable"]["packet"]["channel_id"] == "discord:channel:1483883339701158102"
    assert callback_payload["closeout"]["business_payload_source"] == "generic_tmux_receipt"


def test_dispatch_bridge_complete_routes_tmux_receipt_into_callback_path(isolated_state_dir: Path, tmp_path: Path):
    batch_id = "batch_tmux_bridge_complete"
    task_id = "tsk_tmux_bridge_complete_001"
    requester_session_key = "agent:main:discord:channel:1483883339701158102"
    create_task(task_id, batch_id=batch_id)

    dispatch_dir = isolated_state_dir.parent / "orchestrator" / "dispatches"
    dispatch_dir.mkdir(parents=True, exist_ok=True)
    dispatch_path = dispatch_dir / "disp_batch_tmux_bridge_complete.json"
    dispatch = _dispatch_payload(
        dispatch_path=dispatch_path,
        batch_id=batch_id,
        requester_session_key=requester_session_key,
    )
    dispatch_path.write_text(json.dumps(dispatch, ensure_ascii=False, indent=2), encoding="utf-8")

    report_json = tmp_path / "tmux-report.json"
    report_md = tmp_path / "tmux-report.md"
    report_json.write_text(
        json.dumps(
            {
                "label": "tmux-bridge-complete",
                "workdir": str(REPO_ROOT),
                "changedFiles": ["orchestrator/tmux_terminal_receipts.py"],
                "diffStat": "1 file changed, 42 insertions(+)",
                "lint": {"ok": True, "summary": "ok"},
                "build": {"ok": True, "summary": "ok"},
                "risk": "low",
                "scopeDrift": False,
                "recommendation": "keep",
                "notes": "tmux completion bridge wrote a canonical receipt",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    report_md.write_text("# tmux report", encoding="utf-8")

    lifecycle_paths = receipt_lifecycle_paths(dispatch_path)
    lifecycle_paths["business_payload_path"].write_text(
        json.dumps(_real_trading_business_payload(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    env = {**os.environ, "OPENCLAW_STATE_DIR": str(isolated_state_dir), "OPENCLAW_ACK_GUARD_DISABLE_DELIVERY": "1"}
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "complete",
            "--dispatch",
            str(dispatch_path),
            "--task-id",
            task_id,
            "--tmux-status",
            "likely_done",
            "--report-json",
            str(report_json),
            "--report-md",
            str(report_md),
            "--requester-session-key",
            requester_session_key,
            "--allow-auto-dispatch",
            "false",
        ],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )

    result = json.loads(proc.stdout)
    receipt = result["receipt"]
    bridge_result = result["bridge_result"]

    assert receipt["backend"] == "tmux"
    assert receipt["terminal_state"] == "completed"
    assert receipt["dispatch_readiness"] == "ready"
    assert receipt["stopped_because"] == "tmux_completion_report_ready"
    assert Path(result["receipt_path"]).exists()
    assert Path(result["callback_payload_path"]).exists()

    callback_payload = json.loads(Path(result["callback_payload_path"]).read_text(encoding="utf-8"))
    assert callback_payload["closeout"]["stopped_because"] == "tmux_completion_report_ready"
    assert callback_payload["closeout"]["next_owner"] == "trading"
    assert callback_payload["closeout"]["dispatch_readiness"] == "ready"
    assert callback_payload["closeout"]["business_payload_source"].startswith("business_payload_path:")
    assert callback_payload["tmux_terminal_receipt"]["backend"] == "tmux"
    assert callback_payload["trading_roundtable"]["packet"]["candidate_id"] == "rs_canonical_e2e_demo"
    assert callback_payload["trading_roundtable"]["roundtable"]["conclusion"] == "PASS"

    assert bridge_result["status"] == "processed"
    assert bridge_result["batch_id"] == batch_id
    assert bridge_result["task_id"] == task_id
    assert bridge_result["dispatch_plan"]["backend"] == "tmux"
    assert bridge_result["dispatch_plan"]["canonical_callback"]["callback_envelope_schema"] == "canonical_callback_envelope.v1"
    assert bridge_result["dispatch_plan"]["status"] == "skipped"
    assert bridge_result["dispatch_plan"]["continuation"]["mode"] == "advance_phase_handoff"
    assert bridge_result["dispatch_plan"]["safety_gates"]["default_auto_dispatch_eligible"] is True
    assert bridge_result["ack_guard"]["status"] == "present"
    assert Path(bridge_result["ack_result"]["receipt_path"]).exists()

    state = get_state(task_id)
    assert state["state"] == "final_closed"
    assert state["result"]["closeout"]["stopped_because"] == "tmux_completion_report_ready"
    assert state["result"]["tmux_terminal_receipt"]["dispatch_readiness"] == "ready"
    assert state["result"]["trading_roundtable"]["packet"]["candidate_id"] == "rs_canonical_e2e_demo"
    assert state["result"]["trading_roundtable"]["roundtable"]["conclusion"] == "PASS"


def test_dispatch_bridge_complete_routes_channel_receipt_into_callback_path(isolated_state_dir: Path, tmp_path: Path):
    batch_id = "batch_tmux_channel_bridge_complete"
    task_id = "tsk_tmux_channel_bridge_complete_001"
    requester_session_key = "agent:main:discord:channel:1483883339701158102"
    create_task(task_id, batch_id=batch_id)

    dispatch_dir = isolated_state_dir.parent / "orchestrator" / "dispatches"
    dispatch_dir.mkdir(parents=True, exist_ok=True)
    dispatch_path = dispatch_dir / "disp_batch_tmux_channel_bridge_complete.json"
    dispatch = _channel_dispatch_payload(
        dispatch_path=dispatch_path,
        batch_id=batch_id,
        requester_session_key=requester_session_key,
    )
    dispatch_path.write_text(json.dumps(dispatch, ensure_ascii=False, indent=2), encoding="utf-8")

    report_json = tmp_path / "tmux-channel-report.json"
    report_md = tmp_path / "tmux-channel-report.md"
    report_json.write_text(
        json.dumps(
            {
                "label": "tmux-channel-bridge-complete",
                "workdir": str(REPO_ROOT),
                "changedFiles": ["docs/architecture/2026-03-21-orchestration-skill-and-command-defaults.md"],
                "diffStat": "1 file changed, 18 insertions(+)",
                "lint": {"ok": True, "summary": "ok"},
                "build": {"ok": True, "summary": "ok"},
                "risk": "low",
                "scopeDrift": False,
                "recommendation": "keep",
                "notes": "tmux channel completion bridge wrote a canonical receipt",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    report_md.write_text("# tmux channel report", encoding="utf-8")

    lifecycle_paths = receipt_lifecycle_paths(dispatch_path)
    lifecycle_paths["business_payload_path"].write_text(
        json.dumps(_real_channel_business_payload(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    env = {**os.environ, "OPENCLAW_STATE_DIR": str(isolated_state_dir), "OPENCLAW_ACK_GUARD_DISABLE_DELIVERY": "1"}
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "complete",
            "--dispatch",
            str(dispatch_path),
            "--task-id",
            task_id,
            "--tmux-status",
            "likely_done",
            "--report-json",
            str(report_json),
            "--report-md",
            str(report_md),
            "--requester-session-key",
            requester_session_key,
            "--allow-auto-dispatch",
            "false",
        ],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )

    result = json.loads(proc.stdout)
    callback_payload = json.loads(Path(result["callback_payload_path"]).read_text(encoding="utf-8"))
    bridge_result = result["bridge_result"]

    assert callback_payload["callback_envelope"]["adapter"] == "channel_roundtable"
    assert callback_payload["channel_roundtable"]["roundtable"]["conclusion"] == "PASS"
    assert bridge_result["status"] == "processed"
    assert bridge_result["dispatch_plan"]["backend"] == "tmux"
    assert bridge_result["dispatch_plan"]["canonical_callback"]["callback_envelope_schema"] == "canonical_callback_envelope.v1"
    assert bridge_result["ack_guard"]["status"] == "present"

    state = get_state(task_id)
    assert state["state"] == "final_closed"
    assert state["result"]["channel_roundtable"]["packet"]["topic"] == "Temporal vs LangGraph｜OpenClaw 公司级编排架构"
    assert state["result"]["callback_envelope"]["adapter_scoped_payload"]["payload"]["roundtable"]["conclusion"] == "PASS"


def test_dispatch_bridge_receipt_blocks_dead_tmux_without_report(isolated_state_dir: Path, tmp_path: Path):
    batch_id = "batch_tmux_bridge_dead"
    task_id = "tsk_tmux_bridge_dead_001"
    requester_session_key = "agent:main:discord:channel:1483883339701158102"
    create_task(task_id, batch_id=batch_id)

    dispatch_dir = isolated_state_dir.parent / "orchestrator" / "dispatches"
    dispatch_dir.mkdir(parents=True, exist_ok=True)
    dispatch_path = dispatch_dir / "disp_batch_tmux_bridge_dead.json"
    dispatch = _dispatch_payload(
        dispatch_path=dispatch_path,
        batch_id=batch_id,
        requester_session_key=requester_session_key,
    )
    dispatch_path.write_text(json.dumps(dispatch, ensure_ascii=False, indent=2), encoding="utf-8")

    env = {**os.environ, "OPENCLAW_STATE_DIR": str(isolated_state_dir), "OPENCLAW_ACK_GUARD_DISABLE_DELIVERY": "1"}
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "receipt",
            "--dispatch",
            str(dispatch_path),
            "--tmux-status",
            "dead",
        ],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )

    receipt = json.loads(proc.stdout)
    assert receipt["backend"] == "tmux"
    assert receipt["terminal_state"] == "failed"
    assert receipt["dispatch_readiness"] == "blocked"
    assert receipt["stopped_because"] == "tmux_session_dead_without_report"
    assert Path(receipt["written_receipt_path"]).exists()
