# 回调驱动编排器 v1（proposal repo 同步快照）

> 这是从最近已落地原型同步过来的**最小必要快照**，用于让 proposal 仓直接反映这轮主线推进。
>
> - 原型来源：`orchestrator` 仓
> - 同步基线：commit `64da26e`
> - 这里保留的是：**状态机 / batch fan-in 汇总 / 决策器 / CLI**
> - 这里故意不保留的是：与生产 runtime 深度耦合的 hook/plugin 代码

## 这份快照回答什么

它回答的是：

1. **callback-driven orchestrator v1 已经长什么样**
2. **最小闭环已经推进到哪里**
3. **它和 proposal 仓现有 `orchestration_runtime/` 是什么关系**

一句话：

> `orchestration_runtime/` 代表 proposal 仓里的**控制层 contract / scheduler / adapter 主线**；
> `prototype/callback_driven_orchestrator_v1/` 代表这轮新增的**batch callback → summary → decision** 原型快照。

---

## 原型范围

### 已包含

- `state_machine.py`：任务状态机
- `batch_aggregator.py`：batch fan-in 汇总
- `orchestrator.py`：决策器与下一轮派发接口
- `cli.py`：最小 CLI
- `__init__.py`：模块导出

### 故意未包含

- `spawn-interceptor` 里的 live runtime hook 实现
- 任何与 production Gateway / plugin 生命周期强绑定的文件
- 自动派发下一轮到真实 `sessions_spawn` 的生产接线代码

这些内容的说明见：
`../../docs/runtime-integration/spawn-interceptor-live-bridge.md`

---

## 当前闭环到哪一步

这版原型已经把下面三段做成可读、可跑、可审阅的最小实现：

```text
任务状态登记
  → 子任务回调写入
  → batch 完成判定
  → batch summary 生成
  → decision 产出
```

也就是说，proposal 仓现在不只是“讲架构”，还直接保留了这轮推进的一个具体原型切面。

---

## 状态流转

```text
pending → running → callback_received → next_task_dispatched → final_closed
                              ↓
                         timeout / failed → retrying / abort
```

关键点：
- `callback_received` 被单独建模，不和最终业务关闭态混写
- batch 是否完成由所有 task 是否进入终态决定
- decision 基于 batch summary，而不是基于单个 task 的即时结果拍脑袋判断

---

## 快速查看

在仓库根目录执行：

```bash
python3 prototype/callback_driven_orchestrator_v1/cli.py test
python3 prototype/callback_driven_orchestrator_v1/cli.py list
python3 prototype/callback_driven_orchestrator_v1/cli.py stuck --timeout 60
```

查询单任务：

```bash
python3 prototype/callback_driven_orchestrator_v1/cli.py status <task_id>
```

查询 batch 汇总：

```bash
python3 prototype/callback_driven_orchestrator_v1/cli.py batch-summary <batch_id>
```

做出决策：

```bash
python3 prototype/callback_driven_orchestrator_v1/cli.py decide <batch_id>
```

---

## 核心模块

### `state_machine.py`

统一跟踪任务生命周期，负责：
- create / update / query task state
- batch complete 判定
- batch summary 文件落盘
- timeout / failed / callback_received 等辅助状态更新

### `batch_aggregator.py`

负责：
- 扫描同一 `batch_id` 下的任务
- 汇总成功 / 失败 / 超时
- 提取共同 blocker
- 生成 Markdown summary
- 检测卡住的 batch

### `orchestrator.py`

负责：
- 读取 batch analysis
- 依次套用决策规则
- 产出 `Decision`
- 预留 dispatch callback 接口给下一轮任务派发

内置规则：
- `rule_all_success`
- `rule_has_common_blocker`
- `rule_partial_failure`
- `rule_major_failure`

---

## 它证明了什么

这份同步快照至少证明了两件事：

1. **控制层不只是静态 proposal**，已经有一版真实的 callback-driven prototype
2. **batch fan-in / summary / decision** 这条主线已经从“概念讨论”进入“代码原型”阶段

---

## 它还没有证明什么

这份快照**没有**证明下面这些已经 production-ready：

- 真实 `sessions_spawn` 的全自动下一轮派发
- 多轮闭环在 live runtime 中完全无人值守
- 并发 / join / barrier / DAG 已成熟
- 生产级可恢复性与审计都已收敛

也因此，proposal 仓专门把 runtime integration 说明单独下沉到：
`../../docs/runtime-integration/spawn-interceptor-live-bridge.md`

---

## 与 proposal 仓主线的关系

建议把它看成两层互补资产：

### A. proposal 主线（仓库已有）

- `docs/`：总方案、边界、路线图、验证状态
- `orchestration_runtime/`：控制层 contract / scheduler / adapter 主线

### B. 本次新增同步

- `prototype/callback_driven_orchestrator_v1/`：最近已落地的 callback-driven orchestrator v1 原型快照
- `docs/runtime-integration/spawn-interceptor-live-bridge.md`：live bridge 为什么放在 `spawn-interceptor`，以及当前已接/未接边界

---

## 推荐搭配阅读

1. `../../README.md`
2. `../../docs/validation-status.md`
3. `../../docs/runtime-integration/spawn-interceptor-live-bridge.md`
4. 本目录代码

---

## 当前同步口径

- proposal 仓**已跟上**这轮 orchestrator v1 原型进展
- runtime bridge 的**真实落点**已明确记录为 `spawn-interceptor`
- 分仓边界已经写清：
  - proposal 仓负责方案、最小参考实现、边界说明
  - runtime 仓负责 live hook、生产接线、生命周期管理
