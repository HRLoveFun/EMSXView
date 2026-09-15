"""报告共享口径层 — 作用域 / 成交额加权 / 样本覆盖 / 订单级聚合 / 金额回退的唯一实现源。

与 ``report_spec.py`` 的分工：``report_spec`` 是口径**声明**（脚注与测试断言的事实源），
本模块是口径**实现**（SQL 片段与聚合规则的唯一来源）。``report_aggregator`` /
``anomaly_query`` / ``metric_coverage`` / ``bdib_health`` 一律引用此处，禁止各自重写
同类表达式 —— 历史缺陷的根因正是「同一契约两处实现，只有一处演进」：

- 多值过滤：聚合器按 ``IN`` 匹配、异常查询按 ``=`` 匹配 → 前端多选时异常清单静默清空；
- 作用域：覆盖率按 BDIB 白名单、KPI / 异常按全量 → 同一报告内数字不可对账；
- 订单参与率：异常按维度过滤后的行求和、一致性探针按全量 → 过滤视图下探针失效；
- 金额回退：小计价单位与 fx 兜底在多处硬编码，新增币种需多点同步。

契约要点：
1. **作用域**：默认 = BDIB 白名单（``Config.BDIB_EXCHANGE``）内全量；用户显式指定
   exchange 时为用户口径，白名单外的选择记入 ``out_of_scope`` 由报告显式披露。
2. **加权**：权重恒为 ``fill × p_avg``（成交额口径），与「总成交金额」同源；
   加权均值必须同时披露样本覆盖与权重覆盖（条数覆盖 90% ≠ 权重覆盖 90%）。
3. **订单级聚合**：按 ``(OrderId, order_as_of_date, Exchange)`` 求和，且只受报告期与
   作用域约束、不受 broker / algo / symbol 维度过滤影响。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Sequence

from data_access.config import Config

# ── 1. 作用域（BDIB 白名单 / 用户指定市场）─────────────────────────────────

#: 作用域模式：白名单内全量（默认口径）
WHITELIST_MODE = "bdib_whitelist"
#: 作用域模式：用户显式指定市场
USER_MODE = "user_exchange_filter"

#: 样本（权重）覆盖率提示阈值（%）：低于该值在报告中标注「结论仅供参考」
SAMPLE_COVERAGE_MIN_PCT = 90.0


def bdib_whitelist() -> tuple[str, ...]:
    """BDIB 白名单交易所（大写、去空、去重、升序）。

    ``Config.BDIB_EXCHANGE`` 为唯一真相源，白名单外市场（CN/BZ 等）本就不拉取
    BDIB 行情，其指标必然为 NULL，计入任何分母都会造成口径失真。
    """
    return tuple(sorted({
        str(ex).strip().upper() for ex in Config.BDIB_EXCHANGE if str(ex).strip()
    }))


def split_values(raw: Optional[str]) -> tuple[str, ...]:
    """逗号分隔多值解析：None/空 → ``()``；保序去重（供 IN 匹配统一使用）。"""
    if not raw:
        return ()
    seen: dict[str, None] = {}
    for item in raw.split(","):
        value = item.strip()
        if value:
            seen.setdefault(value, None)
    return tuple(seen)


@dataclass(frozen=True)
class ReportScope:
    """报告作用域：默认 = BDIB 白名单内全量；用户指定 exchange 时 = 用户口径。"""

    mode: str
    exchanges: tuple[str, ...]
    #: 用户口径下被选中、但不在白名单内的市场（需在报告中显式提示）
    out_of_scope: tuple[str, ...] = ()

    @property
    def is_whitelist(self) -> bool:
        """是否为默认的白名单口径。"""
        return self.mode == WHITELIST_MODE

    def describe(self) -> str:
        """报告头展示用的作用域文案。"""
        if self.is_whitelist:
            return f"BDIB 白名单内 {len(self.exchanges)} 个市场"
        return "用户指定市场 " + ", ".join(self.exchanges)

    def to_payload(self) -> dict[str, Any]:
        """供 ``report["filters"]["scope"]`` 落库（渲染与前端消费）。"""
        return {
            "mode": self.mode,
            "exchanges": list(self.exchanges),
            "out_of_scope": list(self.out_of_scope),
            "label": self.describe(),
        }


def resolve_scope(exchange: Optional[str]) -> ReportScope:
    """解析报告作用域：用户给出 exchange → 用户口径；否则 → BDIB 白名单口径。

    白名单外市场被用户显式选中时记入 ``out_of_scope``：此前该情形下覆盖率与
    异常清单会静默剔除这些市场，用户无法察觉数字被口径截断。
    """
    values = split_values(exchange)
    if not values:
        return ReportScope(mode=WHITELIST_MODE, exchanges=bdib_whitelist())
    # 大写归一后再去重（'US, us' → 单值），避免 IN 子句与 describe() 出现重复市场
    normalized = tuple(dict.fromkeys(str(v).upper() for v in values))
    whitelist = set(bdib_whitelist())
    outside = tuple(v for v in normalized if v not in whitelist)
    return ReportScope(mode=USER_MODE, exchanges=normalized, out_of_scope=outside)


def scope_condition(
    scope: ReportScope, column: str = "Exchange",
) -> tuple[str, list[Any]]:
    """作用域 WHERE 片段与参数（大小写不敏感，与白名单大写归一一致）。

    空集合 → 返回 ``("", [])``（不过滤，兼容无白名单配置的场景）。
    """
    if not scope.exchanges:
        return "", []
    placeholders = ", ".join(["?"] * len(scope.exchanges))
    return f"UPPER({column}) IN ({placeholders})", list(scope.exchanges)


def dimension_condition(column: str, raw: Optional[str]) -> tuple[str, list[Any]]:
    """维度过滤片段与参数：多值 → ``IN``；单值等价 ``=``；空 → 不过滤。

    聚合器与异常查询共用本函数，避免「一处支持多选、另一处只支持单值」导致
    前端多选过滤器下异常清单静默为空。
    """
    values = split_values(raw)
    if not values:
        return "", []
    placeholders = ", ".join(["?"] * len(values))
    return f"{column} IN ({placeholders})", list(values)


# ── 2. 成交额加权与样本（权重）覆盖 ────────────────────────────────────────

#: 需披露「样本 / 权重覆盖」的加权指标（KPI 卡 + 附加 KPI + 冲击分解表 + PWP 曲线）
WEIGHTED_METRICS: tuple[str, ...] = (
    "pnl_vwap", "par_rate", "RPM",
    "arrival_cost_bps", "wagner_is_bps",
    "cost_stddev", "cost_cvar", "cost_p95",
    "temp_impact_5min_bps", "temp_impact_10min_bps", "temp_impact_30min_bps",
    "perm_impact_bps", "close_cost_bps",
    # D5：PWP 五档纳入加权体系（此前等权 AVG 与加权 KPI 不可对账）
    "pwp_5", "pwp_10", "pwp_15", "pwp_20", "pwp_25",
)

#: 加权权重表达式（与「总成交金额」同源；report_spec 的 weight_expression 即此串）
WEIGHT_EXPRESSION = "fill * p_avg"


def weight_cond(metric: str) -> str:
    """加权均值中单条路由的纳入条件（指标 / fill / p_avg 三者齐备）。"""
    return f"{metric} IS NOT NULL AND fill IS NOT NULL AND p_avg IS NOT NULL"


def weighted_avg_sql(metric: str) -> str:
    """成交额加权均值 SQL 片段（唯一实现；metric 为内部白名单值，无注入风险）。"""
    cond = weight_cond(metric)
    return (
        f"SUM(CASE WHEN {cond} THEN {metric} * {WEIGHT_EXPRESSION} END) / "
        f"NULLIF(SUM(CASE WHEN {cond} THEN {WEIGHT_EXPRESSION} END), 0)"
    )


def weight_coverage_select(metrics: Sequence[str]) -> str:
    """批量产出「样本量 + 权重覆盖」SELECT 片段（列序固定，供索引化解析）。

    列序：``n_total``、``total_weight``，随后每指标依次 ``n_used_i``、``used_weight_i``。
    分母 ``total_weight`` 为「可加权路由」（fill 与 p_avg 均非 NULL）的成交额合计，
    即加权均值自身的分母上限 —— 权重覆盖率 = ``used_weight / total_weight``。
    """
    columns = [
        "COUNT(*) AS n_total",
        f"SUM(CASE WHEN fill IS NOT NULL AND p_avg IS NOT NULL "
        f"THEN {WEIGHT_EXPRESSION} ELSE 0 END) AS total_weight",
    ]
    for index, metric in enumerate(metrics):
        cond = weight_cond(metric)
        columns.append(f"SUM(CASE WHEN {cond} THEN 1 ELSE 0 END) AS n_used_{index}")
        columns.append(
            f"SUM(CASE WHEN {cond} THEN {WEIGHT_EXPRESSION} ELSE 0 END) "
            f"AS used_weight_{index}"
        )
    return ", ".join(columns)


def weight_coverage_entry(
    n_used: int, n_total: int, used_weight: float, total_weight: float,
) -> dict[str, Any]:
    """组装单指标覆盖条目（含「结论仅供参考」判定，渲染层直接消费）。"""
    sample_pct = round(n_used / n_total * 100.0, 2) if n_total else None
    weight_pct = round(used_weight / total_weight * 100.0, 2) if total_weight else None
    measured = [pct for pct in (sample_pct, weight_pct) if pct is not None]
    return {
        "n_used": n_used,
        "n_total": n_total,
        "sample_pct": sample_pct,
        "used_weight": used_weight,
        "total_weight": total_weight,
        "weight_pct": weight_pct,
        "insufficient": bool(measured) and min(measured) < SAMPLE_COVERAGE_MIN_PCT,
    }


# ── 3. 订单级聚合（唯一实现；只受报告期与作用域约束）───────────────────────

#: 订单参与率聚合键：跨市场求和无物理意义，故按交易所分组
ORDER_PAR_GROUP_COLUMNS: str = "OrderId, order_as_of_date, Exchange"


def order_par_aggregate_sql(where: str, *, alias: Optional[str] = None) -> str:
    """订单参与率求和 SQL（``where`` 只应含报告期与作用域，禁止含维度过滤）。

    作为派生表使用时传 ``alias``（SQLite 要求派生表有别名），否则返回裸 SELECT。
    异常明细与覆盖率一致性探针共用本定义，保证「同一订单参与率」两处可对账。
    """
    columns = ORDER_PAR_GROUP_COLUMNS
    sql = (
        f"SELECT {columns}, SUM(par_rate) AS par_sum "
        f"FROM {Config.TCA_ROUTE_SUMMARY_TABLE} WHERE {where} "
        f"GROUP BY {columns}"
    )
    return f"({sql}) AS {alias}" if alias else sql


def order_par_key(order_id: Any, date: Any, exchange: Any) -> tuple[str, str, str]:
    """订单级聚合键（字段顺序与 ``ORDER_PAR_GROUP_COLUMNS`` 一致）。"""
    return (str(order_id or ""), str(date or ""), str(exchange or ""))


# ── 3.5 异常明细下限门槛的豁免（严重未完成必须可见）────────────────────────

#: 豁免笔数 / 金额下限的规则键（fill_pct = 完成率规则）
FLOOR_EXEMPT_RULE: str = "fill_pct"
#: 触发豁免的严重度档（critical = 严重未完成，含零成交）
FLOOR_EXEMPT_SEVERITY: str = "critical"


def is_floor_exempt(hits: Sequence[dict[str, Any]]) -> bool:
    """命中列表是否含「豁免下限」的严重档。

    该档的目标样本恰是低完成率路由（含完全未执行），用笔数 / 金额下限过滤会把最严重
    的情形整体剔除，故必须豁免；口径声明见 ``report_spec.anomaly_floor_exempt``，
    两者由测试断言一致（改规则名时声明层不会静默脱钩）。
    """
    return any(
        hit.get("key") == FLOOR_EXEMPT_RULE
        and hit.get("severity") == FLOOR_EXEMPT_SEVERITY
        for hit in hits
    )


# ── 4. 金额换算与价格回退 ──────────────────────────────────────────────────

#: 小计价单位货币 → 汇率折算系数（Bloomberg 以最小计价单位报价，需再乘系数）
MINOR_UNIT_FACTORS: dict[str, float] = {"GBp": 0.01, "ILs": 0.01, "ZAr": 0.01}

#: 未成交金额的价格回退链（p_avg 缺失时用可比价格，避免该路由贡献 NULL）
UNFILLED_PRICE_FALLBACKS: tuple[str, ...] = (
    "p_avg", "p_arrival", "p_decision", "p_close",
)


def minor_unit_expr(column: str = "Currency") -> str:
    """小计价单位修正表达式（单一真相源；新增币种只改 ``MINOR_UNIT_FACTORS``）。"""
    cases = " ".join(
        f"WHEN {column} = '{ccy}' THEN {factor}"
        for ccy, factor in MINOR_UNIT_FACTORS.items()
    )
    return f"CASE {cases} ELSE 1.0 END"


def usd_fx_expr(effective_rate: str, currency_column: str = "Currency") -> str:
    """USD 换算因子：有效汇率 × 小计价单位修正；USD/未知币种缺汇率按 1.0 兜底。

    非 USD 且无有效汇率 → NULL（该路由贡献为 NULL，SUM 忽略：不虚高、亦不整体置空）。
    """
    minor = minor_unit_expr(currency_column)
    return (
        f"CASE WHEN {effective_rate} IS NOT NULL THEN {effective_rate} * ({minor}) "
        f"WHEN {currency_column} IS NULL OR {currency_column} = 'USD' THEN 1.0 "
        f"ELSE NULL END"
    )


def unfilled_price_expr(available: Sequence[str]) -> Optional[str]:
    """未成交金额的价格回退表达式（按 ``UNFILLED_PRICE_FALLBACKS`` 保序取可用列）。

    可用列全缺（旧 schema）时返回 ``None``，调用方据此降级为不计算。
    """
    columns = [col for col in UNFILLED_PRICE_FALLBACKS if col in set(available)]
    if not columns:
        return None
    if len(columns) == 1:
        return columns[0]
    return "COALESCE(" + ", ".join(columns) + ")"


def unfilled_notional_expr(price_expr: str, fx_expr: str, *, usd: bool) -> str:
    """未成交金额缺口表达式：正缺口计入，零成交路由不再因 p_avg 缺失被跳过。

    - 缺口 = ``RouteShares − COALESCE(fill, 0)``（fill 为 NULL 视作零成交）；
    - 价格缺失（回退链全空）时该路由贡献 NULL（不虚高、不虚低）；
    - ``usd=False`` 或 ``fx_expr`` 为空时按本币口径计算。
    """
    gap = "COALESCE(fill, 0)"
    amount = f"(RouteShares - {gap}) * ({price_expr})"
    if usd and fx_expr:
        amount = f"{amount} * ({fx_expr})"
    return f"SUM(CASE WHEN RouteShares > {gap} THEN {amount} ELSE 0 END)"


def unfilled_unpriced_expr(price_expr: str) -> str:
    """因价格回退链全空而无法计入缺口的路由数（披露剩余低估规模）。"""
    gap = "COALESCE(fill, 0)"
    return (
        f"SUM(CASE WHEN RouteShares > {gap} AND ({price_expr}) IS NULL "
        f"THEN 1 ELSE 0 END)"
    )


def zero_fill_count_expr() -> str:
    """零成交路由数（fill 为 0/NULL 且有委托股数）。"""
    return (
        "SUM(CASE WHEN COALESCE(fill, 0) = 0 AND RouteShares > 0 THEN 1 ELSE 0 END)"
    )


def zero_fill_notional_expr(price_expr: str, fx_expr: str, *, usd: bool) -> str:
    """零成交路由的委托金额（完全未执行的机会成本规模）。

    「未成交金额缺口」只统计部分成交路由的正缺口，零成交路由若价格缺失会被
    整条跳过；本表达式单独度量「计划成交但一股未成」的规模，避免该情形隐身。
    """
    amount = f"RouteShares * ({price_expr})"
    if usd and fx_expr:
        amount = f"{amount} * ({fx_expr})"
    return (
        f"SUM(CASE WHEN COALESCE(fill, 0) = 0 AND RouteShares > 0 "
        f"THEN {amount} ELSE 0 END)"
    )
