#!/usr/bin/env python3
"""
backend_selector.py — 智能执行后端选择器

根据任务特征自动推荐最佳执行后端 (tmux / subagent)。

P0-3 Batch 4 (2026-03-28): 基于任务特征的智能 backend 推荐
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Literal


BackendType = Literal["subagent", "tmux", "manual"]


@dataclass
class BackendRecommendation:
    """Backend 推荐结果"""
    backend: BackendType
    confidence: float  # 0.0-1.0
    reason: str
    factors: Dict[str, Any]


class BackendSelector:
    """
    智能后端选择器
    
    决策因素：
    1. 预计任务时长
    2. 是否需要监控中间过程
    3. 任务类型（编码/文档/研究）
    4. 历史执行记录
    5. 用户偏好
    """
    
    # 阈值配置
    SHORT_TASK_THRESHOLD_MINUTES = 30
    MONITORING_KEYWORDS = [
        "监控", "观察", "看过程", "watch", "monitor", "track",
        "调试", "debug", "中间状态", "intermediate",
        "容易卡住", "可能失败", "risky", "unstable"
    ]
    CODING_KEYWORDS = [
        "编码", "实现", "重构", "code", "implement", "refactor",
        "fix", "bug", "feature", "开发", "develop"
    ]
    DOCUMENTATION_KEYWORDS = [
        "文档", "文档化", "document", "write doc", "README",
        "注释", "comment", "说明"
    ]
    
    def recommend(
        self,
        task_description: str,
        estimated_duration_minutes: int | None = None,
        task_type: str | None = None,
        requires_monitoring: bool | None = None,
        user_preference: BackendType | None = None,
        metadata: Dict[str, Any] | None = None,
    ) -> BackendRecommendation:
        """
        根据任务特征推荐最佳 backend
        
        Args:
            task_description: 任务描述
            estimated_duration_minutes: 预计时长（分钟）
            task_type: 任务类型 ("coding" / "documentation" / "research" / "custom")
            requires_monitoring: 是否需要监控中间过程
            user_preference: 用户偏好（优先级最高）
            metadata: 额外元数据
        
        Returns:
            BackendRecommendation
        """
        # 用户偏好优先级最高
        if user_preference:
            return BackendRecommendation(
                backend=user_preference,
                confidence=1.0,
                reason="用户明确指定",
                factors={"user_preference": user_preference}
            )
        
        # 收集决策因素
        factors: Dict[str, Any] = {}
        score_tmux = 0.0
        score_subagent = 0.5  # subagent 默认基础分
        
        # 因素 1: 预计时长
        if estimated_duration_minutes is not None:
            factors["estimated_duration"] = estimated_duration_minutes
            if estimated_duration_minutes > self.SHORT_TASK_THRESHOLD_MINUTES:
                score_tmux += 0.4
                factors["duration_factor"] = "long_task"
            else:
                score_subagent += 0.2
                factors["duration_factor"] = "short_task"
        
        # 因素 2: 明确需要监控
        if requires_monitoring:
            score_tmux += 0.4
            factors["monitoring_required"] = True
        
        # 因素 3: 任务描述关键词分析
        if task_description:
            task_lower = task_description.lower()
            
            # 监控相关关键词
            monitoring_matches = sum(1 for kw in self.MONITORING_KEYWORDS if kw.lower() in task_lower)
            if monitoring_matches > 0:
                score_tmux += 0.3 * min(monitoring_matches / 2, 1.0)
                factors["monitoring_keywords"] = monitoring_matches
            
            # 编码任务关键词
            coding_matches = sum(1 for kw in self.CODING_KEYWORDS if kw.lower() in task_lower)
            if coding_matches > 0:
                score_tmux += 0.2 * min(coding_matches / 2, 1.0)
                factors["coding_keywords"] = coding_matches
            
            # 文档任务关键词
            doc_matches = sum(1 for kw in self.DOCUMENTATION_KEYWORDS if kw.lower() in task_lower)
            if doc_matches > 0:
                score_subagent += 0.2 * min(doc_matches / 2, 1.0)
                factors["documentation_keywords"] = doc_matches
        
        # 因素 4: 任务类型
        if task_type:
            factors["task_type"] = task_type
            if task_type in ("coding", "refactoring", "debugging"):
                score_tmux += 0.15
            elif task_type in ("documentation", "simple_query"):
                score_subagent += 0.15
        
        # 决策
        if score_tmux > score_subagent:
            confidence = min((score_tmux - score_subagent) / 0.5 + 0.5, 1.0)
            return BackendRecommendation(
                backend="tmux",
                confidence=confidence,
                reason=self._generate_reason("tmux", factors),
                factors=factors
            )
        else:
            confidence = min((score_subagent - score_tmux) / 0.5 + 0.5, 1.0)
            return BackendRecommendation(
                backend="subagent",
                confidence=confidence,
                reason=self._generate_reason("subagent", factors),
                factors=factors
            )
    
    def _generate_reason(self, backend: BackendType, factors: Dict[str, Any]) -> str:
        """生成推荐理由"""
        reasons = []
        
        if backend == "tmux":
            if factors.get("estimated_duration", 0) > 30:
                reasons.append("长任务 (>30min)")
            if factors.get("monitoring_required"):
                reasons.append("需要监控中间过程")
            if factors.get("coding_keywords", 0) > 0:
                reasons.append("编码任务")
            if factors.get("monitoring_keywords", 0) > 0:
                reasons.append("包含监控相关关键词")
        else:
            if factors.get("estimated_duration", 0) <= 30:
                reasons.append("短任务 (<30min)")
            if factors.get("documentation_keywords", 0) > 0:
                reasons.append("文档任务")
        
        if not reasons:
            return f"基于任务特征推荐 {backend}"
        
        return f"推荐 {backend}：{', '.join(reasons)}"


# 便捷函数
def recommend_backend(
    task_description: str,
    estimated_duration_minutes: int | None = None,
    task_type: str | None = None,
    requires_monitoring: bool | None = None,
    user_preference: BackendType | None = None,
) -> BackendRecommendation:
    """
    快速推荐 backend
    
    Example:
        >>> rec = recommend_backend("重构认证模块，预计 1 小时")
        >>> print(f"推荐：{rec.backend}, 理由：{rec.reason}")
    """
    selector = BackendSelector()
    return selector.recommend(
        task_description=task_description,
        estimated_duration_minutes=estimated_duration_minutes,
        task_type=task_type,
        requires_monitoring=requires_monitoring,
        user_preference=user_preference,
    )


if __name__ == "__main__":
    # 演示
    import json
    
    test_cases = [
        {
            "task": "重构认证模块，预计 1 小时",
            "estimated_duration_minutes": 60,
        },
        {
            "task": "写一个 README 文档",
            "estimated_duration_minutes": 15,
        },
        {
            "task": "调试一个偶发的 bug，可能需要监控",
            "requires_monitoring": True,
        },
        {
            "task": "简单的数据查询",
            "estimated_duration_minutes": 5,
        },
        {
            "task": "实现一个新功能，需要看过程",
            "estimated_duration_minutes": 45,
        },
    ]
    
    print("=== Backend 推荐演示 ===\n")
    for case in test_cases:
        rec = recommend_backend(case["task"], **{k: v for k, v in case.items() if k != "task"})
        print(f"任务：{case['task']}")
        print(f"推荐：{rec.backend} (confidence={rec.confidence:.2f})")
        print(f"理由：{rec.reason}")
        print(f"因素：{json.dumps(rec.factors, indent=2, ensure_ascii=False)}")
        print()
