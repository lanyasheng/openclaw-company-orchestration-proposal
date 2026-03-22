from __future__ import annotations

from datetime import datetime
import shlex
from typing import Any, Dict, Optional

from continuation_backends import normalize_dispatch_backend

ENTRY_DEFAULTS_VERSION = "orchestration_entry_defaults_v1"

CONTEXT_CHANNEL_ROUNDTABLE = "channel_roundtable"
CONTEXT_TRADING_ROUNDTABLE = "trading_roundtable"
SUPPORTED_CONTEXTS = {
    CONTEXT_CHANNEL_ROUNDTABLE,
    CONTEXT_TRADING_ROUNDTABLE,
}

CURRENT_ARCHITECTURE_CHANNEL_ID = "discord:channel:1483883339701158102"
CURRENT_ARCHITECTURE_CHANNEL_NAME = "temporal-vs-langgraph-openclaw-company-architecture"
CURRENT_ARCHITECTURE_TOPIC = "Temporal vs LangGraph｜OpenClaw 公司级编排架构"
CURRENT_ARCHITECTURE_SCENARIO = "current_channel_architecture_roundtable"
CURRENT_ARCHITECTURE_OWNER = "main"
CURRENT_ARCHITECTURE_NEXT_STEP = "先在当前频道跑通 summary/decision/dispatch-plan，再回 trading 线补下一跳"
CURRENT_ARCHITECTURE_COMPLETION_CRITERIA = (
    "当前频道产出 summary/decision/dispatch-plan，且默认白名单模式下 dispatch plan 为 triggered；"
    "其他频道仍保持默认 skipped"
)
CURRENT_ARCHITECTURE_SUMMARY = (
    "当前频道结论已收口：不把 LangGraph 用作 OpenClaw 公司级编排底座；"
    "当前优先 OpenClaw native + thin orchestration。"
)
GENERIC_CHANNEL_NEXT_STEP = (
    "先回填当前 scenario 的 channel_roundtable/generic_roundtable 最小 closure 字段，"
    "再让 callback bridge 进入 summary / decision / dispatch。"
)
GENERIC_CHANNEL_COMPLETION_CRITERIA = (
    "提供 channel packet 最小字段（packet_version/scenario/channel_id/topic/owner/generated_at）"
    "与 roundtable 五字段（conclusion/blocker/owner/next_step/completion_criteria）；"
    "callback/ack/dispatch 继续复用现有 channel_roundtable 链路。"
)
GENERIC_CHANNEL_SUMMARY_TEMPLATE = (
    "Channel roundtable 默认 contract 已生成；scenario={scenario} 需回填最小 closure packet 后再进入 gate。"
)
CHANNEL_OPERATOR_KIT_ENTRY = "orchestrator/examples/generic_channel_roundtable_onboarding_kit.md"
CHANNEL_OPERATOR_KIT_CONTRACT_EXAMPLE = "orchestrator/examples/generic_non_trading_roundtable_contract.json"
CHANNEL_OPERATOR_KIT_CALLBACK_EXAMPLE = "orchestrator/examples/generic_non_trading_roundtable_callback.json"
ROUNDTABLE_CLOSURE_FIELDS = [
    "conclusion",
    "blocker",
    "owner",
    "next_step",
    "completion_criteria",
]
CHANNEL_MINIMAL_PACKET_FIELDS = [
    "packet_version",
    "scenario",
    "channel_id",
    "topic",
    "owner",
    "generated_at",
]
TRADING_MINIMAL_PACKET_FIELDS = [
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
TRADING_ARTIFACT_TRUTH_FIELDS = [
    "artifact.path",
    "artifact.exists",
    "report.path",
    "report.exists",
    "commit.repo",
    "commit.git_commit",
    "test.commands",
    "test.summary",
    "repro.commands",
    "repro.notes",
]
TRADING_TRADABILITY_FIELDS = [
    "tradability.annual_turnover",
    "tradability.liquidity_flags",
    "tradability.gross_return",
    "tradability.net_return",
    "tradability.benchmark_return",
    "tradability.scenario_verdict",
    "tradability.turnover_failure_reasons",
    "tradability.liquidity_failure_reasons",
    "tradability.net_vs_gross_failure_reasons",
    "tradability.summary",
]

TRADING_SCENARIO = "trading_roundtable_phase1"
TRADING_PHASE_ID = "trading_phase1"
TRADING_OWNER = "trading"
TRADING_CHANNEL_ID = "discord:channel:trading-roundtable"
TRADING_CHANNEL_NAME = "trading-roundtable"
TRADING_TOPIC = "Trading Roundtable｜Phase 1 continuation"
TRADING_NEXT_STEP = (
    "按 phase1 packet + roundtable 5 字段自动注册/派发/回流/续推，直到 business gate 或 human gate 正常拦下"
)
TRADING_COMPLETION_CRITERIA = (
    "生成 summary / decision / dispatch-plan；clean PASS 可继续，CONDITIONAL/FAIL 停在 gate_review / packet_freeze / artifact_rerun"
)

DEFAULT_GATE_POLICY = {
    "mode": "stop_on_gate",
    "human_gate": "stop",
    "business_gate": "stop",
    "runtime_gate": "stop",
    "notes": [
        "auto_execute=true 表示自动注册 / 自动派发 / 自动回流 / 自动续推。",
        "一旦命中 human gate / business gate / runtime safety gate，就正常停住，不绕过 gate。",
    ],
}


def _iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _clean_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _slugify(value: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in value.lower()).strip("_") or "orchestration"


def _normalized_channel_tail(value: Optional[str]) -> str:
    raw = _clean_str(value)
    if not raw:
        return ""
    return raw.split(":")[-1]


def _explicit_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if not text:
        return None
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"unsupported boolean value: {value}")


