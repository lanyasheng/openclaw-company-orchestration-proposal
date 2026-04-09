#!/usr/bin/env python3
"""
closeout_generator.py — Closeout Generation for Trading Roundtable

负责构建 trading partial closeout 和生成 next task registrations。
"""

from __future__ import annotations

from typing import Any, Dict, List

from adapters.trading import ADAPTER_NAME, SCENARIO
from partial_continuation import (
    build_partial_closeout,
    adapt_closeout_for_trading,
    generate_registered_registrations_for_closeout,
    ScopeItem,
)
from closeout_tracker import ContinuationContract


class CloseoutGenerator:
    """Trading closeout 生成器"""
    
    def build_partial_closeout_for_trading(
        self,
        batch_id: str,
        decision: Any,
        analysis: Dict[str, Any],
    ) -> Any:
        """
        构建 trading partial closeout
        
        Args:
            batch_id: 批次 ID
            decision: Decision 对象
            analysis: batch 分析结果
        
        Returns:
            适配后的 closeout 对象
        """
        decision_dict = decision.to_dict() if hasattr(decision, 'to_dict') else decision
        packet = decision_dict.get("metadata", {}).get("packet", {})
        roundtable = decision_dict.get("metadata", {}).get("roundtable", {})
        validation = decision_dict.get("metadata", {}).get("packet_validation", {})
        supporting_results = decision_dict.get("metadata", {}).get("supporting_results", [])
        action = decision_dict.get("action", "")
        reason = decision_dict.get("reason", "")
        
        # 构建 completed_scope
        completed_scope = []
        for item in supporting_results:
            if item.get("state") in ("callback_received", "final_closed", "next_task_dispatched"):
                completed_scope.append(
                    ScopeItem(
                        item_id=item.get("task_id", ""),
                        description=f"Task {item.get('task_id', '')}: {item.get('summary') or item.get('verdict') or 'completed'}",
                        status="completed",
                        metadata={"state": item.get("state"), "verdict": item.get("verdict")},
                    )
                )
        
        # 构建 remaining_scope
        remaining_scope = []
        stop_reason = "completed_all"
        
        if action == "proceed":
            next_step = roundtable.get("next_step", "")
            if next_step:
                remaining_scope.append(
                    ScopeItem(
                        item_id="next_step_1",
                        description=next_step,
                        status="not_started",
                        metadata={
                            "completion_criteria": roundtable.get("completion_criteria", ""),
                            "blocker": "none",
                        },
                    )
                )
                stop_reason = "partial_completed"
        elif action == "fix_blocker":
            blocker = roundtable.get("blocker") or packet.get("primary_blocker", "unknown")
            remaining_scope.append(
                ScopeItem(
                    item_id="fix_blocker_1",
                    description=f"Resolve blocker: {blocker}",
                    status="blocked",
                    metadata={
                        "blocker_type": blocker,
                        "completion_criteria": roundtable.get("completion_criteria", ""),
                    },
                )
            )
            stop_reason = "blocked"
        elif action == "abort":
            stop_reason = "failed"
        
        # 如果 packet incomplete，添加 remaining scope
        if not validation.get("complete"):
            missing_fields = validation.get("missing_fields", [])
            for field in missing_fields[:3]:
                remaining_scope.append(
                    ScopeItem(
                        item_id=f"missing_{field.replace('.', '_')}",
                        description=f"Fill missing field: {field}",
                        status="not_started",
                        metadata={"field_type": "packet_completeness"},
                    )
                )
            if stop_reason == "completed_all":
                stop_reason = "partial_completed"
        
        # 构建 generic closeout
        closeout = build_partial_closeout(
            completed_scope=[item.to_dict() for item in completed_scope],
            remaining_scope=[item.to_dict() for item in remaining_scope],
            stop_reason=stop_reason,
            original_batch_id=batch_id,
            metadata={
                "decision_action": action,
                "decision_reason": reason,
            },
        )
        
        # 适配 trading 场景
        adapted = adapt_closeout_for_trading(closeout=closeout, packet=packet, roundtable=roundtable)
        
        # P0-1 Batch 3: Inject unified continuation contract into closeout metadata
        if action == "proceed":
            stopped_because = "roundtable_gate_pass_continuation_ready"
        elif action == "fix_blocker":
            stopped_because = f"roundtable_gate_conditional_blocker_{roundtable.get('blocker', 'unknown')}"
        elif action == "abort":
            stopped_because = f"roundtable_gate_fail_blocker_{roundtable.get('blocker', 'unknown')}"
        else:
            stopped_because = f"decision_action_{action}"
        
        next_step = roundtable.get("next_step", "") or reason
        next_owner = roundtable.get("owner", "") or packet.get("owner", "") or "trading"
        
        continuation = ContinuationContract(
            stopped_because=stopped_because,
            next_step=next_step,
            next_owner=next_owner,
            metadata={
                "decision_action": action,
                "roundtable_conclusion": roundtable.get("conclusion", ""),
                "roundtable_blocker": roundtable.get("blocker", ""),
            },
        )
        continuation.merge_into_closeout(adapted)
        
        return adapted
    
    def generate_next_registrations_for_trading(
        self,
        closeout: Any,
        batch_id: str,
    ) -> List[Dict[str, Any]]:
        """
        为 trading 生成 next task registrations
        
        Args:
            closeout: closeout 对象
            batch_id: 批次 ID
        
        Returns:
            registrations 列表
        """
        if not hasattr(closeout, 'should_generate_next_registration') or not closeout.should_generate_next_registration():
            return []
        
        registrations = generate_registered_registrations_for_closeout(
            closeout=closeout,
            adapter=ADAPTER_NAME,
            scenario=SCENARIO,
            max_candidates=3,
            context={
                "batch_id": batch_id,
                "generated_by": "trading_roundtable_partial_continuation_v2",
            },
            auto_register=True,
            batch_id=batch_id,
            owner=closeout.metadata.get("trading_roundtable", {}).get("owner"),
        )
        
        return [reg.to_dict() for reg in registrations]
