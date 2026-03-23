# Trading Spider Alert System

最小可用提醒发送链，用于交易系统候选推送和 Gate 结果通知。

## 设计目标

1. **不重复刷屏**：基于 `candidate_id + signal_type` 去重，时间窗口节流
2. **发送前有结构化 payload**：统一 schema，包含所有必要上下文
3. **发送结果可查**：状态文件 + 日志文件，可验证回执

## 架构

```
候选变化 → 去重检查 → 节流检查 → 结构化 Payload → 发送 → 状态/日志文件
   │                                              │
   └──────────────────────────────────────────────┘
                                    可验证回执
```

## 安装

无需额外安装，模块位于：
```
repos/openclaw-company-orchestration-proposal/runtime/orchestrator/alerts/
```

状态文件目录：
```
~/.openclaw/shared-context/trading-alerts/state/  # 状态文件
~/.openclaw/shared-context/trading-alerts/logs/   # 日志文件
```

## 使用

### 基础用法

```python
from orchestrator.alerts import TradingAlertSender, send_alert

# 方式 1: 使用类
sender = TradingAlertSender()
result = sender.send_candidate_alert(
    candidate_id="candidate_001",
    signal_type="buy_watch",
    symbol="000001.SZ",
    reason="趋势反转 + 量价共振",
    metadata={"score": 0.92, "sector": "金融"}
)
print(f"Alert sent: {result.delivered}, ID: {result.alert_id}")

# 方式 2: 便捷函数
result = send_alert(
    candidate_id="candidate_002",
    signal_type="gate_pass",
    symbol="N/A",
    reason="Gate review passed"
)
```

### Alert 类型

| 类型 | 说明 | 使用场景 |
|------|------|---------|
| `buy_watch` | 买入观察 | 候选标的达到买入观察条件 |
| `sell_watch` | 卖出观察 | 持仓标的达到卖出观察条件 |
| `hold_watch` | 持仓观察 | 持仓标的需要持续关注 |
| `candidate_new` | 新候选 | 新的候选标的产生 |
| `candidate_update` | 候选更新 | 候选标的信息更新 |
| `candidate_remove` | 候选移除 | 候选标的被移除 |
| `gate_pass` | Gate 通过 | Roundtable Gate 通过 |
| `gate_fail` | Gate 失败 | Roundtable Gate 失败 |
| `gate_conditional` | Gate 条件通过 | Roundtable Gate 条件通过 |

### 配置选项

```python
sender = TradingAlertSender(
    throttle_window_seconds=300,    # 节流窗口（秒），默认 5 分钟
    max_alerts_per_window=1,        # 每窗口最大发送数，默认 1
    enable_dedup=True,              # 启用去重，默认 True
    enable_throttle=True,           # 启用节流，默认 True
    dry_run=False,                  # 干跑模式，默认 False
)
```

## Payload Schema

```json
{
  "alert_version": "trading_alert_sender_v1",
  "alert_id": "alert_xxx",
  "timestamp": "2026-03-23T10:00:00",
  "candidate_id": "candidate_001",
  "signal_type": "buy_watch",
  "symbol": "000001.SZ",
  "reason": "趋势反转 + 量价共振",
  "metadata": {
    "score": 0.92,
    "sector": "金融"
  },
  "sender": {
    "name": "trading_spider",
    "version": "trading_alert_sender_v1"
  },
  "delivery": {
    "channel": "discord",
    "reply_to": "channel:xxx"
  }
}
```

## 状态文件

每个 alert 生成一个状态文件：
```
~/.openclaw/shared-context/trading-alerts/state/alert_xxx.json
```

内容包含：
- `alert_id`: Alert ID
- `payload`: 发送的 payload
- `result`: 发送结果
- `created_at`: 创建时间

## 日志文件

按日期分片的 JSONL 日志：
```
~/.openclaw/shared-context/trading-alerts/logs/alerts-2026-03-23.jsonl
```

每行是一个完整的 alert 记录，包含 payload 和 result。

## 查询状态

```python
from orchestrator.alerts import TradingAlertSender

sender = TradingAlertSender()

# 查询单个 alert 状态
state = sender.get_alert_state("alert_xxx")
print(state)

# 列出最近的 alert
recent = sender.list_recent_alerts(limit=10)
for entry in recent:
    print(f"{entry['alert_id']}: {entry['payload']['signal_type']}")
```

## 去重机制

