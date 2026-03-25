#!/usr/bin/env python3
"""
test_single_writer_guard.py — Single-Writer Guard 测试

测试覆盖：
- 同一 repo 只能有一个 writer lane 持锁
- read-only lane 不占 writer 锁
- 锁超时自动释放
- writer 冲突检测

执行命令：
    python -m pytest tests/orchestrator/test_single_writer_guard.py -v
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

# Add orchestrator to path
ORCHESTRATOR_DIR = Path(__file__).resolve().parents[2] / "runtime" / "orchestrator"
if str(ORCHESTRATOR_DIR) not in sys.path:
    sys.path.insert(0, str(ORCHESTRATOR_DIR))

from single_writer_guard import (
    SingleWriterGuard,
    WriterLockRecord,
    WriterLockStatus,
    acquire_writer_lock,
    release_writer_lock,
    check_writer_conflict,
    WRITER_LOCK_DIR,
    DEFAULT_LOCK_TIMEOUT_SECONDS,
)


@pytest.fixture(autouse=True)
def isolated_lock_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """隔离的锁环境
    
    确保每个测试使用独立的锁目录，避免测试间污染。
    """
    lock_dir = tmp_path / "writer_locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    
    monkeypatch.setenv("OPENCLAW_WRITER_LOCK_DIR", str(lock_dir))
    
    # 重新加载模块以使用新的目录
    import importlib
    import single_writer_guard
    
    importlib.reload(single_writer_guard)
    
    # 更新全局变量
    single_writer_guard.WRITER_LOCK_DIR = lock_dir
    
    yield {
        "lock_dir": lock_dir,
    }
    
    # 清理
    import shutil
    if lock_dir.exists():
        shutil.rmtree(lock_dir, ignore_errors=True)


class TestSingleWriterGuard_BasicLock:
    """测试基本锁操作"""
    
    def test_acquire_writer_lock_success(self):
        """场景：成功获取 writer 锁"""
        guard = SingleWriterGuard(timeout_seconds=60)
        
        success, reason, record = guard.acquire_lock(
            repo="test-repo",
            writer_id="writer_001",
            batch_id="batch_001",
        )
        
        assert success is True
        assert "acquired" in reason.lower()
        assert record is not None
        assert record.lock_id.startswith("lock_")
        assert record.repo == "test-repo"
        assert record.batch_id == "batch_001"
        assert record.writer_id == "writer_001"
        assert record.lane_type == "writer"
        assert record.status == "active"
        
        print("✅ 场景 1 验证通过：成功获取 writer 锁")
    
    def test_release_writer_lock_success(self):
        """场景：成功释放 writer 锁"""
        guard = SingleWriterGuard(timeout_seconds=60)
        
        # 先获取锁
        success, _, record = guard.acquire_lock(
            repo="test-repo",
            writer_id="writer_001",
            batch_id="batch_001",
        )
        assert success is True
        
        # 释放锁
        success, reason = guard.release_lock(
            repo="test-repo",
            writer_id="writer_001",
            batch_id="batch_001",
        )
        
        assert success is True
        assert "released" in reason.lower()
        
        # 验证锁文件已删除
        from single_writer_guard import _lock_file
        lock_path = _lock_file("test-repo", "batch_001")
        assert not lock_path.exists()
        
        print("✅ 场景 2 验证通过：成功释放 writer 锁")
    
    def test_reacquire_lock_by_same_writer(self):
        """场景：同一 writer 可重新获取锁（可重入）"""
        guard = SingleWriterGuard(timeout_seconds=60)
        
        # 第一次获取
        success1, _, record1 = guard.acquire_lock(
            repo="test-repo",
            writer_id="writer_001",
            batch_id="batch_001",
        )
        assert success1 is True
        
        # 第二次获取（同一 writer）
        success2, reason2, record2 = guard.acquire_lock(
            repo="test-repo",
            writer_id="writer_001",
            batch_id="batch_001",
        )
        
        assert success2 is True
        assert "reacquired" in reason2.lower()
        assert record2 is not None
        
        print("✅ 场景 3 验证通过：同一 writer 可重入锁")


class TestSingleWriterGuard_Conflict:
    """测试 writer 冲突"""
    
    def test_writer_conflict_different_writer(self):
        """场景：不同 writer 冲突"""
        guard = SingleWriterGuard(timeout_seconds=60)
        
        # Writer 1 获取锁
        success1, _, record1 = guard.acquire_lock(
            repo="test-repo",
            writer_id="writer_001",
            batch_id="batch_001",
        )
        assert success1 is True
        
        # Writer 2 尝试获取锁（应该失败）
        success2, reason2, record2 = guard.acquire_lock(
            repo="test-repo",
            writer_id="writer_002",
            batch_id="batch_001",
        )
        
        assert success2 is False
        assert "conflict" in reason2.lower()
        assert "writer_001" in reason2
        assert record2 is not None  # 返回现有锁记录
        
        print("✅ 场景 4 验证通过：不同 writer 冲突")
    
    def test_check_writer_conflict_no_conflict(self):
        """场景：无 writer 冲突"""
        guard = SingleWriterGuard(timeout_seconds=60)
        
        # 没有锁
        has_conflict, reason = guard.check_writer_conflict(
            repo="test-repo",
            current_writer_id="writer_001",
            batch_id="batch_001",
        )
        
        assert has_conflict is False
        assert "no_active_lock" in reason.lower()
        
        print("✅ 场景 5 验证通过：无 writer 冲突")
    
    def test_check_writer_conflict_same_writer(self):
        """场景：同一 writer 无冲突"""
        guard = SingleWriterGuard(timeout_seconds=60)
        
        # Writer 1 获取锁
        guard.acquire_lock(
            repo="test-repo",
            writer_id="writer_001",
            batch_id="batch_001",
        )
        
        # 检查冲突（同一 writer）
        has_conflict, reason = guard.check_writer_conflict(
            repo="test-repo",
            current_writer_id="writer_001",
            batch_id="batch_001",
        )
        
        assert has_conflict is False
        assert "same_writer" in reason.lower()
        
        print("✅ 场景 6 验证通过：同一 writer 无冲突")
    
    def test_check_writer_conflict_different_writer(self):
        """场景：不同 writer 有冲突"""
        guard = SingleWriterGuard(timeout_seconds=60)
        
        # Writer 1 获取锁
        guard.acquire_lock(
            repo="test-repo",
            writer_id="writer_001",
            batch_id="batch_001",
        )
        
        # 检查冲突（不同 writer）
        has_conflict, reason = guard.check_writer_conflict(
            repo="test-repo",
            current_writer_id="writer_002",
            batch_id="batch_001",
        )
        
        assert has_conflict is True
        assert "conflict" in reason.lower()
        assert "writer_001" in reason
        
        print("✅ 场景 7 验证通过：不同 writer 有冲突")


class TestSingleWriterGuard_ReaderLane:
    """测试 reader lane"""
    
    def test_reader_lane_no_lock_needed(self):
        """场景：reader lane 不占 writer 锁"""
        guard = SingleWriterGuard(timeout_seconds=60)
        
        success, reason, record = guard.acquire_lock(
            repo="test-repo",
            writer_id="reader_001",
            batch_id="batch_001",
            lane_type="reader",
        )
        
        assert success is True
        assert "reader" in reason.lower()
        assert record is not None
        assert record.lane_type == "reader"
        
        print("✅ 场景 8 验证通过：reader lane 不占 writer 锁")
    
    def test_reader_then_writer_no_conflict(self):
        """场景：reader 之后 writer 可获取锁"""
        guard = SingleWriterGuard(timeout_seconds=60)
        
        # Reader 获取锁
        guard.acquire_lock(
            repo="test-repo",
            writer_id="reader_001",
            batch_id="batch_001",
            lane_type="reader",
        )
        
        # Writer 获取锁（应该成功，reader 不占锁）
        success, reason, record = guard.acquire_lock(
            repo="test-repo",
            writer_id="writer_001",
            batch_id="batch_001",
            lane_type="writer",
        )
        
        assert success is True
        assert "acquired" in reason.lower()
        assert record.lane_type == "writer"
        
        print("✅ 场景 9 验证通过：reader 之后 writer 可获取锁")


class TestSingleWriterGuard_Timeout:
    """测试锁超时"""
    
    def test_lock_expires(self):
        """场景：锁超时自动过期"""
        # 使用非常短的超时时间（1 秒）
        guard = SingleWriterGuard(timeout_seconds=1)
        
        # 获取锁
        success, _, record = guard.acquire_lock(
            repo="test-repo",
            writer_id="writer_001",
            batch_id="batch_001",
        )
        assert success is True
        
        # 等待超时
        time.sleep(1.5)
        
        # 检查锁是否过期
        assert record.is_expired() is True
        
        # 其他 writer 现在可以获取锁
        success2, reason2, record2 = guard.acquire_lock(
            repo="test-repo",
            writer_id="writer_002",
            batch_id="batch_001",
        )
        
        assert success2 is True
        assert "acquired" in reason2.lower()
        
        print("✅ 场景 10 验证通过：锁超时自动过期")
    
    def test_cleanup_expired_locks(self):
        """场景：清理过期锁"""
        guard = SingleWriterGuard(timeout_seconds=1)
        
        # 获取多个锁
        guard.acquire_lock(repo="repo1", writer_id="w1", batch_id="b1")
        guard.acquire_lock(repo="repo2", writer_id="w2", batch_id="b2")
        guard.acquire_lock(repo="repo3", writer_id="w3", batch_id="b3")
        
        # 等待超时
        time.sleep(1.5)
        
        # 清理过期锁
        cleaned = guard.cleanup_expired()
        
        assert cleaned == 3
        
        # 验证锁文件已删除
        assert len(list(WRITER_LOCK_DIR.glob("*.lock"))) == 0
        
        print("✅ 场景 11 验证通过：清理过期锁")


class TestSingleWriterGuard_ConvenienceFunctions:
    """测试便捷函数"""
    
    def test_acquire_writer_lock_function(self):
        """测试 acquire_writer_lock 便捷函数"""
        success, reason, record = acquire_writer_lock(
            repo="test-repo",
            writer_id="writer_001",
            batch_id="batch_001",
            timeout_seconds=60,
        )
        
        assert success is True
        assert record is not None
        
        print("✅ 场景 12 验证通过：acquire_writer_lock 便捷函数")
    
    def test_release_writer_lock_function(self):
        """测试 release_writer_lock 便捷函数"""
        # 先获取锁
        acquire_writer_lock(
            repo="test-repo",
            writer_id="writer_001",
            batch_id="batch_001",
        )
        
        # 释放锁
        success, reason = release_writer_lock(
            repo="test-repo",
            writer_id="writer_001",
            batch_id="batch_001",
        )
        
        assert success is True
        
        print("✅ 场景 13 验证通过：release_writer_lock 便捷函数")
    
    def test_check_writer_conflict_function(self):
        """测试 check_writer_conflict 便捷函数"""
        # 没有锁
        has_conflict, reason = check_writer_conflict(
            repo="test-repo",
            current_writer_id="writer_001",
            batch_id="batch_001",
        )
        
        assert has_conflict is False
        
        print("✅ 场景 14 验证通过：check_writer_conflict 便捷函数")


class TestWriterLockRecord_Serialization:
    """测试 WriterLockRecord 序列化"""
    
    def test_to_dict_from_dict(self):
        """测试序列化和反序列化"""
        original = WriterLockRecord(
            lock_id="lock_test_001",
            repo="test-repo",
            batch_id="batch_001",
            writer_id="writer_001",
            lane_type="writer",
            acquired_at=datetime.now().isoformat(),
            expires_at=(datetime.now() + timedelta(minutes=5)).isoformat(),
            status="active",
            metadata={"test": "value"},
        )
        
        data = original.to_dict()
        restored = WriterLockRecord.from_dict(data)
        
        assert restored.lock_id == original.lock_id
        assert restored.repo == original.repo
        assert restored.batch_id == original.batch_id
        assert restored.writer_id == original.writer_id
        assert restored.lane_type == original.lane_type
        assert restored.status == original.status
        assert restored.metadata == original.metadata
        
        print("✅ 序列化/反序列化验证通过")


def run_all_tests():
    """运行所有测试并输出摘要"""
    print("\n" + "="*60)
    print("Single-Writer Guard 测试报告")
    print("="*60)
    
    # 运行 pytest
    import subprocess
    result = subprocess.run(
        [sys.executable, "-m", "pytest", __file__, "-v", "--tb=short"],
        capture_output=True,
        text=True,
    )
    
    print(result.stdout)
    if result.stderr:
        print(result.stderr)
    
    print("\n" + "="*60)
    print("测试结论")
    print("="*60)
    
    if result.returncode == 0:
        print("✅ 所有场景验证通过")
        print("\n覆盖场景：")
        print("- 同一 repo 只能有一个 writer lane 持锁 ✅")
        print("- read-only lane 不占 writer 锁 ✅")
        print("- 锁超时自动释放 ✅")
        print("- writer 冲突检测 ✅")
        print("- 便捷函数 ✅")
    else:
        print("❌ 部分场景验证失败")
        print("需要修复代码或测试")
    
    return result.returncode == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
