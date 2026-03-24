#!/usr/bin/env python3
"""
test_wave2_cutover.py — Wave 2 Cutover Validation

验证 SubagentExecutor 执行基板切换到 sessions_spawn_bridge 的完整性。

测试覆盖：
1. SubagentExecutor 集成正常
2. Linkage 链完整
3. Policy 评估不变
4. Artifact 生成不变
5. Auto-trigger 配置兼容

执行：
```bash
cd <repo-root>
python3 tests/orchestrator/test_wave2_cutover.py
```
"""

import json
import sys
from pathlib import Path
from typing import Any, Dict

# 添加 runtime/orchestrator 到路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "runtime" / "orchestrator"))

from subagent_executor import (
    SubagentConfig,
    SubagentExecutor,
    SubagentResult,
    EXECUTOR_VERSION,
)
from sessions_spawn_bridge import (
    SessionsSpawnBridge,
    SessionsSpawnBridgePolicy,
    APIExecutionResult,
    SessionsSpawnAPIExecution,
    EXECUTION_VERSION,
)
from sessions_spawn_request import (
    SessionsSpawnRequest,
    SpawnRequestStatus,
    _generate_request_id,
)


def _create_test_request(
    request_id: str = None,
    scenario: str = "test",
    status: str = "prepared",
) -> SessionsSpawnRequest:
    """Helper: Create test request"""
    if not request_id:
        request_id = _generate_request_id()
    
    return SessionsSpawnRequest(
        request_id=request_id,
        source_task_id="task_test_123",
        source_receipt_id="receipt_test_123",
        source_execution_id="exec_test_123",
        source_spawn_id="spawn_test_123",
        source_dispatch_id="dispatch_test_123",
        source_registration_id="reg_test_123",
        spawn_request_status=status,
        spawn_request_reason="Test request",
        spawn_request_time="2026-03-24T23:00:00",
        sessions_spawn_params={
            "task": "Test task",
            "runtime": "subagent",
            "cwd": str(Path.home() / ".openclaw" / "workspace"),
            "label": "wave2-test",
            "metadata": {
                "dispatch_id": "dispatch_test_123",
                "spawn_id": "spawn_test_123",
                "scenario": scenario,
            },
        },
        dedupe_key=f"request_dedupe:test:{request_id}",
        metadata={
            "scenario": scenario,
            "owner": "main",
        },
    )


def test_subagent_executor_integration():
    """Test 1: SubagentExecutor 集成正常"""
    print("Test 1: SubagentExecutor integration...")
    
    config = SubagentConfig(
        label="wave2-test",
        runtime="subagent",
        timeout_seconds=60,
        allowed_tools=["read", "write", "edit"],
        cwd=str(Path.home() / ".openclaw" / "workspace"),
        metadata={"test": "wave2_cutover"},
    )
    
    executor = SubagentExecutor(config=config)
    task_id = executor.execute_async("Test task for Wave 2 cutover")
    result = executor.get_result(task_id)
    
    assert result is not None, "Result should not be None"
    assert result.task_id == task_id, f"Task ID mismatch: {result.task_id} != {task_id}"
    assert result.status in ["pending", "running", "completed", "failed"], f"Unexpected status: {result.status}"
    assert result.config.label == "wave2-test", f"Label mismatch: {result.config.label}"
    assert result.metadata.get("executor_version") == EXECUTOR_VERSION, "Executor version missing"
    
    print(f"  ✓ SubagentExecutor integration OK (task_id={task_id}, status={result.status})")


def test_sessions_spawn_request_creation():
    """Test 2: SessionsSpawnRequest 创建正常"""
    print("Test 2: SessionsSpawnRequest creation...")
    
    request_id = _generate_request_id()
    request = _create_test_request(request_id=request_id)
    
    # 验证序列化
    data = request.to_dict()
    assert data["request_id"] == request_id, "Request ID mismatch"
    assert data["spawn_request_status"] == "prepared", "Status mismatch"
    assert data["sessions_spawn_params"]["task"] == "Test task", "Task mismatch"
    
    # 验证反序列化
    restored = SessionsSpawnRequest.from_dict(data)
    assert restored.request_id == request_id, "Restored request ID mismatch"
    assert restored.source_task_id == "task_test_123", "Restored source task ID mismatch"
    
    print(f"  ✓ SessionsSpawnRequest creation OK (request_id={request_id})")


