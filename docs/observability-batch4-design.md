# Observability Batch 4 设计摘要

> **批次**: Batch 4 - 主动告警 + 人话回报闭环  
> **日期**: 2026-03-29  
> **状态**: 设计中 → 实现中  
> **优先级**: P0 (用户已批准)

---

## 0. 执行摘要

### 问题陈述

当前 Observability Batch 1-3 已完成：
- ✅ Batch 1: 状态卡 CRUD 系统
- ✅ Batch 2: 行为约束钩子
- ✅ Batch 3: tmux 统一状态索引

**最大缺口**：任务完成/超时/失败虽然有真值和钩子，但**用户可见的人话回报与主动告警还不是强闭环**。

具体问题：
1. 子任务完成后，用户看到的是 ACP 原始报告（技术性强），而非自然语言摘要
2. 超时任务没有主动产生人类可读告警
3. 失败任务没有主动产生人类可读告警
4. 告警/回报与现有 truth plane 是分离的，需要统一

### 设计目标

实现最小可用的主动告警 + 人话回报闭环：
1. **告警层只读现有真值**：从 completion_receipt / observability_card / tmux_status 派生可读摘要
2. **不双写真值**：告警层是 observability plane 的延伸，不是新的 truth plane
3. **轻量闭环**：优先实现核心功能，而非大而全
4. **有真实代码 + 测试**：不只是文档或空壳接口

---

## 1. 范围

### 1.1 包含的功能

| 功能 | 说明 | 优先级 |
|------|------|--------|
| **完成事件人话摘要** | 子任务完成后生成自然语言摘要 | P0 |
| **超时事件告警** | 任务超过 promised_eta 未完成后主动告警 | P0 |
| **失败事件告警** | 任务失败后主动告警并说明原因 | P0 |
| **告警去重** | 相同事件不重复告警 | P1 |
| **告警通道** | 支持文件 mock + OpenClaw 原生消息 | P1 |
| **审计日志** | 所有告警/回报记录到审计日志 | P1 |

### 1.2 不包含的功能（后续批次）

| 功能 | 说明 | 后续批次 |
|------|------|---------|
| Web 可视化看板 | Batch 4 专注告警/回报，看板是可选增强 | Batch 5 |
| 复杂告警规则引擎 | 当前只支持超时/失败/完成三类事件 | Batch 5 |
| 多通道路由 | 当前只支持单一通道，后续支持 Discord/邮件/短信 | Batch 5 |
| 告警确认/升级 | 当前告警是单向通知，无确认流程 | Batch 5 |

---

## 2. 架构设计

### 2.1 三层架构

```
┌─────────────────────────────────────────────────────────────┐
│                    Alert & Report Plane                      │
│  (新增) 告警调度器 / 人话渲染器 / 审计日志                     │
│  - 只读 truth plane                                          │
│  - 派生人类可读摘要和告警                                     │
│  - 主动推送给用户                                            │
└─────────────────────────────────────────────────────────────┘
                              ↑ 读取
┌─────────────────────────────────────────────────────────────┐
│                      Truth Plane                             │
│  (现有) dispatch / callback / receipt / closeout artifacts   │
│  - completion_receipt.py: 完成记录                           │
│  - observability_card.py: 状态卡                             │
│  - tmux_status_sync.py: tmux 状态                              │
│  - completion_validator.py: 验证结果                         │
└─────────────────────────────────────────────────────────────┘
                              ↑ 调度
┌─────────────────────────────────────────────────────────────┐
│                    Execution Plane                           │
│  (现有) subagent / tmux / browser / message / cron           │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 核心模块

| 模块 | 职责 | 行数 (预估) |
|------|------|-----------|
| `alert_dispatcher.py` | 告警调度器：检测事件、去重、分发 | ~400 |
| `human_report_renderer.py` | 人话渲染器：将技术报告翻译为自然语言 | ~300 |
| `alert_rules.py` | 告警规则：定义超时/失败/完成事件的判定逻辑 | ~150 |
| `alert_audit.py` | 审计日志：记录所有告警/回报事件 | ~100 |

### 2.3 事件流

#### 完成事件流
```
subagent/tmux 完成
  ↓
completion_receipt.py 创建 receipt
  ↓
alert_dispatcher.py 检测到 completed 事件
  ↓
human_report_renderer.py 生成自然语言摘要
  ↓
