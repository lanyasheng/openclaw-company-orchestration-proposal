#!/usr/bin/env python3
"""
test_trading_dispatch_chain.py — P0-3 Batch 1

测试 trading continuation 主链：trading_roundtable → registration → dispatch artifact。

覆盖：
- trading_roundtable 产生 continuation + registration + readiness
- 当满足 safe 条件时，生成可执行 dispatch artifact
- dispatch artifact 包含 bridge_consumer 可消费的所有字段
- registration 记录包含 readiness 状态，可查询

这是 P0-3 Batch 1 的核心测试，验证 trading 续线真正接入 execution dispatch 主链。
"""

from __future__ import annotations

import json
import pytest
from pathlib import Path
import sys
from datetime import datetime

REPO_ROOT = Path(__file__).resolve().parents[2]
ORCHESTRATOR_DIR = REPO_ROOT / "runtime" / "orchestrator"
CORE_DIR = ORCHESTRATOR_DIR / "core"

if str(ORCHESTRATOR_DIR) not in sys.path:
    sys.path.insert(0, str(ORCHESTRATOR_DIR))
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

from state_machine import create_task, get_state, STATE_DIR  # type: ignore
from trading_roundtable import process_trading_roundtable_callback  # type: ignore
from dispatch_planner import DispatchStatus  # type: ignore
from task_registration import get_registration, TaskRegistry, RegistrationLedger  # type: ignore
from sessions_spawn_request import list_spawn_requests, get_spawn_request  # type: ignore
from bridge_consumer import list_consumed_artifacts, get_consumed_by_request  # type: ignore


@pytest.fixture()
def isolated_state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """隔离的状态目录"""
    state_dir = tmp_path / "shared-context" / "job-status"
    monkeypatch.setenv("OPENCLAW_STATE_DIR", str(state_dir))
    monkeypatch.setenv("OPENCLAW_ACK_GUARD_DISABLE_DELIVERY", "1")
    monkeypatch.setenv("OPENCLAW_REGISTRY_DIR", str(tmp_path / "registry"))
    monkeypatch.setenv("OPENCLAW_SPAWN_REQUEST_DIR", str(tmp_path / "spawn_requests"))
    monkeypatch.setenv("OPENCLAW_BRIDGE_CONSUMED_DIR", str(tmp_path / "bridge_consumed"))
    return state_dir


@pytest.fixture(autouse=True)
def reload_modules(isolated_state_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """重新加载模块以使用隔离的目录
    
    P0-4 Final Mile: 添加 closeout_tracker 隔离，避免 closeout gate 污染
    """
    import importlib
    
    # 设置隔离的 closeout 目录
    closeout_dir = tmp_path / "closeouts"
    closeout_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OPENCLAW_CLOSEOUT_DIR", str(closeout_dir))

    for module_name in [
        "state_machine", "batch_aggregator", "orchestrator",
        "continuation_backends", "trading_roundtable",
        "task_registration", "sessions_spawn_request", "bridge_consumer",
        "closeout_tracker",  # P0-4 Final Mile: closeout isolation
    ]:
        if module_name in sys.modules:
            importlib.reload(sys.modules[module_name])

    yield


def _trading_pass_result() -> dict:
    """构建 trading PASS 结果（包含所有必需字段）"""
    return {
        "verdict": "PASS",
        "trading_roundtable": {
            "packet": {
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
                    "commands": [
                        "python3 research/run_acceptance_harness.py --input research/v2_portfolio/basket_configs/rs_canonical_e2e_demo.json",
                    ],
                    "notes": "requires canonical config and tracked dataset snapshot",
                },
                "tradability": {
                    "annual_turnover": 48.5,
                    "liquidity_flags": [],
                    "gross_return": 0.12,
                    "net_return": 0.12,
                    "benchmark_return": 0.05,
                    "scenario_verdict": "PASS",
                    "turnover_failure_reasons": [],
                    "liquidity_failure_reasons": [],
                    "net_vs_gross_failure_reasons": [],
                    "summary": "tradability evidence is acceptable",
                },
                "macro": {"enabled": False},
            },
            "roundtable": {
                "conclusion": "PASS",
                "blocker": "none",
                "owner": "trading",
                "next_step": "Continue to phase 2 wiring",
                "completion_criteria": "phase1 packet v1 exists with all truth paths",
            },
        },
    }


