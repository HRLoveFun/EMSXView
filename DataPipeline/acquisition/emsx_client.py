"""
EMSX API Client for FillFetch
Handles Bloomberg EMSX History API communication.

"""

import os
import sys
import logging
from datetime import datetime, date
from typing import List, Dict, Any, Optional, Callable

import blpapi
from blpapi import SessionOptions, Session, Service, Request, Message, Event

from DataPipeline.acquisition._constants import (
    GET_FILLS_RESPONSE,
    ERROR_INFO,
    EXPECTED_FILL_COLUMNS,
)

logger = logging.getLogger(__name__)

GET_TRADE_DESKS = blpapi.Name("GetTradeDesks")
GET_TEAMS = blpapi.Name("GetTeams")

EMSX_API_SERVICE = "//blp/emapisvc"
EMSX_API_SERVICE_BETA = "//blp/emapisvc_beta"

class EMSXHistoryClient:
    """Client for Bloomberg EMSX History API."""

    def __init__(self, host: Optional[str] = None, port: Optional[int] = None):
        self.host = host or os.getenv('BLOOMBERG_HOST', 'localhost')
        self.port = port or int(os.getenv('BLOOMBERG_PORT', '8194'))
        self.use_uat = os.getenv('USE_UAT', 'false').lower() == 'true'
        self.service = self._get_service()
        self.session: Optional[Session] = None
        self._response_received = False
        self._fills: List[Dict[str, Any]] = []
        self._generic_response: List[Any] = []

    def _get_service(self) -> str:
        if self.use_uat:
            return os.getenv('EMSX_HISTORY_SERVICE_UAT', '//blp/emsx.history.uat')
        return os.getenv('EMSX_HISTORY_SERVICE', '//blp/emsx.history')

    def connect(self) -> bool:
        """Connect to Bloomberg EMSX service."""
        session_options = SessionOptions()
        session_options.setServerHost(self.host)
        session_options.setServerPort(self.port)

        logger.info(f"Connecting to {self.host}:{self.port}")
        self.session = Session(session_options)

        if not self.session.start():
            logger.error("Failed to start session")
            return False

        if not self.session.openService(self.service):
            logger.error(f"Failed to open service {self.service}")
            return False

        logger.info(f"Connected to {self.service}")
        return True

    def disconnect(self):
        """Disconnect from Bloomberg."""
        if self.session:
            self.session.stop()
            self.session = None
            logger.info("Disconnected from Bloomberg")

    def _open_additional_service(self, service_name: str) -> bool:
        """Open an additional EMSX API service for the current session."""
        if not self.session:
            raise RuntimeError("Not connected to Bloomberg")
        if not self.session.openService(service_name):
            logger.error(f"Failed to open service {service_name}")
            return False
        logger.info(f"Opened additional service {service_name}")
        return True

    def fetch_fills(self, from_date: datetime, to_date: datetime) -> List[Dict[str, Any]]:
        """
        Fetch fill data from EMSX History API.

        Uses TradingSystem scope (fills for the logged-in AIM Px#).

        Args:
            from_date: Start datetime
            to_date: End datetime

        Returns:
            List of dicts with original EMSX column names preserved
        """
        if not self.session:
            raise RuntimeError("Not connected to Bloomberg")

        self._fills = []
        self._response_received = False

        service = self.session.getService(self.service)
        request = service.createRequest("GetFills")

        # Set date range
        from_str = from_date.strftime('%Y-%m-%dT%H:%M:%S.000+00:00')
        to_str = to_date.strftime('%Y-%m-%dT%H:%M:%S.000+00:00')
        request.set("FromDateTime", from_str)
        request.set("ToDateTime", to_str)

        # Set scope - TradingSystem (基于登录的 AIM Px#)
        scope = request.getElement("Scope")
        scope.setChoice("TradingSystem")
        scope.setElement("TradingSystem", True)
        logger.info(f"Requesting fills from {from_str} to {to_str} for TradingSystem (login-based)")

        # Send request and process response
        self.session.sendRequest(request)

        while not self._response_received:
            event = self.session.nextEvent(5000)
            self._process_event(event)

        logger.info(f"Received {len(self._fills)} fills")
        return self._fills

    def get_trade_desks(self) -> List[str]:
        """
        Get available trade desks from EMSX API (AIM only).
        Uses //blp/emapisvc service.

        Returns:
            List of trade desk names
        """
        if not self.session:
            raise RuntimeError("Not connected to Bloomberg")

        self._generic_response = []
        self._response_received = False

        if not self._open_additional_service(EMSX_API_SERVICE):
            return []

        api_service = self.session.getService(EMSX_API_SERVICE)
        request = api_service.createRequest("GetTradeDesks")

        logger.info("Requesting trade desks from EMSX API")
        self.session.sendRequest(request)

        desks = []
        while not self._response_received:
            event = self.session.nextEvent(5000)
            if event.eventType() == Event.RESPONSE or event.eventType() == Event.PARTIAL_RESPONSE:
                for msg in event:
                    if msg.messageType() == GET_TRADE_DESKS:
                        desks_elem = msg.getElement("EMSX_TRADE_DESK")
                        for d in desks_elem.values():
                            desk_name = d.getValueAsString()
                            desks.append(desk_name)
                    elif msg.messageType() == ERROR_INFO:
                        error_code = msg.getElementAsInteger("ErrorCode")
                        error_msg = msg.getElementAsString("ERROR_MESSAGE")
                        logger.error(f"GetTradeDesks Error {error_code}: {error_msg}")
                if event.eventType() == Event.RESPONSE:
                    self._response_received = True

        logger.info(f"Retrieved {len(desks)} trade desks")
        return desks

    def get_teams(self) -> List[str]:
        """
        Get available teams from EMSX API.
        Uses //blp/emapisvc_beta service.

        Returns:
            List of team names
        """
        if not self.session:
            raise RuntimeError("Not connected to Bloomberg")

        self._response_received = False

        if not self._open_additional_service(EMSX_API_SERVICE_BETA):
            return []

        api_service = self.session.getService(EMSX_API_SERVICE_BETA)
        request = api_service.createRequest("GetTeams")

        logger.info("Requesting teams from EMSX API")
        self.session.sendRequest(request)

        teams = []
        while not self._response_received:
            event = self.session.nextEvent(5000)
            if event.eventType() == Event.RESPONSE or event.eventType() == Event.PARTIAL_RESPONSE:
                for msg in event:
                    if msg.messageType() == GET_TEAMS:
                        teams_elem = msg.getElement("TEAMS")
                        for t in teams_elem.values():
                            team_name = t.getValueAsString()
                            teams.append(team_name)
                    elif msg.messageType() == ERROR_INFO:
                        error_code = msg.getElementAsInteger("ErrorCode")
                        error_msg = msg.getElementAsString("ERROR_MESSAGE")
                        logger.error(f"GetTeams Error {error_code}: {error_msg}")
                if event.eventType() == Event.RESPONSE:
                    self._response_received = True

        logger.info(f"Retrieved {len(teams)} teams")
        return teams

    def _process_event(self, event: Event):
        """Process incoming events."""
        if event.eventType() == Event.RESPONSE:
            self._response_received = True
            for msg in event:
                self._process_message(msg)
        elif event.eventType() == Event.PARTIAL_RESPONSE:
            for msg in event:
                self._process_message(msg)

    def _process_message(self, msg: Message):
        """Process a single message."""
        if msg.messageType() == ERROR_INFO:
            error_code = msg.getElementAsInteger("ErrorCode")
            error_msg = msg.getElementAsString("ErrorMsg")
            logger.error(f"EMSX Error {error_code}: {error_msg}")
        elif msg.messageType() == GET_FILLS_RESPONSE:
            fills = msg.getElement("Fills")
            total_fills = fills.numValues()
            parsed_count = 0
            for fill in fills.values():
                record = self._parse_fill(fill)
                if record:
                    self._fills.append(record)
                    parsed_count += 1
                else:
                    logger.warning(f"Fill at index {parsed_count} could not be parsed (empty)")
            if parsed_count != total_fills:
                logger.warning(f"Data loss detected: {total_fills} fills received but only {parsed_count} parsed")
            else:
                logger.info(f"All {total_fills} fills parsed successfully ({len(EXPECTED_FILL_COLUMNS)} columns expected)")

    def _safe_get_value(self, element, name: str):
        """Safely extract a value from a blpapi Element, preserving original type."""
        try:
            if not element.hasElement(name):
                return None
            child = element.getElement(name)
            dt = child.datatype()
            if dt == blpapi.DataType.STRING:
                return child.getValueAsString()
            elif dt == blpapi.DataType.FLOAT or dt == blpapi.DataType.DOUBLE:
                return child.getValueAsFloat()
            elif dt == blpapi.DataType.INT32 or dt == blpapi.DataType.INT64:
                return child.getValueAsInteger()
            elif dt == blpapi.DataType.BOOL:
                return child.getValueAsBool()
            elif dt == blpapi.DataType.DATETIME:
                return child.getValueAsString()
            else:
                return child.getValueAsString()
        except Exception:
            return None

    def _parse_fill(self, fill) -> Optional[Dict[str, Any]]:
        """Parse a fill element into a dict, preserving original EMSX column names.

        Uses two-pass approach to guarantee no data is dropped:
        1. Dynamic iteration captures all fields present in the response
        2. Explicit check ensures all EXPECTED_FILL_COLUMNS are attempted
        """
        record = {}
        try:
            # Pass 1: Dynamic iteration - captures everything the API returns
            num_elements = fill.numElements()
            for i in range(num_elements):
                try:
                    elem = fill.getElement(i)
                    name = str(elem.name())
                    record[name] = self._safe_get_value(fill, name)
                except Exception as e:
                    logger.warning(f"Error reading element at index {i}: {e}")
        except Exception as e:
            logger.error(f"Error during dynamic fill iteration: {e}")

        # Pass 2: Explicitly request all expected columns not yet captured
        for col_name in EXPECTED_FILL_COLUMNS:
            if col_name not in record:
                val = self._safe_get_value(fill, col_name)
                if val is not None:
                    record[col_name] = val
                    logger.debug(f"Recovered field '{col_name}' via explicit access")
                else:
                    record[col_name] = None  # ensure column exists even if empty

        if not record:
            logger.warning("Parsed fill resulted in empty record")
            return None

        return record

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
