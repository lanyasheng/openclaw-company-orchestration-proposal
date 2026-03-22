#!/usr/bin/env python3
"""
callback_auto_close.py — Universal Partial-Completion Continuation Framework v6

目标：实现 **通用** callback auto-close bridge（adapter-agnostic）。

核心能力：
1. 在 completion receipt 之上，生成 canonical callback auto-close artifact
2. Linkage 包含：dispatch_id / spawn_id / execution_id / receipt_id / request_id / source task_id
3. 让主线程/operator 能不靠手工拼接就看到"这一轮已闭环"
4. 不绑定特定场景（trading / channel / generic 均可消费）
5. 提供 summary / linkage index，支持快速查询闭环状态

当前阶段：canonical callback auto-close artifact / interface（不是全域自动闭环）

这是 v6 新增模块，通用 kernel，trading 仅作为首个消费者/样例。
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
)

__all__ = [
    "CloseStatus",
    "CallbackAutoCloseArtifact",
    "CallbackCloseKernel",
    "create_auto_close",
    "list_auto_closes",
    "get_auto_close",
    "build_close_summary",
    "CLOSE_VERSION",
]

CLOSE_VERSION = "callback_auto_close_v1"

CloseStatus = Literal["closed", "pending", "blocked", "partial"]

# Callback auto-close 存储目录
CALLBACK_CLOSE_DIR = Path(
    os.environ.get(
        "OPENCLAW_CALLBACK_CLOSE_DIR",
        Path.home() / ".openclaw" / "shared-context" / "callback_closes",
    )
)

# Linkage index（支持多 ID 查询）
CLOSE_LINKAGE_INDEX = CALLBACK_CLOSE_DIR / "close_linkage_index.json"


def _ensure_close_dir():
    """确保 callback close 目录存在"""
    CALLBACK_CLOSE_DIR.mkdir(parents=True, exist_ok=True)


def _callback_close_file(close_id: str) -> Path:
    """返回 callback close artifact 文件路径"""
    return CALLBACK_CLOSE_DIR / f"{close_id}.json"


def _iso_now() -> str:
    """返回当前 ISO-8601 时间戳"""
    return datetime.now().isoformat()


def _generate_close_id() -> str:
    """生成稳定 close ID"""
    import uuid
    return f"close_{uuid.uuid4().hex[:12]}"


def _generate_linkage_key(
    dispatch_id: str,
    spawn_id: str,
    execution_id: str,
    receipt_id: str,
) -> str:
    """
    生成 linkage key（用于快速查询）。
    
    规则：包含所有关键 ID，支持任意一个 ID 反向查询。
    """
    return f"linkage:{dispatch_id}:{spawn_id}:{execution_id}:{receipt_id}"


def _load_linkage_index() -> Dict[str, str]:
    """
    加载 linkage index（linkage_key -> close_id 映射）。
    
    用于快速查询。
    """
    _ensure_close_dir()
    if not CLOSE_LINKAGE_INDEX.exists():
        return {}
    
    try:
        with open(CLOSE_LINKAGE_INDEX, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, KeyError):
        return {}


def _save_linkage_index(index: Dict[str, str]):
    """保存 linkage index"""
    _ensure_close_dir()
    tmp_file = CLOSE_LINKAGE_INDEX.with_suffix(".tmp")
    with open(tmp_file, "w") as f:
        json.dump(index, f, indent=2)
    tmp_file.replace(CLOSE_LINKAGE_INDEX)


def _record_linkage(linkage_key: str, close_id: str):
    """记录 linkage（支持快速查询）"""
    index = _load_linkage_index()
    index[linkage_key] = close_id
    _save_linkage_index(index)


def _build_linkage_keys(
    dispatch_id: str,
    spawn_id: str,
    execution_id: str,
    receipt_id: str,
    request_id: Optional[str] = None,
) -> List[str]:
    """
    构建多个 linkage keys，支持任意 ID 反向查询。
    
    返回：
    - 完整 linkage key
    - 按各 ID 单独索引的 key
    """
    keys = [
        _generate_linkage_key(dispatch_id, spawn_id, execution_id, receipt_id),
        f"by_dispatch:{dispatch_id}",
        f"by_spawn:{spawn_id}",
        f"by_execution:{execution_id}",
        f"by_receipt:{receipt_id}",
    ]
    if request_id:
        keys.append(f"by_request:{request_id}")
    return keys


@dataclass
class CallbackAutoCloseArtifact:
    """
    Callback auto-close artifact — 通用 callback 闭环记录。
    
    核心字段：
    - close_id: Close ID
    - source_request_id: 来源 spawn request ID（可选，若尚未 request 则空）
    - source_receipt_id: 来源 completion receipt ID
    - source_execution_id: 来源 spawn execution ID
    - source_spawn_id: 来源 spawn closure ID
    - source_dispatch_id: 来源 dispatch ID
    - source_registration_id: 来源 registration ID
    - source_task_id: 来源 task ID
    - close_status: closed | pending | blocked | partial
    - close_reason: 闭环状态的原因
    - close_time: 创建时间戳
    - linkage: 完整 linkage（所有关键 ID）
    - close_summary: 闭环摘要（人类可读）
    - metadata: 额外元数据（adapter-agnostic）
    
    这是 canonical close artifact，operator/main 可直接消费。
    """
    close_id: str
    source_receipt_id: str
    source_execution_id: str
    source_spawn_id: str
    source_dispatch_id: str
    source_registration_id: str
    source_task_id: str
    close_status: CloseStatus
    close_reason: str
    close_time: str
    linkage: Dict[str, str]  # {dispatch_id, spawn_id, execution_id, receipt_id, request_id, ...}
    close_summary: str
    source_request_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "close_version": CLOSE_VERSION,
            "close_id": self.close_id,
            "source_request_id": self.source_request_id,
            "source_receipt_id": self.source_receipt_id,
            "source_execution_id": self.source_execution_id,
            "source_spawn_id": self.source_spawn_id,
            "source_dispatch_id": self.source_dispatch_id,
            "source_registration_id": self.source_registration_id,
            "source_task_id": self.source_task_id,
            "close_status": self.close_status,
            "close_reason": self.close_reason,
            "close_time": self.close_time,
            "linkage": self.linkage,
            "close_summary": self.close_summary,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CallbackAutoCloseArtifact":
        return cls(
            close_id=data.get("close_id", ""),
            source_request_id=data.get("source_request_id"),
            source_receipt_id=data.get("source_receipt_id", ""),
            source_execution_id=data.get("source_execution_id", ""),
            source_spawn_id=data.get("source_spawn_id", ""),
            source_dispatch_id=data.get("source_dispatch_id", ""),
            source_registration_id=data.get("source_registration_id", ""),
            source_task_id=data.get("source_task_id", ""),
            close_status=data.get("close_status", "pending"),
            close_reason=data.get("close_reason", ""),
            close_time=data.get("close_time", ""),
            linkage=data.get("linkage", {}),
            close_summary=data.get("close_summary", ""),
            metadata=data.get("metadata", {}),
        )
    
    def write(self) -> Path:
        """写入 callback close artifact 到文件"""
        _ensure_close_dir()
        close_file = _callback_close_file(self.close_id)
        tmp_file = close_file.with_suffix(".tmp")
        with open(tmp_file, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
        tmp_file.replace(close_file)
        
        # 记录 linkage index
        linkage_keys = _build_linkage_keys(
            self.source_dispatch_id,
            self.source_spawn_id,
            self.source_execution_id,
            self.source_receipt_id,
            self.source_request_id,
        )
        for key in linkage_keys:
            _record_linkage(key, self.close_id)
        
        return close_file


class CallbackCloseKernel:
    """
    Callback close kernel — 从 receipt + request 生成 auto-close artifact。
    
    提供：
    - create_close(): 创建 close artifact
    - emit_close(): emit close（写入 artifact + 记录 linkage）
    """
    
    def __init__(self):
        pass
    
    def _determine_close_status(
        self,
        receipt_status: str,
        request_status: Optional[str],
    ) -> tuple[CloseStatus, str]:
        """
        根据 receipt 和 request status 决定 close status。
        
        Returns:
            (close_status, close_reason)
        """
        if receipt_status == "completed":
            if request_status == "prepared":
                return "closed", "Receipt completed + spawn request prepared = full close"
            elif request_status is None:
                return "partial", "Receipt completed but no spawn request yet (partial close)"
            elif request_status == "blocked":
                return "blocked", "Receipt completed but spawn request blocked"
            elif request_status == "failed":
                return "blocked", "Receipt completed but spawn request failed"
            else:
                return "closed", f"Receipt completed + request status '{request_status}'"
        elif receipt_status == "failed":
            return "blocked", f"Receipt failed: cannot close"
        elif receipt_status == "missing":
            return "pending", "Receipt missing: awaiting completion"
        else:
            return "pending", f"Unknown receipt status: {receipt_status}"
    
    def _build_linkage(
        self,
        receipt_id: str,
        execution_id: str,
        spawn_id: str,
        dispatch_id: str,
        registration_id: str,
        request_id: Optional[str] = None,
    ) -> Dict[str, str]:
        """
        构建完整 linkage 字典。
        """
        linkage = {
            "dispatch_id": dispatch_id,
            "spawn_id": spawn_id,
            "execution_id": execution_id,
            "receipt_id": receipt_id,
            "registration_id": registration_id,
        }
        if request_id:
            linkage["request_id"] = request_id
        return linkage
    
    def _build_close_summary(
        self,
        task_id: str,
        scenario: str,
        close_status: CloseStatus,
        request_status: Optional[str],
    ) -> str:
        """
        构建人类可读的 close summary。
        """
        scenario_label = scenario if scenario else "generic"
        
        if close_status == "closed":
            return f"Task {task_id} ({scenario_label}) fully closed: receipt completed + spawn request {request_status}"
        elif close_status == "partial":
            return f"Task {task_id} ({scenario_label}) partially closed: receipt completed, awaiting spawn request"
        elif close_status == "blocked":
            return f"Task {task_id} ({scenario_label}) blocked: cannot close due to receipt/request status"
        else:
            return f"Task {task_id} ({scenario_label}) pending: awaiting completion"
    
    def create_close(
        self,
        receipt_id: str,
        request_id: Optional[str] = None,
    ) -> CallbackAutoCloseArtifact:
        """
        创建 callback auto-close artifact。
        
        Args:
            receipt_id: Receipt ID
            request_id: Request ID（可选，若尚未 request 则 None）
        
        Returns:
            CallbackAutoCloseArtifact
        """
        # 导入 receipt
        from completion_receipt import get_completion_receipt
        receipt = get_completion_receipt(receipt_id)
        if not receipt:
            raise ValueError(f"Completion receipt {receipt_id} not found")
        
        # 获取 request（如果提供了 request_id）
        request_status = None
        if request_id:
            from sessions_spawn_request import get_spawn_request
            request = get_spawn_request(request_id)
            if request:
                request_status = request.spawn_request_status
        
        # 决定 close status
        close_status, close_reason = self._determine_close_status(
            receipt.receipt_status,
            request_status,
        )
        
        # 构建 linkage
        linkage = self._build_linkage(
            receipt_id=receipt.receipt_id,
            execution_id=receipt.source_spawn_execution_id,
            spawn_id=receipt.source_spawn_id,
            dispatch_id=receipt.source_dispatch_id,
            registration_id=receipt.source_registration_id,
            request_id=request_id,
        )
        
        # 构建 close summary
        scenario = receipt.metadata.get("scenario", "generic")
        close_summary = self._build_close_summary(
            task_id=receipt.source_task_id,
            scenario=scenario,
            close_status=close_status,
            request_status=request_status,
        )
        
        close_id = _generate_close_id()
        
        artifact = CallbackAutoCloseArtifact(
            close_id=close_id,
            source_request_id=request_id,
            source_receipt_id=receipt.receipt_id,
            source_execution_id=receipt.source_spawn_execution_id,
            source_spawn_id=receipt.source_spawn_id,
            source_dispatch_id=receipt.source_dispatch_id,
            source_registration_id=receipt.source_registration_id,
            source_task_id=receipt.source_task_id,
            close_status=close_status,
            close_reason=close_reason,
            close_time=_iso_now(),
            linkage=linkage,
            close_summary=close_summary,
            metadata={
                "source_receipt_status": receipt.receipt_status,
                "source_receipt_time": receipt.receipt_time,
                "scenario": scenario,
                "owner": receipt.metadata.get("owner", ""),
                "truth_anchor": receipt.metadata.get("truth_anchor"),
                "request_status": request_status,
            },
        )
        
        return artifact
    
    def emit_close(
        self,
        receipt_id: str,
        request_id: Optional[str] = None,
    ) -> CallbackAutoCloseArtifact:
        """
        Emit close：创建 artifact -> 写入文件 -> 记录 linkage。
        
        Args:
            receipt_id: Receipt ID
            request_id: Request ID（可选）
        
        Returns:
            CallbackAutoCloseArtifact（已写入文件）
        """
        # 1. Create artifact
        artifact = self.create_close(receipt_id, request_id)
        
        # 2. Write artifact + record linkage
        artifact.write()
        
        return artifact


def create_auto_close(
    receipt_id: str,
    request_id: Optional[str] = None,
) -> CallbackAutoCloseArtifact:
    """
    Convenience function: 从 receipt 创建 auto-close artifact。
    
    Args:
        receipt_id: Receipt ID
        request_id: Request ID（可选）
    
    Returns:
        CallbackAutoCloseArtifact（已写入文件）
    """
    kernel = CallbackCloseKernel()
    return kernel.emit_close(receipt_id, request_id)


def list_auto_closes(
    receipt_id: Optional[str] = None,
    execution_id: Optional[str] = None,
    spawn_id: Optional[str] = None,
    dispatch_id: Optional[str] = None,
    registration_id: Optional[str] = None,
    task_id: Optional[str] = None,
    close_status: Optional[str] = None,
    limit: int = 100,
) -> List[CallbackAutoCloseArtifact]:
    """
    列出 callback auto-close artifacts。
    
    Args:
        receipt_id: 按 receipt_id 过滤
        execution_id: 按 execution_id 过滤
        spawn_id: 按 spawn_id 过滤
        dispatch_id: 按 dispatch_id 过滤
        registration_id: 按 registration_id 过滤
        task_id: 按 task_id 过滤
        close_status: 按 close_status 过滤
        limit: 最大返回数量
    
    Returns:
        CallbackAutoCloseArtifact 列表
    """
    _ensure_close_dir()
    
    closes = []
    for close_file in CALLBACK_CLOSE_DIR.glob("*.json"):
        if close_file.name == "close_linkage_index.json":
            continue
        
        try:
            with open(close_file, "r") as f:
                data = json.load(f)
            artifact = CallbackAutoCloseArtifact.from_dict(data)
            
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
            if close_status and artifact.close_status != close_status:
                continue
            
            closes.append(artifact)
        except (json.JSONDecodeError, KeyError):
            pass
    
    # 按 close_id 排序
    closes.sort(key=lambda c: c.close_id)
    
    return closes[:limit]


def get_auto_close(close_id: str) -> Optional[CallbackAutoCloseArtifact]:
    """
    获取 callback auto-close artifact。
    
    Args:
        close_id: Close ID
    
    Returns:
        CallbackAutoCloseArtifact，不存在则返回 None
    """
    close_file = _callback_close_file(close_id)
    if not close_file.exists():
        return None
    
    with open(close_file, "r") as f:
        data = json.load(f)
    
    return CallbackAutoCloseArtifact.from_dict(data)


def find_close_by_linkage(
    dispatch_id: Optional[str] = None,
    spawn_id: Optional[str] = None,
    execution_id: Optional[str] = None,
    receipt_id: Optional[str] = None,
    request_id: Optional[str] = None,
) -> Optional[CallbackAutoCloseArtifact]:
    """
    通过任意 linkage ID 查找 close artifact。
    
    Args:
        dispatch_id: Dispatch ID
        spawn_id: Spawn ID
        execution_id: Execution ID
        receipt_id: Receipt ID
        request_id: Request ID
    
    Returns:
        CallbackAutoCloseArtifact，不存在则返回 None
    """
    index = _load_linkage_index()
    close_id = None
    
    # 按优先级查找
    if receipt_id and not close_id:
        key = f"by_receipt:{receipt_id}"
        close_id = index.get(key)
    if execution_id and not close_id:
        key = f"by_execution:{execution_id}"
        close_id = index.get(key)
    if spawn_id and not close_id:
        key = f"by_spawn:{spawn_id}"
        close_id = index.get(key)
    if dispatch_id and not close_id:
        key = f"by_dispatch:{dispatch_id}"
        close_id = index.get(key)
    if request_id and not close_id:
        key = f"by_request:{request_id}"
        close_id = index.get(key)
    
    if close_id:
        return get_auto_close(close_id)
    
    return None


def build_close_summary(
    task_id: Optional[str] = None,
    scenario: Optional[str] = None,
    limit: int = 10,
) -> Dict[str, Any]:
    """
    构建闭环状态 summary（供 operator/main 快速查看）。
    
    Args:
        task_id: 按 task_id 过滤（可选）
        scenario: 按 scenario 过滤（可选）
        limit: 最大返回数量
    
    Returns:
        {
            "total_closes": int,
            "by_status": {closed: int, pending: int, blocked: int, partial: int},
            "recent_closes": List[Dict],
        }
    """
    closes = list_auto_closes(task_id=task_id, limit=limit)
    
    # 按 scenario 过滤
    if scenario:
        closes = [c for c in closes if c.metadata.get("scenario") == scenario]
    
    # 统计 by status
    by_status = {"closed": 0, "pending": 0, "blocked": 0, "partial": 0}
    for c in closes:
        if c.close_status in by_status:
            by_status[c.close_status] += 1
    
    # 最近 closes
    recent_closes = [
        {
            "close_id": c.close_id,
            "task_id": c.source_task_id,
            "scenario": c.metadata.get("scenario", ""),
            "close_status": c.close_status,
            "close_summary": c.close_summary,
            "close_time": c.close_time,
            "linkage": c.linkage,
        }
        for c in closes[:5]
    ]
    
    return {
        "total_closes": len(closes),
        "by_status": by_status,
        "recent_closes": recent_closes,
    }


# ============ Full pipeline helper (receipt -> request -> close) ============

def run_full_close_pipeline(
    receipt_id: str,
) -> Dict[str, Any]:
    """
    运行完整 pipeline：receipt -> request -> auto-close。
    
    Args:
        receipt_id: Receipt ID
    
    Returns:
        {
            "receipt": CompletionReceiptArtifact,
            "request": SessionsSpawnRequest,
            "close": CallbackAutoCloseArtifact,
        }
    """
    from completion_receipt import get_completion_receipt
    from sessions_spawn_request import SpawnRequestKernel
    
    # 1. Get receipt
    receipt = get_completion_receipt(receipt_id)
    if not receipt:
        raise ValueError(f"Completion receipt {receipt_id} not found")
    
    # 2. Create request
    request_kernel = SpawnRequestKernel()
    request = request_kernel.emit_request(receipt)
    
    # 3. Create close
    close_kernel = CallbackCloseKernel()
    close = close_kernel.emit_close(receipt_id, request.request_id if request.spawn_request_status == "prepared" else None)
    
    return {
        "receipt": receipt,
        "request": request,
        "close": close,
    }


# CLI 入口
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python callback_auto_close.py create <receipt_id> [--request <request_id>]")
        print("  python callback_auto_close.py list [--status <status>] [--task <task_id>]")
        print("  python callback_auto_close.py get <close_id>")
        print("  python callback_auto_close.py find --receipt <receipt_id>")
        print("  python callback_auto_close.py summary [--scenario <scenario>]")
        print("  python callback_auto_close.py pipeline <receipt_id>")
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == "create":
        if len(sys.argv) < 3:
            print("Error: missing receipt_id")
            sys.exit(1)
        
        receipt_id = sys.argv[2]
        request_id = None
        if "--request" in sys.argv:
            idx = sys.argv.index("--request")
            if idx + 1 < len(sys.argv):
                request_id = sys.argv[idx + 1]
        
        artifact = create_auto_close(receipt_id, request_id)
        print(json.dumps(artifact.to_dict(), indent=2))
        print(f"\nCallback close artifact written to: {_callback_close_file(artifact.close_id)}")
    
    elif cmd == "list":
        status = None
        task_id = None
        if "--status" in sys.argv:
            idx = sys.argv.index("--status")
            if idx + 1 < len(sys.argv):
                status = sys.argv[idx + 1]
        if "--task" in sys.argv:
            idx = sys.argv.index("--task")
            if idx + 1 < len(sys.argv):
                task_id = sys.argv[idx + 1]
        
        closes = list_auto_closes(
            task_id=task_id,
            close_status=status,
        )
        print(json.dumps([c.to_dict() for c in closes], indent=2))
    
    elif cmd == "get":
        if len(sys.argv) < 3:
            print("Error: missing close_id")
            sys.exit(1)
        
        close_id = sys.argv[2]
        artifact = get_auto_close(close_id)
        if artifact:
            print(json.dumps(artifact.to_dict(), indent=2))
        else:
            print(f"Callback close {close_id} not found")
            sys.exit(1)
    
    elif cmd == "find":
        receipt_id = None
        dispatch_id = None
        if "--receipt" in sys.argv:
            idx = sys.argv.index("--receipt")
            if idx + 1 < len(sys.argv):
                receipt_id = sys.argv[idx + 1]
        if "--dispatch" in sys.argv:
            idx = sys.argv.index("--dispatch")
            if idx + 1 < len(sys.argv):
                dispatch_id = sys.argv[idx + 1]
        
        artifact = find_close_by_linkage(
            receipt_id=receipt_id,
            dispatch_id=dispatch_id,
        )
        if artifact:
            print(json.dumps(artifact.to_dict(), indent=2))
        else:
            print("Callback close not found")
            sys.exit(1)
    
    elif cmd == "summary":
        scenario = None
        if "--scenario" in sys.argv:
            idx = sys.argv.index("--scenario")
            if idx + 1 < len(sys.argv):
                scenario = sys.argv[idx + 1]
        
        summary = build_close_summary(scenario=scenario)
        print(json.dumps(summary, indent=2))
    
    elif cmd == "pipeline":
        if len(sys.argv) < 3:
            print("Error: missing receipt_id")
            sys.exit(1)
        
        receipt_id = sys.argv[2]
        
        try:
            result = run_full_close_pipeline(receipt_id)
            print("=== COMPLETION RECEIPT ===")
            print(json.dumps(result["receipt"].to_dict(), indent=2))
            print("\n=== SPAWN REQUEST ===")
            print(json.dumps(result["request"].to_dict(), indent=2))
            print("\n=== CALLBACK AUTO-CLOSE ===")
            print(json.dumps(result["close"].to_dict(), indent=2))
            print(f"\nPipeline complete. Close ID: {result['close'].close_id}")
        except ValueError as e:
            print(f"Error: {e}")
            sys.exit(1)
    
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
