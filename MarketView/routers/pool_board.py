"""固定筛选池池板端点（057 DL-29）——GET /api/marketview/pool-board。

只读汇总现有 4 个固定筛选池：量价指标 + 日度基线难度分位 + 预期成本参考值。
不含当日意图池/观察名单（DL-29 范围），不读 ExecutionView 运营库、无写路径。

成本口径：固定池没有订单数量，参考值按「10% ADV20 参与率 × 25% 年化波动」
计算，载荷内 assumptions 显式标注；不是订单级预测（K3 边界）。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from auth import require_token
from data_access import ConnectionManager
from market_clock import exchange_of, market_clock
from platform_data.adapters import DailyBaselineAdapter, MarketReferenceDataAdapter
from platform_data.adapters.session import ExchangeSessionAdapter

logger = logging.getLogger(__name__)

router = APIRouter(tags=["MarketView"])

# 参考成本假设（固定池无订单量：按固定名义额推导 qty 与参与率，显式标注）
REFERENCE_NOTIONAL_USD = 1_000_000.0
REFERENCE_ANNUAL_VOL_PCT = 25.0
REFERENCE_DURATION_MIN = 60.0
# 成本模型产物按货币市场命名（CH 交易所 → CN 模型）；仅用于模型查找
MODEL_MARKET_ALIASES = {"CH": "CN"}


class PoolBoardAssumptions(BaseModel):
    notional_usd: float = REFERENCE_NOTIONAL_USD
    annual_vol_pct: float = REFERENCE_ANNUAL_VOL_PCT
    duration_min: float = REFERENCE_DURATION_MIN
    model_calibrated: bool = False
    note: str = (
        "参考成本：按 100 万美元名义额 ÷ 收盘价得 qty，再按 qty ÷ ADV20 参与率、"
        "25% 年化波动、60 分钟执行窗口估算；仅用于池内横向比较，不是订单级预测（K3）"
    )


class PoolBoardRowResponse(BaseModel):
    equ_ticker: str
    daily_close: Optional[float] = None
    total_volume: Optional[float] = None
    adv_20d: Optional[float] = None
    volume_vs_adv20_pct: Optional[float] = None
    daily_volatility: Optional[float] = None
    intraday_volatility: Optional[float] = None
    liquidity_alert: str = "none"
    volatility_alert: str = "none"
    log_volume_z: Optional[float] = None
    vol_percentile: Optional[float] = None
    adv5_adv60_ratio: Optional[float] = None
    expected_cost_bps: Optional[float] = None
    timing_risk_bps: Optional[float] = None
    in_domain: bool = False
    model_version: Optional[str] = None
    # 交易状态（pre/open/lunch/closed/unknown）与交易所本地时间：
    # 休市时 mktdata 仍返回上一交易日镜像，前端据此置灰实时列
    market_status: str = "unknown"
    market_time: Optional[str] = None
    data_gaps: list[str] = Field(default_factory=list)


class PoolBoardPayload(BaseModel):
    trade_date: Optional[str] = None
    pool_id: str
    row_count: int = 0
    assumptions: PoolBoardAssumptions = PoolBoardAssumptions()
    rows: list[PoolBoardRowResponse] = Field(default_factory=list)
    generated_at: str = ""


class PoolBoardEnvelope(BaseModel):
    success: bool
    data: PoolBoardPayload
    message: str = ""


_market: MarketReferenceDataAdapter | None = None
_baseline: DailyBaselineAdapter | None = None
_session: ExchangeSessionAdapter | None = None


def _adapters():
    """懒加载三适配器单例（测试经 monkeypatch 替换）。"""
    global _market, _baseline, _session
    if _market is None:
        mgr = ConnectionManager()
        _market = MarketReferenceDataAdapter(connection_manager=mgr)
        _baseline = DailyBaselineAdapter()
        _session = ExchangeSessionAdapter()
    return _market, _baseline, _session


def _exchange_of(equ_ticker: str) -> str:
    return exchange_of(equ_ticker)


def _session_minutes(session_adapter: ExchangeSessionAdapter, market_code: str) -> float:
    session = session_adapter.get_session(market_code)
    if session is None:
        return 390.0
    open_min = int(session.market_open[:2]) * 60 + int(session.market_open[3:5])
    close_min = int(session.market_close[:2]) * 60 + int(session.market_close[3:5])
    return float(close_min - open_min)


def _cost_for(
    market_code: str,
    session_adapter: ExchangeSessionAdapter,
    price: float | None,
    adv20: float | None,
) -> tuple[Optional[float], Optional[float], bool, Optional[str], list[str]]:
    """参考成本与 timing risk；模型/价格/ADV 缺失或域外显式记 gap。"""
    from CostView.src.evaluation.expected_cost import (
        COST_MODEL_VERSION,
        expected_cost_bps,
        load_expected_cost_model,
        timing_risk_bps,
    )

    model = load_expected_cost_model(
        MODEL_MARKET_ALIASES.get(market_code.upper(), market_code)
    )
    if model is None:
        return None, None, False, None, ["cost_model"]
    if not price or not adv20:
        return None, None, False, COST_MODEL_VERSION, ["adv20"]
    participation = (REFERENCE_NOTIONAL_USD / price) / adv20
    cost = expected_cost_bps(model, participation, REFERENCE_ANNUAL_VOL_PCT)
    risk = timing_risk_bps(
        REFERENCE_ANNUAL_VOL_PCT,
        REFERENCE_DURATION_MIN,
        _session_minutes(session_adapter, market_code),
    )
    if cost is None:
        return None, risk, False, COST_MODEL_VERSION, ["cost_domain"]
    return cost, risk, True, COST_MODEL_VERSION, []


def _build_row(row, baseline, market_code: str, session_adapter) -> PoolBoardRowResponse:
    gaps = [] if baseline is not None else ["baseline"]
    cost, risk, in_domain, version, cost_gaps = _cost_for(
        market_code, session_adapter, row.daily_close, row.adv_20d
    )
    status, local_time = market_clock(session_adapter, _exchange_of(row.equ_ticker))
    return PoolBoardRowResponse(
        market_status=status,
        market_time=local_time,
        equ_ticker=row.equ_ticker,
        daily_close=row.daily_close,
        total_volume=row.total_volume,
        adv_20d=row.adv_20d,
        volume_vs_adv20_pct=row.volume_vs_adv20_pct,
        daily_volatility=row.daily_volatility,
        intraday_volatility=row.intraday_volatility,
        liquidity_alert=row.liquidity_alert,
        volatility_alert=row.volatility_alert,
        log_volume_z=baseline.log_volume_z if baseline else None,
        vol_percentile=baseline.vol_percentile if baseline else None,
        adv5_adv60_ratio=baseline.adv5_adv60_ratio if baseline else None,
        expected_cost_bps=cost,
        timing_risk_bps=risk,
        in_domain=in_domain,
        model_version=version,
        data_gaps=[*gaps, *cost_gaps],
    )


def assemble_pool_board(
    pool_id: str = "all",
    trade_date: Optional[str] = None,
    limit: int = 40,
) -> PoolBoardPayload:
    """固定池 → 量价 + 难度分位 + 参考成本（只读装配）。"""
    market, baseline_adapter, session_adapter = _adapters()
    snapshot = market.get_market_snapshot(
        limit=limit, trade_date=trade_date, pool_id=pool_id
    )
    tickers = [row.equ_ticker for row in snapshot.rows]
    mgr = ConnectionManager()
    baselines = {
        item.equ_ticker: item
        for item in baseline_adapter.get_baseline(tickers, connection_manager=mgr)
    }
    rows = []
    for row in snapshot.rows:
        market_code = session_adapter.market_code_for(_exchange_of(row.equ_ticker))
        rows.append(
            _build_row(row, baselines.get(row.equ_ticker), market_code, session_adapter)
        )
    return PoolBoardPayload(
        trade_date=snapshot.trade_date,
        pool_id=snapshot.active_pool_id,
        row_count=len(rows),
        rows=rows,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


@router.get("/api/marketview/pool-board", response_model=PoolBoardEnvelope)
async def get_pool_board(
    pool_id: str = Query(default="all"),
    trade_date: Optional[str] = Query(default=None, pattern=r"^\d{8}$"),
    limit: int = Query(default=40, ge=1, le=100),
    user: dict = Depends(require_token),
):
    try:
        payload = assemble_pool_board(pool_id, trade_date, limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.exception("pool board assembly failed")
        raise HTTPException(status_code=500, detail=f"Pool board error: {exc}")

    with_cost = sum(1 for row in payload.rows if row.expected_cost_bps is not None)
    return PoolBoardEnvelope(
        success=True,
        data=payload,
        message=f"Pool board: {payload.row_count} row(s), {with_cost} with cost reference",
    )