def _shell_quote(value: str) -> str:
    return shlex.quote(str(value))


def _build_bootstrap_capability_card(*, adapter: str, scenario: str, is_trading: bool) -> Dict[str, Any]:
    """
    极短 operator-facing bootstrap card：让其他频道/agent 一眼知道如何接入。
    仅用于 discoverability，不改变 runtime 逻辑。
    """
    if is_trading:
        return {
            "adapter": "trading_roundtable",
            "scenario_hint": "trading_roundtable_phase1",
            "key_constraint": "trading 是 richer specialization；默认 auto-dispatch 仅对 clean PASS + truth 完整 + whitelist 命中放开",
            "next_step": "按 phase1 packet + roundtable 5 字段自动注册/派发/回流/续推",
        }

    return {
        "adapter": "channel_roundtable",
        "scenario_hint": "generic_roundtable (payload alias, not new adapter)",
        "key_constraint": "非 trading 场景默认走 channel_roundtable adapter；不需要新 adapter",
        "first_run_recommendation": {"allow_auto_dispatch": False},
        "operator_kit_path": CHANNEL_OPERATOR_KIT_ENTRY,
        "example_contract": CHANNEL_OPERATOR_KIT_CONTRACT_EXAMPLE,
        "example_callback": CHANNEL_OPERATOR_KIT_CALLBACK_EXAMPLE,
    }


def _build_channel_operator_kit(*, scenario: str, owner: str, channel: Dict[str, str]) -> Dict[str, Any]:
    channel_id = channel.get("channel_id") or channel.get("id") or "discord:channel:<channel-id>"
    channel_name = channel.get("channel_name") or channel.get("name") or "<channel-name>"
    topic = channel.get("topic") or "<topic>"

    return {
        "entry_file": CHANNEL_OPERATOR_KIT_ENTRY,
        "example_contract_file": CHANNEL_OPERATOR_KIT_CONTRACT_EXAMPLE,
        "example_callback_file": CHANNEL_OPERATOR_KIT_CALLBACK_EXAMPLE,
        "checklist": [
            "adapter 固定用 channel_roundtable；generic_roundtable 只是 payload alias，不是新的 runtime adapter。",
            "先生成 contract，再用最小 callback payload 跑通 canonical callback/ack/dispatch artifacts。",
            "新 scenario 首次接入建议显式 --allow-auto-dispatch false；若要默认自动续跑，再单独补 allowlist/策略。",
            "packet 只补最小字段：packet_version/scenario/channel_id/topic/owner/generated_at。",
            "roundtable 只补五字段：conclusion/blocker/owner/next_step/completion_criteria。",
            "backend terminal receipt / completion report 只是诊断与证据，不能替代 canonical business callback PASS。",
        ],
        "example_commands": {
            "generate_contract": (
                "python3 ~/.openclaw/scripts/orch_command.py "
                f"--scenario {_shell_quote(scenario)} "
                f"--channel-id {_shell_quote(channel_id)} "
                f"--channel-name {_shell_quote(channel_name)} "
                f"--topic {_shell_quote(topic)} "
                f"--owner {_shell_quote(owner)} "
                "--backend subagent"
            ),
            "complete_subagent": (
                "python3 scripts/orchestrator_callback_bridge.py complete "
                "--task-id <task_id> "
                f"--batch-id <batch_id> --payload {CHANNEL_OPERATOR_KIT_CALLBACK_EXAMPLE} "
                "--runtime subagent --allow-auto-dispatch false "
                "--requester-session-key <agent:...>"
            ),
            "complete_tmux": (
                "python3 scripts/orchestrator_dispatch_bridge.py complete "
                "--dispatch <dispatch.json> --task-id <task_id> --tmux-status likely_done "
                "--report-json <completion-report.json> --report-md <completion-report.md> "
                "--allow-auto-dispatch false --requester-session-key <agent:...>"
            ),
        },
        "recommended_first_run": {
            "allow_auto_dispatch": False,
            "reason": "先证明 generic callback path/ack/dispatch artifacts 稳定，再决定是否为该 scenario 打开默认自动续跑。",
        },
    }


