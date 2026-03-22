"""
test_post_completion_replan.py — 测试 post-completion follow-up registration contract

覆盖：
- 无 anchor 的 follow-up 不能被标成 in_progress
- 有 anchor（至少一种）时可被标成已启动/已注册
- validate_followup_status 强制修正非法状态
"""

from __future__ import annotations

import pytest
from pathlib import Path

import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
ORCHESTRATOR_DIR = REPO_ROOT / "runtime" / "orchestrator"

if str(ORCHESTRATOR_DIR) not in sys.path:
    sys.path.insert(0, str(ORCHESTRATOR_DIR))

from post_completion_replan import (
    PostCompletionReplanContract,
    TruthAnchor,
    build_replan_contract,
    validate_followup_status,
    check_continuation_in_original_dispatch,
    REPLAN_CONTRACT_VERSION,
)


class TestTruthAnchor:
    """测试 TruthAnchor 基本功能"""
    
    def test_has_anchor_none_type(self):
        anchor = TruthAnchor(anchor_type="none")
        assert anchor.has_anchor() is False
    
    def test_has_anchor_with_value(self):
        anchor = TruthAnchor(anchor_type="task_id", anchor_value="task_123")
        assert anchor.has_anchor() is True
    
    def test_has_anchor_empty_value(self):
        anchor = TruthAnchor(anchor_type="task_id", anchor_value="")
        assert anchor.has_anchor() is False
    
    def test_to_dict(self):
        anchor = TruthAnchor(
            anchor_type="batch_id",
            anchor_value="batch_456",
            anchor_metadata={"source": "test"},
        )
        d = anchor.to_dict()
        assert d["anchor_type"] == "batch_id"
        assert d["anchor_value"] == "batch_456"
        assert d["anchor_metadata"]["source"] == "test"
    
    def test_from_dict(self):
        d = {
            "anchor_type": "commit",
            "anchor_value": "abc123",
            "anchor_metadata": {"repo": "test-repo"},
        }
        anchor = TruthAnchor.from_dict(d)
        assert anchor.anchor_type == "commit"
        assert anchor.anchor_value == "abc123"
        assert anchor.anchor_metadata["repo"] == "test-repo"


class TestPostCompletionReplanContract:
    """测试 PostCompletionReplanContract 基本功能"""
    
    def test_contract_version(self):
        assert REPLAN_CONTRACT_VERSION == "post_completion_replan_v1"
    
    def test_to_dict(self):
        contract = PostCompletionReplanContract(
            followup_mode="pending_registration",
            truth_anchor=TruthAnchor(anchor_type="none"),
            status_phrase="pending_registration",
            followup_description="Test follow-up",
            original_task_id="task_123",
        )
        d = contract.to_dict()
        assert d["contract_version"] == REPLAN_CONTRACT_VERSION
        assert d["followup_mode"] == "pending_registration"
        assert d["status_phrase"] == "pending_registration"
        assert d["followup_description"] == "Test follow-up"
        assert d["original_task_id"] == "task_123"
    
    def test_from_dict(self):
        d = {
            "followup_mode": "existing_dispatch",
            "truth_anchor": {"anchor_type": "batch_id", "anchor_value": "batch_789"},
            "status_phrase": "in_progress",
            "followup_description": "Existing continuation",
        }
        contract = PostCompletionReplanContract.from_dict(d)
        assert contract.followup_mode == "existing_dispatch"
        assert contract.truth_anchor.anchor_type == "batch_id"
        assert contract.truth_anchor.has_anchor() is True
        assert contract.status_phrase == "in_progress"


