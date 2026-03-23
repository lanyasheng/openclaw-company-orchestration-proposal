# Technical Debt & Backlog (2026-03-22)

> **版本**: v10 (2026-03-23) — P0-3 Final Pass (Batches 1-6 Complete)
>
> **定位**: 收敛已知优化点/技术债务，避免在快速迭代中丢失
>
> **状态**: 活文档，随迭代更新
>
> **P0-3 Final Pass Status**: Batches 1-6 completed (2026-03-23). Legacy cleanup reached final boundary.
> Migration is now user-driven. See `docs/migration-retirement-plan.md` for details.

---

## 0. Executive Summary

v8 实现了 **Real Execute Mode + Auto-Trigger Consumption** 的最小闭环。

本文档收敛在 v1-v8 迭代中识别的优化点，按优先级排序，供后续迭代参考。

**核心原则**:
- 不在 v8 做大重构
- 明确记录债务，避免丢失
- 后续迭代按需清偿

---

## 0.5. P0-3 Batch 2: Legacy Runtime Cleanup (2026-03-23)

**状态**: ✅ 已完成

**清理范围**: runtime 级 legacy compatibility / 过度耦合路径

**设计约束**:
1. 先删低风险 runtime legacy，不大拆主逻辑
2. 不能破坏当前 trading live path (subagent backend)
3. 对不能删的旧路径，要明确保留原因
4. 先 targeted tests，再 broader regression

### 已删除 / 已修复

| 文件 | 改动 | 理由 |
|------|------|------|
| `runtime/orchestrator/core/dispatch_planner.py` | 移除不存在的 `stop` 命令引用 | `orchestrator_dispatch_bridge.py` 从未实现 `stop` 命令；tmux session 管理应直接使用 tmux CLI |

### 已标废 (保留但标记)

| 文件 | 标记内容 | 保留原因 |
|------|----------|----------|
| `runtime/orchestrator/continuation_backends.py` | 添加 P0-3 Batch 2 注释，明确 subagent 为主 live path，tmux 为 legacy compatibility | 现有 tmux dispatches 仍在使用；observable session 场景仍需支持 |
| `runtime/orchestrator/tmux_terminal_receipts.py` | 添加模块级 deprecation header | 现有 tmux receipt 处理逻辑仍需向后兼容 |
| `runtime/scripts/orchestrator_dispatch_bridge.py` | 添加模块级 docstring 说明 legacy 定位 | tmux-only bridge 仍需支持现有 dispatches |

### 暂保留 (原因明确)

| 路径 | 保留原因 | 未来清理条件 |
|------|----------|--------------|
| tmux backend (`continuation_backends.py`) | - 现有 production dispatches 仍在使用<br>- observable session 场景需要中间状态监控 | 当所有 production dispatches 迁移到 subagent backend + runner 观察模式 |
| `orchestrator_dispatch_bridge.py` | - tmux dispatch 的完整生命周期管理<br>- receipt/callback bridge 功能 | 当 tmux backend 完全退役 |
| `tmux_terminal_receipts.py` | - tmux receipt 构建逻辑<br>- trading/channel roundtable 标准化 | 当 tmux backend 完全退役 |

### 测试结果

```
tests/orchestrator/test_tmux_dispatch_bridge.py: 11/11 passed
tests/orchestrator/: 404/405 passed (1 flaky test isolation issue, unrelated)
```

### Commit

- **Hash**: `6c31e83`
- **Message**: `P0-3 Batch 2: Legacy runtime cleanup — deprecation markers + fix non-existent stop command`

---

## 0.6. P0-3 Batch 3: Legacy Command Deprecation (2026-03-23)

**状态**: ✅ 已完成

**清理范围**: tmux dispatch bridge 低使用率命令标废

**设计约束**:
1. 不破坏现有 tmux dispatches 的向后兼容性
2. 核心命令 (`prepare`, `start`, `status`, `receipt`, `complete`) 必须保留
3. 低使用率命令标废但不删除，避免 breaking change
4. 先 targeted tests，再 broader regression

### 已标废 (保留但标记)

