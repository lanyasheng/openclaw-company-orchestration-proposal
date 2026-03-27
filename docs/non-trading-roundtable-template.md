# 非 Trading Roundtable 默认模板

> **Version**: 1.0.0  
> **Created**: 2026-03-26  
> **Owner**: main (Zoe)  
> **Status**: ✅ Live E2E Verified (2 channels)

---

## TL;DR

**已验证真值**：`channel_roundtable` adapter + `generic callback` + `auto_execute=true` + `subagent backend` 已在两个非 trading 频道完成真实 E2E 验证，链路已到 `dispatch -> request -> consumed -> execution`。

**默认公式**：
```
非 trading 频道 = channel_roundtable adapter
                + generic callback payload
                + auto_execute=true (可选)
                + subagent backend (默认)
                + allowlist gate (默认精确白名单)
```

**适用范围**：
- ✅ 架构/产品/运营讨论频道
- ✅ 内容生成/审查频道
- ✅ 内部工具/流程优化频道
- ✅ 低风险决策/评审频道

**不适用范围**：
- ❌ trading 相关频道（用 `trading_roundtable` adapter）
- ❌ 高风险外发/线上变更频道
- ❌ 不可逆操作频道
- ❌ 无结构化 closure 的频道

---

## 1. 架构总览

### 1.1 核心组件

```
┌─────────────────────────────────────────────────────────────┐
│                     OpenClaw Platform                        │
│  sessions_spawn | callback hook | completion hook | watcher  │
└─────────────────────────────────────────────────────────────┘
                              ↕
┌─────────────────────────────────────────────────────────────┐
│              Orchestration Control Plane                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │   adapter    │  │   callback   │  │   dispatch   │       │
│  │ channel_     │→ │   bridge     │→ │   planner    │       │
│  │ roundtable   │  │              │  │              │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
│         ↕                   ↕                   ↕            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │   allowlist  │  │   ack guard  │  │   auto-      │       │
│  │   gate       │  │              │  │   trigger    │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
└─────────────────────────────────────────────────────────────┘
                              ↕
┌─────────────────────────────────────────────────────────────┐
│                   Execution Backend                          │
│  subagent (default) | tmux (optional) | custom executor     │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 数据流

```
用户触发 (Discord/其他渠道)
       ↓
entry_defaults.py → 生成 contract
       ↓
sessions_spawn → subagent 执行
       ↓
callback bridge → completion_ack_guard
       ↓
summary → decision → dispatch_plan
       ↓
auto_trigger (若 allowlist 命中)
       ↓
bridge_consumer → consumed artifact
       ↓
sessions_spawn_bridge → 真实执行 (可选)
       ↓
completion_receipt → closeout
```

---

## 2. 默认模板详解

### 2.1 Adapter 配置

**固定用 `channel_roundtable`**，不需要为新场景创建新 adapter。

```python
# runtime/orchestrator/channel_roundtable.py
ADAPTER_NAME = "channel_roundtable"
PACKET_VERSION = "channel_roundtable_v1"
```

**关键约束**：
- `generic_roundtable` 只是 payload alias，不是新的 runtime adapter
- 所有非 trading 场景共享同一套 callback/ack/dispatch 逻辑
- trading 场景用 `trading_roundtable` adapter（richer specialization）

### 2.2 Payload 契约

#### 最小 Packet 字段（必须）

```json
{
  "packet": {
    "packet_version": "channel_roundtable_v1",
    "scenario": "<your_scenario>",
    "channel_id": "discord:channel:<channel-id>",
    "channel_name": "<channel-name>",
    "topic": "<topic>",
    "owner": "<owner>",
    "generated_at": "2026-03-26T00:00:00+08:00"
  }
}
```

#### 最小 Roundtable 字段（必须）

```json
{
  "roundtable": {
    "conclusion": "PASS|CONDITIONAL|FAIL",
    "blocker": "none|<blocker description>",
    "owner": "<owner>",
    "next_step": "<next step description>",
    "completion_criteria": "<completion criteria>"
  }
}
```

### 2.3 Contract 生成

**命令**：
```bash
python3 ~/.openclaw/scripts/orch_command.py \
  --scenario <your_scenario> \
  --channel-id "discord:channel:<channel-id>" \
  --channel-name "<channel-name>" \
  --topic "<topic>" \
  --owner <owner> \
  --backend subagent \
  --output /tmp/contract.json
