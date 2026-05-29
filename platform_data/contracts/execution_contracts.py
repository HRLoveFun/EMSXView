"""Execution-history data contracts — pure dataclasses with no business logic.

Ownership: CostView execution-history pipeline publishes these contracts.
Consumers: ExecutionView, DatabaseView (history queries).
"""

from __future__ import annotations

from dataclasses import dataclass


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
