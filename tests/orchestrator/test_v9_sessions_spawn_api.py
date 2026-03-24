#!/usr/bin/env python3
"""
test_v9_real_sessions_spawn.py — V9 功能验证脚本

快速验证 V9 Real OpenClaw sessions_spawn Integration 功能。
"""

import json
import sys
from pathlib import Path
from datetime import datetime
import uuid

# Add orchestrator directory to path (same pattern as other tests)
REPO_ROOT = Path(__file__).resolve().parents[2]
ORCHESTRATOR_DIR = REPO_ROOT / "runtime" / "orchestrator"
if str(ORCHESTRATOR_DIR) not in sys.path:
    sys.path.insert(0, str(ORCHESTRATOR_DIR))

from sessions_spawn_request import SessionsSpawnRequest, SpawnRequestKernel
from completion_receipt import CompletionReceiptArtifact, COMPLETION_RECEIPT_DIR, _completion_receipt_file
from sessions_spawn_bridge import (
    SessionsSpawnBridge,
    SessionsSpawnBridgePolicy,
    execute_sessions_spawn_api,
    list_api_executions,
    configure_auto_trigger_real_exec,
    get_auto_trigger_real_exec_status,
    API_EXECUTION_DIR,
)


def create_test_receipt(
    receipt_id: str,
    task_id: str,
    scenario: str = "trading",
) -> CompletionReceiptArtifact:
    """创建测试 receipt"""
    receipt = CompletionReceiptArtifact(
        receipt_id=receipt_id,
        source_spawn_execution_id=f"exec_{uuid.uuid4().hex[:8]}",
        source_spawn_id=f"spawn_{uuid.uuid4().hex[:8]}",
        source_dispatch_id=f"dispatch_{uuid.uuid4().hex[:8]}",
        source_registration_id=f"reg_{uuid.uuid4().hex[:8]}",
        source_task_id=task_id,
        receipt_status="completed",
        receipt_reason="V9 test receipt",
        receipt_time=datetime.now().isoformat(),
        result_summary="V9 test execution completed",
        dedupe_key=f"dedupe_{receipt_id}",
        business_result={"scenario": scenario, "test": "v9"},
        metadata={
            "source_execution_status": "started",
            "scenario": scenario,
            "owner": "v9_test",
            "truth_anchor": "v9_test",
        },
    )
    
    COMPLETION_RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
    receipt_file = _completion_receipt_file(receipt_id)
    tmp_file = receipt_file.with_suffix(".tmp")
    with open(tmp_file, "w") as f:
        json.dump(receipt.to_dict(), f, indent=2)
    tmp_file.replace(receipt_file)
    
    return receipt


def create_test_request(receipt: CompletionReceiptArtifact) -> SessionsSpawnRequest:
    """从 receipt 创建 test request"""
    kernel = SpawnRequestKernel()
    policy_eval = kernel.evaluate_policy(receipt)
    request = kernel.create_request(receipt, policy_eval)
    request.write()
    
    from sessions_spawn_request import _record_request_dedupe
    _record_request_dedupe(request.dedupe_key, request.request_id)
    
    return request


