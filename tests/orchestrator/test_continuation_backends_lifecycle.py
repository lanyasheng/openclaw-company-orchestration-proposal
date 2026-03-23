"""
test_continuation_backends_lifecycle.py — P0-3 Batch 6: Generic lifecycle kernel tests

Tests for the backend-agnostic watchdog/lifecycle logic introduced in P0-3 Batch 6.

Coverage:
- GenericBackendStatus enum
- BackendLifecycleConfig for tmux and subagent
- Status mapping from backend-native to generic
- decide_watchdog_action() with generic status
- Backward compatibility with existing tmux/subagent paths
"""

from __future__ import annotations

import pytest
from pathlib import Path
from typing import Any, Dict

import sys
import os

# Add orchestrator directory to path for imports
REPO_ROOT = Path(__file__).resolve().parents[2]
ORCHESTRATOR_DIR = REPO_ROOT / "runtime" / "orchestrator"
if str(ORCHESTRATOR_DIR) not in sys.path:
    sys.path.insert(0, str(ORCHESTRATOR_DIR))

# Import from continuation_backends module
from continuation_backends import (  # type: ignore
    GenericBackendStatus,
    BackendLifecycleConfig,
    decide_watchdog_action,
    build_timeout_policy,
    DEFAULT_TIMEOUT_TOTAL_SECONDS,
    DEFAULT_TIMEOUT_STALL_SECONDS,
    DEFAULT_STALL_GRACE_SECONDS,
)


class TestGenericBackendStatus:
    """Tests for GenericBackendStatus enum."""
    
    def test_enum_members(self):
        """Verify all expected status members exist."""
        assert GenericBackendStatus.DONE.value == "done"
        assert GenericBackendStatus.STUCK.value == "stuck"
        assert GenericBackendStatus.RUNNING.value == "running"
        assert GenericBackendStatus.IDLE.value == "idle"
        assert GenericBackendStatus.UNKNOWN.value == "unknown"
    
    def test_status_from_string(self):
        """Test status enum lookup."""
        assert GenericBackendStatus("done") == GenericBackendStatus.DONE
        assert GenericBackendStatus("stuck") == GenericBackendStatus.STUCK
        assert GenericBackendStatus("running") == GenericBackendStatus.RUNNING
        assert GenericBackendStatus("idle") == GenericBackendStatus.IDLE
        assert GenericBackendStatus("unknown") == GenericBackendStatus.UNKNOWN


