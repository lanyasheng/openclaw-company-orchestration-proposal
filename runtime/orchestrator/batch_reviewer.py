from __future__ import annotations

from datetime import datetime, timezone

from workflow_state import (
    BatchEntry,
    ContinuationDecision,
    WorkflowState,
)

__all__ = ["BatchReviewer"]


class BatchReviewer:
    """评审批次结果，决定是否推进到下一批"""

    def review(self, batch: BatchEntry, workflow_state: WorkflowState) -> ContinuationDecision:
        now = datetime.now(timezone.utc).isoformat()
        next_batch = self._find_next_batch_id(batch.batch_id, workflow_state)
        fan_ok, fan_reason = self._evaluate_fan_in(batch)
        if not fan_ok:
            return ContinuationDecision(
                stopped_because=fan_reason,
                decision="stop",
                next_batch=None,
                decided_at=now,
            )
        if self._check_gate_conditions(batch, workflow_state):
            return ContinuationDecision(
                stopped_because="manual review required",
                decision="gate",
                next_batch=next_batch,
                decided_at=now,
            )
        return ContinuationDecision(
            stopped_because=fan_reason,
            decision="proceed",
            next_batch=next_batch,
            decided_at=now,
        )

    def _find_next_batch_id(self, current_batch_id: str, workflow_state: WorkflowState) -> str | None:
        for i, b in enumerate(workflow_state.batches):
            if b.batch_id == current_batch_id and i + 1 < len(workflow_state.batches):
                return workflow_state.batches[i + 1].batch_id
        return None

    def _evaluate_fan_in(self, batch: BatchEntry) -> tuple[bool, str]:
        tasks = batch.tasks
        if not tasks:
            return False, "empty batch"
        n = len(tasks)
        completed = sum(1 for t in tasks if t.status == "completed")
        policy = batch.fan_in_policy
        if policy == "all_success":
            ok = completed == n
            return (ok, "all tasks completed" if ok else f"expected {n} completed, got {completed}")
        if policy == "any_success":
            ok = completed >= 1
            return (ok, "at least one completed" if ok else "no completed task")
        if policy == "majority":
            ok = completed > n / 2
            return (ok, "majority completed" if ok else f"need >{n / 2:.1f} completed, got {completed}")
        return False, f"unknown fan_in_policy: {policy!r}"

    def _check_gate_conditions(self, batch: BatchEntry, workflow_state: WorkflowState) -> bool:
        _ = workflow_state
        return any("NEEDS_REVIEW" in (t.result_summary or "") for t in batch.tasks)
