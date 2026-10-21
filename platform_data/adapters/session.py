"""交易所会话查询适配器（057 DL-03）——会话注册表的查询层。

公开方法（module-boundary §2.3：跨域仅可调用无下划线公开 API）：
- get_session / session_bounds_for / closing_time_for：会话定义与半日市查询
- session_relative_minutes：本地 naive datetime → 相对开盘挂钟分钟（午休计入）
- is_early_close_auction / market_code_for / time_bucket_for：管道口径镜像查询
"""

from __future__ import annotations

from datetime import date, datetime

from platform_data.contracts.exchange_session_contracts import (
    MARKET_CODE_FOLDING,
    SESSION_REGISTRY,
    TIME_BUCKET_MARKETS,
    ExchangeSession,
)


class ExchangeSessionAdapter:
    """会话注册表只读查询（无状态，可跨模块共享实例）。"""

    def get_session(self, exchange_code: str) -> ExchangeSession | None:
        """返回会话定义；未注册市场返回 None（不抛错）。"""
        return SESSION_REGISTRY.get((exchange_code or "").strip().upper())

    def session_bounds_for(self, exchange_code: str, trade_date: str | date) -> tuple[str, str] | None:
        """返回 (开盘, 收盘) 本地 HH:MM；半日市覆盖生效。未注册返回 None。"""
        session = self.get_session(exchange_code)
        if session is None:
            return None
        close = self.closing_time_for(exchange_code, trade_date) or session.market_close
        return session.market_open, close

    def closing_time_for(self, exchange_code: str, trade_date: str | date) -> str | None:
        """收盘时刻：半日市覆盖优先，否则常规收盘。未注册返回 None。"""
        session = self.get_session(exchange_code)
        if session is None:
            return None
        key = (session.exchange_code, _date_key(trade_date))
        from platform_data.contracts.exchange_session_contracts import HALF_DAY_CLOSE_OVERRIDES

        return HALF_DAY_CLOSE_OVERRIDES.get(key, session.market_close)

    def session_relative_minutes(self, exchange_code: str, local_dt: datetime) -> int | None:
        """本地 naive datetime → 相对开盘的挂钟分钟数（午休计入，即挂钟差）。

        未注册返回 None；不校验是否在会话内（跨时段仍计算挂钟差）。
        """
        session = self.get_session(exchange_code)
        if session is None:
            return None
        open_minutes = _hhmm_to_minutes(session.market_open)
        return local_dt.hour * 60 + local_dt.minute - open_minutes

    def is_early_close_auction(self, exchange_code: str) -> bool:
        """收盘竞价是否提前开始（管道 ADJUST 口径，判定需 ±1min 容差）。"""
        session = self.get_session(exchange_code)
        return bool(session and session.early_close_auction)

    def market_code_for(self, exchange_code: str) -> str:
        """交易所码 → 市场码（管道 derive_market_code 折叠；未知原样返回）。"""
        code = (exchange_code or "").strip().upper()
        return MARKET_CODE_FOLDING.get(code, code)

    def time_bucket_for(self, exchange_code: str, local_dt: datetime) -> str | None:
        """日内时段桶（管道 S9 口径镜像）。

        仅 TIME_BUCKET_MARKETS（折叠后）返回桶名，其余 None。五桶
        open_30m / morning / midday / afternoon / close_30m 由开收盘派生
        （中段三等分）；午休区间优先返回 lunch_break（JP）。
        折叠市场（如 GR→EU）按原交易所会话算桶；纯折叠码（如 EUR）无会话
        定义时返回 None——EU 泛化会话条目待 DL-06 与管道对齐后补充。
        """
        code = (exchange_code or "").strip().upper()
        market = self.market_code_for(code)
        if market not in TIME_BUCKET_MARKETS:
            return None
        session = self.get_session(code) or self.get_session(market)
        if session is None:
            return None

        minutes_of_day = local_dt.hour * 60 + local_dt.minute
        lunch = session.lunch
        if lunch is not None:
            lunch_start = _hhmm_to_minutes(lunch[0])
            lunch_end = _hhmm_to_minutes(lunch[1])
            if lunch_start <= minutes_of_day < lunch_end:
                return "lunch_break"

        relative = minutes_of_day - _hhmm_to_minutes(session.market_open)
        span = _hhmm_to_minutes(session.market_close) - _hhmm_to_minutes(session.market_open)
        if relative < 0:
            return None  # 开盘前
        if relative < 30:
            return "open_30m"
        if relative >= span - 30:
            return "close_30m"
        if lunch is not None:
            # 有午休市场：午休后直接进 afternoon（语义化，不做中段三等分）
            lunch_start_rel = _hhmm_to_minutes(lunch[0]) - _hhmm_to_minutes(session.market_open)
            return "morning" if relative < lunch_start_rel else "afternoon"
        segment = (span - 30) / 3
        if relative < 30 + segment:
            return "morning"
        if relative < 30 + segment * 2:
            return "midday"
        return "afternoon"


def _hhmm_to_minutes(value: str) -> int:
    """'HH:MM' → 分钟数。"""
    hours, _, minutes = value.partition(":")
    return int(hours) * 60 + int(minutes or 0)


def _date_key(trade_date: str | date) -> str:
    """date 或 'YYYY-MM-DD' / 'YYYYMMDD' → 'YYYY-MM-DD'。"""
    if isinstance(trade_date, date):
        return trade_date.isoformat()
    text = str(trade_date).strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text
