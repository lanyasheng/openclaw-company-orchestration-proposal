# 支撑材料：Thin Orchestration Layer 设计口径

## 结论先行

**Thin Orchestration Layer 不是一个新平台名称，而是我们在官方底座层之上补的最小控制层。**

它只解决五件事：
1. task registry
2. state machine
3. workflow templates
4. callback / outbox / delivery audit
5. timeline / retry / escalation

---

## 1. 为什么需要 thin layer

如果只有官方底座层和执行层，会出现：
- runtime 各自定义状态
- terminal 与 callback 混写
- business flow 只能复制脚本
- human-gate、失败分支、重试策略无法沉淀为统一协议

所以必须有一层“轻控制、强边界”的控制面。

---

## 2. 这层不做什么

- 不做通用 DAG 引擎
- 不做任意动态图调度
- 不接管所有 runtime 实现细节
- 不要求一上来支持所有复杂模板

---

## 3. P0 / P1 应支持的模板

### 先支持
- CHAIN
- HUMAN_GATE
- FAILURE_BRANCH（优先走控制层策略 / adapter 路线）

### 后支持
- PARALLEL（待真实能力证明）
- JOIN（待真实能力证明）

---

## 4. 这层和 Lobster 的关系

- Lobster 属于**官方底座层的 workflow shell**
- Thin orchestration layer 属于**公司自己的编排控制层**
- 两者是上下层关系，不是替代关系

---

## 5. 最终口径

**P0/P1 的重点不是“发明一个新引擎”，而是用最小控制层把官方原语接成公司可复用的 workflow engine。**
