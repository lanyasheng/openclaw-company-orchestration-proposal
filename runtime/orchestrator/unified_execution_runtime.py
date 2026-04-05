#!/usr/bin/env python3
"""
unified_execution_runtime.py — Unified Execution Runtime for OpenClaw Orchestration

P0-3 Batch 8 (2026-03-30): 统一执行入口，把 tmux / subagent 接入从多步工程化流程收成单入口体验。

核心能力：
1. 读取 task context / orchestration contract
2. 决定 backend（显式 backend_preference 优先，否则调用 backend_selector）
3. subagent 路径：走现有 SubagentExecutor
4. tmux 路径：自动完成 start + observability register + 初始 sync + callback/wake 接线
5. 对外提供统一 Python API（run_task）和 CLI 入口

使用示例：
```python
from unified_execution_runtime import UnifiedExecutionRuntime, TaskContext

# 最小用法
runtime = UnifiedExecutionRuntime()
result = runtime.run_task(
    task_description="重构认证模块，预计 1 小时",
    workdir="/path/to/workdir",
)

# 显式指定 backend
result = runtime.run_task(
    task_description="写 README 文档",
    backend_preference="subagent",
    workdir="/path/to/workdir",
)

# 完整用法
context = TaskContext(
    task_description="重构认证模块",
    estimated_duration_minutes=60,
    task_type="coding",
    requires_monitoring=True,
    backend_preference=None,  # None = auto recommend
    workdir=Path("/path/to/workdir"),
    metadata={"scenario": "trading_roundtable_phase1"},
)
result = runtime.run_task(context)
```

CLI 用法：
```bash
# 自动推荐 backend
python3 runtime/orchestrator/run_task.py --task "任务描述" --workdir /path/to/workdir

# 显式指定 backend
python3 runtime/orchestrator/run_task.py --task "任务描述" --backend subagent --workdir ...

# JSON 输出
python3 runtime/orchestrator/run_task.py --task "..." --output json --workdir ...
```
"""

from __future__ import annotations

import json
import shlex
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

# Import backend selector
from backend_selector import BackendSelector, BackendRecommendation, recommend_backend

# Import subagent executor
from subagent_executor import SubagentExecutor, SubagentConfig, SubagentResult, _state_file

__all__ = [
    "TaskContext",
    "ExecutionResult",
    "UnifiedExecutionRuntime",
    "run_task",
    "UNIFIED_RUNTIME_VERSION",
]

UNIFIED_RUNTIME_VERSION = "unified_execution_runtime_v1"

# ============ Constants ============

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = WORKSPACE_ROOT / "scripts"

# Tmux scripts (from claude-code-orchestrator skill)
TMUX_START_SCRIPT = Path("~/.openclaw/skills/claude-code-orchestrator/scripts/start-tmux-task.sh").expanduser()
TMUX_STATUS_SCRIPT = Path("~/.openclaw/skills/claude-code-orchestrator/scripts/status-tmux-task.sh").expanduser()
TMUX_MONITOR_SCRIPT = Path("~/.openclaw/skills/claude-code-orchestrator/scripts/monitor-tmux-task.sh").expanduser()
TMUX_WAKE_SCRIPT = Path("~/.openclaw/skills/claude-code-orchestrator/scripts/wake.sh").expanduser()

# Observability sync script
SYNC_OBSERVABILITY_SCRIPT = SCRIPTS_DIR / "sync-tmux-observability.py"

# Default timeouts
DEFAULT_SUBAGENT_TIMEOUT_SECONDS = 30 * 60  # 30 minutes
DEFAULT_TMUX_TIMEOUT_SECONDS = 60 * 60  # 60 minutes (no hard timeout, watchdog managed)

# Dispatch storage
DISPATCH_DIR = Path.home() / ".openclaw" / "shared-context" / "dispatches"


def _ensure_dispatch_dir():
    """Ensure dispatch directory exists."""
    DISPATCH_DIR.mkdir(parents=True, exist_ok=True)


