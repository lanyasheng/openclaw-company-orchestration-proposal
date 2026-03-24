# Subtask Completion Validator 设计文档 (2026-03-25)

> **状态**: 设计锚定 (Design Anchor)  
> **作者**: Zoe (主会话)  
> **审查**: 待实现  
> **实现优先级**: P0 (高)  
> **风险等级**: 中 (涉及 completion 语义收紧，可能误杀)

---

## 执行摘要

### 问题陈述
当前系统存在 **completion 语义过松** 问题：子任务 run 结束 + 返回文本，就被当成 `completed successfully` 冒泡。反复出现以下现象被当成完成：
- 目录 listing 输出
- 代码片段输出
- "开始探索仓库结构"等中间状态

**根本原因**: terminal/completion 链路缺少质量门 validator，`terminal` 与 `done` 语义混淆。

### 设计目标
设计一个 **Subtask Completion Validator**，在 completion 冒泡到父层之前进行质量门检查，确保：
1. 只有真实交付物被标记为 `accepted_completion`
2. 中间状态/无效输出被标记为 `blocked_completion` 或 `invalid_completion`
3. 与现有 `completion_ack_guard` / `closeout_guarantee` / `subagent_announce` 清晰集成

### 范围与边界
- **范围**: completion validator 的规则定义、hook 点、输出状态、集成边界
- **不做什么 (v1)**:
  - 不重构现有 callback transport 层
  - 不改变 subagent 执行模型
  - 不替换 existing ack/closeout 机制
  - 不做语义理解/AI 判断 (基于规则)

### 风险与回退
- **主要风险**: 误杀合法 completion (过于严格的规则)
- **回退方案**: 
  - v1 默认 `mode=audit_only` (只记录不拦截)
  - 白名单机制 (trusted labels 跳过验证)
  - 可配置规则阈值
- **恢复路径**: 发现误杀 → 加白名单 → 调整规则 → 重新验证

---

## 1. 当前 Completion 链路图

### 1.1 Terminal vs Done 的区别 (当前问题)

```
┌─────────────────────────────────────────────────────────────────┐
│                    当前 Completion 链路 (有问题)                  │
└─────────────────────────────────────────────────────────────────┘

Subagent 执行
    │
    ├──→ subagent_ended 事件 (OpenClaw runtime)
    │       │
    │       ├──→ before_prompt_build hook (spawn-interceptor)
    │       │       │
    │       │       └──→ 只要 subagent 退出 + 有输出 → 标记为 completed
    │       │
    │       └──→ completion_receipt (completion_receipt.py)
    │               │
    │               └──→ 不检查输出质量 → 直接落盘
    │
    └──→ tmux terminal receipt (tmux_terminal_receipts.py)
            │
            └──→ 检查 tmux status (likely_done/done_session_ended)
                    │
                    └──→ 不检查 report 内容质量 → 直接落盘

问题：terminal state (进程结束) ≠ done (真实完成)
```

### 1.2 真实 Hook 点候选 (基于现有代码路径)

基于代码阅读，识别出以下 **真实可插入 validator 的 hook 点**:

| Hook 点 | 文件路径 | 函数/位置 | 说明 |
|--------|---------|----------|------|
| **H1: subagent_ended** | `spawn-interceptor` (OpenClaw runtime) | `onTaskCompleted` → `before_prompt_build` | 最早 hook 点，可拦截 completion 冒泡 |
| **H2: completion_receipt 创建** | `runtime/orchestrator/completion_receipt.py` | `CompletionReceiptKernel.create_receipt()` | 在 receipt artifact 生成前验证 |
| **H3: callback_router emit** | `runtime/orchestrator/core/callback_router.py` | `CallbackRouter.emit()` | 在回调事件触发前验证 |
| **H4: completion_ack_guard** | `runtime/orchestrator/completion_ack_guard.py` | `send_roundtable_completion_ack()` | 在 ack 发送前验证 |
| **H5: closeout_guarantee emit** | `runtime/orchestrator/closeout_guarantee.py` | `emit_closeout_guarantee()` | 在 guarantee 落盘前验证 |
| **H6: tmux receipt build** | `runtime/orchestrator/tmux_terminal_receipts.py` | `build_tmux_terminal_receipt()` | tmux backend 专用 hook |

