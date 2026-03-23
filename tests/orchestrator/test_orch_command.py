from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ORCHESTRATOR_DIR = REPO_ROOT / "runtime" / "orchestrator"
ORCH_COMMAND = REPO_ROOT / "runtime" / "scripts" / "orch_command.py"
INSTALL_ORCH_GLOBAL = REPO_ROOT / "runtime" / "scripts" / "install_orchestration_entry_global.py"
CALLBACK_BRIDGE = REPO_ROOT / "runtime" / "scripts" / "orchestrator_callback_bridge.py"
ORCHESTRATION_ENTRY_SKILL = REPO_ROOT / "runtime" / "skills" / "orchestration-entry" / "SKILL.md"
if str(ORCHESTRATOR_DIR) not in sys.path:
    sys.path.insert(0, str(ORCHESTRATOR_DIR))

from entry_defaults import build_default_entry_contract  # type: ignore
from state_machine import create_task  # type: ignore


@pytest.fixture()
def isolated_state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    state_dir = tmp_path / "shared-context" / "job-status"
    monkeypatch.setenv("OPENCLAW_STATE_DIR", str(state_dir))
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
        "entry_defaults",
    ]:
        if module_name in sys.modules:
            importlib.reload(sys.modules[module_name])

    yield


def _run_orch_command(*args: str, env: dict | None = None) -> dict:
    proc = subprocess.run(
        [sys.executable, str(ORCH_COMMAND), *args],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    return json.loads(proc.stdout)


def _frontmatter_keys(markdown_path: Path) -> set[str]:
    text = markdown_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert lines and lines[0].strip() == "---"

    keys: set[str] = set()
    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "---":
            break
        if not stripped:
            continue
        key, _, _ = stripped.partition(":")
        keys.add(key.strip())
    return keys


def _failing_trading_payload(orchestration: dict) -> dict:
    return {
        "summary": "real artifact-backed FAIL payload",
        "verdict": "FAIL",
        "orchestration": orchestration,
        "trading_roundtable": {
            "packet": {
                "packet_version": "trading_phase1_packet_v1",
                "phase_id": "trading_phase1",
                "candidate_id": "rs_canonical_v1",
                "run_label": "rs_canonical_e2e_demo_20260320",
                "input_config_path": "workspace-trading/research/v2_portfolio/basket_configs/rs_canonical_v1.json",
                "generated_at": "2026-03-21T01:46:00+08:00",
                "owner": "trading",
                "overall_gate": "FAIL",
                "primary_blocker": "tradability",
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
                        "python3 -m pytest tests/v2_portfolio/test_acceptance_harness.py -q"
                    ],
                    "summary": "18 passed in 0.41s",
                },
                "repro": {
                    "commands": [
                        "python3 research/run_acceptance_harness.py --input research/v2_portfolio/basket_configs/rs_canonical_v1.json"
                    ],
                    "notes": "artifact-backed failure case",
                },
                "tradability": {
                    "annual_turnover": 4.91,
                    "liquidity_flags": ["small_cap_liquidity"],
                    "gross_return": 0.11,
                    "net_return": -0.02,
                    "benchmark_return": 0.05,
                    "scenario_verdict": "FAIL",
                    "turnover_failure_reasons": ["annual_turnover_exceeds_hard_limit"],
                    "liquidity_failure_reasons": ["liquidity_threshold_not_met"],
                    "net_vs_gross_failure_reasons": ["net_return_under_benchmark"],
                    "summary": "turnover hard-limit violations remain the main blocker",
                },
            },
            "roundtable": {
                "conclusion": "FAIL",
                "blocker": "tradability",
                "owner": "trading",
                "next_step": "freeze this real FAIL packet, then only open the smallest remaining frozen-candidate acceptance run needed to prove whether phase-a has any real PASS candidate",
                "completion_criteria": "real phase1 packet is frozen with artifact/report/commit/test/repro truth paths and remaining frozen-candidate run command is explicit",
            },
        },
    }


