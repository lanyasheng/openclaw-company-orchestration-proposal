#!/usr/bin/env python3
"""
test_payload_extractor.py — Tests for payload_extractor module

注意：extract_payloads 从 state_machine 读取任务状态，
所以测试需要通过更新任务状态来模拟结果。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ORCHESTRATOR_DIR = REPO_ROOT / "runtime" / "orchestrator"
if str(ORCHESTRATOR_DIR) not in sys.path:
    sys.path.insert(0, str(ORCHESTRATOR_DIR))

from payload_extractor import extract_payloads, _merge_first_non_empty
from state_machine import create_task, get_state, STATE_DIR  # type: ignore
from datetime import datetime


@pytest.fixture(autouse=True)
def isolated_state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """隔离的测试环境"""
    state_dir = tmp_path / "shared-context" / "job-status"
    state_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OPENCLAW_STATE_DIR", str(state_dir))
    return state_dir


class TestMergeFirstNonEmpty:
    """测试 _merge_first_non_empty 函数"""
    
    def test_merge_simple_values(self):
        """测试简单值合并"""
        target = {"a": 1, "b": 2}
        patch = {"b": 3, "c": 4}
        result = _merge_first_non_empty(target, patch)
        assert result["a"] == 1  # 保持不变
        assert result["b"] == 2  # target 已有值，不覆盖
        assert result["c"] == 4  # 新值
    
    def test_merge_nested_dicts(self):
        """测试嵌套 dict 合并"""
        target = {"outer": {"inner1": 1}}
        patch = {"outer": {"inner2": 2}}
        result = _merge_first_non_empty(target, patch)
        assert result["outer"]["inner1"] == 1
        assert result["outer"]["inner2"] == 2
    
    def test_merge_empty_target(self):
        """测试空 target 合并"""
        target = {}
        patch = {"a": 1, "b": {"c": 2}}
        result = _merge_first_non_empty(target, patch)
        assert result == {"a": 1, "b": {"c": 2}}
    
    def test_merge_none_values(self):
        """测试 None 值被覆盖"""
        target = {"a": None, "b": ""}
        patch = {"a": 1, "b": "filled"}
        result = _merge_first_non_empty(target, patch)
        assert result["a"] == 1
        assert result["b"] == "filled"


def _create_task_with_result(task_id: str, batch_id: str, result: dict):
    """Helper: 创建任务并设置结果"""
    create_task(task_id=task_id, batch_id=batch_id)
    # 更新任务状态添加结果
    state_path = STATE_DIR / f"{task_id}.json"
    if state_path.exists():
        state = json.loads(state_path.read_text())
        state["result"] = result
        state["state"] = "callback_received"
        state_path.write_text(json.dumps(state, indent=2))


class TestExtractPayloads:
    """测试 extract_payloads 函数"""
    
    def test_extract_payloads_from_single_task(self, isolated_state_dir: Path):
        """测试从单个任务提取 payloads"""
        batch_id = "test_batch_single"
        task_id = "tsk_single_001"
        
        _create_task_with_result(
            task_id=task_id,
            batch_id=batch_id,
            result={
                "trading_roundtable": {
                    "packet": {"field1": "value1"},
                    "roundtable": {"conclusion": "PASS"},
                }
            },
        )
        
        payloads = extract_payloads(batch_id)
        
        assert payloads["packet"]["field1"] == "value1"
        assert payloads["roundtable"]["conclusion"] == "PASS"
        assert len(payloads["supporting_results"]) == 1
    
    def test_extract_payloads_merges_multiple_tasks(self, isolated_state_dir: Path):
        """测试从多个任务合并 payloads"""
        batch_id = "test_batch_multi"
        
        _create_task_with_result(
            task_id="tsk_multi_001",
            batch_id=batch_id,
            result={
                "trading_roundtable": {
                    "packet": {"field1": "value1", "shared": "from_task1"},
                    "roundtable": {"conclusion": "PASS"},
                }
            },
        )
        
        _create_task_with_result(
            task_id="tsk_multi_002",
            batch_id=batch_id,
            result={
                "trading_roundtable": {
                    "packet": {"field2": "value2", "shared": "from_task2"},
                    "roundtable": {"blocker": "none"},
                }
            },
        )
        
        payloads = extract_payloads(batch_id)
        
        # 应该合并两个 packet
        assert payloads["packet"]["field1"] == "value1"
        assert payloads["packet"]["field2"] == "value2"
        # shared 字段应该保留第一个任务的值（非空不覆盖）
        assert payloads["packet"]["shared"] == "from_task1"
        
        # roundtable 也应该合并
        assert payloads["roundtable"]["conclusion"] == "PASS"
        assert payloads["roundtable"]["blocker"] == "none"
        
        assert len(payloads["supporting_results"]) == 2
    
    def test_extract_payloads_handles_waiting_guard(self, isolated_state_dir: Path):
        """测试提取 waiting_guard 和 closeout"""
        batch_id = "test_batch_waiting"
        task_id = "tsk_waiting_001"
        
        _create_task_with_result(
            task_id=task_id,
            batch_id=batch_id,
            result={
                "trading_roundtable": {
                    "packet": {"field1": "value1"},
                },
                "waiting_guard": {
                    "status": "waiting",
                    "closeout": {"reason": "pending"},
                },
            },
        )
        
        payloads = extract_payloads(batch_id)
        
        assert len(payloads["supporting_results"]) == 1
        supporting = payloads["supporting_results"][0]
        assert supporting["waiting_guard"] is not None
        assert supporting["closeout"] == {"reason": "pending"}
    
    def test_extract_payloads_handles_empty_result(self, isolated_state_dir: Path):
        """测试处理空结果"""
        batch_id = "test_batch_empty"
        task_id = "tsk_empty_001"
        
        _create_task_with_result(
            task_id=task_id,
            batch_id=batch_id,
            result={},
        )
        
        payloads = extract_payloads(batch_id)
        
        assert payloads["packet"] == {}
        assert payloads["roundtable"] == {}
        assert len(payloads["supporting_results"]) == 1
