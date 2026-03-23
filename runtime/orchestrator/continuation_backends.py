from __future__ import annotations

import shlex
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Protocol

# P0-3 Batch 4 (2026-03-23): BACKEND POLICY UPDATE
# - 'subagent' backend: PRIMARY AND DEFAULT recommended backend for ALL new development
# - 'tmux' backend: COMPATIBILITY-ONLY legacy path retained for EXISTING production dispatches
#   DO NOT USE tmux backend for new development; migrate existing dispatches to subagent
#
# P0-3 Batch 2 + Batch 3: Legacy compatibility note
# - 'subagent' backend: Primary live path for trading continuation (2026-03-23)
# - 'tmux' backend: Legacy compatibility layer for observable sessions; retained for backward compatibility
#   but new development should prefer subagent backend with runner-based observation
# P0-3 Batch 3 (2026-03-23): tmux bridge commands `describe`, `capture`, `attach` are deprecated
#   due to low usage. Core commands (`prepare`, `start`, `status`, `receipt`, `complete`) remain supported.
#
# P0-3 Batch 6 (2026-03-23): Generic lifecycle kernel — extract backend-agnostic watchdog/lifecycle logic
# - Move tmux-specific status constants to tmux_terminal_receipts.py
# - Add GenericBackendStatus enum for backend-agnostic lifecycle states
# - Add BackendStatusAdapter Protocol for backend-specific status mapping
# - Refactor decide_watchdog_action() to use generic status types

SUPPORTED_DISPATCH_BACKENDS = ("subagent", "tmux")
DEFAULT_DISPATCH_BACKEND = "subagent"

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
TMUX_BRIDGE_SCRIPT = WORKSPACE_ROOT / "scripts" / "orchestrator_dispatch_bridge.py"
TMUX_START_SCRIPT = Path("~/.openclaw/skills/claude-code-orchestrator/scripts/start-tmux-task.sh").expanduser()
TMUX_STATUS_SCRIPT = Path("~/.openclaw/skills/claude-code-orchestrator/scripts/status-tmux-task.sh").expanduser()
TMUX_MONITOR_SCRIPT = Path("~/.openclaw/skills/claude-code-orchestrator/scripts/monitor-tmux-task.sh").expanduser()

DEFAULT_TIMEOUT_TOTAL_SECONDS = 30 * 60
DEFAULT_TIMEOUT_STALL_SECONDS = 10 * 60
DEFAULT_STALL_GRACE_SECONDS = 2 * 60
DEFAULT_RETRY_ONCE_LIMIT = 1
DEFAULT_RETRY_BACKOFF_SECONDS = 30


# ============ P0-3 Batch 6: Generic Lifecycle Kernel ============


class GenericBackendStatus(Enum):
    """
    Backend-agnostic lifecycle status for watchdog/lifecycle decisions.
    
    P0-3 Batch 6 (2026-03-23): Extracted from tmux-specific constants to enable
    multi-backend support and cleaner kernelization.
    
    Members:
    - DONE: Backend reports completion (artifact may or may not exist)
    - STUCK: Backend is stuck/dead/failed and needs intervention
    - RUNNING: Backend is actively making progress
    - IDLE: Backend is idle but not stuck (may be waiting for input)
    - UNKNOWN: Backend status is unknown or unrecognized
    """
    DONE = "done"
    STUCK = "stuck"
    RUNNING = "running"
    IDLE = "idle"
    UNKNOWN = "unknown"


class BackendStatusAdapter(Protocol):
    """
    Protocol for backend-specific status mapping to generic lifecycle states.
    
    P0-3 Batch 6 (2026-03-23): Allows different backends (tmux, subagent, etc.)
    to map their native status strings to GenericBackendStatus.
    
    Example implementations:
    - TmuxStatusAdapter: maps "likely_done", "stuck", "running", etc. to GenericBackendStatus
    - SubagentStatusAdapter: maps "completed", "failed", "running", etc. to GenericBackendStatus
    """
    
    def map_to_generic(self, native_status: str) -> GenericBackendStatus:
        """Map backend-native status string to GenericBackendStatus."""
        ...
    
    def get_done_statuses(self) -> set[str]:
        """Return set of native status strings that map to DONE."""
        ...
    
    def get_stuck_statuses(self) -> set[str]:
        """Return set of native status strings that map to STUCK."""
        ...


