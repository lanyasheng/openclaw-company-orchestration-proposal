#!/usr/bin/env python3
"""
test_partial_continuation.py — Tests for Universal Partial-Completion Continuation Framework

覆盖：
- generic partial closeout contract 构建
- auto-replan 生成 next candidate / registration payload
- 无 remaining scope 时不生成 next registration
- 场景（trading/channel）能调用这个通用 kernel
"""

import pytest
import sys
from pathlib import Path
from datetime import datetime

# Add runtime/orchestrator to path for imports
RUNTIME_DIR = Path(__file__).parent.parent.parent / "runtime" / "orchestrator"
sys.path.insert(0, str(RUNTIME_DIR))

from partial_continuation import (
    ScopeItem,
    PartialCloseoutContract,
    NextTaskCandidate,
    NextTaskRegistrationPayload,
    ContinuationContract,
    build_continuation_contract,
    extract_continuation_contract,
    build_partial_closeout,
    auto_replan,
    build_next_task_registration,
    generate_next_registrations_for_closeout,
    adapt_closeout_for_trading,
    adapt_closeout_for_channel,
    PARTIAL_CLOSEOUT_VERSION,
    CONTINUATION_CONTRACT_VERSION,
)


class TestScopeItem:
    """测试 ScopeItem"""
    
    def test_scope_item_creation(self):
        """测试 ScopeItem 基本创建"""
        item = ScopeItem(
            item_id="scope_001",
            description="Test scope item",
            status="completed",
            metadata={"key": "value"},
        )
        
        assert item.item_id == "scope_001"
        assert item.description == "Test scope item"
        assert item.status == "completed"
        assert item.metadata == {"key": "value"}
    
    def test_scope_item_to_dict(self):
        """测试 ScopeItem 序列化"""
        item = ScopeItem(
            item_id="scope_001",
            description="Test",
            status="completed",
        )
        
        data = item.to_dict()
        assert data["item_id"] == "scope_001"
        assert data["description"] == "Test"
        assert data["status"] == "completed"
    
    def test_scope_item_from_dict(self):
        """测试 ScopeItem 反序列化"""
        data = {
            "item_id": "scope_002",
            "description": "From dict",
            "status": "partial",
            "metadata": {"test": True},
        }
        
        item = ScopeItem.from_dict(data)
        assert item.item_id == "scope_002"
        assert item.description == "From dict"
        assert item.status == "partial"
        assert item.metadata == {"test": True}


