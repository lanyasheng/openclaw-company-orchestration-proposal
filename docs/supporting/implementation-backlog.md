# OpenClaw Thin Orchestration — 实施 Backlog

> 状态：draft-for-execution  
> 日期：2026-03-19  
> 依据文档：`README.md`、`docs/executive-summary.md`、`docs/supporting/thin-orchestration-layer.md`、`docs/openclaw-company-orchestration-proposal.md`、`docs/validation/p0-poc-implementation-status.md`

---

## 0. 背景与约束

### 当前真值

1. **默认内部长任务主链**：`sessions_spawn(runtime="subagent")`
2. **taskwatcher 定位**：external async watcher / reconciler，**不是 backbone**
3. **P0 已有资产**：
   - `poc/lobster_minimal_validation/`：chain / human-gate / failure-branch repo-local POC
   - `poc/subagent_bridge_sim/`：subagent terminal + callback status simulator
   - `schemas/minimal-task-registry.schema.json`：P0 6 字段 schema
   - `plugins/human-gate-message/`：human-gate plugin 源码归档
4. **当前缺口**：官方 Lobster 真接入、workflow model 固化、scheduler/dispatch、state/callback 升格、workspace-trading 首个真实 workflow、timeline/observability、可选 guardrails

### 本 backlog 的使用方式

- 这是**后续派发给 subagent 的执行底单**，不是纯 roadmap 装饰文档。
- 每个 Task 都包含：**目标、范围、不做项、产物、测试/验收、依赖、建议执行顺序**。
- 标记说明：
  - **[DOC]**：文档/方案任务
  - **[CODE]**：代码任务
  - **[DOC+CODE]**：需要文档与代码一起交付
  - **并行：可 / 条件可 / 否**：是否适合与其他任务并行推进

### 全局排序原则

1. 先冻结边界，再接官方底座
2. 先让 `chain + subagent + terminal + callback` 形成真闭环，再扩大模板数
3. `workspace-trading` 首个 workflow 必须是**离线、可回退、无真实交易副作用**
4. observability 与 guards 不阻塞首条闭环，但必须在 pilot 前补齐最小可见性

---

# Epic 1：官方底座接入（Lobster Official Runtime Integration）

## Epic 验收标准

- 至少 1 条 workflow（优先 `chain-basic`）运行在**官方 Lobster runtime/CLI/SDK** 上，而不是仅 repo-local stub。
- 保留 feature flag，可在官方 runtime 与现有 POC harness 间切换。
- 不改写 OpenClaw 控制平面真值：`subagent` 仍是执行主链，Lobster 只是 thin orchestration layer。

## E1-T1 官方接入方案冻结 [DOC] [并行：可]
- **目标**：明确官方 Lobster 的接入形态：CLI、SDK、vendored snapshot、submodule、版本 pin、升级策略。
- **范围**：
  - 明确“如何在本 repo 内调用官方 Lobster”
  - 冻结版本 pin / 获取方式 / 本地开发模式
  - 明确与现有 POC harness 的双轨策略
- **不做项**：
  - 不实现 workflow 执行器
  - 不改 OpenClaw runtime repo
- **产物**：
  - `docs/official-lobster-integration-plan.md`
  - 版本 pin 与接入决策记录（可合并进同文档）
- **测试/验收**：
  - 文档明确回答：从哪里拿 Lobster、如何本地运行、如何回退到 POC harness
  - 明确 license / 依赖 / 版本升级策略
- **依赖**：无
- **建议执行顺序**：01

## E1-T2 官方 Lobster wrapper 接入 [CODE] [并行：否]
- **目标**：提供一个 repo-local wrapper，把官方 Lobster 以稳定接口接进本 proposal repo。
- **范围**：
  - 增加官方 runtime 启动入口
  - 统一输入输出目录约定
  - 暴露最小运行接口给后续 workflow model / scheduler 调用
- **不做项**：
  - 不一次性支持全部 template
  - 不接 browser/message/provider
- **产物**：
  - `poc/official_lobster_bridge/` 或等价目录
  - README / sample command
  - 最小 smoke test
- **测试/验收**：
  - 本地可跑 `chain-basic` 示例
  - 能输出稳定的 execution result / error envelope
  - 失败时能保留 error evidence
