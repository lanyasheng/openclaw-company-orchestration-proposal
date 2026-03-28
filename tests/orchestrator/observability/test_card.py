#!/usr/bin/env python3
"""
test_card.py — 状态卡系统单元测试

测试覆盖：
1. 创建状态卡
2. 读取状态卡
3. 更新状态卡
4. 删除状态卡
5. 查询状态卡（过滤）
6. 生成看板快照
7. 指标自动计算
"""

import json
import sys
import unittest
from datetime import datetime
from pathlib import Path

# 添加 runtime/orchestrator 到路径
REPO_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "runtime" / "orchestrator"))

from observability_card import (
    CARD_VERSION,
    ObservabilityCard,
    ObservabilityCardManager,
    create_card,
    get_card,
    update_card,
    delete_card,
    list_cards,
    generate_board_snapshot,
    _ensure_dirs,
    _card_file,
    _iso_now,
)


class TestObservabilityCard(unittest.TestCase):
    """状态卡基础测试（使用全局目录）"""
    
    def setUp(self):
        """每个测试前确保目录存在"""
        _ensure_dirs()
        self.test_task_ids = []
    
    def tearDown(self):
        """每个测试后清理测试卡片"""
        for task_id in self.test_task_ids:
            delete_card(task_id)
    
    def _create_test_card(self, task_id: str, **kwargs):
        """创建测试卡片并记录 ID"""
        self.test_task_ids.append(task_id)
        return create_card(
            task_id=task_id,
            scenario=kwargs.get('scenario', 'custom'),
            owner=kwargs.get('owner', 'main'),
            executor=kwargs.get('executor', 'subagent'),
            stage=kwargs.get('stage', 'dispatch'),
            promised_eta=kwargs.get('promised_eta', '2026-03-28T16:00:00'),
            anchor_type=kwargs.get('anchor_type', 'session_id'),
            anchor_value=kwargs.get('anchor_value', f'cc-{task_id}'),
        )
    
    def test_create_card(self):
        """测试创建状态卡"""
        card = self._create_test_card("test_001")
        
        # 验证字段
        self.assertEqual(card.task_id, "test_001")
        self.assertEqual(card.scenario, "custom")
        self.assertEqual(card.owner, "main")
        self.assertEqual(card.executor, "subagent")
        self.assertEqual(card.stage, "dispatch")
        self.assertEqual(card.card_version, CARD_VERSION)
        
        # 验证 promise_anchor
        self.assertIsNotNone(card.promise_anchor)
        self.assertEqual(card.promise_anchor["anchor_type"], "session_id")
        self.assertEqual(card.promise_anchor["anchor_value"], "cc-test_001")
        
        # 验证文件存在
        card_file = _card_file("test_001")
        self.assertTrue(card_file.exists())
        
        # 验证文件内容
        with open(card_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["task_id"], "test_001")
    
    def test_get_card(self):
        """测试读取状态卡"""
        # 先创建
        self._create_test_card(
            "test_002",
            scenario="trading_roundtable",
            owner="trading",
            executor="tmux",
            stage="running",
            anchor_value="cc-trading-001",
        )
        
        # 再读取
        card = get_card("test_002")
        
        self.assertIsNotNone(card)
        self.assertEqual(card.task_id, "test_002")
        self.assertEqual(card.scenario, "trading_roundtable")
        self.assertEqual(card.owner, "trading")
        self.assertEqual(card.executor, "tmux")
        self.assertEqual(card.stage, "running")
    
    def test_get_card_not_found(self):
        """测试读取不存在的卡片"""
        card = get_card("nonexistent_" + _iso_now())
        self.assertIsNone(card)
    
    def test_update_card_stage(self):
        """测试更新状态卡阶段"""
        # 创建
        self._create_test_card(
            "test_003",
            scenario="channel_roundtable",
            owner="ainews",
            anchor_value="cc-dispatch-001",
        )
        
        # 更新阶段
        updated = update_card(
            task_id="test_003",
            stage="running",
            heartbeat=_iso_now(),
        )
        
        self.assertEqual(updated.stage, "running")
        self.assertIsNotNone(updated.metrics.get("started_at"))
    
    def test_update_card_auto_metrics(self):
        """测试更新阶段时自动计算指标"""
        # 创建
        self._create_test_card("test_004", anchor_value="cc-metrics-001")
        
        # 更新为 running
        update_card(task_id="test_004", stage="running")
        
        # 更新为 completed
        import time
        time.sleep(0.1)  # 确保时间差
        updated = update_card(task_id="test_004", stage="completed")
        
        # 验证指标
        self.assertIsNotNone(updated.metrics["completed_at"])
        self.assertGreaterEqual(updated.metrics["duration_seconds"], 0)
    
    def test_update_card_recent_output(self):
        """测试更新最近输出"""
        # 创建
        self._create_test_card("test_005", anchor_value="cc-output-001")
        
        # 更新输出
        updated = update_card(
            task_id="test_005",
            recent_output="Task completed successfully. All tests passed.",
        )
        
        self.assertEqual(updated.recent_output, "Task completed successfully. All tests passed.")
    
    def test_delete_card(self):
        """测试删除状态卡"""
        # 创建
        self._create_test_card("test_006", anchor_value="cc-del-001")
        
        # 验证存在
        card = get_card("test_006")
        self.assertIsNotNone(card)
        
        # 删除
        result = delete_card("test_006")
        self.assertTrue(result)
        
        # 从清理列表移除
        self.test_task_ids.remove("test_006")
        
        # 验证不存在
        card = get_card("test_006")
        self.assertIsNone(card)
    
    def test_delete_card_not_found(self):
        """测试删除不存在的卡片"""
        result = delete_card("nonexistent_" + _iso_now())
        self.assertFalse(result)
    
    def test_list_cards_no_filter(self):
        """测试查询所有卡片"""
        # 创建多个卡片
        for i in range(3):
            self._create_test_card(f"test_list_{i}", anchor_value=f"cc-list-{i}")
        
        # 查询
        cards = list_cards(limit=100)
        
        self.assertGreaterEqual(len(cards), 3)
    
    def test_list_cards_filter_owner(self):
        """测试按 owner 过滤"""
        # 创建不同 owner 的卡片
        self._create_test_card("test_owner_main", owner="main", anchor_value="cc-owner-main")
        self._create_test_card("test_owner_trading", owner="trading", executor="tmux", anchor_value="cc-owner-trading")
        
        # 按 owner 过滤
        main_cards = list_cards(owner="main", limit=100)
        trading_cards = list_cards(owner="trading", limit=100)
        
        self.assertGreaterEqual(len(main_cards), 1)
        self.assertGreaterEqual(len(trading_cards), 1)
        
        for card in main_cards:
            self.assertEqual(card.owner, "main")
        
        for card in trading_cards:
            self.assertEqual(card.owner, "trading")
    
    def test_list_cards_filter_stage(self):
        """测试按 stage 过滤"""
        # 创建不同 stage 的卡片
        self._create_test_card("test_stage_dispatch", stage="dispatch", anchor_value="cc-stage-dispatch")
        self._create_test_card("test_stage_running", stage="running", anchor_value="cc-stage-running")
        self._create_test_card("test_stage_completed", stage="completed", anchor_value="cc-stage-completed")
        
        # 按 stage 过滤
        dispatch_cards = list_cards(stage="dispatch", limit=100)
        running_cards = list_cards(stage="running", limit=100)
        completed_cards = list_cards(stage="completed", limit=100)
        
        self.assertGreaterEqual(len(dispatch_cards), 1)
        self.assertGreaterEqual(len(running_cards), 1)
        self.assertGreaterEqual(len(completed_cards), 1)
    
    def test_generate_board_snapshot(self):
        """测试生成看板快照"""
        # 创建多个卡片
        for i in range(3):
            self._create_test_card(f"test_board_{i}", anchor_value=f"cc-board-{i}")
        
        # 生成快照
        snapshot = generate_board_snapshot()
        
        # 验证快照结构
        self.assertIn("snapshot_version", snapshot)
        self.assertIn("generated_at", snapshot)
        self.assertIn("date", snapshot)
        self.assertIn("summary", snapshot)
        self.assertIn("cards_by_stage", snapshot)
        self.assertIn("all_cards", snapshot)
        
        # 验证汇总（至少有卡片）
        self.assertGreater(snapshot["summary"]["total_cards"], 0)
        self.assertIn("main", snapshot["summary"]["by_owner"])
        
        # 验证我们的卡片在快照中
        task_ids_in_snapshot = [c["task_id"] for c in snapshot["all_cards"]]
        self.assertIn("test_board_0", task_ids_in_snapshot)
        self.assertIn("test_board_1", task_ids_in_snapshot)
        self.assertIn("test_board_2", task_ids_in_snapshot)


