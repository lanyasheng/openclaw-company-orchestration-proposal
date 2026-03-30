# Trading Current Chain Mapping v1 (2026-03-30)

> 状态: draft-v1 / mapping bootstrap
> 目标: 把 `workspace-trading` 当前散落的链路映射到 control plane task schema / truth_domain / stage model。

---

## 1. 当前链路分层

### A. Core research engine
- `research/v2_portfolio/*`
- `research/data_portal/*`

映射:
- task_type: `research` / `engineering`
- truth_domain: `strategy` / `data`
- owner: `trading`
- executor: `subagent` or `claude_code`
- backend: `subagent` by default

### B. Runtime tools
- `skills/trading-quant/scripts/intraday_monitor.py`
- `skills/trading-quant/scripts/macro_linkage.py`

映射:
- task_type: `ops`-like runtime task（v1 先落到 `integration` / `execution_prep`）
- truth_domain: `ops`
- owner: `trading`
- executor: `subagent` / `tmux`
- backend: `tmux` if requires monitoring

### C. Input adapters
- theme/news/sentiment adapters
- `feat/real-theme-source-minimal-20260322` 中可复用的最小代码

映射:
- task_type: `integration`
- truth_domain: `adapter`
- owner: `trading`
- executor: `claude_code`
- backend: `subagent`

### D. Repo governance
- branch recovery
- worktree cleanup
- archive / tmp cleanup

映射:
- task_type: `governance`
- truth_domain: `repo`
- owner: `main`
- executor: `subagent`
- backend: `subagent`

---

## 2. v1 首批要接 control plane 的链路

1. capital-flow contract fix
2. strategy acceptance rerun
3. repo closure / branch recovery
4. theme source minimal rescue (selective)
5. intraday monitor / macro linkage runtime ownership split

---

## 3. 立即不接入的链路

1. KOL source search branch
2. alert delivery feature branch
3. tmp / experimental scripts
4. live trading execution

---

## 4. 下一步

1. 为上面 5 条首批链路逐条生成标准 task schema
2. 补 dashboard 字段映射
3. 补 callback / closeout / next-step contract 映射
