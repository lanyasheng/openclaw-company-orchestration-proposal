#!/usr/bin/env python3
"""
trading_batch_spec.py — Trading Batch Spec Schema & Loader

定义 machine-readable trading batch spec，用于描述 T0/T1/T2/T3/T4 队列的：
- batch 定义（ID、名称、描述、WS 范围）
- 前置条件（依赖的 batch、required artifacts）
- 续批规则（completion_gate、next_batch_rules）
- 安全门（auto_continue、stop_at_gate、production_blockers）

这是 canonical schema，trading repo 的 batch spec 必须与此兼容。

设计原则：
1. 机器可读（YAML/JSON），可被 orchestrator 直接消费
2. 向后兼容现有 handoff_schema/continuation_contract
3. 默认安全（auto_continue=false，除非显式启用）
4. 清晰的 stop-at-gate 语义
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional
import json
import yaml

__all__ = [
    "BatchStatus",
    "CompletionGate",
    "NextBatchRule",
    "SafetyGate",
    "TradingBatchSpec",
    "TradingBatchSpecLoader",
    "load_batch_spec",
    "validate_batch_spec",
    "TRADING_BATCH_SPEC_VERSION",
]

TRADING_BATCH_SPEC_VERSION = "trading_batch_spec_v1"


class BatchStatus(str, Enum):
    """Batch 状态"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


class CompletionGate(str, Enum):
    """完成门（决定是否可以续批）"""
    PASS = "PASS"              # 完全通过，可自动续批
    CONDITIONAL = "CONDITIONAL"  # 有条件通过，需人工确认
    FAIL = "FAIL"              # 失败，阻止续批
    DRY_RUN_PASS = "DRY_RUN_PASS"  # 干跑通过，可续批到下一阶段
    DRY_RUN_FAIL = "DRY_RUN_FAIL"  # 干跑失败，需修复


@dataclass
class SafetyGate:
    """
    安全门 — 控制自动续批的安全边界。
    
    核心字段：
    - auto_continue: 是否允许自动续批（默认 false）
    - stop_at_gate: 是否在生产动作前停止（默认 true）
    - production_blockers: 生产级 blocker 列表
    - require_manual_approval: 是否需要人工审批
    - allowed_dispatch_backends: 允许的 dispatch backend 列表
    """
    auto_continue: bool = False
    stop_at_gate: bool = True
    production_blockers: List[str] = field(default_factory=list)
    require_manual_approval: bool = True
    allowed_dispatch_backends: List[str] = field(default_factory=lambda: ["subagent", "tmux"])
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "auto_continue": self.auto_continue,
            "stop_at_gate": self.stop_at_gate,
            "production_blockers": self.production_blockers,
            "require_manual_approval": self.require_manual_approval,
            "allowed_dispatch_backends": self.allowed_dispatch_backends,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SafetyGate":
        return cls(
            auto_continue=data.get("auto_continue", False),
            stop_at_gate=data.get("stop_at_gate", True),
            production_blockers=data.get("production_blockers", []),
            require_manual_approval=data.get("require_manual_approval", True),
            allowed_dispatch_backends=data.get("allowed_dispatch_backends", ["subagent", "tmux"]),
        )
    
    def is_safe_to_continue(self, completion_gate: CompletionGate) -> tuple[bool, str]:
        """
        检查是否可以安全续批。
        
        Returns:
            (is_safe, reason)
        """
        if not self.auto_continue:
            return False, "auto_continue is disabled"
        
        if completion_gate == CompletionGate.FAIL:
            return False, "completion_gate is FAIL"
        
        if completion_gate == CompletionGate.DRY_RUN_FAIL:
            return False, "completion_gate is DRY_RUN_FAIL"
        
        if self.production_blockers:
            return False, f"production_blockers: {', '.join(self.production_blockers)}"
        
        if completion_gate == CompletionGate.CONDITIONAL and self.require_manual_approval:
            return False, "CONDITIONAL gate requires manual approval"
        
        return True, "safe to continue"


