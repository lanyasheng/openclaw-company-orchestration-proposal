#!/usr/bin/env python3
"""
编排器 CLI — 唯一入口

DAG 工作流命令:
  orchestrator-cli plan <description> <config.json>   创建工作流
  orchestrator-cli run <state.json> [--workspace .]   运行工作流
  orchestrator-cli resume <state.json>                从中断处恢复
  orchestrator-cli show <state.json>                  查看工作流状态
  orchestrator-cli retry-task <state.json> <task_id>  重试单个失败任务

运营命令:
  orchestrator-cli all-status                         跨路径统一状态视图

回调驱动命令:
  orchestrator-cli status <task_id>                   查询任务状态
  orchestrator-cli batch-summary <batch_id>           查询批次汇总
  orchestrator-cli decide <batch_id>                  对批次做决策
  orchestrator-cli list [--state <state>]             列出任务
  orchestrator-cli stuck [--timeout <minutes>]        检测卡住的批次
  orchestrator-cli test                               运行内置测试
"""

import json
import sys
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from state_machine import (
    get_state,
    get_batch_summary,
    is_batch_complete,
    list_tasks,
)
from batch_aggregator import (
    check_and_summarize_batch,
    get_batches_by_state,
    analyze_batch_results,
    generate_batch_summary_md,
    detect_stuck_batches,
)
from orchestrator import create_default_orchestrator


def cmd_status(task_id: str):
    """查询任务状态"""
    state = get_state(task_id)
    if state:
        print(f"Task: {state['task_id']}")
        print(f"State: {state['state']}")
        print(f"Batch: {state.get('batch_id', 'N/A')}")
        print(f"Dispatched: {state.get('dispatched_at', 'N/A')}")
        print(f"Completed: {state.get('completed_at') or state.get('callback_received_at') or 'N/A'}")
        if state.get('result'):
            print(f"Result: {state['result']}")
    else:
        print(f"Task {task_id} not found")
        sys.exit(1)


def cmd_batch_summary(batch_id: str):
    """查询批次汇总"""
    # 先生成/更新汇总
    check_and_summarize_batch(batch_id, force=True)
    
    # 显示统计
    summary = get_batch_summary(batch_id)
    print(f"Batch: {batch_id}")
    print(f"Complete: {summary['complete']}")
    print(f"Total: {summary['total']}")
    print(f"Success: {summary['callback_received'] + summary['final_closed']}")
    print(f"Failed: {summary['failed']}")
    print(f"Timeout: {summary['timeout']}")
    print(f"Running: {summary['running']}")
    print(f"Pending: {summary['pending']}")
    
    # 显示汇总报告
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
            for i, task in enumerate(decision.next_tasks):
                print(f"  {i+1}. {task}")
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
    
    # 按批次分组
    batches = {}
    for task in tasks:
        batch_id = task.get('batch_id') or 'no-batch'
        if batch_id not in batches:
            batches[batch_id] = []
        batches[batch_id].append(task)
    
    print(f"Tasks ({len(tasks)} total, {len(batches)} batches):")
    for batch_id in sorted(batches.keys()):
        batch_tasks = batches[batch_id]
        complete = is_batch_complete(batch_id) if batch_id != 'no-batch' else 'N/A'
        print(f"\n  Batch: {batch_id} (complete={complete})")
        for task in sorted(batch_tasks, key=lambda t: t.get('dispatched_at', '')):
            print(f"    - {task['task_id']}: {task['state']}")


def cmd_stuck(timeout: int = 60):
    """检测卡住的批次"""
    stuck = detect_stuck_batches(timeout_minutes=timeout)
    
    if stuck:
        print(f"Stuck batches (>{timeout}min):")
        for item in stuck:
            print(f"  - Batch {item['batch_id']}: {item['task_id']} "
                  f"(state={item['state']}, stuck={item['stuck_minutes']:.1f}min)")
    else:
        print(f"No stuck batches (>{timeout}min).")


def cmd_test():
    """运行测试"""
    print("Running orchestrator tests...")
    
    # 创建测试任务
    from state_machine import create_task, mark_callback_received, mark_final_closed
    
    batch_id = "test_batch_001"
    
    print(f"\n1. Creating test batch: {batch_id}")
    task_ids = []
    for i in range(3):
        task_id = f"tsk_test_{i:03d}"
        create_task(task_id, batch_id=batch_id, timeout_seconds=60)
        task_ids.append(task_id)
        print(f"   Created: {task_id}")
    
    print(f"\n2. Listing tasks...")
    cmd_list("all")
    
    print(f"\n3. Marking tasks as complete...")
    for i, task_id in enumerate(task_ids):
        mark_callback_received(task_id, {"verdict": "PASS" if i < 2 else "FAIL"})
        print(f"   Callback received: {task_id}")
    
    print(f"\n4. Checking batch summary...")
    cmd_batch_summary(batch_id)
    
    print(f"\n5. Making decision...")
    cmd_decide(batch_id)
    
    print(f"\n6. Detecting stuck batches...")
    cmd_stuck(60)
    
    print("\n✅ Tests completed!")


