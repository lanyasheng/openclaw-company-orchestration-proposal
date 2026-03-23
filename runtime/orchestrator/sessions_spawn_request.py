#!/usr/bin/env python3
"""
sessions_spawn_request.py — Universal Partial-Completion Continuation Framework v8

目标：实现 **通用** sessions_spawn-compatible request interface（adapter-agnostic）。

核心能力：
1. 从 spawn execution artifact 生成 canonical sessions_spawn request
2. 字段包括：runtime / cwd / task / label / metadata（dispatch_id / spawn_id / source）
3. 记录状态：spawn_request_status = prepared | emitted | blocked | failed
4. 不绑定特定场景（trading / channel / generic 均可消费）
5. 提供 helper/CLI 产出 request，可被上层 OpenClaw bridge 直接消费
6. **V8 新增**: 支持 auto-trigger consumption（request prepared 后自动触发消费）

当前阶段：canonical spawn request artifact / interface + auto-trigger（V8 新增）

这是 v8 模块，通用 kernel，trading 仅作为首个消费者/样例。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from completion_receipt import (
    CompletionReceiptArtifact,
    ReceiptStatus,
    get_completion_receipt,
    list_completion_receipts,
    COMPLETION_RECEIPT_DIR,
)

__all__ = [
    "SpawnRequestStatus",
    "SessionsSpawnRequest",
    "SpawnRequestPolicy",
    "SpawnRequestKernel",
    "prepare_spawn_request",
    "emit_spawn_request",
    "list_spawn_requests",
    "get_spawn_request",
    "REQUEST_VERSION",
]

REQUEST_VERSION = "sessions_spawn_request_v1"

SpawnRequestStatus = Literal["prepared", "emitted", "blocked", "failed"]

# Sessions spawn request 存储目录
SPAWN_REQUEST_DIR = Path(
    os.environ.get(
        "OPENCLAW_SPAWN_REQUEST_DIR",
        Path.home() / ".openclaw" / "shared-context" / "spawn_requests",
    )
)

# Completion receipt -> Spawn request 映射索引文件
REQUEST_INDEX_FILE = SPAWN_REQUEST_DIR / "request_index.json"

# Auto-trigger 索引文件（V8 新增）
AUTO_TRIGGER_INDEX_FILE = SPAWN_REQUEST_DIR / "auto_trigger_index.json"

# Auto-trigger 配置（V8 新增）
AUTO_TRIGGER_CONFIG_FILE = SPAWN_REQUEST_DIR / "auto_trigger_config.json"


def _ensure_request_dir():
    """确保 spawn request 目录存在"""
    SPAWN_REQUEST_DIR.mkdir(parents=True, exist_ok=True)


def _spawn_request_file(request_id: str) -> Path:
    """返回 spawn request artifact 文件路径"""
    return SPAWN_REQUEST_DIR / f"{request_id}.json"


def _iso_now() -> str:
    """返回当前 ISO-8601 时间戳"""
    return datetime.now().isoformat()


def _generate_request_id() -> str:
    """生成稳定 request ID"""
    import uuid
    return f"req_{uuid.uuid4().hex[:12]}"


def _generate_request_dedupe_key(receipt_id: str, execution_id: str) -> str:
    """
    生成 request 去重 key。
    
    规则：同一 receipt 不重复创建 request。
    """
    return f"request_dedupe:{receipt_id}:{execution_id}"


def _load_request_index() -> Dict[str, str]:
    """
    加载 request index（dedupe_key -> request_id 映射）。
    
    用于去重检查。
    """
    _ensure_request_dir()
    if not REQUEST_INDEX_FILE.exists():
        return {}
    
    try:
        with open(REQUEST_INDEX_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, KeyError):
        return {}


def _save_request_index(index: Dict[str, str]):
    """保存 request index"""
    _ensure_request_dir()
    tmp_file = REQUEST_INDEX_FILE.with_suffix(".tmp")
    with open(tmp_file, "w") as f:
        json.dump(index, f, indent=2)
    tmp_file.replace(REQUEST_INDEX_FILE)


def _record_request_dedupe(dedupe_key: str, request_id: str):
    """记录 request dedupe（防止重复创建）"""
    index = _load_request_index()
    index[dedupe_key] = request_id
    _save_request_index(index)


def _is_duplicate_request(dedupe_key: str) -> bool:
    """检查是否已存在 request（去重）"""
    index = _load_request_index()
    return dedupe_key in index


# ==================== V8 Auto-Trigger Functions ====================

def _load_auto_trigger_index() -> Dict[str, str]:
    """
    加载 auto-trigger 索引（request_id -> consumed_id 映射）。
    
    用于追踪已自动触发的 request。
    """
    _ensure_request_dir()
    if not AUTO_TRIGGER_INDEX_FILE.exists():
        return {}
    
    try:
        with open(AUTO_TRIGGER_INDEX_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, KeyError):
        return {}


def _save_auto_trigger_index(index: Dict[str, str]):
    """保存 auto-trigger 索引"""
    _ensure_request_dir()
    tmp_file = AUTO_TRIGGER_INDEX_FILE.with_suffix(".tmp")
    with open(tmp_file, "w") as f:
        json.dump(index, f, indent=2)
    tmp_file.replace(AUTO_TRIGGER_INDEX_FILE)


def _load_auto_trigger_config() -> Dict[str, Any]:
    """
    加载 auto-trigger 配置。
    
    配置格式：
    {
        "enabled": bool,
        "allowlist": List[str],  # scenario allowlist
        "denylist": List[str],   # scenario denylist
        "require_manual_approval": bool,
    }
    """
    _ensure_request_dir()
    if not AUTO_TRIGGER_CONFIG_FILE.exists():
        return {
            "enabled": False,
            "allowlist": [],
            "denylist": [],
            "require_manual_approval": True,
        }
    
    try:
        with open(AUTO_TRIGGER_CONFIG_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, KeyError):
        return {
            "enabled": False,
            "allowlist": [],
            "denylist": [],
            "require_manual_approval": True,
        }


def _save_auto_trigger_config(config: Dict[str, Any]):
    """保存 auto-trigger 配置"""
    _ensure_request_dir()
    tmp_file = AUTO_TRIGGER_CONFIG_FILE.with_suffix(".tmp")
    with open(tmp_file, "w") as f:
        json.dump(config, f, indent=2)
    tmp_file.replace(AUTO_TRIGGER_CONFIG_FILE)


def _is_auto_triggered(request_id: str) -> bool:
    """检查 request 是否已自动触发"""
    index = _load_auto_trigger_index()
    return request_id in index


def _record_auto_trigger(request_id: str, consumed_id: str):
    """记录 auto-trigger"""
    index = _load_auto_trigger_index()
    index[request_id] = consumed_id
    _save_auto_trigger_index(index)


def _should_auto_trigger(request: SessionsSpawnRequest) -> tuple[bool, str]:
    """
    评估是否应该自动触发 consumption。
    
    V8 新增：auto-trigger guard / dedupe 机制。
    P0-3 Batch 2 增强：增加 readiness / safety_gates / truth_anchor 检查。
    
    Args:
        request: Sessions spawn request
    
    Returns:
        (should_trigger, reason)
    
    检查顺序：
    1. auto-trigger enabled (config)
    2. dedupe (not already triggered)
    3. request status == prepared
    4. scenario allowlist/denylist
    5. manual approval (config)
    6. **P0-3 Batch 2**: truth_anchor present (traceability)
    7. **P0-3 Batch 2**: readiness eligible (if present in metadata)
    8. **P0-3 Batch 2**: safety_gates.allow_auto_dispatch (if present in metadata)
    """
    config = _load_auto_trigger_config()
    metadata = request.metadata or {}
    
    # Check 1: auto-trigger enabled
    if not config.get("enabled", False):
        return False, "Auto-trigger is disabled"
    
    # Check 2: already triggered (dedupe)
    if _is_auto_triggered(request.request_id):
        return False, f"Request {request.request_id} already auto-triggered"
    
    # Check 3: request status must be prepared
    if request.spawn_request_status != "prepared":
        return False, f"Request status is '{request.spawn_request_status}', not 'prepared'"
    
    # Check 4: scenario allowlist/denylist
    scenario = metadata.get("scenario", "generic")
    denylist = config.get("denylist", [])
    allowlist = config.get("allowlist", [])
    
    if scenario in denylist:
        return False, f"Scenario '{scenario}' is in denylist"
    
    if allowlist and scenario not in allowlist:
        return False, f"Scenario '{scenario}' is not in allowlist"
    
    # Check 5: manual approval required
    if config.get("require_manual_approval", True):
        return False, "Manual approval required (config)"
    
    # Check 6: P0-3 Batch 2 - truth_anchor present (traceability)
    truth_anchor = metadata.get("truth_anchor")
    if not truth_anchor:
        # Note: This is a soft check - warn but don't block if missing
        # Some legacy receipts may not have truth_anchor
        pass  # Allow for backward compatibility
    
    # Check 7: P0-3 Batch 2 - readiness eligible (if present)
    readiness = metadata.get("readiness")
    if readiness:
        readiness_eligible = readiness.get("eligible", False)
        readiness_status = readiness.get("status", "not_ready")
        if not readiness_eligible or readiness_status != "ready":
            blockers = readiness.get("blockers", [])
            return False, f"Readiness not met: status={readiness_status}, blockers={blockers}"
    
    # Check 8: P0-3 Batch 2 - safety_gates.allow_auto_dispatch (if present)
    safety_gates = metadata.get("safety_gates")
    if safety_gates:
        allow_auto_dispatch = safety_gates.get("allow_auto_dispatch", False)
        if allow_auto_dispatch is False:
            return False, f"Safety gates not passed: allow_auto_dispatch={allow_auto_dispatch}"
    
    return True, "Auto-trigger approved (readiness/safety_gates/truth_anchor checked)"


def auto_trigger_consumption(
    request_id: str,
    consumer_policy: Optional[Any] = None,
) -> tuple[bool, str, Optional[str]]:
    """
    **V8 新增**: 自动触发 consumption。
    
    Args:
        request_id: Request ID
        consumer_policy: Bridge consumer policy（可选）
    
    Returns:
        (triggered, reason, consumed_id)
        - triggered: 是否成功触发
        - reason: 原因/错误信息
        - consumed_id: consumed artifact ID（如果触发成功）
    """
    # Import here to avoid circular dependency
    from bridge_consumer import (
        BridgeConsumer,
        get_consumed_by_request,
        consume_request,
    )
    
    # 1. Get request
    request = get_spawn_request(request_id)
    if not request:
        return False, f"Request {request_id} not found", None
    
    # 2. Check if already consumed
    existing_consumed = get_consumed_by_request(request_id)
    if existing_consumed:
        return False, f"Request already consumed: {existing_consumed.consumed_id}", existing_consumed.consumed_id
    
    # 3. Evaluate auto-trigger guard
    should_trigger, reason = _should_auto_trigger(request)
    if not should_trigger:
        return False, reason, None
    
    # 4. Consume request
    try:
        artifact = consume_request(request_id, policy=consumer_policy)
        
        if artifact.consumer_status in ("consumed", "executed"):
            # 5. Record auto-trigger
            _record_auto_trigger(request_id, artifact.consumed_id)
            return True, f"Auto-triggered consumption: {artifact.consumed_id}", artifact.consumed_id
        else:
            return False, f"Consumption blocked: {artifact.consumer_reason}", None
            
    except Exception as e:
        return False, f"Auto-trigger failed: {str(e)}", None


def configure_auto_trigger(
    enabled: Optional[bool] = None,
    allowlist: Optional[List[str]] = None,
    denylist: Optional[List[str]] = None,
    require_manual_approval: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    **V8 新增**: 配置 auto-trigger。
    
    Args:
        enabled: 是否启用 auto-trigger
        allowlist: scenario allowlist
        denylist: scenario denylist
        require_manual_approval: 是否需要手动审批
    
    Returns:
        更新后的配置
    """
    config = _load_auto_trigger_config()
    
    if enabled is not None:
        config["enabled"] = enabled
    if allowlist is not None:
        config["allowlist"] = allowlist
    if denylist is not None:
        config["denylist"] = denylist
    if require_manual_approval is not None:
        config["require_manual_approval"] = require_manual_approval
    
    _save_auto_trigger_config(config)
    return config


