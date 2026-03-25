#!/usr/bin/env bash
# OpenClaw Subagent Runner — Claude Code Backend
#
# This script is invoked by SubagentExecutor for each task.
# It writes a result JSON to $OPENCLAW_SUBAGENT_STATE_DIR/$OPENCLAW_TASK_ID.json
# before exiting. Exit code 0 = success, non-zero = failure.
#
# Environment variables (injected by SubagentExecutor):
#   OPENCLAW_TASK_ID              — unique task identifier
#   OPENCLAW_SUBAGENT_STATE_DIR   — directory for state files
#   OPENCLAW_SPAWN_DEPTH          — current recursion depth
#
# Arguments:
#   $1  — task description (the prompt / instruction)
#   $2  — task label
#
# Configuration (environment overrides):
#   CLAUDE_CLI_PATH      — Path to Claude CLI (default: auto-detect)
#   CLAUDE_TIMEOUT_S     — Timeout in seconds (default: 900)
#   CLAUDE_WORKDIR       — Working directory (default: current dir)
#
# Requirements:
#   - Claude Code CLI installed (`npm install -g @anthropic-ai/claude-code`)
#   - Or available at /Users/study/bin/claude
#
# Quickstart:
#   1. Install Claude Code: npm install -g @anthropic-ai/claude-code
#   2. Verify: claude --version
#   3. Run: ./scripts/run_subagent_claude_v1.sh "Your task" "label"

set -euo pipefail

# ──── Configuration ───────────────────────────────────────────────────
TASK_DESC="${1:-}"
TASK_LABEL="${2:-default}"
TASK_ID="${OPENCLAW_TASK_ID:?OPENCLAW_TASK_ID not set}"
STATE_DIR="${OPENCLAW_SUBAGENT_STATE_DIR:?OPENCLAW_SUBAGENT_STATE_DIR not set}"
WORKDIR="${CLAUDE_WORKDIR:-$(pwd)}"
TIMEOUT_S="${CLAUDE_TIMEOUT_S:-900}"

# Auto-detect Claude CLI path
if [ -n "${CLAUDE_CLI_PATH:-}" ]; then
    CLAUDE_BIN="$CLAUDE_CLI_PATH"
elif command -v claude &>/dev/null; then
    CLAUDE_BIN="$(command -v claude)"
elif [ -x /Users/study/bin/claude ]; then
    CLAUDE_BIN="/Users/study/bin/claude"
else
    echo "[runner] ERROR: Claude CLI not found. Install with: npm install -g @anthropic-ai/claude-code" >&2
    echo "[runner] Or set CLAUDE_CLI_PATH environment variable." >&2
    exit 127
fi

# ──── Validation ──────────────────────────────────────────────────────
if [ -z "$TASK_DESC" ]; then
    echo "[runner] ERROR: Task description is required" >&2
    exit 1
fi

if [ ! -d "$WORKDIR" ]; then
    echo "[runner] ERROR: Working directory not found: $WORKDIR" >&2
    exit 1
fi

mkdir -p "$STATE_DIR"
STATE_FILE="$STATE_DIR/$TASK_ID.json"
OUTPUT_LOG="$STATE_DIR/$TASK_ID.output.log"

# ──── Helper Functions ────────────────────────────────────────────────
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
    "config": {
        "label": label,
        "runtime": "subagent",
        "timeout_seconds": 900,
    },
}
with open(out_path, "w") as f:
    json.dump(data, f, indent=2)
PYEOF
}

log() {
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "$OUTPUT_LOG"
}

# ──── Main Execution ──────────────────────────────────────────────────
log "[runner] Starting task $TASK_ID: $TASK_LABEL"
log "[runner] Claude CLI: $CLAUDE_BIN"
log "[runner] Working dir: $WORKDIR"
log "[runner] Timeout: ${TIMEOUT_S}s"

# Create a temporary file for Claude's output
TEMP_OUTPUT="$(mktemp)"
trap 'rm -f "$TEMP_OUTPUT"' EXIT

# Run Claude Code with timeout
# --print: non-interactive mode, output to stdout
# --permission-mode bypassPermissions: skip interactive permission prompts
cd "$WORKDIR"
set +e
timeout "$TIMEOUT_S" "$CLAUDE_BIN" --print --permission-mode bypassPermissions "$TASK_DESC" >"$TEMP_OUTPUT" 2>&1
AGENT_EXIT=$?
set -e

# Read output
if [ -f "$TEMP_OUTPUT" ]; then
    AGENT_OUTPUT="$(cat "$TEMP_OUTPUT")"
else
    AGENT_OUTPUT=""
fi

# Append to log
echo "$AGENT_OUTPUT" >> "$OUTPUT_LOG"

# ──── Result Handling ─────────────────────────────────────────────────
if [ "$AGENT_EXIT" -eq 0 ]; then
    log "[runner] Task $TASK_ID completed successfully"
    write_result "completed" "$AGENT_OUTPUT" ""
    exit 0
elif [ "$AGENT_EXIT" -eq 124 ]; then
    log "[runner] Task $TASK_ID timed out after ${TIMEOUT_S}s"
    write_result "timeout" "" "Task timed out after ${TIMEOUT_S} seconds"
    exit 1
else
    log "[runner] Task $TASK_ID failed (exit code $AGENT_EXIT)"
    write_result "failed" "" "Claude CLI exited with code $AGENT_EXIT"
    exit 1
fi
