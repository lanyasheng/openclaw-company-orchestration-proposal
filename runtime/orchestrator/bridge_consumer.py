#!/usr/bin/env python3
"""
bridge_consumer.py — Universal Partial-Completion Continuation Framework v7

目标：实现 **bridge consumer**，消费 V6 生成的 sessions_spawn request artifact。

核心能力：
1. 读取 V6 的 sessions_spawn request artifact
2. 生成 canonical bridge-consumed artifact / execution envelope
3. 明确状态：consumed | skipped | blocked | failed
4. 包含 linkage：request_id / dispatch_id / spawn_id / source task_id
5. 提供 CLI / helper 对单个 request 执行"consume"动作

当前阶段：bridge consumption layer（V7 新增）

这是 v7 新增模块，通用 kernel，trading 仅作为首个消费者/样例。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from sessions_spawn_request import (
    SessionsSpawnRequest,
    SpawnRequestStatus,
    get_spawn_request,
    list_spawn_requests,
    SPAWN_REQUEST_DIR,
    REQUEST_VERSION,
)

__all__ = [
    "BridgeConsumerStatus",
    "BridgeConsumedArtifact",
    "BridgeConsumerPolicy",
    "BridgeConsumer",
    "consume_request",
    "list_consumed_artifacts",
    "get_consumed_artifact",
    "CONSUMED_VERSION",
]

CONSUMED_VERSION = "bridge_consumed_v1"

BridgeConsumerStatus = Literal["consumed", "skipped", "blocked", "failed"]

# Bridge consumed artifacts 存储目录
BRIDGE_CONSUMED_DIR = Path(
    os.environ.get(
        "OPENCLAW_BRIDGE_CONSUMED_DIR",
        Path.home() / ".openclaw" / "shared-context" / "bridge_consumed",
    )
)

# Request -> Consumed artifact 映射索引文件
CONSUMED_INDEX_FILE = BRIDGE_CONSUMED_DIR / "consumed_index.json"


def _ensure_consumed_dir():
    """确保 bridge consumed 目录存在"""
    BRIDGE_CONSUMED_DIR.mkdir(parents=True, exist_ok=True)


def _consumed_artifact_file(consumed_id: str) -> Path:
    """返回 consumed artifact 文件路径"""
    return BRIDGE_CONSUMED_DIR / f"{consumed_id}.json"


def _iso_now() -> str:
    """返回当前 ISO-8601 时间戳"""
    return datetime.now().isoformat()


def _generate_consumed_id() -> str:
    """生成稳定 consumed ID"""
    import uuid
    return f"consumed_{uuid.uuid4().hex[:12]}"


def _generate_consumed_dedupe_key(request_id: str) -> str:
    """
    生成 consumed 去重 key。
    
    规则：同一 request 不重复消费。
    """
    return f"consumed_dedupe:{request_id}"


def _load_consumed_index() -> Dict[str, str]:
    """
    加载 consumed index（request_id -> consumed_id 映射）。
    
    用于去重检查。
    """
    _ensure_consumed_dir()
    if not CONSUMED_INDEX_FILE.exists():
        return {}
    
    try:
        with open(CONSUMED_INDEX_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, KeyError):
        return {}


def _save_consumed_index(index: Dict[str, str]):
    """保存 consumed index"""
    _ensure_consumed_dir()
    tmp_file = CONSUMED_INDEX_FILE.with_suffix(".tmp")
    with open(tmp_file, "w") as f:
        json.dump(index, f, indent=2)
    tmp_file.replace(CONSUMED_INDEX_FILE)


def _record_consumed_dedupe(request_id: str, consumed_id: str):
    """记录 consumed dedupe（防止重复消费）"""
    index = _load_consumed_index()
    index[request_id] = consumed_id
    _save_consumed_index(index)


def _is_already_consumed(request_id: str) -> bool:
    """检查是否已存在 consumed artifact（去重）"""
    index = _load_consumed_index()
    return request_id in index


def _get_consumed_id_by_request(request_id: str) -> Optional[str]:
    """通过 request_id 获取 consumed_id"""
    index = _load_consumed_index()
    return index.get(request_id)


@dataclass
class BridgeConsumerPolicy:
    """
    Bridge consumer policy — 评估是否可消费 request。
    
    核心字段：
    - require_request_status: 要求的 request status（默认 prepared）
    - prevent_duplicate: 是否防止重复消费（默认 True）
    - simulate_only: 是否仅模拟消费（默认 True，不真正调用 sessions_spawn）
    - require_metadata_fields: 要求的 metadata 字段列表
    
    这是通用 policy，不绑定特定场景。
    """
    require_request_status: str = "prepared"
    prevent_duplicate: bool = True
    simulate_only: bool = True
    require_metadata_fields: List[str] = field(default_factory=lambda: ["dispatch_id", "spawn_id"])
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "require_request_status": self.require_request_status,
            "prevent_duplicate": self.prevent_duplicate,
            "simulate_only": self.simulate_only,
            "require_metadata_fields": self.require_metadata_fields,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BridgeConsumerPolicy":
        return cls(
            require_request_status=data.get("require_request_status", "prepared"),
            prevent_duplicate=data.get("prevent_duplicate", True),
            simulate_only=data.get("simulate_only", True),
            require_metadata_fields=data.get("require_metadata_fields", ["dispatch_id", "spawn_id"]),
        )


@dataclass
class BridgeConsumedArtifact:
    """
    Bridge consumed artifact — V7 桥接层消费后的执行 envelope。
    
    核心字段：
    - consumed_id: Consumed artifact ID
    - source_request_id: 来源 sessions_spawn request ID
    - source_receipt_id: 来源 completion receipt ID
    - source_execution_id: 来源 spawn execution ID
    - source_spawn_id: 来源 spawn closure ID
    - source_dispatch_id: 来源 dispatch ID
    - source_registration_id: 来源 registration ID
    - source_task_id: 来源 task ID
    - consumer_status: consumed | skipped | blocked | failed
    - consumer_reason: 消费/跳过/阻塞/失败的原因
    - consumer_time: 消费时间戳
    - execution_envelope: 执行 envelope（包含 sessions_spawn 参数 + 执行上下文）
    - dedupe_key: 去重 key
    - policy_evaluation: policy 评估结果
    - metadata: 额外元数据（adapter-agnostic）
    
    这是 canonical consumed artifact，标志 request 已被 bridge 层消费。
    """
    consumed_id: str
    source_request_id: str
    source_receipt_id: str
    source_execution_id: str
    source_spawn_id: str
    source_dispatch_id: str
    source_registration_id: str
    source_task_id: str
    consumer_status: BridgeConsumerStatus
    consumer_reason: str
    consumer_time: str
    execution_envelope: Dict[str, Any]  # {sessions_spawn_params, execution_context, ...}
    dedupe_key: str
    policy_evaluation: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "consumed_version": CONSUMED_VERSION,
            "consumed_id": self.consumed_id,
            "source_request_id": self.source_request_id,
            "source_receipt_id": self.source_receipt_id,
            "source_execution_id": self.source_execution_id,
            "source_spawn_id": self.source_spawn_id,
            "source_dispatch_id": self.source_dispatch_id,
            "source_registration_id": self.source_registration_id,
            "source_task_id": self.source_task_id,
            "consumer_status": self.consumer_status,
            "consumer_reason": self.consumer_reason,
            "consumer_time": self.consumer_time,
            "execution_envelope": self.execution_envelope,
            "dedupe_key": self.dedupe_key,
            "policy_evaluation": self.policy_evaluation,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BridgeConsumedArtifact":
        return cls(
            consumed_id=data.get("consumed_id", ""),
            source_request_id=data.get("source_request_id", ""),
            source_receipt_id=data.get("source_receipt_id", ""),
            source_execution_id=data.get("source_execution_id", ""),
            source_spawn_id=data.get("source_spawn_id", ""),
            source_dispatch_id=data.get("source_dispatch_id", ""),
            source_registration_id=data.get("source_registration_id", ""),
            source_task_id=data.get("source_task_id", ""),
            consumer_status=data.get("consumer_status", "blocked"),
            consumer_reason=data.get("consumer_reason", ""),
            consumer_time=data.get("consumer_time", ""),
            execution_envelope=data.get("execution_envelope", {}),
            dedupe_key=data.get("dedupe_key", ""),
            policy_evaluation=data.get("policy_evaluation"),
            metadata=data.get("metadata", {}),
        )
    
    def write(self) -> Path:
        """写入 consumed artifact 到文件"""
        _ensure_consumed_dir()
        artifact_file = _consumed_artifact_file(self.consumed_id)
        tmp_file = artifact_file.with_suffix(".tmp")
        with open(tmp_file, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
        tmp_file.replace(artifact_file)
        return artifact_file
    
    def get_linkage(self) -> Dict[str, str]:
        """返回完整 linkage 字典"""
        return {
            "consumed_id": self.consumed_id,
            "request_id": self.source_request_id,
            "receipt_id": self.source_receipt_id,
            "execution_id": self.source_execution_id,
            "spawn_id": self.source_spawn_id,
            "dispatch_id": self.source_dispatch_id,
            "registration_id": self.source_registration_id,
            "task_id": self.source_task_id,
        }


class BridgeConsumer:
    """
    Bridge consumer — 消费 sessions_spawn request，生成 consumed artifact。
    
    提供：
    - evaluate_policy(): 评估消费 policy
    - build_execution_envelope(): 构建执行 envelope
    - consume(): 消费 request（评估 -> 构建 -> 写入）
    """
    
    def __init__(self, policy: Optional[BridgeConsumerPolicy] = None):
        self.policy = policy or BridgeConsumerPolicy()
    
    def evaluate_policy(
        self,
        request: SessionsSpawnRequest,
        existing_consumed: Optional[BridgeConsumedArtifact] = None,
    ) -> Dict[str, Any]:
        """
        评估消费 policy。
        
        Args:
            request: Sessions spawn request artifact
            existing_consumed: 已存在的 consumed artifact（用于去重）
        
        Returns:
            {
                "eligible": bool,
                "blocked_reasons": List[str],
                "checks": List[Dict],
            }
        """
        checks: List[Dict[str, Any]] = []
        blocked_reasons: List[str] = []
        
        # Check 1: request status
        request_status_ok = request.spawn_request_status == self.policy.require_request_status
        checks.append({
            "name": "request_status",
            "expected": self.policy.require_request_status,
            "actual": request.spawn_request_status,
            "passed": request_status_ok,
        })
        if not request_status_ok:
            blocked_reasons.append(
                f"Request status is '{request.spawn_request_status}', required '{self.policy.require_request_status}'"
            )
        
        # Check 2: duplicate consumption prevention
        duplicate_ok = True
        if self.policy.prevent_duplicate:
            is_duplicate = _is_already_consumed(request.request_id)
            if is_duplicate:
                duplicate_ok = False
                blocked_reasons.append(
                    f"Duplicate consumption: request {request.request_id} already consumed"
                )
        
        checks.append({
            "name": "prevent_duplicate_consumption",
            "expected": "no existing consumed artifact",
            "actual": "duplicate_found" if not duplicate_ok else "no_duplicate",
            "passed": duplicate_ok,
        })
        
        # Check 3: required metadata fields
        metadata = request.sessions_spawn_params.get("metadata", {})
        missing_fields = []
        for field_name in self.policy.require_metadata_fields:
            if field_name not in metadata:
                missing_fields.append(field_name)
        
        metadata_ok = len(missing_fields) == 0
        checks.append({
            "name": "required_metadata_fields",
            "expected": self.policy.require_metadata_fields,
            "actual": "missing: " + ", ".join(missing_fields) if missing_fields else "all present",
            "passed": metadata_ok,
        })
        if not metadata_ok:
            blocked_reasons.append(f"Missing required metadata fields: {', '.join(missing_fields)}")
        
        # Check 4: sessions_spawn_params has task
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
        
        return {
            "eligible": len(blocked_reasons) == 0,
            "blocked_reasons": blocked_reasons,
            "checks": checks,
        }
    
    def build_execution_envelope(
        self,
        request: SessionsSpawnRequest,
    ) -> Dict[str, Any]:
        """
        从 request 构建执行 envelope。
        
        这是通用构建逻辑，不绑定特定场景。
        """
        # 提取 sessions_spawn 参数
        spawn_params = request.sessions_spawn_params.copy()
        
        # 构建执行上下文
        execution_context = {
            "request_id": request.request_id,
            "receipt_id": request.source_receipt_id,
            "execution_id": request.source_execution_id,
            "spawn_id": request.source_spawn_id,
            "dispatch_id": request.source_dispatch_id,
            "registration_id": request.source_registration_id,
            "task_id": request.source_task_id,
            "scenario": request.metadata.get("scenario", "generic"),
            "owner": request.metadata.get("owner", ""),
            "truth_anchor": request.metadata.get("truth_anchor"),
        }
        
        # 构建执行 envelope
        envelope = {
            "sessions_spawn_params": spawn_params,
            "execution_context": execution_context,
            "consume_mode": "simulate" if self.policy.simulate_only else "execute",
            "ready_for_dispatch": not self.policy.simulate_only,
        }
        
        # 如果 request 包含 business_context，添加到 envelope
        if "business_context" in spawn_params.get("metadata", {}):
            envelope["business_context"] = spawn_params["metadata"]["business_context"]
        
        return envelope
    
    def consume(
        self,
        request: SessionsSpawnRequest,
    ) -> BridgeConsumedArtifact:
        """
        Consume request：评估 policy -> 构建 envelope -> 写入 artifact -> 记录 dedupe。
        
        Args:
            request: Sessions spawn request artifact
        
        Returns:
            BridgeConsumedArtifact（已写入文件）
        """
        # 1. Evaluate policy
        policy_evaluation = self.evaluate_policy(request)
        
        # 2. 决定 consumer_status
        if policy_evaluation["eligible"]:
            status: BridgeConsumerStatus = "consumed"
            reason = "Policy evaluation passed; request consumed (execution envelope prepared)"
        elif policy_evaluation["blocked_reasons"]:
            status = "blocked"
            reason = "; ".join(policy_evaluation["blocked_reasons"])
        else:
            status = "failed"
            reason = "Not eligible (unknown reason)"
        
        # 3. 构建 execution envelope
        execution_envelope = self.build_execution_envelope(request)
        
        # 4. 生成 consumed artifact
        consumed_id = _generate_consumed_id()
        dedupe_key = _generate_consumed_dedupe_key(request.request_id)
        
        artifact = BridgeConsumedArtifact(
            consumed_id=consumed_id,
            source_request_id=request.request_id,
            source_receipt_id=request.source_receipt_id,
            source_execution_id=request.source_execution_id,
            source_spawn_id=request.source_spawn_id,
            source_dispatch_id=request.source_dispatch_id,
            source_registration_id=request.source_registration_id,
            source_task_id=request.source_task_id,
            consumer_status=status,
            consumer_reason=reason,
            consumer_time=_iso_now(),
            execution_envelope=execution_envelope,
            dedupe_key=dedupe_key,
            policy_evaluation=policy_evaluation,
            metadata={
                "source_request_status": request.spawn_request_status,
                "source_request_time": request.spawn_request_time,
                "scenario": request.metadata.get("scenario", ""),
                "owner": request.metadata.get("owner", ""),
                "truth_anchor": request.metadata.get("truth_anchor"),
            },
        )
        
        # 5. Write artifact
        artifact.write()
        
        # 6. Record dedupe（如果 consumed）
        if artifact.consumer_status == "consumed":
            _record_consumed_dedupe(request.request_id, consumed_id)
        
        return artifact


def consume_request(
    request_id: str,
    policy: Optional[BridgeConsumerPolicy] = None,
) -> BridgeConsumedArtifact:
    """
    Convenience function: 消费单个 sessions_spawn request。
    
    Args:
        request_id: Request ID
        policy: Consumer policy（可选）
    
    Returns:
        BridgeConsumedArtifact（已写入文件）
    
    Raises:
        ValueError: 如果 request 不存在
    """
    request = get_spawn_request(request_id)
    if not request:
        raise ValueError(f"Spawn request {request_id} not found")
    
    # 检查是否已消费
    if _is_already_consumed(request_id):
        consumed_id = _get_consumed_id_by_request(request_id)
        existing = get_consumed_artifact(consumed_id)
        if existing:
            return existing
    
    consumer = BridgeConsumer(policy)
    return consumer.consume(request)


def list_consumed_artifacts(
    request_id: Optional[str] = None,
    receipt_id: Optional[str] = None,
    task_id: Optional[str] = None,
    dispatch_id: Optional[str] = None,
    consumer_status: Optional[str] = None,
    scenario: Optional[str] = None,
    limit: int = 100,
) -> List[BridgeConsumedArtifact]:
    """
    列出 consumed artifacts。
    
    Args:
        request_id: 按 request_id 过滤
        receipt_id: 按 receipt_id 过滤
        task_id: 按 task_id 过滤
        dispatch_id: 按 dispatch_id 过滤
        consumer_status: 按 consumer_status 过滤
        scenario: 按 scenario 过滤
        limit: 最大返回数量
    
    Returns:
        BridgeConsumedArtifact 列表
    """
    _ensure_consumed_dir()
    
    artifacts = []
    for artifact_file in BRIDGE_CONSUMED_DIR.glob("*.json"):
        if artifact_file.name == "consumed_index.json":
            continue
        
        try:
            with open(artifact_file, "r") as f:
                data = json.load(f)
            artifact = BridgeConsumedArtifact.from_dict(data)
            
            # 过滤
            if request_id and artifact.source_request_id != request_id:
                continue
            if receipt_id and artifact.source_receipt_id != receipt_id:
                continue
            if task_id and artifact.source_task_id != task_id:
                continue
            if dispatch_id and artifact.source_dispatch_id != dispatch_id:
                continue
            if consumer_status and artifact.consumer_status != consumer_status:
                continue
            if scenario and artifact.metadata.get("scenario") != scenario:
                continue
            
            artifacts.append(artifact)
        except (json.JSONDecodeError, KeyError):
            pass
    
    # 按 consumed_id 排序
    artifacts.sort(key=lambda a: a.consumed_id)
    
    return artifacts[:limit]


def get_consumed_artifact(consumed_id: str) -> Optional[BridgeConsumedArtifact]:
    """
    获取 consumed artifact。
    
    Args:
        consumed_id: Consumed ID
    
    Returns:
        BridgeConsumedArtifact，不存在则返回 None
    """
    artifact_file = _consumed_artifact_file(consumed_id)
    if not artifact_file.exists():
        return None
    
    with open(artifact_file, "r") as f:
        data = json.load(f)
    
    return BridgeConsumedArtifact.from_dict(data)


def get_consumed_by_request(request_id: str) -> Optional[BridgeConsumedArtifact]:
    """
    通过 request_id 获取 consumed artifact。
    
    Args:
        request_id: Request ID
    
    Returns:
        BridgeConsumedArtifact，不存在则返回 None
    """
    consumed_id = _get_consumed_id_by_request(request_id)
    if not consumed_id:
        return None
    return get_consumed_artifact(consumed_id)


def build_consumption_summary(
    scenario: Optional[str] = None,
) -> Dict[str, Any]:
    """
    构建消费 summary。
    
    Args:
        scenario: 按 scenario 过滤（可选）
    
    Returns:
        {
            "total_consumed": int,
            "by_status": {status: count},
            "by_scenario": {scenario: count},
            "recent_consumed": List[Dict],
        }
    """
    artifacts = list_consumed_artifacts(scenario=scenario, limit=1000)
    
    by_status: Dict[str, int] = {}
    by_scenario: Dict[str, int] = {}
    recent: List[Dict[str, Any]] = []
    
    for artifact in artifacts:
        # By status
        status = artifact.consumer_status
        by_status[status] = by_status.get(status, 0) + 1
        
        # By scenario
        scenario_name = artifact.metadata.get("scenario", "unknown")
        by_scenario[scenario_name] = by_scenario.get(scenario_name, 0) + 1
        
        # Recent (last 10)
        if len(recent) < 10:
            recent.append({
                "consumed_id": artifact.consumed_id,
                "request_id": artifact.source_request_id,
                "task_id": artifact.source_task_id,
                "status": artifact.consumer_status,
                "scenario": scenario_name,
                "time": artifact.consumer_time,
            })
    
    return {
        "total_consumed": len(artifacts),
        "by_status": by_status,
        "by_scenario": by_scenario,
        "recent_consumed": recent,
    }


# CLI 入口
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python bridge_consumer.py consume <request_id>")
        print("  python bridge_consumer.py list [--status <status>] [--scenario <scenario>]")
        print("  python bridge_consumer.py get <consumed_id>")
        print("  python bridge_consumer.py by-request <request_id>")
        print("  python bridge_consumer.py summary [--scenario <scenario>]")
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == "consume":
        if len(sys.argv) < 3:
            print("Error: missing request_id")
            sys.exit(1)
        
        request_id = sys.argv[2]
        try:
            artifact = consume_request(request_id)
            print(json.dumps(artifact.to_dict(), indent=2))
            print(f"\nConsumed artifact written to: {_consumed_artifact_file(artifact.consumed_id)}")
            if artifact.consumer_status == "consumed":
                print(f"\nExecution envelope:")
                print(json.dumps(artifact.execution_envelope, indent=2))
        except ValueError as e:
            print(f"Error: {e}")
            sys.exit(1)
    
    elif cmd == "list":
        status = None
        scenario = None
        if "--status" in sys.argv:
            idx = sys.argv.index("--status")
            if idx + 1 < len(sys.argv):
                status = sys.argv[idx + 1]
        if "--scenario" in sys.argv:
            idx = sys.argv.index("--scenario")
            if idx + 1 < len(sys.argv):
                scenario = sys.argv[idx + 1]
        
        artifacts = list_consumed_artifacts(
            consumer_status=status,
            scenario=scenario,
        )
        print(json.dumps([a.to_dict() for a in artifacts], indent=2))
    
    elif cmd == "get":
        if len(sys.argv) < 3:
            print("Error: missing consumed_id")
            sys.exit(1)
        
        consumed_id = sys.argv[2]
        artifact = get_consumed_artifact(consumed_id)
        if artifact:
            print(json.dumps(artifact.to_dict(), indent=2))
        else:
            print(f"Consumed artifact {consumed_id} not found")
            sys.exit(1)
    
    elif cmd == "by-request":
        if len(sys.argv) < 3:
            print("Error: missing request_id")
            sys.exit(1)
        
        request_id = sys.argv[2]
        artifact = get_consumed_by_request(request_id)
        if artifact:
            print(json.dumps(artifact.to_dict(), indent=2))
        else:
            print(f"No consumed artifact found for request {request_id}")
            sys.exit(1)
    
    elif cmd == "summary":
        scenario = None
        if "--scenario" in sys.argv:
            idx = sys.argv.index("--scenario")
            if idx + 1 < len(sys.argv):
                scenario = sys.argv[idx + 1]
        
        summary = build_consumption_summary(scenario=scenario)
        print(json.dumps(summary, indent=2))
    
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
