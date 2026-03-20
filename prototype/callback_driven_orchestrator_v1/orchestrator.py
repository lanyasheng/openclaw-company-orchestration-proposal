#!/usr/bin/env python3
"""
回调驱动编排器 v1 — 根据汇总结果决定下一批派什么。

同步来源：orchestrator @ 64da26e
仅做 proposal repo 内的最小同步与 import 适配。
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

try:
    from .batch_aggregator import (
        analyze_batch_results,
        check_and_summarize_batch,
    )
    from .state_machine import (
        STATE_DIR,
        TaskState,
        _ensure_state_dir,
        _iso_now,
        get_batch_tasks,
        is_batch_complete,
        mark_callback_received,
        mark_next_dispatched,
    )
except ImportError:
    from batch_aggregator import (  # type: ignore
        analyze_batch_results,
        check_and_summarize_batch,
    )
    from state_machine import (  # type: ignore
        STATE_DIR,
        TaskState,
        _ensure_state_dir,
        _iso_now,
        get_batch_tasks,
        is_batch_complete,
        mark_callback_received,
        mark_next_dispatched,
    )


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
    ):
        self.action = action
        self.reason = reason
        self.next_tasks = next_tasks or []
        self.metadata = metadata or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "reason": self.reason,
            "next_tasks": self.next_tasks,
            "metadata": self.metadata,
        }


class Orchestrator:
    """
    回调驱动编排器。

    使用方式：
    1. 注册决策规则
    2. 调用 process_batch_callback() 处理回调
    3. 编排器自动决策，并通过 dispatch callback 暴露下一轮派发接口
    """

    def __init__(self):
        _ensure_dirs()
        self._rules: List[Callable[[str, Dict[str, Any]], Optional[Decision]]] = []
        self._dispatch_callback: Optional[Callable[[Dict[str, Any]], str]] = None

    def register_rule(self, rule: Callable[[str, Dict[str, Any]], Optional[Decision]]):
        """注册决策规则"""
        self._rules.append(rule)

    def set_dispatch_callback(self, callback: Callable[[Dict[str, Any]], str]):
        """设置派发回调函数"""
        self._dispatch_callback = callback

    def decide(self, batch_id: str) -> Optional[Decision]:
        """对批次做出决策"""
        analysis = analyze_batch_results(batch_id)

        for rule in self._rules:
            try:
                decision = rule(batch_id, analysis)
                if decision is not None:
                    decision_id = _generate_decision_id(batch_id)
                    decision_data = {
                        "decision_id": decision_id,
                        "batch_id": batch_id,
                        "timestamp": _iso_now(),
                        **decision.to_dict(),
                    }

                    tmp_file = _decision_file(decision_id).with_suffix(".tmp")
                    with open(tmp_file, "w", encoding="utf-8") as f:
                        json.dump(decision_data, f, indent=2, ensure_ascii=False)
                    tmp_file.replace(_decision_file(decision_id))

                    return decision
            except Exception as exc:
                print(f"Rule failed: {exc}")
                continue

        return None

    def process_batch_callback(
        self,
        batch_id: str,
        task_id: str,
        result: Dict[str, Any],
    ) -> Optional[str]:
        """处理批次回调"""
        mark_callback_received(task_id, result)

        if not is_batch_complete(batch_id):
            return None

        check_and_summarize_batch(batch_id)

        decision = self.decide(batch_id)
        if decision is None:
            return None

        next_task_ids = []
        if decision.next_tasks:
            if self._dispatch_callback is None:
                raise RuntimeError("Dispatch callback not set")

            for task_template in decision.next_tasks:
                new_task_id = self._dispatch_callback(task_template)
                next_task_ids.append(new_task_id)

        tasks = get_batch_tasks(batch_id)
        if tasks:
            representative_task_id = tasks[0]["task_id"]
            mark_next_dispatched(representative_task_id, next_task_ids)

        dispatch_id = _generate_dispatch_id()
        dispatch_data = {
            "dispatch_id": dispatch_id,
            "batch_id": batch_id,
            "timestamp": _iso_now(),
            "next_task_ids": next_task_ids,
            "decision": decision.to_dict(),
        }

        tmp_file = _dispatch_file(dispatch_id).with_suffix(".tmp")
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(dispatch_data, f, indent=2, ensure_ascii=False)
        tmp_file.replace(_dispatch_file(dispatch_id))

        return dispatch_id

    def get_decision(self, decision_id: str) -> Optional[Dict[str, Any]]:
        """获取决策记录"""
        decision_file = _decision_file(decision_id)
        if not decision_file.exists():
            return None

        with open(decision_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def get_dispatch(self, dispatch_id: str) -> Optional[Dict[str, Any]]:
        """获取派发记录"""
        dispatch_file = _dispatch_file(dispatch_id)
        if not dispatch_file.exists():
            return None

        with open(dispatch_file, "r", encoding="utf-8") as f:
            return json.load(f)


def rule_all_success(batch_id: str, analysis: Dict[str, Any]) -> Optional[Decision]:
    """如果全部成功，推进到下一阶段"""
    if analysis.get("success_rate", 0) == 1.0 and analysis.get("is_complete"):
        return Decision(
            action="proceed",
            reason="All tasks succeeded, proceeding to next phase",
            next_tasks=[],
        )
    return None


def rule_partial_failure(batch_id: str, analysis: Dict[str, Any]) -> Optional[Decision]:
    """如果部分失败，重试失败任务"""
    success_rate = analysis.get("success_rate", 0)
    if 0.5 <= success_rate < 1.0 and analysis.get("is_complete"):
        tasks = get_batch_tasks(batch_id)
        retry_tasks = []
        for task in tasks:
            if task.get("state") in (TaskState.FAILED.value, TaskState.TIMEOUT.value):
                retry_tasks.append(
                    {
                        "type": "retry",
                        "original_task_id": task["task_id"],
                        "retry_count": task.get("retry_count", 0) + 1,
                    }
                )

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
            metadata={"common_blockers": analysis.get("common_blockers", [])},
        )
    return None


def rule_has_common_blocker(batch_id: str, analysis: Dict[str, Any]) -> Optional[Decision]:
    """如果有共同 blocker，先修复 blocker"""
    common_blockers = analysis.get("common_blockers", [])
    if common_blockers and analysis.get("is_complete"):
        return Decision(
            action="fix_blocker",
            reason=f"Common blockers detected: {[b['error'] for b in common_blockers]}",
            metadata={"common_blockers": common_blockers},
        )
    return None


def create_default_orchestrator() -> Orchestrator:
    """创建默认编排器实例（注册内置规则）"""
    orch = Orchestrator()
    orch.register_rule(rule_all_success)
    orch.register_rule(rule_has_common_blocker)
    orch.register_rule(rule_partial_failure)
    orch.register_rule(rule_major_failure)
    return orch


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
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print(f"Decision {decision_id} not found.")

    elif cmd == "get-dispatch":
        dispatch_id = sys.argv[2]
        result = orch.get_dispatch(dispatch_id)
        if result:
            print(json.dumps(result, indent=2, ensure_ascii=False))
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
            with open(decision_file, "r", encoding="utf-8") as f:
                decision = json.load(f)
            if batch_id is None or decision.get("batch_id") == batch_id:
                decisions.append(decision)

        print(f"Decisions ({len(decisions)}):")
        for item in sorted(decisions, key=lambda x: x.get("timestamp", "")):
            print(
                f"  - {item['decision_id']}: batch={item['batch_id']} "
                f"action={item['action']} ts={item['timestamp'][:19]}"
            )

    elif cmd == "list-dispatches":
        batch_id = None
        if "--batch" in sys.argv:
            idx = sys.argv.index("--batch")
            if idx + 1 < len(sys.argv):
                batch_id = sys.argv[idx + 1]

        dispatches = []
        for dispatch_file in DISPATCHES_DIR.glob("disp_*.json"):
            with open(dispatch_file, "r", encoding="utf-8") as f:
                dispatch = json.load(f)
            if batch_id is None or dispatch.get("batch_id") == batch_id:
                dispatches.append(dispatch)

        print(f"Dispatches ({len(dispatches)}):")
        for item in sorted(dispatches, key=lambda x: x.get("timestamp", "")):
            print(
                f"  - {item['dispatch_id']}: batch={item['batch_id']} "
                f"tasks={len(item.get('next_task_ids', []))} ts={item['timestamp'][:19]}"
            )

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
