"""执行环境上下文派生 —— 026 阶段二（唯一实现源）。

## 为什么需要独立模块

`TcaRouteSummary` 严格匹配 55 字段 schema（`platform_data/contracts/tca_contracts.py:59`），
**不携带**真实环境字段；而环境分层所需的三项原始数据分散在两张只读表：

- ``fill_bdib.mkt_timestamp`` → 路由的交易时段（取该路由内**最早**的成交时刻）；
- ``raw_bdib`` 的 ``bdib_daily_summary`` → ``adv_20d`` 与 ``daily_volatility``
  （已内置，**无需计算**）。

本模块收敛这两类派生的**取数与应用层 join**；分桶职责仍归 ``tca_utils.bucket_*``，
不在本模块重复（口径单点约定见 ``docs/report-tca-known-limitations.md:68-69``）。

## 三级降级链（plan §4.3）

| 级别 | 触发 | 行为 |
|---|---|---|
| L1 真实 | 权威来源可得 | 用真实值 |
| L2 自给 | 权威来源缺该 ticker / 该日 | 用同义派生值并标注来源 |
| L3 代理 | 派生亦不可得 | 该维度留 ``None``，由调用方回退既有代理实现并显式标注 |

本模块只负责产出 ``RouteEnvContext``（字段为 ``None`` 即「该维度不可得」），
**降级到代理的决策留在分桶函数**（``cohort_key_and_label``）—— 那才是「代理口径」
的实现处，两处职责不重叠。

## 实测依据（plan §4.1.2 Checkpoint 2-A，2026-09-21）

- ``fill_bdib.mkt_timestamp`` 恒为 8 字符 ``HH:MM:SS`` 纯时间（纯时间戳下 ``MIN()``
  即当日最早时刻，语义正确）；``raw_bdib`` 同格式，两表无值域差异；
- start_time 可得率 100%（173,685 / 173,685）；
- ``bdib_daily_summary`` 覆盖率：``adv_20d`` 99.39% / ``daily_volatility`` 99.94%
  （``intraday_volatility`` 仅 38.7%，故不作主口径）。

⚠️ 测试夹具 ``CostView/tests/test_tca_query_service.py`` 用的是 ``'20260418 10:10:00'``
全时间戳（简化形态），与真实数据不一致 —— 本模块对两种形态都做防御。
"""

from __future__ import annotations

import math

import logging
from dataclasses import dataclass
from typing import Any, Optional, Sequence

from data_access.config import Config
from data_access.storage.connection import AccessTier, ConnectionManager

logger = logging.getLogger(__name__)

#: 环境维度名（与 ``SCORECARD_COHORTS`` 中的三个环境 cohort 对应）
ENV_DIMENSIONS: tuple[str, ...] = ("time_of_day", "liquidity_adv20", "volatility")


@dataclass(frozen=True)
class RouteEnvContext:
    """单条路由的执行环境上下文。

    字段为 ``None`` 表示该维度在本次取数中不可得（调用方据此回退到代理口径）。
    """

    #: 路由内最早成交时刻；兼容 ``HH:MM:SS`` 与 ``YYYYMMDD HH:MM:SS`` 两种形态
    start_time: Optional[str] = None
    #: 订单规模 / 20 日均量（fill ÷ adv_20d，小数非百分比）；adv_20d 缺失或为 0 时为 None
    adv20_ratio: Optional[float] = None
    #: 交易日波动率，**已统一为年化百分比**（028；小数写法在数据入口归一化）
    daily_volatility: Optional[float] = None
    #: 该值是否命中「小数写法」归一化（028）—— 命中必须可见，不得静默修数
    volatility_normalized: bool = False


def env_route_key(
    order_id: Any, route_id: Any, order_as_of_date: Any,
) -> tuple[str, str, str]:
    """环境上下文的路由键（与 ``tca_route_summary`` 的标识列语义一致）。"""
    return (str(order_id or ""), str(route_id or ""), str(order_as_of_date or ""))


