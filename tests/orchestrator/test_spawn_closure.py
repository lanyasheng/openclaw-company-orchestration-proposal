#!/usr/bin/env python3
"""
test_spawn_closure.py — Tests for Universal Partial-Completion Continuation Framework v4

测试覆盖：
1. Happy path: dispatch artifact -> spawn closure artifact
2. Duplicate dispatch 不重复 emit
3. Missing payload / blocked path 不 emit
4. Trading 场景具体 spawn closure 输出
"""

import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture(autouse=True)
def isolated_spawn_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """为每个测试提供隔离的 spawn closure 目录"""
    spawn_dir = tmp_path / "spawn_closures"
    monkeypatch.setenv("OPENCLAW_SPAWN_CLOSURE_DIR", str(spawn_dir))
    # 强制重新加载模块以使用新的环境变量
    import importlib
    import spawn_closure
    importlib.reload(spawn_closure)
    yield spawn_dir


# 添加 runtime/orchestrator 到路径
# 使用 resolve() 以正确处理通过 symlink 访问的情况
RUNTIME_PATH = Path(__file__).resolve().parent.parent.parent / "runtime" / "orchestrator"
sys.path.insert(0, str(RUNTIME_PATH))

from spawn_closure import (
    SpawnStatus,
    SpawnPolicy,
    SpawnClosureArtifact,
    SpawnClosureKernel,
    create_spawn_closure,
    emit_spawn_closure,
    list_spawn_closures,
    get_spawn_closure,
    _generate_dedupe_key,
    _is_duplicate_spawn,
    _record_spawn_dedupe,
    _load_spawn_index,
    SPAWN_CLOSURE_VERSION,
)

from auto_dispatch import (
    DispatchArtifact,
    DispatchStatus,
)


class TestSpawnPolicy:
    """测试 SpawnPolicy"""
    
    def test_default_policy(self):
        """测试默认 policy"""
        policy = SpawnPolicy()
        
        assert policy.scenario_allowlist == ["trading_roundtable_phase1"]
        assert policy.require_dispatch_status == "dispatched"
        assert policy.require_execution_intent is True
        assert policy.prevent_duplicate is True
        assert policy.allow_limited_emission is True
    
    def test_policy_to_dict(self):
        """测试 policy 序列化"""
        policy = SpawnPolicy(
            scenario_allowlist=["trading_roundtable_phase1", "channel_roundtable"],
            require_dispatch_status="dispatched",
            require_execution_intent=False,
        )
        
        d = policy.to_dict()
        assert d["scenario_allowlist"] == ["trading_roundtable_phase1", "channel_roundtable"]
        assert d["require_dispatch_status"] == "dispatched"
        assert d["require_execution_intent"] is False
    
    def test_policy_from_dict(self):
        """测试 policy 反序列化"""
        data = {
            "scenario_allowlist": ["test_scenario"],
            "require_dispatch_status": "blocked",
            "require_execution_intent": False,
            "prevent_duplicate": False,
        }
        
        policy = SpawnPolicy.from_dict(data)
        assert policy.scenario_allowlist == ["test_scenario"]
        assert policy.require_dispatch_status == "blocked"
        assert policy.require_execution_intent is False
        assert policy.prevent_duplicate is False


