"""数据归档脚本 — 将过期历史数据迁移至归档DB并回收磁盘空间。

使用方式:
    python scripts/run_archive.py                    # 执行全部归档
    python scripts/run_archive.py --dry-run           # 预演
    python scripts/run_archive.py --db processed_fills # 指定数据库
    python scripts/run_archive.py --vacuum-only       # 仅VACUUM (增量模式)

调用链:
    daily_update.py → run_archive() (管线后自动执行)
    Windows Task Scheduler → 每月1次定时执行
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from DataPipeline.config import Config
from DataPipeline.storage.archiver import DataArchiver
from DataPipeline.storage.connection import ConnectionManager, AccessTier

logger = logging.getLogger(__name__)
LOG_DIR = Config._PROJECT_ROOT / "scripts" / "logs"

DB_INCLUDE = [
    "raw_fills",
    "processed_fills",
    "raw_bdib",
    "fill_bdib",
    "execution_history",
    "ticker_registry",
]

DB_SKIP = {"processed_raw_bdib"}  # A8退役后跳过


def _should_skip(db_name: str) -> bool:
    if db_name in DB_SKIP:
        return True
    if db_name == "processed_raw_bdib":
        return True
    return False


def _vacuum_incremental(data_dir: Path, dry_run: bool = False) -> dict[str, Any]:
    """对所有DB执行增量VACUUM。

    先设置 auto_vacuum=INCREMENTAL (仅首次), 然后逐DB执行
    PRAGMA incremental_vacuum 回收空闲页。
    """
    mgr = ConnectionManager()
    results: dict[str, Any] = {}

    db_keys = [k for k in DB_INCLUDE if k != "processed_raw_bdib"]
    for db_key in db_keys:
        if not mgr.database_exists(db_key):
            continue

        db_path = mgr.get_path(db_key)
        size_before = db_path.stat().st_size

        if dry_run:
            results[db_key] = {
                "size_before_gb": round(size_before / 1e9, 3),
                "action": "dry-run",
            }
            continue

        try:
            conn = mgr.get_admin_connection(db_key)
            # 设置增量模式 (首次执行有效)
            conn.execute("PRAGMA auto_vacuum = INCREMENTAL")

            # 获取空闲页数并回收
            freelist = conn.execute("PRAGMA freelist_count").fetchone()[0]
            if freelist > 0:
                conn.execute(f"PRAGMA incremental_vacuum({freelist})")
                logger.info("  %s: 回收 %d 空闲页", db_key, freelist)

            conn.close()

            size_after = db_path.stat().st_size
            freed_mb = (size_before - size_after) / 1e6

            results[db_key] = {
                "size_before_gb": round(size_before / 1e9, 3),
                "size_after_gb": round(size_after / 1e9, 3),
                "freed_mb": round(freed_mb, 2),
                "freelist_pages": freelist,
            }
            logger.info("  %s: %.1fMB freed", db_key, freed_mb)
        except Exception as e:
            results[db_key] = {"error": str(e)}
            logger.warning("  %s VACUUM failed: %s", db_key, e)

    return results


def _run_archive_auto(retention_override: dict[str, int] | None = None) -> dict[str, Any]:
    """在管线末尾自动执行的轻量归档。

    仅归档过期数据 (不执行全量VACUUM, 改用增量模式)。
    返回归档结果摘要。
    """
    archiver = DataArchiver(Config.DATA_DIR)
    all_results: dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "archived": {},
        "vacuum": {},
        "status": "ok",
    }

    for db_name in DB_INCLUDE:
        if _should_skip(db_name):
            continue
        try:
            config = None
            if retention_override and db_name in retention_override:
                config = retention_override[db_name]
            res = archiver.archive_expired(db_name, dry_run=False)
            if res:
                all_results["archived"][db_name] = res
        except Exception as e:
            logger.warning("归档 %s 失败: %s", db_name, e)

    # 增量VACUUM替代全量VACUUM
    all_results["vacuum"] = _vacuum_incremental(Config.DATA_DIR)

    return all_results


def _run_archive_full(dry_run: bool = False) -> dict[str, Any]:
    """全量归档 (每月调度, 包含完整VACUUM)。

    首次运行时执行完整VACUUM用于初始化增量模式。
    """
    if dry_run:
        archiver = DataArchiver(Config.DATA_DIR)
        results: dict[str, Any] = {"dry_run": True, "archived": {}}
        for db_name in DB_INCLUDE:
            if _should_skip(db_name):
                continue
            results["archived"][db_name] = archiver.archive_expired(db_name, dry_run=True)
        return results

    results: dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "archived": {},
        "status": "ok",
    }

    # Step 1: 归档过期数据
    archiver = DataArchiver(Config.DATA_DIR)
    for db_name in DB_INCLUDE:
        if _should_skip(db_name):
            continue
        try:
            res = archiver.archive_expired(db_name, dry_run=False)
            if res:
                results["archived"][db_name] = res
        except Exception as e:
            logger.error("归档 %s 失败: %s", db_name, e)

    # Step 2: 增量VACUUM (首次设置auto_vacuum=INCREMENTAL)
    results["vacuum"] = _vacuum_incremental(Config.DATA_DIR)

    return results


def main():
    parser = argparse.ArgumentParser(description="EMSXView 数据归档")
    parser.add_argument("--dry-run", action="store_true", help="预演模式")
    parser.add_argument("--db", type=str, help="指定数据库名称")
    parser.add_argument("--vacuum-only", action="store_true", help="仅执行增量VACUUM")
    parser.add_argument("--full", action="store_true", help="全量归档+VACUUM (每月调度)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    logger.info("═══ 数据归档 ═══")

    if args.vacuum_only:
        results = _vacuum_incremental(Config.DATA_DIR, dry_run=args.dry_run)
        print(json.dumps(results, indent=2, default=str))
        return

    if args.db:
        archiver = DataArchiver(Config.DATA_DIR)
        results = archiver.archive_expired(args.db, dry_run=args.dry_run)
        print(f"归档 {args.db}: {json.dumps(results, default=str)}")
        return

    if args.full or not args.dry_run:
        results = _run_archive_full(dry_run=args.dry_run)
        manifest_path = Config.DATA_DIR / "archive_manifest.json"
        manifest_path.write_text(json.dumps(results, indent=2, default=str))
        logger.info("归档清单: %s", manifest_path)
        print(json.dumps(results, indent=2, default=str))
    else:
        results = _run_archive_full(dry_run=True)
        print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
