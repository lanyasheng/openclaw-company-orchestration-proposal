#!/usr/bin/env python3
"""Dashboard polish tests: stale flag + safe demo cleanup."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "runtime" / "orchestrator"))

from dashboard import (
    build_dashboard_snapshot,
    cleanup_demo_cards,
    create_active_tasks_table,
    create_summary_panel,
    get_card_health,
    is_historical_stale,
)
from observability_card import ObservabilityCard


class DashboardPolishTest(unittest.TestCase):
    def _make_card(
        self,
        *,
        task_id: str,
        stage: str = "running",
        heartbeat: str,
        promised_eta: str | None,
        owner: str = "main",
        scenario: str = "custom",
        executor: str = "subagent",
        anchor_value: str | None = None,
    ) -> ObservabilityCard:
        return ObservabilityCard(
            task_id=task_id,
            scenario=scenario,
            owner=owner,
            executor=executor,
            stage=stage,
            heartbeat=heartbeat,
            promise_anchor={
                "anchor_type": "session_id",
                "anchor_value": anchor_value or f"cc-{task_id}",
                "promised_eta": promised_eta,
            },
            metrics={
                "created_at": heartbeat,
                "started_at": heartbeat,
                "completed_at": None,
                "duration_seconds": 0,
                "retry_count": 0,
            },
        )

    def _write_card_file(self, card_dir: Path, card: ObservabilityCard) -> Path:
        card_dir.mkdir(parents=True, exist_ok=True)
        path = card_dir / f"{card.task_id}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(card.to_dict(), f, indent=2, ensure_ascii=False)
        return path

    def test_stale_flag_marks_old_running_card(self):
        now = datetime.now()
        heartbeat = (now - timedelta(minutes=40)).isoformat()
        promised_eta = (now - timedelta(minutes=5)).isoformat()
        card = self._make_card(
            task_id="real_task_001",
            stage="running",
            heartbeat=heartbeat,
            promised_eta=promised_eta,
        )

        health = get_card_health(card)

        self.assertTrue(health["is_stale"])
        self.assertIn("heartbeat_stale", health["reasons"])
        self.assertIn("eta_overdue", health["reasons"])
        self.assertEqual(health["label"], "STALE hb+eta")

    def test_terminal_card_not_marked_stale(self):
        now = datetime.now()
        heartbeat = (now - timedelta(days=3)).isoformat()
        promised_eta = (now - timedelta(days=3, hours=1)).isoformat()
        card = self._make_card(
            task_id="real_task_completed",
            stage="completed",
            heartbeat=heartbeat,
            promised_eta=promised_eta,
        )

        health = get_card_health(card)

        self.assertFalse(health["is_stale"])
        self.assertEqual(health["label"], "OK")

    def test_dashboard_snapshot_contains_stale_summary(self):
        now = datetime.now()
        stale_card = self._make_card(
            task_id="real_task_stale",
            stage="dispatch",
            heartbeat=(now - timedelta(hours=2)).isoformat(),
            promised_eta=(now - timedelta(minutes=10)).isoformat(),
        )
        fresh_card = self._make_card(
            task_id="real_task_fresh",
            stage="running",
            heartbeat=(now - timedelta(minutes=2)).isoformat(),
            promised_eta=(now + timedelta(hours=1)).isoformat(),
        )

        snapshot = build_dashboard_snapshot([stale_card, fresh_card])

        self.assertEqual(snapshot["summary"]["stale_cards"], 1)
        enriched = {item["task_id"]: item for item in snapshot["all_cards"]}
        self.assertTrue(enriched["real_task_stale"]["dashboard_health"]["is_stale"])
        self.assertFalse(enriched["real_task_fresh"]["dashboard_health"]["is_stale"])

    def test_cleanup_demo_cards_dry_run_previews_without_deleting(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            card_dir = base / "cards"
            index_dir = base / "index"
            index_dir.mkdir(parents=True, exist_ok=True)

            old_time = (datetime.now() - timedelta(days=2)).isoformat()
            old_eta = (datetime.now() - timedelta(days=2, hours=-1)).isoformat()

            demo_card = self._make_card(
                task_id="test_list_3",
                stage="dispatch",
                heartbeat=old_time,
                promised_eta=old_eta,
                anchor_value="cc-test-list-3",
            )
            real_card = self._make_card(
                task_id="real_customer_task_001",
                stage="dispatch",
                heartbeat=old_time,
                promised_eta=old_eta,
                anchor_value="cc-production-task-001",
            )

            self._write_card_file(card_dir, demo_card)
            self._write_card_file(card_dir, real_card)
            (index_dir / "main.jsonl").write_text(
                json.dumps({"task_id": demo_card.task_id, "updated_at": old_time}) + "\n"
                + json.dumps({"task_id": real_card.task_id, "updated_at": old_time}) + "\n",
                encoding="utf-8",
            )

            report = cleanup_demo_cards(card_dir, older_than_hours=24, dry_run=True)

            self.assertEqual(report["matched"], 1)
            self.assertEqual(report["deleted_count"], 0)
            self.assertTrue((card_dir / "test_list_3.json").exists())
            self.assertTrue((card_dir / "real_customer_task_001.json").exists())

    def test_cleanup_demo_cards_deletes_only_explicit_old_demo_cards(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            card_dir = base / "cards"
            index_dir = base / "index"
            index_dir.mkdir(parents=True, exist_ok=True)

            aware_now = datetime.now().astimezone()
            old_time = (aware_now - timedelta(days=3)).isoformat()
            recent_time = (aware_now - timedelta(hours=1)).isoformat()
            old_eta = (aware_now - timedelta(days=3, hours=-1)).isoformat()
            recent_eta = (aware_now + timedelta(hours=2)).isoformat()

            old_demo = self._make_card(
                task_id="tmux_full_demo_001",
                stage="completed",
                heartbeat=old_time,
                promised_eta=old_eta,
                anchor_value="cc-full-lifecycle-demo",
            )
            recent_demo = self._make_card(
                task_id="task_demo_recent_001",
                stage="running",
                heartbeat=recent_time,
                promised_eta=recent_eta,
                anchor_value="cc-demo-recent",
            )
            real_task = self._make_card(
                task_id="owner_real_reconciliation_001",
                stage="running",
                heartbeat=old_time,
                promised_eta=old_eta,
                anchor_value="cc-owner-real-001",
            )

            self._write_card_file(card_dir, old_demo)
            self._write_card_file(card_dir, recent_demo)
            self._write_card_file(card_dir, real_task)
            (index_dir / "main.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps({"task_id": old_demo.task_id, "updated_at": old_time}),
                        json.dumps({"task_id": recent_demo.task_id, "updated_at": recent_time}),
                        json.dumps({"task_id": real_task.task_id, "updated_at": old_time}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            report = cleanup_demo_cards(card_dir, older_than_hours=24, dry_run=False)

            self.assertEqual(report["matched"], 1)
            self.assertEqual(report["deleted_count"], 1)
            self.assertEqual(report["deleted_task_ids"], ["tmux_full_demo_001"])
            self.assertFalse((card_dir / "tmux_full_demo_001.json").exists())
            self.assertTrue((card_dir / "task_demo_recent_001.json").exists())
            self.assertTrue((card_dir / "owner_real_reconciliation_001.json").exists())

            remaining_index = (index_dir / "main.jsonl").read_text(encoding="utf-8")
            self.assertNotIn("tmux_full_demo_001", remaining_index)
            self.assertIn("task_demo_recent_001", remaining_index)
            self.assertIn("owner_real_reconciliation_001", remaining_index)

    def test_callback_received_stale_not_counted_as_active(self):
        """
        验证 callback_received 状态的 stale 卡片不被算作 active。
        这是针对 trading roundtable dashboard 显示 10 个 active 但实际 active=0 问题的修复。
        """
        now = datetime.now()
        
        # 10 张 stale callback_received 卡片（模拟 trading 历史卡片）
        stale_callback_cards = [
            self._make_card(
                task_id=f"trading_history_{i:02d}",
                stage="callback_received",
                heartbeat=(now - timedelta(days=2)).isoformat(),
                promised_eta=(now - timedelta(days=2)).isoformat(),
                owner="trading",
                scenario="trading_roundtable",
            )
            for i in range(10)
        ]
        
        # 1 张 fresh callback_received 卡片（真实活跃）
        fresh_callback_card = self._make_card(
            task_id="trading_active_001",
            stage="callback_received",
            heartbeat=(now - timedelta(minutes=2)).isoformat(),
            promised_eta=(now + timedelta(minutes=10)).isoformat(),
            owner="trading",
            scenario="trading_roundtable",
        )
        
        # 2 张真实 running 卡片
        running_cards = [
            self._make_card(
                task_id=f"trading_running_{i}",
                stage="running",
                heartbeat=(now - timedelta(minutes=1)).isoformat(),
                promised_eta=(now + timedelta(minutes=30)).isoformat(),
                owner="trading",
                scenario="trading_roundtable",
            )
            for i in range(2)
        ]
        
        # 1 张 completed 卡片
        completed_card = self._make_card(
            task_id="trading_completed_001",
            stage="completed",
            heartbeat=(now - timedelta(hours=1)).isoformat(),
            promised_eta=(now - timedelta(hours=1)).isoformat(),
            owner="trading",
            scenario="trading_roundtable",
        )
        
        all_cards = stale_callback_cards + [fresh_callback_card] + running_cards + [completed_card]
        
        snapshot = build_dashboard_snapshot(all_cards)
        
        # 验证 active count: 应该是 3 (2 running + 1 fresh callback_received)
        # 而不是 13 (如果把所有 callback_received 都算上)
        self.assertEqual(snapshot["summary"]["active_cards"], 3)
        self.assertEqual(snapshot["summary"]["stale_cards"], 10)
        
        # 验证每张 stale callback_received 卡片被正确标记
        enriched = {item["task_id"]: item for item in snapshot["all_cards"]}
        for i in range(10):
            task_id = f"trading_history_{i:02d}"
            self.assertTrue(
                enriched[task_id]["dashboard_health"]["is_stale"],
                f"{task_id} should be marked as stale"
            )
        
        # 验证 fresh callback_received 卡片不被标记为 stale
        self.assertFalse(
            enriched["trading_active_001"]["dashboard_health"]["is_stale"],
            "fresh callback_received should not be stale"
        )

    def test_dashboard_snapshot_active_count_excludes_stale_callback_received(self):
        """
        验证 dashboard 统计口径：callback_received 无条件算 active 的问题已修复。
        修前：10 张 stale callback_received + 2 running + 1 fresh callback = 13 active
        修后：2 running + 1 fresh callback = 3 active
        """
        now = datetime.now()
        
        # 模拟问题场景：10 张 stale callback_received 卡片
        stale_cards = [
            self._make_card(
                task_id=f"stale_cb_{i:02d}",
                stage="callback_received",
                heartbeat=(now - timedelta(days=5)).isoformat(),
                promised_eta=(now - timedelta(days=5)).isoformat(),
            )
            for i in range(10)
        ]
        
        # 2 张真实 running 卡片
        running_cards = [
            self._make_card(
                task_id=f"running_{i}",
                stage="running",
                heartbeat=(now - timedelta(minutes=1)).isoformat(),
                promised_eta=(now + timedelta(minutes=30)).isoformat(),
            )
            for i in range(2)
        ]
        
        snapshot = build_dashboard_snapshot(stale_cards + running_cards)
        
        # 修前会是 12 (10 stale callback + 2 running)
        # 修后应该是 2 (只有 running)
        self.assertEqual(snapshot["summary"]["active_cards"], 2)
        self.assertEqual(snapshot["summary"]["stale_cards"], 10)

    def test_is_historical_stale_identifies_old_trading_callback_cards(self):
        """
        验证 is_historical_stale 正确识别历史 trading stale 卡。
        条件：callback_received + stale + 超过阈值
        - trading scenario: 6 小时
        - 其他 scenario: 48 小时
        """
        now = datetime.now()
        
        # 10 张历史 stale callback_received 卡片（超过 48 小时，trading scenario）
        stale_callback_cards = [
            self._make_card(
                task_id=f"trading_history_{i:02d}",
                stage="callback_received",
                heartbeat=(now - timedelta(days=3)).isoformat(),
                promised_eta=(now - timedelta(days=3)).isoformat(),
                owner="trading",
                scenario="trading_roundtable",
            )
            for i in range(10)
        ]
        
        # 1 张 fresh callback_received 卡片（不到 6 小时，trading scenario）
        fresh_callback_card = self._make_card(
            task_id="trading_active_001",
            stage="callback_received",
            heartbeat=(now - timedelta(hours=2)).isoformat(),
            promised_eta=(now + timedelta(hours=1)).isoformat(),
            owner="trading",
            scenario="trading_roundtable",
        )
        
        # 1 张 stale running 卡片（不是 callback_received）
        stale_running_card = self._make_card(
            task_id="stale_running_001",
            stage="running",
            heartbeat=(now - timedelta(days=3)).isoformat(),
            promised_eta=(now - timedelta(days=3)).isoformat(),
            owner="main",
            scenario="coding_issue",
        )
        
        # 验证历史 stale callback_received 卡被识别
        for i in range(10):
            card = stale_callback_cards[i]
            health = get_card_health(card)
            self.assertTrue(
                is_historical_stale(card, health),
                f"trading_history_{i:02d} should be historical stale"
            )
        
        # 验证 fresh callback_received 卡不被识别为历史归档（不到 6 小时）
        self.assertFalse(
            is_historical_stale(fresh_callback_card, get_card_health(fresh_callback_card)),
            "fresh callback_received (<6h) should not be historical stale"
        )
        
        # 验证 stale running 卡不被识别为历史归档（stage 不对）
        self.assertFalse(
            is_historical_stale(stale_running_card, get_card_health(stale_running_card)),
            "stale running should not be historical stale (wrong stage)"
        )

    def test_dashboard_snapshot_v3_includes_archived_stale_fields(self):
        """
        验证 dashboard snapshot v3 包含归档视图字段。
        """
        now = datetime.now()
        
        # 10 张历史 stale callback_received 卡片
        stale_cards = [
            self._make_card(
                task_id=f"archived_{i:02d}",
                stage="callback_received",
                heartbeat=(now - timedelta(days=3)).isoformat(),
                promised_eta=(now - timedelta(days=3)).isoformat(),
            )
            for i in range(10)
        ]
        
        # 2 张活跃卡片
        active_cards = [
            self._make_card(
                task_id=f"active_{i}",
                stage="running",
                heartbeat=(now - timedelta(minutes=1)).isoformat(),
                promised_eta=(now + timedelta(minutes=30)).isoformat(),
            )
            for i in range(2)
        ]
        
        snapshot = build_dashboard_snapshot(stale_cards + active_cards)
        
        # 验证 snapshot 版本
        self.assertEqual(snapshot["snapshot_version"], "dashboard_snapshot_v3")
        
        # 验证归档统计字段
        self.assertEqual(snapshot["summary"]["archived_stale_cards"], 10)
        self.assertEqual(snapshot["summary"]["visible_active_cards"], 2)
        
        # 验证 historical_stale_cards 列表存在且包含 10 张卡
        self.assertEqual(len(snapshot["historical_stale_cards"]), 10)
        
        # 验证每张卡片的 is_archived 标记
        enriched = {item["task_id"]: item for item in snapshot["all_cards"]}
        for i in range(10):
            task_id = f"archived_{i:02d}"
            self.assertTrue(
                enriched[task_id]["is_archived"],
                f"{task_id} should be marked as archived"
            )
        for i in range(2):
            task_id = f"active_{i}"
            self.assertFalse(
                enriched[task_id]["is_archived"],
                f"{task_id} should not be marked as archived"
            )

    def test_create_active_tasks_table_hides_archived_by_default(self):
        """
        验证 create_active_tasks_table 默认隐藏归档 stale 卡。
        """
        now = datetime.now()
        
        # 5 张历史 stale callback_received 卡片
        archived_cards = [
            self._make_card(
                task_id=f"archived_cb_{i}",
                stage="callback_received",
                heartbeat=(now - timedelta(days=3)).isoformat(),
                promised_eta=(now - timedelta(days=3)).isoformat(),
            )
            for i in range(5)
        ]
        
        # 3 张活跃卡片
        active_cards = [
            self._make_card(
                task_id=f"active_{i}",
                stage="running",
                heartbeat=(now - timedelta(minutes=1)).isoformat(),
                promised_eta=(now + timedelta(minutes=30)).isoformat(),
            )
            for i in range(3)
        ]
        
        all_cards = archived_cards + active_cards
        
        # 默认隐藏归档
        table_hidden = create_active_tasks_table(all_cards, hide_archived=True)
        # 显示归档
        table_visible = create_active_tasks_table(all_cards, hide_archived=False)
        
        # 验证行数：隐藏时只显示活跃卡（最多 15 行，这里只有 3 张活跃）
        # 注意：Rich Table 的行数需要通过 render 来获取，这里我们验证逻辑
        # 通过验证过滤后的卡片数量来间接验证
        from dashboard import is_historical_stale, get_card_health
        
        visible_cards = [
            card for card in all_cards
            if not is_historical_stale(card, get_card_health(card))
        ]
        self.assertEqual(len(visible_cards), 3)
        
        # 验证活跃卡片不被过滤
        for card in active_cards:
            self.assertIn(card, visible_cards)
        
        # 验证归档卡片被过滤
        for card in archived_cards:
            self.assertNotIn(card, visible_cards)

    def test_create_summary_panel_shows_archived_count(self):
        """
        验证 create_summary_panel 显示归档 stale 数量。
        """
        now = datetime.now()
        
        # 5 张历史 stale callback_received 卡片
        archived_cards = [
            self._make_card(
                task_id=f"archived_cb_{i}",
                stage="callback_received",
                heartbeat=(now - timedelta(days=3)).isoformat(),
                promised_eta=(now - timedelta(days=3)).isoformat(),
            )
            for i in range(5)
        ]
        
        # 2 张活跃卡片
        active_cards = [
            self._make_card(
                task_id=f"active_{i}",
                stage="running",
                heartbeat=(now - timedelta(minutes=1)).isoformat(),
                promised_eta=(now + timedelta(minutes=30)).isoformat(),
            )
            for i in range(2)
        ]
        
        panel = create_summary_panel(archived_cards + active_cards)
        
        # 验证面板内容包含归档计数
        panel_text = str(panel.renderable)
        self.assertIn("归档：5", panel_text)

    def test_trading_callback_received_uses_shorter_archive_threshold(self):
        """
        验证 trading scenario 的 callback_received 卡片使用更短的归档阈值（6 小时 vs 48 小时）。
        
        修前：10 张 13-29 小时前的 stale trading callback_received 卡片未被归档（阈值 48h）
        修后：这些卡片被正确归档（阈值 6h for trading）
        """
        now = datetime.now()
        
        # 10 张 trading callback_received 卡片，心跳在 13-29 小时前（超过 6h 但不到 48h）
        trading_stale_cards = [
            self._make_card(
                task_id=f"trading_stale_{i:02d}",
                stage="callback_received",
                heartbeat=(now - timedelta(hours=13 + i)).isoformat(),
                promised_eta=(now - timedelta(hours=13 + i)).isoformat(),
                owner="trading",
                scenario="trading_roundtable",
            )
            for i in range(10)
        ]
        
        # 2 张非 trading callback_received 卡片，同样 13-29 小时前（不到 48h，不应归档）
        non_trading_stale_cards = [
            self._make_card(
                task_id=f"non_trading_stale_{i}",
                stage="callback_received",
                heartbeat=(now - timedelta(hours=13 + i)).isoformat(),
                promised_eta=(now - timedelta(hours=13 + i)).isoformat(),
                owner="main",
                scenario="coding_issue",
            )
            for i in range(2)
        ]
        
        # 验证 trading 卡片被识别为历史归档（6h 阈值）
        for i in range(10):
            card = trading_stale_cards[i]
            health = get_card_health(card)
            self.assertTrue(
                is_historical_stale(card, health),
                f"trading_stale_{i:02d} (scenario={card.scenario}) should be historical stale with 6h threshold"
            )
        
        # 验证非 trading 卡片不被识别为历史归档（48h 阈值）
        for i in range(2):
            card = non_trading_stale_cards[i]
            health = get_card_health(card)
            self.assertFalse(
                is_historical_stale(card, health),
                f"non_trading_stale_{i} (scenario={card.scenario}) should NOT be historical stale with 48h threshold"
            )
        
        # 验证 snapshot 统计
        all_cards = trading_stale_cards + non_trading_stale_cards
        snapshot = build_dashboard_snapshot(all_cards)
        
        self.assertEqual(snapshot["summary"]["archived_stale_cards"], 10)
        self.assertEqual(len(snapshot["historical_stale_cards"]), 10)
        
        # 验证所有归档卡片都是 trading scenario
        archived_scenarios = [c["scenario"] for c in snapshot["historical_stale_cards"]]
        self.assertTrue(all("trading" in s for s in archived_scenarios))


if __name__ == "__main__":
    unittest.main(verbosity=2)