def _iso_now() -> str:
    """Return current ISO-8601 timestamp."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _slugify(value: str) -> str:
    """Slugify a string for use in labels/session names."""
    cleaned = []
    prev_dash = False
    for char in value.lower():
        if char.isalnum():
            cleaned.append(char)
            prev_dash = False
        elif not prev_dash:
            cleaned.append("-")
            prev_dash = True
    result = "".join(cleaned).strip("-")
    return result or "task"


def _generate_dispatch_id() -> str:
    """Generate stable dispatch ID."""
    return f"dispatch_{uuid.uuid4().hex[:12]}"


def _generate_label(task_description: str, dispatch_id: str) -> str:
    """Generate label from task description and dispatch ID."""
    slug = _slugify(task_description[:64])
    short_id = dispatch_id.split("_")[-1]
    return f"{slug}-{short_id}"[:48].strip("-")


# ============ Data Classes ============


@dataclass
class TaskContext:
    """
    Task context for unified execution.
    
    Attributes:
    - task_description: Task description (required)
    - estimated_duration_minutes: Estimated duration in minutes (optional)
    - task_type: Task type ("coding" / "documentation" / "research" / "custom")
    - requires_monitoring: Whether monitoring intermediate progress is needed
    - backend_preference: Explicit backend preference ("subagent" | "tmux" | None for auto)
    - workdir: Working directory (required)
    - metadata: Additional metadata (scenario, owner, etc.)
    - timeout_seconds: Timeout in seconds (optional, uses default if None)
    """
    task_description: str
    workdir: Path
    estimated_duration_minutes: Optional[int] = None
    task_type: Optional[Literal["coding", "documentation", "research", "custom"]] = None
    requires_monitoring: Optional[bool] = None
    backend_preference: Optional[Literal["subagent", "tmux"]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    timeout_seconds: Optional[int] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_description": self.task_description,
            "workdir": str(self.workdir),
            "estimated_duration_minutes": self.estimated_duration_minutes,
            "task_type": self.task_type,
            "requires_monitoring": self.requires_monitoring,
            "backend_preference": self.backend_preference,
            "metadata": self.metadata,
            "timeout_seconds": self.timeout_seconds,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskContext":
        return cls(
            task_description=data.get("task_description", ""),
            workdir=Path(data.get("workdir", ".")),
            estimated_duration_minutes=data.get("estimated_duration_minutes"),
            task_type=data.get("task_type"),
            requires_monitoring=data.get("requires_monitoring"),
            backend_preference=data.get("backend_preference"),
            metadata=data.get("metadata", {}),
            timeout_seconds=data.get("timeout_seconds"),
        )
    
    @classmethod
    def from_string(
        cls,
        task_description: str,
        workdir: Union[str, Path],
        backend_preference: Optional[str] = None,
        estimated_duration_minutes: Optional[int] = None,
        task_type: Optional[str] = None,
        requires_monitoring: Optional[bool] = None,
        metadata: Optional[Dict[str, Any]] = None,
        timeout_seconds: Optional[int] = None,
    ) -> "TaskContext":
        """Convenience constructor from string parameters."""
        return cls(
            task_description=task_description,
            workdir=Path(workdir) if isinstance(workdir, str) else workdir,
            estimated_duration_minutes=estimated_duration_minutes,
            task_type=task_type,
            requires_monitoring=requires_monitoring,
            backend_preference=backend_preference,
            metadata=metadata or {},
            timeout_seconds=timeout_seconds,
        )


@dataclass
class ExecutionResult:
    """
    Execution result from unified runtime.
    
    Attributes:
    - task_id: Task identifier
    - dispatch_id: Dispatch identifier
    - backend: Backend used ("subagent" | "tmux")
    - session_id: Session identifier (tmux session name or subagent task ID)
    - label: Task label
    - status: Current status ("pending" | "running" | "completed" | "failed")
    - callback_path: Path to callback artifact (if applicable)
    - wake_command: Command to wake/check task (tmux only)
    - artifacts: Dictionary of artifact paths
    - backend_selection: Backend selection metadata
    - metadata: Additional metadata
    - error: Error message (if failed)
    """
    task_id: str
    dispatch_id: str
    backend: Literal["subagent", "tmux"]
    session_id: str
    label: str
    status: Literal["pending", "running", "completed", "failed"]
    callback_path: Optional[Path] = None
    wake_command: Optional[str] = None
    artifacts: Dict[str, Path] = field(default_factory=dict)
    backend_selection: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "dispatch_id": self.dispatch_id,
            "backend": self.backend,
            "session_id": self.session_id,
            "label": self.label,
            "status": self.status,
            "callback_path": str(self.callback_path) if self.callback_path else None,
            "wake_command": self.wake_command,
            "artifacts": {k: str(v) for k, v in self.artifacts.items()},
            "backend_selection": self.backend_selection,
            "metadata": self.metadata,
            "error": self.error,
        }
    
    def write_dispatch_artifact(self) -> Path:
        """Write dispatch artifact to file."""
        _ensure_dispatch_dir()
        dispatch_file = DISPATCH_DIR / f"{self.dispatch_id}.json"
        tmp_file = dispatch_file.with_suffix(".tmp")
        
        artifact = {
            "version": UNIFIED_RUNTIME_VERSION,
            "dispatch_id": self.dispatch_id,
            "task_id": self.task_id,
            "backend": self.backend,
            "session_id": self.session_id,
            "label": self.label,
            "status": self.status,
            "created_at": _iso_now(),
            "callback_path": str(self.callback_path) if self.callback_path else None,
            "wake_command": self.wake_command,
            "artifacts": {k: str(v) for k, v in self.artifacts.items()},
            "backend_selection": self.backend_selection,
            "metadata": self.metadata,
        }
        
        with open(tmp_file, "w") as f:
            json.dump(artifact, f, indent=2, ensure_ascii=False)
        tmp_file.replace(dispatch_file)
        
        return dispatch_file


# ============ Unified Execution Runtime ============


class UnifiedExecutionRuntime:
    """
    Unified execution runtime for OpenClaw Orchestration.
    
    Provides single entry point for task execution with automatic backend selection
    and full automation for both subagent and tmux paths.
    """
    
    def __init__(self, workspace_root: Optional[Path] = None):
        """
        Initialize unified runtime.
        
        Args:
            workspace_root: Workspace root directory (defaults to parent of this module)
        """
        self.workspace_root = workspace_root or WORKSPACE_ROOT
        self.backend_selector = BackendSelector()
    
    def run_task(
        self,
        task_context: Union[TaskContext, str],
        workdir: Optional[Union[str, Path]] = None,
        backend_preference: Optional[Literal["subagent", "tmux"]] = None,
        estimated_duration_minutes: Optional[int] = None,
        task_type: Optional[str] = None,
        requires_monitoring: Optional[bool] = None,
        metadata: Optional[Dict[str, Any]] = None,
        timeout_seconds: Optional[int] = None,
    ) -> ExecutionResult:
        """
        Run a task with unified execution runtime.
        
        Args:
            task_context: TaskContext object OR task description string
            workdir: Working directory (required if task_context is string)
            backend_preference: Explicit backend preference (optional)
            estimated_duration_minutes: Estimated duration (optional)
            task_type: Task type (optional)
            requires_monitoring: Whether monitoring is needed (optional)
            metadata: Additional metadata (optional)
            timeout_seconds: Timeout in seconds (optional)
        
        Returns:
            ExecutionResult with task ID, backend info, and callback/wake wiring
        
        Raises:
            ValueError: If invalid parameters
            RuntimeError: If execution fails
        """
        # Normalize input to TaskContext
        if isinstance(task_context, str):
            if not workdir:
                raise ValueError("workdir is required when task_context is a string")
            context = TaskContext.from_string(
                task_description=task_context,
                workdir=workdir,
                backend_preference=backend_preference,
                estimated_duration_minutes=estimated_duration_minutes,
                task_type=task_type,
                requires_monitoring=requires_monitoring,
                metadata=metadata,
                timeout_seconds=timeout_seconds,
            )
        else:
            context = task_context
            # Override with explicit parameters if provided
            if backend_preference is not None:
                context.backend_preference = backend_preference
            if estimated_duration_minutes is not None:
                context.estimated_duration_minutes = estimated_duration_minutes
            if task_type is not None:
                context.task_type = task_type
            if requires_monitoring is not None:
                context.requires_monitoring = requires_monitoring
            if metadata is not None:
                context.metadata = metadata
            if timeout_seconds is not None:
                context.timeout_seconds = timeout_seconds
        
        # Generate dispatch ID and label
        dispatch_id = _generate_dispatch_id()
        label = _generate_label(context.task_description, dispatch_id)
        
        # Decide backend
        applied_backend, backend_rec = self._decide_backend(context)
        
        # Build backend selection metadata
        backend_selection = {
            "auto_recommended": not bool(context.backend_preference),
            "recommended_backend": backend_rec.backend,
            "applied_backend": applied_backend,
            "confidence": backend_rec.confidence,
            "reason": backend_rec.reason,
            "factors": backend_rec.factors,
            "explicit_override": bool(context.backend_preference),
        }
        
        # Execute based on backend
        if applied_backend == "subagent":
            result = self._execute_subagent(context, dispatch_id, label, backend_selection)
        else:
            result = self._execute_tmux(context, dispatch_id, label, backend_selection)
        
        # Write dispatch artifact
        result.write_dispatch_artifact()
        
        return result
    
    def _decide_backend(self, context: TaskContext) -> Tuple[str, BackendRecommendation]:
        """
        Decide backend based on context.
        
        Returns:
            (applied_backend, recommendation)
        """
        if context.backend_preference:
            # Explicit override
            rec = BackendRecommendation(
                backend=context.backend_preference,
                confidence=1.0,
                reason="用户明确指定",
                factors={"user_preference": context.backend_preference},
            )
            return context.backend_preference, rec
        
        # Auto recommend
        rec = self.backend_selector.recommend(
            task_description=context.task_description,
            estimated_duration_minutes=context.estimated_duration_minutes,
            task_type=context.task_type,
            requires_monitoring=context.requires_monitoring,
        )
        return rec.backend, rec
    
    def _execute_subagent(
        self,
        context: TaskContext,
        dispatch_id: str,
        label: str,
        backend_selection: Dict[str, Any],
    ) -> ExecutionResult:
        """
        Execute task via subagent backend.
        
        Preserves existing subagent path via SubagentExecutor.
        """
        timeout = context.timeout_seconds or DEFAULT_SUBAGENT_TIMEOUT_SECONDS
        
        config = SubagentConfig(
            label=label,
            runtime="subagent",
            timeout_seconds=timeout,
            cwd=str(context.workdir),
            metadata={
                "dispatch_id": dispatch_id,
                "backend_selection": backend_selection,
            },
        )
        
        executor = SubagentExecutor(config=config, cwd=str(context.workdir))
        task_id = executor.execute_async(context.task_description)
        
        # Get initial status via get_result
        status_result = executor.get_result(task_id)
        
        # Build callback path
        callback_path = DISPATCH_DIR / f"{dispatch_id}-callback.json"
        
        # Build artifacts dict
        artifacts = {}
        if status_result:
            # Load state file path
            state_file = _state_file(task_id)
            if state_file.exists():
                artifacts["status_json"] = state_file
        
        return ExecutionResult(
            task_id=task_id,
            dispatch_id=dispatch_id,
            backend="subagent",
            session_id=f"subagent-{label}",
            label=label,
            status=status_result.status if status_result else "pending",
            callback_path=callback_path,
            wake_command=None,  # subagent uses callback, not wake
            artifacts=artifacts,
            backend_selection=backend_selection,
            metadata={
                "pid": status_result.pid if status_result else None,
                "runner_label": label,
                "timeout_seconds": timeout,
            },
        )
    
    def _execute_tmux(
        self,
        context: TaskContext,
        dispatch_id: str,
        label: str,
        backend_selection: Dict[str, Any],
    ) -> ExecutionResult:
        """
        Execute task via tmux backend.
        
        Automates:
        1. start-tmux-task.sh
        2. sync-tmux-observability.py
        3. Initial status sync
        4. Return callback/wake wiring info
        """
        timeout = context.timeout_seconds or DEFAULT_TMUX_TIMEOUT_SECONDS
        session = f"cc-{label}"
        
        # Prepare prompt file with task context
        prompt_file = Path("/tmp") / f"{session}-ref.md"
        prompt_content = f"""# Task Reference

