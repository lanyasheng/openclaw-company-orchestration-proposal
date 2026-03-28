#!/usr/bin/env python3
"""
test_tmux_status_sync.py — Observability Batch 3 测试

测试 tmux 状态同步模块的功能和集成。
"""

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# 导入被测模块 - 添加 orchestrator 目录到路径
ORCHESTRATOR_DIR = Path(__file__).parent.parent.parent / "orchestrator"
if str(ORCHESTRATOR_DIR) not in sys.path:
    sys.path.insert(0, str(ORCHESTRATOR_DIR))

# 确保模块可以导入
try:
    from tmux_status_sync import (
        TMUX_SOCKET_DIR,
        TMUX_STATUS_MAP,
        TmuxStatusSync,
        TmuxSessionState,
        get_tmux_status,
        list_tmux_cards,
        register_tmux_card,
        sync_tmux_session,
        update_tmux_card,
    )
    from observability_card import (
        CARD_DIR,
        ObservabilityCardManager,
        _card_file,
        delete_card,
        get_card,
    )
except ImportError as e:
    # pytest 运行时可能需要不同的路径
    pytest.skip(f"Module import failed: {e}", allow_module_level=True)


@pytest.fixture
def clean_test_cards():
    """清理测试卡片"""
    test_ids = ["test_tmux_001", "test_tmux_002", "test_tmux_003"]
    yield test_ids
    for task_id in test_ids:
        try:
            delete_card(task_id)
        except Exception:
            pass


@pytest.fixture
def mock_tmux_env(tmp_path):
    """创建模拟 tmux 环境"""
    socket_dir = tmp_path / "tmux-sockets"
    socket_dir.mkdir()
    socket_file = socket_dir / "clawdbot.sock"
    socket_file.touch()
    
    return {
        "socket_dir": socket_dir,
        "socket": socket_file,
    }


class TestTmuxSessionState:
    """测试 TmuxSessionState 数据类"""
    
    def test_create_state(self):
        state = TmuxSessionState(
            session="cc-test",
            status="running",
            mapped_stage="running",
            report_exists=False,
            session_alive=True,
            last_checked="2026-03-28T16:00:00",
            metadata={},
        )
        
        assert state.session == "cc-test"
        assert state.status == "running"
        assert state.mapped_stage == "running"
        assert state.report_exists is False
        assert state.session_alive is True
    
    def test_to_dict(self):
        state = TmuxSessionState(
            session="cc-test",
            status="likely_done",
            mapped_stage="completed",
            report_exists=True,
            session_alive=True,
            last_checked="2026-03-28T16:00:00",
            metadata={"reason": "report_exists"},
        )
        
        d = state.to_dict()
        assert d["session"] == "cc-test"
        assert d["status"] == "likely_done"
        assert d["mapped_stage"] == "completed"
        assert d["report_exists"] is True
        assert d["metadata"]["reason"] == "report_exists"


class TestTmuxStatusMap:
    """测试 tmux 状态映射"""
    
    def test_running_mapping(self):
        assert TMUX_STATUS_MAP["running"] == "running"
        assert TMUX_STATUS_MAP["idle"] == "idle"
    
    def test_completion_mapping(self):
        assert TMUX_STATUS_MAP["likely_done"] == "completed"
        assert TMUX_STATUS_MAP["done_session_ended"] == "completed"
    
    def test_failure_mapping(self):
        assert TMUX_STATUS_MAP["dead"] == "failed"
    
    def test_stuck_mapping(self):
        # stuck 视为 running 但需要告警
        assert TMUX_STATUS_MAP["stuck"] == "running"


