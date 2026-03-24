#!/usr/bin/env python3
"""
test_retry_cancel_contract.py — Retry/Cancel Contract 测试

覆盖：
- RetryContract 创建和序列化
- CancelContract 创建和序列化
- RetryCancelState 创建和序列化
- RetryCancelManager 状态管理
- can_retry 逻辑
- record_retry 逻辑
- cancel 逻辑
- 持久化
- 便捷函数

这是 Deer-Flow 借鉴线 Batch E 的验收测试。
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path

# 添加 runtime/orchestrator 到路径
orchestrator_path = Path(__file__).parent.parent.parent / "runtime" / "orchestrator"
sys.path.insert(0, str(orchestrator_path))

from retry_cancel_contract import (
    RetryContract,
    CancelContract,
    RetryCancelState,
    RetryCancelManager,
    RetryReason,
    CancelReason,
    RetryCancelStatus,
    create_retry_contract,
    create_cancel_contract,
    get_retry_cancel_state,
    can_retry_task,
    cancel_task,
    get_manager,
    RETRY_CANCEL_CONTRACT_VERSION,
)


def test_retry_contract_creation():
    """测试 RetryContract 创建"""
    contract = RetryContract(
        task_id="test_task_123",
        max_retries=5,
        retry_delay_seconds=120,
        retry_on=[RetryReason.TIMEOUT, RetryReason.NETWORK_ERROR],
        exponential_backoff=True,
        backoff_multiplier=2.5,
        max_delay_seconds=7200,
    )
    
    assert contract.task_id == "test_task_123"
    assert contract.max_retries == 5
    assert contract.retry_delay_seconds == 120
    assert len(contract.retry_on) == 2
    assert RetryReason.TIMEOUT in contract.retry_on
    assert RetryReason.NETWORK_ERROR in contract.retry_on
    assert contract.exponential_backoff is True
    assert contract.backoff_multiplier == 2.5
    assert contract.max_delay_seconds == 7200
    
    print("✓ RetryContract 创建正常")


def test_retry_contract_serialization():
    """测试 RetryContract 序列化"""
    contract = RetryContract(
        task_id="test_task_456",
        max_retries=3,
        retry_delay_seconds=60,
    )
    
    # 序列化
    data = contract.to_dict()
    assert data["contract_version"] == RETRY_CANCEL_CONTRACT_VERSION
    assert data["task_id"] == "test_task_456"
    assert data["max_retries"] == 3
    assert data["retry_delay_seconds"] == 60
    assert data["exponential_backoff"] is True
    
    # 反序列化
    contract2 = RetryContract.from_dict(data)
    assert contract2.task_id == contract.task_id
    assert contract2.max_retries == contract.max_retries
    assert contract2.retry_delay_seconds == contract.retry_delay_seconds
    
    print("✓ RetryContract 序列化正常")


def test_retry_contract_should_retry():
    """测试 RetryContract 重试判断"""
    contract = RetryContract(
        task_id="test_task_789",
        max_retries=3,
        retry_delay_seconds=60,
        retry_on=[RetryReason.TIMEOUT, RetryReason.TRANSIENT_ERROR],
    )
    
    # 可以重试
    assert contract.should_retry(RetryReason.TIMEOUT, 0) is True
    assert contract.should_retry(RetryReason.TIMEOUT, 1) is True
    assert contract.should_retry(RetryReason.TIMEOUT, 2) is True
    assert contract.should_retry(RetryReason.TIMEOUT, 3) is False  # 达到最大次数
    
    # 不在重试列表中
    assert contract.should_retry(RetryReason.MANUAL_RETRY, 0) is False
    
    # 指数退避计算
    assert contract.get_retry_delay(0) == 60  # 60 * 2^0
    assert contract.get_retry_delay(1) == 120  # 60 * 2^1
    assert contract.get_retry_delay(2) == 240  # 60 * 2^2
    
    print("✓ RetryContract 重试判断正常")


def test_cancel_contract_creation():
    """测试 CancelContract 创建"""
    contract = CancelContract(
        task_id="test_task_123",
        reason=CancelReason.USER_REQUESTED,
        message="User requested cancellation",
        cleanup_actions=["archive_state", "notify_upstream"],
        notify=["upstream_owner", "downstream_agent"],
        cascade=True,
    )
    
    assert contract.task_id == "test_task_123"
    assert contract.reason == CancelReason.USER_REQUESTED
    assert contract.message == "User requested cancellation"
    assert len(contract.cleanup_actions) == 2
    assert "archive_state" in contract.cleanup_actions
    assert len(contract.notify) == 2
    assert contract.cascade is True
    
    print("✓ CancelContract 创建正常")


def test_cancel_contract_serialization():
    """测试 CancelContract 序列化"""
    contract = CancelContract(
        task_id="test_task_456",
        reason=CancelReason.MANUAL_CANCEL,
        message="Test cancel",
    )
    
    # 序列化
    data = contract.to_dict()
    assert data["contract_version"] == RETRY_CANCEL_CONTRACT_VERSION
    assert data["task_id"] == "test_task_456"
    assert data["reason"] == "manual_cancel"
    assert data["message"] == "Test cancel"
    
    # 反序列化
    contract2 = CancelContract.from_dict(data)
    assert contract2.task_id == contract.task_id
    assert contract2.reason == contract.reason
    assert contract2.message == contract.message
    
    print("✓ CancelContract 序列化正常")


def test_retry_cancel_state_creation():
    """测试 RetryCancelState 创建"""
    retry_contract = RetryContract(
        task_id="test_task_123",
        max_retries=3,
    )
    
    state = RetryCancelState(
        task_id="test_task_123",
        status=RetryCancelStatus.PENDING,
        retry_contract=retry_contract,
    )
    
    assert state.task_id == "test_task_123"
    assert state.status == RetryCancelStatus.PENDING
    assert state.retry_contract is not None
    assert state.retry_count == 0
    assert len(state.retry_history) == 0
    
    print("✓ RetryCancelState 创建正常")


def test_retry_cancel_state_serialization():
    """测试 RetryCancelState 序列化"""
    retry_contract = RetryContract(task_id="test_task_456", max_retries=3)
    
    state = RetryCancelState(
        task_id="test_task_456",
        status=RetryCancelStatus.RETRYING,
        retry_contract=retry_contract,
        retry_count=1,
        retry_history=[{
            "retry_count": 1,
            "error_reason": "timeout",
            "timestamp": "2026-03-24T12:00:00",
        }],
    )
    
    # 序列化
    data = state.to_dict()
    assert data["state_version"] == RETRY_CANCEL_CONTRACT_VERSION
    assert data["task_id"] == "test_task_456"
    assert data["status"] == "retrying"
    assert data["retry_count"] == 1
    assert len(data["retry_history"]) == 1
    
    # 反序列化
    state2 = RetryCancelState.from_dict(data)
    assert state2.task_id == state.task_id
    assert state2.status == state.status
    assert state2.retry_count == state.retry_count
    
    print("✓ RetryCancelState 序列化正常")


def test_manager_register_retry():
    """测试管理器注册重试契约"""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = RetryCancelManager(state_dir=Path(tmpdir))
        
        contract = RetryContract(
            task_id="test_task_123",
            max_retries=3,
            retry_delay_seconds=60,
        )
        
        state = manager.register_retry(contract)
        
        assert state.task_id == "test_task_123"
        assert state.status == RetryCancelStatus.PENDING
        assert state.retry_contract is not None
        assert state.retry_count == 0
        
        # 验证持久化
        state2 = manager.get_state("test_task_123")
        assert state2 is not None
        assert state2.task_id == state.task_id
        
        print("✓ Manager register_retry 正常")


def test_manager_can_retry():
    """测试管理器 can_retry 判断"""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = RetryCancelManager(state_dir=Path(tmpdir))
        
        contract = RetryContract(
            task_id="test_task_123",
            max_retries=3,
            retry_delay_seconds=60,
            retry_on=[RetryReason.TIMEOUT],
        )
        manager.register_retry(contract)
        
        # 可以重试
        can_retry, reason = manager.can_retry("test_task_123", RetryReason.TIMEOUT)
        assert can_retry is True
        assert "Can retry" in reason
        
        # 记录 3 次重试
        for i in range(3):
            manager.record_retry("test_task_123", RetryReason.TIMEOUT, f"Retry {i+1}")
        
        # 不能再重试（达到最大次数）
        can_retry, reason = manager.can_retry("test_task_123", RetryReason.TIMEOUT)
        assert can_retry is False
        assert "exhausted" in reason.lower() or "max retries" in reason.lower()
        
        print("✓ Manager can_retry 正常")


def test_manager_record_retry():
    """测试管理器记录重试"""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = RetryCancelManager(state_dir=Path(tmpdir))
        
        contract = RetryContract(
            task_id="test_task_123",
            max_retries=3,
            retry_delay_seconds=60,
            exponential_backoff=True,
        )
        manager.register_retry(contract)
        
        # 记录第 1 次重试
        state = manager.record_retry("test_task_123", RetryReason.TIMEOUT, "First retry")
        assert state is not None
        assert state.retry_count == 1
        assert state.status == RetryCancelStatus.RETRYING
        assert len(state.retry_history) == 1
        assert state.retry_history[0]["error_reason"] == "timeout"
        
        # 记录第 2 次重试
        state = manager.record_retry("test_task_123", RetryReason.TIMEOUT, "Second retry")
        assert state.retry_count == 2
        assert len(state.retry_history) == 2
        
        # 记录第 3 次重试（达到最大次数）
        state = manager.record_retry("test_task_123", RetryReason.TIMEOUT, "Third retry")
        assert state.retry_count == 3
        assert state.status == RetryCancelStatus.EXHAUSTED
        
        print("✓ Manager record_retry 正常")


def test_manager_cancel():
    """测试管理器取消任务"""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = RetryCancelManager(state_dir=Path(tmpdir))
        
        # 先注册重试契约
        retry_contract = RetryContract(task_id="test_task_123", max_retries=3)
        manager.register_retry(retry_contract)
        
        # 取消任务
        state = manager.cancel(
            "test_task_123",
            CancelReason.USER_REQUESTED,
            "User requested cancellation",
            ["archive_state", "notify_upstream"],
        )
        
        assert state is not None
        assert state.status == RetryCancelStatus.CANCELLED
        assert state.cancel_contract is not None
        assert state.cancel_contract.reason == CancelReason.USER_REQUESTED
        assert state.cancelled_at is not None
        
        # 验证 cannot retry after cancel
        can_retry, reason = manager.can_retry("test_task_123")
        assert can_retry is False
        assert "cancelled" in reason.lower()
        
        print("✓ Manager cancel 正常")


def test_manager_cleanup():
    """测试管理器清理状态"""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = RetryCancelManager(state_dir=Path(tmpdir))
        
        # 注册并取消任务
        retry_contract = RetryContract(task_id="test_task_123", max_retries=3)
        manager.register_retry(retry_contract)
        manager.cancel("test_task_123", CancelReason.MANUAL_CANCEL)
        
        # 清理
        result = manager.cleanup("test_task_123")
        assert result is True
        
        # 从内存中移除，但文件仍存在
        state = manager.get_state("test_task_123")
        assert state is not None  # 仍可从文件加载
        
        print("✓ Manager cleanup 正常")


def test_convenience_functions():
    """测试便捷函数"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # 重置全局管理器
        import retry_cancel_contract
        retry_cancel_contract._default_manager = RetryCancelManager(state_dir=Path(tmpdir))
        
        # create_retry_contract
        contract = create_retry_contract(
            "test_task_123",
            max_retries=5,
            retry_delay_seconds=120,
        )
        assert contract.task_id == "test_task_123"
        assert contract.max_retries == 5
        
        # create_cancel_contract
        contract = create_cancel_contract(
            "test_task_456",
            reason="upstream_failed",
            message="Upstream task failed",
        )
        assert contract.task_id == "test_task_456"
        assert contract.reason == CancelReason.UPSTREAM_FAILED
        
        # can_retry_task
        retry_contract = RetryContract(task_id="test_task_789", max_retries=3)
        get_manager().register_retry(retry_contract)
        
        can_retry, reason = can_retry_task("test_task_789", "timeout")
        assert can_retry is True
        
        # cancel_task
        state = cancel_task("test_task_789", reason="manual_cancel", message="Test")
        assert state is not None
        assert state.status == RetryCancelStatus.CANCELLED
        
        print("✓ 便捷函数正常")


