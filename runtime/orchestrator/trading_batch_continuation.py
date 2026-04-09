#!/usr/bin/env python3
"""
trading_batch_continuation.py — Trading Batch Continuation (Mechanism-Driven Auto-Continue)

实现 mechanism-driven auto-continue loop：
1. 从 closeout 提取 completion_gate
2. 加载 batch spec，评估 next_batch rule
3. 检查 safety gate / prerequisites / artifacts
4. 生成 next_batch dispatch request（stop-at-gate）
5. 提供 end-to-end proof 能力

这是 trading 特定的 continuation glue，依赖：
- schemas/trading_batch_spec.py (batch spec schema)
- core/handoff_schema.py (handoff schema)
- closeout_tracker.py (closeout state)
- auto_dispatch.py (dispatch execution)

设计原则：
1. 默认安全（auto_continue=false，除非 batch spec 显式启用）
2. stop-at-gate（所有生产动作必须显式确认）
3. 机器可读（batch spec 可被 orchestrator 直接消费）
4. 向后兼容（遵守已有 callback envelope）
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

# Import from canonical modules
try:
    from schemas.trading_batch_spec import (
        TradingBatchSpec,
        TradingBatchSpecCollection,
        TradingBatchSpecLoader,
        CompletionGate,
        SafetyGate,
        NextBatchRule,
        load_batch_spec,
        validate_batch_spec,
        TRADING_BATCH_SPEC_VERSION,
    )
except ImportError:
    from trading_batch_spec import (
        TradingBatchSpec,
        TradingBatchSpecCollection,
        TradingBatchSpecLoader,
        CompletionGate,
        SafetyGate,
        NextBatchRule,
        load_batch_spec,
        validate_batch_spec,
        TRADING_BATCH_SPEC_VERSION,
    )

from core.handoff_schema import (
    build_planning_handoff,
    build_registration_handoff,
    build_execution_handoff,
    PlanningHandoff,
    RegistrationHandoff,
    ExecutionHandoff,
)

from closeout_tracker import (
    get_closeout,
    check_push_consumer_status,
    CloseoutArtifact,
)

from partial_continuation import (
    ContinuationContract,
    build_continuation_contract,
)

from task_registration import (
    register_task,
    TaskRegistrationRecord,
)

__all__ = [
    "BatchContinuationResult",
    "NextBatchDispatchRequest",
    "TradingBatchContinuation",
    "evaluate_next_batch",
    "generate_dispatch_request",
    "execute_auto_continue",
    "BATCH_CONTINUATION_VERSION",
]

BATCH_CONTINUATION_VERSION = "trading_batch_continuation_v1"

# Default batch spec path
DEFAULT_BATCH_SPEC_PATH = Path(__file__).parent.parent.parent / "examples" / "trading" / "batch_spec_t0_t4.yaml"


@dataclass
class BatchContinuationResult:
    """
    Batch continuation result — 续批评估结果。
    
    核心字段：
    - current_batch_id: 当前 batch ID
    - completion_gate: 当前 completion gate
    - can_auto_continue: 是否可以自动续批
    - next_batch_id: 下一批 ID（如果有）
    - next_batch_rule: 匹配的 next_batch rule
    - blocker: 阻止续批的原因（如果有）
    - safety_gate_status: safety gate 状态
    - prerequisites_status: prerequisites 状态
    - artifacts_status: required artifacts 状态
    - recommended_action: 推荐的行动
    - metadata: 额外元数据
    """
    current_batch_id: str
    completion_gate: str
    can_auto_continue: bool
    next_batch_id: Optional[str]
    next_batch_rule: Optional[NextBatchRule]
    blocker: Optional[str]
    safety_gate_status: str
    prerequisites_status: Dict[str, Any]
    artifacts_status: Dict[str, Any]
    recommended_action: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "continuation_version": BATCH_CONTINUATION_VERSION,
            "current_batch_id": self.current_batch_id,
            "completion_gate": self.completion_gate,
            "can_auto_continue": self.can_auto_continue,
            "next_batch_id": self.next_batch_id,
            "next_batch_rule": self.next_batch_rule.to_dict() if self.next_batch_rule else None,
            "blocker": self.blocker,
            "safety_gate_status": self.safety_gate_status,
            "prerequisites_status": self.prerequisites_status,
            "artifacts_status": self.artifacts_status,
            "recommended_action": self.recommended_action,
            "metadata": self.metadata,
        }


@dataclass
class NextBatchDispatchRequest:
    """
    Next batch dispatch request — 下一批派发请求。
    
    核心字段：
    - request_id: 请求 ID
    - source_batch_id: 来源 batch ID
    - target_batch_id: 目标 batch ID
    - dispatch_profile: dispatch profile
    - executor: 执行器
    - task_preview: 任务预览
    - continuation_contract: continuation contract
    - safety_gates: safety gates
    - stop_at_gate: 是否 stop-at-gate
    - metadata: 额外元数据
    
    这是 mechanism-driven 的核心 artifact：
    - 不是 main 人工看结果后决定下一批
    - 而是根据 batch spec / closeout / rules 自动生成
    - 但默认 stop-at-gate，需要显式 consume
    """
    request_id: str
    source_batch_id: str
    target_batch_id: str
    dispatch_profile: str
    executor: str
    task_preview: str
    continuation_contract: ContinuationContract
    safety_gates: Dict[str, Any]
    stop_at_gate: bool
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "dispatch_request_version": BATCH_CONTINUATION_VERSION,
            "request_id": self.request_id,
            "source_batch_id": self.source_batch_id,
            "target_batch_id": self.target_batch_id,
            "dispatch_profile": self.dispatch_profile,
            "executor": self.executor,
            "task_preview": self.task_preview,
            "continuation_contract": self.continuation_contract.to_dict(),
            "safety_gates": self.safety_gates,
            "stop_at_gate": self.stop_at_gate,
            "metadata": self.metadata,
        }
    
    def to_planning_handoff(self) -> PlanningHandoff:
        """
        转换为 planning handoff。
        
        Returns:
            PlanningHandoff
        """
        return build_planning_handoff(
            source_type="completion_receipt",
            source_id=self.source_batch_id,
            continuation_contract=self.continuation_contract.to_dict(),
            scenario="trading_roundtable_phase1",
            adapter="trading",
            owner="trading",
            backend_preference="subagent",
            executor_preference=self.executor,
            execution_profile=self.dispatch_profile,  # type: ignore
            task_preview=self.task_preview,
            safety_gates=self.safety_gates,
            metadata={
                **self.metadata,
                "source": "trading_batch_continuation",
                "target_batch_id": self.target_batch_id,
            },
        )


class TradingBatchContinuation:
    """
    Trading batch continuation — 评估并生成下一批派发请求。
    
    提供：
    - load_batch_spec(): 加载 batch spec
    - evaluate_continuation(): 评估续批
    - generate_dispatch_request(): 生成派发请求
    - execute_auto_continue(): 执行自动续批
    """
    
    def __init__(
        self,
        batch_spec_path: Optional[Path] = None,
        batch_spec_collection: Optional[TradingBatchSpecCollection] = None,
    ):
        """
        初始化。
        
        Args:
            batch_spec_path: batch spec 文件路径（可选）
            batch_spec_collection: 已加载的 batch spec 集合（可选）
        """
        self.batch_spec_path = batch_spec_path or DEFAULT_BATCH_SPEC_PATH
        self._batch_spec_collection = batch_spec_collection
        self._loader = TradingBatchSpecLoader()
    
    def _get_batch_spec_collection(self) -> TradingBatchSpecCollection:
        """获取 batch spec 集合（懒加载）"""
        if self._batch_spec_collection is None:
            self._batch_spec_collection = load_batch_spec(self.batch_spec_path)
        return self._batch_spec_collection
    
    def reload_batch_spec(self) -> TradingBatchSpecCollection:
        """重新加载 batch spec"""
        self._batch_spec_collection = load_batch_spec(self.batch_spec_path)
        return self._batch_spec_collection
    
    def _get_completion_gate_from_closeout(
        self,
        batch_id: str,
        closeout: Optional[CloseoutArtifact] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> CompletionGate:
        """
        从 closeout 提取 completion gate。
        
        Args:
            batch_id: batch ID
            closeout: closeout artifact（可选，不提供则自动加载）
            context: 额外上下文（可选，可包含 completion_gate 覆盖）
        
        Returns:
            CompletionGate
        
        提取逻辑：
        1. 如果 context 包含 completion_gate，优先使用
        2. 优先从 closeout.metadata.roundtable.conclusion 提取
        3. 其次从 closeout.metadata.packet.overall_gate 提取
        4. 从 closeout.continuation_contract.stopped_because 推导
        5. 默认返回 CONDITIONAL
        """
        # 检查 context 中是否有 completion_gate 覆盖
        if context:
            context_gate = context.get("completion_gate")
            if context_gate:
                try:
                    return CompletionGate(context_gate)
                except ValueError:
                    pass
            
            # 检查 roundtable conclusion 在 context 中
            roundtable = context.get("roundtable", {})
            conclusion = str(roundtable.get("conclusion") or "").upper()
            if conclusion in ("PASS", "CONDITIONAL", "FAIL"):
                return CompletionGate(conclusion)
            
            # 检查 packet overall_gate 在 context 中
            packet = context.get("packet", {})
            overall_gate = str(packet.get("overall_gate") or "").upper()
            if overall_gate in ("PASS", "CONDITIONAL", "FAIL"):
                return CompletionGate(overall_gate)
        
        if closeout is None:
            closeout = get_closeout(batch_id)
        
        if closeout is None:
            # 没有 closeout，默认 CONDITIONAL
            return CompletionGate.CONDITIONAL
        
        # 尝试从 roundtable conclusion 提取
        roundtable = closeout.metadata.get("roundtable", {})
        conclusion = str(roundtable.get("conclusion") or "").upper()
        
        if conclusion == "PASS":
            return CompletionGate.PASS
        elif conclusion == "CONDITIONAL":
            return CompletionGate.CONDITIONAL
        elif conclusion == "FAIL":
            return CompletionGate.FAIL
        
        # 尝试从 packet overall_gate 提取
        packet = closeout.metadata.get("packet", {})
        overall_gate = str(packet.get("overall_gate") or "").upper()
        
        if overall_gate == "PASS":
            return CompletionGate.PASS
        elif overall_gate == "CONDITIONAL":
            return CompletionGate.CONDITIONAL
        elif overall_gate == "FAIL":
            return CompletionGate.FAIL
        
        # 尝试从 stopped_because 推导
        stopped_because = closeout.continuation_contract.stopped_because.lower()
        
        if "pass" in stopped_because and "conditional" not in stopped_because:
            return CompletionGate.PASS
        elif "conditional" in stopped_because:
            return CompletionGate.CONDITIONAL
        elif "fail" in stopped_because or "blocked" in stopped_because:
            return CompletionGate.FAIL
        elif "dry_run" in stopped_because and "pass" in stopped_because:
            return CompletionGate.DRY_RUN_PASS
        elif "dry_run" in stopped_because and "fail" in stopped_because:
            return CompletionGate.DRY_RUN_FAIL
        
        # 默认 CONDITIONAL
        return CompletionGate.CONDITIONAL
    
    def _get_completed_batches(self) -> List[str]:
        """
        获取已完成的 batch ID 列表。
        
        从 closeout 目录扫描，找到所有 closeout_status=complete 或 push_status=pushed 的 batch。
        
        Returns:
            completed batch ID 列表
        """
        from closeout_tracker import CLOSEOUT_DIR
        
        completed = []
        
        if not CLOSEOUT_DIR.exists():
            return completed
        
        for closeout_file in CLOSEOUT_DIR.glob("closeout-*.json"):
            try:
                with open(closeout_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                closeout_status = data.get("closeout_status", "")
                push_status = data.get("push_status", "")
                batch_id = data.get("batch_id", "")
                
                # 如果 closeout 完成或 push 已完成，视为 completed
                if closeout_status in ("complete",) or push_status in ("pushed", "not_required"):
                    completed.append(batch_id)
            except (json.JSONDecodeError, KeyError):
                pass
        
        return completed
    
    def _get_available_artifacts(self, batch_id: str) -> List[str]:
        """
        获取 batch 的可用 artifacts 列表。
        
        Args:
            batch_id: batch ID
        
        Returns:
            available artifact 路径列表
        """
        from closeout_tracker import CLOSEOUT_DIR
        
        artifacts = []
        closeout_file = CLOSEOUT_DIR / f"closeout-{batch_id.replace('/', '_')}.json"
        
        if closeout_file.exists():
            try:
                with open(closeout_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                closeout_artifacts = data.get("artifacts", {})
                for artifact_type, artifact_path in closeout_artifacts.items():
                    if Path(artifact_path).exists():
                        artifacts.append(artifact_path)
            except (json.JSONDecodeError, KeyError):
                pass
        
        return artifacts
    
    def evaluate_continuation(
        self,
        batch_id: str,
        closeout: Optional[CloseoutArtifact] = None,
        context: Optional[Dict[str, Any]] = None,
        completed_batches_override: Optional[List[str]] = None,
    ) -> BatchContinuationResult:
        """
        评估续批。
        
        Args:
            batch_id: 当前 batch ID
            closeout: closeout artifact（可选）
            context: 额外上下文
            completed_batches_override: 覆盖已完成的 batches 列表（用于测试）
        
        Returns:
            BatchContinuationResult
        """
        # 加载 batch spec
        collection = self._get_batch_spec_collection()
        
        # 获取 batch spec
        batch_spec = collection.get_batch(batch_id)
        if batch_spec is None:
            return BatchContinuationResult(
                current_batch_id=batch_id,
                completion_gate="UNKNOWN",
                can_auto_continue=False,
                next_batch_id=None,
                next_batch_rule=None,
                blocker=f"Batch {batch_id} not found in spec",
                safety_gate_status="unknown",
                prerequisites_status={"error": "batch not found"},
                artifacts_status={"error": "batch not found"},
                recommended_action="fix_batch_spec",
                metadata={"error": f"Batch {batch_id} not found in spec"},
            )
        
        # 获取 completion gate
        if closeout is None:
            closeout = get_closeout(batch_id)
        
        completion_gate = self._get_completion_gate_from_closeout(batch_id, closeout, context)
        
        # 获取已完成的 batches（可以使用 override）
        if completed_batches_override is not None:
            completed_batches = completed_batches_override
        else:
            completed_batches = self._get_completed_batches()
        
        # 获取可用 artifacts
        available_artifacts = self._get_available_artifacts(batch_id)
        
        # 使用 batch spec 计算续批路径
        continuation_path = collection.compute_continuation_path(
            current_batch_id=batch_id,
            completion_gate=completion_gate,
            completed_batches=completed_batches,
            available_artifacts=available_artifacts,
            context=context,
        )
        
        # 检查 prerequisites
        prereqs_ok, missing_prereqs = batch_spec.check_prerequisites_completed(completed_batches)
        prerequisites_status = {
            "ok": prereqs_ok,
            "missing": missing_prereqs,
            "completed_prerequisites": [p for p in batch_spec.prerequisites if p in completed_batches],
        }
        
        # 检查 required artifacts
        artifacts_ok, missing_artifacts = batch_spec.check_required_artifacts(available_artifacts)
        artifacts_status = {
            "ok": artifacts_ok,
            "missing": missing_artifacts,
            "available": available_artifacts,
        }
        
        # 构建结果
        can_auto_continue = continuation_path.get("can_auto_continue", False)
        next_batch_id = continuation_path.get("next_batch")  # Fixed: was "next_batch_id"
        blocker = continuation_path.get("blocker")
        safety_gate_status = continuation_path.get("safety_gate_status", "unknown")
        
        # 获取 next_batch_rule（如果 next_batch_id 存在）
        next_batch_rule = None
        if next_batch_id:
            next_batch_rule = batch_spec.evaluate_next_batch(completion_gate, context)
        
        # 决定 recommended action
        if can_auto_continue:
            recommended_action = "auto_dispatch"
        elif blocker:
            recommended_action = "manual_review"
        else:
            recommended_action = "stop"
        
        return BatchContinuationResult(
            current_batch_id=batch_id,
            completion_gate=completion_gate.value,
            can_auto_continue=can_auto_continue,
            next_batch_id=next_batch_id,
            next_batch_rule=next_batch_rule,
            blocker=blocker,
            safety_gate_status=safety_gate_status,
            prerequisites_status=prerequisites_status,
            artifacts_status=artifacts_status,
            recommended_action=recommended_action,
            metadata={
                "batch_spec_path": str(self.batch_spec_path),
                "closeout_id": closeout.closeout_id if closeout else None,
                "completed_batches": completed_batches,
                "continuation_path": continuation_path,
            },
        )
    
    def generate_dispatch_request(
        self,
        batch_id: str,
        continuation_result: BatchContinuationResult,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[NextBatchDispatchRequest]:
        """
        生成下一批派发请求。
        
        Args:
            batch_id: 当前 batch ID
            continuation_result: 续批评估结果
            context: 额外上下文
        
        Returns:
            NextBatchDispatchRequest，无法生成则返回 None
        """
        if not continuation_result.next_batch_id:
            return None
        
        if not continuation_result.next_batch_rule:
            return None
        
        # 生成 request ID
        import uuid
        request_id = f"dispatch_req_{uuid.uuid4().hex[:12]}"
        
        # 构建 task preview
        task_preview = f"Trading Batch {continuation_result.next_batch_id}: {continuation_result.next_batch_rule.next_batch_description}"
        
        # 构建 continuation contract
        continuation_contract = build_continuation_contract(
            stopped_because=f"batch_{batch_id}_{continuation_result.completion_gate.lower()}_complete",
            next_step=continuation_result.next_batch_rule.next_batch_description,
            next_owner="trading",
            metadata={
                "source_batch_id": batch_id,
                "target_batch_id": continuation_result.next_batch_id,
                "completion_gate": continuation_result.completion_gate,
                "next_batch_rule": continuation_result.next_batch_rule.to_dict(),
            },
        )
        
        # 构建 safety gates
        collection = self._get_batch_spec_collection()
        next_batch_spec = collection.get_batch(continuation_result.next_batch_id)
        
        safety_gates = {
            "allow_auto_dispatch": continuation_result.can_auto_continue,
            "stop_at_gate": next_batch_spec.safety_gate.stop_at_gate if next_batch_spec else True,
            "production_blockers": next_batch_spec.safety_gate.production_blockers if next_batch_spec else [],
            "require_manual_approval": next_batch_spec.safety_gate.require_manual_approval if next_batch_spec else True,
            "batch_spec_version": TRADING_BATCH_SPEC_VERSION,
        }
        
        # 决定 stop_at_gate
        stop_at_gate = (
            next_batch_spec.safety_gate.stop_at_gate if next_batch_spec else True
        )
        
        return NextBatchDispatchRequest(
            request_id=request_id,
            source_batch_id=batch_id,
            target_batch_id=continuation_result.next_batch_id,
            dispatch_profile=continuation_result.next_batch_rule.dispatch_profile,
            executor=continuation_result.next_batch_rule.executor,
            task_preview=task_preview,
            continuation_contract=continuation_contract,
            safety_gates=safety_gates,
            stop_at_gate=stop_at_gate,
            metadata={
                "generated_from": "trading_batch_continuation",
                "continuation_result": continuation_result.to_dict(),
                "context": context,
            },
        )
    
    def execute_auto_continue(
        self,
        batch_id: str,
        closeout: Optional[CloseoutArtifact] = None,
        dry_run: bool = True,
        context: Optional[Dict[str, Any]] = None,
        completed_batches_override: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        执行自动续批。
        
        Args:
            batch_id: 当前 batch ID
            closeout: closeout artifact（可选）
            dry_run: 是否干跑（默认 True，不真实 dispatch）
            context: 额外上下文
            completed_batches_override: 覆盖已完成的 batches 列表（用于测试）
        
        Returns:
            {
                "status": "success" | "blocked" | "dry_run",
                "continuation_result": BatchContinuationResult dict,
                "dispatch_request": NextBatchDispatchRequest dict (if generated),
                "registration_record": TaskRegistrationRecord dict (if registered),
                "blocker": str (if blocked),
            }
        """
        # 1. Evaluate continuation
        continuation_result = self.evaluate_continuation(
            batch_id, closeout, context, completed_batches_override
        )
        
        # 2. Check if auto-continue is allowed
        if not continuation_result.can_auto_continue:
            return {
                "status": "blocked",
                "continuation_result": continuation_result.to_dict(),
                "dispatch_request": None,
                "registration_record": None,
                "blocker": continuation_result.blocker,
            }
        
        # 3. Generate dispatch request
        dispatch_request = self.generate_dispatch_request(batch_id, continuation_result, context)
        
        if dispatch_request is None:
            return {
                "status": "blocked",
                "continuation_result": continuation_result.to_dict(),
                "dispatch_request": None,
                "registration_record": None,
                "blocker": "Failed to generate dispatch request",
            }
        
        # 4. Convert to planning handoff
        planning_handoff = dispatch_request.to_planning_handoff()
        
        # 5. Build registration handoff
        registration_handoff = build_registration_handoff(
            planning_handoff,
            batch_id=continuation_result.next_batch_id,
        )
        
        # 6. Register task (or dry run)
        registration_record = None
        if not dry_run:
            registration_record = register_from_handoff(registration_handoff)
        else:
            # Dry run: create a mock record dict (not TaskRegistrationRecord object)
            # Note: registration_handoff.truth_anchor is dict, not TruthAnchor object
            registration_record = {
                "registration_id": f"dry_run_{registration_handoff.registration_id}",
                "task_id": registration_handoff.task_id,
                "batch_id": continuation_result.next_batch_id,
                "registration_status": registration_handoff.registration_status,
                "registration_reason": "Dry run",
                "truth_anchor": registration_handoff.truth_anchor,  # dict
                "owner": registration_handoff.proposed_task.get("owner"),
                "status": "pending",
                "source_closeout": registration_handoff.source_closeout,
                "proposed_task": registration_handoff.proposed_task,
                "metadata": {"dry_run": True},
            }
        
        # 7. Return result
        result = {
            "status": "dry_run" if dry_run else "success",
            "continuation_result": continuation_result.to_dict(),
            "dispatch_request": dispatch_request.to_dict(),
            "registration_handoff": registration_handoff.to_dict(),
            "registration_record": registration_record if registration_record else None,  # Already dict in dry_run mode
            "blocker": None,
        }
        
        return result


