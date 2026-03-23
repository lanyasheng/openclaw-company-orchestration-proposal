#!/usr/bin/env python3
"""
test_handoff_schema.py — P0-2 Batch 1

测试 handoff_schema 模块，覆盖 planning → registration → execution 的统一 handoff。

覆盖：
- PlanningHandoff 构建与验证
- RegistrationHandoff 从 planning 推导
- ExecutionHandoff 从 planning 推导
- 与 dispatch_planner 集成
- 与 task_registration 集成
- 向后兼容性
"""

from __future__ import annotations

import pytest
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
ORCHESTRATOR_DIR = REPO_ROOT / "runtime" / "orchestrator"
CORE_DIR = ORCHESTRATOR_DIR / "core"

if str(ORCHESTRATOR_DIR) not in sys.path:
    sys.path.insert(0, str(ORCHESTRATOR_DIR))
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

from partial_continuation import ContinuationContract, build_continuation_contract
from core.handoff_schema import (
    PlanningHandoff,
    RegistrationHandoff,
    ExecutionHandoff,
    build_planning_handoff,
    build_registration_handoff,
    build_execution_handoff,
    handoff_to_task_registration,
    handoff_to_dispatch_spawn,
    HANDOFF_SCHEMA_VERSION,
)
from dispatch_planner import DispatchPlanner, DispatchBackend
from task_registration import register_from_handoff, TaskRegistry, _registry_file


class TestPlanningHandoffBasics:
    """测试 PlanningHandoff 基本功能"""
    
    def test_build_planning_handoff(self):
        """测试：构建 PlanningHandoff"""
        continuation_contract = {
            "stopped_because": "manual_review_required",
            "next_step": "Wait for human confirmation",
            "next_owner": "main",
        }
        
        handoff = build_planning_handoff(
            source_type="dispatch_plan",
            source_id="dispatch_001",
            continuation_contract=continuation_contract,
            scenario="trading_roundtable_phase1",
            adapter="trading_roundtable",
            owner="trading",
            backend_preference="subagent",
            task_preview="Continue trading roundtable after gate",
            safety_gates={"allow_auto_dispatch": False},
        )
        
        assert handoff.handoff_id.startswith("handoff_")
        assert handoff.source_type == "dispatch_plan"
        assert handoff.source_id == "dispatch_001"
        assert handoff.continuation_contract == continuation_contract
        assert handoff.scenario == "trading_roundtable_phase1"
        assert handoff.adapter == "trading_roundtable"
        assert handoff.owner == "trading"
        assert handoff.backend_preference == "subagent"
        assert handoff.task_preview == "Continue trading roundtable after gate"
        assert handoff.safety_gates == {"allow_auto_dispatch": False}
    
    def test_planning_handoff_validation(self):
        """测试：PlanningHandoff 验证"""
        # 有效的 handoff
        handoff = build_planning_handoff(
            source_type="dispatch_plan",
            source_id="dispatch_001",
            continuation_contract={
                "stopped_because": "test",
                "next_step": "test",
                "next_owner": "test",
            },
            scenario="test_scenario",
            adapter="test_adapter",
            owner="main",
        )
        
        is_valid, errors = handoff.validate()
        assert is_valid is True
        assert len(errors) == 0
        
        # 无效的 handoff (缺少 continuation_contract 核心字段)
        bad_handoff = PlanningHandoff(
            handoff_id="handoff_test",
            source_type="dispatch_plan",
            source_id="dispatch_001",
            continuation_contract={},  # 缺少核心字段
            scenario="test",
            adapter="test",
            owner="main",
        )
        
        is_valid, errors = bad_handoff.validate()
        assert is_valid is False
        assert len(errors) > 0
        assert "continuation_contract.stopped_because is required" in errors
    
    def test_planning_handoff_to_dict(self):
        """测试：PlanningHandoff 序列化"""
        handoff = build_planning_handoff(
            source_type="manual",
            source_id="manual_001",
            continuation_contract={
                "stopped_because": "test_stop",
                "next_step": "test_next",
                "next_owner": "test_owner",
            },
            scenario="test",
            adapter="test",
            owner="main",
        )
        
        d = handoff.to_dict()
        assert d["handoff_version"] == HANDOFF_SCHEMA_VERSION
        assert d["handoff_id"] == handoff.handoff_id
        assert d["source_type"] == "manual"
        assert d["continuation_contract"]["stopped_because"] == "test_stop"
        assert "created_at" in d["metadata"]


