#!/usr/bin/env python3
"""
acceptance_test_alert_chain.py — 提醒链验收测试

验收标准：
1. 候选变化 -> 去重 -> 节流 -> 发送 -> 可验证回执 完整链路
2. 不重复刷屏（去重/节流生效）
3. 发送前有结构化 payload
4. 发送结果/失败有可查日志或状态文件

Usage:
    python3 tests/orchestrator/alerts/acceptance_test_alert_chain.py
"""

from __future__ import annotations

import json
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
    ALERT_STATE_DIR,
    ALERT_LOG_DIR,
    _state_file,
    _log_file,
)


def acceptance_scenario_1_candidate_delivery():
    """
    验收场景 1: 候选推送完整链路
    
    流程：
    1. 新候选产生 -> 发送 candidate_new alert
    2. 候选更新 -> 发送 candidate_update alert
    3. 重复更新 -> 被去重
    4. 验证状态文件和日志文件
    """
    print("\n" + "=" * 60)
    print("验收场景 1: 候选推送完整链路")
    print("=" * 60)
    
    sender = TradingAlertSender(enable_throttle=False)
    candidate_id = "acceptance_candidate_001"
    
    # Step 1: 新候选
    print("\nStep 1: 新候选推送")
    result1 = sender.send_candidate_alert(
        candidate_id=candidate_id,
        signal_type="candidate_new",
        symbol="000001.SZ",
        reason="趋势反转 + 量价共振，综合评分 0.92",
        metadata={
            "score": 0.92,
            "sector": "金融",
            "signals": ["trend_reversal", "volume_price"],
        },
    )
    print(f"  Result: delivered={result1.delivered}, dedup_skipped={result1.dedup_skipped}")
    assert result1.delivered, "New candidate should be delivered"
    
    # Step 2: 候选更新
    print("\nStep 2: 候选更新推送")
    result2 = sender.send_candidate_alert(
        candidate_id=candidate_id,
        signal_type="candidate_update",
        symbol="000001.SZ",
        reason="更新：北向资金流入，评分提升至 0.95",
        metadata={
            "score": 0.95,
            "sector": "金融",
            "signals": ["trend_reversal", "volume_price", "northbound_inflow"],
        },
    )
    print(f"  Result: delivered={result2.delivered}, dedup_skipped={result2.dedup_skipped}")
    assert result2.delivered, "Candidate update should be delivered (different signal type)"
    
    # Step 3: 重复更新（应该被去重）
    print("\nStep 3: 重复更新（应该被去重）")
    result3 = sender.send_candidate_alert(
        candidate_id=candidate_id,
        signal_type="candidate_update",
        symbol="000001.SZ",
        reason="重复更新：应该被去重",
        metadata={"score": 0.95},
    )
    print(f"  Result: delivered={result3.delivered}, dedup_skipped={result3.dedup_skipped}")
    assert result3.dedup_skipped, "Duplicate update should be dedup-skipped"
    
    # Step 4: 验证状态文件
    print("\nStep 4: 验证状态文件")
    state_file_1 = _state_file(result1.alert_id)
    state_file_2 = _state_file(result2.alert_id)
    
    assert state_file_1.exists(), f"State file should exist: {state_file_1}"
    assert state_file_2.exists(), f"State file should exist: {state_file_2}"
    
    state1 = json.loads(state_file_1.read_text())
    state2 = json.loads(state_file_2.read_text())
    
    print(f"  State 1: alert_id={state1['alert_id']}, candidate_id={state1['payload']['candidate_id']}")
    print(f"  State 2: alert_id={state2['alert_id']}, candidate_id={state2['payload']['candidate_id']}")
    
    # 验证 payload 结构
    assert state1["payload"]["signal_type"] == "candidate_new"
    assert state1["payload"]["metadata"]["score"] == 0.92
    assert state2["payload"]["signal_type"] == "candidate_update"
    assert state2["payload"]["metadata"]["score"] == 0.95
    
    # Step 5: 验证日志文件
    print("\nStep 5: 验证日志文件")
    log_file = _log_file()
    assert log_file.exists(), f"Log file should exist: {log_file}"
    
    with open(log_file, "r") as f:
        log_lines = f.readlines()
    
    # 找到最新的两条 log
    recent_logs = [json.loads(line) for line in log_lines[-5:] if candidate_id in line]
    print(f"  Found {len(recent_logs)} log entries for candidate")
    assert len(recent_logs) >= 2, "Should have at least 2 log entries"
    
    print("\n✅ 验收场景 1 通过：候选推送完整链路工作正常")
    return True