@dataclass
class BackendLifecycleConfig:
    """
    Configuration for backend-specific lifecycle behavior.
    
    P0-3 Batch 6 (2026-03-23): Encapsulates backend-specific lifecycle configuration
    to keep decide_watchdog_action() backend-agnostic.
    
    Attributes:
    - done_statuses: Native status strings that indicate completion
    - stuck_statuses: Native status strings that indicate stuck/dead state
    - observe_statuses: Native status strings that indicate ongoing observation
    - status_adapter: Optional adapter for status mapping (uses defaults if None)
    """
    done_statuses: set[str]
    stuck_statuses: set[str]
    observe_statuses: set[str]
    status_adapter: Optional[BackendStatusAdapter] = None
    
    @classmethod
    def for_tmux(cls) -> "BackendLifecycleConfig":
        """
        Create lifecycle config for tmux backend.
        
        P0-3 Batch 6 (2026-03-23): Moved from module-level constants to config.
        """
        # Import tmux-specific constants from tmux_terminal_receipts
        from tmux_terminal_receipts import (
            TERMINAL_DONE_STATUSES,
            TERMINAL_FAILED_STATUSES,
            NON_TERMINAL_STATUSES,
        )
        return cls(
            done_statuses=TERMINAL_DONE_STATUSES,
            stuck_statuses=TERMINAL_FAILED_STATUSES,
            observe_statuses=NON_TERMINAL_STATUSES,
        )
    
    @classmethod
    def for_subagent(cls) -> "BackendLifecycleConfig":
        """
        Create lifecycle config for subagent backend.
        
        P0-3 Batch 6 (2026-03-23): Subagent uses runner-based status.
        """
        return cls(
            done_statuses={"completed", "done", "final_closed"},
            stuck_statuses={"failed", "timeout", "stuck", "dead"},
            observe_statuses={"running", "pending", "started"},
        )
    
    def map_status(self, native_status: str) -> GenericBackendStatus:
        """
        Map native status string to GenericBackendStatus.
        
        Priority order:
        1. Use status_adapter if provided
        2. Fall back to config-based mapping
        3. Default to UNKNOWN
        """
        if self.status_adapter is not None:
            return self.status_adapter.map_to_generic(native_status)
        
        status = str(native_status or "").strip().lower()
        if status in self.done_statuses or status in {"done", "completed"}:
            return GenericBackendStatus.DONE
        if status in self.stuck_statuses or status in {"timeout", "failed", "stuck"}:
            return GenericBackendStatus.STUCK
        if status in self.observe_statuses:
            if status == "idle":
                return GenericBackendStatus.IDLE
            return GenericBackendStatus.RUNNING
        return GenericBackendStatus.UNKNOWN


def normalize_dispatch_backend(backend: str | None) -> str:
    resolved = str(backend or DEFAULT_DISPATCH_BACKEND).strip().lower()
    if resolved not in SUPPORTED_DISPATCH_BACKENDS:
        supported = ", ".join(SUPPORTED_DISPATCH_BACKENDS)
        raise ValueError(f"unsupported dispatch backend={resolved!r}; expected one of {supported}")
    return resolved


def _slugify(parts: Iterable[Any]) -> str:
    raw = "-".join(str(part or "") for part in parts).strip().lower()
    cleaned = []
    prev_dash = False
    for char in raw:
        if char.isalnum():
            cleaned.append(char)
            prev_dash = False
            continue
        if not prev_dash:
            cleaned.append("-")
            prev_dash = True
    value = "".join(cleaned).strip("-")
    return value or "dispatch"


