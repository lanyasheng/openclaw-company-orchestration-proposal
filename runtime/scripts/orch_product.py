#!/usr/bin/env python3
"""
orch_product.py — OpenClaw Orchestration 产品化三件套入口

提供面向频道/agent 的统一接入体验：
- onboard: 给频道生成/解释接入方案（adapter/scenario/owner/backend/gate）
- run: 触发一次当前频道/指定频道的执行（尽量隐藏内部 contract 细节）
- status: 查看当前频道/批次/任务的状态总览

使用示例：
```bash
# 1. onboard — 查看频道接入建议
python3 runtime/scripts/orch_product.py onboard

# 2. run — 触发执行
python3 runtime/scripts/orch_product.py run --task "任务描述"

# 3. status — 查看状态
python3 runtime/scripts/orch_product.py status
```

设计原则：
- 复用现有 control plane，不得另起真值链
- 零心智负担：其他 agent 一句话就会用
- 向后兼容：保留现有 orch_command.py 入口
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
LOCAL_RUNTIME_DIR = SCRIPT_DIR / "orchestration_entry_runtime"
REPO_ROOT = SCRIPT_DIR.parent
ORCHESTRATOR_DIR = REPO_ROOT / "orchestrator"

if LOCAL_RUNTIME_DIR.exists():
    sys.path.insert(0, str(LOCAL_RUNTIME_DIR))
elif str(ORCHESTRATOR_DIR) not in sys.path:
    sys.path.insert(0, str(ORCHESTRATOR_DIR))

from entry_defaults import build_default_entry_contract  # type: ignore
from unified_execution_runtime import UnifiedExecutionRuntime, TaskContext, ExecutionResult  # type: ignore
from observability_card import list_cards, generate_board_snapshot, ObservabilityCardManager  # type: ignore


__all__ = ["onboard", "run", "status", "main"]

VERSION = "orch_product_v1"
TRADING_DEFAULT_AUTO_MODE = "default_auto_continue_except_high_risk_gates"
TRADING_RETAINED_GATES = [
    "live_trading",
    "funds_movement",
    "irreversible_external_side_effects",
    "push_merge",
    "production_alert",
    "gate_review",
    "packet_freeze",
]


def _iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _env(name: str) -> Optional[str]:
    import os
    value = os.environ.get(name)
    if value is None:
        return None
    text = value.strip()
    return text or None


def _env_first(*names: str) -> Optional[str]:
    for name in names:
        value = _env(name)
        if value is not None:
            return value
    return None


def _merge_allowlist(existing: Optional[List[str]], required: List[str]) -> List[str]:
    merged: List[str] = []
    seen = set()
    for item in [*(existing or []), *required]:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        merged.append(text)
    return merged


def _is_trading_orchestration(orch: Dict[str, Any]) -> bool:
    adapter = str(orch.get("adapter") or "").strip().lower()
    scenario = str(orch.get("scenario") or "").strip().lower()
    owner = str(orch.get("owner") or "").strip().lower()
    return adapter == "trading_roundtable" or scenario == "trading_roundtable_phase1" or owner == "trading"


def _get_trading_default_auto_profile(
    *,
    scenario: Optional[str] = None,
    apply: bool = False,
) -> Dict[str, Any]:
    from sessions_spawn_request import (  # type: ignore
        SPAWN_REQUEST_DIR,
        AUTO_TRIGGER_CONFIG_FILE,
        configure_auto_trigger,
        get_auto_trigger_status,
    )
    from sessions_spawn_bridge import (  # type: ignore
        AUTO_TRIGGER_REAL_EXEC_CONFIG_FILE,
        configure_auto_trigger_real_exec,
        get_auto_trigger_real_exec_status,
    )

    resolved_scenario = scenario or "trading_roundtable_phase1"

    auto_status_before = get_auto_trigger_status()
    real_exec_status_before = get_auto_trigger_real_exec_status()

    if apply:
        configure_auto_trigger(
            enabled=True,
            allowlist=_merge_allowlist(
                auto_status_before.get("config", {}).get("allowlist"),
                [resolved_scenario],
            ),
            denylist=auto_status_before.get("config", {}).get("denylist"),
            require_manual_approval=False,
        )
        configure_auto_trigger_real_exec(
            enabled=True,
            allowlist=_merge_allowlist(
                real_exec_status_before.get("config", {}).get("allowlist"),
                [resolved_scenario],
            ),
            denylist=real_exec_status_before.get("config", {}).get("denylist"),
            require_manual_approval=False,
            safe_mode=False,
        )

    auto_status = get_auto_trigger_status()
    real_exec_status = get_auto_trigger_real_exec_status()
    auto_cfg = auto_status.get("config", {})
    real_exec_cfg = real_exec_status.get("config", {})

    cutover_applied = (
        bool(auto_cfg.get("enabled"))
        and not bool(auto_cfg.get("require_manual_approval", True))
        and resolved_scenario in (auto_cfg.get("allowlist") or [])
        and bool(real_exec_cfg.get("enabled"))
        and not bool(real_exec_cfg.get("require_manual_approval", True))
        and not bool(real_exec_cfg.get("safe_mode", True))
        and resolved_scenario in (real_exec_cfg.get("allowlist") or [])
    )

    return {
        "mode": TRADING_DEFAULT_AUTO_MODE,
        "cutover_applied": cutover_applied,
        "managed_by": "orch_product_trading_default_auto_profile_v1",
        "adapter": "trading_roundtable",
        "scenario": resolved_scenario,
        "default_auto_scope": [
            "auto_register",
            "auto_dispatch",
            "auto_callback",
            "auto_continue_until_gate",
        ],
        "retained_gates": TRADING_RETAINED_GATES,
        "config_paths": {
            "spawn_request_dir": str(SPAWN_REQUEST_DIR),
            "auto_trigger": str(AUTO_TRIGGER_CONFIG_FILE),
            "real_execution": str(AUTO_TRIGGER_REAL_EXEC_CONFIG_FILE),
        },
        "config_state": {
            "auto_trigger": auto_cfg,
            "real_execution": real_exec_cfg,
        },
    }


# ============ Onboard Command ============


def onboard(
    channel_id: Optional[str] = None,
    channel_name: Optional[str] = None,
    topic: Optional[str] = None,
    context: Optional[str] = None,
    scenario: Optional[str] = None,
    owner: Optional[str] = None,
    backend: Optional[str] = None,
) -> Dict[str, Any]:
    """
    生成频道接入建议卡。
    
    复用 entry_defaults.build_default_entry_contract() 的 contract 推导能力，
    对外提供简化的 onboard 输出。
    
    Args:
        channel_id: 频道 ID
        channel_name: 频道名称
        topic: 讨论主题
        context: 上下文 (channel_roundtable | trading_roundtable)
        scenario: 场景标识
        owner: 任务负责人
        backend: 执行后端偏好
    
    Returns:
        频道接入建议卡（含 adapter/scenario/owner/backend/gate 推荐）
    """
    # 调用现有 contract 推导能力
    contract = build_default_entry_contract(
        context=context,
        scenario=scenario,
        channel_id=channel_id,
        channel_name=channel_name,
        topic=topic,
        owner=owner,
        backend=backend,
        command_name="orch_product_onboard",
    )
    
    # 提取推荐配置
    orch = contract.get("orchestration", {})
    onboarding = contract.get("onboarding", {})
    seed_payload = contract.get("seed_payload", {})
    channel_mode = None
    if _is_trading_orchestration(orch):
        channel_mode = _get_trading_default_auto_profile(
            scenario=orch.get("scenario"),
            apply=True,
        )
    
    # 构建简化的 onboard 输出
    result = {
        "version": VERSION,
        "generated_at": _iso_now(),
        "channel": {
            "channel_id": orch.get("channel", {}).get("channel_id") or orch.get("channel", {}).get("id"),
            "channel_name": orch.get("channel", {}).get("channel_name") or orch.get("channel", {}).get("name"),
            "topic": orch.get("channel", {}).get("topic"),
        },
        "recommendation": {
            "adapter": orch.get("adapter"),
            "scenario": orch.get("scenario"),
            "owner": orch.get("owner"),
            "backend": orch.get("backend_preference"),
            "gate_policy": orch.get("gate_policy", {}).get("mode"),
            "auto_execute": orch.get("auto_execute"),
        },
        "bootstrap_capability_card": onboarding.get("bootstrap_capability_card", {}),
        "operator_kit": onboarding.get("operator_kit", {}),
        "payload_aliases": onboarding.get("payload_aliases", []),
        "channel_mode": channel_mode,
        "next_steps": _generate_onboard_next_steps(orch, channel_mode=channel_mode),
        "example_commands": _generate_example_commands(
            channel_id=orch.get("channel", {}).get("channel_id"),
            scenario=orch.get("scenario"),
            owner=orch.get("owner"),
        ),
        "full_contract": contract,  # 保留完整 contract 供参考
    }
    
    return result


def _generate_onboard_next_steps(
    orch: Dict[str, Any],
    *,
    channel_mode: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """生成下一步行动建议。"""
    steps = []
    
    adapter = orch.get("adapter", "unknown")
    auto_execute = orch.get("auto_execute", True)
    
    steps.append("1. 确认推荐配置（adapter/scenario/owner/backend）")
    
    if channel_mode and channel_mode.get("cutover_applied"):
        steps.append("2. Trading 默认自动推进配置已落地；低风险 continuation 将自动注册/派发/回流/续推")
    elif not auto_execute:
        steps.append("2. 首次接入建议先设置 --auto-execute false 验证稳定")
    else:
        steps.append("2. 当前入口默认开启 auto_execute=true")
    
    steps.append("3. 运行 'orch_product.py run --task \"任务描述\"' 触发执行")
    steps.append("4. 运行 'orch_product.py status' 查看状态")
    
    if adapter == "trading_roundtable":
        steps.append("5. Trading 场景：分析/规划/编码/文档类任务默认自动推进；真实资金/不可逆动作仍保留 gate")
    elif adapter == "channel_roundtable":
        steps.append("5. Channel 场景：关注 roundtable 五字段（conclusion/blocker/owner/next_step/completion_criteria）")
    
    return steps


def _generate_example_commands(
    channel_id: Optional[str],
    scenario: Optional[str],
    owner: Optional[str],
) -> Dict[str, str]:
    """生成示例命令。"""
    channel_arg = f'--channel-id "{channel_id}"' if channel_id else ""
    scenario_arg = f'--scenario "{scenario}"' if scenario else ""
    owner_arg = f'--owner "{owner}"' if owner else ""
    
    base_args = " ".join(filter(None, [channel_arg, scenario_arg, owner_arg]))
    
    return {
        "onboard": f"python3 runtime/scripts/orch_product.py onboard {base_args}".strip(),
        "run": f'python3 runtime/scripts/orch_product.py run {base_args} --task "任务描述"'.strip(),
        "status": f"python3 runtime/scripts/orch_product.py status {channel_arg}".strip(),
    }


# ============ Run Command ============


def run(
    task_description: str,
    channel_id: Optional[str] = None,
    channel_name: Optional[str] = None,
    topic: Optional[str] = None,
    context: Optional[str] = None,
    scenario: Optional[str] = None,
    owner: Optional[str] = None,
    backend: Optional[str] = None,
    workdir: Optional[str] = None,
    estimated_duration_minutes: Optional[int] = None,
    task_type: Optional[str] = None,
    requires_monitoring: Optional[bool] = None,
    timeout_seconds: Optional[int] = None,
    output_format: str = "text",
) -> Dict[str, Any]:
    """
    触发一次执行。
    
    复用 unified_execution_runtime.UnifiedExecutionRuntime，
    自动完成 contract 生成 + backend 选择 + 执行 + observability 注册。
    
    Args:
        task_description: 任务描述（必需）
        channel_id: 频道 ID
        channel_name: 频道名称
        topic: 讨论主题
        context: 上下文
        scenario: 场景标识
        owner: 任务负责人
        backend: 执行后端偏好（subagent | tmux）
        workdir: 工作目录（必需）
        estimated_duration_minutes: 预计时长
        task_type: 任务类型（coding | documentation | research | custom）
        requires_monitoring: 是否需要监控中间过程
        timeout_seconds: 超时时间（秒）
        output_format: 输出格式（text | json）
    
    Returns:
        执行结果（task_id, dispatch_id, backend, session_id, callback_path, wake_command）
    """
    # 确定工作目录
    if not workdir:
        workdir = str(Path.cwd())
    
    workdir_path = Path(workdir).expanduser().resolve()
    
    # 生成 contract（用于获取 channel/owner/scenario 等上下文）
    contract = build_default_entry_contract(
        context=context,
        scenario=scenario,
        channel_id=channel_id,
        channel_name=channel_name,
        topic=topic,
        owner=owner,
        backend=backend,
        command_name="orch_product_run",
    )
    
    orch = contract.get("orchestration", {})
    channel_mode = None
    if _is_trading_orchestration(orch):
        channel_mode = _get_trading_default_auto_profile(
            scenario=orch.get("scenario"),
            apply=True,
        )
    
    # 调用统一执行入口
    runtime = UnifiedExecutionRuntime()
    
    # 构建 task context
    context_obj = TaskContext.from_string(
        task_description=task_description,
        workdir=workdir_path,
        backend_preference=orch.get("backend_preference"),
        estimated_duration_minutes=estimated_duration_minutes,
        task_type=task_type,
        requires_monitoring=requires_monitoring,
        metadata={
            "scenario": orch.get("scenario"),
            "owner": orch.get("owner"),
            "channel_id": orch.get("channel", {}).get("channel_id"),
            "contract_version": contract.get("version"),
        },
        timeout_seconds=timeout_seconds,
    )
    
    # 执行任务
    result = runtime.run_task(context_obj)
    
    # 注册 observability card
    card_manager = ObservabilityCardManager()
    try:
        card = card_manager.create_card(
            task_id=result.task_id,
            batch_id=result.dispatch_id,
            scenario=orch.get("scenario", "generic"),
            owner=orch.get("owner", "main"),
            executor=result.backend,
            stage="dispatch",
            anchor_type="session_id",
            anchor_value=result.session_id,
        )
    except Exception as e:
        # Observability 注册失败不影响执行结果
        card = None
    
    # 构建输出
    output = {
        "version": VERSION,
        "executed_at": _iso_now(),
        "task": {
            "task_id": result.task_id,
            "dispatch_id": result.dispatch_id,
            "description": task_description,
        },
        "execution": {
            "backend": result.backend,
            "session_id": result.session_id,
            "label": result.label,
            "status": result.status,
            "workdir": str(workdir_path),
        },
        "callback": {
            "callback_path": str(result.callback_path) if result.callback_path else None,
            "wake_command": result.wake_command,
        },
        "artifacts": {k: str(v) for k, v in result.artifacts.items()},
        "backend_selection": result.backend_selection,
        "channel_mode": channel_mode,
        "observability_card": {
            "created": card is not None,
            "card_id": card.task_id if card else None,
        } if card else {"created": False},
        "next_steps": _generate_run_next_steps(result),
    }
    
    return output


def _generate_run_next_steps(result: ExecutionResult) -> List[str]:
    """生成 run 后的下一步行动建议。"""
    steps = []
    
    if result.backend == "subagent":
        steps.append(f"1. 任务已派发为 subagent (label={result.label})")
        steps.append("2. 等待 callback 完成（自动触发）")
        steps.append(f"3. 运行 'orch_product.py status' 查看进度")
    elif result.backend == "tmux":
        steps.append(f"1. 任务已启动 tmux session (session={result.session_id})")
        steps.append(f"2. 监控进度：{result.wake_command}")
        steps.append(f"3. 查看实时输出：bash ~/.openclaw/skills/claude-code-orchestrator/scripts/monitor-tmux-task.sh --session {result.session_id}")
        steps.append("4. 完成后自动回调，运行 'orch_product.py status' 查看结果")
    
    return steps


# ============ Status Command ============


def status(
    channel_id: Optional[str] = None,
    batch_key: Optional[str] = None,
    task_id: Optional[str] = None,
    owner: Optional[str] = None,
    scenario: Optional[str] = None,
    stage: Optional[str] = None,
    limit: int = 20,
    output_format: str = "text",
) -> Dict[str, Any]:
    """
    查看状态总览。
    
    复用 observability_card 的 card/board snapshot 能力，
    聚合当前频道/批次/任务的状态。
    
    Args:
        channel_id: 频道 ID（过滤条件）
        batch_key: 批次 key（过滤条件）
        task_id: 任务 ID（查询单个任务）
        owner: 负责人（过滤条件）
        scenario: 场景（过滤条件）
        stage: 阶段（过滤条件：planning/dispatch/running/callback_received/closeout/completed/failed）
        limit: 返回结果数量限制
        output_format: 输出格式（text | json）
    
    Returns:
        状态总览（active_tasks, completed_tasks, blockers, next_steps）
    """
    card_manager = ObservabilityCardManager()
    
    # 查询卡片
    try:
        cards = list_cards(
            owner=owner,
            scenario=scenario,
            stage=stage,
            limit=limit,
        )
    except Exception as e:
        cards = []
    
    # 按 channel_id 过滤（如果需要）
    if channel_id:
        # 注意：observability card 当前不直接存储 channel_id
        # 这里通过 owner/scenario 间接关联
        pass
    
    # 分类卡片
    active_cards = []
    completed_cards = []
    failed_cards = []
    blockers = []
    
    for card in cards:
        card_dict = card.to_dict() if hasattr(card, 'to_dict') else card
        
        stage_val = card_dict.get("stage", "unknown")
        
        if stage_val in ("completed",):
            completed_cards.append(card_dict)
        elif stage_val in ("failed", "cancelled"):
            failed_cards.append(card_dict)
            # 提取 blocker 信息
            if card_dict.get("error"):
                blockers.append({
                    "task_id": card_dict.get("task_id"),
                    "error": card_dict.get("error"),
                    "stage": stage_val,
                })
        else:
            active_cards.append(card_dict)
    
    # 生成看板快照
    try:
        board_snapshot = generate_board_snapshot()
        board_snapshot_path = board_snapshot.get("snapshot_path") if isinstance(board_snapshot, dict) else None
    except Exception:
        board_snapshot_path = None
    
    # 生成 next steps
    next_steps = _generate_status_next_steps(active_cards, completed_cards, failed_cards)

    channel_mode = None
    if (scenario and str(scenario).lower() == "trading_roundtable_phase1") or (owner and str(owner).lower() == "trading"):
        channel_mode = _get_trading_default_auto_profile(
            scenario=scenario or "trading_roundtable_phase1",
            apply=False,
        )
    
    # 构建输出
    output = {
        "version": VERSION,
        "snapshot_time": _iso_now(),
        "filters": {
            "channel_id": channel_id,
            "batch_key": batch_key,
            "task_id": task_id,
            "owner": owner,
            "scenario": scenario,
            "stage": stage,
            "limit": limit,
        },
        "summary": {
            "total_cards": len(cards),
            "active": len(active_cards),
            "completed": len(completed_cards),
            "failed": len(failed_cards),
        },
        "active_tasks": active_cards[:10],  # 限制显示数量
        "completed_tasks": completed_cards[:10],
        "failed_tasks": failed_cards[:10],
        "blockers": blockers,
        "next_steps": next_steps,
        "board_snapshot_path": board_snapshot_path,
        "channel_mode": channel_mode,
    }
    
    # 如果指定了 task_id，返回单个任务详情
    if task_id:
        try:
            single_card = card_manager.get_card(task_id)
            output["task_detail"] = single_card.to_dict() if single_card and hasattr(single_card, 'to_dict') else single_card
        except Exception:
            output["task_detail"] = None
    
    return output


def _generate_status_next_steps(
    active: List[Dict],
    completed: List[Dict],
    failed: List[Dict],
) -> List[str]:
    """生成 status 后的下一步行动建议。"""
    steps = []
    
    if not active and not completed and not failed:
        steps.append("暂无任务记录")
        steps.append("使用 'orch_product.py run --task \"任务描述\"' 开始第一个任务")
        return steps
    
    if active:
        steps.append(f"1. {len(active)} 个任务正在进行中")
        steps.append("2. 等待任务完成（自动回调）")
        if any(c.get("stage") == "dispatch" for c in active):
            steps.append("3. 部分任务刚派发，等待进入 running 状态")
    
    if completed:
        steps.append(f"3. {len(completed)} 个任务已完成")
        steps.append("4. 检查 completed 任务的 verdict 和 artifact")
    
    if failed:
        steps.append(f"4. {len(failed)} 个任务失败，需要审查 blocker")
        steps.append("5. 根据失败原因决定重试/转交/中止")
    
    if active:
        steps.append("5. 运行 'orch_product.py status' 定期刷新状态")
    
    return steps


# ============ CLI Entry ============


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="🚀 OpenClaw Orchestration 产品化三件套 — onboard / run / status",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
╔═══════════════════════════════════════════════════════════╗
║  产品化三件套 — 其他 agent 一句话就会用                    ║
╠═══════════════════════════════════════════════════════════╣
║  快速开始：                                               ║
║                                                           ║
║  # 1. 查看频道接入建议                                    ║
║  python3 runtime/scripts/orch_product.py onboard          ║
║                                                           ║
║  # 2. 触发执行                                            ║
║  python3 runtime/scripts/orch_product.py run \\            ║
║    --task "任务描述"                                      ║
║                                                           ║
║  # 3. 查看状态                                            ║
║  python3 runtime/scripts/orch_product.py status           ║
║                                                           ║
║  详细说明：                                               ║
║  • onboard: 生成频道接入建议卡（adapter/scenario/owner）  ║
║  • run: 触发一次执行（自动 backend 选择 + observability）  ║
║  • status: 查看当前频道/批次/任务的状态总览               ║
║                                                           ║
║  向后兼容：                                               ║
║  • 现有 orch_command.py 入口保持不变                      ║
║  • 新入口复用现有 control plane，不另起真值链             ║
╚═══════════════════════════════════════════════════════════╝
        """,
    )
    
    subparsers = parser.add_subparsers(dest="command", help="可用命令")
    
    # onboard 命令
    onboard_parser = subparsers.add_parser(
        "onboard",
        help="生成频道接入建议卡",
    )
    onboard_parser.add_argument("--channel-id", default=None, help="频道 ID")
    onboard_parser.add_argument("--channel-name", default=None, help="频道名称")
    onboard_parser.add_argument("--topic", default=None, help="讨论主题")
    onboard_parser.add_argument("--context", default=None, help="上下文 (channel_roundtable | trading_roundtable)")
    onboard_parser.add_argument("--scenario", default=None, help="场景标识")
    onboard_parser.add_argument("--owner", default=None, help="任务负责人")
    onboard_parser.add_argument("--backend", default=None, help="执行后端偏好 (subagent | tmux)")
    onboard_parser.add_argument("--output", "-o", choices=["text", "json"], default="text", help="输出格式")
    
    # run 命令
    run_parser = subparsers.add_parser(
        "run",
        help="触发一次执行",
    )
    run_parser.add_argument("--task", "-t", required=True, help="任务描述")
    run_parser.add_argument("--channel-id", default=None, help="频道 ID")
    run_parser.add_argument("--channel-name", default=None, help="频道名称")
    run_parser.add_argument("--topic", default=None, help="讨论主题")
    run_parser.add_argument("--context", default=None, help="上下文")
    run_parser.add_argument("--scenario", default=None, help="场景标识")
    run_parser.add_argument("--owner", default=None, help="任务负责人")
    run_parser.add_argument("--backend", default=None, help="执行后端偏好")
    run_parser.add_argument("--workdir", "-w", default=None, help="工作目录")
    run_parser.add_argument("--duration", "-d", type=int, help="预计时长（分钟）")
    run_parser.add_argument("--type", "-T", dest="task_type", choices=["coding", "documentation", "research", "custom"], help="任务类型")
    run_parser.add_argument("--monitor", "-m", action="store_true", help="需要监控中间过程")
    run_parser.add_argument("--timeout", type=int, help="超时时间（秒）")
    run_parser.add_argument("--output", "-o", choices=["text", "json"], default="text", help="输出格式")
    
    # status 命令
    status_parser = subparsers.add_parser(
        "status",
        help="查看状态总览",
    )
    status_parser.add_argument("--channel-id", default=None, help="频道 ID")
    status_parser.add_argument("--batch-key", default=None, help="批次 key")
    status_parser.add_argument("--task-id", default=None, help="任务 ID")
    status_parser.add_argument("--owner", default=None, help="负责人")
    status_parser.add_argument("--scenario", default=None, help="场景")
    status_parser.add_argument("--stage", default=None, help="阶段")
    status_parser.add_argument("--limit", "-l", type=int, default=20, help="返回结果数量限制")
    status_parser.add_argument("--output", "-o", choices=["text", "json"], default="text", help="输出格式")
    
    return parser


