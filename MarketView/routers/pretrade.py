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

from dataclasses import replace
from datetime import datetime, timezone

import config
from data_access import IntradayStoreReader
from export_parser import load_pre_trade_board
from platform_data.adapters import DailyBaselineAdapter, EventRegimeAdapter
from platform_data.adapters.session import ExchangeSessionAdapter
from platform_data.contracts import (
    HANDOFF_SCHEMA_VERSION,
    DataFreshness,
    OrderIntent,
    PreTradeBoardItem,
)
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


class UnmatchedIntentResponse(BaseModel):
    """未匹配清单条目：意图不可映射、缺连接键，或盘中库无该订单的意图行。"""

    order_key: str = ""
    equ_ticker: str = ""
    pm_note: str = ""
    reason: str = ""


class FreshnessEntryResponse(BaseModel):
    dataset: str
    as_of: str = ""
    lag_minutes: float = -1.0


class PreTradeBoardPayload(BaseModel):
    trade_date: Optional[str] = None
    export_file_name: str = ""
    schema_version: str
    items: list[PreTradeBoardItemResponse] = Field(default_factory=list)
    # 057 DL-07 读侧（081/082）：意图来源、覆盖率、未匹配清单、数据集新鲜度
    intent_source: str = "none"  # intraday | export | none
    intent_coverage_pct: float = 0.0
    unmatched: list[UnmatchedIntentResponse] = Field(default_factory=list)
    freshness: list[FreshnessEntryResponse] = Field(default_factory=list)
    snapshot_source: str = "none"  # formal | intraday | none（契约 formal-first）
    generated_at: str = ""


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


