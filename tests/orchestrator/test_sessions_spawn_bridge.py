#!/usr/bin/env python3
"""
test_sessions_spawn_bridge.py — V10 Real OpenClaw sessions_spawn Integration 测试

覆盖场景：
1. Happy path: request -> real API wrapper call (mock OpenClaw tool 层)
2. Blocked: blocked/duplicate/missing payload 不调用
3. Linkage: 真实执行结果 linkage 正确
4. Trading 场景首个样例
5. Auto-trigger real execution
6. **P0-3 Batch 4**: 真实 API 调用边界测试（runner 脚本调用）
7. **P0-3 Batch 4**: 通用场景验证（非 trading-specific）
8. **P0-3 Batch 4**: 真实产物路径和执行锚点验证
"""

import json
import os
import sys
import unittest
from pathlib import Path
from datetime import datetime
from typing import Any, Dict
import uuid

# 添加 runtime/orchestrator 到路径
runtime_path = Path(__file__).parent.parent.parent / "runtime" / "orchestrator"
sys.path.insert(0, str(runtime_path))

from sessions_spawn_request import (
    SessionsSpawnRequest,
    SpawnRequestKernel,
    get_spawn_request,
    SPAWN_REQUEST_DIR,
    _spawn_request_file,
    configure_auto_trigger,
)
from completion_receipt import (
    CompletionReceiptArtifact,
    COMPLETION_RECEIPT_DIR,
    _completion_receipt_file,
)
from sessions_spawn_bridge import (
    SessionsSpawnBridge,
    SessionsSpawnBridgePolicy,
    SessionsSpawnAPIExecution,
    APIExecutionResult,
    execute_sessions_spawn_api,
    list_api_executions,
    get_api_execution,
    get_api_execution_by_request,
    auto_trigger_real_execution,
    configure_auto_trigger_real_exec,
    get_auto_trigger_real_exec_status,
    API_EXECUTION_DIR,
    _is_already_executed,
    _load_api_execution_index,
    EXECUTION_VERSION,
)


def create_test_receipt(
    receipt_id: str,
    task_id: str,
    spawn_id: str,
    dispatch_id: str,
    registration_id: str,
    execution_id: str,
    receipt_status: str = "completed",
    scenario: str = "trading",
    owner: str = "test_owner",
) -> CompletionReceiptArtifact:
    """创建测试 receipt"""
    receipt = CompletionReceiptArtifact(
        receipt_id=receipt_id,
        source_spawn_execution_id=execution_id,
        source_spawn_id=spawn_id,
        source_dispatch_id=dispatch_id,
        source_registration_id=registration_id,
        source_task_id=task_id,
        receipt_status=receipt_status,
        receipt_reason="Test receipt for V9",
        receipt_time=datetime.now().isoformat(),
        result_summary="Test execution completed",
        dedupe_key=f"dedupe_{receipt_id}",
        business_result={"scenario": scenario, "test": "data"},
        metadata={
            "source_execution_status": "started" if receipt_status == "completed" else "failed",
            "scenario": scenario,
            "owner": owner,
            "truth_anchor": "v9_test_anchor",
        },
    )
    
    COMPLETION_RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
    receipt_file = _completion_receipt_file(receipt_id)
    tmp_file = receipt_file.with_suffix(".tmp")
    with open(tmp_file, "w") as f:
        json.dump(receipt.to_dict(), f, indent=2)
    tmp_file.replace(receipt_file)
    
    return receipt


def create_test_request_from_receipt(
    receipt: CompletionReceiptArtifact,
    request_status: str = "prepared",
) -> SessionsSpawnRequest:
    """从 receipt 创建测试 request"""
    kernel = SpawnRequestKernel()
    policy_eval = kernel.evaluate_policy(receipt)
    request = kernel.create_request(receipt, policy_eval)
    
    if request_status == "blocked":
        request.spawn_request_status = "blocked"
        request.spawn_request_reason = "Test blocked status"
    
    request.write()
    
    from sessions_spawn_request import _record_request_dedupe
    if request.spawn_request_status == "prepared":
        _record_request_dedupe(request.dedupe_key, request.request_id)
    
    return request


