# Main Flow: Request → Callback → Closeout → Next Batch

> **Purpose:** Detailed flow diagram of the orchestration mainline.
> **Audience:** Engineers implementing or debugging the continuation path.
> **Last updated:** 2026-03-24

---

## High-Level Sequence

```mermaid
sequenceDiagram
    participant U as User / Trigger
    participant CP as Control Plane
    participant SS as State Store
    participant EX as Executor
    participant CB as Callback Bridge

    U->>CP: Request / Trigger
    CP->>CP: Generate Planning Artifact
    CP->>SS: Register Task (registration_id)
    CP->>SS: Check Readiness + Safety Gates
    
    alt Gates Pass
        CP->>CP: Create Dispatch Plan
        CP->>SS: Write Dispatch (dispatch_id)
        CP->>CP: Generate Execution Request
        CP->>SS: Write Request (request_id)
        
        CP->>EX: Trigger Execution (sessions_spawn)
        EX->>SS: Write Execution Artifact (execution_id)
        EX->>EX: Run Task (subagent/Claude Code/tmux)
        EX->>SS: Write Completion Receipt (receipt_id)
        
        EX->>CB: Emit Callback
        CB->>CP: Notify Completion
        CP->>CP: Next-Step Decision
        
        alt Has Next Step
            CP->>SS: Register Next Batch
            CP->>U: Progress Update
        else Terminal
            CP->>SS: Mark Closeout
            CP->>U: Final Delivery
        end
    else Gates Block
        CP->>SS: Mark Blocked (wait_at_gate)
        CP->>U: Request Human Decision
    end
```

---

## Detailed State Transitions

### Task Registration

```mermaid
stateDiagram-v2
    [*] --> Unregistered
    
    Unregistered --> Registered: Planning artifact created
    Registered --> Ready: Readiness check passes
    Registered --> Blocked: Readiness check fails
    Ready --> Dispatched: Gates pass, dispatch triggered
    Ready --> Skipped: Gates fail, dispatch skipped
    Ready --> WaitAtGate: Manual approval required
    
    Dispatched --> Executing: Execution started
    Executing --> Completed: Execution succeeds
    Executing --> Failed: Execution fails
    
    Completed --> CallbackSent: Callback emitted
    CallbackSent --> AckReceived: Callback acknowledged
    AckReceived --> NextStepDecided: Next-step evaluated
    
    NextStepDecided --> Registered: Has next batch
    NextStepDecided --> Closed: Terminal state
```

### Dispatch Decision Tree

```mermaid
graph TD
    Start[Dispatch Decision] --> CheckGates{Safety Gates}
    
    CheckGates -->|Pass| CheckReady{Readiness}
    CheckGates -->|Fail| Skip[Skip Dispatch]
    
    CheckReady -->|Ready| CheckAllowlist{Allowlist}
    CheckReady -->|Not Ready| Block[Block Dispatch]
    
    CheckAllowlist -->|Allowed| Trigger[Trigger Execution]
    CheckAllowlist -->|Not Allowed| WaitGate[Wait at Gate]
    
    Trigger --> Exec[Execute via sessions_spawn]
    Exec --> Receipt[Generate Receipt]
    Receipt --> Next[Next-Step Decision]
```

---

## Fan-Out / Fan-In Pattern

```mermaid
graph TB
    subgraph Parent["Parent Task"]
        P1[Planning]
        P2[Fan-Out Plan]
    end
    
    subgraph Children["Child Tasks"]
        C1[Child A]
        C2[Child B]
        C3[Child C]
    end
    
    subgraph Aggregation["Fan-In Aggregation"]
        A1[Collect Receipts]
        A2[Aggregate Readiness]
        A3[Identify Blockers]
    end
    
    subgraph NextBatch["Next Batch Decision"]
        N1[Trigger Next Batch]
        N2[Stop at Gate]
        N3[Request Human Decision]
    end
    
    P1 --> P2
    P2 --> C1
    P2 --> C2
    P2 --> C3
    
    C1 --> A1
    C2 --> A1
    C3 --> A1
    
    A1 --> A2
    A2 --> A3
    A3 --> N1
    A3 --> N2
    A3 --> N3
```

### Fan-In States

| Child A | Child B | Child C | Aggregation Result |
|---------|---------|---------|-------------------|
| done | done | done | Trigger next batch |
| done | blocked | done | Stop at gate / request decision |
| done | failed | done | Evaluate failure policy |
| blocked | blocked | blocked | Escalate to owner |

---

## Artifact Lifecycle