class TestSpawnClosureArtifact:
    """测试 SpawnClosureArtifact"""
    
    def test_artifact_creation(self):
        """测试 artifact 创建"""
        artifact = SpawnClosureArtifact(
            spawn_id="spawn_test123",
            dispatch_id="dispatch_test123",
            registration_id="reg_test123",
            task_id="task_test123",
            spawn_status="ready",
            spawn_reason="Policy evaluation passed",
            spawn_target={
                "runtime": "subagent",
                "owner": "trading",
                "scenario": "trading_roundtable_phase1",
                "task_preview": "Test task",
                "cwd": "/test",
            },
            dedupe_key="dedupe:dispatch_test123:reg_test123:task_test123",
        )
        
        assert artifact.spawn_id == "spawn_test123"
        assert artifact.spawn_status == "ready"
        assert artifact.spawn_target["runtime"] == "subagent"
    
    def test_artifact_to_dict(self):
        """测试 artifact 序列化"""
        artifact = SpawnClosureArtifact(
            spawn_id="spawn_test123",
            dispatch_id="dispatch_test123",
            registration_id="reg_test123",
            task_id="task_test123",
            spawn_status="emitted",
            spawn_reason="Policy evaluation passed",
            spawn_target={"runtime": "subagent"},
            dedupe_key="dedupe:test",
            emitted_at="2026-03-22T12:00:00",
            spawn_command="sessions_spawn(...)",
            spawn_payload={"task": "test"},
        )
        
        d = artifact.to_dict()
        assert d["spawn_version"] == SPAWN_CLOSURE_VERSION
        assert d["spawn_id"] == "spawn_test123"
        assert d["spawn_status"] == "emitted"
        assert d["spawn_command"] == "sessions_spawn(...)"
        assert d["spawn_payload"] == {"task": "test"}
    
    def test_artifact_from_dict(self):
        """测试 artifact 反序列化"""
        data = {
            "spawn_version": SPAWN_CLOSURE_VERSION,
            "spawn_id": "spawn_test123",
            "dispatch_id": "dispatch_test123",
            "registration_id": "reg_test123",
            "task_id": "task_test123",
            "spawn_status": "blocked",
            "spawn_reason": "Scenario not in allowlist",
            "spawn_target": {"runtime": "subagent"},
            "dedupe_key": "dedupe:test",
        }
        
        artifact = SpawnClosureArtifact.from_dict(data)
        assert artifact.spawn_id == "spawn_test123"
        assert artifact.spawn_status == "blocked"
        assert artifact.spawn_reason == "Scenario not in allowlist"


