# Orch Product Guide — 产品化三件套快速入门

> **其他 agent 一句话就会用**：`onboard` → `run` → `status`

---

## 概述

`orch_product.py` 是 OpenClaw Orchestration 的**产品化统一入口**，提供三个简单命令：

| 命令 | 用途 | 一句话说明 |
|-----|------|-----------|
| `onboard` | 生成频道接入建议 | "这个频道该怎么接入编排系统？" |
| `run` | 触发执行 | "帮我跑个任务" |
| `status` | 查看状态 | "现在进展怎么样了？" |

**设计原则：**
- ✅ 复用现有 control plane，不另起真值链
- ✅ 零心智负担：不用理解 contract/backend/observability 内部概念
- ✅ 向后兼容：现有 `orch_command.py` 入口保持不变

---

## 安装

无需额外安装。命令位于：

```bash
/Users/study/.openclaw/workspace/repos/openclaw-company-orchestration-proposal/runtime/scripts/orch_product.py
```

建议添加到 PATH 或创建别名：

```bash
# 添加到 ~/.zshrc 或 ~/.bashrc
alias orch='python3 /Users/study/.openclaw/workspace/repos/openclaw-company-orchestration-proposal/runtime/scripts/orch_product.py'

# 验证
orch --help
```

---

## 快速开始

### 1. Onboard — 查看频道接入建议

```bash
# 最小用法 — 当前频道自动推导
python3 runtime/scripts/orch_product.py onboard

# 指定频道
python3 runtime/scripts/orch_product.py onboard \
  --channel-id "discord:channel:123456" \
  --channel-name "general" \
  --topic "架构讨论"

# 指定场景
python3 runtime/scripts/orch_product.py onboard \
  --context "trading_roundtable" \
  --backend "tmux"
```

**输出示例：**
```
=== orch_product_v1 ===

Channel: discord:channel:1483883339701158102 (temporal-vs-langgraph-openclaw-company-architecture)
Topic: Temporal vs LangGraph｜OpenClaw 公司级编排架构

Recommendation:
  Adapter: channel_roundtable
  Scenario: current_channel_architecture_roundtable
  Owner: main
  Backend: subagent
  Gate Policy: stop_on_gate

Next Steps:
  1. 确认推荐配置（adapter/scenario/owner/backend）
  2. 运行 'orch_product.py run --task "任务描述"' 触发执行
  3. 运行 'orch_product.py status' 查看状态
  4. Channel 场景：关注 roundtable 五字段（conclusion/blocker/owner/next_step/completion_criteria）

Example Commands:
  onboard: python3 runtime/scripts/orch_product.py onboard --channel-id "discord:channel:1483883339701158102"
  run: python3 runtime/scripts/orch_product.py run --channel-id "discord:channel:1483883339701158102" --task "任务描述"
  status: python3 runtime/scripts/orch_product.py status --channel-id "discord:channel:1483883339701158102"
```

**关键字段说明：**
- `adapter`: 使用的适配器（`channel_roundtable` / `trading_roundtable`）
- `scenario`: 场景标识（决定使用哪套业务逻辑）
- `owner`: 任务负责人（决定状态卡归属）
- `backend`: 推荐执行后端（`subagent` / `tmux`）
- `gate_policy`: Gate 策略（默认 `stop_on_gate`）

---

### 2. Run — 触发执行

```bash
# 最小用法 — 使用当前频道默认配置
python3 runtime/scripts/orch_product.py run --task "任务描述"

# 指定工作目录
python3 runtime/scripts/orch_product.py run \
  --task "重构认证模块" \
  --workdir /Users/study/.openclaw/workspace

# 显式指定 backend
python3 runtime/scripts/orch_product.py run \
  --task "写 README 文档" \
  --backend subagent \
  --workdir /path/to/workdir

# 长任务（需要监控中间过程）
python3 runtime/scripts/orch_product.py run \
  --task "调试偶发的网络问题，可能需要监控" \
  --backend tmux \
  --workdir /path/to/workdir \
  --monitor

# 指定任务类型和预计时长
python3 runtime/scripts/orch_product.py run \
  --task "实现用户认证功能" \
  --type coding \
  --duration 60 \
  --workdir /path/to/workdir
```

**输出示例：**
```
=== orch_product_v1 ===

Task ID: task_abc123
Description: 重构认证模块

Execution:
  Backend: subagent
  Session: subagent-feature-abc123
  Status: pending

Callback Path: /Users/study/.openclaw/shared-context/dispatches/dispatch_xyz-callback.json

Next Steps:
  1. 任务已派发为 subagent (label=feature-abc123)
  2. 等待 callback 完成（自动触发）
  3. 运行 'orch_product.py status' 查看进度
```

**关键字段说明：**
- `task_id`: 任务唯一标识
- `dispatch_id`: 派发唯一标识
- `backend`: 实际使用的执行后端
- `session_id`: 会话标识（tmux session 名或 subagent label）
- `callback_path`: 回调文件路径（完成后自动写入）
- `wake_command`: tmux 专用，用于检查任务状态

---

### 3. Status — 查看状态

```bash
# 当前频道状态
python3 runtime/scripts/orch_product.py status

# 指定负责人
python3 runtime/scripts/orch_product.py status --owner "main"

# 查询单个任务
python3 runtime/scripts/orch_product.py status --task-id "task_abc123"

# 过滤阶段
python3 runtime/scripts/orch_product.py status --stage "running"

# 限制结果数量
python3 runtime/scripts/orch_product.py status --limit 10
```