class TestTmuxStatusSync:
    """测试 TmuxStatusSync 类"""
    
    def test_init(self, mock_tmux_env):
        syncer = TmuxStatusSync(socket_dir=mock_tmux_env["socket_dir"])
        assert syncer.socket_dir == mock_tmux_env["socket_dir"]
        assert syncer.card_manager is not None
    
    def test_get_status_session_dead_no_report(self, mock_tmux_env):
        syncer = TmuxStatusSync(socket_dir=mock_tmux_env["socket_dir"])
        
        with patch.object(syncer, '_check_session_alive', return_value=False):
            with patch.object(syncer, '_check_remote_files_exist', return_value=False):
                state = syncer.get_status(
                    session="cc-dead",
                    socket=mock_tmux_env["socket"],
                )
                
                assert state.session == "cc-dead"
                assert state.status == "dead"
                assert state.mapped_stage == "failed"
                assert state.session_alive is False
                assert state.report_exists is False
    
    def test_get_status_session_dead_with_report(self, mock_tmux_env):
        syncer = TmuxStatusSync(socket_dir=mock_tmux_env["socket_dir"])
        
        # Mock session check and file existence
        with patch.object(syncer, '_check_session_alive', return_value=False):
            with patch.object(Path, 'exists', return_value=True):
                state = syncer.get_status(
                    session="cc-done",
                    socket=mock_tmux_env["socket"],
                )
                
                # When session is dead but report exists, status should be done_session_ended
                assert state.status == "done_session_ended"
                assert state.mapped_stage == "completed"
                assert state.report_exists is True
                assert state.session_alive is False
    
    def test_get_status_report_exists(self, mock_tmux_env):
        syncer = TmuxStatusSync(socket_dir=mock_tmux_env["socket_dir"])
        
        # Mock session alive and report exists
        with patch.object(syncer, '_check_session_alive', return_value=True):
            with patch.object(Path, 'exists', return_value=True):
                state = syncer.get_status(
                    session="cc-likely-done",
                    socket=mock_tmux_env["socket"],
                )
                
                assert state.status == "likely_done"
                assert state.mapped_stage == "completed"
                assert state.session_alive is True
                assert state.report_exists is True
    
    def test_get_status_running(self, mock_tmux_env):
        syncer = TmuxStatusSync(socket_dir=mock_tmux_env["socket_dir"])
        
        with patch.object(syncer, '_check_session_alive', return_value=True):
            with patch.object(syncer, '_check_remote_files_exist', return_value=False):
                with patch.object(syncer, '_capture_pane_output', return_value="Thinking..."):
                    state = syncer.get_status(
                        session="cc-running",
                        socket=mock_tmux_env["socket"],
                    )
                    
                    assert state.status == "running"
                    assert state.mapped_stage == "running"
                    assert state.session_alive is True
    
    def test_get_status_idle(self, mock_tmux_env):
        syncer = TmuxStatusSync(socket_dir=mock_tmux_env["socket_dir"])
        
        with patch.object(syncer, '_check_session_alive', return_value=True):
            with patch.object(syncer, '_check_remote_files_exist', return_value=False):
                with patch.object(syncer, '_capture_pane_output', return_value="❯ "):
                    state = syncer.get_status(
                        session="cc-idle",
                        socket=mock_tmux_env["socket"],
                    )
                    
                    assert state.status == "idle"
                    assert state.mapped_stage == "idle"
    
    def test_get_status_stuck(self, mock_tmux_env):
        syncer = TmuxStatusSync(socket_dir=mock_tmux_env["socket_dir"])
        
        with patch.object(syncer, '_check_session_alive', return_value=True):
            with patch.object(syncer, '_check_remote_files_exist', return_value=False):
                with patch.object(syncer, '_capture_pane_output', return_value="Error: something failed"):
                    state = syncer.get_status(
                        session="cc-stuck",
                        socket=mock_tmux_env["socket"],
                    )
                    
                    assert state.status == "stuck"
                    assert state.mapped_stage == "running"  # stuck 映射为 running
    
    def test_classify_pane_status_completion(self):
        syncer = TmuxStatusSync()
        
        assert syncer._classify_pane_status("REPORT_JSON=/tmp/report.json") == "likely_done"
        assert syncer._classify_pane_status("Task Completed") == "likely_done"
        assert syncer._classify_pane_status("Co-Authored-By: Claude") == "likely_done"
    
    def test_classify_pane_status_error(self):
        syncer = TmuxStatusSync()
        
        assert syncer._classify_pane_status("✗ Failed") == "stuck"
        assert syncer._classify_pane_status("Error: timeout") == "stuck"
        assert syncer._classify_pane_status("FAILED: tests") == "stuck"
    
    def test_classify_pane_status_execution(self):
        syncer = TmuxStatusSync()
        
        assert syncer._classify_pane_status("Thinking...") == "running"
        assert syncer._classify_pane_status("Running tests") == "running"
        assert syncer._classify_pane_status("Bash(npm test)") == "running"
    
    def test_classify_pane_status_idle(self):
        syncer = TmuxStatusSync()
        
        assert syncer._classify_pane_status("❯ ") == "idle"
    
    def test_classify_pane_status_default(self):
        syncer = TmuxStatusSync()
        
        assert syncer._classify_pane_status("random output") == "running"
        assert syncer._classify_pane_status("") == "running"


