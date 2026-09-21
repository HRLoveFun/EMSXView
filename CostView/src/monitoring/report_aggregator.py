"""TCA 可视化报告聚合服务 — tca_route_summary 的报表级聚合。

供独立 HTML 报告脚本与监控 API 的报告端点复用：
    KPI（route 数 / 总股数 / 成交额加权 pnl_vwap / 平均 par_rate / 平均 RPM）、
    pnl_vwap 分布直方图、按日加权走势、broker/algo 排行、PWP 五档均值曲线。

加权口径：成交额权重 = fill * p_avg（仅二者均非 NULL 时计入），与 KPI 的
notional = SUM(fill × p_avg) 同源 —— 保证「加权成本」可由「总成交金额」反推校验，
且未成交路由不再以「意图规模」放大权重。加权均值必须同时披露样本量与权重覆盖率
（report["weight_coverage"]）：条数覆盖 90% 不代表权重覆盖 90%，BDIB 缺口集中在
大单时 KPI 实为覆盖子集均值，需让读者可见。

作用域（缺陷 · 白名单作用域不一致）：报告全部小节共用同一作用域 —— 默认取
Config.BDIB_EXCHANGE 白名单（白名单外市场本就不拉 BDIB、指标必然 NULL），用户显式
指定 exchange 时改用用户口径，并披露所选市场中的白名单外项。作用域 / 加权 / 订单级
聚合 / 金额回退的唯一实现见 report_measure.py。
所有过滤条件参数化（? 占位符），指标名仅来自内部白名单常量。
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from data_access.config import Config
from data_access.storage.connection import AccessTier, ConnectionManager

from . import _common
from . import report_measure as rm
from .metric_coverage import MetricCoverageService, validate_metrics
from .anomaly_query import (
    ThresholdRules,
    query_anomaly_routes_page_ex,
)
from .report_dims import get_filter_options as _get_persisted_options

logger = logging.getLogger(__name__)

#: 直方图分桶数
_HISTOGRAM_BINS = 20
#: 排行输出上限（单侧）
_RANKING_LIMIT = 20
#: 排行样本门槛（D4 / DP-1 定稿口径 B）：组内「有成交额权重的路由数」下限。
#: 门槛对象是 broker 聚合组而非单条路由，不复用异常明细 fill_count（单路由）
#: 的语义 —— 组样本量以 n_used 计。
_RANKING_MIN_SAMPLE = 5
#: 排行经济相关性门槛：组成交额占报告期总成交额的下限（防「样本够但金额
#: 边缘」的噪声组；成交额与加权权重同源 fill × p_avg）
_RANKING_MIN_NOTIONAL_SHARE = 0.001
#: 排行聚合组的 SQL 安全上限（broker/algo 组数量级为几十，1000 为防御值）
_RANKING_MAX_GROUPS = 1000
#: PWP 档位（数值为百分比）
_PWP_RATE_LABELS = [("pwp_5", 5), ("pwp_10", 10), ("pwp_15", 15),
                    ("pwp_20", 20), ("pwp_25", 25)]
#: 分市场 PWP 小多图的市场数（DP-2 定稿口径：默认聚合曲线 + Top N 市场小图）
_PWP_TOP_MARKETS = 6
#: 冲击截断占比的分母口径（D15 / DP-4 定稿）：「冲击计算样本」= 任一冲击指标
#: 可计算（temp/perm 之一非 NULL）的路由，而非全量路由 —— 恢复被截断的路由
#: 冲击值非 NULL，必然同时落在分子与分母内，口径自洽。
IMPACT_TRUNCATED_SHARE_DENOMINATOR = "impact_sample"


class TcaReportAggregator:
    """tca_route_summary 报告聚合器。"""

    def __init__(self, connection_manager: Optional[ConnectionManager] = None):
        self._mgr = connection_manager or ConnectionManager()
        #: fill_bdib 汇率回填临时表是否就绪（build_report 内一次性构建，4 个 fx 查询复用）
        self._fbfx_ready = False

    def build_report(
        self,
        start_date: str,
        end_date: str,
        *,
        broker: Optional[str] = None,
        algo: Optional[str] = None,
        symbol: Optional[str] = None,
        exchange: Optional[str] = None,
        metrics: Optional[list[str]] = None,
        thresholds: Optional[dict[str, Any]] = None,
        min_fill_count: int = 10,
        min_notional_usd: float = 10000.0,
        anomaly_limit: Optional[int] = None,
        as_of_date: Optional[str] = None,
        preset: Optional[str] = None,
        granularity: str = rm.DEFAULT_GRANULARITY,
    ) -> dict[str, Any]:
        """组装报告聚合数据。

        granularity：聚合粒度（day / week / month，默认 day），作用于「走势」与
        「分市场金额趋势」两个时间维度小节；day 粒度产出与引入该参数前逐字节一致，
        week / month 使用 ``YYYY-Www`` / ``YYYY-MM`` 期间键（report_measure 单点
        实现，week 按 ISO 8601 归属跨年周）。

        broker/algo/symbol/exchange 支持逗号分隔多值（IN 匹配，前端多选）。
        metrics 控制附加的覆盖率小节统计口径（默认全部 38 个指标）。
        thresholds 控制 S6 异常路由明细的判定阈值（None/空 → 默认阈值）。
        anomaly_limit 控制异常明细返回条数（None = 全量；截断发生在按严重度排序后，
        故截断样本必为最严重的 N 条，且 count 始终为全量命中数）。
        as_of_date / preset 由调用方（装配脚本 / API）透传，仅写入 filters 供报告头
        展示「口径 last=… ，数据截至 …」，使归档报告可自证报告期。
        exchange 不再只是「市场概览的收窄条件」，而是整份报告的作用域：给出时为用户
        口径（含白名单外市场时在 filters.scope.out_of_scope 披露），未给出时为
        BDIB 白名单口径 —— KPI / 覆盖率 / 异常 / 市场概览因此天然可对账。
        filter_options.exchanges 仍忽略 exchange 过滤（供前端筛选下拉展示全部可选
        市场，但受白名单约束）。表不存在时返回带 data_source_warning 的空报告。
        """
        selected = validate_metrics(metrics)
        resolved_granularity = rm.validate_granularity(granularity)
        # 作用域一次性解析：KPI / 直方图 / 走势 / 排行 / 市场概览 / 异常 / 覆盖率
        # 全部共用同一 Exchange 条件（默认白名单；用户指定 exchange 时为用户口径）
        scope = rm.resolve_scope(exchange)
        where, params = self._build_where(
            start_date, end_date, broker, algo, symbol, scope,
        )
        # 筛选下拉的市场选项忽略 exchange 过滤（展示全部可选市场），但仍遵循白名单
        where_no_exchange, params_no_exchange = self._build_where(
            start_date, end_date, broker, algo, symbol, rm.resolve_scope(None),
        )
        conn = None
        try:
            conn = self._mgr.get_connection("fill_bdib", AccessTier.READ)
            if not self._table_exists(conn):
                return self._empty_report(
                    start_date, end_date, broker, algo, symbol, exchange, selected,
                    as_of_date=as_of_date, preset=preset, scope=scope,
                    granularity=resolved_granularity,
                )
            # 报告期一次性构建 fill_bdib 汇率回填临时表，供下方 4 个 fx 查询复用
            self._prepare_fx_enrichment(conn, start_date, end_date)
            report = {
                "filters": self._filters_dict(
                    start_date, end_date, broker, algo, symbol, exchange, selected,
                    as_of_date=as_of_date, preset=preset, scope=scope,
                    granularity=resolved_granularity,
                ),
            }
            report.update(self._query_sections(
                conn, where, params, where_no_exchange, params_no_exchange,
                resolved_granularity,
            ))
        except FileNotFoundError:
            # 只读模式下 fill_bdib.db 缺失 → 空报告（与表缺失同语义, 009）
            return self._empty_report(
                start_date, end_date, broker, algo, symbol, exchange, selected,
                as_of_date=as_of_date, preset=preset, scope=scope,
                granularity=resolved_granularity,
            )
        finally:
            if conn is not None:
                conn.close()

        # 附加所选指标的覆盖率小节（同一作用域；口径与监控页一致）
        report["metric_coverage"] = MetricCoverageService(self._mgr).get_coverage(
            start_date, end_date, selected, scope=scope,
            granularity=resolved_granularity,
        )
        # S6 异常路由明细（阈值可参数化，默认同前端；作用域与聚合各小节一致）；
        # D6：节流统计（阈值命中 / 门槛剔除量）经第二解包点透传进 payload
        anomalies, anomaly_total, throttle = query_anomaly_routes_page_ex(
            self._mgr, start_date, end_date, ThresholdRules.from_payload(thresholds),
            broker=broker, algo=algo, symbol=symbol, exchange=exchange,
            min_fill_count=min_fill_count, min_notional_usd=min_notional_usd,
            limit=anomaly_limit, scope=scope,
        )
        report["anomaly"] = self._anomaly_payload(anomalies, anomaly_total, throttle)
        return report

    def _query_sections(
        self, conn, where: str, params: list[Any],
        where_no_exchange: str, params_no_exchange: list[Any],
        granularity: str = rm.DEFAULT_GRANULARITY,
    ) -> dict[str, Any]:
        """一次连接内完成全部小节聚合（KPI / 走势 / 排行 / 分布 / PWP / 附加 KPI）。

        where 与 where_no_exchange 的差异仅在于是否含用户 exchange 过滤：筛选下拉需
        展示全部可选市场，其余小节与整份报告同作用域。
        各小节 SQL 保持独立（可独立降级），P1-a 不做跨节 SQL 合并；排行门槛的
        「报告期总成交额」复用 weight_coverage 的 total_weight（同一表达式、
        同一作用域，非二次查询）。
        """
        daily_series = self._query_daily_series(conn, where, params, granularity)
        weight_coverage = self._query_weight_coverage(conn, where, params)
        return {
            # 市场概览遵循 exchange 过滤：导出时按交易所整体过滤时，
            # 该小节也仅展示所选交易所（无 exchange 时与 where_no_exchange 等价）。
            "markets": self._query_markets(conn, where, params),
            "filter_options": self._query_filter_options(
                conn, where_no_exchange, params_no_exchange,
            ),
            "market_notional_ranking": self._query_market_notional_ranking(
                conn, where, params,
            ),
            "market_notional_trend": self._query_market_notional_trend(
                conn, where, params, granularity,
            ),
            "kpi": self._query_kpi(conn, where, params),
            "daily_series": daily_series,
            # 014: 走势覆盖度披露。不补零 —— 0 表示「成本为零」，把「无数据」
            # 补成 0 属数据失真；缺失定位交由覆盖率表与 BDIB 缺口附录。
            "daily_series_meta": {
                "covered_days": len(daily_series),
                "granularity": granularity,
            },
            "rankings": self._query_rankings_set(conn, where, params, weight_coverage),
            "pnl_vwap_histogram": self._query_pnl_histogram(conn, where, params),
            "pwp_curve": self._query_pwp_curve(conn, where, params),
            # D5：分市场加权 PWP 小多图数据（跨市场混合的逐档值无物理解释）
            "pwp_by_exchange": self._query_pwp_by_exchange(conn, where, params),
            # 006: 决策基准 / 风险 / 完成率 / 冲击分解
            "extra_kpis": self._query_extra_kpis(conn, where, params),
            "impact_breakdown": self._query_impact_breakdown(conn, where, params),
            # 加权 KPI 的样本量与权重覆盖率（避免把覆盖子集均值读作全量水位）
            "weight_coverage": weight_coverage,
        }

    def _query_rankings_set(
        self, conn, where: str, params: list[Any],
        weight_coverage: Optional[dict[str, Any]],
    ) -> dict[str, Any]:
        """排行集合（D4）：最优/最差双侧 + 门槛排除数披露（broker / algo 各一组）。"""
        total_weight = float((weight_coverage or {}).get("total_weight") or 0.0)
        by_broker, by_broker_worst, excluded_broker = self._query_rankings(
            conn, where, params, "Broker", total_weight,
        )
        by_algo, by_algo_worst, excluded_algo = self._query_rankings(
            conn, where, params, "algo", total_weight,
        )
        return {
            # by_broker / by_algo 保持「最优侧」列表（向后兼容既有消费方）
            "by_broker": by_broker,
            "by_algo": by_algo,
            "by_broker_worst": by_broker_worst,
            "by_algo_worst": by_algo_worst,
            "meta": {
                "min_sample": _RANKING_MIN_SAMPLE,
                "min_notional_share": _RANKING_MIN_NOTIONAL_SHARE,
                "excluded_by_broker": excluded_broker,
                "excluded_by_algo": excluded_algo,
            },
        }

    @staticmethod
    def _anomaly_payload(
        anomalies: list[Any],
        anomaly_total: int,
        throttle: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """异常明细段落：全量计数与截断明细分离，附数据质量计数与导出占位。

        throttle（D6）：阈值命中与门槛剔除量披露，渲染层在明细 notes 区展示。
        """
        rows = [a.__dict__ for a in anomalies]
        return {
            # count 为全量命中数（与 rows 截断解耦）
            "count": anomaly_total,
            "rows": rows,
            "rows_truncated": max(0, anomaly_total - len(rows)),
            # 全量 CSV 导出相对路径；由装配脚本落盘后回填，未导出时为 None
            "export_ref": None,
            # 节流统计（D6）：阈值命中 / 笔数 / 金额 / 豁免 / fill_count 缺失
            "throttle": dict(throttle or {}),
            # 数据质量提示（013）：命中 overfill / 订单参与率 >100% 的条数
            "data_quality": {
                "overfill_count": sum(1 for r in rows if r.get("overfill")),
                "order_par_gt100_count": sum(
                    1 for r in rows if r.get("order_par_gt100")
                ),
            },
        }

    # ── 过滤条件 ─────────────────────────────────────────────────────────

    @staticmethod
    def _build_where(
        start_date: str,
        end_date: str,
        broker: Optional[str],
        algo: Optional[str],
        symbol: Optional[str],
        scope: rm.ReportScope,
    ) -> tuple[str, list[Any]]:
        """构建 WHERE 子句与参数列表（全部 ? 绑定）。

        broker/algo/symbol 支持逗号分隔多值 → IN (...) 匹配（单值等价 =）；
        市场维度统一由作用域承载（默认 BDIB 白名单，用户指定时为用户口径），
        与覆盖率 / 异常 / 健康扫描共用同一条件，避免各小节分母不可对账。
        """
        conditions = ["order_as_of_date BETWEEN ? AND ?"]
        params: list[Any] = [start_date, end_date]
        for column, value in (
            ("Broker", broker), ("algo", algo), ("equ_ticker", symbol),
        ):
            condition, values = rm.dimension_condition(column, value)
            if condition:
                conditions.append(condition)
                params.extend(values)
        scope_sql, scope_params = rm.scope_condition(scope)
        if scope_sql:
            conditions.append(scope_sql)
            params.extend(scope_params)
        return "WHERE " + " AND ".join(conditions), params

    # ── fx 汇率回填（报告期一次性构建，消除 gap sentinel 导致的整组 NULL）──

    def _prepare_fx_enrichment(self, conn, start_date: str, end_date: str) -> None:
        """探测 fill_bdib 汇率回填可行性（不再建临时表）。

        背景（CostView-Report 优化）：原 ``_fx_sum_sql`` 的 gap sentinel 在「任一
        非 USD 路由缺汇率」时把整个市场（乃至整个 KPI）的 notional_usd 置 NULL，
        导致上季度报告仅 3 个市场能算 USD 金额、总成交金额无法计算。fill_bdib
        层 fx_rate 为 fill 级权威源（fx_null=0），此处按主键回填 tca_route_summary
        缺失的 fx_rate，使报告对缺失列具备弹性、无需依赖独立回填脚本。

        注意：本聚合器以 READ 只读事务运行，CREATE TEMP TABLE 被访问层拒绝；
        故改用 CTE（``WITH _fbfx AS (...)``，归类为 read 允许）在每条 fx 查询内
        联回填，避免临时表 DDL。此处仅探测可用性并置 ``_fbfx_ready`` 标志。
        """
        self._fbfx_ready = False
        if not self._has_column(conn, "fx_rate"):
            return
        try:
            has_fb = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='fill_bdib' LIMIT 1"
            ).fetchone() is not None
        except Exception:
            has_fb = False
        self._fbfx_ready = bool(has_fb)

    def _fbfx_cte(self) -> str:
        """fill_bdib 汇率回填 CTE（列名约定 fxf_oad/fb_fx）。

        2026-09-15：实现收敛至 ``report_measure.fbfx_cte``（口径唯一来源），
        此处仅保留方法契约以承接 ``_apply_fx`` 的注入流程。
        """
        return rm.fbfx_cte()

    def _apply_fx(self, sql: str, params: list[Any]) -> tuple[str, list[Any]]:
        """若 fill_bdib 回填可用，将 CTE 前缀注入 SQL 并把日期参数前置。

        params 约定以 [start_date, end_date, *filters] 开头，CTE 的 BETWEEN
        复用前两个日期参数，主查询沿用全部参数。
        """
        if not self._fbfx_ready:
            return sql, params
        return self._fbfx_cte() + sql, [params[0], params[1]] + params

    def _fx_join(self) -> str:
        """fill_bdib 汇率回填 LEFT JOIN 片段（回填可用时生效）。"""
        if not self._fbfx_ready:
            return ""
        return (
            " LEFT JOIN _fbfx"
            " ON _fbfx.OrderId = tca_route_summary.OrderId"
            " AND _fbfx.RouteId = tca_route_summary.RouteId"
            " AND _fbfx.fxf_oad = tca_route_summary.order_as_of_date"
        )

    def _fx_usd_expr(self) -> str:
        """USD 换算因子（含小计价单位修正；换算规则的唯一实现见 report_measure）。

        有效汇率 = COALESCE(tca.fx_rate, fill_bdib 回填 fb_fx)（回填可用时）；
        USD/未知币种缺汇率按 1.0 兜底；非 USD 币种仍缺汇率时该 route 贡献 NULL
        （SUM 忽略，不虚高、亦不再整体置空）。
        """
        effective = "COALESCE(fx_rate, _fbfx.fb_fx)" if self._fbfx_ready else "fx_rate"
        return rm.usd_fx_expr(effective)

    # ── 各小节查询 ───────────────────────────────────────────────

    def _query_markets(
        self, conn, where: str, params: list[Any],
    ) -> list[dict[str, Any]]:
        """可选市场清单：Exchange 去重，遵循传入 where（含 exchange 过滤时同步收窄）。

        每条含 Exchange 与 route 数，按 route 数降序。
        007: 增加 notional / notional_usd（每市场成交金额，USD 换算）。
        """
        has_fx = self._has_column(conn, "fx_rate")
        fx_sum = self._fx_usd_expr() if has_fx else "NULL"
        join = self._fx_join() if has_fx else ""
        sql = f"""
            SELECT COALESCE(Exchange, '(unknown)') AS exchange,
                   COUNT(*) AS route_count,
                   COALESCE(SUM(fill * p_avg), 0) AS notional,
                   SUM(fill * p_avg * ({fx_sum})) AS notional_usd
            FROM {Config.TCA_ROUTE_SUMMARY_TABLE}{join}
            {where}
            GROUP BY Exchange
            ORDER BY route_count DESC, exchange ASC
        """
        sql, params = self._apply_fx(sql, params)
        return [
            {
                "exchange": str(r[0]),
                "route_count": int(r[1]),
                "notional": float(r[2]),
                "notional_usd": self._to_float(r[3]),
            }
            for r in conn.execute(sql, params).fetchall()
        ]

    def _query_market_notional_ranking(
        self, conn, where: str, params: list[Any],
    ) -> list[dict[str, Any]]:
        """按市场的成交金额（美元）排名（008）：notional_usd 降序。

        每条含 Exchange 代码 / 中文显示名 / 本币与 USD 成交金额 / route 数。
        未配置中文名的 Exchange 用代码回退。
        """
        has_fx = self._has_column(conn, "fx_rate")
        fx_sum = self._fx_usd_expr() if has_fx else "NULL"
        join = self._fx_join() if has_fx else ""
        # 排序用有效成交额：有 fx_rate 列用 USD，否则回退本币（无 fx 时 USD 为 NULL）
        order_expr = f"COALESCE(SUM(fill * p_avg * ({fx_sum})), SUM(fill * p_avg))" if has_fx else "SUM(fill * p_avg)"
        sql = f"""
            SELECT COALESCE(Exchange, '(unknown)') AS exchange,
                    COUNT(*) AS route_count,
                    COALESCE(SUM(fill * p_avg), 0) AS notional,
                    SUM(fill * p_avg * ({fx_sum})) AS notional_usd
            FROM {Config.TCA_ROUTE_SUMMARY_TABLE}{join}
            {where}
            GROUP BY Exchange
            ORDER BY {order_expr} DESC, exchange ASC
        """
        sql, params = self._apply_fx(sql, params)
        return [
            {
                "exchange": str(r[0]),
                "name": Config.MARKET_ORDER.get(str(r[0]), str(r[0])),
                "route_count": int(r[1]),
                "notional": float(r[2]),
                "notional_usd": self._to_float(r[3]),
            }
            for r in conn.execute(sql, params).fetchall()
        ]

    def _query_market_notional_trend(
        self, conn, where: str, params: list[Any],
        granularity: str = rm.DEFAULT_GRANULARITY,
    ) -> list[dict[str, Any]]:
        """按市场的成交金额（美元）期间趋势（008）。

        返回 [{date, exchange, notional_usd}, ...] 按期间升序，供前端按市场拆线。
        市场仅列排名中存在的（有成交额的市场），未配置中文名用代码回退。
        ``granularity=week`` / ``month`` 时即「分市场 × 周度 / 月度」交叉视图。
        """
        has_fx = self._has_column(conn, "fx_rate")
        fx_sum = self._fx_usd_expr() if has_fx else "NULL"
        join = self._fx_join() if has_fx else ""
        period_expr = rm.period_key_expr(granularity)
        sql = f"""
            SELECT {period_expr} AS date,
                   COALESCE(Exchange, '(unknown)') AS exchange,
                   SUM(fill * p_avg * ({fx_sum})) AS notional_usd
            FROM {Config.TCA_ROUTE_SUMMARY_TABLE}{join}
            {where}
            GROUP BY {period_expr}, Exchange
            ORDER BY {period_expr} ASC, exchange ASC
        """
        sql, params = self._apply_fx(sql, params)
        return [
            {
                "date": str(r[0]),
                "exchange": str(r[1]),
                "name": Config.MARKET_ORDER.get(str(r[1]), str(r[1])),
                "notional_usd": self._to_float(r[2]),
            }
            for r in conn.execute(sql, params).fetchall()
        ]

    def _query_filter_options(
        self, conn, where: str, params: list[Any],
    ) -> dict[str, list[str]]:
        """筛选选项：优先读持久化维度表（时间无关，daily_update 每日刷新）。

        返回 {brokers, algos, symbols, exchanges}，各按累计次数降序截断
        （控制 payload 大小）。维度表未初始化（首次部署尚未刷新）时回退
        原时间范围查询，保证功能可用。

        市场选项**两条路径都按 BDIB 白名单过滤**：维度表是全市场目录（含已移出
        分析范围的市场），若只有回退路径过滤，同一份报告的市场可选集会随「维度表
        是否就绪」漂移。用户经 API 显式传入白名单外市场时，仍由
        ``filters.scope.out_of_scope`` 在报告头告警承接。
        """
        persisted = _get_persisted_options(self._mgr, conn=conn)
        if persisted is not None:
            return TcaReportAggregator._market_whitelist_only(persisted)
        # 回退：维度表不可用，按原口径对明细表查询（忽略 exchange 过滤）
        result: dict[str, list[str]] = {}
        for dim, col, limit in (
            ("brokers", "Broker", 100),
            ("algos", "algo", 50),
            ("symbols", "equ_ticker", 200),
        ):
            try:
                sql = f"""
                    SELECT COALESCE({col}, '(unknown)') AS v, COUNT(*) AS n
                    FROM {Config.TCA_ROUTE_SUMMARY_TABLE}
                    {where}
                    GROUP BY {col}
                    ORDER BY n DESC, v ASC
                    LIMIT {limit}
                """
                result[dim] = [str(r[0]) for r in conn.execute(sql, params).fetchall()]
            except Exception as exc:
                logger.debug("filter_options[%s] 查询失败: %s", dim, exc)
                result[dim] = []
        # 回退模式下的市场选项来自 markets 清单（与 _query_markets 同口径，已含白名单）
        result["exchanges"] = [m["exchange"] for m in self._query_markets(conn, where, params)]
        return result

    @staticmethod
    def _market_whitelist_only(options: dict[str, list[str]]) -> dict[str, list[str]]:
        """把维度表返回的市场下拉裁剪到 BDIB 白名单内（保序、忽略大小写差异）。"""
        whitelist = set(rm.bdib_whitelist())
        result = dict(options)
        result["exchanges"] = [
            str(ex) for ex in options.get("exchanges") or []
            if str(ex).strip().upper() in whitelist
        ]
        return result

    def _query_kpi(self, conn, where: str, params: list[Any]) -> dict[str, Any]:
        """KPI：route 数、总股数、加权 pnl_vwap、加权 par_rate / RPM。

        均值类指标统一采用成交额加权（与 weighted_pnl_vwap 同源），避免小单
        主导参与率 / RPM 均值；卡片区各指标口径一致、可互相校验。

        007: 增加总成交金额（本币 notional + USD notional + fx_rate 覆盖率）。
        - notional = SUM(fill × p_avg)（本币）
        - notional_usd = SUM(fill × p_avg × fx_rate × minor_unit_factor)（USD 换算，
          仅 USD/未知币种在 fx_rate 缺失时按 1.0 兜底；非 USD 币种缺失汇率时
          整组返回 NULL，Currency ∈ {GBp, ILs, ZAr} 时 ÷100，008）
        - fx_coverage = **USD 换算成功率**（有有效汇率或本身为 USD 的路由占比），
          有效汇率 = COALESCE(tca.fx_rate, fill_bdib 回填)，与 notional_usd 同源；
          None 表示无 fx_rate 列。USD 路由不再被误算为"缺汇率"而拉低覆盖率。
        - notional_usd_excluded = 无法换算 USD 的路由成交金额（本币），
          使"总成交金额被低估多少"可见（此前静默消失）
        """
        has_fx = self._has_column(conn, "fx_rate")
        fx_sum = self._fx_usd_expr() if has_fx else "NULL"
        join = self._fx_join() if has_fx else ""
        fx_cnt, fx_excluded = self._fx_quality_exprs(has_fx)
        sql = f"""
            SELECT COUNT(*) AS route_count,
                   COALESCE(SUM(RouteShares), 0) AS total_shares,
                    {self._weighted_avg_sql("pnl_vwap")} AS weighted_pnl_vwap,
                    {self._weighted_avg_sql("par_rate")} AS avg_par_rate,
                    {self._weighted_avg_sql("RPM")} AS avg_rpm,
                    COALESCE(SUM(fill * p_avg), 0) AS notional,
                    SUM(fill * p_avg * ({fx_sum})) AS notional_usd,
                    {fx_cnt} AS fx_convertible_count,
                    {fx_excluded} AS notional_usd_excluded
            FROM {Config.TCA_ROUTE_SUMMARY_TABLE}{join}
            {where}
        """
        sql, params = self._apply_fx(sql, params)
        row = conn.execute(sql, params).fetchone()
        route_count = int(row[0])
        fx_convertible = row[7]
        fx_coverage = None
        if fx_convertible is not None:
            fx_coverage = round(fx_convertible / route_count, 4) if route_count else None
        return {
            "route_count": route_count,
            "total_route_shares": float(row[1]),
            "weighted_pnl_vwap": self._to_float(row[2]),
            "avg_par_rate": self._to_float(row[3]),
            "avg_rpm": self._to_float(row[4]),
            "notional": float(row[5]),
            "notional_usd": self._to_float(row[6]),
            "fx_coverage": fx_coverage,
            "notional_usd_excluded": self._to_float(row[8]),
        }

    def _fx_quality_exprs(self, has_fx: bool) -> tuple[str, str]:
        """fx 数据质量表达式：(可换算路由数, 无法换算的成交金额)。

        可换算 = 有效汇率非空，或币种本身为 USD/未知（按 1.0 兜底）；
        被排除金额 = 非 USD 币种且无有效汇率的 fill × p_avg（本币口径）。
        无 fx_rate 列时两者均为 NULL（语义为"不可得"，与 0 区分）。
        """
        if not has_fx:
            return "NULL", "NULL"
        eff = "COALESCE(fx_rate, _fbfx.fb_fx)" if self._fbfx_ready else "fx_rate"
        convertible = (
            f"SUM(CASE WHEN {eff} IS NOT NULL OR Currency IS NULL "
            f"OR Currency = 'USD' THEN 1 ELSE 0 END)"
        )
        excluded = (
            f"SUM(CASE WHEN {eff} IS NULL AND Currency IS NOT NULL "
            f"AND Currency <> 'USD' THEN fill * p_avg END)"
        )
        return convertible, excluded

    def _query_daily_series(
        self, conn, where: str, params: list[Any],
        granularity: str = rm.DEFAULT_GRANULARITY,
    ) -> list[dict[str, Any]]:
        """按期间（day / week / month）加权 pnl_vwap / 加权 par_rate 走势。

        day 粒度下分组键为原始 ``YYYYMMDD``，产出与引入粒度参数前逐字节等价；
        week / month 为 ``YYYY-Www`` / ``YYYY-MM`` 期间键（report_measure 单点）。
        """
        period_expr = rm.period_key_expr(granularity)
        sql = f"""
            SELECT {period_expr} AS order_as_of_date, COUNT(*) AS route_count,
                   {self._weighted_avg_sql("pnl_vwap")} AS weighted_pnl_vwap,
                   {self._weighted_avg_sql("par_rate")} AS avg_par_rate
            FROM {Config.TCA_ROUTE_SUMMARY_TABLE}
            {where}
            GROUP BY {period_expr} ORDER BY {period_expr}
        """
        return [
            {
                "date": str(r[0]),
                "route_count": int(r[1]),
                "weighted_pnl_vwap": self._to_float(r[2]),
                "avg_par_rate": self._to_float(r[3]),
            }
            for r in conn.execute(sql, params).fetchall()
        ]

    def _query_rankings(
        self, conn, where: str, params: list[Any],
        dimension: str, total_weight: float,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
        """broker / algo 排行（D4 / DP-1 定稿口径 B）：双维门槛 + 双侧输出。

        - 样本门槛：``n_used >= _RANKING_MIN_SAMPLE``（组内有成交额权重的路由数；
          门槛对象是聚合组，不复用异常明细 fill_count 的单路由语义）；
        - 经济相关性门槛：组成交额（与加权权重同源）占报告期总成交额
          ``>= _RANKING_MIN_NOTIONAL_SHARE``（total_weight 为 0 时关闭该维度）；
        - 双侧输出：最优（加权 pnl_vwap 升序）与最差（降序）各取前 _RANKING_LIMIT，
          与异常明细「严重度优先」哲学对齐 —— 此前仅 ASC 前 10，尾部劣者不可见；
        - 返回 (最优侧, 最差侧, 被门槛排除的组数)，排除量由调用方披露。
        同时披露 n_used / route_count：加权值仅由 pnl_vwap 非 NULL（且有成交额
        权重）的路由决定，route_count 却含全部路由。
        口径注（P1-a 复核 F-e）：金额占比分子（group_weight）要求 pnl_vwap 非 NULL
        （与加权值同源），分母（total_weight）为全部可加权路由的成交额 —— 轻微
        不对称且方向保守（仅在 pnl 覆盖极低时可能误排除经济相关性真实的组，
        0.1% 门槛下实际不可达）。
        """
        used_cond = "pnl_vwap IS NOT NULL AND fill IS NOT NULL AND p_avg IS NOT NULL"
        sql = f"""
            SELECT COALESCE({dimension}, '(unknown)') AS name,
                   COUNT(*) AS route_count,
                   SUM(CASE WHEN {used_cond} THEN 1 ELSE 0 END) AS n_used,
                   SUM(CASE WHEN {used_cond}
                            THEN {rm.WEIGHT_EXPRESSION} ELSE 0 END) AS group_weight,
                   {self._weighted_avg_sql("pnl_vwap")} AS weighted_pnl_vwap,
                   {self._weighted_avg_sql("par_rate")} AS avg_par_rate
            FROM {Config.TCA_ROUTE_SUMMARY_TABLE}
            {where}
            GROUP BY {dimension}
            ORDER BY name
            LIMIT {_RANKING_MAX_GROUPS}
        """
        rows = [
            {
                "name": str(r[0]),
                "route_count": int(r[1]),
                "n_used": int(r[2] or 0),
                "group_weight": float(r[3] or 0.0),
                "weighted_pnl_vwap": self._to_float(r[4]),
                "avg_par_rate": self._to_float(r[5]),
            }
            for r in conn.execute(sql, params).fetchall()
        ]
        eligible = [
            row for row in rows
            if row["n_used"] >= _RANKING_MIN_SAMPLE
            and (
                total_weight <= 0
                or row["group_weight"] >= total_weight * _RANKING_MIN_NOTIONAL_SHARE
            )
        ]

        def _sort_key(row: dict[str, Any]) -> tuple[int, float, str]:
            value = row["weighted_pnl_vwap"]
            return (value is None, value if value is not None else 0.0, row["name"])

        best = sorted(eligible, key=_sort_key)[:_RANKING_LIMIT]
        worst = sorted(eligible, key=_sort_key, reverse=True)[:_RANKING_LIMIT]
        return best, worst, len(rows) - len(eligible)

    def _query_pnl_histogram(
        self, conn, where: str, params: list[Any],
    ) -> dict[str, Any]:
        """pnl_vwap 分布直方图（SQL 侧等宽分桶，P2-4 整改）。

        返回 ``{"buckets", "n_used", "n_total"}``：分布仅覆盖 pnl_vwap 非 NULL
        的路由（BDIB 覆盖子集），披露样本量以免读者误以为分布覆盖全部路由
        （低估尾部风险）。

        此前将区间内全部 pnl_vwap 行拉入 Python/numpy（年区间百万行级内存
        峰值）；改为 MIN/MAX + GROUP BY bucket，空间 O(bins)。
        """
        base = (
            f"FROM {Config.TCA_ROUTE_SUMMARY_TABLE} {where} "
            "AND pnl_vwap IS NOT NULL"
        )
        n_used = int(conn.execute(f"SELECT COUNT(*) {base}", params).fetchone()[0])
        n_total = int(conn.execute(
            f"SELECT COUNT(*) FROM {Config.TCA_ROUTE_SUMMARY_TABLE} {where}", params,
        ).fetchone()[0])
        if n_used == 0:
            return {"buckets": [], "n_used": 0, "n_total": n_total}
        row = conn.execute(
            f"SELECT MIN(pnl_vwap), MAX(pnl_vwap) {base}", params,
        ).fetchone()
        lo, hi = float(row[0]), float(row[1])
        if lo == hi:
            return {
                "buckets": [{"lower": round(lo, 4), "upper": round(hi, 4), "count": n_used}],
                "n_used": n_used, "n_total": n_total,
            }

        width = (hi - lo) / _HISTOGRAM_BINS
        # (v - lo) >= 0 恒成立；v == hi 时 bucket == bins，用 MIN(x, bins-1) 收拢末桶
        sql = f"""
            SELECT MIN(CAST((pnl_vwap - ?) / ? AS INTEGER), {_HISTOGRAM_BINS - 1}) AS bucket,
                   COUNT(*) AS n
            {base}
            GROUP BY bucket ORDER BY bucket
        """
        buckets = conn.execute(sql, [lo, width] + params).fetchall()
        return {
            "buckets": [
                {
                    "lower": round(lo + b * width, 4),
                    "upper": round(lo + (b + 1) * width, 4),
                    "count": int(n),
                }
                for b, n in buckets
            ],
            "n_used": n_used,
            "n_total": n_total,
        }

    def _query_pwp_curve(
        self, conn, where: str, params: list[Any],
    ) -> list[dict[str, Any]]:
        """PWP 五档位均值曲线（D5：成交额加权，与全报告唯一加权口径同源）。

        此前为等权 AVG —— 与加权 KPI 不可对账，且 PWP 不在 WEIGHTED_METRICS
        体系内（weight_coverage 不披露其样本量）。加权后与 KPI 加权口径同源，
        跨期对比与 broker 归因才成立。
        """
        avgs = ", ".join(self._weighted_avg_sql(col) for col, _ in _PWP_RATE_LABELS)
        sql = f"SELECT {avgs} FROM {Config.TCA_ROUTE_SUMMARY_TABLE} {where}"
        row = conn.execute(sql, params).fetchone()
        return [
            {"rate": rate, "avg_pwp": self._to_float(row[i])}
            for i, (_, rate) in enumerate(_PWP_RATE_LABELS)
        ]

    def _query_pwp_by_exchange(
        self, conn, where: str, params: list[Any],
    ) -> list[dict[str, Any]]:
        """分市场加权 PWP 曲线（D5 / DP-2 定稿口径：聚合曲线 + Top N 市场小多图）。

        PWP 的经济含义依赖市场微观结构，跨市场混合的**逐档值**无物理解释
        （与订单参与率「跨市场求和无物理意义故按 Exchange 分组」契约同理）；
        但全市场聚合加权曲线回答「组合整体执行质量水位」仍合法（与加权
        pnl_vwap KPI 同构）。本查询按市场分组输出 Top N（按组成交额降序），
        分市场解释由渲染层小多图承接。
        """
        weighted = [self._weighted_avg_sql(col) for col, _ in _PWP_RATE_LABELS]
        sql = f"""
            SELECT COALESCE(Exchange, '(unknown)') AS exchange,
                   COALESCE(SUM(CASE WHEN fill IS NOT NULL AND p_avg IS NOT NULL
                                     THEN {rm.WEIGHT_EXPRESSION} END), 0) AS group_weight,
                   {", ".join(weighted)}
            FROM {Config.TCA_ROUTE_SUMMARY_TABLE}
            {where}
            GROUP BY Exchange
            ORDER BY group_weight DESC
            LIMIT {_PWP_TOP_MARKETS}
        """
        return [
            {
                "exchange": str(r[0]),
                "name": Config.MARKET_ORDER.get(str(r[0]), str(r[0])),
                "curve": [
                    {"rate": rate, "avg_pwp": self._to_float(r[2 + i])}
                    for i, (_, rate) in enumerate(_PWP_RATE_LABELS)
                ],
            }
            for r in conn.execute(sql, params).fetchall()
        ]

    def _query_extra_kpis(self, conn, where: str, params: list[Any]) -> dict[str, Any]:
        """决策基准 / 实现短缺 / 风险 / 完成率 / 未成交缺口 聚合（006 增补）。

        对齐文献 D1（决策基准 + 市场时间基准并存）与 B2-3（风险维度）：
        - arrival_cost_bps / wagner_is_bps：成交额加权
        - cost_stddev / cost_cvar / cost_p95：成交额加权
        - avg_fill：组合级完成率 SUM(fill) / SUM(RouteShares)，对大额未成交敏感
          （逐单简单平均会被大量小额成交掩盖真实执行缺口）
        - unfilled_notional_usd：未成交金额缺口，价格走回退链
          COALESCE(p_avg, p_arrival, p_decision, p_close)。原实现以 p_avg 计价，
          零成交路由 p_avg 为 NULL → 整条贡献被 SUM 跳过：「完全未执行」这一最严重
          情形对缺口金额贡献为 0。现按缺口口径计入（fill 为 NULL 视作零成交），
          仅正缺口计入，价格全缺时该路由贡献 NULL（不虚高）。
        - zero_fill_routes / zero_fill_notional_usd：零成交路由数与委托金额 ——
          单独度量「计划成交但一股未成」的规模（此前仅 avg_fill 分母可见其存在）。
        - unfilled_notional_unpriced_routes：因价格全缺而无法计入缺口的路由数，
          披露剩余低估规模，避免读者把缺口读作完整值。
        """
        has_fx = self._has_column(conn, "fx_rate")
        fx_sum = self._fx_usd_expr() if has_fx else "NULL"
        join = self._fx_join() if has_fx else ""
        weighted = lambda m: self._weighted_avg_sql(m)  # noqa: E731
        price = rm.unfilled_price_expr(sorted(self._table_columns(conn)))
        money_ready = bool(has_fx and price)
        if price:
            unfilled = rm.unfilled_notional_expr(price, fx_sum, usd=has_fx)
            unpriced = rm.unfilled_unpriced_expr(price)
            zero_notional = rm.zero_fill_notional_expr(price, fx_sum, usd=has_fx)
        else:
            unfilled = unpriced = zero_notional = "NULL"
        sql = f"""
            SELECT
                {weighted("arrival_cost_bps")} AS arrival_cost_bps,
                {weighted("wagner_is_bps")} AS wagner_is_bps,
                {weighted("cost_stddev")} AS cost_stddev,
                {weighted("cost_cvar")} AS cost_cvar,
                {weighted("cost_p95")} AS cost_p95,
                SUM(fill) * 1.0 / NULLIF(SUM(RouteShares), 0) AS avg_fill,
                {unfilled} AS unfilled_notional_usd,
                {unpriced} AS unfilled_notional_unpriced_routes,
                {rm.zero_fill_count_expr()} AS zero_fill_routes,
                {zero_notional} AS zero_fill_notional_usd
            FROM {Config.TCA_ROUTE_SUMMARY_TABLE}{join}
            {where}
        """
        sql, params = self._apply_fx(sql, params)
        row = conn.execute(sql, params).fetchone()
        return {
            "arrival_cost_bps": self._to_float(row[0]),
            "wagner_is_bps": self._to_float(row[1]),
            "cost_stddev": self._to_float(row[2]),
            "cost_cvar": self._to_float(row[3]),
            "cost_p95": self._to_float(row[4]),
            "avg_fill": self._to_float(row[5]),
            # 无 fx_rate 列 / 无可用价格列时与 notional_usd 同语义返回 None（不误报为 0）
            "unfilled_notional_usd": self._to_float(row[6]) if money_ready else None,
            "unfilled_notional_unpriced_routes": (
                self._to_int(row[7]) if price else None
            ),
            "zero_fill_routes": self._to_int(row[8]) or 0,
            "zero_fill_notional_usd": (
                self._to_float(row[9]) if money_ready else None
            ),
        }

    def _query_weight_coverage(
        self, conn, where: str, params: list[Any],
    ) -> dict[str, Any]:
        """加权 KPI 的样本量与权重覆盖率（加权均值实为覆盖子集均值）。

        加权均值只由「指标非 NULL 且有成交额权重」的路由决定，而均值本身不暴露
        该子集规模；BDIB 缺口集中在少数大单时，条数覆盖 95% 可能对应权重覆盖 60%，
        KPI 数值「看起来正常」实为子样本均值。故对每个加权指标同时披露：
        - 样本覆盖 = n_used / n_total（条数口径）
        - 权重覆盖 = used_weight / total_weight（成交额口径，与 notional 同源）
        两者之一低于阈值即标记 insufficient，由渲染层提示「结论仅供参考」。
        """
        metrics_sql = rm.weight_coverage_select(rm.WEIGHTED_METRICS)
        sql = f"SELECT {metrics_sql} FROM {Config.TCA_ROUTE_SUMMARY_TABLE} {where}"
        row = conn.execute(sql, params).fetchone()
        n_total = int(row[0] or 0)
        total_weight = float(row[1] or 0.0)
        metrics: dict[str, Any] = {}
        for index, metric in enumerate(rm.WEIGHTED_METRICS):
            metrics[metric] = rm.weight_coverage_entry(
                int(row[2 + index * 2] or 0),
                n_total,
                float(row[3 + index * 2] or 0.0),
                total_weight,
            )
        return {
            "metrics": metrics,
            "threshold_pct": rm.SAMPLE_COVERAGE_MIN_PCT,
            "n_total": n_total,
            "total_weight": total_weight,
        }

    def _query_impact_breakdown(self, conn, where: str, params: list[Any]) -> dict[str, Any]:
        """市场冲击分解（B2-2）：暂时冲击 5/10/30min + 永久冲击 聚合。

        同时披露跨日恢复占比：恢复窗口越界时冲击值改用次日收盘价兜底，
        混合口径会稀释指标含义，故显式给出被截断路由条数与占比
        （recovery_truncated 列缺失时降级为 None）。
        """
        weighted = lambda m: self._weighted_avg_sql(m)  # noqa: E731
        has_truncated = self._has_column(conn, "recovery_truncated")
        truncated_expr = (
            "SUM(COALESCE(recovery_truncated, 0))" if has_truncated else "NULL"
        )
        # D15：截断占比分母改「冲击计算样本」（任一冲击指标可计算的路由），
        # 与冲击加权均值的计算范围一致；全量路由作分母会稀释跨日兜底口径的渗透度
        impact_sample_expr = (
            "SUM(CASE WHEN perm_impact_bps IS NOT NULL "
            "OR temp_impact_5min_bps IS NOT NULL OR temp_impact_10min_bps IS NOT NULL "
            "OR temp_impact_30min_bps IS NOT NULL THEN 1 ELSE 0 END)"
        )
        sql = f"""
            SELECT
                {weighted("temp_impact_5min_bps")} AS t5,
                {weighted("temp_impact_10min_bps")} AS t10,
                {weighted("temp_impact_30min_bps")} AS t30,
                {weighted("perm_impact_bps")} AS perm,
                {weighted("close_cost_bps")} AS close_cost,
                {truncated_expr} AS truncated_count,
                {impact_sample_expr} AS impact_sample
            FROM {Config.TCA_ROUTE_SUMMARY_TABLE}
            {where}
        """
        row = conn.execute(sql, params).fetchone()
        truncated = self._to_float(row[5])
        impact_sample = int(row[6] or 0)
        truncated_int = int(truncated) if truncated is not None else 0
        # 防御（P1-a 复核 F-f）：分母自洽依赖写入方不变量「truncated 路由的冲击值
        # 非 NULL」；不变量被上游破坏时取两者较大值，share 不超 1 —— 不静默钳制
        # 数值、不掩盖上游违约，仅保证比率语义有效
        impact_denominator = max(impact_sample, truncated_int)
        return {
            "temp_impact_5min_bps": self._to_float(row[0]),
            "temp_impact_10min_bps": self._to_float(row[1]),
            "temp_impact_30min_bps": self._to_float(row[2]),
            "perm_impact_bps": self._to_float(row[3]),
            "close_cost_bps": self._to_float(row[4]),
            "recovery_truncated_count": int(truncated) if truncated is not None else None,
            "impact_sample_count": impact_sample,
            "recovery_truncated_share": (
                round(truncated / impact_denominator, 4)
                if truncated is not None and impact_denominator > 0 else None
            ),
        }

    # ── 工具函数 ─────────────────────────────────────────────────────────

    @staticmethod
    def _weighted_avg_sql(metric: str) -> str:
        """成交额加权均值 SQL 片段（口径实现的唯一来源为 report_measure）。

        权重为实际成交额 fill × p_avg（traded 口径），与 KPI notional 同源；
        该函数被 KPI / daily_series / rankings / extra_kpis / impact_breakdown
        五处复用，改动即全局一致，避免各小节口径分叉。
        """
        return rm.weighted_avg_sql(metric)

    @staticmethod
    def _table_exists(conn) -> bool:
        """tca_route_summary 表/视图是否存在（实现见 monitoring/_common.py）。"""
        return _common.tca_summary_exists(conn)

    @staticmethod
    def _table_columns(conn) -> set[str]:
        """tca_route_summary 现有列名集合（小写；实现见 monitoring/_common.py）。"""
        return _common.tca_summary_columns(conn)

    @classmethod
    def _has_column(cls, conn, column: str) -> bool:
        """tca_route_summary 是否含指定列（幂等兼容旧 schema）。"""
        return column.lower() in cls._table_columns(conn)

    @staticmethod
    def _to_float(value: Any) -> Optional[float]:
        """数值安全转换，None/NaN/不可解析 → None（统一实现，不再抛异常）。"""
        return _common.to_float(value)

    @staticmethod
    def _to_int(value: Any) -> Optional[int]:
        """整数安全转换（计数类列），None/非法值 → None。"""
        return _common.to_int(value)

    @staticmethod
    def _filters_dict(
        start_date: str, end_date: str, broker: Optional[str], algo: Optional[str],
        symbol: Optional[str], exchange: Optional[str], metrics: list[str],
        as_of_date: Optional[str] = None, preset: Optional[str] = None,
        scope: Optional[rm.ReportScope] = None,
        granularity: str = rm.DEFAULT_GRANULARITY,
    ) -> dict[str, Any]:
        """过滤条件 + 报告期 + 作用域 + 粒度（报告自证「统计了哪些市场、什么粒度」）。"""
        return {
            "start_date": start_date, "end_date": end_date,
            "broker": broker, "algo": algo, "symbol": symbol, "exchange": exchange,
            "metrics": metrics,
            "as_of_date": as_of_date, "preset": preset,
            "granularity": granularity,
            "scope": scope.to_payload() if scope else None,
        }

    def _empty_report(
        self, start_date: str, end_date: str, broker: Optional[str],
        algo: Optional[str], symbol: Optional[str], exchange: Optional[str],
        selected: list[str], as_of_date: Optional[str] = None,
        preset: Optional[str] = None, scope: Optional[rm.ReportScope] = None,
        granularity: str = rm.DEFAULT_GRANULARITY,
    ) -> dict[str, Any]:
        return {
            "filters": self._filters_dict(
                start_date, end_date, broker, algo, symbol, exchange, selected,
                as_of_date=as_of_date, preset=preset, scope=scope,
                granularity=granularity,
            ),
            "markets": [],
            "filter_options": {"brokers": [], "algos": [], "symbols": [], "exchanges": []},
            "market_notional_ranking": [],
            "market_notional_trend": [],
            "kpi": None,
            "daily_series": [],
            "daily_series_meta": {"covered_days": 0, "granularity": granularity},
            "rankings": {
                "by_broker": [], "by_algo": [],
                "by_broker_worst": [], "by_algo_worst": [],
                "meta": {
                    "min_sample": _RANKING_MIN_SAMPLE,
                    "min_notional_share": _RANKING_MIN_NOTIONAL_SHARE,
                    "excluded_by_broker": 0, "excluded_by_algo": 0,
                },
            },
            "pnl_vwap_histogram": {"buckets": [], "n_used": 0, "n_total": 0},
            "pwp_curve": [],
            "pwp_by_exchange": [],
            "extra_kpis": None,
            "impact_breakdown": None,
            "weight_coverage": None,
            "anomaly": {
                "count": 0, "rows": [], "rows_truncated": 0, "export_ref": None,
                "throttle": {},
                "data_quality": {"overfill_count": 0, "order_par_gt100_count": 0},
            },
            "metric_coverage": None,
            "evaluation": None,
            "data_source_warning": "tca_route_summary 不存在 — 请先运行管道 S5.5",
        }
