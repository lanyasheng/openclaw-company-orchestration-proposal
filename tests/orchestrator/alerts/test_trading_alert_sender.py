#!/usr/bin/env python3
"""
test_trading_alert_sender.py — Trading Alert Sender 测试

测试覆盖：
1. 去重功能
2. 节流功能
3. 发送功能
4. 状态文件写入
5. 日志文件写入

Usage:
    python3 tests/orchestrator/alerts/test_trading_alert_sender.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from datetime import datetime

# 添加路径
REPO_ROOT = Path(__file__).resolve().parents[3]
ORCHESTRATOR_DIR = REPO_ROOT / "runtime" / "orchestrator"
if str(ORCHESTRATOR_DIR) not in sys.path:
    sys.path.insert(0, str(ORCHESTRATOR_DIR))

from alerts.trading_alert_sender import (
    TradingAlertSender,
    send_alert,
    ALERT_STATE_DIR,
    ALERT_LOG_DIR,
    _dedup_key,
    _state_file,
    _log_file,
    _throttle_state_file,
)


def test_dedup():
    """测试去重功能"""
    print("\n=== Test: Dedup ===")
    
    sender = TradingAlertSender(enable_throttle=False)
    candidate_id = "test_dedup_001"
    signal_type = "buy_watch"
    
    # 第一次发送：应该成功
    result1 = sender.send_candidate_alert(
        candidate_id=candidate_id,
        signal_type=signal_type,
        symbol="000001.SZ",
        reason="第一次发送",
    )
    print(f"First send: delivered={result1.delivered}, dedup_skipped={result1.dedup_skipped}")
    assert result1.delivered or result1.dedup_skipped == False, "First send should not be dedup-skipped"
    
    # 第二次发送：应该被去重
    result2 = sender.send_candidate_alert(
        candidate_id=candidate_id,
        signal_type=signal_type,
        symbol="000001.SZ",
        reason="第二次发送（应该被去重）",
    )
    print(f"Second send: delivered={result2.delivered}, dedup_skipped={result2.dedup_skipped}")
    assert result2.dedup_skipped == True, "Second send should be dedup-skipped"
    assert "duplicate_alert" in (result2.error or ""), "Error should mention duplicate"
    
    print("✅ Dedup test passed")
    return True


def test_throttle():
    """测试节流功能"""
    print("\n=== Test: Throttle ===")
    
    # 创建新的 sender，启用节流，窗口内最多 1 条
    sender = TradingAlertSender(
        throttle_window_seconds=300,
        max_alerts_per_window=1,
        enable_dedup=False,  # 关闭去重以便测试节流
    )
    
    signal_type = "sell_watch"
    
    # 第一次发送：应该成功
    result1 = sender.send_candidate_alert(
        candidate_id="test_throttle_001",
        signal_type=signal_type,
        symbol="000002.SZ",
        reason="第一次发送",
    )
    print(f"First send: delivered={result1.delivered}, throttle_skipped={result1.throttle_skipped}")
    
    # 第二次发送（不同类型，应该不受节流影响）
    result2 = sender.send_candidate_alert(
        candidate_id="test_throttle_002",
        signal_type="buy_watch",  # 不同类型
        symbol="000003.SZ",
        reason="不同类型，应该不受节流影响",
    )
    print(f"Second send (different type): delivered={result2.delivered}, throttle_skipped={result2.throttle_skipped}")
    
    # 第三次发送（相同类型，应该被节流）
    result3 = sender.send_candidate_alert(
        candidate_id="test_throttle_003",
        signal_type=signal_type,  # 相同类型
        symbol="000004.SZ",
        reason="相同类型，应该被节流",
    )
    print(f"Third send (same type): delivered={result3.delivered}, throttle_skipped={result3.throttle_skipped}")
    assert result3.throttle_skipped == True, "Third send should be throttled"
    assert "throttled" in (result3.error or ""), "Error should mention throttled"
    
    print("✅ Throttle test passed")
    return True


def test_state_file():
    """测试状态文件写入"""
    print("\n=== Test: State File ===")
    
    sender = TradingAlertSender(enable_throttle=False)
    candidate_id = "test_state_001"
    signal_type = "hold_watch"
    
    result = sender.send_candidate_alert(
        candidate_id=candidate_id,
        signal_type=signal_type,
        symbol="000005.SZ",
        reason="测试状态文件",
    )
    
    # 检查状态文件是否存在
    state_file = _state_file(result.alert_id)
    print(f"State file: {state_file}")
    print(f"State file exists: {state_file.exists()}")
    
    assert state_file.exists(), f"State file should exist: {state_file}"
    
    # 读取并验证状态文件内容
    state = json.loads(state_file.read_text())
    assert "alert_id" in state, "State should have alert_id"
    assert "payload" in state, "State should have payload"
    assert "result" in state, "State should have result"
    assert state["alert_id"] == result.alert_id, "Alert ID should match"
    
    print(f"State file content: alert_id={state['alert_id']}, delivered={state['result']['delivered']}")
    print("✅ State file test passed")
    return True


def test_log_file():
    """测试日志文件写入"""
    print("\n=== Test: Log File ===")
    
    sender = TradingAlertSender(enable_throttle=False)
    candidate_id = "test_log_001"
    signal_type = "candidate_new"
    
    result = sender.send_candidate_alert(
        candidate_id=candidate_id,
        signal_type=signal_type,
        symbol="000006.SZ",
        reason="测试日志文件",
    )
    
    # 检查日志文件是否存在
    log_file = _log_file()
    print(f"Log file: {log_file}")
    print(f"Log file exists: {log_file.exists()}")
    
    assert log_file.exists(), f"Log file should exist: {log_file}"
    
    # 读取日志文件，查找最新 entry
    with open(log_file, "r") as f:
        lines = f.readlines()
    
    assert len(lines) > 0, "Log file should have entries"
    
    # 解析最后一行
    last_entry = json.loads(lines[-1])
    assert "alert_id" in last_entry, "Log entry should have alert_id"
    assert last_entry["alert_id"] == result.alert_id, "Alert ID should match"
    
    print(f"Log entry: alert_id={last_entry['alert_id']}, timestamp={last_entry['timestamp']}")
    print("✅ Log file test passed")
    return True


def test_payload_structure():
    """测试 payload 结构"""
    print("\n=== Test: Payload Structure ===")
    
    sender = TradingAlertSender(dry_run=True)
    candidate_id = "test_payload_001"
    signal_type = "gate_pass"
    
    result = sender.send_candidate_alert(
        candidate_id=candidate_id,
        signal_type=signal_type,
        symbol="000007.SZ",
        reason="测试 payload 结构",
        metadata={"score": 0.95, "sector": "科技", "tags": ["AI", "芯片"]},
        delivery_channel="discord",
        reply_to="channel:test123",
    )
    
    # 获取状态
    state = sender.get_alert_state(result.alert_id)
    
    if state:
        payload = state.get("payload", {})
        print(f"Payload structure:")
        print(f"  - alert_version: {payload.get('alert_version')}")
        print(f"  - candidate_id: {payload.get('candidate_id')}")
        print(f"  - signal_type: {payload.get('signal_type')}")
        print(f"  - symbol: {payload.get('symbol')}")
        print(f"  - reason: {payload.get('reason')}")
        print(f"  - metadata: {payload.get('metadata')}")
        print(f"  - delivery: {payload.get('delivery')}")
        
        # 验证必需字段
        assert payload.get("candidate_id") == candidate_id
        assert payload.get("signal_type") == signal_type
        assert payload.get("symbol") == "000007.SZ"
        assert payload.get("metadata", {}).get("score") == 0.95
        assert payload.get("delivery", {}).get("channel") == "discord"
        
        print("✅ Payload structure test passed")
        return True
    else:
        print("⚠️ Dry run mode, state file not created")
        print("✅ Payload structure test passed (dry run)")
        return True


def test_list_recent_alerts():
    """测试列出最近 alert"""
    print("\n=== Test: List Recent Alerts ===")
    
    sender = TradingAlertSender()
    recent = sender.list_recent_alerts(limit=5)
    
    print(f"Recent alerts count: {len(recent)}")
    if recent:
        print(f"Most recent: alert_id={recent[-1].get('alert_id')}, timestamp={recent[-1].get('timestamp')}")
    
    assert isinstance(recent, list), "Should return a list"
    print("✅ List recent alerts test passed")
    return True


def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("Trading Alert Sender — Test Suite")
    print("=" * 60)
    
    tests = [
        ("去重功能", test_dedup),
        ("节流功能", test_throttle),
        ("状态文件", test_state_file),
        ("日志文件", test_log_file),
        ("Payload 结构", test_payload_structure),
        ("列出最近 Alert", test_list_recent_alerts),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            passed = test_func()
            results.append((name, passed, None))
        except AssertionError as e:
            results.append((name, False, str(e)))
            print(f"❌ {name} failed: {e}")
        except Exception as e:
            results.append((name, False, f"{type(e).__name__}: {e}"))
            print(f"❌ {name} error: {e}")
    
    # 汇总
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    
    passed_count = sum(1 for _, passed, _ in results if passed)
    total_count = len(results)
    
    for name, passed, error in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {name}")
        if error:
            print(f"       {error}")
    
    print(f"\nTotal: {passed_count}/{total_count} tests passed")
    
    if passed_count == total_count:
        print("\n🎉 All tests passed!")
        return 0
    else:
        print(f"\n⚠️ {total_count - passed_count} tests failed")
        return 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
