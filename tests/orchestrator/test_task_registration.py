#!/usr/bin/env python3
"""
test_task_registration.py — Tests for Universal Task Registration Layer (v2)

覆盖：
- registration payload 会变成真实注册记录/文件
- 无 remaining scope / blocked 时不注册
- trading 场景能触发真实注册
- 已注册结果包含稳定 linkage（source task / source batch / new task id）
"""

import json
import os
import sys
import tempfile
import shutil
from pathlib import Path

# 添加 runtime/orchestrator 到 path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "runtime" / "orchestrator"))

from partial_continuation import (
    build_partial_closeout,
    auto_replan,
    generate_next_registrations_for_closeout,
    generate_registered_registrations_for_closeout,
    adapt_closeout_for_trading,
    ScopeItem,
)
from task_registration import (
    TaskRegistry,
    TaskRegistrationRecord,
    register_task,
    get_registration,
    list_registrations,
    get_registrations_by_source,
    register_next_task_from_payload,
    REGISTRY_DIR,
    _registry_file,
)


def setup_module(module):
    """测试前准备：使用临时目录作为 registry"""
    # 保存原始目录
    setup_module.original_registry_dir = os.environ.get("OPENCLAW_REGISTRY_DIR")
    
    # 创建临时目录
    setup_module.temp_dir = tempfile.mkdtemp()
    os.environ["OPENCLAW_REGISTRY_DIR"] = setup_module.temp_dir


def teardown_module(module):
    """测试后清理：恢复原始目录"""
    # 恢复原始目录
    if setup_module.original_registry_dir:
        os.environ["OPENCLAW_REGISTRY_DIR"] = setup_module.original_registry_dir
    else:
        os.environ.pop("OPENCLAW_REGISTRY_DIR", None)
    
    # 清理临时目录
    if hasattr(setup_module, "temp_dir"):
        shutil.rmtree(setup_module.temp_dir, ignore_errors=True)


class TestTaskRegistry:
    """测试 TaskRegistry 基本功能"""
    
    def test_register_and_get(self):
        """测试注册和获取记录"""
        registry = TaskRegistry()
        
        record = register_task(
            proposed_task={"title": "Test Task", "description": "Test"},
            source_closeout={"original_batch_id": "batch_test"},
            registration_status="registered",
            registration_reason="Test registration",
            batch_id="batch_test",
            owner="test_owner",
            ready_for_auto_dispatch=True,
        )
        
        # 验证记录存在
        assert record is not None
        assert record.registration_status == "registered"
        assert record.batch_id == "batch_test"
        assert record.owner == "test_owner"
        assert record.ready_for_auto_dispatch is True
        
        # 验证可以通过 get 获取
        retrieved = registry.get(record.registration_id)
        assert retrieved is not None
        assert retrieved.task_id == record.task_id
        
        print(f"✓ test_register_and_get: registered {record.registration_id}")
    
    def test_registration_creates_files(self):
        """测试注册会创建真实文件"""
        registry = TaskRegistry()
        
        record = register_task(
            proposed_task={"title": "File Test"},
            registration_status="registered",
            registration_reason="Test",
        )
        
        # 验证注册表文件存在
        registry_file = _registry_file()
        assert registry_file.exists(), "Registry file should exist"
        
        # 验证单个记录文件存在
        record_file = REGISTRY_DIR / f"{record.registration_id}.json"
        assert record_file.exists(), "Individual record file should exist"
        
        # 验证文件内容
        with open(record_file, "r") as f:
            data = json.load(f)
        assert data["registration_id"] == record.registration_id
        
        print(f"✓ test_registration_creates_files: files created at {REGISTRY_DIR}")
    
    def test_list_registrations(self):
        """测试列出注册记录"""
        # 注册多个任务
        for i in range(3):
            register_task(
                proposed_task={"title": f"Task {i}"},
                registration_status="registered",
                batch_id="batch_list_test",
            )
        
        # 列出所有
        all_records = list_registrations(limit=10)
        assert len(all_records) >= 3
        
        # 按 batch_id 过滤
        batch_records = list_registrations(batch_id="batch_list_test", limit=10)
        assert len(batch_records) >= 3
        
        print(f"✓ test_list_registrations: listed {len(all_records)} records")
    
    def test_get_by_source(self):
        """测试按来源查询"""
        source_batch_id = f"batch_source_{os.urandom(4).hex()}"
        
        record = register_task(
            proposed_task={"title": "Source Test"},
            source_closeout={"original_batch_id": source_batch_id},
            registration_status="registered",
        )
        
        # 按 source batch 查询
        results = get_registrations_by_source(source_batch_id=source_batch_id)
        assert len(results) >= 1
        assert any(r.registration_id == record.registration_id for r in results)
        
        print(f"✓ test_get_by_source: found {len(results)} records by source")
    
    def test_update_status(self):
        """测试更新状态"""
        registry = TaskRegistry()
        
        record = register_task(
            proposed_task={"title": "Status Update Test"},
            registration_status="registered",
        )
        
        # 更新状态
        updated = registry.update_status(record.registration_id, "in_progress")
        assert updated is not None
        assert updated.status == "in_progress"
        
        # 验证持久化
        retrieved = registry.get(record.registration_id)
        assert retrieved.status == "in_progress"
        
        print(f"✓ test_update_status: updated to in_progress")