def _assemble_items_from_board(board=None, connection_manager=None) -> list[PreTradeBoardItem]:
    """board → items 的四路装配（纯装配逻辑，测试以 fake 依赖覆盖）。

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

    if board is None:
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


def _reader_for(trade_date: str) -> IntradayStoreReader:
    """盘中库读侧工厂（测试 monkeypatch 替换）。"""
    return IntradayStoreReader(trade_date)


def _latest_intents(reader: IntradayStoreReader) -> dict[str, dict]:
    """按 order_key 取最新 valid_from 的意图行（同一交易日多份导出留版本）。"""
    latest: dict[str, dict] = {}
    for row in reader.read_order_intents():
        key = row.get("order_key") or ""
        current = latest.get(key)
        if current is None or (row.get("valid_from") or "") >= (current.get("valid_from") or ""):
            latest[key] = row
    return latest


def _intent_from_row(row: dict) -> OrderIntent:
    """盘中库意图行 → OrderIntent（字段缺失按 UNMAPPED，不猜）。"""
    try:
        close_pct = float(row["close_pct"]) if row.get("close_pct") not in (None, "") else None
    except (TypeError, ValueError):
        close_pct = None
    return OrderIntent(
        order_key=row.get("order_key") or "",
        benchmark=row.get("benchmark") or "UNMAPPED",
        close_pct=close_pct,
        raw_note=row.get("raw_note") or "",
        intent_source=row.get("intent_source") or "intraday",
        valid_from=row.get("valid_from") or "",
        export_ts=row.get("export_ts") or "",
        unmatched_reason=row.get("unmatched_reason"),
    )


def _snapshot_source(reader: IntradayStoreReader, trade_date: str, connection_manager) -> str:
    """按契约 formal-first 判定快照来源：正式库有该日即 formal，其次盘中库。"""
    try:
        conn = connection_manager.get_connection("raw_bdib")
        try:
            row = conn.execute(
                f"SELECT 1 FROM {BDIB_DAILY_SUMMARY_TABLE} WHERE trade_date = ? LIMIT 1",
                (trade_date,),
            ).fetchone()
        finally:
            conn.close()
        if row:
            return "formal"
    except Exception:  # 正式库不可用不阻断盘中路径
        logger.debug("formal snapshot probe failed", exc_info=True)
    return "intraday" if reader.read_snapshot_t0() else "none"


def _apply_intraday_intents(board, intents: dict[str, dict]):
    """用盘中库意图覆盖导出行；返回 (board, coverage_pct, unmatched, matched)。"""
    patched = []
    unmatched: list[dict] = []
    matched = 0
    for order in board.orders:
        key = order.intent.order_key
        row = intents.get(key)
        if row is None:
            unmatched.append(
                {
                    "order_key": key,
                    "equ_ticker": order.code,
                    "pm_note": order.pm_note,
                    "reason": "no_intent_row",
                }
            )
            patched.append(order)
            continue
        intent = _intent_from_row(row)
        patched.append(replace(order, intent=intent))
        if intent.unmatched_reason:
            unmatched.append(
                {
                    "order_key": key,
                    "equ_ticker": order.code,
                    "pm_note": order.pm_note,
                    "reason": intent.unmatched_reason,
                }
            )
        else:
            matched += 1
    total = len(patched)
    coverage = round(matched / total * 100.0, 2) if total else 0.0
    return replace(board, orders=patched), coverage, unmatched, matched


def assemble_board(connection_manager=None, trade_date: Optional[str] = None):
    """装配盘前单并返回 (items, meta)。

    意图来源优先级：盘中库 order_intent（DL-07）> 收件箱导出（DL-01）。
    盘中库不可用或无意图行时整体回落到导出解析，meta 的 intent_source 显式标注。
    """
    trade_date = trade_date or datetime.now().strftime("%Y%m%d")
    reader = _reader_for(trade_date)
    intents = _latest_intents(reader)
    freshness = tuple(reader.freshness())

    mgr = connection_manager
    if mgr is None:
        from data_access import ConnectionManager

        mgr = ConnectionManager()

    meta: dict = {
        "intent_source": "none",
        "intent_coverage_pct": 0.0,
        "unmatched": (),
        "freshness": freshness,
        "snapshot_source": _snapshot_source(reader, trade_date, mgr),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    board = load_pre_trade_board(config.EXPORT_INBOX_DIR)
    if board is None:
        if intents:
            meta["intent_source"] = "intraday"
            meta["unmatched"] = tuple(
                {
                    "order_key": key,
                    "equ_ticker": "",
                    "pm_note": row.get("raw_note") or "",
                    "reason": row.get("unmatched_reason") or "no_blotter_row",
                }
                for key, row in intents.items()
            )
        return [], meta

    if intents:
        board, coverage, unmatched, _ = _apply_intraday_intents(board, intents)
        meta["intent_source"] = "intraday"
        meta["intent_coverage_pct"] = coverage
        meta["unmatched"] = tuple(unmatched)
    else:
        meta["intent_source"] = "export"
        # 覆盖率缺省 0 是保守方向（不夸大），真实 PreTradeOrderBoard 必带该字段
        meta["intent_coverage_pct"] = getattr(board, "intent_coverage_pct", 0.0)
        meta["unmatched"] = tuple(
            {"order_key": "", "equ_ticker": u.code, "pm_note": u.pm_note, "reason": u.reason}
            for u in getattr(board, "unmatched", ())
        )

    return _assemble_items_from_board(board, mgr), meta


def assemble_items(connection_manager=None) -> list[PreTradeBoardItem]:
    """兼容包装：只返回 items（端点请用 assemble_board 取 meta）。"""
    return assemble_board(connection_manager)[0]


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
        items, meta = assemble_board(trade_date=trade_date)
    except Exception as exc:
        logger.exception("pretrade board assembly failed")
        raise HTTPException(status_code=500, detail=f"Pre-trade board error: {exc}")

    payload = PreTradeBoardPayload(
        trade_date=trade_date,
        export_file_name="",
        schema_version=HANDOFF_SCHEMA_VERSION,
        items=[_serialize(i) for i in items],
        intent_source=meta["intent_source"],
        intent_coverage_pct=meta["intent_coverage_pct"],
        unmatched=[UnmatchedIntentResponse(**u) for u in meta["unmatched"]],
        freshness=[
            FreshnessEntryResponse(
                dataset=f.dataset, as_of=f.as_of, lag_minutes=f.lag_minutes
            )
            for f in meta["freshness"]
        ],
        snapshot_source=meta["snapshot_source"],
        generated_at=meta["generated_at"],
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
