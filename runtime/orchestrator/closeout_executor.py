#!/usr/bin/env python3
"""
closeout_executor.py — Closeout Executor with SubagentExecutor Integration

目标：将 SubagentExecutor 集成到 closeout 生成路径，提供自动化的 closeout artifact 生成能力。

这是 P0-6 Batch E 的最小实现：
- 基于 SubagentExecutor 封装 closeout 特定执行逻辑
- 保持 closeout_tracker.py 的契约不变
- 支持 closeout artifact 自动生成 -> 验证 -> 落盘
- 工具权限隔离到 closeout lane 级

核心类：
- CloseoutExecutor: closeout 专用执行器
- CloseoutExecutionResult: 执行结果封装

使用示例：
```python
from closeout_executor import CloseoutExecutor, CloseoutExecutionConfig

executor = CloseoutExecutor(
    config=CloseoutExecutionConfig(
        batch_id="batch_123",
        timeout_seconds=300,
    )
)

# 执行 closeout 生成
result = executor.execute(
    batch_id="batch_123",
    remaining_work=[],
)

# 获取结果
closeout_artifact = result.closeout_artifact
```
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

# 导入 SubagentExecutor
from subagent_executor import (
    SubagentConfig,
    SubagentExecutor,
    SubagentResult,
    TERMINAL_STATES,
    EXECUTOR_VERSION,
)

# 导入 Closeout Tracker
from closeout_tracker import (
    CloseoutArtifact,
    CloseoutStatus,
    create_closeout,
    CLOSEOUT_DIR,
    _ensure_closeout_dir,
    _closeout_file,
    _iso_now,
    _atomic_json_write,
)

# 导入 Lineage tracking
from lineage import check_fanin_readiness

__all__ = [
    "CLOSEOUT_EXECUTOR_VERSION",
    "CloseoutExecutionConfig",
    "CloseoutExecutionResult",
    "CloseoutExecutor",
    "execute_closeout",
    "get_closeout_execution_result",
    "list_closeout_executions",
]

CLOSEOUT_EXECUTOR_VERSION = "closeout_executor_v1"

# Closeout executor 存储目录
CLOSEOUT_EXECUTOR_DIR = Path(
    os.environ.get(
        "OPENCLAW_CLOSEOUT_EXECUTOR_DIR",
        Path.home() / ".openclaw" / "shared-context" / "closeout_executions",
    )
)


def _ensure_executor_dir():
    """确保执行状态目录存在"""
    CLOSEOUT_EXECUTOR_DIR.mkdir(parents=True, exist_ok=True)


def _execution_file(execution_id: str) -> Path:
    """返回执行状态文件路径"""
    return CLOSEOUT_EXECUTOR_DIR / f"{execution_id}.json"


def _generate_execution_id() -> str:
    """生成执行 ID"""
    import uuid
    return f"closeout_exec_{uuid.uuid4().hex[:12]}"


@dataclass
class CloseoutExecutionConfig:
    """
    Closeout Executor 配置
    
    核心字段：
    - batch_id: Batch ID
    - timeout_seconds: 超时时间
    - allowed_tools: 允许的工具列表
    - cwd: 工作目录
    - metadata: 额外元数据
    """
    batch_id: str
    timeout_seconds: int = 300
    allowed_tools: Optional[List[str]] = None
    cwd: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "timeout_seconds": self.timeout_seconds,
            "allowed_tools": self.allowed_tools,
            "cwd": self.cwd,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CloseoutExecutionConfig":
        return cls(
            batch_id=data.get("batch_id", ""),
            timeout_seconds=data.get("timeout_seconds", 300),
            allowed_tools=data.get("allowed_tools"),
            cwd=data.get("cwd", ""),
            metadata=data.get("metadata", {}),
        )


@dataclass
class CloseoutExecutionResult:
    """
    Closeout Executor 执行结果
    
    核心字段：
    - execution_id: 执行 ID
    - batch_id: Batch ID
    - status: 执行状态
    - subagent_task_id: Subagent 任务 ID
    - subagent_result: Subagent 执行结果
    - closeout_artifact: 生成的 closeout artifact
    - fanin_readiness: Fan-in readiness 检查结果
    - error: 错误信息
    - started_at: 开始时间
    - completed_at: 完成时间
    - metadata: 额外元数据
    """
    execution_id: str
    batch_id: str
    status: Literal["pending", "running", "completed", "failed", "timed_out"]
    subagent_task_id: Optional[str] = None
    subagent_result: Optional[SubagentResult] = None
    closeout_artifact: Optional[CloseoutArtifact] = None
    fanin_readiness: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "executor_version": CLOSEOUT_EXECUTOR_VERSION,
            "execution_id": self.execution_id,
            "batch_id": self.batch_id,
            "status": self.status,
            "subagent_task_id": self.subagent_task_id,
            "subagent_result": self.subagent_result.to_dict() if self.subagent_result else None,
            "closeout_artifact": self.closeout_artifact.to_dict() if self.closeout_artifact else None,
            "fanin_readiness": self.fanin_readiness,
            "error": self.error,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CloseoutExecutionResult":
        subagent_result_data = data.get("subagent_result")
        subagent_result = None
        if subagent_result_data:
            subagent_result = SubagentResult.from_dict(subagent_result_data)
        
        closeout_artifact_data = data.get("closeout_artifact")
        closeout_artifact = None
        if closeout_artifact_data:
            closeout_artifact = CloseoutArtifact.from_dict(closeout_artifact_data)
        
        return cls(
            execution_id=data.get("execution_id", ""),
            batch_id=data.get("batch_id", ""),
            status=data.get("status", "pending"),
            subagent_task_id=data.get("subagent_task_id"),
            subagent_result=subagent_result,
            closeout_artifact=closeout_artifact,
            fanin_readiness=data.get("fanin_readiness"),
            error=data.get("error"),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            metadata=data.get("metadata", {}),
        )


class CloseoutExecutor:
    """
    Closeout Executor — 封装 closeout 生成执行逻辑
    
    核心方法：
    - execute(): 执行 closeout 生成
    - get_result(): 获取执行结果
    """
    
    def __init__(self, config: CloseoutExecutionConfig):
        """
        初始化 CloseoutExecutor
        
        Args:
            config: Closeout 执行配置
        """
        self.config = config
        self.cwd = config.cwd or str(Path.home() / ".openclaw" / "workspace")
        
        # 工具过滤：closeout 只需要读/写/执行基本命令
        default_tools = ["read", "write", "edit", "exec"]
        self.allowed_tools = config.allowed_tools or default_tools
    
    def execute(
        self,
        remaining_work: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> CloseoutExecutionResult:
        """
        执行 closeout 生成
        
        Args:
            remaining_work: 剩余工作列表（用于验证 batch 是否真的完成）
            metadata: 额外元数据
        
        Returns:
            CloseoutExecutionResult
        """
        execution_id = _generate_execution_id()
        remaining_work = remaining_work or []
        metadata = metadata or {}
        
        # 创建执行结果（初始状态）
        result = CloseoutExecutionResult(
            execution_id=execution_id,
            batch_id=self.config.batch_id,
            status="pending",
            started_at=_iso_now(),
            metadata={
                **metadata,
                "executor_version": CLOSEOUT_EXECUTOR_VERSION,
                "allowed_tools": self.allowed_tools,
            },
        )
        
        # 持久化初始状态
        self._persist_result(result)
        
        # Step 1: 检查 fan-in readiness
        try:
            fanin_result = check_fanin_readiness(self.config.batch_id)
            result.fanin_readiness = {
                "status": fanin_result.get("status", "unknown"),
                "ready": fanin_result.get("ready", False),
                "children_count": fanin_result.get("children_count", 0),
                "completed_count": fanin_result.get("completed_count", 0),
            }
            
            if not fanin_result.get("ready", False):
                result.status = "failed"
                result.error = f"Fan-in not ready: {fanin_result.get('reason', 'unknown')}"
                result.completed_at = _iso_now()
                self._persist_result(result)
                return result
        except Exception as e:
            result.status = "failed"
            result.error = f"Fan-in readiness check failed: {str(e)}"
            result.completed_at = _iso_now()
            self._persist_result(result)
            return result
        
        # Step 2: 构建 closeout 生成任务
        task = self._build_closeout_task(remaining_work)
        
        # Step 3: 创建 SubagentExecutor
        subagent_config = SubagentConfig(
            label=f"closeout-{self.config.batch_id.replace('batch_', '')}",
            runtime="subagent",
            timeout_seconds=self.config.timeout_seconds,
            allowed_tools=self.allowed_tools,
            cwd=self.cwd,
            metadata={
                "source": "closeout_executor",
                "batch_id": self.config.batch_id,
                "execution_id": execution_id,
            },
        )
        
        executor = SubagentExecutor(config=subagent_config, cwd=self.cwd)
        
        # Step 4: 启动 subagent 异步执行
        task_id = executor.execute_async(task)
        result.subagent_task_id = task_id
        result.status = "running"
        self._persist_result(result)
        
        # Step 5: 等待 subagent 完成（带超时）
        import time
        start_time = time.time()
        timeout = self.config.timeout_seconds
        
        while time.time() - start_time < timeout:
            subagent_result = executor.get_result(task_id)
            
            if subagent_result and subagent_result.status in TERMINAL_STATES:
                result.subagent_result = subagent_result
                result.completed_at = _iso_now()
                
                if subagent_result.status == "completed":
                    result.status = "completed"
                    # Step 6: 生成 closeout artifact
                    try:
                        closeout_artifact = self._generate_closeout_artifact(remaining_work)
                        result.closeout_artifact = closeout_artifact
                    except Exception as e:
                        result.status = "failed"
                        result.error = f"Closeout artifact generation failed: {str(e)}"
                else:
                    result.status = "failed"
                    result.error = subagent_result.error or f"Subagent failed with status: {subagent_result.status}"
                
                self._persist_result(result)
                return result
            
            time.sleep(0.5)
        
        # 超时
        result.status = "timed_out"
        result.error = f"Closeout execution timed out after {timeout} seconds"
        result.completed_at = _iso_now()
        self._persist_result(result)
        
        # 尝试取消 subagent
        try:
            executor.cancel(task_id)
        except Exception:
            pass
        
        return result
    
    def _build_closeout_task(self, remaining_work: List[str]) -> str:
        """
        构建 closeout 生成任务 prompt
        
        Args:
            remaining_work: 剩余工作列表
        
        Returns:
            任务 prompt
        """
        return f"""
