#!/usr/bin/env python3
"""
test_dashboard.py — 可视化看板验证脚本

验证内容：
1. 能正确读取状态卡
2. 能正确展示摘要
3. 能导出 JSON 快照
4. 关键字段完整

使用示例：
```bash
python runtime/tests/orchestrator/test_dashboard.py
```
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime

# 添加路径
ORCHESTRATOR_PATH = Path(__file__).parent.parent.parent / "orchestrator"
sys.path.insert(0, str(ORCHESTRATOR_PATH))

from observability_card import (
    ObservabilityCard,
    ObservabilityCardManager,
    list_cards,
    generate_board_snapshot,
    CARD_DIR,
    create_card,
    update_card,
    delete_card,
)

# 测试颜色
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"


def print_test(name: str, passed: bool, details: str = ""):
    """打印测试结果"""
    status = f"{GREEN}✅ PASS{RESET}" if passed else f"{RED}❌ FAIL{RESET}"
    print(f"{status} {name}")
    if details and not passed:
        print(f"       {YELLOW}Details: {details}{RESET}")


def test_card_directory_exists():
    """测试 1: 状态卡目录存在"""
    exists = CARD_DIR.exists()
    print_test("状态卡目录存在", exists, f"路径：{CARD_DIR}")
    return exists


def test_cards_readable():
    """测试 2: 状态卡可读"""
    try:
        cards = list_cards(limit=100)
        passed = isinstance(cards, list)
        print_test("状态卡可读", passed, f"读取到 {len(cards)} 张卡片")
        return passed
    except Exception as e:
        print_test("状态卡可读", False, str(e))
        return False


def test_card_fields_complete():
    """测试 3: 卡片字段完整"""
    cards = list_cards(limit=10)
    if not cards:
        print_test("卡片字段完整", False, "没有卡片可测试")
        return False
    
    required_fields = [
        "task_id", "scenario", "owner", "executor", "stage",
        "heartbeat", "promise_anchor", "metrics"
    ]
    
    all_passed = True
    for card in cards:
        card_dict = card.to_dict()
        for field in required_fields:
            if field not in card_dict:
                print_test(f"卡片字段完整 - {card.task_id}", False, f"缺少字段：{field}")
                all_passed = False
                break
    
    if all_passed:
        print_test("卡片字段完整", True, f"检查 {len(cards)} 张卡片，所有必需字段存在")
    
    return all_passed


def test_key_fields_display():
    """测试 4: 关键字段可展示"""
    cards = list_cards(limit=5)
    if not cards:
        print_test("关键字段可展示", False, "没有卡片可测试")
        return False
    
    # 检查关键字段
    key_fields = {
        "task_id": lambda c: c.task_id,
        "scenario": lambda c: c.scenario,
        "owner": lambda c: c.owner,
        "executor": lambda c: c.executor,
        "stage": lambda c: c.stage,
        "heartbeat": lambda c: c.heartbeat,
        "promised_eta": lambda c: c.promise_anchor.get("promised_eta") if c.promise_anchor else None,
        "anchor": lambda c: c.promise_anchor.get("anchor_value") if c.promise_anchor else None,
    }
    
    all_passed = True
    for card in cards:
        for field_name, getter in key_fields.items():
            try:
                value = getter(card)
                # anchor 和 promised_eta 可以为 None
                if field_name not in ["promised_eta", "anchor"] and value is None:
                    print_test(f"关键字段 {field_name} - {card.task_id}", False, "值为 None")
                    all_passed = False
            except Exception as e:
                print_test(f"关键字段 {field_name} - {card.task_id}", False, str(e))
                all_passed = False
    
    if all_passed:
        print_test("关键字段可展示", True, f"检查 {len(cards)} 张卡片，所有关键字段可访问")
    
    return all_passed


def test_board_snapshot_generation():
    """测试 5: 看板快照生成"""
    try:
        snapshot = generate_board_snapshot()
        
        # 检查快照结构
        required_keys = ["snapshot_version", "generated_at", "date", "summary", "cards_by_stage", "all_cards"]
        missing_keys = [k for k in required_keys if k not in snapshot]
        
        if missing_keys:
            print_test("看板快照生成", False, f"缺少键：{missing_keys}")
            return False
        
        # 检查摘要
        summary = snapshot.get("summary", {})
        if "total_cards" not in summary:
            print_test("看板快照生成", False, "摘要缺少 total_cards")
            return False
        
        if "by_stage" not in summary:
            print_test("看板快照生成", False, "摘要缺少 by_stage")
            return False
        
        if "by_owner" not in summary:
            print_test("看板快照生成", False, "摘要缺少 by_owner")
            return False
        
        print_test(
            "看板快照生成",
            True,
            f"总任务数：{summary['total_cards']}, 阶段数：{len(summary['by_stage'])}, Owner 数：{len(summary['by_owner'])}"
        )
        return True
    except Exception as e:
        print_test("看板快照生成", False, str(e))
        return False


def test_snapshot_export():
    """测试 6: 快照导出"""
    import tempfile
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        temp_path = f.name
    
    try:
        from dashboard import Dashboard
        dashboard = Dashboard()
        output_path = dashboard.export_snapshot(temp_path)
        
        # 检查文件存在
        if not Path(output_path).exists():
            print_test("快照导出", False, "导出文件不存在")
            return False
        
        # 检查 JSON 有效性
        with open(output_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if not isinstance(data, dict):
            print_test("快照导出", False, "导出的 JSON 不是对象")
            return False
        
        print_test("快照导出", True, f"导出路径：{output_path}, 大小：{Path(output_path).stat().st_size} bytes")
        return True
    except Exception as e:
        print_test("快照导出", False, str(e))
        return False
    finally:
        # 清理临时文件
        if Path(temp_path).exists():
            Path(temp_path).unlink()


def test_dashboard_render():
    """测试 7: 看板渲染"""
    try:
        from dashboard import render_dashboard, Dashboard
        
        dashboard = Dashboard()
        cards = dashboard.load_cards()
        
        if not cards:
            print_test("看板渲染", False, "没有卡片可渲染")
            return False
        
        layout = render_dashboard(cards)
        
        # 检查布局结构
        if not hasattr(layout, "tree"):
            print_test("看板渲染", False, "布局不是有效的 Layout 对象")
            return False
        
        print_test("看板渲染", True, f"渲染 {len(cards)} 张卡片到布局")
        return True
    except ImportError as e:
        print_test("看板渲染", False, f"导入失败：{e}（请确保 rich 已安装）")
        return False
    except Exception as e:
        print_test("看板渲染", False, str(e))
        return False


def test_stage_grouping():
    """测试 8: 按 stage 分组"""
    cards = list_cards(limit=100)
    if not cards:
        print_test("按 stage 分组", False, "没有卡片可测试")
        return False
    
    # 手动分组
    by_stage = {}
    for card in cards:
        if card.stage not in by_stage:
            by_stage[card.stage] = []
        by_stage[card.stage].append(card)
    
    # 检查分组正确性
    total_from_groups = sum(len(group) for group in by_stage.values())
    passed = total_from_groups == len(cards)
    
    print_test(
        "按 stage 分组",
        passed,
        f"总卡片数：{len(cards)}, 分组总和：{total_from_groups}, 阶段数：{len(by_stage)}"
    )
    return passed


def test_owner_grouping():
    """测试 9: 按 owner 分组"""
    cards = list_cards(limit=100)
    if not cards:
        print_test("按 owner 分组", False, "没有卡片可测试")
        return False
    
    # 手动分组
    by_owner = {}
    for card in cards:
        if card.owner not in by_owner:
            by_owner[card.owner] = []
        by_owner[card.owner].append(card)
    
    # 检查分组正确性
    total_from_groups = sum(len(group) for group in by_owner.values())
    passed = total_from_groups == len(cards)
    
    print_test(
        "按 owner 分组",
        passed,
        f"总卡片数：{len(cards)}, 分组总和：{total_from_groups}, Owner 数：{len(by_owner)}"
    )
    return passed


def test_heartbeat_format():
    """测试 10: 心跳时间格式化"""
    try:
        from dashboard import format_heartbeat
        
        # 测试不同格式
        test_cases = [
            "2026-03-30T00:00:00+08:00",
            "2026-03-30T00:00:00",
            "2026-03-30 00:00:00",
        ]
        
        all_passed = True
        for tc in test_cases:
            try:
                result = format_heartbeat(tc)
                if not result or not isinstance(result, str):
                    print_test(f"心跳格式化 - {tc}", False, f"返回无效：{result}")
                    all_passed = False
            except Exception as e:
                print_test(f"心跳格式化 - {tc}", False, str(e))
                all_passed = False
        
        if all_passed:
            print_test("心跳时间格式化", True, "所有测试用例通过")
        
        return all_passed
    except Exception as e:
        print_test("心跳时间格式化", False, str(e))
        return False


def test_eta_color():
    """测试 11: ETA 颜色判断"""
    try:
        from dashboard import get_eta_color
        
        now = datetime.now()
        
        # 测试过期 ETA
        past = now.replace(year=2020).isoformat()
        color_past = get_eta_color(past, now.isoformat())
        
        # 测试未来 ETA
        future = now.replace(year=2030).isoformat()
        color_future = get_eta_color(future, now.isoformat())
        
        # 过期应为红色
        if color_past != "red":
            print_test("ETA 颜色判断 - 过期", False, f"期望 red，得到 {color_past}")
            return False
        
        # 未来应为绿色
        if color_future != "green":
            print_test("ETA 颜色判断 - 未来", False, f"期望 green，得到 {color_future}")
            return False
        
        print_test("ETA 颜色判断", True, "过期=red, 未来=green")
        return True
    except Exception as e:
        print_test("ETA 颜色判断", False, str(e))
        return False


def test_anchor_display():
    """测试 12: 锚点显示"""
    try:
        from dashboard import get_anchor_display
        from observability_card import ObservabilityCard
        
        # 创建测试卡片
        card = ObservabilityCard(
            task_id="test_001",
            scenario="custom",
            owner="main",
            executor="subagent",
            stage="running",
            heartbeat=datetime.now().isoformat(),
            promise_anchor={
                "anchor_type": "tmux_session",
                "anchor_value": "cc-test-session-123",
            },
        )
        
        display = get_anchor_display(card)
        
        if not display or "[tmux]" not in display:
            print_test("锚点显示", False, f"期望包含 [tmux]，得到 {display}")
            return False
        
        print_test("锚点显示", True, f"显示：{display}")
        return True
    except Exception as e:
        print_test("锚点显示", False, str(e))
        return False


def run_all_tests():
    """运行所有测试"""
    print(f"\n{BLUE}{'='*60}{RESET}")
    print(f"{BLUE}可视化看板验证测试 - Batch 6{RESET}")
    print(f"{BLUE}{'='*60}{RESET}\n")
    
    tests = [
        ("目录存在", test_card_directory_exists),
        ("卡片可读", test_cards_readable),
        ("字段完整", test_card_fields_complete),
        ("关键字段", test_key_fields_display),
        ("快照生成", test_board_snapshot_generation),
        ("快照导出", test_snapshot_export),
        ("看板渲染", test_dashboard_render),
        ("Stage 分组", test_stage_grouping),
        ("Owner 分组", test_owner_grouping),
        ("心跳格式化", test_heartbeat_format),
        ("ETA 颜色", test_eta_color),
        ("锚点显示", test_anchor_display),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"{RED}❌ EXCEPTION{RESET} {name}: {e}")
            results.append((name, False))
        print()
    
    # 汇总
    print(f"{BLUE}{'='*60}{RESET}")
    print(f"{BLUE}测试汇总{RESET}")
    print(f"{BLUE}{'='*60}{RESET}\n")
    
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    for name, result in results:
        status = f"{GREEN}✅{RESET}" if result else f"{RED}❌{RESET}"
        print(f"{status} {name}")
    
    print(f"\n总计：{GREEN}{passed}/{total}{RESET} 通过")
    
    if passed == total:
        print(f"\n{GREEN}🎉 所有测试通过！Batch 6 验证完成。{RESET}\n")
        return 0
    else:
        print(f"\n{RED}⚠️  {total - passed} 个测试失败，请检查。{RESET}\n")
        return 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
