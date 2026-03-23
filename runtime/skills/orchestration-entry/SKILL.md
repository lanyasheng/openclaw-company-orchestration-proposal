---
name: orchestration-entry
description: 🚀 OpenClaw Orchestration 单入口 — 只用这个 skill/command 即可完成默认接入。支持 channel_roundtable / trading_roundtable / 任意频道。默认 coding lane=Claude Code，non-coding lane=subagent。
---

# 🚀 单入口无缝接入 — 只用这个命令

**Orchestration 统一入口**: `python3 ~/.openclaw/scripts/orch_command.py`

> ✅ **一个命令搞定**: 给频道/主题即可生成可用 contract
> ✅ **默认最优配置**: coding lane → Claude Code; non-coding lane → subagent
> ✅ **安全边界内建**: gate_policy=stop_on_gate; 首次接入可保守但不复杂

---

## 快速开始（30 秒接入）

### 方式 1: 无参数（使用当前频道默认）
```bash
python3 ~/.openclaw/scripts/orch_command.py
```

### 方式 2: 指定频道/主题（推荐）
```bash
python3 ~/.openclaw/scripts/orch_command.py \
  --channel-id "discord:channel:YOUR_ID" \
  --channel-name "your-channel" \
  --topic "讨论主题"
```

### 方式 3: Trading 场景
```bash
python3 ~/.openclaw/scripts/orch_command.py --context trading_roundtable
```

### 方式 4: 保存到文件
```bash
python3 ~/.openclaw/scripts/orch_command.py \
  --channel-id "discord:channel:YOUR_ID" \
  --topic "架构评审" \
  --output tmp/orch-contract.json
```

---

## 默认行为（无需配置）

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| **coding lane** | Claude Code (via subagent) | 编码任务自动使用 Claude Code |
| **non-coding lane** | subagent | 非编码任务使用 subagent |
| **auto_execute** | `true` | 自动注册/派发/回调/续推 |
| **gate_policy** | `stop_on_gate` | 命中 human/business/runtime gate 正常停住 |
| **backend** | `subagent` | 默认执行后端；tmux 为兼容模式 |
| **adapter** | 自动推导 | trading 场景→trading_roundtable；其他→channel_roundtable |

---

## 首次接入建议

**首次接入新频道时**,建议显式关闭自动派发，先验证 callback/ack/dispatch artifacts 稳定:

```bash
python3 ~/.openclaw/scripts/orch_command.py \
  --channel-id "discord:channel:YOUR_ID" \
  --channel-name "your-channel" \
  --topic "讨论主题" \
  --auto-execute false
```

跑通 3-5 轮手动 callback 后，再改 `--auto-execute true` 开启自动续跑。

---

## 真值来源

- **Skill 源码**: `runtime/skills/orchestration-entry/SKILL.md`
- **Command 源码**: `runtime/scripts/orch_command.py`
- **安装/刷新全局副本**: `python3 runtime/scripts/install_orchestration_entry_global.py`
- **其他频道 Quickstart**: `docs/quickstart/quickstart-other-channels.md`

---

## 输出说明

命令输出为 JSON contract，包含:
- `entry_context`: 推导的上下文（context/source/matched_on）
- `onboarding`: 接入指南（含 `bootstrap_capability_card`）
- `orchestration`: 编排配置（adapter/scenario/backend/auto_execute/gate_policy）
- `seed_payload`: 种子 payload（channel_roundtable / trading_roundtable）

---

## 高级用法

### 完成回调（subagent 后端）
```bash
python3 scripts/orchestrator_callback_bridge.py complete \
  --task-id <task_id> \
  --batch-id <batch_id> \
  --payload orchestrator/examples/generic_non_trading_roundtable_callback.json \
  --runtime subagent \
  --allow-auto-dispatch false \
  --requester-session-key <agent:...>
```

### 查看帮助
```bash
python3 ~/.openclaw/scripts/orch_command.py --help
```

---

## 安全边界

- ✅ **首次接入默认保守**: `allow_auto_dispatch=false` 直到验证稳定
- ✅ **Gate 不可绕过**: human/business/runtime gate 正常停住
- ✅ **敏感操作需审批**: 生产变更/资金相关必须 human-gate
- ✅ **非全自动**: 当前成熟度 = thin bridge / allowlist / safe semi-auto

---

## 相关文档

- **Orchestration 完成/回执/等待异常**: 同时阅读 `~/.openclaw/skills/orchestration-entry/references/hook-guard-capabilities.md`
- **架构说明**: `docs/architecture/` 目录
- **测试验证**: `python3 -m unittest tests/orchestrator/test_orch_command.py -v`

---

> **一句话总结**: 只用 `python3 ~/.openclaw/scripts/orch_command.py` 这一个命令，给频道/主题即可生成可用 contract；coding lane 默认 Claude Code，non-coding lane 默认 subagent；安全边界内建，首次接入可保守但不复杂。
