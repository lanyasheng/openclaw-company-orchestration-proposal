# OpenClaw Orchestration Control Plane

> A control-plane for multi-agent workflows on top of OpenClaw.
> Default execution path: **subagent**. Optional compatibility path: **tmux**.
> First real validation scenario: **trading continuation**.

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
- [`docs/open-source-release-kit.md`](docs/open-source-release-kit.md)

### If you want the current migration / retention boundary
Read:
- [`docs/migration-retirement-plan.md`](docs/migration-retirement-plan.md)
- [`docs/technical-debt-2026-03-22.md`](docs/technical-debt-2026-03-22.md)

---

## How to think about the repo in one sentence

If you only keep one line in your head, make it this:

> **This repository is building a practical orchestration control-plane for OpenClaw, with subagent as the default execution path, tmux as a compatibility path, and trading as the first real proving ground.**
