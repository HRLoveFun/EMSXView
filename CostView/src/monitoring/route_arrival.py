"""路由到达价与延迟拆分 —— 057 DL-12（本侧自给 + 上游对账切换）。

## 口径定义（本 docstring 即金标准，供 EMSXDataPipeline 物化对齐）

- ``p_route_arrival``：``route_as_of_time``（路由下达时刻，交易所本地时间）
  之前最近一根 ``raw_bdib`` 10 秒 bar 的 **close**；当日该时刻之前无 bar
  （盘前下达）时取当日首 bar 的 **open``（003 ``p_decision`` 盘前处理同口径）；
  bar 的 ``close IS NULL`` 跳过（指南 §10.3）。价格取 close 而非 vwap：与
  003 ``p_arrival``/``p_decision`` 家族一致，且 ``raw_bdib`` 无 vwap 衍生列。
- ``algo_latency_sec``：该路由首笔成交时刻（``processed_fills`` 同路由
  ``MIN(exchange_exec_time)``，秒级）− ``route_as_of_time``，同日差秒；首笔
  早于下达（数据异常）或不可得时为 None。首笔取 ``processed_fills`` 秒级而
  非 ``fill_bdib.mkt_timestamp``（10 秒 floor 且缺 S5 未处理日期）。
- 上游物化四列的 sum 守恒：``trader_delay_cost = RouteShares ×
  (p_route_arrival − p_decision) × side_sign``、``algo_delay_cost =
  RouteShares × (p_arrival − p_route_arrival) × side_sign``，两者之和恰为
  003 既有 ``delay_cost = RouteShares × (P0 − Pd) × side_sign``（可作上游
  对账的额外校验）。

## 三级降级链（与 ``env_context`` 同模式）

| 级别 | 触发 | 行为 |
|---|---|---|
| L1 上游 | ``tca_route_summary`` 已有 ``p_route_arrival`` / ``algo_latency_sec`` 列 | 取上游物化值（``resolve_arrival_fields`` 标注 ``upstream``） |
| L2 自给 | 上游列不存在或该行缺失 | 本模块按上述口径派生（标注 ``self``） |
| L3 不可得 | 两者皆缺 | None，由 ``arrival_coverage`` 披露可得率 |

切换门禁：上游列就绪后由 ``scripts/ops/reconcile_route_arrival.py`` 逐路由
对账（差异 <1bp 占比 ≥99%，tasks.md DL-12 检验方法），通过方切 L1。

## 数据来源与已知边界

- ``route_as_of_time`` / ``exchange_exec_time`` 为 S2 同一批时区转换产物
  （交易所本地 naive），与 ``raw_bdib.mkt_timestamp``（本地 HH:MM:SS）同本地
  时钟可比；跨日/盘前下达按「当日首 bar open」处理，对账时该部分需人工核对；
- ``raw_bdib`` 查询按 ``(equ_ticker, order_as_of_date)`` 带前导列（指南
  §10.3），不扫全表；库/表缺失一律降级为空映射，不抛错。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional, Sequence

from data_access.config import Config
from data_access.storage.connection import AccessTier, ConnectionManager

from CostView.src.monitoring.env_context import env_route_key, normalize_start_time

logger = logging.getLogger(__name__)

#: 路由键（与 ``env_context`` / ``tca_route_summary`` 标识列语义一致）
RouteKey = tuple[str, str, str]

#: 上游物化列名（``tca_route_summary``，EMSXDataPipeline DL-12 请求）
UPSTREAM_ARRIVAL_COLUMNS: tuple[str, ...] = ("p_route_arrival", "algo_latency_sec")

#: 对账容差：相对差异小于该值（bps）记为一致（tasks.md DL-12 检验方法）
RECONCILE_TOLERANCE_BPS: float = 1.0

#: 对账通过阈值：差异 <1bp 的占比不低于该百分比方切 L1
RECONCILE_MIN_PCT: float = 99.0


@dataclass(frozen=True)
class RouteArrivalContext:
    """单条路由的到达价与延迟上下文（L2 自给值）。

    字段为 None 表示该维度本次取数不可得（调用方据此回退或披露）。
    """

    #: 路由下达时刻（归一化 HH:MM:SS，交易所本地）
    route_as_of_time: Optional[str] = None
    #: 路由内首笔成交时刻（归一化 HH:MM:SS，交易所本地）
    first_fill_time: Optional[str] = None
    #: 路由到达价（自给口径，见模块 docstring）
    p_route_arrival: Optional[float] = None
    #: 所用 bar 时刻（归一化 HH:MM:SS；盘前下达时为首 bar 时刻），供审计
    arrival_bar_time: Optional[str] = None
    #: 算法延迟秒数（首笔 − 下达）；首笔早于下达或不可得时为 None
    algo_latency_sec: Optional[float] = None


# ── 纯函数（无 IO，单测直接覆盖） ────────────────────────────────────────────


def _hms_to_seconds(hms: str) -> Optional[int]:
    """``HH:MM:SS`` → 当日秒数；格式或取值非法返回 None。"""
    parts = hms.split(":")
    if len(parts) != 3:
        return None
    try:
        hour, minute, second = (int(part) for part in parts)
    except ValueError:
        return None
    if not (0 <= hour < 24 and 0 <= minute < 60 and 0 <= second < 60):
        return None
    return hour * 3600 + minute * 60 + second


def _resolve_arrival(
    bars: Sequence[tuple[Optional[str], Optional[float], Optional[float]]],
    as_of_hms: Optional[str],
) -> tuple[Optional[float], Optional[str]]:
    """(price, bar_time)：as_of 之前最近 bar 的 close；无则当日首 bar 的 open。

    bars 须为当日升序 ``(mkt_timestamp, close, open)``（``load_arrival_bars``
    已 ``ORDER BY mkt_timestamp``）；close 为 NULL 的 bar 跳过。
    """
    if not as_of_hms:
        return (None, None)
    prior: Optional[tuple[str, float]] = None
    first_open: Optional[tuple[str, float]] = None
    for bar_time, close, open_price in bars:
        if bar_time is None:
            continue
        if first_open is None and open_price is not None:
            first_open = (bar_time, float(open_price))
        if close is not None and bar_time <= as_of_hms:
            prior = (bar_time, float(close))
    if prior is not None:
        return (prior[1], prior[0])
    if first_open is not None:
        return (first_open[1], first_open[0])
    return (None, None)


def arrival_price_from_bars(
    bars: Sequence[tuple[Optional[str], Optional[float], Optional[float]]],
    as_of_hms: Optional[str],
) -> Optional[float]:
    """路由到达价（公开纯函数）：as_of 之前最近 bar close；盘前取首 bar open。"""
    return _resolve_arrival(bars, as_of_hms)[0]


def latency_seconds(
    as_of_hms: Optional[str], first_fill_hms: Optional[str],
) -> Optional[float]:
    """算法延迟秒数（同日差）；首笔早于下达（数据异常）或不可得时返回 None。"""
    as_of = normalize_start_time(as_of_hms)
    first_fill = normalize_start_time(first_fill_hms)
    if not as_of or not first_fill:
        return None
    start = _hms_to_seconds(as_of)
    end = _hms_to_seconds(first_fill)
    if start is None or end is None or end < start:
        return None
    return float(end - start)


def resolve_arrival_fields(
    upstream: Optional[float], selfsup: Optional[float],
) -> tuple[Optional[float], str]:
    """三级降级链取值：L1 上游优先，L2 自给兜底，L3 不可得。

    返回 (值, 来源标签)；来源为 ``upstream`` / ``self`` / ``missing``。
    """
    if upstream is not None:
        return (float(upstream), "upstream")
    if selfsup is not None:
        return (float(selfsup), "self")
    return (None, "missing")


def reconcile_arrival(
    upstream_map: Mapping[RouteKey, Optional[float]],
    selfsup_map: Mapping[RouteKey, Optional[float]],
) -> dict[str, Any]:
    """上游值与本侧自给值逐路由对账（tasks.md DL-12 检验方法）。

    差异 = ``|upstream − selfsup| / selfsup × 1e4``（bps）；selfsup 为 None
    或 0 的路由跳过（不除零）；恰好等于容差不计为一致（严格小于）。
    """
    compared = 0
    within = 0
    max_diff_bps = 0.0
    over_examples: list[dict[str, Any]] = []
    for key, upstream in upstream_map.items():
        selfsup = selfsup_map.get(key)
        if upstream is None or selfsup is None or not selfsup:
            continue
        diff_bps = abs(float(upstream) - float(selfsup)) / float(selfsup) * 1e4
        compared += 1
        max_diff_bps = max(max_diff_bps, diff_bps)
        if diff_bps < RECONCILE_TOLERANCE_BPS:
            within += 1
        else:
            over_examples.append({
                "route_key": list(key),
                "upstream": float(upstream),
                "selfsup": float(selfsup),
                "diff_bps": round(diff_bps, 4),
            })
    over_examples.sort(key=lambda item: item["diff_bps"], reverse=True)
    return {
        "compared": compared,
        "within_1bp": within,
        "pct_within_1bp": (round(within / compared * 100.0, 2) if compared else None),
        "max_diff_bps": (round(max_diff_bps, 4) if compared else None),
        "over_tolerance_examples": over_examples[:10],
    }


# ── IO 函数（只读；库/表缺失降级为空映射，不抛错） ──────────────────────────


def load_route_as_of_and_first_fill(
    mgr: ConnectionManager, start_date: str, end_date: str,
) -> dict[RouteKey, tuple[Optional[str], Optional[str]]]:
    """从 ``processed_fills`` 按路由分组取 (下达时刻, 首笔成交时刻)。

    两列同为 S2 时区转换产物（本地 naive）；``WHERE order_as_of_date`` 走
    PK 前导列。库缺失时返回空映射（该维度整体降级）。
    """
    conn = None
    try:
        conn = mgr.get_connection("processed_fills", AccessTier.READ)
        rows = conn.execute(
            f"SELECT OrderId, RouteId, order_as_of_date, "
            f"MIN(route_as_of_time), MIN(exchange_exec_time) "
            f"FROM {Config.PROCESSED_FILLS_TABLE} "
            f"WHERE order_as_of_date BETWEEN ? AND ? "
            f"GROUP BY OrderId, RouteId, order_as_of_date",
            [start_date, end_date],
        ).fetchall()
    except FileNotFoundError:
        logger.warning("processed_fills 缺失 — 路由下达时刻/首笔成交不可得（降级）")
        return {}
    finally:
        if conn is not None:
            conn.close()

    return {
        env_route_key(row[0], row[1], row[2]): (
            normalize_start_time(row[3]), normalize_start_time(row[4]),
        )
        for row in rows
    }


def load_arrival_bars(
    mgr: ConnectionManager, ticker_dates: Iterable[tuple[Any, Any]],
) -> dict[tuple[str, str], list[tuple[Optional[str], Optional[float], Optional[float]]]]:
    """按 ``(equ_ticker, order_as_of_date)`` 分组读 ``raw_bdib`` 当日 bar。

    每组一次带前导列的点查（指南 §10.3），组内按 ``mkt_timestamp`` 升序；
    ``raw_bdib`` 缺失时返回空映射（p_route_arrival 整体降级）。
    """
    groups = sorted({
        (str(ticker), str(date)) for ticker, date in ticker_dates if ticker and date
    })
    if not groups:
        return {}

    result: dict[tuple[str, str], list[tuple[Optional[str], Optional[float], Optional[float]]]] = {}
    conn = None
    try:
        conn = mgr.get_connection("raw_bdib", AccessTier.READ)
        for ticker, date in groups:
            rows = conn.execute(
                f"SELECT mkt_timestamp, close, open "
                f"FROM {Config.RAW_BDIB_TABLE} "
                f"WHERE equ_ticker = ? AND order_as_of_date = ? "
                f"ORDER BY mkt_timestamp",
                [ticker, date],
            ).fetchall()
            result[(ticker, date)] = [
                (normalize_start_time(row[0]), row[1], row[2]) for row in rows
            ]
    except FileNotFoundError:
        logger.warning("raw_bdib 缺失 — 路由到达价不可得（降级）")
        return {}
    finally:
        if conn is not None:
            conn.close()
    return result


def load_upstream_arrival(
    mgr: ConnectionManager, start_date: str, end_date: str,
) -> dict[RouteKey, dict[str, Optional[float]]]:
    """读 ``tca_route_summary`` 的上游物化列（L1）。

    列不存在即上游未就绪——返回空 dict 而非报错；库缺失同样降级。
    """
    conn = None
    try:
        conn = mgr.get_connection("fill_bdib", AccessTier.READ)
        columns = {
            row[1] for row in conn.execute(
                f"PRAGMA table_info({Config.TCA_ROUTE_SUMMARY_TABLE})"
            ).fetchall()
        }
        if not set(UPSTREAM_ARRIVAL_COLUMNS) <= columns:
            return {}
        rows = conn.execute(
            f"SELECT OrderId, RouteId, order_as_of_date, "
            f"p_route_arrival, algo_latency_sec "
            f"FROM {Config.TCA_ROUTE_SUMMARY_TABLE} "
            f"WHERE order_as_of_date BETWEEN ? AND ?",
            [start_date, end_date],
        ).fetchall()
    except FileNotFoundError:
        logger.warning("fill_bdib 缺失 — 上游到达价不可读（降级）")
        return {}
    finally:
        if conn is not None:
            conn.close()

    return {
        env_route_key(row[0], row[1], row[2]): {
            "p_route_arrival": row[3], "algo_latency_sec": row[4],
        }
        for row in rows
    }


# ── 装配与披露（应用层 join，模式同 build_route_env_context） ────────────────


def build_route_arrival_context(
    mgr: ConnectionManager,
    routes: Sequence[Any],
    start_date: str,
    end_date: str,
) -> dict[RouteKey, RouteArrivalContext]:
    """为给定路由批量构建到达价与延迟上下文（L2 自给）。

    跨库不采用 SQL ``ATTACH``（破坏连接单点），经 ``ConnectionManager``
    分别只读取数后在应用层关联；``equ_ticker`` 取自调用方路由对象。
    """
    as_of_and_first = load_route_as_of_and_first_fill(mgr, start_date, end_date)
    bars_by_group = load_arrival_bars(mgr, [
        (getattr(route, "equ_ticker", None), getattr(route, "order_as_of_date", None))
        for route in routes
    ])

    result: dict[RouteKey, RouteArrivalContext] = {}
    for route in routes:
        key = env_route_key(
            getattr(route, "OrderId", None),
            getattr(route, "RouteId", None),
            getattr(route, "order_as_of_date", None),
        )
        as_of, first_fill = as_of_and_first.get(key, (None, None))
        bars = bars_by_group.get(
            (str(getattr(route, "equ_ticker", None) or ""),
             str(getattr(route, "order_as_of_date", None) or "")),
            [],
        )
        price, bar_time = _resolve_arrival(bars, as_of)
        result[key] = RouteArrivalContext(
            route_as_of_time=as_of,
            first_fill_time=first_fill,
            p_route_arrival=price,
            arrival_bar_time=bar_time,
            algo_latency_sec=latency_seconds(as_of, first_fill),
        )
    return result


def arrival_coverage(
    routes: Sequence[Any],
    ctx_by_route: Mapping[RouteKey, RouteArrivalContext],
) -> dict[str, Any]:
    """到达价与延迟两维度的可得率披露（「不可得」必须可见，同 ``env_coverage``）。"""
    total = len(routes)
    usable = {"p_route_arrival": 0, "algo_latency_sec": 0}
    for route in routes:
        key = env_route_key(
            getattr(route, "OrderId", None),
            getattr(route, "RouteId", None),
            getattr(route, "order_as_of_date", None),
        )
        ctx = ctx_by_route.get(key)
        if ctx is None:
            continue
        if ctx.p_route_arrival is not None:
            usable["p_route_arrival"] += 1
        if ctx.algo_latency_sec is not None:
            usable["algo_latency_sec"] += 1
    return {
        "total_routes": total,
        "usable": usable,
        "pct": {
            dim: (round(count / total * 100.0, 2) if total else None)
            for dim, count in usable.items()
        },
    }
