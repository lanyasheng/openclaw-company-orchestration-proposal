#!/usr/bin/env bash
# OpenClaw Subagent Runner Template
#
# This script is invoked by SubagentExecutor for each task.
# It MUST write a result JSON to $OPENCLAW_SUBAGENT_STATE_DIR/$OPENCLAW_TASK_ID.json
# before exiting.  Exit code 0 = success, non-zero = failure (fallback).
#
# Environment variables injected by SubagentExecutor:
#   OPENCLAW_TASK_ID              — unique task identifier
#   OPENCLAW_SUBAGENT_STATE_DIR   — directory for state files
#   OPENCLAW_SPAWN_DEPTH          — current recursion depth
#
# Arguments:
#   $1  — task description (the prompt / instruction)
#   $2  — task label
#
# Customize the AGENT_CMD below for your agent backend (Claude, GPT, local LLM, etc.)

set -euo pipefail

TASK_DESC="${1:-}"
TASK_LABEL="${2:-default}"
TASK_ID="${OPENCLAW_TASK_ID:?OPENCLAW_TASK_ID not set}"
STATE_DIR="${OPENCLAW_SUBAGENT_STATE_DIR:?OPENCLAW_SUBAGENT_STATE_DIR not set}"

mkdir -p "$STATE_DIR"
STATE_FILE="$STATE_DIR/$TASK_ID.json"

write_result() {
    local status="$1"
    local result="$2"
    local error="${3:-}"
    python3 - "$TASK_ID" "$status" "$result" "$error" "$TASK_DESC" "$TASK_LABEL" "$STATE_FILE" <<'PYEOF'
import json, sys
task_id, status, result, error, desc, label, out_path = sys.argv[1:8]
data = {
    "task_id": task_id,
    "status": status,
    "result": result if result else None,
    "error": error if error else None,
    "task": desc,
    "config": {"label": label, "runtime": "subagent", "timeout_seconds": 900},
}
with open(out_path, "w") as f:
    json.dump(data, f, indent=2)
PYEOF
}

# ──── YOUR AGENT COMMAND HERE ────────────────────────────────────────
# Replace the block below with your actual agent invocation.
# Example for Claude Code:
#   claude --print "$TASK_DESC" > /tmp/agent_output_$TASK_ID.txt 2>&1
#   AGENT_EXIT=$?

echo "[runner] Starting task $TASK_ID: $TASK_LABEL"
echo "[runner] Description: $TASK_DESC"

# Default: echo-based stub (replace with real agent)
AGENT_OUTPUT="Task completed by runner stub: $TASK_LABEL"
AGENT_EXIT=0

# ──── WRITE RESULT ───────────────────────────────────────────────────
if [ "$AGENT_EXIT" -eq 0 ]; then
    write_result "completed" "$AGENT_OUTPUT" ""
    echo "[runner] Task $TASK_ID completed successfully"
else
    write_result "failed" "" "Agent exited with code $AGENT_EXIT"
    echo "[runner] Task $TASK_ID failed (exit code $AGENT_EXIT)"
    exit 1
fi