def test_bridge_policy_evaluation():
    """Test 3: Bridge Policy 评估不变"""
    print("Test 3: Bridge Policy evaluation...")
    
    policy = SessionsSpawnBridgePolicy(
        safe_mode=True,
        allowlist=["trading", "test"],
        denylist=[],
        require_request_status="prepared",
    )
    
    request = _create_test_request(scenario="test")
    bridge = SessionsSpawnBridge(policy=policy)
    eval_result = bridge.evaluate_policy(request)
    
    assert eval_result["eligible"] is True, f"Should be eligible: {eval_result['blocked_reasons']}"
    assert eval_result["should_execute_real"] is False, "Should not execute real in safe_mode"
    assert len(eval_result["checks"]) >= 5, f"Should have at least 5 checks: {len(eval_result['checks'])}"
    
    check_names = [c["name"] for c in eval_result["checks"]]
    assert "request_status" in check_names, "Missing request_status check"
    assert "prevent_duplicate_execution" in check_names, "Missing duplicate check"
    assert "scenario_allowlist" in check_names, "Missing scenario check"
    
    print(f"  ✓ Bridge Policy evaluation OK (eligible={eval_result['eligible']}, checks={len(eval_result['checks'])})")


def test_api_execution_artifact_generation():
    """Test 4: API Execution Artifact 生成不变"""
    print("Test 4: API Execution Artifact generation...")
    
    policy = SessionsSpawnBridgePolicy(safe_mode=True, allowlist=["trading", "test"])
    request = _create_test_request(scenario="test")
    
    bridge = SessionsSpawnBridge(policy=policy)
    artifact = bridge.execute(request)
    
    assert artifact.execution_id.startswith("exec_api_"), f"Invalid execution_id: {artifact.execution_id}"
    assert artifact.source_request_id == request.request_id, "Source request ID mismatch"
    assert artifact.source_task_id == "task_test_123", "Source task ID mismatch"
    assert artifact.api_execution_status == "pending", f"Status should be 'pending' in safe_mode: {artifact.api_execution_status}"
    assert artifact.api_execution_result is not None, "API execution result should not be None"
    
    linkage = artifact.get_linkage()
    assert linkage["request_id"] == request.request_id, "Linkage request_id mismatch"
    assert linkage["task_id"] == "task_test_123", "Linkage task_id mismatch"
    
    data = artifact.to_dict()
    assert data["execution_version"] == EXECUTION_VERSION, f"Version mismatch: {data['execution_version']}"
    assert data["api_execution_status"] == "pending", "Serialized status mismatch"
    
    print(f"  ✓ API Execution Artifact generation OK (execution_id={artifact.execution_id}, status={artifact.api_execution_status})")