def normalize_start_time(raw: Any) -> Optional[str]:
    """把 ``mkt_timestamp`` 归一化为 ``HH:MM:SS``。

    真实数据为 8 字符纯时间（实测），但测试夹具用全时间戳 —— 两种形态都兼容：
    长度 > 8 时取末 8 位（``'20260418 10:10:00'`` → ``'10:10:00'``）。
    无法解析为空串 / None。
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    return text[-8:] if len(text) > 8 else text


def load_start_times(
    mgr: ConnectionManager, start_date: str, end_date: str,
) -> dict[tuple[str, str, str], str]:
    """从 ``fill_bdib`` 派生每条路由的交易时段起点（该路由内最早成交时刻）。

    只读；``fill_bdib`` 缺失时返回空映射（该维度整体降级为不可得，不抛错）。
    """
    conn = None
    try:
        conn = mgr.get_connection("fill_bdib", AccessTier.READ)
        rows = conn.execute(
            "SELECT OrderId, RouteId, order_as_of_date, MIN(mkt_timestamp) "
            "FROM fill_bdib "
            "WHERE order_as_of_date BETWEEN ? AND ? "
            "AND mkt_timestamp IS NOT NULL AND mkt_timestamp <> '' "
            "GROUP BY OrderId, RouteId, order_as_of_date",
            [start_date, end_date],
        ).fetchall()
    except FileNotFoundError:
        logger.warning("fill_bdib 缺失 — 交易时段环境变量不可得（降级）")
        return {}
    finally:
        if conn is not None:
            conn.close()

    result: dict[tuple[str, str, str], str] = {}
    for row in rows:
        normalized = normalize_start_time(row[3])
        if normalized:
            result[env_route_key(row[0], row[1], row[2])] = normalized
    return result


def load_daily_env(
    mgr: ConnectionManager, start_date: str, end_date: str,
) -> dict[tuple[str, str], tuple[Optional[float], Optional[float]]]:
    """从 ``bdib_daily_summary`` 取 ``(ticker, 交易日)`` → ``(adv_20d, daily_volatility)``。

    ``raw_bdib`` 缺失时返回空映射（整体降级，不抛错）。
    """
    conn = None
    try:
        conn = mgr.get_connection("raw_bdib", AccessTier.READ)
        rows = conn.execute(
            f"SELECT equ_ticker, trade_date, adv_20d, daily_volatility "
            f"FROM {Config.BDIB_DAILY_SUMMARY_TABLE} "
            f"WHERE trade_date BETWEEN ? AND ?",
            [start_date, end_date],
        ).fetchall()
    except FileNotFoundError:
        logger.warning("raw_bdib 缺失 — ADV20 / 日波动率不可得（降级）")
        return {}
    finally:
        if conn is not None:
            conn.close()

    return {
        (str(row[0] or ""), str(row[1] or "")): (row[2], row[3]) for row in rows
    }


def _ratio_or_none(fill: Any, adv20: Any) -> Optional[float]:
    """订单规模 / ADV20；adv20 缺失或为 0 时不可计算（返回 None，不做除零兜底）。"""
    if fill is None or adv20 is None or not adv20:
        return None
    return float(fill) / float(adv20)


#: 年化波动率的「小数写法」判定界值（028）。
#:
#: `bdib_daily_summary.daily_volatility` 在 2026-03~04 区间被上游写成了**年化小数**
#: （`0.8175` 表示 `81.75%`），其余时段是**年化百分比**（`81.75`）。
#: 分布上两者间存在天然空档：正常年化百分比 ≥ 5，正常年化小数 ≤ 2 ——
#: 股票年化波动率不可能低于 3%，故以 3.0 为界安全（实测证据见
#: `docs/archive/2026-09-21/028-volatility-scale-fix/research.md` §3）。
VOLATILITY_SCALE_CUT: float = 3.0

#: 归一化后的波动率口径（唯一真相源，供 report_spec 护栏断言）
VOLATILITY_UNIT = "annualized-percent"


def normalize_volatility_to_percent(value: Optional[float]) -> Optional[float]:
    """把 `daily_volatility` 统一到**年化百分比**单位（028）。

    仅处理上游在特定区间的**小数写法**（`< VOLATILITY_SCALE_CUT` → ×100）；
    其余原值返回。命中与否由 `build_route_env_context` 统计并随 payload 披露 ——
    归一化**必须可见**，不得静默修数（与「降级必须可见」同一约定）。
    """
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if math.isfinite(numeric) and 0 < numeric < VOLATILITY_SCALE_CUT:
        return numeric * 100.0
    return numeric if math.isfinite(numeric) else None


def build_route_env_context(
    mgr: ConnectionManager,
    routes: Sequence[Any],
    start_date: str,
    end_date: str,
) -> dict[tuple[str, str, str], RouteEnvContext]:
    """为给定路由批量构建环境上下文（应用层 join 两张来源表）。

    跨库不采用 SQL ``ATTACH``（引入第二数据文件依赖且破坏连接单点），而是经
    ``ConnectionManager`` 分别只读取数后在应用层按 ``(ticker, 交易日)`` 关联。
    """
    start_times = load_start_times(mgr, start_date, end_date)
    daily = load_daily_env(mgr, start_date, end_date)

    result: dict[tuple[str, str, str], RouteEnvContext] = {}
    for route in routes:
        key = env_route_key(
            getattr(route, "OrderId", None),
            getattr(route, "RouteId", None),
            getattr(route, "order_as_of_date", None),
        )
        ticker_key = (
            str(getattr(route, "equ_ticker", None) or ""),
            str(getattr(route, "order_as_of_date", None) or ""),
        )
        adv20, volatility = daily.get(ticker_key, (None, None))
        normalized = normalize_volatility_to_percent(volatility)
        result[key] = RouteEnvContext(
            start_time=start_times.get(key),
            adv20_ratio=_ratio_or_none(getattr(route, "fill", None), adv20),
            # 028：统一到年化百分比（上游 202603/202604 的小数写法在此归一化）
            daily_volatility=normalized,
            # 归一化命中必须可见：命中数经 env_coverage 随 payload 披露
            volatility_normalized=(
                volatility is not None
                and normalized is not None
                and normalized != volatility
            ),
        )
    return result


def env_coverage(
    routes: Sequence[Any],
    env_by_route: dict[tuple[str, str, str], RouteEnvContext],
) -> dict[str, Any]:
    """环境变量的可得率披露（每维度可用路由数 / 总路由数）。

    「不可得」必须是**可见事实**而非静默降级：覆盖率随 scorecard payload 披露，
    低于阈值时由 report_spec 声明并提示结论仅供参考。
    """
    total = len(routes)
    usable = {dim: 0 for dim in ENV_DIMENSIONS}
    scale_fixed = 0
    for route in routes:
        key = env_route_key(
            getattr(route, "OrderId", None),
            getattr(route, "RouteId", None),
            getattr(route, "order_as_of_date", None),
        )
        env = env_by_route.get(key)
        if env is None:
            continue
        if env.start_time:
            usable["time_of_day"] += 1
        if env.adv20_ratio is not None:
            usable["liquidity_adv20"] += 1
        if env.daily_volatility is not None:
            usable["volatility"] += 1
        if getattr(env, "volatility_normalized", False):
            # 028：命中「年化小数」写法并已归一化 —— 必须可见，不得静默修数
            scale_fixed += 1

    return {
        "total_routes": total,
        "usable": usable,
        "pct": {
            dim: (round(count / total * 100.0, 2) if total else None)
            for dim, count in usable.items()
        },
        # 028：量纲归一化披露（上游 202603/202604 区间写的是年化小数）
        "volatility_scale_fixed": scale_fixed,
    }
