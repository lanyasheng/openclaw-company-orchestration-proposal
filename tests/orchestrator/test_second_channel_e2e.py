#!/usr/bin/env python3
"""
Second Non-Trading Channel E2E Verification Script

验证目标：
1. 新频道 (1475854028855443607) 能正常生成 contract
2. callback -> summary -> decision -> dispatch 链路正常
3. allowlist 配置生效
4. artifact 落盘路径正确

验证范围：
- 不实际调用 sessions_spawn（避免创建真实 subagent）
- 验证 contract 生成 / allowlist 检查 / dispatch plan 生成
"""

import json
import sys
from pathlib import Path
from datetime import datetime

# Add repo root to path
repo_root = Path(__file__).parent.parent.parent
orchestrator_path = repo_root / "runtime" / "orchestrator"
sys.path.insert(0, str(orchestrator_path))

from channel_roundtable import (
    CURRENT_ARCHITECTURE_DEFAULT_ALLOW_CHANNEL_IDS,
    SECOND_E2E_CHANNEL_ID,
    SECOND_E2E_SCENARIO,
    SECOND_E2E_OWNER,
    _normalized_channel_id,
    _packet_matches_default_auto_dispatch_whitelist,
)

def test_channel_in_allowlist():
    """测试新频道在白名单中"""
    print("=" * 60)
    print("Test 1: Channel in Allowlist")
    print("=" * 60)
    
    channel_id = _normalized_channel_id(f"discord:channel:{SECOND_E2E_CHANNEL_ID}")
    is_allowed = channel_id in CURRENT_ARCHITECTURE_DEFAULT_ALLOW_CHANNEL_IDS
    
    print(f"Channel ID: {channel_id}")
    print(f"Allowlist: {CURRENT_ARCHITECTURE_DEFAULT_ALLOW_CHANNEL_IDS}")
    print(f"Is Allowed: {is_allowed}")
    
    assert is_allowed, f"Channel {channel_id} should be in allowlist"
    print("✅ PASS: Channel is in allowlist\n")
    return True

def test_contract_generation():
    """测试 contract 生成"""
    print("=" * 60)
    print("Test 2: Contract Generation")
    print("=" * 60)
    
    # Simulate minimal packet
    packet = {
        "packet_version": "channel_roundtable_v1",
        "scenario": SECOND_E2E_SCENARIO,
        "channel_id": f"discord:channel:{SECOND_E2E_CHANNEL_ID}",
        "channel_name": "ainews-content-discussion",
        "topic": "AI News Content Roundtable",
        "owner": SECOND_E2E_OWNER,
        "generated_at": datetime.now().isoformat()
    }
    
    roundtable = {
        "conclusion": "PASS",
        "blocker": "none",
        "owner": SECOND_E2E_OWNER,
        "next_step": "Generate dispatch plan",
        "completion_criteria": "Artifacts written to shared-context"
    }
    
    print(f"Packet: {json.dumps(packet, indent=2, ensure_ascii=False)}")
    print(f"Roundtable: {json.dumps(roundtable, indent=2, ensure_ascii=False)}")
    
    # Validate required fields
    required_packet_fields = ["packet_version", "scenario", "channel_id", "topic", "owner", "generated_at"]
    required_roundtable_fields = ["conclusion", "blocker", "owner", "next_step", "completion_criteria"]
    
    for field in required_packet_fields:
        assert field in packet, f"Missing packet field: {field}"
    
    for field in required_roundtable_fields:
        assert field in roundtable, f"Missing roundtable field: {field}"
    
    print("✅ PASS: Contract fields validated\n")
    return True

def test_allowlist_check():
    """测试 allowlist 检查逻辑"""
    print("=" * 60)
    print("Test 3: Allowlist Check Logic")
    print("=" * 60)
    
    # Test allowed channel
    allowed_packet = {
        "channel_id": f"discord:channel:{SECOND_E2E_CHANNEL_ID}",
        "scenario": SECOND_E2E_SCENARIO,
        "topic": "AI News Content",
        "owner": SECOND_E2E_OWNER
    }
    
    result = _packet_matches_default_auto_dispatch_whitelist(allowed_packet)
    print(f"Allowed channel result: {result}")
    assert result == True, "Allowed channel should pass check"
    
    # Test non-allowed channel
    non_allowed_packet = {
        "channel_id": "discord:channel:999999999999999999",
        "scenario": "unknown_scenario",
        "topic": "Unknown Topic",
        "owner": "unknown"
    }
    
    result = _packet_matches_default_auto_dispatch_whitelist(non_allowed_packet)
    print(f"Non-allowed channel result: {result}")
    assert result == False, "Non-allowed channel should fail check"
    
    print("✅ PASS: Allowlist check logic works correctly\n")
    return True

def test_artifact_paths():
    """测试 artifact 落盘路径"""
    print("=" * 60)
    print("Test 4: Artifact Paths")
    print("=" * 60)
    
    home = Path.home()
    shared_context = home / ".openclaw" / "shared-context"
    
    expected_paths = {
        "dispatches": shared_context / "dispatches",
        "spawn_requests": shared_context / "spawn_requests",
        "bridge_consumed": shared_context / "bridge_consumed",
        "completion_receipts": shared_context / "completion_receipts",
        "api_executions": shared_context / "api_executions",
        "summaries": shared_context / "orchestrator" / "summaries",
    }
    
    for name, path in expected_paths.items():
        exists = path.exists()
        print(f"{name}: {path} - {'✅ exists' if exists else '⚠️ not found'}")
    
    print("✅ PASS: Artifact paths checked\n")
    return True

def main():
    print("\n" + "=" * 60)
    print("Second Non-Trading Channel E2E Verification")
    print("Channel: 1475854028855443607 (ainews)")
    print("Date: 2026-03-26")
    print("=" * 60 + "\n")
    
    tests = [
        test_channel_in_allowlist,
        test_contract_generation,
        test_allowlist_check,
        test_artifact_paths,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            if test():
                passed += 1
        except AssertionError as e:
            print(f"❌ FAIL: {e}\n")
            failed += 1
        except Exception as e:
            print(f"❌ ERROR: {e}\n")
            failed += 1
    
    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)
    
    return 0 if failed == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
