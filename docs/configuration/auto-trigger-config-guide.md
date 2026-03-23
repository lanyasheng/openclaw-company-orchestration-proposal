# Auto-Trigger 配置指南

> **用途**：配置任务完成后的自动续线行为（receipt → request → consumed → execution）
> 
> **成熟度**：thin bridge / allowlist / safe semi-auto
> 
> **最后更新**：2026-03-24

---

## 快速开始（30 秒配置）

### Trading 场景（启用自动续线 + 真实执行）

```bash
# 1. 启用 auto-trigger 消费
cat > ~/.openclaw/shared-context/spawn_requests/auto_trigger_config.json << 'EOF'
{
  "enabled": true,
  "allowlist": ["trading*"],
  "denylist": [],
  "require_manual_approval": false
}
EOF

# 2. 启用真实 API 执行（关闭 safe_mode）
cat > ~/.openclaw/shared-context/spawn_requests/auto_trigger_real_exec_config.json << 'EOF'
{
  "enabled": true,
  "allowlist": ["trading*"],
  "denylist": [],
  "require_manual_approval": false,
  "safe_mode": false,
  "max_concurrent_executions": 3
}
EOF
```

### Channel 场景（仅自动消费，不真实执行）

```bash
# 1. 启用 auto-trigger 消费
cat > ~/.openclaw/shared-context/spawn_requests/auto_trigger_config.json << 'EOF'
{
  "enabled": true,
  "allowlist": ["channel*"],
  "denylist": [],
  "require_manual_approval": false
}
EOF

# 2. 保持 safe_mode（不真实执行）
cat > ~/.openclaw/shared-context/spawn_requests/auto_trigger_real_exec_config.json << 'EOF'
{
  "enabled": false,
  "allowlist": ["channel*"],
  "denylist": [],
  "require_manual_approval": true,
  "safe_mode": true,
  "max_concurrent_executions": 3
}
EOF
```

---

## 配置项总览

| 配置文件 | 用途 | 默认值 | 何时修改 | 配置方法 |
|---------|------|--------|---------|---------|
| `auto_trigger_config.json` | 控制 request 自动消费 | enabled=false | 想让场景自动续线 | 加入 allowlist + enabled=true |
| `auto_trigger_real_exec_config.json` | 控制真实 API 执行 | safe_mode=true | 想真实调用 sessions_spawn | safe_mode=false + enabled=true |

---

## 详细配置说明

### 配置 1：Auto-Trigger 消费（`auto_trigger_config.json`）

**位置**：`~/.openclaw/shared-context/spawn_requests/auto_trigger_config.json`

**用途**：控制 completion receipt 生成 request 后，是否自动触发 consumption（消费 request 生成 execution envelope）。

**配置项**：

```json
{
  "enabled": false,              // 是否启用 auto-trigger（默认 false）
  "allowlist": ["trading"],      // 允许自动触发的场景白名单
  "denylist": [],                // 禁止自动触发的场景黑名单
  "require_manual_approval": true // 是否需要手动审批（默认 true）
}
```

**字段说明**：

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `enabled` | bool | `false` | 总开关。false=完全禁用 auto-trigger |
| `allowlist` | List[str] | `["trading"]` | 场景白名单。支持通配符 `trading*` 匹配 `trading_*` |
| `denylist` | List[str] | `[]` | 场景黑名单。优先级高于 allowlist |
| `require_manual_approval` | bool | `true` | true=需要手动审批才能触发；false=自动触发 |

**何时修改**：

| 需求 | 修改方法 |
|------|---------|
| 想让 trading 场景自动续线 | `allowlist: ["trading*"]` + `enabled: true` + `require_manual_approval: false` |
| 想让 channel 场景自动续线 | `allowlist: ["channel*"]` + `enabled: true` |
| 想完全禁用 auto-trigger | `enabled: false` |
| 想临时禁止某场景 | 加入 `denylist` |

---

### 配置 2：Real Execution（`auto_trigger_real_exec_config.json`）

**位置**：`~/.openclaw/shared-context/spawn_requests/auto_trigger_real_exec_config.json`

**用途**：控制 consumption 后是否真实调用 `sessions_spawn()` API 执行任务，还是仅记录 execution envelope（safe_mode）。

**配置项**：

```json
{
  "enabled": false,                      // 是否启用真实执行（默认 false）
  "allowlist": ["trading"],              // 允许真实执行的场景白名单
  "denylist": [],                        // 禁止真实执行的场景黑名单
  "require_manual_approval": true,       // 是否需要手动审批（默认 true）
  "safe_mode": true,                     // 安全模式（默认 true=仅记录不执行）
  "max_concurrent_executions": 3         // 最大并发执行数（默认 3）
}
```

**字段说明**：

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `enabled` | bool | `false` | 总开关。false=不触发真实执行 |
| `allowlist` | List[str] | `["trading"]` | 场景白名单。仅白名单场景可真实执行 |
| `denylist` | List[str] | `[]` | 场景黑名单。优先级高于 allowlist |
| `require_manual_approval` | bool | `true` | true=需要手动审批；false=自动执行 |
| `safe_mode` | bool | `true` | **关键配置**：true=仅记录 execution envelope，不真实调用 API；false=真实执行 |
| `max_concurrent_executions` | int | `3` | 最大并发执行数，防止资源耗尽 |