class TestPartialCloseoutContract:
    """测试 PartialCloseoutContract"""
    
    def test_basic_creation(self):
        """测试基本创建"""
        contract = PartialCloseoutContract(
            completed_scope=[
                ScopeItem(item_id="c1", description="Completed item 1", status="completed"),
            ],
            remaining_scope=[
                ScopeItem(item_id="r1", description="Remaining item 1", status="not_started"),
            ],
            stop_reason="partial_completed",
            dispatch_readiness="needs_review",
            original_task_id="task_123",
        )
        
        assert len(contract.completed_scope) == 1
        assert len(contract.remaining_scope) == 1
        assert contract.stop_reason == "partial_completed"
        assert contract.dispatch_readiness == "needs_review"
        assert contract.original_task_id == "task_123"
    
    def test_has_remaining_work(self):
        """测试 has_remaining_work"""
        # 有 remaining work
        contract = PartialCloseoutContract(
            remaining_scope=[ScopeItem(item_id="r1", description="R1")],
        )
        assert contract.has_remaining_work() is True
        
        # 无 remaining work
        contract = PartialCloseoutContract(
            remaining_scope=[],
        )
        assert contract.has_remaining_work() is False
    
    def test_is_fully_completed(self):
        """测试 is_fully_completed"""
        # 全部完成
        contract = PartialCloseoutContract(
            completed_scope=[ScopeItem(item_id="c1", description="C1")],
            remaining_scope=[],
            stop_reason="completed_all",
        )
        assert contract.is_fully_completed() is True
        
        # 有 remaining work
        contract = PartialCloseoutContract(
            remaining_scope=[ScopeItem(item_id="r1", description="R1")],
        )
        assert contract.is_fully_completed() is False
        
        # stop_reason 不是 completed_all
        contract = PartialCloseoutContract(
            remaining_scope=[],
            stop_reason="manual_stop",
        )
        assert contract.is_fully_completed() is False
    
    def test_should_generate_next_registration(self):
        """测试 should_generate_next_registration"""
        # 全部完成 -> 不生成
        contract = PartialCloseoutContract(
            remaining_scope=[],
            stop_reason="completed_all",
        )
        assert contract.should_generate_next_registration() is False
        
        # 有 remaining work 且 dispatch_readiness != "blocked" -> 生成
        contract = PartialCloseoutContract(
            remaining_scope=[ScopeItem(item_id="r1", description="R1")],
            stop_reason="partial_completed",
            dispatch_readiness="needs_review",
        )
        assert contract.should_generate_next_registration() is True
        
        # 有 remaining work 但 dispatch_readiness = "blocked" -> 不生成
        contract = PartialCloseoutContract(
            remaining_scope=[ScopeItem(item_id="r1", description="R1")],
            stop_reason="blocked",
            dispatch_readiness="blocked",
        )
        assert contract.should_generate_next_registration() is False
        
        # 无 remaining work -> 不生成
        contract = PartialCloseoutContract(
            remaining_scope=[],
            stop_reason="manual_stop",
        )
        assert contract.should_generate_next_registration() is False
    
    def test_validate_consistent(self):
        """测试 validate - 一致的情况"""
        contract = PartialCloseoutContract(
            completed_scope=[ScopeItem(item_id="c1", description="C1")],
            remaining_scope=[ScopeItem(item_id="r1", description="R1")],
            stop_reason="partial_completed",
            dispatch_readiness="needs_review",
        )
        
        is_valid, errors = contract.validate()
        assert is_valid is True
        assert len(errors) == 0
    
    def test_validate_inconsistent_stop_reason(self):
        """测试 validate - stop_reason 与 scopes 不一致"""
        contract = PartialCloseoutContract(
            completed_scope=[],
            remaining_scope=[ScopeItem(item_id="r1", description="R1")],
            stop_reason="completed_all",  # 不一致
        )
        
        is_valid, errors = contract.validate()
        assert is_valid is False
        assert any("completed_all" in err for err in errors)
    
    def test_validate_inconsistent_readiness(self):
        """测试 validate - dispatch_readiness 与 stop_reason 不一致"""
        contract = PartialCloseoutContract(
            remaining_scope=[],
            stop_reason="blocked",
            dispatch_readiness="ready",  # 不一致
        )
        
        is_valid, errors = contract.validate()
        assert is_valid is False
        assert any("blocked" in err and "ready" in err for err in errors)
    
    def test_to_dict_and_from_dict(self):
        """测试序列化和反序列化"""
        original = PartialCloseoutContract(
            completed_scope=[ScopeItem(item_id="c1", description="C1", status="completed")],
            remaining_scope=[ScopeItem(item_id="r1", description="R1", status="not_started")],
            stop_reason="partial_completed",
            dispatch_readiness="needs_review",
            original_task_id="task_123",
            original_batch_id="batch_456",
            metadata={"test": True},
        )
        
        data = original.to_dict()
        restored = PartialCloseoutContract.from_dict(data)
        
        assert restored.stop_reason == original.stop_reason
        assert restored.dispatch_readiness == original.dispatch_readiness
        assert restored.original_task_id == original.original_task_id
        assert restored.original_batch_id == original.original_batch_id
        assert len(restored.completed_scope) == 1
        assert len(restored.remaining_scope) == 1


