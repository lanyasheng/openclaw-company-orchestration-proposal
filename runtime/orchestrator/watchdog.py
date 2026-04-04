"""Watchdog for automatic workflow recovery.

Monitors workflow state files and auto-resumes gate_blocked or
stalled workflows. Run as a daemon or cron job.

Usage:
    # One-shot check
    python3 watchdog.py check /path/to/state.json

    # Continuous monitoring (every 30s)
    python3 watchdog.py watch /path/to/state.json --interval 30

    # Monitor all state files in a directory
    python3 watchdog.py watch-dir /path/to/states/ --interval 60
"""

from __future__ import annotations

import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from workflow_state import WorkflowState, load_workflow_state, save_workflow_state

logger = logging.getLogger(__name__)

DEFAULT_STALL_TIMEOUT_SECONDS = 3600
DEFAULT_POLL_INTERVAL = 30


def check_workflow(state_path: str | Path) -> dict:
    """Check a single workflow's health. Returns diagnosis."""
    path = Path(state_path)
    if not path.is_file():
        return {"path": str(path), "status": "missing", "action": "none"}

    try:
        ws = load_workflow_state(path)
    except Exception as e:
        return {"path": str(path), "status": "corrupt", "error": str(e), "action": "none"}

    if ws.status == "completed":
        return {"path": str(path), "status": "completed", "action": "none"}

    if ws.status == "failed":
        return {"path": str(path), "status": "failed", "action": "none"}

    if ws.status == "gate_blocked":
        return {
            "path": str(path),
            "status": "gate_blocked",
            "workflow_id": ws.workflow_id,
            "action": "needs_human_approval",
            "updated_at": ws.updated_at,
        }

    if ws.status in ("pending", "running"):
        stall_seconds = _seconds_since(ws.updated_at)
        stalled = stall_seconds > DEFAULT_STALL_TIMEOUT_SECONDS if stall_seconds else False
        return {
            "path": str(path),
            "status": ws.status,
            "workflow_id": ws.workflow_id,
            "stalled": stalled,
            "stall_seconds": stall_seconds,
            "action": "auto_resume" if stalled else "none",
            "updated_at": ws.updated_at,
        }

    return {"path": str(path), "status": ws.status, "action": "unknown"}


def auto_resume(state_path: str | Path) -> Optional[str]:
    """Auto-resume a stalled workflow. Returns new status or None."""
    path = Path(state_path)
    try:
        ws = load_workflow_state(path)
    except Exception:
        return None

    if ws.status not in ("running", "pending"):
        return None

    stall_seconds = _seconds_since(ws.updated_at)
    if stall_seconds and stall_seconds > DEFAULT_STALL_TIMEOUT_SECONDS:
        resume_count = getattr(ws, "resume_count", 0) or 0
        resume_count += 1

        if resume_count > 3:
            logger.error(
                "workflow %s stalled %d times, marking as stalled_unrecoverable",
                ws.workflow_id,
                resume_count,
            )
            ws.status = "stalled_unrecoverable"
            ws.resume_count = resume_count
            ws.updated_at = datetime.now(timezone.utc).isoformat()
            save_workflow_state(ws, path)
            return "stalled_unrecoverable"

        logger.warning(
            "workflow %s stalled for %ds, resuming (attempt %d/3)",
            ws.workflow_id,
            stall_seconds,
            resume_count,
        )
        ws.status = "running"
        ws.resume_count = resume_count
        ws.updated_at = datetime.now(timezone.utc).isoformat()
        save_workflow_state(ws, path)
        return "resumed"

    return None


def find_state_files(directory: str | Path) -> List[Path]:
    """Find all workflow state JSON files in a directory."""
    return sorted(Path(directory).glob("workflow_state_*.json"))


def _seconds_since(iso_timestamp: str) -> Optional[float]:
    try:
        dt = datetime.fromisoformat(iso_timestamp)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds()
    except (ValueError, TypeError):
        return None


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "check":
        result = check_workflow(sys.argv[2])
        for k, v in result.items():
            print(f"  {k}: {v}")

    elif cmd == "watch":
        interval = DEFAULT_POLL_INTERVAL
        if "--interval" in sys.argv:
            idx = sys.argv.index("--interval")
            if idx + 1 < len(sys.argv):
                interval = int(sys.argv[idx + 1])
        path = sys.argv[2]
        print(f"Watching {path} every {interval}s (Ctrl+C to stop)")
        while True:
            try:
                result = check_workflow(path)
                if result.get("action") == "auto_resume":
                    auto_resume(path)
                    print(f"  Auto-resumed: {result.get('workflow_id')}")
                elif result.get("action") != "none":
                    print(f"  {result.get('status')}: {result.get('action')}")
            except Exception as e:
                logger.error("Error checking workflow %s: %s", path, e)
            time.sleep(interval)

    elif cmd == "watch-dir":
        interval = DEFAULT_POLL_INTERVAL
        if "--interval" in sys.argv:
            idx = sys.argv.index("--interval")
            if idx + 1 < len(sys.argv):
                interval = int(sys.argv[idx + 1])
        directory = sys.argv[2]
        print(f"Watching {directory} every {interval}s (Ctrl+C to stop)")
        while True:
            for path in find_state_files(directory):
                try:
                    result = check_workflow(path)
                    if result.get("action") == "auto_resume":
                        auto_resume(path)
                        logger.info("Auto-resumed: %s", result.get("workflow_id"))
                except Exception as e:
                    logger.error("Error checking workflow %s: %s", path, e)
            time.sleep(interval)

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