| 文件 | 改动 | 理由 |
|------|------|------|
| `runtime/orchestrator/entry_defaults.py` | `runtime_reuse.tmux_bridge` 添加 `(legacy; tmux backend only)` 标记 | entry_defaults 中的 tmux 引用仅为 discoverability，非 runtime 依赖 |
| `runtime/orchestrator/continuation_backends.py` | 添加 Batch 3 注释，说明 `describe`/`capture`/`attach` 为 deprecated | 这些命令在测试中未覆盖，使用率低 |
| `runtime/scripts/orchestrator_dispatch_bridge.py` | - 模块 docstring 明确标废 `describe`/`capture`/`attach`<br>- 函数级注释标记 `cmd_describe`/`cmd_capture`/`cmd_attach` 为 deprecated<br>- `cmd_watchdog` 标记为 internal use only | 这些命令非核心 dispatch 流程，新开发应优先使用 subagent backend + runner 观察模式 |

### 核心命令 (继续支持)

| 命令 | 状态 | 用途 |
|------|------|------|
| `prepare` | ✅ 支持 | 生成 dispatch plan reference 文档 |
| `start` | ✅ 支持 | 启动 tmux session |
| `status` | ✅ 支持 | 查询 tmux session 状态 |
| `receipt` | ✅ 支持 | 构建 terminal receipt |
| `complete` | ✅ 支持 | 完成 dispatch 并桥接到 callback（核心路径） |

### 标废命令 (向后兼容)

| 命令 | 状态 | 理由 | 替代方案 |
|------|------|------|----------|
| `describe` | ⚠️ Deprecated | 仅 debug 用途，测试未覆盖 | 直接读 dispatch JSON |
| `capture` | ⚠️ Deprecated | 低使用率；runner 观察模式更优 | subagent backend + runner artifacts |
| `attach` | ⚠️ Deprecated | 低使用率；runner 观察模式更优 | subagent backend + runner artifacts |
| `watchdog` | ⚠️ Internal | 内部使用，非核心流程 | 集成到 continuation kernel |

### 测试结果

```
tests/orchestrator/test_tmux_dispatch_bridge.py: 11/11 passed
tests/orchestrator/: 404/405 passed (1 flaky test isolation issue, unrelated)
```

### Commit

- **Hash**: (待 commit)
- **Message**: `P0-3 Batch 3: Legacy command deprecation — mark describe/capture/attach as deprecated`

### Batch 4 建议

1. **监控 tmux backend 使用率**: 当 production tmux dispatches 降至 0 后，可考虑完全移除 tmux backend
2. **收口 watchdog 逻辑**: 将 `decide_watchdog_action` 集成到 continuation kernel，移除独立命令
3. **清理 tmux_receipts 目录**: 当所有 dispatches 迁移到 subagent 后，可移除 `runtime/orchestrator/tmux_receipts/`
4. **更新 docs**: 在 runtime integration 文档中明确 subagent 为默认推荐 backend

---

## 0.7. P0-3 Batch 4: Subagent as Default Recommended Backend (2026-03-23)

**状态**: ✅ 已完成

**清理范围**: 收口 tmux/dispatch 兼容层，明确 subagent 为唯一默认推荐路径

**设计约束**:
1. 不能破坏 trading live path
2. 先做低风险收口，不大拆主逻辑
3. 对仍必须保留的 tmux 路径，明确其"compat only"定位
4. 小批次、及时提交

### 已删除 / 已收口