请为 batch `{self.config.batch_id}` 生成 closeout artifact。

要求：
1. 检查 batch 状态，确认所有任务已完成
2. 验证 remaining_work 为空或仅有可选优化项
3. 生成 closeout artifact，包含：
   - closeout_status: complete | pending_push | incomplete | blocked | stale
   - continuation_contract: stopped_because / next_step / next_owner
   - push_required: 是否需要 git push
4. 将 closeout artifact 写入标准路径

Remaining work: {remaining_work}

请输出结构化结果，包含：
- closeout_status
- continuation_contract
- push_required
- 验证步骤和证据
"""
    
    def _generate_closeout_artifact(self, remaining_work: List[str]) -> CloseoutArtifact:
        """
        生成 closeout artifact
        
        Args:
            remaining_work: 剩余工作列表
        
        Returns:
            CloseoutArtifact
        """
        # 决定 closeout status
        if not remaining_work:
            closeout_status = "complete"
        else:
            closeout_status = "incomplete"
        
        # 构建 continuation contract
        if closeout_status == "complete":
            stopped_because = "batch_completed"
            next_step = "Awaiting push and next batch dispatch"
            next_owner = "main"
        else:
            stopped_because = "batch_incomplete"
            next_step = f"Complete remaining work: {remaining_work}"
            next_owner = "owner"
        
        # 创建 closeout artifact
        artifact = create_closeout(
            batch_id=self.config.batch_id,
            closeout_status=closeout_status,  # type: ignore
            remaining_work=remaining_work,
            stopped_because=stopped_because,
            next_step=next_step,
            next_owner=next_owner,
            push_required=True,
            metadata={
                "source": "closeout_executor",
                "executor_version": CLOSEOUT_EXECUTOR_VERSION,
                "auto_generated": True,
            },
        )
        
        return artifact
    
    def _persist_result(self, result: CloseoutExecutionResult):
        """持久化执行结果"""
        _ensure_executor_dir()
        exec_file = _execution_file(result.execution_id)
        _atomic_json_write(exec_file, result.to_dict())
    
    def get_result(self, execution_id: str) -> Optional[CloseoutExecutionResult]:
        """
        获取执行结果
        
        Args:
            execution_id: 执行 ID
        
        Returns:
            CloseoutExecutionResult，如果不存在则返回 None
        """
        exec_file = _execution_file(execution_id)
        if not exec_file.exists():
            return None
        
        try:
            with open(exec_file, "r") as f:
                data = json.load(f)
            return CloseoutExecutionResult.from_dict(data)
        except (json.JSONDecodeError, KeyError):
            return None


def execute_closeout(
    batch_id: str,
    timeout_seconds: int = 300,
    remaining_work: Optional[List[str]] = None,
    cwd: Optional[str] = None,
) -> CloseoutExecutionResult:
    """
    便捷函数：执行 closeout 生成
    
    Args:
        batch_id: Batch ID
        timeout_seconds: 超时时间
        remaining_work: 剩余工作列表
        cwd: 工作目录
    
    Returns:
        CloseoutExecutionResult
    """
    config = CloseoutExecutionConfig(
        batch_id=batch_id,
        timeout_seconds=timeout_seconds,
        cwd=cwd or "",
    )
    
    executor = CloseoutExecutor(config)
    return executor.execute(remaining_work=remaining_work)


def get_closeout_execution_result(execution_id: str) -> Optional[CloseoutExecutionResult]:
    """
    便捷函数：获取 closeout 执行结果
    
    Args:
        execution_id: 执行 ID
    
    Returns:
        CloseoutExecutionResult
    """
    executor = CloseoutExecutor(CloseoutExecutionConfig(batch_id=""))
    return executor.get_result(execution_id)


def list_closeout_executions(
    batch_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
) -> List[CloseoutExecutionResult]:
    """
    列出 closeout 执行记录
    
    Args:
        batch_id: 按 batch_id 过滤
        status: 按状态过滤
        limit: 最大返回数量
    
    Returns:
        CloseoutExecutionResult 列表
    """
    _ensure_executor_dir()
    
    executions = []
    for exec_file in CLOSEOUT_EXECUTOR_DIR.glob("*.json"):
        try:
            with open(exec_file, "r") as f:
                data = json.load(f)
            result = CloseoutExecutionResult.from_dict(data)
            
            # 过滤
            if batch_id and result.batch_id != batch_id:
                continue
            if status and result.status != status:
                continue
            
            executions.append(result)
        except (json.JSONDecodeError, KeyError):
            pass
    
    # 按 started_at 倒序
    executions.sort(key=lambda e: e.started_at or "", reverse=True)
    
    return executions[:limit]


# CLI 入口
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python closeout_executor.py execute <batch_id> [--timeout <seconds>]")
        print("  python closeout_executor.py get <execution_id>")
        print("  python closeout_executor.py list [--batch <batch_id>] [--status <status>]")
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == "execute":
        if len(sys.argv) < 3:
            print("Error: missing batch_id")
            sys.exit(1)
        
        batch_id = sys.argv[2]
        timeout = 300
        if "--timeout" in sys.argv:
            idx = sys.argv.index("--timeout")
            if idx + 1 < len(sys.argv):
                timeout = int(sys.argv[idx + 1])
        
        result = execute_closeout(batch_id, timeout_seconds=timeout)
        print(json.dumps(result.to_dict(), indent=2))
    
    elif cmd == "get":
        if len(sys.argv) < 3:
            print("Error: missing execution_id")
            sys.exit(1)
        
        execution_id = sys.argv[2]
        result = get_closeout_execution_result(execution_id)
        
        if result:
            print(json.dumps(result.to_dict(), indent=2))
        else:
            print(f"Execution {execution_id} not found")
            sys.exit(1)
    
    elif cmd == "list":
        batch_id = None
        status = None
        if "--batch" in sys.argv:
            idx = sys.argv.index("--batch")
            if idx + 1 < len(sys.argv):
                batch_id = sys.argv[idx + 1]
        if "--status" in sys.argv:
            idx = sys.argv.index("--status")
            if idx + 1 < len(sys.argv):
                status = sys.argv[idx + 1]
        
        executions = list_closeout_executions(batch_id=batch_id, status=status)
        print(json.dumps([e.to_dict() for e in executions], indent=2))
    
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
