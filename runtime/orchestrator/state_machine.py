#!/usr/bin/env python3
"""
任务状态机 v1 — 统一跟踪任务生命周期

状态流转：
  pending → running → callback_received → next_task_dispatched → final_closed
                              ↓
                         timeout/failed → (retry or abort)
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from enum import Enum


class TaskState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    CALLBACK_RECEIVED = "callback_received"
    NEXT_TASK_DISPATCHED = "next_task_dispatched"
    FINAL_CLOSED = "final_closed"
    TIMEOUT = "timeout"
    FAILED = "failed"
    RETRYING = "retrying"


# 状态存储目录
STATE_DIR = Path(os.environ.get("OPENCLAW_STATE_DIR", 
               Path.home() / ".openclaw" / "shared-context" / "job-status"))


def _ensure_state_dir():
    """确保状态目录存在"""
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def _task_file(task_id: str) -> Path:
    """返回任务状态文件路径"""
    return STATE_DIR / f"{task_id}.json"


def _batch_file(batch_id: str) -> Path:
    """返回 batch 汇总文件路径"""
    return STATE_DIR / f"batch-{batch_id}-summary.md"


def _iso_now() -> str:
    """返回当前 ISO-8601 时间戳"""
    return datetime.now().isoformat()


def create_task(
    task_id: str,
    batch_id: Optional[str] = None,
    timeout_seconds: int = 3600,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    创建新任务状态记录
    
    Args:
        task_id: 任务 ID
        batch_id: 可选的批次 ID（用于批量任务汇总）
        timeout_seconds: 超时阈值（秒）
        metadata: 额外元数据
    
    Returns:
        任务状态字典
    """
    _ensure_state_dir()
    
    state = {
        "task_id": task_id,
        "batch_id": batch_id,
        "state": TaskState.PENDING.value,
        "dispatched_at": _iso_now(),
        "callback_received_at": None,
        "completed_at": None,
        "result": None,
        "next_task_ids": [],
        "retry_count": 0,
        "timeout_seconds": timeout_seconds,
        "metadata": metadata or {},
    }
    
    # 原子写入
    tmp_file = _task_file(task_id).with_suffix(".tmp")
    with open(tmp_file, "w") as f:
        json.dump(state, f, indent=2)
    tmp_file.replace(_task_file(task_id))
    
    return state


