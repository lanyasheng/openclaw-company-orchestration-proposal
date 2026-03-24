# Trading Roundtable 自动执行完整协议 v1.0

**文档类型**: 协议规范 (Protocol Specification)  
**生效日期**: 2026-03-24  
**维护者**: Runtime/Orchestrator 实现团队  
**适用频道**: `#trading` (trading_roundtable)  
**关联协议**: `waiting-integrity-hard-close-policy-2026-03-21.md`

---

## 0. 摘要

本协议定义 `trading_roundtable` 场景下从任务派发到最终收口的**完整自动执行流程**，确保执行链与收口链同步跑通，避免"先跑任务后补 packet truth / closeout / push 收口"的问题。

**核心原则**:
1. **Packet truth 先行**: 启动前必须有完整槽位定义
2. **Callback 标准化**: 所有子任务产出必须遵循统一 envelope
3. **Closeout 强制**: 每批完成后必须完成验收→closeout→git 收口→push
4. **Gate 分层**: auto / conditional / hard stop 三级门控

---

## 1. 适用对象

| 角色 | 职责 | 必读章节 |
|------|------|---------|
| **Runtime/Orchestrator 实现者** | 实现协议规定的 hook、bridge、gate | 4, 5, 6, 7 |
| **Main/Operator** | 验收质量门、决策升级/中止 | 4.8, 6, 8 |
| **Trading 执行链** | 产出标准化 callback、遵循 packet 槽位 | 4.3, 5, 6.2 |
| **子任务 Callback 产出方** | 填写 callback envelope、回填 tradability | 5, 6.2 |
| **Git 收口负责人** | 执行 closeout push、更新 manifest | 4.8, 7 |

---

## 2. 为什么需要该协议

### 2.1 真实问题链（2026-03-21 WS3 暴露）

```
执行链跑通 ✅
    ↓
收口链缺失 ❌
    ↓
等待状态 dangling ❌
    ↓
无法判定是否可 continuation ❌
```

**具体症状**:
- 子任务执行完成但 callback 缺少标准 envelope
- Packet truth 字段在启动后补填，导致无法验证完整性
- Closeout 未与 git push 绑定，导致 manifest 状态滞后
- Gate 条件模糊，导致"等待但没人跑"的假 waiting 状态

### 2.2 协议目标

1. **执行链与收口链同步**: 不允许先跑任务后补收口
2. **Packet truth 前置**: 启动前定义完整槽位，callback 时只填值
3. **Closeout 强制收口**: 每批完成后必须完成 git push 才能启动下一批
4. **Gate 可验证**: 所有门控条件必须基于可验证 artifact

---

## 3. Canonical 存放位置

| 文档类型 | 存放位置 | 说明 |
|---------|---------|------|
| **本协议** | `repos/openclaw-company-orchestration-proposal/docs/protocols/trading_roundtable_auto_execution_protocol_v1.md` | 唯一 canonical 版本 |
| **Runtime 实现** | `repos/openclaw-company-orchestration-proposal/runtime/orchestrator/trading_roundtable.py` | 代码真值 |
| **Schema 定义** | `repos/openclaw-company-orchestration-proposal/schemas/callback_envelope_v1.json` | Callback 结构 |
| **本地索引** | `~/.openclaw/workspace/tmp/trading_roundtable_protocol_note_20260324.md` | 主会话快速参考 |

**规则**: 禁止双写。任何更新必须先在 monorepo 完成，再同步本地索引。

---

## 4. 完整流程（8 步）

### 4.1 Contract 定义

**时机**: 批次启动前  
**负责人**: Operator/Main  
**产出**: `contract.json`

```json
{
  "batch_id": "trading_batch_X",
  "scenario": "trading_roundtable",
  "contract_version": "v1",
  "packet_skeleton_ref": "packet_skeleton_batch_X.json",
  "field_ownership_ref": "field_ownership_v1.md",
  "gate_config_ref": "gate_config_v1.json",
  "expected_artifacts": [
    "terminal.json",
    "final-summary.json",
    "callback_envelope.json"
  ],
  "closeout_requirements": {
    "acceptance_checklist": true,
    "git_closeout": true,
    "push_required": true
  }
}
```

