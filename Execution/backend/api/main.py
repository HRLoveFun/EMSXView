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
import enum
import logging
import logging.handlers
import threading
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Literal, Union
from contextlib import asynccontextmanager
from pathlib import Path

try:
    import aiofiles
except ImportError:
    aiofiles = None  # Fallback for environments without aiofiles

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not installed, use system env vars

from fastapi import FastAPI, HTTPException, Depends, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator, ValidationInfo, ConfigDict
from jose import jwt
import uvicorn

from auth import AuthManager
from db import check_database_connection, dispose_engine, initialize_database
from service_provider import RepositoryProvider
from services.realtime_gateway import realtime_gw


# Bloomberg API
import blpapi
from blpapi import SessionOptions, Session, Service, Request, Message, Event

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
# Configuration
# ============================================================================

class Settings:
    """Application settings from environment variables"""
    # Bloomberg Configuration
    BLOOMBERG_HOST: str = os.getenv("BLOOMBERG_HOST", "localhost")
    BLOOMBERG_PORT: int = int(os.getenv("BLOOMBERG_PORT", "8194"))
    BLOOMBERG_TIMEOUT: int = int(os.getenv("BLOOMBERG_TIMEOUT", "60000"))  # 60s timeout for strategy info
    
    # API Configuration
    API_HOST: str = os.getenv("API_HOST", "0.0.0.0")
    API_PORT: int = int(os.getenv("API_PORT", "3000"))
    API_WORKERS: int = int(os.getenv("API_WORKERS", "1"))

    # Database Configuration
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql+asyncpg://emsx:emsx@postgres:5432/emsx")
    DATABASE_MIGRATION_URL: str = os.getenv("DATABASE_MIGRATION_URL", "postgresql+psycopg://emsx:emsx@postgres:5432/emsx")
    
    # Security - JWT_SECRET must be set in production

    JWT_SECRET: str = os.getenv("JWT_SECRET", "")
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = int(os.getenv("JWT_EXPIRE_MINUTES", "480"))  # 8 hours
    
    # CORS
    ALLOWED_ORIGINS: List[str] = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:80").split(",")
    
    # Trading
    ALLOWED_TRADERS: List[str] = os.getenv("ALLOWED_TRADERS", "").split(",")
    MAX_BATCH_SIZE: int = int(os.getenv("MAX_BATCH_SIZE", "100"))
    
    # Odd lot detection markets (comma-separated, e.g., "JP,US")
    # Uses Bloomberg PX_ROUND_LOT_SIZE to check if quantity is a multiple of round lot
    ODD_LOT_MARKETS: List[str] = [m.strip().upper() for m in os.getenv("ODD_LOT_MARKETS", "JP,US").split(",") if m.strip()]
    
    # Features
    ENABLE_REALTIME: bool = os.getenv("ENABLE_REALTIME", "true").lower() == "true"
    ENABLE_AUDIT_LOG: bool = os.getenv("ENABLE_AUDIT_LOG", "true").lower() == "true"

    # Trader identity — set to your EMSX trader name for ownership checks
    EMSX_TRADER_NAME: str = os.getenv("EMSX_TRADER_NAME", "")
    
    # Development mode - bypass authentication (DO NOT USE IN PRODUCTION)
    BYPASS_AUTH: bool = os.getenv("BYPASS_AUTH", "false").lower() == "true"

    # Persistence — when True, order/route projections are written through
    # to PostgreSQL and the DB read-path is used for warm-start on restart.
    # When False (default during rollout), the in-memory Bloomberg subscription
    # cache remains the sole data source.
    ENABLE_DB_PERSISTENCE: bool = os.getenv("ENABLE_DB_PERSISTENCE", "false").lower() == "true"

