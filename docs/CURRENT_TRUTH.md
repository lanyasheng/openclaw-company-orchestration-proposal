# CURRENT_TRUTH(2026-03-21)

> 用途:给这个 proposal repo 一个**当前真值入口**,避免旧计划、旧评审、旧 POC 被继续误读成"今天的默认口径"。
>
> 注意:这个 repo 现在已升级为**单仓分层 monorepo**:`docs/` 持阅读入口,`runtime/` 持实现真值,`tests/` 持验收。历史上 runtime 曾散落在 OpenClaw workspace 本地;从 2026-03-22 起,本仓开始承担 orchestration runtime 的统一收口。
---

## 0. 入口指引(从哪里开始)

### 阅读入口
1. **首次了解** → `../README.md`(仓库总览 + 快速开始)
2. **5 分钟版本** → `executive-summary.md`
3. **当前真值** → 本页(`CURRENT_TRUTH.md`)
4. **其他频道 quickstart** → `quickstart-other-channels.md`(非 trading 场景)
5. **完整方案** → `openclaw-company-orchestration-proposal.md`

### Runtime 入口
```bash
# 统一入口命令
python3 ~/.openclaw/scripts/orch_command.py --context <场景> --channel-id "<频道 ID>" --topic "<主题>"

# 或从本仓直接运行
cd /Users/study/.openclaw/workspace/repos/openclaw-company-orchestration-proposal
python3 runtime/scripts/orch_command.py --context <场景> --channel-id "<频道 ID>" --topic "<主题>"
```

### Quickstart 入口
| 场景 | 入口 |
|------|------|
| **非 trading 频道**(架构/产品/运营等) | `quickstart-other-channels.md` |
| **trading 场景** | 本节 2.4 + `trading_roundtable` 部分 |
| **验证测试** | `python3 -m unittest tests/ -v` |

**首次接入建议**:`allow_auto_dispatch=false`,先验证 callback/ack/dispatch artifacts 稳定,再考虑自动续跑。

## 1. 当前仓库应该怎样理解

这个仓库现在应当被理解为：

> **OpenClaw 公司级 orchestration / workflow 的单仓分层 monorepo。**

它同时承担：
- `docs/`：canonical 阅读入口 / 计划 / 边界 / CURRENT_TRUTH
- `runtime/`：orchestrator、entry command、callback bridge、skills 等实现真值
- `tests/`：针对 runtime 的验收测试

它仍然不是：
- 任一单个 POC、单个插件、单个 pilot 的代名词
- "已经默认全自动闭环"的完成态说明

当前正确总口径是：
- **OpenClaw 持 control plane**
- **本仓同时持阅读入口与 orchestration runtime 收口**
- **外部框架只进叶子层 / benchmark / 局部方法层**
- **总体仍是 thin bridge / allowlist / safe semi-auto**

### 1.1 本地 workspace 副本已退役（2026-03-22）
历史上 orchestration runtime 曾散落在 `~/.openclaw/workspace` 本地；从 2026-03-22 起：
- **Canonical 主线**：本仓 `runtime/` 目录
- **本地副本状态**：已加 `LEGACY_COPY_NOTICE.md` 标成 legacy / 只读 / 待退役
- **规则**：禁止双写，新改动必须提交到本仓 monorepo

详细退役地图见：`~/.openclaw/workspace/ORCHESTRATION_LEGACY_MAP.md`

---

## 2. 本轮已经定下来的真值

### 2.1 planning 默认口径已经收口

1. **gstack-style planning 已作为全局默认 planning method 落地。**
   默认顺序:`problem reframing -> scope/product review -> engineering review -> execution/test plan`。

2. **要点是"借方法,不换政权"。**
   gstack 现在的定位是 planning / review-readiness 方法层脚手架,**不是** OpenClaw 的 control plane 替代品。

3. **下一阶段默认不是"先加循环",而是"先出 planning artifact"。**
   非 trivial feature / bugfix / workflow 设计,先有 planning,再谈执行与自动推进。

### 2.2 TEAM_RULES 已 codify planning default 与 heartbeat boundary

当前默认已经明确:
- 长任务 / 编码 / 复杂文档默认走 `sessions_spawn(runtime="subagent")`;
- planning artifact 应成为执行层默认输入;
- heartbeat 只做 wake / liveness / 巡检 / 催办 / 告警;
- **heartbeat 不得写 terminal truth,不得直接 dispatch 下一跳,不得接管 gate。**