**推荐 v1 集成点**: **H2** (completion_receipt 创建) + **H4** (ack guard)
- 理由：代码集中、影响面小、可 audit-only 渐进

---

## 2. Validator 设计

### 2.1 Through / Block / Gate 规则

#### 2.1.1 Through 规则 (接受为有效完成)

Completion 被标记为 `accepted_completion` 当且仅当满足以下 **至少 2 条**:

| 规则 ID | 规则名称 | 检查条件 | 权重 |
|--------|---------|---------|------|
| **T1** | 明确完成声明 | 输出包含 "完成" / "completed" / "done" / "finished" + 交付物路径 | 高 |
| **T2** | 交付物存在 | 输出提及的文件/路径真实存在 (通过 `Path.exists()` 验证) | 高 |
| **T3** | 测试通过证据 | 输出包含测试结果 (pytest/unittest pass / "X passed") | 高 |
| **T4** | Git 提交证据 | 输出包含 git commit hash / "committed" + `git status` 干净 | 中 |
| **T5** | 结构化总结 | 输出包含 "## 结论" / "## Summary" / "### Deliverables" 等章节 | 中 |
| **T6** | 无中间状态关键词 | 输出 **不** 包含 "开始探索" / "starting" / "let me check" / "looking at" | 中 |

**Through 判定**:
```python
def is_through(output: str, artifacts: List[Path]) -> bool:
    score = 0
    if has_explicit_completion_statement(output): score += 2  # T1
    if artifacts_exist(artifacts): score += 2                # T2
    if has_test_pass_evidence(output): score += 2            # T3
    if has_git_commit_evidence(output): score += 1           # T4
    if has_structured_summary(output): score += 1            # T5
    if not has_intermediate_keywords(output): score += 1     # T6
    
    return score >= 3  # 至少 3 分 (约 2 条高权重规则)
```

#### 2.1.2 Block 规则 (拒绝为无效完成)

Completion 被标记为 `blocked_completion` 当满足以下 **任一**:

| 规则 ID | 规则名称 | 检查条件 | 动作 |
|--------|---------|---------|------|
| **B1** | 纯目录 listing | 输出仅包含目录列表 (ls/find 输出)，无实际交付物 | block |
| **B2** | 纯代码片段 | 输出仅包含代码片段，无执行结果/测试/总结 | block |
| **B3** | 中间状态声明 | 输出包含 "开始" / "starting" / "接下来" / "next I will" | block |
| **B4** | 错误未处理 | 输出包含错误堆栈 + 无 "已修复" / "resolved" 声明 | block |
| **B5** | 超时退出 | subagent exit code != 0 且无错误处理声明 | block |
| **B6** | 空输出 | 输出长度 < 100 字符 或 无实质内容 | block |

**Block 判定**:
```python
def is_blocked(output: str, exit_code: int) -> tuple[bool, str]:
    if is_pure_directory_listing(output):
        return True, "B1_pure_directory_listing"
    if is_pure_code_snippet(output):
        return True, "B2_pure_code_snippet"
    if has_intermediate_state_keywords(output):
        return True, "B3_intermediate_state"
    if has_unhandled_error(output) and not has_resolution_statement(output):
        return True, "B4_unhandled_error"
    if exit_code != 0 and not has_error_handling(output):
        return True, "B5_timeout_exit"
    if len(output.strip()) < 100:
        return True, "B6_empty_output"
    return False, ""
```

#### 2.1.3 Gate 规则 (需要人工审查)

Completion 被标记为 `gate_required` 当：

| 规则 ID | 规则名称 | 检查条件 | 动作 |
|--------|---------|---------|------|
| **G1** | 边界情况 | Through 分数 = 2 (刚好不够 through) | gate |
| **G2** | Block 但有解释 | 命中 Block 规则，但输出包含详细解释 | gate |
| **G3** | 部分交付物缺失 | 提及的交付物部分存在、部分缺失 | gate |
| **G4** | 测试部分失败 | 测试结果混合 pass/fail | gate |

