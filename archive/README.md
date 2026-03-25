# Archive Index — 归档目录索引

> **用途**: 存放历史性、非 canonical、已完成的文档和代码
> 
> **何时查阅**: 需要了解历史决策过程、审计轨迹、已废弃设计时参考
> 
> **真值边界**: 本文档内容仅供参考，不作为当前系统行为依据；当前真值见 `docs/CURRENT_TRUTH.md` + `runtime/` 实现

---

## 目录结构

```
archive/
├── README.md              # 本索引
├── audit/                 # 审计报告 (历史性的 ack/callback/validator 审计)
├── design-seams/          # 设计 seam 文档 (已实现的设计方案)
├── legacy-scripts/        # 遗留脚本 (已被新实现替代)
├── legacy-tests/          # 遗留测试 (已被新测试替代)
├── old-docs/              # 旧版本文档 (e.g., partial-continuation-kernel v5-v9)
├── poc/                   # 概念验证 (LOB/bridge/subagent 等 POC)
└── prototype/             # 原型实现 (早期 callback-driven orchestrator 等)
```

---

## 归档原则

### 什么进入 archive
- ✅ 已完成的审计报告 (e.g., ACK_GUARD_AUDIT, CALLBACK_AUDIT)
- ✅ 已实现的设计 seam 文档 (e.g., UNIVERSAL_*_CONTRACT)
- ✅ 历史版本文档 (e.g., partial-continuation-kernel v5-v9)
- ✅ 早期 POC/prototype 代码
- ✅ 已被新实现替代的遗留脚本/测试

### 什么不进入 archive
- ❌ 当前 canonical 文档 (见 `docs/CURRENT_TRUTH.md`, `docs/OPERATIONS.md`)
- ❌ 仍在演进的设计计划 (见 `docs/plans/`)
- ❌ 当前运行时实现 (见 `runtime/`, `orchestration_runtime/`)
- ❌ 当前测试集 (见 `tests/`)

---

## 归档子目录说明

### audit/
存放历史性审计报告，包括：
- Ack guard 审计
- Callback bridge 审计
- Validator 审计
- 事故归因证据链审计

> 这些审计报告记录了特定时间点的系统状态和问题归因，对应的修复可能已落地。

### design-seams/
存放已实现的设计 seam 文档，包括：
- Universal terminal callback contract
- Universal scenario onboarding seam
- 其他已落地的设计契约

> 这些文档描述的设计已实现到 runtime 中，文档本身作为历史参考保留。

### old-docs/
存放历史版本文档，例如：
- `partial-continuation-kernel-v5.md` 到 `v9.md`

> 这些是 continuation kernel 的迭代版本，当前真值见 `runtime/orchestrator/continuation_*.py`

### poc/
存放概念验证代码：
- `lobster_minimal_validation/` - 最小验证 POC
- `official_lobster_bridge/` - Lobster 桥接 POC
- `subagent_bridge_sim/` - Subagent 桥接模拟 POC

### prototype/
存放早期原型实现：
- `callback_driven_orchestrator_v1/` - 回调驱动编排器 v1 原型

### legacy-scripts/
存放已被新实现替代的脚本。

### legacy-tests/
存放已被新测试替代的测试。

---

## 与 canonical 文档的关系

| 类型 | 位置 | 用途 |
|------|------|------|
| **当前真值** | `docs/CURRENT_TRUTH.md` | 了解"今天系统实际如何工作" |
| **操作指南** | `docs/OPERATIONS.md` | 日常操作和故障排查 |
| **架构说明** | `docs/architecture-layering.md` | 分层架构设计 |
| **执行摘要** | `docs/executive-summary.md` | 高层业务摘要 |
| **设计计划** | `docs/plans/` | 正在演进的设计方案 |
| **历史参考** | `archive/` | 历史决策/审计/版本文档 |

---

## 更新记录

- **2026-03-25**: Batch B 文档治理 — 建立归档索引，迁移审计和设计 seam 文档
