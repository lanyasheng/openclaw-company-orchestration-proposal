#!/usr/bin/env python3
"""
test_completion_receipt_hotfix.py — P0-Hotfix (2026-03-31)

测试 completion_receipt.py 的 hotfix 修复：
1. next_step 不应该使用通用的 "Awaiting downstream processing or manual review"
2. 应该根据 scenario 生成更具体的 next_step
3. 应该优先从 execution metadata 中提取 next_step
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

import pytest

# 添加 orchestrator 到路径
ORCHESTRATOR_PATH = Path(__file__).parent.parent.parent / "runtime" / "orchestrator"
sys.path.insert(0, str(ORCHESTRATOR_PATH))

from completion_receipt import (
    CompletionReceiptKernel,
    build_receipt_continuation_contract,
)
from spawn_execution import SpawnExecutionArtifact


def create_sample_execution(
    scenario: str = "test",
    owner: str = "test_owner",
    next_step: str = "",
    metadata: dict = None,
    execution_result: dict = None,
) -> SpawnExecutionArtifact:
    """创建样本 spawn execution"""
    return SpawnExecutionArtifact(
        execution_id=f"exec_test_{scenario}",
        spawn_id=f"spawn_test_{scenario}",
        dispatch_id=f"dispatch_test_{scenario}",
        registration_id=f"reg_test_{scenario}",
        task_id=f"task_test_{scenario}",
        spawn_execution_status="started",
        spawn_execution_reason="Execution started successfully",
        spawn_execution_time=datetime.now().isoformat(),
        spawn_execution_target={
            "scenario": scenario,
            "owner": owner,
            "next_step": next_step,  # May be empty
        },
        dedupe_key=f"dedupe_exec_test_{scenario}",
        execution_payload={"metadata": {}},
        execution_result=execution_result or {},
        metadata=metadata or {},
    )


class TestScenarioSpecificNextStep:
    """测试 scenario-specific next_step 生成"""
    
    def test_trading_scenario_completed(self):
        """测试 trading 场景 completed 状态的 next_step"""
        execution = create_sample_execution(
            scenario="trading_roundtable_phase1",
            owner="trading",
            next_step="",  # 没有显式 next_step
        )
        
        cont = build_receipt_continuation_contract(
            execution=execution,
            receipt_status="completed",
            receipt_reason="Execution completed successfully",
        )
        
        # 不应该使用通用的 "Awaiting downstream..."
        assert "Awaiting downstream processing or manual review" not in cont.next_step
        # 应该包含 trading 特定文案
        assert "Trading" in cont.next_step or "交易" in cont.next_step
        assert "trading" in cont.next_owner.lower()
    
    def test_channel_roundtable_scenario_completed(self):
        """测试 channel roundtable 场景 completed 状态的 next_step"""
        execution = create_sample_execution(
            scenario="channel_roundtable",
            owner="main",
            next_step="",
        )
        
        cont = build_receipt_continuation_contract(
            execution=execution,
            receipt_status="completed",
            receipt_reason="Execution completed successfully",
        )
        
        # 不应该使用通用的 "Awaiting downstream..."
        assert "Awaiting downstream processing or manual review" not in cont.next_step
        # 应该包含圆桌讨论特定文案
        assert "圆桌" in cont.next_step or "roundtable" in cont.next_step.lower()
    
    def test_generic_scenario_completed(self):
        """测试通用场景 completed 状态的 next_step"""
        execution = create_sample_execution(
            scenario="custom_task",
            owner="main",
            next_step="",
        )
        
        cont = build_receipt_continuation_contract(
            execution=execution,
            receipt_status="completed",
            receipt_reason="Execution completed successfully",
        )
        
        # 不应该使用通用的 "Awaiting downstream..."
        assert "Awaiting downstream processing or manual review" not in cont.next_step
        # 应该包含 owner 信息
        assert "main" in cont.next_owner.lower()
        assert "完成" in cont.next_step or "completed" in cont.next_step.lower()
    
    def test_failed_scenario(self):
        """测试 failed 状态的 next_step"""
        execution = create_sample_execution(
            scenario="trading_roundtable",
            owner="trading",
            next_step="",
        )
        
        cont = build_receipt_continuation_contract(
            execution=execution,
            receipt_status="failed",
            receipt_reason="Execution failed due to timeout",
        )
        
        # 不应该使用通用的 "Awaiting downstream..."
        assert "Awaiting downstream processing or manual review" not in cont.next_step
        # 应该包含失败原因和 owner 信息
        assert "失败" in cont.next_step or "failed" in cont.next_step.lower()
        assert "trading" in cont.next_owner.lower()
    
    def test_explicit_next_step_from_target(self):
        """测试从 spawn_execution_target 中提取显式 next_step"""
        execution = create_sample_execution(
            scenario="trading_roundtable",
            owner="trading",
            next_step="Continue with phase 2 analysis",  # 显式 next_step
        )
        
        cont = build_receipt_continuation_contract(
            execution=execution,
            receipt_status="completed",
            receipt_reason="Execution completed successfully",
        )
        
        # 应该使用显式 next_step
        assert cont.next_step == "Continue with phase 2 analysis"
    
    def test_next_step_from_execution_result(self):
        """测试从 execution_result 中提取 next_step"""
        execution = create_sample_execution(
            scenario="trading_roundtable",
            owner="trading",
            next_step="",  # target 中没有
            execution_result={"next_step": "Next step from execution result"},
        )
        
        cont = build_receipt_continuation_contract(
            execution=execution,
            receipt_status="completed",
            receipt_reason="Execution completed successfully",
        )
        
        # 应该从 execution_result 中提取
        assert cont.next_step == "Next step from execution result"
    
    def test_next_step_from_metadata(self):
        """测试从 metadata 中提取 next_step"""
        execution = create_sample_execution(
            scenario="trading_roundtable",
            owner="trading",
            next_step="",
            metadata={"next_step": "Next step from metadata"},
        )
        
        cont = build_receipt_continuation_contract(
            execution=execution,
            receipt_status="completed",
            receipt_reason="Execution completed successfully",
        )
        
        # 应该从 metadata 中提取
        assert cont.next_step == "Next step from metadata"
    
    def test_priority_order(self):
        """测试 next_step 提取优先级：target > execution_result > metadata > scenario-specific default"""
        # Priority 1: target next_step
        execution1 = create_sample_execution(
            scenario="trading",
            owner="trading",
            next_step="From target",
            execution_result={"next_step": "From result"},
            metadata={"next_step": "From metadata"},
        )
        cont1 = build_receipt_continuation_contract(execution1, "completed", "OK")
        assert cont1.next_step == "From target"
        
        # Priority 2: execution_result next_step
        execution2 = create_sample_execution(
            scenario="trading",
            owner="trading",
            next_step="",  # target 没有
            execution_result={"next_step": "From result"},
            metadata={"next_step": "From metadata"},
        )
        cont2 = build_receipt_continuation_contract(execution2, "completed", "OK")
        assert cont2.next_step == "From result"
        
        # Priority 3: metadata next_step
        execution3 = create_sample_execution(
            scenario="trading",
            owner="trading",
            next_step="",
            execution_result={},  # result 没有
            metadata={"next_step": "From metadata"},
        )
        cont3 = build_receipt_continuation_contract(execution3, "completed", "OK")
        assert cont3.next_step == "From metadata"
        
        # Priority 4: scenario-specific default
        execution4 = create_sample_execution(
            scenario="trading_roundtable",
            owner="trading",
            next_step="",
            execution_result={},
            metadata={},
        )
        cont4 = build_receipt_continuation_contract(execution4, "completed", "OK")
        assert "Awaiting downstream processing or manual review" not in cont4.next_step
        assert "Trading" in cont4.next_step or "交易" in cont4.next_step


class TestCompletionReceiptKernelHotfix:
    """测试 CompletionReceiptKernel 的 hotfix 集成"""
    
    def test_create_receipt_includes_scenario_specific_next_step(self):
        """测试 create_receipt 生成的 receipt 包含 scenario-specific next_step"""
        execution = create_sample_execution(
            scenario="trading_roundtable_phase1",
            owner="trading",
            next_step="",
        )
        
        kernel = CompletionReceiptKernel()
        receipt = kernel.create_receipt(execution)
        
        # 验证 metadata 包含正确的 next_step
        assert "Awaiting downstream processing or manual review" not in receipt.metadata.get("next_step", "")
        assert "next_step" in receipt.metadata
        assert len(receipt.metadata["next_step"]) > 0
        
        # 验证 continuation_contract 也包含正确的 next_step
        cont_dict = receipt.metadata.get("continuation_contract", {})
        assert cont_dict.get("next_step") == receipt.metadata["next_step"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