- **依赖**：E1-T1
- **建议执行顺序**：02

## E1-T3 用官方 runtime 替换 chain-basic 基线 [DOC+CODE] [并行：条件可]
- **目标**：把当前 `chain-basic` 从“概念 POC”升级为“官方底座驱动的最小真链路”。
- **范围**：
  - 复用现有 `chain-basic` 输入/预期输出
  - 把执行器切到官方 Lobster wrapper
  - 保留 fallback 到旧 harness 的开关
- **不做项**：
  - 不引入 human-gate / failure-branch 的真实 provider
  - 不接入 workspace-trading
- **产物**：
  - 更新后的 `poc/lobster_minimal_validation/` 或新官方样例目录
  - 对比说明文档（官方 runtime vs 旧 POC harness）
- **测试/验收**：
  - 至少 1 个自动化测试证明官方 runtime 路径通过
  - 同一输入在 feature flag 切换下能得到等价终态语义
- **依赖**：E1-T2
- **建议执行顺序**：03

---

# Epic 2：Workflow Model（受限模板与执行语义）

## Epic 验收标准

- 冻结 P0/P1 受限 workflow model：`chain / parallel / join / human-gate / failure-branch`。
- 输入 schema、模板语义、状态转移、evidence 归档方式可被代码直接消费。
- 至少 `chain / human-gate / failure-branch` 有可跑实现；`parallel / join` 至少完成可执行 contract。

## E2-T1 Workflow Model 规范冻结 [DOC] [并行：可]
- **目标**：把现有 proposal 中分散的 template 语义收敛为单一 canonical 文档。
- **范围**：
  - 统一节点、边、resume、failure-branch、join 条件定义
  - 明确 P0 与 P1 支持矩阵
  - 明确 `parallel/join` 是 contract-first 还是 code-first
- **不做项**：
  - 不实现执行器
  - 不引入通用 DAG 语义
- **产物**：
  - `docs/workflow-model.md`
  - 模板支持矩阵表
- **测试/验收**：
  - 文档能唯一回答：每个 template 的输入、状态、终态、失败路径、是否支持并发
  - 与 `docs/supporting/thin-orchestration-layer.md` 不冲突
- **依赖**：建议参考 E1-T1
- **建议执行顺序**：04

## E2-T2 Workflow Schema / Parser 实现 [CODE] [并行：条件可]
- **目标**：实现 workflow definition 的 schema 校验与 parser，避免每个 POC 各写一套输入格式。
- **范围**：
  - workflow definition schema
  - parser / validator
  - 错误输出规范化
- **不做项**：
  - 不做复杂图优化
  - 不做运行时调度策略
- **产物**：
  - `schemas/workflow-definition.schema.json`
  - `src/` 或 `poc/` 下 parser/validator 模块
  - 示例 definition 文件
- **测试/验收**：
  - 合法/非法样例各至少 2 组测试
  - 非法输入报错能定位到模板/字段级别
- **依赖**：E2-T1，建议在 E1-T2 之后实现
- **建议执行顺序**：05

## E2-T3 模板执行语义落地（chain / human-gate / failure-branch）[CODE] [并行：否]
- **目标**：把最先要用的 3 个模板做成统一执行语义，而不是分散在不同 POC runner 里。
- **范围**：
  - chain executor
  - human-gate pause/resume contract
  - failure-branch success/fallback contract
- **不做项**：
  - 不做 generic DAG engine
  - 不一次性支持 nested graph
- **产物**：
  - 统一 template executor 模块
  - 模板示例与 README
- **测试/验收**：
  - 3 类模板都有自动化测试
  - 终态能正确映射到 minimal task registry
- **依赖**：E2-T2、E4-T2
- **建议执行顺序**：08

## E2-T4 `parallel / join` contract 与最小实现 [DOC+CODE] [并行：条件可]
- **目标**：为后续多子任务并发准备最小 contract，优先做到“边界清晰、可受控”，不追求完整图引擎。
- **范围**：
  - `parallel` fan-out contract
  - `join` 汇聚条件与失败处理
  - 最小本地模拟实现
- **不做项**：
  - 不做抢占式调度
  - 不做跨机器 distributed scheduler
