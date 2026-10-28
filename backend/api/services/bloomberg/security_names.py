"""证券名称按需取数（`NAME_CHINESE_SIMPLIFIED`）与进程内缓存。

为什么放在 core：MarketView 微服务无 Bloomberg 会话（只读数据层），而中文名称是
参考数据（refdata）字段，mktdata 不推送。前端通过 core 的
`GET /api/securities/names` 取一次、模块内缓存，避免每屏刷新都打终端。

口径：
- 只取 `NAME_CHINESE_SIMPLIFIED`；取不到（无权限/无该语言名/证券无效）就不缓存，
  由调用方决定回落（前端显示 `—`），不猜、不翻译。
- 缓存进程内常驻（名称是静态参考数据），失败不写负缓存，下次请求会重试。
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Iterable

import blpapi

from config import settings

logger = logging.getLogger(__name__)

FIELD = "NAME_CHINESE_SIMPLIFIED"
CHUNK_SIZE = 100
REQUEST_TIMEOUT_SEC = 10.0


def extract_names(message) -> dict[str, str]:
    """从 ReferenceDataResponse 的一条消息里抽出 {ticker: 名称}。

    缺字段、null、空串、securityError 一律跳过（不写负缓存）。
    """
    if not message.hasElement("securityData"):
        return {}
    names: dict[str, str] = {}
    data = message.getElement("securityData")
    for index in range(data.numValues()):
        item = data.getValueAsElement(index)
        if item.hasElement("securityError"):
            continue
        ticker = item.getElementAsString("security")
        if not item.hasElement("fieldData"):
            continue
        field_data = item.getElement("fieldData")
        if not field_data.hasElement(FIELD):
            continue
        element = field_data.getElement(FIELD)
        if element.isNull():
            continue
        name = element.getValueAsString().strip()
        if name:
            names[ticker] = name
    return names


class SecurityNamesService:
    """按需取中文简称：单会话 + 锁 + 进程内缓存（低 QPS，无需并发优化）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cache: dict[str, str] = {}
        self._session = None

    def get_names(self, tickers: Iterable[str]) -> tuple[dict[str, str], list[str]]:
        """返回 (已解析名称, 仍未取到的 ticker 列表)。"""
        wanted = list(dict.fromkeys(ticker for ticker in (tickers or []) if ticker))
        with self._lock:
            missing = [ticker for ticker in wanted if ticker not in self._cache]
            if missing:
                try:
                    self._fetch(missing)
                except Exception:  # noqa: BLE001 - 终端不可用不应打挂面板
                    logger.warning("security names fetch failed", exc_info=True)
            names = {ticker: self._cache[ticker] for ticker in wanted if ticker in self._cache}
            unresolved = [ticker for ticker in wanted if ticker not in self._cache]
        return names, unresolved

    # ── 内部 ────────────────────────────────────────────────────────────

    def _ensure_session(self):
        if self._session is not None:
            return self._session
        options = blpapi.SessionOptions()
        options.setServerHost(settings.BLOOMBERG_HOST)
        options.setServerPort(settings.BLOOMBERG_PORT)
        options.setAutoRestartOnDisconnection(True)
        session = blpapi.Session(options)
        if not session.start() or not session.openService("//blp/refdata"):
            session.stop()
            raise RuntimeError("blpapi refdata 会话不可用")
        self._session = session
        return session

    def _fetch(self, tickers: list[str]) -> None:
        session = self._ensure_session()
        service = session.getService("//blp/refdata")
        for start in range(0, len(tickers), CHUNK_SIZE):
            self._request_chunk(session, service, tickers[start:start + CHUNK_SIZE])

    def _request_chunk(self, session, service, chunk: list[str]) -> None:
        request = service.createRequest("ReferenceDataRequest")
        securities = request.getElement("securities")
        for ticker in chunk:
            securities.appendValue(ticker)
        request.getElement("fields").appendValue(FIELD)
        session.sendRequest(request)

        deadline = time.monotonic() + REQUEST_TIMEOUT_SEC
        while time.monotonic() < deadline:
            event = session.nextEvent(500)
            if event.eventType() in (blpapi.Event.RESPONSE, blpapi.Event.PARTIAL_RESPONSE):
                for message in event:
                    self._cache.update(extract_names(message))
                if event.eventType() == blpapi.Event.RESPONSE:
                    return
        logger.warning("security names timeout for %d tickers", len(chunk))