@dataclass
class NextBatchRule:
    """
    下一批规则 — 定义当前 batch 完成后如何决定下一批。
    
    核心字段：
    - trigger_gate: 触发此规则的 completion gate（PASS / DRY_RUN_PASS / CONDITIONAL）
    - next_batch_id: 下一批 ID
    - next_batch_description: 下一批描述
    - priority: 优先级（多个规则匹配时，优先级高的优先）
    - conditions: 额外条件（可选）
    - dispatch_profile: dispatch profile（generic_subagent / coding / interactive_observable）
    - executor: 执行器（subagent / claude_code / browser / message）
    """
    trigger_gate: CompletionGate
    next_batch_id: str
    next_batch_description: str
    priority: int = 0
    conditions: Dict[str, Any] = field(default_factory=dict)
    dispatch_profile: str = "generic_subagent"
    executor: str = "subagent"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "trigger_gate": self.trigger_gate.value,
            "next_batch_id": self.next_batch_id,
            "next_batch_description": self.next_batch_description,
            "priority": self.priority,
            "conditions": self.conditions,
            "dispatch_profile": self.dispatch_profile,
            "executor": self.executor,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NextBatchRule":
        return cls(
            trigger_gate=CompletionGate(data.get("trigger_gate", "PASS")),
            next_batch_id=data.get("next_batch_id", ""),
            next_batch_description=data.get("next_batch_description", ""),
            priority=data.get("priority", 0),
            conditions=data.get("conditions", {}),
            dispatch_profile=data.get("dispatch_profile", "generic_subagent"),
            executor=data.get("executor", "subagent"),
        )
    
    def matches(self, completion_gate: CompletionGate, context: Optional[Dict[str, Any]] = None) -> bool:
        """
        检查此规则是否匹配当前 completion gate。
        
        Args:
            completion_gate: 当前 completion gate
            context: 额外上下文（用于 conditions 检查）
        
        Returns:
            True 如果规则匹配
        """
        if self.trigger_gate != completion_gate:
            return False
        
        # 检查额外 conditions
        if self.conditions and context:
            for key, expected_value in self.conditions.items():
                actual_value = context.get(key)
                if actual_value != expected_value:
                    return False
        
        return True


