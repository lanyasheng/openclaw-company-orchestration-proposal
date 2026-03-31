#!/usr/bin/env python3
"""
dashboard.py — 编排系统可视化看板 Batch 6

最小可用看板，基于现有 observability 状态卡/统一索引，提供可直接查看的任务总览。

本次收口增强：
1. stale/过期任务派生标记（基于 heartbeat / promised_eta / stage）
2. 旧 demo/test 卡自动清理（仅 observability 层，安全 TTL + dry-run）
3. 导出快照包含 dashboard_health / cleanup summary，便于验证
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# 添加父目录到路径以导入 observability_card
sys.path.insert(0, str(Path(__file__).parent))

from rich import box
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from observability_card import CARD_DIR, ObservabilityCard

__all__ = [
    "Dashboard",
    "build_dashboard_snapshot",
    "cleanup_demo_cards",
    "create_active_tasks_table",
    "create_owner_summary",
    "create_stage_table",
    "create_summary_panel",
    "get_anchor_display",
    "get_card_health",
    "get_eta_color",
    "is_demo_card",
    "load_cards_from_dir",
    "main",
    "render_dashboard",
]

# 阶段颜色映射
STAGE_COLORS = {
    "planning": "gray50",
    "dispatch": "blue",
    "running": "yellow",
    "callback_received": "cyan",
    "closeout": "magenta",
    "completed": "green",
    "failed": "red",
    "cancelled": "dim",
}

TERMINAL_STAGES = {"completed", "failed", "cancelled"}
ACTIVE_STAGES = {"planning", "dispatch", "running", "callback_received", "closeout"}

# stage-aware stale heartbeat 阈值（秒）
STALE_HEARTBEAT_SECONDS_BY_STAGE = {
    "planning": 3600,
    "dispatch": 1800,
    "running": 900,
    "callback_received": 1800,
    "closeout": 1800,
}
DEFAULT_STALE_HEARTBEAT_SECONDS = 1800
DEFAULT_DEMO_TTL_HOURS = float(os.environ.get("OPENCLAW_OBSERVABILITY_DEMO_TTL_HOURS", "24"))
DEMO_MARKER_RE = re.compile(r"(^|[_-])(demo|test)([_-]|$)", re.IGNORECASE)

# 历史归档阈值：stale 超过此时长的卡片被视为"历史归档"
# 默认 48 小时，但对 trading scenario 的 callback_received 卡片使用更短阈值（6 小时）
ARCHIVE_STALE_THRESHOLD_HOURS = float(os.environ.get("OPENCLAW_ARCHIVE_STALE_THRESHOLD_HOURS", "48"))
ARCHIVE_STALE_TRADING_CALLBACK_HOURS = float(os.environ.get("OPENCLAW_ARCHIVE_STALE_TRADING_CALLBACK_HOURS", "6"))


def _iso_now() -> str:
    return datetime.now().isoformat()


def parse_datetime(value: Optional[str]) -> Optional[datetime]:
    """宽松解析 ISO 时间。"""
    if not value:
        return None

    text = str(value).strip()
    candidates = [text]

    if text.endswith("Z"):
        candidates.append(text[:-1] + "+00:00")
    if " " in text and "T" not in text:
        candidates.append(text.replace(" ", "T", 1))

    seen = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            continue

    return None


def _timestamp_for_sort(value: Optional[str]) -> float:
    dt = parse_datetime(value)
    if dt is None:
        return 0.0
    try:
        return dt.timestamp()
    except Exception:
        return 0.0


def _age_seconds(dt: Optional[datetime], now: Optional[datetime] = None) -> Optional[int]:
    if dt is None:
        return None

    ref = now
    if ref is None:
        ref = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
    elif dt.tzinfo and ref.tzinfo is None:
        ref = ref.replace(tzinfo=dt.tzinfo)
    elif dt.tzinfo is None and ref.tzinfo is not None:
        ref = ref.replace(tzinfo=None)

    try:
        return max(0, int((ref - dt).total_seconds()))
    except Exception:
        return None


def _derive_last_activity(card: ObservabilityCard) -> Optional[datetime]:
    candidates = [
        card.heartbeat,
        card.metrics.get("completed_at") if card.metrics else None,
        card.metrics.get("started_at") if card.metrics else None,
        card.metrics.get("created_at") if card.metrics else None,
    ]
    for candidate in candidates:
        parsed = parse_datetime(candidate)
        if parsed is not None:
            return parsed
    return None


# 优先级颜色（根据 promised_eta）
def get_eta_color(promised_eta: Optional[str], heartbeat: str) -> str:
    """根据 ETA 判断颜色。"""
    del heartbeat  # 保留签名兼容旧测试
    if not promised_eta:
        return "white"

    eta = parse_datetime(promised_eta)
    if eta is None:
        return "white"

    now = datetime.now(eta.tzinfo) if eta.tzinfo else datetime.now()
    diff_seconds = (eta - now).total_seconds()

    if diff_seconds < 0:
        return "red"
    if diff_seconds < 1800:
        return "yellow"
    return "green"


def format_heartbeat(heartbeat: str) -> str:
    """格式化心跳时间。"""
    dt = parse_datetime(heartbeat)
    if dt is None:
        return heartbeat[:19] if heartbeat else "-"

    now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
    diff = max(0, int((now - dt).total_seconds()))

    if diff < 60:
        return f"{diff}s 前"
    if diff < 3600:
        return f"{diff // 60}m 前"
    if diff < 86400:
        return f"{diff // 3600}h 前"
    return dt.strftime("%m-%d %H:%M")


def format_eta(promised_eta: Optional[str]) -> str:
    """格式化 ETA。"""
    if not promised_eta:
        return "-"
    dt = parse_datetime(promised_eta)
    if dt is None:
        return promised_eta[:19]
    return dt.strftime("%m-%d %H:%M")


def get_anchor_display(card: ObservabilityCard) -> str:
    """获取锚点显示文本。"""
    if not card.promise_anchor:
        return "-"

    anchor_type = card.promise_anchor.get("anchor_type", "")
    anchor_value = card.promise_anchor.get("anchor_value", "")

    if anchor_type == "tmux_session":
        return f"[tmux] {anchor_value[:20]}"
    if anchor_type == "session_id":
        return f"[session] {anchor_value[:20]}"
    if anchor_type == "dispatch_id":
        return f"[dispatch] {anchor_value[:15]}"
    return anchor_value[:20] if anchor_value else "-"


def get_card_health(card: ObservabilityCard, now: Optional[datetime] = None) -> Dict[str, Any]:
    """派生 dashboard health / stale 状态（只读，不回写 truth）。"""
    heartbeat_dt = parse_datetime(card.heartbeat)
    promised_eta = card.promise_anchor.get("promised_eta") if card.promise_anchor else None
    eta_dt = parse_datetime(promised_eta)

    heartbeat_age_seconds = _age_seconds(heartbeat_dt, now=now)
    eta_overdue_seconds = None
    if eta_dt is not None:
        eta_ref = now or (datetime.now(eta_dt.tzinfo) if eta_dt.tzinfo else datetime.now())
        eta_overdue_seconds = max(0, int((eta_ref - eta_dt).total_seconds()))

    reasons: List[str] = []
    reason_labels: List[str] = []

    if card.stage in ACTIVE_STAGES:
        heartbeat_limit = STALE_HEARTBEAT_SECONDS_BY_STAGE.get(
            card.stage,
            DEFAULT_STALE_HEARTBEAT_SECONDS,
        )
        if heartbeat_age_seconds is not None and heartbeat_age_seconds > heartbeat_limit:
            reasons.append("heartbeat_stale")
            reason_labels.append(f"hb>{heartbeat_limit // 60}m")

        if eta_dt is not None and eta_overdue_seconds is not None and eta_overdue_seconds > 0:
            reasons.append("eta_overdue")
            reason_labels.append("eta已过期")

    is_stale = len(reasons) > 0 and card.stage not in TERMINAL_STAGES

    if is_stale and {"heartbeat_stale", "eta_overdue"}.issubset(set(reasons)):
        label = "STALE hb+eta"
        color = "red"
        severity = "critical"
    elif is_stale and "eta_overdue" in reasons:
        label = "STALE eta"
        color = "red"
        severity = "critical"
    elif is_stale:
        label = "STALE hb"
        color = "yellow"
        severity = "warning"
    else:
        label = "OK"
        color = "green"
        severity = "ok"

    detail = " / ".join(reason_labels) if reason_labels else "healthy"

    return {
        "is_stale": is_stale,
        "label": label,
        "color": color,
        "severity": severity,
        "detail": detail,
        "reasons": reasons,
        "heartbeat_age_seconds": heartbeat_age_seconds,
        "eta_overdue_seconds": eta_overdue_seconds,
        "promised_eta": promised_eta,
        "last_activity": _derive_last_activity(card).isoformat() if _derive_last_activity(card) else None,
    }


def is_historical_stale(card: ObservabilityCard, health: Dict[str, Any], now: Optional[datetime] = None) -> bool:
    """
    判断卡片是否为"历史归档 stale 卡"。
    
    条件：
    1. 当前是 stale 状态
    2. stage == callback_received（历史回调卡）
    3. stale 时长超过阈值：
       - trading scenario: ARCHIVE_STALE_TRADING_CALLBACK_HOURS（默认 6 小时）
       - 其他 scenario: ARCHIVE_STALE_THRESHOLD_HOURS（默认 48 小时）
    
    这类卡片默认从主视图隐藏，归入归档视图。
    """
    if not health.get("is_stale"):
        return False
    
    if card.stage != "callback_received":
        return False
    
    last_activity = _derive_last_activity(card)
    if last_activity is None:
        return False
    
    age_hours = _age_seconds(last_activity, now=now)
    if age_hours is None:
        return False
    
    # scenario-aware 阈值：trading roundtable 的 stale callback_received 更快归档
    is_trading_scenario = card.scenario and "trading" in card.scenario.lower()
    threshold_hours = ARCHIVE_STALE_TRADING_CALLBACK_HOURS if is_trading_scenario else ARCHIVE_STALE_THRESHOLD_HOURS
    threshold_seconds = threshold_hours * 3600
    
    return age_hours >= threshold_seconds


def load_cards_from_dir(card_dir: Path, limit: int = 1000) -> List[ObservabilityCard]:
    """直接从指定目录加载卡片，避免依赖全局 CARD_DIR。"""
    if not card_dir.exists():
        return []

    cards: List[ObservabilityCard] = []
    files = sorted(card_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for card_file in files:
        if len(cards) >= limit:
            break
        try:
            with open(card_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            cards.append(ObservabilityCard.from_dict(data))
        except (json.JSONDecodeError, OSError, KeyError):
            continue
    return cards


def _has_demo_marker(value: Optional[str]) -> bool:
    return bool(value and DEMO_MARKER_RE.search(str(value)))


def is_demo_card(card: ObservabilityCard) -> bool:
    """只识别明确 demo/test 卡，避免误删真实任务。"""
    metadata = card.metadata or {}
    if metadata.get("demo_card") is True or metadata.get("is_demo") is True:
        return True

    anchor_value = (card.promise_anchor or {}).get("anchor_value")
    attach_info = card.attach_info or {}
    inspect_values = [
        card.task_id,
        card.batch_id,
        anchor_value,
        attach_info.get("session_id"),
        attach_info.get("run_label"),
        attach_info.get("label"),
        attach_info.get("tmux_session"),
    ]
    return any(_has_demo_marker(value) for value in inspect_values)


def _remove_task_from_index(index_path: Path, task_id: str) -> None:
    if not index_path.exists():
        return

    entries: List[str] = []
    with open(index_path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line.strip())
            except json.JSONDecodeError:
                continue
            if entry.get("task_id") != task_id:
                entries.append(json.dumps(entry, ensure_ascii=False))

    tmp_file = index_path.with_suffix(".tmp")
    with open(tmp_file, "w", encoding="utf-8") as f:
        for line in entries:
            f.write(line + "\n")
    tmp_file.replace(index_path)


def cleanup_demo_cards(
    card_dir: Path,
    *,
    older_than_hours: float = DEFAULT_DEMO_TTL_HOURS,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """安全清理旧 demo/test 卡。

    规则：
    - 仅匹配明确 demo/test marker 的卡
    - 且最近活动时间超过 TTL
    - 默认支持 dry-run 预览
    """
    now = datetime.now()
    index_dir = card_dir.parent / "index"
    report: Dict[str, Any] = {
        "scanned": 0,
        "matched": 0,
        "deleted_count": 0,
        "dry_run": dry_run,
        "older_than_hours": older_than_hours,
        "deleted_task_ids": [],
        "candidates": [],
    }

    if not card_dir.exists():
        return report

    ttl_seconds = max(0, int(older_than_hours * 3600))

    for card_file in sorted(card_dir.glob("*.json")):
        report["scanned"] += 1
        try:
            with open(card_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            card = ObservabilityCard.from_dict(data)
        except (json.JSONDecodeError, OSError, KeyError):
            continue

        if not is_demo_card(card):
            continue

        last_activity_dt = _derive_last_activity(card)
        age_seconds = _age_seconds(last_activity_dt, now=now)
        if age_seconds is None or age_seconds < ttl_seconds:
            continue

        candidate = {
            "task_id": card.task_id,
            "stage": card.stage,
            "owner": card.owner,
            "scenario": card.scenario,
            "file": str(card_file),
            "age_hours": round(age_seconds / 3600, 2),
            "last_activity": last_activity_dt.isoformat() if last_activity_dt else None,
            "reason": "explicit demo/test marker + ttl exceeded",
        }
        report["matched"] += 1
        report["candidates"].append(candidate)

        if dry_run:
            continue

        try:
            card_file.unlink()
            _remove_task_from_index(index_dir / f"{card.owner}.jsonl", card.task_id)
            report["deleted_count"] += 1
            report["deleted_task_ids"].append(card.task_id)
        except OSError:
            continue

    return report


def build_dashboard_snapshot(
    cards: List[ObservabilityCard],
    *,
    cleanup_report: Optional[Dict[str, Any]] = None,
    generated_at: Optional[str] = None,
) -> Dict[str, Any]:
    """
    构建 dashboard 导出快照，包含 stale 与 cleanup 摘要。
    
    新增归档视图支持（v3）：
    - archived_stale_cards: 历史归档 stale 卡数量（默认隐藏）
    - visible_active_cards: 可见活跃卡数量（不含归档 stale）
    - historical_stale_cards: 历史 stale 卡列表（可追溯）
    """
    generated_at = generated_at or _iso_now()

    by_stage: Dict[str, int] = {}
    by_owner: Dict[str, int] = {}
    enriched_cards: List[Dict[str, Any]] = []
    stale_count = 0
    active_count = 0
    archived_stale_count = 0
    historical_stale_cards: List[Dict[str, Any]] = []

    for card in cards:
        by_stage[card.stage] = by_stage.get(card.stage, 0) + 1
        by_owner[card.owner] = by_owner.get(card.owner, 0) + 1
        
        # 计算 active count: callback_received 只有非 stale 才算 active
        health = get_card_health(card)
        if card.stage in {"dispatch", "running", "closeout"}:
            active_count += 1
        elif card.stage == "callback_received" and not health["is_stale"]:
            # callback_received 只有近期活跃才算 active，避免历史 stale 卡污染统计
            active_count += 1

        if health["is_stale"]:
            stale_count += 1
        
        # 归档视图逻辑：历史 stale callback_received 卡归入归档
        if is_historical_stale(card, health):
            archived_stale_count += 1
            archived_item = card.to_dict()
            archived_item["dashboard_health"] = health
            archived_item["archive_reason"] = "historical_stale_callback_received"
            historical_stale_cards.append(archived_item)

        item = card.to_dict()
        item["dashboard_health"] = health
        item["is_archived"] = is_historical_stale(card, health)
        enriched_cards.append(item)

    snapshot = {
        "snapshot_version": "dashboard_snapshot_v3",
        "generated_at": generated_at,
        "summary": {
            "total_cards": len(cards),
            "active_cards": active_count,
            "stale_cards": stale_count,
            "archived_stale_cards": archived_stale_count,
            "visible_active_cards": active_count,
            "by_stage": by_stage,
            "by_owner": by_owner,
        },
        "cleanup": cleanup_report or {
            "scanned": 0,
            "matched": 0,
            "deleted_count": 0,
            "dry_run": False,
            "older_than_hours": DEFAULT_DEMO_TTL_HOURS,
            "deleted_task_ids": [],
            "candidates": [],
        },
        "all_cards": enriched_cards,
        "historical_stale_cards": historical_stale_cards,
    }
    return snapshot


def create_summary_panel(cards: List[ObservabilityCard], cleanup_report: Optional[Dict[str, Any]] = None) -> Panel:
    """创建摘要面板。"""
    total = len(cards)

    by_stage: Dict[str, int] = {}
    by_owner: Dict[str, int] = {}
    stale_count = 0
    active_count = 0
    archived_stale_count = 0
    for card in cards:
        by_stage[card.stage] = by_stage.get(card.stage, 0) + 1
        by_owner[card.owner] = by_owner.get(card.owner, 0) + 1
        health = get_card_health(card)
        if health["is_stale"]:
            stale_count += 1
        # 计算 active: callback_received 只有非 stale 才算
        if card.stage in {"dispatch", "running", "closeout"}:
            active_count += 1
        elif card.stage == "callback_received" and not health["is_stale"]:
            active_count += 1
        
        # 归档统计
        if is_historical_stale(card, health):
            archived_stale_count += 1

    active = active_count
    completed = by_stage.get("completed", 0)
    failed = by_stage.get("failed", 0)

    text = Text()
    text.append(f"任务总数：{total}\n", style="bold")
    text.append(f"活跃：{active} ", style="yellow")
    text.append(f"Stale：{stale_count} ", style="bold red" if stale_count else "green")
    if archived_stale_count > 0:
        text.append(f"(归档：{archived_stale_count}) ", style="dim")
    text.append(f"完成：{completed} ", style="green")
    text.append(f"失败：{failed}\n", style="red")

    if cleanup_report:
        deleted_count = cleanup_report.get("deleted_count", 0)
        matched = cleanup_report.get("matched", 0)
        dry_run = cleanup_report.get("dry_run", False)
        cleanup_style = "yellow" if dry_run else ("green" if deleted_count else "dim")
        cleanup_text = (
            f"Demo 清理预览：{matched}" if dry_run else f"Demo 已清理：{deleted_count}"
        )
        text.append(f"{cleanup_text}\n", style=cleanup_style)

    text.append("\n按 Owner 统计:\n", style="bold")
    for owner, count in sorted(by_owner.items()):
        text.append(f"  {owner}: {count}\n", style="cyan")

    return Panel(text, title="[bold]📊 任务摘要[/bold]", border_style="blue")


def create_stage_table(cards: List[ObservabilityCard]) -> Table:
    """按 stage 分组的任务表。"""
    table = Table(
        title="[bold]📋 按阶段分组[/bold]",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold magenta",
    )

    table.add_column("Stage", style="cyan", width=14)
    table.add_column("任务数", justify="right", width=10)
    table.add_column("任务 ID", style="white", width=36)
    table.add_column("Owner", style="green", width=10)
    table.add_column("心跳", width=12)
    table.add_column("状态", width=14)

    by_stage: Dict[str, List[ObservabilityCard]] = {}
    for card in cards:
        by_stage.setdefault(card.stage, []).append(card)

    stage_order = [
        "planning",
        "dispatch",
        "running",
        "callback_received",
        "closeout",
        "completed",
        "failed",
        "cancelled",
    ]

    for stage in stage_order:
        if stage not in by_stage:
            continue

        stage_cards = by_stage[stage]
        color = STAGE_COLORS.get(stage, "white")
        stale_in_stage = sum(1 for card in stage_cards if get_card_health(card)["is_stale"])
        stage_count_text = str(len(stage_cards))
        if stale_in_stage:
            stage_count_text += f" ({stale_in_stage} stale)"

        sorted_stage_cards = sorted(
            stage_cards,
            key=lambda card: (
                0 if get_card_health(card)["is_stale"] else 1,
                -_timestamp_for_sort(card.heartbeat),
            ),
        )

        for i, card in enumerate(sorted_stage_cards[:5]):
            health = get_card_health(card)
            task_id_display = f"⚠ {card.task_id[:32]}" if health["is_stale"] else card.task_id[:35]
            heartbeat_display = format_heartbeat(card.heartbeat)
            if health["is_stale"]:
                heartbeat_display = f"[{health['color']}]{heartbeat_display}[/{health['color']}]"

            table.add_row(
                f"[{color}]{stage}[/{color}]" if i == 0 else "",
                stage_count_text if i == 0 else "",
                task_id_display,
                card.owner,
                heartbeat_display,
                f"[{health['color']}]{health['label']}[/{health['color']}]",
            )

        if len(stage_cards) > 5:
            table.add_row("", f"[dim]+{len(stage_cards) - 5} 更多...[/dim]", "", "", "", "")

    return table


def create_active_tasks_table(cards: List[ObservabilityCard], *, hide_archived: bool = True) -> Table:
    """
    最近活跃任务列表。
    
    Args:
        cards: 所有卡片
        hide_archived: 是否隐藏历史归档 stale 卡（默认 True）
    """
    table = Table(
        title="[bold]🔥 最近活跃任务[/bold]",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold magenta",
    )

    table.add_column("Task ID", style="cyan", width=28)
    table.add_column("Scenario", style="white", width=15)
    table.add_column("Owner", style="green", width=10)
    table.add_column("Executor", style="blue", width=10)
    table.add_column("Stage", width=12)
    table.add_column("状态", width=14)
    table.add_column("心跳", width=10)
    table.add_column("ETA", width=12)
    table.add_column("Anchor", style="dim", width=24)

    decorated = [(card, get_card_health(card)) for card in cards]
    
    # 过滤掉归档的历史 stale 卡（默认隐藏）
    if hide_archived:
        decorated = [(card, health) for card, health in decorated if not is_historical_stale(card, health)]
    
    decorated.sort(
        key=lambda item: (
            0 if item[1]["is_stale"] else 1,
            -_timestamp_for_sort(item[0].heartbeat),
        )
    )

    for card, health in decorated[:15]:
        stage_color = STAGE_COLORS.get(card.stage, "white")
        eta_value = card.promise_anchor.get("promised_eta") if card.promise_anchor else None
        eta_color = "red" if health["is_stale"] and "eta_overdue" in health["reasons"] else get_eta_color(eta_value, card.heartbeat)

        table.add_row(
            f"⚠ {card.task_id[:25]}" if health["is_stale"] else card.task_id[:28],
            card.scenario,
            card.owner,
            card.executor,
            f"[{stage_color}]{card.stage}[/{stage_color}]",
            f"[{health['color']}]{health['label']}[/{health['color']}]",
            f"[{health['color']}]{format_heartbeat(card.heartbeat)}[/{health['color']}]" if health["is_stale"] else format_heartbeat(card.heartbeat),
            f"[{eta_color}]{format_eta(eta_value)}[/{eta_color}]",
            get_anchor_display(card),
        )

    return table


def create_owner_summary(cards: List[ObservabilityCard]) -> Table:
    """按 owner 分组统计。"""
    table = Table(
        title="[bold]👥 按 Owner 分组[/bold]",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold magenta",
    )

    table.add_column("Owner", style="green", width=12)
    table.add_column("总数", justify="right", width=8)
    table.add_column("Running", justify="right", width=10, style="yellow")
    table.add_column("Dispatch", justify="right", width=10, style="blue")
    table.add_column("Stale", justify="right", width=8, style="red")
    table.add_column("Completed", justify="right", width=10, style="green")
    table.add_column("Failed", justify="right", width=8, style="red")

    by_owner: Dict[str, Dict[str, int]] = {}
    for card in cards:
        stats = by_owner.setdefault(
            card.owner,
            {"total": 0, "running": 0, "dispatch": 0, "stale": 0, "completed": 0, "failed": 0},
        )
        stats["total"] += 1
        if card.stage == "running":
            stats["running"] += 1
        elif card.stage == "dispatch":
            stats["dispatch"] += 1
        elif card.stage == "completed":
            stats["completed"] += 1
        elif card.stage == "failed":
            stats["failed"] += 1
        if get_card_health(card)["is_stale"]:
            stats["stale"] += 1

    for owner, stats in sorted(by_owner.items()):
        table.add_row(
            owner,
            str(stats["total"]),
            str(stats["running"]),
            str(stats["dispatch"]),
            str(stats["stale"]),
            str(stats["completed"]),
            str(stats["failed"]),
        )

    return table


def render_dashboard(
    cards: List[ObservabilityCard],
    cleanup_report: Optional[Dict[str, Any]] = None,
    *,
    hide_archived: bool = True,
) -> Layout:
    """
    渲染完整看板布局。
    
    Args:
        cards: 所有卡片
        cleanup_report: 清理报告
        hide_archived: 是否隐藏历史归档 stale 卡（默认 True）
    """
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=12),
        Layout(name="middle", ratio=2),
        Layout(name="bottom", ratio=3),
    )
    layout["middle"].split_row(
        Layout(name="stage", ratio=2),
        Layout(name="owner", ratio=1),
    )

    layout["header"].update(create_summary_panel(cards, cleanup_report=cleanup_report))
    layout["stage"].update(create_stage_table(cards))
    layout["owner"].update(create_owner_summary(cards))
    layout["bottom"].update(create_active_tasks_table(cards, hide_archived=hide_archived))
    return layout


class Dashboard:
    """可视化看板类。"""

    def __init__(
        self,
        refresh_interval: float = 5.0,
        card_dir: Optional[Path] = None,
        *,
        auto_cleanup_demo: bool = True,
        demo_ttl_hours: float = DEFAULT_DEMO_TTL_HOURS,
        hide_archived: bool = True,
    ):
        self.refresh_interval = refresh_interval
        self.card_dir = Path(card_dir or CARD_DIR)
        self.console = Console()
        self.auto_cleanup_demo = auto_cleanup_demo
        self.demo_ttl_hours = demo_ttl_hours
        self.hide_archived = hide_archived
        self.last_cleanup_report: Optional[Dict[str, Any]] = None

    def cleanup_demo_cards(self, dry_run: bool = False) -> Dict[str, Any]:
        self.last_cleanup_report = cleanup_demo_cards(
            self.card_dir,
            older_than_hours=self.demo_ttl_hours,
            dry_run=dry_run,
        )
        return self.last_cleanup_report

    def load_cards(self) -> List[ObservabilityCard]:
        if self.auto_cleanup_demo:
            self.cleanup_demo_cards(dry_run=False)
        return load_cards_from_dir(self.card_dir, limit=1000)

    def render_once(self) -> None:
        cards = self.load_cards()
        layout = render_dashboard(cards, cleanup_report=self.last_cleanup_report, hide_archived=self.hide_archived)
        self.console.print(layout)

    def export_snapshot(self, output_path: str) -> str:
        if self.auto_cleanup_demo:
            self.cleanup_demo_cards(dry_run=False)
        cards = load_cards_from_dir(self.card_dir, limit=1000)
        snapshot = build_dashboard_snapshot(cards, cleanup_report=self.last_cleanup_report)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2, ensure_ascii=False)

        return output_path

    def run_live(self) -> None:
        def generate_layout() -> Layout:
            cards = self.load_cards()
            return render_dashboard(cards, cleanup_report=self.last_cleanup_report, hide_archived=self.hide_archived)

        with Live(generate_layout(), console=self.console, refresh_per_second=1, screen=True) as live:
            while True:
                time.sleep(self.refresh_interval)
                live.update(generate_layout())


def main():
    """命令行入口。"""
    parser = argparse.ArgumentParser(
        description="编排系统可视化看板 - Batch 6",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python dashboard.py                         # 实时看板（5 秒刷新）
  python dashboard.py --refresh 10            # 10 秒刷新
  python dashboard.py --once                  # 单次快照
  python dashboard.py --export out.json       # 导出 JSON
  python dashboard.py --no-auto-cleanup       # 仅查看，不自动清理 demo 卡
  python dashboard.py --demo-ttl-hours 48     # demo 卡 TTL 改为 48 小时
        """,
    )

    parser.add_argument("--refresh", "-r", type=float, default=5.0, help="刷新间隔（秒），默认 5.0")
    parser.add_argument("--once", "-o", action="store_true", help="单次快照模式（不刷新）")
    parser.add_argument("--export", "-e", type=str, metavar="PATH", help="导出 JSON 快照到指定路径")
    parser.add_argument(
        "--card-dir",
        "-d",
        type=Path,
        default=None,
        help="状态卡目录（默认：~/.openclaw/shared-context/observability/cards）",
    )
    parser.add_argument(
        "--no-auto-cleanup",
        action="store_true",
        help="禁用旧 demo/test 卡自动清理",
    )
    parser.add_argument(
        "--demo-ttl-hours",
        type=float,
        default=DEFAULT_DEMO_TTL_HOURS,
        help=f"demo/test 卡自动清理 TTL（小时，默认 {DEFAULT_DEMO_TTL_HOURS}）",
    )
    parser.add_argument(
        "--show-archived",
        action="store_true",
        help="显示历史归档 stale 卡（默认隐藏）",
    )

    args = parser.parse_args()

    dashboard = Dashboard(
        refresh_interval=args.refresh,
        card_dir=args.card_dir,
        auto_cleanup_demo=not args.no_auto_cleanup,
        demo_ttl_hours=args.demo_ttl_hours,
        hide_archived=not args.show_archived,
    )

    if args.export:
        output_path = dashboard.export_snapshot(args.export)
        print(f"✅ 快照已导出：{output_path}")
        return 0

    if args.once:
        dashboard.render_once()
        return 0

    try:
        dashboard.run_live()
    except KeyboardInterrupt:
        print("\n👋 看板已退出")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
