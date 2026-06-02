"""
Bloomberg EMSX Connection Manager — extracted from bloomberg_adapter.py.

Handles Bloomberg API session lifecycle: main session, request session pool,
and mktdata session. Does NOT manage subscription threads — those belong
to higher-level components (EMSXSubscriptionEngine, MarketDataEnrichmentService).
"""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime
from typing import List, Optional, Any

import blpapi
from blpapi import SessionOptions, Session, Service

from schemas import ConnectionStatus, StartupStatus, BackendStartupStatus, SubscriptionStartupStatus

from ._constants import EMSX_SERVICES

logger = logging.getLogger("main")

# Module-level settings — set by configure_connection() before any instance is created
_connection_settings: Any = None


def configure_connection(settings: Any) -> None:
    global _connection_settings
    _connection_settings = settings


class BloombergConnectionManager:
    def __init__(self, _settings: Any = None):
        self._settings = _settings if _settings is not None else _connection_settings

        self.session: Optional[Session] = None
        self.active_service_name: Optional[str] = None
        self.connected: bool = False
        self.connection_time: Optional[datetime] = None
        self.last_error: Optional[str] = None
        self.service: Optional[Service] = None
        self._service_started_at: datetime = datetime.now()

        self._request_sessions: List[Session] = []
        self._request_locks: List[threading.Lock] = []
        self._request_service: Optional[Service] = None
        self._pool_index: int = 0

        self._mktdata_session: Optional[Session] = None
        self._mktdata_connected: bool = False

        self._refdata_service_available: bool = False

        self._lock = asyncio.Lock()

    # ── Properties for sub-components ──────────────────────────────────

    @property
    def request_sessions(self) -> List[Session]:
        return self._request_sessions

    @property
    def request_locks(self) -> List[threading.Lock]:
        return self._request_locks

    @property
    def request_service(self) -> Optional[Service]:
        return self._request_service or self.service

    @property
    def pool_index(self) -> int:
        return self._pool_index

    @pool_index.setter
    def pool_index(self, value: int) -> None:
        self._pool_index = value

    @property
    def mktdata_session(self) -> Optional[Session]:
        return self._mktdata_session

    @property
    def mktdata_connected(self) -> bool:
        return self._mktdata_connected

    @mktdata_connected.setter
    def mktdata_connected(self, value: bool) -> None:
        self._mktdata_connected = value

    @property
    def refdata_service_available(self) -> bool:
        return self._refdata_service_available

    # ── Connection lifecycle ───────────────────────────────────────────

    async def connect(self) -> bool:
        async with self._lock:
            if self.connected and self.session:
                return True

            session = None
            try:
                logger.info(
                    f"Connecting to Bloomberg at {self._settings.BLOOMBERG_HOST}:{self._settings.BLOOMBERG_PORT}"
                )

                session_options = SessionOptions()
                session_options.setServerAddress(
                    self._settings.BLOOMBERG_HOST,
                    self._settings.BLOOMBERG_PORT,
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

                opened_svc = None
                for svc_name in EMSX_SERVICES:
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

                self.session = session
                self.connected = True
                self.connection_time = datetime.now()
                self.last_error = None

                pool_size = max(1, int(self._settings.REQUEST_SESSION_POOL_SIZE))
                sessions: List[Session] = []
                locks: List[threading.Lock] = []
                for i in range(pool_size):
                    sess = self._create_request_session(i)
                    if sess:
                        sessions.append(sess)
                        locks.append(threading.Lock())
                if sessions:
                    self._request_sessions = sessions
                    self._request_locks = locks
                    self._request_service = sessions[0].getService(opened_svc)
                    self._pool_index = 0

                mktdata_session = None
                try:
                    mktdata_opts = SessionOptions()
                    mktdata_opts.setServerAddress(
                        self._settings.BLOOMBERG_HOST, self._settings.BLOOMBERG_PORT, 0
                    )
                    mktdata_session = Session(mktdata_opts)
                    if mktdata_session.start() and mktdata_session.openService("//blp/mktdata"):
                        self._mktdata_session = mktdata_session
                        self._mktdata_connected = True
                        logger.info("Opened dedicated mktdata session for real-time market data subscriptions")
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

                logger.info("Bloomberg connection established (threads not started)")
                return True

            except Exception as e:
                self.last_error = f"Connection error: {str(e)}"
                logger.exception(self.last_error)
                self.connected = False
                if session:
                    try:
                        session.stop()
                    except Exception:
                        pass
                return False

    def disconnect(self):
        logger.info("Disconnecting from Bloomberg...")

        if self._mktdata_session:
            try:
                self._mktdata_session.stop()
                logger.info("Mktdata session stopped")
            except Exception as e:
                logger.warning(f"Error stopping mktdata session: {e}")
            finally:
                self._mktdata_session = None
                self._mktdata_connected = False

        for i, sess in enumerate(self._request_sessions):
            try:
                sess.stop()
                logger.info("request-session[%d] stopped", i)
            except Exception as e:
                logger.warning("Error stopping request-session[%d]: %s", i, e)
        self._request_sessions.clear()
        self._request_locks.clear()
        self._request_service = None
        self._pool_index = 0

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

    def get_startup_status(
        self,
        init_paint_done: bool = False,
        route_init_paint_done: bool = False,
        subscription_failed: bool = False,
        order_count: int = 0,
        route_count: int = 0,
    ) -> StartupStatus:
        bloomberg = self.get_status()
        backend_uptime = int((datetime.now() - self._service_started_at).total_seconds())

        subscriptions = SubscriptionStartupStatus(
            ordersInitPaintDone=init_paint_done,
            routesInitPaintDone=route_init_paint_done,
            subscriptionFailed=subscription_failed,
            marketDataConnected=self._mktdata_connected,
            orderCount=order_count,
            routeCount=route_count,
            ready=(
                self.connected
                and init_paint_done
                and route_init_paint_done
                and not subscription_failed
            ),
        )

        if bloomberg.status != "connected":
            phase = "error" if bloomberg.message else "bloomberg_connecting"
            message = bloomberg.message or "Backend 已启动，正在连接 Bloomberg EMSX..."
        elif subscriptions.subscriptionFailed:
            phase = "error"
            message = "Bloomberg 已连接，但 EMSX 订阅失败；请检查日志并重试。"
        elif subscriptions.ready:
            phase = "ready"
            message = "Backend、Bloomberg 与 EMSX 订阅均已就绪。"
        else:
            phase = "subscriptions_warming"
            message = "Bloomberg 已连接，正在等待订单和路由 INIT_PAINT 完成。"

        return StartupStatus(
            phase=phase,
            ready=subscriptions.ready,
            message=message,
            backend=BackendStartupStatus(
                httpReady=True,
                startedAt=self._service_started_at.isoformat(),
                uptime=backend_uptime,
            ),
            bloomberg=bloomberg,
            subscriptions=subscriptions,
        )

    def _create_request_session(self, index: int) -> Optional[Session]:
        opts = SessionOptions()
        opts.setServerAddress(self._settings.BLOOMBERG_HOST, self._settings.BLOOMBERG_PORT, 0)
        opts.setAutoRestartOnDisconnection(True)
        session = Session(opts)
        if not session.start():
            logger.error("request-session[%d] failed to start", index)
            return None
        if not session.openService(self.active_service_name or "//blp/emapisvc_beta"):
            logger.error("request-session[%d] failed to open service", index)
            session.stop()
            return None
        logger.info("request-session[%d] ready", index)
        return session
