#!/bin/bash
# verify-observability-batch4.sh — Observability Batch 4 验证脚本

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RUNTIME_DIR="$REPO_ROOT/runtime"

echo "========================================"
echo "Observability Batch 4 Verification"
echo "========================================"
echo ""

# 颜色定义
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

pass_count=0
fail_count=0

pass() {
    echo -e "${GREEN}✅ PASS${NC}: $1"
    ((pass_count++))
}

fail() {
    echo -e "${RED}❌ FAIL${NC}: $1"
    ((fail_count++))
}

warn() {
    echo -e "${YELLOW}⚠️  WARN${NC}: $1"
}

# 测试计数器
test_num=0

# =============================================================================
# 1. 检查核心模块文件存在
# =============================================================================
echo "1. Checking core module files..."
echo ""

test_num=$((test_num + 1))
if [[ -f "$RUNTIME_DIR/orchestrator/alert_dispatcher.py" ]]; then
    pass "alert_dispatcher.py exists (Test $test_num)"
else
    fail "alert_dispatcher.py missing (Test $test_num)"
fi

test_num=$((test_num + 1))
if [[ -f "$RUNTIME_DIR/orchestrator/human_report_renderer.py" ]]; then
    pass "human_report_renderer.py exists (Test $test_num)"
else
    fail "human_report_renderer.py missing (Test $test_num)"
fi

test_num=$((test_num + 1))
if [[ -f "$RUNTIME_DIR/orchestrator/alert_rules.py" ]]; then
    pass "alert_rules.py exists (Test $test_num)"
else
    fail "alert_rules.py missing (Test $test_num)"
fi

test_num=$((test_num + 1))
if [[ -f "$RUNTIME_DIR/orchestrator/alert_audit.py" ]]; then
    pass "alert_audit.py exists (Test $test_num)"
else
    fail "alert_audit.py missing (Test $test_num)"
fi

echo ""

# =============================================================================
# 2. 检查测试文件存在
# =============================================================================
echo "2. Checking test files..."
echo ""

test_num=$((test_num + 1))
if [[ -f "$RUNTIME_DIR/tests/orchestrator/alerts/test_alert_dispatcher.py" ]]; then
    pass "test_alert_dispatcher.py exists (Test $test_num)"
else
    fail "test_alert_dispatcher.py missing (Test $test_num)"
fi

test_num=$((test_num + 1))
if [[ -f "$RUNTIME_DIR/tests/orchestrator/alerts/test_human_report_renderer.py" ]]; then
    pass "test_human_report_renderer.py exists (Test $test_num)"
else
    fail "test_human_report_renderer.py missing (Test $test_num)"
fi

test_num=$((test_num + 1))
if [[ -f "$RUNTIME_DIR/tests/orchestrator/alerts/test_alert_rules.py" ]]; then
    pass "test_alert_rules.py exists (Test $test_num)"
else
    fail "test_alert_rules.py missing (Test $test_num)"
fi

test_num=$((test_num + 1))
if [[ -f "$RUNTIME_DIR/tests/orchestrator/alerts/test_alert_audit.py" ]]; then
    pass "test_alert_audit.py exists (Test $test_num)"
else
    fail "test_alert_audit.py missing (Test $test_num)"
fi

echo ""

# =============================================================================
# 3. 检查模块可导入
# =============================================================================
echo "3. Checking module imports..."
echo ""

cd "$RUNTIME_DIR/orchestrator"

test_num=$((test_num + 1))
if python3 -c "from alert_dispatcher import AlertDispatcher" 2>/dev/null; then
    pass "alert_dispatcher importable (Test $test_num)"
else
    fail "alert_dispatcher not importable (Test $test_num)"
fi

test_num=$((test_num + 1))
if python3 -c "from human_report_renderer import HumanReportRenderer" 2>/dev/null; then
    pass "human_report_renderer importable (Test $test_num)"
else
    fail "human_report_renderer not importable (Test $test_num)"
fi

test_num=$((test_num + 1))
if python3 -c "from alert_rules import AlertRules" 2>/dev/null; then
    pass "alert_rules importable (Test $test_num)"
else
    fail "alert_rules not importable (Test $test_num)"