def _channel_descriptor(*, channel_id: str, channel_name: str, topic: str) -> Dict[str, str]:
    return {
        "id": channel_id,
        "channel_id": channel_id,
        "name": channel_name,
        "channel_name": channel_name,
        "topic": topic,
    }


def _is_current_architecture_channel_template(*, scenario: str, channel_id: str, topic: str, owner: str) -> bool:
    return (
        scenario == CURRENT_ARCHITECTURE_SCENARIO
        and _normalized_channel_tail(channel_id) == _normalized_channel_tail(CURRENT_ARCHITECTURE_CHANNEL_ID)
        and topic == CURRENT_ARCHITECTURE_TOPIC
        and owner == CURRENT_ARCHITECTURE_OWNER
    )


def _channel_onboarding_payload_aliases() -> list[str]:
    return ["channel_roundtable", "generic_roundtable"]


def _build_onboarding_seam(
    *,
    adapter: str,
    scenario: str,
    owner: str,
    callback_payload_schema: str,
    template_name: str,
    channel: Dict[str, str],
) -> Dict[str, Any]:
    is_trading = adapter == CONTEXT_TRADING_ROUNDTABLE

    if is_trading:
        result = {
            "adapter_capability": "trading_roundtable.phase1.v1",
            "seed_scope": "trading_roundtable",
            "payload_aliases": ["trading_roundtable"],
            "new_scenario_minimum": {
                "required_contract_fields": ["adapter", "scenario", "batch_key"],
                "derived_by_default": [
                    "owner",
                    "backend_preference",
                    "callback_payload_schema",
                    "auto_execute",
                    "gate_policy",
                ],
                "required_packet_fields": TRADING_MINIMAL_PACKET_FIELDS,
                "required_roundtable_fields": ROUNDTABLE_CLOSURE_FIELDS,
                "required_truth_fields": TRADING_ARTIFACT_TRUTH_FIELDS + TRADING_TRADABILITY_FIELDS,
            },
            "runtime_reuse": {
                "callback_bridge": "scripts/orchestrator_callback_bridge.py complete",
                "ack_guard": "orchestrator/completion_ack_guard.py",
                "dispatch_plan": "summary -> decision -> dispatch plan",
                "tmux_bridge": "scripts/orchestrator_dispatch_bridge.py complete",
            },
            "current_boundary": (
                "trading 仍是 richer specialization：默认 auto-dispatch 只对 clean PASS + truth 完整 + continuation whitelist 命中的 continuation 放开。"
            ),
            "owner": owner,
            "channel": channel,
            "callback_payload_schema": callback_payload_schema,
            "template_name": template_name,
            "scenario": scenario,
        }
    else:
        result = {
            "adapter_capability": "channel_roundtable.generic.v1",
            "seed_scope": "channel_roundtable",
            "payload_aliases": _channel_onboarding_payload_aliases(),
            "new_scenario_minimum": {
                "required_contract_fields": ["scenario"],
                "derived_by_default": [
                    "adapter=channel_roundtable",
                    "batch_key",
                    "owner",
                    "backend_preference",
                    "callback_payload_schema",
                    "auto_execute",
                    "gate_policy",
                    "channel/session metadata when ambient context exists",
                ],
                "required_packet_fields": CHANNEL_MINIMAL_PACKET_FIELDS,
                "required_roundtable_fields": ROUNDTABLE_CLOSURE_FIELDS,
            },
            "runtime_reuse": {
                "callback_bridge": "scripts/orchestrator_callback_bridge.py complete",
                "ack_guard": "orchestrator/completion_ack_guard.py",
                "dispatch_plan": "summary -> decision -> dispatch plan",
                "tmux_bridge": "scripts/orchestrator_dispatch_bridge.py complete",
            },
            "operator_kit": _build_channel_operator_kit(
                scenario=scenario,
                owner=owner,
                channel=channel,
            ),
            "current_boundary": (
                "新的非 trading scenario 现在可复用 channel_roundtable adapter 与 generic_roundtable payload alias；"
                "但默认 allowlist 仍只对白名单频道/明确显式 allow 放开。"
            ),
            "owner": owner,
            "channel": channel,
            "callback_payload_schema": callback_payload_schema,
            "template_name": template_name,
            "scenario": scenario,
        }

    # 添加 bootstrap capability card（仅用于 discoverability，不改变 runtime 逻辑）
    result["bootstrap_capability_card"] = _build_bootstrap_capability_card(
        adapter=adapter,
        scenario=scenario,
        is_trading=is_trading,
    )

    return result


