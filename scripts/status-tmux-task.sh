#!/usr/bin/env bash
# status-tmux-task.sh — Query tmux Claude Code session status
# Part of the OpenClaw orchestration layer (tmux backend).
#
# Usage:
#   status-tmux-task.sh --label <name> [--json]
#   status-tmux-task.sh --session <session-name> [--json]
set -euo pipefail

# ──── Argument Parsing ────────────────────────────────────────────────
LABEL=""
SESSION=""
JSON_OUTPUT=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --label)   LABEL="$2";   shift 2 ;;
    --session) SESSION="$2"; shift 2 ;;
    --json)    JSON_OUTPUT=true; shift ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

if [[ -n "$LABEL" ]]; then
  SESSION="${OPENCLAW_SESSION_PREFIX:-oc}-${LABEL}"
elif [[ -z "$SESSION" ]]; then
  echo "Usage: status-tmux-task.sh --label <name> [--json]" >&2
  exit 1
fi

STATE_DIR="$HOME/.openclaw/state/tmux-tasks"
STATE_FILE="${STATE_DIR}/${SESSION}-state.json"
REPORT_FILE="${STATE_DIR}/${SESSION}-completion-report.md"
NOW=$(date -u '+%Y-%m-%dT%H:%M:%SZ')

# ──── Status Detection (mirrors watchdog.sh detect_status) ───────────
detect_status() {
  local output="$1"
  # Waiting for user input
  echo "$output" | grep -qiE 'do you want to proceed|enter to select|interrupted' && { echo "waiting"; return; }
  echo "$output" | grep -q '❯ 1\.' && { echo "waiting"; return; }
  # Active: spinners or tool markers
  echo "$output" | grep -qE 'Running\.\.\.|⠋|⠙|⠹|⠸|⠼|⠴|⠦|⠧|⠇|⠏|✦|⚡|⟳' && { echo "running"; return; }
  echo "$output" | grep -qE '✓ (Read|Edit|Bash|Write|Grep|Glob)' && { echo "running"; return; }
  # Likely done: completion signals
  echo "$output" | grep -qiE 'completed|finished|done|all tasks' && { echo "likely_done"; return; }
  # Idle: bare prompt
  echo "$output" | tail -5 | grep -qE '^[[:space:]]*❯[[:space:]]*$' && { echo "idle"; return; }
  echo "$output" | tail -5 | grep -qE '^\$[[:space:]]*$' && { echo "idle"; return; }
  # Fallback
  [[ ${#output} -gt 50 ]] && echo "running" || echo "idle"
}

get_last_line() {
  echo "$1" | grep -v '^[[:space:]]*$' | grep -v '^[[:space:]]*❯[[:space:]]*$' | tail -1 | head -c 200
}

# ──── Check Session ──────────────────────────────────────────────────
if ! tmux has-session -t "$SESSION" 2>/dev/null; then
  STATUS="dead"
  LAST_OUTPUT=""
  LAST_LINE="session does not exist"
else
  LAST_OUTPUT=$(tmux capture-pane -t "$SESSION" -p -S -30 2>/dev/null || echo "")
  if [[ -z "$LAST_OUTPUT" ]]; then
    STATUS="dead"
    LAST_LINE="empty pane"
  else
    STATUS=$(detect_status "$LAST_OUTPUT")
    LAST_LINE=$(get_last_line "$LAST_OUTPUT")
  fi
fi

# Check completion report
REPORT_EXISTS=false
[[ -f "$REPORT_FILE" ]] && REPORT_EXISTS=true

# Override: if report exists and session is idle/dead, mark likely_done
if $REPORT_EXISTS && [[ "$STATUS" == "idle" || "$STATUS" == "dead" ]]; then
  STATUS="likely_done"
fi

# Detect stuck: check state file for stale timestamps
STUCK=false
if [[ -f "$STATE_FILE" ]] && command -v python3 &>/dev/null; then
  ELAPSED=$(python3 -c "
import json, sys
from datetime import datetime, timezone
try:
    d = json.load(open('$STATE_FILE'))
    t = datetime.fromisoformat(d.get('updated_at','').replace('Z','+00:00'))
    print(int((datetime.now(timezone.utc) - t).total_seconds()))
except: print(0)
" 2>/dev/null || echo "0")
  if [[ "$STATUS" == "idle" && "$ELAPSED" -gt 1800 ]]; then
    STATUS="stuck"
    STUCK=true
  fi
fi

# ──── Output ─────────────────────────────────────────────────────────
if $JSON_OUTPUT; then
  ESC_LINE=$(printf '%s' "$LAST_LINE" | sed 's/\\/\\\\/g; s/"/\\"/g' | head -c 200)
  cat <<EOJSON
{
  "session": "$SESSION",
  "status": "$STATUS",
  "report_exists": $REPORT_EXISTS,
  "stuck": $STUCK,
  "last_line": "$ESC_LINE",
  "checked_at": "$NOW"
}
EOJSON
else
  echo "Session: $SESSION"
  echo "Status:  $STATUS"
  echo "Report:  $REPORT_EXISTS"
  echo "Last:    ${LAST_LINE:0:120}"
fi