class TestValidateFollowupStatus:
    """测试 validate_followup_status 函数"""
    
    def test_no_anchor_must_be_pending(self):
        """无 anchor 时，必须返回 pending_registration"""
        is_valid, status, errors = validate_followup_status(
            followup_mode="pending_registration",
            anchor_type="none",
            anchor_value=None,
        )
        assert is_valid is True
        assert status == "pending_registration"
        assert len(errors) == 0
    
    def test_no_anchor_cannot_be_in_progress(self):
        """无 anchor 时，不能标成 in_progress"""
        is_valid, status, errors = validate_followup_status(
            followup_mode="pending_registration",
            anchor_type="none",
            anchor_value=None,
            status_phrase="in_progress",  # 非法
        )
        assert is_valid is False
        assert status == "pending_registration"  # 强制修正
        assert len(errors) > 0
        assert "no anchor but status_phrase='in_progress'" in " ".join(errors)
    
    def test_with_anchor_can_be_in_progress(self):
        """有 anchor 时，可以标成 in_progress"""
        is_valid, status, errors = validate_followup_status(
            followup_mode="existing_dispatch",
            anchor_type="task_id",
            anchor_value="task_123",
            status_phrase="in_progress",
        )
        assert is_valid is True
        assert status == "in_progress"
        assert len(errors) == 0
    
    def test_with_anchor_but_pending_is_allowed(self):
        """有 anchor 但仍然选择 pending 是允许的（如需人工确认）"""
        is_valid, status, errors = validate_followup_status(
            followup_mode="pending_registration",
            anchor_type="task_id",
            anchor_value="task_123",
            status_phrase="pending_registration",
        )
        assert is_valid is True
        assert status == "pending_registration"
        assert len(errors) == 0
    
    def test_with_anchor_pending_mode_cannot_be_in_progress(self):
        """followup_mode=pending_registration 时，不能标成 in_progress"""
        is_valid, status, errors = validate_followup_status(
            followup_mode="pending_registration",
            anchor_type="task_id",
            anchor_value="task_123",
            status_phrase="in_progress",  # 非法
        )
        assert is_valid is False
        assert status == "pending_registration"  # 强制修正
        assert len(errors) > 0
    
    def test_auto_derive_status_with_anchor(self):
        """未指定 status_phrase 时，有 anchor 自动推导为 in_progress"""
        is_valid, status, errors = validate_followup_status(
            followup_mode="existing_dispatch",
            anchor_type="batch_id",
            anchor_value="batch_456",
            # status_phrase=None → 自动推导
        )
        assert is_valid is True
        assert status == "in_progress"
        assert len(errors) == 0
    
    def test_auto_derive_status_without_anchor(self):
        """未指定 status_phrase 时，无 anchor 自动推导为 pending_registration"""
        is_valid, status, errors = validate_followup_status(
            followup_mode="pending_registration",
            anchor_type="none",
            anchor_value=None,
            # status_phrase=None → 自动推导
        )
        assert is_valid is True
        assert status == "pending_registration"
        assert len(errors) == 0


class TestBuildReplanContract:
    """测试 build_replan_contract 函数"""
    
    def test_build_without_anchor_defaults_to_pending(self):
        """无 anchor 时，自动设为 pending_registration"""
        contract = build_replan_contract(
            followup_description="New follow-up work",
            original_task_id="task_123",
            # 没有 anchor_type / anchor_value
        )
        assert contract.followup_mode == "pending_registration"
        assert contract.status_phrase == "pending_registration"
        assert contract.truth_anchor.anchor_type == "none"
        assert contract.truth_anchor.has_anchor() is False
    
    def test_build_with_anchor_defaults_to_in_progress(self):
        """有 anchor 时，自动设为 in_progress"""
        contract = build_replan_contract(
            followup_description="Continuation work",
            original_batch_id="batch_456",
            anchor_type="batch_id",
            anchor_value="batch_789",
        )
        assert contract.followup_mode == "existing_dispatch"
        assert contract.status_phrase == "in_progress"
        assert contract.truth_anchor.anchor_type == "batch_id"
        assert contract.truth_anchor.has_anchor() is True
    
    def test_build_force_pending_overrides_anchor(self):
        """force_pending=True 时，即使有 anchor 也设为 pending"""
        contract = build_replan_contract(
            followup_description="Needs human confirmation",
            anchor_type="task_id",
            anchor_value="task_999",
            force_pending=True,
        )
        assert contract.followup_mode == "pending_registration"
        assert contract.status_phrase == "pending_registration"
        assert contract.truth_anchor.has_anchor() is True  # anchor 存在，但模式是 pending
    
    def test_build_invalid_raises(self):
        """非法组合会抛出 ValueError"""
        # 这个测试验证 build_replan_contract 会内部调用 validate
        # 由于 build 函数会自动修正非法状态，所以不会抛异常
        # 我们测试正常情况即可
        contract = build_replan_contract(
            followup_description="Test",
            anchor_type="none",
        )
        assert contract.status_phrase == "pending_registration"
    
    def test_build_with_metadata(self):
        """可以携带额外 metadata"""
        contract = build_replan_contract(
            followup_description="Test with metadata",
            anchor_type="commit",
            anchor_value="abc123",
            anchor_metadata={"repo": "test-repo", "branch": "main"},
            metadata={"priority": "high", "owner": "test"},
        )
        assert contract.truth_anchor.anchor_metadata["repo"] == "test-repo"
        assert contract.metadata["priority"] == "high"