### 2.2 输出状态建议

```python
from typing import Literal

CompletionValidationStatus = Literal[
    # 有效完成 - 可冒泡到父层
    "accepted_completion",
    
    # 无效完成 - 拦截，不冒泡，记录审计
    "blocked_completion",
    
    # 需要人工审查 - 暂停，等待 gate 决策
    "gate_required",
    
    # 内部错误 - validator 自身失败，fallback 到原逻辑
    "validator_error",
]
```

**状态流转**:
```
subagent_ended
    │
    └──→ Validator 检查
            │
            ├──→ accepted_completion ──→ 正常 completion_receipt → ack → closeout
            │
            ├──→ blocked_completion ──→ 记录 audit log → 触发 fallback closeout
            │                             (不发送 ack，标记为 invalid)
            │
            ├──→ gate_required ──→ 记录 gate_request → 通知 operator
            │                        (暂停，等待人工审查)
            │
            └──→ validator_error ──→ fallback 到原逻辑 (不拦截)
                                      (记录 error，后续修复)
```

---

## 3. 与现有机制的集成边界

### 3.1 与 Success/Failure Closeout Guarantee 的关系

```
┌─────────────────────────────────────────────────────────────┐
│              Closeout Guarantee 与 Validator 集成             │
└─────────────────────────────────────────────────────────────┘

Completion Validation
    │
    ├──→ accepted_completion
    │       │
    │       └──→ emit_closeout_guarantee(
    │               ack_status="sent",
    │               user_visible_closeout=True,
    │               metadata={"validation_status": "accepted"}
    │           )
    │
    ├──→ blocked_completion
    │       │
    │       └──→ emit_closeout_guarantee(
    │               ack_status="fallback_recorded",
    │               user_visible_closeout=False,
    │               metadata={
    │                   "validation_status": "blocked",
    │                   "block_reason": "B1_pure_directory_listing",
    │                   "failure_summary": "Completion blocked by validator",
    │                   "failure_stage": "completion_validation",
    │               }
    │           )
    │
    └──→ gate_required
            │
            └──→ emit_closeout_guarantee(
                    ack_status="pending_manual_review",
                    user_visible_closeout=False,
                    metadata={
                        "validation_status": "gate_required",
                        "gate_reason": "G1_boundary_case",
                    }
                )
```

**关键边界**:
- Validator **不替换** closeout guarantee，而是 **增强** 其输入质量
- blocked_completion 触发 `fallback_needed` guarantee
- gate_required 触发 `pending` guarantee (等待人工)

### 3.2 与 Callback / Completion Ack Guard 的集成

```python
# completion_ack_guard.py 集成点 (伪代码)

def send_roundtable_completion_ack(...):
    # ... 现有逻辑 ...
    
    # ========== NEW: Validator 集成 ==========
    validation_result = validate_subtask_completion(
        output=subagent_output,
        exit_code=exit_code,
        artifacts=artifact_paths,
    )
    
    if validation_result.status == "blocked_completion":
        # 不发送 ack，记录审计
        log_blocked_completion(validation_result)
        return {
            "ack_status": "blocked_by_validator",
            "validation_result": validation_result.to_dict(),
        }
    
    if validation_result.status == "gate_required":
        # 发送 gate 通知，不发送完成 ack
        notify_operator_gate(validation_result)
        return {
            "ack_status": "pending_gate",
            "validation_result": validation_result.to_dict(),
        }
    
    if validation_result.status == "validator_error":
        # Fallback 到原逻辑，记录错误
        log_validator_error(validation_result.error)
        # 继续执行原有 ack 逻辑
    
    # accepted_completion: 继续原有 ack 逻辑
    # ========== END NEW ==========
    
    # ... 原有 ack 发送逻辑 ...
```

### 3.3 与 Subagent Announce 的集成

```
subagent_ended 事件
    │
    ├──→ (原有路径) before_prompt_build → parent wake
    │
    └──→ (新增路径) Validator 检查
            │
            ├──→ accepted → 继续原有 announce
            │
            └──→ blocked/gate → 拦截 announce，记录审计
```

