"""057 DL-03 — 交易所会话注册表与查询函数测试。

锁死行为（tasks.md DL-03 检验方法）：
1. 覆盖 BDIB 白名单全部市场（26 个，无遗漏无多余）；
2. 时区与 exchange_tz 双源一致；
3. 管道 closing_auction_times 样本核对（US/JP/HK + ADJUST 集合）；
4. 会话相对时间（含 DST 切换日）；
5. 半日市静态覆盖；
6. 时段桶（5 桶 + JP lunch，end 独占语义）；
7. 市场码折叠；
8. 未知交易所不抛错。
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

REPO_ROOT = API_ROOT.parents[1]  # backend/api → backend → 仓库根（worktree 根）
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from platform_data.adapters import ExchangeSessionAdapter
from platform_data.contracts import (
    EARLY_CLOSE_AUCTION_EXCHANGES,
    HALF_DAY_CLOSE_OVERRIDES,
    SESSION_REGISTRY,
    SESSION_REGISTRY_VERSION,
    TIME_BUCKET_MARKETS,
)

_adapter = ExchangeSessionAdapter()


class TestCoverage:
    """用例 1/2：白名单覆盖与时区双源一致。"""

    def test_registry_covers_bdib_whitelist_exactly(self):
        from data_access.config import Config

        assert set(SESSION_REGISTRY) == set(Config.BDIB_EXCHANGE)
        assert len(SESSION_REGISTRY) == 26  # 含 C1（2026-08-03 沪港通入白名单）

    def test_timezone_matches_exchange_tz(self):
        from data_access.common.exchange_tz import EXCHANGE_TIMEZONE

        for code, session in SESSION_REGISTRY.items():
            assert EXCHANGE_TIMEZONE.get(code) == session.timezone, code


class TestPipelineSamples:
    """用例 3：管道 §5.5 样本与 ADJUST 集合镜像。"""

    def test_closing_auction_samples(self):
        assert SESSION_REGISTRY["US"].closing_auction == "16:00"
        assert SESSION_REGISTRY["JP"].closing_auction == "15:30"
        assert SESSION_REGISTRY["HK"].closing_auction == "16:00"

    def test_early_close_auction_adjust_set(self):
        assert EARLY_CLOSE_AUCTION_EXCHANGES == {"JP", "PW", "SS", "BZ", "CN", "MM", "US"}
        # 白名单内的 ADJUST 成员必须置位；非成员不得置位
        for code, session in SESSION_REGISTRY.items():
            expected = code in EARLY_CLOSE_AUCTION_EXCHANGES
            assert session.early_close_auction is expected, code

    def test_session_bounds_for_us(self):
        assert _adapter.session_bounds_for("US", "20261015") == ("09:30", "16:00")


class TestSessionRelativeMinutes:
    """用例 4：会话相对时间（挂钟差，DST 切换日不抛错）。"""

    def test_us_relative_minutes(self):
        assert _adapter.session_relative_minutes("US", datetime(2026, 10, 15, 9, 30)) == 0
        assert _adapter.session_relative_minutes("US", datetime(2026, 10, 15, 13, 0)) == 210

    def test_jp_lunch_included_in_wall_clock(self):
        # 午休计入挂钟差：JP 开盘 09:00，12:30 → 210 分钟
        assert _adapter.session_relative_minutes("JP", datetime(2026, 10, 15, 12, 30)) == 210

    def test_dst_switch_days_do_not_raise(self):
        # 2026-03-08 US 春切、2026-03-29 EU/LN 春切、2026-04-05 AU 秋切
        assert _adapter.session_relative_minutes("US", datetime(2026, 3, 8, 9, 30)) == 0
        assert _adapter.session_relative_minutes("LN", datetime(2026, 3, 29, 8, 0)) == 0
        assert _adapter.session_relative_minutes("AU", datetime(2026, 4, 5, 10, 0)) == 0
        assert _adapter.session_relative_minutes("GR", datetime(2026, 10, 25, 9, 0)) == 0

    def test_unknown_exchange_returns_none(self):
        assert _adapter.session_relative_minutes("ZZ", datetime(2026, 10, 15, 10, 0)) is None
        assert _adapter.get_session("ZZ") is None


class TestHalfDayOverrides:
    """用例 5：半日市静态覆盖。"""

    def test_override_hit_returns_early_close(self):
        assert _adapter.closing_time_for("US", "2026-11-27") == "13:00"
        assert _adapter.session_bounds_for("HK", "20261224") == ("09:30", "12:00")

    def test_miss_returns_regular_close(self):
        assert _adapter.closing_time_for("US", "2026-11-26") == "16:00"

    def test_date_formats_normalized(self):
        # 'YYYYMMDD' 与 'YYYY-MM-DD' 等价
        assert _adapter.closing_time_for("LN", "20261224") == "13:30"
        assert _adapter.closing_time_for("LN", "2026-12-24") == "13:30"

    def test_overrides_cover_current_and_next_year(self):
        years = {int(key[1][:4]) for key in HALF_DAY_CLOSE_OVERRIDES}
        assert {2026, 2027} <= years


class TestTimeBuckets:
    """用例 6：时段桶（5 桶派生 + JP lunch_break）。"""

    def test_us_buckets(self):
        assert _adapter.time_bucket_for("US", datetime(2026, 10, 15, 9, 45)) == "open_30m"
        assert _adapter.time_bucket_for("US", datetime(2026, 10, 15, 10, 0)) == "morning"
        assert _adapter.time_bucket_for("US", datetime(2026, 10, 15, 12, 0)) == "midday"
        assert _adapter.time_bucket_for("US", datetime(2026, 10, 15, 14, 0)) == "afternoon"
        assert _adapter.time_bucket_for("US", datetime(2026, 10, 15, 15, 45)) == "close_30m"

    def test_jp_lunch_break_bucket(self):
        assert _adapter.time_bucket_for("JP", datetime(2026, 10, 15, 11, 45)) == "lunch_break"
        assert _adapter.time_bucket_for("JP", datetime(2026, 10, 15, 12, 30)) == "afternoon"
        assert _adapter.time_bucket_for("JP", datetime(2026, 10, 15, 9, 15)) == "open_30m"

    def test_pre_open_returns_none(self):
        assert _adapter.time_bucket_for("US", datetime(2026, 10, 15, 8, 0)) is None

    def test_non_enabled_market_returns_none(self):
        assert TIME_BUCKET_MARKETS == ("US", "AU", "LN", "EU", "JP")
        assert _adapter.time_bucket_for("HK", datetime(2026, 10, 15, 10, 0)) is None

    def test_eu_folded_markets_use_own_session(self):
        # GA 折叠为 EU（启用市场），桶按 GA 自身会话（10:00 开盘）派生
        assert _adapter.time_bucket_for("GA", datetime(2026, 10, 15, 10, 15)) == "open_30m"
        # 纯折叠码 EUR 无会话定义 → None（EU 泛化条目待 DL-06）
        assert _adapter.time_bucket_for("EUR", datetime(2026, 10, 15, 10, 15)) is None


class TestMarketCodeFolding:
    """用例 7：市场码折叠（管道 derive_market_code 镜像）。"""

    def test_folding_rules(self):
        assert _adapter.market_code_for("MUMBAI") == "IN"
        assert _adapter.market_code_for("NSE") == "IN"
        assert _adapter.market_code_for("EUR") == "EU"
        assert _adapter.market_code_for("GR") == "EU"
        assert _adapter.market_code_for("ID") == "LN"

    def test_identity_and_unknown(self):
        assert _adapter.market_code_for("US") == "US"
        assert _adapter.market_code_for("hk") == "HK"
        assert _adapter.market_code_for("ZZ") == "ZZ"


def test_registry_version_present():
    """版本常量存在（更新机制升版锚点）。"""
    assert SESSION_REGISTRY_VERSION == "exch-session-v1"