### 2.3 外部框架策略已经统一

一句话:

> **OpenClaw 继续持有控制面;外部框架只准进入叶子执行层、benchmark 层或局部方法层。**

换成更直接的话:
- **继续 OpenClaw native 的层**:入口、`sessions_spawn`、launch/completion hook、callback bridge、scenario adapter、watcher/reconcile 边界、heartbeat 治理边界;
- **允许外部框架进入的层**:DeepAgents 风格 coding runtime、SWE-agent issue lane、局部 analysis graph、未来少数 durable pilot;
- **明确不引成主链的层**:DeepAgents、SWE-agent、OpenSWE、LangGraph、Temporal 都不升为公司级 orchestration backbone。

### 2.4 当前 live continuation 真值仍需收紧理解

以下仍然成立:
- `channel_roundtable` 与 `trading_roundtable` 已证明 continuation 不是纸面设计;
- 当前默认仍是 allowlist、条件触发、可回退;
- trading 不是任意结果都自动 continuation;
- `tmux` 已是正式可选 backend,但不等于已证明全局自动闭环。

因此,当前正确写法仍是:
- **已有真实 continuation 场景**;
- **但总体仍停留在 thin bridge / allowlist / safe semi-auto**;
- **外部框架讨论的是下一阶段增强点,不是当前主链 owner。**

### 2.5 其他频道接入 quickstart 已就绪

新增真值(2026-03-22):
- **quickstart 文档已就绪**:`quickstart-other-channels.md`
- 非 trading 场景默认仍走 `channel_roundtable`,**不需要新 adapter**
- 首次接入仍建议 `allow_auto_dispatch=false`,先证明 callback / ack / dispatch artifacts 稳定,再决定是否放开默认自动续跑
- 最小可运行命令见 quickstart 文档

边界同样要写清:
- 这不代表"其他频道零配置默认全自动"
- 当前成熟度仍是 **thin bridge / allowlist / safe semi-auto**

### 2.6 WS3 暴露的是机制缺口,不是单一个案

当前新增口径:
- WS3 暴露的"waiting 但 active=0"属于 **waiting integrity / hard-close / fail-fast / anomaly detection** 机制缺口;
- 处理顺序必须是:**先修机制,再处理个案**;
- `heartbeat` 仍只在治理外环,负责发现异常等待并请求重查,不负责代替主链写终态。

正式约束入口:`waiting-integrity-hard-close-policy-2026-03-21.md`

---

## 3. 为什么 agent 做完就停,以及接下来怎么修

### 3.1 现在为什么会停

"做完一件事就停"有两层原因:

1. **agent 内部停**
   - 只完成当前 step;
   - 缺默认 planning ledger / closeout checklist / next-step policy;
   - 常见表现是:改完一处代码、跑完一轮测试、写完一份文档后自然停住。

2. **公司级主链停**
   - `summary -> decision -> dispatch` 还没统一成默认 continuation contract;
   - 系统知道"这个 run 结束了",但还不能稳定回答"为什么停、谁接、下一步是什么"。

### 3.2 接下来不是靠盲目加循环修

下一阶段重点是:
1. **先规划**:planning artifact 成为默认输入;
2. **先 contract**:任务 closeout 必须带 `stopped_because / next_step / next_owner`;
3. **再自动推进**:只有 contract 足够清楚时,才讨论自动 dispatch;
4. **heartbeat 继续待在外环**:它负责提醒和重查,不负责代替主链做状态推进。

---

## 4. 当前计划入口

这轮 canonical 计划入口改为:

1. `overall-plan.md` - 当前真值 + P0/P1/P2 计划 + 明确边界
2. `p0-execution-backlog-2026-03-21.md` - P0 第一批执行清单、顺序与 cut line
3. `roadmap.md` - 按阶段展开的最小路线图
4. `validation-status.md` - 已验证 / 未验证边界
5. `runtime-integration/spawn-interceptor-live-bridge.md` - live bridge 当前已接/未接边界

如果只想先抓一句话:

> **下一阶段不是"上更多循环",而是"先把 planning、continuation contract、issue lane baseline、heartbeat boundary 定成默认",然后再用 DeepAgents / SWE-agent 做叶子层 pilot。**

---

## 5. historical / superseded 入口

以下内容保留,但**不再应被当成当前默认口径入口**:

