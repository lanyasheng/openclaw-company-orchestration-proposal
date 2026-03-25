# Design Seams Archive — 设计 seam 归档

> **用途**: 存放已实现的设计 seam 文档，记录关键设计决策和契约定义
> 
> **真值边界**: 这些设计已实现到 runtime 中，文档本身作为历史参考；当前行为以 runtime 实现为准

---

## 归档文档

### UNIVERSAL_TERMINAL_CALLBACK_CONTRACT_2026-03-22.md
- **设计目标**: 统一 tmux terminal callback 路径，支持多 adapter 复用
- **核心分层**:
  1. backend terminal receipt (后端终态)
  2. business callback payload (业务 closeout 真值)
  3. adapter-scoped payload (adapter 私有字段)
  4. canonical callback envelope (统一信封)
- **状态**: ✅ 已实现 (`tmux_terminal_receipts.py`, `orchestrator_callback_bridge.py`)

### UNIVERSAL_SCENARIO_ONBOARDING_SEAM_2026-03-22.md
- **设计目标**: 推进新 scenario 接入的通用 seam，降低接入门槛
- **核心结论**: 非 trading scenario 默认复用 `channel_roundtable` adapter
- **最小接入包**: `orchestrator/examples/generic_channel_roundtable_onboarding_kit.md`
- **状态**: ✅ 已实现 (`orch_command.py`, `channel_roundtable.py`)

---

## 什么是 Design Seam

**Design Seam** 是指：
- 连接不同模块/系统的**最小契约边界**
- 允许两侧独立演进，只要守住 seam 的接口约定
- 通常是"足够通用、足够简单、足够稳定"的设计

本仓的关键 design seams：
- Terminal callback contract (后端 → 编排器)
- Scenario onboarding seam (新场景 → 编排器)
- Completion receipt contract (执行器 → 编排器)
- Dispatch plan contract (编排器 → 执行器)

---

## 与运行时实现的关系

| Design Seam 文档 | 运行时实现 |
|-----------------|-----------|
| `UNIVERSAL_TERMINAL_CALLBACK_CONTRACT` | `tmux_terminal_receipts.py`, `completion_ack_guard.py` |
| `UNIVERSAL_SCENARIO_ONBOARDING_SEAM` | `channel_roundtable.py`, `orch_command.py` |

---

## 何时查阅

- ✅ 需要理解某个设计决策的背景和权衡
- ✅ 需要扩展新 adapter/scenario，参考既有 seam 设计
- ✅ 审计设计一致性和契约边界

- ❌ 日常操作 (见 `docs/OPERATIONS.md`)
- ❌ 了解当前系统行为 (见 `docs/CURRENT_TRUTH.md` + runtime 实现)

---

## 更新记录

- **2026-03-25**: 从 `runtime/orchestrator/` 迁移至此
