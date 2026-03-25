from __future__ import annotations

import heapq
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Tuple

from workflow_state import (
    BatchEntry,
    TaskEntry,
    WorkflowState,
    create_workflow,
    save_workflow_state,
)

__all__ = ["TaskPlanner"]


def _batch_ids(batches_config: List[Dict]) -> List[str]:
    return [str(b["batch_id"]) for b in batches_config]


def _deps_valid(batches_config: List[Dict]) -> bool:
    ids = set(_batch_ids(batches_config))
    for b in batches_config:
        for d in b.get("depends_on") or []:
            if str(d) not in ids:
                return False
    return True


def _kahn(batches_config: List[Dict]) -> Tuple[bool, List[str]]:
    ids = _batch_ids(batches_config)
    id_set = set(ids)
    indeg: Dict[str, int] = {bid: 0 for bid in id_set}
    succ: Dict[str, List[str]] = defaultdict(list)
    for b in batches_config:
        bid = str(b["batch_id"])
        deps = [str(d) for d in (b.get("depends_on") or [])]
        indeg[bid] = len(deps)
        for d in deps:
            succ[d].append(bid)
    for k in succ:
        succ[k].sort()
    heap = [bid for bid in id_set if indeg[bid] == 0]
    heapq.heapify(heap)
    order: List[str] = []
    while heap:
        u = heapq.heappop(heap)
        order.append(u)
        for v in succ[u]:
            indeg[v] -= 1
            if indeg[v] == 0:
                heapq.heappush(heap, v)
    return len(order) == len(id_set), order


@dataclass
class TaskPlanner:
    """将总任务拆解为批次序列，支持 DAG 依赖"""

    def plan(self, description: str, tasks_config: List[Dict]) -> WorkflowState:
        bids = _batch_ids(tasks_config)
        if len(bids) != len(set(bids)):
            raise ValueError("duplicate batch_id")
        if not _deps_valid(tasks_config):
            raise ValueError("depends_on references unknown batch_id")
        if not self.validate_dag(tasks_config):
            raise ValueError("batch dependency graph has a cycle")
        order = self.topological_sort(tasks_config)
        by_id = {str(b["batch_id"]): b for b in tasks_config}
        ordered = [by_id[bid] for bid in order]
        workflow_id = datetime.now().strftime("wf_%Y%m%d_%H%M%S")
        return create_workflow(workflow_id, description, ordered)

    def validate_dag(self, batches_config: List[Dict]) -> bool:
        if not _deps_valid(batches_config):
            return False
        ok, _ = _kahn(batches_config)
        return ok

    def topological_sort(self, batches_config: List[Dict]) -> List[str]:
        if not _deps_valid(batches_config):
            raise ValueError("depends_on references unknown batch_id")
        ok, order = _kahn(batches_config)
        if not ok:
            raise ValueError("batch dependency graph has a cycle")
        return order
