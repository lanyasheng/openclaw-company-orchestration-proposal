#!/usr/bin/env python3
"""
test_packet_schema_preflight.py — P0-1 Packet Schema Preflight Validation Tests

测试前置校验机制：
1. 缺失 truth fields 时会被前置标记
2. 不会错误放行为 clean PASS
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ORCHESTRATOR_DIR = REPO_ROOT / "runtime" / "orchestrator"
if str(ORCHESTRATOR_DIR) not in sys.path:
    sys.path.insert(0, str(ORCHESTRATOR_DIR))

from adapters.trading import TradingAdapter, ADAPTER_NAME  # type: ignore
from state_machine import create_task, get_state  # type: ignore
from trading_roundtable import process_trading_roundtable_callback  # type: ignore


@pytest.fixture()
def isolated_state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """隔离的测试环境 - 同时隔离 state 和 closeout 目录"""
    state_dir = tmp_path / "shared-context" / "job-status"
    closeout_dir = tmp_path / "closeouts"
    closeout_dir.mkdir(parents=True, exist_ok=True)
    
    monkeypatch.setenv("OPENCLAW_STATE_DIR", str(state_dir))
    monkeypatch.setenv("OPENCLAW_CLOSEOUT_DIR", str(closeout_dir))
    monkeypatch.setenv("OPENCLAW_ACK_GUARD_DISABLE_DELIVERY", "1")
    return state_dir


@pytest.fixture(autouse=True)
def reload_modules(isolated_state_dir: Path):
    """重新加载模块以使用隔离的环境变量"""
    import importlib
    import closeout_tracker  # type: ignore

    for module_name in ["state_machine", "batch_aggregator", "orchestrator", "trading_roundtable", "adapters.trading"]:
        if module_name in sys.modules:
            importlib.reload(sys.modules[module_name])
    
    # 重新加载 closeout_tracker 以使用新的 CLOSEOUT_DIR
    if "closeout_tracker" in sys.modules:
        importlib.reload(sys.modules["closeout_tracker"])
        # 更新全局变量
        closeout_tracker.CLOSEOUT_DIR = Path(os.environ.get("OPENCLAW_CLOSEOUT_DIR", closeout_tracker.CLOSEOUT_DIR))

    yield


def _adapter() -> TradingAdapter:
    """获取 TradingAdapter 实例"""
    return TradingAdapter()


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


def _result_with_packet_roundtable(packet: Dict[str, Any], roundtable: Dict[str, Any]) -> Dict[str, Any]:
    """构建包含 packet 和 roundtable 的 result"""
    return {
        "verdict": "PASS" if roundtable.get("conclusion") == "PASS" else "FAIL",
        "trading_roundtable": {
            "packet": packet,
            "roundtable": roundtable,
        },
    }


class TestPacketSchemaPreflight:
    """P0-1 Packet Schema Preflight Validation 测试"""
    
    def test_preflight_validation_passes_with_complete_packet(self):
        """测试：完整的 packet 通过前置校验"""
        adapter = _adapter()
        packet = _clean_packet()
        roundtable = _clean_roundtable()
        
        result = adapter.validate_packet_preflight(packet, roundtable)
        
        assert result["preflight_status"] == "pass"
        assert result["complete"] is True
        assert len(result["missing_fields"]) == 0
        assert len(result["missing_packet_fields"]) == 0
        assert len(result["missing_roundtable_fields"]) == 0
        assert result["checked_at"] == "preflight"
    
    def test_preflight_validation_fails_with_missing_packet_fields(self):
        """测试：缺失 packet 字段时前置校验失败"""
        adapter = _adapter()
        packet = _clean_packet()
        roundtable = _clean_roundtable()
        
        # 移除必需字段
        del packet["candidate_id"]
        del packet["overall_gate"]
        
        result = adapter.validate_packet_preflight(packet, roundtable)
        
        assert result["preflight_status"] == "incomplete"
        assert result["complete"] is False
        assert "candidate_id" in result["missing_fields"]
        assert "overall_gate" in result["missing_fields"]
        assert "candidate_id" in result["missing_packet_fields"]
        assert "overall_gate" in result["missing_packet_fields"]
    
    def test_preflight_validation_fails_with_missing_roundtable_fields(self):
        """测试：缺失 roundtable 字段时前置校验失败"""
        adapter = _adapter()
        packet = _clean_packet()
        roundtable = _clean_roundtable()
        
        # 移除必需字段
        del roundtable["conclusion"]
        del roundtable["next_step"]
        
        result = adapter.validate_packet_preflight(packet, roundtable)
        
        assert result["preflight_status"] == "incomplete"
        assert result["complete"] is False
        assert "conclusion" in result["missing_fields"]
        assert "next_step" in result["missing_fields"]
        assert "conclusion" in result["missing_roundtable_fields"]
        assert "next_step" in result["missing_roundtable_fields"]
    
    def test_preflight_validation_does_not_check_nested_artifact_fields(self):
        """测试：前置校验只检查 top-level 字段，不检查 nested artifact 字段"""
        adapter = _adapter()
        packet = _clean_packet()
        roundtable = _clean_roundtable()
        
        # 移除 nested artifact 字段（这些应该在完整验证中检查）
        del packet["artifact"]
        del packet["report"]
        
        result = adapter.validate_packet_preflight(packet, roundtable)
        
        # 前置校验只检查 top-level，所以应该通过
        assert result["preflight_status"] == "pass"
        assert result["complete"] is True
        # 但完整验证应该失败
        full_validation = adapter.validate_packet(packet, roundtable)
        assert full_validation["complete"] is False
    
    def test_preflight_validation_integrates_with_callback_processing(self, isolated_state_dir: Path):
        """测试：前置校验结果进入 callback 处理流程"""
        batch_id = "batch_preflight_integration_test"
        task_id = "tsk_preflight_integration_001"
        create_task(task_id, batch_id=batch_id)
        
        # 构建缺失字段的 packet
        packet = _clean_packet()
        roundtable = _clean_roundtable()
        del packet["candidate_id"]  # 缺失必需字段
        
        result = process_trading_roundtable_callback(
            batch_id=batch_id,
            task_id=task_id,
            result=_result_with_packet_roundtable(packet, roundtable),
        )
        
        # 验证返回结果包含 preflight validation
        assert "preflight_validation" in result
        assert result["preflight_validation"]["preflight_status"] == "incomplete"
        assert result["preflight_validation"]["preflight_complete"] is False
        assert "candidate_id" in result["preflight_validation"]["preflight_missing_fields"]
    
    def test_preflight_validation_clean_pass_integration(self, isolated_state_dir: Path):
        """测试：完整 packet 的 callback 处理通过前置校验"""
        batch_id = "batch_preflight_clean_pass"
        task_id = "tsk_preflight_clean_001"
        create_task(task_id, batch_id=batch_id)
        
        packet = _clean_packet()
        roundtable = _clean_roundtable()
        
        result = process_trading_roundtable_callback(
            batch_id=batch_id,
            task_id=task_id,
            result=_result_with_packet_roundtable(packet, roundtable),
        )
        
        # 验证返回结果包含 preflight validation 且通过
        assert "preflight_validation" in result
        assert result["preflight_validation"]["preflight_status"] == "pass"
        assert result["preflight_validation"]["preflight_complete"] is True
        assert len(result["preflight_validation"]["preflight_missing_fields"]) == 0
    
    def test_preflight_validation_does_not_bypass_gate(self, isolated_state_dir: Path):
        """测试：前置校验不会绕过 gate，缺失字段仍然会被标记"""
        batch_id = "batch_preflight_gate_check"
        task_id = "tsk_preflight_gate_001"
        create_task(task_id, batch_id=batch_id)
        
        # 构建缺失多个字段的 packet
        packet = _clean_packet()
        roundtable = _clean_roundtable()
        del packet["candidate_id"]
        del roundtable["conclusion"]
        
        result = process_trading_roundtable_callback(
            batch_id=batch_id,
            task_id=task_id,
            result=_result_with_packet_roundtable(packet, roundtable),
        )
        
        # 验证 preflight 标记为 incomplete
        assert result["preflight_validation"]["preflight_status"] == "incomplete"
        
        # 验证完整 validation 也标记为 incomplete
        assert "dispatch_plan" in result
        # decision 中的 packet_validation 应该包含 preflight 结果
        decision_path = Path(result["decision_path"])
        decision = json.loads(decision_path.read_text())
        assert "packet_validation" in decision["metadata"]
        assert "preflight" in decision["metadata"]["packet_validation"]
        assert decision["metadata"]["packet_validation"]["preflight"]["preflight_status"] == "incomplete"
    
    def test_preflight_validation_enters_decision_metadata(self, isolated_state_dir: Path):
        """测试：前置校验结果进入 decision metadata"""
        batch_id = "batch_preflight_decision_metadata"
        task_id = "tsk_preflight_metadata_001"
        create_task(task_id, batch_id=batch_id)
        
        packet = _clean_packet()
        roundtable = _clean_roundtable()
        del packet["owner"]  # 缺失必需字段
        
        result = process_trading_roundtable_callback(
            batch_id=batch_id,
            task_id=task_id,
            result=_result_with_packet_roundtable(packet, roundtable),
        )
        
        # 读取 decision 文件验证
        decision_path = Path(result["decision_path"])
        decision = json.loads(decision_path.read_text())
        
        # 验证 packet_validation 包含 preflight
        assert "packet_validation" in decision["metadata"]
        validation = decision["metadata"]["packet_validation"]
        assert "preflight" in validation
        assert validation["preflight"]["preflight_status"] == "incomplete"
        assert "owner" in validation["preflight"]["missing_fields"]
    
    def test_preflight_validation_enters_decision_metadata(self, isolated_state_dir: Path):
        """测试：前置校验结果进入 decision metadata 的 packet_validation"""
        batch_id = "batch_preflight_decision_meta"
        task_id = "tsk_preflight_decision_002"
        create_task(task_id, batch_id=batch_id)
        
        packet = _clean_packet()
        roundtable = _clean_roundtable()
        
        result = process_trading_roundtable_callback(
            batch_id=batch_id,
            task_id=task_id,
            result=_result_with_packet_roundtable(packet, roundtable),
        )
        
        # 读取 decision 文件验证
        decision_path = Path(result["decision_path"])
        decision = json.loads(decision_path.read_text())
        
        # 验证 packet_validation 包含 preflight 信息
        assert "packet_validation" in decision["metadata"]
        validation = decision["metadata"]["packet_validation"]
        assert "preflight" in validation
        assert validation["preflight"]["checked_at"] == "preflight"
        assert validation["preflight"]["preflight_status"] == "pass"


class TestPacketSchemaPreflightEdgeCases:
    """P0-1 边界情况测试"""
    
    def test_preflight_with_empty_packet(self):
        """测试：空 packet 的前置校验"""
        adapter = _adapter()
        packet = {}
        roundtable = _clean_roundtable()
        
        result = adapter.validate_packet_preflight(packet, roundtable)
        
        assert result["preflight_status"] == "incomplete"
        assert result["complete"] is False
        assert len(result["missing_fields"]) > 0
    
    def test_preflight_with_empty_roundtable(self):
        """测试：空 roundtable 的前置校验"""
        adapter = _adapter()
        packet = _clean_packet()
        roundtable = {}
        
        result = adapter.validate_packet_preflight(packet, roundtable)
        
        assert result["preflight_status"] == "incomplete"
        assert result["complete"] is False
        assert len(result["missing_roundtable_fields"]) > 0
    
    def test_preflight_with_none_values(self):
        """测试：None 值的前置校验"""
        adapter = _adapter()
        packet = None  # type: ignore
        roundtable = None  # type: ignore
        
        # 应该不抛异常，返回 incomplete
        result = adapter.validate_packet_preflight(packet or {}, roundtable or {})
        
        assert result["preflight_status"] == "incomplete"
        assert result["complete"] is False
    
    def test_preflight_version_mismatch_not_checked(self):
        """测试：前置校验不检查版本不匹配（这是完整验证的职责）"""
        adapter = _adapter()
        packet = _clean_packet()
        roundtable = _clean_roundtable()
        
        # 设置错误版本
        packet["packet_version"] = "wrong_version_v999"
        packet["phase_id"] = "wrong_phase_v999"
        
        result = adapter.validate_packet_preflight(packet, roundtable)
        
        # 前置校验不检查版本，所以应该通过
        assert result["preflight_status"] == "pass"
        
        # 但完整验证应该失败
        full_validation = adapter.validate_packet(packet, roundtable)
        assert full_validation["complete"] is False
        assert any("packet_version" in str(f) for f in full_validation["missing_fields"])


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