**Dispatch ID:** {dispatch_id}
**Label:** {label}
**Session:** {session}
**Started:** {_iso_now()}

## Task Description

{context.task_description}

## Context

- Estimated Duration: {context.estimated_duration_minutes or 'N/A'} minutes
- Task Type: {context.task_type or 'custom'}
- Requires Monitoring: {context.requires_monitoring or False}
- Timeout: {timeout} seconds

## Metadata

{json.dumps(context.metadata, indent=2, ensure_ascii=False)}
"""
        prompt_file.write_text(prompt_content, encoding="utf-8")
        
        # 1. Start tmux session
        start_cmd = [
            str(TMUX_START_SCRIPT),
            "--label", label,
            "--workdir", str(context.workdir),
            "--prompt-file", str(prompt_file),
            "--task", context.task_description,
            "--lint-cmd", "",
            "--build-cmd", "",
        ]
        
        try:
            subprocess.run(start_cmd, check=True, capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"Timed out starting tmux session for label={label}")
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to start tmux session: {e.stderr or e.stdout or str(e)}")
        
        # 2. Register observability (sync-tmux-observability.py)
        if SYNC_OBSERVABILITY_SCRIPT.exists():
            sync_cmd = [
                "python3", str(SYNC_OBSERVABILITY_SCRIPT),
                "--label", label,
                "--dispatch-id", dispatch_id,
            ]
            try:
                subprocess.run(sync_cmd, check=True, capture_output=True, text=True, timeout=60)
            except subprocess.TimeoutExpired:
                print(f"Warning: Observability sync timed out for label={label}")
            except subprocess.CalledProcessError as e:
                # Log warning but continue (observability is nice-to-have)
                print(f"Warning: Failed to sync observability: {e.stderr or str(e)}")
        
        # 3. Initial status sync
        status_cmd = [str(TMUX_STATUS_SCRIPT), "--label", label]
        try:
            status_output = subprocess.run(status_cmd, capture_output=True, text=True, timeout=10)
            status_lines = status_output.stdout.strip().split("\n")
            status_dict = {}
            for line in status_lines:
                if "=" in line:
                    key, value = line.split("=", 1)
                    status_dict[key.strip()] = value.strip()
            tmux_status = status_dict.get("STATUS", "unknown")
        except Exception:
            import logging as _logging
            _logging.getLogger(__name__).warning(
                "failed to get tmux status for session %s", session, exc_info=True,
            )
            tmux_status = "unknown"
        
        # 4. Build result with callback/wake wiring
        callback_path = Path("/tmp") / f"{session}-completion-report.json"
        wake_command = f"bash {shlex.quote(str(TMUX_WAKE_SCRIPT))} --label {shlex.quote(label)}"
        
        # Build artifacts dict
        artifacts = {
            "prompt_file": prompt_file,
            "report_json": callback_path,
            "report_md": callback_path.with_suffix(".md"),
        }
        
        return ExecutionResult(
            task_id=dispatch_id,
            dispatch_id=dispatch_id,
            backend="tmux",
            session_id=session,
            label=label,
            status="running" if tmux_status in ("running", "idle", "likely_done") else tmux_status,
            callback_path=callback_path,
            wake_command=wake_command,
            artifacts=artifacts,
            backend_selection=backend_selection,
            metadata={
                "tmux_status": tmux_status,
                "tmux_status_script": str(TMUX_STATUS_SCRIPT),
                "tmux_monitor_script": str(TMUX_MONITOR_SCRIPT),
                "prompt_file": str(prompt_file),
                "timeout_seconds": timeout,
            },
        )


# ============ Convenience Function ============


def run_task(
    task_description: str,
    workdir: Union[str, Path],
    backend_preference: Optional[str] = None,
    estimated_duration_minutes: Optional[int] = None,
    task_type: Optional[str] = None,
    requires_monitoring: Optional[bool] = None,
    metadata: Optional[Dict[str, Any]] = None,
    timeout_seconds: Optional[int] = None,
) -> ExecutionResult:
    """
    Convenience function to run a task with unified execution runtime.
    
    This is a shortcut for:
    ```python
    runtime = UnifiedExecutionRuntime()
    result = runtime.run_task(task_description, workdir, ...)
    ```
    
    Args:
        task_description: Task description
        workdir: Working directory
        backend_preference: Explicit backend preference (optional)
        estimated_duration_minutes: Estimated duration (optional)
        task_type: Task type (optional)
        requires_monitoring: Whether monitoring is needed (optional)
        metadata: Additional metadata (optional)
        timeout_seconds: Timeout in seconds (optional)
    
    Returns:
        ExecutionResult
    
    Example:
        >>> result = run_task("重构认证模块", "/path/to/workdir")
        >>> print(f"Backend: {result.backend}, Session: {result.session_id}")
    """
    runtime = UnifiedExecutionRuntime()
    return runtime.run_task(
        task_context=task_description,
        workdir=workdir,
        backend_preference=backend_preference,
        estimated_duration_minutes=estimated_duration_minutes,
        task_type=task_type,
        requires_monitoring=requires_monitoring,
        metadata=metadata,
        timeout_seconds=timeout_seconds,
    )


# ============ Main (CLI Entry) ============


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Unified Execution Runtime - Run tasks with automatic backend selection",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Auto recommend backend
  python3 unified_execution_runtime.py --task "重构认证模块" --workdir /path/to/workdir
  
  # Explicit backend
  python3 unified_execution_runtime.py --task "写 README" --backend subagent --workdir ...
  
  # JSON output
  python3 unified_execution_runtime.py --task "..." --output json --workdir ...
  
  # With metadata
  python3 unified_execution_runtime.py --task "..." --workdir ... --metadata '{"scenario":"trading"}'
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
