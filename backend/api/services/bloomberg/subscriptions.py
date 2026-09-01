"""
Bloomberg EMSX Subscription Engine — extracted from bloomberg_adapter.py.

Manages EMSX order/route subscriptions: background thread, message parsing,
in-memory cache maintenance, cross-enrichment, and DB write-through.

Threading: owns one background thread (emsx-subscription). Uses _data_lock
(threading.RLock) for all cache mutations.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime
from typing import List, Optional, Dict, Any

import blpapi
from blpapi import Session

from schemas import Order, Route

from services.realtime_gateway import realtime_gw

from ._constants import ORDER_FIELDS, ROUTE_FIELDS, STATUS_MAP, SIDE_MAP
from .connection import BloombergConnectionManager
from .._bloomberg_parsing import (
    msg_safe_int, msg_safe_float, msg_safe_str,
    format_strategy_time, derive_currency, derive_exchange,
)

logger = logging.getLogger("main")


class EMSXSubscriptionEngine:
    def __init__(
        self,
        connection: BloombergConnectionManager,
        repo_provider: Any,
    ):
        self._connection = connection
        self._repo_provider = repo_provider

        self._orders: Dict[str, Order] = {}
        self._init_paint_done: bool = False

        self._routes: Dict[str, Route] = {}
        self._route_init_paint_done: bool = False

        self._last_order_api_seq_num: int = 0
        self._last_route_api_seq_num: int = 0

        self._subscription_failed: bool = False
        self._subscription_failed_at: Optional[datetime] = None

        self._sub_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        self._data_lock = threading.RLock()

    # ── Public properties (read access for other components) ───────────

    @property
    def orders(self) -> Dict[str, Order]:
        return self._orders

    @property
    def routes(self) -> Dict[str, Route]:
        return self._routes

    @property
    def init_paint_done(self) -> bool:
        return self._init_paint_done

    @init_paint_done.setter
    def init_paint_done(self, value: bool) -> None:
        self._init_paint_done = value

    @property
    def route_init_paint_done(self) -> bool:
        return self._route_init_paint_done

    @route_init_paint_done.setter
    def route_init_paint_done(self, value: bool) -> None:
        self._route_init_paint_done = value

    @property
    def subscription_failed(self) -> bool:
        return self._subscription_failed

    @subscription_failed.setter
    def subscription_failed(self, value: bool) -> None:
        self._subscription_failed = value

    @property
    def subscription_failed_at(self) -> Optional[datetime]:
        return self._subscription_failed_at

    @subscription_failed_at.setter
    def subscription_failed_at(self, value: Optional[datetime]) -> None:
        self._subscription_failed_at = value

    @property
    def data_lock(self) -> threading.RLock:
        return self._data_lock

    @property
    def stop_event(self) -> threading.Event:
        return self._stop_event

    # ── Lifecycle ──────────────────────────────────────────────────────

    def start(self):
        self._stop_event.clear()
        self._sub_thread = threading.Thread(
            target=self._subscription_loop,
            daemon=True,
            name="emsx-subscription",
        )
        self._sub_thread.start()
        logger.info("Started EMSX subscription thread")

    def stop(self):
        self._stop_event.set()
        if self._sub_thread and self._sub_thread.is_alive():
            self._sub_thread.join(timeout=5)
            if self._sub_thread.is_alive():
                logger.warning("EMSX subscription thread did not stop within timeout")

    def reset(self):
        with self._data_lock:
            self._subscription_failed = False
            self._subscription_failed_at = None
            self._init_paint_done = False
            self._orders = {}
            self._routes = {}
            self._route_init_paint_done = False
            self._last_order_api_seq_num = 0
            self._last_route_api_seq_num = 0

    # ── Subscription loop ──────────────────────────────────────────────

    def _subscription_loop(self):
        try:
            order_fields_str = ",".join(ORDER_FIELDS)
            order_topic = f"{self._connection.active_service_name}/order?fields={order_fields_str}"
            logger.info(f"Subscribing to: {order_topic}")

            route_fields_str = ",".join(ROUTE_FIELDS)
            route_topic = f"{self._connection.active_service_name}/route?fields={route_fields_str}"
            logger.info(f"Subscribing to: {route_topic}")

            order_cid = blpapi.CorrelationId(98)
            route_cid = blpapi.CorrelationId(99)

            session = self._connection.session
            order_sub_list = blpapi.SubscriptionList()
            order_sub_list.add(topic=order_topic, correlationId=order_cid)
            session.subscribe(order_sub_list)

            route_sub_list = blpapi.SubscriptionList()
            route_sub_list.add(topic=route_topic, correlationId=route_cid)
            session.subscribe(route_sub_list)

            while not self._stop_event.is_set():
                event = session.nextEvent(2000)
                etype = event.eventType()

                if etype == blpapi.Event.SUBSCRIPTION_DATA:
                    for msg in event:
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
                            self._subscription_failed = True
                            self._subscription_failed_at = datetime.now()
                            self._connection.connected = False
                            logger.warning(
                                f"Subscription failed for {self._connection.active_service_name}, "
                                "will retry with fallback service"
                            )
                            return

                elif etype == blpapi.Event.SESSION_STATUS:
                    for msg in event:
                        mtype = str(msg.messageType())
                        if "SessionTerminated" in mtype or "SessionStartupFailure" in mtype:
                            logger.error(f"Bloomberg session event: {mtype}")
                            try:
                                if msg.hasElement("reason"):
                                    reason = msg.getElement("reason")
                                    if reason.hasElement("description"):
                                        desc = reason.getElementAsString("description")
                                    else:
                                        desc = reason.getValueAsString()
                                    logger.error(f"Session error detail: {desc}")
                                    self._connection.last_error = desc
                            except Exception:
                                pass
                            self._connection.connected = False
                            return

                elif etype == blpapi.Event.ADMIN:
                    for msg in event:
                        mtype = str(msg.messageType())
                        if "SlowConsumerWarningCleared" in mtype:
                            logger.info("Bloomberg EMSX slow consumer warning cleared")
                        elif "SlowConsumerWarning" in mtype:
                            logger.warning("Bloomberg EMSX slow consumer warning raised")
                        else:
                            logger.info(f"Bloomberg EMSX ADMIN event: {mtype}")

                elif etype == blpapi.Event.TIMEOUT:
                    continue

        except Exception as e:
            logger.exception(f"Subscription loop error: {e}")
            self._connection.connected = False

    # ── Subscription message processing ────────────────────────────────

    def _process_subscription_message(self, msg):
        try:
            self._track_api_seq_num(msg, "order")

            event_status = self._msg_safe_int(msg, "EVENT_STATUS", -1)
            seq = self._msg_safe_int(msg, "EMSX_SEQUENCE", 0)
            if seq == 0:
                if event_status == 11:
                    with self._data_lock:
                        order_count = len(self._orders)
                        self._init_paint_done = True
                    logger.warning(f"INIT_PAINT complete (control msg) — {order_count} orders loaded")
                return

            seq_key = str(seq)

            # ── 诊断日志：追踪目标订单序列号的消息 ──────────────
            _TRACE_SEQS = {4926854, 5190560}
            if seq in _TRACE_SEQS:
                ticker = self._msg_safe_str(msg, "EMSX_TICKER")
                status = self._msg_safe_str(msg, "EMSX_STATUS") or self._msg_safe_int(msg, "EMSX_STATUS")
                amount = self._msg_safe_int(msg, "EMSX_AMOUNT")
                logger.warning(
                    "TRACE_ORDER: seq=%d seq_key='%s' event_status=%d ticker='%s' status=%s amount=%d init_paint_done=%s cached=%s",
                    seq, seq_key, event_status, ticker, status, amount,
                    self._init_paint_done, seq_key in self._orders,
                )
            # ───────────────────────────────────────────────────

            if event_status == 8:
                deleted_order = None
                with self._data_lock:
                    if seq_key in self._orders:
                        deleted_order = self._orders[seq_key]
                        del self._orders[seq_key]
                        logger.debug(f"Deleted order {seq_key}")
                # 向前端广播删除事件，避免 stream store 保留已删除订单
                if deleted_order:
                    try:
                        loop = asyncio.get_event_loop()
                        asyncio.run_coroutine_threadsafe(
                            realtime_gw.broadcast_order(deleted_order.model_dump(), event_type="delete"),
                            loop,
                        )
                    except RuntimeError:
                        pass
                return

            if event_status == 11:
                with self._data_lock:
                    order_count = len(self._orders)
                    self._init_paint_done = True
                logger.warning(f"INIT_PAINT complete — {order_count} orders loaded")
                return

            order = self._parse_order_message(msg, seq)
            if not order:
                logger.warning(f"Failed to parse order for seq={seq}, event_status={event_status}")
                return

            with self._data_lock:
                if event_status == 7 and seq_key in self._orders:
                    cached = self._orders[seq_key]
                    merged = Order(
                        id=cached.id,
                        symbol=order.symbol or cached.symbol,
                        side=order.side if self._msg_safe_str(msg, "EMSX_SIDE") else cached.side,
                        orderType=order.orderType if self._msg_safe_str(msg, "EMSX_ORDER_TYPE") else cached.orderType,
                        account=order.account or cached.account,
                        portfolio=order.portfolio or cached.portfolio,
                        trader=order.trader or cached.trader,
                        exchange=order.exchange or cached.exchange,
                        currency=order.currency if self._msg_safe_str(msg, "EMSX_CURRENCY_PAIR") else cached.currency,
                        createdAt=cached.createdAt,
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
                        basketName=order.basketName or cached.basketName,
                        basketNum=order.basketNum if order.basketNum is not None else cached.basketNum,
                        dollarValueUsd=order.dollarValueUsd if order.dollarValueUsd is not None else cached.dollarValueUsd,
                        adv5d=cached.adv5d,
                        mktVwap=cached.mktVwap,
                        pctChange=cached.pctChange,
                    )
                    self._orders[seq_key] = merged
                    logger.debug(f"Order update (7): {seq_key} {merged.symbol} -> {merged.status}")
                elif event_status == 7:
                    # 订UPDATE消息包含完整字段，即使缓存中无基础数据也直接入库。
                    # 避免因 INIT_PAINT 消息被错过而导致订单永远不进入缓存。
                    self._orders[seq_key] = order
                    logger.warning(
                        "订单 %s 首次通过 UPDATE 消息入库（INIT_PAINT 消息可能被错过），symbol='%s' status=%s",
                        seq_key, order.symbol, order.status,
                    )
                    self._enrich_routes_with_new_order(order)
                else:
                    self._orders[seq_key] = order
                    if event_status == 4:
                        logger.debug(f"INIT_PAINT order: {seq_key} {order.symbol} {order.side} {order.status}")
                        if len(self._orders) <= 3:
                            logger.warning(
                                f"INIT_PAINT order #{len(self._orders)}: seq={seq_key} "
                                f"symbol='{order.symbol}' exchange='{order.exchange}' side={order.side}"
                            )
                    elif event_status == 6:
                        logger.debug(f"New order (6): {seq_key} {order.symbol} {order.side} {order.status}")
                    self._enrich_routes_with_new_order(order)

            final_order = self._orders.get(seq_key)
            if final_order and self._repo_provider and self._repo_provider.is_active:
                self._schedule_persist_order(final_order)

        except Exception as e:
            logger.warning(f"Error processing subscription message: {e}")

    def _process_route_message(self, msg):
        try:
            self._track_api_seq_num(msg, "route")

            event_status = self._msg_safe_int(msg, "EVENT_STATUS", -1)
            seq = self._msg_safe_int(msg, "EMSX_SEQUENCE", 0)
            route_id = self._msg_safe_int(msg, "EMSX_ROUTE_ID", 0)
            if seq == 0 or route_id == 0:
                if event_status == 11:
                    with self._data_lock:
                        route_count = len(self._routes)
                        self._route_init_paint_done = True
                    logger.info(f"Route INIT_PAINT complete — {route_count} routes loaded")
                return

            route_key = f"{seq}.{route_id}"

            if event_status == 8:
                deleted_route = None
                with self._data_lock:
                    if route_key in self._routes:
                        deleted_route = self._routes[route_key]
                        del self._routes[route_key]
                        logger.debug(f"Deleted route {route_key}")
                # 向前端广播路由删除事件，保持订单/路由一致性
                if deleted_route:
                    try:
                        loop = asyncio.get_event_loop()
                        asyncio.run_coroutine_threadsafe(
                            realtime_gw.broadcast_route(deleted_route.model_dump(), event_type="delete"),
                            loop,
                        )
                    except RuntimeError:
                        pass
                return

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
                        cached = self._routes[route_key]
                        update_dict = {}
                        for field_name in route.model_fields:
                            new_val = getattr(route, field_name)
                            cached_val = getattr(cached, field_name)
                            if new_val is not None and new_val != "" and new_val != 0:
                                update_dict[field_name] = new_val
                            elif cached_val is not None and cached_val != "" and cached_val != 0:
                                update_dict[field_name] = cached_val

                        enrichment_fields = ["ticker", "side", "portfolio", "trader", "traderUuid", "currency", "exchange"]
                        for ef in enrichment_fields:
                            cached_ef_val = getattr(cached, ef, None)
                            if cached_ef_val is not None and cached_ef_val != "" and cached_ef_val != 0:
                                update_dict[ef] = cached_ef_val

                        update_dict["id"] = route_key
                        update_dict["routeId"] = route_id
                        update_dict["sequence"] = seq
                        raw_status = self._msg_safe_str(msg, "EMSX_STATUS")
                        if raw_status:
                            update_dict["status"] = raw_status
                        self._routes[route_key] = Route(**update_dict)
                        logger.debug(
                            f"Route update (7): {route_key} -> {self._routes[route_key].status}, "
                            f"enrichment: ticker='{update_dict.get('ticker','')}', "
                            f"exchange='{update_dict.get('exchange','')}'"
                        )
                    elif event_status == 7:
                        # Route UPDATE 消息包含完整字段，即使缓存中无基础数据也直接入库
                        self._routes[route_key] = route
                        self._enrich_route_from_parent(route_key, route)
                        logger.warning(
                            "Route %s 首次通过 UPDATE 消息入库（INIT_PAINT 消息可能被错过），broker='%s' status=%s",
                            route_key, route.broker, route.status,
                        )
                    else:
                        self._routes[route_key] = route
                        self._enrich_route_from_parent(route_key, route)
                        if event_status == 4:
                            logger.debug(f"INIT_PAINT route: {route_key} {route.broker} {route.status}")
                        elif event_status == 6:
                            logger.debug(f"New route (6): {route_key} {route.broker} {route.status}")

                final_route = self._routes.get(route_key)
                if final_route and self._repo_provider and self._repo_provider.is_active:
                    self._schedule_persist_route(final_route)

        except Exception as e:
            logger.warning(f"Error processing route message: {e}")

    # ── Order parsing ──────────────────────────────────────────────────

    def _parse_order_message(self, msg, seq: int) -> Optional[Order]:
        try:
            symbol = self._msg_safe_str(msg, "EMSX_TICKER")
            qty = self._msg_safe_int(msg, "EMSX_AMOUNT")
            filled = self._msg_safe_int(msg, "EMSX_FILLED")
            remain = qty - filled

            raw_side = self._msg_safe_str(msg, "EMSX_SIDE") or self._msg_safe_int(msg, "EMSX_SIDE")
            side = SIDE_MAP.get(raw_side, "BUY") if raw_side else "BUY"

            raw_status = self._msg_safe_str(msg, "EMSX_STATUS") or self._msg_safe_int(msg, "EMSX_STATUS")
            raw_status_key = str(raw_status).upper() if isinstance(raw_status, str) else raw_status
            status = STATUS_MAP.get(raw_status_key, None)
            if status is None:
                logger.warning(f"Unmapped EMSX_STATUS '{raw_status}' for seq={seq} — defaulting to NEW")
                status = "NEW"

            raw_type = self._msg_safe_str(msg, "EMSX_ORDER_TYPE", "LMT").upper()
            order_type_map = {
                "MKT": "MARKET", "MARKET": "MARKET",
                "LMT": "LIMIT",  "LIMIT": "LIMIT",
                "STP": "STOP",   "STOP": "STOP",
                "STPLMT": "STOP_LIMIT",
            }
            order_type = order_type_map.get(raw_type, "LIMIT")

            raw_price = self._msg_safe_float(msg, "EMSX_LIMIT_PRICE")
            price = raw_price if raw_price > 0 else None
            avg_price = self._msg_safe_float(msg, "EMSX_AVG_PRICE") or None
            stop_price = self._msg_safe_float(msg, "EMSX_STOP_PRICE") or None

            tif_raw = self._msg_safe_str(msg, "EMSX_TIF", "DAY").upper()
            tif_map = {"DAY": "DAY", "GTC": "GTC", "IOC": "IOC", "FOK": "FOK", "GTX": "GTX", "GTD": "GTD"}
            tif = tif_map.get(tif_raw, "DAY")

            account = self._msg_safe_str(msg, "EMSX_ACCOUNT")
            portfolio = self._msg_safe_str(msg, "EMSX_PORT_NAME")
            trader = self._msg_safe_str(msg, "EMSX_TRADER")
            notes = self._msg_safe_str(msg, "EMSX_NOTES") or None
            currency_pair = self._msg_safe_str(msg, "EMSX_CURRENCY_PAIR")
            currency = derive_currency(currency_pair, symbol)
            logger.info(f"Order {seq}: CURRENCY_PAIR='{currency_pair}' ticker='{symbol}' -> currency='{currency}'")
            exchange = self._msg_safe_str(msg, "EMSX_EXCHANGE")
            if not exchange and symbol:
                exchange = derive_exchange(symbol)
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
            strategy_start_time = format_strategy_time(strategy_start_time_raw)
            strategy_end_time_raw = self._msg_safe_int(msg, "EMSX_STRATEGY_END_TIME", 0)
            strategy_end_time = format_strategy_time(strategy_end_time_raw)
            percent_remain = self._msg_safe_float(msg, "EMSX_PERCENT_REMAIN") or None
            broker = self._msg_safe_str(msg, "EMSX_BROKER")
            trader_uuid = self._msg_safe_int(msg, "EMSX_TRAD_UUID", 0)
            day_avg_price = self._msg_safe_float(msg, "EMSX_DAY_AVG_PRICE") or None
            arrival_price_raw = self._msg_safe_float(msg, "EMSX_ARRIVAL_PRICE")
            arrival_price = arrival_price_raw if arrival_price_raw > 0 else None
            last_price_raw = self._msg_safe_float(msg, "EMSX_LAST_PRICE")
            last_price = last_price_raw if last_price_raw > 0 else None
            # Basket 归属：未挂篮子的订单 EMSX_BASKET_NUM 常回 0，统一归一为 None
            basket_name = self._msg_safe_str(msg, "EMSX_BASKET_NAME")
            basket_num_raw = self._msg_safe_int(msg, "EMSX_BASKET_NUM", 0)
            basket_num = basket_num_raw if basket_num_raw > 0 else None

            pct_filled = round((filled / qty) * 100, 1) if qty > 0 else 0.0
            if any([custom_note1, custom_note2, custom_note3, custom_note4, custom_note5,
                    trader_notes, notes, exec_instruction, strategy_type]):
                logger.debug(
                    f"Order {seq}: STRAT='{strategy_type}' STYLE='{strategy_style}' "
                    f"RATE={strategy_part_rate_raw} TIME={strategy_start_time}-{strategy_end_time} NOTES='{notes}'"
                )

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
                basketName=basket_name,
                basketNum=basket_num,
            )
        except Exception as e:
            logger.warning(f"Error parsing order message for seq={seq}: {e}")
            return None

    # ── Route parsing ──────────────────────────────────────────────────

    def _parse_route_message(self, msg, seq: int, route_id: int) -> Optional[Route]:
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
            strategy_start_time_raw = self._msg_safe_int(msg, "EMSX_STRATEGY_START_TIME", 0)
            strategy_start_time = format_strategy_time(strategy_start_time_raw)
            strategy_end_time_raw = self._msg_safe_int(msg, "EMSX_STRATEGY_END_TIME", 0)
            strategy_end_time = format_strategy_time(strategy_end_time_raw)

            exchange_destination = self._msg_safe_str(msg, "EMSX_EXCHANGE_DESTINATION")
            execute_broker = self._msg_safe_str(msg, "EMSX_EXECUTE_BROKER")
            is_manual_route = self._msg_safe_int(msg, "EMSX_IS_MANUAL_ROUTE")
            route_ref_id = self._msg_safe_str(msg, "EMSX_ROUTE_REF_ID")
            currency_pair = self._msg_safe_str(msg, "EMSX_CURRENCY_PAIR")
            urgency_level = self._msg_safe_str(msg, "EMSX_URGENCY_LEVEL")

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

    # ── Cross-enrichment (route ↔ order) ──────────────────────────────

    def _enrich_routes_with_new_order(self, order):
        seq_str = str(order.id)
        enriched_count = 0
        for route_key, route in self._routes.items():
            if str(route.sequence) == seq_str:
                needs_update = not route.ticker or not route.exchange or not route.side
                if needs_update:
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
                    logger.info(
                        f"Delayed enrichment for route {route_key}: "
                        f"ticker='{update_dict['ticker']}', exchange='{update_dict['exchange']}'"
                    )
        if enriched_count > 0:
            logger.info(f"Enriched {enriched_count} routes for new order {seq_str}")

    def _enrich_route_from_parent(self, route_key, route):
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
            logger.debug(
                f"Enrich new route {route_key}: "
                f"ticker='{update_dict['ticker']}', exchange='{update_dict['exchange']}'"
            )

    # ── DB write-through ───────────────────────────────────────────────

    def _schedule_persist_order(self, order: Order) -> None:
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            return
        asyncio.run_coroutine_threadsafe(
            self._repo_provider.persist_order(
                sequence=int(order.id),
                order_id=order.id,
                status=order.status,
                trader=order.trader,
                payload=order.model_dump(),
            ),
            loop,
        )
        asyncio.run_coroutine_threadsafe(
            realtime_gw.broadcast_order(order.model_dump(), event_type="update"),
            loop,
        )

    def _schedule_persist_route(self, route: Route) -> None:
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            return
        asyncio.run_coroutine_threadsafe(
            self._repo_provider.persist_route(
                sequence=route.sequence,
                route_id=route.routeId,
                status=route.status,
                broker=route.broker,
                payload=route.model_dump(),
            ),
            loop,
        )
        asyncio.run_coroutine_threadsafe(
            realtime_gw.broadcast_route(route.model_dump(), event_type="update"),
            loop,
        )

    # ── Utilities ──────────────────────────────────────────────────────

    def _msg_safe_int(self, msg, name: str, default: int = 0) -> int:
        return msg_safe_int(msg, name, default)

    def _msg_safe_float(self, msg, name: str, default: float = 0.0) -> float:
        return msg_safe_float(msg, name, default)

    def _msg_safe_str(self, msg, name: str, default: str = "") -> str:
        return msg_safe_str(msg, name, default)

    def _track_api_seq_num(self, msg, stream: str) -> None:
        api_seq_num = self._msg_safe_int(msg, "API_SEQ_NUM", 0)
        if api_seq_num <= 0:
            return

        attr = "_last_order_api_seq_num" if stream == "order" else "_last_route_api_seq_num"
        last_seen = getattr(self, attr, 0)
        if last_seen and api_seq_num > last_seen + 1:
            logger.warning(
                f"{stream.upper()} API_SEQ_NUM gap detected: expected {last_seen + 1}, got {api_seq_num}"
            )
        setattr(self, attr, api_seq_num)
