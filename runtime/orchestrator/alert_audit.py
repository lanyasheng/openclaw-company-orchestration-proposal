#!/usr/bin/env python3
"""
alert_audit.py — Observability Batch 4: 告警审计日志

目标：记录所有告警/回报事件到审计日志，支持查询和追溯。

核心能力：
1. 记录告警事件（超时/失败/卡住）
2. 记录汇报事件（完成汇报）
3. 查询审计日志
4. 按任务/时间/类型过滤

审计字段：
- audit_id: 审计 ID
- audit_type: alert | report
- alert_type: 告警类型
- task_id: 任务 ID
- timestamp: 时间戳
- payload: 告警/汇报内容
- delivery_result: 发送结果

使用示例：
```python
from alert_audit import AlertAuditLogger

logger = AlertAuditLogger()

# 记录告警
logger.log_alert(
    alert_type="task_timeout",
    task_id="task_001",
    alert_id="alert_abc123",
    payload={...},
    delivery_result={...},
)

# 记录汇报
logger.log_report(
    task_id="task_002",
    alert_id="alert_xyz789",
    report_content="任务已完成...",
    delivery_result={...},
)

# 查询日志
logs = logger.query_logs(task_id="task_001", limit=10)
```
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

__all__ = [
    "AlertAuditLogger",
    "AlertAuditRecord",
    "AuditType",
    "AUDIT_VERSION",
]

AUDIT_VERSION = "alert_audit_v1"

# 审计类型
AuditType = Literal[
    "alert",     # 告警事件
    "report",    # 汇报事件
]


def _ensure_audit_dir(audit_dir: Path) -> None:
    """确保审计目录存在"""
    audit_dir.mkdir(parents=True, exist_ok=True)


def _iso_now() -> str:
    """返回 ISO-8601 时间戳"""
    return datetime.now().isoformat()


def _generate_audit_id() -> str:
    """生成 stable audit ID"""
    import uuid
    return f"audit_{uuid.uuid4().hex[:12]}"


def _audit_file(audit_id: str, audit_dir: Path) -> Path:
    """返回审计文件路径"""
    return audit_dir / f"{audit_id}.json"


def _daily_log_file(audit_dir: Path) -> Path:
    """返回日志文件路径（按日期分片）"""
    date_str = datetime.now().strftime("%Y-%m-%d")
    return audit_dir / f"logs-{date_str}.jsonl"


def _index_file(audit_dir: Path) -> Path:
    """返回索引文件路径"""
    return audit_dir / "audit_index.json"


@dataclass
class AlertAuditRecord:
    """
    告警审计记录
    
    核心字段：
    - audit_id: 审计 ID
    - audit_type: 审计类型（alert/report）
    - alert_type: 告警类型（task_completed/task_timeout/task_failed/task_stuck）
    - task_id: 任务 ID
    - timestamp: 时间戳
    - payload: 告警/汇报内容
    - delivery_result: 发送结果
    - metadata: 额外元数据
    """
    audit_id: str
    audit_type: AuditType
    alert_type: str
    task_id: str
    timestamp: str
    payload: Dict[str, Any]
    delivery_result: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "audit_version": AUDIT_VERSION,
            "audit_id": self.audit_id,
            "audit_type": self.audit_type,
            "alert_type": self.alert_type,
            "task_id": self.task_id,
            "timestamp": self.timestamp,
            "payload": self.payload,
            "delivery_result": self.delivery_result,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AlertAuditRecord":
        return cls(
            audit_id=data.get("audit_id", ""),
            audit_type=data.get("audit_type", "alert"),
            alert_type=data.get("alert_type", ""),
            task_id=data.get("task_id", ""),
            timestamp=data.get("timestamp", ""),
            payload=data.get("payload", {}),
            delivery_result=data.get("delivery_result", {}),
            metadata=data.get("metadata", {}),
        )
    
    def write(self, audit_dir: Path) -> Path:
        """写入审计文件"""
        _ensure_audit_dir(audit_dir)
        
        audit_file = _audit_file(self.audit_id, audit_dir)
        tmp_file = audit_file.with_suffix(".tmp")
        
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
        tmp_file.replace(audit_file)
        
        # 追加到日志文件
        self._append_to_log(audit_dir)
        
        # 更新索引
        self._update_index(audit_dir)
        
        return audit_file
    
    def _append_to_log(self, audit_dir: Path):
        """追加到日志文件"""
        log_file = _daily_log_file(audit_dir)
        
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(self.to_dict(), ensure_ascii=False) + "\n")
    
    def _update_index(self, audit_dir: Path):
        """更新索引"""
        index_file = _index_file(audit_dir)
        
        # 加载索引
        index = self._load_index(audit_dir)
        
        # 添加条目
        if self.task_id not in index:
            index[self.task_id] = []
        index[self.task_id].append({
            "audit_id": self.audit_id,
            "timestamp": self.timestamp,
            "audit_type": self.audit_type,
            "alert_type": self.alert_type,
        })
        
        # 保存索引
        tmp_file = index_file.with_suffix(".tmp")
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(index, f, indent=2, ensure_ascii=False)
        tmp_file.replace(index_file)
    
    def _load_index(self, audit_dir: Path) -> Dict[str, List[Dict[str, Any]]]:
        """加载索引"""
        index_file = _index_file(audit_dir)
        if not index_file.exists():
            return {}
        
        try:
            with open(index_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, KeyError):
            return {}


class AlertAuditLogger:
    """
    告警审计日志器
    
    核心方法：
    - log_alert(): 记录告警事件
    - log_report(): 记录汇报事件
    - query_logs(): 查询审计日志
    - get_task_history(): 获取任务历史
    """
    
    def __init__(self, audit_dir: Optional[Path] = None):
        """
        初始化审计日志器
        
        Args:
            audit_dir: 审计目录（默认：OPENCLAW_ALERT_AUDIT_DIR）
        """
        self.audit_dir = audit_dir or Path(
            os.environ.get(
                "OPENCLAW_ALERT_AUDIT_DIR",
                Path.home() / ".openclaw" / "shared-context" / "alerts" / "audits",
            )
        )
        _ensure_audit_dir(self.audit_dir)
    
    def log_alert(
        self,
        alert_type: str,
        task_id: str,
        alert_id: str,
        payload: Dict[str, Any],
        delivery_result: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AlertAuditRecord:
        """
        记录告警事件
        
        Args:
            alert_type: 告警类型（task_timeout/task_failed/task_stuck）
            task_id: 任务 ID
            alert_id: 告警 ID
            payload: 告警 payload
            delivery_result: 发送结果
            metadata: 额外元数据
        
        Returns:
            AlertAuditRecord
        """
        audit_id = _generate_audit_id()
        
        record = AlertAuditRecord(
            audit_id=audit_id,
            audit_type="alert",
            alert_type=alert_type,
            task_id=task_id,
            timestamp=_iso_now(),
            payload=payload,
            delivery_result=delivery_result,
            metadata=metadata or {},
        )
        
        record.write(self.audit_dir)
        
        return record
    
    def log_report(
        self,
        task_id: str,
        alert_id: str,
        report_content: str,
        delivery_result: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AlertAuditRecord:
        """
        记录汇报事件
        
        Args:
            task_id: 任务 ID
            alert_id: 告警 ID
            report_content: 汇报内容
            delivery_result: 发送结果
            metadata: 额外元数据
        
        Returns:
            AlertAuditRecord
        """
        audit_id = _generate_audit_id()
        
        record = AlertAuditRecord(
            audit_id=audit_id,
            audit_type="report",
            alert_type="task_completed",
            task_id=task_id,
            timestamp=_iso_now(),
            payload={
                "alert_id": alert_id,
                "report_content": report_content,
            },
            delivery_result=delivery_result,
            metadata=metadata or {},
        )
        
        record.write(self.audit_dir)
        
        return record
    
    def query_logs(
        self,
        task_id: Optional[str] = None,
        audit_type: Optional[AuditType] = None,
        alert_type: Optional[str] = None,
        limit: int = 100,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
    ) -> List[AlertAuditRecord]:
        """
        查询审计日志
        
        Args:
            task_id: 按任务 ID 过滤
            audit_type: 按审计类型过滤
            alert_type: 按告警类型过滤
            limit: 最大返回数量
            start_time: 开始时间（ISO-8601）
            end_time: 结束时间（ISO-8601）
        
        Returns:
            审计记录列表
        """
        records: List[AlertAuditRecord] = []
        
        # 遍历所有审计文件
        for audit_file in sorted(self.audit_dir.glob("audit_*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            if len(records) >= limit:
                break
            
            try:
                with open(audit_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                record = AlertAuditRecord.from_dict(data)
                
                # 过滤
                if task_id and record.task_id != task_id:
                    continue
                if audit_type and record.audit_type != audit_type:
                    continue
                if alert_type and record.alert_type != alert_type:
                    continue
                if start_time and record.timestamp < start_time:
                    continue
                if end_time and record.timestamp > end_time:
                    continue
                
                records.append(record)
            except (json.JSONDecodeError, KeyError):
                continue
        
        return records
    
    def get_task_history(
        self,
        task_id: str,
        limit: int = 50,
    ) -> List[AlertAuditRecord]:
        """
        获取任务历史
        
        Args:
            task_id: 任务 ID
            limit: 最大返回数量
        
        Returns:
            审计记录列表（按时间倒序）
        """
        return self.query_logs(task_id=task_id, limit=limit)
    
    def get_recent_alerts(
        self,
        alert_type: str,
        limit: int = 20,
    ) -> List[AlertAuditRecord]:
        """
        获取最近的告警
        
        Args:
            alert_type: 告警类型
            limit: 最大返回数量
        
        Returns:
            审计记录列表
        """
        return self.query_logs(alert_type=alert_type, limit=limit)
    
    def get_stats(
        self,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        获取统计信息
        
        Args:
            start_time: 开始时间
            end_time: 结束时间
        
        Returns:
            统计信息字典
        """
        # 获取所有日志
        all_logs = self.query_logs(start_time=start_time, end_time=end_time, limit=10000)
        
        # 按类型统计
        by_type: Dict[str, int] = {}
        by_task: Dict[str, int] = {}
        by_delivery_status: Dict[str, int] = {}
        
        for record in all_logs:
            # 按告警类型
            alert_type = record.alert_type
            by_type[alert_type] = by_type.get(alert_type, 0) + 1
            
            # 按任务
            task_id = record.task_id
            by_task[task_id] = by_task.get(task_id, 0) + 1
            
            # 按发送状态
            status = record.delivery_result.get("status", "unknown")
            by_delivery_status[status] = by_delivery_status.get(status, 0) + 1
        
        return {
            "total_records": len(all_logs),
            "by_type": by_type,
            "by_task": by_task,
            "by_delivery_status": by_delivery_status,
            "time_range": {
                "start": start_time or "all",
                "end": end_time or "now",
            },
        }


