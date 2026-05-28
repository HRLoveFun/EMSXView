"""Operational database bootstrap for ExecutionView live execution state.

This module manages the optional PostgreSQL layer used for order/route/audit
projections and warm-start reads. It does not own fills-centric execution
history, which remains in CostView stores behind ``platform_data.execution_history``.
Order and route projections plus ``audit_events`` may be exported as
read-only backfill seeds, but they are not the canonical warehouse.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

DEFAULT_DATABASE_URL = "postgresql+asyncpg://emsx:emsx@postgres:5432/emsx"

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_database_url() -> str:
    return os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)


def create_engine(database_url: str | None = None) -> AsyncEngine:
    return create_async_engine(
        database_url or get_database_url(),
        pool_pre_ping=True,
        future=True,
    )


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_engine()
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


@asynccontextmanager
async def get_db_session() -> AsyncIterator[AsyncSession]:
    session_factory = get_session_factory()
    async with session_factory() as session:
        yield session


async def check_database_connection() -> tuple[bool, str]:
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True, "connected"
    except Exception as exc:  # pragma: no cover - runtime environment dependent
        return False, str(exc)


async def initialize_database() -> tuple[bool, str]:
    try:
        from models.execution_state import Base

        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        return True, "schema initialized"
    except Exception as exc:  # pragma: no cover - runtime environment dependent
        return False, str(exc)


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
