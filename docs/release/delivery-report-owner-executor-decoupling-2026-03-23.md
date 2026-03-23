# Owner/Executor 解耦 + Coding Lane 默认 Claude Code - 交付报告

**完成时间**: 2026-03-23  
**Commit**: `d8f4ce4`  
**状态**: ✅ 已完成 + 测试覆盖 + 已 push

---

## 设计摘要

### 核心改动

1. **Owner / Executor 解耦**:
   - `owner`: 业务归属/判断/验收 (e.g., trading, main, channel)
   - `executor`: 具体执行路径 (e.g., claude_code, subagent, browser, message)
   - `backend`: 执行通道 (subagent / tmux)，与 executor 解耦

2. **Coding Lane 默认 Claude Code**:
   - `execution_profile=coding` → `executor=claude_code`
   - `execution_profile=generic_subagent` → `executor=subagent`
   - 从 task description 自动推导，无需额外配置

3. **Execution Profile 推导**:
   ```python
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

### 改动文件

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `runtime/orchestrator/core/handoff_schema.py` | 修改 | 新增 executor/execution_profile 字段 + 推导逻辑 |
| `runtime/orchestrator/core/dispatch_planner.py` | 修改 | 支持从 orchestration_contract 读取 executor_preference |
| `runtime/orchestrator/trading_roundtable.py` | 修改 | 注入 execution_profile 和 executor 信息 |
| `runtime/orchestrator/channel_roundtable.py` | 修改 | 注入 execution_profile 和 executor 信息 |
| `runtime/orchestrator/sessions_spawn_request.py` | 修改 | 传递 executor 信息到 runtime |
| `tests/orchestrator/test_owner_executor_decoupling.py` | 新增 | 23 个测试用例 |
| `docs/plans/owner-executor-decoupling.md` | 新增 | 完整设计文档 |
| `docs/CURRENT_TRUTH.md` | 修改 | 更新版本号和入口指引 |

---

## 测试结果

### 新增测试 (Owner/Executor Decoupling)

```bash
$ python3 -m pytest tests/orchestrator/test_owner_executor_decoupling.py -v
============================= 23 passed in 0.03s ==============================
```

覆盖场景:
- ✅ execution_profile 推导 (coding keywords, tmux backend, explicit override)
- ✅ executor 解析 (profile-driven, preference override, fallback)
- ✅ build_planning_handoff 集成
- ✅ DispatchPlanner 集成
- ✅ Trading Roundtable 集成
- ✅ Channel Roundtable 集成
- ✅ Owner/Executor 解耦语义验证

### 向后兼容性测试

```bash
$ python3 -m pytest tests/orchestrator/test_handoff_schema.py -v
============================= 24 passed in 0.40s ==============================
```

### 集成测试

```bash
$ python3 -m pytest tests/orchestrator/test_trading_roundtable.py -v
============================= 12 passed in 1.02s ==============================
```

### 全量回归测试

```bash
$ python3 -m pytest tests/orchestrator/ -v -k "not slow"
============= 468 passed, 12 warnings, 6 subtests passed in 48.10s =============
```

---

## 风险点与回退方式

### 风险点

1. **Keyword 匹配精度**: coding keywords 列表可能需要根据实际使用场景调整
   - 缓解：显式 `executor_preference` 可覆盖自动推导
   
2. **Executor 语义**: `executor=claude_code` 目前仍通过 subagent runtime 执行
   - 缓解：需要上游正确配置 Claude Code CLI

3. **向后兼容性**: 所有新字段都有默认值
   - 验证：所有现有测试通过

### 回退方式

1. **显式覆盖**: 指定 `executor_preference="subagent"` 可覆盖自动推导
   ```python
   handoff = build_planning_handoff(
       ...
       executor_preference="subagent",  # 强制使用 subagent
   )
   ```

2. **旧代码兼容**: 未指定 execution_profile 时默认 `generic_subagent`

3. **测试保护**: 468 个测试用例确保无破坏性变更

---

## 其他人最简单接入方式

### One-Liner

```bash
# 编码任务自动走 Claude Code，非编码任务走 subagent
# 无需额外配置，从 task description 自动推导
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
# handoff.executor == "claude_code"
# handoff.execution_profile == "coding"

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
# handoff2.executor == "subagent"
# handoff2.execution_profile == "generic_subagent"
```

---

## Repo 真值

### Commit & Push

```bash
$ git log -1 --oneline
d8f4ce4 (HEAD -> main) P0-3 Batch 5: Owner/Executor 解耦 + Coding Lane 默认 Claude Code

$ git push origin main
To github.com:lanyasheng/openclaw-company-orchestration-proposal.git
   00344a1..d8f4ce4  main -> main
```

### 文件清单

**修改文件 (6)**:
- `runtime/orchestrator/core/handoff_schema.py`
- `runtime/orchestrator/core/dispatch_planner.py`
- `runtime/orchestrator/trading_roundtable.py`
- `runtime/orchestrator/channel_roundtable.py`
- `runtime/orchestrator/sessions_spawn_request.py`
- `docs/CURRENT_TRUTH.md`

**新增文件 (2)**:
- `tests/orchestrator/test_owner_executor_decoupling.py`
- `docs/plans/owner-executor-decoupling.md`

### 文档入口

- **设计文档**: `docs/plans/owner-executor-decoupling.md`
- **当前真值**: `docs/CURRENT_TRUTH.md` (已更新 header)
- **测试文件**: `tests/orchestrator/test_owner_executor_decoupling.py`

---

## 交付标准验收

| 标准 | 状态 | 证据 |
|------|------|------|
| ✅ 清晰设计摘要 | 完成 | 本文档 + `docs/plans/owner-executor-decoupling.md` |
| ✅ Targeted tests | 完成 | 23 个测试用例，覆盖所有核心场景 |
| ✅ Trading / Channel 复用 | 完成 | 两个 roundtable 都已注入 executor 信息 |
| ✅ Broader regression | 完成 | 468 个测试全部通过 |
| ✅ Commit & Push | 完成 | Commit `d8f4ce4`, 已 push 到 origin/main |
| ✅ 最简单接入方式 | 完成 | 见上方 "其他人最简单接入方式" 章节 |

---

## 后续扩展

1. **Browser Executor**: 未来可支持 `executor=browser` 用于网页交互任务
2. **Message Executor**: 未来可支持 `executor=message` 用于纯通知任务
3. **Custom Profiles**: 支持自定义 execution_profile 和 executor 映射
4. **Keyword 优化**: 根据实际使用场景调整 coding keywords 列表

---

**交付完成** ✅
