from __future__ import annotations

import argparse
import json
from pathlib import Path

from .poc_runner import PocRunner


ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT_ROOT = ROOT / "runs"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行 Lobster 最小验证 POC")
    parser.add_argument("workflow", choices=["chain", "human-gate", "failure-branch"])
    parser.add_argument("--input", required=True, help="输入 JSON 文件")
    parser.add_argument("--output-dir", help="输出目录；默认写到 poc/lobster_minimal_validation/runs/<workflow>")
    parser.add_argument("--decision-file", help="human-gate 场景的统一 decision payload JSON 文件")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_path = Path(args.input)
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    output_dir = Path(args.output_dir) if args.output_dir else DEFAULT_OUTPUT_ROOT / args.workflow

    runner = PocRunner(output_dir=output_dir)
    if args.workflow == "chain":
        result = runner.run_chain(payload)
    elif args.workflow == "human-gate":
        if not args.decision_file:
            raise SystemExit("human-gate 必须显式传 --decision-file <path>")
        decision_path = Path(args.decision_file)
        decision_payload = json.loads(decision_path.read_text(encoding="utf-8"))
        result = runner.run_human_gate(payload, decision_payload=decision_payload)
    else:
        result = runner.run_failure_branch(payload)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