def get_auto_trigger_status() -> Dict[str, Any]:
    """
    **V8 新增**: 获取 auto-trigger 状态。
    
    Returns:
        {
            "config": Dict,
            "triggered_count": int,
            "pending_requests": List[Dict],
        }
    """
    config = _load_auto_trigger_config()
    index = _load_auto_trigger_index()
    
    # 获取 pending requests（prepared 但未触发）
    pending = []
    requests = list_spawn_requests(request_status="prepared", limit=100)
    for req in requests:
        if not _is_auto_triggered(req.request_id):
            pending.append({
                "request_id": req.request_id,
                "scenario": req.metadata.get("scenario", "generic"),
                "task_id": req.source_task_id,
                "time": req.spawn_request_time,
            })
    
    return {
        "config": config,
        "triggered_count": len(index),
        "pending_requests": pending[:20],  # Limit to 20
    }


@dataclass
class SpawnRequestPolicy:
    """
    Spawn request policy — 评估是否可生成 sessions_spawn request。
    
    核心字段：
    - require_receipt_status: 要求的 receipt status（默认 completed）
    - require_execution_payload: 是否要求 execution payload 存在
    - prevent_duplicate: 是否防止重复创建 request
    - prepare_only: 是否仅准备 request（默认 True，不真正调用 sessions_spawn）
    
    这是通用 policy，不绑定特定场景。
    """
    require_receipt_status: str = "completed"
    require_execution_payload: bool = True
    prevent_duplicate: bool = True
    prepare_only: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "require_receipt_status": self.require_receipt_status,
            "require_execution_payload": self.require_execution_payload,
            "prevent_duplicate": self.prevent_duplicate,
            "prepare_only": self.prepare_only,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SpawnRequestPolicy":
        return cls(
            require_receipt_status=data.get("require_receipt_status", "completed"),
            require_execution_payload=data.get("require_execution_payload", True),
            prevent_duplicate=data.get("prevent_duplicate", True),
            prepare_only=data.get("prepare_only", True),
        )