class TestBackendLifecycleConfig:
    """Tests for BackendLifecycleConfig."""
    
    def test_tmux_config_done_statuses(self):
        """Tmux config should have correct done statuses."""
        config = BackendLifecycleConfig.for_tmux()
        assert "likely_done" in config.done_statuses
        assert "done_session_ended" in config.done_statuses
    
    def test_tmux_config_stuck_statuses(self):
        """Tmux config should have correct stuck statuses."""
        config = BackendLifecycleConfig.for_tmux()
        assert "dead" in config.stuck_statuses
        assert "stuck" in config.stuck_statuses
    
    def test_tmux_config_observe_statuses(self):
        """Tmux config should have correct observe statuses."""
        config = BackendLifecycleConfig.for_tmux()
        assert "running" in config.observe_statuses
        assert "idle" in config.observe_statuses
    
    def test_subagent_config_done_statuses(self):
        """Subagent config should have correct done statuses."""
        config = BackendLifecycleConfig.for_subagent()
        assert "completed" in config.done_statuses
        assert "done" in config.done_statuses
    
    def test_subagent_config_stuck_statuses(self):
        """Subagent config should have correct stuck statuses."""
        config = BackendLifecycleConfig.for_subagent()
        assert "failed" in config.stuck_statuses
        assert "timeout" in config.stuck_statuses
    
    def test_subagent_config_observe_statuses(self):
        """Subagent config should have correct observe statuses."""
        config = BackendLifecycleConfig.for_subagent()
        assert "running" in config.observe_statuses
        assert "pending" in config.observe_statuses
    
    def test_tmux_map_status_done(self):
        """Tmux config should map done statuses correctly."""
        config = BackendLifecycleConfig.for_tmux()
        assert config.map_status("likely_done") == GenericBackendStatus.DONE
        assert config.map_status("done_session_ended") == GenericBackendStatus.DONE
        assert config.map_status("DONE") == GenericBackendStatus.DONE  # case insensitive
    
    def test_tmux_map_status_stuck(self):
        """Tmux config should map stuck statuses correctly."""
        config = BackendLifecycleConfig.for_tmux()
        assert config.map_status("dead") == GenericBackendStatus.STUCK
        assert config.map_status("stuck") == GenericBackendStatus.STUCK
        assert config.map_status("STUCK") == GenericBackendStatus.STUCK  # case insensitive
    
    def test_tmux_map_status_running(self):
        """Tmux config should map running statuses correctly."""
        config = BackendLifecycleConfig.for_tmux()
        assert config.map_status("running") == GenericBackendStatus.RUNNING
        assert config.map_status("idle") == GenericBackendStatus.IDLE
    
    def test_tmux_map_status_unknown(self):
        """Tmux config should map unknown statuses to UNKNOWN."""
        config = BackendLifecycleConfig.for_tmux()
        assert config.map_status("random_status") == GenericBackendStatus.UNKNOWN
        assert config.map_status("") == GenericBackendStatus.UNKNOWN
        assert config.map_status(None) == GenericBackendStatus.UNKNOWN  # type: ignore
    
    def test_subagent_map_status_done(self):
        """Subagent config should map done statuses correctly."""
        config = BackendLifecycleConfig.for_subagent()
        assert config.map_status("completed") == GenericBackendStatus.DONE
        assert config.map_status("done") == GenericBackendStatus.DONE
    
    def test_subagent_map_status_stuck(self):
        """Subagent config should map stuck statuses correctly."""
        config = BackendLifecycleConfig.for_subagent()
        assert config.map_status("failed") == GenericBackendStatus.STUCK
        assert config.map_status("timeout") == GenericBackendStatus.STUCK
    
    def test_subagent_map_status_running(self):
        """Subagent config should map running statuses correctly."""
        config = BackendLifecycleConfig.for_subagent()
        assert config.map_status("running") == GenericBackendStatus.RUNNING
        assert config.map_status("pending") == GenericBackendStatus.RUNNING


