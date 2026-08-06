#!/usr/bin/env python3
"""
EMSXView Trading API - Bloomberg EMSX Integration Service
Production-ready backend for EMSXView Trading Tool

Author: Trading Systems Team
Version: 1.0.0
"""

import os
import sys
import json
import glob
import time
import asyncio
import logging
import logging.handlers
from datetime import datetime
from typing import List, Optional
from contextlib import asynccontextmanager
from pathlib import Path

try:
    import aiofiles
except ImportError:
    aiofiles = None

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

from config import settings
from db import dispose_engine, initialize_database
from service_provider import RepositoryProvider

# ============================================================================
# Logging Configuration
# ============================================================================

# Get log configuration from environment variables with sensible defaults
LOG_LEVEL = os.getenv('LOG_LEVEL', 'WARNING').upper()
LOG_MAX_BYTES = int(os.getenv('LOG_MAX_BYTES', 5 * 1024 * 1024))  # 5 MB default
LOG_BACKUP_COUNT = int(os.getenv('LOG_BACKUP_COUNT', 3))  # 3 files default
LOG_MAX_AGE_DAYS = int(os.getenv('LOG_MAX_AGE_DAYS', 3))  # 3 days default
LOG_DIR = os.getenv('LOG_DIR', '../../logs')  # Default to project root logs/

# Ensure log directory exists (support both relative and absolute paths)
log_path = Path(LOG_DIR).resolve()
os.makedirs(log_path, exist_ok=True)


class _SizeAndAgeRotatingHandler(logging.handlers.RotatingFileHandler):
    """RotatingFileHandler that also purges backup files older than max_age_days."""

    def __init__(self, filename, max_bytes=5 * 1024 * 1024, backup_count=3,
                 max_age_days=3, **kwargs):
        self._max_age_days = max_age_days
        super().__init__(filename, maxBytes=max_bytes, backupCount=backup_count, **kwargs)
        self._purge_old_files()

    def doRollover(self):
        super().doRollover()
        self._purge_old_files()

    def _purge_old_files(self):
        cutoff = time.time() - self._max_age_days * 86400
        base = self.baseFilename
        for path in glob.glob(base + '.*') + [base]:
            try:
                if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                    os.remove(path)
                    # Suppressed log to avoid recursion during logging setup
            except OSError:
                pass


# Configure logging format
_log_formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# File handler with rotation
_file_handler = _SizeAndAgeRotatingHandler(
    str(log_path / 'emsx_api.log'),
    max_bytes=LOG_MAX_BYTES,       # 5 MB per file (configurable)
    backup_count=LOG_BACKUP_COUNT,  # 3 rotated files max
    max_age_days=LOG_MAX_AGE_DAYS,  # purge files older than 3 days
    encoding='utf-8',
)
_file_handler.setFormatter(_log_formatter)

# Console handler
_console_handler = logging.StreamHandler(sys.stdout)
_console_handler.setFormatter(_log_formatter)

# Set log level from environment
numeric_level = getattr(logging, LOG_LEVEL, logging.WARNING)
logging.basicConfig(level=numeric_level, handlers=[_console_handler, _file_handler])
logger = logging.getLogger(__name__)

logger.info(f"Logging configured: level={LOG_LEVEL}, max_bytes={LOG_MAX_BYTES}, "
            f"backup_count={LOG_BACKUP_COUNT}, max_age_days={LOG_MAX_AGE_DAYS}, "
            f"log_dir={log_path}")

# ============================================================================
# Configuration (imported from config.py)
# ============================================================================

# settings is imported from config.py at the top of this file

# Repository provider — gates DB read/write behind ENABLE_DB_PERSISTENCE
repo_provider = RepositoryProvider(enabled=settings.ENABLE_DB_PERSISTENCE)

# ============================================================================
# Data Models (imported from models.py)
# ============================================================================

from schemas import (
    ApiResponse,
)


# ============================================================================
# Broker Algorithm Storage Service
# ============================================================================

from services.broker_storage_service import BrokerAlgorithmStorageService
broker_storage = BrokerAlgorithmStorageService()

# ============================================================================
# Bloomberg EMSX Service (imported from services/bloomberg_adapter.py)
# ============================================================================

from services.bloomberg_adapter import BloombergEMSXService, configure as _configure_bloomberg
_configure_bloomberg(settings, repo_provider)
bloomberg_service = BloombergEMSXService()


# ============================================================================
# Authentication (imported from deps.py)
# ============================================================================

from deps import verify_token, audit_log, init_services

# Wire singletons into the shared dependency module (legacy path).
# P2-2: Services are also stored in app.state below for FastAPI Depends().
init_services(bloomberg_service, broker_storage, repo_provider)

# Phase 4: Register DataPipeline Config so platform_data consumers can
# resolve table names etc. without importing DataPipeline directly.
try:
    from DataPipeline.config import Config
    from platform_data.config_bridge import register_config_impl
    register_config_impl(Config)
    logger.info("Registered DataPipeline Config in platform_data bridge")
except ImportError:
    logger.debug("DataPipeline not available; skipping Config DI registration")

