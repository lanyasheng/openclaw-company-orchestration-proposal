#!/usr/bin/env python3
"""
phase_engine.py — Universal Phase State Machine

核心通用 phase 状态机，不绑定任何业务场景。

Phase 生命周期：
  pending → running → completed
                    ↓
              failed/blocked

支持：
- Phase 定义与状态转换
- Fan-out/Fan-in 控制
- Quality Gate 抽象
- Callback 路由

这是通用 kernel，trading/channel 等场景通过适配器使用。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Callable, Set
from pathlib import Path
import json

from core.types import FanOutMode, FanInMode, GateResult  # noqa: F811

__all__ = [
    "PhaseState",
    "PhaseTransition",
    "Phase",
    "PhaseEngine",
    "QualityGate",
    "GateResult",
    "FanOutMode",
    "FanInMode",
    "CallbackEvent",
    "CallbackRouter",
    "PHASE_ENGINE_VERSION",
]

PHASE_ENGINE_VERSION = "phase_engine_v1"


class PhaseState(str, Enum):
    """Phase 状态定义"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class PhaseTransition(str, Enum):
    """允许的状態转换"""
    START = "start"  # pending → running
    COMPLETE = "complete"  # running → completed
    FAIL = "fail"  # running → failed
    BLOCK = "block"  # running → blocked
    CANCEL = "cancel"  # any → cancelled
    RETRY = "retry"  # failed/blocked → pending
    UNBLOCK = "unblock"  # blocked → pending


# 状态转换规则：(from_state, transition) → to_state
TRANSITION_RULES: Dict[tuple[PhaseState, PhaseTransition], PhaseState] = {
    (PhaseState.PENDING, PhaseTransition.START): PhaseState.RUNNING,
    (PhaseState.RUNNING, PhaseTransition.COMPLETE): PhaseState.COMPLETED,
    (PhaseState.RUNNING, PhaseTransition.FAIL): PhaseState.FAILED,
    (PhaseState.RUNNING, PhaseTransition.BLOCK): PhaseState.BLOCKED,
    (PhaseState.FAILED, PhaseTransition.RETRY): PhaseState.PENDING,
    (PhaseState.BLOCKED, PhaseTransition.RETRY): PhaseState.PENDING,
    (PhaseState.BLOCKED, PhaseTransition.UNBLOCK): PhaseState.PENDING,
}

# 所有状态都可以取消
for state in PhaseState:
    TRANSITION_RULES[(state, PhaseTransition.CANCEL)] = PhaseState.CANCELLED


@dataclass
class QualityGate:
    """
    质量门抽象
    
    用于在 phase 转换前进行检查，确保满足继续执行的条件。
    """
    name: str
    checks: List[Callable[[Dict[str, Any]], GateResult]] = field(default_factory=list)
    required: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def evaluate(self, context: Dict[str, Any]) -> GateResult:
        """
        执行所有检查，返回聚合结果
        
        Args:
            context: 检查上下文（包含 phase 状态、artifact 信息等）
        
        Returns:
            GateResult: 聚合检查结果
        """
        all_checks = []
        all_blockers = []
        all_warnings = []
        any_failed = False
        
        for check_fn in self.checks:
            try:
                result = check_fn(context)
                all_checks.append({
                    "check": check_fn.__name__,
                    "passed": result.passed,
                    "details": result.to_dict() if hasattr(result, 'to_dict') else result,
                })
                if not result.passed:
                    any_failed = True
                    all_blockers.extend(result.blockers)
                all_warnings.extend(result.warnings)
            except Exception as e:
                all_checks.append({
                    "check": check_fn.__name__,
                    "passed": False,
                    "error": str(e),
                })
                any_failed = True
                all_blockers.append(f"Check {check_fn.__name__} failed: {e}")
        
        return GateResult(
            passed=not any_failed or not self.required,
            gate_name=self.name,
            checks=all_checks,
            blockers=all_blockers,
            warnings=all_warnings,
            metadata=self.metadata,
        )


@dataclass
class CallbackEvent:
    """回调事件"""
    event_type: str
    payload: Dict[str, Any]
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    source: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": self.event_type,
            "payload": self.payload,
            "timestamp": self.timestamp,
            "source": self.source,
        }


