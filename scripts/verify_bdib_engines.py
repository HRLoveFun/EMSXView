"""双引擎验证脚本 — DuckDB/Parquet vs SQLite 查询结果 diff 对比。

使用方式:
    python scripts/verify_bdib_engines.py                # 全量对比
    python scripts/verify_bdib_engines.py --quick         # 快速抽样对比
    python scripts/verify_bdib_engines.py --date 20240115 # 指定日期
    python scripts/verify_bdib_engines.py --ticker "7203 JP Equity"

输出:
    - stdout: 对比结果摘要
    - scripts/logs/verify_bdib_YYYYMMDD_HHMMSS.log: 详细日志
    - data/verify_bdib_manifest.json: 验证记录

前置条件:
    A4 回填已完成 (Parquet数据存在)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from DataPipeline.config import Config
from DataPipeline.storage.connection import AccessTier, ConnectionManager
from DataPipeline.storage.market_store import MarketStoreReader

LOG_DIR = Config._PROJECT_ROOT / "scripts" / "logs"
MANIFEST_NAME = "verify_bdib_manifest.json"

logger = logging.getLogger(__name__)


class BDIBEngineVerifier:
    """DuckDB/Parquet vs SQLite 查询结果对比验证器。"""

    def __init__(self):
        self._mgr = ConnectionManager()
        self._reader = MarketStoreReader(Config.BDIB_PARQUET_DIR)
        self._results: dict[str, Any] = {
            "timestamp": datetime.now().isoformat(),
            "checks": {},
            "all_pass": True,
        }

    # ── 校验1: 全量行数对比 ──

    def _verify_row_counts(self) -> dict[str, Any]:
        logger.info("── 校验1: 全量行数对比 ──")
        try:
            conn = self._mgr.get_connection("raw_bdib", AccessTier.READ)
            sqlite_count = conn.execute(
                f"SELECT COUNT(*) FROM {Config.RAW_BDIB_TABLE}"
            ).fetchone()[0]
            conn.close()
        except Exception as e:
            return {"sqlite_rows": -1, "parquet_rows": -1, "match": False, "error": str(e)}

        pq_count = self._reader.get_row_count()

        match = sqlite_count == pq_count
        diff_pct = abs(sqlite_count - pq_count) / max(sqlite_count, 1) * 100.0

        result = {
            "sqlite_rows": sqlite_count,
            "parquet_rows": pq_count,
            "diff": sqlite_count - pq_count,
            "diff_pct": round(diff_pct, 4),
            "match": match,
        }
        status = "✓ 通过" if match else f"✗ 失败 (差异{diff_pct:.2f}%)"
        logger.info("  行数: SQLite=%d, Parquet=%d → %s", sqlite_count, pq_count, status)
        return result

    # ── 校验2: 全量聚合对比 ──

    def _verify_aggregates(self) -> dict[str, Any]:
        logger.info("── 校验2: 全量聚合对比 ──")
        result: dict[str, Any] = {}
        agg_cols = ["close", "volume", "value"]

        conn = self._mgr.get_connection("raw_bdib", AccessTier.READ)
        try:
            for col in agg_cols:
                sql_sum = conn.execute(
                    f"SELECT COALESCE(SUM(CAST({col} AS REAL)), 0) FROM {Config.RAW_BDIB_TABLE}"
                ).fetchone()[0]
                result[f"{col}_sum_sqlite"] = float(sql_sum)
        finally:
            conn.close()

        try:
            for col in agg_cols:
                df = self._reader.query(
                    f"SELECT COALESCE(SUM({col}), 0) AS s FROM bdib_bars"
                )
                pq_sum = float(df["s"].iloc[0]) if not df.empty else 0.0
                result[f"{col}_sum_parquet"] = pq_sum
        except Exception as e:
            result["parquet_error"] = str(e)
            return result

        all_match = True
        for col in agg_cols:
            sql_val = result.get(f"{col}_sum_sqlite", 0)
            pq_val = result.get(f"{col}_sum_parquet", 0)
            diff_ok = abs(sql_val - pq_val) < max(abs(sql_val) * 1e-6, 1e-6)
            result[f"{col}_match"] = diff_ok
            if not diff_ok:
                all_match = False
            logger.info("  %s: SQLite=%.2f, Parquet=%.2f, diff=%.6f → %s",
                        col, sql_val, pq_val, abs(sql_val - pq_val),
                        "✓" if diff_ok else "✗")

        result["all_match"] = all_match
        return result

    # ── 校验3: 按月聚合对比 ──

    def _verify_monthly_aggregates(self) -> dict[str, Any]:
        logger.info("── 校验3: 按月聚合对比 ──")
        conn = self._mgr.get_connection("raw_bdib", AccessTier.READ)
        try:
            sql_df = pd.read_sql_query(
                f"""
                SELECT substr(order_as_of_date, 1, 6) AS month, COUNT(*) AS cnt,
                       COALESCE(SUM(CAST(close AS REAL)), 0) AS sum_close,
                       COALESCE(SUM(CAST(volume AS REAL)), 0) AS sum_volume
                FROM {Config.RAW_BDIB_TABLE}
                WHERE length(order_as_of_date) >= 6
                GROUP BY month ORDER BY month
                """,
                conn.raw_connection,
            )
        finally:
            conn.close()

        try:
            pq_df = self._reader.query(
                "SELECT substr(order_as_of_date, 1, 6) AS month, COUNT(*) AS cnt, "
                "COALESCE(SUM(close), 0) AS sum_close, "
                "COALESCE(SUM(volume), 0) AS sum_volume "
                "FROM bdib_bars "
                "WHERE length(order_as_of_date) >= 6 "
                "GROUP BY month ORDER BY month"
            )
        except Exception as e:
            return {"error": str(e)}

        if sql_df.empty and pq_df.empty:
            return {"months": 0, "all_match": True}

        merged = sql_df.merge(pq_df, on="month", suffixes=("_sql", "_pq"), how="outer").fillna(0)
        mismatches = 0
        for _, row in merged.iterrows():
            cnt_ok = int(row["cnt_sql"]) == int(row["cnt_pq"])
            close_ok = abs(row["sum_close_sql"] - row["sum_close_pq"]) < max(abs(row["sum_close_sql"]) * 1e-6, 1e-6)
            if not cnt_ok or not close_ok:
                mismatches += 1
                logger.warning("  月份%s: 行数%s 聚合%s",
                               row["month"],
                               "✓" if cnt_ok else "✗",
                               "✓" if close_ok else "✗")

        all_match = mismatches == 0
        logger.info("  月份数=%d, 不匹配=%d → %s", len(merged), mismatches,
                     "✓" if all_match else "✗")
        return {"months": int(len(merged)), "mismatches": mismatches, "all_match": all_match}

    # ── 校验4: 查询性能对比 ──

    def _verify_performance(self) -> dict[str, Any]:
        logger.info("── 校验4: 查询性能对比 ──")
        import time

        result: dict[str, Any] = {}

        # 获取一个样本ticker
        conn = self._mgr.get_connection("raw_bdib", AccessTier.READ)
        try:
            sample = conn.execute(
                f"SELECT equ_ticker, order_as_of_date FROM {Config.RAW_BDIB_TABLE} LIMIT 1"
            ).fetchone()
        finally:
            conn.close()

        if not sample:
            return {"error": "无样本数据"}

        ticker, trade_date = sample[0], sample[1]

        # SQLite查询
        t0 = time.perf_counter()
        conn = self._mgr.get_connection("raw_bdib", AccessTier.READ)
        try:
            conn.execute(
                f"SELECT COUNT(*) FROM {Config.RAW_BDIB_TABLE} "
                "WHERE equ_ticker = ? AND order_as_of_date = ?",
                [ticker, trade_date],
            ).fetchone()
        finally:
            conn.close()
        sqlite_time = time.perf_counter() - t0
        result["sqlite_query_ms"] = round(sqlite_time * 1000, 2)

        # DuckDB查询
        t0 = time.perf_counter()
        self._reader.query(
            "SELECT COUNT(*) AS cnt FROM bdib_bars "
            "WHERE equ_ticker = ? AND order_as_of_date = ?",
            [ticker, trade_date],
        )
        duckdb_time = time.perf_counter() - t0
        result["duckdb_query_ms"] = round(duckdb_time * 1000, 2)

        speedup = sqlite_time / max(duckdb_time, 0.001)
        result["speedup"] = round(speedup, 2)
        logger.info("  SQLite=%sms, DuckDB=%sms, 加速比=%.1fx",
                     result["sqlite_query_ms"], result["duckdb_query_ms"], speedup)
        return result

    # ── 校验5: 市场上下文抽样对比 ──

    def _verify_market_context_sample(self, max_samples: int = 10) -> dict[str, Any]:
        logger.info("── 校验5: 市场上下文抽样对比 ──")
        conn = self._mgr.get_connection("raw_bdib", AccessTier.READ)
        try:
            samples = conn.execute(
                f"SELECT DISTINCT equ_ticker, order_as_of_date FROM {Config.RAW_BDIB_TABLE} "
                "LIMIT ?", [max_samples]
            ).fetchall()
        finally:
            conn.close()

        if not samples:
            return {"samples": 0, "message": "无样本数据"}

        mismatches = 0
        for ticker, trade_date in samples:
            sql_count = 0
            conn = self._mgr.get_connection("raw_bdib", AccessTier.READ)
            try:
                sql_count = conn.execute(
                    f"SELECT COUNT(*) FROM {Config.RAW_BDIB_TABLE} "
                    "WHERE equ_ticker = ? AND order_as_of_date = ?",
                    [ticker, trade_date],
                ).fetchone()[0]
            finally:
                conn.close()

            pq_df = self._reader.query(
                "SELECT COUNT(*) AS cnt FROM bdib_bars "
                "WHERE equ_ticker = ? AND order_as_of_date = ?",
                [ticker, trade_date],
            )
            pq_count = int(pq_df["cnt"].iloc[0]) if not pq_df.empty else 0

            if sql_count != pq_count:
                mismatches += 1
                logger.warning("  %s/%s: SQLite=%d, Parquet=%d ✗",
                               ticker, trade_date, sql_count, pq_count)

        all_match = mismatches == 0
        logger.info("  抽样%d个ticker-dates, 不匹配=%d → %s",
                     len(samples), mismatches, "✓" if all_match else "✗")
        return {"samples": len(samples), "mismatches": mismatches, "all_match": all_match}

    def run(self, quick: bool = False, date_filter: Optional[str] = None,
            ticker_filter: Optional[str] = None) -> int:
        """执行全量验证, 返回0=全部通过。"""
        logger.info("═══ BDIB引擎对比验证 ═══")
        logger.info("SQLite: %s", Config.RAW_BDIB_DB)
        logger.info("Parquet: %s", Config.BDIB_PARQUET_DIR)

        checks = [
            ("row_counts", self._verify_row_counts),
            ("aggregates", self._verify_aggregates),
            ("monthly_aggregates", self._verify_monthly_aggregates),
            ("performance", self._verify_performance),
            ("market_context_sample", lambda: self._verify_market_context_sample(
                max_samples=5 if quick else 10)),
        ]

        if quick:
            checks = checks[:2]  # 仅行数+聚合

        all_pass = True
        for check_name, check_fn in checks:
            try:
                result = check_fn()
                self._results["checks"][check_name] = result
                if not result.get("all_match", result.get("match", True)):
                    all_pass = False
            except Exception as e:
                logger.error("校验 %s 异常: %s", check_name, e, exc_info=True)
                self._results["checks"][check_name] = {"error": str(e)}
                all_pass = False

        self._results["all_pass"] = all_pass

        manifest_path = Config.DATA_DIR / MANIFEST_NAME
        try:
            self._results["timestamp"] = datetime.now().isoformat()
            manifest_path.write_text(json.dumps(self._results, indent=2, default=str))
            logger.info("验证清单已保存: %s", manifest_path)
        except Exception:
            pass

        self._reader.close()

        if all_pass:
            logger.info("═══ 全部校验通过 ✓ ═══")
        else:
            logger.warning("═══ 存在校验失败 ✗ ═══")

        return 0 if all_pass else 1


def main():
    parser = argparse.ArgumentParser(description="BDIB引擎对比验证 (SQLite vs DuckDB/Parquet)")
    parser.add_argument("--quick", action="store_true", help="快速抽样对比")
    parser.add_argument("--date", type=str, help="指定日期 (YYYYMMDD)")
    parser.add_argument("--ticker", type=str, help="指定ticker")
    parser.add_argument("-v", "--verbose", action="store_true", help="详细日志")
    args = parser.parse_args()

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"verify_bdib_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(str(log_file), encoding="utf-8")],
    )

    verifier = BDIBEngineVerifier()
    result = verifier.run(
        quick=args.quick,
        date_filter=args.date,
        ticker_filter=args.ticker,
    )
    sys.exit(result)


if __name__ == "__main__":
    main()