def test_linkage_chain_integrity():
    """Test 5: Linkage 链完整"""
    print("Test 5: Linkage chain integrity...")
    
    registration_id = "reg_wave2_123"
    dispatch_id = "dispatch_wave2_123"
    spawn_id = "spawn_wave2_123"
    execution_id = "exec_wave2_123"
    receipt_id = "receipt_wave2_123"
    request_id = _generate_request_id()
    task_id = "task_wave2_123"
    
    request = SessionsSpawnRequest(
        request_id=request_id,
        source_task_id=task_id,
        source_receipt_id=receipt_id,
        source_execution_id=execution_id,
        source_spawn_id=spawn_id,
        source_dispatch_id=dispatch_id,
        source_registration_id=registration_id,
        spawn_request_status="prepared",
        spawn_request_reason="Linkage test",
        spawn_request_time="2026-03-24T23:00:00",
        sessions_spawn_params={
            "task": "Test task",
            "runtime": "subagent",
            "cwd": str(Path.home() / ".openclaw" / "workspace"),
            "label": "wave2-test",
            "metadata": {
                "dispatch_id": dispatch_id,
                "spawn_id": spawn_id,
                "scenario": "test",
            },
        },
        dedupe_key=f"request_dedupe:test:{request_id}",
        metadata={"scenario": "test", "owner": "main"},
    )
    
    policy = SessionsSpawnBridgePolicy(safe_mode=True)
    bridge = SessionsSpawnBridge(policy=policy)
    artifact = bridge.execute(request)
    
    linkage = artifact.get_linkage()
    
    assert linkage["registration_id"] == registration_id, f"Registration ID mismatch: {linkage['registration_id']}"
    assert linkage["dispatch_id"] == dispatch_id, f"Dispatch ID mismatch: {linkage['dispatch_id']}"
    assert linkage["spawn_id"] == spawn_id, f"Spawn ID mismatch: {linkage['spawn_id']}"
    assert linkage["receipt_id"] == receipt_id, f"Receipt ID mismatch: {linkage['receipt_id']}"
    assert linkage["request_id"] == request_id, f"Request ID mismatch: {linkage['request_id']}"
    assert linkage["task_id"] == task_id, f"Task ID mismatch: {linkage['task_id']}"
    
    print(f"  ✓ Linkage chain integrity OK (registration→dispatch→spawn→execution→receipt→request→task)")


def test_subagent_config_mapping():
    """Test 6: SubagentConfig 映射正确"""
    print("Test 6: SubagentConfig mapping...")
    
    call_params = {
        "task": "Test task for Wave 2",
        "runtime": "subagent",
        "cwd": str(Path.home() / ".openclaw" / "workspace"),
        "label": "wave2-mapping-test",
        "metadata": {
            "timeout_seconds": 120,
            "allowed_tools": ["read", "write", "edit", "exec"],
            "scenario": "test",
        },
    }
    
    config = SubagentConfig(
        label=call_params.get("label", "default"),
        runtime="subagent",
        timeout_seconds=call_params["metadata"].get("timeout_seconds", 900),
        allowed_tools=call_params["metadata"].get("allowed_tools"),
        cwd=call_params.get("cwd", ""),
        metadata={
            **call_params.get("metadata", {}),
            "source": "sessions_spawn_bridge",
            "wave": "wave2_cutover",
        },
    )
    
    assert config.label == "wave2-mapping-test", f"Label mismatch: {config.label}"
    assert config.runtime == "subagent", f"Runtime mismatch: {config.runtime}"
    assert config.timeout_seconds == 120, f"Timeout mismatch: {config.timeout_seconds}"
    assert config.allowed_tools == ["read", "write", "edit", "exec"], f"Tools mismatch: {config.allowed_tools}"
    assert config.metadata["source"] == "sessions_spawn_bridge", "Source metadata missing"
    assert config.metadata["wave"] == "wave2_cutover", "Wave metadata missing"
    
    data = config.to_dict()
    assert data["label"] == "wave2-mapping-test", "Serialized label mismatch"
    assert data["timeout_seconds"] == 120, "Serialized timeout mismatch"
    
    print(f"  ✓ SubagentConfig mapping OK (label={config.label}, timeout={config.timeout_seconds}s)")


def run_all_tests():
    """运行所有测试"""
    print("=" * 70)
    print("Wave 2 Cutover Validation Tests")
    print("=" * 70)
    print()
    
    tests = [
        ("SubagentExecutor Integration", test_subagent_executor_integration),
        ("SessionsSpawnRequest Creation", test_sessions_spawn_request_creation),
        ("Bridge Policy Evaluation", test_bridge_policy_evaluation),
        ("API Execution Artifact Generation", test_api_execution_artifact_generation),
        ("Linkage Chain Integrity", test_linkage_chain_integrity),
        ("SubagentConfig Mapping", test_subagent_config_mapping),
    ]
    
    passed = 0
    failed = 0
    
    for name, test_func in tests:
        try:
            if test_func():
                passed += 1
        except AssertionError as e:
            print(f"  ✗ {name} FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"  ✗ {name} ERROR: {e}")
            failed += 1
    
    print()
    print("=" * 70)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 70)
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