| 文档 | 当前状态 | 建议替代阅读 |
|------|----------|--------------|
| `../ROADMAP.md` | historical draft / superseded | `roadmap.md` + `overall-plan.md` |
| `official-lobster-integration-plan.md` | historical batch1 plan | `../README.md` + 本页 |
| `validation/p0-minimal-validation-plan.md` | historical pre-live design note | `validation-status.md` + 本页 |
| `reviews/independent-architecture-review-20260319.md` | historical review snapshot | 本页 + `overall-plan.md` |

---

## 6. 一句话总口径

**proposal repo 现在的真值是:它是 OpenClaw 公司级 orchestration 方案仓与统一阅读入口;gstack-style planning 已成为默认方法,TEAM_RULES 已 codify planning default 与 heartbeat boundary;OpenClaw 继续持有 control plane,外部框架只进叶子层/benchmark/局部方法层;下一阶段重点是先规划、先 contract、再自动推进,而不是盲目加循环。**

---

## 7. Post-Completion Follow-Up Registration(2026-03-22 新增)

### 7.1 问题:为什么"做完就停"看起来像机制坏了

当前系统已支持:
- 同一 orchestrated flow/batch 内 `callback -> decision -> dispatch` 的 continuation
- allowlist / gate / clean PASS 等控制

**但存在一个缝隙**:
- 当前任务结束后,如果出现新的 follow-up / docs 工作流 / operator-facing 交付,系统没有统一把它显式区分为:
  1) **已注册 continuation**(有 task/batch/dispatch anchor)
  2) **待注册新任务**(planned but not started)

结果就是:聊天里容易把"准备做下一步"说成"已经在推进"。

### 7.2 修复:post-completion replan contract

从 2026-03-22 起,新增 `runtime/orchestrator/post_completion_replan.py`,定义最小 contract:

```python
# 核心结构
followup_mode = "existing_dispatch" | "pending_registration"
truth_anchor_type = "task_id" | "batch_id" | "branch" | "commit" | "push" | "none"
allowed_status_phrase = "in_progress" | "pending_registration"
```

**核心规则(强制)**:
1. **没 anchor 时,followup_mode 只能是 `pending_registration`**
2. **没 anchor 时,status_phrase 只能是 `pending_registration`**
3. **有 anchor 时,才允许标成 `in_progress`**

### 7.3 Operator-Facing 规则(必须遵守)

#### 原 dispatch plan 内的 continuation
- 可以自动续推(前提是 clean PASS + whitelist 命中)
- 状态可以写 `in_progress`
- 必须有明确的 anchor(task_id / batch_id / dispatch step)

#### 原 dispatch plan 外的新 follow-up
- **必须先注册为新任务/新 branch/新 commit anchor**
- 注册前状态只能写 `待启动` / `pending_registration`
- **禁止口头说"继续推进"但系统里没有新任务注册**

#### 状态短语使用规范

| 场景 | followup_mode | truth_anchor | 允许的状态短语 |
|------|---------------|--------------|----------------|
| 原 plan 内的下一跳 | existing_dispatch | task_id / batch_id | `in_progress` |
| 新 follow-up(已注册) | existing_dispatch | branch / commit / push | `in_progress` |
| 新 follow-up(未注册) | pending_registration | none | `pending_registration` |
| 有 anchor 但需人工确认 | pending_registration | 有 | `pending_registration` |

### 7.4 代码入口

```python
from runtime.orchestrator.post_completion_replan import (
    build_replan_contract,
    validate_followup_status,
    PostCompletionReplanContract,
)

# 示例:无 anchor 的新 follow-up(只能 pending_registration)
contract = build_replan_contract(
    followup_description="编写用户文档",
    original_task_id="task_123",
    # 没有 anchor_type / anchor_value → 自动设为 pending_registration
)
assert contract.followup_mode == "pending_registration"
assert contract.status_phrase == "pending_registration"

# 示例:有 anchor 的 continuation(可以 in_progress)
contract = build_replan_contract(
    followup_description="Phase 2 实现",
    original_batch_id="batch_phase1",
    anchor_type="batch_id",
    anchor_value="batch_phase2_scheduled",
)
assert contract.followup_mode == "existing_dispatch"
assert contract.status_phrase == "in_progress"
```

### 7.5 与现有机制的关系

- **不是大重构**:只是补一个最小 contract,不改变现有 callback/dispatch/ack 逻辑
- **不是全自动**:仍然需要显式注册 anchor,不能靠聊天口头继续
- **与 waiting-integrity 配合**:waiting guard 负责发现"等但没活",replan contract 负责区分"已注册 vs 待注册"