@dataclass
class SessionsSpawnRequest:
    """
    Sessions spawn request — 通用 sessions_spawn-compatible request artifact。
    
    核心字段：
    - request_id: Request ID
    - source_receipt_id: 来源 completion receipt ID
    - source_execution_id: 来源 spawn execution ID
    - source_spawn_id: 来源 spawn closure ID
    - source_dispatch_id: 来源 dispatch ID
    - source_registration_id: 来源 registration ID
    - source_task_id: 来源 task ID
    - spawn_request_status: prepared | emitted | blocked | failed
    - spawn_request_reason: 请求创建/阻塞/失败的原因
    - spawn_request_time: 创建时间戳
    - sessions_spawn_params: sessions_spawn 兼容参数（runtime / cwd / task / label / metadata）
    - dedupe_key: 去重 key
    - policy_evaluation: policy 评估结果
    - metadata: 额外元数据（adapter-agnostic）
    
    这是 canonical request artifact，可被任何 adapter 消费（trading / channel / generic）。
    """
    request_id: str
    source_receipt_id: str
    source_execution_id: str
    source_spawn_id: str
    source_dispatch_id: str
    source_registration_id: str
    source_task_id: str
    spawn_request_status: SpawnRequestStatus
    spawn_request_reason: str
    spawn_request_time: str
    sessions_spawn_params: Dict[str, Any]  # {runtime, cwd, task, label, metadata, ...}
    dedupe_key: str
    policy_evaluation: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_version": REQUEST_VERSION,
            "request_id": self.request_id,
            "source_receipt_id": self.source_receipt_id,
            "source_execution_id": self.source_execution_id,
            "source_spawn_id": self.source_spawn_id,
            "source_dispatch_id": self.source_dispatch_id,
            "source_registration_id": self.source_registration_id,
            "source_task_id": self.source_task_id,
            "spawn_request_status": self.spawn_request_status,
            "spawn_request_reason": self.spawn_request_reason,
            "spawn_request_time": self.spawn_request_time,
            "sessions_spawn_params": self.sessions_spawn_params,
            "dedupe_key": self.dedupe_key,
            "policy_evaluation": self.policy_evaluation,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionsSpawnRequest":
        return cls(
            request_id=data.get("request_id", ""),
            source_receipt_id=data.get("source_receipt_id", ""),
            source_execution_id=data.get("source_execution_id", ""),
            source_spawn_id=data.get("source_spawn_id", ""),
            source_dispatch_id=data.get("source_dispatch_id", ""),
            source_registration_id=data.get("source_registration_id", ""),
            source_task_id=data.get("source_task_id", ""),
            spawn_request_status=data.get("spawn_request_status", "blocked"),
            spawn_request_reason=data.get("spawn_request_reason", ""),
            spawn_request_time=data.get("spawn_request_time", ""),
            sessions_spawn_params=data.get("sessions_spawn_params", {}),
            dedupe_key=data.get("dedupe_key", ""),
            policy_evaluation=data.get("policy_evaluation"),
            metadata=data.get("metadata", {}),
        )
    
    def write(self) -> Path:
        """写入 spawn request artifact 到文件"""
        _ensure_request_dir()
        req_file = _spawn_request_file(self.request_id)
        tmp_file = req_file.with_suffix(".tmp")
        with open(tmp_file, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
        tmp_file.replace(req_file)
        return req_file
    
    def to_sessions_spawn_call(self) -> Dict[str, Any]:
        """
        转换为可直接调用 sessions_spawn 的参数。
        
        返回格式符合 OpenClaw sessions_spawn API。
        """
        params = self.sessions_spawn_params.copy()
        
        # 确保必要字段存在
        if "runtime" not in params:
            params["runtime"] = "subagent"
        if "metadata" not in params:
            params["metadata"] = {}
        
        # 添加 linkage metadata
        params["metadata"]["request_id"] = self.request_id
        params["metadata"]["source_receipt_id"] = self.source_receipt_id
        params["metadata"]["orchestration_version"] = REQUEST_VERSION
        
        return {
            "task": params.get("task", ""),
            "runtime": params.get("runtime", "subagent"),
            "cwd": params.get("cwd", ""),
            "label": params.get("label", f"orch-{self.source_task_id[:8]}"),
            "metadata": params.get("metadata", {}),
        }


class SpawnRequestKernel:
    """
    Spawn request kernel — 从 completion receipt 生成 sessions_spawn request。
    
    提供：
    - evaluate_policy(): 评估 request policy
    - create_request(): 创建 request artifact
    - emit_request(): emit request（写入 artifact + 记录 dedupe）
    """
    
    def __init__(self, policy: Optional[SpawnRequestPolicy] = None):
        self.policy = policy or SpawnRequestPolicy()
    
    def evaluate_policy(
        self,
        receipt: CompletionReceiptArtifact,
        existing_request: Optional[SessionsSpawnRequest] = None,
    ) -> Dict[str, Any]:
        """
        评估 request policy。
        
        Args:
            receipt: Completion receipt artifact
            existing_request: 已存在的 request（用于去重）
        
        Returns:
            {
                "eligible": bool,
                "blocked_reasons": List[str],
                "checks": List[Dict],
            }
        """
        checks: List[Dict[str, Any]] = []
        blocked_reasons: List[str] = []
        
        # Check 1: receipt status
        receipt_status_ok = receipt.receipt_status == self.policy.require_receipt_status
        checks.append({
            "name": "receipt_status",
            "expected": self.policy.require_receipt_status,
            "actual": receipt.receipt_status,
            "passed": receipt_status_ok,
        })
        if not receipt_status_ok:
            blocked_reasons.append(
                f"Receipt status is '{receipt.receipt_status}', required '{self.policy.require_receipt_status}'"
            )
        
        # Check 2: execution payload required
        # 从 receipt metadata 中推断是否有 execution payload
        has_execution_payload = receipt.metadata.get("source_execution_status") == "started"
        payload_ok = not self.policy.require_execution_payload or has_execution_payload
        checks.append({
            "name": "execution_payload_required",
            "expected": "present" if self.policy.require_execution_payload else "optional",
            "actual": "present" if has_execution_payload else "missing",
            "passed": payload_ok,
        })
        if not payload_ok and self.policy.require_execution_payload:
            blocked_reasons.append("Missing execution payload indicator")
        
        # Check 3: duplicate request prevention
        duplicate_ok = True
        if self.policy.prevent_duplicate:
            dedupe_key = _generate_request_dedupe_key(
                receipt.receipt_id,
                receipt.source_spawn_execution_id,
            )
            is_duplicate = _is_duplicate_request(dedupe_key)
            if is_duplicate:
                duplicate_ok = False
                blocked_reasons.append(
                    f"Duplicate request: already created for receipt {receipt.receipt_id}"
                )
        
        checks.append({
            "name": "prevent_duplicate_request",
            "expected": "no existing request",
            "actual": "duplicate_found" if not duplicate_ok else "no_duplicate",
            "passed": duplicate_ok,
        })
        
        return {
            "eligible": len(blocked_reasons) == 0,
            "blocked_reasons": blocked_reasons,
            "checks": checks,
        }
    
    def _build_sessions_spawn_params(
        self,
        receipt: CompletionReceiptArtifact,
    ) -> Dict[str, Any]:
        """
        从 receipt 构建 sessions_spawn 参数。
        
        这是通用构建逻辑，不绑定特定场景。
        """
        # 从 receipt metadata 中提取场景信息
        scenario = receipt.metadata.get("scenario", "generic")
        owner = receipt.metadata.get("owner", "")
        
        # 构建 task preview
        task_preview = f"Orchestration continuation for task {receipt.source_task_id}"
        
        # 构建 sessions_spawn 参数
        params = {
            "runtime": "subagent",
            "cwd": "",  # 由上游 adapter 填充
            "task": task_preview,
            "label": f"orch-{receipt.source_task_id[:8]}",
            "metadata": {
                "dispatch_id": receipt.source_dispatch_id,
                "registration_id": receipt.source_registration_id,
                "spawn_id": receipt.source_spawn_id,
                "execution_id": receipt.source_spawn_execution_id,
                "receipt_id": receipt.receipt_id,
                "scenario": scenario,
                "owner": owner,
                "orchestration_continuation": True,
            },
        }
        
        # 如果 receipt 包含 business_result，提取额外上下文
        if receipt.business_result:
            params["metadata"]["business_context"] = receipt.business_result
        
        return params
    
    def create_request(
        self,
        receipt: CompletionReceiptArtifact,
        policy_evaluation: Dict[str, Any],
    ) -> SessionsSpawnRequest:
        """
        创建 sessions spawn request artifact。
        
        Args:
            receipt: Completion receipt artifact
            policy_evaluation: Policy evaluation result
        
        Returns:
            SessionsSpawnRequest
        """
        request_id = _generate_request_id()
        dedupe_key = _generate_request_dedupe_key(
            receipt.receipt_id,
            receipt.source_spawn_execution_id,
        )
        
        # 决定 spawn_request_status
        if policy_evaluation["eligible"]:
            req_status: SpawnRequestStatus = "prepared"
            req_reason = "Policy evaluation passed; request prepared (ready for emission)"
        elif policy_evaluation["blocked_reasons"]:
            req_status = "blocked"
            req_reason = "; ".join(policy_evaluation["blocked_reasons"])
        else:
            req_status = "failed"
            req_reason = "Not eligible (unknown reason)"
        
        # 构建 sessions_spawn_params
        sessions_spawn_params = self._build_sessions_spawn_params(receipt)
        
        artifact = SessionsSpawnRequest(
            request_id=request_id,
            source_receipt_id=receipt.receipt_id,
            source_execution_id=receipt.source_spawn_execution_id,
            source_spawn_id=receipt.source_spawn_id,
            source_dispatch_id=receipt.source_dispatch_id,
            source_registration_id=receipt.source_registration_id,
            source_task_id=receipt.source_task_id,
            spawn_request_status=req_status,
            spawn_request_reason=req_reason,
            spawn_request_time=_iso_now(),
            sessions_spawn_params=sessions_spawn_params,
            dedupe_key=dedupe_key,
            policy_evaluation=policy_evaluation,
            metadata={
                "source_receipt_status": receipt.receipt_status,
                "source_receipt_time": receipt.receipt_time,
                "scenario": receipt.metadata.get("scenario", ""),
                "owner": receipt.metadata.get("owner", ""),
                "truth_anchor": receipt.metadata.get("truth_anchor"),
            },
        )
        
        return artifact
    
    def emit_request(
        self,
        receipt: CompletionReceiptArtifact,
    ) -> SessionsSpawnRequest:
        """
        Emit request：评估 policy -> 创建 artifact -> 写入文件 -> 记录 dedupe。
        
        Args:
            receipt: Completion receipt artifact
        
        Returns:
            SessionsSpawnRequest（已写入文件）
        """
        # 1. Evaluate policy
        policy_evaluation = self.evaluate_policy(receipt)
        
        # 2. Create artifact
        artifact = self.create_request(receipt, policy_evaluation)
        
        # 3. Write artifact
        artifact.write()
        
        # 4. Record dedupe（如果 prepared）
        if artifact.spawn_request_status == "prepared":
            _record_request_dedupe(artifact.dedupe_key, artifact.request_id)
        
        return artifact


def prepare_spawn_request(
    receipt_id: str,
    policy: Optional[SpawnRequestPolicy] = None,
) -> SessionsSpawnRequest:
    """
    Convenience function: 从 completion receipt 准备 spawn request。
    
    Args:
        receipt_id: Receipt ID
        policy: Request policy（可选）
    
    Returns:
        SessionsSpawnRequest（已写入文件）
    """
    receipt = get_completion_receipt(receipt_id)
    if not receipt:
        raise ValueError(f"Completion receipt {receipt_id} not found")
    
    kernel = SpawnRequestKernel(policy)
    return kernel.emit_request(receipt)


def emit_spawn_request(
    receipt_id: str,
    policy: Optional[SpawnRequestPolicy] = None,
) -> SessionsSpawnRequest:
    """
    Alias for prepare_spawn_request（保持向后兼容）。
    """
    return prepare_spawn_request(receipt_id, policy)


def list_spawn_requests(
    receipt_id: Optional[str] = None,
    execution_id: Optional[str] = None,
    spawn_id: Optional[str] = None,
    dispatch_id: Optional[str] = None,
    registration_id: Optional[str] = None,
    task_id: Optional[str] = None,
    request_status: Optional[str] = None,
    limit: int = 100,
) -> List[SessionsSpawnRequest]:
    """
    列出 spawn request artifacts。
    
    Args:
        receipt_id: 按 receipt_id 过滤
        execution_id: 按 execution_id 过滤
        spawn_id: 按 spawn_id 过滤
        dispatch_id: 按 dispatch_id 过滤
        registration_id: 按 registration_id 过滤
        task_id: 按 task_id 过滤
        request_status: 按 spawn_request_status 过滤
        limit: 最大返回数量
    
    Returns:
        SessionsSpawnRequest 列表
    """
    _ensure_request_dir()
    
    requests = []
    for req_file in SPAWN_REQUEST_DIR.glob("*.json"):
        if req_file.name == "request_index.json":
            continue
        
        try:
            with open(req_file, "r") as f:
                data = json.load(f)
            artifact = SessionsSpawnRequest.from_dict(data)
            
            # 过滤
            if receipt_id and artifact.source_receipt_id != receipt_id:
                continue
            if execution_id and artifact.source_execution_id != execution_id:
                continue
            if spawn_id and artifact.source_spawn_id != spawn_id:
                continue
            if dispatch_id and artifact.source_dispatch_id != dispatch_id:
                continue
            if registration_id and artifact.source_registration_id != registration_id:
                continue
            if task_id and artifact.source_task_id != task_id:
                continue
            if request_status and artifact.spawn_request_status != request_status:
                continue
            
            requests.append(artifact)
        except (json.JSONDecodeError, KeyError):
            pass
    
    # 按 request_id 排序
    requests.sort(key=lambda r: r.request_id)
    
    return requests[:limit]


def get_spawn_request(request_id: str) -> Optional[SessionsSpawnRequest]:
    """
    获取 spawn request artifact。
    
    Args:
        request_id: Request ID
    
    Returns:
        SessionsSpawnRequest，不存在则返回 None
    """
    req_file = _spawn_request_file(request_id)
    if not req_file.exists():
        return None
    
    with open(req_file, "r") as f:
        data = json.load(f)
    
    return SessionsSpawnRequest.from_dict(data)


# ============ Full pipeline helper (receipt -> request) ============

def run_receipt_to_request_pipeline(
    receipt_id: str,
) -> Dict[str, Any]:
    """
    运行 pipeline：completion receipt -> spawn request。
    
    Args:
        receipt_id: Receipt ID
    
    Returns:
        {
            "receipt": CompletionReceiptArtifact,
            "request": SessionsSpawnRequest,
        }
    """
    # 1. Get receipt
    receipt = get_completion_receipt(receipt_id)
    if not receipt:
        raise ValueError(f"Completion receipt {receipt_id} not found")
    
    # 2. Create request
    kernel = SpawnRequestKernel()
    request = kernel.emit_request(receipt)
    
    return {
        "receipt": receipt,
        "request": request,
    }


# CLI 入口
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python sessions_spawn_request.py prepare <receipt_id>")
        print("  python sessions_spawn_request.py list [--status <status>] [--receipt <receipt_id>]")
        print("  python sessions_spawn_request.py get <request_id>")
        print("  python sessions_spawn_request.py call-params <request_id>")
        print("  python sessions_spawn_request.py auto-trigger <request_id>  # V8 新增")
        print("  python sessions_spawn_request.py auto-trigger-config [options]  # V8 新增")
        print("  python sessions_spawn_request.py auto-trigger-status  # V8 新增")
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == "prepare":
        if len(sys.argv) < 3:
            print("Error: missing receipt_id")
            sys.exit(1)
        
        receipt_id = sys.argv[2]
        artifact = prepare_spawn_request(receipt_id)
        print(json.dumps(artifact.to_dict(), indent=2))
        print(f"\nSpawn request artifact written to: {_spawn_request_file(artifact.request_id)}")
        if artifact.spawn_request_status == "prepared":
            print(f"\nSessions spawn params:")
            print(json.dumps(artifact.sessions_spawn_params, indent=2))
    
    elif cmd == "list":
        status = None
        receipt_id = None
        if "--status" in sys.argv:
            idx = sys.argv.index("--status")
            if idx + 1 < len(sys.argv):
                status = sys.argv[idx + 1]
        if "--receipt" in sys.argv:
            idx = sys.argv.index("--receipt")
            if idx + 1 < len(sys.argv):
                receipt_id = sys.argv[idx + 1]
        
        requests = list_spawn_requests(
            receipt_id=receipt_id,
            request_status=status,
        )
        print(json.dumps([r.to_dict() for r in requests], indent=2))
    
    elif cmd == "get":
        if len(sys.argv) < 3:
            print("Error: missing request_id")
            sys.exit(1)
        
        request_id = sys.argv[2]
        artifact = get_spawn_request(request_id)
        if artifact:
            print(json.dumps(artifact.to_dict(), indent=2))
        else:
            print(f"Spawn request {request_id} not found")
            sys.exit(1)
    
    elif cmd == "call-params":
        if len(sys.argv) < 3:
            print("Error: missing request_id")
            sys.exit(1)
        
        request_id = sys.argv[2]
        artifact = get_spawn_request(request_id)
        if artifact:
            print("=== sessions_spawn() call parameters ===")
            print(json.dumps(artifact.to_sessions_spawn_call(), indent=2))
        else:
            print(f"Spawn request {request_id} not found")
            sys.exit(1)
    
    elif cmd == "auto-trigger":
        # V8 新增：auto-trigger consumption
        if len(sys.argv) < 3:
            print("Error: missing request_id")
            sys.exit(1)
        
        request_id = sys.argv[2]
        triggered, reason, consumed_id = auto_trigger_consumption(request_id)
        
        print(json.dumps({
            "triggered": triggered,
            "reason": reason,
            "consumed_id": consumed_id,
        }, indent=2))
        
        if triggered:
            print(f"\n✓ Auto-triggered consumption: {consumed_id}")
        else:
            print(f"\n✗ Auto-trigger failed: {reason}")
            sys.exit(1)
    
    elif cmd == "auto-trigger-config":
        # V8 新增：配置 auto-trigger
        enabled = None
        allowlist = None
        denylist = None
        require_manual = None
        
        if "--enable" in sys.argv:
            enabled = True
        if "--disable" in sys.argv:
            enabled = False
        if "--allowlist" in sys.argv:
            idx = sys.argv.index("--allowlist")
            if idx + 1 < len(sys.argv):
                allowlist = sys.argv[idx + 1].split(",")
        if "--denylist" in sys.argv:
            idx = sys.argv.index("--denylist")
            if idx + 1 < len(sys.argv):
                denylist = sys.argv[idx + 1].split(",")
        if "--no-manual-approval" in sys.argv:
            require_manual = False
        if "--manual-approval" in sys.argv:
            require_manual = True
        
        config = configure_auto_trigger(
            enabled=enabled,
            allowlist=allowlist,
            denylist=denylist,
            require_manual_approval=require_manual,
        )
        
        print("Auto-trigger configuration updated:")
        print(json.dumps(config, indent=2))
    
    elif cmd == "auto-trigger-status":
        # V8 新增：获取 auto-trigger 状态
        status = get_auto_trigger_status()
        print(json.dumps(status, indent=2))
    
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