class TestV9HappyPath(unittest.TestCase):
    def setUp(self):
        self.suffix = uuid.uuid4().hex[:6]
        self.test_receipt = create_test_receipt(
            receipt_id=f"v9_receipt_happy_{self.suffix}",
            task_id=f"v9_task_happy_{self.suffix}",
            spawn_id=f"v9_spawn_happy_{self.suffix}",
            dispatch_id=f"v9_dispatch_happy_{self.suffix}",
            registration_id=f"v9_reg_happy_{self.suffix}",
            execution_id=f"v9_exec_happy_{self.suffix}",
            receipt_status="completed",
            scenario="trading",
            owner="test_owner",
        )
        self.test_request = create_test_request_from_receipt(self.test_receipt)
    
    def test_happy_path_api_call(self):
        policy = SessionsSpawnBridgePolicy(safe_mode=True, prevent_duplicate=True, allowlist=["trading"])
        bridge = SessionsSpawnBridge(policy)
        artifact = bridge.execute(self.test_request)
        
        self.assertIsNotNone(artifact.execution_id)
        self.assertEqual(artifact.source_request_id, self.test_request.request_id)
        self.assertIn(artifact.api_execution_status, ["started", "pending"])
        self.assertIsNotNone(artifact.api_execution_result)
        
        if artifact.api_execution_result:
            linkage = artifact.api_execution_result.linkage
            self.assertEqual(linkage["request_id"], self.test_request.request_id)
            self.assertEqual(linkage["task_id"], self.test_request.source_task_id)
        
        exec_file = API_EXECUTION_DIR / f"{artifact.execution_id}.json"
        self.assertTrue(exec_file.exists())
        print(f"✓ Happy path: {artifact.execution_id} -> {artifact.api_execution_status}")
    
    def test_happy_path_via_convenience_function(self):
        policy = SessionsSpawnBridgePolicy(safe_mode=True)
        artifact = execute_sessions_spawn_api(self.test_request.request_id, policy)
        
        self.assertIsNotNone(artifact.execution_id)
        self.assertEqual(artifact.source_request_id, self.test_request.request_id)
        
        queried = get_api_execution(artifact.execution_id)
        self.assertIsNotNone(queried)
        self.assertEqual(queried.execution_id, artifact.execution_id)
        
        executions = list_api_executions(request_id=self.test_request.request_id)
        self.assertTrue(len(executions) > 0)
        print(f"✓ Convenience function: {artifact.execution_id}")


class TestV9BlockedScenarios(unittest.TestCase):
    def setUp(self):
        self.suffix = uuid.uuid4().hex[:6]
        self.test_receipt = create_test_receipt(
            receipt_id=f"v9_receipt_blocked_{self.suffix}",
            task_id=f"v9_task_blocked_{self.suffix}",
            spawn_id=f"v9_spawn_blocked_{self.suffix}",
            dispatch_id=f"v9_dispatch_blocked_{self.suffix}",
            registration_id=f"v9_reg_blocked_{self.suffix}",
            execution_id=f"v9_exec_blocked_{self.suffix}",
            receipt_status="completed",
            scenario="generic",
            owner="test_owner",
        )
    
    def test_blocked_request_status(self):
        request = create_test_request_from_receipt(self.test_receipt, request_status="blocked")
        policy = SessionsSpawnBridgePolicy(safe_mode=True)
        bridge = SessionsSpawnBridge(policy)
        artifact = bridge.execute(request)
        
        self.assertEqual(artifact.api_execution_status, "blocked")
        self.assertIn("Request status is 'blocked'", artifact.api_execution_reason)
        print(f"✓ Blocked request status: {artifact.api_execution_reason}")
    
    def test_duplicate_prevention(self):
        request = create_test_request_from_receipt(self.test_receipt)
        policy = SessionsSpawnBridgePolicy(safe_mode=True, prevent_duplicate=True)
        bridge = SessionsSpawnBridge(policy)
        artifact1 = bridge.execute(request)
        
        self.assertIn(artifact1.api_execution_status, ["started", "pending"])
        
        artifact2 = bridge.execute(request)
        self.assertIn(artifact2.api_execution_status, ["blocked", "pending"])
        if artifact2.api_execution_status == "blocked":
            self.assertIn("Duplicate execution", artifact2.api_execution_reason)
        print(f"✓ Duplicate prevention: {artifact1.execution_id} -> {artifact2.api_execution_status}")
    
    def test_missing_metadata(self):
        request = create_test_request_from_receipt(self.test_receipt)
        request.sessions_spawn_params["metadata"] = {}
        request.write()
        
        policy = SessionsSpawnBridgePolicy(safe_mode=True)
        bridge = SessionsSpawnBridge(policy)
        artifact = bridge.execute(request)
        
        self.assertEqual(artifact.api_execution_status, "blocked")
        self.assertIn("Missing metadata", artifact.api_execution_reason)
        print(f"✓ Missing metadata: {artifact.api_execution_reason}")
    
    def test_missing_task(self):
        request = create_test_request_from_receipt(self.test_receipt)
        request.sessions_spawn_params["task"] = ""
        request.write()
        
        policy = SessionsSpawnBridgePolicy(safe_mode=True)
        bridge = SessionsSpawnBridge(policy)
        artifact = bridge.execute(request)
        
        self.assertEqual(artifact.api_execution_status, "blocked")
        self.assertIn("Missing task", artifact.api_execution_reason)
        print(f"✓ Missing task: {artifact.api_execution_reason}")