class TestSpawnClosureKernel:
    """测试 SpawnClosureKernel"""
    
    def _create_test_dispatch(
        self,
        dispatch_status: DispatchStatus = "dispatched",
        scenario: str = "trading_roundtable_phase1",
        has_execution_intent: bool = True,
        suffix: str = "",
    ) -> DispatchArtifact:
        """创建测试 dispatch artifact"""
        exec_intent = None
        if has_execution_intent:
            exec_intent = {
                "recommended_spawn": {
                    "runtime": "subagent",
                    "task": "Test continuation task",
                    "cwd": "/test/workspace",
                    "metadata": {
                        "dispatch_id": f"dispatch_test{suffix}",
                        "registration_id": f"reg_test{suffix}",
                        "task_id": f"task_test{suffix}",
                        "source": "auto_dispatch_v3",
                    },
                },
                "dispatch_id": f"dispatch_test{suffix}",
                "registration_id": f"reg_test{suffix}",
            }
        
        return DispatchArtifact(
            dispatch_id=f"dispatch_test{suffix}",
            registration_id=f"reg_test{suffix}",
            task_id=f"task_test{suffix}",
            dispatch_status=dispatch_status,
            dispatch_reason="Policy evaluation passed",
            dispatch_time="2026-03-22T12:00:00",
            dispatch_target={
                "scenario": scenario,
                "adapter": "trading_roundtable",
                "batch_id": f"batch_test{suffix}",
                "owner": "trading",
            },
            execution_intent=exec_intent,
            policy_evaluation={"eligible": True},
        )
    
    def test_evaluate_policy_happy_path(self):
        """测试 happy path: policy evaluation 通过"""
        kernel = SpawnClosureKernel()
        dispatch = self._create_test_dispatch()
        
        evaluation = kernel.evaluate_policy(dispatch)
        
        assert evaluation["eligible"] is True
        assert len(evaluation["blocked_reasons"]) == 0
        assert len(evaluation["checks"]) > 0
        
        # 所有 checks 应该通过
        for check in evaluation["checks"]:
            assert check["passed"] is True, f"Check {check['name']} failed: {check}"
    
    def test_evaluate_policy_blocked_dispatch_status(self):
        """测试 blocked: dispatch status 不符合要求"""
        kernel = SpawnClosureKernel()
        dispatch = self._create_test_dispatch(dispatch_status="blocked")
        
        evaluation = kernel.evaluate_policy(dispatch)
        
        assert evaluation["eligible"] is False
        assert any("Dispatch status" in reason for reason in evaluation["blocked_reasons"])
    
    def test_evaluate_policy_blocked_missing_execution_intent(self):
        """测试 blocked: missing execution_intent"""
        kernel = SpawnClosureKernel()
        dispatch = self._create_test_dispatch(has_execution_intent=False)
        
        evaluation = kernel.evaluate_policy(dispatch)
        
        assert evaluation["eligible"] is False
        assert any("Missing execution_intent" in reason for reason in evaluation["blocked_reasons"])
    
    def test_evaluate_policy_blocked_scenario_not_allowed(self):
        """测试 blocked: scenario 不在白名单"""
        kernel = SpawnClosureKernel()
        dispatch = self._create_test_dispatch(scenario="unknown_scenario")
        
        evaluation = kernel.evaluate_policy(dispatch)
        
        assert evaluation["eligible"] is False
        assert any("not in allowlist" in reason for reason in evaluation["blocked_reasons"])
    
    def test_create_spawn_closure_happy_path(self):
        """测试 happy path: 创建 spawn closure"""
        kernel = SpawnClosureKernel()
        dispatch = self._create_test_dispatch()
        policy_evaluation = kernel.evaluate_policy(dispatch)
        
        artifact = kernel.create_spawn_closure(dispatch, policy_evaluation)
        
        assert artifact.spawn_status == "ready"
        assert artifact.spawn_target["runtime"] == "subagent"
        assert artifact.spawn_target["scenario"] == "trading_roundtable_phase1"
        assert artifact.spawn_command is not None
        assert artifact.spawn_payload is not None
        assert "sessions_spawn" in artifact.spawn_command
    
    def test_create_spawn_closure_blocked(self):
        """测试 blocked: 创建 blocked 状态的 spawn closure"""
        kernel = SpawnClosureKernel()
        dispatch = self._create_test_dispatch(scenario="unknown_scenario")
        policy_evaluation = kernel.evaluate_policy(dispatch)
        
        artifact = kernel.create_spawn_closure(dispatch, policy_evaluation)
        
        assert artifact.spawn_status == "blocked"
        assert "not in allowlist" in artifact.spawn_reason
        assert artifact.spawn_command is None
        assert artifact.spawn_payload is None
    
    def test_emit_spawn_closure_records_dedupe(self):
        """测试 emit: 记录 dedupe"""
        kernel = SpawnClosureKernel()
        dispatch = self._create_test_dispatch()
        
        # 第一次 emit
        artifact1 = kernel.emit_spawn_closure(dispatch)
        
        assert artifact1.spawn_status == "emitted"
        assert artifact1.emitted_at is not None
        
        # 检查 dedupe key 已记录
        assert _is_duplicate_spawn(artifact1.dedupe_key) is True
        
        # 第二次 emit（同一 dispatch）
        artifact2 = kernel.emit_spawn_closure(dispatch)
        
        assert artifact2.spawn_status == "blocked"
        assert "Duplicate spawn" in artifact2.spawn_reason
    
    def test_emit_spawn_closure_writes_file(self):
        """测试 emit: 写入文件"""
        kernel = SpawnClosureKernel()
        dispatch = self._create_test_dispatch(suffix="_writes_file")
        
        artifact = kernel.emit_spawn_closure(dispatch)
        
        # 检查文件存在
        from spawn_closure import _spawn_closure_file
        spawn_file = _spawn_closure_file(artifact.spawn_id)
        assert spawn_file.exists()
        
        # 检查文件内容
        with open(spawn_file, "r") as f:
            data = json.load(f)
        assert data["spawn_id"] == artifact.spawn_id
        assert data["spawn_status"] == "emitted"


class TestDuplicatePrevention:
    """测试去重/防重复发起"""
    
    def _create_test_dispatch(
        self,
        suffix: str = "",
    ) -> DispatchArtifact:
        """创建测试 dispatch artifact"""
        return DispatchArtifact(
            dispatch_id=f"dispatch_dedupe{suffix}",
            registration_id=f"reg_dedupe{suffix}",
            task_id=f"task_dedupe{suffix}",
            dispatch_status="dispatched",
            dispatch_reason="Policy evaluation passed",
            dispatch_time="2026-03-22T12:00:00",
            dispatch_target={
                "scenario": "trading_roundtable_phase1",
                "adapter": "trading_roundtable",
                "batch_id": f"batch_dedupe{suffix}",
                "owner": "trading",
            },
            execution_intent={
                "recommended_spawn": {
                    "runtime": "subagent",
                    "task": "Test task",
                    "cwd": "/test",
                    "metadata": {},
                },
                "dispatch_id": f"dispatch_dedupe{suffix}",
                "registration_id": f"reg_dedupe{suffix}",
            },
        )
    
    def test_dedupe_key_generation(self):
        """测试 dedupe key 生成"""
        key = _generate_dedupe_key("dispatch_123", "reg_456", "task_789")
        assert key == "dedupe:dispatch_123:reg_456:task_789"
    
    def test_duplicate_prevention_same_dispatch(self):
        """测试同一 dispatch 不重复 emit"""
        kernel = SpawnClosureKernel()
        dispatch = self._create_test_dispatch(suffix="_same")
        
        # 第一次 emit
        artifact1 = kernel.emit_spawn_closure(dispatch)
        assert artifact1.spawn_status == "emitted"
        
        # 第二次 emit（同一 dispatch）
        artifact2 = kernel.emit_spawn_closure(dispatch)
        assert artifact2.spawn_status == "blocked"
        assert "Duplicate spawn" in artifact2.spawn_reason


