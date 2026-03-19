# 支撑材料：现成方案 Shortlist

## 结论先行

**现成方案不是用来“二选一拍板替换 OpenClaw”，而是用来确定每一层该复用什么。**

---

## 1. Lobster

### 定位

- 属于**官方底座层**可复用能力
- 适合作为薄 workflow shell / macro engine
- 不应被直接写成公司级 backbone

### 已知适合

- 顺序 chain
- approval / resume
- OpenClaw tool invoke bridge
- 低侵入、本地优先验证

### 已知边界

- 真并发 / 真 join 还未证明
- 原生 failure-branch 还未证明
- 真实 `subagent` 完整闭环仍待验证

### 当前结论

**P0 / P1 优先复用，但上层仍要建立我们自己的编排控制层。**

---

## 2. Temporal

### 定位

- 属于**P2 以后选择性引入的 durable execution 能力**
- 不是当前主线

### 适合场景

- 跨天流程
- 强恢复 / 强审计 / 强 SLA
- 需要 timer / signal / compensation

### 当前不作为主线的原因

- 引入成本高
- worker / determinism / versioning 负担重
- 当前业务证据不足以 justify 全量上马

### 当前结论

**保留为 P2 选项，而不是 P0/P1 主轴。**

---

## 3. LangGraph

### 定位

- 属于**agent 内部 reasoning / checkpoint / HITL 子图能力**
- 不进入公司级 workflow backbone 位置

### 适合场景

- 单 agent 内部复杂推理
- tool routing
- checkpoint / reflection

### 当前结论

**按需使用，但不进入公司级控制面。**

---

## 4. taskwatcher

### 定位

- 属于**external watcher / reconciler / callback sidecar**
- 不是 state-of-truth
- 不是 orchestration backbone

### 正确职责

- 消费状态变化
- 触发 callback / escalation
- 参与 reconcile

### 当前结论

**保留，但严格降回 watcher 位置。**

---

## 5. 最终 Shortlist 口径

| 方案 | 应放位置 | 当前判断 |
|------|----------|----------|
| Lobster | 官方底座层 | P0/P1 优先复用 |
| Temporal | 执行层增强（P2） | 选择性引入 |
| LangGraph | agent 内部子图 | 只做内部能力 |
| taskwatcher | watcher / reconciler | 不当 backbone |

**关键点：不是选“谁统治全局”，而是选“每一层复用谁”。**
