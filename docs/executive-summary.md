# 执行摘要：OpenClaw Workflow Engine 总方案

> **角色**: 📘 **5 分钟方案总览** — 理解"为什么选这个方向"和"五层架构"
>
> **何时阅读**:
> - 想快速理解整体架构设计思路
> - 需要了解决策背景和排除的方向
> - 向新成员解释仓库定位
>
> **与 CURRENT_TRUTH 关系**: 本文档讲"为什么这样设计"；`CURRENT_TRUTH.md` 讲"今天实际如何工作"；两者配合阅读
>
> **日期**: 2026-03-20  
> **口径**: v3.1，补入 live continuation / whitelist / tmux backend 真值

## 一句话结论

**这个仓库以后应被定义为 OpenClaw 公司级 workflow engine 方案仓。当前正确方向不是让 human-gate 或零散 POC 继续充当主线，而是明确五层架构：官方底座层、编排控制层、执行层、业务场景层，以及可选安全层。**

---

## 最终决策

### 我们现在怎么做

1. **官方底座层**：复用 `OpenClaw 原生能力 + Lobster 官方 workflow shell`
2. **编排控制层**：自建公司协议，统一 `task registry / state machine / callback / timeline / retry / escalation`
3. **执行层**：以 `subagent` 为默认内部执行主链，`browser / message / cron` 为标准 activity
4. **业务场景层**：先落地 `workspace-trading`
5. **可选安全层**：把 human-gate、审计、隔离、幂等、回退作为横切能力逐步补齐

### 我们现在不做什么

- 不自研通用 DAG 平台
- 不把 `taskwatcher` 当 backbone
- 不让 LangGraph 接管公司级执行总线
- 不在 P0 就把 Temporal 全量引入
- 不把 human-gate 插件或单个 POC 写成仓库主叙事

---

## 当前成熟度（2026-03-20）

这份执行摘要也要补齐本轮 live 真值，而不是停留在 2026-03-19 的纯方案口径：

- `trading_roundtable` 已切到 **default auto-continue within low-risk boundary**
- `orch_product onboard/run/status` 成为 trading 主入口，并会落地默认自动推进配置
- `channel_roundtable` 已落地为通用最小适配器，但其他频道默认仍按 allowlist / safe semi-auto 管理
- 当前 `Temporal vs LangGraph｜OpenClaw 公司级编排架构` 频道已成为**第二个真实场景**
- trading 侧当前策略是：**clean PASS + low-risk continuation 默认 `triggered`；真实资金 / 不可逆线上动作仍停在 gate**
- `tmux` 已成为**正式可选 continuation backend**，但 trading 默认自动推进主链为 `subagent`

一句话：**仓库已经从纯方案/POC 推进到“trading 默认自动推进 + 其他频道按 allowlist 管理”的混合成熟态。**

---

## 五层架构

```text
业务场景层
└─ workspace-trading（首个落地）

编排控制层
└─ templates / registry / state machine / callback / timeline / routing

执行层
└─ subagent / browser / message / cron / external async / future Temporal

官方底座层
└─ OpenClaw session/tool/channel/plugin primitives
└─ Lobster workflow shell / approval / invoke bridge

可选安全层（横切）
└─ human-gate / policy / audit / isolation / idempotency / rollback
```

**关键判断**：
- 官方底座层解决“原生能力与官方能力能做什么”
- 编排控制层解决“公司级 workflow 怎么统一管理”
- 执行层解决“谁去真正跑任务”
- 业务场景层解决“先在哪个真实业务里落地”
- 可选安全层解决“什么时候需要额外守门与审计”

---

## 为什么现在选这个方向

### 1. 已验证事实支持“薄控制层”而不是“重做引擎”

已验证：
- `subagent` 是默认内部长任务主链
- Lobster 适合做薄工作流壳，尤其是顺序链、approval、tool bridge
- `taskwatcher` 更像 external watcher / reconciler，而不是 backbone
- callback / terminal / ack 的语义必须分离，不能混写成一个状态

### 2. 当前最大问题不是“缺某个引擎”，而是“缺统一控制面”

如果没有控制层：
- 状态无法跨 runtime 对齐
- 幂等 callback 无法沉淀为标准能力
- human-gate 只能做局部技巧，无法成为公司协议
- 业务 workflow 无法复制，只能复制脚本

### 3. 直接上重型方案的代价现在不值

| 方案 | 当前不选为主线的原因 |
|------|----------------------|
| Temporal-first | 成本高，worker/determinism/versioning 负担过重 |
| LangGraph-first | 更适合 agent 内部 reasoning，不适合公司级 backbone |
| 自研 DAG-first | 需求尚未稳定，过早抽象风险最大 |

---

## 已验证 / 未验证

### 已验证什么

| 主题 | 结论 |
|------|------|
| Lobster 顺序链 | 可作为 P0/P1 workflow shell |
| Lobster approval | 可直接支撑 human-gate 类中断/恢复 |
| `message/browser` bridge | 在官方能力上接线难度低 |
| callback status | `terminal ≠ callback sent ≠ acked` 已有明确契约 |
| P0 最小验证 | human-gate、failure-branch、subagent bridge 均已有 repo 级证据 |
| live continuation 最小接线 | trading + 当前架构频道已形成两条真实场景 |
| `tmux` backend 选项 | 已进入正式口径，但当前仍按收紧边界使用 |

### 还没验证什么

| 主题 | 结论 |
|------|------|
| Lobster → 真实 `subagent` 完整闭环 | 还没跑真实接线 |
| 真并发 / 真 join | 不能提前承诺 |
| 原生 failure-branch 语义 | 目前更像 adapter 路线 |
| trading 通用 workflow engine 化 | `trading_roundtable` continuation 已最小落地，但还不能等同于 trading 全面 workflow 化 |
| trading clean PASS 自动续跑 | 当前只到 clean PASS 默认 `triggered`，并不等于 trading 任意结果都自动 continuation |
| `tmux` 的生产闭环程度 | trading real run 当前仍只到 dry-run，真实 artifact-backed clean PASS 仍缺 |
| 何时必须引入 Temporal | 还没有足够业务证据 |

---

## 路线图

### P0：主线重置 + 最小真实闭环

目标：**把仓库从“方案碎片 + POC”重置为“可执行的 workflow engine 方案仓”。**

交付：
- 五层架构定稿
- 主文档、执行摘要、README 重写
- task registry / state machine / callback 口径冻结
- 选 `workspace-trading` 做首条 dry-run / shadow-run 流程

### P1：控制层可复用 + Trading Pilot 稳定化

目标：**让 workflow engine 具备复用能力，而不只是一次性设计稿。**

交付：
- `subagent / browser / message / cron` adapter contract
- template 基线：chain / human-gate / failure-branch 优先
- timeline / observability / escalation 基线
- `workspace-trading` 成为首个稳定 pilot

### P2：选择性 durable execution + 安全层强化

目标：**只把真正值得重型化的链路升级。**

交付：
- 跨天、强恢复、强审计流程再评估是否引入 Temporal
- 安全层进入策略化与默认治理
- 再决定是否需要更重的 workflow runtime

---

## 对老板的直接建议

1. **把这个仓库正式定为 workflow engine 方案仓**
2. **主线只讲五层架构、验证边界、路线图和首个业务落地**
3. **human-gate 与零散 POC 全部下沉为验证资产**
4. **P0 先服务 `workspace-trading`，不要继续抽象空转**
5. **等 P1 业务证据出来，再决定 Temporal 和更重安全层的投入规模**