class TestTradingScenario:
    """测试 Trading 场景"""
    
    def _create_trading_dispatch(self, suffix: str = "") -> DispatchArtifact:
        """创建 trading 场景 dispatch"""
        return DispatchArtifact(
            dispatch_id=f"dispatch_trading{suffix}",
            registration_id=f"reg_trading{suffix}",
            task_id=f"task_trading{suffix}",
            dispatch_status="dispatched",
            dispatch_reason="Policy evaluation passed",
            dispatch_time="2026-03-22T12:00:00",
            dispatch_target={
                "scenario": "trading_roundtable_phase1",
                "adapter": "trading_roundtable",
                "batch_id": f"batch_trading{suffix}",
                "owner": "trading",
            },
            execution_intent={
                "recommended_spawn": {
                    "runtime": "subagent",
                    "task": "Trading roundtable continuation: analyze remaining scope",
                    "cwd": "/Users/study/.openclaw/workspace",
                    "metadata": {
                        "dispatch_id": f"dispatch_trading{suffix}",
                        "registration_id": f"reg_trading{suffix}",
                        "task_id": f"task_trading{suffix}",
                        "source": "auto_dispatch_v3",
                        "trading_context": {
                            "batch_id": f"batch_trading{suffix}",
                            "phase": "phase1_continuation",
                            "adapter": "trading_roundtable",
                        },
                    },
                },
                "dispatch_id": f"dispatch_trading{suffix}",
                "registration_id": f"reg_trading{suffix}",
            },
            policy_evaluation={"eligible": True},
            metadata={
                "truth_anchor": {
                    "anchor_type": "batch_id",
                    "anchor_value": f"batch_trading{suffix}",
                },
            },
        )
    
    @patch('spawn_closure.get_dispatch')
    @patch('spawn_closure.DISPATCH_DIR')
    def test_trading_spawn_closure_happy_path(self, mock_dispatch_dir, mock_get_dispatch):
        """测试 trading 场景 happy path"""
        from pathlib import Path
        mock_dispatch_dir.__truediv__ = lambda self, key: Path(tempfile.gettempdir()) / key
        
        dispatch = self._create_trading_dispatch()
        mock_get_dispatch.return_value = dispatch
        
        artifact = emit_spawn_closure(dispatch.dispatch_id)
        
        assert artifact.spawn_status == "emitted"
        assert artifact.spawn_target["scenario"] == "trading_roundtable_phase1"
        assert artifact.spawn_target["runtime"] == "subagent"
        assert artifact.spawn_payload is not None
        assert "trading_context" in artifact.spawn_payload.get("metadata", {})
        assert artifact.spawn_command is not None
        assert "sessions_spawn" in artifact.spawn_command
    
    def test_trading_spawn_closure_has_trading_metadata(self):
        """测试 trading spawn closure 包含 trading 特定 metadata"""
        kernel = SpawnClosureKernel()
        dispatch = self._create_trading_dispatch(suffix="_metadata")
        policy_evaluation = kernel.evaluate_policy(dispatch)
        
        artifact = kernel.create_spawn_closure(dispatch, policy_evaluation)
        
        assert artifact.spawn_status == "ready"
        assert artifact.metadata.get("truth_anchor") is not None
        assert artifact.spawn_target["owner"] == "trading"
        assert artifact.spawn_target["scenario"] == "trading_roundtable_phase1"


