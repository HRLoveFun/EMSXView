"""057 DL-17a/071：准入白名单测试。

覆盖：
1. 契约检查纯函数（交易员市场/组合、券商市场、碎股白名单 × 整手倍数）；
2. 服务加载（JSON 缺失全阻断、正常解析、EUR→EU 归一、selection 过滤）；
3. 每日确认四象限与最近更新日期；
4. 既有 market_broker_mapping 单一数据源复用（不新建表）。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

REPO_ROOT = API_ROOT.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from platform_data.contracts import (  # noqa: E402
    ACCESS_POLICY_VERSION,
    BrokerMarketPolicy,
    FractionalSharePolicy,
    PolicyBundle,
    TraderMarketPolicy,
    TraderPortfolioPolicy,
    check_broker_market,
    check_odd_lot,
    check_trader_market,
    check_trader_portfolio,
)
from services import access_policy_service  # noqa: E402


def _bundle(**overrides) -> PolicyBundle:
    base = dict(
        trader_markets=TraderMarketPolicy(traders={"TRD_1": frozenset({"US", "JP"})}),
        trader_portfolios=TraderPortfolioPolicy(traders={"TRD_1": frozenset({"*"})}),
        broker_markets=BrokerMarketPolicy(markets={"US": frozenset({"EQ-AAA", "EQ-BBB"})}),
        fractional_shares=FractionalSharePolicy(markets={"US": True}),
        version=ACCESS_POLICY_VERSION,
        loaded_at="2026-10-23T00:00:00",
    )
    base.update(overrides)
    return PolicyBundle(**base)


class TestPolicyChecks:
    """① 契约检查纯函数。"""

    def test_trader_market(self):
        bundle = _bundle()
        assert check_trader_market("TRD_1", "US", bundle) == []
        assert check_trader_market("TRD_1", "HK", bundle)[0].code == "TRADER_MARKET_NOT_ALLOWED"
        # 未登记交易员 = 无准入（安全默认）
        assert check_trader_market("TRD_X", "US", bundle)[0].code == "TRADER_MARKET_NOT_ALLOWED"

    def test_trader_portfolio(self):
        bundle = _bundle()
        assert check_trader_portfolio("TRD_1", "PF_A", bundle) == []  # '*' 不限
        restricted = _bundle(trader_portfolios=TraderPortfolioPolicy(traders={"TRD_1": frozenset({"PF_A"})}))
        assert check_trader_portfolio("TRD_1", "PF_A", restricted) == []
        assert check_trader_portfolio("TRD_1", "PF_B", restricted)[0].code == "TRADER_PORTFOLIO_NOT_ALLOWED"

    def test_broker_market(self):
        bundle = _bundle()
        assert check_broker_market("EQ-AAA", "US", bundle) == []
        assert check_broker_market("EQ-ZZZ", "US", bundle)[0].code == "BROKER_MARKET_NOT_ALLOWED"
        # 未确认市场 = 全阻断（空集）
        assert check_broker_market("EQ-AAA", "HK", bundle)[0].code == "BROKER_MARKET_NOT_ALLOWED"

    def test_odd_lot_market_scoping(self):
        bundle = _bundle()
        markets = frozenset({"JP", "US"})
        # 市场不在 scope → 不检查
        assert check_odd_lot(99, 100, "HK", bundle, odd_lot_markets=markets) == []
        # round lot 不可得 → 转人工（不猜 100）
        result = check_odd_lot(99, None, "US", bundle, odd_lot_markets=markets)
        assert result[0].code == "ROUND_LOT_UNKNOWN"
        assert result[0].manual_review_required is True

    def test_fractional_whitelist(self):
        markets = frozenset({"JP", "US"})
        # US 在白名单 → 碎股放行
        assert check_odd_lot(99, 100, "US", _bundle(), odd_lot_markets=markets) == []
        # JP 不在白名单 → 转人工
        result = check_odd_lot(99, 100, "JP", _bundle(), odd_lot_markets=markets)
        assert result[0].code == "ODD_LOT_MANUAL_REVIEW"
        # 整手倍数 → 无违规
        assert check_odd_lot(100, 100, "JP", _bundle(), odd_lot_markets=markets) == []


class TestServiceLoading:
    """② 服务加载。"""

    def test_missing_policy_file_skips_checks(self, monkeypatch, tmp_path):
        """未配置策略 → configured=False：入口层跳过（避免漏配停摆），契约层仍严格。"""
        monkeypatch.setenv(access_policy_service.ACCESS_POLICY_FILE_ENV, str(tmp_path / "nope.json"))

        bundle = access_policy_service.load_policy_bundle()

        assert bundle.configured is False
        assert bundle.trader_markets.traders == {}
        # 契约检查本身仍严格（空名单 = 无准入）
        assert check_trader_market("TRD_1", "US", bundle)
        # evaluate_access 在未配置时跳过
        from types import SimpleNamespace

        assert access_policy_service.evaluate_access(
            SimpleNamespace(exchange="US", trader="TRD_1", portfolio=None), {"broker": "EQ-AAA"}, bundle
        ) == []

    def test_policy_file_parsed(self, monkeypatch, tmp_path):
        policy = {
            "traders": {
                "TRD_1": {"markets": ["us", "JP"], "portfolios": ["*"]},
                "TRD_2": {"markets": ["US"], "portfolios": ["PF_A"]},
            },
            "fractional_share_markets": ["us"],
        }
        path = tmp_path / "policy.json"
        path.write_text(json.dumps(policy), encoding="utf-8")
        monkeypatch.setenv(access_policy_service.ACCESS_POLICY_FILE_ENV, str(path))

        bundle = access_policy_service.load_policy_bundle()

        assert bundle.configured is True
        assert bundle.trader_markets.traders["TRD_1"] == frozenset({"US", "JP"})  # 大写归一
        assert bundle.fractional_shares.allows_fractional("US") is True
        assert bundle.fractional_shares.allows_fractional("JP") is False

    def test_evaluate_access_configured_enforces(self, monkeypatch, tmp_path):
        """配置策略后准入严格：交易员不在名单 → TRADER_MARKET_NOT_ALLOWED。"""
        policy = {"traders": {"TRD_1": {"markets": ["US"], "portfolios": ["*"]}}}
        path = tmp_path / "policy.json"
        path.write_text(json.dumps(policy), encoding="utf-8")
        monkeypatch.setenv(access_policy_service.ACCESS_POLICY_FILE_ENV, str(path))
        from types import SimpleNamespace

        violations = access_policy_service.evaluate_access(
            SimpleNamespace(exchange="US", trader="TRD_2", portfolio=None), {"broker": "EQ-AAA"}
        )

        codes = {v.code for v in violations}
        assert "TRADER_MARKET_NOT_ALLOWED" in codes

    def test_broker_policy_from_mapping_file(self, tmp_path):
        state = {
            "updatedAt": "2026-10-23T09:30:00",
            "rosters": {"US": ["EQ-AAA", "EQ-BBB"]},
            "selection": {
                "US": {"EQ-AAA": True, "EQ-BBB": False},
                "EUR": {"EQ-CCC": True},
            },
        }
        path = tmp_path / "market_broker_mapping.json"
        path.write_text(json.dumps(state), encoding="utf-8")

        policy = access_policy_service.load_broker_market_policy(str(path))

        assert policy.allowed("EQ-AAA", "US") is True
        assert policy.allowed("EQ-BBB", "US") is False  # selection false
        assert policy.allowed("EQ-CCC", "EU") is True  # EUR → EU 归一
        assert access_policy_service.last_mapping_update_date(str(path)) == "2026-10-23"

    def test_broker_policy_missing_file_blocks(self, tmp_path):
        policy = access_policy_service.load_broker_market_policy(str(tmp_path / "nope.json"))
        assert policy.markets == {}
        assert policy.allowed("EQ-AAA", "US") is False


class TestDailyConfirmation:
    """③ 每日确认四象限。"""

    def test_before_8am_never_needs(self):
        assert access_policy_service.needs_daily_confirmation(
            datetime(2026, 10, 23, 7, 59), last_confirmed_date=None
        ) is False

    def test_after_8am_unconfirmed_needs(self):
        assert access_policy_service.needs_daily_confirmation(
            datetime(2026, 10, 23, 8, 0), last_confirmed_date="2026-10-22"
        ) is True

    def test_after_8am_confirmed_today_ok(self):
        assert access_policy_service.needs_daily_confirmation(
            datetime(2026, 10, 23, 10, 0), last_confirmed_date="2026-10-23"
        ) is False

    def test_missing_last_date_counts_as_unconfirmed(self):
        assert access_policy_service.needs_daily_confirmation(
            datetime(2026, 10, 23, 9, 0), last_confirmed_date=None
        ) is True
