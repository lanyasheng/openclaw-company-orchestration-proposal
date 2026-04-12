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
from typing import Any, Callable, Dict, Optional

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
        on_complete: Optional[Callable[[str], None]] = None,
    ):
        self.workspace_dir = workspace_dir
        self.timeout_seconds = timeout_seconds
        self.mode = mode
        self._start_times: dict[str, float] = {}
        # session_name -> task_id mapping to avoid fragile reverse reconstruction
        self._task_session_map: dict[str, str] = {}
        # Track sessions we've already sent /exit to, preventing double-exit
        # which causes SessionEnd hooks to fire twice
        self._exit_sent: set[str] = set()
        # Optional callback invoked when a task completes, before /exit.
        # Signature: on_complete(session_name: str) -> None
        # Injected by callers (e.g. patrol-engine) for notifications.
        self._on_complete = on_complete

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
            "--auto-exit",
        ]

        logger.info("dispatching %s -> %s", task_id, session_name)
        # 90s: lock wait (30s max) + tmux create + CC init wait (30s max) + paste
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=90)

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
        try:
            pdata = json.loads(progress_file.read_text())
            if pdata.get("phase") == "idle-waiting-input":
                # Guard: if Ralph is still active, this is a mid-loop stop, not completion
                ralph_file = Path.home() / ".openclaw/shared-context/sessions" / session_name / "ralph.json"
                ralph_active = False
                try:
                    ralph_data = json.loads(ralph_file.read_text())
                    ralph_active = ralph_data.get("active", False)
                except (FileNotFoundError, json.JSONDecodeError):
                    pass
                if ralph_active:
                    return TaskResult(status="running")
                if session_name not in self._exit_sent:
                    logger.info("task %s idle-waiting-input, sending /exit", session_name)
                    if self._on_complete:
                        try:
                            self._on_complete(session_name)
                        except Exception:
                            logger.warning("on_complete callback failed for %s", session_name, exc_info=True)
                    self._send_exit(session_name)
                    self._exit_sent.add(session_name)
                    self._write_completion_marker(session_name)
                # Don't return completed yet — let session die naturally,
                # giving on-session-end.sh time to run.
                return TaskResult(status="running")
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass

        # 2b. Check review-posted marker (task completed but progress file missing/deleted)
        #     This handles the case where CC finished but Stop hook didn't fire again.
        review_posted = Path.home() / ".openclaw/shared-context/results" / f"{session_name}.review-posted"
        if review_posted.exists():
            if session_name not in self._exit_sent:
                logger.info("task %s review-posted marker found, sending /exit", session_name)
                if self._on_complete:
                    try:
                        self._on_complete(session_name)
                    except Exception:
                        logger.debug("on_complete callback failed for %s", session_name)
                self._send_exit(session_name)
                self._exit_sent.add(session_name)
                self._write_completion_marker(session_name)
            return TaskResult(status="running")

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

    def _send_exit(self, session_name: str) -> None:
        """Send /exit to a tmux session, with kill-session fallback."""
        try:
            subprocess.run(
                ["tmux", "send-keys", "-t", session_name, "/exit", "Enter"],
                capture_output=True, timeout=5,
            )
        except (subprocess.TimeoutExpired, subprocess.SubprocessError):
            try:
                subprocess.run(
                    ["tmux", "kill-session", "-t", session_name],
                    capture_output=True, timeout=30,
                )
            except subprocess.TimeoutExpired:
                logger.warning("tmux kill-session timed out for %s", session_name)

    def _write_completion_marker(self, session_name: str) -> None:
        """Write a completion JSON so _check_orch_bridge can detect it after session dies."""
        result_json = Path.home() / ".openclaw/shared-context/results" / f"{session_name}.json"
        if not result_json.exists():
            try:
                from datetime import datetime, timezone
                data = {
                    "session": session_name,
                    "status": "completed",
                    "subtype": "completed",
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "content": "poll-detected completion",
                }
                tmp = result_json.with_suffix(f".{os.getpid()}.tmp")
                tmp.write_text(json.dumps(data))
                tmp.rename(result_json)
            except Exception:
                logger.warning("failed to write completion marker for %s", session_name, exc_info=True)

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

        # 4. Remove session from in-memory maps to avoid memory leak
        self._task_session_map.pop(session_name, None)
        self._start_times.pop(session_name, None)
        self._exit_sent.discard(session_name)

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
            logger.warning("JSONL log check failed for %s: %s", session_name, e)
        return None

    def _check_orch_bridge(self, session_name: str) -> TaskResult:
        """Check for task completion status after tmux session has exited."""
        # Check JSONL log (headless mode may have finished cleanly)
        jsonl_result = self._check_jsonl_log(session_name)
        if jsonl_result is not None:
            return jsonl_result

        # Check result JSON written by on-stop.sh auto-exit (interactive mode)
        result_json = Path.home() / ".openclaw/shared-context/results" / f"{session_name}.json"
        try:
            rdata = json.loads(result_json.read_text())
            if rdata.get("status") == "completed" or rdata.get("subtype") == "completed":
                logger.info(
                    "task %s completed per result JSON (session already gone)",
                    session_name,
                )
                return TaskResult(
                    status="completed",
                    output=rdata.get("content", "auto-exit completion"),
                )
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass

        # Session gone, no completion evidence — assume failed
        return TaskResult(status="failed", error="tmux session exited without completion")