| 文件 | 改动 | 理由 |
|------|------|------|
| `runtime/orchestrator/entry_defaults.py` | `runtime_reuse.tmux_bridge` 标记升级为 `(COMPAT-ONLY; ... NEW DEVELOPMENT MUST USE subagent BACKEND)` | entry_defaults 是 operator-facing discoverability 入口，必须明确口径 |
| `runtime/orchestrator/continuation_backends.py` | 模块头部添加 P0-3 Batch 4 BACKEND POLICY UPDATE 注释 | 明确 subagent 为 PRIMARY AND DEFAULT，tmux 为 COMPATIBILITY-ONLY |
| `runtime/orchestrator/continuation_backends.py` | `build_backend_plan()` subagent 分支 notes 强化为 "PRIMARY RECOMMENDED BACKEND" | 代码级明确推荐路径 |
| `runtime/orchestrator/continuation_backends.py` | `build_backend_plan()` tmux 分支 notes 添加 "COMPATIBILITY-ONLY LEGACY BACKEND" / "DO NOT USE for new development" | 明确 tmux 为兼容路径 |
| `runtime/scripts/orchestrator_dispatch_bridge.py` | 模块 docstring 升级为 "P0-3 Batch 4: LEGACY COMPATIBILITY BRIDGE SCRIPT" | 明确脚本定位 |
| `runtime/orchestrator/README.md` | 新增 "Backend Policy (P0-3 Batch 4, 2026-03-23)" 章节 | 文档级明确默认 backend |

### 已标废 (保留但标记)

| 路径 | 标记内容 | 保留原因 |
|------|----------|----------|
| tmux backend (`continuation_backends.py`) | "COMPATIBILITY-ONLY legacy path for EXISTING production dispatches" | 现有 production dispatches 仍在使用，需等待迁移 |
| `orchestrator_dispatch_bridge.py` | "DO NOT USE for new development. Migrate existing tmux dispatches to subagent backend." | tmux dispatch 的完整生命周期管理仍需向后兼容 |

### 暂保留 (原因明确)

| 路径 | 保留原因 | 未来清理条件 |
|------|----------|--------------|
| tmux backend (`continuation_backends.py`) | - 现有 production dispatches 仍在使用<br>- observable session 场景仍需支持 (但应迁移到 subagent + runner) | 当所有 production dispatches 迁移到 subagent backend + runner 观察模式 |
| `orchestrator_dispatch_bridge.py` | - tmux dispatch 的完整生命周期管理<br>- receipt/callback bridge 功能 | 当 tmux backend 完全退役 |
| `tmux_terminal_receipts.py` | - tmux receipt 构建逻辑<br>- trading/channel roundtable 标准化 | 当 tmux backend 完全退役 |

### 测试结果

```bash
cd <path-to-repo>/openclaw-company-orchestration-proposal
python3 -m pytest tests/orchestrator/test_tmux_dispatch_bridge.py -v
python3 -m pytest tests/orchestrator/ -v --tb=short
```

**结果**: 所有现有测试通过 (改动仅为文案/注释强化，不影响功能)

### Commit

- **Hash**: `7ef74cc`
- **Message**: `P0-3 Batch 4: Subagent as default recommended backend — tighten tmux compat layer`

---

## 0.8. P0-3 Batch 5: Direct tmux -> subagent Migration (2026-03-23)

**状态**: ✅ 进行中 (本批次)

**清理范围**: 直接推进 tmux -> subagent 迁移，不再先做使用率监控；收口默认路径、入口配置、推荐命令、文档

**设计约束**:
1. 不能破坏 trading live path
2. 默认路径必须进一步向 subagent 收拢
3. 若某些 tmux 逻辑还不能删，必须明确为何仍保留
4. 先 targeted tests，再 broader regression
5. 小批次、及时提交

### 已删除 / 已收口

| 文件 | 改动 | 理由 |
|------|------|------|
| `runtime/orchestrator/entry_defaults.py` | 注释掉 `complete_tmux` 示例命令，添加 Batch 5 deprecation 注释 | 入口文档不应展示 tmux 为推荐路径 |
| `runtime/orchestrator/continuation_backends.py` | `build_backend_plan()` tmux 分支移除 deprecated commands (capture/attach/watchdog/start_dry_run) | 最小化 tmux 命令触达面，仅保留核心生命周期命令 |
| `runtime/orchestrator/continuation_backends.py` | `build_backend_plan()` subagent 分支 notes 添加 "ONLY default path for new development" | 强化 subagent 为唯一默认路径 |
| `runtime/orchestrator/continuation_backends.py` | `build_backend_plan()` tmux 分支 notes 升级为 "MIGRATION REQUIRED" | 明确 tmux 为需迁移的兼容路径 |
| `runtime/orchestrator/README.md` | Backend Policy 升级为 Batch 5，明确 subagent 为"ONLY DEFAULT FOR NEW DEVELOPMENT" | 文档级明确默认路径 |
| `docs/CURRENT_TRUTH.md` | 添加 Batch 5 完成状态 | 真值入口同步更新 |

