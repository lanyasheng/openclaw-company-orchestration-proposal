# Hook Guard Capabilities

Use this reference when the issue is about:
- orchestration completion not visibly landing
- subagent terminal/completion receipt
- orphan task / stale task / lost task
- roundtable ack / missing completion reply
- waiting anomaly (`waiting` but leaf already dead or inactive)

Important:
- These capabilities are **not implemented by the skill itself**.
- They live in **runtime hook / orchestrator code**.
- This reference exists so an agent can **discover** that the capabilities already exist and know where to look.

## What exists today

### 1. Completion delivery receipt guard
Primary path for internal subagent completion:
- `spawn-interceptor`: `subagent_ended -> onTaskCompleted -> before_prompt_build`

What to look for:
- receipt stages like `queued` / `woke_parent` / `acked`
- parent wake + prompt injection as the main internal completion path

Use when:
- child finished but parent seems unaware
- completion looked "lost" after terminal state

### 2. Roundtable ack guard
Primary path for roundtable completion acknowledgements:
- `scripts/orchestrator_callback_bridge.py`
- `orchestrator/completion_ack_guard.py`
- `orchestrator/trading_roundtable.py`
- `orchestrator/channel_roundtable.py`

What it guarantees:
- completion handling should yield `ack_result`
- if delivery cannot be sent, fallback receipt/audit files should still be written

Use when:
- roundtable processed a completion but requester saw no visible ack

### 3. Orphan / waiting hard-close guard
Primary path for stale-or-dead task reconciliation:
- runtime side: `spawn-interceptor` reconcile / stale reaper
- business side: `orchestrator/waiting_guard.py`

What it guards against:
- `waiting` tasks with no live execution
- dead/failed/timed-out leaf tasks still being treated as healthy waiting
- the "waiting but active=0" class of anomaly

Use when:
- a batch will not close
- task state looks stuck in `waiting`
- orphaned leafs are suspected

## Scope limits
- This reference only improves **capability discovery**.
- It helps only if the agent actually **triggers/reads `orchestration-entry`**.
- Paths outside this entry or outside the covered runtime hooks still need their own discovery/docs.