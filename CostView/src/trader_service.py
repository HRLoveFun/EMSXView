"""交易员复盘台服务编排（PR-1：订单列表 + 筛选项）。

纯函数放 trader_metrics、SQL 放 trader_query；本层只做参数解析、校验、
组装 payload。缺库降级沿用 009 约定（FileNotFoundError → 由路由层 503）。
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import math
import time
from datetime import datetime, timedelta
from typing import Any, Iterator, Optional

from data_access.storage.connection import AccessTier, ConnectionManager

from . import trader_metrics as tm
from . import trader_models as tmod
from . import trader_query as tq
# 210 §4.11：订单级异常摘要复用路由级同一套阈值引擎（禁止第二套常量）
from .monitoring.anomaly_query import (
    ThresholdRules,
    evaluate_metrics,
    order_rule_values,
)

logger = logging.getLogger(__name__)

#: 交易员视图契约版本（导出与页面同源，见 §4.14）
#: 2026.11.03：PR-1 列表 + KPI + 探针
#: 2026.11.04：PR-5 订单级异常摘要（anomaly_summary）+ 异常订单 KPI 并集口径
TRADER_SPEC_VERSION = "2026.11.04"
#: 默认日期窗口：最近 5 个交易日（§4.1）
DEFAULT_TRADING_DAYS = 5
#: 单例连接管理器（测试可整体替换；只读连接，mode=ro）
DEFAULT_MANAGER = ConnectionManager()


class DataNotReadyError(Exception):
    """默认日期范围内无任何 TCA 汇总（管道未产出）→ 路由层 503 data_not_ready。"""


class OrderNotFound(Exception):
    """订单不存在（或 order_as_of_date 不匹配）→ 路由层 404。"""


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
    exchange: Optional[str] = None,
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
    order_id: Optional[str] = None,
) -> tmod.TraderFilters:
    """原始查询参数 → TraderFilters（含日期默认值与白名单校验）。"""
    resolved_start, resolved_end = _resolve_dates(conn, start_date, end_date)
    filters = tmod.TraderFilters(
        start_date=resolved_start, end_date=resolved_end, order_id=order_id,
        trader=parse_multi(trader), ticker=parse_multi(ticker),
        exchange=parse_multi(exchange),
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


def _page_payload(
    filters: tmod.TraderFilters, rows: list[dict[str, Any]],
    manager: Optional[ConnectionManager] = None,
) -> dict[str, Any]:
    """组装列表 payload：kpi/probes 基于全筛选范围；当前页逐笔补列后再出页行。"""
    models = [_row_to_model(r) for r in rows]
    page = models[filters.offset:filters.offset + filters.limit]
    ctx = _page_fill_context(
        manager, [(m.order_id, m.order_as_of_date) for m in page],
    ) if manager else {}
    for model in page:
        _apply_fill_context(model, ctx.get(model.order_id))
    anomaly = _anomaly_summary(rows)
    kpi = tm.compute_kpi(rows, anomaly)
    kpi["passive_ratio"] = _passive_kpi(ctx)
    kpi["release_delay_p90"] = _delay_kpi(ctx, len(page))
    return {
        "filters": filters.to_payload(),
        "generated_at": datetime.now().isoformat(),
        "total_orders": len(models),
        "offset": filters.offset,
        "limit": filters.limit,
        "kpi": kpi,
        "probes": {
            "checks": tm.compute_probes(rows, _fill_quality_probe(ctx, filters)),
            "spec_version": TRADER_SPEC_VERSION,
        },
        "anomaly_summary": anomaly,
        "orders": [m.to_payload() for m in page],
    }


def _anomaly_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """订单级异常摘要（§4.11）：默认阈值 + 订单级取值 → 聚合。

    阈值取 ``ThresholdRules.from_payload(None)``（与 Report 默认一致）；自定义阈值
    的联动属 v1（Report 表单已可改，交易员页暂不暴露），差异在 UI 注明。
    """
    rules = ThresholdRules.from_payload(None)
    return tm.compute_anomaly_summary(
        rows, lambda row: evaluate_metrics(order_rule_values(row), rules),
    )


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
    return _page_payload(filters, rows, manager)


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
    return _page_payload(filters, rows, manager)


# ── 210 §3.4.4 / §4.14：CSV 导出（订单汇总 / 成交明细）──────────────────────

#: 导出行数上限（§3.4.4：超出返回 422 提示缩小范围，不静默截断）
EXPORT_ORDER_CAP = 50_000
EXPORT_FILL_CAP = 500_000

#: 订单汇总列（§4.14，顺序即 CSV 列顺序）
EXPORT_ORDER_COLUMNS: tuple[str, ...] = (
    "order_id", "order_as_of_date", "trader_name", "equ_ticker", "exchange", "side",
    "strategy_type", "algo", "broker", "route_count", "fill_count", "route_shares",
    "fill", "completion", "vwap", "arrival_cost_bps", "wagner_is_bps", "delay_bps",
    "trading_bps", "opportunity_bps", "residual_bps", "fill_span_sec",
    "speed_shares_per_min", "passive_ratio", "passive_cost_bps",
    "aggressive_cost_bps", "unknown_share", "order_to_route_sec",
    "route_to_first_fill_sec", "peer_n", "quality_flags",
)

#: 成交明细列（§4.14）
EXPORT_FILL_COLUMNS: tuple[str, ...] = (
    "order_id", "route_id", "fill_id", "ts_local", "price", "shares",
    "liquidity_raw", "liquidity_class", "last_capacity", "last_market",
    "exchange_exec_time", "route_as_of_time",
)


class ExportTooLargeError(ValueError):
    """导出超过行数上限 → 路由层 422（明确报错，不静默截断）。"""


def _chunks(values: list[Any], size: int) -> Iterator[list[Any]]:
    """按固定大小切分（导出逐笔按 OrderId 键集分批，守住 SQLite 变量上限）。"""
    for start in range(0, len(values), size):
        yield values[start:start + size]


#: 公式注入起始字符（Excel 会忽略前导空白/制表符，遇到时再 lstrip 判断）
_CSV_INJECTION_HEADS = frozenset("=+-@")


def _csv_cell(value: Any) -> Any:
    """CSV 单元格：None → 空；文本以 ``= + - @`` 开头时前置 ``'`` 防公式注入。

    数字不加固：负数是本层计算出的可信数值，前置 ``'`` 会把它变成文本、破坏
    Excel 汇总；注入风险只来自用户可控的文本字段（order_id / ticker / broker 等）。
    500k 笔导出时本函数会被调用数百万次，故用 ``type is`` 与首字符快路径。
    """
    if value is None:
        return ""
    if value.__class__ is str:
        head = value[:1]
        if head in _CSV_INJECTION_HEADS:
            return f"'{value}"
        # Excel 会忽略前导空白/制表符，"\t=cmd" 同样触发公式
        if head.isspace() and value.lstrip()[:1] in _CSV_INJECTION_HEADS:
            return f"'{value}"
        return value
    if value.__class__ is float:
        return value if math.isfinite(value) else ""
    if value.__class__ is bool:
        return "true" if value else "false"
    return value


def _csv_text(value: Any) -> Any:
    """只对文本做公式注入加固（逐笔热路径：数值原样交给 csv writer，None → 空）。"""
    if value.__class__ is str:
        head = value[:1]
        if head in _CSV_INJECTION_HEADS:
            return f"'{value}"
        if head.isspace() and value.lstrip()[:1] in _CSV_INJECTION_HEADS:
            return f"'{value}"
    return value


def _csv_header_text(
    kind: str,
    filters: tmod.TraderFilters,
    columns: tuple[str, ...],
    generated_at: str,
) -> str:
    """CSV 前导块：3 行 ``#`` 注释 + 英文表头（数据行按块另行输出）。"""
    snapshot = {"kind": kind, **filters.to_payload()}
    header = [
        f"# spec_version={TRADER_SPEC_VERSION}",
        f"# generated_at={generated_at}",
        "# filters=" + json.dumps(
            snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ),
    ]
    buffer = io.StringIO()
    for line in header:
        buffer.write(line + "\n")
    csv.writer(buffer, lineterminator="\n").writerow(columns)
    return buffer.getvalue()


