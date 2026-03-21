# CURRENT_TRUTH（2026-03-21）

> 用途：给这个 proposal repo 一个**当前真值入口**，避免旧计划、旧评审、旧 POC 被继续误读成“今天的默认口径”。
>
> 注意：这个 repo 现在的职责是**统一阅读入口 / 架构方案仓**，不是 runtime 真代码仓；runtime live 接线与执行真值仍以 OpenClaw 主仓和相关运行仓为准。

---

## 1. 当前仓库应该怎样理解

这个仓库现在应当被理解为：

> **OpenClaw 公司级 orchestration / workflow 方案仓 + canonical 阅读入口。**

它不是：
- 生产 runtime 真代码仓
- 任一单个 POC、单个插件、单个 pilot 的代名词
- “已经默认全自动闭环”的完成态说明

当前正确总口径是：
- **OpenClaw 持 control plane**
- **proposal repo 持阅读入口与计划/真值索引**
- **外部框架只进叶子层 / benchmark / 局部方法层**
- **总体仍是 thin bridge / allowlist / safe semi-auto**

---

## 2. 本轮已经定下来的真值

### 2.1 planning 默认口径已经收口

1. **gstack-style planning 已作为全局默认 planning method 落地。**
   默认顺序：`problem reframing -> scope/product review -> engineering review -> execution/test plan`。

2. **要点是“借方法，不换政权”。**
   gstack 现在的定位是 planning / review-readiness 方法层脚手架，**不是** OpenClaw 的 control plane 替代品。

3. **下一阶段默认不是“先加循环”，而是“先出 planning artifact”。**
   非 trivial feature / bugfix / workflow 设计，先有 planning，再谈执行与自动推进。

### 2.2 TEAM_RULES 已 codify planning default 与 heartbeat boundary

当前默认已经明确：
- 长任务 / 编码 / 复杂文档默认走 `sessions_spawn(runtime="subagent")`；
- planning artifact 应成为执行层默认输入；
- heartbeat 只做 wake / liveness / 巡检 / 催办 / 告警；
- **heartbeat 不得写 terminal truth，不得直接 dispatch 下一跳，不得接管 gate。**

### 2.3 外部框架策略已经统一

一句话：

> **OpenClaw 继续持有控制面；外部框架只准进入叶子执行层、benchmark 层或局部方法层。**

换成更直接的话：
- **继续 OpenClaw native 的层**：入口、`sessions_spawn`、launch/completion hook、callback bridge、scenario adapter、watcher/reconcile 边界、heartbeat 治理边界；
- **允许外部框架进入的层**：DeepAgents 风格 coding runtime、SWE-agent issue lane、局部 analysis graph、未来少数 durable pilot；
- **明确不引成主链的层**：DeepAgents、SWE-agent、OpenSWE、LangGraph、Temporal 都不升为公司级 orchestration backbone。

### 2.4 当前 live continuation 真值仍需收紧理解

以下仍然成立：
- `channel_roundtable` 与 `trading_roundtable` 已证明 continuation 不是纸面设计；
- 当前默认仍是 allowlist、条件触发、可回退；
- trading 不是任意结果都自动 continuation；
- `tmux` 已是正式可选 backend，但不等于已证明全局自动闭环。

因此，当前正确写法仍是：
- **已有真实 continuation 场景**；
- **但总体仍停留在 thin bridge / allowlist / safe semi-auto**；
- **外部框架讨论的是下一阶段增强点，不是当前主链 owner。**

---

## 3. 为什么 agent 做完就停，以及接下来怎么修

### 3.1 现在为什么会停

“做完一件事就停”有两层原因：

1. **agent 内部停**
   - 只完成当前 step；
   - 缺默认 planning ledger / closeout checklist / next-step policy；
   - 常见表现是：改完一处代码、跑完一轮测试、写完一份文档后自然停住。

2. **公司级主链停**
   - `summary -> decision -> dispatch` 还没统一成默认 continuation contract；
   - 系统知道“这个 run 结束了”，但还不能稳定回答“为什么停、谁接、下一步是什么”。

### 3.2 接下来不是靠盲目加循环修

下一阶段重点是：
1. **先规划**：planning artifact 成为默认输入；
2. **先 contract**：任务 closeout 必须带 `stopped_because / next_step / next_owner`；
3. **再自动推进**：只有 contract 足够清楚时，才讨论自动 dispatch；
4. **heartbeat 继续待在外环**：它负责提醒和重查，不负责代替主链做状态推进。

---

## 4. 当前计划入口

这轮 canonical 计划入口改为：

1. `overall-plan.md` — 当前真值 + P0/P1/P2 计划 + 明确边界
2. `roadmap.md` — 按阶段展开的最小路线图
3. `validation-status.md` — 已验证 / 未验证边界
4. `runtime-integration/spawn-interceptor-live-bridge.md` — live bridge 当前已接/未接边界

如果只想先抓一句话：

> **下一阶段不是“上更多循环”，而是“先把 planning、continuation contract、issue lane baseline、heartbeat boundary 定成默认”，然后再用 DeepAgents / SWE-agent 做叶子层 pilot。**

---

## 5. historical / superseded 入口

以下内容保留，但**不再应被当成当前默认口径入口**：

| 文档 | 当前状态 | 建议替代阅读 |
|------|----------|--------------|
| `../ROADMAP.md` | historical draft / superseded | `roadmap.md` + `overall-plan.md` |
| `official-lobster-integration-plan.md` | historical batch1 plan | `../README.md` + 本页 |
| `validation/p0-minimal-validation-plan.md` | historical pre-live design note | `validation-status.md` + 本页 |
| `reviews/independent-architecture-review-20260319.md` | historical review snapshot | 本页 + `overall-plan.md` |

---

## 6. 一句话总口径

**proposal repo 现在的真值是：它是 OpenClaw 公司级 orchestration 方案仓与统一阅读入口；gstack-style planning 已成为默认方法，TEAM_RULES 已 codify planning default 与 heartbeat boundary；OpenClaw 继续持有 control plane，外部框架只进叶子层/benchmark/局部方法层；下一阶段重点是先规划、先 contract、再自动推进，而不是盲目加循环。**
