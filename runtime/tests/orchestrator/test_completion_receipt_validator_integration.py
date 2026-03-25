#!/usr/bin/env python3
"""
test_completion_receipt_validator_integration.py — Completion Receipt + Validator 集成测试

P0 全切 (2026-03-25): Validator 结果接入 receipt 主判定链

测试覆盖：
- TC1: blocked_completion → receipt status 不能是 completed
- TC2: gate_required → receipt status 进入 failed
- TC3: accepted_completion → receipt status 正常 completed
- TC4: validator_error → conservative fallback (failed)
- TC5: whitelist → 跳过 validator，按 execution status 判断
"""

import unittest
import sys
from pathlib import Path
from datetime import datetime
from typing import Any, Dict

# 添加 runtime/orchestrator 到路径
orchestrator_path = Path(__file__).parent.parent.parent / "orchestrator"
sys.path.insert(0, str(orchestrator_path))

from completion_receipt import CompletionReceiptKernel, CompletionReceiptArtifact
from completion_validator import CompletionValidationResult
from spawn_execution import SpawnExecutionArtifact, SpawnExecutionStatus


def _create_mock_execution(
    exec_status: str = "started",
    output: str = "",
    exit_code: int = 0,
    label: str = "",
) -> SpawnExecutionArtifact:
    """创建 mock execution artifact 用于测试"""
    from uuid import uuid4
    
    return SpawnExecutionArtifact(
        execution_id=f"exec_{uuid4().hex[:12]}",
        spawn_id=f"spawn_{uuid4().hex[:12]}",
        dispatch_id=f"dispatch_{uuid4().hex[:12]}",
        registration_id=f"reg_{uuid4().hex[:12]}",
        task_id=f"task_{uuid4().hex[:12]}",
        spawn_execution_status=exec_status,  # type: ignore
        spawn_execution_reason="",
        spawn_execution_time=datetime.now().isoformat(),
        spawn_execution_target={
            "scenario": "test",
            "owner": "main",
            "runtime": "subagent",
            "cwd": "/tmp",
            "task_preview": "test task",
        },
        dedupe_key=f"dedupe_{uuid4().hex[:12]}",
        execution_payload={
            "metadata": {
                "label": label,
            }
        },
        execution_result={
            "execution_mode": "simulated",
            "result": output,
            "exit_code": exit_code,
            "stdout": output,
            "stderr": "",
        },
        metadata={
            "label": label,
        },
    )


class TestReceiptValidatorIntegration(unittest.TestCase):
    """测试 Completion Receipt + Validator 集成"""
    
    def test_TC1_blocked_completion_not_completed(self):
        """TC1: blocked_completion → receipt status 不能是 completed"""
        kernel = CompletionReceiptKernel()
        
        # 创建目录 listing 输出 (会被 validator block)
        output = """
drwxr-xr-x  5 user staff  160 Mar 25 00:00 .
drwxr-xr-x  7 user staff  224 Mar 25 00:00 ..
-rw-------  1 user staff  100 Mar 25 00:00 file1.txt
-rw-------  1 user staff  200 Mar 25 00:00 file2.txt
-rw-------  1 user staff  300 Mar 25 00:00 file3.txt
"""
        execution = _create_mock_execution(
            exec_status="started",
            output=output,
            label="coding-task",
        )
        
        receipt = kernel.create_receipt(execution)
        
        # P0 全切：blocked completion 不能标记为 completed
        self.assertNotEqual(receipt.receipt_status, "completed")
        self.assertEqual(receipt.receipt_status, "failed")
        self.assertIn("Validator blocked", receipt.receipt_reason)
    
    def test_TC2_gate_required_is_failed(self):
        """TC2: gate_required → receipt status 进入 failed"""
        kernel = CompletionReceiptKernel()
        
        # 创建边界情况输出 (可能会 gate)
        output = """
任务完成了。

这是一个简单的完成声明，没有结构化总结章节。
输出长度足够长，不会被 B6 拦截。
但没有测试证据，没有交付物证据。
"""
        execution = _create_mock_execution(
            exec_status="started",
            output=output,
            label="coding-task",
        )
        
        receipt = kernel.create_receipt(execution)
        
        # gate_required 应该映射为 failed
        # (具体取决于 validator 规则，可能是 blocked 或 gate)
        # 关键是：不能是 completed
        self.assertNotEqual(receipt.receipt_status, "completed")
    
    def test_TC3_accepted_completion_normal(self):
        """TC3: accepted_completion → receipt status 正常 completed"""
        kernel = CompletionReceiptKernel()
        
        # 创建真实完成输出
        output = """
## 完成总结

已完成所有功能实现：
- 实现了 validator 核心模块
- 添加了测试覆盖
- 所有测试通过

### 测试结果
5 passed, 0 failed

### 交付物
- completion_validator.py
- completion_validator_rules.py

任务完成了！所有功能正常工作。
"""
        execution = _create_mock_execution(
            exec_status="started",
            output=output,
            label="coding-task",
        )
        
        receipt = kernel.create_receipt(execution)
        
        # accepted completion 应该正常 completed
        self.assertEqual(receipt.receipt_status, "completed")
        # 验证 metadata 中包含 validator 结果
        self.assertIn("validation_result", receipt.metadata)
        val_status = receipt.metadata["validation_result"]["status"]
        self.assertEqual(val_status, "accepted_completion")
    
    def test_TC4_validator_error_fallback(self):
        """TC4: validator_error → conservative fallback (failed)"""
        kernel = CompletionReceiptKernel()
        
        # 创建正常输出 (不应该触发 validator error)
        # 这个测试主要验证 validator error 路径存在
        output = "Normal output"
        execution = _create_mock_execution(
            exec_status="started",
            output=output,
            label="coding-task",
        )
        
        receipt = kernel.create_receipt(execution)
        
        # validator error 应该 fallback 到 failed (保守策略)
        # 但正常输出不会触发 error，所以这里验证的是机制存在
        # 实际 error 场景需要模拟异常
        self.assertIn("validation_result", receipt.metadata)
    
    def test_TC5_whitelist_skips_validator(self):
        """TC5: whitelist → 跳过 validator，按 execution status 判断"""
        kernel = CompletionReceiptKernel()
        
        # 使用白名单 label
        output = "Just exploring files..."
        execution = _create_mock_execution(
            exec_status="started",
            output=output,
            label="explore-repo",  # 白名单 label
        )
        
        receipt = kernel.create_receipt(execution)
        
        # 白名单任务应该 completed (跳过 validator)
        self.assertEqual(receipt.receipt_status, "completed")
        # 验证 metadata 中标记为 whitelisted
        self.assertIn("validation_result", receipt.metadata)
        val_status = receipt.metadata["validation_result"]["status"]
        self.assertEqual(val_status, "accepted_completion")
        self.assertTrue(receipt.metadata["validation_result"]["metadata"].get("whitelisted"))
    
    def test_TC6_intermediate_state_blocked(self):
        """TC6: 中间状态输出 → blocked"""
        kernel = CompletionReceiptKernel()
        
        output = """
开始探索仓库结构...

让我先检查一下文件：
- file1.txt
- file2.txt

接下来我会实现功能。
"""
        execution = _create_mock_execution(
            exec_status="started",
            output=output,
            label="coding-task",
        )
        
        receipt = kernel.create_receipt(execution)
        
        # 中间状态应该被 block
        self.assertNotEqual(receipt.receipt_status, "completed")
        self.assertEqual(receipt.receipt_status, "failed")
        self.assertIn("Validator", receipt.receipt_reason)
    
    def test_TC7_code_snippet_blocked(self):
        """TC7: 纯代码片段 → blocked"""
        kernel = CompletionReceiptKernel()
        
        output = """
def validate():
    return True

class Test:
    def run(self):
        pass

def main():
    validate()

if __name__ == "__main__":
    main()
"""
        execution = _create_mock_execution(
            exec_status="started",
            output=output,
            label="coding-task",
        )
        
        receipt = kernel.create_receipt(execution)
        
        # 纯代码片段应该被 block
        self.assertNotEqual(receipt.receipt_status, "completed")