def _csv_lists_text(rows: list[list[Any]]) -> str:
    """一块已按列顺序排列、且已做注入加固的数据行（逐笔导出热路径）。"""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerows(rows)
    return buffer.getvalue()


def _csv_cell_lists_text(rows: list[list[Any]]) -> str:
    """一块原始值行 → CSV（订单汇总：数值需处理 NaN，故逐格经 ``_csv_cell``）。"""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerows([[_csv_cell(value) for value in row] for row in rows])
    return buffer.getvalue()


def _export_filename(
    kind: str, filters: tmod.TraderFilters, generated_at: str,
) -> str:
    """文件名短哈希：筛选快照 + 生成时刻（流式输出下无法回算全文哈希）。"""
    payload = json.dumps(
        {"kind": kind, **filters.to_payload(), "generated_at": generated_at},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:8]
    return f"trader_{kind}_{filters.start_date}_{filters.end_date}_{digest}.csv"


def _csv_prelude(
    kind: str,
    filters: tmod.TraderFilters,
    columns: tuple[str, ...],
    generated_at: str,
) -> bytes:
    """首块：BOM + 3 行注释 + 表头（后续块只含数据行）。"""
    text = _csv_header_text(kind, filters, columns, generated_at)
    return (chr(0xFEFF) + text).encode("utf-8")


def _export_fill_context(
    proc_conn: Any, raw_conn: Any, keys: list[tuple[str, str]],
) -> dict[str, dict[str, Any]]:
    """单块逐笔上下文（span / 速度 / 被动占比 / 交付延迟）。

    与列表当前页共用 ``_context_from_aggs``（同一口径）；连接由调用方按块
    创建/关闭（不能跨 ``yield`` 持有，见 ``_export_connections``）。
    ``order_to_route_sec`` 另由 raw_fills 的 NY 时刻 GROUP BY 得到。
    无逐笔的订单也建空条目，``_order_export_values`` 以 ``total_shares == 0``
    输出空值「无逐笔」；「有逐笔但 Liquidity 全缺」时 total_shares > 0，
    被动占比为 0.0（与列表页一致）。
    """
    ctx = _context_from_aggs(
        tq.query_page_fill_agg(proc_conn, keys),
        tq.query_page_liquidity_agg(raw_conn, keys),
    )
    for row in tq.query_export_latency_agg(raw_conn, keys):
        order_create = _parse_instant(row.get("order_create"))
        route_create = _parse_instant(row.get("route_create"))
        if order_create is None or route_create is None:
            continue
        entry = ctx.setdefault(str(row.get("OrderId")), {})
        entry["order_to_route_sec"] = (route_create - order_create).total_seconds()
    for order_id, _order_as_of_date in keys:
        ctx.setdefault(order_id, {})
    return ctx


def _order_export_values(
    row: dict[str, Any], ctx: Optional[dict[str, Any]],
) -> list[Any]:
    """订单聚合行 → CSV 值列表（顺序 = ``EXPORT_ORDER_COLUMNS``）。

    与列表/详情同一口径；不可得列输出空值。直接产出值列表（而非记录 dict
    再按列名取），50k 单导出时省掉 31 次/行的键查找与 dict 构造。
    """
    cost = tm.cost_decomposition(
        delay_cost=row.get("delay_cost"), trading_cost=row.get("trading_cost"),
        opportunity_cost=row.get("opportunity_cost"),
        wagner_is_bps=row.get("wagner_is_bps"),
        route_shares=row.get("route_shares"), p_decision=row.get("p_decision"),
        arrival_cost_bps=row.get("arrival_cost_bps"),
        completion=row.get("completion"),
    )
    _, flags = tm.quality_flags(row)
    ctx = ctx or {}
    total_shares = float(ctx.get("total_shares") or 0.0)
    unknown_share = (ctx.get("unknown_shares", 0.0) / total_shares) if total_shares else None
    # 与列表页 `_apply_fill_context` 同界：未知 Liquidity 占比 >10% 打徽章
    if unknown_share is not None and unknown_share > tm.LIQUIDITY_UNKNOWN_BADGE:
        flags.append("liquidity_unknown")
    return [
        row.get("OrderId"),
        row.get("order_as_of_date"),
        row.get("trader_name"),
        row.get("equ_ticker"),
        row.get("exchange"),
        row.get("side"),
        row.get("strategy_type"),
        row.get("algo"),
        row.get("broker"),
        row.get("route_count"),
        row.get("fill_count"),
        row.get("route_shares"),
        row.get("fill"),
        row.get("completion"),
        row.get("vwap"),
        row.get("arrival_cost_bps"),
        row.get("wagner_is_bps"),
        cost["delay_bps"],
        cost["trading_bps"],
        cost["opportunity_bps"],
        cost["residual_bps"],
        ctx.get("fill_span_sec"),
        ctx.get("speed_shares_per_min"),
        # 与列表页 `_apply_fill_context` 同界：有逐笔但 Liquidity 全缺 → 0.0（不写空）
        (
            ctx.get("passive_shares", 0.0) / total_shares
            if total_shares else None
        ),
        # 类别成本需「逐笔价格 × Liquidity 分类」联查；批量导出不拉全量逐笔，
        # 与页面列表同口径留空（详情端点可精确计算）。
        None,
        None,
        unknown_share,
        ctx.get("order_to_route_sec"),
        ctx.get("route_to_first_fill_sec"),
        # peer 需逐单 180 天同类聚合，属详情懒加载；批量导出不计算。
        None,
        ";".join(flags) or None,
    ]


