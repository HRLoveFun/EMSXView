"""Concrete repository implementations for the attribution module.

All SQL and sqlite3 knowledge is encapsulated here. Business logic modules
(writer, aggregator, etc.) never import sqlite3 directly — they depend on
the Protocol interfaces defined in protocols.py.

Each repository class corresponds to a Protocol and manages its own
database connections and queries. The repository implementations delegate
to the project's existing DB classes where possible, and execute raw SQL
only when no higher-level API exists.
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd

from DataPipeline.config import Config
from DataPipeline.storage.connection import ConnectionManager, AccessTier
from DataPipeline.analysis.regime.schema import (
    REGIME_DB_PATH,
    connect as connect_regime,
    ensure_schema_current,
)

from DataPipeline.storage.dto import (
    AttributionConfigDTO,
    AttributionRowDTO,
    FillMetricsQueryDTO,
    PipelineRunDTO,
    PipelineRunResultDTO,
)

from .benchmarks import BarPanel, _floor_to_minute

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SqliteFillRepository — reads from processed_fills.db
# ---------------------------------------------------------------------------

class SqliteFillRepository:
    """Read access to processed fills + route registry via parameterized SQL.

    Migrated from benchmarks.load_fills_for_date() and the date-discovery
    query in writer.run_metrics().
    """

    def __init__(
        self,
        db_path: Optional[Path] = None,
        connection_manager: Optional[ConnectionManager] = None,
    ):
        if connection_manager is not None:
            self._mgr = connection_manager
        elif db_path is not None:
            self._mgr = ConnectionManager(
                path_overrides={"processed_fills": Path(db_path)}
            )
        else:
            self._mgr = ConnectionManager()

    def _connect(self):
        return self._mgr.get_connection(
            "processed_fills", AccessTier.READ, row_factory=sqlite3.Row
        )

    def get_fills_for_date(self, yyyymmdd: str) -> pd.DataFrame:
        """Pull fills + route ticker/side context for a single order_as_of_date.

        Migrated from benchmarks.load_fills_for_date().
        """
        sql = """
        SELECT pf.OrderId, pf.RouteId, pf.FillId, pf.order_as_of_date,
               pf.mkt_timestamp, pf.Broker, pf.algo,
               pf.FillPrice, pf.FillShares, pf.RouteShares, pf.Exchange,
               rr.equ_ticker, rr.Side
        FROM processed_fills pf
        LEFT JOIN route_registry rr
          ON rr.OrderId = pf.OrderId AND rr.RouteId = pf.RouteId
        WHERE pf.order_as_of_date = ?
          AND pf.ExecType = 'FILL'
          AND pf.FillShares > 0
          AND pf.FillPrice > 0
        """
        conn = self._connect()
        try:
            return pd.read_sql_query(sql, conn.raw_connection, params=(yyyymmdd,))
        finally:
            conn.close()

    def get_distinct_dates_in_range(
        self, start_yyyymmdd: str, end_yyyymmdd: str,
    ) -> List[str]:
        """Return sorted list of distinct order_as_of_date values with fills.

        Migrated from the date-discovery query in writer.run_metrics().
        """
        sql = (
            "SELECT DISTINCT order_as_of_date FROM processed_fills "
            "WHERE order_as_of_date BETWEEN ? AND ? "
            "  AND ExecType='FILL' AND FillShares>0 AND FillPrice>0 "
            "ORDER BY order_as_of_date"
        )
        conn = self._connect()
        try:
            df = pd.read_sql_query(sql, conn.raw_connection, params=(start_yyyymmdd, end_yyyymmdd))
            return df["order_as_of_date"].tolist()
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# SqliteBarDataRepository — reads from raw_bdib.db
# ---------------------------------------------------------------------------

class SqliteBarDataRepository:
    """Read access to intraday bar data (raw_bdib) and ADV (bdib_daily_summary).

    Migrated from benchmarks.load_bar_panels_for_date() and
    writer._load_adv_map().
    """

    def __init__(
        self,
        db_path: Optional[Path] = None,
        connection_manager: Optional[ConnectionManager] = None,
    ):
        if connection_manager is not None:
            self._mgr = connection_manager
        elif db_path is not None:
            self._mgr = ConnectionManager(
                path_overrides={"raw_bdib": Path(db_path)}
            )
        else:
            self._mgr = ConnectionManager()

    def _connect(self):
        return self._mgr.get_connection(
            "raw_bdib", AccessTier.READ, row_factory=sqlite3.Row
        )

    def get_bar_panels_for_date(
        self, yyyymmdd: str, tickers: Iterable[str],
    ) -> Dict[str, BarPanel]:
        """Return {equ_ticker: BarPanel} for date + requested tickers.

        Migrated from benchmarks.load_bar_panels_for_date().
        """
        tickers = sorted(set(t for t in tickers if t))
        if not tickers:
            return {}

        out: Dict[str, BarPanel] = {}
        CHUNK = 500
        conn = self._connect()
        try:
            for i in range(0, len(tickers), CHUNK):
                batch = tickers[i:i + CHUNK]
                placeholders = ",".join(["?"] * len(batch))
                sql = (
                    f"SELECT equ_ticker, mkt_timestamp, close, volume "
                    f"FROM raw_bdib "
                    f"WHERE order_as_of_date = ? "
                    f"  AND equ_ticker IN ({placeholders})"
                )
                df = pd.read_sql_query(sql, conn.raw_connection, params=[yyyymmdd] + batch)
                if df.empty:
                    continue
                df["minute"] = df["mkt_timestamp"].apply(_floor_to_minute)
                df = df[df["minute"] != ""]
                df["close"] = pd.to_numeric(df["close"], errors="coerce")
                df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0.0)
                df = df[(df["close"].notna()) & (df["close"] > 0)]
                if df.empty:
                    continue
                df = df.sort_values(["equ_ticker", "mkt_timestamp"])
                for tk, sub in df.groupby("equ_ticker", sort=False):
                    mid_by_minute = (
                        sub.drop_duplicates(subset=["minute"], keep="last")
                           .set_index("minute")["close"]
                    )
                    bars = sub[["minute", "close", "volume"]].set_index("minute")
                    out[tk] = BarPanel(mid_by_minute=mid_by_minute, bars=bars)
        finally:
            conn.close()
        return out

    def get_adv_map(
        self, yyyymmdd: str, tickers: Iterable[str],
    ) -> Dict[str, float]:
        """Return {equ_ticker: adv_20d} from bdib_daily_summary.

        Migrated from writer._load_adv_map().
        """
        tickers = list(tickers)
        if not tickers:
            return {}
        out: Dict[str, float] = {}
        CHUNK = 500
        conn = self._connect()
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


# ---------------------------------------------------------------------------
# SqliteRegimeRepository — read+write to regime.db
# ---------------------------------------------------------------------------

# DDL for the research snapshot table (P2.9), kept here since it's DB-layer.
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

# UPSERT SQL for fill_attribution_metrics (migrated from writer.py).
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


class SqliteRegimeRepository:
    """Read+write access to regime.db for attribution metrics, regime labels,
    and pipeline audit.

    Manages its own connections; callers never see sqlite3.Connection.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = Path(db_path or REGIME_DB_PATH)

    def _connect(self) -> sqlite3.Connection:
        ensure_schema_current(self._db_path)
        return connect_regime(self._db_path)

    def upsert_attribution_metrics(
        self, rows: List[AttributionRowDTO], *,
        batch_size: int = 5000,
    ) -> int:
        """Bulk upsert attribution metric rows. Returns total rows written.

        Migrated from writer._process_one_date() regime_conn.executemany().
        """
        if not rows:
            return 0
        # Convert DTOs to tuples for executemany
        tuples = [(
            r.order_id, r.route_id, r.fill_id, r.order_as_of_date_iso,
            r.config_version,
            r.market_code, r.broker, r.algo, r.side, r.fill_shares,
            r.fill_price,
            r.route_shares, r.pct_adv, r.participation_rate,
            r.arrival_px, r.interval_vwap,
            r.mid_at_fill, r.mid_fill_plus_1m, r.mid_fill_plus_5m,
            r.mid_fill_plus_30m,
            r.is_bps, r.vwap_bps, r.reversal_1m_bps, r.reversal_5m_bps,
            r.reversal_30m_bps,
            r.data_quality_flags, r.source_version, r.ingested_at,
        ) for r in rows]

        written = 0
        conn = self._connect()
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

    def get_fill_metrics(self, query: FillMetricsQueryDTO) -> pd.DataFrame:
        """Load fill_attribution_metrics optionally joined with regime labels.

        Migrated from aggregator.load_fill_metrics().
        """
        if query.config_version is None:
            cfg_repo = SqliteAttributionConfigRepository(self._db_path)
            cfg = cfg_repo.get_active_config()
            if cfg is None:
                raise RuntimeError("no active attribution config")
            config_version = cfg.version_id
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
        conn = self._connect()
        try:
            df = pd.read_sql_query(
                base_sql, conn,
                params=(config_version, query.start_date_iso, query.end_date_iso),
            )
            if query.regime_dim:
                if query.regime_dim not in {"vol_regime", "liq_regime", "trend_regime"}:
                    raise ValueError(f"unknown regime_dim: {query.regime_dim}")
                reg_df = pd.read_sql_query(
                    f"""SELECT OrderId, RouteId, FillId, order_as_of_date_iso,
                               {query.regime_dim} AS regime_value
                        FROM fill_regime_labels
                        WHERE config_version = (
                            SELECT version_id FROM audit_regime_config_versions
                            WHERE is_active = 1 LIMIT 1
                        )
                          AND order_as_of_date_iso BETWEEN ? AND ?""",
                    conn, params=(query.start_date_iso, query.end_date_iso),
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

    def get_regime_labels(
        self, start_date_iso: str, end_date_iso: str,
        regime_dim: str, *,
        regime_config_version: Optional[str] = None,
    ) -> pd.DataFrame:
        """Get regime labels for a date range and dimension."""
        conn = self._connect()
        try:
            if regime_config_version is None:
                row = conn.execute(
                    "SELECT version_id FROM audit_regime_config_versions "
                    "WHERE is_active = 1 LIMIT 1"
                ).fetchone()
                if row is None:
                    return pd.DataFrame()
                regime_config_version = row[0]

            sql = f"""SELECT OrderId, RouteId, FillId, order_as_of_date_iso,
                             {regime_dim} AS regime_value
                      FROM fill_regime_labels
                      WHERE config_version = ?
                        AND order_as_of_date_iso BETWEEN ? AND ?"""
            return pd.read_sql_query(
                sql, conn,
                params=(regime_config_version, start_date_iso, end_date_iso),
            )
        finally:
            conn.close()

    def insert_pipeline_run(self, run: PipelineRunDTO) -> int:
        """Insert an audit_pipeline_runs row. Returns run_id."""
        conn = self._connect()
        try:
            cur = conn.execute(
                """INSERT INTO audit_pipeline_runs
                   (stage_name, run_started_at, status, target_start_date,
                    target_end_date, config_version, schema_version)
                   VALUES (?,?,?,?,?,?,?)""",
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
        conn = self._connect()
        try:
            conn.execute(
                """UPDATE audit_pipeline_runs
                   SET run_finished_at=?, status=?, rows_written=?, rows_updated=?,
                       error_message=?, duration_sec=?
                   WHERE run_id=?""",
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
        conn = self._connect()
        try:
            conn.execute(_SNAPSHOT_DDL)
            conn.execute(
                """INSERT OR REPLACE INTO audit_research_snapshots
                   (run_id, stage_name, config_version, start_date,
                    end_date, rows_written, rows_total, snapshot_sha256,
                    created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (run_id, "attribution_metrics", config_version,
                 start_date_iso, end_date_iso, rows_written, rows_total,
                 snapshot_sha256, created_at),
            )
            conn.execute("COMMIT")
        finally:
            conn.close()

    def compute_snapshot_hash(
        self, config_version: str, start_iso: str, end_iso: str,
    ) -> Tuple[str, int]:
        """Return (sha256_hex, total_rows_in_range) for deterministic sampling.

        Migrated from writer._compute_snapshot_sha256().
        """
        conn = self._connect()
        try:
            cur = conn.execute(
                """SELECT OrderId, RouteId, FillId, order_as_of_date_iso, is_bps
                   FROM fill_attribution_metrics
                   WHERE config_version=? AND order_as_of_date_iso BETWEEN ? AND ?
                   ORDER BY OrderId, RouteId, FillId, order_as_of_date_iso
                   LIMIT 100""",
                (config_version, start_iso, end_iso),
            )
            h = hashlib.sha256()
            for row in cur.fetchall():
                oid, rid, fid, d, isb = row
                h.update(f"{oid}|{rid}|{fid}|{d}|{isb}\n".encode("utf-8"))
            total = conn.execute(
                """SELECT COUNT(*) FROM fill_attribution_metrics
                   WHERE config_version=? AND order_as_of_date_iso BETWEEN ? AND ?""",
                (config_version, start_iso, end_iso),
            ).fetchone()[0]
            return h.hexdigest(), int(total)
        finally:
            conn.close()

    def get_recommendations(
        self, market: str, side: int, lo: float, hi: float,
        metric: str, config_version: str, *,
        join_sql: str = "", where_extra: str = "",
        params: list = None,
    ) -> pd.DataFrame:
        """Execute the recommender query directly.

        Migrated from recommender.recommend() — kept as a raw SQL method
        because the recommender's SQL is highly dynamic (conditional JOINs).
        """
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
        conn = self._connect()
        try:
            return pd.read_sql_query(sql, conn, params=params)
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# SqliteAttributionConfigRepository — config from regime.db
# ---------------------------------------------------------------------------

class SqliteAttributionConfigRepository:
    """Read+write access to audit_attribution_config_versions.

    Migrated from config.py get_active_config() and seed_default_config().
    """

    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = Path(db_path or REGIME_DB_PATH)

    def _connect(self) -> sqlite3.Connection:
        ensure_schema_current(self._db_path)
        return connect_regime(self._db_path)

    def get_active_config(self) -> Optional[AttributionConfigDTO]:
        """Return the active attribution config, or None."""
        conn = self._connect()
        try:
            row = conn.execute(
                """SELECT version_id, bench_methods, reversal_windows_min,
                          winsor_pct, adv_window_days, bootstrap_n, min_cell_n,
                          description
                   FROM audit_attribution_config_versions
                   WHERE is_active = 1
                   LIMIT 1"""
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

    def seed_default_config(self) -> str:
        """Seed 'attr_v0' if none exists. Returns version_id."""
        import datetime as dt
        now_iso = dt.datetime.now().isoformat(timespec="seconds")
        conn = self._connect()
        try:
            # Check if any config exists
            existing = conn.execute(
                "SELECT COUNT(*) FROM audit_attribution_config_versions"
            ).fetchone()[0]
            if existing > 0:
                # Return the active version
                row = conn.execute(
                    "SELECT version_id FROM audit_attribution_config_versions "
                    "WHERE is_active = 1 LIMIT 1"
                ).fetchone()
                return row[0] if row else "attr_v0"

            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    """INSERT INTO audit_attribution_config_versions
                       (version_id, bench_methods, reversal_windows_min,
                        winsor_pct, adv_window_days, bootstrap_n, min_cell_n,
                        is_active, description, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
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
        ensure_schema_current(self._db_path)
