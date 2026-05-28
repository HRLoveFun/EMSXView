"""Parent-child execution entities for algorithmic scheduling.

A *ParentExecution* captures the trader's top-level objective
(e.g. "work 10 000 shares of AAPL VWAP over the afternoon").
Each *ChildSlice* records one discrete route submission that
the scheduler generates to fulfil that objective.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.execution_state import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Enum helpers (stored as VARCHAR, validated in Python)
# ---------------------------------------------------------------------------

class ScheduleType(str, Enum):
    TWAP = "TWAP"
    VWAP = "VWAP"
    POV = "POV"
    IS = "IS"          # Implementation Shortfall
    MANUAL = "MANUAL"  # No algorithmic scheduling


class ExecutionStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class SliceStatus(str, Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    WORKING = "WORKING"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


# ---------------------------------------------------------------------------
# ParentExecution — the trader's top-level algorithmic objective
# ---------------------------------------------------------------------------

class ParentExecution(Base):
    __tablename__ = "parent_executions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    order_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    trader: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # Objective
    schedule_type: Mapped[str] = mapped_column(String(16), nullable=False)
    target_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    filled_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Scheduling window (nullable for MANUAL)
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Participation / urgency
    participation_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    urgency: Mapped[str | None] = mapped_column(String(16), nullable=True)

    # Benchmark reference price (e.g. arrival price for IS)
    benchmark_price: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Broker / strategy defaults for child slices
    broker: Mapped[str | None] = mapped_column(String(64), nullable=True)
    strategy_params: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default=ExecutionStatus.PENDING.value, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    # Relationship
    slices: Mapped[list["ChildSlice"]] = relationship(back_populates="parent", lazy="selectin")


# ---------------------------------------------------------------------------
# ChildSlice — one discrete route submitted by the scheduler
# ---------------------------------------------------------------------------

class ChildSlice(Base):
    __tablename__ = "child_slices"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    parent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("parent_executions.id"), nullable=False, index=True)

    # Route identity (matches routes_projection keys)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    route_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    # Slice schedule
    slice_index: Mapped[int] = mapped_column(Integer, nullable=False)
    planned_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    filled_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Optional scheduled time window for this slice
    scheduled_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scheduled_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Limit price / strategy override for this slice
    limit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    strategy_params: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default=SliceStatus.PENDING.value, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    # Relationship
    parent: Mapped["ParentExecution"] = relationship(back_populates="slices")
