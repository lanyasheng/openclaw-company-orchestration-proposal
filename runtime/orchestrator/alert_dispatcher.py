#!/usr/bin/env python3
"""
alert_dispatcher.py — Observability Batch 4: 主动告警调度器

目标：实现最小可用的主动告警闭环，覆盖完成/超时/失败三类事件。

核心能力：
1. 检测 completion_receipt / observability_card 事件
2. 生成人类可读告警/汇报
3. 去重 + 节流控制
4. 多通道发送（文件 mock / OpenClaw 原生）
5. 审计日志记录

集成点：
- completion_receipt.py: 创建 receipt 后调用 dispatch
- watchdog.py: 定期巡检调用 check_timeouts
- hooks/post_completion_translate_hook.py: 复用翻译逻辑

使用示例：
```python
from alert_dispatcher import AlertDispatcher

dispatcher = AlertDispatcher()

# 完成事件
dispatcher.dispatch_completion_alert(receipt, task_context)

# 超时事件
dispatcher.dispatch_timeout_alert(card, timeout_minutes=15)

# 失败事件
dispatcher.dispatch_failure_alert(receipt, task_context)
```
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

from human_report_renderer import HumanReportRenderer, ReportTemplate
from alert_rules import AlertRules, TimeoutRule, FailureRule, CompletionRule
from alert_audit import AlertAuditLogger, AlertAuditRecord

__all__ = [
    "AlertDispatcher",
    "AlertPayload",
    "AlertType",
    "AlertSeverity",
    "DeliveryChannel",
    "DeliveryResult",
    "ALERT_DISPATCHER_VERSION",
]

ALERT_DISPATCHER_VERSION = "alert_dispatcher_v1"

# 告警类型
AlertType = Literal[
    "task_completed",    # 任务完成
    "task_timeout",      # 任务超时
    "task_failed",       # 任务失败
    "task_stuck",        # 任务卡住
]

# 告警严重程度
AlertSeverity = Literal[
    "info",       # 信息（完成）
    "warning",    # 警告（超时）
    "error",      # 错误（失败）
    "critical",   # 严重（卡住）
]

# 告警通道
DeliveryChannel = Literal[
    "file",              # 文件 mock (测试用)
    "dingtalk",          # 钉钉群机器人 webhook
    "discord",           # Discord 消息 (fallback to file)
    "openclaw_native",   # OpenClaw 原生消息 (fallback to file)
]

# 告警状态目录
ALERT_STATE_DIR = Path(
    os.environ.get(
        "OPENCLAW_ALERT_STATE_DIR",
        Path.home() / ".openclaw" / "shared-context" / "alerts" / "state",
    )
)
ALERT_LOG_DIR = Path(
    os.environ.get(
        "OPENCLAW_ALERT_LOG_DIR",
        Path.home() / ".openclaw" / "shared-context" / "alerts" / "logs",
    )
)
ALERT_AUDIT_DIR = Path(
    os.environ.get(
        "OPENCLAW_ALERT_AUDIT_DIR",
        Path.home() / ".openclaw" / "shared-context" / "alerts" / "audits",
    )
)

# 节流配置
DEFAULT_THROTTLE_WINDOW_SECONDS = 300  # 5 分钟内相同类型 alert 最多 1 条
DEFAULT_MAX_ALERTS_PER_WINDOW = 1
DEFAULT_TIMEOUT_THRESHOLD_MINUTES = 15  # 超时阈值（分钟）
DEFAULT_HEARTBEAT_TIMEOUT_MINUTES = 10  # 心跳超时阈值（分钟）


def _ensure_dirs():
    """确保目录存在"""
    ALERT_STATE_DIR.mkdir(parents=True, exist_ok=True)
    ALERT_LOG_DIR.mkdir(parents=True, exist_ok=True)
    ALERT_AUDIT_DIR.mkdir(parents=True, exist_ok=True)


def _iso_now() -> str:
    """返回 ISO-8601 时间戳"""
    return datetime.now(timezone.utc).isoformat()


def _generate_alert_id(task_id: str, alert_type: str, timestamp: str) -> str:
    """生成稳定 alert ID"""
    content = f"{task_id}:{alert_type}:{timestamp}"
    return f"alert_{hashlib.sha256(content.encode()).hexdigest()[:12]}"


def _generate_dedupe_key(task_id: str, alert_type: str) -> str:
    """生成去重 key"""
    return f"{task_id}:{alert_type}"


def _generate_timeout_dedupe_key(task_id: str, hour: str) -> str:
    """生成超时告警去重 key（每小时允许一次）"""
    return f"{task_id}:timeout:{hour}"


def _state_file(alert_id: str) -> Path:
    """返回状态文件路径"""
    return ALERT_STATE_DIR / f"{alert_id}.json"


def _throttle_state_file() -> Path:
    """返回节流状态文件路径"""
    return ALERT_STATE_DIR / "throttle_state.json"


def _log_file() -> Path:
    """返回日志文件路径（按日期分片）"""
    date_str = datetime.now().strftime("%Y-%m-%d")
    return ALERT_LOG_DIR / f"alerts-{date_str}.jsonl"


@dataclass
class DeliveryResult:
    """
    告警发送结果
    
    字段：
    - status: sent | failed | dry_run
    - channel: 发送通道
    - message_id: 消息 ID（如有）
    - error: 错误信息（如有）
    - metadata: 额外元数据
    """
    status: Literal["sent", "failed", "dry_run"]
    channel: DeliveryChannel
    message_id: Optional[str] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "channel": self.channel,
            "message_id": self.message_id,
            "error": self.error,
            "metadata": self.metadata,
        }


@dataclass
class AlertPayload:
    """
    告警 Payload
    
    核心字段：
    - alert_id: 告警 ID
    - alert_type: 告警类型
    - task_id: 任务 ID
    - task_label: 任务标签
    - scenario: 场景
    - owner: 负责人
    - severity: 严重程度
    - human_message: 人类可读消息
    - technical_details: 技术细节
    - delivery: 发送配置
    - dedupe_key: 去重 key
    """
    alert_id: str
    alert_type: AlertType
    task_id: str
    task_label: str
    scenario: str
    owner: str
    severity: AlertSeverity
    human_message: str
    technical_details: Dict[str, Any]
    delivery: Dict[str, Any]
    dedupe_key: str
    timestamp: str = field(default_factory=_iso_now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "alert_version": ALERT_DISPATCHER_VERSION,
            "alert_id": self.alert_id,
            "alert_type": self.alert_type,
            "task_id": self.task_id,
            "task_label": self.task_label,
            "scenario": self.scenario,
            "owner": self.owner,
            "severity": self.severity,
            "human_message": self.human_message,
            "technical_details": self.technical_details,
            "delivery": self.delivery,
            "dedupe_key": self.dedupe_key,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AlertPayload":
        return cls(
            alert_id=data.get("alert_id", ""),
            alert_type=data.get("alert_type", "task_completed"),
            task_id=data.get("task_id", ""),
            task_label=data.get("task_label", ""),
            scenario=data.get("scenario", ""),
            owner=data.get("owner", ""),
            severity=data.get("severity", "info"),
            human_message=data.get("human_message", ""),
            technical_details=data.get("technical_details", {}),
            delivery=data.get("delivery", {}),
            dedupe_key=data.get("dedupe_key", ""),
            timestamp=data.get("timestamp", _iso_now()),
            metadata=data.get("metadata", {}),
        )
    
    def write_state(self) -> Path:
        """写入告警状态文件"""
        _ensure_dirs()
        state_file = _state_file(self.alert_id)
        state_data = {
            "alert_id": self.alert_id,
            "status": "pending",
            "created_at": self.timestamp,
            "payload": self.to_dict(),
        }
        
        tmp_file = state_file.with_suffix(".tmp")
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(state_data, f, indent=2, ensure_ascii=False)
        tmp_file.replace(state_file)
        
        return state_file
    
    def update_state(self, delivery_result: DeliveryResult) -> Path:
        """更新告警状态"""
        state_file = _state_file(self.alert_id)
        if not state_file.exists():
            self.write_state()
        
        with open(state_file, "r", encoding="utf-8") as f:
            state_data = json.load(f)
        
        state_data["status"] = delivery_result.status
        state_data["sent_at"] = _iso_now()
        state_data["delivery_result"] = delivery_result.to_dict()
        
        tmp_file = state_file.with_suffix(".tmp")
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(state_data, f, indent=2, ensure_ascii=False)
        tmp_file.replace(state_file)
        
        return state_file


class AlertDispatcher:
    """
    告警调度器
    
    核心方法：
    - dispatch_completion_alert(): 完成事件告警
    - dispatch_timeout_alert(): 超时事件告警
    - dispatch_failure_alert(): 失败事件告警
    - dispatch_stuck_alert(): 卡住事件告警
    - check_and_dispatch(): 通用检查并调度
    - is_duplicate(): 检查是否重复告警
    - _deliver(): 发送告警
    """
    
    def __init__(
        self,
        channel: DeliveryChannel = None,
        dry_run: bool = False,
        throttle_window_seconds: int = DEFAULT_THROTTLE_WINDOW_SECONDS,
        max_alerts_per_window: int = DEFAULT_MAX_ALERTS_PER_WINDOW,
        timeout_threshold_minutes: int = DEFAULT_TIMEOUT_THRESHOLD_MINUTES,
        heartbeat_timeout_minutes: int = DEFAULT_HEARTBEAT_TIMEOUT_MINUTES,
    ):
        """
        初始化告警调度器
        
        Args:
            channel: 告警通道（file/discord/openclaw_native）
            dry_run: 是否干跑（不真实发送）
            throttle_window_seconds: 节流窗口（秒）
            max_alerts_per_window: 窗口内最大告警数
            timeout_threshold_minutes: 超时阈值（分钟）
            heartbeat_timeout_minutes: 心跳超时阈值（分钟）
        """
        if channel is None:
            channel = os.environ.get("OPENCLAW_ALERT_CHANNEL", "dingtalk")
        self.channel = channel
        self.dry_run = dry_run
        self.throttle_window_seconds = throttle_window_seconds
        self.max_alerts_per_window = max_alerts_per_window
        self.timeout_threshold_minutes = timeout_threshold_minutes
        self.heartbeat_timeout_minutes = heartbeat_timeout_minutes
        
        self.renderer = HumanReportRenderer()
        self.rules = AlertRules(
            timeout_threshold_minutes=timeout_threshold_minutes,
            heartbeat_timeout_minutes=heartbeat_timeout_minutes,
        )
        self.audit_logger = AlertAuditLogger(audit_dir=ALERT_AUDIT_DIR)
        
        _ensure_dirs()
    
    def _load_throttle_state(self) -> Dict[str, List[str]]:
        """加载节流状态"""
        throttle_file = _throttle_state_file()
        if not throttle_file.exists():
            return {}
        
        try:
            with open(throttle_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, KeyError):
            return {}
    
    def _save_throttle_state(self, state: Dict[str, List[str]]):
        """保存节流状态"""
        throttle_file = _throttle_state_file()
        tmp_file = throttle_file.with_suffix(".tmp")
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        tmp_file.replace(throttle_file)
    
    def _is_duplicate(self, dedupe_key: str) -> bool:
        """
        检查是否重复告警
        
        规则：
        1. 检查节流窗口内是否已有相同 dedupe_key 的告警
        2. 超时告警特殊处理：每小时允许一次
        """
        state = self._load_throttle_state()
        
        if dedupe_key not in state:
            return False
        
        # 检查窗口内告警（支持新旧格式兼容）
        cutoff = datetime.now() - timedelta(seconds=self.throttle_window_seconds)
        recent_alerts = []
        for entry in state[dedupe_key]:
            if isinstance(entry, dict):
                # 新格式：{"alert_id": ..., "timestamp": ...}
                if datetime.fromisoformat(entry["timestamp"]) > cutoff:
                    recent_alerts.append(entry)
            else:
                # 旧格式：alert_id 字符串（尝试解析）
                try:
                    if datetime.fromisoformat(entry.split("_")[-1]) > cutoff:
                        recent_alerts.append(entry)
                except (ValueError, IndexError):
                    # 无法解析的旧格式，保留
                    recent_alerts.append(entry)
        
        return len(recent_alerts) >= self.max_alerts_per_window
    
    def _record_throttle(self, dedupe_key: str, alert_id: str):
        """记录节流状态"""
        state = self._load_throttle_state()
        
        if dedupe_key not in state:
            state[dedupe_key] = []
        
        # 存储 (alert_id, timestamp) 元组
        timestamp = _iso_now()
        state[dedupe_key].append({"alert_id": alert_id, "timestamp": timestamp})
        
        # 清理过期条目
        cutoff = datetime.now() - timedelta(seconds=self.throttle_window_seconds)
        state[dedupe_key] = [
            entry for entry in state[dedupe_key]
            if datetime.fromisoformat(entry["timestamp"]) > cutoff
        ]
        
        self._save_throttle_state(state)
    
    def _deliver(self, payload: AlertPayload) -> DeliveryResult:
        """
        发送告警
        
        Args:
            payload: Alert payload
        
        Returns:
            DeliveryResult
        """
        if self.dry_run:
            return DeliveryResult(
                status="dry_run",
                channel=self.channel,
                metadata={"reason": "dry_run_enabled"},
            )
        
        if self.channel == "file":
            return self._deliver_to_file(payload)
        elif self.channel == "dingtalk":
            return self._deliver_to_dingtalk(payload)
        elif self.channel == "discord":
            return self._deliver_to_discord(payload)
        elif self.channel == "openclaw_native":
            return self._deliver_to_openclaw(payload)
        else:
            return DeliveryResult(
                status="failed",
                channel=self.channel,
                error=f"Unknown channel: {self.channel}",
            )
    
    def _deliver_to_file(self, payload: AlertPayload) -> DeliveryResult:
        """发送到文件（Mock 模式）"""
        try:
            notification_file = ALERT_LOG_DIR / f"{payload.alert_id}.json"
            notification_data = {
                "alert_id": payload.alert_id,
                "channel": "file",
                "message": payload.human_message,
                "timestamp": payload.timestamp,
                "payload": payload.to_dict(),
            }
            
            tmp_file = notification_file.with_suffix(".tmp")
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(notification_data, f, indent=2, ensure_ascii=False)
            tmp_file.replace(notification_file)
            
            return DeliveryResult(
                status="sent",
                channel="file",
                message_id=str(notification_file),
                metadata={"file_path": str(notification_file)},
            )
        except Exception as e:
            return DeliveryResult(
                status="failed",
                channel="file",
                error=str(e),
            )
    
    def _deliver_to_dingtalk(self, payload: AlertPayload) -> DeliveryResult:
        """发送到钉钉群机器人 webhook"""
        import hmac
        import hashlib as _hashlib
        import base64
        import urllib.parse
        import urllib.request
        import time as _time

        config_path = Path.home() / ".openclaw" / "dingtalk-config.json"
        if not config_path.exists():
            return self._deliver_to_file(payload)  # fallback

        try:
            config = json.loads(config_path.read_text())
            webhook_url = config["webhookUrl"]
            secret = config.get("secret", "")

            # Sign if secret is present
            if secret:
                timestamp = str(int(_time.time() * 1000))
                string_to_sign = f"{timestamp}\n{secret}"
                hmac_code = hmac.new(
                    secret.encode("utf-8"),
                    string_to_sign.encode("utf-8"),
                    digestmod=_hashlib.sha256,
                ).digest()
                sign = urllib.parse.quote_plus(base64.b64encode(hmac_code).decode())
                webhook_url = f"{webhook_url}&timestamp={timestamp}&sign={sign}"

            # Build markdown message
            severity_icon = {"info": "✅", "warning": "⚠️", "error": "❌", "critical": "🔴"}.get(
                payload.severity, "ℹ️"
            )
            title = f"{severity_icon} [{payload.alert_type}] {payload.task_id}"
            body = {
                "msgtype": "markdown",
                "markdown": {
                    "title": title,
                    "text": f"### {title}\n\n{payload.human_message[:2000]}",
                },
            }

            req = urllib.request.Request(
                webhook_url,
                data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp_data = json.loads(resp.read())

            if resp_data.get("errcode") == 0:
                # Also write to file for audit
                self._deliver_to_file(payload)
                return DeliveryResult(
                    status="sent",
                    channel="dingtalk",
                    message_id=str(resp_data.get("errmsg", "")),
                )
            else:
                return DeliveryResult(
                    status="failed",
                    channel="dingtalk",
                    error=f"DingTalk API error: {resp_data}",
                )
        except Exception as e:
            # Fallback to file on any error
            self._deliver_to_file(payload)
            return DeliveryResult(
                status="failed",
                channel="dingtalk",
                error=f"DingTalk delivery failed, wrote to file: {e}",
            )

    def _deliver_to_discord(self, payload: AlertPayload) -> DeliveryResult:
        """发送到 Discord — fallback 到文件"""
        return self._deliver_to_file(payload)

    def _deliver_to_openclaw(self, payload: AlertPayload) -> DeliveryResult:
        """发送到 OpenClaw 原生消息 — fallback 到文件"""
        return self._deliver_to_file(payload)
    
    def dispatch_completion_alert(
        self,
        completion_receipt: Dict[str, Any],
        task_context: Dict[str, Any],
        template: Optional[ReportTemplate] = None,
    ) -> Tuple[Optional[AlertPayload], DeliveryResult]:
        """
        发送完成事件告警
        
        Args:
            completion_receipt: Completion receipt artifact
            task_context: 任务上下文
            template: 可选的汇报模板
        
        Returns:
            (AlertPayload, DeliveryResult)
        """
        task_id = completion_receipt.get("source_task_id", "")
        receipt_status = completion_receipt.get("receipt_status", "")
        
        # 只处理 completed 状态
        if receipt_status != "completed":
            return None, DeliveryResult(
                status="failed",
                channel=self.channel,
                error=f"Receipt status is '{receipt_status}', not 'completed'",
            )
        
        # 检查是否重复
        dedupe_key = _generate_dedupe_key(task_id, "task_completed")
        if self._is_duplicate(dedupe_key):
            return None, DeliveryResult(
                status="failed",
                channel=self.channel,
                error="Duplicate alert (throttled)",
            )
        
        # 生成告警 ID
        alert_id = _generate_alert_id(task_id, "task_completed", _iso_now())
        
        # 提取任务上下文
        task_label = task_context.get("label", "unnamed")
        scenario = task_context.get("scenario", "custom")
        owner = task_context.get("owner", "main")
        
        # 生成人话汇报
        human_message = self.renderer.render_completion_summary(
            completion_receipt=completion_receipt,
            task_context=task_context,
            template=template,
        )
        
        # 构建 payload
        payload = AlertPayload(
            alert_id=alert_id,
            alert_type="task_completed",
            task_id=task_id,
            task_label=task_label,
            scenario=scenario,
            owner=owner,
            severity="info",
            human_message=human_message,
            technical_details={
                "receipt_id": completion_receipt.get("receipt_id", ""),
                "receipt_status": receipt_status,
                "result_summary": completion_receipt.get("result_summary", ""),
            },
            delivery={
                "channel": self.channel,
                "dedupe_key": dedupe_key,
            },
            dedupe_key=dedupe_key,
        )
        
        # 写入状态
        payload.write_state()
        
        # 发送告警
        result = self._deliver(payload)
        
        # 更新状态
        payload.update_state(result)
        
        # 记录节流
        self._record_throttle(dedupe_key, alert_id)
        
        # 记录审计
        self.audit_logger.log_report(
            task_id=task_id,
            alert_id=alert_id,
            report_content=human_message,
            delivery_result=result.to_dict(),
        )
        
        return payload, result
    
    def dispatch_timeout_alert(
        self,
        card: Dict[str, Any],
        timeout_minutes: Optional[int] = None,
    ) -> Tuple[Optional[AlertPayload], DeliveryResult]:
        """
        发送超时事件告警
        
        Args:
            card: Observability card
            timeout_minutes: 超时阈值（分钟），默认使用实例配置
        
        Returns:
            (AlertPayload, DeliveryResult)
        """
        task_id = card.get("task_id", "")
        
        # 检查是否超时
        timeout_check = self.rules.check_timeout(card, timeout_minutes)
        if not timeout_check.is_timeout:
            return None, DeliveryResult(
                status="failed",
                channel=self.channel,
                error=timeout_check.reason,
            )
        
        # 检查是否重复（超时告警每小时允许一次）
        hour = datetime.now().strftime("%Y-%m-%d-%H")
        dedupe_key = _generate_timeout_dedupe_key(task_id, hour)
        if self._is_duplicate(dedupe_key):
            return None, DeliveryResult(
                status="failed",
                channel=self.channel,
                error="Duplicate timeout alert (throttled)",
            )
        
        # 生成告警 ID
        alert_id = _generate_alert_id(task_id, "task_timeout", _iso_now())
        
        # 提取任务上下文
        task_label = card.get("metadata", {}).get("label", "unnamed")
        scenario = card.get("scenario", "custom")
        owner = card.get("owner", "main")
        promised_eta = card.get("promise_anchor", {}).get("promised_eta", "")
        
        # 生成人话告警
        human_message = self.renderer.render_timeout_alert(
            card=card,
            timeout_minutes=timeout_check.timeout_minutes,
            overdue_minutes=timeout_check.overdue_minutes,
        )
        
        # 构建 payload
        payload = AlertPayload(
            alert_id=alert_id,
            alert_type="task_timeout",
            task_id=task_id,
            task_label=task_label,
            scenario=scenario,
            owner=owner,
            severity="warning",
            human_message=human_message,
            technical_details={
                "promised_eta": promised_eta,
                "current_stage": card.get("stage", ""),
                "timeout_minutes": timeout_check.timeout_minutes,
                "overdue_minutes": timeout_check.overdue_minutes,
            },
            delivery={
                "channel": self.channel,
                "dedupe_key": dedupe_key,
            },
            dedupe_key=dedupe_key,
        )
        
        # 写入状态
        payload.write_state()
        
        # 发送告警
        result = self._deliver(payload)
        
        # 更新状态
        payload.update_state(result)
        
        # 记录节流
        self._record_throttle(dedupe_key, alert_id)
        
        # 记录审计
        self.audit_logger.log_alert(
            alert_type="task_timeout",
            task_id=task_id,
            alert_id=alert_id,
            payload=payload.to_dict(),
            delivery_result=result.to_dict(),
        )
        
        return payload, result
    
    def dispatch_failure_alert(
        self,
        completion_receipt: Dict[str, Any],
        task_context: Dict[str, Any],
    ) -> Tuple[Optional[AlertPayload], DeliveryResult]:
        """
        发送失败事件告警
        
        Args:
            completion_receipt: Completion receipt artifact
            task_context: 任务上下文
        
        Returns:
            (AlertPayload, DeliveryResult)
        """
        task_id = completion_receipt.get("source_task_id", "")
        receipt_status = completion_receipt.get("receipt_status", "")
        
        # 只处理 failed 状态
        if receipt_status != "failed":
            return None, DeliveryResult(
                status="failed",
                channel=self.channel,
                error=f"Receipt status is '{receipt_status}', not 'failed'",
            )
        
        # 检查是否重复
        dedupe_key = _generate_dedupe_key(task_id, "task_failed")
        if self._is_duplicate(dedupe_key):
            return None, DeliveryResult(
                status="failed",
                channel=self.channel,
                error="Duplicate alert (throttled)",
            )
        
        # 生成告警 ID
        alert_id = _generate_alert_id(task_id, "task_failed", _iso_now())
        
        # 提取任务上下文
        task_label = task_context.get("label", "unnamed")
        scenario = task_context.get("scenario", "custom")
        owner = task_context.get("owner", "main")
        
        # 生成人话告警
        human_message = self.renderer.render_failure_alert(
            completion_receipt=completion_receipt,
            task_context=task_context,
        )
        
        # 构建 payload
        payload = AlertPayload(
            alert_id=alert_id,
            alert_type="task_failed",
            task_id=task_id,
            task_label=task_label,
            scenario=scenario,
            owner=owner,
            severity="error",
            human_message=human_message,
            technical_details={
                "receipt_id": completion_receipt.get("receipt_id", ""),
                "receipt_status": receipt_status,
                "receipt_reason": completion_receipt.get("receipt_reason", ""),
            },
            delivery={
                "channel": self.channel,
                "dedupe_key": dedupe_key,
            },
            dedupe_key=dedupe_key,
        )
        
        # 写入状态
        payload.write_state()
        
        # 发送告警
        result = self._deliver(payload)
        
        # 更新状态
        payload.update_state(result)
        
        # 记录节流
        self._record_throttle(dedupe_key, alert_id)
        
        # 记录审计
        self.audit_logger.log_alert(
            alert_type="task_failed",
            task_id=task_id,
            alert_id=alert_id,
            payload=payload.to_dict(),
            delivery_result=result.to_dict(),
        )
        
        return payload, result
    
    def dispatch_stuck_alert(
        self,
        card: Dict[str, Any],
    ) -> Tuple[Optional[AlertPayload], DeliveryResult]:
        """
        发送卡住事件告警
        
        Args:
            card: Observability card
        
        Returns:
            (AlertPayload, DeliveryResult)
        """
        task_id = card.get("task_id", "")
        
        # 检查是否卡住
        stuck_check = self.rules.check_stuck(card)
        if not stuck_check.is_stuck:
            return None, DeliveryResult(
                status="failed",
                channel=self.channel,
                error=stuck_check.reason,
            )
        
        # 检查是否重复
        dedupe_key = _generate_dedupe_key(task_id, "task_stuck")
        if self._is_duplicate(dedupe_key):
            return None, DeliveryResult(
                status="failed",
                channel=self.channel,
                error="Duplicate alert (throttled)",
            )
        
        # 生成告警 ID
        alert_id = _generate_alert_id(task_id, "task_stuck", _iso_now())
        
        # 提取任务上下文
        task_label = card.get("metadata", {}).get("label", "unnamed")
        scenario = card.get("scenario", "custom")
        owner = card.get("owner", "main")
        
        # 生成人话告警
        human_message = self.renderer.render_stuck_alert(
            card=card,
            no_heartbeat_minutes=stuck_check.no_heartbeat_minutes,
        )
        
        # 构建 payload
        payload = AlertPayload(
            alert_id=alert_id,
            alert_type="task_stuck",
            task_id=task_id,
            task_label=task_label,
            scenario=scenario,
            owner=owner,
            severity="critical",
            human_message=human_message,
            technical_details={
                "current_stage": card.get("stage", ""),
                "last_heartbeat": card.get("heartbeat", ""),
                "no_heartbeat_minutes": stuck_check.no_heartbeat_minutes,
            },
            delivery={
                "channel": self.channel,
                "dedupe_key": dedupe_key,
            },
            dedupe_key=dedupe_key,
        )
        
        # 写入状态
        payload.write_state()
        
        # 发送告警
        result = self._deliver(payload)
        
        # 更新状态
        payload.update_state(result)
        
        # 记录节流
        self._record_throttle(dedupe_key, alert_id)
        
        # 记录审计
        self.audit_logger.log_alert(
            alert_type="task_stuck",
            task_id=task_id,
            alert_id=alert_id,
            payload=payload.to_dict(),
            delivery_result=result.to_dict(),
        )
        
        return payload, result
    
    def check_and_dispatch(
        self,
        completion_receipt: Optional[Dict[str, Any]] = None,
        card: Optional[Dict[str, Any]] = None,
        task_context: Optional[Dict[str, Any]] = None,
    ) -> List[Tuple[AlertType, Optional[AlertPayload], DeliveryResult]]:
        """
        通用检查并调度告警
        
        Args:
            completion_receipt: Completion receipt（如有）
            card: Observability card（如有）
            task_context: 任务上下文
        
        Returns:
            列表：[(alert_type, payload, result), ...]
        """
        results: List[Tuple[AlertType, Optional[AlertPayload], DeliveryResult]] = []
        task_ctx = task_context or {}
        
        # 处理 completion receipt
        if completion_receipt:
            receipt_status = completion_receipt.get("receipt_status", "")
            
            if receipt_status == "completed":
                payload, result = self.dispatch_completion_alert(
                    completion_receipt, task_ctx
                )
                results.append(("task_completed", payload, result))
            
            elif receipt_status == "failed":
                payload, result = self.dispatch_failure_alert(
                    completion_receipt, task_ctx
                )
                results.append(("task_failed", payload, result))
        
        # 处理 observability card
        if card:
            # 检查超时
            payload, result = self.dispatch_timeout_alert(card)
            if payload:
                results.append(("task_timeout", payload, result))
            
            # 检查卡住
            payload, result = self.dispatch_stuck_alert(card)
            if payload:
                results.append(("task_stuck", payload, result))
        
        return results


# 便捷函数

def dispatch_completion(
    receipt: Dict[str, Any],
    context: Dict[str, Any],
    channel: DeliveryChannel = "file",
) -> Tuple[Optional[AlertPayload], DeliveryResult]:
    """便捷函数：发送完成告警"""
    dispatcher = AlertDispatcher(channel=channel)
    return dispatcher.dispatch_completion_alert(receipt, context)


def dispatch_timeout(
    card: Dict[str, Any],
    channel: DeliveryChannel = "file",
) -> Tuple[Optional[AlertPayload], DeliveryResult]:
    """便捷函数：发送超时告警"""
    dispatcher = AlertDispatcher(channel=channel)
    return dispatcher.dispatch_timeout_alert(card)


def dispatch_failure(
    receipt: Dict[str, Any],
    context: Dict[str, Any],
    channel: DeliveryChannel = "file",
) -> Tuple[Optional[AlertPayload], DeliveryResult]:
    """便捷函数：发送失败告警"""
    dispatcher = AlertDispatcher(channel=channel)
    return dispatcher.dispatch_failure_alert(receipt, context)


if __name__ == "__main__":
    # 简单测试
    print("Alert Dispatcher - Quick Test")
    print("=" * 50)
    
    # 测试完成告警
    test_receipt = {
        "receipt_id": "receipt_test_001",
        "source_task_id": "task_test_001",
        "receipt_status": "completed",
        "result_summary": "Task completed successfully",
    }
    test_context = {
        "label": "test-feature",
        "scenario": "custom",
        "owner": "main",
    }
    
    payload, result = dispatch_completion(test_receipt, test_context)
    print(f"Completion alert: {result.status}, file={result.message_id}")
    
    # 测试失败告警
    test_receipt_failed = {
        "receipt_id": "receipt_test_002",
        "source_task_id": "task_test_002",
        "receipt_status": "failed",
        "receipt_reason": "Test failure",
    }
    
    payload, result = dispatch_failure(test_receipt_failed, test_context)
    print(f"Failure alert: {result.status}, file={result.message_id}")
    
    # 测试超时告警
    test_card = {
        "task_id": "task_test_003",
        "stage": "running",
        "heartbeat": "2026-03-29T10:00:00",
        "promise_anchor": {
            "promised_eta": "2026-03-29T11:00:00",
        },
        "metadata": {"label": "test-timeout"},
        "scenario": "custom",
        "owner": "main",
    }
    
    payload, result = dispatch_timeout(test_card)
    print(f"Timeout alert: {result.status}, file={result.message_id}")
    
    print("Test completed!")