def test_orchestration_entry_skill_points_to_runnable_command():
    text = ORCHESTRATION_ENTRY_SKILL.read_text(encoding="utf-8")

    assert ORCHESTRATION_ENTRY_SKILL.exists()
    assert _frontmatter_keys(ORCHESTRATION_ENTRY_SKILL) == {"name", "description"}
    assert "python3 ~/.openclaw/scripts/orch_command.py" in text
    assert "python3 ~/.openclaw/workspace/scripts/install_orchestration_entry_global.py" in text
    assert "~/.openclaw/workspace/docs/architecture/2026-03-21-orchestration-skill-and-command-defaults.md" in text

    result = _run_orch_command()
    assert result["orchestration"]["entrypoint"]["command"] == "contract"


def test_orch_command_without_input_defaults_to_current_channel_contract():
    result = _run_orch_command()

    assert result["entry_context"]["resolved_context"] == "channel_roundtable"
    assert result["orchestration"]["adapter"] == "channel_roundtable"
    assert result["orchestration"]["scenario"] == "current_channel_architecture_roundtable"
    assert result["orchestration"]["auto_execute"] is True
    assert result["orchestration"]["entrypoint"]["command"] == "contract"
    assert result["orchestration"]["gate_policy"]["mode"] == "stop_on_gate"
    assert result["seed_payload"]["channel_roundtable"]["packet"]["channel_id"] == "discord:channel:1483883339701158102"


def test_default_contract_includes_bootstrap_capability_card():
    """Verify that default contract (no input) includes bootstrap_capability_card."""
    result = _run_orch_command()

    assert "onboarding" in result
    assert "bootstrap_capability_card" in result["onboarding"]

    card = result["onboarding"]["bootstrap_capability_card"]
    assert card["adapter"] == "channel_roundtable"
    assert "key_constraint" in card
    assert "channel_roundtable" in card["key_constraint"]
    assert "不需要新 adapter" in card["key_constraint"]
    assert "first_run_recommendation" in card
    assert card["first_run_recommendation"]["allow_auto_dispatch"] is False
    assert "operator_kit_path" in card
    assert "example_contract" in card
    assert "example_callback" in card


def test_orch_command_uses_ambient_context_for_trading_without_cli_input():
    env = {
        **os.environ,
        "ORCH_CONTEXT": "trading_roundtable",
        "ORCH_BACKEND": "tmux",
    }
    result = _run_orch_command(env=env)

    assert result["entry_context"]["resolved_context"] == "trading_roundtable"
    assert result["orchestration"]["adapter"] == "trading_roundtable"
    assert result["orchestration"]["scenario"] == "trading_roundtable_phase1"
    assert result["orchestration"]["backend_preference"] == "tmux"
    assert result["orchestration"]["auto_execute"] is True
    assert result["seed_payload"]["trading_roundtable"]["roundtable"]["conclusion"] == "PENDING"


def test_orch_command_custom_channel_scenario_exposes_generic_onboarding_seam():
    result = _run_orch_command(
        "--scenario",
        "product_launch_roundtable",
        "--channel-id",
        "discord:channel:4242",
        "--channel-name",
        "product-launch-review",
        "--topic",
        "Product Launch Review",
        "--owner",
        "content",
    )

    assert result["entry_context"]["resolved_context"] == "channel_roundtable"
    assert result["orchestration"]["scenario"] == "product_launch_roundtable"
    assert result["orchestration"]["channel"]["id"] == "discord:channel:4242"
    assert result["orchestration"]["channel"]["channel_id"] == "discord:channel:4242"
    assert result["orchestration"]["channel"]["name"] == "product-launch-review"
    assert result["orchestration"]["channel"]["channel_name"] == "product-launch-review"
    assert result["orchestration"]["channel"]["topic"] == "Product Launch Review"
    assert result["orchestration"]["metadata"]["template_name"] == "channel_roundtable.generic_defaults"
    assert result["seed_payload"]["channel_roundtable"]["packet"]["scenario"] == "product_launch_roundtable"
    assert result["seed_payload"]["generic_roundtable"]["packet"]["scenario"] == "product_launch_roundtable"
    assert result["seed_payload"]["channel_roundtable"]["roundtable"]["conclusion"] == "CONDITIONAL"
    assert result["onboarding"]["adapter_capability"] == "channel_roundtable.generic.v1"
    assert result["onboarding"]["payload_aliases"] == ["channel_roundtable", "generic_roundtable"]
    assert result["onboarding"]["new_scenario_minimum"]["required_contract_fields"] == ["scenario"]
    assert "channel_id" in result["onboarding"]["new_scenario_minimum"]["required_packet_fields"]


