"""BDIB 数据健康服务 — SQLite 热数据 + Parquet 分区双源扫描。

按交易日对比"processed_fills 中有成交的 ticker 集合"与
"raw_bdib 双源中有行情的 ticker 集合"，输出覆盖率与健康分级：
    ok            — 全部成交 ticker 均有 BDIB 行情
    partial       — 部分 ticker 缺失，且日期仍在 Bloomberg 保留窗口内（可回补）
    missing       — 当日完全无 BDIB 数据，且仍在保留窗口内（可回补）
    unrecoverable — 存在缺口且日期已超出保留窗口（BDIB_API_RETENTION_DAYS，无法回补）

查询全部使用聚合 SQL（GROUP BY 一次完成），避免按日循环的 N+1。
"""

from __future__ import annotations

import enum
import logging
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from DataPipeline.config import Config
from DataPipeline.storage.connection import AccessTier, ConnectionManager
from DataPipeline.storage.market_store import MarketStoreReader

logger = logging.getLogger(__name__)

#: 缺口明细中 missing_tickers 列表的最大返回长度（防止单日数百 ticker 撑爆响应）
MAX_MISSING_TICKERS_DETAIL = 50


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
    ) -> dict[str, Any]:
        """扫描 [start_date, end_date] 内有成交交易日的 BDIB 健康度。

        Returns:
            {"start_date", "end_date", "retention_days", "dates": [...],
             "summary": {各状态日数、最近缺口日期、缺口 ticker 总数}}
        """
        today = today or date.today()
        fill_map = self._load_fill_tickers(start_date, end_date)
        if not fill_map:
            return self._empty_result(start_date, end_date)

        sql_rows, sql_tickers = self._scan_sqlite(start_date, end_date)
        pq_rows, pq_tickers = self._scan_parquet(start_date, end_date)

        dates = [
            self._build_date_entry(
                d, fill_map[d], sql_rows.get(d, 0), pq_rows.get(d, 0),
                sql_tickers.get(d, set()) | pq_tickers.get(d, set()), today,
            )
            for d in sorted(fill_map)
        ]
        return {
            "start_date": start_date,
            "end_date": end_date,
            "retention_days": self._retention_days,
            "dates": dates,
            "summary": self._build_summary(dates),
        }

    # ── 数据加载 ─────────────────────────────────────────────────────────

    def _load_fill_tickers(
        self, start_date: str, end_date: str,
    ) -> dict[str, set[str]]:
        """processed_fills 中有成交的 (日期 → ticker 集合)。

        仅统计 BDIB_EXCHANGE 白名单内交易所的 ticker —— 白名单外交易所
        （CN/BZ/MM/PW/DC/IT/NZ/MUMBAI 等，2026-07-16 起移出分析范围）的
        ticker 本就不拉取 BDIB 行情，将其计入缺口会虚高"BDIB 缺口"、拉低
        指标覆盖率的观感（实际为 out-of-scope，非数据缺失）。

        注：白名单过滤依赖 processed_fills 的 Exchange 列。部分测试/旧表无该列，
        此时退化为"全部成交 ticker"（与历史行为一致），避免硬失败。
        """
        whitelist = tuple(str(e).strip().upper() for e in Config.BDIB_EXCHANGE if str(e).strip())
        conn = None
        try:
            conn = self._mgr.get_connection("processed_fills", AccessTier.READ)
            has_exchange = self._table_has_column(conn, Config.PROCESSED_FILLS_TABLE, "Exchange")
            if has_exchange and whitelist:
                placeholders = ", ".join(["?"] * len(whitelist))
                cursor = conn.execute(
                    f"SELECT DISTINCT order_as_of_date, equ_ticker "
                    f"FROM {Config.PROCESSED_FILLS_TABLE} "
                    f"WHERE order_as_of_date BETWEEN ? AND ? AND equ_ticker IS NOT NULL "
                    f"AND Exchange IN ({placeholders})",
                    [start_date, end_date, *whitelist],
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
        """判断 processed_fills 等表是否含指定列（幂等兼容旧 schema / 测试 fixture）。"""
        try:
            rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        except Exception:
            return False
        return any(str(r[1]).lower() == column.lower() for r in rows)

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
    ) -> dict[str, Any]:
        """单日健康记录：覆盖率 + 分级 + 保留窗口信息。"""
        missing = sorted(fill_tickers - bdib_tickers)
        coverage = (len(fill_tickers) - len(missing)) / len(fill_tickers) * 100.0
        days_old = (today - datetime.strptime(date_str, Config.DATE_FORMAT).date()).days
        retention_left = self._retention_days - days_old
        return {
            "date": date_str,
            "fill_tickers": len(fill_tickers),
            "bdib_tickers": len(fill_tickers) - len(missing),
            "coverage_pct": round(coverage, 2),
            "missing_ticker_count": len(missing),
            "missing_tickers": missing[:MAX_MISSING_TICKERS_DETAIL],
            "sqlite_rows": sqlite_rows,
            "parquet_rows": parquet_rows,
            "status": self._classify(coverage, retention_left).value,
            "retention_days_left": retention_left,
        }

    @staticmethod
    def _classify(coverage_pct: float, retention_left: int) -> BdibHealthStatus:
        """四级分级：ok / partial / missing / unrecoverable。"""
        if coverage_pct >= 100.0:
            return BdibHealthStatus.OK
        if retention_left < 0:
            return BdibHealthStatus.UNRECOVERABLE
        if coverage_pct <= 0.0:
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

    def _empty_result(self, start_date: str, end_date: str) -> dict[str, Any]:
        return {
            "start_date": start_date,
            "end_date": end_date,
            "retention_days": self._retention_days,
            "dates": [],
            "summary": self._build_summary([]),
            "data_source_warning": "日期范围内 processed_fills 无成交记录",
        }


def get_health_safe(
    start_date: str,
    end_date: str,
    timeout: float = 25.0,
    health_service: Optional[Any] = None,
    **kwargs: Any,
) -> Optional[dict[str, Any]]:
    """带超时护栏的 BDIB 健康查询（供报告导出复用）。

    报告导出场景下，raw_bdib 全量扫描在历史大区间可能耗时极长甚至阻塞
    服务；此处在守护线程中运行，超时即降级为 None（报告仍正常生成，仅缺
    BDIB 缺口附录），绝不因附录拖垮导出响应。

    ``health_service`` 可注入（测试用）；默认 ``BdibHealthService``。
    """
    if health_service is None:
        health_service = BdibHealthService

    holder: dict[str, Any] = {}

    def _run() -> None:
        try:
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
        return None
    return holder.get("result")