def _validate_settings():
    """Validate critical settings on startup."""
    # In production, JWT_SECRET must be set to a secure value
    if not settings.BYPASS_AUTH and not settings.JWT_SECRET:
        raise ValueError(
            "JWT_SECRET environment variable must be set. "
            "Generate a secure key with: openssl rand -hex 32"
        )
    
    # Warn if using default/weak JWT secret
    weak_secrets = ["your-secret-key", "change-in-production", "secret", "password"]
    if settings.JWT_SECRET and any(weak in settings.JWT_SECRET.lower() for weak in weak_secrets):
        logger.warning("JWT_SECRET appears to be using a weak/default value. Please set a secure random key.")
    
    logger.info(f"Settings validated: BYPASS_AUTH={settings.BYPASS_AUTH}, JWT_SECRET set={bool(settings.JWT_SECRET)}")
    logger.info(f"Odd lot detection enabled for markets: {settings.ODD_LOT_MARKETS}")
    logger.info(f"DB persistence: ENABLE_DB_PERSISTENCE={settings.ENABLE_DB_PERSISTENCE}")

settings = Settings()
_validate_settings()

# Repository provider — gates DB read/write behind ENABLE_DB_PERSISTENCE
repo_provider = RepositoryProvider(enabled=settings.ENABLE_DB_PERSISTENCE)

# ============================================================================
# Data Models (imported from models.py)
# ============================================================================