class TestDecideWatchdogAction:
    """Tests for decide_watchdog_action() with generic lifecycle kernel."""
    
    def test_canonical_business_terminal_recorded(self):
        """Should collect report when canonical business terminal already recorded."""
        result = decide_watchdog_action(
            backend="tmux",
            status="final_closed",
            retry_count=0,
            report_exists=False,
        )
        assert result["action"] == "collect_report"
        assert result["reason"] == "canonical_business_terminal_recorded"
    
    def test_await_canonical_callback_when_report_exists(self):
        """Should await canonical callback when report exists."""
        result = decide_watchdog_action(
            backend="tmux",
            status="likely_done",
            retry_count=0,
            report_exists=True,
        )
        assert result["action"] == "await_canonical_callback"
        assert result["reason"] == "completion_artifact_ready_but_canonical_callback_required"
    
    def test_await_completion_artifact_when_done_no_report(self):
        """Should await completion artifact when backend reports done but no report."""
        result = decide_watchdog_action(
            backend="tmux",
            status="likely_done",
            retry_count=0,
            report_exists=False,
        )
        assert result["action"] == "await_completion_artifact"
        assert result["reason"] == "backend_reports_done_but_no_completion_artifact"
    
    def test_manual_takeover_on_total_timeout(self):
        """Should manual takeover when total timeout exceeded."""
        result = decide_watchdog_action(
            backend="tmux",
            status="running",
            retry_count=0,
            elapsed_total_seconds=DEFAULT_TIMEOUT_TOTAL_SECONDS + 60,
            report_exists=False,
        )
        assert result["action"] == "manual_takeover"
        assert result["reason"] == "timeout_total_exceeded"
    
    def test_retry_once_on_first_stuck(self):
        """Should retry once on first stuck event."""
        result = decide_watchdog_action(
            backend="tmux",
            status="stuck",
            retry_count=0,
            report_exists=False,
        )
        assert result["action"] == "retry_once"
        assert result["reason"] == "status_stuck_or_dead"
    
    def test_manual_takeover_after_retry_limit(self):
        """Should manual takeover after retry limit."""
        result = decide_watchdog_action(
            backend="tmux",
            status="stuck",
            retry_count=1,
            report_exists=False,
        )
        assert result["action"] == "manual_takeover"
        assert result["reason"] == "status_stuck_or_dead_after_retry_limit"
    
    def test_manual_takeover_on_stall_window_exceeded(self):
        """Should manual takeover when stall window exceeded."""
        stall_limit = DEFAULT_TIMEOUT_STALL_SECONDS + DEFAULT_STALL_GRACE_SECONDS
        # Use retry_count=1 to skip retry_once and go straight to manual_takeover
        result = decide_watchdog_action(
            backend="tmux",
            status="idle",
            retry_count=1,  # Already consumed retry
            elapsed_idle_seconds=stall_limit + 60,
            report_exists=False,
        )
        assert result["action"] == "manual_takeover"
        assert result["reason"] == "stall_window_exceeded_after_retry_limit"
    
    def test_observe_when_within_budget(self):
        """Should observe when still within timeout/stall budget."""
        result = decide_watchdog_action(
            backend="tmux",
            status="running",
            retry_count=0,
            elapsed_total_seconds=60,
            elapsed_idle_seconds=30,
            report_exists=False,
        )
        assert result["action"] == "observe"
        assert result["reason"] == "still within timeout/stall budget"
    
    def test_subagent_backend_stuck_handling(self):
        """Should handle subagent backend stuck status correctly."""
        result = decide_watchdog_action(
            backend="subagent",
            status="failed",
            retry_count=0,
            report_exists=False,
        )
        assert result["action"] == "retry_once"
        assert result["reason"] == "status_stuck_or_dead"
    
    def test_subagent_backend_done_handling(self):
        """Should handle subagent backend done status correctly."""
        result = decide_watchdog_action(
            backend="subagent",
            status="completed",
            retry_count=0,
            report_exists=False,
        )
        assert result["action"] == "await_completion_artifact"
        assert result["reason"] == "backend_reports_done_but_no_completion_artifact"
    
    def test_policy_included_in_result(self):
        """Should include timeout policy in result."""
        result = decide_watchdog_action(
            backend="tmux",
            status="running",
            retry_count=0,
            report_exists=False,
        )
        assert "policy" in result
        assert result["policy"]["backend"] == "tmux"
        assert result["policy"]["timeout_total_seconds"] == DEFAULT_TIMEOUT_TOTAL_SECONDS


class TestBackwardCompatibility:
    """Tests for backward compatibility with existing code."""
    
    def test_tmux_status_constants_still_available(self):
        """Tmux status constants should still be available from tmux_terminal_receipts."""
        from tmux_terminal_receipts import (  # type: ignore
            TERMINAL_DONE_STATUSES,
            TERMINAL_FAILED_STATUSES,
            NON_TERMINAL_STATUSES,
        )
        assert "likely_done" in TERMINAL_DONE_STATUSES
        assert "dead" in TERMINAL_FAILED_STATUSES
        assert "running" in NON_TERMINAL_STATUSES
    
    def test_decide_watchdog_action_signature_unchanged(self):
        """decide_watchdog_action() signature should be unchanged for backward compatibility."""
        import inspect
        sig = inspect.signature(decide_watchdog_action)
        params = list(sig.parameters.keys())
        assert "backend" in params
        assert "status" in params
        assert "retry_count" in params
        assert "elapsed_total_seconds" in params
        assert "elapsed_idle_seconds" in params
        assert "report_exists" in params
    
    def test_build_timeout_policy_tmux_statuses(self):
        """build_timeout_policy() should still include tmux_statuses for backward compatibility."""
        policy = build_timeout_policy("tmux")
        assert "backend_statuses" in policy
        assert "done" in policy["backend_statuses"]
        assert "stuck" in policy["backend_statuses"]
        assert "observe" in policy["backend_statuses"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