def cmd_plan(description: str, config_path: str):
    """创建工作流"""
    from task_planner import TaskPlanner
    from workflow_state import save_workflow_state

    with open(config_path) as f:
        batches_config = json.load(f)

    planner = TaskPlanner()
    state = planner.plan(description, batches_config)

    out_path = f"workflow_state_{state.workflow_id}.json"
    save_workflow_state(state, out_path)
    print(f"Workflow created: {state.workflow_id}")
    print(f"  Batches: {len(state.batches)}")
    total_tasks = sum(len(b.tasks) for b in state.batches)
    print(f"  Tasks: {total_tasks}")
    print(f"  State file: {out_path}")
    print(f"\nRun with: orchestrator-cli run {out_path}")


def cmd_run(state_path: str, workspace_dir: str = ".", backend: str = "auto", on_task_complete_script: str = ""):
    """运行工作流"""
    from workflow_state_store import get_store
    store = get_store()
    store.set_active(os.path.abspath(state_path))
    os.environ["OPENCLAW_WORKFLOW_STATE_PATH"] = os.path.abspath(state_path)

    from workflow_state import load_workflow_state
    if backend in ("tmux", "auto"):
        # tmux backend requires WorkflowLoop (LangGraph doesn't support custom executors)
        from workflow_loop import WorkflowLoop
        engine = "WorkflowLoop"
    else:
        try:
            from workflow_graph import run_workflow
            engine = "LangGraph"
        except ImportError:
            from workflow_loop import WorkflowLoop
            engine = "WorkflowLoop"

    try:
        ws = load_workflow_state(state_path)
    except FileNotFoundError:
        print(f"Error: state file not found: {state_path}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON in {state_path}: {e}")
        sys.exit(1)

    print(f"Running workflow {ws.workflow_id} ({engine})")
    print(f"  Batches: {len(ws.batches)}, current: {ws.plan.get('current_batch_index', 0)}")

    try:
        if engine == "LangGraph":
            result = run_workflow(ws, state_path, workspace_dir)
        else:
            on_complete_fn = None
            if on_task_complete_script:
                import subprocess as _sp
                _notify_script = on_task_complete_script  # capture for closure
                def on_complete_fn(session_name: str) -> None:
                    r = _sp.run(["bash", _notify_script, session_name],
                                capture_output=True, text=True, timeout=30)
                    if r.returncode == 0:
                        print(f"  [notify] sent for {session_name}")
                    else:
                        print(f"  [notify] failed for {session_name}: {r.stderr[:100]}")
            loop = WorkflowLoop(workspace_dir, backend=backend, on_task_complete=on_complete_fn)
            result = loop.run(state_path)
    except Exception as e:
        print(f"\nError during execution: {type(e).__name__}: {e}")
        print(f"State saved to: {state_path}")
        print(f"Resume with: orchestrator-cli resume {state_path}")
        sys.exit(1)

    print(f"\nResult: {result.status}")
    for b in result.batches:
        dec = b.continuation.decision if b.continuation else "—"
        print(f"  {b.batch_id} ({b.label}): {b.status} → {dec}")

    if result.status == "gate_blocked":
        print(f"\nWorkflow paused — manual review required.")
        print(f"Resume with: orchestrator-cli resume {state_path}")
    elif result.status == "failed":
        for b in result.batches:
            for t in b.tasks:
                if t.error:
                    print(f"\n  FAILED: {t.task_id}: {t.error}")


def cmd_resume_workflow(state_path: str, workspace_dir: str = "."):
    """从中断处恢复工作流"""
    from workflow_state_store import get_store
    store = get_store()
    store.set_active(os.path.abspath(state_path))
    os.environ["OPENCLAW_WORKFLOW_STATE_PATH"] = os.path.abspath(state_path)

    try:
        from workflow_graph import resume_workflow
        engine = "LangGraph"
    except ImportError:
        from workflow_loop import WorkflowLoop
        engine = "WorkflowLoop"

    print(f"Resuming workflow from {state_path} ({engine}, workspace={workspace_dir})")

    if engine == "LangGraph":
        result = resume_workflow(state_path, workspace_dir)
    else:
        loop = WorkflowLoop(workspace_dir)
        result = loop.resume(state_path)

    print(f"\nResult: {result.status}")
    for b in result.batches:
        dec = b.continuation.decision if b.continuation else "—"
        print(f"  {b.batch_id} ({b.label}): {b.status} → {dec}")