def infer_entry_context(
    *,
    context: Optional[str] = None,
    scenario: Optional[str] = None,
    channel_id: Optional[str] = None,
    channel_name: Optional[str] = None,
    topic: Optional[str] = None,
) -> Dict[str, Any]:
    context_value = _clean_str(context)
    if context_value:
        normalized = context_value.lower()
        if normalized in {"trading", CONTEXT_TRADING_ROUNDTABLE, TRADING_SCENARIO}:
            return {
                "context": CONTEXT_TRADING_ROUNDTABLE,
                "source": "explicit_context",
                "matched_on": normalized,
            }
        if normalized in {"channel", CONTEXT_CHANNEL_ROUNDTABLE, CURRENT_ARCHITECTURE_SCENARIO}:
            return {
                "context": CONTEXT_CHANNEL_ROUNDTABLE,
                "source": "explicit_context",
                "matched_on": normalized,
            }
        raise ValueError(f"unsupported context: {context_value}")

    scenario_value = _clean_str(scenario)
    if scenario_value:
        if scenario_value == TRADING_SCENARIO or scenario_value.startswith("trading_"):
            return {
                "context": CONTEXT_TRADING_ROUNDTABLE,
                "source": "scenario",
                "matched_on": scenario_value,
            }
        return {
            "context": CONTEXT_CHANNEL_ROUNDTABLE,
            "source": "scenario",
            "matched_on": scenario_value,
        }

    channel_tail = _normalized_channel_tail(channel_id)
    if channel_tail and channel_tail == _normalized_channel_tail(CURRENT_ARCHITECTURE_CHANNEL_ID):
        return {
            "context": CONTEXT_CHANNEL_ROUNDTABLE,
            "source": "channel_id_whitelist",
            "matched_on": channel_id,
        }

    topic_value = _clean_str(topic) or ""
    channel_name_value = _clean_str(channel_name) or ""
    joined = f"{topic_value} {channel_name_value}".lower()
    if "trading roundtable" in joined or "trading-roundtable" in joined:
        return {
            "context": CONTEXT_TRADING_ROUNDTABLE,
            "source": "topic_or_channel_name",
            "matched_on": joined.strip(),
        }
    if "temporal" in joined or "langgraph" in joined or "openclaw 公司级编排架构" in joined:
        return {
            "context": CONTEXT_CHANNEL_ROUNDTABLE,
            "source": "topic_or_channel_name",
            "matched_on": joined.strip(),
        }

    return {
        "context": CONTEXT_CHANNEL_ROUNDTABLE,
        "source": "ambient_default_current_channel",
        "matched_on": CURRENT_ARCHITECTURE_CHANNEL_ID,
    }


def _default_batch_key(*, context: str, scenario: str, channel_id: Optional[str]) -> str:
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    if context == CONTEXT_TRADING_ROUNDTABLE:
        return f"batch_{_slugify(scenario)}_{ts}"
    channel_tail = _normalized_channel_tail(channel_id) or "current_channel"
    return f"batch_{_slugify(scenario)}_{_slugify(channel_tail)}_{ts}"


