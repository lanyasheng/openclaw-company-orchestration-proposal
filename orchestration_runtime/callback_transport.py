from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .task_registry import write_json_atomic


@dataclass
class CallbackTransportResult:
    callback_status: str
    history: List[Dict[str, Any]] = field(default_factory=list)
    delivery: Optional[Dict[str, Any]] = None
    receipt: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None


class FileCallbackTransport:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir
        self.outbox_dir = self.root_dir / "callback-outbox"
        self.receipts_dir = self.root_dir / "callback-receipts"
        self.errors_dir = self.root_dir / "callback-errors"
        self.outbox_dir.mkdir(parents=True, exist_ok=True)
        self.receipts_dir.mkdir(parents=True, exist_ok=True)
        self.errors_dir.mkdir(parents=True, exist_ok=True)

    def send(
        self,
        *,
        task_id: str,
        payload: Dict[str, Any],
        step_config: Dict[str, Any],
        workflow_state: str,
    ) -> CallbackTransportResult:
        transport_config = step_config.get("transport")
        if not isinstance(transport_config, dict):
            transport_config = {}

        channel = str(transport_config.get("channel", "repo-local"))
        target = str(transport_config.get("target", "lobster/final-callback"))
        delivery_id = str(transport_config.get("delivery_id") or f"cb-{uuid.uuid4().hex[:12]}")
        occurred_at = transport_config.get("occurred_at") or transport_config.get("sent_at")
        history: List[Dict[str, Any]] = []

        if transport_config.get("simulate") == "failed" or transport_config.get("result") == "failed":
            error = {
                "code": str(transport_config.get("error_code", "callback_delivery_failed")),
                "message": str(transport_config.get("error_message", "callback delivery failed")),
            }
            error_envelope = {
                "task_id": task_id,
                "stage": "final_callback_failed",
                "state": workflow_state,
                "occurred_at": occurred_at,
                "target": target,
                "payload": payload,
                "error": error,
            }
            write_json_atomic(self.errors_dir / f"{task_id}.failed.json", error_envelope)
            history.append(
                {
                    "stage": "final_callback_failed",
                    "callback_status": "failed",
                    "occurred_at": occurred_at,
                    "summary": "callback delivery failed",
                    "error": error,
                    "raw_event_ref": str((self.errors_dir / f"{task_id}.failed.json").relative_to(self.root_dir)),
                }
            )
            return CallbackTransportResult(callback_status="failed", history=history, error=error)

        delivery = {
            "channel": channel,
            "target": target,
            "delivery_id": delivery_id,
        }
        sent_envelope = {
            "task_id": task_id,
            "stage": "final_callback_sent",
            "state": workflow_state,
            "occurred_at": occurred_at,
            "delivery": delivery,
            "payload": payload,
        }
        sent_path = self.outbox_dir / f"{task_id}.sent.json"
        write_json_atomic(sent_path, sent_envelope)
        history.append(
            {
                "stage": "final_callback_sent",
                "callback_status": "sent",
                "occurred_at": occurred_at,
                "summary": "final callback delivered to repo-local receiver",
                "delivery": delivery,
                "raw_event_ref": str(sent_path.relative_to(self.root_dir)),
            }
        )

        auto_ack = transport_config.get("auto_ack", True)
        if not auto_ack:
            return CallbackTransportResult(callback_status="sent", history=history, delivery=delivery)

        ack_id = str(transport_config.get("ack_id") or f"ack-{uuid.uuid4().hex[:12]}")
        acked_at = transport_config.get("acked_at") or transport_config.get("receipt_at") or occurred_at
        receipt = {
            "ack_id": ack_id,
            "received_at": acked_at,
        }
        receipt_envelope = {
            "task_id": task_id,
            "stage": "callback_receipt_acked",
            "state": workflow_state,
            "occurred_at": acked_at,
            "delivery": delivery,
            "receipt": receipt,
            "payload": payload,
        }
        receipt_path = self.receipts_dir / f"{task_id}.acked.json"
        write_json_atomic(receipt_path, receipt_envelope)
        history.append(
            {
                "stage": "callback_receipt_acked",
                "callback_status": "acked",
                "occurred_at": acked_at,
                "summary": "repo-local receiver acknowledged callback receipt",
                "receipt": receipt,
                "raw_event_ref": str(receipt_path.relative_to(self.root_dir)),
            }
        )
        return CallbackTransportResult(
            callback_status="acked",
            history=history,
            delivery=delivery,
            receipt=receipt,
        )