def build_timeout_policy(backend: str) -> Dict[str, Any]:
    normalized_backend = normalize_dispatch_backend(backend)
    policy = {
        "backend": normalized_backend,
        "timeout_total_seconds": DEFAULT_TIMEOUT_TOTAL_SECONDS,
        "timeout_stall_seconds": DEFAULT_TIMEOUT_STALL_SECONDS,
        "stall_grace_seconds": DEFAULT_STALL_GRACE_SECONDS,
        "max_auto_retry": DEFAULT_RETRY_ONCE_LIMIT,
        "retry_backoff_seconds": DEFAULT_RETRY_BACKOFF_SECONDS,
        "stuck_definition": [],
        "retry_once_when": [],
        "manual_takeover_when": [],
    }

    # P0-3 Batch 6 (2026-03-23): Use generic lifecycle config instead of hardcoded tmux constants
    lifecycle_config = BackendLifecycleConfig.for_subagent() if normalized_backend == "subagent" else BackendLifecycleConfig.for_tmux()

    if normalized_backend == "subagent":
        policy["observer"] = "runner status.json + heartbeat + callback state"
        policy["business_terminal_source"] = "canonical_callback"
        policy["backend_terminal_role"] = "callback_status and runner artifacts are evidence; business closeout still follows callback processing"
        policy["stuck_definition"] = [
            "runner reports timeout/failed",
            f"no meaningful progress beyond timeout_stall_seconds={DEFAULT_TIMEOUT_STALL_SECONDS}",
            f"stall persists past stall_grace_seconds={DEFAULT_STALL_GRACE_SECONDS}",
        ]
    else:
        policy["observer"] = "tmux status-tmux-task.sh + monitor-tmux-task.sh + completion report existence"
        policy["business_terminal_source"] = "canonical_callback"
        policy["backend_terminal_role"] = "tmux status and completion report are diagnostic only until the structured callback is bridged"
        # P0-3 Batch 6: Use lifecycle config for status sets
        policy["backend_statuses"] = {
            "done": sorted(lifecycle_config.done_statuses),
            "stuck": sorted(lifecycle_config.stuck_statuses),
            "observe": sorted(lifecycle_config.observe_statuses),
        }
        policy["stuck_definition"] = [
            "status-tmux-task.sh returns STATUS=stuck or STATUS=dead before report exists",
            f"status stays idle beyond timeout_stall_seconds={DEFAULT_TIMEOUT_STALL_SECONDS} and exceeds stall_grace_seconds={DEFAULT_STALL_GRACE_SECONDS}",
            "session exits without completion report",
        ]

    policy["retry_once_when"] = [
        "first stuck/timeout event still looks recoverable and no completion report exists",
        "single backend restart can recover without widening scope",
    ]
    policy["manual_takeover_when"] = [
        "retry_once already consumed and task is still stuck/dead/timeout",
        f"elapsed wall clock exceeds timeout_total_seconds={DEFAULT_TIMEOUT_TOTAL_SECONDS}",
        "task needs scope change, blocker clarification, or human review",
    ]
    return policy