class TestRegistrationHandoff:
    """测试 RegistrationHandoff"""
    
    def test_build_registration_handoff_from_planning(self):
        """测试：从 PlanningHandoff 构建 RegistrationHandoff"""
        planning = build_planning_handoff(
            source_type="dispatch_plan",
            source_id="dispatch_001",
            continuation_contract={
                "stopped_because": "gate_held",
                "next_step": "Wait for gate release",
                "next_owner": "trading",
            },
            scenario="trading_roundtable_phase1",
            adapter="trading_roundtable",
            owner="trading",
            backend_preference="subagent",
            safety_gates={"allow_auto_dispatch": False},
        )
        
        registration = build_registration_handoff(planning, batch_id="batch_001")
        
        assert registration.handoff_id == planning.handoff_id
        assert registration.registration_id.startswith("reg_")
        assert registration.task_id.startswith("task_")
        assert registration.batch_id == "batch_001"
        assert registration.registration_status == "skipped"  # 因为 allow_auto_dispatch=False
        assert registration.ready_for_auto_dispatch is False
        
        # 验证 proposed_task 包含 continuation 信息
        assert "continuation" in registration.proposed_task
        assert registration.proposed_task["continuation"]["stopped_because"] == "gate_held"
        assert registration.proposed_task["continuation"]["next_step"] == "Wait for gate release"
        
        # 验证 truth_anchor
        assert registration.truth_anchor is not None
        assert registration.truth_anchor["anchor_type"] == "handoff_id"
        assert registration.truth_anchor["anchor_value"] == planning.handoff_id
    
    def test_registration_handoff_auto_dispatch_ready(self):
        """测试：RegistrationHandoff 自动推导 ready_for_auto_dispatch"""
        planning = build_planning_handoff(
            source_type="dispatch_plan",
            source_id="dispatch_002",
            continuation_contract={
                "stopped_because": "continuation",
                "next_step": "Continue work",
                "next_owner": "main",
            },
            scenario="test",
            adapter="test",
            owner="main",
            safety_gates={"allow_auto_dispatch": True},  # 允许自动 dispatch
        )
        
        registration = build_registration_handoff(planning)
        
        assert registration.registration_status == "registered"
        assert registration.ready_for_auto_dispatch is True


class TestExecutionHandoff:
    """测试 ExecutionHandoff"""
    
    def test_build_execution_handoff_from_planning(self):
        """测试：从 PlanningHandoff 构建 ExecutionHandoff"""
        planning = build_planning_handoff(
            source_type="dispatch_plan",
            source_id="dispatch_003",
            continuation_contract={
                "stopped_because": "test",
                "next_step": "Execute next step",
                "next_owner": "main",
            },
            scenario="test",
            adapter="test",
            owner="main",
            backend_preference="tmux",
            task_preview="Test task preview",
        )
        
        execution = build_execution_handoff(planning, timeout_seconds=1800)
        
        assert execution.handoff_id == planning.handoff_id
        assert execution.dispatch_id.startswith("dispatch_")
        assert execution.runtime == "tmux"
        assert execution.task == "Test task preview"
        assert execution.timeout_seconds == 1800
        
        # 验证 continuation_context
        assert execution.continuation_context is not None
        assert execution.continuation_context["handoff_id"] == planning.handoff_id
        assert execution.continuation_context["continuation_contract"]["next_step"] == "Execute next step"
    
    def test_execution_handoff_defaults(self):
        """测试：ExecutionHandoff 默认值"""
        planning = build_planning_handoff(
            source_type="manual",
            source_id="manual_001",
            continuation_contract={
                "stopped_because": "test",
                "next_step": "Default test",
                "next_owner": "main",
            },
            scenario="test",
            adapter="test",
            owner="main",
            backend_preference="subagent",
        )
        
        execution = build_execution_handoff(planning)
        
        assert execution.runtime == "subagent"
        assert execution.task == "Default test"  # 从 next_step 推导
        assert execution.timeout_seconds == 3600  # 默认值


