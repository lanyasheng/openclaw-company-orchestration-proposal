#!/usr/bin/env python3
"""
tmux_status_sync.py — 编排系统透明度/可视化 Batch 3

目标：将 tmux session 状态纳入 observability 统一索引。

核心能力：
1. 从 tmux session 读取状态（running/idle/likely_done/stuck/dead）
2. 自动同步到 observability cards 索引
3. 支持 local 和 ssh 远程 tmux session
4. 与 start-tmux-task.sh / status-tmux-task.sh 集成

使用示例：
```python
from tmux_status_sync import (
    TmuxStatusSync,
    sync_tmux_session,
    get_tmux_status,
    register_tmux_card,
)

# 同步单个 tmux session
sync_tmux_session(
    label="feature-xxx",
    session="cc-feature-xxx",
    task_id="task_001",
    owner="main",
    scenario="custom",
)

# 获取 tmux 状态
status = get_tmux_status(session="cc-feature-xxx")

# 注册新的 tmux 任务卡
card = register_tmux_card(
    task_id="task_002",
    label="bug-fix",
    owner="trading",
    scenario="trading_roundtable",
    promised_eta="2026-03-28T18:00:00",
)
```
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

from observability_card import (
    CARD_DIR,
    CardOwner,
    CardScenario,
    CardStage,
    ObservabilityCard,
    ObservabilityCardManager,
    _ensure_dirs,
    _iso_now,
    create_card,
    get_card,
    list_cards,
    update_card,
)

__all__ = [
    "TmuxStatusSync",
    "sync_tmux_session",
    "get_tmux_status",
    "register_tmux_card",
    "update_tmux_card",
    "list_tmux_cards",
    "TMUX_STATUS_MAP",
    "TMUX_SOCKET_DIR",
]

# tmux 状态映射到统一状态语言
TMUX_STATUS_MAP: Dict[str, CardStage] = {
    "running": "running",
    "idle": "idle",
    "likely_done": "completed",
    "done_session_ended": "completed",
    "stuck": "running",  # stuck 仍视为 running 但需要告警
    "dead": "failed",
    "input_pending": "dispatch",
    "submitted_scrollback": "running",
    "input_cleared": "running",
    "report_ready": "completed",
}

# 默认 tmux socket 目录
TMUX_SOCKET_DIR = Path(os.environ.get("TMPDIR", "/tmp")) / "clawdbot-tmux-sockets"


def _ensure_tmux_dirs():
    """确保 tmux 相关目录存在"""
    TMUX_SOCKET_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class TmuxSessionState:
    """
    tmux session 状态
    
    字段：
    - session: session 名称
    - status: 原始 tmux 状态
    - mapped_stage: 映射后的统一阶段
    - report_exists: 报告文件是否存在
    - session_alive: session 是否存活
    - last_checked: 最后检查时间
    - metadata: 额外元数据
    """
    session: str
    status: str
    mapped_stage: CardStage
    report_exists: bool
    session_alive: bool
    last_checked: str
    metadata: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "session": self.session,
            "status": self.status,
            "mapped_stage": self.mapped_stage,
            "report_exists": self.report_exists,
            "session_alive": self.session_alive,
            "last_checked": self.last_checked,
            "metadata": self.metadata,
        }


class TmuxStatusSync:
    """
    tmux 状态同步器
    
    核心方法：
    - get_status(session, socket, target, ssh_host): 获取 tmux session 状态
    - sync_to_card(task_id, session, socket, target, ssh_host): 同步到状态卡
    - register_task(task_id, label, owner, scenario, ...): 注册新任务
    - list_active_sessions(): 列出所有活跃的 tmux session
    """
    
    def __init__(self, socket_dir: Optional[Path] = None):
        """
        初始化同步器
        
        Args:
            socket_dir: tmux socket 目录（默认：TMUX_SOCKET_DIR）
        """
        self.socket_dir = socket_dir or TMUX_SOCKET_DIR
        _ensure_tmux_dirs()
        _ensure_dirs()  # 确保 observability 目录存在
        self.card_manager = ObservabilityCardManager()
    
    def get_status(
        self,
        session: str,
        socket: Optional[Path] = None,
        target: Literal["local", "ssh"] = "local",
        ssh_host: Optional[str] = None,
    ) -> TmuxSessionState:
        """
        获取 tmux session 状态
        
        Args:
            session: session 名称
            socket: socket 文件路径（可选）
            target: 目标类型（local/ssh）
            ssh_host: SSH 主机别名（target=ssh 时必需）
        
        Returns:
            TmuxSessionState 对象
        """
        if socket is None:
            socket = self.socket_dir / "clawdbot.sock"
        
        if target == "ssh" and not ssh_host:
            raise ValueError("target=ssh requires ssh_host")
        
        # 1. 检查 session 是否存在
        session_alive = self._check_session_alive(session, socket, target, ssh_host)
        
        # 2. 检查报告文件是否存在
        report_json = Path("/tmp") / f"{session}-completion-report.json"
        report_md = Path("/tmp") / f"{session}-completion-report.md"
        
        if target == "ssh":
            report_exists = self._check_remote_files_exist(ssh_host, [report_json, report_md])
        else:
            report_exists = report_json.exists() or report_md.exists()
        
        # 3. 如果 session 不存在，根据报告判断状态
        if not session_alive:
            if report_exists:
                status = "done_session_ended"
            else:
                status = "dead"
            
            return TmuxSessionState(
                session=session,
                status=status,
                mapped_stage=TMUX_STATUS_MAP.get(status, "failed"),
                report_exists=report_exists,
                session_alive=False,
                last_checked=_iso_now(),
                metadata={"reason": "session_not_found"},
            )
        
        # 4. 如果报告存在，视为 likely_done
        if report_exists:
            return TmuxSessionState(
                session=session,
                status="likely_done",
                mapped_stage="completed",
                report_exists=True,
                session_alive=True,
                last_checked=_iso_now(),
                metadata={"reason": "report_exists"},
            )
        
        # 5. 检查 pane 输出信号
        pane_output = self._capture_pane_output(session, socket, target, ssh_host)
        status = self._classify_pane_status(pane_output)
        
        return TmuxSessionState(
            session=session,
            status=status,
            mapped_stage=TMUX_STATUS_MAP.get(status, "running"),
            report_exists=False,
            session_alive=True,
            last_checked=_iso_now(),
            metadata={
                "pane_output_length": len(pane_output) if pane_output else 0,
            },
        )
    
    def sync_to_card(
        self,
        task_id: str,
        session: str,
        socket: Optional[Path] = None,
        target: Literal["local", "ssh"] = "local",
        ssh_host: Optional[str] = None,
        force: bool = False,
    ) -> Optional[ObservabilityCard]:
        """
        同步 tmux session 状态到状态卡
        
        Args:
            task_id: 任务 ID
            session: session 名称
            socket: socket 文件路径（可选）
            target: 目标类型（local/ssh）
            ssh_host: SSH 主机别名
            force: 强制更新（即使卡片不存在也创建）
        
        Returns:
            更新后的状态卡，失败返回 None
        """
        # 获取 tmux 状态
        tmux_state = self.get_status(session, socket, target, ssh_host)
        
        # 检查卡片是否存在
        card = self.card_manager.get_card(task_id)
        
        if card is None:
            if not force:
                return None
            
            # 创建新卡片（需要额外信息）
            # 这里返回 None，调用方应使用 register_tmux_card
            return None
        
        # 更新卡片
        attach_info = {
            "session_id": session,
            "tmux_socket": str(socket),
            "tmux_target": target,
            "tmux_ssh_host": ssh_host,
            "report_path": f"/tmp/{session}-completion-report.md",
        }
        
        updated = self.card_manager.update_card(
            task_id=task_id,
            stage=tmux_state.mapped_stage,
            heartbeat=tmux_state.last_checked,
            attach_info=attach_info,
            metadata={
                "tmux_status": tmux_state.status,
                "tmux_session_alive": tmux_state.session_alive,
                "tmux_report_exists": tmux_state.report_exists,
            },
        )
        
        return updated
    
    def register_task(
        self,
        task_id: str,
        label: str,
        owner: CardOwner,
        scenario: CardScenario,
        promised_eta: str,
        anchor_type: str = "tmux_session",
        socket: Optional[Path] = None,
        target: Literal["local", "ssh"] = "local",
        ssh_host: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ObservabilityCard:
        """
        注册新的 tmux 任务卡
        
        Args:
            task_id: 任务 ID
            label: 任务标签
            owner: 负责 agent
            scenario: 场景类型
            promised_eta: 承诺完成时间（ISO-8601）
            anchor_type: 锚点类型（默认：tmux_session）
            socket: socket 文件路径
            target: 目标类型
            ssh_host: SSH 主机别名
            metadata: 额外元数据
        
        Returns:
            创建的状态卡
        """
        if socket is None:
            socket = self.socket_dir / "clawdbot.sock"
        
        session = f"cc-{label}" if not label.startswith("cc-") else label
        
        card = self.card_manager.create_card(
            task_id=task_id,
            scenario=scenario,
            owner=owner,
            executor="tmux",
            stage="dispatch",
            promised_eta=promised_eta,
            anchor_type=anchor_type,
            anchor_value=session,
            metadata=metadata or {},
        )
        
        # 初始化 attach_info 并返回更新后的卡片
        updated_card = self.card_manager.update_card(
            task_id=task_id,
            attach_info={
                "session_id": session,
                "tmux_socket": str(socket),
                "tmux_target": target,
                "tmux_ssh_host": ssh_host,
            },
        )
        
        return updated_card if updated_card else card
    
    def list_active_sessions(
        self,
        owner: Optional[CardOwner] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        列出所有活跃的 tmux session
        
        Args:
            owner: 按 owner 过滤（可选）
            limit: 最大返回数量
        
        Returns:
            session 状态列表
        """
        # 查询所有 tmux executor 的卡片
        cards = list_cards(owner=owner, limit=limit)
        tmux_cards = [c for c in cards if c.executor == "tmux"]
        
        results = []
        for card in tmux_cards:
            session = card.attach_info.get("session_id", "")
            if not session:
                continue
            
            socket_str = card.attach_info.get("tmux_socket")
            socket = Path(socket_str) if socket_str else None
            target = card.attach_info.get("tmux_target", "local")
            ssh_host = card.attach_info.get("tmux_ssh_host")
            
            try:
                state = self.get_status(session, socket, target, ssh_host)
                results.append({
                    "task_id": card.task_id,
                    "session": session,
                    "state": state.to_dict(),
                    "card_stage": card.stage,
                })
            except Exception as e:
                results.append({
                    "task_id": card.task_id,
                    "session": session,
                    "error": str(e),
                })
        
        return results
    
    def _check_session_alive(
        self,
        session: str,
        socket: Path,
        target: Literal["local", "ssh"],
        ssh_host: Optional[str],
    ) -> bool:
        """检查 session 是否存活"""
        try:
            if target == "ssh":
                result = subprocess.run(
                    ["ssh", "-o", "BatchMode=yes", ssh_host,
                     "tmux", "-S", str(socket), "has-session", "-t", session],
                    capture_output=True,
                    timeout=5,
                )
            else:
                result = subprocess.run(
                    ["tmux", "-S", str(socket), "has-session", "-t", session],
                    capture_output=True,
                    timeout=5,
                )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, Exception):
            return False
    
    def _check_remote_files_exist(
        self,
        ssh_host: Optional[str],
        paths: List[Path],
    ) -> bool:
        """检查远程文件是否存在"""
        if not ssh_host:
            return False
        
        try:
            cmd = " && ".join([f"test -f '{p}'" for p in paths])
            result = subprocess.run(
                ["ssh", "-o", "BatchMode=yes", ssh_host, "bash", "-c", cmd],
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, Exception):
            return False
    
    def _capture_pane_output(
        self,
        session: str,
        socket: Path,
        target: Literal["local", "ssh"],
        ssh_host: Optional[str],
    ) -> str:
        """捕获 pane 输出"""
        try:
            if target == "ssh":
                result = subprocess.run(
                    ["ssh", "-o", "BatchMode=yes", ssh_host,
                     "tmux", "-S", str(socket), "capture-pane", "-p", "-J",
                     "-t", f"{session}:0.0", "-S", "-50"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
            else:
                result = subprocess.run(
                    ["tmux", "-S", str(socket), "capture-pane", "-p", "-J",
                     "-t", f"{session}:0.0", "-S", "-50"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
            return result.stdout or ""
        except (subprocess.TimeoutExpired, Exception):
            return ""
    
    def _classify_pane_status(self, pane_output: str) -> str:
        """根据 pane 输出分类状态"""
        if not pane_output:
            return "running"
        
        # 完成信号
        completion_signals = [
            "REPORT_JSON=", "WAKE_SENT=", "Co-Authored-By:",
            "completion-report", "Task Completed",
        ]
        for signal in completion_signals:
            if signal in pane_output:
                return "likely_done"
        
        # 错误信号
        error_signals = ["✗", "Error:", "FAILED", "fatal:"]
        for signal in error_signals:
            if signal in pane_output:
                return "stuck"
        
        # 执行信号
        execution_signals = [
            "Envisioning", "Thinking", "Running", "✽", "Mustering",
            "Read", "Bash(", "Edit(", "Write(",
        ]
        for signal in execution_signals:
            if signal in pane_output:
                return "running"
        
        # 空闲信号
        if "❯" in pane_output:
            return "idle"
        
        return "running"


# 便捷函数
def get_tmux_status(
    session: str,
    socket: Optional[Path] = None,
    target: Literal["local", "ssh"] = "local",
    ssh_host: Optional[str] = None,
) -> TmuxSessionState:
    """获取 tmux session 状态（便捷函数）"""
    syncer = TmuxStatusSync()
    return syncer.get_status(session, socket, target, ssh_host)


def sync_tmux_session(
    task_id: str,
    session: str,
    socket: Optional[Path] = None,
    target: Literal["local", "ssh"] = "local",
    ssh_host: Optional[str] = None,
    force: bool = False,
) -> Optional[ObservabilityCard]:
    """同步 tmux session 到状态卡（便捷函数）"""
    syncer = TmuxStatusSync()
    return syncer.sync_to_card(task_id, session, socket, target, ssh_host, force)


def register_tmux_card(
    task_id: str,
    label: str,
    owner: CardOwner,
    scenario: CardScenario,
    promised_eta: str,
    socket: Optional[Path] = None,
    target: Literal["local", "ssh"] = "local",
    ssh_host: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> ObservabilityCard:
    """注册 tmux 任务卡（便捷函数）"""
    syncer = TmuxStatusSync()
    return syncer.register_task(
        task_id, label, owner, scenario, promised_eta,
        socket=socket, target=target, ssh_host=ssh_host, metadata=metadata,
    )


def update_tmux_card(
    task_id: str,
    session: str,
    socket: Optional[Path] = None,
    target: Literal["local", "ssh"] = "local",
    ssh_host: Optional[str] = None,
) -> Optional[ObservabilityCard]:
    """更新 tmux 任务卡状态（便捷函数）"""
    syncer = TmuxStatusSync()
    return syncer.sync_to_card(task_id, session, socket, target, ssh_host)


def list_tmux_cards(
    owner: Optional[CardOwner] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """列出活跃的 tmux session（便捷函数）"""
    syncer = TmuxStatusSync()
    return syncer.list_active_sessions(owner=owner, limit=limit)


if __name__ == "__main__":
    # 简单测试
    print("Tmux Status Sync - Quick Test")
    print("=" * 50)
    
    # 测试注册
    try:
        card = register_tmux_card(
            task_id="test_tmux_001",
            label="test-sync",
            owner="main",
            scenario="custom",
            promised_eta="2026-03-28T18:00:00",
        )
        print(f"Registered tmux card: {card.task_id}")
        print(f"  executor: {card.executor}")
        print(f"  anchor: {card.promise_anchor}")
    except Exception as e:
        print(f"Register failed (expected if card exists): {e}")
    
    # 测试获取状态
    try:
        state = get_tmux_status(session="cc-test-sync")
        print(f"Session status: {state.status} -> {state.mapped_stage}")
    except Exception as e:
        print(f"Status check: {e}")
    
    # 测试列表
    active = list_tmux_cards(owner="main", limit=10)
    print(f"Active tmux sessions: {len(active)}")
    
    print("Test completed!")