class TestRegistrationWithStatus:
    """测试 NextTaskRegistrationWithStatus (v2)"""
    
    def test_generate_registered_registrations(self):
        """测试 generate_registered_registrations_for_closeout"""
        # 构建 partial closeout（有 remaining work）
        closeout = build_partial_closeout(
            completed_scope=[{"item_id": "c1", "description": "Completed"}],
            remaining_scope=[{"item_id": "r1", "description": "Remaining work"}],
            stop_reason="partial_completed",
            original_batch_id="batch_v2_test",
        )
        
        # 生成 registrations with status
        registrations = generate_registered_registrations_for_closeout(
            closeout=closeout,
            adapter="test_adapter",
            scenario="test_scenario",
            auto_register=True,
            batch_id="batch_v2_test",
        )
        
        # 验证生成了 registration
        assert len(registrations) >= 1
        
        reg = registrations[0]
        assert reg.registration_status == "registered"
        assert reg.truth_anchor is not None
        assert "anchor_type" in reg.truth_anchor
        assert "anchor_value" in reg.truth_anchor
        
        # 验证 truth_anchor 包含 source linkage
        anchor_metadata = reg.truth_anchor.get("metadata", {})
        assert "source_batch_id" in anchor_metadata or "source_task_id" in anchor_metadata
        
        print(f"✓ test_generate_registered_registrations: generated {len(registrations)} registrations")
    
    def test_no_registration_when_no_remaining_work(self):
        """测试无 remaining scope 时不注册"""
        # 构建 fully completed closeout
        closeout = build_partial_closeout(
            completed_scope=[{"item_id": "c1", "description": "Completed"}],
            remaining_scope=[],  # 无剩余工作
            stop_reason="completed_all",
        )
        
        registrations = generate_registered_registrations_for_closeout(
            closeout=closeout,
            auto_register=True,
        )
        
        assert len(registrations) == 0
        
        print("✓ test_no_registration_when_no_remaining_work: correctly skipped")
    
    def test_blocked_registration(self):
        """测试 blocked 时不注册"""
        # 构建 blocked closeout
        closeout = build_partial_closeout(
            completed_scope=[{"item_id": "c1", "description": "Completed"}],
            remaining_scope=[{"item_id": "r1", "description": "Blocked work", "status": "blocked"}],
            stop_reason="blocked",
            dispatch_readiness="blocked",
        )
        
        registrations = generate_registered_registrations_for_closeout(
            closeout=closeout,
            auto_register=True,
        )
        
        # blocked 时应该不生成 registrations
        assert len(registrations) == 0
        
        print("✓ test_blocked_registration: correctly skipped blocked closeout")
    
    def test_ready_for_auto_dispatch_flag(self):
        """测试 ready_for_auto_dispatch 标志"""
        # 构建 ready closeout
        closeout = build_partial_closeout(
            completed_scope=[{"item_id": "c1", "description": "Completed"}],
            remaining_scope=[{"item_id": "r1", "description": "Next step"}],
            stop_reason="partial_completed",
            dispatch_readiness="ready",
        )
        
        registrations = generate_registered_registrations_for_closeout(
            closeout=closeout,
            auto_register=False,  # 不实际注册，只测试 flag
        )
        
        assert len(registrations) >= 1
        reg = registrations[0]
        
        # ready + priority=1 应该是 ready_for_auto_dispatch=True
        assert reg.ready_for_auto_dispatch is True
        
        print(f"✓ test_ready_for_auto_dispatch_flag: ready={reg.ready_for_auto_dispatch}")
    
    def test_stable_linkage(self):
        """测试稳定 linkage（source task / source batch / new task id）"""
        source_batch_id = f"batch_linkage_{os.urandom(4).hex()}"
        source_task_id = f"task_linkage_{os.urandom(4).hex()}"
        
        closeout = build_partial_closeout(
            completed_scope=[{"item_id": "c1", "description": "Completed"}],
            remaining_scope=[{"item_id": "r1", "description": "Next"}],
            stop_reason="partial_completed",
            original_task_id=source_task_id,
            original_batch_id=source_batch_id,
        )
        
        registrations = generate_registered_registrations_for_closeout(
            closeout=closeout,
            auto_register=True,
        )
        
        assert len(registrations) >= 1
        reg = registrations[0]
        
        # 验证 truth_anchor 包含 source linkage
        anchor = reg.truth_anchor
        assert anchor["anchor_type"] in ("task_id", "batch_id")
        
        anchor_metadata = anchor.get("metadata", {})
        assert anchor_metadata.get("source_batch_id") == source_batch_id
        assert anchor_metadata.get("source_task_id") == source_task_id
        
        # 验证 task_registry_record 包含 new task id
        if "task_registry_record" in reg.metadata:
            task_registry = reg.metadata["task_registry_record"]
            assert "task_id" in task_registry
            assert "registration_id" in task_registry
        
        print(f"✓ test_stable_linkage: linkage verified (source_batch={source_batch_id})")


