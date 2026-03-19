from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .poc_runner import SubagentBridgeSimulator


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_callback_events(path: Optional[Path]) -> Optional[List[Dict[str, Any]]]:
    if path is None:
        return None

    payload = load_json(path)
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        events = payload.get("events")
        if isinstance(events, list):
            return events
    raise ValueError("callback input must be a JSON array or an object with an 'events' array")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the repo-local subagent bridge simulator")
    parser.add_argument(
        "--spawn-input",
        type=Path,
        default=Path("poc/subagent_bridge_sim/inputs/spawn-request.json"),
        help="sample spawn request json",
    )
    parser.add_argument(
        "--terminal-input",
        type=Path,
        default=Path("poc/subagent_bridge_sim/inputs/terminal-event.json"),
        help="sample terminal event json",
    )
    parser.add_argument(
        "--callback-input",
        type=Path,
        default=None,
        help="optional callback event sequence json (array or {\"events\": [...]})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("poc/subagent_bridge_sim/demo-run"),
        help="directory where runtime/ and output/ files will be written",
    )
    parser.add_argument(
        "--await-timeout-ms",
        type=int,
        default=1000,
        help="timeout for await_terminal in milliseconds",
    )
    args = parser.parse_args()

    simulator = SubagentBridgeSimulator(args.output_dir)
    result = simulator.run_simulation(
        load_json(args.spawn_input),
        load_json(args.terminal_input),
        callback_events=load_callback_events(args.callback_input),
        await_timeout_ms=args.await_timeout_ms,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
