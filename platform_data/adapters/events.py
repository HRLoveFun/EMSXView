"""事件与市场级状态适配器（057 DL-11）——日级 regime + 事件窗口。

数据源（2026-10-23 实测核验，全部只读）：
- `regime.db::daily_liquidity_regime` / `daily_vol_regime` / `daily_trend_regime`：
  23 市场 × 日级状态（管道 S8 口径，带 config_version 审计）；
- `regime.db::ref_macro_event_calendar`：131 条 12 类宏观事件（severity/window_days）；
- DL-03 `HALF_DAY_CLOSE_OVERRIDES`：半日市静态表（有限覆盖）；
- EMSX 导出字段（财报/除息）：尽力而为维度——样例填充率未验证，由调用方
  传入解析行，无行时仅半日市且 coverage 披露（不强求，父计划 DL-11 裁剪）。

未知市场/无数据返回 None 或空列表（降级可见，不静默填常态）。
"""

from __future__ import annotations

import logging
from typing import Sequence

from platform_data.contracts.market_contracts import (
    REGIME_SCHEMA_VERSION,
    EventFlag,
    MarketRegimeState,
)

logger = logging.getLogger(__name__)

# 事件来源标识（EventFlag.source）
SOURCE_MACRO_CALENDAR = "macro-calendar"
SOURCE_EMSX_EXPORT = "emsx-export"
SOURCE_HALF_DAY_TABLE = "half-day-table"


