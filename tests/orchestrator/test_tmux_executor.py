#!/usr/bin/env python3
"""test_tmux_executor.py — TmuxTaskExecutor unit tests (16 cases)."""
import json, os, sys, tempfile, time
from pathlib import Path
from unittest import TestCase, main
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "runtime" / "orchestrator"))
os.environ.setdefault("OPENCLAW_TEST_MODE", "1")

from tmux_executor import TmuxTaskExecutor
from executor_interface import TaskResult

TID = "tsk_abc_123"
SES = "oc-review-abc-123"
WS = "/tmp/test-workspace"
CTX = {"type": "review", "prompt": "review this PR"}


def _ex(**kw):
    d = dict(workspace_dir=WS, timeout_seconds=3600, mode="interactive")
    d.update(kw)
    return TmuxTaskExecutor(**d)


def _ok(rc=0, stdout="", stderr=""):
    m = MagicMock(); m.returncode = rc; m.stdout = stdout; m.stderr = stderr
    return m


class _Home(TestCase):
    """Real temp dir as fake $HOME so Path / works naturally."""
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.home = Path(self._td.name)
        self._p = patch("tmux_executor.Path.home", return_value=self.home)
        self._p.start()

    def tearDown(self):
        self._p.stop(); self._td.cleanup()

    def _mkd(self, rel):
        d = self.home / rel; d.mkdir(parents=True, exist_ok=True); return d

    def _progress_dir(self): return self._mkd(".openclaw/shared-context/progress")
    def _task_dir(self):     return self._mkd(".openclaw/shared-context/task-registry/tasks")
    def _log_dir(self):      return self._mkd(".openclaw/logs")


# ── execute() ──────────────────────────────────────────────────────────
class TestExecute(TestCase):
    @patch("tmux_executor.subprocess.run", return_value=_ok())
    def test_returns_session_name(self, _r):
        self.assertEqual(_ex().execute(TID, "l", CTX), SES)

    @patch("tmux_executor.subprocess.run", return_value=_ok())
    def test_dispatch_cmd_args(self, mr):
        _ex().execute(TID, "l", CTX)
        a = mr.call_args[0][0]
        for v in ("--type", "review", "--label", "review-abc-123",
                   "--task", "review this PR", "--workdir", WS):
            self.assertIn(v, a)

    @patch("tmux_executor.subprocess.run", return_value=_ok())
    def test_populates_map(self, _r):
        ex = _ex(); h = ex.execute(TID, "l", CTX)
        self.assertEqual(ex._task_session_map[h], TID)
        self.assertIn(h, ex._start_times)

    @patch("tmux_executor.subprocess.run", return_value=_ok(rc=1, stderr="boom"))
    def test_raises_on_failure(self, _r):
        with self.assertRaises(RuntimeError) as c:
            _ex().execute(TID, "l", CTX)
        self.assertIn("boom", str(c.exception))


# ── poll(): 4 scenarios ───────────────────────────────────────────────
class TestPollRunning(_Home):
    @patch("tmux_executor.subprocess.run", return_value=_ok())
    def test_running(self, _r):
        ex = _ex(); ex._start_times[SES] = time.monotonic()
        self.assertEqual(ex.poll(SES).status, "running")


class TestPollCompleted(_Home):
    def test_idle_waiting_input(self):
        pd = self._progress_dir()
        (pd / f"{SES}.json").write_text(json.dumps({"phase": "idle-waiting-input"}))

        def fr(cmd, **kw):
            if "has-session" in cmd:   return _ok()
            if "capture-pane" in cmd:  return _ok(stdout="last output")
            return _ok()

        with patch("tmux_executor.subprocess.run", side_effect=fr):
            ex = _ex(); ex._start_times[SES] = time.monotonic()
            r = ex.poll(SES)
        self.assertEqual(r.status, "completed")
        self.assertIn("last output", r.output)
        self.assertFalse((pd / f"{SES}.json").exists())


class TestPollGoneJsonl(_Home):
    def test_completed_from_jsonl(self):
        ld = self._log_dir()
        (ld / f"{SES}.jsonl").write_text(json.dumps({"type": "result", "result": "ok"}) + "\n")

        def fr(cmd, **kw):
            if "has-session" in cmd: return _ok(rc=1)
            return _ok()

        with patch("tmux_executor.subprocess.run", side_effect=fr):
            ex = _ex(); ex._start_times[SES] = time.monotonic()
            r = ex.poll(SES)
        self.assertEqual(r.status, "completed")
        self.assertEqual(r.output, "ok")


