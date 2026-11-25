"""057 DL-31/218：会话过滤与订阅截断测试。"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
REPO_ROOT = API_ROOT.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.market_session import (  # noqa: E402
    exchange_for_ticker,
    is_session_open_or_soon,
)


def _utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def test_exchange_alias_normalization() -> None:
    assert exchange_for_ticker("SAP GY Equity") == "GR"
    assert exchange_for_ticker("601398 CH Equity") == "C1"
    assert exchange_for_ticker("AAPL US Equity") == "US"
    assert exchange_for_ticker("BHP AU Equity") == "AU"
    assert exchange_for_ticker("") == ""


def test_us_session_open_soon_and_closed() -> None:
    # 2026-11-25 周三；纽约 11 月为 EST (UTC-5)
    assert is_session_open_or_soon("AAPL US Equity", now_utc=_utc(2026, 11, 25, 14, 0))
    assert is_session_open_or_soon("AAPL US Equity", now_utc=_utc(2026, 11, 25, 15, 0))
    assert not is_session_open_or_soon("AAPL US Equity", now_utc=_utc(2026, 11, 25, 13, 0))
    assert not is_session_open_or_soon("AAPL US Equity", now_utc=_utc(2026, 11, 25, 22, 0))


def test_jp_session_open_soon_and_closed() -> None:
    # 东京 11 月为 JST (UTC+9)：09:00 JST = 00:00 UTC
    assert is_session_open_or_soon("7203 JP Equity", now_utc=_utc(2026, 11, 25, 0, 0))
    assert is_session_open_or_soon("7203 JP Equity", now_utc=_utc(2026, 11, 24, 23, 0))
    assert not is_session_open_or_soon("7203 JP Equity", now_utc=_utc(2026, 11, 24, 22, 0))


def test_weekend_and_unknown_market() -> None:
    assert not is_session_open_or_soon("AAPL US Equity", now_utc=_utc(2026, 11, 28, 15, 0))
    assert is_session_open_or_soon("ZZZ ZZ Equity", now_utc=_utc(2026, 11, 28, 15, 0))


def test_alias_markets_use_session_registry() -> None:
    # SAP GY → GR (Xetra 09:00–17:30 CET；11 月 CET = UTC+1)
    assert is_session_open_or_soon("SAP GY Equity", now_utc=_utc(2026, 11, 25, 8, 0))
    # 601398 CH → C1 (上交所 09:30–15:00 CST；UTC+8)
    assert is_session_open_or_soon("601398 CH Equity", now_utc=_utc(2026, 11, 25, 1, 30))
