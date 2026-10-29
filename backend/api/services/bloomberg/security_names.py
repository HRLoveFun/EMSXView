"""证券名称按需取数（refdata 名称字段）与进程内缓存。

为什么放在 core：MarketView 微服务无 Bloomberg 会话（只读数据层），而名称是
参考数据（refdata）字段，mktdata 不推送。前端通过 core 的
`GET /api/securities/names` 取一次、模块内缓存，避免每屏刷新都打终端。

口径：
- 支持两个字段：`NAME_CHINESE_SIMPLIFIED`（中文简称，既有默认）与 `SHORT_NAME`
  （英文短名，监控台 Name 列用）。取不到（无权限/无该语言名/证券无效）就不缓存，
  由调用方决定回落（前端显示 `—`），不猜、不翻译。
- 缓存键为 (字段, ticker)，两个字段互不覆盖；失败不写负缓存，下次请求会重试。
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Iterable

import blpapi

from config import settings

logger = logging.getLogger(__name__)

#: 默认字段（保持既有调用方行为不变）
DEFAULT_FIELD = "NAME_CHINESE_SIMPLIFIED"
#: 允许请求的名称字段白名单（未列出的字段直接 400，不向终端发任意字段）
SUPPORTED_FIELDS: frozenset[str] = frozenset({"NAME_CHINESE_SIMPLIFIED", "SHORT_NAME"})
#: 兼容既有引用（测试与调用方按 FIELD 取值）
FIELD = DEFAULT_FIELD
CHUNK_SIZE = 100
REQUEST_TIMEOUT_SEC = 10.0


def extract_names(message, field: str = DEFAULT_FIELD) -> dict[str, str]:
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
        if not field_data.hasElement(field):
            continue
        element = field_data.getElement(field)
        if element.isNull():
            continue
        name = element.getValueAsString().strip()
        if name:
            names[ticker] = name
    return names


class SecurityNamesService:
    """按需取名称：单会话 + 锁 + 进程内缓存（低 QPS，无需并发优化）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cache: dict[tuple[str, str], str] = {}
        self._session = None

    def get_names(
        self,
        tickers: Iterable[str],
        field: str = DEFAULT_FIELD,
    ) -> tuple[dict[str, str], list[str]]:
        """返回 (已解析名称, 仍未取到的 ticker 列表)。"""
        wanted = list(dict.fromkeys(ticker for ticker in (tickers or []) if ticker))
        with self._lock:
            missing = [ticker for ticker in wanted if (field, ticker) not in self._cache]
            if missing:
                try:
                    self._fetch(missing, field)
                except Exception:  # noqa: BLE001 - 终端不可用不应打挂面板
                    logger.warning("security names fetch failed", exc_info=True)
            names = {
                ticker: self._cache[(field, ticker)]
                for ticker in wanted
                if (field, ticker) in self._cache
            }
            unresolved = [ticker for ticker in wanted if (field, ticker) not in self._cache]
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

    def _fetch(self, tickers: list[str], field: str = DEFAULT_FIELD) -> None:
        session = self._ensure_session()
        service = session.getService("//blp/refdata")
        for start in range(0, len(tickers), CHUNK_SIZE):
            self._request_chunk(session, service, tickers[start:start + CHUNK_SIZE], field)

    def _request_chunk(self, session, service, chunk: list[str], field: str = DEFAULT_FIELD) -> None:
        request = service.createRequest("ReferenceDataRequest")
        securities = request.getElement("securities")
        for ticker in chunk:
            securities.appendValue(ticker)
        request.getElement("fields").appendValue(field)
        session.sendRequest(request)

        deadline = time.monotonic() + REQUEST_TIMEOUT_SEC
        while time.monotonic() < deadline:
            event = session.nextEvent(500)
            if event.eventType() in (blpapi.Event.RESPONSE, blpapi.Event.PARTIAL_RESPONSE):
                for message in event:
                    for ticker, name in extract_names(message, field).items():
                        self._cache[(field, ticker)] = name
                if event.eventType() == blpapi.Event.RESPONSE:
                    return
        logger.warning("security names timeout for %d tickers (field=%s)", len(chunk), field)