**集成点**: `spawn-interceptor` 的 `onTaskCompleted` hook

---

## 4. 最小实施方案 (v1)

### 4.1 V1 范围 (先做什么)

| 模块 | 功能 | 优先级 |
|------|------|--------|
| **validator_core.py** | 核心验证逻辑 (Through/Block/Gate 规则) | P0 |
| **completion_receipt 集成** | 在 `create_receipt()` 前调用 validator | P0 |
| **audit 日志** | 记录 blocked/gate 决策及原因 | P0 |
| **audit_only 模式** | 默认只记录不拦截，观察 1 周 | P0 |
| **白名单机制** | trusted labels 跳过验证 | P1 |

### 4.2 V1 不做什么

- ❌ 不重构 callback transport 层
- ❌ 不改变 subagent 执行模型
- ❌ 不做 AI 语义理解 (基于规则)
- ❌ 不集成到 tmux backend (v2 再考虑)
- ❌ 不自动 retry blocked completion

### 4.3 V1 文件结构

```
runtime/orchestrator/
├── completion_validator.py          # 新增：Validator 核心
├── completion_validator_rules.py    # 新增：规则定义
└── completion_receipt.py            # 修改：集成 validator
```

---

## 5. 风险、误杀场景、回退方案

### 5.1 误杀场景 (False Positive)

| 场景 | 描述 | 缓解措施 |
|------|------|---------|
| **FP1** | 简单任务确实只需 listing (如"列出文件") | 白名单：label 包含 `list`/`explore` 跳过 |
| **FP2** | 代码片段就是交付物 (如"生成脚本") | T1 规则增强：检测"脚本已生成"声明 |
| **FP3** | 中间状态但实际已完成 (如"开始测试...测试通过") | B3 规则增强：检测后续是否有完成声明 |
| **FP4** | 输出短但有效 (如"修复完成，1 行修改") | B6 规则增强：结合 git diff 验证 |

### 5.2 漏杀场景 (False Negative)

| 场景 | 描述 | 缓解措施 |
|------|------|---------|
| **FN1** | 精心伪造的完成声明 | v1 不处理，依赖 operator 发现后加规则 |
| **FN2** | 交付物存在但内容错误 | v1 不检查内容质量，v2 考虑 checksum |

### 5.3 回退方案

```python
# 配置化回退
VALIDATOR_CONFIG = {
    "mode": "audit_only",  # audit_only | enforce
    "whitelist_labels": ["explore", "list", "check"],
    "through_threshold": 3,  # 降低阈值更宽松
    "fallback_on_error": True,  # validator 错误时 fallback 到原逻辑
}

# 紧急关闭
if os.environ.get("DISABLE_COMPLETION_VALIDATOR") == "1":
    # 完全跳过 validator
    pass
```

---

## 6. 验收标准

### 6.1 功能验收

| 测试用例 | 预期结果 | 验证方法 |
|---------|---------|---------|
| **TC1**: 真实完成 (有交付物 + 测试通过) | `accepted_completion` | 运行真实 coding 任务 |
| **TC2**: 目录 listing 冒充完成 | `blocked_completion` | 模拟 `ls -la` 输出 |
| **TC3**: 代码片段冒充完成 | `blocked_completion` | 模拟纯代码输出 |
| **TC4**: 中间状态冒充完成 | `blocked_completion` | 模拟"开始探索..."输出 |
| **TC5**: 边界情况 (分数=2) | `gate_required` | 构造边界输出 |
| **TC6**: Validator 错误 | `validator_error` + fallback | 模拟异常 |
| **TC7**: 白名单任务跳过 | 直接 through | label 匹配白名单 |
| **TC8**: audit_only 模式 | 只记录不拦截 | 设置 mode=audit_only |

### 6.2 回归验收