def _channel_seed_payload(
    *,
    scenario: str,
    channel_id: str,
    channel_name: str,
    topic: str,
    owner: str,
    template_mode: str,
) -> Dict[str, Any]:
    if template_mode == "channel_roundtable.current_channel_defaults":
        summary = CURRENT_ARCHITECTURE_SUMMARY
        conclusion = "PASS"
        blocker = "none"
        next_step = CURRENT_ARCHITECTURE_NEXT_STEP
        completion_criteria = CURRENT_ARCHITECTURE_COMPLETION_CRITERIA
        scoped_summary = (
            "结论：不把 LangGraph 用作 OpenClaw 公司级编排底座；当前优先 OpenClaw native + thin orchestration。"
        )
    else:
        summary = GENERIC_CHANNEL_SUMMARY_TEMPLATE.format(scenario=scenario)
        conclusion = "CONDITIONAL"
        blocker = "pending_roundtable"
        next_step = GENERIC_CHANNEL_NEXT_STEP
        completion_criteria = GENERIC_CHANNEL_COMPLETION_CRITERIA
        scoped_summary = summary

    return {
        "summary": summary,
        "channel_roundtable": {
            "packet": {
                "packet_version": "channel_roundtable_v1",
                "scenario": scenario,
                "channel_id": channel_id,
                "channel_name": channel_name,
                "topic": topic,
                "owner": owner,
                "generated_at": _iso_now(),
            },
            "roundtable": {
                "conclusion": conclusion,
                "blocker": blocker,
                "owner": owner,
                "next_step": next_step,
                "completion_criteria": completion_criteria,
            },
            "summary": scoped_summary,
        },
        "generic_roundtable": {
            "packet": {
                "packet_version": "channel_roundtable_v1",
                "scenario": scenario,
                "channel_id": channel_id,
                "channel_name": channel_name,
                "topic": topic,
                "owner": owner,
                "generated_at": _iso_now(),
            },
            "roundtable": {
                "conclusion": conclusion,
                "blocker": blocker,
                "owner": owner,
                "next_step": next_step,
                "completion_criteria": completion_criteria,
            },
            "summary": scoped_summary,
        },
    }


def _trading_seed_payload(*, owner: str) -> Dict[str, Any]:
    return {
        "summary": "Trading roundtable 默认 contract 已生成；运行时应自动执行到 gate，而不是绕过 gate。",
        "trading_roundtable": {
            "packet": {
                "packet_version": "trading_phase1_packet_v1",
                "phase_id": TRADING_PHASE_ID,
                "candidate_id": "pending_candidate",
                "run_label": "pending_run_label",
                "input_config_path": "docs/plans/2026-03-20-trading-roundtable-phase1-input.md",
                "generated_at": _iso_now(),
                "owner": owner,
                "overall_gate": "PENDING",
                "primary_blocker": "pending_roundtable",
                "artifact": {
                    "path": "TBD",
                    "exists": False,
                },
                "report": {
                    "path": "TBD",
                    "exists": False,
                },
                "commit": {
                    "repo": "workspace-trading",
                    "git_commit": "TBD",
                },
                "test": {
                    "commands": [],
                    "summary": "pending",
                },
                "repro": {
                    "commands": [],
                    "notes": "pending",
                },
                "tradability": {
                    "annual_turnover": 0,
                    "liquidity_flags": [],
                    "gross_return": 0,
                    "net_return": 0,
                    "benchmark_return": 0,
                    "scenario_verdict": "PENDING",
                    "turnover_failure_reasons": [],
                    "liquidity_failure_reasons": [],
                    "net_vs_gross_failure_reasons": [],
                    "summary": "pending packet truth",
                },
            },
            "roundtable": {
                "conclusion": "PENDING",
                "blocker": "pending_roundtable",
                "owner": owner,
                "next_step": TRADING_NEXT_STEP,
                "completion_criteria": TRADING_COMPLETION_CRITERIA,
            },
        },
    }


