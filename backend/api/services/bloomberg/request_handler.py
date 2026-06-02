"""
EMSX Request Handler — extracted from bloomberg_adapter.py.

Handles all EMSX request/response operations: modify/cancel/route orders,
modify/cancel routes, broker and strategy discovery, asset class resolution.

Uses the connection manager's request session pool for concurrent EMSX requests.
Connect checks are handled by the facade — methods here assume the connection
is already established.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import List, Optional, Dict, Any

import blpapi
from blpapi import Event, Message, Request, Service

from fastapi import HTTPException

from schemas import (
    BatchUpdateRequest, BatchUpdateResponse,
    CancelRouteRequest, ModifyRouteRequest, RouteOrderRequest,
)

from services.route_service import _resolve_hand_instruction

from ._constants import EMSX_ORDER_TYPE_MAP
from .connection import BloombergConnectionManager
from .subscriptions import EMSXSubscriptionEngine
from .._bloomberg_parsing import (
    msg_safe_int, msg_safe_float, msg_safe_str,
    order_type_uses_limit_price, order_type_uses_stop_price,
)

logger = logging.getLogger("main")

# Module-level settings — set by configure_handler() before any instance is created
_handler_settings: Any = None


def configure_handler(settings: Any) -> None:
    global _handler_settings
    _handler_settings = settings


class EMSXRequestHandler:
    def __init__(
        self,
        connection: BloombergConnectionManager,
        subscription_engine: EMSXSubscriptionEngine,
        _settings: Any = None,
    ):
        self._connection = connection
        self._subscription_engine = subscription_engine
        self._settings = _settings if _settings is not None else _handler_settings

    # ── Request helpers ────────────────────────────────────────────────

    @property
    def _req_service(self) -> Service:
        svc = self._connection.request_service
        if not svc:
            raise HTTPException(503, "Bloomberg service not available")
        return svc

    def _send_request(self, request: Request) -> List[Message]:
        if not self._connection.connected or not self._connection.request_sessions:
            raise HTTPException(503, "Bloomberg not connected (no request sessions)")

        idx = self._connection.pool_index
        self._connection.pool_index = (idx + 1) % len(self._connection.request_sessions)
        sess = self._connection.request_sessions[idx]

        with self._connection.request_locks[idx]:
            cid = blpapi.CorrelationId()
            sess.sendRequest(request, correlationId=cid)

            messages: List[Message] = []
            timeout_ms = self._settings.BLOOMBERG_TIMEOUT
            deadline = datetime.now().timestamp() * 1000 + timeout_ms

            while True:
                remaining = max(0, int(deadline - datetime.now().timestamp() * 1000))
                event = sess.nextEvent(remaining)
                etype = event.eventType()

                if etype in (Event.PARTIAL_RESPONSE, Event.RESPONSE):
                    matched_response = False
                    for msg in event:
                        if self._message_has_correlation_id(msg, cid):
                            messages.append(msg)
                            matched_response = True
                    if etype == Event.RESPONSE and matched_response:
                        break
                elif etype == Event.TIMEOUT:
                    raise HTTPException(504, "Bloomberg request timed out")

            return messages

    async def _send_request_async(self, request: Request) -> List[Message]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._send_request, request)

    @staticmethod
    def _message_has_correlation_id(msg: Message, cid: blpapi.CorrelationId) -> bool:
        try:
            target = cid.value()
            for candidate in msg.correlationIds():
                if candidate.value() == target:
                    return True
        except Exception:
            return False
        return False

    def _normalize_emsx_order_type(self, order_type: Optional[str]) -> str:
        normalized = (order_type or "").strip().upper().replace("-", "_").replace(" ", "_")
        if not normalized:
            return ""
        emsx_order_type = EMSX_ORDER_TYPE_MAP.get(normalized)
        if emsx_order_type:
            return emsx_order_type
        raise HTTPException(400, f"Unsupported order type '{order_type}'")

    def _apply_strategy_params(
        self, request: Request, strategy_params: Optional[Dict[str, Any]]
    ) -> None:
        if not strategy_params:
            return

        strategy_name = str(strategy_params.get("strategyName", "") or "").strip()
        fields_data = strategy_params.get("fields", [])

        if not strategy_name:
            return
        if fields_data is None:
            fields_data = []
        if not isinstance(fields_data, list):
            raise HTTPException(400, "Strategy fields must be a list")

        strategy = request.getElement("EMSX_STRATEGY_PARAMS")
        strategy.setElement("EMSX_STRATEGY_NAME", strategy_name)

        indicator = strategy.getElement("EMSX_STRATEGY_FIELD_INDICATORS")
        data = strategy.getElement("EMSX_STRATEGY_FIELDS")

        for field_entry in fields_data:
            raw_value = field_entry.get("value", "")
            value = "" if raw_value is None else str(raw_value).strip()
            disabled = bool(field_entry.get("disabled", False))
            if not disabled and value == "":
                disabled = True
            data.appendElement().setElement("EMSX_FIELD_DATA", "" if disabled else value)
            indicator.appendElement().setElement("EMSX_FIELD_INDICATOR", 1 if disabled else 0)

    # ── Order operations ───────────────────────────────────────────────

    async def modify_order(self, order_id: str, field: str, value: Any) -> bool:
        try:
            request = self._req_service.createRequest("ModifyOrderEx")
            request.set("EMSX_SEQUENCE", int(order_id))

            with self._subscription_engine.data_lock:
                cached = self._subscription_engine.orders.get(order_id)
            if cached:
                request.set("EMSX_TICKER", cached.symbol)
                request.set("EMSX_AMOUNT", cached.quantity)
                request.set(
                    "EMSX_ORDER_TYPE",
                    {"MARKET": "MKT", "LIMIT": "LMT", "STOP": "STP"}.get(
                        cached.orderType, "LMT"
                    ),
                )
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
                    raise HTTPException(
                        400, msg_safe_str(msg, "ERROR_MESSAGE", "Modify rejected")
                    )

            logger.info(f"Modified order {order_id}: {field}={value}")
            return True

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error modifying order {order_id}: {e}")
            raise HTTPException(500, f"Failed to modify order: {str(e)}")

    async def cancel_order(self, order_id: str) -> bool:
        try:
            request = self._req_service.createRequest("CancelOrderEx")
            request.getElement("EMSX_SEQUENCE").appendValue(int(order_id))

            messages = await self._send_request_async(request)
            for msg in messages:
                if "Error" in str(msg.messageType()):
                    raise HTTPException(
                        400, msg_safe_str(msg, "ERROR_MESSAGE", "Cancel rejected")
                    )

            logger.info(f"Cancelled order {order_id}")
            return True

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error cancelling order {order_id}: {e}")
            raise HTTPException(500, f"Failed to cancel order: {str(e)}")

    # ── Batch update (used by facade) ──────────────────────────────────

    async def batch_update(
        self, request_data: BatchUpdateRequest, service: Any
    ) -> BatchUpdateResponse:
        updated = 0
        failed = []

        for order_id in request_data.orderIds:
            try:
                if request_data.field == "status" and request_data.value == "CANCELLED":
                    await service.cancel_order(order_id)
                else:
                    await service.modify_order(order_id, request_data.field, request_data.value)
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
            message=message,
        )

    # ── Route operations ───────────────────────────────────────────────

    async def cancel_route(self, request_data: CancelRouteRequest) -> bool:
        try:
            request = self._req_service.createRequest("CancelRouteEx")
            request.set("EMSX_SEQUENCE", request_data.sequence)
            request.set("EMSX_ROUTE_ID", request_data.routeId)

            messages = await self._send_request_async(request)
            for msg in messages:
                if "Error" in str(msg.messageType()):
                    raise HTTPException(
                        400, msg_safe_str(msg, "ERROR_MESSAGE", "Cancel route rejected")
                    )

            logger.info(
                f"Cancelled route {request_data.routeId} for order {request_data.sequence}"
            )
            return True

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error cancelling route {request_data.routeId}: {e}")
            raise HTTPException(500, f"Failed to cancel route: {str(e)}")

    async def modify_route(self, request_data: ModifyRouteRequest) -> bool:
        try:
            request = self._req_service.createRequest("ModifyRouteEx")
            request.set("EMSX_SEQUENCE", request_data.sequence)
            request.set("EMSX_ROUTE_ID", request_data.routeId)

            route_key = f"{request_data.sequence}.{request_data.routeId}"
            with self._subscription_engine.data_lock:
                cached = self._subscription_engine.routes.get(route_key)

            if request_data.amount is not None:
                request.set("EMSX_AMOUNT", request_data.amount)
            elif cached:
                request.set("EMSX_AMOUNT", cached.amount)
            else:
                raise HTTPException(400, "Amount is required for route modification")

            order_type = self._normalize_emsx_order_type(
                request_data.orderType or (cached.orderType if cached else "")
            )
            if order_type:
                request.set("EMSX_ORDER_TYPE", order_type)
            else:
                raise HTTPException(400, "Order type is required for route modification")
            cached_order_type = self._normalize_emsx_order_type(
                cached.orderType if cached else ""
            )

            tif = request_data.tif or (cached.tif if cached else "DAY")
            request.set("EMSX_TIF", tif)

            limit_price_provided = "limitPrice" in request_data.model_fields_set
            stop_price_provided = "stopPrice" in request_data.model_fields_set
            if limit_price_provided:
                request.set(
                    "EMSX_LIMIT_PRICE",
                    -99999 if request_data.limitPrice is None else request_data.limitPrice,
                )
            elif (
                cached_order_type
                and order_type_uses_limit_price(cached_order_type)
                and not order_type_uses_limit_price(order_type)
            ):
                request.set("EMSX_LIMIT_PRICE", -99999)

            if stop_price_provided:
                request.set(
                    "EMSX_STOP_PRICE",
                    -1 if request_data.stopPrice is None else request_data.stopPrice,
                )
            elif (
                cached_order_type
                and order_type_uses_stop_price(cached_order_type)
                and not order_type_uses_stop_price(order_type)
            ):
                request.set("EMSX_STOP_PRICE", -1)

            if request_data.broker:
                cached_broker = (cached.broker if cached else "") or ""
                if request_data.broker.strip().upper() != cached_broker.strip().upper():
                    raise HTTPException(
                        400,
                        "EMSX does not support changing the broker on an existing route. "
                        "Cancel this route and create a new route to the desired broker.",
                    )
            if request_data.exchangeDestination:
                request.set("EMSX_EXCHANGE_DESTINATION", request_data.exchangeDestination)
            if request_data.notes:
                request.set("EMSX_NOTES", request_data.notes)

            self._apply_strategy_params(request, request_data.strategyParams)

            messages = await self._send_request_async(request)
            for msg in messages:
                if "Error" in str(msg.messageType()):
                    raise HTTPException(
                        400, msg_safe_str(msg, "ERROR_MESSAGE", "Modify route rejected")
                    )

            logger.info(
                f"Modified route {request_data.routeId} for order {request_data.sequence}"
            )
            return True

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error modifying route {request_data.routeId}: {e}")
            raise HTTPException(500, f"Failed to modify route: {str(e)}")

    async def route_order(self, request_data: RouteOrderRequest, service: Any) -> dict:
        logger.info(f"Routing order {request_data.orderId} to broker {request_data.broker}")

        try:
            with self._subscription_engine.data_lock:
                parent_order = self._subscription_engine.orders.get(request_data.orderId)

            if not parent_order:
                raise HTTPException(404, f"Order {request_data.orderId} not found")

            routable_statuses = {"NEW", "ASSIGN", "WORKING", "PARTIAL", "SENT", "QUEUED"}
            if parent_order.status not in routable_statuses:
                raise HTTPException(
                    400,
                    f"Order {request_data.orderId} has status '{parent_order.status}' "
                    f"— only orders with status {', '.join(sorted(routable_statuses))} "
                    "can be routed",
                )

            terminal_trader = service.get_terminal_trader_name()
            if (
                terminal_trader
                and parent_order.trader
                and terminal_trader.upper() != parent_order.trader.upper()
            ):
                raise HTTPException(
                    403,
                    f"Cannot route order {request_data.orderId}: assigned to trader "
                    f"'{parent_order.trader}', but current trader is '{terminal_trader}'",
                )

            if request_data.quantity > parent_order.remainingQuantity:
                raise HTTPException(
                    400,
                    f"Route quantity ({request_data.quantity}) exceeds remaining quantity "
                    f"({parent_order.remainingQuantity})",
                )

            request = self._req_service.createRequest("RouteEx")

            request.set("EMSX_SEQUENCE", int(request_data.orderId))
            request.set("EMSX_TICKER", parent_order.symbol)
            request.set("EMSX_BROKER", request_data.broker)
            request.set("EMSX_AMOUNT", request_data.quantity)
            emsx_order_type = self._normalize_emsx_order_type(request_data.orderType)
            request.set("EMSX_ORDER_TYPE", emsx_order_type)
            request.set("EMSX_TIF", request_data.timeInForce)
            request.set("EMSX_HAND_INSTRUCTION", _resolve_hand_instruction(request_data.broker))

            if order_type_uses_limit_price(emsx_order_type) and request_data.price is not None:
                request.set("EMSX_LIMIT_PRICE", request_data.price)
            if order_type_uses_stop_price(emsx_order_type) and request_data.stopPrice is not None:
                request.set("EMSX_STOP_PRICE", request_data.stopPrice)
            if request_data.exchangeDestination:
                request.set("EMSX_EXCHANGE_DESTINATION", request_data.exchangeDestination)
            if request_data.notes:
                request.set("EMSX_NOTES", request_data.notes)
            if request_data.releaseTime is not None:
                request.set("EMSX_RELEASE_TIME", request_data.releaseTime)

            self._apply_strategy_params(request, request_data.strategyParams)

            messages = await self._send_request_async(request)

            route_id = None
            for msg in messages:
                if "Error" in str(msg.messageType()):
                    raise HTTPException(
                        400, msg_safe_str(msg, "ERROR_MESSAGE", "Route order rejected")
                    )
                if msg.hasElement("EMSX_ROUTE_ID"):
                    route_id = msg.getElementAsInteger("EMSX_ROUTE_ID")

            logger.info(
                f"Created route for order {request_data.orderId} to broker "
                f"{request_data.broker}, route_id: {route_id}"
            )
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

    # ── Broker / strategy queries ──────────────────────────────────────

    async def get_asset_class(self, ticker: str) -> str:
        logger.info(f"Getting asset class for {ticker}")

        try:
            request = self._req_service.createRequest("GetAssetClass")
            request.set("EMSX_TICKER", ticker)

            messages = await self._send_request_async(request)
            for msg in messages:
                if msg.hasElement("EMSX_ASSET_CLASS"):
                    return msg_safe_str(msg, "EMSX_ASSET_CLASS", "EQTY") or "EQTY"
                if "Error" in str(msg.messageType()):
                    error_msg = msg_safe_str(msg, "ERROR_MESSAGE", "Failed to get asset class")
                    logger.warning(
                        f"GetAssetClass rejected for {ticker}: {error_msg} - defaulting to EQTY"
                    )
                    return "EQTY"

            logger.warning(
                f"GetAssetClass returned no EMSX_ASSET_CLASS for {ticker} - defaulting to EQTY"
            )
            return "EQTY"

        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"GetAssetClass failed for {ticker}: {e} - defaulting to EQTY")
            return "EQTY"

    async def get_broker_strategies(
        self, broker: str, asset_class: str = "EQTY"
    ) -> List[str]:
        logger.info(f"Getting broker strategies for {broker} ({asset_class})")

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
                    error_msg = msg_safe_str(msg, "ERROR_MESSAGE", "Failed to get broker strategies")
                    logger.warning(f"GetBrokerStrategies error for {broker}: {error_msg}")

            logger.info(f"Broker {broker} ({asset_class}): {len(strategies)} strategies found")
            return strategies

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting broker strategies for {broker}: {e}")
            raise HTTPException(500, f"Failed to get broker strategies: {str(e)}")

    async def get_broker_strategy_info(
        self, broker: str, strategy: str, asset_class: str = "EQTY"
    ) -> List[dict]:
        logger.info(f"Getting strategy info for {broker}/{strategy} ({asset_class})")

        try:
            request = self._req_service.createRequest("GetBrokerStrategyInfoWithAssetClass")
            request.set("EMSX_BROKER", broker)
            request.set("EMSX_STRATEGY", strategy)
            request.set("EMSX_ASSET_CLASS", asset_class)

            logger.info(f"Sending GetBrokerStrategyInfoWithAssetClass request for {broker}/{strategy}")
            start_time = time.time()

            messages = await self._send_request_async(request)

            elapsed = time.time() - start_time
            logger.info(
                f"GetBrokerStrategyInfoWithAssetClass response received in {elapsed:.2f}s"
            )

            fields = []
            for msg in messages:
                if msg.hasElement("EMSX_STRATEGY_INFO"):
                    info_elem = msg.getElement("EMSX_STRATEGY_INFO")
                    for i in range(info_elem.numValues()):
                        entry = info_elem.getValueAsElement(i)
                        field_name = (
                            entry.getElementAsString("FieldName")
                            if entry.hasElement("FieldName")
                            else ""
                        )
                        disable = (
                            entry.getElementAsString("Disable")
                            if entry.hasElement("Disable")
                            else "0"
                        )
                        string_value = (
                            entry.getElementAsString("StringValue")
                            if entry.hasElement("StringValue")
                            else ""
                        )
                        fields.append({
                            "fieldName": field_name,
                            "disable": disable,
                            "stringValue": string_value,
                        })
                elif "Error" in str(msg.messageType()):
                    error_msg = msg_safe_str(
                        msg, "ERROR_MESSAGE", "Failed to get strategy info"
                    )
                    logger.warning(
                        f"GetBrokerStrategyInfo error for {broker}/{strategy}: {error_msg}"
                    )

            logger.info(
                f"Broker {broker} strategy {strategy} ({asset_class}): "
                f"{len(fields)} parameter fields"
            )
            return fields

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting strategy info for {broker}/{strategy}: {e}")
            raise HTTPException(500, f"Failed to get broker strategy info: {str(e)}")

    async def get_brokers(self, asset_class: str = "EQTY") -> List[str]:
        logger.info(f"Getting brokers for asset class {asset_class}")

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
                    error_msg = msg_safe_str(msg, "ERROR_MESSAGE", "Failed to get brokers")
                    logger.warning(f"GetBrokers error: {error_msg}")

            logger.info(f"Found {len(brokers)} brokers for asset class {asset_class}")
            return brokers

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting brokers: {e}")
            raise HTTPException(500, f"Failed to get brokers: {str(e)}")

    # ── Terminal trader ────────────────────────────────────────────────

    def get_terminal_trader_name(self) -> str:
        if self._settings.EMSXVIEW_TRADER_NAME:
            return self._settings.EMSXVIEW_TRADER_NAME
        votes: Dict[str, int] = {}
        for order in self._subscription_engine.orders.values():
            t = order.trader
            if t:
                votes[t] = votes.get(t, 0) + 1
        if votes:
            best = max(votes, key=votes.get)
            logger.debug(f"Auto-detected trader (fallback): {best} with {votes[best]} orders")
            return best
        return ""
