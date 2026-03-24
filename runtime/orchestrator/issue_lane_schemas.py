#!/usr/bin/env python3
"""
issue_lane_schemas.py — Coding Issue Lane Baseline Schema (v1)

目标：定义 coding issue lane 的最小输入输出契约。
这是 P0 Batch 3: Coding Issue Lane Baseline 的核心 contract。

核心概念：
- IssueInput: 标准 GitHub issue 输入（URL 或标准化 payload）
- PlanningOutput: planning artifact（可选，但推荐）
- ExecutionOutput: 执行结果（patch / PR description）
- CloseoutOutput: closeout summary（stopped_because / next_step / owner）

设计原则：
1. 最小通用 schema，不做大而全设计
2. 向后兼容，保留扩展现有 handoff schema
3. 支持 GitHub issue URL 和标准化 payload 两种输入
4. 输出包含 patch artifact / PR description / closeout summary
5. 默认接 Claude Code / subagent lane

版本：issue_lane_v1
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import urlparse

__all__ = [
    "ISSUE_LANE_SCHEMA_VERSION",
    "IssueInput",
    "IssueSource",
    "PlanningOutput",
    "ExecutionOutput",
    "PatchArtifact",
    "CloseoutOutput",
    "IssueLaneContract",
    "validate_github_issue_url",
    "parse_github_issue_url",
    "build_issue_input",
    "build_issue_lane_contract",
]

ISSUE_LANE_SCHEMA_VERSION = "issue_lane_v1"


# =============================================================================
# Issue Source Types
# =============================================================================

IssueSource = Literal["github_url", "github_payload", "manual", "api"]


@dataclass
class GitHubIssueRef:
    """
    GitHub Issue 引用信息
    
    从 URL 或 payload 提取的最小 issue 元数据
    """
    owner: str
    repo: str
    issue_number: int
    url: str
    
    @property
    def api_url(self) -> str:
        """GitHub API URL for this issue"""
        return f"https://api.github.com/repos/{self.owner}/{self.repo}/issues/{self.issue_number}"
    
    @property
    def html_url(self) -> str:
        """GitHub HTML URL for this issue"""
        return f"https://github.com/{self.owner}/{self.repo}/issues/{self.issue_number}"


def validate_github_issue_url(url: str) -> bool:
    """验证是否为有效的 GitHub issue URL"""
    try:
        parsed = urlparse(url)
        if parsed.netloc not in ("github.com", "www.github.com"):
            return False
        # Path should be /owner/repo/issues/number
        parts = parsed.path.strip("/").split("/")
        if len(parts) != 4 or parts[2] != "issues":
            return False
        int(parts[3])  # Validate issue number is integer
        return True
    except (ValueError, IndexError):
        return False


def parse_github_issue_url(url: str) -> Optional[GitHubIssueRef]:
    """从 GitHub issue URL 提取引用信息"""
    if not validate_github_issue_url(url):
        return None
    
    parsed = urlparse(url)
    parts = parsed.path.strip("/").split("/")
    
    return GitHubIssueRef(
        owner=parts[0],
        repo=parts[1],
        issue_number=int(parts[3]),
        url=url,
    )


# =============================================================================
# Issue Input Schema
# =============================================================================

@dataclass
class IssueInput:
    """
    Issue Lane Input — 标准 GitHub issue 输入
    
    核心字段：
    - issue_id: issue lane 内部 ID
    - source: 来源类型 (github_url / github_payload / manual / api)
    - source_url: GitHub issue URL（如果适用）
    - issue_ref: 解析后的 GitHub issue 引用
    - title: issue 标题
    - body: issue 正文
    - labels: issue 标签
    - assignee: 指派人
    - state: issue 状态 (open / closed)
    - created_at: 创建时间
    - updated_at: 更新时间
    - metadata: 额外元数据
    
    输入来源：
    1. GitHub URL: 通过 GitHub API 获取完整信息
    2. GitHub Payload: 直接使用 GitHub webhook / API 返回的 payload
    3. Manual: 手动创建的简化 issue
    4. API: 通过 orchestration API 传入
    """
    issue_id: str
    source: IssueSource
    source_url: Optional[str] = None
    issue_ref: Optional[GitHubIssueRef] = None
    title: str = ""
    body: str = ""
    labels: List[str] = field(default_factory=list)
    assignee: Optional[str] = None
    state: Literal["open", "closed"] = "open"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # Issue Lane 特定字段
    executor_preference: Literal["claude_code", "subagent", "manual"] = "claude_code"
    backend_preference: Literal["subagent", "tmux", "manual"] = "subagent"
    execution_profile: Literal["coding", "generic_subagent", "interactive_observable"] = "coding"
    owner: str = "main"  # 业务 owner (default: main for coding issues)
    
    def validate(self) -> tuple[bool, List[str]]:
        """验证 issue input 是否符合规则"""
        errors: List[str] = []
        
        # 规则 1: issue_id 不能为空
        if not self.issue_id or not self.issue_id.strip():
            errors.append("issue_id is required")
        
        # 规则 2: source 必须是有效值
        valid_sources = ["github_url", "github_payload", "manual", "api"]
        if self.source not in valid_sources:
            errors.append(f"source must be one of {valid_sources}")
        
        # 规则 3: github_url source 必须有 source_url 和 issue_ref
        if self.source == "github_url":
            if not self.source_url:
                errors.append("source_url is required for github_url source")
            if not self.issue_ref:
                errors.append("issue_ref is required for github_url source")
        
        # 规则 4: title 不能为空（至少要有简短描述）
        if not self.title or not self.title.strip():
            errors.append("title is required")
        
        # 规则 5: executor_preference 必须有效
        valid_executors = ["claude_code", "subagent", "manual"]
        if self.executor_preference not in valid_executors:
            errors.append(f"executor_preference must be one of {valid_executors}")
        
        return len(errors) == 0, errors
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "issue_id": self.issue_id,
            "source": self.source,
            "source_url": self.source_url,
            "issue_ref": {
                "owner": self.issue_ref.owner,
                "repo": self.issue_ref.repo,
                "issue_number": self.issue_ref.issue_number,
                "url": self.issue_ref.url,
            } if self.issue_ref else None,
            "title": self.title,
            "body": self.body,
            "labels": self.labels,
            "assignee": self.assignee,
            "state": self.state,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
            "executor_preference": self.executor_preference,
            "backend_preference": self.backend_preference,
            "execution_profile": self.execution_profile,
            "owner": self.owner,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "IssueInput":
        """从字典创建"""
        issue_ref_data = data.get("issue_ref")
        issue_ref = None
        if issue_ref_data:
            issue_ref = GitHubIssueRef(
                owner=issue_ref_data["owner"],
                repo=issue_ref_data["repo"],
                issue_number=issue_ref_data["issue_number"],
                url=issue_ref_data["url"],
            )
        
        return cls(
            issue_id=data["issue_id"],
            source=data["source"],
            source_url=data.get("source_url"),
            issue_ref=issue_ref,
            title=data.get("title", ""),
            body=data.get("body", ""),
            labels=data.get("labels", []),
            assignee=data.get("assignee"),
            state=data.get("state", "open"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            metadata=data.get("metadata", {}),
            executor_preference=data.get("executor_preference", "claude_code"),
            backend_preference=data.get("backend_preference", "subagent"),
            execution_profile=data.get("execution_profile", "coding"),
            owner=data.get("owner", "main"),
        )


def build_issue_input(
    *,
    issue_id: str,
    source: IssueSource,
    source_url: Optional[str] = None,
    title: str,
    body: str = "",
    labels: Optional[List[str]] = None,
    assignee: Optional[str] = None,
    executor_preference: Literal["claude_code", "subagent", "manual"] = "claude_code",
    backend_preference: Literal["subagent", "tmux", "manual"] = "subagent",
    owner: str = "main",
    metadata: Optional[Dict[str, Any]] = None,
) -> IssueInput:
    """
    构建 IssueInput 的便捷函数
    
    自动处理 github_url source 的 issue_ref 解析
    """
    issue_ref = None
    if source == "github_url" and source_url:
        issue_ref = parse_github_issue_url(source_url)
        if not issue_ref:
            raise ValueError(f"Invalid GitHub issue URL: {source_url}")
    
    return IssueInput(
        issue_id=issue_id,
        source=source,
        source_url=source_url,
        issue_ref=issue_ref,
        title=title,
        body=body,
        labels=labels or [],
        assignee=assignee,
        executor_preference=executor_preference,
        backend_preference=backend_preference,
        owner=owner,
        metadata=metadata or {},
    )


# =============================================================================
# Planning Output Schema
# =============================================================================

@dataclass
class PlanningOutput:
    """
    Planning Output — Issue Lane Planning Artifact
    
    这是从 issue 到 execution 的中间产物，包含：
    - problem reframing: 问题重述
    - scope: 范围定义
    - engineering review: 技术评审
    - execution plan: 执行计划
    
    可选但推荐：对于非 trivial 的 coding issue，应先有 planning
    """
    planning_id: str
    issue_id: str
    problem_reframing: str
    scope: str
    engineering_review: str
    execution_plan: str
    acceptance_criteria: List[str] = field(default_factory=list)
    estimated_effort: Optional[str] = None  # e.g., "S/M/L/XL" or "2-4 hours"
    risks: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def validate(self) -> tuple[bool, List[str]]:
        """验证 planning output"""
        errors: List[str] = []
        
        if not self.planning_id:
            errors.append("planning_id is required")
        if not self.issue_id:
            errors.append("issue_id is required")
        if not self.problem_reframing:
            errors.append("problem_reframing is required")
        if not self.execution_plan:
            errors.append("execution_plan is required")
        
        return len(errors) == 0, errors
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "planning_id": self.planning_id,
            "issue_id": self.issue_id,
            "problem_reframing": self.problem_reframing,
            "scope": self.scope,
            "engineering_review": self.engineering_review,
            "execution_plan": self.execution_plan,
            "acceptance_criteria": self.acceptance_criteria,
            "estimated_effort": self.estimated_effort,
            "risks": self.risks,
            "dependencies": self.dependencies,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }


# =============================================================================
# Execution Output Schema
# =============================================================================

@dataclass
class PatchArtifact:
    """
    Patch Artifact — 代码变更产物
    
    包含实际的代码变更，可以是：
    - git diff
    - 文件变更列表
    - PR-ready patch
    """
    patch_id: str
    issue_id: str
    planning_id: Optional[str] = None
    repo_path: Optional[str] = None
    files_changed: List[str] = field(default_factory=list)
    diff_summary: str = ""
    diff_content: Optional[str] = None  # 完整 diff（可选，可能很大）
    commit_message: Optional[str] = None
    branch_name: Optional[str] = None
    pr_ready: bool = False
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "patch_id": self.patch_id,
            "issue_id": self.issue_id,
            "planning_id": self.planning_id,
            "repo_path": self.repo_path,
            "files_changed": self.files_changed,
            "diff_summary": self.diff_summary,
            "diff_content": self.diff_content,
            "commit_message": self.commit_message,
            "branch_name": self.branch_name,
            "pr_ready": self.pr_ready,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }


@dataclass
class PRDescription:
    """
    PR Description — Pull Request 描述
    
    用于创建 GitHub PR 的标准描述模板
    """
    pr_id: str
    issue_id: str
    patch_id: str
    title: str
    body: str
    base_branch: str = "main"
    head_branch: Optional[str] = None
    labels: List[str] = field(default_factory=list)
    reviewers: List[str] = field(default_factory=list)
    linked_issues: List[str] = field(default_factory=list)
    checklist: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "pr_id": self.pr_id,
            "issue_id": self.issue_id,
            "patch_id": self.patch_id,
            "title": self.title,
            "body": self.body,
            "base_branch": self.base_branch,
            "head_branch": self.head_branch,
            "labels": self.labels,
            "reviewers": self.reviewers,
            "linked_issues": self.linked_issues,
            "checklist": self.checklist,
            "created_at": self.created_at,
        }


@dataclass
class ExecutionOutput:
    """
    Execution Output — Issue Lane Execution Result
    
    包含执行的所有产物：
    - patch: 代码变更
    - pr_description: PR 描述（如果适用）
    - execution_summary: 执行摘要
    - test_results: 测试结果
    """
    execution_id: str
    issue_id: str
    planning_id: Optional[str] = None
    executor: Literal["claude_code", "subagent", "manual"] = "claude_code"
    backend: Literal["subagent", "tmux", "manual"] = "subagent"
    status: Literal["success", "partial", "failed", "blocked"] = "success"
    patch: Optional[PatchArtifact] = None
    pr_description: Optional[PRDescription] = None
    execution_summary: str = ""
    test_results: Optional[Dict[str, Any]] = None
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    started_at: Optional[str] = None
    completed_at: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def validate(self) -> tuple[bool, List[str]]:
        """验证 execution output"""
        errors: List[str] = []
        
        if not self.execution_id:
            errors.append("execution_id is required")
        if not self.issue_id:
            errors.append("issue_id is required")
        
        return len(errors) == 0, errors
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "execution_id": self.execution_id,
            "issue_id": self.issue_id,
            "planning_id": self.planning_id,
            "executor": self.executor,
            "backend": self.backend,
            "status": self.status,
            "patch": self.patch.to_dict() if self.patch else None,
            "pr_description": self.pr_description.to_dict() if self.pr_description else None,
            "execution_summary": self.execution_summary,
            "test_results": self.test_results,
            "errors": self.errors,
            "warnings": self.warnings,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "metadata": self.metadata,
        }


# =============================================================================
# Closeout Output Schema
# =============================================================================

@dataclass
class CloseoutOutput:
    """
    Closeout Output — Issue Lane Closeout Summary
    
    这是 continuation contract 的核心部分，必须包含：
    - stopped_because: 为什么停止
    - next_step: 下一步是什么
    - next_owner: 谁应该接手
    - dispatch_readiness: 是否准备好 dispatch
    
    这是 P0 Batch 1 continuation contract v1 的 issue lane 特化版本
    
    注意：字段顺序遵循 dataclass 规则（无默认值字段在前，有默认值字段在后）
    """
    # 必需字段（无默认值）
    closeout_id: str
    issue_id: str
    stopped_because: str  # 为什么停止
    next_step: str  # 下一步是什么
    next_owner: str  # 谁应该接手
    
    # 可选字段（有默认值）
    execution_id: Optional[str] = None
    planning_id: Optional[str] = None
    dispatch_readiness: Literal["ready", "blocked", "pending_review", "complete"] = "blocked"
    
    # Closeout 摘要
    summary: str = ""
    decision: Optional[str] = None
    blocker: Optional[str] = None
    
    # 产物引用
    artifacts: List[str] = field(default_factory=list)  # 产物 ID 列表
    artifact_paths: List[str] = field(default_factory=list)  # 产物文件路径
    
    # 时间戳
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def validate(self) -> tuple[bool, List[str]]:
        """验证 closeout output"""
        errors: List[str] = []
        
        if not self.closeout_id:
            errors.append("closeout_id is required")
        if not self.issue_id:
            errors.append("issue_id is required")
        if not self.stopped_because:
            errors.append("stopped_because is required")
        if not self.next_step:
            errors.append("next_step is required")
        if not self.next_owner:
            errors.append("next_owner is required")
        
        # dispatch_readiness 验证
        valid_readiness = ["ready", "blocked", "pending_review", "complete"]
        if self.dispatch_readiness not in valid_readiness:
            errors.append(f"dispatch_readiness must be one of {valid_readiness}")
        
        # 如果 dispatch_readiness=ready，必须有 next_owner
        if self.dispatch_readiness == "ready" and not self.next_owner:
            errors.append("next_owner is required when dispatch_readiness=ready")
        
        return len(errors) == 0, errors
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "closeout_id": self.closeout_id,
            "issue_id": self.issue_id,
            "execution_id": self.execution_id,
            "planning_id": self.planning_id,
            "stopped_because": self.stopped_because,
            "next_step": self.next_step,
            "next_owner": self.next_owner,
            "dispatch_readiness": self.dispatch_readiness,
            "summary": self.summary,
            "decision": self.decision,
            "blocker": self.blocker,
            "artifacts": self.artifacts,
            "artifact_paths": self.artifact_paths,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CloseoutOutput":
        """从字典创建"""
        return cls(
            closeout_id=data["closeout_id"],
            issue_id=data["issue_id"],
            execution_id=data.get("execution_id"),
            planning_id=data.get("planning_id"),
            stopped_because=data["stopped_because"],
            next_step=data["next_step"],
            next_owner=data["next_owner"],
            dispatch_readiness=data.get("dispatch_readiness", "blocked"),
            summary=data.get("summary", ""),
            decision=data.get("decision"),
            blocker=data.get("blocker"),
            artifacts=data.get("artifacts", []),
            artifact_paths=data.get("artifact_paths", []),
            metadata=data.get("metadata", {}),
        )


# =============================================================================
# Issue Lane Contract (Unified)
# =============================================================================

@dataclass
class IssueLaneContract:
    """
    Issue Lane Contract — 统一契约
    
    包含 issue lane 的完整生命周期：
    input -> planning (optional) -> execution -> closeout
    
    这是 issue lane 的最高层级契约，用于：
    1. 验证 issue lane 的完整性
    2. 序列化/反序列化 issue lane 状态
    3. 与其他 lane 的互操作
    """
    contract_id: str
    version: str = ISSUE_LANE_SCHEMA_VERSION
    input: Optional[IssueInput] = None
    planning: Optional[PlanningOutput] = None
    execution: Optional[ExecutionOutput] = None
    closeout: Optional[CloseoutOutput] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def validate(self) -> tuple[bool, List[str]]:
        """验证完整契约"""
        errors: List[str] = []
        
        if not self.contract_id:
            errors.append("contract_id is required")
        
        # 验证 input
        if self.input:
            valid, input_errors = self.input.validate()
            if not valid:
                errors.extend([f"input.{e}" for e in input_errors])
        
        # 验证 planning（如果有）
        if self.planning:
            valid, planning_errors = self.planning.validate()
            if not valid:
                errors.extend([f"planning.{e}" for e in planning_errors])
        
        # 验证 execution（如果有）
        if self.execution:
            valid, execution_errors = self.execution.validate()
            if not valid:
                errors.extend([f"execution.{e}" for e in execution_errors])
        
        # 验证 closeout（如果有）
        if self.closeout:
            valid, closeout_errors = self.closeout.validate()
            if not valid:
                errors.extend([f"closeout.{e}" for e in closeout_errors])
        
        return len(errors) == 0, errors
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "contract_id": self.contract_id,
            "version": self.version,
            "input": self.input.to_dict() if self.input else None,
            "planning": self.planning.to_dict() if self.planning else None,
            "execution": self.execution.to_dict() if self.execution else None,
            "closeout": self.closeout.to_dict() if self.closeout else None,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "IssueLaneContract":
        """从字典创建"""
        input_data = data.get("input")
        planning_data = data.get("planning")
        execution_data = data.get("execution")
        closeout_data = data.get("closeout")
        
        return cls(
            contract_id=data["contract_id"],
            version=data.get("version", ISSUE_LANE_SCHEMA_VERSION),
            input=IssueInput.from_dict(input_data) if input_data else None,
            planning=PlanningOutput(**planning_data) if planning_data else None,
            execution=ExecutionOutput(**execution_data) if execution_data else None,
            closeout=CloseoutOutput.from_dict(closeout_data) if closeout_data else None,
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            metadata=data.get("metadata", {}),
        )


def build_issue_lane_contract(
    *,
    contract_id: str,
    issue_input: IssueInput,
    planning: Optional[PlanningOutput] = None,
    execution: Optional[ExecutionOutput] = None,
    closeout: Optional[CloseoutOutput] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> IssueLaneContract:
    """
    构建 Issue Lane Contract 的便捷函数
    """
    return IssueLaneContract(
        contract_id=contract_id,
        input=issue_input,
        planning=planning,
        execution=execution,
        closeout=closeout,
        metadata=metadata or {},
    )
