# Protocol Gap Fix Batch Plan — Trading Roundtable

**日期**: 2026-03-24  
**作者**: Zoe (subagent: protocol-gap-fix-batch-plan-20260324-0938)  
**基于**: trading_roundtable 真实问题审计 + 已有修复 (closeout chain fix d60c3c5)

---

## Executive Summary

### 核心问题
本次 trading_roundtable 暴露的不是单一 bug，而是**协议链路多处缺口导致的状态不一致**：
- packet 缺失 30+ truth fields → packet_freeze
- backend terminal receipt 与 business callback 脱节
- closeout 状态显式化后仍依赖手动 push
- callback envelope 有标准但 producer 不遵守

### 修复策略
**不做大而全的 runtime 重构**，而是：
1. 优先修最容易再次出问题的环节（glue/contract 校验）
2. 批次化推进：P0 必须先修 → P1 强烈建议 → P2 优化项
3. 明确边界：哪些修完后能基本消灭这类问题，哪些只能降低复发概率

---

## 1. 协议缺口清单（6 个）

### Gap 1: Packet Skeleton 前置校验缺失

**问题描述**:
- phase1 packet 经常缺失 30+ truth fields（packet_version, phase_id, candidate_id, overall_gate, artifact paths 等）
- 当前在 `process_trading_roundtable_callback()` 中才做校验，导致 packet_freeze
- Selector500 closeout 案例显示：需要手动 backfill 才能继续

**缺口类型**: **混合问题** (runtime 校验 + operator 流程)
- runtime: 缺少前置 schema 校验层
- operator: 没有 checklist 确保 producer 输出完整 packet

**影响**:
- 主线频繁停住，需要人工介入 backfill
- 同样的缺失字段问题重复出现

---

### Gap 2: 字段归属/回填责任不明确

**问题描述**:
- 不清楚哪些字段由 backend terminal receipt 填（tmux/subagent completion）
- 哪些由 adapter 填（trading_roundtable.py）
- 哪些由 operator/上层 glue 补（process_trading_roundtable_callback 调用方）

**缺口类型**: **混合问题** (文档/契约 + operator 流程)
- 文档: 没有明确的字段责任矩阵
- runtime: 没有强制校验字段来源

**影响**:
- producer 不知道必须输出哪些字段
- adapter 和 operator 之间责任模糊
- 问题出现时难以定位责任方

---

### Gap 3: Callback Envelope 标准化执行不力

**问题描述**:
- canonical_callback_envelope.v1 已定义，但 producer 经常不写或写不全
- tmux completion report 与 business callback payload 脱节
- `orchestrator/tmux_terminal_receipts.py` 有 blocked fallback，但 producer 仍可能输出不完整 payload

**缺口类型**: **混合问题** (glue 问题 + operator 流程)
- glue: dispatch reference 没有强制写明 business callback 输出路径与 contract
- operator: tmux continuation prompt 没有强制要求写出真实 business callback payload

**影响**:
- callback bridge 收到的 payload 质量不稳定
- 需要依赖 blocked fallback 来兜底，但 fallback 本身是 degraded 状态

---

### Gap 4: Closeout 默认硬步骤未自动化

**问题描述**:
- P0-4 Batch 1 (d60c3c5) 已实现 closeout 状态显式化（closeout_status + push_required）
- 但 **不自动 push**，仅输出状态信号
- 实际 push 由上层 glue/operator 执行，依赖人工判断

**缺口类型**: **混合问题** (runtime 核心 + operator 流程)
- runtime: 故意不自动 push（安全设计）
- operator: 需要明确 glue 层消费 closeout 状态并执行 push

**影响**:
- "最后一公里"仍可能停住（closeout complete 但 push 未执行）
- 依赖 operator 记住检查 closeout 状态

---

### Gap 5: Git Closeout/Push 默认动作缺失

**问题描述**:
- 没有标准化的 git closeout/push 流程
- 哪些分支需要 push、push 前是否需要人工确认、push 失败如何处理，没有统一规范
- trading 场景默认需要 push，但具体动作由 operator 自行决定

**缺口类型**: **operator 流程问题**
- 不是 runtime 核心问题，是上层 glue 职责
- 需要 runbook/SOP 明确 push 流程

**影响**:
- 不同 operator 可能有不同的 push 习惯
- push 失败时缺乏标准回退方案

---

### Gap 6: Backend Terminal Receipt → Business Callback 映射不完整

