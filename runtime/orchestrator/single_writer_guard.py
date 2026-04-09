#!/usr/bin/env python3
"""
single_writer_guard.py — Single-Writer Repo Guard (Minimal Implementation)

目标：实现最小 single-writer guard，确保同一 repo 只能有一个 writer lane 持锁推进。

核心规则：
1. 同一 repo 只能有一个 writer lane 持锁推进
2. 其他任务如果是 audit/read-only，可并行但不能 claim writer
3. 使用文件锁机制，超时自动释放（5 分钟）

这是 P0-4 Single-Writer Guard 的核心实现，依赖：
- 文件系统锁（fcntl / msvcrt）
- shared-context 目录持久化

设计原则：
1. 最小实现（不求大而全）
2. 超时自动释放（防死锁）
3. 读写分离（reader 不占 writer 锁）
"""

from __future__ import annotations

import fcntl
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

__all__ = [
    "WriterLockStatus",
    "WriterLockRecord",
    "SingleWriterGuard",
    "acquire_writer_lock",
    "release_writer_lock",
    "check_writer_conflict",
    "SINGLE_WRITER_GUARD_VERSION",
]

SINGLE_WRITER_GUARD_VERSION = "single_writer_guard_v1"

WriterLockStatus = Literal["active", "expired", "released", "missing"]

# Writer lock 存储目录
WRITER_LOCK_DIR = Path(
    os.environ.get(
        "OPENCLAW_WRITER_LOCK_DIR",
        Path.home() / ".openclaw" / "shared-context" / "writer_locks",
    )
)

# 默认锁超时时间（秒）
DEFAULT_LOCK_TIMEOUT_SECONDS = 5 * 60  # 5 分钟


def _ensure_lock_dir():
    """确保 lock 目录存在"""
    WRITER_LOCK_DIR.mkdir(parents=True, exist_ok=True)


def _lock_file(repo: str, batch_id: str = "") -> Path:
    """返回 lock 文件路径"""
    # 使用 repo + batch_id 作为 lock key
    # 如果 batch_id 为空，则只对 repo 加锁
    key = f"{repo}:{batch_id}" if batch_id else repo
    # 安全文件名：替换特殊字符
    safe_key = key.replace("/", "_").replace(":", "_").replace("\\", "_")
    return WRITER_LOCK_DIR / f"{safe_key}.lock"


def _iso_now() -> str:
    """返回当前 ISO-8601 时间戳"""
    return datetime.now(timezone.utc).isoformat()


def _generate_lock_id() -> str:
    """生成 stable lock ID"""
    import uuid
    return f"lock_{uuid.uuid4().hex[:12]}"


@dataclass
class WriterLockRecord:
    """
    Writer lock record — 写锁记录。
    
    核心字段：
    - lock_id: Lock ID
    - repo: 仓库标识
    - batch_id: Batch ID（可选）
    - writer_id: Writer ID（执行器/任务 ID）
    - lane_type: Lane 类型 (writer / reader)
    - acquired_at: 获取时间
    - expires_at: 过期时间
    - status: 锁状态
    - metadata: 额外元数据
    """
    lock_id: str
    repo: str
    batch_id: str = ""
    writer_id: str = ""
    lane_type: Literal["writer", "reader"] = "writer"
    acquired_at: str = ""
    expires_at: str = ""
    status: WriterLockStatus = "active"
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "guard_version": SINGLE_WRITER_GUARD_VERSION,
            "lock_id": self.lock_id,
            "repo": self.repo,
            "batch_id": self.batch_id,
            "writer_id": self.writer_id,
            "lane_type": self.lane_type,
            "acquired_at": self.acquired_at,
            "expires_at": self.expires_at,
            "status": self.status,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WriterLockRecord":
        return cls(
            lock_id=data.get("lock_id", ""),
            repo=data.get("repo", ""),
            batch_id=data.get("batch_id", ""),
            writer_id=data.get("writer_id", ""),
            lane_type=data.get("lane_type", "writer"),
            acquired_at=data.get("acquired_at", ""),
            expires_at=data.get("expires_at", ""),
            status=data.get("status", "missing"),
            metadata=data.get("metadata", {}),
        )
    
    def is_expired(self) -> bool:
        """检查锁是否已过期"""
        if not self.expires_at:
            return False
        try:
            expires = datetime.fromisoformat(self.expires_at)
            return datetime.now() > expires
        except (ValueError, TypeError):
            return False


