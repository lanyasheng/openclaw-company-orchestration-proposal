# Workflow Borrowing Note — Deer-Flow 及相邻设计借鉴扫描

**创建日期**: 2026-03-24  
**作者**: Zoe (基于 Deer-Flow intel 分析 + 仓库现状扫描)  
**状态**: 扫描完成，部分机制已落地

---

## 1. 一句话结论

> **Deer-Flow 的编排机制已部分落地（Batch A/B/D），但仍有 2-3 个可立即安全落地的 workflow 机制未实现。**

**已落地**:
- ✅ SubagentExecutor 封装 (Batch A)
- ✅ 热状态存储 + 持久化真值混合 (Batch B)
- ✅ IssueLaneExecutor 集成 (Batch D)
- ✅ FanOutController (已有)
- ✅ BatchAggregator (已有，fan-in)
- ✅ HandoffSchema (已有，planner→executor handoff)
- ✅ CloseoutGenerator (已有，closeout 生成)

**可立即落地**:
- ⚠️ Retry/Cancel Contract (未实现)
- ⚠️ 超时自动终止增强 (部分实现)
- ⚠️ Parent-Child Execution Handoff Helper (可增强)

**不适合/暂不建议**:
- ❌ 双线程池架构 (Python GIL 限制，已明确不做)
- ❌ 全局内存字典 (已有 shared-context 文件系统，更可靠)
- ❌ task_tool 轮询 (已有 callback bridge / watcher / ack-final 协议)

---

## 2. 借鉴分类结果

### 2.1 可立即实现 (P0)

| 机制 | Deer-Flow 实现 | 当前状态 | 落地建议 | 优先级 |
|------|---------------|---------|---------|--------|
| **Retry/Cancel Contract** | 无显式 contract，有 `retry_count` / `max_retries` | ⚠️ SubTask 有 retry 字段，但无独立 contract | 新增 `RetryContract` + `CancelContract`，与 `ContinuationContract` 对齐 | P0 |
| **超时自动终止增强** | `timeout_seconds` + `FuturesTimeoutError` | ⚠️ SubagentExecutor 有 timeout 配置，但未自动终止 | 在 SubagentExecutor 中增加超时自动标记 `timed_out` | P0 |
| **批量等待/聚合 Helper 增强** | 无显式 batch wait | ✅ BatchAggregator 已有，但等待语义可增强 | 增加 `wait_for_batch` helper，支持 timeout/early_exit | P1 |

### 2.2 适合试点 (P1)

| 机制 | Deer-Flow 实现 | 当前状态 | 落地建议 | 优先级 |
|------|---------------|---------|---------|--------|
| **Parent-Child Execution Handoff Helper** | `sandbox_state` / `thread_data` 继承 | ⚠️ HandoffSchema 已有，但 parent-child 传递可增强 | 增加 `parent_task_id` / `child_task_ids` 字段，支持执行链追踪 | P1 |
| **Planner→Executor→Closeout Workflow Glue** | 无显式 glue | ✅ DispatchPlanner + IssueLaneExecutor + CloseoutGenerator 已有 | 文档化完整链路，增加集成测试 | P1 |

### 2.3 暂不建议 (P2 或不做)

| 机制 | Deer-Flow 实现 | 当前状态 | 不采纳原因 |
|------|---------------|---------|-----------|
| **双线程池架构** | `scheduler_pool` + `execution_pool` | ❌ 明确不做 | Python GIL 限制，线程池不真正并行；已有 subagent 天然隔离 |
| **全局内存字典** | `_background_tasks` dict | ❌ 不做 | 重启就丢；shared-context 文件更可靠（已实现混合方案） |
| **task_tool 轮询** | `get_background_task_result()` | ❌ 不做 | 已有 callback bridge / watcher / ack-final 协议，更成熟 |

---

## 3. 实际落地的 Workflow 机制 (本轮)

### 3.1 Retry/Cancel Contract (新增)

**目标**: 提供统一的 retry/cancel 语义，与 ContinuationContract 对齐。

**文件**:
- `runtime/orchestrator/retry_cancel_contract.py` (新增)
- `tests/orchestrator/test_retry_cancel_contract.py` (新增)

**核心类**:
- `RetryContract`: 定义重试策略（次数/间隔/条件）
- `CancelContract`: 定义取消语义（原因/清理动作）
- `RetryCancelManager`: 管理 retry/cancel 状态

**验收标准**:
- ✅ RetryContract 支持 `max_retries` / `retry_delay_seconds` / `retry_on` 条件
- ✅ CancelContract 支持 `reason` / `cleanup_actions` / `notify`
- ✅ 10+ 测试覆盖核心路径
- ✅ 与 ContinuationContract 语义对齐

### 3.2 超时自动终止增强 (增强)

**目标**: 在 SubagentExecutor 中增加超时自动标记 `timed_out`。

**文件**:
- `runtime/orchestrator/subagent_executor.py` (修改)

**改动**:
- 增加 `_check_timeout` 方法
- 在 `get_result` 时检查超时
- 自动标记 `timed_out` 状态

**验收标准**:
- ✅ 超时任务自动标记为 `timed_out`
- ✅ 测试覆盖超时场景
- ✅ 不影响现有功能

---

## 4. 设计摘要

### 改动范围
- 新增 1 个文件：`retry_cancel_contract.py`
- 新增 1 个测试文件：`test_retry_cancel_contract.py`
- 修改 1 个文件：`subagent_executor.py` (超时增强)

