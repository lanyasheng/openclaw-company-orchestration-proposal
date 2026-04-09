#!/usr/bin/env python3
"""
adapters/base.py — Adapter Base Class

适配器基类，定义所有适配器必须实现的接口。

核心接口：
- validate_packet()
- build_summary()
- build_continuation_plan()
- evaluate_auto_dispatch_readiness()
- build_followup_prompt()

这是通用 kernel，不绑定任何业务场景。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path

__all__ = [
    "BaseAdapter",
    "AdapterMetadata",
    "ADAPTER_BASE_VERSION",
]

ADAPTER_BASE_VERSION = "adapter_base_v1"


@dataclass
class AdapterMetadata:
    """适配器元数据"""
    name: str
    version: str
    description: str
    scenario: str
    
    # 必需字段定义
    packet_required_fields: List[str] = field(default_factory=list)
    roundtable_required_fields: List[str] = field(default_factory=list)
    artifact_required_fields: List[Tuple[str, str]] = field(default_factory=list)
    tradability_required_fields: List[Tuple[str, str]] = field(default_factory=list)
    
    # 配置
    default_auto_dispatch_allowed_modes: set = field(default_factory=set)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "scenario": self.scenario,
            "packet_required_fields": self.packet_required_fields,
            "roundtable_required_fields": self.roundtable_required_fields,
            "artifact_required_fields": self.artifact_required_fields,
            "tradability_required_fields": self.tradability_required_fields,
            "default_auto_dispatch_allowed_modes": list(self.default_auto_dispatch_allowed_modes),
        }


class BaseAdapter(ABC):
    """
    适配器基类
    
    所有业务场景适配器必须继承此类并实现所有抽象方法。
    """
    
    def __init__(self):
        self.metadata = self._define_metadata()
    
    @abstractmethod
    def _define_metadata(self) -> AdapterMetadata:
        """
        定义适配器元数据
        
        Returns:
            AdapterMetadata: 适配器元数据
        """
        pass
    
    @abstractmethod
    def validate_packet(
        self,
        packet: Dict[str, Any],
        roundtable: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        验证 packet 完整性
        
        Args:
            packet: Packet 数据
            roundtable: Roundtable 数据
        
        Returns:
            验证结果：
            {
                "complete": bool,
                "missing_fields": List[str],
                "missing_packet_fields": List[str],
                "missing_roundtable_fields": List[str],
                "missing_artifact_fields": List[str],
                "missing_tradability_fields": List[str],
            }
        """
        pass
    
    @abstractmethod
    def build_summary(
        self,
        batch_id: str,
        analysis: Dict[str, Any],
        decision: Dict[str, Any],
    ) -> str:
        """
        构建 batch summary
        
        Args:
            batch_id: 批次 ID
            analysis: Batch 分析结果
            decision: Decision 数据
        
        Returns:
            str: Markdown 格式的 summary
        """
        pass
    
    @abstractmethod
    def build_continuation_plan(
        self,
        decision: Dict[str, Any],
        analysis: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        构建延续计划
        
        Args:
            decision: Decision 数据
            analysis: Batch 分析结果
        
        Returns:
            延续计划：
            {
                "mode": str,
                "task_preview": str,
                "next_round_goal": str,
                "rationale": str,
                "review_required": bool,
                "required_actions": List[str],
                "completion_criteria": str,
            }
        """
        pass
    
    @abstractmethod
    def evaluate_auto_dispatch_readiness(
        self,
        decision: Dict[str, Any],
        analysis: Dict[str, Any],
        continuation: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        评估 auto-dispatch 就绪状态
        
        Args:
            decision: Decision 数据
            analysis: Batch 分析结果
            continuation: 延续计划
        
        Returns:
            就绪状态：
            {
                "eligible": bool,
                "status": str,
                "blockers": List[str],
                "upgrade_requirements": List[str],
                "criteria": List[Dict[str, Any]],
                "gate_truth_issues": List[str],
                "artifact_truth_issues": List[str],
            }
        """
        pass
    
    @abstractmethod
    def build_followup_prompt(
        self,
        batch_id: str,
        decision: Dict[str, Any],
        summary_path: Path,
    ) -> str:
        """
        构建 follow-up prompt
        
        Args:
            batch_id: 批次 ID
            decision: Decision 数据
            summary_path: Summary 文件路径
        
        Returns:
            str: Follow-up prompt
        """
        pass
    
    # ============== 辅助方法 ==============
    
    def _missing_nested_fields(
        self,
        payload: Dict[str, Any],
        required_fields: List[Tuple[str, str]],
    ) -> List[str]:
        """
        检查嵌套字段是否缺失
        
        Args:
            payload: 数据
            required_fields: 必需字段列表 [(parent, child), ...]
        
        Returns:
            缺失字段列表
        """
        missing = []
        for parent, child in required_fields:
            parent_value = payload.get(parent)
            if not isinstance(parent_value, dict) or child not in parent_value:
                missing.append(f"{parent}.{child}")
                continue
            value = parent_value.get(child)
            if value in (None, ""):
                missing.append(f"{parent}.{child}")
        return missing
    
    def _missing_top_level_fields(
        self,
        payload: Dict[str, Any],
        required_fields: List[str],
    ) -> List[str]:
        """
        检查顶层字段是否缺失
        
        Args:
            payload: 数据
            required_fields: 必需字段列表
        
        Returns:
            缺失字段列表
        """
        return [
            field for field in required_fields
            if payload.get(field) in (None, "")
        ]
    
    def _check_artifact_truth(self, packet: Dict[str, Any]) -> List[str]:
        """
        检查 artifact 真值
        
        Args:
            packet: Packet 数据
        
        Returns:
            问题列表
        """
        issues = []
        
        artifact = packet.get("artifact") if isinstance(packet.get("artifact"), dict) else {}
        report = packet.get("report") if isinstance(packet.get("report"), dict) else {}
        test_info = packet.get("test") if isinstance(packet.get("test"), dict) else {}
        repro = packet.get("repro") if isinstance(packet.get("repro"), dict) else {}
        
        if artifact.get("exists") is not True:
            issues.append("artifact.exists is not true")
        if report.get("exists") is not True:
            issues.append("report.exists is not true")
        if not test_info.get("commands"):
            issues.append("test.commands is empty")
        if not repro.get("commands"):
            issues.append("repro.commands is empty")
        
        return issues
    
    def _check_gate_consistency(
        self,
        packet: Dict[str, Any],
        roundtable: Dict[str, Any],
    ) -> List[str]:
        """
        检查 gate 一致性
        
        Args:
            packet: Packet 数据
            roundtable: Roundtable 数据
        
        Returns:
            问题列表
        """
        issues = []
        
        conclusion = str(roundtable.get("conclusion") or "").upper()
        blocker = str(roundtable.get("blocker") or "").lower()
        overall_gate = str(packet.get("overall_gate") or "").upper()
        primary_blocker = str(packet.get("primary_blocker") or "").lower()
        tradability = packet.get("tradability") if isinstance(packet.get("tradability"), dict) else {}
        tradability_verdict = str(tradability.get("scenario_verdict") or "").upper()
        
        if conclusion == "PASS" and overall_gate not in ("", "PASS"):
            issues.append(f"roundtable conclusion PASS but overall_gate={overall_gate or 'N/A'}")
        if blocker == "none" and primary_blocker not in ("", "none"):
            issues.append(f"roundtable blocker none but primary_blocker={primary_blocker}")
        if conclusion == "PASS" and tradability_verdict not in ("", "PASS"):
            issues.append(f"roundtable conclusion PASS but tradability.scenario_verdict={tradability_verdict or 'N/A'}")
        
        return issues
    
    def get_metadata(self) -> Dict[str, Any]:
        """获取适配器元数据"""
        return self.metadata.to_dict()
