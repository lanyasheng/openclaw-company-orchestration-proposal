# Deer-Flow 适配计划 (2026-03-24)

> **角色**: 📋 **Deer-Flow 借鉴线实施计划** - 明确"借什么、不借什么、为什么、如何落地"
>
> **背景**: 基于 `shared-context/intel/2026-03-24-deerflow-orchestration-mechanism-lessons.md` 的分析结论
>
> **原则**: 薄层、可回退、不推翻现有主链

---

## 1. 一句话结论

> **Deer-Flow 的编排机制是能跑的，但只借 execution layer / subagent runtime，不替换现有 control plane。**

**借的**:
- SubagentExecutor 封装（统一 task_id / timeout / status / result handle / tool allowlist）
- 调度/执行分离思路（局部试点，不大规模引入）
- 热状态存储 + 持久化真值混合方案（内存快、文件真）

**不借的**:
- 双线程池架构（Python GIL 限制，收益有限）
- 全局内存字典（重启就丢，不如直接用 shared-context 文件系统）
- task_tool 轮询机制（我们已有更成熟的 callback bridge / watcher）

**为什么**:
- Deer-Flow 的 control plane 只有 task_tool 轮询，不如我们的 sessions_spawn / roundtable / ack-final 协议成熟
- 我们的 shared-context 文件系统比内存字典更可靠（重启不丢、可审计、可回溯）
- 我们的多 Agent 协作协议（双向 roundtable）比 Deer-Flow 的 lead→sub 单向更丰富

---

## 2. 实施批次

### Batch A: SubagentExecutor 薄封装 Trial

**目标**: 把 `sessions_spawn` / ACP / subagent 封装成正式 executor 类

**范围**:
- 不改现有控制面
- 只做一层薄封装
- 验证工具权限隔离是否可行

**位置**:
- `runtime/orchestrator/subagent_executor.py`（新增）
- `tests/orchestrator/test_subagent_executor.py`（新增测试）

**验收标准**:
- ✅ 封装类可实例化，接口清晰
- ✅ 支持 tool allowlist 过滤
- ✅ 支持 timeout 配置
- ✅ 返回 task_id 和 status
- ✅ 10+ 测试覆盖核心路径

**风险**:
- 低：只是封装层，不影响现有代码
- 回退方案：直接删除新文件，不影响主链

**依赖**: 无

**预计工时**: 2-3 小时

---

### Batch B: 热状态存储 + 持久化真值混合方案

**目标**: 引入内存缓存 + shared-context 文件持久化混合方案

**范围**:
- 在 SubagentExecutor 内部引入内存缓存
- 完成后持久化到 shared-context 文件
- 验证轮询性能提升

**位置**:
- `runtime/orchestrator/subagent_state.py`（新增）
- `~/.openclaw/shared-context/subagent_states/`（新增目录）

**验收标准**:
- ✅ 内存缓存读写正常
- ✅ 完成后持久化到文件
- ✅ 重启后可从文件恢复终态
- ✅ 8+ 测试覆盖核心路径

**风险**:
- 低：内存缓存只是加速层，文件仍是真值
- 回退方案：禁用内存缓存，直接读写文件

**依赖**: Batch A 完成

**预计工时**: 2-3 小时

---

### Batch C: 调度/执行分离轻量试点

**目标**: 在局部场景试点调度/执行分离

**范围**:
- **不做**全局双线程池（Python GIL 限制，收益有限）
- **只做**局部试点：在 coding issue lane 中引入简单的任务队列
- 验证长任务不阻塞调度

**位置**:
- `runtime/orchestrator/issue_lane_executor.py`（新增或修改）

**验收标准**:
- ⚠️ 如果适合：试点成功，文档记录经验
- ⚠️ 如果不适合：明确缩范围，文档记录原因

**风险**:
- 中：可能发现不适合当前架构
- 回退方案：保留试点代码但默认禁用

**依赖**: Batch A 完成

**预计工时**: 3-4 小时（或 1 小时决策不做）

---

### Batch D: 最小集成到现有执行路径

**目标**: 将 SubagentExecutor 集成到 coding issue lane 或现有 subagent 执行路径

**范围**:
- 在 `issue_lane_schemas.py` 中引入 SubagentExecutor
- 或在 `spawn_execution.py` 中引入 SubagentExecutor
- 验证工具权限隔离到 subagent 级

**位置**:
- `runtime/orchestrator/issue_lane_schemas.py` 或 `runtime/orchestrator/spawn_execution.py`

**验收标准**:
- ✅ 集成后测试通过
- ✅ 工具权限隔离生效
- ✅ 不破坏现有功能

**风险**:
- 中：可能影响现有执行路径
- 回退方案：保留旧路径，新路径通过 feature flag 控制

**依赖**: Batch A + B 完成

**预计工时**: 3-4 小时

---

## 3. 批次关系

```
Batch A (SubagentExecutor)
    ↓
Batch B (热状态存储) ──→ Batch D (最小集成)
    ↓
Batch C (调度/执行分离试点) [可选，视情况而定]
```

**并行关系**:
- Batch A 和 Batch C 可以并行（如果 C 决定做）
- Batch B 依赖 A
- Batch D 依赖 A + B

**串行关系**:
- A → B → D 是主线
- C 是可选试点

---

## 4. 明确不做的部分

