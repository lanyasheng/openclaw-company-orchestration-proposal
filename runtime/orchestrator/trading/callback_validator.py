#!/usr/bin/env python3
"""
trading/callback_validator.py — Trading Callback Envelope Validator

验证 trading roundtable callback envelope 是否符合 canonical schema。

用法:
    python -m runtime.orchestrator.trading.callback_validator <callback.json>
    
或作为模块导入:
    from runtime.orchestrator.trading.callback_validator import validate_trading_callback
    result = validate_trading_callback(callback_dict)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime


@dataclass
class ValidationResult:
    """验证结果"""
    valid: bool
    errors: List[str]
    warnings: List[str]
    
    def __bool__(self) -> bool:
        return self.valid


def _check_required_fields(data: Dict[str, Any], required: List[str], path: str = "") -> List[str]:
    """检查必填字段"""
    errors = []
    for field in required:
        if field not in data:
            errors.append(f"{path}{field}: 缺少必填字段")
    return errors


def _check_envelope_version(data: Dict[str, Any]) -> List[str]:
    """检查 envelope 版本"""
    errors = []
    version = data.get("envelope_version")
    if version != "canonical_callback_envelope.v1":
        errors.append(f"envelope_version: 期望 'canonical_callback_envelope.v1', 实际 '{version}'")
    return errors


def _check_adapter(data: Dict[str, Any]) -> List[str]:
    """检查 adapter 类型"""
    errors = []
    adapter = data.get("adapter")
    if adapter != "trading_roundtable":
        errors.append(f"adapter: 期望 'trading_roundtable', 实际 '{adapter}'")
    return errors


def _check_backend_terminal_receipt(receipt: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    """检查 backend terminal receipt"""
    errors = []
    warnings = []
    
    # 必填字段
    required = ["receipt_version", "backend", "terminal_status", "artifact_paths", "dispatch_readiness"]
    errors.extend(_check_required_fields(receipt, required, "backend_terminal_receipt."))
    
    # 检查 receipt_version
    if receipt.get("receipt_version") != "tmux_terminal_receipt.v1":
        errors.append(f"backend_terminal_receipt.receipt_version: 期望 'tmux_terminal_receipt.v1'")
    
    # 检查 backend
    if receipt.get("backend") != "tmux":
        errors.append(f"backend_terminal_receipt.backend: 期望 'tmux'")
    
    # 检查 terminal_status
    valid_statuses = ["completed", "failed", "blocked"]
    status = receipt.get("terminal_status")
    if status not in valid_statuses:
        errors.append(f"backend_terminal_receipt.terminal_status: 期望 {valid_statuses}, 实际 '{status}'")
    
    # 检查 artifact_paths (P0 强制：不得为空)
    artifact_paths = receipt.get("artifact_paths", [])
    if not artifact_paths:
        errors.append("backend_terminal_receipt.artifact_paths: 不得为空数组 (P0 强制)")
    elif "terminal.json" not in str(artifact_paths):
        warnings.append("backend_terminal_receipt.artifact_paths: 建议包含 terminal.json")
    
    # 检查 dispatch_readiness
    if not isinstance(receipt.get("dispatch_readiness"), bool):
        errors.append("backend_terminal_receipt.dispatch_readiness: 必须是布尔值")
    
    return errors, warnings


def _check_business_callback_payload(payload: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    """检查 business callback payload"""
    errors = []
    warnings = []
    
    # 必填字段
    required = ["tradability_score", "tradability_reason", "decision"]
    errors.extend(_check_required_fields(payload, required, "business_callback_payload."))
    
    # 检查 tradability_score
    score = payload.get("tradability_score")
    if score is not None:
        if not isinstance(score, (int, float)):
            errors.append("business_callback_payload.tradability_score: 必须是数字")
        elif not (0.0 <= score <= 1.0):
            errors.append("business_callback_payload.tradability_score: 必须在 [0.0, 1.0] 范围内")
    
    # 检查 tradability_reason
    reason = payload.get("tradability_reason")
    if reason is not None and not isinstance(reason, str):
        errors.append("business_callback_payload.tradability_reason: 必须是字符串")
    
    # 检查 decision
    valid_decisions = ["PASS", "FAIL", "DEGRADED", "BLOCKED"]
    decision = payload.get("decision")
    if decision not in valid_decisions:
        errors.append(f"business_callback_payload.decision: 期望 {valid_decisions}, 实际 '{decision}'")
    
    # 检查 decision 与 blocked_reason/degraded_reason 的一致性
    if decision == "BLOCKED" and not payload.get("blocked_reason"):
        warnings.append("business_callback_payload: decision=BLOCKED 但缺少 blocked_reason")
    if decision == "DEGRADED" and not payload.get("degraded_reason"):
        warnings.append("business_callback_payload: decision=DEGRADED 但缺少 degraded_reason")
    
    return errors, warnings


def _check_adapter_scoped_payload(payload: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    """检查 adapter scoped payload"""
    errors = []
    warnings = []
    
    # 必填字段
    required = ["adapter", "schema", "payload"]
    errors.extend(_check_required_fields(payload, required, "adapter_scoped_payload."))
    
    # 检查 adapter
    if payload.get("adapter") != "trading_roundtable":
        errors.append("adapter_scoped_payload.adapter: 期望 'trading_roundtable'")
    
    # 检查 schema
    if payload.get("schema") != "trading_roundtable_callback.v1":
        errors.append("adapter_scoped_payload.schema: 期望 'trading_roundtable_callback.v1'")
    
    # 检查 nested payload
    nested = payload.get("payload", {})
    if not isinstance(nested, dict):
        errors.append("adapter_scoped_payload.payload: 必须是对象")
        return errors, warnings
    
    # 检查 packet 和 roundtable
    if "packet" not in nested:
        errors.append("adapter_scoped_payload.payload: 缺少 packet")
    if "roundtable" not in nested:
        errors.append("adapter_scoped_payload.payload: 缺少 roundtable")
    
    # 检查 roundtable 必填字段
    roundtable = nested.get("roundtable", {})
    if isinstance(roundtable, dict):
        rt_required = ["conclusion", "blocker", "owner", "next_step"]
        errors.extend(_check_required_fields(roundtable, rt_required, "adapter_scoped_payload.payload.roundtable."))
        
        # 检查 conclusion
        valid_conclusions = ["PASS", "FAIL", "CONDITIONAL"]
        conclusion = roundtable.get("conclusion")
        if conclusion not in valid_conclusions:
            errors.append(f"adapter_scoped_payload.payload.roundtable.conclusion: 期望 {valid_conclusions}")
    
    return errors, warnings


def _check_orchestration_contract(contract: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    """检查 orchestration contract"""
    errors = []
    warnings = []
    
    # 必填字段
    required = ["callback_envelope_schema", "next_step", "next_owner", "dispatch_readiness"]
    errors.extend(_check_required_fields(contract, required, "orchestration_contract."))
    
    # 检查 callback_envelope_schema
    if contract.get("callback_envelope_schema") != "canonical_callback_envelope.v1":
        errors.append("orchestration_contract.callback_envelope_schema: 期望 'canonical_callback_envelope.v1'")
    
    # 检查 next_step
    valid_steps = ["acceptance_check", "closeout", "dispatch", "blocked"]
    step = contract.get("next_step")
    if step not in valid_steps:
        errors.append(f"orchestration_contract.next_step: 期望 {valid_steps}")
    
    # 检查 dispatch_readiness
    if not isinstance(contract.get("dispatch_readiness"), bool):
        errors.append("orchestration_contract.dispatch_readiness: 必须是布尔值")
    
    return errors, warnings


def _check_source(source: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    """检查 source 元数据"""
    errors = []
    warnings = []
    
    # 必填字段
    required = ["adapter", "runner", "label"]
    errors.extend(_check_required_fields(source, required, "source."))
    
    return errors, warnings


def validate_trading_callback(data: Dict[str, Any], strict: bool = True) -> ValidationResult:
    """
    验证 trading callback envelope
    
    Args:
        data: callback envelope 字典
        strict: 是否严格模式（strict=True 时 warnings 也视为错误）
    
    Returns:
        ValidationResult
    """
    all_errors: List[str] = []
    all_warnings: List[str] = []
    
    # 顶层必填字段
    required_top_level = [
        "envelope_version",
        "adapter",
        "scenario",
        "batch_id",
        "backend_terminal_receipt",
        "business_callback_payload",
        "adapter_scoped_payload",
        "orchestration_contract",
        "source"
    ]
    all_errors.extend(_check_required_fields(data, required_top_level))
    
    # 检查 envelope_version
    all_errors.extend(_check_envelope_version(data))
    
    # 检查 adapter
    all_errors.extend(_check_adapter(data))
    
    # 检查 backend_terminal_receipt
    receipt = data.get("backend_terminal_receipt", {})
    if isinstance(receipt, dict):
        errs, warns = _check_backend_terminal_receipt(receipt)
        all_errors.extend(errs)
        all_warnings.extend(warns)
    
    # 检查 business_callback_payload
    payload = data.get("business_callback_payload", {})
    if isinstance(payload, dict):
        errs, warns = _check_business_callback_payload(payload)
        all_errors.extend(errs)
        all_warnings.extend(warns)
    
    # 检查 adapter_scoped_payload
    scoped = data.get("adapter_scoped_payload", {})
    if isinstance(scoped, dict):
        errs, warns = _check_adapter_scoped_payload(scoped)
        all_errors.extend(errs)
        all_warnings.extend(warns)
    
    # 检查 orchestration_contract
    contract = data.get("orchestration_contract", {})
    if isinstance(contract, dict):
        errs, warns = _check_orchestration_contract(contract)
        all_errors.extend(errs)
        all_warnings.extend(warns)
    
    # 检查 source
    source = data.get("source", {})
    if isinstance(source, dict):
        errs, warns = _check_source(source)
        all_errors.extend(errs)
        all_warnings.extend(warns)
    
    # Strict 模式下 warnings 也视为错误
    if strict:
        all_errors.extend(all_warnings)
        all_warnings = []
    
    return ValidationResult(
        valid=len(all_errors) == 0,
        errors=all_errors,
        warnings=all_warnings if not strict else []
    )


def validate_callback_file(file_path: str, strict: bool = True) -> ValidationResult:
    """
    验证 callback JSON 文件
    
    Args:
        file_path: JSON 文件路径
        strict: 是否严格模式
    
    Returns:
        ValidationResult
    """
    path = Path(file_path)
    if not path.exists():
        return ValidationResult(
            valid=False,
            errors=[f"文件不存在：{file_path}"],
            warnings=[]
        )
    
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        return ValidationResult(
            valid=False,
            errors=[f"JSON 解析失败：{e}"],
            warnings=[]
        )
    
    return validate_trading_callback(data, strict=strict)


def main():
    """CLI 入口"""
    if len(sys.argv) < 2:
        print("用法：python -m runtime.orchestrator.trading.callback_validator <callback.json> [--strict]")
        sys.exit(1)
    
    file_path = sys.argv[1]
    strict = "--strict" in sys.argv
    
    result = validate_callback_file(file_path, strict=strict)
    
    if result.valid:
        print(f"✅ 验证通过：{file_path}")
        if result.warnings:
            print(f"⚠️  警告 ({len(result.warnings)}):")
            for w in result.warnings:
                print(f"   - {w}")
        sys.exit(0)
    else:
        print(f"❌ 验证失败：{file_path}")
        print(f"错误 ({len(result.errors)}):")
        for e in result.errors:
            print(f"   - {e}")
        if result.warnings:
            print(f"⚠️  警告 ({len(result.warnings)}):")
            for w in result.warnings:
                print(f"   - {w}")
        sys.exit(1)


if __name__ == "__main__":
    main()