class TestObservabilityCardDataclass(unittest.TestCase):
    """ObservabilityCard 数据类测试"""
    
    def test_to_dict(self):
        """测试转换为字典"""
        card = ObservabilityCard(
            task_id="test_dc_001",
            scenario="custom",
            owner="main",
            executor="subagent",
            stage="dispatch",
            heartbeat=_iso_now(),
        )
        
        data = card.to_dict()
        
        self.assertEqual(data["task_id"], "test_dc_001")
        self.assertEqual(data["card_version"], CARD_VERSION)
        self.assertEqual(data["scenario"], "custom")
        self.assertEqual(data["owner"], "main")
        self.assertEqual(data["executor"], "subagent")
        self.assertEqual(data["stage"], "dispatch")
    
    def test_from_dict(self):
        """测试从字典创建"""
        data = {
            "card_version": CARD_VERSION,
            "task_id": "test_dc_002",
            "scenario": "trading_roundtable",
            "owner": "trading",
            "executor": "tmux",
            "stage": "running",
            "heartbeat": _iso_now(),
            "recent_output": "Test output",
            "metadata": {"custom_key": "custom_value"},
        }
        
        card = ObservabilityCard.from_dict(data)
        
        self.assertEqual(card.task_id, "test_dc_002")
        self.assertEqual(card.scenario, "trading_roundtable")
        self.assertEqual(card.owner, "trading")
        self.assertEqual(card.executor, "tmux")
        self.assertEqual(card.stage, "running")
        self.assertEqual(card.recent_output, "Test output")
        self.assertEqual(card.metadata["custom_key"], "custom_value")


