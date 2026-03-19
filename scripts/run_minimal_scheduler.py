from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from orchestration_runtime import (
    DispatchResult,
    FileTaskRegistry,
    WorkflowDispatcher,
    await_terminal_handler,
    callback_send_once_handler,
    init_registry_handler,
    inline_payload_handler,
    load_json_file,
    write_json_atomic,
)


def build_dispatcher(run_dir: Path) -> WorkflowDispatcher:
    registry = FileTaskRegistry(run_dir / "runtime")
    handlers = {
        "control.init_registry": init_registry_handler,
        "control.inline_payload": inline_payload_handler,
        "subagent.await_terminal": await_terminal_handler,
        "callback.send_once": callback_send_once_handler,
    }
    return WorkflowDispatcher(registry=registry, step_handlers=handlers)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行最小 scheduler/dispatcher sample runner")
    parser.add_argument("--workflow", required=True, help="workflow definition JSON 文件")
    parser.add_argument("--input", required=True, help="请求输入 JSON 文件")
    parser.add_argument("--run-dir", required=True, help="运行目录，会在其下写 runtime/tasks/<task_id>.json")
    parser.add_argument("--signal", help="可选 resume signal JSON 文件")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    workflow = load_json_file(Path(args.workflow))
    request = load_json_file(Path(args.input))
    signal = load_json_file(Path(args.signal)) if args.signal else None
    task_id = str(request["task_id"])
    run_dir = Path(args.run_dir)

    dispatcher = build_dispatcher(run_dir)
    result = dispatcher.dispatch(workflow, task_id=task_id, request=request, signal=signal)
    persist_result(run_dir, result)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


def persist_result(run_dir: Path, result: DispatchResult) -> None:
    write_json_atomic(run_dir / "dispatch-result.json", result.to_dict())
    callback_payload = result.record.get("evidence", {}).get("callback", {}).get("last_payload")
    if isinstance(callback_payload, dict):
        write_json_atomic(run_dir / "callback.json", callback_payload)


if __name__ == "__main__":
    main()
