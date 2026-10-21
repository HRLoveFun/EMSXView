"""EMSX 导出盘前单端点（057 DL-01，只读 MVP）。

GET /api/marketview/pre-trade-orders：读收件箱最新一份导出，返回解析后的
盘前单 v0（现成字段 + 意图 + 未匹配清单 + 覆盖率）。不落库、不碰 Bloomberg。
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import config
from export_parser import ExportParseError, load_pre_trade_board
from platform_data.contracts.order_intent_contracts import (
    BlotterOrderRow,
    OrderIntent,
    PreTradeOrderBoard,
    UnmatchedOrder,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["MarketView"])


class OrderIntentResponse(BaseModel):
    order_key: str
    benchmark: str
    close_pct: Optional[float] = None
    raw_note: str
    intent_source: str
    valid_from: str
    export_ts: str
    unmatched_reason: Optional[str] = None


class ExportOrderRowResponse(BaseModel):
    code: str
    exch_code: str
    name: str
    side: str
    qty: Optional[float] = None
    ccy: str
    status: str
    fill_qty: Optional[float] = None
    pct_filled: Optional[float] = None
    q_pct_5d_adv: Optional[float] = None
    q_pct_tdy: Optional[float] = None
    rem_bal_pct_avg_cls_auct_vol: Optional[float] = None
    working_val_usd: Optional[float] = None
    value_usd: Optional[float] = None
    chg_pct_dtdy: Optional[float] = None
    last_px_vs_vwap_bps: Optional[float] = None
    earn_rpt_time: Optional[str] = None
    ex_dvd_flag: Optional[str] = None
    brkr_code: str
    create_time: str
    pm_note: str
    intent: OrderIntentResponse
    extra_fields: dict[str, str] = Field(default_factory=dict)


class UnmatchedOrderResponse(BaseModel):
    code: str
    pm_note: str
    reason: str


class PreTradeOrdersPayload(BaseModel):
    exported_at: str = ""
    export_file_name: str = ""
    order_count: int = 0
    intent_coverage_pct: float = 0.0
    intent_mapping_version: str = ""
    orders: list[ExportOrderRowResponse] = Field(default_factory=list)
    unmatched: list[UnmatchedOrderResponse] = Field(default_factory=list)


class PreTradeOrdersEnvelope(BaseModel):
    success: bool
    data: PreTradeOrdersPayload
    message: str = ""


def _serialize_intent(intent: OrderIntent) -> OrderIntentResponse:
    return OrderIntentResponse(
        order_key=intent.order_key,
        benchmark=intent.benchmark,
        close_pct=intent.close_pct,
        raw_note=intent.raw_note,
        intent_source=intent.intent_source,
        valid_from=intent.valid_from,
        export_ts=intent.export_ts,
        unmatched_reason=intent.unmatched_reason,
    )


def _serialize_row(row: BlotterOrderRow) -> ExportOrderRowResponse:
    return ExportOrderRowResponse(
        code=row.code,
        exch_code=row.exch_code,
        name=row.name,
        side=row.side,
        qty=row.qty,
        ccy=row.ccy,
        status=row.status,
        fill_qty=row.fill_qty,
        pct_filled=row.pct_filled,
        q_pct_5d_adv=row.q_pct_5d_adv,
        q_pct_tdy=row.q_pct_tdy,
        rem_bal_pct_avg_cls_auct_vol=row.rem_bal_pct_avg_cls_auct_vol,
        working_val_usd=row.working_val_usd,
        value_usd=row.value_usd,
        chg_pct_dtdy=row.chg_pct_dtdy,
        last_px_vs_vwap_bps=row.last_px_vs_vwap_bps,
        earn_rpt_time=row.earn_rpt_time,
        ex_dvd_flag=row.ex_dvd_flag,
        brkr_code=row.brkr_code,
        create_time=row.create_time,
        pm_note=row.pm_note,
        intent=_serialize_intent(row.intent),
        extra_fields=dict(row.extra_fields),
    )


def _serialize_unmatched(entry: UnmatchedOrder) -> UnmatchedOrderResponse:
    return UnmatchedOrderResponse(code=entry.code, pm_note=entry.pm_note, reason=entry.reason)


def _serialize_board(board: PreTradeOrderBoard) -> PreTradeOrdersPayload:
    return PreTradeOrdersPayload(
        exported_at=board.exported_at,
        export_file_name=board.export_file_name,
        order_count=board.order_count,
        intent_coverage_pct=board.intent_coverage_pct,
        intent_mapping_version=board.intent_mapping_version,
        orders=[_serialize_row(row) for row in board.orders],
        unmatched=[_serialize_unmatched(entry) for entry in board.unmatched],
    )


@router.get("/api/marketview/pre-trade-orders", response_model=PreTradeOrdersEnvelope)
async def get_pre_trade_orders():
    """返回最新一份 EMSX 导出的盘前单 v0。

    未配置收件箱或无导出文件时返回空盘前单（success=true + message 说明），
    与 snapshot 端点的 unavailable 模式一致，不抛 500。
    """
    inbox = config.EXPORT_INBOX_DIR
    if not inbox:
        return PreTradeOrdersEnvelope(
            success=True,
            data=PreTradeOrdersPayload(),
            message="EMSX export inbox not configured (EMSXVIEW_EXPORT_INBOX_DIR unset)",
        )

    try:
        board = load_pre_trade_board(inbox)
    except ExportParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("pre-trade order board load failed")
        raise HTTPException(status_code=500, detail=f"Pre-trade order board error: {exc}")

    if board is None:
        return PreTradeOrdersEnvelope(
            success=True,
            data=PreTradeOrdersPayload(),
            message=f"No EMSX export file found in inbox ({inbox})",
        )

    payload = _serialize_board(board)
    return PreTradeOrdersEnvelope(
        success=True,
        data=payload,
        message=(
            f"Pre-trade orders from {payload.export_file_name}: {payload.order_count} order(s), "
            f"intent coverage {payload.intent_coverage_pct}%, {len(payload.unmatched)} unmatched"
        ),
    )
