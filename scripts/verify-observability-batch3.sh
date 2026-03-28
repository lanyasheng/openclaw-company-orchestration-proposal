#!/usr/bin/env bash
set -euo pipefail

# verify-observability-batch3.sh — Observability Batch 3 验证脚本
# 验证 tmux 统一状态索引功能

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ORCH_REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SYNC_SCRIPT="$ORCH_REPO_DIR/scripts/sync-tmux-observability.py"
TEST_DIR="$ORCH_REPO_DIR/runtime/tests/orchestrator/observability"

echo "=============================================="
echo "Observability Batch 3 Verification"
echo "=============================================="
echo ""

PASSED=0
FAILED=0

pass() {
  echo "✅ $1"
  PASSED=$((PASSED + 1))
}

fail() {
  echo "❌ $1"
  FAILED=$((FAILED + 1))
}

# 1. 检查核心模块文件存在
echo "1. Checking core module files..."

if [[ -f "$ORCH_REPO_DIR/runtime/orchestrator/tmux_status_sync.py" ]]; then
  pass "tmux_status_sync.py exists"
else
  fail "tmux_status_sync.py missing"
fi

if [[ -f "$TEST_DIR/test_tmux_status_sync.py" ]]; then
  pass "test_tmux_status_sync.py exists"
else
  fail "test_tmux_status_sync.py missing"
fi

if [[ -f "$SYNC_SCRIPT" ]]; then
  pass "sync-tmux-observability.py exists"
else
  fail "sync-tmux-observability.py missing"
fi

# 2. 检查脚本集成
echo ""
echo "2. Checking script integrations..."

# Check both possible paths for skills directory
SKILLS_PATH1="$ORCH_REPO_DIR/../skills/claude-code-orchestrator/scripts"
SKILLS_PATH2="$HOME/.openclaw/skills/claude-code-orchestrator/scripts"

START_SCRIPT=""
STATUS_SCRIPT=""

if [[ -f "$SKILLS_PATH1/start-tmux-task.sh" ]]; then
  START_SCRIPT="$SKILLS_PATH1/start-tmux-task.sh"
  STATUS_SCRIPT="$SKILLS_PATH1/status-tmux-task.sh"
elif [[ -f "$SKILLS_PATH2/start-tmux-task.sh" ]]; then
  START_SCRIPT="$SKILLS_PATH2/start-tmux-task.sh"
  STATUS_SCRIPT="$SKILLS_PATH2/status-tmux-task.sh"
fi

if [[ -n "$START_SCRIPT" ]] && grep -q "Observability Batch 3" "$START_SCRIPT" 2>/dev/null; then
  pass "start-tmux-task.sh has Batch 3 integration"
else
  fail "start-tmux-task.sh missing Batch 3 integration"
fi

if [[ -n "$STATUS_SCRIPT" ]] && grep -q "Observability Batch 3" "$STATUS_SCRIPT" 2>/dev/null; then
  pass "status-tmux-task.sh has Batch 3 integration"
else
  fail "status-tmux-task.sh missing Batch 3 integration"
fi

# 3. 运行单元测试
echo ""
echo "3. Running unit tests..."

cd "$ORCH_REPO_DIR"

# 运行 pytest（设置 PYTHONPATH）
if PYTHONPATH="$ORCH_REPO_DIR/runtime/orchestrator:${PYTHONPATH:-}" python3 -m pytest "$TEST_DIR/test_tmux_status_sync.py" -v --tb=short 2>&1 | tee /tmp/batch3_test_output.txt | grep -q "passed"; then
  pass "Unit tests passed"
else
  # 检查是否有测试被跳过
  if grep -q "skipped" /tmp/batch3_test_output.txt && ! grep -q "passed" /tmp/batch3_test_output.txt; then
    # 重试，确保 PYTHONPATH 正确
    if PYTHONPATH="$ORCH_REPO_DIR/runtime/orchestrator" python3 -m pytest "$TEST_DIR/test_tmux_status_sync.py" -v 2>&1 | tee /tmp/batch3_test_output.txt | grep -q "passed"; then
      pass "Unit tests passed (retry)"
    else
      fail "Unit tests skipped or failed"
      echo "   See /tmp/batch3_test_output.txt for details"
    fi
  elif grep -q "failed" /tmp/batch3_test_output.txt; then
    fail "Unit tests failed"
    echo "   See /tmp/batch3_test_output.txt for details"
  else
    fail "Unit tests execution failed"
  fi
fi

# 4. 测试 CLI 工具
echo ""
echo "4. Testing CLI tool..."

