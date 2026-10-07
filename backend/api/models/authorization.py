"""PM 授权意图模型 (S12/042) —— 投资决策层的数量授权。

报告场景：「PM 要买 100 万股，允许今天完成 60 万股；其中 30 万股正在
券商算法中执行。系统应知道剩余授权是多少，而不仅显示订单还剩多少股。」

AuthorizationIntent 记录 PM 的授权（symbol+side+portfolio 维度的
数量上限），剩余授权 = target_quantity − 执行占用（父单承诺量）。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from models.execution_state import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AuthorizationStatus:
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    CANCELLED = "CANCELLED"


class AuthorizationIntent(Base):
    """一条 PM 授权：对 symbol+side(+portfolio) 的数量上限。"""

    __tablename__ = "authorization_intents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # 授权维度——symbol 精确匹配；side 为 BUY/SELL；portfolio 可空（不限组合）
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    portfolio: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    # PM 授权目标数量
    target_quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    # 授权元数据
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE", index=True)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    note: Mapped[str | None] = mapped_column(String(256), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