| 测试用例 | 预期结果 | 验证方法 |
|---------|---------|---------|
| **RC1**: 现有 completion_receipt 测试通过 | 无回归 | 运行 `test_completion_receipt.py` |
| **RC2**: 现有 ack_guard 测试通过 | 无回归 | 运行 `test_completion_ack_guard.py` |
| **RC3**: 现有 closeout_guarantee 测试通过 | 无回归 | 运行 `test_closeout_guarantee.py` |

### 6.3 性能验收

| 指标 | 目标 | 验证方法 |
|------|------|---------|
| Validator 延迟 | < 100ms / completion | 基准测试 |
| 内存占用 | < 10MB | 压力测试 |
| 误杀率 (audit_only 期间) | < 5% | 人工审计 100 个样本 |

---

## 7. 实现计划

### Phase 1: 核心逻辑 (Day 1-2)
- [ ] 编写 `completion_validator_rules.py` (规则定义)
- [ ] 编写 `completion_validator.py` (核心验证逻辑)
- [ ] 编写单元测试 (覆盖 TC1-TC8)

### Phase 2: 集成 (Day 3-4)
- [ ] 集成到 `completion_receipt.py` (H2 hook)
- [ ] 集成到 `completion_ack_guard.py` (H4 hook)
- [ ] 添加 audit 日志
- [ ] 运行回归测试 (RC1-RC3)

### Phase 3: 观察与调优 (Day 5-11)
- [ ] 部署 audit_only 模式，观察 7 天
- [ ] 收集误杀/漏杀样本
- [ ] 调整规则阈值
- [ ] 更新白名单

### Phase 4: 强制执行 (Day 12+)
- [ ] 切换到 enforce 模式
- [ ] 添加 operator gate UI (可选)
- [ ] 文档更新

---

## 8. 参考与引用

### 8.1 相关文档
- `CURRENT_TRUTH.md`: 当前真值入口
- `overall-plan.md`: 整体计划
- `hook-guard-capabilities.md`: Hook Guard Capabilities 参考
- `completion_receipt.py`: 现有 completion receipt 实现
- `completion_ack_guard.py`: 现有 ack guard 实现
- `closeout_guarantee.py`: 现有 closeout guarantee 实现

### 8.2 代码路径
- `runtime/orchestrator/completion_receipt.py`
- `runtime/orchestrator/completion_ack_guard.py`
- `runtime/orchestrator/closeout_guarantee.py`
- `runtime/orchestrator/core/callback_router.py`
- `runtime/orchestrator/tmux_terminal_receipts.py`

---

## 9. 变更日志

| 日期 | 版本 | 变更 | 作者 |
|------|------|------|------|
| 2026-03-25 | v1.0 | 初始设计锚定 | Zoe |

---

## 附录 A: 规则实现示例 (伪代码)

