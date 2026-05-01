"""Route Plan models — pre-trade route plan templates and sub-order proposals.

A *RoutePlan* is a reusable template that defines how to split
an incoming parent order into sub-order proposals.
A *RoutePlanAllocation* defines per-broker allocation within a plan.
A *SubOrderProposal* is a generated sub-order pending trader confirmation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.execution_state import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Enum helpers
# ---------------------------------------------------------------------------

class ActivationMode(str, Enum):
    AUTO = "AUTO"
    MANUAL = "MANUAL"


class SubmissionMode(str, Enum):
    MANUAL_CONFIRM = "MANUAL_CONFIRM"
    AUTO_SUBMIT = "AUTO_SUBMIT"


class SplitType(str, Enum):
    BROKER_SPLIT = "BROKER_SPLIT"
    TIME_SCHEDULE = "TIME_SCHEDULE"
    HYBRID = "HYBRID"


class AllocationType(str, Enum):
    PERCENTAGE = "PERCENTAGE"
    FIXED = "FIXED"


class ProposalStatus(str, Enum):
    PENDING_CONFIRM = "PENDING_CONFIRM"
    CONFIRMED = "CONFIRMED"
    SUBMITTED = "SUBMITTED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class MatchSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    BOTH = "BOTH"


# ---------------------------------------------------------------------------
# RoutePlan — reusable route plan template
# ---------------------------------------------------------------------------

class RoutePlan(Base):
    __tablename__ = "route_plans"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Match criteria
    match_market: Mapped[str] = mapped_column(String(32), nullable=False, default="", index=True)
    match_symbol: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    match_side: Mapped[str] = mapped_column(String(8), nullable=False, default=MatchSide.BOTH.value)
    match_portfolio: Mapped[str | None] = mapped_column(String(64), nullable=True)
    match_trader: Mapped[str | None] = mapped_column(String(64), nullable=True)
    match_exchange: Mapped[str | None] = mapped_column(String(32), nullable=True)
    match_currency: Mapped[str | None] = mapped_column(String(8), nullable=True)

    # Activation / submission mode
    activation_mode: Mapped[str] = mapped_column(String(16), nullable=False, default=ActivationMode.MANUAL.value)
    submission_mode: Mapped[str] = mapped_column(String(16), nullable=False, default=SubmissionMode.MANUAL_CONFIRM.value)

    # Status
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Split strategy
    split_type: Mapped[str] = mapped_column(String(16), nullable=False, default=SplitType.BROKER_SPLIT.value)

    # Time schedule config (for TIME_SCHEDULE or HYBRID)
    schedule_type: Mapped[str | None] = mapped_column(String(16), nullable=True)  # TWAP/VWAP/POV
    num_slices: Mapped[int | None] = mapped_column(Integer, nullable=True)
    default_start_offset_min: Mapped[int | None] = mapped_column(Integer, nullable=True)  # minutes from now
    default_end_time_local: Mapped[str | None] = mapped_column(String(8), nullable=True)  # e.g. "16:00"
    participation_rate: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Default route params for generated proposals
    default_broker: Mapped[str | None] = mapped_column(String(64), nullable=True)
    default_order_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    default_tif: Mapped[str | None] = mapped_column(String(8), nullable=True)
    default_strategy_params: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    # Relationships
    allocations: Mapped[list["RoutePlanAllocation"]] = relationship(
        back_populates="route_plan", lazy="selectin", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# RoutePlanAllocation — per-broker allocation entry
# ---------------------------------------------------------------------------

class RoutePlanAllocation(Base):
    __tablename__ = "route_plan_allocations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    route_plan_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("route_plans.id", ondelete="CASCADE"), nullable=False, index=True
    )

    broker: Mapped[str] = mapped_column(String(64), nullable=False)
    allocation_type: Mapped[str] = mapped_column(String(16), nullable=False, default=AllocationType.PERCENTAGE.value)
    allocation_value: Mapped[float] = mapped_column(Float, nullable=False)

    # Per-broker route parameters (override plan defaults)
    order_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    limit_price_offset: Mapped[float | None] = mapped_column(Float, nullable=True)
    strategy_params: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    # Relationship
    route_plan: Mapped["RoutePlan"] = relationship(back_populates="allocations")


# ---------------------------------------------------------------------------
# SubOrderProposal — generated sub-order awaiting trader action
# ---------------------------------------------------------------------------

class SubOrderProposal(Base):
    __tablename__ = "sub_order_proposals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    route_plan_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("route_plans.id", ondelete="SET NULL"), nullable=True, index=True
    )
    parent_order_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # Route identity (populated after EMSX submission)
    route_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Proposal details
    broker: Mapped[str] = mapped_column(String(64), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    order_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    limit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    tif: Mapped[str | None] = mapped_column(String(8), nullable=True)
    strategy_params: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Time schedule info (for TIME_SCHEDULE / HYBRID)
    slice_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scheduled_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scheduled_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Parent order snapshot (for display without re-fetching)
    parent_symbol: Mapped[str | None] = mapped_column(String(32), nullable=True)
    parent_side: Mapped[str | None] = mapped_column(String(8), nullable=True)
    parent_trader: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parent_portfolio: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Status
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=ProposalStatus.PENDING_CONFIRM.value, index=True)

    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
