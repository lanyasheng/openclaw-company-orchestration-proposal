# 路线图：P0 / P1 / P2

## 结论先行

**路线图不是按“技术酷炫度”排优先级，而是按“先统一主线、再跑真实业务、最后再上重型能力”排序。**

---

## P0：主线重置 + Trading 最小闭环

### 目标

把仓库从“零散验证资产集合”重置为“workflow engine 方案仓”，并让 `workspace-trading` 成为首个真实落地场景。

### 必交付

1. README / 执行摘要 / 主方案文档完成重写
2. 五层架构口径冻结
3. task registry / state machine / callback 语义冻结
4. 文档结构分层：主线 / supporting / validation
5. `workspace-trading` 选定 1 条 dry-run 或 shadow-run 流程

### 推荐流程

- 盘前 preflight
- 盘中风险守门
- 盘后回执与总结

### P0 完成标准

- 新人 5 分钟内能看懂仓库主线
- `subagent` / watcher / human-gate 的边界不再混乱
- 至少 1 条 Trading 流程进入 workflow engine 视角
- 所有“已验证”与“未验证”边界写清楚

---

## P1：控制层可复用 + Trading Pilot 稳定化

### 目标

让 workflow engine 从“能说清楚”变成“能复用”。

### 必交付

1. `subagent / browser / message / cron` adapter contract
2. CHAIN / HUMAN_GATE / FAILURE_BRANCH 模板固化
3. timeline / observability / escalation / retry 基线
4. Trading pilot 稳定化 + 回退开关
5. human-gate / callback / outbox 进入控制层标准能力

### 有条件交付

以下能力只有在真实验证通过后才进入：
- `parallel`
- `join`
- 更复杂失败补偿树

### P1 完成标准

- 模板与状态机可被复用
- Trading pilot 能稳定跑
- callback、审计、证据链不依赖单个 POC

---

## P2：Selective Durability + 安全层策略化

### 目标

只把真正值得重型化的链路升级，而不是全仓库进入基础设施改造期。

### 必交付

1. 识别跨天、强恢复、强审计场景
2. 决定哪些流程需要 Temporal 级 durable execution
3. 安全层进入策略化：policy / allowlist / isolation / approval trail
4. 明确多业务场景扩展边界

### 不做什么

- 不全量迁移到 Temporal
- 不在没有业务证据时自研通用 DAG 平台
- 不让 LangGraph 进入公司级 backbone 位置

### P2 完成标准

- 重型 runtime 只服务高价值链路
- 所有升级均可 cutover / rollback
- 安全层不再只是原则，而是制度化能力

---

## 最终节奏

```text
P0：把仓库主线和首条真实业务跑通
P1：把控制层做成可复用能力
P2：只把必须重型化的部分升级
```

**先统一，后复用，再重型化。**
