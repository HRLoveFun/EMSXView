"""
Route projection service — enrichment logic for routes.

Extracted from BloombergEMSXService.get_routes() to enable testable,
standalone route processing without Bloomberg session dependency.
"""

from __future__ import annotations

import logging
from typing import List, Dict, Callable

from models import Order, Route

logger = logging.getLogger("main")


def enrich_routes(
    routes: List[Route],
    orders_snapshot: Dict[str, Order],
    *,
    derive_exchange: Callable[[str], str],
) -> List[dict]:
    """Enrich routes with parent order data and return as dicts.

    Pure function — does not modify any external state.

    Parameters
    ----------
    routes : list[Route]
        Raw routes from the subscription cache.
    orders_snapshot : dict[str, Order]
        Current order cache snapshot (key = order id / sequence str).
    derive_exchange : callable
        Function ``(ticker) -> exchange_code``.

    Returns
    -------
    list[dict]
        Enriched route dicts ready for API response.
    """
    enriched: List[dict] = []
    logger.info(f"Enriching {len(routes)} routes, orders cache has {len(orders_snapshot)} orders")

    for r in routes:
        r_dict = r.model_dump()
        parent = orders_snapshot.get(str(r.sequence))

        if parent:
            r_dict["ticker"] = r.ticker or parent.symbol or ""
            r_dict["side"] = r.side or parent.side or ""
            r_dict["portfolio"] = r.portfolio or parent.portfolio or ""
            r_dict["trader"] = r.trader or parent.trader or ""
            r_dict["traderUuid"] = r.traderUuid if r.traderUuid else parent.traderUuid
            r_dict["currency"] = r.currency or parent.currency or ""
            r_dict["exchange"] = (
                r.exchange or parent.exchange or derive_exchange(r_dict["ticker"]) or ""
            )
            logger.info(
                f"Enrich route {r.id}: parent seq={r.sequence}, "
                f"route.ticker='{r.ticker}'->'{r_dict['ticker']}', "
                f"route.exchange='{r.exchange}'->'{r_dict['exchange']}'"
            )
        else:
            if r.ticker:
                logger.debug(
                    f"Enrich route {r.id}: using cached values, "
                    f"ticker='{r.ticker}', exchange='{r.exchange}'"
                )
            else:
                logger.warning(
                    f"Enrich route {r.id}: no parent order found "
                    f"for seq={r.sequence} and no cached values"
                )
            r_dict["ticker"] = r.ticker or ""
            r_dict["side"] = r.side or ""
            r_dict["portfolio"] = r.portfolio or ""
            r_dict["trader"] = r.trader or ""
            r_dict["traderUuid"] = r.traderUuid or 0
            r_dict["currency"] = r.currency or ""
            r_dict["exchange"] = r.exchange or ""

        enriched.append(r_dict)

    return enriched
