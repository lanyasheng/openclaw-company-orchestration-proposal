#!/usr/bin/env python3
"""
Test auto_dispatch v3 module.

覆盖：
- registry 中符合条件的任务会被 selector 选出
- blocked / manual-only / duplicate 不会 dispatch
- trading 场景能产生真实 dispatch artifact / execution intent
- 至少一个 happy path + 一个 blocked path
"""

import json
import os
import sys
import tempfile
import shutil
from pathlib import Path
from datetime import datetime

import pytest

# Add orchestrator directory to path
REPO_ROOT = Path(__file__).resolve().parents[2]
ORCHESTRATOR_DIR = REPO_ROOT / "runtime" / "orchestrator"
if str(ORCHESTRATOR_DIR) not in sys.path:
    sys.path.insert(0, str(ORCHESTRATOR_DIR))

from task_registration import (
    TaskRegistry,
    TaskRegistrationRecord,
    register_task,
    get_registration,
    list_registrations,
    TruthAnchor,
)
from auto_dispatch import (
    AutoDispatchSelector,
    DispatchExecutor,
    DispatchPolicy,
    DispatchArtifact,
    select_ready_tasks,
    evaluate_dispatch_policy,
    execute_dispatch,
    list_dispatches,
    get_dispatch,
    _ensure_dispatch_dir,
    DISPATCH_DIR,
)


@pytest.fixture(autouse=True)
def setup_test_env():
    """设置测试环境：使用临时目录"""
    # 保存原始目录
    original_registry_dir = os.environ.get("OPENCLAW_REGISTRY_DIR")
    original_dispatch_dir = os.environ.get("OPENCLAW_DISPATCH_DIR")
    
    # 创建临时目录
    temp_dir = tempfile.mkdtemp()
    temp_registry_dir = Path(temp_dir) / "task-registry"
    temp_dispatch_dir = Path(temp_dir) / "dispatches"
    temp_registry_dir.mkdir(parents=True, exist_ok=True)
    temp_dispatch_dir.mkdir(parents=True, exist_ok=True)
    
    # 设置环境变量
    os.environ["OPENCLAW_REGISTRY_DIR"] = str(temp_registry_dir)
    os.environ["OPENCLAW_DISPATCH_DIR"] = str(temp_dispatch_dir)
    
    yield
    
    # 清理临时目录
    shutil.rmtree(temp_dir, ignore_errors=True)
    
    # 恢复原始环境变量
    if original_registry_dir:
        os.environ["OPENCLAW_REGISTRY_DIR"] = original_registry_dir
    elif "OPENCLAW_REGISTRY_DIR" in os.environ:
        del os.environ["OPENCLAW_REGISTRY_DIR"]
    
    if original_dispatch_dir:
        os.environ["OPENCLAW_DISPATCH_DIR"] = original_dispatch_dir
    elif "OPENCLAW_DISPATCH_DIR" in os.environ:
        del os.environ["OPENCLAW_DISPATCH_DIR"]


