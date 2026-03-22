#!/usr/bin/env python3
"""
test_bridge_consumer.py — V7 Bridge Consumer 测试

覆盖场景：
1. Happy path: consume prepared request
2. Blocked: request status 不符不消费
3. Duplicate: 同一 request 不重复消费
4. Missing request: request 不存在
5. Linkage: 完整 linkage 验证
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
    SpawnRequestPolicy,
    SpawnRequestKernel,
    get_spawn_request,
    list_spawn_requests,
    SPAWN_REQUEST_DIR,
    _spawn_request_file,
)
from completion_receipt import (
    CompletionReceiptArtifact,
    ReceiptStatus,
    COMPLETION_RECEIPT_DIR,
    _completion_receipt_file,
)
from bridge_consumer import (
    BridgeConsumer,
    BridgeConsumerPolicy,
    BridgeConsumedArtifact,
    consume_request,
    list_consumed_artifacts,
    get_consumed_artifact,
    get_consumed_by_request,
    build_consumption_summary,
    BRIDGE_CONSUMED_DIR,
    _is_already_consumed,
    _load_consumed_index,
    CONSUMED_VERSION,
)


def create_test_receipt(
    receipt_id: str,
    task_id: str,
    spawn_id: str,
    dispatch_id: str,
    registration_id: str,
    execution_id: str,
    receipt_status: str = "completed",
    scenario: str = "generic",
    owner: str = "test_owner",
) -> CompletionReceiptArtifact:
    """创建测试 receipt 并写入文件"""
    receipt = CompletionReceiptArtifact(
        receipt_id=receipt_id,
        source_spawn_execution_id=execution_id,
        source_spawn_id=spawn_id,
        source_dispatch_id=dispatch_id,
        source_registration_id=registration_id,
        source_task_id=task_id,
        receipt_status=receipt_status,
        receipt_reason="Test receipt",
        receipt_time=datetime.now().isoformat(),
        result_summary="Test execution completed",
        dedupe_key=f"dedupe_{receipt_id}",
        business_result={"test": "data"},
        metadata={
            "source_execution_status": "started" if receipt_status == "completed" else "failed",
            "scenario": scenario,
            "owner": owner,
            "truth_anchor": "test_anchor",
        },
    )
    
    # 写入文件
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
    """从 receipt 创建测试 request 并写入文件"""
    # 使用 kernel 创建 request
    kernel = SpawnRequestKernel()
    
    # 评估 policy
    policy_eval = kernel.evaluate_policy(receipt)
    
    # 强制设置状态（用于测试 blocked 场景）
    request = kernel.create_request(receipt, policy_eval)
    
    # 如果需要 blocked 状态，手动修改
    if request_status == "blocked":
        request.spawn_request_status = "blocked"
        request.spawn_request_reason = "Test blocked status"
    
    # 写入文件
    request.write()
    
    # 记录 dedupe
    from sessions_spawn_request import _record_request_dedupe
    if request.spawn_request_status == "prepared":
        _record_request_dedupe(request.dedupe_key, request.request_id)
    
    return request


class TestBridgeConsumerHappyPath(unittest.TestCase):
    """Happy path: consume prepared request"""
    
    def setUp(self):
        """创建测试用的 receipt 和 request"""
        self.suffix = uuid.uuid4().hex[:6]
        
        # 创建测试 receipt
        self.test_receipt = create_test_receipt(
            receipt_id=f"test_receipt_happy_{self.suffix}",
            task_id=f"test_task_happy_{self.suffix}",
            spawn_id=f"test_spawn_happy_{self.suffix}",
            dispatch_id=f"test_dispatch_happy_{self.suffix}",
            registration_id=f"test_reg_happy_{self.suffix}",
            execution_id=f"test_exec_happy_{self.suffix}",
            receipt_status="completed",
            scenario="generic",
            owner="test_owner",
        )
        
        # 创建 request
        self.test_request = create_test_request_from_receipt(self.test_receipt, "prepared")
    
    def test_consume_prepared_request(self):
        """测试消费 prepared request"""
        # 消费 request
        policy = BridgeConsumerPolicy(
            require_request_status="prepared",
            prevent_duplicate=True,
            simulate_only=True,
        )
        
        artifact = consume_request(self.test_request.request_id, policy)
        
        # 验证 consumed artifact
        self.assertIsNotNone(artifact)
        self.assertEqual(artifact.consumer_status, "consumed")
        self.assertIn("Policy evaluation passed", artifact.consumer_reason)
        
        # 验证 linkage
        self.assertEqual(artifact.source_request_id, self.test_request.request_id)
        self.assertEqual(artifact.source_receipt_id, self.test_receipt.receipt_id)
        self.assertEqual(artifact.source_task_id, self.test_receipt.source_task_id)
        self.assertEqual(artifact.source_spawn_id, self.test_receipt.source_spawn_id)
        self.assertEqual(artifact.source_dispatch_id, self.test_receipt.source_dispatch_id)
        
        # 验证 execution envelope
        self.assertIn("sessions_spawn_params", artifact.execution_envelope)
        self.assertIn("execution_context", artifact.execution_envelope)
        self.assertEqual(artifact.execution_envelope["consume_mode"], "simulate")
        
        # 验证 artifact 已写入文件
        artifact_file = BRIDGE_CONSUMED_DIR / f"{artifact.consumed_id}.json"
        self.assertTrue(artifact_file.exists())
        
        # 验证版本
        self.assertEqual(artifact.to_dict()["consumed_version"], CONSUMED_VERSION)
    
    def test_execution_envelope_contains_linkage(self):
        """测试 execution envelope 包含完整 linkage"""
        artifact = consume_request(self.test_request.request_id)
        
        envelope = artifact.execution_envelope
        context = envelope.get("execution_context", {})
        
        # 验证 linkage 完整性
        self.assertEqual(context["request_id"], self.test_request.request_id)
        self.assertEqual(context["receipt_id"], self.test_receipt.receipt_id)
        self.assertEqual(context["execution_id"], self.test_receipt.source_spawn_execution_id)
        self.assertEqual(context["spawn_id"], self.test_receipt.source_spawn_id)
        self.assertEqual(context["dispatch_id"], self.test_receipt.source_dispatch_id)
        self.assertEqual(context["registration_id"], self.test_receipt.source_registration_id)
        self.assertEqual(context["task_id"], self.test_receipt.source_task_id)
        self.assertEqual(context["scenario"], "generic")


class TestBridgeConsumerBlocked(unittest.TestCase):
    """Blocked: request status 不符不消费"""
    
    def setUp(self):
        """创建测试用的 receipt 和 blocked request"""
        self.suffix = uuid.uuid4().hex[:6]
        
        # 创建测试 receipt
        self.test_receipt = create_test_receipt(
            receipt_id=f"test_receipt_blocked_{self.suffix}",
            task_id=f"test_task_blocked_{self.suffix}",
            spawn_id=f"test_spawn_blocked_{self.suffix}",
            dispatch_id=f"test_dispatch_blocked_{self.suffix}",
            registration_id=f"test_reg_blocked_{self.suffix}",
            execution_id=f"test_exec_blocked_{self.suffix}",
            receipt_status="completed",
            scenario="generic",
            owner="test_owner",
        )
        
        # 创建 blocked request
        self.test_request = create_test_request_from_receipt(self.test_receipt, "blocked")
    
    def test_blocked_request_not_consumed(self):
        """测试 blocked request 不被消费"""
        policy = BridgeConsumerPolicy(
            require_request_status="prepared",  # 要求 prepared
            prevent_duplicate=True,
            simulate_only=True,
        )
        
        artifact = consume_request(self.test_request.request_id, policy)
        
        # 验证被阻塞
        self.assertEqual(artifact.consumer_status, "blocked")
        self.assertIn("Request status is 'blocked'", artifact.consumer_reason)
        
        # 验证 linkage 仍然完整
        self.assertEqual(artifact.source_request_id, self.test_request.request_id)
        self.assertEqual(artifact.source_receipt_id, self.test_receipt.receipt_id)
    
    def test_policy_evaluation_checks(self):
        """测试 policy evaluation 包含详细 checks"""
        consumer = BridgeConsumer()
        request = self.test_request
        
        evaluation = consumer.evaluate_policy(request)
        
        # 验证 checks 存在
        self.assertIn("checks", evaluation)
        self.assertIn("blocked_reasons", evaluation)
        self.assertFalse(evaluation["eligible"])
        
        # 验证至少有一个 check 失败
        checks = evaluation["checks"]
        failed_checks = [c for c in checks if not c["passed"]]
        self.assertGreater(len(failed_checks), 0)


class TestBridgeConsumerDuplicate(unittest.TestCase):
    """Duplicate: 同一 request 不重复消费"""
    
    def setUp(self):
        """创建测试用的 receipt 和 request"""
        self.suffix = uuid.uuid4().hex[:6]
        
        # 创建测试 receipt
        self.test_receipt = create_test_receipt(
            receipt_id=f"test_receipt_dup_{self.suffix}",
            task_id=f"test_task_dup_{self.suffix}",
            spawn_id=f"test_spawn_dup_{self.suffix}",
            dispatch_id=f"test_dispatch_dup_{self.suffix}",
            registration_id=f"test_reg_dup_{self.suffix}",
            execution_id=f"test_exec_dup_{self.suffix}",
            receipt_status="completed",
            scenario="generic",
            owner="test_owner",
        )
        
        # 创建 request
        self.test_request = create_test_request_from_receipt(self.test_receipt, "prepared")
    
    def test_no_duplicate_consumption(self):
        """测试同一 request 不重复消费"""
        # 第一次消费
        artifact1 = consume_request(self.test_request.request_id)
        self.assertEqual(artifact1.consumer_status, "consumed")
        
        # 第二次消费（应该返回已存在的 artifact）
        artifact2 = consume_request(self.test_request.request_id)
        
        # 验证是同一个 artifact
        self.assertEqual(artifact1.consumed_id, artifact2.consumed_id)
        
        # 验证去重索引
        self.assertTrue(_is_already_consumed(self.test_request.request_id))
        index = _load_consumed_index()
        self.assertIn(self.test_request.request_id, index)
    
    def test_consumed_artifact_retrieval(self):
        """测试通过 request_id 获取 consumed artifact"""
        # 先消费
        artifact = consume_request(self.test_request.request_id)
        
        # 通过 request_id 获取
        retrieved = get_consumed_by_request(self.test_request.request_id)
        
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.consumed_id, artifact.consumed_id)
        self.assertEqual(retrieved.source_request_id, self.test_request.request_id)


class TestBridgeConsumerMissingRequest(unittest.TestCase):
    """Missing: request 不存在"""
    
    def test_missing_request_raises_error(self):
        """测试消费不存在的 request 抛出错误"""
        with self.assertRaises(ValueError) as context:
            consume_request(f"nonexistent_request_{uuid.uuid4().hex[:6]}")
        
        self.assertIn("not found", str(context.exception))


class TestBridgeConsumerLinkage(unittest.TestCase):
    """Linkage: 完整 linkage 验证"""
    
    def setUp(self):
        """创建测试用的 receipt 和 request"""
        self.suffix = uuid.uuid4().hex[:6]
        
        # 创建测试 receipt
        self.test_receipt = create_test_receipt(
            receipt_id=f"test_receipt_link_{self.suffix}",
            task_id=f"test_task_link_{self.suffix}",
            spawn_id=f"test_spawn_link_{self.suffix}",
            dispatch_id=f"test_dispatch_link_{self.suffix}",
            registration_id=f"test_reg_link_{self.suffix}",
            execution_id=f"test_exec_link_{self.suffix}",
            receipt_status="completed",
            scenario="trading_roundtable_phase1",
            owner="trading",
        )
        
        # 创建 request
        self.test_request = create_test_request_from_receipt(self.test_receipt, "prepared")
        
        # 消费
        self.consumed = consume_request(self.test_request.request_id)
    
    def test_complete_linkage_chain(self):
        """测试完整 linkage 链"""
        linkage = self.consumed.get_linkage()
        
        # 验证所有 linkage 字段
        self.assertEqual(linkage["consumed_id"], self.consumed.consumed_id)
        self.assertEqual(linkage["request_id"], self.test_request.request_id)
        self.assertEqual(linkage["receipt_id"], self.test_receipt.receipt_id)
        self.assertEqual(linkage["execution_id"], self.test_receipt.source_spawn_execution_id)
        self.assertEqual(linkage["spawn_id"], self.test_receipt.source_spawn_id)
        self.assertEqual(linkage["dispatch_id"], self.test_receipt.source_dispatch_id)
        self.assertEqual(linkage["registration_id"], self.test_receipt.source_registration_id)
        self.assertEqual(linkage["task_id"], self.test_receipt.source_task_id)
    
    def test_list_consumed_by_scenario(self):
        """测试按 scenario 过滤 consumed artifacts"""
        # 列出 trading 场景
        artifacts = list_consumed_artifacts(scenario="trading_roundtable_phase1")
        
        # 应该至少包含我们刚创建的
        trading_artifacts = [a for a in artifacts if a.consumed_id == self.consumed.consumed_id]
        self.assertEqual(len(trading_artifacts), 1)
    
    def test_consumption_summary(self):
        """测试消费 summary"""
        summary = build_consumption_summary()
        
        # 验证 summary 结构
        self.assertIn("total_consumed", summary)
        self.assertIn("by_status", summary)
        self.assertIn("by_scenario", summary)
        self.assertIn("recent_consumed", summary)
        
        # 验证至少有一个 consumed
        self.assertGreater(summary["total_consumed"], 0)
        
        # 验证 status 统计
        self.assertIn("consumed", summary["by_status"])
        self.assertGreater(summary["by_status"]["consumed"], 0)


class TestBridgeConsumerPolicy(unittest.TestCase):
    """Policy 配置测试"""
    
    def test_custom_policy(self):
        """测试自定义 policy"""
        self.suffix = uuid.uuid4().hex[:6]
        
        # 创建测试 receipt
        receipt = create_test_receipt(
            receipt_id=f"test_receipt_policy_{self.suffix}",
            task_id=f"test_task_policy_{self.suffix}",
            spawn_id=f"test_spawn_policy_{self.suffix}",
            dispatch_id=f"test_dispatch_policy_{self.suffix}",
            registration_id=f"test_reg_policy_{self.suffix}",
            execution_id=f"test_exec_policy_{self.suffix}",
            receipt_status="completed",
            scenario="generic",
            owner="test_owner",
        )
        
        request = create_test_request_from_receipt(receipt, "prepared")
        
        # 自定义 policy：要求 blocked 状态
        policy = BridgeConsumerPolicy(
            require_request_status="blocked",  # 要求 blocked
            prevent_duplicate=False,  # 允许重复
            simulate_only=True,
            require_metadata_fields=[],  # 不要求 metadata 字段
        )
        
        consumer = BridgeConsumer(policy)
        evaluation = consumer.evaluate_policy(request)
        
        # 验证 policy 生效
        # request 是 prepared，但 policy 要求 blocked，所以不匹配
        self.assertFalse(evaluation["eligible"])
        self.assertTrue(any("Request status" in reason for reason in evaluation["blocked_reasons"]))
    
    def test_policy_serialization(self):
        """测试 policy 序列化"""
        policy = BridgeConsumerPolicy(
            require_request_status="prepared",
            prevent_duplicate=True,
            simulate_only=False,
            require_metadata_fields=["dispatch_id", "spawn_id", "receipt_id"],
        )
        
        # 序列化
        policy_dict = policy.to_dict()
        self.assertEqual(policy_dict["require_request_status"], "prepared")
        self.assertEqual(policy_dict["prevent_duplicate"], True)
        self.assertEqual(policy_dict["simulate_only"], False)
        self.assertEqual(policy_dict["require_metadata_fields"], ["dispatch_id", "spawn_id", "receipt_id"])
        
        # 反序列化
        restored = BridgeConsumerPolicy.from_dict(policy_dict)
        self.assertEqual(restored.require_request_status, policy.require_request_status)
        self.assertEqual(restored.prevent_duplicate, policy.prevent_duplicate)
        self.assertEqual(restored.simulate_only, policy.simulate_only)
        self.assertEqual(restored.require_metadata_fields, policy.require_metadata_fields)


class TestBridgeConsumerArtifact(unittest.TestCase):
    """Artifact 序列化测试"""
    
    def test_artifact_serialization(self):
        """测试 consumed artifact 序列化"""
        artifact = BridgeConsumedArtifact(
            consumed_id="test_consumed_001",
            source_request_id="req_001",
            source_receipt_id="receipt_001",
            source_execution_id="exec_001",
            source_spawn_id="spawn_001",
            source_dispatch_id="dispatch_001",
            source_registration_id="reg_001",
            source_task_id="task_001",
            consumer_status="consumed",
            consumer_reason="Test consumption",
            consumer_time=datetime.now().isoformat(),
            execution_envelope={
                "sessions_spawn_params": {"task": "test"},
                "execution_context": {"scenario": "generic"},
            },
            dedupe_key="test_dedupe",
            metadata={"test": "artifact"},
        )
        
        # 序列化
        artifact_dict = artifact.to_dict()
        self.assertEqual(artifact_dict["consumed_version"], CONSUMED_VERSION)
        self.assertEqual(artifact_dict["consumed_id"], "test_consumed_001")
        self.assertEqual(artifact_dict["consumer_status"], "consumed")
        
        # 反序列化
        restored = BridgeConsumedArtifact.from_dict(artifact_dict)
        self.assertEqual(restored.consumed_id, artifact.consumed_id)
        self.assertEqual(restored.source_request_id, artifact.source_request_id)
        self.assertEqual(restored.consumer_status, artifact.consumer_status)
        self.assertEqual(restored.execution_envelope, artifact.execution_envelope)
    
    def test_artifact_write_read(self):
        """测试 artifact 写入和读取"""
        artifact = BridgeConsumedArtifact(
            consumed_id=f"test_consumed_{uuid.uuid4().hex[:6]}",
            source_request_id="req_002",
            source_receipt_id="receipt_002",
            source_execution_id="exec_002",
            source_spawn_id="spawn_002",
            source_dispatch_id="dispatch_002",
            source_registration_id="reg_002",
            source_task_id="task_002",
            consumer_status="consumed",
            consumer_reason="Test write/read",
            consumer_time=datetime.now().isoformat(),
            execution_envelope={"test": "envelope"},
            dedupe_key="test_dedupe_2",
        )
        
        # 写入
        file_path = artifact.write()
        self.assertTrue(file_path.exists())
        
        # 读取
        retrieved = get_consumed_artifact(artifact.consumed_id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.consumed_id, artifact.consumed_id)
        self.assertEqual(retrieved.consumer_status, artifact.consumer_status)


if __name__ == "__main__":
    # 运行测试
    unittest.main(verbosity=2)