**何时修改**：

| 需求 | 修改方法 |
|------|---------|
| 想让 trading 场景真实执行 | `allowlist: ["trading*"]` + `enabled: true` + `safe_mode: false` + `require_manual_approval: false` |
| 想测试链路但不真实执行 | 保持 `safe_mode: true` |
| 想限制并发数 | 调整 `max_concurrent_executions` |
| 想完全禁用真实执行 | `enabled: false` 或 `safe_mode: true` |

---

## 场景配置示例

### 示例 1：Trading 场景（生产环境）

**目标**：交易圆桌任务完成后自动续线并真实执行。

```json
// auto_trigger_config.json
{
  "enabled": true,
  "allowlist": ["trading*"],
  "denylist": [],
  "require_manual_approval": false
}

// auto_trigger_real_exec_config.json
{
  "enabled": true,
  "allowlist": ["trading*"],
  "denylist": [],
  "require_manual_approval": false,
  "safe_mode": false,
  "max_concurrent_executions": 3
}
```

**说明**：
- `trading*` 匹配所有 `trading_*` 场景（如 `trading_roundtable_phase1`、`trading_batch3_c2276a`）
- `safe_mode: false` 启用真实执行
- `require_manual_approval: false` 跳过手动审批

---

### 示例 2：Channel 场景（测试环境）

**目标**：频道圆桌任务完成后自动续线，但仅记录不执行（测试链路）。

```json
// auto_trigger_config.json
{
  "enabled": true,
  "allowlist": ["channel*"],
  "denylist": [],
  "require_manual_approval": false
}

// auto_trigger_real_exec_config.json
{
  "enabled": false,
  "allowlist": ["channel*"],
  "denylist": [],
  "require_manual_approval": true,
  "safe_mode": true,
  "max_concurrent_executions": 3
}
```

**说明**：
- `safe_mode: true` 保持安全模式，仅记录 execution envelope
- `enabled: false` 禁用真实执行

---

### 示例 3：混合场景（Trading 生产 + Channel 测试）

**目标**：Trading 场景真实执行，Channel 场景仅测试链路。

```json
// auto_trigger_config.json
{
  "enabled": true,
  "allowlist": ["trading*", "channel*"],
  "denylist": [],
  "require_manual_approval": false
}

// auto_trigger_real_exec_config.json
{
  "enabled": true,
  "allowlist": ["trading*"],  // 仅 trading 场景真实执行
  "denylist": ["channel*"],   // channel 场景禁止真实执行
  "require_manual_approval": false,
  "safe_mode": true,          // 非白名单场景保持 safe_mode
  "max_concurrent_executions": 3
}
```

---

## 验证方法

### 方法 1：查看当前配置状态

```bash
# 查看 auto-trigger 配置
cat ~/.openclaw/shared-context/spawn_requests/auto_trigger_config.json

# 查看 real exec 配置
cat ~/.openclaw/shared-context/spawn_requests/auto_trigger_real_exec_config.json
```

### 方法 2：查看 auto-trigger 状态

```bash
cd /Users/study/.openclaw/workspace/repos/openclaw-company-orchestration-proposal
python3 runtime/orchestrator/sessions_spawn_request.py auto-trigger-status
```

输出示例：
```json
{
  "config": {
    "enabled": true,
    "allowlist": ["trading*"],
    "require_manual_approval": false
  },
  "triggered_count": 5,
  "pending_requests": [
    {
      "request_id": "req_xxx",
      "scenario": "trading_roundtable_phase1",
      "task_id": "task_xxx"
    }
  ]
}
```

### 方法 3：查看 pending requests

```bash
# 查看 prepared 状态的 requests
ls -lt ~/.openclaw/shared-context/spawn_requests/req_*.json | head

# 查看具体 request 内容
cat ~/.openclaw/shared-context/spawn_requests/req_xxx.json | python3 -m json.tool
```

### 方法 4：手动触发测试

```bash
# 手动触发 consumption（不执行）
python3 runtime/orchestrator/sessions_spawn_request.py auto-trigger req_xxx

# 手动触发 consumption + execution（真实执行）
python3 runtime/orchestrator/sessions_spawn_request.py auto-trigger req_xxx --chain-to-execution
```

### 方法 5：查看 execution 结果

```bash
# 查看 API execution artifacts
ls -lt ~/.openclaw/shared-context/api_executions/exec_api_*.json | head

# 查看具体 execution 结果
cat ~/.openclaw/shared-context/api_executions/exec_api_xxx.json | python3 -m json.tool
```

**关键字段**：
- `api_execution_status`: `started`（成功）/ `failed`（失败）/ `pending`（safe_mode）
- `runId`: 真实执行的 run ID（成功时存在）
- `childSessionKey`: 子 session key（成功时存在）
- `api_error`: 错误信息（失败时存在）

---

## 故障排查