class TestBuildPartialCloseout:
    """测试 build_partial_closeout"""
    
    def test_build_with_completed_and_remaining(self):
        """测试构建有 completed 和 remaining 的 closeout"""
        contract = build_partial_closeout(
            completed_scope=[
                {"item_id": "c1", "description": "Completed 1"},
                {"item_id": "c2", "description": "Completed 2"},
            ],
            remaining_scope=[
                {"item_id": "r1", "description": "Remaining 1"},
            ],
            stop_reason="partial_completed",
            original_task_id="task_123",
        )
        
        assert len(contract.completed_scope) == 2
        assert len(contract.remaining_scope) == 1
        assert contract.stop_reason == "partial_completed"
        assert contract.original_task_id == "task_123"
    
    def test_build_auto_derives_readiness(self):
        """测试自动推导 dispatch_readiness"""
        # partial_completed -> needs_review
        contract = build_partial_closeout(
            remaining_scope=[ScopeItem(item_id="r1", description="R1")],
            stop_reason="partial_completed",
        )
        assert contract.dispatch_readiness == "needs_review"
        
        # blocked -> blocked
        contract = build_partial_closeout(
            remaining_scope=[],
            stop_reason="blocked",
        )
        assert contract.dispatch_readiness == "blocked"
        
        # completed_all -> not_applicable
        contract = build_partial_closeout(
            remaining_scope=[],
            stop_reason="completed_all",
        )
        assert contract.dispatch_readiness == "not_applicable"
    
    def test_build_empty_scopes(self):
        """测试空 scopes"""
        contract = build_partial_closeout()
        
        assert len(contract.completed_scope) == 0
        assert len(contract.remaining_scope) == 0
        assert contract.stop_reason == "completed_all"


class TestAutoReplan:
    """测试 auto_replan"""
    
    def test_auto_replan_with_remaining_work(self):
        """测试有 remaining work 时生成 candidates"""
        closeout = build_partial_closeout(
            completed_scope=[{"item_id": "c1", "description": "Done"}],
            remaining_scope=[
                {"item_id": "r1", "description": "Need to do this"},
                {"item_id": "r2", "description": "Also need this"},
            ],
            stop_reason="partial_completed",
        )
        
        candidates = auto_replan(closeout, max_candidates=3)
        
        assert len(candidates) == 2
        assert candidates[0].description == "Need to do this"
        assert candidates[1].description == "Also need this"
        assert all("source_scope_item_id" in c.metadata for c in candidates)
    
    def test_auto_replan_no_remaining_work(self):
        """测试无 remaining work 时不生成 candidates"""
        closeout = build_partial_closeout(
            remaining_scope=[],
            stop_reason="completed_all",
        )
        
        candidates = auto_replan(closeout)
        
        assert len(candidates) == 0
    
    def test_auto_replan_respects_max_candidates(self):
        """测试 max_candidates 限制"""
        closeout = build_partial_closeout(
            remaining_scope=[
                {"item_id": f"r{i}", "description": f"Item {i}"}
                for i in range(10)
            ],
            stop_reason="partial_completed",
        )
        
        candidates = auto_replan(closeout, max_candidates=3)
        
        assert len(candidates) == 3
    
    def test_auto_replan_priority_by_status(self):
        """测试根据 status 设置 priority"""
        closeout = build_partial_closeout(
            remaining_scope=[
                {"item_id": "r1", "description": "Partial", "status": "partial"},
                {"item_id": "r2", "description": "Blocked", "status": "blocked"},
                {"item_id": "r3", "description": "Not started", "status": "not_started"},
            ],
            stop_reason="partial_completed",
        )
        
        candidates = auto_replan(closeout, max_candidates=5)
        
        # partial 的 priority 应该是 1
        partial_candidate = next(c for c in candidates if c.metadata["source_scope_item_id"] == "r1")
        assert partial_candidate.priority == 1
        
        # blocked 的 priority 应该是 2
        blocked_candidate = next(c for c in candidates if c.metadata["source_scope_item_id"] == "r2")
        assert blocked_candidate.priority == 2
    
    def test_auto_replan_sorted_by_priority(self):
        """测试 candidates 按 priority 排序"""
        closeout = build_partial_closeout(
            remaining_scope=[
                {"item_id": "r1", "description": "Not blocked", "status": "not_started"},
                {"item_id": "r2", "description": "Blocked", "status": "blocked"},
            ],
            stop_reason="partial_completed",
        )
        
        candidates = auto_replan(closeout)
        
        # priority 1 (not blocked) 应该在 priority 2 (blocked) 前面
        assert candidates[0].priority <= candidates[1].priority


