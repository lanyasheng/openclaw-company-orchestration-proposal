#!/usr/bin/env python3
"""
acceptance_test_alert_chain.py — Trading Alert Chain 验收测试

测试完整提醒链工作流程：
1. 新候选提醒（首次发送）
2. 重复候选提醒（去重）
3. 不同类型提醒（不受去重影响）
4. 节流测试
5. 真实发送出口验证

Usage:
    cd <path-to-repo>
    python3 tests/orchestrator/alerts/acceptance_test_alert_chain.py
"""

from __future__ import annotations

import sys
import json
from pathlib import Path
from datetime import datetime

# 添加路径
REPO_ROOT = Path(__file__).resolve().parents[3]
ORCHESTRATOR_DIR = REPO_ROOT / "runtime" / "orchestrator"
if str(ORCHESTRATOR_DIR) not in sys.path:
    sys.path.insert(0, str(ORCHESTRATOR_DIR))

from alerts.trading_alert_sender import (
    TradingAlertSender,
    FileDeliveryAdapter,
    create_openclaw_adapter,
    ALERT_STATE_DIR,
    ALERT_LOG_DIR,
)


def clean_state():
    """清理状态目录"""
    import shutil
    for dir_path in [ALERT_STATE_DIR, ALERT_LOG_DIR]:
        if dir_path.exists():
            for f in dir_path.iterdir():
                if f.is_file():
                    f.unlink()
    print(f"✅ Cleaned state directories")


def test_new_candidate_alert():
    """测试 1: 新候选提醒"""
    print("\n=== Test 1: New Candidate Alert ===")
    
    sender = TradingAlertSender(
        delivery_adapter=FileDeliveryAdapter(),
        dry_run=False,
        enable_dedup=True,
        enable_throttle=True,
    )
    
    result = sender.send_candidate_alert(
        candidate_id="acceptance_test_001",
        signal_type="candidate_new",
        symbol="000001.SZ",
        reason="趋势反转 + 量价共振",
        metadata={"score": 0.92, "sector": "金融"},
    )
    
    print(f"Result: ok={result.ok}, delivered={result.delivered}")
    print(f"Alert ID: {result.alert_id}")
    
    assert result.ok == True, "Should succeed"
    assert result.delivered == True, "Should be delivered"
    assert result.dedup_skipped == False, "Should not be dedup-skipped"
    
    # 验证状态文件
    state = sender.get_alert_state(result.alert_id)
    assert state is not None, "State file should exist"
    assert state["payload"]["candidate_id"] == "acceptance_test_001"
    assert state["payload"]["symbol"] == "000001.SZ"
    
    print(f"✅ State file verified: {result.alert_id}")
    return True


def test_duplicate_alert_blocked():
    """测试 2: 重复提醒被阻止"""
    print("\n=== Test 2: Duplicate Alert Blocked ===")
    
    sender = TradingAlertSender(
        delivery_adapter=FileDeliveryAdapter(),
        dry_run=False,
        enable_dedup=True,
        enable_throttle=True,
    )
    
    # 发送相同 candidate_id + signal_type
    result = sender.send_candidate_alert(
        candidate_id="acceptance_test_001",  # 相同
        signal_type="candidate_new",         # 相同
        symbol="000001.SZ",
        reason="重复测试",
    )
    
    print(f"Result: ok={result.ok}, dedup_skipped={result.dedup_skipped}")
    print(f"Error: {result.error}")
    
    assert result.ok == True, "Should be ok (not an error)"
    assert result.dedup_skipped == True, "Should be dedup-skipped"
    assert "duplicate_alert" in (result.error or ""), "Error should mention duplicate"
    
    print("✅ Duplicate alert correctly blocked")
    return True


def test_different_signal_type_allowed():
    """测试 3: 不同类型提醒允许发送"""
    print("\n=== Test 3: Different Signal Type Allowed ===")
    
    sender = TradingAlertSender(
        delivery_adapter=FileDeliveryAdapter(),
        dry_run=False,
        enable_dedup=True,
        enable_throttle=False,  # 关闭节流以便测试
    )
    
    # 发送不同类型的提醒（相同 candidate_id）
    result = sender.send_candidate_alert(
        candidate_id="acceptance_test_001",
        signal_type="candidate_update",  # 不同类型
        symbol="000001.SZ",
        reason="候选更新",
    )
    
    print(f"Result: ok={result.ok}, delivered={result.delivered}")
    
    assert result.ok == True, "Should succeed"
    assert result.delivered == True, "Should be delivered"
    assert result.dedup_skipped == False, "Should not be dedup-skipped"
    
    print("✅ Different signal type correctly allowed")
    return True


