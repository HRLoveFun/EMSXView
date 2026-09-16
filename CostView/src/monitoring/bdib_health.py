"""BDIB 数据健康服务 — SQLite 热数据 + Parquet 分区双源扫描。

按交易日对比"processed_fills 中有成交的 ticker 集合"与
"raw_bdib 双源中有行情的 ticker 集合"，输出覆盖率与健康分级：
    ok            — 全部成交 ticker 均有 BDIB 行情
    partial       — 部分 ticker 缺失，且日期仍在 Bloomberg 保留窗口内（可回补）
    missing       — 当日完全无 BDIB 数据，且仍在保留窗口内（可回补）
    unrecoverable — 存在缺口且日期已超出保留窗口（BDIB_API_RETENTION_DAYS，无法回补）

Parquet 侧使用聚合 SQL（GROUP BY 一次完成）；SQLite 侧按交易日逐日查询
（复用 idx_raw_bdib_date 索引）——范围级 DISTINCT 在 175M 行级别会 hang
数十秒，逐日是有意取舍（见 _scan_sqlite docstring）。
"""

from __future__ import annotations

import enum
import logging
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from data_access.config import Config
from data_access.storage.connection import AccessTier, ConnectionManager
from data_access.storage.market_store import MarketStoreReader

from . import report_measure as rm
from . import _common

logger = logging.getLogger(__name__)

#: 缺口明细中 missing_tickers 列表的最大返回长度（防止单日数百 ticker 撑爆响应）
MAX_MISSING_TICKERS_DETAIL = 50

#: get_health_safe 并发扫描闸（P2-5 整改）：超时被放弃的 daemon 线程仍会继续
#: 占用 IO/CPU 扫描，无上限并发导出会堆积线程；限流为同时 2 个扫描。
_HEALTH_SCAN_SEMAPHORE = threading.Semaphore(2)


class BdibHealthStatus(str, enum.Enum):
    """BDIB 健康分级。"""

    OK = "ok"
    PARTIAL = "partial"
    MISSING = "missing"
    UNRECOVERABLE = "unrecoverable"