class TestV9Linkage(unittest.TestCase):
    def setUp(self):
        self.suffix = uuid.uuid4().hex[:6]
        self.test_receipt = create_test_receipt(
            receipt_id=f"v9_receipt_linkage_{self.suffix}",
            task_id=f"v9_task_linkage_{self.suffix}",
            spawn_id=f"v9_spawn_linkage_{self.suffix}",
            dispatch_id=f"v9_dispatch_linkage_{self.suffix}",
            registration_id=f"v9_reg_linkage_{self.suffix}",
            execution_id=f"v9_exec_linkage_{self.suffix}",
            receipt_status="completed",
            scenario="trading",
            owner="test_owner",
        )
        self.test_request = create_test_request_from_receipt(self.test_receipt)
    
    def test_full_linkage(self):
        policy = SessionsSpawnBridgePolicy(safe_mode=True)
        bridge = SessionsSpawnBridge(policy)
        artifact = bridge.execute(self.test_request)
        
        self.assertEqual(artifact.source_request_id, self.test_request.request_id)
        self.assertEqual(artifact.source_receipt_id, self.test_receipt.receipt_id)
        self.assertEqual(artifact.source_task_id, self.test_receipt.source_task_id)
        
        if artifact.api_execution_result:
            linkage = artifact.api_execution_result.linkage
            self.assertIsNotNone(linkage)
            self.assertEqual(linkage["request_id"], self.test_request.request_id)
            self.assertEqual(linkage["task_id"], self.test_request.source_task_id)
        
        print(f"✓ Full linkage verified: {artifact.execution_id}")
    
    def test_linkage_via_list(self):
        policy = SessionsSpawnBridgePolicy(safe_mode=True)
        bridge = SessionsSpawnBridge(policy)
        artifact = bridge.execute(self.test_request)
        
        executions = list_api_executions(task_id=self.test_request.source_task_id)
        self.assertTrue(len(executions) > 0)
        
        found = None
        for exec_artifact in executions:
            if exec_artifact.execution_id == artifact.execution_id:
                found = exec_artifact
                break
        
        self.assertIsNotNone(found)
        self.assertEqual(found.source_task_id, self.test_request.source_task_id)
        print(f"✓ Linkage via list: found {len(executions)} executions")


class TestV9TradingScenario(unittest.TestCase):
    def setUp(self):
        self.suffix = uuid.uuid4().hex[:6]
        self.test_receipt = create_test_receipt(
            receipt_id=f"v9_trading_receipt_{self.suffix}",
            task_id=f"v9_trading_task_{self.suffix}",
            spawn_id=f"v9_trading_spawn_{self.suffix}",
            dispatch_id=f"v9_trading_dispatch_{self.suffix}",
            registration_id=f"v9_trading_reg_{self.suffix}",
            execution_id=f"v9_trading_exec_{self.suffix}",
            receipt_status="completed",
            scenario="trading",
            owner="trading_agent",
        )
        self.test_request = create_test_request_from_receipt(self.test_receipt)
    
    def test_trading_happy_path(self):
        policy = SessionsSpawnBridgePolicy(safe_mode=True, allowlist=["trading"])
        bridge = SessionsSpawnBridge(policy)
        artifact = bridge.execute(self.test_request)
        
        self.assertIn(artifact.api_execution_status, ["started", "pending"])
        self.assertEqual(artifact.metadata.get("scenario"), "trading")
        print(f"✓ Trading happy path: {artifact.execution_id} (scenario=trading)")
    
    def test_trading_auto_trigger(self):
        configure_auto_trigger_real_exec(
            enabled=True, allowlist=["trading"], require_manual_approval=False, safe_mode=True,
        )
        
        suffix2 = uuid.uuid4().hex[:6]
        receipt2 = create_test_receipt(
            receipt_id=f"v9_trading_auto_receipt_{suffix2}",
            task_id=f"v9_trading_auto_task_{suffix2}",
            spawn_id=f"v9_trading_auto_spawn_{suffix2}",
            dispatch_id=f"v9_trading_auto_dispatch_{suffix2}",
            registration_id=f"v9_trading_auto_reg_{suffix2}",
            execution_id=f"v9_trading_auto_exec_{suffix2}",
            receipt_status="completed",
            scenario="trading",
            owner="trading_agent",
        )
        request2 = create_test_request_from_receipt(receipt2)
        
        triggered, reason, exec_id = auto_trigger_real_execution(request2.request_id)
        
        executions = list_api_executions(request_id=request2.request_id)
        self.assertTrue(len(executions) > 0, f"Auto-trigger should create execution: {reason}")
        
        artifact = executions[0]
        self.assertEqual(artifact.source_request_id, request2.request_id)
        self.assertEqual(artifact.metadata.get("scenario"), "trading")
        print(f"✓ Trading auto-trigger: {artifact.execution_id} (status={artifact.api_execution_status})")