def test_retry_history_tracking():
    """测试重试历史追踪"""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = RetryCancelManager(state_dir=Path(tmpdir))
        
        contract = RetryContract(
            task_id="test_task_123",
            max_retries=3,
            retry_delay_seconds=60,
            exponential_backoff=True,
        )
        manager.register_retry(contract)
        
        # 记录多次重试
        for i in range(3):
            manager.record_retry(
                "test_task_123",
                RetryReason.TIMEOUT,
                f"Retry attempt {i+1}",
            )
        
        state = manager.get_state("test_task_123")
        assert len(state.retry_history) == 3
        
        # 验证历史记录内容
        for i, history in enumerate(state.retry_history):
            assert history["retry_count"] == i + 1
            assert history["error_reason"] == "timeout"
            assert f"Retry attempt {i+1}" in history["message"]
            assert "timestamp" in history
            assert "next_delay_seconds" in history
        
        # 验证指数退避
        # 注意：retry_count 在记录后增加，所以第 1 次重试后 retry_count=1，下一次延迟是 60 * 2^1
        assert state.retry_history[0]["next_delay_seconds"] == 120  # 60 * 2^1
        assert state.retry_history[1]["next_delay_seconds"] == 240  # 60 * 2^2
        assert state.retry_history[2]["next_delay_seconds"] == 480  # 60 * 2^3
        
        print("✓ 重试历史追踪正常")