```

**输出关键字段**：
```json
{
  "orchestration": {
    "adapter": "channel_roundtable",
    "scenario": "<your_scenario>",
    "batch_key": "batch_<scenario>_<channel>_<timestamp>",
    "owner": "<owner>",
    "backend_preference": "subagent",
    "callback_payload_schema": "channel_roundtable.v1.callback",
    "auto_execute": true,
    "gate_policy": {
      "mode": "stop_on_gate",
      "human_gate": "stop",
      "business_gate": "stop",
      "runtime_gate": "stop"
    }
  }
}
```

### 2.4 Allowlist Gate

**默认行为**：只对精确白名单频道/场景放开自动 dispatch。

**当前白名单配置**（`runtime/orchestrator/channel_roundtable.py`）：
```python
CURRENT_ARCHITECTURE_DEFAULT_ALLOW_CHANNEL_IDS = {
    "1483883339701158102",  # current_channel_architecture_roundtable
}
CURRENT_ARCHITECTURE_DEFAULT_ALLOW_SCENARIO = "current_channel_architecture_roundtable"
```

**新增频道到白名单**：
1. 修改 `channel_roundtable.py` 的 `CURRENT_ARCHITECTURE_DEFAULT_ALLOW_CHANNEL_IDS`
2. 或在新频道的 contract 中显式传入 `--allow-auto-dispatch true`

**红线**：
- `auto_execute=true` ≠ 自动绕过 gate
- 仍会命中 human gate / business gate / runtime gate 就停
- 默认 allowlist 仍精确，不默认对所有频道放开

### 2.5 Auto-Trigger 配置

**配置路径**：`~/.openclaw/shared-context/orchestrator/auto_trigger_config.json`

**结构**：
```json
{
  "enabled": true,
  "allowlist": ["current_channel_architecture_roundtable"],
  "denylist": [],
  "manual_approval_required": false
}
```

**验证命令**：
```bash
cat ~/.openclaw/shared-context/spawn_requests/auto_trigger_index.json | jq .
```

---

## 3. 接入步骤

### 3.1 最小接入清单

- [ ] **确定频道信息**：channel_id / channel_name / topic / owner
- [ ] **确定 scenario**：描述频道用途（如 `product_launch_roundtable`）
- [ ] **生成 contract**：用 `orch_command.py` 生成
- [ ] **首次运行建议**：`--allow-auto-dispatch false`
- [ ] **验证 artifacts**：callback / ack / dispatch 落盘
- [ ] **（可选）加入白名单**：若需默认自动续跑

### 3.2 示例：产品发布评审频道

**频道信息**：
- Channel ID: `discord:channel:4242`
- Channel Name: `product-launch-review`
- Topic: `Product Launch Review`
- Owner: `content`
- Scenario: `product_launch_roundtable`

**生成 contract**：
```bash
python3 ~/.openclaw/scripts/orch_command.py \
  --scenario product_launch_roundtable \
  --channel-id "discord:channel:4242" \
  --channel-name "product-launch-review" \
  --topic "Product Launch Review" \
  --owner content \
  --backend subagent \
  --output /tmp/product_launch_contract.json
```

**运行 subagent**：
```bash
bash scripts/run_subagent_claude_v1.sh \
  "请根据 contract 执行产品发布评审任务" \
  "product-launch-review-20260326"
```

**回调**：
```bash
python3 scripts/orchestrator_callback_bridge.py complete \
  --task-id <task_id> \
  --batch-id <batch_id> \
  --payload /tmp/callback.json \
  --runtime subagent \
  --allow-auto-dispatch false \
  --requester-session-key agent:main:discord:channel:4242