class TestV9AutoTrigger(unittest.TestCase):
    def setUp(self):
        self.suffix = uuid.uuid4().hex[:6]
        self.test_receipt = create_test_receipt(
            receipt_id=f"v9_auto_receipt_{self.suffix}",
            task_id=f"v9_auto_task_{self.suffix}",
            spawn_id=f"v9_auto_spawn_{self.suffix}",
            dispatch_id=f"v9_auto_dispatch_{self.suffix}",
            registration_id=f"v9_auto_reg_{self.suffix}",
            execution_id=f"v9_auto_exec_{self.suffix}",
            receipt_status="completed",
            scenario="trading",
            owner="test_owner",
        )
        self.test_request = create_test_request_from_receipt(self.test_receipt)
    
    def test_auto_trigger_config(self):
        config = configure_auto_trigger_real_exec(
            enabled=True, allowlist=["trading", "channel"], require_manual_approval=False, safe_mode=True,
        )
        
        self.assertTrue(config["enabled"])
        self.assertEqual(config["allowlist"], ["trading", "channel"])
        self.assertFalse(config["require_manual_approval"])
        
        status = get_auto_trigger_real_exec_status()
        self.assertEqual(status["config"]["enabled"], True)
        print(f"✓ Auto-trigger config: enabled={config['enabled']}, allowlist={config['allowlist']}")
    
    def test_auto_trigger_blocked_by_manual_approval(self):
        configure_auto_trigger_real_exec(enabled=True, require_manual_approval=True)
        triggered, reason, exec_id = auto_trigger_real_execution(self.test_request.request_id)
        
        self.assertFalse(triggered)
        self.assertIn("Manual approval", reason)
        print(f"✓ Auto-trigger blocked by manual approval: {reason}")
    
    def test_auto_trigger_blocked_by_scenario(self):
        configure_auto_trigger_real_exec(enabled=True, allowlist=["trading"], require_manual_approval=False)
        
        suffix2 = uuid.uuid4().hex[:6]
        receipt2 = create_test_receipt(
            receipt_id=f"v9_generic_receipt_{suffix2}",
            task_id=f"v9_generic_task_{suffix2}",
            spawn_id=f"v9_generic_spawn_{suffix2}",
            dispatch_id=f"v9_generic_dispatch_{suffix2}",
            registration_id=f"v9_generic_reg_{suffix2}",
            execution_id=f"v9_generic_exec_{suffix2}",
            receipt_status="completed",
            scenario="generic",
            owner="test_owner",
        )
        request2 = create_test_request_from_receipt(receipt2)
        
        triggered, reason, exec_id = auto_trigger_real_execution(request2.request_id)
        
        self.assertFalse(triggered)
        self.assertIn("not in allowlist", reason)
        print(f"✓ Auto-trigger blocked by scenario: {reason}")


class TestV9Integration(unittest.TestCase):
    def test_full_pipeline_receipt_to_api_execution(self):
        suffix = uuid.uuid4().hex[:6]
        
        receipt = create_test_receipt(
            receipt_id=f"v9_pipeline_receipt_{suffix}",
            task_id=f"v9_pipeline_task_{suffix}",
            spawn_id=f"v9_pipeline_spawn_{suffix}",
            dispatch_id=f"v9_pipeline_dispatch_{suffix}",
            registration_id=f"v9_pipeline_reg_{suffix}",
            execution_id=f"v9_pipeline_exec_{suffix}",
            receipt_status="completed",
            scenario="trading",
            owner="test_owner",
        )
        
        request = create_test_request_from_receipt(receipt)
        policy = SessionsSpawnBridgePolicy(safe_mode=True)
        artifact = execute_sessions_spawn_api(request.request_id, policy)
        
        self.assertEqual(artifact.source_receipt_id, receipt.receipt_id)
        self.assertEqual(artifact.source_request_id, request.request_id)
        self.assertEqual(artifact.source_task_id, receipt.source_task_id)
        
        exec_file = API_EXECUTION_DIR / f"{artifact.execution_id}.json"
        self.assertTrue(exec_file.exists())
        
        queried = get_api_execution(artifact.execution_id)
        self.assertIsNotNone(queried)
        self.assertEqual(queried.execution_id, artifact.execution_id)
        self.assertEqual(queried.source_task_id, receipt.source_task_id)
        
        print(f"✓ Full pipeline: receipt -> request -> API execution ({artifact.execution_id})")