**输出示例：**
```
=== orch_product_v1 ===

Summary:
  Total: 5
  Active: 2
  Completed: 3
  Failed: 0

Active Tasks (2):
  - task_abc123: running @ subagent
  - task_def456: dispatch @ tmux

Completed Tasks (3):
  - task_ghi789: completed (verdict: PASS)
  - task_jkl012: completed (verdict: PASS)
  - task_mno345: completed (verdict: CONDITIONAL)

Next Steps:
  1. 2 个任务正在进行中
  2. 等待任务完成（自动回调）
  3. 3 个任务已完成
  4. 检查 completed 任务的 verdict 和 artifact
  5. 运行 'orch_product.py status' 定期刷新状态
```

**关键字段说明：**
- `summary`: 汇总统计（total/active/completed/failed）
- `active_tasks`: 进行中的任务列表
- `completed_tasks`: 已完成的任务列表
- `blockers`: 阻塞问题列表（失败任务）
- `next_steps`: 下一步行动建议

---

## 完整工作流示例

### 场景 1: Channel Roundtable 新频道接入

```bash
# 1. 查看接入建议
python3 runtime/scripts/orch_product.py onboard \
  --channel-id "discord:channel:9999" \
  --channel-name "product-review" \
  --topic "产品评审圆桌" \
  --owner "content"

# 2. 触发第一个任务
python3 runtime/scripts/orch_product.py run \
  --channel-id "discord:channel:9999" \
  --task "生成产品评审圆桌的 summary 和 decision" \
  --workdir /Users/study/.openclaw/workspace \
  --type documentation \
  --duration 30

# 3. 等待完成，查看状态
python3 runtime/scripts/orch_product.py status --owner "content"
```

### 场景 2: Trading Roundtable 续推

```bash
# 1. 查看当前配置
python3 runtime/scripts/orch_product.py onboard \
  --context "trading_roundtable"

# 2. 触发下一批次
python3 runtime/scripts/orch_product.py run \
  --context "trading_roundtable" \
  --task "运行 frozen candidate acceptance harness" \
  --workdir /Users/study/workspace-trading \
  --type coding \
  --duration 45 \
  --monitor

# 3. 监控进度
python3 runtime/scripts/orch_product.py status --owner "trading" --scenario "trading_roundtable_phase1"
```

### 场景 3: 调试问题任务

```bash
# 1. 查看失败任务
python3 runtime/scripts/orch_product.py status --stage "failed"

# 2. 查询单个任务详情
python3 runtime/scripts/orch_product.py status --task-id "task_failed_123"

# 3. 根据 blocker 决定重试/转交/中止
# （手动决策后重新 run 或放弃）
```

---

## JSON 输出

所有命令支持 `--output json` 用于程序化处理：

```bash
# JSON 输出
python3 runtime/scripts/orch_product.py onboard --output json

# 用 jq 处理
python3 runtime/scripts/orch_product.py status --output json | jq '.summary'
```

---

## 与现有入口的对比

| 特性 | `orch_command.py` (旧) | `orch_product.py` (新) |
|-----|----------------------|---------------------|
| 目标用户 | 平台工程师 | 频道 operator / agent |
| 心智负担 | 需要理解 contract/backend | 零概念，三件套 |
| 输出 | 完整 contract JSON | 简化建议卡 + 执行结果 |
| 执行 | 仅生成 contract | 直接触发执行 |
| 状态 | 无 | 内置 status 命令 |
| 向后兼容 | N/A | ✅ 完全兼容 |

**建议：**
- 新频道/新 agent：优先使用 `orch_product.py`
- 平台开发/调试：仍可使用 `orch_command.py` 查看完整 contract

---

## 故障排查

### 问题：`onboard` 返回的 backend 不是预期的

**原因：** backend_selector 根据任务特征自动推荐

**解决：** `run` 命令显式指定 `--backend subagent` 或 `--backend tmux`

### 问题：`status` 返回空结果

**原因：** 尚未创建任何 observability card

**解决：** 先用 `run` 触发至少一个任务

### 问题：`run` 执行失败

**检查：**
1. 工作目录是否存在且可写
2. Claude CLI 是否已安装（subagent 路径）
3. tmux 是否可用（tmux 路径）

**查看错误详情：**
```bash
python3 runtime/scripts/orch_product.py run ... --output json | jq '.error'
```

---

## 高级用法

### 环境变量覆盖

```bash
# 覆盖频道 ID
export ORCH_CHANNEL_ID="discord:channel:123456"
python3 runtime/scripts/orch_product.py onboard

# 覆盖 backend 偏好
export ORCH_BACKEND="tmux"
python3 runtime/scripts/orch_product.py run --task "..."
```

### 与现有工具集成

```bash
# 生成 contract 后手动处理
python3 runtime/scripts/orch_product.py onboard --output json | \
  jq '.full_contract' > contract.json

# 批量状态查询
for owner in main trading ainews; do
  python3 runtime/scripts/orch_product.py status --owner $owner --output json
done
```

---

## 参考文档

- [设计摘要](../docs/design/orch-product-entry-design-2026-03-30.md)
- [Operations Guide](OPERATIONS.md)
- [Current Truth](CURRENT_TRUTH.md)
- [Backend Selection Guide](BACKEND_SELECTION_GUIDE.md)

---

## 总结

**记住这三个命令就够了：**

```bash
# 1. 怎么接入？
orch_product.py onboard

# 2. 跑个任务
orch_product.py run --task "..."

# 3. 进展如何？
orch_product.py status
```

其他都是细节。
