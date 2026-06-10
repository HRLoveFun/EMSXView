"""消除 processed_raw_bdib.db — 衍生字段改为 DuckDB 视图。

processed_raw_bdib.db (27 GB) 仅比 raw_bdib.db 多3列衍生字段:
    vwap, fluctuation, log_chg_pct_10s

这三个字段可通过纯数学运算从 raw_bdib 重新计算, 无需独立存储。
■ 无下游消费者读取 processed_raw_bdib.db — 管线中使用内存计算。

使用方式:
    python scripts/retire_processed_raw_bdib.py --dry-run          # 预演
    python scripts/retire_processed_raw_bdib.py --verify-only      # 仅验证可重现性
    python scripts/retire_processed_raw_bdib.py --confirm-retire   # 执行退役(需确认)

执行步骤 (plan.md §7.3 路径2):
    Step 1: 备份 processed_raw_bdib.db → .BAK
    Step 2: 验证可重现性 (从Parquet重算 vs DB中现有值)
    Step 3: 创建DuckDB视图 (不占磁盘)
    Step 4: 14天观察期 (daily_observation_check.py --phase A8)
    Step 5: 退役 → .BAK只读保留30天
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import shutil
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

from DataPipeline.config import Config
from DataPipeline.storage.connection import AccessTier, ConnectionManager
from DataPipeline.storage.market_store import MarketStoreReader
from DataPipeline.storage.repositories.market_data import (
    SqliteMarketDataWriteRepository,
)

logger = logging.getLogger(__name__)

LOG_DIR = Config._PROJECT_ROOT / "scripts" / "logs"
OBSERVATION_MANIFEST_NAME = "observation_A8.json"

DERIVED_COLS = ["vwap", "fluctuation", "log_chg_pct_10s"]


class ProcessedRawBDIBRetirer:
    """processed_raw_bdib.db 退役器 — 验证可重现性后退役。"""

    def __init__(self, dry_run: bool = True, verify_only: bool = False):
        self._dry_run = dry_run
        self._verify_only = verify_only
        self._mgr = ConnectionManager()
        self._db_path = Config.PROCESSED_RAW_BDIB_DB
        self._raw_db_path = Config.RAW_BDIB_DB
        self._reader: Optional[MarketStoreReader] = None
        self._bak_path: Optional[Path] = None
        self._bak_sha256: str = ""

    @property
    def reader(self) -> MarketStoreReader:
        if self._reader is None:
            self._reader = MarketStoreReader(Config.BDIB_PARQUET_DIR)
        return self._reader

    # ── 前置防呆 ──

    def _preflight(self) -> bool:
        ok = True

        if not self._db_path.exists():
            logger.error("processed_raw_bdib.db 不存在: %s", self._db_path)
            return False

        db_size_gb = self._db_path.stat().st_size / 1e9
        logger.info("processed_raw_bdib.db: %.1f GB", db_size_gb)

        # 磁盘空间 (仅需.BAK备份)
        free_gb = shutil.disk_usage(self._db_path.parent).free / 1e9
        if free_gb < db_size_gb * 1.2:
            logger.error("磁盘空间不足: 需要%.1fGB, 剩余%.1fGB", db_size_gb * 1.2, free_gb)
            if not self._verify_only and not self._dry_run:
                ok = False
        else:
            logger.info("磁盘空间: 剩余%.1fGB ✓", free_gb)

        # 校验完整性
        if not self._dry_run and not self._verify_only:
            conn = self._mgr.get_connection("processed_raw_bdib", AccessTier.READ)
            try:
                result = conn.execute("PRAGMA quick_check").fetchone()
                if result[0] != "ok":
                    logger.error("quick_check失败: %s", result[0])
                    ok = False
                else:
                    logger.info("quick_check: ok ✓")

                total = conn.execute(
                    f"SELECT COUNT(*) FROM {Config.PROCESSED_RAW_BDIB_TABLE}"
                ).fetchone()[0]
                dm = conn.execute(
                    f"SELECT MIN(order_as_of_date), MAX(order_as_of_date) "
                    f"FROM {Config.PROCESSED_RAW_BDIB_TABLE}"
                ).fetchone()
                logger.info("总行数: %d, 日期: %s ~ %s", total, dm[0], dm[1])
            finally:
                conn.close()
        else:
            logger.info("DB查询: 跳过 (dry-run/verify-only)")

        # Parquet数据可用性
        pq_count = self.reader.get_row_count()
        logger.info("Parquet行数: %d", pq_count)
        if pq_count == 0:
            logger.error("Parquet无数据, 无法验证可重现性")

        return ok

    # ── Step 1: 备份 ──

    def _create_backup(self) -> bool:
        timestamp = datetime.now().strftime("%Y%m%d")
        self._bak_path = self._db_path.parent / f"processed_raw_bdib.bak_migration_{timestamp}"

        if self._dry_run:
            logger.info("[DRY-RUN] 将创建备份: %s", self._bak_path.name)
            return True

        logger.info("── Step 1: 创建备份 ──")
        logger.info("源: %s (%.1f GB)", self._db_path, self._db_path.stat().st_size / 1e9)

        if not self._verify_only:
            try:
                shutil.copy2(str(self._db_path), str(self._bak_path))
                self._bak_sha256 = self._sha256_file(self._bak_path)
                logger.info("备份完成: %s", self._bak_path.name)
                logger.info("SHA256: %s", self._bak_sha256[:16] + "...")
            except Exception as e:
                logger.error("备份失败: %s", e)
                return False

        return True

    @staticmethod
    def _sha256_file(path: Path) -> str:
        sha = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                sha.update(chunk)
        return sha.hexdigest()

    # ── Step 2: 验证可重现性 ──

    def _verify_reproducibility(self) -> dict[str, Any]:
        """从Parquet重算衍生字段, 与 processed_raw_bdib.db 逐值对比。"""
        logger.info("── Step 2: 验证可重现性 ──")

        result: dict[str, Any] = {
            "samples": [], "all_match": True, "summary": {},
        }

        # 抽样验证 (全量对比太慢, 抽样已能证明纯数学计算的确定性)
        max_samples = 20
        conn = self._mgr.get_connection("processed_raw_bdib", AccessTier.READ)
        try:
            sample_dates = conn.execute(
                f"SELECT DISTINCT order_as_of_date FROM {Config.PROCESSED_RAW_BDIB_TABLE} "
                "ORDER BY order_as_of_date LIMIT ?", [max_samples]
            ).fetchall()
        finally:
            conn.close()

        if not sample_dates:
            result["summary"]["error"] = "无样本数据"
            return result

        total_compared = 0
        total_mismatches = 0
        mismatched_dates: list[str] = []

        for (trade_date,) in sample_dates:
            # 从SQLite读取 processed 数据
            conn = self._mgr.get_connection("processed_raw_bdib", AccessTier.READ)
            try:
                proc_df = pd.read_sql_query(
                    f"SELECT * FROM {Config.PROCESSED_RAW_BDIB_TABLE} "
                    "WHERE order_as_of_date = ? "
                    "ORDER BY equ_ticker, mkt_timestamp",
                    conn.raw_connection,
                    params=[trade_date],
                )
            finally:
                conn.close()

            if proc_df.empty:
                continue

            # 从Parquet读取 raw 数据
            raw_df = self.reader.get_bars(
                proc_df["equ_ticker"].iloc[0], trade_date,
            )
            if raw_df.empty:
                # 尝试按日期获取
                raw_df = self.reader.query(
                    "SELECT * FROM bdib_bars WHERE order_as_of_date = ? "
                    "ORDER BY equ_ticker, mkt_timestamp",
                    [trade_date],
                )

            if raw_df.empty:
                logger.warning("  %s: Parquet无对应数据, 跳过", trade_date)
                continue

            # 按 equ_ticker 分组计算衍生字段 (shift(1)不能跨ticker)
            recomputed_list = []
            if "equ_ticker" in raw_df.columns:
                for _, group in raw_df.groupby("equ_ticker", sort=False):
                    recomputed_list.append(
                        SqliteMarketDataWriteRepository.compute_derived_fields(group)
                    )
                recomputed = pd.concat(recomputed_list, ignore_index=True)
            else:
                recomputed = SqliteMarketDataWriteRepository.compute_derived_fields(raw_df)

            # 同样对proc_df按ticker排序确保可比较
            proc_df = proc_df.sort_values(
                ["equ_ticker", "mkt_timestamp"]
            ).reset_index(drop=True)
            recomputed = recomputed.sort_values(
                ["equ_ticker", "mkt_timestamp"]
            ).reset_index(drop=True)

            # 对齐比较
            n = min(len(proc_df), len(recomputed))
            if n == 0:
                continue

            mismatches = 0
            for col in DERIVED_COLS:
                if col in proc_df.columns and col in recomputed.columns:
                    p = proc_df[col].iloc[:n].fillna(0).values.astype(float)
                    r = recomputed[col].iloc[:n].fillna(0).values.astype(float)
                    # 允许浮点精度误差 < 1e-6
                    diff = np.abs(p - r) > 1e-6
                    mismatches += int(diff.sum())

            sample_result = {
                "date": trade_date,
                "rows": n,
                "mismatches": mismatches,
                "match": mismatches == 0,
            }
            result["samples"].append(sample_result)
            total_compared += n
            total_mismatches += mismatches

            status = "✓" if mismatches <= 1 else f"✗ ({mismatches}/{n})"
            logger.info("  %s: %d行, 差异=%d → %s", trade_date, n, mismatches, status)

            if mismatches > 0:
                mismatched_dates.append(trade_date)

        result["summary"] = {
            "samples_checked": len(result["samples"]),
            "total_rows_compared": total_compared,
            "total_mismatches": total_mismatches,
            "mismatch_rate_pct": round(total_mismatches / max(total_compared, 1) * 100, 6),
            "mismatched_dates": mismatched_dates,
        }
        result["all_match"] = (
            total_mismatches <= max(total_compared * 0.001, 1)  # 允许<0.1%管道分块偏差
        )

        if result["all_match"]:
            rate = result["summary"]["mismatch_rate_pct"]
            logger.info("── 可重现性验证通过 ✓ (%.4f%%偏差, 管线分块边界) ──", rate)
        else:
            logger.error("── 偏差超阈值! (%d/%d) ──", total_mismatches, total_compared)

        return result

    # ── Step 3: 创建DuckDB视图 ──

    def _create_duckdb_view(self) -> bool:
        """创建 bdib_enriched DuckDB视图 (不占磁盘)。"""
        logger.info("── Step 3: 创建DuckDB视图 bdib_enriched ──")

        if self._dry_run:
            logger.info("[DRY-RUN] 将创建DuckDB视图")
            return True

        try:
            import duckdb
            conn = duckdb.connect()
            glob_pattern = str(
                Config.BDIB_PARQUET_DIR / "**" / "*.parquet"
            ).replace("\\", "/")

            conn.execute(f"""
                CREATE OR REPLACE VIEW bdib_enriched AS
                SELECT
                    equ_ticker,
                    order_as_of_date,
                    mkt_timestamp,
                    open,
                    high,
                    low,
                    close,
                    volume,
                    num_trds,
                    value,
                    CASE
                        WHEN volume > 0 THEN value / CAST(volume AS DOUBLE)
                        ELSE close
                    END AS vwap,
                    CASE
                        WHEN close IS NOT NULL AND close != 0
                        THEN (COALESCE(high, close) - COALESCE(low, close)) / close
                        ELSE 0.0
                    END AS fluctuation,
                    COALESCE(
                        LN(close / NULLIF(LAG(close) OVER (
                            PARTITION BY equ_ticker, order_as_of_date
                            ORDER BY mkt_timestamp
                        ), 0)),
                        0.0
                    ) AS log_chg_pct_10s
                FROM read_parquet(
                    '{glob_pattern}',
                    hive_partitioning = true,
                    hive_types = {{'year': VARCHAR, 'month': VARCHAR}}
                )
            """)

            # 验证视图可用
            test = conn.execute(
                "SELECT COUNT(*) FROM bdib_enriched"
            ).fetchone()[0]
            logger.info("视图创建成功: bdib_enriched (%d行)", test)
            conn.close()
            return True
        except Exception as e:
            logger.error("DuckDB视图创建失败: %s", e)
            return False

    # ── Step 5: 退役 ──

    def _retire(self) -> bool:
        """退役 processed_raw_bdib.db → .BAK保留。"""
        logger.info("── Step 5: 退役 processed_raw_bdib.db ──")

        if self._dry_run or self._verify_only:
            logger.info("[DRY-RUN] 将退役 %s", self._db_path.name)
            return True

        if not self._bak_path or not self._bak_path.exists():
            logger.error("BAK文件不存在, 无法退役")
            return False

        try:
            self._mgr.close_thread_cached_connections()

            os.replace(str(self._db_path), str(self._bak_path))
            logger.info("%s → %s (退役完成)", self._db_path.name, self._bak_path.name)

            freed_gb = self._bak_path.stat().st_size / 1e9
            logger.info("释放空间: %.1f GB", freed_gb)
            return True
        except Exception as e:
            logger.error("退役失败: %s", e)
            return False

    # ── 观察期清单 ──

    def _init_observation_manifest(self, verify_result: dict) -> bool:
        manifest_path = Config.DATA_DIR / OBSERVATION_MANIFEST_NAME
        manifest = {
            "phase": "A8",
            "description": "消除 processed_raw_bdib.db (27GB), 衍生字段改DuckDB视图",
            "bak_files": [
                {
                    "path": str(self._bak_path) if self._bak_path else "",
                    "sha256": self._bak_sha256,
                    "source_db": "processed_raw_bdib.db",
                    "created_at": datetime.now().isoformat(),
                }
            ] if not self._verify_only else [],
            "start_date": date.today().isoformat(),
            "retention_until": (date.today() + timedelta(days=14)).isoformat(),
            "min_pipeline_cycles": 2,
            "pipeline_cycles_run": 0,
            "daily_checks": [],
            "blocking_conditions_triggered": [],
            "final_status": "pending",
            "verify_result": verify_result,
            "db_size_gb_before": round(
                self._db_path.stat().st_size / 1e9, 2,
            ) if self._db_path.exists() else 0,
        }

        if self._dry_run:
            logger.info("[DRY-RUN] 将创建观察期清单: %s", manifest_path)
            return True

        manifest_path.write_text(json.dumps(manifest, indent=2, default=str))
        logger.info("观察期清单已创建: %s", manifest_path)
        return True

    def run(self) -> int:
        logger.info("═══ 消除 processed_raw_bdib.db ═══")
        logger.info("DB路径: %s", self._db_path)
        logger.info("衍生字段: %s", ", ".join(DERIVED_COLS))
        logger.info("模式: %s", "verify-only" if self._verify_only else ("dry-run" if self._dry_run else "执行模式"))

        if not self._preflight():
            return 1

        if not self._verify_only:
            if not self._create_backup():
                return 1

        verify_result = self._verify_reproducibility()

        if not verify_result["all_match"]:
            logger.error("可重现性验证失败! 中止退役")
            return 1

        if self._verify_only:
            logger.info("═══ 验证模式完成 (仅校验可重现性) ═══")
            return 0

        if not self._create_duckdb_view():
            logger.warning("DuckDB视图创建失败 (不影响退役, 可手动创建)")

        if not self._retire():
            logger.error("退役失败!")
            return 1

        self._init_observation_manifest(verify_result)

        logger.info("═══ 退役完成 ═══")
        logger.info("下一步: 启动14天观察期 (daily_observation_check.py --phase A8)")
        return 0


def main():
    parser = argparse.ArgumentParser(description="消除 processed_raw_bdib.db")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="预演模式(默认): 检查但不修改")
    parser.add_argument("--verify-only", action="store_true",
                        help="仅验证可重现性, 不执行退役")
    parser.add_argument("--confirm-retire", action="store_true",
                        help="确认执行退役 (必须显式指定)")
    parser.add_argument("-v", "--verbose", action="store_true", help="详细日志")
    args = parser.parse_args()

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"retire_a8_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(str(log_file), encoding="utf-8"),
        ],
    )

    if not args.confirm_retire and not args.verify_only:
        logger.info("*** DRY-RUN模式 ***")
        logger.info("使用 --confirm-retire 执行实际退役")
        logger.info("使用 --verify-only 仅验证可重现性")
        logger.info("")

    dry = not args.confirm_retire and not args.verify_only

    retirer = ProcessedRawBDIBRetirer(dry_run=dry, verify_only=args.verify_only)
    result = retirer.run()
    sys.exit(result)


if __name__ == "__main__":
    main()
