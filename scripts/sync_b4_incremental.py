"""B4 增量同步: 将 B1 迁移后 processed_fills.db 新增数据同步到分区库。

背景:
    B1 将 processed_fills.db 中 9 张表复制到 execution_history.db 和 ticker_registry.db。
    B2 双写开关 PARTITION_DUAL_WRITE 实际未启用，导致 B1→当前期间的新增数据
    仅写入 processed_fills.db，分区库未同步。

策略:
    使用 INSERT OR IGNORE 逐表同步，依赖主键约束去重，幂等可安全重跑。
    route_event_history 的 event_id 为 AUTOINCREMENT，B1 迁移时已复制所有现有值，
    新增行的事件 id 不会与目标库冲突。

使用方式:
    python scripts/sync_b4_incremental.py --dry-run       # 预演 (默认)
    python scripts/sync_b4_incremental.py --confirm-sync  # 执行同步
    python scripts/sync_b4_incremental.py --verify-only   # 仅行数诊断
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from DataPipeline.config import Config

logger = logging.getLogger(__name__)

LOG_DIR = Config._PROJECT_ROOT / "scripts" / "logs"

# ── 分区方案: (表名, 目标库属性名, 主键列) ──
# 主键列用于诊断输出的行数差值计算，INSERT OR IGNORE 依赖表级 PRIMARY KEY 约束

EXECUTION_HISTORY_TABLES: list[tuple[str, str, list[str]]] = [
    ("route_registry",       "EXECUTION_HISTORY_DB", ["OrderId", "RouteId"]),
    ("order_history",        "EXECUTION_HISTORY_DB", ["OrderId", "order_as_of_date"]),
    ("route_history",        "EXECUTION_HISTORY_DB", ["OrderId", "RouteId", "order_as_of_date"]),
    ("route_event_history",  "EXECUTION_HISTORY_DB", ["event_id"]),
]

TICKER_REGISTRY_TABLES: list[tuple[str, str, list[str]]] = [
    ("ticker_repository",    "TICKER_REGISTRY_DB",   ["equ_ticker"]),
    ("equ_ticker_registry",  "TICKER_REGISTRY_DB",   ["equ_ticker"]),
    ("ccy_ticker_registry",  "TICKER_REGISTRY_DB",   ["ccy_ticker"]),
    ("ticker_date_mapping",  "TICKER_REGISTRY_DB",   ["ticker", "ticker_type", "order_as_of_date"]),
    ("order_label",          "TICKER_REGISTRY_DB",   ["OrderId"]),
]

ALL_SYNC_TABLES = EXECUTION_HISTORY_TABLES + TICKER_REGISTRY_TABLES

# 批量写入大小
BATCH_SIZE = 5000


class IncrementalSyncRunner:
    """B4 增量同步执行器。"""

    def __init__(self, dry_run: bool = True):
        self._dry_run = dry_run
        self._source = Config.PROCESSED_FILLS_DB

    # ── 前置防呆 ──

    def _preflight(self) -> bool:
        """验证源库和分区库存在且可访问。"""
        ok = True

        if not self._source.exists():
            logger.error("processed_fills.db 不存在: %s", self._source)
            return False

        logger.info("源库: %s (%.1f GB)", self._source.name,
                     self._source.stat().st_size / 1e9)

        for _, db_attr, _ in ALL_SYNC_TABLES:
            tgt_path = getattr(Config, db_attr)
            if not tgt_path.exists():
                logger.error("分区库不存在: %s", tgt_path)
                ok = False
            else:
                logger.info("分区库: %s (%.1f MB)", tgt_path.name,
                             tgt_path.stat().st_size / 1e6)

        # 源库完整性检查
        if not self._dry_run:
            conn = sqlite3.connect(str(self._source))
            try:
                result = conn.execute("PRAGMA quick_check").fetchone()
                if result[0] != "ok":
                    logger.error("源库 quick_check 失败: %s", result[0])
                    ok = False
                else:
                    logger.info("源库 quick_check: ok ✓")
            finally:
                conn.close()

        return ok

    # ── 诊断: 行数差异 ──

    def diagnose(self) -> dict[str, Any]:
        """输出 9 张表的行数差异诊断。"""
        result: dict[str, Any] = {"tables": {}, "total_diff": 0}

        src_conn = sqlite3.connect(str(self._source))
        try:
            for table, db_attr, pk_cols in ALL_SYNC_TABLES:
                tgt_path = getattr(Config, db_attr)

                src_count = src_conn.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]

                tgt_conn = sqlite3.connect(str(tgt_path))
                try:
                    tgt_count = tgt_conn.execute(
                        f"SELECT COUNT(*) FROM {table}"
                    ).fetchone()[0]
                finally:
                    tgt_conn.close()

                diff = src_count - tgt_count
                result["tables"][table] = {
                    "source_rows": src_count,
                    "target_rows": tgt_count,
                    "diff": diff,
                }
                result["total_diff"] += max(diff, 0)

                if diff == 0:
                    logger.info("  [✓] %s: %d = %d", table, src_count, tgt_count)
                else:
                    logger.info("  [→] %s: src=%d tgt=%d diff=%d",
                                 table, src_count, tgt_count, diff)
        finally:
            src_conn.close()

        if result["total_diff"] == 0:
            logger.info("── 全部 9 表行数一致，无需同步 ──")
        else:
            logger.info("── 总计需同步 %d 行 ──", result["total_diff"])

        return result

    # ── 增量同步 ──

    def _sync_table(
        self,
        src_conn: sqlite3.Connection,
        tgt_conn: sqlite3.Connection,
        table: str,
    ) -> int:
        """增量同步单张表，返回实际写入行数。

        使用 INSERT OR IGNORE 依赖表级 PRIMARY KEY 约束去重，
        已存在的行会被静默跳过。
        """
        # 获取列名
        col_info = src_conn.execute(f"PRAGMA table_info({table})").fetchall()
        col_names = [c[1] for c in col_info]
        col_list = ", ".join(col_names)
        placeholders = ", ".join(["?"] * len(col_names))
        insert_sql = f"INSERT OR IGNORE INTO {table} ({col_list}) VALUES ({placeholders})"

        inserted = 0
        skipped = 0
        cursor = src_conn.execute(f"SELECT * FROM {table}")
        batch: list[tuple] = []

        for row in cursor:
            batch.append(row)
            if len(batch) >= BATCH_SIZE:
                for r in batch:
                    try:
                        tgt_conn.execute(insert_sql, r)
                        inserted += 1
                    except sqlite3.IntegrityError:
                        skipped += 1
                tgt_conn.commit()
                batch.clear()

        # 处理剩余批次
        for r in batch:
            try:
                tgt_conn.execute(insert_sql, r)
                inserted += 1
            except sqlite3.IntegrityError:
                skipped += 1

        if batch:
            tgt_conn.commit()

        logger.debug("  %s: 写入 %d 行, 跳过 %d 行", table, inserted, skipped)
        return inserted

    def sync(self) -> dict[str, Any]:
        """执行全部 9 张表的增量同步。"""
        result: dict[str, Any] = {"tables": {}, "total_inserted": 0}

        src_conn = sqlite3.connect(str(self._source))

        try:
            for table, db_attr, pk_cols in ALL_SYNC_TABLES:
                tgt_path = getattr(Config, db_attr)

                # 同步前行数
                tgt_before_conn = sqlite3.connect(str(tgt_path))
                try:
                    tgt_before = tgt_before_conn.execute(
                        f"SELECT COUNT(*) FROM {table}"
                    ).fetchone()[0]
                finally:
                    tgt_before_conn.close()

                src_count = src_conn.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]

                diff = src_count - tgt_before

                if diff <= 0:
                    logger.info("[✓] %s: 已同步 (src=%d, tgt=%d)",
                                 table, src_count, tgt_before)
                    result["tables"][table] = {
                        "source_rows": src_count,
                        "target_before": tgt_before,
                        "target_after": tgt_before,
                        "inserted": 0,
                        "diff": 0,
                    }
                    continue

                logger.info("[→] %s: 差异 %d 行, 开始同步...", table, diff)

                if self._dry_run:
                    logger.info("  [DRY-RUN] 将 INSERT %d 行到 %s", diff, tgt_path.name)
                    result["tables"][table] = {
                        "source_rows": src_count,
                        "target_before": tgt_before,
                        "target_after": src_count,
                        "inserted": diff,
                        "diff": diff,
                    }
                    result["total_inserted"] += diff
                    continue

                # 实际写入
                tgt_conn = sqlite3.connect(str(tgt_path))
                try:
                    inserted = self._sync_table(src_conn, tgt_conn, table)
                finally:
                    tgt_conn.close()

                # 同步后行数验证
                tgt_after_conn = sqlite3.connect(str(tgt_path))
                try:
                    tgt_after = tgt_after_conn.execute(
                        f"SELECT COUNT(*) FROM {table}"
                    ).fetchone()[0]
                finally:
                    tgt_after_conn.close()

                match = tgt_after == src_count
                status = "✓" if match else "✗"
                logger.info("  [%s] %s: %d → %d (新增 %d 行)",
                             status, table, tgt_before, tgt_after, inserted)

                result["tables"][table] = {
                    "source_rows": src_count,
                    "target_before": tgt_before,
                    "target_after": tgt_after,
                    "inserted": inserted,
                    "diff": src_count - tgt_after,
                }
                result["total_inserted"] += inserted
        finally:
            src_conn.close()

        if not self._dry_run and result["total_inserted"] > 0:
            logger.info("── 增量同步完成: 总计写入 %d 行 ──", result["total_inserted"])
        elif result["total_inserted"] == 0:
            logger.info("── 无需同步，全部 9 表已一致 ──")

        return result

    # ── 校验 ──

    def verify(self) -> bool:
        """全量行数校验，确认 9 表一致。"""
        logger.info("── 全量行数校验 ──")
        all_match = True

        src_conn = sqlite3.connect(str(self._source))
        try:
            for table, db_attr, _ in ALL_SYNC_TABLES:
                tgt_path = getattr(Config, db_attr)
                src_count = src_conn.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]

                tgt_conn = sqlite3.connect(str(tgt_path))
                try:
                    tgt_count = tgt_conn.execute(
                        f"SELECT COUNT(*) FROM {table}"
                    ).fetchone()[0]
                finally:
                    tgt_conn.close()

                match = src_count == tgt_count
                if not match:
                    all_match = False
                status = "✓" if match else "✗"
                logger.info("  [%s] %s: %d = %d", status, table, src_count, tgt_count)
        finally:
            src_conn.close()

        if all_match:
            logger.info("── 全量校验通过: 9/9 ✓ ──")
        else:
            logger.error("── 全量校验存在不匹配! ──")

        return all_match

    # ── 主流程 ──

    def run(self, mode: str) -> int:
        """执行完整流程。

        Args:
            mode: "diagnose" | "sync" | "verify"
        """
        logger.info("═══ B4 增量同步: processed_fills.db → 分区库 ═══")
        logger.info("模式: %s (%s)", mode,
                     "DRY-RUN" if self._dry_run and mode == "sync" else "执行")

        if not self._preflight():
            return 1

        if mode == "diagnose":
            self.diagnose()
            return 0

        if mode == "verify":
            return 0 if self.verify() else 1

        if mode == "sync":
            sync_result = self.sync()
            if not self._dry_run and sync_result["total_inserted"] > 0:
                if not self.verify():
                    logger.error("同步后校验失败!")
                    return 1
            return 0

        logger.error("未知模式: %s", mode)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="B4 增量同步: 将 processed_fills.db 新增数据同步到分区库"
    )
    parser.add_argument(
        "--dry-run", action="store_true", default=True,
        help="预演模式 (默认)",
    )
    parser.add_argument(
        "--confirm-sync", action="store_true",
        help="确认执行增量同步",
    )
    parser.add_argument(
        "--verify-only", action="store_true",
        help="仅执行行数诊断 + 全量校验，不写入",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="详细日志",
    )
    args = parser.parse_args()

    # 日志配置
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"sync_b4_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(str(log_file), encoding="utf-8"),
        ],
    )

    # 确定运行模式
    if args.confirm_sync:
        mode = "sync"
        dry_run = False
    elif args.verify_only:
        mode = "verify"
        dry_run = True
    else:
        # 默认: 诊断模式 (与 --dry-run 行为一致)
        mode = "diagnose"
        dry_run = True
        logger.info("*** 诊断模式 (默认) ***")
        logger.info("使用 --confirm-sync 执行同步, --verify-only 仅校验")

    runner = IncrementalSyncRunner(dry_run=dry_run)
    return runner.run(mode)


if __name__ == "__main__":
    sys.exit(main())
