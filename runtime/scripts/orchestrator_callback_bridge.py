#!/usr/bin/env python3
"""Workspace-side bridge for structured orchestrator callback processing."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
ORCHESTRATOR_DIR = REPO_ROOT / "orchestrator"
if str(ORCHESTRATOR_DIR) not in sys.path:
    sys.path.insert(0, str(ORCHESTRATOR_DIR))

from channel_roundtable import process_channel_roundtable_callback  # type: ignore
from completion_ack_guard import ensure_callback_ack_result  # type: ignore
from contracts import (  # type: ignore
    TASK_TIER_ORCHESTRATED,
    normalize_callback_payload,
    resolve_orchestration_contract,
)
from trading_roundtable import process_trading_roundtable_callback  # type: ignore


AdapterHandler = Callable[..., Dict[str, Any]]


def _load_json(path_str: str) -> Dict[str, Any]:
    path = Path(path_str).expanduser().resolve()
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"payload must be a JSON object: {path}")
    return data


def _parse_allow_auto_dispatch(raw: Optional[str]) -> Optional[bool]:
    if raw is None:
        return None
    value = raw.strip().lower()
    if not value or value == "auto":
        return None
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"unsupported --allow-auto-dispatch value: {raw}")


def _adapter_registry() -> Dict[str, AdapterHandler]:
    return {
        "trading_roundtable": process_trading_roundtable_callback,
        "channel_roundtable": process_channel_roundtable_callback,
    }


def _resolve_invocation(args: argparse.Namespace, payload: Dict[str, Any]) -> Dict[str, Any]:
    adapter_arg = str(args.adapter or "auto").strip().lower()
    explicit_adapter = None if adapter_arg in {"", "auto"} else adapter_arg
    resolved_contract = resolve_orchestration_contract(
        payload,
        default_adapter=explicit_adapter,
        batch_key=args.batch_id,
        default_backend=args.backend,
    )

    adapter = explicit_adapter or resolved_contract.get("adapter")
    if explicit_adapter is None and resolved_contract.get("task_tier") != TASK_TIER_ORCHESTRATED:
        raise ValueError(
            "payload is not orchestrated: "
            f"task_tier={resolved_contract.get('task_tier')} "
            "(auto mode only accepts enabled orchestration contracts)"
        )
    if adapter is None:
        raise ValueError("unable to resolve adapter from payload contract; pass --adapter explicitly")

    batch_id = args.batch_id or resolved_contract.get("batch_key")
    if not batch_id:
        raise ValueError("missing batch id: pass --batch-id or set orchestration.batch_key")

    backend = resolved_contract.get("backend_preference") or args.backend or "subagent"
    return {
        "adapter": adapter,
        "batch_id": batch_id,
        "backend": backend,
        "orchestration_contract": resolved_contract,
    }


def _handle_complete(args: argparse.Namespace) -> Dict[str, Any]:
    raw_payload = _load_json(args.payload)
    payload = normalize_callback_payload(raw_payload)
    allow_auto_dispatch = _parse_allow_auto_dispatch(args.allow_auto_dispatch)
    registry = _adapter_registry()
    invocation = _resolve_invocation(args, payload)

    if allow_auto_dispatch is None:
        contract_auto_execute = invocation["orchestration_contract"].get("auto_execute")
        if invocation["adapter"] == "channel_roundtable" and contract_auto_execute is True:
            # Keep channel/generic onboarding on the existing safe path: auto_execute=true
            # should still respect the adapter's whitelist/default-deny policy unless the
            # caller explicitly forces --allow-auto-dispatch true.
            allow_auto_dispatch = None
        else:
            allow_auto_dispatch = contract_auto_execute

    requester_session_key = (
        args.requester_session_key
        or invocation["orchestration_contract"].get("session", {}).get("requester_session_key")
    )

    handler = registry.get(invocation["adapter"])
    if handler is None:
        raise ValueError(f"unsupported adapter: {invocation['adapter']}")

    result = handler(
        batch_id=invocation["batch_id"],
        task_id=args.task_id,
        result=payload,
        allow_auto_dispatch=allow_auto_dispatch,
        runtime=args.runtime,
        backend=invocation["backend"],
        requester_session_key=requester_session_key,
    )
    
    # ========== P0-3 Batch 9: Auto-Execute Integration ==========
    # 从 dispatch_plan 触发真实执行，打通 execution → receipt → request → consumed 主链
    dispatch_plan = result.get("dispatch_plan") if isinstance(result.get("dispatch_plan"), dict) else {}
    
    if dispatch_plan.get("status") == "triggered":
        # 提取 execution_handoff（如果存在）
        handoff_schema = result.get("handoff_schema") if isinstance(result.get("handoff_schema"), dict) else {}
        execution_handoff = handoff_schema.get("execution_handoff") if isinstance(handoff_schema.get("execution_handoff"), dict) else None
        
        if execution_handoff:
            try:
                # 从 execution_handoff 直接创建 completion_receipt
                # 使用 dispatch_id 作为 execution_id（简化方案）
                from completion_receipt import CompletionReceiptKernel, CompletionReceiptArtifact  # type: ignore
                from spawn_execution import SpawnExecutionArtifact  # type: ignore
                
                execution_id = f"exec_{execution_handoff.get('dispatch_id', 'unknown')[-12:]}"
                
                # 创建 completion receipt（会自动触发 emit_request → auto_trigger_consumption）
                receipt_kernel = CompletionReceiptKernel()
                
                # 构建简化的 execution artifact（用于创建 receipt）
                exec_artifact = SpawnExecutionArtifact(
                    execution_id=execution_id,
                    source_spawn_closure_id=None,  # 没有 spawn_closure
                    source_dispatch_id=execution_handoff.get('dispatch_id', ''),
                    source_spawn_id=None,
                    source_registration_id=None,
                    source_task_id=None,
                    spawn_execution_status="started",
                    spawn_execution_reason="Auto-triggered from execution_handoff",
                    spawn_execution_time=execution_handoff.get('metadata', {}).get('created_at'),
                    spawn_execution_target={
                        "runtime": execution_handoff.get('runtime', 'subagent'),
                        "task": execution_handoff.get('task', ''),
                        "workdir": execution_handoff.get('workdir'),
                    },
                    metadata={
                        "created_from": "execution_handoff",
                        "handoff_id": execution_handoff.get('handoff_id', ''),
                        "auto_execute_integration": True,
                    },
                )
                
                # 创建 receipt（会自动触发 emit_request → auto_trigger_consumption）
                receipt = receipt_kernel.emit_receipt(exec_artifact)
                
                result["auto_execute_intent"] = {
                    "status": "completed",
                    "execution_id": execution_id,
                    "completion_receipt_id": receipt.receipt_id,
                    "message": "completion_receipt created; auto-trigger chain activated",
                }
                    
            except Exception as e:
                # 执行失败不阻塞主流程，仅记录
                result["auto_execute_intent"] = {
                    "status": "failed",
                    "error": str(e),
                    "message": "Auto-execute failed; falling back to ack-only mode",
                }
    # ========== End P0-3 Batch 9 ==========
    
    result = ensure_callback_ack_result(
        result,
        adapter_name=invocation["adapter"],
        batch_id=invocation["batch_id"],
        scenario=invocation["orchestration_contract"].get("scenario") or invocation["adapter"],
        requester_session_key=requester_session_key,
    )
    result["contract_resolution"] = invocation["orchestration_contract"]
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Workspace-side orchestrator callback bridge")
    subparsers = parser.add_subparsers(dest="command", required=True)

    complete = subparsers.add_parser("complete", help="Process one structured callback payload")
    complete.add_argument("--adapter", default="auto", help="Adapter name or auto")
    complete.add_argument("--task-id", required=True)
    complete.add_argument("--batch-id", default=None)
    complete.add_argument("--payload", required=True, help="Structured JSON payload path")
    complete.add_argument("--runtime", default="subagent")
    complete.add_argument("--backend", default=None)
    complete.add_argument("--requester-session-key", default=None)
    complete.add_argument("--allow-auto-dispatch", default="auto")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command != "complete":
        parser.error(f"unsupported command: {args.command}")

    result = _handle_complete(args)
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
