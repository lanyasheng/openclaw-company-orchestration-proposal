#!/usr/bin/env python3
"""
test_telemetry.py — Telemetry / SLA Metrics 测试

覆盖：
- ValidatorMetrics 数据结构
- AutoContinueMetrics 数据结构
- TelemetryRecorder 记录功能
- Validator stats 统计
- Auto-continue stats 统计
"""

import json
import os
import sys
import tempfile
import shutil
from pathlib import Path
from datetime import datetime

# 添加 runtime 路径
sys.path.insert(0, str(Path(__file__).parent.parent / "runtime" / "orchestrator"))

from telemetry import (
    ValidatorMetrics,
    AutoContinueMetrics,
    TelemetryRecorder,
    record_validator_metric,
    record_auto_continue_metric,
    get_validator_stats,
    get_auto_continue_stats,
    get_telemetry_summary,
    TELEMETRY_VERSION,
    TELEMETRY_DIR,
    _validator_metrics_file,
    _auto_continue_metrics_file,
    _ensure_telemetry_dir,
    _iso_now,
)


def test_validator_metrics_structure():
    """测试 ValidatorMetrics 数据结构"""
    metric = ValidatorMetrics(
        timestamp="2026-03-25T12:00:00",
        audit_id="validator_audit_test123",
        status="blocked_completion",
        reason="B1_pure_directory_listing",
        score=0,
        label="test-task",
        metadata={"test": "value"},
    )
    
    assert metric.timestamp == "2026-03-25T12:00:00"
    assert metric.audit_id == "validator_audit_test123"
    assert metric.status == "blocked_completion"
    assert metric.reason == "B1_pure_directory_listing"
    assert metric.score == 0
    assert metric.label == "test-task"
    
    # 序列化
    data = metric.to_dict()
    assert data["telemetry_version"] == TELEMETRY_VERSION
    assert data["status"] == "blocked_completion"
    assert data["score"] == 0
    
    print("✓ ValidatorMetrics 数据结构正常")


def test_auto_continue_metrics_structure():
    """测试 AutoContinueMetrics 数据结构"""
    metric = AutoContinueMetrics(
        timestamp="2026-03-25T12:00:00",
        receipt_id="receipt_test123",
        decision="continue_allowed",
        reason="Validator accepted + no writer conflict",
        writer_conflict=False,
        batch_id="batch_123",
        metadata={"test": "value"},
    )
    
    assert metric.receipt_id == "receipt_test123"
    assert metric.decision == "continue_allowed"
    assert metric.writer_conflict is False
    assert metric.batch_id == "batch_123"
    
    # 序列化
    data = metric.to_dict()
    assert data["telemetry_version"] == TELEMETRY_VERSION
    assert data["decision"] == "continue_allowed"
    
    print("✓ AutoContinueMetrics 数据结构正常")


def test_telemetry_recorder_initialization():
    """测试 TelemetryRecorder 初始化"""
    recorder = TelemetryRecorder()
    assert recorder is not None
    print("✓ TelemetryRecorder 初始化正常")


