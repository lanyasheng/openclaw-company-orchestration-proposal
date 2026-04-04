#!/usr/bin/env bash
# start-tmux-task.sh — Start a tmux session running Claude Code
# Part of the OpenClaw orchestration layer (tmux backend).
#
# Usage:
#   start-tmux-task.sh --label <name> --workdir <dir> --task <prompt> \
#                      [--timeout <seconds>] [--mode <headless|interactive>]
set -euo pipefail

MAX_SESSIONS="${OPENCLAW_MAX_TMUX_SESSIONS:-6}"
STATE_DIR="/tmp"
LOG_DIR="$HOME/.openclaw/logs"

# ──── Argument Parsing ────────────────────────────────────────────────
LABEL=""
WORKDIR=""
TASK=""
TIMEOUT=3600
MODE="headless"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --label)   LABEL="$2";   shift 2 ;;
    --workdir) WORKDIR="$2"; shift 2 ;;
    --task)    TASK="$2";    shift 2 ;;
    --timeout) TIMEOUT="$2"; shift 2 ;;
    --mode)    MODE="$2";    shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$LABEL" || -z "$WORKDIR" || -z "$TASK" ]]; then
  echo "Usage: start-tmux-task.sh --label <name> --workdir <dir> --task <prompt> [--timeout <s>] [--mode headless|interactive]" >&2
  exit 1
fi

SESSION="cc-${LABEL}"
STATE_FILE="${STATE_DIR}/${SESSION}-state.json"

# ──── Precondition Checks ────────────────────────────────────────────
command -v tmux &>/dev/null || { echo "Error: tmux not found" >&2; exit 1; }
command -v claude &>/dev/null || { echo "Error: claude CLI not found" >&2; exit 1; }
[[ -d "$WORKDIR" ]] || { echo "Error: workdir not found: $WORKDIR" >&2; exit 1; }

if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "Session '$SESSION' already exists. Attach: tmux attach -t $SESSION" >&2
  exit 0
fi

ACTIVE=$(tmux ls 2>/dev/null | grep -c "^cc-" || true)
if [[ "$ACTIVE" -ge "$MAX_SESSIONS" ]]; then
  echo "Error: $ACTIVE active cc-* sessions (max $MAX_SESSIONS)" >&2
  exit 1
fi

mkdir -p "$LOG_DIR"

# ──── Build Claude Command ───────────────────────────────────────────
PROMPT_FILE=$(mktemp "/tmp/${SESSION}-prompt-XXXXXX.txt")
printf '%s' "$TASK" > "$PROMPT_FILE"

if [[ "$MODE" == "headless" ]]; then
  CC_CMD="cd '${WORKDIR}' && claude -p --output-format stream-json --max-turns 200 --max-budget-usd 10 --permission-mode bypassPermissions < '${PROMPT_FILE}' > '${LOG_DIR}/${SESSION}.jsonl' 2>&1; rm -f '${PROMPT_FILE}'"
else
  CC_CMD="cd '${WORKDIR}' && export CLAUDE_CODE_DISABLE_MOUSE=1 && export CLAUDE_CODE_DISABLE_ALTERNATE_SCREEN=1 && claude --permission-mode bypassPermissions"
fi

# ──── Create tmux Session ────────────────────────────────────────────
if ! tmux new-session -d -s "$SESSION" "$CC_CMD"; then
  echo "Error: Failed to create tmux session '$SESSION'" >&2
  rm -f "$PROMPT_FILE"
  exit 1
fi

# Interactive mode: wait for init, then paste prompt
if [[ "$MODE" == "interactive" ]]; then
  for _ in $(seq 1 15); do
    sleep 1
    tmux has-session -t "$SESSION" 2>/dev/null || { echo "Error: session died during startup" >&2; rm -f "$PROMPT_FILE"; exit 1; }
    PANE=$(tmux capture-pane -t "$SESSION" -p 2>/dev/null || echo "")
    [[ ${#PANE} -gt 10 ]] && break
  done
  BUFNAME="prompt-${SESSION}"
  tmux load-buffer -b "$BUFNAME" "$PROMPT_FILE"
  tmux paste-buffer -b "$BUFNAME" -t "$SESSION"
  tmux send-keys -t "$SESSION" Enter
  rm -f "$PROMPT_FILE"
fi

# ──── Write Initial State JSON ───────────────────────────────────────
NOW=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
cat > "$STATE_FILE" <<EOJSON
{
  "session": "$SESSION",
  "label": "$LABEL",
  "mode": "$MODE",
  "workdir": "$WORKDIR",
  "status": "started",
  "timeout": $TIMEOUT,
  "started_at": "$NOW",
  "updated_at": "$NOW",
  "pid": $$
}
EOJSON

echo "Started: $SESSION (mode=$MODE, timeout=${TIMEOUT}s)"
echo "  Workdir: $WORKDIR"
echo "  State:   $STATE_FILE"
echo "  Attach:  tmux attach -t $SESSION"
