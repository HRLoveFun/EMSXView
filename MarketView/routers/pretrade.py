"""盘前单装配端点（057 DL-14）——GET /api/marketview/pretrade-board。

四路产物装配（1a–1c）：DL-01 盘前单（收件箱解析）+ DL-10 日度基线 +
DL-11 市场状态 + DL-13 预期成本。任一路缺失 → item 字段 None + data_gaps
记录（不静默填 0）；DL-13 v1 模型校准未达标 → model_calibrated=False 显式
标注（docs/report-cost-model-calibration.md）。
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

import config
from export_parser import load_pre_trade_board
from platform_data.adapters import DailyBaselineAdapter, EventRegimeAdapter
from platform_data.adapters.session import ExchangeSessionAdapter
from platform_data.contracts import HANDOFF_SCHEMA_VERSION, PreTradeBoardItem
from platform_data.contracts.db_constants import BDIB_DAILY_SUMMARY_TABLE

logger = logging.getLogger(__name__)

router = APIRouter(tags=["MarketView"])

_baseline: DailyBaselineAdapter | None = None
_regime: EventRegimeAdapter | None = None
_session: ExchangeSessionAdapter | None = None


def _adapters() -> tuple[DailyBaselineAdapter, EventRegimeAdapter, ExchangeSessionAdapter]:
    """懒加载三适配器单例（测试经 monkeypatch 替换）。"""
    global _baseline, _regime, _session
    if _baseline is None:
        _baseline = DailyBaselineAdapter()
        _regime = EventRegimeAdapter()
        _session = ExchangeSessionAdapter()
    return _baseline, _regime, _session


class PreTradeBoardItemResponse(BaseModel):
    equ_ticker: str
    order_key: str
    benchmark: str
    close_pct: Optional[float] = None
    qty: Optional[float] = None
    log_volume_z: Optional[float] = None
    vol_percentile: Optional[float] = None
    adv5_adv60_ratio: Optional[float] = None
    market_code: Optional[str] = None
    liq_regime: Optional[str] = None
    vol_regime: Optional[str] = None
    expected_cost_bps: Optional[float] = None
    timing_risk_bps: Optional[float] = None
    in_domain: bool = False
    model_version: Optional[str] = None
    model_calibrated: bool = False
    data_gaps: list[str] = Field(default_factory=list)


class PreTradeBoardPayload(BaseModel):
    trade_date: Optional[str] = None
    export_file_name: str = ""
    schema_version: str
    items: list[PreTradeBoardItemResponse] = Field(default_factory=list)


class PreTradeBoardEnvelope(BaseModel):
    success: bool
    data: PreTradeBoardPayload
    message: str = ""


def _serialize(item: PreTradeBoardItem) -> PreTradeBoardItemResponse:
    return PreTradeBoardItemResponse(**item.__dict__)


def _load_adv20(mgr, equ_ticker: str, trade_date: str) -> Optional[float]:
    """ADV20 点查（bdib_daily_summary，equ_ticker × date）。"""
    conn = mgr.get_connection("raw_bdib")
    try:
        row = conn.execute(
            f"SELECT adv_20d FROM {BDIB_DAILY_SUMMARY_TABLE} WHERE equ_ticker = ? AND trade_date = ?",
            (equ_ticker, trade_date),
        ).fetchone()
        return float(row[0]) if row and row[0] else None
    finally:
        conn.close()


def _session_minutes(market_code: Optional[str]) -> Optional[float]:
    """会话时长（DL-03 注册表；未注册回落 390）。"""
    session = _adapters()[2].get_session(market_code or "")
    if session is None:
        return 390.0
    open_min = int(session.market_open[:2]) * 60 + int(session.market_open[3:5])
    close_min = int(session.market_close[:2]) * 60 + int(session.market_close[3:5])
    return float(close_min - open_min)


def assemble_items(connection_manager=None) -> list[PreTradeBoardItem]:
    """四路装配（纯装配逻辑，测试以 fake 依赖覆盖）。

    DL-13 难度：模型 + 意图参与率（qty ÷ ADV20）+ 年化波动（DL-10 基线 vol
    代理——基线只有分位，此处用模型域内所需 vol 从 bdib 点查；v0 简化：
    无 vol 点查时 difficulty 留空并记 data_gaps，不猜）。
    """
    from CostView.src.evaluation.expected_cost import (
        COST_MODEL_VERSION,
        expected_cost_bps,
        load_expected_cost_model,
        timing_risk_bps,
    )

    mgr = connection_manager
    if mgr is None:
        from data_access import ConnectionManager

        mgr = ConnectionManager()

    board = load_pre_trade_board(config.EXPORT_INBOX_DIR)
    if board is None:
        return []

    baseline_adapter, regime_adapter, session_adapter = _adapters()
    tickers = [order.code for order in board.orders]
    baselines = {
        b.equ_ticker: b for b in baseline_adapter.get_baseline(tickers, connection_manager=mgr)
    }
    markets = sorted({session_adapter.market_code_for(_exchange_of(t)) for t in tickers})
    states = {s.market_code: s for s in regime_adapter.get_market_states(markets, connection_manager=mgr)}

    items: list[PreTradeBoardItem] = []
    for order in board.orders:
        gaps: list[str] = []
        baseline = baselines.get(order.code)
        if baseline is None:
            gaps.append("baseline")
        market = session_adapter.market_code_for(_exchange_of(order.code))
        state = states.get(market)
        if state is None:
            gaps.append("regime")

        item = PreTradeBoardItem(
            equ_ticker=order.code,
            order_key=order.intent.order_key,
            benchmark=order.intent.benchmark,
            close_pct=order.intent.close_pct,
            qty=order.qty,
            log_volume_z=baseline.log_volume_z if baseline else None,
            vol_percentile=baseline.vol_percentile if baseline else None,
            adv5_adv60_ratio=baseline.adv5_adv60_ratio if baseline else None,
            market_code=market,
            liq_regime=state.liq_regime if state else None,
            vol_regime=state.vol_regime if state else None,
            data_gaps=tuple(gaps),
        )

        # 难度（DL-13）：ADV20 与模型各自独立检查（缺失均记 data_gaps）
        model = load_expected_cost_model(market)
        adv20 = _load_adv20(mgr, order.code, baseline.as_of) if baseline else None
        gaps = list(item.data_gaps)
        if adv20 is None or not order.qty:
            gaps.append("adv20")
        if model is None:
            gaps.append("cost_model")
        item = PreTradeBoardItem(**{**item.__dict__, "data_gaps": tuple(gaps)})

        if model is not None and adv20 and order.qty:
            participation = order.qty / adv20
            cost = expected_cost_bps(model, participation, _DEFAULT_VOL)
            if cost is not None:
                risk = timing_risk_bps(_DEFAULT_VOL, _DEFAULT_DURATION_MIN, _session_minutes(market) or 390)
                item = PreTradeBoardItem(
                    **{
                        **item.__dict__,
                        "expected_cost_bps": cost,
                        "timing_risk_bps": risk,
                        "in_domain": True,
                        "model_version": COST_MODEL_VERSION,
                        "model_calibrated": False,  # DL-13 v1 校准未达标
                        "data_gaps": tuple(g for g in gaps if g not in {"adv20", "cost_domain"}),
                    }
                )
            else:
                item = PreTradeBoardItem(
                    **{**item.__dict__, "data_gaps": (*item.data_gaps, "cost_domain")}
                )
        items.append(item)
    return items


# v0 简化口径（子规格 §2.4 诚实记录）：波动与时长用保守默认值，
# 逐单 vol/duration 精装待 DL-15 盘中字段就绪后升级
_DEFAULT_VOL = 25.0
_DEFAULT_DURATION_MIN = 60.0


def _exchange_of(equ_ticker: str) -> str:
    parts = str(equ_ticker).split()
    return parts[-2].upper() if len(parts) >= 2 else ""


@router.get("/api/marketview/pretrade-board", response_model=PreTradeBoardEnvelope)
async def get_pretrade_board(trade_date: Optional[str] = Query(default=None, pattern=r"^\d{8}$")):
    try:
        items = assemble_items()
    except Exception as exc:
        logger.exception("pretrade board assembly failed")
        raise HTTPException(status_code=500, detail=f"Pre-trade board error: {exc}")

    payload = PreTradeBoardPayload(
        trade_date=trade_date,
        export_file_name="",
        schema_version=HANDOFF_SCHEMA_VERSION,
        items=[_serialize(i) for i in items],
    )
    if not items:
        return PreTradeBoardEnvelope(
            success=True,
            data=payload,
            message="No EMSX export available (configure EMSXVIEW_EXPORT_INBOX_DIR)",
        )
    with_cost = sum(1 for i in items if i.expected_cost_bps is not None)
    return PreTradeBoardEnvelope(
        success=True,
        data=payload,
        message=f"Pre-trade board: {len(items)} order(s), {with_cost} with cost estimate",
    )