```python
# completion_validator_rules.py

import re
from pathlib import Path
from typing import List, Tuple

# ========== Through 规则 ==========

THROUGH_KEYWORDS = {
    "完成": 2, "completed": 2, "done": 2, "finished": 2,
    "## 结论": 1, "## Summary": 1, "### Deliverables": 1,
}

def has_explicit_completion_statement(output: str) -> bool:
    """T1: 检查明确完成声明"""
    for keyword, weight in THROUGH_KEYWORDS.items():
        if keyword.lower() in output.lower():
            return True
    return False

def artifacts_exist(artifacts: List[Path]) -> bool:
    """T2: 检查交付物存在"""
    if not artifacts:
        return False
    existing = sum(1 for p in artifacts if p.exists())
    return existing > 0

def has_test_pass_evidence(output: str) -> bool:
    """T3: 检查测试通过证据"""
    patterns = [
        r"\d+ passed",
        r"tests? passed",
        r"ok$",
        r"✓",
        r"全部通过",
    ]
    return any(re.search(p, output, re.IGNORECASE | re.MULTILINE) for p in patterns)

def has_git_commit_evidence(output: str) -> bool:
    """T4: 检查 git 提交证据"""
    patterns = [
        r"\[main [a-f0-9]{7}\]",
        r"committed:",
        r"git commit",
    ]
    return any(re.search(p, output, re.IGNORECASE) for p in patterns)

def has_structured_summary(output: str) -> bool:
    """T5: 检查结构化总结"""
    patterns = [r"^##+\s+\w+", r"^###+\s+\w+"]
    return any(re.search(p, output, re.MULTILINE) for p in patterns)

def has_intermediate_keywords(output: str) -> bool:
    """T6 反向：检查中间状态关键词"""
    keywords = ["开始探索", "starting", "let me check", "looking at", "接下来", "next I will"]
    return any(kw.lower() in output.lower() for kw in keywords)

# ========== Block 规则 ==========

def is_pure_directory_listing(output: str) -> bool:
    """B1: 检查纯目录 listing"""
    lines = output.strip().split("\n")
    if len(lines) < 3:
        return False
    # 检查是否大部分行是文件/目录格式
    dir_pattern = r"^[-d][rwx-]{9}\s+\d+\s+\w+\s+\w+\s+\d+"
    dir_lines = sum(1 for line in lines if re.match(dir_pattern, line))
    return dir_lines / len(lines) > 0.8

def is_pure_code_snippet(output: str) -> bool:
    """B2: 检查纯代码片段"""
    lines = output.strip().split("\n")
    if len(lines) < 5:
        return False
    # 检查是否大部分行是代码格式 (缩进、关键字)
    code_patterns = [r"^\s+(def |class |import |from )", r"^\s+[a-z_]+\(", r"^\s+return "]
    code_lines = sum(1 for line in lines if any(re.match(p, line) for p in code_patterns))
    return code_lines / len(lines) > 0.8 and not has_explicit_completion_statement(output)

def has_intermediate_state_keywords(output: str) -> bool:
    """B3: 检查中间状态关键词"""
    keywords = ["^开始", "^starting", "接下来", "next i will", "让我先", "let me first"]
    return any(re.search(kw, output, re.IGNORECASE) for kw in keywords)

def has_unhandled_error(output: str) -> bool:
    """B4: 检查未处理错误"""
    error_patterns = [r"Traceback \(most recent", r"Error:", r"Exception:", r"失败"]
    resolution_patterns = [r"已修复", r"resolved", r"fixed", r"handled"]
    has_error = any(re.search(p, output) for p in error_patterns)
    has_resolution = any(re.search(p, output, re.IGNORECASE) for p in resolution_patterns)
    return has_error and not has_resolution

# ========== 主验证函数 ==========

def validate_completion(
    output: str,
    exit_code: int,
    artifacts: List[Path],
) -> Tuple[str, str, int]:
    """
    验证 completion
    
    Returns:
        (status, reason, score)
        status: "accepted" | "blocked" | "gate" | "error"
        reason: 规则 ID (如 "B1_pure_directory_listing")
        score: Through 分数
    """
    try:
        # 先检查 Block 规则
        blocked, block_reason = False, ""
        if is_pure_directory_listing(output):
            blocked, block_reason = True, "B1_pure_directory_listing"
        elif is_pure_code_snippet(output):
            blocked, block_reason = True, "B2_pure_code_snippet"
        elif has_intermediate_state_keywords(output):
            blocked, block_reason = True, "B3_intermediate_state"
        elif has_unhandled_error(output):
            blocked, block_reason = True, "B4_unhandled_error"
        elif exit_code != 0:
            blocked, block_reason = True, "B5_timeout_exit"
        elif len(output.strip()) < 100:
            blocked, block_reason = True, "B6_empty_output"
        
        if blocked:
            # 有解释则降为 gate
            if len(output) > 500:
                return "gate", block_reason, 0
            return "blocked", block_reason, 0
        
        # 计算 Through 分数
        score = 0
        if has_explicit_completion_statement(output): score += 2
        if artifacts_exist(artifacts): score += 2
        if has_test_pass_evidence(output): score += 2
        if has_git_commit_evidence(output): score += 1
        if has_structured_summary(output): score += 1
        if not has_intermediate_keywords(output): score += 1
        
        if score >= 3:
            return "accepted", "", score
        elif score == 2:
            return "gate", "G1_boundary_case", score
        else:
            return "blocked", "low_through_score", score
    
    except Exception as e:
        return "error", str(e), 0
```

---

*End of Design Document*