alert_dispatcher.py 发送给用户
  ↓
alert_audit.py 记录审计日志
```

#### 超时事件流
```
watchdog.py 定期巡检 (每 5 分钟)
  ↓
alert_rules.py 检查 promised_eta < now AND stage=running
  ↓
alert_dispatcher.py 检测到 timeout 事件
  ↓
human_report_renderer.py 生成超时告警
  ↓
alert_dispatcher.py 发送给用户
  ↓
alert_audit.py 记录审计日志
```

#### 失败事件流
```
subagent/tmux 失败
  ↓
completion_receipt.py 创建 receipt (status=failed)
  ↓
alert_dispatcher.py 检测到 failed 事件
  ↓
human_report_renderer.py 生成失败告警
  ↓
alert_dispatcher.py 发送给用户
  ↓
alert_audit.py 记录审计日志
```

---

## 3. 核心设计

### 3.1 告警调度器 (alert_dispatcher.py)

```python
class AlertDispatcher:
    """
    告警调度器
    
    核心方法：
    - check_and_dispatch(): 检查事件并调度告警
    - dispatch_completion_alert(): 完成事件告警
    - dispatch_timeout_alert(): 超时事件告警
    - dispatch_failure_alert(): 失败事件告警
    - is_duplicate(): 检查是否重复告警
    """
    
    # 告警类型
    AlertType = Literal[
        "task_completed",    # 任务完成
        "task_timeout",      # 任务超时
        "task_failed",       # 任务失败
        "task_stuck",        # 任务卡住
    ]
    
    # 告警通道
    DeliveryChannel = Literal[
        "file",              # 文件 mock (测试用)
        "discord",           # Discord 消息
        "openclaw_native",   # OpenClaw 原生消息
    ]
```

### 3.2 人话渲染器 (human_report_renderer.py)

```python
class HumanReportRenderer:
    """
    人话渲染器
    
    核心方法：
    - render_completion_summary(): 渲染完成摘要
    - render_timeout_alert(): 渲染超时告警
    - render_failure_alert(): 渲染失败告警
    - translate_technical_terms(): 翻译技术术语
    
    汇报模板：
    ## 任务完成汇报
    **任务**: {label}
    **状态**: ✅ 已完成 / ❌ 失败 / ⚠️ 超时
    **时间**: {duration}
    
    ### 结论
    {一句话总结}
    
    ### 证据
    - 技术指标：{metrics}
    - 关键输出：{output_summary}
    
    ### 动作
    - 建议操作：{recommended_actions}
    """
```

### 3.3 告警规则 (alert_rules.py)

```python
class AlertRules:
    """
    告警规则
    
    核心规则：
    - check_timeout(): 检查超时
    - check_failure(): 检查失败
    - check_completion(): 检查完成
    - check_stuck(): 检查卡住
    
    超时规则：
    - 当前时间 - promised_eta > threshold (默认 15 分钟)
    - stage 仍为 running/dispatch
    - 无 heartbeat 更新 (超过 10 分钟)
    """
```

### 3.4 审计日志 (alert_audit.py)

```python
class AlertAuditLogger:
    """
    审计日志
    
    核心方法：
    - log_alert(): 记录告警事件
    - log_report(): 记录汇报事件
    - query_logs(): 查询审计日志
    
    审计字段：
    - alert_id: 告警 ID
    - alert_type: 告警类型
    - task_id: 任务 ID
    - timestamp: 时间戳
    - payload: 告警内容
    - delivery_result: 发送结果
    """
```

---

## 4. 数据结构

### 4.1 AlertPayload

```json
{
  "alert_version": "alert_payload_v1",
  "alert_id": "alert_abc123",
  "alert_type": "task_completed | task_timeout | task_failed | task_stuck",
  "task_id": "task_xxx",
  "task_label": "feature-xxx",
  "scenario": "trading_roundtable",
  "owner": "main",
  "severity": "info | warning | error | critical",
  "timestamp": "2026-03-29T15:00:00",
  "human_message": "任务 feature-xxx 已完成，耗时 25 分钟...",
  "technical_details": {
    "receipt_id": "receipt_xyz",
    "receipt_status": "completed",
    "duration_seconds": 1500,
    "exit_code": 0,
    "artifacts": ["/path/to/report.md"]
  },
  "delivery": {
    "channel": "discord",
    "reply_to": "channel_id",
    "dedupe_key": "task_xxx:completed"
  },
  "metadata": {}
}
```

### 4.2 AlertDedupeKey

```python
# 去重 key 生成规则
def generate_dedupe_key(task_id: str, alert_type: str) -> str:
    return f"{task_id}:{alert_type}"

