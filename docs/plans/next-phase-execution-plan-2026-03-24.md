# 下一阶段执行清单 (2026-03-24)

> **文档类型**: P0/P1/P2 阶段执行计划  
> **编制日期**: 2026-03-24  
> **编制者**: Zoe (CTO & Chief Orchestrator)  
> **目标**: 把后续工作收敛成可执行的 P0/P1/P2 清单  
> **关联文档**: [`../review/orchestration-architecture-review-2026-03-24.md`](../review/orchestration-architecture-review-2026-03-24.md)

---

## 执行摘要

### 阶段划分

| 阶段 | 目标 | 预计时间 | 优先级 |
|------|------|----------|--------|
| **P0: Contract 基线** | 建立默认 planning、continuation contract、issue lane baseline、heartbeat boundary | 1-2 周 | 🔴 必须 |
| **P1: 叶子 Pilots** | 验证叶子执行增强，不破坏控制面 | 2-3 周 | 🟡 重要 |
| **P2: 选择性重型 Pilots** | 仅在高价值场景试点重型基础设施 | 4-6 周 | 🟢 可选 |

### 推荐顺序

```
P0 (1-2 周) → P1 (2-3 周) → P2 (4-6 周，按需)
```

### 并行/串行策略

| 工作流 | 并行/串行 | 理由 |
|--------|----------|------|
| P0 内部任务 | 部分并行 | planning default 与 continuation contract 可并行；issue lane 与 heartbeat boundary 可并行 |
| P0 → P1 | 串行 | P0 是 P1 的前提 (没有 contract 基线，叶子 pilot 无法标准化) |
| P1 内部任务 | 并行 | DeepAgents profile 与 SWE-agent lane 独立 |
| P1 → P2 | 串行 | P2 依赖 P1 的叶子 pilot 验证结果 |
| P2 内部任务 | 按需 | 高价值场景识别后独立试点 |

### 用户可见闭环 vs. 工程内控

| 能力 | 类型 | 说明 |
|------|------|------|
| Planning artifact 默认输出 | 用户可见 | 用户能看到结构化 planning 文档 |
| Continuation contract 标准化 | 工程内控 | 系统内部状态追踪，用户感知为"自动续推更稳定" |
| Issue lane baseline | 用户可见 | GitHub issue → patch 的完整链路 |
| Heartbeat boundary freeze | 工程内控 | 系统内部治理，用户感知为"告警更准确" |
| DeepAgents profile | 用户可见 | coding subagent 质量提升 |
| SWE-agent lane | 用户可见 | issue-to-patch 自动化 |
| Temporal pilot | 工程内控 | durable execution 后台能力 |

---

## P0: Contract 基线 (1-2 周)

### 目标

先把"为什么停、停在哪、下一步怎么接"这件事讲清并定成默认。

### 为什么先做这个

1. **当前痛点**: "agent 做完就停"不是单一问题，而是两层问题叠加
   - Agent 内部：做完当前 step 就交卷，缺少默认 planning ledger、closeout checklist、next-step policy
   - 公司级主链：`summary -> decision -> dispatch` 还没被统一成默认 continuation contract

2. **不修的后果**: 循环越多越容易噪音化，没有 planning、没有 handoff、没有 owner 时，自动化等于混乱

3. **修好的收益**: 默认回答"为什么停"不再靠聊天猜；主链知道下一步该由谁接；heartbeat 不再被误当 workflow owner

### 任务清单

#### P0-1: gstack-style planning default

**目标**: 非 trivial feature / bugfix / workflow 设计先产出 planning artifact。

**验收标准**:
- [ ] 编码/复杂文档任务默认生成 planning artifact
- [ ] Planning artifact 包含：problem reframing / scope review / engineering review / execution plan
- [ ] 下游执行、review、QA 默认消费该 artifact
- [ ] 测试覆盖：planning artifact 生成与消费链路

**预计工作量**: 4-6 小时

**风险与回退**:
- 风险：planning artifact 格式不稳定，下游消费困难
- 回退：保留旧路径兼容，逐步迁移

**依赖**: 无

**并行性**: 可与 P0-2 并行

---

#### P0-2: continuation contract v1

**目标**: 每个任务 closeout 至少带：`summary`、`decision`、`stopped_because`、`next_step`、`next_owner`、`dispatch_readiness`。

**验收标准**:
- [ ] `ContinuationContract` schema 冻结
- [ ] 所有场景适配器 (trading / channel) 注入 continuation contract
- [ ] completion receipt 包含 continuation contract 字段
- [ ] 测试覆盖：continuation contract 生成与验证

