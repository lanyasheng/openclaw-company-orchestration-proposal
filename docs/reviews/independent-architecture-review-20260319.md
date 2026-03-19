# 独立架构审查报告

**审查日期**: 2026-03-19  
**审查对象**: `openclaw-company-orchestration-proposal` 仓库  
**最新 Commit**: `c2a2649 feat: add minimal scheduler dispatcher core`  
**审查人**: Independent Reviewer (Subagent)  
**审查范围**: 整体架构设计、代码实现状态、路线图可行性、风险评估

---

## 结论先行

**整体判断：方案方向正确，架构设计清晰，但存在 3 个关键风险点需要正视。建议继续推进 P0/P1，但必须在进入 P1 前解决"官方 Lobster 闭环未验证"和"顺序链是否足够支撑 trading pilot"两个核心问题。**

**最终建议：继续推进，但需调整 P1 优先级，先验证 Lobster→subagent 真实闭环，再固化模板。**

---

## 1. 整体架构评估

### 1.1 五层架构清晰度：✅ 良好

```
业务场景层 (workspace-trading 首个落地)
    ↑
编排控制层 (task registry / state machine / callback / timeline)
    ↑
执行层 (subagent 主链 / browser / message / cron)
    ↑
官方底座层 (OpenClaw 原生能力 + Lobster workflow shell)

可选安全层 (横切：human-gate / policy / audit / rollback)
```

**优点**:
- 分层边界清晰，职责分离合理
- 官方底座层与编排控制层分离，避免把 Lobster 误当 backbone
- 执行层明确 `subagent` 为事实主链，口径一致
- 可选安全层"横切"定位准确，避免 P0 阶段过度治理

**问题**:
- **human-gate 位置模糊**：文档中 human-gate 同时出现在"可选安全层"和"编排控制层标准能力"两种表述中。审查发现 `p0-6-human-gate-integration.md` 将其作为控制层协议，但 `architecture-layering.md` 将其列为可选安全层。**建议明确：human-gate 是控制层必备协议，安全层只负责策略化增强。**

### 1.2 层间边界评估：⚠️ 存在风险

| 层间边界 | 状态 | 风险 |
|---------|------|------|
| 官方底座层 → 编排控制层 | 清晰 | 低 |
| 编排控制层 → 执行层 | **部分模糊** | 中 |
| 编排控制层 → 业务场景层 | 清晰 | 低 |
| 可选安全层 → 控制层/执行层 | **未明确接口** | 中 |

**关键问题**:
- 编排控制层与执行层的接口契约 (`adapter contract`) 在 P1 交付物中提及，但当前代码中只有 `builtin_handlers.py` 中的硬编码 handler，没有可插拔 adapter 机制
- `scheduler.py` 中 `step_handlers` 是 `Mapping[str, StepHandler]`，但缺少标准 adapter interface 定义

---

## 2. 代码推送状态确认

### 2.1 Git 状态核验

```bash
$ git log --oneline -1
c2a2649 feat: add minimal scheduler dispatcher core

$ git status
On branch main
Your branch is up to date with 'origin/main'.
nothing to commit, working tree clean
```

**结论**: ✅ **所有代码已推送到远端**，`origin/main` 包含最新实现。

### 2.2 关键代码文件清单

已推送的核心代码：
- `orchestration_runtime/task_registry.py` (6.1KB)
- `orchestration_runtime/scheduler.py` (11.6KB)
- `orchestration_runtime/builtin_handlers.py` (6.5KB)
- `scripts/run_minimal_scheduler.py` (2.4KB)
- `examples/workflows/chain-basic.scheduler.json`
- `poc/official_lobster_bridge/` (官方 Lobster 桥接)
- `poc/lobster_minimal_validation/` (POC harness 保留)
- `poc/subagent_bridge_sim/` (subagent 桥接模拟)

**未发现本地未推送的关键代码**。

---

## 3. P0/P1/P2 路线图评估

### 3.1 P0 评估：✅ 可执行

**P0 交付物**:
1. ✅ README/执行摘要/主方案文档重写 — 已完成
2. ✅ 五层架构口径冻结 — 已完成
3. ✅ task registry / state machine / callback 语义冻结 — 已完成
4. ✅ 文档结构分层 — 已完成
5. ⚠️ Trading 首个流程 dry-run — **未完全完成**

