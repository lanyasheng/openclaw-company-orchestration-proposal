#!/usr/bin/env python3
"""
dashboard.py — 编排系统可视化看板 Batch 6

最小可用看板，基于现有 observability 状态卡/统一索引，提供可直接查看的任务总览。

核心能力：
1. 任务总数统计
2. 按 stage 分组显示
3. 按 owner 分组统计
4. 最近活跃任务列表
5. 关键字段：task_id / scenario / owner / executor / stage / heartbeat / promised_eta / anchor

使用示例：
```bash
# 启动看板（默认刷新间隔 5 秒）
python runtime/orchestrator/dashboard.py

# 指定刷新间隔（秒）
python runtime/orchestrator/dashboard.py --refresh 10

# 单次快照（不刷新）
python runtime/orchestrator/dashboard.py --once

# 导出 JSON 快照
python runtime/orchestrator/dashboard.py --export /tmp/board-snapshot.json
```
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# 添加父目录到路径以导入 observability_card
sys.path.insert(0, str(Path(__file__).parent))

from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.text import Text
from rich import box

# 从 observability_card 导入
from observability_card import (
    ObservabilityCard,
    ObservabilityCardManager,
    list_cards,
    generate_board_snapshot,
    CARD_DIR,
)

__all__ = [
    "Dashboard",
    "render_dashboard",
    "main",
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

# 优先级颜色（根据 promised_eta）
def get_eta_color(promised_eta: Optional[str], heartbeat: str) -> str:
    """根据 ETA 和心跳判断颜色"""
    if not promised_eta:
        return "white"
    
    try:
        eta = datetime.fromisoformat(promised_eta.replace("+08:00", "+08:00").replace("Z", "+00:00"))
        now = datetime.now(eta.tzinfo)
        
        # 如果已过期
        if now > eta:
            return "red"
        # 如果 30 分钟内到期
        elif (eta - now).total_seconds() < 1800:
            return "yellow"
        else:
            return "green"
    except Exception:
        return "white"


def format_heartbeat(heartbeat: str) -> str:
    """格式化心跳时间"""
    try:
        dt = datetime.fromisoformat(heartbeat.replace("+08:00", "+08:00"))
        # 计算相对时间
        now = datetime.now(dt.tzinfo)
        diff = (now - dt).total_seconds()
        
        if diff < 60:
            return f"{int(diff)}s 前"
        elif diff < 3600:
            return f"{int(diff / 60)}m 前"
        elif diff < 86400:
            return f"{int(diff / 3600)}h 前"
        else:
            return dt.strftime("%m-%d %H:%M")
    except Exception:
        return heartbeat[:19]


def format_eta(promised_eta: Optional[str]) -> str:
    """格式化 ETA"""
    if not promised_eta:
        return "-"
    try:
        dt = datetime.fromisoformat(promised_eta.replace("+08:00", "+08:00"))
        return dt.strftime("%m-%d %H:%M")
    except Exception:
        return promised_eta[:19] if promised_eta else "-"


def get_anchor_display(card: ObservabilityCard) -> str:
    """获取锚点显示文本"""
    if not card.promise_anchor:
        return "-"
    
    anchor_type = card.promise_anchor.get("anchor_type", "")
    anchor_value = card.promise_anchor.get("anchor_value", "")
    
    if anchor_type == "tmux_session":
        return f"[tmux] {anchor_value[:20]}"
    elif anchor_type == "session_id":
        return f"[session] {anchor_value[:20]}"
    elif anchor_type == "dispatch_id":
        return f"[dispatch] {anchor_value[:15]}"
    else:
        return anchor_value[:20] if anchor_value else "-"


def create_summary_panel(cards: List[ObservabilityCard]) -> Panel:
    """创建摘要面板"""
    total = len(cards)
    
    # 按 stage 统计
    by_stage: Dict[str, int] = {}
    for card in cards:
        by_stage[card.stage] = by_stage.get(card.stage, 0) + 1
    
    # 按 owner 统计
    by_owner: Dict[str, int] = {}
    for card in cards:
        by_owner[card.owner] = by_owner.get(card.owner, 0) + 1
    
    # 活跃任务（running + dispatch）
    active = by_stage.get("running", 0) + by_stage.get("dispatch", 0)
    # 完成/失败
    completed = by_stage.get("completed", 0)
    failed = by_stage.get("failed", 0)
    
    # 构建摘要文本
    text = Text()
    text.append(f"任务总数：{total}\n", style="bold")
    text.append(f"活跃：{active} ", style="yellow")
    text.append(f"完成：{completed} ", style="green")
    text.append(f"失败：{failed}\n", style="red")
    text.append("\n按 Owner 统计:\n", style="bold")
    for owner, count in sorted(by_owner.items()):
        text.append(f"  {owner}: {count}\n", style="cyan")
    
    return Panel(text, title="[bold]📊 任务摘要[/bold]", border_style="blue")


def create_stage_table(cards: List[ObservabilityCard]) -> Table:
    """按 stage 分组的任务表"""
    table = Table(
        title="[bold]📋 按阶段分组[/bold]",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold magenta",
    )
    
    # 添加列
    table.add_column("Stage", style="cyan", width=12)
    table.add_column("任务数", justify="right", width=8)
    table.add_column("任务 ID", style="white", width=40)
    table.add_column("Owner", style="green", width=10)
    table.add_column("心跳", style="yellow", width=10)
    
    # 按 stage 分组
    by_stage: Dict[str, List[ObservabilityCard]] = {}
    for card in cards:
        if card.stage not in by_stage:
            by_stage[card.stage] = []
        by_stage[card.stage].append(card)
    
    # 按预定顺序显示 stage
    stage_order = ["planning", "dispatch", "running", "callback_received", "closeout", "completed", "failed", "cancelled"]
    
    for stage in stage_order:
        if stage not in by_stage:
            continue
        
        stage_cards = by_stage[stage]
        color = STAGE_COLORS.get(stage, "white")
        
        # 第一个卡片显示 stage 名称，其他留空
        for i, card in enumerate(stage_cards[:5]):  # 每个 stage 最多显示 5 个
            stage_display = f"[{color}]{stage}[/{color}]" if i == 0 else ""
            table.add_row(
                stage_display,
                str(len(stage_cards)) if i == 0 else "",
                card.task_id[:35],
                card.owner,
                format_heartbeat(card.heartbeat),
            )
        
        if len(stage_cards) > 5:
            table.add_row("", f"[dim]+{len(stage_cards) - 5} 更多...[/dim]", "", "", "")
    
    return table


def create_active_tasks_table(cards: List[ObservabilityCard]) -> Table:
    """最近活跃任务列表"""
    table = Table(
        title="[bold]🔥 最近活跃任务[/bold]",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold magenta",
    )
    
    # 添加列
    table.add_column("Task ID", style="cyan", width=30)
    table.add_column("Scenario", style="white", width=15)
    table.add_column("Owner", style="green", width=10)
    table.add_column("Executor", style="blue", width=10)
    table.add_column("Stage", width=12)
    table.add_column("心跳", style="yellow", width=10)
    table.add_column("ETA", width=12)
    table.add_column("Anchor", style="dim", width=25)
    
    # 按心跳排序，取最近 15 个
    sorted_cards = sorted(cards, key=lambda c: c.heartbeat, reverse=True)[:15]
    
    for card in sorted_cards:
        stage_color = STAGE_COLORS.get(card.stage, "white")
        eta_color = get_eta_color(
            card.promise_anchor.get("promised_eta") if card.promise_anchor else None,
            card.heartbeat
        )
        
        table.add_row(
            card.task_id[:28],
            card.scenario,
            card.owner,
            card.executor,
            f"[{stage_color}]{card.stage}[/{stage_color}]",
            format_heartbeat(card.heartbeat),
            f"[{eta_color}]{format_eta(card.promise_anchor.get('promised_eta') if card.promise_anchor else None)}[/{eta_color}]",
            get_anchor_display(card),
        )
    
    return table


def create_owner_summary(cards: List[ObservabilityCard]) -> Table:
    """按 owner 分组统计"""
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
    table.add_column("Completed", justify="right", width=12, style="green")
    table.add_column("Failed", justify="right", width=8, style="red")
    
    # 按 owner 统计
    by_owner: Dict[str, Dict[str, int]] = {}
    for card in cards:
        if card.owner not in by_owner:
            by_owner[card.owner] = {"total": 0, "running": 0, "dispatch": 0, "completed": 0, "failed": 0}
        by_owner[card.owner]["total"] += 1
        if card.stage == "running":
            by_owner[card.owner]["running"] += 1
        elif card.stage == "dispatch":
            by_owner[card.owner]["dispatch"] += 1
        elif card.stage == "completed":
            by_owner[card.owner]["completed"] += 1
        elif card.stage == "failed":
            by_owner[card.owner]["failed"] += 1
    
    for owner, stats in sorted(by_owner.items()):
        table.add_row(
            owner,
            str(stats["total"]),
            str(stats["running"]),
            str(stats["dispatch"]),
            str(stats["completed"]),
            str(stats["failed"]),
        )
    
    return table


def render_dashboard(cards: List[ObservabilityCard]) -> Layout:
    """渲染完整看板布局"""
    layout = Layout()
    
    # 分割为三行：摘要 / 阶段表 / 活跃任务
    layout.split_column(
        Layout(name="header", size=12),
        Layout(name="middle", ratio=2),
        Layout(name="bottom", ratio=3),
    )
    
    # 中间部分再分为左右两列
    layout["middle"].split_row(
        Layout(name="stage", ratio=2),
        Layout(name="owner", ratio=1),
    )
    
    # 填充内容
    layout["header"].update(create_summary_panel(cards))
    layout["stage"].update(create_stage_table(cards))
    layout["owner"].update(create_owner_summary(cards))
    layout["bottom"].update(create_active_tasks_table(cards))
    
    return layout


class Dashboard:
    """可视化看板类"""
    
    def __init__(self, refresh_interval: float = 5.0, card_dir: Optional[Path] = None):
        """
        初始化看板
        
        Args:
            refresh_interval: 刷新间隔（秒）
            card_dir: 卡片目录（默认：CARD_DIR）
        """
        self.refresh_interval = refresh_interval
        self.card_dir = card_dir or CARD_DIR
        self.console = Console()
        self.manager = ObservabilityCardManager(card_dir=self.card_dir)
    
    def load_cards(self) -> List[ObservabilityCard]:
        """加载所有卡片"""
        return list_cards(limit=1000)
    
    def render_once(self) -> None:
        """渲染单次快照"""
        cards = self.load_cards()
        layout = render_dashboard(cards)
        self.console.print(layout)
    
    def export_snapshot(self, output_path: str) -> str:
        """导出 JSON 快照"""
        snapshot = generate_board_snapshot()
        
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2, ensure_ascii=False)
        
        return output_path
    
    def run_live(self) -> None:
        """运行实时刷新看板"""
        def generate_layout() -> Layout:
            cards = self.load_cards()
            return render_dashboard(cards)
        
        with Live(generate_layout(), console=self.console, refresh_per_second=1, screen=True) as live:
            while True:
                time.sleep(self.refresh_interval)
                live.update(generate_layout())


def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(
        description="编排系统可视化看板 - Batch 6",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python dashboard.py                    # 实时看板（5 秒刷新）
  python dashboard.py --refresh 10       # 10 秒刷新
  python dashboard.py --once             # 单次快照
  python dashboard.py --export out.json  # 导出 JSON
        """,
    )
    
    parser.add_argument(
        "--refresh", "-r",
        type=float,
        default=5.0,
        help="刷新间隔（秒），默认 5.0"
    )
    
    parser.add_argument(
        "--once", "-o",
        action="store_true",
        help="单次快照模式（不刷新）"
    )
    
    parser.add_argument(
        "--export", "-e",
        type=str,
        metavar="PATH",
        help="导出 JSON 快照到指定路径"
    )
    
    parser.add_argument(
        "--card-dir", "-d",
        type=Path,
        default=None,
        help="状态卡目录（默认：~/.openclaw/shared-context/observability/cards）"
    )
    
    args = parser.parse_args()
    
    # 创建看板
    dashboard = Dashboard(refresh_interval=args.refresh, card_dir=args.card_dir)
    
    # 导出模式
    if args.export:
        output_path = dashboard.export_snapshot(args.export)
        print(f"✅ 快照已导出：{output_path}")
        return 0
    
    # 单次快照模式
    if args.once:
        dashboard.render_once()
        return 0
    
    # 实时刷新模式
    try:
        dashboard.run_live()
    except KeyboardInterrupt:
        print("\n👋 看板已退出")
        return 0
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
