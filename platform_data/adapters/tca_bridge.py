"""TCA query service bridge — lazy factory for CostView TCA service.

Provides a dependency injection registry that breaks the platform_data ↔ CostView
circular import chain. Consumers call get_tca_query_service(); CostView registers
its TcaQueryService implementation at startup via register_tca_service_impl().

Extracted from the formerly monolithic adapters.py (lines 1-124).
"""

from __future__ import annotations

import logging
from typing import Any

from platform_data.contracts.tca_service_protocol import TcaQueryServiceProtocol

logger_bridge = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# TCA Service DI Registry — breaks platform_data ↔ CostView circular dep
# ---------------------------------------------------------------------------

_tca_service_registry: dict[str, TcaQueryServiceProtocol] = {}


def register_tca_service_impl(impl: TcaQueryServiceProtocol, key: str = "default") -> None:
    """Register a TcaQueryServiceProtocol implementation.

    Called at application startup by CostView (or any module providing a TCA
    query service) to inject its implementation into the platform_data layer.

    Args:
        impl: An object conforming to TcaQueryServiceProtocol.
        key: Registry key (default "default").
    """
    _tca_service_registry[key] = impl


def get_tca_query_service(key: str = "default") -> TcaQueryServiceProtocol:
    """Return the registered TCA query service instance.

    If no implementation has been registered, falls back to lazy-importing
    CostView.src.tca_query_service.TcaQueryService (backward compatibility).

    Args:
        key: Registry key (default "default").

    Returns:
        A TcaQueryServiceProtocol-compatible instance.
    """
    if key in _tca_service_registry:
        return _tca_service_registry[key]

    # No implementation registered — caller must register TcaQueryService
    # before using TCA features. In standalone CostView mode, CostView/api/main.py
    # calls register_tca_service_impl() at startup.
    raise RuntimeError(
        "No TcaQueryService implementation registered. "
        "Ensure register_tca_service_impl() is called at application startup "
        "(e.g. from CostView/api/main.py:_setup_dependencies())."
    )


# ---------------------------------------------------------------------------
# Daily summary reader — replaces RawBDIBDB direct import
# ---------------------------------------------------------------------------

# P2-D3: Import ConnectionManagerProtocol instead of the concrete class.
# AccessTier is a lightweight enum from DataPipeline's public API surface.
from data_access import AccessTier
from platform_data.contracts.protocols import ConnectionManagerProtocol
from platform_data.contracts import (
    ScorecardCohortMetrics,
    ScorecardFilters,
    ScorecardReport,
    TcaFilters,
    TcaReport,
)

# ── Re-export constants from canonical location ─────────────────────────────────
# Imported from platform_data.contracts.db_constants which is the single source
# of truth. Direct consumers should import from contracts directly.
from platform_data.contracts.db_constants import (
    BARS_PER_YEAR,
    BDIB_DAILY_SUMMARY_TABLE,
    RAW_BDIB_TABLE,
)


class _ConnectionManagerDailySummaryReader:
    """Read-only daily summary access via ConnectionManager.

    Replaces the direct ``RawBDIBDB`` instantiation that previously
    coupled platform_data to a CostView legacy DB class.
    """

    def __init__(self, connection_manager: ConnectionManagerProtocol | None = None):
        if connection_manager is None:
            raise ValueError(
                "ConnectionManager must be provided to _ConnectionManagerDailySummaryReader. "
                "Inject via platform_data.contracts.protocols.ConnectionManagerProtocol."
            )
        self._mgr = connection_manager

    def get_latest_daily_summary(
        self,
        limit: int = 25,
        trade_date: str | None = None,
    ):
        """Return the latest available daily-summary rows as a DataFrame."""
        import pandas as pd

        empty = pd.DataFrame(
            columns=[
                "equ_ticker",
                "trade_date",
                "total_volume",
                "daily_close",
                "daily_volatility",
                "intraday_volatility",
                "adv_5d",
                "adv_20d",
            ]
        )
        conn = None
        try:
            conn = self._mgr.get_connection("raw_bdib", AccessTier.READ)
            resolved_trade_date = trade_date
            if not resolved_trade_date:
                cursor = conn.execute(
                    f"SELECT MAX(trade_date) FROM {BDIB_DAILY_SUMMARY_TABLE}"
                )
                resolved_trade_date = cursor.fetchone()[0]

            if not resolved_trade_date:
                return empty

            return pd.read_sql_query(
                f"SELECT equ_ticker, trade_date, total_volume, daily_close, daily_volatility, "
                f"intraday_volatility, adv_5d, adv_20d "
                f"FROM {BDIB_DAILY_SUMMARY_TABLE} "
                "WHERE trade_date = ? "
                "ORDER BY COALESCE(total_volume, 0) DESC, equ_ticker ASC "
                "LIMIT ?",
                conn.raw_connection,
                params=[resolved_trade_date, limit],
            )
        except FileNotFoundError:
            # 只读模式下 raw_bdib.db 缺失 → 返回空 DataFrame（降级, 009）
            return empty
        finally:
            if conn is not None:
                conn.close()


# ---------------------------------------------------------------------------
# CostView bridge registration — single entry point for backend/costview merge
# ---------------------------------------------------------------------------


def register_costview_bridge_dependencies() -> None:
    """注册 CostView 分析层依赖（TCA 查询实现 + DataPipeline 配置）。

    集中封装对 ``CostView.src`` / ``DataPipeline.config`` 的 import，使
    backend 桥接模块只依赖 platform_data，避免 backend → CostView.src 的
    深度 import（违反模块边界 AP-01）。CostView 独立部署与 core 单进程
    merge 模式共用本函数，注册逻辑幂等。

    调用方：
    - ``CostView/api/main.py``（独立 :8002）
    - ``backend/api/routers/costview.py``（core :3000 merge 模式）
    """
    from CostView.src.tca_query_service import TcaQueryService

    register_tca_service_impl(TcaQueryService())

    from data_access.config import Config
    from platform_data.config_bridge import register_config_impl

    register_config_impl(Config)
    logger_bridge.info("CostView bridge dependencies registered (merge mode)")