**问题描述**:
- tmux terminal receipt 只描述 backend truth（completion status, artifact paths）
- business callback payload 需要业务 closeout 真值（PASS/FAIL/CONDITIONAL）
- 两者之间的映射/ETL 层不完整，依赖 producer 手动写出 business payload

**缺口类型**: **glue 问题**
- tmux_terminal_receipts.py 有 blocked fallback，但不能替代真实 business payload
- 需要更智能的 ETL/backfill 层（但当前策略是"无真值不伪造"）

**影响**:
- tmux 路径的 business callback 质量依赖 producer 纪律
- 自动化程度受限

---

### Gap 7: Timeout / Error / Empty-Result Fallback 未正式纳入协议

**问题描述**:
- 当前 state_machine.py 有 `TIMEOUT` / `FAILED` 状态，但**没有标准化的 closeout 处理流程**
- batch_aggregator.py 有 `detect_stuck_batches()`，但**没有自动 retry / degrade / abort 策略**
- empty-result（任务完成但输出为空/无 artifact）没有硬拦截，可能被当成正常完成
- completion_ack_guard.py 有 fallback receipt，但**fallback 后的 closeout 语义不明确**

**缺口类型**: **混合问题** (runtime 核心 + glue + operator 流程)
- runtime: 有状态定义但缺少标准化处理策略
- glue: 没有统一的 fallback closeout 协议
- operator: 没有明确的 retry / degrade / abort 决策树

**影响**:
- stuck batches 需要人工发现和处理
- timeout 后的 closeout 状态不一致（有时标记 timeout，有时仍等 callback）
- empty-result 可能污染 downstream 决策（没有 artifact 但 verdict=PASS）

**当前代码证据**:
```python
# state_machine.py — 有状态定义
class TaskState(str, Enum):
    TIMEOUT = "timeout"
    FAILED = "failed"
    RETRYING = "retrying"

# batch_aggregator.py — 有 stuck 检测
def detect_stuck_batches(timeout_minutes: int = 60) -> List[Dict[str, Any]]:
    # 返回 stuck 批次列表，但**不自动处理**
    ...

# 但缺少：
# 1. timeout 后的自动 closeout 协议
# 2. empty-result 的硬拦截逻辑
# 3. retry / degrade / abort 的标准化决策树
```

---

## 2. 批次化修复方案

### Batch P0: 必须先修（本周内）

| # | 修复项 | 类型 | 预计工时 | 修复后效果 |
|---|--------|------|---------|-----------|
| P0-1 | **Packet Schema 前置校验** | runtime+glue | 4-6h | packet 缺失字段在 callback 前就被捕获，不再等到 processing 阶段才发现 |
| P0-2 | **字段责任矩阵文档** | 文档 | 2-3h | producer/adapter/operator 清楚各自职责，减少推诿 |
| P0-3 | **Dispatch Reference 强制写明 business callback contract** | glue | 2-3h | tmux dispatch 明确写出 business payload 输出路径，减少脱节 |
| P0-4 | **Timeout / Empty-Result 最小 Fallback 协议** | runtime+glue | 6-8h | stuck batches 自动 closeout，empty-result 硬拦截为非完成 |

**P0 修复后效果**:
- ✅ **基本消灭** "packet 缺失 30+ fields 导致 packet_freeze" 这类问题
- ✅ **基本消灭** "stuck batches 无人处理" 这类问题（有自动 fallback closeout）
- ✅ **基本消灭** "empty-result 被当成正常完成" 这类问题（硬拦截）
- ✅ **显著降低** "callback payload 不完整" 的复发概率
- ⚠️ 仍可能出现：producer 不遵守 contract 写出错误字段值（需要 P1 的自动化校验）

---

### Batch P1: 强烈建议修（下周）

| # | 修复项 | 类型 | 预计工时 | 修复后效果 |
|---|--------|------|---------|-----------|
| P1-1 | **Closeout Push Glue 实现** | glue | 6-8h | closeout complete 后自动触发 push（带人工确认 gate） |
| P1-2 | **Business Payload 自动生成（有限场景）** | glue | 4-6h | 对 acceptance harness 结果等结构化数据，自动 ETL 生成 business payload |
| P1-3 | **Git Closeout SOP** | 文档+脚本 | 3-4h | 标准化 push 流程，包括失败回退方案 |
| P1-4 | **Fallback Closeout 审计日志** | runtime | 3-4h | 记录所有 timeout/error/empty-result fallback 事件，便于复盘 |

