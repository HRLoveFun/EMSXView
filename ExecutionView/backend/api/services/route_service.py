"""Route creation and modification business logic.

Centralises validation, pre-flight checks, and Bloomberg request
delegation so that both create and modify use the same strategy
parameter handling.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Mapping, Sequence

from fastapi import HTTPException

from schemas import RouteOrderRequest, ModifyRouteRequest

if TYPE_CHECKING:
    from services.bloomberg_interface import BloombergEMSXAdapterInterface

logger = logging.getLogger(__name__)

# Statuses that permit route creation
ROUTABLE_STATUSES = frozenset({"NEW", "ASSIGN", "WORKING", "PARTIAL", "SENT", "QUEUED"})
LIMIT_PRICE_RESET_SENTINEL = -99999
STOP_PRICE_RESET_SENTINEL = -1

# Per-broker EMSX_HAND_INSTRUCTION defaults — loaded once from JSON config
_HI_CONFIG_PATH = Path(__file__).resolve().parent.parent / "data" / "broker_hand_instruction.json"
_hand_instruction_map: dict[str, str] = {}


def _load_hand_instruction_map() -> dict[str, str]:
    try:
        if _HI_CONFIG_PATH.exists():
            with _HI_CONFIG_PATH.open("r", encoding="utf-8") as f:
                raw = json.load(f)
            return {k.strip().upper(): str(v).strip() for k, v in raw.items() if k[0] != "_" and v}
        else:
            logger.warning(
                "EMSX_HAND_INSTRUCTION config file not found: %s — all brokers will default to 'ANY'",
                _HI_CONFIG_PATH,
            )
    except (OSError, json.JSONDecodeError):
        logger.error(
            "Failed to load EMSX_HAND_INSTRUCTION config from %s — all brokers will default to 'ANY'",
            _HI_CONFIG_PATH,
            exc_info=True,
        )
    return {}


def _resolve_hand_instruction(broker: str) -> str:
    global _hand_instruction_map
    if not _hand_instruction_map:
        _hand_instruction_map = _load_hand_instruction_map()
    key = broker.strip().upper()
    if key in _hand_instruction_map:
        return _hand_instruction_map[key]
    logger.warning(
        "Broker '%s' not found in EMSX_HAND_INSTRUCTION config (%s) — defaulting to 'ANY'. "
        "Edit the JSON file to add an entry for this broker.",
        key,
        _HI_CONFIG_PATH,
    )
    return "ANY"


def validate_route_request(request: RouteOrderRequest, parent_order: Any) -> None:
    """Run pre-flight checks before sending a RouteEx request.

    Raises ``HTTPException`` on failure — suitable for direct use in
    FastAPI endpoint handlers.
    """
    if parent_order is None:
        raise HTTPException(404, f"Order {request.orderId} not found")

    if parent_order.status not in ROUTABLE_STATUSES:
        raise HTTPException(
            400,
            f"Order {request.orderId} has status '{parent_order.status}' — "
            f"only orders with status {', '.join(sorted(ROUTABLE_STATUSES))} can be routed",
        )

    if request.quantity > parent_order.remainingQuantity:
        raise HTTPException(
            400,
            f"Route quantity ({request.quantity}) exceeds remaining quantity "
            f"({parent_order.remainingQuantity})",
        )


def validate_trader_ownership(
    order_id: str,
    parent_trader: str | None,
    terminal_trader: str | None,
) -> None:
    """Verify the current terminal trader matches the order's trader."""
    if terminal_trader and parent_trader and terminal_trader.upper() != parent_trader.upper():
        raise HTTPException(
            403,
            f"Cannot route order {order_id}: assigned to trader "
            f"'{parent_trader}', but current trader is '{terminal_trader}'",
        )


def _coerce_strategy_field_entries(fields_data: Any) -> list[dict[str, Any]]:
    if fields_data is None:
        return []
    if not isinstance(fields_data, list):
        raise HTTPException(400, "Strategy fields must be a list")

    entries: list[dict[str, Any]] = []
    for index, raw_entry in enumerate(fields_data):
        if not isinstance(raw_entry, Mapping):
            raise HTTPException(400, "Strategy fields must be objects")

        disabled = bool(raw_entry.get("disabled", False))
        entries.append(
            {
                "fieldName": str(raw_entry.get("fieldName", "") or "").strip(),
                "value": "" if disabled else str(raw_entry.get("value", "") or ""),
                "indicator": 1 if disabled else 0,
                "_index": index,
            }
        )

    return entries


