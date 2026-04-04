"""TmuxTaskExecutor — runs tasks via tmux + Claude Code CLI.

Implements TaskExecutorBase so WorkflowLoop can use tmux sessions
as its execution backend instead of (or alongside) subagent spawn.

Uses dispatch.sh (or start-tmux-task.sh) for session creation and
status-tmux-task.sh (or tmux capture-pane) for status polling.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict

from executor_interface import TaskExecutorBase, TaskResult

__all__ = ["TmuxTaskExecutor"]

logger = logging.getLogger(__name__)

DISPATCH_SCRIPT = Path(os.environ.get(
    "OPENCLAW_DISPATCH_SCRIPT",
    os.path.expanduser("~/.openclaw/skills/nanocompose-dispatch/scripts/dispatch.sh"),
))
STATUS_SCRIPT = Path(os.environ.get(
    "OPENCLAW_STATUS_SCRIPT",
    os.path.expanduser("~/.openclaw/skills/nanocompose-dispatch/scripts/status.sh"),
))
ORCH_BRIDGE = Path(os.environ.get(
    "OPENCLAW_ORCH_BRIDGE",
    os.path.expanduser("~/.openclaw/skills/nanocompose-dispatch/scripts/orch-bridge.sh"),
))

_TERMINAL_STATUSES = {"completed", "failed", "exited"}


class TmuxTaskExecutor(TaskExecutorBase):
    """Execute tasks in tmux sessions via dispatch.sh."""

    def __init__(
        self,
        workspace_dir: str,
        timeout_seconds: int = 3600,
        mode: str = "headless",
    ):
        self.workspace_dir = workspace_dir
        self.timeout_seconds = timeout_seconds
        self.mode = mode
        self._start_times: dict[str, float] = {}

    def execute(self, task_id: str, label: str, context: Dict[str, Any]) -> str:
        """Start a tmux session with Claude Code. Returns session name as handle."""
        task_type = context.get("type", "review")
        prompt = context.get("prompt", label)
        task_short_id = task_id.replace("tsk_", "").replace("_", "-")
        session_name = f"nc-{task_type}-{task_short_id}"

        cmd = [
            str(DISPATCH_SCRIPT),
            "--type", task_type,
            "--id", task_short_id,
            "--prompt", prompt,
            "--project-dir", self.workspace_dir,
            "--mode", self.mode,
        ]

        logger.info("dispatching %s -> %s", task_id, session_name)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode != 0:
            error = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(f"dispatch failed for {task_id}: {error}")

        self._start_times[session_name] = time.monotonic()
        return session_name

    def poll(self, handle: str) -> TaskResult:
        """Check tmux session status. handle is the session name."""
        session_name = handle

        # 1. Check if tmux session still exists
        check = subprocess.run(
            ["tmux", "has-session", "-t", session_name],
            capture_output=True,
        )
        if check.returncode != 0:
            # Session gone — check orch-bridge for final state
            return self._check_orch_bridge(session_name)

        # 2. Check timeout
        start = self._start_times.get(session_name)
        if start and (time.monotonic() - start) > self.timeout_seconds:
            logger.warning("task %s timed out after %ds", session_name, self.timeout_seconds)
            subprocess.run(["tmux", "kill-session", "-t", session_name], capture_output=True)
            return TaskResult(status="timed_out", error=f"timeout after {self.timeout_seconds}s")

        # 3. Still running
        return TaskResult(status="running")

    def cancel(self, handle: str) -> bool:
        """Kill the tmux session."""
        result = subprocess.run(
            ["tmux", "kill-session", "-t", handle],
            capture_output=True,
        )
        return result.returncode == 0

    def cleanup(self, handle: str) -> None:
        """Remove progress file."""
        progress_file = Path.home() / ".openclaw/shared-context/progress" / f"{handle}.json"
        progress_file.unlink(missing_ok=True)

    def _check_orch_bridge(self, session_name: str) -> TaskResult:
        """Check orch-bridge for task completion status."""
        task_ref = "tsk_" + session_name.replace("nc-", "").replace("-", "_")
        try:
            result = subprocess.run(
                [str(ORCH_BRIDGE), "status", task_ref],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                state = data.get("state", "")
                if state == "completed":
                    summary = data.get("continuation", {}).get("stopped_because", "")
                    return TaskResult(status="completed", output=summary)
                elif state == "failed":
                    return TaskResult(status="failed", error="task failed")
        except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception) as e:
            logger.debug("orch-bridge check failed for %s: %s", session_name, e)

        # Session gone, no orch-bridge info — assume failed
        return TaskResult(status="failed", error="tmux session exited without completion")
