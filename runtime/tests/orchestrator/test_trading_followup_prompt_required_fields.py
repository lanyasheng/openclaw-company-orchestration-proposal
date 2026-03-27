#!/usr/bin/env python3
"""
test_trading_followup_prompt_required_fields.py — Test Trading Follow-up Prompt Required Fields

验证 trading follow-up prompt 是否包含所有必需字段清单。

这是 P0-3 Batch 11: Trading Callback Packet Completeness Fix 的测试覆盖。
"""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any, Dict

# Add orchestrator to path
ROOT_DIR = Path(__file__).resolve().parents[2]  # runtime/
ORCHESTRATOR_DIR = ROOT_DIR / "orchestrator"

import sys
for path in [str(ORCHESTRATOR_DIR), str(ROOT_DIR)]:
    if path not in sys.path:
        sys.path.insert(0, path)

from adapters.trading import TradingAdapter, ADAPTER_NAME, SCENARIO


class TestTradingFollowupPromptRequiredFields(unittest.TestCase):
    """测试 trading follow-up prompt 包含所有必需字段清单"""
    
    def setUp(self):
        self.adapter = TradingAdapter()
        self.batch_id = "test_batch_001"
        self.decision = {
            "action": "fix_blocker",
            "reason": "phase1 packet incomplete",
            "metadata": {
                "packet": {
                    "candidate_id": "AAPL",
                    "run_label": "test_run",
                    "primary_blocker": "missing_fields",
                },
                "roundtable": {
                    "conclusion": "CONDITIONAL",
                    "blocker": "missing_fields",
                    "owner": "trading",
                    "next_step": "fill missing fields",
                    "completion_criteria": "all required fields present",
                },
                "continuation": {
                    "mode": "packet_freeze",
                    "task_preview": "fill missing packet fields",
                    "next_round_goal": "complete phase1 packet",
                    "review_required": True,
                },
            },
        }
        self.summary_path = Path("/tmp/test-summary.md")
    
    def test_followup_prompt_contains_required_fields_header(self):
        """测试 prompt 包含必需字段标题"""
        prompt = self.adapter.build_followup_prompt(
            batch_id=self.batch_id,
            decision=self.decision,
            summary_path=self.summary_path,
        )
        
        self.assertIn("P0 强制：Callback 时必须填齐的 Phase1 Packet 字段", prompt)
    
    def test_followup_prompt_contains_top_level_fields(self):
        """测试 prompt 包含 top-level packet 字段清单"""
        prompt = self.adapter.build_followup_prompt(
            batch_id=self.batch_id,
            decision=self.decision,
            summary_path=self.summary_path,
        )
        
        # 检查 9 个 top-level 字段
        self.assertIn("### Top-Level Packet Fields (9 个)", prompt)
        self.assertIn("1. `packet_version`", prompt)
        self.assertIn("2. `phase_id`", prompt)
        self.assertIn("3. `candidate_id`", prompt)
        self.assertIn("4. `run_label`", prompt)
        self.assertIn("5. `input_config_path`", prompt)
        self.assertIn("6. `generated_at`", prompt)
        self.assertIn("7. `owner`", prompt)
        self.assertIn("8. `overall_gate`", prompt)
        self.assertIn("9. `primary_blocker`", prompt)
    
    def test_followup_prompt_contains_artifact_truth_fields(self):
        """测试 prompt 包含 artifact truth 字段清单"""
        prompt = self.adapter.build_followup_prompt(
            batch_id=self.batch_id,
            decision=self.decision,
            summary_path=self.summary_path,
        )
        
        # 检查 10 个 artifact truth 字段
        self.assertIn("### Artifact Truth Fields (10 个)", prompt)
        self.assertIn("`artifact.path`", prompt)
        self.assertIn("`artifact.exists`", prompt)
        self.assertIn("`report.path`", prompt)
        self.assertIn("`report.exists`", prompt)
        self.assertIn("`commit.repo`", prompt)
        self.assertIn("`commit.git_commit`", prompt)
        self.assertIn("`test.commands`", prompt)
        self.assertIn("`test.summary`", prompt)
        self.assertIn("`repro.commands`", prompt)
        self.assertIn("`repro.notes`", prompt)
    
    def test_followup_prompt_contains_tradability_fields(self):
        """测试 prompt 包含 tradability 字段清单"""
        prompt = self.adapter.build_followup_prompt(
            batch_id=self.batch_id,
            decision=self.decision,
            summary_path=self.summary_path,
        )
        
        # 检查 10 个 tradability 字段
        self.assertIn("### Tradability Fields (10 个)", prompt)
        self.assertIn("`tradability.annual_turnover`", prompt)
        self.assertIn("`tradability.liquidity_flags`", prompt)
        self.assertIn("`tradability.gross_return`", prompt)
        self.assertIn("`tradability.net_return`", prompt)
        self.assertIn("`tradability.benchmark_return`", prompt)
        self.assertIn("`tradability.scenario_verdict`", prompt)
        self.assertIn("`tradability.turnover_failure_reasons`", prompt)
        self.assertIn("`tradability.liquidity_failure_reasons`", prompt)
        self.assertIn("`tradability.net_vs_gross_failure_reasons`", prompt)
        self.assertIn("`tradability.summary`", prompt)
    
    def test_followup_prompt_contains_roundtable_fields(self):
        """测试 prompt 包含 roundtable closure 字段清单"""
        prompt = self.adapter.build_followup_prompt(
            batch_id=self.batch_id,
            decision=self.decision,
            summary_path=self.summary_path,
        )
        
        # 检查 5 个 roundtable 字段
        self.assertIn("### Roundtable Closure Fields (5 个)", prompt)
        self.assertIn("`roundtable.conclusion`", prompt)
        self.assertIn("`roundtable.blocker`", prompt)
        self.assertIn("`roundtable.owner`", prompt)
        self.assertIn("`roundtable.next_step`", prompt)
        self.assertIn("`roundtable.completion_criteria`", prompt)
    
    def test_followup_prompt_contains_validation_reminder(self):
        """测试 prompt 包含验证提醒"""
        prompt = self.adapter.build_followup_prompt(
            batch_id=self.batch_id,
            decision=self.decision,
            summary_path=self.summary_path,
        )
        
        self.assertIn("validate_packet", prompt)
        self.assertIn("complete=True", prompt)
    
    def test_followup_prompt_field_count(self):
        """测试 prompt 列出 34 个必需字段"""
        prompt = self.adapter.build_followup_prompt(
            batch_id=self.batch_id,
            decision=self.decision,
            summary_path=self.summary_path,
        )
        
        # 检查字段编号（1-34）
        for i in range(1, 35):
            self.assertIn(f"{i}.", prompt, f"Missing field number {i}")
    
    def test_followup_prompt_emphasizes_repro_notes(self):
        """测试 prompt 强调 repro.notes 不得留空"""
        prompt = self.adapter.build_followup_prompt(
            batch_id=self.batch_id,
            decision=self.decision,
            summary_path=self.summary_path,
        )
        
        self.assertIn("`repro.notes`: 复现说明（**不得留空**）", prompt)
    
    def test_followup_prompt_emphasizes_tradability_summary(self):
        """测试 prompt 强调 tradability.summary 不得留空"""
        prompt = self.adapter.build_followup_prompt(
            batch_id=self.batch_id,
            decision=self.decision,
            summary_path=self.summary_path,
        )
        
        self.assertIn("`tradability.summary`: tradability 摘要（**不得留空**）", prompt)


if __name__ == "__main__":
    unittest.main()