class TestPolicyGuards:
    """测试 policy / guard"""
    
    def test_blocked_dispatch_cannot_emit(self):
        """测试 blocked dispatch 不能 emit"""
        kernel = SpawnClosureKernel()
        dispatch = DispatchArtifact(
            dispatch_id="dispatch_blocked",
            registration_id="reg_blocked",
            task_id="task_blocked",
            dispatch_status="blocked",
            dispatch_reason="Policy evaluation failed",
            dispatch_time="2026-03-22T12:00:00",
            dispatch_target={"scenario": "trading_roundtable_phase1"},
            execution_intent=None,
        )
        
        artifact = kernel.emit_spawn_closure(dispatch)
        
        assert artifact.spawn_status == "blocked"
        assert artifact.spawn_command is None
        assert artifact.spawn_payload is None
    
    def test_missing_payload_cannot_emit(self):
        """测试 missing payload 不能 emit"""
        kernel = SpawnClosureKernel()
        dispatch = DispatchArtifact(
            dispatch_id="dispatch_missing",
            registration_id="reg_missing",
            task_id="task_missing",
            dispatch_status="dispatched",
            dispatch_reason="OK",
            dispatch_time="2026-03-22T12:00:00",
            dispatch_target={"scenario": "trading_roundtable_phase1"},
            execution_intent={},  # 空的 execution_intent
        )
        
        artifact = kernel.emit_spawn_closure(dispatch)
        
        assert artifact.spawn_status == "blocked"
        assert "Missing recommended_spawn" in artifact.spawn_reason
    
    def test_non_whitelist_scenario_cannot_emit(self):
        """测试非白名单场景不能 emit"""
        kernel = SpawnClosureKernel()
        dispatch = DispatchArtifact(
            dispatch_id="dispatch_unknown",
            registration_id="reg_unknown",
            task_id="task_unknown",
            dispatch_status="dispatched",
            dispatch_reason="OK",
            dispatch_time="2026-03-22T12:00:00",
            dispatch_target={"scenario": "unknown_scenario"},
            execution_intent={"recommended_spawn": {"runtime": "subagent"}},
        )
        
        artifact = kernel.emit_spawn_closure(dispatch)
        
        assert artifact.spawn_status == "blocked"
        assert "not in allowlist" in artifact.spawn_reason


class TestListAndGet:
    """测试 list 和 get 函数"""
    
    def test_list_spawn_closures(self):
        """测试列出 spawn closures"""
        # 先创建一个
        kernel = SpawnClosureKernel()
        dispatch = DispatchArtifact(
            dispatch_id="dispatch_list_test",
            registration_id="reg_list_test",
            task_id="task_list_test",
            dispatch_status="dispatched",
            dispatch_reason="OK",
            dispatch_time="2026-03-22T12:00:00",
            dispatch_target={"scenario": "trading_roundtable_phase1"},
            execution_intent={"recommended_spawn": {"runtime": "subagent"}},
        )
        
        artifact = kernel.emit_spawn_closure(dispatch)
        
        # 列出
        spawns = list_spawn_closures(dispatch_id=artifact.dispatch_id)
        
        assert len(spawns) >= 1
        found = False
        for spawn in spawns:
            if spawn.spawn_id == artifact.spawn_id:
                found = True
                break
        assert found
    
    def test_get_spawn_closure(self):
        """测试获取单个 spawn closure"""
        kernel = SpawnClosureKernel()
        dispatch = DispatchArtifact(
            dispatch_id="dispatch_get_test",
            registration_id="reg_get_test",
            task_id="task_get_test",
            dispatch_status="dispatched",
            dispatch_reason="OK",
            dispatch_time="2026-03-22T12:00:00",
            dispatch_target={"scenario": "trading_roundtable_phase1"},
            execution_intent={"recommended_spawn": {"runtime": "subagent"}},
        )
        
        artifact = kernel.emit_spawn_closure(dispatch)
        
        # 获取
        retrieved = get_spawn_closure(artifact.spawn_id)
        
        assert retrieved is not None
        assert retrieved.spawn_id == artifact.spawn_id
        assert retrieved.dispatch_id == artifact.dispatch_id
    
    def test_get_spawn_closure_not_found(self):
        """测试获取不存在的 spawn closure"""
        retrieved = get_spawn_closure("spawn_nonexistent")
        assert retrieved is None


# 运行测试
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
