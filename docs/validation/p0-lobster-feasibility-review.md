# P0-1《Lobster 可行性审计》

## 结论先行

**总评：PARTIAL（适合继续做“收缩版 P0 最小验证”，不适合按“通用编排引擎”预期推进）。**

一句话结论：**P0 值得继续用 Lobster 做最小验证，但前提是把目标收缩到「顺序 chain + human-gate + message/browser 桥接 + 单 subagent handoff」，不要把 parallel / 真 join / 原生 failure-branch 当作它现在已经具备的能力。**

---

## 1. 审计范围与方法

本次只看最小验证，不做大而全方案；重点回答：

1. Lobster 现在是否支持/能否低成本实现 `chain`、`parallel`、`join`、`human-gate`、`failure-branch`
2. 它与 OpenClaw `subagent` / `message` / `browser` 的接线难度
3. 哪些能力可直接复用，哪些需要补 adapter
4. 给出 yes / no / partial 结论

审计方法：
- 读 `openclaw/lobster` README 与源码
- 跑最小测试验证 approval / resume / OpenClaw bridge
- 只用最小证据，不扩展到 P1/P2 设计

---

## 2. 最终判断总表

| 能力 | 当前状态 | 低成本实现性 | 结论 | 说明 |
|---|---|---:|---|---|
| `chain` | 原生支持 | 高 | **YES** | 工作流文件 `steps[]` 顺序执行，天然适合 P0 顺序链 |
| `parallel` | 未见原生支持 | 低 | **NO** | 运行时是串行 `for` 循环；命令注册里也没有 parallel/join 原语 |
| `join` | 仅支持“顺序结果汇合” | 中 | **PARTIAL** | 可引用前序 `$step.stdout/$step.json` 拼接，但没有真正的并发 join/barrier |
| `human-gate` | 原生支持 | 高 | **YES** | `approval:` / `approve` + `resumeToken` + 状态清理都已具备 |
| `failure-branch` | 原生 fail-fast，有条件跳转但无 error branch | 中低 | **PARTIAL** | 失败默认直接抛错退出；若要失败后走 fallback，需补一层 adapter/小扩展 |
| OpenClaw `message` | 可直接桥接 | 高 | **YES** | `openclaw.invoke --tool message --action send ...` 模式天然匹配 |
| OpenClaw `browser` | 可直接桥接 | 高 | **YES** | `browser` 本身是 action 型接口，和 `openclaw.invoke` 契合 |
| OpenClaw `subagent` | 不能零成本直连完整闭环 | 中低 | **PARTIAL** | `sessions_spawn` 不是现成 action 型；且“spawn 后等待终态/回写”不是 Lobster 原生能力 |

---

## 3. 对五类能力的逐项审计

### 3.1 `chain`：**YES**

Lobster 很适合做 P0 的顺序链。

**判断理由**
- 工作流文件是 `steps:` 数组，天然按顺序执行。
- README 明确把工作流定义成“小脚本式”的顺序步骤。
- 运行时核心实现就是串行遍历步骤/阶段。

**最小证据**
- README：工作流样例明确是 `fetch -> confirm -> advice`
  - `README.md:170-203`
- 工作流执行器按 `for (let idx = startIndex; idx < steps.length; idx++)` 逐步执行
  - `src/workflows/file.ts:217-255`
- Pipeline 运行时也是串行 `for` 循环
  - `src/runtime.ts:46-67`
- 自带测试覆盖了顺序 collect → mutate → approve_step → finish
  - `test/workflow_file.test.ts:12-78`

**结论**
- `chain` 是 Lobster 当前最强、最稳、最适合 P0 的能力。

---

### 3.2 `parallel`：**NO**

当前没有看到 Lobster 的原生并发 stage / fan-out / fan-in 语义。

**判断理由**
- 运行时是严格串行执行，没有 `Promise.all`、worker pool、parallel stage 等结构。
- 默认命令注册表没有 `parallel` / `join` / `fork` 之类命令。
- README 也没有任何并发语义说明。

