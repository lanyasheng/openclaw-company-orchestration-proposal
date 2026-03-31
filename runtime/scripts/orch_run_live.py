#!/usr/bin/env python3
"""
orch_run_live.py — Orch run with LIVE artifact chain

目标：让 `orch run` 直接进入完整的 shared-context artifact 链，而不是绕过它。

完整链路：
1. SpawnExecutionArtifact (execution intent)
2. CompletionReceipt (receipt closure)
3. SessionsSpawnRequest (spawn request)
4. BridgeConsumed (consumption record)
5. APIExecution (real sessions_spawn API call)

使用示例：
```bash
# Trading live chain
python3 runtime/scripts/orch_run_live.py \\
  --scenario trading_roundtable \\
  --task "测试任务" \\
  --workdir /path/to/workdir

# JSON output
python3 runtime/scripts/orch_run_live.py --scenario trading --task "..." --workdir ... --output json
```

验收标准：
- 入口明确是 `orch_run_live.py` 或 `orch run --live-chain`
- 产出真实 shared-context artifacts：
  - ~/.openclaw/shared-context/spawn_executions/*
  - ~/.openclaw/shared-context/completion_receipts/*
  - ~/.openclaw/shared-context/spawn_requests/*
  - ~/.openclaw/shared-context/bridge_consumed/*
  - ~/.openclaw/shared-context/api_executions/*
- 不再出现 `simulate` 字样（或明确标记为 partial）
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

# Add orchestrator to path
SCRIPT_DIR = Path(__file__).resolve().parent
ORCHESTRATOR_DIR = SCRIPT_DIR.parent / "orchestrator"
sys.path.insert(0, str(ORCHESTRATOR_DIR))

from spawn_execution import SpawnExecutionArtifact, SpawnExecutionKernel, SpawnExecutionPolicy
from completion_receipt import CompletionReceiptKernel
from sessions_spawn_request import prepare_spawn_request, auto_trigger_consumption, configure_auto_trigger
from sessions_spawn_bridge import (
    get_api_execution_by_request,
    SessionsSpawnBridgePolicy,
    configure_auto_trigger_real_exec,
    auto_trigger_real_execution,
)
from bridge_consumer import get_consumed_by_request

SHARED_CONTEXT = Path.home() / ".openclaw" / "shared-context"
LIVE_VERSION = "orch_run_live_v1"


def _iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _ensure_dirs():
    """确保所有 artifact 目录存在"""
    dirs = [
        SHARED_CONTEXT / "spawn_executions",
        SHARED_CONTEXT / "completion_receipts",
        SHARED_CONTEXT / "spawn_requests",
        SHARED_CONTEXT / "bridge_consumed",
        SHARED_CONTEXT / "api_executions",
        SHARED_CONTEXT / "dispatches",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)


def run_live_chain(
    task_description: str,
    workdir: str,
    scenario: str = "trading_roundtable",
    owner: str = "trading",
    runtime: str = "subagent",
    timeout_seconds: int = 900,
) -> Dict[str, Any]:
    """
    运行完整的 live artifact chain。
    
    Returns:
        包含所有 artifact IDs 和路径的结果字典
    """
    _ensure_dirs()
    
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    
    # ========== Step 1: Spawn Execution ==========
    print("[Step 1] 创建 Spawn Execution Artifact...")
    
    dispatch_id = f"live_dispatch_{timestamp}"
    spawn_id = f"live_spawn_{timestamp}"
    registration_id = f"live_reg_{timestamp}"
    task_id = f"live_task_{timestamp}"
    execution_id = f"live_exec_{timestamp}"
    
    exec_artifact = SpawnExecutionArtifact(
        execution_id=execution_id,
        spawn_id=spawn_id,
        dispatch_id=dispatch_id,
        registration_id=registration_id,
        task_id=task_id,
        spawn_execution_status="started",
        spawn_execution_reason="Live chain execution via orch_run_live.py",
        spawn_execution_time=_iso_now(),
        spawn_execution_target={
            "runtime": runtime,
            "task": task_description,
            "workdir": workdir,
            "scenario": scenario,
            "owner": owner,
        },
        dedupe_key=f"live_orch_run_dedupe_{timestamp}",
        metadata={
            "entry_point": "orch_run_live.py",
            "live_chain": True,
            "timestamp": _iso_now(),
        },
    )
    
    exec_path = exec_artifact.write()
    print(f"  ✓ Execution ID: {execution_id}")
    print(f"  ✓ Path: {exec_path}")
    
    # ========== Step 2: Completion Receipt ==========
    print("[Step 2] 创建 Completion Receipt...")
    
    receipt_kernel = CompletionReceiptKernel()
    receipt = receipt_kernel.emit_receipt(exec_artifact)
    receipt_path = receipt.write()
    
    print(f"  ✓ Receipt ID: {receipt.receipt_id}")
    print(f"  ✓ Path: {receipt_path}")
    
    # ========== Step 3: Sessions Spawn Request ==========
    print("[Step 3] 创建 Sessions Spawn Request...")
    
    request = prepare_spawn_request(receipt.receipt_id)
    request_path = SHARED_CONTEXT / "spawn_requests" / f"{request.request_id}.json"
    
    print(f"  ✓ Request ID: {request.request_id}")
    print(f"  ✓ Path: {request_path}")
    print(f"  ✓ Status: {request.spawn_request_status}")
    
    # ========== Step 4: Auto-trigger Consumption ==========
    print("[Step 4] 自动触发 Consumption...")
    
    # 配置 auto-trigger consumption（允许 trading 场景）
    configure_auto_trigger(
        enabled=True,
        allowlist=[scenario, "trading_roundtable", "trading"],
        denylist=[],
        require_manual_approval=False,
    )
    
    # 配置 auto-trigger real execution（关闭 safe_mode 以真实执行）
    configure_auto_trigger_real_exec(
        enabled=True,
        allowlist=[scenario, "trading_roundtable", "trading"],
        denylist=[],
        require_manual_approval=False,
        safe_mode=False,  # 真实执行，不是模拟
    )
    
    # 触发 consumption（包括 chain_to_execution）
    triggered, reason, consumed_id, execution_id_from_consumption = auto_trigger_consumption(
        request.request_id,
        chain_to_execution=True,
    )
    
    # 获取 consumed artifact
    consumed_artifact = get_consumed_by_request(request.request_id)
    consumed_path = None
    if consumed_artifact:
        consumed_suffix = consumed_artifact.consumed_id.split('_')[-1] if '_' in consumed_artifact.consumed_id else consumed_artifact.consumed_id
        consumed_path = SHARED_CONTEXT / "bridge_consumed" / f"consumed_{consumed_suffix}.json"
    
    if triggered:
        print(f"  ✓ Auto-triggered: True")
        print(f"  ✓ Consumed ID: {consumed_id}")
    elif "already consumed" in reason:
        print(f"  ✓ Already consumed: {consumed_id}")
    else:
        print(f"  ⚠ Auto-trigger: {reason}")
    
    if consumed_path:
        print(f"  ✓ Consumed Path: {consumed_path}")
    
    # ========== Step 5: Check/Trigger API Execution ==========
    print("[Step 5] 检查/触发 API Execution...")
    
    # 先检查是否已存在 API execution
    api_exec = get_api_execution_by_request(request.request_id)
    
    # 如果没有，显式触发
    if not api_exec:
        print("  → API execution not found, triggering now...")
        exec_triggered, exec_reason, exec_id = auto_trigger_real_execution(
            request.request_id,
            policy=SessionsSpawnBridgePolicy(
                safe_mode=False,  # 真实执行
                allowlist=[scenario, "trading_roundtable", "trading"],
            ),
        )
        if exec_triggered and exec_id:
            print(f"  ✓ Execution triggered: {exec_id}")
            api_exec = get_api_execution_by_request(request.request_id)
        else:
            print(f"  ⚠ Execution trigger: {exec_reason}")
    
    api_exec_path = None
    child_session_key = None
    run_id = None
    
    if api_exec:
        api_exec_path = SHARED_CONTEXT / "api_executions" / f"{api_exec.execution_id}.json"
        print(f"  ✓ Execution ID: {api_exec.execution_id}")
        print(f"  ✓ Path: {api_exec_path}")
        print(f"  ✓ Status: {api_exec.api_execution_status}")
        print(f"  ✓ Reason: {api_exec.api_execution_reason}")
        
        # Extract childSessionKey and runId
        if api_exec.api_execution_result:
            child_session_key = api_exec.api_execution_result.childSessionKey
            run_id = api_exec.api_execution_result.runId
            if child_session_key:
                print(f"  ✓ Child Session Key: {child_session_key}")
            if run_id:
                print(f"  ✓ Run ID: {run_id}")
    else:
        print(f"  ⚠ API Execution not found after trigger")
    
    # ========== Step 6: Build Result ==========
    print("[Step 6] 构建结果...")
    
    linkage = {
        "execution_id": execution_id,
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
        "api_execution": api_exec_path.exists() if api_exec_path else False,
    }
    
    complete_chain = all(artifacts_exist.values())
    
    result = {
        "version": LIVE_VERSION,
        "timestamp": _iso_now(),
        "entry_point": "orch_run_live.py",
        "input": {
            "task": task_description,
            "workdir": workdir,
            "scenario": scenario,
            "owner": owner,
            "runtime": runtime,
        },
        "linkage": linkage,
        "artifacts": {
            "execution": {
                "id": execution_id,
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
                "path": str(api_exec_path) if api_exec_path else None,
                "exists": artifacts_exist["api_execution"],
                "status": api_exec.api_execution_status if api_exec else None,
                "reason": api_exec.api_execution_reason if api_exec else None,
                "childSessionKey": child_session_key,
                "runId": run_id,
            },
        },
        "validation": {
            "complete_chain": complete_chain,
            "all_artifacts_exist": all(artifacts_exist.values()),
            "linkage_complete": all(v is not None for v in linkage.values()),
        },
    }
    
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Orch run with LIVE artifact chain",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Trading live chain
  python3 orch_run_live.py --scenario trading_roundtable --task "测试任务" --workdir /path/to/workdir
  
  # JSON output
  python3 orch_run_live.py --scenario trading --task "..." --workdir ... --output json
        """,
    )
    
    parser.add_argument("--task", "-t", required=True, help="任务描述")
    parser.add_argument("--workdir", "-w", required=True, help="工作目录")
    parser.add_argument("--scenario", "-s", default="trading_roundtable", help="场景标识")
    parser.add_argument("--owner", "-o", default="trading", help="负责人")
    parser.add_argument("--runtime", default="subagent", choices=["subagent", "tmux"], help="执行 runtime")
    parser.add_argument("--timeout", type=int, default=900, help="超时时间（秒）")
    parser.add_argument("--output", choices=["text", "json"], default="text", help="输出格式")
    
    args = parser.parse_args()
    
    try:
        result = run_live_chain(
            task_description=args.task,
            workdir=args.workdir,
            scenario=args.scenario,
            owner=args.owner,
            runtime=args.runtime,
            timeout_seconds=args.timeout,
        )
        
        if args.output == "json":
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print()
            print("=" * 70)
            print("Orch Run Live Chain Result")
            print("=" * 70)
            print()
            print(f"Entry Point: {result['entry_point']}")
            print(f"Timestamp: {result['timestamp']}")
            print()
            print("Linkage:")
            for key, value in result['linkage'].items():
                print(f"  {key}: {value}")
            print()
            print("Artifacts:")
            for name, info in result['artifacts'].items():
                status = "✓" if info.get('exists') else "✗"
                print(f"  {status} {name}: {info.get('id', 'N/A')}")
                if info.get('path'):
                    print(f"      {info['path']}")
            print()
            print("Validation:")
            val = result['validation']
            print(f"  Complete Chain: {'✓' if val['complete_chain'] else '✗'}")
            print(f"  All Artifacts Exist: {'✓' if val['all_artifacts_exist'] else '✗'}")
            print(f"  Linkage Complete: {'✓' if val['linkage_complete'] else '✗'}")
            print()
            
            if val['complete_chain']:
                print("✓ FULL PASS: 完整 artifact 链验证通过")
            else:
                print("⚠ PARTIAL: 链路不完整 (stop-at-gate)")
            
            print("=" * 70)
        
        # Return exit code based on validation
        sys.exit(0 if result['validation']['complete_chain'] else 1)
        
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