def build_strategy_elements(
    strategy_params: dict[str, Any] | None,
    *,
    catalog_field_names: Sequence[str] | None = None,
) -> list[dict[str, Any]] | None:
    """Normalise strategy params into ordered field-indicator pairs.

    Returns ``None`` when *strategy_params* is empty or missing required keys,
    so callers can short-circuit.

    When ``catalog_field_names`` is provided and the incoming field payload carries
    ``fieldName`` values, the result is reordered to match Bloomberg metadata and
    any omitted catalog fields are padded as ignored values.
    """
    if not strategy_params:
        return None

    strategy_name = strategy_params.get("strategyName", "")
    entries = _coerce_strategy_field_entries(strategy_params.get("fields", []))

    if not strategy_name:
        return None

    if not entries:
        return None

    if catalog_field_names:
        has_named_fields = any(entry["fieldName"] for entry in entries)
        if has_named_fields:
            if any(not entry["fieldName"] for entry in entries):
                raise HTTPException(400, "Strategy fields must either all include fieldName or all omit it")

            named_entries: dict[str, dict[str, Any]] = {}
            for entry in entries:
                field_name = entry["fieldName"]
                if field_name in named_entries:
                    raise HTTPException(400, f"Duplicate strategy field '{field_name}'")
                named_entries[field_name] = entry

            unknown_fields = sorted(set(named_entries).difference(catalog_field_names))
            if unknown_fields:
                raise HTTPException(
                    400,
                    f"Strategy fields do not match broker catalog: {', '.join(unknown_fields)}",
                )

            ordered_entries: list[dict[str, Any]] = []
            for field_name in catalog_field_names:
                ordered_entries.append(
                    named_entries.get(
                        field_name,
                        {
                            "fieldName": field_name,
                            "value": "",
                            "indicator": 1,
                            "_index": len(entries),
                        },
                    )
                )
            entries = ordered_entries

    return [{"value": entry["value"], "indicator": entry["indicator"]} for entry in entries]


def build_route_request_fields(
    request: RouteOrderRequest,
    parent_order: Any,
    *,
    terminal_trader: str | None,
    normalize_order_type: Callable[[str | None], str],
    order_type_uses_limit_price: Callable[[str], bool],
    order_type_uses_stop_price: Callable[[str], bool],
) -> dict[str, Any]:
    """Build the EMSX RouteEx field map from one normalized rule layer."""
    validate_route_request(request, parent_order)
    validate_trader_ownership(request.orderId, getattr(parent_order, "trader", None), terminal_trader)

    emsx_order_type = normalize_order_type(request.orderType)
    fields: dict[str, Any] = {
        "EMSX_SEQUENCE": int(request.orderId),
        "EMSX_TICKER": parent_order.symbol,
        "EMSX_BROKER": request.broker,
        "EMSX_AMOUNT": request.quantity,
        "EMSX_ORDER_TYPE": emsx_order_type,
        "EMSX_TIF": request.timeInForce,
        "EMSX_HAND_INSTRUCTION": _resolve_hand_instruction(request.broker),
    }

    if order_type_uses_limit_price(emsx_order_type) and request.price is not None:
        fields["EMSX_LIMIT_PRICE"] = request.price
    if order_type_uses_stop_price(emsx_order_type) and request.stopPrice is not None:
        fields["EMSX_STOP_PRICE"] = request.stopPrice
    if request.exchangeDestination:
        fields["EMSX_EXCHANGE_DESTINATION"] = request.exchangeDestination
    if request.notes:
        fields["EMSX_NOTES"] = request.notes

    return fields


def build_modify_route_request_fields(
    request: ModifyRouteRequest,
    cached_route: Any | None,
    *,
    normalize_order_type: Callable[[str | None], str],
    order_type_uses_limit_price: Callable[[str], bool],
    order_type_uses_stop_price: Callable[[str], bool],
) -> dict[str, Any]:
    """Build the EMSX ModifyRouteEx field map from one normalized rule layer."""
    fields: dict[str, Any] = {
        "EMSX_SEQUENCE": request.sequence,
        "EMSX_ROUTE_ID": request.routeId,
    }

    if request.amount is not None:
        fields["EMSX_AMOUNT"] = request.amount
    elif cached_route is not None:
        fields["EMSX_AMOUNT"] = cached_route.amount
    else:
        raise HTTPException(400, "Amount is required for route modification")

    requested_order_type = request.orderType or (cached_route.orderType if cached_route else "")
    order_type = normalize_order_type(requested_order_type)
    if not order_type:
        raise HTTPException(400, "Order type is required for route modification")
    fields["EMSX_ORDER_TYPE"] = order_type

    cached_order_type = normalize_order_type(cached_route.orderType if cached_route else "") if cached_route else ""
    fields["EMSX_TIF"] = request.tif or (cached_route.tif if cached_route else "DAY")

    limit_price_provided = "limitPrice" in request.model_fields_set
    stop_price_provided = "stopPrice" in request.model_fields_set

    if limit_price_provided:
        fields["EMSX_LIMIT_PRICE"] = LIMIT_PRICE_RESET_SENTINEL if request.limitPrice is None else request.limitPrice
    elif cached_order_type and order_type_uses_limit_price(cached_order_type) and not order_type_uses_limit_price(order_type):
        fields["EMSX_LIMIT_PRICE"] = LIMIT_PRICE_RESET_SENTINEL

    if stop_price_provided:
        fields["EMSX_STOP_PRICE"] = STOP_PRICE_RESET_SENTINEL if request.stopPrice is None else request.stopPrice
    elif cached_order_type and order_type_uses_stop_price(cached_order_type) and not order_type_uses_stop_price(order_type):
        fields["EMSX_STOP_PRICE"] = STOP_PRICE_RESET_SENTINEL

    if request.broker:
        fields["EMSX_BROKER"] = request.broker
    if request.exchangeDestination:
        fields["EMSX_EXCHANGE_DESTINATION"] = request.exchangeDestination
    if request.notes:
        fields["EMSX_NOTES"] = request.notes

    return fields