# 超时告警特殊处理：每小时允许一次
def generate_timeout_dedupe_key(task_id: str, hour: str) -> str:
    return f"{task_id}:timeout:{hour}"
```

### 4.3 AlertState

```json
{
  "alert_id": "alert_abc123",
  "status": "pending | sent | failed",
  "sent_at": "2026-03-29T15:00:00",
  "delivery_result": {
    "channel": "discord",
    "message_id": "msg_xyz",
    "error": null
  },
  "ack_status": "pending | acknowledged",
  "ack_at": null
}
```

---

## 5. 集成点

### 5.1 与 completion_receipt.py 集成

```python
# completion_receipt.py 创建 receipt 后调用
from alert_dispatcher import AlertDispatcher

def create_completion_receipt(...):
    receipt = ...  # 创建 receipt
    
    # 触发告警检查
    dispatcher = AlertDispatcher()
    dispatcher.check_and_dispatch(receipt)
    
    return receipt
```

### 5.2 与 watchdog.py 集成

```python
# watchdog.py 定期巡检时调用
from alert_dispatcher import AlertDispatcher

def periodic_check():
    dispatcher = AlertDispatcher()
    
    # 检查超时任务
    timeout_alerts = dispatcher.check_timeouts()
    
    # 检查卡住任务
    stuck_alerts = dispatcher.check_stuck()
    
    return timeout_alerts + stuck_alerts
```

### 5.3 与 hooks/post_completion_translate_hook.py 集成

```python
# 复用现有翻译钩子，增强为告警
from hooks.post_completion_translate_hook import PostCompletionTranslateHook

hook = PostCompletionTranslateHook()
requirement = hook.check(completion_receipt, task_context)

if requirement.requires_translation:
    # 生成翻译汇报
    translation = hook.enforce(completion_receipt, task_context)
    
    # 发送告警
    dispatcher.dispatch_completion_alert(translation)
```

---

## 6. 风险与回退

### 6.1 风险

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 告警刷屏 | 用户体验差 | 严格去重 + 节流控制 |
| 误报/漏报 | 信任度下降 | 审计日志 + 可配置阈值 |
| 性能开销 | 影响主流程 | 异步执行 + 后台处理 |
| 与现有系统集成失败 | 功能不可用 | 充分测试 + 回退方案 |

### 6.2 回退方案

如需回退：
```bash
# 1. 删除新增模块
rm runtime/orchestrator/alert_dispatcher.py
rm runtime/orchestrator/human_report_renderer.py
rm runtime/orchestrator/alert_rules.py
rm runtime/orchestrator/alert_audit.py
rm runtime/tests/orchestrator/alerts/test_*.py

# 2. 回滚集成点修改
git checkout runtime/orchestrator/completion_receipt.py
git checkout runtime/orchestrator/watchdog.py

# 3. 删除告警数据 (可选)
rm -rf ~/.openclaw/shared-context/alerts/

# 4. Git 回滚
git revert <commit_hash>
```

### 6.3 边界条件

| 边界 | 处理方式 |
|------|---------|
| completion_receipt 不存在 | 跳过告警，记录审计日志 |
| promised_eta 缺失 | 使用默认阈值 (30 分钟) |
| 告警发送失败 | 记录错误，不重试 (避免刷屏) |
| 重复告警 | 去重检查，跳过发送 |

---

## 7. 测试策略

### 7.1 单元测试

| 测试模块 | 测试内容 | 目标覆盖率 |
|---------|---------|-----------|
| `test_alert_dispatcher.py` | 告警调度逻辑、去重、节流 | 100% |
| `test_human_report_renderer.py` | 汇报渲染、模板、翻译 | 100% |
| `test_alert_rules.py` | 超时/失败/完成规则 | 100% |
| `test_alert_audit.py` | 审计日志读写 | 100% |

### 7.2 集成测试

| 测试场景 | 验证内容 |
|---------|---------|
| 完成事件闭环 | receipt 创建 → 告警生成 → 发送 → 审计 |
| 超时事件闭环 | watchdog 巡检 → 告警生成 → 发送 → 审计 |
| 失败事件闭环 | receipt 创建 (failed) → 告警生成 → 发送 → 审计 |

### 7.3 验证脚本

```bash
# verify-observability-batch4.sh
# 1. 运行单元测试
pytest runtime/tests/orchestrator/alerts/ -v

