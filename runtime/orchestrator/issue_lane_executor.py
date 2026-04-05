#!/usr/bin/env python3
"""
issue_lane_executor.py — Coding Issue Lane Executor (v1)

目标：将 SubagentExecutor 集成到 coding issue lane，提供统一的执行入口。

这是 Deer-Flow 借鉴线 Batch D 的最小集成实现：
- 基于 SubagentExecutor 封装 issue lane 特定执行逻辑
- 保持 issue_lane_schemas.py 的契约不变
- 支持 planning -> execution -> closeout 完整链路
- 工具权限隔离到 issue lane 级

核心类：
- IssueLaneExecutor: issue lane 专用执行器
- IssueLaneExecutionResult: 执行结果封装

使用示例：
```python
from issue_lane_executor import IssueLaneExecutor, IssueLaneExecutionConfig

executor = IssueLaneExecutor(
    config=IssueLaneExecutionConfig(
        issue_id="issue_123",
        backend="subagent",
        timeout_seconds=1800,
    )
)

# 执行 issue
result = executor.execute(
    issue_input=issue_input,
    planning=planning_output,  # optional
)

# 获取结果
closeout = result.closeout
```
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

# 导入 SubagentExecutor (Batch A)
from subagent_executor import (
    SubagentConfig,
    SubagentExecutor,
    SubagentResult,
    TERMINAL_STATES,
    EXECUTOR_VERSION,
)

# 导入 Issue Lane Schemas
from issue_lane_schemas import (
    IssueInput,
    IssueSource,
    PlanningOutput,
    ExecutionOutput,
    PatchArtifact,
    PRDescription,
    CloseoutOutput,
    IssueLaneContract,
    build_issue_lane_contract,
    ISSUE_LANE_SCHEMA_VERSION,
)

__all__ = [
    "ISSUE_LANE_EXECUTOR_VERSION",
    "IssueLaneExecutionConfig",
    "IssueLaneExecutionResult",
    "IssueLaneExecutor",
    "execute_issue",
    "get_issue_execution_result",
    "list_issue_executions",
]

ISSUE_LANE_EXECUTOR_VERSION = "issue_lane_executor_v1"

# Issue lane execution 存储目录
ISSUE_LANE_EXECUTION_DIR = Path(
    os.environ.get(
        "OPENCLAW_ISSUE_LANE_EXECUTION_DIR",
        Path.home() / ".openclaw" / "shared-context" / "issue_lane_executions",
    )
)


def _ensure_execution_dir():
    """确保执行状态目录存在"""
    ISSUE_LANE_EXECUTION_DIR.mkdir(parents=True, exist_ok=True)


def _execution_file(execution_id: str) -> Path:
    """返回执行状态文件路径"""
    return ISSUE_LANE_EXECUTION_DIR / f"{execution_id}.json"


def _iso_now() -> str:
    """返回 ISO-8601 时间戳"""
    return datetime.now(timezone.utc).isoformat()


def _generate_execution_id() -> str:
    """生成执行 ID"""
    import uuid
    return f"issue_exec_{uuid.uuid4().hex[:12]}"


@dataclass
class IssueLaneExecutionConfig:
    """
    Issue Lane 执行配置
    
    核心字段：
    - issue_id: Issue ID
    - backend: 执行 backend (subagent / tmux / manual)
    - executor: 执行器类型 (claude_code / subagent / manual)
    - timeout_seconds: 超时时间
    - allowed_tools: 允许的工具列表
    - cwd: 工作目录
    - metadata: 额外元数据
    """
    issue_id: str
    backend: Literal["subagent", "tmux", "manual"] = "subagent"
    executor: Literal["claude_code", "subagent", "manual"] = "claude_code"
    timeout_seconds: int = 1800
    allowed_tools: Optional[List[str]] = None
    cwd: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "issue_id": self.issue_id,
            "backend": self.backend,
            "executor": self.executor,
            "timeout_seconds": self.timeout_seconds,
            "allowed_tools": self.allowed_tools,
            "cwd": self.cwd,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "IssueLaneExecutionConfig":
        return cls(
            issue_id=data.get("issue_id", ""),
            backend=data.get("backend", "subagent"),
            executor=data.get("executor", "claude_code"),
            timeout_seconds=data.get("timeout_seconds", 1800),
            allowed_tools=data.get("allowed_tools"),
            cwd=data.get("cwd", ""),
            metadata=data.get("metadata", {}),
        )
    
    def to_subagent_config(self, label: str) -> SubagentConfig:
        """转换为 SubagentConfig"""
        return SubagentConfig(
            label=label,
            runtime="subagent" if self.backend == "subagent" else "acp",
            timeout_seconds=self.timeout_seconds,
            allowed_tools=self.allowed_tools,
            cwd=self.cwd,
            metadata={
                **self.metadata,
                "issue_id": self.issue_id,
                "backend": self.backend,
                "executor": self.executor,
            },
        )


@dataclass
class IssueLaneExecutionResult:
    """
    Issue Lane 执行结果
    
    包含完整的执行链路产物：
    - execution_id: 执行 ID
    - issue_id: Issue ID
    - contract: Issue Lane Contract（包含 input/planning/execution/closeout）
    - subagent_result: Subagent 执行结果（如果适用）
    - status: 执行状态
    - error: 错误信息（如果失败）
    - started_at: 开始时间
    - completed_at: 完成时间
    """
    execution_id: str
    issue_id: str
    contract: IssueLaneContract
    subagent_result: Optional[SubagentResult] = None
    status: Literal["pending", "running", "completed", "failed", "timed_out"] = "pending"
    error: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "executor_version": ISSUE_LANE_EXECUTOR_VERSION,
            "execution_id": self.execution_id,
            "issue_id": self.issue_id,
            "contract": self.contract.to_dict() if self.contract else None,
            "subagent_result": self.subagent_result.to_dict() if self.subagent_result else None,
            "status": self.status,
            "error": self.error,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "IssueLaneExecutionResult":
        contract_data = data.get("contract")
        contract = None
        if contract_data:
            contract = IssueLaneContract.from_dict(contract_data)
        
        subagent_result_data = data.get("subagent_result")
        subagent_result = None
        if subagent_result_data:
            subagent_result = SubagentResult.from_dict(subagent_result_data)
        
        return cls(
            execution_id=data.get("execution_id", ""),
            issue_id=data.get("issue_id", ""),
            contract=contract,
            subagent_result=subagent_result,
            status=data.get("status", "pending"),
            error=data.get("error"),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            metadata=data.get("metadata", {}),
        )
    
    def write(self) -> Path:
        _ensure_execution_dir()
        exec_file = _execution_file(self.execution_id)
        tmp_file = exec_file.with_suffix(".tmp")
        with open(tmp_file, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
        result_path = tmp_file.replace(exec_file)
        try:
            from workflow_state_store import get_store
            store = get_store()
            if store.is_active:
                store.update_task(
                    self.issue_id,
                    execution_metadata={"issue_execution_id": self.execution_id},
                )
        except Exception:
            pass
        return result_path
    
    @classmethod
    def load(cls, execution_id: str) -> Optional["IssueLaneExecutionResult"]:
        """从文件加载执行结果"""
        exec_file = _execution_file(execution_id)
        if not exec_file.exists():
            return None
        
        with open(exec_file, "r") as f:
            data = json.load(f)
        
        return cls.from_dict(data)


class IssueLaneExecutor:
    """
    Issue Lane 执行器 — 封装 issue lane 的完整执行链路
    
    核心方法：
    - execute(issue_input, planning): 执行 issue，返回执行结果
    - get_result(execution_id): 获取执行结果
    - is_completed(execution_id): 检查是否完成
    
    设计原则：
    1. 基于 SubagentExecutor 封装，不重复造轮子
    2. 保持 issue_lane_schemas 契约不变
    3. 支持 planning -> execution -> closeout 完整链路
    4. 工具权限隔离到 issue lane 级
    """
    
    # 默认 coding issue 工具白名单
    DEFAULT_CODING_TOOLS = [
        "read", "write", "edit", "exec",
        "bash", "python", "node", "git",
    ]
    
    def __init__(
        self,
        config: IssueLaneExecutionConfig,
    ):
        """
        初始化 Issue Lane Executor
        
        Args:
            config: 执行配置
        """
        self.config = config
        
        # 工具过滤：coding issue 默认允许的工具
        allowed_tools = config.allowed_tools or self.DEFAULT_CODING_TOOLS[:]
        
        # 创建 SubagentExecutor
        subagent_config = config.to_subagent_config(
            label=f"issue-{config.issue_id}"
        )
        
        self.executor = SubagentExecutor(
            config=subagent_config,
            cwd=config.cwd or None,
        )
    
    def execute(
        self,
        issue_input: IssueInput,
        planning: Optional[PlanningOutput] = None,
    ) -> IssueLaneExecutionResult:
        """
        执行 issue
        
        Args:
            issue_input: Issue 输入
            planning: Planning artifact（可选）
        
        Returns:
            IssueLaneExecutionResult
        """
        execution_id = _generate_execution_id()
        
        # 创建初始 contract
        contract = build_issue_lane_contract(
            contract_id=f"contract_{execution_id}",
            issue_input=issue_input,
            planning=planning,
        )
        
        # 创建初始结果
        result = IssueLaneExecutionResult(
            execution_id=execution_id,
            issue_id=issue_input.issue_id,
            contract=contract,
            status="pending",
            started_at=_iso_now(),
            metadata={
                "executor_version": ISSUE_LANE_EXECUTOR_VERSION,
                "subagent_executor_version": EXECUTOR_VERSION,
            },
        )
        
        # 持久化初始状态
        result.write()
        
        # 构建执行任务描述
        task_description = self._build_task_description(issue_input, planning)
        
        # 启动 subagent 执行
        try:
            task_id = self.executor.execute_async(task_description)
            
            # 更新状态为 running
            result.status = "running"
            result.metadata["subagent_task_id"] = task_id
            result.write()
            
        except Exception as e:
            # 启动失败
            result.status = "failed"
            result.error = f"Failed to start subagent: {str(e)}"
            result.completed_at = _iso_now()
            
            # 生成 failure closeout
            contract.closeout = self._create_closeout(
                issue_input=issue_input,
                planning=planning,
                status="failed",
                error=result.error,
            )
            result.contract = contract
            result.write()
        
        return result
    
    def _build_task_description(
        self,
        issue_input: IssueInput,
        planning: Optional[PlanningOutput],
    ) -> str:
        """构建 subagent 任务描述"""
        parts = [
            f"Issue: {issue_input.title}",
            f"Source: {issue_input.source}",
        ]
        
        if issue_input.source_url:
            parts.append(f"URL: {issue_input.source_url}")
        
        if issue_input.body:
            parts.append(f"\nDescription:\n{issue_input.body}")
        
        if planning:
            parts.append(f"\nPlanning:\n{planning.execution_plan}")
            if planning.acceptance_criteria:
                parts.append(f"\nAcceptance Criteria:\n{planning.acceptance_criteria}")
        
        if issue_input.labels:
            parts.append(f"\nLabels: {', '.join(issue_input.labels)}")
        
        parts.append(
            f"\n\nExecution Profile: {issue_input.execution_profile}"
        )
        parts.append(
            f"\nBackend: {issue_input.backend_preference}"
        )
        
        return "\n".join(parts)
    
    def _create_closeout(
        self,
        issue_input: IssueInput,
        planning: Optional[PlanningOutput],
        status: Literal["success", "partial", "failed", "blocked"],
        error: Optional[str] = None,
    ) -> CloseoutOutput:
        """创建 closeout output"""
        import uuid
        
        if status == "failed":
            return CloseoutOutput(
                closeout_id=f"closeout_{uuid.uuid4().hex[:12]}",
                issue_id=issue_input.issue_id,
                stopped_because=f"Execution failed: {error or 'Unknown error'}",
                next_step="Review error and retry or escalate",
                next_owner="main",
                dispatch_readiness="blocked",
                decision="retry_or_escalate",
                blocker=error,
            )
        elif status == "success":
            return CloseoutOutput(
                closeout_id=f"closeout_{uuid.uuid4().hex[:12]}",
                issue_id=issue_input.issue_id,
                stopped_because="Execution completed successfully",
                next_step="Review and merge changes",
                next_owner="main",
                dispatch_readiness="ready",
                decision="complete",
            )
        else:
            return CloseoutOutput(
                closeout_id=f"closeout_{uuid.uuid4().hex[:12]}",
                issue_id=issue_input.issue_id,
                stopped_because=f"Execution {status}",
                next_step="Review and decide next action",
                next_owner="main",
                dispatch_readiness="pending_review",
                decision="review",
            )
    
    def get_result(self, execution_id: str) -> Optional[IssueLaneExecutionResult]:
        """
        获取执行结果
        
        Args:
            execution_id: 执行 ID
        
        Returns:
            IssueLaneExecutionResult，不存在则返回 None
        """
        return IssueLaneExecutionResult.load(execution_id)
    
    def is_completed(self, execution_id: str) -> bool:
        """
        检查执行是否完成
        
        Args:
            execution_id: 执行 ID
        
        Returns:
            True 如果执行已完成
        """
        result = self.get_result(execution_id)
        return result is not None and result.status in {"completed", "failed", "timed_out"}
    
    def get_subagent_status(self, execution_id: str) -> Optional[Dict[str, Any]]:
        """
        获取 subagent 执行状态
        
        Args:
            execution_id: 执行 ID
        
        Returns:
            Subagent 状态字典，不存在则返回 None
        """
        result = self.get_result(execution_id)
        if not result or not result.metadata.get("subagent_task_id"):
            return None
        
        task_id = result.metadata["subagent_task_id"]
        subagent_result = self.executor.get_result(task_id)
        
        if not subagent_result:
            return None
        
        return {
            "task_id": task_id,
            "status": subagent_result.status,
            "result": subagent_result.result,
            "error": subagent_result.error,
            "started_at": subagent_result.started_at,
            "completed_at": subagent_result.completed_at,
        }


# ============ 便捷函数 ============

def execute_issue(
    issue_input: IssueInput,
    planning: Optional[PlanningOutput] = None,
    backend: Literal["subagent", "tmux", "manual"] = "subagent",
    executor: Literal["claude_code", "subagent", "manual"] = "claude_code",
    timeout_seconds: int = 1800,
    allowed_tools: Optional[List[str]] = None,
    cwd: Optional[str] = None,
) -> IssueLaneExecutionResult:
    """
    便捷函数：执行 issue
    
    Args:
        issue_input: Issue 输入
        planning: Planning artifact（可选）
        backend: 执行 backend
        executor: 执行器类型
        timeout_seconds: 超时时间
        allowed_tools: 允许的工具列表
        cwd: 工作目录
    
    Returns:
        IssueLaneExecutionResult
    """
    config = IssueLaneExecutionConfig(
        issue_id=issue_input.issue_id,
        backend=backend,
        executor=executor,
        timeout_seconds=timeout_seconds,
        allowed_tools=allowed_tools,
        cwd=cwd or "",
    )
    
    executor_instance = IssueLaneExecutor(config)
    return executor_instance.execute(issue_input, planning)


def get_issue_execution_result(
    execution_id: str,
) -> Optional[IssueLaneExecutionResult]:
    """
    便捷函数：获取 issue 执行结果
    
    Args:
        execution_id: 执行 ID
    
    Returns:
        IssueLaneExecutionResult
    """
    return IssueLaneExecutionResult.load(execution_id)


def list_issue_executions(
    issue_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
) -> List[IssueLaneExecutionResult]:
    """
    列出 issue 执行结果
    
    Args:
        issue_id: 按 issue_id 过滤
        status: 按状态过滤
        limit: 最大返回数量
    
    Returns:
        IssueLaneExecutionResult 列表
    """
    _ensure_execution_dir()
    
    executions = []
    for exec_file in ISSUE_LANE_EXECUTION_DIR.glob("*.json"):
        try:
            with open(exec_file, "r") as f:
                data = json.load(f)
            result = IssueLaneExecutionResult.from_dict(data)
            
            # 过滤
            if issue_id and result.issue_id != issue_id:
                continue
            if status and result.status != status:
                continue
            
            executions.append(result)
        except (json.JSONDecodeError, KeyError):
            pass
    
    # 按 started_at 排序
    executions.sort(key=lambda e: e.started_at or "", reverse=True)
    
    return executions[:limit]


# ============ CLI 入口 ============

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python issue_lane_executor.py execute <issue_id> <title> [body]")
        print("  python issue_lane_executor.py get <execution_id>")
        print("  python issue_lane_executor.py list [--issue <issue_id>] [--status <status>]")
        print("  python issue_lane_executor.py status <execution_id>")
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == "execute":
        if len(sys.argv) < 4:
            print("Error: missing issue_id or title")
            sys.exit(1)
        
        issue_id = sys.argv[2]
        title = sys.argv[3]
        body = sys.argv[4] if len(sys.argv) > 4 else ""
        
        # 创建 issue input
        issue_input = IssueInput(
            issue_id=issue_id,
            source="manual",
            title=title,
            body=body,
        )
        
        # 执行
        result = execute_issue(issue_input)
        print(json.dumps(result.to_dict(), indent=2))
        print(f"\nExecution started: {result.execution_id}")
        print(f"Status: {result.status}")
        print(f"Check status with: python issue_lane_executor.py status {result.execution_id}")
    
    elif cmd == "get":
        if len(sys.argv) < 3:
            print("Error: missing execution_id")
            sys.exit(1)
        
        execution_id = sys.argv[2]
        result = get_issue_execution_result(execution_id)
        
        if result:
            print(json.dumps(result.to_dict(), indent=2))
        else:
            print(f"Execution not found: {execution_id}")
            sys.exit(1)
    
    elif cmd == "list":
        issue_id = None
        status = None
        if "--issue" in sys.argv:
            idx = sys.argv.index("--issue")
            if idx + 1 < len(sys.argv):
                issue_id = sys.argv[idx + 1]
        if "--status" in sys.argv:
            idx = sys.argv.index("--status")
            if idx + 1 < len(sys.argv):
                status = sys.argv[idx + 1]
        
        executions = list_issue_executions(issue_id=issue_id, status=status)
        print(json.dumps([e.to_dict() for e in executions], indent=2))
    
    elif cmd == "status":
        if len(sys.argv) < 3:
            print("Error: missing execution_id")
            sys.exit(1)
        
        execution_id = sys.argv[2]
        result = get_issue_execution_result(execution_id)
        
        if not result:
            print(f"Execution not found: {execution_id}")
            sys.exit(1)
        
        print(f"Execution ID: {result.execution_id}")
        print(f"Issue ID: {result.issue_id}")
        print(f"Status: {result.status}")
        
        if result.started_at:
            print(f"Started: {result.started_at}")
        if result.completed_at:
            print(f"Completed: {result.completed_at}")
        if result.error:
            print(f"Error: {result.error}")
        
        # Subagent 状态
        subagent_status = result.metadata.get("subagent_task_id")
        if subagent_status:
            print(f"Subagent Task: {subagent_status}")
    
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