class TestBuildNextTaskRegistration:
    """测试 build_next_task_registration"""
    
    def test_build_registration(self):
        """测试构建 registration payload"""
        closeout = build_partial_closeout(
            remaining_scope=[{"item_id": "r1", "description": "Next step"}],
            stop_reason="partial_completed",
            original_task_id="task_123",
        )
        
        candidates = auto_replan(closeout)
        assert len(candidates) == 1
        
        registration = build_next_task_registration(
            closeout=closeout,
            candidate=candidates[0],
            adapter="test_adapter",
            scenario="test_scenario",
        )
        
        assert registration.registration_id.startswith("reg_")
        assert registration.source_closeout["stop_reason"] == "partial_completed"
        assert registration.candidate["candidate_id"] == candidates[0].candidate_id
        assert registration.proposed_task["task_type"] == "continuation"
        assert registration.proposed_task["source"]["original_task_id"] == "task_123"
        assert registration.proposed_task["context"]["adapter"] == "test_adapter"
        assert registration.proposed_task["context"]["scenario"] == "test_scenario"
    
    def test_registration_requires_approval_when_not_ready(self):
        """测试 dispatch_readiness != ready 时需要审批"""
        closeout = build_partial_closeout(
            remaining_scope=[{"item_id": "r1", "description": "R1"}],
            stop_reason="blocked",
            dispatch_readiness="blocked",
        )
        
        candidates = auto_replan(closeout)
        registration = build_next_task_registration(
            closeout=closeout,
            candidate=candidates[0],
        )
        
        assert registration.requires_manual_approval is True
    
    def test_registration_no_approval_when_ready(self):
        """测试 dispatch_readiness = ready 时不需要审批"""
        closeout = build_partial_closeout(
            remaining_scope=[{"item_id": "r1", "description": "R1"}],
            stop_reason="partial_completed",
            dispatch_readiness="ready",
        )
        
        candidates = auto_replan(closeout)
        registration = build_next_task_registration(
            closeout=closeout,
            candidate=candidates[0],
            requires_manual_approval=False,
        )
        
        assert registration.requires_manual_approval is False


class TestGenerateNextRegistrationsForCloseout:
    """测试 generate_next_registrations_for_closeout"""
    
    def test_generate_registrations(self):
        """测试生成 registrations"""
        closeout = build_partial_closeout(
            remaining_scope=[
                {"item_id": "r1", "description": "Step 1"},
                {"item_id": "r2", "description": "Step 2"},
            ],
            stop_reason="partial_completed",
            dispatch_readiness="needs_review",
        )
        
        registrations = generate_next_registrations_for_closeout(
            closeout=closeout,
            adapter="test",
            max_candidates=5,
        )
        
        assert len(registrations) == 2
        assert all(r.requires_manual_approval is True for r in registrations)
        assert all(r.metadata.get("auto_generated") is True for r in registrations)
    
    def test_no_registrations_when_fully_completed(self):
        """测试全部完成时不生成 registrations"""
        closeout = build_partial_closeout(
            remaining_scope=[],
            stop_reason="completed_all",
        )
        
        registrations = generate_next_registrations_for_closeout(closeout)
        
        assert len(registrations) == 0
    
    def test_no_registrations_when_blocked(self):
        """测试 blocked 时不生成 registrations"""
        closeout = build_partial_closeout(
            remaining_scope=[{"item_id": "r1", "description": "R1"}],
            stop_reason="blocked",
            dispatch_readiness="blocked",
        )
        
        registrations = generate_next_registrations_for_closeout(closeout)
        
        assert len(registrations) == 0