**预计工作量**: 6-8 小时

**风险与回退**:
- 风险：旧 receipt 格式不兼容
- 回退：保留旧字段兼容，新增字段可选

**依赖**: 无

**并行性**: 可与 P0-1 并行

---

#### P0-3: coding issue lane baseline

**目标**: 先冻结 `issue_to_patch.v1` 这类窄 lane 的输入输出。

**验收标准**:
- [ ] Issue lane 输入 schema 冻结 (GitHub issue URL / 内容)
- [ ] Issue lane 输出 schema 冻结 (patch file / PR description)
- [ ] 单 issue、单仓、单 acceptance 的稳定 handoff
- [ ] 测试覆盖：issue → planning → patch 完整链路

**预计工作量**: 8-12 小时

**风险与回退**:
- 风险：issue 格式多样，难以标准化
- 回退：先支持标准 GitHub issue，逐步扩展

**依赖**: P0-1 (planning default)

**并行性**: 需在 P0-1 完成后开始

---

#### P0-4: heartbeat boundary freeze

**目标**: heartbeat 只保留 wake / liveness / 巡检 / 催办 / 告警；禁止 heartbeat 写 terminal truth、直接 dispatch 下一跳、接管 gate。

**验收标准**:
- [ ] Heartbeat 职责文档化 (`docs/policies/heartbeat-boundary-policy.md`)
- [ ] 代码审查：移除 heartbeat 写 terminal state 的逻辑
- [ ] 测试覆盖：heartbeat 越界行为拦截
- [ ] 监控告警：heartbeat 越界检测

**预计工作量**: 4-6 小时

**风险与回退**:
- 风险：现有 heartbeat 逻辑耦合深，难以剥离
- 回退：标记 deprecated，逐步迁移

**依赖**: 无

**并行性**: 可与 P0-1 / P0-2 并行

---

### P0 完成标准

- [ ] 默认回答"为什么停"不再靠聊天猜
- [ ] 主链知道下一步该由谁接
- [ ] coding continuation 至少有一条窄 lane 可标准化
- [ ] heartbeat 不再被误当 workflow owner
- [ ] 所有 P0 任务验收标准达成

---

## P1: 叶子 Pilots (2-3 周)

### 目标

在不碰 control plane 的前提下，验证叶子执行增强是否真有收益。

### 为什么先做这个

1. **P0 已建立 contract 基线**: planning default / continuation contract / issue lane / heartbeat boundary 已冻结
2. **需要验证执行层增强**: contract 基线是骨架，叶子 pilot 是肌肉
3. **风险可控**: 叶子层增强不破坏控制面，可随时回退

### 任务清单

#### P1-1: DeepAgents leaf pilot

**目标**: DeepAgents 风格 profile 只进 `coding-subagent` 内部。

**验收标准**:
- [ ] coding subagent profile 包含 TDD / systematic debugging / code review 等方法论
- [ ] profile 不侵入控制面，仅在 subagent 内部生效
- [ ] 测试覆盖：profile 激活与执行质量提升
- [ ] 用户可见：coding 任务交付质量提升

**预计工作量**: 6-8 小时

**风险与回退**:
- 风险：profile 与控制面耦合
- 回退：profile 配置化，可随时禁用

**依赖**: P0-1 (planning default)

**并行性**: 可与 P1-2 并行

---

#### P1-2: SWE-agent issue lane pilot

**目标**: SWE-agent 只进 `issue_to_patch` 窄 lane。

**验收标准**:
- [ ] SWE-agent 风格 issue-to-patch lane 实现
- [ ] lane 不侵入控制面，仅在 issue lane 内部生效
- [ ] 测试覆盖：issue → patch 完整链路
- [ ] 用户可见：issue 修复自动化程度提升

**预计工作量**: 8-12 小时

**风险与回退**:
- 风险：SWE-agent 与现有 issue lane 冲突
- 回退：保留现有 lane，SWE-agent 为可选 profile

**依赖**: P0-3 (issue lane baseline)

**并行性**: 可与 P1-1 并行

---

#### P1-3: planning → execution handoff 标准化

**目标**: planning artifact 字段稳定，执行层、review、QA 能直接消费。

**验收标准**:
- [ ] planning artifact schema 冻结
- [ ] 执行层默认消费 planning artifact
- [ ] review / QA 默认消费 planning artifact
- [ ] 测试覆盖：planning → execution handoff 链路

**预计工作量**: 4-6 小时

**风险与回退**:
- 风险：planning artifact 字段频繁变更
- 回退：schema versioning，向后兼容

