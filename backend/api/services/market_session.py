"""交易所会话过滤（057 DL-31/218 补全）。

订阅范围 = 池成员 ∩（会话 open，或距开盘 ≤ ``lead_minutes``）。池由 MarketView
返回，core 是唯一订阅方；本模块只做纯判定（无 IO），供
``MarketDataEnrichmentService.add_mktdata_tickers`` 在注册额外标的前过滤。

市场码：ticker 后缀经 ``GY→GR`` / ``CH→C1`` 归一化到 ``SESSION_REGISTRY``；
未注册市场**不丢**（返回 True，避免静默缩范围），披露留给调用方计数。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from platform_data.adapters.session import ExchangeSessionAdapter

#: 池 ticker 后缀 → 会话注册表键（DL-31 明确的两处规范化）
EXCHANGE_ALIASES: dict[str, str] = {"GY": "GR", "CH": "C1"}

_ADAPTER = ExchangeSessionAdapter()


def exchange_for_ticker(ticker: str) -> str:
    """``SAP GY Equity`` → ``GR``；无法解析返回空串。"""
    parts = str(ticker or "").strip().split()
    if len(parts) < 2:
        return ""
    code = parts[-2].upper()
    return EXCHANGE_ALIASES.get(code, code)


def _hhmm_to_minutes(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    try:
        hour, minute = str(value).strip().split(":")[:2]
        return int(hour) * 60 + int(minute)
    except (TypeError, ValueError):
        return None


def is_session_open_or_soon(
    ticker_or_exchange: str,
    *,
    now_utc: Optional[datetime] = None,
    lead_minutes: int = 60,
) -> bool:
    """会话是否 open，或距开盘 ≤ ``lead_minutes``。

    - 未注册市场 → True（不静默缩范围）；
    - 周末 → False（注册表不含周末信息，按 Mon–Fri 处理）；
    - 时刻不可解析 → True（保守保留）。
    """
    text = str(ticker_or_exchange or "").strip()
    exchange = exchange_for_ticker(text) if " " in text else text.upper()
    session = _ADAPTER.get_session(exchange)
    if session is None:
        return True
    try:
        timezone_name = session.timezone
        local = (now_utc or datetime.now(timezone.utc)).astimezone(
            __import__("zoneinfo").ZoneInfo(timezone_name)
        )
    except Exception:  # 时区数据缺失：保守保留
        return True
    if local.weekday() >= 5:
        return False
    minutes = local.hour * 60 + local.minute
    open_min = _hhmm_to_minutes(session.market_open)
    close_min = _hhmm_to_minutes(session.market_close)
    if open_min is None or close_min is None:
        return True
    if open_min <= close_min:
        if open_min <= minutes < close_min:
            return True
    else:  # 跨午夜会话（极少见）
        if minutes >= open_min or minutes < close_min:
            return True
    return 0 <= (open_min - minutes) <= max(0, int(lead_minutes))
