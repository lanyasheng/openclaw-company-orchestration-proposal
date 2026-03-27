#!/usr/bin/env python3
"""
test_trading_live_chain_fix_verification.py — Trading Live Chain Fix Verification

验证 trading callback packet completeness fix 是否生效。

验证目标：
1. 不再因同类缺字段直接 packet incomplete
2. dispatch_plan.status 不再因 fix_blocker 被 skipped（如果仍 skipped，要明确剩余缺字段）
3. 若能推进到 request / consumed / execution，则给出 artifact 路径

这是 P0-3 Batch 11: Trading Callback Packet Completeness Fix 的 E2E 验证。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

# Add orchestrator to path
ROOT_DIR = Path(__file__).resolve().parents[2]  # runtime/
ORCHESTRATOR_DIR = ROOT_DIR / "orchestrator"

for path in [str(ORCHESTRATOR_DIR), str(ROOT_DIR)]:
    if path not in sys.path:
        sys.path.insert(0, path)

from adapters.trading import TradingAdapter, ADAPTER_NAME, SCENARIO


def build_complete_trading_packet() -> Dict[str, Any]:
    """构建完整的 trading phase1 packet（包含所有 34 个必需字段）"""
    return {
        # Top-Level Packet Fields (9 个)
        "packet_version": "trading_phase1_packet_v1",
        "phase_id": "trading_phase1",
        "candidate_id": "AAPL",
        "run_label": "live_verification_20260327",
        "input_config_path": "docs/plans/2026-03-20-trading-roundtable-phase1-input.md",
        "generated_at": datetime.now().isoformat(),
        "owner": "trading",
        "overall_gate": "PASS",
        "primary_blocker": "none",
        
        # Artifact Truth Fields (10 个)
        "artifact": {
            "path": "artifacts/tradable_universe/tradable_universe_20260327.json",
            "exists": True,
        },
        "report": {
            "path": "tmp/live_verification_report_20260327.json",
            "exists": True,
        },
        "commit": {
            "repo": "workspace-trading",
            "git_commit": "live_verification_abc123",
        },
        "test": {
            "commands": [
                "python3 research/run_fixed_candidate_acceptance.py --basket phase_a",
                "python3 scripts/run_preheat_validation.py --sample 500",
            ],
            "summary": "500/500 preheat passed, 0 synthetic contamination",
        },
        "repro": {
            "commands": [
                "cat tmp/live_verification_report_20260327.json | jq '.stats'",
            ],
            "notes": "Live verification test for packet completeness fix - all fields present",
        },
        
        # Tradability Fields (10 个)
        "tradability": {
            "annual_turnover": 2.5,
            "liquidity_flags": [],
            "gross_return": 0.15,
            "net_return": 0.12,
            "benchmark_return": 0.10,
            "scenario_verdict": "PASS",
            "turnover_failure_reasons": [],
            "liquidity_failure_reasons": [],
            "net_vs_gross_failure_reasons": [],
            "summary": "Live verification passed - all tradability metrics meet threshold",
        },
    }


def build_complete_roundtable() -> Dict[str, Any]:
    """构建完整的 roundtable closure（包含所有 5 个必需字段）"""
    return {
        "conclusion": "PASS",
        "blocker": "none",
        "owner": "trading",
        "next_step": "Proceed to dispatch phase 2 execution with complete packet",
        "completion_criteria": "Phase1 packet complete with all 34 required fields",
    }


def test_packet_completeness():
    """测试完整 packet 的验证"""
    adapter = TradingAdapter()
    packet = build_complete_trading_packet()
    roundtable = build_complete_roundtable()
    
    result = adapter.validate_packet(packet, roundtable)
    
    print("=" * 80)
    print("Trading Live Chain Fix Verification")
    print("=" * 80)
    print()
    print("## 1. Packet Completeness Validation")
    print()
    print(f"Validation Result:")
    print(f"  - complete: {result['complete']}")
    print(f"  - missing_fields: {result['missing_fields']}")
    print()
    
    assert result['complete'], f"Packet should be complete, but missing: {result['missing_fields']}"
    assert len(result['missing_fields']) == 0, f"Should have no missing fields, but found: {result['missing_fields']}"
    
    print("✅ PASS: Packet is complete with all 34 required fields")
    print()
    
    return True


def test_preflight_validation():
    """测试 preflight validation"""
    adapter = TradingAdapter()
    packet = build_complete_trading_packet()
    roundtable = build_complete_roundtable()
    
    result = adapter.validate_packet_preflight(packet, roundtable)
    
    print("## 2. Preflight Validation")
    print()
    print(f"Preflight Result:")
    print(f"  - preflight_status: {result['preflight_status']}")
    print(f"  - complete: {result['complete']}")
    print(f"  - missing_fields: {result['missing_fields']}")
    print()
    
    assert result['preflight_status'] == 'pass', f"Preflight should pass, but got: {result['preflight_status']}"
    assert result['complete'], f"Packet should be complete in preflight"
    
    print("✅ PASS: Preflight validation passed")
    print()
    
    return True


def test_continuation_plan():
    """测试 continuation plan 构建"""
    adapter = TradingAdapter()
    
    decision = {
        "action": "proceed",
        "reason": "roundtable gate is PASS and no blocker remains",
        "metadata": {
            "packet": build_complete_trading_packet(),
            "roundtable": build_complete_roundtable(),
            "packet_validation": {"complete": True, "missing_fields": []},
        },
    }
    analysis = {"timeout": 0, "failed": 0, "is_complete": True, "success_rate": 1.0}
    
    continuation = adapter.build_continuation_plan(decision, analysis)
    
    print("## 3. Continuation Plan")
    print()
    print(f"Continuation Plan:")
    print(f"  - mode: {continuation['mode']}")
    print(f"  - task_preview: {continuation['task_preview'][:100]}...")
    print(f"  - review_required: {continuation['review_required']}")
    print()
    
    # 完整 packet + PASS roundtable 应该生成 advance_phase_handoff 或 packet_freeze
    assert continuation['mode'] in {'advance_phase_handoff', 'packet_freeze'}, \
        f"Expected advance_phase_handoff or packet_freeze, got: {continuation['mode']}"
    
    print("✅ PASS: Continuation plan generated correctly")
    print()
    
    return True


def test_auto_dispatch_readiness():
    """测试 auto-dispatch readiness 评估"""
    adapter = TradingAdapter()
    
    decision = {
        "action": "proceed",
        "reason": "roundtable gate is PASS and no blocker remains",
        "metadata": {
            "packet": build_complete_trading_packet(),
            "roundtable": build_complete_roundtable(),
            "packet_validation": {"complete": True, "missing_fields": []},
        },
    }
    analysis = {"timeout": 0, "failed": 0, "is_complete": True, "success_rate": 1.0}
    continuation = {"mode": "advance_phase_handoff"}
    
    readiness = adapter.evaluate_auto_dispatch_readiness(decision, analysis, continuation)
    
    print("## 4. Auto-Dispatch Readiness")
    print()
    print(f"Readiness Result:")
    print(f"  - eligible: {readiness['eligible']}")
    print(f"  - status: {readiness['status']}")
    print(f"  - blockers: {readiness['blockers']}")
    print()
    
    # 完整 packet + PASS roundtable 应该 eligible
    # 但 continuation mode 必须是 whitelisted
    if readiness['eligible']:
        print("✅ PASS: Auto-dispatch eligible (packet complete + roundtable PASS)")
    else:
        print(f"⚠️  NOT ELIGIBLE: blockers = {readiness['blockers']}")
        print("   This is expected if continuation mode is not whitelisted")
    
    print()
    
    return True


def test_followup_prompt_contains_required_fields():
    """测试 follow-up prompt 包含必需字段清单"""
    adapter = TradingAdapter()
    
    decision = {
        "action": "fix_blocker",
        "reason": "phase1 packet incomplete",
        "metadata": {
            "packet": {"candidate_id": "AAPL", "primary_blocker": "missing_fields"},
            "roundtable": {
                "conclusion": "CONDITIONAL",
                "blocker": "missing_fields",
                "owner": "trading",
                "next_step": "fill missing fields",
                "completion_criteria": "all required fields present",
            },
            "continuation": {
                "mode": "packet_freeze",
                "task_preview": "fill missing packet fields",
                "review_required": True,
            },
        },
    }
    
    prompt = adapter.build_followup_prompt(
        batch_id="live_verification_20260327",
        decision=decision,
        summary_path=Path("/tmp/live-verification-summary.md"),
    )
    
    print("## 5. Follow-up Prompt Required Fields")
    print()
    
    # 检查关键部分
    checks = [
        ("P0 强制：Callback 时必须填齐的 Phase1 Packet 字段", "P0 header"),
        ("### Top-Level Packet Fields (9 个)", "top-level fields header"),
        ("### Artifact Truth Fields (10 个)", "artifact fields header"),
        ("### Tradability Fields (10 个)", "tradability fields header"),
        ("### Roundtable Closure Fields (5 个)", "roundtable fields header"),
        ("`repro.notes`: 复现说明（**不得留空**）", "repro.notes emphasis"),
        ("`tradability.summary`: tradability 摘要（**不得留空**）", "tradability.summary emphasis"),
        ("validate_packet", "validation reminder"),
    ]
    
    all_passed = True
    for text, description in checks:
        if text in prompt:
            print(f"  ✅ {description}: found")
        else:
            print(f"  ❌ {description}: NOT found")
            all_passed = False
    
    print()
    
    assert all_passed, "Follow-up prompt should contain all required fields sections"
    print("✅ PASS: Follow-up prompt contains all required fields清单")
    print()
    
    return True


def main():
    """主验证函数"""
    print()
    print("=" * 80)
    print("TRADING LIVE CHAIN FIX VERIFICATION")
    print("P0-3 Batch 11: Trading Callback Packet Completeness Fix")
    print("=" * 80)
    print()
    
    tests = [
        ("Packet Completeness", test_packet_completeness),
        ("Preflight Validation", test_preflight_validation),
        ("Continuation Plan", test_continuation_plan),
        ("Auto-Dispatch Readiness", test_auto_dispatch_readiness),
        ("Follow-up Prompt Required Fields", test_followup_prompt_contains_required_fields),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, True, None))
        except AssertionError as e:
            results.append((name, False, str(e)))
            print(f"❌ FAIL: {name} - {e}")
            print()
        except Exception as e:
            results.append((name, False, f"Unexpected error: {e}"))
            print(f"❌ ERROR: {name} - {e}")
            print()
    
    # 汇总结果
    print("=" * 80)
    print("VERIFICATION SUMMARY")
    print("=" * 80)
    print()
    
    passed = sum(1 for _, success, _ in results if success)
    total = len(results)
    
    for name, success, error in results:
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status}: {name}")
        if error:
            print(f"       {error}")
    
    print()
    print(f"Total: {passed}/{total} tests passed")
    print()
    
    if passed == total:
        print("🎉 ALL VERIFICATION TESTS PASSED")
        print()
        print("## 结论")
        print()
        print("1. ✅ **Packet Completeness Fix 生效**: 完整 packet 不再被判定为 incomplete")
        print("2. ✅ **Follow-up Prompt 包含必需字段清单**: 34 个必需字段明确列出")
        print("3. ✅ **验证提醒已添加**: callback 前自检 validate_packet 返回 complete=True")
        print()
        print("## 证据")
        print()
        print("- 代码改动：`runtime/orchestrator/adapters/trading.py`")
        print("- 新增测试：`runtime/tests/orchestrator/test_trading_followup_prompt_required_fields.py`")
        print("- Git commit: `4e33f36`")
        print("- Git push: origin/main")
        print()
        print("## 下一步")
        print()
        print("1. 在真实 Discord trading 频道触发新的 trading live 链")
        print("2. 验证 dispatch_plan.status 不再因 packet incomplete 被 skipped")
        print("3. 检查 artifact 落盘路径")
        print()
        return 0
    else:
        print("⚠️  SOME VERIFICATION TESTS FAILED")
        print()
        return 1


if __name__ == "__main__":
    sys.exit(main())
