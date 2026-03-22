# Generic Channel Roundtable Onboarding Kit

> 非 trading scenario 最小接入包｜operator-facing checklist + 示例命令 + 示例 payload

**Version**: 1.0.0  
**Created**: 2026-03-22  
**Owner**: main (Zoe)  
**Related**: `entry_defaults.py` → `_build_channel_operator_kit()`

---

## TL;DR

新 scenario 接入 **不需要新 adapter**，只需：

1. 用 `channel_roundtable` adapter
2. 提供最小 packet + roundtable closure
3. 跑通 canonical callback → ack → dispatch artifacts
4. 首次建议 `--allow-auto-dispatch false`；稳定后再考虑放开默认自动续跑

---

## 5-Item Checklist

- [ ] **adapter 固定用 `channel_roundtable`**；`generic_roundtable` 只是 payload alias，不是新的 runtime adapter
- [ ] **先生成 contract**，再用最小 callback payload 跑通 canonical callback/ack/dispatch artifacts
- [ ] **新 scenario 首次接入建议显式 `--allow-auto-dispatch false`**；若要默认自动续跑，再单独补 allowlist/策略
- [ ] **packet 只补最小字段**：`packet_version/scenario/channel_id/topic/owner/generated_at`
- [ ] **roundtable 只补五字段**：`conclusion/blocker/owner/next_step/completion_criteria`

**红线**：backend terminal receipt / completion report 只是诊断与证据，**不能替代 canonical business callback PASS**。

---

## 最小 Contract 字段

生成命令：

```bash
python3 ~/.openclaw/scripts/orch_command.py \
  --scenario <your_scenario> \
  --channel-id discord:channel:<channel-id> \
  --channel-name <channel-name> \
  --topic "<topic>" \
  --owner <owner> \
  --backend subagent
```

输出中关键字段：

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
    "gate_policy": { "mode": "stop_on_gate" },
    "channel": {
      "id": "discord:channel:<channel-id>",
      "name": "<channel-name>",
      "topic": "<topic>"
    }
  },
  "onboarding": {
    "adapter_capability": "channel_roundtable.generic.v1",
    "payload_aliases": ["channel_roundtable", "generic_roundtable"],
    "new_scenario_minimum": {
      "required_contract_fields": ["scenario"],
      "required_packet_fields": [
        "packet_version", "scenario", "channel_id", "topic", "owner", "generated_at"
      ],
      "required_roundtable_fields": [
        "conclusion", "blocker", "owner", "next_step", "completion_criteria"
      ]
    }
  }
}
```

---

## 最小 Callback Payload

示例见：`generic_non_trading_roundtable_callback.json`

关键结构：

```json
{
  "summary": "简短总结",
  "verdict": "PASS|CONDITIONAL|FAIL",
  "channel_roundtable": {
    "packet": {
      "packet_version": "channel_roundtable_v1",
      "scenario": "<your_scenario>",
      "channel_id": "discord:channel:<channel-id>",
      "channel_name": "<channel-name>",
      "topic": "<topic>",
      "owner": "<owner>",
      "generated_at": "2026-03-22T00:00:00+08:00"
    },
    "roundtable": {
      "conclusion": "PASS|CONDITIONAL|FAIL",
      "blocker": "none|<blocker>",
      "owner": "<owner>",
      "next_step": "下一步动作",
      "completion_criteria": "完成标准"
    },
    "summary": "可选：scenario 专属总结"
  }
}
```

**注意**：payload 顶层用 `channel_roundtable` 或 `generic_roundtable` 均可（两者是 alias）。

---

## 示例命令

### 1. 生成 Contract

```bash
python3 ~/.openclaw/scripts/orch_command.py \
  --scenario product_launch_roundtable \
  --channel-id discord:channel:4242 \
  --channel-name product-launch-review \
  --topic "Product Launch Review" \
  --owner content \
  --backend subagent \
  --output tmp/product_launch_contract.json
```

### 2. Subagent 完成后回调

```bash
python3 scripts/orchestrator_callback_bridge.py complete \
  --task-id <task_id> \
  --batch-id <batch_id> \
  --payload tmp/product_launch_callback.json \
  --runtime subagent \
  --allow-auto-dispatch false \
  --requester-session-key agent:main:discord:channel:4242
```

### 3. TMUX 完成后回调

```bash
python3 scripts/orchestrator_dispatch_bridge.py complete \
  --dispatch tmp/dispatch.json \
  --task-id <task_id> \
  --tmux-status likely_done \
  --report-json /tmp/cc-<label>-completion-report.json \
  --report-md /tmp/cc-<label>-completion-report.md \
  --allow-auto-dispatch false \
  --requester-session-key agent:main:discord:channel:4242
```

---

## 安全门与风险点

### 不会自动放开的

- **auto_execute=true ≠ 自动绕过 gate**：仍会命中 human gate / business gate / runtime gate 就停
- **默认 allowlist 仍精确**：当前只对 `current_channel_architecture_roundtable` 场景放开
- **backend receipt ≠ business PASS**：tmux completion report 只是诊断证据

### 建议首次运行

```json
{
  "allow_auto_dispatch": false,
  "reason": "先证明 generic callback path/ack/dispatch artifacts 稳定，再决定是否为该 scenario 打开默认自动续跑。"
}
```

---

## 可直接复用的 Runtime 逻辑

新 scenario 只要接入上述最小 packet，就可直接复用：

- `scripts/orchestrator_callback_bridge.py complete`
- `orchestrator/completion_ack_guard.py`
- `summary -> decision -> dispatch plan`
- `scripts/orchestrator_dispatch_bridge.py complete`（tmux receipt → canonical callback）

---

## 示例文件

| 文件 | 用途 |
|------|------|
| `generic_non_trading_roundtable_contract.json` | 示例 contract（orch_command 输出格式） |
| `generic_non_trading_roundtable_callback.json` | 示例 callback payload |
| `current_channel_temporal_vs_langgraph_payload.json` | 当前架构频道真实 payload 参考 |

---

## 回退方案

若新增行为不稳，可通过回退以下文件撤销：

- 本文件（`generic_channel_roundtable_onboarding_kit.md`）
- 示例 JSON 文件（`generic_non_trading_roundtable_*.json`）
- `entry_defaults.py` 中 `_build_channel_operator_kit()` 相关改动
- `orchestrator_callback_bridge.py` 中 channel auto_execute 处理逻辑

**不要大改现有主链**（state_machine / batch_aggregator / orchestrator 核心逻辑）。

---

## 验证命令

```bash
# 1. 跑已有测试
python3 -m pytest tests/orchestrator/test_orch_command.py -v -k "generic"

# 2. 验证 callback bridge 处理 generic payload
python3 -m pytest tests/orchestrator/test_runtime_callback_bridge.py -v -k "channel"

# 3. 验证 tmux dispatch bridge 处理 channel callback
python3 -m pytest tests/orchestrator/test_tmux_dispatch_bridge.py -v -k "channel"
```

---

*End of Onboarding Kit*