def _fill_records_chunk(
    proc_conn: Any, raw_conn: Any,
    chunk: list[tuple[str, str]], remaining: int,
) -> list[list[Any]]:
    """单块逐笔导出行（processed_fills 主表 + raw_fills 补 Liquidity）。

    直接产出按 ``EXPORT_FILL_COLUMNS`` 顺序、已做注入加固的值列表：500k 行时
    「tuple → 按键名取值的 dict → 再按列名取值」两跳是主要 Python 开销。
    """
    columns, processed_rows = tq.query_export_fills(proc_conn, chunk, remaining)
    if not columns:
        return []
    idx = {name: i for i, name in enumerate(columns)}
    i_oid, i_rid, i_fid = idx["OrderId"], idx["RouteId"], idx["FillId"]
    i_date = idx["order_as_of_date"]
    i_ts, i_exec = idx.get("local_fill_datetime"), idx.get("exchange_exec_time")
    i_price, i_shares = idx.get("FillPrice"), idx.get("FillShares")
    i_cap, i_mkt = idx.get("LastCapacity"), idx.get("LastMarket")
    i_route_asof = idx.get("route_as_of_time")

    chunk_set = set(chunk)
    processed = [
        row for row in processed_rows
        # OrderId 在同一交易日集内全局唯一；跨日同号按 (id, date) 精确归属
        if (str(row[i_oid]), str(row[i_date])) in chunk_set
    ]
    if len(processed) > remaining:
        raise ExportTooLargeError(
            f"导出成交明细超过上限 {EXPORT_FILL_CAP:,} 行，"
            "请缩小日期范围或加筛选条件（或指定 order_id 导出单笔）"
        )
    # Liquidity 只对已归属本批的逐笔补列：raw_fills 按 OrderId 取，同号跨日行
    # 会混入，按键过滤后既避免无谓内存也保证与 processed 一一对应
    processed_keys = {
        (str(row[i_oid]), str(row[i_rid]), str(row[i_fid]), str(row[i_date]))
        for row in processed
    }
    raw_by_key: dict[tuple[str, str, str, str], Any] = {}
    for order_id, route_id, fill_id, oad, liquidity in (
        tq.query_export_raw_fills(raw_conn, chunk)
    ):
        key = (str(order_id), str(route_id), str(fill_id), str(oad))
        if key in processed_keys:
            raw_by_key[key] = liquidity

    rows: list[list[Any]] = []
    for row in processed:
        key = (str(row[i_oid]), str(row[i_rid]), str(row[i_fid]), str(row[i_date]))
        liquidity = raw_by_key.get(key)
        ts_local = (row[i_ts] if i_ts is not None else None) or (
            row[i_exec] if i_exec is not None else None
        )
        exec_time = row[i_exec] if i_exec is not None else None
        rows.append([
            _csv_text(row[i_oid]),
            _csv_text(row[i_rid]),
            _csv_text(row[i_fid]),
            _csv_text(ts_local),
            row[i_price] if i_price is not None else None,
            row[i_shares] if i_shares is not None else None,
            _csv_text(liquidity),
            _csv_text(tm.liquidity_class(liquidity)),
            _csv_text(row[i_cap]) if i_cap is not None else None,
            _csv_text(row[i_mkt]) if i_mkt is not None else None,
            _csv_text(exec_time),
            _csv_text(row[i_route_asof]) if i_route_asof is not None else None,
        ])
    return rows


def _fill_export_count(proc_conn: Any, keys: list[tuple[str, str]]) -> int:
    """按导出键集精确计数（跨日同号只算本批日期，与流式输出同一集合）。"""
    key_set = set(keys)
    total = 0
    for chunk in _chunks(keys, tq.EXPORT_KEY_CHUNK):
        for row in tq.query_export_fill_counts(proc_conn, chunk):
            if (str(row.get("OrderId")), str(row.get("order_as_of_date"))) in key_set:
                total += int(row.get("n") or 0)
    return total


def _iter_orders_csv(
    manager: ConnectionManager,
    filters: tmod.TraderFilters, rows: list[dict[str, Any]], generated_at: str,
) -> Iterator[bytes]:
    """订单汇总 CSV 生成器：首块表头，之后每块 400 单（内存与块成正比）。

    连接在**每块**的 ``next()`` 调用内创建并关闭，绝不跨 ``yield`` 持有：
    StreamingResponse 用 ``anyio.to_thread.run_sync`` 分次驱动同步生成器，
    相邻两次 ``next()`` 可能落在不同工作线程，跨线程复用 sqlite 连接会抛
    ``ProgrammingError``（``check_same_thread``）。
    """
    columns = EXPORT_ORDER_COLUMNS
    yield _csv_prelude("orders", filters, columns, generated_at)
    for chunk in _chunks(rows, tq.EXPORT_KEY_CHUNK):
        keys = [
            (str(row.get("OrderId")), str(row.get("order_as_of_date")))
            for row in chunk
        ]
        proc_conn, raw_conn = _export_connections(manager)
        try:
            ctx = _export_fill_context(proc_conn, raw_conn, keys)
        finally:
            proc_conn.close()
            raw_conn.close()
        records = [
            _order_export_values(row, ctx.get(str(row.get("OrderId"))))
            for row in chunk
        ]
        yield _csv_cell_lists_text(records).encode("utf-8")


def _iter_fills_csv(
    manager: ConnectionManager,
    filters: tmod.TraderFilters, keys: list[tuple[str, str]], generated_at: str,
) -> Iterator[bytes]:
    """成交明细 CSV 生成器：首块表头，之后每块 400 单。

    与 ``_iter_orders_csv`` 同理，连接在每块 ``next()`` 内创建/关闭，
    不跨 ``yield`` 持有（Starlette 线程池可能在不同线程完成下一次迭代）。
    """
    columns = EXPORT_FILL_COLUMNS
    yield _csv_prelude("fills", filters, columns, generated_at)
    written = 0
    for chunk in _chunks(keys, tq.EXPORT_KEY_CHUNK):
        proc_conn, raw_conn = _export_connections(manager)
        try:
            rows = _fill_records_chunk(
                proc_conn, raw_conn, chunk, EXPORT_FILL_CAP - written,
            )
        finally:
            proc_conn.close()
            raw_conn.close()
        written += len(rows)
        yield _csv_lists_text(rows).encode("utf-8")