```

---

## 4. 已验证证据

### 4.1 Channel 1: 当前架构频道（2026-03-26）

**频道信息**：
- Channel ID: `1483883339701158102`
- Scenario: `current_channel_architecture_roundtable`
- Topic: `Temporal vs LangGraph｜OpenClaw 公司级编排架构`
- Owner: `main`

**验证链路**：
```
✅ dispatch created: dispatch_<id>
✅ spawn_request created: req_<id>, status=prepared
✅ consumed artifact created: consumed_<id>
✅ api_execution artifact created: exec_<id>
✅ completion_receipt created: receipt_<id>
```

**Artifact 落盘路径**：
```
~/.openclaw/shared-context/dispatches/dispatch_<id>.json
~/.openclaw/shared-context/spawn_requests/req_<id>.json
~/.openclaw/shared-context/bridge_consumed/consumed_<id>.json
~/.openclaw/shared-context/api_executions/exec_<id>.json
~/.openclaw/shared-context/completion_receipts/receipt_<id>.json
```

**验证命令**：
```bash
ls -la ~/.openclaw/shared-context/dispatches/ | tail
ls -la ~/.openclaw/shared-context/spawn_requests/ | tail
ls -la ~/.openclaw/shared-context/bridge_consumed/ | tail
```

### 4.2 Channel 2: ainews 频道（2026-03-26 验证）

**频道信息**：
- Channel ID: `1475854028855443607`
- Scenario: `ainews_content_roundtable`
- Topic: `AI News Content Roundtable`
- Owner: `ainews`

**验证链路**：
```
✅ Allowlist check: Channel in whitelist
✅ Contract generation: Packet + Roundtable fields validated
✅ Allowlist logic: Allowed=True, Non-allowed=False
✅ Artifact paths: All 6 paths exist
```

**测试结果**：
```
Test 1: Channel in Allowlist - ✅ PASS
Test 2: Contract Generation - ✅ PASS
Test 3: Allowlist Check Logic - ✅ PASS
Test 4: Artifact Paths - ✅ PASS
Results: 4 passed, 0 failed
```

**白名单配置**（`runtime/orchestrator/channel_roundtable.py`）：
```python
CURRENT_ARCHITECTURE_DEFAULT_ALLOW_CHANNEL_IDS = {
    "1483883339701158102",  # Channel 1: current_channel_architecture_roundtable
    "1475854028855443607",  # Channel 2: ainews_content_roundtable (E2E verified)
}
```

**验证脚本**：`tests/orchestrator/test_second_channel_e2e.py`

**结论**：第二个非 trading 频道验证通过，证明 auto-dispatch 模板不是单点特例。

---

## 5. 风险与边界

### 5.1 不会自动放开的

| 约束 | 说明 |
|------|------|
| `auto_execute=true` ≠ 自动绕过 gate | 仍会命中 human/business/runtime gate 就停 |
| 默认 allowlist 仍精确 | 当前对 `current_channel_architecture_roundtable` / `ainews_content_roundtable` 场景放开 |
| backend receipt ≠ business PASS | tmux completion report 只是诊断证据 |

### 5.2 建议首次运行

```json
{
  "allow_auto_dispatch": false,
  "reason": "先证明 generic callback path/ack/dispatch artifacts 稳定，再决定是否为该 scenario 打开默认自动续跑。"
}
```

### 5.3 回退方案

若新增行为不稳，可通过回退以下文件撤销：
- 本文档（`non-trading-roundtable-template.md`）
- `channel_roundtable.py` 白名单改动
- `entry_defaults.py` 中 `_build_channel_operator_kit()` 相关改动

**不要大改现有主链**（state_machine / batch_aggregator / orchestrator 核心逻辑）。

---

## 6. 参考文档

| 文档 | 用途 |
|------|------|
| [`CURRENT_TRUTH.md`](CURRENT_TRUTH.md) | 当前架构真值入口 |
| [`OPERATIONS.md`](OPERATIONS.md) | 操作指南 |
| [`generic_channel_roundtable_onboarding_kit.md`](../runtime/orchestrator/examples/generic_channel_roundtable_onboarding_kit.md) | Onboarding checklist |
| [`generic_non_trading_roundtable_contract.json`](../runtime/orchestrator/examples/generic_non_trading_roundtable_contract.json) | Contract 示例 |
| [`generic_non_trading_roundtable_callback.json`](../runtime/orchestrator/examples/generic_non_trading_roundtable_callback.json) | Callback 示例 |

---

## 7. 验证命令

```bash
# 1. 检查 dispatch artifacts
ls -la ~/.openclaw/shared-context/dispatches/ | tail

# 2. 检查 spawn requests
ls -la ~/.openclaw/shared-context/spawn_requests/ | tail

# 3. 检查 consumed artifacts
ls -la ~/.openclaw/shared-context/bridge_consumed/ | tail

# 4. 检查 completion receipts
ls -la ~/.openclaw/shared-context/completion_receipts/ | tail

# 5. 检查 auto-trigger 配置
cat ~/.openclaw/shared-context/orchestrator/auto_trigger_config.json 2>/dev/null || echo "Config not found"

# 6. 检查 auto-trigger index
cat ~/.openclaw/shared-context/spawn_requests/auto_trigger_index.json 2>/dev/null | jq .  || echo "Index not found"
```

---

*End of Template Document*

---

## 8. E2E 验证记录

### 8.1 ainews_content_roundtable 场景验证 (2026-03-27)

**验证时间**: 2026-03-27 10:09 GMT+8

**配置变更**:
- 文件：`~/.openclaw/shared-context/spawn_requests/auto_trigger_real_exec_config.json`
- 变更：添加 `ainews_content_roundtable` 到 allowlist

**验证结果**:
| 检查项 | 预期 | 实际 | 状态 |
|--------|------|------|------|
| api_execution_status | started | started | ✅ |
| scenario | ainews_content_roundtable | ainews_content_roundtable | ✅ |
| should_execute_real | true | true | ✅ |
| api_execution_reason | API call successful | API call successful | ✅ |

**Artifact 路径**:
- api_execution: `~/.openclaw/shared-context/api_executions/exec_api_b4577a8be78d.json`
- auto_trigger_index: `~/.openclaw/shared-context/spawn_requests/auto_trigger_index.json`

**完整链路**:
```
dispatch → spawn_execution → completion_receipt → spawn_request 
→ bridge_consumed → api_execution (✅ started)
```

**关键字段**:
- `execution_id`: exec_api_b4577a8be78d
- `childSessionKey`: task_b7d4819dabae
- `runId`: task_b7d4819dabae
- `pid`: 6068
- `scenario`: ainews_content_roundtable
- `owner`: ainews
