"""
Application configuration — Settings class and validated singleton.

Extracted from main.py so that routers and services can import ``settings``
without pulling in the entire application module.
"""

from __future__ import annotations

import os
import logging
from pathlib import Path
from typing import List

logger = logging.getLogger("main")


class Settings:
    """Application settings from environment variables."""

    # Bloomberg Configuration
    BLOOMBERG_HOST: str = os.getenv("BLOOMBERG_HOST", "localhost")
    BLOOMBERG_PORT: int = int(os.getenv("BLOOMBERG_PORT", "8194"))
    BLOOMBERG_TIMEOUT: int = int(os.getenv("BLOOMBERG_TIMEOUT", "60000"))

    # API Configuration
    API_HOST: str = os.getenv("API_HOST", "0.0.0.0")
    API_PORT: int = int(os.getenv("API_PORT", "3000"))
    API_WORKERS: int = int(os.getenv("API_WORKERS", "1"))

    # Database Configuration
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql+asyncpg://emsx:emsx@postgres:5432/emsx")
    DATABASE_MIGRATION_URL: str = os.getenv("DATABASE_MIGRATION_URL", "postgresql+psycopg://emsx:emsx@postgres:5432/emsx")

    # 运营库（ExecutionView 订单/路由/审计持久化，D-4：SQLite）——
    # 库文件放仓库外固定目录，不与管道分析库（${EMSXVIEW_DATA_DIR}）混放。
    # 未配置时取用户主目录下 .emsxview/ops/emsx_ops.db；显式设置 DATABASE_URL 时
    # 以它为准（docker-compose 部署仍走 PostgreSQL，行为不变）。
    EMSXVIEW_OPS_DB_DIR: str = os.getenv("EMSXVIEW_OPS_DB_DIR", "")
    OPS_DB_FILE_NAME: str = "emsx_ops.db"

    # Security
    JWT_SECRET: str = os.getenv("JWT_SECRET", "")
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = int(os.getenv("JWT_EXPIRE_MINUTES", "480"))

    # CORS
    ALLOWED_ORIGINS: List[str] = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:80").split(",")

    # Trading
    ALLOWED_TRADERS: List[str] = os.getenv("ALLOWED_TRADERS", "").split(",")
    MAX_BATCH_SIZE: int = int(os.getenv("MAX_BATCH_SIZE", "100"))

    # Batch route / modify-route operations (separate from MAX_BATCH_SIZE which
    # is used by /api/orders/batch-update for legacy reasons).
    BATCH_ROUTE_MAX_SIZE: int = int(os.getenv("BATCH_ROUTE_MAX_SIZE", "500"))

    # Concurrent in-flight EMSX submissions per batch.
    BATCH_CONCURRENCY: int = int(os.getenv("BATCH_CONCURRENCY", "5"))

    # Size of the dedicated request session pool (N=1 = legacy single-session).
    # Multiple sessions allow concurrent EMSX RouteEx submissions.
    REQUEST_SESSION_POOL_SIZE: int = int(os.getenv("REQUEST_SESSION_POOL_SIZE", "1"))

    # Pre-trade compliance thresholds (USD). Values failing these bounds are
    # hard-blocked. See services/compliance_service.py.
    USD_NOTIONAL_MIN: float = float(os.getenv("USD_NOTIONAL_MIN", "10000"))
    USD_NOTIONAL_MAX: float = float(os.getenv("USD_NOTIONAL_MAX", "49000000"))

    # Odd lot detection markets
    ODD_LOT_MARKETS: List[str] = [
        m.strip().upper()
        for m in os.getenv("ODD_LOT_MARKETS", "JP,US").split(",")
        if m.strip()
    ]

    # Features
    ENABLE_REALTIME: bool = os.getenv("ENABLE_REALTIME", "true").lower() == "true"
    ENABLE_AUDIT_LOG: bool = os.getenv("ENABLE_AUDIT_LOG", "true").lower() == "true"

    # 执行驱动循环 (S9/039)：默认关闭——开启后调度驱动会把到期切片
    # 提交到市场（真实下单），须显式评估并接线 submit 函数后启用
    EXECUTION_DRIVER_ENABLED: bool = os.getenv("EXECUTION_DRIVER_ENABLED", "false").lower() == "true"

    # Trader identity
    EMSXVIEW_TRADER_NAME: str = os.getenv("EMSXVIEW_TRADER_NAME", "")

    # 用户源 (S10/040)：JSON 数组，替代硬编码 DEMO_USERS。
    # 每项：{"username", "password_hash"(bcrypt), "full_name", "role"}
    # 生成 bcrypt：python -c "from passlib.context import CryptContext; print(CryptContext(schemes=['bcrypt']).hash('明文'))"
    # 未配置时回落 DEMO_USERS 并启动告警（诚实可见）。
    EMSXVIEW_USERS: str = os.getenv("EMSXVIEW_USERS", "")

    # Development mode
    BYPASS_AUTH: bool = os.getenv("BYPASS_AUTH", "false").lower() == "true"
    # DEBUG 模式下 API 响应透传内部异常 detail (默认遮蔽)
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"

    # 057 DL-15：盘中市场状态（C 层实时特征）；G2 特性开关，默认关闭
    EMSXVIEW_INTRADAY_STATE_ENABLED: bool = (
        os.getenv("EMSXVIEW_INTRADAY_STATE_ENABLED", "false").lower() == "true"
    )

    # Persistence
    ENABLE_DB_PERSISTENCE: bool = os.getenv("ENABLE_DB_PERSISTENCE", "false").lower() == "true"

    # 数据管道 Runner（EMSXDataPipeline 独立进程，默认 :8100）——
    # P2-4 整改：前端不再直连 Runner，统一经 :3000 鉴权代理转发
    RUNNER_URL: str = os.getenv("EMSXVIEW_RUNNER_URL", "http://127.0.0.1:8100")

    # Optional module routers — comma-separated "module:label" pairs.
    # Set to empty string to disable all optional modules.
    # Set to "*" or "all" to load all known optional modules.
    # Default loads CostView (bridged TCA/monitoring routers,
    # so the frontend reaches /api/tca/* via :3000 without a separate :8002).
    # 010-extract-pipeline: DatabaseView 已迁独立项目 EMSXDataPipeline Runner，
    # 其 /api/db/* 端点不再由本仓库提供（P2-2 整改：清除默认值残留）。
    # Example: EMSXVIEW_OPTIONAL_MODULES=costview:CostView
    OPTIONAL_MODULES: str = os.getenv(
        "EMSXVIEW_OPTIONAL_MODULES",
        "costview:CostView",
    )