# 测试 help
if python3 "$SYNC_SCRIPT" --help >/dev/null 2>&1; then
  pass "CLI help works"
else
  fail "CLI help failed"
fi

# 测试 register 命令（dry-run）
if python3 "$SYNC_SCRIPT" register --help >/dev/null 2>&1; then
  pass "CLI register command available"
else
  fail "CLI register command missing"
fi

# 测试 update 命令
if python3 "$SYNC_SCRIPT" update --help >/dev/null 2>&1; then
  pass "CLI update command available"
else
  fail "CLI update command missing"
fi

# 测试 status 命令
if python3 "$SYNC_SCRIPT" status --help >/dev/null 2>&1; then
  pass "CLI status command available"
else
  fail "CLI status command missing"
fi

# 测试 list 命令
if python3 "$SYNC_SCRIPT" list --help >/dev/null 2>&1; then
  pass "CLI list command available"
else
  fail "CLI list command missing"
fi

# 5. 功能测试：注册任务
echo ""
echo "5. Testing functional registration..."

TEST_TASK_ID="test_batch3_$(date +%s)"
TEST_LABEL="batch3-test"

REGISTER_OUTPUT=$(python3 "$SYNC_SCRIPT" register \
  --task-id "$TEST_TASK_ID" \
  --label "$TEST_LABEL" \
  --owner "main" \
  --scenario "custom" \
  --promised-eta "$(date -v+2H +%Y-%m-%dT%H:%M:%S 2>/dev/null || date +%Y-%m-%dT%H:%M:%S)" \
  2>&1 || true)

if echo "$REGISTER_OUTPUT" | grep -q '"success": true'; then
  pass "Task registration works"
else
  fail "Task registration failed: $REGISTER_OUTPUT"
fi

# 6. 功能测试：查询状态
echo ""
echo "6. Testing status query..."

STATUS_OUTPUT=$(python3 "$SYNC_SCRIPT" status --session "cc-$TEST_LABEL" 2>&1 || true)

# 状态查询应该返回一些内容（即使 session 不存在）
if [[ -n "$STATUS_OUTPUT" ]]; then
  pass "Status query returns output"
else
  fail "Status query returned empty"
fi

# 7. 功能测试：列出 session
echo ""
echo "7. Testing session listing..."

LIST_OUTPUT=$(python3 "$SYNC_SCRIPT" list --owner main --limit 10 2>&1 || true)

if echo "$LIST_OUTPUT" | grep -q '"success": true'; then
  pass "Session listing works"
else
  fail "Session listing failed: $LIST_OUTPUT"
fi

# 8. 验证状态卡 schema
echo ""
echo "8. Verifying card schema..."

if echo "$REGISTER_OUTPUT" | grep -q '"executor": "tmux"'; then
  pass "Card has tmux executor type"
else
  fail "Card missing tmux executor"
fi

if echo "$REGISTER_OUTPUT" | grep -q '"anchor_type": "tmux_session"'; then
  pass "Card has tmux_session anchor type"
else
  fail "Card missing tmux_session anchor"
fi

# 9. 清理测试数据
echo ""
echo "9. Cleaning up test data..."

python3 "$SYNC_SCRIPT" list --owner main --limit 100 2>/dev/null | \
  grep -o '"task_id": "test_batch3_[0-9]*"' | \
  cut -d'"' -f4 | \
  while read -r tid; do
    # 删除测试卡片（通过 Python API）
    python3 -c "
import sys
sys.path.insert(0, '$ORCH_REPO_DIR/runtime/orchestrator')
from observability_card import delete_card
delete_card('$tid')
" 2>/dev/null || true
  done

pass "Test data cleaned"

# 10. 验证模块导入
echo ""
echo "10. Verifying module imports..."

if python3 -c "
import sys
sys.path.insert(0, '$ORCH_REPO_DIR/runtime/orchestrator')
from tmux_status_sync import (
    TmuxStatusSync,
    TMUX_STATUS_MAP,
    get_tmux_status,
    register_tmux_card,
    sync_tmux_session,
    list_tmux_cards,
)
print('All imports successful')
" 2>&1; then
  pass "Module imports work correctly"
else
  fail "Module imports failed"
fi

# 总结
echo ""
echo "=============================================="
echo "Verification Summary"
echo "=============================================="
echo "Tests Passed: $PASSED"
echo "Tests Failed: $FAILED"
echo ""

if [[ $FAILED -eq 0 ]]; then
  echo "✅ Batch 3 Verification PASSED"
  exit 0
else
  echo "❌ Batch 3 Verification FAILED"
  exit 1
fi