**协议强制项**:
- ✅ `batch_id` 必须全局唯一
- ✅ `expected_artifacts` 必须明确定义
- ✅ `closeout_requirements` 必须声明

---

### 4.2 Packet Skeleton 预生成

**时机**: Contract 定义后、Task Spawn 前  
**负责人**: Runtime/Orchestrator  
**产出**: `packet_skeleton.json`

```json
{
  "packet_id": "pkt_batch_X_round_Y",
  "batch_id": "trading_batch_X",
  "created_at": "2026-03-24T09:00:00Z",
  "slots": {
    "启动前必须有槽位": {
      "candidate_id": null,
      "signal_type": null,
      "timeframe": null,
      "basket_ref": null
    },
    "callback 时填": {
      "tradability_score": null,
      "tradability_reason": null,
      "artifact_paths": [],
      "terminal_status": null
    },
    "harness 时填": {
      "execution_pid": null,
      "run_id": null,
      "child_session_key": null
    },
    "closeout 时聚合": {
      "acceptance_status": null,
      "git_closeout_commit": null,
      "push_timestamp": null,
      "next_batch_ready": null
    }
  },
  "field_ownership": "参见 4.3 字段归属表"
}
```

**协议强制项**:
- ✅ 所有槽位必须在启动前预定义（值可为 null，但 key 必须存在）
- ✅ 槽位必须按 4.6 分类组织
- ✅ `packet_id` 必须全局唯一且可追溯

---

### 4.3 字段归属表

| 字段 | 归属阶段 | 填写方 | 验证方 | 强制等级 |
|------|---------|--------|--------|---------|
| `candidate_id` | 启动前 | Operator | Runtime | **P0 强制** |
| `signal_type` | 启动前 | Operator | Runtime | **P0 强制** |
| `timeframe` | 启动前 | Operator | Runtime | P1 建议 |
| `basket_ref` | 启动前 | Operator | Runtime | P1 建议 |
| `tradability_score` | Callback | Trading 执行链 | Runtime | **P0 强制** |
| `tradability_reason` | Callback | Trading 执行链 | Runtime | **P0 强制** |
| `artifact_paths` | Callback | Trading 执行链 | Runtime | **P0 强制** |
| `terminal_status` | Callback | Trading 执行链 | Runtime | **P0 强制** |
| `execution_pid` | Harness | Runtime | - | P1 建议 |
| `run_id` | Harness | Runtime | - | P1 建议 |
| `child_session_key` | Harness | Runtime | - | P1 建议 |
| `acceptance_status` | Closeout | Main/Operator | - | **P0 强制** |
| `git_closeout_commit` | Closeout | Git 收口负责人 | - | **P0 强制** |
| `push_timestamp` | Closeout | Git 收口负责人 | - | **P0 强制** |
| `next_batch_ready` | Closeout | Main/Operator | - | **P0 强制** |

**协议强制项**:
- ✅ P0 强制字段缺少时不得进入下一阶段
- ✅ 字段归属不得越界（例如 callback 时不得填 closeout 字段）

---

### 4.4 Task Spawn

**时机**: Packet Skeleton 完成后  
**负责人**: Runtime/Orchestrator  
**触发条件**:
1. Contract 已定义
2. Packet Skeleton 已预生成
3. P0 强制槽位已填充（candidate_id, signal_type）

**执行动作**:
```python
# runtime/orchestrator/trading_roundtable.py
def spawn_trading_task(packet_skeleton, contract):
    # 1. 验证 P0 强制槽位
    validate_packet_slots(packet_skeleton, required=["candidate_id", "signal_type"])
    
    # 2. 生成 sessions_spawn 请求
    request = SessionsSpawnRequest(
        scenario="trading_roundtable",
        packet_ref=packet_skeleton["packet_id"],
        task_prompt=build_task_prompt(packet_skeleton),
        callback_envelope_schema="canonical_callback_envelope.v1"
    )
    
    # 3. 执行 spawn
    execution = sessions_spawn_bridge.dispatch(request)
    
    # 4. 回填 harness 字段
    packet_skeleton["slots"]["harness 时填"].update({
        "execution_pid": execution.pid,
        "run_id": execution.run_id,
        "child_session_key": execution.child_session_key
    })
    
    return execution
```

