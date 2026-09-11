"""
Market Data Enrichment Service — extracted from bloomberg_adapter.py.

Manages real-time market data via //blp/mktdata streaming subscriptions,
FX rate resolution via //blp/refdata, ticker currency CRNCY lookups,
round-lot size queries, and permanently-failed ticker fallback.

Threading: owns one background thread (mktdata-subscription).
Uses _market_data_lock (threading.Lock) for subscription management.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Optional, Dict, Set, Any

import blpapi

from .connection import BloombergConnectionManager
from .subscriptions import EMSXSubscriptionEngine

logger = logging.getLogger("main")


class MarketDataEnrichmentService:
    def __init__(
        self,
        connection: BloombergConnectionManager,
        subscription_engine: EMSXSubscriptionEngine,
        _settings: Any,
    ):
        self._connection = connection
        self._subscription_engine = subscription_engine
        self._settings = _settings

        self._price_changes: Dict[str, float] = {}
        self._adv5d: Dict[str, float] = {}
        self._mkt_vwap: Dict[str, float] = {}

        self._fx_rates: Dict[str, float] = {}
        self._round_lot_sizes: Dict[str, int] = {}

        self._mktdata_subscribed_tickers: set = set()
        self._mktdata_active_tickers: set = set()
        self._mktdata_failed_tickers: set = set()
        self._mktdata_permanently_failed: set = set()
        self._mktdata_last_retry: Optional[datetime] = None
        self._mktdata_retry_interval = 300

        self._fx_discrepancy_threshold = 0.02
        self._fx_scaled_quote_logged: set[str] = set()
        self._fx_refresh_interval = 300
        self._fx_last_refresh: Optional[datetime] = None
        self._fx_refdata_pending = False
        self._fx_refdata_cid = blpapi.CorrelationId("__fx_refdata__")
        self._crncy_refdata_cid = blpapi.CorrelationId("__crncy_refdata__")
        self._crncy_refdata_pending = False

        self._ticker_currencies: Dict[str, str] = {}
        self._crncy_queried_tickers: set = set()

        self._round_lot_sizes: Dict[str, int] = {}
        self._round_lot_queried_tickers: set = set()
        self._round_lot_pending_tickers: set = set()
        self._round_lot_refdata_cid = blpapi.CorrelationId("__round_lot_refdata__")
        self._round_lot_refdata_pending = False

        # 行情附属维护（订阅同步/FX/CRNCY/整手/永久失败重试）的节流周期。
        # 原先这些维护在 while 循环内**每轮**执行，而循环唯一节奏来自
        # sess.nextEvent(2000) —— 事件积压时可退化为满速自旋（实测空闲态占用
        # 14.4% of one core，见 code-cleanup skill 复盘日志）。
        self._housekeeping_interval_s = 1.0
        # 订单快照：每周期重建一次，供三个维护函数共享（原先各自 O(#orders) 遍历）。
        self._orders_symbols: Set[str] = set()
        self._orders_symbol_exchange: list[tuple[str, str]] = []

        self._permfail_last_prices: Dict[str, float] = {}

        self._mktdata_thread: Optional[threading.Thread] = None
        self._market_data_lock = threading.Lock()

    # ── Public properties ──────────────────────────────────────────────

    @property
    def price_changes(self) -> Dict[str, float]:
        return self._price_changes

    @property
    def adv5d(self) -> Dict[str, float]:
        return self._adv5d

    @property
    def mkt_vwap(self) -> Dict[str, float]:
        return self._mkt_vwap

    @property
    def fx_rates(self) -> Dict[str, float]:
        return self._fx_rates

    @property
    def round_lot_sizes(self) -> Dict[str, int]:
        return self._round_lot_sizes

    @property
    def ticker_currencies(self) -> Dict[str, str]:
        return self._ticker_currencies

    @property
    def permfail_last_prices(self) -> Dict[str, float]:
        return self._permfail_last_prices

    # ── Lifecycle ──────────────────────────────────────────────────────

    def start(self):
        self._mktdata_thread = threading.Thread(
            target=self._mktdata_subscription_loop,
            daemon=True,
            name="mktdata-subscription",
        )
        self._mktdata_thread.start()
        logger.info("Started mktdata subscription thread")

    def stop(self):
        if self._mktdata_thread and self._mktdata_thread.is_alive():
            self._mktdata_thread.join(timeout=5)
            if self._mktdata_thread.is_alive():
                logger.warning("Mktdata subscription thread did not stop within timeout")

    def reset(self):
        self._price_changes = {}
        self._adv5d = {}
        self._mkt_vwap = {}
        self._fx_rates = {}
        self._round_lot_sizes = {}
        self._mktdata_subscribed_tickers = set()
        self._mktdata_active_tickers = set()
        self._mktdata_failed_tickers = set()
        self._mktdata_permanently_failed = set()
        self._permfail_last_prices = {}
        self._mktdata_last_retry = None
        self._fx_last_refresh = None
        self._fx_refdata_pending = False
        self._crncy_refdata_pending = False
        self._crncy_queried_tickers = set()
        self._ticker_currencies = {}

    # ── Mktdata subscription loop ──────────────────────────────────────

    def _mktdata_subscription_loop(self):
        sess = self._connection.mktdata_session
        if not sess or not self._connection.mktdata_connected:
            logger.warning("Mktdata session not available — market data enrichment disabled")
            return

        logger.info("Mktdata subscription loop started")
        self._fx_rates["USD"] = 1.0

        stop_event = self._subscription_engine.stop_event
        stop_event.wait(3)

        next_housekeeping = 0.0
        while not stop_event.is_set():
            # 附属维护按固定周期执行（而非每轮）：事件泵本身保持不变，
            # 因此行情推送的实时性不受影响。
            now_monotonic = time.monotonic()
            if now_monotonic >= next_housekeeping:
                next_housekeeping = now_monotonic + self._housekeeping_interval_s
                self._run_housekeeping(sess)

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
                            reasons: list[str] = []
                            try:
                                if msg.hasElement("reason"):
                                    reason = msg.getElement("reason")
                                    if reason.isArray():
                                        for i in range(reason.numValues()):
                                            entry = reason.getValueAsElement(i)
                                            desc = ""
                                            ec: Optional[int] = None
                                            if entry.hasElement("errorCode"):
                                                ec = entry.getElementAsInteger("errorCode")
                                            if entry.hasElement("description"):
                                                desc = str(entry.getElement("description").getValue())
                                            elif entry.hasElement("source"):
                                                desc = str(entry.getElement("source").getValue())
                                            reasons.append(
                                                f"{desc}, rcode = {ec}" if ec is not None and desc
                                                else (f"rcode = {ec}" if ec is not None else desc)
                                            )
                                    else:
                                        desc = ""
                                        ec = None
                                        if reason.hasElement("errorCode"):
                                            ec = reason.getElementAsInteger("errorCode")
                                        if reason.hasElement("description"):
                                            desc = str(reason.getElement("description").getValue())
                                        elif reason.hasElement("source"):
                                            desc = str(reason.getElement("source").getValue())
                                        reasons.append(
                                            f"{desc}, rcode = {ec}" if ec is not None and desc
                                            else (f"rcode = {ec}" if ec is not None else desc)
                                        )
                            except Exception:
                                pass
                            failure_reason = "; ".join(reasons) if reasons else ""

                            _permanent_rcodes = {"-11", "-1", "2", "7"}
                            if cid_val and any(
                                f"rcode = {rc}" in r for r in reasons for rc in _permanent_rcodes
                            ):
                                self._mktdata_permanently_failed.add(cid_val)
                                self._mktdata_failed_tickers.discard(cid_val)
                                logger.warning(
                                    "[MKTDATA PERMFAIL] %s — will not retry. Falling back to //blp/refdata.",
                                    cid_val,
                                )
                            batch_failures.append((cid_val or "unknown", failure_reason))
                        elif "SubscriptionStarted" in mtype:
                            if cid_val:
                                self._mktdata_active_tickers.add(cid_val)
                                self._mktdata_failed_tickers.discard(cid_val)
                            batch_started.append(cid_val or "unknown")

                    if batch_started:
                        logger.info(
                            f"Mktdata subscriptions started: {len(batch_started)} "
                            f"({batch_started[:5]}{'...' if len(batch_started) > 5 else ''})"
                        )
                    if batch_failures:
                        failure_details = [(t, r) for t, r in batch_failures[:3]]
                        logger.warning(
                            f"Mktdata subscription failures: {len(batch_failures)} ({failure_details}). "
                            f"Will retry in {self._mktdata_retry_interval}s."
                        )

                elif etype in (blpapi.Event.PARTIAL_RESPONSE, blpapi.Event.RESPONSE):
                    completed_refdata_cids: set[str] = set()
                    for msg in event:
                        try:
                            cid = msg.correlationIds()[0] if msg.correlationIds() else None
                            cid_val = str(cid.value()) if cid else ""
                            if cid_val == "__crncy_refdata__":
                                self._process_crncy_refdata_response(msg)
                            elif cid_val == "__round_lot_refdata__":
                                self._process_round_lot_refdata_response(msg)
                            elif cid_val == "__permfail_refdata__":
                                self._process_permfail_refdata_response(msg)
                            else:
                                self._process_fx_refdata_response(msg)
                            if cid_val:
                                completed_refdata_cids.add(cid_val)
                        except Exception as e:
                            logger.debug(f"Error processing refdata response: {e}")
                    if etype == blpapi.Event.RESPONSE:
                        self._mark_refdata_response_complete(completed_refdata_cids)

                elif etype == blpapi.Event.SESSION_STATUS:
                    for msg in event:
                        mtype = str(msg.messageType())
                        if "SessionTerminated" in mtype:
                            logger.error("Mktdata session terminated")
                            self._connection.mktdata_connected = False
                            return

                elif etype == blpapi.Event.TIMEOUT:
                    pass

            except Exception as e:
                logger.debug(f"Mktdata event loop error: {e}")

        logger.info("Mktdata subscription loop stopped")

    # ── Subscription management ────────────────────────────────────────

    def _run_housekeeping(self, sess) -> None:
        """按固定周期执行一次行情附属维护（原为 while 每轮执行）。

        独立成方法的原因：这五项都是 O(#orders) 遍历或带 IO 的维护动作，
        不应随事件泵的节奏执行（事件积压时事件泵可退化为满速自旋）。
        """
        try:
            self._refresh_orders_snapshot()
        except Exception as e:
            logger.warning(f"Error refreshing orders snapshot: {e}")

        try:
            self._update_mktdata_subscriptions(sess)
        except Exception as e:
            logger.warning(f"Error updating mktdata subscriptions: {e}")

        try:
            self._maybe_refresh_fx_rates(sess)
        except Exception as e:
            logger.warning(f"Error refreshing FX rates: {e}")

        try:
            self._maybe_query_ticker_currencies(sess)
        except Exception as e:
            logger.warning(f"Error querying ticker currencies: {e}")

        try:
            self._maybe_query_round_lot_sizes(sess)
        except Exception as e:
            logger.warning(f"Error querying round lot sizes: {e}")

        try:
            self._maybe_refresh_permanently_failed_tickers(sess)
        except Exception as e:
            logger.warning(f"Error refreshing permanently-failed tickers: {e}")

    def _refresh_orders_snapshot(self) -> None:
        """重建订单快照（每个 housekeeping 周期一次）。

        原先三个维护函数各自遍历 ``self._subscription_engine.orders`` 构造符号集合，
        实测在空闲态占该线程活跃 CPU 的约 70%（见 skill 复盘日志的 py-spy 采样）。
        """
        symbols: Set[str] = set()
        pairs: list[tuple[str, str]] = []
        for order in self._subscription_engine.orders.values():
            if not order.symbol:
                continue
            symbols.add(order.symbol)
            pairs.append((order.symbol, order.exchange or ""))
        self._orders_symbols = symbols
        self._orders_symbol_exchange = pairs

    def _send_refdata_request(self, sess, request, correlation_id, label: str) -> bool:
        """发送 refdata 请求；correlationId 仍在途时视为「已发出」而非错误。

        背景：blpapi 对尚未完成响应的同一 correlationId 再次 sendRequest 会抛
        ``DuplicateCorrelationIdException``。早期实现把该异常记为 WARNING 并在下一轮
        重试，配合无节流自旋造成重复发送风暴（实测日志中 577 次 Duplicate）。
        返回 True 表示请求已在途（本次发出 **或** 上次仍在途）——调用方应保持 pending；
        返回 False 表示真正发送失败（未发出），调用方可不置 pending 以便下轮重试。
        """
        try:
            sess.sendRequest(request, correlationId=correlation_id)
            return True
        except blpapi.DuplicateCorrelationIdException:
            logger.debug("refdata 请求已在途，跳过重复发送: %s", label)
            return True
        except Exception as e:
            logger.warning(f"Failed to send {label} refdata request: {e}")
            return False

    def _update_mktdata_subscriptions(self, sess):
        current_tickers = self._orders_symbols
        new_tickers = current_tickers - self._mktdata_subscribed_tickers

        now = datetime.now()
        retry_tickers: set = set()
        if self._mktdata_failed_tickers:
            if self._mktdata_last_retry is None or (
                now - self._mktdata_last_retry
            ).total_seconds() >= self._mktdata_retry_interval:
                retry_tickers = self._mktdata_failed_tickers - self._mktdata_permanently_failed
                self._mktdata_last_retry = now
                if retry_tickers:
                    logger.info(f"Retrying {len(retry_tickers)} failed ticker subscriptions")

        all_new_tickers = new_tickers | retry_tickers

        if not all_new_tickers:
            return

        sub_list = blpapi.SubscriptionList()

        for ticker in all_new_tickers:
            cid = blpapi.CorrelationId(ticker)
            sub_list.add(
                topic=f"//blp/mktdata/{ticker}",
                fields=["CHG_PCT_1D", "VOLUME_AVG_5D", "VWAP", "PX_ROUND_LOT_SIZE"],
                correlationId=cid,
            )
        logger.info(
            f"Subscribing mktdata for {len(all_new_tickers)} tickers: "
            f"{sorted(all_new_tickers)[:10]}{'...' if len(all_new_tickers) > 10 else ''}"
        )
        self._mktdata_subscribed_tickers.update(all_new_tickers)

        try:
            sess.subscribe(sub_list)
            self._mktdata_failed_tickers -= retry_tickers
            if self._mktdata_last_retry is None:
                self._mktdata_last_retry = now
        except Exception as e:
            logger.warning(f"Failed to subscribe mktdata: {e}")

    def _process_mktdata_message(self, msg):
        cid = msg.correlationId()
        if not cid:
            return
        topic = cid.value()
        if not isinstance(topic, str):
            return

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
                debug_symbols = {
                    "COST", "DE", "GEV", "RS", "ZS", "ROP", "ORCL", "MSTR", "INTU",
                    "HUBS", "ADBE", "MPWR", "VRSN", "IT", "IBM", "ZBRA", "TDY",
                    "MSI", "CHTR", "SPY", "AVGO", "PH", "ETN", "V", "PG", "WMT",
                    "PEP", "KO", "XOM",
                }
                ticker_base = ticker.split()[0] if " " in ticker else ticker
                if ticker_base in debug_symbols:
                    logger.info(f"[ROUND_LOT_MKTDATA] {ticker}: PX_ROUND_LOT_SIZE = {val}")
                else:
                    logger.debug(f"[ROUND_LOT] {ticker}: PX_ROUND_LOT_SIZE = {val}")
        except Exception as e:
            logger.debug(f"Error parsing mktdata for {ticker}: {e}")

    # ── FX rate refresh ────────────────────────────────────────────────

    def _maybe_refresh_fx_rates(self, sess):
        if not self._connection.refdata_service_available or self._fx_refdata_pending:
            return
        now = datetime.now()
        if self._fx_last_refresh is not None and (
            now - self._fx_last_refresh
        ).total_seconds() < self._fx_refresh_interval:
            return

        currencies: set = set()
        for o in self._subscription_engine.orders.values():
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
                securities.appendValue(f"{ccy}USD Curncy")
                securities.appendValue(f"USD{ccy} Curncy")
            fields = req.getElement("fields")
            fields.appendValue("PX_LAST")
            if self._send_refdata_request(sess, req, self._fx_refdata_cid, "FX"):
                self._fx_refdata_pending = True
                logger.info(f"Sent FX refdata request for {len(currencies)} currencies: {sorted(currencies)}")
            self._fx_last_refresh = now
        except Exception as e:
            logger.warning(f"Failed to send FX refdata request: {e}")

    def _mark_refdata_response_complete(self, correlation_values: set[str]) -> None:
        if "__fx_refdata__" in correlation_values:
            self._fx_refdata_pending = False
        if "__crncy_refdata__" in correlation_values:
            self._crncy_refdata_pending = False
        if "__round_lot_refdata__" in correlation_values:
            self._round_lot_refdata_pending = False

    def _normalize_scaled_fx_direct_rate(
        self,
        direct_rate: float,
        inverse_rate: float,
    ) -> tuple[Optional[float], Optional[int]]:
        if direct_rate <= 0 or inverse_rate <= 0:
            return None, None

        for scale_factor in (10, 100, 1000, 10000):
            normalized_rate = direct_rate / scale_factor
            normalized_gap = abs((normalized_rate / inverse_rate) - 1.0)
            if normalized_gap <= self._fx_discrepancy_threshold:
                return normalized_rate, scale_factor

            normalized_rate = direct_rate * scale_factor
            normalized_gap = abs((normalized_rate / inverse_rate) - 1.0)
            if normalized_gap <= self._fx_discrepancy_threshold:
                return normalized_rate, -scale_factor

        return None, None

    def _log_fx_rate_discrepancy(self, ccy: str, direct_rate: float, inverse_rate: float) -> None:
        if direct_rate <= 0 or inverse_rate <= 0:
            return

        ratio = direct_rate / inverse_rate
        if abs(ratio - 1.0) <= self._fx_discrepancy_threshold:
            return

        normalized_rate, scale_factor = self._normalize_scaled_fx_direct_rate(
            direct_rate, inverse_rate
        )
        if scale_factor is not None:
            if ccy not in self._fx_scaled_quote_logged:
                if scale_factor > 0:
                    logger.info(
                        f"FX {ccy}: direct quote appears scaled by {scale_factor}x "
                        f"(normalized direct={normalized_rate:.6f}, inverse={inverse_rate:.6f}) — using inverse"
                    )
                else:
                    logger.info(
                        f"FX {ccy}: direct quote appears scaled by 1/{abs(scale_factor)}x "
                        f"(normalized direct={normalized_rate:.6f}, inverse={inverse_rate:.6f}) — using inverse"
                    )
                self._fx_scaled_quote_logged.add(ccy)
            return

        logger.warning(
            f"FX {ccy}: direct={direct_rate:.6f} vs inverse={inverse_rate:.6f} "
            f"(ratio={ratio:.2f}x) — using inverse"
        )

    def _process_fx_refdata_response(self, msg):
        try:
            if not msg.hasElement("securityData"):
                return
            sd = msg.getElement("securityData")
            direct_rates = {}
            inverse_rates = {}
            for i in range(sd.numValues()):
                entry = sd.getValueAsElement(i)
                sec = entry.getElementAsString("security")
                if entry.hasElement("fieldData"):
                    fd = entry.getElement("fieldData")
                    if fd.hasElement("PX_LAST"):
                        rate = fd.getElementAsFloat("PX_LAST")
                        if rate > 0:
                            pair = sec.replace(" Curncy", "").strip()
                            if pair.endswith("USD") and len(pair) == 6:
                                ccy_code = pair[:3]
                                direct_rates[ccy_code] = rate
                            elif pair.startswith("USD") and len(pair) == 6:
                                ccy_code = pair[3:]
                                inverse_rates[ccy_code] = 1.0 / rate
                else:
                    logger.debug(f"FX: no fieldData for {sec} (security may not exist)")

            all_ccys = set(direct_rates.keys()) | set(inverse_rates.keys())
            updated = 0
            for ccy in all_ccys:
                if ccy in inverse_rates:
                    new_rate = inverse_rates[ccy]
                elif ccy in direct_rates:
                    new_rate = direct_rates[ccy]
                else:
                    continue
                self._fx_rates[ccy] = new_rate
                updated += 1
                if ccy in direct_rates and ccy in inverse_rates:
                    self._log_fx_rate_discrepancy(ccy, direct_rates[ccy], inverse_rates[ccy])

            if updated:
                logger.info(
                    f"FX rates updated: {updated} currencies — "
                    f"{dict(sorted(self._fx_rates.items()))}"
                )
        except Exception as e:
            logger.warning(f"Error processing FX refdata response: {e}")

    # ── Ticker currency resolution ─────────────────────────────────────

    def _maybe_query_ticker_currencies(self, sess):
        if not self._connection.refdata_service_available or self._crncy_refdata_pending:
            return
        new_tickers = self._orders_symbols - self._crncy_queried_tickers
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
            if self._send_refdata_request(sess, req, self._crncy_refdata_cid, "CRNCY"):
                self._crncy_refdata_pending = True
                logger.info(f"Sent CRNCY refdata request for {len(new_tickers)} tickers")
            self._crncy_queried_tickers |= new_tickers
        except Exception as e:
            logger.warning(f"Failed to send CRNCY refdata request: {e}")

    def _process_crncy_refdata_response(self, msg):
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
                            self._ticker_currencies[sec] = crncy
                            for o in self._subscription_engine.orders.values():
                                if o.symbol == sec and o.currency != crncy:
                                    logger.info(
                                        f"CRNCY override: order {o.id} ({sec}) "
                                        f"currency '{o.currency}' → '{crncy}'"
                                    )
                                    o.currency = crncy
                            updated += 1
            if updated:
                self._fx_last_refresh = None
                sample = dict(list(sorted(self._ticker_currencies.items()))[:10])
                logger.info(f"CRNCY updated: {updated} tickers (sample: {sample})")
        except Exception as e:
            logger.warning(f"Error processing CRNCY refdata response: {e}")

    # ── Round lot size queries ─────────────────────────────────────────

    def _maybe_query_round_lot_sizes(self, sess):
        if not self._connection.refdata_service_available:
            logger.warning("[ROUND_LOT] Skipping: refdata service not available")
            return
        if self._round_lot_refdata_pending:
            logger.debug("[ROUND_LOT] Skipping: previous request still pending")
            return

        target_tickers = set()
        odd_lot_markets = set(self._settings.ODD_LOT_MARKETS)
        for symbol, exchange in self._orders_symbol_exchange:
            if exchange and exchange.upper() in odd_lot_markets \
                    and symbol not in self._round_lot_queried_tickers:
                target_tickers.add(symbol)

        if target_tickers:
            logger.info(
                f"[ROUND_LOT] Found {len(target_tickers)} new tickers to query "
                f"for markets {sorted(odd_lot_markets)} "
                f"(total orders: {len(self._subscription_engine.orders)}, "
                f"queried: {len(self._round_lot_queried_tickers)})"
            )

        if not target_tickers:
            return

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
            if self._send_refdata_request(sess, req, self._round_lot_refdata_cid, "round lot"):
                self._round_lot_refdata_pending = True
                logger.info(
                    f"Sent PX_ROUND_LOT_SIZE refdata request for "
                    f"{len(tickers_to_query)} tickers: {tickers_to_query[:5]}..."
                )
            self._round_lot_queried_tickers.update(tickers_to_query)
        except Exception as e:
            logger.warning(f"Failed to send round lot refdata request: {e}")

    def _process_round_lot_refdata_response(self, msg):
        try:
            # pending 由 _mark_refdata_response_complete 在 Event.RESPONSE 时清除。
            # 此处**不得**提前清除：PARTIAL_RESPONSE 也会进入本函数，提前清除会让
            # 下一轮立即重发同一请求 → blpapi 抛 DuplicateCorrelationIdException
            # （实测日志中 141 次 round lot Duplicate 的根因）。
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
                        self._round_lot_sizes[sec] = -1
                        logger.info(
                            f"[ROUND_LOT_BDP] {sec}: PX_ROUND_LOT_SIZE not available, marked as unknown"
                        )
                else:
                    self._round_lot_sizes[sec] = -1
                    logger.info(f"[ROUND_LOT_BDP] {sec}: No field data, marked as unknown")
            if updated:
                logger.info(
                    f"PX_ROUND_LOT_SIZE updated: {updated} tickers "
                    f"(total cached: {len(self._round_lot_sizes)})"
                )
        except Exception as e:
            logger.warning(f"Error processing PX_ROUND_LOT_SIZE refdata response: {e}")

    # ── Permfail fallback ──────────────────────────────────────────────

    def _maybe_refresh_permanently_failed_tickers(self, sess):
        if not self._connection.refdata_service_available:
            return
        if not self._mktdata_permanently_failed:
            return
        now = datetime.now()
        if not hasattr(self, "_permfail_last_refresh"):
            self._permfail_last_refresh: Optional[datetime] = None
        if self._permfail_last_refresh is not None and (
            now - self._permfail_last_refresh
        ).total_seconds() < 60:
            return
        self._permfail_last_refresh = now

        tickers = sorted(self._mktdata_permanently_failed)
        try:
            svc = sess.getService("//blp/refdata")
            req = svc.createRequest("ReferenceDataRequest")
            securities = req.getElement("securities")
            for t in tickers:
                securities.appendValue(t)
            fields = req.getElement("fields")
            fields.appendValue("PX_LAST")
            self._send_refdata_request(
                sess, req, blpapi.CorrelationId("__permfail_refdata__"), "permfail")
            logger.warning(
                "[MKTDATA PERMFAIL REFDATA] Sent PX_LAST request for %d "
                "permanently-failed tickers: %s",
                len(tickers),
                tickers[:5],
            )
        except Exception as e:
            logger.warning(f"Failed to send permanently-failed refdata request: {e}")

    def _process_permfail_refdata_response(self, msg):
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
                    if fd.hasElement("PX_LAST"):
                        px = fd.getElementAsFloat("PX_LAST")
                        if px > 0:
                            self._permfail_last_prices[sec] = px
                            updated += 1
            if updated:
                logger.warning(
                    "[MKTDATA PERMFAIL REFDATA] Updated PX_LAST for %d "
                    "permanently-failed tickers",
                    updated,
                )
        except Exception as e:
            logger.warning(f"Error processing permfail refdata response: {e}")