def test_string_to_enum_conversion():
    """测试字符串到枚举的转换"""
    # RetryContract
    contract = RetryContract(
        task_id="test_task_123",
        max_retries=3,
        retry_on=["timeout", "network_error"],  # 字符串列表
    )
    assert all(isinstance(r, RetryReason) for r in contract.retry_on)
    
    # CancelContract
    contract = CancelContract(
        task_id="test_task_456",
        reason="user_requested",  # 字符串
    )
    assert isinstance(contract.reason, CancelReason)
    assert contract.reason == CancelReason.USER_REQUESTED
    
    # from_dict
    data = {
        "task_id": "test_task_789",
        "reason": "manual_cancel",
    }
    contract = CancelContract.from_dict(data)
    assert isinstance(contract.reason, CancelReason)
    
    print("✓ 字符串到枚举转换正常")


def test_list_states():
    """测试列出状态"""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = RetryCancelManager(state_dir=Path(tmpdir))
        
        # 创建多个任务
        for i in range(5):
            contract = RetryContract(task_id=f"test_task_{i}", max_retries=3)
            manager.register_retry(contract)
        
        # 列出所有状态
        states = manager.list_states()
        assert len(states) == 5
        
        # 取消其中一个
        manager.cancel("test_task_2", CancelReason.MANUAL_CANCEL)
        
        # 按状态过滤
        cancelled_states = manager.list_states(status=RetryCancelStatus.CANCELLED)
        assert len(cancelled_states) == 1
        assert cancelled_states[0].task_id == "test_task_2"
        
        pending_states = manager.list_states(status=RetryCancelStatus.PENDING)
        assert len(pending_states) == 4
        
        print("✓ list_states 正常")