**最小证据**
- `runPipeline()` 逐 stage 串行执行
  - `src/runtime.ts:46-67`
- `runWorkflowFile()` 逐 step 串行执行
  - `src/workflows/file.ts:217-255`
- 默认 registry 只有 `exec/head/json/pick/.../approve/openclaw.invoke/...`，没有 parallel/join
  - `src/commands/registry.ts:28-53`
- 实跑 `node bin/lobster.js "commands.list | json"`，输出命令清单中未见 `parallel` / `join`

**结论**
- 如果 P0 需要“真并发”，Lobster 现在**不满足**。
- 若强行通过 shell 后台任务或外部 watcher 拼并发，已经超出“低成本验证”的边界。

---

### 3.3 `join`：**PARTIAL**

Lobster 只支持“顺序链上的结果汇合”，不支持“并发后的 barrier/join”。

**判断理由**
- 后续 step 可以引用前序 step 的 `stdout/json/approved`。
- 因此可以在一个后续 step 中把多个前序结果拼起来，当作“弱 join / merge”。
- 但由于前面没有原生 `parallel`，这个 join 不是 DAG 意义上的 join，只是**顺序结果汇总**。

**最小证据**
- README 支持 `stdin: $step.stdout` / `$step.json`
  - `README.md:172-175, 207-210, 269-271`
- 模板替换支持在字符串里引用 `$step.stdout | $step.json | $step.approved`
  - `src/workflows/file.ts:430-438`
- Shell / pipeline step 共用相同 args/env/results 模型
  - `README.md:207-210`

**结论**
- 如果 `join` 的定义是“把前面顺序步骤的结果汇总到一步”，**可以低成本做到**。
- 如果 `join` 的定义是“并发分支收敛点”，**当前不成立**。

---

### 3.4 `human-gate`：**YES**

这是 Lobster 当前第二个最成熟能力。

**判断理由**
- 有原生 `approve` 命令。
- 工作流 DSL 有专门的 `approval:` step。
- 在 tool / 非交互模式下，会返回 `approval_request + resumeToken`，并可恢复继续执行。
- 支持多次审批 gate 连续恢复。

**最小证据**
- README：`approval:` 被列为 workflow 一等能力
  - `README.md:172-175, 193-202, 209-210`
- `approve` 命令在 tool mode 下 emit `approval_request` 并 halt
  - `src/commands/stdlib/approve.ts:25-50`
- 工作流执行器遇到 approval 会保存 resume state，并返回 `needs_approval`
  - `src/workflows/file.ts:257-289`
- 测试验证：approval + resume 正常
  - `test/workflow_file.test.ts:12-78`
- 测试验证：两个审批门可串行恢复
  - `test/multi_approval_resume.test.ts:28-55`

**结论**
- `human-gate` 原生可用，P0 可以直接复用。

---

### 3.5 `failure-branch`：**PARTIAL**

Lobster 有“失败即停”的原生语义，但没有“失败后自动进 fallback 分支”的原生语义。

**判断理由**
- shell step 失败时，`runShellCommand()` 直接 reject。
- workflow condition 只支持 `$step.approved` / `$step.skipped`，不支持 `$step.failed`、`$step.json.status == ...` 这类错误分支表达式。
- 这意味着现在的默认行为是 **fail-fast**，不是 **failure-branch**。

**最小证据**
- step 命令失败直接抛 `workflow command failed (...)`
  - `src/workflows/file.ts:617-619`
- `evaluateCondition()` 仅接受 `approved|skipped`
  - `src/workflows/file.ts:461-479`
- README 仅提 `when` / `condition`，未见 `on_error` / `catch` / `fallback`
  - `README.md:207-210`

**能否低成本实现？**
- **可以，但要补 adapter 或一个很小的 DSL 扩展。**
- 两种低成本路线：
  1. **Adapter 路线**：把易失败步骤包成“永不抛异常、只输出 `{ok:false,error:...}`”的命令，然后再补一个很薄的 `branch.if` / `status.check` 命令。
  2. **小扩展路线**：给 `evaluateCondition()` 增加 `$step.json.xxx` / `$step.failed` 判定，或新增 `on_error` 字段。

