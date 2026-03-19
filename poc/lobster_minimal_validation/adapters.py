from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


ALLOWED_HUMAN_VERDICTS = {"approve", "reject", "timeout", "withdraw"}


@dataclass
class HumanDecisionAdapterStub:
    """P0.6 repo-local 适配器：读取统一 decision payload，而不是直接吃 CLI verdict。"""

    def resolve(
        self,
        decision_payload: Dict[str, Any],
        *,
        expected_task_id: str,
        expected_resume_token: str,
    ) -> Dict[str, Any]:
        verdict = str(decision_payload.get("verdict", "")).strip().lower()
        if verdict not in ALLOWED_HUMAN_VERDICTS:
            raise ValueError("verdict 只允许 approve/reject/timeout/withdraw")

        required_fields = ["decision_id", "task_id", "resume_token", "source", "actor", "decided_at"]
        missing_fields = [field for field in required_fields if field not in decision_payload]
        if missing_fields:
            raise ValueError(f"decision payload 缺少必填字段: {', '.join(missing_fields)}")

        task_id = str(decision_payload["task_id"])
        if task_id != expected_task_id:
            raise ValueError(f"decision payload task_id 不匹配: {task_id} != {expected_task_id}")

        resume_token = str(decision_payload["resume_token"])
        if resume_token != expected_resume_token:
            raise ValueError("decision payload resume_token 不匹配当前 waiting_human 请求")

        source = decision_payload["source"]
        if not isinstance(source, dict) or not source.get("transport") or not source.get("ref"):
            raise ValueError("decision payload.source 必须包含 transport/ref")

        actor = decision_payload["actor"]
        if not isinstance(actor, dict) or not actor.get("id"):
            raise ValueError("decision payload.actor 必须包含 id")

        normalized: Dict[str, Any] = {
            "adapter": "human-decision-payload-file",
            "native": False,
            "decision_id": str(decision_payload["decision_id"]),
            "task_id": task_id,
            "resume_token": resume_token,
            "verdict": verdict,
            "source": {
                "transport": str(source["transport"]),
                "ref": str(source["ref"]),
            },
            "actor": {
                "id": str(actor["id"]),
            },
            "decided_at": str(decision_payload["decided_at"]),
            "note": "P0.6 在 repo-local 用 decision payload 文件模拟统一人工决定输入；未来 message/browser 只需产出同结构 payload。",
        }

        if actor.get("name"):
            normalized["actor"]["name"] = str(actor["name"])
        if decision_payload.get("reason"):
            normalized["reason"] = str(decision_payload["reason"])

        return normalized


@dataclass
class FailureBranchAdapterStub:
    """P0 占位：Lobster 现阶段缺少原生 failure branch，这里显式走 adapter stub。"""

    def branch(self, error: str) -> Dict[str, Any]:
        return {
            "adapter": "failure-branch-stub",
            "native": False,
            "error": error,
            "fallback_action": "notify-human-and-degrade",
            "note": "P0 通过 adapter stub 显式转入 fallback；真实实现需补 Lobster DSL 扩展或包装命令。",
        }
