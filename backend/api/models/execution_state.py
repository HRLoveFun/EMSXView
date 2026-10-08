from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB  # noqa: F401 保留兼容导入

# 048：JSONB → 跨方言 JSON——SQLite 演练环境可用；PostgreSQL 上 JSON 类型
# 同样有效（本仓库未使用 JSONB 操作符查询），既有 PG 表结构不受影响。
JSONPayload = JSON

# 048：SQLite 主键自增仅对 Integer 生效（BigInteger PK 不触发 ROWID 自增）——
# 跨方言主键类型：PostgreSQL 仍为 BIGINT，SQLite 映射为 INTEGER 自增。
BigIntPK = BigInteger().with_variant(Integer, "sqlite")
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class OrderProjection(Base):
    __tablename__ = "orders_projection"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, unique=True, index=True)
    order_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    trader: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSONPayload, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class RouteProjection(Base):
    __tablename__ = "routes_projection"
    __table_args__ = (
        UniqueConstraint("sequence", "route_id", name="uq_routes_projection_sequence_route_id"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    route_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    broker: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSONPayload, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actor: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    endpoint: Mapped[str] = mapped_column(String(128), nullable=False)
    result: Mapped[str] = mapped_column(String(32), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    payload_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class SubscriptionWatermark(Base):
    __tablename__ = "subscription_watermarks"

    stream_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_event_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
