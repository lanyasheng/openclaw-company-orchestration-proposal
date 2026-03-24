#!/usr/bin/env python3
"""
completion_validator.py — Subtask Completion Validator

核心验证逻辑：在 completion 冒泡到父层之前进行质量门检查

这是 Subtask Completion Validator 的核心实现，提供：
- CompletionValidatorKernel: 验证核心
- validate_subtask_completion: 便捷函数
- audit 日志记录

设计文档：docs/plans/subtask-completion-validator-design-2026-03-25.md
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from completion_validator_rules import (
    validate_completion,
    VALIDATOR_CONFIG,
)

__all__ = [
    "CompletionValidationStatus",
    "CompletionValidationResult",
    "CompletionValidatorKernel",
    "validate_subtask_completion",
    "log_validation_audit",
    "load_validation_audit",
    "VALIDATOR_AUDIT_DIR",
]

# 验证状态
CompletionValidationStatus = Literal[
    "accepted_completion",    # 有效完成 - 可冒泡到父层
    "blocked_completion",     # 无效完成 - 拦截，不冒泡，记录审计
    "gate_required",          # 需要人工审查 - 暂停，等待 gate 决策
    "validator_error",        # 内部错误 - validator 自身失败，fallback 到原逻辑
]

# Audit 日志目录
VALIDATOR_AUDIT_DIR = Path(
    os.environ.get(
        "OPENCLAW_VALIDATOR_AUDIT_DIR",
        Path.home() / ".openclaw" / "shared-context" / "validator_audits",
    )
)


def _ensure_audit_dir() -> None:
    """确保 audit 目录存在"""
    VALIDATOR_AUDIT_DIR.mkdir(parents=True, exist_ok=True)


def _iso_now() -> str:
    """返回当前 ISO-8601 时间戳"""
    return datetime.now().isoformat()


def _generate_audit_id() -> str:
    """生成 stable audit ID"""
    import uuid
    return f"validator_audit_{uuid.uuid4().hex[:12]}"


@dataclass
class CompletionValidationResult:
    """
    Completion 验证结果
    
    核心字段：
    - status: 验证状态 (accepted/blocked/gate/error)
    - reason: 规则 ID 或原因
    - score: Through 分数
    - metadata: 额外元数据 (包含详细规则命中情况)
    - output_preview: 输出预览 (前 500 字符)
    - artifacts: 交付物路径列表
    - label: 任务标签
    """
    status: CompletionValidationStatus
    reason: str
    score: int
    metadata: Dict[str, Any]
    output_preview: str = ""
    artifacts: List[str] = field(default_factory=list)
    label: str = ""
    audit_id: str = field(default_factory=lambda: "")
    timestamp: str = field(default_factory=lambda: "")
    
    def __post_init__(self):
        if not self.audit_id:
            self.audit_id = _generate_audit_id()
        if not self.timestamp:
            self.timestamp = _iso_now()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "audit_id": self.audit_id,
            "timestamp": self.timestamp,
            "status": self.status,
            "reason": self.reason,
            "score": self.score,
            "metadata": self.metadata,
            "output_preview": self.output_preview,
            "artifacts": self.artifacts,
            "label": self.label,
        }
    
    @classmethod
    def from_validation_tuple(
        cls,
        validation_tuple: tuple,
        output: str = "",
        artifacts: List[Path] = None,
        label: str = "",
    ) -> "CompletionValidationResult":
        """
        从 validate_completion 返回的 tuple 创建结果
        
        Args:
            validation_tuple: (status, reason, score, metadata)
            output: 原始输出
            artifacts: 交付物路径列表
            label: 任务标签
        """
        status, reason, score, metadata = validation_tuple
        
        # 映射内部状态到外部状态
        status_map = {
            "accepted": "accepted_completion",
            "blocked": "blocked_completion",
            "gate": "gate_required",
            "error": "validator_error",
        }
        external_status = status_map.get(status, "validator_error")
        
        return cls(
            status=external_status,  # type: ignore
            reason=reason,
            score=score,
            metadata=metadata,
            output_preview=output[:500] if output else "",
            artifacts=[str(p) for p in (artifacts or [])],
            label=label,
        )


class CompletionValidatorKernel:
    """
    Completion Validator Kernel
    
    提供：
    - validate(): 验证 completion
    - validate_and_audit(): 验证并记录 audit 日志
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        初始化 validator kernel
        
        Args:
            config: 配置覆盖 (可选)
        """
        self.config = {**VALIDATOR_CONFIG, **(config or {})}
    
    def _should_skip_validation(self, label: str) -> bool:
        """
        检查是否应跳过验证 (白名单)
        
        Args:
            label: 任务标签
        
        Returns:
            True 如果应跳过验证
        """
        whitelist = self.config.get("whitelist_labels", [])
        for whitelist_label in whitelist:
            if whitelist_label.lower() in label.lower():
                return True
        return False
    
    def validate(
        self,
        output: str,
        exit_code: int = 0,
        artifacts: List[Path] = None,
        label: str = "",
    ) -> CompletionValidationResult:
        """
        验证 completion
        
        Args:
            output: subagent 输出文本
            exit_code: 退出码
            artifacts: 交付物路径列表
            label: 任务标签
        
        Returns:
            CompletionValidationResult
        """
        if artifacts is None:
            artifacts = []
        
        # 检查是否完全禁用 validator
        if os.environ.get("DISABLE_COMPLETION_VALIDATOR") == "1":
            return CompletionValidationResult(
                status="accepted_completion",
                reason="validator_disabled_by_env",
                score=0,
                metadata={"disabled": True},
                output_preview=output[:500] if output else "",
                artifacts=[str(p) for p in artifacts],
                label=label,
            )
        
        # 白名单检查
        if self._should_skip_validation(label):
            result = CompletionValidationResult(
                status="accepted_completion",
                reason="whitelisted",
                score=0,
                metadata={"whitelisted": True},
                output_preview=output[:500] if output else "",
                artifacts=[str(p) for p in artifacts],
                label=label,
            )
            return result
        
        # 调用验证规则
        validation_tuple = validate_completion(
            output=output,
            exit_code=exit_code,
            artifacts=artifacts,
            label=label,
        )
        
        # 创建结果
        result = CompletionValidationResult.from_validation_tuple(
            validation_tuple=validation_tuple,
            output=output,
            artifacts=artifacts,
            label=label,
        )
        
        return result
    
    def validate_and_audit(
        self,
        output: str,
        exit_code: int = 0,
        artifacts: List[Path] = None,
        label: str = "",
        execution_id: str = "",
        spawn_id: str = "",
    ) -> CompletionValidationResult:
        """
        验证 completion 并记录 audit 日志
        
        Args:
            output: subagent 输出文本
            exit_code: 退出码
            artifacts: 交付物路径列表
            label: 任务标签
            execution_id: execution ID (用于关联)
            spawn_id: spawn ID (用于关联)
        
        Returns:
            CompletionValidationResult (已记录 audit)
        """
        # 验证
        result = self.validate(
            output=output,
            exit_code=exit_code,
            artifacts=artifacts,
            label=label,
        )
        
        # 记录 audit 日志
        log_validation_audit(
            result=result,
            execution_id=execution_id,
            spawn_id=spawn_id,
        )
        
        return result


def validate_subtask_completion(
    output: str,
    exit_code: int = 0,
    artifacts: List[Path] = None,
    label: str = "",
    execution_id: str = "",
    spawn_id: str = "",
    audit: bool = True,
) -> CompletionValidationResult:
    """
    便捷函数：验证 subtask completion
    
    Args:
        output: subagent 输出文本
        exit_code: 退出码
        artifacts: 交付物路径列表
        label: 任务标签
        execution_id: execution ID (用于关联)
        spawn_id: spawn ID (用于关联)
        audit: 是否记录 audit 日志 (默认 True)
    
    Returns:
        CompletionValidationResult
    """
    kernel = CompletionValidatorKernel()
    
    if audit:
        return kernel.validate_and_audit(
            output=output,
            exit_code=exit_code,
            artifacts=artifacts,
            label=label,
            execution_id=execution_id,
            spawn_id=spawn_id,
        )
    else:
        return kernel.validate(
            output=output,
            exit_code=exit_code,
            artifacts=artifacts,
            label=label,
        )


def log_validation_audit(
    result: CompletionValidationResult,
    execution_id: str = "",
    spawn_id: str = "",
) -> Path:
    """
    记录 validation audit 日志
    
    Args:
        result: 验证结果
        execution_id: execution ID (用于关联)
        spawn_id: spawn ID (用于关联)
    
    Returns:
        audit 文件路径
    """
    _ensure_audit_dir()
    
    audit_record = result.to_dict()
    audit_record["execution_id"] = execution_id
    audit_record["spawn_id"] = spawn_id
    
    # 写入 audit 文件
    audit_file = VALIDATOR_AUDIT_DIR / f"{result.audit_id}.json"
    tmp_file = audit_file.with_suffix(".tmp")
    
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(audit_record, f, ensure_ascii=False, indent=2)
    tmp_file.replace(audit_file)
    
    return audit_file


def load_validation_audit(audit_id: str) -> Optional[Dict[str, Any]]:
    """
    加载 validation audit 记录
    
    Args:
        audit_id: audit ID
    
    Returns:
        audit 记录 dict，如果不存在则返回 None
    """
    _ensure_audit_dir()
    
    audit_file = VALIDATOR_AUDIT_DIR / f"{audit_id}.json"
    if not audit_file.exists():
        return None
    
    with open(audit_file, "r", encoding="utf-8") as f:
        return json.load(f)


def list_validation_audits(
    status: Optional[CompletionValidationStatus] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """
    列出 validation audit 记录
    
    Args:
        status: 按状态过滤 (可选)
        limit: 最大返回数量
    
    Returns:
        audit 记录列表
    """
    _ensure_audit_dir()
    
    audits = []
    for audit_file in VALIDATOR_AUDIT_DIR.glob("*.json"):
        try:
            with open(audit_file, "r", encoding="utf-8") as f:
                audit = json.load(f)
            
            if status and audit.get("status") != status:
                continue
            
            audits.append(audit)
            
            if len(audits) >= limit:
                break
        except (json.JSONDecodeError, KeyError):
            continue
    
    # 按时间戳倒序
    audits.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return audits