def decide_watchdog_action(
    *,
    backend: str,
    status: str,
    retry_count: int = 0,
    elapsed_total_seconds: int | None = None,
    elapsed_idle_seconds: int | None = None,
    report_exists: bool = False,
) -> Dict[str, Any]:
    """
    Decide watchdog action based on backend status and timeout policy.
    
    P0-3 Batch 6 (2026-03-23): Refactored to use generic lifecycle kernel.
    - Uses BackendLifecycleConfig for backend-specific status mapping
    - Backend-agnostic decision logic
    - Preserves backward compatibility with existing tmux/subagent paths
    
    Args:
    - backend: Backend name ("tmux" | "subagent" | future backends)
    - status: Backend-native status string (e.g., "likely_done", "stuck", "running")
    - retry_count: Number of auto-retries already attempted
    - elapsed_total_seconds: Total elapsed time since task start
    - elapsed_idle_seconds: Time since last meaningful progress
    - report_exists: Whether completion report artifact exists
    
    Returns:
    - Dict with action, reason, and policy
    
    Actions:
    - collect_report: Canonical business terminal already recorded
    - await_canonical_callback: Completion artifact ready, waiting for callback
    - await_completion_artifact: Backend reports done but no artifact yet
    - manual_takeover: Human intervention required
    - retry_once: Auto-retry once before manual takeover
    - observe: Still within timeout/stall budget
    """
    normalized_backend = normalize_dispatch_backend(backend)
    normalized_status = str(status or "unknown").strip().lower()
    policy = build_timeout_policy(normalized_backend)
    
    # P0-3 Batch 6: Use generic lifecycle config for status mapping
    lifecycle_config = BackendLifecycleConfig.for_subagent() if normalized_backend == "subagent" else BackendLifecycleConfig.for_tmux()
    generic_status = lifecycle_config.map_status(normalized_status)

    # Rule 1: Canonical business terminal already recorded
    if normalized_status in {"final_closed", "next_task_dispatched"}:
        return {
            "action": "collect_report",
            "reason": "canonical_business_terminal_recorded",
            "policy": policy,
        }

    # Rule 2: Completion artifact ready - await canonical callback
    if report_exists:
        return {
            "action": "await_canonical_callback",
            "reason": "completion_artifact_ready_but_canonical_callback_required",
            "policy": policy,
        }

    # Rule 3: Backend reports done but no artifact yet
    if generic_status == GenericBackendStatus.DONE:
        return {
            "action": "await_completion_artifact",
            "reason": "backend_reports_done_but_no_completion_artifact",
            "policy": policy,
        }

    # Rule 4: Total timeout exceeded - manual takeover
    if elapsed_total_seconds is not None and elapsed_total_seconds >= policy["timeout_total_seconds"]:
        return {
            "action": "manual_takeover",
            "reason": "timeout_total_exceeded",
            "policy": policy,
        }

    # Rule 5: Stall window exceeded or backend stuck
    stall_limit = policy["timeout_stall_seconds"] + policy["stall_grace_seconds"]
    idle_too_long = elapsed_idle_seconds is not None and elapsed_idle_seconds >= stall_limit
    stuck_now = generic_status == GenericBackendStatus.STUCK or idle_too_long

    if stuck_now:
        # P0-3 Batch 6: Use generic status for reason determination
        reason = "status_stuck_or_dead" if generic_status == GenericBackendStatus.STUCK else "stall_window_exceeded"
        if retry_count < policy["max_auto_retry"]:
            return {
                "action": "retry_once",
                "reason": reason,
                "policy": policy,
            }
        return {
            "action": "manual_takeover",
            "reason": f"{reason}_after_retry_limit",
            "policy": policy,
        }

    # Rule 6: Still observing - within budget
    return {
        "action": "observe",
        "reason": "still within timeout/stall budget",
        "policy": policy,
    }


