#!/usr/bin/env python3
"""
spawn_closure.py — Universal Partial-Completion Continuation Framework v4

目标：把 v3 的 dispatch intent 推进到 downstream spawn closure（可执行的 spawn artifact）。

核心能力：
1. 读取 dispatch artifact 中的 execution_intent.recommended_spawn
2. 生成 canonical spawn closure artifact（spawn_status / spawn_reason / spawn_target / dedupe_key 等）
3. 最小去重/防重复发起（同一 dispatch 不重复 emit）
4. policy guard（blocked / duplicate / missing payload 不能 emit，白名单场景）
5. 输出 downstream 可消费的 spawn command / payload

当前阶段：dispatch -> spawn closure intent / limited emission（不是全域自动外部执行）

这是 v4 新增模块，保持通用 kernel，trading 作为首个接入场景。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from auto_dispatch import (
    DispatchArtifact,
    DispatchStatus,
    get_dispatch,
    list_dispatches,
    DISPATCH_DIR,
)

__all__ = [
    "SpawnStatus",
    "SpawnPolicy",
    "SpawnClosureArtifact",
    "SpawnClosureKernel",
    "create_spawn_closure",
    "emit_spawn_closure",
    "list_spawn_closures",
    "get_spawn_closure",
    "SPAWN_CLOSURE_VERSION",
]

SPAWN_CLOSURE_VERSION = "spawn_closure_v1"

SpawnStatus = Literal["ready", "skipped", "blocked", "emitted"]

# 默认白名单场景（低风险，允许 emit）
DEFAULT_SPAWN_ALLOWED_SCENARIOS = [
    "trading_roundtable_phase1",
    # 可以添加更多白名单场景
]

# Spawn closure 存储目录
SPAWN_CLOSURE_DIR = Path(
    os.environ.get(
        "OPENCLAW_SPAWN_CLOSURE_DIR",
        Path.home() / ".openclaw" / "shared-context" / "spawn_closures",
    )
)

# Dispatch -> Spawn closure 映射索引文件
SPAWN_INDEX_FILE = SPAWN_CLOSURE_DIR / "spawn_index.json"


def _ensure_spawn_dir():
    """确保 spawn closure 目录存在"""
    SPAWN_CLOSURE_DIR.mkdir(parents=True, exist_ok=True)


def _spawn_closure_file(spawn_id: str) -> Path:
    """返回 spawn closure artifact 文件路径"""
    return SPAWN_CLOSURE_DIR / f"{spawn_id}.json"


def _iso_now() -> str:
    """返回当前 ISO-8601 时间戳"""
    return datetime.now(timezone.utc).isoformat()


def _generate_spawn_id() -> str:
    """生成稳定 spawn ID"""
    import uuid
    return f"spawn_{uuid.uuid4().hex[:12]}"


def _generate_dedupe_key(dispatch_id: str, registration_id: str, task_id: str) -> str:
    """
    生成去重 key。
    
    规则：同一 dispatch 不重复 emit spawn closure。
    """
    return f"dedupe:{dispatch_id}:{registration_id}:{task_id}"


def _load_spawn_index() -> Dict[str, str]:
    """
    加载 spawn index（dedupe_key -> spawn_id 映射）。
    
    用于去重检查。
    """
    _ensure_spawn_dir()
    if not SPAWN_INDEX_FILE.exists():
        return {}
    
    try:
        with open(SPAWN_INDEX_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, KeyError):
        return {}


def _save_spawn_index(index: Dict[str, str]):
    """保存 spawn index"""
    _ensure_spawn_dir()
    tmp_file = SPAWN_INDEX_FILE.with_suffix(".tmp")
    with open(tmp_file, "w") as f:
        json.dump(index, f, indent=2)
    tmp_file.replace(SPAWN_INDEX_FILE)


def _record_spawn_dedupe(dedupe_key: str, spawn_id: str):
    """记录 spawn dedupe（防止重复 emit）"""
    index = _load_spawn_index()
    index[dedupe_key] = spawn_id
    _save_spawn_index(index)


def _is_duplicate_spawn(dedupe_key: str) -> bool:
    """检查是否已存在 spawn（去重）"""
    index = _load_spawn_index()
    return dedupe_key in index


@dataclass
class SpawnPolicy:
    """
    Spawn policy — 评估是否可 emit spawn closure。
    
    核心字段：
    - scenario_allowlist: 允许 emit spawn 的场景白名单
    - require_dispatch_status: 要求的 dispatch status（默认 dispatched）
    - require_execution_intent: 是否要求 execution_intent 存在
    - prevent_duplicate: 是否防止重复 spawn
    - allow_limited_emission: 是否允许 limited emission（默认 True，只输出 artifact + command）
    
    这是通用 policy，不绑定特定场景。
    """
    scenario_allowlist: List[str] = field(default_factory=lambda: DEFAULT_SPAWN_ALLOWED_SCENARIOS[:])
    require_dispatch_status: str = "dispatched"
    require_execution_intent: bool = True
    prevent_duplicate: bool = True
    allow_limited_emission: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "scenario_allowlist": self.scenario_allowlist,
            "require_dispatch_status": self.require_dispatch_status,
            "require_execution_intent": self.require_execution_intent,
            "prevent_duplicate": self.prevent_duplicate,
            "allow_limited_emission": self.allow_limited_emission,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SpawnPolicy":
        return cls(
            scenario_allowlist=data.get("scenario_allowlist", DEFAULT_SPAWN_ALLOWED_SCENARIOS[:]),
            require_dispatch_status=data.get("require_dispatch_status", "dispatched"),
            require_execution_intent=data.get("require_execution_intent", True),
            prevent_duplicate=data.get("prevent_duplicate", True),
            allow_limited_emission=data.get("allow_limited_emission", True),
        )


@dataclass
class SpawnClosureArtifact:
    """
    Spawn closure artifact — 真实 spawn closure 记录（可落盘）。
    
    核心字段：
    - spawn_id: Spawn closure ID
    - dispatch_id: 来源 dispatch ID
    - registration_id: 来源 registration ID
    - task_id: 来源 task ID
    - spawn_status: ready | skipped | blocked | emitted
    - spawn_reason: spawn/skip/block/emit 的原因
    - spawn_target: spawn 目标（runtime / owner / scenario / task preview）
    - dedupe_key: 去重 key
    - emitted_at: emit 时间戳（如果已 emit）
    - spawn_command: downstream 可消费的 spawn command（可选）
    - spawn_payload: downstream 可消费的 spawn payload（可选）
    - policy_evaluation: policy 评估结果
    - metadata: 额外元数据
    
    这是 canonical artifact，operator/main 可以继续消费。
    """
    spawn_id: str
    dispatch_id: str
    registration_id: str
    task_id: str
    spawn_status: SpawnStatus
    spawn_reason: str
    spawn_target: Dict[str, Any]  # {runtime, owner, scenario, task_preview, cwd}
    dedupe_key: str
    emitted_at: Optional[str] = None
    spawn_command: Optional[str] = None
    spawn_payload: Optional[Dict[str, Any]] = None
    policy_evaluation: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "spawn_version": SPAWN_CLOSURE_VERSION,
            "spawn_id": self.spawn_id,
            "dispatch_id": self.dispatch_id,
            "registration_id": self.registration_id,
            "task_id": self.task_id,
            "spawn_status": self.spawn_status,
            "spawn_reason": self.spawn_reason,
            "spawn_target": self.spawn_target,
            "dedupe_key": self.dedupe_key,
            "emitted_at": self.emitted_at,
            "spawn_command": self.spawn_command,
            "spawn_payload": self.spawn_payload,
            "policy_evaluation": self.policy_evaluation,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SpawnClosureArtifact":
        return cls(
            spawn_id=data.get("spawn_id", ""),
            dispatch_id=data.get("dispatch_id", ""),
            registration_id=data.get("registration_id", ""),
            task_id=data.get("task_id", ""),
            spawn_status=data.get("spawn_status", "blocked"),
            spawn_reason=data.get("spawn_reason", ""),
            spawn_target=data.get("spawn_target", {}),
            dedupe_key=data.get("dedupe_key", ""),
            emitted_at=data.get("emitted_at"),
            spawn_command=data.get("spawn_command"),
            spawn_payload=data.get("spawn_payload"),
            policy_evaluation=data.get("policy_evaluation"),
            metadata=data.get("metadata", {}),
        )
    
    def write(self) -> Path:
        _ensure_spawn_dir()
        spawn_file = _spawn_closure_file(self.spawn_id)
        tmp_file = spawn_file.with_suffix(".tmp")
        with open(tmp_file, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
        tmp_file.replace(spawn_file)
        try:
            from workflow_state_store import get_store
            store = get_store()
            if store.is_active:
                store.update_task(
                    self.task_id,
                    execution_metadata={"spawn_id": self.spawn_id, "dispatch_id": self.dispatch_id},
                )
        except Exception:
            pass
        return spawn_file


class SpawnClosureKernel:
    """
    Spawn closure kernel — 从 dispatch artifact 生成 spawn closure。
    
    提供：
    - evaluate_policy(): 评估 spawn policy
    - create_spawn_closure(): 创建 spawn closure artifact
    - emit_spawn_closure(): emit spawn closure（写入 artifact + 记录 dedupe）
    """
    
    def __init__(self, policy: Optional[SpawnPolicy] = None):
        self.policy = policy or SpawnPolicy()
    
    def evaluate_policy(
        self,
        dispatch: DispatchArtifact,
        existing_spawn: Optional[SpawnClosureArtifact] = None,
    ) -> Dict[str, Any]:
        """
        评估 spawn policy。
        
        Args:
            dispatch: Dispatch artifact
            existing_spawn: 已存在的 spawn closure（用于去重）
        
        Returns:
            {
                "eligible": bool,
                "blocked_reasons": List[str],
                "checks": List[Dict],
            }
        """
        checks: List[Dict[str, Any]] = []
        blocked_reasons: List[str] = []
        
        # Check 1: dispatch status
        dispatch_status_ok = dispatch.dispatch_status == self.policy.require_dispatch_status
        checks.append({
            "name": "dispatch_status",
            "expected": self.policy.require_dispatch_status,
            "actual": dispatch.dispatch_status,
            "passed": dispatch_status_ok,
        })
        if not dispatch_status_ok:
            blocked_reasons.append(
                f"Dispatch status is '{dispatch.dispatch_status}', required '{self.policy.require_dispatch_status}'"
            )
        
        # Check 2: execution_intent required
        has_execution_intent = dispatch.execution_intent is not None
        intent_ok = not self.policy.require_execution_intent or has_execution_intent
        checks.append({
            "name": "execution_intent_required",
            "expected": "present" if self.policy.require_execution_intent else "optional",
            "actual": "present" if has_execution_intent else "missing",
            "passed": intent_ok,
        })
        if not intent_ok:
            blocked_reasons.append("Missing execution_intent")
        
        # Check 3: recommended_spawn in execution_intent
        has_recommended_spawn = False
        if has_execution_intent:
            has_recommended_spawn = "recommended_spawn" in dispatch.execution_intent
        spawn_payload_ok = not self.policy.require_execution_intent or has_recommended_spawn
        checks.append({
            "name": "recommended_spawn_present",
            "expected": "present" if self.policy.require_execution_intent else "optional",
            "actual": "present" if has_recommended_spawn else "missing",
            "passed": spawn_payload_ok,
        })
        if not spawn_payload_ok and self.policy.require_execution_intent:
            blocked_reasons.append("Missing recommended_spawn in execution_intent")
        
        # Check 4: scenario allowlist
        scenario = dispatch.dispatch_target.get("scenario", "")
        scenario_allowed = scenario in self.policy.scenario_allowlist
        checks.append({
            "name": "scenario_allowlist",
            "expected": f"in {self.policy.scenario_allowlist}",
            "actual": scenario,
            "passed": scenario_allowed,
        })
        if not scenario_allowed:
            blocked_reasons.append(f"Scenario '{scenario}' not in allowlist")
        
        # Check 5: duplicate spawn prevention
        duplicate_ok = True
        if self.policy.prevent_duplicate:
            dedupe_key = _generate_dedupe_key(
                dispatch.dispatch_id,
                dispatch.registration_id,
                dispatch.task_id,
            )
            is_duplicate = _is_duplicate_spawn(dedupe_key)
            if is_duplicate:
                duplicate_ok = False
                blocked_reasons.append(f"Duplicate spawn: already spawned for dispatch {dispatch.dispatch_id}")
        
        checks.append({
            "name": "prevent_duplicate_spawn",
            "expected": "no existing spawn",
            "actual": "duplicate_found" if not duplicate_ok else "no_duplicate",
            "passed": duplicate_ok,
        })
        
        return {
            "eligible": len(blocked_reasons) == 0,
            "blocked_reasons": blocked_reasons,
            "checks": checks,
        }
    
    def create_spawn_closure(
        self,
        dispatch: DispatchArtifact,
        policy_evaluation: Dict[str, Any],
    ) -> SpawnClosureArtifact:
        """
        创建 spawn closure artifact。
        
        Args:
            dispatch: Dispatch artifact
            policy_evaluation: Policy evaluation result
        
        Returns:
            SpawnClosureArtifact
        """
        spawn_id = _generate_spawn_id()
        dedupe_key = _generate_dedupe_key(
            dispatch.dispatch_id,
            dispatch.registration_id,
            dispatch.task_id,
        )
        
        # 决定 spawn_status
        if policy_evaluation["eligible"]:
            spawn_status: SpawnStatus = "ready"
            spawn_reason = "Policy evaluation passed"
        elif policy_evaluation["blocked_reasons"]:
            spawn_status = "blocked"
            spawn_reason = "; ".join(policy_evaluation["blocked_reasons"])
        else:
            spawn_status = "skipped"
            spawn_reason = "Not eligible (unknown reason)"
        
        # 构建 spawn_target
        spawn_target = {
            "runtime": "subagent",  # 默认 runtime
            "owner": dispatch.dispatch_target.get("owner", ""),
            "scenario": dispatch.dispatch_target.get("scenario", ""),
            "task_preview": "",
            "cwd": str(Path.home() / ".openclaw" / "workspace"),
        }
        
        # 从 execution_intent 中提取 recommended_spawn
        spawn_command = None
        spawn_payload = None
        if dispatch.execution_intent and "recommended_spawn" in dispatch.execution_intent:
            recommended_spawn = dispatch.execution_intent["recommended_spawn"]
            spawn_target["runtime"] = recommended_spawn.get("runtime", "subagent")
            spawn_target["task_preview"] = recommended_spawn.get("task_preview", "")
            spawn_target["cwd"] = recommended_spawn.get("cwd", spawn_target["cwd"])
            
            # 构建 spawn payload
            spawn_payload = {
                "runtime": spawn_target["runtime"],
                "task": recommended_spawn.get("task", ""),
                "cwd": spawn_target["cwd"],
                "metadata": recommended_spawn.get("metadata", {}),
            }
            
            # 构建 spawn command（downstream 可消费）
            # 当前阶段只输出 intent / command，不真正执行
            spawn_command = self._build_spawn_command(spawn_payload)
        
        artifact = SpawnClosureArtifact(
            spawn_id=spawn_id,
            dispatch_id=dispatch.dispatch_id,
            registration_id=dispatch.registration_id,
            task_id=dispatch.task_id,
            spawn_status=spawn_status,
            spawn_reason=spawn_reason,
            spawn_target=spawn_target,
            dedupe_key=dedupe_key,
            policy_evaluation=policy_evaluation,
            metadata={
                "source_dispatch_status": dispatch.dispatch_status,
                "source_dispatch_time": dispatch.dispatch_time,
                "truth_anchor": dispatch.metadata.get("truth_anchor"),
            },
        )
        
        # 如果 ready，附加 spawn command / payload
        if spawn_status == "ready":
            artifact.spawn_command = spawn_command
            artifact.spawn_payload = spawn_payload
        
        return artifact
    
    def _build_spawn_command(self, spawn_payload: Dict[str, Any]) -> str:
        """
        构建 downstream 可消费的 spawn command。
        
        当前阶段只输出 command string，不真正执行。
        """
        runtime = spawn_payload.get("runtime", "subagent")
        task = spawn_payload.get("task", "")
        cwd = spawn_payload.get("cwd", "")
        metadata = spawn_payload.get("metadata", {})
        
        # 构建 sessions_spawn 风格的 command
        # 这是 downstream 可以直接消费的 spawn command
        cmd_parts = [
            "sessions_spawn(",
            f'    runtime="{runtime}",',
            f'    task="{task[:100]}..."',  # 截断避免过长
            f'    cwd="{cwd}",',
            f'    metadata={json.dumps(metadata)},',
            ")",
        ]
        
        return "\n".join(cmd_parts)
    
    def emit_spawn_closure(
        self,
        dispatch: DispatchArtifact,
        existing_spawn: Optional[SpawnClosureArtifact] = None,
    ) -> SpawnClosureArtifact:
        """
        Emit spawn closure：评估 policy -> 创建 artifact -> 写入文件 -> 记录 dedupe。
        
        Args:
            dispatch: Dispatch artifact
            existing_spawn: 已存在的 spawn closure
        
        Returns:
            SpawnClosureArtifact（已写入文件）
        """
        # 1. Evaluate policy
        policy_evaluation = self.evaluate_policy(dispatch, existing_spawn)
        
        # 2. Create artifact
        artifact = self.create_spawn_closure(dispatch, policy_evaluation)
        
        # 3. Write artifact
        artifact.write()
        
        # 4. Record dedupe（如果 ready）
        if artifact.spawn_status == "ready":
            _record_spawn_dedupe(artifact.dedupe_key, artifact.spawn_id)
            artifact.emitted_at = _iso_now()
            artifact.spawn_status = "emitted"
            # 重新写入更新后的 artifact
            artifact.write()
        
        return artifact


def create_spawn_closure(
    dispatch_id: str,
    policy: Optional[SpawnPolicy] = None,
) -> SpawnClosureArtifact:
    """
    Convenience function: 从 dispatch artifact 创建 spawn closure。
    
    Args:
        dispatch_id: Dispatch ID
        policy: Spawn policy（可选）
    
    Returns:
        SpawnClosureArtifact
    """
    dispatch = get_dispatch(dispatch_id)
    if not dispatch:
        raise ValueError(f"Dispatch {dispatch_id} not found")
    
    kernel = SpawnClosureKernel(policy)
    policy_evaluation = kernel.evaluate_policy(dispatch)
    return kernel.create_spawn_closure(dispatch, policy_evaluation)


def emit_spawn_closure(
    dispatch_id: str,
    policy: Optional[SpawnPolicy] = None,
) -> SpawnClosureArtifact:
    """
    Convenience function: emit spawn closure。
    
    Args:
        dispatch_id: Dispatch ID
        policy: Spawn policy（可选）
    
    Returns:
        SpawnClosureArtifact（已写入文件）
    """
    dispatch = get_dispatch(dispatch_id)
    if not dispatch:
        raise ValueError(f"Dispatch {dispatch_id} not found")
    
    kernel = SpawnClosureKernel(policy)
    return kernel.emit_spawn_closure(dispatch)


def list_spawn_closures(
    dispatch_id: Optional[str] = None,
    registration_id: Optional[str] = None,
    task_id: Optional[str] = None,
    spawn_status: Optional[str] = None,
    limit: int = 100,
) -> List[SpawnClosureArtifact]:
    """
    列出 spawn closure artifacts。
    
    Args:
        dispatch_id: 按 dispatch_id 过滤
        registration_id: 按 registration_id 过滤
        task_id: 按 task_id 过滤
        spawn_status: 按 spawn_status 过滤
        limit: 最大返回数量
    
    Returns:
        SpawnClosureArtifact 列表
    """
    _ensure_spawn_dir()
    
    spawns = []
    for spawn_file in SPAWN_CLOSURE_DIR.glob("*.json"):
        if spawn_file.name == "spawn_index.json":
            continue
        
        try:
            with open(spawn_file, "r") as f:
                data = json.load(f)
            artifact = SpawnClosureArtifact.from_dict(data)
            
            # 过滤
            if dispatch_id and artifact.dispatch_id != dispatch_id:
                continue
            if registration_id and artifact.registration_id != registration_id:
                continue
            if task_id and artifact.task_id != task_id:
                continue
            if spawn_status and artifact.spawn_status != spawn_status:
                continue
            
            spawns.append(artifact)
        except (json.JSONDecodeError, KeyError):
            pass
    
    # 按 spawn_id 排序
    spawns.sort(key=lambda s: s.spawn_id)
    
    return spawns[:limit]


def get_spawn_closure(spawn_id: str) -> Optional[SpawnClosureArtifact]:
    """
    获取 spawn closure artifact。
    
    Args:
        spawn_id: Spawn ID
    
    Returns:
        SpawnClosureArtifact，不存在则返回 None
    """
    spawn_file = _spawn_closure_file(spawn_id)
    if not spawn_file.exists():
        return None
    
    with open(spawn_file, "r") as f:
        data = json.load(f)
    
    return SpawnClosureArtifact.from_dict(data)


# ============ Trading 场景特定 helper ============

def create_trading_spawn_closure(
    dispatch_id: str,
    *,
    policy: Optional[SpawnPolicy] = None,
) -> SpawnClosureArtifact:
    """
    Trading 场景特定的 spawn closure 创建。
    
    这是 trading_roundtable_phase1 场景的 convenience function。
    """
    # 使用 trading 特定的 policy（白名单包含 trading_roundtable_phase1）
    if policy is None:
        policy = SpawnPolicy(
            scenario_allowlist=["trading_roundtable_phase1"],
            require_dispatch_status="dispatched",
            require_execution_intent=True,
            prevent_duplicate=True,
            allow_limited_emission=True,
        )
    
    return emit_spawn_closure(dispatch_id, policy)


# CLI 入口
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python spawn_closure.py create <dispatch_id>")
        print("  python spawn_closure.py emit <dispatch_id>")
        print("  python spawn_closure.py list [--status <status>] [--dispatch <dispatch_id>]")
        print("  python spawn_closure.py get <spawn_id>")
        print("  python spawn_closure.py trading <dispatch_id>")
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == "create":
        if len(sys.argv) < 3:
            print("Error: missing dispatch_id")
            sys.exit(1)
        
        dispatch_id = sys.argv[2]
        artifact = create_spawn_closure(dispatch_id)
        print(json.dumps(artifact.to_dict(), indent=2))
        print(f"\nSpawn closure artifact written to: {_spawn_closure_file(artifact.spawn_id)}")
    
    elif cmd == "emit":
        if len(sys.argv) < 3:
            print("Error: missing dispatch_id")
            sys.exit(1)
        
        dispatch_id = sys.argv[2]
        artifact = emit_spawn_closure(dispatch_id)
        print(json.dumps(artifact.to_dict(), indent=2))
        print(f"\nSpawn closure artifact written to: {_spawn_closure_file(artifact.spawn_id)}")
        if artifact.spawn_status == "emitted":
            print(f"\nSpawn command (downstream consumable):")
            print(artifact.spawn_command)
    
    elif cmd == "list":
        status = None
        dispatch_id = None
        if "--status" in sys.argv:
            idx = sys.argv.index("--status")
            if idx + 1 < len(sys.argv):
                status = sys.argv[idx + 1]
        if "--dispatch" in sys.argv:
            idx = sys.argv.index("--dispatch")
            if idx + 1 < len(sys.argv):
                dispatch_id = sys.argv[idx + 1]
        
        spawns = list_spawn_closures(
            dispatch_id=dispatch_id,
            spawn_status=status,
        )
        print(json.dumps([s.to_dict() for s in spawns], indent=2))
    
    elif cmd == "get":
        if len(sys.argv) < 3:
            print("Error: missing spawn_id")
            sys.exit(1)
        
        spawn_id = sys.argv[2]
        artifact = get_spawn_closure(spawn_id)
        if artifact:
            print(json.dumps(artifact.to_dict(), indent=2))
        else:
            print(f"Spawn closure {spawn_id} not found")
            sys.exit(1)
    
    elif cmd == "trading":
        if len(sys.argv) < 3:
            print("Error: missing dispatch_id")
            sys.exit(1)
        
        dispatch_id = sys.argv[2]
        artifact = create_trading_spawn_closure(dispatch_id)
        print(json.dumps(artifact.to_dict(), indent=2))
        print(f"\nSpawn closure artifact written to: {_spawn_closure_file(artifact.spawn_id)}")
        if artifact.spawn_status == "emitted":
            print(f"\nTrading spawn command:")
            print(artifact.spawn_command)
    
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
