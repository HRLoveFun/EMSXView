"""B4: 清理 processed_fills.db 已迁移至分区库的表。

processed_fills.db (26.4 GB) 中已有 9 张表迁移至:
    execution_history.db: route_registry, order_history, route_history, route_event_history
    ticker_registry.db:   ticker_repository, equ_ticker_registry, ccy_ticker_registry,
                          ticker_date_mapping, order_label

使用方式:
    python scripts/cleanup_partitioned_db.py --dry-run
    python scripts/cleanup_partitioned_db.py --confirm-cleanup
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
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from DataPipeline.config import Config

logger = logging.getLogger(__name__)

LOG_DIR = Config._PROJECT_ROOT / "scripts" / "logs"

# 已迁移至 execution_history.db 的表
EXECUTION_HISTORY_TABLES = [
    "route_registry",
    "order_history",
    "route_history",
    "route_event_history",
]

# 已迁移至 ticker_registry.db 的表
TICKER_REGISTRY_TABLES = [
    "ticker_repository",
    "equ_ticker_registry",
    "ccy_ticker_registry",
    "ticker_date_mapping",
    "order_label",
]

ALL_MIGRATED_TABLES = EXECUTION_HISTORY_TABLES + TICKER_REGISTRY_TABLES


class PartitionCleanupRunner:
    """B4 分区表清理器 — 备份 → 校验 → DROP → VACUUM → 观察期。"""

    def __init__(self, dry_run: bool = True):
        self._dry_run = dry_run
        self._source = Config.PROCESSED_FILLS_DB
        self._exec_db = Config.EXECUTION_HISTORY_DB
        self._ticker_db = Config.TICKER_REGISTRY_DB
        self._bak_path: Path | None = None
        self._bak_sha256: str = ""

    # ── 前置防呆 ──

    def _preflight(self) -> bool:
        ok = True

        if not self._source.exists():
            logger.error("processed_fills.db 不存在: %s", self._source)
            return False

        source_gb = self._source.stat().st_size / 1e9
        logger.info("processed_fills.db: %.1f GB", source_gb)

        # 磁盘空间检查
        free_gb = shutil.disk_usage(self._source.parent).free / 1e9
        # .BAK 需要的空间
        needed = source_gb * 1.2
        if free_gb < needed and not self._dry_run:
            logger.error("磁盘空间不足: 需要 %.1f GB, 剩余 %.1f GB", needed, free_gb)
            ok = False
        else:
            logger.info("磁盘空间: 剩余 %.1f GB ✓", free_gb)

        # 验证新库存在
        for db_path in [self._exec_db, self._ticker_db]:
            if not db_path.exists():
                logger.error("分区库不存在: %s", db_path)
                ok = False
            else:
                logger.info("分区库存在: %s (%.1f MB)", db_path.name,
                            db_path.stat().st_size / 1e6)

        # 源库完整性检查
        if not self._dry_run:
            conn = sqlite3.connect(str(self._source))
            try:
                result = conn.execute("PRAGMA quick_check").fetchone()
                if result[0] != "ok":
                    logger.error("quick_check 失败: %s", result[0])
                    ok = False
                else:
                    logger.info("quick_check: ok ✓")
            finally:
                conn.close()

        return ok

    # ── Step 1: 备份 ──

    def _create_backup(self) -> bool:
        timestamp = datetime.now().strftime("%Y%m%d")
        self._bak_path = self._source.parent / f"processed_fills.bak_migration_{timestamp}"

        if self._dry_run:
            logger.info("[DRY-RUN] 将创建备份: %s", self._bak_path.name)
            return True

        logger.info("── Step 1: 创建备份 ──")
        logger.info("源: %s (%.1f GB)", self._source, self._source.stat().st_size / 1e9)

        try:
            shutil.copy2(str(self._source), str(self._bak_path))
            self._bak_sha256 = self._sha256_file(self._bak_path)
            logger.info("备份完成: %s", self._bak_path.name)
            logger.info("SHA256: %s...", self._bak_sha256[:16])
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

    # ── Step 2: 行数校验 ──

    def _verify_row_counts(self) -> dict[str, Any]:
        """确认新库中已迁移表的行数与源库一致。"""
        logger.info("── Step 2: 行数校验 ──")

        result: dict[str, Any] = {"tables": {}, "all_match": True}
        src_conn = sqlite3.connect(str(self._source))

        try:
            for table in ALL_MIGRATED_TABLES:
                # 源库行数
                src_count = src_conn.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]

                # 目标库
                if table in EXECUTION_HISTORY_TABLES:
                    target_db = self._exec_db
                else:
                    target_db = self._ticker_db

                tgt_conn = sqlite3.connect(str(target_db))
                try:
                    tgt_count = tgt_conn.execute(
                        f"SELECT COUNT(*) FROM {table}"
                    ).fetchone()[0]
                finally:
                    tgt_conn.close()

                match = src_count == tgt_count
                result["tables"][table] = {
                    "source_rows": src_count,
                    "target_rows": tgt_count,
                    "match": match,
                }
                if not match:
                    result["all_match"] = False
                status = "✓" if match else "✗"
                logger.info("  [%s] %s: %d = %d", status, table, src_count, tgt_count)
        finally:
            src_conn.close()

        if result["all_match"]:
            logger.info("── 行数校验全部通过 ✓ ──")
        else:
            logger.error("── 行数校验存在不匹配! ──")

        return result

    # ── Step 3: DROP 已迁移表 ──

    def _drop_migrated_tables(self) -> bool:
        logger.info("── Step 3: DROP 已迁移表 ──")

        if self._dry_run:
            logger.info("[DRY-RUN] 将从 processed_fills.db 删除以下表:")
            for t in ALL_MIGRATED_TABLES:
                logger.info("  DROP TABLE %s;", t)
            return True

        conn = sqlite3.connect(str(self._source))
        try:
            for table in ALL_MIGRATED_TABLES:
                conn.execute(f"DROP TABLE IF EXISTS {table}")
                logger.info("  DROP TABLE %s ✓", table)
            conn.commit()
        except Exception as e:
            logger.error("DROP 失败: %s", e)
            return False
        finally:
            conn.close()

        return True

    # ── Step 4: VACUUM ──

    def _vacuum(self) -> bool:
        logger.info("── Step 4: VACUUM ──")

        if self._dry_run:
            logger.info("[DRY-RUN] 将执行 VACUUM")
            return True

        size_before = self._source.stat().st_size / 1e9
        logger.info("VACUUM 前: %.2f GB", size_before)

        t0 = time.time()
        conn = sqlite3.connect(str(self._source))
        try:
            conn.execute("VACUUM")
        finally:
            conn.close()
        elapsed = time.time() - t0

        size_after = self._source.stat().st_size / 1e9
        freed_gb = size_before - size_after
        logger.info("VACUUM 后: %.2f GB (释放 %.2f GB, 耗时 %.0fs)",
                     size_after, freed_gb, elapsed)

        resource_path = str(self._source)
        logger.info("完整路径: %s", resource_path)

        return True

    # ── 观察期清单 ──

    def _init_observation_manifest(self, verify_result: dict) -> bool:
        manifest_path = Config.DATA_DIR / "observation_B4.json"
        manifest = {
            "phase": "B4",
            "description": (
                "清理 processed_fills.db 已迁移至分区库的表 "
                "(9表 → execution_history.db / ticker_registry.db)"
            ),
            "bak_files": [
                {
                    "path": str(self._bak_path) if self._bak_path else "",
                    "sha256": self._bak_sha256,
                    "source_db": "processed_fills.db",
                    "created_at": datetime.now().isoformat(),
                }
            ],
            "start_date": date.today().isoformat(),
            "retention_until": (date.today() + timedelta(days=14)).isoformat(),
            "min_pipeline_cycles": 2,
            "pipeline_cycles_run": 0,
            "daily_checks": [],
            "blocking_conditions_triggered": [],
            "final_status": "pending",
            "verify_result": verify_result,
            "db_size_gb_before": round(
                self._source.stat().st_size / 1e9, 2,
            ) if self._source.exists() else 0,
        }

        if self._dry_run:
            logger.info("[DRY-RUN] 将创建观察期清单: %s", manifest_path)
            return True

        manifest_path.write_text(json.dumps(manifest, indent=2, default=str),
                                 encoding="utf-8")
        logger.info("观察期清单已创建: %s", manifest_path)
        return True

    def run(self) -> int:
        logger.info("═══ B4: 清理 processed_fills.db 已迁移表 ═══")
        logger.info("迁移到 execution_history.db: %s", ", ".join(EXECUTION_HISTORY_TABLES))
        logger.info("迁移到 ticker_registry.db:   %s", ", ".join(TICKER_REGISTRY_TABLES))
        logger.info("模式: %s", "DRY-RUN" if self._dry_run else "执行模式")

        if not self._preflight():
            return 1

        if not self._create_backup():
            return 1

        verify_result = self._verify_row_counts()
        if not verify_result["all_match"]:
            logger.error("行数校验失败! 中止清理")
            return 1

        if not self._drop_migrated_tables():
            return 1

        if not self._vacuum():
            return 1

        self._init_observation_manifest(verify_result)

        logger.info("═══ B4 清理完成 ═══")
        logger.info("下一步: 启动观察期 (daily_observation_check.py --phase B4)")
        return 0


def main():
    parser = argparse.ArgumentParser(description="B4: 清理 processed_fills.db 已迁移表")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="预演模式 (默认)")
    parser.add_argument("--confirm-cleanup", action="store_true",
                        help="确认执行清理")
    parser.add_argument("-v", "--verbose", action="store_true", help="详细日志")
    args = parser.parse_args()

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"cleanup_b4_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(str(log_file), encoding="utf-8"),
        ],
    )

    if not args.confirm_cleanup:
        logger.info("*** DRY-RUN 模式 ***")
        logger.info("使用 --confirm-cleanup 执行实际清理")

    runner = PartitionCleanupRunner(dry_run=not args.confirm_cleanup)
    result = runner.run()
    sys.exit(result)


if __name__ == "__main__":
    main()