### 问题 1：任务完成后没有自动续线

**症状**：batch 完成后，没有生成 sessions_spawn request。

**排查步骤**：

```bash
# 1. 检查 completion receipt 是否生成
ls -lt ~/.openclaw/shared-context/completion_receipts/receipt_*.json | head

# 2. 检查 spawn request 是否生成
ls -lt ~/.openclaw/shared-context/spawn_requests/req_*.json | head

# 3. 检查 auto-trigger 配置
cat ~/.openclaw/shared-context/spawn_requests/auto_trigger_config.json

# 4. 手动触发测试
python3 runtime/orchestrator/sessions_spawn_request.py auto-trigger req_xxx
```

**可能原因**：
- `enabled: false` → 改为 `true`
- 场景不在 `allowlist` → 加入场景名
- `require_manual_approval: true` → 改为 `false` 或手动审批

---

### 问题 2：执行状态一直是 `pending`

**症状**：`api_execution_status` = `pending`，没有真实调用 `sessions_spawn`。

**排查步骤**：

```bash
# 1. 检查 safe_mode 配置
cat ~/.openclaw/shared-context/spawn_requests/auto_trigger_real_exec_config.json | grep safe_mode

# 2. 检查场景是否在 allowlist
cat ~/.openclaw/shared-context/spawn_requests/auto_trigger_real_exec_config.json | grep allowlist
```

**可能原因**：
- `safe_mode: true` → 改为 `false`（真实执行）
- 场景不在 `allowlist` → 加入场景名
- `enabled: false` → 改为 `true`

---

### 问题 3：执行失败（`api_execution_status: failed`）

**症状**：`api_execution_status` = `failed`，`api_error` 包含错误信息。

**排查步骤**：

```bash
# 1. 查看错误信息
cat ~/.openclaw/shared-context/api_executions/exec_api_xxx.json | python3 -c "import json,sys; print(json.load(sys.stdin)['api_execution_result']['api_error'])"

# 2. 检查 runner 脚本是否存在
ls -la ~/.openclaw/scripts/run_subagent_claude_v1.sh

# 3. 检查 cwd 目录是否存在
cat ~/.openclaw/shared-context/api_executions/exec_api_xxx.json | python3 -c "import json,sys; print(json.load(sys.stdin)['api_execution_result']['sessions_spawn_result']['input']['cwd'])"
```

**常见错误**：
- `unknown command 'sessions_spawn'` → CLI 路径问题（已修复，使用 Python API）
- `FileNotFoundError: [Errno 2] No such file or directory` → `cwd` 为空或不存在
- `Permission denied` → runner 脚本无执行权限

---

## 最佳实践

### 1. 首次接入新场景

**建议**：先测试链路，再开启真实执行。

```bash
# 步骤 1: 仅启用 auto-trigger 消费（safe_mode=true）
cat > ~/.openclaw/shared-context/spawn_requests/auto_trigger_real_exec_config.json << 'EOF'
{
  "enabled": false,
  "safe_mode": true
}
EOF

# 步骤 2: 验证链路（查看 generated artifacts）
python3 runtime/orchestrator/sessions_spawn_request.py auto-trigger-status

# 步骤 3: 确认稳定后开启真实执行
cat > ~/.openclaw/shared-context/spawn_requests/auto_trigger_real_exec_config.json << 'EOF'
{
  "enabled": true,
  "allowlist": ["your_scenario*"],
  "safe_mode": false,
  "require_manual_approval": false
}
EOF
```

---

### 2. 生产环境配置

**建议**：
- 明确 `allowlist`，不使用通配符
- 设置 `max_concurrent_executions` 防止资源耗尽
- 保留 `require_manual_approval: true` 对敏感操作

```json
{
  "enabled": true,
  "allowlist": ["trading_roundtable_phase1", "trading_roundtable_phase2"],
  "denylist": ["trading_sensitive_operation"],
  "require_manual_approval": true,
  "safe_mode": false,
  "max_concurrent_executions": 3
}
```

---

### 3. 开发/测试环境配置

**建议**：
- 使用通配符简化配置
- `safe_mode: true` 避免意外执行
- `require_manual_approval: false` 方便快速迭代

```json
{
  "enabled": true,
  "allowlist": ["test*", "dev*"],
  "safe_mode": true,
  "require_manual_approval": false
}
```

---

## 相关文档

- **快速开始**：`../quickstart/quickstart-other-channels.md`
- **架构说明**：`../architecture-layering.md`
- **当前真值**：`../CURRENT_TRUTH.md`
- **验证状态**：`../validation-status.md`
- **Runtime 源码**：`../../runtime/orchestrator/sessions_spawn_request.py`
- **Runtime 源码**：`../../runtime/orchestrator/sessions_spawn_bridge.py`

---

## 更新日志

| 日期 | 变更 |
|------|------|
| 2026-03-24 | 初始版本：整合分散的配置说明到单一文档 |
| 2026-03-24 | 修复 `emit_request()` 自动触发消费链 |
| 2026-03-24 | 更新 trading 场景默认配置为 `safe_mode: false` |
