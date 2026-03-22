# Roundtable Ack Guard Audit — 2026-03-21

## Scope
- trading roundtable completion path
- channel roundtable completion path
- callback bridge ack-required contract

## What changed
1. Added `completion_ack_guard.py`
   - normalizes completion ack message
   - writes receipt markdown + audit json
   - downgrades to `fallback_recorded` when delivery is unavailable/fails
2. `trading_roundtable.py`
   - completion processed => mandatory `ack_result`
3. `channel_roundtable.py`
   - completion processed => mandatory `ack_result`
4. `scripts/orchestrator_callback_bridge.py`
   - enforces ack-required contract
   - synthesizes fallback receipt if adapter forgets to return ack metadata

## Receipt contract
Every completion should now leave:
- `ack_status`
- `delivery_status`
- `receipt_path`
- `audit_file`
- `message_sent`

Receipt body must carry:
- summary path
- decision path
- dispatch plan path
- next step

## Fallback rule
When live delivery does not happen (`missing_requester_channel_id`, disabled delivery, openclaw send failure, adapter omission), we still persist a receipt and mark:
- `ack_status = fallback_recorded`

So completion is no longer silently internal-only.
