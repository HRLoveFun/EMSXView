"""市场时钟：交易所本地时间与交易状态（057 DL-03 会话注册表的展示口径）。

为什么要这层：mktdata 在休市时仍返回上一交易日的完整镜像（价、量、高开低），
前端若不区分状态，会把镜像值当成「实时在跳」。本模块只回答「此刻该市场是什么状态」，
不做行情判断、不触库。

状态取值（前端按此映射文案与配色）：`pre` 盘前 / `open` 交易中 / `lunch` 午休 /
`closed` 已收市 / `unknown` 未知市场。
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

STATUS_PRE = "pre"
STATUS_OPEN = "open"
STATUS_LUNCH = "lunch"
STATUS_CLOSED = "closed"
STATUS_UNKNOWN = "unknown"

# 行情侧交易所码 → 会话注册表码（注册表按国家/通道注册，行情侧用复合码）：
# - `CH`：沪深港通在注册表里是 `C1`，但 Bloomberg 行情代码写 `CH`（池板 43/100 是这类）
# - `EU`：欧元区复合代码，无单一国家归属；Xetra/Paris/Amsterdam/Milan/Madrid/
#   Brussels/Lisbon 同为 09:00–17:30 本地时，故用 Berlin 时区的 Xetra 时段近似
#   （雅典 10:15–17:20、布拉格等不适用；EU 正式会话条目待 DL-06 与管道对齐后补）
EXCHANGE_ALIASES = {"CH": "C1", "EU": "GR"}


def exchange_of(equ_ticker: str) -> str:
    """`AAPL US Equity` → `US`；格式不符返回空串（与 pool_board 同口径）。"""
    parts = str(equ_ticker).split()
    return parts[-2].upper() if len(parts) >= 2 else ""


def _minutes(hhmm: str) -> int:
    """'HH:MM' → 分钟数。"""
    hours, _, minutes = hhmm.partition(":")
    return int(hours) * 60 + int(minutes or 0)


def market_clock(
    session_adapter,
    exchange_code: str,
    now: datetime | None = None,
) -> tuple[str, str | None]:
    """返回 (状态, 交易所本地 `HH:MM`)。

    判定顺序：未注册 → `unknown`；周末 → `closed`；午休区间 → `lunch`；
    开盘前 → `pre`；收盘后（含收盘竞价）→ `closed`；其余 → `open`。

    已知边界：注册表没有法定节假日数据，节假日盘中会显示 `open`——此时以
    「窗口内 LAST_PRICE 是否变化」为准（见 docs/report-marketview-live-fields.md）。
    """
    code = (exchange_code or "").strip().upper()
    session = None
    if code:
        session = session_adapter.get_session(code) or session_adapter.get_session(
            EXCHANGE_ALIASES.get(code, "")
        )
    if session is None:
        return STATUS_UNKNOWN, None
    try:
        local = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(session.timezone))
    except Exception:  # noqa: BLE001 - 缺 tzdata 时退化为 unknown，不阻断面板
        return STATUS_UNKNOWN, None

    local_time = local.strftime("%H:%M")
    if local.weekday() >= 5:
        return STATUS_CLOSED, local_time

    minutes = local.hour * 60 + local.minute
    if session.lunch and _minutes(session.lunch[0]) <= minutes < _minutes(session.lunch[1]):
        return STATUS_LUNCH, local_time
    if minutes < _minutes(session.market_open):
        return STATUS_PRE, local_time
    if minutes >= _minutes(session.market_close):
        return STATUS_CLOSED, local_time
    return STATUS_OPEN, local_time
