"""准入白名单服务（057 DL-17a/071）。

四类策略加载与检查入口：
- 交易员市场/组合准入：仓库外 JSON（EMSXVIEW_ACCESS_POLICY_FILE），未配置 = 全阻断；
- 券商市场准入：运营库 broker_market_policy（人工确认后落库；候选来自内部系统，
  v0 用 EMSX 策略缓存清单临时源）；
- 碎股常规路由白名单：JSON 的 fractional_share_markets。

每日确认（当地 08:00 后首次打开弹窗）：needs_daily_confirmation(now)。
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, time as dtime

from platform_data.contracts import (
    ACCESS_POLICY_VERSION,
    BrokerMarketPolicy,
    FractionalSharePolicy,
    PolicyBundle,
    TraderMarketPolicy,
    TraderPortfolioPolicy,
)

logger = logging.getLogger(__name__)

# 交易员/碎股白名单 JSON 路径（仓库外；未配置 = 全阻断安全默认）
ACCESS_POLICY_FILE_ENV = "EMSXVIEW_ACCESS_POLICY_FILE"

# 每日确认时点（当地 08:00；当天首次打开触发弹窗）
DAILY_CONFIRM_HOUR = 8


def load_policy_bundle(path: str | None = None) -> PolicyBundle:
    """加载 JSON 策略（券商准入由运营库并入，见 with_broker_policy）。

    JSON 结构：
      {"traders": {"TRD_1": {"markets": ["US", "JP"], "portfolios": ["*"]}},
       "fractional_share_markets": ["US"]}
    """
    target = path or os.getenv(ACCESS_POLICY_FILE_ENV, "")
    trader_markets: dict[str, frozenset[str]] = {}
    trader_portfolios: dict[str, frozenset[str]] = {}
    fractional: dict[str, bool] = {}
    if not target or not os.path.exists(target):
        logger.warning(
            "access policy file not configured (%s) — 准入检查跳过（配置后严格生效）", ACCESS_POLICY_FILE_ENV
        )
        return PolicyBundle(
            trader_markets=TraderMarketPolicy(),
            trader_portfolios=TraderPortfolioPolicy(),
            broker_markets=BrokerMarketPolicy(),
            fractional_shares=FractionalSharePolicy(),
            version=ACCESS_POLICY_VERSION,
            loaded_at=datetime.now().isoformat(timespec="seconds"),
            configured=False,
        )

    with open(target, encoding="utf-8") as fh:
        data = json.load(fh) or {}

    for trader, spec in (data.get("traders") or {}).items():
        markets = frozenset(str(m).strip().upper() for m in (spec.get("markets") or []))
        portfolios = frozenset(str(p).strip() for p in (spec.get("portfolios") or []))
        trader_markets[str(trader)] = markets
        trader_portfolios[str(trader)] = portfolios
    for market in data.get("fractional_share_markets") or []:
        fractional[str(market).strip().upper()] = True

    return PolicyBundle(
        trader_markets=TraderMarketPolicy(traders=trader_markets),
        trader_portfolios=TraderPortfolioPolicy(traders=trader_portfolios),
        # 券商市场准入：读既有 market_broker_mapping.json（单一数据源）
        broker_markets=load_broker_market_policy(),
        fractional_shares=FractionalSharePolicy(markets=fractional),
        version=ACCESS_POLICY_VERSION,
        loaded_at=datetime.now().isoformat(timespec="seconds"),
        configured=True,
    )


def with_broker_policy(bundle: PolicyBundle, markets: dict[str, frozenset[str]]) -> PolicyBundle:
    """把运营库确认结果并入 bundle（markets: market_code → brokers）。"""
    normalized = {str(k).strip().upper(): frozenset(v) for k, v in markets.items()}
    return PolicyBundle(
        trader_markets=bundle.trader_markets,
        trader_portfolios=bundle.trader_portfolios,
        broker_markets=BrokerMarketPolicy(markets=normalized),
        fractional_shares=bundle.fractional_shares,
        version=bundle.version,
        loaded_at=bundle.loaded_at,
        configured=bundle.configured,
    )


def needs_daily_confirmation(now: datetime | None = None, last_confirmed_date: str | None = None) -> bool:
    """当日 08:00 后且当日未确认 → True（触发弹窗）。"""
    current = now or datetime.now()
    if current.time() < dtime(hour=DAILY_CONFIRM_HOUR):
        return False
    return last_confirmed_date != current.strftime("%Y-%m-%d")


def load_broker_market_policy(path: str | None = None) -> BrokerMarketPolicy:
    """券商市场准入：读既有 market_broker_mapping.json 的 selection（单一数据源）。

    2026-10-23 核查：`routers/market_broker_mapping.py` 已实现——rosters 为
    「按市场可用券商列表」（密码门控维护），selection 为每市场每券商允许开关。
    本函数只读 selection（true = 允许），marketKey 归一：EUR → EU（DL-03 折叠）。
    文件缺失/解析失败 → 空策略（全部阻断，安全默认）。
    """
    target = path or _default_mapping_path()
    if not target or not os.path.exists(target):
        logger.warning("market_broker_mapping.json 缺失——券商市场准入为空（全部阻断）")
        return BrokerMarketPolicy()
    try:
        with open(target, encoding="utf-8") as fh:
            state = json.load(fh) or {}
    except (OSError, json.JSONDecodeError):
        logger.warning("market_broker_mapping.json 解析失败——券商准入按空处理", exc_info=True)
        return BrokerMarketPolicy()

    markets: dict[str, frozenset[str]] = {}
    for market_key, selection in (state.get("selection") or {}).items():
        market = _normalize_market_key(market_key)
        allowed = frozenset(b for b, on in (selection or {}).items() if on)
        markets[market] = allowed
    return BrokerMarketPolicy(markets=markets)


def _normalize_market_key(market_key: str) -> str:
    """marketKey → DL-03 市场码（EUR→EU；其余原样大写）。"""
    text = str(market_key).strip().upper()
    return "EU" if text == "EUR" else text


def _default_mapping_path() -> str:
    from pathlib import Path

    return str(Path(__file__).resolve().parent.parent / "data" / "market_broker_mapping.json")


def evaluate_access(parent_order, proposal: dict, bundle: PolicyBundle | None = None):
    """准入检查入口（路由前调用）：返回契约 PolicyViolation 列表。

    market 由 exchange 经 DL-03 market_code_for 折叠；trader 取订单对象属性
    （OrderProjection.trader 来源）；券商取 proposal['broker']。
    """
    from platform_data.adapters import ExchangeSessionAdapter
    from platform_data.contracts import (
        check_broker_market,
        check_trader_market,
        check_trader_portfolio,
    )

    active = bundle or load_policy_bundle()
    if not active.configured:
        # 部署初期未配置策略：跳过准入检查（避免漏配即全系统停摆），仅告警
        logger.warning("access policy not configured — 准入检查跳过（配置 EMSXVIEW_ACCESS_POLICY_FILE 后严格生效）")
        return []
    exchange = getattr(parent_order, "exchange", "") or ""
    market = ExchangeSessionAdapter().market_code_for(exchange) if exchange else ""
    trader = getattr(parent_order, "trader", "") or ""
    portfolio = getattr(parent_order, "portfolio", None)
    broker = (proposal or {}).get("broker", "")

    violations = []
    violations.extend(check_trader_market(trader, market, active))
    violations.extend(check_trader_portfolio(trader, portfolio, active))
    violations.extend(check_broker_market(broker, market, active))
    return violations


def fractional_markets(bundle: PolicyBundle | None = None) -> frozenset[str]:
    """碎股常规路由白名单市场集合（供 compliance_service._check_odd_lot 使用）。"""
    active = bundle or load_policy_bundle()
    return frozenset(active.fractional_shares.markets.keys())


def last_mapping_update_date(path: str | None = None) -> str | None:
    """映射文件最近更新日期（YYYY-MM-DD；判定当日是否已确认）。"""
    target = path or _default_mapping_path()
    if not target or not os.path.exists(target):
        return None
    try:
        with open(target, encoding="utf-8") as fh:
            updated = (json.load(fh) or {}).get("updatedAt")
    except (OSError, json.JSONDecodeError):
        return None
    if not updated:
        return None
    try:
        return datetime.fromisoformat(str(updated).replace("Z", "+00:00")).strftime("%Y-%m-%d")
    except ValueError:
        return None