class EventRegimeAdapter:
    """市场级状态与事件只读查询（无状态；公开 API 见 module-boundary §2.3）。"""

    def get_market_state(
        self,
        market_code: str,
        *,
        as_of: str | None = None,
        connection_manager=None,
    ) -> MarketRegimeState | None:
        """单市场日级状态 + 当日窗口内宏观事件；未知/无数据返回 None。"""
        mgr = connection_manager or self._mgr()
        market = market_code.strip().upper()
        regimes = self._load_regimes(mgr, market, as_of)
        if not regimes:
            return None
        events = self._load_macro_events(mgr, market, regimes["as_of"])
        return MarketRegimeState(
            market_code=market,
            as_of=regimes["as_of"],
            liq_regime=regimes["liq"],
            vol_regime=regimes["vol"],
            trend_regime=regimes["trend"],
            macro_events=tuple(events),
            config_version=regimes["config_version"],
            schema_version=REGIME_SCHEMA_VERSION,
        )

    def get_market_states(
        self,
        market_codes: Sequence[str],
        *,
        as_of: str | None = None,
        connection_manager=None,
    ) -> list[MarketRegimeState]:
        """批量（盘前单按股票池）；无数据的市场不出现在结果中（调用方可见缺口）。"""
        mgr = connection_manager or self._mgr()
        states: list[MarketRegimeState] = []
        for code in market_codes:
            state = self.get_market_state(code, as_of=as_of, connection_manager=mgr)
            if state is not None:
                states.append(state)
        return states

    def event_flags_for_ticker(
        self,
        equ_ticker: str,
        *,
        trade_date: str,
        export_row: dict | None = None,
    ) -> tuple[list[EventFlag], bool]:
        """逐票事件标记 + 导出覆盖率。

        返回 (flags, export_covered)：
        - 半日市（DL-03 静态表）始终尝试；
        - export_row（DL-01 导出行 dict，含 Exp Earn Rpt Time/Ex-Dvd Flag）非空时
          解析财报/除息标记；为空时 export_covered=False（填充率披露，不强求）。
        """
        flags: list[EventFlag] = []
        from platform_data.contracts.exchange_session_contracts import (
            HALF_DAY_CLOSE_OVERRIDES,
        )

        exchange = _exchange_of(equ_ticker)
        key = (exchange, trade_date)
        if key in HALF_DAY_CLOSE_OVERRIDES:
            flags.append(
                EventFlag(
                    code="half_day",
                    severity="normal",
                    window_days=0,
                    source=SOURCE_HALF_DAY_TABLE,
                    evidence=f"close {HALF_DAY_CLOSE_OVERRIDES[key]}",
                )
            )

        export_covered = export_row is not None
        if export_row is not None:
            earn_time = (export_row.get("Exp Earn Rpt Time") or "").strip()
            if earn_time:
                flags.append(
                    EventFlag(
                        code="earnings",
                        severity="high",
                        window_days=0,
                        source=SOURCE_EMSX_EXPORT,
                        evidence=earn_time,
                    )
                )
            ex_dvd = (export_row.get("Ex-Dvd Flag") or "").strip().upper()
            if ex_dvd == "Y":
                flags.append(
                    EventFlag(
                        code="ex_dividend",
                        severity="normal",
                        window_days=0,
                        source=SOURCE_EMSX_EXPORT,
                        evidence="Y",
                    )
                )
        return flags, export_covered

    # ── 内部（regime.db 只读） ──

    @staticmethod
    def _mgr():
        from data_access import ConnectionManager

        return ConnectionManager()

    @staticmethod
    def _load_regimes(mgr, market: str, as_of: str | None) -> dict | None:
        """三张 regime 表按 (market, date) 读取；date 缺省取各表最近日。"""
        conn = mgr.get_connection("regime")
        try:
            date_clause = "AND trade_date = ?" if as_of else "AND trade_date = (SELECT MAX(trade_date) FROM {table})"
            liq = conn.execute(
                f"SELECT trade_date, liq_regime, config_version FROM daily_liquidity_regime "
                f"WHERE market_code = ? {date_clause.format(table='daily_liquidity_regime')}",
                (market,) if not as_of else (market, as_of),
            ).fetchone()
            if not liq:
                return None
            vol = conn.execute(
                f"SELECT vol_regime FROM daily_vol_regime WHERE market_code = ? AND trade_date = ?",
                (market, liq[0]),
            ).fetchone()
            trend = conn.execute(
                f"SELECT trend_regime FROM daily_trend_regime WHERE market_code = ? AND trade_date = ?",
                (market, liq[0]),
            ).fetchone()
        finally:
            conn.close()
        return {
            "as_of": str(liq[0]),
            "liq": liq[1],
            "vol": vol[0] if vol else None,
            "trend": trend[0] if trend else None,
            "config_version": liq[2],
        }

    @staticmethod
    def _load_macro_events(mgr, market: str, trade_date: str) -> list[EventFlag]:
        """当日窗口内的宏观事件：event_date − window_days ≤ trade_date ≤ event_date。

        trade_date 为 YYYYMMDD（EMSX 口径）——SQLite date() 只认 YYYY-MM-DD，
        先归一化再比较（regime 库 event_date 为横线格式）。
        """
        iso = _iso_date(trade_date)
        conn = mgr.get_connection("regime")
        try:
            rows = conn.execute(
                "SELECT event_type, severity, window_days, description FROM ref_macro_event_calendar "
                "WHERE market_code = ? AND date(event_date, '-' || window_days || ' days') <= date(?) "
                "AND date(event_date) >= date(?)",
                (market, iso, iso),
            ).fetchall()
        finally:
            conn.close()
        return [
            EventFlag(
                code=str(r[0]),
                severity=str(r[1] or "normal"),
                window_days=int(r[2] or 0),
                source=SOURCE_MACRO_CALENDAR,
                evidence=r[3],
            )
            for r in rows
        ]


def _exchange_of(equ_ticker: str) -> str:
    """'AAPL US Equity' → 'US'（BDIB 复合代码后缀）。"""
    parts = str(equ_ticker).split()
    return parts[-2].upper() if len(parts) >= 2 else ""


def _iso_date(trade_date: str) -> str:
    """YYYYMMDD → YYYY-MM-DD（已是横线格式或无法解析则原样返回）。"""
    text = str(trade_date).strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text
