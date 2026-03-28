# OpenClaw-RL 集成报告

**调研日期**: 2026-03-28  
**调研人**: Zoe (subagent)  
**仓库**: https://github.com/Gen-Verse/OpenClaw-RL.git  
**位置**: `/tmp/openclaw-rl`

---

## 核心能力

### 1. 框架概述

OpenClaw-RL 是一个**完全异步的强化学习框架**，用于将日常对话转化为个性化 AI 代理的训练信号。核心特点：

- **完全异步 4 组件架构**: Agent 服务、Rollout 收集、PRM/Judge 评估、Policy 训练相互独立
- **自托管 & 隐私保护**: 所有组件（policy model、judge/PRM、trainer）都在本地基础设施运行
- **自动从反馈到梯度**: 无需手动标注，系统自动组织多轮交互、分类 main/side turns、异步评估
- **三种优化方法**: Binary RL (GRPO)、On-Policy Distillation (OPD)、Combine (混合)

### 2. 三种学习方法

| 方法 | 信号类型 | 优势 | 适用场景 |
|------|---------|------|---------|
| **Binary RL** | 评估性 (好/坏) | 序列级标量奖励，所有 scored turns 都可用 | 用户隐式反馈、环境结构化输出 |
| **OPD** | 方向性 | Token 级精细修正，高梯度分辨率 | 用户显式纠正、详细错误追踪 |
| **Combine** | 评估 + 方向 | 混合优势，实验效果最佳 | 通用场景，推荐默认使用 |

### 3. 核心组件

```
openclaw-rl/
├── openclaw_api_server.py      # FastAPI 代理 + PRM 评分 + 样本提交
├── openclaw_rollout.py         # Async rollout worker (桥接 API server ↔ SLIME trainer)
└── run_qwen3_4b_openclaw_rl.sh # 启动脚本

openclaw-combine/
├── openclaw_combine_api_server.py  # 混合方法 API 服务
├── openclaw_combine_rollout.py     # 混合方法 Rollout
├── combine_loss.py                 # 加权优势计算
└── run_qwen35_4b_openclaw_combine.sh

extensions/rl-training-headers/     # OpenClaw 插件 (关键集成点)
├── index.ts                        # 注入 X-Session-Id 和 X-Turn-Type headers
├── openclaw.plugin.json
└── README.md
```

### 4. 支持的场景 (Track 2)