**依赖**: P0-1 (planning default)

**并行性**: 可与 P1-1 / P1-2 并行

---

#### P1-4: stopped_because / next_step / owner 标准化

**目标**: 让 operator/main 一眼看懂：当前为何停、谁该接、要不要 gate。

**验收标准**:
- [ ] closeout artifact 包含标准化 `stopped_because` / `next_step` / `next_owner` 字段
- [ ] 所有场景适配器 (trading / channel) 注入标准化字段
- [ ] operator 工具支持查询与展示
- [ ] 测试覆盖：closeout 字段验证

**预计工作量**: 4-6 小时

**风险与回退**:
- 风险：旧 closeout artifact 不兼容
- 回退：保留旧字段兼容，新增字段可选

**依赖**: P0-2 (continuation contract v1)

**并行性**: 可与 P1-1 / P1-2 / P1-3 并行

---

### P1 完成标准

- [ ] 叶子执行质量提升，但 control plane 没被破坏
- [ ] callback 更结构化
- [ ] 人工补洞成本下降
- [ ] 所有 P1 任务验收标准达成

---

## P2: 选择性重型 Pilots (4-6 周，按需)

### 目标

只在真的值得重型化的地方试，而不是把全仓迁到新 runtime。

### 为什么放在 P2

1. **业务证据不足**: 当前没有跨天 durable / 复杂 analysis graph 的强需求
2. **风险较高**: 重型框架引入会增加系统复杂度
3. **可回退性差**: 一旦引入 Temporal/LangGraph，回退成本高

### 任务清单

#### P2-1: 识别高价值 durable 场景

**目标**: 识别跨天、强恢复、强审计的少数高价值 durable 场景。

**验收标准**:
- [ ] durable 场景清单 (不超过 3 个)
- [ ] 每个场景的 SLA / 恢复要求 / 审计要求明确
- [ ] Temporal pilot 可行性评估报告
- [ ] 决策：是否引入 Temporal

**预计工作量**: 8-12 小时

**风险与回退**:
- 风险：场景识别不准确，引入重型框架后使用率低
- 回退：fenced pilot，可独立关闭

**依赖**: P1 完成 (叶子 pilot 验证)

**并行性**: 独立

---

#### P2-2: 识别复杂 analysis 场景

**目标**: 识别单 agent 内确实复杂、值得 graph 化的 analysis 场景。

**验收标准**:
- [ ] analysis graph 场景清单 (不超过 3 个)
- [ ] 每个场景的复杂度评估 (state 数量 / 分支数量)
- [ ] LangGraph pilot 可行性评估报告
- [ ] 决策：是否引入 LangGraph

**预计工作量**: 8-12 小时

**风险与回退**:
- 风险：场景复杂度被高估，LangGraph 过度设计
- 回退：fenced pilot，可独立关闭

**依赖**: P1 完成 (叶子 pilot 验证)

**并行性**: 可与 P2-1 并行

---

#### P2-3: Temporal pilot (如 P2-1 决策为 Yes)

**目标**: 在高价值 durable 场景试点 Temporal。

**验收标准**:
- [ ] Temporal worker 实现
- [ ] durable execution 验证 (跨天恢复)
- [ ] 审计日志完整
- [ ] 回退方案验证

**预计工作量**: 2-3 周

**风险与回退**:
- 风险：Temporal 基础设施复杂，运维成本高
- 回退：fenced pilot，不影响主链

**依赖**: P2-1 决策为 Yes

**并行性**: 独立

---

#### P2-4: LangGraph pilot (如 P2-2 决策为 Yes)

**目标**: 在复杂 analysis 场景试点 LangGraph。

**验收标准**:
- [ ] LangGraph graph 实现
- [ ] reasoning graph 验证 (多状态 / 多分支)
- [ ] 与 OpenClaw control plane 集成
- [ ] 回退方案验证

**预计工作量**: 2-3 周

**风险与回退**:
- 风险：LangGraph 与 OpenClaw control plane 耦合
- 回退：fenced pilot，不影响主链

**依赖**: P2-2 决策为 Yes

**并行性**: 可与 P2-3 并行

---

### P2 完成标准

- [ ] durable/graph 只服务高价值少数场景
- [ ] 任何试点都可 rollback
- [ ] OpenClaw control plane 仍是主链 owner
- [ ] 所有 P2 任务验收标准达成 (如启动)

---

## 风险总览

### 高风险项

