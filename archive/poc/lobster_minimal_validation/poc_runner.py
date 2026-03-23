from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .adapters import FailureBranchAdapterStub, HumanDecisionAdapterStub


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TaskRegistry:
    task_id: str
    owner: str = "zoe"
    runtime: str = "lobster"
    state: str = "queued"
    callback_status: str = "pending"
    evidence: Dict[str, Any] = field(default_factory=dict)
    state_history: List[Dict[str, str]] = field(default_factory=list)

    def transition(self, state: str, runtime: Optional[str] = None, note: Optional[str] = None) -> None:
        self.state = state
        if runtime:
            self.runtime = runtime
        entry = {"state": state, "runtime": self.runtime, "at": now_iso()}
        if note:
            entry["note"] = note
        self.state_history.append(entry)

    def add_evidence(self, key: str, value: Any) -> None:
        self.evidence[key] = value

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "owner": self.owner,
            "runtime": self.runtime,
            "state": self.state,
            "callback_status": self.callback_status,
            "evidence": self.evidence,
            "state_history": self.state_history,
        }


class PocRunner:
    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _persist(self, registry: TaskRegistry, callback: Optional[Dict[str, Any]] = None) -> None:
        (self.output_dir / "registry.json").write_text(
            json.dumps(registry.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if callback is not None:
            (self.output_dir / "callback.json").write_text(
                json.dumps(callback, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

    def _final_callback(self, registry: TaskRegistry, result: str, summary: Dict[str, Any]) -> Dict[str, Any]:
        if registry.callback_status != "pending":
            raise RuntimeError("final callback 已发送，P0 不允许重复发送")
        registry.callback_status = "sent"
        callback = {
            "task_id": registry.task_id,
            "result": result,
            "sent_at": now_iso(),
            "summary": summary,
        }
        self._persist(registry, callback)
        registry.callback_status = "acked"
        self._persist(registry, callback)
        return callback

    def _build_human_gate_request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        task_id = str(payload["task_id"])
        return {
            "transport": str(payload.get("request_transport", "file")),
            "resume_token": str(payload.get("resume_token", f"lobster_resume_{task_id}")),
            "timeout_ms": int(payload.get("timeout_ms", 1_800_000)),
            "prompt": str(payload.get("approval_prompt", f"是否批准 {payload['change']}?")),
            "source_ref": str(payload.get("request_source_ref", f"local://human-gate/request/{task_id}")),
            "driver": "decision-payload-file",
            "native": False,
            "requested_at": now_iso(),
        }

    def run_chain(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        registry = TaskRegistry(task_id=payload["task_id"])
        registry.transition("queued", note="创建任务")
        registry.transition("running", runtime="lobster", note="启动 chain")

        registry.add_evidence("input", payload)
        registry.add_evidence("step_a", {"status": "ok", "topic": payload["topic"]})
        registry.add_evidence(
            "step_b",
            {"status": "ok", "target": payload["target"], "message": f"{payload['topic']} -> {payload['target']}"},
        )
        registry.transition("completed", runtime="lobster", note="chain 完成")
        callback = self._final_callback(
            registry,
            result="completed",
            summary={
                "workflow": "chain-basic",
                "ordered_steps": ["step_a", "step_b", "final_callback"],
                "evidence_keys": ["input", "step_a", "step_b"],
            },
        )
        return {"registry": registry.to_dict(), "callback": callback}

    def run_human_gate(self, payload: Dict[str, Any], decision_payload: Dict[str, Any]) -> Dict[str, Any]:
        registry = TaskRegistry(task_id=payload["task_id"])
        registry.transition("queued", note="创建任务")
        registry.transition("running", runtime="lobster", note="执行 precheck")
        registry.add_evidence("input", payload)
        registry.add_evidence("precheck", {"status": "ok", "change": payload["change"]})

        human_gate_request = self._build_human_gate_request(payload)
        registry.add_evidence("human_gate", {"request": human_gate_request})
        registry.transition("waiting_human", runtime="human", note="等待统一 decision payload")

        adapter_result = HumanDecisionAdapterStub().resolve(
            decision_payload,
            expected_task_id=registry.task_id,
            expected_resume_token=human_gate_request["resume_token"],
        )
        registry.evidence["human_gate"]["decision"] = adapter_result

        verdict = adapter_result["verdict"]
        if verdict == "approve":
            registry.transition("running", runtime="lobster", note="人工批准，使用 decision payload 恢复执行")
            registry.evidence["human_gate"]["resolution"] = {
                "status": "resumed",
                "resume_token": human_gate_request["resume_token"],
                "applied_change": payload["change"],
            }
            registry.transition("completed", runtime="lobster", note="人工闸门通过")
            result = "completed"
        elif verdict == "reject":
            registry.evidence["human_gate"]["resolution"] = {
                "status": "rejected",
                "final_state": "degraded",
                "reason": adapter_result.get("reason", "human_rejected"),
            }
            registry.transition("degraded", runtime="human", note="人工拒绝，按降级结束")
            result = "degraded"
        elif verdict == "timeout":
            registry.evidence["human_gate"]["resolution"] = {
                "status": "timed_out",
                "final_state": "failed",
                "reason": adapter_result.get("reason", "approval_timeout"),
            }
            registry.transition("failed", runtime="human", note="人工闸门超时，按失败结束")
            result = "failed"
        else:
            registry.evidence["human_gate"]["resolution"] = {
                "status": "withdrawn",
                "final_state": "degraded",
                "reason": adapter_result.get("reason", "request_withdrawn"),
            }
            registry.transition("degraded", runtime="human", note="人工闸门撤回，按降级结束")
            result = "degraded"

        callback = self._final_callback(
            registry,
            result=result,
            summary={
                "workflow": "human-gate-basic",
                "verdict": verdict,
                "state": registry.state,
                "runtime": registry.runtime,
                "human_gate_transport": human_gate_request["transport"],
            },
        )
        return {"registry": registry.to_dict(), "callback": callback}

    def run_failure_branch(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        registry = TaskRegistry(task_id=payload["task_id"])
        registry.transition("queued", note="创建任务")
        registry.transition("running", runtime="lobster", note="执行主链")
        registry.add_evidence("input", payload)
        registry.add_evidence("step_a", {"status": "ok"})

        if payload.get("mode") == "force_fail_step_b":
            error = "forced_failure_at_step_b"
            registry.add_evidence("step_b", {"status": "failed", "error": error})
            registry.add_evidence("error", error)
            failure_branch = FailureBranchAdapterStub().branch(error)
            registry.add_evidence("failure_branch", failure_branch)
            registry.add_evidence(
                "fallback_step",
                {"status": "ok", "action": "notify-human", "target": payload.get("target", "unknown")},
            )
            registry.transition("degraded", runtime="lobster", note="failure branch 收敛")
            result = "degraded"
        else:
            registry.add_evidence("step_b", {"status": "ok"})
            registry.transition("completed", runtime="lobster", note="主链完成")
            result = "completed"

        callback = self._final_callback(
            registry,
            result=result,
            summary={
                "workflow": "failure-branch-basic",
                "final_state": registry.state,
                "error": registry.evidence.get("error"),
            },
        )
        return {"registry": registry.to_dict(), "callback": callback}
