"""
Order projection service — enrichment and filtering logic for orders.

Extracted from BloombergEMSXService.get_orders() to enable testable,
standalone order processing without Bloomberg session dependency.
"""

from __future__ import annotations

import logging
from typing import List, Optional, Dict, Callable

from schemas import Order, OrderFilters

logger = logging.getLogger("main")


def enrich_orders(
    orders: List[Order],
    *,
    price_changes: Dict[str, float],
    adv5d: Dict[str, float],
    mkt_vwap: Dict[str, float],
    fx_rates: Dict[str, float],
    ticker_currencies: Dict[str, str],
    round_lot_sizes: Dict[str, int],
    order_last_prices: Dict[str, float],
    odd_lot_markets: set,
    derive_exchange: Callable[[str], str],
) -> List[Order]:
    """Enrich a list of orders with market data, FX rates, and computed fields.

    Pure function — does not touch any external state.  Returns a new list of
    enriched Order instances.  The caller is responsible for writing enriched
    data back to the cache if desired.

    Parameters
    ----------
    orders : list[Order]
        Raw orders from the subscription cache.
    price_changes, adv5d, mkt_vwap : dict
        Ticker → value caches from mktdata subscriptions.
    fx_rates : dict
        Currency → USD rate.
    ticker_currencies : dict
        Ticker → authoritative trading currency (from //blp/refdata CRNCY).
    round_lot_sizes : dict
        Ticker → PX_ROUND_LOT_SIZE.
    order_last_prices : dict
        Order id → last price (derived from route data).
    odd_lot_markets : set
        Exchange codes where odd-lot detection is enabled.
    derive_exchange : callable
        Function ``(ticker) -> exchange_code``.
    """
    enriched: List[Order] = []
    fx_miss_count = 0

    for o in orders:
        updates: dict = {}

        # Derive exchange from ticker if empty
        if not o.exchange and o.symbol:
            updates["exchange"] = derive_exchange(o.symbol)

        # Market data enrichment
        pct = price_changes.get(o.symbol)
        if pct is not None:
            updates["pctChange"] = pct
        adv = adv5d.get(o.symbol)
        if adv is not None:
            updates["adv5d"] = adv
        vwap = mkt_vwap.get(o.symbol)
        if vwap is not None:
            updates["mktVwap"] = vwap

        # Last price from routes
        lp = order_last_prices.get(o.id)
        if lp is not None:
            updates["lastPrice"] = lp
        effective_last = lp if lp is not None else o.lastPrice

        # Odd-lot detection
        effective_exchange = updates.get("exchange", o.exchange) or ""
        if effective_exchange.upper() in odd_lot_markets:
            round_lot = round_lot_sizes.get(o.symbol)
            if round_lot is not None and round_lot > 0:
                updates["isOddLot"] = (o.quantity % round_lot) != 0
            else:
                updates["isOddLot"] = None
        else:
            updates["isOddLot"] = False

        # Authoritative trading currency
        auth_ccy = ticker_currencies.get(o.symbol) or o.currency or ""
        if auth_ccy and auth_ccy != o.currency:
            updates["currency"] = auth_ccy

        # FX rate
        fx_rate: Optional[float] = None
        if auth_ccy:
            if auth_ccy == "USD":
                fx_rate = 1.0
            else:
                fx_rate = fx_rates.get(auth_ccy)
            if fx_rate is not None:
                updates["fxRate"] = round(fx_rate, 6) if fx_rate != 1.0 else 1.0

        if auth_ccy and auth_ccy != "USD" and fx_rate is None:
            fx_miss_count += 1
            if fx_miss_count <= 3:
                logger.warning(
                    f"FX MISS: order {o.id} symbol={o.symbol} "
                    f"auth_ccy='{auth_ccy}' stored_ccy='{o.currency}'"
                )

        # Dollar value computation
        effective_vwap = vwap if vwap is not None else o.mktVwap
        best_price = (
            effective_vwap if (effective_vwap and effective_vwap > 0) else
            effective_last if (effective_last and effective_last > 0) else
            o.avgPrice if (o.avgPrice and o.avgPrice > 0) else
            o.price if (o.price and o.price > 0) else
            None
        )
        if best_price and o.quantity > 0:
            if auth_ccy == "USD" or not auth_ccy:
                updates["dollarValueUsd"] = round(best_price * o.quantity, 0)
            elif fx_rate is not None and fx_rate > 0:
                if auth_ccy in ("GBP", "ZAR"):
                    updates["dollarValueUsd"] = round(best_price * o.quantity * fx_rate / 100, 0)
                else:
                    updates["dollarValueUsd"] = round(best_price * o.quantity * fx_rate, 0)

        enriched_order = o.model_copy(update=updates) if updates else o
        enriched.append(enriched_order)

    if fx_miss_count > 0:
        logger.warning(f"FX rate missing for {fx_miss_count} non-USD orders out of {len(orders)} total")

    return enriched


def filter_orders(
    orders: List[Order],
    filters: OrderFilters,
    *,
    round_lot_sizes: Dict[str, int],
    odd_lot_markets: set,
) -> List[Order]:
    """Apply client-side filters to an enriched order list.

    Pure function — no side effects.

    Parameters
    ----------
    orders : list[Order]
        Pre-enriched orders.
    filters : OrderFilters
        Filter criteria from the API request.
    round_lot_sizes : dict
        Ticker → PX_ROUND_LOT_SIZE (needed for oddLot filter).
    odd_lot_markets : set
        Exchange codes where odd-lot detection is enabled.
    """
    result = list(orders)

    if filters.symbol:
        sym = filters.symbol.upper()
        result = [o for o in result if sym in o.symbol.upper()]
    if filters.side:
        result = [o for o in result if o.side == filters.side]
    if filters.status:
        result = [o for o in result if o.status == filters.status]
    if filters.orderType:
        result = [o for o in result if o.orderType == filters.orderType]
    if filters.portfolio:
        port = filters.portfolio.upper()
        result = [o for o in result if port in o.portfolio.upper()]
    if filters.trader:
        result = [o for o in result if filters.trader.upper() in o.trader.upper()]
    if filters.exchange:
        ex = filters.exchange.upper()
        result = [o for o in result if o.exchange and ex in o.exchange.upper()]
    if filters.currency:
        cur = filters.currency.upper()
        result = [o for o in result if cur in o.currency.upper()]
    if filters.oddLot is not None:
        def _is_odd_lot(order: Order) -> bool:
            if not order.exchange or order.exchange.upper() not in odd_lot_markets:
                return False
            round_lot = round_lot_sizes.get(order.symbol)
            if round_lot is None or round_lot <= 0:
                return False
            return (order.quantity % round_lot) != 0
        result = [o for o in result if _is_odd_lot(o) == filters.oddLot]

    return result
