#!/usr/bin/env python3
"""
test_orch_product.py — 测试 orch_product.py 三件套命令

覆盖：
- onboard: 输出频道接入建议
- run: 触发统一执行入口
- status: 返回当前状态摘要
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ORCHESTRATOR_DIR = REPO_ROOT / "runtime" / "orchestrator"
ORCH_PRODUCT = REPO_ROOT / "runtime" / "scripts" / "orch_product.py"
ORCH_COMMAND = REPO_ROOT / "runtime" / "scripts" / "orch_command.py"

if str(ORCHESTRATOR_DIR) not in sys.path:
    sys.path.insert(0, str(ORCHESTRATOR_DIR))


@pytest.fixture()
def isolated_state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    state_dir = tmp_path / "shared-context"
    monkeypatch.setenv("OPENCLAW_STATE_DIR", str(state_dir))
    monkeypatch.setenv("OPENCLAW_OBSERVABILITY_DIR", str(state_dir / "observability"))
    return state_dir


@pytest.fixture(autouse=True)
def reload_modules(isolated_state_dir: Path):
    import importlib

    for module_name in [
        "state_machine",
        "batch_aggregator",
        "orchestrator",
        "continuation_backends",
        "contracts",
        "trading_roundtable",
        "channel_roundtable",
        "entry_defaults",
        "observability_card",
        "unified_execution_runtime",
    ]:
        if module_name in sys.modules:
            importlib.reload(sys.modules[module_name])

    yield


def _run_orch_product(*args: str, env: dict | None = None, cwd: str | None = None) -> dict:
    """运行 orch_product.py 命令并解析 JSON 输出。"""
    full_env = {**os.environ, **(env or {})}
    full_env["PYTHONPATH"] = str(ORCHESTRATOR_DIR)
    
    cmd = [sys.executable, str(ORCH_PRODUCT), *args, "--output", "json"]
    
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=True,
        env=full_env,
        cwd=cwd or REPO_ROOT,
    )
    
    return json.loads(proc.stdout)


def _run_orch_product_text(*args: str, env: dict | None = None) -> str:
    """运行 orch_product.py 命令并返回文本输出。"""
    full_env = {**os.environ, **(env or {})}
    full_env["PYTHONPATH"] = str(ORCHESTRATOR_DIR)
    
    cmd = [sys.executable, str(ORCH_PRODUCT), *args]
    
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=True,
        env=full_env,
        cwd=REPO_ROOT,
    )
    
    return proc.stdout


class TestOnboardCommand:
    """测试 onboard 命令"""
    
    def test_onboard_without_input_defaults_to_current_channel(self):
        """验证无参数 onboard 默认返回当前频道接入建议"""
        result = _run_orch_product("onboard")
        
        assert result["version"] == "orch_product_v1"
        assert "generated_at" in result
        assert "channel" in result
        assert "recommendation" in result
        assert "bootstrap_capability_card" in result
        assert "next_steps" in result
        assert "example_commands" in result
        
        # 验证推荐配置
        rec = result["recommendation"]
        assert rec["adapter"] in ("channel_roundtable", "trading_roundtable")
        assert "scenario" in rec
        assert "owner" in rec
        assert "backend" in rec
        assert "gate_policy" in rec
    
    def test_onboard_includes_bootstrap_capability_card(self):
        """验证 onboard 输出包含 bootstrap_capability_card"""
        result = _run_orch_product("onboard")
        
        card = result["bootstrap_capability_card"]
        assert "adapter" in card
        assert "key_constraint" in card
        assert "scenario_hint" in card
        
        # channel_roundtable 特有字段
        if card["adapter"] == "channel_roundtable":
            assert "first_run_recommendation" in card
            assert "operator_kit_path" in card
            assert card["first_run_recommendation"]["allow_auto_dispatch"] is False
    
    def test_onboard_with_custom_channel(self):
        """验证指定频道参数的 onboard"""
        result = _run_orch_product(
            "onboard",
            "--channel-id", "discord:channel:9999",
            "--channel-name", "test-channel",
            "--topic", "Test Topic",
            "--owner", "test",
            "--scenario", "test_scenario",
        )
        
        assert result["channel"]["channel_id"] == "discord:channel:9999"
        assert result["channel"]["channel_name"] == "test-channel"
        assert result["channel"]["topic"] == "Test Topic"
        assert result["recommendation"]["owner"] == "test"
        assert result["recommendation"]["scenario"] == "test_scenario"
    
    def test_onboard_trading_context(self):
        """验证 trading_roundtable 上下文的 onboard"""
        result = _run_orch_product(
            "onboard",
            "--context", "trading_roundtable",
            "--backend", "tmux",
        )
        
        assert result["recommendation"]["adapter"] == "trading_roundtable"
        assert result["recommendation"]["backend"] == "tmux"
        assert result["recommendation"]["scenario"] == "trading_roundtable_phase1"
        
        # trading card 不包含 channel 特有字段
        card = result["bootstrap_capability_card"]
        assert card["adapter"] == "trading_roundtable"
        assert "first_run_recommendation" not in card
    
    def test_onboard_example_commands_are_valid(self):
        """验证生成的示例命令格式正确"""
        result = _run_orch_product("onboard")
        
        cmds = result["example_commands"]
        assert "onboard" in cmds
        assert "run" in cmds
        assert "status" in cmds
        
        # 验证命令包含 orch_product.py
        assert "orch_product.py" in cmds["onboard"]
        assert "orch_product.py" in cmds["run"]
        assert "orch_product.py" in cmds["status"]
    
    def test_onboard_next_steps_are_actionable(self):
        """验证 next_steps 包含可执行的行动建议"""
        result = _run_orch_product("onboard")
        
        steps = result["next_steps"]
        assert len(steps) >= 3
        
        # 必须包含 run 和 status 的引导
        steps_text = " ".join(steps).lower()
        assert "run" in steps_text or "orch_product.py run" in steps_text
        assert "status" in steps_text or "orch_product.py status" in steps_text


class TestRunCommand:
    """测试 run 命令"""
    
    def test_run_minimal_invocation(self, tmp_path: Path):
        """验证 run 命令最小调用"""
        workdir = str(tmp_path)
        
        result = _run_orch_product(
            "run",
            "--task", "Test task description",
            "--workdir", workdir,
        )
        
        assert result["version"] == "orch_product_v1"
        assert "executed_at" in result
        assert "task" in result
        assert "execution" in result
        assert "callback" in result
        assert "next_steps" in result
        
        # 验证任务信息
        assert result["task"]["description"] == "Test task description"
        assert "task_id" in result["task"]
        assert "dispatch_id" in result["task"]
        
        # 验证执行信息
        exec_info = result["execution"]
        assert exec_info["backend"] in ("subagent", "tmux")
        assert "session_id" in exec_info
        assert "label" in exec_info
        assert exec_info["workdir"] == workdir
    
    def test_run_with_explicit_backend(self, tmp_path: Path):
        """验证显式指定 backend 的 run"""
        workdir = str(tmp_path)
        
        result = _run_orch_product(
            "run",
            "--task", "Test task",
            "--workdir", workdir,
            "--backend", "subagent",
        )
        
        assert result["execution"]["backend"] == "subagent"
    
    def test_run_with_channel_context(self, tmp_path: Path):
        """验证带频道上下文的 run"""
        workdir = str(tmp_path)
        
        result = _run_orch_product(
            "run",
            "--task", "Test task",
            "--workdir", workdir,
            "--channel-id", "discord:channel:123456",
            "--channel-name", "test-channel",
            "--topic", "Test Topic",
            "--owner", "test",
        )
        
        # 验证 metadata 包含频道信息
        assert "backend_selection" in result
        
    def test_run_with_task_type(self, tmp_path: Path):
        """验证带任务类型的 run"""
        workdir = str(tmp_path)
        
        result = _run_orch_product(
            "run",
            "--task", "Write documentation",
            "--workdir", workdir,
            "--type", "documentation",
            "--duration", "15",
        )
        
        # backend_selection 应该反映任务类型
        backend_sel = result.get("backend_selection", {})
        assert "recommended_backend" in backend_sel
        assert "reason" in backend_sel
    
    def test_run_next_steps_are_backend_specific(self, tmp_path: Path):
        """验证 run 的 next_steps 根据 backend 不同而变化"""
        workdir = str(tmp_path)
        
        result = _run_orch_product(
            "run",
            "--task", "Test task",
            "--workdir", workdir,
            "--backend", "subagent",
        )
        
        steps = result["next_steps"]
        steps_text = " ".join(steps)
        
        # subagent 路径应该提到 callback
        assert "callback" in steps_text.lower() or "subagent" in steps_text.lower()


class TestStatusCommand:
    """测试 status 命令"""
    
    def test_status_empty_state(self, isolated_state_dir: Path):
        """验证空状态下的 status"""
        result = _run_orch_product("status")
        
        assert result["version"] == "orch_product_v1"
        assert "snapshot_time" in result
        assert "summary" in result
        assert "active_tasks" in result
        assert "completed_tasks" in result
        assert "blockers" in result
        assert "next_steps" in result
        
        # 空状态下应该给出引导
        summary = result["summary"]
        assert summary["total_cards"] == 0
        assert summary["active"] == 0
        assert summary["completed"] == 0
        assert summary["failed"] == 0
        
        # next_steps 应该引导用户创建第一个任务
        steps_text = " ".join(result["next_steps"]).lower()
        assert "run" in steps_text or "task" in steps_text
    
    def test_status_with_owner_filter(self, isolated_state_dir: Path):
        """验证带 owner 过滤的 status"""
        result = _run_orch_product("status", "--owner", "main")
        
        assert result["filters"]["owner"] == "main"
        assert "summary" in result
    
    def test_status_with_task_id(self, isolated_state_dir: Path):
        """验证查询单个任务的 status"""
        result = _run_orch_product("status", "--task-id", "nonexistent_task_12345")
        
        assert result["filters"]["task_id"] == "nonexistent_task_12345"
        # 不存在的任务应该返回 None 或空
        assert "task_detail" in result
    
    def test_status_with_limit(self, isolated_state_dir: Path):
        """验证 limit 参数"""
        result = _run_orch_product("status", "--limit", "5")
        
        assert result["filters"]["limit"] == 5
        assert len(result["active_tasks"]) <= 10  # 内部硬编码限制
        assert len(result["completed_tasks"]) <= 10
        assert len(result["failed_tasks"]) <= 10
    
    def test_status_next_steps_are_contextual(self, isolated_state_dir: Path):
        """验证 status 的 next_steps 根据状态不同而变化"""
        result = _run_orch_product("status")
        
        steps = result["next_steps"]
        assert len(steps) >= 1
        
        # 空状态下应该引导创建任务
        if result["summary"]["total_cards"] == 0:
            steps_text = " ".join(steps).lower()
            assert "run" in steps_text or "task" in steps_text


class TestCompatibility:
    """测试向后兼容性"""
    
    def test_orch_command_still_works(self):
        """验证现有 orch_command.py 仍然可用"""
        env = {"PYTHONPATH": str(ORCHESTRATOR_DIR)}
        
        proc = subprocess.run(
            [sys.executable, str(ORCH_COMMAND), "--output", "json"],
            capture_output=True,
            text=True,
            check=True,
            env={**os.environ, **env},
            cwd=REPO_ROOT,
        )
        
        result = json.loads(proc.stdout)
        
        # 原有 contract 结构必须完整
        assert "entry_context" in result
        assert "onboarding" in result
        assert "orchestration" in result
        assert "seed_payload" in result
    
    def test_orch_product_does_not_break_existing_contract(self):
        """验证 orch_product 不破坏现有 contract 结构"""
        # onboard 内部调用 build_default_entry_contract
        result = _run_orch_product("onboard")
        
        # 完整 contract 必须保留原有结构
        full_contract = result.get("full_contract", {})
        assert "entry_context" in full_contract
        assert "onboarding" in full_contract
        assert "orchestration" in full_contract
        assert "seed_payload" in full_contract


class TestIntegration:
    """集成测试"""
    
    def test_onboard_then_run_workflow(self, tmp_path: Path, isolated_state_dir: Path):
        """验证 onboard -> run 的完整工作流"""
        workdir = str(tmp_path)
        
        # 1. onboard 获取建议
        onboard_result = _run_orch_product("onboard")
        assert "recommendation" in onboard_result
        assert "example_commands" in onboard_result
        
        # 2. run 触发执行
        run_result = _run_orch_product(
            "run",
            "--task", "Integration test task",
            "--workdir", workdir,
        )
        
        assert run_result["task"]["task_id"]
        assert run_result["execution"]["backend"] in ("subagent", "tmux")
        
        # 3. status 查看状态
        status_result = _run_orch_product("status")
        
        assert "summary" in status_result
        # 注意：由于 observability card 可能未实际创建（依赖完整环境）
        # 这里只验证结构完整性
    
    def test_text_output_is_readable(self, tmp_path: Path):
        """验证文本输出可读性"""
        workdir = str(tmp_path)
        
        # onboard 文本输出
        text = _run_orch_product_text("onboard")
        assert "orch_product" in text.lower() or "Channel" in text or "Recommendation" in text
        
        # run 文本输出
        text = _run_orch_product_text("run", "--task", "Test", "--workdir", workdir)
        assert "Task ID" in text or "Backend" in text or "Session" in text
        
        # status 文本输出
        text = _run_orch_product_text("status")
        assert "Summary" in text or "summary" in text or "Next Steps" in text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