def build_backend_plan(
    *,
    backend: str,
    dispatch_id: str,
    dispatch_path: Path,
    batch_id: str,
    scenario: str,
    adapter: str,
    workdir: Path,
    task_preview: str,
) -> Dict[str, Any]:
    """
    Build backend-specific execution plan.
    
    P0-3 Batch 6 (2026-03-23): Updated to use generic lifecycle config.
    
    Args:
    - backend: Backend name ("tmux" | "subagent")
    - dispatch_id: Dispatch identifier
    - dispatch_path: Path to dispatch JSON file
    - batch_id: Batch identifier
    - scenario: Scenario name
    - adapter: Adapter name
    - workdir: Working directory
    - task_preview: Task preview/description
    
    Returns:
    - Backend plan dict with commands, scripts, and metadata
    """
    normalized_backend = normalize_dispatch_backend(backend)
    dispatch_q = shlex.quote(str(dispatch_path))
    workdir_q = shlex.quote(str(workdir))
    task_preview_q = shlex.quote(task_preview)

    if normalized_backend == "subagent":
        # P0-3 Batch 4 (2026-03-23): subagent is PRIMARY recommended backend
        # P0-3 Batch 5 (2026-03-23): Reinforced - subagent is the ONLY default path for new development
        return {
            "backend": "subagent",
            "mode": "tool_managed_non_interactive",
            "observable_intermediate_state": False,
            "notes": [
                "PRIMARY RECOMMENDED BACKEND: Use sessions_spawn(runtime=\"subagent\") with recommended_spawn.task.",
                "Progress is primarily observed via runner artifacts (status.json, final-summary.json, final-report.md).",
                "For new development, ALWAYS prefer subagent backend over tmux backend.",
                "P0-3 Batch 5: This is the ONLY default path for new dispatches.",
            ],
        }

    # P0-3 Batch 5 (2026-03-23): COMPATIBILITY-ONLY LEGACY PATH
    # This tmux backend plan is retained ONLY for existing production dispatches that have not yet migrated.
    # DO NOT USE for new development. All new dispatches MUST use subagent backend.
    # Migration path: existing tmux dispatches should be migrated to subagent backend at next opportunity.
    label = _slugify([adapter, scenario, batch_id, dispatch_id.split("_")[-1]])[:48].strip("-") or "dispatch"
    session = f"cc-{label}"
    prompt_file = Path("/tmp") / f"{session}-dispatch-ref.md"

    # P0-3 Batch 5: Minimize tmux command surface - only essential commands for legacy migration
    # P0-3 Batch 6: Use lifecycle config for status sets (no longer hardcoded)
    return {
        "backend": "tmux",
        "mode": "interactive_observable",
        "observable_intermediate_state": True,
        "label": label,
        "session": session,
        "workdir": str(workdir),
        "prompt_file": str(prompt_file),
        "task_preview": task_preview,
        "scripts": {
            "bridge": str(TMUX_BRIDGE_SCRIPT),
            "start_tmux_task": str(TMUX_START_SCRIPT),
            "status_tmux_task": str(TMUX_STATUS_SCRIPT),
            # P0-3 Batch 5: monitor script retained only for legacy attach use cases (not recommended)
            "monitor_tmux_task": str(TMUX_MONITOR_SCRIPT),
        },
        "commands": {
            # P0-3 Batch 5: Only core lifecycle commands retained for migration path
            "prepare": f"python3 scripts/orchestrator_dispatch_bridge.py prepare --dispatch {dispatch_q}",
            "start": f"python3 scripts/orchestrator_dispatch_bridge.py start --dispatch {dispatch_q}",
            "status": f"python3 scripts/orchestrator_dispatch_bridge.py status --dispatch {dispatch_q}",
            "receipt": f"python3 scripts/orchestrator_dispatch_bridge.py receipt --dispatch {dispatch_q}",
            "complete": f"python3 scripts/orchestrator_dispatch_bridge.py complete --dispatch {dispatch_q} --task-id <tmux-task-id>",
            # P0-3 Batch 5: Deprecated commands removed - use subagent backend instead
            # P0-3 Batch 6: watchdog command removed from backend_plan - integrated into kernel
            # "start_dry_run": ...,
            # "capture": ...,  # Deprecated - low usage
            # "attach": ...,   # Deprecated - low usage
            # "watchdog": ..., # Internal use only - now part of continuation kernel
        },
        "notes": [
            "COMPATIBILITY-ONLY LEGACY BACKEND: Retained ONLY for existing production tmux dispatches awaiting migration.",
            "DO NOT USE for new development - ALL new dispatches MUST use subagent backend.",
            "Migration required: existing tmux dispatches should migrate to subagent at next opportunity.",
            "tmux backend provides interactive session separate from OpenClaw runtime process.",
            "tmux STATUS/completion report are diagnostic only; business closeout requires canonical callback bridge.",
            "P0-3 Batch 6: Watchdog/lifecycle logic now in continuation kernel (continuation_backends.py).",
        ],
    }
