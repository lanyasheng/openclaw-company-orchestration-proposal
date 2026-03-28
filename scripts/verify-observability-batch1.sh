#!/bin/bash
# verify-observability-batch1.sh — 验证 Batch 1 实现

set -e

echo "=============================================="
echo "Observability Transparency - Batch 1 Verification"
echo "=============================================="
echo ""

# 颜色定义
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 计数器
TESTS_PASSED=0
TESTS_FAILED=0

# 测试函数
run_test() {
    local test_name="$1"
    local test_command="$2"
    
    echo -n "Testing: $test_name ... "
    
    if eval "$test_command" > /dev/null 2>&1; then
        echo -e "${GREEN}PASS${NC}"
        ((TESTS_PASSED++))
        return 0
    else
        echo -e "${RED}FAIL${NC}"
        ((TESTS_FAILED++))
        return 1
    fi
}

# 1. 检查模块文件存在
echo "1. Checking module files..."
echo "-------------------------------------------"

run_test "observability_card.py exists" \
    "test -f runtime/orchestrator/observability_card.py"

run_test "test_card.py exists" \
    "test -f tests/orchestrator/observability/test_card.py"

run_test "design doc exists" \
    "test -f docs/observability-transparency-design-2026-03-28.md"

echo ""

# 2. 运行单元测试
echo "2. Running unit tests..."
echo "-------------------------------------------"

cd "$(dirname "$0")/.."

if python3 -m pytest tests/orchestrator/observability/test_card.py -v --tb=short 2>&1 | tee /tmp/observability_test_output.txt; then
    echo -e "${GREEN}Unit tests passed${NC}"
    ((TESTS_PASSED++))
else
    echo -e "${RED}Unit tests failed${NC}"
    ((TESTS_FAILED++))
fi

echo ""

# 3. 快速功能测试
echo "3. Running quick functional tests..."
echo "-------------------------------------------"

# 创建测试卡片
python3 << 'EOF'
import sys
sys.path.insert(0, 'runtime/orchestrator')

from observability_card import (
    create_card,
    get_card,
    update_card,
    list_cards,
    delete_card,
    generate_board_snapshot,
)

# 测试创建
card = create_card(
    task_id="verify_test_001",
    scenario="custom",
    owner="main",
    executor="subagent",
    stage="dispatch",
    promised_eta="2026-03-28T16:00:00",
    anchor_type="session_id",
    anchor_value="cc-verify-001",
)
assert card.task_id == "verify_test_001", "Create failed"
print("✓ Card created")

# 测试读取
retrieved = get_card("verify_test_001")
assert retrieved is not None, "Get failed"
assert retrieved.task_id == "verify_test_001", "Get data mismatch"
print("✓ Card retrieved")

# 测试更新
updated = update_card(
    task_id="verify_test_001",
    stage="running",
    recent_output="Verification in progress...",
)
assert updated.stage == "running", "Update stage failed"
assert updated.recent_output == "Verification in progress...", "Update output failed"
print("✓ Card updated")

# 测试查询
cards = list_cards(owner="main", limit=100)
assert len(cards) >= 1, "List failed"
print(f"✓ Listed {len(cards)} cards")

# 测试快照
snapshot = generate_board_snapshot()
assert "summary" in snapshot, "Snapshot failed"
assert snapshot["summary"]["total_cards"] >= 1, "Snapshot summary failed"
print(f"✓ Snapshot generated with {snapshot['summary']['total_cards']} cards")

# 清理
delete_card("verify_test_001")
print("✓ Test card cleaned up")

print("\nAll functional tests passed!")
EOF

if [ $? -eq 0 ]; then
    echo -e "${GREEN}Functional tests passed${NC}"
    ((TESTS_PASSED++))
else
    echo -e "${RED}Functional tests failed${NC}"
    ((TESTS_FAILED++))
fi

echo ""

# 4. 检查目录结构
echo "4. Checking directory structure..."
echo "-------------------------------------------"

OBSERVABILITY_DIR="$HOME/.openclaw/shared-context/observability"

run_test "observability base dir exists" \
    "test -d $OBSERVABILITY_DIR"

run_test "cards dir exists" \
    "test -d $OBSERVABILITY_DIR/cards"

run_test "index dir exists" \
    "test -d $OBSERVABILITY_DIR/index"

run_test "boards dir exists" \
    "test -d $OBSERVABILITY_DIR/boards"

echo ""

# 5. 检查索引文件
echo "5. Checking index files..."
echo "-------------------------------------------"

run_test "main index exists" \
    "test -f $OBSERVABILITY_DIR/index/main.jsonl"

echo ""

# 6. 检查看板快照
echo "6. Checking board snapshots..."
echo "-------------------------------------------"

TODAY=$(date +%Y-%m-%d)
run_test "today's board snapshot exists" \
    "test -f $OBSERVABILITY_DIR/boards/board-${TODAY}.json"

echo ""

# 7. 检查设计文档内容
echo "7. Checking design doc content..."
echo "-------------------------------------------"

run_test "design doc has three-layer architecture" \
    "grep -q 'Observability Plane' docs/observability-transparency-design-2026-03-28.md"

run_test "design doc has card schema" \
    "grep -q 'card_version' docs/observability-transparency-design-2026-03-28.md"

run_test "design doc has batch plan" \
    "grep -q 'Batch 1' docs/observability-transparency-design-2026-03-28.md"

echo ""

# 总结
echo "=============================================="
echo "Verification Summary"
echo "=============================================="
echo -e "Tests Passed: ${GREEN}$TESTS_PASSED${NC}"
echo -e "Tests Failed: ${RED}$TESTS_FAILED${NC}"
echo ""

if [ $TESTS_FAILED -eq 0 ]; then
    echo -e "${GREEN}✅ Batch 1 Verification PASSED${NC}"
    echo ""
    echo "Next steps:"
    echo "1. Review design doc: docs/observability-transparency-design-2026-03-28.md"
    echo "2. Check test coverage: tests/orchestrator/observability/test_card.py"
    echo "3. Try CLI commands (if integrated): python3 runtime/orchestrator/cli.py orch-observability --help"
    echo ""
    exit 0
else
    echo -e "${RED}❌ Batch 1 Verification FAILED${NC}"
    echo ""
    echo "Check /tmp/observability_test_output.txt for details"
    exit 1
fi
