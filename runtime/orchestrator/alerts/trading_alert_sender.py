#!/usr/bin/env python3
"""
trading_alert_sender.py — Trading Spider Alert Sender (Minimal Viable Chain)

最小可用提醒发送链：
1. 候选变化检测（去重）
2. 节流控制（频率限制）
3. 结构化 payload
4. 发送结果日志

设计原则：
- 不重复刷屏：基于 candidate_id + signal_type 去重
- 发送前有结构化 payload：统一 schema
- 发送结果可查：状态文件 + 日志文件

Usage:
    from orchestrator.alerts.trading_alert_sender import TradingAlertSender
    
    sender = TradingAlertSender()
    result = sender.send_candidate_alert(
        candidate_id="candidate_001",
        signal_type="buy_watch",
        symbol="000001.SZ",
        reason="趋势反转 + 量价共振",
        metadata={"score": 0.85, "sector": "金融"}
    )
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Literal

__all__ = [
    "TradingAlertSender",
    "AlertPayload",
    "SendResult",
    "ALERT_SENDER_VERSION",
]

ALERT_SENDER_VERSION = "trading_alert_sender_v1"

# 状态文件目录
ALERT_STATE_DIR = Path(
    os.environ.get(
        "TRADING_ALERT_STATE_DIR",
        Path.home() / ".openclaw" / "shared-context" / "trading-alerts" / "state",
    )
)
ALERT_LOG_DIR = Path(
    os.environ.get(
        "TRADING_ALERT_LOG_DIR",
        Path.home() / ".openclaw" / "shared-context" / "trading-alerts" / "logs",
    )
)

# 节流配置
DEFAULT_THROTTLE_WINDOW_SECONDS = 300  # 5 分钟内相同类型 alert 最多 1 条
DEFAULT_MAX_ALERTS_PER_WINDOW = 1

# Alert 类型
AlertType = Literal[
    "buy_watch",      # 买入观察
    "sell_watch",     # 卖出观察
    "hold_watch",     # 持仓观察
    "candidate_new",  # 新候选
    "candidate_update",  # 候选更新
    "candidate_remove",  # 候选移除
    "gate_pass",      # Gate 通过
    "gate_fail",      # Gate 失败
    "gate_conditional",  # Gate 条件通过
]


def _ensure_dirs():
    """确保目录存在"""
    ALERT_STATE_DIR.mkdir(parents=True, exist_ok=True)
    ALERT_LOG_DIR.mkdir(parents=True, exist_ok=True)


def _iso_now() -> str:
    """返回 ISO-8601 时间戳"""
    return datetime.now().isoformat()


def _generate_alert_id(candidate_id: str, signal_type: str, timestamp: str) -> str:
    """生成稳定 alert ID"""
    content = f"{candidate_id}:{signal_type}:{timestamp}"
    return f"alert_{hashlib.sha256(content.encode()).hexdigest()[:12]}"


def _state_file(alert_id: str) -> Path:
    """返回状态文件路径"""
    return ALERT_STATE_DIR / f"{alert_id}.json"


def _log_file() -> Path:
    """返回日志文件路径（按日期分片）"""
    date_str = datetime.now().strftime("%Y-%m-%d")
    return ALERT_LOG_DIR / f"alerts-{date_str}.jsonl"


def _dedup_key(candidate_id: str, signal_type: str) -> str:
    """生成去重 key"""
    return f"{candidate_id}:{signal_type}"


def _throttle_state_file() -> Path:
    """返回节流状态文件路径"""
    return ALERT_STATE_DIR / "throttle_state.json"


@dataclass
class AlertPayload:
    """
    Alert payload — 结构化发送内容。
    
    Schema:
    {
        "alert_version": "trading_alert_sender_v1",
        "alert_id": "alert_xxx",
        "timestamp": "2026-03-23T10:00:00",
        "candidate_id": "candidate_001",
        "signal_type": "buy_watch",
        "symbol": "000001.SZ",
        "reason": "趋势反转 + 量价共振",
        "metadata": {...},
        "sender": {"name": "trading_spider", "version": "v1"},
        "delivery": {"channel": "discord", "reply_to": "channel:xxx"}
    }
    """
    alert_id: str
    timestamp: str
    candidate_id: str
    signal_type: AlertType
    symbol: str
    reason: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    sender: Dict[str, str] = field(default_factory=lambda: {"name": "trading_spider", "version": ALERT_SENDER_VERSION})
    delivery: Dict[str, str] = field(default_factory=lambda: {"channel": "discord", "reply_to": ""})
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


@dataclass
class SendResult:
    """
    Send result — 发送结果。
    
    Schema:
    {
        "ok": true,
        "alert_id": "alert_xxx",
        "delivered": true,
        "timestamp": "2026-03-23T10:00:00",
        "dedup_skipped": false,
        "throttle_skipped": false,
        "error": null,
        "metadata": {...}
    }
    """
    ok: bool
    alert_id: str
    delivered: bool
    timestamp: str
    dedup_skipped: bool = False
    throttle_skipped: bool = False
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class TradingAlertSender:
    """
    Trading Alert Sender — 交易提醒发送器。
    
    提供：
    - send_candidate_alert(): 发送候选提醒
    - check_dedup(): 检查去重
    - check_throttle(): 检查节流
    - write_state(): 写入状态
    - write_log(): 写入日志
    """
    
    def __init__(
        self,
        throttle_window_seconds: int = DEFAULT_THROTTLE_WINDOW_SECONDS,
        max_alerts_per_window: int = DEFAULT_MAX_ALERTS_PER_WINDOW,
        enable_dedup: bool = True,
        enable_throttle: bool = True,
        dry_run: bool = False,
    ):
        self.throttle_window_seconds = throttle_window_seconds
        self.max_alerts_per_window = max_alerts_per_window
        self.enable_dedup = enable_dedup
        self.enable_throttle = enable_throttle
        self.dry_run = dry_run
        _ensure_dirs()
    
    def _load_throttle_state(self) -> Dict[str, Any]:
        """加载节流状态"""
        throttle_file = _throttle_state_file()
        if not throttle_file.exists():
            return {"windows": {}}
        try:
            return json.loads(throttle_file.read_text())
        except (json.JSONDecodeError, IOError):
            return {"windows": {}}
    
    def _save_throttle_state(self, state: Dict[str, Any]) -> None:
        """保存节流状态"""
        throttle_file = _throttle_state_file()
        tmp_file = throttle_file.with_suffix(".tmp")
        with open(tmp_file, "w") as f:
            json.dump(state, f, indent=2)
        tmp_file.replace(throttle_file)
    
    def _load_sent_alerts(self) -> Dict[str, str]:
        """加载已发送 alert 记录（用于去重）"""
        index_file = ALERT_STATE_DIR / "sent_alerts_index.json"
        if not index_file.exists():
            return {}
        try:
            return json.loads(index_file.read_text())
        except (json.JSONDecodeError, IOError):
            return {}
    
    def _save_sent_alert(self, dedup_key: str, alert_id: str, timestamp: str) -> None:
        """保存已发送 alert 记录"""
        index_file = ALERT_STATE_DIR / "sent_alerts_index.json"
        index = self._load_sent_alerts()
        index[dedup_key] = {"alert_id": alert_id, "timestamp": timestamp}
        tmp_file = index_file.with_suffix(".tmp")
        with open(tmp_file, "w") as f:
            json.dump(index, f, indent=2)
        tmp_file.replace(index_file)
    
    def check_dedup(self, candidate_id: str, signal_type: str) -> tuple[bool, Optional[str]]:
        """
        检查去重。
        
        Returns:
            (should_skip, reason): 是否应该跳过，跳过原因
        """
        if not self.enable_dedup:
            return False, None
        
        dedup_key = _dedup_key(candidate_id, signal_type)
        sent_alerts = self._load_sent_alerts()
        
        if dedup_key in sent_alerts:
            prev = sent_alerts[dedup_key]
            return True, f"duplicate_alert: previously sent as {prev['alert_id']} at {prev['timestamp']}"
        
        return False, None
    
    def check_throttle(self, signal_type: str) -> tuple[bool, Optional[str]]:
        """
        检查节流。
        
        Returns:
            (should_skip, reason): 是否应该跳过，跳过原因
        """
        if not self.enable_throttle:
            return False, None
        
        throttle_state = self._load_throttle_state()
        windows = throttle_state.get("windows", {})
        
        # 获取当前时间窗口
        now = datetime.now()
        window_key = f"{signal_type}:{now.strftime('%Y-%m-%d-%H-%M')}"
        
        # 检查窗口内发送次数
        window_data = windows.get(window_key, {"count": 0, "reset_at": ""})
        count = window_data.get("count", 0)
        
        if count >= self.max_alerts_per_window:
            return True, f"throttled: {count} alerts already sent in window {window_key}"
        
        return False, None
    
    def _update_throttle_state(self, signal_type: str) -> None:
        """更新节流状态"""
        throttle_state = self._load_throttle_state()
        now = datetime.now()
        window_key = f"{signal_type}:{now.strftime('%Y-%m-%d-%H-%M')}"
        
        if "windows" not in throttle_state:
            throttle_state["windows"] = {}
        
        if window_key not in throttle_state["windows"]:
            throttle_state["windows"][window_key] = {
                "count": 0,
                "started_at": _iso_now(),
                "reset_at": (now + timedelta(seconds=self.throttle_window_seconds)).isoformat(),
            }
        
        throttle_state["windows"][window_key]["count"] += 1
        self._save_throttle_state(throttle_state)
    
    def _write_state(self, alert_id: str, payload: AlertPayload, result: SendResult) -> Path:
        """写入状态文件"""
        state_file = _state_file(alert_id)
        state = {
            "alert_id": alert_id,
            "payload": payload.to_dict(),
            "result": result.to_dict(),
            "created_at": _iso_now(),
        }
        tmp_file = state_file.with_suffix(".tmp")
        with open(tmp_file, "w") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        tmp_file.replace(state_file)
        return state_file
    
    def _write_log(self, alert_id: str, payload: AlertPayload, result: SendResult) -> Path:
        """写入日志文件（JSONL）"""
        log_file = _log_file()
        log_entry = {
            "timestamp": _iso_now(),
            "alert_id": alert_id,
            "payload": payload.to_dict(),
            "result": result.to_dict(),
        }
        with open(log_file, "a") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
        return log_file
    
    def _deliver_message(self, payload: AlertPayload) -> Dict[str, Any]:
        """
        发送消息（真实发送逻辑）。
        
        当前实现：写入文件作为 Mock，后续可替换为真实 Discord API。
        """
        if self.dry_run:
            return {"status": "dry_run", "reason": "dry_run_enabled"}
        
        # 当前实现：写入通知文件（与 task-callback-bus 兼容）
        notification_file = ALERT_LOG_DIR / f"{payload.alert_id}.json"
        notification_data = {
            "alert_id": payload.alert_id,
            "channel": payload.delivery.get("channel", "discord"),
            "reply_to": payload.delivery.get("reply_to", ""),
            "message": self._format_message(payload),
            "timestamp": payload.timestamp,
            "payload": payload.to_dict(),
        }
        
        tmp_file = notification_file.with_suffix(".tmp")
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(notification_data, f, ensure_ascii=False, indent=2)
        tmp_file.replace(notification_file)
        
        return {
            "status": "sent",
            "reason": "delivered_to_file",
            "file": str(notification_file),
        }
    
    def _format_message(self, payload: AlertPayload) -> str:
        """格式化消息文本"""
        emoji_map = {
            "buy_watch": "👀",
            "sell_watch": "⚠️",
            "hold_watch": "📊",
            "candidate_new": "🆕",
            "candidate_update": "🔄",
            "candidate_remove": "❌",
            "gate_pass": "✅",
            "gate_fail": "❌",
            "gate_conditional": "🟡",
        }
        emoji = emoji_map.get(payload.signal_type, "📋")
        
        return f"""{emoji} 交易提醒