**P1 修复后效果**:
- ✅ **基本消灭** "closeout complete 但 push 未执行" 这类问题
- ✅ **显著提升** fallback 事件的可观测性和可审计性
- ✅ **显著降低** "tmux business payload 缺失" 的复发概率
- ⚠️ 仍可能出现：ETL 逻辑无法覆盖的 edge cases

---

### Batch P2: 优化项（后续迭代）

| # | 修复项 | 类型 | 预计工时 | 修复后效果 |
|---|--------|------|---------|-----------|
| P2-1 | **Closeout Dashboard 集成** | 工具 | 4-6h | 在 OpenClaw dashboard 中显示 closeout 状态 |
| P2-2 | **Closeout 审计日志** | runtime | 3-4h | 记录所有 closeout 状态变更历史 |
| P2-3 | **统一 Closeout 接口** | runtime | 4-6h | channel/non-trading 场景也可以使用 closeout_tracker |

**P2 修复后效果**:
- ✅ 提升可观测性和审计能力
- ⚠️ 不直接影响核心链路稳定性

---

## 2.5 最小 Fallback 协议（P0-4 详细设计）

### Timeout / Error / Empty-Result Fallback 协议 v1

#### 定义

| 类型 | 定义 | 检测方式 |
|------|------|---------|
| **Timeout** | 任务超过 `timeout_seconds` 仍未 callback | `state_machine.py` 检测 `dispatched_at` + `timeout_seconds` |
| **Error** | 任务明确失败（error verdict / exception） | `backend_terminal_receipt.state = failed` |
| **Empty-Result** | 任务完成但无 artifact / 输出为空 | `backend_terminal_receipt.artifacts = {}` 或 `business_callback_payload = {}` |

---

#### Fallback 决策树

```
任务完成/超时
    │
    ├── Timeout?
    │   ├── 首次超时 → 标记 timeout，触发 retry（最多 1 次）
    │   └── 重试后仍超时 → 标记 timeout_closeout，degrade batch 为 CONDITIONAL
    │
    ├── Error?
    │   ├── 可恢复错误（网络/临时故障）→ 标记 error_retry，触发 retry（最多 1 次）
    │   └── 不可恢复错误 → 标记 error_closeout，batch 为 FAIL
    │
    └── Empty-Result?
        ├── 有 backend receipt 但无 business payload → 生成 blocked fallback payload
        └── 完全无输出 → 标记 empty_closeout，batch 为 FAIL
```

---

#### Closeout 状态定义

```python
class FallbackCloseoutStatus(str, Enum):
    TIMEOUT_RETRY = "timeout_retry"          # 首次超时，准备重试
    TIMEOUT_CLOSEOUT = "timeout_closeout"    # 重试后仍超时，降级 closeout
    ERROR_RETRY = "error_retry"              # 可恢复错误，准备重试
    ERROR_CLOSEOUT = "error_closeout"        # 不可恢复错误，失败 closeout
    EMPTY_CLOSEOUT = "empty_closeout"        # 空输出，失败 closeout
    DEGRADED_CLOSEOUT = "degraded_closeout"  # 部分成功，降级 closeout
```

---

#### 最小协议流程

**1. Timeout 处理流程**:
```
1. detect_stuck_batches() 发现超时任务
2. 检查 retry_count:
   - retry_count = 0 → 标记 TIMEOUT_RETRY，retry_count++，重新 dispatch
   - retry_count >= 1 → 标记 TIMEOUT_CLOSEOUT，生成 degraded closeout
3. 生成 closeout artifact:
   - closeout_status = "incomplete" (TIMEOUT_CLOSEOUT)
   - fallback_reason = "timeout_after_retry"
   - batch_verdict = "CONDITIONAL" (允许人工确认后继续)
```

**2. Error 处理流程**:
```
1. backend_terminal_receipt.state = failed
2. 检查错误类型:
   - 可恢复（网络/临时）→ 标记 ERROR_RETRY，retry_count++，重新 dispatch
   - 不可恢复（逻辑/数据）→ 标记 ERROR_CLOSEOUT
3. 生成 closeout artifact:
   - closeout_status = "blocked" (ERROR_CLOSEOUT)
   - fallback_reason = "error_<type>"
   - batch_verdict = "FAIL"
```

**3. Empty-Result 处理流程**:
```
1. 检查 backend_terminal_receipt.artifacts:
   - 有 artifacts 但无 business payload → 生成 blocked fallback payload
   - 完全无 artifacts → 标记 EMPTY_CLOSEOUT
2. 生成 closeout artifact:
   - closeout_status = "blocked" (EMPTY_CLOSEOUT)
   - fallback_reason = "empty_result"
   - batch_verdict = "FAIL" (硬拦截，不允许 downstream 使用)
```

