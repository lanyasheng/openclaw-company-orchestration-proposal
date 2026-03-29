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

from dashboard import build_dashboard_snapshot, cleanup_demo_cards, get_card_health
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
