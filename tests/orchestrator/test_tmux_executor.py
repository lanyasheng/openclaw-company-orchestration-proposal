#!/usr/bin/env python3
"""
test_tmux_executor.py — TmuxTaskExecutor unit tests

Covers:
- execute(): dispatch.sh invocation, session name, map population
- poll(): 4 scenarios (running / idle-completed / jsonl-completed / failed)
- poll() timeout: cleanup + timed_out
- cancel(): tmux kill-session
- cleanup(): progress + task-registry + tmux kill + map cleared
- _task_session_map lifecycle
- _check_jsonl_log(): result event parsing
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest import TestCase, main
from unittest.mock import MagicMock, patch

# Add runtime/orchestrator to path
orchestrator_path = Path(__file__).parent.parent.parent / "runtime" / "orchestrator"
sys.path.insert(0, str(orchestrator_path))

os.environ.setdefault("OPENCLAW_TEST_MODE", "1")

from tmux_executor import TmuxTaskExecutor
from executor_interface import TaskResult

TASK_ID = "tsk_abc_123"
SESSION = "nc-review-abc-123"
WORKSPACE = "/tmp/test-workspace"
CTX = {"type": "review", "prompt": "review this PR"}


def _make_executor(**kw) -> TmuxTaskExecutor:
    defaults = dict(workspace_dir=WORKSPACE, timeout_seconds=3600, mode="interactive")
    defaults.update(kw)
    return TmuxTaskExecutor(**defaults)


def _ok(returncode=0, stdout="", stderr=""):
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


class _TmpHomeBase(TestCase):
    """Provides a real temp dir as fake $HOME so Path.home()/... works."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.fake_home = Path(self._tmpdir.name)
        self._patcher = patch("tmux_executor.Path.home", return_value=self.fake_home)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self._tmpdir.cleanup()

    # helpers
    def _progress_dir(self):
        d = self.fake_home / ".openclaw/shared-context/progress"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _task_dir(self):
        d = self.fake_home / ".openclaw/shared-context/task-registry/tasks"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _log_dir(self):
        d = self.fake_home / ".openclaw" / "logs"
        d.mkdir(parents=True, exist_ok=True)
        return d


# ── execute() ──────────────────────────────────────────────────────────

class TestExecute(TestCase):
    @patch("tmux_executor.subprocess.run", return_value=_ok())
    def test_returns_session_name(self, mock_run):
        handle = _make_executor().execute(TASK_ID, "Review PR", CTX)
        self.assertEqual(handle, SESSION)

    @patch("tmux_executor.subprocess.run", return_value=_ok())
    def test_dispatch_cmd_args(self, mock_run):
        _make_executor().execute(TASK_ID, "Review PR", CTX)
        args = mock_run.call_args[0][0]
        for expected in ("--type", "review", "--id", "abc-123",
                         "--prompt", "review this PR",
                         "--project-dir", WORKSPACE, "--mode", "interactive"):
            self.assertIn(expected, args)

    @patch("tmux_executor.subprocess.run", return_value=_ok())
    def test_populates_session_map(self, mock_run):
        ex = _make_executor()
        handle = ex.execute(TASK_ID, "l", CTX)
        self.assertEqual(ex._task_session_map[handle], TASK_ID)
        self.assertIn(handle, ex._start_times)

    @patch("tmux_executor.subprocess.run", return_value=_ok(returncode=1, stderr="boom"))
    def test_raises_on_dispatch_failure(self, mock_run):
        with self.assertRaises(RuntimeError) as ctx:
            _make_executor().execute(TASK_ID, "l", CTX)
        self.assertIn("boom", str(ctx.exception))


# ── poll(): 4 scenarios ───────────────────────────────────────────────

class TestPollRunning(_TmpHomeBase):
    """tmux alive + no progress -> running."""

    @patch("tmux_executor.subprocess.run", return_value=_ok(returncode=0))
    def test_running(self, mock_run):
        ex = _make_executor()
        ex._start_times[SESSION] = time.monotonic()
        self.assertEqual(ex.poll(SESSION).status, "running")


class TestPollCompleted(_TmpHomeBase):
    """tmux alive + progress idle-waiting-input -> completed."""

    def test_completed_on_idle(self):
        pdir = self._progress_dir()
        (pdir / f"{SESSION}.json").write_text(
            json.dumps({"phase": "idle-waiting-input"})
        )

        def fake_run(cmd, **kw):
            if "has-session" in cmd:
                return _ok(returncode=0)
            if "capture-pane" in cmd:
                return _ok(stdout="last 10 lines of output")
            return _ok()

        with patch("tmux_executor.subprocess.run", side_effect=fake_run):
            ex = _make_executor()
            ex._start_times[SESSION] = time.monotonic()
            result = ex.poll(SESSION)

        self.assertEqual(result.status, "completed")
        self.assertIn("last 10 lines", result.output)
        # progress file should have been deleted
        self.assertFalse((pdir / f"{SESSION}.json").exists())


