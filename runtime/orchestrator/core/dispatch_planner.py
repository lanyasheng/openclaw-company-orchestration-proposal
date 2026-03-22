#!/usr/bin/env python3
"""
dispatch_planner.py — Dispatch Plan Generator

调度计划生成器，基于 decision 生成 dispatch plan。

核心功能：
- 基于 decision 生成 dispatch plan
- 支持 backend 选择、timeout policy
- 持久化 dispatch plan

这是通用 kernel，不绑定任何业务场景。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path
import json

__all__ = [
    "DispatchBackend",
    "TimeoutPolicy",
    "DispatchPlan",
    "DispatchPlanner",
    "DISPATCH_PLANNER_VERSION",
]

DISPATCH_PLANNER_VERSION = "dispatch_planner_v1"


class DispatchBackend(str, Enum):
    """调度后端类型"""
    SUBAGENT = "subagent"  # Subagent runtime
    TMUX = "tmux"  # Tmux observable session
    MANUAL = "manual"  # Manual execution


class DispatchStatus(str, Enum):
    """调度状态"""
    TRIGGERED = "triggered"  # 已触发
    SKIPPED = "skipped"  # 已跳过
    PENDING = "pending"  # 待处理
    EXECUTING = "executing"  # 执行中
    COMPLETED = "completed"  # 已完成
    FAILED = "failed"  # 失败


@dataclass
class TimeoutPolicy:
    """
    超时策略
    
    定义任务执行的超时配置。
    """
    backend: DispatchBackend
    timeout_total_seconds: int = 3600  # 总超时
    timeout_stall_seconds: int = 600  # 停滞超时
    stall_grace_seconds: int = 60  # 停滞宽限期
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "backend": self.backend.value,
            "timeout_total_seconds": self.timeout_total_seconds,
            "timeout_stall_seconds": self.timeout_stall_seconds,
            "stall_grace_seconds": self.stall_grace_seconds,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TimeoutPolicy":
        return cls(
            backend=DispatchBackend(data.get("backend", "subagent")),
            timeout_total_seconds=data.get("timeout_total_seconds", 3600),
            timeout_stall_seconds=data.get("timeout_stall_seconds", 600),
            stall_grace_seconds=data.get("stall_grace_seconds", 60),
        )


@dataclass
class SkipReason:
    """跳过原因"""
    code: str
    message: str
    
    def to_dict(self) -> Dict[str, Any]:
        return {"code": self.code, "message": self.message}


@dataclass
class BackendPlan:
    """
    后端执行计划
    
    定义如何在特定后端执行任务。
    """
    backend: DispatchBackend
    commands: Dict[str, str] = field(default_factory=dict)  # start/status/stop 命令
    workdir: Optional[str] = None
    observable_intermediate_state: bool = False
    notes: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "backend": self.backend.value,
            "commands": self.commands,
            "workdir": self.workdir,
            "observable_intermediate_state": self.observable_intermediate_state,
            "notes": self.notes,
        }


@dataclass
class DispatchPlan:
    """
    调度计划
    
    完整的调度计划，包含所有执行所需信息。
    """
    dispatch_id: str
    batch_id: str
    scenario: str
    adapter: str
    decision_id: str
    
    status: DispatchStatus = DispatchStatus.PENDING
    reason: str = ""
    
    # 执行配置
    backend: DispatchBackend = DispatchBackend.SUBAGENT
    timeout_policy: Optional[TimeoutPolicy] = None
    backend_plan: Optional[BackendPlan] = None
    
    # 跳过原因（如果 status=skipped）
    skip_reasons: List[SkipReason] = field(default_factory=list)
    
    # 延续计划
    continuation: Dict[str, Any] = field(default_factory=dict)
    
    # 编排契约
    orchestration_contract: Dict[str, Any] = field(default_factory=dict)
    
    # 安全门
    safety_gates: Dict[str, Any] = field(default_factory=dict)
    
    # 推荐执行
    recommended_spawn: Dict[str, Any] = field(default_factory=dict)
    
    # 父消息（用于通知）
    parent_message: Optional[str] = None
    
    # 元数据
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    artifacts: Dict[str, str] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "dispatch_id": self.dispatch_id,
            "batch_id": self.batch_id,
            "scenario": self.scenario,
            "adapter": self.adapter,
            "decision_id": self.decision_id,
            "status": self.status.value,
            "reason": self.reason,
            "backend": self.backend.value,
            "timeout_policy": self.timeout_policy.to_dict() if self.timeout_policy else None,
            "backend_plan": self.backend_plan.to_dict() if self.backend_plan else None,
            "skip_reasons": [sr.to_dict() for sr in self.skip_reasons],
            "continuation": self.continuation,
            "orchestration_contract": self.orchestration_contract,
            "safety_gates": self.safety_gates,
            "recommended_spawn": self.recommended_spawn,
            "parent_message": self.parent_message,
            "timestamp": self.timestamp,
            "artifacts": self.artifacts,
        }


class DispatchPlanner:
    """
    调度计划生成器
    
    基于 decision 和配置生成 dispatch plan。
    """
    
    def __init__(self, planner_id: str = "default"):
        self.planner_id = planner_id
        self.plans: Dict[str, DispatchPlan] = {}
        self.context: Dict[str, Any] = {}
        self.created_at = datetime.now().isoformat()
        
        # 默认超时策略
        self._default_timeout_policies = {
            DispatchBackend.SUBAGENT: TimeoutPolicy(
                backend=DispatchBackend.SUBAGENT,
                timeout_total_seconds=3600,
                timeout_stall_seconds=600,
                stall_grace_seconds=60,
            ),
            DispatchBackend.TMUX: TimeoutPolicy(
                backend=DispatchBackend.TMUX,
                timeout_total_seconds=3600,
                timeout_stall_seconds=600,
                stall_grace_seconds=60,
            ),
            DispatchBackend.MANUAL: TimeoutPolicy(
                backend=DispatchBackend.MANUAL,
                timeout_total_seconds=7200,
                timeout_stall_seconds=1800,
                stall_grace_seconds=120,
            ),
        }
    
    def set_timeout_policy(self, backend: DispatchBackend, policy: TimeoutPolicy):
        """设置后端超时策略"""
        self._default_timeout_policies[backend] = policy
    
    def get_timeout_policy(self, backend: DispatchBackend) -> TimeoutPolicy:
        """获取后端超时策略"""
        return self._default_timeout_policies.get(
            backend,
            self._default_timeout_policies[DispatchBackend.SUBAGENT],
        )
    
    def create_plan(
        self,
        dispatch_id: str,
        batch_id: str,
        scenario: str,
        adapter: str,
        decision_id: str,
        decision: Dict[str, Any],
        continuation: Dict[str, Any],
        backend: DispatchBackend = DispatchBackend.SUBAGENT,
        allow_auto_dispatch: bool = False,
        auto_dispatch_source: str = "default_deny",
        requester_session_key: Optional[str] = None,
        validation: Optional[Dict[str, Any]] = None,
        analysis: Optional[Dict[str, Any]] = None,
        readiness: Optional[Dict[str, Any]] = None,
        roundtable: Optional[Dict[str, Any]] = None,
        packet: Optional[Dict[str, Any]] = None,
    ) -> DispatchPlan:
        """
        创建调度计划
        
        Args:
            dispatch_id: 调度 ID
            batch_id: 批次 ID
            scenario: 场景
            adapter: 适配器
            decision_id: Decision ID
            decision: Decision 数据
            continuation: 延续计划
            backend: 执行后端
            allow_auto_dispatch: 是否允许自动 dispatch
            auto_dispatch_source: auto-dispatch 来源
            requester_session_key: 请求者 session key
            validation: packet 验证结果
            analysis: batch 分析结果
            readiness: auto-dispatch 就绪状态
            roundtable: roundtable 数据
            packet: packet 数据
        
        Returns:
            DispatchPlan: 创建的调度计划
        """
        # 获取超时策略
        timeout_policy = self.get_timeout_policy(backend)
        
        # 构建后端计划
        backend_plan = self._build_backend_plan(
            backend=backend,
            dispatch_id=dispatch_id,
            batch_id=batch_id,
            scenario=scenario,
            adapter=adapter,
            task_preview=continuation.get("task_preview", ""),
        )
        
        # 评估是否应该跳过
        skip_reasons = self._evaluate_skip_conditions(
            allow_auto_dispatch=allow_auto_dispatch,
            auto_dispatch_source=auto_dispatch_source,
            validation=validation,
            analysis=analysis,
            decision=decision,
            backend=backend,
            requester_session_key=requester_session_key,
            readiness=readiness,
            roundtable=roundtable,
            packet=packet,
        )
        
        # 确定状态
        status = DispatchStatus.SKIPPED if skip_reasons else DispatchStatus.TRIGGERED
        reason = "; ".join(sr.message for sr in skip_reasons) if skip_reasons else (
            f"Decision {decision.get('action', 'unknown')} can continue via backend={backend.value}"
        )
        
        # 构建推荐执行
        recommended_spawn = self._build_recommended_spawn(
            backend=backend,
            continuation=continuation,
            roundtable=roundtable,
            decision=decision,
            dispatch_id=dispatch_id,
            dispatch_path=f"/tmp/dispatch_{dispatch_id}.json",
        )
        
        # 构建父消息
        parent_message = self._build_parent_message(
            adapter=adapter,
            scenario=scenario,
            batch_id=batch_id,
            decision_action=decision.get("action", "unknown"),
            backend=backend,
            dispatch_path=f"/tmp/dispatch_{dispatch_id}.json",
            backend_plan=backend_plan,
            status=status,
        )
        
        # 创建计划
        plan = DispatchPlan(
            dispatch_id=dispatch_id,
            batch_id=batch_id,
            scenario=scenario,
            adapter=adapter,
            decision_id=decision_id,
            status=status,
            reason=reason,
            backend=backend,
            timeout_policy=timeout_policy,
            backend_plan=backend_plan,
            skip_reasons=skip_reasons,
            continuation=continuation,
            recommended_spawn=recommended_spawn,
            parent_message=parent_message,
        )
        
        self.plans[dispatch_id] = plan
        return plan
    
    def _build_backend_plan(
        self,
        backend: DispatchBackend,
        dispatch_id: str,
        batch_id: str,
        scenario: str,
        adapter: str,
        task_preview: str,
    ) -> BackendPlan:
        """构建后端执行计划"""
        if backend == DispatchBackend.SUBAGENT:
            return BackendPlan(
                backend=backend,
                commands={
                    "start": f'python3 scripts/orchestrator_dispatch_bridge.py start --dispatch {dispatch_id}',
                    "status": f'python3 scripts/orchestrator_dispatch_bridge.py status --dispatch {dispatch_id}',
                },
                observable_intermediate_state=False,
                notes=[
                    "Subagent runtime execution",
                    "No intermediate state observation",
                    "Completion reported via callback",
                ],
            )
        
        elif backend == DispatchBackend.TMUX:
            return BackendPlan(
                backend=backend,
                commands={
                    "start": f'python3 scripts/orchestrator_dispatch_bridge.py start --dispatch {dispatch_id} --backend tmux',
                    "status": f'python3 scripts/orchestrator_dispatch_bridge.py status --dispatch {dispatch_id}',
                    "stop": f'python3 scripts/orchestrator_dispatch_bridge.py stop --dispatch {dispatch_id}',
                },
                observable_intermediate_state=True,
                notes=[
                    "Tmux observable session",
                    "Intermediate state can be monitored",
                    "Backend terminal is diagnostic only",
                ],
            )
        
        else:  # MANUAL
            return BackendPlan(
                backend=backend,
                commands={},
                observable_intermediate_state=False,
                notes=[
                    "Manual execution required",
                    "Follow the recommended_spawn task preview",
                ],
            )
    
    def _evaluate_skip_conditions(
        self,
        allow_auto_dispatch: bool,
        auto_dispatch_source: str,
        validation: Optional[Dict[str, Any]],
        analysis: Optional[Dict[str, Any]],
        decision: Dict[str, Any],
        backend: DispatchBackend,
        requester_session_key: Optional[str],
        readiness: Optional[Dict[str, Any]],
        roundtable: Optional[Dict[str, Any]],
        packet: Optional[Dict[str, Any]],
    ) -> List[SkipReason]:
        """评估跳过条件"""
        skip_reasons = []
        
        def skip(code: str, message: str):
            skip_reasons.append(SkipReason(code=code, message=message))
        
        # 检查 explicit false
        if not allow_auto_dispatch:
            if auto_dispatch_source == "explicit":
                skip(
                    "auto_dispatch_explicitly_disabled",
                    "allow_auto_dispatch was explicitly set to false",
                )
            else:
                skip(
                    "trading_default_deny_manual_review",
                    "Manual confirmation is required before continuation",
                )
        
        # 检查 packet 完整性
        if validation and not validation.get("complete"):
            skip(
                "phase1_packet_incomplete",
                "Phase1 packet or roundtable closure is incomplete",
            )
        
        # 检查 timeout 任务
        analysis = analysis or {}
        timeout_count = int(analysis.get("timeout") or 0)
        if timeout_count > 0:
            skip(
                "batch_has_timeout_tasks",
                f"Batch has {timeout_count} timeout task(s)",
            )
        
        # 检查 failed 任务
        failed_count = int(analysis.get("failed") or 0)
        if failed_count > 0:
            skip(
                "batch_has_failed_tasks",
                f"Batch has {failed_count} failed task(s)",
            )
        
        # 检查 decision action
        decision_action = decision.get("action", "")
        if decision_action not in {"proceed", "retry"}:
            skip(
                "decision_not_auto_dispatchable",
                f"Decision {decision_action} is not auto-dispatchable",
            )
        
        # 检查 requester_session_key（对于 subagent backend）
        if backend == DispatchBackend.SUBAGENT and allow_auto_dispatch and not skip_reasons:
            if not requester_session_key:
                skip(
                    "missing_requester_session_key",
                    "Missing requester_session_key for runtime wake-up",
                )
        
        return skip_reasons
    
    def _build_recommended_spawn(
        self,
        backend: DispatchBackend,
        continuation: Dict[str, Any],
        roundtable: Optional[Dict[str, Any]],
        decision: Dict[str, Any],
        dispatch_id: str,
        dispatch_path: str,
    ) -> Dict[str, Any]:
        """构建推荐执行配置"""
        task_preview = (
            continuation.get("task_preview") or
            (roundtable.get("next_step") if roundtable else "") or
            decision.get("reason", "")
        )
        
        return {
            "runtime": "subagent" if backend == DispatchBackend.SUBAGENT else "tmux",
            "task_preview": task_preview,
            "dispatch_id": dispatch_id,
            "dispatch_path": dispatch_path,
        }
    
    def _build_parent_message(
        self,
        adapter: str,
        scenario: str,
        batch_id: str,
        decision_action: str,
        backend: DispatchBackend,
        dispatch_path: str,
        backend_plan: BackendPlan,
        status: DispatchStatus,
    ) -> str:
        """构建父消息"""
        if status == DispatchStatus.SKIPPED:
            return (
                f"⏭️ SKIP adapter={adapter} scenario={scenario} batch={batch_id} "
                f"decision={decision_action} backend={backend.value}\n"
                f"Read dispatch plan: {dispatch_path}\n"
                "Manual confirmation required before continuation."
            )
        
        if backend == DispatchBackend.SUBAGENT:
            return (
                f"🔁 AUTO_DISPATCH_REQUEST adapter={adapter} scenario={scenario} "
                f"batch={batch_id} decision={decision_action} backend=subagent\n"
                f"Read dispatch plan: {dispatch_path}\n"
                'Execute exactly one sessions_spawn(runtime="subagent") using recommended_spawn from that file.\n'
                "Do not fan out further in this turn; this is a single-step continuation."
            )
        else:
            start_cmd = backend_plan.commands.get("start", "N/A")
            status_cmd = backend_plan.commands.get("status", "N/A")
            return (
                f"🔁 AUTO_DISPATCH_REQUEST adapter={adapter} scenario={scenario} "
                f"batch={batch_id} decision={decision_action} backend=tmux\n"
                f"Read dispatch plan: {dispatch_path}\n"
                f"Start observable tmux continuation with: {start_cmd}\n"
                f"Check live status with: {status_cmd}\n"
                "tmux STATUS/completion report are diagnostic only; roundtable advances only after the canonical callback is bridged.\n"
                "Do not fan out further in this turn; this is a single-step continuation."
            )
    
    def get_plan(self, dispatch_id: str) -> Optional[DispatchPlan]:
        """获取调度计划"""
        return self.plans.get(dispatch_id)
    
    def update_status(
        self,
        dispatch_id: str,
        status: DispatchStatus,
        reason: Optional[str] = None,
    ) -> bool:
        """更新调度计划状态"""
        plan = self.get_plan(dispatch_id)
        if not plan:
            return False
        
        plan.status = status
        if reason:
            plan.reason = reason
        
        return True
    
    def set_context(self, key: str, value: Any):
        """设置上下文"""
        self.context[key] = value
    
    def get_context(self, key: str, default: Any = None) -> Any:
        """获取上下文"""
        return self.context.get(key, default)
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化规划器状态"""
        return {
            "planner_id": self.planner_id,
            "created_at": self.created_at,
            "plans": {did: p.to_dict() for did, p in self.plans.items()},
            "context": self.context,
        }
    
    def save(self, path: Path):
        """保存状态到文件"""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".tmp")
        with open(tmp_path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
        tmp_path.replace(path)
    
    @classmethod
    def load(cls, path: Path) -> "DispatchPlanner":
        """从文件加载状态"""
        with open(path, "r") as f:
            data = json.load(f)
        
        planner = cls(planner_id=data.get("planner_id", "default"))
        planner.created_at = data.get("created_at", datetime.now().isoformat())
        planner.context = data.get("context", {})
        
        # 加载计划
        for dispatch_id, plan_data in data.get("plans", {}).items():
            plan = DispatchPlan(
                dispatch_id=plan_data["dispatch_id"],
                batch_id=plan_data["batch_id"],
                scenario=plan_data["scenario"],
                adapter=plan_data["adapter"],
                decision_id=plan_data["decision_id"],
                status=DispatchStatus(plan_data["status"]),
                reason=plan_data.get("reason", ""),
                backend=DispatchBackend(plan_data["backend"]),
                continuation=plan_data.get("continuation", {}),
                timestamp=plan_data.get("timestamp", datetime.now().isoformat()),
            )
            
            if plan_data.get("timeout_policy"):
                plan.timeout_policy = TimeoutPolicy.from_dict(plan_data["timeout_policy"])
            
            plan.skip_reasons = [
                SkipReason(code=sr["code"], message=sr["message"])
                for sr in plan_data.get("skip_reasons", [])
            ]
            
            planner.plans[dispatch_id] = plan
        
        return planner