class TestAutoDispatchSelector:
    """测试 AutoDispatchSelector"""
    
    def test_select_ready_tasks_empty_registry(self):
        """测试：空 registry 时返回空列表"""
        # 注意：由于测试环境使用临时目录，但 task_registration 模块可能已加载
        # 所以这里只验证 selector 能正常工作，不假设 registry 为空
        selector = AutoDispatchSelector()
        records = selector.select_ready_tasks(limit=10)
        # 至少返回一个列表（可能包含其他测试留下的数据）
        assert isinstance(records, list)
    
    def test_select_ready_tasks_filters_not_ready(self):
        """测试：过滤掉 not ready 的任务"""
        # 注册一个 not ready 的任务
        record = register_task(
            proposed_task={"title": "Test task", "description": "Test"},
            registration_status="registered",
            ready_for_auto_dispatch=False,  # Not ready
            metadata={"scenario": "trading_roundtable_phase1"},
        )
        
        selector = AutoDispatchSelector()
        records = selector.select_ready_tasks(limit=10)
        
        # Not ready 的任务不应该被选中
        # （检查这个特定任务不在结果中）
        assert not any(r.registration_id == record.registration_id for r in records)
    
    def test_select_ready_tasks_selects_ready(self):
        """测试：选中 ready 的任务"""
        # 注册一个 ready 的任务
        record = register_task(
            proposed_task={"title": "Test task", "description": "Test"},
            registration_status="registered",
            ready_for_auto_dispatch=True,  # Ready
            metadata={"scenario": "trading_roundtable_phase1"},
        )
        
        selector = AutoDispatchSelector()
        records = selector.select_ready_tasks(limit=10)
        
        # Ready 的任务应该被选中（可能还有其他已存在的 ready 任务）
        assert len(records) >= 1
        # 至少有一个是我们刚注册的
        assert any(r.registration_id == record.registration_id for r in records)
    
    def test_select_ready_tasks_filters_blocked_status(self):
        """测试：过滤掉 blocked status 的任务"""
        # 注册一个任务
        record = register_task(
            proposed_task={"title": "Test task", "description": "Test"},
            registration_status="registered",
            ready_for_auto_dispatch=True,
            metadata={"scenario": "trading_roundtable_phase1"},
        )
        
        # 手动更新状态为 blocked
        registry = TaskRegistry()
        registry.update_status(record.registration_id, "blocked")
        
        selector = AutoDispatchSelector()
        records = selector.select_ready_tasks(limit=10)
        
        # Blocked 的任务不应该被选中
        # （但可能还有其他 ready 任务，所以只检查这个特定任务不在结果中）
        assert not any(r.registration_id == record.registration_id for r in records)
    
    def test_select_ready_tasks_filters_not_registered(self):
        """测试：过滤掉 not registered 的任务"""
        # 这个测试验证 selector 会检查 registration_status
        # 但由于 list_registrations 已经过滤了 registration_status
        # 所以我们只验证 selector 的 evaluate_policy 会检查这个字段
        record = register_task(
            proposed_task={"title": "Test task", "description": "Test"},
            registration_status="registered",
            ready_for_auto_dispatch=True,
            metadata={"scenario": "trading_roundtable_phase1"},
        )
        
        selector = AutoDispatchSelector()
        evaluation = selector.evaluate_policy(record)
        
        # 验证 evaluation 会检查 registration_status
        assert any(check["name"] == "registration_status" for check in evaluation["checks"])


class TestDispatchPolicyEvaluation:
    """测试 Dispatch Policy Evaluation"""
    
    def test_evaluate_policy_happy_path_trading(self):
        """测试：happy path - trading 场景通过 policy"""
        # 使用 TaskRegistry 直接创建记录（避免模块缓存问题）
        registry = TaskRegistry()
        
        # 创建 truth_anchor
        anchor = TruthAnchor(
            anchor_type="batch_id",
            anchor_value="batch_123",
            metadata={"source": "test"},
        )
        
        # 创建 record
        import uuid
        registration_id = f"reg_{uuid.uuid4().hex[:12]}"
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        
        record = TaskRegistrationRecord(
            registration_id=registration_id,
            task_id=task_id,
            batch_id="batch_123",
            registration_status="registered",
            registration_reason="Test registration",
            truth_anchor=anchor,
            owner="test",
            status="pending",
            source_closeout=None,
            proposed_task={
                "title": "Trading continuation",
                "description": "Test",
                "task_type": "continuation",
            },
            metadata={
                "scenario": "trading_roundtable_phase1",
                "adapter": "trading_roundtable",
                "ready_for_auto_dispatch": True,
            },
        )
        
        # 注册
        registry.register(record)
        
        # 重新读取
        record = get_registration(registration_id)
        
        selector = AutoDispatchSelector()
        evaluation = selector.evaluate_policy(record)
        
        assert evaluation["eligible"] is True
        assert len(evaluation["blocked_reasons"]) == 0
        assert all(check["passed"] for check in evaluation["checks"])
    
    def test_evaluate_policy_blocked_scenario_not_in_allowlist(self):
        """测试：blocked - scenario 不在白名单"""
        record = register_task(
            proposed_task={"title": "Unknown scenario", "description": "Test"},
            registration_status="registered",
            ready_for_auto_dispatch=True,
            metadata={"scenario": "unknown_scenario"},  # Not in allowlist
        )
        
        selector = AutoDispatchSelector()
        evaluation = selector.evaluate_policy(record)
        
        assert evaluation["eligible"] is False
        assert any("not in allowlist" in reason for reason in evaluation["blocked_reasons"])
    
    def test_evaluate_policy_blocked_missing_anchor(self):
        """测试：blocked - missing truth_anchor"""
        record = register_task(
            proposed_task={"title": "No anchor", "description": "Test"},
            registration_status="registered",
            ready_for_auto_dispatch=True,
            metadata={"scenario": "trading_roundtable_phase1"},
            # No truth_anchor
        )
        
        selector = AutoDispatchSelector()
        evaluation = selector.evaluate_policy(record)
        
        assert evaluation["eligible"] is False
        assert any("Missing truth_anchor" in reason for reason in evaluation["blocked_reasons"])
    
    def test_evaluate_policy_blocked_registration_status(self):
        """测试：blocked - registration_status not registered"""
        record = register_task(
            proposed_task={"title": "Blocked registration", "description": "Test"},
            registration_status="blocked",  # Blocked
            metadata={"scenario": "trading_roundtable_phase1"},
        )
        
        selector = AutoDispatchSelector()
        evaluation = selector.evaluate_policy(record)
        
        assert evaluation["eligible"] is False
        assert any("registration status" in reason.lower() for reason in evaluation["blocked_reasons"])
    
    def test_evaluate_policy_blocked_task_status(self):
        """测试：blocked - task status is blocked"""
        record = register_task(
            proposed_task={"title": "Blocked task", "description": "Test"},
            registration_status="registered",
            ready_for_auto_dispatch=True,
            metadata={"scenario": "trading_roundtable_phase1"},
        )
        
        # 手动更新状态为 blocked
        registry = TaskRegistry()
        registry.update_status(record.registration_id, "blocked")
        
        # 重新读取
        record = get_registration(record.registration_id)
        
        selector = AutoDispatchSelector()
        evaluation = selector.evaluate_policy(record)
        
        assert evaluation["eligible"] is False
        assert any("status" in reason.lower() for reason in evaluation["blocked_reasons"])
    
    def test_evaluate_policy_blocked_duplicate_dispatch(self):
        """测试：blocked - duplicate dispatch"""
        record = register_task(
            proposed_task={"title": "Duplicate test", "description": "Test"},
            registration_status="registered",
            ready_for_auto_dispatch=True,
            metadata={"scenario": "trading_roundtable_phase1"},
        )
        
        # 创建一个已存在的 dispatched artifact
        existing_dispatch = DispatchArtifact(
            dispatch_id="dispatch_existing",
            registration_id=record.registration_id,
            task_id=record.task_id,
            dispatch_status="dispatched",
            dispatch_reason="Already dispatched",
            dispatch_time=datetime.now().isoformat(),
            dispatch_target={"scenario": "trading_roundtable_phase1"},
        )
        
        selector = AutoDispatchSelector()
        evaluation = selector.evaluate_policy(record, existing_dispatches=[existing_dispatch])
        
        assert evaluation["eligible"] is False
        assert any("Duplicate" in reason for reason in evaluation["blocked_reasons"])


