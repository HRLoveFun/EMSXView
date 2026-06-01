"""Data access layer abstract contracts.

Defines the interfaces that all data access implementations must satisfy.
Business logic depends on these contracts — never on concrete storage
implementations like ConnectionManager or specific repository classes.

This enables:
    - Unit testing with mock implementations
    - Storage backend substitution (SQLite -> PostgreSQL)
    - Clear separation of concerns between data and business layers

Usage in CostView/TcaQueryService::

    from platform_data.contracts.data_access import (
        DataAccessFactory,
        FillReadAccess,
    )

    class TcaQueryService:
        def __init__(self, fill_access: FillReadAccess, ...):
            self._fills = fill_access
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple


class FillReadAccess(ABC):
    """Read-only access to processed fill data."""

    @abstractmethod
    def get_fills_for_date(
        self, order_as_of_date: str, columns: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        ...

    @abstractmethod
    def get_routes_for_order(
        self, order_id: str, date: str
    ) -> List[Dict[str, Any]]:
        ...

    @abstractmethod
    def get_agg_fills_10s(
        self, order_id: str, route_id: str, date: str
    ) -> List[Dict[str, Any]]:
        ...

    @abstractmethod
    def get_processing_stats(
        self, start_date: str, end_date: str
    ) -> Dict[str, Any]:
        ...


class MarketDataReadAccess(ABC):
    """Read-only access to market data (BDIB bars, daily summaries)."""

    @abstractmethod
    def get_bdib_bars(
        self,
        ticker: str,
        date: str,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        ...

    @abstractmethod
    def get_daily_summary(
        self, ticker: str, date: str
    ) -> Optional[Dict[str, Any]]:
        ...

    @abstractmethod
    def get_adv(
        self, ticker: str, date: str, windows: Tuple[int, ...] = (5, 20)
    ) -> Dict[int, float]:
        ...


class IntegratedDataReadAccess(ABC):
    """Read-only access to integrated fill+BDIB data with TCA metrics."""

    @abstractmethod
    def get_time_series(
        self, order_id: str, route_id: str, date: str
    ) -> List[Dict[str, Any]]:
        ...

    @abstractmethod
    def get_tca_metrics(
        self, order_id: str, route_id: str, date: str
    ) -> Optional[Dict[str, Any]]:
        ...


class RegimeDataReadAccess(ABC):
    """Read-only access to regime classification and attribution data."""

    @abstractmethod
    def get_regime_labels(
        self, order_id: str, route_id: str, fill_id: str, date: str
    ) -> Optional[Dict[str, Any]]:
        ...

    @abstractmethod
    def get_fill_metrics(
        self, order_id: str, route_id: str, fill_id: str, date: str
    ) -> Optional[Dict[str, Any]]:
        ...


class DataAccessFactory(ABC):
    """Factory for creating data access implementations.

    Injected at application startup — business logic receives this
    factory and calls create_* methods to obtain access objects.
    """

    @abstractmethod
    def create_fill_access(self) -> FillReadAccess:
        ...

    @abstractmethod
    def create_market_data_access(self) -> MarketDataReadAccess:
        ...

    @abstractmethod
    def create_integrated_access(self) -> IntegratedDataReadAccess:
        ...

    @abstractmethod
    def create_regime_access(self) -> RegimeDataReadAccess:
        ...