---

#### 硬拦截规则（Empty-Result）

**Empty-Result 必须标记为 FAIL，不允许 PASS 或 CONDITIONAL**:

```python
def validate_callback_payload(payload: Dict[str, Any]) -> ValidationResult:
    # 硬拦截：empty result → FAIL
    if not payload.get("trading_roundtable"):
        return ValidationResult(
            valid=False,
            verdict="FAIL",
            reason="empty_result_no_business_payload",
            closeout_status="empty_closeout",
        )
    
    packet = payload.get("trading_roundtable", {}).get("packet", {})
    if not packet.get("artifact", {}).get("path"):
        return ValidationResult(
            valid=False,
            verdict="FAIL",
            reason="empty_result_no_artifact",
            closeout_status="empty_closeout",
        )
    
    # 其他校验...
```

**理由**: Empty-result 表示任务没有产生任何有效输出，可能是：
- 执行失败但未正确报告
- 数据源问题导致无结果
- 代码逻辑 bug 导致无输出

这类情况下游无法使用，必须硬拦截。

---

#### Retry 策略

| 场景 | 最大重试次数 | 重试间隔 | 重试条件 |
|------|------------|---------|---------|
| Timeout | 1 次 | 立即 | retry_count = 0 |
| Error (可恢复) | 1 次 | 立即 | 错误类型在白名单内 |
| Error (不可恢复) | 0 次 | N/A | 直接进入 closeout |
| Empty-Result | 0 次 | N/A | 硬拦截，不重试 |

**可恢复错误白名单**:
- 网络超时 (`ETIMEDOUT`, `ECONNRESET`)
- 临时资源不足 (`ENOENT` 临时文件)
- Rate limit (`429 Too Many Requests`)

**不可恢复错误**:
- 逻辑错误 (`AssertionError`, `ValueError`)
- 数据错误 (`DataValidationError`)
- 配置错误 (`ConfigError`)

---

#### Closeout Artifact 结构

```json
{
  "closeout_id": "closeout_<batch_id>_<timestamp>",
  "batch_id": "<batch_id>",
  "closeout_status": "timeout_closeout|error_closeout|empty_closeout|degraded_closeout",
  "fallback_reason": "timeout_after_retry|error_<type>|empty_result|partial_success",
  "batch_verdict": "CONDITIONAL|FAIL",
  "retry_count": 0,
  "original_timeout_seconds": 3600,
  "actual_duration_seconds": 3601,
  "artifacts": {
    "backend_receipt_path": "<path>",
    "fallback_payload_path": "<path>",
    "closeout_path": "<path>"
  },
  "continuation_contract": {
    "stopped_because": "timeout|error|empty_result",
    "next_step": "manual_review_required|fix_and_retry",
    "next_owner": "operator"
  },
  "created_at": "2026-03-24T10:00:00+08:00"
}
```

---

#### 实现位置

| 模块 | 职责 |
|------|------|
| `runtime/orchestrator/fallback_closeout.py` (新增) | Fallback closeout 核心逻辑 |
| `runtime/orchestrator/state_machine.py` (增强) | 增加 timeout 自动检测和 retry 状态 |
| `runtime/orchestrator/batch_aggregator.py` (增强) | `detect_stuck_batches()` → 自动触发 fallback closeout |
| `runtime/orchestrator/trading_roundtable.py` (增强) | 集成 empty-result 硬拦截校验 |
| `scripts/orchestrator_callback_bridge.py` (增强) | callback 前校验 empty-result |

---

#### 测试要求

```python
# tests/orchestrator/test_fallback_closeout.py

def test_timeout_retry():
    # 首次超时 → retry
    ...

def test_timeout_closeout_after_retry():
    # 重试后仍超时 → degraded closeout
    ...

def test_error_closeout_nonrecoverable():
    # 不可恢复错误 → fail closeout
    ...

def test_empty_result_hard_fail():
    # empty-result → hard fail (不允许 PASS/CONDITIONAL)
    ...

def test_degraded_closeout_partial_success():
    # 部分成功 → degraded closeout (CONDITIONAL)
    ...
```

---

## 3. 立即落地的小补丁（P0-1 前置工作）

### 补丁内容：Packet Schema 校验清单文档

