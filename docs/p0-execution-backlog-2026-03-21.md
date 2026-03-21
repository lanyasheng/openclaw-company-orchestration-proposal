# P0 执行 backlog（2026-03-21）

> 用途：把 P0 从“整体计划”收口成可直接执行的 backlog。只回答三件事：先做什么、做到什么算过、在哪一刀停。
>
> 适用范围：仅覆盖本轮 P0 四项，不展开 P1/P2，不讨论框架偏好。

---

## 0. 执行顺序与 cut line

### 默认执行顺序

1. **planning default freeze**
2. **continuation contract v1**
3. **heartbeat boundary freeze**
4. **issue_to_patch.v1 baseline**

### 为什么这样排

- **1 先于 2**：没有 planning 默认输入，closeout/continuation 只能靠聊天补。
- **2 先于 3**：先明确主链 closeout contract，再冻结 heartbeat 不该做什么。
- **3 先于 4**：先把边界钉死，避免 issue lane baseline 落地时又把 heartbeat 用成 workflow owner。
- **4 最后**：只做一条窄 lane，验证前 3 项 contract 能否被执行线直接消费。

### Cut line

- **Cut line A（输入冻结）**：完成 1 后，后续执行类任务必须默认引用 planning artifact；未引用的实现任务不进入 P0 主线。
- **Cut line B（closeout 冻结）**：完成 2 后，任何 continuation / handoff 相关任务都必须产出 `summary / decision / stopped_because / next_step / next_owner / dispatch_readiness`；缺字段不算完成。
- **Cut line C（边界冻结）**：完成 3 后，heartbeat 不再允许承接 terminal truth / next dispatch / gate ownership；仍靠 heartbeat 补主链逻辑的方案直接出 P0。
- **Cut line D（P0 收口）**：完成 4 且通过最小验收后，P0 才算结束；P1 才能进入 leaf pilot。

### P0 明确不做

- 不扩成多 lane / 通用 DAG / 并发 join
- 不引入 DeepAgents / SWE-agent / LangGraph / Temporal 作为 P0 主线依赖
- 不把 proposal repo 写成 runtime 已完成
- 不先开自动 dispatch，再回头补 contract

---

## 1. planning default freeze

- **目标**
  - 把“非 trivial 任务先有 planning artifact”从口径变成冻结默认，作为后续执行/评审/QA 的统一输入。

- **产物**
  - `planning-default-v1` 文档或模板（字段冻结）
  - 1 份最小示例（feature / bugfix / workflow 任一）
  - proposal repo 入口文档中的链接与一句话口径

- **最小实现**
  - 冻结 planning artifact 最少字段：`problem / scope / non-goals / risks / validation / owner / next_step`
  - 明确适用范围：非 trivial feature、bugfix、workflow 设计
  - 明确豁免范围：一次性小修、小查询、纯状态检查
  - 明确消费方：执行、review、QA 默认引用同一份 planning artifact，而不是各写一版

- **验收标准**
  - 任何新进入 P0/P1 的非 trivial 任务，都能在入口文档中指到唯一 planning artifact
  - planning 字段不再按任务临时发挥
  - 至少 1 个示例能被后续 continuation contract 直接引用，无需重新翻译需求

- **依赖**
  - 无前置依赖；这是 P0 起点

- **风险**
  - 字段过多，导致团队继续跳过 planning
  - 字段过少，无法支撑 handoff / QA
  - “非 trivial”边界不清，造成执行口径不一致

- **建议 owner**
  - **main（spec owner）**，**proposal repo owner（文档落盘）**

---

## 2. continuation contract v1

- **目标**
  - 把“任务为什么停、谁该接、能不能继续 dispatch”冻结成统一 closeout contract，结束靠聊天猜下一步的状态。

- **产物**
  - `continuation-contract-v1` 文档（字段、语义、状态边界）
  - 1 份 closeout 示例（建议 JSON + 人类可读摘要）
  - 与现有 callback/status 语义的映射说明

- **最小实现**
  - 冻结以下必填字段：
    - `summary`
    - `decision`
    - `stopped_because`
    - `next_step`
    - `next_owner`
    - `dispatch_readiness`
  - 给出 `dispatch_readiness` 最小枚举：`ready / blocked / human_gate / not_applicable`
  - 明确 `terminal state`、`callback sent`、`acked`、`dispatch readiness` 不是同一件事
  - 约定 closeout 缺字段时的处理：视为未达 continuation-ready

- **验收标准**
  - 任一子任务结束后，可以不看聊天上下文，只看 closeout 就回答：为什么停、谁接、现在能不能继续
  - callback/status 文档与 continuation contract 不冲突
  - 至少 1 个真实任务类型（建议 coding lane）可直接消费该 contract

- **依赖**
  - 依赖 **planning default freeze** 提供稳定输入字段

