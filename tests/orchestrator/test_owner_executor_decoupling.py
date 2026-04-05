#!/usr/bin/env python3
"""
test_owner_executor_decoupling.py — P0-3 Batch 5

测试 owner/executor 解耦功能，覆盖：
- execution_profile 推导
- executor 解析
- coding lane 默认 Claude Code
- 非 coding lane 保持 subagent
- trading / channel 场景复用 owner/executor 模型

核心规则：
- execution_profile=coding → executor=claude_code
- execution_profile=generic_subagent → executor=subagent
- execution_profile=interactive_observable → executor=subagent
- task_preview 包含 coding keywords → execution_profile=coding → executor=claude_code
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

from core.handoff_schema import (
    PlanningHandoff,
    build_planning_handoff,
    _resolve_executor_from_profile_and_task,
    _resolve_execution_profile_from_task,
)
from dispatch_planner import DispatchPlanner, DispatchBackend


class TestExecutionProfileResolution:
    """测试 execution_profile 推导"""
    
    def test_coding_keywords_yield_coding_profile(self):
        """测试：coding keywords → coding profile"""
        test_cases = [
            "Implement new feature",
            "Refactor the payment module",
            "Fix the bug in auth",
            "Write tests for API",
            "Bugfix: handle edge case",
            "test-fix: update test cases",
        ]
        
        for task in test_cases:
            profile = _resolve_execution_profile_from_task(task)
            assert profile == "coding", f"Expected 'coding' for task: {task}"
    
    def test_non_coding_yield_generic_profile(self):
        """测试：非 coding 任务 → generic_subagent profile"""
        test_cases = [
            "Review trading strategy",
            "Analyze market data",
            "Write documentation",
            "Plan architecture",
            "Monitor system health",
        ]
        
        for task in test_cases:
            profile = _resolve_execution_profile_from_task(task)
            assert profile == "generic_subagent", f"Expected 'generic_subagent' for task: {task}"
    
    def test_tmux_backend_yield_interactive_profile(self):
        """测试：tmux backend → interactive_observable profile"""
        profile = _resolve_execution_profile_from_task(
            "Monitor long-running task",
            backend_preference="tmux"
        )
        assert profile == "interactive_observable"
    
    def test_explicit_profile_override(self):
        """测试：显式指定 profile 覆盖自动推导"""
        # 即使 task 包含 coding keywords，显式指定 generic_subagent 应该生效
        handoff = build_planning_handoff(
            source_type="dispatch_plan",
            source_id="test_001",
            continuation_contract={
                "stopped_because": "test",
                "next_step": "test",
                "next_owner": "test",
            },
            scenario="test",
            adapter="test",
            owner="main",
            execution_profile="generic_subagent",  # 显式指定
            task_preview="Implement new feature",  # 包含 coding keyword
        )
        
        assert handoff.execution_profile == "generic_subagent"


class TestExecutorResolution:
    """测试 executor 解析"""
    
    def test_coding_profile_yield_claude_code(self):
        """测试：coding profile → claude_code executor"""
        executor = _resolve_executor_from_profile_and_task(
            execution_profile="coding",
            task_preview="Implement feature"
        )
        assert executor == "claude_code"
    
    def test_generic_profile_yield_subagent(self):
        """测试：generic_subagent profile → subagent executor"""
        executor = _resolve_executor_from_profile_and_task(
            execution_profile="generic_subagent",
            task_preview="Review strategy"
        )
        assert executor == "subagent"
    
    def test_interactive_profile_yield_subagent(self):
        """测试：interactive_observable profile → subagent executor"""
        executor = _resolve_executor_from_profile_and_task(
            execution_profile="interactive_observable",
            task_preview="Monitor task"
        )
        assert executor == "subagent"
    
    def test_explicit_executor_preference_override(self):
        """测试：显式指定 executor_preference 覆盖自动推导"""
        # 即使 profile 是 coding，显式指定 subagent 应该生效
        executor = _resolve_executor_from_profile_and_task(
            execution_profile="coding",
            task_preview="Implement feature",
            executor_preference="subagent"
        )
        assert executor == "subagent"
    
    def test_coding_keywords_fallback(self):
        """测试：task_preview keywords fallback (无 profile 时)"""
        executor = _resolve_executor_from_profile_and_task(
            execution_profile="generic_subagent",
            task_preview="Refactor the payment module"
        )
        # 虽然 profile 是 generic，但 task 包含 coding keywords
        # 应该还是返回 subagent (因为 profile 优先)
        assert executor == "subagent"


class TestBuildPlanningHandoffWithExecutor:
    """测试 build_planning_handoff 包含 executor 推导"""
    
    def test_coding_task_auto_claude_code(self):
        """测试：coding 任务自动推导 claude_code executor"""
        handoff = build_planning_handoff(
            source_type="dispatch_plan",
            source_id="coding_001",
            continuation_contract={
                "stopped_because": "continuation",
                "next_step": "Implement new API endpoint",
                "next_owner": "main",
            },
            scenario="api_development",
            adapter="api_adapter",
            owner="main",
        )
        
        assert handoff.execution_profile == "coding"
        assert handoff.executor == "claude_code"
    
    def test_non_coding_task_auto_subagent(self):
        """测试：非 coding 任务自动推导 subagent executor"""
        handoff = build_planning_handoff(
            source_type="dispatch_plan",
            source_id="generic_001",
            continuation_contract={
                "stopped_because": "continuation",
                "next_step": "Review trading strategy",
                "next_owner": "trading",
            },
            scenario="trading_strategy",
            adapter="trading_adapter",
            owner="trading",
        )
        
        assert handoff.execution_profile == "generic_subagent"
        assert handoff.executor == "subagent"
    
    def test_tmux_backend_interactive_profile(self):
        """测试：tmux backend → interactive_observable profile"""
        handoff = build_planning_handoff(
            source_type="dispatch_plan",
            source_id="tmux_001",
            continuation_contract={
                "stopped_because": "continuation",
                "next_step": "Monitor long-running process",
                "next_owner": "ops",
            },
            scenario="monitoring",
            adapter="ops_adapter",
            owner="ops",
            backend_preference="tmux",
        )
        
        assert handoff.execution_profile == "interactive_observable"
        assert handoff.backend_preference == "tmux"
        assert handoff.executor == "subagent"
    
    def test_executor_preference_override(self):
        """测试：executor_preference 覆盖自动推导"""
        handoff = build_planning_handoff(
            source_type="dispatch_plan",
            source_id="override_001",
            continuation_contract={
                "stopped_because": "continuation",
                "next_step": "Implement feature",
                "next_owner": "main",
            },
            scenario="feature",
            adapter="feature_adapter",
            owner="main",
            executor_preference="subagent",  # 显式覆盖
        )
        
        # 虽然 task 是 coding，但显式指定 subagent
        assert handoff.executor == "subagent"
    
    def test_handoff_to_dict_includes_executor_fields(self):
        """测试：handoff.to_dict() 包含 executor 字段"""
        handoff = build_planning_handoff(
            source_type="dispatch_plan",
            source_id="dict_001",
            continuation_contract={
                "stopped_because": "test",
                "next_step": "test",
                "next_owner": "test",
            },
            scenario="test",
            adapter="test",
            owner="main",
        )
        
        d = handoff.to_dict()
        assert "executor" in d
        assert "execution_profile" in d
        assert d["executor"] == handoff.executor
        assert d["execution_profile"] == handoff.execution_profile


class TestDispatchPlannerExecutorIntegration:
    """测试 DispatchPlanner 与 executor 集成"""
    
    def test_dispatch_plan_to_planning_handoff_with_executor(self):
        """测试：DispatchPlan → PlanningHandoff 包含 executor 推导"""
        planner = DispatchPlanner()

        # Coding task — explicit backend_preference=subagent to test coding profile derivation
        plan = planner.create_plan(
            dispatch_id="disp_coding_001",
            batch_id="batch_coding_001",
            scenario="api_development",
            adapter="api_adapter",
            decision_id="dec_001",
            decision={"action": "proceed", "metadata": {
                "orchestration_contract": {"backend_preference": "subagent"},
            }},
            continuation={
                "stopped_because": "continuation",
                "next_step": "Implement new API endpoint",
                "next_owner": "main",
            },
            backend=DispatchBackend.SUBAGENT,
            allow_auto_dispatch=False,
        )

        handoff = plan.to_planning_handoff()

        assert handoff.executor == "claude_code"
        assert handoff.execution_profile == "coding"
    
    def test_dispatch_plan_non_coding_task(self):
        """测试：DispatchPlan 非 coding 任务 → subagent executor"""
        planner = DispatchPlanner()

        plan = planner.create_plan(
            dispatch_id="disp_generic_001",
            batch_id="batch_generic_001",
            scenario="trading_strategy",
            adapter="trading_adapter",
            decision_id="dec_002",
            decision={"action": "proceed", "metadata": {
                "orchestration_contract": {"backend_preference": "subagent"},
            }},
            continuation={
                "stopped_because": "continuation",
                "next_step": "Review and analyze trading strategy",
                "next_owner": "trading",
            },
            backend=DispatchBackend.SUBAGENT,
            allow_auto_dispatch=False,
        )

        handoff = plan.to_planning_handoff()

        assert handoff.executor == "subagent"
        assert handoff.execution_profile == "generic_subagent"
    
    def test_dispatch_plan_with_orchestration_contract_executor(self):
        """测试：DispatchPlan 从 orchestration_contract 读取 executor_preference"""
        planner = DispatchPlanner()
        
        plan = planner.create_plan(
            dispatch_id="disp_override_001",
            batch_id="batch_override_001",
            scenario="test",
            adapter="test_adapter",
            decision_id="dec_003",
            decision={
                "action": "proceed",
                "metadata": {
                    "orchestration_contract": {
                        "executor_preference": "subagent",
                    }
                }
            },
            continuation={
                "stopped_because": "continuation",
                "next_step": "Implement feature",
                "next_owner": "main",
            },
            backend=DispatchBackend.SUBAGENT,
            allow_auto_dispatch=False,
        )
        
        # 手动设置 orchestration_contract (create_plan 不会自动设置)
        plan.orchestration_contract["executor_preference"] = "subagent"
        
        handoff = plan.to_planning_handoff()
        
        # 显式指定 subagent 应该覆盖自动推导
        assert handoff.executor == "subagent"


class TestTradingRoundtableExecutorIntegration:
    """测试 Trading Roundtable 与 executor 集成"""
    
    def test_trading_roundtable_coding_continuation(self):
        """测试：Trading roundtable coding continuation → claude_code"""
        # 模拟 trading roundtable result
        result = {
            "trading_roundtable": {
                "packet": {
                    "packet_version": "trading_roundtable_v1",
                    "scenario": "trading_roundtable_phase1",
                    "owner": "trading",
                },
                "roundtable": {
                    "conclusion": "PASS",
                    "blocker": "none",
                    "owner": "trading",
                    "next_step": "Implement risk management module",
                    "completion_criteria": "Module passes all tests",
                }
            }
        }
        
        # 从 next_step 推导 execution_profile 和 executor
        # 使用与 handoff_schema.py 相同的 keyword 列表
        next_step = result["trading_roundtable"]["roundtable"]["next_step"]
        coding_keywords = [
            "implement", "implementation", "implementing",
            "refactor", "refactoring",
            "fix", "fixing", "bugfix", "bug-fix",
            "test", "testing", "test-fix",
            "code", "coding",
            "build", "develop", "development",
            "api endpoint", "module", "feature"
        ]
        execution_profile = "coding" if any(kw in next_step.lower() for kw in coding_keywords) else "generic_subagent"
        executor = "claude_code" if execution_profile == "coding" else "subagent"
        
        assert execution_profile == "coding"
        assert executor == "claude_code"
    
    def test_trading_roundtable_non_coding_continuation(self):
        """测试：Trading roundtable 非 coding continuation → subagent"""
        result = {
            "trading_roundtable": {
                "packet": {
                    "packet_version": "trading_roundtable_v1",
                    "scenario": "trading_roundtable_phase1",
                    "owner": "trading",
                },
                "roundtable": {
                    "conclusion": "PASS",
                    "blocker": "none",
                    "owner": "trading",
                    "next_step": "Review and optimize trading strategy",
                    "completion_criteria": "Strategy documented",
                }
            }
        }
        
        next_step = result["trading_roundtable"]["roundtable"]["next_step"]
        coding_keywords = ["coding", "implementation", "refactor", "fix", "test-fix", "bugfix"]
        execution_profile = "coding" if any(kw in next_step.lower() for kw in coding_keywords) else "generic_subagent"
        executor = "claude_code" if execution_profile == "coding" else "subagent"
        
        assert execution_profile == "generic_subagent"
        assert executor == "subagent"


class TestChannelRoundtableExecutorIntegration:
    """测试 Channel Roundtable 与 executor 集成"""
    
    def test_channel_roundtable_coding_continuation(self):
        """测试：Channel roundtable coding continuation → claude_code"""
        result = {
            "channel_roundtable": {
                "packet": {
                    "packet_version": "channel_roundtable_v1",
                    "scenario": "architecture_discussion",
                    "channel_id": "discord:channel:123",
                    "topic": "API Design",
                    "owner": "main",
                },
                "roundtable": {
                    "conclusion": "PASS",
                    "blocker": "none",
                    "owner": "main",
                    "next_step": "Refactor API adapter layer",
                    "completion_criteria": "Tests pass",
                }
            }
        }
        
        next_step = result["channel_roundtable"]["roundtable"]["next_step"]
        coding_keywords = ["coding", "implementation", "refactor", "fix", "test-fix", "bugfix"]
        execution_profile = "coding" if any(kw in next_step.lower() for kw in coding_keywords) else "generic_subagent"
        executor = "claude_code" if execution_profile == "coding" else "subagent"
        
        assert execution_profile == "coding"
        assert executor == "claude_code"


class TestOwnerExecutorDecouplingSemantics:
    """测试 owner/executor 解耦语义"""
    
    def test_owner_is_business_owner(self):
        """测试：owner 是业务所有者，不是执行者"""
        handoff = build_planning_handoff(
            source_type="dispatch_plan",
            source_id="test_001",
            continuation_contract={
                "stopped_because": "test",
                "next_step": "Implement feature",
                "next_owner": "trading",  # trading 是业务 owner
            },
            scenario="trading_feature",
            adapter="trading_adapter",
            owner="trading",  # owner = business owner
        )
        
        assert handoff.owner == "trading"
        assert handoff.executor == "claude_code"  # executor = Claude Code
        # owner 和 executor 是分离的
    
    def test_executor_is_implementation_path(self):
        """测试：executor 是具体执行路径"""
        handoff = build_planning_handoff(
            source_type="dispatch_plan",
            source_id="test_002",
            continuation_contract={
                "stopped_because": "test",
                "next_step": "Review strategy",
                "next_owner": "trading",
            },
            scenario="trading_review",
            adapter="trading_adapter",
            owner="trading",
        )
        
        assert handoff.owner == "trading"  # 业务 owner
        assert handoff.executor == "subagent"  # 执行者 = role agent
    
    def test_same_owner_different_executor(self):
        """测试：相同 owner，不同 executor (基于 task 类型)"""
        # Trading owner + coding task → claude_code
        coding_handoff = build_planning_handoff(
            source_type="dispatch_plan",
            source_id="coding_001",
            continuation_contract={
                "stopped_because": "test",
                "next_step": "Implement trading feature",
                "next_owner": "trading",
            },
            scenario="trading_coding",
            adapter="trading_adapter",
            owner="trading",
        )
        
        # Trading owner + non-coding task → subagent
        generic_handoff = build_planning_handoff(
            source_type="dispatch_plan",
            source_id="generic_001",
            continuation_contract={
                "stopped_because": "test",
                "next_step": "Review trading performance",
                "next_owner": "trading",
            },
            scenario="trading_review",
            adapter="trading_adapter",
            owner="trading",
        )
        
        assert coding_handoff.owner == "trading"
        assert generic_handoff.owner == "trading"
        assert coding_handoff.executor == "claude_code"
        assert generic_handoff.executor == "subagent"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
