"""Regime repository — read/write access to regime.db.

Implements RegimeReadRepository and RegimeWriteRepository Protocols
using ConnectionManager.

Merges functionality from:
- CostView.src.attribution.repositories.SqliteRegimeRepository
- CostView.src.attribution.repositories.SqliteAttributionConfigRepository
- CostView.src.regime.schema (connect/ensure_schema_current)
- CostView.src.storage.regime_reader
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd

from DataPipeline.storage.connection import AccessTier, ConnectionManager
from DataPipeline.storage.dto import (
    AttributionConfigDTO,
    AttributionRowDTO,
    FillMetricsQueryDTO,
    PipelineRunDTO,
    PipelineRunResultDTO,
)
from ._base import BaseRepository

logger = logging.getLogger(__name__)


# ── DDL and SQL constants (migrated from attribution/repositories.py) ──

_SNAPSHOT_DDL = """
CREATE TABLE IF NOT EXISTS audit_research_snapshots (
    run_id           INTEGER PRIMARY KEY,
    stage_name       TEXT NOT NULL,
    config_version   TEXT NOT NULL,
    start_date       TEXT NOT NULL,
    end_date         TEXT NOT NULL,
    rows_written     INTEGER NOT NULL,
    rows_total       INTEGER NOT NULL,
    snapshot_sha256  TEXT NOT NULL,
    created_at       TIMESTAMP NOT NULL
)
"""

_METRICS_UPSERT_SQL = """
INSERT INTO fill_attribution_metrics
  (OrderId, RouteId, FillId, order_as_of_date_iso, config_version,
   market_code, broker, algo, side, fill_shares, fill_price,
   route_shares, pct_adv, participation_rate,
   arrival_px, interval_vwap,
   mid_at_fill, mid_fill_plus_1m, mid_fill_plus_5m, mid_fill_plus_30m,
   is_bps, vwap_bps, reversal_1m_bps, reversal_5m_bps, reversal_30m_bps,
   data_quality_flags, source_version, ingested_at)
VALUES (?,?,?,?,?, ?,?,?,?,?,?, ?,?,?, ?,?, ?,?,?,?, ?,?,?,?,?, ?,?,?)
ON CONFLICT(OrderId, RouteId, FillId, order_as_of_date_iso, config_version)
DO UPDATE SET
   market_code=excluded.market_code,
   broker=excluded.broker, algo=excluded.algo, side=excluded.side,
   fill_shares=excluded.fill_shares, fill_price=excluded.fill_price,
   route_shares=excluded.route_shares, pct_adv=excluded.pct_adv,
   participation_rate=excluded.participation_rate,
   arrival_px=excluded.arrival_px, interval_vwap=excluded.interval_vwap,
   mid_at_fill=excluded.mid_at_fill,
   mid_fill_plus_1m=excluded.mid_fill_plus_1m,
   mid_fill_plus_5m=excluded.mid_fill_plus_5m,
   mid_fill_plus_30m=excluded.mid_fill_plus_30m,
   is_bps=excluded.is_bps, vwap_bps=excluded.vwap_bps,
   reversal_1m_bps=excluded.reversal_1m_bps,
   reversal_5m_bps=excluded.reversal_5m_bps,
   reversal_30m_bps=excluded.reversal_30m_bps,
   data_quality_flags=excluded.data_quality_flags,
   source_version=excluded.source_version,
   ingested_at=excluded.ingested_at
