#!/usr/bin/env python3
"""orchestrator_dispatch_bridge.py — Unified tmux backend lifecycle entry point.

Subcommands: prepare | start | status | receipt | complete
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
START_SCRIPT = SCRIPTS_DIR / "start-tmux-task.sh"
STATUS_SCRIPT = SCRIPTS_DIR / "status-tmux-task.sh"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=60, **kwargs)


# ──── prepare ─────────────────────────────────────────────────────────

def cmd_prepare(args: argparse.Namespace) -> None:
    dispatch = json.loads(Path(args.dispatch).read_text())
    label = dispatch.get("label", dispatch.get("dispatch_id", "task")[:48])
    workdir = dispatch.get("workdir", ".")
    plan = {
        "backend": "tmux",
        "label": label,
        "session": f"cc-{label}",
        "workdir": workdir,
        "scripts": {
            "start": str(START_SCRIPT),
            "status": str(STATUS_SCRIPT),
        },
        "prepared_at": _now_iso(),
    }
    print(json.dumps(plan, indent=2))


# ──── start ───────────────────────────────────────────────────────────

def cmd_start(args: argparse.Namespace) -> None:
    dispatch = json.loads(Path(args.dispatch).read_text())
    label = dispatch.get("label", dispatch.get("dispatch_id", "task")[:48])
    workdir = dispatch.get("workdir", ".")
    task = dispatch.get("task", dispatch.get("prompt", ""))
    mode = dispatch.get("mode", "headless")
    timeout = str(dispatch.get("timeout", 3600))

    cmd = [
        str(START_SCRIPT),
        "--label", label,
        "--workdir", workdir,
        "--task", task,
        "--timeout", timeout,
        "--mode", mode,
    ]
    result = _run(cmd)
    sys.stdout.write(result.stdout)
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        sys.exit(result.returncode)


# ──── status ──────────────────────────────────────────────────────────

def cmd_status(args: argparse.Namespace) -> None:
    dispatch = json.loads(Path(args.dispatch).read_text())
    label = dispatch.get("label", dispatch.get("dispatch_id", "task")[:48])

    cmd = [str(STATUS_SCRIPT), "--label", label, "--json"]
    result = _run(cmd)
    sys.stdout.write(result.stdout)
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        sys.exit(result.returncode)


# ──── receipt ─────────────────────────────────────────────────────────

def cmd_receipt(args: argparse.Namespace) -> None:
    dispatch = json.loads(Path(args.dispatch).read_text())
    label = dispatch.get("label", dispatch.get("dispatch_id", "task")[:48])
    session = f"cc-{label}"

    report_path = Path(f"/tmp/{session}-completion-report.md")
    state_path = Path(f"/tmp/{session}-state.json")
    log_path = Path.home() / ".openclaw/logs" / f"{session}.jsonl"

    receipt = {
        "session": session,
        "label": label,
        "generated_at": _now_iso(),
        "report_exists": report_path.is_file(),
        "state_exists": state_path.is_file(),
        "log_exists": log_path.is_file(),
    }

    if report_path.is_file():
        receipt["report_preview"] = report_path.read_text()[:500]

    if state_path.is_file():
        try:
            receipt["state"] = json.loads(state_path.read_text())
        except json.JSONDecodeError:
            receipt["state"] = None

    print(json.dumps(receipt, indent=2))


# ──── complete ────────────────────────────────────────────────────────

def cmd_complete(args: argparse.Namespace) -> None:
    dispatch = json.loads(Path(args.dispatch).read_text())
    label = dispatch.get("label", dispatch.get("dispatch_id", "task")[:48])
    session = f"cc-{label}"
    state_path = Path(f"/tmp/{session}-state.json")

    state = {}
    if state_path.is_file():
        try:
            state = json.loads(state_path.read_text())
        except json.JSONDecodeError:
            pass

    state["status"] = "completed"
    state["completed_at"] = _now_iso()
    state["updated_at"] = _now_iso()
    if args.task_id:
        state["task_id"] = args.task_id

    state_path.write_text(json.dumps(state, indent=2))
    print(json.dumps({"action": "complete", "session": session, "state_file": str(state_path)}, indent=2))


# ──── CLI ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Orchestrator dispatch bridge for tmux backend")
    sub = parser.add_subparsers(dest="command", required=True)

    for name in ("prepare", "start", "status", "receipt"):
        p = sub.add_parser(name)
        p.add_argument("--dispatch", required=True, help="Path to dispatch JSON")

    p_complete = sub.add_parser("complete")
    p_complete.add_argument("--dispatch", required=True, help="Path to dispatch JSON")
    p_complete.add_argument("--task-id", default=None, help="Task ID to record")

    args = parser.parse_args()
    {"prepare": cmd_prepare, "start": cmd_start, "status": cmd_status, "receipt": cmd_receipt, "complete": cmd_complete}[args.command](args)


if __name__ == "__main__":
    main()