- **产物**：
  - contract 文档补充
  - 最小并行模拟器或测试桩
- **测试/验收**：
  - 至少 1 个 `parallel -> join` 本地样例跑通
  - join 对“部分失败/超时”有明确语义
- **依赖**：E2-T1、E3-T2
- **建议执行顺序**：12

---

# Epic 3：Scheduler / Dispatch（调度与派发）

## Epic 验收标准

- workflow step 能被调度到正确 adapter/subagent。
- `spawn -> await terminal -> next step` 不再靠手写 POC 粘合。
- `parallel/join` 至少有单机最小派发与汇聚语义。

## E3-T1 Scheduler / Dispatch 边界冻结 [DOC] [并行：可]
- **目标**：明确 scheduler、dispatch、taskwatcher、subagent bridge、callback plane 的边界。
- **范围**：
  - immediate dispatch vs waiting states
  - 谁负责推进下一步、谁只负责观察
  - external watcher 何时介入
- **不做项**：
  - 不做代码实现
  - 不扩 taskwatcher scope
- **产物**：
  - `docs/scheduler-dispatch-contract.md`
- **测试/验收**：
  - 文档能回答：谁创建任务、谁推进 step、谁写 terminal、谁发 callback
  - 明确 taskwatcher 仅 external observer
- **依赖**：E2-T1
- **建议执行顺序**：06

## E3-T2 最小 scheduler / dispatcher 实现 [CODE] [并行：否]
- **目标**：提供一个最小 dispatcher，能按 workflow definition 顺序推进 step。
- **范围**：
  - immediate step dispatch
  - waiting_human / waiting_subagent terminal 的暂停与恢复
  - next-step selection
- **不做项**：
  - 不做 cron 级长期排程
  - 不做复杂优先级队列
- **产物**：
  - scheduler/dispatcher 模块
  - 本地 sample runner
- **测试/验收**：
  - `chain` 能自动推进到最后一步
  - `waiting_human` / `waiting_subagent` 时不会误推进下一步
- **依赖**：E2-T2、E4-T2
- **建议执行顺序**：09

## E3-T3 subagent dispatch adapter 升格 [CODE] [并行：否]
- **目标**：把当前 `poc/subagent_bridge_sim/` 的关键能力升格成可复用 adapter。
- **范围**：
  - `subagent.spawn`
  - `subagent.await_terminal`
  - `child_session_key -> task_id` 反查索引
- **不做项**：
  - 不做 ACP 主链
  - 不做 taskwatcher primary tracking
- **产物**：
  - 复用型 subagent adapter 模块
  - README / example input-output
- **测试/验收**：
  - spawn 成功后 registry 中能看到 `runtime=subagent`
  - terminal 到达后同一 `task_id` 能被收敛
- **依赖**：E1-T3、E4-T2
- **建议执行顺序**：10

## E3-T4 外部 dispatch / reconcile 对接策略 [DOC+CODE] [并行：条件可]
- **目标**：定义何时需要把任务交给 external watcher / dispatch consumer，而不是全部压在薄层调度器里。
- **范围**：
  - external async adapter 接口
  - reconcile 入口
  - 与 taskwatcher 的 compatibility contract
- **不做项**：
  - 不把 taskwatcher 重新升格为 backbone
  - 不重写旧 dispatch consumer
- **产物**：
  - 对接策略文档
  - 最小 compatibility shim（如需要）
- **测试/验收**：
  - 至少 1 条 external-like stub 任务能被登记为 waiting_external，并由 reconcile 收口
- **依赖**：E3-T1、E4-T3
- **建议执行顺序**：15

---

# Epic 4：State / Callback（统一真值与回调）

## Epic 验收标准

- minimal task registry 从“P0 文档 + 示例”升级为可复用状态库。
- `state` 与 `callback_status` 严格分离。
- terminal ingest、callback send、callback ack/fail 都能通过统一接口推进。

## E4-T1 minimal registry / callback canonical 文档冻结 [DOC] [并行：可]
- **目标**：把 registry 与 callback 语义固定成单一真值来源。
- **范围**：
  - 6 字段 schema 的继续冻结或升级条件
  - `state` / `callback_status` 语义边界
  - atomic patch / merge 规则