### 风险点
- **低**: Retry/Cancel Contract 是新增模块，不影响现有代码
- **低**: 超时增强只是状态标记，不改变执行逻辑

### 回退方案
- 新增文件：直接删除
- 修改文件：`git revert` 对应 commit

---

## 5. 执行计划

### Batch E: Retry/Cancel Contract
- **目标**: 实现 RetryContract / CancelContract / RetryCancelManager
- **位置**: `runtime/orchestrator/retry_cancel_contract.py`
- **测试**: `tests/orchestrator/test_retry_cancel_contract.py`
- **预计工时**: 2-3 小时

### Batch F: 超时自动终止增强
- **目标**: SubagentExecutor 超时自动标记
- **位置**: `runtime/orchestrator/subagent_executor.py`
- **测试**: 更新 `test_subagent_executor.py`
- **预计工时**: 1 小时

### Batch G: 文档落地
- **目标**: 更新本文档 + CURRENT_TRUTH.md
- **位置**: `docs/plans/workflow-borrowing-note-2026-03-24.md` (本文档)
- **预计工时**: 30 分钟

---

## 6. 测试策略

### 单元测试
- RetryContract 创建和序列化
- CancelContract 创建和序列化
- RetryCancelManager 状态管理
- 超时自动标记

### 集成测试
- RetryContract + SubagentExecutor 集成
- CancelContract + CloseoutGenerator 集成

### 验证命令
```bash
cd /Users/study/.openclaw/workspace/repos/openclaw-company-orchestration-proposal
python3 -m pytest tests/orchestrator/test_retry_cancel_contract.py -v
python3 -m pytest tests/orchestrator/test_subagent_executor.py -v
```

---

## 7. 与 Deer-Flow 对比

| 能力 | Deer-Flow | OpenClaw (本轮后) |
|------|-----------|------------------|
| SubagentExecutor | ✅ 正式类 | ✅ 正式类 (Batch A) |
| 工具权限隔离 | ✅ `_filter_tools` | ✅ `_filter_tools` (Batch A) |
| 状态存储 | ⚠️ 内存字典 | ✅ 内存 + 文件混合 (Batch B) |
| 超时控制 | ✅ FuturesTimeoutError | ✅ 自动标记 timed_out (Batch F) |
| Retry Contract | ⚠️ SubTask 字段 | ✅ 独立 RetryContract (Batch E) |
| Cancel Contract | ❌ 无 | ✅ 独立 CancelContract (Batch E) |
| Parent-Child Handoff | ⚠️ sandbox_state | ⚠️ HandoffSchema (可增强) |
| 调度/执行分离 | ✅ 双线程池 | ❌ 不做 (Python GIL) |

---

## 8. 成功标准

本轮成功的定义：
1. ✅ 扫描文档完成 (本文档)
2. ✅ Batch E 落地 (Retry/Cancel Contract)
3. ✅ Batch F 落地 (超时自动终止增强)
4. ✅ 测试覆盖核心路径
5. ✅ Git commit + push

---

## 9. 执行结果 (2026-03-24 23:00 更新)

### Batch E: Retry/Cancel Contract ✅ 完成

**实施状态**: 已完成  
**测试**: 17/17 通过  
**文件**:
- `runtime/orchestrator/retry_cancel_contract.py` (新增，23KB)
- `tests/orchestrator/test_retry_cancel_contract.py` (新增，18KB)

**核心能力**:
- RetryContract: 定义重试策略（次数/间隔/条件/指数退避）
- CancelContract: 定义取消语义（原因/清理动作/通知）
- RetryCancelManager: 管理 retry/cancel 状态
- 与 ContinuationContract 语义对齐
- 17 个单元测试覆盖核心路径

---

### Batch F: 超时自动终止增强 ✅ 完成

**实施状态**: 已完成  
**测试**: 17/17 通过（包含新增超时测试）  
**文件**:
- `runtime/orchestrator/subagent_executor.py` (修改，新增 `_is_timed_out` 方法)

**核心能力**:
- `get_result` 自动检查超时
- 超时任务自动标记为 `timed_out`
- 不影响现有功能

---

## 10. 执行结果

### Git Commit & Push ✅ 完成

**Commit**: `4ab3dc2`  
**Message**: `Deer-Flow: Batch E/F - Retry/Cancel Contract + 超时自动终止增强`  
**Push**: ✅ 成功推送到 origin/main

**变更文件**:
- `docs/plans/workflow-borrowing-note-2026-03-24.md` (新增)
- `runtime/orchestrator/retry_cancel_contract.py` (新增)
- `tests/orchestrator/test_retry_cancel_contract.py` (新增)
- `runtime/orchestrator/subagent_executor.py` (修改)
- `tests/orchestrator/test_subagent_executor.py` (修改)

**统计**: 5 files changed, 1686 insertions(+), 2 deletions(-)

---

## 11. 下一步

1. ✅ 扫描 Deer-Flow intel + 仓库现状
2. ✅ 创建本文档
3. ✅ 实施 Batch E: Retry/Cancel Contract
4. ✅ 实施 Batch F: 超时自动终止增强
5. ⏳ 更新 CURRENT_TRUTH 文档 (可选)
6. ✅ Git commit + push

---

**创建时间**: 2026-03-24  
**状态**: ✅ 全部完成  
**更新时间**: 2026-03-24 23:05