- **风险**
  - 字段名冻结过早，与 runtime 现状脱节
  - 把 summary 写成 narrative，仍然无法自动判定下一步
  - `dispatch_readiness` 与审批/人工 gate 边界混淆

- **建议 owner**
  - **orchestration/runtime owner（contract owner）**，**main（验收口径）**

---

## 3. heartbeat boundary freeze

- **目标**
  - 把 heartbeat 的职责固定在外环治理，明确禁止其接管主链状态推进，避免“看起来自动化，实际上多了一套隐形状态机”。

- **产物**
  - `heartbeat-boundary-freeze` 文档
  - allow / deny 清单（heartbeat 能做什么、不能做什么）
  - 与 TEAM_RULES / runtime governance 的对齐说明

- **最小实现**
  - 明确 heartbeat **允许**：wake、liveness、巡检、催办、告警、请求重查
  - 明确 heartbeat **禁止**：写 terminal truth、直接 dispatch 下一跳、接管 human gate、覆盖 closeout owner 判断
  - 明确若 heartbeat 发现异常，输出应是“提醒/重查请求”，而不是“状态改写/继续执行”
  - 将该边界写入 proposal repo canonical 文档入口

- **验收标准**
  - 任一 heartbeat 相关设计评审都能用 allow / deny 清单快速判定是否越界
  - continuation 主链不再依赖 heartbeat 补写 `next_step` 或 `next_owner`
  - proposal repo 的主线文档不再出现“heartbeat 驱动 workflow”式表述

- **依赖**
  - 依赖 **continuation contract v1**，否则无法明确 heartbeat 与主链的分工边界

- **风险**
  - 边界写得太原则化，实施时继续打擦边球
  - 将 watchdog / reconcile 与 heartbeat 混成一个概念
  - 线上已有薄桥逻辑表述不一致，造成误读

- **建议 owner**
  - **ops / governance owner（边界 owner）**，**main（质量门）**

---

## 4. issue_to_patch.v1 baseline

- **目标**
  - 冻结第一条可执行 coding continuation 窄 lane，证明 planning + closeout + boundary 三件套能被实现线直接消费。

- **产物**
  - `issue_to_patch.v1` baseline 文档（输入 / 输出 / stop conditions / acceptance）
  - 1 份最小样例（单 issue、单 repo、单 acceptance）
  - 需要时附 1 份 handoff 示例：planning → execution → closeout

- **最小实现**
  - 冻结 lane 范围：**单 issue / 单仓 / 单 patch / 单 acceptance**
  - 冻结输入最小集：issue 描述、repo/workdir、acceptance、约束、planning artifact 引用
  - 冻结输出最小集：patch / diff、测试结果、closeout contract、是否 ready for next dispatch
  - 明确 stop conditions：缺 planning、缺 acceptance、测试未跑、需要人工 gate 时均不得冒充 ready
  - 不扩到多 issue、跨仓、自动合并、自动发布

- **验收标准**
  - 新实现线接到 `issue_to_patch.v1` 后，不靠额外口头解释即可开始工作
  - 结束时能稳定产出 patch 证据 + 测试结果 + continuation closeout
  - lane 失败时也能明确给出 `stopped_because / next_owner`，而不是只报“失败了”

- **依赖**
  - 依赖 **planning default freeze**
  - 依赖 **continuation contract v1**
  - 应受 **heartbeat boundary freeze** 约束

- **风险**
  - baseline 写成“万能 coding lane”，范围失控
  - 输入字段过松，执行线仍需二次澄清
  - 把 acceptance 与 PR-ready / merge-ready 混为一谈

- **建议 owner**
  - **coding lane owner（baseline owner）**，**runtime adapter owner（接线）**，**main（验收）**

---

## 5. 交付节奏（可直接照此开工）

### Batch A：先冻结输入与 closeout（必须先完成）

- [ ] 完成 `planning default freeze`
- [ ] 完成 `continuation contract v1`

**批次出口**：任何非 trivial 执行任务都已有统一输入与统一 closeout 字段。

### Batch B：再冻结治理边界（不能跳过）

- [ ] 完成 `heartbeat boundary freeze`

**批次出口**：heartbeat 不再被当成 continuation owner 或状态机替身。

### Batch C：最后打一条窄 lane（P0 收口）

- [ ] 完成 `issue_to_patch.v1 baseline`
- [ ] 用 1 个最小样例走通 planning → execution → closeout

**批次出口**：P0 形成“有输入、有 closeout、有边界、有第一条可消费 lane”的闭环。

---

## 6. P0 结束定义

只有同时满足以下四条，P0 才算完成：

1. planning artifact 已冻结为默认输入；
2. continuation closeout contract v1 已冻结并可独立阅读；
3. heartbeat 边界已冻结，且不再承担主链推进；
4. `issue_to_patch.v1` 作为第一条窄 lane 已可被实现线直接消费。

**未同时满足前，不进入 P1 leaf pilot。**