class BdibHealthService:
    """BDIB 健康扫描服务（双源合并）。"""

    def __init__(
        self,
        connection_manager: Optional[ConnectionManager] = None,
        parquet_dir: Optional[Path] = None,
        retention_days: Optional[int] = None,
    ):
        self._mgr = connection_manager or ConnectionManager()
        self._parquet_dir = parquet_dir or Config.BDIB_PARQUET_DIR
        self._retention_days = retention_days or Config.BDIB_API_RETENTION_DAYS

    def get_health(
        self,
        start_date: str,
        end_date: str,
        *,
        today: Optional[date] = None,
        scope: Optional[rm.ReportScope] = None,
    ) -> dict[str, Any]:
        """扫描 [start_date, end_date] 内有成交交易日的 BDIB 健康度。

        scope 为报告作用域（None → 默认 BDIB 白名单）：成交 ticker 集合与缺口金额
        均按同一作用域裁剪，使报告头的缺口附录与 KPI / 覆盖率 / 异常明细严格同口径
        —— 此前健康扫描独立取白名单，用户按市场过滤时两者只在"恰好同源"时一致。

        Returns:
            {"start_date", "end_date", "status", "scope", "retention_days",
             "dates": [...], "summary": {各状态日数、最近缺口日期、缺口 ticker 总数}}
        """
        today = today or date.today()
        resolved = scope or rm.resolve_scope(None)
        fill_map = self._load_fill_tickers(start_date, end_date, resolved)
        if not fill_map:
            return self._empty_result(start_date, end_date, resolved)

        sql_rows, sql_tickers = self._scan_sqlite(start_date, end_date)
        pq_rows, pq_tickers = self._scan_parquet(start_date, end_date)
        ticker_weight, gap_fx_usd = self._load_ticker_weight(start_date, end_date, resolved)
        # TCA 整日缺失检测（缺陷 D11）：有成交记录但 tca_route_summary 无汇总行的日期
        # （管道 S5.5 未产出）。None 表示日期集不可得，检测显式降级而非静默放行。
        tca_dates = self._load_tca_dates(start_date, end_date, resolved)

        dates = []
        for d in sorted(fill_map):
            bdib_set = sql_tickers.get(d, set()) | pq_tickers.get(d, set())
            missing = fill_map[d] - bdib_set
            dates.append(self._build_date_entry(
                d, fill_map[d], sql_rows.get(d, 0), pq_rows.get(d, 0),
                bdib_set, today,
                missing_weight=self._sum_missing_weight(d, missing, ticker_weight),
                tca_missing=(d not in tca_dates) if tca_dates is not None else False,
            ))
        result = {
            "start_date": start_date,
            "end_date": end_date,
            "status": "ok",
            "scope": resolved.to_payload(),
            "retention_days": self._retention_days,
            "dates": dates,
            "summary": self._build_summary(dates),
            # 缺口金额是否为 USD 口径（False = 旧 schema 无 fx_rate 列，金额为本币合计，
            # 渲染层须显式提示，避免读者把本币数读作 USD）
            "gap_notional_fx_usd": gap_fx_usd,
        }
        if tca_dates is None:
            result["data_source_warning"] = (
                "TCA 汇总日期集不可得，TCA 整日缺失检测未执行"
            )
        else:
            result["tca_gap_dates"] = sorted(set(fill_map) - tca_dates)
        return result

    # ── 数据加载 ─────────────────────────────────────────────────────────

    def _load_fill_tickers(
        self, start_date: str, end_date: str, scope: Optional[rm.ReportScope] = None,
    ) -> dict[str, set[str]]:
        """processed_fills 中有成交的 (日期 → ticker 集合)，按报告作用域裁剪。

        默认口径为 BDIB_EXCHANGE 白名单：白名单外交易所（CN/BZ/MM/PW/DC/IT/NZ 等，
        2026-07-16 起移出分析范围）本就不拉取 BDIB 行情，将其计入缺口会虚高
        "BDIB 缺口"、拉低指标覆盖率的观感（实际为 out-of-scope，非数据缺失）。
        作用域由调用方传入（与 KPI / 覆盖率 / 异常明细同源，不再各自取白名单）。

        注：作用域过滤依赖 processed_fills 的 Exchange 列。部分测试/旧表无该列，
        此时退化为"全部成交 ticker"（与历史行为一致），避免硬失败。
        """
        condition, scope_params = rm.scope_condition(scope or rm.resolve_scope(None))
        conn = None
        try:
            conn = self._mgr.get_connection("processed_fills", AccessTier.READ)
            has_exchange = self._table_has_column(conn, Config.PROCESSED_FILLS_TABLE, "Exchange")
            if has_exchange and condition:
                cursor = conn.execute(
                    f"SELECT DISTINCT order_as_of_date, equ_ticker "
                    f"FROM {Config.PROCESSED_FILLS_TABLE} "
                    f"WHERE order_as_of_date BETWEEN ? AND ? AND equ_ticker IS NOT NULL "
                    f"AND {condition}",
                    [start_date, end_date, *scope_params],
                )
            else:
                cursor = conn.execute(
                    f"SELECT DISTINCT order_as_of_date, equ_ticker "
                    f"FROM {Config.PROCESSED_FILLS_TABLE} "
                    f"WHERE order_as_of_date BETWEEN ? AND ? AND equ_ticker IS NOT NULL",
                    [start_date, end_date],
                )
            result: dict[str, set[str]] = {}
            for oad, ticker in cursor.fetchall():
                result.setdefault(str(oad), set()).add(str(ticker))
            return result
        except Exception as exc:
            logger.warning("读取 processed_fills ticker 集合失败: %s", exc)
            return {}
        finally:
            if conn is not None:
                conn.close()

    @staticmethod
    def _table_has_column(conn, table: str, column: str) -> bool:
        """判断表是否含指定列（幂等兼容旧 schema / 测试 fixture；实现见 _common.py）。"""
        return _common.has_column(conn, table, column)

    def _scan_sqlite(
        self, start_date: str, end_date: str,
    ) -> tuple[dict[str, int], dict[str, set[str]]]:
        """SQLite @raw_bdib 扫描：每日行数 + (交易日 × ticker 集合)。

        按交易日逐日查询（复用 idx_raw_bdib_date 索引），避免对全量数据做
        范围级 DISTINCT（175M 行级别扫描会在大区间时 hangs 数十秒乃至更久，
        是报告导出「速度很慢」的根因之一）。
        """
        conn = None
        try:
            conn = self._mgr.get_connection("raw_bdib", AccessTier.READ)
            dates = [
                str(d) for (d,) in conn.execute(
                    f"SELECT DISTINCT order_as_of_date FROM {Config.RAW_BDIB_TABLE} "
                    "WHERE order_as_of_date BETWEEN ? AND ? ORDER BY order_as_of_date",
                    [start_date, end_date],
                ).fetchall()
            ]
            row_counts: dict[str, int] = {}
            tickers: dict[str, set[str]] = {}
            for d in dates:
                rc = conn.execute(
                    f"SELECT COUNT(*) FROM {Config.RAW_BDIB_TABLE} "
                    "WHERE order_as_of_date = ?",
                    [d],
                ).fetchone()[0]
                row_counts[d] = int(rc)
                tk = conn.execute(
                    f"SELECT DISTINCT equ_ticker FROM {Config.RAW_BDIB_TABLE} "
                    "WHERE order_as_of_date = ?",
                    [d],
                ).fetchall()
                tickers[d] = {str(t[0]) for t in tk}
            return row_counts, tickers
        except Exception as exc:
            logger.warning("raw_bdib SQLite 扫描失败: %s", exc)
            return {}, {}
        finally:
            if conn is not None:
                conn.close()

    def _scan_parquet(
        self, start_date: str, end_date: str,
    ) -> tuple[dict[str, int], dict[str, set[str]]]:
        """Parquet 分区：每日行数 + (日期 → ticker 集合)，带 year/month 分区裁剪。"""
        if not self._parquet_dir.exists():
            return {}, {}
        if not any(self._parquet_dir.rglob("*.parquet")):
            return {}, {}
        partition_filter = self._partition_filter(start_date, end_date)
        reader = MarketStoreReader(self._parquet_dir)
        try:
            rows_df = reader.query(
                f"SELECT order_as_of_date, COUNT(*) AS n FROM {reader.table_name} "
                f"WHERE {partition_filter} AND order_as_of_date BETWEEN ? AND ? "
                "GROUP BY order_as_of_date",
                [start_date, end_date],
            )
            tick_df = reader.query(
                f"SELECT DISTINCT order_as_of_date, equ_ticker FROM {reader.table_name} "
                f"WHERE {partition_filter} AND order_as_of_date BETWEEN ? AND ?",
                [start_date, end_date],
            )
        finally:
            reader.close()
        return self._df_to_row_counts(rows_df), self._df_to_tickers(tick_df)

    # ── 结果组装 ─────────────────────────────────────────────────────────

    def _build_date_entry(
        self,
        date_str: str,
        fill_tickers: set[str],
        sqlite_rows: int,
        parquet_rows: int,
        bdib_tickers: set[str],
        today: date,
        missing_weight: tuple[int, float, float] = (0, 0, 0),
        tca_missing: bool = False,
    ) -> dict[str, Any]:
        """单日健康记录：覆盖率 + 分级 + 保留窗口 + 缺口影响面。

        missing_weight 为 (受影响 route 数, 缺口成交金额, 未换算本币金额)。
        ticker 数只反映「多少个标的缺失」，无法回答"影响多少成交量"；
        金额/路由权重使缺口严重度可度量（例如缺 3 个 ticker 却覆盖 80% 成交额
        的情形得以暴露）。
        ``tca_missing``：当日有成交记录但 tca_route_summary 无汇总行（管道 S5.5
        未产出）—— 该日走势/覆盖率缺失属管道缺口，而非非交易日。
        """
        missing = sorted(fill_tickers - bdib_tickers)
        fill_count = len(fill_tickers)
        coverage = (fill_count - len(missing)) / fill_count * 100.0 if fill_count else 100.0
        days_old = (today - datetime.strptime(date_str, Config.DATE_FORMAT).date()).days
        retention_left = self._retention_days - days_old
        missing_routes, missing_notional, missing_unconvertible = missing_weight
        return {
            "date": date_str,
            "fill_tickers": fill_count,
            "bdib_tickers": fill_count - len(missing),
            "coverage_pct": round(coverage, 2),
            "missing_ticker_count": len(missing),
            "missing_tickers": missing[:MAX_MISSING_TICKERS_DETAIL],
            "missing_route_count": missing_routes,
            "missing_notional": missing_notional,
            "missing_notional_unconvertible": missing_unconvertible,
            "tca_missing": tca_missing,
            "sqlite_rows": sqlite_rows,
            "parquet_rows": parquet_rows,
            "status": self._classify(
                len(missing), fill_count, retention_left,
            ).value,
            "retention_days_left": retention_left,
        }

    @staticmethod
    def _classify(
        missing_count: int, fill_count: int, retention_left: int,
    ) -> BdibHealthStatus:
        """四级分级：ok / partial / missing / unrecoverable。

        以「缺口 ticker 数」精确判定 ok，不再依赖 round(coverage, 2) 后的百分比
        （99.995% 会被 round 成 100.0 而误判为 ok）。
        """
        if missing_count <= 0:
            return BdibHealthStatus.OK
        if retention_left < 0:
            return BdibHealthStatus.UNRECOVERABLE
        if fill_count > 0 and missing_count >= fill_count:
            return BdibHealthStatus.MISSING
        return BdibHealthStatus.PARTIAL

    @staticmethod
    def _build_summary(dates: list[dict[str, Any]]) -> dict[str, Any]:
        """汇总各状态日数与最近缺口日期。"""
        counts = {s.value: 0 for s in BdibHealthStatus}
        for d in dates:
            counts[d["status"]] += 1
        gap_dates = [d["date"] for d in dates if d["status"] != BdibHealthStatus.OK.value]
        return {
            "total_dates": len(dates),
            "ok_dates": counts[BdibHealthStatus.OK.value],
            "partial_dates": counts[BdibHealthStatus.PARTIAL.value],
            "missing_dates": counts[BdibHealthStatus.MISSING.value],
            "unrecoverable_dates": counts[BdibHealthStatus.UNRECOVERABLE.value],
            "recoverable_gap_dates": counts[BdibHealthStatus.PARTIAL.value]
            + counts[BdibHealthStatus.MISSING.value],
            "total_missing_tickers": sum(d["missing_ticker_count"] for d in dates),
            "total_missing_routes": sum(d.get("missing_route_count", 0) for d in dates),
            "total_missing_notional": sum(d.get("missing_notional", 0.0) for d in dates),
            "total_missing_notional_unconvertible": sum(
                d.get("missing_notional_unconvertible", 0.0) for d in dates
            ),
            "tca_missing_dates": sum(1 for d in dates if d.get("tca_missing")),
            "latest_gap_date": max(gap_dates) if gap_dates else None,
        }

    # ── 工具函数 ─────────────────────────────────────────────────────────

    @staticmethod
    def _partition_filter(start_date: str, end_date: str) -> str:
        """生成 year/month 分区裁剪条件（常量表达式，无用户输入注入风险）。"""
        sy, sm = start_date[:4], start_date[4:6]
        ey, em = end_date[:4], end_date[4:6]
        return (
            f"(year > '{sy}' OR (year = '{sy}' AND month >= '{sm}')) "
            f"AND (year < '{ey}' OR (year = '{ey}' AND month <= '{em}'))"
        )

    @staticmethod
    def _df_to_row_counts(df: pd.DataFrame) -> dict[str, int]:
        if df.empty:
            return {}
        return {str(d): int(n) for d, n in zip(df["order_as_of_date"], df["n"])}

    @staticmethod
    def _df_to_tickers(df: pd.DataFrame) -> dict[str, set[str]]:
        tickers: dict[str, set[str]] = {}
        if df.empty:
            return tickers
        for oad, ticker in zip(df["order_as_of_date"], df["equ_ticker"]):
            tickers.setdefault(str(oad), set()).add(str(ticker))
        return tickers

    def _load_ticker_weight(
        self, start_date: str, end_date: str, scope: Optional[rm.ReportScope] = None,
    ) -> tuple[dict[tuple[str, str], tuple[int, float, float]], bool]:
        """tca_route_summary 按 (日期, ticker) 汇总的 (route 数, 成交金额, 未换算金额)。

        返回 ``(权重表, 是否 USD 口径)``：``False`` = 旧 schema 无 fx_rate 列，
        金额退化为本币合计（历史行为）——此时字段仍名 notional 但口径为本币，
        调用方须据此在渲染层显式提示，避免读者把本币数读作 USD。

        金额口径与 KPI 同源（换算规则唯一实现见 report_measure.usd_fx_expr）：
        - 有效汇率 = COALESCE(tca.fx_rate, fill_bdib 回填 fb_fx)（回填可用时），
          与 KPI 的 COALESCE 链一致（历史缺陷：此前未接回填，回退本币概率高于 KPI）；
        - 换算含小计价单位修正（GBp/ILs/ZAr ×0.01 —— 历史缺陷：缺此修正使 GBp
          市场缺口金额被高估 100 倍）；
        - 逐行换算：非 USD 且缺有效汇率的路由贡献 NULL（SUM 忽略，不虚高），其本币
          金额单独计入 notional_unconvertible 披露。此前 ``COALESCE(SUM(a), SUM(b))``
          是整组粒度回退：组内部分路由缺汇率时缺口金额被静默低估且无披露。
        作用域由调用方传入，与覆盖率 / KPI 同源。
        表缺失 / 查询失败时返回空权重表（不阻断健康分级主体逻辑；口径标志置 True
        —— 金额不可得时不误标「本币口径」）。
        """
        condition, scope_params = rm.scope_condition(scope or rm.resolve_scope(None))
        conn = None
        try:
            conn = self._mgr.get_connection("fill_bdib", AccessTier.READ)
            has_fx = self._table_has_column(
                conn, Config.TCA_ROUTE_SUMMARY_TABLE, "fx_rate",
            )
            if not has_fx:
                # 旧 schema 无 fx_rate 列：金额退化为本币口径（历史行为），无换算语义
                cte, join, fx_expr = "", "", "1.0"
            else:
                fbfx_ready = self._fill_bdib_table_exists(conn)
                effective = (
                    "COALESCE(t.fx_rate, _fbfx.fb_fx)" if fbfx_ready else "t.fx_rate"
                )
                cte = self._fbfx_cte() if fbfx_ready else ""
                join = self._fbfx_join() if fbfx_ready else ""
                fx_expr = rm.usd_fx_expr(effective, currency_column="t.Currency")
            scope_sql = f" AND {condition}" if condition else ""
            params: list[Any] = [start_date, end_date, *scope_params]
            if cte:
                # CTE 内的 BETWEEN 复用前两个日期参数（与 report_aggregator._apply_fx 同约定）
                params = [start_date, end_date] + params
            cursor = conn.execute(
                f"{cte}"
                "SELECT t.order_as_of_date, t.equ_ticker, COUNT(*), "
                f"SUM(t.fill * t.p_avg * ({fx_expr})) AS notional_usd, "
                f"SUM(CASE WHEN ({fx_expr}) IS NULL "
                "THEN t.fill * t.p_avg ELSE 0 END) AS notional_unconvertible "
                f"FROM {Config.TCA_ROUTE_SUMMARY_TABLE} t{join} "
                "WHERE t.order_as_of_date BETWEEN ? AND ? AND t.equ_ticker IS NOT NULL"
                f"{scope_sql} "
                "GROUP BY t.order_as_of_date, t.equ_ticker",
                params,
            )
            weights = {
                (str(d), str(t)): (int(n), float(a or 0.0), float(u or 0.0))
                for d, t, n, a, u in cursor.fetchall()
            }
            return weights, has_fx
        except Exception as exc:
            logger.debug("读取 ticker 成交金额失败（缺口影响面降级）: %s", exc)
            return {}, True
        finally:
            if conn is not None:
                conn.close()

    @staticmethod
    def _fill_bdib_table_exists(conn) -> bool:
        """fill_bdib 明细表是否存在于当前库（fx 回填可用性探测）。"""
        try:
            row = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='fill_bdib' LIMIT 1"
            ).fetchone()
        except Exception:
            return False
        return row is not None

    @staticmethod
    def _fbfx_cte() -> str:
        """fill_bdib 汇率回填 CTE（实现见 report_measure.fbfx_cte）。"""
        return rm.fbfx_cte()

    @staticmethod
    def _fbfx_join() -> str:
        """fill_bdib 汇率回填 LEFT JOIN 片段（主表别名 t）。"""
        return (
            " LEFT JOIN _fbfx"
            " ON _fbfx.OrderId = t.OrderId"
            " AND _fbfx.RouteId = t.RouteId"
            " AND _fbfx.fxf_oad = t.order_as_of_date"
        )

    def _load_tca_dates(
        self, start_date: str, end_date: str, scope: Optional[rm.ReportScope] = None,
    ) -> Optional[set[str]]:
        """tca_route_summary 中有汇总数据的日期集合（TCA 整日缺失检测用）。

        返回 None 表示日期集不可得（表不存在 / 查询失败），此时整日缺失检测降级
        为「未执行」并显式披露，不误报缺口。
        """
        condition, scope_params = rm.scope_condition(scope or rm.resolve_scope(None))
        conn = None
        try:
            conn = self._mgr.get_connection("fill_bdib", AccessTier.READ)
            if not self._table_exists(conn):
                return set()
            where = "order_as_of_date BETWEEN ? AND ?"
            params: list[Any] = [start_date, end_date]
            if condition:
                where = f"{where} AND {condition}"
                params.extend(scope_params)
            rows = conn.execute(
                f"SELECT DISTINCT order_as_of_date "
                f"FROM {Config.TCA_ROUTE_SUMMARY_TABLE} WHERE {where}",
                params,
            ).fetchall()
            return {str(r[0]) for r in rows}
        except Exception as exc:
            logger.warning("读取 TCA 汇总日期集失败（整日缺失检测降级）: %s", exc)
            return None
        finally:
            if conn is not None:
                conn.close()

    @staticmethod
    def _table_exists(conn) -> bool:
        """tca_route_summary 表/视图是否存在于当前库（实现见 _common.py）。"""
        return _common.tca_summary_exists(conn)

    @staticmethod
    def _sum_missing_weight(
        date_str: str,
        missing: set[str],
        ticker_weight: dict[tuple[str, str], tuple[int, float, float]],
    ) -> tuple[int, float, float]:
        """汇总某日缺口 ticker 的 (受影响 route 数, 成交金额, 未换算本币金额)。"""
        routes = 0
        notional = 0.0
        unconvertible = 0.0
        for ticker in missing:
            entry = ticker_weight.get((date_str, ticker))
            if entry:
                routes += entry[0]
                notional += entry[1]
                unconvertible += entry[2]
        return routes, notional, unconvertible

    def _empty_result(
        self, start_date: str, end_date: str,
        scope: Optional[rm.ReportScope] = None,
    ) -> dict[str, Any]:
        return {
            "start_date": start_date,
            "end_date": end_date,
            "status": "ok",
            "scope": (scope or rm.resolve_scope(None)).to_payload(),
            "retention_days": self._retention_days,
            "dates": [],
            "summary": self._build_summary([]),
            "gap_notional_fx_usd": True,
            "data_source_warning": "日期范围内 processed_fills 无成交记录",
        }