**协议强制项**:
- ✅ 必须先验证 P0 强制槽位
- ✅ 必须声明 `callback_envelope_schema`
- ✅ 必须回填 harness 字段

---

### 4.5 Standardized Callback Envelope

**时机**: 子任务完成时  
**负责人**: Trading 执行链（子任务）  
**产出**: `callback_envelope.json`

```json
{
  "envelope_version": "v1",
  "packet_id": "pkt_batch_X_round_Y",
  "task_id": "tsk_xxx",
  "completed_at": "2026-03-24T10:00:00Z",
  "backend_terminal_receipt": {
    "terminal_status": "completed|failed|blocked",
    "artifact_paths": [
      "/path/to/terminal.json",
      "/path/to/final-summary.json"
    ],
    "run_handle": {
      "run_id": "run_xxx",
      "child_session_key": "session_xxx",
      "pid": 12345
    }
  },
  "business_callback_payload": {
    "tradability_score": 0.85,
    "tradability_reason": "信号强度足够，basket 覆盖率>80%",
    "decision": "PASS|FAIL|DEGRADED",
    "blocked_reason": null
  },
  "adapter_scoped_payload": {
    "trading_roundtable": {
      "packet": { /* 完整 packet 状态 */ },
      "roundtable": { /* roundtable 特定状态 */ }
    }
  },
  "orchestration_contract": {
    "callback_envelope_schema": "canonical_callback_envelope.v1",
    "next_step": "acceptance_check",
    "next_owner": "main/operator",
    "dispatch_readiness": true
  },
  "source": {
    "adapter": "trading_roundtable",
    "runner": "run_subagent_claude_v1.sh",
    "label": "trading_batch_X_round_Y"
  }
}
```

**协议强制项**:
- ✅ 必须包含全部 5 个顶层字段
- ✅ `backend_terminal_receipt` 必须声明 artifact_paths
- ✅ `business_callback_payload` 不得伪造 clean PASS（如不足则声明 DEGRADED/BLOCKED）
- ✅ `orchestration_contract.dispatch_readiness` 必须明确 true/false

---

### 4.6 Acceptance/Tradability 回填

**时机**: Callback 被消费后、Closeout 前  
**负责人**: Runtime/Orchestrator  
**动作**:

```python
# runtime/orchestrator/trading_roundtable.py
def process_callback_and回填(packet_skeleton, callback_envelope):
    # 1. 验证 envelope 完整性
    validate_envelope(callback_envelope, required_fields=[
        "backend_terminal_receipt",
        "business_callback_payload",
        "orchestration_contract"
    ])
    
    # 2. 回填 callback 时填字段
    packet_skeleton["slots"]["callback 时填"].update({
        "tradability_score": callback_envelope["business_callback_payload"]["tradability_score"],
        "tradability_reason": callback_envelope["business_callback_payload"]["tradability_reason"],
        "artifact_paths": callback_envelope["backend_terminal_receipt"]["artifact_paths"],
        "terminal_status": callback_envelope["backend_terminal_receipt"]["terminal_status"]
    })
    
    # 3. 验证 tradability gate
    tradability_gate_result = evaluate_tradability_gate(
        score=packet_skeleton["slots"]["callback 时填"]["tradability_score"],
        config=gate_config
    )
    
    # 4. 判定是否可进入 closeout
    if tradability_gate_result.passed:
        packet_skeleton["slots"]["callback 时填"]["acceptance_ready"] = True
    else:
        packet_skeleton["slots"]["callback 时填"]["acceptance_ready"] = False
        packet_skeleton["slots"]["callback 时填"]["gate_failure_reason"] = tradability_gate_result.reason
    
    return packet_skeleton, tradability_gate_result
```

**协议强制项**:
- ✅ 必须先验证 envelope 完整性
- ✅ 必须执行 tradability gate 评估
- ✅ gate failure 必须声明原因

---

### 4.7 Runtime Closeout

**时机**: Acceptance 通过后  
**负责人**: Runtime/Orchestrator + Main/Operator  
**动作**:

