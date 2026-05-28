"""
Stable delta-event schema for realtime order/route broadcasting.

Every event has: type, entity, key, version, timestamp, and a data/patch payload.
"""

from __future__ import annotations

import time
from typing import Any, Literal


def make_event(
    *,
    event_type: Literal["snapshot", "update", "delete"],
    entity: Literal["order", "route"],
    key: str,
    data: dict[str, Any],
    version: int | None = None,
) -> dict[str, Any]:
    """Build a canonical delta event dict ready for JSON serialization."""
    return {
        "type": event_type,
        "entity": entity,
        "key": key,
        "version": version,
        "ts": time.time(),
        "data": data,
    }


def order_delta(
    event_type: Literal["snapshot", "update", "delete"],
    order_dict: dict[str, Any],
) -> dict[str, Any]:
    """Convenience: build an order delta from an Order.model_dump() dict."""
    return make_event(
        event_type=event_type,
        entity="order",
        key=str(order_dict.get("id", "")),
        data=order_dict,
        version=int(order_dict.get("id", 0)) if event_type != "delete" else None,
    )


def route_delta(
    event_type: Literal["snapshot", "update", "delete"],
    route_dict: dict[str, Any],
) -> dict[str, Any]:
    """Convenience: build a route delta from a Route.model_dump() dict."""
    return make_event(
        event_type=event_type,
        entity="route",
        key=str(route_dict.get("id", "")),
        data=route_dict,
        version=route_dict.get("sequence"),
    )