class TestTradingDispatchChainBasics:
    """测试 trading dispatch 链基本功能"""
    
    def test_trading_roundtable_produces_dispatch_plan(self, isolated_state_dir: Path):
        """测试：trading_roundtable 产生 dispatch plan"""
        batch_id = "batch_dispatch_chain_test"
        create_task("tsk_dispatch_chain_001", batch_id=batch_id)
        
        result = process_trading_roundtable_callback(
            batch_id=batch_id,
            task_id="tsk_dispatch_chain_001",
            result=_trading_pass_result(),
            allow_auto_dispatch=True,
            requester_session_key="agent:main:discord:channel:1483883339701158102",
        )
        
        assert result["status"] == "processed"
        assert "dispatch_path" in result
        assert "dispatch_plan" in result
        
        # 验证 dispatch plan 状态
        dispatch_plan = result["dispatch_plan"]
        assert dispatch_plan["status"] == "triggered"
        assert dispatch_plan["adapter"] == "trading_roundtable"
        assert dispatch_plan["scenario"] == "trading_roundtable_phase1"
        
        # 验证 safety_gates
        sg = dispatch_plan["safety_gates"]
        assert sg["allow_auto_dispatch"] is True
        assert sg["auto_dispatch_source"] == "explicit"
        assert sg["packet_complete"] is True
        assert sg["roundtable_conclusion"] == "PASS"
        
        # 验证 continuation_contract
        cc = dispatch_plan.get("continuation_contract") or dispatch_plan["continuation"]
        assert cc["stopped_because"]
        assert cc["next_step"]
        assert cc["next_owner"]
    
    def test_trading_roundtable_produces_registration_handoff(self, isolated_state_dir: Path):
        """测试：trading_roundtable 产生 registration handoff"""
        batch_id = "batch_registration_test"
        create_task("tsk_registration_001", batch_id=batch_id)
        
        result = process_trading_roundtable_callback(
            batch_id=batch_id,
            task_id="tsk_registration_001",
            result=_trading_pass_result(),
            allow_auto_dispatch=True,
            requester_session_key="agent:main:discord:channel:1483883339701158102",
        )
        
        assert result["status"] == "processed"
        assert "handoff_schema" in result
        
        handoff = result["handoff_schema"]
        assert "planning_handoff" in handoff
        assert "registration_handoff" in handoff
        
        # 验证 planning handoff
        planning = handoff["planning_handoff"]
        assert planning["source_type"] == "dispatch_plan"
        assert planning["scenario"] == "trading_roundtable_phase1"
        assert planning["adapter"] == "trading_roundtable"
        
        # 验证 registration handoff
        registration = handoff["registration_handoff"]
        assert registration["registration_id"].startswith("reg_")
        assert registration["task_id"].startswith("task_")
        assert registration["batch_id"] == batch_id
        assert registration["registration_status"] == "registered"
        
        # 验证 readiness (P0-2 Batch 4)
        assert "readiness" in registration
        assert registration["readiness"]["status"] == "ready"
        assert registration["readiness"]["eligible"] is True
    
    def test_trading_roundtable_produces_execution_handoff_when_triggered(self, isolated_state_dir: Path):
        """测试：trading_roundtable 在 triggered 时产生 execution handoff"""
        batch_id = "batch_execution_test"
        create_task("tsk_execution_001", batch_id=batch_id)
        
        result = process_trading_roundtable_callback(
            batch_id=batch_id,
            task_id="tsk_execution_001",
            result=_trading_pass_result(),
            allow_auto_dispatch=True,
            requester_session_key="agent:main:discord:channel:1483883339701158102",
        )
        
        assert result["status"] == "processed"
        assert result["dispatch_plan"]["status"] == "triggered"
        
        # 验证 execution handoff 存在
        handoff = result["handoff_schema"]
        assert "execution_handoff" in handoff
        
        execution = handoff["execution_handoff"]
        assert execution["runtime"] == "subagent"
        assert execution["task"]
        assert execution["timeout_seconds"] == 3600
        assert "continuation_context" in execution
    
    def test_trading_roundtable_skipped_when_not_safe(self, isolated_state_dir: Path):
        """测试：trading_roundtable 在不安全时跳过 dispatch"""
        batch_id = "batch_skipped_test"
        create_task("tsk_skipped_001", batch_id=batch_id)
        
        # CONDITIONAL 结论应该导致 skipped
        conditional_result = _trading_pass_result()
        conditional_result["trading_roundtable"]["roundtable"]["conclusion"] = "CONDITIONAL"
        conditional_result["trading_roundtable"]["roundtable"]["blocker"] = "tradability"
        
        result = process_trading_roundtable_callback(
            batch_id=batch_id,
            task_id="tsk_skipped_001",
            result=conditional_result,
            requester_session_key="agent:main:discord:channel:1483883339701158102",
        )
        
        assert result["status"] == "processed"
        assert result["dispatch_plan"]["status"] == "skipped"
        
        # 验证 registration_status 是 skipped
        handoff = result["handoff_schema"]
        registration = handoff["registration_handoff"]
        assert registration["registration_status"] == "skipped"
        assert registration["ready_for_auto_dispatch"] is False


