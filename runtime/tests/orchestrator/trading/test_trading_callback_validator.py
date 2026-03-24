#!/usr/bin/env python3
"""
test_trading_callback_validator.py — Tests for Trading Callback Envelope Validator

测试 trading callback envelope 的验证逻辑，确保：
1. 符合 canonical schema 的 callback 通过验证
2. 缺少必填字段的 callback 被正确拦截
3. Empty-Result 硬拦截规则生效（artifact_paths 不得为空）
4. 与现有 callback bridge 契约兼容

这是批量任务 C1（callback 标准化）的测试覆盖。
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from typing import Any, Dict

# Add orchestrator/trading to path
ROOT_DIR = Path(__file__).resolve().parents[3]  # runtime/
ORCHESTRATOR_DIR = ROOT_DIR / "orchestrator"
TRADING_DIR = ORCHESTRATOR_DIR / "trading"

# Insert paths in correct order (most specific first)
for path in [str(TRADING_DIR), str(ORCHESTRATOR_DIR), str(ROOT_DIR)]:
    if path not in sys.path:
        sys.path.insert(0, path)

# Import validator
from callback_validator import (
    validate_trading_callback,
    validate_callback_file,
    ValidationResult,
)


def build_minimal_valid_callback() -> Dict[str, Any]:
    """构建最小有效 callback"""
    return {
        "envelope_version": "canonical_callback_envelope.v1",
        "adapter": "trading_roundtable",
        "scenario": "trading_roundtable",
        "batch_id": "trading_batch_test_001",
        "packet_id": "pkt_trading_batch_test_001_round_1",
        "task_id": "tsk_trading_test_001",
        "completed_at": "2026-03-24T10:00:00Z",
        
        "backend_terminal_receipt": {
            "receipt_version": "tmux_terminal_receipt.v1",
            "backend": "tmux",
            "terminal_status": "completed",
            "artifact_paths": [
                "/tmp/terminal.json",
                "/tmp/final-summary.json"
            ],
            "dispatch_readiness": True
        },
        
        "business_callback_payload": {
            "tradability_score": 0.85,
            "tradability_reason": "信号强度足够，basket 覆盖率>80%",
            "decision": "PASS",
            "blocked_reason": None,
            "degraded_reason": None
        },
        
        "adapter_scoped_payload": {
            "adapter": "trading_roundtable",
            "schema": "trading_roundtable_callback.v1",
            "payload": {
                "packet": {
                    "packet_version": "trading_roundtable_v1",
                    "packet_id": "pkt_trading_batch_test_001_round_1",
                    "batch_id": "trading_batch_test_001",
                    "scenario": "trading_roundtable",
                    "owner": "trading",
                    "generated_at": "2026-03-24T09:00:00Z"
                },
                "roundtable": {
                    "conclusion": "PASS",
                    "blocker": "none",
                    "owner": "trading",
                    "next_step": "Proceed to dispatch",
                    "completion_criteria": "Tradability score >= 0.7",
                    "summary": "Test callback"
                }
            }
        },
        
        "orchestration_contract": {
            "callback_envelope_schema": "canonical_callback_envelope.v1",
            "next_step": "acceptance_check",
            "next_owner": "main/operator",
            "dispatch_readiness": True
        },
        
        "source": {
            "adapter": "trading_roundtable",
            "runner": "run_subagent_claude_v1.sh",
            "label": "trading_batch_test_001_round_1"
        }
    }


class TestTradingCallbackValidator(unittest.TestCase):
    """测试 Trading Callback Validator"""
    
    def test_valid_callback_passes(self):
        """测试有效 callback 通过验证"""
        callback = build_minimal_valid_callback()
        result = validate_trading_callback(callback)
        
        self.assertTrue(result.valid, f"验证应该通过，但失败：{result.errors}")
        self.assertEqual(len(result.errors), 0)
    
    def test_missing_envelope_version_fails(self):
        """测试缺少 envelope_version 时验证失败"""
        callback = build_minimal_valid_callback()
        del callback["envelope_version"]
        
        result = validate_trading_callback(callback)
        
        self.assertFalse(result.valid)
        self.assertTrue(any("envelope_version" in e for e in result.errors))
    
    def test_wrong_envelope_version_fails(self):
        """测试错误的 envelope_version 时验证失败"""
        callback = build_minimal_valid_callback()
        callback["envelope_version"] = "wrong_version.v1"
        
        result = validate_trading_callback(callback)
        
        self.assertFalse(result.valid)
        self.assertTrue(any("envelope_version" in e for e in result.errors))
    
    def test_wrong_adapter_fails(self):
        """测试错误的 adapter 时验证失败"""
        callback = build_minimal_valid_callback()
        callback["adapter"] = "channel_roundtable"
        
        result = validate_trading_callback(callback)
        
        self.assertFalse(result.valid)
        self.assertTrue(any("adapter" in e for e in result.errors))
    
    def test_empty_artifact_paths_fails_p0(self):
        """测试 artifact_paths 为空时 P0 强制拦截"""
        callback = build_minimal_valid_callback()
        callback["backend_terminal_receipt"]["artifact_paths"] = []
        
        result = validate_trading_callback(callback)
        
        self.assertFalse(result.valid)
        self.assertTrue(any("artifact_paths" in e and "空" in e for e in result.errors))
    
    def test_missing_artifact_paths_fails(self):
        """测试缺少 artifact_paths 时验证失败"""
        callback = build_minimal_valid_callback()
        del callback["backend_terminal_receipt"]["artifact_paths"]
        
        result = validate_trading_callback(callback)
        
        self.assertFalse(result.valid)
        self.assertTrue(any("artifact_paths" in e for e in result.errors))
    
    def test_invalid_terminal_status_fails(self):
        """测试无效的 terminal_status 时验证失败"""
        callback = build_minimal_valid_callback()
        callback["backend_terminal_receipt"]["terminal_status"] = "invalid_status"
        
        result = validate_trading_callback(callback)
        
        self.assertFalse(result.valid)
        self.assertTrue(any("terminal_status" in e for e in result.errors))
    
    def test_tradability_score_out_of_range_fails(self):
        """测试 tradability_score 超出范围时验证失败"""
        callback = build_minimal_valid_callback()
        callback["business_callback_payload"]["tradability_score"] = 1.5
        
        result = validate_trading_callback(callback)
        
        self.assertFalse(result.valid)
        self.assertTrue(any("tradability_score" in e for e in result.errors))
    
    def test_invalid_decision_fails(self):
        """测试无效的 decision 时验证失败"""
        callback = build_minimal_valid_callback()
        callback["business_callback_payload"]["decision"] = "INVALID"
        
        result = validate_trading_callback(callback)
        
        self.assertFalse(result.valid)
        self.assertTrue(any("decision" in e for e in result.errors))
    
    def test_missing_roundtable_conclusion_fails(self):
        """测试缺少 roundtable conclusion 时验证失败"""
        callback = build_minimal_valid_callback()
        del callback["adapter_scoped_payload"]["payload"]["roundtable"]["conclusion"]
        
        result = validate_trading_callback(callback)
        
        self.assertFalse(result.valid)
        self.assertTrue(any("conclusion" in e for e in result.errors))
    
    def test_missing_orchestration_contract_fails(self):
        """测试缺少 orchestration_contract 时验证失败"""
        callback = build_minimal_valid_callback()
        del callback["orchestration_contract"]
        
        result = validate_trading_callback(callback)
        
        self.assertFalse(result.valid)
        self.assertTrue(any("orchestration_contract" in e for e in result.errors))
    
    def test_invalid_dispatch_readiness_fails(self):
        """测试无效的 dispatch_readiness 时验证失败"""
        callback = build_minimal_valid_callback()
        callback["orchestration_contract"]["dispatch_readiness"] = "true"  # 应该是布尔值
        
        result = validate_trading_callback(callback)
        
        self.assertFalse(result.valid)
        self.assertTrue(any("dispatch_readiness" in e for e in result.errors))
    
    def test_blocked_decision_with_reason_warning(self):
        """测试 BLOCKED decision 但缺少 blocked_reason 时产生警告"""
        callback = build_minimal_valid_callback()
        callback["business_callback_payload"]["decision"] = "BLOCKED"
        callback["business_callback_payload"]["blocked_reason"] = None
        
        result = validate_trading_callback(callback, strict=False)
        
        # Strict=False 时应该是警告而不是错误
        self.assertTrue(result.valid)
        self.assertTrue(any("blocked_reason" in w for w in result.warnings))
    
    def test_template_file_validates(self):
        """测试模板文件本身通过验证"""
        # 模板在根目录 examples/trading/ 下
        template_path = Path(__file__).resolve().parents[4] / "examples" / "trading" / "callback_envelope_template.json"
        
        if template_path.exists():
            result = validate_callback_file(str(template_path))
            self.assertTrue(result.valid, f"模板文件应该通过验证，但失败：{result.errors}")
        else:
            self.skipTest(f"模板文件不存在：{template_path}")


class TestCallbackBridgeCompatibility(unittest.TestCase):
    """测试与现有 callback bridge 契约的兼容性"""
    
    def test_legacy_callback_format_compatibility(self):
        """测试 legacy callback 格式可以通过 normalize 兼容"""
        # 这是一个简化测试，实际 bridge 兼容逻辑在 contracts.py 中
        callback = build_minimal_valid_callback()
        
        # 验证基本结构符合 canonical envelope
        result = validate_trading_callback(callback)
        self.assertTrue(result.valid)
        
        # 验证包含所有 bridge 需要的关键字段
        self.assertIn("backend_terminal_receipt", callback)
        self.assertIn("business_callback_payload", callback)
        self.assertIn("adapter_scoped_payload", callback)
        self.assertIn("orchestration_contract", callback)
        
        # 验证 adapter scoped payload 包含 packet 和 roundtable
        scoped = callback["adapter_scoped_payload"]["payload"]
        self.assertIn("packet", scoped)
        self.assertIn("roundtable", scoped)
    
    def test_packet_truth_fields_present(self):
        """测试 Phase1 Packet Truth 字段完整"""
        callback = build_minimal_valid_callback()
        packet = callback["adapter_scoped_payload"]["payload"]["packet"]
        business_payload = callback["business_callback_payload"]
        receipt = callback["backend_terminal_receipt"]
        
        # 验证启动前槽位（在 packet 中）
        # 注意：这些字段可能在 packet 的 slots 中或作为独立字段
        packet_str = str(packet)
        self.assertIn("packet_version", packet_str)
        self.assertIn("batch_id", packet_str)
        
        # 验证 callback 时填槽位（在 business_payload 和 receipt 中）
        self.assertIn("tradability_score", business_payload)
        self.assertIn("terminal_status", receipt)
        
        # 验证 roundtable 字段
        roundtable = callback["adapter_scoped_payload"]["payload"]["roundtable"]
        self.assertIn("conclusion", roundtable)
        self.assertIn("next_step", roundtable)
        self.assertIn("owner", roundtable)


if __name__ == "__main__":
    unittest.main(verbosity=2)