def test_orch_command_generic_channel_scenario_includes_operator_kit():
    """Verify that generic channel scenarios include the operator-facing onboarding kit."""
    result = _run_orch_command(
        "--scenario",
        "marketing_sync_roundtable",
        "--channel-id",
        "discord:channel:9999",
        "--channel-name",
        "marketing-sync",
        "--topic",
        "Marketing Sync Roundtable",
        "--owner",
        "marketing",
    )

    assert result["entry_context"]["resolved_context"] == "channel_roundtable"
    assert result["orchestration"]["scenario"] == "marketing_sync_roundtable"
    assert "operator_kit" in result["onboarding"]

    kit = result["onboarding"]["operator_kit"]
    assert "entry_file" in kit
    assert "example_contract_file" in kit
    assert "example_callback_file" in kit
    assert "checklist" in kit
    assert "example_commands" in kit
    assert "recommended_first_run" in kit

    assert len(kit["checklist"]) >= 5
    assert kit["recommended_first_run"]["allow_auto_dispatch"] is False
    assert "generate_contract" in kit["example_commands"]
    assert "complete_subagent" in kit["example_commands"]
    # P0-3 Batch 5 (2026-03-23): complete_tmux removed from default example commands
    # tmux backend is COMPAT-ONLY for legacy dispatches; new development MUST use subagent
    assert "complete_tmux" not in kit["example_commands"], "P0-3 Batch 5: tmux commands should not be in default example_commands"

    commands = kit["example_commands"]
    assert "marketing_sync_roundtable" in commands["generate_contract"]
    assert "discord:channel:9999" in commands["generate_contract"]
    assert "generic_non_trading_roundtable_callback.json" in commands["complete_subagent"]


def test_generic_channel_contract_includes_bootstrap_capability_card_with_key_constraints():
    """Verify that generic channel contract includes bootstrap_capability_card with key constraints."""
    result = _run_orch_command(
        "--scenario",
        "product_launch_roundtable",
        "--channel-id",
        "discord:channel:4242",
        "--channel-name",
        "product-launch-review",
        "--topic",
        "Product Launch Review",
        "--owner",
        "content",
    )

    assert "onboarding" in result
    assert "bootstrap_capability_card" in result["onboarding"]

    card = result["onboarding"]["bootstrap_capability_card"]
    # 关键约束：adapter、不需要新 adapter、allow_auto_dispatch false、operator kit path
    assert card["adapter"] == "channel_roundtable"
    assert "scenario_hint" in card
    assert "generic_roundtable" in card["scenario_hint"]
    assert "key_constraint" in card
    assert "channel_roundtable" in card["key_constraint"]
    assert "不需要新 adapter" in card["key_constraint"]
    assert "first_run_recommendation" in card
    assert card["first_run_recommendation"]["allow_auto_dispatch"] is False
    assert "operator_kit_path" in card
    assert "orchestrator/examples/generic_channel_roundtable_onboarding_kit.md" in card["operator_kit_path"]
    assert "example_contract" in card
    assert "example_callback" in card


