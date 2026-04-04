#!/usr/bin/env bash
# monitor-tmux-task.sh — Continuously monitor a tmux Claude Code session
# Part of the OpenClaw orchestration layer (tmux backend).
#
# Usage:
#   monitor-tmux-task.sh --label <name> [--interval 30] [--timeout 3600] \
#                        [--on-done <cmd>] [--on-stuck <cmd>]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
STATUS_SCRIPT="${SCRIPT_DIR}/status-tmux-task.sh"

# ──── Argument Parsing ────────────────────────────────────────────────
LABEL=""
INTERVAL=30
TIMEOUT=3600
ON_DONE=""
ON_STUCK=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --label)    LABEL="$2";    shift 2 ;;
    --interval) INTERVAL="$2"; shift 2 ;;
    --timeout)  TIMEOUT="$2";  shift 2 ;;
    --on-done)  ON_DONE="$2";  shift 2 ;;
    --on-stuck) ON_STUCK="$2"; shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$LABEL" ]]; then
  echo "Usage: monitor-tmux-task.sh --label <name> [--interval <s>] [--timeout <s>] [--on-done <cmd>] [--on-stuck <cmd>]" >&2
  exit 1
fi

SESSION="cc-${LABEL}"
LOG_FILE="/tmp/${SESSION}-monitor.log"

log() {
  local ts; ts=$(date '+%Y-%m-%d %H:%M:%S')
  echo "${ts} | $*" | tee -a "$LOG_FILE"
}

# ──── Monitor Loop ───────────────────────────────────────────────────
START_EPOCH=$(date +%s)
PREV_STATUS=""
CHECKS=0

log "Monitor started: session=$SESSION interval=${INTERVAL}s timeout=${TIMEOUT}s"

while true; do
  NOW_EPOCH=$(date +%s)
  ELAPSED=$(( NOW_EPOCH - START_EPOCH ))

  # Timeout check
  if [[ "$ELAPSED" -ge "$TIMEOUT" ]]; then
    log "TIMEOUT: ${ELAPSED}s elapsed (limit=${TIMEOUT}s)"
    if [[ -n "$ON_STUCK" ]]; then
      log "Executing on-stuck: $ON_STUCK"
      eval "$ON_STUCK" || log "on-stuck command failed (exit $?)"
    fi
    exit 2
  fi

  # Query status
  if [[ ! -x "$STATUS_SCRIPT" ]]; then
    log "Error: status script not found: $STATUS_SCRIPT"
    exit 1
  fi

  STATUS_JSON=$("$STATUS_SCRIPT" --label "$LABEL" --json 2>/dev/null || echo '{"status":"error"}')
  CURRENT_STATUS=$(echo "$STATUS_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin).get('status','unknown'))" 2>/dev/null || echo "unknown")
  REPORT_EXISTS=$(echo "$STATUS_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin).get('report_exists',False))" 2>/dev/null || echo "False")

  CHECKS=$(( CHECKS + 1 ))

  # Log status change
  if [[ "$CURRENT_STATUS" != "$PREV_STATUS" ]]; then
    log "Status change: ${PREV_STATUS:-<init>} -> $CURRENT_STATUS (check #$CHECKS, elapsed ${ELAPSED}s)"
    PREV_STATUS="$CURRENT_STATUS"
  fi

  # Terminal states
  case "$CURRENT_STATUS" in
    likely_done|done|completed)
      log "DONE: task completed (status=$CURRENT_STATUS, report=$REPORT_EXISTS)"
      if [[ -n "$ON_DONE" ]]; then
        log "Executing on-done: $ON_DONE"
        eval "$ON_DONE" || log "on-done command failed (exit $?)"
      fi
      exit 0
      ;;
    stuck)
      log "STUCK: task appears stuck"
      if [[ -n "$ON_STUCK" ]]; then
        log "Executing on-stuck: $ON_STUCK"
        eval "$ON_STUCK" || log "on-stuck command failed (exit $?)"
      fi
      exit 2
      ;;
    dead)
      log "DEAD: session no longer exists"
      if [[ "$REPORT_EXISTS" == "True" ]]; then
        log "Report exists — treating as done"
        [[ -n "$ON_DONE" ]] && { eval "$ON_DONE" || log "on-done command failed (exit $?)"; }
        exit 0
      fi
      [[ -n "$ON_STUCK" ]] && { eval "$ON_STUCK" || log "on-stuck command failed (exit $?)"; }
      exit 2
      ;;
  esac

  sleep "$INTERVAL"
done
