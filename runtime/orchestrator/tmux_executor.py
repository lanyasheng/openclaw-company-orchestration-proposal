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

# Default to orchestrator's own scripts; projects override via env vars
_ORCH_SCRIPTS = Path(__file__).resolve().parent.parent.parent / "scripts"
DISPATCH_SCRIPT = Path(os.environ.get(
    "OPENCLAW_DISPATCH_SCRIPT",
    str(_ORCH_SCRIPTS / "start-tmux-task.sh"),
))
STATUS_SCRIPT = Path(os.environ.get(
    "OPENCLAW_STATUS_SCRIPT",
    str(_ORCH_SCRIPTS / "status-tmux-task.sh"),
))
SESSION_PREFIX = os.environ.get("OPENCLAW_SESSION_PREFIX", "oc")



class TmuxTaskExecutor(TaskExecutorBase):
    """Execute tasks in tmux sessions via dispatch.sh."""

    def __init__(
        self,
        workspace_dir: str,
        timeout_seconds: int = 3600,
        mode: str = "interactive",
    ):
        self.workspace_dir = workspace_dir
        self.timeout_seconds = timeout_seconds
        self.mode = mode
        self._start_times: dict[str, float] = {}
        # session_name -> task_id mapping to avoid fragile reverse reconstruction
        self._task_session_map: dict[str, str] = {}

    def execute(self, task_id: str, label: str, context: Dict[str, Any]) -> str:
        """Start a tmux session with Claude Code. Returns session name as handle."""
        task_type = context.get("type", "review")
        prompt = context.get("prompt", label)
        task_short_id = task_id.replace("tsk_", "").replace("_", "-")
        session_label = f"{task_type}-{task_short_id}"
        session_name = f"{SESSION_PREFIX}-{session_label}"

        # start-tmux-task.sh interface: --label/--workdir/--task [--type]
        cmd = [
            str(DISPATCH_SCRIPT),
            "--label", session_label,
            "--workdir", self.workspace_dir,
            "--task", prompt,
            "--type", task_type,
        ]

        logger.info("dispatching %s -> %s", task_id, session_name)
        # 60s: lock wait (30s max) + tmux create + CC init wait (15s max)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        if result.returncode != 0:
            error = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(f"dispatch failed for {task_id}: {error}")

        self._start_times[session_name] = time.monotonic()
        self._task_session_map[session_name] = task_id
        return session_name

    def poll(self, handle: str) -> TaskResult:
        """Check tmux session status. handle is the session name."""
        session_name = handle

        # 1. Check if tmux session still exists
        try:
            check = subprocess.run(
                ["tmux", "has-session", "-t", session_name],
                capture_output=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            logger.warning("tmux has-session timed out for %s", session_name)
            return TaskResult(status="running")
        if check.returncode != 0:
            # Session gone — check JSONL log for final state
            return self._check_orch_bridge(session_name)

        # 2. Check progress file for interactive mode completion
        #    on-stop.sh writes phase=idle-waiting-input when CC finishes a turn
        progress_file = Path.home() / ".openclaw/shared-context/progress" / f"{session_name}.json"
        if progress_file.exists():
            try:
                pdata = json.loads(progress_file.read_text())
                if pdata.get("phase") == "idle-waiting-input":
                    logger.info("task %s completed (interactive mode, idle-waiting-input)", session_name)
                    # Capture last output as summary
                    summary = ""
                    try:
                        cap = subprocess.run(
                            ["tmux", "capture-pane", "-t", session_name, "-p", "-S", "-10"],
                            capture_output=True, text=True, timeout=5,
                        )
                        summary = cap.stdout.strip()[-500:] if cap.stdout else ""
                    except Exception:
                        pass
                    # Clean up progress file
                    progress_file.unlink(missing_ok=True)
                    # Kill the session (task is done, CC is waiting for input we won't send)
                    try:
                        subprocess.run(["tmux", "kill-session", "-t", session_name], capture_output=True, timeout=30)
                    except subprocess.TimeoutExpired:
                        logger.warning("tmux kill-session timed out for %s", session_name)
                    return TaskResult(status="completed", output=summary)
            except (json.JSONDecodeError, OSError):
                pass

        # 3. Check timeout
        start = self._start_times.get(session_name)
        if start and (time.monotonic() - start) > self.timeout_seconds:
            logger.warning("task %s timed out after %ds", session_name, self.timeout_seconds)
            # cleanup() handles progress file removal, task-registry cleanup,
            # and kill-session (tolerates already-dead sessions)
            self.cleanup(session_name)
            return TaskResult(status="timed_out", error=f"timeout after {self.timeout_seconds}s")

        # 4. Still running
        return TaskResult(status="running")

    def cancel(self, handle: str) -> bool:
        """Kill the tmux session."""
        try:
            result = subprocess.run(
                ["tmux", "kill-session", "-t", handle],
                capture_output=True,
                timeout=30,
            )
            return result.returncode == 0
        except subprocess.TimeoutExpired:
            logger.warning("tmux kill-session timed out for %s", handle)
            return False

    def cleanup(self, handle: str) -> None:
        """Clean up all state sources for a completed task."""
        session_name = handle

        # 1. Remove progress file
        progress_file = Path.home() / ".openclaw/shared-context/progress" / f"{session_name}.json"
        progress_file.unlink(missing_ok=True)

        # 2. Remove task-registry file directly
        task_ref = self._task_session_map.get(
            session_name,
            "tsk_" + session_name.replace(f"{SESSION_PREFIX}-", "", 1).replace("-", "_"),
        )
        task_file = Path.home() / ".openclaw/shared-context/task-registry/tasks" / f"{task_ref}.json"
        task_file.unlink(missing_ok=True)

        # 3. Kill tmux session if still alive
        try:
            subprocess.run(["tmux", "kill-session", "-t", session_name], capture_output=True, timeout=30)
        except subprocess.TimeoutExpired:
            logger.warning("tmux kill-session timed out during cleanup for %s", session_name)

        # 4. Remove session from in-memory map to avoid memory leak
        self._task_session_map.pop(session_name, None)
        self._start_times.pop(session_name, None)

        logger.info("cleanup completed for %s", session_name)

    def _check_jsonl_log(self, session_name: str) -> TaskResult | None:
        """Check the JSONL log file for a 'result' event from headless mode.

        In headless mode Claude Code writes stream-json to
        ``~/.openclaw/logs/{session_name}.jsonl``.  If the session's tmux
        window has already exited but a ``result`` event exists in the log,
        the task actually completed successfully.
        """
        log_path = Path.home() / ".openclaw" / "logs" / f"{session_name}.jsonl"
        if not log_path.exists():
            return None
        try:
            # Read in reverse so we find the last result quickly
            lines = log_path.read_text().splitlines()
            for line in reversed(lines):
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "result":
                    summary = event.get("result", event.get("output", ""))
                    logger.info(
                        "task %s completed per JSONL log (session already gone)",
                        session_name,
                    )
                    return TaskResult(status="completed", output=str(summary))
        except Exception as e:
            logger.debug("JSONL log check failed for %s: %s", session_name, e)
        return None

    def _check_orch_bridge(self, session_name: str) -> TaskResult:
        """Check for task completion status after tmux session has exited."""
        # Check JSONL log (headless mode may have finished cleanly)
        jsonl_result = self._check_jsonl_log(session_name)
        if jsonl_result is not None:
            return jsonl_result

        # Session gone, no JSONL result — assume failed
        return TaskResult(status="failed", error="tmux session exited without completion")
