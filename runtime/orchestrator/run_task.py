#!/usr/bin/env python3
"""
run_task.py — CLI entry point for Unified Execution Runtime

P0-3 Batch 8 (2026-03-30): 最小 CLI 入口，让"以后其他 agent 怎么用"一句话讲清楚。

用法：
```bash
# 自动推荐 backend
python3 runtime/orchestrator/run_task.py --task "任务描述" --workdir /path/to/workdir

# 显式指定 backend
python3 runtime/orchestrator/run_task.py --task "任务描述" --backend subagent --workdir ...

# JSON 输出（便于脚本消费）
python3 runtime/orchestrator/run_task.py --task "..." --output json --workdir ...

# 带 metadata
python3 runtime/orchestrator/run_task.py --task "..." --workdir ... --metadata '{"scenario":"trading"}'
```

一句话说明：
> 这是 OpenClaw Orchestration 的统一执行入口，自动选择 backend（tmux/subagent）并返回 callback/wake 接线信息。
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent))

from unified_execution_runtime import run_task, ExecutionResult
import json
import argparse


def main():
    parser = argparse.ArgumentParser(
        description="Unified Execution Runtime CLI - Run tasks with automatic backend selection",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Auto recommend backend
  python3 run_task.py --task "重构认证模块" --workdir /path/to/workdir
  
  # Explicit backend
  python3 run_task.py --task "写 README" --backend subagent --workdir ...
  
  # JSON output (for scripting)
  python3 run_task.py --task "..." --output json --workdir ...
  
  # With metadata
  python3 run_task.py --task "..." --workdir ... --metadata '{"scenario":"trading"}'

One-liner for other agents:
  > This is the unified execution entry point for OpenClaw Orchestration.
  > It automatically selects backend (tmux/subagent) and returns callback/wake wiring info.
        """,
    )
    
    parser.add_argument("--task", "-t", required=True, help="Task description")
    parser.add_argument("--workdir", "-w", required=True, help="Working directory")
    parser.add_argument("--backend", "-b", choices=["subagent", "tmux"], help="Explicit backend preference")
    parser.add_argument("--duration", "-d", type=int, help="Estimated duration in minutes")
    parser.add_argument("--type", "-T", dest="task_type", choices=["coding", "documentation", "research", "custom"], help="Task type")
    parser.add_argument("--monitor", "-m", action="store_true", help="Requires monitoring")
    parser.add_argument("--timeout", type=int, help="Timeout in seconds")
    parser.add_argument("--metadata", "-M", type=str, help="Additional metadata (JSON string)")
    parser.add_argument("--output", "-o", choices=["text", "json"], default="text", help="Output format")
    
    args = parser.parse_args()
    
    # Parse metadata
    metadata = {}
    if args.metadata:
        try:
            metadata = json.loads(args.metadata)
        except json.JSONDecodeError as e:
            print(f"Error: Invalid metadata JSON: {e}", file=sys.stderr)
            sys.exit(1)
    
    # Run task
    try:
        result = run_task(
            task_description=args.task,
            workdir=args.workdir,
            backend_preference=args.backend,
            estimated_duration_minutes=args.duration,
            task_type=args.task_type,
            requires_monitoring=args.monitor,
            metadata=metadata,
            timeout_seconds=args.timeout,
        )
        
        if args.output == "json":
            print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        else:
            print(f"=== Execution Result ===")
            print(f"Task ID:      {result.task_id}")
            print(f"Dispatch ID:  {result.dispatch_id}")
            print(f"Backend:      {result.backend}")
            print(f"Session:      {result.session_id}")
            print(f"Label:        {result.label}")
            print(f"Status:       {result.status}")
            print(f"Callback:     {result.callback_path}")
            if result.wake_command:
                print(f"Wake Command: {result.wake_command}")
            print(f"Artifacts:")
            for name, path in result.artifacts.items():
                print(f"  - {name}: {path}")
            print(f"Backend Selection:")
            if result.backend_selection:
                print(f"  - Recommended: {result.backend_selection.get('recommended_backend')}")
                print(f"  - Reason: {result.backend_selection.get('reason')}")
                print(f"  - Confidence: {result.backend_selection.get('confidence')}")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