| 能力 | Deer-Flow 实现 | 我们的决策 | 原因 |
|------|---------------|-----------|------|
| 双线程池 | scheduler_pool + execution_pool | ❌ 不做 | Python GIL 限制，线程池不真正并行；我们已有 subagent 天然隔离 |
| 全局内存字典 | `_background_tasks` dict | ❌ 不做 | 重启就丢；我们的 shared-context 文件更可靠 |
| task_tool 轮询 | `get_background_task_result()` | ❌ 不做 | 我们已有 callback bridge / watcher / ack-final 协议 |
| 工具过滤 | `_filter_tools()` | ✅ 借鉴 | 这是有价值的，封装到 SubagentExecutor |
| 超时控制 | `timeout_seconds` + FuturesTimeoutError | ✅ 借鉴 | 我们已有 session timeout，但可以更细粒度 |
| 状态继承 | sandbox_state / thread_data | ⚠️ 部分借鉴 | 我们通过上下文注入实现，不需要显式继承 |

---

## 5. 测试策略

### 单元测试
- 每个新增模块独立测试
- 覆盖核心路径 + 边界条件
- 不追求 100% coverage，但核心逻辑必须覆盖

### 集成测试
- SubagentExecutor + 现有执行路径
- 验证不破坏现有功能

### 验证命令
```bash
cd <repo-root>
python3 -m pytest tests/orchestrator/test_subagent_executor.py -v
python3 -m pytest tests/orchestrator/test_subagent_state.py -v
```

---

## 6. 文档更新

### 必须更新
- `docs/CURRENT_TRUTH.md`: 添加 Deer-Flow 借鉴线状态
- `runtime/orchestrator/README.md`: 添加 SubagentExecutor 说明

### 可选更新
- `docs/executive-summary.md`: 如果 Batch D 成功集成，更新执行层架构

---

## 7. Git 策略

- 每个批次完成后 commit
- Commit message 格式：`Deer-Flow: [Batch X] 简短描述`
- 全部完成后 push 到 origin/main

---

## 8. 成功标准

本轮成功的定义：
1. ✅ 计划文档完成
2. ✅ Batch A + B 落地（核心封装 + 状态存储）
3. ✅ 测试覆盖核心路径
4. ✅ 文档最小更新
5. ✅ Git push 完成

Batch C + D 是**可选项**：
- 如果适合当前架构，落地
- 如果不适合，明确记录原因并跳过

---

## 9. 时间估算

| 批次 | 预计工时 | 优先级 |
|------|---------|--------|
| Batch A | 2-3 小时 | P0 |
| Batch B | 2-3 小时 | P0 |
| Batch C | 1-4 小时（或 1 小时决策不做） | P1 |
| Batch D | 3-4 小时（或跳过） | P1 |

**总计**: 4-6 小时（只做 P0）或 8-14 小时（全做）

**本轮目标**: 完成 P0 (Batch A + B) + 评估 C/D 可行性

---

## 10. 回退方案

如果任何批次遇到问题：
1. **代码回退**: `git revert` 对应 commit
2. **功能禁用**: 通过 feature flag 禁用新功能
3. **文档说明**: 在本文档记录原因

**核心原则**: 不影响现有主链稳定性

---

## 11. 执行结果 (2026-03-24 更新)

### Batch A: SubagentExecutor 封装 ✅ 完成

**实施状态**: 已完成
**测试**: 16/16 通过
**文件**:
- `runtime/orchestrator/subagent_executor.py` (新增，15KB)
- `tests/orchestrator/test_subagent_executor.py` (新增，12KB)

**核心能力**:
- SubagentConfig / SubagentResult / SubagentExecutor 类
- 工具权限隔离（allowed_tools / disallowed_tools）
- 统一 task_id / timeout / status / result handle
- 内存缓存 + 文件持久化混合
- 16 个单元测试覆盖核心路径

---

### Batch B: 热状态存储 + 持久化真值 ✅ 完成

**实施状态**: 已完成
**测试**: 16/16 通过
**文件**:
- `runtime/orchestrator/subagent_state.py` (新增，14KB)
- `tests/orchestrator/test_subagent_state.py` (新增，12KB)

**核心能力**:
- SubagentStateManager 类
- 内存缓存（热状态）+ 文件持久化（真值）混合
- 重启后可从磁盘恢复终态
- 线程安全的并发操作
- 16 个单元测试覆盖核心路径

---

### Batch C: 调度/执行分离试点 ❌ 明确不做

**决策**: 不做
**原因**:
1. 现有 `issue_lane_schemas.py` 已定义清晰契约
2. 现有 `spawn_execution.py` / `sessions_spawn_bridge.py` 已处理执行
3. Python GIL 限制，双线程池收益有限
4. 当前 subagent 天然隔离，不需要额外线程池

**文档记录**: 本章节

---

### Batch D: 最小集成到现有执行路径 ⏸️ 暂缓

**决策**: 暂缓（不破坏现有主链）
**原因**:
1. Batch A/B 已提供独立封装层
2. 现有执行路径稳定，不需要立即集成
3. 可等待实际使用场景驱动集成

**后续**: 当有明确使用场景时，再考虑集成

---

## 12. 下一步

1. ✅ 阅读 intel 文档，理解 Deer-Flow 核心机制
2. ✅ 创建本计划文档
3. ✅ 实施 Batch A: SubagentExecutor 封装
4. ✅ 实施 Batch B: 热状态存储
5. ✅ 评估 Batch C/D 可行性（C 不做，D 暂缓）
6. ⏳ 更新 CURRENT_TRUTH 文档
7. ⏳ Git commit + push

---

**创建时间**: 2026-03-24
**作者**: Zoe (基于 Deer-Flow intel 分析)
**状态**: Batch A/B 完成，C 明确不做，D 暂缓
**更新时间**: 2026-03-24 22:00