class TestReceiptStatusMapping(unittest.TestCase):
    """测试 Receipt Status 映射逻辑"""
    
    def test_blocked_maps_to_failed(self):
        """测试 blocked_completion → failed"""
        kernel = CompletionReceiptKernel()
        
        # 手动创建 blocked validation result
        validation_result = CompletionValidationResult(
            status="blocked_completion",
            reason="B1_pure_directory_listing",
            score=0,
            metadata={"blocked": True},
        )
        
        execution = _create_mock_execution(exec_status="started")
        status, reason = kernel._determine_receipt_status(execution, validation_result)
        
        self.assertEqual(status, "failed")
        self.assertIn("Validator blocked", reason)
    
    def test_gate_maps_to_failed(self):
        """测试 gate_required → failed"""
        kernel = CompletionReceiptKernel()
        
        validation_result = CompletionValidationResult(
            status="gate_required",
            reason="G1_boundary_case",
            score=2,
            metadata={"gate": True},
        )
        
        execution = _create_mock_execution(exec_status="started")
        status, reason = kernel._determine_receipt_status(execution, validation_result)
        
        self.assertEqual(status, "failed")
        self.assertIn("Validator gate", reason)
    
    def test_error_maps_to_failed(self):
        """测试 validator_error → failed (conservative fallback)"""
        kernel = CompletionReceiptKernel()
        
        validation_result = CompletionValidationResult(
            status="validator_error",
            reason="Simulated error",
            score=0,
            metadata={"error": True},
        )
        
        execution = _create_mock_execution(exec_status="started")
        status, reason = kernel._determine_receipt_status(execution, validation_result)
        
        self.assertEqual(status, "failed")
        self.assertIn("Validator error", reason)
    
    def test_accepted_continues_normal(self):
        """测试 accepted_completion → 继续按 execution status 判断"""
        kernel = CompletionReceiptKernel()
        
        validation_result = CompletionValidationResult(
            status="accepted_completion",
            reason="",
            score=5,
            metadata={"accepted": True},
        )
        
        execution = _create_mock_execution(exec_status="started")
        status, reason = kernel._determine_receipt_status(execution, validation_result)
        
        # accepted 时，按 execution status 判断
        self.assertEqual(status, "completed")
    
    def test_whitelisted_continues_normal(self):
        """测试 whitelisted → 继续按 execution status 判断"""
        kernel = CompletionReceiptKernel()
        
        validation_result = CompletionValidationResult(
            status="accepted_completion",
            reason="whitelisted",
            score=0,
            metadata={"whitelisted": True},
        )
        
        execution = _create_mock_execution(exec_status="started")
        status, reason = kernel._determine_receipt_status(execution, validation_result)
        
        self.assertEqual(status, "completed")


if __name__ == "__main__":
    unittest.main()
