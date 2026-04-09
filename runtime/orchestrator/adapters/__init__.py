#!/usr/bin/env python3
"""
adapters — Orchestrator Adapters

业务场景适配器模块，将通用编排内核与具体业务场景解耦。

可用适配器：
- TradingAdapter: 交易 roundtable 适配器
"""

from adapters.base import BaseAdapter, AdapterMetadata, ADAPTER_BASE_VERSION
from adapters.trading import TradingAdapter, TRADING_ADAPTER_VERSION

__all__ = [
    "BaseAdapter",
    "AdapterMetadata",
    "ADAPTER_BASE_VERSION",
    "TradingAdapter",
    "TRADING_ADAPTER_VERSION",
]
