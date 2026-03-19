# human-gate-message

最小可用的人审门禁插件：拦截 OpenClaw `message` 工具发送动作，先落一条待审批 decision，再等待人工 approve / reject / withdraw。

## 代码归属

- **源码归属**：`openclaw-company-orchestration-proposal/plugins/human-gate-message/`
- **runtime repo 只保留最小 glue**：
  1. 在 `openclaw.json` 里加载插件
  2. 提供人工判定入口（CLI / UI / webhook / button handler）
  3. 把 verdict 回写到 `pending.json` / `decisions.jsonl`

不要再把 `human-gate-message` 的业务语义塞回 runtime 主仓。

## 目录结构

```text
plugins/human-gate-message/
├── README.md
├── cli.js
├── index.js
├── openclaw.plugin.json
├── package.json
├── examples/
│   ├── openclaw.example.json
│   └── pending-decision.example.json
└── tests/
    └── human-gate-message.test.js
```

## 安装

在 runtime 的 `openclaw.json` 中加载本目录：

```json
{
  "plugins": {
    "allow": ["human-gate-message"],
    "load": {
      "paths": ["/path/to/openclaw-company-orchestration-proposal/plugins/human-gate-message"]
    },
    "entries": {
      "human-gate-message": {
        "enabled": true,
        "timeoutSeconds": 300,
        "allowAgents": [],
        "storageDir": "~/.openclaw/shared-context/human-gate"
      }
    }
  }
}
```

然后重启 OpenClaw Gateway。

## 配置

| Key | 默认值 | 说明 |
|---|---|---|
| `enabled` | `true` | 是否启用插件 |
| `timeoutSeconds` | `300` | 等待人工 verdict 的超时秒数 |
| `allowAgents` | `[]` | 空数组 = 拦所有 agent；非空 = 只拦指定 agent |
| `storageDir` | `~/.openclaw/shared-context/human-gate` | decision 持久化目录 |

也可通过环境变量覆盖持久化目录：

```bash
export OPENCLAW_HUMAN_GATE_DIR=/tmp/human-gate-message
```

## 决策流

```text
Agent calls message tool
    ↓
Plugin intercepts before_tool_call
    ↓
Creates decision in pending.json
    ↓
Blocks and waits for verdict
    ↓
Human verdict via CLI / UI / webhook
    ↓
approved   -> message continues
rejected   -> message blocked
withdrawn  -> message blocked
timeout    -> message blocked
```

## CLI 用法

```bash
# 列出待处理 decision
node cli.js list

# 查看单条 decision
node cli.js get hg_20260319_175700_ab12

# 批准
node cli.js approve hg_20260319_175700_ab12

# 拒绝
node cli.js reject hg_20260319_175700_ab12 "inappropriate content"

# 撤回
node cli.js withdraw hg_20260319_175700_ab12 "user changed mind"
```

## 数据落点

默认目录：`~/.openclaw/shared-context/human-gate/`

- `pending.json`：当前 decision 状态
- `decisions.jsonl`：审计日志

decision 记录最小结构：

```json
{
  "decisionId": "hg_20260319_175700_ab12",
  "agentId": "main",
  "sessionKey": "agent:main:discord:channel:123456",
  "channel": "123456",
  "messagePreview": "first 200 chars...",
  "fullMessage": "complete message content",
  "createdAt": "2026-03-19T17:57:00.000Z",
  "expiresAt": "2026-03-19T18:02:00.000Z",
  "status": "pending|approved|rejected|timeout|withdrawn",
  "verdictAt": "2026-03-19T17:58:00.000Z",
  "verdictBy": "user123",
  "verdictReason": "manual approval"
}
```

## 测试

```bash
cd plugins/human-gate-message
npm test
```

测试默认使用临时目录，不污染真实 `~/.openclaw/shared-context/`。

## 限制

- 当前是阻塞式等待 verdict；长时间人审可能卡住上游 agent
- 还没有内建 UI；需要 runtime glue 自己提供按钮、表单或 webhook
- 目前按单机文件存储设计，不适合高并发审批面
