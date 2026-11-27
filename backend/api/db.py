"""Operational database bootstrap for ExecutionView live execution state.

This module manages the optional persistence layer used for order/route/audit
projections and warm-start reads. It does not own fills-centric execution
history, which remains in CostView stores behind ``platform_data.execution_history``.
Order and route projections plus ``audit_events`` may be exported as
read-only backfill seeds, but they are not the canonical warehouse.

DL-02/060：默认运营库为 SQLite（D-4）——DATABASE_URL 显式设置时以它为准
（docker-compose 部署仍走 PostgreSQL），未设置时落到 EMSXVIEW_OPS_DB_DIR
（默认用户主目录 .emsxview/ops）下的 emsx_ops.db。SQLite 连接统一注入
WAL / busy_timeout / foreign_keys，见 _apply_sqlite_pragmas。
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

logger = logging.getLogger(__name__)

DEFAULT_DATABASE_URL = "postgresql+asyncpg://emsx:emsx@postgres:5432/emsx"

# SQLite 运营库 PRAGMA 口径（与 data_access 分析库 busy_timeout 30s 一致；
# foreign_keys 必须显式开启——SQLite 默认 OFF，建议单 FK 锚点依赖它）
SQLITE_BUSY_TIMEOUT_MS = 30000

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_database_url() -> str:
    """运营库连接串解析（DL-02/060）。

    优先级：env DATABASE_URL 显式值 → SQLite（EMSXVIEW_OPS_DB_DIR 或默认目录）
    → PG 默认兜底。显式值路径保证 docker-compose 部署行为不变。
    """
    env_url = os.getenv("DATABASE_URL")
    if env_url:
        return env_url
    from config import resolve_ops_db_dir, settings

    db_dir = resolve_ops_db_dir()
    return f"sqlite+aiosqlite:///{db_dir.replace(os.sep, '/')}/{settings.OPS_DB_FILE_NAME}"


def _apply_sqlite_pragmas(engine: AsyncEngine) -> None:
    """为 SQLite 引擎注入连接级 PRAGMA（WAL / busy_timeout / FK）。"""

    @event.listens_for(engine.sync_engine, "connect")
    def _set_pragmas(dbapi_conn, _record):  # pragma: no cover - 依赖真实连接
        cursor = dbapi_conn.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()


def _pool_options() -> dict:
    """连接池容量与取连接超时（env 可覆盖）。

    2026-11-27 事故：EMSX 订单/路由事件成批到达（单批 25+ 次写）与分析型
    只读查询并发时，默认 QueuePool(5+10) 被瞬时打满；写请求在池上排队 30s
    后超时，5s 健康探针也拿不到连接 → 误报 BACKEND_UNREACHABLE，并把写熔断
    推到阈值。SQLite(WAL) 连接成本低，放宽到 10+20 吸收突发；取连接超时
    缩短到 10s，使真正的池饥饿尽快失败而不是长时间挂住探针。
    """
    return {
        "pool_size": max(1, int(os.getenv("DB_POOL_SIZE", "10"))),
        "max_overflow": max(0, int(os.getenv("DB_MAX_OVERFLOW", "20"))),
        "pool_timeout": max(1.0, float(os.getenv("DB_POOL_TIMEOUT_SECONDS", "10"))),
    }


def create_engine(database_url: str | None = None) -> AsyncEngine:
    url = database_url or get_database_url()
    connect_args: dict = {}
    if url.startswith("sqlite"):
        # 运营库目录默认在仓库外（~/.emsxview/ops），首次启动需创建；
        # aiosqlite 不会自动建目录，缺失时连接直接报 unable to open database file。
        # 用 Path.parent 解析——URL 路径可能是反斜杠（Windows env 直填），
        # 按 "/" 切分会把整个文件路径误判为目录
        db_dir = Path(url.split(":///", 1)[1]).parent
        os.makedirs(db_dir, exist_ok=True)
        # aiosqlite 层超时与 busy_timeout 双保险（连接建立与语句执行两个阶段）
        connect_args = {"timeout": SQLITE_BUSY_TIMEOUT_MS / 1000}
    engine = create_async_engine(
        url,
        pool_pre_ping=True,
        future=True,
        connect_args=connect_args,
        **_pool_options(),
    )
    if url.startswith("sqlite"):
        _apply_sqlite_pragmas(engine)
    return engine


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


async def _ensure_decision_columns(conn) -> None:
    """214：存量 ``routing_decisions`` 表补 ``source`` / ``updated_at``（幂等）。

    ``create_all`` 不会给已存在的表加列；这里做最小化迁移。失败只告警，
    影子记录写入会因缺列返回 False，不阻断主服务。
    """
    try:
        if conn.dialect.name == "sqlite":
            result = await conn.execute(text("PRAGMA table_info(routing_decisions)"))
            columns = {row[1] for row in result.fetchall()}
            if "source" not in columns:
                await conn.execute(
                    text("ALTER TABLE routing_decisions ADD COLUMN source VARCHAR(24) DEFAULT 'ENGINE'")
                )
            if "updated_at" not in columns:
                await conn.execute(
                    text("ALTER TABLE routing_decisions ADD COLUMN updated_at DATETIME")
                )
        elif conn.dialect.name == "postgresql":
            await conn.execute(
                text("ALTER TABLE routing_decisions ADD COLUMN IF NOT EXISTS source VARCHAR(24) DEFAULT 'ENGINE'")
            )
            await conn.execute(
                text(
                    "ALTER TABLE routing_decisions ADD COLUMN IF NOT EXISTS "
                    "updated_at TIMESTAMP WITH TIME ZONE"
                )
            )
    except Exception:
        logger.warning(
            "routing_decisions column migration failed (shadow records may degrade)",
            exc_info=True,
        )


async def initialize_database() -> tuple[bool, str]:
    try:
        from models.execution_state import Base

        # 048 实测修复：必须显式 import 全部模型模块——SQLAlchemy 只把
        # 「已导入模块」中定义的表注册进 Base.metadata。此前仅导入
        # execution_state，route_plans / sub_order_proposals /
        # authorization_intents / parent_executions 等表从未被创建。
        import models.authorization  # noqa: F401
        import models.parent_child_orders  # noqa: F401
        import models.route_plan  # noqa: F401

        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await _ensure_decision_columns(conn)
        return True, "schema initialized"
    except Exception as exc:  # pragma: no cover - runtime environment dependent
        return False, str(exc)


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