```python
# runtime/orchestrator/closeout_tracker.py
def runtime_closeout(packet_skeleton, acceptance_result):
    # 1. 写入 closeout 状态
    closeout_artifact = {
        "packet_id": packet_skeleton["packet_id"],
        "batch_id": packet_skeleton["batch_id"],
        "closeout_timestamp": datetime.utcnow().isoformat(),
        "acceptance_status": acceptance_result.status,
        "tradability_score": packet_skeleton["slots"]["callback 时填"]["tradability_score"],
        "terminal_status": packet_skeleton["slots"]["callback 时填"]["terminal_status"],
        "closeout_type": "normal|degraded|failed",
        "stopped_because": acceptance_result.stopped_because,
        "next_step": acceptance_result.next_step,
        "next_owner": acceptance_result.next_owner,
        "dispatch_readiness": acceptance_result.dispatch_readiness
    }
    
    # 2. 写入 closeout artifact
    write_closeout_artifact(closeout_artifact)
    
    # 3. 更新 packet slots
    packet_skeleton["slots"]["closeout 时聚合"].update({
        "acceptance_status": acceptance_result.status,
        "closeout_type": closeout_artifact["closeout_type"]
    })
    
    return closeout_artifact
```

**协议强制项**:
- ✅ 必须写入 closeout artifact
- ✅ 必须包含 `stopped_because / next_step / next_owner`
- ✅ 必须更新 packet slots

---

### 4.8 Git Closeout/Push

**时机**: Runtime Closeout 完成后  
**负责人**: Git 收口负责人（默认 Main/Operator）  
**动作**:

```bash
# Git Closeout 标准流程
cd /Users/study/.openclaw/workspace/repos/openclaw-company-orchestration-proposal

# 1. 更新 manifest
python3 runtime/scripts/update_manifest.py \
  --batch-id trading_batch_X \
  --packet-id pkt_batch_X_round_Y \
  --closeout-status accepted \
  --tradability-score 0.85

# 2. 提交 closeout
git add docs/batch-summaries/trading_batch_X_round_Y_closeout.md
git add manifest.json
git commit -m "Closeout trading_batch_X round Y: accepted, tradability=0.85"

# 3. Push 到远端
git push origin main

# 4. 回填 push 时间戳
# (由 update_manifest.py 自动完成)
```

**协议强制项**:
- ✅ 必须先完成 Runtime Closeout 才能执行 Git Closeout
- ✅ Manifest 必须更新
- ✅ Push 必须成功才能启动下一批
- ✅ 必须回填 `git_closeout_commit` 和 `push_timestamp`

---

## 5. Phase1 Packet Truth Fields 分类

### 5.1 启动前必须有槽位

| 字段 | 说明 | 默认值 | 验证规则 |
|------|------|--------|---------|
| `candidate_id` | 标的 ID | null | 非空字符串 |
| `signal_type` | 信号类型 | null | enum: long/short/neutral |
| `timeframe` | 时间框架 | null | enum: 1m/5m/15m/1h/4h/1d |
| `basket_ref` | 篮子引用 | null | 非空字符串 |

**规则**: 这些字段在 Packet Skeleton 预生成时必须声明为 key（值可为 null），在 Task Spawn 前必须填充非 null 值。

---

### 5.2 Callback 时填

| 字段 | 说明 | 填写方 | 验证规则 |
|------|------|--------|---------|
| `tradability_score` | 可交易性评分 | Trading 执行链 | float [0.0, 1.0] |
| `tradability_reason` | 评分理由 | Trading 执行链 | 非空字符串 |
| `artifact_paths` | 产出物路径 | Trading 执行链 | 数组，至少包含 terminal.json |
| `terminal_status` | 终态状态 | Trading 执行链 | enum: completed/failed/blocked |

**规则**: 这些字段在 Callback Envelope 中必须填写，由 Runtime 验证后回填到 Packet。

---

### 5.3 Harness 时填

| 字段 | 说明 | 填写方 | 自动/手动 |
|------|------|--------|----------|
| `execution_pid` | 执行进程 ID | Runtime | 自动 |
| `run_id` | Run ID | Runtime | 自动 |
| `child_session_key` | 子 Session Key | Runtime | 自动 |