去重基于 `candidate_id + signal_type` 组合：
- 相同的 candidate_id + signal_type 只会发送一次
- 更新需要使用不同的 signal_type（如 `candidate_new` → `candidate_update`）

## 节流机制

节流基于时间窗口：
- 默认 5 分钟内每个 signal_type 最多发送 1 条
- 不同类型的 alert 互不影响
- 窗口按分钟计算（`YYYY-MM-DD-HH-MM`）

## 测试

### 单元测试
```bash
cd /Users/study/.openclaw/workspace
python3 tests/orchestrator/alerts/test_trading_alert_sender.py
```

### 验收测试
```bash
cd /Users/study/.openclaw/workspace
python3 tests/orchestrator/alerts/acceptance_test_alert_chain.py
```

## 与 Trading Roundtable 集成

在 `trading_roundtable.py` 中使用：

```python
from orchestrator.alerts import TradingAlertSender

def process_trading_roundtable_callback(...):
    # ... 处理 callback
    
    # 发送 Gate 结果提醒
    sender = TradingAlertSender()
    sender.send_candidate_alert(
        candidate_id=packet.get("candidate_id"),
        signal_type=f"gate_{conclusion.lower()}",
        symbol="N/A",
        reason=f"Roundtable {conclusion}, blocker={blocker}",
        metadata={
            "batch_id": batch_id,
            "conclusion": conclusion,
            "blocker": blocker,
            "next_step": next_step,
        }
    )
```

## 发送适配器

当前支持两种发送方式：

### 1. FileDeliveryAdapter（默认）
写入文件作为 Mock，用于测试和降级：
```python
from orchestrator.alerts import TradingAlertSender, FileDeliveryAdapter

sender = TradingAlertSender(
    delivery_adapter=FileDeliveryAdapter(),
    dry_run=False
)
```

### 2. OpenClawAgentDeliveryAdapter（真实发送）
通过 `openclaw agent --deliver` 发送真实 Discord 消息。

**前提条件**：
- Gateway 必须运行中 (`openclaw gateway status`)
- Discord 频道必须已配置并授权 (`openclaw channels list`)
- 发送可能超时（120s），建议先在测试环境验证

```python
from orchestrator.alerts import TradingAlertSender, create_openclaw_adapter

# 创建 OpenClaw 适配器
adapter = create_openclaw_adapter(agent_id="main", default_channel="discord")

# 使用适配器（建议先用 dry_run=True 测试）
sender = TradingAlertSender(
    delivery_adapter=adapter,
    dry_run=False  # 关闭干跑模式
)

result = sender.send_candidate_alert(
    candidate_id="candidate_001",
    signal_type="buy_watch",
    symbol="000001.SZ",
    reason="趋势反转 + 量价共振"
)

if result.delivered:
    print(f"✅ Alert sent via OpenClaw: {result.alert_id}")
elif result.error:
    print(f"❌ Alert failed: {result.error}")
    # 常见错误：
    # - openclaw_agent_timeout: Gateway 响应超时，检查 Gateway 状态
    # - openclaw_binary_not_found: openclaw CLI 路径不对
    # - openclaw_agent_exit_1: Gateway 返回错误，检查日志
```

### 发送状态对比

| 状态 | 说明 | 处理方式 |
|------|------|---------|
| `delivered=True` | 发送成功 | 正常继续 |
| `dedup_skipped=True` | 被去重跳过 | 预期行为，无需处理 |
| `throttle_skipped=True` | 被节流跳过 | 预期行为，无需处理 |
| `error=...` | 发送失败 | 检查错误原因，必要时降级到 File 适配器 |

### 适配器对比

| 适配器 | 发送方式 | 使用场景 |
|--------|---------|---------|
| `FileDeliveryAdapter` | 写入文件 | 本地测试、降级、审计 |
| `OpenClawAgentDeliveryAdapter` | `openclaw agent --deliver` | 真实 Discord 消息 |

## 未来扩展

1. **多频道支持**：支持 Telegram、Slack 等
2. **优先级队列**：支持 alert 优先级排序
3. **批量发送**：支持批量 alert 聚合发送

## 版本

- `trading_alert_sender_v1`: 初始版本，最小可用闭环

## 相关文件

- 实现：`runtime/orchestrator/alerts/trading_alert_sender.py`
- 测试：`tests/orchestrator/alerts/test_trading_alert_sender.py`
- 验收：`tests/orchestrator/alerts/acceptance_test_alert_chain.py`
- 状态目录：`~/.openclaw/shared-context/trading-alerts/`
