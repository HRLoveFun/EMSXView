"""Concrete data access implementations adapting the existing Repository layer.

Bridges the gap between abstract ``platform_data.contracts.data_access``
interfaces and the concrete ``DataPipeline.storage`` repositories.  Each
access_impl method delegates to the corresponding repository method with
necessary parameter adaptation and return-type conversion
(DataFrame -> List[Dict], DTO construction, etc.).

Usage::

    from DataPipeline.storage.access_impl import DataAccessFactoryImpl
    factory = DataAccessFactoryImpl()
    fill_access = factory.create_fill_access()
    fills = fill_access.get_fills_for_date("20260601")
"""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from DataPipeline.config import Config
from DataPipeline.storage.dto import FillMetricsQueryDTO
from DataPipeline.storage.facade import DatabaseFacade

from platform_data.contracts.data_access import (
    DataAccessFactory,
    FillReadAccess,
    IntegratedDataReadAccess,
    MarketDataReadAccess,
    RegimeDataReadAccess,
)


def _df_to_dicts(df: pd.DataFrame, columns: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    if df is None or df.empty:
        return []
    if columns:
        existing = [c for c in columns if c in df.columns]
        df = df[existing]
    return df.to_dict(orient="records")


def _first_row(df: pd.DataFrame) -> Optional[Dict[str, Any]]:
    if df is None or df.empty:
        return None
    return df.iloc[0].to_dict()


class FillReadAccessImpl(FillReadAccess):

    def __init__(self, facade: DatabaseFacade) -> None:
        self._repo = facade.fills_read

    def get_fills_for_date(
        self, order_as_of_date: str, columns: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        df = self._repo.get_fills_for_date(order_as_of_date)
        return _df_to_dicts(df, columns)

    def get_routes_for_order(
        self, order_id: str, date: str
    ) -> List[Dict[str, Any]]:
        conn = self._repo._get_read_conn()
        try:
            df = pd.read_sql_query(
                "SELECT * FROM route_registry WHERE OrderId = ?",
                conn.raw_connection,
                params=[order_id],
            )
            return _df_to_dicts(df)
        finally:
            conn.close()

    def get_agg_fills_10s(
        self, order_id: str, route_id: str, date: str
    ) -> List[Dict[str, Any]]:
        df = self._repo.get_agg_fills_10s_for_date(date)
        if df.empty:
            return []
        mask = (df["OrderId"] == order_id) & (df["RouteId"] == route_id)
        return _df_to_dicts(df[mask])

    def get_processing_stats(
        self, start_date: str, end_date: str
    ) -> Dict[str, Any]:
        return self._repo.get_processing_stats()


class MarketDataReadAccessImpl(MarketDataReadAccess):

    def __init__(self, facade: DatabaseFacade) -> None:
        self._repo = facade.market_data_read

    def get_bdib_bars(
        self,
        ticker: str,
        date: str,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        df = self._repo.get_bdib_bars_for_date(ticker, date)
        if df.empty:
            return []
        if start_time:
            df = df[df["mkt_timestamp"] >= start_time]
        if end_time:
            df = df[df["mkt_timestamp"] <= end_time]
        return _df_to_dicts(df)

    def get_daily_summary(
        self, ticker: str, date: str
    ) -> Optional[Dict[str, Any]]:
        df = self._repo.get_daily_summary(ticker, start_date=date, end_date=date)
        return _first_row(df)

    def get_adv(
        self, ticker: str, date: str, windows: Tuple[int, ...] = (5, 20)
    ) -> Dict[int, float]:
        df = self._repo.get_daily_summary(ticker, start_date=date, end_date=date)
        if df.empty:
            return {w: 0.0 for w in windows}
        row = df.iloc[0]
        result: Dict[int, float] = {}
        for w in windows:
            col = f"adv_{w}d"
            if col in row:
                result[w] = float(row[col]) if pd.notna(row[col]) else 0.0
            else:
                result[w] = 0.0
        return result


class IntegratedDataReadAccessImpl(IntegratedDataReadAccess):

    def __init__(self, facade: DatabaseFacade) -> None:
        self._repo = facade.integrated_read

    def get_time_series(
        self, order_id: str, route_id: str, date: str
    ) -> List[Dict[str, Any]]:
        conn = self._repo._get_read_conn()
        try:
            df = pd.read_sql_query(
                f"SELECT mkt_timestamp, close, fill_px, fill_volume, volume, "
                f"cum_volume_pct, cum_fill_vwap, cum_vwap, cum_slippage_bps, "
                f"cum_tracking_error "
                f"FROM {Config.FILL_BDIB_TABLE} "
                f"WHERE OrderId = ? AND RouteId = ? AND order_as_of_date = ? "
                f"ORDER BY mkt_timestamp",
                conn.raw_connection,
                params=[order_id, route_id, date],
            )
            return _df_to_dicts(df)
        finally:
            conn.close()

    def get_tca_metrics(
        self, order_id: str, route_id: str, date: str
    ) -> Optional[Dict[str, Any]]:
        conn = self._repo._get_read_conn()
        try:
            df = pd.read_sql_query(
                f"SELECT cum_slippage_bps, cum_vwap, cum_fill_vwap, "
                f"cum_volume_pct, cum_tracking_error, cum_info_ratio, "
                f"cum_interval_volatility, equ_ticker "
                f"FROM {Config.FILL_BDIB_TABLE} "
                f"WHERE OrderId = ? AND RouteId = ? AND order_as_of_date = ? "
                f"ORDER BY mkt_timestamp DESC LIMIT 1",
                conn.raw_connection,
                params=[order_id, route_id, date],
            )
            return _first_row(df)
        finally:
            conn.close()


class RegimeDataReadAccessImpl(RegimeDataReadAccess):

    def __init__(self, facade: DatabaseFacade) -> None:
        self._repo = facade.regime_read

    def get_regime_labels(
        self, order_id: str, route_id: str, fill_id: str, date: str
    ) -> Optional[Dict[str, Any]]:
        df = self._repo.get_regime_labels(date, date, "vol_regime")
        if df.empty:
            return None
        mask = (
            (df["OrderId"] == order_id)
            & (df["RouteId"] == route_id)
            & (df["FillId"] == fill_id)
        )
        return _first_row(df[mask])

    def get_fill_metrics(
        self, order_id: str, route_id: str, fill_id: str, date: str
    ) -> Optional[Dict[str, Any]]:
        query = FillMetricsQueryDTO(start_date_iso=date, end_date_iso=date)
        try:
            df = self._repo.get_fill_metrics(query)
        except RuntimeError:
            return None
        if df.empty:
            return None
        mask = (
            (df["OrderId"] == order_id)
            & (df["RouteId"] == route_id)
            & (df["FillId"] == fill_id)
        )
        return _first_row(df[mask])


class DataAccessFactoryImpl(DataAccessFactory):
    """Concrete factory for data access objects.

    Accepts an optional ``DatabaseFacade`` or ``ConnectionManager`` for
    dependency injection.  When neither is provided a default
    ``DatabaseFacade`` is created from the standard configuration paths.

    Parameters
    ----------
    facade : DatabaseFacade, optional
        Pre-configured facade (e.g. with custom ConnectionManager for
        testing or path overrides).
    connection_manager : ConnectionManager, optional
        Alternative to ``facade`` — a new DatabaseFacade is created
        wrapping this ConnectionManager.  Ignored when ``facade`` is
        provided.
    """

    def __init__(
        self,
        facade: Optional[DatabaseFacade] = None,
        connection_manager: Optional[Any] = None,
    ) -> None:
        if facade is not None:
            self._facade = facade
        elif connection_manager is not None:
            self._facade = DatabaseFacade(connection_manager)
        else:
            self._facade = DatabaseFacade()

    def create_fill_access(self) -> FillReadAccess:
        return FillReadAccessImpl(self._facade)

    def create_market_data_access(self) -> MarketDataReadAccess:
        return MarketDataReadAccessImpl(self._facade)

    def create_integrated_access(self) -> IntegratedDataReadAccess:
        return IntegratedDataReadAccessImpl(self._facade)

    def create_regime_access(self) -> RegimeDataReadAccess:
        return RegimeDataReadAccessImpl(self._facade)
