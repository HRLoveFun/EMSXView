"""Pre-trade compliance checks for route / modify-route operations.

Three hard-block rules are evaluated in USD-equivalent notional terms:

  1. NOTIONAL_TOO_SMALL — $Value < USD_NOTIONAL_MIN (default 10,000)
  2. NOTIONAL_TOO_LARGE — $Value > USD_NOTIONAL_MAX (default 49,000,000)
  3. JP_ODD_LOT       — JP-listed instrument and qty not multiple of round-lot

A fourth conservative rule is applied when the notional cannot be estimated
(MARKET order with no last price): NOTIONAL_UNKNOWN — also a hard block, in
keeping with the user-aligned "USD hard-block" stance.

All thresholds come from ``config.settings``.
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

from config import settings
from schemas import Violation

logger = logging.getLogger(__name__)


# EMSX exchange code prefixes / values commonly associated with Japan-listed
# instruments. Lower-cased on comparison.
_JP_EXCHANGE_CODES: frozenset[str] = frozenset({"JP", "JT", "JF", "JU", "JE", "JQ"})

# Order types treated as "needs limit price" for $Value computation.
_LIMIT_ORDER_TYPES: frozenset[str] = frozenset({"LMT", "LIMIT", "STP_LMT", "STOP_LIMIT"})

_DEFAULT_JP_ROUND_LOT = 100


def _is_jp_market(exchange: Optional[str], currency: Optional[str]) -> bool:
    if currency and currency.strip().upper() == "JPY":
        return True
    if exchange:
        token = exchange.strip().upper()
        if token in _JP_EXCHANGE_CODES:
            return True
        # Some upstream feeds use "JP Equity" / "Tokyo" — match a leading token.
        head = token.split()[0] if token else ""
        if head in _JP_EXCHANGE_CODES:
            return True
    return False


def _normalize_order_type(order_type: Optional[str]) -> str:
    if not order_type:
        return ""
    return order_type.strip().upper()


def _resolve_effective_price(
    order_type: str,
    limit_price: Optional[float],
    stop_price: Optional[float],
    fallback_last_price: Optional[float],
) -> Optional[float]:
    """Return the price used to estimate $Value, or None when unknown.

    Priority: limit_price (when order type uses limit) > stop_price (when stop
    type) > fallback_last_price.
    """
    ot = _normalize_order_type(order_type)
    if ot in _LIMIT_ORDER_TYPES and limit_price is not None and limit_price > 0:
        return float(limit_price)
    if ot in {"STP", "STOP"} and stop_price is not None and stop_price > 0:
        return float(stop_price)
    if fallback_last_price is not None and fallback_last_price > 0:
        return float(fallback_last_price)
    return None


def _to_usd(price: float, qty: int, fx_rate: Optional[float], currency: Optional[str]) -> float:
    """Convert ``price * qty`` from local currency to USD.

    Convention used by upstream Bloomberg refdata in this codebase: ``fxRate``
    is the multiplier that converts a local-currency notional to USD. When
    currency is already USD or no fx is supplied, the multiplier is 1.0.
    """
    notional_local = float(price) * int(qty)
    ccy = (currency or "").strip().upper()
    if ccy in ("", "USD"):
        return notional_local
    if fx_rate is not None and fx_rate > 0:
        return notional_local * float(fx_rate)
    # Currency is non-USD but fx unknown — treat as unknown by returning a
    # sentinel; callers handle this via the NOTIONAL_UNKNOWN rule.
    return float("nan")


def _check_notional(
    *,
    order_type: str,
    qty: int,
    limit_price: Optional[float],
    stop_price: Optional[float],
    last_price: Optional[float],
    fx_rate: Optional[float],
    currency: Optional[str],
) -> List[Violation]:
    if qty <= 0:
        return []
    eff_price = _resolve_effective_price(order_type, limit_price, stop_price, last_price)
    if eff_price is None:
        return [
            Violation(
                code="NOTIONAL_UNKNOWN",
                message=(
                    "Cannot estimate USD notional: order has no limit price and "
                    "no last price is available."
                ),
                details={"orderType": order_type, "qty": qty, "currency": currency},
            )
        ]
    notional_usd = _to_usd(eff_price, qty, fx_rate, currency)
    if notional_usd != notional_usd:  # NaN sentinel from missing fx
        return [
            Violation(
                code="NOTIONAL_UNKNOWN",
                message=(
                    f"Cannot estimate USD notional: currency '{currency}' "
                    "has no FX rate available."
                ),
                details={
                    "orderType": order_type,
                    "qty": qty,
                    "price": eff_price,
                    "currency": currency,
                },
            )
        ]

    violations: List[Violation] = []
    min_thr = settings.USD_NOTIONAL_MIN
    max_thr = settings.USD_NOTIONAL_MAX
    if notional_usd < min_thr:
        violations.append(
            Violation(
                code="NOTIONAL_TOO_SMALL",
                message=(
                    f"USD notional {notional_usd:,.2f} is below the minimum "
                    f"{min_thr:,.0f}."
                ),
                details={
                    "notionalUsd": round(notional_usd, 2),
                    "thresholdUsd": min_thr,
                    "price": eff_price,
                    "qty": qty,
                    "currency": currency,
                    "fxRate": fx_rate,
                },
            )
        )
    elif notional_usd > max_thr:
        violations.append(
            Violation(
                code="NOTIONAL_TOO_LARGE",
                message=(
                    f"USD notional {notional_usd:,.2f} exceeds the maximum "
                    f"{max_thr:,.0f}."
                ),
                details={
                    "notionalUsd": round(notional_usd, 2),
                    "thresholdUsd": max_thr,
                    "price": eff_price,
                    "qty": qty,
                    "currency": currency,
                    "fxRate": fx_rate,
                },
            )
        )
    return violations


def _check_jp_odd_lot(
    *,
    qty: int,
    exchange: Optional[str],
    currency: Optional[str],
    round_lot_size: Optional[int],
) -> List[Violation]:
    if qty <= 0:
        return []
    if not _is_jp_market(exchange, currency):
        return []
    lot = int(round_lot_size) if round_lot_size and round_lot_size > 0 else _DEFAULT_JP_ROUND_LOT
    if qty % lot != 0:
        return [
            Violation(
                code="JP_ODD_LOT",
                message=(
                    f"Quantity {qty} is not a multiple of the JP round-lot "
                    f"size {lot}."
                ),
                details={"qty": qty, "lotSize": lot, "exchange": exchange},
            )
        ]
    return []


def check_route(
    parent_order: Any,
    *,
    route_qty: int,
    limit_price: Optional[float],
    stop_price: Optional[float],
    order_type: Optional[str],
) -> List[Violation]:
    """Run pre-trade compliance for a new RouteEx request.

    ``parent_order`` may be a Pydantic ``Order`` model or a plain object that
    exposes the relevant attributes (``currency``, ``exchange``, ``fxRate``,
    ``lastPrice``, ``roundLotSize``).
    """
    if parent_order is None:
        return []
    currency = getattr(parent_order, "currency", None)
    exchange = getattr(parent_order, "exchange", None)
    fx_rate = getattr(parent_order, "fxRate", None)
    last_price = getattr(parent_order, "lastPrice", None)
    round_lot_size = getattr(parent_order, "roundLotSize", None)

    violations: List[Violation] = []
    violations.extend(
        _check_notional(
            order_type=order_type or "",
            qty=route_qty,
            limit_price=limit_price,
            stop_price=stop_price,
            last_price=last_price,
            fx_rate=fx_rate,
            currency=currency,
        )
    )
    violations.extend(
        _check_jp_odd_lot(
            qty=route_qty,
            exchange=exchange,
            currency=currency,
            round_lot_size=round_lot_size,
        )
    )
    return violations


def check_modify(
    cached_route: Any,
    parent_order: Any,
    *,
    new_qty: Optional[int],
    new_limit_price: Optional[float],
    new_stop_price: Optional[float],
    new_order_type: Optional[str],
) -> List[Violation]:
    """Run pre-trade compliance for a ModifyRouteEx request.

    Effective values fall back to the cached route / parent order when the
    request does not explicitly override them.
    """
    if cached_route is None and parent_order is None:
        return []

    qty = new_qty if new_qty is not None else int(getattr(cached_route, "amount", 0) or 0)
    if qty <= 0:
        return []

    order_type = new_order_type or getattr(cached_route, "orderType", "") or ""

    if new_limit_price is not None:
        limit_price: Optional[float] = new_limit_price
    else:
        limit_price = getattr(cached_route, "limitPrice", None)
    if new_stop_price is not None:
        stop_price: Optional[float] = new_stop_price
    else:
        stop_price = getattr(cached_route, "stopPrice", None)

    currency = (
        getattr(parent_order, "currency", None)
        if parent_order is not None
        else getattr(cached_route, "currency", None)
    )
    exchange = (
        getattr(parent_order, "exchange", None)
        if parent_order is not None
        else getattr(cached_route, "exchange", None)
    )
    fx_rate = getattr(parent_order, "fxRate", None) if parent_order is not None else None
    last_price = (
        getattr(parent_order, "lastPrice", None)
        if parent_order is not None
        else getattr(cached_route, "lastPrice", None)
    )
    round_lot_size = (
        getattr(parent_order, "roundLotSize", None) if parent_order is not None else None
    )

    violations: List[Violation] = []
    violations.extend(
        _check_notional(
            order_type=order_type,
            qty=qty,
            limit_price=limit_price,
            stop_price=stop_price,
            last_price=last_price,
            fx_rate=fx_rate,
            currency=currency,
        )
    )
    violations.extend(
        _check_jp_odd_lot(
            qty=qty,
            exchange=exchange,
            currency=currency,
            round_lot_size=round_lot_size,
        )
    )
    return violations
