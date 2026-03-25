#!/usr/bin/env python3
"""
回调驱动编排器 v1 — 根据汇总结果决定下一批派什么

决策逻辑：
- 如果全部成功 → 派下一阶段
- 如果部分失败 → 派重试/修复
- 如果大部分失败 → 中止并报告
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from state_machine import (
    TaskState,
    create_task,
    update_state,
    get_state,
    get_batch_tasks,
    get_batch_summary,
    is_batch_complete,
    mark_callback_received,
    mark_next_dispatched,
    mark_final_closed,
    mark_failed,
    retry_task,
    STATE_DIR,
    _ensure_state_dir,
    _iso_now,
)
from batch_aggregator import (
    analyze_batch_results,
    generate_batch_summary_md,
    check_and_summarize_batch,
    get_batch_summary_content,
)


# 决策存储目录
DECISIONS_DIR = STATE_DIR.parent / "orchestrator" / "decisions"
DISPATCHES_DIR = STATE_DIR.parent / "orchestrator" / "dispatches"


def _ensure_dirs():
    """确保所有目录存在"""
    _ensure_state_dir()
    DECISIONS_DIR.mkdir(parents=True, exist_ok=True)
    DISPATCHES_DIR.mkdir(parents=True, exist_ok=True)


def _decision_file(decision_id: str) -> Path:
    """返回决策文件路径"""
    return DECISIONS_DIR / f"{decision_id}.json"


def _dispatch_file(dispatch_id: str) -> Path:
    """返回派发文件路径"""
    return DISPATCHES_DIR / f"{dispatch_id}.json"


def _generate_decision_id(batch_id: str) -> str:
    """生成决策 ID"""
    return f"dec_{batch_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}"


def _generate_dispatch_id() -> str:
    """生成派发 ID"""
    return f"disp_{datetime.now().strftime('%Y%m%d%H%M%S')}"


class Decision:
    """决策结果"""
    
    def __init__(
        self,
        action: str,
        reason: str,
        next_tasks: Optional[List[Dict[str, Any]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        decision_id: Optional[str] = None,
    ):
        self.action = action  # "proceed" | "retry" | "abort"
        self.reason = reason
        self.next_tasks = next_tasks or []
        self.metadata = metadata or {}
        self.decision_id = decision_id
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "action": self.action,
            "reason": self.reason,
            "next_tasks": self.next_tasks,
            "metadata": self.metadata,
        }


class Orchestrator:
    """
    回调驱动编排器
    
    使用方式：
    1. 注册决策规则
    2. 调用 process_batch_callback() 处理回调
    3. 编排器自动决策并派发下一轮
    """
    
    def __init__(self):
        _ensure_dirs()
        self._rules: List[Callable[[str, Dict[str, Any]], Optional[Decision]]] = []
        self._dispatch_callback: Optional[Callable[[Dict[str, Any]], str]] = None
    
    def register_rule(
        self,
        rule: Callable[[str, Dict[str, Any]], Optional[Decision]],
    ):
        """
        注册决策规则
        
        规则函数签名：
          def rule(batch_id: str, analysis: Dict[str, Any]) -> Optional[Decision]
        
        返回 None 表示规则不适用，返回 Decision 表示决策结果
        """
        self._rules.append(rule)
    
    def set_dispatch_callback(
        self,
        callback: Callable[[Dict[str, Any]], str],
    ):
        """
        设置派发回调函数
        
        回调函数签名：
          def dispatch(task: Dict[str, Any]) -> str
        
        返回新派发任务的 task_id
        """
        self._dispatch_callback = callback
    
    def decide(self, batch_id: str) -> Optional[Decision]:
        """
        对批次做出决策
        
        Args:
            batch_id: 批次 ID
        
        Returns:
            决策结果，如果没有规则适用则返回 None
        """
        analysis = analyze_batch_results(batch_id)
        
        # 按顺序尝试每个规则
        for rule in self._rules:
            try:
                decision = rule(batch_id, analysis)
                if decision is not None:
                    # 记录决策
                    decision_id = _generate_decision_id(batch_id)
                    decision.decision_id = decision_id
                    decision_data = {
                        "decision_id": decision_id,
                        "batch_id": batch_id,
                        "timestamp": _iso_now(),
                        **decision.to_dict(),
                    }
                    
                    # 原子写入
                    tmp_file = _decision_file(decision_id).with_suffix(".tmp")
                    with open(tmp_file, "w") as f:
                        json.dump(decision_data, f, indent=2)
                    tmp_file.replace(_decision_file(decision_id))
                    
                    return decision
            except Exception as e:
                # 规则失败不影响其他规则
                print(f"Rule failed: {e}")
                continue
        
        return None
    
    def process_batch_callback(
        self,
        batch_id: str,
        task_id: str,
        result: Dict[str, Any],
    ) -> Optional[str]:
        """
        处理批次回调
        
        Args:
            batch_id: 批次 ID
            task_id: 任务 ID
            result: 任务执行结果
        
        Returns:
            如果触发了新派发则返回 dispatch_id，否则返回 None
        """
        mark_callback_received(task_id, result)

        self._sync_to_workflow_state(task_id, "callback_received", result)

        if not is_batch_complete(batch_id):
            return None
        
        # 3. 生成汇总报告
        check_and_summarize_batch(batch_id)
        
        # 4. 做出决策
        decision = self.decide(batch_id)
        if decision is None:
            return None  # 没有规则适用
        
        # 5. 派发下一轮任务
        next_task_ids = []
        if decision.next_tasks:
            if self._dispatch_callback is None:
                raise RuntimeError("Dispatch callback not set")
            
            for task_template in decision.next_tasks:
                new_task_id = self._dispatch_callback(task_template)
                next_task_ids.append(new_task_id)
        
        # 6. 标记当前批次任务已派发下一轮
        # （这里简化处理，只标记 batch 的代表任务）
        tasks = get_batch_tasks(batch_id)
        if tasks:
            # 选第一个任务作为代表
            representative_task_id = tasks[0]["task_id"]
            mark_next_dispatched(representative_task_id, next_task_ids)
        
        # 7. 记录派发
        dispatch_id = _generate_dispatch_id()
        dispatch_data = {
            "dispatch_id": dispatch_id,
            "batch_id": batch_id,
            "decision_id": decision.decision_id,
            "timestamp": _iso_now(),
            "next_task_ids": next_task_ids,
            "decision": decision.to_dict(),
        }
        
        # 原子写入
        tmp_file = _dispatch_file(dispatch_id).with_suffix(".tmp")
        with open(tmp_file, "w") as f:
            json.dump(dispatch_data, f, indent=2)
        tmp_file.replace(_dispatch_file(dispatch_id))
        
        return dispatch_id
    
    def get_decision(self, decision_id: str) -> Optional[Dict[str, Any]]:
        decision_file = _decision_file(decision_id)
        if not decision_file.exists():
            return None
        with open(decision_file, "r") as f:
            return json.load(f)

    def get_dispatch(self, dispatch_id: str) -> Optional[Dict[str, Any]]:
        dispatch_file = _dispatch_file(dispatch_id)
        if not dispatch_file.exists():
            return None
        with open(dispatch_file, "r") as f:
            return json.load(f)

    def _sync_to_workflow_state(
        self, task_id: str, status: str, result: Optional[Dict[str, Any]] = None
    ) -> None:
        try:
            from state_sync import sync_callback_to_workflow_state, find_active_workflow_state
            ws_path = find_active_workflow_state()
            if ws_path:
                sync_callback_to_workflow_state(ws_path, task_id, status, result)
        except Exception:
            pass


# ============ 内置决策规则 ============

def rule_all_success(batch_id: str, analysis: Dict[str, Any]) -> Optional[Decision]:
    """如果全部成功，推进到下一阶段"""
    if analysis.get("success_rate", 0) == 1.0 and analysis.get("is_complete"):
        return Decision(
            action="proceed",
            reason="All tasks succeeded, proceeding to next phase",
            next_tasks=[],  # 由上层根据具体业务填充
        )
    return None


def rule_partial_failure(batch_id: str, analysis: Dict[str, Any]) -> Optional[Decision]:
    """如果部分失败，重试失败任务"""
    success_rate = analysis.get("success_rate", 0)
    if 0.5 <= success_rate < 1.0 and analysis.get("is_complete"):
        # 找出失败任务
        tasks = get_batch_tasks(batch_id)
        retry_tasks = []
        for task in tasks:
            if task.get("state") in (TaskState.FAILED.value, TaskState.TIMEOUT.value):
                retry_tasks.append({
                    "type": "retry",
                    "original_task_id": task["task_id"],
                    "retry_count": task.get("retry_count", 0) + 1,
                })
        
        return Decision(
            action="retry",
            reason=f"Partial success ({success_rate:.1%}), retrying failed tasks",
            next_tasks=retry_tasks,
        )
    return None


def rule_major_failure(batch_id: str, analysis: Dict[str, Any]) -> Optional[Decision]:
    """如果大部分失败，中止并报告"""
    success_rate = analysis.get("success_rate", 0)
    if success_rate < 0.5 and analysis.get("is_complete"):
        return Decision(
            action="abort",
            reason=f"Low success rate ({success_rate:.1%}), aborting and reporting",
            metadata={
                "common_blockers": analysis.get("common_blockers", []),
            },
        )
    return None


def rule_has_common_blocker(batch_id: str, analysis: Dict[str, Any]) -> Optional[Decision]:
    """如果有共同 blocker，先修复 blocker"""
    common_blockers = analysis.get("common_blockers", [])
    if common_blockers and analysis.get("is_complete"):
        return Decision(
            action="fix_blocker",
            reason=f"Common blockers detected: {[b['error'] for b in common_blockers]}",
            metadata={
                "common_blockers": common_blockers,
            },
        )
    return None


# ============ 默认编排器实例 ============

def create_default_orchestrator() -> Orchestrator:
    """
    创建默认编排器实例（注册内置规则）
    
    规则优先级：
    1. 全部成功 → 推进
    2. 有共同 blocker → 修复 blocker
    3. 部分失败 → 重试
    4. 大部分失败 → 中止
    """
    orch = Orchestrator()
    orch.register_rule(rule_all_success)
    orch.register_rule(rule_has_common_blocker)
    orch.register_rule(rule_partial_failure)
    orch.register_rule(rule_major_failure)
    return orch


# CLI 入口
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python orchestrator.py decide <batch_id>")
        print("  python orchestrator.py process-callback <batch_id> <task_id> <result_json>")
        print("  python orchestrator.py get-decision <decision_id>")
        print("  python orchestrator.py get-dispatch <dispatch_id>")
        print("  python orchestrator.py list-decisions [--batch <batch_id>]")
        print("  python orchestrator.py list-dispatches [--batch <batch_id>]")
        sys.exit(1)
    
    cmd = sys.argv[1]
    orch = create_default_orchestrator()
    
    if cmd == "decide":
        batch_id = sys.argv[2]
        decision = orch.decide(batch_id)
        if decision:
            print(f"Decision: {decision.action}")
            print(f"Reason: {decision.reason}")
            if decision.next_tasks:
                print(f"Next tasks: {len(decision.next_tasks)}")
        else:
            print("No decision made (no rules matched).")
    
    elif cmd == "process-callback":
        batch_id = sys.argv[2]
        task_id = sys.argv[3]
        result_json = sys.argv[4]
        result = json.loads(result_json)
        
        dispatch_id = orch.process_batch_callback(batch_id, task_id, result)
        if dispatch_id:
            print(f"Dispatch triggered: {dispatch_id}")
        else:
            print("No dispatch triggered (batch not complete or no rules matched).")
    
    elif cmd == "get-decision":
        decision_id = sys.argv[2]
        result = orch.get_decision(decision_id)
        if result:
            print(json.dumps(result, indent=2))
        else:
            print(f"Decision {decision_id} not found.")
    
    elif cmd == "get-dispatch":
        dispatch_id = sys.argv[2]
        result = orch.get_dispatch(dispatch_id)
        if result:
            print(json.dumps(result, indent=2))
        else:
            print(f"Dispatch {dispatch_id} not found.")
    
    elif cmd == "list-decisions":
        batch_id = None
        if "--batch" in sys.argv:
            idx = sys.argv.index("--batch")
            if idx + 1 < len(sys.argv):
                batch_id = sys.argv[idx + 1]
        
        decisions = []
        for decision_file in DECISIONS_DIR.glob("dec_*.json"):
            with open(decision_file, "r") as f:
                decision = json.load(f)
            if batch_id is None or decision.get("batch_id") == batch_id:
                decisions.append(decision)
        
        print(f"Decisions ({len(decisions)}):")
        for d in sorted(decisions, key=lambda x: x.get("timestamp", "")):
            print(f"  - {d['decision_id']}: batch={d['batch_id']} "
                  f"action={d['action']} ts={d['timestamp'][:19]}")
    
    elif cmd == "list-dispatches":
        batch_id = None
        if "--batch" in sys.argv:
            idx = sys.argv.index("--batch")
            if idx + 1 < len(sys.argv):
                batch_id = sys.argv[idx + 1]
        
        dispatches = []
        for dispatch_file in DISPATCHES_DIR.glob("disp_*.json"):
            with open(dispatch_file, "r") as f:
                dispatch = json.load(f)
            if batch_id is None or dispatch.get("batch_id") == batch_id:
                dispatches.append(dispatch)
        
        print(f"Dispatches ({len(dispatches)}):")
        for d in sorted(dispatches, key=lambda x: x.get("timestamp", "")):
            print(f"  - {d['dispatch_id']}: batch={d['batch_id']} "
                  f"tasks={len(d.get('next_task_ids', []))} ts={d['timestamp'][:19]}")
    
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
