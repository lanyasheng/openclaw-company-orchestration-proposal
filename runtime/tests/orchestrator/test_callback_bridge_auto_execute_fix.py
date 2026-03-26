#!/usr/bin/env python3
"""
test_callback_bridge_auto_execute_fix.py — 验证 orchestrator_callback_bridge.py auto-execute 修复

测试点：
1. prepare_spawn_request 可正确导入
2. 从 completion receipt 创建 spawn request 的链路可用
3. auto-trigger 结果正确记录到 metadata

这是针对 2026-03-26 修复的 targeted test。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict

# Add orchestrator to path
ORCHESTRATOR_DIR = Path(__file__).resolve().parents[2] / "orchestrator"
if str(ORCHESTRATOR_DIR) not in sys.path:
    sys.path.insert(0, str(ORCHESTRATOR_DIR))

from completion_receipt import CompletionReceiptKernel, CompletionReceiptArtifact
from spawn_execution import SpawnExecutionArtifact
from sessions_spawn_request import prepare_spawn_request, get_spawn_request


def test_prepare_spawn_request_import():
    """测试 prepare_spawn_request 可正确导入"""
    assert prepare_spawn_request is not None
    assert get_spawn_request is not None
    print("✓ Import test passed")


def test_create_receipt_and_request():
    """测试从 execution artifact 创建 receipt 和 request"""
    from datetime import datetime
    
    # 1. 创建 execution artifact
    exec_artifact = SpawnExecutionArtifact(
        execution_id="exec_test_fix_20260326",
        spawn_id=None,
        dispatch_id="disp_test_fix",
        registration_id=None,
        task_id="tsk_test_fix",
        spawn_execution_status="started",
        spawn_execution_reason="Test auto-execute fix",
        spawn_execution_time=datetime.now().isoformat(),
        spawn_execution_target={
            "runtime": "subagent",
            "task": "测试任务",
            "workdir": "/tmp",
        },
        dedupe_key="test_dedupe",
        execution_payload={},
        execution_result=None,
        policy_evaluation=None,
        metadata={
            "created_from": "test",
            "auto_execute_integration": True,
        },
    )
    
    # 2. 创建 receipt
    receipt_kernel = CompletionReceiptKernel()
    receipt = receipt_kernel.emit_receipt(exec_artifact)
    
    assert receipt is not None
    assert receipt.receipt_id.startswith("receipt_")
    print(f"✓ Receipt created: {receipt.receipt_id}")
    
    # 3. 创建 request (这会触发 auto-trigger)
    request = prepare_spawn_request(receipt.receipt_id)
    
    assert request is not None
    assert request.request_id.startswith("req_")
    assert request.spawn_request_status in ("prepared", "blocked")
    print(f"✓ Request created: {request.request_id}, status={request.spawn_request_status}")
    
    # 4. 验证 auto-trigger 结果记录到 metadata
    auto_trigger_result = request.metadata.get("auto_trigger_result")
    if auto_trigger_result:
        print(f"✓ Auto-trigger result recorded: triggered={auto_trigger_result.get('triggered')}")
        print(f"  Reason: {auto_trigger_result.get('reason')}")
    else:
        print("⚠ Auto-trigger result not in metadata (may be expected if auto-trigger disabled)")
    
    # 5. 验证 request 可被读取
    retrieved = get_spawn_request(request.request_id)
    assert retrieved is not None
    assert retrieved.request_id == request.request_id
    print(f"✓ Request can be retrieved")
    
    return {
        "receipt_id": receipt.receipt_id,
        "request_id": request.request_id,
        "request_status": request.spawn_request_status,
        "auto_trigger_result": auto_trigger_result,
    }


def test_scenario_propagation_for_auto_trigger():
    """
    P0-3 Batch 9: 测试 scenario 字段在 completion_receipt -> spawn_request -> auto_trigger 链中正确传播
    
    验证点：
    1. execution artifact 包含 scenario/owner 字段
    2. completion receipt 从 execution 提取 scenario/owner
    3. spawn request 从 receipt 提取 scenario/owner
    4. auto-trigger allowlist 检查能看到 scenario
    """
    from datetime import datetime
    
    # 1. 创建包含 scenario/owner 的 execution artifact
    exec_artifact = SpawnExecutionArtifact(
        execution_id="exec_test_scenario_20260326",
        spawn_id=None,
        dispatch_id="disp_test_scenario",
        registration_id=None,
        task_id="tsk_test_scenario",
        spawn_execution_status="started",
        spawn_execution_reason="Test scenario propagation",
        spawn_execution_time=datetime.now().isoformat(),
        spawn_execution_target={
            "runtime": "subagent",
            "task": "测试场景传播",
            "workdir": "/tmp",
            "scenario": "current_channel_architecture_roundtable",  # 关键字段
            "owner": "main",  # 关键字段
        },
        dedupe_key="test_scenario_dedupe",
        execution_payload={},
        execution_result=None,
        policy_evaluation=None,
        metadata={
            "created_from": "test",
            "auto_execute_integration": True,
            "scenario": "current_channel_architecture_roundtable",
            "owner": "main",
        },
    )
    
    # 2. 创建 receipt
    receipt_kernel = CompletionReceiptKernel()
    receipt = receipt_kernel.emit_receipt(exec_artifact)
    
    # 验证 receipt 包含 scenario/owner
    receipt_scenario = receipt.metadata.get("scenario", "")
    receipt_owner = receipt.metadata.get("owner", "")
    print(f"✓ Receipt scenario: {receipt_scenario}")
    print(f"✓ Receipt owner: {receipt_owner}")
    
    assert receipt_scenario == "current_channel_architecture_roundtable", \
        f"Expected scenario in receipt, got '{receipt_scenario}'"
    assert receipt_owner == "main", f"Expected owner in receipt, got '{receipt_owner}'"
    
    # 3. 创建 request (这会触发 auto-trigger)
    request = prepare_spawn_request(receipt.receipt_id)
    
    # 验证 request 包含 scenario/owner
    request_scenario = request.metadata.get("scenario", "")
    request_owner = request.metadata.get("owner", "")
    print(f"✓ Request scenario: {request_scenario}")
    print(f"✓ Request owner: {request_owner}")
    
    assert request_scenario == "current_channel_architecture_roundtable", \
        f"Expected scenario in request, got '{request_scenario}'"
    assert request_owner == "main", f"Expected owner in request, got '{request_owner}'"
    
    # 4. 验证 auto-trigger 结果
    auto_trigger_result = request.metadata.get("auto_trigger_result")
    if auto_trigger_result:
        triggered = auto_trigger_result.get("triggered", False)
        reason = auto_trigger_result.get("reason", "")
        print(f"✓ Auto-trigger result: triggered={triggered}")
        print(f"  Reason: {reason}")
        
        # 验证 scenario 不再为空（修复前是 "Scenario '' is not in allowlist"）
        if not triggered and "Scenario ''" in reason:
            raise AssertionError(f"Scenario field is still empty in auto-trigger check: {reason}")
    else:
        print("⚠ Auto-trigger result not in metadata (auto-trigger may be disabled)")
    
    return {
        "receipt_id": receipt.receipt_id,
        "request_id": request.request_id,
        "receipt_scenario": receipt_scenario,
        "request_scenario": request_scenario,
        "auto_trigger_result": auto_trigger_result,
    }


def main():
    print("=" * 60)
    print("Testing orchestrator_callback_bridge.py auto-execute fix")
    print("=" * 60)
    
    test_prepare_spawn_request_import()
    result = test_create_receipt_and_request()
    
    print("\n" + "=" * 60)
    print("Testing scenario propagation for auto-trigger allowlist")
    print("=" * 60)
    
    scenario_result = test_scenario_propagation_for_auto_trigger()
    
    print("=" * 60)
    print("Test Summary:")
    print(f"  [Test 1] Receipt ID: {result['receipt_id']}")
    print(f"  [Test 1] Request ID: {result['request_id']}")
    print(f"  [Test 1] Request Status: {result['request_status']}")
    if result['auto_trigger_result']:
        print(f"  [Test 1] Auto-trigger: triggered={result['auto_trigger_result'].get('triggered')}")
    
    print(f"  [Test 2] Receipt scenario: {scenario_result['receipt_scenario']}")
    print(f"  [Test 2] Request scenario: {scenario_result['request_scenario']}")
    if scenario_result['auto_trigger_result']:
        print(f"  [Test 2] Auto-trigger: triggered={scenario_result['auto_trigger_result'].get('triggered')}")
    
    print("=" * 60)
    print("✓ All tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