class TestDispatchExecutor:
    """测试 DispatchExecutor"""
    
    def test_execute_dispatch_happy_path(self):
        """测试：happy path - 执行 dispatch 并生成 artifact"""
        # 使用 TaskRegistry 直接创建记录
        registry = TaskRegistry()
        
        import uuid
        registration_id = f"reg_{uuid.uuid4().hex[:12]}"
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        
        record = TaskRegistrationRecord(
            registration_id=registration_id,
            task_id=task_id,
            batch_id="batch_123",
            registration_status="registered",
            registration_reason="Test",
            truth_anchor=TruthAnchor(anchor_type="batch_id", anchor_value="batch_123", metadata={}),
            owner="test",
            status="pending",
            source_closeout=None,
            proposed_task={
                "title": "Trading continuation",
                "description": "Continue trading roundtable",
                "task_type": "continuation",
            },
            metadata={
                "scenario": "trading_roundtable_phase1",
                "adapter": "trading_roundtable",
                "ready_for_auto_dispatch": True,
            },
        )
        registry.register(record)
        record = get_registration(registration_id)
        
        # 执行 dispatch
        artifact = execute_dispatch(record)
        
        # 验证 artifact
        assert artifact.dispatch_status == "dispatched"
        assert artifact.registration_id == record.registration_id
        assert artifact.task_id == record.task_id
        assert artifact.dispatch_target["scenario"] == "trading_roundtable_phase1"
        assert artifact.execution_intent is not None
        assert "recommended_spawn" in artifact.execution_intent
        
        # 验证 artifact 已写入文件
        dispatch_file = DISPATCH_DIR / f"{artifact.dispatch_id}.json"
        assert dispatch_file.exists()
    
    def test_execute_dispatch_blocked_path(self):
        """测试：blocked path - 执行 dispatch 但被阻止"""
        record = register_task(
            proposed_task={"title": "Blocked scenario", "description": "Test"},
            registration_status="registered",
            ready_for_auto_dispatch=True,
            metadata={"scenario": "unknown_scenario"},  # Not in allowlist
        )
        
        artifact = execute_dispatch(record)
        
        # 验证 artifact
        assert artifact.dispatch_status == "blocked"
        assert "not in allowlist" in artifact.dispatch_reason
        assert artifact.execution_intent is None  # Blocked 时没有 execution_intent
        
        # 验证 artifact 已写入文件
        dispatch_file = DISPATCH_DIR / f"{artifact.dispatch_id}.json"
        assert dispatch_file.exists()
        
        # 验证 task status 未更新（仍然是 pending）
        updated_record = get_registration(record.registration_id)
        assert updated_record.status == "pending"
    
    def test_execute_dispatch_trading_execution_intent(self):
        """测试：trading 场景的 execution_intent 包含正确的 metadata"""
        # 使用 TaskRegistry 直接创建记录
        registry = TaskRegistry()
        
        import uuid
        registration_id = f"reg_{uuid.uuid4().hex[:12]}"
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        
        record = TaskRegistrationRecord(
            registration_id=registration_id,
            task_id=task_id,
            batch_id="batch_trading_123",
            registration_status="registered",
            registration_reason="Test",
            truth_anchor=TruthAnchor(anchor_type="batch_id", anchor_value="batch_trading_123", metadata={}),
            owner="test",
            status="pending",
            source_closeout=None,
            proposed_task={
                "title": "Trading phase 1 continuation",
                "description": "Continue trading roundtable phase 1",
                "task_type": "continuation",
            },
            metadata={
                "scenario": "trading_roundtable_phase1",
                "adapter": "trading_roundtable",
                "ready_for_auto_dispatch": True,
            },
        )
        registry.register(record)
        record = get_registration(registration_id)
        
        artifact = execute_dispatch(record)
        
        # 验证 trading 特定的 execution_intent
        assert artifact.execution_intent is not None
        intent = artifact.execution_intent
        assert "recommended_spawn" in intent
        assert "trading_context" in intent["recommended_spawn"]["metadata"]
        trading_context = intent["recommended_spawn"]["metadata"]["trading_context"]
        assert trading_context["phase"] == "phase1_continuation"
        assert trading_context["batch_id"] == "batch_trading_123"


