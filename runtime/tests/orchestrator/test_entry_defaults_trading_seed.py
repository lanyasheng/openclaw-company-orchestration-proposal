#!/usr/bin/env python3
"""
test_entry_defaults_trading_seed.py — Trading Seed Payload Completeness Test

验证 entry_defaults._trading_seed_payload 生成的默认 packet 是否包含所有必需字段骨架。

这是 P0-3 Batch 12: Trading Producer/Template Hardening 的测试。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

# Add orchestrator to path
ROOT_DIR = Path(__file__).resolve().parents[2]  # runtime/
ORCHESTRATOR_DIR = ROOT_DIR / "orchestrator"

for path in [str(ORCHESTRATOR_DIR), str(ROOT_DIR)]:
    if path not in sys.path:
        sys.path.insert(0, path)

from entry_defaults import _trading_seed_payload, TRADING_PHASE_ID
from adapters.trading import TradingAdapter, TOP_LEVEL_PACKET_REQUIRED_FIELDS, ARTIFACT_REQUIRED_FIELDS, TRADABILITY_REQUIRED_FIELDS, ROUNDTABLE_REQUIRED_FIELDS


def test_trading_seed_payload_has_all_top_level_fields():
    """测试 seed payload 包含所有 top-level packet 字段"""
    payload = _trading_seed_payload(owner="trading")
    packet = payload["trading_roundtable"]["packet"]
    
    missing = []
    for field in TOP_LEVEL_PACKET_REQUIRED_FIELDS:
        if field not in packet:
            missing.append(field)
    
    assert len(missing) == 0, f"Missing top-level fields: {missing}"
    print(f"✅ PASS: All {len(TOP_LEVEL_PACKET_REQUIRED_FIELDS)} top-level fields present")


def test_trading_seed_payload_has_all_artifact_fields():
    """测试 seed payload 包含所有 artifact truth 字段骨架"""
    payload = _trading_seed_payload(owner="trading")
    packet = payload["trading_roundtable"]["packet"]
    
    missing = []
    for parent, field in ARTIFACT_REQUIRED_FIELDS:
        parent_obj = packet.get(parent)
        if not isinstance(parent_obj, dict):
            missing.append(f"{parent}.{field} (parent missing)")
        elif field not in parent_obj:
            missing.append(f"{parent}.{field}")
    
    assert len(missing) == 0, f"Missing artifact fields: {missing}"
    print(f"✅ PASS: All {len(ARTIFACT_REQUIRED_FIELDS)} artifact fields present")


def test_trading_seed_payload_has_all_tradability_fields():
    """测试 seed payload 包含所有 tradability 字段骨架"""
    payload = _trading_seed_payload(owner="trading")
    packet = payload["trading_roundtable"]["packet"]
    
    missing = []
    for parent, field in TRADABILITY_REQUIRED_FIELDS:
        parent_obj = packet.get(parent)
        if not isinstance(parent_obj, dict):
            missing.append(f"{parent}.{field} (parent missing)")
        elif field not in parent_obj:
            missing.append(f"{parent}.{field}")
    
    assert len(missing) == 0, f"Missing tradability fields: {missing}"
    print(f"✅ PASS: All {len(TRADABILITY_REQUIRED_FIELDS)} tradability fields present")


def test_trading_seed_payload_has_all_roundtable_fields():
    """测试 seed payload 包含所有 roundtable closure 字段"""
    payload = _trading_seed_payload(owner="trading")
    roundtable = payload["trading_roundtable"]["roundtable"]
    
    missing = []
    for field in ROUNDTABLE_REQUIRED_FIELDS:
        if field not in roundtable:
            missing.append(field)
    
    assert len(missing) == 0, f"Missing roundtable fields: {missing}"
    print(f"✅ PASS: All {len(ROUNDTABLE_REQUIRED_FIELDS)} roundtable fields present")


def test_trading_seed_payload_core_blocked_fields():
    """
    测试此前导致 blocked 的核心字段都有默认值：
    - input_config_path
    - repro.notes
    - tradability.annual_turnover
    - tradability.liquidity_flags
    - tradability.gross_return
    - tradability.summary
    """
    payload = _trading_seed_payload(owner="trading")
    packet = payload["trading_roundtable"]["packet"]
    
    # 检查 input_config_path
    assert "input_config_path" in packet, "Missing input_config_path"
    assert packet["input_config_path"] not in (None, "", "TBD"), "input_config_path should have meaningful default"
    print(f"✅ input_config_path: {packet['input_config_path']}")
    
    # 检查 repro.notes
    repro = packet.get("repro", {})
    assert "notes" in repro, "Missing repro.notes"
    assert repro["notes"] not in (None, "", "pending"), "repro.notes should have meaningful default (not 'pending')"
    print(f"✅ repro.notes: {repro['notes'][:80]}...")
    
    # 检查 tradability.annual_turnover
    tradability = packet.get("tradability", {})
    assert "annual_turnover" in tradability, "Missing tradability.annual_turnover"
    assert isinstance(tradability["annual_turnover"], (int, float)), "annual_turnover should be numeric"
    print(f"✅ tradability.annual_turnover: {tradability['annual_turnover']}")
    
    # 检查 tradability.liquidity_flags
    assert "liquidity_flags" in tradability, "Missing tradability.liquidity_flags"
    assert isinstance(tradability["liquidity_flags"], list), "liquidity_flags should be list"
    print(f"✅ tradability.liquidity_flags: {tradability['liquidity_flags']}")
    
    # 检查 tradability.gross_return
    assert "gross_return" in tradability, "Missing tradability.gross_return"
    assert isinstance(tradability["gross_return"], (int, float)), "gross_return should be numeric"
    print(f"✅ tradability.gross_return: {tradability['gross_return']}")
    
    # 检查 tradability.summary (不得留空)
    assert "summary" in tradability, "Missing tradability.summary"
    assert tradability["summary"] not in (None, "", "pending"), "tradability.summary should have meaningful default"
    print(f"✅ tradability.summary: {tradability['summary'][:80]}...")
    
    print("✅ PASS: All core blocked fields have meaningful defaults")


def test_trading_seed_payload_packet_structure_valid():
    """测试 seed payload packet 结构可以通过 adapter 验证（至少结构完整）"""
    payload = _trading_seed_payload(owner="trading")
    packet = payload["trading_roundtable"]["packet"]
    roundtable = payload["trading_roundtable"]["roundtable"]
    
    adapter = TradingAdapter()
    validation = adapter.validate_packet(packet, roundtable)
    
    # 注意：seed payload 的 exists 字段是 False，所以完整验证会失败
    # 但我们至少可以检查 missing_fields 不包含结构性缺失
    structural_fields = [
        "packet_version", "phase_id", "candidate_id", "run_label",
        "input_config_path", "generated_at", "owner", "overall_gate", "primary_blocker",
        "artifact.path", "artifact.exists", "report.path", "report.exists",
        "commit.repo", "commit.git_commit", "test.commands", "test.summary",
        "repro.commands", "repro.notes",
        "tradability.annual_turnover", "tradability.liquidity_flags", "tradability.gross_return",
        "tradability.net_return", "tradability.benchmark_return", "tradability.scenario_verdict",
        "tradability.turnover_failure_reasons", "tradability.liquidity_failure_reasons",
        "tradability.net_vs_gross_failure_reasons", "tradability.summary",
        "conclusion", "blocker", "owner", "next_step", "completion_criteria",
    ]
    
    # 检查 structural fields 是否都在 missing_fields 中
    missing_structural = [f for f in structural_fields if f in validation["missing_fields"]]
    
    assert len(missing_structural) == 0, f"Structural fields missing: {missing_structural}"
    print(f"✅ PASS: Packet structure is complete ({len(structural_fields)} fields)")
    print(f"   Note: validation['complete']={validation['complete']} (expected False for seed payload with exists=False)")


def test_trading_seed_payload_preflight_passes():
    """测试 seed payload 通过 preflight validation（top-level + roundtable 字段）"""
    payload = _trading_seed_payload(owner="trading")
    packet = payload["trading_roundtable"]["packet"]
    roundtable = payload["trading_roundtable"]["roundtable"]
    
    adapter = TradingAdapter()
    preflight = adapter.validate_packet_preflight(packet, roundtable)
    
    # Preflight 只检查 top-level + roundtable 字段，应该通过
    assert preflight["preflight_status"] == "pass", f"Preflight should pass, got: {preflight['preflight_status']}"
    assert preflight["complete"], "Preflight should be complete for top-level + roundtable fields"
    assert len(preflight["missing_fields"]) == 0, f"Preflight missing fields: {preflight['missing_fields']}"
    
    print("✅ PASS: Preflight validation passed")


def main():
    """主测试函数"""
    print()
    print("=" * 80)
    print("TRADING SEED PAYLOAD COMPLETENESS TEST")
    print("P0-3 Batch 12: Trading Producer/Template Hardening")
    print("=" * 80)
    print()
    
    tests = [
        ("Top-Level Fields", test_trading_seed_payload_has_all_top_level_fields),
        ("Artifact Fields", test_trading_seed_payload_has_all_artifact_fields),
        ("Tradability Fields", test_trading_seed_payload_has_all_tradability_fields),
        ("Roundtable Fields", test_trading_seed_payload_has_all_roundtable_fields),
        ("Core Blocked Fields", test_trading_seed_payload_core_blocked_fields),
        ("Packet Structure", test_trading_seed_payload_packet_structure_valid),
        ("Preflight Validation", test_trading_seed_payload_preflight_passes),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            test_func()
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
    print()
    print("=" * 80)
    print("TEST SUMMARY")
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
        print("🎉 ALL TESTS PASSED")
        print()
        print("## 结论")
        print()
        print("1. ✅ **默认 seed payload包含所有必需字段骨架**: 34 个 phase1 packet 字段 + 5 个 roundtable 字段")
        print("2. ✅ **核心 blocked 字段有有意义默认值**: input_config_path, repro.notes, tradability.*")
        print("3. ✅ **Preflight validation 通过**: top-level + roundtable 字段完整")
        print()
        print("## 证据")
        print()
        print("- 代码改动：`runtime/orchestrator/entry_defaults.py::_trading_seed_payload`")
        print("- 新增测试：`runtime/tests/orchestrator/test_entry_defaults_trading_seed.py`")
        print()
        print("## 下一步")
        print()
        print("1. 在真实 Discord trading 频道触发新的 trading live 链")
        print("2. 验证 subagent 执行后 callback packet completeness preflight 更容易通过")
        print("3. 检查 dispatch_plan.status 不再因 packet incomplete 被 skipped")
        print()
        return 0
    else:
        print("⚠️  SOME TESTS FAILED")
        print()
        return 1


if __name__ == "__main__":
    sys.exit(main())