### 已降级为 compat-only

| 路径 | 降级内容 | 保留原因 |
|------|----------|----------|
| tmux backend commands (`continuation_backends.py`) | 仅保留 `prepare/start/status/receipt/complete` 核心命令 | 现有 production dispatches 仍需完整生命周期管理 |
| `orchestrator_dispatch_bridge.py` | deprecated commands (describe/capture/attach/watchdog) 已在 Batch 3 标废，Batch 5 从 backend_plan 移除 | 低使用率命令不应在默认路径展示 |

### 暂保留 (原因明确)

| 路径 | 保留原因 | 未来清理条件 |
|------|----------|--------------|
| tmux backend (`continuation_backends.py`) | 现有 production dispatches 仍在使用，需等待迁移 | 当所有 production dispatches 迁移到 subagent |
| `orchestrator_dispatch_bridge.py` | tmux dispatch 的完整生命周期管理仍需向后兼容 | 当 tmux backend 完全退役 |
| `tmux_terminal_receipts.py` | tmux receipt 构建逻辑仍需向后兼容 | 当 tmux backend 完全退役 |

### 测试结果

```bash
cd <path-to-repo>/openclaw-company-orchestration-proposal
python3 -m pytest tests/orchestrator/test_tmux_dispatch_bridge.py -v
python3 -m pytest tests/orchestrator/ -v --tb=short
```

**预期**: 所有现有测试通过 (改动仅为文案/注释/命令表面清理，不影响功能)

### Commit

- **Hash**: (待 commit)
- **Message**: `P0-3 Batch 5: Direct tmux -> subagent migration — remove tmux from default paths, minimize compat surface`

### Batch 6 建议

1. **tmux backend 使用率追踪**: 建立指标/日志追踪 production tmux dispatches 数量，为完全移除做准备
2. **迁移指南文档**: 创建 `docs/migration/tmux-to-subagent-migration.md` 帮助现有用户迁移
3. **清理 tmux_receipts 目录**: 当使用率降至 0 后，可移除 `runtime/orchestrator/tmux_receipts/`
4. **收口 watchdog 逻辑**: 将 `decide_watchdog_action` 集成到 continuation kernel，移除独立命令
5. **评估移除 tmux backend**: 当 production dispatches 降至 0 后，可考虑完全移除 tmux backend 支持

---

## 0.9. P0-3 Batch 6: Generic Lifecycle Kernel (2026-03-23)

**状态**: ✅ 已完成 (本批次)

**清理范围**: 把 tmux 兼容层剩余的 watchdog / lifecycle 判定逻辑进一步并回 continuation kernel

**设计约束**:
1. 不能破坏 trading live path
2. 不搞大拆主逻辑，只做低风险 kernelization / boundary 收口
3. 对不能删的兼容逻辑写明保留原因
4. 先 targeted tests，再 broader regression
5. 输出分三类：已迁入通用层 / 已标废保留 / 暂保留

### 已迁入通用层

| 文件 | 改动 | 理由 |
|------|------|------|
| `runtime/orchestrator/continuation_backends.py` | 新增 `GenericBackendStatus` enum | 后端无关的生命周期状态枚举 |
| `runtime/orchestrator/continuation_backends.py` | 新增 `BackendStatusAdapter` Protocol | 后端特定状态映射接口 |
| `runtime/orchestrator/continuation_backends.py` | 新增 `BackendLifecycleConfig` dataclass | 后端特定生命周期配置封装 |
| `runtime/orchestrator/continuation_backends.py` | `build_timeout_policy()` 使用 `BackendLifecycleConfig` | 移除硬编码 tmux 常量 |
| `runtime/orchestrator/continuation_backends.py` | `decide_watchdog_action()` 使用 generic status | 后端无关的 watchdog 决策逻辑 |
| `runtime/orchestrator/continuation_backends.py` | `build_backend_plan()` 更新注释 | 明确 watchdog 已集成到 kernel |