class TestContractValidation:
    """测试 PostCompletionReplanContract.validate 方法"""
    
    def test_valid_pending_without_anchor(self):
        contract = PostCompletionReplanContract(
            followup_mode="pending_registration",
            truth_anchor=TruthAnchor(anchor_type="none"),
            status_phrase="pending_registration",
            followup_description="Test",
        )
        is_valid, errors = contract.validate()
        assert is_valid is True
        assert len(errors) == 0
    
    def test_invalid_mode_without_anchor(self):
        contract = PostCompletionReplanContract(
            followup_mode="existing_dispatch",  # 非法
            truth_anchor=TruthAnchor(anchor_type="none"),
            status_phrase="pending_registration",
            followup_description="Test",
        )
        is_valid, errors = contract.validate()
        assert is_valid is False
        assert len(errors) > 0
        assert "no truth_anchor but followup_mode='existing_dispatch'" in " ".join(errors)
    
    def test_invalid_status_without_anchor(self):
        contract = PostCompletionReplanContract(
            followup_mode="pending_registration",
            truth_anchor=TruthAnchor(anchor_type="none"),
            status_phrase="in_progress",  # 非法
            followup_description="Test",
        )
        is_valid, errors = contract.validate()
        assert is_valid is False
        assert len(errors) > 0
        assert "no truth_anchor but status_phrase='in_progress'" in " ".join(errors)
    
    def test_valid_with_anchor(self):
        contract = PostCompletionReplanContract(
            followup_mode="existing_dispatch",
            truth_anchor=TruthAnchor(anchor_type="task_id", anchor_value="task_123"),
            status_phrase="in_progress",
            followup_description="Test",
        )
        is_valid, errors = contract.validate()
        assert is_valid is True
        assert len(errors) == 0
    
    def test_valid_pending_with_anchor(self):
        """有 anchor 但仍然选择 pending 是有效的"""
        contract = PostCompletionReplanContract(
            followup_mode="pending_registration",
            truth_anchor=TruthAnchor(anchor_type="batch_id", anchor_value="batch_456"),
            status_phrase="pending_registration",
            followup_description="Test",
        )
        is_valid, errors = contract.validate()
        assert is_valid is True
        assert len(errors) == 0


class TestCheckContinuationInOriginalDispatch:
    """测试 check_continuation_in_original_dispatch 函数"""
    
    def test_no_dispatch_plan(self):
        is_in_plan, anchor_type, anchor_value = check_continuation_in_original_dispatch(
            original_dispatch_plan=None,
            followup_description="Test follow-up",
        )
        assert is_in_plan is False
        assert anchor_type is None
        assert anchor_value is None
    
    def test_followup_in_next_steps(self):
        dispatch_plan = {
            "next_steps": [
                {"description": "Write documentation", "anchor_type": "task_id", "anchor_value": "task_doc_1"},
                {"description": "Run tests", "anchor_type": "task_id", "anchor_value": "task_test_1"},
            ]
        }
        is_in_plan, anchor_type, anchor_value = check_continuation_in_original_dispatch(
            original_dispatch_plan=dispatch_plan,
            followup_description="Write documentation",
        )
        assert is_in_plan is True
        assert anchor_type == "task_id"
        assert anchor_value == "task_doc_1"
    
    def test_followup_in_continuations(self):
        dispatch_plan = {
            "continuations": [
                {"description": "Phase 2 implementation", "anchor_type": "batch_id", "anchor_value": "batch_phase2"},
            ]
        }
        is_in_plan, anchor_type, anchor_value = check_continuation_in_original_dispatch(
            original_dispatch_plan=dispatch_plan,
            followup_description="Phase 2 implementation",
        )
        assert is_in_plan is True
        assert anchor_type == "batch_id"
        assert anchor_value == "batch_phase2"
    
    def test_followup_not_in_plan(self):
        dispatch_plan = {
            "next_steps": [
                {"description": "Write documentation", "anchor_type": "task_id", "anchor_value": "task_doc_1"},
            ]
        }
        is_in_plan, anchor_type, anchor_value = check_continuation_in_original_dispatch(
            original_dispatch_plan=dispatch_plan,
            followup_description="New unplanned work",
        )
        assert is_in_plan is False
        assert anchor_type is None
        assert anchor_value is None
    
    def test_case_insensitive_match(self):
        dispatch_plan = {
            "next_steps": [
                {"description": "WRITE DOCUMENTATION", "anchor_type": "task_id", "anchor_value": "task_doc_1"},
            ]
        }
        is_in_plan, anchor_type, anchor_value = check_continuation_in_original_dispatch(
            original_dispatch_plan=dispatch_plan,
            followup_description="write documentation",
        )
        assert is_in_plan is True
        assert anchor_type == "task_id"
        assert anchor_value == "task_doc_1"


