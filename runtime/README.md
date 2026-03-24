# runtime/

本目录是本仓的 **orchestration 实现真值层**。

## 包含内容
- `orchestrator/`：核心编排逻辑
- `scripts/`：入口命令与 callback / dispatch bridge
- `skills/`：runtime 侧技能入口（当前主要是 `orchestration-entry`）

## 边界
- `docs/` 负责阅读入口、CURRENT_TRUTH、计划与边界说明
- `runtime/` 负责真实实现
- `tests/` 负责针对 `runtime/` 的验收

## 运行时产物边界

**不应提交到 repo 的文件**：
- `runtime/*.db` / `runtime/*.sqlite` / `runtime/*.sqlite3` — 运行时数据库文件
- `*.pid` — 进程 ID 文件
- `*.lock` — 锁文件

**可以保留在 repo 的文件**：
- `docs/reports/*.md` — 测试报告、验证报告、健康报告等文档性产物

**规则**：运行时产生的临时状态文件不应入仓；有文档价值的报告/总结应保留在 `docs/reports/`。

## 当前口径
- 本目录已从 OpenClaw workspace 中最小导入 orchestration 相关实现子树
- 不包含人格/记忆/runtime 数据/无关 skills/trading 杂项
- 当前整体成熟度仍是 **thin bridge / allowlist / safe semi-auto**，不是默认全自动闭环
