#!/usr/bin/env bash
# start-tmux-task.sh — Start a tmux session running Claude Code
# Part of the OpenClaw orchestration layer (tmux backend).
# Generic: no project-specific logic. Hooks integration via NC_SESSION env.
#
# Usage:
#   start-tmux-task.sh --label <name> --workdir <dir> --task <prompt> \
#     [--timeout <s>] [--type <type>] [--model <model>] \
#     [--no-ralph] [--max-iterations <n>] [--no-worktree]
set -euo pipefail

MAX_SESSIONS="${OPENCLAW_MAX_TMUX_SESSIONS:-6}"
SESSION_PREFIX="${OPENCLAW_SESSION_PREFIX:-oc}"
STATE_DIR="$HOME/.openclaw/state/tmux-tasks"
PROGRESS_DIR="$HOME/.openclaw/shared-context/progress"
RESULTS_DIR="$HOME/.openclaw/shared-context/results"
LOG_DIR="$HOME/.openclaw/logs"
ORCH_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TMUX_SYNC_SCRIPT="${ORCH_DIR}/scripts/sync-tmux-observability.py"

# 会修改代码的任务类型 → 需要 worktree 隔离
CODING_TYPES="bugfix feat crash comp fix"

# ──── Argument Parsing ────────────────────────────────────────────────
LABEL=""
WORKDIR=""
TASK=""
TIMEOUT=3600
TYPE=""
MODEL_ARG=""
RALPH_ENABLED=true
RALPH_MAX_ITERATIONS=50
WORKTREE_ENABLED=true
AUTO_EXIT=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --label)          LABEL="$2";   shift 2 ;;
    --workdir)        WORKDIR="$2"; shift 2 ;;
    --task)           TASK="$2";    shift 2 ;;
    --timeout)        TIMEOUT="$2"; shift 2 ;;
    --type)           TYPE="$2";    shift 2 ;;
    --model)          MODEL_ARG="$2"; shift 2 ;;
    --mode)           shift 2 ;;  # 接受但忽略，统一 interactive
    --ralph)          RALPH_ENABLED=true; shift ;;
    --no-ralph)       RALPH_ENABLED=false; shift ;;
    --max-iterations) RALPH_MAX_ITERATIONS="$2"; shift 2 ;;
    --no-worktree)    WORKTREE_ENABLED=false; shift ;;
    --auto-exit)      AUTO_EXIT=true; shift ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$LABEL" || -z "$WORKDIR" || -z "$TASK" ]]; then
  echo "Usage: start-tmux-task.sh --label <name> --workdir <dir> --task <prompt>" >&2
  echo "  --type <type>        Task type (review/bugfix/feat/...), used for worktree/observability" >&2
  echo "  --model <model>      Claude model override" >&2
  echo "  --no-ralph           Disable Ralph persistent execution" >&2
  echo "  --no-worktree        Disable git worktree isolation for coding tasks" >&2
  exit 1
fi

SESSION="${SESSION_PREFIX}-${LABEL}"
STATE_FILE="${STATE_DIR}/${SESSION}-state.json"

# ──── Precondition Checks ────────────────────────────────────────────
command -v tmux &>/dev/null || { echo "Error: tmux not found" >&2; exit 1; }
command -v claude &>/dev/null || { echo "Error: claude CLI not found" >&2; exit 1; }
[[ -d "$WORKDIR" ]] || { echo "Error: workdir not found: $WORKDIR" >&2; exit 1; }

# Session 存在检查
if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "Session '$SESSION' already exists. Attach: tmux attach -t $SESSION"
  exit 0
fi

# ──── Results 去重 ────────────────────────────────────────────────────
RESULT_FILE="${RESULTS_DIR}/${SESSION}.json"
RESULT_TXT="${RESULTS_DIR}/${SESSION}.txt"
if [[ -f "$RESULT_FILE" || -f "$RESULT_TXT" ]]; then
  _CHECK="${RESULT_FILE}"; [[ ! -f "$_CHECK" ]] && _CHECK="$RESULT_TXT"
  _STATUS=$(jq -r '.subtype // .status // "unknown"' "$_CHECK" 2>/dev/null || echo "exists")
  if [[ "$_STATUS" == "success" || "$_STATUS" == "completed" || "$_STATUS" == "exists" ]]; then
    echo "Task ${SESSION} already completed (result file exists). Skipping."
    exit 0
  fi