- **terminal-rl/**: Terminal agent 训练 (Docker 环境)
- **gui-rl/**: GUI agent 训练
- **swe-rl/**: 软件工程 agent 训练
- **toolcall-rl/**: Tool-call agent 训练

### 5. 技术栈

- **训练后端**: SLIME (基于 Megatron-LM)
- **推理服务**: SGLang
- **支持模型**: Qwen3、Qwen3.5 (支持 LoRA)
- **部署模式**: 本地 GPU 或云端 (Tinker)

---

## 集成方案

### 方案 A: 轻量级集成 (推荐起点)

**目标**: 先启用 rl-training-headers 插件，收集训练数据，暂不启动完整 RL 训练

**步骤**:

1. **安装插件**:
```bash
# 复制插件到 OpenClaw 扩展目录
cp -r /tmp/openclaw-rl/extensions/rl-training-headers \
  ~/.openclaw/extensions/rl-training-headers

# 启用插件
cd ~/.openclaw
corepack pnpm start -- plugins enable rl-training-headers

# 重启 Gateway
openclaw gateway restart
```

2. **验证 Headers 注入**:
```bash
# 检查 openclaw.json 中插件配置
cat ~/.openclaw/openclaw.json | jq '.plugins.entries["rl-training-headers"]'

# 预期输出:
# {
#   "enabled": true,
#   "config": {
#     "sessionIdHeader": "X-Session-Id",
#     "turnTypeHeader": "X-Turn-Type"
#   }
# }
```

3. **数据收集**:
   - 插件会自动为每个 LLM API 请求注入 `X-Session-Id` 和 `X-Turn-Type` headers
   - 可在 API 代理层或日志中捕获这些数据
   - 用于后续离线分析或训练

**优点**:
- 零训练成本，仅收集数据
- 不影响现有系统稳定性
- 可积累高质量对话数据

**缺点**:
- 暂无在线 RL 优化

---

### 方案 B: 完整集成 (需要 GPU 资源)

**目标**: 部署完整的 OpenClaw-RL 训练循环，实现在线优化

#### B1: 环境准备

```bash
# 创建 Conda 环境 (需要 CUDA 12.9)
conda create --name openclaw-rl python=3.12 -y
conda activate openclaw-rl

# 安装 PyTorch (根据 CUDA 版本调整)
pip install torch==2.9.1+cu129 torchvision==0.24.1+cu129 torchaudio==2.9.1+cu129 \
  --index-url https://download.pytorch.org/whl/cu129

# 安装依赖
pip install -r /tmp/openclaw-rl/requirements.txt

# 安装额外组件 (参考 instructions/README.md)
# - DeepEP, apex, flash_attn, flashinfer, megatron-bridge, TransformerEngine
```

#### B2: 部署架构

```
┌─────────────────────────────────────────────────────────────┐
│                     OpenClaw Gateway                        │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  rl-training-headers 插件                            │    │
│  │  - 注入 X-Session-Id, X-Turn-Type headers           │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│              OpenClaw-RL API Server                         │
│  (openclaw_combine_api_server.py)                           │
│  - FastAPI 代理，转发请求到 SGLang                          │
│  - 异步 PRM/Judge 评估                                      │
│  - 样本收集与提交                                           │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│              Rollout Worker                                 │
│  (openclaw_combine_rollout.py)                              │
│  - 桥接 API Server ↔ SLIME Trainer                          │
│  - 异步样本收集                                             │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│              SLIME Trainer                                  │
│  (基于 Megatron-LM)                                         │
│  - GRPO + OPD 混合训练                                      │
│  - LoRA 或全参数微调                                        │
│  - Checkpoint 保存                                          │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│              SGLang 推理服务                                │
│  - 部署训练后的 Policy Model                                │
│  - OpenAI 兼容 API                                          │
│  - 支持 per-token logprobs                                  │
└─────────────────────────────────────────────────────────────┘
```

#### B3: 启动训练 (以 Combine 方法为例)

```bash
cd /tmp/openclaw-rl

# 设置环境变量
export HF_HOME="/path/to/huggingface"
export MODEL_CKPT="/path/to/Qwen3.5-4B"
export REF_LOAD="/path/to/Qwen3.5-4B"  # 参考模型
export SAVE_CKPT="/path/to/save/checkpoints"
export WANDB_KEY="your-wandb-key"

# 启动训练 (Qwen3.5, LoRA, 4 GPUs)
cd slime
bash ../openclaw-combine/run_qwen35_4b_openclaw_combine_lora.sh
```

#### B4: 与现有 Subagent 系统集成

**关键观察**: OpenClaw-RL 的 rollout 系统与现有 subagent 系统是**正交的**:

| 维度 | 现有 Subagent 系统 | OpenClaw-RL |
|------|------------------|-------------|
| 目的 | 任务执行 (编码/调研) | RL 训练数据收集 |
| 触发 | 用户任务分配 | 用户对话交互 |
| 输出 | 任务完成报告 | 训练样本 (state, action, reward) |
| 执行者 | Claude Code CLI | SGLang + SLIME |

**集成策略**:

1. **保持现有 subagent 系统不变**
   - `scripts/run_subagent_claude_v1.sh` 继续负责任务执行
   - subagent 内部仍可调用 Claude Code CLI

2. **为特定 agent 启用 RL 训练**
   - **trading**: 高价值场景，建议优先启用 (市场反馈=天然 reward)
   - **macro**: 中等优先级 (新闻/数据反馈可作为 reward 信号)
   - **content**: 低优先级 (用户互动数据可作为 reward)
   - **butler**: 低优先级 (任务完成状态可作为 binary reward)

3. **实现方式**:
   - 为每个 agent 配置独立的 `session_id` 前缀
   - 在 `rl-training-headers` 插件中扩展 `turn_type` 分类逻辑
   - 为 trading/macro 配置更积极的 `main` turn 判定

---

### 方案 C: 混合部署 (推荐生产环境)

**架构**:

```
开发/测试环境 (本地 Mac Studio):
- 运行 rl-training-headers 插件收集数据
- 离线分析对话质量
- 小批量实验性训练 (LoRA, 单 GPU)

生产环境 (GPU 集群或 Tinker 云):
- 部署完整 OpenClaw-RL 训练循环
- 定期从开发环境同步数据
- 训练后推送 checkpoint 回开发环境
```

**优势**:
- 开发环境轻量化，不影响日常使用
- 生产环境专注训练，资源利用高效
- 数据隔离，降低风险

---

## 工作量评估

### 阶段 1: 轻量级集成 (1-2 天)

| 任务 | 工作量 | 负责人 |
|------|--------|--------|
| 安装 rl-training-headers 插件 | 0.5 天 | Zoe |
| 验证 Headers 注入 | 0.5 天 | Zoe |
| 配置数据收集管道 | 1 天 | Zoe + butler |
| 文档与 SOP 编写 | 0.5 天 | content |

**交付物**:
- 插件安装完成
- 数据收集管道运行
- 集成文档

### 阶段 2: 完整训练环境 (3-5 天，需要 GPU)

| 任务 | 工作量 | 负责人 |
|------|--------|--------|
| GPU 环境配置 (CUDA/PyTorch/SLIME) | 1-2 天 | trading (有量化经验) |
| SGLang 推理服务部署 | 0.5 天 | trading |
| OpenClaw-RL API Server 配置 | 0.5 天 | Zoe |
| 训练脚本调试与验证 | 1-2 天 | trading + Zoe |
| 与 OpenClaw Gateway 集成 | 0.5 天 | Zoe |

**交付物**:
- 完整训练环境运行
- 端到端训练示例完成
- 性能基准测试

### 阶段 3: 多 Agent 适配 (2-3 天)

| 任务 | 工作量 | 负责人 |
|------|--------|--------|
| trading agent RL 适配 | 1 天 | trading |
| macro agent RL 适配 | 0.5 天 | ainews/macro |
| content/butler RL 适配 | 0.5 天 | content/butler |
| 统一监控看板 | 1 天 | Zoe |

**交付物**:
- 各 agent RL 配置完成
- 监控看板上线

---

## 风险与回退

### 技术风险

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| CUDA/PyTorch 环境配置复杂 | 高 | 中 | 优先用 Tinker 云部署，跳过本地配置 |
| 训练不稳定/发散 | 中 | 高 | 先用 LoRA 小批量实验，验证后再全参数 |
| SGLang 推理服务性能不足 | 中 | 中 | 预设 batch size 上限，监控延迟 |
| 与现有 Gateway 冲突 | 低 | 高 | 插件设计为被动注入，不修改核心逻辑 |
| 数据隐私泄露 | 低 | 高 | 全本地部署，禁止外发数据 |

### 回退方案

**Level 1: 插件回退**
```bash
# 禁用插件
corepack pnpm start -- plugins disable rl-training-headers

# 重启 Gateway
openclaw gateway restart
```

**Level 2: 训练回退**
```bash
# 停止训练进程
pkill -f "openclaw_combine_api_server"
pkill -f "openclaw_combine_rollout"

# 恢复原始模型配置
# 修改 OpenClaw 配置，指回原始模型端点
```

**Level 3: 完整回退**
```bash
# 删除 RL 相关组件
rm -rf ~/.openclaw/extensions/rl-training-headers
rm -rf /tmp/openclaw-rl

# 恢复 openclaw.json 备份
cp ~/.openclaw/openclaw.json.backup ~/.openclaw/openclaw.json

# 重启 Gateway
openclaw gateway restart
```

### 监控指标

**训练健康度**:
- 样本收集速率 (samples/hour)
- 训练 loss 曲线
- Checkpoint 保存间隔

**推理性能**:
- P95 延迟
- 吞吐量 (requests/second)
- 错误率

**业务影响**:
- Agent 任务完成率变化
- 用户满意度 (如有反馈)
- Token 使用效率

---

## 推荐执行路径

### 立即执行 (本周)

1. **安装 rl-training-headers 插件** (方案 A)
   - 零风险，仅收集数据
   - 为未来训练积累素材

2. **文档与团队同步**
   - 向 trading/macro/content/butler 同步 OpenClaw-RL 能力
   - 收集各 agent 的 RL 需求优先级

### 短期规划 (2-4 周)

3. **GPU 资源评估**
   - 评估本地 Mac Studio 是否支持 (M1 Max 无 CUDA，不支持)
   - 考虑租用云 GPU 或使用 Tinker 云服务

4. **试点训练 (trading agent)**
   - trading 场景 reward 信号最清晰 (盈亏=天然 reward)
   - 小批量 LoRA 实验验证可行性

### 长期规划 (1-3 月)

5. **扩展到多 agent**
   - 根据试点结果决定是否扩展
   - 为 macro/content/butler 配置 RL

6. **自动化训练循环**
   - 定期自动训练 (如每周一次)
   - 自动评估 checkpoint 质量
   - 自动/手动部署最佳模型

---

## 关键发现

1. **OpenClaw-RL 与现有 subagent 系统正交**: 前者优化对话策略，后者执行具体任务，可并行运行

2. **插件是核心集成点**: `rl-training-headers` 插件是唯一需要修改 OpenClaw 的地方，设计轻量

3. **训练资源门槛较高**: 完整训练需要多 GPU 集群，建议优先用云服务 (Tinker)

4. **trading 是最佳试点场景**: 市场反馈提供天然 reward 信号，RL 优化收益最大

5. **Combine 方法效果最佳**: 根据 README，混合 Binary RL + OPD 效果优于单一方法

---

## 附录：关键文件清单

### 核心代码
- `/tmp/openclaw-rl/openclaw-rl/openclaw_api_server.py` - API 代理服务
- `/tmp/openclaw-rl/openclaw-rl/openclaw_rollout.py` - Rollout worker
- `/tmp/openclaw-rl/openclaw-combine/openclaw_combine_api_server.py` - 混合方法 API
- `/tmp/openclaw-rl/openclaw-combine/combine_loss.py` - 损失函数

### 启动脚本
- `/tmp/openclaw-rl/openclaw-rl/run_qwen35_4b_openclaw_rl.sh`
- `/tmp/openclaw-rl/openclaw-combine/run_qwen35_4b_openclaw_combine.sh`
- `/tmp/openclaw-rl/openclaw-combine/run_qwen35_4b_openclaw_combine_lora.sh`

### 插件
- `/tmp/openclaw-rl/extensions/rl-training-headers/` - OpenClaw 插件

### 文档
- `/tmp/openclaw-rl/README.md` - 主文档
- `/tmp/openclaw-rl/instructions/README.md` - 环境配置
- `/tmp/openclaw-rl/openclaw-rl/README.md` - Binary RL 文档
- `/tmp/openclaw-rl/openclaw-combine/README.md` - Combine 方法文档
- `/tmp/openclaw-rl/terminal-rl/README.md` - Terminal agent 文档

---

**报告完成时间**: 2026-03-28 16:45 GMT+8  
**下一步建议**: 执行阶段 1 (轻量级集成)，安装 rl-training-headers 插件