**规则**: 这些字段由 Runtime 在 Task Spawn 时自动填充，无需人工干预。

---

### 5.4 Closeout 时聚合

| 字段 | 说明 | 填写方 | 前置条件 |
|------|------|--------|---------|
| `acceptance_status` | 验收状态 | Main/Operator | Callback 已处理 |
| `git_closeout_commit` | Git 提交 Hash | Git 收口负责人 | Runtime Closeout 完成 |
| `push_timestamp` | Push 时间戳 | Git 收口负责人 | Git commit 成功 |
| `next_batch_ready` | 下一批就绪 | Main/Operator | Push 成功 |

**规则**: 这些字段在所有前置步骤完成后聚合，用于判定是否可启动下一批。

---

## 6. Gate 分层

### 6.1 Auto Gate（自动门）

**触发条件**: 系统自动评估，无需人工干预

| Gate 名称 | 条件 | 动作 |
|----------|------|------|
| `packet_completeness` | P0 强制槽位全部非 null | 允许 Task Spawn |
| `envelope_integrity` | Callback Envelope 包含全部 5 个顶层字段 | 允许进入 Acceptance |
| `artifact_existence` | artifact_paths 中所有文件存在 | 允许进入 Closeout |

**实现**:
```python
# runtime/orchestrator/gates.py
def auto_gate_packet_completeness(packet_skeleton):
    required_slots = ["candidate_id", "signal_type"]
    for slot in required_slots:
        if packet_skeleton["slots"]["启动前必须有槽位"].get(slot) is None:
            return GateResult(passed=False, reason=f"Missing required slot: {slot}")
    return GateResult(passed=True)
```

---

### 6.2 Conditional Gate（条件门）

**触发条件**: 基于配置阈值评估，可配置

| Gate 名称 | 条件 | 默认阈值 | 动作 |
|----------|------|---------|------|
| `tradability_threshold` | tradability_score >= threshold | 0.7 | 允许 Closeout |
| `artifact_minimum` | artifact_paths 数量 >= min_count | 2 | 允许 Closeout |
| `terminal_status_clean` | terminal_status == "completed" | - | 允许 Closeout |

**实现**:
```python
# runtime/orchestrator/gates.py
def conditional_gate_tradability(packet_skeleton, config):
    score = packet_skeleton["slots"]["callback 时填"]["tradability_score"]
    threshold = config.get("tradability_threshold", 0.7)
    if score >= threshold:
        return GateResult(passed=True)
    else:
        return GateResult(passed=False, reason=f"Tradability {score} < threshold {threshold}")
```

**配置**:
```json
// ~/.openclaw/shared-context/gate_config.json
{
  "trading_roundtable": {
    "tradability_threshold": 0.7,
    "artifact_minimum": 2,
    "require_terminal_clean": true
  }
}
```

---

### 6.3 Hard Stop Gate（硬停止门）

**触发条件**: 必须人工干预或明确配置才能绕过

| Gate 名称 | 触发条件 | 动作 | 绕过方式 |
|----------|---------|------|---------|
| `consecutive_failures` | 连续失败 >= 2 次 | 停止批次 | Operator 确认 |
| `timeout_exceeded` | 等待时间 > timeout_at | Hard Close | 重新定义 timeout |
| `artifact_missing_critical` | 缺少 P0 强制 artifact | 停止批次 | 补全 artifact 或降级 |
| `waiting_without_binding` | waiting 但 active=0 | Hard Close | 重新绑定或 closeout |

**实现**:
```python
# runtime/orchestrator/gates.py
def hard_stop_gate_consecutive_failures(batch_id, config):
    failure_count = get_consecutive_failure_count(batch_id)
    threshold = config.get("max_consecutive_failures", 2)
    if failure_count >= threshold:
        return GateResult(passed=False, reason=f"Consecutive failures {failure_count} >= threshold {threshold}", hard_stop=True)
    return GateResult(passed=True)
```