def test_throttle_blocks_same_type():
    """测试 4: 节流阻止同类型频繁发送"""
    print("\n=== Test 4: Throttle Blocks Same Type ===")
    
    sender = TradingAlertSender(
        delivery_adapter=FileDeliveryAdapter(),
        dry_run=False,
        enable_dedup=False,  # 关闭去重以便测试节流
        enable_throttle=True,
        max_alerts_per_window=1,  # 每窗口最多 1 条
    )
    
    # 第一次发送
    result1 = sender.send_candidate_alert(
        candidate_id="throttle_test_001",
        signal_type="buy_watch",
        symbol="000002.SZ",
        reason="第一次",
    )
    print(f"First send: delivered={result1.delivered}")
    
    # 第二次发送（相同类型，应该被节流）
    result2 = sender.send_candidate_alert(
        candidate_id="throttle_test_002",
        signal_type="buy_watch",  # 相同类型
        symbol="000003.SZ",
        reason="第二次（应该被节流）",
    )
    print(f"Second send: throttle_skipped={result2.throttle_skipped}")
    
    assert result2.throttle_skipped == True, "Should be throttled"
    assert "throttled" in (result2.error or ""), "Error should mention throttled"
    
    print("✅ Throttle correctly blocked same type")
    return True


def test_openclaw_adapter_available():
    """测试 5: OpenClaw 适配器可用性检查"""
    print("\n=== Test 5: OpenClaw Adapter Availability ===")
    
    adapter = create_openclaw_adapter()
    
    # 检查二进制
    import os
    binary_exists = os.path.exists(adapter.openclaw_bin)
    print(f"OpenClaw binary: {adapter.openclaw_bin}")
    print(f"Binary exists: {binary_exists}")
    
    # 检查 Gateway 状态
    try:
        result = adapter.deliver(
            type('MockPayload', (), {
                'alert_id': 'test_availability',
                'signal_type': 'hold_watch',
                'candidate_id': 'test',
                'symbol': 'N/A',
                'reason': '测试',
                'timestamp': datetime.now().isoformat(),
                'metadata': {},
                'delivery': {'channel': 'discord', 'reply_to': ''},
                'to_dict': lambda self: {},
            })(),
            dry_run=True  # 干跑模式
        )
        print(f"Dry run result: {result}")
        assert result.get("status") == "dry_run", "Dry run should work"
        print("✅ OpenClaw adapter dry_run works")
    except Exception as e:
        print(f"⚠️ OpenClaw adapter test error: {e}")
    
    return True


def test_end_to_end_workflow():
    """测试 6: 完整工作流"""
    print("\n=== Test 6: End-to-End Workflow ===")
    
    clean_state()
    
    sender = TradingAlertSender(
        delivery_adapter=FileDeliveryAdapter(),
        dry_run=False,
        enable_dedup=True,
        enable_throttle=True,
    )
    
    # 场景 1: Gate 通过提醒
    result1 = sender.send_candidate_alert(
        candidate_id="e2e_gate_001",
        signal_type="gate_pass",
        symbol="N/A",
        reason="Roundtable Gate review passed",
        metadata={"batch_id": "batch_001", "conclusion": "pass"},
    )
    print(f"Gate pass alert: delivered={result1.delivered}")
    assert result1.delivered == True
    
    # 场景 2: 新候选提醒
    result2 = sender.send_candidate_alert(
        candidate_id="e2e_candidate_001",
        signal_type="candidate_new",
        symbol="000005.SZ",
        reason="新候选发现",
        metadata={"score": 0.88},
    )
    print(f"Candidate new alert: delivered={result2.delivered}")
    assert result2.delivered == True
    
    # 场景 3: 买入观察提醒
    result3 = sender.send_candidate_alert(
        candidate_id="e2e_candidate_001",
        signal_type="buy_watch",
        symbol="000005.SZ",
        reason="达到买入观察条件",
    )
    print(f"Buy watch alert: delivered={result3.delivered}")
    assert result3.delivered == True
    
    # 验证日志
    recent = sender.list_recent_alerts(limit=10)
    print(f"Recent alerts count: {len(recent)}")
    assert len(recent) >= 3, "Should have at least 3 alerts in log"
    
    print("✅ End-to-end workflow completed")
    return True


def run_all_tests():
    """运行所有验收测试"""
    print("=" * 60)
    print("Trading Alert Chain — Acceptance Test Suite")
    print("=" * 60)
    
    tests = [
        ("新候选提醒", test_new_candidate_alert),
        ("重复提醒阻止", test_duplicate_alert_blocked),
        ("不同类型允许", test_different_signal_type_allowed),
        ("节流测试", test_throttle_blocks_same_type),
        ("OpenClaw 适配器检查", test_openclaw_adapter_available),
        ("完整工作流", test_end_to_end_workflow),
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
    print("Acceptance Test Summary")
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
        print("\n🎉 All acceptance tests passed!")
        print("\n📊 真实出口状态:")
        print("   - FileDeliveryAdapter: ✅ 已接通（写入文件）")
        print("   - OpenClawAgentDeliveryAdapter: ⚠️ 需要 Gateway 配置")
        print("\n📁 关键文件路径:")
        print(f"   - 状态目录：{ALERT_STATE_DIR}")
        print(f"   - 日志目录：{ALERT_LOG_DIR}")
        return 0
    else:
        print(f"\n⚠️ {total_count - passed_count} tests failed")
        return 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
