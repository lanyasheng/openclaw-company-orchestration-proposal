#!/usr/bin/env python3
"""
completion_backwrite.py — Completion Backwrite Bridge for Ad-Hoc Tasks

目标：实现 ad-hoc trading tasks completion 结果自动回写到三个控制面系统：
1. task_registration.status -> completed/blocked/failed
2. state_machine.state -> callback_received/failed
3. observability_card.stage -> callback_received/failed

根因：
- ad-hoc tasks 通过 task_registration.py 注册，dispatch 到 subagent
- completion_receipt.py 创建 receipt，但没有回写到三个控制面系统
- state_sync.py 只覆盖 WorkflowState <-> state_machine，不覆盖 ad-hoc tasks

使用示例：
```python
from completion_backwrite import backwrite_completion

# 在 completion receipt 被消费时调用
backwrite_completion(
    receipt_id="receipt_xxx",
    task_id="task_xxx",
    registration_id="reg_xxx",
    receipt_status="completed",
    result_summary="Task completed successfully",
    metadata={...},
)
```
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Literal, Optional

from completion_receipt import CompletionReceiptArtifact, ReceiptStatus

logger = logging.getLogger(__name__)

__all__ = [
    "BackwriteResult",
    "backwrite_completion",
    "backwrite_to_task_registration",
    "backwrite_to_state_machine",
    "backwrite_to_observability_card",
]


@dataclass
class BackwriteResult:
    """
    Backwrite result — 记录回写操作的结果。
    
    核心字段：
    - task_registration_updated: task_registration 是否更新成功
    - state_machine_updated: state_machine 是否更新成功
    - observability_card_updated: observability_card 是否更新成功
    - errors: 错误列表（如果有）
    - metadata: 额外元数据
    """
    task_registration_updated: bool = False
    state_machine_updated: bool = False
    observability_card_updated: bool = False
    errors: list[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_registration_updated": self.task_registration_updated,
            "state_machine_updated": self.state_machine_updated,
            "observability_card_updated": self.observability_card_updated,
            "errors": self.errors,
            "metadata": self.metadata,
            "success": (
                self.task_registration_updated and
                self.state_machine_updated and
                self.observability_card_updated
            ),
            "partial_success": (
                self.task_registration_updated or
                self.state_machine_updated or
                self.observability_card_updated
            ),
        }


def _map_receipt_status_to_task_status(
    receipt_status: ReceiptStatus,
) -> Literal["completed", "blocked", "failed"]:
    """
    将 receipt status 映射到 task registration status。
    
    规则：
    - completed -> completed
    - failed -> failed
    - missing -> blocked (需要人工审查)
    """
    if receipt_status == "completed":
        return "completed"
    elif receipt_status == "failed":
        return "failed"
    else:  # missing
        return "blocked"


def _map_receipt_status_to_state_machine_state(
    receipt_status: ReceiptStatus,
) -> str:
    """
    将 receipt status 映射到 state_machine state。
    
    规则：
    - completed -> callback_received
    - failed -> failed
    - missing -> failed (保守处理)
    """
    if receipt_status == "completed":
        return "callback_received"
    else:  # failed or missing
        return "failed"


def _map_receipt_status_to_card_stage(
    receipt_status: ReceiptStatus,
) -> Literal["callback_received", "failed"]:
    """
    将 receipt status 映射到 observability_card stage。
    
    规则：
    - completed -> callback_received
    - failed -> failed
    - missing -> failed (保守处理)
    """
    if receipt_status == "completed":
        return "callback_received"
    else:  # failed or missing
        return "failed"


def backwrite_to_task_registration(
    registration_id: str,
    task_id: str,
    receipt_status: ReceiptStatus,
    result_summary: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    回写到 task_registration。
    
    Args:
        registration_id: Registration ID
        task_id: Task ID
        receipt_status: Receipt status
        result_summary: 结果摘要
        metadata: 额外元数据
    
    Returns:
        True 如果更新成功
    """
    try:
        from task_registration import TaskRegistry, TaskRegistrationRecord
        
        registry = TaskRegistry()
        record = registry.get(registration_id)
        
        if not record:
            logger.warning(
                "Registration %s not found for task %s, skipping backwrite",
                registration_id,
                task_id,
            )
            return False
        
        # P0-Hotfix (2026-03-31): Extract human_translation and continuation context
        metadata = metadata or {}
        human_translation = metadata.get("human_translation") or metadata.get("translation", "")
        continuation_contract = metadata.get("continuation_contract", {})
        next_step = continuation_contract.get("next_step", "") or metadata.get("next_step", "")
        stopped_because = continuation_contract.get("stopped_because", "") or metadata.get("stopped_because", "")
        
        # 更新状态
        new_status = _map_receipt_status_to_task_status(receipt_status)
        update_metadata = {
            **(record.metadata or {}),
            "completion_receipt_status": receipt_status,
            "completion_result_summary": result_summary[:500],
            "backwritten_at": metadata.get("backwritten_at"),
        }
        if human_translation:
            update_metadata["human_translation"] = human_translation
        if next_step:
            update_metadata["next_step"] = next_step
        if stopped_because:
            update_metadata["stopped_because"] = stopped_because
        
        updated_record = registry.update_status(
            registration_id=registration_id,
            new_status=new_status,
            metadata=update_metadata,
        )
        
        if updated_record:
            logger.info(
                "Backwrote task_registration %s: status=%s, receipt_status=%s",
                registration_id,
                new_status,
                receipt_status,
            )
            return True
        else:
            logger.warning("Failed to update registration %s", registration_id)
            return False
            
    except Exception as e:
        logger.exception("Error backwriting to task_registration: %s", e)
        return False


