#!/usr/bin/env python3
"""
test_callback_bridge_strict_validation.py — C2 Callback Bridge Strict Validation Tests

测试 callback bridge 的强校验逻辑：
1. empty-result（无 artifact/report/test summary）时硬拦截
2. 缺关键 packet/roundtable 字段时，不允许 completed/PASS 混过去
3. 合法 callback 仍通过

这是 C2 batch callback standard 的测试覆盖。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch, MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "runtime" / "scripts"
ORCHESTRATOR_DIR = REPO_ROOT / "runtime" / "orchestrator"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
if str(ORCHESTRATOR_DIR) not in sys.path:
    sys.path.insert(0, str(ORCHESTRATOR_DIR))

from state_machine import create_task, get_state, STATE_DIR  # type: ignore
from adapters.trading import TradingAdapter  # type: ignore
from trading_roundtable import process_trading_roundtable_callback  # type: ignore


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """隔离的测试环境 - 同时隔离 state 和 closeout 目录
    
    使用 autouse=True 确保每个测试都自动使用隔离环境。
    """
    state_dir = tmp_path / "shared-context" / "job-status"
    closeout_dir = tmp_path / "closeouts"
    closeout_dir.mkdir(parents=True, exist_ok=True)
    
    monkeypatch.setenv("OPENCLAW_STATE_DIR", str(state_dir))
    monkeypatch.setenv("OPENCLAW_CLOSEOUT_DIR", str(closeout_dir))
    monkeypatch.setenv("OPENCLAW_ACK_GUARD_DISABLE_DELIVERY", "1")
    
    # 重新加载模块以使用新的环境变量
    import importlib
    
    # 先更新 closeout_tracker.CLOSEOUT_DIR（如果已加载）
    if "closeout_tracker" in sys.modules:
        import closeout_tracker  # type: ignore
        closeout_tracker.CLOSEOUT_DIR = closeout_dir
    
    # 重新加载关键模块
    for module_name in ["state_machine", "batch_aggregator", "orchestrator", "trading_roundtable", "adapters.trading", "closeout_tracker"]:
        if module_name in sys.modules:
            try:
                importlib.reload(sys.modules[module_name])
            except Exception:
                pass
    
    # 再次确保 CLOSEOUT_DIR 正确设置（reload 后）
    if "closeout_tracker" in sys.modules:
        import closeout_tracker  # type: ignore
        closeout_tracker.CLOSEOUT_DIR = closeout_dir
    
    yield {
        "state_dir": state_dir,
        "closeout_dir": closeout_dir,
    }


def _clean_packet() -> Dict[str, Any]:
    """返回完整的 clean packet"""
    return {
        "packet_version": "trading_phase1_packet_v1",
        "phase_id": "trading_phase1",
        "candidate_id": "rs_canonical_e2e_demo",
        "run_label": "run_2026_03_20",
        "input_config_path": "workspace-trading/research/v2_portfolio/basket_configs/rs_canonical_e2e_demo.json",
        "generated_at": "2026-03-20T18:00:00+08:00",
        "owner": "trading",
        "overall_gate": "PASS",
        "primary_blocker": "none",
        "artifact": {
            "path": "workspace-trading/artifacts/acceptance/2026-03-20/acceptance_harness.json",
            "exists": True,
        },
        "report": {
            "path": "workspace-trading/reports/acceptance/2026-03-20/acceptance_harness.md",
            "exists": True,
        },
        "commit": {
            "repo": "workspace-trading",
            "git_commit": "3ea9378",
        },
        "test": {
            "commands": ["python3 -m pytest tests/v2_portfolio/test_acceptance_harness.py -q"],
            "summary": "36 passed in 0.41s",
        },
        "repro": {
            "commands": ["python3 research/run_acceptance_harness.py"],
            "notes": "requires canonical config",
        },
        "tradability": {
            "annual_turnover": 1.82,
            "liquidity_flags": [],
            "gross_return": 0.21,
            "net_return": 0.19,
            "benchmark_return": 0.05,
            "scenario_verdict": "PASS",
            "turnover_failure_reasons": [],
            "liquidity_failure_reasons": [],
            "net_vs_gross_failure_reasons": [],
            "summary": "clean pass candidate",
        },
    }


def _clean_roundtable() -> Dict[str, Any]:
    """返回完整的 clean roundtable"""
    return {
        "conclusion": "PASS",
        "blocker": "none",
        "owner": "trading",
        "next_step": "freeze intake and open the next minimal wiring task",
        "completion_criteria": "phase1 packet v1 exists with artifact/report/commit/test/repro truth paths",
    }


def _empty_result() -> Dict[str, Any]:
    """返回 empty result（无 artifact/report/test summary）"""
    return {
        "verdict": "PASS",
        "trading_roundtable": {
            "packet": {},
            "roundtable": {},
        },
    }


def _result_missing_artifact_truth() -> Dict[str, Any]:
    """返回缺失 artifact truth 的 result"""
    packet = _clean_packet()
    # 移除 artifact truth 字段
    del packet["artifact"]
    del packet["report"]
    del packet["test"]
    
    return {
        "verdict": "PASS",
        "trading_roundtable": {
            "packet": packet,
            "roundtable": _clean_roundtable(),
        },
    }


def _result_missing_packet_fields() -> Dict[str, Any]:
    """返回缺失 packet 关键字段的 result"""
    packet = _clean_packet()
    # 移除关键字段
    del packet["candidate_id"]
    del packet["overall_gate"]
    
    return {
        "verdict": "PASS",
        "trading_roundtable": {
            "packet": packet,
            "roundtable": _clean_roundtable(),
        },
    }


def _result_missing_roundtable_fields() -> Dict[str, Any]:
    """返回缺失 roundtable 关键字段的 result"""
    roundtable = _clean_roundtable()
    # 移除关键字段
    del roundtable["conclusion"]
    del roundtable["blocker"]
    
    return {
        "verdict": "PASS",
        "trading_roundtable": {
            "packet": _clean_packet(),
            "roundtable": roundtable,
        },
    }


def _clean_result() -> Dict[str, Any]:
    """返回完整合法的 result"""
    return {
        "verdict": "PASS",
        "trading_roundtable": {
            "packet": _clean_packet(),
            "roundtable": _clean_roundtable(),
        },
    }


class TestCallbackBridgeStrictValidation:
    """C2 Callback Bridge Strict Validation 测试"""
    
    def test_empty_result_blocked(self, isolated_environment):
        """测试：empty-result 被硬拦截"""
        batch_id = "batch_empty_result_blocked"
        task_id = "tsk_empty_result_001"
        create_task(task_id, batch_id=batch_id)
        
        result = process_trading_roundtable_callback(
            batch_id=batch_id,
            task_id=task_id,
            result=_empty_result(),
        )
        
        # 验证 empty-result 被拦截
        assert "preflight_validation" in result
        assert result["preflight_validation"]["preflight_status"] == "incomplete"
        assert result["preflight_validation"]["preflight_complete"] is False
        
        # 验证 dispatch plan 被跳过（不是 triggered）
        assert "dispatch_plan" in result
        assert result["dispatch_plan"]["status"] == "skipped"
        
        # 验证 skip reasons 包含 empty result 相关的原因
        skip_reasons = result["dispatch_plan"].get("skip_reasons", [])
        skip_codes = [sr.get("code", "") for sr in skip_reasons]
        assert "empty_result_blocked" in skip_codes
    
    def test_missing_artifact_truth_blocked(self, isolated_environment):
        """测试：缺失 artifact truth 被硬拦截"""
        batch_id = "batch_missing_artifact_truth"
        task_id = "tsk_missing_artifact_001"
        create_task(task_id, batch_id=batch_id)
        
        result = process_trading_roundtable_callback(
            batch_id=batch_id,
            task_id=task_id,
            result=_result_missing_artifact_truth(),
        )
        
        # 验证 artifact truth 缺失被检测
        assert "dispatch_plan" in result
        assert result["dispatch_plan"]["status"] == "skipped"
        
        # 验证 skip reasons
        skip_reasons = result["dispatch_plan"].get("skip_reasons", [])
        skip_codes = [sr.get("code", "") for sr in skip_reasons]
        # 缺失 artifact truth 被检测为 empty result
        assert "empty_result_blocked" in skip_codes
    
    def test_missing_packet_fields_blocked(self, isolated_environment):
        """测试：缺失 packet 关键字段被硬拦截"""
        batch_id = "batch_missing_packet_fields"
        task_id = "tsk_missing_packet_001"
        create_task(task_id, batch_id=batch_id)
        
        result = process_trading_roundtable_callback(
            batch_id=batch_id,
            task_id=task_id,
            result=_result_missing_packet_fields(),
        )
        
        # 验证 packet 字段缺失被检测
        assert "preflight_validation" in result
        assert result["preflight_validation"]["preflight_status"] == "incomplete"
        assert "candidate_id" in result["preflight_validation"]["preflight_missing_fields"]
        assert "overall_gate" in result["preflight_validation"]["preflight_missing_fields"]
        
        # 验证 dispatch plan 被跳过
        assert "dispatch_plan" in result
        assert result["dispatch_plan"]["status"] == "skipped"
    
    def test_missing_roundtable_fields_blocked(self, isolated_environment):
        """测试：缺失 roundtable 关键字段被硬拦截"""
        batch_id = "batch_missing_roundtable_fields"
        task_id = "tsk_missing_roundtable_001"
        create_task(task_id, batch_id=batch_id)
        
        result = process_trading_roundtable_callback(
            batch_id=batch_id,
            task_id=task_id,
            result=_result_missing_roundtable_fields(),
        )
        
        # 验证 roundtable 字段缺失被检测
        assert "preflight_validation" in result
        assert result["preflight_validation"]["preflight_status"] == "incomplete"
        assert "conclusion" in result["preflight_validation"]["preflight_missing_fields"]
        assert "blocker" in result["preflight_validation"]["preflight_missing_fields"]
        
        # 验证 dispatch plan 被跳过
        assert "dispatch_plan" in result
        assert result["dispatch_plan"]["status"] == "skipped"
    
    def test_clean_callback_passes(self, isolated_environment):
        """测试：合法 callback 仍通过"""
        batch_id = "batch_clean_callback_passes"
        task_id = "tsk_clean_callback_001"
        create_task(task_id, batch_id=batch_id)
        
        result = process_trading_roundtable_callback(
            batch_id=batch_id,
            task_id=task_id,
            result=_clean_result(),
            requester_session_key="agent:main:discord:channel:123456789",
        )
        
        # 验证 preflight validation 通过
        assert "preflight_validation" in result
        assert result["preflight_validation"]["preflight_status"] == "pass"
        assert result["preflight_validation"]["preflight_complete"] is True
        
        # 验证 dispatch plan 被触发（假设 auto-dispatch 条件满足）
        assert "dispatch_plan" in result
        # 注意：即使 validation 通过，dispatch plan 也可能因为其他原因被跳过
        # （如 allow_auto_dispatch=False），所以这里只验证 processing 成功
        assert result["status"] == "processed"
        
        # 验证关键产物存在
        assert "summary_path" in result
        assert "decision_path" in result
        assert "dispatch_path" in result
        
        # 验证 summary 文件已写入
        summary_path = Path(result["summary_path"])
        assert summary_path.exists()
    
    def test_blocked_status_not_hard_fail(self, isolated_environment):
        """测试：blocked 状态不是硬 FAIL，尊重 blocked/conditional 语义"""
        batch_id = "batch_blocked_not_fail"
        task_id = "tsk_blocked_not_fail_001"
        create_task(task_id, batch_id=batch_id)
        
        # 构建 CONDITIONAL 结论的 result
        packet = _clean_packet()
        packet["overall_gate"] = "CONDITIONAL"
        roundtable = _clean_roundtable()
        roundtable["conclusion"] = "CONDITIONAL"
        roundtable["blocker"] = "tradability"
        
        result = process_trading_roundtable_callback(
            batch_id=batch_id,
            task_id=task_id,
            result={
                "verdict": "CONDITIONAL",
                "trading_roundtable": {
                    "packet": packet,
                    "roundtable": roundtable,
                },
            },
        )
        
        # 验证 CONDITIONAL 被正确处理（不是硬 FAIL）
        assert "dispatch_plan" in result
        # CONDITIONAL 应该被跳过，但状态是 blocked 而不是 failed
        assert result["dispatch_plan"]["status"] == "skipped"
        
        # 验证 decision action 是 fix_blocker 而不是 abort
        decision_path = Path(result["decision_path"])
        decision = json.loads(decision_path.read_text())
        assert decision["action"] == "fix_blocker"


class TestCallbackValidationEdgeCases:
    """边界情况测试"""
    
    def test_partial_artifact_truth_blocked(self, isolated_environment):
        """测试：部分 artifact truth 缺失被拦截"""
        batch_id = "batch_partial_artifact"
        task_id = "tsk_partial_artifact_001"
        create_task(task_id, batch_id=batch_id)
        
        packet = _clean_packet()
        # 只移除 report，保留 artifact
        del packet["report"]
        
        result = process_trading_roundtable_callback(
            batch_id=batch_id,
            task_id=task_id,
            result={
                "verdict": "PASS",
                "trading_roundtable": {
                    "packet": packet,
                    "roundtable": _clean_roundtable(),
                },
            },
        )
        
        # 验证不完整 artifact truth 被检测
        assert "dispatch_plan" in result
        assert result["dispatch_plan"]["status"] == "skipped"
    
    def test_exists_false_blocked(self, isolated_environment):
        """测试：artifact exists=false 被拦截"""
        batch_id = "batch_exists_false"
        task_id = "tsk_exists_false_001"
        create_task(task_id, batch_id=batch_id)
        
        packet = _clean_packet()
        packet["artifact"]["exists"] = False
        packet["report"]["exists"] = False
        
        result = process_trading_roundtable_callback(
            batch_id=batch_id,
            task_id=task_id,
            result={
                "verdict": "PASS",
                "trading_roundtable": {
                    "packet": packet,
                    "roundtable": _clean_roundtable(),
                },
            },
        )
        
        # 验证 exists=false 被检测
        assert "dispatch_plan" in result
        assert result["dispatch_plan"]["status"] == "skipped"
    
    def test_test_summary_empty_blocked(self, isolated_environment):
        """测试：test summary 为空被拦截"""
        batch_id = "batch_test_empty"
        task_id = "tsk_test_empty_001"
        create_task(task_id, batch_id=batch_id)
        
        packet = _clean_packet()
        packet["test"]["summary"] = ""
        packet["test"]["commands"] = []
        
        result = process_trading_roundtable_callback(
            batch_id=batch_id,
            task_id=task_id,
            result={
                "verdict": "PASS",
                "trading_roundtable": {
                    "packet": packet,
                    "roundtable": _clean_roundtable(),
                },
            },
        )
        
        # 验证空 test summary 被检测
        assert "dispatch_plan" in result
        assert result["dispatch_plan"]["status"] == "skipped"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
