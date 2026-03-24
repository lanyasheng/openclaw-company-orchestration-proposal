#!/usr/bin/env python3
"""
test_mainline_auto_continue.py — 主线自动推进实测验证

验证 trading_roundtable 在"前一批待 push / 已模拟 pushed / next batch gate"三种状态下的行为。

这是 P0-4 Final Mile 的主线级验证，不是底层单元测试。

场景覆盖：
- 场景 A：前一批 closeout complete + push pending → 下一批应被 gate 阻止
- 场景 B：前一批经过 emit/consume/simulate_push_success → 下一批 gate 允许继续
- 场景 C：check_push_consumer_status 能给出 can_auto_continue 与 blocker 的清晰结果

执行命令：
    python -m pytest tests/orchestrator/test_mainline_auto_continue.py -v

交付：
1) 结论：现在主线自动推进的验证程度
2) 证据：测试运行结果、关键状态
3) 动作：离真实 production 自动推进还差什么
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from datetime import datetime

import pytest

# Add orchestrator to path
ORCHESTRATOR_DIR = Path(__file__).resolve().parents[2] / "runtime" / "orchestrator"
if str(ORCHESTRATOR_DIR) not in sys.path:
    sys.path.insert(0, str(ORCHESTRATOR_DIR))

from closeout_tracker import (
    CloseoutTracker,
    create_closeout,
    get_closeout,
    check_closeout_gate,
    CloseoutGateResult,
    ContinuationContract,
    CLOSEOUT_DIR,
    _ensure_closeout_dir,
    emit_push_action,
    consume_push_action,
    simulate_push_success,
    check_push_consumer_status,
)
from state_machine import create_task, get_state, STATE_DIR  # type: ignore
from trading_roundtable import process_trading_roundtable_callback  # type: ignore


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """隔离的测试环境"""
    state_dir = tmp_path / "state"
    closeout_dir = tmp_path / "closeouts"
    
    monkeypatch.setenv("OPENCLAW_STATE_DIR", str(state_dir))
    state_dir.mkdir(parents=True, exist_ok=True)
    closeout_dir.mkdir(parents=True, exist_ok=True)
    
    # 重新加载模块以使用新的目录
    import importlib
    import closeout_tracker
    import state_machine
    import trading_roundtable
    
    importlib.reload(closeout_tracker)
    importlib.reload(state_machine)
    importlib.reload(trading_roundtable)
    
    # 更新全局变量
    closeout_tracker.CLOSEOUT_DIR = closeout_dir
    
    yield {
        "state_dir": state_dir,
        "closeout_dir": closeout_dir,
    }


def _trading_pass_result() -> dict:
    """构建 trading PASS 结果（最小可行）"""
    return {
        "verdict": "PASS",
        "trading_roundtable": {
            "packet": {
                "packet_version": "trading_phase1_packet_v1",
                "phase_id": "trading_phase1",
                "candidate_id": "test_candidate",
                "run_label": "test_run",
                "generated_at": datetime.now().isoformat(),
                "owner": "trading",
                "overall_gate": "PASS",
                "primary_blocker": "none",
                "artifact": {"path": "test/artifact.json", "exists": True},
                "report": {"path": "test/report.md", "exists": True},
                "commit": {"repo": "test-repo", "git_commit": "abc123"},
                "test": {"commands": ["pytest tests/"], "summary": "all passed"},
                "repro": {"commands": ["python test.py"]},
                "tradability": {"scenario_verdict": "PASS", "summary": "ok"},
            },
            "roundtable": {
                "conclusion": "PASS",
                "blocker": "none",
                "owner": "trading",
                "next_step": "Continue to next phase",
                "completion_criteria": "phase1 complete",
            },
        },
    }


class TestScenarioA_PushPendingBlocksNextBatch:
    """
    场景 A：前一批 closeout complete + push pending → 下一批应被 gate 阻止
    
    验证：closeout gate 在 push 未执行时阻止下一批
    """
    
    def test_closeout_complete_push_pending_blocks_next_batch(self, isolated_environment):
        """场景 A 核心测试：push pending 阻止下一批"""
        # 步骤 1：创建前一批 closeout（complete 但 push pending）
        continuation = ContinuationContract(
            stopped_because="roundtable_gate_pass_continuation_ready",
            next_step="Proceed to next batch",
            next_owner="trading",
        )
        
        closeout = create_closeout(
            batch_id="batch_001",
            scenario="trading_roundtable",
            continuation=continuation,
            has_remaining_work=False,
            metadata={"packet": {"overall_gate": "PASS"}},
        )
        
        # 验证 closeout 状态
        assert closeout.closeout_status == "complete"
        assert closeout.push_required is True
        assert closeout.push_status == "pending"
        
        # 步骤 2：检查下一批 gate
        gate_result = check_closeout_gate(
            batch_id="batch_002",
            scenario="trading_roundtable",
            require_push_complete=True,
        )
        
        # 验证：gate 应该阻止
        assert gate_result.allowed is False, "场景 A 失败：push pending 时应该阻止下一批"
        assert "push" in gate_result.reason.lower()
        assert gate_result.previous_batch_id == "batch_001"
        assert gate_result.previous_push_status == "pending"
        
        # 步骤 3：验证 check_push_consumer_status 给出清晰结果
        consumer_status = check_push_consumer_status("batch_001")
        
        assert consumer_status["closeout_status"] == "complete"
        assert consumer_status["push_status"] == "pending"
        assert consumer_status["push_required"] is True
        assert consumer_status["can_auto_continue"] is False
        assert consumer_status["blocker"] is not None
        assert "push" in consumer_status["blocker"].lower()
        
        print("\n=== 场景 A 验证通过 ===")
        print(f"前一批 batch_001: closeout_status={closeout.closeout_status}, push_status={closeout.push_status}")
        print(f"Gate 结果：allowed={gate_result.allowed}, reason={gate_result.reason}")
        print(f"Consumer status: can_auto_continue={consumer_status['can_auto_continue']}, blocker={consumer_status['blocker']}")


class TestScenarioB_PushExecutedAllowsNextBatch:
    """
    场景 B：前一批经过 emit/consume/simulate_push_success → 下一批 gate 允许继续
    
    验证：push consumer 完整链路 + 状态回填后，下一批可以继续
    """
    
    def test_push_consumer_chain_allows_next_batch(self, isolated_environment):
        """场景 B 核心测试：push consumer 完整链路"""
        # 步骤 1：创建前一批 closeout
        continuation = ContinuationContract(
            stopped_because="roundtable_gate_pass_continuation_ready",
            next_step="Proceed to next batch",
            next_owner="trading",
        )
        
        closeout = create_closeout(
            batch_id="batch_001",
            scenario="trading_roundtable",
            continuation=continuation,
            has_remaining_work=False,
            metadata={"packet": {"overall_gate": "PASS"}},
        )
        
        assert closeout.push_status == "pending"
        
        # 步骤 2：Emit push action
        push_action = emit_push_action(
            batch_id="batch_001",
            closeout_id=closeout.closeout_id,
            intent="Git push for batch_001 closeout",
        )
        
        assert push_action.status == "emitted"
        
        # 验证 closeout 中的 push_action 引用
        closeout_updated = get_closeout("batch_001")
        assert closeout_updated.push_action is not None
        assert closeout_updated.push_action.status == "emitted"
        
        # 步骤 3：Consume push action
        consumed_action = consume_push_action("batch_001")
        
        assert consumed_action.status == "consumed"
        
        # 步骤 4：Simulate push success（受控模拟，不真实 push 远端）
        closeout_after_push = simulate_push_success(
            batch_id="batch_001",
            metadata={"test_simulation": True},
        )
        
        assert closeout_after_push.push_status == "pushed"
        assert closeout_after_push.push_action.status == "executed"
        assert closeout_after_push.metadata.get("simulated") is True
        
        # 步骤 5：检查下一批 gate
        gate_result = check_closeout_gate(
            batch_id="batch_002",
            scenario="trading_roundtable",
            require_push_complete=True,
        )
        
        # 验证：gate 应该允许
        assert gate_result.allowed is True, "场景 B 失败：push executed 时应该允许下一批"
        assert "passed" in gate_result.reason.lower()
        assert gate_result.previous_batch_id == "batch_001"
        assert gate_result.previous_push_status == "pushed"
        
        # 步骤 6：验证 check_push_consumer_status 给出清晰结果
        consumer_status = check_push_consumer_status("batch_001")
        
        assert consumer_status["closeout_status"] == "complete"
        assert consumer_status["push_status"] == "pushed"
        assert consumer_status["can_auto_continue"] is True
        assert consumer_status["blocker"] is None
        
        print("\n=== 场景 B 验证通过 ===")
        print(f"Push action 链路：emitted → consumed → executed")
        print(f"Closeout after push: push_status={closeout_after_push.push_status}")
        print(f"Gate 结果：allowed={gate_result.allowed}, reason={gate_result.reason}")
        print(f"Consumer status: can_auto_continue={consumer_status['can_auto_continue']}, blocker={consumer_status['blocker']}")


class TestScenarioC_PushConsumerStatusClarity:
    """
    场景 C：check_push_consumer_status 能给出 can_auto_continue 与 blocker 的清晰结果
    
    验证：各种状态下的 can_auto_continue 和 blocker 输出
    """
    
    def test_blocked_closeout_gives_clear_blocker(self, isolated_environment):
        """场景 C.1：blocked closeout 给出清晰 blocker"""
        continuation = ContinuationContract(
            stopped_because="roundtable_gate_fail_blocker_tradability",
            next_step="Resolve blocker first",
            next_owner="trading",
        )
        
        create_closeout(
            batch_id="batch_blocked",
            scenario="trading_roundtable",
            continuation=continuation,
            has_remaining_work=True,
            metadata={
                "packet": {"overall_gate": "FAIL"},
                "roundtable": {"conclusion": "FAIL", "blocker": "tradability"},
            },
        )
        
        consumer_status = check_push_consumer_status("batch_blocked")
        
        assert consumer_status["closeout_status"] == "blocked"
        assert consumer_status["can_auto_continue"] is False
        assert consumer_status["blocker"] is not None
        assert "blocked" in consumer_status["blocker"].lower()
        
        print("\n=== 场景 C.1 验证通过 ===")
        print(f"Blocked closeout: blocker={consumer_status['blocker']}")
    
    def test_incomplete_closeout_gives_clear_blocker(self, isolated_environment):
        """场景 C.2：incomplete closeout 给出清晰 blocker"""
        continuation = ContinuationContract(
            stopped_because="follow_up_partial_completed",
            next_step="Complete remaining work",
            next_owner="trading",
        )
        
        create_closeout(
            batch_id="batch_incomplete",
            scenario="trading_roundtable",
            continuation=continuation,
            has_remaining_work=True,
            metadata={"packet": {"overall_gate": "PASS"}},
        )
        
        consumer_status = check_push_consumer_status("batch_incomplete")
        
        assert consumer_status["closeout_status"] == "incomplete"
        assert consumer_status["can_auto_continue"] is False
        assert consumer_status["blocker"] is not None
        
        print("\n=== 场景 C.2 验证通过 ===")
        print(f"Incomplete closeout: blocker={consumer_status['blocker']}")
    
    def test_no_closeout_allows_first_run(self, isolated_environment):
        """场景 C.3：没有 closeout 时允许首次运行"""
        consumer_status = check_push_consumer_status("batch_first_run")
        
        assert consumer_status["closeout_status"] == "incomplete"
        assert consumer_status["can_auto_continue"] is True
        assert consumer_status["blocker"] is None
        
        print("\n=== 场景 C.3 验证通过 ===")
        print(f"First run: can_auto_continue={consumer_status['can_auto_continue']}")


class TestMainlineIntegration:
    """
    主线集成测试：完整的两批连续运行模拟
    
    验证：batch_001 (PASS + push) → simulate_push → batch_002 允许继续
    
    注意：当 decision.action="proceed" 且有 next_step 时，closeout 会被标记为 incomplete
    （因为有 remaining work）。这是正确行为。
    
    本测试使用直接 create_closeout 来验证"closeout complete + push pending"场景，
    因为 process_trading_roundtable_callback 在有 next_step 时会正确标记为 incomplete。
    """
    
    def test_two_batch_sequential_run(self, isolated_environment):
        """主线集成：两批连续运行"""
        # ========== 第一批：batch_001 ==========
        # 使用直接 create_closeout 来模拟"closeout complete"场景
        # （没有 remaining work 的情况）
        batch_id_1 = "batch_mainline_001"
        
        continuation_1 = ContinuationContract(
            stopped_because="roundtable_gate_pass_continuation_ready",
            next_step="Proceed to next batch",
            next_owner="trading",
        )
        
        closeout_1 = create_closeout(
            batch_id=batch_id_1,
            scenario="trading_roundtable",
            continuation=continuation_1,
            has_remaining_work=False,  # 明确标记没有 remaining work
            metadata={"packet": {"overall_gate": "PASS"}},
        )
        
        # 验证 closeout 状态
        assert closeout_1.closeout_status == "complete"
        assert closeout_1.push_required is True
        assert closeout_1.push_status == "pending", f"Expected pending, got {closeout_1.push_status}"
        
        # 模拟 push success（受控模拟，不真实 push 远端）
        closeout_1_after_push = simulate_push_success(batch_id_1)
        assert closeout_1_after_push.push_status == "pushed"
        
        # ========== 第二批：batch_002 ==========
        batch_id_2 = "batch_mainline_002"
        task_id_2 = "tsk_mainline_002"
        create_task(task_id_2, batch_id=batch_id_2)
        
        # 第二批不跳过 gate 检查
        result_2 = process_trading_roundtable_callback(
            batch_id=batch_id_2,
            task_id=task_id_2,
            result=_trading_pass_result(),
            allow_auto_dispatch=True,
            skip_closeout_gate=False,  # 第二批启用 gate 检查
            requester_session_key="test_session",
        )
        
        # 验证：第二批应该被允许（因为第一批 push 已完成）
        assert result_2["status"] == "processed", f"场景失败：第二批被阻止，result={result_2}"
        assert "closeout_gate" in result_2
        assert result_2["closeout_gate"]["allowed"] is True, f"Gate should allow batch_002, reason={result_2['closeout_gate']['reason']}"
        
        # 验证 closeout gate 输出
        gate_output = result_2["closeout_gate"]
        assert gate_output["previous_batch_id"] == batch_id_1
        assert gate_output["previous_push_status"] == "pushed"
        
        print("\n=== 主线集成测试验证通过 ===")
        print(f"Batch 1: {batch_id_1}, closeout_status={closeout_1.closeout_status}, push_status={closeout_1_after_push.push_status}")
        print(f"Batch 2: {batch_id_2}, gate allowed={result_2['closeout_gate']['allowed']}")
        print(f"Gate 输出：previous_batch={gate_output['previous_batch_id']}, previous_push_status={gate_output['previous_push_status']}")


def run_mainline_validation():
    """运行主线验证并输出摘要"""
    print("\n" + "="*60)
    print("主线自动推进验证报告")
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
    print("验证结论")
    print("="*60)
    
    if result.returncode == 0:
        print("✅ 所有场景验证通过")
        print("\n当前状态：")
        print("- closeout gate glue: 已验证 (f4bac32)")
        print("- push consumer + status backfill: 已验证 (0aaef98)")
        print("- 内部模拟闭环：已跑通")
        print("\n主线自动化程度：")
        print("- 内部自动推进模拟：✅ 已跑通")
        print("- 真实远端 push 自动推进：❌ 未打通（需要真实 git push 集成）")
        print("\n下一步动作：")
        print("1. 将 simulate_push_success 替换为真实 git push 执行器")
        print("2. 在 production 环境验证完整链路")
        print("3. 添加 push 失败回滚机制")
    else:
        print("❌ 部分场景验证失败")
        print("需要修复代码或测试")
    
    return result.returncode == 0


if __name__ == "__main__":
    success = run_mainline_validation()
    sys.exit(0 if success else 1)
