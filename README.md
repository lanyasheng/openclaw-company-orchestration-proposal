# OpenClaw Orchestration Control Plane

> A control-plane for multi-agent workflows on top of OpenClaw.
> Default execution path: **subagent**. Optional compatibility path: **tmux**.
> First real validation scenario: **trading continuation**.

---

## 🚀 单入口快速接入（30 秒）

**统一入口命令**: `python3 ~/.openclaw/scripts/orch_command.py`

```bash
# 方式 1: 无参数 = 使用当前频道默认
python3 ~/.openclaw/scripts/orch_command.py

# 方式 2: 指定频道/主题
python3 ~/.openclaw/scripts/orch_command.py \
  --channel-id "discord:channel:YOUR_ID" \
  --channel-name "your-channel" \
  --topic "讨论主题"

# 方式 3: Trading 场景
python3 ~/.openclaw/scripts/orch_command.py --context trading_roundtable

# 方式 4: 保存到文件
python3 ~/.openclaw/scripts/orch_command.py \
  --channel-id "discord:channel:YOUR_ID" \
  --topic "架构评审" \
  --output tmp/orch-contract.json
```

**默认行为**:
- ✅ coding lane → Claude Code (via subagent)
- ✅ non-coding lane → subagent
- ✅ auto_execute=true (自动注册/派发/回调/续推)
- ✅ gate_policy=stop_on_gate (命中 gate 正常停住)
- ✅ 首次接入建议 `--auto-execute false` 先验证稳定

**详细文档**:
- **Skill 入口**: `runtime/skills/orchestration-entry/SKILL.md`
- **其他频道 Quickstart**: `docs/quickstart/quickstart-other-channels.md`
- **当前真值**: `docs/CURRENT_TRUTH.md`

---

## What this repository is

This repository is an attempt to answer a practical question:

**How do you make AI-agent workflows reliable enough to use for real work, without immediately jumping to a heavy workflow engine?**

The answer in this repo is:
- keep **OpenClaw** as the runtime foundation,
- build a thin but explicit **control plane** on top,
- standardize contracts for dispatch, callback, continuation, and execution,
- validate the design in a real business scenario first,
- and only then decide what deserves heavier infrastructure.

This is **not** just a collection of prompts or demos.
It is a working repository for:
- orchestration contracts,
- workflow state and callback handling,
- dispatch planning,
- execution handoff,
- and real integration with OpenClaw subagent execution.

---

## What problem this repository actually solves

This repository solves a very specific class of problems:

> **What should happen after one task finishes, when the real work is still not done?**

In real multi-agent systems, the failure mode is rarely “the model cannot answer.”
The real failure mode is usually one of these:
- a task completes but nobody knows who owns the next step,
- multiple child tasks return but there is no clean fan-in point,
- the system can generate a plan but cannot safely dispatch the next action,
- a callback is emitted but never reaches the right parent or user-visible channel,
- business ownership and execution ownership are mixed together,
- or the system keeps adding more scripts without a stable control plane.

This repository is trying to make those transitions explicit.

It focuses on:
- **how work continues**,
- **how it is registered**,
- **how it is dispatched**,
- **how it is acknowledged**,
- **how it is gated**,
- and **how the next step is decided without losing truth**.

That is why the core objects here are not just prompts or runners, but things like:
- continuation contracts,
- handoff schemas,
- registration and readiness tracking,
- dispatch plans,
- bridge consumption,
- execution requests,
- receipts,
- and callback/ack separation.

---

## Why this is more than harness engineering

Harness engineering is an important part of this repo, but it is **not the whole repo**.

### Harness engineering is the execution layer
That includes things like:
- how Claude Code is invoked,
- how subagents are launched,
- how tmux stays usable as a compatibility path,
- how execution artifacts are captured,
- and how long-running tasks stay observable.

### This repository goes one layer above that
This repo is also building a **workflow control plane**.
That means it defines:
- how work is modeled before execution,
- how ownership is tracked,
- how owner and executor are decoupled,
- how fan-out / fan-in is represented,
- how continuation is gated,
- how receipts and acknowledgements are separated,
- and how the next dispatch is triggered after earlier work returns.

A short way to say it is:

> **Harness engineering answers “how do we run this task?”**
>
> **This repository also answers “how do we keep the workflow moving correctly after tasks begin to branch, return, and hand off?”**

That is why this repo should be read as:
- **control-plane engineering first**,
- with **harness engineering inside the execution layer**.

---

## What we are doing

At a high level, this repo is building a company-grade workflow layer for AI agents.

That means making these things explicit and reusable:
- **what to run next**,
- **why a workflow stopped**,
- **who owns the next step**,
- **when a task is safe to auto-dispatch**,
- **how completion gets back to the parent session**,
- **how to move from planning → registration → execution**,
- and **how to keep all of that observable and testable**.

In concrete terms, this repo already includes:
- a continuation contract,
- a planning handoff schema,
- registration and readiness tracking,
- bridge consumer auto-trigger decisions,
- execution request generation,
- real `sessions_spawn` integration,
- and dual-track backend support:
  - **subagent** as the default execution path,
  - **tmux** as a compatibility path for observable interactive sessions.

---

## What this repository brings

If you are building agent workflows, this repo is useful because it tries to solve the problems that usually make multi-agent systems feel flaky:

### 1. It separates control from execution
Instead of burying workflow decisions inside ad-hoc scripts, it keeps:
- planning,
- dispatch,
- callback,
- continuation,
- and execution
as different layers with explicit contracts.

### 2. It treats workflow state as first-class
This repo does not assume “task finished” means “business is done.”
It explicitly distinguishes:
- terminal state,
- callback sent,
- callback acknowledged,
- next-step registration,
- and final closeout.