class TestPollGoneFailed(_Home):
    def test_failed(self):
        def fr(cmd, **kw):
            if "has-session" in cmd: return _ok(rc=1)
            return _ok()
        with patch("tmux_executor.subprocess.run", side_effect=fr):
            ex = _ex(); ex._start_times[SES] = time.monotonic()
            r = ex.poll(SES)
        self.assertEqual(r.status, "failed")
        self.assertIn("exited without completion", r.error)


# ── poll() timeout ─────────────────────────────────────────────────────
class TestPollTimeout(_Home):
    def test_timed_out(self):
        self._progress_dir(); self._task_dir()

        def fr(cmd, **kw):
            if "has-session" in cmd: return _ok()
            return _ok()

        with patch("tmux_executor.subprocess.run", side_effect=fr):
            ex = _ex(timeout_seconds=10)
            ex._start_times[SES] = time.monotonic() - 100
            ex._task_session_map[SES] = TID
            r = ex.poll(SES)
        self.assertEqual(r.status, "timed_out")
        self.assertIn("timeout", r.error)
        self.assertNotIn(SES, ex._task_session_map)
        self.assertNotIn(SES, ex._start_times)


# ── cancel() ───────────────────────────────────────────────────────────
class TestCancel(TestCase):
    @patch("tmux_executor.subprocess.run", return_value=_ok())
    def test_success(self, mr):
        self.assertTrue(_ex().cancel(SES))
        self.assertEqual(mr.call_args[0][0], ["tmux", "kill-session", "-t", SES])

    @patch("tmux_executor.subprocess.run", return_value=_ok(rc=1))
    def test_failure(self, _r):
        self.assertFalse(_ex().cancel(SES))


# ── cleanup() ──────────────────────────────────────────────────────────
class TestCleanup(_Home):
    def test_full(self):
        pd = self._progress_dir(); td = self._task_dir()
        pf = pd / f"{SES}.json"; tf = td / f"{TID}.json"
        pf.write_text("{}"); tf.write_text("{}")

        with patch("tmux_executor.subprocess.run", return_value=_ok()) as mr:
            ex = _ex(); ex._task_session_map[SES] = TID; ex._start_times[SES] = 1.0
            ex.cleanup(SES)

        self.assertFalse(pf.exists())
        self.assertFalse(tf.exists())
        mr.assert_called_once_with(["tmux", "kill-session", "-t", SES], capture_output=True, timeout=30)
        self.assertNotIn(SES, ex._task_session_map)
        self.assertNotIn(SES, ex._start_times)


# ── _task_session_map lifecycle ────────────────────────────────────────
class TestMapLifecycle(_Home):
    @patch("tmux_executor.subprocess.run", return_value=_ok())
    def test_execute_then_cleanup(self, _r):
        self._progress_dir(); self._task_dir()
        ex = _ex(); h = ex.execute(TID, "l", CTX)
        self.assertIn(h, ex._task_session_map)
        ex.cleanup(h)
        self.assertNotIn(h, ex._task_session_map)
        self.assertNotIn(h, ex._start_times)


# ── _check_jsonl_log() ────────────────────────────────────────────────
class TestCheckJsonl(_Home):
    def test_completed_on_result(self):
        ld = self._log_dir()
        (ld / f"{SES}.jsonl").write_text("\n".join([
            json.dumps({"type": "start"}),
            json.dumps({"type": "result", "result": "done"}),
        ]))
        r = _ex()._check_jsonl_log(SES)
        self.assertEqual(r.status, "completed")
        self.assertEqual(r.output, "done")

    def test_none_when_no_file(self):
        self._log_dir()
        self.assertIsNone(_ex()._check_jsonl_log(SES))

    def test_none_when_no_result_event(self):
        ld = self._log_dir()
        (ld / f"{SES}.jsonl").write_text(json.dumps({"type": "content"}) + "\n")
        self.assertIsNone(_ex()._check_jsonl_log(SES))


if __name__ == "__main__":
    main()
