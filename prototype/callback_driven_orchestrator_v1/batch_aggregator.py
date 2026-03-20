#!/usr/bin/env python3
"""
Fan-in 汇总层 v1 — 监听多个子任务的 completion 事件，按 batch_id 汇总。

同步来源：orchestrator @ 64da26e
仅做 proposal repo 内的最小同步与 import 适配。
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from .state_machine import (
        TaskState,
        STATE_DIR,
        _ensure_state_dir,
        _iso_now,
        get_batch_summary,
        get_batch_summary_content,
        get_batch_tasks,
        is_batch_complete,
        write_batch_summary,
    )
except ImportError:
    from state_machine import (  # type: ignore
        TaskState,
        STATE_DIR,
        _ensure_state_dir,
        _iso_now,
        get_batch_summary,
        get_batch_summary_content,
        get_batch_tasks,
        is_batch_complete,
        write_batch_summary,
    )


def _batch_summary_file(batch_id: str) -> Path:
    """返回 batch 汇总文件路径"""
    return STATE_DIR / f"batch-{batch_id}-summary.md"


def analyze_batch_results(batch_id: str) -> Dict[str, Any]:
    """分析批次任务结果，提取共同模式和 blocker"""
    tasks = get_batch_tasks(batch_id)

    if not tasks:
        return {"error": "No tasks found for batch"}

    success_tasks = []
    failed_tasks = []
    timeout_tasks = []

    for task in tasks:
        current_state = task.get("state")
        if current_state in (TaskState.CALLBACK_RECEIVED.value, TaskState.FINAL_CLOSED.value):
            success_tasks.append(task)
        elif current_state == TaskState.FAILED.value:
            failed_tasks.append(task)
        elif current_state == TaskState.TIMEOUT.value:
            timeout_tasks.append(task)

    common_blockers = []
    error_patterns: Dict[str, int] = {}

    for task in failed_tasks + timeout_tasks:
        result = task.get("result", {})
        if result:
            error = result.get("error", "unknown")
            error_patterns[error] = error_patterns.get(error, 0) + 1

    for error, count in error_patterns.items():
        if count >= 2:
            common_blockers.append(
                {
                    "error": error,
                    "count": count,
                    "affected_tasks": [
                        t["task_id"]
                        for t in failed_tasks + timeout_tasks
                        if t.get("result", {}).get("error") == error
                    ],
                }
            )

    success_patterns = []
    for task in success_tasks:
        result = task.get("result", {})
        if result and "verdict" in result:
            success_patterns.append(
                {
                    "task_id": task["task_id"],
                    "verdict": result.get("verdict"),
                }
            )

    return {
        "batch_id": batch_id,
        "total": len(tasks),
        "success": len(success_tasks),
        "failed": len(failed_tasks),
        "timeout": len(timeout_tasks),
        "success_rate": len(success_tasks) / len(tasks) if tasks else 0,
        "common_blockers": common_blockers,
        "success_patterns": success_patterns,
        "is_complete": is_batch_complete(batch_id),
    }


def generate_batch_summary_md(
    batch_id: str,
    analysis: Optional[Dict[str, Any]] = None,
) -> str:
    """生成批次汇总报告（Markdown 格式）"""
    if analysis is None:
        analysis = analyze_batch_results(batch_id)

    summary = get_batch_summary(batch_id)

    lines = [
        f"# Batch {batch_id} Summary",
        "",
        f"**Generated**: {_iso_now()}",
        f"**Status**: {'COMPLETE' if summary['complete'] else 'IN_PROGRESS'}",
        "",
        "## 完成状态",
        "",
        f"- **总计**: {summary['total']}",
        f"- **成功**: {summary['callback_received'] + summary['final_closed']}",
        f"- **失败**: {summary['failed']}",
        f"- **超时**: {summary['timeout']}",
        f"- **进行中**: {summary['pending'] + summary['running']}",
        (
            f"- **成功率**: {'{:.1%}'.format(analysis.get('success_rate', 0))}"
            if summary["complete"]
            else "- **成功率**: N/A"
        ),
        "",
    ]

    lines.append("## 任务列表")
    lines.append("")
    lines.append("| Task ID | State | Dispatched At | Completed At |")
    lines.append("|---------|-------|---------------|--------------|")

    tasks = get_batch_tasks(batch_id)
    for task in sorted(tasks, key=lambda item: item.get("dispatched_at", "")):
        task_id = task.get("task_id", "unknown")[:20]
        current_state = task.get("state", "unknown")
        dispatched = task.get("dispatched_at", "N/A")[:19]
        completed = task.get("completed_at") or task.get("callback_received_at") or "N/A"
        if completed != "N/A":
            completed = completed[:19]
        lines.append(f"| {task_id} | {current_state} | {dispatched} | {completed} |")

    lines.append("")

    if analysis.get("common_blockers"):
        lines.append("## 共同 Blocker")
        lines.append("")
        for blocker in analysis["common_blockers"]:
            lines.append(f"- **{blocker['error']}** (影响 {blocker['count']} 个任务)")
            lines.append(f"  - 任务：{', '.join(t[:20] for t in blocker['affected_tasks'])}")
        lines.append("")

    if analysis.get("success_patterns"):
        lines.append("## 成功模式")
        lines.append("")
        for pattern in analysis["success_patterns"]:
            lines.append(f"- {pattern['task_id']}: verdict={pattern.get('verdict', 'N/A')}")
        lines.append("")

    lines.append("## 建议下一轮动作")
    lines.append("")

    if not summary["complete"]:
        lines.append("- **等待**: 批次尚未完成，继续等待剩余任务")
    elif analysis.get("success_rate", 0) == 1.0:
        lines.append("- **推进**: 所有任务成功，可进入下一阶段")
    elif analysis.get("success_rate", 0) >= 0.5:
        lines.append("- **部分推进**: 大部分任务成功，建议针对失败任务重试或修复")
    else:
        lines.append("- **审查**: 成功率过低，建议先审查失败原因再决定下一步")

    lines.append("")
    lines.append("---")
    lines.append("*End of Summary*")

    return "\n".join(lines)


def check_and_summarize_batch(batch_id: str, force: bool = False) -> Optional[str]:
    """检查批次是否完成，如果完成则生成汇总报告"""
    _ensure_state_dir()

    complete = is_batch_complete(batch_id)
    if not complete and not force:
        return None

    existing = get_batch_summary_content(batch_id)
    if existing and not force:
        return existing

    analysis = analyze_batch_results(batch_id)
    content = generate_batch_summary_md(batch_id, analysis)
    write_batch_summary(batch_id, content)

    return content


def get_batches_by_state(state: str = "in_progress") -> List[str]:
    """获取指定状态的批次列表"""
    _ensure_state_dir()

    batch_ids = set()
    for task_file in STATE_DIR.glob("tsk_*.json"):
        with open(task_file, "r", encoding="utf-8") as f:
            task = json.load(f)
        batch_id = task.get("batch_id")
        if batch_id:
            batch_ids.add(batch_id)

    if state == "all":
        return list(batch_ids)

    result = []
    for batch_id in batch_ids:
        complete = is_batch_complete(batch_id)
        if state == "complete" and complete:
            result.append(batch_id)
        elif state == "in_progress" and not complete:
            result.append(batch_id)

    return result


def detect_stuck_batches(timeout_minutes: int = 60) -> List[Dict[str, Any]]:
    """检测可能卡住的批次（超过超时阈值但没有进展）"""
    _ensure_state_dir()

    stuck = []
    now = datetime.now()
    threshold = now - timedelta(minutes=timeout_minutes)

    batch_ids = set()
    for task_file in STATE_DIR.glob("tsk_*.json"):
        with open(task_file, "r", encoding="utf-8") as f:
            task = json.load(f)
        batch_id = task.get("batch_id")
        if batch_id:
            batch_ids.add(batch_id)

    for batch_id in batch_ids:
        tasks = get_batch_tasks(batch_id)
        if not tasks:
            continue

        for task in tasks:
            dispatched = task.get("dispatched_at")
            if not dispatched:
                continue

            try:
                dispatched_time = datetime.fromisoformat(dispatched)
            except ValueError:
                continue

            current_state = task.get("state")
            terminal_states = {
                TaskState.FINAL_CLOSED.value,
                TaskState.TIMEOUT.value,
                TaskState.FAILED.value,
            }

            if current_state not in terminal_states and dispatched_time < threshold:
                stuck.append(
                    {
                        "batch_id": batch_id,
                        "task_id": task["task_id"],
                        "state": current_state,
                        "dispatched_at": dispatched,
                        "stuck_minutes": (now - dispatched_time).total_seconds() / 60,
                    }
                )
                break

    return stuck


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python batch_aggregator.py check <batch_id>")
        print("  python batch_aggregator.py summarize <batch_id> [--force]")
        print("  python batch_aggregator.py list [--state in_progress|complete|all]")
        print("  python batch_aggregator.py stuck [--timeout <minutes>]")
        print("  python batch_aggregator.py analyze <batch_id>")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "check":
        batch_id = sys.argv[2]
        result = check_and_summarize_batch(batch_id)
        if result:
            print("Batch is complete. Summary generated:")
            print(result)
        else:
            print("Batch is still in progress.")

    elif cmd == "summarize":
        batch_id = sys.argv[2]
        force = "--force" in sys.argv
        result = check_and_summarize_batch(batch_id, force=force)
        if result:
            print(result)
        else:
            print("Batch is still in progress (use --force to generate anyway).")

    elif cmd == "list":
        selected_state = "in_progress"
        if "--state" in sys.argv:
            idx = sys.argv.index("--state")
            if idx + 1 < len(sys.argv):
                selected_state = sys.argv[idx + 1]
        batches = get_batches_by_state(selected_state)
        print(f"Batches ({selected_state}):")
        for batch_id in sorted(batches):
            print(f"  - {batch_id}")

    elif cmd == "stuck":
        timeout = 60
        if "--timeout" in sys.argv:
            idx = sys.argv.index("--timeout")
            if idx + 1 < len(sys.argv):
                timeout = int(sys.argv[idx + 1])
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

    elif cmd == "analyze":
        batch_id = sys.argv[2]
        result = analyze_batch_results(batch_id)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
