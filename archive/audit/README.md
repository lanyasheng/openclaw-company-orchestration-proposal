# Audit Archive — 审计报告归档

> **用途**: 存放历史性审计报告，记录特定时间点的系统状态、问题归因和修复建议
> 
> **真值边界**: 审计报告是历史记录，不代表当前系统状态；对应修复可能已落地

---

## 归档文档

### ACK_GUARD_AUDIT_2026-03-21.md
- **审计范围**: trading/channel roundtable completion path, callback bridge ack-required contract
- **核心发现**: completion ack guard 实现，确保每个 completion 都留下 receipt 和 audit trail
- **状态**: ✅ 已实现 (`completion_ack_guard.py`)

### TMUX_TRADING_BUSINESS_CALLBACK_AUDIT_2026-03-21.md
- **审计范围**: tmux trading business callback 路径
- **核心发现**: tmux completion 不再只落 generic report，trading roundtable 优先读取真实 business callback payload
- **状态**: ✅ 已实现 (`tmux_terminal_receipts.py`)

---

## 审计原则

1. **一事一审计**: 每次重大修复/实现后，如有必要，写简短审计报告记录：
   - 问题归因
   - 修复方案
   - 验证结果

2. **审计不是设计文档**: 审计报告聚焦"发生了什么、为什么、怎么修的"，不是设计规范

3. **审计完成后归档**: 对应的修复落地后，审计报告移入 archive，不作为日常参考

---

## 与 CURRENT_TRUTH 的关系

- 审计报告是**历史证据链**，用于追溯决策过程
- `docs/CURRENT_TRUTH.md` 会引用关键审计的结论，但不包含详细审计过程
- 需要了解"为什么这样设计"时，可查阅对应审计报告

---

## 更新记录

- **2026-03-25**: 从 `runtime/orchestrator/` 迁移至此
