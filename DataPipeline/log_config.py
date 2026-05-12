"""Logging configuration — formats, retention, and execution history policies."""

from __future__ import annotations


class LoggingConfig:
    LOG_FORMAT: str = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    LOG_DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"

    LOG_RETENTION_DAYS: int = 30
    LOG_DEBUG_RETENTION_DAYS: int = 7

    EXECUTION_HISTORY_SOURCE_POLICY: dict[str, tuple[str, ...]] = {
        "fills": ("emsx.history:GetFills",),
        "orders": ("costview.fill-rollup", "executionview.orders_projection"),
        "routes": ("costview.fill-rollup", "executionview.routes_projection"),
        "route_events": ("emsx.history:GetFills", "executionview.audit_events"),
    }
    EXECUTION_HISTORY_REFRESH_POLICY: dict[str, str] = {
        "fills": "incremental-per-fetch",
        "orders": "rebuild-per-processed-date;patch-from-executionview-when-available",
        "routes": "rebuild-per-processed-date;patch-from-executionview-when-available",
        "route_events": "append-per-fill;patch-from-executionview-audit-when-available",
    }
