#!/usr/bin/env python3
"""
payload_extractor.py — Payload Extraction for Trading Roundtable

负责从 batch 任务中提取和合并 payloads。
"""

from __future__ import annotations

from typing import Any, Dict, List

from adapters.trading import ADAPTER_NAME
from state_machine import get_batch_tasks


def _merge_first_non_empty(target: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    """
    合并非空值到 target 中。
    
    规则：
    - 如果 patch 的值是 dict，递归合并
    - 如果 target 中不存在该 key 或值为空 (None/" "/[]/{})，则使用 patch 的值
    """
    for key, value in patch.items():
        if isinstance(value, dict):
            child = target.get(key, {})
            if not isinstance(child, dict):
                child = {}
            target[key] = _merge_first_non_empty(child, value)
        elif key not in target or target[key] in (None, "", [], {}):
            target[key] = value
    return target


def extract_payloads(batch_id: str) -> Dict[str, Any]:
    """
    从 batch 任务中提取 payloads。
    
    Returns:
        包含以下字段的 dict：
        - packet: 合并后的 packet 数据
        - roundtable: 合并后的 roundtable 数据
        - supporting_results: 所有任务的结果列表
    """
    packet: Dict[str, Any] = {}
    roundtable: Dict[str, Any] = {}
    supporting_results: List[Dict[str, Any]] = []

    for task in get_batch_tasks(batch_id):
        result = task.get("result") or {}
        scoped = result.get(ADAPTER_NAME) or {}
        
        # 合并 packet
        if isinstance(scoped.get("packet"), dict):
            packet = _merge_first_non_empty(packet, scoped["packet"])
        
        # 合并 roundtable
        if isinstance(scoped.get("roundtable"), dict):
            roundtable = _merge_first_non_empty(roundtable, scoped["roundtable"])
        
        # 提取 waiting_guard 和 closeout
        waiting_guard = result.get("waiting_guard") if isinstance(result.get("waiting_guard"), dict) else {}
        closeout = result.get("closeout") if isinstance(result.get("closeout"), dict) else waiting_guard.get("closeout")
        
        # 构建 supporting result
        supporting_results.append({
            "task_id": task["task_id"],
            "state": task.get("state"),
            "verdict": result.get("verdict"),
            "summary": result.get("summary") or scoped.get("summary"),
            "error": result.get("error"),
            "waiting_guard": waiting_guard or None,
            "closeout": closeout if isinstance(closeout, dict) else None,
        })

    return {
        "packet": packet,
        "roundtable": roundtable,
        "supporting_results": supporting_results,
    }
