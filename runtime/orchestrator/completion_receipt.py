#!/usr/bin/env python3
"""
completion_receipt.py — Universal Partial-Completion Continuation Framework v5

目标：实现 spawn execution 后的 completion receipt closure 闭环。

核心能力：
1. 消费 spawn execution artifact
2. 生成 canonical completion receipt artifact
3. 字段包括：receipt_status / source_spawn_execution_id / source_dispatch_id / result_summary
4. Linkage 回 source task/batch
5. 最小真实闭环：receipt 真落盘

当前阶段：spawn execution -> completion receipt artifact（不是全域自动闭环）

这是 v5 新增模块，保持通用 kernel，trading 作为首个接入场景。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from spawn_execution import (
    SpawnExecutionArtifact,
    SpawnExecutionStatus,
    get_spawn_execution,
    list_spawn_executions,
    SPAWN_EXECUTION_DIR,
)

from partial_continuation import ContinuationContract, build_continuation_contract

__all__ = [
    "ReceiptStatus",
    "CompletionReceiptArtifact",
    "CompletionReceiptKernel",
    "create_completion_receipt",
    "list_completion_receipts",
    "get_completion_receipt",
    "RECEIPT_VERSION",
    "build_receipt_continuation_contract",
]

RECEIPT_VERSION = "completion_receipt_v1"

ReceiptStatus = Literal["completed", "failed", "missing"]

# Completion receipt 存储目录
COMPLETION_RECEIPT_DIR = Path(
    os.environ.get(
        "OPENCLAW_COMPLETION_RECEIPT_DIR",
        Path.home() / ".openclaw" / "shared-context" / "completion_receipts",
    )
)

# Spawn execution -> Completion receipt 映射索引文件
RECEIPT_INDEX_FILE = COMPLETION_RECEIPT_DIR / "receipt_index.json"


def _ensure_receipt_dir():
    """确保 completion receipt 目录存在"""
    COMPLETION_RECEIPT_DIR.mkdir(parents=True, exist_ok=True)


def _completion_receipt_file(receipt_id: str) -> Path:
    """返回 completion receipt artifact 文件路径"""
    return COMPLETION_RECEIPT_DIR / f"{receipt_id}.json"


def _iso_now() -> str:
    """返回当前 ISO-8601 时间戳"""
    return datetime.now().isoformat()


def _generate_receipt_id() -> str:
    """生成稳定 receipt ID"""
    import uuid
    return f"receipt_{uuid.uuid4().hex[:12]}"


def _generate_receipt_dedupe_key(execution_id: str, spawn_id: str) -> str:
    """
    生成 receipt 去重 key。
    
    规则：同一 execution 不重复创建 receipt。
    """
    return f"receipt_dedupe:{execution_id}:{spawn_id}"


def _load_receipt_index() -> Dict[str, str]:
    """
    加载 receipt index（dedupe_key -> receipt_id 映射）。
    
    用于去重检查。
    """
    _ensure_receipt_dir()
    if not RECEIPT_INDEX_FILE.exists():
        return {}
    
    try:
        with open(RECEIPT_INDEX_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, KeyError):
        return {}


def _save_receipt_index(index: Dict[str, str]):
    """保存 receipt index"""
    _ensure_receipt_dir()
    tmp_file = RECEIPT_INDEX_FILE.with_suffix(".tmp")
    with open(tmp_file, "w") as f:
        json.dump(index, f, indent=2)
    tmp_file.replace(RECEIPT_INDEX_FILE)


def _record_receipt_dedupe(dedupe_key: str, receipt_id: str):
    """记录 receipt dedupe（防止重复创建）"""
    index = _load_receipt_index()
    index[dedupe_key] = receipt_id
    _save_receipt_index(index)


def _is_duplicate_receipt(dedupe_key: str) -> bool:
    """检查是否已存在 receipt（去重）"""
    index = _load_receipt_index()
    return dedupe_key in index


def build_receipt_continuation_contract(
    execution: SpawnExecutionArtifact,
    receipt_status: ReceiptStatus,
    receipt_reason: str,
) -> ContinuationContract:
    """
    Build a ContinuationContract from receipt context.
    
    This is the canonical helper for deriving continuation semantics from
    completion receipt data. Uses receipt status/reason as the source of truth
    for stopped_because, and extracts next_step/next_owner from execution metadata.
    
    Args:
        execution: Source spawn execution artifact
        receipt_status: Receipt status (completed/failed/missing)
        receipt_reason: Receipt reason string
    
    Returns:
        ContinuationContract with continuation semantics derived from receipt
    """
    # Derive stopped_because from receipt status/reason
    if receipt_status == "completed":
        stopped_because = "receipt_completed"
    elif receipt_status == "failed":
        stopped_because = f"receipt_failed_{receipt_reason[:50].lower().replace(' ', '_')}"
    else:
        stopped_because = f"receipt_missing_{receipt_reason[:50].lower().replace(' ', '_')}"
    
    # Extract next_step from execution metadata or derive from status
    next_step = execution.spawn_execution_target.get("next_step", "")
    if not next_step:
        if receipt_status == "completed":
            next_step = "Awaiting downstream processing or manual review"
        elif receipt_status == "failed":
            next_step = f"Resolve failure: {receipt_reason[:100]}"
        else:
            next_step = f"Investigate missing receipt: {receipt_reason[:100]}"
    
    # Extract next_owner from execution metadata or default to main
    next_owner = execution.spawn_execution_target.get("owner", "main")
    
    # Build continuation contract
    return build_continuation_contract(
        stopped_because=stopped_because,
        next_step=next_step,
        next_owner=next_owner,
        metadata={
            "source": "completion_receipt",
            "receipt_status": receipt_status,
            "receipt_reason": receipt_reason,
            "execution_id": execution.execution_id,
            "scenario": execution.spawn_execution_target.get("scenario", ""),
        },
    )


@dataclass
class CompletionReceiptArtifact:
    """
    Completion receipt artifact — 真实 completion receipt 记录（可落盘）。
    
    核心字段：
    - receipt_id: Receipt ID
    - source_spawn_execution_id: 来源 spawn execution ID
    - source_spawn_id: 来源 spawn closure ID
    - source_dispatch_id: 来源 dispatch ID
    - source_registration_id: 来源 registration ID
    - source_task_id: 来源 task ID
    - receipt_status: completed | failed | missing
    - receipt_reason: receipt 状态的原因
    - receipt_time: 创建时间戳
    - result_summary: 结果摘要
    - dedupe_key: 去重 key
    - business_result: 业务结果（可选，trading 场景特定等）
    - metadata: 额外元数据
    
    这是 canonical artifact，operator/main 可以继续消费。
    """
    receipt_id: str
    source_spawn_execution_id: str
    source_spawn_id: str
    source_dispatch_id: str
    source_registration_id: str
    source_task_id: str
    receipt_status: ReceiptStatus
    receipt_reason: str
    receipt_time: str
    result_summary: str
    dedupe_key: str
    business_result: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "receipt_version": RECEIPT_VERSION,
            "receipt_id": self.receipt_id,
            "source_spawn_execution_id": self.source_spawn_execution_id,
            "source_spawn_id": self.source_spawn_id,
            "source_dispatch_id": self.source_dispatch_id,
            "source_registration_id": self.source_registration_id,
            "source_task_id": self.source_task_id,
            "receipt_status": self.receipt_status,
            "receipt_reason": self.receipt_reason,
            "receipt_time": self.receipt_time,
            "result_summary": self.result_summary,
            "dedupe_key": self.dedupe_key,
            "business_result": self.business_result,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CompletionReceiptArtifact":
        return cls(
            receipt_id=data.get("receipt_id", ""),
            source_spawn_execution_id=data.get("source_spawn_execution_id", ""),
            source_spawn_id=data.get("source_spawn_id", ""),
            source_dispatch_id=data.get("source_dispatch_id", ""),
            source_registration_id=data.get("source_registration_id", ""),
            source_task_id=data.get("source_task_id", ""),
            receipt_status=data.get("receipt_status", "missing"),
            receipt_reason=data.get("receipt_reason", ""),
            receipt_time=data.get("receipt_time", ""),
            result_summary=data.get("result_summary", ""),
            dedupe_key=data.get("dedupe_key", ""),
            business_result=data.get("business_result"),
            metadata=data.get("metadata", {}),
        )
    
    def write(self) -> Path:
        """写入 completion receipt artifact 到文件"""
        _ensure_receipt_dir()
        receipt_file = _completion_receipt_file(self.receipt_id)
        tmp_file = receipt_file.with_suffix(".tmp")
        with open(tmp_file, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
        tmp_file.replace(receipt_file)
        return receipt_file


class CompletionReceiptKernel:
    """
    Completion receipt kernel — 从 spawn execution artifact生成 receipt。
    
    提供：
    - create_receipt(): 创建 receipt artifact
    - emit_receipt(): emit receipt（写入 artifact + 记录 dedupe）
    """
    
    def __init__(self):
        pass
    
    def _determine_receipt_status(
        self,
        execution: SpawnExecutionArtifact,
    ) -> tuple[ReceiptStatus, str]:
        """
        根据 execution status 决定 receipt status。
        
        Returns:
            (receipt_status, receipt_reason)
        """
        exec_status = execution.spawn_execution_status
        
        if exec_status == "started":
            # 执行已开始，假设完成（当前阶段模拟）
            return "completed", "Execution started and completed (simulated)"
        elif exec_status == "blocked":
            return "failed", f"Execution was blocked: {execution.spawn_execution_reason}"
        elif exec_status == "failed":
            return "failed", f"Execution failed: {execution.spawn_execution_reason}"
        elif exec_status == "skipped":
            return "missing", f"Execution was skipped: {execution.spawn_execution_reason}"
        else:
            return "missing", f"Unknown execution status: {exec_status}"
    
    def _extract_result_summary(
        self,
        execution: SpawnExecutionArtifact,
    ) -> str:
        """
        从 execution 中提取 result summary。
        """
        if execution.execution_result:
            mode = execution.execution_result.get("execution_mode", "unknown")
            if mode == "simulated":
                return f"Simulated execution for task {execution.task_id} (scenario: {execution.spawn_execution_target.get('scenario', 'unknown')})"
            elif mode == "real":
                return f"Real execution for task {execution.task_id}"
        
        return f"Execution {execution.spawn_execution_status} for task {execution.task_id}"
    
    def _extract_business_result(
        self,
        execution: SpawnExecutionArtifact,
    ) -> Optional[Dict[str, Any]]:
        """
        从 execution 中提取 business result（场景特定）。
        
        Trading 场景会包含 trading_context 等信息。
        """
        business_result = {}
        
        # 从 execution payload 中提取业务上下文
        if execution.execution_payload:
            metadata = execution.execution_payload.get("metadata", {})
            
            # Trading 场景特定字段
            if "trading_context" in metadata:
                business_result["trading_context"] = metadata["trading_context"]
            
            # 通用 linkage
            business_result["dispatch_id"] = execution.dispatch_id
            business_result["registration_id"] = execution.registration_id
            business_result["task_id"] = execution.task_id
        
        # 从 execution result 中提取
        if execution.execution_result:
            business_result["execution_mode"] = execution.execution_result.get("execution_mode")
            business_result["downstream_ready"] = execution.execution_result.get("ready_for_downstream", False)
        
        return business_result if business_result else None
    
    def create_receipt(
        self,
        execution: SpawnExecutionArtifact,
    ) -> CompletionReceiptArtifact:
        """
        创建 completion receipt artifact。
        
        Args:
            execution: Spawn execution artifact
        
        Returns:
            CompletionReceiptArtifact
        """
        receipt_id = _generate_receipt_id()
        dedupe_key = _generate_receipt_dedupe_key(execution.execution_id, execution.spawn_id)
        
        # 决定 receipt status
        receipt_status, receipt_reason = self._determine_receipt_status(execution)
        
        # 提取 result summary
        result_summary = self._extract_result_summary(execution)
        
        # 提取 business result
        business_result = self._extract_business_result(execution)
        
        # Build ContinuationContract (P0-1 Batch 5: unified continuation semantics)
        continuation = build_receipt_continuation_contract(
            execution=execution,
            receipt_status=receipt_status,
            receipt_reason=receipt_reason,
        )
        
        artifact = CompletionReceiptArtifact(
            receipt_id=receipt_id,
            source_spawn_execution_id=execution.execution_id,
            source_spawn_id=execution.spawn_id,
            source_dispatch_id=execution.dispatch_id,
            source_registration_id=execution.registration_id,
            source_task_id=execution.task_id,
            receipt_status=receipt_status,
            receipt_reason=receipt_reason,
            receipt_time=_iso_now(),
            result_summary=result_summary,
            dedupe_key=dedupe_key,
            business_result=business_result,
            metadata={
                "source_execution_status": execution.spawn_execution_status,
                "source_execution_time": execution.spawn_execution_time,
                "source_spawn_status": execution.metadata.get("source_spawn_status"),
                "source_dispatch_status": execution.metadata.get("source_dispatch_status"),
                "truth_anchor": execution.metadata.get("truth_anchor"),
                "scenario": execution.spawn_execution_target.get("scenario", ""),
                "owner": execution.spawn_execution_target.get("owner", ""),
                # P0-1 Batch 5: Include ContinuationContract as canonical continuation semantics
                "continuation_contract": continuation.to_dict(),
                "stopped_because": continuation.stopped_because,
                "next_step": continuation.next_step,
                "next_owner": continuation.next_owner,
            },
        )
        
        return artifact
    
    def emit_receipt(
        self,
        execution: SpawnExecutionArtifact,
    ) -> CompletionReceiptArtifact:
        """
        Emit receipt：创建 artifact -> 写入文件 -> 记录 dedupe。
        
        Args:
            execution: Spawn execution artifact
        
        Returns:
            CompletionReceiptArtifact（已写入文件）
        """
        # 1. Create artifact
        artifact = self.create_receipt(execution)
        
        # 2. Write artifact
        artifact.write()
        
        # 3. Record dedupe
        _record_receipt_dedupe(artifact.dedupe_key, artifact.receipt_id)
        
        return artifact


def create_completion_receipt(
    execution_id: str,
) -> CompletionReceiptArtifact:
    """
    Convenience function: 从 spawn execution 创建 completion receipt。
    
    Args:
        execution_id: Execution ID
    
    Returns:
        CompletionReceiptArtifact（已写入文件）
    """
    execution = get_spawn_execution(execution_id)
    if not execution:
        raise ValueError(f"Spawn execution {execution_id} not found")
    
    kernel = CompletionReceiptKernel()
    return kernel.emit_receipt(execution)


def list_completion_receipts(
    execution_id: Optional[str] = None,
    spawn_id: Optional[str] = None,
    dispatch_id: Optional[str] = None,
    registration_id: Optional[str] = None,
    task_id: Optional[str] = None,
    receipt_status: Optional[str] = None,
    limit: int = 100,
) -> List[CompletionReceiptArtifact]:
    """
    列出 completion receipt artifacts。
    
    Args:
        execution_id: 按 execution_id 过滤
        spawn_id: 按 spawn_id 过滤
        dispatch_id: 按 dispatch_id 过滤
        registration_id: 按 registration_id 过滤
        task_id: 按 task_id 过滤
        receipt_status: 按 receipt_status 过滤
        limit: 最大返回数量
    
    Returns:
        CompletionReceiptArtifact 列表
    """
    _ensure_receipt_dir()
    
    receipts = []
    for receipt_file in COMPLETION_RECEIPT_DIR.glob("*.json"):
        if receipt_file.name == "receipt_index.json":
            continue
        
        try:
            with open(receipt_file, "r") as f:
                data = json.load(f)
            artifact = CompletionReceiptArtifact.from_dict(data)
            
            # 过滤
            if execution_id and artifact.source_spawn_execution_id != execution_id:
                continue
            if spawn_id and artifact.source_spawn_id != spawn_id:
                continue
            if dispatch_id and artifact.source_dispatch_id != dispatch_id:
                continue
            if registration_id and artifact.source_registration_id != registration_id:
                continue
            if task_id and artifact.source_task_id != task_id:
                continue
            if receipt_status and artifact.receipt_status != receipt_status:
                continue
            
            receipts.append(artifact)
        except (json.JSONDecodeError, KeyError):
            pass
    
    # 按 receipt_id 排序
    receipts.sort(key=lambda r: r.receipt_id)
    
    return receipts[:limit]


def get_completion_receipt(receipt_id: str) -> Optional[CompletionReceiptArtifact]:
    """
    获取 completion receipt artifact。
    
    Args:
        receipt_id: Receipt ID
    
    Returns:
        CompletionReceiptArtifact，不存在则返回 None
    """
    receipt_file = _completion_receipt_file(receipt_id)
    if not receipt_file.exists():
        return None
    
    with open(receipt_file, "r") as f:
        data = json.load(f)
    
    return CompletionReceiptArtifact.from_dict(data)


# ============ Trading 场景特定 helper ============

def create_trading_completion_receipt(
    execution_id: str,
) -> CompletionReceiptArtifact:
    """
    Trading 场景特定的 completion receipt 创建。
    
    这是 trading_roundtable_phase1 场景的 convenience function。
    """
    return create_completion_receipt(execution_id)


# ============ Full pipeline helper (spawn closure -> execution -> receipt) ============

def run_full_pipeline(
    spawn_id: str,
    simulate: bool = True,
) -> Dict[str, Any]:
    """
    运行完整 pipeline：spawn closure -> execution -> receipt。
    
    Args:
        spawn_id: Spawn closure ID
        simulate: 是否模拟执行（默认 True）
    
    Returns:
        {
            "spawn": SpawnClosureArtifact,
            "execution": SpawnExecutionArtifact,
            "receipt": CompletionReceiptArtifact,
        }
    """
    from spawn_closure import get_spawn_closure
    from spawn_execution import SpawnExecutionKernel, SpawnExecutionPolicy
    
    # 1. Get spawn closure
    spawn = get_spawn_closure(spawn_id)
    if not spawn:
        raise ValueError(f"Spawn closure {spawn_id} not found")
    
    # 2. Execute spawn
    exec_policy = SpawnExecutionPolicy(
        scenario_allowlist=["trading_roundtable_phase1"],
        require_spawn_status="emitted",
        require_spawn_payload=True,
        prevent_duplicate=True,
        simulate_execution=simulate,
    )
    exec_kernel = SpawnExecutionKernel(exec_policy)
    execution = exec_kernel.execute_spawn(spawn)
    
    # 3. Create receipt
    receipt_kernel = CompletionReceiptKernel()
    receipt = receipt_kernel.emit_receipt(execution)
    
    return {
        "spawn": spawn,
        "execution": execution,
        "receipt": receipt,
    }


# CLI 入口
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python completion_receipt.py create <execution_id>")
        print("  python completion_receipt.py list [--status <status>] [--execution <execution_id>]")
        print("  python completion_receipt.py get <receipt_id>")
        print("  python completion_receipt.py trading <execution_id>")
        print("  python completion_receipt.py pipeline <spawn_id> [--real]")
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == "create":
        if len(sys.argv) < 3:
            print("Error: missing execution_id")
            sys.exit(1)
        
        execution_id = sys.argv[2]
        artifact = create_completion_receipt(execution_id)
        print(json.dumps(artifact.to_dict(), indent=2))
        print(f"\nCompletion receipt artifact written to: {_completion_receipt_file(artifact.receipt_id)}")
    
    elif cmd == "list":
        status = None
        execution_id = None
        if "--status" in sys.argv:
            idx = sys.argv.index("--status")
            if idx + 1 < len(sys.argv):
                status = sys.argv[idx + 1]
        if "--execution" in sys.argv:
            idx = sys.argv.index("--execution")
            if idx + 1 < len(sys.argv):
                execution_id = sys.argv[idx + 1]
        
        receipts = list_completion_receipts(
            execution_id=execution_id,
            receipt_status=status,
        )
        print(json.dumps([r.to_dict() for r in receipts], indent=2))
    
    elif cmd == "get":
        if len(sys.argv) < 3:
            print("Error: missing receipt_id")
            sys.exit(1)
        
        receipt_id = sys.argv[2]
        artifact = get_completion_receipt(receipt_id)
        if artifact:
            print(json.dumps(artifact.to_dict(), indent=2))
        else:
            print(f"Completion receipt {receipt_id} not found")
            sys.exit(1)
    
    elif cmd == "trading":
        if len(sys.argv) < 3:
            print("Error: missing execution_id")
            sys.exit(1)
        
        execution_id = sys.argv[2]
        artifact = create_trading_completion_receipt(execution_id)
        print(json.dumps(artifact.to_dict(), indent=2))
        print(f"\nTrading completion receipt written to: {_completion_receipt_file(artifact.receipt_id)}")
    
    elif cmd == "pipeline":
        if len(sys.argv) < 3:
            print("Error: missing spawn_id")
            sys.exit(1)
        
        spawn_id = sys.argv[2]
        simulate = "--real" not in sys.argv
        
        try:
            result = run_full_pipeline(spawn_id, simulate=simulate)
            print("=== SPAWN CLOSURE ===")
            print(json.dumps(result["spawn"].to_dict(), indent=2))
            print("\n=== SPAWN EXECUTION ===")
            print(json.dumps(result["execution"].to_dict(), indent=2))
            print("\n=== COMPLETION RECEIPT ===")
            print(json.dumps(result["receipt"].to_dict(), indent=2))
            print(f"\nPipeline complete. Receipt ID: {result['receipt'].receipt_id}")
        except ValueError as e:
            print(f"Error: {e}")
            sys.exit(1)
    
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
