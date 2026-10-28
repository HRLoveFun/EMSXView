"""市场时钟：按交易所本地时间判定盘前/交易中/午休/收市（057 DL-29 追加）。"""

from datetime import datetime, timezone

import pytest

import market_clock as mc
from platform_data.adapters import ExchangeSessionAdapter


@pytest.fixture()
def adapter():
    return ExchangeSessionAdapter()


def _utc(hour: int, minute: int = 0, *, day: int = 28) -> datetime:
    # 2026-10-28 是周三；day=31 为周六
    return datetime(2026, 10, day, hour, minute, tzinfo=timezone.utc)


class TestMarketClock:
    def test_us_pre_open_open_and_closed(self, adapter):
        # 12:30 UTC = 08:30 EDT（开盘前）；14:30 UTC = 10:30 EDT（盘中）；21:30 UTC = 17:30 EDT（收市）
        assert mc.market_clock(adapter, "US", _utc(12, 30))[0] == mc.STATUS_PRE
        assert mc.market_clock(adapter, "US", _utc(14, 30))[0] == mc.STATUS_OPEN
        assert mc.market_clock(adapter, "US", _utc(21, 30))[0] == mc.STATUS_CLOSED

    def test_jp_lunch_break(self, adapter):
        # 03:00 UTC = 12:00 JST（午休 11:30–12:30）
        status, local_time = mc.market_clock(adapter, "JP", _utc(3, 0))
        assert status == mc.STATUS_LUNCH
        assert local_time == "12:00"

    def test_hk_afternoon_session(self, adapter):
        assert mc.market_clock(adapter, "HK", _utc(6, 30))[0] == mc.STATUS_OPEN

    def test_weekend_is_closed(self, adapter):
        # 2026-10-31 是周六；04:00 UTC = 12:00 HKT
        assert mc.market_clock(adapter, "HK", _utc(4, 0, day=31))[0] == mc.STATUS_CLOSED

    def test_ch_maps_to_stock_connect_session(self, adapter):
        # 06:30 UTC = 14:30 CST：沪深港通（注册表 C1）盘中
        status, local_time = mc.market_clock(adapter, "CH", _utc(6, 30))
        assert status == mc.STATUS_OPEN
        assert local_time == "14:30"

    def test_eu_composite_uses_eurozone_approximation(self, adapter):
        # 10:00 UTC = 11:00 CET：欧元区盘中；EUR 复合码无国家归属，按 Xetra 时段近似
        assert mc.market_clock(adapter, "EU", _utc(10, 0))[0] == mc.STATUS_OPEN
        # 19:00 UTC = 20:00 CET：收市
        assert mc.market_clock(adapter, "EU", _utc(19, 0))[0] == mc.STATUS_CLOSED

    def test_unknown_market_and_bad_ticker(self, adapter):
        assert mc.market_clock(adapter, "ZZ", _utc(6, 0)) == (mc.STATUS_UNKNOWN, None)
        assert mc.market_clock(adapter, "", _utc(6, 0)) == (mc.STATUS_UNKNOWN, None)

    def test_exchange_code_from_ticker(self):
        assert mc.exchange_of("AAPL US Equity") == "US"
        assert mc.exchange_of("700 HK Equity") == "HK"
        assert mc.exchange_of("BAD") == ""