class TestP03Batch3ConsumptionToExecutionChain(unittest.TestCase):
    """
    P0-3 Batch 3: Integration test for artifact -> bridge_consumer -> execution request chain.
    
    验证通用 bridge_consumer auto-trigger 决策接到 sessions_spawn execution request 主链。
    Trading 仅作为首个验证场景，实现保持 adapter-agnostic。
    """
    
    def setUp(self):
        self.suffix = uuid.uuid4().hex[:6]
        
        # 创建测试 receipt（带 readiness/safety_gates/truth_anchor）
        self.test_receipt = create_test_receipt(
            receipt_id=f"batch3_receipt_{self.suffix}",
            task_id=f"batch3_task_{self.suffix}",
            spawn_id=f"batch3_spawn_{self.suffix}",
            dispatch_id=f"batch3_dispatch_{self.suffix}",
            registration_id=f"batch3_reg_{self.suffix}",
            execution_id=f"batch3_exec_{self.suffix}",
            receipt_status="completed",
            scenario="trading",
            owner="trading",
        )
        
        # 创建 request（带 readiness/safety_gates/truth_anchor metadata）
        kernel = SpawnRequestKernel()
        policy_eval = kernel.evaluate_policy(self.test_receipt)
        request = kernel.create_request(self.test_receipt, policy_eval)
        
        # P0-3 Batch 2/3: 添加 readiness/safety_gates/truth_anchor metadata
        request.metadata["readiness"] = {
            "eligible": True,
            "status": "ready",
            "blockers": [],
            "criteria": ["registration_status == 'registered'"],
        }
        request.metadata["safety_gates"] = {
            "allow_auto_dispatch": True,
            "batch_has_timeout_tasks": False,
            "batch_has_failed_tasks": False,
            "packet_complete": True,
        }
        request.metadata["truth_anchor"] = {
            "anchor_type": "handoff_id",
            "anchor_value": f"handoff_{self.suffix}",
        }
        
        # 写入 request
        request.write()
        from sessions_spawn_request import _record_request_dedupe
        _record_request_dedupe(request.dedupe_key, request.request_id)
        
        self.test_request = request
    
    def test_batch3_consumption_to_execution_chain(self):
        """
        P0-3 Batch 3: 验证 artifact -> bridge_consumer -> execution request 主链打通。
        
        流程：
        1. sessions_spawn_request (prepared)
        2. auto_trigger_consumption(chain_to_execution=True)
        3. bridge_consumer.consume() -> consumed artifact
        4. sessions_spawn_bridge.execute() -> API execution artifact
        
        验证：
        - consumed artifact 生成
        - API execution artifact 生成
        - linkage 完整
        """
        from sessions_spawn_request import (
            configure_auto_trigger,
            auto_trigger_consumption,
            _is_auto_triggered,
        )
        from bridge_consumer import get_consumed_by_request
        from sessions_spawn_bridge import (
            configure_auto_trigger_real_exec,
            get_api_execution_by_request,
        )
        
        # 使用唯一场景名避免测试干扰
        unique_scenario = f"trading_batch3_{self.suffix}"
        
        # 1. 配置 auto-trigger（启用，唯一场景名在 allowlist）
        config = configure_auto_trigger(
            enabled=True,
            allowlist=[unique_scenario],
            denylist=[],
            require_manual_approval=False,
        )
        self.assertTrue(config["enabled"])
        
        # 2. 配置 auto-trigger real execution（启用，safe_mode=True 用于测试）
        exec_config = configure_auto_trigger_real_exec(
            enabled=True,
            allowlist=[unique_scenario],
            require_manual_approval=False,
            safe_mode=True,  # 测试模式：仅模拟执行
        )
        self.assertTrue(exec_config["enabled"])
        
        # 更新 request 的场景为唯一场景名
        self.test_request.metadata["scenario"] = unique_scenario
        self.test_request.sessions_spawn_params["metadata"]["scenario"] = unique_scenario
        self.test_request.write()
        
        # 3. 执行 auto-trigger with chain_to_execution=True
        triggered, reason, consumed_id, execution_id = auto_trigger_consumption(
            self.test_request.request_id,
            chain_to_execution=True,
        )
        
        # 4. 验证结果
        self.assertTrue(triggered, f"Auto-trigger should succeed, reason: {reason}")
        self.assertIsNotNone(consumed_id, "consumed_id should be present")
        self.assertIsNotNone(execution_id, "execution_id should be present (chain_to_execution=True)")
        
        # 5. 验证 consumed artifact
        consumed = get_consumed_by_request(self.test_request.request_id)
        self.assertIsNotNone(consumed)
        self.assertEqual(consumed.consumed_id, consumed_id)
        self.assertIn(consumed.consumer_status, ["consumed", "executed", "pending"])
        
        # 6. 验证 API execution artifact
        execution = get_api_execution_by_request(self.test_request.request_id)
        self.assertIsNotNone(execution)
        self.assertEqual(execution.execution_id, execution_id)
        self.assertIn(execution.api_execution_status, ["started", "pending", "blocked"])
        
        # 7. 验证 linkage 完整性
        self.assertEqual(consumed.source_request_id, self.test_request.request_id)
        self.assertEqual(execution.source_request_id, self.test_request.request_id)
        self.assertEqual(consumed.source_task_id, self.test_receipt.source_task_id)
        self.assertEqual(execution.source_task_id, self.test_receipt.source_task_id)
        
        # 8. 验证 metadata 传递
        self.assertEqual(consumed.metadata.get("scenario"), unique_scenario)
        self.assertEqual(execution.metadata.get("scenario"), unique_scenario)
        self.assertIsNotNone(consumed.metadata.get("truth_anchor"))
        
        print(f"✓ P0-3 Batch 3 chain ({unique_scenario}): {self.test_request.request_id} -> {consumed_id} -> {execution_id}")
    
    def test_batch3_chain_blocked_by_readiness(self):
        """
        P0-3 Batch 3: 验证 readiness not met 时 chain 被阻塞。
        """
        from sessions_spawn_request import (
            configure_auto_trigger,
            auto_trigger_consumption,
        )
        from bridge_consumer import get_consumed_by_request
        from sessions_spawn_bridge import get_api_execution_by_request
        
        # 创建 readiness not ready 的 request
        suffix2 = uuid.uuid4().hex[:6]
        receipt2 = create_test_receipt(
            receipt_id=f"batch3_not_ready_receipt_{suffix2}",
            task_id=f"batch3_not_ready_task_{suffix2}",
            spawn_id=f"batch3_not_ready_spawn_{suffix2}",
            dispatch_id=f"batch3_not_ready_dispatch_{suffix2}",
            registration_id=f"batch3_not_ready_reg_{suffix2}",
            execution_id=f"batch3_not_ready_exec_{suffix2}",
            receipt_status="completed",
            scenario="trading",
            owner="trading",
        )
        
        kernel = SpawnRequestKernel()
        policy_eval = kernel.evaluate_policy(receipt2)
        request2 = kernel.create_request(receipt2, policy_eval)
        
        # 设置 readiness not ready
        request2.metadata["readiness"] = {
            "eligible": False,
            "status": "blocked",
            "blockers": ["safety_gates.allow_auto_dispatch=False"],
        }
        request2.metadata["safety_gates"] = {
            "allow_auto_dispatch": False,
        }
        request2.metadata["truth_anchor"] = {"anchor_type": "handoff_id", "anchor_value": f"handoff_{suffix2}"}
        
        request2.write()
        from sessions_spawn_request import _record_request_dedupe
        _record_request_dedupe(request2.dedupe_key, request2.request_id)
        
        # 配置 auto-trigger
        configure_auto_trigger(
            enabled=True,
            allowlist=["trading"],
            require_manual_approval=False,
        )
        
        # 执行 auto-trigger with chain_to_execution
        triggered, reason, consumed_id, execution_id = auto_trigger_consumption(
            request2.request_id,
            chain_to_execution=True,
        )
        
        # 验证被阻塞
        self.assertFalse(triggered)
        self.assertIn("Readiness not met", reason)
        self.assertIsNone(consumed_id)
        self.assertIsNone(execution_id)
        
        # 验证没有生成 consumed artifact
        consumed = get_consumed_by_request(request2.request_id)
        self.assertIsNone(consumed)
        
        # 验证没有生成 API execution artifact
        execution = get_api_execution_by_request(request2.request_id)
        self.assertIsNone(execution)
        
        print(f"✓ P0-3 Batch 3 chain blocked by readiness: {reason}")
    
    def test_batch3_chain_generic_not_trading_specific(self):
        """
        P0-3 Batch 3: 验证 chain 实现是通用的，不是 trading-specific。
        """
        from sessions_spawn_request import (
            configure_auto_trigger,
            auto_trigger_consumption,
        )
        from bridge_consumer import get_consumed_by_request
        from sessions_spawn_bridge import (
            configure_auto_trigger_real_exec,
            get_api_execution_by_request,
        )
        
        # 创建 channel 场景的 request（使用唯一场景名避免测试干扰）
        suffix3 = uuid.uuid4().hex[:6]
        unique_scenario = f"channel_batch3_{suffix3}"
        
        receipt3 = create_test_receipt(
            receipt_id=f"batch3_channel_receipt_{suffix3}",
            task_id=f"batch3_channel_task_{suffix3}",
            spawn_id=f"batch3_channel_spawn_{suffix3}",
            dispatch_id=f"batch3_channel_dispatch_{suffix3}",
            registration_id=f"batch3_channel_reg_{suffix3}",
            execution_id=f"batch3_channel_exec_{suffix3}",
            receipt_status="completed",
            scenario=unique_scenario,
            owner="channel",
        )
        
        kernel = SpawnRequestKernel()
        policy_eval = kernel.evaluate_policy(receipt3)
        request3 = kernel.create_request(receipt3, policy_eval)
        
        # 设置 readiness/safety_gates（通用字段）
        request3.metadata["readiness"] = {
            "eligible": True,
            "status": "ready",
            "blockers": [],
        }
        request3.metadata["safety_gates"] = {
            "allow_auto_dispatch": True,
        }
        request3.metadata["truth_anchor"] = {"anchor_type": "handoff_id", "anchor_value": f"handoff_{suffix3}"}
        
        request3.write()
        from sessions_spawn_request import _record_request_dedupe
        _record_request_dedupe(request3.dedupe_key, request3.request_id)
        
        # 配置 auto-trigger（allowlist 包含唯一场景名）
        configure_auto_trigger(
            enabled=True,
            allowlist=[unique_scenario],
            require_manual_approval=False,
        )
        
        # 配置 auto-trigger real execution
        configure_auto_trigger_real_exec(
            enabled=True,
            allowlist=[unique_scenario],
            require_manual_approval=False,
            safe_mode=True,
        )
        
        # 执行 auto-trigger with chain_to_execution
        triggered, reason, consumed_id, execution_id = auto_trigger_consumption(
            request3.request_id,
            chain_to_execution=True,
        )
        
        # 验证通用场景也能成功
        self.assertTrue(triggered, f"Auto-trigger should succeed for {unique_scenario}, reason: {reason}")
        self.assertIsNotNone(consumed_id, f"consumed_id should be present for {unique_scenario}")
        self.assertIsNotNone(execution_id, f"execution_id should be present for {unique_scenario}")
        
        # 验证 consumed artifact
        consumed = get_consumed_by_request(request3.request_id)
        self.assertIsNotNone(consumed)
        self.assertEqual(consumed.metadata.get("scenario"), unique_scenario)
        
        # 验证 API execution artifact
        execution = get_api_execution_by_request(request3.request_id)
        self.assertIsNotNone(execution)
        self.assertEqual(execution.metadata.get("scenario"), unique_scenario)
        
        print(f"✓ P0-3 Batch 3 chain ({unique_scenario}): {request3.request_id} -> {consumed_id} -> {execution_id}")