def evaluate_next_batch(
    batch_id: str,
    batch_spec_path: Optional[Path] = None,
    context: Optional[Dict[str, Any]] = None,
) -> BatchContinuationResult:
    """
    Convenience function: 评估下一批。
    
    Args:
        batch_id: 当前 batch ID
        batch_spec_path: batch spec 文件路径（可选）
        context: 额外上下文
    
    Returns:
        BatchContinuationResult
    """
    continuation = TradingBatchContinuation(batch_spec_path)
    return continuation.evaluate_continuation(batch_id, context=context)


def generate_dispatch_request(
    batch_id: str,
    continuation_result: BatchContinuationResult,
    batch_spec_path: Optional[Path] = None,
    context: Optional[Dict[str, Any]] = None,
) -> Optional[NextBatchDispatchRequest]:
    """
    Convenience function: 生成派发请求。
    
    Args:
        batch_id: 当前 batch ID
        continuation_result: 续批评估结果
        batch_spec_path: batch spec 文件路径（可选）
        context: 额外上下文
    
    Returns:
        NextBatchDispatchRequest
    """
    continuation = TradingBatchContinuation(batch_spec_path)
    return continuation.generate_dispatch_request(batch_id, continuation_result, context)


def execute_auto_continue(
    batch_id: str,
    batch_spec_path: Optional[Path] = None,
    dry_run: bool = True,
    context: Optional[Dict[str, Any]] = None,
    completed_batches_override: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Convenience function: 执行自动续批。
    
    Args:
        batch_id: 当前 batch ID
        batch_spec_path: batch spec 文件路径（可选）
        dry_run: 是否干跑（默认 True）
        context: 额外上下文
        completed_batches_override: 覆盖已完成的 batches 列表（用于测试）
    
    Returns:
        auto-continue result dict
    """
    continuation = TradingBatchContinuation(batch_spec_path)
    return continuation.execute_auto_continue(
        batch_id, dry_run=dry_run, context=context, completed_batches_override=completed_batches_override
    )


# CLI 入口
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python trading_batch_continuation.py evaluate <batch_id> [--spec <path>]")
        print("  python trading_batch_continuation.py execute <batch_id> [--spec <path>] [--dry-run]")
        print("  python trading_batch_continuation.py validate-spec <path>")
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == "evaluate":
        if len(sys.argv) < 3:
            print("Error: missing batch_id")
            sys.exit(1)
        
        batch_id = sys.argv[2]
        spec_path = None
        
        if "--spec" in sys.argv:
            idx = sys.argv.index("--spec")
            if idx + 1 < len(sys.argv):
                spec_path = Path(sys.argv[idx + 1])
        
        result = evaluate_next_batch(batch_id, spec_path)
        print(json.dumps(result.to_dict(), indent=2))
    
    elif cmd == "execute":
        if len(sys.argv) < 3:
            print("Error: missing batch_id")
            sys.exit(1)
        
        batch_id = sys.argv[2]
        spec_path = None
        dry_run = True
        
        if "--spec" in sys.argv:
            idx = sys.argv.index("--spec")
            if idx + 1 < len(sys.argv):
                spec_path = Path(sys.argv[idx + 1])
        
        if "--no-dry-run" in sys.argv:
            dry_run = False
        
        result = execute_auto_continue(batch_id, spec_path, dry_run=dry_run)
        print(json.dumps(result, indent=2))
    
    elif cmd == "validate-spec":
        if len(sys.argv) < 3:
            print("Error: missing path")
            sys.exit(1)
        
        spec_path = Path(sys.argv[2])
        collection = load_batch_spec(spec_path)
        is_valid, errors = validate_batch_spec(collection)
        
        if is_valid:
            print("✓ Batch spec is valid")
        else:
            print("✗ Batch spec validation failed:")
            for error in errors:
                print(f"  - {error}")
            sys.exit(1)
    
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
