from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any, Dict, Iterable, List

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

TMUX_DONE_STATUSES = {"likely_done", "done_session_ended"}
TMUX_STUCK_STATUSES = {"stuck", "dead"}
TMUX_OBSERVE_STATUSES = {"running", "idle"}


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
        policy["tmux_statuses"] = {
            "done": sorted(TMUX_DONE_STATUSES),
            "stuck": sorted(TMUX_STUCK_STATUSES),
            "observe": sorted(TMUX_OBSERVE_STATUSES),
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
    normalized_backend = normalize_dispatch_backend(backend)
    normalized_status = str(status or "unknown").strip().lower()
    policy = build_timeout_policy(normalized_backend)

    if normalized_status in {"final_closed", "next_task_dispatched"}:
        return {
            "action": "collect_report",
            "reason": "canonical_business_terminal_recorded",
            "policy": policy,
        }

    if report_exists:
        return {
            "action": "await_canonical_callback",
            "reason": "completion_artifact_ready_but_canonical_callback_required",
            "policy": policy,
        }

    if normalized_status in TMUX_DONE_STATUSES or normalized_status in {"done", "completed"}:
        return {
            "action": "await_completion_artifact",
            "reason": "backend_reports_done_but_no_completion_artifact",
            "policy": policy,
        }

    if elapsed_total_seconds is not None and elapsed_total_seconds >= policy["timeout_total_seconds"]:
        return {
            "action": "manual_takeover",
            "reason": "timeout_total_exceeded",
            "policy": policy,
        }

    stall_limit = policy["timeout_stall_seconds"] + policy["stall_grace_seconds"]
    idle_too_long = elapsed_idle_seconds is not None and elapsed_idle_seconds >= stall_limit
    stuck_now = normalized_status in TMUX_STUCK_STATUSES or normalized_status in {"timeout", "failed", "stuck"} or idle_too_long

    if stuck_now:
        reason = "status_stuck_or_dead" if normalized_status in TMUX_STUCK_STATUSES or normalized_status in {"timeout", "failed", "stuck"} else "stall_window_exceeded"
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
    normalized_backend = normalize_dispatch_backend(backend)
    dispatch_q = shlex.quote(str(dispatch_path))
    workdir_q = shlex.quote(str(workdir))
    task_preview_q = shlex.quote(task_preview)

    if normalized_backend == "subagent":
        # P0-3 Batch 4 (2026-03-23): subagent is PRIMARY recommended backend
        return {
            "backend": "subagent",
            "mode": "tool_managed_non_interactive",
            "observable_intermediate_state": False,
            "notes": [
                "PRIMARY RECOMMENDED BACKEND: Use sessions_spawn(runtime=\"subagent\") with recommended_spawn.task.",
                "Progress is primarily observed via runner artifacts (status.json, final-summary.json, final-report.md).",
                "For new development, ALWAYS prefer subagent backend over tmux backend.",
            ],
        }

    label = _slugify([adapter, scenario, batch_id, dispatch_id.split("_")[-1]])[:48].strip("-") or "dispatch"
    session = f"cc-{label}"
    prompt_file = Path("/tmp") / f"{session}-dispatch-ref.md"

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
            "monitor_tmux_task": str(TMUX_MONITOR_SCRIPT),
        },
        "commands": {
            "prepare": f"python3 scripts/orchestrator_dispatch_bridge.py prepare --dispatch {dispatch_q}",
            "start": f"python3 scripts/orchestrator_dispatch_bridge.py start --dispatch {dispatch_q}",
            "start_dry_run": f"python3 scripts/orchestrator_dispatch_bridge.py start --dispatch {dispatch_q} --dry-run",
            "status": f"python3 scripts/orchestrator_dispatch_bridge.py status --dispatch {dispatch_q}",
            "capture": f"python3 scripts/orchestrator_dispatch_bridge.py capture --dispatch {dispatch_q}",
            "attach": f"python3 scripts/orchestrator_dispatch_bridge.py attach --dispatch {dispatch_q}",
            "receipt": f"python3 scripts/orchestrator_dispatch_bridge.py receipt --dispatch {dispatch_q}",
            "complete_template": f"python3 scripts/orchestrator_dispatch_bridge.py complete --dispatch {dispatch_q} --task-id <tmux-task-id>",
            "watchdog": f"python3 scripts/orchestrator_dispatch_bridge.py watchdog --dispatch {dispatch_q} --tmux-status running",
        },
        "manual_start_equivalent": " ".join(
            [
                "bash",
                shlex.quote(str(TMUX_START_SCRIPT)),
                "--label",
                shlex.quote(label),
                "--workdir",
                workdir_q,
                "--prompt-file",
                shlex.quote(str(prompt_file)),
                "--task",
                task_preview_q,
                "--lint-cmd",
                "''",
                "--build-cmd",
                "''",
            ]
        ),
        "notes": [
            "COMPATIBILITY-ONLY LEGACY BACKEND: Retained for existing production tmux dispatches.",
            "DO NOT USE for new development; migrate to subagent backend.",
            "tmux backend keeps an attachable interactive session separate from the OpenClaw runtime process.",
            "Use prepare/start/status/capture/attach via the bridge script so dispatch plan remains the single source of truth.",
            "tmux STATUS/completion report are diagnostic only; roundtable business closeout still requires the canonical callback bridge.",
        ],
    }