def test_install_orchestration_entry_global_builds_self_contained_runtime(tmp_path: Path):
    global_root = tmp_path / "global-openclaw"

    proc = subprocess.run(
        [sys.executable, str(INSTALL_ORCH_GLOBAL), "--global-root", str(global_root)],
        capture_output=True,
        text=True,
        check=True,
    )
    install_result = json.loads(proc.stdout)

    installed_skill = global_root / "skills" / "orchestration-entry" / "SKILL.md"
    installed_references_dir = global_root / "skills" / "orchestration-entry" / "references"
    installed_hook_guard_reference = installed_references_dir / "hook-guard-capabilities.md"
    installed_command = global_root / "scripts" / "orch_command.py"
    installed_runtime_dir = global_root / "scripts" / "orchestration_entry_runtime"

    assert install_result["self_contained_runtime"] is True
    assert Path(install_result["installed"]["skill"]) == installed_skill
    assert Path(install_result["installed"]["references_dir"]) == installed_references_dir
    assert Path(install_result["installed"]["command"]) == installed_command
    assert installed_skill.exists()
    assert installed_hook_guard_reference.exists()
    assert installed_command.exists()
    assert (installed_runtime_dir / "__init__.py").exists()
    assert (installed_runtime_dir / "entry_defaults.py").exists()
    assert (installed_runtime_dir / "continuation_backends.py").exists()

    skill_text = installed_skill.read_text(encoding="utf-8")
    reference_text = installed_hook_guard_reference.read_text(encoding="utf-8")
    assert "python3 ~/.openclaw/scripts/orch_command.py" in skill_text
    assert "Completion delivery receipt guard" in reference_text

    contract_proc = subprocess.run(
        [sys.executable, str(installed_command)],
        capture_output=True,
        text=True,
        check=True,
    )
    contract_result = json.loads(contract_proc.stdout)
    assert contract_result["entry_context"]["resolved_context"] == "channel_roundtable"
    assert contract_result["orchestration"]["entrypoint"]["command"] == "contract"

    trading_proc = subprocess.run(
        [sys.executable, str(installed_command), "--context", "trading_roundtable", "--backend", "tmux"],
        capture_output=True,
        text=True,
        check=True,
    )
    trading_result = json.loads(trading_proc.stdout)
    assert trading_result["entry_context"]["resolved_context"] == "trading_roundtable"
    assert trading_result["orchestration"]["backend_preference"] == "tmux"
    assert trading_result["orchestration"]["auto_execute"] is True