def _export_connections(manager: ConnectionManager) -> tuple[Any, Any]:
    """单块导出用的只读连接（processed_fills / raw_fills），由调用方就地关闭。

    必须在**使用它的同一次** ``next()`` 调用内创建/使用/关闭：SQLite 默认
    ``check_same_thread=True``，而 StreamingResponse 会把每次 ``next()`` 派发到
    线程池的不同工作线程，跨 ``yield`` 持有的连接会在下一次迭代时抛
    ``ProgrammingError``。缺库检查由 ``_validate_export_sources`` 在响应前完成。
    """
    return (
        manager.get_connection("processed_fills", AccessTier.READ),
        manager.get_connection("raw_fills", AccessTier.READ),
    )


def _validate_export_sources(manager: ConnectionManager) -> None:
    """响应开始前确认逐笔两库可开（缺库 → ``FileNotFoundError`` → 路由 503）。"""
    for key in ("processed_fills", "raw_fills"):
        manager.get_connection(key, AccessTier.READ).close()


def stream_export_csv(
    kind: str,
    *,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    trader: Optional[str] = None,
    ticker: Optional[str] = None,
    exchange: Optional[str] = None,
    side: Optional[str] = None,
    strategy_type: Optional[str] = None,
    algo: Optional[str] = None,
    broker: Optional[str] = None,
    completion_bucket: Optional[str] = None,
    quality: Optional[str] = None,
    sort: str = "date",
    sort_dir: str = "desc",
    order_id: Optional[str] = None,
    mgr: Optional[ConnectionManager] = None,
) -> tuple[Iterator[bytes], str]:
    """导出的流式入口（§3.4.4 / §8 性能预算）：``(chunks, filename)``。

    - 校验、行数上限与连接可用性在返回生成器前完成：所有错误仍走路由层
      422/404/503，不会出现「200 状态 + 半截 CSV」；
    - 数据按 400 单一块产出（``EXPORT_KEY_CHUNK``），内存不随 50k/500k 总量增长；
    - 与列表端点共用 ``build_filters``（同一日期默认值、枚举白名单与维度语义）。
    """
    if kind not in ("orders", "fills"):
        raise ValueError(f"kind 非法: {kind!r}，可选 ['orders', 'fills']")
    manager = _manager(mgr)
    conn = manager.get_connection("fill_bdib", AccessTier.READ)
    try:
        if order_id:
            routes = tq.query_order_routes(conn, order_id)
            if not routes:
                raise OrderNotFound(f"订单不存在: {order_id}")
            if not (start_date and end_date):
                dates = sorted({
                    str(route.get("order_as_of_date"))
                    for route in routes if route.get("order_as_of_date")
                })
                if dates:
                    start_date = start_date or dates[0]
                    end_date = end_date or dates[-1]
        filters = build_filters(
            conn, start_date=start_date, end_date=end_date,
            trader=trader, ticker=ticker, exchange=exchange, side=side,
            strategy_type=strategy_type, algo=algo, broker=broker,
            completion_bucket=completion_bucket, quality=quality,
            sort=sort, sort_dir=sort_dir, order_id=order_id,
        )
        rows = tq.query_order_rows(conn, filters)
    finally:
        conn.close()

    generated_at = datetime.now().isoformat()
    filename = _export_filename(kind, filters, generated_at)
    _validate_export_sources(manager)

    if kind == "orders":
        if len(rows) > EXPORT_ORDER_CAP:
            raise ExportTooLargeError(
                f"导出订单数 {len(rows):,} 超过上限 {EXPORT_ORDER_CAP:,}，"
                "请缩小日期范围或加筛选条件"
            )
        return _iter_orders_csv(manager, filters, rows, generated_at), filename

    keys = sorted({
        (str(row.get("OrderId")), str(row.get("order_as_of_date")))
        for row in rows
    })
    proc_conn = manager.get_connection("processed_fills", AccessTier.READ)
    try:
        total = _fill_export_count(proc_conn, keys)
    finally:
        proc_conn.close()
    if total > EXPORT_FILL_CAP:
        raise ExportTooLargeError(
            f"导出成交明细 {total:,} 行超过上限 {EXPORT_FILL_CAP:,} 行，"
            "请缩小日期范围或加筛选条件（或指定 order_id 导出单笔）"
        )
    return _iter_fills_csv(manager, filters, keys, generated_at), filename


def build_export_csv(
    kind: str,
    *,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    trader: Optional[str] = None,
    ticker: Optional[str] = None,
    exchange: Optional[str] = None,
    side: Optional[str] = None,
    strategy_type: Optional[str] = None,
    algo: Optional[str] = None,
    broker: Optional[str] = None,
    completion_bucket: Optional[str] = None,
    quality: Optional[str] = None,
    sort: str = "date",
    sort_dir: str = "desc",
    order_id: Optional[str] = None,
    mgr: Optional[ConnectionManager] = None,
) -> tuple[bytes, str]:
    """一次性取回完整 CSV（测试/脚本便利入口；HTTP 路由用 ``stream_export_csv``）。"""
    chunks, filename = stream_export_csv(
        kind,
        start_date=start_date, end_date=end_date,
        trader=trader, ticker=ticker, exchange=exchange, side=side,
        strategy_type=strategy_type, algo=algo, broker=broker,
        completion_bucket=completion_bucket, quality=quality,
        sort=sort, sort_dir=sort_dir, order_id=order_id, mgr=mgr,
    )
    return b"".join(chunks), filename


# ── 订单详情与逐笔补列（PR-2）─────────────────────────────────────────────


def _read(manager: ConnectionManager, key: str, fetch) -> list[dict[str, Any]]:
    """跨库只读取数（缺库/缺表由查询层降级空列表）。"""
    conn = manager.get_connection(key, AccessTier.READ)
    try:
        return fetch(conn)
    finally:
        conn.close()


def _time_sec(value: Any) -> Optional[float]:
    """``HH:MM:SS[.sss]`` / ``YYYY-MM-DD HH:MM:SS`` → 当日秒；解析失败 None。"""
    if not value:
        return None
    text = str(value).strip()
    if " " in text:
        text = text.split(" ")[-1]
    parts = text.split(":")
    if len(parts) < 2:
        return None
    try:
        hour, minute = int(parts[0]), int(parts[1])
        second = float(parts[2]) if len(parts) > 2 else 0.0
    except ValueError:
        return None
    return hour * 3600.0 + minute * 60.0 + second


def _parse_instant(value: Any) -> Optional[datetime]:
    """ISO 8601（含时区偏移）→ datetime；NY 时间戳差值与时区偏移无关。"""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).strip())
    except ValueError:
        return None