class TestObservabilityCardIntegration(unittest.TestCase):
    """集成测试（使用全局目录）"""
    
    def setUp(self):
        _ensure_dirs()
        self.test_task_ids = []
    
    def tearDown(self):
        for task_id in self.test_task_ids:
            delete_card(task_id)
    
    def test_create_and_get_with_global_functions(self):
        """测试使用便捷函数创建和读取"""
        task_id = "test_global_001"
        self.test_task_ids.append(task_id)
        
        # 创建
        card = create_card(
            task_id=task_id,
            scenario="custom",
            owner="main",
            executor="subagent",
            stage="dispatch",
            promised_eta="2026-03-28T23:59:00",
            anchor_type="session_id",
            anchor_value="cc-global-001",
        )
        
        self.assertIsNotNone(card)
        self.assertEqual(card.task_id, task_id)
        
        # 读取
        retrieved = get_card(task_id)
        
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.task_id, task_id)
    
    def test_update_with_global_functions(self):
        """测试使用便捷函数更新"""
        task_id = "test_global_002"
        self.test_task_ids.append(task_id)
        
        # 创建
        create_card(
            task_id=task_id,
            scenario="custom",
            owner="main",
            executor="subagent",
            stage="dispatch",
            promised_eta="2026-03-28T23:59:00",
            anchor_type="session_id",
            anchor_value="cc-global-002",
        )
        
        # 更新
        updated = update_card(
            task_id=task_id,
            stage="running",
            recent_output="Running...",
        )
        
        self.assertEqual(updated.stage, "running")
        self.assertEqual(updated.recent_output, "Running...")


if __name__ == "__main__":
    unittest.main(verbosity=2)