- **不做项**：
  - 不在 P0/P1 直接扩成大而全 schema
  - 不引入 DB-first 方案
- **产物**：
  - `docs/state-and-callback-contract.md`
  - 如有需要，更新 `schemas/minimal-task-registry.schema.json`
- **测试/验收**：
  - 文档明确列出所有合法状态流转
  - 与 `docs/validation/p0-task-registry.md`、`docs/validation/p0-5-callback-status.md` 不矛盾
- **依赖**：无
- **建议执行顺序**：07

## E4-T2 Registry Library（upsert / patch / atomic write）[CODE] [并行：否]
- **目标**：提供一个可复用 registry library，替代多个 POC 各自手写 JSON patch。
- **范围**：
  - upsert / patch / merge
  - atomic write
  - evidence merge 规则
- **不做项**：
  - 不做数据库
  - 不做复杂索引服务
- **产物**：
  - registry library 模块
  - 示例存储目录结构
- **测试/验收**：
  - 并发写入至少有最小保护（原子写 / 版本校验其一）
  - `state` 和 `callback_status` 更新互不覆盖
- **依赖**：E4-T1
- **建议执行顺序**：08（可与 E2-T3 协调）

## E4-T3 Terminal ingest + callback outbox [CODE] [并行：否]
- **目标**：把 terminal 事件归一化、写 registry、再由 callback stage 推进，不再混在单个 runner 里。
- **范围**：
  - terminal envelope normalize
  - callback outbox / send stage
  - ack / failed stage patch
- **不做项**：
  - 不接真实 provider retry engine
  - 不做完整 DLQ
- **产物**：
  - terminal ingest 模块
  - callback outbox / envelope 示例
- **测试/验收**：
  - `completed + pending -> completed + sent -> completed + acked`
  - `failed + pending -> failed + failed`
- **依赖**：E4-T2、E3-T3
- **建议执行顺序**：11

## E4-T4 Human decision payload verifier / resume gate [CODE] [并行：条件可]
- **目标**：把 human-gate 的 decision payload 校验、resume token 校验、resolution 写回逻辑独立成可复用组件。
- **范围**：
  - task_id / resume_token 校验
  - approve / reject / timeout / withdraw 解析
  - registry 写回规范
- **不做项**：
  - 不做真实 Discord/browser provider 接线
  - 不引入第二套 human registry
- **产物**：
  - verifier / resolver 模块
  - 示例 payload 与错误样例
- **测试/验收**：
  - 4 类 verdict 全覆盖
  - task_id / token 不匹配时拒绝 resume
- **依赖**：E2-T3、E4-T2
- **建议执行顺序**：13

---

# Epic 5：workspace-trading 首个 Workflow（Pilot）

## Epic 验收标准

- 选出 1 条**离线、可回退、无真实交易副作用**的 workspace-trading workflow 作为 pilot。
- 该 workflow 能跑通：workflow model → scheduler/dispatch → subagent → terminal/state → callback。
- Pilot 产物和 runbook 能交给后续 subagent 重复执行。

## E5-T1 选型并冻结 trading pilot workflow [DOC] [并行：可]
- **目标**：冻结首个 pilot，不再让“首条 workflow 做什么”持续摇摆。
- **范围**：
  - 推荐首选：**离线策略实验闭环**
    - 输入实验 brief
    - 在 `workspace-trading` 派发 subagent 执行离线实验/测试
    - 收集 artifact/report
    - 可选 human gate 决定“继续/降级/终止”
  - 定义 I/O、风险边界、回退方式
- **不做项**：
  - 不接真实下单
  - 不改线上 gateway / 盘中执行逻辑
- **产物**：
  - `docs/workspace-trading-first-workflow.md`
- **测试/验收**：
  - 文档明确输入、执行步骤、产物目录、失败回退口径
  - 明确禁止 live trading side effect
- **依赖**：E2-T1、E3-T1
- **建议执行顺序**：14

## E5-T2 实现 trading pilot workflow definition + adapter binding [CODE] [并行：否]
- **目标**：在 orchestration repo 内提供可运行的 trading pilot workflow definition 与 adapter 绑定。
- **范围**：
  - workflow definition 文件
  - subagent step 指向 `workspace-trading`
  - artifact collection step