**协议强制项**:
- ✅ Hard Stop Gate 触发时必须停止批次
- ✅ 绕过 Hard Stop 必须人工确认并记录原因
- ✅ Hard Stop 事件必须写入 closeout artifact

---

## 7. 每批完成后的默认动作

### 7.1 标准流程

```
验收 (Acceptance)
    ↓ 必须通过
Closeout (Runtime)
    ↓ 必须完成
Git 收口 (Git Closeout)
    ↓ 必须成功
Push (远端同步)
    ↓ 必须成功
下一批 (Next Batch)
```

### 7.2 详细步骤

#### Step 1: 验收 (Acceptance)
```python
# runtime/orchestrator/trading_roundtable.py
acceptance_result = run_acceptance_check(
    packet_skeleton=packet_skeleton,
    callback_envelope=callback_envelope,
    checklist=[
        "P0 强制字段完整",
        "tradability_score >= threshold",
        "artifact_paths 存在",
        "terminal_status != failed"
    ]
)
```

**产出**: `acceptance_result.json`  
**强制项**: ✅ 必须通过所有 checklist 项目

---

#### Step 2: Closeout (Runtime)
```python
# runtime/orchestrator/closeout_tracker.py
closeout_artifact = runtime_closeout(
    packet_skeleton=packet_skeleton,
    acceptance_result=acceptance_result
)
```

**产出**: `closeout_artifact.json`  
**强制项**: ✅ 必须包含 `stopped_because / next_step / next_owner`

---

#### Step 3: Git 收口 (Git Closeout)
```bash
# 更新 manifest
python3 runtime/scripts/update_manifest.py \
  --batch-id trading_batch_X \
  --packet-id pkt_batch_X_round_Y \
  --closeout-status accepted

# 提交
git add docs/batch-summaries/trading_batch_X_round_Y_closeout.md manifest.json
git commit -m "Closeout trading_batch_X round Y"
```

**产出**: Git commit  
**强制项**: ✅ Manifest 必须更新

---

#### Step 4: Push (远端同步)
```bash
git push origin main
```

**产出**: Push 成功确认  
**强制项**: ✅ Push 必须成功

---

#### Step 5: 下一批 (Next Batch)
```python
# runtime/orchestrator/trading_roundtable.py
if push_successful and closeout_artifact["next_batch_ready"]:
    spawn_next_batch()
else:
    log_blocked_reason("Push failed or next_batch_ready=false")
```

**强制项**: ✅ 必须确认前 4 步全部完成

---

### 7.3 异常处理

| 异常 | 默认动作 | 升级条件 |
|------|---------|---------|
| 验收失败 | 写入 degraded closeout，不启动下一批 | 连续 2 次失败 |
| Closeout 失败 | 重试 1 次，仍失败则 Hard Stop | 无法写入 artifact |
| Git 收口失败 | 重试 1 次，仍失败则停止批次 | Git 冲突无法解决 |
| Push 失败 | 重试 1 次，仍失败则停止批次 | 远端拒绝 |

**协议强制项**:
- ✅ 任何一步失败都不得启动下一批
- ✅ 连续失败必须触发 Hard Stop Gate
- ✅ 所有异常必须写入 closeout artifact

---

## 8. 最小落地清单

### 8.1 已有实现

| 组件 | 位置 | 状态 |
|------|------|------|
| Packet Skeleton 预生成 | `runtime/orchestrator/trading_roundtable.py` | ✅ 已实现 |
| Callback Envelope Schema | `schemas/callback_envelope_v1.json` | ✅ 已实现 |
| Runtime Closeout | `runtime/orchestrator/closeout_tracker.py` | ✅ 已实现 |
| Auto Gate | `runtime/orchestrator/gates.py` | ✅ 已实现 |
| Conditional Gate | `runtime/orchestrator/gates.py` | ✅ 已实现 |
| Hard Stop Gate | `runtime/orchestrator/gates.py` | ✅ 已实现 |

---

### 8.2 待实现/待完善