fi

mkdir -p "$LOG_DIR" "$STATE_DIR" "$PROGRESS_DIR" "$RESULTS_DIR"

# 并行数量检查（mkdir 原子锁防竞态：多个 dispatch 同时跑时串行化）
LOCK_DIR="$HOME/.openclaw/state/.dispatch-lock"
_lock_acquired=false
for _ in $(seq 1 60); do
  if mkdir "$LOCK_DIR" 2>/dev/null; then
    _lock_acquired=true
    break
  fi
  # 检查锁是否过期（>60 秒则清理死锁）
  if [[ -d "$LOCK_DIR" ]]; then
    _lock_age=$(( $(date +%s) - $(stat -f%m "$LOCK_DIR" 2>/dev/null || stat -c%Y "$LOCK_DIR" 2>/dev/null || echo 0) ))
    if [[ "$_lock_age" -gt 60 ]]; then
      rmdir "$LOCK_DIR" 2>/dev/null
      continue
    fi
  fi
  sleep 0.5
done
if ! $_lock_acquired; then
  echo "Error: could not acquire dispatch lock after 30s" >&2
  exit 1
fi
_unlock() { rmdir "$LOCK_DIR" 2>/dev/null; }
trap _unlock EXIT

ACTIVE=$(tmux ls 2>/dev/null | grep -c "^${SESSION_PREFIX}-" || true)
if [[ "$ACTIVE" -ge "$MAX_SESSIONS" ]]; then
  echo "Error: $ACTIVE active ${SESSION_PREFIX}-* sessions (max $MAX_SESSIONS)" >&2
  exit 1
fi

# ──── Ralph 持续执行初始化（execution-harness Pattern 1）────────────
if $RALPH_ENABLED; then
  HARNESS_DIR="$HOME/.openclaw/skills/execution-harness/skills/agent-hooks/scripts"
  if [[ -f "$HARNESS_DIR/ralph-init.sh" ]]; then
    bash "$HARNESS_DIR/ralph-init.sh" "$SESSION" "$RALPH_MAX_ITERATIONS" || \
      { echo "Warning: ralph-init.sh failed, continuing without Ralph" >&2; RALPH_ENABLED=false; }
  else
    echo "Warning: ralph-init.sh not found, skipping Ralph" >&2
  fi
fi

# ──── Worktree 隔离（编码类任务）─────────────────────────────────────
WORK_DIR="$WORKDIR"
WORKTREE_DIR=""
NEEDS_WORKTREE=false

if $WORKTREE_ENABLED && [[ -n "$TYPE" ]]; then
  for ct in $CODING_TYPES; do
    if [[ "$TYPE" == "$ct" ]]; then
      NEEDS_WORKTREE=true
      break
    fi
  done
fi

if $NEEDS_WORKTREE && [[ -d "$WORKDIR/.git" || -f "$WORKDIR/.git" ]]; then
  WORKTREE_DIR="${WORKDIR}/.claude/worktrees/${SESSION}"
  BRANCH_NAME="dispatch/${LABEL}"

  if [[ -d "$WORKTREE_DIR" ]]; then
    echo "Worktree already exists: $WORKTREE_DIR"
  else
    echo "Creating worktree: $BRANCH_NAME → $WORKTREE_DIR"
    git -C "$WORKDIR" worktree add -b "$BRANCH_NAME" "$WORKTREE_DIR" HEAD 2>/dev/null || \
    git -C "$WORKDIR" worktree add "$WORKTREE_DIR" "$BRANCH_NAME" 2>/dev/null || \
    { echo "Warning: Failed to create worktree, using main workdir" >&2; NEEDS_WORKTREE=false; }
  fi

  if $NEEDS_WORKTREE; then
    WORK_DIR="$WORKTREE_DIR"
    # 保存 branch name 供 on-session-end.sh 清理时使用（避免 sed 重建不一致）
    echo "$BRANCH_NAME" > "$WORKTREE_DIR/.openclaw-branch" 2>/dev/null || true
    echo "  Worktree: $WORKTREE_DIR"
  fi
