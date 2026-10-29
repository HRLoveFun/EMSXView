"""监控台取数适配器（057 节点一重定义）。

职责：把「池成员」翻译成监控表行与行详情三联图所需的序列，全部只读。

数据来源与口径：

- 当日量价：``raw_bdib`` 的 10 秒 bar（``mkt_timestamp`` 只有时分秒，按交易日内
  顺序聚合，不做跨时区换算——桶标签即 bar 自带时钟，跨日对齐用同一时钟）。
- 日度基线：``bdib_daily_summary`` 的最新可用行（逐行返回 ``baseline_date``，
  调用方据此标 ``stale``；不同市场的最新日期并不一致）。
- 前收盘：优先取 ``bdib_daily_summary`` 中早于当日的最新收盘，缺失时回落到
  上一有 bar 交易日的末 bar 收盘。
- 价格—成交量分布：把每根 bar 的成交量按 ``[low, high]`` 与价格分档的重叠比例
  摊开（OHLC 近似，不是逐笔成交价；注释与前端图注都要说明这一点）。

严重度阈值沿用 ``platform_data.adapters.market`` 的既有绝对值（量比 2×/5× 与
0.5×/0.25× ADV20、日波动 25/40、日内波动 2/3），保证面板与历史口径同源。
"""

from __future__ import annotations

from platform_data.adapters.market import _liquidity_severity, _volatility_severity
from platform_data.contracts.db_constants import BDIB_DAILY_SUMMARY_TABLE, RAW_BDIB_TABLE
from platform_data.contracts.monitor_contracts import (
    DetailBucket,
    DetailCell,
    MonitorPoolMember,
    MonitorQuote,
    PrevBucket,
    TickerDetail,
)

# 价格分档默认数量（12 档在 8pt 图内仍可辨；行详情按票面价格跨度自适应见 _price_bins）
DEFAULT_PRICE_BINS = 12


def _bucket_label(timestamp: str, bucket_minutes: int) -> str | None:
    """'09:35:20' → '09:30'（按桶宽向下取整）；非法输入返回 None。"""
    text = str(timestamp or "")
    if len(text) < 5 or text[2] != ":":
        return None
    try:
        total = int(text[0:2]) * 60 + int(text[3:5])
    except ValueError:
        return None
    total -= total % max(bucket_minutes, 1)
    return f"{total // 60:02d}:{total % 60:02d}"


def _label_minutes(label: str) -> int:
    hours, _, minutes = label.partition(":")
    return int(hours) * 60 + int(minutes or 0)