class TestTmuxStatusSyncCardIntegration:
    """测试 tmux 状态同步与状态卡集成"""
    
    def test_register_tmux_card(self, clean_test_cards, mock_tmux_env):
        syncer = TmuxStatusSync(socket_dir=mock_tmux_env["socket_dir"])
        
        card = syncer.register_task(
            task_id="test_tmux_001",
            label="test-register",
            owner="main",
            scenario="custom",
            promised_eta="2026-03-28T18:00:00",
            socket=mock_tmux_env["socket"],
        )
        
        assert card.task_id == "test_tmux_001"
        assert card.executor == "tmux"
        assert card.stage == "dispatch"
        assert card.promise_anchor["anchor_type"] == "tmux_session"
        assert card.promise_anchor["anchor_value"] == "cc-test-register"
        assert card.attach_info["session_id"] == "cc-test-register"
        assert card.attach_info["tmux_socket"] == str(mock_tmux_env["socket"])
    
    def test_sync_to_card_existing(self, clean_test_cards, mock_tmux_env):
        syncer = TmuxStatusSync(socket_dir=mock_tmux_env["socket_dir"])
        
        # 先创建卡片
        syncer.register_task(
            task_id="test_tmux_002",
            label="test-sync",
            owner="main",
            scenario="custom",
            promised_eta="2026-03-28T18:00:00",
        )
        
        # Mock tmux 状态为 running
        with patch.object(syncer, 'get_status') as mock_get:
            mock_get.return_value = TmuxSessionState(
                session="cc-test-sync",
                status="running",
                mapped_stage="running",
                report_exists=False,
                session_alive=True,
                last_checked="2026-03-28T16:00:00",
                metadata={},
            )
            
            updated = syncer.sync_to_card(
                task_id="test_tmux_002",
                session="cc-test-sync",
            )
            
            assert updated is not None
            assert updated.stage == "running"
            assert updated.metadata.get("tmux_status") == "running"
    
    def test_sync_to_card_not_exists_no_force(self, mock_tmux_env):
        syncer = TmuxStatusSync(socket_dir=mock_tmux_env["socket_dir"])
        
        # 卡片不存在，force=False
        result = syncer.sync_to_card(
            task_id="non_existent",
            session="cc-non-existent",
            force=False,
        )
        
        assert result is None
    
    def test_list_active_sessions(self, clean_test_cards, mock_tmux_env):
        syncer = TmuxStatusSync(socket_dir=mock_tmux_env["socket_dir"])
        
        # 创建两个 tmux 卡片
        syncer.register_task(
            task_id="test_tmux_001",
            label="test-list-1",
            owner="main",
            scenario="custom",
            promised_eta="2026-03-28T18:00:00",
        )
        syncer.register_task(
            task_id="test_tmux_002",
            label="test-list-2",
            owner="trading",
            scenario="trading_roundtable",
            promised_eta="2026-03-28T18:00:00",
        )
        
        # Mock get_status
        with patch.object(syncer, 'get_status') as mock_get:
            mock_get.return_value = TmuxSessionState(
                session="cc-test",
                status="running",
                mapped_stage="running",
                report_exists=False,
                session_alive=True,
                last_checked="2026-03-28T16:00:00",
                metadata={},
            )
            
            # 列出所有
            all_sessions = syncer.list_active_sessions(limit=10)
            assert len(all_sessions) >= 2
            
            # 按 owner 过滤
            main_sessions = syncer.list_active_sessions(owner="main", limit=10)
            assert len(main_sessions) >= 1


