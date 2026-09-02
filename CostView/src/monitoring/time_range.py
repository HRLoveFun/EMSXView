"""时间范围解析 — CLI / API / 调度共用的互斥时间范围校验与预设解析。

规则（与计划一致）：
- ``--start/--end`` 显式区间与 ``--last`` 预设二选一互斥，必须且只能输入一种；
- 两者同时给出、start/end 不成对、start > end、未知预设值均抛 ``ValueError``；
- 都不给时按默认 ``last="day"``；
- ``last day`` 取 tca_route_summary 中最近一个有数据的 ``order_as_of_date``
  （避免周末/假日产生空报告），需调用方通过 ``latest_data_date`` 注入。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from DataPipeline.config import Config
from DataPipeline.storage.connection import AccessTier, ConnectionManager

logger = logging.getLogger(__name__)

#: last 预设白名单
LAST_PRESETS: tuple[str, ...] = ("day", "week", "month", "quarter", "year")

_DATE_RE = re.compile(r"^\d{8}$")


@dataclass(frozen=True)
class TimeRange:
    """解析后的时间范围（YYYYMMDD 闭区间）。"""

    start_date: str
    end_date: str
    #: 使用的 last 预设；显式区间时为 None
    preset: Optional[str] = None


def resolve_time_range(
    start: Optional[str] = None,
    end: Optional[str] = None,
    last: Optional[str] = None,
    *,
    today: Optional[date] = None,
    latest_data_date: Optional[str] = None,
) -> TimeRange:
    """互斥校验并解析时间范围。

    Args:
        start: 显式起始日 YYYYMMDD。
        end: 显式截止日 YYYYMMDD。
        last: 相对预设（day/week/month/quarter/year）。
        today: 参考"今天"，默认取系统日期（测试可注入）。
        latest_data_date: tca_route_summary 最近数据日期 YYYYMMDD，
            仅 ``last="day"`` 时必需。

    Returns:
        TimeRange（闭区间）。

    Raises:
        ValueError: 互斥冲突 / 参数不成对 / start > end / 未知预设 /
            last=day 但无数据日期。
    """
    today = today or date.today()
    has_explicit = start is not None or end is not None
    last = last.strip().lower() if last else None

    if has_explicit and last:
        raise ValueError(
            "时间范围二选一：--start/--end 与 --last 不能同时使用"
        )
    if has_explicit:
        return _resolve_explicit(start, end)
    return _resolve_preset(last or "day", today, latest_data_date)


def fetch_latest_tca_date(mgr: Optional[ConnectionManager] = None) -> Optional[str]:
    """查询 tca_route_summary 中最近一个有数据的 order_as_of_date。

    表不存在或为空时返回 None（调用方据此给出友好报错）。
    """
    mgr = mgr or ConnectionManager()
    conn = None
    try:
        conn = mgr.get_connection("fill_bdib", AccessTier.READ)
        cursor = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ? LIMIT 1",
            [Config.TCA_ROUTE_SUMMARY_TABLE],
        )
        if cursor.fetchone() is None:
            return None
        row = conn.execute(
            f"SELECT MAX(order_as_of_date) FROM {Config.TCA_ROUTE_SUMMARY_TABLE}"
        ).fetchone()
        return str(row[0]) if row and row[0] else None
    except Exception as exc:  # 数据库缺失等异常降级为 None
        logger.warning("查询最近 TCA 数据日期失败: %s", exc)
        return None
    finally:
        if conn is not None:
            conn.close()


def _resolve_explicit(start: Optional[str], end: Optional[str]) -> TimeRange:
    """校验显式区间：必须成对、格式合法、start <= end。"""
    if not start or not end:
        raise ValueError("--start 与 --end 必须同时提供")
    if not _DATE_RE.match(start) or not _DATE_RE.match(end):
        raise ValueError("日期格式必须为 YYYYMMDD")
    if start > end:
        raise ValueError(f"起始日期晚于截止日期: {start} > {end}")
    return TimeRange(start_date=start, end_date=end)


def _resolve_preset(
    preset: str,
    today: date,
    latest_data_date: Optional[str],
) -> TimeRange:
    """将 last 预设解析为具体日期区间。"""
    if preset not in LAST_PRESETS:
        raise ValueError(
            f"未知 --last 预设 {preset!r}，可选: {', '.join(LAST_PRESETS)}"
        )
    if preset == "day":
        if not latest_data_date:
            raise ValueError(
                "last day 需要 tca_route_summary 已有数据（表为空或无记录）"
            )
        return TimeRange(start_date=latest_data_date, end_date=latest_data_date,
                         preset="day")
    if preset == "week":
        # 上周一 ~ 上周日
        this_monday = today - timedelta(days=today.weekday())
        last_monday = this_monday - timedelta(days=7)
        return TimeRange(_fmt(last_monday), _fmt(last_monday + timedelta(days=6)),
                         preset="week")
    if preset == "month":
        first_this_month = today.replace(day=1)
        last_month_end = first_this_month - timedelta(days=1)
        return TimeRange(_fmt(last_month_end.replace(day=1)), _fmt(last_month_end),
                         preset="month")
    if preset == "quarter":
        start, end = _last_quarter(today)
        return TimeRange(_fmt(start), _fmt(end), preset="quarter")
    # year
    return TimeRange(f"{today.year - 1}0101", f"{today.year - 1}1231", preset="year")


def _last_quarter(today: date) -> tuple[date, date]:
    """计算上一自然季度的首日与末日。"""
    quarter_first_month = 3 * ((today.month - 1) // 3) + 1
    quarter_start = date(today.year, quarter_first_month, 1)
    prev_quarter_end = quarter_start - timedelta(days=1)
    prev_quarter_start = date(
        prev_quarter_end.year, 3 * ((prev_quarter_end.month - 1) // 3) + 1, 1
    )
    return prev_quarter_start, prev_quarter_end


def _fmt(d: date) -> str:
    """date → YYYYMMDD。"""
    return d.strftime(Config.DATE_FORMAT)