def main():
    print("=" * 70)
    print("V9 Real OpenClaw sessions_spawn Integration 功能验证")
    print("=" * 70)
    
    suffix = uuid.uuid4().hex[:6]
    
    # Test 1: Happy path
    print("\n[Test 1] Happy path: prepared request -> API call (safe mode)")
    receipt1 = create_test_receipt(
        receipt_id=f"v9_test_receipt_{suffix}",
        task_id=f"v9_test_task_{suffix}",
        scenario="trading",
    )
    request1 = create_test_request(receipt1)
    
    policy = SessionsSpawnBridgePolicy(safe_mode=True, allowlist=["trading"])
    bridge = SessionsSpawnBridge(policy)
    artifact = bridge.execute(request1)
    
    assert artifact.execution_id.startswith("exec_api_"), f"Invalid execution_id: {artifact.execution_id}"
    assert artifact.api_execution_status in ["started", "pending"], f"Unexpected status: {artifact.api_execution_status}"
    assert artifact.source_request_id == request1.request_id
    assert artifact.metadata.get("scenario") == "trading"
    
    print(f"  ✓ Execution ID: {artifact.execution_id}")
    print(f"  ✓ Status: {artifact.api_execution_status}")
    print(f"  ✓ Scenario: {artifact.metadata.get('scenario')}")
    
    # Test 2: Linkage verification
    print("\n[Test 2] Linkage verification")
    if artifact.api_execution_result:
        linkage = artifact.api_execution_result.linkage
        assert linkage is not None
        assert linkage["request_id"] == request1.request_id
        assert linkage["task_id"] == receipt1.source_task_id
        print(f"  ✓ Linkage: request_id={linkage['request_id'][:12]}..., task_id={linkage['task_id'][:12]}...")
    
    # Test 3: Blocked scenarios
    print("\n[Test 3] Blocked scenarios")
    receipt2 = create_test_receipt(
        receipt_id=f"v9_test_blocked_{suffix}",
        task_id=f"v9_test_blocked_{suffix}",
        scenario="generic",
    )
    request2 = create_test_request(receipt2)
    request2.spawn_request_status = "blocked"
    request2.write()
    
    artifact2 = bridge.execute(request2)
    assert artifact2.api_execution_status == "blocked"
    assert "Request status is 'blocked'" in artifact2.api_execution_reason
    print(f"  ✓ Blocked request status correctly rejected")
    
    # Test 4: Auto-trigger config
    print("\n[Test 4] Auto-trigger configuration")
    config = configure_auto_trigger_real_exec(
        enabled=True,
        allowlist=["trading"],
        require_manual_approval=False,
        safe_mode=True,
    )
    assert config["enabled"] == True
    assert config["allowlist"] == ["trading"]
    print(f"  ✓ Auto-trigger config: enabled={config['enabled']}, allowlist={config['allowlist']}")
    
    # Test 5: Status query
    print("\n[Test 5] Auto-trigger status query")
    status = get_auto_trigger_real_exec_status()
    assert "config" in status
    assert status["config"]["enabled"] == True
    print(f"  ✓ Executed count: {status.get('executed_count', 0)}")
    print(f"  ✓ Pending requests: {len(status.get('pending_requests', []))}")
    
    # Test 6: List API executions
    print("\n[Test 6] List API executions")
    executions = list_api_executions(scenario="trading", limit=10)
    assert len(executions) > 0
    print(f"  ✓ Found {len(executions)} trading scenario executions")
    
    # Test 7: Artifact file verification
    print("\n[Test 7] Artifact file verification")
    exec_file = API_EXECUTION_DIR / f"{artifact.execution_id}.json"
    assert exec_file.exists(), f"Artifact file not found: {exec_file}"
    
    with open(exec_file, "r") as f:
        data = json.load(f)
    assert data["execution_version"] == "sessions_spawn_api_execution_v1"
    assert data["api_execution_status"] in ["started", "pending", "blocked", "failed"]
    print(f"  ✓ Artifact file: {exec_file}")
    print(f"  ✓ Version: {data['execution_version']}")
    
    # Summary
    print("\n" + "=" * 70)
    print("V9 功能验证结果")
    print("=" * 70)
    print("✅ 所有测试通过")
    print(f"✅ 新增文件：{exec_file.parent}")
    print(f"✅ 测试执行：{artifact.execution_id}")
    print(f"✅ 当前链路：")
    print("   proposal -> registration -> auto-dispatch -> spawn closure")
    print("   -> spawn execution -> completion receipt -> sessions_spawn request")
    print("   -> bridge consumption -> real sessions_spawn API execution (V9)")
    print("=" * 70)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
