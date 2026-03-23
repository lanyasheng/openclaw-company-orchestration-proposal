#!/usr/bin/env python3
"""
编排器 CLI 入口。

Usage:
  orchestrator-cli status <task_id>
  orchestrator-cli batch-summary <batch_id>
  orchestrator-cli decide <batch_id>
  orchestrator-cli list [--state <state>]
  orchestrator-cli stuck [--timeout <minutes>]
  orchestrator-cli test
"""

import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from batch_aggregator import check_and_summarize_batch, detect_stuck_batches  # noqa: E402
from orchestrator import create_default_orchestrator  # noqa: E402
from state_machine import get_batch_summary, get_state, is_batch_complete, list_tasks  # noqa: E402


def cmd_status(task_id: str):
    """查询任务状态"""
    state = get_state(task_id)
    if state:
        print(f"Task: {state['task_id']}")
        print(f"State: {state['state']}")
        print(f"Batch: {state.get('batch_id', 'N/A')}")
        print(f"Dispatched: {state.get('dispatched_at', 'N/A')}")
        print(
            "Completed: "
            f"{state.get('completed_at') or state.get('callback_received_at') or 'N/A'}"
        )
        if state.get("result"):
            print(f"Result: {state['result']}")
    else:
        print(f"Task {task_id} not found")
        sys.exit(1)


def cmd_batch_summary(batch_id: str):
    """查询批次汇总"""
    check_and_summarize_batch(batch_id, force=True)

    summary = get_batch_summary(batch_id)
    print(f"Batch: {batch_id}")
    print(f"Complete: {summary['complete']}")
    print(f"Total: {summary['total']}")
    print(f"Success: {summary['callback_received'] + summary['final_closed']}")
    print(f"Failed: {summary['failed']}")
    print(f"Timeout: {summary['timeout']}")
    print(f"Running: {summary['running']}")
    print(f"Pending: {summary['pending']}")

    print("\n--- Summary Report ---")
    content = check_and_summarize_batch(batch_id)
    if content:
        print(content)


def cmd_decide(batch_id: str):
    """对批次做出决策"""
    orch = create_default_orchestrator()
    decision = orch.decide(batch_id)

    if decision:
        print(f"Decision: {decision.action}")
        print(f"Reason: {decision.reason}")
        if decision.next_tasks:
            print(f"Next tasks: {len(decision.next_tasks)}")
            for index, task in enumerate(decision.next_tasks, start=1):
                print(f"  {index}. {task}")
        if decision.metadata:
            print(f"Metadata: {decision.metadata}")
    else:
        print("No decision made (no rules matched).")


def cmd_list(state_filter: str = "all"):
    """列出任务"""
    from state_machine import TaskState

    state = None
    if state_filter != "all":
        try:
            state = TaskState(state_filter)
        except ValueError:
            print(f"Invalid state: {state_filter}")
            sys.exit(1)

    tasks = list_tasks(state=state)

    batches = {}
    for task in tasks:
        batch_id = task.get("batch_id") or "no-batch"
        batches.setdefault(batch_id, []).append(task)

    print(f"Tasks ({len(tasks)} total, {len(batches)} batches):")
    for batch_id in sorted(batches.keys()):
        batch_tasks = batches[batch_id]
        complete = is_batch_complete(batch_id) if batch_id != "no-batch" else "N/A"
        print(f"\n  Batch: {batch_id} (complete={complete})")
        for task in sorted(batch_tasks, key=lambda item: item.get("dispatched_at", "")):
            print(f"    - {task['task_id']}: {task['state']}")


def cmd_stuck(timeout: int = 60):
    """检测卡住的批次"""
    stuck = detect_stuck_batches(timeout_minutes=timeout)

    if stuck:
        print(f"Stuck batches (>{timeout}min):")
        for item in stuck:
            print(
                f"  - Batch {item['batch_id']}: {item['task_id']} "
                f"(state={item['state']}, stuck={item['stuck_minutes']:.1f}min)"
            )
    else:
        print(f"No stuck batches (>{timeout}min).")


def cmd_test():
    """运行最小自检"""
    print("Running orchestrator tests...")

    from state_machine import create_task, mark_callback_received

    batch_id = "test_batch_001"

    print(f"\n1. Creating test batch: {batch_id}")
    task_ids = []
    for i in range(3):
        task_id = f"tsk_test_{i:03d}"
        create_task(task_id, batch_id=batch_id, timeout_seconds=60)
        task_ids.append(task_id)
        print(f"   Created: {task_id}")

    print("\n2. Listing tasks...")
    cmd_list("all")

    print("\n3. Marking tasks as complete...")
    for i, task_id in enumerate(task_ids):
        mark_callback_received(task_id, {"verdict": "PASS" if i < 2 else "FAIL"})
        print(f"   Callback received: {task_id}")

    print("\n4. Checking batch summary...")
    cmd_batch_summary(batch_id)

    print("\n5. Making decision...")
    cmd_decide(batch_id)

    print("\n6. Detecting stuck batches...")
    cmd_stuck(60)

    print("\n✅ Tests completed!")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "status":
        if len(sys.argv) < 3:
            print("Usage: orchestrator-cli status <task_id>")
            sys.exit(1)
        cmd_status(sys.argv[2])

    elif cmd == "batch-summary":
        if len(sys.argv) < 3:
            print("Usage: orchestrator-cli batch-summary <batch_id>")
            sys.exit(1)
        cmd_batch_summary(sys.argv[2])

    elif cmd == "decide":
        if len(sys.argv) < 3:
            print("Usage: orchestrator-cli decide <batch_id>")
            sys.exit(1)
        cmd_decide(sys.argv[2])

    elif cmd == "list":
        state = "all"
        if "--state" in sys.argv:
            idx = sys.argv.index("--state")
            if idx + 1 < len(sys.argv):
                state = sys.argv[idx + 1]
        cmd_list(state)

    elif cmd == "stuck":
        timeout = 60
        if "--timeout" in sys.argv:
            idx = sys.argv.index("--timeout")
            if idx + 1 < len(sys.argv):
                timeout = int(sys.argv[idx + 1])
        cmd_stuck(timeout)

    elif cmd == "test":
        cmd_test()

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