def update_state(
    task_id: str,
    new_state: TaskState,
    result: Optional[Dict[str, Any]] = None,
    next_task_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    更新任务状态
    
    Args:
        task_id: 任务 ID
        new_state: 新状态
        result: 任务执行结果（可选）
        next_task_ids: 下一轮任务 ID 列表（可选）
    
    Returns:
        更新后的任务状态字典
    """
    _ensure_state_dir()
    
    task_file = _task_file(task_id)
    if not task_file.exists():
        raise FileNotFoundError(f"Task {task_id} not found")
    
    with open(task_file, "r") as f:
        state = json.load(f)
    
    state["state"] = new_state.value
    
    if result is not None:
        state["result"] = result
    
    if next_task_ids is not None:
        state["next_task_ids"] = next_task_ids
    
    if new_state == TaskState.CALLBACK_RECEIVED:
        state["callback_received_at"] = _iso_now()
    elif new_state in (TaskState.FINAL_CLOSED, TaskState.TIMEOUT, TaskState.FAILED):
        state["completed_at"] = _iso_now()
    
    # 原子写入
    tmp_file = task_file.with_suffix(".tmp")
    with open(tmp_file, "w") as f:
        json.dump(state, f, indent=2)
    tmp_file.replace(task_file)
    
    return state


def get_state(task_id: str) -> Optional[Dict[str, Any]]:
    """
    获取任务状态
    
    Args:
        task_id: 任务 ID
    
    Returns:
        任务状态字典，不存在则返回 None
    """
    task_file = _task_file(task_id)
    if not task_file.exists():
        return None
    
    with open(task_file, "r") as f:
        return json.load(f)


def list_tasks(
    batch_id: Optional[str] = None,
    state: Optional[TaskState] = None,
) -> List[Dict[str, Any]]:
    """
    列出任务
    
    Args:
        batch_id: 可选的批次 ID 过滤
        state: 可选的状态过滤
    
    Returns:
        任务状态列表
    """
    _ensure_state_dir()
    
    tasks = []
    for task_file in STATE_DIR.glob("*.json"):
        if task_file.name.startswith("batch-"):
            continue
        try:
            with open(task_file, "r") as f:
                task = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        if "task_id" not in task:
            continue

        if batch_id is not None and task.get("batch_id") != batch_id:
            continue
        if state is not None and task.get("state") != state.value:
            continue
        
        tasks.append(task)
    
    return tasks


def get_batch_tasks(batch_id: str) -> List[Dict[str, Any]]:
    """
    获取批次下所有任务
    
    Args:
        batch_id: 批次 ID
    
    Returns:
        任务状态列表
    """
    return list_tasks(batch_id=batch_id)


def is_batch_complete(batch_id: str) -> bool:
    """
    检查批次是否完成（所有任务都进入终态）
    
    终态包括：CALLBACK_RECEIVED, FINAL_CLOSED, TIMEOUT, FAILED
    
    Args:
        batch_id: 批次 ID
    
    Returns:
        True 如果所有任务都进入终态
    """
    tasks = get_batch_tasks(batch_id)
    if not tasks:
        return False
    
    terminal_states = {
        TaskState.CALLBACK_RECEIVED.value,
        TaskState.FINAL_CLOSED.value,
        TaskState.TIMEOUT.value,
        TaskState.FAILED.value,
    }
    
    return all(task["state"] in terminal_states for task in tasks)


def get_batch_summary(batch_id: str) -> Dict[str, Any]:
    """
    获取批次汇总统计
    
    Args:
        batch_id: 批次 ID
    
    Returns:
        汇总统计字典
    """
    tasks = get_batch_tasks(batch_id)
    
    summary = {
        "batch_id": batch_id,
        "total": len(tasks),
        "pending": 0,
        "running": 0,
        "callback_received": 0,
        "final_closed": 0,
        "timeout": 0,
        "failed": 0,
        "retrying": 0,
    }
    
    for task in tasks:
        state = task.get("state", "unknown")
        if state in summary:
            summary[state] += 1
    
    summary["complete"] = is_batch_complete(batch_id)
    
    return summary


def write_batch_summary(batch_id: str, content: str):
    """
    写入批次汇总报告（Markdown）
    
    Args:
        batch_id: 批次 ID
        content: Markdown 内容
    """
    _ensure_state_dir()
    
    summary_file = _batch_file(batch_id)
    with open(summary_file, "w") as f:
        f.write(content)


def get_batch_summary_content(batch_id: str) -> Optional[str]:
    """
    读取批次汇总报告
    
    Args:
        batch_id: 批次 ID
    
    Returns:
        Markdown 内容，不存在则返回 None
    """
    summary_file = _batch_file(batch_id)
    if not summary_file.exists():
        return None
    
    with open(summary_file, "r") as f:
        return f.read()


def mark_timeout(task_id: str) -> Dict[str, Any]:
    """标记任务超时"""
    return update_state(task_id, TaskState.TIMEOUT)


def mark_failed(task_id: str, error: Optional[str] = None) -> Dict[str, Any]:
    """标记任务失败"""
    return update_state(task_id, TaskState.FAILED, result={"error": error})


def mark_callback_received(
    task_id: str,
    result: Dict[str, Any],
) -> Dict[str, Any]:
    """标记收到回调"""
    return update_state(task_id, TaskState.CALLBACK_RECEIVED, result=result)


def mark_next_dispatched(
    task_id: str,
    next_task_ids: List[str],
) -> Dict[str, Any]:
    """标记下一轮任务已派发"""
    return update_state(
        task_id,
        TaskState.NEXT_TASK_DISPATCHED,
        next_task_ids=next_task_ids,
    )


def mark_final_closed(task_id: str) -> Dict[str, Any]:
    """标记任务最终关闭"""
    return update_state(task_id, TaskState.FINAL_CLOSED)


def retry_task(task_id: str) -> Dict[str, Any]:
    """
    重试任务（增加 retry_count，状态回到 pending）
    
    Args:
        task_id: 任务 ID
    
    Returns:
        更新后的任务状态
    """
    _ensure_state_dir()
    
    task_file = _task_file(task_id)
    if not task_file.exists():
        raise FileNotFoundError(f"Task {task_id} not found")
    
    with open(task_file, "r") as f:
        state = json.load(f)
    
    state["state"] = TaskState.RETRYING.value
    state["retry_count"] = state.get("retry_count", 0) + 1
    state["completed_at"] = None
    
    # 原子写入
    tmp_file = task_file.with_suffix(".tmp")
    with open(tmp_file, "w") as f:
        json.dump(state, f, indent=2)
    tmp_file.replace(task_file)
    
    # 回到 pending
    return update_state(task_id, TaskState.PENDING)


# CLI 入口
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python state_machine.py create <task_id> [--batch <batch_id>]")
        print("  python state_machine.py get <task_id>")
        print("  python state_machine.py update <task_id> <state>")
        print("  python state_machine.py list [--batch <batch_id>] [--state <state>]")
        print("  python state_machine.py batch-summary <batch_id>")
        print("  python state_machine.py is-batch-complete <batch_id>")
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == "create":
        task_id = sys.argv[2]
        batch_id = None
        if "--batch" in sys.argv:
            idx = sys.argv.index("--batch")
            if idx + 1 < len(sys.argv):
                batch_id = sys.argv[idx + 1]
        result = create_task(task_id, batch_id=batch_id)
        print(json.dumps(result, indent=2))
    
    elif cmd == "get":
        task_id = sys.argv[2]
        result = get_state(task_id)
        if result:
            print(json.dumps(result, indent=2))
        else:
            print(f"Task {task_id} not found")
            sys.exit(1)
    
    elif cmd == "update":
        task_id = sys.argv[2]
        new_state = sys.argv[3]
        try:
            state = TaskState(new_state)
            result = update_state(task_id, state)
            print(json.dumps(result, indent=2))
        except ValueError as e:
            print(f"Invalid state: {new_state}")
            sys.exit(1)
    
    elif cmd == "list":
        batch_id = None
        state_filter = None
        if "--batch" in sys.argv:
            idx = sys.argv.index("--batch")
            if idx + 1 < len(sys.argv):
                batch_id = sys.argv[idx + 1]
        if "--state" in sys.argv:
            idx = sys.argv.index("--state")
            if idx + 1 < len(sys.argv):
                state_filter = TaskState(sys.argv[idx + 1])
        results = list_tasks(batch_id=batch_id, state=state_filter)
        print(json.dumps(results, indent=2))
    
    elif cmd == "batch-summary":
        batch_id = sys.argv[2]
        result = get_batch_summary(batch_id)
        print(json.dumps(result, indent=2))
    
    elif cmd == "is-batch-complete":
        batch_id = sys.argv[2]
        result = is_batch_complete(batch_id)
        print("true" if result else "false")
    
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