class TestAdaptCloseoutForTrading:
    """测试 trading 场景适配"""
    
    def test_adapt_for_trading_pass(self):
        """测试 trading PASS 场景"""
        closeout = build_partial_closeout(
            remaining_scope=[{"item_id": "r1", "description": "Phase 2"}],
            stop_reason="partial_completed",
        )
        
        adapted = adapt_closeout_for_trading(
            closeout=closeout,
            packet={"overall_gate": "PASS"},
            roundtable={"conclusion": "PASS", "blocker": "none"},
        )
        
        assert adapted.metadata["adapter"] == "trading_roundtable"
        assert adapted.metadata["trading_packet"]["overall_gate"] == "PASS"
        assert adapted.dispatch_readiness == "ready"
    
    def test_adapt_for_trading_conditional(self):
        """测试 trading CONDITIONAL 场景"""
        closeout = build_partial_closeout(
            remaining_scope=[{"item_id": "r1", "description": "Fix blocker"}],
            stop_reason="partial_completed",
        )
        
        adapted = adapt_closeout_for_trading(
            closeout=closeout,
            roundtable={"conclusion": "CONDITIONAL", "blocker": "tradability"},
        )
        
        assert adapted.dispatch_readiness == "needs_review"
    
    def test_adapt_for_trading_blocked(self):
        """测试 trading blocked 场景"""
        closeout = build_partial_closeout(
            remaining_scope=[{"item_id": "r1", "description": "Resolve blocker"}],
            stop_reason="blocked",
        )
        
        adapted = adapt_closeout_for_trading(
            closeout=closeout,
            roundtable={"conclusion": "FAIL", "blocker": "implementation_risk"},
        )
        
        assert adapted.dispatch_readiness == "blocked"


class TestAdaptCloseoutForChannel:
    """测试 channel 场景适配"""
    
    def test_adapt_for_channel_pass(self):
        """测试 channel PASS 场景"""
        closeout = build_partial_closeout(
            remaining_scope=[{"item_id": "r1", "description": "Next discussion"}],
            stop_reason="partial_completed",
        )
        
        adapted = adapt_closeout_for_channel(
            closeout=closeout,
            channel_packet={"scenario": "architecture_roundtable"},
            roundtable={"conclusion": "PASS", "blocker": "none"},
        )
        
        assert adapted.metadata["adapter"] == "channel_roundtable"
        assert adapted.dispatch_readiness == "ready"
    
    def test_adapt_for_channel_needs_review(self):
        """测试 channel needs_review 场景"""
        closeout = build_partial_closeout(
            remaining_scope=[{"item_id": "r1", "description": "More discussion"}],
            stop_reason="partial_completed",
        )
        
        adapted = adapt_closeout_for_channel(
            closeout=closeout,
            roundtable={"conclusion": "CONDITIONAL", "blocker": "more_research"},
        )
        
        assert adapted.dispatch_readiness == "needs_review"


