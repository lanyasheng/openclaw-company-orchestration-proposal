# 通用编排内核重构 — Phase Engine 架构设计

## 目标
将 trading_roundtable.py (1324 行) 中的通用编排逻辑抽象成独立的 phase engine，交易特定逻辑下沉为适配器，目标精简到~500 行。

## 架构设计

### 核心模块 (runtime/orchestrator/core/)

#### 1. phase_engine.py (已存在，669 行)
- PhaseState, PhaseTransition 状态机
- Phase, PhaseEngine 核心类
- QualityGate, GateResult 质量门抽象
- CallbackRouter, CallbackEvent 回调路由
- FanOutMode, FanInMode fan-out/fan-in 控制

#### 2. task_registry.py (新建)
- TaskRegistry 类：任务注册表
- TaskRegistration 数据类：任务注册记录
- 支持任务状态追踪、查询、持久化
- 与 state_machine.py 解耦

#### 3. quality_gate.py (新建)
- QualityGateEvaluator 类：质量门评估器
- 预定义检查函数：packet completeness, artifact truth, gate consistency
- 支持组合检查、阻塞条件收集
- 返回结构化 GateResult

#### 4. fanout_controller.py (新建)
- FanOutController 类：fan-out 执行控制器
- 支持 sequential/parallel/batched 模式
- 子任务状态追踪、聚合
- Fan-in 条件评估

#### 5. callback_router.py (新建)
- CallbackRouter 类：回调路由器（增强 core/phase_engine.py 中的基础版本）
- 支持事件订阅、过滤
- 回调链执行、错误处理
- 事件日志持久化

#### 6. dispatch_planner.py (新建)
- DispatchPlanner 类：调度计划生成器
- 基于 decision 生成 dispatch plan
- 支持 backend 选择、timeout policy
- 持久化 dispatch plan

### 适配器模块 (runtime/orchestrator/adapters/)

#### 1. base.py (新建)
- BaseAdapter 抽象基类
- 定义适配器接口：
  - validate_packet()
  - build_summary()
  - build_continuation_plan()
  - evaluate_auto_dispatch_readiness()
  - build_followup_prompt()

#### 2. trading.py (新建)
- TradingAdapter 实现
- 交易特定逻辑：
  - Trading packet 验证 (ARTIFACT_REQUIRED_FIELDS, TRADABILITY_REQUIRED_FIELDS)
  - Trading summary 构建
  - Trading continuation plan
  - Trading auto-dispatch readiness
  - Trading followup prompt

### 重构后的 trading_roundtable.py (目标~500 行)

```python
# 只保留：
# 1. 导入核心模块和适配器
# 2. 初始化 adapter
# 3. process_trading_roundtable_callback() 主入口函数
# 4. 简单的 glue code

from core.phase_engine import PhaseEngine, PhaseState
from core.task_registry import TaskRegistry
from core.quality_gate import QualityGateEvaluator
from core.fanout_controller import FanOutController
from core.callback_router import CallbackRouter
from core.dispatch_planner import DispatchPlanner
from adapters.trading import TradingAdapter

# 初始化
engine = PhaseEngine()
registry = TaskRegistry()
gate_evaluator = QualityGateEvaluator()
fanout_controller = FanOutController()
callback_router = CallbackRouter()
dispatch_planner = DispatchPlanner()
adapter = TradingAdapter()

def process_trading_roundtable_callback(...):
    # 1. 标记 callback 接收
    # 2. 检查 batch 是否完成
    # 3. 分析 batch 结果
    # 4. 使用 adapter 验证 packet
    # 5. 使用 gate_evaluator 评估质量门
    # 6. 使用 adapter 构建 decision
    # 7. 使用 adapter 构建 continuation plan
    # 8. 评估 auto-dispatch readiness
    # 9. 持久化 decision/summary/dispatch plan
    # 10. 发送 completion ack
    # 11. 返回结果
```

## 依赖关系图

```
trading_roundtable.py
  ├── core/phase_engine.py (状态机)
  ├── core/task_registry.py (任务注册)
  ├── core/quality_gate.py (质量门)
  ├── core/fanout_controller.py (fan-out 控制)
  ├── core/callback_router.py (回调路由)
  ├── core/dispatch_planner.py (调度计划)
  └── adapters/
      ├── base.py (适配器基类)
      └── trading.py (交易适配器)

现有模块保持不动：
  - state_machine.py (底层状态存储)
  - batch_aggregator.py (batch 分析)
  - continuation_backends.py (backend 逻辑)
  - completion_ack_guard.py (ack 发送)
  - partial_continuation.py (partial closeout)
  - contracts.py (契约定义)
  - orchestrator.py (Decision 类)
```

## 交付标准

1. ✅ 核心模块可独立 import，无 trading 依赖
2. ✅ trading 适配器通过核心模块完成相同功能
3. ✅ 现有测试通过 (`pytest tests/orchestrator/test_trading_roundtable.py`)
4. ✅ 文档更新完成
5. ✅ commit & push

## 执行步骤

1. 创建 core/task_registry.py
2. 创建 core/quality_gate.py
3. 创建 core/fanout_controller.py
4. 创建 core/callback_router.py
5. 创建 core/dispatch_planner.py
6. 创建 adapters/base.py
7. 创建 adapters/trading.py
8. 重构 trading_roundtable.py (精简到~500 行)
9. 运行测试验证
10. 更新文档
11. Commit & push