def backwrite_to_state_machine(
    task_id: str,
    receipt_status: ReceiptStatus,
    result: Dict[str, Any],
) -> bool:
    """
    回写到 state_machine。
    
    Args:
        task_id: Task ID
        receipt_status: Receipt status
        result: 回调结果（包含 receipt 信息）
    
    Returns:
        True 如果更新成功
    """
    try:
        from state_machine import get_state, mark_callback_received, mark_failed, create_task
        
        # 检查任务是否存在
        existing = get_state(task_id)
        
        if not existing:
            # 任务不存在，创建一个（ad-hoc 任务可能没有预先创建 state_machine 记录）
            logger.info("Creating state_machine record for ad-hoc task %s", task_id)
            create_task(task_id, timeout_seconds=3600)
        
        # P0-Hotfix (2026-03-31): Enrich result with human_translation and continuation context
        enriched_result = dict(result)  # Copy to avoid mutating input
        metadata = result.get("metadata", {}) or {}
        human_translation = metadata.get("human_translation") or metadata.get("translation", "")
        continuation_contract = metadata.get("continuation_contract", {})
        
        if human_translation:
            enriched_result["human_translation"] = human_translation
        if continuation_contract:
            enriched_result["continuation_contract"] = continuation_contract
            enriched_result["next_step"] = continuation_contract.get("next_step", "")
            enriched_result["stopped_because"] = continuation_contract.get("stopped_because", "")
        
        # 根据 receipt status 更新状态
        if receipt_status == "completed":
            mark_callback_received(task_id, enriched_result)
            logger.info(
                "Backwrote state_machine %s: callback_received",
                task_id,
            )
        else:
            mark_failed(task_id, error=enriched_result.get("receipt_reason", "completion failed"))
            logger.info(
                "Backwrote state_machine %s: failed (receipt_status=%s)",
                task_id,
                receipt_status,
            )
        
        return True
        
    except Exception as e:
        logger.exception("Error backwriting to state_machine: %s", e)
        return False