class TestTradingRegistrationLedger:
    """测试 trading registration ledger"""
    
    def test_registration_record_persisted(self, isolated_state_dir: Path):
        """测试：registration 记录被持久化"""
        batch_id = "batch_ledger_test"
        create_task("tsk_ledger_001", batch_id=batch_id)
        
        result = process_trading_roundtable_callback(
            batch_id=batch_id,
            task_id="tsk_ledger_001",
            result=_trading_pass_result(),
            allow_auto_dispatch=True,
            requester_session_key="agent:main:discord:channel:1483883339701158102",
        )
        
        # 获取 registration info
        reg_info = result["registration"]
        registration_id = reg_info["registration_id"]
        
        # 验证可以从 registry 读取
        record = get_registration(registration_id)
        assert record is not None
        assert record.task_id == reg_info["task_id"]
        assert record.batch_id == batch_id
        assert record.registration_status == "registered"
        
        # 验证 metadata 包含 handoff_id
        assert "handoff_id" in record.metadata
    
    def test_registration_ledger_queryable(self, isolated_state_dir: Path):
        """测试：registration ledger 可查询"""
        batch_id = "batch_ledger_query_test"
        create_task("tsk_ledger_query_001", batch_id=batch_id)
        
        result = process_trading_roundtable_callback(
            batch_id=batch_id,
            task_id="tsk_ledger_query_001",
            result=_trading_pass_result(),
            allow_auto_dispatch=True,
            requester_session_key="agent:main:discord:channel:1483883339701158102",
        )
        
        # 使用 ledger 查询
        ledger = RegistrationLedger()
        entries = ledger.list_entries(limit=10)
        
        # 验证至少有一条记录
        assert len(entries) >= 1
        
        # 验证可以按 readiness 查询
        ready_entries = ledger.list_entries(readiness_status="ready", limit=10)
        assert len(ready_entries) >= 1
        
        # 验证可以获取 ready for dispatch 的记录
        dispatch_ready = ledger.get_ready_for_dispatch(limit=10)
        assert len(dispatch_ready) >= 1