@dataclass
class TradingBatchSpec:
    """
    Trading Batch Spec — 定义一个 trading batch 的完整规格。
    
    核心字段：
    - batch_id: Batch ID（如 "T0", "T1", "T2"）
    - name: Batch 名称
    - description: Batch 描述
    - workstreams: 包含的 workstreams 列表（如 ["WS0", "WS7"]）
    - prerequisites: 前置 batch ID 列表
    - required_artifacts: 必需的 artifacts 列表
    - completion_gate_definition: completion gate 定义
    - next_batch_rules: 下一批规则列表
    - safety_gate: 安全门
    - metadata: 额外元数据
    """
    batch_id: str
    name: str
    description: str
    workstreams: List[str]
    prerequisites: List[str] = field(default_factory=list)
    required_artifacts: List[str] = field(default_factory=list)
    completion_gate_definition: Dict[str, Any] = field(default_factory=dict)
    next_batch_rules: List[NextBatchRule] = field(default_factory=list)
    safety_gate: SafetyGate = field(default_factory=SafetyGate)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "batch_spec_version": TRADING_BATCH_SPEC_VERSION,
            "batch_id": self.batch_id,
            "name": self.name,
            "description": self.description,
            "workstreams": self.workstreams,
            "prerequisites": self.prerequisites,
            "required_artifacts": self.required_artifacts,
            "completion_gate_definition": self.completion_gate_definition,
            "next_batch_rules": [r.to_dict() for r in self.next_batch_rules],
            "safety_gate": self.safety_gate.to_dict(),
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TradingBatchSpec":
        return cls(
            batch_id=data.get("batch_id", ""),
            name=data.get("name", ""),
            description=data.get("description", ""),
            workstreams=data.get("workstreams", []),
            prerequisites=data.get("prerequisites", []),
            required_artifacts=data.get("required_artifacts", []),
            completion_gate_definition=data.get("completion_gate_definition", {}),
            next_batch_rules=[NextBatchRule.from_dict(r) for r in data.get("next_batch_rules", [])],
            safety_gate=SafetyGate.from_dict(data.get("safety_gate", {})),
            metadata=data.get("metadata", {}),
        )
    
    def evaluate_next_batch(
        self,
        completion_gate: CompletionGate,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[NextBatchRule]:
        """
        评估下一批规则，返回匹配的 rule。
        
        Args:
            completion_gate: 当前 completion gate
            context: 额外上下文
        
        Returns:
            匹配的 NextBatchRule，无匹配则返回 None
        """
        # 按优先级排序
        sorted_rules = sorted(self.next_batch_rules, key=lambda r: r.priority, reverse=True)
        
        for rule in sorted_rules:
            if rule.matches(completion_gate, context):
                return rule
        
        return None
    
    def check_prerequisites_completed(
        self,
        completed_batches: List[str],
    ) -> tuple[bool, List[str]]:
        """
        检查前置 batch 是否已完成。
        
        Args:
            completed_batches: 已完成的 batch ID 列表
        
        Returns:
            (all_completed, missing_prerequisites)
        """
        missing = []
        for prereq in self.prerequisites:
            if prereq not in completed_batches:
                missing.append(prereq)
        
        return len(missing) == 0, missing
    
    def check_required_artifacts(
        self,
        available_artifacts: List[str],
    ) -> tuple[bool, List[str]]:
        """
        检查必需的 artifacts 是否存在。
        
        Args:
            available_artifacts: 可用的 artifacts 列表
        
        Returns:
            (all_present, missing_artifacts)
        """
        missing = []
        for artifact in self.required_artifacts:
            if artifact not in available_artifacts:
                missing.append(artifact)
        
        return len(missing) == 0, missing


@dataclass
class TradingBatchSpecCollection:
    """
    Trading Batch Spec Collection — 管理多个 batch specs 的集合。
    
    提供 batch 队列的整体视图和续批路径计算。
    """
    batches: Dict[str, TradingBatchSpec]
    version: str = TRADING_BATCH_SPEC_VERSION
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "batch_spec_version": self.version,
            "batches": {bid: b.to_dict() for bid, b in self.batches.items()},
            "created_at": self.created_at,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TradingBatchSpecCollection":
        return cls(
            batches={
                bid: TradingBatchSpec.from_dict(b)
                for bid, b in data.get("batches", {}).items()
            },
            version=data.get("batch_spec_version", TRADING_BATCH_SPEC_VERSION),
            created_at=data.get("created_at", datetime.now().isoformat()),
            metadata=data.get("metadata", {}),
        )
    
    def get_batch(self, batch_id: str) -> Optional[TradingBatchSpec]:
        """获取指定 batch spec"""
        return self.batches.get(batch_id)
    
    def get_batch_order(self) -> List[str]:
        """
        获取 batch 执行顺序（拓扑排序）。
        
        Returns:
            batch ID 列表，按依赖顺序排列
        """
        # 简单拓扑排序
        visited = set()
        order = []
        
        def visit(batch_id: str):
            if batch_id in visited:
                return
            visited.add(batch_id)
            
            batch = self.batches.get(batch_id)
            if batch:
                for prereq in batch.prerequisites:
                    visit(prereq)
                order.append(batch_id)
        
        for batch_id in self.batches:
            visit(batch_id)
        
        return order
    
    def compute_continuation_path(
        self,
        current_batch_id: str,
        completion_gate: CompletionGate,
        completed_batches: List[str],
        available_artifacts: List[str],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        计算续批路径。
        
        Args:
            current_batch_id: 当前 batch ID
            completion_gate: 当前 completion gate
            completed_batches: 已完成的 batch ID 列表
            available_artifacts: 可用的 artifacts 列表
            context: 额外上下文
        
        Returns:
            {
                "current_batch": str,
                "completion_gate": str,
                "next_batch": Optional[str],
                "next_batch_description": str,
                "can_auto_continue": bool,
                "blocker": Optional[str],
                "safety_gate_status": str,
                "recommended_action": str,
            }
        """
        current_batch = self.get_batch(current_batch_id)
        
        if not current_batch:
            return {
                "current_batch": current_batch_id,
                "completion_gate": completion_gate.value,
                "next_batch": None,
                "next_batch_description": "",
                "can_auto_continue": False,
                "blocker": f"Batch {current_batch_id} not found in spec",
                "safety_gate_status": "unknown",
                "recommended_action": "fix_batch_spec",
            }
        
        # 检查 prerequisites
        prereqs_ok, missing_prereqs = current_batch.check_prerequisites_completed(completed_batches)
        if not prereqs_ok:
            return {
                "current_batch": current_batch_id,
                "completion_gate": completion_gate.value,
                "next_batch": None,
                "next_batch_description": "",
                "can_auto_continue": False,
                "blocker": f"Missing prerequisites: {', '.join(missing_prereqs)}",
                "safety_gate_status": "blocked",
                "recommended_action": "complete_prerequisites",
            }
        
        # 检查 safety gate
        safety_ok, safety_reason = current_batch.safety_gate.is_safe_to_continue(completion_gate)
        
        # 评估 next batch rule
        next_rule = current_batch.evaluate_next_batch(completion_gate, context)
        
        if not next_rule:
            return {
                "current_batch": current_batch_id,
                "completion_gate": completion_gate.value,
                "next_batch": None,
                "next_batch_description": "",
                "can_auto_continue": False,
                "blocker": f"No matching next_batch_rule for gate={completion_gate.value}",
                "safety_gate_status": "gate_held",
                "recommended_action": "manual_review",
            }
        
        # 检查下一批的 prerequisites
        next_batch = self.get_batch(next_rule.next_batch_id)
        if next_batch:
            next_prereqs_ok, next_missing_prereqs = next_batch.check_prerequisites_completed(
                completed_batches + [current_batch_id]
            )
            if not next_prereqs_ok:
                safety_ok = False
                safety_reason = f"Next batch missing prerequisites: {', '.join(next_missing_prereqs)}"
        
        can_auto_continue = safety_ok and next_rule is not None
        
        return {
            "current_batch": current_batch_id,
            "completion_gate": completion_gate.value,
            "next_batch": next_rule.next_batch_id if next_rule else None,
            "next_batch_description": next_rule.next_batch_description if next_rule else "",
            "can_auto_continue": can_auto_continue,
            "blocker": None if can_auto_continue else safety_reason,
            "safety_gate_status": "pass" if safety_ok else "blocked",
            "recommended_action": "auto_dispatch" if can_auto_continue else "manual_review",
            "dispatch_profile": next_rule.dispatch_profile if next_rule else None,
            "executor": next_rule.executor if next_rule else None,
        }


class TradingBatchSpecLoader:
    """
    Trading Batch Spec Loader — 从 YAML/JSON 文件加载 batch spec。
    
    提供：
    - load_yaml(): 从 YAML 文件加载
    - load_json(): 从 JSON 文件加载
    - load_dict(): 从 dict 加载
    - validate(): 验证 batch spec
    """
    
    def __init__(self):
        pass
    
    def load_yaml(self, path: Path) -> TradingBatchSpecCollection:
        """从 YAML 文件加载"""
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return TradingBatchSpecCollection.from_dict(data)
    
    def load_json(self, path: Path) -> TradingBatchSpecCollection:
        """从 JSON 文件加载"""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return TradingBatchSpecCollection.from_dict(data)
    
    def load_dict(self, data: Dict[str, Any]) -> TradingBatchSpecCollection:
        """从 dict 加载"""
        return TradingBatchSpecCollection.from_dict(data)
    
    def validate(self, collection: TradingBatchSpecCollection) -> tuple[bool, List[str]]:
        """
        验证 batch spec 集合。
        
        Returns:
            (is_valid, errors)
        """
        errors: List[str] = []
        
        # 检查 batch ID 唯一性
        batch_ids = list(collection.batches.keys())
        if len(batch_ids) != len(set(batch_ids)):
            errors.append("Duplicate batch IDs detected")
        
        # 检查每个 batch
        for batch_id, batch in collection.batches.items():
            # 检查 batch_id 一致性
            if batch.batch_id != batch_id:
                errors.append(f"Batch {batch_id}: batch_id mismatch (spec={batch.batch_id})")
            
            # 检查 prerequisites 引用
            for prereq in batch.prerequisites:
                if prereq not in collection.batches:
                    errors.append(f"Batch {batch_id}: unknown prerequisite '{prereq}'")
            
            # 检查 next_batch_rules 引用
            for rule in batch.next_batch_rules:
                # next_batch_id 可以为 None（表示队列完成）
                if rule.next_batch_id is not None and rule.next_batch_id not in collection.batches:
                    errors.append(f"Batch {batch_id}: next_batch_rule references unknown batch '{rule.next_batch_id}'")
            
            # 检查 completion_gate_definition
            if not batch.completion_gate_definition:
                errors.append(f"Batch {batch_id}: missing completion_gate_definition")
        
        # 检查循环依赖
        def has_cycle(batch_id: str, visited: set, rec_stack: set) -> bool:
            visited.add(batch_id)
            rec_stack.add(batch_id)
            
            batch = collection.batches.get(batch_id)
            if batch:
                for prereq in batch.prerequisites:
                    if prereq not in visited:
                        if has_cycle(prereq, visited, rec_stack):
                            return True
                    elif prereq in rec_stack:
                        return True
            
            rec_stack.remove(batch_id)
            return False
        
        visited: set = set()
        for batch_id in collection.batches:
            if batch_id not in visited:
                if has_cycle(batch_id, visited, set()):
                    errors.append("Circular dependency detected in batch prerequisites")
                    break
        
        return len(errors) == 0, errors


def load_batch_spec(path: Path) -> TradingBatchSpecCollection:
    """
    Convenience function: 从文件加载 batch spec。
    
    Args:
        path: YAML 或 JSON 文件路径
    
    Returns:
        TradingBatchSpecCollection
    """
    loader = TradingBatchSpecLoader()
    
    if path.suffix in (".yaml", ".yml"):
        return loader.load_yaml(path)
    elif path.suffix == ".json":
        return loader.load_json(path)
    else:
        raise ValueError(f"Unsupported file format: {path.suffix}")


def validate_batch_spec(collection: TradingBatchSpecCollection) -> tuple[bool, List[str]]:
    """
    Convenience function: 验证 batch spec。
    
    Args:
        collection: TradingBatchSpecCollection
    
    Returns:
        (is_valid, errors)
    """
    loader = TradingBatchSpecLoader()
    return loader.validate(collection)


# CLI 入口
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python trading_batch_spec.py load <path>")
        print("  python trading_batch_spec.py validate <path>")
        print("  python trading_batch_spec.py order <path>")
        print("  python trading_batch_spec.py continue <path> <batch_id> <gate>")
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == "load":
        if len(sys.argv) < 3:
            print("Error: missing path")
            sys.exit(1)
        
        path = Path(sys.argv[2])
        collection = load_batch_spec(path)
        print(json.dumps(collection.to_dict(), indent=2))
    
    elif cmd == "validate":
        if len(sys.argv) < 3:
            print("Error: missing path")
            sys.exit(1)
        
        path = Path(sys.argv[2])
        collection = load_batch_spec(path)
        is_valid, errors = validate_batch_spec(collection)
        
        if is_valid:
            print("✓ Batch spec is valid")
        else:
            print("✗ Batch spec validation failed:")
            for error in errors:
                print(f"  - {error}")
            sys.exit(1)
    
    elif cmd == "order":
        if len(sys.argv) < 3:
            print("Error: missing path")
            sys.exit(1)
        
        path = Path(sys.argv[2])
        collection = load_batch_spec(path)
        order = collection.get_batch_order()
        print("Batch execution order:")
        for i, batch_id in enumerate(order, 1):
            batch = collection.get_batch(batch_id)
            print(f"  {i}. {batch_id}: {batch.name if batch else 'unknown'}")
    
    elif cmd == "continue":
        if len(sys.argv) < 5:
            print("Error: missing arguments")
            print("Usage: python trading_batch_spec.py continue <path> <batch_id> <gate>")
            sys.exit(1)
        
        path = Path(sys.argv[2])
        batch_id = sys.argv[3]
        gate_value = sys.argv[4].upper()
        
        collection = load_batch_spec(path)
        
        try:
            completion_gate = CompletionGate(gate_value)
        except ValueError:
            print(f"Error: invalid gate '{gate_value}'. Valid values: {[g.value for g in CompletionGate]}")
            sys.exit(1)
        
        result = collection.compute_continuation_path(
            current_batch_id=batch_id,
            completion_gate=completion_gate,
            completed_batches=[],
            available_artifacts=[],
        )
        
        print(json.dumps(result, indent=2))
    
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