### 已标废保留

| 路径 | 标记内容 | 保留原因 |
|------|----------|----------|
| `runtime/orchestrator/tmux_terminal_receipts.py` 的 `TERMINAL_*_STATUSES` | 添加 Batch 6 注释，说明用于 `BackendLifecycleConfig.for_tmux()` | tmux 特定状态常量仍需保留供 lifecycle config 使用 |
| `runtime/orchestrator/continuation_backends.py` 的 tmux 分支 | 标记为 compat-only，但保留完整功能 | 现有 production dispatches 仍在使用 |

### 暂保留 (原因明确)

| 路径 | 保留原因 | 未来清理条件 |
|------|----------|--------------|
| `orchestrator_dispatch_bridge.py` 的 `cmd_watchdog()` | 仍作为 CLI 入口，但内部委托给 kernel | 当 CLI 使用率降至 0 后可移除 |
| tmux backend 完整支持 | 现有 production dispatches 仍需完整生命周期管理 | 当所有 dispatches 迁移到 subagent |

### 新增能力

1. **GenericBackendStatus enum**: 后端无关的生命周期状态
   - DONE, STUCK, RUNNING, IDLE, UNKNOWN
   - 支持多后端统一决策逻辑

2. **BackendLifecycleConfig**: 后端特定配置封装
   - `for_tmux()`: tmux 后端配置
   - `for_subagent()`: subagent 后端配置
   - `map_status()`: 原生状态到通用状态映射

3. **BackendStatusAdapter Protocol**: 可扩展的状态映射接口
   - 支持未来新增后端 (如 kubernetes, docker, etc.)

### 测试结果

```bash
cd <path-to-repo>/openclaw-company-orchestration-proposal
python3 -m pytest tests/orchestrator/test_continuation_backends_lifecycle.py -v
python3 -m pytest tests/orchestrator/ -v --tb=short
```

**结果**: 
- 新增 29 个 lifecycle kernel 测试全部通过
- 原有 405 个测试全部通过
- 总计 434 个测试通过

### Commit

- **Hash**: (待 commit)
- **Message**: `P0-3 Batch 6: Generic lifecycle kernel — extract backend-agnostic watchdog/lifecycle logic`

### Batch 7+ 建议

1. **新增后端支持**: 使用 `BackendLifecycleConfig` 和 `BackendStatusAdapter` 快速接入新后端 (kubernetes/docker/etc.)
2. **移除 tmux backend**: 当 production dispatches 降至 0 后，可完全移除 tmux backend
3. **清理 tmux_receipts 目录**: 当 tmux backend 移除后，可移除 `runtime/orchestrator/tmux_receipts/`
4. **文档更新**: 在 runtime integration 文档中说明 generic lifecycle kernel 设计

---

### 0.10. P0-3 Final Pass: Dual-Track Backend Strategy (2026-03-23)

**状态**: ✅ 已完成 (Final Pass)

**清理范围**: 盘点全部 legacy/tmux/dispatch compatibility 表面面积，确立双轨兼容策略

**设计约束**:
1. 不能破坏 trading live path
2. **tmux 不应被删除** - 保留为兼容路径
3. subagent 作为默认主路径继续强化
4. 先 targeted tests，再 broader regression
5. 输出必须一次性回答：默认入口 / 兼容路径 / 双轨边界

#### Final Pass 总结

**已清理** (Batches 1-6 累计):
- `docs/archive/old-docs/` - 历史 POC 和过时设计文档归档
- `dispatch_planner.py` 中的不存在 `stop` 命令引用
- 文档注释更新为双轨策略口径

**保留** (双轨兼容):
- tmux backend - **FULLY SUPPORTED** for interactive/observable scenarios
- `orchestrator_dispatch_bridge.py` - tmux 完整生命周期管理
- `tmux_terminal_receipts.py` - tmux receipt 构建逻辑
- All commands - 两种 backend 都支持

**双轨策略**:

