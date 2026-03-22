#!/usr/bin/env python3
"""Run the current architecture-discussion channel through channel_roundtable whitelist-default auto-dispatch flow."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict


REPO_ROOT = Path(__file__).resolve().parents[1]
PAYLOAD_PATH = REPO_ROOT / "orchestrator" / "examples" / "current_channel_temporal_vs_langgraph_payload.json"
OUTPUT_ROOT = REPO_ROOT / "tmp" / "channel_roundtable_current_architecture_demo"
BATCH_ID = "batch_current_channel_temporal_vs_langgraph"
TASK_IDS = [
    "tsk_current_channel_architecture_001",
    "tsk_current_channel_architecture_002",
]


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=["subagent", "tmux"], default="subagent")
    args = parser.parse_args()

    output_root = OUTPUT_ROOT / args.backend
    state_dir = output_root / "state" / "job-status"

    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    payload = _read_json(PAYLOAD_PATH)
    (output_root / "payload.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")

    os.environ["OPENCLAW_STATE_DIR"] = str(state_dir)

    from state_machine import create_task  # pylint: disable=import-outside-toplevel
    from channel_roundtable import process_channel_roundtable_callback  # pylint: disable=import-outside-toplevel

    for task_id in TASK_IDS:
        create_task(task_id, batch_id=BATCH_ID)

    first = process_channel_roundtable_callback(
        batch_id=BATCH_ID,
        task_id=TASK_IDS[0],
        result=payload,
        backend=args.backend,
    )
    final = process_channel_roundtable_callback(
        batch_id=BATCH_ID,
        task_id=TASK_IDS[1],
        result=payload,
        backend=args.backend,
        requester_session_key="agent:main:discord:channel:1483883339701158102",
    )

    result = {
        "backend": args.backend,
        "payload_path": str(output_root / "payload.json"),
        "first_callback": first,
        "final_callback": final,
        "summary_path": final["summary_path"],
        "decision_path": final["decision_path"],
        "dispatch_path": final["dispatch_path"],
    }
    result_path = output_root / "run_result.json"
    result_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