def _fill_models(
    processed: list[dict[str, Any]], raw: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """逐笔模型：processed_fills 为主表，raw_fills 按 (RouteId, FillId) 补 Liquidity。"""
    raw_by_key = {(str(r.get("RouteId")), str(r.get("FillId"))): r for r in raw}
    models: list[dict[str, Any]] = []
    for p in processed:
        raw_row = raw_by_key.get((str(p.get("RouteId")), str(p.get("FillId"))), {})
        liquidity_raw = raw_row.get("Liquidity")
        models.append({
            "route_id": p.get("RouteId"),
            "fill_id": p.get("FillId"),
            "ts_local": p.get("local_fill_datetime") or p.get("exchange_exec_time"),
            "ts_sec": _time_sec(p.get("exchange_exec_time")),
            "route_as_of_sec": _time_sec(p.get("route_as_of_time")),
            "price": p.get("FillPrice"),
            "shares": p.get("FillShares"),
            "is_closing_auction": bool(p.get("is_closing_auction")),
            "liquidity_raw": liquidity_raw,
            "liquidity_class": tm.liquidity_class(liquidity_raw),
        })
    return models


def _latency_numbers(
    fills: list[dict[str, Any]], raw: list[dict[str, Any]], algo: Optional[str],
) -> dict[str, Any]:
    """延迟三段（§4.9）：order→route / route→首笔 / 首笔非竞价（连续段）。"""
    def _min_instant(field: str) -> Optional[datetime]:
        values = [v for v in (_parse_instant(r.get(field)) for r in raw) if v]
        return min(values) if values else None

    order_create = _min_instant("NyOrderCreateAsOfDateTime")
    route_create = _min_instant("NyTranCreateAsOfDateTime")
    first_fill = _min_instant("DateTimeOfFill")
    route_secs = [f.get("route_as_of_sec") for f in fills if f.get("route_as_of_sec") is not None]
    cont = next((f for f in fills if not f.get("is_closing_auction")), None)
    return tm.latency_block(
        order_to_route_sec=(
            (route_create - order_create).total_seconds()
            if (order_create and route_create) else None
        ),
        route_to_first_fill_sec=(
            (first_fill - route_create).total_seconds()
            if (route_create and first_fill) else None
        ),
        first_continuous_fill_sec=(
            (cont["ts_sec"] - min(route_secs)) if (cont and route_secs) else None
        ),
        algo=algo,
        first_fill_is_auction=bool(fills and fills[0].get("is_closing_auction")),
    )


def _detail_quality(
    head: dict[str, Any], liquidity: dict[str, Any], latency: dict[str, Any],
) -> dict[str, Any]:
    """详情质量徽章（§4.12）：订单级 + 逐笔级（liquidity_unknown / latency_anomaly）。"""
    level, flags = tm.quality_flags(head)
    entries = [
        {"id": fid, "severity": level if level != "clean" else "info", "detail": None}
        for fid in flags
    ]
    unknown = liquidity.get("unknown_share")
    if unknown is not None and unknown > tm.LIQUIDITY_UNKNOWN_BADGE:
        severity = "warn" if unknown > tm.LIQUIDITY_UNKNOWN_WARN else "info"
        entries.append({"id": "liquidity_unknown", "severity": severity,
                        "detail": f"{unknown * 100:.0f}% 成交的 Liquidity 未识别"})
        level = "warn" if severity == "warn" and level == "clean" else level
    if latency.get("latency_anomaly"):
        entries.append({"id": "latency_anomaly", "severity": "warn",
                        "detail": "首笔非竞价成交早于路由下达 >1s"})
        level = "warn" if level == "clean" else level
    if latency.get("scheduled"):
        entries.append({"id": "scheduled_close", "severity": "info",
                        "detail": "按计划在收盘竞价成交"})
    return {"level": level, "flags": entries}


def _resolve_order_date(
    routes: list[dict[str, Any]], order_as_of_date: Optional[str],
) -> str:
    """订单交易日：显式参数优先；跨日订单必须显式指定（否则 ValueError）。"""
    dates = {str(r.get("order_as_of_date")) for r in routes}
    if order_as_of_date:
        if order_as_of_date not in dates:
            raise OrderNotFound(f"订单在 {order_as_of_date} 无路由记录")
        return order_as_of_date
    if len(dates) != 1:
        raise ValueError("订单跨多个交易日，请显式指定 order_as_of_date")
    return dates.pop()


def _par_rate_check(
    head: dict[str, Any], timeline: dict[str, Any],
) -> Optional[dict[str, Any]]:
    """逐桶参与率 vs par_rate（§4.2 验收）：单路由 0.99–1.01，越界标窗口差异。"""
    if head.get("route_count") != 1:
        return {"note": "多路由订单：分母为订单窗口并集，不与单路由 par_rate 直接可比"}
    par = head.get("par_rate")
    buckets = timeline.get("buckets") or []
    market = sum((b.get("market_volume") or 0.0) for b in buckets)
    fills_total = sum((b.get("fill") or 0.0) for b in buckets)
    if not par or not market:
        return None
    window = fills_total / market
    ratio = window / par
    return {
        "route_par_rate": par, "window_participation": window, "ratio": ratio,
        "note": None if 0.99 <= ratio <= 1.01 else "窗口/时区差异",
    }


def _routes_payload(routes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """路由子表（§3.4.2）：completion = fill / route_shares。"""
    out = []
    for r in routes:
        shares = r.get("RouteShares")
        fill = r.get("fill")
        out.append({
            "route_id": r.get("RouteId"), "broker": r.get("Broker"),
            "algo": r.get("algo"), "route_shares": shares, "fill": fill,
            "completion": (fill / shares) if (shares and fill is not None) else None,
            "arrival_cost_bps": r.get("arrival_cost_bps"),
            "wagner_is_bps": r.get("wagner_is_bps"),
        })
    return out


def _detail_payload(
    head: dict[str, Any], routes: list[dict[str, Any]],
    processed: list[dict[str, Any]], raw: list[dict[str, Any]],
    bars_raw: list[dict[str, Any]], bucket_min: int,
) -> dict[str, Any]:
    """订单详情 payload 组装（§3.4.2；daily 随 P2 批次接入，此处为 None）。"""
    fills = _fill_models(processed, raw)
    bars = [
        {"ts_sec": _time_sec(b.get("mkt_timestamp")), "volume": b.get("volume")}
        for b in bars_raw
    ]
    timeline = tm.bucket_fills(fills, bucket_min, head.get("route_shares"), bars)
    timeline["benchmarks"] = {
        k: head.get(k) for k in ("p_decision", "p_arrival", "p_avg", "p_close", "limit_price")
    }
    timeline["par_rate_check"] = _par_rate_check(head, timeline)
    liquidity = tm.liquidity_split(fills, head.get("p_arrival"), head.get("side"))
    latency = _latency_numbers(fills, raw, head.get("algo"))
    order_payload = _row_to_model(head).to_payload()
    order_payload.update({
        "limit_price": head.get("limit_price"), "currency": head.get("currency"),
    })
    if fills:
        ctx = _order_fill_stats(fills, raw, str(head.get("OrderId") or ""))
        order_payload["fill_span_sec"] = ctx["fill_span_sec"]
        order_payload["speed_shares_per_min"] = ctx["speed_shares_per_min"]
        total = ctx["total_shares"]
        order_payload["passive_ratio"] = (
            ctx["passive_shares"] / total if total else None
        )
    return {
        "order": order_payload,
        "routes": _routes_payload(routes),
        "fills": fills,
        "timeline": timeline,
        "cost": tm.cost_decomposition(
            delay_cost=head.get("delay_cost"), trading_cost=head.get("trading_cost"),
            opportunity_cost=head.get("opportunity_cost"),
            wagner_is_bps=head.get("wagner_is_bps"),
            route_shares=head.get("route_shares"), p_decision=head.get("p_decision"),
            arrival_cost_bps=head.get("arrival_cost_bps"),
            completion=head.get("completion"),
        ),
        "fill_stats": tm.fill_distribution(fills, head.get("route_shares")),
        "liquidity": liquidity,
        "latency": latency,
        "daily": None,
        "quality": _detail_quality(head, liquidity, latency),
    }


def build_order_detail(
    order_id: str,
    *,
    order_as_of_date: Optional[str] = None,
    bucket_min: int = tm.DEFAULT_BUCKET_MIN,
    mgr: Optional[ConnectionManager] = None,
) -> dict[str, Any]:
    """订单详情端点编排（§3.4.2）：聚合头复用列表口径，逐笔/行情跨库只读。"""
    if bucket_min not in tm.BUCKET_MINUTES:
        raise ValueError(f"bucket_min 非法: {bucket_min!r}，可选 {list(tm.BUCKET_MINUTES)}")
    manager = _manager(mgr)
    conn = manager.get_connection("fill_bdib", AccessTier.READ)
    try:
        routes = tq.query_order_routes(conn, order_id)
        if not routes:
            raise OrderNotFound(f"订单不存在: {order_id}")
        oad = _resolve_order_date(routes, order_as_of_date)
        head_rows = tq.query_order_rows(conn, tmod.TraderFilters(
            start_date=oad, end_date=oad, order_id=order_id, limit=1,
        ))
    finally:
        conn.close()
    if not head_rows:
        raise OrderNotFound(f"订单不存在: {order_id}")
    processed = _read(manager, "processed_fills",
                      lambda c: tq.query_order_fills(c, order_id, oad))
    raw = _read(manager, "raw_fills",
                lambda c: tq.query_order_raw_fills(c, order_id, oad))
    bars_raw = _read(manager, "raw_bdib",
                     lambda c: tq.query_order_bars(c, head_rows[0].get("equ_ticker") or "", oad))
    return _detail_payload(head_rows[0], routes, processed, raw, bars_raw, bucket_min)


# ── 列表当前页逐笔补列（fill_span / speed / passive_ratio）───────────────────


def _page_fill_context(
    manager: Optional[ConnectionManager], keys: list[tuple[str, str]],
) -> dict[str, dict[str, Any]]:
    """当前页逐笔上下文（聚合查询，不拉全量逐笔）：span/速度/被动占比/延迟。"""
    if not manager or not keys:
        return {}
    fill_agg = _read(manager, "processed_fills", lambda c: tq.query_page_fill_agg(c, keys))
    liq_agg = _read(manager, "raw_fills", lambda c: tq.query_page_liquidity_agg(c, keys))
    return _context_from_aggs(fill_agg, liq_agg)


def _context_from_aggs(
    fill_agg: list[dict[str, Any]], liq_agg: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """逐笔聚合行 → 订单上下文（列表当前页与 CSV 导出共用同一口径）。"""
    shares_by_order: dict[str, dict[str, float]] = {}
    for row in liq_agg:
        cls = tm.liquidity_class(row.get("Liquidity"))
        bucket = shares_by_order.setdefault(
            str(row.get("OrderId")), {"passive": 0.0, "unknown": 0.0, "total": 0.0},
        )
        shares = float(row.get("shares") or 0.0)
        bucket["total"] += shares
        if cls == "passive":
            bucket["passive"] += shares
        elif cls == "unknown":
            bucket["unknown"] += shares
    return {
        str(row.get("OrderId")): _agg_fill_ctx(row, shares_by_order.get(str(row.get("OrderId")), {}))
        for row in fill_agg
    }


def _agg_fill_ctx(row: dict[str, Any], shares: dict[str, float]) -> dict[str, Any]:
    """聚合行 → 逐笔上下文（span = 首末成交时刻差；scheduled 由调用方结合 algo 判定）。"""
    first, last = _time_sec(row.get("first_exec")), _time_sec(row.get("last_exec"))
    route_sec = _time_sec(row.get("first_route_as_of"))
    span = (last - first) if (first is not None and last is not None) else None
    gap = (first - route_sec) if (first is not None and route_sec is not None) else None
    total = shares.get("total", 0.0)
    return {
        "fill_span_sec": span,
        "speed_shares_per_min": (total / (span / 60.0)) if span else None,
        "passive_shares": shares.get("passive", 0.0),
        "unknown_shares": shares.get("unknown", 0.0),
        "total_shares": total,
        "single_fill": int(row.get("fill_n") or 0) < 2,
        # MIN(is_closing_auction) != 0 → 全部为竞价成交（列表级近似，详情端点精确）
        "all_auction": row.get("all_auction") not in (0, None),
        "scheduled": False,
        "latency_anomaly": bool(gap is not None and gap < -1.0),
        "route_to_first_fill_sec": gap,
    }


def _order_fill_stats(
    fills: list[dict[str, Any]], raw: list[dict[str, Any]], order_id: str,
) -> dict[str, Any]:
    """单订单逐笔摘要（列表补列与 KPI 共用）。"""
    split = tm.liquidity_split(fills, None, None)
    ts = [f["ts_sec"] for f in fills if f.get("ts_sec") is not None]
    span = (max(ts) - min(ts)) if len(ts) >= 2 else None
    latency = _latency_numbers(
        fills, [r for r in raw if r.get("OrderId") == order_id], None,
    )
    return {
        "fill_span_sec": span,
        "speed_shares_per_min": (split["total_shares"] / (span / 60.0)) if span else None,
        "passive_shares": split["passive_share_strict"] * split["total_shares"],
        "unknown_shares": split["unknown_share"] * split["total_shares"],
        "total_shares": split["total_shares"],
        "single_fill": len(fills) < 2,
        "scheduled": latency.get("scheduled"),
        "latency_anomaly": latency.get("latency_anomaly"),
        "route_to_first_fill_sec": latency.get("route_to_first_fill_sec"),
    }


def _apply_fill_context(
    model: tmod.TraderOrderRow, ctx: Optional[dict[str, Any]],
) -> None:
    """把逐笔上下文写回列表行（无逐笔 → 保持 None，不写 0）。"""
    if not ctx:
        return
    ctx["scheduled"] = bool(model.algo == "close" or ctx.get("all_auction"))
    model.fill_span_sec = ctx["fill_span_sec"]
    model.speed_shares_per_min = ctx["speed_shares_per_min"]
    total = ctx["total_shares"]
    model.passive_ratio = (ctx["passive_shares"] / total) if total else None
    unknown_share = (ctx["unknown_shares"] / total) if total else 0.0
    if unknown_share > tm.LIQUIDITY_UNKNOWN_BADGE:
        model.quality_flags.append("liquidity_unknown")
        if unknown_share > tm.LIQUIDITY_UNKNOWN_WARN and model.quality_level in ("clean", "info"):
            model.quality_level = "warn"


def _passive_kpi(ctx: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """被动占比 KPI（§4.13）：范围 = 当前页；未知占比随值披露。"""
    total = sum(c["total_shares"] for c in ctx.values())
    if not total:
        return {"value": None, "n": 0, "unknown_share": None,
                "scope": "current_page", "note": "当前页无逐笔"}
    return {
        "value": sum(c["passive_shares"] for c in ctx.values()) / total,
        "n": total,
        "unknown_share": sum(c["unknown_shares"] for c in ctx.values()) / total,
        "scope": "current_page",
    }


def _delay_kpi(ctx: dict[str, dict[str, Any]], page_orders: int) -> dict[str, Any]:
    """释放延迟 p90（§4.13）：route→首笔，仅连续算法（收盘/竞价单剔除）。"""
    values = [
        c["route_to_first_fill_sec"] for c in ctx.values()
        if not c["scheduled"] and c["route_to_first_fill_sec"] is not None
    ]
    return {
        "value": tm.percentile(values, 90.0),
        "n": len(values), "denominator": page_orders,
        "scope": "continuous_only",
    }


def _fill_quality_probe(
    ctx: dict[str, dict[str, Any]], filters: tmod.TraderFilters,
) -> dict[str, Any]:
    """fill_quality 探针（§4.12）：范围 >31 天或无逐笔 → 显式未检查。"""
    window_days = (
        datetime.strptime(filters.end_date, "%Y%m%d")
        - datetime.strptime(filters.start_date, "%Y%m%d")
    ).days + 1
    if window_days > 31:
        return {"checked": False, "triggered": None,
                "note": "范围 >31 天，未检查（不伪装通过）"}
    if not ctx:
        return {"checked": False, "triggered": None,
                "note": "当前页无逐笔，未检查（不伪装通过）"}
    triggered = sum(
        1 for c in ctx.values()
        if c["latency_anomaly"] or c["single_fill"]
        or (c["unknown_shares"] / c["total_shares"] if c["total_shares"] else 0)
        > tm.LIQUIDITY_UNKNOWN_WARN
    )
    return {"checked": True, "triggered": triggered, "note": None}

# ── 210 §4.7：同类 peer 分位（两级口径 + 进程内缓存）────────────────────────

#: peer 结果缓存 TTL（§3.7：进程内 LRU，TTL 10 分钟，key 含数据最新日期）
PEER_CACHE_TTL_SEC = 600.0
#: 库内最新日期缓存 TTL（避免每次请求都对全表求 MAX）
LATEST_DATE_TTL_SEC = 60.0
#: 散点最多返回的 peer 点数（超出按到达成本抽样截断并披露）
PEER_SCATTER_LIMIT = 200

_PEER_CACHE: dict[tuple[str, str, Optional[str]], tuple[float, dict[str, Any]]] = {}
_LATEST_DATE_CACHE: dict[str, tuple[float, Optional[str]]] = {}


def clear_peer_cache() -> None:
    """清空 peer 缓存（测试与运维手动失效用；进程内缓存无跨进程共享）。"""
    _PEER_CACHE.clear()
    _LATEST_DATE_CACHE.clear()


def _latest_tca_date(conn) -> Optional[str]:
    """库内最新 TCA 日期（短 TTL 缓存；用作 peer 缓存 key，跑批后自然失效）。"""
    now = time.time()
    cached = _LATEST_DATE_CACHE.get("latest")
    if cached and now - cached[0] < LATEST_DATE_TTL_SEC:
        return cached[1]
    value = tq.query_latest_order_date(conn)
    _LATEST_DATE_CACHE["latest"] = (now, value)
    return value


def _window_start(order_date: str, days: int) -> str:
    """窗口起点（含）：订单日回溯 N 个自然日（YYYYMMDD）。"""
    start = datetime.strptime(order_date, "%Y%m%d") - timedelta(days=days)
    return start.strftime("%Y%m%d")


def _peer_where(
    *, ticker: Optional[str] = None, exchange: Optional[str] = None,
    side: Optional[str], algo: Optional[str],
    start_date: str, end_date: str,
) -> tuple[str, list[Any]]:
    """peer 分组条件（ticker 精确口径 / exchange 宽口径二选一）。"""
    conditions = ["order_as_of_date BETWEEN ? AND ?"]
    params: list[Any] = [start_date, end_date]
    if ticker:
        conditions.append("equ_ticker = ?")
        params.append(ticker)
    if exchange:
        conditions.append("Exchange = ?")
        params.append(exchange)
    for column, value in (("Side", side), ("algo", algo)):
        if value:
            conditions.append(f"{column} = ?")
            params.append(value)
    return "WHERE " + " AND ".join(conditions), params


def _peer_rows(conn, where: str, params: list[Any], *, exclude: tuple[str, str]) -> list[dict[str, Any]]:
    """同类订单样本（去掉订单自身：自己不该是自己的基准）。"""
    rows = tq.query_peer_orders(conn, where, params)
    return [
        row for row in rows
        if (str(row.get("OrderId")), str(row.get("order_as_of_date"))) != exclude
    ]


def _peer_group_with(
    conn, current: dict[str, Any], oad: str,
) -> tuple[str, int, list[dict[str, Any]], str]:
    """两级口径的实际判定（独立函数：便于单测注入连接）。"""
    exclude = (str(current.get("OrderId")), oad)
    ticker = current.get("equ_ticker")
    side, algo = current.get("Side"), current.get("algo")
    exact_where, exact_params = _peer_where(
        ticker=ticker, side=side, algo=algo,
        start_date=_window_start(oad, tq.PEER_EXACT_WINDOW_DAYS), end_date=oad,
    )
    peers = _peer_rows(conn, exact_where, exact_params, exclude=exclude)
    if len(peers) >= tq.PEER_EXACT_MIN_SAMPLE:
        return "exact", tq.PEER_EXACT_WINDOW_DAYS, peers, "同类精确口径（同标的 + 方向 + 算法）"
    wide_where, wide_params = _peer_where(
        exchange=current.get("exchange"), side=side, algo=algo,
        start_date=_window_start(oad, tq.PEER_WIDE_WINDOW_DAYS), end_date=oad,
    )
    wide = _peer_rows(conn, wide_where, wide_params, exclude=exclude)
    if len(wide) >= tq.PEER_WIDE_MIN_SAMPLE:
        return (
            "wide", tq.PEER_WIDE_WINDOW_DAYS, wide,
            "宽口径（同市场 + 方向 + 算法；精确口径样本不足）",
        )
    return (
        "insufficient", tq.PEER_EXACT_WINDOW_DAYS, peers,
        "样本不足：精确与宽口径都未达最小样本，仅展示原值与 n",
    )


def _peer_payload(
    current: dict[str, Any], oad: str, kind: str, window_days: int,
    peers: list[dict[str, Any]], latency_p90: Optional[float], latency_n: int,
    group_note: str,
) -> dict[str, Any]:
    """组装 peer payload（§3.4.3 契约 + 两级口径与降级披露）。"""
    insufficient = kind == "insufficient"
    metrics = tm.compute_peer_metrics(current, peers)
    if insufficient:
        for item in metrics:
            item["percentile"] = None
            item["median"] = None
    degraded = [
        f"{dim.key}: {dim.note}" for dim in tm.PEER_DIMENSIONS if dim.loader is None
    ]
    if insufficient:
        degraded.append("分位：样本不足（n < 最小样本），只给原值与 n")
    if latency_p90 is None:
        degraded.append("latency_p90: 无可用逐笔时刻（或宽口径不含同标的），未计算")
    points = [
        {
            "order_id": str(row.get("OrderId")),
            "arrival_cost_bps": row.get("arrival_cost_bps"),
            "opportunity_cost_bps": tm.order_opp_bps(row),
            "completion": row.get("completion"),
            "is_self": False,
        }
        for row in peers[:PEER_SCATTER_LIMIT]
    ]
    points.append({
        "order_id": str(current.get("OrderId")),
        "arrival_cost_bps": current.get("arrival_cost_bps"),
        "opportunity_cost_bps": tm.order_opp_bps(current),
        "completion": current.get("completion"),
        "is_self": True,
    })
    return {
        "group": {
            "definition": "ticker+side+algo" if kind == "exact" else "exchange+side+algo",
            "kind": kind,
            "window_days": window_days,
            "ticker": current.get("equ_ticker"),
            "exchange": current.get("exchange"),
            "side": current.get("Side"),
            "algo": current.get("algo"),
            "order_as_of_date": oad,
            "note": group_note,
            "excludes_self": True,
        },
        "n": len(peers),
        "metrics": metrics,
        "hints": [],
        "latency": {"p90_sec": latency_p90, "n": latency_n},
        "points": points,
        "points_truncated": max(0, len(peers) - PEER_SCATTER_LIMIT),
        "sample_insufficient": insufficient,
        "deviation_count": tm.fingerprint_deviation(metrics),
        "degraded": degraded,
        "generated_at": datetime.now().isoformat(),
    }


def build_order_peer(
    order_id: str,
    *,
    order_as_of_date: Optional[str] = None,
    mgr: Optional[ConnectionManager] = None,
) -> dict[str, Any]:
    """订单的同类 peer 分位（§3.4.3 / §4.7）：两级口径 + 10 分钟缓存。"""
    manager = _manager(mgr)
    conn = manager.get_connection("fill_bdib", AccessTier.READ)
    try:
        head = _head_row(conn, order_id, order_as_of_date)
        current, oad = head
        latest = _latest_tca_date(conn)
        cache_key = (order_id, oad, latest)
        cached = _PEER_CACHE.get(cache_key)
        if cached and time.time() - cached[0] < PEER_CACHE_TTL_SEC:
            return cached[1]
        kind, window_days, peers, note = _peer_group_with(conn, current, oad)
    finally:
        conn.close()

    latency_p90, latency_n = _peer_latency(manager, peers, kind)
    payload = _peer_payload(current, oad, kind, window_days, peers, latency_p90, latency_n, note)
    payload["hints"] = tm.evaluate_hints(
        _hint_inputs(current, manager, order_id), payload,
    )
    payload["degraded"].extend(
        f"{rule_id}: {reason}" for rule_id, reason in tm.HINT_SKIPPED_RULES.items()
    )
    _PEER_CACHE[cache_key] = (time.time(), payload)
    return payload


def _hint_inputs(
    current: dict[str, Any], manager: ConnectionManager, order_id: str,
) -> dict[str, Any]:
    """提示规则入参：订单聚合行 + 自身延迟 + 质量级别（§4.8 抑制条件用）。"""
    level, _ = tm.quality_flags(current)
    return {
        "completion": current.get("completion"),
        "fill_count": current.get("fill_count"),
        "algo": current.get("algo"),
        "opp_bps": tm.order_opp_bps(current),
        "arrival_cost_bps": current.get("arrival_cost_bps"),
        "first_continuous_fill_sec": _self_latency(manager, order_id),
        "quality_level": level,
    }


def _self_latency(manager: ConnectionManager, order_id: str) -> Optional[float]:
    """本单的「路由下达 → 首笔连续成交」秒数（H4 与 peer p90 比大小用）。"""
    conn = None
    try:
        conn = manager.get_connection("processed_fills", AccessTier.READ)
        rows = tq.query_peer_latency(conn, [order_id])
    finally:
        if conn is not None:
            conn.close()
    return tm.latency_seconds(rows[0]) if rows else None


def _head_row(conn, order_id: str, order_as_of_date: Optional[str]):
    """订单聚合头（与详情同一口径）；订单不存在 → OrderNotFound。"""
    routes = tq.query_order_routes(conn, order_id)
    if not routes:
        raise OrderNotFound(f"订单不存在: {order_id}")
    oad = _resolve_order_date(routes, order_as_of_date)
    rows = tq.query_order_rows(conn, tmod.TraderFilters(
        start_date=oad, end_date=oad, order_id=order_id, limit=1,
    ))
    if not rows:
        raise OrderNotFound(f"订单不存在: {order_id}")
    return rows[0], oad


def _peer_latency(
    manager: ConnectionManager, peers: list[dict[str, Any]], kind: str,
) -> tuple[Optional[float], int]:
    """peer 延迟 p90（§4.9 H4 证据）：按**已选出的 peer 订单 id** 反查逐笔。

    延迟是流程指标，与标的不强相关，因此精确与宽口径都可比较；样本为 0 或
    逐笔缺失时返回 None + 0，由调用方写进 ``degraded``。
    """
    ids = [str(row.get("OrderId")) for row in peers if row.get("OrderId")]
    if not ids:
        return None, 0
    conn = None
    try:
        conn = manager.get_connection("processed_fills", AccessTier.READ)
        rows = tq.query_peer_latency(conn, ids)
    finally:
        if conn is not None:
            conn.close()
    return tm.peer_latency_p90(rows), len(rows)