# ============================================================================
# FastAPI Application
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    # Startup
    logger.info("=" * 60)
    logger.info("EMSXView Trading API Starting...")
    logger.info(f"Version: 1.0.0")
    logger.info(f"Bloomberg: {settings.BLOOMBERG_HOST}:{settings.BLOOMBERG_PORT}")
    logger.info(f"Database: {settings.DATABASE_URL}")
    logger.info("=" * 60)

    if settings.ENABLE_DB_PERSISTENCE:
        db_ready, db_message = await initialize_database()
        if db_ready:
            logger.info("Database schema bootstrap completed")
            repo_provider.mark_db_ready(True)
        else:
            logger.warning("Database schema bootstrap failed: %s", db_message)
            repo_provider.mark_db_ready(False)
    else:
        logger.info("Database persistence disabled; skipping schema bootstrap")
        repo_provider.mark_db_ready(False)

    # Start Bloomberg connection in background so the server is ready to accept
    # HTTP requests immediately (Bloomberg session.start() + openService() are
    # synchronous SDK calls that can take 30-120s during BPIPE initialisation).
    asyncio.create_task(bloomberg_service.connect())
    logger.info("Bloomberg connection started in background")

    yield
    
    # Shutdown
    logger.info("Shutting down EMSXView Trading API...")
    bloomberg_service.disconnect()
    await dispose_engine()


app = FastAPI(
    title="EMSXView Trading API",
    description=(
        "Bloomberg EMSX Integration Service for Trading Tool. "
        "Provides pre-trade MarketView, order/route ExecutionView, and "
        "post-trade CostView TCA analytics."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    contact={"name": "Trading Systems Team"},
    license_info={"name": "Proprietary"},
    swagger_ui_parameters={"defaultModelsExpandDepth": -1},
)

# P2-2: Store service singletons in app.state for FastAPI Depends() DI.
# This replaces the global mutable state in deps.py (get_bloomberg / get_broker_storage).
# New code should use: bloomberg_svc: BloombergEMSXService = Depends(get_bloomberg_service)
app.state.bloomberg_service = bloomberg_service
app.state.broker_storage = broker_storage
app.state.repo_provider = repo_provider

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"]
)

# ============================================================================
# Domain Routers
# ============================================================================

from routers.connection import router as connection_router
from routers.auth import router as auth_router
from routers.orders import router as orders_router
from routers.routes import router as routes_router
from routers.broker import router as broker_router
from routers.debug import router as debug_router
from routers.realtime import router as realtime_router
from routers.market_broker_mapping import router as market_broker_mapping_router
from routers.route_plans import router as route_plans_router

app.include_router(connection_router)
app.include_router(auth_router)
app.include_router(orders_router)
app.include_router(routes_router)
app.include_router(broker_router)
app.include_router(debug_router)
app.include_router(realtime_router)
app.include_router(market_broker_mapping_router)
app.include_router(route_plans_router)

# ============================================================================
# Optional Module Routers — config-driven via EMSXVIEW_OPTIONAL_MODULES env var.
# Each entry is "module:label", comma-separated. Failure of any single module
# must never prevent the core ExecutionView from starting.
# ============================================================================

# Registry of all known optional modules (single source of truth).
# Environment variable can override which subset to load.
# PR-2: execution_history 孤儿 API 已退役（前端 0 个消费者，被 baseline_violations.json
# 记录为 AP-05 违规）。保留注释以追踪删除原因。
_KNOWN_OPTIONAL_MODULES: dict[str, str] = {
    "database": "DatabaseView",
    # costview 为桥接 router（backend/api/routers/costview.py），将 CostView
    # 服务的 /api/tca/* 与 /api/tca/monitoring/* 合并进 core 进程，
    # 使前端经 :3000 单入口即可访问 TCA 与监控端点。
    "costview": "CostView",
}


def _parse_optional_modules(raw: str) -> list[tuple[str, str]]:
    """Parse EMSXVIEW_OPTIONAL_MODULES into (module_name, label) pairs.

    Supports:
      - "*" or "all" → load all known optional modules
      - "" (empty) → load none
      - "costview:Label,database:Label" → load specified modules with custom labels
    """
    if not raw or raw.strip() == "":
        return []
    if raw.strip() in ("*", "all"):
        return list(_KNOWN_OPTIONAL_MODULES.items())
    result: list[tuple[str, str]] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            name, label = part.split(":", 1)
            result.append((name.strip(), label.strip()))
        else:
            # Module name only — use known label or default
            name = part.strip()
            label = _KNOWN_OPTIONAL_MODULES.get(name, name)
            result.append((name, label))
    return result


def _register_optional(module_name: str, router_label: str) -> None:
    """Lazily import and register an optional router; log warning on failure."""
    import importlib
    try:
        mod = importlib.import_module(f"routers.{module_name}")
        app.include_router(mod.router)
    except Exception as exc:  # noqa: BLE001
        logging.getLogger("main").warning(
            "%s router 未加载（ExecutionView 不受影响）: %s", router_label, exc
        )


for _mod_name, _mod_label in _parse_optional_modules(settings.OPTIONAL_MODULES):
    _register_optional(_mod_name, _mod_label)

# ============================================================================
# Error Handlers
# ============================================================================

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content=ApiResponse(success=False, error=exc.detail).model_dump()
    )

@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    logger.exception("Unhandled exception")
    return JSONResponse(
        status_code=500,
        content=ApiResponse(success=False, error="Internal server error").model_dump()
    )

# ============================================================================
# Main Entry Point
# ============================================================================

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        workers=settings.API_WORKERS,
        log_level="info",
        reload=False
    )