class CallbackRouter:
    """
    回调路由器
    
    注册回调处理器，在 phase 状态变化时触发。
    """
    
    def __init__(self):
        self._handlers: Dict[str, List[Callable[[CallbackEvent], None]]] = {}
        self._event_log: List[CallbackEvent] = []
    
    def register(self, event_type: str, handler: Callable[[CallbackEvent], None]):
        """注册回调处理器"""
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)
    
    def unregister(self, event_type: str, handler: Callable[[CallbackEvent], None]):
        """注销回调处理器"""
        if event_type in self._handlers:
            self._handlers[event_type] = [
                h for h in self._handlers[event_type] if h != handler
            ]
    
    def emit(self, event: CallbackEvent):
        """触发回调"""
        self._event_log.append(event)
        handlers = self._handlers.get(event.event_type, [])
        for handler in handlers:
            try:
                handler(event)
            except Exception as e:
                # 回调失败不影响主流程
                import logging
                logging.getLogger(__name__).warning("Callback handler failed: %s", e)
    
    def get_event_log(self, event_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取事件日志"""
        events = self._event_log
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        return [e.to_dict() for e in events]
    
    def clear_log(self):
        """清空事件日志"""
        self._event_log = []


@dataclass
class Phase:
    """
    Phase 定义
    
    表示一个可执行的工作单元，有明确的状态和生命周期。
    """
    phase_id: str
    name: str
    state: PhaseState = PhaseState.PENDING
    description: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # 执行配置
    fan_out_mode: FanOutMode = FanOutMode.SEQUENTIAL
    fan_in_mode: FanInMode = FanInMode.ALL_SUCCESS
    batch_size: int = 1  # 用于 batched fan-out
    timeout_seconds: int = 3600
    max_retries: int = 3
    
    # 状态追踪
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    retry_count: int = 0
    error_message: Optional[str] = None
    
    # 子任务（用于 fan-out）
    child_phases: List[str] = field(default_factory=list)
    parent_phase: Optional[str] = None
    
    # 质量门
    gates: List[QualityGate] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "phase_id": self.phase_id,
            "name": self.name,
            "state": self.state.value,
            "description": self.description,
            "metadata": self.metadata,
            "fan_out_mode": self.fan_out_mode.value,
            "fan_in_mode": self.fan_in_mode.value,
            "batch_size": self.batch_size,
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "retry_count": self.retry_count,
            "error_message": self.error_message,
            "child_phases": self.child_phases,
            "parent_phase": self.parent_phase,
            "gates": [{"name": g.name, "required": g.required} for g in self.gates],
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Phase":
        return cls(
            phase_id=data.get("phase_id", ""),
            name=data.get("name", ""),
            state=PhaseState(data.get("state", "pending")),
            description=data.get("description", ""),
            metadata=data.get("metadata", {}),
            fan_out_mode=FanOutMode(data.get("fan_out_mode", "sequential")),
            fan_in_mode=FanInMode(data.get("fan_in_mode", "all_success")),
            batch_size=data.get("batch_size", 1),
            timeout_seconds=data.get("timeout_seconds", 3600),
            max_retries=data.get("max_retries", 3),
            created_at=data.get("created_at", datetime.now().isoformat()),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            retry_count=data.get("retry_count", 0),
            error_message=data.get("error_message"),
            child_phases=data.get("child_phases", []),
            parent_phase=data.get("parent_phase"),
        )
    
    def can_transition(self, transition: PhaseTransition) -> bool:
        """检查是否可以进行某个状态转换"""
        return (self.state, transition) in TRANSITION_RULES
    
    def apply_transition(self, transition: PhaseTransition) -> PhaseState:
        """
        应用状态转换
        
        Returns:
            新状态
        
        Raises:
            ValueError: 如果转换不允许
        """
        key = (self.state, transition)
        if key not in TRANSITION_RULES:
            raise ValueError(
                f"Invalid transition {transition} from state {self.state}"
            )
        
        new_state = TRANSITION_RULES[key]
        self.state = new_state
        
        # 更新时间戳
        now = datetime.now().isoformat()
        if transition == PhaseTransition.START:
            self.started_at = now
        elif transition in (
            PhaseTransition.COMPLETE,
            PhaseTransition.FAIL,
            PhaseTransition.BLOCK,
            PhaseTransition.CANCEL,
        ):
            self.completed_at = now
        elif transition == PhaseTransition.RETRY:
            self.retry_count += 1
            self.started_at = None
            self.completed_at = None
            self.error_message = None
        
        return new_state


class PhaseEngine:
    """
    通用 Phase 状态机引擎
    
    管理多个 phase 的生命周期，支持 fan-out/fan-in、质量门、回调等。
    """
    
    def __init__(self, engine_id: str = "default"):
        self.engine_id = engine_id
        self.phases: Dict[str, Phase] = {}
        self.callback_router = CallbackRouter()
        self.context: Dict[str, Any] = {}
        self.created_at = datetime.now().isoformat()
    
    def register_phase(self, phase: Phase):
        """注册一个 phase"""
        self.phases[phase.phase_id] = phase
    
    def get_phase(self, phase_id: str) -> Optional[Phase]:
        """获取 phase"""
        return self.phases.get(phase_id)
    
    def list_phases(
        self,
        state: Optional[PhaseState] = None,
        parent_phase: Optional[str] = None,
    ) -> List[Phase]:
        """列出 phase"""
        phases = list(self.phases.values())
        if state:
            phases = [p for p in phases if p.state == state]
        if parent_phase:
            phases = [p for p in phases if p.parent_phase == parent_phase]
        return phases
    
    def transition_phase(
        self,
        phase_id: str,
        transition: PhaseTransition,
        error_message: Optional[str] = None,
    ) -> PhaseState:
        """
        转换 phase 状态
        
        Args:
            phase_id: Phase ID
            transition: 转换类型
            error_message: 错误信息（用于 fail/block）
        
        Returns:
            新状态
        
        Raises:
            KeyError: Phase 不存在
            ValueError: 转换不允许
        """
        phase = self.get_phase(phase_id)
        if not phase:
            raise KeyError(f"Phase {phase_id} not found")
        
        # 检查质量门（仅对 start/complete 转换）
        if transition in (PhaseTransition.START, PhaseTransition.COMPLETE):
            for gate in phase.gates:
                result = gate.evaluate(self.context)
                if not result.passed:
                    if gate.required:
                        raise ValueError(
                            f"Quality gate '{gate.name}' failed: {result.blockers}"
                        )
        
        # 应用转换
        new_state = phase.apply_transition(transition)
        
        if error_message:
            phase.error_message = error_message
        
        # 触发回调
        self.callback_router.emit(CallbackEvent(
            event_type="phase_transition",
            payload={
                "phase_id": phase_id,
                "from_state": phase.state,
                "to_state": new_state,
                "transition": transition.value,
            },
            source=self.engine_id,
        ))
        
        return new_state
    
    def start_phase(self, phase_id: str) -> PhaseState:
        """启动 phase"""
        return self.transition_phase(phase_id, PhaseTransition.START)
    
    def complete_phase(
        self,
        phase_id: str,
        result: Optional[Dict[str, Any]] = None,
    ) -> PhaseState:
        """完成 phase"""
        if result:
            phase = self.get_phase(phase_id)
            if phase:
                phase.metadata["result"] = result
        return self.transition_phase(phase_id, PhaseTransition.COMPLETE)
    
    def fail_phase(
        self,
        phase_id: str,
        error: str,
    ) -> PhaseState:
        """标记 phase 失败"""
        return self.transition_phase(
            phase_id,
            PhaseTransition.FAIL,
            error_message=error,
        )
    
    def block_phase(
        self,
        phase_id: str,
        reason: str,
    ) -> PhaseState:
        """标记 phase 阻塞"""
        return self.transition_phase(
            phase_id,
            PhaseTransition.BLOCK,
            error_message=reason,
        )
    
    def retry_phase(self, phase_id: str) -> PhaseState:
        """重试 phase"""
        return self.transition_phase(phase_id, PhaseTransition.RETRY)
    
    def cancel_phase(self, phase_id: str) -> PhaseState:
        """取消 phase"""
        return self.transition_phase(phase_id, PhaseTransition.CANCEL)
    
    def add_quality_gate(
        self,
        phase_id: str,
        gate: QualityGate,
    ):
        """为 phase 添加质量门"""
        phase = self.get_phase(phase_id)
        if not phase:
            raise KeyError(f"Phase {phase_id} not found")
        phase.gates.append(gate)
    
    def set_context(self, key: str, value: Any):
        """设置全局上下文"""
        self.context[key] = value
    
    def get_context(self, key: str, default: Any = None) -> Any:
        """获取全局上下文"""
        return self.context.get(key, default)
    
    def create_fan_out(
        self,
        parent_phase_id: str,
        child_phases: List[Phase],
        mode: FanOutMode = FanOutMode.SEQUENTIAL,
    ):
        """
        创建 fan-out 结构
        
        Args:
            parent_phase_id: 父 phase ID
            child_phases: 子 phase 列表
            mode: fan-out 模式
        """
        parent = self.get_phase(parent_phase_id)
        if not parent:
            raise KeyError(f"Parent phase {parent_phase_id} not found")
        
        parent.fan_out_mode = mode
        parent.child_phases = [p.phase_id for p in child_phases]
        
        for child in child_phases:
            child.parent_phase = parent_phase_id
            self.register_phase(child)
    
    def evaluate_fan_in(self, parent_phase_id: str) -> GateResult:
        """
        评估 fan-in 条件是否满足
        
        Args:
            parent_phase_id: 父 phase ID
        
        Returns:
            GateResult: fan-in 检查结果
        """
        parent = self.get_phase(parent_phase_id)
        if not parent:
            raise KeyError(f"Parent phase {parent_phase_id} not found")
        
        child_phases = [
            self.get_phase(pid) for pid in parent.child_phases
        ]
        child_phases = [p for p in child_phases if p]
        
        if not child_phases:
            return GateResult(
                passed=True,
                gate_name="fan_in",
                checks=[{"message": "No child phases"}],
            )
        
        completed = [p for p in child_phases if p.state == PhaseState.COMPLETED]
        failed = [p for p in child_phases if p.state == PhaseState.FAILED]
        
        checks = [
            {"phase_id": p.phase_id, "state": p.state.value}
            for p in child_phases
        ]
        
        passed = False
        blockers = []
        
        if parent.fan_in_mode == FanInMode.ALL_SUCCESS:
            passed = len(completed) == len(child_phases)
            if not passed:
                blockers.append(
                    f"Waiting for {len(child_phases) - len(completed)} child phases to complete"
                )
        elif parent.fan_in_mode == FanInMode.ANY_SUCCESS:
            passed = len(completed) > 0
            if not passed:
                blockers.append("No child phase has completed successfully")
        elif parent.fan_in_mode == FanInMode.MAJORITY:
            passed = len(completed) > len(child_phases) / 2
            if not passed:
                blockers.append("Majority of child phases have not completed")
        
        return GateResult(
            passed=passed,
            gate_name="fan_in",
            checks=checks,
            blockers=blockers,
            metadata={
                "fan_in_mode": parent.fan_in_mode.value,
                "total": len(child_phases),
                "completed": len(completed),
                "failed": len(failed),
            },
        )
    
    def get_phase_summary(self, phase_id: str) -> Dict[str, Any]:
        """获取 phase 摘要"""
        phase = self.get_phase(phase_id)
        if not phase:
            raise KeyError(f"Phase {phase_id} not found")
        
        return {
            "phase_id": phase_id,
            "name": phase.name,
            "state": phase.state.value,
            "progress": {
                "created_at": phase.created_at,
                "started_at": phase.started_at,
                "completed_at": phase.completed_at,
                "retry_count": phase.retry_count,
            },
            "fan_out": {
                "mode": phase.fan_out_mode.value,
                "child_count": len(phase.child_phases),
            },
            "fan_in": {
                "mode": phase.fan_in_mode.value,
            } if phase.parent_phase else None,
            "gates": [g.name for g in phase.gates],
            "error": phase.error_message,
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化引擎状态"""
        return {
            "engine_id": self.engine_id,
            "created_at": self.created_at,
            "phases": {pid: p.to_dict() for pid, p in self.phases.items()},
            "context": self.context,
            "callback_events": self.callback_router.get_event_log(),
        }
    
    def save(self, path: Path):
        """保存引擎状态到文件"""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".tmp")
        with open(tmp_path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
        tmp_path.replace(path)
    
    @classmethod
    def load(cls, path: Path) -> "PhaseEngine":
        """从文件加载引擎状态"""
        with open(path, "r") as f:
            data = json.load(f)
        
        engine = cls(engine_id=data.get("engine_id", "default"))
        engine.created_at = data.get("created_at", datetime.now().isoformat())
        engine.context = data.get("context", {})
        
        for phase_id, phase_data in data.get("phases", {}).items():
            phase = Phase.from_dict(phase_data)
            engine.phases[phase_id] = phase
        
        return engine