**结论**
- 不是现成能力，但还没到“必须放弃”的程度；更准确是 **PARTIAL**。

---

## 4. 与 OpenClaw 的接线难度

### 4.1 `message`：**低难度，几乎可直接复用**

**原因**
- Lobster 已内置 `openclaw.invoke` 传输桥。
- `message` 本身就是典型 `tool + action + args` 模式。
- 这和 Lobster 的 `openclaw.invoke --tool <x> --action <y> --args-json <...>` 完全对齐。

**最小证据**
- README 明确提供 `openclaw.invoke` / `clawd.invoke` shim
  - `README.md:236-267`
- `openclaw.invoke` 的参数模型就是 `tool + action + args-json`
  - `src/commands/stdlib/openclaw_invoke.ts:14-27, 51-90`
- 其本质是 POST `/tools/invoke`
  - `src/commands/stdlib/openclaw_invoke.ts:73-90`

**结论**
- `message.send`、`message.react`、`message.read` 这一类 action 型工具，Lobster 接线难度很低。

---

### 4.2 `browser`：**低难度，可直接桥接**

**原因**
- `browser` 也是标准 action 型接口（如 `open/snapshot/act/...`）。
- Lobster 不需要理解浏览器语义本身，只要通过 `openclaw.invoke` 发请求即可。
- 复杂点只在于：browser 的返回结构比较富，需要业务侧自己约定 workflow 中取哪些字段。

**结论**
- `browser.open / snapshot / act` 级别接线难度低。
- 若要做“页面状态机 + 重试 + 条件等待”，那是 workflow 设计问题，不是 Lobster transport 问题。

---

### 4.3 `subagent` / `sessions_spawn`：**中低可行，但不是零成本**

这是本次审计里最需要警惕的点。

**问题 1：Lobster 自带桥接是 action 型；`sessions_spawn` 不是这个形态**
- `openclaw.invoke` 强制要求 `tool` 和 `action`
  - `src/commands/stdlib/openclaw_invoke.ts:54-56`
- 但 OpenClaw 当前 `sessions_spawn` 是“单函数型工具调用”，不是天然的 `tool+action` 风格。

**问题 2：spawn 只是第一步，真正难点是“等待终态 + 回写 + 收敛”**
- Lobster 当前强项是同步顺序步骤。
- 对 `sessions_spawn(runtime="subagent")` 这种异步子执行单元，P0 真正需要的是：
  1. 发起 handoff
  2. 获得 `session_id`
  3. 等待 completion event / callback
  4. 回写同一任务上下文
  5. 再继续主流程
- 这一整套不是 Lobster 现成原语。

**结论**
- **只做“spawn 一下并记录 session_id”**：可做，难度中等。
- **做“spawn + 等终态 + 回写主链 + 最终收敛”**：必须补 adapter，难度显著高于 message/browser。

**建议口径**
- 对 `subagent` 不要说“直接接上就行”；应说：**需要一个薄 adapter**，至少把它包装成：
  - `subagent.spawn`
  - `subagent.await`（或接 callback bus）
  - `subagent.result`

---

## 5. 哪些能力可直接复用，哪些要补 adapter

### 5.1 可直接复用

1. **顺序 workflow DSL**
   - `steps[]`
   - `run:` / `command:` / `pipeline:`
   - `stdin` / `env` / `cwd`

2. **审批与恢复机制**
   - `approval:`
   - `approve`
   - `resumeToken`
   - state-backed resume cleanup

3. **本地状态与恢复基础设施**
   - `state.get` / `state.set`
   - workflow/pipeline resume state

4. **OpenClaw action 型工具传输层**
   - `openclaw.invoke`
   - 对 `message` / `browser` 很合适

5. **LLM 调用能力**
   - `llm.invoke`
   - 适合做“浏览器结果总结 / 文本整理 / 分类”等工作流中的轻模型步骤

### 5.2 必须补 adapter 的地方

