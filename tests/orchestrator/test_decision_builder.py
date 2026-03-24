#!/usr/bin/env python3
"""
test_decision_builder.py — Tests for decision_builder module
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ORCHESTRATOR_DIR = REPO_ROOT / "runtime" / "orchestrator"
if str(ORCHESTRATOR_DIR) not in sys.path:
    sys.path.insert(0, str(ORCHESTRATOR_DIR))

from decision_builder import build_decision, _check_empty_result
from orchestrator import Decision


class TestCheckEmptyResult:
    """测试 _check_empty_result 函数"""
    
    def test_empty_packet(self):
        """测试空 packet"""
        result = _check_empty_result({})
        assert result == "packet is empty"
    
    def test_missing_artifact(self):
        """测试缺少 artifact"""
        packet = {
            "artifact": {},
            "report": {"path": "report.md", "exists": True},
            "test": {"commands": ["pytest"], "summary": "passed"},
            "repro": {"commands": ["run"]},
        }
        result = _check_empty_result(packet)
        assert "missing artifact" in result
    
    def test_missing_report(self):
        """测试缺少 report"""
        packet = {
            "artifact": {"path": "artifact.json", "exists": True},
            "report": {},
            "test": {"commands": ["pytest"], "summary": "passed"},
            "repro": {"commands": ["run"]},
        }
        result = _check_empty_result(packet)
        assert "missing report" in result
    
    def test_missing_test(self):
        """测试缺少 test"""
        packet = {
            "artifact": {"path": "artifact.json", "exists": True},
            "report": {"path": "report.md", "exists": True},
            "test": {},
            "repro": {"commands": ["run"]},
        }
        result = _check_empty_result(packet)
        assert "missing test" in result
    
    def test_missing_repro(self):
        """测试缺少 repro"""
        packet = {
            "artifact": {"path": "artifact.json", "exists": True},
            "report": {"path": "report.md", "exists": True},
            "test": {"commands": ["pytest"], "summary": "passed"},
            "repro": {},
        }
        result = _check_empty_result(packet)
        assert "missing repro" in result
    
    def test_complete_packet(self):
        """测试完整 packet"""
        packet = {
            "artifact": {"path": "artifact.json", "exists": True},
            "report": {"path": "report.md", "exists": True},
            "test": {"commands": ["pytest"], "summary": "passed"},
            "repro": {"commands": ["run"]},
        }
        result = _check_empty_result(packet)
        assert result is None


class TestBuildDecision:
    """测试 build_decision 函数"""
    
    def _complete_packet(self, overall_gate: str = "PASS", primary_blocker: str = "none") -> dict:
        """Helper: 创建完整的 packet（通过 validate_packet 验证）"""
        return {
            "packet_version": "trading_phase1_packet_v1",
            "phase_id": "trading_phase1",
            "candidate_id": "test_candidate",
            "run_label": "test_run",
            "input_config_path": "test/config.json",
            "generated_at": "2026-03-24T12:00:00+08:00",
            "owner": "trading",
            "overall_gate": overall_gate,
            "primary_blocker": primary_blocker,
            "artifact": {"path": "a.json", "exists": True},
            "report": {"path": "r.md", "exists": True},
            "commit": {"repo": "test-repo", "git_commit": "abc123"},
            "test": {"commands": ["pytest"], "summary": "passed"},
            "repro": {"commands": ["run"], "notes": "test notes"},
            "tradability": {
                "annual_turnover": 100.0,
                "liquidity_flags": [],
                "gross_return": 0.1,
                "net_return": 0.08,
                "benchmark_return": 0.05,
                "scenario_verdict": "PASS",
                "turnover_failure_reasons": [],
                "liquidity_failure_reasons": [],
                "net_vs_gross_failure_reasons": [],
                "summary": "tradability OK",
            },
        }
    
    def test_build_decision_proceed_on_pass(self):
        """测试 PASS 时构建 proceed decision"""
        payloads = {
            "packet": self._complete_packet("PASS", "none"),
            "roundtable": {
                "conclusion": "PASS",
                "blocker": "none",
                "next_step": "implement feature X",
                "completion_criteria": "tests pass",
                "owner": "trading",
            },
            "supporting_results": [],
        }
        
        decision = build_decision("test_batch", payloads, {"summary": "test"})
        
        assert decision.action == "proceed"
        assert "PASS" in decision.reason
        assert len(decision.next_tasks) > 0
    
    def test_build_decision_fix_blocker_on_conditional(self):
        """测试 CONDITIONAL 时构建 fix_blocker decision"""
        payloads = {
            "packet": self._complete_packet("PASS", "performance_issue"),
            "roundtable": {
                "conclusion": "CONDITIONAL",
                "blocker": "performance_issue",
                "owner": "trading",
                "next_step": "fix performance issue",
                "completion_criteria": "performance tests pass",
            },
            "supporting_results": [],
        }
        
        decision = build_decision("test_batch", payloads, {"summary": "test"})
        
        assert decision.action == "fix_blocker"
        assert "CONDITIONAL" in decision.reason
    
    def test_build_decision_abort_on_fail(self):
        """测试 FAIL 时构建 abort decision"""
        payloads = {
            "packet": self._complete_packet("FAIL", "critical_bug"),
            "roundtable": {
                "conclusion": "FAIL",
                "blocker": "critical_bug",
                "owner": "trading",
                "next_step": "address critical bug",
                "completion_criteria": "bug fixed",
            },
            "supporting_results": [],
        }
        
        decision = build_decision("test_batch", payloads, {"summary": "test"})
        
        assert decision.action == "abort"
        assert "FAIL" in decision.reason
    
    def test_build_decision_blocks_empty_result(self):
        """测试 empty-result 硬拦截"""
        payloads = {
            "packet": {},  # Empty packet
            "roundtable": {
                "conclusion": "PASS",
                "blocker": "none",
            },
            "supporting_results": [],
        }
        
        decision = build_decision("test_batch", payloads, {"summary": "test"})
        
        assert decision.action == "fix_blocker"
        assert "EMPTY_RESULT_BLOCKED" in decision.reason
        assert decision.metadata["packet_validation"]["empty_result_blocked"] is True
    
    def test_build_decision_includes_preflight(self):
        """测试 preflight validation 被包含"""
        payloads = {
            "packet": {
                "artifact": {"path": "a.json", "exists": True},
                "report": {"path": "r.md", "exists": True},
                "test": {"commands": ["pytest"], "summary": "passed"},
                "repro": {"commands": ["run"]},
                "overall_gate": "PASS",
            },
            "roundtable": {
                "conclusion": "PASS",
                "blocker": "none",
            },
            "supporting_results": [],
        }
        
        preflight = {"complete": True, "preflight_status": "passed"}
        decision = build_decision("test_batch", payloads, {"summary": "test"}, preflight_validation=preflight)
        
        assert decision.metadata["packet_validation"]["preflight"] == preflight
    
    def test_build_decision_metadata_contains_all_fields(self):
        """测试 decision metadata 包含所有必需字段"""
        payloads = {
            "packet": {
                "artifact": {"path": "a.json", "exists": True},
                "report": {"path": "r.md", "exists": True},
                "test": {"commands": ["pytest"], "summary": "passed"},
                "repro": {"commands": ["run"]},
                "overall_gate": "PASS",
            },
            "roundtable": {
                "conclusion": "PASS",
                "blocker": "none",
            },
            "supporting_results": [{"task_id": "tsk_001", "verdict": "PASS"}],
        }
        
        decision = build_decision("test_batch", payloads, {"summary": "test"})
        
        assert "adapter" in decision.metadata
        assert "scenario" in decision.metadata
        assert "packet" in decision.metadata
        assert "roundtable" in decision.metadata
        assert "packet_validation" in decision.metadata
        assert "batch_analysis" in decision.metadata
        assert "supporting_results" in decision.metadata
