#!/usr/bin/env python3
"""
planning_execution_closeout_integration.py — Unified Planning → Execution → Closeout Integration

目标：把 planning artifact 进入 execution result / closeout context 的统一映射整合成一个中等粒度整合点。

这是 Batch D 中等批次 truth-domain 整合，而不是大抽象探索。

核心能力：
1. Planning artifact → Execution result 的统一映射
2. Execution result → Closeout glue 输入的 richer mapping
3. Closeout context 汇总时带出 planning / lineage / dispatch readiness 的统一结构

核心类：
- PlanningExecutionCloseoutContext: 统一上下文，包含完整的 planning/execution/closeout 链路
- IntegrationKernel: 整合内核，负责从各个 artifact 构建统一上下文
- build_integration_context: 便捷函数，从 issue_id 或 execution_id 构建整合上下文

使用示例：
```python
from planning_execution_closeout_integration import build_integration_context

# 从 execution_id 构建整合上下文
context = build_integration_context(execution_id="exec_001")

# 访问统一结构
print(f"Planning: {context.planning_summary}")
print(f"Execution: {context.execution_status}")
print(f"Closeout: {context.closeout_readiness}")
print(f"Lineage: {context.lineage_info}")
```
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

# Import from existing modules
from issue_lane_schemas import (
    IssueInput,
    PlanningOutput,
    ExecutionOutput,
    CloseoutOutput,
    IssueLaneContract,
)
from closeout_glue import (
    CloseoutGlueInput,
    ExecutionToCloseoutGlue,
    map_receipt_to_closeout,
)
from completion_receipt import (
    CompletionReceiptArtifact,
    get_completion_receipt,
    list_completion_receipts,
)
from lineage import (
    LineageRecord,
    get_lineage_by_parent,
    get_lineage_by_child,
    check_fanin_readiness,
    build_fanin_closeout_context,
)

__all__ = [
    "INTEGRATION_VERSION",
    "IntegrationStatus",
    "PlanningExecutionCloseoutContext",
    "IntegrationKernel",
    "build_integration_context",
    "build_integration_from_issue",
    "build_integration_from_execution",
    "summarize_integration_context",
]

INTEGRATION_VERSION = "planning_execution_closeout_integration_v1"

IntegrationStatus = Literal[
    "complete",           # planning + execution + closeout 完整
    "partial_planning",   # 只有 planning
    "partial_execution",  # planning + execution，缺 closeout
    "partial_closeout",   # planning + execution + closeout 不完整
    "missing_planning",   # 只有 execution + closeout，缺 planning
    "incomplete",         # 其他不完整状态
]


@dataclass
class PlanningExecutionCloseoutContext:
    """
    Unified Planning → Execution → Closeout Context
    
    这是中等粒度整合点，把原本分散的 planning/execution/closeout/lineage 统一到一个结构。
    
    核心字段：
    - context_id: 上下文 ID
    - issue_id: Issue ID
    - execution_id: Execution ID
    - status: 整合状态
    - planning: Planning artifact（可选）
    - planning_summary: Planning 摘要（从 planning 提取）
    - execution: Execution artifact（可选）
    - execution_status: Execution 状态
    - execution_result_summary: Execution 结果摘要
    - completion_receipt: Completion receipt artifact（可选）
    - receipt_status: Receipt 状态
    - closeout_glue_input: Closeout glue input（从 receipt 映射）
    - closeout: Closeout output（可选）
    - closeout_readiness: Closeout readiness（从 closeout glue 提取）
    - lineage_info: Lineage 信息（父子关系）
    - fanin_readiness: Fan-in readiness 状态（如果有 batch）
    - dispatch_readiness: Dispatch readiness（从 closeout glue 提取）
    - continuation_contract: Continuation contract（从 receipt metadata 提取）
    - metadata: 额外元数据
    """
    context_id: str
    issue_id: str
    execution_id: str
    status: IntegrationStatus
    
    # Planning
    planning: Optional[PlanningOutput] = None
    planning_summary: str = ""
    
    # Execution
    execution: Optional[ExecutionOutput] = None
    execution_status: str = ""
    execution_result_summary: str = ""
    
    # Completion Receipt
    completion_receipt: Optional[CompletionReceiptArtifact] = None
    receipt_status: str = ""
    
    # Closeout Glue
    closeout_glue_input: Optional[CloseoutGlueInput] = None
    closeout: Optional[CloseoutOutput] = None
    closeout_readiness: str = ""
    
    # Lineage & Fan-in
    lineage_info: Optional[Dict[str, Any]] = None
    fanin_readiness: Optional[Dict[str, Any]] = None
    
    # Dispatch & Continuation
    dispatch_readiness: str = ""
    continuation_contract: Optional[Dict[str, Any]] = None
    
    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "integration_version": INTEGRATION_VERSION,
            "context_id": self.context_id,
            "issue_id": self.issue_id,
            "execution_id": self.execution_id,
            "status": self.status,
            "planning": self.planning.to_dict() if self.planning else None,
            "planning_summary": self.planning_summary,
            "execution": self.execution.to_dict() if self.execution else None,
            "execution_status": self.execution_status,
            "execution_result_summary": self.execution_result_summary,
            "completion_receipt": self.completion_receipt.to_dict() if self.completion_receipt else None,
            "receipt_status": self.receipt_status,
            "closeout_glue_input": self.closeout_glue_input.to_dict() if self.closeout_glue_input else None,
            "closeout": self.closeout.to_dict() if self.closeout else None,
            "closeout_readiness": self.closeout_readiness,
            "lineage_info": self.lineage_info,
            "fanin_readiness": self.fanin_readiness,
            "dispatch_readiness": self.dispatch_readiness,
            "continuation_contract": self.continuation_contract,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PlanningExecutionCloseoutContext":
        """从字典反序列化"""
        planning_data = data.get("planning")
        planning = PlanningOutput(**planning_data) if planning_data else None
        
        execution_data = data.get("execution")
        execution = ExecutionOutput(**execution_data) if execution_data else None
        
        receipt_data = data.get("completion_receipt")
        completion_receipt = None
        if receipt_data:
            completion_receipt = CompletionReceiptArtifact.from_dict(receipt_data)
        
        glue_data = data.get("closeout_glue_input")
        closeout_glue_input = None
        if glue_data:
            closeout_glue_input = CloseoutGlueInput.from_dict(glue_data)
        
        closeout_data = data.get("closeout")
        closeout = None
        if closeout_data:
            closeout = CloseoutOutput.from_dict(closeout_data)
        
        return cls(
            context_id=data.get("context_id", ""),
            issue_id=data.get("issue_id", ""),
            execution_id=data.get("execution_id", ""),
            status=data.get("status", "incomplete"),
            planning=planning,
            planning_summary=data.get("planning_summary", ""),
            execution=execution,
            execution_status=data.get("execution_status", ""),
            execution_result_summary=data.get("execution_result_summary", ""),
            completion_receipt=completion_receipt,
            receipt_status=data.get("receipt_status", ""),
            closeout_glue_input=closeout_glue_input,
            closeout=closeout,
            closeout_readiness=data.get("closeout_readiness", ""),
            lineage_info=data.get("lineage_info"),
            fanin_readiness=data.get("fanin_readiness"),
            dispatch_readiness=data.get("dispatch_readiness", ""),
            continuation_contract=data.get("continuation_contract"),
            metadata=data.get("metadata", {}),
        )


class IntegrationKernel:
    """
    Integration Kernel — 从各个 artifact 构建统一的 planning/execution/closeout 上下文。
    
    核心方法：
    - build_context_from_execution(): 从 execution_id 构建整合上下文
    - build_context_from_issue(): 从 issue_id 构建整合上下文
    - _extract_planning_summary(): 从 planning 提取摘要
    - _extract_execution_summary(): 从 execution 提取摘要
    - _build_lineage_info(): 构建 lineage 信息
    - _determine_integration_status(): 决定整合状态
    """
    
    def __init__(self):
        self.closeout_glue = ExecutionToCloseoutGlue()
    
    def _extract_planning_summary(self, planning: PlanningOutput) -> str:
        """从 planning 提取摘要"""
        parts = []
        if planning.problem_reframing:
            parts.append(f"Problem: {planning.problem_reframing[:100]}")
        if planning.execution_plan:
            parts.append(f"Plan: {planning.execution_plan[:100]}")
        if planning.acceptance_criteria:
            parts.append(f"Criteria: {len(planning.acceptance_criteria)} items")
        return " | ".join(parts) if parts else "No planning summary"
    
    def _extract_execution_summary(self, execution: ExecutionOutput) -> str:
        """从 execution 提取摘要"""
        parts = []
        if execution.status:
            parts.append(f"Status: {execution.status}")
        if execution.execution_summary:
            parts.append(f"Summary: {execution.execution_summary[:100]}")
        if execution.patch:
            parts.append(f"Patch: {len(execution.patch.files_changed)} files")
        if execution.test_results:
            parts.append(f"Tests: {execution.test_results.get('passed', 0)}/{execution.test_results.get('total', 0)}")
        return " | ".join(parts) if parts else "No execution summary"
    
    def _build_lineage_info(self, execution_id: str) -> Dict[str, Any]:
        """
        从 execution_id 构建 lineage 信息。
        
        查询：
        - 作为 parent 的 lineage records（children）
        - 作为 child 的 lineage records（parent）
        """
        lineage_info = {
            "execution_id": execution_id,
            "parents": [],
            "children": [],
            "batch_id": None,
        }
        
        # 查询作为 parent 的 lineage
        try:
            children = get_lineage_by_parent(parent_id=execution_id)
            lineage_info["children"] = [
                {
                    "lineage_id": lr.lineage_id,
                    "child_id": lr.child_id,
                    "relation_type": lr.relation_type,
                    "batch_id": lr.batch_id,
                }
                for lr in children
            ]
            if children:
                lineage_info["batch_id"] = children[0].batch_id
        except (FileNotFoundError, json.JSONDecodeError, KeyError, OSError):
            pass
        
        # 查询作为 child 的 lineage
        try:
            parents = get_lineage_by_child(child_id=execution_id)
            lineage_info["parents"] = [
                {
                    "lineage_id": lr.lineage_id,
                    "parent_id": lr.parent_id,
                    "relation_type": lr.relation_type,
                    "batch_id": lr.batch_id,
                }
                for lr in parents
            ]
            if parents and not lineage_info["batch_id"]:
                lineage_info["batch_id"] = parents[0].batch_id
        except (FileNotFoundError, json.JSONDecodeError, KeyError, OSError):
            pass
        
        return lineage_info
    
    def _determine_integration_status(
        self,
        planning: Optional[PlanningOutput],
        execution: Optional[ExecutionOutput],
        completion_receipt: Optional[CompletionReceiptArtifact],
        closeout_glue_input: Optional[CloseoutGlueInput],
    ) -> IntegrationStatus:
        """
        决定整合状态。
        
        规则：
        - planning + execution + receipt + closeout_glue → complete
        - execution + receipt + closeout_glue (no planning) → missing_planning
        - planning + execution (no receipt) → partial_execution
        - planning only → partial_planning
        - 其他 → incomplete
        """
        if planning and execution and completion_receipt and closeout_glue_input:
            return "complete"
        elif execution and completion_receipt and closeout_glue_input and not planning:
            return "missing_planning"
        elif planning and execution and not completion_receipt:
            return "partial_execution"
        elif planning and not execution:
            return "partial_planning"
        else:
            return "incomplete"
    
    def build_context_from_execution(
        self,
        execution_id: str,
        include_lineage: bool = True,
        include_fanin: bool = True,
    ) -> PlanningExecutionCloseoutContext:
        """
        从 execution_id 构建整合上下文。
        
        Args:
            execution_id: Execution ID
            include_lineage: 是否包含 lineage 信息
            include_fanin: 是否包含 fan-in readiness
        
        Returns:
            PlanningExecutionCloseoutContext
        """
        import uuid
        
        # 1. 获取 completion receipt
        completion_receipt = get_completion_receipt_by_execution_id(execution_id)
        
        # 2. 从 receipt 中提取 execution 信息（当前阶段简化处理）
        # 注意：实际实现需要从 execution store 获取完整 execution artifact
        # 这里我们简化，假设 execution 信息可以从 receipt metadata 推断
        execution: Optional[ExecutionOutput] = None
        execution_status = ""
        execution_result_summary = ""
        
        if completion_receipt:
            # 从 receipt metadata 提取 execution 信息
            metadata = completion_receipt.metadata or {}
            execution_status = metadata.get("source_execution_status", "unknown")
            execution_result_summary = completion_receipt.result_summary
            
            # 尝试从 business_result 提取更多信息
            business_result = completion_receipt.business_result
            if business_result:
                execution_result_summary = business_result.get("summary", execution_result_summary)
        
        # 3. 从 receipt 映射到 closeout glue input
        closeout_glue_input: Optional[CloseoutGlueInput] = None
        closeout_readiness = ""
        dispatch_readiness = ""
        
        if completion_receipt:
            closeout_glue_input = self.closeout_glue.map_receipt_to_closeout_input(completion_receipt)
            closeout_readiness = closeout_glue_input.dispatch_readiness
            dispatch_readiness = closeout_glue_input.dispatch_readiness
        
        # 4. 提取 planning（如果有）
        # 注意：当前阶段 planning 存储在其他地方，需要额外查询
        # 这里简化处理，假设 planning 信息可以从 receipt metadata 获取
        planning: Optional[PlanningOutput] = None
        planning_summary = ""
        
        if completion_receipt:
            metadata = completion_receipt.metadata or {}
            planning_data = metadata.get("planning")
            if planning_data and isinstance(planning_data, dict):
                planning = PlanningOutput(**planning_data)
                planning_summary = self._extract_planning_summary(planning)
        
        # 5. 构建 lineage 信息
        lineage_info: Optional[Dict[str, Any]] = None
        fanin_readiness: Optional[Dict[str, Any]] = None
        
        if include_lineage and completion_receipt:
            lineage_info = self._build_lineage_info(execution_id)
        
        if include_fanin and lineage_info and lineage_info.get("batch_id"):
            try:
                fanin_readiness = check_fanin_readiness(batch_id=lineage_info["batch_id"])
            except (FileNotFoundError, json.JSONDecodeError, KeyError, OSError):
                fanin_readiness = {"status": "error", "message": "Failed to check fan-in readiness"}
        
        # 6. 提取 continuation contract
        continuation_contract: Optional[Dict[str, Any]] = None
        if completion_receipt:
            metadata = completion_receipt.metadata or {}
            continuation_contract = metadata.get("continuation_contract")
        
        # 7. 决定整合状态
        status = self._determine_integration_status(
            planning=planning,
            execution=execution,
            completion_receipt=completion_receipt,
            closeout_glue_input=closeout_glue_input,
        )
        
        # 8. 构建上下文
        issue_id = completion_receipt.source_task_id if completion_receipt else ""
        
        return PlanningExecutionCloseoutContext(
            context_id=f"integration_{uuid.uuid4().hex[:12]}",
            issue_id=issue_id,
            execution_id=execution_id,
            status=status,
            planning=planning,
            planning_summary=planning_summary,
            execution=execution,
            execution_status=execution_status,
            execution_result_summary=execution_result_summary,
            completion_receipt=completion_receipt,
            receipt_status=completion_receipt.receipt_status if completion_receipt else "",
            closeout_glue_input=closeout_glue_input,
            closeout_readiness=closeout_readiness,
            lineage_info=lineage_info,
            fanin_readiness=fanin_readiness,
            dispatch_readiness=dispatch_readiness,
            continuation_contract=continuation_contract,
            metadata={
                "built_at": _iso_now(),
                "include_lineage": include_lineage,
                "include_fanin": include_fanin,
            },
        )
    
    def build_context_from_issue(
        self,
        issue_id: str,
        include_lineage: bool = True,
        include_fanin: bool = True,
    ) -> Optional[PlanningExecutionCloseoutContext]:
        """
        从 issue_id 构建整合上下文。
        
        Args:
            issue_id: Issue ID
            include_lineage: 是否包含 lineage 信息
            include_fanin: 是否包含 fan-in readiness
        
        Returns:
            PlanningExecutionCloseoutContext，不存在则返回 None
        """
        # 1. 查找与 issue_id 相关的 completion receipts
        receipts = list_completion_receipts(task_id=issue_id, limit=1)
        
        if not receipts:
            return None
        
        receipt = receipts[0]
        
        # 2. 从 receipt 获取 execution_id
        execution_id = receipt.source_spawn_execution_id
        
        # 3. 委托给 build_context_from_execution
        return self.build_context_from_execution(
            execution_id=execution_id,
            include_lineage=include_lineage,
            include_fanin=include_fanin,
        )


def _iso_now() -> str:
    """返回当前 ISO-8601 时间戳"""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def get_completion_receipt_by_execution_id(execution_id: str) -> Optional[CompletionReceiptArtifact]:
    """
    按 execution_id 获取 completion receipt。
    
    这是便捷函数，用于从 execution_id 反向查询 receipt。
    """
    receipts = list_completion_receipts(execution_id=execution_id, limit=1)
    return receipts[0] if receipts else None


def build_integration_context(
    execution_id: Optional[str] = None,
    issue_id: Optional[str] = None,
    include_lineage: bool = True,
    include_fanin: bool = True,
) -> Optional[PlanningExecutionCloseoutContext]:
    """
    便捷函数：构建整合上下文。
    
    Args:
        execution_id: Execution ID（优先）
        issue_id: Issue ID（fallback）
        include_lineage: 是否包含 lineage 信息
        include_fanin: 是否包含 fan-in readiness
    
    Returns:
        PlanningExecutionCloseoutContext，不存在则返回 None
    """
    kernel = IntegrationKernel()
    
    if execution_id:
        return kernel.build_context_from_execution(
            execution_id=execution_id,
            include_lineage=include_lineage,
            include_fanin=include_fanin,
        )
    elif issue_id:
        return kernel.build_context_from_issue(
            issue_id=issue_id,
            include_lineage=include_lineage,
            include_fanin=include_fanin,
        )
    
    return None


def build_integration_from_execution(
    execution_id: str,
    include_lineage: bool = True,
    include_fanin: bool = True,
) -> PlanningExecutionCloseoutContext:
    """
    便捷函数：从 execution_id 构建整合上下文。
    """
    kernel = IntegrationKernel()
    return kernel.build_context_from_execution(
        execution_id=execution_id,
        include_lineage=include_lineage,
        include_fanin=include_fanin,
    )


def build_integration_from_issue(
    issue_id: str,
    include_lineage: bool = True,
    include_fanin: bool = True,
) -> Optional[PlanningExecutionCloseoutContext]:
    """
    便捷函数：从 issue_id 构建整合上下文。
    """
    kernel = IntegrationKernel()
    return kernel.build_context_from_issue(
        issue_id=issue_id,
        include_lineage=include_lineage,
        include_fanin=include_fanin,
    )


def summarize_integration_context(context: PlanningExecutionCloseoutContext) -> str:
    """
    生成整合上下文的摘要（人类可读）。
    
    Args:
        context: PlanningExecutionCloseoutContext
    
    Returns:
        人类可读的摘要字符串
    """
    lines = [
        f"Integration Context: {context.context_id}",
        f"Issue: {context.issue_id}",
        f"Execution: {context.execution_id}",
        f"Status: {context.status}",
        "",
    ]
    
    # Planning
    if context.planning:
        lines.append(f"Planning: ✅ {context.planning_summary[:100]}")
    else:
        lines.append("Planning: ❌ Missing")
    
    # Execution
    if context.execution:
        lines.append(f"Execution: ✅ {context.execution_status} - {context.execution_result_summary[:100]}")
    else:
        lines.append(f"Execution: ℹ️  {context.execution_status} - {context.execution_result_summary[:100]}")
    
    # Completion Receipt
    if context.completion_receipt:
        lines.append(f"Receipt: ✅ {context.receipt_status}")
    else:
        lines.append("Receipt: ❌ Missing")
    
    # Closeout Glue
    if context.closeout_glue_input:
        lines.append(f"Closeout Glue: ✅ dispatch_readiness={context.dispatch_readiness}")
    else:
        lines.append("Closeout Glue: ❌ Missing")
    
    # Lineage
    if context.lineage_info:
        children_count = len(context.lineage_info.get("children", []))
        parents_count = len(context.lineage_info.get("parents", []))
        lines.append(f"Lineage: ✅ {parents_count} parent(s), {children_count} child(ren)")
    else:
        lines.append("Lineage: ❌ Missing")
    
    # Fan-in
    if context.fanin_readiness:
        fanin_status = context.fanin_readiness.get("status", "unknown")
        lines.append(f"Fan-in Readiness: ✅ {fanin_status}")
    else:
        lines.append("Fan-in Readiness: ❌ Not applicable")
    
    # Continuation Contract
    if context.continuation_contract:
        next_step = context.continuation_contract.get("next_step", "N/A")[:50]
        next_owner = context.continuation_contract.get("next_owner", "N/A")
        lines.append(f"Continuation: ✅ next_step={next_step}..., next_owner={next_owner}")
    else:
        lines.append("Continuation: ❌ Missing")
    
    return "\n".join(lines)


# CLI 入口
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python planning_execution_closeout_integration.py build <execution_id>")
        print("  python planning_execution_closeout_integration.py build-issue <issue_id>")
        print("  python planning_execution_closeout_integration.py summarize <context_id>")
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == "build":
        if len(sys.argv) < 3:
            print("Error: missing execution_id")
            sys.exit(1)
        
        execution_id = sys.argv[2]
        context = build_integration_context(execution_id=execution_id)
        
        if context:
            print(json.dumps(context.to_dict(), indent=2))
            print("\n" + "=" * 60)
            print(summarize_integration_context(context))
        else:
            print(f"Integration context not found for execution_id: {execution_id}")
            sys.exit(1)
    
    elif cmd == "build-issue":
        if len(sys.argv) < 3:
            print("Error: missing issue_id")
            sys.exit(1)
        
        issue_id = sys.argv[2]
        context = build_integration_context(issue_id=issue_id)
        
        if context:
            print(json.dumps(context.to_dict(), indent=2))
            print("\n" + "=" * 60)
            print(summarize_integration_context(context))
        else:
            print(f"Integration context not found for issue_id: {issue_id}")
            sys.exit(1)
    
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