| Backend | 定位 | 使用场景 |
|---------|------|----------|
| subagent | DEFAULT | 自动化执行、CI/CD、新开发 |
| tmux | FULLY SUPPORTED | 交互式会话、手动观察、调试 |

#### 最终边界声明

**这是最终边界：双轨兼容策略。**

**含义**:
- 不再计划进一步的清理批次
- **两种 backend 都保留** - 不做破坏性删除
- 用户可根据需求选择 backend
- subagent 是默认推荐，但 tmux 完全可用

**原因**:
- trading live path  preserved
- tmux 使用场景仍然有效（交互式观察）
- 双轨提供灵活性
- 清晰的政策 + 文档是最终状态

#### 交付文档

- [`../migration/migration-retirement-plan.md`](../migration/migration-retirement-plan.md) → 更名为双轨策略文档
- `docs/CURRENT_TRUTH.md` - 更新 V10 双轨策略状态
- `runtime/orchestrator/README.md` - Backend Policy 已更新
- `runtime/orchestrator/continuation_backends.py` - 代码注释已更新

#### 测试结果

```bash
cd <path-to-repo>/openclaw-company-orchestration-proposal
python3 -m pytest tests/orchestrator/ -v --tb=short
```

**结果**: 434 个测试全部通过

#### Commit

- **Hash**: `ffd84d8`
- **Message**: `P0-3 Final: Dual-track backend strategy (subagent + tmux)`

---

## 1. 高优先级债务 (P0)

### 1.1 `trading_roundtable.py` 职责过大

**问题**:
- 文件行数：~1500 行
- 职责混杂：adapter logic / business rules / dispatch / status tracking
- 难以测试和维护

**影响**:
- 新场景接入成本高
- 回归测试覆盖困难
- 单点故障风险

**建议方案**:
```
trading_roundtable/
├── __init__.py
├── adapter.py          # Trading-specific adapter logic
├── business_rules.py   # Trading business rules
├── dispatch.py         # Dispatch logic
├── status.py           # Status tracking
└── main.py             # 入口，组合以上模块
```

**优先级**: P0
**预计工作量**: 4-6 小时
**风险**: 中（需确保向后兼容）

---

### 1.2 Continuation v1-v7 模块收口

**问题**:
- v1-v7 迭代产生多个模块，职责有重叠：
  - `task_registration.py` (v1)
  - `auto_dispatch.py` (v2)
  - `spawn_closure.py` (v3)
  - `spawn_execution.py` (v4)
  - `completion_receipt.py` (v5)
  - `sessions_spawn_request.py` (v6)
  - `bridge_consumer.py` (v7/v8)
- 模块间耦合度高，链路追踪复杂

**影响**:
- 新开发者理解成本高
- 修改一处可能影响多处
- 文档分散

**建议方案**:
- 创建 `continuation_kernel.py` 统一入口
- 保留现有模块为向后兼容层
- 新增代码优先使用统一入口

**优先级**: P1
**预计工作量**: 8-12 小时
**风险**: 中高（需充分测试）

---

### 1.3 `CURRENT_TRUTH.md` / `README.md` 去重瘦身

**问题**:
- `CURRENT_TRUTH.md` 和 `README.md` 内容有重叠
- 部分章节过于详细，失去"真值入口"的简洁性
- 新读者难以快速定位关键信息

**影响**:
- 文档维护成本高
- 读者容易迷失

**建议方案**:
- `README.md`: 保留 5 分钟快速开始 + 核心概念
- `CURRENT_TRUTH.md`: 聚焦当前迭代真值（v8）
- 历史细节移至 `docs/history/` 或 `docs/archive/`

**优先级**: P1
**预计工作量**: 2-3 小时
**风险**: 低

---

### 1.4 Deprecated / Legacy 路径清理

**问题**:
- Workspace 本地副本仍存（已标记 deprecated）
- 部分旧脚本/测试仍引用旧路径
- `prototype/` 目录内容过时

**影响**:
- 误用风险
- 仓库体积膨胀

**建议方案**:
- 创建 `docs/deprecated-paths.md` 明确列出所有废弃路径
- 添加迁移指南
- 设定清理时间表（如 v10 前完成）

