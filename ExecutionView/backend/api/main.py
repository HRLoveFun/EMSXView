#!/usr/bin/env python3
"""
EMSX Trading API - Bloomberg EMSX Integration Service
Production-ready backend for EMSX Trading Tool

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
logger = logging.getLogger(__name__)

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
    ApiResponse, BrokerAlgorithmConfig, BrokerAlgorithmStorage,
)


# ============================================================================
# Broker Algorithm Storage Service
# ============================================================================

class BrokerAlgorithmStorageService:
    """
    Persistent storage for broker algorithm configuration.
    Stores data in a JSON file and provides freshness checking.
    """
    
    def __init__(self, storage_dir: str = "./data"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.storage_file = self.storage_dir / "broker_algorithms.json"
        self._cache: Optional[BrokerAlgorithmStorage] = None
        self._lock = asyncio.Lock()
    
    async def load(self) -> Optional[BrokerAlgorithmStorage]:
        """Load stored configuration from disk"""
        async with self._lock:
            if self._cache is not None:
                return self._cache
            
            try:
                if self.storage_file.exists():
                    if aiofiles:
                        async with aiofiles.open(self.storage_file, 'r') as f:
                            content = await f.read()
                    else:
                        # Fallback to synchronous file I/O
                        with open(self.storage_file, 'r') as f:
                            content = f.read()
                    data = json.loads(content)
                    self._cache = BrokerAlgorithmStorage(**data)
                    logger.info(f"[BrokerAlgorithmStorage] Loaded {len(self._cache.configs)} broker configs")
                    return self._cache
            except Exception as e:
                logger.error(f"[BrokerAlgorithmStorage] Failed to load: {e}")
            
            return None
    
    async def save(self, configs: List[BrokerAlgorithmConfig]) -> bool:
        """Save configuration to disk"""
        async with self._lock:
            try:
                storage = BrokerAlgorithmStorage(configs=configs)
                self._cache = storage
                
                content = json.dumps(storage.model_dump(), indent=2)
                if aiofiles:
                    async with aiofiles.open(self.storage_file, 'w') as f:
                        await f.write(content)
                else:
                    # Fallback to synchronous file I/O
                    with open(self.storage_file, 'w') as f:
                        f.write(content)
                
                logger.info(f"[BrokerAlgorithmStorage] Saved {len(configs)} broker configs")
                return True
            except Exception as e:
                logger.error(f"[BrokerAlgorithmStorage] Failed to save: {e}")
                return False
    
    async def get_configs(self) -> List[BrokerAlgorithmConfig]:
        """Get all stored configurations"""
        storage = await self.load()
        return storage.configs if storage else []
    
    async def get_last_updated(self) -> Optional[datetime]:
        """Get last update timestamp"""
        storage = await self.load()
        if storage and storage.lastUpdated:
            try:
                return datetime.fromisoformat(storage.lastUpdated)
            except:
                pass
        return None
    
    async def needs_refresh(self) -> bool:
        """Check if data needs refresh (older than 1 day)"""
        last_updated = await self.get_last_updated()
        if not last_updated:
            return True
        
        now = datetime.now()
        last_update_day = last_updated.replace(hour=0, minute=0, second=0, microsecond=0)
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        
        return last_update_day < today
    
    def clear_cache(self):
        """Clear in-memory cache"""
        self._cache = None

# Global storage instance
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

# Wire singletons into the shared dependency module
init_services(bloomberg_service, broker_storage, repo_provider)

# ============================================================================
# FastAPI Application
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    # Startup
    logger.info("=" * 60)
    logger.info("EMSX Trading API Starting...")
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
    logger.info("Shutting down EMSX Trading API...")
    bloomberg_service.disconnect()
    await dispose_engine()


app = FastAPI(
    title="EMSX Trading API",
    description="Bloomberg EMSX Integration Service for Trading Tool",
    version="1.0.0",
    lifespan=lifespan
)

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
from routers.marketview import router as marketview_router
from routers.auth import router as auth_router
from routers.orders import router as orders_router
from routers.routes import router as routes_router
from routers.broker import router as broker_router
from routers.debug import router as debug_router
from routers.realtime import router as realtime_router

app.include_router(connection_router)
app.include_router(marketview_router)
app.include_router(auth_router)
app.include_router(orders_router)
app.include_router(routes_router)
app.include_router(broker_router)
app.include_router(debug_router)
app.include_router(realtime_router)

# CostView TCA 路由 — 可选模块，不影响 ExecutionView 核心启动
# MarketView / ExecutionView / CostView 是三个独立模块，任一模块
# 的异常不应导致其他模块无法启动。
try:
    from routers.costview import router as costview_router
    app.include_router(costview_router)
except Exception as _costview_err:  # noqa: BLE001
    import logging as _log
    _log.getLogger("main").warning(
        "CostView TCA router 未加载（ExecutionView 不受影响）: %s", _costview_err
    )

try:
    from routers.execution_history import router as execution_history_router
    app.include_router(execution_history_router)
except Exception as _execution_history_err:  # noqa: BLE001
    import logging as _log
    _log.getLogger("main").warning(
        "Execution history router 未加载（ExecutionView 不受影响）: %s", _execution_history_err
    )

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