def get_health_safe(
    start_date: str,
    end_date: str,
    timeout: float = 25.0,
    health_service: Optional[Any] = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """带超时护栏的 BDIB 健康查询（供报告导出复用）。

    报告导出场景下，raw_bdib 全量扫描在历史大区间可能耗时极长甚至阻塞
    服务；此处在守护线程中运行，超时即降级（报告仍正常生成，仅缺 BDIB 缺口
    附录），绝不因附录拖垮导出响应。

    返回结构显式区分三态，不再用 None 表示降级（避免与「无缺口」在渲染上
    不可区分）：
      - 正常：health dict（含 ``status: "ok"`` 与 ``scope``）
      - 超时：``{"status": "skipped", "reason": "timeout"}``
      - 异常：``{"status": "skipped", "reason": "error"}``

    ``health_service`` 可注入（测试用）；默认 ``BdibHealthService``。
    ``**kwargs`` 透传给 ``get_health``（``today`` 对齐报告期、``scope`` 对齐报告作用域）。
    """
    if health_service is None:
        health_service = BdibHealthService

    holder: dict[str, Any] = {}

    def _run() -> None:
        try:
            # P2-5：并发闸限流，避免超时线程无限堆积（超时线程仍会跑完当前扫描）
            with _HEALTH_SCAN_SEMAPHORE:
                holder["result"] = health_service().get_health(
                    start_date, end_date, **kwargs
                )
        except Exception as exc:  # 异常同样降级
            logger.warning("BDIB 健康查询失败（跳过附录）: %s", exc)
            holder["result"] = None

    worker = threading.Thread(target=_run, daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        logger.warning(
            "BDIB 健康查询超时（%.0fs），导出附录降级跳过: %s~%s",
            timeout, start_date, end_date,
        )
        return {"status": "skipped", "reason": "timeout"}
    result = holder.get("result")
    if result is None:
        return {"status": "skipped", "reason": "error"}
    return result