**文件**: `repos/openclaw-company-orchestration-proposal/runtime/orchestrator/TRADING_PACKET_SCHEMA_CHECKLIST.md`

**目的**: 
- 明确 trading_phase1_packet_v1 的必填字段
- 提供校验命令供 producer 自检
- 减少因字段缺失导致的 packet_freeze

**内容**:
```markdown
# Trading Packet Schema Checklist

## 必填字段（Missing → packet_freeze）

### Packet 顶层
- [ ] packet_version: "trading_phase1_packet_v1"
- [ ] phase_id: "trading_phase1"
- [ ] candidate_id: "<string>"
- [ ] run_label: "<string>"
- [ ] input_config_path: "<path>" (可选但建议)
- [ ] generated_at: "<ISO8601>"
- [ ] owner: "trading"
- [ ] overall_gate: "PASS|CONDITIONAL|FAIL"
- [ ] primary_blocker: "none|<blocker>"

### Artifact Truth
- [ ] artifact.path: "<path>"
- [ ] artifact.exists: true
- [ ] artifact.commit: "<git_commit>"

### Report Truth
- [ ] report.path: "<path>"
- [ ] report.exists: true
- [ ] report.summary: "<summary>"

### Commit Truth
- [ ] commit.repo: "workspace-trading"
- [ ] commit.git_commit: "<git_commit>"

### Test Truth
- [ ] test.commands: ["<cmd1>", "<cmd2>"]
- [ ] test.summary: "<summary>"

### Repro Truth
- [ ] repro.commands: ["<cmd1>"]
- [ ] repro.notes: "<notes>"

### Tradability Metrics
- [ ] tradability.annual_turnover: <float>
- [ ] tradability.liquidity_flags: []
- [ ] tradability.gross_return: <float>
- [ ] tradability.net_return: <float>
- [ ] tradability.benchmark_return: <float>
- [ ] tradability.scenario_verdict: "PASS|CONDITIONAL|FAIL"
- [ ] tradability.turnover_failure_reasons: []
- [ ] tradability.liquidity_failure_reasons: []
- [ ] tradability.net_vs_gross_failure_reasons: []
- [ ] tradability.summary: "<summary>"

### Roundtable Closure
- [ ] roundtable.conclusion: "PASS|CONDITIONAL|FAIL"
- [ ] roundtable.blocker: "none|<blocker>"
- [ ] roundtable.owner: "trading"
- [ ] roundtable.next_step: "<next_step>"
- [ ] roundtable.completion_criteria: "<criteria>"

## 校验命令

```bash
# 使用 jq 校验必填字段
cat callback_payload.json | jq '
  .trading_roundtable.packet |
  if .packet_version and .phase_id and .candidate_id and .overall_gate
  then "✅ Packet schema OK"
  else "❌ Missing required fields"
  end
'

# 完整校验脚本（见 scripts/validate_trading_packet.py）
python3 scripts/validate_trading_packet.py callback_payload.json
```
```

**Commit**: 将创建新文件并 commit

---

## 4. 核心问题回答

### "这些都修掉之后，是不是就不会再有这些问题？"

**诚实回答**:

**不能保证 100% 无问题**，但可以区分：

#### 修完后能基本消灭的问题：
1. ✅ **Packet 缺失 30+ fields 导致 packet_freeze**
   - P0-1 前置校验会在 callback 前捕获缺失字段
   - producer 有 checklist 自检
   - 这类问题将**基本消失**

2. ✅ **Closeout complete 但 push 未执行**
   - P1-1 实现 closeout push glue（带人工确认 gate）
   - P1-3 标准化 push SOP
   - 这类问题将**基本消失**

3. ✅ **字段责任不清导致的推诿**
   - P0-2 明确字段责任矩阵
   - 文档清晰界定 producer/adapter/operator 职责
   - 这类问题将**基本消失**

4. ✅ **Stuck batches 无人处理**
   - P0-4 实现自动 fallback closeout
   - timeout 后自动标记 closeout，不再无限等待
   - 这类问题将**基本消失**

5. ✅ **Empty-result 被当成正常完成**
   - P0-4 实现 empty-result 硬拦截
   - 无 artifact / 空 payload 直接标记 FAIL
   - 这类问题将**基本消失**

#### 只能显著降低复发概率的问题：
1. ⚠️ **Callback payload 字段值错误**（不是缺失，是值不对）
   - P0-3 强制写明 contract 可以减少脱节
   - P1-2 自动 ETL 可以覆盖部分场景
   - 但 edge cases 和逻辑错误仍可能出现
   - **复发概率显著降低，但不能消灭**

