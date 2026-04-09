#!/usr/bin/env python3
"""
lineage.py — Minimal Parent-Child Lineage Tracking

目标：提供最小的 lineage 数据结构，用于追踪任务之间的父子关系。

核心字段：
- lineage_id: 唯一标识
- parent_id: 父任务 ID (dispatch_id / spawn_id / execution_id 等)
- child_id: 子任务 ID
- batch_id: 批次 ID (可选，用于 grouping)
- relation_type: 关系类型 (spawn / continuation / followup / retry / fanin)
- created_at: 创建时间戳
- metadata: 额外元数据 (可选)

当前阶段：最小数据结构 + 序列化/反序列化 + 最小接线到 sessions_spawn_bridge

这是极小切片实现，不做完整的 fan-in / parent-child helper。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

__all__ = [
    "LINEAGE_VERSION",
    "RelationType",
    "LineageRecord",
    "LineageStore",
    "create_lineage_record",
    "list_lineage_records",
    "get_lineage_record",
    "get_lineage_by_parent",
    "get_lineage_by_child",
    "get_lineage_by_batch",
    "check_fanin_readiness",
    "build_fanin_closeout_context",
    "LINEAGE_STORE_DIR",
]

LINEAGE_VERSION = "lineage_v1"

RelationType = Literal["spawn", "continuation", "followup", "retry", "fanin", "other"]

# Lineage store 存储目录
LINEAGE_STORE_DIR = Path(
    os.environ.get(
        "OPENCLAW_LINEAGE_STORE_DIR",
        Path.home() / ".openclaw" / "shared-context" / "lineage",
    )
)

# Lineage index 文件
LINEAGE_INDEX_FILE = LINEAGE_STORE_DIR / "lineage_index.json"


def _ensure_lineage_dir():
    """确保 lineage 目录存在"""
    LINEAGE_STORE_DIR.mkdir(parents=True, exist_ok=True)


def _lineage_file(lineage_id: str) -> Path:
    """返回 lineage record 文件路径"""
    return LINEAGE_STORE_DIR / f"{lineage_id}.json"


def _iso_now() -> str:
    """返回当前 ISO-8601 时间戳"""
    return datetime.now(timezone.utc).isoformat()


def _generate_lineage_id() -> str:
    """生成稳定 lineage ID"""
    import uuid
    return f"lineage_{uuid.uuid4().hex[:12]}"


@dataclass
class LineageRecord:
    """
    Lineage record — 最小父子关系追踪
    
    核心字段：
    - lineage_id: 唯一标识
    - parent_id: 父任务 ID
    - child_id: 子任务 ID
    - batch_id: 批次 ID (可选)
    - relation_type: 关系类型
    - created_at: 创建时间戳
    - metadata: 额外元数据 (可选)
    """
    lineage_id: str
    parent_id: str
    child_id: str
    batch_id: Optional[str] = None
    relation_type: RelationType = "spawn"
    created_at: str = field(default_factory=_iso_now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "lineage_id": self.lineage_id,
            "parent_id": self.parent_id,
            "child_id": self.child_id,
            "batch_id": self.batch_id,
            "relation_type": self.relation_type,
            "created_at": self.created_at,
            "metadata": self.metadata,
            "version": LINEAGE_VERSION,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LineageRecord":
        """从字典反序列化"""
        return cls(
            lineage_id=data.get("lineage_id", ""),
            parent_id=data.get("parent_id", ""),
            child_id=data.get("child_id", ""),
            batch_id=data.get("batch_id"),
            relation_type=data.get("relation_type", "spawn"),
            created_at=data.get("created_at", _iso_now()),
            metadata=data.get("metadata", {}),
        )
    
    def to_json(self, indent: int = 2) -> str:
        """序列化为 JSON 字符串"""
        return json.dumps(self.to_dict(), indent=indent)
    
    @classmethod
    def from_json(cls, json_str: str) -> "LineageRecord":
        """从 JSON 字符串反序列化"""
        return cls.from_dict(json.loads(json_str))


def _load_lineage_index() -> Dict[str, str]:
    """
    加载 lineage index（lineage_id -> file_path 映射）。
    
    用于快速查询。
    """
    _ensure_lineage_dir()
    if not LINEAGE_INDEX_FILE.exists():
        return {}
    
    try:
        with open(LINEAGE_INDEX_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, KeyError):
        return {}


def _save_lineage_index(index: Dict[str, str]):
    """保存 lineage index"""
    _ensure_lineage_dir()
    tmp_file = LINEAGE_INDEX_FILE.with_suffix(".tmp")
    with open(tmp_file, "w") as f:
        json.dump(index, f, indent=2)
    tmp_file.replace(LINEAGE_INDEX_FILE)


def _record_lineage_index(lineage_id: str, file_path: Path):
    """记录 lineage index"""
    index = _load_lineage_index()
    index[lineage_id] = str(file_path)
    _save_lineage_index(index)


@dataclass
class LineageStore:
    """
    Lineage store — lineage record 存储管理器
    
    提供 CRUD 操作和查询接口。
    """
    
    def create_record(
        self,
        parent_id: str,
        child_id: str,
        batch_id: Optional[str] = None,
        relation_type: RelationType = "spawn",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> LineageRecord:
        """
        创建新的 lineage record
        
        Args:
            parent_id: 父任务 ID
            child_id: 子任务 ID
            batch_id: 批次 ID (可选)
            relation_type: 关系类型
            metadata: 额外元数据
        
        Returns:
            LineageRecord: 创建的 record
        """
        record = LineageRecord(
            lineage_id=_generate_lineage_id(),
            parent_id=parent_id,
            child_id=child_id,
            batch_id=batch_id,
            relation_type=relation_type,
            metadata=metadata or {},
        )
        
        # 保存到文件（原子写入）
        from utils.io import atomic_write_text
        file_path = _lineage_file(record.lineage_id)
        _ensure_lineage_dir()
        atomic_write_text(file_path, record.to_json())
        
        # 更新索引
        _record_lineage_index(record.lineage_id, file_path)
        
        return record
    
    def get_record(self, lineage_id: str) -> Optional[LineageRecord]:
        """
        获取 lineage record
        
        Args:
            lineage_id: lineage ID
        
        Returns:
            LineageRecord 或 None
        """
        file_path = _lineage_file(lineage_id)
        if not file_path.exists():
            return None
        
        with open(file_path, "r") as f:
            return LineageRecord.from_json(f.read())
    
    def list_records(
        self,
        parent_id: Optional[str] = None,
        child_id: Optional[str] = None,
        batch_id: Optional[str] = None,
        relation_type: Optional[RelationType] = None,
    ) -> List[LineageRecord]:
        """
        查询 lineage record 列表
        
        Args:
            parent_id: 按父 ID 过滤
            child_id: 按子 ID 过滤
            batch_id: 按批次 ID 过滤
            relation_type: 按关系类型过滤
        
        Returns:
            LineageRecord 列表
        """
        records = []
        
        for lineage_id in _load_lineage_index().keys():
            record = self.get_record(lineage_id)
            if record is None:
                continue
            
            # 应用过滤器
            if parent_id and record.parent_id != parent_id:
                continue
            if child_id and record.child_id != child_id:
                continue
            if batch_id and record.batch_id != batch_id:
                continue
            if relation_type and record.relation_type != relation_type:
                continue
            
            records.append(record)
        
        return records
    
    def get_by_parent(self, parent_id: str) -> List[LineageRecord]:
        """获取指定父任务的所有子任务"""
        return self.list_records(parent_id=parent_id)
    
    def get_by_child(self, child_id: str) -> List[LineageRecord]:
        """获取指定子任务的所有父任务"""
        return self.list_records(child_id=child_id)
    
    def get_by_batch(self, batch_id: str) -> List[LineageRecord]:
        """获取指定批次的所有 lineage"""
        return self.list_records(batch_id=batch_id)


# 全局 store 实例
_default_store: Optional[LineageStore] = None


def _get_default_store() -> LineageStore:
    """获取默认 store 实例"""
    global _default_store
    if _default_store is None:
        _default_store = LineageStore()
    return _default_store


def create_lineage_record(
    parent_id: str,
    child_id: str,
    batch_id: Optional[str] = None,
    relation_type: RelationType = "spawn",
    metadata: Optional[Dict[str, Any]] = None,
) -> LineageRecord:
    """
    创建 lineage record (便捷函数)
    
    Args:
        parent_id: 父任务 ID
        child_id: 子任务 ID
        batch_id: 批次 ID (可选)
        relation_type: 关系类型
        metadata: 额外元数据
    
    Returns:
        LineageRecord: 创建的 record
    """
    return _get_default_store().create_record(
        parent_id=parent_id,
        child_id=child_id,
        batch_id=batch_id,
        relation_type=relation_type,
        metadata=metadata,
    )


def list_lineage_records(
    parent_id: Optional[str] = None,
    child_id: Optional[str] = None,
    batch_id: Optional[str] = None,
    relation_type: Optional[RelationType] = None,
) -> List[LineageRecord]:
    """
    查询 lineage record 列表 (便捷函数)
    
    Args:
        parent_id: 按父 ID 过滤
        child_id: 按子 ID 过滤
        batch_id: 按批次 ID 过滤
        relation_type: 按关系类型过滤
    
    Returns:
        LineageRecord 列表
    """
    return _get_default_store().list_records(
        parent_id=parent_id,
        child_id=child_id,
        batch_id=batch_id,
        relation_type=relation_type,
    )


def get_lineage_record(lineage_id: str) -> Optional[LineageRecord]:
    """
    获取 lineage record (便捷函数)
    
    Args:
        lineage_id: lineage ID
    
    Returns:
        LineageRecord 或 None
    """
    return _get_default_store().get_record(lineage_id)


def get_lineage_by_parent(parent_id: str) -> List[LineageRecord]:
    """
    获取指定父任务的所有 lineage (便捷函数)
    
    Args:
        parent_id: 父任务 ID
    
    Returns:
        LineageRecord 列表
    """
    return _get_default_store().get_by_parent(parent_id)


def get_lineage_by_child(child_id: str) -> List[LineageRecord]:
    """
    获取指定子任务的所有 lineage (便捷函数)
    
    Args:
        child_id: 子任务 ID
    
    Returns:
        LineageRecord 列表
    """
    return _get_default_store().get_by_child(child_id)


def get_lineage_by_batch(batch_id: str) -> List[LineageRecord]:
    """
    获取指定批次的所有 lineage (便捷函数)
    
    Args:
        batch_id: 批次 ID
    
    Returns:
        LineageRecord 列表
    """
    return _get_default_store().get_by_batch(batch_id)


def check_fanin_readiness(batch_id: str) -> Dict[str, Any]:
    """
    检查 batch 是否 ready to fan-in
    
    基于 lineage 和 closeout 状态判断：
    1. 查询该 batch 的所有 lineage records
    2. 检查每个 child 是否有 closeout 且状态为 complete
    3. 返回 readiness 判定结果
    
    这是极小切片实现，只做状态查询，不触发任何动作。
    
    Args:
        batch_id: 批次 ID
    
    Returns:
        Dict with:
        - ready: bool - 是否 ready to fan-in
        - reason: str - 判定原因
        - total_children: int - 子任务总数
        - completed_children: int - 已完成的子任务数
        - pending_children: List[str] - 未完成的子任务 ID 列表
        - details: Dict - 详细信息
    
    Example:
        >>> result = check_fanin_readiness("batch_001")
        >>> if result["ready"]:
        ...     proceed_to_fanin()
    """
    # 查询该 batch 的所有 lineage records
    records = get_lineage_by_batch(batch_id)
    
    if not records:
        return {
            "ready": False,
            "reason": "No lineage records found for batch",
            "total_children": 0,
            "completed_children": 0,
            "pending_children": [],
            "details": {"batch_id": batch_id, "error": "no_lineage"},
        }
    
    # 提取所有 child IDs
    child_ids = [r.child_id for r in records]
    total_children = len(child_ids)
    
    # 检查每个 child 的 closeout 状态
    completed_children = 0
    pending_children = []
    child_details = {}
    
    try:
        from closeout_tracker import get_closeout
        
        for child_id in child_ids:
            closeout = get_closeout(child_id)
            
            if closeout is None:
                # 没有 closeout 记录
                pending_children.append(child_id)
                child_details[child_id] = {"status": "no_closeout"}
            elif closeout.closeout_status == "complete":
                # closeout 已完成
                completed_children += 1
                child_details[child_id] = {
                    "status": "complete",
                    "closeout_id": closeout.closeout_id,
                }
            else:
                # closeout 存在但未完成
                pending_children.append(child_id)
                child_details[child_id] = {
                    "status": closeout.closeout_status,
                    "closeout_id": closeout.closeout_id,
                }
    
    except ImportError:
        # closeout_tracker 不可用时，退化到只检查 lineage
        # 假设所有有 lineage 的 child 都是 pending
        pending_children = child_ids.copy()
        child_details = {cid: {"status": "unknown_no_closeout_module"} for cid in child_ids}
    
    # 判定是否 ready
    ready = len(pending_children) == 0 and total_children > 0
    
    if ready:
        reason = f"All {total_children} children completed"
    elif total_children == 0:
        reason = "No children in batch"
    else:
        reason = f"{len(pending_children)}/{total_children} children pending"
    
    return {
        "ready": ready,
        "reason": reason,
        "total_children": total_children,
        "completed_children": completed_children,
        "pending_children": pending_children,
        "details": {
            "batch_id": batch_id,
            "children": child_details,
        },
    }


@dataclass
class FaninCloseoutContext:
    """
    Fan-in Closeout Context — 整合 lineage / fan-in readiness / closeout glue 的上下文。
    
    这是 P0 中等批次整合点 (batch-b-parent-child-fanin-closeout-integration) 的核心数据结构。
    
    核心字段：
    - batch_id: 批次 ID
    - readiness: fan-in readiness 检查结果
    - children: 所有 child 的 closeout glue input 列表
    - ready_to_fanin: 是否 ready to fan-in
    - fanin_decision: fan-in 决策建议
    - metadata: 额外元数据
    
    使用示例：
    ```python
    from lineage import build_fanin_closeout_context
    
    ctx = build_fanin_closeout_context("batch_001")
    if ctx.ready_to_fanin:
        proceed_to_fanin(ctx.children)
    else:
        wait_for_children(ctx.readiness["pending_children"])
    ```
    """
    batch_id: str
    readiness: Dict[str, Any]
    children: List[Dict[str, Any]]
    ready_to_fanin: bool
    fanin_decision: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "batch_id": self.batch_id,
            "readiness": self.readiness,
            "children": self.children,
            "ready_to_fanin": self.ready_to_fanin,
            "fanin_decision": self.fanin_decision,
            "metadata": self.metadata,
        }


def build_fanin_closeout_context(batch_id: str) -> FaninCloseoutContext:
    """
    构建 Fan-in Closeout Context — 整合 lineage / fan-in readiness / closeout glue。
    
    这是 P0 中等批次整合点 (batch-b-parent-child-fanin-closeout-integration) 的核心函数。
    
    核心流程：
    1. 查询 batch 的所有 lineage records (lineage 能力)
    2. 检查 fan-in readiness (fan-in readiness 能力)
    3. 为每个 child 生成 closeout glue input (closeout glue 能力)
    4. 返回整合的上下文
    
    Args:
        batch_id: 批次 ID
    
    Returns:
        FaninCloseoutContext: 整合的上下文
    
    整合能力：
    - 基于 lineage 查 children
    - 基于 closeout 查 readiness
    - 基于 completion receipt 生成 closeout glue input
    
    决策逻辑：
    - ready_to_fanin = readiness["ready"]
    - fanin_decision:
      - "proceed" if ready_to_fanin
      - "wait" if not ready (有 pending children)
      - "review" if no lineage found
    
    使用示例：
    ```python
    ctx = build_fanin_closeout_context("batch_001")
    
    print(f"Batch {ctx.batch_id}:")
    print(f"  Ready to fan-in: {ctx.ready_to_fanin}")
    print(f"  Decision: {ctx.fanin_decision}")
    print(f"  Total children: {ctx.readiness['total_children']}")
    print(f"  Completed: {ctx.readiness['completed_children']}")
    
    if ctx.ready_to_fanin:
        # 所有 children 完成，可以 fan-in
        for child_glue in ctx.children:
            process_fanin_input(child_glue)
    else:
        # 等待 pending children
        for pending_id in ctx.readiness["pending_children"]:
            wait_for_child(pending_id)
    ```
    """
    # Step 1: 查询 lineage records
    records = get_lineage_by_batch(batch_id)
    
    if not records:
        # 没有 lineage records
        return FaninCloseoutContext(
            batch_id=batch_id,
            readiness={
                "ready": False,
                "reason": "No lineage records found for batch",
                "total_children": 0,
                "completed_children": 0,
                "pending_children": [],
                "details": {"batch_id": batch_id, "error": "no_lineage"},
            },
            children=[],
            ready_to_fanin=False,
            fanin_decision="review",
            metadata={"error": "no_lineage"},
        )
    
    # Step 2: 检查 fan-in readiness
    readiness = check_fanin_readiness(batch_id)
    
    # Step 3: 为每个 child 生成 closeout glue input
    children_glue = []
    
    for child_id in [r.child_id for r in records]:
        child_detail = readiness["details"]["children"].get(child_id, {})
        child_status = child_detail.get("status", "unknown")
        
        # 尝试从 completion receipt 生成 closeout glue input
        glue_input = _build_child_closeout_glue(child_id, child_status)
        
        if glue_input:
            children_glue.append(glue_input)
    
    # Step 4: 决定 fan-in decision
    ready_to_fanin = readiness["ready"]
    
    if ready_to_fanin:
        fanin_decision = "proceed"
    elif readiness["total_children"] == 0:
        fanin_decision = "review"
    else:
        fanin_decision = "wait"
    
    return FaninCloseoutContext(
        batch_id=batch_id,
        readiness=readiness,
        children=children_glue,
        ready_to_fanin=ready_to_fanin,
        fanin_decision=fanin_decision,
        metadata={
            "integration_version": "fanin_closeout_v1",
            "generated_at": _iso_now(),
        },
    )


def _build_child_closeout_glue(child_id: str, child_status: str) -> Optional[Dict[str, Any]]:
    """
    为单个 child 构建 closeout glue input。
    
    尝试从 completion receipt 和 closeout 生成 glue input。
    
    Args:
        child_id: child ID
        child_status: child 状态 (from readiness check)
    
    Returns:
        Dict with glue input, or None if not available
    """
    glue_input = {
        "child_id": child_id,
        "status": child_status,
        "glue_available": False,
    }
    
    # 尝试从 closeout_tracker 获取 closeout
    try:
        from closeout_tracker import get_closeout
        closeout = get_closeout(child_id)
        
        if closeout:
            glue_input["closeout_id"] = closeout.closeout_id
            glue_input["closeout_status"] = closeout.closeout_status
            glue_input["push_required"] = closeout.push_required
            glue_input["push_status"] = closeout.push_status
            
            # 从 continuation contract 提取 continuation 字段
            glue_input["next_step"] = closeout.continuation_contract.next_step
            glue_input["next_owner"] = closeout.continuation_contract.next_owner
            glue_input["stopped_because"] = closeout.continuation_contract.stopped_because
            
            # 尝试从 completion receipt 生成更丰富的 glue
            try:
                from completion_receipt import get_completion_receipt_by_spawn_id
                receipt = get_completion_receipt_by_spawn_id(child_id)
                
                if receipt:
                    glue_input["receipt_id"] = receipt.receipt_id
                    glue_input["receipt_status"] = receipt.receipt_status
                    glue_input["result_summary"] = receipt.result_summary
                    
                    # 使用 closeout_glue 模块进行映射
                    try:
                        from closeout_glue import map_receipt_to_closeout
                        closeout_glue_input = map_receipt_to_closeout(receipt)
                        glue_input["glue_input"] = closeout_glue_input.to_dict()
                        glue_input["glue_available"] = True
                    except ImportError:
                        # closeout_glue 不可用时，手动构建
                        glue_input["dispatch_readiness"] = (
                            "ready" if receipt.receipt_status == "completed" else "blocked"
                        )
                        glue_input["glue_available"] = True
                
            except (ImportError, AttributeError):
                # completion_receipt 不可用或没有 get_completion_receipt_by_spawn_id
                pass
            
            glue_input["glue_available"] = True
    
    except ImportError:
        # closeout_tracker 不可用
        pass
    
    return glue_input


# CLI 入口
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python lineage.py <command> [args]")
        print("Commands:")
        print("  create <parent_id> <child_id> [batch_id] [relation_type]")
        print("  get <lineage_id>")
        print("  list [--parent <id>] [--child <id>] [--batch <id>]")
        sys.exit(1)
    
    cmd = sys.argv[1]
    store = _get_default_store()
    
    if cmd == "create":
        if len(sys.argv) < 4:
            print("Usage: python lineage.py create <parent_id> <child_id> [batch_id] [relation_type]")
            sys.exit(1)
        parent_id = sys.argv[2]
        child_id = sys.argv[3]
        batch_id = sys.argv[4] if len(sys.argv) > 4 else None
        relation_type = sys.argv[5] if len(sys.argv) > 5 else "spawn"
        
        record = store.create_record(
            parent_id=parent_id,
            child_id=child_id,
            batch_id=batch_id,
            relation_type=relation_type,  # type: ignore
        )
        print(record.to_json())
    
    elif cmd == "get":
        if len(sys.argv) < 3:
            print("Usage: python lineage.py get <lineage_id>")
            sys.exit(1)
        lineage_id = sys.argv[2]
        record = store.get_record(lineage_id)
        if record:
            print(record.to_json())
        else:
            print(f"Lineage record {lineage_id} not found")
            sys.exit(1)
    
    elif cmd == "list":
        parent_id = None
        child_id = None
        batch_id = None
        
        i = 2
        while i < len(sys.argv):
            if sys.argv[i] == "--parent" and i + 1 < len(sys.argv):
                parent_id = sys.argv[i + 1]
                i += 2
            elif sys.argv[i] == "--child" and i + 1 < len(sys.argv):
                child_id = sys.argv[i + 1]
                i += 2
            elif sys.argv[i] == "--batch" and i + 1 < len(sys.argv):
                batch_id = sys.argv[i + 1]
                i += 2
            else:
                i += 1
        
        records = store.list_records(
            parent_id=parent_id,
            child_id=child_id,
            batch_id=batch_id,
        )
        print(json.dumps([r.to_dict() for r in records], indent=2))
    
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