def test_persistence():
    """测试持久化"""
    with tempfile.TemporaryDirectory() as tmpdir:
        state_dir = Path(tmpdir)
        
        # 创建管理器并注册任务
        manager1 = RetryCancelManager(state_dir=state_dir)
        contract = RetryContract(
            task_id="test_task_123",
            max_retries=3,
            retry_delay_seconds=60,
        )
        manager1.register_retry(contract)
        manager1.record_retry("test_task_123", RetryReason.TIMEOUT, "Test retry")
        
        # 创建新管理器（模拟重启）
        manager2 = RetryCancelManager(state_dir=state_dir)
        state = manager2.get_state("test_task_123")
        
        assert state is not None
        assert state.task_id == "test_task_123"
        assert state.retry_count == 1
        assert len(state.retry_history) == 1
        
        print("✓ 持久化正常")


# ============ 主测试入口 ============

if __name__ == "__main__":
    tests = [
        test_retry_contract_creation,
        test_retry_contract_serialization,
        test_retry_contract_should_retry,
        test_cancel_contract_creation,
        test_cancel_contract_serialization,
        test_retry_cancel_state_creation,
        test_retry_cancel_state_serialization,
        test_manager_register_retry,
        test_manager_can_retry,
        test_manager_record_retry,
        test_manager_cancel,
        test_manager_cleanup,
        test_convenience_functions,
        test_retry_history_tracking,
        test_string_to_enum_conversion,
        test_list_states,
        test_persistence,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"✗ {test.__name__} 失败：{e}")
            failed += 1
        except Exception as e:
            print(f"✗ {test.__name__} 异常：{e}")
            failed += 1
    
    print(f"\n{'='*50}")
    print(f"测试结果：{passed} passed, {failed} failed")
    
    if failed > 0:
        sys.exit(1)