- **不做项**：
  - 不直接改策略逻辑本身
  - 不处理多策略并发编排
- **产物**：
  - pilot workflow definition
  - 示例输入 / expected outputs
- **测试/验收**：
  - 本地或模拟环境能完成一次 dry-run
  - registry 能完整记录 `task_id -> subagent -> terminal -> callback`
- **依赖**：E3-T2、E3-T3、E4-T3、E5-T1
- **建议执行顺序**：16

## E5-T3 workspace-trading 集成验收 harness [DOC+CODE] [并行：条件可]
- **目标**：为 workspace-trading 首个 workflow 提供可重复的验收入口，而不是靠人工口头复盘。
- **范围**：
  - dry-run / sample input
  - artifact checklist
  - regression command
- **不做项**：
  - 不做生产部署
  - 不做跨 repo 自动 PR 流水线
- **产物**：
  - `docs/workspace-trading-pilot-runbook.md`
  - 自动化或半自动验收脚本
- **测试/验收**：
  - 能一键或一步命令重放 dry-run
  - 产物检查项固定，包括 report / evidence / callback state
- **依赖**：E5-T2
- **建议执行顺序**：17

---

# Epic 6：Observability（事件、时间线、健康度）

## Epic 验收标准

- 每条 workflow 都能看到统一 timeline，而不是散落在多个 JSON/日志里。
- 至少能看见：当前 backlog、terminal 延迟、callback 失败、卡住任务。
- Pilot workflow 的问题可以靠 timeline 快速定位，不依赖大量人工 grep。

## E6-T1 Event model / timeline 规范冻结 [DOC] [并行：可]
- **目标**：把 proposal 中的事件名与 timeline 口径固定成可实现的最小事件模型。
- **范围**：
  - 事件列表
  - 最小字段集
  - timeline view / health view / audit view
- **不做项**：
  - 不做大屏 UI
  - 不接真实 metrics 平台
- **产物**：
  - `docs/observability-contract.md`
- **测试/验收**：
  - 至少覆盖：TaskCreated / StepDispatched / ActivityStarted / TerminalObserved / CallbackSent / CallbackAcked / WorkflowCompleted
- **依赖**：E4-T1
- **建议执行顺序**：10（可与 E4-T3 前后协调）

## E6-T2 Timeline writer / assembler [CODE] [并行：条件可]
- **目标**：把 registry、terminal、callback、scheduler 事件聚合成单条 timeline。
- **范围**：
  - event append
  - timeline assemble
  - human-readable summary export
- **不做项**：
  - 不做复杂查询后端
  - 不做实时 websocket 面板
- **产物**：
  - event/timeline 模块
  - timeline sample outputs
- **测试/验收**：
  - 单条任务至少可生成一份 timeline JSON 和一份 markdown summary
  - 事件顺序在 success / failure path 下均正确
- **依赖**：E3-T2、E4-T3、E6-T1
- **建议执行顺序**：18

## E6-T3 健康度与 backlog 视图 [CODE] [并行：条件可]
- **目标**：给实施期最需要的 3 个健康视图：活跃任务、卡住任务、callback 失败任务。
- **范围**：
  - backlog summary
  - stuck task detection
  - callback failure report
- **不做项**：
  - 不做 Grafana/Prometheus 正式集成
  - 不做告警自动升级系统
- **产物**：
  - CLI 或脚本视图
  - 样例报表
- **测试/验收**：
  - 对样例数据能正确识别 waiting 过久 / callback failed / terminal missing
- **依赖**：E6-T2
- **建议执行顺序**：19

---

# Epic 7：Optional Guards（可选保护栏）

## Epic 验收标准

- guards 不改变主设计方向，但能在 pilot 前提供最低限度的风险收敛。
- feature flag、workspace 边界、幂等/重复执行保护至少覆盖最常见误用。
- 所有 guards 都应是**可开关、可回退**，不阻塞核心路径调试。

## E7-T1 Guard Matrix 与启用策略 [DOC] [并行：可]
- **目标**：明确哪些 guard 是 P0/P1 必开，哪些是 optional。
- **范围**：
  - feature flag
  - workspace boundary
  - duplicate callback / duplicate resume
  - timeout / manual override / kill switch