class TestHandoffConversion:
    """测试 handoff 转换函数"""
    
    def test_handoff_to_task_registration(self):
        """测试：RegistrationHandoff → task_registration 参数"""
        registration = RegistrationHandoff(
            handoff_id="handoff_test",
            registration_id="reg_test",
            task_id="task_test",
            batch_id="batch_test",
            proposed_task={"title": "Test task"},
            registration_status="registered",
            ready_for_auto_dispatch=True,
            truth_anchor={"anchor_type": "handoff_id", "anchor_value": "handoff_test"},
        )
        
        kwargs = handoff_to_task_registration(registration)
        
        assert kwargs["proposed_task"] == {"title": "Test task"}
        assert kwargs["registration_status"] == "registered"
        assert kwargs["batch_id"] == "batch_test"
        assert kwargs["ready_for_auto_dispatch"] is True
        assert kwargs["metadata"]["handoff_id"] == "handoff_test"
    
    def test_handoff_to_dispatch_spawn(self):
        """测试：ExecutionHandoff → sessions_spawn 参数"""
        execution = ExecutionHandoff(
            handoff_id="handoff_test",
            dispatch_id="dispatch_test",
            runtime="subagent",
            task="Test task",
            workdir="/tmp/test",
            timeout_seconds=1800,
        )
        
        kwargs = handoff_to_dispatch_spawn(execution, requester_session_key="agent:test")
        
        assert kwargs["runtime"] == "subagent"
        assert kwargs["task"] == "Test task"
        assert kwargs["workdir"] == "/tmp/test"
        assert kwargs["timeout_seconds"] == 1800
        assert kwargs["metadata"]["handoff_id"] == "handoff_test"
        assert kwargs["metadata"]["requester_session_key"] == "agent:test"


class TestDispatchPlannerIntegration:
    """测试与 DispatchPlanner 的集成"""
    
    def test_dispatch_plan_to_planning_handoff(self):
        """测试：DispatchPlan.to_planning_handoff()"""
        planner = DispatchPlanner()
        
        plan = planner.create_plan(
            dispatch_id="dispatch_handoff_001",
            batch_id="batch_handoff_001",
            scenario="trading_roundtable_phase1",
            adapter="trading_roundtable",
            decision_id="decision_001",
            decision={"action": "proceed"},
            continuation={
                "stopped_because": "manual_review",
                "next_step": "Wait for review",
                "next_owner": "trading",
            },
            backend=DispatchBackend.SUBAGENT,
            allow_auto_dispatch=False,
        )
        
        # 转换为 PlanningHandoff
        handoff = plan.to_planning_handoff()
        
        assert handoff.source_type == "dispatch_plan"
        assert handoff.source_id == "dispatch_handoff_001"
        assert handoff.scenario == "trading_roundtable_phase1"
        assert handoff.adapter == "trading_roundtable"
        assert handoff.continuation_contract["stopped_because"] == "manual_review"
        assert handoff.continuation_contract["next_step"] == "Wait for review"
        assert handoff.backend_preference == "subagent"
    
    def test_dispatch_plan_handoff_roundtrip(self):
        """测试：DispatchPlan → PlanningHandoff → dict → PlanningHandoff"""
        planner = DispatchPlanner()
        
        plan = planner.create_plan(
            dispatch_id="dispatch_handoff_002",
            batch_id="batch_handoff_002",
            scenario="test",
            adapter="test",
            decision_id="decision_002",
            decision={"action": "proceed"},
            continuation={
                "stopped_because": "test",
                "next_step": "test",
                "next_owner": "test",
            },
        )
        
        # 转换为 handoff
        handoff1 = plan.to_planning_handoff()
        
        # 序列化再反序列化
        d = handoff1.to_dict()
        handoff2 = PlanningHandoff.from_dict(d)
        
        # 验证核心字段保持一致
        assert handoff2.source_type == handoff1.source_type
        assert handoff2.source_id == handoff1.source_id
        assert handoff2.continuation_contract == handoff1.continuation_contract
        assert handoff2.scenario == handoff1.scenario