fi

# ──── Auto-exit marker (on-stop.sh will send /exit when CC finishes) ──
if $AUTO_EXIT; then
  mkdir -p "$HOME/.openclaw/shared-context/sessions/${SESSION}"
  echo "true" > "$HOME/.openclaw/shared-context/sessions/${SESSION}/auto-exit"
fi

# ──── Build Claude Command (unified interactive) ─────────────────────
PROMPT_FILE=$(mktemp "$STATE_DIR/${SESSION}-prompt-XXXXXX")
printf '%s' "$TASK" > "$PROMPT_FILE"

EXTRA=""
if [[ -n "$MODEL_ARG" ]]; then EXTRA="$EXTRA --model $MODEL_ARG"; fi

# Export NC_SESSION + NC_PROJECT_DIR so hooks (Stop/SessionEnd) can identify this session
CC_CMD="cd '${WORK_DIR}' && export NC_SESSION='${SESSION}' && export NC_PROJECT_DIR='${WORKDIR}' && export CLAUDE_ENABLE_STREAM_WATCHDOG=1 && export CLAUDE_CODE_DISABLE_MOUSE=1 && export CLAUDE_CODE_DISABLE_ALTERNATE_SCREEN=1 && claude --permission-mode bypassPermissions --name '${SESSION}'${EXTRA}"

# ──── Create tmux Session ────────────────────────────────────────────
if ! tmux new-session -d -s "$SESSION" "$CC_CMD"; then
  echo "Error: Failed to create tmux session '$SESSION'" >&2
  rm -f "$PROMPT_FILE"
  exit 1
fi
# 释放 dispatch 锁（session 已注册到 tmux，后续 dispatch 能计数到它）
_unlock

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

# State file (atomic write, Pattern 6)
_STATE_TMP="${STATE_FILE}.${$}.tmp"
cat > "$_STATE_TMP" <<EOJSON
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
mv "$_STATE_TMP" "$STATE_FILE"

# Progress file (atomic write, Pattern 6)
_PROG_TMP="${PROGRESS_DIR}/${SESSION}.${$}.tmp"
jq -n --arg s "$SESSION" --arg p "starting" --arg pd "$WORKDIR" --arg m "interactive" --arg ts "$NOW" \
  '{session:$s,phase:$p,project_dir:$pd,mode:$m,tools_used:0,updated_at:$ts}' \
  > "$_PROG_TMP" 2>/dev/null && mv "$_PROG_TMP" "$PROGRESS_DIR/${SESSION}.json" || true

# ──── Observability 注册（非阻塞）────────────────────────────────────
if [[ -f "$TMUX_SYNC_SCRIPT" ]]; then
  python3 "$TMUX_SYNC_SCRIPT" register \
    --task-id "tsk_${TYPE:-task}_$(echo "$LABEL" | tr '-' '_')" \
    --label "$SESSION" \
    --owner "dispatch" \
    --scenario "${TYPE:-custom}" 2>/dev/null || true
fi

# ──── Output ─────────────────────────────────────────────────────────
echo "Started: $SESSION (interactive, timeout=${TIMEOUT}s)"
if $RALPH_ENABLED; then
echo "  Ralph:    ON (max $RALPH_MAX_ITERATIONS iterations)"
fi
echo "  Workdir:  $WORK_DIR"
if $NEEDS_WORKTREE; then
echo "  Worktree: $WORKTREE_DIR"
fi
echo "  State:    $STATE_FILE"
echo "  Progress: $PROGRESS_DIR/${SESSION}.json"
echo "  Attach:   tmux attach -t $SESSION"
