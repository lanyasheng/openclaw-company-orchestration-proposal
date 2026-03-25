#!/usr/bin/env python3
"""
test_auto_dispatch_execution.py — Tests for P0-5 Batch C: Auto-Dispatch Execution Cutover

测试 auto-dispatch 与 SubagentExecutor 集成，确保：
1. DispatchExecutor 能正确集成 SubagentExecutor
2. Dispatch intent 能实际启动 subagent 执行
3. Artifact 元数据正确记录 subagent_task_id
4. 回归测试：保持原有 dispatch artifact 生成逻辑不变

这是 P0-5 Batch C 的测试覆盖。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

import pytest

# Add orchestrator to path
ORCHESTRATOR_DIR = Path(__file__).resolve().parents[2] / "orchestrator"
if str(ORCHESTRATOR_DIR) not in sys.path:
    sys.path.insert(0, str(ORCHESTRATOR_DIR))

from auto_dispatch import (
    DispatchExecutor,
    AutoDispatchSelector,
    DispatchPolicy,
    DispatchArtifact,
    execute_dispatch,
    DISPATCH_ARTIFACT_VERSION,
)

from task_registration import (
    TaskRegistrationRecord,
    TruthAnchor,
    register_task,
    get_registration,
)

# P0-5 Batch C: Import SubagentExecutor for integration tests
from subagent_executor import (
    SubagentExecutor,
    SubagentConfig,
    TERMINAL_STATES,
)


@pytest.fixture(autouse=True)
def clean_test_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """使用临时目录，避免污染真实数据"""
    import importlib
    import auto_dispatch
    import task_registration
    
    # 设置临时目录
    DISPATCH_DIR = tmp_path / "dispatches"
    DISPATCH_DIR.mkdir(parents=True, exist_ok=True)
    auto_dispatch.DISPATCH_DIR = DISPATCH_DIR
    
    REGISTRATION_DIR = tmp_path / "registrations"
    REGISTRATION_DIR.mkdir(parents=True, exist_ok=True)
    task_registration.REGISTRATION_DIR = REGISTRATION_DIR
    
    yield
    
    # 清理
    import shutil
    if tmp_path.exists():
        shutil.rmtree(tmp_path)


class TestDispatchExecutorIntegration:
    """测试 DispatchExecutor 与 SubagentExecutor 集成"""
    
    def test_dispatch_executor_has_subagent_executor_import(self):
        """测试 SubagentExecutor 已正确导入"""
        # 验证模块已导入
        from auto_dispatch import SubagentExecutor as ImportedExecutor
        assert ImportedExecutor is not None
        
        # 验证 SubagentConfig 也已导入
        from auto_dispatch import SubagentConfig as ImportedConfig
        assert ImportedConfig is not None
    
    def test_execute_dispatch_generates_artifact(self):
        """测试 execute_dispatch 生成 artifact（回归测试）"""
        # 创建测试 record
        record = TaskRegistrationRecord(
            registration_id="reg_test001",
            task_id="task_test001",
            batch_id="batch_001",
            owner="trading",
            registration_status="registered",
            registration_reason="Test registration",
            status="pending",
            source_closeout=None,
            truth_anchor=TruthAnchor(
                anchor_type="batch_id",
                anchor_value="batch_001",
            ),
            proposed_task={
                "task_type": "continuation",
                "title": "Test continuation task",
                "description": "Execute continuation for batch_001",
            },
            metadata={
                "adapter": "trading_adapter",
                "scenario": "trading_roundtable_phase1",
                "ready_for_auto_dispatch": True,
            },
        )
        
        # 执行 dispatch
        executor = DispatchExecutor()
        artifact = executor.execute_dispatch(record)
        
        # 验证 artifact 生成
        assert artifact.dispatch_id.startswith("dispatch_")
        assert artifact.registration_id == "reg_test001"
        assert artifact.task_id == "task_test001"
        assert artifact.dispatch_status == "dispatched"
        assert artifact.dispatch_time is not None
        
        # 验证 execution_intent 生成
        assert artifact.execution_intent is not None
        assert "recommended_spawn" in artifact.execution_intent
        
        # 验证 dispatch_target
        assert artifact.dispatch_target["scenario"] == "trading_roundtable_phase1"
        assert artifact.dispatch_target["batch_id"] == "batch_001"
        assert artifact.dispatch_target["owner"] == "trading"
    
    def test_execute_dispatch_records_subagent_task_id(self):
        """测试 execute_dispatch 记录 subagent_task_id（P0-5 Batch C 新增）"""
        # 创建测试 record
        record = TaskRegistrationRecord(
            registration_id="reg_test002",
            task_id="task_test002",
            batch_id="batch_002",
            owner="trading",
            registration_status="registered",
            registration_reason="Test registration",
            status="pending",
            source_closeout=None,
            truth_anchor=TruthAnchor(
                anchor_type="batch_id",
                anchor_value="batch_002",
            ),
            proposed_task={
                "task_type": "continuation",
                "title": "Test continuation with execution",
                "description": "Execute continuation with SubagentExecutor",
            },
            metadata={
                "adapter": "trading_adapter",
                "scenario": "trading_roundtable_phase1",
                "ready_for_auto_dispatch": True,
            },
        )
        
        # 执行 dispatch
        executor = DispatchExecutor()
        artifact = executor.execute_dispatch(record)
        
        # P0-5 Batch C: 验证 subagent_task_id 已记录
        assert artifact.dispatch_status == "dispatched"
        assert "subagent_task_id" in artifact.metadata
        assert artifact.metadata["subagent_task_id"].startswith("task_")
        assert artifact.metadata.get("execution_started") is True
        
        # 验证 execution_intent 结构
        assert artifact.execution_intent is not None
        recommended_spawn = artifact.execution_intent["recommended_spawn"]
        assert recommended_spawn["runtime"] == "subagent"
        assert "dispatch_id" in recommended_spawn["metadata"]
        assert recommended_spawn["metadata"]["dispatch_id"] == artifact.dispatch_id
    
    def test_execute_dispatch_blocked_no_subagent(self):
        """测试 blocked dispatch 不启动 subagent"""
        # 创建 blocked record（scenario 不在 allowlist）
        record = TaskRegistrationRecord(
            registration_id="reg_test003",
            task_id="task_test003",
            batch_id="batch_003",
            owner="generic",
            registration_status="registered",
            registration_reason="Test registration",
            status="pending",
            source_closeout=None,
            truth_anchor=TruthAnchor(
                anchor_type="batch_id",
                anchor_value="batch_003",
            ),
            proposed_task={
                "task_type": "continuation",
                "title": "Blocked task",
                "description": "This task should be blocked",
            },
            metadata={
                "scenario": "unknown_scenario",  # 不在 allowlist
                "ready_for_auto_dispatch": True,
            },
        )
        
        # 执行 dispatch
        executor = DispatchExecutor()
        artifact = executor.execute_dispatch(record)
        
        # 验证被 blocked
        assert artifact.dispatch_status == "blocked"
        assert "subagent_task_id" not in artifact.metadata
        assert artifact.metadata.get("execution_started") is None
    
    def test_execute_dispatch_policy_evaluation_unchanged(self):
        """测试 policy 评估逻辑保持不变（回归测试）"""
        # 创建测试 record
        record = TaskRegistrationRecord(
            registration_id="reg_test004",
            task_id="task_test004",
            batch_id="batch_004",
            owner="trading",
            registration_status="registered",
            registration_reason="Test registration",
            status="pending",
            source_closeout=None,
            truth_anchor=TruthAnchor(
                anchor_type="batch_id",
                anchor_value="batch_004",
            ),
            proposed_task={
                "task_type": "continuation",
                "title": "Policy test",
                "description": "Test policy evaluation",
            },
            metadata={
                "adapter": "trading_adapter",
                "scenario": "trading_roundtable_phase1",
                "ready_for_auto_dispatch": True,
            },
        )
        
        # 手动评估 policy
        selector = AutoDispatchSelector()
        policy_eval = selector.evaluate_policy(record)
        
        # 验证 policy 评估结果
        assert policy_eval["eligible"] is True
        assert len(policy_eval["blocked_reasons"]) == 0
        
        # 验证 checks
        check_names = [check["name"] for check in policy_eval["checks"]]
        assert "scenario_allowlist" in check_names
        assert "truth_anchor_required" in check_names
        assert "registration_status" in check_names
        assert "task_status_not_blocked" in check_names
        assert "ready_for_auto_dispatch" in check_names
        assert "prevent_duplicate_dispatch" in check_names


class TestSubagentExecutorIntegration:
    """测试 SubagentExecutor 实际集成"""
    
    def test_subagent_config_creation_from_execution_intent(self):
        """测试从 execution_intent 创建 SubagentConfig"""
        # 模拟 execution_intent
        execution_intent = {
            "recommended_spawn": {
                "task": "Test task description",
                "runtime": "subagent",
                "cwd": "/tmp/test",
                "metadata": {
                    "dispatch_id": "dispatch_test123",
                    "registration_id": "reg_test123",
                    "task_id": "task_test123",
                    "timeout_seconds": 900,
                },
            }
        }
        
        recommended_spawn = execution_intent["recommended_spawn"]
        
        # 创建 SubagentConfig
        config = SubagentConfig(
            label="dispatch-test123",
            runtime="subagent",
            timeout_seconds=recommended_spawn["metadata"].get("timeout_seconds", 900),
            cwd=recommended_spawn.get("cwd", "/tmp"),
            metadata={
                **recommended_spawn["metadata"],
                "source": "auto_dispatch",
            },
        )
        
        # 验证配置
        assert config.label == "dispatch-test123"
        assert config.runtime == "subagent"
        assert config.timeout_seconds == 900
        assert config.cwd == "/tmp/test"
        assert config.metadata["dispatch_id"] == "dispatch_test123"
        assert config.metadata["source"] == "auto_dispatch"
    
    def test_subagent_executor_instantiation(self):
        """测试 SubagentExecutor 可实例化"""
        config = SubagentConfig(
            label="test-label",
            runtime="subagent",
            timeout_seconds=300,
        )
        
        executor = SubagentExecutor(config=config, cwd="/tmp")
        
        assert executor is not None
        assert executor.config.label == "test-label"
        assert executor.config.timeout_seconds == 300


class TestDispatchArtifactMetadata:
    """测试 DispatchArtifact 元数据完整性"""
    
    def test_artifact_metadata_contains_linkage(self):
        """测试 artifact 元数据包含完整 linkage"""
        record = TaskRegistrationRecord(
            registration_id="reg_linkage001",
            task_id="task_linkage001",
            batch_id="batch_linkage001",
            owner="trading",
            registration_status="registered",
            registration_reason="Test registration",
            status="pending",
            source_closeout=None,
            truth_anchor=TruthAnchor(
                anchor_type="batch_id",
                anchor_value="batch_linkage001",
            ),
            proposed_task={
                "task_type": "continuation",
                "title": "Linkage test",
                "description": "Test linkage completeness",
            },
            metadata={
                "adapter": "trading_adapter",
                "scenario": "trading_roundtable_phase1",
                "ready_for_auto_dispatch": True,
            },
        )
        
        executor = DispatchExecutor()
        artifact = executor.execute_dispatch(record)
        
        # 验证 linkage
        assert artifact.metadata["source_registration_status"] == "registered"
        assert artifact.metadata["source_task_status"] == "pending"
        assert artifact.metadata["truth_anchor"]["anchor_type"] == "batch_id"
        assert artifact.metadata["truth_anchor"]["anchor_value"] == "batch_linkage001"
        
        # P0-5 Batch C: 验证 execution linkage
        assert "subagent_task_id" in artifact.metadata
        assert artifact.metadata["execution_started"] is True
    
    def test_artifact_serialization_roundtrip(self):
        """测试 artifact 序列化/反序列化往返"""
        record = TaskRegistrationRecord(
            registration_id="reg_serial001",
            task_id="task_serial001",
            batch_id="batch_serial001",
            owner="trading",
            registration_status="registered",
            registration_reason="Test registration",
            status="pending",
            source_closeout=None,
            truth_anchor=TruthAnchor(
                anchor_type="batch_id",
                anchor_value="batch_serial001",
            ),
            proposed_task={
                "task_type": "continuation",
                "title": "Serialization test",
                "description": "Test artifact serialization",
            },
            metadata={
                "adapter": "trading_adapter",
                "scenario": "trading_roundtable_phase1",
                "ready_for_auto_dispatch": True,
            },
        )
        
        executor = DispatchExecutor()
        artifact = executor.execute_dispatch(record)
        
        # 序列化
        artifact_dict = artifact.to_dict()
        
        # 反序列化
        restored = DispatchArtifact.from_dict(artifact_dict)
        
        # 验证关键字段
        assert restored.dispatch_id == artifact.dispatch_id
        assert restored.registration_id == artifact.registration_id
        assert restored.dispatch_status == artifact.dispatch_status
        assert restored.execution_intent == artifact.execution_intent
        assert restored.metadata.get("subagent_task_id") == artifact.metadata.get("subagent_task_id")


class TestRegression:
    """回归测试：确保原有功能不受影响"""
    
    def test_dispatch_policy_allowlist_unchanged(self):
        """测试 dispatch policy allowlist 保持不变"""
        from auto_dispatch import DEFAULT_AUTO_DISPATCH_ALLOWED_SCENARIOS
        
        # 验证默认 allowlist 包含 trading_roundtable_phase1
        assert "trading_roundtable_phase1" in DEFAULT_AUTO_DISPATCH_ALLOWED_SCENARIOS
        
        # 验证可以自定义 allowlist
        custom_policy = DispatchPolicy(
            scenario_allowlist=["custom_scenario"]
        )
        assert custom_policy.scenario_allowlist == ["custom_scenario"]
    
    def test_dispatch_artifact_version_unchanged(self):
        """测试 dispatch artifact version 保持不变"""
        assert DISPATCH_ARTIFACT_VERSION == "auto_dispatch_v1"
    
    def test_convenience_functions_available(self):
        """测试便捷函数仍可访问"""
        from auto_dispatch import (
            select_ready_tasks,
            evaluate_dispatch_policy,
            generate_dispatch_artifact,
            execute_dispatch,
        )
        
        assert callable(select_ready_tasks)
        assert callable(evaluate_dispatch_policy)
        assert callable(generate_dispatch_artifact)
        assert callable(execute_dispatch)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
