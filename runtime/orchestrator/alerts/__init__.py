"""
orchestrator.alerts — Trading Spider Alert System

最小可用提醒发送链：
- 去重：基于 candidate_id + signal_type
- 节流：时间窗口内限制发送次数
- 结构化 payload：统一 schema
- 可验证回执：状态文件 + 日志文件

Usage:
    from orchestrator.alerts import TradingAlertSender, send_alert
    
    # 方式 1: 使用类
    sender = TradingAlertSender()
    result = sender.send_candidate_alert(
        candidate_id="candidate_001",
        signal_type="buy_watch",
        symbol="000001.SZ",
        reason="趋势反转 + 量价共振"
    )
    
    # 方式 2: 便捷函数
    result = send_alert(
        candidate_id="candidate_001",
        signal_type="buy_watch",
        symbol="000001.SZ",
        reason="趋势反转 + 量价共振"
    )
"""

from .trading_alert_sender import (
    TradingAlertSender,
    AlertPayload,
    SendResult,
    send_alert,
    ALERT_SENDER_VERSION,
    AlertType,
    ALERT_STATE_DIR,
    ALERT_LOG_DIR,
)

__all__ = [
    "TradingAlertSender",
    "AlertPayload",
    "SendResult",
    "send_alert",
    "ALERT_SENDER_VERSION",
    "AlertType",
    "ALERT_STATE_DIR",
    "ALERT_LOG_DIR",
]
