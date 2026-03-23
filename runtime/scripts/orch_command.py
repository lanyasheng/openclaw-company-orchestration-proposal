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
        description="🚀 OpenClaw Orchestration 单入口命令 — 给频道/主题即可生成可用 contract",
        epilog=(
            "╔═══════════════════════════════════════════════════════════╗\n"
            "║  单入口无缝接入 — 只用这个命令即可完成默认接入            ║\n"
            "╠═══════════════════════════════════════════════════════════╣\n"
            "║  快速开始：                                               ║\n"
            "║  # 1. 无参数 = 使用当前频道默认配置                        ║\n"
            "║  python3 ~/.openclaw/scripts/orch_command.py              ║\n"
            "║                                                           ║\n"
            "║  # 2. 指定频道/主题 = 生成该频道 contract                  ║\n"
            "║  python3 ~/.openclaw/scripts/orch_command.py \\            ║\n"
            "║    --channel-id \"discord:channel:YOUR_ID\" \\              ║\n"
            "║    --channel-name \"your-channel\" \\                       ║\n"
            "║    --topic \"讨论主题\"                                     ║\n"
            "║                                                           ║\n"
            "║  # 3. Trading 场景 = 自动使用 trading_roundtable           ║\n"
            "║  python3 ~/.openclaw/scripts/orch_command.py \\            ║\n"
            "║    --context trading_roundtable                           ║\n"
            "║                                                           ║\n"
            "║  默认行为：                                               ║\n"
            "║  • coding lane → Claude Code (via subagent)               ║\n"
            "║  • non-coding lane → subagent                             ║\n"
            "║  • auto_execute=true (自动注册/派发/回调/续推)             ║\n"
            "║  • gate_policy=stop_on_gate (命中 gate 正常停住)           ║\n"
            "║  • 首次接入建议 --auto-execute false 先验证稳定            ║\n"
            "╚═══════════════════════════════════════════════════════════╝"
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
    parser.add_argument("--context", default=None, help="auto | channel_roundtable | trading_roundtable (默认根据场景/频道自动推导)")
    parser.add_argument("--scenario", default=None, help="场景标识，例如 product_launch_roundtable (默认根据频道推导)")
    parser.add_argument("--channel-id", default=None, help="频道 ID，例如 discord:channel:123456")
    parser.add_argument("--channel-name", default=None, help="频道名称，例如 general")
    parser.add_argument("--topic", default=None, help="讨论主题，例如 架构评审")
    parser.add_argument("--owner", default=None, help="任务负责人，例如 main")
    parser.add_argument("--backend", default=None, help="执行后端：subagent (默认) | tmux (兼容模式)")
    parser.add_argument("--requester-session-key", default=None, help="请求者 session key (可选)")
    parser.add_argument("--batch-key", default=None, help="批次 key (可选，默认自动生成)")
    parser.add_argument("--auto-execute", default=None, help="true|false; 默认=true; 首次接入建议 false 先验证稳定")
    parser.add_argument("--output", default=None, help="可选的 JSON 输出路径，例如 tmp/orch-contract.json")
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