class TestConvenienceFunctions:
    """测试便捷函数"""
    
    def test_register_tmux_card_function(self, clean_test_cards):
        card = register_tmux_card(
            task_id="test_tmux_003",
            label="test-func",
            owner="main",
            scenario="custom",
            promised_eta="2026-03-28T18:00:00",
        )
        
        assert card.task_id == "test_tmux_003"
        assert card.executor == "tmux"
    
    def test_get_tmux_status_function(self):
        with patch('tmux_status_sync.TmuxStatusSync') as MockSync:
            mock_instance = MockSync.return_value
            mock_instance.get_status.return_value = TmuxSessionState(
                session="cc-mock",
                status="running",
                mapped_stage="running",
                report_exists=False,
                session_alive=True,
                last_checked="2026-03-28T16:00:00",
                metadata={},
            )
            
            state = get_tmux_status(session="cc-mock")
            assert state.status == "running"
    
    def test_list_tmux_cards_function(self):
        with patch('tmux_status_sync.TmuxStatusSync') as MockSync:
            mock_instance = MockSync.return_value
            mock_instance.list_active_sessions.return_value = [
                {"task_id": "test_001", "session": "cc-test", "state": {"status": "running"}}
            ]
            
            sessions = list_tmux_cards(owner="main", limit=10)
            assert len(sessions) == 1


class TestTmuxStatusSyncSSH:
    """测试 SSH 远程 tmux 支持"""
    
    def test_get_status_ssh_target(self, mock_tmux_env):
        syncer = TmuxStatusSync(socket_dir=mock_tmux_env["socket_dir"])
        
        # SSH target 但没有 ssh_host 应该报错
        with pytest.raises(ValueError, match="ssh_host"):
            syncer.get_status(
                session="cc-ssh-test",
                target="ssh",
            )
    
    def test_check_session_alive_ssh(self, mock_tmux_env):
        syncer = TmuxStatusSync(socket_dir=mock_tmux_env["socket_dir"])
        
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            
            alive = syncer._check_session_alive(
                session="cc-ssh",
                socket=mock_tmux_env["socket"],
                target="ssh",
                ssh_host="test-host",
            )
            
            assert alive is True
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            assert "ssh" in call_args
            assert "test-host" in call_args
    
    def test_check_remote_files_exist(self, mock_tmux_env):
        syncer = TmuxStatusSync(socket_dir=mock_tmux_env["socket_dir"])
        
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            
            exists = syncer._check_remote_files_exist(
                ssh_host="test-host",
                paths=[Path("/tmp/report.json"), Path("/tmp/report.md")],
            )
            
            assert exists is True


