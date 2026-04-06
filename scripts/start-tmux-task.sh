#!/usr/bin/env bash
# start-tmux-task.sh — Start a tmux session running Claude Code
# Part of the OpenClaw orchestration layer (tmux backend).
# Generic: no project-specific logic. Hooks integration via NC_SESSION env.
#
# Usage:
#   start-tmux-task.sh --label <name> --workdir <dir> --task <prompt> \
#                      [--timeout <seconds>] [--mode <headless|interactive>]
set -euo pipefail

MAX_SESSIONS="${OPENCLAW_MAX_TMUX_SESSIONS:-6}"
SESSION_PREFIX="${OPENCLAW_SESSION_PREFIX:-oc}"
STATE_DIR="$HOME/.openclaw/state/tmux-tasks"
PROGRESS_DIR="$HOME/.openclaw/shared-context/progress"
LOG_DIR="$HOME/.openclaw/logs"

# ──── Argument Parsing ────────────────────────────────────────────────
LABEL=""
WORKDIR=""
TASK=""
TIMEOUT=3600
MODE="interactive"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --label)   LABEL="$2";   shift 2 ;;
    --workdir) WORKDIR="$2"; shift 2 ;;
    --task)    TASK="$2";    shift 2 ;;
    --timeout) TIMEOUT="$2"; shift 2 ;;
    --mode)    shift 2 ;;  # 接受但忽略，统一 interactive
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$LABEL" || -z "$WORKDIR" || -z "$TASK" ]]; then
  echo "Usage: start-tmux-task.sh --label <name> --workdir <dir> --task <prompt> [--timeout <s>]" >&2
  exit 1
fi

SESSION="${SESSION_PREFIX}-${LABEL}"
STATE_FILE="${STATE_DIR}/${SESSION}-state.json"

# ──── Precondition Checks ────────────────────────────────────────────
command -v tmux &>/dev/null || { echo "Error: tmux not found" >&2; exit 1; }
command -v claude &>/dev/null || { echo "Error: claude CLI not found" >&2; exit 1; }
[[ -d "$WORKDIR" ]] || { echo "Error: workdir not found: $WORKDIR" >&2; exit 1; }

if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "Session '$SESSION' already exists. Attach: tmux attach -t $SESSION" >&2
  exit 0
fi

ACTIVE=$(tmux ls 2>/dev/null | grep -c "^${SESSION_PREFIX}-" || true)
if [[ "$ACTIVE" -ge "$MAX_SESSIONS" ]]; then
  echo "Error: $ACTIVE active ${SESSION_PREFIX}-* sessions (max $MAX_SESSIONS)" >&2
  exit 1
fi

mkdir -p "$LOG_DIR" "$STATE_DIR" "$PROGRESS_DIR"

# ──── Build Claude Command (unified interactive) ─────────────────────
PROMPT_FILE=$(mktemp "$STATE_DIR/${SESSION}-prompt-XXXXXX")
printf '%s' "$TASK" > "$PROMPT_FILE"

# Export NC_SESSION + NC_PROJECT_DIR so hooks (Stop/SessionEnd) can identify this session
CC_CMD="cd '${WORKDIR}' && export NC_SESSION='${SESSION}' && export NC_PROJECT_DIR='${WORKDIR}' && export CLAUDE_ENABLE_STREAM_WATCHDOG=1 && export CLAUDE_CODE_DISABLE_MOUSE=1 && export CLAUDE_CODE_DISABLE_ALTERNATE_SCREEN=1 && claude --permission-mode bypassPermissions --name '${SESSION}'"

# ──── Create tmux Session ────────────────────────────────────────────
if ! tmux new-session -d -s "$SESSION" "$CC_CMD"; then
  echo "Error: Failed to create tmux session '$SESSION'" >&2
  rm -f "$PROMPT_FILE"
  exit 1
fi

# Wait for CC init, then paste prompt
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

# ──── Write State Files ──────────────────────────────────────────────
NOW=$(date -u '+%Y-%m-%dT%H:%M:%SZ')

# State file (for orchestrator dispatch bridge)
cat > "$STATE_FILE" <<EOJSON
{
  "session": "$SESSION",
  "label": "$LABEL",
  "mode": "interactive",
  "workdir": "$WORKDIR",
  "status": "started",
  "timeout": $TIMEOUT,
  "started_at": "$NOW",
  "updated_at": "$NOW",
  "pid": $$
}
EOJSON

# Progress file (for TmuxTaskExecutor.poll + on-stop.sh)
jq -n --arg s "$SESSION" --arg p "starting" --arg pd "$WORKDIR" --arg m "interactive" --arg ts "$NOW" \
  '{session:$s,phase:$p,project_dir:$pd,mode:$m,tools_used:0,updated_at:$ts}' \
  > "$PROGRESS_DIR/${SESSION}.json" 2>/dev/null || true

echo "Started: $SESSION (interactive, timeout=${TIMEOUT}s)"
echo "  Workdir:  $WORKDIR"
echo "  State:    $STATE_FILE"
echo "  Progress: $PROGRESS_DIR/${SESSION}.json"
echo "  Attach:   tmux attach -t $SESSION"
