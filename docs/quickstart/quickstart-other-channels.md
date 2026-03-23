# 其他频道 Quickstart（非 trading 场景）

> 适用场景：架构讨论、产品评审、运营协调等所有非 trading 频道
> 
> 成熟度：**thin bridge / allowlist / safe semi-auto**

---

## 🚀 30 秒快速接入

### 步骤 1: 生成 contract（复制修改）

```bash
python3 ~/.openclaw/scripts/orch_command.py \
  --channel-id "discord:channel:YOUR_ID" \
  --channel-name "your-channel" \
  --topic "讨论主题" \
  --output tmp/orch-contract.json
```

### 步骤 2: 验证输出

```bash
cat tmp/orch-contract.json | python3 -m json.tool | head -30
```

确认关键字段:
- `orchestration.adapter` = `channel_roundtable`
- `orchestration.channel.id` = 你的频道 ID
- `onboarding.bootstrap_capability_card` 存在

### 步骤 3: 首次运行（保守模式）

```bash
python3 ~/.openclaw/scripts/orch_command.py \
  --channel-id "discord:channel:YOUR_ID" \
  --channel-name "your-channel" \
  --topic "讨论主题" \
  --auto-execute false
```

---

## 完整示例（可直接运行）

```bash
# 1. 生成 contract
python3 ~/.openclaw/scripts/orch_command.py \
  --channel-id "discord:channel:-1002381931352" \
  --channel-name "general" \
  --topic "架构评审" \
  --owner "main" \
  --output tmp/orch-contract.json

# 2. 查看 contract
cat tmp/orch-contract.json

# 3. 运行测试（可选）
cd <path-to-repo>/openclaw-company-orchestration-proposal
python3 -m pytest tests/orchestrator/test_orch_command.py -v
```

---

## 默认配置（无需手动设置）

| 配置 | 默认值 | 说明 |
|------|--------|------|
| adapter | `channel_roundtable` | 非 trading 场景统一使用 |
| backend | `subagent` | 默认执行后端 |
| auto_execute | `true` | 自动注册/派发/回调/续推 |
| gate_policy | `stop_on_gate` | 命中 gate 正常停住 |
| coding lane | Claude Code | 编码任务自动使用 |
| non-coding lane | subagent | 非编码任务使用 |

---

## 首次接入检查清单

- [ ] **首次运行**: `--auto-execute false`（先验证稳定）
- [ ] **跑通 callback**: 手动完成 3-5 轮 callback/ack/dispatch
- [ ] **验证 artifacts**: 确认 completion receipt / dispatch plan 正常生成
- [ ] **开启自动**: 验证稳定后改 `--auto-execute true`
- [ ] **敏感操作**: 生产变更/资金相关必须 human-gate

---

## 常见场景

### 场景 1: 架构讨论频道
```bash
python3 ~/.openclaw/scripts/orch_command.py \
  --channel-id "discord:channel:1483883339701158102" \
  --channel-name "architecture" \
  --topic "Temporal vs LangGraph 架构评审" \
  --owner "main"
```

### 场景 2: 产品评审频道
```bash
python3 ~/.openclaw/scripts/orch_command.py \
  --channel-id "discord:channel:PRODUCT_ID" \
  --channel-name "product-review" \
  --topic "Q2 产品规划评审" \
  --owner "content"
```

### 场景 3: 运营协调频道
```bash
python3 ~/.openclaw/scripts/orch_command.py \
  --channel-id "discord:channel:OPS_ID" \
  --channel-name "ops-coordination" \
  --topic "每周运营同步" \
  --owner "butler"
```

---

## 完成回调示例

```bash
python3 scripts/orchestrator_callback_bridge.py complete \
  --task-id <task_id> \
  --batch-id <batch_id> \
  --payload orchestrator/examples/generic_non_trading_roundtable_callback.json \
  --runtime subagent \
  --allow-auto-dispatch false \
  --requester-session-key "agent:main:discord:channel:YOUR_ID"
```

---

## 红线

- ❌ 首次接入不要直接 `auto_execute=true`
- ❌ 不要跳过 callback/ack 验证直接上自动续跑
- ❌ 敏感操作（生产变更/资金）不要绕过 human-gate
- ✅ 首次一律 `allow_auto_dispatch=false`
- ✅ 先跑通 3-5 轮手动 callback 再考虑自动
- ✅ 涉及敏感操作必须 human-gate

---

## 下一步

- **完整文档**: `runtime/orchestrator/entry_defaults.py`
- **示例合同**: `orchestrator/examples/generic_channel_roundtable_onboarding_kit.md`
- **Callback 机制**: `docs/continuation-contract-v1.md`
- **统一入口**: `runtime/skills/orchestration-entry/SKILL.md`