def default_ops_db_dir() -> str:
    """运营库默认目录（DL-02/060）：用户主目录下固定路径，仓库外、免安装。

    单人单机场景（D-4）；显式设置 EMSXVIEW_OPS_DB_DIR 可改指任意仓库外路径。
    """
    return str(Path.home() / ".emsxview" / "ops")


def resolve_ops_db_dir() -> str:
    """运营库目录解析：EMSXVIEW_OPS_DB_DIR 显式值优先，否则取默认目录。"""
    return settings.EMSXVIEW_OPS_DB_DIR or default_ops_db_dir()


def _validate_settings(s: Settings) -> None:
    """Validate critical settings on startup."""
    if not s.BYPASS_AUTH and not s.JWT_SECRET:
        raise ValueError(
            "JWT_SECRET environment variable must be set. "
            "Generate a secure key with: openssl rand -hex 32"
        )
    weak_secrets = [
        "your-secret-key", "change-in-production", "secret", "password",
        # 曾硬编码在 start-backend.ps1 中的历史回退密钥（P1-1 整改）
        "bbgemsxprogramatictrading",
    ]
    if s.JWT_SECRET and any(weak in s.JWT_SECRET.lower() for weak in weak_secrets):
        logger.warning("JWT_SECRET appears to be using a weak/default value.")
    logger.info(f"Settings validated: BYPASS_AUTH={s.BYPASS_AUTH}, JWT_SECRET set={bool(s.JWT_SECRET)}")
    logger.info(f"Odd lot detection enabled for markets: {s.ODD_LOT_MARKETS}")
    logger.info(f"DB persistence: ENABLE_DB_PERSISTENCE={s.ENABLE_DB_PERSISTENCE}")
    # DL-02/060：运营库位置始终可见——未显式设 DATABASE_URL 时默认走 SQLite，
    # 路径须可追溯（库文件在仓库外，备份与恢复演练以此为准）
    logger.info(f"Operational DB: url_source={'env' if 'DATABASE_URL' in os.environ else 'default'}, sqlite_dir={resolve_ops_db_dir()}")


settings = Settings()
_validate_settings(settings)