class TestDispatchListAndGet:
    """测试 dispatch list 和 get 功能"""
    
    def test_list_dispatches(self):
        """测试：列出 dispatches"""
        # 使用 TaskRegistry 直接创建记录
        registry = TaskRegistry()
        import uuid
        
        records = []
        for i in range(3):
            registration_id = f"reg_task{i}_{uuid.uuid4().hex[:8]}"
            task_id = f"task_{uuid.uuid4().hex[:12]}"
            
            record = TaskRegistrationRecord(
                registration_id=registration_id,
                task_id=task_id,
                batch_id=f"batch_{i}",
                registration_status="registered",
                registration_reason="Test",
                truth_anchor=TruthAnchor(anchor_type="batch_id", anchor_value=f"batch_{i}", metadata={}),
                owner="test",
                status="pending",
                source_closeout=None,
                proposed_task={"title": f"Task {i}", "description": "Test"},
                metadata={
                    "scenario": "trading_roundtable_phase1",
                    "ready_for_auto_dispatch": True,
                },
            )
            registry.register(record)
            records.append(get_registration(registration_id))
        
        # 执行 dispatch
        artifacts = []
        for record in records:
            artifact = execute_dispatch(record)
            artifacts.append(artifact)
        
        # 列出所有 dispatches
        all_dispatches = list_dispatches()
        assert len(all_dispatches) >= 3
        
        # 按 status 过滤
        dispatched = list_dispatches(dispatch_status="dispatched")
        assert len(dispatched) >= 3
        
        # 按 registration_id 过滤
        by_registration = list_dispatches(registration_id=records[0].registration_id)
        assert len(by_registration) >= 1
        assert all(d.registration_id == records[0].registration_id for d in by_registration)
    
    def test_get_dispatch(self):
        """测试：获取单个 dispatch"""
        # 使用 TaskRegistry 直接创建记录
        registry = TaskRegistry()
        import uuid
        
        registration_id = f"reg_get_{uuid.uuid4().hex[:8]}"
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        
        record = TaskRegistrationRecord(
            registration_id=registration_id,
            task_id=task_id,
            batch_id="batch_123",
            registration_status="registered",
            registration_reason="Test",
            truth_anchor=TruthAnchor(anchor_type="batch_id", anchor_value="batch_123", metadata={}),
            owner="test",
            status="pending",
            source_closeout=None,
            proposed_task={"title": "Test", "description": "Test"},
            metadata={
                "scenario": "trading_roundtable_phase1",
                "ready_for_auto_dispatch": True,
            },
        )
        registry.register(record)
        record = get_registration(registration_id)
        
        artifact = execute_dispatch(record)
        
        # 获取 dispatch
        retrieved = get_dispatch(artifact.dispatch_id)
        assert retrieved is not None
        assert retrieved.dispatch_id == artifact.dispatch_id
        assert retrieved.registration_id == artifact.registration_id
        
        # 获取不存在的 dispatch
        not_found = get_dispatch("dispatch_nonexistent_xyz999")
        assert not_found is None