def build_default_entry_contract(
    *,
    context: Optional[str] = None,
    scenario: Optional[str] = None,
    channel_id: Optional[str] = None,
    channel_name: Optional[str] = None,
    topic: Optional[str] = None,
    owner: Optional[str] = None,
    backend: Optional[str] = None,
    requester_session_key: Optional[str] = None,
    batch_key: Optional[str] = None,
    auto_execute: Optional[bool] = True,
    command_name: str = "orch_start",
) -> Dict[str, Any]:
    inferred = infer_entry_context(
        context=context,
        scenario=scenario,
        channel_id=channel_id,
        channel_name=channel_name,
        topic=topic,
    )
    resolved_context = inferred["context"]
    normalized_backend = normalize_dispatch_backend(backend or "subagent")
    resolved_auto_execute = True if auto_execute is None else bool(auto_execute)

    if resolved_context == CONTEXT_TRADING_ROUNDTABLE:
        resolved_scenario = scenario or TRADING_SCENARIO
        resolved_owner = owner or TRADING_OWNER
        resolved_channel_id = channel_id or TRADING_CHANNEL_ID
        resolved_channel_name = channel_name or TRADING_CHANNEL_NAME
        resolved_topic = topic or TRADING_TOPIC
        seed_payload = _trading_seed_payload(owner=resolved_owner)
        callback_payload_schema = "trading_roundtable.v1.callback"
        template_name = "trading_roundtable.phase1_defaults"
    else:
        resolved_scenario = scenario or CURRENT_ARCHITECTURE_SCENARIO
        resolved_owner = owner or CURRENT_ARCHITECTURE_OWNER
        resolved_channel_id = channel_id or CURRENT_ARCHITECTURE_CHANNEL_ID
        resolved_channel_name = channel_name or CURRENT_ARCHITECTURE_CHANNEL_NAME
        resolved_topic = topic or CURRENT_ARCHITECTURE_TOPIC
        template_name = (
            "channel_roundtable.current_channel_defaults"
            if _is_current_architecture_channel_template(
                scenario=resolved_scenario,
                channel_id=resolved_channel_id,
                topic=resolved_topic,
                owner=resolved_owner,
            )
            else "channel_roundtable.generic_defaults"
        )
        seed_payload = _channel_seed_payload(
            scenario=resolved_scenario,
            channel_id=resolved_channel_id,
            channel_name=resolved_channel_name,
            topic=resolved_topic,
            owner=resolved_owner,
            template_mode=template_name,
        )
        callback_payload_schema = "channel_roundtable.v1.callback"

    resolved_batch_key = batch_key or _default_batch_key(
        context=resolved_context,
        scenario=resolved_scenario,
        channel_id=resolved_channel_id,
    )

    session = {}
    if requester_session_key:
        session["requester_session_key"] = requester_session_key

    channel = _channel_descriptor(
        channel_id=resolved_channel_id,
        channel_name=resolved_channel_name,
        topic=resolved_topic,
    )
    onboarding = _build_onboarding_seam(
        adapter=resolved_context,
        scenario=resolved_scenario,
        owner=resolved_owner,
        callback_payload_schema=callback_payload_schema,
        template_name=template_name,
        channel=channel,
    )

    orchestration = {
        "enabled": True,
        "adapter": resolved_context,
        "scenario": resolved_scenario,
        "batch_key": resolved_batch_key,
        "owner": resolved_owner,
        "backend_preference": normalized_backend,
        "callback_payload_schema": callback_payload_schema,
        "auto_execute": resolved_auto_execute,
        "auto_execute_scope": [
            "auto_register",
            "auto_dispatch",
            "auto_callback",
            "auto_continue_until_gate",
        ],
        "entrypoint": {
            "layer": "command",
            "name": command_name,
            "version": ENTRY_DEFAULTS_VERSION,
            "mode": "no_input_defaults" if context is None and scenario is None else "explicit_or_ambient",
        },
        "gate_policy": DEFAULT_GATE_POLICY,
        "channel": channel,
        "session": session,
        "metadata": {
            "default_source": inferred["source"],
            "matched_on": inferred["matched_on"],
            "template_name": template_name,
            "topic": resolved_topic,
            "entry_defaults_version": ENTRY_DEFAULTS_VERSION,
            "seed_scope": onboarding["seed_scope"],
            "payload_aliases": onboarding["payload_aliases"],
        },
    }

    return {
        "entry_context": {
            "resolved_context": resolved_context,
            "source": inferred["source"],
            "matched_on": inferred["matched_on"],
            "generated_at": _iso_now(),
        },
        "onboarding": onboarding,
        "orchestration": orchestration,
        "seed_payload": seed_payload,
    }