class TestPollSessionGoneJsonl(_TmpHomeBase):
    """tmux gone + JSONL has result -> completed."""

    def test_completed_from_jsonl(self):
        logdir = self._log_dir()
        (logdir / f"{SESSION}.jsonl").write_text(
            json.dumps({"type": "result", "result": "all good"}) + "\n"
        )

        def fake_run(cmd, **kw):
            if "has-session" in cmd:
                return _ok(returncode=1)
            return _ok()

        with patch("tmux_executor.subprocess.run", side_effect=fake_run):
            ex = _make_executor()
            ex._start_times[SESSION] = time.monotonic()
            result = ex.poll(SESSION)

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.output, "all good")


class TestPollSessionGoneFailed(_TmpHomeBase):
    """tmux gone + no JSONL -> failed."""

    def test_failed(self):
        def fake_run(cmd, **kw):
            if "has-session" in cmd:
                return _ok(returncode=1)
            return _ok()

        with patch("tmux_executor.subprocess.run", side_effect=fake_run):
            ex = _make_executor()
            ex._start_times[SESSION] = time.monotonic()
            result = ex.poll(SESSION)

        self.assertEqual(result.status, "failed")
        self.assertIn("exited without completion", result.error)


# ── poll() timeout ─────────────────────────────────────────────────────

class TestPollTimeout(_TmpHomeBase):
    """elapsed > timeout -> cleanup + timed_out."""

    def test_timed_out(self):
        # Ensure cleanup dirs exist so unlink(missing_ok) works on real paths
        self._progress_dir()
        self._task_dir()

        def fake_run(cmd, **kw):
            if "has-session" in cmd:
                return _ok(returncode=0)  # session alive
            return _ok()

        with patch("tmux_executor.subprocess.run", side_effect=fake_run):
            ex = _make_executor(timeout_seconds=10)
            ex._start_times[SESSION] = time.monotonic() - 100
            ex._task_session_map[SESSION] = TASK_ID
            result = ex.poll(SESSION)

        self.assertEqual(result.status, "timed_out")
        self.assertIn("timeout", result.error)
        self.assertNotIn(SESSION, ex._task_session_map)
        self.assertNotIn(SESSION, ex._start_times)


# ── cancel() ───────────────────────────────────────────────────────────

class TestCancel(TestCase):
    @patch("tmux_executor.subprocess.run", return_value=_ok(returncode=0))
    def test_success(self, mock_run):
        self.assertTrue(_make_executor().cancel(SESSION))
        self.assertEqual(mock_run.call_args[0][0],
                         ["tmux", "kill-session", "-t", SESSION])

    @patch("tmux_executor.subprocess.run", return_value=_ok(returncode=1))
    def test_failure(self, mock_run):
        self.assertFalse(_make_executor().cancel(SESSION))


# ── cleanup() ──────────────────────────────────────────────────────────

class TestCleanup(_TmpHomeBase):
    def test_full_cleanup(self):
        pdir = self._progress_dir()
        tdir = self._task_dir()
        pfile = pdir / f"{SESSION}.json"
        tfile = tdir / f"{TASK_ID}.json"
        pfile.write_text("{}")
        tfile.write_text("{}")

        with patch("tmux_executor.subprocess.run", return_value=_ok()) as mock_run:
            ex = _make_executor()
            ex._task_session_map[SESSION] = TASK_ID
            ex._start_times[SESSION] = 1.0
            ex.cleanup(SESSION)

        self.assertFalse(pfile.exists())
        self.assertFalse(tfile.exists())
        mock_run.assert_called_once_with(
            ["tmux", "kill-session", "-t", SESSION], capture_output=True,
        )
        self.assertNotIn(SESSION, ex._task_session_map)
        self.assertNotIn(SESSION, ex._start_times)


# ── _task_session_map lifecycle ────────────────────────────────────────

class TestSessionMapLifecycle(_TmpHomeBase):
    @patch("tmux_executor.subprocess.run", return_value=_ok())
    def test_execute_then_cleanup(self, mock_run):
        ex = _make_executor()
        handle = ex.execute(TASK_ID, "l", CTX)
        self.assertIn(handle, ex._task_session_map)
        self.assertIn(handle, ex._start_times)

        # Ensure dirs exist for cleanup
        self._progress_dir()
        self._task_dir()
        ex.cleanup(handle)

        self.assertNotIn(handle, ex._task_session_map)
        self.assertNotIn(handle, ex._start_times)


# ── _check_jsonl_log() ────────────────────────────────────────────────

class TestCheckJsonlLog(_TmpHomeBase):
    def test_returns_completed_on_result_event(self):
        logdir = self._log_dir()
        (logdir / f"{SESSION}.jsonl").write_text("\n".join([
            json.dumps({"type": "start", "id": "1"}),
            json.dumps({"type": "content", "text": "working"}),
            json.dumps({"type": "result", "result": "done"}),
        ]))
        r = _make_executor()._check_jsonl_log(SESSION)
        self.assertEqual(r.status, "completed")
        self.assertEqual(r.output, "done")

    def test_returns_none_when_no_file(self):
        # log dir exists but no file for this session
        self._log_dir()
        self.assertIsNone(_make_executor()._check_jsonl_log(SESSION))

    def test_returns_none_when_no_result_event(self):
        logdir = self._log_dir()
        (logdir / f"{SESSION}.jsonl").write_text(
            json.dumps({"type": "content", "text": "still working"}) + "\n"
        )
        self.assertIsNone(_make_executor()._check_jsonl_log(SESSION))


if __name__ == "__main__":
    main()