| 风险 | 阶段 | 概率 | 影响 | 缓解措施 |
|------|------|------|------|---------|
| Planning artifact 格式不稳定 | P0 | 中 | 高 | 先小范围试点，逐步扩展 |
| Continuation contract 向后兼容 | P0 | 中 | 高 | 保留旧字段兼容，新增字段可选 |
| Temporal/LangGraph 耦合控制面 | P2 | 高 | 高 | fenced pilot，严格边界 |

### 中风险项

| 风险 | 阶段 | 概率 | 影响 | 缓解措施 |
|------|------|------|------|---------|
| Issue lane 输入格式多样 | P0 | 高 | 中 | 先支持标准 GitHub issue |
| Heartbeat 逻辑耦合深 | P0 | 中 | 中 | 标记 deprecated，逐步迁移 |
| DeepAgents profile 与控制面耦合 | P1 | 中 | 中 | profile 配置化，可随时禁用 |

### 低风险项

| 风险 | 阶段 | 概率 | 影响 | 缓解措施 |
|------|------|------|------|---------|
| Planning → execution handoff 字段变更 | P1 | 低 | 中 | schema versioning |
| Closeout 字段旧 artifact 不兼容 | P1 | 低 | 中 | 保留旧字段兼容 |

---

## 资源估算

### 人力估算

| 阶段 | 预计工时 | 人力配置 |
|------|----------|---------|
| P0 | 22-32 小时 | 1 人全职 1-2 周 |
| P1 | 22-32 小时 | 1 人全职 2-3 周 |
| P2 | 40-80 小时 (如启动) | 1-2 人全职 4-6 周 |

### 基础设施估算

| 阶段 | 基础设施需求 |
|------|-------------|
| P0 | 无新增 |
| P1 | 无新增 |
| P2 | Temporal cluster (如启动 P2-3) / LangGraph 依赖 (如启动 P2-4) |

---

## 验收总览

### P0 验收清单

- [ ] Planning artifact 默认生成
- [ ] Continuation contract v1 冻结
- [ ] Issue lane baseline 冻结
- [ ] Heartbeat boundary freeze 文档化 + 代码审查通过
- [ ] 所有 P0 测试通过

### P1 验收清单

- [ ] DeepAgents profile 实现 + 测试通过
- [ ] SWE-agent lane 实现 + 测试通过
- [ ] Planning → execution handoff schema 冻结
- [ ] Closeout 字段标准化 + 测试通过
- [ ] 所有 P1 测试通过

### P2 验收清单 (如启动)

- [ ] 高价值 durable 场景清单 + 决策报告
- [ ] 复杂 analysis 场景清单 + 决策报告
- [ ] Temporal pilot (如启动) + 测试通过
- [ ] LangGraph pilot (如启动) + 测试通过
- [ ] 所有 P2 测试通过

---

## 附录 A: 与架构审查的对应关系

本执行清单基于 [`../review/orchestration-architecture-review-2026-03-24.md`](../review/orchestration-architecture-review-2026-03-24.md) 的结论制定：

| 架构审查结论 | 对应执行任务 |
|-------------|-------------|
| 控制面主链已打通 | P0 基线巩固 |
| 测试覆盖充分 | 所有任务包含测试验收 |
| 双轨后端策略清晰 | 保持 subagent/tmux 双轨 |
| trading continuation 已验证 | P0-3 issue lane 借鉴 trading 经验 |
| 技术债务可管理 | P0/P1 任务优先清偿高优先级债务 |
| 不推荐引入重型框架 | P2 仅按需试点，不进主链 |

---

## 附录 B: 技术债务对应关系

本执行清单与 `docs/technical-debt/technical-debt-2026-03-22.md` 的对应关系：

| 技术债务 | 对应执行任务 | 阶段 |
|---------|-------------|------|
| D1: trading_roundtable 拆分 | 独立任务 (建议在 P0 前完成) | P0-0 |
| D2: Continuation 模块收口 | P0-2 (continuation contract v1) | P0 |
| D3: 文档去重瘦身 | 独立任务 (建议在 P0 前完成) | P0-0 |
| D5: Auto-trigger 配置管理 | P1 任务 (规划中) | P1 |
| D6: Execute mode 真实集成 | P1 任务 (规划中) | P1 |
| D7: 测试覆盖率提升 | 所有任务包含测试验收 | P0/P1 |

---

## 附录 C: 变更日志

| 日期 | 变更 | 作者 |
|------|------|------|
| 2026-03-24 | 初始版本 | Zoe |

---

**文档生成时间**: 2026-03-24 19:00 GMT+8  
**编制者**: Zoe (CTO & Chief Orchestrator)  
**下次更新**: P0 完成后更新 P1/P2 优先级  
**审批状态**: 待审批