### 3. It gives you a thin path before a heavy engine
Many teams jump too early into Temporal-style complexity, or stay stuck in script spaghetti.
This repo explores the middle path:
- enough structure to be reliable,
- not so much machinery that iteration stops.

### 4. It is validated in a real scenario
The first serious validation path is **trading continuation**.
That matters because the repo is not only theoretical; it has already been forced to deal with:
- gated continuation,
- real dispatch artifacts,
- real execution,
- completion delivery,
- and legacy cleanup under production constraints.

### 5. It stays compatible while migrating forward
The current strategy is deliberately **dual-track**:
- **subagent** is the default and recommended path for new work,
- **tmux** remains supported where interactive observation still matters.

So the repo is not forcing a breaking migration before the system is ready.

---

## What inspired it

This repository is not a clone of any single framework.
It borrows ideas from several places, but keeps its own boundary.

### OpenClaw native runtime
OpenClaw is the foundation.
This repo builds on:
- sessions,
- tools,
- callbacks,
- subagents,
- messaging,
- and plugin hooks.

### Temporal
Temporal influences the thinking around:
- durable workflow state,
- explicit boundaries between orchestration and execution,
- retries / recovery / lifecycle semantics,
- and treating workflow progression as a real system concern.

But this repo does **not** currently adopt Temporal as the system backbone.

### LangGraph
LangGraph influences the thinking around:
- graph-shaped control flow,
- explicit node transitions,
- and composable reasoning/execution steps.

But LangGraph is treated here as a possible leaf-layer technique, **not** as the company-wide control plane.

### Lobster / workflow-shell style tools
Lobster-like workflow-shell ideas influenced:
- approval boundaries,
- thin orchestration shells,
- invoke bridges,
- and explicit workflow contracts.

### DeepAgents
DeepAgents influenced the thinking around:
- execution profiles for coding-heavy agent work,
- clearer separation between orchestration policy and leaf execution behavior,
- observable long-running agent work,
- and keeping agent execution practical before introducing heavier infrastructure.

But this repo does **not** treat DeepAgents as the company-wide control plane.
It is closer to a reference point for execution patterns and evaluation, not the orchestration backbone.

### OpenSWE / SWE-agent style systems
OpenSWE- and SWE-agent-like systems influenced the thinking around:
- issue-to-patch lanes,
- engineering-task packaging,
- reproducible execution envelopes,
- and how coding agents can be plugged into a larger workflow.

But here they are treated as:
- leaf execution inspirations,
- benchmarking references,
- or future narrow lanes,

not as the main workflow control plane for the company.

### Practical production debugging
A lot of the shape of this repo came from real problems:
- tasks completing without visible user acknowledgement,
- callbacks not bubbling to the right parent,
- dispatch plans existing but not executing,
- tmux compatibility hanging around longer than expected,
- docs drifting away from reality,
- and tests that passed locally but did not reflect the real lifecycle.

---

## What this repository is not

To understand the repo, it is equally important to say what it is **not**:

- It is **not** a generic DAG platform.
- It is **not** trying to replace OpenClaw.
- It is **not** a LangGraph wrapper.
- It is **not** a Temporal deployment template.
- It is **not** a DeepAgents fork.
- It is **not** an OpenSWE / SWE-agent replacement.
- It is **not** just a trading bot repo.
- It is **not** a pile of isolated POCs anymore.

The current intent is much narrower and more practical:

> **A reusable workflow control-plane on top of OpenClaw, validated first through trading continuation, but designed to stay generic.**

---

## Current status

### Confirmed
- trading continuation has entered the **real execution path**,
- the control-plane main chain is in place,
- subagent is the default path,
- tmux remains supported as a compatibility path,
- legacy docs / POCs / stale tests have been cleaned up,
- and the repository has been cleaned for open-source publication.

### Current backend policy
- **Default:** `subagent`
- **Compatibility:** `tmux`
- **New development:** should prefer `subagent`
- **Existing interactive/observable flows:** may still use `tmux`

### Current maturity
A fair description today is:

> **thin bridge / explicit contracts / safe semi-auto / production-validated on one real scenario**

This repo is further along than a proposal, but still intentionally earlier than a fully general-purpose workflow platform.

---

## Repository structure

```text
openclaw-company-orchestration-proposal/
├── README.md
├── docs/
├── runtime/
├── tests/
├── archive/
└── scripts/
```

### `docs/`
Human-facing documentation:
- current truth,
- architecture,
- migration/retirement notes,
- release materials,
- batch summaries.

### `runtime/`
The actual orchestration runtime and integration code:
- contracts,
- continuation handling,
- dispatch planning,
- bridge consumer,
- sessions spawn integration,
- backend strategy.

### `tests/`
Behavioral proof.
This repo treats tests as a source of truth, not just packaging hygiene.

### `archive/`
Historical material kept for reference, not for the active path.

---

## Where to start

### If you want the fast overview
Read:
- [`docs/executive-summary.md`](docs/executive-summary.md)
- [`docs/CURRENT_TRUTH.md`](docs/CURRENT_TRUTH.md)

### If you want the architecture
Read:
- [`docs/architecture-layering.md`](docs/architecture-layering.md)

### If you want the release / publishing material
Read:
- [`docs/release/open-source-release-kit.md`](docs/release/open-source-release-kit.md)

### If you want the current migration / retention boundary
Read:
- [`docs/migration/migration-retirement-plan.md`](docs/migration/migration-retirement-plan.md)
- [`docs/technical-debt/technical-debt-2026-03-22.md`](docs/technical-debt/technical-debt-2026-03-22.md)

---

## How to think about the repo in one sentence

If you only keep one line in your head, make it this:

> **This repository is building a practical orchestration control-plane for OpenClaw, with subagent as the default execution path, tmux as a compatibility path, and trading as the first real proving ground.**
