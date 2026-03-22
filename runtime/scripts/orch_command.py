#!/usr/bin/env python3
"""Canonical orchestration entry command with no-input defaults."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
LOCAL_RUNTIME_DIR = SCRIPT_DIR / "orchestration_entry_runtime"
REPO_ROOT = Path(__file__).resolve().parents[1]
ORCHESTRATOR_DIR = REPO_ROOT / "orchestrator"

if LOCAL_RUNTIME_DIR.exists():
    sys.path.insert(0, str(LOCAL_RUNTIME_DIR))
elif str(ORCHESTRATOR_DIR) not in sys.path:
    sys.path.insert(0, str(ORCHESTRATOR_DIR))

from entry_defaults import build_default_entry_contract  # type: ignore


def _env(name: str) -> Optional[str]:
    import os

    value = os.environ.get(name)
    if value is None:
        return None
    text = value.strip()
    return text or None


def _env_first(*names: str) -> Optional[str]:
    for name in names:
        value = _env(name)
        if value is not None:
            return value
    return None


def _parse_auto_execute(raw: Optional[str]) -> Optional[bool]:
    if raw is None:
        return True
    value = raw.strip().lower()
    if not value or value == "auto":
        return True
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"unsupported --auto-execute value: {raw}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate the canonical orchestration contract from explicit or ambient context.",
        epilog=(
            "Examples:\n"
            "  python3 ~/.openclaw/scripts/orch_command.py\n"
            "  python3 ~/.openclaw/scripts/orch_command.py --context trading_roundtable --backend tmux\n"
            "  python3 ~/.openclaw/scripts/orch_command.py contract --output tmp/orch-contract.json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="contract",
        choices=["contract", "start"],
        help="contract = generate the canonical contract; start is a backward-compatible alias.",
    )
    parser.add_argument("--context", default=None, help="auto | channel_roundtable | trading_roundtable")
    parser.add_argument("--scenario", default=None)
    parser.add_argument("--channel-id", default=None)
    parser.add_argument("--channel-name", default=None)
    parser.add_argument("--topic", default=None)
    parser.add_argument("--owner", default=None)
    parser.add_argument("--backend", default=None)
    parser.add_argument("--requester-session-key", default=None)
    parser.add_argument("--batch-key", default=None)
    parser.add_argument("--auto-execute", default=None, help="true|false; default=true")
    parser.add_argument("--output", default=None, help="optional JSON output path")
    return parser


def _resolved_value(cli_value: Optional[str], *env_names: str) -> Optional[str]:
    return cli_value or _env_first(*env_names)


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    contract = build_default_entry_contract(
        context=_resolved_value(args.context, "ORCH_CONTEXT", "OPENCLAW_ORCH_CONTEXT"),
        scenario=_resolved_value(args.scenario, "ORCH_SCENARIO", "OPENCLAW_ORCH_SCENARIO"),
        channel_id=_resolved_value(
            args.channel_id,
            "ORCH_CHANNEL_ID",
            "OPENCLAW_REQUESTER_CHANNEL_ID",
            "OPENCLAW_REQUESTER_CHANNEL",
        ),
        channel_name=_resolved_value(args.channel_name, "ORCH_CHANNEL_NAME", "OPENCLAW_REQUESTER_CHANNEL_NAME"),
        topic=_resolved_value(args.topic, "ORCH_TOPIC", "OPENCLAW_REQUESTER_TOPIC"),
        owner=_resolved_value(args.owner, "ORCH_OWNER", "OPENCLAW_ORCH_OWNER"),
        backend=_resolved_value(args.backend, "ORCH_BACKEND", "OPENCLAW_ORCH_BACKEND"),
        requester_session_key=_resolved_value(
            args.requester_session_key,
            "ORCH_REQUESTER_SESSION_KEY",
            "OPENCLAW_REQUESTER_SESSION_KEY",
        ),
        batch_key=_resolved_value(args.batch_key, "ORCH_BATCH_KEY", "OPENCLAW_ORCH_BATCH_KEY"),
        auto_execute=_parse_auto_execute(args.auto_execute),
        command_name="orch_command",
    )
    contract["orchestration"]["entrypoint"]["command"] = "contract" if args.command == "start" else args.command
    contract["orchestration"]["entrypoint"]["command_alias_used"] = args.command == "start"

    if args.output:
        output_path = Path(args.output).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    json.dump(contract, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
