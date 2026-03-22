# Technical Debt & Backlog (2026-03-22)

> **版本**: v8 (2026-03-22)
>
> **定位**: 收敛已知优化点/技术债务，避免在快速迭代中丢失
>
> **状态**: 活文档，随迭代更新

---

## 0. Executive Summary

v8 实现了 **Real Execute Mode + Auto-Trigger Consumption** 的最小闭环。

本文档收敛在 v1-v8 迭代中识别的优化点，按优先级排序，供后续迭代参考。

**核心原则**:
- 不在 v8 做大重构
- 明确记录债务，避免丢失
- 后续迭代按需清偿

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
| D4 | Legacy 路径清理 | P2 | 待处理 | 2-4h |
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

## 5. 附录：v1-v8 演进摘要

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

---

**最后更新**: 2026-03-22
**维护者**: Zoe (CTO & Chief Orchestrator)