class TestContinuationContract:
    """测试 ContinuationContract（P0-1 Batch 1）"""
    
    def test_continuation_contract_creation(self):
        """测试基本创建"""
        contract = ContinuationContract(
            stopped_because="tmux_completion_report_ready",
            next_step="review tmux completion artifacts",
            next_owner="main",
        )
        
        assert contract.stopped_because == "tmux_completion_report_ready"
        assert contract.next_step == "review tmux completion artifacts"
        assert contract.next_owner == "main"
    
    def test_continuation_contract_validation(self):
        """测试验证"""
        # 有效 contract
        contract = ContinuationContract(
            stopped_because="test",
            next_step="test",
            next_owner="test",
        )
        is_valid, errors = contract.validate()
        assert is_valid is True
        assert len(errors) == 0
        
        # 无效 contract - 空 stopped_because
        contract = ContinuationContract(
            stopped_because="",
            next_step="test",
            next_owner="test",
        )
        is_valid, errors = contract.validate()
        assert is_valid is False
        assert any("stopped_because" in err for err in errors)
        
        # 无效 contract - 空 next_step
        contract = ContinuationContract(
            stopped_because="test",
            next_step="",
            next_owner="test",
        )
        is_valid, errors = contract.validate()
        assert is_valid is False
        assert any("next_step" in err for err in errors)
        
        # 无效 contract - 空 next_owner
        contract = ContinuationContract(
            stopped_because="test",
            next_step="test",
            next_owner="",
        )
        is_valid, errors = contract.validate()
        assert is_valid is False
        assert any("next_owner" in err for err in errors)
    
    def test_continuation_contract_to_dict(self):
        """测试序列化"""
        contract = ContinuationContract(
            stopped_because="test_stop",
            next_step="test_next",
            next_owner="test_owner",
            metadata={"key": "value"},
        )
        
        data = contract.to_dict()
        assert data["contract_version"] == CONTINUATION_CONTRACT_VERSION
        assert data["stopped_because"] == "test_stop"
        assert data["next_step"] == "test_next"
        assert data["next_owner"] == "test_owner"
        assert data["metadata"] == {"key": "value"}
    
    def test_continuation_contract_from_dict(self):
        """测试反序列化"""
        data = {
            "contract_version": CONTINUATION_CONTRACT_VERSION,
            "stopped_because": "from_dict_stop",
            "next_step": "from_dict_next",
            "next_owner": "from_dict_owner",
            "metadata": {"test": True},
        }
        
        contract = ContinuationContract.from_dict(data)
        assert contract.stopped_because == "from_dict_stop"
        assert contract.next_step == "from_dict_next"
        assert contract.next_owner == "from_dict_owner"
        assert contract.metadata == {"test": True}
    
    def test_merge_into_closeout(self):
        """测试合并到 closeout"""
        contract = ContinuationContract(
            stopped_because="blocked_by_tradability",
            next_step="fix tradability issues",
            next_owner="trading",
        )
        
        closeout = build_partial_closeout(
            remaining_scope=[{"item_id": "r1", "description": "Fix issues"}],
            stop_reason="partial_completed",
        )
        
        merged = contract.merge_into_closeout(closeout)
        
        assert merged.metadata["continuation_contract"]["stopped_because"] == "blocked_by_tradability"
        assert merged.metadata["stopped_because"] == "blocked_by_tradability"
        assert merged.metadata["next_step"] == "fix tradability issues"
        assert merged.metadata["next_owner"] == "trading"
    
    def test_from_closeout(self):
        """测试从 closeout 提取"""
        closeout = build_partial_closeout(
            completed_scope=[{"item_id": "c1", "description": "Done"}],
            remaining_scope=[{"item_id": "r1", "description": "Next step from remaining"}],
            stop_reason="partial_completed",
            metadata={
                "stopped_because": "extracted_stop",
                "next_step": "extracted_next",
                "next_owner": "extracted_owner",
            },
        )
        
        contract = ContinuationContract.from_closeout(closeout)
        
        assert contract.stopped_because == "extracted_stop"
        assert contract.next_step == "extracted_next"
        assert contract.next_owner == "extracted_owner"
        assert contract.metadata["source"] == "partial_closeout"
    
    def test_from_closeout_derives_next_step(self):
        """测试从 closeout 剩余范围推导 next_step"""
        closeout = build_partial_closeout(
            remaining_scope=[{"item_id": "r1", "description": "Derived from remaining scope"}],
            stop_reason="partial_completed",
        )
        
        contract = ContinuationContract.from_closeout(closeout)
        
        assert "Derived from remaining scope" in contract.next_step
    
    def test_build_continuation_contract(self):
        """测试 build_continuation_contract helper"""
        contract = build_continuation_contract(
            stopped_because="test_stop",
            next_step="test_next",
            next_owner="test_owner",
            metadata={"custom": "value"},
        )
        
        assert contract.stopped_because == "test_stop"
        assert isinstance(contract, ContinuationContract)
        assert contract.metadata["custom"] == "value"
    
    def test_extract_continuation_contract_from_closeout(self):
        """测试从 closeout payload 提取"""
        payload = {
            "closeout": {
                "stopped_because": "from_closeout",
                "next_step": "next from closeout",
                "next_owner": "owner from closeout",
            }
        }
        
        contract = extract_continuation_contract(payload, source="test")
        
        assert contract is not None
        assert contract.stopped_because == "from_closeout"
        assert "closeout:test" in contract.metadata["source"]
    
    def test_extract_continuation_contract_from_tmux_receipt(self):
        """测试从 tmux receipt 提取"""
        payload = {
            "tmux_terminal_receipt": {
                "stopped_because": "from_tmux",
                "next_step": "next from tmux",
                "next_owner": "owner from tmux",
            }
        }
        
        contract = extract_continuation_contract(payload, source="tmux")
        
        assert contract is not None
        assert contract.stopped_because == "from_tmux"
        assert "tmux_receipt:tmux" in contract.metadata["source"]
    
    def test_extract_continuation_contract_from_metadata(self):
        """测试从 metadata 提取"""
        payload = {
            "metadata": {
                "stopped_because": "from_metadata",
                "next_step": "next from metadata",
                "next_owner": "owner from metadata",
            }
        }
        
        contract = extract_continuation_contract(payload, source="meta")
        
        assert contract is not None
        assert contract.stopped_because == "from_metadata"
    
    def test_extract_continuation_contract_returns_none(self):
        """测试无 continuation 信息时返回 None"""
        payload = {"other": "data"}
        
        contract = extract_continuation_contract(payload)
        
        assert contract is None