```mermaid
graph LR
    subgraph Planning["Planning Artifacts"]
        PA[Planning Artifact]
        HS[Handoff Schema]
    end
    
    subgraph Registration["Registration Artifacts"]
        TR[Task Registry]
        RS[Readiness Status]
        SG[Safety Gates]
    end
    
    subgraph Dispatch["Dispatch Artifacts"]
        DP[Dispatch Plan]
        ER[Execution Request]
    end
    
    subgraph Execution["Execution Artifacts"]
        SC[Spawn Closure]
        EA[Execution Artifact]
        CR[Completion Receipt]
    end
    
    subgraph Callback["Callback Artifacts"]
        CC[Callback Close]
        NS[Next-Step Decision]
    end
    
    PA --> HS
    HS --> TR
    TR --> RS
    RS --> SG
    SG --> DP
    DP --> ER
    ER --> SC
    SC --> EA
    EA --> CR
    CR --> CC
    CC --> NS
```

---

## Linkage Chain (Traceability)

Every execution maintains a complete linkage chain:

```
┌─────────────────────────────────────────────────────────────┐
│ Linkage Chain (queryable by any ID)                         │
├─────────────────────────────────────────────────────────────┤
│ registration_id → dispatch_id → spawn_id → execution_id    │
│       ↓                ↓           ↓            ↓           │
│   task registry   dispatch    spawn       execution        │
│   entry           plan        closure     artifact         │
│                                                           │
│ execution_id → receipt_id → request_id → consumed_id      │
│       ↓             ↓            ↓            ↓            │
│   execution     completion   spawn       bridge           │
│   artifact      receipt      request     consumed         │
│                                                           │
│ consumed_id → api_execution_id (childSessionKey / runId) │
│       ↓                ↓                                   │
│   bridge          OpenClaw API                            │
│   consumed        execution                               │
└─────────────────────────────────────────────────────────────┘
```

### Query Examples

```bash
# Query by registration_id
cat ~/.openclaw/shared-context/task_registry/<registration_id>.json

# Query by receipt_id
cat ~/.openclaw/shared-context/completion_receipts/receipt_<id>.json

# Query full chain (any ID)
# Use any ID to trace through all linked artifacts
```

---

## Error Handling

### Failure Modes

| Mode | Detection | Response |
|------|-----------|----------|
| Missing artifact | File not found | Fail-fast, log error |
| Duplicate execution | ID collision check | Skip, log warning |
| Gate violation | Policy evaluation | Block, request approval |
| Execution timeout | Heartbeat / timeout | Mark failed, escalate |
| Callback lost | No ack received | Retry, alert owner |
| Waiting anomaly | active=0, waiting=true | Heartbeat triggers re-check |

### Recovery Path

```mermaid
graph TD
    Fail[Execution Failed] --> CheckRetry{Retry Allowed?}
    CheckRetry -->|Yes| Retry[Retry Execution]
    CheckRetry -->|No| Escalate[Escalate to Owner]
    
    Retry --> CheckSuccess{Success?}
    CheckSuccess -->|Yes| Continue[Continue Flow]
    CheckSuccess -->|No| CheckMaxRetry{Max Retries?}
    
    CheckMaxRetry -->|No| Retry
    CheckMaxRetry -->|Yes| Escalate
    
    Escalate --> Log[Log Failure]
    Log --> Notify[Notify Owner]
    Notify --> End[End Flow]
```

---

## Current Implementation Status

| Component | Status | Notes |
|-----------|--------|-------|
| Planning artifact | ✅ Implemented | gstack-style planning default |
| Task registration | ✅ Implemented | JSONL registry ledger |
| Readiness check | ✅ Implemented | Payload validation + dedupe |
| Safety gates | ✅ Implemented | Allowlist-based |
| Dispatch plan | ✅ Implemented | Auto-trigger configurable |
| Execution request | ✅ Implemented | Canonical sessions_spawn interface |
| Bridge consumer | ✅ Implemented | Real execute mode + auto-trigger |
| Sessions spawn bridge | ✅ Implemented | Real OpenClaw API integration |
| Completion receipt | ✅ Implemented | Closure artifact with linkage |
| Callback auto-close | ✅ Implemented | Bridge consumption layer |
| Next-step decision | ✅ Implemented | Post-completion replan contract |
| Fan-out/fan-in | ✅ Implemented | Multi-child aggregation |
| Git push auto-continue | ⚠️ Partial | Not fully closed |

---

## See Also

- **Architecture overview:** [`./overview.md`](./overview.md)
- **Current truth:** [`../CURRENT_TRUTH.md`](../CURRENT_TRUTH.md)
- **Auto-trigger config:** [`../configuration/auto-trigger-config-guide.md`](../configuration/auto-trigger-config-guide.md)
- **Validation status:** [`../validation-status.md`](../validation-status.md)
