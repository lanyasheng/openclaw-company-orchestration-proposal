#!/usr/bin/env python3
"""
completion_validator_rules.py — Subtask Completion Validator Rules

规则定义：Through / Block / Gate 判定规则

这是 Subtask Completion Validator 的规则层，定义：
- Through 规则 (接受为有效完成)
- Block 规则 (拒绝为无效完成)
- Gate 规则 (需要人工审查)

设计文档：docs/plans/subtask-completion-validator-design-2026-03-25.md
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Tuple, Dict, Any

__all__ = [
    # Through 规则
    "has_explicit_completion_statement",
    "artifacts_exist",
    "has_test_pass_evidence",
    "has_git_commit_evidence",
    "has_structured_summary",
    "has_intermediate_keywords",
    # Block 规则
    "is_pure_directory_listing",
    "is_pure_code_snippet",
    "has_intermediate_state_keywords",
    "has_unhandled_error",
    # 主验证函数
    "validate_completion",
    # Post-enforce 调优
    "format_decision_reason",
    "generate_audit_summary",
    # 配置
    "VALIDATOR_CONFIG",
]

# ========== 配置 ==========

VALIDATOR_CONFIG: Dict[str, Any] = {
    "mode": "enforce",  # audit_only | enforce (P0 全切：2026-03-25)
    "whitelist_labels": ["explore", "audit", "scan"],  # 收紧：减少 label，移除过宽的 list/check
    "whitelist_match_mode": "prefix",  # prefix | exact (prefix: label 以 whitelist 开头)
    "whitelist_min_checks": ["B4", "B6"],  # 白名单任务也要检查：B4(未处理错误), B6(空输出)
    "through_threshold": 3,  # Through 分数阈值
    "fallback_on_error": True,  # validator 错误时 fallback 到原逻辑
    "min_output_length": 100,  # 最小输出长度
}


# ========== Through 规则 ==========

THROUGH_KEYWORDS = {
    "完成": 2, "completed": 2, "done": 2, "finished": 2,
    "## 结论": 1, "## Summary": 1, "### Deliverables": 1,
}


def has_explicit_completion_statement(output: str) -> bool:
    """
    T1: 检查明确完成声明
    
    输出包含 "完成" / "completed" / "done" / "finished" 等关键词
    """
    for keyword in THROUGH_KEYWORDS.keys():
        if keyword.lower() in output.lower():
            return True
    return False


def artifacts_exist(artifacts: List[Path]) -> bool:
    """
    T2: 检查交付物存在
    
    输出提及的文件/路径真实存在 (通过 Path.exists() 验证)
    """
    if not artifacts:
        return False
    existing = sum(1 for p in artifacts if p.exists())
    return existing > 0


def has_test_pass_evidence(output: str) -> bool:
    """
    T3: 检查测试通过证据
    
    输出包含测试结果 (pytest/unittest pass / "X passed")
    """
    patterns = [
        r"\d+ passed",
        r"tests? passed",
        r"\bok\b",
        r"✓",
        r"全部通过",
        r"test.*passed",
        r"passed.*test",
    ]
    return any(re.search(p, output, re.IGNORECASE | re.MULTILINE) for p in patterns)


def has_git_commit_evidence(output: str) -> bool:
    """
    T4: 检查 git 提交证据
    
    输出包含 git commit hash / "committed"
    """
    patterns = [
        r"\[main [a-f0-9]{7}\]",
        r"committed:",
        r"git commit",
        r"[a-f0-9]{7,40}",  # git hash
    ]
    return any(re.search(p, output, re.IGNORECASE) for p in patterns)


def has_structured_summary(output: str) -> bool:
    """
    T5: 检查结构化总结
    
    输出包含 "## 结论" / "## Summary" / "### Deliverables" 等章节
    """
    patterns = [r"^##+\s+\w+", r"^###+\s+\w+"]
    return any(re.search(p, output, re.MULTILINE) for p in patterns)


def has_intermediate_keywords(output: str) -> bool:
    """
    T6 反向：检查中间状态关键词
    
    输出包含 "开始探索" / "starting" / "let me check" / "looking at" 等
    """
    keywords = ["开始探索", "starting", "let me", "looking at", "接下来", "next I will"]
    return any(kw.lower() in output.lower() for kw in keywords)


# ========== Block 规则 ==========


def is_pure_directory_listing(output: str) -> bool:
    """
    B1: 检查纯目录 listing
    
    输出仅包含目录列表 (ls/find 输出)，无实际交付物
    """
    lines = output.strip().split("\n")
    if len(lines) < 3:
        return False
    
    # 检查是否大部分行是文件/目录格式
    dir_pattern = r"^[-d][rwx-]{9}\s+\d+\s+\w+\s+\w+\s+\d+"
    dir_lines = sum(1 for line in lines if re.match(dir_pattern, line))
    
    # 也检查简单的文件名列表模式
    simple_file_pattern = r"^[\w\.\-_/]+\s*$"
    simple_file_lines = sum(1 for line in lines if re.match(simple_file_pattern, line))
    
    total_meaningful_lines = len([l for l in lines if l.strip()])
    if total_meaningful_lines == 0:
        return False
    
    dir_ratio = dir_lines / total_meaningful_lines if total_meaningful_lines > 0 else 0
    simple_ratio = simple_file_lines / total_meaningful_lines if total_meaningful_lines > 0 else 0
    
    # 如果大部分是目录格式或简单文件名，且没有完成声明
    return (dir_ratio > 0.8 or simple_ratio > 0.8) and not has_explicit_completion_statement(output)


def is_pure_code_snippet(output: str) -> bool:
    """
    B2: 检查纯代码片段
    
    输出仅包含代码片段，无执行结果/测试/总结
    """
    lines = output.strip().split("\n")
    if len(lines) < 3:
        return False
    
    # 检查是否大部分行是代码格式 (缩进、关键字)
    code_patterns = [
        r"^\s+(def |class |import |from |return |if |else |for |while )",
        r"^\s+[a-z_]+\(",
        r"^\s+return ",
        r"^\s+const |let |var ",
        r"^\s+function ",
        r"^\s+print\(",
        r"^def\s+",
        r"^class\s+",
        r"^import\s+",
        r"^from\s+",
    ]
    code_lines = sum(1 for line in lines if any(re.match(p, line) for p in code_patterns))
    
    total_meaningful_lines = len([l for l in lines if l.strip()])
    if total_meaningful_lines == 0:
        return False
    
    code_ratio = code_lines / total_meaningful_lines if total_meaningful_lines > 0 else 0
    
    # 如果大部分是代码，且没有完成声明
    return code_ratio > 0.5 and not has_explicit_completion_statement(output)


def has_intermediate_state_keywords(output: str) -> bool:
    """
    B3: 检查中间状态关键词
    
    输出包含 "^开始" / "^starting" / "接下来" / "next I will" / "let me" 等
    """
    keywords = ["^开始", "^starting", "接下来", "next i will", "让我先", "let me first", "let me"]
    return any(re.search(kw, output, re.IGNORECASE) for kw in keywords)


def has_unhandled_error(output: str) -> bool:
    """
    B4: 检查未处理错误
    
    输出包含错误堆栈 + 无 "已修复" / "resolved" 声明
    
    注意：需要避免误判 "X passed, 0 failed" 这种测试结果
    """
    # 更精确的错误模式 (避免误判测试结果)
    error_patterns = [
        r"Traceback \(most recent",  # Python traceback
        r"^\s*Error:\s*\S",  # Error: 开头 (不是 "0 failed")
        r"^\s*Exception:",  # Exception 开头
        r"^\s*失败",  # 失败开头
        r"Error:\s+[A-Z]",  # Error: 后跟大写字母 (错误类型)
        r"Exception:\s+[A-Z]",  # Exception: 后跟大写字母
    ]
    resolution_patterns = [r"已修复", r"resolved", r"fixed", r"handled", r"已解决", r"pass"]
    
    has_error = any(re.search(p, output, re.MULTILINE) for p in error_patterns)
    has_resolution = any(re.search(p, output, re.IGNORECASE) for p in resolution_patterns)
    
    return has_error and not has_resolution


# ========== 主验证函数 ==========


def _match_whitelist(label: str, whitelist_label: str, mode: str = "prefix") -> bool:
    """
    白名单匹配逻辑
    
    Args:
        label: 任务标签
        whitelist_label: 白名单 label
        mode: 匹配模式 ("prefix" | "exact")
    
    Returns:
        bool: 是否匹配
    """
    label_lower = label.lower()
    whitelist_lower = whitelist_label.lower()
    
    if mode == "exact":
        return label_lower == whitelist_lower
    else:  # prefix (默认)
        # 前缀匹配：label 以 whitelist 开头，且 whitelist 后面是连字符/下划线或 label 结束
        # 例如：whitelist="explore" 匹配 "explore-repo" / "explore_task" / "explore"
        # 但不匹配 "checklist" (check 后面是 l，不是连字符/下划线)
        if label_lower.startswith(whitelist_lower):
            # 如果 label 刚好等于 whitelist，匹配
            if len(label_lower) == len(whitelist_lower):
                return True
            # 如果 whitelist 后面是连字符/下划线，匹配
            next_char = label_lower[len(whitelist_lower)]
            if next_char in "-_":
                return True
            # 否则不匹配 (如 "checklist" 中 "check" 后面是 "l")
            return False
        
        # 也允许 whitelist 在 label 中间，但必须前面和后面都是连字符/下划线
        # 例如：whitelist="audit" 匹配 "code-audit-task"
        idx = label_lower.find(whitelist_lower)
        if idx > 0 and idx + len(whitelist_lower) < len(label_lower):
            prev_char = label_lower[idx - 1]
            next_char = label_lower[idx + len(whitelist_lower)]
            if prev_char in "-_" and next_char in "-_":
                return True
        return False


def validate_completion(
    output: str,
    exit_code: int = 0,
    artifacts: List[Path] = None,
    label: str = "",
) -> Tuple[str, str, int, Dict[str, Any]]:
    """
    验证 completion
    
    Args:
        output: subagent 输出文本
        exit_code: 退出码
        artifacts: 交付物路径列表
        label: 任务标签 (用于白名单检查)
    
    Returns:
        (status, reason, score, metadata)
        status: "accepted" | "blocked" | "gate" | "error"
        reason: 规则 ID (如 "B1_pure_directory_listing")
        score: Through 分数
        metadata: 额外元数据 (包含详细规则命中情况)
    """
    if artifacts is None:
        artifacts = []
    
    try:
        # 检查白名单
        whitelist_matched = None
        match_mode = VALIDATOR_CONFIG.get("whitelist_match_mode", "prefix")
        whitelist_min_checks = VALIDATOR_CONFIG.get("whitelist_min_checks", [])
        
        if label:
            for whitelist_label in VALIDATOR_CONFIG.get("whitelist_labels", []):
                if _match_whitelist(label, whitelist_label, match_mode):
                    whitelist_matched = whitelist_label
                    break
        
        # 白名单任务：只进行基本质量检查 (B4 未处理错误，B6 空输出)
        if whitelist_matched:
            # B6: 空输出检查 (白名单也要满足)
            if len(output.strip()) < VALIDATOR_CONFIG.get("min_output_length", 100):
                return "blocked", "B6_empty_output", 0, {
                    "blocked": True,
                    "block_reason": "B6_empty_output",
                    "whitelisted": True,
                    "whitelist_label": whitelist_matched,
                    "whitelist_override": False,
                }
            
            # B4: 未处理错误检查 (白名单也要满足)
            if has_unhandled_error(output):
                return "blocked", "B4_unhandled_error", 0, {
                    "blocked": True,
                    "block_reason": "B4_unhandled_error",
                    "whitelisted": True,
                    "whitelist_label": whitelist_matched,
                    "whitelist_override": False,
                }
            
            # 通过白名单检查
            return "accepted", "whitelisted", 0, {
                "whitelisted": True,
                "whitelist_label": whitelist_matched,
                "whitelist_min_checks_passed": True,
            }
        
        # 先检查 Block 规则
        blocked = False
        block_reason = ""
        block_details = []
        
        if is_pure_directory_listing(output):
            blocked = True
            block_reason = "B1_pure_directory_listing"
            block_details.append("B1")
        
        if is_pure_code_snippet(output):
            blocked = True
            block_reason = "B2_pure_code_snippet" if not blocked else block_reason + "+B2"
            block_details.append("B2")
        
        if has_intermediate_state_keywords(output):
            blocked = True
            block_reason = "B3_intermediate_state" if not blocked else block_reason + "+B3"
            block_details.append("B3")
        
        if has_unhandled_error(output):
            blocked = True
            block_reason = "B4_unhandled_error" if not blocked else block_reason + "+B4"
            block_details.append("B4")
        
        if exit_code != 0:
            blocked = True
            block_reason = "B5_nonzero_exit" if not blocked else block_reason + "+B5"
            block_details.append("B5")
        
        if len(output.strip()) < VALIDATOR_CONFIG.get("min_output_length", 100):
            blocked = True
            block_reason = "B6_empty_output" if not blocked else block_reason + "+B6"
            block_details.append("B6")
        
        if blocked:
            # 有详细解释则降为 gate
            if len(output) > 500:
                return "gate", block_reason, 0, {
                    "blocked": True,
                    "block_reason": block_reason,
                    "block_details": block_details,
                    "downgraded_to_gate": True,
                    "gate_reason": "G2_blocked_with_explanation",
                }
            return "blocked", block_reason, 0, {
                "blocked": True,
                "block_reason": block_reason,
                "block_details": block_details,
            }
        
        # 计算 Through 分数
        score = 0
        through_details = []
        
        if has_explicit_completion_statement(output):
            score += 2
            through_details.append("T1")
        
        if artifacts_exist(artifacts):
            score += 2
            through_details.append("T2")
        
        if has_test_pass_evidence(output):
            score += 2
            through_details.append("T3")
        
        if has_git_commit_evidence(output):
            score += 1
            through_details.append("T4")
        
        if has_structured_summary(output):
            score += 1
            through_details.append("T5")
        
        if not has_intermediate_keywords(output):
            score += 1
            through_details.append("T6")
        
        threshold = VALIDATOR_CONFIG.get("through_threshold", 3)
        
        if score >= threshold:
            return "accepted", "", score, {
                "accepted": True,
                "through_score": score,
                "through_threshold": threshold,
                "through_details": through_details,
            }
        elif score == threshold - 1:  # 边界情况
            return "gate", "G1_boundary_case", score, {
                "gate": True,
                "gate_reason": "G1_boundary_case",
                "through_score": score,
                "through_threshold": threshold,
                "through_details": through_details,
            }
        else:
            return "blocked", "low_through_score", score, {
                "blocked": True,
                "block_reason": "low_through_score",
                "through_score": score,
                "through_threshold": threshold,
                "through_details": through_details,
            }
    
    except Exception as e:
        return "error", str(e), 0, {
            "error": True,
            "error_message": str(e),
        }


# ========== Post-Enforce 调优 (P0-6 Batch G) ==========

# Block 规则人类可读描述
BLOCK_RULE_DESCRIPTIONS: Dict[str, str] = {
    "B1_pure_directory_listing": "输出仅包含目录列表，无实际交付物",
    "B2_pure_code_snippet": "输出仅包含代码片段，无执行结果/测试/总结",
    "B3_intermediate_state": "输出包含中间状态关键词，任务未完成",
    "B4_unhandled_error": "输出包含未处理的错误堆栈",
    "B5_nonzero_exit": "任务退出码非零",
    "B6_empty_output": "输出过短或为空",
}

# Through 规则人类可读描述
THROUGH_RULE_DESCRIPTIONS: Dict[str, str] = {
    "T1": "包含明确完成声明",
    "T2": "交付物文件存在",
    "T3": "包含测试通过证据",
    "T4": "包含 git 提交证据",
    "T5": "包含结构化总结",
    "T6": "无中间状态关键词",
}

# Gate 规则人类可读描述
GATE_RULE_DESCRIPTIONS: Dict[str, str] = {
    "G1_boundary_case": "Through 分数处于边界，需要人工审查",
    "G2_blocked_with_explanation": "被 Block 规则命中但有详细解释，降级为 Gate",
}


def format_decision_reason(
    status: str,
    reason: str,
    metadata: Dict[str, Any],
) -> Dict[str, Any]:
    """
    格式化 decision reason，生成结构化输出
    
    Args:
        status: 验证状态 (accepted/blocked/gate/error)
        reason: 规则 ID 或原因
        metadata: 验证元数据
    
    Returns:
        结构化 decision reason 字典，包含：
        - status: 验证状态
        - reason_code: 规则 ID
        - reason_human: 人类可读描述
        - rule_details: 命中的规则详情
        - suggestions: 改进建议（如果适用）
    """
    # 确定规则类型和描述
    rule_type = "unknown"
    rule_description = "未知规则"
    
    if status == "accepted":
        rule_type = "through"
        if reason == "whitelisted":
            rule_description = "白名单任务，通过基本质量检查"
        else:
            rule_description = "Through 分数达到阈值"
    elif status == "blocked":
        rule_type = "block"
        rule_description = BLOCK_RULE_DESCRIPTIONS.get(reason, reason)
    elif status == "gate":
        rule_type = "gate"
        rule_description = GATE_RULE_DESCRIPTIONS.get(reason, reason)
    elif status == "error":
        rule_type = "error"
        rule_description = f"Validator 内部错误：{reason}"
    
    # 提取规则详情
    rule_details = []
    
    # Block 规则详情
    if "block_details" in metadata:
        for rule_id in metadata["block_details"]:
            rule_details.append({
                "rule_id": rule_id,
                "description": BLOCK_RULE_DESCRIPTIONS.get(rule_id, rule_id),
                "type": "block",
            })
    
    # Through 规则详情
    if "through_details" in metadata:
        for rule_id in metadata["through_details"]:
            rule_details.append({
                "rule_id": rule_id,
                "description": THROUGH_RULE_DESCRIPTIONS.get(rule_id, rule_id),
                "type": "through",
            })
    
    # 生成改进建议
    suggestions = []
    
    if status == "blocked":
        if "B1" in metadata.get("block_details", []):
            suggestions.append("添加实际交付物说明，而非仅列出目录")
        if "B2" in metadata.get("block_details", []):
            suggestions.append("添加代码执行结果、测试输出或总结")
        if "B3" in metadata.get("block_details", []):
            suggestions.append("完成任务后再提交，避免中间状态")
        if "B4" in metadata.get("block_details", []):
            suggestions.append("处理错误后再提交，或明确说明错误原因")
        if "B5" in metadata.get("block_details", []):
            suggestions.append("修复错误确保退出码为 0")
        if "B6" in metadata.get("block_details", []):
            suggestions.append("提供更详细的输出（至少 100 字符）")
        if reason == "low_through_score":
            suggestions.append("添加完成声明、测试证据、git 提交等交付物")
    
    if status == "gate":
        suggestions.append("请人工审查任务完成情况")
    
    return {
        "status": status,
        "reason_code": reason,
        "reason_human": rule_description,
        "rule_type": rule_type,
        "rule_details": rule_details,
        "suggestions": suggestions,
        "metadata_summary": {
            "score": metadata.get("through_score", metadata.get("score", 0)),
            "threshold": metadata.get("through_threshold", 3),
            "whitelisted": metadata.get("whitelisted", False),
            "blocked": metadata.get("blocked", False),
            "gate": metadata.get("gate", False),
        },
    }


def generate_audit_summary(
    audits: List[Dict[str, Any]],
    group_by: str = "status",
) -> Dict[str, Any]:
    """
    生成审计样本汇总
    
    Args:
        audits: 审计记录列表（来自 load_validation_audit 或 list_validation_audits）
        group_by: 分组维度 (status / label / reason / date)
    
    Returns:
        汇总字典，包含：
        - total: 总样本数
        - by_group: 按分组维度的统计
        - blocked_rate: 拦截率
        - gate_rate: Gate 率
        - common_block_reasons: 常见 Block 原因
        - common_gate_reasons: 常见 Gate 原因
        - samples: 样本摘要（每个分组最多 5 个）
    """
    if not audits:
        return {
            "total": 0,
            "by_group": {},
            "blocked_rate": 0.0,
            "gate_rate": 0.0,
            "common_block_reasons": [],
            "common_gate_reasons": [],
            "samples": {},
        }
    
    total = len(audits)
    
    # 按维度分组
    by_group: Dict[str, List[Dict[str, Any]]] = {}
    for audit in audits:
        if group_by == "status":
            key = audit.get("status", "unknown")
        elif group_by == "label":
            key = audit.get("label", "unknown")
        elif group_by == "reason":
            key = audit.get("reason", "unknown")
        elif group_by == "date":
            # 按日期分组（ISO 日期部分）
            timestamp = audit.get("timestamp", "")
            key = timestamp.split("T")[0] if timestamp else "unknown"
        else:
            key = "unknown"
        
        if key not in by_group:
            by_group[key] = []
        by_group[key].append(audit)
    
    # 统计
    blocked_count = sum(1 for a in audits if a.get("status") == "blocked_completion")
    gate_count = sum(1 for a in audits if a.get("status") == "gate_required")
    
    blocked_rate = blocked_count / total if total > 0 else 0.0
    gate_rate = gate_count / total if total > 0 else 0.0
    
    # 常见 Block 原因
    block_reasons: Dict[str, int] = {}
    for audit in audits:
        if audit.get("status") == "blocked_completion":
            reason = audit.get("reason", "unknown")
            block_reasons[reason] = block_reasons.get(reason, 0) + 1
    
    common_block_reasons = sorted(
        [{"reason": k, "count": v} for k, v in block_reasons.items()],
        key=lambda x: x["count"],
        reverse=True,
    )[:10]
    
    # 常见 Gate 原因
    gate_reasons: Dict[str, int] = {}
    for audit in audits:
        if audit.get("status") == "gate_required":
            reason = audit.get("reason", "unknown")
            gate_reasons[reason] = gate_reasons.get(reason, 0) + 1
    
    common_gate_reasons = sorted(
        [{"reason": k, "count": v} for k, v in gate_reasons.items()],
        key=lambda x: x["count"],
        reverse=True,
    )[:10]
    
    # 样本摘要（每个分组最多 5 个）
    samples: Dict[str, List[Dict[str, Any]]] = {}
    for key, group_audits in by_group.items():
        samples[key] = [
            {
                "audit_id": a.get("audit_id", ""),
                "status": a.get("status", ""),
                "reason": a.get("reason", ""),
                "label": a.get("label", ""),
                "timestamp": a.get("timestamp", ""),
            }
            for a in group_audits[:5]
        ]
    
    return {
        "total": total,
        "by_group": {k: len(v) for k, v in by_group.items()},
        "blocked_rate": blocked_rate,
        "gate_rate": gate_rate,
        "common_block_reasons": common_block_reasons,
        "common_gate_reasons": common_gate_reasons,
        "samples": samples,
    }


# ========== End Post-Enforce 调优 ==========