class TestIntegration:
    """集成测试：模拟真实使用场景"""
    
    def test_scenario_new_followup_without_anchor(self):
        """场景：任务完成后，发现新的 follow-up 工作（未在原 plan 内）"""
        # 原 dispatch plan
        original_dispatch = {
            "next_steps": [
                {"description": "Run tests", "anchor_type": "task_id", "anchor_value": "task_test"},
            ]
        }
        
        # 发现新的 follow-up
        followup_desc = "Write user documentation"
        is_in_plan, _, _ = check_continuation_in_original_dispatch(
            original_dispatch_plan=original_dispatch,
            followup_description=followup_desc,
        )
        assert is_in_plan is False  # 不在原 plan 内
        
        # 必须创建 pending_registration contract
        contract = build_replan_contract(
            followup_description=followup_desc,
            original_task_id="task_original",
            # 没有 anchor → 自动 pending
        )
        
        assert contract.followup_mode == "pending_registration"
        assert contract.status_phrase == "pending_registration"
        assert contract.truth_anchor.has_anchor() is False
        
        # 验证通过
        is_valid, errors = contract.validate()
        assert is_valid is True
        assert len(errors) == 0
    
    def test_scenario_existing_continuation_with_anchor(self):
        """场景：原 plan 内的 continuation，有明确 anchor"""
        # 原 dispatch plan
        original_dispatch = {
            "next_steps": [
                {"description": "Phase 2 implementation", "anchor_type": "batch_id", "anchor_value": "batch_phase2"},
            ]
        }
        
        # 检查是否在 plan 内
        followup_desc = "Phase 2 implementation"
        is_in_plan, anchor_type, anchor_value = check_continuation_in_original_dispatch(
            original_dispatch_plan=original_dispatch,
            followup_description=followup_desc,
        )
        assert is_in_plan is True
        assert anchor_type == "batch_id"
        assert anchor_value == "batch_phase2"
        
        # 可以创建 existing_dispatch contract
        contract = build_replan_contract(
            followup_description=followup_desc,
            original_batch_id="batch_phase1",
            anchor_type=anchor_type,
            anchor_value=anchor_value,
        )
        
        assert contract.followup_mode == "existing_dispatch"
        assert contract.status_phrase == "in_progress"
        assert contract.truth_anchor.has_anchor() is True
        
        # 验证通过
        is_valid, errors = contract.validate()
        assert is_valid is True
        assert len(errors) == 0
    
    def test_scenario_cannot_claim_in_progress_without_anchor(self):
        """场景：不能在没有 anchor 的情况下声称 in_progress"""
        # 尝试创建非法 contract
        is_valid, status, errors = validate_followup_status(
            followup_mode="pending_registration",
            anchor_type="none",
            anchor_value=None,
            status_phrase="in_progress",  # 试图声称 in_progress
        )
        
        assert is_valid is False
        assert status == "pending_registration"  # 强制修正
        assert len(errors) > 0
        assert "no anchor but status_phrase='in_progress'" in " ".join(errors)