2. ⚠️ **Backend terminal receipt 与 business callback 不一致**
   - P1-2 自动 ETL 可以减少手动错误
   - 但"无真值不伪造"策略下，复杂场景仍需人工判断
   - **复发概率显著降低，但不能消灭**

3. ⚠️ **Operator 忘记执行 push 或执行错误**
   - P1-1/P1-3 提供自动化和 SOP
   - 但人工操作仍可能出错
   - **复发概率显著降低，但不能消灭**

#### 仍可能残留的问题（超出本次修复范围）：
1. ⚠️ **Runtime 核心逻辑 bug**（state_machine / batch_aggregator / orchestrator）
   - 本次修复不涉及 runtime 核心重构
   - 需要单独的测试/审计来发现

2. ⚠️ **极端 edge cases**（网络故障、文件 I/O 失败、并发冲突）
   - P0-4 有 fallback closeout，但极端情况下仍可能失败
   - 需要更完善的错误处理和重试机制
   - 超出本次修复范围

3. ⚠️ **新场景接入带来的新问题**
   - channel/non-trading 场景可能有不同的需求
   - 需要持续迭代

4. ⚠️ **Retry 后的二次失败**
   - P0-4 只 retry 1 次，二次失败后仍需要人工介入
   - 这是有意设计（避免无限重试），但意味着问题不会完全消失

---

## 5. 边界声明

### 本次修复不做的事情：
1. ❌ **大规模 runtime 重构** — 保持 state_machine / batch_aggregator / orchestrator 核心稳定
2. ❌ **伪造"修完就 100% 无问题"** — 诚实区分"基本消灭"和"显著降低"
3. ❌ **把 workspace-trading 当 canonical runtime 实现路径** — canonical 在 repos/openclaw-company-orchestration-proposal/

### 本次修复的边界：
1. ✅ **优先修 glue/contract 校验** — 低成本高收益
2. ✅ **文档 + 脚本 + 少量 runtime 增强** — 不破坏现有行为
3. ✅ **向后兼容** — 新增字段/功能都是可选的

---

## 6. 下一步行动

### 立即执行（今天）：
1. ✅ **创建 Packet Schema Checklist 文档** — 本补丁
2. ⚠️ **Commit 并推送到 repos/openclaw-company-orchestration-proposal**

### 本周内（P0）：
1. ⚠️ **实现 Packet Schema 前置校验脚本** — `scripts/validate_trading_packet.py`
2. ⚠️ **创建字段责任矩阵文档**
3. ⚠️ **更新 Dispatch Reference 强制写明 business callback contract**
4. ⚠️ **实现 Fallback Closeout 核心逻辑** — `runtime/orchestrator/fallback_closeout.py`
5. ⚠️ **集成 Empty-Result 硬拦截** — `scripts/orchestrator_callback_bridge.py`

### 下周（P1）：
1. ⚠️ **实现 Closeout Push Glue**
2. ⚠️ **实现 Business Payload 自动生成（有限场景）**
3. ⚠️ **创建 Git Closeout SOP**

---

## Appendix A: 参考文件

- `runtime/orchestrator/trading_roundtable.py` — Trading adapter 处理逻辑
- `runtime/orchestrator/closeout_tracker.py` — Closeout 状态跟踪（d60c3c5）
- `runtime/orchestrator/fallback_closeout.py` — Fallback closeout 核心逻辑（P0-4 新增）
- `runtime/orchestrator/contracts.py` — Callback envelope 标准化
- `runtime/orchestrator/tmux_terminal_receipts.py` — TMUX terminal receipt 处理
- `runtime/orchestrator/state_machine.py` — 任务状态机（TIMEOUT/FAILED 状态定义）
- `runtime/orchestrator/batch_aggregator.py` — Batch 汇总（stuck detection）
- `scripts/orchestrator_callback_bridge.py` — Callback bridge 入口
- `scripts/orchestrator_dispatch_bridge.py` — Dispatch bridge 入口

---

## Appendix B: 相关 Commits

- `d60c3c5` — P0-4 Batch 1: Closeout chain fix (explicit closeout status + push_required)
- `39d8efd` — P0-3 Batch 9 Fix: Add explicit emit_request() call
- `aa88596` — P0-3 Batch 8: Auto-execute integration in callback_bridge
- `03fe667` — P0-3 Batch 8: Auto-trigger continuation fix

---

*End of Report*