### 7.6 验收测试

```bash
# 运行 post-completion replan 测试
python3 -m pytest tests/orchestrator/test_post_completion_replan.py -q
```

覆盖:
- 无 anchor 的 follow-up 不能被标成 `in_progress`
- 有 anchor(至少一种)时可被标成已启动/已注册
- validate_followup_status 强制修正非法状态

### 7.7 Partial Continuation Kernel v1 (2026-03-22 新增)

从 2026-03-22 起，新增 `runtime/orchestrator/partial_continuation.py`，提供**通用 partial closeout / auto-replan / next-task registration 能力**。

**核心能力:**
1. **Partial Closeout Contract** — 描述任务部分完成后的状态
   - `completed_scope`: 已完成的工作
   - `remaining_scope`: 剩余的工作
   - `stop_reason`: 停止原因
   - `dispatch_readiness`: 是否准备好 dispatch 下一跳
   - `next_candidates`: 自动生成的候选任务

2. **Auto-Replan Helper** — 基于 `remaining_scope` 自动生成 next task candidates
   - 按优先级排序 (partial > not_started > blocked)
   - 可配置最大候选数量

3. **Next-Task Registration Payload** — 结构化注册 payload
   - 这是 canonical artifact，operator/main 可以继续消费
   - 当前不直接写入 state machine，但提供完整可用结构

**核心规则:**
- `should_generate_next_registration()` 仅在以下条件满足时返回 True:
  - 有 `remaining_scope` AND
  - `dispatch_readiness != "blocked"` AND
  - 不是 fully completed

**与 post_completion_replan 的关系:**
- `post_completion_replan.py`: 关注 follow-up mode (existing_dispatch vs pending_registration) 和 truth anchor
- `partial_continuation.py`: 关注 partial closeout 的结构化描述和 auto-replan
- 两者互补：replan 定义"是否有 anchor"，continuation 定义"remaining work 是什么"

**场景接入:**
- **Trading roundtable** (已接入): `process_trading_roundtable_callback()` 现在生成 `partial_closeout` 和 `next_task_registrations`
- **Channel roundtable** (可接入): 可通过 `adapt_closeout_for_channel()` 接入

**代码入口:**
```python
from runtime.orchestrator.partial_continuation import (
    build_partial_closeout,
    auto_replan,
    generate_next_registrations_for_closeout,
    adapt_closeout_for_trading,
)

# 构建 generic closeout
closeout = build_partial_closeout(
    completed_scope=[{"item_id": "c1", "description": "Done"}],
    remaining_scope=[{"item_id": "r1", "description": "Next"}],
    stop_reason="partial_completed",
)

# 适配 trading 场景
adapted = adapt_closeout_for_trading(
    closeout=closeout,
    roundtable={"conclusion": "PASS", "blocker": "none"},
)

# 生成 registrations
registrations = generate_next_registrations_for_closeout(
    closeout=adapted,
    adapter="trading_roundtable",
)
```

**验收测试:**
```bash
# 运行 partial continuation 测试
python3 -m pytest tests/orchestrator/test_partial_continuation.py -v
# 33 passed
```

**覆盖:**
- ✅ Generic partial closeout contract 构建
- ✅ Auto-replan 生成 next candidate / registration payload
- ✅ 无 remaining scope 时不生成 next registration
- ✅ Blocked 时不生成 next registration
- ✅ Trading 场景能调用这个通用 kernel
- ✅ Channel 场景适配逻辑

**当前成熟度:**
- ✅ Generic kernel v1 实现完成
- ✅ Trading 场景最小接入完成
- ⏳ Channel 场景可接入（未实施）
- ❌ 不直接写入 state machine（需手动消费 registration payload）
- ❌ 不等于"全域全自动无人续跑"

详细文档：`docs/partial-continuation-kernel-v1.md`

---

## 8. 历史入口与 Superseded 内容

保留但**不再应被当成当前默认口径入口**:

| 文档 | 当前状态 | 建议替代阅读 |
|------|----------|--------------|
| `../ROADMAP.md` | historical draft / superseded | `roadmap.md` + `overall-plan.md` |
| `official-lobster-integration-plan.md` | historical batch1 plan | `../README.md` + 本页 |
| `validation/p0-minimal-validation-plan.md` | historical pre-live design note | `validation-status.md` + 本页 |
| `reviews/independent-architecture-review-20260319.md` | historical review snapshot | 本页 + `overall-plan.md` |