"""


class SqliteRegimeReadRepository(BaseRepository):
    """Read access to regime labels, distributions, and config."""

    def __init__(self, connection_manager=None):
        super().__init__(connection_manager, database="regime")

    def _ensure_schema(self):
        """Ensure regime.db schema is current before reads."""
        try:
            from CostView.src.regime.schema import ensure_schema_current
            ensure_schema_current(self._mgr.get_path("regime"))
        except Exception:
            pass  # schema init may fail if regime module not fully loaded

    def get_regime_distribution(
        self,
        start_date: str,
        end_date: str,
        regime_dim: str = "vol_regime",
        config_version: Optional[str] = None,
    ) -> List[Tuple[str, str, str, int]]:
        """Return (date, market_code, regime_label, count) tuples."""
        self._ensure_schema()
        if config_version is None:
            config_version = self.get_active_config_version()
        if config_version is None:
            return []

        conn = self._get_read_conn()
        try:
            sql = f"""
                SELECT trade_date AS date, market_code,
                       COALESCE({regime_dim}, 'none') AS regime, COUNT(*) AS n
                FROM fill_regime_labels
                WHERE config_version = ?
                  AND trade_date BETWEEN ? AND ?
                GROUP BY trade_date, market_code, COALESCE({regime_dim}, 'none')
                ORDER BY trade_date, market_code
            """
            cur = conn.execute(sql, (config_version, start_date, end_date))
            return cur.fetchall()
        finally:
            conn.close()

    def get_active_config_version(self) -> Optional[str]:
        """Return the active regime config version."""
        self._ensure_schema()
        conn = self._get_read_conn()
        try:
            row = conn.execute(
                "SELECT version_id FROM audit_regime_config_versions "
                "WHERE is_active=1 LIMIT 1"
            ).fetchone()
            return row[0] if row else None
        finally:
            conn.close()

    def get_regime_labels(
        self, start_date_iso: str, end_date_iso: str,
        regime_dim: str, *,
        regime_config_version: Optional[str] = None,
    ) -> pd.DataFrame:
        """Get regime labels for a date range and dimension."""
        self._ensure_schema()
        if regime_config_version is None:
            regime_config_version = self.get_active_config_version()
        if regime_config_version is None:
            return pd.DataFrame()

        conn = self._get_read_conn()
        try:
            sql = f"""SELECT OrderId, RouteId, FillId, order_as_of_date_iso,
                             {regime_dim} AS regime_value
                      FROM fill_regime_labels
                      WHERE config_version = ?
                        AND order_as_of_date_iso BETWEEN ? AND ?"""
            return pd.read_sql_query(
                sql, conn.raw_connection,
                params=(regime_config_version, start_date_iso, end_date_iso),
            )
        finally:
            conn.close()

    def get_fill_metrics(self, query: FillMetricsQueryDTO) -> pd.DataFrame:
        """Load fill_attribution_metrics optionally joined with regime labels."""
        self._ensure_schema()
        if query.config_version is None:
            config_version = self.get_active_config_version()
            if config_version is None:
                raise RuntimeError("no active attribution config")
        else:
            config_version = query.config_version

        base_sql = """
            SELECT fam.OrderId, fam.RouteId, fam.FillId, fam.order_as_of_date_iso,
                   fam.market_code, fam.broker, fam.algo, fam.side,
                   fam.fill_shares, fam.fill_price, fam.route_shares,
                   fam.pct_adv, fam.participation_rate,
                   fam.is_bps, fam.vwap_bps,
                   fam.reversal_1m_bps, fam.reversal_5m_bps, fam.reversal_30m_bps
            FROM fill_attribution_metrics fam
            WHERE fam.config_version = ?
              AND fam.order_as_of_date_iso BETWEEN ? AND ?
        """
        conn = self._get_read_conn()
        try:
            df = pd.read_sql_query(
                base_sql, conn.raw_connection,
                params=(config_version, query.start_date_iso, query.end_date_iso),
            )
            if query.regime_dim:
                reg_df = pd.read_sql_query(
                    f"""SELECT OrderId, RouteId, FillId, order_as_of_date_iso,
                               {query.regime_dim} AS regime_value
                        FROM fill_regime_labels
                        WHERE config_version = (
                            SELECT version_id FROM audit_regime_config_versions
                            WHERE is_active = 1 LIMIT 1
                        )
                          AND order_as_of_date_iso BETWEEN ? AND ?""",
                    conn.raw_connection,
                    params=(query.start_date_iso, query.end_date_iso),
                )
                df = df.merge(
                    reg_df,
                    on=["OrderId", "RouteId", "FillId", "order_as_of_date_iso"],
                    how="left",
                )
                df = df.rename(columns={"regime_value": query.regime_dim})
        finally:
            conn.close()
        return df

    def get_active_config(self) -> Optional[AttributionConfigDTO]:
        """Return the active attribution config, or None."""
        self._ensure_schema()
        conn = self._get_read_conn()
        try:
            row = conn.execute(
                "SELECT version_id, bench_methods, reversal_windows_min, "
                "winsor_pct, adv_window_days, bootstrap_n, min_cell_n, description "
                "FROM audit_attribution_config_versions WHERE is_active = 1 LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        return AttributionConfigDTO(
            version_id=row[0],
            bench_methods=[s.strip() for s in str(row[1]).split(",") if s.strip()],
            reversal_windows_min=[int(x.strip()) for x in str(row[2]).split(",") if x.strip()],
            winsor_pct=float(row[3]),
            adv_window_days=int(row[4]),
            bootstrap_n=int(row[5]),
            min_cell_n=int(row[6]),
            description=row[7],
        )

    def get_adv_map(
        self, yyyymmdd: str, tickers: Iterable[str],
    ) -> Dict[str, float]:
        """Return {equ_ticker: adv_20d} from bdib_daily_summary via raw_bdib."""
        tickers = list(tickers)
        if not tickers:
            return {}
        out: Dict[str, float] = {}
        CHUNK = 500
        conn = self._mgr.get_connection("raw_bdib", AccessTier.READ)
        try:
            for i in range(0, len(tickers), CHUNK):
                batch = tickers[i:i + CHUNK]
                ph = ",".join(["?"] * len(batch))
                sql = (
                    f"SELECT equ_ticker, adv_20d FROM bdib_daily_summary "
                    f"WHERE trade_date=? AND equ_ticker IN ({ph})"
                )
                for tk, adv in conn.execute(sql, [yyyymmdd] + batch).fetchall():
                    if adv is not None and adv > 0:
                        out[tk] = float(adv)
        finally:
            conn.close()
        return out

    def compute_snapshot_hash(
        self, config_version: str, start_iso: str, end_iso: str,
    ) -> Tuple[str, int]:
        """Return (sha256_hex, total_rows) for deterministic sampling."""
        conn = self._get_read_conn()
        try:
            cur = conn.execute(
                "SELECT OrderId, RouteId, FillId, order_as_of_date_iso, is_bps "
                "FROM fill_attribution_metrics "
                "WHERE config_version=? AND order_as_of_date_iso BETWEEN ? AND ? "
                "ORDER BY OrderId, RouteId, FillId, order_as_of_date_iso LIMIT 100",
                (config_version, start_iso, end_iso),
            )
            h = hashlib.sha256()
            for row in cur.fetchall():
                oid, rid, fid, d, isb = row
                h.update(f"{oid}|{rid}|{fid}|{d}|{isb}\n".encode("utf-8"))
            total = conn.execute(
                "SELECT COUNT(*) FROM fill_attribution_metrics "
                "WHERE config_version=? AND order_as_of_date_iso BETWEEN ? AND ?",
                (config_version, start_iso, end_iso),
            ).fetchone()[0]
            return h.hexdigest(), int(total)
        finally:
            conn.close()


class SqliteRegimeWriteRepository(BaseRepository):
    """Write access to regime labels and audit tables."""

    def __init__(self, connection_manager=None):
        super().__init__(connection_manager, database="regime")

    def _ensure_schema(self):
        """Ensure regime.db schema is current before writes."""
        try:
            from CostView.src.regime.schema import ensure_schema_current
            ensure_schema_current(self._mgr.get_path("regime"))
        except Exception:
            pass

    def upsert_regime_labels(self, df: pd.DataFrame) -> int:
        """Upsert regime label rows. Returns row count."""
        if df.empty:
            return 0
        self._ensure_schema()
        conn = self._get_write_conn()
        try:
            # Delegate to regime module for upsert logic
            # (regime label schema is managed by regime/fill_regime_tagger.py)
            from CostView.src.regime.fill_regime_tagger import _upsert_labels
            result = _upsert_labels(df, self._mgr.get_path("regime"))
            return result
        finally:
            conn.close()

    def upsert_attribution_metrics(
        self, rows: List[AttributionRowDTO], *,
        batch_size: int = 5000,
    ) -> int:
        """Bulk upsert attribution metric rows. Returns total rows written."""
        if not rows:
            return 0
        self._ensure_schema()
        tuples = [(
            r.order_id, r.route_id, r.fill_id, r.order_as_of_date_iso,
            r.config_version, r.market_code, r.broker, r.algo, r.side,
            r.fill_shares, r.fill_price, r.route_shares, r.pct_adv,
            r.participation_rate, r.arrival_px, r.interval_vwap,
            r.mid_at_fill, r.mid_fill_plus_1m, r.mid_fill_plus_5m,
            r.mid_fill_plus_30m, r.is_bps, r.vwap_bps,
            r.reversal_1m_bps, r.reversal_5m_bps, r.reversal_30m_bps,
            r.data_quality_flags, r.source_version, r.ingested_at,
        ) for r in rows]

        written = 0
        conn = self._get_admin_conn()
        try:
            for i in range(0, len(tuples), batch_size):
                chunk = tuples[i:i + batch_size]
                conn.execute("BEGIN IMMEDIATE")
                try:
                    conn.executemany(_METRICS_UPSERT_SQL, chunk)
                    conn.execute("COMMIT")
                    written += len(chunk)
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
        finally:
            conn.close()
        return written

    def insert_pipeline_run(self, run: PipelineRunDTO) -> int:
        """Insert an audit_pipeline_runs row. Returns run_id."""
        self._ensure_schema()
        conn = self._get_admin_conn()
        try:
            cur = conn.execute(
                "INSERT INTO audit_pipeline_runs "
                "(stage_name, run_started_at, status, target_start_date, "
                "target_end_date, config_version, schema_version) "
                "VALUES (?,?,?,?,?,?,?)",
                (run.stage_name, run.run_started_at, run.status,
                 run.target_start_date, run.target_end_date,
                 run.config_version, run.schema_version),
            )
            conn.execute("COMMIT")
            return cur.lastrowid
        finally:
            conn.close()

    def update_pipeline_run(self, result: PipelineRunResultDTO) -> None:
        """Update an existing pipeline run with completion info."""
        conn = self._get_admin_conn()
        try:
            conn.execute(
                "UPDATE audit_pipeline_runs "
                "SET run_finished_at=?, status=?, rows_written=?, rows_updated=?, "
                "error_message=?, duration_sec=? WHERE run_id=?",
                (result.run_finished_at, result.status,
                 result.rows_written, result.rows_updated,
                 result.error_message, result.duration_sec, result.run_id),
            )
            conn.execute("COMMIT")
        finally:
            conn.close()

    def write_research_snapshot(
        self, run_id: int, config_version: str,
        start_date_iso: str, end_date_iso: str,
        rows_written: int, rows_total: int,
        snapshot_sha256: str, created_at: str,
    ) -> None:
        """Write a research snapshot record."""
        conn = self._get_admin_conn()
        try:
            conn.execute(_SNAPSHOT_DDL)
            conn.execute(
                "INSERT OR REPLACE INTO audit_research_snapshots "
                "(run_id, stage_name, config_version, start_date, end_date, "
                "rows_written, rows_total, snapshot_sha256, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (run_id, "attribution_metrics", config_version,
                 start_date_iso, end_date_iso, rows_written, rows_total,
                 snapshot_sha256, created_at),
            )
            conn.execute("COMMIT")
        finally:
            conn.close()

    def seed_default_config(self) -> str:
        """Seed 'attr_v0' if none exists. Returns version_id."""
        import datetime as dt
        self._ensure_schema()
        now_iso = dt.datetime.now().isoformat(timespec="seconds")
        conn = self._get_admin_conn()
        try:
            existing = conn.execute(
                "SELECT COUNT(*) FROM audit_attribution_config_versions"
            ).fetchone()[0]
            if existing > 0:
                row = conn.execute(
                    "SELECT version_id FROM audit_attribution_config_versions "
                    "WHERE is_active = 1 LIMIT 1"
                ).fetchone()
                return row[0] if row else "attr_v0"
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    "INSERT INTO audit_attribution_config_versions "
                    "(version_id, bench_methods, reversal_windows_min, "
                    "winsor_pct, adv_window_days, bootstrap_n, min_cell_n, "
                    "is_active, description, created_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    ("attr_v0", "arrival_mid,interval_vwap", "1,5,30",
                     0.05, 20, 5000, 30, 1,
                     "Default config: arrival mid + interval VWAP benchmarks",
                     now_iso),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        finally:
            conn.close()
        return "attr_v0"

    def ensure_schema_current(self) -> None:
        """Verify regime.db schema is at the expected version."""
        self._ensure_schema()

    def get_recommendations(
        self, market: str, side: int, lo: float, hi: float,
        metric: str, config_version: str, *,
        join_sql: str = "", where_extra: str = "",
        params: list = None,
    ) -> pd.DataFrame:
        """Execute the recommender query."""
        if params is None:
            params = []
        sql = f"""
            SELECT fam.broker, fam.algo, fam.{metric} AS m
            FROM fill_attribution_metrics fam
            {join_sql}
            WHERE fam.config_version = ?
              AND fam.market_code = ?
              AND fam.side = ?
              AND fam.pct_adv BETWEEN ? AND ?
              AND fam.{metric} IS NOT NULL
              {where_extra}
        """
        conn = self._get_read_conn()
        try:
            return pd.read_sql_query(sql, conn.raw_connection, params=params)
        finally:
            conn.close()
