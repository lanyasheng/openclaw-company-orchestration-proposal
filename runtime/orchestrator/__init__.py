"""
回调驱动编排器 v1

模块：
- state_machine: 任务状态机
- batch_aggregator: Fan-in 汇总层
- orchestrator: 回调驱动编排器
"""

from state_machine import (
    TaskState,
    create_task,
    update_state,
    get_state,
    list_tasks,
    get_batch_tasks,
    is_batch_complete,
    get_batch_summary,
    write_batch_summary,
    get_batch_summary_content,
    mark_timeout,
    mark_failed,
    mark_callback_received,
    mark_next_dispatched,
    mark_final_closed,
    retry_task,
)

from batch_aggregator import (
    analyze_batch_results,
    generate_batch_summary_md,
    check_and_summarize_batch,
    get_batches_by_state,
    detect_stuck_batches,
)

from orchestrator import (
    Decision,
    Orchestrator,
    create_default_orchestrator,
    rule_all_success,
    rule_partial_failure,
    rule_major_failure,
    rule_has_common_blocker,
)
from trading_roundtable import (
    process_trading_roundtable_callback,
)
from channel_roundtable import (
    process_channel_roundtable_callback,
)
from contracts import (
    TASK_TIER_ORCHESTRATED,
    TASK_TIER_PLAIN,
    TASK_TIER_TRACKED,
    classify_callback_payload,
    extract_explicit_orchestration_contract,
    is_orchestrated_payload,
    resolve_orchestration_contract,
)

__version__ = "1.0.0"
__all__ = [
    # State Machine
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
    # Batch Aggregator
    "analyze_batch_results",
    "generate_batch_summary_md",
    "check_and_summarize_batch",
    "get_batches_by_state",
    "detect_stuck_batches",
    # Orchestrator
    "Decision",
    "Orchestrator",
    "create_default_orchestrator",
    "rule_all_success",
    "rule_partial_failure",
    "rule_major_failure",
    "rule_has_common_blocker",
    # Trading roundtable glue
    "process_trading_roundtable_callback",
    # Generic channel/thread roundtable glue
    "process_channel_roundtable_callback",
    # Orchestration contract helpers
    "TASK_TIER_PLAIN",
    "TASK_TIER_TRACKED",
    "TASK_TIER_ORCHESTRATED",
    "classify_callback_payload",
    "extract_explicit_orchestration_contract",
    "is_orchestrated_payload",
    "resolve_orchestration_contract",
]
