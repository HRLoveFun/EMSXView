"""
Abstract interface for the Bloomberg EMSX adapter.

Defines the public contract that BloombergEMSXService implements,
enabling test doubles and alternative data sources.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional, Any

from schemas import (
    Order, OrderFilters, ConnectionStatus,
    BatchUpdateRequest, BatchUpdateResponse,
    CancelRouteRequest, ModifyRouteRequest, RouteOrderRequest,
)


class BloombergEMSXAdapterInterface(ABC):
    """Public operations provided by the Bloomberg EMSX adapter."""

    @abstractmethod
    async def connect(self) -> bool:
        """Establish Bloomberg session(s) and start subscription threads."""

    @abstractmethod
    def disconnect(self) -> None:
        """Disconnect all sessions and stop background threads."""

    @abstractmethod
    def get_status(self) -> ConnectionStatus:
        """Return current connection status."""

    @abstractmethod
    async def get_orders(self, filters: Optional[OrderFilters] = None) -> List[Order]:
        """Return enriched orders from the live subscription cache."""

    @abstractmethod
    async def get_routes(self) -> List[dict]:
        """Return enriched routes from the live subscription cache."""

    @abstractmethod
    async def modify_order(self, order_id: str, field: str, value: Any) -> bool:
        """Modify a single EMSX order field."""

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an EMSX order."""

    @abstractmethod
    async def batch_update(self, request_data: BatchUpdateRequest) -> BatchUpdateResponse:
        """Apply a batch update to multiple orders."""

    @abstractmethod
    async def cancel_route(self, request_data: CancelRouteRequest) -> bool:
        """Cancel a route."""

    @abstractmethod
    async def modify_route(self, request_data: ModifyRouteRequest) -> bool:
        """Modify a route."""

    @abstractmethod
    async def route_order(self, request_data: RouteOrderRequest) -> dict:
        """Create a new route for an order."""

    @abstractmethod
    async def get_broker_strategies(self, broker: str, asset_class: str = "EQTY") -> List[str]:
        """List strategies available for a broker."""

    @abstractmethod
    async def get_broker_strategy_info(self, broker: str, strategy: str, asset_class: str = "EQTY") -> List[dict]:
        """Return parameter fields for a broker strategy."""

    @abstractmethod
    async def get_brokers(self, asset_class: str = "EQTY") -> List[str]:
        """List available brokers."""

    @abstractmethod
    def get_terminal_trader_name(self) -> str:
        """Return the terminal trader name."""
