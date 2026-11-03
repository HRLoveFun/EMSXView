"""交易员复盘台服务编排（PR-1：订单列表 + 筛选项）。

纯函数放 trader_metrics、SQL 放 trader_query；本层只做参数解析、校验、
组装 payload。缺库降级沿用 009 约定（FileNotFoundError → 由路由层 503）。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from data_access.storage.connection import AccessTier, ConnectionManager

from . import trader_metrics as tm
from . import trader_models as tmod
from . import trader_query as tq

logger = logging.getLogger(__name__)

#: 交易员视图契约版本（导出与页面同源，见 §4.14）
TRADER_SPEC_VERSION = "2026.11.03"
#: 默认日期窗口：最近 5 个交易日（§4.1）
DEFAULT_TRADING_DAYS = 5
#: 单例连接管理器（测试可整体替换；只读连接，mode=ro）
DEFAULT_MANAGER = ConnectionManager()


class DataNotReadyError(Exception):
    """默认日期范围内无任何 TCA 汇总（管道未产出）→ 路由层 503 data_not_ready。"""


def parse_multi(raw: Optional[str]) -> Optional[tuple[str, ...]]:
    """逗号分隔多值 → 去空白去重元组（空输入返回 None）。"""
    if not raw:
        return None
    values = tuple(dict.fromkeys(v.strip() for v in raw.split(",") if v.strip()))
    return values or None


def validate_options(filters: tmod.TraderFilters) -> None:
    """枚举 / 排序 / 分页白名单校验（非法值 ValueError → 路由层 422）。"""
    if filters.sort not in tq.SORT_COLUMNS:
        raise ValueError(f"sort 非法: {filters.sort!r}，可选 {sorted(tq.SORT_COLUMNS)}")
    if filters.sort_dir not in tq.SORT_DIRS:
        raise ValueError(f"sort_dir 非法: {filters.sort_dir!r}，可选 {sorted(tq.SORT_DIRS)}")
    if filters.limit < 1 or filters.limit > tq.MAX_LIMIT:
        raise ValueError(f"limit 必须在 1..{tq.MAX_LIMIT}，得到 {filters.limit}")
    if filters.offset < 0:
        raise ValueError(f"offset 不能为负: {filters.offset}")
    if filters.completion_bucket and filters.completion_bucket not in tm.COMPLETION_BUCKETS:
        raise ValueError(
            f"completion_bucket 非法: {filters.completion_bucket!r}，"
            f"可选 {list(tm.COMPLETION_BUCKETS)}"
        )
    if filters.quality and filters.quality not in tm.QUALITY_FILTERS:
        raise ValueError(f"quality 非法: {filters.quality!r}，可选 {list(tm.QUALITY_FILTERS)}")


def _resolve_dates(
    conn, start_date: Optional[str], end_date: Optional[str],
) -> tuple[str, str]:
    """日期缺省 → 最近 5 个交易日；区间为空 → DataNotReadyError。"""
    if start_date and end_date:
        return start_date, end_date
    dates = tq.recent_trading_dates(conn, DEFAULT_TRADING_DAYS)
    if not dates:
        raise DataNotReadyError(
            "tca_route_summary 无可用交易日（数据尚未生成）；"
            "数据更新维护的唯一写入方是独立仓库 EMSXDataPipeline。"
        )
    return (start_date or dates[0]), (end_date or dates[-1])


def build_filters(
    conn,
    *,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    trader: Optional[str] = None,
    ticker: Optional[str] = None,
    side: Optional[str] = None,
    strategy_type: Optional[str] = None,
    algo: Optional[str] = None,
    broker: Optional[str] = None,
    completion_bucket: Optional[str] = None,
    quality: Optional[str] = None,
    sort: str = "date",
    sort_dir: str = "desc",
    limit: int = 50,
    offset: int = 0,
) -> tmod.TraderFilters:
    """原始查询参数 → TraderFilters（含日期默认值与白名单校验）。"""
    resolved_start, resolved_end = _resolve_dates(conn, start_date, end_date)
    filters = tmod.TraderFilters(
        start_date=resolved_start, end_date=resolved_end,
        trader=parse_multi(trader), ticker=parse_multi(ticker),
        side=parse_multi(side), strategy_type=parse_multi(strategy_type),
        algo=parse_multi(algo), broker=parse_multi(broker),
        completion_bucket=completion_bucket, quality=quality,
        sort=sort, sort_dir=sort_dir, limit=limit, offset=offset,
    )
    validate_options(filters)
    return filters


def _row_to_model(row: dict[str, Any]) -> tmod.TraderOrderRow:
    """SQL 聚合行 → 列表行模型（质量徽章由纯函数判定）。"""
    level, flags = tm.quality_flags(row)
    return tmod.TraderOrderRow(
        order_id=str(row.get("OrderId") or ""),
        order_as_of_date=str(row.get("order_as_of_date") or ""),
        trader_name=row.get("trader_name"),
        equ_ticker=row.get("equ_ticker"),
        exchange=row.get("exchange"),
        side=row.get("side"),
        strategy_type=row.get("strategy_type"),
        algo=row.get("algo"),
        broker=row.get("broker"),
        route_count=int(row.get("route_count") or 0),
        fill_count=row.get("fill_count"),
        route_shares=row.get("route_shares"),
        fill=row.get("fill"),
        completion=row.get("completion"),
        vwap=row.get("vwap"),
        arrival_cost_bps=row.get("arrival_cost_bps"),
        opportunity_cost=row.get("opportunity_cost"),
        order_duration_sec=row.get("order_duration_sec"),
        mixed=bool(row.get("mixed")),
        quality_level=level,
        quality_flags=flags,
    )


def _manager(mgr: Optional[ConnectionManager]) -> ConnectionManager:
    return mgr or DEFAULT_MANAGER


def _page_payload(filters: tmod.TraderFilters, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """组装列表 payload：kpi / probes 基于全筛选范围，orders 为当前页切片。"""
    models = [_row_to_model(r) for r in rows]
    page = models[filters.offset:filters.offset + filters.limit]
    return {
        "filters": filters.to_payload(),
        "generated_at": datetime.now().isoformat(),
        "total_orders": len(models),
        "offset": filters.offset,
        "limit": filters.limit,
        "kpi": tm.compute_kpi(rows),
        "probes": {
            "checks": tm.compute_probes(rows),
            "spec_version": TRADER_SPEC_VERSION,
        },
        "orders": [m.to_payload() for m in page],
    }


def build_order_page(
    filters: tmod.TraderFilters, mgr: Optional[ConnectionManager] = None,
) -> dict[str, Any]:
    """已构造筛选 → 订单列表 payload（测试与对账入口）。"""
    manager = _manager(mgr)
    conn = manager.get_connection("fill_bdib", AccessTier.READ)
    try:
        rows = tq.query_order_rows(conn, filters)
    finally:
        conn.close()
    return _page_payload(filters, rows)


def build_filter_options(
    *,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    ticker_prefix: Optional[str] = None,
    mgr: Optional[ConnectionManager] = None,
) -> dict[str, list[str]]:
    """筛选下拉（§3.4.5）：traders/strategy_types 逐查询，其余复用维度表。"""
    manager = _manager(mgr)
    conn = manager.get_connection("fill_bdib", AccessTier.READ)
    try:
        return tq.query_filter_options(conn, start_date, end_date, ticker_prefix)
    finally:
        conn.close()


def build_order_page_from_query(
    mgr: Optional[ConnectionManager] = None, **raw: Any,
) -> dict[str, Any]:
    """路由入口：原始查询参数 → 校验 → 订单列表 payload（单次连接内完成）。"""
    manager = _manager(mgr)
    conn = manager.get_connection("fill_bdib", AccessTier.READ)
    try:
        filters = build_filters(conn, **raw)
        rows = tq.query_order_rows(conn, filters)
    finally:
        conn.close()
    return _page_payload(filters, rows)
