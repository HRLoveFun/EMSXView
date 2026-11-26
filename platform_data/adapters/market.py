"""Market reference data adapter — canonical adapter for MarketView-facing data.

Extracted from the formerly monolithic adapters.py (lines 443-967).
Contains MarketReferenceDataAdapter, severity helpers, sort helpers,
and default stock pool definitions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from platform_data.contracts.db_constants import (
    BARS_PER_YEAR,
    BDIB_DAILY_SUMMARY_TABLE,
    RAW_BDIB_TABLE,
)
from platform_data.adapters.tca_bridge import (
    _ConnectionManagerDailySummaryReader,
)
from platform_data.contracts.intraday_contracts import (
    INTRADAY_BUCKET_OPTIONS,
    INTRADAY_DEFAULT_BUCKET_MINUTES,
    INTRADAY_MAX_TICKERS,
    IntradayFeatureBucket,
    IntradayFeatureSnapshot,
    IntradayTickerFeatures,
)
from platform_data.contracts.market_contracts import (
    MarketAlert,
    MarketCandidatePayload,
    MarketCandidateRow,
    MarketDailySnapshotRow,
    MarketSnapshot,
    MarketSnapshotFilters,
    MarketSnapshotSort,
    MarketStockPool,
)
from platform_data.contracts.protocols import ConnectionManagerProtocol


# ── Liquidity thresholds ───────────────────────────────────────────────────────

_LIQ_HIGH_CRITICAL = 500.0   # >= 5x ADV20 burst
_LIQ_HIGH_WARNING = 200.0    # >= 2x ADV20
_LIQ_LOW_CRITICAL = 25.0     # <= 0.25x ADV20 drought
_LIQ_LOW_WARNING = 50.0      # <= 0.5x ADV20

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


# ── MarketReferenceDataAdapter ──────────────────────────────────────────────────


@dataclass(frozen=True)
class MarketReferenceDataAdapter:
    """Canonical adapter for MarketView-facing market reference data."""

    _reader: Any = field(default=None, repr=False)
    connection_manager: ConnectionManagerProtocol | None = field(default=None, compare=False)

    def _get_reader(self):
        if self._reader is None:
            if self.connection_manager is None:
                raise ValueError(
                    "MarketReferenceDataAdapter requires connection_manager to be set. "
                    "Create with: MarketReferenceDataAdapter(connection_manager=ConnectionManager())"
                )
            object.__setattr__(self, '_reader', _ConnectionManagerDailySummaryReader(self.connection_manager))
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
        _validate_intraday_request(equ_tickers, bucket_minutes)

        if trade_date is None or self.connection_manager is None:
            return _empty_intraday_snapshot(equ_tickers, trade_date, bucket_minutes)

        manager = self.connection_manager
        bucket_seconds = bucket_minutes * 60
        bars_df = _query_raw_bdib_bars(manager, equ_tickers, trade_date)
        summary_df = _query_daily_summary(manager, trade_date)

        ticker_features: list[IntradayTickerFeatures] = []
        tickers_with_data: set[str] = set()
        for ticker in equ_tickers:
            ticker_bars = bars_df[bars_df["equ_ticker"] == ticker].copy()
            if ticker_bars.empty:
                continue
            tickers_with_data.add(ticker)
            ticker_summary = summary_df[summary_df["equ_ticker"] == ticker]
            ticker_features.append(
                _build_ticker_features(
                    ticker, ticker_bars, ticker_summary, trade_date, bucket_seconds,
                )
            )

        missing = [ticker for ticker in equ_tickers if ticker not in tickers_with_data]
        return IntradayFeatureSnapshot(
            trade_date=trade_date,
            bucket_minutes=bucket_minutes,
            ticker_count=len(ticker_features),
            missing_tickers=missing,
            tickers=ticker_features,
        )


# A14/227: helpers extracted from get_intraday_features (behavior unchanged).
def _validate_intraday_request(equ_tickers: list[str], bucket_minutes: int) -> None:
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


def _empty_intraday_snapshot(
    equ_tickers: list[str], trade_date: str | None, bucket_minutes: int,
) -> IntradayFeatureSnapshot:
    return IntradayFeatureSnapshot(
        trade_date=trade_date,
        bucket_minutes=bucket_minutes,
        ticker_count=0,
        missing_tickers=list(equ_tickers),
        tickers=[],
    )


def _query_raw_bdib_bars(manager: Any, equ_tickers: list[str], trade_date: str):
    import pandas as pd

    conn = manager.get_connection("raw_bdib")
    try:
        placeholders = ",".join(["?"] * len(equ_tickers))
        return pd.read_sql_query(
            f"SELECT equ_ticker, mkt_timestamp, open, high, low, close, volume, num_trds, value "
            f"FROM {RAW_BDIB_TABLE} "
            f"WHERE equ_ticker IN ({placeholders}) AND order_as_of_date = ? "
            f"ORDER BY equ_ticker, mkt_timestamp",
            conn.raw_connection,
            params=[*equ_tickers, trade_date],
        )
    finally:
        conn.close()


def _query_daily_summary(manager: Any, trade_date: str):
    import pandas as pd

    conn = manager.get_connection("raw_bdib")
    try:
        return pd.read_sql_query(
            f"SELECT equ_ticker, total_volume, daily_vwap, daily_close, "
            f"daily_volatility, intraday_volatility, adv_5d, adv_20d "
            f"FROM {BDIB_DAILY_SUMMARY_TABLE} "
            f"WHERE trade_date = ?",
            conn.raw_connection,
            params=[trade_date],
        )
    finally:
        conn.close()


def _time_to_seconds(value: Any) -> int:
    return sum(
        int(part) * 60 ** index
        for index, part in enumerate(reversed(str(value).split(":")))
    )


def _bar_time_range(ticker_bars) -> tuple[str | None, str | None]:
    if len(ticker_bars) == 0:
        return None, None
    first = str(ticker_bars["mkt_timestamp"].iloc[0])
    last = str(ticker_bars["mkt_timestamp"].iloc[-1])
    return (
        first[:5] if len(first) >= 5 else first,
        last[:5] if len(last) >= 5 else last,
    )


def _daily_vwap(ticker_bars, total_volume: float | None) -> float | None:
    if not total_volume or total_volume <= 0 or "close" not in ticker_bars.columns:
        return None
    return float((ticker_bars["close"] * ticker_bars["volume"]).sum() / total_volume)


def _summary_values(ticker_summary) -> dict[str, float | None]:
    if ticker_summary.empty:
        return {
            "daily_close": None,
            "daily_volatility": None,
            "intraday_volatility": None,
            "adv_20d": None,
        }
    return {
        "daily_close": _to_optional_float(ticker_summary["daily_close"].iloc[0]),
        "daily_volatility": _to_optional_float(ticker_summary["daily_volatility"].iloc[0]),
        "intraday_volatility": _to_optional_float(ticker_summary["intraday_volatility"].iloc[0]),
        "adv_20d": _to_optional_float(ticker_summary["adv_20d"].iloc[0]),
    }


def _realized_vol(closes) -> float | None:
    if closes is None or len(closes) < 2:
        return None
    import numpy as np

    log_returns = np.log(closes / closes.shift(1)).dropna()
    if len(log_returns) < 2:
        return None
    return float(log_returns.std() * math.sqrt(BARS_PER_YEAR))


def _bucket_vwap(bucket_bars, bucket_volume: float) -> float | None:
    if bucket_volume <= 0 or "close" not in bucket_bars.columns:
        return None
    return float((bucket_bars["close"] * bucket_bars["volume"]).sum() / bucket_volume)


def _bucket_extremes(
    bucket_bars,
) -> tuple[float | None, float | None, float | None]:
    if bucket_bars.empty:
        return None, None, None
    close = (
        _to_optional_float(bucket_bars["close"].iloc[-1])
        if "close" in bucket_bars.columns else None
    )
    high = (
        float(bucket_bars["high"].max())
        if "high" in bucket_bars.columns else None
    )
    low = (
        float(bucket_bars["low"].min())
        if "low" in bucket_bars.columns else None
    )
    return close, high, low


def _bucket_realized_vol(bucket_bars) -> float | None:
    if "close" not in bucket_bars.columns:
        return None
    return _realized_vol(bucket_bars["close"].dropna())


def _make_bucket(
    bucket_bars,
    *,
    bucket_volume: float,
    running_volume: float,
    total_volume: float | None,
    adv_20d: float | None,
    bucket_seconds: int,
) -> IntradayFeatureBucket:
    cum_vol = running_volume if running_volume > 0 else None
    cum_pct = (
        (running_volume / total_volume * 100.0)
        if total_volume and total_volume > 0 else None
    )
    bucket_vwap = _bucket_vwap(bucket_bars, bucket_volume)
    close, high, low = _bucket_extremes(bucket_bars)
    realized_vol = _bucket_realized_vol(bucket_bars)

    min_ts = int(bucket_bars["_ts_seconds"].min())
    wall_start = (min_ts // bucket_seconds) * bucket_seconds
    wall_end = wall_start + bucket_seconds
    start = f"{wall_start // 3600:02d}:{(wall_start % 3600) // 60:02d}"
    end = f"{wall_end // 3600:02d}:{(wall_end % 3600) // 60:02d}"
    vol_vs_adv20 = (
        (running_volume / adv_20d * 100.0) if adv_20d and adv_20d > 0 else None
    )
    return IntradayFeatureBucket(
        bucket_start=start,
        bucket_end=end,
        bar_count=len(bucket_bars),
        volume=bucket_volume if bucket_volume > 0 else None,
        cumulative_volume=cum_vol,
        cumulative_volume_pct=round(cum_pct, 4) if cum_pct is not None else None,
        vwap=_round_or_none(bucket_vwap, 6),
        close=close,
        high=high,
        low=low,
        realized_vol_annualized=realized_vol,
        volume_vs_adv20_pct=vol_vs_adv20,
    )


def _build_buckets(
    ticker_bars, total_volume: float | None, bucket_seconds: int,
    adv_20d: float | None,
) -> list[IntradayFeatureBucket]:
    if len(ticker_bars) == 0 or "_ts_seconds" not in ticker_bars.columns:
        return []
    working = ticker_bars.copy()
    working["_bucket"] = working["_ts_seconds"] // bucket_seconds
    buckets: list[IntradayFeatureBucket] = []
    running_volume = 0.0
    for _, bucket_bars in working.groupby("_bucket", sort=True):
        bucket_volume = (
            float(bucket_bars["volume"].sum())
            if "volume" in bucket_bars.columns else 0.0
        )
        running_volume += bucket_volume
        buckets.append(
            _make_bucket(
                bucket_bars,
                bucket_volume=bucket_volume,
                running_volume=running_volume,
                total_volume=total_volume,
                adv_20d=adv_20d,
                bucket_seconds=bucket_seconds,
            )
        )
    return buckets


def _window_volume_vwap(window_bars) -> tuple[float, float | None]:
    volume = (
        float(window_bars["volume"].sum())
        if not window_bars.empty and "volume" in window_bars.columns else 0.0
    )
    if volume <= 0 or "close" not in window_bars.columns:
        return volume, None
    return volume, float(
        (window_bars["close"] * window_bars["volume"]).sum() / volume
    )


def _window_share(volume: float, total_volume: float | None) -> float | None:
    if not total_volume or total_volume <= 0:
        return None
    return volume / total_volume * 100.0 if volume > 0 else 0.0


def _window_stats(ticker_bars, total_volume: float | None) -> dict[str, float | None]:
    stats: dict[str, float | None] = {
        "open_window_volume": None,
        "open_window_vwap": None,
        "open_window_share_pct": None,
        "close_window_volume": None,
        "close_window_vwap": None,
        "close_window_share_pct": None,
    }
    if len(ticker_bars) == 0 or "_ts_seconds" not in ticker_bars.columns:
        return stats

    min_ts = ticker_bars["_ts_seconds"].min()
    max_ts = ticker_bars["_ts_seconds"].max()
    window_seconds = 10 * 60

    open_bars = ticker_bars[ticker_bars["_ts_seconds"] <= min_ts + window_seconds]
    open_volume, open_vwap = _window_volume_vwap(open_bars)
    stats["open_window_volume"] = open_volume if open_volume > 0 else None
    stats["open_window_vwap"] = open_vwap
    stats["open_window_share_pct"] = _window_share(open_volume, total_volume)

    close_bars = ticker_bars[ticker_bars["_ts_seconds"] > max_ts - window_seconds]
    close_volume, close_vwap = _window_volume_vwap(close_bars)
    stats["close_window_volume"] = close_volume if close_volume > 0 else None
    stats["close_window_vwap"] = close_vwap
    stats["close_window_share_pct"] = _window_share(close_volume, total_volume)
    return stats


def _build_ticker_features(
    ticker: str,
    ticker_bars,
    ticker_summary,
    trade_date: str,
    bucket_seconds: int,
) -> IntradayTickerFeatures:
    total_volume = (
        float(ticker_bars["volume"].sum())
        if "volume" in ticker_bars.columns else None
    )
    first_bar_time, last_bar_time = _bar_time_range(ticker_bars)
    daily_vwap = _daily_vwap(ticker_bars, total_volume)
    summary = _summary_values(ticker_summary)
    adv_20d = summary["adv_20d"]

    if "mkt_timestamp" in ticker_bars.columns:
        ticker_bars = ticker_bars.copy()
        ticker_bars["_ts_seconds"] = ticker_bars["mkt_timestamp"].apply(_time_to_seconds)

    buckets = _build_buckets(ticker_bars, total_volume, bucket_seconds, adv_20d)
    windows = _window_stats(ticker_bars, total_volume)
    volume_vs_adv20_pct = (
        total_volume / adv_20d * 100.0
        if total_volume and adv_20d and adv_20d > 0 else None
    )

    return IntradayTickerFeatures(
        equ_ticker=ticker,
        trade_date=trade_date,
        bar_count=len(ticker_bars),
        first_bar_time=first_bar_time,
        last_bar_time=last_bar_time,
        total_volume=total_volume,
        daily_vwap=daily_vwap,
        daily_close=summary["daily_close"],
        daily_volatility=summary["daily_volatility"],
        intraday_volatility=summary["intraday_volatility"],
        adv_20d=adv_20d,
        open_window_volume=windows["open_window_volume"],
        open_window_vwap=windows["open_window_vwap"],
        open_window_share_pct=windows["open_window_share_pct"],
        close_window_volume=windows["close_window_volume"],
        close_window_vwap=windows["close_window_vwap"],
        close_window_share_pct=windows["close_window_share_pct"],
        volume_vs_adv20_pct=volume_vs_adv20_pct,
        buckets=buckets,
    )