**风险**:
- P0 要求"选定 Trading 首个流程并完成 dry-run 或 shadow-run"，但当前只有 `workspace-trading-pilot-workflow.md` 设计文档，**没有实际执行记录或产物**。
- `run_minimal_scheduler.py` 只能跑 `chain-basic` 示例，**没有与 workspace-trading 真实接线**。

**建议**: P0 完成标准应调整为"Trading 流程设计冻结 + 最小调度器打通"，而非"真实 dry-run 完成"。

### 3.2 P1 评估：⚠️ 过于理想化

**P1 交付物**:
1. `subagent / browser / message / cron` adapter contract — **未开始**
2. CHAIN / HUMAN_GATE / FAILURE_BRANCH 模板固化 — **部分完成**
3. timeline / observability / escalation / retry 基线 — **未开始**
4. Trading pilot 稳定化 + 回退开关 — **未开始**
5. human-gate / callback / outbox 进入控制层标准能力 — **部分完成**

**关键风险**:
- **P1 范围过大**：5 项交付物中 3 项未开始，且"adapter contract"和"timeline 基线"都是需要真实业务反馈才能设计合理的抽象。
- **模板固化时机过早**：`CHAIN` 模板已有代码，但 `HUMAN_GATE` 和 `FAILURE_BRANCH` 只有文档设计，没有代码验证。在真实业务反馈前固化模板，容易设计过度或不足。
- **"稳定化"定义模糊**：什么叫"Trading pilot 稳定化"？需要多少轮成功执行？错误率低于多少？没有量化标准。

**建议**:
1. 将 P1 拆分为 P1a (adapter contract + CHAIN 模板) 和 P1b (其他模板 + timeline)
2. 先跑通一条真实 Trading 流程，再固化模板
3. 为"稳定化"定义量化指标（如：连续 10 次执行成功率 > 90%）

### 3.3 P2 评估：✅ 合理

P2 定位清晰："只把真正值得重型化的链路升级"，不承诺全量 Temporal 化。这个收敛是对的。

**潜在问题**:
- "识别跨天、强恢复、强审计场景"需要 P1 真实运行数据支撑，当前无法提前识别。
- 建议 P2 启动条件明确为"P1 完成后 + 至少 3 条真实 workflow 运行数据"。

---

## 4. Trading Pilot Workflow 设计评估

### 4.1 Use Case 选择：✅ 合理

**选中的 pilot**: `固定候选验收闭环（Acceptance Harness Dry-Run v1）`

**优点**:
- ✅ 离线执行，无真实交易副作用
- ✅ 输入/输出契约已存在 (`workspace-trading` 已有 acceptance harness)
- ✅ 可回退（停掉 workflow 即可恢复人工执行）
- ✅ 覆盖核心链路：`dispatch -> subagent -> terminal -> classify -> callback`

**潜在问题**:
- **这个 use case 太"干净"了**：它不涉及 human-gate、不涉及失败分支、不涉及超时降级。用它验证 workflow engine，相当于用"Hello World"验证操作系统。
- **无法验证关键能力**：human-gate 审批、failure-branch 回退、超时降级、callback 重试等关键能力在这个 pilot 中都触发不了。

**建议**:
- 在 P1 阶段增加第二条 pilot：`盘中风险守门（带 human-gate）`，验证 waiting_human / timeout / reject / degrade 语义。
- 或者在当前 pilot 中**人为注入故障场景**（如模拟 subagent 超时、模拟 artifact 解析失败），验证失败处理逻辑。

### 4.2 节点列表评估：⚠️ 部分清晰

**6 个节点设计**:
1. `init_registry` — ✅ 清晰
2. `validate_request` — ✅ 清晰
3. `dispatch_acceptance_subagent` — ⚠️ **实现缺失**
4. `await_terminal` — ⚠️ **实现缺失**
5. `collect_and_classify` — ⚠️ **实现缺失**
6. `final_callback` — ⚠️ **部分实现**

**问题**:
- 当前 `builtin_handlers.py` 中只有 `control.init_registry`、`control.inline_payload`、`subagent.await_terminal`、`callback.send_once` 四个 handler。
- **缺少 `dispatch_acceptance_subagent` 的真实实现**：当前 `subagent.await_terminal` 只是模拟等待，没有真实调用 `sessions_spawn(runtime="subagent")`。
- **缺少 `collect_and_classify` 的实现**：这个 handler 需要读取 artifact JSON、验证 manifest/checklist、映射 verdict 到 workflow state，当前没有代码。

