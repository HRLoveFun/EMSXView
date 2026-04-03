"""
Bloomberg EMSX Service — extracted from main.py for modular architecture.

Provides the BloombergEMSXService class that manages Bloomberg API connections,
subscriptions, order/route caching, market data enrichment, and request/response
operations.

Dependencies are injected via ``configure()`` before constructing the service.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

from fastapi import HTTPException

import blpapi
from blpapi import SessionOptions, Session, Service, Request, Message, Event

from schemas import (
    Order, Route, OrderFilters, ConnectionStatus,
    BatchUpdateRequest, BatchUpdateResponse,
    CancelRouteRequest, ModifyRouteRequest, RouteOrderRequest,
)
from services.realtime_gateway import realtime_gw
from services.order_projections import enrich_orders, filter_orders
from services.route_projections import enrich_routes

logger = logging.getLogger("main")

# ---------------------------------------------------------------------------
# Module-level dependencies — set by configure() before instantiation
# ---------------------------------------------------------------------------
settings = None          # type: Any  # Settings instance from main
repo_provider = None     # type: Any  # RepositoryProvider instance


def configure(_settings, _repo_provider):
    """Inject module-level dependencies. Must be called before creating BloombergEMSXService."""
    global settings, repo_provider
    settings = _settings
    repo_provider = _repo_provider


class BloombergEMSXService:
    """
    Bloomberg EMSX API Service — Subscription Mode
    
    Uses the EMSX subscription service (per Bloomberg docs) to monitor live orders.
    Subscribe to //blp/emapisvc_beta/order (or //blp/emapisvc/order) and maintain
    an in-memory order cache updated by INIT_PAINT and live update events.
    
    Event statuses:
      EVENT_STATUS = 4   INIT_PAINT   — initial snapshot of all current orders
      EVENT_STATUS = 6   NEW_ORDER    — new order added to blotter
      EVENT_STATUS = 7   UPD_ORDER    — existing order updated
      EVENT_STATUS = 8   DELETION     — order deleted
      EVENT_STATUS = 11  INIT_PAINT_END — end of initial snapshot
    """

    EMSX_SERVICES = ["//blp/emapisvc", "//blp/emapisvc_beta"]

    # Fields to subscribe to
    ORDER_FIELDS = [
        "API_SEQ_NUM",
        "EMSX_SEQUENCE",
        "EMSX_TICKER",
        "EMSX_SIDE",
        "EMSX_AMOUNT",
        "EMSX_FILLED",
        "EMSX_STATUS",
        "EMSX_ORDER_TYPE",
        "EMSX_LIMIT_PRICE",
        "EMSX_STOP_PRICE",
        "EMSX_AVG_PRICE",
        "EMSX_TIF",
        "EMSX_ACCOUNT",
        "EMSX_TRADER",
        "EMSX_NOTES",
        "EMSX_DATE",
        "EMSX_TIME_STAMP",
        "EMSX_EXCHANGE",
        "EMSX_CURRENCY_PAIR",
        "EMSX_ISIN",
        "EMSX_SEC_NAME",
        "EMSX_WORKING",
        "EMSX_PORT_NAME",
        "EMSX_CUSTOM_NOTE1",
        "EMSX_CUSTOM_NOTE2",
        "EMSX_CUSTOM_NOTE3",
        "EMSX_CUSTOM_NOTE4",
        "EMSX_CUSTOM_NOTE5",
        "EMSX_TRADER_NOTES",
        "EMSX_EXEC_INSTRUCTION",
        "EMSX_PERCENT_REMAIN",
        "EMSX_HAND_INSTRUCTION",
        "EMSX_STRATEGY_TYPE",
        "EMSX_STRATEGY_PART_RATE1",
        "EMSX_STRATEGY_STYLE",
        "EMSX_STRATEGY_START_TIME",
        "EMSX_STRATEGY_END_TIME",
        "EMSX_PM_UUID",
        "EMSX_TRAD_UUID",
        "EMSX_BROKER",
        "EMSX_DAY_AVG_PRICE",
        "EMSX_ARRIVAL_PRICE",
    ]

    # Route subscription fields (per EMSX API Developer's Guide)
    ROUTE_FIELDS = [
        "API_SEQ_NUM",
        "EMSX_SEQUENCE",
        "EMSX_ROUTE_ID",
        "EMSX_STATUS",
        "EMSX_BROKER",
        "EMSX_AMOUNT",
        "EMSX_FILLED",
        "EMSX_WORKING",
        "EMSX_AVG_PRICE",
        "EMSX_LIMIT_PRICE",
        "EMSX_STOP_PRICE",
        "EMSX_LAST_PRICE",
        "EMSX_LAST_SHARES",
        "EMSX_LAST_FILL_DATE",
        "EMSX_LAST_FILL_TIME",
        "EMSX_DAY_AVG_PRICE",
        "EMSX_DAY_FILL",
        "EMSX_ORDER_TYPE",
        "EMSX_TIF",
        "EMSX_HAND_INSTRUCTION",
        "EMSX_EXEC_INSTRUCTION",
        "EMSX_NOTES",
        "EMSX_STRATEGY_TYPE",
        "EMSX_STRATEGY_STYLE",
        "EMSX_STRATEGY_PART_RATE1",
        "EMSX_STRATEGY_PART_RATE2",
        "EMSX_STRATEGY_START_TIME",
        "EMSX_STRATEGY_END_TIME",
        "EMSX_EXCHANGE_DESTINATION",
        "EMSX_EXECUTE_BROKER",
        "EMSX_IS_MANUAL_ROUTE",
        "EMSX_ROUTE_REF_ID",
        "EMSX_CURRENCY_PAIR",
        "EMSX_URGENCY_LEVEL",
        "EMSX_ROUTE_CREATE_DATE",
        "EMSX_ROUTE_CREATE_TIME",
        "EMSX_TIME_STAMP",
        "EMSX_ROUTE_LAST_UPDATE_TIME",
        "EMSX_FILL_ID",
        "EMSX_PERCENT_REMAIN",
        "EMSX_REMAIN_BALANCE",
        "EMSX_REASON_CODE",
        "EMSX_REASON_DESC",
        "EMSX_BROKER_STATUS",
        "EMSX_SETTLE_AMOUNT",
        "EMSX_SETTLE_DATE",
        "EMSX_COMM_RATE",
        "EMSX_BROKER_COMM",
        "EMSX_USER_COMM_RATE",
        "EMSX_USER_COMM_AMOUNT",
        "EMSX_USER_FEES",
        "EMSX_MISC_FEES",
        "EMSX_USER_NET_MONEY",
        "EMSX_PRINCIPAL",
        "EMSX_ROUTE_PRICE",
        "EMSX_BSE_AVG_PRICE",
        "EMSX_BSE_FILLED",
        "EMSX_NSE_AVG_PRICE",
        "EMSX_NSE_FILLED",
    ]

    STATUS_MAP = {
        "NEW": "NEW", "WORKING": "WORKING",
        "PARTFILLED": "PARTIAL", "PARTFILL": "PARTIAL",
        "FILLED": "FILLED",
        "CANCELLED": "CANCELLED", "CANCEL": "CANCELLED",
        "CXL-PEND": "PENDING_CANCEL", "CXLPENDING": "PENDING_CANCEL",
        "REJECTED": "REJECTED",
        "EXPIRED": "CANCELLED",
        "ASSIGN": "ASSIGN",
        "COMPLETED": "COMPLETED",
        "QUEUED": "QUEUED",
        "SUSPEND": "SUSPENDED", "SUSPENDED": "SUSPENDED",
        "SENT": "SENT", "A-SENT": "SENT",
        "ROUTED": "WORKING", "ACTIVE": "WORKING",
        "PENDING": "NEW", "PEND-NEW": "NEW",
    }

    SIDE_MAP = {"BUY": "BUY", "SELL": "SELL", 1: "BUY", 2: "SELL"}

    def __init__(self):
        self.session: Optional[Session] = None
        self.active_service_name: Optional[str] = None
        self.connected: bool = False
        self.connection_time: Optional[datetime] = None
        self.last_error: Optional[str] = None
        self.service: Optional[Service] = None

        # Dedicated session for request/response operations (get_brokers,
        # route_order, etc.).  Bloomberg's nextEvent() is NOT thread-safe:
        # calling it concurrently on the same session from the subscription
        # thread and request handler causes the subscription thread to steal
        # response events, making requests time out.
        self._request_session: Optional[Session] = None
        self._request_service: Optional[Service] = None

        # Separate session for //blp/mktdata subscriptions (market data, FX rates)
        # Using a separate session avoids nextEvent() races with the EMSX
        # subscription thread on the main session.
        self._mktdata_session: Optional[Session] = None
        self._mktdata_connected: bool = False

        # Order cache: keyed by EMSX_SEQUENCE (str)
        self._orders: Dict[str, Order] = {}
        self._init_paint_done: bool = False
        self._lock = asyncio.Lock()
        
        # Thread-safe lock for shared data access (protects _orders, _routes, etc.)
        self._data_lock = threading.RLock()

        # Route cache: keyed by "{EMSX_SEQUENCE}.{EMSX_ROUTE_ID}"
        self._routes: Dict[str, Route] = {}
        self._route_init_paint_done: bool = False

        # Terminal trader identity: computed on-demand from order cache

        # Subscription state tracking
        self._subscription_failed: bool = False

        # Background subscription thread
        self._sub_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Market data cache: ticker -> value (updated in real-time via //blp/mktdata subscriptions)
        self._price_changes: Dict[str, float] = {}
        self._adv5d: Dict[str, float] = {}
        self._mkt_vwap: Dict[str, float] = {}
        self._fx_rates: Dict[str, float] = {}  # currency -> USD rate (e.g. "HKD" -> 0.128)
        self._round_lot_sizes: Dict[str, int] = {}  # ticker -> round lot size (for odd lot detection)
        self._mktdata_subscribed_tickers: set = set()  # tickers currently subscribed (attempted)
        self._mktdata_active_tickers: set = set()       # tickers confirmed streaming data
        self._mktdata_failed_tickers: set = set()       # tickers whose subscription failed (retry later)
        self._mktdata_last_retry: Optional[datetime] = None
        self._mktdata_retry_interval = 300  # retry failed subscriptions every 5 min
        self._market_data_lock = threading.Lock()  # protect subscription management

        # FX rate refresh via //blp/refdata (every 5 minutes)
        self._fx_refresh_interval = 300  # refresh FX rates every 5 minutes (was: 3600)
        self._fx_last_refresh: Optional[datetime] = None
        self._fx_refdata_pending = False
        self._fx_refdata_cid = blpapi.CorrelationId("__fx_refdata__")
        self._crncy_refdata_cid = blpapi.CorrelationId("__crncy_refdata__")
        self._crncy_refdata_pending = False
        self._refdata_service_available = False

        # Authoritative ticker→trading-currency map from //blp/refdata CRNCY field
        self._ticker_currencies: Dict[str, str] = {}  # e.g. "0700 HK Equity" -> "HKD"
        self._crncy_queried_tickers: set = set()  # tickers already queried

        # Round lot size cache from //blp/refdata (like BDP function) - fetched once per ticker
        self._round_lot_sizes: Dict[str, int] = {}  # ticker -> round lot size
        self._round_lot_queried_tickers: set = set()  # tickers already queried (fetch once)
        self._round_lot_pending_tickers: set = set()  # tickers with pending refdata request
        self._round_lot_refdata_cid = blpapi.CorrelationId("__round_lot_refdata__")
        self._round_lot_refdata_pending = False

        # Background mktdata subscription thread
        self._mktdata_thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        async with self._lock:
            if self.connected and self.session:
                return True

            session = None  # Local variable for proper cleanup
            try:
                logger.info(f"Connecting to Bloomberg at {settings.BLOOMBERG_HOST}:{settings.BLOOMBERG_PORT}")

                session_options = SessionOptions()
                session_options.setServerAddress(
                    settings.BLOOMBERG_HOST,
                    settings.BLOOMBERG_PORT,
                    0,
                )
                session_options.setAutoRestartOnDisconnection(True)
                session_options.setNumStartAttempts(3)

                session = Session(session_options)
                if not session.start():
                    self.last_error = "Failed to start Bloomberg session"
                    logger.error(self.last_error)
                    if session:
                        try:
                            session.stop()
                        except Exception:
                            pass
                    return False

                # Try each service name in order
                opened_svc = None
                for svc_name in self.EMSX_SERVICES:
                    if session.openService(svc_name):
                        self.service = session.getService(svc_name)
                        self.active_service_name = svc_name
                        opened_svc = svc_name
                        logger.info(f"Opened Bloomberg EMSX service: {svc_name}")
                        break
                    else:
                        logger.warning(f"Could not open {svc_name}, trying next...")

                if not opened_svc:
                    self.last_error = "Failed to open any EMSX service"
                    logger.error(self.last_error)
                    session.stop()
                    return False

                # Store session only after all checks pass
                self.session = session
                self.connected = True
                self.connection_time = datetime.now()
                self.last_error = None

                # Reset subscription state for fresh connection
                with self._data_lock:
                    self._subscription_failed = False
                    self._init_paint_done = False
                    self._orders = {}
                    self._routes = {}
                    self._route_init_paint_done = False
                # Terminal trader identity resets with reconnect
                self._price_changes = {}
                self._adv5d = {}
                self._mkt_vwap = {}
                self._fx_rates = {}
                self._round_lot_sizes = {}
                self._mktdata_subscribed_tickers = set()
                self._mktdata_active_tickers = set()
                self._mktdata_failed_tickers = set()
                self._mktdata_last_retry = None
                self._fx_last_refresh = None
                self._fx_refdata_pending = False
                self._crncy_refdata_pending = False
                self._crncy_queried_tickers = set()
                self._ticker_currencies = {}
                self._refdata_service_available = False

                # Open dedicated request session for request/response operations
                # (avoids nextEvent race with EMSX subscription thread on main session)
                request_session = None
                try:
                    req_opts = SessionOptions()
                    req_opts.setServerAddress(settings.BLOOMBERG_HOST, settings.BLOOMBERG_PORT, 0)
                    req_opts.setAutoRestartOnDisconnection(True)
                    request_session = Session(req_opts)
                    if request_session.start() and request_session.openService(opened_svc):
                        self._request_session = request_session
                        self._request_service = request_session.getService(opened_svc)
                        logger.info(f"Opened dedicated request session for {opened_svc}")
                    else:
                        logger.warning("Could not open request session — falling back to shared session")
                        if request_session:
                            try:
                                request_session.stop()
                            except Exception:
                                pass
                        self._request_session = None
                        self._request_service = None
                except Exception as e:
                    logger.warning(f"Failed to open request session: {e}")
                    if request_session:
                        try:
                            request_session.stop()
                        except Exception:
                            pass
                    self._request_session = None
                    self._request_service = None

                # Open separate mktdata session for streaming market data + FX rates
                # (avoids nextEvent race with EMSX subscription thread on main session)
                mktdata_session = None
                try:
                    mktdata_opts = SessionOptions()
                    mktdata_opts.setServerAddress(settings.BLOOMBERG_HOST, settings.BLOOMBERG_PORT, 0)
                    mktdata_session = Session(mktdata_opts)
                    if mktdata_session.start() and mktdata_session.openService("//blp/mktdata"):
                        self._mktdata_session = mktdata_session
                        self._mktdata_connected = True
                        logger.info("Opened dedicated mktdata session for real-time market data subscriptions")
                        # Also open //blp/refdata for periodic FX rate queries
                        try:
                            if mktdata_session.openService("//blp/refdata"):
                                self._refdata_service_available = True
                                logger.info("Opened //blp/refdata on mktdata session for hourly FX rate lookups")
                        except Exception as e:
                            logger.warning(f"Could not open //blp/refdata on mktdata session: {e}")
                    else:
                        logger.warning("Could not open mktdata session — market data enrichment will be unavailable")
                        if mktdata_session:
                            try:
                                mktdata_session.stop()
                            except Exception:
                                pass
                        self._mktdata_session = None
                        self._mktdata_connected = False
                except Exception as e:
                    logger.warning(f"Failed to open mktdata session: {e}")
                    if mktdata_session:
                        try:
                            mktdata_session.stop()
                        except Exception:
                            pass
                    self._mktdata_session = None
                    self._mktdata_connected = False

                # Start background subscription thread
                self._stop_event.clear()
                self._sub_thread = threading.Thread(
                    target=self._subscription_loop,
                    daemon=True,
                    name="emsx-subscription",
                )
                self._sub_thread.start()

                # Start background mktdata subscription thread (real-time market data + FX)
                self._mktdata_thread = threading.Thread(
                    target=self._mktdata_subscription_loop,
                    daemon=True,
                    name="mktdata-subscription",
                )
                self._mktdata_thread.start()

                logger.info("Started EMSX subscription + mktdata subscription threads")
                return True

            except Exception as e:
                self.last_error = f"Connection error: {str(e)}"
                logger.exception(self.last_error)
                self.connected = False
                # Ensure session cleanup on error
                if session:
                    try:
                        session.stop()
                    except Exception:
                        pass
                return False

    def disconnect(self):
        """Disconnect from Bloomberg and cleanup all resources.
        
        Ensures proper cleanup even if threads are stuck.
        """
        logger.info("Disconnecting from Bloomberg...")
        self._stop_event.set()
        
        # Wait for threads with timeout, log warnings if stuck
        if self._sub_thread and self._sub_thread.is_alive():
            self._sub_thread.join(timeout=5)
            if self._sub_thread.is_alive():
                logger.warning("EMSX subscription thread did not stop within timeout")
        
        if self._mktdata_thread and self._mktdata_thread.is_alive():
            self._mktdata_thread.join(timeout=5)
            if self._mktdata_thread.is_alive():
                logger.warning("Mktdata subscription thread did not stop within timeout")
        
        # Stop mktdata session first (dependent on main session)
        if self._mktdata_session:
            try:
                self._mktdata_session.stop()
                logger.info("Mktdata session stopped")
            except Exception as e:
                logger.warning(f"Error stopping mktdata session: {e}")
            finally:
                self._mktdata_session = None
                self._mktdata_connected = False
        
        # Stop request session
        if self._request_session:
            try:
                self._request_session.stop()
                logger.info("Request session stopped")
            except Exception as e:
                logger.warning(f"Error stopping request session: {e}")
            finally:
                self._request_session = None
                self._request_service = None
        
        # Stop main session
        if self.session:
            try:
                self.session.stop()
                logger.info("Bloomberg session stopped")
            except Exception as e:
                logger.error(f"Error stopping session: {e}")
            finally:
                self.session = None
                self.service = None
                self.active_service_name = None
        
        self.connected = False
        self.connection_time = None
        logger.info("Bloomberg disconnect complete")

    def get_status(self) -> ConnectionStatus:
        if not self.connected:
            return ConnectionStatus(status="disconnected", message=self.last_error)
        uptime = int((datetime.now() - self.connection_time).total_seconds()) if self.connection_time else None
        return ConnectionStatus(
            status="connected",
            lastConnected=self.connection_time.isoformat() if self.connection_time else None,
            uptime=uptime,
        )

    # ------------------------------------------------------------------
    # Subscription loop (runs in background thread)
    # ------------------------------------------------------------------

    def _subscription_loop(self):
        """
        Background thread: subscribe to EMSX orders AND routes and keep caches updated.
        Bloomberg EMSX Subscription approach per official docs.
        """
        try:
            # Order subscription
            order_fields_str = ",".join(self.ORDER_FIELDS)
            order_topic = f"{self.active_service_name}/order?fields={order_fields_str}"
            logger.info(f"Subscribing to: {order_topic}")

            # Route subscription
            route_fields_str = ",".join(self.ROUTE_FIELDS)
            route_topic = f"{self.active_service_name}/route?fields={route_fields_str}"
            logger.info(f"Subscribing to: {route_topic}")

            sub_list = blpapi.SubscriptionList()
            order_cid = blpapi.CorrelationId(98)
            route_cid = blpapi.CorrelationId(99)
            sub_list.add(topic=order_topic, correlationId=order_cid)
            sub_list.add(topic=route_topic, correlationId=route_cid)
            self.session.subscribe(sub_list)

            while not self._stop_event.is_set():
                event = self.session.nextEvent(2000)  # 2-second timeout
                etype = event.eventType()

                if etype == blpapi.Event.SUBSCRIPTION_DATA:
                    for msg in event:
                        # Dispatch by CorrelationId (98=order, 99=route)
                        cid = msg.correlationId()
                        cid_val = cid.value() if cid else None
                        if cid_val == 99:
                            self._process_route_message(msg)
                        else:
                            self._process_subscription_message(msg)

                elif etype == blpapi.Event.SUBSCRIPTION_STATUS:
                    for msg in event:
                        mtype = str(msg.messageType())
                        if "SubscriptionStarted" in mtype:
                            logger.info("EMSX order subscription started")
                        elif "SubscriptionFailure" in mtype or "SubscriptionTerminated" in mtype:
                            logger.error(f"Subscription issue: {mtype}")
                            try:
                                reason = msg.getElement("reason")
                                desc = reason.getElementAsString("description")
                                logger.error(f"Subscription error detail: {desc}")
                            except Exception:
                                pass
                            # Mark subscription as failed and stop this thread
                            # so get_orders() can retry with the next service
                            self._subscription_failed = True
                            self.connected = False
                            logger.warning(f"Subscription failed for {self.active_service_name}, will retry with fallback service")
                            return

                elif etype == blpapi.Event.SESSION_STATUS:
                    for msg in event:
                        mtype = str(msg.messageType())
                        if "SessionTerminated" in mtype or "SessionStartupFailure" in mtype:
                            logger.error("Bloomberg session terminated")
                            self.connected = False
                            return

                elif etype == blpapi.Event.TIMEOUT:
                    continue  # normal timeout, keep looping

        except Exception as e:
            logger.exception(f"Subscription loop error: {e}")
            self.connected = False

    def _process_subscription_message(self, msg):
        """Process a single subscription message and update the order cache.
        
        Thread-safe: uses _data_lock to protect shared _orders cache.
        """
        try:
            # Check message fields
            event_status = self._msg_safe_int(msg, "EVENT_STATUS", -1)
            seq = self._msg_safe_int(msg, "EMSX_SEQUENCE", 0)
            if seq == 0:
                return

            seq_key = str(seq)

            # EVENT_STATUS = 8 → deletion
            if event_status == 8:
                with self._data_lock:
                    if seq_key in self._orders:
                        del self._orders[seq_key]
                        logger.debug(f"Deleted order {seq_key}")
                return

            # EVENT_STATUS = 11 → end of INIT_PAINT
            if event_status == 11:
                with self._data_lock:
                    order_count = len(self._orders)
                    self._init_paint_done = True
                logger.warning(f"INIT_PAINT complete — {order_count} orders loaded")
                return

            # Parse order from message (fields come directly in the message)
            order = self._parse_order_message(msg, seq)
            if not order:
                logger.warning(f"Failed to parse order for seq={seq}, event_status={event_status}")
                return

            # EVENT_STATUS=7 (update) only contains dynamic fields.
            # Static fields (EMSX_TICKER, EMSX_SIDE, etc.) will be empty.
            # Merge with cached order so static fields are preserved.
            with self._data_lock:
                if event_status == 7 and seq_key in self._orders:
                    cached = self._orders[seq_key]
                    merged = Order(
                        id=cached.id,
                        # Static fields: keep cached values when update is empty
                        symbol=order.symbol or cached.symbol,
                        side=order.side if self._msg_safe_str(msg, "EMSX_SIDE") else cached.side,
                        orderType=order.orderType if self._msg_safe_str(msg, "EMSX_ORDER_TYPE") else cached.orderType,
                        account=order.account or cached.account,
                        portfolio=order.portfolio or cached.portfolio,
                        trader=order.trader or cached.trader,
                        exchange=order.exchange or cached.exchange,
                        currency=order.currency if self._msg_safe_str(msg, "EMSX_CURRENCY_PAIR") else cached.currency,
                        createdAt=cached.createdAt,
                        # Dynamic fields: only update status if EMSX_STATUS was present in the message
                        status=order.status if self._msg_safe_str(msg, "EMSX_STATUS") else cached.status,
                        quantity=order.quantity if order.quantity > 0 else cached.quantity,
                        filledQuantity=order.filledQuantity,
                        remainingQuantity=order.remainingQuantity if order.quantity > 0 else cached.remainingQuantity,
                        price=order.price if order.price is not None else cached.price,
                        stopPrice=order.stopPrice or cached.stopPrice,
                        avgPrice=order.avgPrice or cached.avgPrice,
                        timeInForce=order.timeInForce if self._msg_safe_str(msg, "EMSX_TIF") else cached.timeInForce,
                        updatedAt=datetime.now().isoformat(),
                        notes=order.notes or cached.notes,
                        customNote1=order.customNote1 or cached.customNote1,
                        customNote2=order.customNote2 or cached.customNote2,
                        customNote3=order.customNote3 or cached.customNote3,
                        customNote4=order.customNote4 or cached.customNote4,
                        customNote5=order.customNote5 or cached.customNote5,
                        traderNotes=order.traderNotes or cached.traderNotes,
                        execInstruction=order.execInstruction or cached.execInstruction,
                        percentRemain=order.percentRemain if order.percentRemain is not None else cached.percentRemain,
                        percentFilled=order.percentFilled if order.filledQuantity > 0 else cached.percentFilled,
                        strategyType=order.strategyType or cached.strategyType,
                        strategyPartRate=order.strategyPartRate if order.strategyPartRate is not None else cached.strategyPartRate,
                        strategyStyle=order.strategyStyle or cached.strategyStyle,
                        strategyStartTime=order.strategyStartTime or cached.strategyStartTime,
                        strategyEndTime=order.strategyEndTime or cached.strategyEndTime,
                        broker=order.broker or cached.broker,
                        dayAvgPrice=order.dayAvgPrice if order.dayAvgPrice is not None else cached.dayAvgPrice,
                        arrivalPrice=order.arrivalPrice if order.arrivalPrice is not None else cached.arrivalPrice,
                        lastPrice=order.lastPrice if order.lastPrice is not None else cached.lastPrice,
                        dollarValueUsd=order.dollarValueUsd if order.dollarValueUsd is not None else cached.dollarValueUsd,
                        adv5d=cached.adv5d,  # preserved from market data enrichment
                        mktVwap=cached.mktVwap,  # preserved from market data enrichment
                        pctChange=cached.pctChange,  # preserved from market data enrichment
                    )
                    self._orders[seq_key] = merged
                    logger.debug(f"Order update (7): {seq_key} {merged.symbol} -> {merged.status}")
                elif event_status == 7:
                    # Update for a sequence not yet in cache (arrived before its INIT_PAINT).
                    # Skip to avoid inserting an order with empty static fields (blank ticker).
                    logger.debug(f"Skip update for unseen seq {seq_key} — no cached base data")
                else:
                    self._orders[seq_key] = order
                    if event_status == 4:
                        logger.debug(f"INIT_PAINT order: {seq_key} {order.symbol} {order.side} {order.status}")
                        # Log first few orders at WARNING level for diagnostics
                        if len(self._orders) <= 3:
                            logger.warning(f"INIT_PAINT order #{len(self._orders)}: seq={seq_key} symbol='{order.symbol}' exchange='{order.exchange}' side={order.side}")
                    elif event_status == 6:
                        logger.debug(f"New order (6): {seq_key} {order.symbol} {order.side} {order.status}")
                    # NEW: Try to enrich related routes when new order arrives
                    self._enrich_routes_with_new_order(order)

            # DB write-through (fire-and-forget from background thread)
            final_order = self._orders.get(seq_key)
            if final_order and repo_provider.is_active:
                self._schedule_persist_order(final_order)

        except Exception as e:
            logger.warning(f"Error processing subscription message: {e}")

    def _enrich_routes_with_new_order(self, order):
        """When a new order arrives, enrich related routes that were missing parent data.
        
        This handles the case where route data arrives before parent order.
        Thread-safe: should be called within _data_lock.
        """
        seq_str = str(order.id)  # order.id is the sequence number
        enriched_count = 0
        for route_key, route in self._routes.items():
            if str(route.sequence) == seq_str:
                # Check if ANY enrichment field is missing (not just ticker)
                needs_update = not route.ticker or not route.exchange or not route.side
                if needs_update:
                    # Update route with parent order data
                    update_dict = route.model_dump()
                    update_dict["ticker"] = route.ticker or order.symbol or ""
                    update_dict["side"] = route.side or order.side or ""
                    update_dict["portfolio"] = route.portfolio or order.portfolio or ""
                    update_dict["trader"] = route.trader or order.trader or ""
                    update_dict["traderUuid"] = route.traderUuid if route.traderUuid else (order.traderUuid or 0)
                    update_dict["currency"] = route.currency or order.currency or ""
                    update_dict["exchange"] = route.exchange or order.exchange or ""
                    self._routes[route_key] = Route(**update_dict)
                    enriched_count += 1
                    logger.info(f"Delayed enrichment for route {route_key}: ticker='{update_dict['ticker']}', exchange='{update_dict['exchange']}'")
        if enriched_count > 0:
            logger.info(f"Enriched {enriched_count} routes for new order {seq_str}")

    def _enrich_route_from_parent(self, route_key, route):
        """Enrich a single route from its parent order in cache.
        
        Thread-safe: should be called within _data_lock.
        """
        parent = self._orders.get(str(route.sequence))
        if parent and (not route.ticker or not route.exchange or not route.side):
            update_dict = route.model_dump()
            update_dict["ticker"] = route.ticker or parent.symbol or ""
            update_dict["side"] = route.side or parent.side or ""
            update_dict["portfolio"] = route.portfolio or parent.portfolio or ""
            update_dict["trader"] = route.trader or parent.trader or ""
            update_dict["traderUuid"] = route.traderUuid if route.traderUuid else (parent.traderUuid or 0)
            update_dict["currency"] = route.currency or parent.currency or ""
            update_dict["exchange"] = route.exchange or parent.exchange or ""
            self._routes[route_key] = Route(**update_dict)
            logger.debug(f"Enrich new route {route_key}: ticker='{update_dict['ticker']}', exchange='{update_dict['exchange']}'")

    # ------------------------------------------------------------------
    #  DB write-through helpers (called from background thread)
    # ------------------------------------------------------------------

    def _schedule_persist_order(self, order: Order) -> None:
        """Schedule an async DB upsert from the synchronous subscription thread."""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            return
        asyncio.run_coroutine_threadsafe(
            repo_provider.persist_order(
                sequence=int(order.id),
                order_id=order.id,
                status=order.status,
                trader=order.trader,
                payload=order.model_dump(),
            ),
            loop,
        )
        # Broadcast order delta to realtime clients
        asyncio.run_coroutine_threadsafe(
            realtime_gw.broadcast_order(order.model_dump(), event_type="update"),
            loop,
        )

    def _schedule_persist_route(self, route: Route) -> None:
        """Schedule an async DB upsert from the synchronous subscription thread."""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            return
        asyncio.run_coroutine_threadsafe(
            repo_provider.persist_route(
                sequence=route.sequence,
                route_id=route.routeId,
                status=route.status,
                broker=route.broker,
                payload=route.model_dump(),
            ),
            loop,
        )
        # Broadcast route delta to realtime clients
        asyncio.run_coroutine_threadsafe(
            realtime_gw.broadcast_route(route.model_dump(), event_type="update"),
            loop,
        )

    def _process_route_message(self, msg):
        """Process a single route subscription message and update the route cache.
        
        Thread-safe: uses _data_lock to protect shared _routes cache.
        """
        try:
            event_status = self._msg_safe_int(msg, "EVENT_STATUS", -1)
            seq = self._msg_safe_int(msg, "EMSX_SEQUENCE", 0)
            route_id = self._msg_safe_int(msg, "EMSX_ROUTE_ID", 0)
            if seq == 0 or route_id == 0:
                # Heartbeats and other control messages
                if event_status == 11:
                    with self._data_lock:
                        route_count = len(self._routes)
                        self._route_init_paint_done = True
                    logger.info(f"Route INIT_PAINT complete — {route_count} routes loaded")
                return

            route_key = f"{seq}.{route_id}"

            # EVENT_STATUS = 8 → deletion
            if event_status == 8:
                with self._data_lock:
                    if route_key in self._routes:
                        del self._routes[route_key]
                        logger.debug(f"Deleted route {route_key}")
                return

            # EVENT_STATUS = 11 → end of INIT_PAINT
            if event_status == 11:
                with self._data_lock:
                    route_count = len(self._routes)
                    self._route_init_paint_done = True
                logger.info(f"Route INIT_PAINT complete — {route_count} routes loaded")
                return

            route = self._parse_route_message(msg, seq, route_id)
            if route:
                with self._data_lock:
                    if event_status == 7 and route_key in self._routes:
                        # Merge update with cached route (keep static fields)
                        cached = self._routes[route_key]
                        update_dict = {}
                        for field_name in route.model_fields:
                            new_val = getattr(route, field_name)
                            cached_val = getattr(cached, field_name)
                            # Keep cached value if update is empty/default
                            if new_val is not None and new_val != "" and new_val != 0:
                                update_dict[field_name] = new_val
                            elif cached_val is not None and cached_val != "" and cached_val != 0:
                                update_dict[field_name] = cached_val

                        # IMPORTANT: Always preserve enrichment fields from cache
                        # These fields are populated from parent order and not in route messages
                        enrichment_fields = ["ticker", "side", "portfolio", "trader", "traderUuid", "currency", "exchange"]
                        for ef in enrichment_fields:
                            cached_ef_val = getattr(cached, ef, None)
                            # Use explicit comparison: empty string and 0 are valid cached values to skip,
                            # but non-empty strings and non-zero ints must be preserved
                            if cached_ef_val is not None and cached_ef_val != "" and cached_ef_val != 0:
                                update_dict[ef] = cached_ef_val

                        # Always keep key fields
                        update_dict["id"] = route_key
                        update_dict["routeId"] = route_id
                        update_dict["sequence"] = seq
                        # Always update status from the message if present
                        raw_status = self._msg_safe_str(msg, "EMSX_STATUS")
                        if raw_status:
                            update_dict["status"] = raw_status
                        self._routes[route_key] = Route(**update_dict)
                        logger.debug(f"Route update (7): {route_key} -> {self._routes[route_key].status}, "
                                    f"enrichment: ticker='{update_dict.get('ticker','')}', exchange='{update_dict.get('exchange','')}'")
                    elif event_status == 7:
                        logger.debug(f"Skip route update for unseen {route_key}")
                    else:
                        self._routes[route_key] = route
                        # Immediately enrich new route from parent order if available
                        self._enrich_route_from_parent(route_key, route)
                        if event_status == 4:
                            logger.debug(f"INIT_PAINT route: {route_key} {route.broker} {route.status}")
                        elif event_status == 6:
                            logger.debug(f"New route (6): {route_key} {route.broker} {route.status}")

                # DB write-through for routes (fire-and-forget)
                final_route = self._routes.get(route_key)
                if final_route and repo_provider.is_active:
                    self._schedule_persist_route(final_route)

        except Exception as e:
            logger.warning(f"Error processing route message: {e}")

    def _parse_route_message(self, msg, seq: int, route_id: int) -> Optional[Route]:
        """Parse a route subscription message into a Route model."""
        try:
            route_key = f"{seq}.{route_id}"
            status = self._msg_safe_str(msg, "EMSX_STATUS")
            broker = self._msg_safe_str(msg, "EMSX_BROKER")
            amount = self._msg_safe_int(msg, "EMSX_AMOUNT")
            filled = self._msg_safe_int(msg, "EMSX_FILLED")
            working = self._msg_safe_int(msg, "EMSX_WORKING")
            remain_balance = self._msg_safe_int(msg, "EMSX_REMAIN_BALANCE")
            avg_price = self._msg_safe_float(msg, "EMSX_AVG_PRICE") or None
            limit_price = self._msg_safe_float(msg, "EMSX_LIMIT_PRICE") or None
            stop_price = self._msg_safe_float(msg, "EMSX_STOP_PRICE") or None
            last_price = self._msg_safe_float(msg, "EMSX_LAST_PRICE") or None
            last_shares_raw = self._msg_safe_int(msg, "EMSX_LAST_SHARES", 0)
            last_shares = last_shares_raw if last_shares_raw > 0 else None
            day_avg_price = self._msg_safe_float(msg, "EMSX_DAY_AVG_PRICE") or None
            day_fill = self._msg_safe_int(msg, "EMSX_DAY_FILL")
            bse_avg_price = self._msg_safe_float(msg, "EMSX_BSE_AVG_PRICE") or None
            bse_filled = self._msg_safe_int(msg, "EMSX_BSE_FILLED")
            nse_avg_price = self._msg_safe_float(msg, "EMSX_NSE_AVG_PRICE") or None
            nse_filled = self._msg_safe_int(msg, "EMSX_NSE_FILLED")

            order_type = self._msg_safe_str(msg, "EMSX_ORDER_TYPE")
            tif = self._msg_safe_str(msg, "EMSX_TIF")
            hand_instruction = self._msg_safe_str(msg, "EMSX_HAND_INSTRUCTION")
            exec_instruction = self._msg_safe_str(msg, "EMSX_EXEC_INSTRUCTION")
            notes = self._msg_safe_str(msg, "EMSX_NOTES")

            strategy_type = self._msg_safe_str(msg, "EMSX_STRATEGY_TYPE")
            strategy_style = self._msg_safe_str(msg, "EMSX_STRATEGY_STYLE")
            strategy_part_rate1 = self._msg_safe_float(msg, "EMSX_STRATEGY_PART_RATE1") or None
            strategy_part_rate2 = self._msg_safe_float(msg, "EMSX_STRATEGY_PART_RATE2") or None
            # EMSX_STRATEGY_START_TIME / END_TIME are integers (HHMM format, e.g. 930 = 09:30)
            strategy_start_time_raw = self._msg_safe_int(msg, "EMSX_STRATEGY_START_TIME", 0)
            strategy_start_time = self._format_strategy_time(strategy_start_time_raw)
            strategy_end_time_raw = self._msg_safe_int(msg, "EMSX_STRATEGY_END_TIME", 0)
            strategy_end_time = self._format_strategy_time(strategy_end_time_raw)

            exchange_destination = self._msg_safe_str(msg, "EMSX_EXCHANGE_DESTINATION")
            execute_broker = self._msg_safe_str(msg, "EMSX_EXECUTE_BROKER")
            is_manual_route = self._msg_safe_int(msg, "EMSX_IS_MANUAL_ROUTE")
            route_ref_id = self._msg_safe_str(msg, "EMSX_ROUTE_REF_ID")
            currency_pair = self._msg_safe_str(msg, "EMSX_CURRENCY_PAIR")
            urgency_level = self._msg_safe_str(msg, "EMSX_URGENCY_LEVEL")

            # Timestamps
            route_create_date_raw = self._msg_safe_int(msg, "EMSX_ROUTE_CREATE_DATE")
            route_create_date = str(route_create_date_raw) if route_create_date_raw > 0 else ""
            route_create_time_raw = self._msg_safe_int(msg, "EMSX_ROUTE_CREATE_TIME")
            route_create_time = str(route_create_time_raw) if route_create_time_raw > 0 else ""
            last_fill_date_raw = self._msg_safe_int(msg, "EMSX_LAST_FILL_DATE")
            last_fill_date = str(last_fill_date_raw) if last_fill_date_raw > 0 else ""
            last_fill_time_raw = self._msg_safe_int(msg, "EMSX_LAST_FILL_TIME")
            last_fill_time = str(last_fill_time_raw) if last_fill_time_raw > 0 else ""
            time_stamp_raw = self._msg_safe_int(msg, "EMSX_TIME_STAMP")
            time_stamp = str(time_stamp_raw) if time_stamp_raw > 0 else ""
            route_last_update_raw = self._msg_safe_str(msg, "EMSX_ROUTE_LAST_UPDATE_TIME")
            route_last_update_time = route_last_update_raw

            fill_id = self._msg_safe_int(msg, "EMSX_FILL_ID")
            percent_remain = self._msg_safe_float(msg, "EMSX_PERCENT_REMAIN") or None

            reason_code = self._msg_safe_str(msg, "EMSX_REASON_CODE")
            reason_desc = self._msg_safe_str(msg, "EMSX_REASON_DESC")
            broker_status = self._msg_safe_str(msg, "EMSX_BROKER_STATUS")

            settle_amount = self._msg_safe_float(msg, "EMSX_SETTLE_AMOUNT") or None
            settle_date = self._msg_safe_str(msg, "EMSX_SETTLE_DATE")

            comm_rate = self._msg_safe_float(msg, "EMSX_COMM_RATE") or None
            broker_comm = self._msg_safe_float(msg, "EMSX_BROKER_COMM") or None
            user_comm_rate = self._msg_safe_float(msg, "EMSX_USER_COMM_RATE") or None
            user_comm_amount = self._msg_safe_float(msg, "EMSX_USER_COMM_AMOUNT") or None
            user_fees = self._msg_safe_float(msg, "EMSX_USER_FEES") or None
            misc_fees = self._msg_safe_float(msg, "EMSX_MISC_FEES") or None
            user_net_money = self._msg_safe_float(msg, "EMSX_USER_NET_MONEY") or None
            principal = self._msg_safe_float(msg, "EMSX_PRINCIPAL") or None
            route_price = self._msg_safe_float(msg, "EMSX_ROUTE_PRICE") or None

            return Route(
                id=route_key,
                routeId=route_id,
                sequence=seq,
                status=status,
                broker=broker,
                amount=amount,
                filled=filled,
                working=working,
                remainBalance=remain_balance,
                avgPrice=avg_price,
                limitPrice=limit_price,
                stopPrice=stop_price,
                lastPrice=last_price,
                lastShares=last_shares,
                dayAvgPrice=day_avg_price,
                dayFill=day_fill,
                bseAvgPrice=bse_avg_price,
                bseFilled=bse_filled,
                nseAvgPrice=nse_avg_price,
                nseFilled=nse_filled,
                orderType=order_type,
                tif=tif,
                handInstruction=hand_instruction,
                execInstruction=exec_instruction,
                notes=notes,
                strategyType=strategy_type,
                strategyStyle=strategy_style,
                strategyPartRate1=strategy_part_rate1,
                strategyPartRate2=strategy_part_rate2,
                strategyStartTime=strategy_start_time,
                strategyEndTime=strategy_end_time,
                exchangeDestination=exchange_destination,
                executeBroker=execute_broker,
                isManualRoute=is_manual_route,
                routeRefId=route_ref_id,
                currencyPair=currency_pair,
                urgencyLevel=urgency_level,
                routeCreateDate=route_create_date,
                routeCreateTime=route_create_time,
                lastFillDate=last_fill_date,
                lastFillTime=last_fill_time,
                timeStamp=time_stamp,
                routeLastUpdateTime=route_last_update_time,
                fillId=fill_id,
                percentRemain=percent_remain,
                reasonCode=reason_code,
                reasonDesc=reason_desc,
                brokerStatus=broker_status,
                settleAmount=settle_amount,
                settleDate=settle_date,
                commRate=comm_rate,
                brokerComm=broker_comm,
                userCommRate=user_comm_rate,
                userCommAmount=user_comm_amount,
                userFees=user_fees,
                miscFees=misc_fees,
                userNetMoney=user_net_money,
                principal=principal,
                routePrice=route_price,
            )
        except Exception as e:
            logger.warning(f"Error parsing route message for {seq}.{route_id}: {e}")
            return None

    def _msg_safe_int(self, msg, name: str, default: int = 0) -> int:
        try:
            if msg.hasElement(name):
                return msg.getElementAsInteger(name)
        except Exception:
            pass
        return default

    def _msg_safe_float(self, msg, name: str, default: float = 0.0) -> float:
        try:
            if msg.hasElement(name):
                return msg.getElementAsFloat(name)
        except Exception:
            pass
        return default

    def _msg_safe_str(self, msg, name: str, default: str = "") -> str:
        try:
            if msg.hasElement(name):
                return msg.getElementAsString(name)
        except Exception:
            pass
        return default

    @staticmethod
    def _format_strategy_time(raw: int) -> str:
        """Convert Bloomberg strategy time integer to HH:MM string.

        Bloomberg encodes strategy start/end times as integers in HHMM format
        (e.g. 930 = 09:30, 1600 = 16:00) or as seconds from midnight.
        Returns empty string for 0 (unset).
        """
        if not raw or raw <= 0:
            return ""
        # If value looks like seconds from midnight (> 2400), convert
        if raw > 2400:
            h = raw // 3600
            m = (raw % 3600) // 60
        else:
            # HHMM format
            h = raw // 100
            m = raw % 100
        return f"{h:02d}:{m:02d}"

    # Mapping of Bloomberg exchange suffixes to trading currencies
    _EXCHANGE_CURRENCY_MAP = {
        "US": "USD", "UN": "USD", "UQ": "USD", "UW": "USD", "UA": "USD", "UP": "USD",
        "CT": "USD", "UF": "USD",
        "CN": "CAD", "CF": "CAD",
        "LN": "GBP", "LI": "GBP",
        "JP": "JPY", "JT": "JPY",
        "HK": "HKD",
        "CH": "CNY", "CS": "CNY", "CG": "CNY", "CI": "CNY", "C1": "CNY", "C2": "CNY",
        "SS": "CNY", "SZ": "CNY",
        "GR": "EUR", "GY": "EUR", "GF": "EUR",
        "FP": "EUR", "PA": "EUR",
        "IM": "EUR", "NA": "EUR", "SM": "EUR", "BB": "EUR",
        "SQ": "EUR", "PL": "EUR", "ID": "EUR", "GA": "EUR",
        "AU": "AUD", "AT": "AUD",
        "SP": "SGD", "SI": "SGD",
        "KS": "KRW", "KQ": "KRW",
        "TT": "TWD",
        "TB": "THB",
        "IJ": "IDR",
        "MK": "MYR",
        "PM": "PHP",
        "IN": "INR", "IB": "INR", "IS": "INR",
        "BZ": "BRL",
        "MM": "MXN",
        "NZ": "NZD",
        "ST": "SEK", "NO": "NOK", "DC": "DKK", "FH": "EUR",
        "SW": "CHF", "SE": "CHF",
        "SJ": "ZAR",
        "AB": "AED",
    }

    @classmethod
    def _derive_currency(cls, currency_pair: str, ticker: str) -> str:
        """Derive the **trading currency** of the security.

        EMSX_CURRENCY_PAIR is unreliable for this purpose because:
          - It may return the settlement/user currency ("USD") for non-USD securities.
          - It may return a 6-char pair code ("HKDUSD") which is not a valid 3-char ccy.
        Therefore we **prioritise the ticker exchange suffix** (always reliable for
        exchange-listed instruments) and only fall back to EMSX_CURRENCY_PAIR when
        the ticker cannot be resolved.

        Priority:
          1. Ticker exchange suffix → _EXCHANGE_CURRENCY_MAP  (most reliable)
          2. EMSX_CURRENCY_PAIR parsed intelligently               (fallback)
          3. Empty string                                           (last resort)
        """
        # ── Step 1: Ticker exchange suffix (most reliable) ──────────────
        ticker_ccy = ""
        parts = ticker.strip().split() if ticker else []
        if len(parts) >= 2:
            asset_types = ("EQUITY", "GOVT", "CORP", "COMDTY", "INDEX", "CURNCY", "PREF", "MTGE")
            exch_code = parts[-2].upper() if parts[-1].upper() in asset_types else parts[-1].upper()
            ticker_ccy = cls._EXCHANGE_CURRENCY_MAP.get(exch_code, "")

        if ticker_ccy:
            return ticker_ccy

        # ── Step 2: Parse EMSX_CURRENCY_PAIR ────────────────────────────
        if currency_pair:
            cp = currency_pair.strip()
            # Handle 6-char pair codes like "HKDUSD", "JPYUSD" → extract first 3 chars
            if len(cp) == 6 and cp[3:].upper() == "USD":
                return cp[:3].upper()            # "HKDUSD" → "HKD"
            if len(cp) == 6 and cp[:3].upper() == "USD":
                return cp[3:].upper()            # "USDHKD" → "HKD"
            # Handle slash-separated pairs
            if "/" in cp:
                parts_pair = [p.strip() for p in cp.split("/")]
                # Return the non-USD side, preferring first token
                for p in parts_pair:
                    if p.upper() != "USD" and len(p) == 3:
                        return p.upper()
                # Both sides might be the same or both USD — return first
                return parts_pair[0].upper() if parts_pair[0] else ""
            # Plain 3-char code (e.g. "HKD", "JPY", "USD")
            if len(cp) <= 3:
                return cp.upper()

        return ""

    @classmethod
    def _derive_exchange(cls, ticker: str) -> str:
        """Derive exchange code from Bloomberg ticker suffix (e.g., '7203 JP Equity' → 'JP')."""
        parts = ticker.strip().split() if ticker else []
        if len(parts) >= 2:
            asset_types = ("EQUITY", "GOVT", "CORP", "COMDTY", "INDEX", "CURNCY", "PREF", "MTGE")
            return parts[-2].upper() if parts[-1].upper() in asset_types else parts[-1].upper()
        return ""

    def _parse_order_message(self, msg, seq: int) -> Optional[Order]:
        """Parse an OrderRouteFields subscription message into an Order."""
        try:
            symbol  = self._msg_safe_str(msg, "EMSX_TICKER")
            qty     = self._msg_safe_int(msg, "EMSX_AMOUNT")
            filled  = self._msg_safe_int(msg, "EMSX_FILLED")
            remain  = qty - filled

            # Side
            raw_side = self._msg_safe_str(msg, "EMSX_SIDE") or self._msg_safe_int(msg, "EMSX_SIDE")
            side = self.SIDE_MAP.get(raw_side, "BUY") if raw_side else "BUY"

            # Status
            raw_status = self._msg_safe_str(msg, "EMSX_STATUS") or self._msg_safe_int(msg, "EMSX_STATUS")
            raw_status_key = str(raw_status).upper() if isinstance(raw_status, str) else raw_status
            status = self.STATUS_MAP.get(raw_status_key, None)
            if status is None:
                logger.warning(f"Unmapped EMSX_STATUS '{raw_status}' for seq={seq} — defaulting to NEW")
                status = "NEW"

            # Order type
            raw_type = self._msg_safe_str(msg, "EMSX_ORDER_TYPE", "LMT").upper()
            order_type_map = {
                "MKT": "MARKET", "MARKET": "MARKET",
                "LMT": "LIMIT",  "LIMIT": "LIMIT",
                "STP": "STOP",   "STOP": "STOP",
                "STPLMT": "STOP_LIMIT",
            }
            order_type = order_type_map.get(raw_type, "LIMIT")

            raw_price  = self._msg_safe_float(msg, "EMSX_LIMIT_PRICE")
            price      = raw_price if raw_price > 0 else None
            avg_price  = self._msg_safe_float(msg, "EMSX_AVG_PRICE") or None
            stop_price = self._msg_safe_float(msg, "EMSX_STOP_PRICE") or None

            tif_raw = self._msg_safe_str(msg, "EMSX_TIF", "DAY").upper()
            tif_map = {"DAY": "DAY", "GTC": "GTC", "IOC": "IOC", "FOK": "FOK", "GTX": "GTX", "GTD": "GTD"}
            tif = tif_map.get(tif_raw, "DAY")

            account   = self._msg_safe_str(msg, "EMSX_ACCOUNT")
            portfolio = self._msg_safe_str(msg, "EMSX_PORT_NAME")
            trader    = self._msg_safe_str(msg, "EMSX_TRADER")
            notes    = self._msg_safe_str(msg, "EMSX_NOTES") or None
            currency_pair = self._msg_safe_str(msg, "EMSX_CURRENCY_PAIR")
            currency = self._derive_currency(currency_pair, symbol)
            logger.info(f"Order {seq}: CURRENCY_PAIR='{currency_pair}' ticker='{symbol}' -> currency='{currency}'")
            exchange = self._msg_safe_str(msg, "EMSX_EXCHANGE")
            # Derive exchange from ticker suffix when Bloomberg returns empty EMSX_EXCHANGE
            if not exchange and symbol:
                exchange = self._derive_exchange(symbol)
            logger.info(f"Order {seq}: EMSX_EXCHANGE='{self._msg_safe_str(msg, 'EMSX_EXCHANGE')}' -> exchange='{exchange}'")

            custom_note1 = self._msg_safe_str(msg, "EMSX_CUSTOM_NOTE1")
            custom_note2 = self._msg_safe_str(msg, "EMSX_CUSTOM_NOTE2")
            custom_note3 = self._msg_safe_str(msg, "EMSX_CUSTOM_NOTE3")
            custom_note4 = self._msg_safe_str(msg, "EMSX_CUSTOM_NOTE4")
            custom_note5 = self._msg_safe_str(msg, "EMSX_CUSTOM_NOTE5")
            trader_notes = self._msg_safe_str(msg, "EMSX_TRADER_NOTES")
            exec_instruction = self._msg_safe_str(msg, "EMSX_EXEC_INSTRUCTION")
            strategy_type = self._msg_safe_str(msg, "EMSX_STRATEGY_TYPE")
            strategy_style = self._msg_safe_str(msg, "EMSX_STRATEGY_STYLE")
            strategy_part_rate_raw = self._msg_safe_float(msg, "EMSX_STRATEGY_PART_RATE1")
            strategy_part_rate = strategy_part_rate_raw if strategy_part_rate_raw > 0 else None
            strategy_start_time_raw = self._msg_safe_int(msg, "EMSX_STRATEGY_START_TIME", 0)
            strategy_start_time = self._format_strategy_time(strategy_start_time_raw)
            strategy_end_time_raw = self._msg_safe_int(msg, "EMSX_STRATEGY_END_TIME", 0)
            strategy_end_time = self._format_strategy_time(strategy_end_time_raw)
            percent_remain = self._msg_safe_float(msg, "EMSX_PERCENT_REMAIN") or None
            broker = self._msg_safe_str(msg, "EMSX_BROKER")
            trader_uuid = self._msg_safe_int(msg, "EMSX_TRAD_UUID", 0)
            day_avg_price = self._msg_safe_float(msg, "EMSX_DAY_AVG_PRICE") or None
            arrival_price_raw = self._msg_safe_float(msg, "EMSX_ARRIVAL_PRICE")
            arrival_price = arrival_price_raw if arrival_price_raw > 0 else None
            last_price_raw = self._msg_safe_float(msg, "EMSX_LAST_PRICE")
            last_price = last_price_raw if last_price_raw > 0 else None

            # (Terminal trader identity is computed on-demand from the full orders cache)

            # Compute derived fields
            pct_filled = round((filled / qty) * 100, 1) if qty > 0 else 0.0
            if any([custom_note1, custom_note2, custom_note3, custom_note4, custom_note5, trader_notes, notes, exec_instruction, strategy_type]):
                logger.debug(f"Order {seq}: STRAT='{strategy_type}' STYLE='{strategy_style}' RATE={strategy_part_rate_raw} TIME={strategy_start_time}-{strategy_end_time} NOTES='{notes}'")

            # Date: EMSX_DATE is YYYYMMDD integer, EMSX_TIME_STAMP is seconds from midnight
            emsx_date = self._msg_safe_int(msg, "EMSX_DATE")
            created_at = datetime.now().isoformat()
            if emsx_date > 0:
                try:
                    y = emsx_date // 10000
                    m = (emsx_date % 10000) // 100
                    d = emsx_date % 100
                    ts = self._msg_safe_int(msg, "EMSX_TIME_STAMP", 0)
                    h = ts // 3600
                    mn = (ts % 3600) // 60
                    s = ts % 60
                    created_at = datetime(y, m, d, h, mn, s).isoformat()
                except Exception:
                    pass

            return Order(
                id=str(seq),
                symbol=symbol,
                side=side,
                status=status,
                orderType=order_type,
                quantity=qty,
                filledQuantity=filled,
                remainingQuantity=remain,
                price=price,
                stopPrice=stop_price,
                avgPrice=avg_price,
                timeInForce=tif,
                account=account,
                portfolio=portfolio,
                trader=trader,
                createdAt=created_at,
                updatedAt=created_at,
                notes=notes,
                currency=currency,
                exchange=exchange,
                customNote1=custom_note1,
                customNote2=custom_note2,
                customNote3=custom_note3,
                customNote4=custom_note4,
                customNote5=custom_note5,
                traderNotes=trader_notes,
                execInstruction=exec_instruction,
                percentRemain=percent_remain,
                percentFilled=pct_filled,
                strategyType=strategy_type,
                strategyPartRate=strategy_part_rate,
                strategyStyle=strategy_style,
                strategyStartTime=strategy_start_time,
                strategyEndTime=strategy_end_time,
                broker=broker,
                traderUuid=trader_uuid,
                dayAvgPrice=day_avg_price,
                arrivalPrice=arrival_price,
                lastPrice=last_price,
            )
        except Exception as e:
            logger.warning(f"Error parsing order message for seq={seq}: {e}")
            return None

    # ------------------------------------------------------------------
    # Real-time market data via //blp/mktdata subscriptions
    # ------------------------------------------------------------------
    # Unlike //blp/refdata (request/response, has DAILY_CAPACITY_REACHED limit),
    # //blp/mktdata uses streaming subscriptions with no daily capacity limit.
    # Data updates in real-time with every market tick — same as %Filled, Avg Px.
    # ------------------------------------------------------------------

    def _mktdata_subscription_loop(self):
        """Background thread: manage //blp/mktdata subscriptions and process updates.

        Subscribes to CHG_PCT_1D, VOLUME_AVG_5D, VWAP for all order tickers.
        FX rates are fetched via //blp/refdata every 5 min. Trading currencies via CRNCY refdata.
        Automatically adds new subscriptions when new tickers appear in the order cache.
        """
        sess = self._mktdata_session
        if not sess or not self._mktdata_connected:
            logger.warning("Mktdata session not available — market data enrichment disabled")
            return

        logger.info("Mktdata subscription loop started")
        self._fx_rates["USD"] = 1.0

        # Wait briefly for EMSX orders to populate before first subscription
        self._stop_event.wait(3)

        while not self._stop_event.is_set():
            try:
                self._update_mktdata_subscriptions(sess)
            except Exception as e:
                logger.warning(f"Error updating mktdata subscriptions: {e}")

            # Periodic FX rate refresh via //blp/refdata (every 5 min)
            try:
                self._maybe_refresh_fx_rates(sess)
            except Exception as e:
                logger.warning(f"Error refreshing FX rates: {e}")

            # Query //blp/refdata CRNCY for new tickers (authoritative currency source)
            try:
                self._maybe_query_ticker_currencies(sess)
            except Exception as e:
                logger.warning(f"Error querying ticker currencies: {e}")

            # Query //blp/refdata PX_ROUND_LOT_SIZE for new tickers (odd lot detection)
            try:
                self._maybe_query_round_lot_sizes(sess)
            except Exception as e:
                logger.warning(f"Error querying round lot sizes: {e}")

            # Process events from mktdata session
            try:
                event = sess.nextEvent(2000)
                etype = event.eventType()

                if etype == blpapi.Event.SUBSCRIPTION_DATA:
                    for msg in event:
                        try:
                            self._process_mktdata_message(msg)
                        except Exception as e:
                            logger.debug(f"Error processing mktdata message: {e}")

                elif etype == blpapi.Event.SUBSCRIPTION_STATUS:
                    batch_failures = []
                    batch_started = []
                    for msg in event:
                        mtype = str(msg.messageType())
                        cid_val = str(msg.correlationIds()[0].value()) if msg.correlationIds() else None
                        if "SubscriptionFailure" in mtype or "SubscriptionTerminated" in mtype:
                            if cid_val:
                                self._mktdata_failed_tickers.add(cid_val)
                                self._mktdata_active_tickers.discard(cid_val)
                            # Extract failure reason from Bloomberg API
                            failure_reason = ""
                            try:
                                if msg.hasElement("reason"):
                                    reason = msg.getElement("reason")
                                    if reason.hasElement("description"):
                                        failure_reason = str(reason.getElement("description").getValue())
                                    elif reason.hasElement("source"):
                                        failure_reason = str(reason.getElement("source").getValue())
                            except Exception:
                                pass
                            batch_failures.append((cid_val or "unknown", failure_reason))
                        elif "SubscriptionStarted" in mtype:
                            if cid_val:
                                self._mktdata_active_tickers.add(cid_val)
                                self._mktdata_failed_tickers.discard(cid_val)
                            batch_started.append(cid_val or "unknown")
                    # Batch-log to reduce noise
                    if batch_started:
                        logger.info(f"Mktdata subscriptions started: {len(batch_started)} ({batch_started[:5]}{'...' if len(batch_started) > 5 else ''})")
                    if batch_failures:
                        failure_details = [(t, r) for t, r in batch_failures[:3]]
                        logger.warning(f"Mktdata subscription failures: {len(batch_failures)} ({failure_details}). Will retry in {self._mktdata_retry_interval}s.")

                elif etype in (blpapi.Event.PARTIAL_RESPONSE, blpapi.Event.RESPONSE):
                    # Handle //blp/refdata responses (FX rate + CRNCY queries + Round Lot)
                    for msg in event:
                        try:
                            cid = msg.correlationIds()[0] if msg.correlationIds() else None
                            cid_val = str(cid.value()) if cid else ""
                            if cid_val == "__crncy_refdata__":
                                self._process_crncy_refdata_response(msg)
                            elif cid_val == "__round_lot_refdata__":
                                self._process_round_lot_refdata_response(msg)
                            else:
                                self._process_fx_refdata_response(msg)
                        except Exception as e:
                            logger.debug(f"Error processing refdata response: {e}")
                    if etype == blpapi.Event.RESPONSE:
                        self._fx_refdata_pending = False
                        self._crncy_refdata_pending = False

                elif etype == blpapi.Event.SESSION_STATUS:
                    for msg in event:
                        mtype = str(msg.messageType())
                        if "SessionTerminated" in mtype:
                            logger.error("Mktdata session terminated")
                            self._mktdata_connected = False
                            return

                elif etype == blpapi.Event.TIMEOUT:
                    pass  # normal

            except Exception as e:
                logger.debug(f"Mktdata event loop error: {e}")

        logger.info("Mktdata subscription loop stopped")

    def _update_mktdata_subscriptions(self, sess):
        """Add mktdata subscriptions for any new tickers in the order cache.
        FX rates are handled separately via hourly //blp/refdata requests.
        Also retries failed subscriptions periodically (e.g., after DAILY_CAPACITY_REACHED resets).
        """
        # Collect current tickers from order cache
        current_tickers = {o.symbol for o in self._orders.values() if o.symbol}
        
        # Diagnostic: Check specific tickers
        for check_ticker in ["UU/ LN Equity", "SVT LN Equity", "GLEN LN Equity"]:
            if check_ticker in current_tickers:
                in_subscribed = check_ticker in self._mktdata_subscribed_tickers
                in_failed = check_ticker in self._mktdata_failed_tickers
                logger.info(f"[MKTDATA CHECK] {check_ticker}: in_cache=True, subscribed={in_subscribed}, failed={in_failed}")

        new_tickers = current_tickers - self._mktdata_subscribed_tickers

        # Periodically retry failed subscriptions (capacity may have reset)
        now = datetime.now()
        retry_tickers: set = set()
        if self._mktdata_failed_tickers:
            if self._mktdata_last_retry is None or (now - self._mktdata_last_retry).total_seconds() >= self._mktdata_retry_interval:
                retry_tickers = self._mktdata_failed_tickers.copy()
                self._mktdata_last_retry = now
                if retry_tickers:
                    logger.info(f"Retrying {len(retry_tickers)} failed ticker subscriptions")

        all_new_tickers = new_tickers | retry_tickers

        if not all_new_tickers:
            return

        sub_list = blpapi.SubscriptionList()

        # Subscribe to market data fields for new equity tickers
        for ticker in all_new_tickers:
            cid = blpapi.CorrelationId(ticker)  # use ticker string as CID for easy lookup
            sub_list.add(
                topic=f"//blp/mktdata/{ticker}",
                fields=["CHG_PCT_1D", "VOLUME_AVG_5D", "VWAP", "PX_ROUND_LOT_SIZE"],
                correlationId=cid,
            )
        logger.info(f"Subscribing mktdata for {len(all_new_tickers)} tickers: {sorted(all_new_tickers)[:10]}{'...' if len(all_new_tickers) > 10 else ''}")
        self._mktdata_subscribed_tickers.update(all_new_tickers)

        try:
            sess.subscribe(sub_list)
            # Clear retried items from failed sets (will be re-added if they fail again)
            self._mktdata_failed_tickers -= retry_tickers
            # Initialize retry timer on first subscription to avoid immediate retry
            if self._mktdata_last_retry is None:
                self._mktdata_last_retry = now
        except Exception as e:
            logger.warning(f"Failed to subscribe mktdata: {e}")

    def _process_mktdata_message(self, msg):
        """Process a single //blp/mktdata subscription message and update caches."""
        cid = msg.correlationId()
        if not cid:
            return
        topic = cid.value()  # ticker string
        if not isinstance(topic, str):
            return

        # Equity market data message
        ticker = topic
        try:
            if msg.hasElement("CHG_PCT_1D"):
                val = msg.getElementAsFloat("CHG_PCT_1D")
                self._price_changes[ticker] = val
            if msg.hasElement("VOLUME_AVG_5D"):
                val = msg.getElementAsFloat("VOLUME_AVG_5D")
                self._adv5d[ticker] = val
            if msg.hasElement("VWAP"):
                val = msg.getElementAsFloat("VWAP")
                self._mkt_vwap[ticker] = val
            if msg.hasElement("PX_ROUND_LOT_SIZE"):
                val = msg.getElementAsInteger("PX_ROUND_LOT_SIZE")
                self._round_lot_sizes[ticker] = val
                # Debug logging for specific symbols
                debug_symbols = {"COST", "DE", "GEV", "RS", "ZS", "ROP", "ORCL", "MSTR", "INTU", 
                                "HUBS", "ADBE", "MPWR", "VRSN", "IT", "IBM", "ZBRA", "TDY", 
                                "MSI", "CHTR", "SPY", "AVGO", "PH", "ETN", "V", "PG", "WMT", "PEP", "KO", "XOM"}
                ticker_base = ticker.split()[0] if " " in ticker else ticker
                if ticker_base in debug_symbols:
                    logger.info(f"[ROUND_LOT_MKTDATA] {ticker}: PX_ROUND_LOT_SIZE = {val}")
                else:
                    logger.debug(f"[ROUND_LOT] {ticker}: PX_ROUND_LOT_SIZE = {val}")
        except Exception as e:
            logger.debug(f"Error parsing mktdata for {ticker}: {e}")

    # ------------------------------------------------------------------
    # FX rate refresh via //blp/refdata (every 5 minutes, per currency pair)
    # ------------------------------------------------------------------

    def _maybe_refresh_fx_rates(self, sess):
        """Send a //blp/refdata request for FX rates if due (every _fx_refresh_interval seconds).
        Requests BOTH {ccy}USD Curncy AND USD{ccy} Curncy for full coverage — some
        Bloomberg FX pairs only exist in one direction (e.g. USDKRW but not KRWUSD).
        """
        if not self._refdata_service_available or self._fx_refdata_pending:
            return
        now = datetime.now()
        if self._fx_last_refresh is not None and (now - self._fx_last_refresh).total_seconds() < self._fx_refresh_interval:
            return
        # Collect currencies from BOTH order.currency AND authoritative _ticker_currencies
        currencies: set = set()
        for o in self._orders.values():
            if o.currency and o.currency != "USD" and len(o.currency) == 3:
                currencies.add(o.currency)
        for ccy in self._ticker_currencies.values():
            if ccy and ccy != "USD" and len(ccy) == 3:
                currencies.add(ccy)
        if not currencies:
            return
        try:
            svc = sess.getService("//blp/refdata")
            req = svc.createRequest("ReferenceDataRequest")
            securities = req.getElement("securities")
            for ccy in sorted(currencies):
                securities.appendValue(f"{ccy}USD Curncy")   # e.g. AUDUSD Curncy
                securities.appendValue(f"USD{ccy} Curncy")   # e.g. USDKRW Curncy (inverse)
            fields = req.getElement("fields")
            fields.appendValue("PX_LAST")
            sess.sendRequest(req, correlationId=self._fx_refdata_cid)
            self._fx_refdata_pending = True
            self._fx_last_refresh = now
            logger.info(f"Sent FX refdata request for {len(currencies)} currencies: {sorted(currencies)}")
        except Exception as e:
            logger.warning(f"Failed to send FX refdata request: {e}")

    def _maybe_query_ticker_currencies(self, sess):
        """Query //blp/refdata CRNCY field for new tickers to get authoritative trading currency."""
        if not self._refdata_service_available or self._crncy_refdata_pending:
            return
        new_tickers = {o.symbol for o in self._orders.values() if o.symbol} - self._crncy_queried_tickers
        if not new_tickers:
            return
        try:
            svc = sess.getService("//blp/refdata")
            req = svc.createRequest("ReferenceDataRequest")
            securities = req.getElement("securities")
            for t in sorted(new_tickers):
                securities.appendValue(t)
            fields = req.getElement("fields")
            fields.appendValue("CRNCY")
            sess.sendRequest(req, correlationId=self._crncy_refdata_cid)
            self._crncy_refdata_pending = True
            self._crncy_queried_tickers |= new_tickers
            logger.info(f"Sent CRNCY refdata request for {len(new_tickers)} tickers")
        except Exception as e:
            logger.warning(f"Failed to send CRNCY refdata request: {e}")

    def _process_fx_refdata_response(self, msg):
        """Process a //blp/refdata response containing FX PX_LAST values.
        Handles both {ccy}USD Curncy (direct) and USD{ccy} Curncy (inverted) formats.
        
        Strategy: collect BOTH direct and inverse rates, then for each currency
        prefer the inverse rate (USD{ccy}) because Bloomberg's {ccy}USD Curncy
        returns per-100 or per-1000 rates for some EM currencies (KRW, IDR, etc.).
        USD{ccy} Curncy always returns the standard spot rate.
        """
        try:
            if not msg.hasElement("securityData"):
                return
            sd = msg.getElement("securityData")
            direct_rates = {}   # from {ccy}USD Curncy
            inverse_rates = {}  # from USD{ccy} Curncy → 1/rate
            for i in range(sd.numValues()):
                entry = sd.getValueAsElement(i)
                sec = entry.getElementAsString("security")  # e.g. "AUDUSD Curncy" or "USDKRW Curncy"
                if entry.hasElement("fieldData"):
                    fd = entry.getElement("fieldData")
                    if fd.hasElement("PX_LAST"):
                        rate = fd.getElementAsFloat("PX_LAST")
                        if rate > 0:
                            pair = sec.replace(" Curncy", "").strip()
                            # Direct format: {ccy}USD → e.g. "AUDUSD" (1 AUD = 0.71 USD)
                            if pair.endswith("USD") and len(pair) == 6:
                                ccy_code = pair[:3]
                                direct_rates[ccy_code] = rate
                            # Inverse format: USD{ccy} → e.g. "USDKRW" (1 USD = 1430 KRW)
                            elif pair.startswith("USD") and len(pair) == 6:
                                ccy_code = pair[3:]
                                inverse_rates[ccy_code] = 1.0 / rate
                else:
                    logger.debug(f"FX: no fieldData for {sec} (security may not exist)")
            
            # Merge: start with direct rates, then let inverse OVERRIDE
            # (inverse is more reliable for EM currencies like KRW, IDR)
            all_ccys = set(direct_rates.keys()) | set(inverse_rates.keys())
            updated = 0
            for ccy in all_ccys:
                if ccy in inverse_rates:
                    new_rate = inverse_rates[ccy]
                elif ccy in direct_rates:
                    new_rate = direct_rates[ccy]
                else:
                    continue
                old_rate = self._fx_rates.get(ccy)
                self._fx_rates[ccy] = new_rate
                updated += 1
                # Log discrepancies between direct and inverse
                if ccy in direct_rates and ccy in inverse_rates:
                    d, inv = direct_rates[ccy], inverse_rates[ccy]
                    ratio = d / inv if inv > 0 else 0
                    if abs(ratio - 1.0) > 0.02:  # >2% discrepancy
                        logger.warning(f"FX {ccy}: direct={d:.6f} vs inverse={inv:.6f} (ratio={ratio:.2f}x) — using inverse")
            
            if updated:
                logger.info(f"FX rates updated: {updated} currencies — {dict(sorted(self._fx_rates.items()))}")
        except Exception as e:
            logger.warning(f"Error processing FX refdata response: {e}")

    def _process_crncy_refdata_response(self, msg):
        """Process a //blp/refdata response containing CRNCY (trading currency) per ticker."""
        try:
            if not msg.hasElement("securityData"):
                return
            sd = msg.getElement("securityData")
            updated = 0
            for i in range(sd.numValues()):
                entry = sd.getValueAsElement(i)
                sec = entry.getElementAsString("security")
                if entry.hasElement("fieldData"):
                    fd = entry.getElement("fieldData")
                    if fd.hasElement("CRNCY"):
                        crncy = fd.getElementAsString("CRNCY").strip().upper()
                        if crncy and len(crncy) == 3:
                            old = self._ticker_currencies.get(sec)
                            self._ticker_currencies[sec] = crncy
                            # Also patch the order's currency in-place if it was wrong
                            for o in self._orders.values():
                                if o.symbol == sec and o.currency != crncy:
                                    logger.info(f"CRNCY override: order {o.id} ({sec}) currency '{o.currency}' → '{crncy}'")
                                    o.currency = crncy
                            updated += 1
            if updated:
                # Force an immediate FX rate refresh to cover newly-discovered currencies
                self._fx_last_refresh = None
                sample = dict(list(sorted(self._ticker_currencies.items()))[:10])
                logger.info(f"CRNCY updated: {updated} tickers (sample: {sample})")
        except Exception as e:
            logger.warning(f"Error processing CRNCY refdata response: {e}")

    def _maybe_query_round_lot_sizes(self, sess):
        """Query //blp/refdata PX_ROUND_LOT_SIZE field for new tickers (like BDP function).
        
        This fetches the round lot size once per ticker using ReferenceDataRequest,
        similar to the Excel formula =BDP("ticker","PX_ROUND_LOT_SIZE").
        The data is cached and not refreshed (assumed static for the trading day).
        """
        if not self._refdata_service_available:
            logger.warning("[ROUND_LOT] Skipping: refdata service not available")
            return
        if self._round_lot_refdata_pending:
            logger.debug("[ROUND_LOT] Skipping: previous request still pending")
            return
        
        # Get tickers from configured odd lot markets that haven't been queried yet
        target_tickers = set()
        odd_lot_markets = set(settings.ODD_LOT_MARKETS)
        for o in self._orders.values():
            if o.symbol and o.exchange and o.exchange.upper() in odd_lot_markets:
                if o.symbol not in self._round_lot_queried_tickers:
                    target_tickers.add(o.symbol)
        
        if target_tickers:
            logger.info(f"[ROUND_LOT] Found {len(target_tickers)} new tickers to query for markets {sorted(odd_lot_markets)} (total orders: {len(self._orders)}, queried: {len(self._round_lot_queried_tickers)})")
            sample = sorted(list(target_tickers))[:5]
            logger.info(f"[ROUND_LOT] Sample tickers to query: {sample}")
        elif len(self._orders) > 0 and len(self._round_lot_queried_tickers) == 0:
            # No target tickers but we have orders - log for debugging
            exchanges = {}
            for o in self._orders.values():
                exch = o.exchange or "None"
                exchanges[exch] = exchanges.get(exch, 0) + 1
            logger.info(f"[ROUND_LOT] No target tickers for markets {sorted(odd_lot_markets)}. Exchange distribution: {exchanges}")
        
        if not target_tickers:
            return
        
        # Limit batch size to avoid request too large
        batch_size = 50
        tickers_to_query = sorted(list(target_tickers))[:batch_size]
        
        try:
            svc = sess.getService("//blp/refdata")
            req = svc.createRequest("ReferenceDataRequest")
            securities = req.getElement("securities")
            for t in tickers_to_query:
                securities.appendValue(t)
            fields = req.getElement("fields")
            fields.appendValue("PX_ROUND_LOT_SIZE")
            sess.sendRequest(req, correlationId=self._round_lot_refdata_cid)
            self._round_lot_refdata_pending = True
            self._round_lot_queried_tickers.update(tickers_to_query)
            logger.info(f"Sent PX_ROUND_LOT_SIZE refdata request for {len(tickers_to_query)} tickers: {tickers_to_query[:5]}...")
        except Exception as e:
            logger.warning(f"Failed to send round lot refdata request: {e}")

    def _process_round_lot_refdata_response(self, msg):
        """Process a //blp/refdata response containing PX_ROUND_LOT_SIZE per ticker."""
        try:
            self._round_lot_refdata_pending = False
            if not msg.hasElement("securityData"):
                return
            sd = msg.getElement("securityData")
            updated = 0
            for i in range(sd.numValues()):
                entry = sd.getValueAsElement(i)
                sec = entry.getElementAsString("security")
                if entry.hasElement("fieldData"):
                    fd = entry.getElement("fieldData")
                    if fd.hasElement("PX_ROUND_LOT_SIZE"):
                        round_lot = fd.getElementAsInteger("PX_ROUND_LOT_SIZE")
                        if round_lot > 0:
                            self._round_lot_sizes[sec] = round_lot
                            updated += 1
                            logger.info(f"[ROUND_LOT_BDP] {sec}: PX_ROUND_LOT_SIZE = {round_lot}")
                    else:
                        # Field not available — mark as unknown (sentinel -1)
                        self._round_lot_sizes[sec] = -1
                        logger.info(f"[ROUND_LOT_BDP] {sec}: PX_ROUND_LOT_SIZE not available, marked as unknown")
                else:
                    # No field data — mark as unknown (sentinel -1)
                    self._round_lot_sizes[sec] = -1
                    logger.info(f"[ROUND_LOT_BDP] {sec}: No field data, marked as unknown")
            if updated:
                sample = dict(list(sorted(self._round_lot_sizes.items()))[:10])
                logger.info(f"PX_ROUND_LOT_SIZE updated: {updated} tickers (total cached: {len(self._round_lot_sizes)})")
        except Exception as e:
            logger.warning(f"Error processing PX_ROUND_LOT_SIZE refdata response: {e}")

    # ------------------------------------------------------------------
    # Request/response helpers (for ModifyOrder, CancelOrder, etc.)
    # ------------------------------------------------------------------

    @property
    def _req_service(self) -> Service:
        """Return the request-dedicated service (or fallback to shared service)."""
        svc = self._request_service or self.service
        if not svc:
            raise HTTPException(503, "Bloomberg service not available")
        return svc

    def _send_request(self, request: Request) -> List[Message]:
        """Send a synchronous EMSX request and collect all response messages.
        
        Uses the dedicated _request_session to avoid nextEvent() races
        with the subscription thread on the main session.
        """
        req_session = self._request_session or self.session
        if not req_session or not self.connected:
            raise HTTPException(503, "Bloomberg not connected")

        cid = blpapi.CorrelationId()
        req_session.sendRequest(request, correlationId=cid)

        messages: List[Message] = []
        timeout_ms = settings.BLOOMBERG_TIMEOUT
        deadline = datetime.now().timestamp() * 1000 + timeout_ms

        while True:
            remaining = max(0, int(deadline - datetime.now().timestamp() * 1000))
            event = req_session.nextEvent(remaining)
            etype = event.eventType()

            if etype in (Event.PARTIAL_RESPONSE, Event.RESPONSE):
                for msg in event:
                    messages.append(msg)
                if etype == Event.RESPONSE:
                    break
            elif etype == Event.TIMEOUT:
                raise HTTPException(504, "Bloomberg request timed out")
            # Ignore subscription events that arrive in this event loop

        return messages

    async def _send_request_async(self, request: Request) -> List[Message]:
        """Async wrapper for _send_request — runs in thread pool to avoid blocking the event loop."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._send_request, request)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_orders(self, filters: Optional[OrderFilters] = None) -> List[Order]:
        """Return orders from the live subscription cache.
        
        Thread-safe: uses _data_lock when accessing shared caches.
        """
        if not await self.connect():
            raise HTTPException(503, "Failed to connect to Bloomberg")

        # Wait for initial paint to complete — but only when the cache is truly empty.
        # Bloomberg does not always send EVENT_STATUS=11 (INIT_PAINT_END); once we have
        # orders in cache we treat the snapshot as done.
        if not self._init_paint_done:
            with self._data_lock:
                order_count = len(self._orders)
            if order_count > 0:
                # Already have orders — mark done without waiting
                self._init_paint_done = True
                logger.info(f"INIT_PAINT inferred complete — {order_count} orders in cache")
            else:
                logger.info("Waiting for EMSX INIT_PAINT to complete...")
                # INCREASED: From 30 iterations (15s) to 60 iterations (30s)
                # This ensures we capture all orders from large order books
                for _ in range(60):
                    await asyncio.sleep(0.5)
                    with self._data_lock:
                        has_orders = len(self._orders) > 0
                        current_count = len(self._orders)
                    if self._init_paint_done or has_orders or self._subscription_failed:
                        # Additional check: wait a bit more to ensure we get all orders
                        if has_orders and not self._init_paint_done:
                            logger.info(f"Orders arriving: {current_count} so far, waiting for more...")
                            # Wait 2 more seconds to capture any trailing orders
                            await asyncio.sleep(2.0)
                        break
                with self._data_lock:
                    order_count = len(self._orders)
                if order_count > 0 and not self._init_paint_done:
                    self._init_paint_done = True
                    logger.info(f"INIT_PAINT inferred complete — {order_count} orders in cache")
                if not self._init_paint_done and not self._subscription_failed:
                    logger.warning("INIT_PAINT not complete after 30s — returning partial snapshot")
            if self._subscription_failed:
                logger.warning("Subscription failed — returning stale/empty cache. Bloomberg EMSX may be reconnecting.")
                # Reset connected so next call triggers a fresh reconnect
                self.connected = False

        with self._data_lock:
            orders = list(self._orders.values())
        # Filter orders with a valid ticker (skip blank-symbol orphans from out-of-order updates)
        orders = [o for o in orders if o.symbol]
        logger.info(f"Returning {len(orders)} orders from subscription cache")

        # --- Diagnostic: log first 5 order currencies + CRNCY overrides ---
        for i, o in enumerate(orders[:5]):
            crncy = self._ticker_currencies.get(o.symbol, "?")
            logger.info(f"  order[{i}] id={o.id} symbol={o.symbol} derived_currency='{o.currency}' crncy_refdata='{crncy}'")

        # --- Diagnostic: log current FX rate cache ---
        fx_items = list(self._fx_rates.items())[:15]
        logger.info(f"  _fx_rates (first 15): {dict(fx_items)}")
        logger.info(f"  _ticker_currencies count: {len(self._ticker_currencies)}")

        # Enrichment data comes from real-time //blp/mktdata subscriptions — just read cached data.

        # Build order -> lastPrice map from route data (EMSX_LAST_PRICE is route-level only)
        # Thread-safe: copy routes data under lock
        order_last_prices: Dict[str, float] = {}
        with self._data_lock:
            routes_snapshot = list(self._routes.items())
        for rkey, route in routes_snapshot:
            if route.lastPrice and route.lastPrice > 0:
                seq_str = str(route.sequence)
                order_last_prices[seq_str] = route.lastPrice

        # Delegate enrichment to order projection service
        odd_lot_mkts = set(settings.ODD_LOT_MARKETS)
        enriched = enrich_orders(
            orders,
            price_changes=dict(self._price_changes),
            adv5d=dict(self._adv5d),
            mkt_vwap=dict(self._mkt_vwap),
            fx_rates=dict(self._fx_rates),
            ticker_currencies=dict(self._ticker_currencies),
            round_lot_sizes=dict(self._round_lot_sizes),
            order_last_prices=order_last_prices,
            odd_lot_markets=odd_lot_mkts,
            derive_exchange=self._derive_exchange,
        )

        # Save enriched data back to cache so future updates preserve calculated values
        with self._data_lock:
            for order in enriched:
                self._orders[order.id] = order
        orders = enriched

        # Client-side filtering via projection service
        if filters:
            orders = filter_orders(
                orders,
                filters,
                round_lot_sizes=dict(self._round_lot_sizes),
                odd_lot_markets=odd_lot_mkts,
            )

        return orders

    async def get_routes(self) -> List[dict]:
        """Return routes from the live subscription cache.
        
        Thread-safe: uses _data_lock when accessing shared caches.
        """
        if not await self.connect():
            raise HTTPException(503, "Failed to connect to Bloomberg")

        # Wait for route init paint (similar to order logic)
        if not self._route_init_paint_done:
            with self._data_lock:
                route_count = len(self._routes)
            if route_count > 0:
                self._route_init_paint_done = True
                logger.info(f"Route INIT_PAINT inferred complete — {route_count} routes in cache")
            else:
                logger.info("Waiting for Route INIT_PAINT to complete...")
                for _ in range(30):
                    await asyncio.sleep(0.5)
                    with self._data_lock:
                        has_routes = len(self._routes) > 0
                    if self._route_init_paint_done or has_routes:
                        break
                with self._data_lock:
                    route_count = len(self._routes)
                if route_count > 0 and not self._route_init_paint_done:
                    self._route_init_paint_done = True

        # Thread-safe: copy data under lock
        with self._data_lock:
            routes = list(self._routes.values())
            orders_snapshot = dict(self._orders)  # shallow copy for lookup
        logger.info(f"Returning {len(routes)} routes from subscription cache")

        # Delegate enrichment to route projection service
        return enrich_routes(routes, orders_snapshot, derive_exchange=self._derive_exchange)

    async def modify_order(self, order_id: str, field: str, value: Any) -> bool:
        """Modify a single EMSX order field via ModifyOrderEx request.
        
        Thread-safe: uses _data_lock when accessing order cache.
        """
        if not await self.connect():
            raise HTTPException(503, "Bloomberg not connected")

        try:
            request = self._req_service.createRequest("ModifyOrderEx")
            request.set("EMSX_SEQUENCE", int(order_id))

            # ModifyOrderEx requires mandatory fields — try to read from cache
            with self._data_lock:
                cached = self._orders.get(order_id)
            if cached:
                request.set("EMSX_TICKER", cached.symbol)
                request.set("EMSX_AMOUNT", cached.quantity)
                request.set("EMSX_ORDER_TYPE", {"MARKET": "MKT", "LIMIT": "LMT", "STOP": "STP"}.get(cached.orderType, "LMT"))
                request.set("EMSX_TIF", cached.timeInForce)

            if field == "price":
                request.set("EMSX_LIMIT_PRICE", float(value))
            elif field == "quantity":
                request.set("EMSX_AMOUNT", int(value))
            elif field == "timeInForce":
                request.set("EMSX_TIF", str(value))
            else:
                raise ValueError(f"Unsupported field: {field}")

            messages = await self._send_request_async(request)
            for msg in messages:
                if "Error" in str(msg.messageType()):
                    raise HTTPException(400, self._msg_safe_str(msg, "ERROR_MESSAGE", "Modify rejected"))

            logger.info(f"Modified order {order_id}: {field}={value}")
            return True

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error modifying order {order_id}: {e}")
            raise HTTPException(500, f"Failed to modify order: {str(e)}")

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an EMSX order via CancelOrderEx request."""
        if not await self.connect():
            raise HTTPException(503, "Bloomberg not connected")

        try:
            request = self._req_service.createRequest("CancelOrderEx")
            request.getElement("EMSX_SEQUENCE").appendValue(int(order_id))

            messages = await self._send_request_async(request)
            for msg in messages:
                if "Error" in str(msg.messageType()):
                    raise HTTPException(400, self._msg_safe_str(msg, "ERROR_MESSAGE", "Cancel rejected"))

            logger.info(f"Cancelled order {order_id}")
            return True

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error cancelling order {order_id}: {e}")
            raise HTTPException(500, f"Failed to cancel order: {str(e)}")

    async def batch_update(self, request_data: BatchUpdateRequest) -> BatchUpdateResponse:
        """Batch update multiple orders."""
        updated = 0
        failed = []

        for order_id in request_data.orderIds:
            try:
                if request_data.field == "status" and request_data.value == "CANCELLED":
                    await self.cancel_order(order_id)
                else:
                    await self.modify_order(order_id, request_data.field, request_data.value)
                updated += 1
            except HTTPException as e:
                failed.append({"orderId": order_id, "reason": e.detail})
            except Exception as e:
                failed.append({"orderId": order_id, "reason": str(e)})
        
        success = len(failed) == 0
        message = f"Updated {updated} orders"
        if failed:
            message += f", {len(failed)} failed"
        
        logger.info(f"Batch update complete: {message}")
        
        return BatchUpdateResponse(
            success=success,
            updatedCount=updated,
            failedOrders=failed if failed else None,
            message=message
        )

    async def cancel_route(self, request_data: CancelRouteRequest) -> bool:
        """Cancel an EMSX route via CancelRouteEx request."""
        if not await self.connect():
            raise HTTPException(503, "Bloomberg not connected")

        try:
            request = self._req_service.createRequest("CancelRouteEx")
            request.set("EMSX_SEQUENCE", request_data.sequence)
            request.set("EMSX_ROUTE_ID", request_data.routeId)

            messages = await self._send_request_async(request)
            for msg in messages:
                if "Error" in str(msg.messageType()):
                    raise HTTPException(400, self._msg_safe_str(msg, "ERROR_MESSAGE", "Cancel route rejected"))

            logger.info(f"Cancelled route {request_data.routeId} for order {request_data.sequence}")
            return True

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error cancelling route {request_data.routeId}: {e}")
            raise HTTPException(500, f"Failed to cancel route: {str(e)}")

    async def modify_route(self, request_data: ModifyRouteRequest) -> bool:
        """Modify an EMSX route via ModifyRouteEx request.
        
        Thread-safe: uses _data_lock when accessing route cache.
        """
        if not await self.connect():
            raise HTTPException(503, "Bloomberg not connected")

        try:
            request = self._req_service.createRequest("ModifyRouteEx")
            request.set("EMSX_SEQUENCE", request_data.sequence)
            request.set("EMSX_ROUTE_ID", request_data.routeId)

            # Required fields - use current values from cache if not provided
            route_key = f"{request_data.sequence}.{request_data.routeId}"
            with self._data_lock:
                cached = self._routes.get(route_key)

            # Set amount (required)
            if request_data.amount is not None:
                request.set("EMSX_AMOUNT", request_data.amount)
            elif cached:
                request.set("EMSX_AMOUNT", cached.amount)
            else:
                raise HTTPException(400, "Amount is required for route modification")

            # Set order type (required)
            order_type = request_data.orderType or (cached.orderType if cached else "")
            if order_type:
                request.set("EMSX_ORDER_TYPE", order_type)
            else:
                raise HTTPException(400, "Order type is required for route modification")

            # Set TIF (required)
            tif = request_data.tif or (cached.tif if cached else "DAY")
            request.set("EMSX_TIF", tif)

            # Optional fields
            if request_data.limitPrice is not None:
                request.set("EMSX_LIMIT_PRICE", request_data.limitPrice)
            if request_data.stopPrice is not None:
                request.set("EMSX_STOP_PRICE", request_data.stopPrice)
            if request_data.broker:
                request.set("EMSX_BROKER", request_data.broker)
            if request_data.exchangeDestination:
                request.set("EMSX_EXCHANGE_DESTINATION", request_data.exchangeDestination)
            if request_data.notes:
                request.set("EMSX_NOTES", request_data.notes)

            # Strategy params — set EMSX_STRATEGY_PARAMS with proper field indicators
            if request_data.strategyParams:
                strategy_name = request_data.strategyParams.get("strategyName", "")
                fields_data = request_data.strategyParams.get("fields", [])
                if strategy_name and isinstance(fields_data, list):
                    strategy = request.getElement("EMSX_STRATEGY_PARAMS")
                    strategy.setElement("EMSX_STRATEGY_NAME", strategy_name)

                    indicator = strategy.getElement("EMSX_STRATEGY_FIELD_INDICATORS")
                    data = strategy.getElement("EMSX_STRATEGY_FIELDS")

                    for field_entry in fields_data:
                        value = field_entry.get("value", "")
                        disabled = field_entry.get("disabled", False)
                        data.appendElement().setElement("EMSX_FIELD_DATA", str(value) if not disabled else "")
                        indicator.appendElement().setElement("EMSX_FIELD_INDICATOR", 1 if disabled else 0)

            messages = await self._send_request_async(request)
            for msg in messages:
                if "Error" in str(msg.messageType()):
                    raise HTTPException(400, self._msg_safe_str(msg, "ERROR_MESSAGE", "Modify route rejected"))

            logger.info(f"Modified route {request_data.routeId} for order {request_data.sequence}")
            return True

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error modifying route {request_data.routeId}: {e}")
            raise HTTPException(500, f"Failed to modify route: {str(e)}")

    async def route_order(self, request_data: RouteOrderRequest) -> dict:
        """Route an order via RouteEx request.
        
        Creates a child route from a parent order for execution by a broker.
        Validates order status and trader ownership before routing.
        """
        logger.info(f"Routing order {request_data.orderId} to broker {request_data.broker}")
        if not await self.connect():
            raise HTTPException(503, "Bloomberg not connected")

        try:
            # Get parent order details
            with self._data_lock:
                parent_order = self._orders.get(request_data.orderId)
            
            if not parent_order:
                raise HTTPException(404, f"Order {request_data.orderId} not found")
            
            # Validate order status — only certain statuses are routable
            routable_statuses = {"NEW", "ASSIGN", "WORKING", "PARTIAL", "SENT", "QUEUED"}
            if parent_order.status not in routable_statuses:
                raise HTTPException(400, f"Order {request_data.orderId} has status '{parent_order.status}' — only orders with status {', '.join(sorted(routable_statuses))} can be routed")

            # Validate trader ownership — the current terminal trader must match the order's trader
            terminal_trader = self.get_terminal_trader_name()
            if terminal_trader and parent_order.trader and terminal_trader.upper() != parent_order.trader.upper():
                raise HTTPException(403, f"Cannot route order {request_data.orderId}: assigned to trader '{parent_order.trader}', but current trader is '{terminal_trader}'")

            # Validate remaining quantity
            if request_data.quantity > parent_order.remainingQuantity:
                raise HTTPException(400, f"Route quantity ({request_data.quantity}) exceeds remaining quantity ({parent_order.remainingQuantity})")

            # Create RouteEx request
            request = self._req_service.createRequest("RouteEx")
            
            # Mandatory fields
            request.set("EMSX_SEQUENCE", int(request_data.orderId))
            request.set("EMSX_TICKER", parent_order.symbol)
            request.set("EMSX_BROKER", request_data.broker)
            request.set("EMSX_AMOUNT", request_data.quantity)
            request.set("EMSX_ORDER_TYPE", request_data.orderType[:3].upper())  # LMT, MKT, STP
            request.set("EMSX_TIF", request_data.timeInForce)
            request.set("EMSX_HAND_INSTRUCTION", "ANY")
            
            # Optional fields
            if request_data.price is not None:
                request.set("EMSX_LIMIT_PRICE", request_data.price)
            if request_data.stopPrice is not None:
                request.set("EMSX_STOP_PRICE", request_data.stopPrice)
            if request_data.exchangeDestination:
                request.set("EMSX_EXCHANGE_DESTINATION", request_data.exchangeDestination)
            if request_data.notes:
                request.set("EMSX_NOTES", request_data.notes)

            # Strategy params — same handling as modify_route
            if request_data.strategyParams:
                strategy_name = request_data.strategyParams.get("strategyName", "")
                fields_data = request_data.strategyParams.get("fields", [])
                if strategy_name and isinstance(fields_data, list):
                    strategy = request.getElement("EMSX_STRATEGY_PARAMS")
                    strategy.setElement("EMSX_STRATEGY_NAME", strategy_name)

                    indicator = strategy.getElement("EMSX_STRATEGY_FIELD_INDICATORS")
                    data = strategy.getElement("EMSX_STRATEGY_FIELDS")

                    for field_entry in fields_data:
                        value = field_entry.get("value", "")
                        disabled = field_entry.get("disabled", False)
                        data.appendElement().setElement("EMSX_FIELD_DATA", str(value) if not disabled else "")
                        indicator.appendElement().setElement("EMSX_FIELD_INDICATOR", 1 if disabled else 0)

            messages = await self._send_request_async(request)
            
            route_id = None
            for msg in messages:
                if "Error" in str(msg.messageType()):
                    raise HTTPException(400, self._msg_safe_str(msg, "ERROR_MESSAGE", "Route order rejected"))
                # Extract route ID from response if available
                if msg.hasElement("EMSX_ROUTE_ID"):
                    route_id = msg.getElementAsInteger("EMSX_ROUTE_ID")

            logger.info(f"Created route for order {request_data.orderId} to broker {request_data.broker}, route_id: {route_id}")
            return {
                "success": True,
                "orderId": request_data.orderId,
                "routeId": route_id,
                "broker": request_data.broker,
                "quantity": request_data.quantity,
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error routing order {request_data.orderId}: {e}")
            raise HTTPException(500, f"Failed to route order: {str(e)}")

    async def get_broker_strategies(self, broker: str, asset_class: str = "EQTY") -> List[str]:
        """Get available strategies for a broker via GetBrokerStrategiesWithAssetClass."""
        logger.info(f"Getting broker strategies for {broker} ({asset_class})")
        if not await self.connect():
            logger.error(f"Bloomberg not connected - cannot get strategies for {broker}")
            raise HTTPException(503, f"Bloomberg not connected - last error: {self.last_error or 'Unknown'}")

        try:
            request = self._req_service.createRequest("GetBrokerStrategiesWithAssetClass")
            request.set("EMSX_BROKER", broker)
            request.set("EMSX_ASSET_CLASS", asset_class)

            messages = await self._send_request_async(request)
            strategies = []
            for msg in messages:
                if msg.hasElement("EMSX_STRATEGIES"):
                    strats_elem = msg.getElement("EMSX_STRATEGIES")
                    for i in range(strats_elem.numValues()):
                        strategies.append(strats_elem.getValueAsString(i))
                elif "Error" in str(msg.messageType()):
                    error_msg = self._msg_safe_str(msg, "ERROR_MESSAGE", "Failed to get broker strategies")
                    logger.warning(f"GetBrokerStrategies error for {broker}: {error_msg}")

            logger.info(f"Broker {broker} ({asset_class}): {len(strategies)} strategies found")
            return strategies

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting broker strategies for {broker}: {e}")
            raise HTTPException(500, f"Failed to get broker strategies: {str(e)}")

    async def get_broker_strategy_info(self, broker: str, strategy: str, asset_class: str = "EQTY") -> List[dict]:
        """Get strategy parameter info via GetBrokerStrategyInfoWithAssetClass."""
        logger.info(f"Getting strategy info for {broker}/{strategy} ({asset_class})")
        if not await self.connect():
            logger.error(f"Bloomberg not connected - cannot get strategy info for {broker}/{strategy}")
            raise HTTPException(503, f"Bloomberg not connected - last error: {self.last_error or 'Unknown'}")

        try:
            request = self._req_service.createRequest("GetBrokerStrategyInfoWithAssetClass")
            request.set("EMSX_BROKER", broker)
            request.set("EMSX_STRATEGY", strategy)
            request.set("EMSX_ASSET_CLASS", asset_class)
            
            logger.info(f"Sending GetBrokerStrategyInfoWithAssetClass request for {broker}/{strategy}")
            import time
            start_time = time.time()
            
            messages = await self._send_request_async(request)
            
            elapsed = time.time() - start_time
            logger.info(f"GetBrokerStrategyInfoWithAssetClass response received in {elapsed:.2f}s")
            
            fields = []
            for msg in messages:
                if msg.hasElement("EMSX_STRATEGY_INFO"):
                    info_elem = msg.getElement("EMSX_STRATEGY_INFO")
                    for i in range(info_elem.numValues()):
                        entry = info_elem.getValueAsElement(i)
                        field_name = entry.getElementAsString("FieldName") if entry.hasElement("FieldName") else ""
                        disable = entry.getElementAsString("Disable") if entry.hasElement("Disable") else "0"
                        string_value = entry.getElementAsString("StringValue") if entry.hasElement("StringValue") else ""
                        fields.append({
                            "fieldName": field_name,
                            "disable": disable,
                            "stringValue": string_value,
                        })
                elif "Error" in str(msg.messageType()):
                    error_msg = self._msg_safe_str(msg, "ERROR_MESSAGE", "Failed to get strategy info")
                    logger.warning(f"GetBrokerStrategyInfo error for {broker}/{strategy}: {error_msg}")

            logger.info(f"Broker {broker} strategy {strategy} ({asset_class}): {len(fields)} parameter fields")
            return fields

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting strategy info for {broker}/{strategy}: {e}")
            raise HTTPException(500, f"Failed to get broker strategy info: {str(e)}")

    async def get_brokers(self, asset_class: str = "EQTY") -> List[str]:
        """Get available brokers for an asset class via GetBrokersWithAssetClass."""
        logger.info(f"Getting brokers for asset class {asset_class}")
        if not await self.connect():
            logger.error(f"Bloomberg not connected - cannot get brokers")
            raise HTTPException(503, f"Bloomberg not connected - last error: {self.last_error or 'Unknown'}")

        try:
            request = self._req_service.createRequest("GetBrokersWithAssetClass")
            request.set("EMSX_ASSET_CLASS", asset_class)

            messages = await self._send_request_async(request)
            brokers = []
            for msg in messages:
                if msg.hasElement("EMSX_BROKERS"):
                    brokers_elem = msg.getElement("EMSX_BROKERS")
                    for i in range(brokers_elem.numValues()):
                        brokers.append(brokers_elem.getValueAsString(i))
                elif "Error" in str(msg.messageType()):
                    error_msg = self._msg_safe_str(msg, "ERROR_MESSAGE", "Failed to get brokers")
                    logger.warning(f"GetBrokers error: {error_msg}")

            logger.info(f"Found {len(brokers)} brokers for asset class {asset_class}")
            return brokers

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting brokers: {e}")
            raise HTTPException(500, f"Failed to get brokers: {str(e)}")

    def get_terminal_trader_name(self) -> str:
        """Return the terminal trader name.
        Priority: 1) EMSX_TRADER_NAME from config, 2) most common trader in order cache."""
        if settings.EMSX_TRADER_NAME:
            return settings.EMSX_TRADER_NAME
        # Fallback: most common trader in order cache (may be inaccurate on shared desks)
        votes: Dict[str, int] = {}
        for order in self._orders.values():
            t = order.trader
            if t:
                votes[t] = votes.get(t, 0) + 1
        if votes:
            best = max(votes, key=votes.get)
            logger.debug(f"Auto-detected trader (fallback): {best} with {votes[best]} orders")
            return best
        return ""