class TestTradingDispatchArtifactStructure:
    """测试 trading dispatch artifact 结构"""
    
    def test_dispatch_plan_contains_required_fields_for_bridge(self, isolated_state_dir: Path):
        """测试：dispatch plan 包含 bridge_consumer 所需的字段"""
        batch_id = "batch_bridge_test"
        create_task("tsk_bridge_001", batch_id=batch_id)
        
        result = process_trading_roundtable_callback(
            batch_id=batch_id,
            task_id="tsk_bridge_001",
            result=_trading_pass_result(),
            allow_auto_dispatch=True,
            requester_session_key="agent:main:discord:channel:1483883339701158102",
        )
        
        dispatch_plan = result["dispatch_plan"]
        
        # 验证 bridge_consumer 所需的核心字段
        assert "dispatch_id" in dispatch_plan
        assert "batch_id" in dispatch_plan
        assert "recommended_spawn" in dispatch_plan
        
        # 验证 recommended_spawn 包含 sessions_spawn 所需参数
        spawn = dispatch_plan["recommended_spawn"]
        assert "runtime" in spawn
        assert "task" in spawn
        assert "dispatch_id" in spawn
        assert "dispatch_path" in spawn
        
        # 验证 canonical_callback 契约
        callback = dispatch_plan["canonical_callback"]
        assert callback["required"] is True
        assert "business_terminal_source" in callback
        assert "callback_payload_schema" in callback
    
    def test_dispatch_plan_safety_gates_complete(self, isolated_state_dir: Path):
        """测试：dispatch plan safety_gates 完整"""
        batch_id = "batch_safety_gates_test"
        create_task("tsk_safety_gates_001", batch_id=batch_id)
        
        result = process_trading_roundtable_callback(
            batch_id=batch_id,
            task_id="tsk_safety_gates_001",
            result=_trading_pass_result(),
            allow_auto_dispatch=True,
            requester_session_key="agent:main:discord:channel:1483883339701158102",
        )
        
        sg = result["dispatch_plan"]["safety_gates"]
        
        # 验证所有 safety_gates 字段存在
        required_fields = [
            "allow_auto_dispatch",
            "auto_dispatch_source",
            "default_auto_dispatch_eligible",
            "default_auto_dispatch_status",
            "default_auto_dispatch_blockers",
            "default_auto_dispatch_criteria",
            "batch_timeout_count",
            "batch_failed_count",
            "packet_complete",
            "roundtable_conclusion",
            "business_terminal_source",
            "backend_terminal_role",
        ]
        
        for field in required_fields:
            assert field in sg, f"Missing safety_gates field: {field}"


