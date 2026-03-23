# Owner/Executor 解耦设计 (P0-3 Batch 5)

> **实现日期**: 2026-03-23
> **状态**: ✅ 已实现 + 测试覆盖

## 核心目标

1. **Owner / Executor 解耦**:
   - `owner`: 负责业务归属、判断、验收 (e.g., trading, main, channel)
   - `executor`: 负责具体执行路径 (e.g., claude_code for coding, subagent for generic)
   - `backend`: 执行通道 (subagent / tmux)，与 executor 解耦

2. **Coding Lane 默认 Claude Code**:
   - 对 coding / implementation / refactor / bugfix / test-fix 类型任务，默认 `executor=claude_code`
   - 非 coding lane 继续默认 `executor=subagent` (role agent)

3. **保持通用**:
   - 不做 trading 私补丁
   - trading / channel 等场景都能复用这套 owner/executor 模型

## 设计摘要

### 新增字段

```python
@dataclass
class PlanningHandoff:
    owner: str  # 业务所有者
    executor: Literal["subagent", "claude_code", "browser", "message"]  # 执行器
    backend_preference: Literal["subagent", "tmux", "manual"]  # 执行通道
    execution_profile: Literal["generic_subagent", "coding", "interactive_observable"]  # 执行 profile
```

### Execution Profile 推导规则

```python
# 1. backend_preference=tmux → interactive_observable
# 2. task_preview 包含 coding keywords → coding
# 3. 默认 → generic_subagent

coding_keywords = [
    "implement", "implementation", "implementing",
    "refactor", "refactoring",
    "fix", "fixing", "bugfix", "bug-fix",
    "test", "testing", "test-fix",
    "code", "coding",
    "build", "develop", "development",
    "api endpoint", "module", "feature"
]
```

### Executor 推导规则

```python
# 1. 显式 executor_preference 优先
# 2. execution_profile=coding → executor=claude_code
# 3. execution_profile=generic_subagent → executor=subagent
# 4. execution_profile=interactive_observable → executor=subagent
# 5. Fallback: task_preview 包含 coding keywords → executor=claude_code
```

### 默认映射表

| execution_profile | executor | backend | 场景示例 |
|------------------|----------|---------|---------|
| `coding` | `claude_code` | `subagent` | Implement API, Refactor module |
| `generic_subagent` | `subagent` | `subagent` | Review strategy, Analyze data |
| `interactive_observable` | `subagent` | `tmux` | Monitor long-running task |

## 其他人最简单接入方式

### One-Liner

```bash
# 编码任务自动走 Claude Code，非编码任务走 subagent
# 无需额外配置，从 task description 自动推导 execution_profile 和 executor
```

### 快速示例

```python
from core.handoff_schema import build_planning_handoff

# Coding 任务 → 自动推导 claude_code
handoff = build_planning_handoff(
    source_type="dispatch_plan",
    source_id="dispatch_001",
    continuation_contract={
        "stopped_because": "continuation",
        "next_step": "Implement new API endpoint",
        "next_owner": "main",
    },
    scenario="api_development",
    adapter="api_adapter",
    owner="main",
)
assert handoff.executor == "claude_code"
assert handoff.execution_profile == "coding"

# 非 coding 任务 → 自动推导 subagent
handoff2 = build_planning_handoff(
    source_type="dispatch_plan",
    source_id="dispatch_002",
    continuation_contract={
        "stopped_because": "continuation",
        "next_step": "Review trading strategy",
        "next_owner": "trading",
    },
    scenario="trading_review",
    adapter="trading_adapter",
    owner="trading",
)
assert handoff2.executor == "subagent"
assert handoff2.execution_profile == "generic_subagent"
```

### 显式覆盖

```python
# 即使 task 是 coding，显式指定 subagent 也会生效
handoff = build_planning_handoff(
    source_type="dispatch_plan",
    source_id="dispatch_003",
    continuation_contract={
        "stopped_because": "continuation",
        "next_step": "Implement feature",
        "next_owner": "main",
    },
    scenario="feature",
    adapter="feature_adapter",
    owner="main",
    executor_preference="subagent",  # 显式覆盖
)
assert handoff.executor == "subagent"
```

## 改动文件

### 核心实现

1. **`runtime/orchestrator/core/handoff_schema.py`**
   - 新增 `executor`, `execution_profile` 字段到 `PlanningHandoff`
   - 新增 `_resolve_executor_from_profile_and_task()` 函数
   - 新增 `_resolve_execution_profile_from_task()` 函数
   - 更新 `build_planning_handoff()` 支持自动推导

2. **`runtime/orchestrator/core/dispatch_planner.py`**
   - 更新 `DispatchPlan.to_planning_handoff()` 传递 `executor_preference`

3. **`runtime/orchestrator/trading_roundtable.py`**
   - 注入 `execution_profile` 和 `executor` 到 orchestration_contract

4. **`runtime/orchestrator/channel_roundtable.py`**
   - 注入 `execution_profile` 和 `executor` 到 orchestration_contract

5. **`runtime/orchestrator/sessions_spawn_request.py`**
   - 更新 `_build_sessions_spawn_params()` 包含 executor 信息

### 测试覆盖

6. **`tests/orchestrator/test_owner_executor_decoupling.py`** (新增)
   - 23 个测试用例覆盖:
     - execution_profile 推导
     - executor 解析
     - coding lane 默认 Claude Code
     - 非 coding lane 保持 subagent
     - trading / channel 场景复用

## 测试结果

```bash
$ python3 -m pytest tests/orchestrator/test_owner_executor_decoupling.py -v
============================= 23 passed in 0.03s ==============================

$ python3 -m pytest tests/orchestrator/test_handoff_schema.py -v
============================= 24 passed in 0.40s ==============================

$ python3 -m pytest tests/orchestrator/test_trading_roundtable.py -v
============================= 12 passed in 1.02s ==============================
```

## 风险点

1. **向后兼容性**: 所有新字段都有默认值，旧代码不受影响
2. **Keyword 匹配**: coding keywords 列表可能需要根据实际使用场景调整
3. **Executor 语义**: `executor=claude_code` 目前仍通过 subagent runtime 执行，需要上游正确配置 Claude Code CLI

## 回退方式

1. **显式覆盖**: 指定 `executor_preference="subagent"` 可覆盖自动推导
2. **旧代码兼容**: 未指定 execution_profile 时默认 `generic_subagent`
3. **测试验证**: 所有现有测试通过，确保无破坏性变更

## 后续扩展

1. **Browser Executor**: 未来可支持 `executor=browser` 用于网页交互任务
2. **Message Executor**: 未来可支持 `executor=message` 用于纯通知任务
3. **Custom Profiles**: 支持自定义 execution_profile 和 executor 映射

## 真值锚点

- **Commit Hash**: (待 commit 后填充)
- **测试文件**: `tests/orchestrator/test_owner_executor_decoupling.py`
- **实现文件**: `runtime/orchestrator/core/handoff_schema.py`
- **文档入口**: `docs/CURRENT_TRUTH.md` + 本页