1. **`sessions_spawn` adapter**
   - 把非 action 型的 `sessions_spawn` 包一层，暴露成 Lobster 可稳定调用的形态
   - 建议名字：`subagent.spawn`

2. **异步 completion / callback adapter**
   - 解决“spawn 之后怎么知道结束”
   - 可选做法：
     - 复用 OpenClaw 现有 callback/watcher bus
     - 或用本地状态文件/回执文件做最小闭环

3. **failure-branch adapter / 小扩展**
   - 需要一个最小错误分支机制
   - 否则默认只有 fail-fast，没有 fallback path

4. **（若未来做 P1）parallel/join 扩展**
   - 这是能力扩展，不该塞进 P0 最小验证

---

## 6. P0 是否值得继续：我的明确判断

### 6.1 值得继续的前提

如果 P0 的目标是下面这个收缩版：

- 一个顺序 `chain`
- 一个 `human-gate`
- 一个 `message` 或 `browser` action 桥接
- 一个“单 subagent handoff + 回执收敛”的薄 adapter 验证

那么 **值得继续用 Lobster**，因为：
- 它已经有顺序 workflow、approval、resume、OpenClaw transport 这些现成资产
- 本地优先、JSON-first，很适合低成本原型
- 不需要先上 Temporal/LangGraph 这种更重的 runtime

### 6.2 不值得继续的前提

如果 P0 实际想验证的是：

- 原生并发 fan-out/fan-in
- 复杂 join/barrier
- 完整失败补偿树
- 多 subagent 并发编排与收敛

那 **不值得继续押 Lobster 当现成答案**，因为这些今天并不是它的强项。

---

## 7. 最小证据清单

### 7.1 README / 源码证据
- `README.md:170-203`：workflow 示例，证明顺序链 + approval + when
- `README.md:236-267`：`openclaw.invoke` 用法，证明可桥接 OpenClaw tool
- `src/runtime.ts:46-67`：pipeline 串行执行
- `src/workflows/file.ts:217-255`：workflow step 串行执行
- `src/workflows/file.ts:257-289`：approval + resumeToken
- `src/workflows/file.ts:461-479`：condition 仅支持 `approved|skipped`
- `src/workflows/file.ts:617-619`：step 失败默认抛错退出
- `src/commands/registry.ts:28-53`：默认命令集中无 `parallel/join`
- `src/commands/stdlib/openclaw_invoke.ts:14-27, 73-90`：OpenClaw 工具桥接契约

### 7.2 我实际跑过的命令

```bash
gh repo view openclaw/lobster --json name,description,homepageUrl,url,defaultBranchRef
gh api repos/openclaw/lobster/readme -H 'Accept: application/vnd.github.raw+json'

cd /tmp/lobster-audit
pnpm install --frozen-lockfile
pnpm build
node --test dist/test/workflow_file.test.js dist/test/multi_approval_resume.test.js dist/test/openclaw_invoke_alias.test.js dist/test/core_tool_runtime.test.js
node bin/lobster.js "commands.list | json"
```

### 7.3 实际结果摘要

- `gh repo view` 返回：Lobster 定位是 **OpenClaw-native workflow shell**
- 目标测试 **8/8 通过**：
  - approval + resume
  - multi approval resume
  - `openclaw.invoke` alias
  - tool runtime workflow resume
- `commands.list` 输出里未见 `parallel` / `join` 原语

---

## 8. 最终 yes / no / partial 结论

- `chain` → **YES**
- `parallel` → **NO**
- `join` → **PARTIAL**
- `human-gate` → **YES**
- `failure-branch` → **PARTIAL**
- `message` 接线 → **YES**
- `browser` 接线 → **YES**
- `subagent` 接线 → **PARTIAL**
- **Lobster 作为 P0 thin orchestration shell** → **PARTIAL（但值得继续做收缩版 P0）**

---

## 9. 一句话结论

**P0 值得继续用 Lobster 做最小验证，但必须收缩口径：把它当“顺序链 + 审批门 + OpenClaw action bridge + 单 subagent adapter”的薄编排壳，而不是已经具备并发/join/失败补偿的完整编排引擎。**