- **不做项**：
  - 不先实现全部 guard
  - 不引入重型 policy engine
- **产物**：
  - `docs/guard-matrix.md`
- **测试/验收**：
  - 每个 guard 明确 owner、触发条件、默认开关、回退方式
- **依赖**：E5-T1、E6-T1
- **建议执行顺序**：15（文档可先行）

## E7-T2 Feature flags / kill switch [CODE] [并行：条件可]
- **目标**：允许在官方 runtime、旧 POC harness、新 scheduler 之间快速切换，避免单点卡死。
- **范围**：
  - runtime selection flag
  - pilot enable/disable flag
  - emergency kill switch
- **不做项**：
  - 不做复杂配置中心
  - 不做远程集中控制台
- **产物**：
  - 配置文件或环境变量方案
  - README / runbook 补充
- **测试/验收**：
  - 至少能一键切回旧 POC harness 或禁用 trading pilot
- **依赖**：E1-T3、E3-T2
- **建议执行顺序**：11（可穿插）

## E7-T3 Workspace / idempotency / duplicate guards [CODE] [并行：条件可]
- **目标**：避免最常见的工程事故：写错 repo、重复 callback、重复 resume、重复 dispatch。
- **范围**：
  - `workspace-trading` boundary check
  - duplicate callback / duplicate decision guard
  - duplicate dispatch / terminal replay guard
- **不做项**：
  - 不做全局权限平台
  - 不做复杂分布式锁
- **产物**：
  - guard helper 模块
  - 负例测试
- **测试/验收**：
  - 重复 callback 不会把 acked 覆盖回 sent
  - 错误 workspace 会被拒绝执行
  - 重复 decision payload 会被拒绝或幂等忽略
- **依赖**：E4-T3、E4-T4、E5-T2
- **建议执行顺序**：20

## E7-T4 Timeout / manual override / degraded path [CODE] [并行：条件可]
- **目标**：给 human-gate、subagent await、external waiting 增加诚实降级而非假完成的保护机制。
- **范围**：
  - timeout to degraded/failed policy
  - manual override record
  - reason/evidence patch 规范
- **不做项**：
  - 不做自动自愈编排系统
  - 不做复杂 SLA 调优
- **产物**：
  - timeout / override helpers
  - 样例 degraded evidence
- **测试/验收**：
  - await 超时时进入 `degraded` 或 `failed`，而不是 silent success
  - manual override 会留下 evidence 与 timeline 记录
- **依赖**：E3-T2、E4-T3、E6-T2
- **建议执行顺序**：21

---

## 推荐执行批次（便于后续派发 subagent）

### Batch A：先冻结口径（可高并行）
- E1-T1
- E2-T1
- E3-T1
- E4-T1
- E5-T1
- E6-T1
- E7-T1

### Batch B：把“官方底座 + registry + scheduler”连成主干
- E1-T2
- E1-T3
- E4-T2
- E3-T2
- E3-T3
- E4-T3

### Batch C：补全模板与人机交互
- E2-T3
- E4-T4
- E2-T4

### Batch D：做首个真实 pilot
- E5-T2
- E5-T3

### Batch E：可观测性与保护栏收尾
- E6-T2
- E6-T3
- E7-T2
- E7-T3
- E7-T4

---

## 不进入本轮 backlog 的事项

1. Temporal 生产级接入
2. LangGraph 作为公司级 backbone
3. 通用 DAG / 动态图引擎
4. 真实交易执行 / 线上 gateway 变更
5. 完整多租户权限系统
6. 完整 callback retry/DLQ 平台化

---

## Done 的统一判定口径

任一代码任务完成，必须同时满足：

1. **产物存在**：代码/文档/样例/配置文件已落 repo
2. **测试通过**：至少有 targeted tests 或 dry-run evidence
3. **状态收敛**：若涉及 workflow，能看到 terminal / callback 真值
4. **回退明确**：feature flag、fallback 路径或 manual rollback 已写明
5. **不越界**：不把 taskwatcher 重新写成 backbone，不把 trading pilot 扩成 live trading
ve trading