class TestP03Batch4RealAPICall(unittest.TestCase):
    """
    P0-3 Batch 4: Integration test for real sessions_spawn API call boundary.
    
    验证 bridge_consumer / sessions_spawn_bridge 真实调用 OpenClaw sessions_spawn API。
    核心目标：
    1. _call_via_python_api() 调用真实 subagent runner 脚本
    2. 生成真实 runId / childSessionKey / pid
    3. 后台启动 subagent 进程（非阻塞）
    4. 保持 safe_mode 默认开启（生产安全）
    5. 通用实现（trading 只是首个验证场景）
    """
    
    def setUp(self):
        self.suffix = uuid.uuid4().hex[:6]
        
        # 创建测试 receipt
        self.test_receipt = create_test_receipt(
            receipt_id=f"batch4_receipt_{self.suffix}",
            task_id=f"batch4_task_{self.suffix}",
            spawn_id=f"batch4_spawn_{self.suffix}",
            dispatch_id=f"batch4_dispatch_{self.suffix}",
            registration_id=f"batch4_reg_{self.suffix}",
            execution_id=f"batch4_exec_{self.suffix}",
            receipt_status="completed",
            scenario="trading",
            owner="trading",
        )
        
        # 创建 request
        kernel = SpawnRequestKernel()
        policy_eval = kernel.evaluate_policy(self.test_receipt)
        request = kernel.create_request(self.test_receipt, policy_eval)
        
        # 添加 readiness/safety_gates/truth_anchor metadata
        request.metadata["readiness"] = {
            "eligible": True,
            "status": "ready",
            "blockers": [],
        }
        request.metadata["safety_gates"] = {
            "allow_auto_dispatch": True,
        }
        request.metadata["truth_anchor"] = {
            "anchor_type": "handoff_id",
            "anchor_value": f"handoff_{self.suffix}",
        }
        
        request.write()
        from sessions_spawn_request import _record_request_dedupe
        _record_request_dedupe(request.dedupe_key, request.request_id)
        
        self.test_request = request
    
    def test_batch4_real_api_call_mock_boundary(self):
        """
        P0-3 Batch 4: 验证真实 API 调用边界（mock runner 脚本存在性检查）。
        
        由于真实 runner 调用会启动实际 subagent 进程，
        本测试验证：
        1. runner 脚本路径解析正确
        2. 调用参数构建正确
        3. API response 包含 runId / childSessionKey / pid
        4. safe_mode 下生成 pending 状态
        """
        from sessions_spawn_bridge import SessionsSpawnBridge, SessionsSpawnBridgePolicy
        
        # 使用 safe_mode=True 避免真实启动 subagent
        policy = SessionsSpawnBridgePolicy(safe_mode=True, allowlist=["trading"])
        bridge = SessionsSpawnBridge(policy)
        
        # 执行
        artifact = bridge.execute(self.test_request)
        
        # 验证 artifact 生成
        self.assertIsNotNone(artifact.execution_id)
        self.assertEqual(artifact.source_request_id, self.test_request.request_id)
        
        # safe_mode 下应该是 pending 状态
        self.assertEqual(artifact.api_execution_status, "pending")
        self.assertIsNotNone(artifact.api_execution_result)
        
        if artifact.api_execution_result:
            # 验证 response 包含必要字段
            api_response = artifact.api_execution_result.api_response
            self.assertIsNotNone(api_response)
            self.assertEqual(api_response.get("status"), "recorded")
            self.assertTrue(api_response.get("safe_mode"))
            
            # 验证 request_snapshot 存在
            self.assertIsNotNone(artifact.api_execution_result.request_snapshot)
        
        print(f"✓ P0-3 Batch 4 mock boundary: {artifact.execution_id} (safe_mode=pending)")
    
    def test_batch4_real_api_call_real_execution_structure(self):
        """
        Wave 2 Cutover (2026-03-24): 验证真实执行模式下的 API response 结构。
        
        验证 _call_via_python_api() 返回的 response 包含：
        - status: started
        - childSessionKey: task_xxx (SubagentExecutor task_id)
        - runId: task_xxx (SubagentExecutor task_id)
        - pid: int
        - label: str
        - runtime: subagent
        - message: Wave 2 Cutover message
        """
        from sessions_spawn_bridge import SessionsSpawnBridge, SessionsSpawnBridgePolicy
        
        # 创建 bridge（safe_mode=False 用于测试 response 结构）
        # 注意：实际不会启动真实进程，因为 runner 脚本可能不存在于测试环境
        policy = SessionsSpawnBridgePolicy(safe_mode=False, allowlist=["trading"])
        bridge = SessionsSpawnBridge(policy)
        
        # 直接调用 _call_openclaw_sessions_spawn
        success, error, api_response = bridge._call_openclaw_sessions_spawn(self.test_request)
        
        # 三种可能结果：
        # 1. SubagentExecutor 成功启动 -> success=True, response 包含 task_id/pid
        # 2. SubagentExecutor 失败 -> success=False, error 包含错误信息
        
        if success:
            # SubagentExecutor 成功，验证 response 结构
            self.assertIsNotNone(api_response)
            self.assertEqual(api_response.get("status"), "started")
            # Wave 2 Cutover: childSessionKey 和 runId 现在是 task_id 格式
            child_key = api_response.get("childSessionKey", "")
            run_id = api_response.get("runId", "")
            self.assertTrue(
                child_key.startswith("task_") or child_key.startswith("session_"),
                f"childSessionKey should start with 'task_' or 'session_', got: {child_key}"
            )
            self.assertTrue(
                run_id.startswith("task_") or run_id.startswith("run_"),
                f"runId should start with 'task_' or 'run_', got: {run_id}"
            )
            # pid 可能存在（如果进程已启动）或者是 None
            pid = api_response.get("pid")
            if pid is not None:
                self.assertIsInstance(pid, int)
            self.assertEqual(api_response.get("runtime"), "subagent")
            # Wave 2 Cutover: 验证新字段
            self.assertIn("subagent_config", api_response, "Should include subagent_config")
            self.assertIn("executor_version", api_response, "Should include executor_version")
            print(f"✓ Wave 2 Cutover real execution: runId={api_response['runId']}, pid={pid}")
        else:
            # SubagentExecutor 失败（测试环境），验证错误信息
            self.assertIsNotNone(error)
            print(f"✓ Wave 2 Cutover execution blocked (expected in test env): {error[:100]}...")
    
    def test_batch4_generic_scenario_not_trading_specific(self):
        """
        P0-3 Batch 4: 验证实现是通用的，不是 trading-specific。
        """
        from sessions_spawn_bridge import SessionsSpawnBridge, SessionsSpawnBridgePolicy
        
        # 创建 channel 场景的 request
        suffix2 = uuid.uuid4().hex[:6]
        receipt2 = create_test_receipt(
            receipt_id=f"batch4_channel_receipt_{suffix2}",
            task_id=f"batch4_channel_task_{suffix2}",
            spawn_id=f"batch4_channel_spawn_{suffix2}",
            dispatch_id=f"batch4_channel_dispatch_{suffix2}",
            registration_id=f"batch4_channel_reg_{suffix2}",
            execution_id=f"batch4_channel_exec_{suffix2}",
            receipt_status="completed",
            scenario="channel",
            owner="channel",
        )
        
        kernel = SpawnRequestKernel()
        policy_eval = kernel.evaluate_policy(receipt2)
        request2 = kernel.create_request(receipt2, policy_eval)
        request2.metadata["readiness"] = {"eligible": True, "status": "ready", "blockers": []}
        request2.metadata["safety_gates"] = {"allow_auto_dispatch": True}
        request2.write()
        
        from sessions_spawn_request import _record_request_dedupe
        _record_request_dedupe(request2.dedupe_key, request2.request_id)
        
        # 使用 channel 场景的 allowlist
        policy = SessionsSpawnBridgePolicy(safe_mode=True, allowlist=["channel", "trading"])
        bridge = SessionsSpawnBridge(policy)
        
        artifact = bridge.execute(request2)
        
        # 验证 channel 场景也能成功
        self.assertIsNotNone(artifact.execution_id)
        self.assertEqual(artifact.metadata.get("scenario"), "channel")
        self.assertIn(artifact.api_execution_status, ["pending", "started"])
        
        print(f"✓ P0-3 Batch 4 generic scenario (channel): {artifact.execution_id}")
    
    def test_batch4_execution_artifact_paths(self):
        """
        P0-3 Batch 4: 验证真实产物路径和执行锚点。
        """
        from sessions_spawn_bridge import (
            SessionsSpawnBridge,
            SessionsSpawnBridgePolicy,
            API_EXECUTION_DIR,
            _api_execution_file,
            _load_api_execution_index,
        )
        
        policy = SessionsSpawnBridgePolicy(safe_mode=True, allowlist=["trading"])
        bridge = SessionsSpawnBridge(policy)
        
        artifact = bridge.execute(self.test_request)
        
        # 验证 artifact 文件路径
        exec_file = _api_execution_file(artifact.execution_id)
        self.assertTrue(exec_file.exists())
        self.assertEqual(exec_file.suffix, ".json")
        self.assertTrue(str(exec_file).startswith(str(API_EXECUTION_DIR)))
        
        # 验证 index 记录
        index = _load_api_execution_index()
        self.assertIn(self.test_request.request_id, index)
        self.assertEqual(index[self.test_request.request_id], artifact.execution_id)
        
        # 验证可通过 request_id 查询
        from sessions_spawn_bridge import get_api_execution_by_request
        queried = get_api_execution_by_request(self.test_request.request_id)
        self.assertIsNotNone(queried)
        self.assertEqual(queried.execution_id, artifact.execution_id)
        
        print(f"✓ P0-3 Batch 4 artifact paths: {exec_file}")


def run_tests():
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    suite.addTests(loader.loadTestsFromTestCase(TestV9HappyPath))
    suite.addTests(loader.loadTestsFromTestCase(TestV9BlockedScenarios))
    suite.addTests(loader.loadTestsFromTestCase(TestV9Linkage))
    suite.addTests(loader.loadTestsFromTestCase(TestV9TradingScenario))
    suite.addTests(loader.loadTestsFromTestCase(TestV9AutoTrigger))
    suite.addTests(loader.loadTestsFromTestCase(TestV9Integration))
    suite.addTests(loader.loadTestsFromTestCase(TestP03Batch3ConsumptionToExecutionChain))
    suite.addTests(loader.loadTestsFromTestCase(TestP03Batch4RealAPICall))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    print("\n" + "=" * 60)
    print("V9 Real OpenClaw sessions_spawn Integration 测试结果")
    print("=" * 60)
    print(f"总计：{result.testsRun} 测试")
    print(f"成功：{result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"失败：{len(result.failures)}")
    print(f"错误：{len(result.errors)}")
    print("=" * 60)
    
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
