#!/usr/bin/env python3
"""
closeout_glue.py — Closeout Glue Core (Minimal Implementation)

目标：把 execution 结果中的核心字段统一映射到 closeout 可消费的结构。

这是极小切片实现 (micro-slice-03)，只做最小字段映射，不做"大一统 glue"。

核心映射字段：
- execution_id → source_execution_id (linkage)
- receipt_status → dispatch_readiness (决策依据)
- result_summary → summary (人类可读摘要)
- lineage_id → lineage_id (父子关系追踪)
- next_step/next_owner (从 continuation contract 继承)

当前阶段：最小字段映射 + 接线到 completion_receipt.py

使用示例：
```python
from closeout_glue import ExecutionToCloseoutGlue
from completion_receipt import CompletionReceiptArtifact

glue = ExecutionToCloseoutGlue()
closeout_input = glue.map_receipt_to_closeout_input(receipt_artifact)
```
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Literal, Optional

from completion_receipt import CompletionReceiptArtifact, ReceiptStatus

__all__ = [
    "CLOSEOUT_GLUE_VERSION",
    "DispatchReadiness",
    "CloseoutGlueInput",
    "ExecutionToCloseoutGlue",
]

CLOSEOUT_GLUE_VERSION = "closeout_glue_v1"

DispatchReadiness = Literal["ready", "blocked", "pending_review", "missing"]


@dataclass
class CloseoutGlueInput:
    """
    Closeout glue input — 从 execution/receipt 映射到 closeout 可消费的结构。
    
    核心字段：
    - source_execution_id: 来源 execution ID (linkage)
    - source_receipt_id: 来源 receipt ID (linkage)
    - source_receipt_status: 来源 receipt status (决策依据)
    - dispatch_readiness: 是否准备好 dispatch 下一跳
    - summary: 人类可读的结果摘要
    - lineage_id: lineage 追踪 ID (父子关系)
    - next_step: 下一步行动 (从 continuation contract 继承)
    - next_owner: 下一跳负责人 (从 continuation contract 继承)
    - stopped_because: 停止原因 (从 continuation contract 继承)
    - metadata: 额外元数据
    """
    source_execution_id: str
    source_receipt_id: str
    source_receipt_status: ReceiptStatus
    dispatch_readiness: DispatchReadiness
    summary: str
    lineage_id: Optional[str] = None
    next_step: str = ""
    next_owner: str = ""
    stopped_because: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "glue_version": CLOSEOUT_GLUE_VERSION,
            "source_execution_id": self.source_execution_id,
            "source_receipt_id": self.source_receipt_id,
            "source_receipt_status": self.source_receipt_status,
            "dispatch_readiness": self.dispatch_readiness,
            "summary": self.summary,
            "lineage_id": self.lineage_id,
            "next_step": self.next_step,
            "next_owner": self.next_owner,
            "stopped_because": self.stopped_because,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CloseoutGlueInput":
        return cls(
            source_execution_id=data.get("source_execution_id", ""),
            source_receipt_id=data.get("source_receipt_id", ""),
            source_receipt_status=data.get("source_receipt_status", "missing"),
            dispatch_readiness=data.get("dispatch_readiness", "pending_review"),
            summary=data.get("summary", ""),
            lineage_id=data.get("lineage_id"),
            next_step=data.get("next_step", ""),
            next_owner=data.get("next_owner", ""),
            stopped_because=data.get("stopped_because", ""),
            metadata=data.get("metadata", {}),
        )


class ExecutionToCloseoutGlue:
    """
    Execution to Closeout Glue — 把 execution/receipt 映射到 closeout 输入。
    
    核心方法：
    - map_receipt_to_closeout_input(): 从 completion receipt 映射到 closeout 输入
    - _determine_dispatch_readiness(): 根据 receipt status 决定 dispatch readiness
    - _extract_summary(): 从 receipt 提取结果摘要
    - _extract_continuation_fields(): 从 receipt metadata 提取 continuation 字段
    """
    
    def __init__(self):
        pass
    
    def _determine_dispatch_readiness(
        self,
        receipt_status: ReceiptStatus,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> DispatchReadiness:
        """
        根据 receipt status 决定 dispatch readiness。
        
        规则：
        - completed → ready (可以 dispatch 下一跳)
        - failed → blocked (需要先处理失败)
        - missing → pending_review (需要人工审查)
        
        Returns:
            DispatchReadiness
        """
        metadata = metadata or {}
        
        # 检查 metadata 中是否有显式标记
        if metadata.get("dispatch_readiness"):
            readiness = metadata.get("dispatch_readiness")
            if readiness in ("ready", "blocked", "pending_review", "missing"):
                return readiness  # type: ignore
        
        # 默认规则：基于 receipt status
        if receipt_status == "completed":
            return "ready"
        elif receipt_status == "failed":
            return "blocked"
        else:  # missing
            return "pending_review"
    
    def _extract_summary(
        self,
        receipt: CompletionReceiptArtifact,
    ) -> str:
        """
        从 receipt 提取结果摘要。
        
        优先级：
        1. receipt.result_summary (如果有)
        2. receipt.receipt_reason (fallback)
        3. 默认摘要
        
        Returns:
            人类可读的结果摘要
        """
        if receipt.result_summary:
            return receipt.result_summary
        elif receipt.receipt_reason:
            return f"Receipt {receipt.receipt_status}: {receipt.receipt_reason[:100]}"
        else:
            return f"Execution {receipt.receipt_status} for task {receipt.source_task_id}"
    
    def _extract_continuation_fields(
        self,
        receipt: CompletionReceiptArtifact,
    ) -> Dict[str, str]:
        """
        从 receipt metadata 提取 continuation 字段。
        
        从 receipt.metadata.continuation_contract 中提取：
        - next_step
        - next_owner
        - stopped_because
        
        Returns:
            {next_step, next_owner, stopped_because}
        """
        metadata = receipt.metadata or {}
        continuation = metadata.get("continuation_contract", {})
        
        return {
            "next_step": continuation.get("next_step", ""),
            "next_owner": continuation.get("next_owner", ""),
            "stopped_because": continuation.get("stopped_because", ""),
        }
    
    def map_receipt_to_closeout_input(
        self,
        receipt: CompletionReceiptArtifact,
    ) -> CloseoutGlueInput:
        """
        从 completion receipt 映射到 closeout 输入。
        
        这是核心映射函数，把 receipt 的核心字段统一映射到 closeout 可消费的结构。
        
        Args:
            receipt: Completion receipt artifact
        
        Returns:
            CloseoutGlueInput: 映射后的 closeout 输入
        
        映射规则：
        - source_execution_id ← receipt.source_spawn_execution_id
        - source_receipt_id ← receipt.receipt_id
        - source_receipt_status ← receipt.receipt_status
        - dispatch_readiness ← 根据 receipt_status 决定
        - summary ← receipt.result_summary 或 receipt.receipt_reason
        - lineage_id ← receipt.metadata.lineage_id (如果有)
        - next_step/next_owner/stopped_because ← receipt.metadata.continuation_contract
        """
        # 提取 continuation 字段
        continuation_fields = self._extract_continuation_fields(receipt)
        
        # 决定 dispatch readiness
        dispatch_readiness = self._determine_dispatch_readiness(
            receipt_status=receipt.receipt_status,
            metadata=receipt.metadata,
        )
        
        # 提取 summary
        summary = self._extract_summary(receipt)
        
        # 提取 lineage_id (如果有)
        lineage_id = receipt.metadata.get("lineage_id")
        
        # 构建 closeout glue input
        return CloseoutGlueInput(
            source_execution_id=receipt.source_spawn_execution_id,
            source_receipt_id=receipt.receipt_id,
            source_receipt_status=receipt.receipt_status,
            dispatch_readiness=dispatch_readiness,
            summary=summary,
            lineage_id=lineage_id,
            next_step=continuation_fields["next_step"],
            next_owner=continuation_fields["next_owner"],
            stopped_because=continuation_fields["stopped_because"],
            metadata={
                "source_task_id": receipt.source_task_id,
                "source_dispatch_id": receipt.source_dispatch_id,
                "source_spawn_id": receipt.source_spawn_id,
                "receipt_time": receipt.receipt_time,
                "business_result": receipt.business_result,
            },
        )


# 便捷函数
def map_receipt_to_closeout(
    receipt: CompletionReceiptArtifact,
) -> CloseoutGlueInput:
    """
    便捷函数：从 completion receipt 映射到 closeout 输入。
    
    Args:
        receipt: Completion receipt artifact
    
    Returns:
        CloseoutGlueInput
    """
    glue = ExecutionToCloseoutGlue()
    return glue.map_receipt_to_closeout_input(receipt)


# CLI 入口
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python closeout_glue.py test <receipt_id>")
        print("  python closeout_glue.py list-receipts [--status <status>]")
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == "test":
        # 测试模式：创建模拟 receipt 并测试映射
        from completion_receipt import CompletionReceiptArtifact, _iso_now
        
        # 创建模拟 receipt
        receipt = CompletionReceiptArtifact(
            receipt_id="test_receipt_001",
            source_spawn_execution_id="exec_001",
            source_spawn_id="spawn_001",
            source_dispatch_id="dispatch_001",
            source_registration_id="reg_001",
            source_task_id="task_001",
            receipt_status="completed",
            receipt_reason="Execution completed successfully",
            receipt_time=_iso_now(),
            result_summary="Test execution completed",
            dedupe_key="test_dedupe",
            metadata={
                "continuation_contract": {
                    "next_step": "Review and merge changes",
                    "next_owner": "main",
                    "stopped_because": "Execution completed successfully",
                },
                "lineage_id": "lineage_001",
            },
        )
        
        # 测试映射
        glue = ExecutionToCloseoutGlue()
        closeout_input = glue.map_receipt_to_closeout_input(receipt)
        
        print("=== Completion Receipt ===")
        print(f"Receipt ID: {receipt.receipt_id}")
        print(f"Status: {receipt.receipt_status}")
        print(f"Summary: {receipt.result_summary}")
        
        print("\n=== Closeout Glue Input ===")
        print(f"Source Execution ID: {closeout_input.source_execution_id}")
        print(f"Source Receipt ID: {closeout_input.source_receipt_id}")
        print(f"Dispatch Readiness: {closeout_input.dispatch_readiness}")
        print(f"Summary: {closeout_input.summary}")
        print(f"Next Step: {closeout_input.next_step}")
        print(f"Next Owner: {closeout_input.next_owner}")
        print(f"Stopped Because: {closeout_input.stopped_because}")
        print(f"Lineage ID: {closeout_input.lineage_id}")
        
        print("\n✅ Test passed: Receipt mapped to closeout input successfully")
    
    elif cmd == "list-receipts":
        from completion_receipt import list_completion_receipts
        
        status = None
        if "--status" in sys.argv:
            idx = sys.argv.index("--status")
            if idx + 1 < len(sys.argv):
                status = sys.argv[idx + 1]
        
        receipts = list_completion_receipts(receipt_status=status)
        print(f"Found {len(receipts)} receipts:")
        for r in receipts:
            print(f"  - {r.receipt_id}: {r.receipt_status} (task: {r.source_task_id})")
    
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