| 组件 | 优先级 | 说明 | 预计完成 |
|------|--------|------|---------|
| Git Closeout 自动化脚本 | P0 | `runtime/scripts/update_manifest.py` 需完善 | 2026-03-25 |
| Push 成功回调 | P0 | Push 成功后自动回填 `push_timestamp` | 2026-03-25 |
| 批次间依赖检查 | P1 | 确保前一批 closeout 完成后才启动下一批 | 2026-03-26 |
| Closeout Dashboard | P2 | 可视化展示所有批次 closeout 状态 | 2026-03-28 |

---

### 8.3 配置缺口

| 配置项 | 位置 | 状态 |
|--------|------|------|
| `gate_config.json` | `~/.openclaw/shared-context/gate_config.json` | ⚠️ 需创建 |
| `closeout_requirements` | Contract 中声明 | ⚠️ 需标准化 |
| `manifest.json` Schema | `schemas/manifest_v1.json` | ⚠️ 需定义 |

---

## 9. 与当前 Trading 线程/频道的映射

### 9.1 频道映射

| Discord 频道 | 对应 Scenario | 协议版本 |
|-------------|--------------|---------|
| `#trading` (1483138253539250217) | `trading_roundtable` | v1.0 |
| `#general` | `channel_roundtable` | v1.0 (参考) |

---

### 9.2 线程映射

| 线程类型 | 对应协议阶段 | 产出物 |
|---------|-------------|--------|
| Spawn 线程 | 4.4 Task Spawn | `req_xxx.json`, `exec_xxx.json` |
| 执行线程 | 4.5 Callback | `callback_envelope.json` |
| Closeout 线程 | 4.7-4.8 | `closeout_artifact.json`, Git commit |

---

### 9.3 状态文件映射

| 状态 | 文件路径 | 更新时机 |
|------|---------|---------|
| Packet Skeleton | `~/.openclaw/shared-context/packets/pkt_xxx.json` | 4.2 预生成时 |
| Callback Envelope | `~/.openclaw/shared-context/callbacks/callback_xxx.json` | 4.5 完成时 |
| Closeout Artifact | `~/.openclaw/shared-context/closeouts/closeout_xxx.json` | 4.7 完成时 |
| Manifest | `repos/.../manifest.json` | 4.8 Git Closeout 时 |

---

### 9.4 当前 Trading 会话参考

**当前活跃会话**: 参见 `~/.openclaw/workspace/tmp/trading_runtime_bootstrap_current_thread_20260324.md`

**协议应用**:
- 当前会话中的每个任务必须遵循本协议 4.1-4.8 流程
- 所有 callback 必须包含标准 envelope
- 每批完成后必须完成 git closeout 才能启动下一批

---

## 10. 附录

### 10.1 术语表

| 术语 | 定义 |
|------|------|
| **Packet** | 任务数据包，包含所有槽位和状态 |
| **Skeleton** | Packet 的预定义结构（槽位定义） |
| **Callback Envelope** | 标准化的回调数据结构 |
| **Closeout** | 批次完成的最终收口动作 |
| **Gate** | 流程中的质量门控点 |
| **Hard Stop** | 必须人工干预才能绕过的门控 |

---

### 10.2 参考文档

| 文档 | 位置 |
|------|------|
| Waiting Integrity Policy | `docs/policies/waiting-integrity-hard-close-policy-2026-03-21.md` |
| Universal Callback Contract | `runtime/orchestrator/UNIVERSAL_TERMINAL_CALLBACK_CONTRACT_2026-03-22.md` |
| Current Truth | `docs/CURRENT_TRUTH.md` |
| Batch Summaries | `docs/batch-summaries/` |

---

### 10.3 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.0 | 2026-03-24 | 初始版本，基于 WS3 问题链经验 |

---

## 11. 合规检查清单

在启动任何 trading_roundtable 批次前，必须确认以下项目：

- [ ] Contract 已定义（4.1）
- [ ] Packet Skeleton 已预生成（4.2）
- [ ] P0 强制槽位已填充（4.3）
- [ ] Gate 配置已加载（6）
- [ ] Callback Envelope Schema 已声明（4.5）
- [ ] Closeout 要求已明确（4.7-4.8）
- [ ] Git 收口负责人已指定（4.8）
- [ ] 下一批启动条件已定义（7）

**规则**: 任何一项未完成不得启动批次。

---

**文档结束**