def _round(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(float(value), digits)


class MarketMonitorAdapter:
    """池成员 → 监控行 / 行详情（只读）。"""

    def __init__(self, connection_manager):
        self._mgr = connection_manager

    # ── 基础查询 ────────────────────────────────────────────────────────────

    def _connect(self):
        return self._mgr.get_connection("raw_bdib")

    def latest_trade_date(self, tickers: list[str]) -> str | None:
        """池内可用的最新 bar 交易日（无数据返回 None）。"""
        if not tickers:
            return None
        placeholders = ",".join("?" * len(tickers))
        conn = self._connect()
        try:
            row = conn.execute(
                f"SELECT MAX(order_as_of_date) FROM {RAW_BDIB_TABLE} "
                f"WHERE equ_ticker IN ({placeholders})",
                tickers,
            ).fetchone()
        finally:
            conn.close()
        return str(row[0]) if row and row[0] else None

    def _day_aggregate(self, equ_ticker: str, trade_date: str) -> dict:
        """当日 bar 聚合：首末时间、量、高开低、首开末收、bar 数。"""
        conn = self._connect()
        try:
            agg = conn.execute(
                f"SELECT COUNT(*), MIN(mkt_timestamp), MAX(mkt_timestamp), SUM(volume), "
                f"MAX(high), MIN(low) FROM {RAW_BDIB_TABLE} "
                f"WHERE equ_ticker = ? AND order_as_of_date = ?",
                (equ_ticker, trade_date),
            ).fetchone()
            if not agg or not agg[0]:
                return {"bar_count": 0}
            first = conn.execute(
                f"SELECT open FROM {RAW_BDIB_TABLE} "
                f"WHERE equ_ticker = ? AND order_as_of_date = ? "
                f"ORDER BY mkt_timestamp LIMIT 1",
                (equ_ticker, trade_date),
            ).fetchone()
            last = conn.execute(
                f"SELECT close FROM {RAW_BDIB_TABLE} "
                f"WHERE equ_ticker = ? AND order_as_of_date = ? "
                f"ORDER BY mkt_timestamp DESC LIMIT 1",
                (equ_ticker, trade_date),
            ).fetchone()
        finally:
            conn.close()
        return {
            "bar_count": int(agg[0] or 0),
            "first_bar_time": str(agg[1]) if agg[1] else None,
            "last_bar_time": str(agg[2]) if agg[2] else None,
            "total_volume": float(agg[3] or 0.0),
            "high": float(agg[4]) if agg[4] is not None else None,
            "low": float(agg[5]) if agg[5] is not None else None,
            "open": float(first[0]) if first and first[0] is not None else None,
            "last": float(last[0]) if last and last[0] is not None else None,
        }

    def _summary(self, equ_ticker: str, trade_date: str | None) -> dict:
        """最新日度基线行（trade_date 为空则取全表最新）。"""
        conn = self._connect()
        try:
            if trade_date:
                row = conn.execute(
                    f"SELECT trade_date, daily_close, total_volume, adv_5d, adv_20d, "
                    f"daily_volatility, intraday_volatility FROM {BDIB_DAILY_SUMMARY_TABLE} "
                    f"WHERE equ_ticker = ? AND trade_date <= ? "
                    f"ORDER BY trade_date DESC LIMIT 1",
                    (equ_ticker, trade_date),
                ).fetchone()
            else:
                row = conn.execute(
                    f"SELECT trade_date, daily_close, total_volume, adv_5d, adv_20d, "
                    f"daily_volatility, intraday_volatility FROM {BDIB_DAILY_SUMMARY_TABLE} "
                    f"WHERE equ_ticker = ? ORDER BY trade_date DESC LIMIT 1",
                    (equ_ticker,),
                ).fetchone()
        finally:
            conn.close()
        if not row:
            return {}
        return {
            "baseline_date": str(row[0]),
            "close": float(row[1]) if row[1] is not None else None,
            "baseline_volume": float(row[2]) if row[2] is not None else None,
            "adv_5d": float(row[3]) if row[3] is not None else None,
            "adv_20d": float(row[4]) if row[4] is not None else None,
            "daily_volatility": float(row[5]) if row[5] is not None else None,
            "intraday_volatility": float(row[6]) if row[6] is not None else None,
        }

    def _prev_close(self, equ_ticker: str, trade_date: str | None) -> float | None:
        """前一交易日收盘：bar 优先（更新更快），缺失时回落日度基线。

        顺序不能颠倒：``bdib_daily_summary`` 按市场滞后不一（实测 700 HK 停在
        2026-09-28 而 bar 已到 10-27），用基线价当基准会算出 -12% 的假涨跌幅。
        """
        if not trade_date:
            return None
        conn = self._connect()
        try:
            row = conn.execute(
                f"SELECT close FROM {RAW_BDIB_TABLE} "
                f"WHERE equ_ticker = ? AND order_as_of_date < ? "
                f"ORDER BY order_as_of_date DESC, mkt_timestamp DESC LIMIT 1",
                (equ_ticker, trade_date),
            ).fetchone()
            if row and row[0] is not None:
                return float(row[0])
            row = conn.execute(
                f"SELECT daily_close FROM {BDIB_DAILY_SUMMARY_TABLE} "
                f"WHERE equ_ticker = ? AND trade_date < ? AND daily_close IS NOT NULL "
                f"ORDER BY trade_date DESC LIMIT 1",
                (equ_ticker, trade_date),
            ).fetchone()
        finally:
            conn.close()
        return float(row[0]) if row and row[0] is not None else None

    # ── 监控行 ──────────────────────────────────────────────────────────────

    def get_quotes(
        self,
        members: list[MonitorPoolMember],
        trade_date: str | None = None,
    ) -> tuple[str | None, list[MonitorQuote]]:
        """池成员 → (所用交易日, 监控行)。缺数据一律 None + gaps，不填 0。"""
        tickers = [member.equ_ticker for member in members]
        resolved = trade_date or self.latest_trade_date(tickers)
        rows: list[MonitorQuote] = []
        for member in members:
            rows.append(self._build_quote(member, resolved))
        return resolved, rows

    def _build_quote(self, member: MonitorPoolMember, trade_date: str | None) -> MonitorQuote:
        gaps: list[str] = []
        aggregate = (
            self._day_aggregate(member.equ_ticker, trade_date) if trade_date else {"bar_count": 0}
        )
        summary = self._summary(member.equ_ticker, trade_date)
        prev_close = self._prev_close(member.equ_ticker, trade_date)

        if not summary:
            gaps.append("baseline")
        if not aggregate.get("bar_count"):
            gaps.append("bars")

        adv_20d = summary.get("adv_20d")
        total_volume = aggregate.get("total_volume") if aggregate.get("bar_count") else None
        vol_vs_adv20 = (
            (total_volume / adv_20d) * 100.0
            if total_volume is not None and adv_20d not in (None, 0)
            else None
        )
        if adv_20d in (None, 0):
            gaps.append("adv20")

        last = aggregate.get("last")
        chg_pct = (
            ((last / prev_close) - 1.0) * 100.0
            if last is not None and prev_close not in (None, 0)
            else None
        )
        if prev_close in (None, 0):
            gaps.append("prev_close")

        daily_vol = summary.get("daily_volatility")
        intraday_vol = summary.get("intraday_volatility")
        return MonitorQuote(
            equ_ticker=member.equ_ticker,
            trade_date=trade_date,
            baseline_date=summary.get("baseline_date"),
            last=_round(last, 4),
            prev_close=_round(prev_close, 4),
            chg_pct=_round(chg_pct, 4),
            # Close 列 = 前收盘（涨跌幅基准，与 Last 成对）；基线日收盘不再单列
            close=_round(prev_close, 4),
            total_volume=total_volume,
            adv_20d=adv_20d,
            adv_5d=summary.get("adv_5d"),
            vol_vs_adv20=_round(vol_vs_adv20, 4),
            daily_volatility=daily_vol,
            intraday_volatility=intraday_vol,
            open=aggregate.get("open"),
            high=aggregate.get("high"),
            low=aggregate.get("low"),
            first_bar_time=aggregate.get("first_bar_time"),
            last_bar_time=aggregate.get("last_bar_time"),
            bar_count=int(aggregate.get("bar_count") or 0),
            liquidity=_liquidity_severity(vol_vs_adv20),
            volatility=_volatility_severity(daily_vol, intraday_vol),
            gaps=tuple(gaps),
        )

    # ── 行详情 ──────────────────────────────────────────────────────────────

    def get_detail(
        self,
        equ_ticker: str,
        trade_date: str | None = None,
        bucket_minutes: int = 10,
        prev_days: int = 5,
        price_bins: int = DEFAULT_PRICE_BINS,
    ) -> TickerDetail:
        """单票行详情：当日桶序列 + 前 N 日均值 + 价格分档分布。"""
        resolved = trade_date or self.latest_trade_date([equ_ticker])
        bars = self._load_bars(equ_ticker, resolved) if resolved else []
        prev_dates = self._prev_dates(equ_ticker, resolved, prev_days)
        prev_bars = {date: self._load_bars(equ_ticker, date) for date in prev_dates}
        return self._assemble_detail(
            equ_ticker,
            resolved,
            bars,
            prev_bars,
            bucket_minutes=bucket_minutes,
            price_bins=price_bins,
            prev_close=self._prev_close(equ_ticker, resolved),
        )

    def _load_bars(self, equ_ticker: str, trade_date: str) -> list[tuple]:
        conn = self._connect()
        try:
            rows = conn.execute(
                f"SELECT mkt_timestamp, open, high, low, close, volume FROM {RAW_BDIB_TABLE} "
                f"WHERE equ_ticker = ? AND order_as_of_date = ? ORDER BY mkt_timestamp",
                (equ_ticker, trade_date),
            ).fetchall()
        finally:
            conn.close()
        return [
            (str(r[0]), float(r[1] or 0), float(r[2] or 0), float(r[3] or 0), float(r[4] or 0), float(r[5] or 0))
            for r in rows
        ]

    def _prev_dates(self, equ_ticker: str, trade_date: str | None, prev_days: int) -> list[str]:
        if not trade_date or prev_days <= 0:
            return []
        conn = self._connect()
        try:
            rows = conn.execute(
                f"SELECT DISTINCT order_as_of_date FROM {RAW_BDIB_TABLE} "
                f"WHERE equ_ticker = ? AND order_as_of_date < ? "
                f"ORDER BY order_as_of_date DESC LIMIT ?",
                (equ_ticker, trade_date, prev_days),
            ).fetchall()
        finally:
            conn.close()
        return [str(r[0]) for r in rows]

    @staticmethod
    def _aggregate_buckets(bars: list[tuple], bucket_minutes: int) -> dict[str, dict]:
        """按桶聚合：量、高开低、末价、vwap（close 加权，bar 级近似）。"""
        buckets: dict[str, dict] = {}
        for timestamp, open_, high, low, close, volume in bars:
            label = _bucket_label(timestamp, bucket_minutes)
            if label is None:
                continue
            item = buckets.setdefault(
                label,
                {
                    "volume": 0.0,
                    "open": None,
                    "high": None,
                    "low": None,
                    "close": None,
                    "value": 0.0,
                },
            )
            item["volume"] += volume
            item["value"] += close * volume
            # 桶内 OHLC：首根 open / 逐根极值 / 末根 close（供逐桶 OHLC 点）
            item["open"] = open_ if item["open"] is None else item["open"]
            item["high"] = high if item["high"] is None else max(item["high"], high)
            item["low"] = low if item["low"] is None else min(item["low"], low)
            item["close"] = close
        return buckets

    @staticmethod
    def _price_bins(low: float | None, high: float | None, count: int) -> list[tuple[float, float]]:
        if low is None or high is None or count <= 0:
            return []
        if high <= low:
            return [(low, low)] * count
        step = (high - low) / count
        return [(low + step * index, low + step * (index + 1)) for index in range(count)]

    @staticmethod
    def _spread_volume(
        volume: float,
        bar_low: float,
        bar_high: float,
        bins: list[tuple[float, float]],
    ) -> dict[int, float]:
        """把一根 bar 的量按与各价格分档的重叠比例摊开（OHLC 近似）。"""
        if bar_high <= bar_low:
            for index, (bin_low, bin_high) in enumerate(bins):
                if bin_low <= bar_low <= bin_high:
                    return {index: volume}
            return {}
        span = bar_high - bar_low
        shares: dict[int, float] = {}
        for index, (bin_low, bin_high) in enumerate(bins):
            overlap = min(bar_high, bin_high) - max(bar_low, bin_low)
            if overlap > 0:
                shares[index] = volume * (overlap / span)
        return shares

    def _assemble_detail(
        self,
        equ_ticker: str,
        trade_date: str | None,
        bars: list[tuple],
        prev_bars: dict[str, list[tuple]],
        *,
        bucket_minutes: int,
        price_bins: int,
        prev_close: float | None = None,
    ) -> TickerDetail:
        today = self._aggregate_buckets(bars, bucket_minutes)
        prev_agg = {
            date: self._aggregate_buckets(day_bars, bucket_minutes)
            for date, day_bars in prev_bars.items()
        }

        labels = set(today)
        for day in prev_agg.values():
            labels.update(day)
        grid = sorted(labels, key=_label_minutes)
        if not grid:
            return TickerDetail(
                equ_ticker=equ_ticker,
                trade_date=trade_date,
                bucket_minutes=bucket_minutes,
                prev_close=prev_close,
            )

        total_volume = sum(item["volume"] for item in today.values()) if today else None
        cumulative = 0.0
        buckets: list[DetailBucket] = []
        for index, label in enumerate(grid):
            item = today.get(label)
            if item:
                cumulative += item["volume"]
                buckets.append(
                    DetailBucket(
                        index=index,
                        label=label,
                        volume=_round(item["volume"], 4),
                        cumulative_volume=_round(cumulative, 4),
                        cumulative_pct=_round(cumulative / total_volume, 6) if total_volume else None,
                        vwap=_round(item["value"] / item["volume"], 4) if item["volume"] else None,
                        open=item["open"],
                        high=item["high"],
                        low=item["low"],
                        close=item["close"],
                    )
                )
            else:
                buckets.append(DetailBucket(index=index, label=label))

        today_labels = sorted(today, key=_label_minutes)
        gaps: tuple[str, ...] = ()
        if len(today_labels) >= 2:
            span = range(_label_minutes(today_labels[0]), _label_minutes(today_labels[-1]), bucket_minutes)
            expected = {f"{m // 60:02d}:{m % 60:02d}" for m in span}
            gaps = tuple(sorted(expected - set(today), key=_label_minutes))

        prev_buckets = self._prev_series(grid, prev_agg)
        prev_volumes = [sum(v["volume"] for v in day.values()) for day in prev_agg.values() if day]
        day_low = min((bar[3] for bar in bars), default=None)
        day_high = max((bar[2] for bar in bars), default=None)
        bins = self._price_bins(day_low, day_high, price_bins)
        cells = self._cells(bars, grid, bins, bucket_minutes)

        return TickerDetail(
            equ_ticker=equ_ticker,
            trade_date=trade_date,
            bucket_minutes=bucket_minutes,
            buckets=tuple(buckets),
            prev_buckets=prev_buckets,
            prev_days=len(prev_volumes),
            prev_dates=tuple(sorted(prev_agg, reverse=True)),
            ohlc={
                "open": bars[0][1] if bars else None,
                "high": day_high,
                "low": day_low,
                "close": bars[-1][4] if bars else None,
            },
            prev_close=_round(prev_close, 4),
            price_low=day_low,
            price_high=day_high,
            price_bin_count=len(bins),
            cells=cells,
            total_volume=_round(total_volume, 4),
            prev_avg_volume=_round(sum(prev_volumes) / len(prev_volumes), 4) if prev_volumes else None,
            gaps=gaps,
        )

    @staticmethod
    def _prev_series(grid: list[str], prev_agg: dict[str, dict]) -> tuple[PrevBucket, ...]:
        """前 N 日：逐桶取「有该桶的交易日」均值（量与占比分别平均）。"""
        series: list[PrevBucket] = []
        for index, label in enumerate(grid):
            volumes: list[float] = []
            pcts: list[float] = []
            for day in prev_agg.values():
                item = day.get(label)
                if not item:
                    continue
                day_total = sum(value["volume"] for value in day.values())
                cumulative = sum(
                    value["volume"]
                    for key, value in day.items()
                    if _label_minutes(key) <= _label_minutes(label)
                )
                volumes.append(cumulative)
                if day_total:
                    pcts.append(cumulative / day_total)
            series.append(
                PrevBucket(
                    index=index,
                    label=label,
                    cumulative_volume=_round(sum(volumes) / len(volumes), 4) if volumes else None,
                    cumulative_pct=_round(sum(pcts) / len(pcts), 6) if pcts else None,
                )
            )
        return tuple(series)

    def _cells(
        self,
        bars: list[tuple],
        grid: list[str],
        bins: list[tuple[float, float]],
        bucket_minutes: int,
    ) -> tuple[DetailCell, ...]:
        if not bins:
            return ()
        # 桶序号必须与 ``buckets`` 同一套 grid（含前五日多出的桶），否则热力格错位
        index_of = {label: index for index, label in enumerate(grid)}
        totals: dict[tuple[int, int], float] = {}
        for timestamp, _open, high, low, _close, volume in bars:
            label = _bucket_label(timestamp, bucket_minutes)
            if label is None or label not in index_of or volume <= 0:
                continue
            for bin_index, share in self._spread_volume(volume, low, high, bins).items():
                key = (index_of[label], bin_index)
                totals[key] = totals.get(key, 0.0) + share
        return tuple(
            DetailCell(bucket=bucket, price_bin=bin_index, volume=_round(volume, 4) or 0.0)
            for (bucket, bin_index), volume in sorted(totals.items())
        )