class TestIntegrationScenario:
    """集成测试：模拟真实场景"""
    
    def test_trading_partial_completion_workflow(self):
        """测试 trading partial completion 完整流程"""
        # 1. 构建 partial closeout
        closeout = build_partial_closeout(
            completed_scope=[
                {"item_id": "c1", "description": "Phase 1 artifact generated"},
                {"item_id": "c2", "description": "Tests passed"},
            ],
            remaining_scope=[
                {"item_id": "r1", "description": "Phase 2: implement continuation logic"},
                {"item_id": "r2", "description": "Phase 2: add tests"},
            ],
            stop_reason="partial_completed",
            original_task_id="task_trading_phase1",
            original_batch_id="batch_trading_001",
        )
        
        # 2. 适配 trading 场景
        adapted = adapt_closeout_for_trading(
            closeout=closeout,
            packet={"overall_gate": "PASS", "phase_id": "trading_phase1"},
            roundtable={"conclusion": "PASS", "blocker": "none", "next_step": "Phase 2"},
        )
        
        assert adapted.dispatch_readiness == "ready"
        
        # 3. 生成 next task registrations
        registrations = generate_next_registrations_for_closeout(
            closeout=adapted,
            adapter="trading_roundtable",
            scenario="trading_roundtable_phase2",
        )
        
        # 4. 验证 registrations
        assert len(registrations) == 2  # 2 remaining items
        assert registrations[0].proposed_task["context"]["adapter"] == "trading_roundtable"
        assert registrations[0].proposed_task["source"]["original_batch_id"] == "batch_trading_001"
        
        # 5. 验证 registration payload 结构完整
        reg_dict = registrations[0].to_dict()
        assert "registration_version" in reg_dict
        assert "source_closeout" in reg_dict
        assert "candidate" in reg_dict
        assert "proposed_task" in reg_dict
    
    def test_channel_no_remaining_work(self):
        """测试 channel 无 remaining work 场景"""
        closeout = build_partial_closeout(
            completed_scope=[
                {"item_id": "c1", "description": "Discussion completed"},
            ],
            remaining_scope=[],
            stop_reason="completed_all",
        )
        
        adapted = adapt_closeout_for_channel(
            closeout=closeout,
            roundtable={"conclusion": "PASS", "blocker": "none"},
        )
        
        registrations = generate_next_registrations_for_closeout(
            closeout=adapted,
            adapter="channel_roundtable",
        )
        
        # 无 remaining work，不应生成 registrations
        assert len(registrations) == 0
    
    def test_blocked_workflow_no_registrations(self):
        """测试 blocked 工作流不生成 registrations"""
        closeout = build_partial_closeout(
            completed_scope=[{"item_id": "c1", "description": "Attempted"}],
            remaining_scope=[{"item_id": "r1", "description": "Blocked step"}],
            stop_reason="blocked",
            dispatch_readiness="blocked",  # 明确设置 blocked
        )
        
        # 注意：adapt_closeout_for_trading 会把 FAIL 结论设置成 blocked
        adapted = adapt_closeout_for_trading(
            closeout=closeout,
            roundtable={"conclusion": "FAIL", "blocker": "critical_issue"},
        )
        
        # 验证 dispatch_readiness 确实是 blocked
        assert adapted.dispatch_readiness == "blocked"
        
        registrations = generate_next_registrations_for_closeout(
            closeout=adapted,
            adapter="trading_roundtable",
        )
        
        # blocked 时不应生成 registrations
        assert len(registrations) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
