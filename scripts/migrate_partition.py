"""processed_fills.db 垂直分区迁移 — B1: 创建新DB + 复制数据。

将 processed_fills.db 中的9张表拆分至3个DB (按访问模式):
    execution_history.db — route_registry, order_history, route_history, route_event_history
    ticker_registry.db   — ticker_repository, equ/ccy_ticker_registry, ticker_date_mapping, order_label
    processed_fills.db   — 保留 processed_fills, agg_fills_*, processing_log

使用方式:
    python scripts/migrate_partition.py --dry-run            # 预演
    python scripts/migrate_partition.py --confirm-migrate    # 执行迁移(复制数据)
    python scripts/migrate_partition.py --verify             # 仅验证行数一致性
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from DataPipeline.config import Config
from DataPipeline.storage.connection import AccessTier, ConnectionManager
from DataPipeline.storage.schema.inline_ddl import (
    init_processed_fills_schema,
)
from DataPipeline.storage.schema.columns import (
    ROUTE_REGISTRY_COLUMNS,
    ORDER_HISTORY_COLUMNS,
    ROUTE_HISTORY_COLUMNS,
    ROUTE_EVENT_HISTORY_COLUMNS,
)

LOG_DIR = Config._PROJECT_ROOT / "scripts" / "logs"
MANIFEST_NAME = "partition_b1_manifest.json"

logger = logging.getLogger(__name__)

# 分区方案: (源表名, 目标DB键, 目标表名)
EXECUTION_HISTORY_TABLES = [
    ("route_registry", "execution_history", "route_registry"),
    ("order_history", "execution_history", "order_history"),
    ("route_history", "execution_history", "route_history"),
    ("route_event_history", "execution_history", "route_event_history"),
]

TICKER_REGISTRY_TABLES = [
    ("ticker_repository", "ticker_registry", "ticker_repository"),
    ("equ_ticker_registry", "ticker_registry", "equ_ticker_registry"),
    ("ccy_ticker_registry", "ticker_registry", "ccy_ticker_registry"),
    ("ticker_date_mapping", "ticker_registry", "ticker_date_mapping"),
    ("order_label", "ticker_registry", "order_label"),
]

ALL_PARTITIONS = EXECUTION_HISTORY_TABLES + TICKER_REGISTRY_TABLES


class PartitionMigrator:
    """processed_fills.db → 3-DB 分区迁移器。"""

    def __init__(self, dry_run: bool = True, verify_only: bool = False):
        self._dry_run = dry_run
        self._verify_only = verify_only
        self._mgr = ConnectionManager()
        self._source_path = Config.PROCESSED_FILLS_DB
        self._exec_history_path = Config.EXECUTION_HISTORY_DB
        self._ticker_registry_path = Config.TICKER_REGISTRY_DB
        self._manifest: dict[str, Any] = {
            "started_at": datetime.now().isoformat(),
            "tables": [],
        }

    def _preflight(self) -> bool:
        ok = True
        if not self._source_path.exists():
            logger.error("源DB不存在: %s", self._source_path)
            return False

        source_gb = self._source_path.stat().st_size / 1e9
        logger.info("源DB: %s (%.1f GB)", self._source_path, source_gb)

        free_gb = self._source_path.stat().st_size / 1e9  # actually need free space check
        import shutil
        free_gb = shutil.disk_usage(self._source_path.parent).free / 1e9
        logger.info("磁盘空间: %.1f GB", free_gb)

        return ok

    def _create_target_dbs(self) -> bool:
        """在新DB中创建表 (使用 inline DDL 中的 processed_fills schema, 然后只保留需要的表)."""
        logger.info("── 创建目标DB ──")

        # 使用 ATTACH 从源DB复刻DDL
        source_conn = sqlite3.connect(str(self._source_path))
        source_conn.execute("PRAGMA query_only = ON")

        for target_path, tables_info in [
            (self._exec_history_path, EXECUTION_HISTORY_TABLES),
            (self._ticker_registry_path, TICKER_REGISTRY_TABLES),
        ]:
            if self._dry_run:
                logger.info("[DRY-RUN] 创建: %s", target_path.name)
                continue

            if target_path.exists():
                logger.warning("%s 已存在, 跳过DDL创建", target_path.name)
                continue

            dest_conn = sqlite3.connect(str(target_path))
            try:
                dest_conn.execute("PRAGMA journal_mode=WAL")

                for (src_table, _, dest_table) in tables_info:
                    create_sql = source_conn.execute(
                        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                        [src_table],
                    ).fetchone()
                    if create_sql and create_sql[0]:
                        rename_sql = create_sql[0].replace(
                            f"CREATE TABLE {src_table}",
                            f"CREATE TABLE {dest_table}",
                        )
                        try:
                            dest_conn.execute(rename_sql)
                            logger.info("  创建表: %s", dest_table)
                        except Exception as e:
                            logger.warning("  创建表 %s 失败: %s", dest_table, e)

                    # 复刻索引
                    for idx_sql in source_conn.execute(
                        "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL",
                        [src_table],
                    ).fetchall():
                        if idx_sql[0]:
                            renamed = idx_sql[0].replace(
                                f"ON {src_table}", f"ON {dest_table}"
                            ).replace(
                                f"INDEX {src_table}", f"INDEX {dest_table}"
                            )
                            try:
                                dest_conn.execute(renamed)
                            except Exception:
                                pass

                dest_conn.commit()
                logger.info("  创建完成: %s", target_path.name)
            finally:
                dest_conn.close()

        source_conn.close()
        return True

    def _copy_data(self) -> bool:
        """从 processed_fills.db 复制数据到新DB。"""
        logger.info("── 复制数据 ──")

        if self._dry_run:
            for src_table, target_db, _ in ALL_PARTITIONS:
                logger.info("[DRY-RUN] 复制: %s → %s", src_table, target_db)
            return True

        all_ok = True
        for src_table, target_db_key, dest_table in ALL_PARTITIONS:
            source_conn = sqlite3.connect(str(self._source_path))
            source_conn.execute("PRAGMA query_only = ON")

            try:
                src_count = source_conn.execute(
                    f"SELECT COUNT(*) FROM {src_table}"
                ).fetchone()[0]

                if src_count == 0:
                    logger.info("  %s: 0行, 跳过", src_table)
                    self._manifest["tables"].append({
                        "table": src_table, "target_db": target_db_key,
                        "source_rows": 0, "copied_rows": 0, "match": True,
                    })
                    continue

                # 读取源表列名
                cursor = source_conn.execute(f"SELECT * FROM {src_table} LIMIT 1")
                src_cols = [d[0] for d in cursor.description]
                col_str = ", ".join(src_cols)

                # 分批复制
                dest_path = self._mgr.get_path(target_db_key)
                dest_conn = sqlite3.connect(str(dest_path))
                batch_size = 10000
                offset = 0
                total_copied = 0

                try:
                    placeholders = ", ".join(["?"] * len(src_cols))

                    while True:
                        rows = source_conn.execute(
                            f"SELECT {col_str} FROM {src_table} LIMIT ? OFFSET ?",
                            [batch_size, offset],
                        ).fetchall()
                        if not rows:
                            break

                        dest_conn.executemany(
                            f"INSERT OR IGNORE INTO {dest_table} ({col_str}) VALUES ({placeholders})",
                            rows,
                        )
                        total_copied += len(rows)
                        offset += batch_size

                    dest_conn.commit()
                    dest_count = dest_conn.execute(
                        f"SELECT COUNT(*) FROM {dest_table}"
                    ).fetchone()[0]
                finally:
                    dest_conn.close()

                match = src_count == dest_count
                status = "✓" if match else f"✗ ({dest_count}/{src_count})"
                logger.info("  %s: %d行 → %s", src_table, src_count, status)

                self._manifest["tables"].append({
                    "table": src_table, "target_db": target_db_key,
                    "source_rows": src_count, "copied_rows": dest_count,
                    "match": match,
                })
                if not match:
                    all_ok = False
            except Exception as e:
                logger.error("  %s: 复制失败 - %s", src_table, e)
                all_ok = False

        return all_ok

    def _verify(self) -> bool:
        """验证新DB与源DB行数一致性。"""
        logger.info("── 验证行数一致性 ──")

        source_conn = sqlite3.connect(str(self._source_path))
        source_conn.execute("PRAGMA query_only = ON")
        all_ok = True

        for src_table, target_db_key, dest_table in ALL_PARTITIONS:
            try:
                src_count = source_conn.execute(
                    f"SELECT COUNT(*) FROM {src_table}"
                ).fetchone()[0]
            except Exception:
                src_count = -1

            dest_count = -1
            dest_path = self._mgr.get_path(target_db_key)
            if dest_path.exists():
                try:
                    dest_conn = sqlite3.connect(str(dest_path))
                    dest_count = dest_conn.execute(
                        f"SELECT COUNT(*) FROM {dest_table}"
                    ).fetchone()[0]
                    dest_conn.close()
                except Exception:
                    pass

            match = src_count == dest_count
            status = "✓" if match else f"✗ (src={src_count}, dst={dest_count})"
            logger.info("  %s: %s", src_table, status)
            if not match:
                all_ok = False

        source_conn.close()
        return all_ok

    def run(self) -> int:
        logger.info("═══ processed_fills.db 分区迁移 ═══")

        if self._verify_only:
            ok = self._verify()
            return 0 if ok else 1

        if not self._preflight():
            return 1

        if not self._create_target_dbs():
            return 1

        if not self._copy_data():
            logger.error("数据复制存在差异!")
            return 1

        ok = self._verify()
        self._manifest["completed_at"] = datetime.now().isoformat()
        self._manifest["all_match"] = ok

        manifest_path = Config.DATA_DIR / MANIFEST_NAME
        manifest_path.write_text(json.dumps(self._manifest, indent=2, default=str))

        logger.info("═══ 分区迁移完成 ═══")
        logger.info("Manifest: %s", manifest_path)
        return 0 if ok else 1


def main():
    parser = argparse.ArgumentParser(description="processed_fills.db 垂直分区迁移")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="预演模式")
    parser.add_argument("--confirm-migrate", action="store_true",
                        help="确认执行迁移")
    parser.add_argument("--verify", action="store_true",
                        help="仅验证行数一致性")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    if not args.confirm_migrate and not args.verify:
        logger.info("*** DRY-RUN模式 ***")
        logger.info("使用 --confirm-migrate 执行实际迁移")

    dry = not args.confirm_migrate and not args.verify
    migrator = PartitionMigrator(dry_run=dry, verify_only=args.verify)
    result = migrator.run()
    sys.exit(result)


if __name__ == "__main__":
    main()
