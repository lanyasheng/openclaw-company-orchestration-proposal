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
#   - Or set CLAUDE_CLI_PATH environment variable
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
# Priority: CLAUDE_CLI_PATH env > PATH > common locations
if [ -n "${CLAUDE_CLI_PATH:-}" ]; then
    CLAUDE_BIN="$CLAUDE_CLI_PATH"
elif command -v claude &>/dev/null; then
    CLAUDE_BIN="$(command -v claude)"
elif [ -x "$HOME/bin/claude" ]; then
    CLAUDE_BIN="$HOME/bin/claude"
elif [ -x "$HOME/.npm-global/bin/claude" ]; then
    CLAUDE_BIN="$HOME/.npm-global/bin/claude"
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
    local result_file="$2"
    local error="${3:-}"
    local error_file
    error_file="$(mktemp)"
    printf '%s' "$error" > "$error_file"
    python3 - "$TASK_ID" "$status" "$result_file" "$error_file" "$TASK_DESC" "$TASK_LABEL" "$STATE_FILE" "$TIMEOUT_S" <<'PYEOF'
import json, sys, os
task_id, status, result_path, error_path, desc, label, out_path, timeout_s = sys.argv[1:9]
result = None
if os.path.isfile(result_path) and os.path.getsize(result_path) > 0:
    with open(result_path, "r") as f:
        result = f.read()
error = None
if os.path.isfile(error_path) and os.path.getsize(error_path) > 0:
    with open(error_path, "r") as f:
        error = f.read()
data = {
    "task_id": task_id,
    "status": status,
    "result": result,
    "error": error,
    "task": desc,
    "config": {
        "label": label,
        "runtime": "subagent",
        "timeout_seconds": int(timeout_s),
    },
}
with open(out_path, "w") as f:
    json.dump(data, f, indent=2)
PYEOF
    rm -f "$error_file"
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

# Append output to log
if [ -f "$TEMP_OUTPUT" ]; then
    cat "$TEMP_OUTPUT" >> "$OUTPUT_LOG"
fi

# ──── Result Handling ─────────────────────────────────────────────────
if [ "$AGENT_EXIT" -eq 0 ]; then
    log "[runner] Task $TASK_ID completed successfully"
    write_result "completed" "$TEMP_OUTPUT" ""
    exit 0
elif [ "$AGENT_EXIT" -eq 124 ]; then
    log "[runner] Task $TASK_ID timed out after ${TIMEOUT_S}s"
    write_result "timeout" "/dev/null" "Task timed out after ${TIMEOUT_S} seconds"
    exit 1
else
    log "[runner] Task $TASK_ID failed (exit code $AGENT_EXIT)"
    write_result "failed" "/dev/null" "Claude CLI exited with code $AGENT_EXIT"
    exit 1
fi
