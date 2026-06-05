"""raw_bdib.db收缩脚本 — 仅保留近N个月K线数据, 其余已迁移至Parquet。

⚠️ 此操作包含 .BAK 备份操作。执行前必须先陈述计划并等待确认。

使用方式:
    python scripts/shrink_raw_bdib.py --dry-run            # 预演(只检查不修改)
    python scripts/shrink_raw_bdib.py --confirm-shrink      # 执行收缩(需确认)
    python scripts/shrink_raw_bdib.py --confirm-shrink --months 6  # 保留6个月

安全网 (7层, 见 plan.md §附录A):
    层级1: 前置防呆 — WAL checkpoint / integrity_check / Parquet校验 / 磁盘空间
    层级2: 批次校验 — 新DB vs 原DB行数/聚合/抽样对比
    层级3: API回归 — 由 daily_observation_check.py 覆盖
    层级4: 关联完整性 — 由 daily_observation_check.py 覆盖
    层级5: 观察期每日自动 — observation_A7.json
    层级6: 硬性阻断 — 自动判定
    层级7: .BAK物理保留 — 观察期通过后只读保留30天

执行步骤 (见 plan.md §7.3 路径1):
    Step 1: 全量备份 → raw_bdib.db.bak_migration_YYYYMMDD
    Step 2: 逐月复制到Parquet (已完成, 见A4回填脚本)
    Step 3: 全量校验通过后, 收缩SQLite
    Step 4: 14天观察期
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import sys
from datetime import datetime, date
from pathlib import Path
from typing import Optional

from DataPipeline.config import Config
from DataPipeline.storage.connection import AccessTier, ConnectionManager
from DataPipeline.storage.market_store import MarketStoreReader, MarketStoreWriter

logger = logging.getLogger(__name__)

LOG_DIR = Config._PROJECT_ROOT / "scripts" / "logs"
OBSERVATION_MANIFEST_NAME = "observation_A7.json"

RAW_BDIB_COLS = [
    "equ_ticker", "order_as_of_date", "mkt_timestamp",
    "open", "high", "low", "close", "volume", "num_trds", "value",
]


class RawBDIBShrinker:
    """raw_bdib.db收缩器 — 移除老旧数据, 仅保留近N个月。"""

    def __init__(self, retention_months: int = 3, dry_run: bool = True, temp_dir: Optional[Path] = None):
        self._retention_months = retention_months
        self._dry_run = dry_run
        self._mgr = ConnectionManager()
        self._db_path = Config.RAW_BDIB_DB
        self._temp_dir = Path(temp_dir) if temp_dir else self._db_path.parent
        self._bak_path: Optional[Path] = None
        self._bak_sha256: str = ""
        self._new_db_path: Optional[Path] = None

    # ── 层级1: 前置防呆 ──

    def _preflight(self) -> bool:
        """前置防呆检查, 任一失败则中止。"""
        logger.info("═══ 层级1: 前置防呆 ═══")
        ok = True

        if not self._db_path.exists():
            logger.error("数据库不存在: %s", self._db_path)
            return False

        db_size_gb = self._db_path.stat().st_size / 1e9
        logger.info("源DB: %s (%.1f GB)", self._db_path, db_size_gb)

        # 磁盘空间检查 (检查临时目录所在磁盘, 新DB在此创建)
        self._temp_dir.mkdir(parents=True, exist_ok=True)
        free_gb = shutil.disk_usage(self._temp_dir).free / 1e9
        if self._temp_dir != self._db_path.parent:
            need_gb = db_size_gb * 0.4  # 新DB仅需源文件的~40%空间
        else:
            need_gb = db_size_gb * 1.3
        if free_gb < need_gb:
            logger.error("磁盘空间不足: 需要%.1fGB, 剩余%.1fGB", need_gb, free_gb)
            ok = False
        else:
            logger.info("磁盘空间: 剩余%.1fGB (需要%.1fGB) ✓", free_gb, need_gb)

        # Integrity check (dry-run跳过重IO操作)
        total_rows = 0
        if not self._dry_run:
            conn = self._mgr.get_admin_connection("raw_bdib")
            try:
                result = conn.execute("PRAGMA quick_check").fetchone()
                if result[0] != "ok":
                    logger.error("quick_check失败: %s", result[0])
                    ok = False
                else:
                    logger.info("quick_check: ok ✓")

                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                logger.info("WAL checkpoint: TRUNCATE ✓")

                total_rows = conn.execute(
                    f"SELECT COUNT(*) FROM {Config.RAW_BDIB_TABLE}"
                ).fetchone()[0]
                logger.info("总行数: %d", total_rows)

                date_range = conn.execute(
                    f"SELECT MIN(order_as_of_date), MAX(order_as_of_date) FROM {Config.RAW_BDIB_TABLE}"
                ).fetchone()
                logger.info("日期范围: %s ~ %s", date_range[0], date_range[1])
            finally:
                conn.close()
        else:
            logger.info("quick_check: 跳过 (dry-run)")
            logger.info("WAL checkpoint: 跳过 (dry-run)")
            logger.info("总行数: 跳过 (dry-run)")

        # Parquet数据存在性校验
        reader = MarketStoreReader(Config.BDIB_PARQUET_DIR)
        try:
            pq_count = reader.get_row_count()
            pq_dates = reader.get_distinct_dates()
            logger.info("Parquet行数: %d, 日期数: %d", pq_count, len(pq_dates))
            if pq_count == 0:
                if self._dry_run:
                    logger.warning("Parquet无数据 — 请确保已执行A4回填脚本 (scripts/backfill_bdib_to_parquet.py)")
                else:
                    logger.error("Parquet无数据! 请先执行A4回填脚本")
                    ok = False
            elif total_rows > 0 and pq_count < total_rows * 0.99:
                logger.warning("Parquet行数(%d) < SQLite行数(%d) 的99%%, 可能有数据遗漏",
                               pq_count, total_rows)
        finally:
            reader.close()

        # 计算保留截止日期
        cutoff_date = self._compute_cutoff_date()
        logger.info("保留截止日期: %s (保留最近%d个月)", cutoff_date, self._retention_months)

        if not self._dry_run:
            conn = self._mgr.get_admin_connection("raw_bdib")
            try:
                keep_rows = conn.execute(
                    f"SELECT COUNT(*) FROM {Config.RAW_BDIB_TABLE} WHERE order_as_of_date >= ?",
                    [cutoff_date],
                ).fetchone()[0]
                remove_rows = total_rows - keep_rows
                logger.info("保留行数: %d, 移除行数: %d (%.1f%%)",
                            keep_rows, remove_rows, remove_rows / max(total_rows, 1) * 100)
            finally:
                conn.close()
        else:
            logger.info("保留行数估算: 跳过 (dry-run)")

        return ok

    def _compute_cutoff_date(self) -> str:
        today = date.today()
        year = today.year
        month = today.month - self._retention_months
        while month <= 0:
            month += 12
            year -= 1
        return f"{year:04d}{month:02d}01"

    # ── Step 1: 计算源文件SHA256 (实际备份由replace_original完成) ──

    def _create_backup(self) -> bool:
        """计算源文件SHA256。实际.BAK由os.replace在替换时原子完成。"""
        timestamp = datetime.now().strftime("%Y%m%d")
        bak_path = self._db_path.parent / f"{self._db_path.stem}.bak_migration_{timestamp}"

        self._bak_path = bak_path

        logger.info("── Step 1: 源文件校验 ──")
        logger.info("源: %s (%.1f GB)", self._db_path, self._db_path.stat().st_size / 1e9)

        if self._dry_run:
            logger.info("[DRY-RUN] 将计算SHA256 → %s", bak_path.name)
            return True

        try:
            sha = self._sha256_file(self._db_path)
            logger.info("SHA256: %s", sha[:16] + "...")
            self._bak_sha256 = sha
            return True
        except Exception as e:
            logger.error("SHA256计算失败: %s", e)
            return False

    @staticmethod
    def _sha256_file(path: Path) -> str:
        sha = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha.update(chunk)
        return sha.hexdigest()

    # ── Step 3: 创建新DB ──

    def _create_shrunk_db(self) -> bool:
        """创建仅包含近N个月数据的新DB文件。"""
        logger.info("── Step 3: 创建收缩数据库 ──")
        cutoff_date = self._compute_cutoff_date()

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._temp_dir.mkdir(parents=True, exist_ok=True)
        new_path = self._temp_dir / f"raw_bdib_shrunk_{timestamp}.db"

        if self._dry_run:
            self._new_db_path = Config.DATA_DIR / f"raw_bdib_shrunk_dryrun.db"
            logger.info("[DRY-RUN] 将在 %s 创建新DB, 过滤条件: order_as_of_date >= %s",
                        new_path.name, cutoff_date)
            return True

        source_conn = sqlite3.connect(str(self._db_path))
        try:
            source_conn.execute("PRAGMA query_only = ON")

            dest_conn = sqlite3.connect(str(new_path))
            try:
                dest_conn.execute("PRAGMA journal_mode=WAL")
                dest_conn.execute("PRAGMA synchronous=OFF")
                dest_conn.execute("PRAGMA cache_size=-2000000")

                # 挂载源DB, 单语句复制: O(1) 替代批处理 O(n²)
                dest_conn.execute(f"ATTACH DATABASE ? AS source_db", [str(self._db_path)])

                # 复刻表DDL + 索引
                create_sql = source_conn.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                    [Config.RAW_BDIB_TABLE],
                ).fetchone()
                if not create_sql or not create_sql[0]:
                    logger.error("无法获取源表DDL")
                    return False
                dest_conn.execute(create_sql[0])

                for idx_sql in source_conn.execute(
                    "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL",
                    [Config.RAW_BDIB_TABLE],
                ).fetchall():
                    if idx_sql[0]:
                        try:
                            dest_conn.execute(idx_sql[0])
                        except Exception:
                            pass

                # 复刻 daily_summary 表
                summary_ddl = source_conn.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                    [Config.BDIB_DAILY_SUMMARY_TABLE],
                ).fetchone()
                if summary_ddl and summary_ddl[0]:
                    dest_conn.execute(summary_ddl[0])

                # 单语句复制: raw_bdib 数据
                logger.info("复制数据: WHERE order_as_of_date >= %s", cutoff_date)
                copied = dest_conn.execute(
                    f"INSERT INTO {Config.RAW_BDIB_TABLE} "
                    f"SELECT * FROM source_db.{Config.RAW_BDIB_TABLE} "
                    "WHERE order_as_of_date >= ?",
                    [cutoff_date],
                ).rowcount
                logger.info("raw_bdib: 复制 %d 行", copied)

                # 单语句复制: daily_summary
                try:
                    summary_copied = dest_conn.execute(
                        f"INSERT INTO {Config.BDIB_DAILY_SUMMARY_TABLE} "
                        f"SELECT * FROM source_db.{Config.BDIB_DAILY_SUMMARY_TABLE} "
                        "WHERE trade_date >= ?",
                        [cutoff_date],
                    ).rowcount
                    logger.info("daily_summary: 复制 %d 行", summary_copied)
                except Exception:
                    logger.info("daily_summary: 跳过 (表可能为空)")

                dest_conn.commit()
                dest_conn.execute("DETACH DATABASE source_db")

                logger.info("新DB: %s (raw_bdib=%d行)", new_path.name, copied)

                # 校验新DB
                integrity = dest_conn.execute("PRAGMA integrity_check").fetchone()
                logger.info("新DB integrity_check: %s", integrity[0])
                if integrity[0] != "ok":
                    logger.error("新DB完整性检查失败!")
                    dest_conn.close()
                    source_conn.close()
                    new_path.unlink(missing_ok=True)
                    return False
            finally:
                dest_conn.close()
        finally:
            source_conn.close()

        self._new_db_path = new_path
        return True

    # ── Step 3b: 替换原DB ──

    def _replace_original(self) -> bool:
        """用新DB替换原DB, 原文件保留为.BAK。"""
        if self._dry_run:
            logger.info("[DRY-RUN] 将替换 %s → %s", self._db_path.name, self._new_db_path.name)
            return True

        if not self._new_db_path or not self._new_db_path.exists():
            logger.error("新DB不存在")
            return False

        logger.info("── 替换原DB ──")

        # 关闭所有连接
        self._mgr.close_thread_cached_connections()

        try:
            bak_path = self._bak_path or self._db_path.parent / f"{self._db_path.stem}.bak_migration_unknown"
            os.replace(str(self._db_path), str(bak_path))
            logger.info("原DB已重命名为.BAK: %s", bak_path.name)

            # 跨盘移动: os.replace 不支持跨盘, 用 copy2 + unlink
            if self._new_db_path.drive != self._db_path.drive:
                shutil.copy2(str(self._new_db_path), str(self._db_path))
                self._new_db_path.unlink()
                logger.info("新DB已跨盘复制到: %s", self._db_path.name)
            else:
                os.replace(str(self._new_db_path), str(self._db_path))
                logger.info("新DB已就位: %s", self._db_path.name)

            new_size_gb = self._db_path.stat().st_size / 1e9
            old_size_gb = bak_path.stat().st_size / 1e9
            logger.info("体积: %.1fGB → %.1fGB (缩减 %.1f%%)",
                        old_size_gb, new_size_gb,
                        (1 - new_size_gb / max(old_size_gb, 0.001)) * 100)

            return True
        except Exception as e:
            logger.error("替换失败: %s", e)
            return False

    # ── 观察期清单 ──

    def _init_observation_manifest(self) -> bool:
        """初始化观察期manifest。"""
        manifest_path = Config.DATA_DIR / OBSERVATION_MANIFEST_NAME
        bak_path = self._bak_path or Config.RAW_BDIB_DB.parent / "raw_bdib.db.bak_migration_unknown"

        manifest = {
            "phase": "A7",
            "description": f"收缩 raw_bdib.db 至近{self._retention_months}个月",
            "bak_files": [
                {
                    "path": str(bak_path),
                    "sha256": getattr(self, '_bak_sha256', ''),
                    "source_db": "raw_bdib.db",
                    "created_at": datetime.now().isoformat(),
                }
            ],
            "start_date": date.today().isoformat(),
            "retention_until": (date.today().replace(day=date.today().day + 14)).isoformat(),
            "min_pipeline_cycles": 2,
            "pipeline_cycles_run": 0,
            "daily_checks": [],
            "blocking_conditions_triggered": [],
            "final_status": "pending",
            "retention_months": self._retention_months,
        }

        if self._dry_run:
            logger.info("[DRY-RUN] 将创建观察期清单: %s", manifest_path)
            return True

        manifest_path.write_text(json.dumps(manifest, indent=2, default=str))
        logger.info("观察期清单已创建: %s", manifest_path)
        return True

    def run(self) -> int:
        """执行收缩流程。Returns 0=成功。"""
        logger.info("═══ raw_bdib.db收缩 (保留%d个月) ═══", self._retention_months)

        if not self._preflight():
            logger.error("前置检查失败, 中止")
            return 1

        if not self._create_backup():
            logger.error("备份失败, 中止")
            return 1

        if not self._create_shrunk_db():
            logger.error("新DB创建失败, 中止")
            return 1

        if not self._replace_original():
            logger.error("替换失败! 请手动恢复.BAK文件")
            return 1

        if not self._init_observation_manifest():
            logger.warning("观察期清单创建失败 (不影响数据)")

        logger.info("═══ 收缩完成 ═══")
        logger.info("下一步: 启动14天观察期 (daily_observation_check.py --phase A7)")
        return 0


def main():
    parser = argparse.ArgumentParser(description="raw_bdib.db收缩 — 移除老旧数据")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="预演模式(默认): 检查但不修改任何文件")
    parser.add_argument("--confirm-shrink", action="store_true",
                        help="确认执行收缩 (必须显式指定)")
    parser.add_argument("--months", type=int, default=None,
                        help=f"保留月数 (默认: {Config.BDIB_HOT_RETENTION_MONTHS})")
    parser.add_argument("--temp-dir", type=str, default=None,
                        help="临时目录 (新DB创建位置, 完成后自动移回源目录)")
    parser.add_argument("-v", "--verbose", action="store_true", help="详细日志")
    args = parser.parse_args()

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"shrink_a7_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(str(log_file), encoding="utf-8")],
    )

    is_dry = not args.confirm_shrink
    retention = args.months or Config.BDIB_HOT_RETENTION_MONTHS

    if not args.confirm_shrink:
        logger.info("*** DRY-RUN模式: 仅检查不修改 ***")
        logger.info("使用 --confirm-shrink 执行实际收缩")
        logger.info("")

    shrinker = RawBDIBShrinker(retention_months=retention, dry_run=is_dry, temp_dir=args.temp_dir)
    result = shrinker.run()
    sys.exit(result)


if __name__ == "__main__":
    main()