class TestTaskRegistrationIntegration:
    """测试与 TaskRegistration 的集成"""
    
    def test_register_from_handoff(self, tmp_path, monkeypatch):
        """测试：register_from_handoff() 真实注册"""
        # 临时重定向 registry 目录
        monkeypatch.setenv("OPENCLAW_REGISTRY_DIR", str(tmp_path))
        
        # 构建 handoff
        planning = build_planning_handoff(
            source_type="dispatch_plan",
            source_id="dispatch_reg_test",
            continuation_contract={
                "stopped_because": "test",
                "next_step": "Test registration",
                "next_owner": "main",
            },
            scenario="test_scenario",
            adapter="test_adapter",
            owner="test_owner",
        )
        
        registration = build_registration_handoff(planning, batch_id="batch_reg_test")
        
        # 注册
        record = register_from_handoff(registration)
        
        # 验证注册成功
        assert record.registration_id == registration.registration_id
        assert record.task_id == registration.task_id
        assert record.batch_id == registration.batch_id
        assert record.registration_status == registration.registration_status
        
        # 验证可以从 registry 读取
        registry = TaskRegistry()
        retrieved = registry.get(record.registration_id)
        assert retrieved is not None
        assert retrieved.metadata.get("handoff_id") == planning.handoff_id


class TestBackwardCompatibility:
    """测试向后兼容性"""
    
    def test_planning_handoff_from_old_continuation_dict(self):
        """测试：PlanningHandoff 兼容旧的 continuation dict 格式"""
        # 旧格式可能没有 contract_version
        old_format = {
            "stopped_because": "old_style",
            "next_step": "old_step",
            "next_owner": "old_owner",
        }
        
        handoff = build_planning_handoff(
            source_type="completion_receipt",
            source_id="receipt_001",
            continuation_contract=old_format,
            scenario="test",
            adapter="test",
            owner="main",
        )
        
        assert handoff.continuation_contract == old_format
        is_valid, errors = handoff.validate()
        assert is_valid is True
    
    def test_registration_handoff_without_truth_anchor(self):
        """测试：RegistrationHandoff 兼容没有 truth_anchor 的情况"""
        registration = RegistrationHandoff(
            handoff_id="handoff_test",
            registration_id="reg_test",
            task_id="task_test",
            batch_id=None,
            proposed_task={},
            truth_anchor=None,  # 可以为 None
        )
        
        d = registration.to_dict()
        assert d["truth_anchor"] is None
        
        # 反序列化
        registration2 = RegistrationHandoff.from_dict(d)
        assert registration2.truth_anchor is None


class TestIntegration:
    """集成测试：完整 handoff 流程"""
    
    def test_full_handoff_workflow(self, tmp_path, monkeypatch):
        """集成测试：完整的 planning → registration → execution handoff 流程"""
        # 临时重定向 registry 目录
        monkeypatch.setenv("OPENCLAW_REGISTRY_DIR", str(tmp_path))
        
        # 1. 创建 DispatchPlan
        planner = DispatchPlanner()
        plan = planner.create_plan(
            dispatch_id="dispatch_integration",
            batch_id="batch_integration",
            scenario="trading_roundtable_phase1",
            adapter="trading_roundtable",
            decision_id="decision_integration",
            decision={"action": "proceed", "metadata": {}},
            continuation={
                "stopped_because": "gate_held",
                "next_step": "Continue after gate",
                "next_owner": "trading",
            },
            backend=DispatchBackend.SUBAGENT,
            allow_auto_dispatch=False,
        )
        
        # 2. 转换为 PlanningHandoff
        planning_handoff = plan.to_planning_handoff()
        assert planning_handoff.source_type == "dispatch_plan"
        
        # 3. 构建 RegistrationHandoff
        registration_handoff = build_registration_handoff(planning_handoff)
        assert registration_handoff.registration_status == "skipped"  # allow_auto_dispatch=False
        
        # 4. 构建 ExecutionHandoff
        execution_handoff = build_execution_handoff(planning_handoff)
        assert execution_handoff.runtime == "subagent"
        
        # 5. 注册任务
        record = register_from_handoff(registration_handoff)
        assert record.registration_id == registration_handoff.registration_id
        
        # 6. 转换为 sessions_spawn 参数
        spawn_params = handoff_to_dispatch_spawn(execution_handoff)
        assert spawn_params["runtime"] == "subagent"
        assert "continuation_context" in spawn_params["metadata"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
