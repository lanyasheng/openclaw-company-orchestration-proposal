#!/usr/bin/env python3
"""
fallback_protocol.py — P0-4 Timeout / Error / Empty-Result Fallback Protocol

最小 fallback 闭环协议，显式化处理 timeout / error / empty-result 三种失败场景。

核心规则：
1. timeout：首次超时 → retry 1 次 → 仍失败则 timeout_closeout (CONDITIONAL)
2. error：可恢复 → retry 1 次；不可恢复 → error_closeout (FAIL)
3. empty-result：硬拦截为 FAIL，不重试

边界：
- 不做大而全 runtime 重构
- 不伪造重试成功
- 不绕过 trading gate
- empty-result 的"无 artifact/report/test summary"必须作为强信号拦截

这是 P0-4 最小可行修复，复用现有 state/closeout 机制。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Tuple
from pathlib import Path
import json

from partial_continuation import ContinuationContract, build_continuation_contract

__all__ = [
    "FallbackVerdict",
    "FallbackCloseoutStatus",
    "FallbackProtocol",
    "FallbackResult",
    "FALLBACK_PROTOCOL_VERSION",
    "check_empty_result",
    "determine_retry_eligibility",
    "build_fallback_closeout",
]

FALLBACK_PROTOCOL_VERSION = "fallback_protocol_v1"

# Fallback verdict 类型
FallbackVerdict = Literal["PASS", "FAIL", "CONDITIONAL", "RETRY"]

# Closeout status 类型（复用 closeout_tracker 的语义）
FallbackCloseoutStatus = Literal[
    "complete",           # closeout 已完成
    "pending_push",       # 等待 push
    "incomplete",         # closeout 未完成（仍有 remaining work）
    "blocked",            # closeout 被 blocker 阻止
    "stale",              # closeout 状态落后
    "timeout_closeout",   # P0-4 新增：超时 closeout
    "error_closeout",     # P0-4 新增：错误 closeout
    "empty_result_closeout",  # P0-4 新增：空结果 closeout
]


@dataclass
class FallbackResult:
    """
    Fallback 协议执行结果
    
    核心字段：
    - verdict: 最终裁决 (PASS/FAIL/CONDITIONAL/RETRY)
    - closeout_status: closeout 状态
    - retry_count: 已重试次数
    - retry_eligible: 是否可重试
    - failure_type: 失败类型 (timeout/error/empty-result/none)
    - failure_reason: 失败原因详情
    - continuation_contract: 统一的 continuation 语义
    - metadata: 额外元数据
    """
    verdict: FallbackVerdict
    closeout_status: FallbackCloseoutStatus
    retry_count: int = 0
    retry_eligible: bool = False
    failure_type: Literal["timeout", "error", "empty-result", "none"] = "none"
    failure_reason: str = ""
    continuation_contract: Optional[ContinuationContract] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "fallback_version": FALLBACK_PROTOCOL_VERSION,
            "verdict": self.verdict,
            "closeout_status": self.closeout_status,
            "retry_count": self.retry_count,
            "retry_eligible": self.retry_eligible,
            "failure_type": self.failure_type,
            "failure_reason": self.failure_reason,
            "continuation_contract": self.continuation_contract.to_dict() if self.continuation_contract else None,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FallbackResult":
        cc_data = data.get("continuation_contract")
        continuation_contract = None
        if cc_data:
            continuation_contract = ContinuationContract.from_dict(cc_data)
        
        return cls(
            verdict=data.get("verdict", "FAIL"),
            closeout_status=data.get("closeout_status", "blocked"),
            retry_count=data.get("retry_count", 0),
            retry_eligible=data.get("retry_eligible", False),
            failure_type=data.get("failure_type", "none"),
            failure_reason=data.get("failure_reason", ""),
            continuation_contract=continuation_contract,
            metadata=data.get("metadata", {}),
        )


class FallbackProtocol:
    """
    Fallback 协议执行器
    
    提供：
    - evaluate(): 评估任务结果，决定 fallback 行为
    - check_timeout(): 检查超时状态
    - check_error(): 检查错误状态
    - check_empty_result(): 检查空结果状态
    - determine_retry(): 决定是否可重试
    """
    
    # 最大重试次数
    MAX_RETRY_COUNT = 1
    
    # 可恢复错误类型白名单
    RECOVERABLE_ERROR_TYPES = {
        "network_error",
        "rate_limit",
        "temporary_unavailable",
        "timeout_retryable",
    }
    
    # 不可恢复错误类型黑名单
    NON_RECOVERABLE_ERROR_TYPES = {
        "auth_failure",
        "permission_denied",
        "invalid_input",
        "configuration_error",
        "tradability_blocker",
        "gate_fail",
    }
    
    def __init__(self):
        self.context: Dict[str, Any] = {}
    
    def set_context(self, key: str, value: Any):
        """设置评估上下文"""
        self.context[key] = value
    
    def get_context(self, key: str, default: Any = None) -> Any:
        """获取评估上下文"""
        return self.context.get(key, default)
    
    def evaluate(
        self,
        task_result: Dict[str, Any],
        retry_count: int = 0,
        batch_analysis: Optional[Dict[str, Any]] = None,
    ) -> FallbackResult:
        """
        评估任务结果，决定 fallback 行为。
        
        评估顺序：
        1. 先检查 timeout（因为 timeout 是明确的失败状态）
        2. 再检查 error（因为 error 也是明确的失败状态）
        3. 最后检查 empty-result（只在 completed 但没有产出物时触发）
        
        Args:
            task_result: 任务执行结果（包含 status / artifacts / error 等）
            retry_count: 当前已重试次数
            batch_analysis: batch 分析结果（可选）
        
        Returns:
            FallbackResult: fallback 协议执行结果
        """
        # 1. 先检查 timeout（明确失败状态）
        timeout_check = self._check_timeout(task_result, batch_analysis)
        if timeout_check["is_timeout"]:
            return self._handle_timeout(
                timeout_check=timeout_check,
                retry_count=retry_count,
                task_result=task_result,
            )
        
        # 2. 再检查 error（明确失败状态）
        error_check = self._check_error(task_result)
        if error_check["has_error"]:
            return self._handle_error(
                error_check=error_check,
                retry_count=retry_count,
                task_result=task_result,
            )
        
        # 3. 最后检查 empty-result（只在 completed 但没有产出物时触发）
        # 注意：empty-result 只在状态是 completed/success 但无产出物时才判定
        status = task_result.get("status", "")
        if status in ("completed", "success", "passed", ""):
            empty_result_check = check_empty_result(task_result)
            if empty_result_check["is_empty"]:
                return FallbackResult(
                    verdict="FAIL",
                    closeout_status="empty_result_closeout",
                    retry_count=retry_count,
                    retry_eligible=False,  # empty-result 不重试
                    failure_type="empty-result",
                    failure_reason=empty_result_check["reason"],
                    continuation_contract=build_continuation_contract(
                        stopped_because=f"empty_result_hard_block: {empty_result_check['reason']}",
                        next_step="Investigate why no artifacts were produced; fix root cause before retry",
                        next_owner="main",
                        metadata={
                            "fallback_protocol": FALLBACK_PROTOCOL_VERSION,
                            "empty_result_check": empty_result_check,
                        },
                    ),
                    metadata={
                        "empty_result": True,
                        "hard_block": True,
                        "checked_at": datetime.now().isoformat(),
                    },
                )
        
        # 4. 默认：PASS
        return FallbackResult(
            verdict="PASS",
            closeout_status="complete",
            retry_count=retry_count,
            retry_eligible=False,
            failure_type="none",
            continuation_contract=build_continuation_contract(
                stopped_because="task_completed_successfully",
                next_step="Proceed to next phase or batch",
                next_owner="main",
                metadata={"fallback_protocol": FALLBACK_PROTOCOL_VERSION},
            ),
            metadata={
                "checked_at": datetime.now().isoformat(),
                "batch_analysis": batch_analysis,
            },
        )
    
    def _check_timeout(
        self,
        task_result: Dict[str, Any],
        batch_analysis: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        检查超时状态。
        
        Returns:
            {
                "is_timeout": bool,
                "timeout_count": int,
                "reason": str,
            }
        """
        # 从 task_result 中检查
        status = task_result.get("status", "")
        error = task_result.get("error", "")
        metadata = task_result.get("metadata", {})
        
        is_timeout = (
            status in ("timeout", "timed_out") or
            "timeout" in str(error).lower() or
            metadata.get("timeout", False)
        )
        
        # 从 batch_analysis 中获取 timeout 计数
        timeout_count = 0
        if batch_analysis:
            timeout_count = int(batch_analysis.get("timeout", 0))
        
        reason = ""
        if is_timeout:
            reason = f"Task timed out (batch timeout count: {timeout_count})"
        
        return {
            "is_timeout": is_timeout,
            "timeout_count": timeout_count,
            "reason": reason,
        }
    
    def _handle_timeout(
        self,
        timeout_check: Dict[str, Any],
        retry_count: int,
        task_result: Dict[str, Any],
    ) -> FallbackResult:
        """
        处理超时场景。
        
        规则：首次超时 → retry 1 次 → 仍失败则 timeout_closeout (CONDITIONAL)
        """
        retry_eligible = retry_count < self.MAX_RETRY_COUNT
        
        if retry_eligible:
            # 允许重试
            return FallbackResult(
                verdict="RETRY",
                closeout_status="incomplete",
                retry_count=retry_count,
                retry_eligible=True,
                failure_type="timeout",
                failure_reason=timeout_check["reason"],
                continuation_contract=build_continuation_contract(
                    stopped_because=f"timeout_retry_attempt_{retry_count + 1}",
                    next_step=f"Retry task (attempt {retry_count + 1}/{self.MAX_RETRY_COUNT + 1})",
                    next_owner="main",
                    metadata={
                        "fallback_protocol": FALLBACK_PROTOCOL_VERSION,
                        "retry_attempt": retry_count + 1,
                        "max_retries": self.MAX_RETRY_COUNT,
                    },
                ),
                metadata={
                    "timeout_check": timeout_check,
                    "retry_allowed": True,
                },
            )
        else:
            # 已达到最大重试次数，timeout_closeout
            return FallbackResult(
                verdict="CONDITIONAL",
                closeout_status="timeout_closeout",
                retry_count=retry_count,
                retry_eligible=False,
                failure_type="timeout",
                failure_reason=f"Timeout after {retry_count} retry attempts: {timeout_check['reason']}",
                continuation_contract=build_continuation_contract(
                    stopped_because=f"timeout_closeout_after_{retry_count}_retries",
                    next_step="Review timeout cause; decide whether to manually retry or proceed with degraded results",
                    next_owner="main",
                    metadata={
                        "fallback_protocol": FALLBACK_PROTOCOL_VERSION,
                        "timeout_closeout": True,
                        "max_retries_reached": True,
                    },
                ),
                metadata={
                    "timeout_check": timeout_check,
                    "max_retries_reached": True,
                },
            )
    
    def _check_error(
        self,
        task_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        检查错误状态。
        
        Returns:
            {
                "has_error": bool,
                "error_type": str,
                "error_message": str,
                "recoverable": bool,
            }
        """
        status = task_result.get("status", "")
        error = task_result.get("error", "")
        error_type = task_result.get("error_type", "")
        metadata = task_result.get("metadata", {})
        
        has_error = (
            status == "failed" or
            error != "" or
            metadata.get("error", False)
        )
        
        if not has_error:
            return {
                "has_error": False,
                "error_type": "",
                "error_message": "",
                "recoverable": False,
            }
        
        # 判断是否可恢复
        error_type_lower = str(error_type or error).lower()
        recoverable = any(
            recoverable_type in error_type_lower
            for recoverable_type in self.RECOVERABLE_ERROR_TYPES
        )
        
        # 检查是否在黑名单中（不可恢复）
        if any(
            non_recoverable_type in error_type_lower
            for non_recoverable_type in self.NON_RECOVERABLE_ERROR_TYPES
        ):
            recoverable = False
        
        return {
            "has_error": has_error,
            "error_type": error_type or "unknown",
            "error_message": str(error),
            "recoverable": recoverable,
        }
    
    def _handle_error(
        self,
        error_check: Dict[str, Any],
        retry_count: int,
        task_result: Dict[str, Any],
    ) -> FallbackResult:
        """
        处理错误场景。
        
        规则：可恢复 → retry 1 次；不可恢复 → error_closeout (FAIL)
        """
        if error_check["recoverable"] and retry_count < self.MAX_RETRY_COUNT:
            # 可恢复错误，允许重试
            return FallbackResult(
                verdict="RETRY",
                closeout_status="incomplete",
                retry_count=retry_count,
                retry_eligible=True,
                failure_type="error",
                failure_reason=f"Recoverable error: {error_check['error_message']}",
                continuation_contract=build_continuation_contract(
                    stopped_because=f"error_retry_attempt_{retry_count + 1}",
                    next_step=f"Retry task (attempt {retry_count + 1}/{self.MAX_RETRY_COUNT + 1}): {error_check['error_type']}",
                    next_owner="main",
                    metadata={
                        "fallback_protocol": FALLBACK_PROTOCOL_VERSION,
                        "retry_attempt": retry_count + 1,
                        "max_retries": self.MAX_RETRY_COUNT,
                        "error_type": error_check["error_type"],
                    },
                ),
                metadata={
                    "error_check": error_check,
                    "retry_allowed": True,
                    "recoverable": True,
                },
            )
        else:
            # 不可恢复错误或已达到最大重试次数，error_closeout
            return FallbackResult(
                verdict="FAIL",
                closeout_status="error_closeout",
                retry_count=retry_count,
                retry_eligible=False,
                failure_type="error",
                failure_reason=f"{'Irrecoverable' if not error_check['recoverable'] else 'Max retries exceeded'} error: {error_check['error_message']}",
                continuation_contract=build_continuation_contract(
                    stopped_because=f"error_closeout_{error_check['error_type']}",
                    next_step=f"Resolve error before continuation: {error_check['error_message']}",
                    next_owner="main",
                    metadata={
                        "fallback_protocol": FALLBACK_PROTOCOL_VERSION,
                        "error_closeout": True,
                        "error_type": error_check["error_type"],
                        "recoverable": error_check["recoverable"],
                    },
                ),
                metadata={
                    "error_check": error_check,
                    "max_retries_reached": retry_count >= self.MAX_RETRY_COUNT,
                    "recoverable": error_check["recoverable"],
                },
            )


def check_empty_result(
    task_result: Dict[str, Any],
    required_artifacts: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    检查空结果（empty-result）。
    
    空结果的判定条件：
    1. 没有 artifact / report / test summary
    2. result 为空或只有空字段
    3. 没有实质性的输出内容
    
    Args:
        task_result: 任务执行结果
        required_artifacts: 必需的 artifact 列表（可选）
    
    Returns:
        {
            "is_empty": bool,
            "reason": str,
            "missing_artifacts": List[str],
            "checked_fields": List[str],
        }
    """
    missing_artifacts: List[str] = []
    checked_fields: List[str] = []
    present_artifacts: List[str] = []
    
    # 默认必需的 artifact 字段
    if required_artifacts is None:
        required_artifacts = [
            "artifact",
            "report",
            "test_summary",
            "result",
            "output",
            "summary",
        ]
    
    # 检查 task_result 是否为空
    if not task_result:
        return {
            "is_empty": True,
            "reason": "task_result is None or empty",
            "missing_artifacts": required_artifacts,
            "checked_fields": [],
        }
    
    # 检查 error 字段（如果有 error 但不是 empty-result）
    if task_result.get("error") or task_result.get("error_type"):
        # 有错误信息，不算 empty-result
        return {
            "is_empty": False,
            "reason": "Error present; not an empty result",
            "missing_artifacts": [],
            "checked_fields": [],
        }
    
    # 检查必需 artifact 是否存在且非空
    for artifact_key in required_artifacts:
        checked_fields.append(artifact_key)
        artifact_value = task_result.get(artifact_key)
        
        if artifact_value is None:
            missing_artifacts.append(artifact_key)
            continue
        
        # 检查是否为空字符串
        if isinstance(artifact_value, str) and not artifact_value.strip():
            missing_artifacts.append(artifact_key)
            continue
        
        # 检查是否为空列表/字典
        if isinstance(artifact_value, (list, dict)) and len(artifact_value) == 0:
            missing_artifacts.append(artifact_key)
            continue
        
        # 有实质性内容
        present_artifacts.append(artifact_key)
    
    # 如果有任何 artifact 存在，不算 empty-result
    if present_artifacts:
        return {
            "is_empty": False,
            "reason": f"Has artifacts: {', '.join(present_artifacts)}",
            "missing_artifacts": missing_artifacts,
            "checked_fields": checked_fields,
        }
    
    # 检查 result / output 是否有实质内容（嵌套在 result 字段中）
    result = task_result.get("result", {})
    if isinstance(result, dict) and result:
        # 检查是否有实质性字段
        substantive_fields = ["artifact", "report", "test", "repro", "summary", "output", "data"]
        has_substantive_content = any(
            result.get(field) and (
                not isinstance(result[field], (str, list, dict)) or
                len(str(result[field]).strip()) > 0 or
                (isinstance(result[field], (list, dict)) and len(result[field]) > 0)
            )
            for field in substantive_fields
        )
        if has_substantive_content:
            return {
                "is_empty": False,
                "reason": "Has substantive content in result",
                "missing_artifacts": missing_artifacts,
                "checked_fields": checked_fields,
            }
    
    # 所有必需 artifact 都缺失，判定为空结果
    return {
        "is_empty": True,
        "reason": f"Missing critical artifacts: {', '.join(missing_artifacts)}",
        "missing_artifacts": missing_artifacts,
        "checked_fields": checked_fields,
    }


def determine_retry_eligibility(
    task_result: Dict[str, Any],
    retry_count: int,
    max_retries: int = 1,
) -> Tuple[bool, str]:
    """
    决定是否可重试。
    
    Args:
        task_result: 任务执行结果
        retry_count: 当前已重试次数
        max_retries: 最大重试次数
    
    Returns:
        (retry_eligible, reason)
    """
    # 检查是否超过最大重试次数
    if retry_count >= max_retries:
        return False, f"Max retries ({max_retries}) exceeded"
    
    # 检查超时（可重试）
    status = task_result.get("status", "")
    metadata = task_result.get("metadata", {})
    if status in ("timeout", "timed_out") or metadata.get("timeout", False):
        return True, f"Retry eligible for timeout (attempt {retry_count + 1}/{max_retries + 1})"
    
    # 检查 empty-result（硬拦截，不重试）
    empty_check = check_empty_result(task_result)
    if empty_check["is_empty"]:
        return False, f"Empty result (hard block): {empty_check['reason']}"
    
    # 检查错误类型
    error_type = str(task_result.get("error_type", task_result.get("error", ""))).lower()
    
    # 不可恢复错误
    non_recoverable_keywords = [
        "auth", "permission", "invalid", "configuration",
        "tradability", "gate_fail", "blocked",
    ]
    if any(keyword in error_type for keyword in non_recoverable_keywords):
        return False, f"Irrecoverable error type: {error_type}"
    
    # 可恢复错误
    if status == "failed" or error_type:
        return True, f"Retry eligible for error (attempt {retry_count + 1}/{max_retries + 1})"
    
    return False, "No retry needed (task completed or unknown state)"


def build_fallback_closeout(
    fallback_result: FallbackResult,
    batch_id: str,
    task_id: str,
    scenario: str,
) -> Dict[str, Any]:
    """
    构建 fallback closeout 数据结构。
    
    Args:
        fallback_result: Fallback 协议执行结果
        batch_id: 批次 ID
        task_id: 任务 ID
        scenario: 场景名称
    
    Returns:
        closeout 数据字典（可传递给 closeout_tracker）
    """
    # 根据 fallback result 决定 closeout 状态
    closeout_status_map: Dict[FallbackCloseoutStatus, str] = {
        "complete": "Closeout complete; awaiting git push",
        "pending_push": "Closeout complete; pending git push",
        "incomplete": "Closeout incomplete; has remaining work",
        "blocked": "Closeout blocked by error or gate failure",
        "stale": "Closeout stale;落后于最新 batch",
        "timeout_closeout": f"Timeout closeout after {fallback_result.retry_count} retries",
        "error_closeout": f"Error closeout: {fallback_result.failure_reason}",
        "empty_result_closeout": f"Empty result closeout (hard block): {fallback_result.failure_reason}",
    }
    
    closeout_reason = closeout_status_map.get(
        fallback_result.closeout_status,
        f"Unknown closeout status: {fallback_result.closeout_status}",
    )
    
    return {
        "batch_id": batch_id,
        "task_id": task_id,
        "scenario": scenario,
        "closeout_status": fallback_result.closeout_status,
        "verdict": fallback_result.verdict,
        "retry_count": fallback_result.retry_count,
        "retry_eligible": fallback_result.retry_eligible,
        "failure_type": fallback_result.failure_type,
        "failure_reason": fallback_result.failure_reason,
        "closeout_reason": closeout_reason,
        "continuation_contract": fallback_result.continuation_contract.to_dict() if fallback_result.continuation_contract else None,
        "metadata": {
            "fallback_protocol": FALLBACK_PROTOCOL_VERSION,
            "checked_at": datetime.now().isoformat(),
            **fallback_result.metadata,
        },
    }


# ============ Convenience functions ============

def evaluate_fallback(
    task_result: Dict[str, Any],
    retry_count: int = 0,
    batch_analysis: Optional[Dict[str, Any]] = None,
) -> FallbackResult:
    """
    Convenience function: 评估任务结果的 fallback 行为。
    
    Args:
        task_result: 任务执行结果
        retry_count: 当前已重试次数
        batch_analysis: batch 分析结果
    
    Returns:
        FallbackResult
    """
    protocol = FallbackProtocol()
    return protocol.evaluate(task_result, retry_count, batch_analysis)


# CLI 入口
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python fallback_protocol.py evaluate <result_json_file>")
        print("  python fallback_protocol.py check-empty <result_json_file>")
        print("  python fallback_protocol.py retry-check <result_json_file> <retry_count>")
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == "evaluate":
        if len(sys.argv) < 3:
            print("Error: missing result_json_file")
            sys.exit(1)
        
        result_file = Path(sys.argv[2])
        with open(result_file, "r") as f:
            task_result = json.load(f)
        
        result = evaluate_fallback(task_result)
        print(json.dumps(result.to_dict(), indent=2))
    
    elif cmd == "check-empty":
        if len(sys.argv) < 3:
            print("Error: missing result_json_file")
            sys.exit(1)
        
        result_file = Path(sys.argv[2])
        with open(result_file, "r") as f:
            task_result = json.load(f)
        
        empty_check = check_empty_result(task_result)
        print(json.dumps(empty_check, indent=2))
    
    elif cmd == "retry-check":
        if len(sys.argv) < 4:
            print("Error: missing result_json_file or retry_count")
            sys.exit(1)
        
        result_file = Path(sys.argv[2])
        retry_count = int(sys.argv[3])
        
        with open(result_file, "r") as f:
            task_result = json.load(f)
        
        eligible, reason = determine_retry_eligibility(task_result, retry_count)
        print(json.dumps({
            "retry_eligible": eligible,
            "reason": reason,
        }, indent=2))
    
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
