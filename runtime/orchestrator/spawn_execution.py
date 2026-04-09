#!/usr/bin/env python3
"""
spawn_execution.py — Universal Partial-Completion Continuation Framework v5

目标：把 v4 的 spawn closure 推进到 real spawn execution artifact。

核心能力：
1. 消费 spawn closure artifact / spawn payload
2. 生成 canonical spawn execution artifact
3. 字段包括：spawn_execution_status / spawn_execution_reason / spawn_execution_time / spawn_execution_target
4. Linkage 到 dispatch_id / spawn_closure_id
5. 若当前仓无法真正直接调用外部 sessions_spawn，至少做到：
   - canonical execution artifact
   - downstream 可消费 payload
   - 明确 execution 已被 emit / started 的状态

当前阶段：spawn closure -> spawn execution artifact / intent（不是全域自动外部执行）

这是 v5 新增模块，保持通用 kernel，trading 作为首个接入场景。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from spawn_closure import (
    SpawnClosureArtifact,
    SpawnStatus,
    get_spawn_closure,
    list_spawn_closures,
    SPAWN_CLOSURE_DIR,
)

__all__ = [
    "SpawnExecutionStatus",
    "SpawnExecutionPolicy",
    "SpawnExecutionArtifact",
    "SpawnExecutionKernel",
    "execute_spawn",
    "list_spawn_executions",
    "get_spawn_execution",
    "SPAWN_EXECUTION_VERSION",
]

SPAWN_EXECUTION_VERSION = "spawn_execution_v1"

SpawnExecutionStatus = Literal["started", "skipped", "blocked", "failed"]

# 默认白名单场景（低风险，允许执行）
DEFAULT_EXECUTION_ALLOWED_SCENARIOS = [
    "trading_roundtable_phase1",
    # 可以添加更多白名单场景
]

# Spawn execution 存储目录
SPAWN_EXECUTION_DIR = Path(
    os.environ.get(
        "OPENCLAW_SPAWN_EXECUTION_DIR",
        Path.home() / ".openclaw" / "shared-context" / "spawn_executions",
    )
)

# Spawn closure -> Spawn execution 映射索引文件
EXECUTION_INDEX_FILE = SPAWN_EXECUTION_DIR / "execution_index.json"


def _ensure_execution_dir():
    """确保 spawn execution 目录存在"""
    SPAWN_EXECUTION_DIR.mkdir(parents=True, exist_ok=True)


def _spawn_execution_file(execution_id: str) -> Path:
    """返回 spawn execution artifact 文件路径"""
    return SPAWN_EXECUTION_DIR / f"{execution_id}.json"


def _iso_now() -> str:
    """返回当前 ISO-8601 时间戳"""
    return datetime.now(timezone.utc).isoformat()


def _generate_execution_id() -> str:
    """生成稳定 execution ID"""
    import uuid
    return f"exec_{uuid.uuid4().hex[:12]}"


def _generate_execution_dedupe_key(spawn_id: str, dispatch_id: str) -> str:
    """
    生成 execution 去重 key。
    
    规则：同一 spawn closure 不重复执行。
    """
    return f"exec_dedupe:{spawn_id}:{dispatch_id}"


def _load_execution_index() -> Dict[str, str]:
    """
    加载 execution index（dedupe_key -> execution_id 映射）。
    
    用于去重检查。
    """
    _ensure_execution_dir()
    if not EXECUTION_INDEX_FILE.exists():
        return {}
    
    try:
        with open(EXECUTION_INDEX_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, KeyError):
        return {}


def _save_execution_index(index: Dict[str, str]):
    """保存 execution index"""
    _ensure_execution_dir()
    tmp_file = EXECUTION_INDEX_FILE.with_suffix(".tmp")
    with open(tmp_file, "w") as f:
        json.dump(index, f, indent=2)
    tmp_file.replace(EXECUTION_INDEX_FILE)


def _record_execution_dedupe(dedupe_key: str, execution_id: str):
    """记录 execution dedupe（防止重复执行）"""
    index = _load_execution_index()
    index[dedupe_key] = execution_id
    _save_execution_index(index)


def _is_duplicate_execution(dedupe_key: str) -> bool:
    """检查是否已存在 execution（去重）"""
    index = _load_execution_index()
    return dedupe_key in index


@dataclass
class SpawnExecutionPolicy:
    """
    Spawn execution policy — 评估是否可执行 spawn。
    
    核心字段：
    - scenario_allowlist: 允许执行的场景白名单
    - require_spawn_status: 要求的 spawn status（默认 emitted）
    - require_spawn_payload: 是否要求 spawn_payload 存在
    - prevent_duplicate: 是否防止重复执行
    - simulate_execution: 是否模拟执行（默认 True，只输出 artifact，不真正调用 sessions_spawn）
    
    这是通用 policy，不绑定特定场景。
    """
    scenario_allowlist: List[str] = field(default_factory=lambda: DEFAULT_EXECUTION_ALLOWED_SCENARIOS[:])
    require_spawn_status: str = "emitted"
    require_spawn_payload: bool = True
    prevent_duplicate: bool = True
    simulate_execution: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "scenario_allowlist": self.scenario_allowlist,
            "require_spawn_status": self.require_spawn_status,
            "require_spawn_payload": self.require_spawn_payload,
            "prevent_duplicate": self.prevent_duplicate,
            "simulate_execution": self.simulate_execution,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SpawnExecutionPolicy":
        return cls(
            scenario_allowlist=data.get("scenario_allowlist", DEFAULT_EXECUTION_ALLOWED_SCENARIOS[:]),
            require_spawn_status=data.get("require_spawn_status", "emitted"),
            require_spawn_payload=data.get("require_spawn_payload", True),
            prevent_duplicate=data.get("prevent_duplicate", True),
            simulate_execution=data.get("simulate_execution", True),
        )


@dataclass
class SpawnExecutionArtifact:
    """
    Spawn execution artifact — 真实 spawn execution 记录（可落盘）。
    
    核心字段：
    - execution_id: Execution ID
    - spawn_id: 来源 spawn closure ID
    - dispatch_id: 来源 dispatch ID
    - registration_id: 来源 registration ID
    - task_id: 来源 task ID
    - spawn_execution_status: started | skipped | blocked | failed
    - spawn_execution_reason: 执行/跳过/阻塞/失败的原因
    - spawn_execution_time: 执行时间戳
    - spawn_execution_target: 执行目标（runtime / owner / scenario / task preview）
    - dedupe_key: 去重 key
    - execution_payload: 执行 payload（包含 sessions_spawn 参数）
    - execution_result: 执行结果（模拟或真实）
    - policy_evaluation: policy 评估结果
    - metadata: 额外元数据
    
    这是 canonical artifact，operator/main 可以继续消费。
    """
    execution_id: str
    spawn_id: str
    dispatch_id: str
    registration_id: str
    task_id: str
    spawn_execution_status: SpawnExecutionStatus
    spawn_execution_reason: str
    spawn_execution_time: str
    spawn_execution_target: Dict[str, Any]  # {runtime, owner, scenario, task_preview, cwd}
    dedupe_key: str
    execution_payload: Optional[Dict[str, Any]] = None
    execution_result: Optional[Dict[str, Any]] = None
    policy_evaluation: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "execution_version": SPAWN_EXECUTION_VERSION,
            "execution_id": self.execution_id,
            "spawn_id": self.spawn_id,
            "dispatch_id": self.dispatch_id,
            "registration_id": self.registration_id,
            "task_id": self.task_id,
            "spawn_execution_status": self.spawn_execution_status,
            "spawn_execution_reason": self.spawn_execution_reason,
            "spawn_execution_time": self.spawn_execution_time,
            "spawn_execution_target": self.spawn_execution_target,
            "dedupe_key": self.dedupe_key,
            "execution_payload": self.execution_payload,
            "execution_result": self.execution_result,
            "policy_evaluation": self.policy_evaluation,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SpawnExecutionArtifact":
        return cls(
            execution_id=data.get("execution_id", ""),
            spawn_id=data.get("spawn_id", ""),
            dispatch_id=data.get("dispatch_id", ""),
            registration_id=data.get("registration_id", ""),
            task_id=data.get("task_id", ""),
            spawn_execution_status=data.get("spawn_execution_status", "blocked"),
            spawn_execution_reason=data.get("spawn_execution_reason", ""),
            spawn_execution_time=data.get("spawn_execution_time", ""),
            spawn_execution_target=data.get("spawn_execution_target", {}),
            dedupe_key=data.get("dedupe_key", ""),
            execution_payload=data.get("execution_payload"),
            execution_result=data.get("execution_result"),
            policy_evaluation=data.get("policy_evaluation"),
            metadata=data.get("metadata", {}),
        )
    
    def write(self) -> Path:
        _ensure_execution_dir()
        exec_file = _spawn_execution_file(self.execution_id)
        tmp_file = exec_file.with_suffix(".tmp")
        with open(tmp_file, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
        tmp_file.replace(exec_file)
        try:
            from workflow_state_store import get_store
            store = get_store()
            if store.is_active:
                store.update_task(
                    self.task_id,
                    execution_metadata={"execution_id": self.execution_id, "spawn_id": self.spawn_id},
                )
        except Exception:
            pass
        return exec_file


class SpawnExecutionKernel:
    """
    Spawn execution kernel — 从 spawn closure artifact生成 execution。
    
    提供：
    - evaluate_policy(): 评估 execution policy
    - create_execution(): 创建 execution artifact
    - execute_spawn(): 执行 spawn（写入 artifact + 记录 dedupe）
    """
    
    def __init__(self, policy: Optional[SpawnExecutionPolicy] = None):
        self.policy = policy or SpawnExecutionPolicy()
    
    def evaluate_policy(
        self,
        spawn: SpawnClosureArtifact,
        existing_execution: Optional[SpawnExecutionArtifact] = None,
    ) -> Dict[str, Any]:
        """
        评估 execution policy。
        
        Args:
            spawn: Spawn closure artifact
            existing_execution: 已存在的 execution（用于去重）
        
        Returns:
            {
                "eligible": bool,
                "blocked_reasons": List[str],
                "checks": List[Dict],
            }
        """
        checks: List[Dict[str, Any]] = []
        blocked_reasons: List[str] = []
        
        # Check 1: spawn status
        spawn_status_ok = spawn.spawn_status == self.policy.require_spawn_status
        checks.append({
            "name": "spawn_status",
            "expected": self.policy.require_spawn_status,
            "actual": spawn.spawn_status,
            "passed": spawn_status_ok,
        })
        if not spawn_status_ok:
            blocked_reasons.append(
                f"Spawn status is '{spawn.spawn_status}', required '{self.policy.require_spawn_status}'"
            )
        
        # Check 2: spawn_payload required
        has_spawn_payload = spawn.spawn_payload is not None
        payload_ok = not self.policy.require_spawn_payload or has_spawn_payload
        checks.append({
            "name": "spawn_payload_required",
            "expected": "present" if self.policy.require_spawn_payload else "optional",
            "actual": "present" if has_spawn_payload else "missing",
            "passed": payload_ok,
        })
        if not payload_ok and self.policy.require_spawn_payload:
            blocked_reasons.append("Missing spawn_payload")
        
        # Check 3: scenario allowlist
        scenario = spawn.spawn_target.get("scenario", "")
        scenario_allowed = scenario in self.policy.scenario_allowlist
        checks.append({
            "name": "scenario_allowlist",
            "expected": f"in {self.policy.scenario_allowlist}",
            "actual": scenario,
            "passed": scenario_allowed,
        })
        if not scenario_allowed:
            blocked_reasons.append(f"Scenario '{scenario}' not in allowlist")
        
        # Check 4: duplicate execution prevention
        duplicate_ok = True
        if self.policy.prevent_duplicate:
            dedupe_key = _generate_execution_dedupe_key(spawn.spawn_id, spawn.dispatch_id)
            is_duplicate = _is_duplicate_execution(dedupe_key)
            if is_duplicate:
                duplicate_ok = False
                blocked_reasons.append(f"Duplicate execution: already executed for spawn {spawn.spawn_id}")
        
        checks.append({
            "name": "prevent_duplicate_execution",
            "expected": "no existing execution",
            "actual": "duplicate_found" if not duplicate_ok else "no_duplicate",
            "passed": duplicate_ok,
        })
        
        return {
            "eligible": len(blocked_reasons) == 0,
            "blocked_reasons": blocked_reasons,
            "checks": checks,
        }
    
    def create_execution(
        self,
        spawn: SpawnClosureArtifact,
        policy_evaluation: Dict[str, Any],
    ) -> SpawnExecutionArtifact:
        """
        创建 spawn execution artifact。
        
        Args:
            spawn: Spawn closure artifact
            policy_evaluation: Policy evaluation result
        
        Returns:
            SpawnExecutionArtifact
        """
        execution_id = _generate_execution_id()
        dedupe_key = _generate_execution_dedupe_key(spawn.spawn_id, spawn.dispatch_id)
        
        # 决定 spawn_execution_status
        if policy_evaluation["eligible"]:
            exec_status: SpawnExecutionStatus = "started"
            exec_reason = "Policy evaluation passed; execution started (simulated)" if self.policy.simulate_execution else "Policy evaluation passed; execution started"
        elif policy_evaluation["blocked_reasons"]:
            exec_status = "blocked"
            exec_reason = "; ".join(policy_evaluation["blocked_reasons"])
        else:
            exec_status = "skipped"
            exec_reason = "Not eligible (unknown reason)"
        
        # 构建 spawn_execution_target
        exec_target = {
            "runtime": spawn.spawn_target.get("runtime", "subagent"),
            "owner": spawn.spawn_target.get("owner", ""),
            "scenario": spawn.spawn_target.get("scenario", ""),
            "task_preview": spawn.spawn_target.get("task_preview", ""),
            "cwd": spawn.spawn_target.get("cwd", ""),
        }
        
        # 构建 execution_payload
        execution_payload = None
        execution_result = None
        if spawn.spawn_payload and policy_evaluation["eligible"]:
            execution_payload = spawn.spawn_payload.copy()
            execution_payload["spawn_id"] = spawn.spawn_id
            execution_payload["dispatch_id"] = spawn.dispatch_id
            
            # 模拟执行结果
            if self.policy.simulate_execution:
                execution_result = {
                    "execution_mode": "simulated",
                    "simulation_note": "This is a simulated execution. No actual sessions_spawn was called.",
                    "ready_for_downstream": True,
                    "downstream_payload": execution_payload,
                }
            else:
                # 真实执行路径（当前阶段不启用）
                execution_result = {
                    "execution_mode": "real",
                    "note": "Real execution not yet implemented; requires sessions_spawn integration",
                }
        
        artifact = SpawnExecutionArtifact(
            execution_id=execution_id,
            spawn_id=spawn.spawn_id,
            dispatch_id=spawn.dispatch_id,
            registration_id=spawn.registration_id,
            task_id=spawn.task_id,
            spawn_execution_status=exec_status,
            spawn_execution_reason=exec_reason,
            spawn_execution_time=_iso_now(),
            spawn_execution_target=exec_target,
            dedupe_key=dedupe_key,
            execution_payload=execution_payload,
            execution_result=execution_result,
            policy_evaluation=policy_evaluation,
            metadata={
                "source_spawn_status": spawn.spawn_status,
                "source_spawn_time": spawn.emitted_at,
                "source_dispatch_status": spawn.metadata.get("source_dispatch_status"),
                "truth_anchor": spawn.metadata.get("truth_anchor"),
            },
        )
        
        return artifact
    
    def execute_spawn(
        self,
        spawn: SpawnClosureArtifact,
        existing_execution: Optional[SpawnExecutionArtifact] = None,
    ) -> SpawnExecutionArtifact:
        """
        Execute spawn：评估 policy -> 创建 artifact -> 写入文件 -> 记录 dedupe。
        
        Args:
            spawn: Spawn closure artifact
            existing_execution: 已存在的 execution
        
        Returns:
            SpawnExecutionArtifact（已写入文件）
        """
        # 1. Evaluate policy
        policy_evaluation = self.evaluate_policy(spawn, existing_execution)
        
        # 2. Create artifact
        artifact = self.create_execution(spawn, policy_evaluation)
        
        # 3. Write artifact
        artifact.write()
        
        # 4. Record dedupe（如果 started）
        if artifact.spawn_execution_status == "started":
            _record_execution_dedupe(artifact.dedupe_key, artifact.execution_id)
        
        return artifact


def execute_spawn(
    spawn_id: str,
    policy: Optional[SpawnExecutionPolicy] = None,
) -> SpawnExecutionArtifact:
    """
    Convenience function: 从 spawn closure 执行 spawn。
    
    Args:
        spawn_id: Spawn closure ID
        policy: Execution policy（可选）
    
    Returns:
        SpawnExecutionArtifact（已写入文件）
    """
    spawn = get_spawn_closure(spawn_id)
    if not spawn:
        raise ValueError(f"Spawn closure {spawn_id} not found")
    
    kernel = SpawnExecutionKernel(policy)
    return kernel.execute_spawn(spawn)


def list_spawn_executions(
    spawn_id: Optional[str] = None,
    dispatch_id: Optional[str] = None,
    registration_id: Optional[str] = None,
    task_id: Optional[str] = None,
    execution_status: Optional[str] = None,
    limit: int = 100,
) -> List[SpawnExecutionArtifact]:
    """
    列出 spawn execution artifacts。
    
    Args:
        spawn_id: 按 spawn_id 过滤
        dispatch_id: 按 dispatch_id 过滤
        registration_id: 按 registration_id 过滤
        task_id: 按 task_id 过滤
        execution_status: 按 spawn_execution_status 过滤
        limit: 最大返回数量
    
    Returns:
        SpawnExecutionArtifact 列表
    """
    _ensure_execution_dir()
    
    executions = []
    for exec_file in SPAWN_EXECUTION_DIR.glob("*.json"):
        if exec_file.name == "execution_index.json":
            continue
        
        try:
            with open(exec_file, "r") as f:
                data = json.load(f)
            artifact = SpawnExecutionArtifact.from_dict(data)
            
            # 过滤
            if spawn_id and artifact.spawn_id != spawn_id:
                continue
            if dispatch_id and artifact.dispatch_id != dispatch_id:
                continue
            if registration_id and artifact.registration_id != registration_id:
                continue
            if task_id and artifact.task_id != task_id:
                continue
            if execution_status and artifact.spawn_execution_status != execution_status:
                continue
            
            executions.append(artifact)
        except (json.JSONDecodeError, KeyError):
            pass
    
    # 按 execution_id 排序
    executions.sort(key=lambda e: e.execution_id)
    
    return executions[:limit]


def get_spawn_execution(execution_id: str) -> Optional[SpawnExecutionArtifact]:
    """
    获取 spawn execution artifact。
    
    Args:
        execution_id: Execution ID
    
    Returns:
        SpawnExecutionArtifact，不存在则返回 None
    """
    exec_file = _spawn_execution_file(execution_id)
    if not exec_file.exists():
        return None
    
    with open(exec_file, "r") as f:
        data = json.load(f)
    
    return SpawnExecutionArtifact.from_dict(data)


# ============ Trading 场景特定 helper ============

def execute_trading_spawn(
    spawn_id: str,
    *,
    policy: Optional[SpawnExecutionPolicy] = None,
) -> SpawnExecutionArtifact:
    """
    Trading 场景特定的 spawn execution。
    
    这是 trading_roundtable_phase1 场景的 convenience function。
    """
    # 使用 trading 特定的 policy（白名单包含 trading_roundtable_phase1）
    if policy is None:
        policy = SpawnExecutionPolicy(
            scenario_allowlist=["trading_roundtable_phase1"],
            require_spawn_status="emitted",
            require_spawn_payload=True,
            prevent_duplicate=True,
            simulate_execution=True,
        )
    
    return execute_spawn(spawn_id, policy)


# CLI 入口
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python spawn_execution.py execute <spawn_id>")
        print("  python spawn_execution.py list [--status <status>] [--spawn <spawn_id>]")
        print("  python spawn_execution.py get <execution_id>")
        print("  python spawn_execution.py trading <spawn_id>")
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == "execute":
        if len(sys.argv) < 3:
            print("Error: missing spawn_id")
            sys.exit(1)
        
        spawn_id = sys.argv[2]
        artifact = execute_spawn(spawn_id)
        print(json.dumps(artifact.to_dict(), indent=2))
        print(f"\nSpawn execution artifact written to: {_spawn_execution_file(artifact.execution_id)}")
        if artifact.spawn_execution_status == "started":
            print(f"\nExecution result (simulated):")
            print(json.dumps(artifact.execution_result, indent=2))
    
    elif cmd == "list":
        status = None
        spawn_id = None
        if "--status" in sys.argv:
            idx = sys.argv.index("--status")
            if idx + 1 < len(sys.argv):
                status = sys.argv[idx + 1]
        if "--spawn" in sys.argv:
            idx = sys.argv.index("--spawn")
            if idx + 1 < len(sys.argv):
                spawn_id = sys.argv[idx + 1]
        
        executions = list_spawn_executions(
            spawn_id=spawn_id,
            execution_status=status,
        )
        print(json.dumps([e.to_dict() for e in executions], indent=2))
    
    elif cmd == "get":
        if len(sys.argv) < 3:
            print("Error: missing execution_id")
            sys.exit(1)
        
        execution_id = sys.argv[2]
        artifact = get_spawn_execution(execution_id)
        if artifact:
            print(json.dumps(artifact.to_dict(), indent=2))
        else:
            print(f"Spawn execution {execution_id} not found")
            sys.exit(1)
    
    elif cmd == "trading":
        if len(sys.argv) < 3:
            print("Error: missing spawn_id")
            sys.exit(1)
        
        spawn_id = sys.argv[2]
        artifact = execute_trading_spawn(spawn_id)
        print(json.dumps(artifact.to_dict(), indent=2))
        print(f"\nTrading spawn execution artifact written to: {_spawn_execution_file(artifact.execution_id)}")
        if artifact.spawn_execution_status == "started":
            print(f"\nTrading execution result:")
            print(json.dumps(artifact.execution_result, indent=2))
    
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