def _print_result(result: Dict[str, Any], output_format: str) -> None:
    """打印结果。"""
    if output_format == "json":
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        # 人类可读格式
        print(f"=== {result.get('version', 'orch_product')} ===")
        print()
        
        if "channel" in result:
            ch = result["channel"]
            print(f"Channel: {ch.get('channel_id') or 'N/A'} ({ch.get('channel_name') or 'N/A'})")
            if ch.get("topic"):
                print(f"Topic: {ch['topic']}")
            print()
        
        if "recommendation" in result:
            rec = result["recommendation"]
            print("Recommendation:")
            print(f"  Adapter: {rec.get('adapter', 'N/A')}")
            print(f"  Scenario: {rec.get('scenario', 'N/A')}")
            print(f"  Owner: {rec.get('owner', 'N/A')}")
            print(f"  Backend: {rec.get('backend', 'N/A')}")
            print(f"  Gate Policy: {rec.get('gate_policy', 'N/A')}")
            print()
        
        if result.get("channel_mode"):
            mode = result["channel_mode"]
            print("Channel Mode:")
            print(f"  Mode: {mode.get('mode', 'N/A')}")
            print(f"  Cutover Applied: {mode.get('cutover_applied', False)}")
            retained = mode.get("retained_gates") or []
            if retained:
                print(f"  Retained Gates: {', '.join(retained)}")
            print()

        if "task" in result:
            task = result["task"]
            print(f"Task ID: {task.get('task_id', 'N/A')}")
            print(f"Description: {task.get('description', 'N/A')}")
            print()
        
        if "execution" in result:
            exec_info = result["execution"]
            print("Execution:")
            print(f"  Backend: {exec_info.get('backend', 'N/A')}")
            print(f"  Session: {exec_info.get('session_id', 'N/A')}")
            print(f"  Status: {exec_info.get('status', 'N/A')}")
            print()
        
        if "callback" in result:
            cb = result["callback"]
            if cb.get("callback_path"):
                print(f"Callback Path: {cb['callback_path']}")
            if cb.get("wake_command"):
                print(f"Wake Command: {cb['wake_command']}")
            print()
        
        if "summary" in result:
            summary = result["summary"]
            print("Summary:")
            print(f"  Total: {summary.get('total_cards', 0)}")
            print(f"  Active: {summary.get('active', 0)}")
            print(f"  Completed: {summary.get('completed', 0)}")
            print(f"  Failed: {summary.get('failed', 0)}")
            print()
        
        if "active_tasks" in result:
            active = result["active_tasks"]
            if active:
                print(f"Active Tasks ({len(active)}):")
                for task in active[:5]:
                    print(f"  - {task.get('task_id')}: {task.get('stage')} @ {task.get('executor')}")
                if len(active) > 5:
                    print(f"  ... and {len(active) - 5} more")
            print()
        
        if "blockers" in result:
            blockers = result["blockers"]
            if blockers:
                print(f"Blockers ({len(blockers)}):")
                for b in blockers:
                    print(f"  - {b.get('task_id')}: {b.get('error')}")
            print()
        
        if "next_steps" in result:
            print("Next Steps:")
            for step in result["next_steps"]:
                print(f"  {step}")
            print()
        
        if "example_commands" in result:
            print("Example Commands:")
            for cmd_name, cmd in result["example_commands"].items():
                print(f"  {cmd_name}: {cmd}")
            print()


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    try:
        if args.command == "onboard":
            result = onboard(
                channel_id=args.channel_id,
                channel_name=args.channel_name,
                topic=args.topic,
                context=args.context,
                scenario=args.scenario,
                owner=args.owner,
                backend=args.backend,
            )
            _print_result(result, args.output)
        
        elif args.command == "run":
            result = run(
                task_description=args.task,
                channel_id=args.channel_id,
                channel_name=args.channel_name,
                topic=args.topic,
                context=args.context,
                scenario=args.scenario,
                owner=args.owner,
                backend=args.backend,
                workdir=args.workdir,
                estimated_duration_minutes=args.duration,
                task_type=args.task_type,
                requires_monitoring=args.monitor,
                timeout_seconds=args.timeout,
                output_format=args.output,
            )
            _print_result(result, args.output)
        
        elif args.command == "status":
            result = status(
                channel_id=args.channel_id,
                batch_key=args.batch_key,
                task_id=args.task_id,
                owner=args.owner,
                scenario=args.scenario,
                stage=args.stage,
                limit=args.limit,
                output_format=args.output,
            )
            _print_result(result, args.output)
        
        else:
            parser.print_help()
            return 1
        
        return 0
    
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
