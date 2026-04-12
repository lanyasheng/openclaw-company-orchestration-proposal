#!/usr/bin/env python3
"""
observability_card.py — 编排系统透明度/可视化 Batch 1

目标：实现状态卡 CRUD 系统，支持任务进度追踪和可视化。

核心能力：
1. 创建/读取/更新/删除状态卡
2. 按 owner/scenario/stage 查询卡片
3. 生成任务看板快照
4. 与 subagent_state / completion_receipt 集成

这是 Batch 1 实现，后续批次将增加：
- Batch 2: 行为约束钩子（承诺即执行校验）
- Batch 3: tmux 统一状态索引
- Batch 4: 可视化看板（Web/TUI）

使用示例：
```python
from observability_card import (
    ObservabilityCardManager,
    create_card,
    get_card,
    update_card,
    list_cards,
    generate_board_snapshot,
)

# 创建状态卡
card = create_card(
    task_id="task_001",
    batch_id="batch_001",
    scenario="trading_roundtable",
    owner="trading",
    executor="subagent",
    stage="dispatch",
    promised_eta="2026-03-28T16:00:00",
    anchor_type="session_id",
    anchor_value="cc-feature-xxx",
)

# 更新状态
update_card(task_id="task_001", stage="running", heartbeat="2026-03-28T15:30:00")

# 查询卡片
cards = list_cards(owner="trading", stage="running")

# 生成看板快照
snapshot = generate_board_snapshot()
```
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

__all__ = [
    "CARD_VERSION",
    "CardStage",
    "CardExecutor",
    "ObservabilityCard",
    "ObservabilityCardManager",
    "create_card",
    "get_card",
    "update_card",
    "delete_card",
    "list_cards",
    "generate_board_snapshot",
    "CARD_DIR",
    "INDEX_DIR",
    "BOARD_DIR",
]

CARD_VERSION = "observability_card_v1"

# 存储目录
OBSERVABILITY_BASE_DIR = Path(
    os.environ.get(
        "OPENCLAW_OBSERVABILITY_DIR",
        Path.home() / ".openclaw" / "shared-context" / "observability",
    )
)

CARD_DIR = OBSERVABILITY_BASE_DIR / "cards"
INDEX_DIR = OBSERVABILITY_BASE_DIR / "index"
BOARD_DIR = OBSERVABILITY_BASE_DIR / "boards"

# 枚举类型
CardStage = Literal[
    "planning",
    "dispatch",
    "running",
    "idle",
    "callback_received",
    "closeout",
    "completed",
    "failed",
    "cancelled",
]

CardExecutor = Literal["subagent", "tmux", "browser", "message", "cron", "manual"]

CardOwner = Literal["main", "trading", "ainews", "macro", "content", "butler", "custom"]

CardScenario = Literal[
    "trading_roundtable",
    "channel_roundtable",
    "coding_issue",
    "workflow_dag",
    "custom",
]


def _ensure_dirs():
    """确保所有目录存在"""
    CARD_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    BOARD_DIR.mkdir(parents=True, exist_ok=True)


def _iso_now() -> str:
    """返回当前 ISO-8601 时间戳"""
    return datetime.now(timezone.utc).isoformat()


def _card_file(task_id: str) -> Path:
    """返回状态卡文件路径"""
    _ensure_dirs()
    return CARD_DIR / f"{task_id}.json"


def _index_file(owner: str) -> Path:
    """返回索引文件路径（按 owner 分片）"""
    _ensure_dirs()
    return INDEX_DIR / f"{owner}.jsonl"


def _board_file(date_str: Optional[str] = None) -> Path:
    """返回看板快照文件路径"""
    _ensure_dirs()
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
    return BOARD_DIR / f"board-{date_str}.json"


@dataclass
class ObservabilityCard:
    """
    可观测性状态卡
    
    核心字段：
    - task_id: 任务唯一 ID
    - batch_id: 批次 ID（可选）
    - scenario: 场景类型
    - owner: 负责 agent
    - executor: 执行后端
    - stage: 当前阶段
    - heartbeat: 最后心跳时间
    - recent_output: 最近输出摘要
    - attach_info: 附加信息（session/report/log 路径）
    - gate_state: Gate 状态
    - promise_anchor: 承诺锚点
    - metrics: 时间指标
    """
    task_id: str
    scenario: CardScenario
    owner: CardOwner
    executor: CardExecutor
    stage: CardStage
    heartbeat: str
    card_version: str = CARD_VERSION
    batch_id: Optional[str] = None
    recent_output: str = ""
    attach_info: Dict[str, Any] = field(default_factory=dict)
    gate_state: Optional[Dict[str, Any]] = None
    promise_anchor: Optional[Dict[str, Any]] = None
    metrics: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "card_version": self.card_version,
            "task_id": self.task_id,
            "batch_id": self.batch_id,
            "scenario": self.scenario,
            "owner": self.owner,
            "executor": self.executor,
            "stage": self.stage,
            "heartbeat": self.heartbeat,
            "recent_output": self.recent_output,
            "attach_info": self.attach_info,
            "gate_state": self.gate_state,
            "promise_anchor": self.promise_anchor,
            "metrics": self.metrics,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ObservabilityCard":
        """从字典创建"""
        return cls(
            card_version=data.get("card_version", CARD_VERSION),
            task_id=data.get("task_id", ""),
            batch_id=data.get("batch_id"),
            scenario=data.get("scenario", "custom"),
            owner=data.get("owner", "custom"),
            executor=data.get("executor", "manual"),
            stage=data.get("stage", "planning"),
            heartbeat=data.get("heartbeat", _iso_now()),
            recent_output=data.get("recent_output", ""),
            attach_info=data.get("attach_info", {}),
            gate_state=data.get("gate_state"),
            promise_anchor=data.get("promise_anchor"),
            metrics=data.get("metrics", {}),
            metadata=data.get("metadata", {}),
        )


class ObservabilityCardManager:
    """
    状态卡管理器
    
    核心方法：
    - create_card(...): 创建状态卡
    - get_card(task_id): 获取状态卡
    - update_card(task_id, **kwargs): 更新状态卡
    - delete_card(task_id): 删除状态卡
    - list_cards(owner=None, scenario=None, stage=None): 查询卡片
    - generate_board_snapshot(): 生成看板快照
    """
    
    def __init__(self, card_dir: Optional[Path] = None):
        """
        初始化管理器
        
        Args:
            card_dir: 卡片目录（默认：CARD_DIR）
        """
        self.card_dir = card_dir or CARD_DIR
        _ensure_dirs()
    
    def create_card(
        self,
        task_id: str,
        scenario: CardScenario,
        owner: CardOwner,
        executor: CardExecutor,
        stage: CardStage,
        promised_eta: str,
        anchor_type: str,
        anchor_value: str,
        batch_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ObservabilityCard:
        """
        创建状态卡
        
        Args:
            task_id: 任务 ID
            scenario: 场景类型
            owner: 负责 agent
            executor: 执行后端
            stage: 初始阶段
            promised_eta: 承诺完成时间（ISO-8601）
            anchor_type: 锚点类型（dispatch_id/session_id/tmux_session）
            anchor_value: 锚点值
            batch_id: 批次 ID（可选）
            metadata: 额外元数据
        
        Returns:
            创建的状态卡
        """
        now = _iso_now()
        
        card = ObservabilityCard(
            task_id=task_id,
            scenario=scenario,
            owner=owner,
            executor=executor,
            stage=stage,
            heartbeat=now,
            batch_id=batch_id,
            promise_anchor={
                "promised_at": now,
                "promised_eta": promised_eta,
                "anchor_type": anchor_type,
                "anchor_value": anchor_value,
            },
            metrics={
                "created_at": now,
                "started_at": None,
                "completed_at": None,
                "duration_seconds": 0,
                "retry_count": 0,
            },
            metadata=metadata or {},
        )
        
        # 原子写入
        card_path = _card_file(task_id)
        tmp_file = card_path.with_suffix(".tmp")
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(card.to_dict(), f, indent=2, ensure_ascii=False)
        tmp_file.replace(card_path)
        
        # 更新索引
        self._append_to_index(card)
        
        return card
    
    def get_card(self, task_id: str) -> Optional[ObservabilityCard]:
        """
        获取状态卡
        
        Args:
            task_id: 任务 ID
        
        Returns:
            状态卡，不存在则返回 None
        """
        card_path = _card_file(task_id)
        if not card_path.exists():
            return None
        
        try:
            with open(card_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return ObservabilityCard.from_dict(data)
        except (json.JSONDecodeError, KeyError):
            return None
    
    def update_card(
        self,
        task_id: str,
        stage: Optional[CardStage] = None,
        heartbeat: Optional[str] = None,
        recent_output: Optional[str] = None,
        attach_info: Optional[Dict[str, Any]] = None,
        gate_state: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Optional[ObservabilityCard]:
        """
        更新状态卡
        
        Args:
            task_id: 任务 ID
            stage: 新阶段（可选）
            heartbeat: 新心跳时间（可选）
            recent_output: 最近输出摘要（可选）
            attach_info: 附加信息（可选）
            gate_state: Gate 状态（可选）
            **kwargs: 其他要更新的字段
        
        Returns:
            更新后的状态卡，不存在则返回 None
        """
        card = self.get_card(task_id)
        if card is None:
            return None
        
        # 更新字段
        if stage is not None:
            card.stage = stage
            # 自动更新 metrics
            if stage == "running" and card.metrics.get("started_at") is None:
                card.metrics["started_at"] = _iso_now()
            elif stage in ("completed", "failed", "cancelled"):
                card.metrics["completed_at"] = _iso_now()
                # 计算 duration
                if card.metrics.get("started_at"):
                    start = datetime.fromisoformat(card.metrics["started_at"])
                    end = datetime.fromisoformat(card.metrics["completed_at"])
                    card.metrics["duration_seconds"] = int((end - start).total_seconds())
        
        if heartbeat is not None:
            card.heartbeat = heartbeat
        
        if recent_output is not None:
            card.recent_output = recent_output
        
        if attach_info is not None:
            card.attach_info.update(attach_info)
        
        if gate_state is not None:
            card.gate_state = gate_state
        
        # 更新其他字段
        for key, value in kwargs.items():
            if hasattr(card, key):
                setattr(card, key, value)
            else:
                card.metadata[key] = value
        
        # 原子写入
        card_path = _card_file(task_id)
        tmp_file = card_path.with_suffix(".tmp")
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(card.to_dict(), f, indent=2, ensure_ascii=False)
        tmp_file.replace(card_path)
        
        # 更新索引（重新写入）
        self._rebuild_index_entry(card)
        
        return card
    
    def delete_card(self, task_id: str) -> bool:
        """
        删除状态卡
        
        Args:
            task_id: 任务 ID
        
        Returns:
            是否删除成功
        """
        card_path = _card_file(task_id)
        if not card_path.exists():
            return False
        
        # 读取卡片以获取 owner
        card = self.get_card(task_id)
        
        # 删除文件
        card_path.unlink()
        
        # 从索引移除（重建索引文件）
        if card:
            self._remove_from_index(task_id, card.owner)
        
        return True
    
    def list_cards(
        self,
        owner: Optional[CardOwner] = None,
        scenario: Optional[CardScenario] = None,
        stage: Optional[CardStage] = None,
        limit: int = 100,
    ) -> List[ObservabilityCard]:
        """
        查询状态卡
        
        Args:
            owner: 按 owner 过滤（可选）
            scenario: 按 scenario 过滤（可选）
            stage: 按 stage 过滤（可选）
            limit: 最大返回数量
        
        Returns:
            状态卡列表
        """
        cards = []
        
        # 遍历所有卡片文件
        for card_file in sorted(CARD_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            if len(cards) >= limit:
                break
            
            try:
                with open(card_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                card = ObservabilityCard.from_dict(data)
                
                # 过滤
                if owner and card.owner != owner:
                    continue
                if scenario and card.scenario != scenario:
                    continue
                if stage and card.stage != stage:
                    continue
                
                cards.append(card)
            except (json.JSONDecodeError, KeyError):
                continue
        
        return cards
    
    def generate_board_snapshot(self, date_str: Optional[str] = None) -> Dict[str, Any]:
        """
        生成任务看板快照
        
        Args:
            date_str: 日期字符串（YYYY-MM-DD），默认今天
        
        Returns:
            看板快照字典
        """
        now = _iso_now()
        if date_str is None:
            date_str = datetime.now().strftime("%Y-%m-%d")
        
        # 收集所有卡片
        all_cards = self.list_cards(limit=1000)
        
        # 按 stage 分组
        by_stage: Dict[str, List[Dict[str, Any]]] = {}
        for card in all_cards:
            stage = card.stage
            if stage not in by_stage:
                by_stage[stage] = []
            by_stage[stage].append(card.to_dict())
        
        # 按 owner 统计
        by_owner: Dict[str, int] = {}
        for card in all_cards:
            owner = card.owner
            by_owner[owner] = by_owner.get(owner, 0) + 1
        
        # 构建快照
        snapshot = {
            "snapshot_version": "board_snapshot_v1",
            "generated_at": now,
            "date": date_str,
            "summary": {
                "total_cards": len(all_cards),
                "by_stage": {stage: len(cards) for stage, cards in by_stage.items()},
                "by_owner": by_owner,
            },
            "cards_by_stage": by_stage,
            "all_cards": [card.to_dict() for card in all_cards],
        }
        
        # 保存快照
        snapshot_path = _board_file(date_str)
        tmp_file = snapshot_path.with_suffix(".tmp")
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2, ensure_ascii=False)
        tmp_file.replace(snapshot_path)
        
        return snapshot
    
    def _append_to_index(self, card: ObservabilityCard):
        """追加卡片到索引文件"""
        index_path = _index_file(card.owner)
        
        # 追加写入 JSONL
        with open(index_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"task_id": card.task_id, "updated_at": card.heartbeat}) + "\n")
    
    def _rebuild_index_entry(self, card: ObservabilityCard):
        """重建索引条目（更新时调用）"""
        # 简单实现：重建整个 owner 索引文件
        index_path = _index_file(card.owner)
        
        # 读取所有条目
        entries = []
        seen_task_ids = set()
        
        if index_path.exists():
            with open(index_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                        if entry["task_id"] not in seen_task_ids:
                            entries.append(entry)
                            seen_task_ids.add(entry["task_id"])
                    except json.JSONDecodeError:
                        continue
        
        # 更新或添加当前卡片
        seen_task_ids.discard(card.task_id)
        entries.append({"task_id": card.task_id, "updated_at": card.heartbeat})
        
        # 重写索引文件
        tmp_file = index_path.with_suffix(".tmp")
        with open(tmp_file, "w", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(entry) + "\n")
        tmp_file.replace(index_path)
    
    def _remove_from_index(self, task_id: str, owner: str):
        """从索引移除卡片"""
        index_path = _index_file(owner)
        if not index_path.exists():
            return
        
        # 读取所有条目，过滤掉要删除的
        entries = []
        with open(index_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                    if entry["task_id"] != task_id:
                        entries.append(entry)
                except json.JSONDecodeError:
                    continue
        
        # 重写索引文件
        tmp_file = index_path.with_suffix(".tmp")
        with open(tmp_file, "w", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(entry) + "\n")
        tmp_file.replace(index_path)


# 便捷函数
def create_card(
    task_id: str,
    scenario: CardScenario,
    owner: CardOwner,
    executor: CardExecutor,
    stage: CardStage,
    promised_eta: str,
    anchor_type: str,
    anchor_value: str,
    batch_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> ObservabilityCard:
    """创建状态卡（便捷函数）"""
    manager = ObservabilityCardManager()
    return manager.create_card(
        task_id=task_id,
        scenario=scenario,
        owner=owner,
        executor=executor,
        stage=stage,
        promised_eta=promised_eta,
        anchor_type=anchor_type,
        anchor_value=anchor_value,
        batch_id=batch_id,
        metadata=metadata,
    )


def get_card(task_id: str) -> Optional[ObservabilityCard]:
    """获取状态卡（便捷函数）"""
    manager = ObservabilityCardManager()
    return manager.get_card(task_id)


def update_card(
    task_id: str,
    stage: Optional[CardStage] = None,
    heartbeat: Optional[str] = None,
    recent_output: Optional[str] = None,
    attach_info: Optional[Dict[str, Any]] = None,
    gate_state: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> Optional[ObservabilityCard]:
    """更新状态卡（便捷函数）"""
    manager = ObservabilityCardManager()
    return manager.update_card(
        task_id=task_id,
        stage=stage,
        heartbeat=heartbeat,
        recent_output=recent_output,
        attach_info=attach_info,
        gate_state=gate_state,
        **kwargs,
    )


def delete_card(task_id: str) -> bool:
    """删除状态卡（便捷函数）"""
    manager = ObservabilityCardManager()
    return manager.delete_card(task_id)


def list_cards(
    owner: Optional[CardOwner] = None,
    scenario: Optional[CardScenario] = None,
    stage: Optional[CardStage] = None,
    limit: int = 100,
) -> List[ObservabilityCard]:
    """查询状态卡（便捷函数）"""
    manager = ObservabilityCardManager()
    return manager.list_cards(owner=owner, scenario=scenario, stage=stage, limit=limit)


def generate_board_snapshot(date_str: Optional[str] = None) -> Dict[str, Any]:
    """生成看板快照（便捷函数）"""
    manager = ObservabilityCardManager()
    return manager.generate_board_snapshot(date_str=date_str)


if __name__ == "__main__":
    # 简单测试
    print("Observability Card System - Quick Test")
    print("=" * 50)
    
    # 创建测试卡片
    card = create_card(
        task_id="test_task_001",
        scenario="custom",
        owner="main",
        executor="subagent",
        stage="dispatch",
        promised_eta="2026-03-28T16:00:00",
        anchor_type="session_id",
        anchor_value="cc-test-xxx",
    )
    print(f"Created card: {card.task_id}")
    
    # 更新卡片
    updated = update_card(
        task_id="test_task_001",
        stage="running",
        heartbeat=_iso_now(),
        recent_output="Task is running...",
    )
    print(f"Updated card stage: {updated.stage if updated else 'N/A'}")
    
    # 查询卡片
    cards = list_cards(owner="main", limit=10)
    print(f"Found {len(cards)} cards for owner=main")
    
    # 生成快照
    snapshot = generate_board_snapshot()
    print(f"Generated snapshot with {snapshot['summary']['total_cards']} cards")
    
    # 清理测试
    delete_card("test_task_001")
    print("Test completed!")
