#!/usr/bin/env python3
"""
auto_dispatch.py — Universal Partial-Completion Continuation Framework v3

目标：把 v2 已注册的 tasks 推进到 auto-dispatch execution intent + 最小执行路径。

核心能力：
1. Auto-dispatch selector: 从 task registry 读取 registered + ready_for_auto_dispatch 的任务
2. Dispatch policy evaluation: 评估是否可自动派发（blocked / missing anchor / scenario allowlist / duplicate）
3. Dispatch artifact generation: 生成真实 dispatch artifact（dispatch_status / dispatch_reason / dispatch_time / dispatch_target）
4. 最小真实执行路径：trading_roundtable 场景能产生真实 dispatch artifact / execution intent

这是 v3 新增模块，保持通用 kernel，trading 作为首个接入场景。

当前阶段：registered -> auto-dispatch intent / limited execution（不是全域无人值守）
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from task_registration import (
    TaskRegistry,
    TaskRegistrationRecord,
    list_registrations,
    get_registration,
)

# P0-5 Batch C: SubagentExecutor integration for dispatch execution
from subagent_executor import (
    SubagentConfig,
    SubagentExecutor,
    TERMINAL_STATES,
)

__all__ = [
    "DispatchStatus",
    "DispatchPolicy",
    "DispatchArtifact",
    "AutoDispatchSelector",
    "DispatchExecutor",
    "select_ready_tasks",
    "evaluate_dispatch_policy",
    "generate_dispatch_artifact",
    "execute_dispatch",
    "DISPATCH_ARTIFACT_VERSION",
]

DISPATCH_ARTIFACT_VERSION = "auto_dispatch_v1"

DispatchStatus = Literal["dispatched", "skipped", "blocked"]

# 默认白名单场景（低风险）
DEFAULT_AUTO_DISPATCH_ALLOWED_SCENARIOS = [
    "trading_roundtable_phase1",
    # 可以添加更多白名单场景
]

# Dispatch 存储目录
DISPATCH_DIR = Path(
    os.environ.get(
        "OPENCLAW_DISPATCH_DIR",
        Path.home() / ".openclaw" / "shared-context" / "dispatches",
    )
)


def _ensure_dispatch_dir():
    """确保 dispatch 目录存在"""
    DISPATCH_DIR.mkdir(parents=True, exist_ok=True)


def _dispatch_file(dispatch_id: str) -> Path:
    """返回 dispatch artifact 文件路径"""
    return DISPATCH_DIR / f"{dispatch_id}.json"


def _iso_now() -> str:
    """返回当前 ISO-8601 时间戳"""
    return datetime.now().isoformat()


def _generate_dispatch_id() -> str:
    """生成稳定 dispatch ID"""
    import uuid
    return f"dispatch_{uuid.uuid4().hex[:12]}"


@dataclass
class DispatchPolicy:
    """
    Dispatch policy — 评估是否可自动派发。
    
    核心字段：
    - scenario_allowlist: 允许自动 dispatch 的场景白名单
    - blocked_statuses: 阻止 dispatch 的任务状态
    - require_anchor: 是否要求 truth_anchor
    - prevent_duplicate: 是否防止重复 dispatch
    
    这是通用 policy，不绑定特定场景。
    """
    scenario_allowlist: List[str] = field(default_factory=lambda: DEFAULT_AUTO_DISPATCH_ALLOWED_SCENARIOS[:])
    blocked_statuses: List[str] = field(default_factory=lambda: ["blocked", "in_progress"])
    require_anchor: bool = True
    prevent_duplicate: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "scenario_allowlist": self.scenario_allowlist,
            "blocked_statuses": self.blocked_statuses,
            "require_anchor": self.require_anchor,
            "prevent_duplicate": self.prevent_duplicate,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DispatchPolicy":
        return cls(
            scenario_allowlist=data.get("scenario_allowlist", DEFAULT_AUTO_DISPATCH_ALLOWED_SCENARIOS[:]),
            blocked_statuses=data.get("blocked_statuses", ["blocked", "in_progress"]),
            require_anchor=data.get("require_anchor", True),
            prevent_duplicate=data.get("prevent_duplicate", True),
        )


@dataclass
class DispatchArtifact:
    """
    Dispatch artifact — 真实 dispatch 记录（可落盘）。
    
    核心字段：
    - dispatch_id: Dispatch 记录 ID
    - registration_id: 来源 registration ID
    - task_id: 来源 task ID
    - dispatch_status: dispatched | skipped | blocked
    - dispatch_reason: dispatch/skip/block 的原因
    - dispatch_time: dispatch 时间戳
    - dispatch_target: dispatch 目标（scenario / adapter）
    - execution_intent: 执行 intent（可选，包含 recommended_spawn 等）
    - policy_evaluation: policy 评估结果
    - metadata: 额外元数据
    
    这是 canonical artifact，operator/main 可以继续消费。
    """
    dispatch_id: str
    registration_id: str
    task_id: str
    dispatch_status: DispatchStatus
    dispatch_reason: str
    dispatch_time: str
    dispatch_target: Dict[str, Any]  # {scenario, adapter, batch_id, owner}
    execution_intent: Optional[Dict[str, Any]] = None
    policy_evaluation: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "dispatch_version": DISPATCH_ARTIFACT_VERSION,
            "dispatch_id": self.dispatch_id,
            "registration_id": self.registration_id,
            "task_id": self.task_id,
            "dispatch_status": self.dispatch_status,
            "dispatch_reason": self.dispatch_reason,
            "dispatch_time": self.dispatch_time,
            "dispatch_target": self.dispatch_target,
            "execution_intent": self.execution_intent,
            "policy_evaluation": self.policy_evaluation,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DispatchArtifact":
        return cls(
            dispatch_id=data.get("dispatch_id", ""),
            registration_id=data.get("registration_id", ""),
            task_id=data.get("task_id", ""),
            dispatch_status=data.get("dispatch_status", "blocked"),
            dispatch_reason=data.get("dispatch_reason", ""),
            dispatch_time=data.get("dispatch_time", ""),
            dispatch_target=data.get("dispatch_target", {}),
            execution_intent=data.get("execution_intent"),
            policy_evaluation=data.get("policy_evaluation"),
            metadata=data.get("metadata", {}),
        )
    
    def write(self) -> Path:
        """写入 dispatch artifact 到文件，同时同步到 WorkflowState"""
        _ensure_dispatch_dir()
        dispatch_file = _dispatch_file(self.dispatch_id)
        tmp_file = dispatch_file.with_suffix(".tmp")
        with open(tmp_file, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
        tmp_file.replace(dispatch_file)
        try:
            from workflow_state_store import get_store
            store = get_store()
            if store.is_active:
                store.update_task(
                    self.task_id,
                    execution_metadata={
                        "dispatch_id": self.dispatch_id,
                        "dispatch_status": self.dispatch_status,
                    },
                )
        except Exception:
            pass
        return dispatch_file


class AutoDispatchSelector:
    """
    Auto-dispatch selector — 从 task registry 选择可 dispatch 的任务。
    
    提供：
    - select_ready_tasks(): 选择 ready_for_auto_dispatch 的任务
    - evaluate_policy(): 评估 dispatch policy
    """
    
    def __init__(self, policy: Optional[DispatchPolicy] = None):
        self.policy = policy or DispatchPolicy()
        self.registry = TaskRegistry()
    
    def select_ready_tasks(
        self,
        limit: int = 10,
    ) -> List[TaskRegistrationRecord]:
        """
        选择 ready_for_auto_dispatch 的任务。
        
        Args:
            limit: 最大返回数量
        
        Returns:
            TaskRegistrationRecord 列表
        """
        # 从 registry 读取 registered + ready_for_auto_dispatch 的任务
        records = list_registrations(
            registration_status="registered",
            limit=limit * 2,  # 多读一些，因为后面会过滤
        )
        
        # 过滤 ready_for_auto_dispatch
        ready_records = []
        for record in records:
            if not record.ready_for_auto_dispatch:
                continue
            if record.status in self.policy.blocked_statuses:
                continue
            ready_records.append(record)
        
        return ready_records[:limit]
    
    def evaluate_policy(
        self,
        record: TaskRegistrationRecord,
        existing_dispatches: Optional[List[DispatchArtifact]] = None,
    ) -> Dict[str, Any]:
        """
        评估 dispatch policy。
        
        Args:
            record: Task registration record
            existing_dispatches: 已存在的 dispatch artifacts（用于去重）
        
        Returns:
            {
                "eligible": bool,
                "blocked_reasons": List[str],
                "checks": List[Dict],
            }
        """
        checks: List[Dict[str, Any]] = []
        blocked_reasons: List[str] = []
        
        # Check 1: scenario allowlist
        scenario = record.metadata.get("scenario", "")
        scenario_allowed = scenario in self.policy.scenario_allowlist
        checks.append({
            "name": "scenario_allowlist",
            "expected": f"in {self.policy.scenario_allowlist}",
            "actual": scenario,
            "passed": scenario_allowed,
        })
        if not scenario_allowed:
            blocked_reasons.append(f"Scenario '{scenario}' not in allowlist")
        
        # Check 2: truth_anchor required
        has_anchor = record.truth_anchor is not None and record.truth_anchor.anchor_value
        anchor_ok = not self.policy.require_anchor or has_anchor
        checks.append({
            "name": "truth_anchor_required",
            "expected": "present" if self.policy.require_anchor else "optional",
            "actual": "present" if has_anchor else "missing",
            "passed": anchor_ok,
        })
        if not anchor_ok:
            blocked_reasons.append("Missing truth_anchor")
        
        # Check 3: registration_status
        status_ok = record.registration_status == "registered"
        checks.append({
            "name": "registration_status",
            "expected": "registered",
            "actual": record.registration_status,
            "passed": status_ok,
        })
        if not status_ok:
            blocked_reasons.append(f"Registration status is '{record.registration_status}'")
        
        # Check 4: task status not blocked
        task_status_ok = record.status not in self.policy.blocked_statuses
        checks.append({
            "name": "task_status_not_blocked",
            "expected": f"not in {self.policy.blocked_statuses}",
            "actual": record.status,
            "passed": task_status_ok,
        })
        if not task_status_ok:
            blocked_reasons.append(f"Task status '{record.status}' is blocked")
        
        # Check 5: ready_for_auto_dispatch
        ready_ok = record.ready_for_auto_dispatch
        checks.append({
            "name": "ready_for_auto_dispatch",
            "expected": True,
            "actual": ready_ok,
            "passed": ready_ok,
        })
        if not ready_ok:
            blocked_reasons.append("Not ready for auto_dispatch")
        
        # Check 6: duplicate dispatch prevention
        duplicate_ok = True
        if self.policy.prevent_duplicate and existing_dispatches:
            for dispatch in existing_dispatches:
                if dispatch.registration_id == record.registration_id:
                    if dispatch.dispatch_status == "dispatched":
                        duplicate_ok = False
                        blocked_reasons.append(f"Duplicate dispatch: already dispatched as {dispatch.dispatch_id}")
                        break
        
        checks.append({
            "name": "prevent_duplicate_dispatch",
            "expected": "no existing dispatch",
            "actual": "duplicate_found" if not duplicate_ok else "no_duplicate",
            "passed": duplicate_ok,
        })
        
        return {
            "eligible": len(blocked_reasons) == 0,
            "blocked_reasons": blocked_reasons,
            "checks": checks,
        }


class DispatchExecutor:
    """
    Dispatch executor — 执行 dispatch 并生成 artifact。
    
    P0-5 Batch C (2026-03-25): Integrated SubagentExecutor for real dispatch execution.
    
    提供：
    - generate_dispatch_artifact(): 生成 dispatch artifact
    - execute_dispatch(): 执行 dispatch（写入 artifact + 可选执行 intent）
    - _execute_dispatch_intent(): 实际启动 subagent 执行 dispatch intent（新增）
    """
    
    def __init__(self, selector: Optional[AutoDispatchSelector] = None):
        self.selector = selector or AutoDispatchSelector()
    
    def generate_dispatch_artifact(
        self,
        record: TaskRegistrationRecord,
        policy_evaluation: Dict[str, Any],
    ) -> DispatchArtifact:
        """
        生成 dispatch artifact。
        
        Args:
            record: Task registration record
            policy_evaluation: Policy evaluation result
        
        Returns:
            DispatchArtifact
        """
        dispatch_id = _generate_dispatch_id()
        
        # 决定 dispatch_status
        if policy_evaluation["eligible"]:
            dispatch_status: DispatchStatus = "dispatched"
            dispatch_reason = "Policy evaluation passed"
        elif policy_evaluation["blocked_reasons"]:
            dispatch_status = "blocked"
            dispatch_reason = "; ".join(policy_evaluation["blocked_reasons"])
        else:
            dispatch_status = "skipped"
            dispatch_reason = "Not eligible (unknown reason)"
        
        # 构建 dispatch_target
        dispatch_target = {
            "scenario": record.metadata.get("scenario", ""),
            "adapter": record.metadata.get("adapter", ""),
            "batch_id": record.batch_id,
            "owner": record.owner,
        }
        
        # 构建 execution_intent（最小真实执行路径）
        execution_intent = None
        if dispatch_status == "dispatched":
            execution_intent = self._build_execution_intent(record, dispatch_id)
        
        artifact = DispatchArtifact(
            dispatch_id=dispatch_id,
            registration_id=record.registration_id,
            task_id=record.task_id,
            dispatch_status=dispatch_status,
            dispatch_reason=dispatch_reason,
            dispatch_time=_iso_now(),
            dispatch_target=dispatch_target,
            execution_intent=execution_intent,
            policy_evaluation=policy_evaluation,
            metadata={
                "source_registration_status": record.registration_status,
                "source_task_status": record.status,
                "truth_anchor": record.truth_anchor.to_dict() if record.truth_anchor else None,
            },
        )
        
        # ========== Observability Batch 2: Promise Anchor Verification ==========
        # 验证 dispatch 是否包含有效承诺锚点（audit-only 模式）
        try:
            from hooks.hook_integrations import verify_dispatch_promise_anchor, log_anchor_violation
            
            anchor_ok, anchor_reason = verify_dispatch_promise_anchor(record, artifact.to_dict())
            if not anchor_ok:
                # 记录违规但不阻止 dispatch（audit-only）
                log_anchor_violation(record.task_id, anchor_reason, {
                    "registration_id": record.registration_id,
                    "dispatch_id": dispatch_id,
                    "dispatch_status": dispatch_status,
                })
                # 将锚点验证结果添加到 metadata
                artifact.metadata["anchor_verification"] = {
                    "verified": anchor_ok,
                    "reason": anchor_reason,
                    "violation_logged": True,
                }
            else:
                artifact.metadata["anchor_verification"] = {
                    "verified": True,
                    "reason": anchor_reason,
                }
        except ImportError:
            # Hook 模块不可用时不阻断主流程
            pass
        # ========== End Batch 2 Hook Integration ==========
        
        return artifact
    
    def _build_execution_intent(
        self,
        record: TaskRegistrationRecord,
        dispatch_id: str,
    ) -> Dict[str, Any]:
        """
        构建 execution intent（最小真实执行路径）。
        
        对于 trading_roundtable 场景，生成 recommended_spawn。
        """
        scenario = record.metadata.get("scenario", "")
        adapter = record.metadata.get("adapter", "")
        
        # 从 proposed_task 中提取信息
        proposed_task = record.proposed_task
        task_type = proposed_task.get("task_type", "continuation")
        title = proposed_task.get("title", "Continuation task")
        description = proposed_task.get("description", "")
        
        # 构建 recommended_spawn
        recommended_spawn = {
            "runtime": "subagent",
            "task_preview": title,
            "task": description,
            "cwd": record.metadata.get("cwd", str(Path.home() / ".openclaw" / "workspace")),
            "metadata": {
                "dispatch_id": dispatch_id,
                "registration_id": record.registration_id,
                "task_id": record.task_id,
                "source": "auto_dispatch_v3",
            },
        }
        
        # Trading 场景特定增强
        if scenario == "trading_roundtable_phase1":
            # 从 truth_anchor 中提取 batch_id
            batch_id = record.batch_id
            if record.truth_anchor and record.truth_anchor.anchor_type == "batch_id":
                batch_id = record.truth_anchor.anchor_value
            
            recommended_spawn["metadata"]["trading_context"] = {
                "batch_id": batch_id,
                "phase": "phase1_continuation",
                "adapter": adapter,
            }
        
        return {
            "recommended_spawn": recommended_spawn,
            "dispatch_id": dispatch_id,
            "registration_id": record.registration_id,
        }
    
    def execute_dispatch(
        self,
        record: TaskRegistrationRecord,
        existing_dispatches: Optional[List[DispatchArtifact]] = None,
    ) -> DispatchArtifact:
        """
        执行 dispatch：评估 policy -> 生成 artifact -> 写入文件 -> (可选) 启动 subagent 执行。
        
        P0-5 Batch C (2026-03-25): Integrated SubagentExecutor for real dispatch execution.
        
        Args:
            record: Task registration record
            existing_dispatches: 已存在的 dispatch artifacts
        
        Returns:
            DispatchArtifact（已写入文件）
        """
        # 1. Evaluate policy
        policy_evaluation = self.selector.evaluate_policy(record, existing_dispatches)
        
        # 2. Generate artifact
        artifact = self.generate_dispatch_artifact(record, policy_evaluation)
        
        # 3. Write artifact
        artifact.write()
        
        # 4. Update task status（如果 dispatched）
        if artifact.dispatch_status == "dispatched":
            self.selector.registry.update_status(
                record.registration_id,
                "in_progress",
                metadata={
                    "dispatch_id": artifact.dispatch_id,
                    "dispatch_time": artifact.dispatch_time,
                },
            )
            
            # P0-5 Batch C: Execute dispatch intent via SubagentExecutor
            # This actually starts the subagent to execute the dispatched task
            if artifact.execution_intent and "recommended_spawn" in artifact.execution_intent:
                subagent_task_id = self._execute_dispatch_intent(
                    record=record,
                    dispatch_id=artifact.dispatch_id,
                    execution_intent=artifact.execution_intent,
                )
                # Update artifact with subagent task info
                artifact.metadata["subagent_task_id"] = subagent_task_id
                artifact.metadata["execution_started"] = True
                artifact.write()
        
        return artifact
    
    def _execute_dispatch_intent(
        self,
        record: TaskRegistrationRecord,
        dispatch_id: str,
        execution_intent: Dict[str, Any],
    ) -> str:
        """
        P0-5 Batch C (2026-03-25): Execute dispatch intent via SubagentExecutor.
        
        This method actually starts a subagent to execute the dispatched task.
        
        Args:
            record: Task registration record
            dispatch_id: Dispatch ID
            execution_intent: Execution intent from dispatch artifact
        
        Returns:
            subagent_task_id: Subagent task ID for tracking
        """
        recommended_spawn = execution_intent.get("recommended_spawn", {})
        
        # Extract spawn parameters
        task = recommended_spawn.get("task", "")
        runtime = recommended_spawn.get("runtime", "subagent")
        cwd = recommended_spawn.get("cwd", str(Path.home() / ".openclaw" / "workspace"))
        metadata = recommended_spawn.get("metadata", {})
        
        # Generate label from dispatch_id
        label = f"dispatch-{dispatch_id.replace('dispatch_', '')}"
        
        # Create SubagentConfig
        subagent_config = SubagentConfig(
            label=label,
            runtime="subagent" if runtime == "subagent" else "acp",
            timeout_seconds=metadata.get("timeout_seconds", 1800),
            allowed_tools=metadata.get("allowed_tools"),
            cwd=cwd,
            metadata={
                **metadata,
                "source": "auto_dispatch",
                "dispatch_id": dispatch_id,
                "registration_id": record.registration_id,
                "task_id": record.task_id,
            },
        )
        
        # Create SubagentExecutor
        executor = SubagentExecutor(config=subagent_config, cwd=cwd)
        
        # Start subagent asynchronously
        task_id = executor.execute_async(task)
        
        return task_id


def select_ready_tasks(
    limit: int = 10,
    policy: Optional[DispatchPolicy] = None,
) -> List[TaskRegistrationRecord]:
    """
    Convenience function: 选择 ready_for_auto_dispatch 的任务。
    
    Args:
        limit: 最大返回数量
        policy: Dispatch policy（可选）
    
    Returns:
        TaskRegistrationRecord 列表
    """
    selector = AutoDispatchSelector(policy)
    return selector.select_ready_tasks(limit)


def evaluate_dispatch_policy(
    record: TaskRegistrationRecord,
    policy: Optional[DispatchPolicy] = None,
    existing_dispatches: Optional[List[DispatchArtifact]] = None,
) -> Dict[str, Any]:
    """
    Convenience function: 评估 dispatch policy。
    
    Args:
        record: Task registration record
        policy: Dispatch policy（可选）
        existing_dispatches: 已存在的 dispatch artifacts
    
    Returns:
        Policy evaluation result
    """
    selector = AutoDispatchSelector(policy)
    return selector.evaluate_policy(record, existing_dispatches)


def generate_dispatch_artifact(
    record: TaskRegistrationRecord,
    policy_evaluation: Dict[str, Any],
) -> DispatchArtifact:
    """
    Convenience function: 生成 dispatch artifact。
    
    Args:
        record: Task registration record
        policy_evaluation: Policy evaluation result
    
    Returns:
        DispatchArtifact
    """
    executor = DispatchExecutor()
    return executor.generate_dispatch_artifact(record, policy_evaluation)


def execute_dispatch(
    record: TaskRegistrationRecord,
    policy: Optional[DispatchPolicy] = None,
    existing_dispatches: Optional[List[DispatchArtifact]] = None,
) -> DispatchArtifact:
    """
    Convenience function: 执行 dispatch。
    
    Args:
        record: Task registration record
        policy: Dispatch policy（可选）
        existing_dispatches: 已存在的 dispatch artifacts
    
    Returns:
        DispatchArtifact（已写入文件）
    """
    selector = AutoDispatchSelector(policy)
    executor = DispatchExecutor(selector)
    return executor.execute_dispatch(record, existing_dispatches)


def list_dispatches(
    registration_id: Optional[str] = None,
    task_id: Optional[str] = None,
    dispatch_status: Optional[str] = None,
    limit: int = 100,
) -> List[DispatchArtifact]:
    """
    列出 dispatch artifacts。
    
    Args:
        registration_id: 按 registration_id 过滤
        task_id: 按 task_id 过滤
        dispatch_status: 按 dispatch_status 过滤
        limit: 最大返回数量
    
    Returns:
        DispatchArtifact 列表
    """
    _ensure_dispatch_dir()
    
    dispatches = []
    for dispatch_file in DISPATCH_DIR.glob("*.json"):
        try:
            with open(dispatch_file, "r") as f:
                data = json.load(f)
            artifact = DispatchArtifact.from_dict(data)
            
            # 过滤
            if registration_id and artifact.registration_id != registration_id:
                continue
            if task_id and artifact.task_id != task_id:
                continue
            if dispatch_status and artifact.dispatch_status != dispatch_status:
                continue
            
            dispatches.append(artifact)
        except (json.JSONDecodeError, KeyError):
            pass
    
    # 按 dispatch_time 倒序
    dispatches.sort(key=lambda d: d.dispatch_time, reverse=True)
    
    return dispatches[:limit]


def get_dispatch(dispatch_id: str) -> Optional[DispatchArtifact]:
    """
    获取 dispatch artifact。
    
    Args:
        dispatch_id: Dispatch ID
    
    Returns:
        DispatchArtifact，不存在则返回 None
    """
    dispatch_file = _dispatch_file(dispatch_id)
    if not dispatch_file.exists():
        return None
    
    with open(dispatch_file, "r") as f:
        data = json.load(f)
    
    return DispatchArtifact.from_dict(data)


# CLI 入口
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python auto_dispatch.py select [--limit <limit>]")
        print("  python auto_dispatch.py evaluate <registration_id>")
        print("  python auto_dispatch.py execute <registration_id>")
        print("  python auto_dispatch.py list [--status <status>] [--registration <registration_id>]")
        print("  python auto_dispatch.py get <dispatch_id>")
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == "select":
        limit = 10
        if "--limit" in sys.argv:
            idx = sys.argv.index("--limit")
            if idx + 1 < len(sys.argv):
                limit = int(sys.argv[idx + 1])
        
        records = select_ready_tasks(limit)
        print(json.dumps([r.to_dict() for r in records], indent=2))
    
    elif cmd == "evaluate":
        if len(sys.argv) < 3:
            print("Error: missing registration_id")
            sys.exit(1)
        
        registration_id = sys.argv[2]
        record = get_registration(registration_id)
        if not record:
            print(f"Registration {registration_id} not found")
            sys.exit(1)
        
        evaluation = evaluate_dispatch_policy(record)
        print(json.dumps(evaluation, indent=2))
    
    elif cmd == "execute":
        if len(sys.argv) < 3:
            print("Error: missing registration_id")
            sys.exit(1)
        
        registration_id = sys.argv[2]
        record = get_registration(registration_id)
        if not record:
            print(f"Registration {registration_id} not found")
            sys.exit(1)
        
        artifact = execute_dispatch(record)
        print(json.dumps(artifact.to_dict(), indent=2))
        print(f"\nDispatch artifact written to: {_dispatch_file(artifact.dispatch_id)}")
    
    elif cmd == "list":
        status = None
        registration_id = None
        if "--status" in sys.argv:
            idx = sys.argv.index("--status")
            if idx + 1 < len(sys.argv):
                status = sys.argv[idx + 1]
        if "--registration" in sys.argv:
            idx = sys.argv.index("--registration")
            if idx + 1 < len(sys.argv):
                registration_id = sys.argv[idx + 1]
        
        dispatches = list_dispatches(
            registration_id=registration_id,
            dispatch_status=status,
        )
        print(json.dumps([d.to_dict() for d in dispatches], indent=2))
    
    elif cmd == "get":
        if len(sys.argv) < 3:
            print("Error: missing dispatch_id")
            sys.exit(1)
        
        dispatch_id = sys.argv[2]
        artifact = get_dispatch(dispatch_id)
        if artifact:
            print(json.dumps(artifact.to_dict(), indent=2))
        else:
            print(f"Dispatch {dispatch_id} not found")
            sys.exit(1)
    
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
