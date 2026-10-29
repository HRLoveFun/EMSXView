"""监控台端点（057 节点一重定义）：高亮面板 + 监控表 + 行详情三联图。

- ``GET /api/marketview/monitor-board``：池成员 → 14 列监控行 + 三个高亮模块；
- ``GET /api/marketview/ticker-detail``：单票行详情（10 分钟价格量分布 / 当日与前五
  日均累计量 / 累计量占比），三图共用同一时间桶序列。

只读：取数走 ``platform_data`` 适配器，不写任何库、不读执行侧运营库、不碰下单路径。
池来源 v0 是仓库内配置（开发验证 8 个 ticker），指数池表就绪后由 DL-31 切换。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from auth import require_token
from market_clock import exchange_of, market_clock
from platform_data.adapters.monitor import DEFAULT_PRICE_BINS, MarketMonitorAdapter
from platform_data.adapters.session import ExchangeSessionAdapter
from platform_data.contracts.exchange_session_contracts import SESSION_REGISTRY
from platform_data.contracts.monitor_contracts import MonitorQuote
from pool_registry import DEFAULT_POOL_ID, get_pool, list_pools, market_code_for

logger = logging.getLogger(__name__)

router = APIRouter(tags=["MarketView"])

_market_clock_adapter = ExchangeSessionAdapter()
_monitor: MarketMonitorAdapter | None = None


def _get_monitor() -> MarketMonitorAdapter:
    global _monitor
    if _monitor is None:
        from data_access import ConnectionManager

        _monitor = MarketMonitorAdapter(connection_manager=ConnectionManager())
    return _monitor


# ── 响应模型 ────────────────────────────────────────────────────────────────


class PoolSummaryResponse(BaseModel):
    pool_id: str
    label: str
    description: str = ""
    source: str = "config"
    as_of: str = ""
    member_count: int = 0


class MonitorRowResponse(BaseModel):
    equ_ticker: str
    name: Optional[str] = None
    market_status: str = "unknown"
    market_time: Optional[str] = None
    last: Optional[float] = None
    chg_pct: Optional[float] = None
    close: Optional[float] = None
    prev_close: Optional[float] = None
    total_volume: Optional[float] = None
    adv_20d: Optional[float] = None
    vol_vs_adv20: Optional[float] = None
    daily_volatility: Optional[float] = None
    intraday_volatility: Optional[float] = None
    liquidity: str = "none"
    volatility: str = "none"
    risk_notes: list[str] = Field(default_factory=list)
    data_gaps: list[str] = Field(default_factory=list)
    trade_date: Optional[str] = None
    baseline_date: Optional[str] = None
    bar_count: int = 0
    first_bar_time: Optional[str] = None
    last_bar_time: Optional[str] = None
    source: str = "bars"


class HighlightItemResponse(BaseModel):
    equ_ticker: str
    name: Optional[str] = None
    metric: str
    value: Optional[float] = None
    threshold: str = ""
    severity: str = "warning"
    note: str = ""


class HighlightsResponse(BaseModel):
    liquidity: list[HighlightItemResponse] = Field(default_factory=list)
    volatility: list[HighlightItemResponse] = Field(default_factory=list)
    risk_notes: list[HighlightItemResponse] = Field(default_factory=list)


class MonitorBoardPayload(BaseModel):
    pool: PoolSummaryResponse
    trade_date: Optional[str] = None
    row_count: int = 0
    rows: list[MonitorRowResponse] = Field(default_factory=list)
    highlights: HighlightsResponse = HighlightsResponse()
    subscribe_tickers: list[str] = Field(default_factory=list)
    generated_at: str = ""


class MonitorBoardEnvelope(BaseModel):
    success: bool
    data: MonitorBoardPayload
    message: str = ""


class DetailBucketResponse(BaseModel):
    index: int
    label: str
    volume: Optional[float] = None
    cumulative_volume: Optional[float] = None
    cumulative_pct: Optional[float] = None
    vwap: Optional[float] = None
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    gap: bool = False


class PrevBucketResponse(BaseModel):
    index: int
    label: str
    cumulative_volume: Optional[float] = None
    cumulative_pct: Optional[float] = None


class DetailCellResponse(BaseModel):
    bucket: int
    price_bin: int
    volume: float


class TickerDetailPayload(BaseModel):
    equ_ticker: str
    trade_date: Optional[str] = None
    bucket_minutes: int = 10
    market_code: Optional[str] = None
    session_open: Optional[str] = None
    session_close: Optional[str] = None
    session_note: str = ""
    buckets: list[DetailBucketResponse] = Field(default_factory=list)
    prev_buckets: list[PrevBucketResponse] = Field(default_factory=list)
    prev_days: int = 0
    prev_dates: list[str] = Field(default_factory=list)
    ohlc: dict[str, Optional[float]] = Field(default_factory=dict)
    prev_close: Optional[float] = None
    price_low: Optional[float] = None
    price_high: Optional[float] = None
    price_bin_count: int = 0
    cells: list[DetailCellResponse] = Field(default_factory=list)
    total_volume: Optional[float] = None
    prev_avg_volume: Optional[float] = None
    gaps: list[str] = Field(default_factory=list)
    source: str = "raw_bdib"


class TickerDetailEnvelope(BaseModel):
    success: bool
    data: TickerDetailPayload
    message: str = ""


# ── 风险提示与高亮 ──────────────────────────────────────────────────────────

LIQUIDITY_THRESHOLD_TEXT = "2×/5× or 0.5×/0.25× ADV20"
VOLATILITY_THRESHOLD_TEXT = "daily vol 25/40 or intraday vol 2/3"
CHG_NOTE_PCT = 4.5


def _risk_notes(quote: MonitorQuote) -> list[str]:
    """后端统一生成风险提示文本（前端只渲染，不再拼文案）；界面全英文。"""
    notes: list[str] = []
    if "baseline" in quote.gaps:
        notes.append("No daily baseline")
    if "bars" in quote.gaps:
        notes.append("No intraday bars")
    if quote.baseline_date and quote.trade_date and quote.baseline_date < quote.trade_date:
        notes.append(f"Baseline stale to {quote.baseline_date}")
    if "adv20" in quote.gaps:
        notes.append("ADV20 missing")
    if "prev_close" in quote.gaps:
        notes.append("Prev close missing; change unavailable")
    if quote.liquidity in ("warning", "critical") and quote.vol_vs_adv20 is not None:
        notes.append(f"Volume {quote.vol_vs_adv20:.0f}% of ADV20")
    if quote.volatility in ("warning", "critical"):
        daily = f"{quote.daily_volatility:.1f}%" if quote.daily_volatility is not None else "—"
        intra = (
            f"{quote.intraday_volatility:.2f}%" if quote.intraday_volatility is not None else "—"
        )
        notes.append(f"Volatility elevated (daily {daily} / intraday {intra})")
    if quote.chg_pct is not None and abs(quote.chg_pct) >= CHG_NOTE_PCT:
        notes.append(f"Move {quote.chg_pct:+.1f}%")
    return notes


def _build_highlights(rows: list[MonitorRowResponse], severity_rank: dict[str, int]) -> HighlightsResponse:
    liquidity: list[HighlightItemResponse] = []
    volatility: list[HighlightItemResponse] = []
    notes: list[HighlightItemResponse] = []
    for row in rows:
        if row.liquidity in ("warning", "critical"):
            liquidity.append(
                HighlightItemResponse(
                    equ_ticker=row.equ_ticker,
                    name=row.name,
                    metric="Vol / ADV20",
                    value=row.vol_vs_adv20,
                    threshold=LIQUIDITY_THRESHOLD_TEXT,
                    severity=row.liquidity,
                    note=f"{row.vol_vs_adv20:.0f}% of ADV20" if row.vol_vs_adv20 is not None else "",
                )
            )
        if row.volatility in ("warning", "critical"):
            volatility.append(
                HighlightItemResponse(
                    equ_ticker=row.equ_ticker,
                    name=row.name,
                    metric="Daily / Intraday Vol",
                    value=row.daily_volatility,
                    threshold=VOLATILITY_THRESHOLD_TEXT,
                    severity=row.volatility,
                    note=(
                        f"daily {row.daily_volatility:.1f}% / intraday "
                        f"{row.intraday_volatility:.2f}%"
                        if row.daily_volatility is not None and row.intraday_volatility is not None
                        else ""
                    ),
                )
            )
        if row.risk_notes:
            notes.append(
                HighlightItemResponse(
                    equ_ticker=row.equ_ticker,
                    name=row.name,
                    metric="Risk notes",
                    value=None,
                    threshold="",
                    severity="critical" if len(row.risk_notes) >= 2 else "warning",
                    note="; ".join(row.risk_notes),
                )
            )
    key = lambda item: (-severity_rank.get(item.severity, 0), item.equ_ticker)  # noqa: E731
    return HighlightsResponse(
        liquidity=sorted(liquidity, key=key),
        volatility=sorted(volatility, key=key),
        risk_notes=sorted(notes, key=key),
    )


# ── 装配 ────────────────────────────────────────────────────────────────────


def _pool_summary(pool) -> PoolSummaryResponse:
    return PoolSummaryResponse(
        pool_id=pool.pool_id,
        label=pool.label,
        description=pool.description,
        source=pool.source,
        as_of=pool.as_of,
        member_count=len(pool.members),
    )


def assemble_monitor_board(pool_id: str | None = None, trade_date: str | None = None) -> MonitorBoardPayload:
    pool = get_pool(pool_id)
    resolved, quotes = _get_monitor().get_quotes(list(pool.members), trade_date)
    names = {member.equ_ticker: member.name for member in pool.members}
    rows: list[MonitorRowResponse] = []
    for quote in quotes:
        status, local_time = market_clock(_market_clock_adapter, exchange_of(quote.equ_ticker))
        rows.append(
            MonitorRowResponse(
                equ_ticker=quote.equ_ticker,
                name=names.get(quote.equ_ticker),
                market_status=status,
                market_time=local_time,
                last=quote.last,
                chg_pct=quote.chg_pct,
                close=quote.close,
                prev_close=quote.prev_close,
                total_volume=quote.total_volume,
                adv_20d=quote.adv_20d,
                vol_vs_adv20=quote.vol_vs_adv20,
                daily_volatility=quote.daily_volatility,
                intraday_volatility=quote.intraday_volatility,
                liquidity=quote.liquidity,
                volatility=quote.volatility,
                risk_notes=_risk_notes(quote),
                data_gaps=list(quote.gaps),
                trade_date=quote.trade_date,
                baseline_date=quote.baseline_date,
                bar_count=quote.bar_count,
                first_bar_time=quote.first_bar_time,
                last_bar_time=quote.last_bar_time,
                source="bars" if quote.bar_count else "none",
            )
        )
    return MonitorBoardPayload(
        pool=_pool_summary(pool),
        trade_date=resolved,
        row_count=len(rows),
        rows=rows,
        highlights=_build_highlights(rows, {"critical": 2, "warning": 1}),
        subscribe_tickers=[row.equ_ticker for row in rows],
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


def assemble_ticker_detail(
    equ_ticker: str,
    trade_date: str | None = None,
    bucket_minutes: int = 10,
    prev_days: int = 5,
    price_bins: int = DEFAULT_PRICE_BINS,
) -> TickerDetailPayload:
    market_code = (equ_ticker.split()[-2].upper() if len(equ_ticker.split()) >= 2 else "")
    session_code = market_code_for(market_code)
    session = SESSION_REGISTRY.get(session_code)
    detail = _get_monitor().get_detail(
        equ_ticker,
        trade_date=trade_date,
        bucket_minutes=bucket_minutes,
        prev_days=prev_days,
        price_bins=price_bins,
    )
    return TickerDetailPayload(
        equ_ticker=detail.equ_ticker,
        trade_date=detail.trade_date,
        bucket_minutes=detail.bucket_minutes,
        market_code=session_code,
        session_open=session.market_open if session else None,
        session_close=session.market_close if session else None,
        session_note=session.notes if session else "",
        buckets=[DetailBucketResponse(**bucket.__dict__) for bucket in detail.buckets],
        prev_buckets=[PrevBucketResponse(**bucket.__dict__) for bucket in detail.prev_buckets],
        prev_days=detail.prev_days,
        prev_dates=list(detail.prev_dates),
        ohlc=dict(detail.ohlc),
        prev_close=detail.prev_close,
        price_low=detail.price_low,
        price_high=detail.price_high,
        price_bin_count=detail.price_bin_count,
        cells=[DetailCellResponse(**cell.__dict__) for cell in detail.cells],
        total_volume=detail.total_volume,
        prev_avg_volume=detail.prev_avg_volume,
        gaps=list(detail.gaps),
        source=detail.source,
    )


# ── 端点 ────────────────────────────────────────────────────────────────────


@router.get("/api/marketview/pools", response_model=list[PoolSummaryResponse])
async def get_pools(user: dict = Depends(require_token)):
    """池清单（v0 来自仓库内配置；池来源与 as_of 一并返回）。"""
    return [_pool_summary(pool) for pool in list_pools()]


@router.get("/api/marketview/monitor-board", response_model=MonitorBoardEnvelope)
async def get_monitor_board(
    pool_id: str = Query(default=DEFAULT_POOL_ID),
    trade_date: Optional[str] = Query(default=None, pattern=r"^\d{8}$"),
    user: dict = Depends(require_token),
):
    try:
        payload = assemble_monitor_board(pool_id, trade_date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 - 端点统一转 500，细节进日志
        logger.exception("monitor board assembly failed")
        raise HTTPException(status_code=500, detail=f"Monitor board error: {exc}")

    return MonitorBoardEnvelope(
        success=True,
        data=payload,
        message=(
            f"Monitor board: {payload.row_count} row(s) from pool "
            f"{payload.pool.pool_id} ({payload.pool.source}) on {payload.trade_date}"
        ),
    )


@router.get("/api/marketview/ticker-detail", response_model=TickerDetailEnvelope)
async def get_ticker_detail(
    ticker: str = Query(..., min_length=3),
    trade_date: Optional[str] = Query(default=None, pattern=r"^\d{8}$"),
    bucket_minutes: int = Query(default=10, ge=5, le=60),
    prev_days: int = Query(default=5, ge=0, le=10),
    price_bins: int = Query(default=DEFAULT_PRICE_BINS, ge=4, le=40),
    user: dict = Depends(require_token),
):
    try:
        payload = assemble_ticker_detail(
            ticker, trade_date, bucket_minutes, prev_days, price_bins
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("ticker detail assembly failed")
        raise HTTPException(status_code=500, detail=f"Ticker detail error: {exc}")

    return TickerDetailEnvelope(
        success=True,
        data=payload,
        message=(
            f"{payload.equ_ticker}: {len(payload.buckets)} buckets, "
            f"{len(payload.gaps)} gap(s), prev {payload.prev_days} day(s)"
        ),
    )