# 2. 验证告警模块可导入
python -c "from alert_dispatcher import AlertDispatcher"

# 3. 验证汇报渲染器可导入
python -c "from human_report_renderer import HumanReportRenderer"

# 4. 集成测试
python scripts/test-alert-batch4.py

# 5. 检查审计日志
ls -la ~/.openclaw/shared-context/alerts/audits/
```

---

## 8. 交付物清单

### 8.1 核心模块

| 文件 | 行数 (预估) | 说明 |
|------|-----------|------|
| `runtime/orchestrator/alert_dispatcher.py` | ~400 | 告警调度器 |
| `runtime/orchestrator/human_report_renderer.py` | ~300 | 人话渲染器 |
| `runtime/orchestrator/alert_rules.py` | ~150 | 告警规则 |
| `runtime/orchestrator/alert_audit.py` | ~100 | 审计日志 |

### 8.2 测试

| 文件 | 行数 (预估) | 说明 |
|------|-----------|------|
| `runtime/tests/orchestrator/alerts/test_alert_dispatcher.py` | ~300 | 调度器测试 |
| `runtime/tests/orchestrator/alerts/test_human_report_renderer.py` | ~250 | 渲染器测试 |
| `runtime/tests/orchestrator/alerts/test_alert_rules.py` | ~150 | 规则测试 |
| `runtime/tests/orchestrator/alerts/test_alert_audit.py` | ~100 | 审计测试 |

### 8.3 脚本与文档

| 文件 | 说明 |
|------|------|
| `scripts/verify-observability-batch4.sh` | 验证脚本 |
| `scripts/test-alert-batch4.py` | 集成测试脚本 |
| `docs/observability-batch4-completion-report.md` | 完成报告 |

---

## 9. 验收标准

| 验收项 | 标准 | 验证方式 |
|--------|------|---------|
| 完成事件生成可读摘要 | 有自然语言汇报，非 ACP 原始报告 | 测试 + 人工检查 |
| 超时事件生成可读告警 | 超时任务主动告警 | 测试 + 人工检查 |
| 失败事件生成可读告警 | 失败任务主动告警 | 测试 + 人工检查 |
| 不双写真值 | 告警层只读 truth plane | 代码审查 |
| 单元测试通过 | 100% 通过 | pytest |
| 验证脚本通过 | 100% 通过 | 执行验证脚本 |
| Git 提交完成 | 已 push 到 origin/main | git log |

---

## 10. 质量门

| 质量门 | 标准 |
|--------|------|
| 代码质量 | 无 lint 错误，类型注解完整 |
| 测试覆盖 | 核心路径 100%，分支>80% |
| 文档完整 | 模块 docstring + 使用示例 |
| 集成兼容 | 不破坏现有 completion_receipt / watchdog |
| 性能 | 单次告警检查 <100ms |

---

## 11. 后续工作

### Batch 4 完成后
1. 用户反馈收集
2. 告警规则优化（根据实际使用情况调整阈值）
3. 多通道支持（Discord/邮件/短信）

### Batch 5 (可选)
1. Web 可视化看板
2. 告警确认/升级流程
3. 复杂告警规则引擎

---

## 12. 参考文档

- [observability-transparency-design-2026-03-28.md](observability-transparency-design-2026-03-28.md)
- [observability-batch1-completion-report.md](observability-batch1-completion-report.md)
- [observability-batch2-completion-report.md](observability-batch2-completion-report.md)
- [observability-batch3-completion-report.md](observability-batch3-completion-report.md)
- [completion_receipt.py](../runtime/orchestrator/completion_receipt.py)
- [observability_card.py](../runtime/orchestrator/observability_card.py)
- [hooks/post_completion_translate_hook.py](../runtime/orchestrator/hooks/post_completion_translate_hook.py)

---

## 13. 变更日志

| 版本 | 日期 | 变更 |
|------|------|------|
| v0.1 | 2026-03-29 | 初始设计稿 |
| v1.0 | 2026-03-29 | 设计评审通过，开始实现 |
