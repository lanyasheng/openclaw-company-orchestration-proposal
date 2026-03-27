#!/usr/bin/env python3
"""
adapters/trading.py — Trading Adapter

交易适配器实现，处理 trading roundtable 特定逻辑。

实现：
- Trading packet 验证
- Trading summary 构建
- Trading continuation plan
- Trading auto-dispatch readiness
- Trading followup prompt
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from adapters.base import BaseAdapter, AdapterMetadata

__all__ = [
    "TradingAdapter",
    "TRADING_ADAPTER_VERSION",
]

TRADING_ADAPTER_VERSION = "trading_adapter_v1"

# Trading 特定常量
ADAPTER_NAME = "trading_roundtable"
SCENARIO = "trading_roundtable_phase1"
PACKET_VERSION = "trading_phase1_packet_v1"
PHASE_ID = "trading_phase1"

# 必需字段定义
ROUNDTABLE_REQUIRED_FIELDS = [
    "conclusion",
    "blocker",
    "owner",
    "next_step",
    "completion_criteria",
]
TOP_LEVEL_PACKET_REQUIRED_FIELDS = [
    "packet_version",
    "phase_id",
    "candidate_id",
    "run_label",
    "input_config_path",
    "generated_at",
    "owner",
    "overall_gate",
    "primary_blocker",
]
ARTIFACT_REQUIRED_FIELDS = [
    ("artifact", "path"),
    ("artifact", "exists"),
    ("report", "path"),
    ("report", "exists"),
    ("commit", "repo"),
    ("commit", "git_commit"),
    ("test", "commands"),
    ("test", "summary"),
    ("repro", "commands"),
    ("repro", "notes"),
]
TRADABILITY_REQUIRED_FIELDS = [
    ("tradability", "annual_turnover"),
    ("tradability", "liquidity_flags"),
    ("tradability", "gross_return"),
    ("tradability", "net_return"),
    ("tradability", "benchmark_return"),
    ("tradability", "scenario_verdict"),
    ("tradability", "turnover_failure_reasons"),
    ("tradability", "liquidity_failure_reasons"),
    ("tradability", "net_vs_gross_failure_reasons"),
    ("tradability", "summary"),
]

# ============== Auto-Dispatch Allowlist (P0-3 Batch 10: Low-Risk Continuation) ==============

# 默认允许的 continuation modes（窄白名单，仅适用于最安全的 handoff）
DEFAULT_AUTO_DISPATCH_ALLOWED_CONTINUATION_MODES = {
    "advance_phase_handoff",
}

# 低风险 continuation allowlist（P0-3 Batch 10 新增）
# 这些 continuation 可以由 runtime 自动推进，无需主会话手工续批
# 注意：这不代表"完全无人工 gate"，而是"gate 保留，但低风险修复判断与续推由 runtime 自动做"
LOW_RISK_CONTINUATION_ALLOWLIST = {
    # Preheat 系列：预热/预验证任务
    "preheat100",
    "preheat250", 
    "preheat500",
    # Synthetic cleanup：数据清理/整理
    "synthetic_cleanup",
    # Rerun validation：重跑验证
    "artifact_rerun",
    "rerun_validation",
    # Selector fullrun：选择器全量运行
    "selector_fullrun",
    # Runtime closeout：运行时闭环
    "runtime_closeout",
    # Advance phase handoff：阶段移交（原有）
    "advance_phase_handoff",
}

# 高风险动作（必须保留人工 gate，不能 auto-dispatch）
HIGH_RISK_ACTIONS = {
    "push_merge",        # push/merge 代码
    "production_alert",  # 生产告警正式上线
    "live_trading",      # 实盘/交易执行
    "packet_freeze",     # 真值不完整的放行
    "gate_review",       # gate 审议（需要人工判断）
}

# 文档路径
PHASE1_INPUT_DOC = "docs/plans/2026-03-20-trading-roundtable-phase1-input.md"
CLOSURE_TEMPLATE_DOC = "docs/plans/2026-03-20-trading-roundtable-closure-template.md"
FOLLOWUP_VERDICT_DOC = "docs/plans/2026-03-20-trading-roundtable-followup-verdict.md"
FOLLOWUP_CHECKLIST_DOC = "docs/plans/2026-03-20-trading-roundtable-phase1-followup-checklist.md"
PACKET_REQUIRED_FIELDS_DOC = "docs/architecture/trading-phase1-packet-required-fields-2026-03.md"
PHASE_MAP_DOC = "docs/architecture/trading-phase1-orchestration-phase-map-2026-03.md"


class TradingAdapter(BaseAdapter):
    """
    交易适配器
    
    实现 trading roundtable 特定逻辑。
    """
    
    def _define_metadata(self) -> AdapterMetadata:
        return AdapterMetadata(
            name=ADAPTER_NAME,
            version=TRADING_ADAPTER_VERSION,
            description="Trading roundtable adapter for phase 1 orchestration",
            scenario=SCENARIO,
            packet_required_fields=TOP_LEVEL_PACKET_REQUIRED_FIELDS,
            roundtable_required_fields=ROUNDTABLE_REQUIRED_FIELDS,
            artifact_required_fields=ARTIFACT_REQUIRED_FIELDS,
            tradability_required_fields=TRADABILITY_REQUIRED_FIELDS,
            default_auto_dispatch_allowed_modes=DEFAULT_AUTO_DISPATCH_ALLOWED_CONTINUATION_MODES,
        )
    
    def validate_packet(
        self,
        packet: Dict[str, Any],
        roundtable: Dict[str, Any],
    ) -> Dict[str, Any]:
        """验证 trading packet 完整性"""
        missing_packet_fields = self._missing_top_level_fields(
            packet,
            TOP_LEVEL_PACKET_REQUIRED_FIELDS,
        )
        missing_roundtable_fields = self._missing_top_level_fields(
            roundtable,
            ROUNDTABLE_REQUIRED_FIELDS,
        )
        missing_artifact_fields = self._missing_nested_fields(
            packet,
            ARTIFACT_REQUIRED_FIELDS,
        )
        missing_tradability_fields = self._missing_nested_fields(
            packet,
            TRADABILITY_REQUIRED_FIELDS,
        )
        
        # 检查版本
        version_ok = packet.get("packet_version") in (None, PACKET_VERSION)
        phase_ok = packet.get("phase_id") in (None, PHASE_ID)
        
        all_missing = [
            *missing_packet_fields,
            *missing_roundtable_fields,
            *missing_artifact_fields,
            *missing_tradability_fields,
        ]
        
        if not version_ok:
            all_missing.append(f"packet_version!=${PACKET_VERSION}")
        if not phase_ok:
            all_missing.append(f"phase_id!=${PHASE_ID}")
        
        return {
            "complete": len(all_missing) == 0,
            "missing_fields": all_missing,
            "missing_packet_fields": missing_packet_fields,
            "missing_roundtable_fields": missing_roundtable_fields,
            "missing_artifact_fields": missing_artifact_fields,
            "missing_tradability_fields": missing_tradability_fields,
        }
    
    def validate_packet_preflight(
        self,
        packet: Dict[str, Any],
        roundtable: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        P0-1: Packet Schema 前置校验
        
        在 callback 处理的最早阶段进行 schema presence validation，
        显式标记 incomplete 状态，避免等 closeout 才发现缺失。
        
        与 validate_packet() 的区别：
        - 前置校验只做最基础的字段存在性检查（top-level + roundtable）
        - 返回明确的 preflight_status: "pass" | "incomplete" | "missing_fields"
        - 用于在 decision 构建之前就标记问题
        
        Returns:
            {
                "preflight_status": "pass" | "incomplete",
                "complete": bool,
                "missing_fields": [...],
                "missing_packet_fields": [...],
                "missing_roundtable_fields": [...],
                "checked_at": "preflight",
            }
        """
        missing_packet_fields = self._missing_top_level_fields(
            packet,
            TOP_LEVEL_PACKET_REQUIRED_FIELDS,
        )
        missing_roundtable_fields = self._missing_top_level_fields(
            roundtable,
            ROUNDTABLE_REQUIRED_FIELDS,
        )
        
        all_missing = [
            *missing_packet_fields,
            *missing_roundtable_fields,
        ]
        
        is_complete = len(all_missing) == 0
        
        return {
            "preflight_status": "pass" if is_complete else "incomplete",
            "complete": is_complete,
            "missing_fields": all_missing,
            "missing_packet_fields": missing_packet_fields,
            "missing_roundtable_fields": missing_roundtable_fields,
            "checked_at": "preflight",
        }
    
    def build_summary(
        self,
        batch_id: str,
        analysis: Dict[str, Any],
        decision: Dict[str, Any],
    ) -> str:
        """构建 trading summary"""
        packet = decision.get("metadata", {}).get("packet", {})
        roundtable = decision.get("metadata", {}).get("roundtable", {})
        validation = decision.get("metadata", {}).get("packet_validation", {})
        tradability = packet.get("tradability", {}) if isinstance(packet.get("tradability"), dict) else {}
        continuation = decision.get("metadata", {}).get("continuation", {})
        readiness = decision.get("metadata", {}).get("default_auto_dispatch_readiness", {})
        dispatch_backend = decision.get("metadata", {}).get("dispatch_backend", "subagent")
        
        # 构建超时策略
        timeout_policy = self._build_timeout_policy(dispatch_backend)
        
        lines = [
            f"# Trading Roundtable Continuation Summary — {batch_id}",
            "",
            f"- Generated: {datetime.now().isoformat()}",
            f"- Adapter: {ADAPTER_NAME}",
            f"- Scenario: {SCENARIO}",
            f"- Batch Complete: {'yes' if analysis.get('is_complete') else 'no'}",
            f"- Success Rate: {analysis.get('success_rate', 0):.1%}",
            f"- Failed Tasks: {analysis.get('failed', 0)}",
            f"- Timeout Tasks: {analysis.get('timeout', 0)}",
            f"- Dispatch Backend: {dispatch_backend}",
            f"- timeout_total_seconds: {timeout_policy.get('timeout_total_seconds')}",
            f"- timeout_stall_seconds: {timeout_policy.get('timeout_stall_seconds')}",
            f"- stall_grace_seconds: {timeout_policy.get('stall_grace_seconds')}",
            f"- Decision: {decision.get('action', 'N/A')}",
            f"- Reason: {decision.get('reason', 'N/A')}",
            "",
            "## Roundtable Closure",
            "",
            f"- Conclusion: {roundtable.get('conclusion', 'N/A')}",
            f"- Blocker: {roundtable.get('blocker', 'N/A')}",
            f"- Owner: {roundtable.get('owner', 'N/A')}",
            f"- Next Step: {roundtable.get('next_step', 'N/A')}",
            f"- Completion Criteria: {roundtable.get('completion_criteria', 'N/A')}",
            "",
            "## Phase 1 Packet",
            "",
            f"- Packet Version: {packet.get('packet_version', 'N/A')}",
            f"- Phase ID: {packet.get('phase_id', 'N/A')}",
            f"- Candidate ID: {packet.get('candidate_id', 'N/A')}",
            f"- Run Label: {packet.get('run_label', 'N/A')}",
            f"- Overall Gate: {packet.get('overall_gate', 'N/A')}",
            f"- Primary Blocker: {packet.get('primary_blocker', 'N/A')}",
            f"- Packet Complete: {'yes' if validation.get('complete') else 'no'}",
            "",
            "## Tradability Snapshot",
            "",
            f"- annual_turnover: {tradability.get('annual_turnover', 'N/A')}",
            f"- scenario_verdict: {tradability.get('scenario_verdict', 'N/A')}",
            f"- turnover_failure_reasons: {tradability.get('turnover_failure_reasons', [])}",
            f"- liquidity_failure_reasons: {tradability.get('liquidity_failure_reasons', [])}",
            f"- net_vs_gross_failure_reasons: {tradability.get('net_vs_gross_failure_reasons', [])}",
            f"- summary: {tradability.get('summary', 'N/A')}",
            "",
            "## Continuation Plan",
            "",
            f"- Mode: {continuation.get('mode', 'N/A')}",
            f"- Task Preview: {continuation.get('task_preview', 'N/A')}",
            f"- Next-Round Goal: {continuation.get('next_round_goal', 'N/A')}",
            f"- Rationale: {continuation.get('rationale', 'N/A')}",
            f"- Review Required: {'yes' if continuation.get('review_required') else 'no'}",
            f"- Completion Criteria: {continuation.get('completion_criteria', 'N/A')}",
            "",
            "## Default Auto-Dispatch Readiness",
            "",
            f"- Eligible Now: {'yes' if readiness.get('eligible') else 'no'}",
            f"- Status: {readiness.get('status', 'N/A')}",
            f"- Blockers: {readiness.get('blockers', [])}",
            "",
            "## Runtime Bridge Inputs",
            "",
            f"- phase1_input_doc: {PHASE1_INPUT_DOC}",
            f"- closure_template_doc: {CLOSURE_TEMPLATE_DOC}",
            f"- followup_verdict_doc: {FOLLOWUP_VERDICT_DOC}",
            f"- followup_checklist_doc: {FOLLOWUP_CHECKLIST_DOC}",
            f"- packet_required_fields_doc: {PACKET_REQUIRED_FIELDS_DOC}",
            f"- phase_map_doc: {PHASE_MAP_DOC}",
            "",
            "## Business Terminal Contract",
            "",
            "- Business closeout source: canonical callback via scripts/orchestrator_callback_bridge.py complete",
            "- tmux STATUS / completion report role: diagnostic evidence only; not a roundtable business terminal",
        ]
        
        # 添加缺失字段
        missing_fields = validation.get("missing_fields") or []
        if missing_fields:
            lines.extend(["", "## Missing Fields", ""])
            for field in missing_fields:
                lines.append(f"- {field}")
        
        # 添加 required actions
        required_actions = continuation.get("required_actions") or []
        if required_actions:
            lines.extend(["", "## Next-Round Required Actions", ""])
            for item in required_actions:
                lines.append(f"- {item}")
        
        # 添加 readiness criteria
        readiness_criteria = readiness.get("criteria") or []
        if readiness_criteria:
            lines.extend(["", "## Default Auto-Dispatch Criteria", ""])
            for item in readiness_criteria:
                lines.append(
                    f"- {item.get('field')}: expected={item.get('expected')} "
                    f"actual={item.get('actual')} passed={'yes' if item.get('passed') else 'no'}"
                )
        
        # 添加 upgrade requirements
        upgrade_requirements = readiness.get("upgrade_requirements") or []
        if upgrade_requirements:
            lines.extend(["", "## Upgrade Requirements For Default Auto", ""])
            for item in upgrade_requirements:
                lines.append(f"- {item}")
        
        # 添加任务结果
        lines.extend(["", "## Task Results", ""])
        for item in decision.get("metadata", {}).get("supporting_results", []):
            closeout = item.get("closeout") if isinstance(item.get("closeout"), dict) else {}
            closeout_bits = []
            if closeout:
                closeout_bits.append(f"stopped_because={closeout.get('stopped_because') or 'N/A'}")
                closeout_bits.append(f"next_owner={closeout.get('next_owner') or 'N/A'}")
                closeout_bits.append(f"dispatch_readiness={closeout.get('dispatch_readiness') or 'N/A'}")
            suffix = f" closeout[{', '.join(closeout_bits)}]" if closeout_bits else ""
            lines.append(
                f"- {item.get('task_id')}: state={item.get('state')} "
                f"verdict={item.get('verdict')} error={item.get('error') or 'N/A'} "
                f"summary={item.get('summary') or 'N/A'}{suffix}"
            )
        
        return "\n".join(lines) + "\n"
    
    def build_continuation_plan(
        self,
        decision: Dict[str, Any],
        analysis: Dict[str, Any],
    ) -> Dict[str, Any]:
        """构建 trading continuation plan"""
        packet = decision.get("metadata", {}).get("packet", {})
        roundtable = decision.get("metadata", {}).get("roundtable", {})
        validation = decision.get("metadata", {}).get("packet_validation", {})
        blocker = str(roundtable.get("blocker") or packet.get("primary_blocker") or "unknown")
        next_step = str(roundtable.get("next_step") or "review the batch summary and continue the minimal next step")
        completion_criteria = str(
            roundtable.get("completion_criteria") or "produce the smallest verifiable continuation artifact"
        )
        
        timeout_count = int(analysis.get("timeout") or 0)
        failed_count = int(analysis.get("failed") or 0)
        missing_fields = validation.get("missing_fields") or []
        
        # Timeout/failed 任务 -> artifact_rerun
        if timeout_count or failed_count:
            affected = [
                item["task_id"]
                for item in decision.get("metadata", {}).get("supporting_results", [])
                if item.get("state") in {"timeout", "failed"}
            ]
            return {
                "mode": "artifact_rerun",
                "task_preview": "rerun timeout/failed artifacts, refresh packet truth paths, then re-open the gate review",
                "next_round_goal": "recover missing evidence from timeout/failed tasks before trusting the current trading verdict",
                "rationale": "batch contains timeout/failed tasks, so the next round must refresh evidence instead of pretending the packet is clean",
                "review_required": True,
                "required_actions": [
                    f"rerun affected tasks: {', '.join(affected) if affected else 'timeout/failed tasks in this batch'}",
                    "refresh artifact/report/test/repro truth paths in phase1 packet v1",
                    "only reopen roundtable gate review after rerun evidence is attached",
                ],
                "completion_criteria": completion_criteria,
            }
        
        # Missing fields -> packet_freeze
        if missing_fields:
            return {
                "mode": "packet_freeze",
                "task_preview": "freeze phase1 packet v1 by backfilling missing truth fields before any further continuation",
                "next_round_goal": "turn the current roundtable output into a complete phase1 packet v1 with all required truth fields",
                "rationale": "packet/closure is incomplete, so the next actionable hop is packet freeze instead of broader follow-up",
                "review_required": True,
                "required_actions": [
                    f"fill missing fields: {', '.join(missing_fields)}",
                    "persist artifact/report/commit/test/repro truth paths in the frozen packet",
                    "re-run gate review only after the packet is complete",
                ],
                "completion_criteria": completion_criteria,
            }
        
        # 推断 continuation mode
        inferred_mode = self._continuation_mode_from_next_step(next_step)
        
        # Decision action 处理
        if decision.get("action") == "proceed":
            return {
                "mode": inferred_mode,
                "task_preview": next_step,
                "next_round_goal": "freeze this passing gate and open exactly one minimal next-round trading continuation",
                "rationale": "roundtable gate passed, so the next hop should be a single minimal continuation with packet/gate truth carried forward",
                "review_required": inferred_mode != "advance_phase_handoff",
                "required_actions": [
                    "freeze the accepted packet/gate record before any wider follow-up",
                    "keep continuation scope to a single task with explicit artifact outputs",
                    "persist updated packet/report paths in the final answer",
                ],
                "completion_criteria": completion_criteria,
            }
        
        if blocker == "tradability":
            return {
                "mode": inferred_mode if inferred_mode != "advance_phase_handoff" else "packet_freeze",
                "task_preview": next_step,
                "next_round_goal": "freeze tradability evidence and prepare a focused re-review instead of opening a broader new phase",
                "rationale": "tradability is still the blocker, so the next round must collect/freeze blocker evidence before another gate decision",
                "review_required": True,
                "required_actions": [
                    "attach turnover/liquidity/net_vs_gross failure reasons to phase1 packet v1",
                    "if a rerun is requested, link the new artifact/report/verdict to the same packet",
                    "return with a narrow gate-review packet, not a wider architecture rewrite",
                ],
                "completion_criteria": completion_criteria,
            }
        
        # 默认：gate_review
        return {
            "mode": inferred_mode if inferred_mode != "advance_phase_handoff" else "gate_review",
            "task_preview": next_step,
            "next_round_goal": "resolve the single named blocker and return with a smaller, more reviewable packet",
            "rationale": "the roundtable did not fully pass, so continuation stays focused on blocker repair + re-review",
            "review_required": True,
            "required_actions": [
                f"resolve blocker: {blocker}",
                "keep the scope to one blocker-oriented follow-up",
                "persist updated packet/report/decision truth in the return artifact",
            ],
            "completion_criteria": completion_criteria,
        }
    
    def evaluate_auto_dispatch_readiness(
        self,
        decision: Dict[str, Any],
        analysis: Dict[str, Any],
        continuation: Dict[str, Any],
    ) -> Dict[str, Any]:
        """评估 auto-dispatch 就绪状态"""
        packet = decision.get("metadata", {}).get("packet", {})
        roundtable = decision.get("metadata", {}).get("roundtable", {})
        validation = decision.get("metadata", {}).get("packet_validation", {})
        tradability = packet.get("tradability", {}) if isinstance(packet.get("tradability"), dict) else {}
        
        timeout_count = int(analysis.get("timeout") or 0)
        failed_count = int(analysis.get("failed") or 0)
        artifact_issues = self._check_artifact_truth(packet)
        gate_issues = self._check_gate_consistency(packet, roundtable)
        
        # 构建检查 criteria
        criteria = [
            {
                "name": "roundtable_conclusion_pass",
                "field": "roundtable.conclusion",
                "expected": "PASS",
                "actual": str(roundtable.get("conclusion") or "").upper() or "N/A",
                "passed": str(roundtable.get("conclusion") or "").upper() == "PASS",
            },
            {
                "name": "roundtable_blocker_none",
                "field": "roundtable.blocker",
                "expected": "none",
                "actual": str(roundtable.get("blocker") or "").lower() or "N/A",
                "passed": str(roundtable.get("blocker") or "").lower() == "none",
            },
            {
                "name": "packet_overall_gate_pass",
                "field": "packet.overall_gate",
                "expected": "PASS",
                "actual": str(packet.get("overall_gate") or "").upper() or "N/A",
                "passed": str(packet.get("overall_gate") or "").upper() == "PASS",
            },
            {
                "name": "packet_primary_blocker_none",
                "field": "packet.primary_blocker",
                "expected": "none",
                "actual": str(packet.get("primary_blocker") or "").lower() or "N/A",
                "passed": str(packet.get("primary_blocker") or "").lower() == "none",
            },
            {
                "name": "tradability_scenario_verdict_pass",
                "field": "packet.tradability.scenario_verdict",
                "expected": "PASS",
                "actual": str(tradability.get("scenario_verdict") or "").upper() or "N/A",
                "passed": str(tradability.get("scenario_verdict") or "").upper() == "PASS",
            },
            {
                "name": "batch_timeout_count_zero",
                "field": "batch.timeout",
                "expected": 0,
                "actual": timeout_count,
                "passed": timeout_count == 0,
            },
            {
                "name": "batch_failed_count_zero",
                "field": "batch.failed",
                "expected": 0,
                "actual": failed_count,
                "passed": failed_count == 0,
            },
            {
                "name": "truth_paths_complete",
                "field": "packet.artifact/report/test/repro truth paths",
                "expected": "complete + exists=true",
                "actual": "complete" if validation.get("complete") and not artifact_issues else "; ".join(
                    [
                        *([f"missing_fields={','.join(validation.get('missing_fields') or [])}"] if validation.get("missing_fields") else []),
                        *artifact_issues,
                    ]
                ) or "incomplete",
                "passed": bool(validation.get("complete")) and len(artifact_issues) == 0,
            },
            {
                "name": "continuation_mode_whitelisted",
                "field": "continuation.mode",
                "expected": "advance_phase_handoff",
                "actual": str(continuation.get("mode") or "N/A"),
                "passed": continuation.get("mode") in DEFAULT_AUTO_DISPATCH_ALLOWED_CONTINUATION_MODES,
            },
        ]
        
        # 收集 blockers
        blockers: List[str] = []
        upgrade_requirements: List[str] = []
        
        def add_blocker(code: str, requirement: str):
            if code not in blockers:
                blockers.append(code)
            if requirement not in upgrade_requirements:
                upgrade_requirements.append(requirement)
        
        # 检查各种条件
        if timeout_count > 0:
            add_blocker(
                "batch_has_timeout_tasks",
                "所有 timeout task 必须先 rerun 完并把新 artifact/report 真值回填到同一份 phase1 packet。",
            )
        if failed_count > 0:
            add_blocker(
                "batch_has_failed_tasks",
                "所有 failed task 必须先修复/重跑并回填证据，不能带着失败分支进入默认 auto。",
            )
        if not validation.get("complete"):
            add_blocker(
                "packet_incomplete",
                "phase1 packet v1 与 roundtable closure 5 字段必须完整，missing fields 归零。",
            )
        if artifact_issues:
            add_blocker(
                "artifact_truth_not_verified",
                "artifact/report/test/repro 真值必须完整且 exists=true，才能考虑默认 auto-dispatch。",
            )
        if gate_issues:
            add_blocker(
                "gate_truth_mismatch",
                "roundtable 结论与 packet overall_gate / primary_blocker / tradability verdict 必须一致。",
            )
        if decision.get("action") != "proceed":
            add_blocker(
                f"decision_{decision.get('action')}_requires_manual_gate",
                "只有 proceed 且 blocker=none 的 trading roundtable，才有资格讨论默认 auto-dispatch。",
            )
        if not criteria[0]["passed"]:
            add_blocker(
                "roundtable_not_pass",
                "默认 auto 仅适用于 PASS roundtable；CONDITIONAL/FAIL 仍保持人工 gate review。",
            )
        if not criteria[1]["passed"]:
            add_blocker(
                "roundtable_blocker_present",
                "roundtable blocker 必须为 none，且主 blocker 不再需要额外审议。",
            )
        if not criteria[2]["passed"]:
            add_blocker(
                "overall_gate_not_pass",
                "packet overall_gate 必须为 PASS，不能靠 roundtable 文案单独放行。",
            )
        if not criteria[3]["passed"]:
            add_blocker(
                "primary_blocker_present",
                "packet primary_blocker 必须为 none，不能把 blocker 带进默认 auto。",
            )
        if not criteria[4]["passed"]:
            add_blocker(
                "tradability_not_pass",
                "tradability.scenario_verdict 必须为 PASS；turnover/liquidity/net_vs_gross 不能残留硬失败。",
            )
        if not criteria[8]["passed"]:
            add_blocker(
                f"continuation_mode_{continuation.get('mode')}_not_whitelist_safe",
                "默认 auto 只适用于单步、低风险的 handoff；packet freeze / artifact rerun / gate review 仍需人工确认。",
            )
        
        eligible = len(blockers) == 0
        
        if eligible:
            upgrade_requirements = [
                "维持当前单步 continuation：freeze gate record -> open exactly one minimal next-round wiring task。",
                "继续限定为 subagent runtime + requester_session_key 存在 + 单轮不 fan-out。",
                "确认这条 continuation 不会触发真实交易执行，只是证据/编排层推进。",
            ]
        
        return {
            "eligible": eligible,
            "status": "eligible_for_default_whitelist" if eligible else "not_ready",
            "blockers": blockers,
            "upgrade_requirements": upgrade_requirements,
            "criteria": criteria,
            "gate_truth_issues": gate_issues,
            "artifact_truth_issues": artifact_issues,
        }
    
    def build_followup_prompt(
        self,
        batch_id: str,
        decision: Dict[str, Any],
        summary_path: Path,
    ) -> str:
        """构建 follow-up prompt"""
        roundtable = decision.get("metadata", {}).get("roundtable", {})
        packet = decision.get("metadata", {}).get("packet", {})
        continuation = decision.get("metadata", {}).get("continuation", {})
        next_step = continuation.get("task_preview") or roundtable.get(
            "next_step"
        ) or "review the batch summary and continue the minimal next step"
        completion_criteria = continuation.get("completion_criteria") or roundtable.get(
            "completion_criteria"
        ) or "produce the smallest verifiable continuation artifact"
        
        prompt_lines = [
            "# Trading Roundtable Follow-up",
            "",
            f"Adapter: {ADAPTER_NAME}",
            f"Scenario: {SCENARIO}",
            f"Batch ID: {batch_id}",
            f"Decision: {decision.get('action', 'N/A')}",
            f"Reason: {decision.get('reason', 'N/A')}",
            f"Summary: {summary_path}",
            "",
            "Read these docs first:",
            f"- {PHASE1_INPUT_DOC}",
            f"- {CLOSURE_TEMPLATE_DOC}",
            f"- {FOLLOWUP_VERDICT_DOC}",
            f"- {FOLLOWUP_CHECKLIST_DOC}",
            f"- {PACKET_REQUIRED_FIELDS_DOC}",
            f"- {PHASE_MAP_DOC}",
            "",
            f"Candidate ID: {packet.get('candidate_id', 'N/A')}",
            f"Run Label: {packet.get('run_label', 'N/A')}",
            f"Primary Blocker: {packet.get('primary_blocker', roundtable.get('blocker', 'N/A'))}",
            f"Continuation Mode: {continuation.get('mode', 'N/A')}",
            f"Next-Round Goal: {continuation.get('next_round_goal', 'N/A')}",
            f"Review Required: {'yes' if continuation.get('review_required') else 'no'}",
            "",
            f"Next Step: {next_step}",
            f"Completion Criteria: {completion_criteria}",
            "",
            "Required actions:",
        ]
        
        for item in continuation.get("required_actions") or []:
            prompt_lines.append(f"- {item}")
        
        prompt_lines.extend(
            [
                "",
                "Rules:",
                "- Do not widen scope beyond the single next step above.",
                "- Reuse existing trading mainline artifacts; do not rewrite the engine.",
                "- Persist any updated packet/verdict/report paths in the final answer.",
                "- If you need rerun evidence, attach it back to the same phase1 packet instead of opening a parallel packet lineage.",
                "",
                "## P0 强制：Callback 时必须填齐的 Phase1 Packet 字段",
                "",
                "以下字段在 callback 的 `adapter_scoped_payload.payload.packet` 中必须完整填充，不得留空或 TBD：",
                "",
                "### Top-Level Packet Fields (9 个)",
                "1. `packet_version`: 固定为 `trading_phase1_packet_v1`",
                "2. `phase_id`: 固定为 `trading_phase1`",
                "3. `candidate_id`: 实际候选标的 ID（如 AAPL）",
                "4. `run_label`: 实际运行标签（如 preheat500_20260327）",
                "5. `input_config_path`: 输入配置路径（如 `docs/plans/2026-03-20-trading-roundtable-phase1-input.md`）",
                "6. `generated_at`: ISO-8601 时间戳",
                "7. `owner`: 所有者（如 trading）",
                "8. `overall_gate`: PASS | CONDITIONAL | FAIL",
                "9. `primary_blocker`: none 或具体 blocker 描述",
                "",
                "### Artifact Truth Fields (10 个)",
                "10. `artifact.path`: 实际 artifact 文件路径",
                "11. `artifact.exists`: true | false",
                "12. `report.path`: 实际 report 文件路径",
                "13. `report.exists`: true | false",
                "14. `commit.repo`: 仓库名（如 workspace-trading）",
                "15. `commit.git_commit`: 实际 git commit hash",
                "16. `test.commands`: 测试命令数组",
                "17. `test.summary`: 测试结果摘要",
                "18. `repro.commands`: 复现命令数组",
                "19. `repro.notes`: 复现说明（**不得留空**）",
                "",
                "### Tradability Fields (10 个)",
                "20. `tradability.annual_turnover`: 年化换手率（数字）",
                "21. `tradability.liquidity_flags`: 流动性标志数组",
                "22. `tradability.gross_return`: 毛回报（数字）",
                "23. `tradability.net_return`: 净回报（数字）",
                "24. `tradability.benchmark_return`: 基准回报（数字）",
                "25. `tradability.scenario_verdict`: PASS | CONDITIONAL | FAIL",
                "26. `tradability.turnover_failure_reasons`: 换手失败原因数组",
                "27. `tradability.liquidity_failure_reasons`: 流动性失败原因数组",
                "28. `tradability.net_vs_gross_failure_reasons`: 净 vs 毛失败原因数组",
                "29. `tradability.summary`: tradability 摘要（**不得留空**）",
                "",
                "### Roundtable Closure Fields (5 个)",
                "30. `roundtable.conclusion`: PASS | CONDITIONAL | FAIL",
                "31. `roundtable.blocker`: none 或具体 blocker",
                "32. `roundtable.owner`: 所有者",
                "33. `roundtable.next_step`: 下一步动作",
                "34. `roundtable.completion_criteria`: 完成标准",
                "",
                "**验证**：callback 前请自检 `adapter.validate_packet(packet, roundtable)` 返回 `complete=True`。",
            ]
        )
        
        return "\n".join(prompt_lines)
    
    # ============== 辅助方法 ==============
    
    def _continuation_mode_from_next_step(self, next_step: str) -> str:
        """从 next_step 推断 continuation mode"""
        text = next_step.lower()
        if "rerun" in text or "re-run" in text:
            return "artifact_rerun"
        if "freeze" in text and "packet" in text:
            return "packet_freeze"
        if "review" in text or "gate" in text:
            return "gate_review"
        return "advance_phase_handoff"
    
    def _build_timeout_policy(self, backend: str) -> Dict[str, Any]:
        """构建超时策略"""
        if backend == "tmux":
            return {
                "backend": "tmux",
                "timeout_total_seconds": 3600,
                "timeout_stall_seconds": 600,
                "stall_grace_seconds": 60,
            }
        else:
            return {
                "backend": "subagent",
                "timeout_total_seconds": 3600,
                "timeout_stall_seconds": 600,
                "stall_grace_seconds": 60,
            }
