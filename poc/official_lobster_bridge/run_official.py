from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT_ROOT = ROOT / "runs"
DEFAULT_WORKFLOW = ROOT / "workflows" / "chain-basic.lobster"
DEFAULT_LOCAL_BIN = ROOT / "node_modules" / ".bin" / "lobster"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TaskRegistry:
    task_id: str
    owner: str = "zoe"
    runtime: str = "lobster"
    state: str = "queued"
    callback_status: str = "pending"
    evidence: Dict[str, Any] = field(default_factory=dict)
    state_history: List[Dict[str, str]] = field(default_factory=list)

    def transition(self, state: str, runtime: Optional[str] = None, note: Optional[str] = None) -> None:
        self.state = state
        if runtime:
            self.runtime = runtime
        entry = {"state": state, "runtime": self.runtime, "at": now_iso()}
        if note:
            entry["note"] = note
        self.state_history.append(entry)

    def add_evidence(self, key: str, value: Any) -> None:
        self.evidence[key] = value

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "owner": self.owner,
            "runtime": self.runtime,
            "state": self.state,
            "callback_status": self.callback_status,
            "evidence": self.evidence,
            "state_history": self.state_history,
        }


class OfficialLobsterRunnerError(RuntimeError):
    pass


def resolve_lobster_bin(explicit: Optional[str] = None) -> str:
    candidates: List[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    candidates.append(DEFAULT_LOCAL_BIN)

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    system_bin = shutil.which("lobster")
    if system_bin:
        return system_bin

    raise OfficialLobsterRunnerError(
        "未找到 lobster 可执行文件。请先在 poc/official_lobster_bridge 下执行 npm install，"
        "或通过 --lobster-bin 显式传入路径。"
    )


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def run_lobster_workflow(
    payload: Dict[str, Any],
    workflow_file: Path = DEFAULT_WORKFLOW,
    lobster_bin: Optional[str] = None,
) -> Dict[str, Any]:
    resolved_bin = resolve_lobster_bin(lobster_bin)
    args_json = json.dumps(
        {
            "topic": payload["topic"],
            "target": payload["target"],
        },
        ensure_ascii=False,
    )
    cmd = [
        resolved_bin,
        "run",
        "--mode",
        "tool",
        "--file",
        str(workflow_file),
        "--args-json",
        args_json,
    ]
    completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise OfficialLobsterRunnerError(
            f"官方 Lobster 执行失败(exit={completed.returncode}): {completed.stderr.strip() or completed.stdout.strip()}"
        )

    try:
        envelope = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise OfficialLobsterRunnerError(f"官方 Lobster 输出不是合法 JSON: {exc}") from exc

    if not envelope.get("ok"):
        raise OfficialLobsterRunnerError(
            f"官方 Lobster 返回非成功状态: {json.dumps(envelope, ensure_ascii=False)}"
        )

    output = envelope.get("output") or []
    if len(output) != 1 or not isinstance(output[0], dict):
        raise OfficialLobsterRunnerError(
            f"chain-basic 期望得到单个 JSON 对象输出，实际为: {json.dumps(output, ensure_ascii=False)}"
        )

    return {
        "bin": resolved_bin,
        "command": cmd,
        "workflow_file": str(workflow_file),
        "envelope": envelope,
        "result": output[0],
    }


def build_chain_basic_artifacts(payload: Dict[str, Any], run_result: Dict[str, Any]) -> Dict[str, Any]:
    final_output = run_result["result"]
    registry = TaskRegistry(task_id=payload["task_id"])
    registry.transition("queued", note="创建任务")
    registry.transition("running", runtime="lobster", note="启动 chain")
    registry.add_evidence("input", payload)
    registry.add_evidence("step_a", {"status": "ok", "topic": payload["topic"]})
    registry.add_evidence(
        "step_b",
        {
            "status": final_output.get("status", "ok"),
            "target": final_output["target"],
            "message": final_output["message"],
        },
    )
    registry.add_evidence(
        "official_runtime",
        {
            "bin": run_result["bin"],
            "workflow_file": run_result["workflow_file"],
            "envelope_status": run_result["envelope"].get("status"),
        },
    )
    registry.transition("completed", runtime="lobster", note="chain 完成")

    callback = {
        "task_id": registry.task_id,
        "result": "completed",
        "sent_at": now_iso(),
        "summary": {
            "workflow": "chain-basic",
            "ordered_steps": ["step_a", "step_b", "final_callback"],
            "evidence_keys": ["input", "step_a", "step_b", "official_runtime"],
            "runtime": "official-lobster-cli",
        },
    }
    registry.callback_status = "sent"
    registry.callback_status = "acked"

    return {
        "registry": registry.to_dict(),
        "callback": callback,
        "lobster-envelope": run_result["envelope"],
        "lobster-command": run_result["command"],
    }


def persist_artifacts(output_dir: Path, artifacts: Dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, payload in artifacts.items():
        if name == "lobster-command":
            text = json.dumps({"argv": payload}, ensure_ascii=False, indent=2)
        else:
            text = json.dumps(payload, ensure_ascii=False, indent=2)
        (output_dir / f"{name}.json").write_text(text + "\n", encoding="utf-8")


def run_chain_basic(
    input_file: Path,
    output_dir: Optional[Path] = None,
    workflow_file: Path = DEFAULT_WORKFLOW,
    lobster_bin: Optional[str] = None,
) -> Dict[str, Any]:
    payload = load_json(input_file)
    run_result = run_lobster_workflow(payload, workflow_file=workflow_file, lobster_bin=lobster_bin)
    artifacts = build_chain_basic_artifacts(payload, run_result)
    final_output_dir = output_dir or (DEFAULT_OUTPUT_ROOT / "chain-basic")
    persist_artifacts(final_output_dir, artifacts)
    artifacts["output_dir"] = str(final_output_dir)
    return artifacts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行官方 Lobster 最小 bridge")
    parser.add_argument("workflow", choices=["chain-basic"], help="当前只支持 chain-basic")
    parser.add_argument("--input", required=True, help="输入 JSON 文件")
    parser.add_argument("--output-dir", help="输出目录；默认写到 poc/official_lobster_bridge/runs/<workflow>")
    parser.add_argument("--workflow-file", default=str(DEFAULT_WORKFLOW), help="官方 Lobster workflow 文件路径")
    parser.add_argument("--lobster-bin", help="显式指定 lobster 可执行文件")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.workflow != "chain-basic":
        raise SystemExit("当前 batch1 仅实现 chain-basic")

    artifacts = run_chain_basic(
        input_file=Path(args.input),
        output_dir=Path(args.output_dir) if args.output_dir else None,
        workflow_file=Path(args.workflow_file),
        lobster_bin=args.lobster_bin,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "workflow": args.workflow,
                "output_dir": artifacts["output_dir"],
                "callback": artifacts["callback"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