- 候选 ID: {payload.candidate_id}
- 标的：{payload.symbol}
- 类型：{payload.signal_type}
- 原因：{payload.reason}
- 时间：{payload.timestamp}

Metadata: {json.dumps(payload.metadata, ensure_ascii=False)}"""
    
    def send_candidate_alert(
        self,
        candidate_id: str,
        signal_type: AlertType,
        symbol: str,
        reason: str,
        metadata: Optional[Dict[str, Any]] = None,
        delivery_channel: str = "discord",
        reply_to: str = "",
    ) -> SendResult:
        """
        发送候选提醒。
        
        Args:
            candidate_id: 候选 ID
            signal_type: 信号类型
            symbol: 标的代码
            reason: 触发原因
            metadata: 额外元数据
            delivery_channel: 发送频道
            reply_to: 回复目标
        
        Returns:
            SendResult: 发送结果
        """
        timestamp = _iso_now()
        alert_id = _generate_alert_id(candidate_id, signal_type, timestamp)
        
        # Check 1: 去重检查
        should_skip_dedup, dedup_reason = self.check_dedup(candidate_id, signal_type)
        if should_skip_dedup:
            result = SendResult(
                ok=True,
                alert_id=alert_id,
                delivered=False,
                timestamp=timestamp,
                dedup_skipped=True,
                error=dedup_reason,
            )
            return result
        
        # Check 2: 节流检查
        should_skip_throttle, throttle_reason = self.check_throttle(signal_type)
        if should_skip_throttle:
            result = SendResult(
                ok=True,
                alert_id=alert_id,
                delivered=False,
                timestamp=timestamp,
                throttle_skipped=True,
                error=throttle_reason,
            )
            return result
        
        # 构建 payload
        payload = AlertPayload(
            alert_id=alert_id,
            timestamp=timestamp,
            candidate_id=candidate_id,
            signal_type=signal_type,
            symbol=symbol,
            reason=reason,
            metadata=metadata or {},
            delivery={"channel": delivery_channel, "reply_to": reply_to},
        )
        
        # 发送消息
        delivery_result = self._deliver_message(payload)
        delivered = delivery_result.get("status") == "sent"
        
        # 构建结果
        result = SendResult(
            ok=delivered or self.dry_run,
            alert_id=alert_id,
            delivered=delivered,
            timestamp=timestamp,
            metadata=delivery_result,
        )
        
        # 写入状态和日志
        if not self.dry_run:
            self._write_state(alert_id, payload, result)
            self._write_log(alert_id, payload, result)
            self._update_throttle_state(signal_type)
            self._save_sent_alert(_dedup_key(candidate_id, signal_type), alert_id, timestamp)
        
        return result
    
    def get_alert_state(self, alert_id: str) -> Optional[Dict[str, Any]]:
        """获取 alert 状态"""
        state_file = _state_file(alert_id)
        if not state_file.exists():
            return None
        try:
            return json.loads(state_file.read_text())
        except (json.JSONDecodeError, IOError):
            return None
    
    def list_recent_alerts(self, limit: int = 10) -> List[Dict[str, Any]]:
        """列出最近的 alert"""
        log_file = _log_file()
        if not log_file.exists():
            return []
        
        alerts = []
        with open(log_file, "r") as f:
            for line in f:
                if line.strip():
                    try:
                        alerts.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        
        return alerts[-limit:]


# 便捷函数
def send_alert(
    candidate_id: str,
    signal_type: AlertType,
    symbol: str,
    reason: str,
    metadata: Optional[Dict[str, Any]] = None,
    dry_run: bool = False,
) -> SendResult:
    """便捷发送函数"""
    sender = TradingAlertSender(dry_run=dry_run)
    return sender.send_candidate_alert(
        candidate_id=candidate_id,
        signal_type=signal_type,
        symbol=symbol,
        reason=reason,
        metadata=metadata,
    )


if __name__ == "__main__":
    # 测试运行
    import argparse
    
    parser = argparse.ArgumentParser(description="Trading Alert Sender Test")
    parser.add_argument("--dry-run", action="store_true", help="Dry run mode")
    parser.add_argument("--candidate-id", default="test_candidate_001", help="Candidate ID")
    parser.add_argument("--signal-type", default="buy_watch", help="Signal type")
    parser.add_argument("--symbol", default="000001.SZ", help="Symbol")
    parser.add_argument("--reason", default="测试提醒", help="Reason")
    
    args = parser.parse_args()
    
    result = send_alert(
        candidate_id=args.candidate_id,
        signal_type=args.signal_type,  # type: ignore
        symbol=args.symbol,
        reason=args.reason,
        dry_run=args.dry_run,
    )
    
    print(f"Alert sent: {result.to_dict()}")