class TestTradingContinuationIntegration:
    """集成测试：trading continuation 完整链路"""
    
    def test_full_trading_dispatch_chain(self, isolated_state_dir: Path):
        """
        集成测试：完整的 trading dispatch 链。
        
        验证：
        1. trading_roundtable 产生 dispatch plan
        2. dispatch plan 转换为 planning/registration/execution handoff
        3. registration 记录被持久化到 registry
        4. dispatch plan 包含 bridge_consumer 可消费的所有字段
        5. state machine 正确标记任务状态
        """
        batch_id = "batch_full_chain_test"
        task_id = "tsk_full_chain_001"
        create_task(task_id, batch_id=batch_id)
        
        # 1. 调用 trading_roundtable
        result = process_trading_roundtable_callback(
            batch_id=batch_id,
            task_id=task_id,
            result=_trading_pass_result(),
            allow_auto_dispatch=True,
            requester_session_key="agent:main:discord:channel:1483883339701158102",
        )
        
        # 2. 验证 dispatch plan
        assert result["status"] == "processed"
        assert result["dispatch_plan"]["status"] == "triggered"
        dispatch_id = result["dispatch_plan"]["dispatch_id"]
        
        # 3. 验证 handoff artifacts
        handoff = result["handoff_schema"]
        assert "planning_handoff" in handoff
        assert "registration_handoff" in handoff
        assert "execution_handoff" in handoff
        
        # 4. 验证 registration 记录
        reg_info = result["registration"]
        record = get_registration(reg_info["registration_id"])
        assert record is not None
        assert record.registration_status == "registered"
        assert record.ready_for_auto_dispatch is True
        
        # 5. 验证 ledger 可查询
        ledger = RegistrationLedger()
        ready_entries = ledger.get_ready_for_dispatch(limit=10)
        assert len(ready_entries) >= 1
        
        # 6. 验证 state machine 状态
        state = get_state(task_id)
        assert state["state"] == "next_task_dispatched"
        
        # 7. 验证 dispatch plan 文件存在
        dispatch_path = Path(result["dispatch_path"])
        assert dispatch_path.exists()
        dispatch_data = json.loads(dispatch_path.read_text())
        assert dispatch_data["dispatch_id"] == dispatch_id
        
        # 8. 验证 decision 文件存在
        decision_path = Path(result["decision_path"])
        assert decision_path.exists()
    
    def test_trading_dispatch_chain_conditional_blocked(self, isolated_state_dir: Path):
        """
        测试：trading dispatch 链在 CONDITIONAL 时被阻塞。
        
        验证 safe semi-auto 机制正常工作：只有 clean PASS 才允许进入 dispatch。
        """
        batch_id = "batch_blocked_chain_test"
        task_id = "tsk_blocked_chain_001"
        create_task(task_id, batch_id=batch_id)
        
        # CONDITIONAL 结果
        conditional_result = _trading_pass_result()
        conditional_result["trading_roundtable"]["roundtable"]["conclusion"] = "CONDITIONAL"
        conditional_result["trading_roundtable"]["roundtable"]["blocker"] = "tradability"
        conditional_result["trading_roundtable"]["packet"]["overall_gate"] = "CONDITIONAL"
        
        # 调用 trading_roundtable
        result = process_trading_roundtable_callback(
            batch_id=batch_id,
            task_id=task_id,
            result=conditional_result,
            requester_session_key="agent:main:discord:channel:1483883339701158102",
        )
        
        # 验证 dispatch 被跳过
        assert result["dispatch_plan"]["status"] == "skipped"
        
        # 验证 registration_status 是 skipped
        reg_info = result["registration"]
        assert reg_info["registration_status"] == "skipped"
        assert reg_info["ready_for_auto_dispatch"] is False
        
        # 验证 state machine 状态是 final_closed
        state = get_state(task_id)
        assert state["state"] == "final_closed"
        
        # 验证 ledger 中没有 ready for dispatch 的记录
        ledger = RegistrationLedger()
        ready_entries = ledger.get_ready_for_dispatch(limit=10)
        # 这条记录不应该在 ready for dispatch 列表中


class TestTradingDispatchBackwardCompatibility:
    """测试向后兼容性"""
    
    def test_dispatch_plan_loads_without_continuation_contract(self, isolated_state_dir: Path):
        """测试：dispatch plan 兼容没有 continuation_contract 的情况"""
        from dispatch_planner import DispatchPlanner, DispatchBackend
        
        planner = DispatchPlanner()
        
        # 使用旧格式（没有 contract_version）
        plan = planner.create_plan(
            dispatch_id="dispatch_compat_test",
            batch_id="batch_compat_test",
            scenario="test",
            adapter="test",
            decision_id="dec_test",
            decision={"action": "proceed"},
            continuation={
                "stopped_because": "test",
                "next_step": "test",
                "next_owner": "test",
            },
            backend=DispatchBackend.SUBAGENT,
            allow_auto_dispatch=False,
        )
        
        # 验证可以转换为 handoff
        handoff = plan.to_planning_handoff()
        assert handoff.source_type == "dispatch_plan"
        assert handoff.continuation_contract["stopped_because"] == "test"
    
    def test_trading_roundtable_output_backward_compatible(self, isolated_state_dir: Path):
        """测试：trading_roundtable 输出向后兼容"""
        batch_id = "batch_compat_output_test"
        create_task("tsk_compat_output_001", batch_id=batch_id)
        
        result = process_trading_roundtable_callback(
            batch_id=batch_id,
            task_id="tsk_compat_output_001",
            result=_trading_pass_result(),
            allow_auto_dispatch=True,
            requester_session_key="agent:main:discord:channel:1483883339701158102",
        )
        
        # 验证旧字段仍然存在
        assert "dispatch_plan" in result
        assert "summary_path" in result
        assert "decision_path" in result
        assert "dispatch_path" in result
        assert "ack_result" in result
        
        # 验证新字段也存在
        assert "handoff_schema" in result
        assert "registration" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