fi

test_num=$((test_num + 1))
if python3 -c "from alert_audit import AlertAuditLogger" 2>/dev/null; then
    pass "alert_audit importable (Test $test_num)"
else
    fail "alert_audit not importable (Test $test_num)"
fi

echo ""

# =============================================================================
# 4. 运行单元测试
# =============================================================================
echo "4. Running unit tests..."
echo ""

cd "$RUNTIME_DIR"

test_num=$((test_num + 1))
if pytest tests/orchestrator/alerts/ -v --tb=short 2>&1 | tee /tmp/batch4_test_output.txt; then
    pass "Unit tests passed (Test $test_num)"
else
    fail "Unit tests failed (Test $test_num)"
fi

echo ""

# =============================================================================
# 5. 检查文档文件
# =============================================================================
echo "5. Checking documentation files..."
echo ""

test_num=$((test_num + 1))
if [[ -f "$REPO_ROOT/docs/observability-batch4-design.md" ]]; then
    pass "observability-batch4-design.md exists (Test $test_num)"
else
    fail "observability-batch4-design.md missing (Test $test_num)"
fi

echo ""

# =============================================================================
# 6. 快速功能测试
# =============================================================================
echo "6. Running quick functional tests..."
echo ""

cd "$RUNTIME_DIR/orchestrator"

test_num=$((test_num + 1))
if python3 -c "
from alert_dispatcher import AlertDispatcher
from human_report_renderer import HumanReportRenderer
from alert_rules import AlertRules
from alert_audit import AlertAuditLogger
import tempfile
import os

# 创建临时目录
tmp_dir = tempfile.mkdtemp()

# 测试告警调度器
dispatcher = AlertDispatcher(channel='file', dry_run=True)

# 测试完成告警
receipt = {
    'receipt_id': 'test_001',
    'source_task_id': 'task_001',
    'receipt_status': 'completed',
    'result_summary': 'Test completed',
}
context = {'label': 'test', 'scenario': 'custom', 'owner': 'main'}
payload, result = dispatcher.dispatch_completion_alert(receipt, context)
assert payload is not None, 'Completion alert should be created'
assert result.status == 'dry_run', 'Should be dry run'

# 测试渲染器
renderer = HumanReportRenderer()
summary = renderer.render_completion_summary(receipt, context)
assert '完成' in summary, 'Summary should contain completion text'

# 测试规则
rules = AlertRules()
from datetime import datetime, timedelta
past_eta = (datetime.now() - timedelta(hours=1)).isoformat()
card = {
    'task_id': 'task_002',
    'stage': 'running',
    'heartbeat': datetime.now().isoformat(),
    'promise_anchor': {'promised_eta': past_eta},
}
timeout_result = rules.check_timeout(card)
assert timeout_result.is_timeout, 'Should be timeout'

# 测试审计
audit_logger = AlertAuditLogger(audit_dir=tmp_dir)
record = audit_logger.log_alert(
    alert_type='task_timeout',
    task_id='task_003',
    alert_id='alert_003',
    payload={},
    delivery_result={'status': 'sent'},
)
assert record.audit_id.startswith('audit_'), 'Audit ID should start with audit_'

# 清理
import shutil
shutil.rmtree(tmp_dir)

print('All functional tests passed!')
" 2>&1; then
    pass "Functional tests passed (Test $test_num)"
else
    fail "Functional tests failed (Test $test_num)"
fi

echo ""

# =============================================================================
# 总结
# =============================================================================
echo "========================================"
echo "Verification Summary"
echo "========================================"
echo -e "Tests Passed: ${GREEN}$pass_count${NC}"
echo -e "Tests Failed: ${RED}$fail_count${NC}"
echo ""

if [[ $fail_count -eq 0 ]]; then
    echo -e "${GREEN}✅ Batch 4 Verification PASSED${NC}"
    echo ""
    echo "Next steps:"
    echo "1. Review the implementation"
    echo "2. Commit and push to origin/main"
    echo "3. Update completion report"
    exit 0
else
    echo -e "${RED}❌ Batch 4 Verification FAILED${NC}"
    echo ""
    echo "Please fix the failing tests and re-run."
    exit 1
fi