def test_telemetry_recorder_validator_metric():
    """测试 TelemetryRecorder 记录 validator 指标"""
    # 创建临时目录
    temp_dir = tempfile.mkdtemp()
    original_dir = TELEMETRY_DIR
    
    try:
        # 临时替换目录
        import telemetry
        telemetry.TELEMETRY_DIR = Path(temp_dir)
        telemetry._ensure_telemetry_dir()
        
        recorder = TelemetryRecorder()
        
        metric = ValidatorMetrics(
            timestamp=_iso_now(),
            audit_id="validator_audit_test_record",
            status="accepted_completion",
            reason="",
            score=5,
            label="test-task",
        )
        
        recorder.record_validator_metric(metric)
        
        # 验证文件存在
        metrics_file = _validator_metrics_file()
        assert metrics_file.exists()
        
        # 验证内容
        with open(metrics_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["audit_id"] == "validator_audit_test_record"
        assert data["status"] == "accepted_completion"
        
        print("✓ TelemetryRecorder 记录 validator 指标正常")
    
    finally:
        # 恢复原目录
        telemetry.TELEMETRY_DIR = original_dir
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_telemetry_recorder_auto_continue_metric():
    """测试 TelemetryRecorder 记录 auto-continue 指标"""
    # 创建临时目录
    temp_dir = tempfile.mkdtemp()
    original_dir = TELEMETRY_DIR
    
    try:
        # 临时替换目录
        import telemetry
        telemetry.TELEMETRY_DIR = Path(temp_dir)
        telemetry._ensure_telemetry_dir()
        
        recorder = TelemetryRecorder()
        
        metric = AutoContinueMetrics(
            timestamp=_iso_now(),
            receipt_id="receipt_test_record",
            decision="continue_blocked",
            reason="Writer conflict detected",
            writer_conflict=True,
            batch_id="batch_456",
        )
        
        recorder.record_auto_continue_metric(metric)
        
        # 验证文件存在
        metrics_file = _auto_continue_metrics_file()
        assert metrics_file.exists()
        
        # 验证内容
        with open(metrics_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["receipt_id"] == "receipt_test_record"
        assert data["decision"] == "continue_blocked"
        assert data["writer_conflict"] is True
        
        print("✓ TelemetryRecorder 记录 auto-continue 指标正常")
    
    finally:
        # 恢复原目录
        telemetry.TELEMETRY_DIR = original_dir
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_get_validator_stats():
    """测试获取 validator 统计"""
    # 创建临时目录
    temp_dir = tempfile.mkdtemp()
    original_dir = TELEMETRY_DIR
    
    try:
        # 临时替换目录
        import telemetry
        telemetry.TELEMETRY_DIR = Path(temp_dir)
        telemetry._ensure_telemetry_dir()
        
        recorder = TelemetryRecorder()
        
        # 记录多个指标
        for i in range(5):
            status = "accepted_completion" if i % 2 == 0 else "blocked_completion"
            metric = ValidatorMetrics(
                timestamp=_iso_now(),
                audit_id=f"validator_audit_stats_{i}",
                status=status,
                reason=f"reason_{i % 2}",
                score=5 if status == "accepted_completion" else 0,
                label=f"label_{i % 2}",
            )
            recorder.record_validator_metric(metric)
        
        # 获取统计
        stats = recorder.get_validator_stats()
        
        assert stats["total"] == 5
        assert stats["accepted_count"] == 3  # i=0,2,4
        assert stats["blocked_count"] == 2  # i=1,3
        assert stats["gate_count"] == 0
        assert stats["error_count"] == 0
        assert 0.0 < stats["blocked_rate"] < 1.0
        assert "reason_0" in stats["by_reason"]
        assert "reason_1" in stats["by_reason"]
        
        print("✓ 获取 validator 统计正常")
    
    finally:
        # 恢复原目录
        telemetry.TELEMETRY_DIR = original_dir
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_get_auto_continue_stats():
    """测试获取 auto-continue 统计"""
    # 创建临时目录
    temp_dir = tempfile.mkdtemp()
    original_dir = TELEMETRY_DIR
    
    try:
        # 临时替换目录
        import telemetry
        telemetry.TELEMETRY_DIR = Path(temp_dir)
        telemetry._ensure_telemetry_dir()
        
        recorder = TelemetryRecorder()
        
        # 记录多个指标
        for i in range(4):
            decision = "continue_allowed" if i % 2 == 0 else "continue_blocked"
            metric = AutoContinueMetrics(
                timestamp=_iso_now(),
                receipt_id=f"receipt_stats_{i}",
                decision=decision,
                reason=f"reason_{i % 2}",
                writer_conflict=(i == 1),
                batch_id=f"batch_{i % 2}",
            )
            recorder.record_auto_continue_metric(metric)
        
        # 获取统计
        stats = recorder.get_auto_continue_stats()
        
        assert stats["total"] == 4
        assert stats["continue_allowed_count"] == 2  # i=0,2
        assert stats["continue_blocked_count"] == 2  # i=1,3
        assert stats["writer_conflict_count"] == 1  # i=1
        assert 0.0 < stats["continue_rate"] < 1.0
        assert "batch_0" in stats["by_batch"]
        assert "batch_1" in stats["by_batch"]
        
        print("✓ 获取 auto-continue 统计正常")
    
    finally:
        # 恢复原目录
        telemetry.TELEMETRY_DIR = original_dir
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_get_telemetry_summary():
    """测试获取 telemetry 摘要"""
    # 创建临时目录
    temp_dir = tempfile.mkdtemp()
    original_dir = TELEMETRY_DIR
    
    try:
        # 临时替换目录
        import telemetry
        telemetry.TELEMETRY_DIR = Path(temp_dir)
        telemetry._ensure_telemetry_dir()
        
        summary = get_telemetry_summary()
        
        assert summary["telemetry_version"] == TELEMETRY_VERSION
        assert "timestamp" in summary
        assert "validator" in summary
        assert "auto_continue" in summary
        assert "total" in summary["validator"]
        assert "total" in summary["auto_continue"]
        
        print("✓ 获取 telemetry 摘要正常")
    
    finally:
        # 恢复原目录
        telemetry.TELEMETRY_DIR = original_dir
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_telemetry_version():
    """测试版本号"""
    assert TELEMETRY_VERSION == "telemetry_v1"
    print("✓ Telemetry 版本号正常")


def test_empty_stats():
    """测试空统计"""
    # 创建临时目录
    temp_dir = tempfile.mkdtemp()
    original_dir = TELEMETRY_DIR
    
    try:
        # 临时替换目录
        import telemetry
        telemetry.TELEMETRY_DIR = Path(temp_dir)
        telemetry._ensure_telemetry_dir()
        
        # 不记录任何指标，直接获取统计
        validator_stats = get_validator_stats()
        auto_continue_stats = get_auto_continue_stats()
        
        assert validator_stats["total"] == 0
        assert validator_stats["blocked_rate"] == 0.0
        assert auto_continue_stats["total"] == 0
        assert auto_continue_stats["continue_rate"] == 0.0
        
        print("✓ 空统计正常")
    
    finally:
        # 恢复原目录
        telemetry.TELEMETRY_DIR = original_dir
        shutil.rmtree(temp_dir, ignore_errors=True)


def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("Telemetry / SLA Metrics 测试")
    print("=" * 60)
    
    tests = [
        test_validator_metrics_structure,
        test_auto_continue_metrics_structure,
        test_telemetry_recorder_initialization,
        test_telemetry_recorder_validator_metric,
        test_telemetry_recorder_auto_continue_metric,
        test_get_validator_stats,
        test_get_auto_continue_stats,
        test_get_telemetry_summary,
        test_telemetry_version,
        test_empty_stats,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"✗ {test.__name__} 失败：{e}")
            failed += 1
        except Exception as e:
            print(f"✗ {test.__name__} 错误：{e}")
            failed += 1
    
    print("=" * 60)
    print(f"测试结果：{passed} 通过，{failed} 失败")
    print("=" * 60)
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