### 4.3 Fan-out/Join 语义：✅ 清晰但过于简单

**设计**:
- 控制面 fan-out: none（单链）
- 业务面 fan-out: acceptance harness 内部 4 个 scenario 维度
- Join 规则: 4 个维度必须同时存在

**评估**:
- 这个设计是**对的**：P1 阶段不应该引入真并发，先把单链跑通。
- 但需要明确：**当需要真并发时（如同时验收多个候选策略），当前架构如何扩展？** 文档中提到 `PARALLEL` 模板"仅在真实能力确认后纳入"，但没说清楚这个能力确认的标准是什么。

### 4.4 成功/降级/失败/超时语义：✅ 清晰

| 状态 | 条件 | 评估 |
|------|------|------|
| `completed` | exit_code=0 + artifact 完整 + verdict=PASS | ✅ 清晰 |
| `degraded` | exit_code=0 + artifact 完整 + verdict=CONDITIONAL/FAIL | ✅ 清晰 |
| `failed` | exit_code≠0 / artifact 缺失 / manifest 缺失 | ✅ 清晰 |
| `timeout` | 300 秒无 terminal | ✅ 清晰 |

**亮点**:
- 明确区分"workflow 执行失败"和"业务 verdict 不好"
- `callback_status` 与 `state` 分离，callback 失败不回写业务终态

**建议**:
- 增加 `retrying` 状态的定义：什么情况下会重试？重试几次？重试间隔多久？
- 增加 `cancelled` 状态的定义：人工取消 workflow 时如何处理？

---

## 5. 最小 Scheduler/Dispatcher 评估

### 5.1 当前能力：✅ 顺序链够用

**已实现**:
- ✅ JSON file based task registry (`FileTaskRegistry`)
- ✅ 顺序 workflow 执行 (`WorkflowDispatcher`)
- ✅ step handler 返回值 (`completed` / `waiting`)
- ✅ 暂停/恢复语义 (`waiting_for` + `signal`)
- ✅ evidence deep merge
- ✅ atomic write

**代码质量**:
- `scheduler.py` 250 行，逻辑清晰，错误处理到位
- `task_registry.py` 使用临时文件 + rename 实现 atomic write，设计正确
- `builtin_handlers.py` 中 handler 实现简单但功能完整

### 5.2 是否太弱：⚠️ 取决于 Trading pilot 需求

**当前只支持顺序链**，但 Trading pilot workflow 设计也是顺序链（6 个节点依次执行），所以**当前收敛是对的**。

**但存在一个关键缺口**:
- Trading pilot 中 `dispatch_acceptance_subagent` 节点需要**真实调用 `sessions_spawn(runtime="subagent")`**，并等待 terminal。
- 当前 `subagent.await_terminal` handler 只是模拟等待，**没有真实 handoff 到 subagent 的能力**。

**缺什么才能真正接 Trading pilot**:
1. **真实 subagent dispatch adapter**：调用 OpenClaw `sessions_spawn` API，获取 `child_session_key`
2. **真实 terminal ingest**：监听 subagent terminal envelope，提取 `exit_code`、`stdout_tail`、`evidence`
3. **真实 callback transport**：当前 `callback.send_once` 只更新 registry 状态，**没有实际发送消息到 Discord/Slack 等渠道**

**评估**:
- 当前 scheduler core **足够支撑顺序链语义**
- 但**缺少与外部系统（OpenClaw session、消息渠道）的真实接线**
- 建议 P1a 优先实现这三个 adapter，而不是先固化模板

---

## 6. 官方 Lobster 接入评估

### 6.1 接入真实性：⚠️ "看起来接了，但没完全接"

**当前状态**:
- ✅ `poc/official_lobster_bridge/` 目录已创建
- ✅ `package.json` pin 了 `@clawdbot/lobster@2026.1.24`
- ✅ `run_official.py` wrapper 已实现
- ✅ `workflows/chain-basic.lobster` workflow 文件已创建
- ⚠️ **`chain-basic` 是否已实际切换到官方 runtime 执行？** — 文档说"已切换"，但没有执行记录或产物证明

**审查发现的关键问题**:

