"""Unified adapter entry points for the logical data domain.

This module does not collapse storage technologies into a single database.
Instead, it defines a stable entry layer that separates:

- operational execution data owned by Execution
- analytical market/fill/TCA data owned by CostView
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from CostView.src.raw_bdib_db import RawBDIBDB
from CostView.src.tca_query_service import TcaFilters, TcaQueryService, TcaReport


@dataclass(frozen=True)
class MarketDailySnapshotRow:
    equ_ticker: str
    trade_date: str
    daily_close: float | None
    daily_volatility: float | None
    intraday_volatility: float | None
    total_volume: float | None
    adv_5d: float | None
    adv_20d: float | None


@dataclass(frozen=True)
class MarketSnapshot:
    trade_date: str | None
    row_count: int
    rows: list[MarketDailySnapshotRow]


@dataclass(frozen=True)
class ExecutionOperationalDataAdapter:
    """Canonical adapter for Execution-owned operational data.

    Wraps the existing RepositoryProvider so callers integrate with one
    stable interface rather than depending on concrete repository layout.
    """

    provider: Any

    @property
    def is_active(self) -> bool:
        return bool(self.provider and self.provider.is_active)

    def describe(self) -> dict[str, str]:
        return {
            "domain": "execution-operational",
            "owner": "Execution",
            "storage": "PostgreSQL + in-memory fallback",
            "entrypoint": "RepositoryProvider",
        }

    async def load_orders(self, limit: int = 5000) -> list[dict[str, Any]]:
        return await self.provider.load_orders(limit=limit)

    async def load_routes(self, limit: int = 10000) -> list[dict[str, Any]]:
        return await self.provider.load_routes(limit=limit)

    async def persist_order(self, **kwargs: Any) -> bool:
        return await self.provider.persist_order(**kwargs)

    async def persist_route(self, **kwargs: Any) -> bool:
        return await self.provider.persist_route(**kwargs)

    async def persist_audit_event(self, **kwargs: Any) -> bool:
        return await self.provider.persist_audit_event(**kwargs)


@dataclass(frozen=True)
class CostViewAnalyticsAdapter:
    """Canonical adapter for CostView-owned analytical data."""

    query_service_factory: Callable[[], TcaQueryService] = TcaQueryService

    def describe(self) -> dict[str, str]:
        return {
            "domain": "costview-analytics",
            "owner": "CostView",
            "storage": "SQLite analytical stores",
            "entrypoint": "TcaQueryService",
        }

    def build_tca_report(self, filters: TcaFilters) -> TcaReport:
        return self.query_service_factory().build_tca_report(filters)


@dataclass(frozen=True)
class MarketReferenceDataAdapter:
    """Canonical adapter for MarketView-facing market reference data."""

    daily_summary_db_factory: Callable[[], RawBDIBDB] = RawBDIBDB

    def describe(self) -> dict[str, str]:
        return {
            "domain": "market-reference",
            "owner": "CostView market-data pipeline",
            "storage": "SQLite bdib_daily_summary",
            "entrypoint": "RawBDIBDB",
        }

    def get_market_snapshot(self, limit: int = 25, trade_date: str | None = None) -> MarketSnapshot:
        db = self.daily_summary_db_factory()
        frame = db.get_latest_daily_summary(limit=limit, trade_date=trade_date)
        if frame.empty:
            return MarketSnapshot(trade_date=trade_date, row_count=0, rows=[])

        rows = [
            MarketDailySnapshotRow(
                equ_ticker=str(row["equ_ticker"]),
                trade_date=str(row["trade_date"]),
                daily_close=_to_optional_float(row.get("daily_close")),
                daily_volatility=_to_optional_float(row.get("daily_volatility")),
                intraday_volatility=_to_optional_float(row.get("intraday_volatility")),
                total_volume=_to_optional_float(row.get("total_volume")),
                adv_5d=_to_optional_float(row.get("adv_5d")),
                adv_20d=_to_optional_float(row.get("adv_20d")),
            )
            for _, row in frame.iterrows()
        ]
        resolved_trade_date = rows[0].trade_date if rows else trade_date
        return MarketSnapshot(trade_date=resolved_trade_date, row_count=len(rows), rows=rows)


@dataclass(frozen=True)
class PlatformDataAccess:
    """Unified logical data-domain entry point for platform code."""

    operational: ExecutionOperationalDataAdapter | None
    market: MarketReferenceDataAdapter
    analytics: CostViewAnalyticsAdapter


def build_platform_data_access(
    repository_provider: Any | None = None,
    *,
    market_db_factory: Callable[[], RawBDIBDB] = RawBDIBDB,
    query_service_factory: Callable[[], TcaQueryService] = TcaQueryService,
) -> PlatformDataAccess:
    operational = (
        ExecutionOperationalDataAdapter(repository_provider)
        if repository_provider is not None
        else None
    )
    market = MarketReferenceDataAdapter(daily_summary_db_factory=market_db_factory)
    analytics = CostViewAnalyticsAdapter(query_service_factory=query_service_factory)
    return PlatformDataAccess(operational=operational, market=market, analytics=analytics)


def _to_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric != numeric:
        return None
    return numeric