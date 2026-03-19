from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent.parent
DEFAULT_OUTPUT_ROOT = ROOT / "runs"
DEFAULT_WORKFLOW = ROOT / "workflows" / "chain-basic.lobster"
DEFAULT_LOCAL_BIN = ROOT / "node_modules" / ".bin" / "lobster"
CANONICAL_ENTRY = "python3 poc/official_lobster_bridge/run_official.py chain-basic --input poc/official_lobster_bridge/inputs/chain-basic.args.json"
FALLBACK_ENTRY = "python3 -m poc.lobster_minimal_validation.run_poc chain --input poc/lobster_minimal_validation/inputs/chain-basic.json"


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
            "mode": "official",
            "bin": run_result["bin"],
            "workflow_file": run_result["workflow_file"],
            "envelope_status": run_result["envelope"].get("status"),
            "canonical_entry": CANONICAL_ENTRY,
            "fallback_entry": FALLBACK_ENTRY,
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
            "fallback": False,
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


def build_poc_fallback_artifacts(
    payload: Dict[str, Any],
    output_dir: Path,
    reason: str,
    workflow_file: Path,
    requested_lobster_bin: Optional[str],
    source_input: Path,
) -> Dict[str, Any]:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    from poc.lobster_minimal_validation.poc_runner import PocRunner

    runner = PocRunner(output_dir=output_dir)
    result = runner.run_chain(payload)
    registry = result["registry"]
    callback = result["callback"]

    registry.setdefault("evidence", {})
    registry["evidence"]["official_runtime"] = {
        "mode": "fallback-poc",
        "requested_bin": requested_lobster_bin,
        "workflow_file": str(workflow_file),
        "error": reason,
        "canonical_entry": CANONICAL_ENTRY,
        "fallback_entry": FALLBACK_ENTRY,
    }
    callback.setdefault("summary", {})
    callback["summary"]["runtime"] = "legacy-poc-fallback"
    callback["summary"]["fallback"] = True
    callback["summary"].setdefault("evidence_keys", ["input", "step_a", "step_b"])
    if "official_runtime" not in callback["summary"]["evidence_keys"]:
        callback["summary"]["evidence_keys"].append("official_runtime")

    artifacts = {
        "registry": registry,
        "callback": callback,
        "lobster-envelope": {
            "ok": False,
            "status": "fallback",
            "source": "legacy-poc-harness",
            "error": reason,
        },
        "lobster-command": {
            "argv": [
                "python3",
                "-m",
                "poc.lobster_minimal_validation.run_poc",
                "chain",
                "--input",
                str(source_input),
            ]
        },
    }
    persist_artifacts(output_dir, artifacts)
    artifacts["output_dir"] = str(output_dir)
    return artifacts


def persist_artifacts(output_dir: Path, artifacts: Dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, payload in artifacts.items():
        if name == "output_dir":
            continue
        if name == "lobster-command" and isinstance(payload, dict) and "argv" in payload:
            text = json.dumps(payload, ensure_ascii=False, indent=2)
        elif name == "lobster-command":
            text = json.dumps({"argv": payload}, ensure_ascii=False, indent=2)
        else:
            text = json.dumps(payload, ensure_ascii=False, indent=2)
        (output_dir / f"{name}.json").write_text(text + "\n", encoding="utf-8")


def run_chain_basic(
    input_file: Path,
    output_dir: Optional[Path] = None,
    workflow_file: Path = DEFAULT_WORKFLOW,
    lobster_bin: Optional[str] = None,
    fallback_to_poc: bool = False,
) -> Dict[str, Any]:
    payload = load_json(input_file)
    final_output_dir = output_dir or (DEFAULT_OUTPUT_ROOT / "chain-basic")

    try:
        run_result = run_lobster_workflow(payload, workflow_file=workflow_file, lobster_bin=lobster_bin)
    except OfficialLobsterRunnerError as exc:
        if not fallback_to_poc:
            raise
        return build_poc_fallback_artifacts(
            payload=payload,
            output_dir=final_output_dir,
            reason=str(exc),
            workflow_file=workflow_file,
            requested_lobster_bin=lobster_bin or str(DEFAULT_LOCAL_BIN),
            source_input=input_file,
        )

    artifacts = build_chain_basic_artifacts(payload, run_result)
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
    parser.add_argument(
        "--fallback-to-poc",
        action="store_true",
        help="当官方 runtime 不可用时，回退到旧的 poc.lobster_minimal_validation chain harness",
    )
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
        fallback_to_poc=args.fallback_to_poc,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "workflow": args.workflow,
                "output_dir": artifacts["output_dir"],
                "callback": artifacts["callback"],
                "mode": artifacts["callback"]["summary"].get("runtime"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
