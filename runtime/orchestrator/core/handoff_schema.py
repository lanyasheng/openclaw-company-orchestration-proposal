#!/usr/bin/env python3
"""
handoff_schema.py — Unified Planning → Execution Handoff Schema (v1)

目标：提供通用的 handoff schema，连接 planning artifact → task registration → execution。
减少不同场景各自拼任务定义，确保 handoff 语义一致。

核心概念：
- PlanningHandoff: 从 planning artifact (DispatchPlan) 提取的 handoff 数据
- RegistrationHandoff: 用于 task registration 的 handoff 数据
- ExecutionHandoff: 用于 execution dispatch 的 handoff 数据

这是通用 kernel，不绑定任何特定场景。

设计原则：
1. 最小通用 schema，不做大而全设计
2. 向后兼容，保留现有字段
3. 不把 trading 特有 planning 字段写死到通用层
4. helper/contract-first，避免多处散写 handoff 字段
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

__all__ = [
    "HandoffVersion",
    "PlanningHandoff",
    "RegistrationHandoff",
    "RegistrationReadiness",
    "ExecutionHandoff",
    "build_planning_handoff",
    "build_registration_handoff",
    "build_execution_handoff",
    "handoff_to_task_registration",
    "handoff_to_dispatch_spawn",
    "HANDOFF_SCHEMA_VERSION",
]

HANDOFF_SCHEMA_VERSION = "handoff_schema_v1"
HandoffVersion = Literal["handoff_schema_v1"]


@dataclass
class PlanningHandoff:
    """
    Planning Handoff — 从 planning artifact 提取的 handoff 数据。
    
    核心字段：
    - handoff_id: handoff 记录 ID
    - source_type: 来源类型 (dispatch_plan / completion_receipt / manual)
    - source_id: 来源 ID (dispatch_id / task_id / batch_id)
    - continuation_contract: 统一 continuation contract
    - scenario: 场景标识
    - adapter: 适配器标识
    - owner: 任务所有者
    - backend_preference: 后端偏好 (subagent / tmux / manual)
    - task_preview: 任务预览/描述
    - safety_gates: 安全门检查结果
    - metadata: 额外元数据
    
    这是从 planning 层到 registration/execution 层的统一接口。
    """
    handoff_id: str
    source_type: Literal["dispatch_plan", "completion_receipt", "manual"]
    source_id: str
    continuation_contract: Dict[str, Any]
    scenario: str
    adapter: str
    owner: str
    backend_preference: Literal["subagent", "tmux", "manual"] = "subagent"
    task_preview: str = ""
    safety_gates: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def validate(self) -> tuple[bool, List[str]]:
        """验证 handoff 是否符合规则"""
        errors: List[str] = []
        
        # 规则 1: handoff_id 不能为空
        if not self.handoff_id or not self.handoff_id.strip():
            errors.append("handoff_id is required")
        
        # 规则 2: source_id 不能为空
        if not self.source_id or not self.source_id.strip():
            errors.append("source_id is required")
        
        # 规则 3: continuation_contract 必须包含核心字段
        cc = self.continuation_contract
        if not cc.get("stopped_because"):
            errors.append("continuation_contract.stopped_because is required")
        if not cc.get("next_step"):
            errors.append("continuation_contract.next_step is required")
        if not cc.get("next_owner"):
            errors.append("continuation_contract.next_owner is required")
        
        # 规则 4: scenario 和 adapter 不能为空
        if not self.scenario or not self.scenario.strip():
            errors.append("scenario is required")
        if not self.adapter or not self.adapter.strip():
            errors.append("adapter is required")
        
        return len(errors) == 0, errors
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "handoff_version": HANDOFF_SCHEMA_VERSION,
            "handoff_id": self.handoff_id,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "continuation_contract": self.continuation_contract,
            "scenario": self.scenario,
            "adapter": self.adapter,
            "owner": self.owner,
            "backend_preference": self.backend_preference,
            "task_preview": self.task_preview,
            "safety_gates": self.safety_gates,
            "metadata": self.metadata,
            "created_at": self.metadata.get("created_at"),
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PlanningHandoff":
        return cls(
            handoff_id=data.get("handoff_id", ""),
            source_type=data.get("source_type", "manual"),
            source_id=data.get("source_id", ""),
            continuation_contract=data.get("continuation_contract", {}),
            scenario=data.get("scenario", ""),
            adapter=data.get("adapter", ""),
            owner=data.get("owner", "main"),
            backend_preference=data.get("backend_preference", "subagent"),
            task_preview=data.get("task_preview", ""),
            safety_gates=data.get("safety_gates", {}),
            metadata=data.get("metadata", {}),
        )


@dataclass
class RegistrationReadiness:
    """
    Registration Readiness — 注册就绪状态评估。
    
    核心字段：
    - eligible: 是否符合 auto-dispatch 资格
    - status: ready | not_ready | blocked
    - blockers: 阻塞原因列表
    - criteria: 评估标准列表
    - safety_gates_snapshot: 安全门快照
    
    P0-2 Batch 4: 明确 registration 与 readiness 的关系。
    """
    eligible: bool = False
    status: Literal["ready", "not_ready", "blocked"] = "not_ready"
    blockers: List[str] = field(default_factory=list)
    criteria: List[str] = field(default_factory=list)
    safety_gates_snapshot: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "eligible": self.eligible,
            "status": self.status,
            "blockers": self.blockers,
            "criteria": self.criteria,
            "safety_gates_snapshot": self.safety_gates_snapshot,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RegistrationReadiness":
        return cls(
            eligible=data.get("eligible", False),
            status=data.get("status", "not_ready"),
            blockers=data.get("blockers", []),
            criteria=data.get("criteria", []),
            safety_gates_snapshot=data.get("safety_gates_snapshot", {}),
        )


@dataclass
class RegistrationHandoff:
    """
    Registration Handoff — 用于 task registration 的 handoff 数据。
    
    核心字段：
    - handoff_id: 关联的 planning handoff ID
    - registration_id: 生成的 registration ID
    - task_id: 生成的 task ID
    - batch_id: 批次 ID
    - proposed_task: 提议的任务内容
    - source_closeout: 来源 closeout (可选)
    - truth_anchor: 真值锚点
    - registration_status: registered | skipped | blocked
    - ready_for_auto_dispatch: 是否准备好自动 dispatch
    - readiness: 注册就绪状态评估 (P0-2 Batch 4)
    - metadata: 额外元数据
    
    这是从 planning handoff 到 task registration 的桥梁。
    
    P0-2 Batch 4 增强：
    - 明确 registration 与 readiness / safety_gates / truth_anchor 的关系
    - readiness 字段提供可查询的就绪状态评估
    - truth_anchor 提供可追溯的来源 linkage
    """
    handoff_id: str
    registration_id: str
    task_id: str
    batch_id: Optional[str]
    proposed_task: Dict[str, Any]
    source_closeout: Optional[Dict[str, Any]] = None
    truth_anchor: Optional[Dict[str, Any]] = None
    registration_status: Literal["registered", "skipped", "blocked"] = "registered"
    ready_for_auto_dispatch: bool = False
    readiness: Optional[RegistrationReadiness] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "handoff_version": HANDOFF_SCHEMA_VERSION,
            "handoff_id": self.handoff_id,
            "registration_id": self.registration_id,
            "task_id": self.task_id,
            "batch_id": self.batch_id,
            "proposed_task": self.proposed_task,
            "source_closeout": self.source_closeout,
            "truth_anchor": self.truth_anchor,
            "registration_status": self.registration_status,
            "ready_for_auto_dispatch": self.ready_for_auto_dispatch,
            "readiness": self.readiness.to_dict() if self.readiness else None,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RegistrationHandoff":
        readiness = None
        if data.get("readiness"):
            readiness = RegistrationReadiness.from_dict(data["readiness"])
        
        return cls(
            handoff_id=data.get("handoff_id", ""),
            registration_id=data.get("registration_id", ""),
            task_id=data.get("task_id", ""),
            batch_id=data.get("batch_id"),
            proposed_task=data.get("proposed_task", {}),
            source_closeout=data.get("source_closeout"),
            truth_anchor=data.get("truth_anchor"),
            registration_status=data.get("registration_status", "registered"),
            ready_for_auto_dispatch=data.get("ready_for_auto_dispatch", False),
            readiness=readiness,
            metadata=data.get("metadata", {}),
        )


@dataclass
class ExecutionHandoff:
    """
    Execution Handoff — 用于 execution dispatch 的 handoff 数据。
    
    核心字段：
    - handoff_id: 关联的 planning handoff ID
    - dispatch_id: 生成的 dispatch ID
    - runtime: 运行时类型 (subagent / tmux)
    - task: 任务描述
    - workdir: 工作目录
    - timeout_seconds: 超时时间
    - continuation_context: continuation 上下文 (用于 subagent 唤醒)
    - metadata: 额外元数据
    
    这是从 planning handoff 到 execution 的桥梁。
    """
    handoff_id: str
    dispatch_id: str
    runtime: Literal["subagent", "tmux", "manual"]
    task: str
    workdir: Optional[str] = None
    timeout_seconds: int = 3600
    continuation_context: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "handoff_version": HANDOFF_SCHEMA_VERSION,
            "handoff_id": self.handoff_id,
            "dispatch_id": self.dispatch_id,
            "runtime": self.runtime,
            "task": self.task,
            "workdir": self.workdir,
            "timeout_seconds": self.timeout_seconds,
            "continuation_context": self.continuation_context,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExecutionHandoff":
        return cls(
            handoff_id=data.get("handoff_id", ""),
            dispatch_id=data.get("dispatch_id", ""),
            runtime=data.get("runtime", "subagent"),
            task=data.get("task", ""),
            workdir=data.get("workdir"),
            timeout_seconds=data.get("timeout_seconds", 3600),
            continuation_context=data.get("continuation_context"),
            metadata=data.get("metadata", {}),
        )


def _generate_id(prefix: str) -> str:
    """生成稳定 ID"""
    import uuid
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _iso_now() -> str:
    """返回当前 ISO-8601 时间戳"""
    return datetime.now().isoformat()


def build_planning_handoff(
    *,
    source_type: Literal["dispatch_plan", "completion_receipt", "manual"],
    source_id: str,
    continuation_contract: Dict[str, Any],
    scenario: str,
    adapter: str,
    owner: str,
    backend_preference: Literal["subagent", "tmux", "manual"] = "subagent",
    task_preview: str = "",
    safety_gates: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> PlanningHandoff:
    """
    构建 planning handoff。
    
    参数：
    - source_type: 来源类型
    - source_id: 来源 ID
    - continuation_contract: continuation contract (from DispatchPlan.continuation_contract)
    - scenario: 场景标识
    - adapter: 适配器标识
    - owner: 任务所有者
    - backend_preference: 后端偏好
    - task_preview: 任务预览
    - safety_gates: 安全门检查结果
    - metadata: 额外元数据
    
    返回：PlanningHandoff
    """
    full_metadata = metadata or {}
    full_metadata["created_at"] = _iso_now()
    
    handoff = PlanningHandoff(
        handoff_id=_generate_id("handoff"),
        source_type=source_type,
        source_id=source_id,
        continuation_contract=continuation_contract,
        scenario=scenario,
        adapter=adapter,
        owner=owner,
        backend_preference=backend_preference,
        task_preview=task_preview,
        safety_gates=safety_gates or {},
        metadata=full_metadata,
    )
    
    is_valid, errors = handoff.validate()
    if not is_valid:
        handoff.metadata["validation_warnings"] = errors
    
    return handoff


def _evaluate_registration_readiness(
    planning_handoff: PlanningHandoff,
    registration_status: str,
) -> RegistrationReadiness:
    """
    P0-2 Batch 4: 评估 registration readiness。
    
    基于 safety_gates 和 registration_status 生成可读的就绪状态评估。
    
    参数：
    - planning_handoff: planning handoff
    - registration_status: 注册状态
    
    返回：RegistrationReadiness
    """
    sg = planning_handoff.safety_gates
    blockers: List[str] = []
    criteria: List[str] = [
        "registration_status == 'registered'",
        "safety_gates.allow_auto_dispatch == True",
        "batch_has_timeout_tasks == False",
        "batch_has_failed_tasks == False",
        "packet_complete == True",
    ]
    
    # 检查 blocker
    if registration_status != "registered":
        if registration_status == "skipped":
            blockers.append(f"registration_status={registration_status}")
        elif registration_status == "blocked":
            blockers.append(f"registration_status={registration_status}")
    
    if sg.get("allow_auto_dispatch") is False:
        blockers.append("safety_gates.allow_auto_dispatch=False")
    
    if sg.get("batch_has_timeout_tasks"):
        blockers.append(f"batch_has_timeout_tasks={sg.get('batch_has_timeout_tasks')}")
    
    if sg.get("batch_has_failed_tasks"):
        blockers.append(f"batch_has_failed_tasks={sg.get('batch_has_failed_tasks')}")
    
    if sg.get("packet_complete") is False:
        blockers.append("packet_complete=False")
    
    eligible = len(blockers) == 0 and registration_status == "registered"
    status = "ready" if eligible else ("blocked" if blockers else "not_ready")
    
    return RegistrationReadiness(
        eligible=eligible,
        status=status,
        blockers=blockers,
        criteria=criteria,
        safety_gates_snapshot={
            "allow_auto_dispatch": sg.get("allow_auto_dispatch"),
            "batch_has_timeout_tasks": sg.get("batch_has_timeout_tasks"),
            "batch_has_failed_tasks": sg.get("batch_has_failed_tasks"),
            "packet_complete": sg.get("packet_complete"),
        },
    )


def build_registration_handoff(
    planning_handoff: PlanningHandoff,
    *,
    batch_id: Optional[str] = None,
    registration_status: Literal["registered", "skipped", "blocked"] = None,
    ready_for_auto_dispatch: Optional[bool] = None,
) -> RegistrationHandoff:
    """
    从 planning handoff 构建 registration handoff。
    
    参数：
    - planning_handoff: planning handoff
    - batch_id: 批次 ID
    - registration_status: 注册状态 (默认从 safety_gates 推导)
    - ready_for_auto_dispatch: 是否准备好自动 dispatch
    
    返回：RegistrationHandoff
    
    P0-2 Batch 4: 自动评估 readiness 状态，提供可查询的就绪评估。
    """
    # 生成 stable IDs
    registration_id = _generate_id("reg")
    task_id = _generate_id("task")
    
    # 从 planning handoff 提取信息构建 proposed_task
    cc = planning_handoff.continuation_contract
    proposed_task = {
        "task_type": "continuation",
        "title": f"Continuation: {cc.get('next_step', 'Next step')[:50]}",
        "description": cc.get("next_step", ""),
        "owner": planning_handoff.owner,
        "source": {
            "handoff_id": planning_handoff.handoff_id,
            "source_type": planning_handoff.source_type,
            "source_id": planning_handoff.source_id,
        },
        "context": {
            "adapter": planning_handoff.adapter,
            "scenario": planning_handoff.scenario,
            "stopped_because": cc.get("stopped_because", ""),
        },
        "continuation": {
            "stopped_because": cc.get("stopped_because", ""),
            "next_step": cc.get("next_step", ""),
            "next_owner": cc.get("next_owner", ""),
        },
    }
    
    # 构建 truth_anchor
    truth_anchor = {
        "anchor_type": "handoff_id",
        "anchor_value": planning_handoff.handoff_id,
        "metadata": {
            "source_type": planning_handoff.source_type,
            "source_id": planning_handoff.source_id,
            "adapter": planning_handoff.adapter,
            "scenario": planning_handoff.scenario,
        },
    }
    
    # 推导 registration_status
    if registration_status is None:
        sg = planning_handoff.safety_gates
        if sg.get("allow_auto_dispatch") is False:
            registration_status = "skipped"
        elif sg.get("batch_has_timeout_tasks") or sg.get("batch_has_failed_tasks"):
            registration_status = "blocked"
        else:
            registration_status = "registered"
    
    # 推导 ready_for_auto_dispatch
    if ready_for_auto_dispatch is None:
        ready_for_auto_dispatch = (
            registration_status == "registered" and
            planning_handoff.safety_gates.get("allow_auto_dispatch", False) is True
        )
    
    # P0-2 Batch 4: 评估 readiness
    readiness = _evaluate_registration_readiness(planning_handoff, registration_status)
    
    return RegistrationHandoff(
        handoff_id=planning_handoff.handoff_id,
        registration_id=registration_id,
        task_id=task_id,
        batch_id=batch_id,
        proposed_task=proposed_task,
        source_closeout=None,  # 可以从 planning_handoff 进一步提取
        truth_anchor=truth_anchor,
        registration_status=registration_status,
        ready_for_auto_dispatch=ready_for_auto_dispatch,
        readiness=readiness,
        metadata={
            "created_from": "planning_handoff",
            "created_at": _iso_now(),
        },
    )


def build_execution_handoff(
    planning_handoff: PlanningHandoff,
    *,
    dispatch_id: Optional[str] = None,
    runtime: Optional[Literal["subagent", "tmux", "manual"]] = None,
    timeout_seconds: int = 3600,
) -> ExecutionHandoff:
    """
    从 planning handoff 构建 execution handoff。
    
    参数：
    - planning_handoff: planning handoff
    - dispatch_id: dispatch ID (默认自动生成)
    - runtime: 运行时类型 (默认从 planning_handoff.backend_preference 推导)
    - timeout_seconds: 超时时间
    
    返回：ExecutionHandoff
    """
    # 推导 runtime
    if runtime is None:
        runtime = planning_handoff.backend_preference  # type: ignore
    
    # 生成 dispatch_id
    if dispatch_id is None:
        dispatch_id = _generate_id("dispatch")
    
    # 构建 continuation_context (用于 subagent 唤醒)
    continuation_context = {
        "handoff_id": planning_handoff.handoff_id,
        "source_type": planning_handoff.source_type,
        "source_id": planning_handoff.source_id,
        "continuation_contract": planning_handoff.continuation_contract,
    }
    
    return ExecutionHandoff(
        handoff_id=planning_handoff.handoff_id,
        dispatch_id=dispatch_id,
        runtime=runtime,
        task=planning_handoff.task_preview or planning_handoff.continuation_contract.get("next_step", ""),
        workdir=None,  # 可以从 metadata 进一步提取
        timeout_seconds=timeout_seconds,
        continuation_context=continuation_context,
        metadata={
            "created_from": "planning_handoff",
            "created_at": _iso_now(),
        },
    )


def handoff_to_task_registration(
    registration_handoff: RegistrationHandoff,
) -> Dict[str, Any]:
    """
    将 registration handoff 转换为 task_registration 模块可消费的格式。
    
    参数：
    - registration_handoff: registration handoff
    
    返回：register_task() 所需的参数字典
    """
    return {
        "proposed_task": registration_handoff.proposed_task,
        "source_closeout": registration_handoff.source_closeout,
        "registration_status": registration_handoff.registration_status,
        "registration_reason": f"Handoff from {registration_handoff.handoff_id}",
        "batch_id": registration_handoff.batch_id,
        "owner": registration_handoff.proposed_task.get("owner"),
        "ready_for_auto_dispatch": registration_handoff.ready_for_auto_dispatch,
        "metadata": {
            **registration_handoff.metadata,
            "handoff_id": registration_handoff.handoff_id,
            "truth_anchor": registration_handoff.truth_anchor,
        },
    }


def handoff_to_dispatch_spawn(
    execution_handoff: ExecutionHandoff,
    *,
    requester_session_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    将 execution handoff 转换为 sessions_spawn 所需的格式。
    
    参数：
    - execution_handoff: execution handoff
    - requester_session_key: 请求者 session key (用于 subagent 唤醒)
    
    返回：sessions_spawn() 所需的参数字典
    """
    task = execution_handoff.task
    
    # 构建 metadata，包含 continuation_context
    metadata = {
        **execution_handoff.metadata,
        "handoff_id": execution_handoff.handoff_id,
        "dispatch_id": execution_handoff.dispatch_id,
        "requester_session_key": requester_session_key,
    }
    
    # 如果有 continuation_context，添加到 metadata
    if execution_handoff.continuation_context:
        metadata["continuation_context"] = execution_handoff.continuation_context
    
    return {
        "runtime": execution_handoff.runtime,
        "task": task,
        "workdir": execution_handoff.workdir,
        "timeout_seconds": execution_handoff.timeout_seconds,
        "metadata": metadata,
    }
