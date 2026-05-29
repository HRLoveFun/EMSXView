"""
Bloomberg EMSX Service — Facade.

Orchestrates the four internal components:
  - BloombergConnectionManager    (session lifecycle, pools)
  - EMSXSubscriptionEngine        (order/route subscription, cache, parsing)
  - MarketDataEnrichmentService   (mktdata streaming, FX, currency, round lot)
  - EMSXRequestHandler            (modify/cancel/route, broker/strategy queries)

Provides backward-compatible BloombergEMSXService that satisfies the
BloombergEMSXAdapterInterface ABC from bloomberg_interface.py.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

from fastapi import HTTPException

from schemas import (
    Order, OrderFilters, StartupStatus,
    BatchUpdateRequest, BatchUpdateResponse,
    CancelRouteRequest, ModifyRouteRequest, RouteOrderRequest,
)

from services.order_projections import enrich_orders, filter_orders
from services.route_projections import enrich_routes

from .connection import BloombergConnectionManager, configure_connection
from .subscriptions import EMSXSubscriptionEngine
from .enrichment import MarketDataEnrichmentService
from .request_handler import EMSXRequestHandler, configure_handler

from .._bloomberg_parsing import derive_currency, derive_exchange

logger = logging.getLogger("main")

# Module-level dependencies — set by configure() before instantiation
settings = None          # type: Any
repo_provider = None     # type: Any


def configure(_settings, _repo_provider):
    """Inject module-level dependencies. Must be called before creating BloombergEMSXService."""
    global settings, repo_provider
    settings = _settings
    repo_provider = _repo_provider
    configure_connection(_settings)
    configure_handler(_settings)


class BloombergEMSXService:
    """Bloomberg EMSX API Service — Subscription Mode (Facade).

    Delegates to 4 internal classes:
      - _conn:    BloombergConnectionManager
      - _sub:     EMSXSubscriptionEngine
      - _enrich:  MarketDataEnrichmentService
      - _handler: EMSXRequestHandler
    """

    def __init__(self):
        # ── Sub-components ────────────────────────────────────────────
        self._conn = BloombergConnectionManager()
        self._sub = EMSXSubscriptionEngine(self._conn, repo_provider)
        self._enrich = MarketDataEnrichmentService(self._conn, self._sub, settings)
        self._handler = EMSXRequestHandler(self._conn, self._sub)

        # Backward-compatible async lock (kept for connect())
        self._lock = asyncio.Lock()

    # ── Backward-compatible proxy properties (for tests) ──────────────
    # These attributes previously lived on BloombergEMSXService directly.
    # Now delegated to MarketDataEnrichmentService.

    @property
    def _fx_refdata_pending(self):
        return self._enrich._fx_refdata_pending

    @_fx_refdata_pending.setter
    def _fx_refdata_pending(self, value):
        self._enrich._fx_refdata_pending = value

    @property
    def _crncy_refdata_pending(self):
        return self._enrich._crncy_refdata_pending

    @_crncy_refdata_pending.setter
    def _crncy_refdata_pending(self, value):
        self._enrich._crncy_refdata_pending = value

    @property
    def _round_lot_refdata_pending(self):
        return self._enrich._round_lot_refdata_pending

    @_round_lot_refdata_pending.setter
    def _round_lot_refdata_pending(self, value):
        self._enrich._round_lot_refdata_pending = value

    def _mark_refdata_response_complete(self, correlation_values: set) -> None:
        self._enrich._mark_refdata_response_complete(correlation_values)

    def _log_fx_rate_discrepancy(self, ccy: str, direct_rate: float, inverse_rate: float) -> None:
        self._enrich._log_fx_rate_discrepancy(ccy, direct_rate, inverse_rate)

    # ── Connection management (delegated to ConnectionManager) ────────

    async def connect(self) -> bool:
        async with self._lock:
            if self._conn.connected and self._conn.session:
                return True

            if not self._conn.connect():
                return False

            # Reset subscription and enrichment state for fresh connection
            self._sub.reset_state()
            self._enrich.reset_state()

            # Start background threads
            self._sub.start()
            self._enrich.start()

            logger.info("Started EMSX subscription + mktdata subscription threads")
            return True

    def disconnect(self) -> None:
        """Disconnect from Bloomberg and cleanup all resources."""
        logger.info("Disconnecting from Bloomberg...")
        self._sub.stop()
        self._enrich.stop()
        self._conn.disconnect()

    def get_status(self):
        return self._conn.get_status()

    def get_startup_status(self) -> StartupStatus:
        # Mark init paint complete if we have data (same as original logic)
        with self._sub.data_lock:
            if self._sub.orders and not self._sub.init_paint_done:
                self._sub.init_paint_done = True
            if self._sub.routes and not self._sub.route_init_paint_done:
                self._sub.route_init_paint_done = True

        result = self._conn.get_startup_status(
            init_paint_done=self._sub.init_paint_done,
            route_init_paint_done=self._sub.route_init_paint_done,
            subscription_failed=self._sub.subscription_failed,
            subscription_failed_at=self._sub.subscription_failed_at,
            _mktdata_connected=self._enrich.mktdata_connected,
            order_count=len(self._sub.orders),
            route_count=len(self._sub.routes),
        )

        # Auto-clear subscription failure if stuck > 5 min
        if self._sub.subscription_failed and self._sub.subscription_failed_at:
            stuck_seconds = (datetime.now() - self._sub.subscription_failed_at).total_seconds()
            if stuck_seconds > 300:
                logger.warning(
                    "Subscription failed for %.0fs — auto-clearing flag", stuck_seconds,
                )
                self._sub._subscription_failed = False
                self._sub._subscription_failed_at = None

        return result

    # ── Public API: Orders (combines subscription + enrichment) ───────

    async def get_orders(self, filters: Optional[OrderFilters] = None) -> List[Order]:
        """Return enriched orders from the live subscription cache."""
        if not await self.connect():
            raise HTTPException(503, "Failed to connect to Bloomberg")

        # Wait for INIT_PAINT
        if not self._sub.init_paint_done:
            with self._sub.data_lock:
                order_count = len(self._sub.orders)
            if order_count > 0:
                self._sub.init_paint_done = True
                logger.info("INIT_PAINT inferred complete — %d orders in cache", order_count)
            else:
                logger.info("Waiting for EMSX INIT_PAINT to complete...")
                for _ in range(60):
                    await asyncio.sleep(0.5)
                    with self._sub.data_lock:
                        has_orders = len(self._sub.orders) > 0
                        current_count = len(self._sub.orders)
                    if self._sub.init_paint_done or has_orders or self._sub.subscription_failed:
                        if has_orders and not self._sub.init_paint_done:
                            logger.info("Orders arriving: %d so far, waiting for more...", current_count)
                            await asyncio.sleep(2.0)
                        break
                with self._sub.data_lock:
                    order_count = len(self._sub.orders)
                if order_count > 0 and not self._sub.init_paint_done:
                    self._sub.init_paint_done = True
                    logger.info("INIT_PAINT inferred complete — %d orders in cache", order_count)
                if not self._sub.init_paint_done and not self._sub.subscription_failed:
                    logger.warning("INIT_PAINT not complete after 30s — returning partial snapshot")
            if self._sub.subscription_failed:
                logger.warning("Subscription failed — returning stale/empty cache. Bloomberg EMSX may be reconnecting.")
                self._conn.connected = False

        with self._sub.data_lock:
            orders = list(self._sub.orders.values())
        orders = [o for o in orders if o.symbol]
        logger.info("Returning %d orders from subscription cache", len(orders))

        # Build order -> lastPrice map from route data
        order_last_prices: Dict[str, float] = {}
        with self._sub.data_lock:
            routes_snapshot = list(self._sub.routes.items())
        for _rkey, route in routes_snapshot:
            if route.lastPrice and route.lastPrice > 0:
                seq_str = str(route.sequence)
                order_last_prices[seq_str] = route.lastPrice

        odd_lot_mkts = set(settings.ODD_LOT_MARKETS)
        enriched = enrich_orders(
            orders,
            price_changes=dict(self._enrich.price_changes),
            adv5d=dict(self._enrich.adv5d),
            mkt_vwap=dict(self._enrich.mkt_vwap),
            fx_rates=dict(self._enrich.fx_rates),
            ticker_currencies=dict(self._enrich.ticker_currencies),
            round_lot_sizes=dict(self._enrich.round_lot_sizes),
            order_last_prices=order_last_prices,
            odd_lot_markets=odd_lot_mkts,
            derive_exchange=derive_exchange,
        )

        # Save enriched data back to cache + inject permfail last-prices
        with self._sub.data_lock:
            for order in enriched:
                permfail_px = self._enrich.permfail_last_prices.get(order.symbol)
                if permfail_px is not None and permfail_px > 0:
                    order.lastPrice = permfail_px
                self._sub.orders[order.id] = order
        orders = enriched

        if filters:
            orders = filter_orders(
                orders,
                filters,
                round_lot_sizes=dict(self._enrich.round_lot_sizes),
                odd_lot_markets=odd_lot_mkts,
            )

        return orders

    async def get_routes(self) -> List[dict]:
        """Return enriched routes from the live subscription cache."""
        if not await self.connect():
            raise HTTPException(503, "Failed to connect to Bloomberg")

        if not self._sub.route_init_paint_done:
            with self._sub.data_lock:
                route_count = len(self._sub.routes)
            if route_count > 0:
                self._sub.route_init_paint_done = True
                logger.info("Route INIT_PAINT inferred complete — %d routes in cache", route_count)
            else:
                logger.info("Waiting for Route INIT_PAINT to complete...")
                for _ in range(30):
                    await asyncio.sleep(0.5)
                    with self._sub.data_lock:
                        has_routes = len(self._sub.routes) > 0
                    if self._sub.route_init_paint_done or has_routes or self._sub.subscription_failed:
                        break
                with self._sub.data_lock:
                    route_count = len(self._sub.routes)
                if route_count > 0 and not self._sub.route_init_paint_done:
                    self._sub.route_init_paint_done = True
                if self._sub.subscription_failed:
                    logger.warning("Route subscription failed — resetting for reconnect")
                    self._conn.connected = False

        with self._sub.data_lock:
            routes = list(self._sub.routes.values())
            orders_snapshot = dict(self._sub.orders)
        logger.info("Returning %d routes from subscription cache", len(routes))

        return enrich_routes(routes, orders_snapshot, derive_exchange=derive_exchange)

    # ── Public API: Order/Route operations (delegated to RequestHandler)

    async def modify_order(self, order_id: str, field: str, value: Any) -> bool:
        if not await self.connect():
            raise HTTPException(503, "Bloomberg not connected")
        return await self._handler.modify_order(order_id, field, value)

    async def cancel_order(self, order_id: str) -> bool:
        if not await self.connect():
            raise HTTPException(503, "Bloomberg not connected")
        return await self._handler.cancel_order(order_id)

    async def batch_update(self, request_data: BatchUpdateRequest) -> BatchUpdateResponse:
        if not await self.connect():
            raise HTTPException(503, "Bloomberg not connected")
        return await self._handler.batch_update(request_data)

    async def cancel_route(self, request_data: CancelRouteRequest) -> bool:
        if not await self.connect():
            raise HTTPException(503, "Bloomberg not connected")
        return await self._handler.cancel_route(request_data)

    async def modify_route(self, request_data: ModifyRouteRequest) -> bool:
        if not await self.connect():
            raise HTTPException(503, "Bloomberg not connected")
        return await self._handler.modify_route(request_data)

    async def route_order(self, request_data: RouteOrderRequest) -> dict:
        if not await self.connect():
            raise HTTPException(503, "Bloomberg not connected")
        return await self._handler.route_order(request_data)

    async def get_asset_class(self, ticker: str) -> str:
        if not await self.connect():
            logger.warning("Bloomberg not connected - defaulting asset class to EQTY for %s", ticker)
            return "EQTY"
        return await self._handler.get_asset_class(ticker)

    async def get_broker_strategies(self, broker: str, asset_class: str = "EQTY") -> List[str]:
        if not await self.connect():
            logger.error("Bloomberg not connected - cannot get strategies for %s", broker)
            raise HTTPException(
                503,
                f"Bloomberg not connected - last error: {self._conn.last_error or 'Unknown'}",
            )
        return await self._handler.get_broker_strategies(broker, asset_class)

    async def get_broker_strategy_info(
        self, broker: str, strategy: str, asset_class: str = "EQTY",
    ) -> List[dict]:
        if not await self.connect():
            logger.error("Bloomberg not connected - cannot get strategy info for %s/%s", broker, strategy)
            raise HTTPException(
                503,
                f"Bloomberg not connected - last error: {self._conn.last_error or 'Unknown'}",
            )
        return await self._handler.get_broker_strategy_info(broker, strategy, asset_class)

    async def get_brokers(self, asset_class: str = "EQTY") -> List[str]:
        if not await self.connect():
            logger.error("Bloomberg not connected - cannot get brokers")
            raise HTTPException(
                503,
                f"Bloomberg not connected - last error: {self._conn.last_error or 'Unknown'}",
            )
        return await self._handler.get_brokers(asset_class)

    def get_terminal_trader_name(self) -> str:
        if settings.EMSXVIEW_TRADER_NAME:
            return settings.EMSXVIEW_TRADER_NAME
        votes: Dict[str, int] = {}
        for order in self._sub.orders.values():
            t = order.trader
            if t:
                votes[t] = votes.get(t, 0) + 1
        if votes:
            best = max(votes, key=votes.get)
            logger.debug("Auto-detected trader (fallback): %s with %d orders", best, votes[best])
            return best
        return ""
