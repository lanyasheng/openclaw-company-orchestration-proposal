#!/usr/bin/env python3
"""
test_execute_mode_and_auto_trigger.py — Execute Mode + Auto-Trigger 功能验证

验证:
1. Execute mode happy path
2. Auto-trigger 配置和状态查询
3. 向后兼容性

使用方式:
    python3 -m pytest tests/orchestrator/test_execute_mode_and_auto_trigger.py -v
"""

import sys
import tempfile
import shutil
from pathlib import Path

# Add orchestrator directory to path (same pattern as other tests)
REPO_ROOT = Path(__file__).resolve().parents[2]
ORCHESTRATOR_DIR = REPO_ROOT / "runtime" / "orchestrator"
if str(ORCHESTRATOR_DIR) not in sys.path:
    sys.path.insert(0, str(ORCHESTRATOR_DIR))

from sessions_spawn_request import (
    SessionsSpawnRequest,
    SpawnRequestStatus,
    configure_auto_trigger,
    get_auto_trigger_status,
    _iso_now,
)

from bridge_consumer import (
    BridgeConsumer,
    BridgeConsumerPolicy,
    ExecutionResult,
)


def test_execution_result():
    """测试 ExecutionResult 数据结构"""
    print("\n=== Test 1: ExecutionResult 数据结构 ===")
    
    result = ExecutionResult(
        executed=True,
        execute_time="2026-03-22T12:00:00",
        execute_mode="execute",
        session_id="session_test123",
        output="Test output",
    )
    
    assert result.executed is True
    assert result.execute_mode == "execute"
    assert result.session_id == "session_test123"
    
    # 序列化/反序列化
    data = result.to_dict()
    result2 = ExecutionResult.from_dict(data)
    assert result2.executed == result.executed
    
    print("✓ ExecutionResult 数据结构正常")


def test_execute_mode_policy():
    """测试 execute mode policy"""
    print("\n=== Test 2: Execute Mode Policy ===")
    
    policy = BridgeConsumerPolicy(
        simulate_only=False,
        execute_mode="execute",
    )
    
    assert policy.is_execute_mode() is True
    
    # simulate_only=True 时不是 execute mode
    policy2 = BridgeConsumerPolicy(
        simulate_only=True,
        execute_mode="execute",
    )
    assert policy2.is_execute_mode() is False
    
    print("✓ Execute mode policy 正常")


def test_auto_trigger_config():
    """测试 auto-trigger 配置"""
    print("\n=== Test 3: Auto-Trigger 配置 ===")
    
    # 初始配置
    config = configure_auto_trigger(
        enabled=True,
        allowlist=["trading", "test"],
        denylist=["blocked"],
        require_manual_approval=False,
    )
    
    assert config["enabled"] is True
    assert "trading" in config["allowlist"]
    assert "blocked" in config["denylist"]
    assert config["require_manual_approval"] is False
    
    # 查询状态
    status = get_auto_trigger_status()
    assert "config" in status
    assert "triggered_count" in status
    
    print(f"✓ Auto-trigger 配置正常 (triggered_count={status['triggered_count']})")


def test_backward_compatibility():
    """测试向后兼容性（v7 功能仍然正常）"""
    print("\n=== Test 4: 向后兼容性 ===")
    
    # v7 的 BridgeConsumerPolicy 仍然可用
    policy = BridgeConsumerPolicy(
        simulate_only=True,  # v7 默认
        require_request_status="prepared",
    )
    
    assert policy.simulate_only is True
    assert policy.execute_mode == "simulate"  # v8 新增，但有默认值
    
    print("✓ 向后兼容性正常")


def main():
    print("=" * 60)
    print("V8 Execute Mode + Auto-Trigger 功能验证")
    print("=" * 60)
    
    tests = [
        ("ExecutionResult 数据结构", test_execution_result),
        ("Execute Mode Policy", test_execute_mode_policy),
        ("Auto-Trigger 配置", test_auto_trigger_config),
        ("向后兼容性", test_backward_compatibility),
    ]
    
    passed = 0
    failed = 0
    
    for name, test_func in tests:
        try:
            if test_func():
                passed += 1
        except Exception as e:
            print(f"✗ {name} 失败：{e}")
            failed += 1
    
    print("\n" + "=" * 60)
    print(f"测试结果：{passed} 通过，{failed} 失败")
    print("=" * 60)
    
    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
