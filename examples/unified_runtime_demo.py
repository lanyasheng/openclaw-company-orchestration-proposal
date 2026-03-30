#!/usr/bin/env python3
"""
unified_runtime_demo.py — Demo script for Unified Execution Runtime

P0-3 Batch 8 (2026-03-30): 演示统一执行入口的使用。

运行：
```bash
cd runtime/orchestrator
python3 ../../examples/unified_runtime_demo.py
```

注意：本演示脚本使用 mock 避免实际执行 subagent/tmux，只演示 API 接口。
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add orchestrator directory to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "runtime" / "orchestrator"))

from unified_execution_runtime import UnifiedExecutionRuntime, TaskContext, run_task, ExecutionResult
from backend_selector import recommend_backend


def demo_backend_selector():
    """Demo backend selector recommendations."""
    print("=" * 60)
    print("Backend Selector Demo")
    print("=" * 60)
    
    test_cases = [
        {
            "task": "重构认证模块，预计 1 小时",
            "estimated_duration_minutes": 60,
        },
        {
            "task": "写一个 README 文档",
            "estimated_duration_minutes": 15,
        },
        {
            "task": "调试一个偶发的 bug，可能需要监控",
            "requires_monitoring": True,
        },
        {
            "task": "简单的数据查询",
            "estimated_duration_minutes": 5,
        },
        {
            "task": "实现一个新功能，需要看过程",
            "estimated_duration_minutes": 45,
        },
    ]
    
    for case in test_cases:
        rec = recommend_backend(case["task"], **{k: v for k, v in case.items() if k != "task"})
        print(f"\n任务：{case['task']}")
        print(f"推荐：{rec.backend} (confidence={rec.confidence:.2f})")
        print(f"理由：{rec.reason}")


def demo_unified_runtime_api():
    """Demo unified runtime Python API with mocks."""
    print("\n" + "=" * 60)
    print("Unified Runtime API Demo (Mocked)")
    print("=" * 60)
    
    runtime = UnifiedExecutionRuntime()
    
    # Mock SubagentExecutor
    with patch('unified_execution_runtime.SubagentExecutor') as mock_executor_class:
        mock_executor = MagicMock()
        mock_executor.execute_async.return_value = "task_demo_123"
        mock_executor.get_result.return_value = MagicMock(
            status="running",
            pid=12345,
        )
        mock_executor_class.return_value = mock_executor
        
        # Demo 1: Auto recommend backend (short task → subagent)
        print("\n1. Auto recommend (short task):")
        context = TaskContext.from_string(
            task_description="写 README 文档",
            workdir="/tmp",
            estimated_duration_minutes=15,
        )
        result = runtime.run_task(context)
        print(f"   Backend: {result.backend}")
        print(f"   Session: {result.session_id}")
        print(f"   Reason: {result.backend_selection['reason']}")
    
    # Mock tmux subprocess
    with patch('unified_execution_runtime.subprocess.run') as mock_run:
        mock_run.return_value = MagicMock(stdout="STATUS=running\n", stderr="")
        
        # Demo 2: Auto recommend backend (long task → tmux)
        print("\n2. Auto recommend (long task):")
        context = TaskContext.from_string(
            task_description="重构认证模块，预计 1 小时",
            workdir="/tmp",
            estimated_duration_minutes=60,
        )
        result = runtime.run_task(context)
        print(f"   Backend: {result.backend}")
        print(f"   Session: {result.session_id}")
        print(f"   Reason: {result.backend_selection['reason']}")
        print(f"   Wake Command: {result.wake_command[:50]}...")
    
    # Demo 3: Explicit backend preference
    print("\n3. Explicit backend preference (tmux):")
    with patch('unified_execution_runtime.subprocess.run') as mock_run:
        mock_run.return_value = MagicMock(stdout="STATUS=running\n", stderr="")
        context = TaskContext.from_string(
            task_description="短任务但用户指定 tmux",
            workdir="/tmp",
            backend_preference="tmux",
        )
        result = runtime.run_task(context)
        print(f"   Backend: {result.backend}")
        print(f"   Explicit override: {result.backend_selection['explicit_override']}")
    
    # Demo 4: Monitoring required
    print("\n4. Monitoring required:")
    with patch('unified_execution_runtime.subprocess.run') as mock_run:
        mock_run.return_value = MagicMock(stdout="STATUS=running\n", stderr="")
        context = TaskContext.from_string(
            task_description="调试 bug，需要监控中间过程",
            workdir="/tmp",
            requires_monitoring=True,
        )
        result = runtime.run_task(context)
        print(f"   Backend: {result.backend}")
        print(f"   Reason: {result.backend_selection['reason']}")


def demo_convenience_function():
    """Demo convenience run_task function with mock."""
    print("\n" + "=" * 60)
    print("Convenience Function Demo (Mocked)")
    print("=" * 60)
    
    with patch('unified_execution_runtime.SubagentExecutor') as mock_executor_class:
        mock_executor = MagicMock()
        mock_executor.execute_async.return_value = "task_demo_456"
        mock_executor.get_result.return_value = MagicMock(status="running", pid=12345)
        mock_executor_class.return_value = mock_executor
        
        print("\nUsing run_task() convenience function:")
        result = run_task(
            task_description="测试任务",
            workdir="/tmp",
            backend_preference="subagent",
            metadata={"demo": True},
        )
        print(f"   Task ID: {result.task_id}")
        print(f"   Dispatch ID: {result.dispatch_id}")
        print(f"   Backend: {result.backend}")
        print(f"   Status: {result.status}")


def demo_result_schema():
    """Demo ExecutionResult schema."""
    print("\n" + "=" * 60)
    print("ExecutionResult Schema Demo")
    print("=" * 60)
    
    # Create a mock result
    result = ExecutionResult(
        task_id="task_demo_789",
        dispatch_id="dispatch_demo_789",
        backend="subagent",
        session_id="subagent-demo",
        label="demo-task",
        status="running",
        callback_path=Path("/tmp/callback.json"),
        wake_command=None,
        artifacts={"status_json": Path("/tmp/status.json")},
        backend_selection={
            "auto_recommended": True,
            "recommended_backend": "subagent",
            "applied_backend": "subagent",
            "confidence": 0.8,
            "reason": "短任务 (<30min)",
            "factors": {"duration_factor": "short_task"},
            "explicit_override": False,
        },
        metadata={"demo": True},
    )
    
    print("\nResult attributes:")
    print(f"   task_id: {result.task_id}")
    print(f"   dispatch_id: {result.dispatch_id}")
    print(f"   backend: {result.backend}")
    print(f"   session_id: {result.session_id}")
    print(f"   label: {result.label}")
    print(f"   status: {result.status}")
    print(f"   callback_path: {result.callback_path}")
    print(f"   wake_command: {result.wake_command or 'N/A (subagent)'}")
    print(f"   artifacts: {list(result.artifacts.keys())}")
    print(f"   backend_selection keys: {list(result.backend_selection.keys())}")
    
    print("\nResult as dict (partial):")
    data = result.to_dict()
    for key in ["task_id", "backend", "session_id", "status"]:
        print(f"   {key}: {data[key]}")


def demo_cli_usage():
    """Demo CLI usage examples."""
    print("\n" + "=" * 60)
    print("CLI Usage Examples")
    print("=" * 60)
    
    examples = [
        "# Auto recommend backend",
        "python3 runtime/orchestrator/run_task.py \\",
        "  --task \"重构认证模块\" \\",
        "  --workdir /path/to/workdir",
        "",
        "# Explicit backend",
        "python3 runtime/orchestrator/run_task.py \\",
        "  --task \"写 README 文档\" \\",
        "  --backend subagent \\",
        "  --workdir /path/to/workdir",
        "",
        "# JSON output (for scripting)",
        "python3 runtime/orchestrator/run_task.py \\",
        "  --task \"...\" \\",
        "  --output json \\",
        "  --workdir /path/to/workdir",
        "",
        "# With metadata",
        "python3 runtime/orchestrator/run_task.py \\",
        "  --task \"...\" \\",
        "  --workdir /path/to/workdir \\",
        "  --metadata '{\"scenario\":\"trading\"}'",
    ]
    
    for line in examples:
        print(line)


if __name__ == "__main__":
    print("Unified Execution Runtime Demo")
    print("P0-3 Batch 8 (2026-03-30)")
    print()
    
    demo_backend_selector()
    demo_unified_runtime_api()
    demo_convenience_function()
    demo_result_schema()
    demo_cli_usage()
    
    print("\n" + "=" * 60)
    print("Demo Complete!")
    print("=" * 60)
    print("\nFor real execution (not mock), run:")
    print("  python3 runtime/orchestrator/run_task.py --task '...' --workdir /path/to/workdir")