def acceptance_scenario_2_gate_alerts():
    """
    验收场景 2: Gate 结果推送
    
    流程：
    1. Gate Pass -> 发送 gate_pass alert
    2. Gate Fail -> 发送 gate_fail alert
    3. 验证结构化 payload
    """
    print("\n" + "=" * 60)
    print("验收场景 2: Gate 结果推送")
    print("=" * 60)
    
    sender = TradingAlertSender(enable_throttle=False)
    batch_id = "acceptance_batch_001"
    
    # Step 1: Gate Pass
    print("\nStep 1: Gate Pass 推送")
    result1 = sender.send_candidate_alert(
        candidate_id=f"batch_{batch_id}",
        signal_type="gate_pass",
        symbol="N/A",
        reason=f"Batch {batch_id} gate review passed, proceeding to next phase",
        metadata={
            "batch_id": batch_id,
            "conclusion": "PASS",
            "blocker": "none",
            "next_step": "advance_phase_handoff",
        },
    )
    print(f"  Result: delivered={result1.delivered}")
    assert result1.delivered, "Gate pass should be delivered"
    
    # Step 2: Gate Fail（不同 batch）
    print("\nStep 2: Gate Fail 推送")
    result2 = sender.send_candidate_alert(
        candidate_id=f"batch_{batch_id}_fail",
        signal_type="gate_fail",
        symbol="N/A",
        reason=f"Batch {batch_id}_fail gate review failed, tradability blocker",
        metadata={
            "batch_id": f"{batch_id}_fail",
            "conclusion": "FAIL",
            "blocker": "tradability",
            "next_step": "packet_freeze",
        },
    )
    print(f"  Result: delivered={result2.delivered}")
    assert result2.delivered, "Gate fail should be delivered"
    
    # Step 3: 验证 payload 结构
    print("\nStep 3: 验证 payload 结构")
    state1 = sender.get_alert_state(result1.alert_id)
    state2 = sender.get_alert_state(result2.alert_id)
    
    assert state1 is not None, "State should exist"
    assert state2 is not None, "State should exist"
    
    # 验证 gate 特定字段
    assert state1["payload"]["metadata"]["conclusion"] == "PASS"
    assert state2["payload"]["metadata"]["conclusion"] == "FAIL"
    assert state1["payload"]["metadata"]["blocker"] == "none"
    assert state2["payload"]["metadata"]["blocker"] == "tradability"
    
    print(f"  Gate Pass payload: conclusion={state1['payload']['metadata']['conclusion']}, blocker={state1['payload']['metadata']['blocker']}")
    print(f"  Gate Fail payload: conclusion={state2['payload']['metadata']['conclusion']}, blocker={state2['payload']['metadata']['blocker']}")
    
    print("\n✅ 验收场景 2 通过：Gate 结果推送工作正常")
    return True


def acceptance_scenario_3_state_verification():
    """
    验收场景 3: 状态可验证性
    
    流程：
    1. 发送 alert
    2. 读取状态文件
    3. 读取日志文件
    4. 验证一致性
    """
    print("\n" + "=" * 60)
    print("验收场景 3: 状态可验证性")
    print("=" * 60)
    
    sender = TradingAlertSender(enable_throttle=False)
    
    # Step 1: 发送 alert
    print("\nStep 1: 发送测试 alert")
    result = sender.send_candidate_alert(
        candidate_id="verify_state_001",
        signal_type="buy_watch",
        symbol="000002.SZ",
        reason="状态验证测试",
        metadata={"test": True},
    )
    print(f"  Alert ID: {result.alert_id}")
    
    # Step 2: 读取状态文件
    print("\nStep 2: 读取状态文件")
    state = sender.get_alert_state(result.alert_id)
    assert state is not None, "State should exist"
    print(f"  State file: alert_id={state['alert_id']}, created_at={state['created_at']}")
    
    # Step 3: 读取日志文件
    print("\nStep 3: 读取日志文件")
    recent = sender.list_recent_alerts(limit=1)
    assert len(recent) > 0, "Should have recent alerts"
    log_entry = recent[-1]
    print(f"  Log entry: alert_id={log_entry['alert_id']}, timestamp={log_entry['timestamp']}")
    
    # Step 4: 验证一致性
    print("\nStep 4: 验证状态和日志一致性")
    assert state["alert_id"] == log_entry["alert_id"], "Alert ID should match"
    assert state["payload"]["candidate_id"] == log_entry["payload"]["candidate_id"], "Candidate ID should match"
    assert state["result"]["delivered"] == log_entry["result"]["delivered"], "Delivered status should match"
    
    print(f"  Consistency check: alert_id match={state['alert_id'] == log_entry['alert_id']}")
    
    print("\n✅ 验收场景 3 通过：状态可验证性工作正常")
    return True


def run_acceptance_tests():
    """运行所有验收测试"""
    print("=" * 60)
    print("Trading Alert Chain — Acceptance Tests")
    print(f"Timestamp: {datetime.now().isoformat()}")
    print("=" * 60)
    
    tests = [
        ("候选推送完整链路", acceptance_scenario_1_candidate_delivery),
        ("Gate 结果推送", acceptance_scenario_2_gate_alerts),
        ("状态可验证性", acceptance_scenario_3_state_verification),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            passed = test_func()
            results.append((name, passed, None))
        except AssertionError as e:
            results.append((name, False, str(e)))
            print(f"\n❌ {name} failed: {e}")
        except Exception as e:
            results.append((name, False, f"{type(e).__name__}: {e}"))
            print(f"\n❌ {name} error: {e}")
    
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
    
    print(f"\nTotal: {passed_count}/{total_count} acceptance tests passed")
    
    if passed_count == total_count:
        print("\n🎉 All acceptance tests passed! 提醒链已闭环。")
        return 0
    else:
        print(f"\n⚠️ {total_count - passed_count} acceptance tests failed")
        return 1


if __name__ == "__main__":
    sys.exit(run_acceptance_tests())
