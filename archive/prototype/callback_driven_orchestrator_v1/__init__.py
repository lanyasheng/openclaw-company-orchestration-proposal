"""
回调驱动编排器 v1（proposal repo 同步快照）

同步来源：orchestrator @ 64da26e
"""

from .batch_aggregator import (
    analyze_batch_results,
    check_and_summarize_batch,
    detect_stuck_batches,
    generate_batch_summary_md,
    get_batches_by_state,
)
from .orchestrator import (
    Decision,
    Orchestrator,
    create_default_orchestrator,
    rule_all_success,
    rule_has_common_blocker,
    rule_major_failure,
    rule_partial_failure,
)
from .state_machine import (
    TaskState,
    create_task,
    get_batch_summary,
    get_batch_summary_content,
    get_batch_tasks,
    get_state,
    is_batch_complete,
    list_tasks,
    mark_callback_received,
    mark_failed,
    mark_final_closed,
    mark_next_dispatched,
    mark_timeout,
    retry_task,
    update_state,
    write_batch_summary,
)

__version__ = "1.0.0"

__all__ = [
    "TaskState",
    "create_task",
    "update_state",
    "get_state",
    "list_tasks",
    "get_batch_tasks",
    "is_batch_complete",
    "get_batch_summary",
    "write_batch_summary",
    "get_batch_summary_content",
    "mark_timeout",
    "mark_failed",
    "mark_callback_received",
    "mark_next_dispatched",
    "mark_final_closed",
    "retry_task",
    "analyze_batch_results",
    "generate_batch_summary_md",
    "check_and_summarize_batch",
    "get_batches_by_state",
    "detect_stuck_batches",
    "Decision",
    "Orchestrator",
    "create_default_orchestrator",
    "rule_all_success",
    "rule_partial_failure",
    "rule_major_failure",
    "rule_has_common_blocker",
]
