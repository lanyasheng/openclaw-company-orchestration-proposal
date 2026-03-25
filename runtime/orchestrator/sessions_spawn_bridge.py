#!/usr/bin/env python3
"""
sessions_spawn_bridge.py — Universal Partial-Completion Continuation Framework v10

目标：实现 **Real OpenClaw sessions_spawn Integration**。

核心能力：
1. 读取 V8 产生的 canonical sessions_spawn request / execution envelope
2. 调用真实的 OpenClaw `sessions_spawn(runtime="subagent")` 路径
3. 记录真实执行结果：
   - api_execution_status = started | failed | blocked
   - api_execution_reason
   - childSessionKey / runId（若成功）
   - linkage 回 request_id / dispatch_id / spawn_id / source task_id
4. 生成 canonical API execution artifact 落盘
5. 支持 auto-trigger 对 allowlist 场景进入真实 API execution
6. 支持 guard / dedupe / safe mode

当前阶段：V10 — Real OpenClaw sessions_spawn API execution via subagent runner

**P0-3 Batch 4 增强**:
- `_call_via_python_api()` 现在调用真实 subagent runner 脚本
- 生成真实 runId / childSessionKey / pid
- 后台启动 subagent 进程（非阻塞）
- 保持 safe_mode 默认开启（生产安全）

这是 v10 模块，通用 kernel，trading 仅作为首个消费者/样例。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

# 导入 V8 模块
from sessions_spawn_request import (
    SessionsSpawnRequest,
    get_spawn_request,
    list_spawn_requests,
    SPAWN_REQUEST_DIR,
    _load_auto_trigger_config,
    _is_auto_triggered,
    _record_auto_trigger,
)
from bridge_consumer import (
    BridgeConsumer,
    BridgeConsumerPolicy,
    BridgeConsumedArtifact,
    ExecutionResult,
    BRIDGE_CONSUMED_DIR,
    _ensure_consumed_dir,
    _iso_now,
    _generate_consumed_id,
    _generate_consumed_dedupe_key,
    _load_consumed_index,
    _save_consumed_index,
    get_consumed_by_request,
)

# Wave 2 Cutover: Import SubagentExecutor for unified execution substrate
from subagent_executor import (
    SubagentConfig,
    SubagentExecutor,
    SubagentResult,
    TERMINAL_STATES,
)

# Lineage tracking integration (minimal slice)
from lineage import create_lineage_record, LineageRecord

__all__ = [
    "APIExecutionStatus",
    "APIExecutionResult",
    "SessionsSpawnBridgePolicy",
    "SessionsSpawnBridge",
    "execute_sessions_spawn_api",
    "list_api_executions",
    "get_api_execution",
    "auto_trigger_real_execution",
    "EXECUTION_VERSION",
]

EXECUTION_VERSION = "sessions_spawn_api_execution_v1"

# API execution 存储目录
API_EXECUTION_DIR = Path(
    os.environ.get(
        "OPENCLAW_API_EXECUTION_DIR",
        Path.home() / ".openclaw" / "shared-context" / "api_executions",
    )
)

# API execution 索引文件
API_EXECUTION_INDEX_FILE = API_EXECUTION_DIR / "api_execution_index.json"

# Auto-trigger 配置扩展（V9 新增）
AUTO_TRIGGER_REAL_EXEC_CONFIG_FILE = SPAWN_REQUEST_DIR / "auto_trigger_real_exec_config.json"


APIExecutionStatus = Literal["started", "failed", "blocked", "pending"]


def _ensure_api_execution_dir():
    """确保 API execution 目录存在"""
    API_EXECUTION_DIR.mkdir(parents=True, exist_ok=True)


def _api_execution_file(execution_id: str) -> Path:
    """返回 API execution artifact 文件路径"""
    return API_EXECUTION_DIR / f"{execution_id}.json"


def _generate_execution_id() -> str:
    """生成 stable execution ID"""
    import uuid
    return f"exec_api_{uuid.uuid4().hex[:12]}"


def _generate_api_execution_dedupe_key(request_id: str) -> str:
    """生成 API execution 去重 key"""
    return f"api_exec_dedupe:{request_id}"


def _load_api_execution_index() -> Dict[str, str]:
    """加载 API execution index（request_id -> execution_id 映射）"""
    _ensure_api_execution_dir()
    if not API_EXECUTION_INDEX_FILE.exists():
        return {}
    
    try:
        with open(API_EXECUTION_INDEX_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, KeyError):
        return {}


def _save_api_execution_index(index: Dict[str, str]):
    """保存 API execution index"""
    _ensure_api_execution_dir()
    tmp_file = API_EXECUTION_INDEX_FILE.with_suffix(".tmp")
    with open(tmp_file, "w") as f:
        json.dump(index, f, indent=2)
    tmp_file.replace(API_EXECUTION_INDEX_FILE)


def _record_api_execution_dedupe(request_id: str, execution_id: str):
    """记录 API execution dedupe"""
    index = _load_api_execution_index()
    index[request_id] = execution_id
    _save_api_execution_index(index)


def _is_already_executed(request_id: str) -> bool:
    """检查是否已存在 API execution"""
    index = _load_api_execution_index()
    return request_id in index


def _get_execution_id_by_request(request_id: str) -> Optional[str]:
    """通过 request_id 获取 execution_id"""
    index = _load_api_execution_index()
    return index.get(request_id)


# ==================== V9 Auto-Trigger Real Execution Config ====================

def _load_auto_trigger_real_exec_config() -> Dict[str, Any]:
    """
    加载 auto-trigger real execution 配置。
    
    配置格式：
    {
        "enabled": bool,
        "allowlist": List[str],  # scenario allowlist（仅白名单场景可真实执行）
        "denylist": List[str],
        "require_manual_approval": bool,
        "safe_mode": bool,  # True=仅模拟，False=真实执行
        "max_concurrent_executions": int,
    }
    """
    _ensure_request_dir()
    if not AUTO_TRIGGER_REAL_EXEC_CONFIG_FILE.exists():
        return {
            "enabled": False,
            "allowlist": ["trading"],  # 默认仅 trading 场景可真实执行
            "denylist": [],
            "require_manual_approval": True,
            "safe_mode": True,  # 默认安全模式
            "max_concurrent_executions": 3,
        }
    
    try:
        with open(AUTO_TRIGGER_REAL_EXEC_CONFIG_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, KeyError):
        return {
            "enabled": False,
            "allowlist": ["trading"],
            "denylist": [],
            "require_manual_approval": True,
            "safe_mode": True,
            "max_concurrent_executions": 3,
        }


def _save_auto_trigger_real_exec_config(config: Dict[str, Any]):
    """保存 auto-trigger real execution 配置"""
    _ensure_request_dir()
    tmp_file = AUTO_TRIGGER_REAL_EXEC_CONFIG_FILE.with_suffix(".tmp")
    with open(tmp_file, "w") as f:
        json.dump(config, f, indent=2)
    tmp_file.replace(AUTO_TRIGGER_REAL_EXEC_CONFIG_FILE)


def _ensure_request_dir():
    """确保 spawn request 目录存在"""
    SPAWN_REQUEST_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class APIExecutionResult:
    """
    V9 API 执行结果 — 记录真实 OpenClaw sessions_spawn API 调用结果。
    
    核心字段：
    - api_execution_status: started | failed | blocked | pending
    - api_execution_reason: 执行原因/错误信息
    - childSessionKey: OpenClaw 返回的子 session key（如果成功）
    - runId: OpenClaw 返回的运行 ID（如果成功）
    - api_response: 原始 API 响应
    - api_error: API 错误信息
    - linkage: 完整链路 ID 映射
    """
    api_execution_status: APIExecutionStatus
    api_execution_reason: str
    api_execution_time: str
    childSessionKey: Optional[str] = None
    runId: Optional[str] = None
    api_response: Optional[Dict[str, Any]] = None
    api_error: Optional[str] = None
    linkage: Optional[Dict[str, str]] = None
    request_snapshot: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "api_execution_status": self.api_execution_status,
            "api_execution_reason": self.api_execution_reason,
            "api_execution_time": self.api_execution_time,
            "childSessionKey": self.childSessionKey,
            "runId": self.runId,
            "api_response": self.api_response,
            "api_error": self.api_error,
            "linkage": self.linkage,
            "request_snapshot": self.request_snapshot,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "APIExecutionResult":
        return cls(
            api_execution_status=data.get("api_execution_status", "blocked"),
            api_execution_reason=data.get("api_execution_reason", ""),
            api_execution_time=data.get("api_execution_time", ""),
            childSessionKey=data.get("childSessionKey"),
            runId=data.get("runId"),
            api_response=data.get("api_response"),
            api_error=data.get("api_error"),
            linkage=data.get("linkage"),
            request_snapshot=data.get("request_snapshot"),
        )


@dataclass
class SessionsSpawnBridgePolicy:
    """
    V9 Bridge policy — 评估是否可执行真实 API call。
    
    核心字段：
    - require_request_status: 要求的 request status
    - prevent_duplicate: 防止重复执行
    - safe_mode: 安全模式（默认 True，仅记录不执行）
    - allowlist: 允许真实执行的场景列表
    - denylist: 禁止真实执行的场景列表
    - require_manual_approval: 需要手动审批
    - max_concurrent: 最大并发执行数
    """
    require_request_status: str = "prepared"
    prevent_duplicate: bool = True
    safe_mode: bool = True  # 默认安全模式
    allowlist: List[str] = field(default_factory=lambda: ["trading"])
    denylist: List[str] = field(default_factory=list)
    require_manual_approval: bool = True
    max_concurrent: int = 3
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "require_request_status": self.require_request_status,
            "prevent_duplicate": self.prevent_duplicate,
            "safe_mode": self.safe_mode,
            "allowlist": self.allowlist,
            "denylist": self.denylist,
            "require_manual_approval": self.require_manual_approval,
            "max_concurrent": self.max_concurrent,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionsSpawnBridgePolicy":
        return cls(
            require_request_status=data.get("require_request_status", "prepared"),
            prevent_duplicate=data.get("prevent_duplicate", True),
            safe_mode=data.get("safe_mode", True),
            allowlist=data.get("allowlist", ["trading"]),
            denylist=data.get("denylist", []),
            require_manual_approval=data.get("require_manual_approval", True),
            max_concurrent=data.get("max_concurrent", 3),
        )
    
    def should_execute_real(self, scenario: str) -> bool:
        """检查场景是否允许真实执行"""
        if self.safe_mode:
            return False
        if scenario in self.denylist:
            return False
        if self.allowlist and scenario not in self.allowlist:
            return False
        return True


@dataclass
class SessionsSpawnAPIExecution:
    """
    V9 API execution artifact — 记录真实 sessions_spawn API 调用。
    
    核心字段：
    - execution_id: API execution ID
    - source_request_id: 来源 request ID
    - source_receipt_id: 来源 receipt ID
    - source_execution_id: 来源 execution ID
    - source_spawn_id: 来源 spawn ID
    - source_dispatch_id: 来源 dispatch ID
    - source_registration_id: 来源 registration ID
    - source_task_id: 来源 task ID
    - api_execution_status: started | failed | blocked | pending
    - api_execution_reason: 执行原因
    - api_execution_time: 执行时间戳
    - api_execution_result: API 执行结果
    - dedupe_key: 去重 key
    - policy_evaluation: policy 评估结果
    - metadata: 额外元数据
    """
    execution_id: str
    source_request_id: str
    source_receipt_id: str
    source_execution_id: str
    source_spawn_id: str
    source_dispatch_id: str
    source_registration_id: str
    source_task_id: str
    api_execution_status: APIExecutionStatus
    api_execution_reason: str
    api_execution_time: str
    api_execution_result: Optional[APIExecutionResult] = None
    dedupe_key: str = ""
    policy_evaluation: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    lineage_id: Optional[str] = None  # Lineage tracking (minimal slice)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "execution_version": EXECUTION_VERSION,
            "execution_id": self.execution_id,
            "source_request_id": self.source_request_id,
            "source_receipt_id": self.source_receipt_id,
            "source_execution_id": self.source_execution_id,
            "source_spawn_id": self.source_spawn_id,
            "source_dispatch_id": self.source_dispatch_id,
            "source_registration_id": self.source_registration_id,
            "source_task_id": self.source_task_id,
            "api_execution_status": self.api_execution_status,
            "api_execution_reason": self.api_execution_reason,
            "api_execution_time": self.api_execution_time,
            "api_execution_result": self.api_execution_result.to_dict() if self.api_execution_result else None,
            "dedupe_key": self.dedupe_key,
            "policy_evaluation": self.policy_evaluation,
            "metadata": self.metadata,
            "lineage_id": self.lineage_id,  # Lineage tracking (minimal slice)
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionsSpawnAPIExecution":
        result_data = data.get("api_execution_result")
        api_result = None
        if result_data:
            api_result = APIExecutionResult.from_dict(result_data)
        
        return cls(
            execution_id=data.get("execution_id", ""),
            source_request_id=data.get("source_request_id", ""),
            source_receipt_id=data.get("source_receipt_id", ""),
            source_execution_id=data.get("source_execution_id", ""),
            source_spawn_id=data.get("source_spawn_id", ""),
            source_dispatch_id=data.get("source_dispatch_id", ""),
            source_registration_id=data.get("source_registration_id", ""),
            source_task_id=data.get("source_task_id", ""),
            api_execution_status=data.get("api_execution_status", "blocked"),
            api_execution_reason=data.get("api_execution_reason", ""),
            api_execution_time=data.get("api_execution_time", ""),
            api_execution_result=api_result,
            dedupe_key=data.get("dedupe_key", ""),
            policy_evaluation=data.get("policy_evaluation"),
            metadata=data.get("metadata", {}),
            lineage_id=data.get("lineage_id"),  # Lineage tracking (minimal slice)
        )
    
    def write(self) -> Path:
        """写入 API execution artifact"""
        _ensure_api_execution_dir()
        exec_file = _api_execution_file(self.execution_id)
        tmp_file = exec_file.with_suffix(".tmp")
        with open(tmp_file, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
        tmp_file.replace(exec_file)
        return exec_file
    
    def get_linkage(self) -> Dict[str, str]:
        """返回完整 linkage"""
        return {
            "execution_id": self.execution_id,
            "request_id": self.source_request_id,
            "receipt_id": self.source_receipt_id,
            "execution_id": self.source_execution_id,
            "spawn_id": self.source_spawn_id,
            "dispatch_id": self.source_dispatch_id,
            "registration_id": self.source_registration_id,
            "task_id": self.source_task_id,
        }


class SessionsSpawnBridge:
    """
    V9 Sessions Spawn Bridge — 真实调用 OpenClaw sessions_spawn API。
    """
    
    def __init__(self, policy: Optional[SessionsSpawnBridgePolicy] = None):
        self.policy = policy or SessionsSpawnBridgePolicy()
    
    def evaluate_policy(
        self,
        request: SessionsSpawnRequest,
        existing_execution: Optional[SessionsSpawnAPIExecution] = None,
    ) -> Dict[str, Any]:
        """
        评估执行 policy。
        
        Returns:
            {
                "eligible": bool,
                "blocked_reasons": List[str],
                "checks": List[Dict],
                "should_execute_real": bool,
            }
        """
        checks: List[Dict[str, Any]] = []
        blocked_reasons: List[str] = []
        should_execute_real = False
        
        # Check 1: request status
        status_ok = request.spawn_request_status == self.policy.require_request_status
        checks.append({
            "name": "request_status",
            "expected": self.policy.require_request_status,
            "actual": request.spawn_request_status,
            "passed": status_ok,
        })
        if not status_ok:
            blocked_reasons.append(
                f"Request status is '{request.spawn_request_status}', required '{self.policy.require_request_status}'"
            )
        
        # Check 2: duplicate prevention
        duplicate_ok = True
        if self.policy.prevent_duplicate:
            is_duplicate = _is_already_executed(request.request_id)
            if is_duplicate:
                duplicate_ok = False
                blocked_reasons.append(
                    f"Duplicate execution: request {request.request_id} already executed"
                )
        
        checks.append({
            "name": "prevent_duplicate_execution",
            "expected": "no existing execution",
            "actual": "duplicate_found" if not duplicate_ok else "no_duplicate",
            "passed": duplicate_ok,
        })
        
        # Check 3: required metadata
        metadata = request.sessions_spawn_params.get("metadata", {})
        required_fields = ["dispatch_id", "spawn_id"]
        missing = [f for f in required_fields if f not in metadata]
        metadata_ok = len(missing) == 0
        checks.append({
            "name": "required_metadata",
            "expected": required_fields,
            "actual": "missing: " + ", ".join(missing) if missing else "all present",
            "passed": metadata_ok,
        })
        if not metadata_ok:
            blocked_reasons.append(f"Missing metadata: {', '.join(missing)}")
        
        # Check 4: task required
        has_task = bool(request.sessions_spawn_params.get("task"))
        task_ok = has_task
        checks.append({
            "name": "task_required",
            "expected": "non-empty task",
            "actual": "present" if has_task else "missing",
            "passed": task_ok,
        })
        if not task_ok:
            blocked_reasons.append("Missing task in sessions_spawn_params")
        
        # Check 5: scenario allowlist/denylist (for real execution)
        scenario = metadata.get("scenario", "generic")
        if self.policy.safe_mode:
            should_execute_real = False
            checks.append({
                "name": "safe_mode",
                "expected": "simulate only",
                "actual": "safe_mode enabled",
                "passed": True,
            })
        else:
            if scenario in self.policy.denylist:
                should_execute_real = False
                blocked_reasons.append(f"Scenario '{scenario}' in denylist")
            elif self.policy.allowlist and scenario not in self.policy.allowlist:
                should_execute_real = False
                blocked_reasons.append(f"Scenario '{scenario}' not in allowlist")
            else:
                should_execute_real = True
        
        checks.append({
            "name": "scenario_allowlist",
            "expected": f"allowlist={self.policy.allowlist}",
            "actual": f"scenario={scenario}, execute_real={should_execute_real}",
            "passed": True,
        })
        
        return {
            "eligible": len(blocked_reasons) == 0,
            "blocked_reasons": blocked_reasons,
            "checks": checks,
            "should_execute_real": should_execute_real,
        }
    
    def _call_openclaw_sessions_spawn(
        self,
        request: SessionsSpawnRequest,
    ) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """
        **核心**: 调用真实 OpenClaw sessions_spawn API。
        
        使用 OpenClaw 现有 subagent runner 基础设施（run_subagent_claude_v1.sh）。
        
        注意：不使用 `openclaw sessions_spawn` CLI 命令，因为该子命令不存在。
        直接使用 Python API 调用 runner 脚本。
        
        Args:
            request: Sessions spawn request
        
        Returns:
            (success, error_message, api_response)
        """
        spawn_params = request.sessions_spawn_params
        spawn_params["metadata"]["request_id"] = request.request_id
        
        # 构建 sessions_spawn 调用参数
        call_params = {
            "task": spawn_params.get("task", ""),
            "runtime": spawn_params.get("runtime", "subagent"),
            "cwd": spawn_params.get("cwd") or str(Path.home() / ".openclaw" / "workspace"),
            "label": spawn_params.get("label", f"orch-{request.source_task_id[:8]}"),
            "metadata": spawn_params.get("metadata", {}),
        }
        
        try:
            # 直接调用 Python sessions_spawn API（使用 subagent runner）
            # 注意：不使用 CLI 路径，因为 `openclaw sessions_spawn` 子命令不存在
            return self._call_via_python_api(call_params)
            
        except Exception as e:
            return False, str(e), None
    
    def _call_via_python_api(
        self,
        call_params: Dict[str, Any],
    ) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """
        **Wave 2 Cutover (2026-03-24)**: 通过 SubagentExecutor 调用真实 sessions_spawn。
        
        使用统一的 SubagentExecutor 执行引擎（Deer-Flow 借鉴线 Batch A）：
        - 统一 task_id / timeout / status / result handle
        - 工具权限隔离（tool allowlist）
        - 状态继承（内存缓存 + 文件持久化）
        - 返回 runId / childSessionKey / pid
        
        Args:
            call_params: {task, runtime, cwd, label, metadata}
        
        Returns:
            (success, error_message, api_response)
        """
        import uuid
        import time
        
        try:
            # 生成唯一 run label / task_id（如果未提供）
            label = call_params.get("label", f"orch-{uuid.uuid4().hex[:8]}")
            task = call_params.get("task", "")
            cwd = call_params.get("cwd") or str(Path.home() / ".openclaw" / "workspace")
            runtime = call_params.get("runtime", "subagent")
            metadata = call_params.get("metadata", {})
            
            # 验证 runtime（仅支持 subagent）
            if runtime != "subagent":
                return False, f"Unsupported runtime: {runtime}. Only 'subagent' is supported.", None
            
            # Wave 2 Cutover: 使用 SubagentExecutor 替代直接调用 runner 脚本
            # 创建 SubagentConfig
            subagent_config = SubagentConfig(
                label=label,
                runtime="subagent",
                timeout_seconds=metadata.get("timeout_seconds", 900),
                allowed_tools=metadata.get("allowed_tools"),
                disallowed_tools=metadata.get("disallowed_tools"),
                cwd=cwd,
                metadata={
                    **metadata,
                    "source": "sessions_spawn_bridge",
                    "wave": "wave2_cutover",
                },
            )
            
            # 创建 SubagentExecutor
            executor = SubagentExecutor(
                config=subagent_config,
                cwd=cwd,
            )
            
            # 生成 task_id（使用 request_id 映射或生成新的）
            # Wave 2 Cutover: 保持 task_id 格式一致（task_xxx）
            request_id = metadata.get("request_id")
            if request_id:
                task_id = f"task_{request_id.replace('req_', '')}"
            else:
                task_id = f"task_{uuid.uuid4().hex[:12]}"
            
            # 异步启动 subagent
            actual_task_id = executor.execute_async(task, task_id=task_id)
            
            # 等待短暂时间确保进程启动
            time.sleep(0.5)
            
            # 获取任务状态
            result = executor.get_result(actual_task_id)
            
            if not result:
                return False, "Failed to get subagent result after startup", None
            
            if result.status == "failed":
                return False, result.error or "Subagent failed to start", None
            
            # 成功启动
            api_response = {
                "status": "started",
                "childSessionKey": actual_task_id,  # Use task_id as childSessionKey
                "runId": actual_task_id,  # Use task_id as runId
                "label": label,
                "runtime": runtime,
                "cwd": cwd,
                "pid": result.pid,
                "message": "Wave 2 Cutover (2026-03-24): Real sessions_spawn via SubagentExecutor",
                "input": call_params,
                "subagent_config": subagent_config.to_dict(),
                "executor_version": result.metadata.get("executor_version"),
                "allowed_tools": result.metadata.get("allowed_tools"),
            }
            
            # Minimal lineage tracking (slice 1): 创建 parent-child lineage record
            # parent_id = dispatch_id (from metadata), child_id = actual_task_id
            dispatch_id = metadata.get("dispatch_id")
            if dispatch_id:
                try:
                    lineage_record: LineageRecord = create_lineage_record(
                        parent_id=dispatch_id,
                        child_id=actual_task_id,
                        batch_id=metadata.get("batch_id"),  # optional
                        relation_type="spawn",
                        metadata={
                            "source": "sessions_spawn_bridge",
                            "request_id": metadata.get("request_id"),
                            "spawn_id": metadata.get("spawn_id"),
                        },
                    )
                    # 将 lineage_id 附加到 api_response 中，供 execute() 方法使用
                    api_response["lineage_id"] = lineage_record.lineage_id
                except Exception as e:
                    # Lineage 创建失败不影响主流程（optional）
                    api_response["lineage_error"] = f"Failed to create lineage: {str(e)}"
            
            return True, None, api_response
            
        except Exception as e:
            return False, f"Unexpected error: {str(e)}", None
    
    def execute(
        self,
        request: SessionsSpawnRequest,
    ) -> SessionsSpawnAPIExecution:
        """
        Execute: 评估 policy -> (可选) 真实调用 API -> 写入 artifact。
        
        Args:
            request: Sessions spawn request
        
        Returns:
            SessionsSpawnAPIExecution（已写入文件）
        """
        # 1. Evaluate policy
        policy_eval = self.evaluate_policy(request)
        
        # 2. 决定 api_execution_status
        if not policy_eval["eligible"]:
            status: APIExecutionStatus = "blocked"
            reason = "; ".join(policy_eval["blocked_reasons"])
            api_result = None
        else:
            # 3. 执行 API call（或模拟）
            if policy_eval["should_execute_real"]:
                # 真实调用
                success, error, api_response = self._call_openclaw_sessions_spawn(request)
                
                if success:
                    status = "started"
                    reason = "API call successful"
                    api_result = APIExecutionResult(
                        api_execution_status="started",
                        api_execution_reason="API call successful",
                        api_execution_time=_iso_now(),
                        childSessionKey=api_response.get("childSessionKey") if api_response else None,
                        runId=api_response.get("runId") if api_response else None,
                        api_response=api_response,
                        linkage={
                            "request_id": request.request_id,
                            "task_id": request.source_task_id,
                            "dispatch_id": request.source_dispatch_id,
                            "spawn_id": request.source_spawn_id,
                        },
                        request_snapshot=request.to_dict(),
                    )
                else:
                    status = "failed"
                    reason = f"API call failed: {error}"
                    api_result = APIExecutionResult(
                        api_execution_status="failed",
                        api_execution_reason=reason,
                        api_execution_time=_iso_now(),
                        api_error=error,
                        linkage={
                            "request_id": request.request_id,
                            "task_id": request.source_task_id,
                        },
                        request_snapshot=request.to_dict(),
                    )
            else:
                # Safe mode / simulate only
                status = "pending"
                reason = "Safe mode enabled; execution recorded but not executed"
                api_result = APIExecutionResult(
                    api_execution_status="pending",
                    api_execution_reason=reason,
                    api_execution_time=_iso_now(),
                    api_response={
                        "status": "simulated",
                        "safe_mode": True,
                        "input": request.to_dict(),
                    },
                    linkage={
                        "request_id": request.request_id,
                        "task_id": request.source_task_id,
                        "dispatch_id": request.source_dispatch_id,
                        "spawn_id": request.source_spawn_id,
                        "receipt_id": request.source_receipt_id,
                    },
                    request_snapshot=request.to_dict(),
                )
        
        # 4. 生成 artifact
        execution_id = _generate_execution_id()
        dedupe_key = _generate_api_execution_dedupe_key(request.request_id)
        
        # Extract lineage_id from api_result if available
        lineage_id = None
        if api_result and api_result.api_response:
            lineage_id = api_result.api_response.get("lineage_id")
        
        artifact = SessionsSpawnAPIExecution(
            execution_id=execution_id,
            source_request_id=request.request_id,
            source_receipt_id=request.source_receipt_id,
            source_execution_id=request.source_execution_id,
            source_spawn_id=request.source_spawn_id,
            source_dispatch_id=request.source_dispatch_id,
            source_registration_id=request.source_registration_id,
            source_task_id=request.source_task_id,
            api_execution_status=status,
            api_execution_reason=reason,
            api_execution_time=_iso_now(),
            api_execution_result=api_result,
            dedupe_key=dedupe_key,
            policy_evaluation=policy_eval,
            metadata={
                "source_request_status": request.spawn_request_status,
                "scenario": request.metadata.get("scenario", ""),
                "owner": request.metadata.get("owner", ""),
                "safe_mode": self.policy.safe_mode,
                "should_execute_real": policy_eval.get("should_execute_real", False),
            },
            lineage_id=lineage_id,  # Lineage tracking (minimal slice)
        )
        
        # 5. Write artifact
        artifact.write()
        
        # 6. Record dedupe (include 'pending' for safe_mode scenarios)
        # P0-3 Batch 3: Also record 'pending' status for chain_to_execution support
        if status in ("started", "failed", "pending"):
            _record_api_execution_dedupe(request.request_id, execution_id)
        
        return artifact


def execute_sessions_spawn_api(
    request_id: str,
    policy: Optional[SessionsSpawnBridgePolicy] = None,
) -> SessionsSpawnAPIExecution:
    """
    Convenience function: 执行单个 request 的 API call。
    
    Args:
        request_id: Request ID
        policy: Bridge policy（可选）
    
    Returns:
        SessionsSpawnAPIExecution（已写入文件）
    
    Raises:
        ValueError: 如果 request 不存在
    """
    request = get_spawn_request(request_id)
    if not request:
        raise ValueError(f"Spawn request {request_id} not found")
    
    bridge = SessionsSpawnBridge(policy)
    return bridge.execute(request)


def list_api_executions(
    request_id: Optional[str] = None,
    task_id: Optional[str] = None,
    status: Optional[str] = None,
    scenario: Optional[str] = None,
    limit: int = 100,
) -> List[SessionsSpawnAPIExecution]:
    """列出 API executions"""
    _ensure_api_execution_dir()
    
    executions = []
    for exec_file in API_EXECUTION_DIR.glob("*.json"):
        try:
            with open(exec_file, "r") as f:
                data = json.load(f)
            artifact = SessionsSpawnAPIExecution.from_dict(data)
            
            # 过滤
            if request_id and artifact.source_request_id != request_id:
                continue
            if task_id and artifact.source_task_id != task_id:
                continue
            if status and artifact.api_execution_status != status:
                continue
            if scenario and artifact.metadata.get("scenario") != scenario:
                continue
            
            executions.append(artifact)
        except (json.JSONDecodeError, KeyError):
            pass
    
    executions.sort(key=lambda e: e.execution_id)
    return executions[:limit]


def get_api_execution(execution_id: str) -> Optional[SessionsSpawnAPIExecution]:
    """获取 API execution artifact"""
    exec_file = _api_execution_file(execution_id)
    if not exec_file.exists():
        return None
    
    with open(exec_file, "r") as f:
        data = json.load(f)
    
    return SessionsSpawnAPIExecution.from_dict(data)


def get_api_execution_by_request(request_id: str) -> Optional[SessionsSpawnAPIExecution]:
    """通过 request_id 获取 API execution"""
    execution_id = _get_execution_id_by_request(request_id)
    if not execution_id:
        # Try to find by scanning index
        index = _load_api_execution_index()
        execution_id = index.get(request_id)
        if not execution_id:
            return None
    return get_api_execution(execution_id)


def auto_trigger_real_execution(
    request_id: str,
    policy: Optional[SessionsSpawnBridgePolicy] = None,
) -> Tuple[bool, str, Optional[str]]:
    """
    V9: 自动触发真实 API execution。
    
    **P0-3 Batch 3 增强**: 支持 safe_mode 下的 pending 状态也视为成功触发。
    
    Args:
        request_id: Request ID
        policy: Bridge policy（可选）
    
    Returns:
        (triggered, reason, execution_id)
    """
    # 1. Get request
    request = get_spawn_request(request_id)
    if not request:
        return False, f"Request {request_id} not found", None
    
    # 2. Check if already executed
    existing = get_api_execution_by_request(request_id)
    if existing:
        return False, f"Already executed: {existing.execution_id}", existing.execution_id
    
    # 3. Check auto-trigger config
    config = _load_auto_trigger_real_exec_config()
    
    if not config.get("enabled", False):
        return False, "Auto-trigger real execution is disabled", None
    
    if config.get("require_manual_approval", True):
        return False, "Manual approval required", None
    
    # 4. Check scenario allowlist
    scenario = request.metadata.get("scenario", "generic")
    allowlist = config.get("allowlist", [])
    if allowlist and scenario not in allowlist:
        return False, f"Scenario '{scenario}' not in allowlist", None
    
    # 5. Construct policy from config (P0-3 Batch 6 fix)
    if policy is None:
        policy = SessionsSpawnBridgePolicy(
            safe_mode=config.get("safe_mode", True),
            allowlist=config.get("allowlist", ["trading"]),
            denylist=config.get("denylist", []),
            require_manual_approval=config.get("require_manual_approval", True),
            max_concurrent=config.get("max_concurrent_executions", 3),
        )
    
    # 6. Execute
    try:
        exec_artifact = execute_sessions_spawn_api(request_id, policy)
        
        # P0-3 Batch 3: Consider both 'started' and 'pending' as successful triggers
        # 'pending' means safe_mode is enabled (recorded but not actually executed)
        if exec_artifact.api_execution_status in ("started", "pending"):
            _record_auto_trigger(request_id, exec_artifact.execution_id)
            return True, f"Auto-triggered: {exec_artifact.execution_id} (status={exec_artifact.api_execution_status})", exec_artifact.execution_id
        else:
            return False, f"Execution status: {exec_artifact.api_execution_status}", None
            
    except Exception as e:
        return False, f"Execution failed: {str(e)}", None


def configure_auto_trigger_real_exec(
    enabled: Optional[bool] = None,
    allowlist: Optional[List[str]] = None,
    denylist: Optional[List[str]] = None,
    require_manual_approval: Optional[bool] = None,
    safe_mode: Optional[bool] = None,
) -> Dict[str, Any]:
    """配置 auto-trigger real execution"""
    config = _load_auto_trigger_real_exec_config()
    
    if enabled is not None:
        config["enabled"] = enabled
    if allowlist is not None:
        config["allowlist"] = allowlist
    if denylist is not None:
        config["denylist"] = denylist
    if require_manual_approval is not None:
        config["require_manual_approval"] = require_manual_approval
    if safe_mode is not None:
        config["safe_mode"] = safe_mode
    
    _save_auto_trigger_real_exec_config(config)
    return config


def get_auto_trigger_real_exec_status() -> Dict[str, Any]:
    """获取 auto-trigger real execution 状态"""
    config = _load_auto_trigger_real_exec_config()
    index = _load_api_execution_index()
    
    # 获取 pending requests
    pending = []
    requests = list_spawn_requests(request_status="prepared", limit=100)
    for req in requests:
        if not _is_already_executed(req.request_id):
            pending.append({
                "request_id": req.request_id,
                "scenario": req.metadata.get("scenario", "generic"),
                "task_id": req.source_task_id,
                "time": req.spawn_request_time,
            })
    
    return {
        "config": config,
        "executed_count": len(index),
        "pending_requests": pending[:20],
    }


# CLI 入口
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python sessions_spawn_bridge.py execute <request_id>")
        print("  python sessions_spawn_bridge.py list [--status <status>]")
        print("  python sessions_spawn_bridge.py get <execution_id>")
        print("  python sessions_spawn_bridge.py by-request <request_id>")
        print("  python sessions_spawn_bridge.py auto-trigger <request_id>")
        print("  python sessions_spawn_bridge.py auto-trigger-config [options]")
        print("  python sessions_spawn_bridge.py auto-trigger-status")
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == "execute":
        if len(sys.argv) < 3:
            print("Error: missing request_id")
            sys.exit(1)
        
        request_id = sys.argv[2]
        try:
            artifact = execute_sessions_spawn_api(request_id)
            print(json.dumps(artifact.to_dict(), indent=2))
            print(f"\nAPI execution written to: {_api_execution_file(artifact.execution_id)}")
        except ValueError as e:
            print(f"Error: {e}")
            sys.exit(1)
    
    elif cmd == "list":
        status = None
        if "--status" in sys.argv:
            idx = sys.argv.index("--status")
            if idx + 1 < len(sys.argv):
                status = sys.argv[idx + 1]
        
        executions = list_api_executions(status=status)
        print(json.dumps([e.to_dict() for e in executions], indent=2))
    
    elif cmd == "get":
        if len(sys.argv) < 3:
            print("Error: missing execution_id")
            sys.exit(1)
        
        execution_id = sys.argv[2]
        artifact = get_api_execution(execution_id)
        if artifact:
            print(json.dumps(artifact.to_dict(), indent=2))
        else:
            print(f"API execution {execution_id} not found")
            sys.exit(1)
    
    elif cmd == "by-request":
        if len(sys.argv) < 3:
            print("Error: missing request_id")
            sys.exit(1)
        
        request_id = sys.argv[2]
        artifact = get_api_execution_by_request(request_id)
        if artifact:
            print(json.dumps(artifact.to_dict(), indent=2))
        else:
            print(f"No API execution found for request {request_id}")
            sys.exit(1)
    
    elif cmd == "auto-trigger":
        if len(sys.argv) < 3:
            print("Error: missing request_id")
            sys.exit(1)
        
        request_id = sys.argv[2]
        triggered, reason, exec_id = auto_trigger_real_execution(request_id)
        print(json.dumps({
            "triggered": triggered,
            "reason": reason,
            "execution_id": exec_id,
        }, indent=2))
    
    elif cmd == "auto-trigger-config":
        enabled = None
        allowlist = None
        require_manual = None
        safe_mode = None
        
        if "--enable" in sys.argv:
            enabled = True
        if "--disable" in sys.argv:
            enabled = False
        if "--allowlist" in sys.argv:
            idx = sys.argv.index("--allowlist")
            if idx + 1 < len(sys.argv):
                allowlist = sys.argv[idx + 1].split(",")
        if "--no-manual-approval" in sys.argv:
            require_manual = False
        if "--no-safe-mode" in sys.argv:
            safe_mode = False
        
        config = configure_auto_trigger_real_exec(
            enabled=enabled,
            allowlist=allowlist,
            require_manual_approval=require_manual,
            safe_mode=safe_mode,
        )
        print("Auto-trigger real execution config:")
        print(json.dumps(config, indent=2))
    
    elif cmd == "auto-trigger-status":
        status = get_auto_trigger_real_exec_status()
        print(json.dumps(status, indent=2))
    
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
