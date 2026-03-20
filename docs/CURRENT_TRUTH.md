# CURRENT_TRUTH（2026-03-20）

> 用途：给这个 proposal repo 一个**当前真值入口**，避免旧计划文档、旧评审结论、旧 POC 设计稿继续被误读成“今天的默认口径”。
>
> 基线：proposal 仓已同步到 `57562f1` 之后，本页补入本轮 continuation / whitelist / tmux backend 的最新治理口径。

---

## 1. 当前仓库应该怎样理解

这个仓库现在的主定位仍然是：

> **OpenClaw 公司级编排 / workflow engine 的方案仓 + 最小验证资产仓。**

它不是：
- 生产 runtime 真代码仓
- “已经默认全自动闭环”的完成态说明
- 任一单个 human-gate / POC / 旧计划文档的主语

当前正确总口径仍是：
- **thin bridge**
- **allowlist**
- **safe semi-auto**
- 默认优先可回退，而不是默认全量放权

---

## 2. 本轮必须同步的 live 真值

### 2.1 已出现两条真实 continuation 场景

1. **`trading_roundtable` continuation 已最小落地**
   - 这说明 proposal 主线不再只是纸面设计。
   - 但当前仍不是“trading 全面 workflow engine 化已完成”。

2. **`channel_roundtable` 已落地为通用最小适配器**
   - 当前 `Temporal vs LangGraph｜OpenClaw 公司级编排架构` 频道已成为**第二个真实场景**。
   - 这条线证明 continuation 不再只服务 trading 单点。

### 2.2 当前默认 dispatch 口径

| 场景 | 当前默认 | 说明 |
|------|----------|------|
| 当前架构频道（白名单） | `triggered` | 默认 auto-dispatch |
| 其他普通频道 | `skipped` | 默认不自动续跑 |
| trading continuation | **仅 clean PASS 默认 `triggered`** | 其他结果继续默认 `skipped` |

这条口径要连起来理解：
- **不是全频道放开**
- **不是 trading 任意结果都自动续跑**
- 仍然是白名单 / 条件触发 / 可回退的薄桥策略

### 2.3 tmux backend 的当前状态

`tmux` 现在已经是**正式可选 continuation backend**，但要写清楚边界：

**已成立：**
- 可以作为 continuation backend 选项被正式讨论和接入
- 适合需要中间态可见性、可 attach、可人工介入的场景
- 与“safe semi-auto”口径兼容，因为它天然保留了更强的人工观察与回退空间

**还不能夸大成：**
- trading 真实 artifact-backed clean PASS 已经跑通
- trading 已有完整 tmux-backed 自动闭环
- tmux backend 已经覆盖所有频道 / 所有 continuation 变体

**当前最关键边界：**
- trading real run **目前只到 dry-run**
- 真实 **artifact-backed clean PASS** 仍然缺
- 因此 tmux backend 虽已进入正式选项，但仍属于“能力已纳入口径、生产边界仍收紧”的阶段

---

## 3. 当前最容易被旧文档误导的点

### 3.1 不能再把下面这些写成“今天默认已经成立”

- 通用全自动 workflow engine 已完成
- 所有频道默认 auto-dispatch
- trading 任意 PASS 都会自动 continuation
- trading 已完成真实 artifact-backed clean PASS
- tmux 只是临时实验，不属于正式 backend 选项
- 某些 2026-03-19 的评审缺口仍 100% 原样未变化

### 3.2 当前正确写法

- **已有两条真实场景**，但仍是最小接线
- **只有 allowlist / 条件满足时才默认 triggered**
- **trading 当前只对 clean PASS 保持默认 triggered，其余 skipped**
- **tmux 已是正式可选 backend，但 trading real run 仍只到 dry-run**
- **总体仍是 thin bridge / safe semi-auto，不是默认无人值守生产闭环**

---

## 4. 现在应优先看哪些文档

1. `../README.md`
2. `executive-summary.md`
3. `openclaw-company-orchestration-proposal.md`
4. `validation-status.md`
5. `runtime-integration/spawn-interceptor-live-bridge.md`
6. 本页 `CURRENT_TRUTH.md`

如果需要追老证据，再进：
- `validation/`
- `reviews/`
- `poc/`

---

## 5. 已标记为 historical / superseded 的入口

以下内容保留，但**不再应被当成当前默认口径入口**：

| 文档 | 当前状态 | 建议替代阅读 |
|------|----------|--------------|
| `../ROADMAP.md` | historical draft / superseded | `roadmap.md` + 本页 |
| `official-lobster-integration-plan.md` | historical batch1 plan | `../README.md` + `validation-status.md` |
| `validation/p0-minimal-validation-plan.md` | historical pre-live design note | `validation-status.md` + 本页 |
| `reviews/independent-architecture-review-20260319.md` | historical review snapshot | 本页 + `validation-status.md` |

---

## 6. 旧代码 / 旧样例目录的最小治理口径

| 目录 | 当前定位 |
|------|----------|
| `poc/lobster_minimal_validation/` | **legacy fallback + validation asset**；`chain-basic` 不再 canonical |
| `poc/subagent_bridge_sim/` | simulation / evidence asset，不是 live runtime |
| `prototype/callback_driven_orchestrator_v1/` | 原型快照，不等同生产 runtime |

---

## 7. 一句话总口径

**proposal repo 现在已经基本跟上最新真值：它不再只是旧架构设计稿，已经同步了 trading + 当前架构频道两条真实场景，以及 allowlist / clean PASS / tmux backend 的当前边界；但它仍然明确停留在 thin bridge、allowlist、safe semi-auto，而不是默认全自动闭环。**
