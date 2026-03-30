#!/usr/bin/env python3
"""
Trading Live Validation Script — 真正的 trading live validation

目标：通过 Python API 直接触发完整的 artifact 链，验证从 dispatch → spawn_request → consumed → api_execution 的完整链路。

约束：
- 必须落到 ~/.openclaw/shared-context/ 真路径
- 必须列出真实文件路径与对应 IDs
- 不能拿历史 artifacts 充数
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

# Add orchestrator to path
SCRIPT_DIR = Path(__file__).resolve().parent
ORCHESTRATOR_DIR = SCRIPT_DIR.parent / "orchestrator"
sys.path.insert(0, str(ORCHESTRATOR_DIR))

from completion_receipt import CompletionReceiptKernel
from sessions_spawn_request import prepare_spawn_request, auto_trigger_consumption, configure_auto_trigger
from sessions_spawn_bridge import get_api_execution_by_request
from spawn_execution import SpawnExecutionArtifact

SHARED_CONTEXT = Path.home() / ".openclaw" / "shared-context"


def _iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _ensure_dirs():
    """确保所有 artifact 目录存在"""
    dirs = [
        SHARED_CONTEXT / "dispatches",
        SHARED_CONTEXT / "spawn_requests",
        SHARED_CONTEXT / "bridge_consumed",
        SHARED_CONTEXT / "api_executions",
        SHARED_CONTEXT / "completion_receipts",
        SHARED_CONTEXT / "spawn_executions",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)


def run_live_validation():
    """运行完整的 trading live validation 链路。"""
    _ensure_dirs()
    
    print("=" * 70)
    print("Trading Live Validation — 真正的 shared-context artifact 链验证")
    print("=" * 70)
    print()
    
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    
    # ========== Step 1: 创建 Spawn Execution Artifact ==========
    print("[Step 1] 创建 Spawn Execution Artifact...")
    
    exec_artifact = SpawnExecutionArtifact(
        execution_id=f"live_exec_{timestamp}",
        spawn_id=f"live_spawn_{timestamp}",
        dispatch_id=f"live_dispatch_{timestamp}",
        registration_id=f"live_reg_{timestamp}",
        task_id=f"live_task_{timestamp}",
        spawn_execution_status="started",
        spawn_execution_reason="Live validation test execution",
        spawn_execution_time=_iso_now(),
        spawn_execution_target={
            "runtime": "subagent",
            "task": "Trading live validation test",
            "workdir": str(Path.home() / ".openclaw" / "workspace"),
            "scenario": "trading_roundtable_phase1",
            "owner": "trading",
        },
        dedupe_key=f"live_validation_dedupe_{timestamp}",
        metadata={
            "validation_run": True,
            "validation_timestamp": _iso_now(),
            "truth_anchor": {
                "type": "spawn_execution",
                "source": "live_validation_script",
                "timestamp": _iso_now(),
            },
        },
    )
    
    exec_path = exec_artifact.write()
    print(f"  ✓ Execution ID: {exec_artifact.execution_id}")
    print(f"  ✓ Execution Path: {exec_path}")
    print(f"  ✓ Status: {exec_artifact.spawn_execution_status}")
    print()
    
    # ========== Step 2: 创建 Completion Receipt ==========
    print("[Step 2] 创建 Completion Receipt (从 execution 生成)...")
    
    receipt_kernel = CompletionReceiptKernel()
    receipt = receipt_kernel.emit_receipt(exec_artifact)
    receipt_path = receipt.write()
    
    print(f"  ✓ Receipt ID: {receipt.receipt_id}")
    print(f"  ✓ Receipt Path: {receipt_path}")
    print(f"  ✓ Status: {receipt.receipt_status}")
    print()
    
    # ========== Step 3: 创建 Spawn Request ==========
    print("[Step 3] 创建 Spawn Request (从 receipt 生成)...")
    
    request = prepare_spawn_request(receipt.receipt_id)
    request_path = SHARED_CONTEXT / "spawn_requests" / f"{request.request_id}.json"
    
    print(f"  ✓ Request ID: {request.request_id}")
    print(f"  ✓ Request Path: {request_path}")
    print(f"  ✓ Status: {request.spawn_request_status}")
    print(f"  ✓ Scenario: {request.metadata.get('scenario')}")
    print()
    
    # ========== Step 4: 自动触发 Consumption ==========
    print("[Step 4] 自动触发 Consumption (request → consumed)...")
    
    configure_auto_trigger(
        enabled=True,
        allowlist=["trading_roundtable_phase1"],
        denylist=[],
        require_manual_approval=False,
    )
    
    triggered, reason, consumed_id, execution_id = auto_trigger_consumption(
        request.request_id,
        chain_to_execution=True,
    )
    
    consumed_path = None
    # Extract consumed_id from reason if already consumed
    if not triggered and "already consumed:" in reason:
        consumed_id = reason.split("already consumed:")[1].strip()
    
    if consumed_id:
        consumed_suffix = consumed_id.split('_')[-1] if '_' in consumed_id else consumed_id
        consumed_path = SHARED_CONTEXT / "bridge_consumed" / f"consumed_{consumed_suffix}.json"
    
    if triggered:
        print(f"  ✓ Auto-triggered: True")
        print(f"  ✓ Reason: {reason}")
        print(f"  ✓ Consumed ID: {consumed_id}")
        if consumed_path:
            print(f"  ✓ Consumed Path: {consumed_path}")
    elif "already consumed" in reason:
        print(f"  ✓ Already consumed (dedupe): {consumed_id}")
        if consumed_path:
            print(f"  ✓ Consumed Path: {consumed_path}")
    else:
        print(f"  ✗ Auto-triggered: False")
        print(f"  ✗ Reason: {reason}")
    print()
    
    # ========== Step 5: 检查 API Execution ==========
    print("[Step 5] 检查 API Execution (consumed → api_execution)...")
    
    api_exec = get_api_execution_by_request(request.request_id)
    exec_path_final = None
    
    if api_exec:
        exec_path_final = SHARED_CONTEXT / "api_executions" / f"{api_exec.execution_id}.json"
        print(f"  ✓ Execution ID: {api_exec.execution_id}")
        print(f"  ✓ Execution Path: {exec_path_final}")
        print(f"  ✓ Status: {api_exec.api_execution_status}")
        print(f"  ✓ Reason: {api_exec.api_execution_reason}")
        
        # childSessionKey and runId are direct attributes of api_execution_result
        result = api_exec.api_execution_result
        child_session_key = result.childSessionKey if result else None
        run_id = result.runId if result else None
        
        if child_session_key:
            print(f"  ✓ Child Session Key: {child_session_key}")
        if run_id:
            print(f"  ✓ Run ID: {run_id}")
    else:
        print(f"  ✗ API Execution not found (may be safe mode or blocked)")
    print()
    
    # ========== Step 6: 验证完整链路 ==========
    print("[Step 6] 验证完整链路...")
    
    linkage = {
        "execution_id": exec_artifact.execution_id,
        "receipt_id": receipt.receipt_id,
        "request_id": request.request_id,
        "consumed_id": consumed_id,
        "api_execution_id": api_exec.execution_id if api_exec else None,
    }
    
    artifacts_exist = {
        "execution": exec_path.exists(),
        "receipt": receipt_path.exists(),
        "request": request_path.exists(),
        "consumed": consumed_path.exists() if consumed_path else False,
        "api_execution": exec_path_final.exists() if exec_path_final else False,
    }
    
    print("  Artifact 存在性检查:")
    for name, exists in artifacts_exist.items():
        status = "✓" if exists else "✗"
        print(f"    {status} {name}: {exists}")
    
    complete_chain = all(artifacts_exist.values())
    print()
    print(f"  链路完整性: {'✓ FULL PASS' if complete_chain else '⚠ PARTIAL (stop-at-gate)'}")
    print()
    
    # ========== Step 7: 生成验证报告 ==========
    print("[Step 7] 生成验证报告...")
    
    report = {
        "validation_version": "trading_live_validation_v1",
        "validation_timestamp": _iso_now(),
        "entry_point": "runtime/scripts/trading_live_validation.py",
        "linkage": linkage,
        "artifacts": {
            "execution": {
                "id": exec_artifact.execution_id,
                "path": str(exec_path),
                "exists": artifacts_exist["execution"],
                "status": exec_artifact.spawn_execution_status,
            },
            "receipt": {
                "id": receipt.receipt_id,
                "path": str(receipt_path),
                "exists": artifacts_exist["receipt"],
                "status": receipt.receipt_status,
            },
            "request": {
                "id": request.request_id,
                "path": str(request_path),
                "exists": artifacts_exist["request"],
                "status": request.spawn_request_status,
                "scenario": request.metadata.get("scenario"),
            },
            "consumed": {
                "id": consumed_id,
                "path": str(consumed_path) if consumed_path else None,
                "exists": artifacts_exist["consumed"],
            },
            "api_execution": {
                "id": api_exec.execution_id if api_exec else None,
                "path": str(exec_path_final) if exec_path_final else None,
                "exists": artifacts_exist["api_execution"],
                "status": api_exec.api_execution_status if api_exec else None,
                "reason": api_exec.api_execution_reason if api_exec else None,
                "childSessionKey": api_exec.api_execution_result.childSessionKey if (api_exec and api_exec.api_execution_result) else None,
                "runId": api_exec.api_execution_result.runId if (api_exec and api_exec.api_execution_result) else None,
            },
        },
        "validation_result": {
            "full_pass": complete_chain,
            "stop_at_gate": not complete_chain,
            "linkage_complete": all(v is not None for v in linkage.values()),
            "all_artifacts_exist": all(artifacts_exist.values()),
        },
        "configuration": {
            "auto_trigger_enabled": True,
            "allowlist": ["trading_roundtable_phase1"],
            "require_manual_approval": False,
        },
    }
    
    report_path = Path(__file__).resolve().parent.parent / "docs" / "trading-live-validation-report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    print(f"  ✓ 报告路径：{report_path}")
    print()
    
    # ========== 最终结论 ==========
    print("=" * 70)
    print("验证结论")
    print("=" * 70)
    
    if complete_chain:
        print("✓ FULL PASS: 完整 artifact 链验证通过")
        print(f"  - Execution: {exec_artifact.execution_id}")
        print(f"  - Receipt: {receipt.receipt_id}")
        print(f"  - Request: {request.request_id}")
        print(f"  - Consumed: {consumed_id}")
        print(f"  - API Execution: {api_exec.execution_id if api_exec else 'N/A'}")
    else:
        print("⚠ PARTIAL: 链路不完整 (stop-at-gate)")
        print(f"  - Execution: {exec_artifact.execution_id} ✓")
        print(f"  - Receipt: {receipt.receipt_id} ✓")
        print(f"  - Request: {request.request_id} ✓")
        print(f"  - Consumed: {consumed_id or 'N/A'} {'✓' if consumed_id else '✗'}")
        print(f"  - API Execution: {api_exec.execution_id if api_exec else 'N/A'} {'✓' if api_exec else '✗'}")
    
    print()
    print(f"详细报告：{report_path}")
    print("=" * 70)
    
    return report


if __name__ == "__main__":
    try:
        report = run_live_validation()
        sys.exit(0 if report["validation_result"]["full_pass"] else 1)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