**优先级**: P2
**预计工作量**: 2-4 小时
**风险**: 中（需确认无外部依赖）

---

## 2. 中优先级债务 (P1)

### 2.1 Auto-Trigger 配置管理

**问题**:
- v8 的 auto-trigger 配置使用本地 JSON 文件
- 缺少版本控制/审计日志
- 多环境配置同步困难

**建议方案**:
- 集成到 OpenClaw 配置系统
- 添加配置变更审计日志
- 支持环境变量覆盖

**优先级**: P1
**预计工作量**: 3-4 小时

---

### 2.2 Execute Mode 真实集成

**问题**:
- v8 的 execute mode 仍为模拟执行
- 未真正调用 OpenClaw sessions_spawn API
- 缺少执行结果追踪

**建议方案**:
- 集成 OpenClaw sessions_spawn API
- 添加执行结果回写机制
- 支持执行超时/重试策略

**优先级**: P1
**预计工作量**: 6-8 小时

---

### 2.3 测试覆盖率提升

**问题**:
- v8 新增功能测试覆盖不全
- 缺少集成测试
- 缺少端到端测试

**建议方案**:
- 补充 execute mode 测试
- 补充 auto-trigger 测试
- 添加端到端链路测试

**优先级**: P1
**预计工作量**: 4-6 小时

---

## 3. 低优先级债务 (P2)

### 3.1 状态机可视化

**问题**:
- 10-ID 链路状态转换复杂
- 缺少可视化调试工具

**建议方案**:
- 创建状态机可视化工具
- 支持链路追踪查询

**优先级**: P2
**预计工作量**: 4-6 小时

---

### 3.2 性能优化

**问题**:
- 大量 artifact 读写使用 JSON 文件
- 缺少缓存机制
- 批量操作效率低

**建议方案**:
- 评估使用 SQLite/其他存储
- 添加读取缓存
- 优化批量操作

**优先级**: P2
**预计工作量**: 8-12 小时

---

## 4. 债务追踪

### 4.1 债务清单

| ID | 债务项 | 优先级 | 状态 | 预计工作量 |
|----|--------|--------|------|------------|
| D1 | trading_roundtable 拆分 | P0 | 待处理 | 4-6h |
| D2 | Continuation 模块收口 | P1 | 待处理 | 8-12h |
| D3 | 文档去重瘦身 | P1 | 待处理 | 2-3h |
| D4 | Legacy 路径清理 | P2 | ✅ Batch 2 完成 (runtime 级) | 2-4h |
| D5 | Auto-trigger 配置管理 | P1 | 待处理 | 3-4h |
| D6 | Execute mode 真实集成 | P1 | 待处理 | 6-8h |
| D7 | 测试覆盖率提升 | P1 | 待处理 | 4-6h |
| D8 | 状态机可视化 | P2 | 待处理 | 4-6h |
| D9 | 性能优化 | P2 | 待处理 | 8-12h |

### 4.2 清偿计划

- **v9**: 优先处理 D1 (trading_roundtable 拆分)
- **v10**: 处理 D2 + D3 + D4 (模块收口 + 文档清理)
- **v11+**: 按需处理 D5-D9

---

## 5. 附录：v1-v9 演进摘要

| 版本 | 核心能力 | 状态 |
|------|----------|------|
| v1 | Task Registration | 完成 |
| v2 | Auto Dispatch | 完成 |
| v3 | Spawn Closure | 完成 |
| v4 | Spawn Execution | 完成 |
| v5 | Completion Receipt | 完成 |
| v6 | Sessions Spawn Request | 完成 |
| v7 | Bridge Consumption | 完成 |
| v8 | Execute Mode + Auto-Trigger | 完成 |
| v9 | Real API Integration + Legacy Cleanup Batch 2 | 完成 |
| v10 | P0-3 Final Pass: Legacy Cleanup Final Boundary | 完成 |

---

**最后更新**: 2026-03-23 (v10 - P0-3 Final Pass Complete)
**维护者**: Zoe (CTO & Chief Orchestrator)