def test_contract_auto_execute_default_does_not_bypass_trading_gate(
    isolated_state_dir: Path, tmp_path: Path
):
    batch_id = "batch_orch_command_fail_gate"
    task_id = "tsk_orch_command_fail_gate_001"
    create_task(task_id, batch_id=batch_id)

    contract = build_default_entry_contract(
        context="trading_roundtable",
        backend="tmux",
        requester_session_key="agent:main:discord:channel:1483883339701158102",
        batch_key=batch_id,
    )
    payload = _failing_trading_payload(contract["orchestration"])
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    env = {**os.environ, "OPENCLAW_STATE_DIR": str(isolated_state_dir)}
    proc = subprocess.run(
        [
            sys.executable,
            str(CALLBACK_BRIDGE),
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
        check=True,
        env=env,
    )

    result = json.loads(proc.stdout)
    skip_codes = {item["code"] for item in result["dispatch_plan"]["skip_reasons"]}

    assert result["contract_resolution"]["task_tier"] == "orchestrated"
    assert result["contract_resolution"]["auto_execute"] is True
    assert result["dispatch_plan"]["safety_gates"]["allow_auto_dispatch"] is True
    assert result["dispatch_plan"]["status"] == "skipped"
    assert "decision_not_auto_dispatchable" in skip_codes
    assert "roundtable_not_pass" in result["dispatch_plan"]["safety_gates"]["default_auto_dispatch_blockers"]


def test_contract_auto_execute_channel_does_not_bypass_whitelist(
    isolated_state_dir: Path, tmp_path: Path
):
    """
    Verify that for channel_roundtable, auto_execute=true in contract does NOT
    bypass the existing whitelist/default-deny policy unless explicitly forced.
    """
    batch_id = "batch_channel_whitelist_test"
    task_id = "tsk_channel_whitelist_test_001"
    create_task(task_id, batch_id=batch_id)

    contract = build_default_entry_contract(
        context="channel_roundtable",
        scenario="generic_product_test",
        channel_id="discord:channel:9999",
        channel_name="test-channel",
        topic="Test Channel",
        owner="test",
        backend="subagent",
        batch_key=batch_id,
    )

    callback_payload = {
        "summary": "Generic channel test completed.",
        "verdict": "PASS",
        "orchestration": {
            "enabled": True,
            "adapter": "channel_roundtable",
            "scenario": "generic_product_test",
            "batch_key": batch_id,
            "owner": "test",
            "backend_preference": "subagent",
            "callback_payload_schema": "channel_roundtable.v1.callback",
            "auto_execute": True,
            "channel": {
                "id": "discord:channel:9999",
                "name": "test-channel",
                "topic": "Test Channel",
            },
        },
        "channel_roundtable": {
            "packet": {
                "packet_version": "channel_roundtable_v1",
                "scenario": "generic_product_test",
                "channel_id": "discord:channel:9999",
                "channel_name": "test-channel",
                "topic": "Test Channel",
                "owner": "test",
                "generated_at": "2026-03-22T00:00:00+08:00",
            },
            "roundtable": {
                "conclusion": "PASS",
                "blocker": "none",
                "owner": "test",
                "next_step": "Continue to next phase.",
                "completion_criteria": "Next phase artifact exists.",
            },
        },
    }

    payload_path = tmp_path / "channel_callback.json"
    payload_path.write_text(json.dumps(callback_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    env = {**os.environ, "OPENCLAW_STATE_DIR": str(isolated_state_dir)}
    proc = subprocess.run(
        [
            sys.executable,
            str(CALLBACK_BRIDGE),
            "complete",
            "--task-id",
            task_id,
            "--batch-id",
            batch_id,
            "--payload",
            str(payload_path),
            "--runtime",
            "subagent",
            "--requester-session-key",
            "agent:main:discord:channel:9999",
        ],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )

    result = json.loads(proc.stdout)

    assert result["contract_resolution"]["task_tier"] == "orchestrated"
    assert result["contract_resolution"]["auto_execute"] is True
    assert result["dispatch_plan"]["status"] == "skipped"
    assert result["dispatch_plan"]["safety_gates"]["allow_auto_dispatch"] is False
    assert result["dispatch_plan"]["safety_gates"]["auto_dispatch_source"] == "default_deny"
    assert "manual confirmation required" in result["dispatch_plan"]["reason"]


def test_trading_contract_includes_bootstrap_capability_card():
    """Verify that trading contract also includes bootstrap_capability_card (optional but for completeness)."""
    env = {
        **os.environ,
        "ORCH_CONTEXT": "trading_roundtable",
        "ORCH_BACKEND": "tmux",
    }
    result = _run_orch_command(env=env)

    assert "onboarding" in result
    assert "bootstrap_capability_card" in result["onboarding"]

    card = result["onboarding"]["bootstrap_capability_card"]
    assert card["adapter"] == "trading_roundtable"
    assert "scenario_hint" in card
    assert "trading_roundtable_phase1" in card["scenario_hint"]
    assert "key_constraint" in card
    assert "trading" in card["key_constraint"]
    # trading card 不包含 first_run_recommendation / operator_kit_path 等 channel 特有字段
    assert "first_run_recommendation" not in card
    assert "operator_kit_path" not in card


def test_contract_structure_integrity_with_bootstrap_card():
    """
    Verify that adding bootstrap_capability_card does not break existing contract structure.
    Core assertions remain intact.
    """
    result = _run_orch_command()

    # 核心结构必须存在
    assert "entry_context" in result
    assert "onboarding" in result
    assert "orchestration" in result
    assert "seed_payload" in result

    # orchestration 核心字段
    orch = result["orchestration"]
    assert "enabled" in orch
    assert "adapter" in orch
    assert "scenario" in orch
    assert "batch_key" in orch
    assert "owner" in orch
    assert "backend_preference" in orch
    assert "callback_payload_schema" in orch
    assert "auto_execute" in orch
    assert "gate_policy" in orch
    assert "channel" in orch

    # onboarding 核心字段（原有）
    onboarding = result["onboarding"]
    assert "adapter_capability" in onboarding
    assert "seed_scope" in onboarding
    assert "payload_aliases" in onboarding
    assert "new_scenario_minimum" in onboarding
    assert "runtime_reuse" in onboarding
    assert "current_boundary" in onboarding

    # 新增 bootstrap_capability_card 不影响原有字段
    assert "bootstrap_capability_card" in onboarding
    # 验证原有字段仍然完整
    assert onboarding["adapter_capability"] == "channel_roundtable.generic.v1"
    assert onboarding["seed_scope"] == "channel_roundtable"
    assert "channel_roundtable" in onboarding["payload_aliases"]
