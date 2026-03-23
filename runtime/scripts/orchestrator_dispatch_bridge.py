#!/usr/bin/env python3
"""
P0-3 Batch 4 (2026-03-23): LEGACY COMPATIBILITY BRIDGE SCRIPT

BACKEND POLICY:
- subagent backend: PRIMARY AND DEFAULT recommended backend for ALL new development
- tmux backend: COMPATIBILITY-ONLY legacy path for EXISTING production dispatches

This script provides tmux-specific dispatch bridge commands for backward compatibility ONLY.
DO NOT USE for new development. Migrate existing tmux dispatches to subagent backend.

Primary live path (2026-03-23): subagent backend with runner-based execution.

Retained for:
- Existing tmux-based dispatches in production (migration pending)
- Legacy observable session use cases (prefer subagent + runner artifacts)

Commands:
- prepare: Prepare dispatch plan reference document
- start: Launch tmux session with Claude Code
- status: Query tmux session status
- receipt: Build terminal receipt from tmux status
- complete: Complete dispatch and bridge to callback (critical path)
- capture: Capture tmux pane output (P0-3 Batch 3: deprecated; low usage)
- attach: Attach to tmux session (P0-3 Batch 3: deprecated; low usage)
- watchdog: Evaluate timeout/stuck policy (internal use only)
- describe: Describe dispatch plan (P0-3 Batch 3: deprecated; debug only)

Note: This bridge only supports tmux backend. For subagent backend,
use sessions_spawn directly with runner-based observation.

P0-3 Batch 3 (2026-03-23): Commands `describe`, `capture`, `attach` are marked
as deprecated due to low usage. They are retained for backward compatibility
but new development should prefer runner-based observation via subagent backend.

P0-3 Batch 4 (2026-03-23): Strengthened deprecation; tmux is COMPAT-ONLY.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

REPO_ROOT = Path(__file__).resolve().parents[1]
ORCHESTRATOR_DIR = REPO_ROOT / "orchestrator"
if str(ORCHESTRATOR_DIR) not in sys.path:
    sys.path.insert(0, str(ORCHESTRATOR_DIR))

from continuation_backends import build_timeout_policy, decide_watchdog_action  # type: ignore
from tmux_terminal_receipts import (  # type: ignore
    build_callback_payload_from_tmux_receipt,
    build_tmux_terminal_receipt,
    parse_tmux_status_output,
    receipt_lifecycle_paths,
    write_json,
)


CALLBACK_BRIDGE_SCRIPT = REPO_ROOT / "scripts" / "orchestrator_callback_bridge.py"


class BridgeError(RuntimeError):
    pass


def _read_dispatch(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text())
    backend = payload.get("backend")
    if backend != "tmux":
        raise BridgeError(f"dispatch backend is {backend!r}; bridge only supports tmux dispatches")
    backend_plan = payload.get("backend_plan") or {}
    if backend_plan.get("backend") != "tmux":
        raise BridgeError("dispatch missing tmux backend_plan")
    return payload


def _business_callback_contract_lines(dispatch: Dict[str, Any], lifecycle_paths: Dict[str, Path]) -> list[str]:
    adapter = str(dispatch.get("adapter") or "").strip() or "adapter"
    if adapter == "channel_roundtable":
        adapter_state_line = "- rule: tmux STATUS / completion report do not by themselves advance channel_roundtable business state."
    elif adapter == "trading_roundtable":
        adapter_state_line = "- rule: tmux STATUS / completion report do not by themselves advance trading roundtable business state."
    else:
        adapter_state_line = "- rule: tmux STATUS / completion report do not by themselves advance business state."

    return [
        f"- business_callback_output_path: {lifecycle_paths['business_payload_path']}",
        adapter_state_line,
        f"- rule: if the task can produce real {adapter} truth, write a structured business callback JSON to business_callback_output_path.",
        "- rule: if truth is insufficient for a clean business closeout, still write a blocked/degraded callback payload with explicit blocker and missing evidence instead of a generic completion note.",
        "- rule: the bridge will wrap the normalized payload into callback_envelope so future adapters can share the same terminal callback contract.",
    ]


def _business_callback_minimum_contract_lines(dispatch: Dict[str, Any]) -> list[str]:
    adapter = str(dispatch.get("adapter") or "").strip()
    common_lines = [
        "- callback_envelope.backend_terminal_receipt: canonical backend terminal receipt (tmux terminal state + artifact paths + readiness)",
        "- callback_envelope.business_callback_payload: normalized business callback payload used for business closeout",
        "- callback_envelope.adapter_scoped_payload: adapter-specific scoped payload (adapter + schema + payload)",
        "- callback_envelope.orchestration_contract: canonical contract for adapter/scenario/batch/session routing",
        "- legacy compatibility: summary/verdict/closeout/orchestration and adapter-scoped top-level keys are still preserved at the top level",
    ]
    if adapter == "channel_roundtable":
        return common_lines + [
            "- channel path: channel_roundtable.packet + channel_roundtable.roundtable",
            "- packet should carry packet_version/scenario/channel_id/topic/owner/generated_at, plus artifact hint when available",
            "- roundtable should carry conclusion/blocker/owner/next_step/completion_criteria",
        ]
    return common_lines + [
        "- trading path: trading_roundtable.packet + trading_roundtable.roundtable",
        "- packet should carry real phase1 truth when available (candidate/run_label/input_config/artifact/report/commit/test/repro/tradability)",
        "- blocked fallback is allowed: keep packet_version/phase_id/owner/generated_at plus tmux_bridge blocker + missing_business_fields",
    ]


def _render_reference(dispatch: Dict[str, Any], dispatch_path: Path) -> str:
    artifacts = dispatch.get("artifacts") or {}
    continuation = dispatch.get("continuation") or {}
    safety_gates = dispatch.get("safety_gates") or {}
    timeout_policy = dispatch.get("timeout_policy") or build_timeout_policy("tmux")
    recommended_spawn = dispatch.get("recommended_spawn") or {}
    canonical_callback = dispatch.get("canonical_callback") or {}
    orchestration_contract = dispatch.get("orchestration_contract") or {}
    lifecycle_paths = receipt_lifecycle_paths(dispatch_path)

    lines = [
        f"# Dispatch Plan Reference — {dispatch.get('dispatch_id', 'unknown')}",
        "",
        f"- Dispatch File: {dispatch_path}",
        f"- Adapter: {dispatch.get('adapter', 'N/A')}",
        f"- Scenario: {dispatch.get('scenario', 'N/A')}",
        f"- Batch ID: {dispatch.get('batch_id', 'N/A')}",
        f"- Decision ID: {dispatch.get('decision_id', 'N/A')}",
        f"- Backend: tmux",
        f"- Dispatch Status: {dispatch.get('status', 'N/A')}",
        f"- Reason: {dispatch.get('reason', 'N/A')}",
        "",
        "## Required continuation",
        "",
        f"- Task preview: {recommended_spawn.get('task_preview') or continuation.get('task_preview') or 'N/A'}",
        f"- Review required: {continuation.get('review_required', 'N/A')}",
        f"- Next-round goal: {continuation.get('next_round_goal', 'N/A')}",
        f"- Completion criteria: {continuation.get('completion_criteria', 'N/A')}",
        "",
        "## Single-source artifacts",
        "",
    ]

    for key, value in artifacts.items():
        lines.append(f"- {key}: {value}")

    lines.extend(
        [
            "",
            "## Canonical callback contract",
            "",
            f"- required: {canonical_callback.get('required', 'N/A')}",
            f"- business_terminal_source: {canonical_callback.get('business_terminal_source') or timeout_policy.get('business_terminal_source', 'N/A')}",
            f"- callback_payload_schema: {canonical_callback.get('callback_payload_schema') or orchestration_contract.get('callback_payload_schema', 'N/A')}",
            f"- callback_envelope_schema: {canonical_callback.get('callback_envelope_schema', 'canonical_callback_envelope.v1')}",
            f"- backend_terminal_role: {canonical_callback.get('backend_terminal_role') or timeout_policy.get('backend_terminal_role', 'N/A')}",
            f"- report_role: {canonical_callback.get('report_role', 'N/A')}",
            *_business_callback_contract_lines(dispatch, lifecycle_paths),
            "",
            "## Timeout / stuck / retry policy",
            "",
            f"- timeout_total_seconds: {timeout_policy.get('timeout_total_seconds')}",
            f"- timeout_stall_seconds: {timeout_policy.get('timeout_stall_seconds')}",
            f"- stall_grace_seconds: {timeout_policy.get('stall_grace_seconds')}",
            f"- max_auto_retry: {timeout_policy.get('max_auto_retry')}",
            f"- observer: {timeout_policy.get('observer', 'N/A')}",
            f"- stuck_definition: {timeout_policy.get('stuck_definition', [])}",
            f"- retry_once_when: {timeout_policy.get('retry_once_when', [])}",
            f"- manual_takeover_when: {timeout_policy.get('manual_takeover_when', [])}",
            "",
            "## Safety gates",
            "",
        ]
    )
    for key, value in safety_gates.items():
        lines.append(f"- {key}: {value}")

    lines.extend(
        [
            "",
            "## tmux terminal callback minimum contract",
            "",
            *_business_callback_minimum_contract_lines(dispatch),
            "",
            "## Full continuation prompt",
            "",
            recommended_spawn.get("task") or "N/A",
            "",
            "## Rules",
            "",
            "- Keep scope to exactly one continuation hop.",
            "- Use this dispatch plan as the source of truth for summary/decision/artifacts.",
            "- tmux STATUS / completion report are diagnostic only; business closeout still requires the canonical callback bridge.",
            "- If timeout/stuck/retry policy escalates to manual takeover, stop auto-retrying and hand back evidence.",
            "",
        ]
    )
    return "\n".join(lines)


def _prompt_file(dispatch: Dict[str, Any]) -> Path:
    backend_plan = dispatch["backend_plan"]
    return Path(backend_plan["prompt_file"])


def _prepare(dispatch_path: Path, dispatch: Dict[str, Any]) -> Dict[str, Any]:
    backend_plan = dispatch["backend_plan"]
    prompt_file = _prompt_file(dispatch)
    prompt_file.write_text(_render_reference(dispatch, dispatch_path))
    return {
        "dispatch_id": dispatch.get("dispatch_id"),
        "backend": "tmux",
        "prompt_file": str(prompt_file),
        "label": backend_plan.get("label"),
        "session": backend_plan.get("session"),
        "workdir": backend_plan.get("workdir"),
        "commands": backend_plan.get("commands", {}),
    }


def _run(args: list[str], *, capture_output: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        check=True,
        text=True,
        capture_output=capture_output,
    )


def _resolve_tmux_status(dispatch: Dict[str, Any], ns: argparse.Namespace) -> str:
    explicit = str(getattr(ns, "tmux_status", "") or "").strip()
    if explicit:
        return explicit

    backend_plan = dispatch["backend_plan"]
    scripts = backend_plan.get("scripts") or {}
    status_script = scripts.get("status_tmux_task")
    if not status_script:
        raise BridgeError("dispatch missing status_tmux_task script; pass --tmux-status explicitly")

    command = ["bash", status_script, "--label", backend_plan["label"]]
    result = _run(command, capture_output=True)
    parsed = parse_tmux_status_output(result.stdout)
    status = parsed.get("STATUS")
    if not status:
        raise BridgeError("unable to resolve tmux status from status script output")
    return status


def _report_json_path(dispatch: Dict[str, Any], ns: argparse.Namespace) -> Path | None:
    raw = getattr(ns, "report_json", None)
    return Path(raw).expanduser().resolve() if raw else None


def _report_md_path(dispatch: Dict[str, Any], ns: argparse.Namespace) -> Path | None:
    raw = getattr(ns, "report_md", None)
    return Path(raw).expanduser().resolve() if raw else None


def _build_receipt(dispatch_path: Path, dispatch: Dict[str, Any], ns: argparse.Namespace) -> Dict[str, Any]:
    tmux_status = _resolve_tmux_status(dispatch, ns)
    return build_tmux_terminal_receipt(
        dispatch=dispatch,
        dispatch_path=dispatch_path,
        tmux_status=tmux_status,
        report_json_path=_report_json_path(dispatch, ns),
        report_md_path=_report_md_path(dispatch, ns),
    )


def cmd_describe(ns: argparse.Namespace) -> int:
    # P0-3 Batch 3 (2026-03-23): Deprecated - low usage debug command
    dispatch_path = Path(ns.dispatch).resolve()
    dispatch = _read_dispatch(dispatch_path)
    print(json.dumps(_prepare(dispatch_path, dispatch), indent=2, ensure_ascii=False))
    return 0


def cmd_prepare(ns: argparse.Namespace) -> int:
    dispatch_path = Path(ns.dispatch).resolve()
    dispatch = _read_dispatch(dispatch_path)
    print(json.dumps(_prepare(dispatch_path, dispatch), indent=2, ensure_ascii=False))
    return 0


def cmd_start(ns: argparse.Namespace) -> int:
    dispatch_path = Path(ns.dispatch).resolve()
    dispatch = _read_dispatch(dispatch_path)
    prepared = _prepare(dispatch_path, dispatch)
    backend_plan = dispatch["backend_plan"]
    scripts = backend_plan["scripts"]
    task_preview = (dispatch.get("recommended_spawn") or {}).get("task_preview") or backend_plan.get("task_preview") or dispatch.get("reason", "continue")

    command = [
        "bash",
        scripts["start_tmux_task"],
        "--label",
        backend_plan["label"],
        "--workdir",
        backend_plan["workdir"],
        "--prompt-file",
        prepared["prompt_file"],
        "--task",
        task_preview,
        "--lint-cmd",
        "",
        "--build-cmd",
        "",
    ]

    if ns.dry_run:
        print(json.dumps({"dry_run": True, "command": command, **prepared}, indent=2, ensure_ascii=False))
        return 0

    result = _run(command, capture_output=True)
    print(
        json.dumps(
            {
                "dry_run": False,
                "command": command,
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
                **prepared,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def cmd_status(ns: argparse.Namespace) -> int:
    dispatch = _read_dispatch(Path(ns.dispatch).resolve())
    backend_plan = dispatch["backend_plan"]
    scripts = backend_plan["scripts"]
    command = ["bash", scripts["status_tmux_task"], "--label", backend_plan["label"]]
    result = _run(command, capture_output=True)
    print(result.stdout.strip())
    return 0


def cmd_capture(ns: argparse.Namespace) -> int:
    # P0-3 Batch 3 (2026-03-23): Deprecated - low usage; prefer runner-based observation
    dispatch = _read_dispatch(Path(ns.dispatch).resolve())
    backend_plan = dispatch["backend_plan"]
    scripts = backend_plan["scripts"]
    command = [
        "bash",
        scripts["monitor_tmux_task"],
        "--session",
        backend_plan["session"],
        "--lines",
        str(ns.lines),
    ]
    result = _run(command, capture_output=True)
    print(result.stdout, end="")
    return 0


def cmd_attach(ns: argparse.Namespace) -> int:
    # P0-3 Batch 3 (2026-03-23): Deprecated - low usage; prefer runner-based observation
    dispatch = _read_dispatch(Path(ns.dispatch).resolve())
    backend_plan = dispatch["backend_plan"]
    scripts = backend_plan["scripts"]
    command = ["bash", scripts["monitor_tmux_task"], "--session", backend_plan["session"], "--attach"]
    if ns.print_only:
        print(" ".join(command))
        return 0
    subprocess.run(command, check=True)
    return 0


def cmd_receipt(ns: argparse.Namespace) -> int:
    dispatch_path = Path(ns.dispatch).resolve()
    dispatch = _read_dispatch(dispatch_path)
    receipt = _build_receipt(dispatch_path, dispatch, ns)
    lifecycle_paths = receipt_lifecycle_paths(dispatch_path)
    write_json(lifecycle_paths["receipt_path"], receipt)
    payload = {
        **receipt,
        "written_receipt_path": str(lifecycle_paths["receipt_path"]),
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


def cmd_complete(ns: argparse.Namespace) -> int:
    dispatch_path = Path(ns.dispatch).resolve()
    dispatch = _read_dispatch(dispatch_path)
    receipt = _build_receipt(dispatch_path, dispatch, ns)
    lifecycle_paths = receipt_lifecycle_paths(dispatch_path)
    receipt_path = write_json(lifecycle_paths["receipt_path"], receipt)
    callback_payload = build_callback_payload_from_tmux_receipt(dispatch, receipt)
    callback_payload_path = write_json(lifecycle_paths["callback_payload_path"], callback_payload)

    requester_session_key = ns.requester_session_key
    if not requester_session_key:
        contract = dispatch.get("orchestration_contract") if isinstance(dispatch.get("orchestration_contract"), dict) else {}
        session = contract.get("session") if isinstance(contract.get("session"), dict) else {}
        requester_session_key = session.get("requester_session_key")

    command = [
        sys.executable,
        str(CALLBACK_BRIDGE_SCRIPT),
        "complete",
        "--adapter",
        str(dispatch.get("adapter") or "auto"),
        "--task-id",
        ns.task_id,
        "--batch-id",
        str(dispatch.get("batch_id") or ""),
        "--payload",
        str(callback_payload_path),
        "--runtime",
        ns.runtime,
        "--backend",
        "tmux",
        "--allow-auto-dispatch",
        ns.allow_auto_dispatch,
    ]
    if requester_session_key:
        command.extend(["--requester-session-key", requester_session_key])

    result = _run(command, capture_output=True)
    try:
        bridge_result = json.loads(result.stdout)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise BridgeError(f"callback bridge returned non-JSON output: {exc}") from exc

    print(
        json.dumps(
            {
                "dispatch_id": dispatch.get("dispatch_id"),
                "backend": "tmux",
                "receipt": receipt,
                "receipt_path": str(receipt_path),
                "callback_payload_path": str(callback_payload_path),
                "callback_command": command,
                "bridge_result": bridge_result,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def cmd_watchdog(ns: argparse.Namespace) -> int:
    # P0-3 Batch 3 (2026-03-23): Internal use only - not part of primary dispatch flow
    dispatch = _read_dispatch(Path(ns.dispatch).resolve())
    timeout_policy = dispatch.get("timeout_policy") or build_timeout_policy("tmux")
    result = decide_watchdog_action(
        backend="tmux",
        status=ns.tmux_status,
        retry_count=ns.retry_count,
        elapsed_total_seconds=ns.elapsed_total_seconds,
        elapsed_idle_seconds=ns.elapsed_idle_seconds,
        report_exists=ns.report_exists,
    )
    result["dispatch_id"] = dispatch.get("dispatch_id")
    result["backend"] = "tmux"
    result["timeout_policy"] = timeout_policy
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bridge orchestrator dispatch plans into observable tmux commands")
    subparsers = parser.add_subparsers(dest="command", required=True)

    handlers = (
        ("describe", cmd_describe),
        ("prepare", cmd_prepare),
        ("start", cmd_start),
        ("status", cmd_status),
        ("capture", cmd_capture),
        ("attach", cmd_attach),
        ("receipt", cmd_receipt),
        ("complete", cmd_complete),
        ("watchdog", cmd_watchdog),
    )

    for name, handler in handlers:
        sub = subparsers.add_parser(name)
        sub.add_argument("--dispatch", required=True, help="path to dispatch plan json")
        if name == "start":
            sub.add_argument("--dry-run", action="store_true")
        if name == "capture":
            sub.add_argument("--lines", type=int, default=80)
        if name == "attach":
            sub.add_argument("--print-only", action="store_true")
        if name in {"receipt", "complete"}:
            sub.add_argument("--tmux-status", default=None, help="override tmux STATUS value instead of calling status-tmux-task.sh")
            sub.add_argument("--report-json", default=None, help="override completion report json path")
            sub.add_argument("--report-md", default=None, help="override completion report markdown path")
        if name == "complete":
            sub.add_argument("--task-id", required=True)
            sub.add_argument("--runtime", default="subagent")
            sub.add_argument("--requester-session-key", default=None)
            sub.add_argument("--allow-auto-dispatch", default="false")
        if name == "watchdog":
            sub.add_argument("--tmux-status", required=True)
            sub.add_argument("--retry-count", type=int, default=0)
            sub.add_argument("--elapsed-total-seconds", type=int)
            sub.add_argument("--elapsed-idle-seconds", type=int)
            sub.add_argument("--report-exists", action="store_true")
        sub.set_defaults(func=handler)

    return parser


def main() -> int:
    parser = build_parser()
    ns = parser.parse_args()
    try:
        return ns.func(ns)
    except BridgeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as exc:
        payload = {
            "command": exc.cmd,
            "returncode": exc.returncode,
            "stdout": exc.stdout,
            "stderr": exc.stderr,
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False), file=sys.stderr)
        return exc.returncode or 1


if __name__ == "__main__":
    raise SystemExit(main())