def backwrite_to_observability_card(
    task_id: str,
    receipt_status: ReceiptStatus,
    result_summary: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    回写到 observability_card。
    
    Args:
        task_id: Task ID
        receipt_status: Receipt status
        result_summary: 结果摘要
        metadata: 额外元数据（可能包含 scenario/owner 等信息）
    
    Returns:
        True 如果更新成功
    """
    try:
        from observability_card import get_card, update_card, create_card, CARD_DIR
        from pathlib import Path
        
        # 检查卡片是否存在
        card = get_card(task_id)
        
        metadata = metadata or {}
        scenario = metadata.get("scenario", "custom")
        owner = metadata.get("owner", "custom")
        executor = metadata.get("executor", "subagent")
        
        # P0-Hotfix (2026-03-31): Extract human_translation and continuation_contract from metadata
        human_translation = metadata.get("human_translation") or metadata.get("translation", "")
        continuation_contract = metadata.get("continuation_contract", {})
        next_step = continuation_contract.get("next_step", "") or metadata.get("next_step", "")
        stopped_because = continuation_contract.get("stopped_because", "") or metadata.get("stopped_because", "")
        
        if not card:
            # 卡片不存在，创建一个（ad-hoc 任务可能没有预先创建卡片）
            logger.info("Creating observability card for ad-hoc task %s", task_id)
            
            # 推导 stage
            initial_stage = "callback_received" if receipt_status == "completed" else "failed"
            
            create_card(
                task_id=task_id,
                scenario=scenario,  # type: ignore
                owner=owner,  # type: ignore
                executor=executor,  # type: ignore
                stage=initial_stage,  # type: ignore
                promised_eta=metadata.get("promised_eta", ""),
                anchor_type="receipt_id",
                anchor_value=metadata.get("receipt_id", ""),
                metadata={
                    "completion_receipt_status": receipt_status,
                    "completion_result_summary": result_summary[:500],
                    "human_translation": human_translation,
                    "next_step": next_step,
                    "stopped_because": stopped_because,
                    "auto_created": True,
                    "backwritten_at": metadata.get("backwritten_at"),
                },
            )
            logger.info(
                "Created observability card %s: stage=%s",
                task_id,
                initial_stage,
            )
            return True
        
        # 更新现有卡片
        new_stage = _map_receipt_status_to_card_stage(receipt_status)
        
        # P0-Hotfix: Include human_translation and continuation context in update
        update_metadata = {
            "completion_receipt_status": receipt_status,
            "completion_result_summary": result_summary[:500],
            "backwritten_at": metadata.get("backwritten_at"),
        }
        if human_translation:
            update_metadata["human_translation"] = human_translation
        if next_step:
            update_metadata["next_step"] = next_step
        if stopped_because:
            update_metadata["stopped_because"] = stopped_because
        
        updated = update_card(
            task_id=task_id,
            stage=new_stage,
            recent_output=result_summary[:1000],
            attach_info={
                "receipt_id": metadata.get("receipt_id"),
                "receipt_status": receipt_status,
                "execution_id": metadata.get("execution_id"),
            },
            gate_state={
                "completion_verified": True,
                "receipt_status": receipt_status,
            },
            metadata=update_metadata,
        )
        
        if updated:
            logger.info(
                "Backwrote observability_card %s: stage=%s, receipt_status=%s",
                task_id,
                new_stage,
                receipt_status,
            )
            return True
        else:
            logger.warning("Failed to update observability card %s", task_id)
            return False
            
    except Exception as e:
        logger.exception("Error backwriting to observability_card: %s", e)
        return False


def backwrite_completion(
    *,
    receipt: CompletionReceiptArtifact,
    task_id: Optional[str] = None,
    registration_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> BackwriteResult:
    """
    主入口函数：回写 completion 结果到三个控制面系统。
    
    Args:
        receipt: Completion receipt artifact
        task_id: Task ID（可选，默认从 receipt 中提取）
        registration_id: Registration ID（可选，默认从 receipt 中提取）
        metadata: 额外元数据
    
    Returns:
        BackwriteResult: 回写结果
    
    回写目标：
    1. task_registration.status -> completed/blocked/failed
    2. state_machine.state -> callback_received/failed
    3. observability_card.stage -> callback_received/failed
    """
    result = BackwriteResult()
    
    # 提取基本信息
    task_id = task_id or receipt.source_task_id
    registration_id = registration_id or receipt.source_registration_id
    receipt_status = receipt.receipt_status
    result_summary = receipt.result_summary
    
    # 构建元数据
    backwrite_metadata = {
        **(metadata or {}),
        "receipt_id": receipt.receipt_id,
        "execution_id": receipt.source_spawn_execution_id,
        "spawn_id": receipt.source_spawn_id,
        "dispatch_id": receipt.source_dispatch_id,
        "backwritten_at": receipt.receipt_time,
        "scenario": receipt.metadata.get("scenario", ""),
        "owner": receipt.metadata.get("owner", ""),
        "executor": receipt.metadata.get("executor", "subagent"),
    }
    
    # 从 receipt metadata 中提取 continuation contract 信息
    continuation = receipt.metadata.get("continuation_contract", {})
    if continuation:
        backwrite_metadata["next_step"] = continuation.get("next_step", "")
        backwrite_metadata["next_owner"] = continuation.get("next_owner", "")
        backwrite_metadata["stopped_because"] = continuation.get("stopped_because", "")
    
    # 构建 state_machine 结果
    state_machine_result = {
        "receipt_id": receipt.receipt_id,
        "receipt_status": receipt_status,
        "receipt_reason": receipt.receipt_reason,
        "result_summary": result_summary,
        "continuation_contract": continuation,
    }
    
    # ========== 1. 回写到 task_registration ==========
    if registration_id:
        result.task_registration_updated = backwrite_to_task_registration(
            registration_id=registration_id,
            task_id=task_id,
            receipt_status=receipt_status,
            result_summary=result_summary,
            metadata=backwrite_metadata,
        )
    else:
        result.errors.append("Missing registration_id, skipping task_registration backwrite")
    
    # ========== 2. 回写到 state_machine ==========
    result.state_machine_updated = backwrite_to_state_machine(
        task_id=task_id,
        receipt_status=receipt_status,
        result=state_machine_result,
    )
    
    # ========== 3. 回写到 observability_card ==========
    result.observability_card_updated = backwrite_to_observability_card(
        task_id=task_id,
        receipt_status=receipt_status,
        result_summary=result_summary,
        metadata=backwrite_metadata,
    )
    
    # 记录汇总日志
    logger.info(
        "Completion backwrite for task %s: task_reg=%s, state_machine=%s, obs_card=%s",
        task_id,
        result.task_registration_updated,
        result.state_machine_updated,
        result.observability_card_updated,
    )
    
    return result


# 便捷函数：从 receipt_id 触发 backwrite
def backwrite_from_receipt_id(
    receipt_id: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> BackwriteResult:
    """
    便捷函数：从 receipt_id 触发 backwrite。
    
    Args:
        receipt_id: Receipt ID
        metadata: 额外元数据
    
    Returns:
        BackwriteResult
    """
    from completion_receipt import get_completion_receipt
    
    receipt = get_completion_receipt(receipt_id)
    if not receipt:
        logger.error("Receipt %s not found", receipt_id)
        return BackwriteResult(errors=[f"Receipt {receipt_id} not found"])
    
    return backwrite_completion(receipt=receipt, metadata=metadata)


# CLI 入口
if __name__ == "__main__":
    import sys
    import json
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python completion_backwrite.py from-receipt <receipt_id>")
        print("  python completion_backwrite.py test")
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == "from-receipt":
        if len(sys.argv) < 3:
            print("Error: missing receipt_id")
            sys.exit(1)
        
        receipt_id = sys.argv[2]
        result = backwrite_from_receipt_id(receipt_id)
        print(json.dumps(result.to_dict(), indent=2))
    
    elif cmd == "test":
        # 测试模式：创建模拟 receipt 并测试 backwrite
        from completion_receipt import CompletionReceiptArtifact, _iso_now
        
        receipt = CompletionReceiptArtifact(
            receipt_id="test_receipt_backwrite",
            source_spawn_execution_id="exec_test",
            source_spawn_id="spawn_test",
            source_dispatch_id="dispatch_test",
            source_registration_id="reg_test",
            source_task_id="task_test_backwrite",
            receipt_status="completed",
            receipt_reason="Test execution completed successfully",
            receipt_time=_iso_now(),
            result_summary="Test task completed successfully",
            dedupe_key="test_dedupe_backwrite",
            metadata={
                "scenario": "test_scenario",
                "owner": "test_owner",
                "executor": "subagent",
                "continuation_contract": {
                    "next_step": "Test next step",
                    "next_owner": "test_owner",
                    "stopped_because": "Test completed",
                },
            },
        )
        
        result = backwrite_completion(receipt=receipt)
        print("=== Backwrite Result ===")
        print(json.dumps(result.to_dict(), indent=2))
        
        if result.success:
            print("\n✅ Test passed: Backwrite completed successfully")
        else:
            print("\n⚠️  Test partial: Some backwrites failed")
            print(f"Errors: {result.errors}")
    
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
