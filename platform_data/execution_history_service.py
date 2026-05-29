from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Optional

from DataPipeline import AccessTier, Config, ConnectionManager


class ExecutionHistoryQueryService:
    """Read fills-centric execution history from processed_fills.db."""

    def __init__(
        self,
        connection_manager: Optional[ConnectionManager] = None,
        proc_fills_db_path: str | None = None,
        raw_fills_db_path: str | None = None,
    ):
        if connection_manager is not None:
            self._mgr = connection_manager
        elif proc_fills_db_path or raw_fills_db_path:
            overrides: dict[str, Path] = {}
            if proc_fills_db_path:
                overrides["processed_fills"] = Path(proc_fills_db_path)
            if raw_fills_db_path:
                overrides["raw_fills"] = Path(raw_fills_db_path)
            self._mgr = ConnectionManager(path_overrides=overrides)
        else:
            self._mgr = ConnectionManager()

    def list_fill_history(
        self,
        *,
        limit: int = 100,
        order_id: str | None = None,
        route_id: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict[str, Any]]:
        if not self._mgr.database_exists("processed_fills"):
            return []

        where_sql, params = self._build_processed_filters(
            order_id=order_id,
            route_id=route_id,
            start_date=start_date,
            end_date=end_date,
        )

        raw_join = ""
        raw_source_date = "NULL AS source_date"
        raw_fetched_at = "NULL AS fetched_at"
        if self._mgr.database_exists("raw_fills"):
            raw_join = f"""
                LEFT JOIN raw.{Config.RAW_FILLS_TABLE} raw
                  ON CAST(raw.OrderId AS TEXT) = CAST(p.OrderId AS TEXT)
                 AND CAST(raw.RouteId AS TEXT) = CAST(p.RouteId AS TEXT)
                 AND CAST(raw.FillId AS TEXT) = CAST(p.FillId AS TEXT)
            """
            raw_source_date = "raw.source_date AS source_date"
            raw_fetched_at = "raw.fetched_at AS fetched_at"

        query = f"""
            SELECT
                CAST(p.OrderId AS TEXT) AS order_id,
                CAST(p.RouteId AS TEXT) AS route_id,
                CAST(p.FillId AS TEXT) AS fill_id,
                p.order_as_of_date AS order_as_of_date,
                {raw_source_date},
                p.local_fill_datetime AS local_fill_datetime,
                p.exchange_exec_time AS exchange_exec_time,
                p.route_as_of_time AS route_as_of_time,
                p.DateTimeOfFill AS ny_fill_datetime,
                p.Broker AS broker,
                p.StrategyType AS strategy_type,
                p.algo AS algo,
                p.TraderName AS trader_name,
                p.Exchange AS exchange,
                rr.Side AS side,
                rr.equ_ticker AS equ_ticker,
                rr.ccy_ticker AS ccy_ticker,
                p.ExecType AS exec_type,
                p.Amount AS amount,
                p.RouteShares AS route_shares,
                p.FillPrice AS fill_price,
                p.FillShares AS fill_shares,
                {raw_fetched_at}
            FROM {Config.PROCESSED_FILLS_TABLE} p
            LEFT JOIN route_registry rr
              ON CAST(rr.OrderId AS TEXT) = CAST(p.OrderId AS TEXT)
             AND CAST(rr.RouteId AS TEXT) = CAST(p.RouteId AS TEXT)
            {raw_join}
            {where_sql}
            ORDER BY p.order_as_of_date DESC,
                     COALESCE(p.local_fill_datetime, p.DateTimeOfFill) DESC,
                     CAST(p.OrderId AS TEXT) DESC,
                     CAST(p.RouteId AS TEXT) DESC,
                     CAST(p.FillId AS TEXT) DESC
            LIMIT ?
        """
        params.append(limit)
        return self._fetch_rows(query, params, attach_raw=self._mgr.database_exists("raw_fills"))

    def list_order_history(
        self,
        *,
        limit: int = 100,
        order_id: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict[str, Any]]:
        if not self._mgr.database_exists("processed_fills"):
            return []

        where_sql, params = self._build_processed_filters(
            order_id=order_id,
            route_id=None,
            start_date=start_date,
            end_date=end_date,
        )

        query = f"""
            SELECT
                CAST(p.OrderId AS TEXT) AS order_id,
                p.order_as_of_date AS order_as_of_date,
                MAX(rr.equ_ticker) AS equ_ticker,
                MAX(rr.Side) AS side,
                COUNT(DISTINCT CAST(p.RouteId AS TEXT)) AS route_count,
                COUNT(*) AS fill_count,
                SUM(COALESCE(p.FillShares, 0)) AS total_fill_shares,
                CASE
                    WHEN SUM(COALESCE(p.FillShares, 0)) = 0 THEN NULL
                    ELSE SUM(COALESCE(p.FillPrice, 0) * COALESCE(p.FillShares, 0)) / SUM(COALESCE(p.FillShares, 0))
                END AS average_fill_price,
                MIN(COALESCE(p.local_fill_datetime, p.DateTimeOfFill)) AS first_fill_time,
                MAX(COALESCE(p.local_fill_datetime, p.DateTimeOfFill)) AS last_fill_time
            FROM {Config.PROCESSED_FILLS_TABLE} p
            LEFT JOIN route_registry rr
              ON CAST(rr.OrderId AS TEXT) = CAST(p.OrderId AS TEXT)
             AND CAST(rr.RouteId AS TEXT) = CAST(p.RouteId AS TEXT)
            {where_sql}
            GROUP BY CAST(p.OrderId AS TEXT), p.order_as_of_date
            ORDER BY p.order_as_of_date DESC,
                     last_fill_time DESC,
                     CAST(p.OrderId AS TEXT) DESC
            LIMIT ?
        """
        params.append(limit)
        return self._fetch_rows(query, params)

    def list_route_history(
        self,
        *,
        limit: int = 100,
        order_id: str | None = None,
        route_id: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict[str, Any]]:
        if not self._mgr.database_exists("processed_fills"):
            return []

        where_sql, params = self._build_processed_filters(
            order_id=order_id,
            route_id=route_id,
            start_date=start_date,
            end_date=end_date,
        )

        query = f"""
            SELECT
                CAST(p.OrderId AS TEXT) AS order_id,
                CAST(p.RouteId AS TEXT) AS route_id,
                p.order_as_of_date AS order_as_of_date,
                MAX(p.Broker) AS broker,
                MAX(p.algo) AS algo,
                MAX(p.TraderName) AS trader_name,
                MAX(p.Exchange) AS exchange,
                MAX(rr.Side) AS side,
                MAX(rr.equ_ticker) AS equ_ticker,
                COUNT(*) AS fill_count,
                SUM(COALESCE(p.FillShares, 0)) AS total_fill_shares,
                CASE
                    WHEN SUM(COALESCE(p.FillShares, 0)) = 0 THEN NULL
                    ELSE SUM(COALESCE(p.FillPrice, 0) * COALESCE(p.FillShares, 0)) / SUM(COALESCE(p.FillShares, 0))
                END AS average_fill_price,
                MIN(COALESCE(p.local_fill_datetime, p.DateTimeOfFill)) AS first_fill_time,
                MAX(COALESCE(p.local_fill_datetime, p.DateTimeOfFill)) AS last_fill_time
            FROM {Config.PROCESSED_FILLS_TABLE} p
            LEFT JOIN route_registry rr
              ON CAST(rr.OrderId AS TEXT) = CAST(p.OrderId AS TEXT)
             AND CAST(rr.RouteId AS TEXT) = CAST(p.RouteId AS TEXT)
            {where_sql}
            GROUP BY CAST(p.OrderId AS TEXT), CAST(p.RouteId AS TEXT), p.order_as_of_date
            ORDER BY p.order_as_of_date DESC,
                     last_fill_time DESC,
                     CAST(p.OrderId AS TEXT) DESC,
                     CAST(p.RouteId AS TEXT) DESC
            LIMIT ?
        """
        params.append(limit)
        return self._fetch_rows(query, params)

    def _build_processed_filters(
        self,
        *,
        order_id: str | None,
        route_id: str | None,
        start_date: str | None,
        end_date: str | None,
    ) -> tuple[str, list[Any]]:
        resolved_start = start_date or end_date
        resolved_end = end_date or start_date
        clauses: list[str] = []
        params: list[Any] = []

        if resolved_start is not None:
            clauses.append("p.order_as_of_date >= ?")
            params.append(resolved_start)
        if resolved_end is not None:
            clauses.append("p.order_as_of_date <= ?")
            params.append(resolved_end)
        if order_id is not None:
            clauses.append("CAST(p.OrderId AS TEXT) = ?")
            params.append(str(order_id))
        if route_id is not None:
            clauses.append("CAST(p.RouteId AS TEXT) = ?")
            params.append(str(route_id))

        if not clauses:
            return "", params
        return "WHERE " + " AND ".join(clauses), params

    def _fetch_rows(
        self,
        query: str,
        params: list[Any],
        *,
        attach_raw: bool = False,
    ) -> list[dict[str, Any]]:
        conn = self._mgr.get_connection("processed_fills", AccessTier.READ, row_factory=sqlite3.Row)
        try:
            if attach_raw:
                raw_path = self._mgr.get_path("raw_fills")
                conn.execute("ATTACH DATABASE ? AS raw", [str(raw_path)])
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()
