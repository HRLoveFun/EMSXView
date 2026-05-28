"""Adapter entry points for the logical data domain."""

from __future__ import annotations

import math
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

from DataPipeline.storage.connection import ConnectionManager, AccessTier
from platform_data.contracts import (
    ScorecardCohortMetrics,
    ScorecardFilters,
    ScorecardReport,
    TcaFilters,
    TcaReport,
)

# Lazy service factories — resolved at call time, not import time, to avoid
# circular chains (platform_data → CostView → platform_data → ...)
# and to keep imports live even when stub files are deleted during migration.


# ---------------------------------------------------------------------------
# Daily summary reader — replaces RawBDIBDB direct import
# ---------------------------------------------------------------------------

_RAW_BDIB_TABLE = "raw_bdib"
_BDIB_DAILY_SUMMARY_TABLE = "bdib_daily_summary"

# Annualization factor for 10-second bars used in intraday realized vol.
_BARS_PER_YEAR = 252 * 6.5 * 3600 / 10  # approx 589,680


class _ConnectionManagerDailySummaryReader:
    """Read-only daily summary access via ConnectionManager.

    Replaces the direct ``RawBDIBDB`` instantiation that previously
    coupled platform_data to a CostView legacy DB class.
    """

    def __init__(self, connection_manager: ConnectionManager | None = None):
        self._mgr = connection_manager or ConnectionManager()

    def get_latest_daily_summary(
        self,
        limit: int = 25,
        trade_date: str | None = None,
    ):
        """Return the latest available daily-summary rows as a DataFrame."""
        import pandas as pd

        conn = self._mgr.get_connection("raw_bdib", AccessTier.READ)
        try:
            resolved_trade_date = trade_date
            if not resolved_trade_date:
                cursor = conn.execute(
                    f"SELECT MAX(trade_date) FROM {_BDIB_DAILY_SUMMARY_TABLE}"
                )
                resolved_trade_date = cursor.fetchone()[0]

            if not resolved_trade_date:
                return pd.DataFrame(
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

            return pd.read_sql_query(
                f"SELECT equ_ticker, trade_date, total_volume, daily_close, daily_volatility, "
                f"intraday_volatility, adv_5d, adv_20d "
                f"FROM {_BDIB_DAILY_SUMMARY_TABLE} "
                "WHERE trade_date = ? "
                "ORDER BY COALESCE(total_volume, 0) DESC, equ_ticker ASC "
                "LIMIT ?",
                conn.raw_connection,
                params=[resolved_trade_date, limit],
            )
        finally:
            conn.close()


@dataclass(frozen=True)
class MarketAlert:
    code: str
    category: str  # "liquidity" | "volatility"
    severity: str  # "normal" | "warning" | "critical"
    message: str


@dataclass(frozen=True)
class MarketStockPool:
    pool_id: str
    label: str
    description: str
    default_sort_by: str = "total_volume"
    default_sort_direction: str = "desc"


@dataclass(frozen=True)
class MarketSnapshotFilters:
    min_adv_20d: float | None = None
    min_total_volume: float | None = None
    min_daily_volatility: float | None = None
    min_intraday_volatility: float | None = None
    liquidity_alert: str = "all"
    volatility_alert: str = "all"


@dataclass(frozen=True)
class MarketSnapshotSort:
    field: str = "total_volume"
    direction: str = "desc"


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
    volume_vs_adv20_pct: float | None = None
    liquidity_alert: str = "none"
    volatility_alert: str = "none"
    alert_count: int = 0
    alerts: list[MarketAlert] = field(default_factory=list)


@dataclass(frozen=True)
class MarketCandidateRow:
    equ_ticker: str
    trade_date: str
    daily_close: float | None
    total_volume: float | None
    adv_20d: float | None
    daily_volatility: float | None
    intraday_volatility: float | None
    liquidity_alert: str
    volatility_alert: str
    alerts: list[MarketAlert] = field(default_factory=list)


@dataclass(frozen=True)
class MarketCandidatePayload:
    source: str
    handoff_target: str
    trade_date: str | None
    pool_id: str
    pool_label: str | None
    filters: MarketSnapshotFilters
    sort: MarketSnapshotSort
    row_count: int
    candidates: list[MarketCandidateRow]


@dataclass(frozen=True)
class MarketSnapshot:
    trade_date: str | None
    row_count: int
    available_pools: list[MarketStockPool]
    active_pool_id: str
    filters: MarketSnapshotFilters
    sort: MarketSnapshotSort
    rows: list[MarketDailySnapshotRow]
    candidate_payload: MarketCandidatePayload


# ── Intraday feature dataclasses ──────────────────────────────────────────────

INTRADAY_BUCKET_OPTIONS: tuple[int, ...] = (5, 10, 15, 30, 60)
INTRADAY_DEFAULT_BUCKET_MINUTES: int = 30
INTRADAY_MAX_TICKERS: int = 25


@dataclass(frozen=True)
class IntradayFeatureBucket:
    bucket_start: str
    bucket_end: str
    bar_count: int
    volume: float | None
    cumulative_volume: float | None
    cumulative_volume_pct: float | None
    vwap: float | None
    close: float | None
    high: float | None
    low: float | None
    realized_vol_annualized: float | None
    volume_vs_adv20_pct: float | None


@dataclass(frozen=True)
class IntradayTickerFeatures:
    equ_ticker: str
    trade_date: str
    bar_count: int
    first_bar_time: str | None
    last_bar_time: str | None
    total_volume: float | None
    daily_vwap: float | None
    daily_close: float | None
    daily_volatility: float | None
    intraday_volatility: float | None
    adv_20d: float | None
    open_window_volume: float | None
    open_window_vwap: float | None
    open_window_share_pct: float | None
    close_window_volume: float | None
    close_window_vwap: float | None
    close_window_share_pct: float | None
    volume_vs_adv20_pct: float | None
    buckets: list[IntradayFeatureBucket] = field(default_factory=list)


@dataclass(frozen=True)
class IntradayFeatureSnapshot:
    trade_date: str | None
    bucket_minutes: int
    ticker_count: int
    missing_tickers: list[str]
    tickers: list[IntradayTickerFeatures]


# ── Execution history (CostView read path) ────────────────────────────────────


@dataclass(frozen=True)
class ExecutionHistoryFillRow:
    order_id: str
    route_id: str
    fill_id: str
    order_as_of_date: str
    source_date: str | None = None
    local_fill_datetime: str | None = None
    exchange_exec_time: str | None = None
    route_as_of_time: str | None = None
    ny_fill_datetime: str | None = None
    broker: str | None = None
    strategy_type: str | None = None
    algo: str | None = None
    trader_name: str | None = None
    exchange: str | None = None
    side: str | None = None
    equ_ticker: str | None = None
    ccy_ticker: str | None = None
    exec_type: str | None = None
    amount: float | None = None
    route_shares: float | None = None
    fill_price: float | None = None
    fill_shares: float | None = None
    fetched_at: str | None = None


@dataclass(frozen=True)
class ExecutionHistoryOrderSummaryRow:
    order_id: str
    order_as_of_date: str
    equ_ticker: str | None = None
    side: str | None = None
    route_count: int = 0
    fill_count: int = 0
    total_fill_shares: float | None = None
    average_fill_price: float | None = None
    first_fill_time: str | None = None
    last_fill_time: str | None = None


@dataclass(frozen=True)
class ExecutionHistoryRouteSummaryRow:
    order_id: str
    route_id: str
    order_as_of_date: str
    broker: str | None = None
    algo: str | None = None
    trader_name: str | None = None
    exchange: str | None = None
    side: str | None = None
    equ_ticker: str | None = None
    fill_count: int = 0
    total_fill_shares: float | None = None
    average_fill_price: float | None = None
    first_fill_time: str | None = None
    last_fill_time: str | None = None


@dataclass(frozen=True)
class ExecutionHistoryFillSnapshot:
    start_date: str | None
    end_date: str | None
    row_count: int
    rows: list[ExecutionHistoryFillRow]
    contract_version: str | None = None


@dataclass(frozen=True)
class ExecutionHistoryOrderSummarySnapshot:
    start_date: str | None
    end_date: str | None
    row_count: int
    rows: list[ExecutionHistoryOrderSummaryRow]
    contract_version: str | None = None


@dataclass(frozen=True)
class ExecutionHistoryRouteSummarySnapshot:
    start_date: str | None
    end_date: str | None
    row_count: int
    rows: list[ExecutionHistoryRouteSummaryRow]
    contract_version: str | None = None



# ── Handoff contract types (WBS-08) ───────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_trace_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


@dataclass(frozen=True)
class HandoffMetadata:
    contract_version: str
    source: str
    handoff_target: str
    generated_at: str
    trace_id: str
    origin_trace_id: str | None = None


@dataclass(frozen=True)
class ExecutionCandidateHandoff:
    """MarketView -> ExecutionView contract.

    Wraps a MarketView candidate list with an execution hint block so that
    ExecutionView can pre-fill order/route forms without requiring per-page
    local state plumbing.
    """

    metadata: HandoffMetadata
    trade_date: str | None
    pool_id: str
    pool_label: str | None
    candidate_payload: MarketCandidatePayload
    execution_hint: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionPostTradeHandoff:
    """ExecutionView -> CostView contract.

    Captures the execution context of a completed order (parent execution,
    strategy parameters, child routes) that CostView needs to correlate with
    TCA metrics. The actual fill data stays in CostView stores — this
    contract only carries identifiers and policy context.
    """

    metadata: HandoffMetadata
    order_id: str
    parent_execution_id: str | None
    broker: str | None
    strategy: str | None
    asset_class: str | None
    urgency: str | None
    route_ids: list[str]
    strategy_params: dict[str, Any]
    candidate_trace_id: str | None = None  # back-pointer to MarketView handoff


@dataclass(frozen=True)
class BrokerStrategyRecommendation:
    """CostView -> ExecutionView contract.

    Represents a broker/strategy recommendation derived from the CostView
    scorecard cohort metrics. The payload is intentionally narrow: only the
    dimensions ExecutionView can act on (broker, strategy, urgency hint) plus
    the statistics that justify the recommendation.
    """

    metadata: HandoffMetadata
    cohort: str
    asset_class: str | None
    broker: str | None
    strategy: str | None
    urgency: str | None
    sample_size: int
    arrival_bps: float | None
    implementation_bps: float | None
    severity: str  # "normal" | "warning" | "critical"
    rationale: str
    source_report_trace_id: str | None = None


# ── Market reference adapter ──────────────────────────────────────────────────

_LIQ_HIGH_CRITICAL = 500.0  # >= 5x ADV20 burst
_LIQ_HIGH_WARNING = 200.0  # >= 2x ADV20
_LIQ_LOW_CRITICAL = 25.0  # <= 0.25x ADV20 drought
_LIQ_LOW_WARNING = 50.0  # <= 0.5x ADV20

_DAILY_VOL_CRITICAL = 40.0
_DAILY_VOL_WARNING = 25.0
_INTRADAY_VOL_CRITICAL = 3.0
_INTRADAY_VOL_WARNING = 2.0

_SEVERITY_RANK = {"none": 0, "normal": 0, "warning": 1, "critical": 2}
_SEVERITY_FILTER_MIN = {"all": -1, "warning": 1, "critical": 2}


def _severity_at_least(row_severity: str, required: str) -> bool:
    return _SEVERITY_RANK.get(row_severity, 0) >= _SEVERITY_FILTER_MIN.get(required, -1)


def _liquidity_severity(volume_vs_adv20_pct: float | None) -> str:
    if volume_vs_adv20_pct is None:
        return "none"
    v = volume_vs_adv20_pct
    if v >= _LIQ_HIGH_CRITICAL or v <= _LIQ_LOW_CRITICAL:
        return "critical"
    if v >= _LIQ_HIGH_WARNING or v <= _LIQ_LOW_WARNING:
        return "warning"
    return "normal"


def _volatility_severity(daily_vol: float | None, intraday_vol: float | None) -> str:
    daily = daily_vol if daily_vol is not None else 0.0
    intraday = intraday_vol if intraday_vol is not None else 0.0
    if daily >= _DAILY_VOL_CRITICAL or intraday >= _INTRADAY_VOL_CRITICAL:
        return "critical"
    if daily >= _DAILY_VOL_WARNING or intraday >= _INTRADAY_VOL_WARNING:
        return "warning"
    if daily_vol is None and intraday_vol is None:
        return "none"
    return "normal"


_DEFAULT_STOCK_POOLS: tuple[MarketStockPool, ...] = (
    MarketStockPool(
        pool_id="all",
        label="Full Snapshot",
        description="Latest Stage 7 universe for the selected trade date.",
    ),
    MarketStockPool(
        pool_id="volatility-watch",
        label="Volatility Watch",
        description="Names with elevated daily or intraday volatility for gap-risk review.",
        default_sort_by="daily_volatility",
    ),
    MarketStockPool(
        pool_id="liquidity-watch",
        label="Liquidity Watch",
        description="Names trading unusually high or low versus their ADV-20 baseline.",
        default_sort_by="volume_vs_adv20_pct",
    ),
    MarketStockPool(
        pool_id="active-names",
        label="Active Names",
        description="Highest participation names for the day, ranked by total volume.",
        default_sort_by="total_volume",
    ),
)


@dataclass(frozen=True)
class MarketReferenceDataAdapter:
    """Canonical adapter for MarketView-facing market reference data."""

    _reader: Any = field(default=None, repr=False)
    connection_manager: ConnectionManager | None = field(default=None, compare=False)

    def _get_reader(self):
        if self._reader is None:
            object.__setattr__(self, '_reader', _ConnectionManagerDailySummaryReader())
        return self._reader

    def describe(self) -> dict[str, str]:
        return {
            "domain": "market-reference",
            "owner": "CostView market-data pipeline",
            "storage": "SQLite bdib_daily_summary",
            "entrypoint": "ConnectionManager",
        }

    def get_market_snapshot(
        self,
        *,
        limit: int = 25,
        trade_date: str | None = None,
        pool_id: str = "all",
        min_adv_20d: float | None = None,
        min_total_volume: float | None = None,
        min_daily_volatility: float | None = None,
        min_intraday_volatility: float | None = None,
        liquidity_alert: str = "all",
        volatility_alert: str = "all",
        sort_by: str = "total_volume",
        sort_direction: str = "desc",
    ) -> MarketSnapshot:
        pools = list(_DEFAULT_STOCK_POOLS)
        pool_ids = {pool.pool_id for pool in pools}
        if pool_id not in pool_ids:
            raise ValueError(f"Unknown market stock pool: {pool_id}")

        active_pool = next(pool for pool in pools if pool.pool_id == pool_id)

        filters = MarketSnapshotFilters(
            min_adv_20d=min_adv_20d,
            min_total_volume=min_total_volume,
            min_daily_volatility=min_daily_volatility,
            min_intraday_volatility=min_intraday_volatility,
            liquidity_alert=liquidity_alert,
            volatility_alert=volatility_alert,
        )
        sort_spec = MarketSnapshotSort(field=sort_by, direction=sort_direction)

        db = self._get_reader()
        # Request a larger universe than `limit` so filtering + pool bucketing
        # doesn't starve the final page.
        fetch_limit = max(limit * 4, 200)
        frame = db.get_latest_daily_summary(limit=fetch_limit, trade_date=trade_date)
        if frame.empty:
            empty_candidate = MarketCandidatePayload(
                source="marketview-candidate-v1",
                handoff_target="ExecutionView",
                trade_date=trade_date,
                pool_id=pool_id,
                pool_label=active_pool.label,
                filters=filters,
                sort=sort_spec,
                row_count=0,
                candidates=[],
            )
            return MarketSnapshot(
                trade_date=trade_date,
                row_count=0,
                available_pools=pools,
                active_pool_id=pool_id,
                filters=filters,
                sort=sort_spec,
                rows=[],
                candidate_payload=empty_candidate,
            )

        rows: list[MarketDailySnapshotRow] = []
        for _, src in frame.iterrows():
            total_volume = _to_optional_float(src.get("total_volume"))
            adv_20d = _to_optional_float(src.get("adv_20d"))
            volume_vs_adv20_pct = (
                (total_volume / adv_20d) * 100.0
                if total_volume is not None and adv_20d not in (None, 0)
                else None
            )
            daily_vol = _to_optional_float(src.get("daily_volatility"))
            intraday_vol = _to_optional_float(src.get("intraday_volatility"))
            liq_sev = _liquidity_severity(volume_vs_adv20_pct)
            vol_sev = _volatility_severity(daily_vol, intraday_vol)
            alerts: list[MarketAlert] = []
            if liq_sev in ("warning", "critical"):
                alerts.append(
                    MarketAlert(
                        code=f"liquidity-{liq_sev}",
                        category="liquidity",
                        severity=liq_sev,
                        message=f"Volume {volume_vs_adv20_pct:.1f}% vs ADV20"
                        if volume_vs_adv20_pct is not None
                        else "Liquidity alert",
                    )
                )
            if vol_sev in ("warning", "critical"):
                alerts.append(
                    MarketAlert(
                        code=f"volatility-{vol_sev}",
                        category="volatility",
                        severity=vol_sev,
                        message=(
                            f"Daily vol {daily_vol:.1f}%, intraday vol {intraday_vol:.1f}%"
                            if daily_vol is not None and intraday_vol is not None
                            else "Volatility alert"
                        ),
                    )
                )
            rows.append(
                MarketDailySnapshotRow(
                    equ_ticker=str(src["equ_ticker"]),
                    trade_date=str(src["trade_date"]),
                    daily_close=_to_optional_float(src.get("daily_close")),
                    daily_volatility=daily_vol,
                    intraday_volatility=intraday_vol,
                    total_volume=total_volume,
                    adv_5d=_to_optional_float(src.get("adv_5d")),
                    adv_20d=adv_20d,
                    volume_vs_adv20_pct=_round_or_none(volume_vs_adv20_pct, 4),
                    liquidity_alert=liq_sev,
                    volatility_alert=vol_sev,
                    alert_count=len(alerts),
                    alerts=alerts,
                )
            )

        # Apply pool bucketing
        if pool_id == "volatility-watch":
            rows = [r for r in rows if _severity_at_least(r.volatility_alert, "warning")]
        elif pool_id == "liquidity-watch":
            rows = [r for r in rows if _severity_at_least(r.liquidity_alert, "warning")]
        elif pool_id == "active-names":
            rows = [r for r in rows if (r.total_volume or 0) > 0]
        # "all" keeps every row

        # Apply min-threshold filters
        if min_adv_20d is not None:
            rows = [r for r in rows if (r.adv_20d or 0) >= min_adv_20d]
        if min_total_volume is not None:
            rows = [r for r in rows if (r.total_volume or 0) >= min_total_volume]
        if min_daily_volatility is not None:
            rows = [r for r in rows if (r.daily_volatility or 0) >= min_daily_volatility]
        if min_intraday_volatility is not None:
            rows = [r for r in rows if (r.intraday_volatility or 0) >= min_intraday_volatility]

        # Apply alert filters
        if liquidity_alert != "all":
            rows = [r for r in rows if _severity_at_least(r.liquidity_alert, liquidity_alert)]
        if volatility_alert != "all":
            rows = [r for r in rows if _severity_at_least(r.volatility_alert, volatility_alert)]

        # Sort
        rows = _sort_market_rows(rows, sort_by, sort_direction)
        rows = rows[:limit]

        resolved_trade_date = rows[0].trade_date if rows else trade_date
        candidates = [
            MarketCandidateRow(
                equ_ticker=r.equ_ticker,
                trade_date=r.trade_date,
                daily_close=r.daily_close,
                total_volume=r.total_volume,
                adv_20d=r.adv_20d,
                daily_volatility=r.daily_volatility,
                intraday_volatility=r.intraday_volatility,
                liquidity_alert=r.liquidity_alert,
                volatility_alert=r.volatility_alert,
                alerts=list(r.alerts),
            )
            for r in rows
        ]
        candidate_payload = MarketCandidatePayload(
            source="marketview-candidate-v1",
            handoff_target="ExecutionView",
            trade_date=resolved_trade_date,
            pool_id=pool_id,
            pool_label=active_pool.label,
            filters=filters,
            sort=sort_spec,
            row_count=len(candidates),
            candidates=candidates,
        )
        return MarketSnapshot(
            trade_date=resolved_trade_date,
            row_count=len(rows),
            available_pools=pools,
            active_pool_id=pool_id,
            filters=filters,
            sort=sort_spec,
            rows=rows,
            candidate_payload=candidate_payload,
        )

    def get_intraday_features(
        self,
        *,
        equ_tickers: list[str],
        trade_date: str | None = None,
        bucket_minutes: int = INTRADAY_DEFAULT_BUCKET_MINUTES,
    ) -> IntradayFeatureSnapshot:
        if bucket_minutes not in INTRADAY_BUCKET_OPTIONS:
            raise ValueError(
                f"Unsupported bucket_minutes={bucket_minutes}; allowed: {list(INTRADAY_BUCKET_OPTIONS)}"
            )
        if not equ_tickers:
            raise ValueError("equ_tickers must include at least one value")
        if len(equ_tickers) > INTRADAY_MAX_TICKERS:
            raise ValueError(
                f"Too many tickers requested ({len(equ_tickers)}); max {INTRADAY_MAX_TICKERS}"
            )

        if trade_date is None or self.connection_manager is None:
            return IntradayFeatureSnapshot(
                trade_date=trade_date,
                bucket_minutes=bucket_minutes,
                ticker_count=0,
                missing_tickers=list(equ_tickers),
                tickers=[],
            )

        import pandas as pd

        mgr = self.connection_manager
        bucket_seconds = bucket_minutes * 60

        # ── Query raw BDIB bars ──────────────────────────────────────
        conn = mgr.get_connection("raw_bdib")
        try:
            placeholders = ",".join(["?"] * len(equ_tickers))
            bars_df = pd.read_sql_query(
                f"SELECT equ_ticker, mkt_timestamp, open, high, low, close, volume, num_trds, value "
                f"FROM {_RAW_BDIB_TABLE} "
                f"WHERE equ_ticker IN ({placeholders}) AND order_as_of_date = ? "
                f"ORDER BY equ_ticker, mkt_timestamp",
                conn.raw_connection,
                params=[*equ_tickers, trade_date],
            )
        finally:
            conn.close()

        # ── Query daily summary ──────────────────────────────────────
        summary_conn = mgr.get_connection("raw_bdib")
        try:
            summary_df = pd.read_sql_query(
                f"SELECT equ_ticker, total_volume, daily_vwap, daily_close, "
                f"daily_volatility, intraday_volatility, adv_5d, adv_20d "
                f"FROM {_BDIB_DAILY_SUMMARY_TABLE} "
                f"WHERE trade_date = ?",
                summary_conn.raw_connection,
                params=[trade_date],
            )
        finally:
            summary_conn.close()

        # ── Build ticker features ────────────────────────────────────
        ticker_features: list[IntradayTickerFeatures] = []
        tickers_with_data: set[str] = set()

        for ticker in equ_tickers:
            ticker_bars = bars_df[bars_df["equ_ticker"] == ticker].copy()
            if ticker_bars.empty:
                continue
            tickers_with_data.add(ticker)

            ticker_summary = summary_df[summary_df["equ_ticker"] == ticker]
            total_volume = float(ticker_bars["volume"].sum()) if "volume" in ticker_bars.columns else None
            bar_count = len(ticker_bars)

            first_bar_time: str | None = None
            last_bar_time: str | None = None
            if bar_count > 0:
                fb = str(ticker_bars["mkt_timestamp"].iloc[0])
                lb = str(ticker_bars["mkt_timestamp"].iloc[-1])
                first_bar_time = fb[:5] if len(fb) >= 5 else fb
                last_bar_time = lb[:5] if len(lb) >= 5 else lb

            # Daily VWAP from bars
            daily_vwap: float | None = None
            if total_volume and total_volume > 0 and "close" in ticker_bars.columns:
                daily_vwap = float((ticker_bars["close"] * ticker_bars["volume"]).sum() / total_volume)

            daily_close = _to_optional_float(ticker_summary["daily_close"].iloc[0]) if not ticker_summary.empty else None
            daily_volatility = _to_optional_float(ticker_summary["daily_volatility"].iloc[0]) if not ticker_summary.empty else None
            intraday_vol = _to_optional_float(ticker_summary["intraday_volatility"].iloc[0]) if not ticker_summary.empty else None
            adv_20d = _to_optional_float(ticker_summary["adv_20d"].iloc[0]) if not ticker_summary.empty else None

            # ── Bucketing ────────────────────────────────────────────
            buckets: list[IntradayFeatureBucket] = []
            if bar_count > 0 and "mkt_timestamp" in ticker_bars.columns:
                ticker_bars["_ts_seconds"] = ticker_bars["mkt_timestamp"].apply(
                    lambda t: sum(int(x) * 60 ** i for i, x in enumerate(reversed(str(t).split(":"))))
                )
                ticker_bars["_bucket"] = ticker_bars["_ts_seconds"] // bucket_seconds

                running_volume = 0.0
                for bucket_idx, (_, bdf) in enumerate(ticker_bars.groupby("_bucket", sort=True)):
                    running_volume += float(bdf["volume"].sum()) if "volume" in bdf.columns else 0.0

                    bucket_bar_count = len(bdf)
                    bucket_volume = float(bdf["volume"].sum()) if "volume" in bdf.columns else 0.0
                    cum_vol = running_volume if running_volume > 0 else None
                    cum_pct = (running_volume / total_volume * 100.0) if total_volume and total_volume > 0 else None

                    # Bucket VWAP
                    b_vwap: float | None = None
                    if bucket_volume > 0 and "close" in bdf.columns:
                        b_vwap = float((bdf["close"] * bdf["volume"]).sum() / bucket_volume)

                    b_close = _to_optional_float(bdf["close"].iloc[-1]) if "close" in bdf.columns and not bdf.empty else None
                    b_high = float(bdf["high"].max()) if "high" in bdf.columns and not bdf.empty else None
                    b_low = float(bdf["low"].min()) if "low" in bdf.columns and not bdf.empty else None

                    # Realized vol within bucket
                    closes = bdf["close"].dropna() if "close" in bdf.columns else pd.Series(dtype=float)
                    realized_vol: float | None = None
                    if len(closes) >= 2:
                        import numpy as np
                        log_returns = np.log(closes / closes.shift(1)).dropna()
                        if len(log_returns) >= 2:
                            realized_vol = float(log_returns.std() * math.sqrt(_BARS_PER_YEAR))

                    # Bucket time boundaries
                    min_ts = int(bdf["_ts_seconds"].min())
                    # bucket_idx tracks ordinal within this ticker; compute wall clock bucket boundary
                    wall_bucket_start = (min_ts // bucket_seconds) * bucket_seconds
                    wall_bucket_end = wall_bucket_start + bucket_seconds
                    b_start = f"{wall_bucket_start // 3600:02d}:{(wall_bucket_start % 3600) // 60:02d}"
                    b_end = f"{wall_bucket_end // 3600:02d}:{(wall_bucket_end % 3600) // 60:02d}"

                    vol_vs_adv20 = (running_volume / adv_20d * 100.0) if adv_20d and adv_20d > 0 else None

                    buckets.append(IntradayFeatureBucket(
                        bucket_start=b_start,
                        bucket_end=b_end,
                        bar_count=bucket_bar_count,
                        volume=bucket_volume if bucket_volume > 0 else None,
                        cumulative_volume=cum_vol,
                        cumulative_volume_pct=round(cum_pct, 4) if cum_pct is not None else None,
                        vwap=_round_or_none(b_vwap, 6),
                        close=b_close,
                        high=b_high,
                        low=b_low,
                        realized_vol_annualized=realized_vol,
                        volume_vs_adv20_pct=vol_vs_adv20,
                    ))

            # ── Open / close window shares (relative to first/last bar) ──
            open_window_volume: float | None = None
            open_window_vwap: float | None = None
            open_window_share_pct: float | None = None
            close_window_volume: float | None = None
            close_window_vwap: float | None = None
            close_window_share_pct: float | None = None

            if bar_count > 0 and "_ts_seconds" in ticker_bars.columns:
                min_ts = ticker_bars["_ts_seconds"].min()
                max_ts = ticker_bars["_ts_seconds"].max()
                window_seconds = 10 * 60  # 10-minute window

                # Open window: first 10 minutes from first bar
                open_cutoff = min_ts + window_seconds
                open_bars = ticker_bars[ticker_bars["_ts_seconds"] <= open_cutoff]
                open_vol = float(open_bars["volume"].sum()) if not open_bars.empty and "volume" in open_bars.columns else 0.0
                open_window_volume = open_vol if open_vol > 0 else None
                if open_vol > 0 and "close" in open_bars.columns:
                    open_window_vwap = float((open_bars["close"] * open_bars["volume"]).sum() / open_vol)
                if total_volume and total_volume > 0:
                    open_window_share_pct = open_vol / total_volume * 100.0 if open_vol > 0 else 0.0

                # Close window: last 10 minutes before last bar
                close_cutoff = max_ts - window_seconds
                close_bars = ticker_bars[ticker_bars["_ts_seconds"] > close_cutoff]
                close_vol = float(close_bars["volume"].sum()) if not close_bars.empty and "volume" in close_bars.columns else 0.0
                close_window_volume = close_vol if close_vol > 0 else None
                if close_vol > 0 and "close" in close_bars.columns:
                    close_window_vwap = float((close_bars["close"] * close_bars["volume"]).sum() / close_vol)
                if total_volume and total_volume > 0:
                    close_window_share_pct = close_vol / total_volume * 100.0 if close_vol > 0 else 0.0

            volume_vs_adv20_pct = (total_volume / adv_20d * 100.0) if total_volume and adv_20d and adv_20d > 0 else None

            ticker_features.append(IntradayTickerFeatures(
                equ_ticker=ticker,
                trade_date=trade_date,
                bar_count=bar_count,
                first_bar_time=first_bar_time,
                last_bar_time=last_bar_time,
                total_volume=total_volume,
                daily_vwap=daily_vwap,
                daily_close=daily_close,
                daily_volatility=daily_volatility,
                intraday_volatility=intraday_vol,
                adv_20d=adv_20d,
                open_window_volume=open_window_volume,
                open_window_vwap=open_window_vwap,
                open_window_share_pct=open_window_share_pct,
                close_window_volume=close_window_volume,
                close_window_vwap=close_window_vwap,
                close_window_share_pct=close_window_share_pct,
                volume_vs_adv20_pct=volume_vs_adv20_pct,
                buckets=buckets,
            ))

        missing = [t for t in equ_tickers if t not in tickers_with_data]

        return IntradayFeatureSnapshot(
            trade_date=trade_date,
            bucket_minutes=bucket_minutes,
            ticker_count=len(ticker_features),
            missing_tickers=missing,
            tickers=ticker_features,
        )


def _sort_market_rows(
    rows: list[MarketDailySnapshotRow], sort_by: str, sort_direction: str
) -> list[MarketDailySnapshotRow]:
    reverse = sort_direction != "asc"

    if sort_by in ("liquidity_alert", "volatility_alert"):
        def key(row: MarketDailySnapshotRow) -> tuple[int, str]:
            sev = row.liquidity_alert if sort_by == "liquidity_alert" else row.volatility_alert
            return (_SEVERITY_RANK.get(sev, 0), row.equ_ticker)
        return sorted(rows, key=key, reverse=reverse)

    if sort_by == "equ_ticker":
        return sorted(rows, key=lambda r: r.equ_ticker, reverse=reverse)

    def numeric_key(row: MarketDailySnapshotRow) -> tuple[int, float]:
        value = getattr(row, sort_by, None)
        if value is None:
            return (1, 0.0) if reverse else (1, math.inf)
        return (0, float(value))

    return sorted(rows, key=numeric_key, reverse=reverse)


def _round_or_none(value: float | None, digits: int) -> float | None:
    if value is None:
        return None
    try:
        return round(value, digits)
    except (TypeError, ValueError):
        return None


# ── Handoff exchange adapter (WBS-08) ─────────────────────────────────────────


class HandoffExchangeAdapter:
    """In-memory cross-module handoff exchange.

    Holds the latest version of each of the three handoff contracts. The
    store is intentionally small and process-local; persistence is the
    responsibility of the owner domain (MarketView snapshots, ExecutionView
    parent execution records, CostView scorecards), not of the exchange
    itself.
    """

    _MARKET_CONTRACT_VERSION = "v1"
    _EXECUTION_CONTRACT_VERSION = "v1"
    _COST_CONTRACT_VERSION = "v1"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._market_to_execution: ExecutionCandidateHandoff | None = None
        self._execution_to_cost: dict[str, ExecutionPostTradeHandoff] = {}
        self._cost_to_execution: list[BrokerStrategyRecommendation] = []

    def describe(self) -> dict[str, str]:
        return {
            "domain": "handoff-exchange",
            "owner": "platform_data",
            "storage": "in-memory process-local store",
            "entrypoint": "HandoffExchangeAdapter",
        }

    # — Market → Execution —

    def publish_market_to_execution(
        self,
        candidate_payload: MarketCandidatePayload,
        *,
        execution_hint: dict[str, Any] | None = None,
        origin_trace_id: str | None = None,
    ) -> ExecutionCandidateHandoff:
        metadata = HandoffMetadata(
            contract_version=self._MARKET_CONTRACT_VERSION,
            source="MarketView",
            handoff_target="ExecutionView",
            generated_at=_now_iso(),
            trace_id=_new_trace_id("mv-ev"),
            origin_trace_id=origin_trace_id,
        )
        handoff = ExecutionCandidateHandoff(
            metadata=metadata,
            trade_date=candidate_payload.trade_date,
            pool_id=candidate_payload.pool_id,
            pool_label=candidate_payload.pool_label,
            candidate_payload=candidate_payload,
            execution_hint=dict(execution_hint or {}),
        )
        with self._lock:
            self._market_to_execution = handoff
        return handoff

    def get_market_to_execution(self) -> ExecutionCandidateHandoff | None:
        with self._lock:
            return self._market_to_execution

    def clear_market_to_execution(self) -> None:
        with self._lock:
            self._market_to_execution = None

    # — Execution → Cost —

    def publish_execution_to_cost(
        self,
        *,
        order_id: str,
        parent_execution_id: str | None,
        broker: str | None,
        strategy: str | None,
        asset_class: str | None,
        urgency: str | None,
        route_ids: Iterable[str],
        strategy_params: dict[str, Any] | None,
        candidate_trace_id: str | None = None,
        origin_trace_id: str | None = None,
    ) -> ExecutionPostTradeHandoff:
        metadata = HandoffMetadata(
            contract_version=self._EXECUTION_CONTRACT_VERSION,
            source="ExecutionView",
            handoff_target="CostView",
            generated_at=_now_iso(),
            trace_id=_new_trace_id("ev-cv"),
            origin_trace_id=origin_trace_id,
        )
        handoff = ExecutionPostTradeHandoff(
            metadata=metadata,
            order_id=str(order_id),
            parent_execution_id=parent_execution_id,
            broker=broker,
            strategy=strategy,
            asset_class=asset_class,
            urgency=urgency,
            route_ids=[str(rid) for rid in route_ids],
            strategy_params=dict(strategy_params or {}),
            candidate_trace_id=candidate_trace_id,
        )
        with self._lock:
            self._execution_to_cost[str(order_id)] = handoff
        return handoff

    def get_execution_to_cost(self, order_id: str) -> ExecutionPostTradeHandoff | None:
        with self._lock:
            return self._execution_to_cost.get(str(order_id))

    def list_execution_to_cost(self, limit: int = 50) -> list[ExecutionPostTradeHandoff]:
        with self._lock:
            # Return most-recently-written first (publish order is preserved
            # by dict insertion order).
            values = list(self._execution_to_cost.values())
        values.sort(key=lambda h: h.metadata.generated_at, reverse=True)
        return values[:limit]

    # — Cost → Execution —

    def publish_cost_to_execution(
        self,
        *,
        cohort: str,
        asset_class: str | None,
        broker: str | None,
        strategy: str | None,
        urgency: str | None,
        sample_size: int,
        arrival_bps: float | None,
        implementation_bps: float | None,
        severity: str,
        rationale: str,
        source_report_trace_id: str | None = None,
        origin_trace_id: str | None = None,
    ) -> BrokerStrategyRecommendation:
        metadata = HandoffMetadata(
            contract_version=self._COST_CONTRACT_VERSION,
            source="CostView",
            handoff_target="ExecutionView",
            generated_at=_now_iso(),
            trace_id=_new_trace_id("cv-ev"),
            origin_trace_id=origin_trace_id,
        )
        rec = BrokerStrategyRecommendation(
            metadata=metadata,
            cohort=cohort,
            asset_class=asset_class,
            broker=broker,
            strategy=strategy,
            urgency=urgency,
            sample_size=sample_size,
            arrival_bps=arrival_bps,
            implementation_bps=implementation_bps,
            severity=severity,
            rationale=rationale,
            source_report_trace_id=source_report_trace_id,
        )
        with self._lock:
            self._cost_to_execution.append(rec)
            # Cap retention to avoid unbounded growth.
            if len(self._cost_to_execution) > 200:
                self._cost_to_execution = self._cost_to_execution[-200:]
        return rec

    def list_cost_to_execution(
        self,
        *,
        asset_class: str | None = None,
        broker: str | None = None,
        limit: int = 20,
    ) -> list[BrokerStrategyRecommendation]:
        with self._lock:
            items = list(self._cost_to_execution)
        items = [
            r
            for r in items
            if (asset_class is None or (r.asset_class or "") == asset_class)
            and (broker is None or (r.broker or "") == broker)
        ]
        items.sort(key=lambda r: r.metadata.generated_at, reverse=True)
        return items[:limit]

    def clear_cost_to_execution(self) -> None:
        with self._lock:
            self._cost_to_execution.clear()


# ── Redis-backed handoff exchange adapter (cross-process) ──────────────────────


class RedisHandoffExchangeAdapter:
    """Redis-backed cross-module handoff exchange.

    Implements the same interface as HandoffExchangeAdapter but uses Redis keys
    so that the exchange survives process restarts and works across microservice
    boundaries.

    Keys:
      emsxview:handoff:mv-to-ev    (String — Market → Execution, single value)
      emsxview:handoff:ev-to-cv    (Hash  — Execution → Cost, by order_id)
      emsxview:handoff:cv-to-ev    (List  — Cost → Execution, capped at 200)
    """

    _MARKET_CONTRACT_VERSION = "v1"
    _EXECUTION_CONTRACT_VERSION = "v1"
    _COST_CONTRACT_VERSION = "v1"

    _KEY_MV_TO_EV = "emsxview:handoff:mv-to-ev"
    _KEY_EV_TO_CV = "emsxview:handoff:ev-to-cv"
    _KEY_CV_TO_EV = "emsxview:handoff:cv-to-ev"

    _MAX_CV_TO_EV = 200

    def __init__(self, redis_url: str = "redis://localhost:6379/0") -> None:
        import redis
        self._redis = redis.from_url(redis_url, decode_responses=False)

    def describe(self) -> dict[str, str]:
        return {
            "domain": "handoff-exchange",
            "owner": "platform_data",
            "storage": "Redis",
            "entrypoint": "RedisHandoffExchangeAdapter",
        }

    # — Serialization helpers —

    def _serialize(self, obj: Any) -> bytes:
        """Serialize a dataclass or dict to JSON bytes."""
        import json
        from dataclasses import asdict
        payload = asdict(obj) if hasattr(obj, '__dataclass_fields__') else obj
        return json.dumps(payload, default=str, ensure_ascii=False).encode('utf-8')

    def _deserialize_handoff(self, raw: bytes | None) -> ExecutionCandidateHandoff | None:
        """Deserialize a Market→Execution handoff from JSON bytes."""
        import json
        if raw is None:
            return None
        data = json.loads(raw.decode('utf-8'))
        return self._rebuild_handoff(data)

    def _rebuild_handoff(self, data: dict[str, Any]) -> ExecutionCandidateHandoff:
        meta = HandoffMetadata(**data["metadata"])
        cp_data = data["candidate_payload"]
        cp = MarketCandidatePayload(
            trade_date=cp_data["trade_date"],
            pool_id=cp_data["pool_id"],
            pool_label=cp_data.get("pool_label"),
            rows=[MarketCandidateRow(**r) for r in cp_data.get("rows", [])],
            row_count=cp_data.get("row_count", 0),
            generated_at=cp_data.get("generated_at"),
        )
        return ExecutionCandidateHandoff(
            metadata=meta,
            trade_date=data["trade_date"],
            pool_id=data["pool_id"],
            pool_label=data.get("pool_label"),
            candidate_payload=cp,
            execution_hint=data.get("execution_hint", {}),
        )

    def _deserialize_post_trade(self, raw: bytes | None) -> ExecutionPostTradeHandoff | None:
        import json
        if raw is None:
            return None
        data = json.loads(raw.decode('utf-8'))
        meta = HandoffMetadata(**data["metadata"])
        return ExecutionPostTradeHandoff(
            metadata=meta,
            order_id=data["order_id"],
            parent_execution_id=data.get("parent_execution_id"),
            broker=data.get("broker"),
            strategy=data.get("strategy"),
            asset_class=data.get("asset_class"),
            urgency=data.get("urgency"),
            route_ids=data.get("route_ids", []),
            strategy_params=data.get("strategy_params"),
        )

    def _deserialize_recommendation(self, data: dict[str, Any]) -> BrokerStrategyRecommendation:
        meta = HandoffMetadata(**data["metadata"])
        return BrokerStrategyRecommendation(
            metadata=meta,
            cohort_id=data.get("cohort_id"),
            broker=data.get("broker"),
            strategy_alias=data.get("strategy_alias"),
            asset_class=data.get("asset_class"),
            recommendation_assessment=data.get("recommendation_assessment"),
            scorecard_snapshot=ScorecardCohortMetrics(**data["scorecard_snapshot"])
            if data.get("scorecard_snapshot") else None,
            cross_reference_note=data.get("cross_reference_note"),
        )

    # — Market → Execution —

    def publish_market_to_execution(
        self,
        candidate_payload: MarketCandidatePayload,
        *,
        execution_hint: dict[str, Any] | None = None,
        origin_trace_id: str | None = None,
    ) -> ExecutionCandidateHandoff:
        metadata = HandoffMetadata(
            contract_version=self._MARKET_CONTRACT_VERSION,
            source="MarketView",
            handoff_target="ExecutionView",
            generated_at=_now_iso(),
            trace_id=_new_trace_id("mv-ev"),
            origin_trace_id=origin_trace_id,
        )
        handoff = ExecutionCandidateHandoff(
            metadata=metadata,
            trade_date=candidate_payload.trade_date,
            pool_id=candidate_payload.pool_id,
            pool_label=candidate_payload.pool_label,
            candidate_payload=candidate_payload,
            execution_hint=dict(execution_hint or {}),
        )
        self._redis.set(self._KEY_MV_TO_EV, self._serialize(handoff))
        return handoff

    def get_market_to_execution(self) -> ExecutionCandidateHandoff | None:
        raw = self._redis.get(self._KEY_MV_TO_EV)
        return self._deserialize_handoff(raw)

    def clear_market_to_execution(self) -> None:
        self._redis.delete(self._KEY_MV_TO_EV)

    # — Execution → Cost —

    def publish_execution_to_cost(
        self,
        *,
        order_id: str,
        parent_execution_id: str | None,
        broker: str | None,
        strategy: str | None,
        asset_class: str | None,
        urgency: str | None,
        route_ids: Iterable[str],
        strategy_params: dict[str, Any] | None,
        candidate_trace_id: str | None = None,
        origin_trace_id: str | None = None,
    ) -> ExecutionPostTradeHandoff:
        metadata = HandoffMetadata(
            contract_version=self._EXECUTION_CONTRACT_VERSION,
            source="ExecutionView",
            handoff_target="CostView",
            generated_at=_now_iso(),
            trace_id=_new_trace_id("ev-cv"),
            origin_trace_id=origin_trace_id,
        )
        handoff = ExecutionPostTradeHandoff(
            metadata=metadata,
            order_id=order_id,
            parent_execution_id=parent_execution_id,
            broker=broker,
            strategy=strategy,
            asset_class=asset_class,
            urgency=urgency,
            route_ids=list(route_ids),
            strategy_params=strategy_params,
        )
        self._redis.hset(self._KEY_EV_TO_CV, order_id, self._serialize(handoff))
        return handoff

    def get_execution_to_cost(self, order_id: str) -> ExecutionPostTradeHandoff | None:
        raw = self._redis.hget(self._KEY_EV_TO_CV, order_id)
        return self._deserialize_post_trade(raw)

    def clear_execution_to_cost(self) -> None:
        self._redis.delete(self._KEY_EV_TO_CV)

    # — Cost → Execution —

    def publish_cost_to_execution(
        self,
        *,
        cohort_id: str | None = None,
        broker: str,
        strategy_alias: str,
        asset_class: str,
        recommendation_assessment: str | None = None,
        scorecard_snapshot: ScorecardCohortMetrics | None = None,
        cross_reference_note: str | None = None,
        origin_trace_id: str | None = None,
    ) -> BrokerStrategyRecommendation:
        metadata = HandoffMetadata(
            contract_version=self._COST_CONTRACT_VERSION,
            source="CostView",
            handoff_target="ExecutionView",
            generated_at=_now_iso(),
            trace_id=_new_trace_id("cv-ev"),
            origin_trace_id=origin_trace_id,
        )
        rec = BrokerStrategyRecommendation(
            metadata=metadata,
            cohort_id=cohort_id,
            broker=broker,
            strategy_alias=strategy_alias,
            asset_class=asset_class,
            recommendation_assessment=recommendation_assessment,
            scorecard_snapshot=scorecard_snapshot,
            cross_reference_note=cross_reference_note,
        )
        self._redis.rpush(self._KEY_CV_TO_EV, self._serialize(rec))
        # Trim list to max size
        self._redis.ltrim(self._KEY_CV_TO_EV, -self._MAX_CV_TO_EV, -1)
        return rec

    def list_cost_to_execution(
        self,
        *,
        asset_class: str | None = None,
        broker: str | None = None,
        limit: int = 20,
    ) -> list[BrokerStrategyRecommendation]:
        raw_items = self._redis.lrange(self._KEY_CV_TO_EV, -limit * 10, -1)
        import json
        items: list[BrokerStrategyRecommendation] = []
        for raw in raw_items:
            data = json.loads(raw.decode('utf-8'))
            items.append(self._deserialize_recommendation(data))
        filtered = [
            r for r in items
            if (asset_class is None or (r.asset_class or "") == asset_class)
            and (broker is None or (r.broker or "") == broker)
        ]
        filtered.sort(key=lambda r: r.metadata.generated_at, reverse=True)
        return filtered[:limit]

    def clear_cost_to_execution(self) -> None:
        self._redis.delete(self._KEY_CV_TO_EV)


# ── Exchange singleton — configurable backend ─────────────────────────────────

import logging
_log = logging.getLogger(__name__)

from platform_data.config import HANDOFF_BACKEND, REDIS_URL

_EXCHANGE: HandoffExchangeAdapter | RedisHandoffExchangeAdapter | None = None


def get_shared_handoff_exchange() -> HandoffExchangeAdapter | RedisHandoffExchangeAdapter:
    """Return the process-wide handoff exchange singleton.

    Backend is controlled by EMSXVIEW_HANDOFF_BACKEND env var:
      - "memory" (default): in-process HandoffExchangeAdapter
      - "redis": cross-process RedisHandoffExchangeAdapter
    """
    global _EXCHANGE
    if _EXCHANGE is not None:
        return _EXCHANGE

    if HANDOFF_BACKEND == "redis":
        _log.info("Handoff exchange: Redis backend at %s", REDIS_URL)
        _EXCHANGE = RedisHandoffExchangeAdapter(redis_url=REDIS_URL)
    else:
        _log.info("Handoff exchange: in-memory backend (single-process mode)")
        _EXCHANGE = HandoffExchangeAdapter()

    return _EXCHANGE


# ── Platform data access ──────────────────────────────────────────────────────



def _to_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric != numeric:  # NaN check
        return None
    return numeric






