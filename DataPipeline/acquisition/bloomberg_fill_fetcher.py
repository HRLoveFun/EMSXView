"""
Bloomberg EMSX Fill Fetcher — blpapi-based fill data retrieval.

Handles the low-level Bloomberg EMSX History API communication:
  - Session management (connect, disconnect, reconnect on timeout)
  - Fill request creation (GetFills, scope: TradingSystem)
  - Response parsing with field extraction
  - Retry with exponential backoff on transient failures

Extracted from DataPipeline.ingestion.fill_fetch (2026-05-11).
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import blpapi

from DataPipeline.acquisition._constants import (
    GET_FILLS_RESPONSE,
    ERROR_INFO,
    ERROR_RESPONSE,
    FILL_FIELD_EXTRACTORS,
)

logger = logging.getLogger(__name__)

EMSX_HISTORY_SERVICE = "//blp/emsx.history"
DEFAULT_HOST = "localhost"
DEFAULT_PORT = 8194


# ── Custom Exceptions ──────────────────────────────────────────────────────

class EMSXSessionError(Exception):
    """Bloomberg session could not be started."""

class EMSXServiceError(Exception):
    """Bloomberg service could not be opened."""

class EMSXRequestError(Exception):
    """Bloomberg request returned an error or timed out."""


# ── Parse Helpers ──────────────────────────────────────────────────────────

def _parse_fill_messages(msg) -> List[Dict[str, Any]]:
    """Parse GetFillsResponse message into a list of fill dicts.

    The message contains a single ``Fills`` array element. Each fill
    in the array is parsed using the field names in
    ``FILL_FIELD_EXTRACTORS`` via ``getElementAsString`` /
    ``getElementAsInteger`` / ``getElementAsFloat`` as appropriate.
    """
    getter_map = {
        "getElementAsString": lambda e, f: e.getElementAsString(f),
        "getElementAsInteger": lambda e, f: e.getElementAsInteger(f),
        "getElementAsFloat": lambda e, f: e.getElementAsFloat(f),
    }
    fills_out: List[Dict[str, Any]] = []
    fills_el = msg.getElement("Fills")
    for i in range(fills_el.numValues()):
        fill_el = fills_el.getValueAsElement(i)
        fill: Dict[str, Any] = {}
        for field, getter_name in FILL_FIELD_EXTRACTORS.items():
            try:
                getter = getter_map[getter_name]
                value = getter(fill_el, field)
                fill[field] = value
            except Exception:
                fill[field] = None
        fills_out.append(fill)
    return fills_out


# ── Bloomberg Fill Fetcher ───────────────────────────────────────────────

class BloombergFillFetcher:
    """EMSX History fill fetcher using blpapi.

    Manages a Bloomberg session, sends GetFills requests, and parses
    responses with retry logic for transient failures.
    """

    def __init__(self, host: str = None, port: int = None,
                 max_retries: int = 2, event_timeout_ms: int = 30000):
        self.host = host or os.getenv('BLOOMBERG_HOST', DEFAULT_HOST)
        self.port = port or int(os.getenv('BLOOMBERG_PORT', str(DEFAULT_PORT)))
        self.use_uat = os.getenv('USE_UAT', 'false').lower() == 'true'
        self.service_name = self._resolve_service()
        self.max_retries = max_retries
        self.event_timeout_ms = event_timeout_ms
        self._session: Optional[blpapi.Session] = None
        self._connected = False

    def _resolve_service(self) -> str:
        if self.use_uat:
            return os.getenv('EMSX_HISTORY_SERVICE_UAT', '//blp/emsx.history.uat')
        return os.getenv('EMSX_HISTORY_SERVICE', EMSX_HISTORY_SERVICE)

    def connect(self) -> bool:
        """Connect to Bloomberg EMSX service."""
        session_options = blpapi.SessionOptions()
        session_options.setServerHost(self.host)
        session_options.setServerPort(self.port)
        logger.info(f"Connecting to {self.host}:{self.port}")
        self._session = blpapi.Session(session_options)
        if not self._session.start():
            raise EMSXSessionError(f"Failed to start Bloomberg session on {self.host}:{self.port}")
        if not self._session.openService(self.service_name):
            self._session.stop()
            self._session = None
            raise EMSXServiceError(f"Failed to open service {self.service_name}")
        self._connected = True
        logger.info(f"Connected to {self.service_name}")
        return True

    def disconnect(self):
        """Disconnect from Bloomberg."""
        if self._session:
            self._session.stop()
            self._session = None
        self._connected = False
        logger.info("Disconnected from Bloomberg")

    def _ensure_connected(self):
        if not self._connected or self._session is None:
            raise RuntimeError("Not connected to Bloomberg. Call connect() first.")

    def fetch_fills(self, from_date: datetime, to_date: datetime) -> List[Dict[str, Any]]:
        """Fetch fills from Bloomberg EMSX history with retry logic.

        Uses ``nextEvent(timeout_ms)`` internally. After consecutive TIMEOUT
        events the call reconnects the Bloomberg session to clear bbcomm backlog.
        """
        self._ensure_connected()
        last_error: Exception = EMSXRequestError("No fetch attempts made")
        for attempt in range(1, self.max_retries + 1):
            is_timeout = False
            try:
                return self._fetch_fills_once(from_date, to_date)
            except EMSXRequestError as exc:
                last_error = exc
                is_timeout = (
                    "timeout" in str(exc).lower()
                    or "not responding" in str(exc).lower()
                    or "timed out" in str(exc).lower()
                )
                if is_timeout:
                    logger.warning("Bloomberg timeout — reconnecting session")
                    try:
                        self.disconnect()
                    except Exception:
                        pass
                    time.sleep(2)
                    try:
                        self.connect()
                    except Exception as conn_err:
                        raise EMSXRequestError(
                            f"Timeout recovery failed: {conn_err}"
                        ) from conn_err
            if attempt < self.max_retries:
                wait = attempt * 2
                logger.warning(
                    f"Fetch attempt {attempt}/{self.max_retries} failed: {last_error}."
                    f"{' [TIMEOUT]' if is_timeout else ''} Retrying in {wait}s..."
                )
                time.sleep(wait)
            else:
                logger.error(f"All {self.max_retries} fetch attempts failed")
        raise last_error

    def _fetch_fills_once(self, from_date: datetime, to_date: datetime) -> List[Dict[str, Any]]:
        """Execute a single GetFills request and parse the response.

        Scope 固定为 TradingSystem（基于登录的 AIM Px#），不支持 Team scope。
        """
        service = self._session.getService(self.service_name)
        request = service.createRequest("GetFills")
        from_str = from_date.strftime('%Y-%m-%dT%H:%M:%S.000+00:00')
        to_str = to_date.strftime('%Y-%m-%dT%H:%M:%S.000+00:00')
        request.set("FromDateTime", from_str)
        request.set("ToDateTime", to_str)
        scope = request.getElement("Scope")
        scope.setChoice("TradingSystem")
        scope.setElement("TradingSystem", True)
        self._session.sendRequest(request)
        fills: List[Dict[str, Any]] = []
        done = False
        consecutive_timeouts = 0
        while not done:
            try:
                event = self._session.nextEvent(self.event_timeout_ms)
            except Exception as e:
                raise EMSXRequestError(f"Timeout waiting for event: {e}")
            et = event.eventType()
            if et == blpapi.Event.PARTIAL_RESPONSE:
                consecutive_timeouts = 0
                for msg in event:
                    msg_type = msg.messageType()
                    if msg_type == GET_FILLS_RESPONSE:
                        try:
                            fills.extend(_parse_fill_messages(msg))
                        except Exception as e:
                            logger.warning("解析 fill 消息失败: %s", e)
                    elif msg_type == ERROR_RESPONSE or msg_type == ERROR_INFO:
                        raise self._build_request_error(msg)
            elif et == blpapi.Event.RESPONSE:
                consecutive_timeouts = 0
                for msg in event:
                    msg_type = msg.messageType()
                    if msg_type == GET_FILLS_RESPONSE:
                        try:
                            fills.extend(_parse_fill_messages(msg))
                        except Exception as e:
                            logger.warning("解析 fill 消息失败: %s", e)
                    elif msg_type == ERROR_RESPONSE or msg_type == ERROR_INFO:
                        raise self._build_request_error(msg)
                done = True
            elif et == blpapi.Event.TIMEOUT:
                consecutive_timeouts += 1
                if consecutive_timeouts >= 3:
                    raise EMSXRequestError(
                        f"3 consecutive timeouts — bbcomm may be unresponsive"
                    )
            else:
                pass
        return fills

    @staticmethod
    def _build_request_error(msg) -> EMSXRequestError:
        """从 ErrorResponse / ErrorInfo 消息提取错误码和消息，构造 EMSXRequestError。

        不同错误场景字段可能缺失，提取时 try-except 包裹以防再次抛异常。
        """
        error_code = ""
        error_msg = ""
        try:
            error_code = msg.getElementAsString("ErrorCode")
        except Exception:
            pass
        try:
            error_msg = msg.getElementAsString("ErrorMsg")
        except Exception:
            pass
        detail = f"Bloomberg API error: {error_code} - {error_msg}".strip(" -")
        logger.error(detail)
        return EMSXRequestError(detail)

    def get_trade_desks(self) -> List[str]:
        """Get available trade desks from EMSX API."""
        return []

    def get_teams(self) -> List[str]:
        """Get available teams from EMSX API."""
        return []

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
