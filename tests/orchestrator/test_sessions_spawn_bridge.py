#!/usr/bin/env python3
"""
test_sessions_spawn_bridge.py — V9 Real OpenClaw sessions_spawn Integration 测试

覆盖场景：
1. Happy path: request -> real API wrapper call (mock OpenClaw tool 层)
2. Blocked: blocked/duplicate/missing payload 不调用
3. Linkage: 真实执行结果 linkage 正确
4. Trading 场景首个样例
5. Auto-trigger real execution
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


def run_tests():
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    suite.addTests(loader.loadTestsFromTestCase(TestV9HappyPath))
    suite.addTests(loader.loadTestsFromTestCase(TestV9BlockedScenarios))
    suite.addTests(loader.loadTestsFromTestCase(TestV9Linkage))
    suite.addTests(loader.loadTestsFromTestCase(TestV9TradingScenario))
    suite.addTests(loader.loadTestsFromTestCase(TestV9AutoTrigger))
    suite.addTests(loader.loadTestsFromTestCase(TestV9Integration))
    
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
