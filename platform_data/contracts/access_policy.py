"""准入白名单契约（057 DL-17a/071）——纯数据 + 纯函数，无 IO。

四类准入（交易员市场 / 交易员组合 / 券商市场 / 碎股常规路由）与整手倍数检查。
交易员意见（2026-10-23 约束矩阵 v2）：
- 交易员市场/组合准入：手动维护，未准入即 HARD 阻断；
- 券商市场准入：按市场维护，候选来自内部系统（后续开发），v0 人工确认；
- 碎股：白名单内市场允许常规路由，白名单外含碎股转人工；
- 整手：按 ticker 级 round lot（彭博 PX_ROUND_LOT_SIZE），不猜 100。

安全默认：未配置 = 全阻断（宁可转人工，不放行未准入账户）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

# 策略版本：结构/数据变更时升版（提交审计记录所用版本）
ACCESS_POLICY_VERSION = "access-policy-v1"


@dataclass(frozen=True)
class TraderMarketPolicy:
    """交易员 → 可交易市场（DL-03 折叠码）。未列入 = 无准入。"""

    traders: dict[str, frozenset[str]] = field(default_factory=dict)

    def allowed(self, trader: str, market_code: str) -> bool:
        markets = self.traders.get((trader or "").strip())
        return markets is not None and (market_code or "").strip().upper() in markets


@dataclass(frozen=True)
class TraderPortfolioPolicy:
    """交易员 → 可交易组合；'*' = 不限。未列入 = 无准入。"""

    traders: dict[str, frozenset[str]] = field(default_factory=dict)

    def allowed(self, trader: str, portfolio: str | None) -> bool:
        portfolios = self.traders.get((trader or "").strip())
        if portfolios is None:
            return False
        if "*" in portfolios:
            return True
        return (portfolio or "").strip() in portfolios


@dataclass(frozen=True)
class BrokerMarketPolicy:
    """市场 → 可路由券商（人工确认后落库）。未确认市场 = 空集 = 全阻断。"""

    markets: dict[str, frozenset[str]] = field(default_factory=dict)

    def allowed(self, broker: str, market_code: str) -> bool:
        brokers = self.markets.get((market_code or "").strip().upper())
        return brokers is not None and (broker or "").strip() in brokers


@dataclass(frozen=True)
class FractionalSharePolicy:
    """碎股常规路由白名单：市场 → 是否允许碎股直接路由。

    True = 该市场碎股可常规路由；False/缺失 = 含碎股转人工（manual_review）。
    """

    markets: dict[str, bool] = field(default_factory=dict)

    def allows_fractional(self, market_code: str) -> bool:
        return bool(self.markets.get((market_code or "").strip().upper(), False))


@dataclass(frozen=True)
class PolicyBundle:
    """四类策略打包（提交审计记录 version/loaded_at）。

    configured=False 表示策略文件未配置（部署初期）：准入检查整体跳过并告警
    （否则漏配一次即全系统停摆）；一旦配置，未准入（含未登记交易员）即阻断。
    """

    trader_markets: TraderMarketPolicy = field(default_factory=TraderMarketPolicy)
    trader_portfolios: TraderPortfolioPolicy = field(default_factory=TraderPortfolioPolicy)
    broker_markets: BrokerMarketPolicy = field(default_factory=BrokerMarketPolicy)
    fractional_shares: FractionalSharePolicy = field(default_factory=FractionalSharePolicy)
    version: str = ACCESS_POLICY_VERSION
    loaded_at: str = ""
    configured: bool = False


@dataclass(frozen=True)
class PolicyViolation:
    """准入违规（HARD 阻断；manual_review_required 时转人工）。"""

    code: str
    message: str
    manual_review_required: bool = False


# ── 检查纯函数 ────────────────────────────────────────────────────────────────


def check_trader_market(trader: str, market_code: str, bundle: PolicyBundle) -> list[PolicyViolation]:
    if bundle.trader_markets.allowed(trader, market_code):
        return []
    return [
        PolicyViolation(
            code="TRADER_MARKET_NOT_ALLOWED",
            message=f"Trader {trader!r} not allowed to trade market {market_code!r}",
        )
    ]


def check_trader_portfolio(trader: str, portfolio: str | None, bundle: PolicyBundle) -> list[PolicyViolation]:
    if bundle.trader_portfolios.allowed(trader, portfolio):
        return []
    return [
        PolicyViolation(
            code="TRADER_PORTFOLIO_NOT_ALLOWED",
            message=f"Trader {trader!r} not allowed to trade portfolio {portfolio!r}",
        )
    ]


def check_broker_market(broker: str, market_code: str, bundle: PolicyBundle) -> list[PolicyViolation]:
    if bundle.broker_markets.allowed(broker, market_code):
        return []
    return [
        PolicyViolation(
            code="BROKER_MARKET_NOT_ALLOWED",
            message=f"Broker {broker!r} not allowed to route in market {market_code!r}",
        )
    ]


def check_odd_lot(
    route_qty: int,
    round_lot: int | None,
    market_code: str,
    bundle: PolicyBundle,
    *,
    odd_lot_markets: frozenset[str] | set[str] = frozenset(),
) -> list[PolicyViolation]:
    """整手与碎股检查（交易员口径：ticker 级 round lot，不猜 100）。

    - 市场不在 odd_lot_markets → 不检查（该市场无整手概念）；
    - round_lot 不可得 → 转人工（manual_review_required，不猜 100）；
    - qty 非 round_lot 倍数 → 白名单内市场放行，白名单外转人工。
    """
    market = (market_code or "").strip().upper()
    if market not in {m.upper() for m in odd_lot_markets}:
        return []
    if round_lot is None or round_lot <= 0:
        return [
            PolicyViolation(
                code="ROUND_LOT_UNKNOWN",
                message=f"Round lot unavailable for {market}: manual review required",
                manual_review_required=True,
            )
        ]
    if route_qty <= 0 or route_qty % round_lot == 0:
        return []
    if bundle.fractional_shares.allows_fractional(market):
        return []
    return [
        PolicyViolation(
            code="ODD_LOT_MANUAL_REVIEW",
            message=(
                f"Odd lot qty={route_qty} (round_lot={round_lot}) in {market} "
                f"not in fractional routing whitelist: manual review required"
            ),
            manual_review_required=True,
        )
    ]