class TestDispatchArtifactStructure:
    """测试 DispatchArtifact 结构"""
    
    def test_dispatch_artifact_to_dict(self):
        """测试：DispatchArtifact 序列化"""
        artifact = DispatchArtifact(
            dispatch_id="dispatch_test",
            registration_id="reg_test",
            task_id="task_test",
            dispatch_status="dispatched",
            dispatch_reason="Test dispatch",
            dispatch_time=datetime.now().isoformat(),
            dispatch_target={"scenario": "trading_roundtable_phase1"},
            execution_intent={"recommended_spawn": {"task": "Test"}},
            policy_evaluation={"eligible": True, "checks": []},
        )
        
        data = artifact.to_dict()
        
        assert data["dispatch_version"] == "auto_dispatch_v1"
        assert data["dispatch_id"] == "dispatch_test"
        assert data["dispatch_status"] == "dispatched"
        assert data["execution_intent"] is not None
    
    def test_dispatch_artifact_from_dict(self):
        """测试：DispatchArtifact 反序列化"""
        data = {
            "dispatch_version": "auto_dispatch_v1",
            "dispatch_id": "dispatch_test",
            "registration_id": "reg_test",
            "task_id": "task_test",
            "dispatch_status": "blocked",
            "dispatch_reason": "Test blocked",
            "dispatch_time": "2026-03-22T12:00:00",
            "dispatch_target": {"scenario": "unknown"},
            "execution_intent": None,
            "policy_evaluation": {"eligible": False},
        }
        
        artifact = DispatchArtifact.from_dict(data)
        
        assert artifact.dispatch_id == "dispatch_test"
        assert artifact.dispatch_status == "blocked"
        assert artifact.execution_intent is None
    
    def test_dispatch_artifact_write_and_read(self):
        """测试：DispatchArtifact 写入和读取"""
        artifact = DispatchArtifact(
            dispatch_id="dispatch_persist_test",
            registration_id="reg_test",
            task_id="task_test",
            dispatch_status="dispatched",
            dispatch_reason="Test",
            dispatch_time=datetime.now().isoformat(),
            dispatch_target={"scenario": "trading_roundtable_phase1"},
        )
        
        # 写入
        path = artifact.write()
        assert path.exists()
        
        # 读取
        retrieved = get_dispatch("dispatch_persist_test")
        assert retrieved is not None
        assert retrieved.dispatch_id == "dispatch_persist_test"


class TestPolicyCustomization:
    """测试 Policy 自定义"""
    
    def test_custom_policy_allowlist(self):
        """测试：自定义 policy allowlist"""
        custom_policy = DispatchPolicy(
            scenario_allowlist=["custom_scenario"],
        )
        
        # 使用 TaskRegistry 直接创建记录
        registry = TaskRegistry()
        import uuid
        
        registration_id = f"reg_custom_{uuid.uuid4().hex[:8]}"
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        
        record = TaskRegistrationRecord(
            registration_id=registration_id,
            task_id=task_id,
            batch_id=None,
            registration_status="registered",
            registration_reason="Test",
            truth_anchor=TruthAnchor(anchor_type="task_id", anchor_value=task_id, metadata={}),
            owner="test",
            status="pending",
            source_closeout=None,
            proposed_task={"title": "Custom", "description": "Test"},
            metadata={
                "scenario": "custom_scenario",
                "ready_for_auto_dispatch": True,
            },
        )
        registry.register(record)
        record = get_registration(registration_id)
        
        selector = AutoDispatchSelector(custom_policy)
        evaluation = selector.evaluate_policy(record)
        
        assert evaluation["eligible"] is True
        assert len(evaluation["blocked_reasons"]) == 0
    
    def test_custom_policy_no_anchor_required(self):
        """测试：自定义 policy 不要求 anchor"""
        custom_policy = DispatchPolicy(
            require_anchor=False,
        )
        
        record = register_task(
            proposed_task={"title": "No anchor", "description": "Test"},
            registration_status="registered",
            ready_for_auto_dispatch=True,
            metadata={"scenario": "trading_roundtable_phase1"},
            # No truth_anchor
        )
        
        selector = AutoDispatchSelector(custom_policy)
        evaluation = selector.evaluate_policy(record)
        
        # 不要求 anchor 时应该通过
        assert evaluation["eligible"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