1. **版本 pin 口径不一致**:
   - 文档说 pin `@clawdbot/lobster@2026.1.24`
   - 但 `official-lobster-integration-plan.md` 同时记录源码审计基线 `openclaw/lobster@1d2b7ee6be9d5c3b6b21235afa181927a2693366`
   - **问题**: npm 包 `2026.1.24` 与 GitHub 源码 `1d2b7ee` 是否一致？如果不一致，以哪个为准？

2. **CLI / SDK 选择**:
   - 当前选择 CLI-first 是对的（薄 wrapper、易回退）
   - 但文档提到"SDK 暂不作为默认执行路径"，**没有说明 SDK 的评估标准**：什么情况下会切换到 SDK-first？

3. **回退方式**:
   - 回退命令已给出：`python3 -m poc.lobster_minimal_validation.run_poc chain ...`
   - **但没有自动化回退机制**：如果官方 CLI 失败，是否会自动 fallback 到 POC harness？还是必须人工介入？

4. **`openclaw.invoke` shim 未解决**:
   - 文档明确说"batch1 不去绑定 `openclaw.invoke`"
   - **问题**: 如果不绑定 `openclaw.invoke`，Lobster workflow 如何调用 OpenClaw tool？当前 `chain-basic.lobster` 是否真的能调用 `sessions_spawn`？

### 6.2 版本 Pin 评估：⚠️ 存在漂移风险

**当前方案**:
- 执行 pin: `@clawdbot/lobster@2026.1.24` (npm)
- 源码审计 pin: `openclaw/lobster@1d2b7ee` (GitHub)

**风险**:
- npm 包可能随时更新，如果 `2026.1.25` 有 breaking change，当前 workflow 是否会失败？
- 建议使用 **精确版本 + lockfile**：`package-lock.json` 应提交到 repo，确保可重现。

### 6.3 回退方式评估：✅ 清晰但手动

**回退触发条件**已明确：
- 官方 CLI 安装失败
- workflow file 能力不满足
- npm 包行为漂移
- 输出契约无法对齐

**问题**:
- 回退是**手动操作**，需要人工执行 fallback 命令
- 建议增加**自动化健康检查**：在 workflow 启动前先检查 `lobster` CLI 是否可用，不可用时自动 fallback

---

## 7. 最大的 3 个风险点

### 风险 1: Lobster → Subagent 真实闭环未验证 🔴 高危

**问题描述**:
- 当前所有验证都是"模拟"或"POC"，**没有真实跑通 `Lobster workflow → sessions_spawn(subagent) → terminal → callback` 完整链路**
- `poc/subagent_bridge_sim/` 是模拟器，不是真实接线
- `poc/official_lobster_bridge/` 只验证了 Lobster CLI 能跑，**没有验证能调用 OpenClaw subagent**

**如果跑不通会怎样**:
- 整个"官方底座层 + 编排控制层"设计需要重做
- 可能需要放弃 Lobster，改用其他 workflow shell（或自研）
- P1 所有模板固化工作可能白费

**缓解建议**:
1. **P1a 最高优先级**: 实现真实 `subagent.dispatch` adapter，跑通一次完整闭环
2. **准备 Plan B**: 如果 Lobster 无法调用 subagent，评估直接用 Python 实现薄 workflow shell
3. **设定验证时限**: 2 周内必须跑通真实闭环，否则重新评估方案

### 风险 2: 顺序链不足以支撑真实 Trading 场景 🟡 中危

**问题描述**:
- 当前 scheduler 只支持顺序链，不支持 parallel / join / failure-branch
- Trading pilot 设计也是顺序链，**但这个 pilot 太简单，不能代表真实 Trading 场景**
- 真实 Trading 场景可能需要：
  - 并行检查多个数据源
  - 并行运行多个风险检查
  - 失败时走不同分支（如数据降级 vs 直接拒绝）

**如果不够用会怎样**:
- 需要在 P1 中期紧急扩展 scheduler 支持 parallel / join
- 可能引入新的复杂度，破坏当前简洁设计
- 或者被迫把复杂逻辑塞进单个 subagent，违背分层原则

**缓解建议**:
1. **明确边界**: 在 P1 开始前明确"顺序链能做什么、不能做什么"
2. **提前设计 parallel/join 接口**: 不实现，但先设计好接口，评估扩展成本
3. **监控 Trading pilot 局限性**: 如果 pilot 执行中发现"这里要是能并行就好了"，立即记录并评估

