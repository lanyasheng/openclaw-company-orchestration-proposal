# Universal terminal callback contract（2026-03-22）

## 结论
这次把 tmux terminal callback 路径继续往全场景通用推进，但没有做空泛大重构。

新增的通用分层是：
1. **backend terminal receipt**
   - 后端终态、artifact 路径、dispatch readiness
   - 只描述 terminal truth，不直接代表业务 PASS/FAIL
2. **business callback payload**
   - 业务 closeout 真值
   - 不足以得出真实业务结论时，允许 blocked/degraded payload，但不能伪造 clean PASS
3. **adapter-scoped payload**
   - adapter 私有字段，例如：
     - `trading_roundtable.packet + trading_roundtable.roundtable`
     - `channel_roundtable.packet + channel_roundtable.roundtable`
4. **canonical callback envelope**
   - 统一挂到 `callback_envelope`
   - 里面放：
     - `backend_terminal_receipt`
     - `business_callback_payload`
     - `adapter_scoped_payload`
     - `orchestration_contract`
     - `source`

## 现在怎么接
- `orchestrator/tmux_terminal_receipts.py`
  - 不再只产出 trading-specific 顶层 payload
  - 最终都会补上 `callback_envelope`
- `scripts/orchestrator_callback_bridge.py`
  - 入口先做 `normalize_callback_payload(...)`
  - 所以 future producer 即使只写 envelope，也能继续喂给现有 adapter
- `scripts/orchestrator_dispatch_bridge.py`
  - tmux prompt/reference 改成写明 universal terminal callback contract
- `trading_roundtable.py` / `channel_roundtable.py`
  - dispatch plan 都显式声明 `callback_envelope_schema=canonical_callback_envelope.v1`

## 兼容策略
不是一次性把所有 adapter 改成 envelope-only。

当前策略是：
- producer 可以开始只写 canonical envelope；
- bridge 会把 envelope 兼容展开成现有 adapter 还能吃的 legacy 顶层结构；
- adapter 继续按自己的 scoped payload 做业务判断；
- future adapter 只需要补 scoped payload 解释层，不需要重写 tmux receipt / callback bridge。

## 边界
这次没有改写 business gate judgement，也没有让 backend report 直接等价于业务 PASS。

真正补上的，是一条可复用的通用 seam：
- backend terminal truth
- business closeout truth
- adapter private truth
- canonical envelope