def cmd_show(state_path: str):
    """查看工作流状态"""
    from workflow_state import load_workflow_state
    ws = load_workflow_state(state_path)
    print(f"Workflow: {ws.workflow_id}")
    print(f"Status: {ws.status}")
    print(f"Created: {ws.created_at}")
    print(f"Updated: {ws.updated_at}")
    print(f"Description: {ws.plan.get('description', '—')}")
    print(f"Batches: {len(ws.batches)} (current: {ws.plan.get('current_batch_index', 0)})")
    print()
    for i, b in enumerate(ws.batches):
        marker = "→ " if i == ws.plan.get("current_batch_index", 0) else "  "
        dec_str = ""
        if b.continuation:
            dec_str = f" → {b.continuation.decision}"
        deps = f" (deps: {', '.join(b.depends_on)})" if b.depends_on else ""
        print(f"{marker}[{b.status:>10}] {b.batch_id}: {b.label}{deps}{dec_str}")
        for t in b.tasks:
            t_status = t.status
            t_extra = ""
            if t.result_summary:
                t_extra = f" — {t.result_summary[:60]}"
            if t.error:
                t_extra = f" — ERROR: {t.error[:60]}"
            print(f"      [{t_status:>10}] {t.task_id}: {t.label}{t_extra}")
    if ws.context_summary:
        print(f"\nContext summary ({len(ws.context_summary)} chars):")
        print(f"  {ws.context_summary[:200]}...")