### 风险 3: 控制层与执行层接口契约模糊 🟡 中危

**问题描述**:
- 文档中提到"adapter contract"是 P1 交付物，但**当前没有 interface 定义**
- `builtin_handlers.py` 中 handler 是硬编码的，**没有可插拔机制**
- 如果要新增一个执行单元（如 Temporal worker），需要改 `scheduler.py` 代码

**如果处理不好会怎样**:
- 控制层与执行层紧耦合，违反分层原则
- 新增执行单元需要改控制层代码，难以扩展
- 不同执行单元的 error handling、timeout、retry 语义不一致

**缓解建议**:
1. **P1a 优先定义 adapter interface**:
   ```python
   class ExecutionAdapter(Protocol):
       def dispatch(self, payload: Dict) -> DispatchHandle: ...
       def poll_terminal(self, handle: DispatchHandle) -> TerminalResult: ...
       def cancel(self, handle: DispatchHandle) -> None: ...
   ```
2. **为每个执行单元实现 adapter**:
   - `SubagentAdapter`
   - `BrowserAdapter`
   - `MessageAdapter`
   - `CronAdapter`
3. **在 scheduler 中通过 registry 注册 adapter**，而不是硬编码

---

## 8. 最终建议

### 8.1 是否建议继续推进？

**✅ 建议继续推进，但需调整优先级。**

**理由**:
1. 五层架构设计清晰，方向正确
2. 当前代码质量良好，scheduler core 实现扎实
3. Trading pilot 设计合理，离线、可回退、无副作用
4. 风险点已识别，都有缓解方案

**但必须调整**:
- P1 范围过大，需要拆分
- Lobster→subagent 真实闭环验证优先级应提到最高
- adapter contract 应先于模板固化

### 8.2 调整后的优先级建议

```
P0 (当前):
  ✅ 文档冻结
  ✅ scheduler core 实现
  ⚠️ Trading pilot 设计冻结（完成）

P1a (2 周内):
  🔴 实现真实 subagent dispatch adapter
  🔴 跑通 Lobster → subagent → terminal → callback 完整闭环
  🟡 定义 adapter interface
  🟡 实现 SubagentAdapter / MessageAdapter

P1b (4 周内):
  🟡 实现 HUMAN_GATE / FAILURE_BRANCH 模板
  🟡 实现 timeline / observability 基线
  🟡 跑通第二条 pilot（带 human-gate）

P2 (8 周内):
  🟢 评估是否需要 Temporal
  🟢 安全层策略化
```

### 8.3 停止推进的条件

**如果出现以下情况，应停下来重设计**:
1. **2 周内无法跑通 Lobster→subagent 真实闭环** — 说明官方底座层不可用
2. **Trading pilot 执行中发现顺序链严重不足** — 说明架构需要支持并发
3. **adapter interface 设计后发现扩展成本过高** — 说明控制层/执行层边界设计有问题

---

## 9. 审查总结

| 审查维度 | 评分 | 说明 |
|---------|------|------|
| 整体架构合理性 | ⭐⭐⭐⭐ | 五层架构清晰，但 human-gate 位置需明确 |
| 代码推送状态 | ✅ 完成 | 所有代码已推送到 origin/main |
| P0/P1/P2 可执行性 | ⭐⭐⭐ | P0 基本完成，P1 范围过大需拆分 |
| Trading pilot 设计 | ⭐⭐⭐⭐ | 设计合理，但太简单无法验证关键能力 |
| Scheduler 能力 | ⭐⭐⭐⭐ | 顺序链够用，但缺少真实 adapter |
| Lobster 接入真实性 | ⭐⭐ | 看起来接了，但真实闭环未验证 |
| 风险识别 | ⭐⭐⭐⭐⭐ | 已识别 3 个关键风险，都有缓解方案 |

**最终结论**: 方案方向正确，架构设计清晰，代码质量良好。但存在"官方 Lobster 闭环未验证"和"顺序链是否足够"两个关键风险。**建议继续推进 P0/P1，但必须将 Lobster→subagent 真实闭环验证作为 P1a 最高优先级，2 周内必须跑通，否则重新评估方案。**

---

**审查人**: Independent Reviewer (Subagent)  
**审查完成时间**: 2026-03-19  
**Commit Hash**: `c2a2649`
