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

settings = Settings()
_validate_settings()

# ============================================================================
# Data Models
# ============================================================================

class OrderSide(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"

class OrderStatus(str, enum.Enum):
    NEW = "NEW"
    ASSIGN = "ASSIGN"
    WORKING = "WORKING"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    PENDING_CANCEL = "PENDING_CANCEL"
    REJECTED = "REJECTED"
    COMPLETED = "COMPLETED"
    QUEUED = "QUEUED"
    SUSPENDED = "SUSPENDED"

class OrderType(str, enum.Enum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"

class TimeInForce(str, enum.Enum):
    DAY = "DAY"
    GTC = "GTC"  # Good Till Cancelled
    IOC = "IOC"  # Immediate or Cancel
    FOK = "FOK"  # Fill or Kill
    GTX = "GTX"  # Good Till Crossing
    GTD = "GTD"  # Good Till Date

class Order(BaseModel):
    """Order model matching frontend expectations"""
    model_config = ConfigDict(use_enum_values=True)

    id: str
    symbol: str
    side: OrderSide
    status: OrderStatus
    orderType: OrderType
    quantity: int
    filledQuantity: int = 0
    remainingQuantity: int
    price: Optional[float] = None
    stopPrice: Optional[float] = None
    timeInForce: TimeInForce
    account: str
    portfolio: str = ""
    trader: str
    createdAt: str
    updatedAt: str
    notes: Optional[str] = None
    avgPrice: Optional[float] = None
    currency: str = ""
    exchange: str = ""  # Changed from Optional[str] = None to ensure consistent string type
    customNote1: str = ""
    customNote2: str = ""
    customNote3: str = ""
    customNote4: str = ""
    customNote5: str = ""
    traderNotes: str = ""
    execInstruction: str = ""
    percentRemain: Optional[float] = None
    percentFilled: float = 0.0
    pctChange: Optional[float] = None
    strategyType: str = ""
    strategyPartRate: Optional[float] = None
    strategyStyle: str = ""
    strategyStartTime: str = ""
    strategyEndTime: str = ""
    broker: str = ""
    traderUuid: int = 0
    adv5d: Optional[float] = None
    dollarValueUsd: Optional[float] = None
    fxRate: Optional[float] = None
    arrivalPrice: Optional[float] = None
    lastPrice: Optional[float] = None
    dayAvgPrice: Optional[float] = None
    mktVwap: Optional[float] = None
    isOddLot: Optional[bool] = None  # True if JP market and quantity not multiple of round lot size


class RouteStatus(str, enum.Enum):
    SENT = "SENT"
    WORKING = "WORKING"
    PARTFILLED = "PARTFILLED"
    FILLED = "FILLED"
    CANCEL = "CANCEL"
    CXLREQ = "CXLREQ"
    CXLREJ = "CXLREJ"
    CXLREP = "CXLREP"
    CXLRPRQ = "CXLRPRQ"
    CXLRPRJ = "CXLRPRJ"
    REJECTED = "REJECTED"
    DONE = "DONE"
    QUEUED = "QUEUED"
    HOLD = "HOLD"
    BUST = "BUST"
    CORRECTED = "CORRECTED"
    REPPEN = "REPPEN"
    ROUTE_ERR = "ROUTE-ERR"
    OMS_PEND = "OMS-PEND"
    A_SENT = "A-SENT"
    ALLOCATED = "ALLOCATED"
    OA_SENT = "OA-SENT"


class Route(BaseModel):
    """Route model for route-level execution data"""
    model_config = ConfigDict(use_enum_values=True)

    # Key identifiers
    routeId: int  # EMSX_ROUTE_ID
    sequence: int  # EMSX_SEQUENCE (parent order)
    # Composite key for display
    id: str  # "{sequence}.{routeId}"

    # Execution
    status: str
    broker: str = ""
    amount: int = 0
    filled: int = 0
    working: int = 0
    remainBalance: int = 0
    avgPrice: Optional[float] = None
    limitPrice: Optional[float] = None
    stopPrice: Optional[float] = None
    lastPrice: Optional[float] = None
    lastShares: Optional[int] = None
    dayAvgPrice: Optional[float] = None
    dayFill: int = 0
    bseAvgPrice: Optional[float] = None
    bseFilled: int = 0
    nseAvgPrice: Optional[float] = None
    nseFilled: int = 0

    # Order info
    orderType: str = ""
    tif: str = ""
    handInstruction: str = ""
    execInstruction: str = ""
    notes: str = ""

    # Strategy
    strategyType: str = ""
    strategyStyle: str = ""
    strategyPartRate1: Optional[float] = None
    strategyPartRate2: Optional[float] = None
    strategyStartTime: str = ""
    strategyEndTime: str = ""

    # Routing details
    exchangeDestination: str = ""
    executeBroker: str = ""
    isManualRoute: int = 0
    routeRefId: str = ""
    currencyPair: str = ""
    urgencyLevel: str = ""

    # Timestamps
    routeCreateDate: str = ""
    routeCreateTime: str = ""
    lastFillDate: str = ""
    lastFillTime: str = ""
    timeStamp: str = ""
    routeLastUpdateTime: str = ""

    # Fill details
    fillId: int = 0
    percentRemain: Optional[float] = None

    # Reason / rejection
    reasonCode: str = ""
    reasonDesc: str = ""
    brokerStatus: str = ""

    # Settle
    settleAmount: Optional[float] = None
    settleDate: str = ""

    # Commission
    commRate: Optional[float] = None
    brokerComm: Optional[float] = None
    userCommRate: Optional[float] = None
    userCommAmount: Optional[float] = None
    userFees: Optional[float] = None
    miscFees: Optional[float] = None
    userNetMoney: Optional[float] = None
    principal: Optional[float] = None
    routePrice: Optional[float] = None

    # Enriched fields from parent order (stored here for persistence)
    ticker: str = ""  # Parent order's symbol (EMSX_TICKER)
    side: str = ""    # Parent order's side
    portfolio: str = ""  # Parent order's portfolio
    trader: str = ""     # Parent order's trader
    traderUuid: int = 0  # Parent order's trader UUID
    currency: str = ""   # Parent order's currency
    exchange: str = ""   # Parent order's exchange (EMSX_EXCHANGE)


class OrderFilters(BaseModel):
    """Order filter parameters"""
    symbol: Optional[str] = None
    side: Optional[OrderSide] = None
    status: Optional[OrderStatus] = None
    orderType: Optional[OrderType] = None
    portfolio: Optional[str] = None
    trader: Optional[str] = None
    exchange: Optional[str] = None
    currency: Optional[str] = None
    oddLot: Optional[bool] = None  # Filter for odd lot orders (JP market only: quantity not multiple of PX_ROUND_LOT_SIZE)

class BatchUpdateRequest(BaseModel):
    """Batch update request"""
    orderIds: List[str] = Field(..., min_length=1)
    field: Literal["price", "quantity", "timeInForce", "status"]
    value: Union[str, float]

    @field_validator('orderIds')
    @classmethod
    def validate_order_count(cls, v: List[str]) -> List[str]:
        if len(v) > settings.MAX_BATCH_SIZE:
            raise ValueError(f"Batch size {len(v)} exceeds maximum of {settings.MAX_BATCH_SIZE}")
        return v

    @field_validator('value', mode='before')
    @classmethod
    def validate_value(cls, v: Any, info: ValidationInfo) -> Any:
        field_name = (info.data or {}).get('field')
        if field_name in ['price', 'quantity']:
            try:
                float_v = float(v)
                if float_v <= 0:
                    raise ValueError(f"{field_name} must be positive")
                return float_v
            except (ValueError, TypeError):
                raise ValueError(f"Invalid numeric value for {field_name}")
        return v

class BatchUpdateResponse(BaseModel):
    """Batch update response"""
    success: bool
    updatedCount: int
    failedOrders: Optional[List[Dict[str, str]]] = None
    message: str

class CancelRouteRequest(BaseModel):
    """Cancel route request"""
    sequence: int = Field(..., description="EMSX_SEQUENCE (parent order ID)")
    routeId: int = Field(..., description="EMSX_ROUTE_ID")

class ModifyRouteRequest(BaseModel):
    """Modify route request"""
    sequence: int = Field(..., description="EMSX_SEQUENCE (parent order ID)")
    routeId: int = Field(..., description="EMSX_ROUTE_ID")
    amount: Optional[int] = Field(None, description="New quantity")
    orderType: Optional[str] = Field(None, description="MKT, LMT, STP, STOP_LIMIT")
    limitPrice: Optional[float] = Field(None, description="Limit price (0=ignore, -99999=reset)")
    stopPrice: Optional[float] = Field(None, description="Stop price (-1=clear)")
    tif: Optional[str] = Field(None, description="DAY, GTC, IOC, FOK, GTD")
    broker: Optional[str] = Field(None, description="New broker")
    exchangeDestination: Optional[str] = Field(None, description="Exchange destination")
    notes: Optional[str] = Field(None, description="Route notes")
    strategyParams: Optional[Dict[str, Any]] = Field(None, description="Strategy parameters")

class ModifyOrderRequest(BaseModel):
    """Modify order request"""
    orderId: str = Field(..., description="EMSX_SEQUENCE (order ID)")
    orderType: Optional[str] = Field(None, description="LIMIT, MARKET, STOP, STOP_LIMIT")
    price: Optional[float] = Field(None, description="Limit price")
    quantity: Optional[int] = Field(None, description="New quantity")
    timeInForce: Optional[str] = Field(None, description="DAY, GTC, IOC, FOK")
    stopPrice: Optional[float] = Field(None, description="Stop price")

class RouteOrderRequest(BaseModel):
    """Route order request - creates a child route from a parent order"""
    orderId: str = Field(..., description="EMSX_SEQUENCE (parent order ID)")
    broker: str = Field(..., description="Broker code for routing")
    quantity: int = Field(..., description="Quantity to route", ge=1)
    orderType: str = Field(..., description="LIMIT, MARKET, STOP, STOP_LIMIT")
    price: Optional[float] = Field(None, description="Limit price")
    stopPrice: Optional[float] = Field(None, description="Stop price")
    timeInForce: str = Field(..., description="DAY, GTC, IOC, FOK")
    exchangeDestination: Optional[str] = Field(None, description="Exchange destination")
    notes: Optional[str] = Field(None, description="Route notes")

class ApiResponse(BaseModel):
    """Standard API response wrapper"""
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None
    message: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())

class ConnectionStatus(BaseModel):
    """Bloomberg connection status"""
    status: Literal["connected", "disconnected", "connecting", "error"]
    message: Optional[str] = None
    lastConnected: Optional[str] = None
    uptime: Optional[int] = None  # seconds


class LoginRequest(BaseModel):
    """Login credentials"""
    username: str
    password: str

# ============================================================================
# Broker Algorithm Configuration Models
# ============================================================================

class StrategyParameter(BaseModel):
    """Strategy parameter configuration"""
    fieldName: str
    stringValue: str
    disable: str
    dataType: str = "string"
    description: str = ""

class StrategyConfig(BaseModel):
    """Strategy configuration for a broker"""
    name: str
    parameters: List[StrategyParameter]

class BrokerAlgorithmConfig(BaseModel):
    """Broker algorithm configuration"""
    broker: str
    exchange: str
    strategies: List[StrategyConfig]

class BrokerAlgorithmStorage(BaseModel):
    """Storage wrapper for broker algorithm data"""
    version: str = "1.0"
    lastUpdated: str = Field(default_factory=lambda: datetime.now().isoformat())
    configs: List[BrokerAlgorithmConfig]

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
# Bloomberg EMSX Service
# ============================================================================

class BloombergEMSXService:
    """
    Bloomberg EMSX API Service — Subscription Mode
    
    Uses the EMSX subscription service (per Bloomberg docs) to monitor live orders.
    Subscribe to //blp/emapisvc_beta/order (or //blp/emapisvc/order) and maintain
    an in-memory order cache updated by INIT_PAINT and live update events.
    
    Event statuses:
      EVENT_STATUS = 4   INIT_PAINT   — initial snapshot of all current orders
      EVENT_STATUS = 6   NEW_ORDER    — new order added to blotter
      EVENT_STATUS = 7   UPD_ORDER    — existing order updated
      EVENT_STATUS = 8   DELETION     — order deleted
      EVENT_STATUS = 11  INIT_PAINT_END — end of initial snapshot
    """

    EMSX_SERVICES = ["//blp/emapisvc", "//blp/emapisvc_beta"]

    # Fields to subscribe to
    ORDER_FIELDS = [
        "API_SEQ_NUM",
        "EMSX_SEQUENCE",
        "EMSX_TICKER",
        "EMSX_SIDE",
        "EMSX_AMOUNT",
        "EMSX_FILLED",
        "EMSX_STATUS",
        "EMSX_ORDER_TYPE",
        "EMSX_LIMIT_PRICE",
        "EMSX_STOP_PRICE",
        "EMSX_AVG_PRICE",
        "EMSX_TIF",
        "EMSX_ACCOUNT",
        "EMSX_TRADER",
        "EMSX_NOTES",
        "EMSX_DATE",
        "EMSX_TIME_STAMP",
        "EMSX_EXCHANGE",
        "EMSX_CURRENCY_PAIR",
        "EMSX_ISIN",
        "EMSX_SEC_NAME",
        "EMSX_WORKING",
        "EMSX_PORT_NAME",
        "EMSX_CUSTOM_NOTE1",
        "EMSX_CUSTOM_NOTE2",
        "EMSX_CUSTOM_NOTE3",
        "EMSX_CUSTOM_NOTE4",
        "EMSX_CUSTOM_NOTE5",
        "EMSX_TRADER_NOTES",
        "EMSX_EXEC_INSTRUCTION",
        "EMSX_PERCENT_REMAIN",
        "EMSX_HAND_INSTRUCTION",
        "EMSX_STRATEGY_TYPE",
        "EMSX_STRATEGY_PART_RATE1",
        "EMSX_STRATEGY_STYLE",
        "EMSX_STRATEGY_START_TIME",
        "EMSX_STRATEGY_END_TIME",
        "EMSX_PM_UUID",
        "EMSX_TRAD_UUID",
        "EMSX_BROKER",
        "EMSX_DAY_AVG_PRICE",
        "EMSX_ARRIVAL_PRICE",
    ]

    # Route subscription fields (per EMSX API Developer's Guide)
    ROUTE_FIELDS = [
        "API_SEQ_NUM",
        "EMSX_SEQUENCE",
        "EMSX_ROUTE_ID",
        "EMSX_STATUS",
        "EMSX_BROKER",
        "EMSX_AMOUNT",
        "EMSX_FILLED",
        "EMSX_WORKING",
        "EMSX_AVG_PRICE",
        "EMSX_LIMIT_PRICE",
        "EMSX_STOP_PRICE",
        "EMSX_LAST_PRICE",
        "EMSX_LAST_SHARES",
        "EMSX_LAST_FILL_DATE",
        "EMSX_LAST_FILL_TIME",
        "EMSX_DAY_AVG_PRICE",
        "EMSX_DAY_FILL",
        "EMSX_ORDER_TYPE",
        "EMSX_TIF",
        "EMSX_HAND_INSTRUCTION",
        "EMSX_EXEC_INSTRUCTION",
        "EMSX_NOTES",
        "EMSX_STRATEGY_TYPE",
        "EMSX_STRATEGY_STYLE",
        "EMSX_STRATEGY_PART_RATE1",
        "EMSX_STRATEGY_PART_RATE2",
        "EMSX_STRATEGY_START_TIME",
        "EMSX_STRATEGY_END_TIME",
        "EMSX_EXCHANGE_DESTINATION",
        "EMSX_EXECUTE_BROKER",
        "EMSX_IS_MANUAL_ROUTE",
        "EMSX_ROUTE_REF_ID",
        "EMSX_CURRENCY_PAIR",
        "EMSX_URGENCY_LEVEL",
        "EMSX_ROUTE_CREATE_DATE",
        "EMSX_ROUTE_CREATE_TIME",
        "EMSX_TIME_STAMP",
        "EMSX_ROUTE_LAST_UPDATE_TIME",
        "EMSX_FILL_ID",
        "EMSX_PERCENT_REMAIN",
        "EMSX_REMAIN_BALANCE",
        "EMSX_REASON_CODE",
        "EMSX_REASON_DESC",
        "EMSX_BROKER_STATUS",
        "EMSX_SETTLE_AMOUNT",
        "EMSX_SETTLE_DATE",
        "EMSX_COMM_RATE",
        "EMSX_BROKER_COMM",
        "EMSX_USER_COMM_RATE",
        "EMSX_USER_COMM_AMOUNT",
        "EMSX_USER_FEES",
        "EMSX_MISC_FEES",
        "EMSX_USER_NET_MONEY",
        "EMSX_PRINCIPAL",
        "EMSX_ROUTE_PRICE",
        "EMSX_BSE_AVG_PRICE",
        "EMSX_BSE_FILLED",
        "EMSX_NSE_AVG_PRICE",
        "EMSX_NSE_FILLED",
    ]

    STATUS_MAP = {
        "NEW": "NEW", "WORKING": "WORKING",
        "PARTFILLED": "PARTIAL", "PARTFILL": "PARTIAL",
        "FILLED": "FILLED",
        "CANCELLED": "CANCELLED", "CANCEL": "CANCELLED",
        "CXL-PEND": "PENDING_CANCEL", "CXLPENDING": "PENDING_CANCEL",
        "REJECTED": "REJECTED",
        "EXPIRED": "CANCELLED",
        "ASSIGN": "ASSIGN",
        "COMPLETED": "COMPLETED",
        "QUEUED": "QUEUED",
        "SUSPEND": "SUSPENDED", "SUSPENDED": "SUSPENDED",
        "SENT": "SENT", "A-SENT": "SENT",
        "ROUTED": "WORKING", "ACTIVE": "WORKING",
        "PENDING": "NEW", "PEND-NEW": "NEW",
    }

    SIDE_MAP = {"BUY": "BUY", "SELL": "SELL", 1: "BUY", 2: "SELL"}

    def __init__(self):
        self.session: Optional[Session] = None
        self.active_service_name: Optional[str] = None
        self.connected: bool = False
        self.connection_time: Optional[datetime] = None
        self.last_error: Optional[str] = None
        self.service: Optional[Service] = None

        # Dedicated session for request/response operations (get_brokers,
        # route_order, etc.).  Bloomberg's nextEvent() is NOT thread-safe:
        # calling it concurrently on the same session from the subscription
        # thread and request handler causes the subscription thread to steal
        # response events, making requests time out.
        self._request_session: Optional[Session] = None
        self._request_service: Optional[Service] = None

        # Separate session for //blp/mktdata subscriptions (market data, FX rates)
        # Using a separate session avoids nextEvent() races with the EMSX
        # subscription thread on the main session.
        self._mktdata_session: Optional[Session] = None
        self._mktdata_connected: bool = False

        # Order cache: keyed by EMSX_SEQUENCE (str)
        self._orders: Dict[str, Order] = {}
        self._init_paint_done: bool = False
        self._lock = asyncio.Lock()
        
        # Thread-safe lock for shared data access (protects _orders, _routes, etc.)
        self._data_lock = threading.RLock()

        # Route cache: keyed by "{EMSX_SEQUENCE}.{EMSX_ROUTE_ID}"
        self._routes: Dict[str, Route] = {}
        self._route_init_paint_done: bool = False

        # Terminal trader identity: computed on-demand from order cache

        # Subscription state tracking
        self._subscription_failed: bool = False

        # Background subscription thread
        self._sub_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Market data cache: ticker -> value (updated in real-time via //blp/mktdata subscriptions)
        self._price_changes: Dict[str, float] = {}
        self._adv5d: Dict[str, float] = {}
        self._mkt_vwap: Dict[str, float] = {}
        self._fx_rates: Dict[str, float] = {}  # currency -> USD rate (e.g. "HKD" -> 0.128)
        self._round_lot_sizes: Dict[str, int] = {}  # ticker -> round lot size (for odd lot detection)
        self._mktdata_subscribed_tickers: set = set()  # tickers currently subscribed (attempted)
        self._mktdata_active_tickers: set = set()       # tickers confirmed streaming data
        self._mktdata_failed_tickers: set = set()       # tickers whose subscription failed (retry later)
        self._mktdata_last_retry: Optional[datetime] = None
        self._mktdata_retry_interval = 300  # retry failed subscriptions every 5 min
        self._market_data_lock = threading.Lock()  # protect subscription management

        # FX rate refresh via //blp/refdata (every 5 minutes)
        self._fx_refresh_interval = 300  # refresh FX rates every 5 minutes (was: 3600)
        self._fx_last_refresh: Optional[datetime] = None
        self._fx_refdata_pending = False
        self._fx_refdata_cid = blpapi.CorrelationId("__fx_refdata__")
        self._crncy_refdata_cid = blpapi.CorrelationId("__crncy_refdata__")
        self._crncy_refdata_pending = False
        self._refdata_service_available = False

        # Authoritative ticker→trading-currency map from //blp/refdata CRNCY field
        self._ticker_currencies: Dict[str, str] = {}  # e.g. "0700 HK Equity" -> "HKD"
        self._crncy_queried_tickers: set = set()  # tickers already queried

        # Round lot size cache from //blp/refdata (like BDP function) - fetched once per ticker
        self._round_lot_sizes: Dict[str, int] = {}  # ticker -> round lot size
        self._round_lot_queried_tickers: set = set()  # tickers already queried (fetch once)
        self._round_lot_pending_tickers: set = set()  # tickers with pending refdata request
        self._round_lot_refdata_cid = blpapi.CorrelationId("__round_lot_refdata__")
        self._round_lot_refdata_pending = False

        # Background mktdata subscription thread
        self._mktdata_thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        async with self._lock:
            if self.connected and self.session:
                return True

            session = None  # Local variable for proper cleanup
            try:
                logger.info(f"Connecting to Bloomberg at {settings.BLOOMBERG_HOST}:{settings.BLOOMBERG_PORT}")

                session_options = SessionOptions()
                session_options.setServerAddress(
                    settings.BLOOMBERG_HOST,
                    settings.BLOOMBERG_PORT,
                    0,
                )
                session_options.setAutoRestartOnDisconnection(True)
                session_options.setNumStartAttempts(3)

                session = Session(session_options)
                if not session.start():
                    self.last_error = "Failed to start Bloomberg session"
                    logger.error(self.last_error)
                    if session:
                        try:
                            session.stop()
                        except Exception:
                            pass
                    return False

                # Try each service name in order
                opened_svc = None
                for svc_name in self.EMSX_SERVICES:
                    if session.openService(svc_name):
                        self.service = session.getService(svc_name)
                        self.active_service_name = svc_name
                        opened_svc = svc_name
                        logger.info(f"Opened Bloomberg EMSX service: {svc_name}")
                        break
                    else:
                        logger.warning(f"Could not open {svc_name}, trying next...")

                if not opened_svc:
                    self.last_error = "Failed to open any EMSX service"
                    logger.error(self.last_error)
                    session.stop()
                    return False

                # Store session only after all checks pass
                self.session = session
                self.connected = True
                self.connection_time = datetime.now()
                self.last_error = None

                # Reset subscription state for fresh connection
                with self._data_lock:
                    self._subscription_failed = False
                    self._init_paint_done = False
                    self._orders = {}
                    self._routes = {}
                    self._route_init_paint_done = False
                # Terminal trader identity resets with reconnect
                self._price_changes = {}
                self._adv5d = {}
                self._mkt_vwap = {}
                self._fx_rates = {}
                self._round_lot_sizes = {}
                self._mktdata_subscribed_tickers = set()
                self._mktdata_active_tickers = set()
                self._mktdata_failed_tickers = set()
                self._mktdata_last_retry = None
                self._fx_last_refresh = None
                self._fx_refdata_pending = False
                self._crncy_refdata_pending = False
                self._crncy_queried_tickers = set()
                self._ticker_currencies = {}
                self._refdata_service_available = False

                # Open dedicated request session for request/response operations
                # (avoids nextEvent race with EMSX subscription thread on main session)
                request_session = None
                try:
                    req_opts = SessionOptions()
                    req_opts.setServerAddress(settings.BLOOMBERG_HOST, settings.BLOOMBERG_PORT, 0)
                    req_opts.setAutoRestartOnDisconnection(True)
                    request_session = Session(req_opts)
                    if request_session.start() and request_session.openService(opened_svc):
                        self._request_session = request_session
                        self._request_service = request_session.getService(opened_svc)
                        logger.info(f"Opened dedicated request session for {opened_svc}")
                    else:
                        logger.warning("Could not open request session — falling back to shared session")
                        if request_session:
                            try:
                                request_session.stop()
                            except Exception:
                                pass
                        self._request_session = None
                        self._request_service = None
                except Exception as e:
                    logger.warning(f"Failed to open request session: {e}")
                    if request_session:
                        try:
                            request_session.stop()
                        except Exception:
                            pass
                    self._request_session = None
                    self._request_service = None

                # Open separate mktdata session for streaming market data + FX rates
                # (avoids nextEvent race with EMSX subscription thread on main session)
                mktdata_session = None
                try:
                    mktdata_opts = SessionOptions()
                    mktdata_opts.setServerAddress(settings.BLOOMBERG_HOST, settings.BLOOMBERG_PORT, 0)
                    mktdata_session = Session(mktdata_opts)
                    if mktdata_session.start() and mktdata_session.openService("//blp/mktdata"):
                        self._mktdata_session = mktdata_session
                        self._mktdata_connected = True
                        logger.info("Opened dedicated mktdata session for real-time market data subscriptions")
                        # Also open //blp/refdata for periodic FX rate queries
                        try:
                            if mktdata_session.openService("//blp/refdata"):
                                self._refdata_service_available = True
                                logger.info("Opened //blp/refdata on mktdata session for hourly FX rate lookups")
                        except Exception as e:
                            logger.warning(f"Could not open //blp/refdata on mktdata session: {e}")
                    else:
                        logger.warning("Could not open mktdata session — market data enrichment will be unavailable")
                        if mktdata_session:
                            try:
                                mktdata_session.stop()
                            except Exception:
                                pass
                        self._mktdata_session = None
                        self._mktdata_connected = False
                except Exception as e:
                    logger.warning(f"Failed to open mktdata session: {e}")
                    if mktdata_session:
                        try:
                            mktdata_session.stop()
                        except Exception:
                            pass
                    self._mktdata_session = None
                    self._mktdata_connected = False

                # Start background subscription thread
                self._stop_event.clear()
                self._sub_thread = threading.Thread(
                    target=self._subscription_loop,
                    daemon=True,
                    name="emsx-subscription",
                )
                self._sub_thread.start()

                # Start background mktdata subscription thread (real-time market data + FX)
                self._mktdata_thread = threading.Thread(
                    target=self._mktdata_subscription_loop,
                    daemon=True,
                    name="mktdata-subscription",
                )
                self._mktdata_thread.start()

                logger.info("Started EMSX subscription + mktdata subscription threads")
                return True

            except Exception as e:
                self.last_error = f"Connection error: {str(e)}"
                logger.exception(self.last_error)
                self.connected = False
                # Ensure session cleanup on error
                if session:
                    try:
                        session.stop()
                    except Exception:
                        pass
                return False

    def disconnect(self):
        """Disconnect from Bloomberg and cleanup all resources.
        
        Ensures proper cleanup even if threads are stuck.
        """
        logger.info("Disconnecting from Bloomberg...")
        self._stop_event.set()
        
        # Wait for threads with timeout, log warnings if stuck
        if self._sub_thread and self._sub_thread.is_alive():
            self._sub_thread.join(timeout=5)
            if self._sub_thread.is_alive():
                logger.warning("EMSX subscription thread did not stop within timeout")
        
        if self._mktdata_thread and self._mktdata_thread.is_alive():
            self._mktdata_thread.join(timeout=5)
            if self._mktdata_thread.is_alive():
                logger.warning("Mktdata subscription thread did not stop within timeout")
        
        # Stop mktdata session first (dependent on main session)
        if self._mktdata_session:
            try:
                self._mktdata_session.stop()
                logger.info("Mktdata session stopped")
            except Exception as e:
                logger.warning(f"Error stopping mktdata session: {e}")
            finally:
                self._mktdata_session = None
                self._mktdata_connected = False
        
        # Stop request session
        if self._request_session:
            try:
                self._request_session.stop()
                logger.info("Request session stopped")
            except Exception as e:
                logger.warning(f"Error stopping request session: {e}")
            finally:
                self._request_session = None
                self._request_service = None
        
        # Stop main session
        if self.session:
            try:
                self.session.stop()
                logger.info("Bloomberg session stopped")
            except Exception as e:
                logger.error(f"Error stopping session: {e}")
            finally:
                self.session = None
                self.service = None
                self.active_service_name = None
        
        self.connected = False
        self.connection_time = None
        logger.info("Bloomberg disconnect complete")

    def get_status(self) -> ConnectionStatus:
        if not self.connected:
            return ConnectionStatus(status="disconnected", message=self.last_error)
        uptime = int((datetime.now() - self.connection_time).total_seconds()) if self.connection_time else None
        return ConnectionStatus(
            status="connected",
            lastConnected=self.connection_time.isoformat() if self.connection_time else None,
            uptime=uptime,
        )

    # ------------------------------------------------------------------
    # Subscription loop (runs in background thread)
    # ------------------------------------------------------------------

    def _subscription_loop(self):
        """
        Background thread: subscribe to EMSX orders AND routes and keep caches updated.
        Bloomberg EMSX Subscription approach per official docs.
        """
        try:
            # Order subscription
            order_fields_str = ",".join(self.ORDER_FIELDS)
            order_topic = f"{self.active_service_name}/order?fields={order_fields_str}"
            logger.info(f"Subscribing to: {order_topic}")

            # Route subscription
            route_fields_str = ",".join(self.ROUTE_FIELDS)
            route_topic = f"{self.active_service_name}/route?fields={route_fields_str}"
            logger.info(f"Subscribing to: {route_topic}")

            sub_list = blpapi.SubscriptionList()
            order_cid = blpapi.CorrelationId(98)
            route_cid = blpapi.CorrelationId(99)
            sub_list.add(topic=order_topic, correlationId=order_cid)
            sub_list.add(topic=route_topic, correlationId=route_cid)
            self.session.subscribe(sub_list)

            while not self._stop_event.is_set():
                event = self.session.nextEvent(2000)  # 2-second timeout
                etype = event.eventType()

                if etype == blpapi.Event.SUBSCRIPTION_DATA:
                    for msg in event:
                        # Dispatch by CorrelationId (98=order, 99=route)
                        cid = msg.correlationId()
                        cid_val = cid.value() if cid else None
                        if cid_val == 99:
                            self._process_route_message(msg)
                        else:
                            self._process_subscription_message(msg)

                elif etype == blpapi.Event.SUBSCRIPTION_STATUS:
                    for msg in event:
                        mtype = str(msg.messageType())
                        if "SubscriptionStarted" in mtype:
                            logger.info("EMSX order subscription started")
                        elif "SubscriptionFailure" in mtype or "SubscriptionTerminated" in mtype:
                            logger.error(f"Subscription issue: {mtype}")
                            try:
                                reason = msg.getElement("reason")
                                desc = reason.getElementAsString("description")
                                logger.error(f"Subscription error detail: {desc}")
                            except Exception:
                                pass
                            # Mark subscription as failed and stop this thread
                            # so get_orders() can retry with the next service
                            self._subscription_failed = True
                            self.connected = False
                            logger.warning(f"Subscription failed for {self.active_service_name}, will retry with fallback service")
                            return

                elif etype == blpapi.Event.SESSION_STATUS:
                    for msg in event:
                        mtype = str(msg.messageType())
                        if "SessionTerminated" in mtype or "SessionStartupFailure" in mtype:
                            logger.error("Bloomberg session terminated")
                            self.connected = False
                            return

                elif etype == blpapi.Event.TIMEOUT:
                    continue  # normal timeout, keep looping

        except Exception as e:
            logger.exception(f"Subscription loop error: {e}")
            self.connected = False

    def _process_subscription_message(self, msg):
        """Process a single subscription message and update the order cache.
        
        Thread-safe: uses _data_lock to protect shared _orders cache.
        """
        try:
            # Check message fields
            event_status = self._msg_safe_int(msg, "EVENT_STATUS", -1)
            seq = self._msg_safe_int(msg, "EMSX_SEQUENCE", 0)
            if seq == 0:
                return

            seq_key = str(seq)

            # EVENT_STATUS = 8 → deletion
            if event_status == 8:
                with self._data_lock:
                    if seq_key in self._orders:
                        del self._orders[seq_key]
                        logger.debug(f"Deleted order {seq_key}")
                return

            # EVENT_STATUS = 11 → end of INIT_PAINT
            if event_status == 11:
                with self._data_lock:
                    order_count = len(self._orders)
                    self._init_paint_done = True
                logger.warning(f"INIT_PAINT complete — {order_count} orders loaded")
                return

            # Parse order from message (fields come directly in the message)
            order = self._parse_order_message(msg, seq)
            if not order:
                logger.warning(f"Failed to parse order for seq={seq}, event_status={event_status}")
                return

            # EVENT_STATUS=7 (update) only contains dynamic fields.
            # Static fields (EMSX_TICKER, EMSX_SIDE, etc.) will be empty.
            # Merge with cached order so static fields are preserved.
            with self._data_lock:
                if event_status == 7 and seq_key in self._orders:
                    cached = self._orders[seq_key]
                    merged = Order(
                        id=cached.id,
                        # Static fields: keep cached values when update is empty
                        symbol=order.symbol or cached.symbol,
                        side=order.side if self._msg_safe_str(msg, "EMSX_SIDE") else cached.side,
                        orderType=order.orderType if self._msg_safe_str(msg, "EMSX_ORDER_TYPE") else cached.orderType,
                        account=order.account or cached.account,
                        portfolio=order.portfolio or cached.portfolio,
                        trader=order.trader or cached.trader,
                        exchange=order.exchange or cached.exchange,
                        currency=order.currency if self._msg_safe_str(msg, "EMSX_CURRENCY_PAIR") else cached.currency,
                        createdAt=cached.createdAt,
                        # Dynamic fields: only update status if EMSX_STATUS was present in the message
                        status=order.status if self._msg_safe_str(msg, "EMSX_STATUS") else cached.status,
                        quantity=order.quantity if order.quantity > 0 else cached.quantity,
                        filledQuantity=order.filledQuantity,
                        remainingQuantity=order.remainingQuantity if order.quantity > 0 else cached.remainingQuantity,
                        price=order.price if order.price is not None else cached.price,
                        stopPrice=order.stopPrice or cached.stopPrice,
                        avgPrice=order.avgPrice or cached.avgPrice,
                        timeInForce=order.timeInForce if self._msg_safe_str(msg, "EMSX_TIF") else cached.timeInForce,
                        updatedAt=datetime.now().isoformat(),
                        notes=order.notes or cached.notes,
                        customNote1=order.customNote1 or cached.customNote1,
                        customNote2=order.customNote2 or cached.customNote2,
                        customNote3=order.customNote3 or cached.customNote3,
                        customNote4=order.customNote4 or cached.customNote4,
                        customNote5=order.customNote5 or cached.customNote5,
                        traderNotes=order.traderNotes or cached.traderNotes,
                        execInstruction=order.execInstruction or cached.execInstruction,
                        percentRemain=order.percentRemain if order.percentRemain is not None else cached.percentRemain,
                        percentFilled=order.percentFilled if order.filledQuantity > 0 else cached.percentFilled,
                        strategyType=order.strategyType or cached.strategyType,
                        strategyPartRate=order.strategyPartRate if order.strategyPartRate is not None else cached.strategyPartRate,
                        strategyStyle=order.strategyStyle or cached.strategyStyle,
                        strategyStartTime=order.strategyStartTime or cached.strategyStartTime,
                        strategyEndTime=order.strategyEndTime or cached.strategyEndTime,
                        broker=order.broker or cached.broker,
                        dayAvgPrice=order.dayAvgPrice if order.dayAvgPrice is not None else cached.dayAvgPrice,
                        arrivalPrice=order.arrivalPrice if order.arrivalPrice is not None else cached.arrivalPrice,
                        lastPrice=order.lastPrice if order.lastPrice is not None else cached.lastPrice,
                        dollarValueUsd=order.dollarValueUsd if order.dollarValueUsd is not None else cached.dollarValueUsd,
                        adv5d=cached.adv5d,  # preserved from market data enrichment
                        mktVwap=cached.mktVwap,  # preserved from market data enrichment
                        pctChange=cached.pctChange,  # preserved from market data enrichment
                    )
                    self._orders[seq_key] = merged
                    logger.debug(f"Order update (7): {seq_key} {merged.symbol} -> {merged.status}")
                elif event_status == 7:
                    # Update for a sequence not yet in cache (arrived before its INIT_PAINT).
                    # Skip to avoid inserting an order with empty static fields (blank ticker).
                    logger.debug(f"Skip update for unseen seq {seq_key} — no cached base data")
                else:
                    self._orders[seq_key] = order
                    if event_status == 4:
                        logger.debug(f"INIT_PAINT order: {seq_key} {order.symbol} {order.side} {order.status}")
                        # Log first few orders at WARNING level for diagnostics
                        if len(self._orders) <= 3:
                            logger.warning(f"INIT_PAINT order #{len(self._orders)}: seq={seq_key} symbol='{order.symbol}' exchange='{order.exchange}' side={order.side}")
                    elif event_status == 6:
                        logger.debug(f"New order (6): {seq_key} {order.symbol} {order.side} {order.status}")
                    # NEW: Try to enrich related routes when new order arrives
                    self._enrich_routes_with_new_order(order)

        except Exception as e:
            logger.warning(f"Error processing subscription message: {e}")

    def _enrich_routes_with_new_order(self, order):
        """When a new order arrives, enrich related routes that were missing parent data.
        
        This handles the case where route data arrives before parent order.
        Thread-safe: should be called within _data_lock.
        """
        seq_str = str(order.id)  # order.id is the sequence number
        enriched_count = 0
        for route_key, route in self._routes.items():
            if str(route.sequence) == seq_str:
                # Check if ANY enrichment field is missing (not just ticker)
                needs_update = not route.ticker or not route.exchange or not route.side
                if needs_update:
                    # Update route with parent order data
                    update_dict = route.model_dump()
                    update_dict["ticker"] = route.ticker or order.symbol or ""
                    update_dict["side"] = route.side or order.side or ""
                    update_dict["portfolio"] = route.portfolio or order.portfolio or ""
                    update_dict["trader"] = route.trader or order.trader or ""
                    update_dict["traderUuid"] = route.traderUuid if route.traderUuid else (order.traderUuid or 0)
                    update_dict["currency"] = route.currency or order.currency or ""
                    update_dict["exchange"] = route.exchange or order.exchange or ""
                    self._routes[route_key] = Route(**update_dict)
                    enriched_count += 1
                    logger.info(f"Delayed enrichment for route {route_key}: ticker='{update_dict['ticker']}', exchange='{update_dict['exchange']}'")
        if enriched_count > 0:
            logger.info(f"Enriched {enriched_count} routes for new order {seq_str}")

    def _enrich_route_from_parent(self, route_key, route):
        """Enrich a single route from its parent order in cache.
        
        Thread-safe: should be called within _data_lock.
        """
        parent = self._orders.get(str(route.sequence))
        if parent and (not route.ticker or not route.exchange or not route.side):
            update_dict = route.model_dump()
            update_dict["ticker"] = route.ticker or parent.symbol or ""
            update_dict["side"] = route.side or parent.side or ""
            update_dict["portfolio"] = route.portfolio or parent.portfolio or ""
            update_dict["trader"] = route.trader or parent.trader or ""
            update_dict["traderUuid"] = route.traderUuid if route.traderUuid else (parent.traderUuid or 0)
            update_dict["currency"] = route.currency or parent.currency or ""
            update_dict["exchange"] = route.exchange or parent.exchange or ""
            self._routes[route_key] = Route(**update_dict)
            logger.debug(f"Enrich new route {route_key}: ticker='{update_dict['ticker']}', exchange='{update_dict['exchange']}'")

    def _process_route_message(self, msg):
        """Process a single route subscription message and update the route cache.
        
        Thread-safe: uses _data_lock to protect shared _routes cache.
        """
        try:
            event_status = self._msg_safe_int(msg, "EVENT_STATUS", -1)
            seq = self._msg_safe_int(msg, "EMSX_SEQUENCE", 0)
            route_id = self._msg_safe_int(msg, "EMSX_ROUTE_ID", 0)
            if seq == 0 or route_id == 0:
                # Heartbeats and other control messages
                if event_status == 11:
                    with self._data_lock:
                        route_count = len(self._routes)
                        self._route_init_paint_done = True
                    logger.info(f"Route INIT_PAINT complete — {route_count} routes loaded")
                return

            route_key = f"{seq}.{route_id}"

            # EVENT_STATUS = 8 → deletion
            if event_status == 8:
                with self._data_lock:
                    if route_key in self._routes:
                        del self._routes[route_key]
                        logger.debug(f"Deleted route {route_key}")
                return

            # EVENT_STATUS = 11 → end of INIT_PAINT
            if event_status == 11:
                with self._data_lock:
                    route_count = len(self._routes)
                    self._route_init_paint_done = True
                logger.info(f"Route INIT_PAINT complete — {route_count} routes loaded")
                return

            route = self._parse_route_message(msg, seq, route_id)
            if route:
                with self._data_lock:
                    if event_status == 7 and route_key in self._routes:
                        # Merge update with cached route (keep static fields)
                        cached = self._routes[route_key]
                        update_dict = {}
                        for field_name in route.model_fields:
                            new_val = getattr(route, field_name)
                            cached_val = getattr(cached, field_name)
                            # Keep cached value if update is empty/default
                            if new_val is not None and new_val != "" and new_val != 0:
                                update_dict[field_name] = new_val
                            elif cached_val is not None and cached_val != "" and cached_val != 0:
                                update_dict[field_name] = cached_val

                        # IMPORTANT: Always preserve enrichment fields from cache
                        # These fields are populated from parent order and not in route messages
                        enrichment_fields = ["ticker", "side", "portfolio", "trader", "traderUuid", "currency", "exchange"]
                        for ef in enrichment_fields:
                            cached_ef_val = getattr(cached, ef, None)
                            # Use explicit comparison: empty string and 0 are valid cached values to skip,
                            # but non-empty strings and non-zero ints must be preserved
                            if cached_ef_val is not None and cached_ef_val != "" and cached_ef_val != 0:
                                update_dict[ef] = cached_ef_val

                        # Always keep key fields
                        update_dict["id"] = route_key
                        update_dict["routeId"] = route_id
                        update_dict["sequence"] = seq
                        # Always update status from the message if present
                        raw_status = self._msg_safe_str(msg, "EMSX_STATUS")
                        if raw_status:
                            update_dict["status"] = raw_status
                        self._routes[route_key] = Route(**update_dict)
                        logger.debug(f"Route update (7): {route_key} -> {self._routes[route_key].status}, "
                                    f"enrichment: ticker='{update_dict.get('ticker','')}', exchange='{update_dict.get('exchange','')}'")
                    elif event_status == 7:
                        logger.debug(f"Skip route update for unseen {route_key}")
                    else:
                        self._routes[route_key] = route
                        # Immediately enrich new route from parent order if available
                        self._enrich_route_from_parent(route_key, route)
                        if event_status == 4:
                            logger.debug(f"INIT_PAINT route: {route_key} {route.broker} {route.status}")
                        elif event_status == 6:
                            logger.debug(f"New route (6): {route_key} {route.broker} {route.status}")

        except Exception as e:
            logger.warning(f"Error processing route message: {e}")

    def _parse_route_message(self, msg, seq: int, route_id: int) -> Optional[Route]:
        """Parse a route subscription message into a Route model."""
        try:
            route_key = f"{seq}.{route_id}"
            status = self._msg_safe_str(msg, "EMSX_STATUS")
            broker = self._msg_safe_str(msg, "EMSX_BROKER")
            amount = self._msg_safe_int(msg, "EMSX_AMOUNT")
            filled = self._msg_safe_int(msg, "EMSX_FILLED")
            working = self._msg_safe_int(msg, "EMSX_WORKING")
            remain_balance = self._msg_safe_int(msg, "EMSX_REMAIN_BALANCE")
            avg_price = self._msg_safe_float(msg, "EMSX_AVG_PRICE") or None
            limit_price = self._msg_safe_float(msg, "EMSX_LIMIT_PRICE") or None
            stop_price = self._msg_safe_float(msg, "EMSX_STOP_PRICE") or None
            last_price = self._msg_safe_float(msg, "EMSX_LAST_PRICE") or None
            last_shares_raw = self._msg_safe_int(msg, "EMSX_LAST_SHARES", 0)
            last_shares = last_shares_raw if last_shares_raw > 0 else None
            day_avg_price = self._msg_safe_float(msg, "EMSX_DAY_AVG_PRICE") or None
            day_fill = self._msg_safe_int(msg, "EMSX_DAY_FILL")
            bse_avg_price = self._msg_safe_float(msg, "EMSX_BSE_AVG_PRICE") or None
            bse_filled = self._msg_safe_int(msg, "EMSX_BSE_FILLED")
            nse_avg_price = self._msg_safe_float(msg, "EMSX_NSE_AVG_PRICE") or None
            nse_filled = self._msg_safe_int(msg, "EMSX_NSE_FILLED")

            order_type = self._msg_safe_str(msg, "EMSX_ORDER_TYPE")
            tif = self._msg_safe_str(msg, "EMSX_TIF")
            hand_instruction = self._msg_safe_str(msg, "EMSX_HAND_INSTRUCTION")
            exec_instruction = self._msg_safe_str(msg, "EMSX_EXEC_INSTRUCTION")
            notes = self._msg_safe_str(msg, "EMSX_NOTES")

            strategy_type = self._msg_safe_str(msg, "EMSX_STRATEGY_TYPE")
            strategy_style = self._msg_safe_str(msg, "EMSX_STRATEGY_STYLE")
            strategy_part_rate1 = self._msg_safe_float(msg, "EMSX_STRATEGY_PART_RATE1") or None
            strategy_part_rate2 = self._msg_safe_float(msg, "EMSX_STRATEGY_PART_RATE2") or None
            # EMSX_STRATEGY_START_TIME / END_TIME are integers (HHMM format, e.g. 930 = 09:30)
            strategy_start_time_raw = self._msg_safe_int(msg, "EMSX_STRATEGY_START_TIME", 0)
            strategy_start_time = self._format_strategy_time(strategy_start_time_raw)
            strategy_end_time_raw = self._msg_safe_int(msg, "EMSX_STRATEGY_END_TIME", 0)
            strategy_end_time = self._format_strategy_time(strategy_end_time_raw)

            exchange_destination = self._msg_safe_str(msg, "EMSX_EXCHANGE_DESTINATION")
            execute_broker = self._msg_safe_str(msg, "EMSX_EXECUTE_BROKER")
            is_manual_route = self._msg_safe_int(msg, "EMSX_IS_MANUAL_ROUTE")
            route_ref_id = self._msg_safe_str(msg, "EMSX_ROUTE_REF_ID")
            currency_pair = self._msg_safe_str(msg, "EMSX_CURRENCY_PAIR")
            urgency_level = self._msg_safe_str(msg, "EMSX_URGENCY_LEVEL")

            # Timestamps
            route_create_date_raw = self._msg_safe_int(msg, "EMSX_ROUTE_CREATE_DATE")
            route_create_date = str(route_create_date_raw) if route_create_date_raw > 0 else ""
            route_create_time_raw = self._msg_safe_int(msg, "EMSX_ROUTE_CREATE_TIME")
            route_create_time = str(route_create_time_raw) if route_create_time_raw > 0 else ""
            last_fill_date_raw = self._msg_safe_int(msg, "EMSX_LAST_FILL_DATE")
            last_fill_date = str(last_fill_date_raw) if last_fill_date_raw > 0 else ""
            last_fill_time_raw = self._msg_safe_int(msg, "EMSX_LAST_FILL_TIME")
            last_fill_time = str(last_fill_time_raw) if last_fill_time_raw > 0 else ""
            time_stamp_raw = self._msg_safe_int(msg, "EMSX_TIME_STAMP")
            time_stamp = str(time_stamp_raw) if time_stamp_raw > 0 else ""
            route_last_update_raw = self._msg_safe_str(msg, "EMSX_ROUTE_LAST_UPDATE_TIME")
            route_last_update_time = route_last_update_raw

            fill_id = self._msg_safe_int(msg, "EMSX_FILL_ID")
            percent_remain = self._msg_safe_float(msg, "EMSX_PERCENT_REMAIN") or None

            reason_code = self._msg_safe_str(msg, "EMSX_REASON_CODE")
            reason_desc = self._msg_safe_str(msg, "EMSX_REASON_DESC")
            broker_status = self._msg_safe_str(msg, "EMSX_BROKER_STATUS")

            settle_amount = self._msg_safe_float(msg, "EMSX_SETTLE_AMOUNT") or None
            settle_date = self._msg_safe_str(msg, "EMSX_SETTLE_DATE")

            comm_rate = self._msg_safe_float(msg, "EMSX_COMM_RATE") or None
            broker_comm = self._msg_safe_float(msg, "EMSX_BROKER_COMM") or None
            user_comm_rate = self._msg_safe_float(msg, "EMSX_USER_COMM_RATE") or None
            user_comm_amount = self._msg_safe_float(msg, "EMSX_USER_COMM_AMOUNT") or None
            user_fees = self._msg_safe_float(msg, "EMSX_USER_FEES") or None
            misc_fees = self._msg_safe_float(msg, "EMSX_MISC_FEES") or None
            user_net_money = self._msg_safe_float(msg, "EMSX_USER_NET_MONEY") or None
            principal = self._msg_safe_float(msg, "EMSX_PRINCIPAL") or None
            route_price = self._msg_safe_float(msg, "EMSX_ROUTE_PRICE") or None

            return Route(
                id=route_key,
                routeId=route_id,
                sequence=seq,
                status=status,
                broker=broker,
                amount=amount,
                filled=filled,
                working=working,
                remainBalance=remain_balance,
                avgPrice=avg_price,
                limitPrice=limit_price,
                stopPrice=stop_price,
                lastPrice=last_price,
                lastShares=last_shares,
                dayAvgPrice=day_avg_price,
                dayFill=day_fill,
                bseAvgPrice=bse_avg_price,
                bseFilled=bse_filled,
                nseAvgPrice=nse_avg_price,
                nseFilled=nse_filled,
                orderType=order_type,
                tif=tif,
                handInstruction=hand_instruction,
                execInstruction=exec_instruction,
                notes=notes,
                strategyType=strategy_type,
                strategyStyle=strategy_style,
                strategyPartRate1=strategy_part_rate1,
                strategyPartRate2=strategy_part_rate2,
                strategyStartTime=strategy_start_time,
                strategyEndTime=strategy_end_time,
                exchangeDestination=exchange_destination,
                executeBroker=execute_broker,
                isManualRoute=is_manual_route,
                routeRefId=route_ref_id,
                currencyPair=currency_pair,
                urgencyLevel=urgency_level,
                routeCreateDate=route_create_date,
                routeCreateTime=route_create_time,
                lastFillDate=last_fill_date,
                lastFillTime=last_fill_time,
                timeStamp=time_stamp,
                routeLastUpdateTime=route_last_update_time,
                fillId=fill_id,
                percentRemain=percent_remain,
                reasonCode=reason_code,
                reasonDesc=reason_desc,
                brokerStatus=broker_status,
                settleAmount=settle_amount,
                settleDate=settle_date,
                commRate=comm_rate,
                brokerComm=broker_comm,
                userCommRate=user_comm_rate,
                userCommAmount=user_comm_amount,
                userFees=user_fees,
                miscFees=misc_fees,
                userNetMoney=user_net_money,
                principal=principal,
                routePrice=route_price,
            )
        except Exception as e:
            logger.warning(f"Error parsing route message for {seq}.{route_id}: {e}")
            return None

    def _msg_safe_int(self, msg, name: str, default: int = 0) -> int:
        try:
            if msg.hasElement(name):
                return msg.getElementAsInteger(name)
        except Exception:
            pass
        return default

    def _msg_safe_float(self, msg, name: str, default: float = 0.0) -> float:
        try:
            if msg.hasElement(name):
                return msg.getElementAsFloat(name)
        except Exception:
            pass
        return default

    def _msg_safe_str(self, msg, name: str, default: str = "") -> str:
        try:
            if msg.hasElement(name):
                return msg.getElementAsString(name)
        except Exception:
            pass
        return default

    @staticmethod
    def _format_strategy_time(raw: int) -> str:
        """Convert Bloomberg strategy time integer to HH:MM string.

        Bloomberg encodes strategy start/end times as integers in HHMM format
        (e.g. 930 = 09:30, 1600 = 16:00) or as seconds from midnight.
        Returns empty string for 0 (unset).
        """
        if not raw or raw <= 0:
            return ""
        # If value looks like seconds from midnight (> 2400), convert
        if raw > 2400:
            h = raw // 3600
            m = (raw % 3600) // 60
        else:
            # HHMM format
            h = raw // 100
            m = raw % 100
        return f"{h:02d}:{m:02d}"

    # Mapping of Bloomberg exchange suffixes to trading currencies
    _EXCHANGE_CURRENCY_MAP = {
        "US": "USD", "UN": "USD", "UQ": "USD", "UW": "USD", "UA": "USD", "UP": "USD",
        "CT": "USD", "UF": "USD",
        "CN": "CAD", "CF": "CAD",
        "LN": "GBP", "LI": "GBP",
        "JP": "JPY", "JT": "JPY",
        "HK": "HKD",
        "CH": "CNY", "CS": "CNY", "CG": "CNY", "CI": "CNY", "C1": "CNY", "C2": "CNY",
        "SS": "CNY", "SZ": "CNY",
        "GR": "EUR", "GY": "EUR", "GF": "EUR",
        "FP": "EUR", "PA": "EUR",
        "IM": "EUR", "NA": "EUR", "SM": "EUR", "BB": "EUR",
        "SQ": "EUR", "PL": "EUR", "ID": "EUR", "GA": "EUR",
        "AU": "AUD", "AT": "AUD",
        "SP": "SGD", "SI": "SGD",
        "KS": "KRW", "KQ": "KRW",
        "TT": "TWD",
        "TB": "THB",
        "IJ": "IDR",
        "MK": "MYR",
        "PM": "PHP",
        "IN": "INR", "IB": "INR", "IS": "INR",
        "BZ": "BRL",
        "MM": "MXN",
        "NZ": "NZD",
        "ST": "SEK", "NO": "NOK", "DC": "DKK", "FH": "EUR",
        "SW": "CHF", "SE": "CHF",
        "SJ": "ZAR",
        "AB": "AED",
    }

    @classmethod
    def _derive_currency(cls, currency_pair: str, ticker: str) -> str:
        """Derive the **trading currency** of the security.

        EMSX_CURRENCY_PAIR is unreliable for this purpose because:
          - It may return the settlement/user currency ("USD") for non-USD securities.
          - It may return a 6-char pair code ("HKDUSD") which is not a valid 3-char ccy.
        Therefore we **prioritise the ticker exchange suffix** (always reliable for
        exchange-listed instruments) and only fall back to EMSX_CURRENCY_PAIR when
        the ticker cannot be resolved.

        Priority:
          1. Ticker exchange suffix → _EXCHANGE_CURRENCY_MAP  (most reliable)
          2. EMSX_CURRENCY_PAIR parsed intelligently               (fallback)
          3. Empty string                                           (last resort)
        """
        # ── Step 1: Ticker exchange suffix (most reliable) ──────────────
        ticker_ccy = ""
        parts = ticker.strip().split() if ticker else []
        if len(parts) >= 2:
            asset_types = ("EQUITY", "GOVT", "CORP", "COMDTY", "INDEX", "CURNCY", "PREF", "MTGE")
            exch_code = parts[-2].upper() if parts[-1].upper() in asset_types else parts[-1].upper()
            ticker_ccy = cls._EXCHANGE_CURRENCY_MAP.get(exch_code, "")

        if ticker_ccy:
            return ticker_ccy

        # ── Step 2: Parse EMSX_CURRENCY_PAIR ────────────────────────────
        if currency_pair:
            cp = currency_pair.strip()
            # Handle 6-char pair codes like "HKDUSD", "JPYUSD" → extract first 3 chars
            if len(cp) == 6 and cp[3:].upper() == "USD":
                return cp[:3].upper()            # "HKDUSD" → "HKD"
            if len(cp) == 6 and cp[:3].upper() == "USD":
                return cp[3:].upper()            # "USDHKD" → "HKD"
            # Handle slash-separated pairs
            if "/" in cp:
                parts_pair = [p.strip() for p in cp.split("/")]
                # Return the non-USD side, preferring first token
                for p in parts_pair:
                    if p.upper() != "USD" and len(p) == 3:
                        return p.upper()
                # Both sides might be the same or both USD — return first
                return parts_pair[0].upper() if parts_pair[0] else ""
            # Plain 3-char code (e.g. "HKD", "JPY", "USD")
            if len(cp) <= 3:
                return cp.upper()

        return ""

    @classmethod
    def _derive_exchange(cls, ticker: str) -> str:
        """Derive exchange code from Bloomberg ticker suffix (e.g., '7203 JP Equity' → 'JP')."""
        parts = ticker.strip().split() if ticker else []
        if len(parts) >= 2:
            asset_types = ("EQUITY", "GOVT", "CORP", "COMDTY", "INDEX", "CURNCY", "PREF", "MTGE")
            return parts[-2].upper() if parts[-1].upper() in asset_types else parts[-1].upper()
        return ""

    def _parse_order_message(self, msg, seq: int) -> Optional[Order]:
        """Parse an OrderRouteFields subscription message into an Order."""
        try:
            symbol  = self._msg_safe_str(msg, "EMSX_TICKER")
            qty     = self._msg_safe_int(msg, "EMSX_AMOUNT")
            filled  = self._msg_safe_int(msg, "EMSX_FILLED")
            remain  = qty - filled

            # Side
            raw_side = self._msg_safe_str(msg, "EMSX_SIDE") or self._msg_safe_int(msg, "EMSX_SIDE")
            side = self.SIDE_MAP.get(raw_side, "BUY") if raw_side else "BUY"

            # Status
            raw_status = self._msg_safe_str(msg, "EMSX_STATUS") or self._msg_safe_int(msg, "EMSX_STATUS")
            raw_status_key = str(raw_status).upper() if isinstance(raw_status, str) else raw_status
            status = self.STATUS_MAP.get(raw_status_key, None)
            if status is None:
                logger.warning(f"Unmapped EMSX_STATUS '{raw_status}' for seq={seq} — defaulting to NEW")
                status = "NEW"

            # Order type
            raw_type = self._msg_safe_str(msg, "EMSX_ORDER_TYPE", "LMT").upper()
            order_type_map = {
                "MKT": "MARKET", "MARKET": "MARKET",
                "LMT": "LIMIT",  "LIMIT": "LIMIT",
                "STP": "STOP",   "STOP": "STOP",
                "STPLMT": "STOP_LIMIT",
            }
            order_type = order_type_map.get(raw_type, "LIMIT")

            raw_price  = self._msg_safe_float(msg, "EMSX_LIMIT_PRICE")
            price      = raw_price if raw_price > 0 else None
            avg_price  = self._msg_safe_float(msg, "EMSX_AVG_PRICE") or None
            stop_price = self._msg_safe_float(msg, "EMSX_STOP_PRICE") or None

            tif_raw = self._msg_safe_str(msg, "EMSX_TIF", "DAY").upper()
            tif_map = {"DAY": "DAY", "GTC": "GTC", "IOC": "IOC", "FOK": "FOK", "GTX": "GTX", "GTD": "GTD"}
            tif = tif_map.get(tif_raw, "DAY")

            account   = self._msg_safe_str(msg, "EMSX_ACCOUNT")
            portfolio = self._msg_safe_str(msg, "EMSX_PORT_NAME")
            trader    = self._msg_safe_str(msg, "EMSX_TRADER")
            notes    = self._msg_safe_str(msg, "EMSX_NOTES") or None
            currency_pair = self._msg_safe_str(msg, "EMSX_CURRENCY_PAIR")
            currency = self._derive_currency(currency_pair, symbol)
            logger.info(f"Order {seq}: CURRENCY_PAIR='{currency_pair}' ticker='{symbol}' -> currency='{currency}'")
            exchange = self._msg_safe_str(msg, "EMSX_EXCHANGE")
            # Derive exchange from ticker suffix when Bloomberg returns empty EMSX_EXCHANGE
            if not exchange and symbol:
                exchange = self._derive_exchange(symbol)
            logger.info(f"Order {seq}: EMSX_EXCHANGE='{self._msg_safe_str(msg, 'EMSX_EXCHANGE')}' -> exchange='{exchange}'")

            custom_note1 = self._msg_safe_str(msg, "EMSX_CUSTOM_NOTE1")
            custom_note2 = self._msg_safe_str(msg, "EMSX_CUSTOM_NOTE2")
            custom_note3 = self._msg_safe_str(msg, "EMSX_CUSTOM_NOTE3")
            custom_note4 = self._msg_safe_str(msg, "EMSX_CUSTOM_NOTE4")
            custom_note5 = self._msg_safe_str(msg, "EMSX_CUSTOM_NOTE5")
            trader_notes = self._msg_safe_str(msg, "EMSX_TRADER_NOTES")
            exec_instruction = self._msg_safe_str(msg, "EMSX_EXEC_INSTRUCTION")
            strategy_type = self._msg_safe_str(msg, "EMSX_STRATEGY_TYPE")
            strategy_style = self._msg_safe_str(msg, "EMSX_STRATEGY_STYLE")
            strategy_part_rate_raw = self._msg_safe_float(msg, "EMSX_STRATEGY_PART_RATE1")
            strategy_part_rate = strategy_part_rate_raw if strategy_part_rate_raw > 0 else None
            strategy_start_time_raw = self._msg_safe_int(msg, "EMSX_STRATEGY_START_TIME", 0)
            strategy_start_time = self._format_strategy_time(strategy_start_time_raw)
            strategy_end_time_raw = self._msg_safe_int(msg, "EMSX_STRATEGY_END_TIME", 0)
            strategy_end_time = self._format_strategy_time(strategy_end_time_raw)
            percent_remain = self._msg_safe_float(msg, "EMSX_PERCENT_REMAIN") or None
            broker = self._msg_safe_str(msg, "EMSX_BROKER")
            trader_uuid = self._msg_safe_int(msg, "EMSX_TRAD_UUID", 0)
            day_avg_price = self._msg_safe_float(msg, "EMSX_DAY_AVG_PRICE") or None
            arrival_price_raw = self._msg_safe_float(msg, "EMSX_ARRIVAL_PRICE")
            arrival_price = arrival_price_raw if arrival_price_raw > 0 else None
            last_price_raw = self._msg_safe_float(msg, "EMSX_LAST_PRICE")
            last_price = last_price_raw if last_price_raw > 0 else None

            # (Terminal trader identity is computed on-demand from the full orders cache)

            # Compute derived fields
            pct_filled = round((filled / qty) * 100, 1) if qty > 0 else 0.0
            if any([custom_note1, custom_note2, custom_note3, custom_note4, custom_note5, trader_notes, notes, exec_instruction, strategy_type]):
                logger.debug(f"Order {seq}: STRAT='{strategy_type}' STYLE='{strategy_style}' RATE={strategy_part_rate_raw} TIME={strategy_start_time}-{strategy_end_time} NOTES='{notes}'")

            # Date: EMSX_DATE is YYYYMMDD integer, EMSX_TIME_STAMP is seconds from midnight
            emsx_date = self._msg_safe_int(msg, "EMSX_DATE")
            created_at = datetime.now().isoformat()
            if emsx_date > 0:
                try:
                    y = emsx_date // 10000
                    m = (emsx_date % 10000) // 100
                    d = emsx_date % 100
                    ts = self._msg_safe_int(msg, "EMSX_TIME_STAMP", 0)
                    h = ts // 3600
                    mn = (ts % 3600) // 60
                    s = ts % 60
                    created_at = datetime(y, m, d, h, mn, s).isoformat()
                except Exception:
                    pass

            return Order(
                id=str(seq),
                symbol=symbol,
                side=side,
                status=status,
                orderType=order_type,
                quantity=qty,
                filledQuantity=filled,
                remainingQuantity=remain,
                price=price,
                stopPrice=stop_price,
                avgPrice=avg_price,
                timeInForce=tif,
                account=account,
                portfolio=portfolio,
                trader=trader,
                createdAt=created_at,
                updatedAt=created_at,
                notes=notes,
                currency=currency,
                exchange=exchange,
                customNote1=custom_note1,
                customNote2=custom_note2,
                customNote3=custom_note3,
                customNote4=custom_note4,
                customNote5=custom_note5,
                traderNotes=trader_notes,
                execInstruction=exec_instruction,
                percentRemain=percent_remain,
                percentFilled=pct_filled,
                strategyType=strategy_type,
                strategyPartRate=strategy_part_rate,
                strategyStyle=strategy_style,
                strategyStartTime=strategy_start_time,
                strategyEndTime=strategy_end_time,
                broker=broker,
                traderUuid=trader_uuid,
                dayAvgPrice=day_avg_price,
                arrivalPrice=arrival_price,
                lastPrice=last_price,
            )
        except Exception as e:
            logger.warning(f"Error parsing order message for seq={seq}: {e}")
            return None

    # ------------------------------------------------------------------
    # Real-time market data via //blp/mktdata subscriptions
    # ------------------------------------------------------------------
    # Unlike //blp/refdata (request/response, has DAILY_CAPACITY_REACHED limit),
    # //blp/mktdata uses streaming subscriptions with no daily capacity limit.
    # Data updates in real-time with every market tick — same as %Filled, Avg Px.
    # ------------------------------------------------------------------

    def _mktdata_subscription_loop(self):
        """Background thread: manage //blp/mktdata subscriptions and process updates.

        Subscribes to CHG_PCT_1D, VOLUME_AVG_5D, VWAP for all order tickers.
        FX rates are fetched via //blp/refdata every 5 min. Trading currencies via CRNCY refdata.
        Automatically adds new subscriptions when new tickers appear in the order cache.
        """
        sess = self._mktdata_session
        if not sess or not self._mktdata_connected:
            logger.warning("Mktdata session not available — market data enrichment disabled")
            return

        logger.info("Mktdata subscription loop started")
        self._fx_rates["USD"] = 1.0

        # Wait briefly for EMSX orders to populate before first subscription
        self._stop_event.wait(3)

        while not self._stop_event.is_set():
            try:
                self._update_mktdata_subscriptions(sess)
            except Exception as e:
                logger.warning(f"Error updating mktdata subscriptions: {e}")

            # Periodic FX rate refresh via //blp/refdata (every 5 min)
            try:
                self._maybe_refresh_fx_rates(sess)
            except Exception as e:
                logger.warning(f"Error refreshing FX rates: {e}")

            # Query //blp/refdata CRNCY for new tickers (authoritative currency source)
            try:
                self._maybe_query_ticker_currencies(sess)
            except Exception as e:
                logger.warning(f"Error querying ticker currencies: {e}")

            # Query //blp/refdata PX_ROUND_LOT_SIZE for new tickers (odd lot detection)
            try:
                self._maybe_query_round_lot_sizes(sess)
            except Exception as e:
                logger.warning(f"Error querying round lot sizes: {e}")

            # Process events from mktdata session
            try:
                event = sess.nextEvent(2000)
                etype = event.eventType()

                if etype == blpapi.Event.SUBSCRIPTION_DATA:
                    for msg in event:
                        try:
                            self._process_mktdata_message(msg)
                        except Exception as e:
                            logger.debug(f"Error processing mktdata message: {e}")

                elif etype == blpapi.Event.SUBSCRIPTION_STATUS:
                    batch_failures = []
                    batch_started = []
                    for msg in event:
                        mtype = str(msg.messageType())
                        cid_val = str(msg.correlationIds()[0].value()) if msg.correlationIds() else None
                        if "SubscriptionFailure" in mtype or "SubscriptionTerminated" in mtype:
                            if cid_val:
                                self._mktdata_failed_tickers.add(cid_val)
                                self._mktdata_active_tickers.discard(cid_val)
                            # Extract failure reason from Bloomberg API
                            failure_reason = ""
                            try:
                                if msg.hasElement("reason"):
                                    reason = msg.getElement("reason")
                                    if reason.hasElement("description"):
                                        failure_reason = str(reason.getElement("description").getValue())
                                    elif reason.hasElement("source"):
                                        failure_reason = str(reason.getElement("source").getValue())
                            except Exception:
                                pass
                            batch_failures.append((cid_val or "unknown", failure_reason))
                        elif "SubscriptionStarted" in mtype:
                            if cid_val:
                                self._mktdata_active_tickers.add(cid_val)
                                self._mktdata_failed_tickers.discard(cid_val)
                            batch_started.append(cid_val or "unknown")
                    # Batch-log to reduce noise
                    if batch_started:
                        logger.info(f"Mktdata subscriptions started: {len(batch_started)} ({batch_started[:5]}{'...' if len(batch_started) > 5 else ''})")
                    if batch_failures:
                        failure_details = [(t, r) for t, r in batch_failures[:3]]
                        logger.warning(f"Mktdata subscription failures: {len(batch_failures)} ({failure_details}). Will retry in {self._mktdata_retry_interval}s.")

                elif etype in (blpapi.Event.PARTIAL_RESPONSE, blpapi.Event.RESPONSE):
                    # Handle //blp/refdata responses (FX rate + CRNCY queries + Round Lot)
                    for msg in event:
                        try:
                            cid = msg.correlationIds()[0] if msg.correlationIds() else None
                            cid_val = str(cid.value()) if cid else ""
                            if cid_val == "__crncy_refdata__":
                                self._process_crncy_refdata_response(msg)
                            elif cid_val == "__round_lot_refdata__":
                                self._process_round_lot_refdata_response(msg)
                            else:
                                self._process_fx_refdata_response(msg)
                        except Exception as e:
                            logger.debug(f"Error processing refdata response: {e}")
                    if etype == blpapi.Event.RESPONSE:
                        self._fx_refdata_pending = False
                        self._crncy_refdata_pending = False

                elif etype == blpapi.Event.SESSION_STATUS:
                    for msg in event:
                        mtype = str(msg.messageType())
                        if "SessionTerminated" in mtype:
                            logger.error("Mktdata session terminated")
                            self._mktdata_connected = False
                            return

                elif etype == blpapi.Event.TIMEOUT:
                    pass  # normal

            except Exception as e:
                logger.debug(f"Mktdata event loop error: {e}")

        logger.info("Mktdata subscription loop stopped")

    def _update_mktdata_subscriptions(self, sess):
        """Add mktdata subscriptions for any new tickers in the order cache.
        FX rates are handled separately via hourly //blp/refdata requests.
        Also retries failed subscriptions periodically (e.g., after DAILY_CAPACITY_REACHED resets).
        """
        # Collect current tickers from order cache
        current_tickers = {o.symbol for o in self._orders.values() if o.symbol}
        
        # Diagnostic: Check specific tickers
        for check_ticker in ["UU/ LN Equity", "SVT LN Equity", "GLEN LN Equity"]:
            if check_ticker in current_tickers:
                in_subscribed = check_ticker in self._mktdata_subscribed_tickers
                in_failed = check_ticker in self._mktdata_failed_tickers
                logger.info(f"[MKTDATA CHECK] {check_ticker}: in_cache=True, subscribed={in_subscribed}, failed={in_failed}")

        new_tickers = current_tickers - self._mktdata_subscribed_tickers

        # Periodically retry failed subscriptions (capacity may have reset)
        now = datetime.now()
        retry_tickers: set = set()
        if self._mktdata_failed_tickers:
            if self._mktdata_last_retry is None or (now - self._mktdata_last_retry).total_seconds() >= self._mktdata_retry_interval:
                retry_tickers = self._mktdata_failed_tickers.copy()
                self._mktdata_last_retry = now
                if retry_tickers:
                    logger.info(f"Retrying {len(retry_tickers)} failed ticker subscriptions")

        all_new_tickers = new_tickers | retry_tickers

        if not all_new_tickers:
            return

        sub_list = blpapi.SubscriptionList()

        # Subscribe to market data fields for new equity tickers
        for ticker in all_new_tickers:
            cid = blpapi.CorrelationId(ticker)  # use ticker string as CID for easy lookup
            sub_list.add(
                topic=f"//blp/mktdata/{ticker}",
                fields=["CHG_PCT_1D", "VOLUME_AVG_5D", "VWAP", "PX_ROUND_LOT_SIZE"],
                correlationId=cid,
            )
        logger.info(f"Subscribing mktdata for {len(all_new_tickers)} tickers: {sorted(all_new_tickers)[:10]}{'...' if len(all_new_tickers) > 10 else ''}")
        self._mktdata_subscribed_tickers.update(all_new_tickers)

        try:
            sess.subscribe(sub_list)
            # Clear retried items from failed sets (will be re-added if they fail again)
            self._mktdata_failed_tickers -= retry_tickers
            # Initialize retry timer on first subscription to avoid immediate retry
            if self._mktdata_last_retry is None:
                self._mktdata_last_retry = now
        except Exception as e:
            logger.warning(f"Failed to subscribe mktdata: {e}")

    def _process_mktdata_message(self, msg):
        """Process a single //blp/mktdata subscription message and update caches."""
        cid = msg.correlationId()
        if not cid:
            return
        topic = cid.value()  # ticker string
        if not isinstance(topic, str):
            return

        # Equity market data message
        ticker = topic
        try:
            if msg.hasElement("CHG_PCT_1D"):
                val = msg.getElementAsFloat("CHG_PCT_1D")
                self._price_changes[ticker] = val
            if msg.hasElement("VOLUME_AVG_5D"):
                val = msg.getElementAsFloat("VOLUME_AVG_5D")
                self._adv5d[ticker] = val
            if msg.hasElement("VWAP"):
                val = msg.getElementAsFloat("VWAP")
                self._mkt_vwap[ticker] = val
            if msg.hasElement("PX_ROUND_LOT_SIZE"):
                val = msg.getElementAsInteger("PX_ROUND_LOT_SIZE")
                self._round_lot_sizes[ticker] = val
                # Debug logging for specific symbols
                debug_symbols = {"COST", "DE", "GEV", "RS", "ZS", "ROP", "ORCL", "MSTR", "INTU", 
                                "HUBS", "ADBE", "MPWR", "VRSN", "IT", "IBM", "ZBRA", "TDY", 
                                "MSI", "CHTR", "SPY", "AVGO", "PH", "ETN", "V", "PG", "WMT", "PEP", "KO", "XOM"}
                ticker_base = ticker.split()[0] if " " in ticker else ticker
                if ticker_base in debug_symbols:
                    logger.info(f"[ROUND_LOT_MKTDATA] {ticker}: PX_ROUND_LOT_SIZE = {val}")
                else:
                    logger.debug(f"[ROUND_LOT] {ticker}: PX_ROUND_LOT_SIZE = {val}")
        except Exception as e:
            logger.debug(f"Error parsing mktdata for {ticker}: {e}")

    # ------------------------------------------------------------------
    # FX rate refresh via //blp/refdata (every 5 minutes, per currency pair)
    # ------------------------------------------------------------------

    def _maybe_refresh_fx_rates(self, sess):
        """Send a //blp/refdata request for FX rates if due (every _fx_refresh_interval seconds).
        Requests BOTH {ccy}USD Curncy AND USD{ccy} Curncy for full coverage — some
        Bloomberg FX pairs only exist in one direction (e.g. USDKRW but not KRWUSD).
        """
        if not self._refdata_service_available or self._fx_refdata_pending:
            return
        now = datetime.now()
        if self._fx_last_refresh is not None and (now - self._fx_last_refresh).total_seconds() < self._fx_refresh_interval:
            return
        # Collect currencies from BOTH order.currency AND authoritative _ticker_currencies
        currencies: set = set()
        for o in self._orders.values():
            if o.currency and o.currency != "USD" and len(o.currency) == 3:
                currencies.add(o.currency)
        for ccy in self._ticker_currencies.values():
            if ccy and ccy != "USD" and len(ccy) == 3:
                currencies.add(ccy)
        if not currencies:
            return
        try:
            svc = sess.getService("//blp/refdata")
            req = svc.createRequest("ReferenceDataRequest")
            securities = req.getElement("securities")
            for ccy in sorted(currencies):
                securities.appendValue(f"{ccy}USD Curncy")   # e.g. AUDUSD Curncy
                securities.appendValue(f"USD{ccy} Curncy")   # e.g. USDKRW Curncy (inverse)
            fields = req.getElement("fields")
            fields.appendValue("PX_LAST")
            sess.sendRequest(req, correlationId=self._fx_refdata_cid)
            self._fx_refdata_pending = True
            self._fx_last_refresh = now
            logger.info(f"Sent FX refdata request for {len(currencies)} currencies: {sorted(currencies)}")
        except Exception as e:
            logger.warning(f"Failed to send FX refdata request: {e}")

    def _maybe_query_ticker_currencies(self, sess):
        """Query //blp/refdata CRNCY field for new tickers to get authoritative trading currency."""
        if not self._refdata_service_available or self._crncy_refdata_pending:
            return
        new_tickers = {o.symbol for o in self._orders.values() if o.symbol} - self._crncy_queried_tickers
        if not new_tickers:
            return
        try:
            svc = sess.getService("//blp/refdata")
            req = svc.createRequest("ReferenceDataRequest")
            securities = req.getElement("securities")
            for t in sorted(new_tickers):
                securities.appendValue(t)
            fields = req.getElement("fields")
            fields.appendValue("CRNCY")
            sess.sendRequest(req, correlationId=self._crncy_refdata_cid)
            self._crncy_refdata_pending = True
            self._crncy_queried_tickers |= new_tickers
            logger.info(f"Sent CRNCY refdata request for {len(new_tickers)} tickers")
        except Exception as e:
            logger.warning(f"Failed to send CRNCY refdata request: {e}")

    def _process_fx_refdata_response(self, msg):
        """Process a //blp/refdata response containing FX PX_LAST values.
        Handles both {ccy}USD Curncy (direct) and USD{ccy} Curncy (inverted) formats.
        
        Strategy: collect BOTH direct and inverse rates, then for each currency
        prefer the inverse rate (USD{ccy}) because Bloomberg's {ccy}USD Curncy
        returns per-100 or per-1000 rates for some EM currencies (KRW, IDR, etc.).
        USD{ccy} Curncy always returns the standard spot rate.
        """
        try:
            if not msg.hasElement("securityData"):
                return
            sd = msg.getElement("securityData")
            direct_rates = {}   # from {ccy}USD Curncy
            inverse_rates = {}  # from USD{ccy} Curncy → 1/rate
            for i in range(sd.numValues()):
                entry = sd.getValueAsElement(i)
                sec = entry.getElementAsString("security")  # e.g. "AUDUSD Curncy" or "USDKRW Curncy"
                if entry.hasElement("fieldData"):
                    fd = entry.getElement("fieldData")
                    if fd.hasElement("PX_LAST"):
                        rate = fd.getElementAsFloat("PX_LAST")
                        if rate > 0:
                            pair = sec.replace(" Curncy", "").strip()
                            # Direct format: {ccy}USD → e.g. "AUDUSD" (1 AUD = 0.71 USD)
                            if pair.endswith("USD") and len(pair) == 6:
                                ccy_code = pair[:3]
                                direct_rates[ccy_code] = rate
                            # Inverse format: USD{ccy} → e.g. "USDKRW" (1 USD = 1430 KRW)
                            elif pair.startswith("USD") and len(pair) == 6:
                                ccy_code = pair[3:]
                                inverse_rates[ccy_code] = 1.0 / rate
                else:
                    logger.debug(f"FX: no fieldData for {sec} (security may not exist)")
            
            # Merge: start with direct rates, then let inverse OVERRIDE
            # (inverse is more reliable for EM currencies like KRW, IDR)
            all_ccys = set(direct_rates.keys()) | set(inverse_rates.keys())
            updated = 0
            for ccy in all_ccys:
                if ccy in inverse_rates:
                    new_rate = inverse_rates[ccy]
                elif ccy in direct_rates:
                    new_rate = direct_rates[ccy]
                else:
                    continue
                old_rate = self._fx_rates.get(ccy)
                self._fx_rates[ccy] = new_rate
                updated += 1
                # Log discrepancies between direct and inverse
                if ccy in direct_rates and ccy in inverse_rates:
                    d, inv = direct_rates[ccy], inverse_rates[ccy]
                    ratio = d / inv if inv > 0 else 0
                    if abs(ratio - 1.0) > 0.02:  # >2% discrepancy
                        logger.warning(f"FX {ccy}: direct={d:.6f} vs inverse={inv:.6f} (ratio={ratio:.2f}x) — using inverse")
            
            if updated:
                logger.info(f"FX rates updated: {updated} currencies — {dict(sorted(self._fx_rates.items()))}")
        except Exception as e:
            logger.warning(f"Error processing FX refdata response: {e}")

    def _process_crncy_refdata_response(self, msg):
        """Process a //blp/refdata response containing CRNCY (trading currency) per ticker."""
        try:
            if not msg.hasElement("securityData"):
                return
            sd = msg.getElement("securityData")
            updated = 0
            for i in range(sd.numValues()):
                entry = sd.getValueAsElement(i)
                sec = entry.getElementAsString("security")
                if entry.hasElement("fieldData"):
                    fd = entry.getElement("fieldData")
                    if fd.hasElement("CRNCY"):
                        crncy = fd.getElementAsString("CRNCY").strip().upper()
                        if crncy and len(crncy) == 3:
                            old = self._ticker_currencies.get(sec)
                            self._ticker_currencies[sec] = crncy
                            # Also patch the order's currency in-place if it was wrong
                            for o in self._orders.values():
                                if o.symbol == sec and o.currency != crncy:
                                    logger.info(f"CRNCY override: order {o.id} ({sec}) currency '{o.currency}' → '{crncy}'")
                                    o.currency = crncy
                            updated += 1
            if updated:
                # Force an immediate FX rate refresh to cover newly-discovered currencies
                self._fx_last_refresh = None
                sample = dict(list(sorted(self._ticker_currencies.items()))[:10])
                logger.info(f"CRNCY updated: {updated} tickers (sample: {sample})")
        except Exception as e:
            logger.warning(f"Error processing CRNCY refdata response: {e}")

    def _maybe_query_round_lot_sizes(self, sess):
        """Query //blp/refdata PX_ROUND_LOT_SIZE field for new tickers (like BDP function).
        
        This fetches the round lot size once per ticker using ReferenceDataRequest,
        similar to the Excel formula =BDP("ticker","PX_ROUND_LOT_SIZE").
        The data is cached and not refreshed (assumed static for the trading day).
        """
        if not self._refdata_service_available:
            logger.warning("[ROUND_LOT] Skipping: refdata service not available")
            return
        if self._round_lot_refdata_pending:
            logger.debug("[ROUND_LOT] Skipping: previous request still pending")
            return
        
        # Get tickers from configured odd lot markets that haven't been queried yet
        target_tickers = set()
        odd_lot_markets = set(settings.ODD_LOT_MARKETS)
        for o in self._orders.values():
            if o.symbol and o.exchange and o.exchange.upper() in odd_lot_markets:
                if o.symbol not in self._round_lot_queried_tickers:
                    target_tickers.add(o.symbol)
        
        if target_tickers:
            logger.info(f"[ROUND_LOT] Found {len(target_tickers)} new tickers to query for markets {sorted(odd_lot_markets)} (total orders: {len(self._orders)}, queried: {len(self._round_lot_queried_tickers)})")
            sample = sorted(list(target_tickers))[:5]
            logger.info(f"[ROUND_LOT] Sample tickers to query: {sample}")
        elif len(self._orders) > 0 and len(self._round_lot_queried_tickers) == 0:
            # No target tickers but we have orders - log for debugging
            exchanges = {}
            for o in self._orders.values():
                exch = o.exchange or "None"
                exchanges[exch] = exchanges.get(exch, 0) + 1
            logger.info(f"[ROUND_LOT] No target tickers for markets {sorted(odd_lot_markets)}. Exchange distribution: {exchanges}")
        
        if not target_tickers:
            return
        
        # Limit batch size to avoid request too large
        batch_size = 50
        tickers_to_query = sorted(list(target_tickers))[:batch_size]
        
        try:
            svc = sess.getService("//blp/refdata")
            req = svc.createRequest("ReferenceDataRequest")
            securities = req.getElement("securities")
            for t in tickers_to_query:
                securities.appendValue(t)
            fields = req.getElement("fields")
            fields.appendValue("PX_ROUND_LOT_SIZE")
            sess.sendRequest(req, correlationId=self._round_lot_refdata_cid)
            self._round_lot_refdata_pending = True
            self._round_lot_queried_tickers.update(tickers_to_query)
            logger.info(f"Sent PX_ROUND_LOT_SIZE refdata request for {len(tickers_to_query)} tickers: {tickers_to_query[:5]}...")
        except Exception as e:
            logger.warning(f"Failed to send round lot refdata request: {e}")

    def _process_round_lot_refdata_response(self, msg):
        """Process a //blp/refdata response containing PX_ROUND_LOT_SIZE per ticker."""
        try:
            self._round_lot_refdata_pending = False
            if not msg.hasElement("securityData"):
                return
            sd = msg.getElement("securityData")
            updated = 0
            for i in range(sd.numValues()):
                entry = sd.getValueAsElement(i)
                sec = entry.getElementAsString("security")
                if entry.hasElement("fieldData"):
                    fd = entry.getElement("fieldData")
                    if fd.hasElement("PX_ROUND_LOT_SIZE"):
                        round_lot = fd.getElementAsInteger("PX_ROUND_LOT_SIZE")
                        if round_lot > 0:
                            self._round_lot_sizes[sec] = round_lot
                            updated += 1
                            logger.info(f"[ROUND_LOT_BDP] {sec}: PX_ROUND_LOT_SIZE = {round_lot}")
                    else:
                        # Field not available — mark as unknown (sentinel -1)
                        self._round_lot_sizes[sec] = -1
                        logger.info(f"[ROUND_LOT_BDP] {sec}: PX_ROUND_LOT_SIZE not available, marked as unknown")
                else:
                    # No field data — mark as unknown (sentinel -1)
                    self._round_lot_sizes[sec] = -1
                    logger.info(f"[ROUND_LOT_BDP] {sec}: No field data, marked as unknown")
            if updated:
                sample = dict(list(sorted(self._round_lot_sizes.items()))[:10])
                logger.info(f"PX_ROUND_LOT_SIZE updated: {updated} tickers (total cached: {len(self._round_lot_sizes)})")
        except Exception as e:
            logger.warning(f"Error processing PX_ROUND_LOT_SIZE refdata response: {e}")

    # ------------------------------------------------------------------
    # Request/response helpers (for ModifyOrder, CancelOrder, etc.)
    # ------------------------------------------------------------------

    @property
    def _req_service(self) -> Service:
        """Return the request-dedicated service (or fallback to shared service)."""
        svc = self._request_service or self.service
        if not svc:
            raise HTTPException(503, "Bloomberg service not available")
        return svc

    def _send_request(self, request: Request) -> List[Message]:
        """Send a synchronous EMSX request and collect all response messages.
        
        Uses the dedicated _request_session to avoid nextEvent() races
        with the subscription thread on the main session.
        """
        req_session = self._request_session or self.session
        if not req_session or not self.connected:
            raise HTTPException(503, "Bloomberg not connected")

        cid = blpapi.CorrelationId()
        req_session.sendRequest(request, correlationId=cid)

        messages: List[Message] = []
        timeout_ms = settings.BLOOMBERG_TIMEOUT
        deadline = datetime.now().timestamp() * 1000 + timeout_ms

        while True:
            remaining = max(0, int(deadline - datetime.now().timestamp() * 1000))
            event = req_session.nextEvent(remaining)
            etype = event.eventType()

            if etype in (Event.PARTIAL_RESPONSE, Event.RESPONSE):
                for msg in event:
                    messages.append(msg)
                if etype == Event.RESPONSE:
                    break
            elif etype == Event.TIMEOUT:
                raise HTTPException(504, "Bloomberg request timed out")
            # Ignore subscription events that arrive in this event loop

        return messages

    async def _send_request_async(self, request: Request) -> List[Message]:
        """Async wrapper for _send_request — runs in thread pool to avoid blocking the event loop."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._send_request, request)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_orders(self, filters: Optional[OrderFilters] = None) -> List[Order]:
        """Return orders from the live subscription cache.
        
        Thread-safe: uses _data_lock when accessing shared caches.
        """
        if not await self.connect():
            raise HTTPException(503, "Failed to connect to Bloomberg")

        # Wait for initial paint to complete — but only when the cache is truly empty.
        # Bloomberg does not always send EVENT_STATUS=11 (INIT_PAINT_END); once we have
        # orders in cache we treat the snapshot as done.
        if not self._init_paint_done:
            with self._data_lock:
                order_count = len(self._orders)
            if order_count > 0:
                # Already have orders — mark done without waiting
                self._init_paint_done = True
                logger.info(f"INIT_PAINT inferred complete — {order_count} orders in cache")
            else:
                logger.info("Waiting for EMSX INIT_PAINT to complete...")
                # INCREASED: From 30 iterations (15s) to 60 iterations (30s)
                # This ensures we capture all orders from large order books
                for _ in range(60):
                    await asyncio.sleep(0.5)
                    with self._data_lock:
                        has_orders = len(self._orders) > 0
                        current_count = len(self._orders)
                    if self._init_paint_done or has_orders or self._subscription_failed:
                        # Additional check: wait a bit more to ensure we get all orders
                        if has_orders and not self._init_paint_done:
                            logger.info(f"Orders arriving: {current_count} so far, waiting for more...")
                            # Wait 2 more seconds to capture any trailing orders
                            await asyncio.sleep(2.0)
                        break
                with self._data_lock:
                    order_count = len(self._orders)
                if order_count > 0 and not self._init_paint_done:
                    self._init_paint_done = True
                    logger.info(f"INIT_PAINT inferred complete — {order_count} orders in cache")
                if not self._init_paint_done and not self._subscription_failed:
                    logger.warning("INIT_PAINT not complete after 30s — returning partial snapshot")
            if self._subscription_failed:
                logger.warning("Subscription failed — returning stale/empty cache. Bloomberg EMSX may be reconnecting.")
                # Reset connected so next call triggers a fresh reconnect
                self.connected = False

        with self._data_lock:
            orders = list(self._orders.values())
        # Filter orders with a valid ticker (skip blank-symbol orphans from out-of-order updates)
        orders = [o for o in orders if o.symbol]
        logger.info(f"Returning {len(orders)} orders from subscription cache")

        # --- Diagnostic: log first 5 order currencies + CRNCY overrides ---
        for i, o in enumerate(orders[:5]):
            crncy = self._ticker_currencies.get(o.symbol, "?")
            logger.info(f"  order[{i}] id={o.id} symbol={o.symbol} derived_currency='{o.currency}' crncy_refdata='{crncy}'")

        # --- Diagnostic: log current FX rate cache ---
        fx_items = list(self._fx_rates.items())[:15]
        logger.info(f"  _fx_rates (first 15): {dict(fx_items)}")
        logger.info(f"  _ticker_currencies count: {len(self._ticker_currencies)}")

        # Enrichment data comes from real-time //blp/mktdata subscriptions — just read cached data.

        # Build order -> lastPrice map from route data (EMSX_LAST_PRICE is route-level only)
        # Thread-safe: copy routes data under lock
        order_last_prices: Dict[str, float] = {}
        with self._data_lock:
            routes_snapshot = list(self._routes.items())
        for rkey, route in routes_snapshot:
            if route.lastPrice and route.lastPrice > 0:
                seq_str = str(route.sequence)
                order_last_prices[seq_str] = route.lastPrice

        # Enrich orders: pctChange, adv5d, mktVwap, lastPrice, fxRate, dollarValueUsd
        enriched = []
        fx_miss_count = 0
        for o in orders:
            updates: dict = {}
            # Ensure exchange is derived from ticker if still empty
            if not o.exchange and o.symbol:
                updates["exchange"] = self._derive_exchange(o.symbol)
            pct = self._price_changes.get(o.symbol)
            if pct is not None:
                updates["pctChange"] = pct
            adv = self._adv5d.get(o.symbol)
            if adv is not None:
                updates["adv5d"] = adv
            vwap = self._mkt_vwap.get(o.symbol)
            if vwap is not None:
                updates["mktVwap"] = vwap
            
            # Diagnostic: Check specific orders
            if o.id in ("4880699", "4880700"):
                logger.info(f"[DEBUG {o.id}] symbol={o.symbol} cached_pctChange={o.pctChange} cached_adv5d={o.adv5d}")
                logger.info(f"[DEBUG {o.id}] _price_changes.has={o.symbol in self._price_changes} val={self._price_changes.get(o.symbol)}")
                logger.info(f"[DEBUG {o.id}] _adv5d.has={o.symbol in self._adv5d} val={self._adv5d.get(o.symbol)}")
                logger.info(f"[DEBUG {o.id}] updates.pctChange={'pctChange' in updates} updates.adv5d={'adv5d' in updates}")
            # Enrich lastPrice from route data (EMSX_LAST_PRICE is route-level only)
            lp = order_last_prices.get(o.id)
            if lp is not None:
                updates["lastPrice"] = lp
            effective_last = lp if lp is not None else o.lastPrice

            # ── Compute isOddLot for configured markets ───────────────────
            # Check if quantity is not a multiple of round lot size from Bloomberg PX_ROUND_LOT_SIZE
            # Markets are configured via ODD_LOT_MARKETS env variable (default: JP,US)
            odd_lot_markets = set(settings.ODD_LOT_MARKETS)
            if o.exchange and o.exchange.upper() in odd_lot_markets:
                round_lot = self._round_lot_sizes.get(o.symbol)
                if round_lot is not None and round_lot > 0:
                    is_odd = (o.quantity % round_lot) != 0
                    updates["isOddLot"] = is_odd
                else:
                    # Round lot size not found or unknown — leave as None
                    updates["isOddLot"] = None
            else:
                updates["isOddLot"] = False

            # ── Resolve AUTHORITATIVE trading currency ──────────────
            # Priority: 1) //blp/refdata CRNCY  2) order.currency from _derive_currency
            auth_ccy = self._ticker_currencies.get(o.symbol) or o.currency or ""
            # If the authoritative source disagrees with the order's stored currency, patch it
            if auth_ccy and auth_ccy != o.currency:
                updates["currency"] = auth_ccy

            # ── FX rate ─────────────────────────────────────────────
            fx_rate: Optional[float] = None
            if auth_ccy:
                if auth_ccy == "USD":
                    fx_rate = 1.0
                else:
                    fx_rate = self._fx_rates.get(auth_ccy)
                if fx_rate is not None:
                    updates["fxRate"] = round(fx_rate, 6) if fx_rate != 1.0 else 1.0

            # --- Diagnostic: validate FX rate for non-USD orders ---
            if auth_ccy and auth_ccy != "USD" and fx_rate is None:
                fx_miss_count += 1
                if fx_miss_count <= 3:
                    logger.warning(f"FX MISS: order {o.id} symbol={o.symbol} auth_ccy='{auth_ccy}' stored_ccy='{o.currency}' _fx_rates has {list(self._fx_rates.keys())}")

            # ── $Value = price × quantity × fxRate → USD ────────────
            # Always compute using the best available price and FX rate.
            # If FX rate is unavailable for a non-USD instrument, skip (leave null)
            # rather than report a misleading local-currency value.
            # NOTE: Use vwap from updates (enriched mktVwap) not o.mktVwap (original)
            effective_vwap = vwap if vwap is not None else o.mktVwap
            best_price = (
                effective_vwap if (effective_vwap and effective_vwap > 0) else
                effective_last if (effective_last and effective_last > 0) else
                o.avgPrice if (o.avgPrice and o.avgPrice > 0) else
                o.price if (o.price and o.price > 0) else
                None
            )
            if best_price and o.quantity > 0:
                if auth_ccy == "USD" or not auth_ccy:
                    # USD instrument or unknown currency — assume USD
                    updates["dollarValueUsd"] = round(best_price * o.quantity, 0)
                elif fx_rate is not None and fx_rate > 0:
                    # Non-USD with valid FX rate — convert to USD
                    # Special handling: GBP and ZAR require division by 100
                    if auth_ccy in ("GBP", "ZAR"):
                        updates["dollarValueUsd"] = round(best_price * o.quantity * fx_rate / 100, 0)
                    else:
                        updates["dollarValueUsd"] = round(best_price * o.quantity * fx_rate, 0)
                # else: non-USD with no FX rate → leave dollarValueUsd as null (NOT local ccy!)

            enriched_order = o.model_copy(update=updates) if updates else o
            enriched.append(enriched_order)
        
        # Save enriched data back to cache so future updates preserve calculated values
        # Thread-safe: batch update under lock
        with self._data_lock:
            for order in enriched:
                self._orders[order.id] = order
        orders = enriched

        if fx_miss_count > 0:
            logger.warning(f"FX rate missing for {fx_miss_count} non-USD orders out of {len(orders)} total")

        # Client-side filtering
        if filters:
            if filters.symbol:
                sym = filters.symbol.upper()
                orders = [o for o in orders if sym in o.symbol.upper()]
            if filters.side:
                orders = [o for o in orders if o.side == filters.side]
            if filters.status:
                orders = [o for o in orders if o.status == filters.status]
            if filters.orderType:
                orders = [o for o in orders if o.orderType == filters.orderType]
            if filters.portfolio:
                port = filters.portfolio.upper()
                orders = [o for o in orders if port in o.portfolio.upper()]
            if filters.trader:
                orders = [o for o in orders if filters.trader.upper() in o.trader.upper()]
            if filters.exchange:
                ex = filters.exchange.upper()
                orders = [o for o in orders if o.exchange and ex in o.exchange.upper()]
            if filters.currency:
                cur = filters.currency.upper()
                orders = [o for o in orders if cur in o.currency.upper()]
            if filters.oddLot is not None:
                # Odd lot detection: for configured markets
                # Uses PX_ROUND_LOT_SIZE from Bloomberg mktdata
                # Odd lot = quantity is NOT a multiple of round lot size
                def is_odd_lot(order) -> bool:
                    # Only apply to configured odd lot markets
                    odd_lot_mkts = set(settings.ODD_LOT_MARKETS)
                    if not order.exchange or order.exchange.upper() not in odd_lot_mkts:
                        return False
                    # Get round lot size from cache; skip if not available
                    round_lot = self._round_lot_sizes.get(order.symbol)
                    if round_lot is None or round_lot <= 0:
                        return False  # Cannot determine — exclude from odd lot filter
                    # Odd lot: quantity is not a multiple of round lot size
                    return (order.quantity % round_lot) != 0
                
                orders = [o for o in orders if is_odd_lot(o) == filters.oddLot]

        return orders

    async def get_routes(self) -> List[dict]:
        """Return routes from the live subscription cache.
        
        Thread-safe: uses _data_lock when accessing shared caches.
        """
        if not await self.connect():
            raise HTTPException(503, "Failed to connect to Bloomberg")

        # Wait for route init paint (similar to order logic)
        if not self._route_init_paint_done:
            with self._data_lock:
                route_count = len(self._routes)
            if route_count > 0:
                self._route_init_paint_done = True
                logger.info(f"Route INIT_PAINT inferred complete — {route_count} routes in cache")
            else:
                logger.info("Waiting for Route INIT_PAINT to complete...")
                for _ in range(30):
                    await asyncio.sleep(0.5)
                    with self._data_lock:
                        has_routes = len(self._routes) > 0
                    if self._route_init_paint_done or has_routes:
                        break
                with self._data_lock:
                    route_count = len(self._routes)
                if route_count > 0 and not self._route_init_paint_done:
                    self._route_init_paint_done = True

        # Thread-safe: copy data under lock
        with self._data_lock:
            routes = list(self._routes.values())
            orders_snapshot = dict(self._orders)  # shallow copy for lookup
        logger.info(f"Returning {len(routes)} routes from subscription cache")

        # Enrich routes with parent order ticker & side from order cache
        enriched = []
        logger.info(f"Enriching {len(routes)} routes, orders cache has {len(orders_snapshot)} orders")
        for r in routes:
            r_dict = r.model_dump()
            parent = orders_snapshot.get(str(r.sequence))
            if parent:
                # Use cached values on route if available, otherwise from parent
                # This preserves values even when parent temporarily unavailable
                r_dict["ticker"] = r.ticker or parent.symbol or ""
                r_dict["side"] = r.side or parent.side or ""
                r_dict["portfolio"] = r.portfolio or parent.portfolio or ""
                r_dict["trader"] = r.trader or parent.trader or ""
                r_dict["traderUuid"] = r.traderUuid if r.traderUuid else parent.traderUuid
                r_dict["currency"] = r.currency or parent.currency or ""
                # Use parent order's exchange, derive from ticker as fallback
                r_dict["exchange"] = r.exchange or parent.exchange or self._derive_exchange(r_dict["ticker"]) or ""
                logger.info(f"Enrich route {r.id}: parent seq={r.sequence}, "
                           f"route.ticker='{r.ticker}'->'{r_dict['ticker']}', "
                           f"route.exchange='{r.exchange}'->'{r_dict['exchange']}'")
            else:
                # Parent not in cache - use route's cached values if available
                if r.ticker:
                    # Route has cached enrichment data, use it
                    logger.debug(f"Enrich route {r.id}: using cached values, ticker='{r.ticker}', exchange='{r.exchange}'")
                else:
                    # No cached data available - log warning
                    logger.warning(f"Enrich route {r.id}: no parent order found for seq={r.sequence} and no cached values")
                # Ensure all enrichment fields have at least empty string values
                r_dict["ticker"] = r.ticker or ""
                r_dict["side"] = r.side or ""
                r_dict["portfolio"] = r.portfolio or ""
                r_dict["trader"] = r.trader or ""
                r_dict["traderUuid"] = r.traderUuid or 0
                r_dict["currency"] = r.currency or ""
                r_dict["exchange"] = r.exchange or ""
            enriched.append(r_dict)
        return enriched

    async def modify_order(self, order_id: str, field: str, value: Any) -> bool:
        """Modify a single EMSX order field via ModifyOrderEx request.
        
        Thread-safe: uses _data_lock when accessing order cache.
        """
        if not await self.connect():
            raise HTTPException(503, "Bloomberg not connected")

        try:
            request = self._req_service.createRequest("ModifyOrderEx")
            request.set("EMSX_SEQUENCE", int(order_id))

            # ModifyOrderEx requires mandatory fields — try to read from cache
            with self._data_lock:
                cached = self._orders.get(order_id)
            if cached:
                request.set("EMSX_TICKER", cached.symbol)
                request.set("EMSX_AMOUNT", cached.quantity)
                request.set("EMSX_ORDER_TYPE", {"MARKET": "MKT", "LIMIT": "LMT", "STOP": "STP"}.get(cached.orderType, "LMT"))
                request.set("EMSX_TIF", cached.timeInForce)

            if field == "price":
                request.set("EMSX_LIMIT_PRICE", float(value))
            elif field == "quantity":
                request.set("EMSX_AMOUNT", int(value))
            elif field == "timeInForce":
                request.set("EMSX_TIF", str(value))
            else:
                raise ValueError(f"Unsupported field: {field}")

            messages = await self._send_request_async(request)
            for msg in messages:
                if "Error" in str(msg.messageType()):
                    raise HTTPException(400, self._msg_safe_str(msg, "ERROR_MESSAGE", "Modify rejected"))

            logger.info(f"Modified order {order_id}: {field}={value}")
            return True

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error modifying order {order_id}: {e}")
            raise HTTPException(500, f"Failed to modify order: {str(e)}")

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an EMSX order via CancelOrderEx request."""
        if not await self.connect():
            raise HTTPException(503, "Bloomberg not connected")

        try:
            request = self._req_service.createRequest("CancelOrderEx")
            request.getElement("EMSX_SEQUENCE").appendValue(int(order_id))

            messages = await self._send_request_async(request)
            for msg in messages:
                if "Error" in str(msg.messageType()):
                    raise HTTPException(400, self._msg_safe_str(msg, "ERROR_MESSAGE", "Cancel rejected"))

            logger.info(f"Cancelled order {order_id}")
            return True

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error cancelling order {order_id}: {e}")
            raise HTTPException(500, f"Failed to cancel order: {str(e)}")

    async def batch_update(self, request_data: BatchUpdateRequest) -> BatchUpdateResponse:
        """Batch update multiple orders."""
        updated = 0
        failed = []

        for order_id in request_data.orderIds:
            try:
                if request_data.field == "status" and request_data.value == "CANCELLED":
                    await self.cancel_order(order_id)
                else:
                    await self.modify_order(order_id, request_data.field, request_data.value)
                updated += 1
            except HTTPException as e:
                failed.append({"orderId": order_id, "reason": e.detail})
            except Exception as e:
                failed.append({"orderId": order_id, "reason": str(e)})
        
        success = len(failed) == 0
        message = f"Updated {updated} orders"
        if failed:
            message += f", {len(failed)} failed"
        
        logger.info(f"Batch update complete: {message}")
        
        return BatchUpdateResponse(
            success=success,
            updatedCount=updated,
            failedOrders=failed if failed else None,
            message=message
        )

    async def cancel_route(self, request_data: CancelRouteRequest) -> bool:
        """Cancel an EMSX route via CancelRouteEx request."""
        if not await self.connect():
            raise HTTPException(503, "Bloomberg not connected")

        try:
            request = self._req_service.createRequest("CancelRouteEx")
            request.set("EMSX_SEQUENCE", request_data.sequence)
            request.set("EMSX_ROUTE_ID", request_data.routeId)

            messages = await self._send_request_async(request)
            for msg in messages:
                if "Error" in str(msg.messageType()):
                    raise HTTPException(400, self._msg_safe_str(msg, "ERROR_MESSAGE", "Cancel route rejected"))

            logger.info(f"Cancelled route {request_data.routeId} for order {request_data.sequence}")
            return True

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error cancelling route {request_data.routeId}: {e}")
            raise HTTPException(500, f"Failed to cancel route: {str(e)}")

    async def modify_route(self, request_data: ModifyRouteRequest) -> bool:
        """Modify an EMSX route via ModifyRouteEx request.
        
        Thread-safe: uses _data_lock when accessing route cache.
        """
        if not await self.connect():
            raise HTTPException(503, "Bloomberg not connected")

        try:
            request = self._req_service.createRequest("ModifyRouteEx")
            request.set("EMSX_SEQUENCE", request_data.sequence)
            request.set("EMSX_ROUTE_ID", request_data.routeId)

            # Required fields - use current values from cache if not provided
            route_key = f"{request_data.sequence}.{request_data.routeId}"
            with self._data_lock:
                cached = self._routes.get(route_key)

            # Set amount (required)
            if request_data.amount is not None:
                request.set("EMSX_AMOUNT", request_data.amount)
            elif cached:
                request.set("EMSX_AMOUNT", cached.amount)
            else:
                raise HTTPException(400, "Amount is required for route modification")

            # Set order type (required)
            order_type = request_data.orderType or (cached.orderType if cached else "")
            if order_type:
                request.set("EMSX_ORDER_TYPE", order_type)
            else:
                raise HTTPException(400, "Order type is required for route modification")

            # Set TIF (required)
            tif = request_data.tif or (cached.tif if cached else "DAY")
            request.set("EMSX_TIF", tif)

            # Optional fields
            if request_data.limitPrice is not None:
                request.set("EMSX_LIMIT_PRICE", request_data.limitPrice)
            if request_data.stopPrice is not None:
                request.set("EMSX_STOP_PRICE", request_data.stopPrice)
            if request_data.broker:
                request.set("EMSX_BROKER", request_data.broker)
            if request_data.exchangeDestination:
                request.set("EMSX_EXCHANGE_DESTINATION", request_data.exchangeDestination)
            if request_data.notes:
                request.set("EMSX_NOTES", request_data.notes)

            # Strategy params — set EMSX_STRATEGY_PARAMS with proper field indicators
            if request_data.strategyParams:
                strategy_name = request_data.strategyParams.get("strategyName", "")
                fields_data = request_data.strategyParams.get("fields", [])
                if strategy_name and isinstance(fields_data, list):
                    strategy = request.getElement("EMSX_STRATEGY_PARAMS")
                    strategy.setElement("EMSX_STRATEGY_NAME", strategy_name)

                    indicator = strategy.getElement("EMSX_STRATEGY_FIELD_INDICATORS")
                    data = strategy.getElement("EMSX_STRATEGY_FIELDS")

                    for field_entry in fields_data:
                        value = field_entry.get("value", "")
                        disabled = field_entry.get("disabled", False)
                        data.appendElement().setElement("EMSX_FIELD_DATA", str(value) if not disabled else "")
                        indicator.appendElement().setElement("EMSX_FIELD_INDICATOR", 1 if disabled else 0)

            messages = await self._send_request_async(request)
            for msg in messages:
                if "Error" in str(msg.messageType()):
                    raise HTTPException(400, self._msg_safe_str(msg, "ERROR_MESSAGE", "Modify route rejected"))

            logger.info(f"Modified route {request_data.routeId} for order {request_data.sequence}")
            return True

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error modifying route {request_data.routeId}: {e}")
            raise HTTPException(500, f"Failed to modify route: {str(e)}")

    async def route_order(self, request_data: RouteOrderRequest) -> dict:
        """Route an order via RouteEx request.
        
        Creates a child route from a parent order for execution by a broker.
        Validates order status and trader ownership before routing.
        """
        logger.info(f"Routing order {request_data.orderId} to broker {request_data.broker}")
        if not await self.connect():
            raise HTTPException(503, "Bloomberg not connected")

        try:
            # Get parent order details
            with self._data_lock:
                parent_order = self._orders.get(request_data.orderId)
            
            if not parent_order:
                raise HTTPException(404, f"Order {request_data.orderId} not found")
            
            # Validate order status — only certain statuses are routable
            routable_statuses = {"NEW", "ASSIGN", "WORKING", "PARTIAL", "SENT", "QUEUED"}
            if parent_order.status not in routable_statuses:
                raise HTTPException(400, f"Order {request_data.orderId} has status '{parent_order.status}' — only orders with status {', '.join(sorted(routable_statuses))} can be routed")

            # Validate trader ownership — the current terminal trader must match the order's trader
            terminal_trader = self.get_terminal_trader_name()
            if terminal_trader and parent_order.trader and terminal_trader.upper() != parent_order.trader.upper():
                raise HTTPException(403, f"Cannot route order {request_data.orderId}: assigned to trader '{parent_order.trader}', but current trader is '{terminal_trader}'")

            # Validate remaining quantity
            if request_data.quantity > parent_order.remainingQuantity:
                raise HTTPException(400, f"Route quantity ({request_data.quantity}) exceeds remaining quantity ({parent_order.remainingQuantity})")

            # Create RouteEx request
            request = self._req_service.createRequest("RouteEx")
            
            # Mandatory fields
            request.set("EMSX_SEQUENCE", int(request_data.orderId))
            request.set("EMSX_TICKER", parent_order.symbol)
            request.set("EMSX_BROKER", request_data.broker)
            request.set("EMSX_AMOUNT", request_data.quantity)
            request.set("EMSX_ORDER_TYPE", request_data.orderType[:3].upper())  # LMT, MKT, STP
            request.set("EMSX_TIF", request_data.timeInForce)
            request.set("EMSX_HAND_INSTRUCTION", "ANY")
            
            # Optional fields
            if request_data.price is not None:
                request.set("EMSX_LIMIT_PRICE", request_data.price)
            if request_data.stopPrice is not None:
                request.set("EMSX_STOP_PRICE", request_data.stopPrice)
            if request_data.exchangeDestination:
                request.set("EMSX_EXCHANGE_DESTINATION", request_data.exchangeDestination)
            if request_data.notes:
                request.set("EMSX_NOTES", request_data.notes)

            messages = await self._send_request_async(request)
            
            route_id = None
            for msg in messages:
                if "Error" in str(msg.messageType()):
                    raise HTTPException(400, self._msg_safe_str(msg, "ERROR_MESSAGE", "Route order rejected"))
                # Extract route ID from response if available
                if msg.hasElement("EMSX_ROUTE_ID"):
                    route_id = msg.getElementAsInteger("EMSX_ROUTE_ID")

            logger.info(f"Created route for order {request_data.orderId} to broker {request_data.broker}, route_id: {route_id}")
            return {
                "success": True,
                "orderId": request_data.orderId,
                "routeId": route_id,
                "broker": request_data.broker,
                "quantity": request_data.quantity,
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error routing order {request_data.orderId}: {e}")
            raise HTTPException(500, f"Failed to route order: {str(e)}")

    async def get_broker_strategies(self, broker: str, asset_class: str = "EQTY") -> List[str]:
        """Get available strategies for a broker via GetBrokerStrategiesWithAssetClass."""
        logger.info(f"Getting broker strategies for {broker} ({asset_class})")
        if not await self.connect():
            logger.error(f"Bloomberg not connected - cannot get strategies for {broker}")
            raise HTTPException(503, f"Bloomberg not connected - last error: {self.last_error or 'Unknown'}")

        try:
            request = self._req_service.createRequest("GetBrokerStrategiesWithAssetClass")
            request.set("EMSX_BROKER", broker)
            request.set("EMSX_ASSET_CLASS", asset_class)

            messages = await self._send_request_async(request)
            strategies = []
            for msg in messages:
                if msg.hasElement("EMSX_STRATEGIES"):
                    strats_elem = msg.getElement("EMSX_STRATEGIES")
                    for i in range(strats_elem.numValues()):
                        strategies.append(strats_elem.getValueAsString(i))
                elif "Error" in str(msg.messageType()):
                    error_msg = self._msg_safe_str(msg, "ERROR_MESSAGE", "Failed to get broker strategies")
                    logger.warning(f"GetBrokerStrategies error for {broker}: {error_msg}")

            logger.info(f"Broker {broker} ({asset_class}): {len(strategies)} strategies found")
            return strategies

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting broker strategies for {broker}: {e}")
            raise HTTPException(500, f"Failed to get broker strategies: {str(e)}")

    async def get_broker_strategy_info(self, broker: str, strategy: str, asset_class: str = "EQTY") -> List[dict]:
        """Get strategy parameter info via GetBrokerStrategyInfoWithAssetClass."""
        logger.info(f"Getting strategy info for {broker}/{strategy} ({asset_class})")
        if not await self.connect():
            logger.error(f"Bloomberg not connected - cannot get strategy info for {broker}/{strategy}")
            raise HTTPException(503, f"Bloomberg not connected - last error: {self.last_error or 'Unknown'}")

        try:
            request = self._req_service.createRequest("GetBrokerStrategyInfoWithAssetClass")
            request.set("EMSX_BROKER", broker)
            request.set("EMSX_STRATEGY", strategy)
            request.set("EMSX_ASSET_CLASS", asset_class)
            
            logger.info(f"Sending GetBrokerStrategyInfoWithAssetClass request for {broker}/{strategy}")
            import time
            start_time = time.time()
            
            messages = await self._send_request_async(request)
            
            elapsed = time.time() - start_time
            logger.info(f"GetBrokerStrategyInfoWithAssetClass response received in {elapsed:.2f}s")
            
            fields = []
            for msg in messages:
                if msg.hasElement("EMSX_STRATEGY_INFO"):
                    info_elem = msg.getElement("EMSX_STRATEGY_INFO")
                    for i in range(info_elem.numValues()):
                        entry = info_elem.getValueAsElement(i)
                        field_name = entry.getElementAsString("FieldName") if entry.hasElement("FieldName") else ""
                        disable = entry.getElementAsString("Disable") if entry.hasElement("Disable") else "0"
                        string_value = entry.getElementAsString("StringValue") if entry.hasElement("StringValue") else ""
                        fields.append({
                            "fieldName": field_name,
                            "disable": disable,
                            "stringValue": string_value,
                        })
                elif "Error" in str(msg.messageType()):
                    error_msg = self._msg_safe_str(msg, "ERROR_MESSAGE", "Failed to get strategy info")
                    logger.warning(f"GetBrokerStrategyInfo error for {broker}/{strategy}: {error_msg}")

            logger.info(f"Broker {broker} strategy {strategy} ({asset_class}): {len(fields)} parameter fields")
            return fields

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting strategy info for {broker}/{strategy}: {e}")
            raise HTTPException(500, f"Failed to get broker strategy info: {str(e)}")

    async def get_brokers(self, asset_class: str = "EQTY") -> List[str]:
        """Get available brokers for an asset class via GetBrokersWithAssetClass."""
        logger.info(f"Getting brokers for asset class {asset_class}")
        if not await self.connect():
            logger.error(f"Bloomberg not connected - cannot get brokers")
            raise HTTPException(503, f"Bloomberg not connected - last error: {self.last_error or 'Unknown'}")

        try:
            request = self._req_service.createRequest("GetBrokersWithAssetClass")
            request.set("EMSX_ASSET_CLASS", asset_class)

            messages = await self._send_request_async(request)
            brokers = []
            for msg in messages:
                if msg.hasElement("EMSX_BROKERS"):
                    brokers_elem = msg.getElement("EMSX_BROKERS")
                    for i in range(brokers_elem.numValues()):
                        brokers.append(brokers_elem.getValueAsString(i))
                elif "Error" in str(msg.messageType()):
                    error_msg = self._msg_safe_str(msg, "ERROR_MESSAGE", "Failed to get brokers")
                    logger.warning(f"GetBrokers error: {error_msg}")

            logger.info(f"Found {len(brokers)} brokers for asset class {asset_class}")
            return brokers

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting brokers: {e}")
            raise HTTPException(500, f"Failed to get brokers: {str(e)}")

    def get_terminal_trader_name(self) -> str:
        """Return the terminal trader name.
        Priority: 1) EMSX_TRADER_NAME from config, 2) most common trader in order cache."""
        if settings.EMSX_TRADER_NAME:
            return settings.EMSX_TRADER_NAME
        # Fallback: most common trader in order cache (may be inaccurate on shared desks)
        votes: Dict[str, int] = {}
        for order in self._orders.values():
            t = order.trader
            if t:
                votes[t] = votes.get(t, 0) + 1
        if votes:
            best = max(votes, key=votes.get)
            logger.debug(f"Auto-detected trader (fallback): {best} with {votes[best]} orders")
            return best
        return ""

# Global Bloomberg service instance
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
    """Log trading action for audit"""
    if settings.ENABLE_AUDIT_LOG:
        logger.info(f"AUDIT: {action} | User: {user} | Details: {json.dumps(details)}")

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
    logger.info("=" * 60)
    
    # Try to connect to Bloomberg
    connected = await bloomberg_service.connect()
    if not connected:
        logger.warning("Could not connect to Bloomberg on startup - will retry on first request")
    
    yield
    
    # Shutdown
    logger.info("Shutting down EMSX Trading API...")
    bloomberg_service.disconnect()

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
    return ApiResponse(
        success=bb_status.status == "connected",
        data=bb_status.model_dump(),
        message="Service is healthy" if bb_status.status == "connected" else bb_status.message
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
    """WebSocket connection manager"""
    def __init__(self):
        self.active_connections: List[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket client connected. Total: {len(self.active_connections)}")
    
    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"WebSocket client disconnected. Total: {len(self.active_connections)}")
    
    async def broadcast(self, message: dict):
        """Broadcast message to all connected clients"""
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.append(connection)
        
        # Clean up disconnected clients
        for conn in disconnected:
            self.disconnect(conn)

manager = ConnectionManager()

@app.websocket("/ws/orders")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time order updates"""
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive and handle client messages
            data = await websocket.receive_text()
            message = json.loads(data)
            
            if message.get("action") == "ping":
                await websocket.send_json({"type": "pong", "timestamp": datetime.now().isoformat()})
            
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(websocket)

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