class TestTmuxStatusSyncEdgeCases:
    """测试边界情况"""
    
    def test_session_name_with_cc_prefix(self, clean_test_cards, mock_tmux_env):
        syncer = TmuxStatusSync(socket_dir=mock_tmux_env["socket_dir"])
        
        # label 已经有 cc- 前缀
        card = syncer.register_task(
            task_id="test_tmux_001",
            label="cc-custom-prefix",
            owner="main",
            scenario="custom",
            promised_eta="2026-03-28T18:00:00",
        )
        
        assert card.promise_anchor["anchor_value"] == "cc-custom-prefix"
    
    def test_session_name_without_cc_prefix(self, clean_test_cards, mock_tmux_env):
        syncer = TmuxStatusSync(socket_dir=mock_tmux_env["socket_dir"])
        
        # label 没有 cc- 前缀，自动添加
        card = syncer.register_task(
            task_id="test_tmux_002",
            label="no-prefix",
            owner="main",
            scenario="custom",
            promised_eta="2026-03-28T18:00:00",
        )
        
        assert card.promise_anchor["anchor_value"] == "cc-no-prefix"
    
    def test_timeout_handling(self, mock_tmux_env):
        syncer = TmuxStatusSync(socket_dir=mock_tmux_env["socket_dir"])
        
        with patch('subprocess.run', side_effect=subprocess.TimeoutExpired(cmd="tmux", timeout=5)):
            alive = syncer._check_session_alive(
                session="cc-timeout",
                socket=mock_tmux_env["socket"],
                target="local",
                ssh_host=None,
            )
            
            assert alive is False  # 超时视为不存活
    
    def test_capture_pane_output_timeout(self, mock_tmux_env):
        syncer = TmuxStatusSync(socket_dir=mock_tmux_env["socket_dir"])
        
        with patch('subprocess.run', side_effect=subprocess.TimeoutExpired(cmd="tmux", timeout=5)):
            output = syncer._capture_pane_output(
                session="cc-timeout",
                socket=mock_tmux_env["socket"],
                target="local",
                ssh_host=None,
            )
            
            assert output == ""  # 超时返回空字符串


class TestTmuxStatusSyncIntegration:
    """集成测试：验证 tmux session 自动注册到索引"""
    
    def test_full_workflow(self, clean_test_cards, mock_tmux_env):
        """完整工作流测试：注册 -> 查询 -> 更新 -> 验证"""
        syncer = TmuxStatusSync(socket_dir=mock_tmux_env["socket_dir"])
        
        # 1. 注册任务
        card = syncer.register_task(
            task_id="test_tmux_001",
            label="integration-test",
            owner="main",
            scenario="custom",
            promised_eta="2026-03-28T18:00:00",
            socket=mock_tmux_env["socket"],
        )
        
        assert card.task_id == "test_tmux_001"
        assert card.executor == "tmux"
        assert card.stage == "dispatch"
        
        # 2. 验证卡片已创建
        retrieved = get_card("test_tmux_001")
        assert retrieved is not None
        assert retrieved.executor == "tmux"
        
        # 3. 模拟状态更新为 running
        with patch.object(syncer, 'get_status') as mock_get:
            mock_get.return_value = TmuxSessionState(
                session="cc-integration-test",
                status="running",
                mapped_stage="running",
                report_exists=False,
                session_alive=True,
                last_checked="2026-03-28T16:00:00",
                metadata={"test": "value"},
            )
            
            updated = syncer.sync_to_card(
                task_id="test_tmux_001",
                session="cc-integration-test",
            )
            
            assert updated is not None
            assert updated.stage == "running"
            assert updated.metadata.get("tmux_status") == "running"
        
        # 4. 验证状态已更新
        final_card = get_card("test_tmux_001")
        assert final_card.stage == "running"
        assert final_card.attach_info.get("session_id") == "cc-integration-test"
        
        # 5. 模拟完成状态
        with patch.object(syncer, 'get_status') as mock_get:
            mock_get.return_value = TmuxSessionState(
                session="cc-integration-test",
                status="likely_done",
                mapped_stage="completed",
                report_exists=True,
                session_alive=True,
                last_checked="2026-03-28T17:00:00",
                metadata={},
            )
            
            updated = syncer.sync_to_card(
                task_id="test_tmux_001",
                session="cc-integration-test",
            )
            
            assert updated.stage == "completed"
        
        # 6. 验证最终状态
        final_card = get_card("test_tmux_001")
        assert final_card.stage == "completed"
        assert final_card.metadata.get("tmux_status") == "likely_done"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
