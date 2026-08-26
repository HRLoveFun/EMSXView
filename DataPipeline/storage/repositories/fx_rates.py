"""FX rates repository — read/write access to fx_rates table in fill_bdib.db.

fx_rates 表是全系统汇率的唯一真相源（fx-rate-persistence）：
- 管道 S5 拉取链查表优先（命中零 Bloomberg 配额消耗）
- 成功拉取立即落表（幂等 INSERT OR REPLACE，latest-wins）
- 拉取失败/额度暂停时按「目标日期上界」查最近已知汇率回退
  （跨进程重启仍有效，且强制 order_as_of_date <= 目标日期防未来汇率泄漏）

降级回退值/USD 兜底值由调用方（fx_fetcher）控制，本仓储不做业务判断。
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from DataPipeline.config import Config
from ._base import BaseRepository

logger = logging.getLogger(__name__)


def _norm_ccy(ccy_ticker: str) -> str:
    """规范化 ccy_ticker 键（大写 + 去首尾空白），保证查表/写表键一致。"""
    return (ccy_ticker or "").upper().strip()


class SqliteFxRatesRepository(BaseRepository):
    """fx_rates 表读写（fill_bdib.db，币种 × 交易日汇率唯一真相源）。"""

    def __init__(self, connection_manager=None):
        super().__init__(connection_manager, database="fill_bdib")

    # ── 读路径 ──────────────────────────────────────────────────────────────

    def get_rate(self, ccy_ticker: str, order_as_of_date: str) -> Optional[float]:
        """精确查询单一币种在指定交易日的汇率；未命中返回 None。"""
        conn = self._get_read_conn()
        try:
            row = conn.execute(
                f"SELECT fx_rate FROM {Config.FX_RATES_TABLE} "
                "WHERE ccy_ticker = ? AND order_as_of_date = ?",
                [_norm_ccy(ccy_ticker), order_as_of_date],
            ).fetchone()
            return float(row[0]) if row and row[0] is not None else None
        finally:
            conn.close()

    def get_rates_for_date(
        self, ccy_tickers: list[str], order_as_of_date: str,
    ) -> dict[str, float]:
        """批量查询多个币种在指定交易日的汇率（精确命中）。

        未命中的币种不出现在返回 dict 中；返回键保留调用方原始大小写，
        避免破坏上层 join / integrate 语义。
        """
        if not ccy_tickers:
            return {}
        norm = {_norm_ccy(c): c for c in ccy_tickers}
        conn = self._get_read_conn()
        try:
            placeholders = ", ".join(["?"] * len(norm))
            rows = conn.execute(
                f"SELECT ccy_ticker, fx_rate FROM {Config.FX_RATES_TABLE} "
                f"WHERE order_as_of_date = ? AND ccy_ticker IN ({placeholders})",
                [order_as_of_date, *norm.keys()],
            ).fetchall()
            return {norm[row[0]]: float(row[1]) for row in rows if row[1] is not None}
        finally:
            conn.close()

    def get_recent_rate(self, ccy_ticker: str, on_or_before: str) -> Optional[float]:
        """查询不晚于 on_or_before 的最近已知汇率（降级回退用）。

        强制日期上界，防止回填旧日期时泄漏「未来」汇率。
        """
        conn = self._get_read_conn()
        try:
            row = conn.execute(
                f"SELECT fx_rate FROM {Config.FX_RATES_TABLE} "
                "WHERE ccy_ticker = ? AND order_as_of_date <= ? "
                "ORDER BY order_as_of_date DESC LIMIT 1",
                [_norm_ccy(ccy_ticker), on_or_before],
            ).fetchone()
            return float(row[0]) if row and row[0] is not None else None
        finally:
            conn.close()

    # ── 写路径 ──────────────────────────────────────────────────────────────

    def upsert_rate(
        self,
        ccy_ticker: str,
        order_as_of_date: str,
        fx_rate: float,
        px_last: Optional[float] = None,
        source: str = "bloomberg",
    ) -> int:
        """写入单条汇率（幂等 INSERT OR REPLACE）。仅成功拉取值应写入。"""
        if fx_rate is None or fx_rate != fx_rate or fx_rate <= 0:
            return 0
        return self._upsert_rows([
            (
                _norm_ccy(ccy_ticker), order_as_of_date, float(fx_rate),
                None if px_last is None else float(px_last), source,
            ),
        ])

    def upsert_rates(self, df: pd.DataFrame) -> int:
        """批量写入汇率 DataFrame。

        必填列: ccy_ticker / order_as_of_date / fx_rate；
        可选列: px_last（缺省 NULL）、source（缺省 'bloomberg'）。
        fx_rate 为 NaN 或非正的行跳过（降级回退值绝不落表）。
        """
        if df is None or df.empty:
            return 0
        out = df.copy()
        if "px_last" not in out.columns:
            out["px_last"] = None
        if "source" not in out.columns:
            out["source"] = "bloomberg"
        out = out[out["fx_rate"].notna() & (out["fx_rate"] > 0)]
        if out.empty:
            return 0
        cols = ["ccy_ticker", "order_as_of_date", "fx_rate", "px_last", "source"]
        rows = [self._to_row(r) for r in out[cols].itertuples(index=False, name=None)]
        return self._upsert_rows(rows)

    @staticmethod
    def _to_row(r: tuple) -> tuple:
        """单行 DataFrame 记录 → SQL 参数元组（NaN/None → NULL）。"""
        px = None if (r[3] is None or pd.isna(r[3])) else float(r[3])
        src = "bloomberg" if r[4] is None or pd.isna(r[4]) else str(r[4])
        return (_norm_ccy(str(r[0])), str(r[1]), float(r[2]), px, src)

    def _upsert_rows(self, rows: list[tuple]) -> int:
        """批量 INSERT OR REPLACE（latest-wins，与其他表幂等语义一致）。"""
        if not rows:
            return 0
        sql = (
            f"INSERT OR REPLACE INTO {Config.FX_RATES_TABLE} "
            "(ccy_ticker, order_as_of_date, fx_rate, px_last, source) "
            "VALUES (?, ?, ?, ?, ?)"
        )
        conn = self._get_write_conn()
        try:
            conn.executemany(sql, rows)
            conn.commit()
            logger.debug("Upserted %d fx_rates rows", len(rows))
            return len(rows)
        finally:
            conn.close()