from models import (
    OrderSide, OrderStatus, OrderType, TimeInForce,
    Order, RouteStatus, Route, OrderFilters,
    BatchUpdateRequest, BatchUpdateResponse,
    CancelRouteRequest, ModifyRouteRequest, ModifyOrderRequest, RouteOrderRequest,
    ApiResponse, ConnectionStatus, LoginRequest,
    StrategyParameter, StrategyConfig, BrokerAlgorithmConfig, BrokerAlgorithmStorage,
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
# Authentication
# ============================================================================

security = HTTPBearer(auto_error=False)

def verify_token(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> dict:
    """Verify JWT token for API authentication.
    
    Requires valid Bearer token in Authorization header.
    Falls back to localhost bypass only in development mode (BYPASS_AUTH=true).
    """
    # Check if auth should be bypassed (development mode only)
    if settings.BYPASS_AUTH:
        logger.debug("Auth bypassed for development mode")
        return {"sub": "bloomberg_local", "name": "Bloomberg Terminal User", "role": "trader"}
    
    # Production: require valid token
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    # Use AuthManager for token verification
    return AuthManager.verify_token(credentials.credentials)

def audit_log(action: str, user: str, details: dict):
    """Log trading action for audit — with optional DB persistence."""
    if settings.ENABLE_AUDIT_LOG:
        logger.info(f"AUDIT: {action} | User: {user} | Details: {json.dumps(details)}")
    if repo_provider.is_active:
        asyncio.ensure_future(
            repo_provider.persist_audit_event(
                action=action,
                actor=user,
                endpoint=action,
                result="ok",
                payload_summary=json.dumps(details)[:500] if details else None,
            )
        )

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

    db_ready, db_message = await initialize_database()
    if db_ready:
        logger.info("Database schema bootstrap completed")
        repo_provider.mark_db_ready(True)
    else:
        logger.warning("Database schema bootstrap failed: %s", db_message)
        repo_provider.mark_db_ready(False)

    # Try to connect to Bloomberg
    connected = await bloomberg_service.connect()
    if not connected:
        logger.warning("Could not connect to Bloomberg on startup - will retry on first request")
    
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
# API Endpoints
# ============================================================================

@app.get("/", tags=["Health"])
async def root():
    """API root - service info"""
    return {
        "service": "EMSX Trading API",
        "version": "1.0.0",
        "status": "running",
        "bloomberg": bloomberg_service.get_status().model_dump()
    }

@app.get("/api/health", response_model=ApiResponse, tags=["Health"])
async def health_check():
    """Health check endpoint"""
    bb_status = bloomberg_service.get_status()
    db_connected, db_message = await check_database_connection()

    healthy = bb_status.status == "connected" and db_connected
    data = {
        "bloomberg": bb_status.model_dump(),
        "database": {
            "status": "connected" if db_connected else "disconnected",
            "message": db_message,
        },
    }

    return ApiResponse(
        success=healthy,
        data=data,
        message="Service is healthy" if healthy else f"bloomberg={bb_status.status}, database={'connected' if db_connected else 'disconnected'}"
    )



@app.post("/api/auth/login", response_model=ApiResponse, tags=["Auth"])
async def login(request: LoginRequest):
    """
    Authenticate user and return JWT access token

    - **username**: Trader username
    - **password**: Trader password
    """
    user = AuthManager.authenticate_user(request.username, request.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password"
        )
    token = AuthManager.create_access_token(user)
    return ApiResponse(
        success=True,
        data={"token": token, "user": user.to_dict()},
        message="Login successful"
    )


@app.get("/api/connection", response_model=ApiResponse, tags=["Connection"])
async def get_connection_status(user: dict = Depends(verify_token)):
    """Get Bloomberg connection status"""
    bb_status = bloomberg_service.get_status()
    return ApiResponse(
        success=True,
        data={"status": bb_status.status},
        message=f"Bloomberg is {bb_status.status}"
    )


@app.get("/api/orders/status", response_model=ApiResponse, tags=["Orders"])
async def get_orders_status(user: dict = Depends(verify_token)):
    """
    Get order subscription status
    
    Returns:
    - init_paint_done: Whether INIT_PAINT is complete
    - order_count: Number of orders in cache
    - subscription_failed: Whether subscription failed
    - is_connected: Connection status
    """
    status = {
        "init_paint_done": bloomberg_service._init_paint_done,
        "order_count": len(bloomberg_service._orders),
        "route_count": len(bloomberg_service._routes),
        "subscription_failed": bloomberg_service._subscription_failed,
        "is_connected": bloomberg_service.connected
    }
    return ApiResponse(success=True, data=status, message="Order subscription status")


@app.get("/api/orders", response_model=ApiResponse, tags=["Orders"])
async def get_orders(
    symbol: Optional[str] = None,
    side: Optional[OrderSide] = None,
    status: Optional[OrderStatus] = None,
    orderType: Optional[OrderType] = None,
    portfolio: Optional[str] = None,
    trader: Optional[str] = None,
    exchange: Optional[str] = None,
    currency: Optional[str] = None,
    oddLot: Optional[bool] = None,
    user: dict = Depends(verify_token)
):
    """
    Get orders from EMSX with optional filtering
    
    - **symbol**: Filter by ticker symbol (e.g., AAPL)
    - **side**: Filter by side (BUY or SELL)
    - **status**: Filter by order status
    - **portfolio**: Filter by portfolio name
    - **trader**: Filter by trader
    - **exchange**: Filter by exchange
    - **currency**: Filter by currency
    - **oddLot**: Filter by odd lot status (JP market only: True=quantity not multiple of PX_ROUND_LOT_SIZE, False=round lot)
    """
    filters = OrderFilters(
        symbol=symbol,
        side=side,
        status=status,
        orderType=orderType,
        portfolio=portfolio,
        trader=trader,
        exchange=exchange,
        currency=currency,
        oddLot=oddLot,
    )
    
    orders = await bloomberg_service.get_orders(filters)
    
    audit_log("GET_ORDERS", user.get("sub"), {"filters": filters.model_dump(exclude_none=True)})
    
    return ApiResponse(success=True, data=orders, message=f"Retrieved {len(orders)} orders")


@app.get("/api/routes", response_model=ApiResponse, tags=["Routes"])
async def get_routes(user: dict = Depends(verify_token)):
    """
    Get routes from EMSX subscription cache.
    Returns route-level execution data enriched with parent order info.
    """
    routes = await bloomberg_service.get_routes()
    return ApiResponse(success=True, data=routes, message=f"Retrieved {len(routes)} routes")


@app.post("/api/routes/cancel", response_model=ApiResponse, tags=["Routes"])
async def cancel_route(
    request: CancelRouteRequest,
    user: dict = Depends(verify_token)
):
    """
    Cancel a route via CancelRouteEx

    - **sequence**: Parent order EMSX_SEQUENCE
    - **routeId**: EMSX_ROUTE_ID to cancel
    """
    audit_log("CANCEL_ROUTE", user.get("sub"), {
        "sequence": request.sequence,
        "routeId": request.routeId
    })

    await bloomberg_service.cancel_route(request)

    return ApiResponse(
        success=True,
        message=f"Route {request.routeId} cancel request sent"
    )


@app.post("/api/routes/modify", response_model=ApiResponse, tags=["Routes"])
async def modify_route(
    request: ModifyRouteRequest,
    user: dict = Depends(verify_token)
):
    """
    Modify a route via ModifyRouteEx

    - **sequence**: Parent order EMSX_SEQUENCE
    - **routeId**: EMSX_ROUTE_ID to modify
    - **amount**: New quantity (optional)
    - **orderType**: MKT, LMT, STP, STOP_LIMIT (optional)
    - **limitPrice**: Limit price (optional, 0=ignore, -99999=reset)
    - **stopPrice**: Stop price (optional, -1=clear)
    - **tif**: DAY, GTC, IOC, FOK, GTD (optional)
    - **broker**: New broker (optional)
    - **exchangeDestination**: Exchange destination (optional)
    - **notes**: Route notes (optional)
    - **strategyParams**: Strategy parameters (optional)
    """
    audit_log("MODIFY_ROUTE", user.get("sub"), {
        "sequence": request.sequence,
        "routeId": request.routeId,
        "fields": request.model_dump(exclude_none=True, exclude={'sequence', 'routeId'})
    })

    await bloomberg_service.modify_route(request)

    return ApiResponse(
        success=True,
        message=f"Route {request.routeId} modify request sent"
    )


@app.get("/api/trader-info", response_model=ApiResponse, tags=["Trader"])
async def get_trader_info(user: dict = Depends(verify_token)):
    """
    Get the terminal's trader identity (auto-detected from EMSX_TRADER field).
    """
    name = bloomberg_service.get_terminal_trader_name()
    return ApiResponse(
        success=True,
        data={"traderName": name},
        message=f"Terminal trader: {name}"
    )


@app.get("/api/broker-strategies", response_model=ApiResponse, tags=["Broker"])
async def get_broker_strategies(
    broker: str,
    assetClass: str = "EQTY",
    user: dict = Depends(verify_token),
):
    """
    Get available strategies for a broker via GetBrokerStrategiesWithAssetClass.

    - **broker**: Broker code (e.g., BMTB)
    - **assetClass**: EQTY, OPT, FUT, or MULTILEG_OPT (default: EQTY)
    """
    strategies = await bloomberg_service.get_broker_strategies(broker, assetClass)
    return ApiResponse(
        success=True,
        data={"broker": broker, "assetClass": assetClass, "strategies": strategies},
        message=f"Found {len(strategies)} strategies for {broker}"
    )


@app.get("/api/broker-strategy-info", response_model=ApiResponse, tags=["Broker"])
async def get_broker_strategy_info(
    broker: str,
    strategy: str,
    assetClass: str = "EQTY",
    user: dict = Depends(verify_token),
):
    """
    Get strategy parameter details via GetBrokerStrategyInfoWithAssetClass.

    - **broker**: Broker code (e.g., BMTB)
    - **strategy**: Strategy name (e.g., VWAP)
    - **assetClass**: EQTY, OPT, FUT, or MULTILEG_OPT (default: EQTY)
    """
    fields = await bloomberg_service.get_broker_strategy_info(broker, strategy, assetClass)
    return ApiResponse(
        success=True,
        data={"broker": broker, "strategy": strategy, "assetClass": assetClass, "fields": fields},
        message=f"Found {len(fields)} parameters for {broker}/{strategy}"
    )


@app.get("/api/brokers", response_model=ApiResponse, tags=["Broker"])
async def get_brokers(
    assetClass: str = "EQTY",
    user: dict = Depends(verify_token),
):
    """
    Get available brokers for an asset class via GetBrokersWithAssetClass.

    - **assetClass**: EQTY, OPT, FUT, or MULTILEG_OPT (default: EQTY)
    """
    brokers = await bloomberg_service.get_brokers(assetClass)
    return ApiResponse(
        success=True,
        data={"brokers": brokers, "assetClass": assetClass},
        message=f"Found {len(brokers)} brokers"
    )


@app.get("/api/broker-algorithms", response_model=ApiResponse, tags=["Broker"])
async def get_stored_broker_algorithms(
    user: dict = Depends(verify_token),
):
    """
    Get stored broker algorithm configuration.
    Returns cached data with freshness information.
    """
    configs = await broker_storage.get_configs()
    last_updated = await broker_storage.get_last_updated()
    needs_refresh = await broker_storage.needs_refresh()
    
    return ApiResponse(
        success=True,
        data={
            "configs": [c.model_dump() for c in configs],
            "lastUpdated": last_updated.isoformat() if last_updated else None,
            "needsRefresh": needs_refresh,
            "count": len(configs),
        },
        message=f"Retrieved {len(configs)} broker algorithm configurations"
    )


@app.post("/api/broker-algorithms/refresh", response_model=ApiResponse, tags=["Broker"])
async def refresh_broker_algorithms(
    user: dict = Depends(verify_token),
):
    """
    Refresh broker algorithm configuration from Bloomberg API.
    Fetches all brokers, strategies, and parameters and stores them.
    """
    audit_log("REFRESH_BROKER_ALGORITHMS", user.get("sub"), {})
    
    try:
        configs: List[BrokerAlgorithmConfig] = []
        
        # 1. Get all brokers
        brokers = await bloomberg_service.get_brokers("EQTY")
        logger.info(f"[RefreshBrokerAlgorithms] Found {len(brokers)} brokers")
        
        # Exchange mapping — Bloomberg broker IDs use "EQ-" prefix
        exchange_map = {
            'EQ-GS': 'US', 'EQ-MS': 'US', 'EQ-JPM': 'US', 'EQ-BARCLAY': 'LN',
            'EQ-ML': 'US', 'EQ-CITI': 'US', 'EQ-UBS': 'US',
            'EQ-HSBC': 'LN', 'EQ-BNP': 'FP',
            'EQ-NOMURA': 'JP', 'EQ-DAIWA': 'JP', 'EQ-MIZUHO': 'JP',
            'EQ-CLSA': 'HK', 'EQ-MACQ': 'AU',
            'EQ-INSTNET': 'US', 'EQ-SEB': 'SS', 'EQ-TD': 'CN',
            'EQ-BHP': 'AU',
        }
        
        # 2. For each broker, get strategies
        for broker in brokers:
            try:
                strategies = await bloomberg_service.get_broker_strategies(broker, "EQTY")
                if not strategies:
                    continue
                
                strategy_configs: List[StrategyConfig] = []
                
                # 3. For each strategy, get parameters
                for strategy_name in strategies:
                    try:
                        fields = await bloomberg_service.get_broker_strategy_info(broker, strategy_name, "EQTY")
                        strategy_configs.append(StrategyConfig(
                            name=strategy_name,
                            parameters=[
                                StrategyParameter(
                                    fieldName=f.get("fieldName", ""),
                                    stringValue=f.get("stringValue", ""),
                                    disable=f.get("disable", "N"),
                                    dataType="string",
                                    description=f"{f.get('fieldName', '')} parameter"
                                )
                                for f in fields
                            ] if fields else []
                        ))
                    except Exception as e:
                        # Still include the strategy even if parameter info fails
                        strategy_configs.append(StrategyConfig(
                            name=strategy_name,
                            parameters=[]
                        ))
                        logger.warning(f"[RefreshBrokerAlgorithms] Failed to get info for {broker}/{strategy_name}: {e}")
                
                configs.append(BrokerAlgorithmConfig(
                    broker=broker,
                    exchange=exchange_map.get(broker, 'OTHER'),
                    strategies=strategy_configs
                ))
                    
            except Exception as e:
                logger.warning(f"[RefreshBrokerAlgorithms] Failed to process broker {broker}: {e}")
        
        # 4. Save to storage
        success = await broker_storage.save(configs)
        
        if success:
            return ApiResponse(
                success=True,
                data={
                    "configs": [c.model_dump() for c in configs],
                    "count": len(configs),
                    "lastUpdated": datetime.now().isoformat(),
                },
                message=f"Successfully refreshed {len(configs)} broker algorithm configurations"
            )
        else:
            raise HTTPException(500, "Failed to save broker algorithm configuration")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[RefreshBrokerAlgorithms] Failed: {e}")
        raise HTTPException(500, f"Failed to refresh broker algorithms: {str(e)}")


@app.get("/api/broker-algorithms/status", response_model=ApiResponse, tags=["Broker"])
async def get_broker_algorithms_status(
    user: dict = Depends(verify_token),
):
    """
    Get status of broker algorithm configuration storage.
    Returns freshness information without loading full data.
    """
    last_updated = await broker_storage.get_last_updated()
    needs_refresh = await broker_storage.needs_refresh()
    
    return ApiResponse(
        success=True,
        data={
            "lastUpdated": last_updated.isoformat() if last_updated else None,
            "needsRefresh": needs_refresh,
            "hasData": last_updated is not None,
        },
        message="Broker algorithm status retrieved"
    )


@app.post("/api/orders/modify", response_model=ApiResponse, tags=["Orders"])
async def modify_order(
    request: ModifyOrderRequest,
    user: dict = Depends(verify_token)
):
    """
    Modify a single order via ModifyOrderEx.

    - **orderId**: Order ID (EMSX_SEQUENCE)
    - **orderType**: LIMIT, MARKET, STOP, STOP_LIMIT (optional)
    - **price**: Limit price (optional)
    - **quantity**: New quantity (optional)
    - **timeInForce**: DAY, GTC, IOC, FOK (optional)
    - **stopPrice**: Stop price (optional)
    """
    audit_log("MODIFY_ORDER", user.get("sub"), {
        "orderId": request.orderId,
        "orderType": request.orderType,
        "price": request.price,
        "quantity": request.quantity,
        "timeInForce": request.timeInForce,
        "stopPrice": request.stopPrice,
    })

    # Map order type to EMSX format
    field_updates = {}
    if request.orderType:
        emsx_order_type = {"LIMIT": "LMT", "MARKET": "MKT", "STOP": "STP", "STOP_LIMIT": "STP_LMT"}.get(request.orderType, request.orderType)
        field_updates["orderType"] = emsx_order_type
    if request.price is not None:
        field_updates["price"] = request.price
    if request.quantity is not None:
        field_updates["quantity"] = request.quantity
    if request.timeInForce:
        field_updates["timeInForce"] = request.timeInForce
    if request.stopPrice is not None:
        field_updates["stopPrice"] = request.stopPrice

    # Apply modifications one by one
    for field, value in field_updates.items():
        await bloomberg_service.modify_order(request.orderId, field, value)

    return ApiResponse(
        success=True,
        message=f"Order {request.orderId} modified successfully"
    )


@app.post("/api/orders/route", response_model=ApiResponse, tags=["Orders"])
async def route_order(
    request: RouteOrderRequest,
    user: dict = Depends(verify_token)
):
    """
    Route an order to a broker via RouteEx.
    Creates a child route from a parent order for execution.

    - **orderId**: Parent order ID (EMSX_SEQUENCE)
    - **broker**: Broker code for routing (required)
    - **quantity**: Quantity to route (required)
    - **orderType**: LIMIT, MARKET, STOP, STOP_LIMIT (required)
    - **price**: Limit price (required for LIMIT orders)
    - **stopPrice**: Stop price (required for STOP orders)
    - **timeInForce**: DAY, GTC, IOC, FOK (required)
    - **exchangeDestination**: Exchange destination (optional)
    - **notes**: Route notes (optional)
    """
    audit_log("ROUTE_ORDER", user.get("sub"), {
        "orderId": request.orderId,
        "broker": request.broker,
        "quantity": request.quantity,
        "orderType": request.orderType,
    })

    result = await bloomberg_service.route_order(request)

    return ApiResponse(
        success=True,
        data=result,
        message=f"Route created for order {request.orderId} to broker {request.broker}"
    )


@app.post("/api/orders/batch-update", response_model=ApiResponse, tags=["Orders"])
async def batch_update(
    request: BatchUpdateRequest,
    user: dict = Depends(verify_token)
):
    """
    Batch update multiple orders

    - **orderIds**: List of order IDs to update
    - **field**: Field to modify (price, quantity, timeInForce, status)
    - **value**: New value for the field
    """
    audit_log("BATCH_UPDATE", user.get("sub"), {
        "orderIds": request.orderIds,
        "field": request.field,
        "value": str(request.value)
    })

    result = await bloomberg_service.batch_update(request)

    return ApiResponse(
        success=result.success,
        data=result.model_dump(),
        message=result.message
    )


@app.get("/api/orders/refresh", response_model=ApiResponse, tags=["Orders"])
async def refresh_orders(user: dict = Depends(verify_token)):
    """Force-refresh order list from Bloomberg"""
    orders = await bloomberg_service.get_orders()
    audit_log("REFRESH_ORDERS", user.get("sub"), {})
    return ApiResponse(success=True, data=orders, message=f"Retrieved {len(orders)} orders")

@app.post("/api/orders/{order_id}/cancel", response_model=ApiResponse, tags=["Orders"])
async def cancel_order(order_id: str, user: dict = Depends(verify_token)):
    """Cancel a single order"""
    audit_log("CANCEL_ORDER", user.get("sub"), {"orderId": order_id})
    
    await bloomberg_service.cancel_order(order_id)
    
    return ApiResponse(success=True, message=f"Order {order_id} cancelled successfully")

@app.post("/api/connection/reconnect", response_model=ApiResponse, tags=["Connection"])
async def reconnect_bloomberg(user: dict = Depends(verify_token)):
    """Force reconnection to Bloomberg"""
    bloomberg_service.disconnect()
    connected = await bloomberg_service.connect()
    
    if connected:
        return ApiResponse(success=True, message="Reconnected to Bloomberg")
    else:
        raise HTTPException(503, "Failed to reconnect to Bloomberg")

@app.get("/api/debug/round-lot-sizes", response_model=ApiResponse, tags=["Debug"])
async def get_round_lot_sizes(user: dict = Depends(verify_token)):
    """Get cached round lot sizes for debugging odd lot detection"""
    round_lot_sizes = dict(bloomberg_service._round_lot_sizes)
    subscribed_tickers = list(bloomberg_service._mktdata_subscribed_tickers)
    active_tickers = list(bloomberg_service._mktdata_active_tickers)
    failed_tickers = list(bloomberg_service._mktdata_failed_tickers)
    
    # Check specific symbols
    debug_symbols = ["COST US Equity", "DE US Equity", "GEV US Equity", "RS US Equity", 
                     "ZS US Equity", "ROP US Equity", "ORCL US Equity", "MSTR US Equity",
                     "INTU US Equity", "HUBS US Equity", "ADBE US Equity", "MPWR US Equity",
                     "VRSN US Equity", "IT US Equity", "IBM US Equity", "ZBRA US Equity",
                     "TDY US Equity", "MSI US Equity", "CHTR US Equity", "SPY US Equity",
                     "AVGO US Equity", "PH US Equity", "ETN US Equity", "V US Equity"]
    
    debug_info = {}
    for sym in debug_symbols:
        debug_info[sym] = {
            "round_lot": round_lot_sizes.get(sym),
            "subscribed": sym in subscribed_tickers,
            "active": sym in active_tickers,
            "failed": sym in failed_tickers
        }
    
    return ApiResponse(success=True, data={
        "round_lot_sizes": round_lot_sizes,
        "debug_symbols": debug_info,
        "config": {
            "odd_lot_markets": settings.ODD_LOT_MARKETS
        },
        "stats": {
            "total_cached": len(round_lot_sizes),
            "subscribed": len(subscribed_tickers),
            "active": len(active_tickers),
            "failed": len(failed_tickers)
        }
    }, message=f"Cached {len(round_lot_sizes)} round lot sizes for markets {settings.ODD_LOT_MARKETS}")


@app.post("/api/debug/query-round-lot", response_model=ApiResponse, tags=["Debug"])
async def query_round_lot(ticker: str, user: dict = Depends(verify_token)):
    """Manually query PX_ROUND_LOT_SIZE for a specific ticker using BDP-style request"""
    try:
        import blpapi
        from datetime import datetime
        
        sess = bloomberg_service._mktdata_session
        if not sess:
            return ApiResponse(success=False, error="Mktdata session not available")
        
        svc = sess.getService("//blp/refdata")
        req = svc.createRequest("ReferenceDataRequest")
        securities = req.getElement("securities")
        securities.appendValue(ticker)
        fields = req.getElement("fields")
        fields.appendValue("PX_ROUND_LOT_SIZE")
        
        logger.info(f"[DEBUG_BDP] Querying PX_ROUND_LOT_SIZE for {ticker}")
        sess.sendRequest(req)
        
        # Wait for response (blocking for simplicity in debug endpoint)
        timeout_ms = 5000
        deadline = datetime.now().timestamp() * 1000 + timeout_ms
        result = None
        
        while datetime.now().timestamp() * 1000 < deadline:
            event = sess.nextEvent(1000)
            if event.eventType() in (blpapi.Event.PARTIAL_RESPONSE, blpapi.Event.RESPONSE):
                for msg in event:
                    if msg.hasElement("securityData"):
                        sd = msg.getElement("securityData")
                        for i in range(sd.numValues()):
                            entry = sd.getValueAsElement(i)
                            sec = entry.getElementAsString("security")
                            if entry.hasElement("fieldData"):
                                fd = entry.getElement("fieldData")
                                if fd.hasElement("PX_ROUND_LOT_SIZE"):
                                    val = fd.getElementAsInteger("PX_ROUND_LOT_SIZE")
                                    bloomberg_service._round_lot_sizes[sec] = val
                                    result = val
                                    logger.info(f"[DEBUG_BDP] {sec}: PX_ROUND_LOT_SIZE = {val}")
                                else:
                                    result = "Field not available"
                            else:
                                result = "No field data"
                if event.eventType() == blpapi.Event.RESPONSE:
                    break
        
        return ApiResponse(success=True, data={
            "ticker": ticker,
            "round_lot_size": result,
            "cached_value": bloomberg_service._round_lot_sizes.get(ticker)
        })
    except Exception as e:
        logger.error(f"[DEBUG_BDP] Error querying {ticker}: {e}")
        return ApiResponse(success=False, error=str(e))


# ============================================================================
# WebSocket for Real-time Updates
# ============================================================================

class ConnectionManager:
    """Legacy WebSocket connection manager — kept for backward compat; delegates to realtime_gw."""
    @property
    def active_connections(self) -> list:
        return realtime_gw._connections

    async def connect(self, websocket: WebSocket):
        await realtime_gw.connect(websocket)

    def disconnect(self, websocket: WebSocket):
        realtime_gw.disconnect(websocket)

    async def broadcast(self, message: dict):
        """Broadcast message to all connected clients via gateway."""
        import json as _json
        payload = _json.dumps(message)
        dead = []
        for conn in realtime_gw._connections:
            try:
                await conn.send_text(payload)
            except Exception:
                dead.append(conn)
        for conn in dead:
            realtime_gw.disconnect(conn)

manager = ConnectionManager()

@app.websocket("/ws/orders")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time order/route updates.
    
    Supports:
    - ping/pong keep-alive
    - cursor-based backfill: send {"action": "replay", "cursor": N}
    - stats: send {"action": "stats"}
    """
    await realtime_gw.connect(websocket)
    try:
        # Send current cursor so client knows where it is
        await websocket.send_json({
            "type": "connected",
            "cursor": realtime_gw.latest_cursor,
            "timestamp": datetime.now().isoformat(),
        })
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            action = message.get("action", "")
            
            if action == "ping":
                await websocket.send_json({"type": "pong", "timestamp": datetime.now().isoformat()})
            elif action == "replay":
                since = int(message.get("cursor", 0))
                count = await realtime_gw.replay_since(websocket, since)
                await websocket.send_json({"type": "replay_done", "replayed": count, "cursor": realtime_gw.latest_cursor})
            elif action == "stats":
                await websocket.send_json({"type": "stats", **realtime_gw.stats()})
    except WebSocketDisconnect:
        realtime_gw.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        realtime_gw.disconnect(websocket)

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