class SingleWriterGuard:
    """
    Single-Writer Guard — 管理 single-writer 锁。
    
    核心方法：
    - acquire_lock(): 获取写锁
    - release_lock(): 释放写锁
    - check_conflict(): 检查写冲突
    - get_active_lock(): 获取当前活跃锁
    - cleanup_expired(): 清理过期锁
    """
    
    def __init__(self, timeout_seconds: int = DEFAULT_LOCK_TIMEOUT_SECONDS):
        """
        初始化 single-writer guard。
        
        Args:
            timeout_seconds: 锁超时时间（秒）
        """
        self.timeout_seconds = timeout_seconds
        _ensure_lock_dir()
    
    def _read_lock_record(self, repo: str, batch_id: str = "") -> Optional[WriterLockRecord]:
        """
        读取锁记录。
        
        Args:
            repo: 仓库标识
            batch_id: Batch ID（可选）
        
        Returns:
            WriterLockRecord 或 None
        """
        lock_path = _lock_file(repo, batch_id)
        
        if not lock_path.exists():
            return None
        
        try:
            with open(lock_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return WriterLockRecord.from_dict(data)
        except (json.JSONDecodeError, KeyError, ValueError):
            return None
    
    def _write_lock_record(
        self,
        record: WriterLockRecord,
        repo: str,
        batch_id: str = "",
    ) -> bool:
        """
        写入锁记录（带文件锁）。
        
        Args:
            record: Lock record
            repo: 仓库标识
            batch_id: Batch ID（可选）
        
        Returns:
            True 如果写入成功
        """
        lock_path = _lock_file(repo, batch_id)
        tmp_path = lock_path.with_suffix(".tmp")
        
        try:
            # 使用文件锁防止并发写入
            with open(tmp_path, "w", encoding="utf-8") as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    json.dump(record.to_dict(), f, ensure_ascii=False, indent=2)
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            
            # 原子替换
            tmp_path.replace(lock_path)
            return True
        except (IOError, OSError):
            if tmp_path.exists():
                tmp_path.unlink()
            return False
    
    def acquire_lock(
        self,
        repo: str,
        writer_id: str,
        batch_id: str = "",
        lane_type: Literal["writer", "reader"] = "writer",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> tuple[bool, str, Optional[WriterLockRecord]]:
        """
        获取写锁。
        
        Args:
            repo: 仓库标识
            writer_id: Writer ID
            batch_id: Batch ID（可选）
            lane_type: Lane 类型 (writer / reader)
            metadata: 额外元数据
        
        Returns:
            (success, reason, lock_record)
        """
        # Reader 不占锁，直接允许
        if lane_type == "reader":
            record = WriterLockRecord(
                lock_id=_generate_lock_id(),
                repo=repo,
                batch_id=batch_id,
                writer_id=writer_id,
                lane_type="reader",
                acquired_at=_iso_now(),
                expires_at="",  # Reader 不过期
                status="active",
                metadata=metadata or {},
            )
            return True, "reader_lock_always_allowed", record
        
        # 检查是否有现有锁
        existing = self._read_lock_record(repo, batch_id)
        
        if existing is not None:
            # 检查是否是同一个 writer（可重入）
            if existing.writer_id == writer_id and not existing.is_expired():
                # 刷新过期时间
                existing.expires_at = (
                    datetime.now() + timedelta(seconds=self.timeout_seconds)
                ).isoformat()
                self._write_lock_record(existing, repo, batch_id)
                return True, "lock_reacquired", existing
            
            # 检查是否已过期
            if existing.is_expired():
                # 过期锁可被覆盖
                pass
            else:
                # 活跃锁冲突
                return (
                    False,
                    f"writer_conflict_with_{existing.writer_id}",
                    existing,
                )
        
        # 创建新锁
        record = WriterLockRecord(
            lock_id=_generate_lock_id(),
            repo=repo,
            batch_id=batch_id,
            writer_id=writer_id,
            lane_type="writer",
            acquired_at=_iso_now(),
            expires_at=(datetime.now() + timedelta(seconds=self.timeout_seconds)).isoformat(),
            status="active",
            metadata=metadata or {},
        )
        
        if self._write_lock_record(record, repo, batch_id):
            return True, "lock_acquired", record
        else:
            return False, "failed_to_write_lock_file", None
    
    def release_lock(
        self,
        repo: str,
        writer_id: str,
        batch_id: str = "",
    ) -> tuple[bool, str]:
        """
        释放写锁。
        
        Args:
            repo: 仓库标识
            writer_id: Writer ID
            batch_id: Batch ID（可选）
        
        Returns:
            (success, reason)
        """
        existing = self._read_lock_record(repo, batch_id)
        
        if existing is None:
            return False, "lock_not_found"
        
        # 检查是否是同一个 writer
        if existing.writer_id != writer_id:
            return False, f"lock_owned_by_{existing.writer_id}"
        
        # 删除锁文件
        lock_path = _lock_file(repo, batch_id)
        try:
            lock_path.unlink()
            return True, "lock_released"
        except OSError:
            return False, "failed_to_delete_lock_file"
    
    def check_writer_conflict(
        self,
        repo: str,
        current_writer_id: str,
        batch_id: str = "",
    ) -> tuple[bool, str]:
        """
        检查写冲突。
        
        Args:
            repo: 仓库标识
            current_writer_id: 当前 writer ID
            batch_id: Batch ID（可选）
        
        Returns:
            (has_conflict, reason)
        """
        existing = self._read_lock_record(repo, batch_id)
        
        if existing is None:
            return False, "no_active_lock"
        
        # 检查是否已过期
        if existing.is_expired():
            return False, "lock_expired"
        
        # 检查是否是同一个 writer
        if existing.writer_id == current_writer_id:
            return False, "same_writer_no_conflict"
        
        # 检查是否是 reader
        if existing.lane_type == "reader":
            return False, "reader_lock_no_conflict"
        
        # Writer 冲突
        return True, f"writer_conflict_with_{existing.writer_id}"
    
    def get_active_lock(
        self,
        repo: str,
        batch_id: str = "",
    ) -> Optional[WriterLockRecord]:
        """
        获取当前活跃锁。
        
        Args:
            repo: 仓库标识
            batch_id: Batch ID（可选）
        
        Returns:
            WriterLockRecord 或 None
        """
        record = self._read_lock_record(repo, batch_id)
        
        if record is None:
            return None
        
        # 更新状态
        if record.is_expired():
            record.status = "expired"
        else:
            record.status = "active"
        
        return record
    
    def cleanup_expired(self) -> int:
        """
        清理过期锁。
        
        Returns:
            清理的锁数量
        """
        cleaned = 0
        
        for lock_file in WRITER_LOCK_DIR.glob("*.lock"):
            try:
                with open(lock_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                record = WriterLockRecord.from_dict(data)
                
                if record.is_expired():
                    lock_file.unlink()
                    cleaned += 1
            except (json.JSONDecodeError, KeyError, ValueError, OSError):
                continue
        
        return cleaned


def acquire_writer_lock(
    repo: str,
    writer_id: str,
    batch_id: str = "",
    lane_type: Literal["writer", "reader"] = "writer",
    timeout_seconds: int = DEFAULT_LOCK_TIMEOUT_SECONDS,
    metadata: Optional[Dict[str, Any]] = None,
) -> tuple[bool, str, Optional[WriterLockRecord]]:
    """
    便捷函数：获取写锁。
    
    Args:
        repo: 仓库标识
        writer_id: Writer ID
        batch_id: Batch ID（可选）
        lane_type: Lane 类型
        timeout_seconds: 超时时间
        metadata: 额外元数据
    
    Returns:
        (success, reason, lock_record)
    """
    guard = SingleWriterGuard(timeout_seconds=timeout_seconds)
    return guard.acquire_lock(
        repo=repo,
        writer_id=writer_id,
        batch_id=batch_id,
        lane_type=lane_type,
        metadata=metadata,
    )


def release_writer_lock(
    repo: str,
    writer_id: str,
    batch_id: str = "",
) -> tuple[bool, str]:
    """
    便捷函数：释放写锁。
    
    Args:
        repo: 仓库标识
        writer_id: Writer ID
        batch_id: Batch ID（可选）
    
    Returns:
        (success, reason)
    """
    guard = SingleWriterGuard()
    return guard.release_lock(
        repo=repo,
        writer_id=writer_id,
        batch_id=batch_id,
    )


def check_writer_conflict(
    repo: str,
    current_writer_id: str,
    batch_id: str = "",
) -> tuple[bool, str]:
    """
    便捷函数：检查写冲突。
    
    Args:
        repo: 仓库标识
        current_writer_id: 当前 writer ID
        batch_id: Batch ID（可选）
    
    Returns:
        (has_conflict, reason)
    """
    guard = SingleWriterGuard()
    return guard.check_writer_conflict(
        repo=repo,
        current_writer_id=current_writer_id,
        batch_id=batch_id,
    )