class TestTradingScenarioIntegration:
    """测试 trading 场景集成"""
    
    def test_trading_triggers_real_registration(self):
        """测试 trading 场景能触发真实注册"""
        # 模拟 trading roundtable PASS 场景
        closeout = build_partial_closeout(
            completed_scope=[{"item_id": "c1", "description": "Phase 1 completed"}],
            remaining_scope=[{"item_id": "r1", "description": "Phase 2 handoff"}],
            stop_reason="partial_completed",
            dispatch_readiness="ready",
            original_batch_id="batch_trading_test",
        )
        
        # 适配 trading 场景
        adapted = adapt_closeout_for_trading(
            closeout=closeout,
            packet={"overall_gate": "PASS"},
            roundtable={"conclusion": "PASS", "blocker": "none"},
        )
        
        # 生成 registrations
        registrations = generate_registered_registrations_for_closeout(
            closeout=adapted,
            adapter="trading_roundtable",
            scenario="trading_roundtable_phase1",
            auto_register=True,
            batch_id="batch_trading_test",
            owner="trading",
        )
        
        # 验证生成了真实注册
        assert len(registrations) >= 1
        reg = registrations[0]
        
        assert reg.registration_status == "registered"
        assert reg.metadata.get("adapter") == "trading_roundtable"
        
        # 验证注册到了 task registry
        if "task_registry_record" in reg.metadata:
            task_registry = reg.metadata["task_registry_record"]
            retrieved = get_registration(task_registry["registration_id"])
            assert retrieved is not None
            assert retrieved.registration_status == "registered"
        
        print(f"✓ test_trading_triggers_real_registration: trading scenario registered {len(registrations)} tasks")


class TestRegistrationPayloadToRecord:
    """测试 registration payload 转真实记录"""
    
    def test_register_next_task_from_payload(self):
        """测试从 payload 注册"""
        # 构建 closeout 和 registration payload
        closeout = build_partial_closeout(
            completed_scope=[{"item_id": "c1", "description": "Done"}],
            remaining_scope=[{"item_id": "r1", "description": "Next"}],
            stop_reason="partial_completed",
            original_batch_id="batch_payload_test",
        )
        
        # 生成 v1 payload
        v1_registrations = generate_next_registrations_for_closeout(
            closeout=closeout,
            adapter="test",
        )
        
        assert len(v1_registrations) >= 1
        payload = v1_registrations[0].to_dict()
        
        # 从 payload 注册
        record = register_next_task_from_payload(
            registration_payload=payload,
            registration_status="registered",
            registration_reason="From payload test",
            batch_id="batch_payload_test",
            ready_for_auto_dispatch=True,
        )
        
        # 验证记录
        assert record is not None
        assert record.registration_status == "registered"
        assert record.source_closeout is not None
        
        # 验证可以从 registry 获取
        retrieved = get_registration(record.registration_id)
        assert retrieved is not None
        assert retrieved.task_id == record.task_id
        
        print(f"✓ test_register_next_task_from_payload: registered from payload")


def run_tests():
    """运行所有测试"""
    import pytest
    
    # 使用 pytest 运行
    exit_code = pytest.main([
        __file__,
        "-v",
        "--tb=short",
    ])
    
    return exit_code


if __name__ == "__main__":
    exit_code = run_tests()
    sys.exit(exit_code)