def cmd_all_status():
    """跨路径统一状态视图：DAG 工作流 + 回调任务 + tmux sessions"""
    from pathlib import Path
    import subprocess

    home = Path.home()
    sections = []

    # 1. DAG workflows
    wf_dir = home / ".openclaw/shared-context/workflows"
    wf_files = sorted(wf_dir.glob("workflow_state_*.json")) if wf_dir.is_dir() else []
    # Also check orchestrator working dir
    orch_dir = home / ".openclaw/orchestrator"
    if orch_dir.is_dir():
        wf_files.extend(sorted(orch_dir.glob("workflow_state_*.json")))

    active_wf = []
    for wf in wf_files:
        try:
            from workflow_state import load_workflow_state
            ws = load_workflow_state(wf)
            if ws.status in ("running", "pending", "gate_blocked"):
                running = sum(1 for b in ws.batches for t in b.tasks if t.status == "running")
                pending = sum(1 for b in ws.batches for t in b.tasks if t.status == "pending")
                failed = sum(1 for b in ws.batches for t in b.tasks if t.status == "failed")
                active_wf.append(f"  {ws.workflow_id} [{ws.status}] "
                                 f"running={running} pending={pending} failed={failed} "
                                 f"updated={ws.updated_at}")
        except Exception:
            pass

    if active_wf:
        sections.append("DAG Workflows:\n" + "\n".join(active_wf))
    else:
        sections.append("DAG Workflows: none active")

    # 2. Callback-driven tasks
    job_dir = home / ".openclaw/shared-context/job-status"
    cb_running, cb_pending = [], []
    if job_dir.is_dir():
        for f in sorted(job_dir.glob("*.json")):
            if f.name.startswith("batch-"):
                continue
            try:
                data = json.loads(f.read_text())
                state = data.get("state", "")
                if state in ("running", "pending", "callback_received"):
                    entry = f"  {data['task_id']} [{state}] batch={data.get('batch_id', '?')}"
                    (cb_running if state == "running" else cb_pending).append(entry)
            except Exception:
                pass
    cb_items = cb_running + cb_pending
    if cb_items:
        sections.append(f"Callback Tasks ({len(cb_items)} active):\n" + "\n".join(cb_items))
    else:
        sections.append("Callback Tasks: none active")

    # 3. Live tmux sessions
    prefix = os.environ.get("OPENCLAW_SESSION_PREFIX", "oc")
    tmux_lines = []
    try:
        result = subprocess.run(
            ["tmux", "list-sessions", "-F", "#{session_name} #{session_created}"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                if line and line.startswith(prefix + "-"):
                    tmux_lines.append(f"  {line}")
    except Exception:
        pass

    if tmux_lines:
        sections.append(f"Tmux Sessions ({len(tmux_lines)}):\n" + "\n".join(tmux_lines))
    else:
        sections.append("Tmux Sessions: none")

    # 4. Observability cards (active only)
    cards_dir = home / ".openclaw/shared-context/observability/cards"
    active_cards = []
    if cards_dir.is_dir():
        for f in sorted(cards_dir.glob("*.json")):
            try:
                data = json.loads(f.read_text())
                stage = data.get("stage", "")
                if stage in ("planning", "dispatch", "running", "idle", "callback_received"):
                    active_cards.append(
                        f"  {data.get('task_id', '?')} [{stage}] "
                        f"owner={data.get('owner', '?')} executor={data.get('executor', '?')}")
            except Exception:
                pass

    if active_cards:
        sections.append(f"Observability Cards ({len(active_cards)} active):\n" + "\n".join(active_cards))

    print("\n\n".join(sections))


def cmd_retry_task(state_path: str, task_id: str):
    """重试工作流中单个失败的任务"""
    from workflow_state import load_workflow_state, save_workflow_state
    from datetime import datetime, timezone

    ws = load_workflow_state(state_path)

    # Find the task
    target_task = None
    target_batch = None
    for batch in ws.batches:
        for task in batch.tasks:
            if task.task_id == task_id:
                target_task = task
                target_batch = batch
                break

    if target_task is None:
        print(f"Error: task '{task_id}' not found in {state_path}")
        sys.exit(1)

    if target_task.status not in ("failed", "timed_out"):
        print(f"Error: task '{task_id}' is '{target_task.status}', not failed/timed_out")
        sys.exit(1)

    # Reset the task
    target_task.status = "pending"
    target_task.error = None
    target_task.completed_at = None
    target_task.subagent_task_id = None
    target_task.retry_count += 1

    # If the batch was marked failed, reset it to running
    if target_batch.status == "failed":
        target_batch.status = "running"
        target_batch.completed_at = None

    # If the workflow was marked failed, reset to running
    if ws.status == "failed":
        ws.status = "running"

    ws.updated_at = datetime.now(timezone.utc).isoformat()
    save_workflow_state(ws, state_path)

    print(f"Task '{task_id}' reset to pending (retry #{target_task.retry_count})")
    print(f"Batch '{target_batch.batch_id}' status: {target_batch.status}")
    print(f"Workflow status: {ws.status}")
    print(f"\nResume with: orchestrator-cli resume {state_path}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    cmd = sys.argv[1]

    # DAG workflow commands
    if cmd == "plan":
        if len(sys.argv) < 4:
            print("Usage: orchestrator-cli plan <description> <config.json>")
            sys.exit(1)
        cmd_plan(sys.argv[2], sys.argv[3])
        return

    if cmd == "run":
        if len(sys.argv) < 3:
            print("Usage: orchestrator-cli run <state.json> [--workspace <dir>] [--backend tmux|subagent|auto] [--on-task-complete <script>]")
            sys.exit(1)
        workspace = "."
        backend = os.environ.get("OPENCLAW_DEFAULT_BACKEND", "auto")
        on_complete_script = ""
        if "--workspace" in sys.argv:
            idx = sys.argv.index("--workspace")
            if idx + 1 < len(sys.argv):
                workspace = sys.argv[idx + 1]
        if "--backend" in sys.argv:
            idx = sys.argv.index("--backend")
            if idx + 1 < len(sys.argv):
                backend = sys.argv[idx + 1]
        if "--on-task-complete" in sys.argv:
            idx = sys.argv.index("--on-task-complete")
            if idx + 1 < len(sys.argv):
                on_complete_script = sys.argv[idx + 1]
        cmd_run(sys.argv[2], workspace, backend, on_complete_script)
        return

    if cmd == "resume":
        if len(sys.argv) < 3:
            print("Usage: orchestrator-cli resume <state.json> [--workspace <dir>]")
            sys.exit(1)
        workspace = "."
        if "--workspace" in sys.argv:
            idx = sys.argv.index("--workspace")
            if idx + 1 < len(sys.argv):
                workspace = sys.argv[idx + 1]
        cmd_resume_workflow(sys.argv[2], workspace)
        return

    if cmd == "show":
        if len(sys.argv) < 3:
            print("Usage: orchestrator-cli show <state.json>")
            sys.exit(1)
        cmd_show(sys.argv[2])
        return

    if cmd == "retry-task":
        if len(sys.argv) < 4:
            print("Usage: orchestrator-cli retry-task <state.json> <task_id>")
            sys.exit(1)
        cmd_retry_task(sys.argv[2], sys.argv[3])
        return

    if cmd == "all-status":
        cmd_all_status()
        return

    # Callback-driven commands
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