# 便捷函数

def log_alert(
    alert_type: str,
    task_id: str,
    alert_id: str,
    payload: Dict[str, Any],
    delivery_result: Dict[str, Any],
    audit_dir: Optional[Path] = None,
) -> AlertAuditRecord:
    """便捷函数：记录告警"""
    logger = AlertAuditLogger(audit_dir=audit_dir)
    return logger.log_alert(alert_type, task_id, alert_id, payload, delivery_result)


def log_report(
    task_id: str,
    alert_id: str,
    report_content: str,
    delivery_result: Dict[str, Any],
    audit_dir: Optional[Path] = None,
) -> AlertAuditRecord:
    """便捷函数：记录汇报"""
    logger = AlertAuditLogger(audit_dir=audit_dir)
    return logger.log_report(task_id, alert_id, report_content, delivery_result)


def query_logs(
    task_id: Optional[str] = None,
    audit_type: Optional[AuditType] = None,
    alert_type: Optional[str] = None,
    limit: int = 100,
    audit_dir: Optional[Path] = None,
) -> List[AlertAuditRecord]:
    """便捷函数：查询日志"""
    logger = AlertAuditLogger(audit_dir=audit_dir)
    return logger.query_logs(task_id=task_id, audit_type=audit_type, alert_type=alert_type, limit=limit)


if __name__ == "__main__":
    # 简单测试
    print("Alert Audit Logger - Quick Test")
    print("=" * 50)
    
    logger = AlertAuditLogger()
    
    # 测试记录告警
    record = logger.log_alert(
        alert_type="task_timeout",
        task_id="task_test_001",
        alert_id="alert_test_001",
        payload={"test": "timeout alert"},
        delivery_result={"status": "sent", "channel": "file"},
    )
    print(f"Logged alert: {record.audit_id}")
    
    # 测试记录汇报
    record = logger.log_report(
        task_id="task_test_002",
        alert_id="alert_test_002",
        report_content="Task completed successfully",
        delivery_result={"status": "sent", "channel": "file"},
    )
    print(f"Logged report: {record.audit_id}")
    
    # 测试查询日志
    logs = logger.query_logs(task_id="task_test_001", limit=10)
    print(f"Found {len(logs)} logs for task_test_001")
    
    # 测试获取任务历史
    history = logger.get_task_history("task_test_001")
    print(f"Task history: {len(history)} records")
    
    # 测试统计
    stats = logger.get_stats()
    print(f"Stats: {stats['total_records']} total records")
    
    print("Test completed!")
