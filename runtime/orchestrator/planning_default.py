#!/usr/bin/env python3
"""
planning_default.py — Default Planning Artifact for Non-Trivial Tasks

为非 trivial feature / bugfix / workflow 设计引入默认 planning artifact/schema。

核心能力：
1. PlanningArtifact schema：problem_reframing / scope_review / engineering_review / execution_plan
2. build_planning_artifact(): 构建 planning artifact
3. extract_planning_artifact(): 从 payload 中提取 planning artifact
4. validate_planning_artifact(): 验证 planning artifact 完整性

这是 P0-1 Batch 1 的核心交付，让下游执行链路能消费 planning artifact。

设计原则：
- 最小核心：只包含必需字段
- 向后兼容：可选字段支持渐进式采用
- 场景可扩展：通过 metadata 支持场景特定字段
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

__all__ = [
    "PlanningArtifact",
    "ProblemReframing",
    "ScopeReview",
    "EngineeringReview",
    "ExecutionPlan",
    "build_planning_artifact",
    "extract_planning_artifact",
    "validate_planning_artifact",
    "merge_planning_into_dispatch",
    "PLANNING_ARTIFACT_VERSION",
]

PLANNING_ARTIFACT_VERSION = "planning_artifact_v1"

# Planning artifact 存储目录
PLANNING_DIR = Path.home() / ".openclaw" / "shared-context" / "planning_artifacts"


def _ensure_planning_dir() -> None:
    """确保 planning artifact 目录存在"""
    PLANNING_DIR.mkdir(parents=True, exist_ok=True)


def _iso_now() -> str:
    """返回当前 ISO-8601 时间戳"""
    return datetime.now(timezone.utc).isoformat()


def _generate_id(prefix: str) -> str:
    """生成 ID"""
    import uuid
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _planning_file(artifact_id: str) -> Path:
    """返回 planning artifact 文件路径"""
    return PLANNING_DIR / f"{artifact_id}.json"


@dataclass
class ProblemReframing:
    """
    Problem Reframing — 问题重述与背景分析
    
    核心字段：
    - problem_statement: 问题陈述（人类可读）
    - root_cause: 根因分析（如果已知）
    - context: 背景信息（相关业务/技术上下文）
    - success_criteria: 成功标准（可验证的条件）
    """
    problem_statement: str
    root_cause: Optional[str] = None
    context: str = ""
    success_criteria: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "problem_statement": self.problem_statement,
            "root_cause": self.root_cause,
            "context": self.context,
            "success_criteria": self.success_criteria,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProblemReframing":
        return cls(
            problem_statement=data.get("problem_statement", ""),
            root_cause=data.get("root_cause"),
            context=data.get("context", ""),
            success_criteria=data.get("success_criteria", []),
            metadata=data.get("metadata", {}),
        )
    
    def validate(self) -> tuple[bool, List[str]]:
        """验证 problem reframing 完整性"""
        errors: List[str] = []
        
        if not self.problem_statement or not self.problem_statement.strip():
            errors.append("problem_statement is required")
        
        if not self.success_criteria:
            errors.append("success_criteria should have at least one item")
        
        return len(errors) == 0, errors


@dataclass
class ScopeReview:
    """
    Scope Review — 范围审查
    
    核心字段：
    - in_scope: 范围内的工作项
    - out_of_scope: 范围外的工作项（显式排除）
    - dependencies: 依赖项（内部/外部）
    - constraints: 约束条件（时间/资源/技术等）
    """
    in_scope: List[str] = field(default_factory=list)
    out_of_scope: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "in_scope": self.in_scope,
            "out_of_scope": self.out_of_scope,
            "dependencies": self.dependencies,
            "constraints": self.constraints,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScopeReview":
        return cls(
            in_scope=data.get("in_scope", []),
            out_of_scope=data.get("out_of_scope", []),
            dependencies=data.get("dependencies", []),
            constraints=data.get("constraints", []),
            metadata=data.get("metadata", {}),
        )
    
    def validate(self) -> tuple[bool, List[str]]:
        """验证 scope review 完整性"""
        errors: List[str] = []
        
        if not self.in_scope:
            errors.append("in_scope is required and cannot be empty")
        
        return len(errors) == 0, errors


@dataclass
class EngineeringReview:
    """
    Engineering Review — 工程审查
    
    核心字段：
    - technical_approach: 技术方案描述
    - architecture_changes: 架构变更（如果有）
    - risk_assessment: 风险评估
    - testing_strategy: 测试策略
    - rollback_plan: 回退方案
    """
    technical_approach: str = ""
    architecture_changes: List[str] = field(default_factory=list)
    risk_assessment: List[Dict[str, str]] = field(default_factory=list)  # [{risk, impact, mitigation}]
    testing_strategy: str = ""
    rollback_plan: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "technical_approach": self.technical_approach,
            "architecture_changes": self.architecture_changes,
            "risk_assessment": self.risk_assessment,
            "testing_strategy": self.testing_strategy,
            "rollback_plan": self.rollback_plan,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EngineeringReview":
        return cls(
            technical_approach=data.get("technical_approach", ""),
            architecture_changes=data.get("architecture_changes", []),
            risk_assessment=data.get("risk_assessment", []),
            testing_strategy=data.get("testing_strategy", ""),
            rollback_plan=data.get("rollback_plan", ""),
            metadata=data.get("metadata", {}),
        )
    
    def validate(self) -> tuple[bool, List[str]]:
        """验证 engineering review 完整性"""
        errors: List[str] = []
        
        # 这些都是可选字段，但如果有值应该合理
        if self.technical_approach and len(self.technical_approach) < 10:
            errors.append("technical_approach should be more detailed")
        
        return len(errors) == 0, errors


@dataclass
class ExecutionPlan:
    """
    Execution Plan — 执行计划
    
    核心字段：
    - phases: 执行阶段列表
    - milestones: 里程碑
    - estimated_duration: 预估时长（如 "2h", "1d"）
    - owner: 负责人
    """
    phases: List[Dict[str, str]] = field(default_factory=list)  # [{phase, description, deliverable}]
    milestones: List[str] = field(default_factory=list)
    estimated_duration: str = ""
    owner: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "phases": self.phases,
            "milestones": self.milestones,
            "estimated_duration": self.estimated_duration,
            "owner": self.owner,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExecutionPlan":
        return cls(
            phases=data.get("phases", []),
            milestones=data.get("milestones", []),
            estimated_duration=data.get("estimated_duration", ""),
            owner=data.get("owner", ""),
            metadata=data.get("metadata", {}),
        )
    
    def validate(self) -> tuple[bool, List[str]]:
        """验证 execution plan 完整性"""
        errors: List[str] = []
        
        if not self.phases:
            errors.append("phases is required and cannot be empty")
        
        if not self.owner:
            errors.append("owner is required")
        
        return len(errors) == 0, errors


@dataclass
class PlanningArtifact:
    """
    Planning Artifact — 默认 planning artifact
    
    核心字段：
    - artifact_id: Artifact ID
    - problem_reframing: 问题重述
    - scope_review: 范围审查
    - engineering_review: 工程审查（可选）
    - execution_plan: 执行计划
    - metadata: 额外元数据
    
    这是 canonical artifact，下游执行链路可以消费。
    """
    artifact_id: str
    problem_reframing: ProblemReframing
    scope_review: ScopeReview
    engineering_review: Optional[EngineeringReview] = None
    execution_plan: Optional[ExecutionPlan] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: _iso_now())
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "artifact_version": PLANNING_ARTIFACT_VERSION,
            "artifact_id": self.artifact_id,
            "problem_reframing": self.problem_reframing.to_dict(),
            "scope_review": self.scope_review.to_dict(),
            "engineering_review": self.engineering_review.to_dict() if self.engineering_review else None,
            "execution_plan": self.execution_plan.to_dict() if self.execution_plan else None,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PlanningArtifact":
        engineering_review_data = data.get("engineering_review")
        engineering_review = EngineeringReview.from_dict(engineering_review_data) if engineering_review_data else None
        
        execution_plan_data = data.get("execution_plan")
        execution_plan = ExecutionPlan.from_dict(execution_plan_data) if execution_plan_data else None
        
        return cls(
            artifact_id=data.get("artifact_id", ""),
            problem_reframing=ProblemReframing.from_dict(data.get("problem_reframing", {})),
            scope_review=ScopeReview.from_dict(data.get("scope_review", {})),
            engineering_review=engineering_review,
            execution_plan=execution_plan,
            metadata=data.get("metadata", {}),
            created_at=data.get("created_at", _iso_now()),
        )
    
    def validate(self) -> tuple[bool, List[str]]:
        """验证 planning artifact 完整性"""
        errors: List[str] = []
        
        # 验证必需字段
        if not self.artifact_id:
            errors.append("artifact_id is required")
        
        # 验证子组件
        pr_valid, pr_errors = self.problem_reframing.validate()
        if not pr_valid:
            errors.extend([f"problem_reframing: {e}" for e in pr_errors])
        
        sr_valid, sr_errors = self.scope_review.validate()
        if not sr_valid:
            errors.extend([f"scope_review: {e}" for e in sr_errors])
        
        # engineering_review 和 execution_plan 是可选的
        
        return len(errors) == 0, errors
    
    def write(self) -> Path:
        _ensure_planning_dir()
        planning_file = _planning_file(self.artifact_id)
        tmp_file = planning_file.with_suffix(".tmp")
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
        tmp_file.replace(planning_file)
        try:
            from workflow_state_store import get_store
            store = get_store()
            if store.is_active and hasattr(self, "source_task_id") and self.source_task_id:
                store.update_task(
                    self.source_task_id,
                    execution_metadata={"planning_id": self.artifact_id},
                )
        except Exception:
            pass
        return planning_file


def build_planning_artifact(
    *,
    problem_statement: str,
    in_scope: List[str],
    success_criteria: Optional[List[str]] = None,
    root_cause: Optional[str] = None,
    context: str = "",
    out_of_scope: Optional[List[str]] = None,
    dependencies: Optional[List[str]] = None,
    constraints: Optional[List[str]] = None,
    technical_approach: Optional[str] = None,
    architecture_changes: Optional[List[str]] = None,
    risk_assessment: Optional[List[Dict[str, str]]] = None,
    testing_strategy: Optional[str] = None,
    rollback_plan: Optional[str] = None,
    phases: Optional[List[Dict[str, str]]] = None,
    milestones: Optional[List[str]] = None,
    estimated_duration: Optional[str] = None,
    owner: str = "main",
    metadata: Optional[Dict[str, Any]] = None,
) -> PlanningArtifact:
    """
    构建 planning artifact
    
    Args:
        problem_statement: 问题陈述（必需）
        in_scope: 范围内工作项（必需）
        success_criteria: 成功标准（可选，但推荐）
        root_cause: 根因分析（可选）
        context: 背景信息（可选）
        out_of_scope: 范围外工作项（可选）
        dependencies: 依赖项（可选）
        constraints: 约束条件（可选）
        technical_approach: 技术方案（可选）
        architecture_changes: 架构变更（可选）
        risk_assessment: 风险评估（可选）
        testing_strategy: 测试策略（可选）
        rollback_plan: 回退方案（可选）
        phases: 执行阶段（可选）
        milestones: 里程碑（可选）
        estimated_duration: 预估时长（可选）
        owner: 负责人（默认 "main"）
        metadata: 额外元数据（可选）
    
    Returns:
        PlanningArtifact
    """
    artifact_id = _generate_id("plan")
    
    # 构建 problem reframing
    problem_reframing = ProblemReframing(
        problem_statement=problem_statement,
        root_cause=root_cause,
        context=context,
        success_criteria=success_criteria or [],
    )
    
    # 构建 scope review
    scope_review = ScopeReview(
        in_scope=in_scope,
        out_of_scope=out_of_scope or [],
        dependencies=dependencies or [],
        constraints=constraints or [],
    )
    
    # 构建 engineering review（可选）
    engineering_review = None
    if technical_approach or architecture_changes or risk_assessment or testing_strategy or rollback_plan:
        engineering_review = EngineeringReview(
            technical_approach=technical_approach or "",
            architecture_changes=architecture_changes or [],
            risk_assessment=risk_assessment or [],
            testing_strategy=testing_strategy or "",
            rollback_plan=rollback_plan or "",
        )
    
    # 构建 execution plan（可选）
    execution_plan = None
    if phases or milestones or estimated_duration or owner:
        execution_plan = ExecutionPlan(
            phases=phases or [],
            milestones=milestones or [],
            estimated_duration=estimated_duration or "",
            owner=owner,
        )
    
    artifact = PlanningArtifact(
        artifact_id=artifact_id,
        problem_reframing=problem_reframing,
        scope_review=scope_review,
        engineering_review=engineering_review,
        execution_plan=execution_plan,
        metadata=metadata or {},
    )
    
    return artifact


def extract_planning_artifact(
    payload: Dict[str, Any],
    source: str = "unknown",
) -> Optional[PlanningArtifact]:
    """
    从 payload 中提取 planning artifact
    
    支持从多种来源提取：
    - dispatch plan metadata
    - decision metadata
    - 直接 planning_artifact 字段
    
    Args:
        payload: 包含 planning artifact 的 payload
        source: 来源标识（用于调试）
    
    Returns:
        PlanningArtifact 或 None
    """
    # 尝试直接提取 planning_artifact
    if isinstance(payload.get("planning_artifact"), dict):
        return PlanningArtifact.from_dict(payload["planning_artifact"])
    
    # 尝试从 dispatch plan 提取
    if isinstance(payload.get("dispatch_plan"), dict):
        dispatch_plan = payload["dispatch_plan"]
        if isinstance(dispatch_plan.get("planning_artifact"), dict):
            return PlanningArtifact.from_dict(dispatch_plan["planning_artifact"])
        if isinstance(dispatch_plan.get("metadata"), dict):
            metadata = dispatch_plan["metadata"]
            if isinstance(metadata.get("planning_artifact"), dict):
                return PlanningArtifact.from_dict(metadata["planning_artifact"])
    
    # 尝试从 decision 提取
    if isinstance(payload.get("decision"), dict):
        decision = payload["decision"]
        if isinstance(decision.get("metadata"), dict):
            metadata = decision["metadata"]
            if isinstance(metadata.get("planning_artifact"), dict):
                return PlanningArtifact.from_dict(metadata["planning_artifact"])
    
    # 尝试从 metadata 直接提取
    if isinstance(payload.get("metadata"), dict):
        metadata = payload["metadata"]
        if isinstance(metadata.get("planning_artifact"), dict):
            return PlanningArtifact.from_dict(metadata["planning_artifact"])
    
    return None


def validate_planning_artifact(
    artifact: PlanningArtifact,
    *,
    require_engineering_review: bool = False,
    require_execution_plan: bool = False,
) -> tuple[bool, List[str]]:
    """
    验证 planning artifact
    
    Args:
        artifact: PlanningArtifact
        require_engineering_review: 是否要求 engineering_review（默认 False）
        require_execution_plan: 是否要求 execution_plan（默认 False）
    
    Returns:
        (is_valid, errors)
    """
    errors: List[str] = []
    
    # 基础验证
    is_valid, base_errors = artifact.validate()
    if not is_valid:
        errors.extend(base_errors)
    
    # 可选字段要求检查
    if require_engineering_review and not artifact.engineering_review:
        errors.append("engineering_review is required but missing")
    
    if require_execution_plan and not artifact.execution_plan:
        errors.append("execution_plan is required but missing")
    
    return len(errors) == 0, errors


def merge_planning_into_dispatch(
    dispatch_plan: Dict[str, Any],
    planning_artifact: PlanningArtifact,
) -> Dict[str, Any]:
    """
    将 planning artifact 合并到 dispatch plan 中
    
    Args:
        dispatch_plan: Dispatch plan dict
        planning_artifact: PlanningArtifact
    
    Returns:
        更新后的 dispatch plan dict
    """
    # 确保 metadata 存在
    if "metadata" not in dispatch_plan:
        dispatch_plan["metadata"] = {}
    
    # 合并 planning artifact
    dispatch_plan["metadata"]["planning_artifact"] = planning_artifact.to_dict()
    dispatch_plan["metadata"]["planning_artifact_id"] = planning_artifact.artifact_id
    
    return dispatch_plan


def get_planning_artifact(artifact_id: str) -> Optional[PlanningArtifact]:
    """
    获取 planning artifact
    
    Args:
        artifact_id: Artifact ID
    
    Returns:
        PlanningArtifact，不存在则返回 None
    """
    planning_file = _planning_file(artifact_id)
    if not planning_file.exists():
        return None
    
    with open(planning_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    return PlanningArtifact.from_dict(data)


def list_planning_artifacts(
    limit: int = 100,
) -> List[PlanningArtifact]:
    """
    列出 planning artifacts
    
    Args:
        limit: 最大返回数量
    
    Returns:
        PlanningArtifact 列表
    """
    _ensure_planning_dir()
    
    artifacts = []
    for planning_file in PLANNING_DIR.glob("*.json"):
        try:
            with open(planning_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            artifact = PlanningArtifact.from_dict(data)
            artifacts.append(artifact)
        except (json.JSONDecodeError, KeyError):
            pass
    
    # 按 created_at 排序（最新的在前）
    artifacts.sort(key=lambda a: a.created_at, reverse=True)
    
    return artifacts[:limit]


# CLI 入口
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python planning_default.py build --problem <statement> --scope <item1,item2> --owner <owner>")
        print("  python planning_default.py get <artifact_id>")
        print("  python planning_default.py list")
        print("  python planning_default.py validate <artifact_id>")
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == "build":
        # 简单示例：构建一个 planning artifact
        problem = "Example problem"
        scope = ["task1", "task2"]
        owner = "main"
        
        # 解析命令行参数（简化版）
        for i, arg in enumerate(sys.argv):
            if arg == "--problem" and i + 1 < len(sys.argv):
                problem = sys.argv[i + 1]
            elif arg == "--scope" and i + 1 < len(sys.argv):
                scope = sys.argv[i + 1].split(",")
            elif arg == "--owner" and i + 1 < len(sys.argv):
                owner = sys.argv[i + 1]
        
        artifact = build_planning_artifact(
            problem_statement=problem,
            in_scope=scope,
            owner=owner,
            phases=[{"phase": "phase1", "description": "First phase", "deliverable": "deliverable1"}],
        )
        
        print(json.dumps(artifact.to_dict(), indent=2))
        print(f"\nPlanning artifact written to: {artifact.write()}")
    
    elif cmd == "get":
        if len(sys.argv) < 3:
            print("Error: missing artifact_id")
            sys.exit(1)
        
        artifact_id = sys.argv[2]
        artifact = get_planning_artifact(artifact_id)
        if artifact:
            print(json.dumps(artifact.to_dict(), indent=2))
        else:
            print(f"Planning artifact {artifact_id} not found")
            sys.exit(1)
    
    elif cmd == "list":
        artifacts = list_planning_artifacts()
        print(json.dumps([a.to_dict() for a in artifacts], indent=2))
    
    elif cmd == "validate":
        if len(sys.argv) < 3:
            print("Error: missing artifact_id")
            sys.exit(1)
        
        artifact_id = sys.argv[2]
        artifact = get_planning_artifact(artifact_id)
        if not artifact:
            print(f"Planning artifact {artifact_id} not found")
            sys.exit(1)
        
        is_valid, errors = validate_planning_artifact(artifact)
        if is_valid:
            print("Planning artifact is valid")
        else:
            print("Planning artifact has errors:")
            for error in errors:
                print(f"  - {error}")
            sys.exit(1)
    
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
