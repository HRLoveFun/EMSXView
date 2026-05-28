"""Execution history record schemas."""

from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel


class ExecutionHistoryFillRecord(BaseModel):
    order_id: str
    route_id: str
    fill_id: str
    order_as_of_date: str
    source_date: Optional[str] = None
    local_fill_datetime: Optional[str] = None
    exchange_exec_time: Optional[str] = None
    route_as_of_time: Optional[str] = None
    ny_fill_datetime: Optional[str] = None
    broker: Optional[str] = None
    strategy_type: Optional[str] = None
    algo: Optional[str] = None
    trader_name: Optional[str] = None
    exchange: Optional[str] = None
    side: Optional[str] = None
    equ_ticker: Optional[str] = None
    ccy_ticker: Optional[str] = None
    exec_type: Optional[str] = None
    amount: Optional[float] = None
    route_shares: Optional[float] = None
    fill_price: Optional[float] = None
    fill_shares: Optional[float] = None
    fetched_at: Optional[str] = None


class ExecutionHistoryFillData(BaseModel):
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    contract_version: Optional[str] = None
    row_count: int
    rows: List[ExecutionHistoryFillRecord]


class ExecutionHistoryFillResponse(BaseModel):
    success: bool
    data: ExecutionHistoryFillData
    message: str = ""


class ExecutionHistoryOrderSummaryRecord(BaseModel):
    order_id: str
    order_as_of_date: str
    equ_ticker: Optional[str] = None
    side: Optional[str] = None
    route_count: int
    fill_count: int
    total_fill_shares: Optional[float] = None
    average_fill_price: Optional[float] = None
    first_fill_time: Optional[str] = None
    last_fill_time: Optional[str] = None


class ExecutionHistoryOrderSummaryData(BaseModel):
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    contract_version: Optional[str] = None
    row_count: int
    rows: List[ExecutionHistoryOrderSummaryRecord]


class ExecutionHistoryOrderSummaryResponse(BaseModel):
    success: bool
    data: ExecutionHistoryOrderSummaryData
    message: str = ""


class ExecutionHistoryRouteSummaryRecord(BaseModel):
    order_id: str
    route_id: str
    order_as_of_date: str
    broker: Optional[str] = None
    algo: Optional[str] = None
    trader_name: Optional[str] = None
    exchange: Optional[str] = None
    side: Optional[str] = None
    equ_ticker: Optional[str] = None
    fill_count: int
    total_fill_shares: Optional[float] = None
    average_fill_price: Optional[float] = None
    first_fill_time: Optional[str] = None
    last_fill_time: Optional[str] = None


class ExecutionHistoryRouteSummaryData(BaseModel):
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    contract_version: Optional[str] = None
    row_count: int
    rows: List[ExecutionHistoryRouteSummaryRecord]


class ExecutionHistoryRouteSummaryResponse(BaseModel):
    success: bool
    data: ExecutionHistoryRouteSummaryData
    message: str = ""
