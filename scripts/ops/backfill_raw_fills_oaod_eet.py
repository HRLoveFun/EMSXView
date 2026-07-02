"""回填 raw_fills.order_as_of_date 与 exchange_exec_time 字段。

2026-07-02 P1 修复：
  - exchange_exec_time 4.6M 行 (41.7%) NULL（代码 bug: upsert_raw_api_data cols 缺该字段）
  - order_as_of_date 240 行 (0.002%) NULL（MUMBAI 不在 EXCHANGE_TIMEZONE 字典）
  - 修复代码后回填历史数据

数据规模:
  - exchange_exec_time 全表 4.6M 行 NULL
  - order_as_of_date 240 行 NULL (5 OrderId × 5 交易日)
  - 用 derive_exchange_times 内存重算逐行 UPDATE，开销 ~10 分钟

使用：
  python scripts/ops/backfill_raw_fills_oaod_eet.py --dry-run
  python scripts/ops/backfill_raw_fills_oaod_eet.py --execute
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
import time
from pathlib import Path

# 让脚本能独立运行（不依赖 DataPipeline 安装）
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from DataPipeline.config import Config
from DataPipeline.processing.fill_cleaner import derive_exchange_times

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def count_nulls(conn: sqlite3.Connection) -> dict:
    """统计 oaod/eet NULL 数量。"""
    cur = conn.execute("SELECT COUNT(*) FROM raw_fills")
    total = cur.fetchone()[0]
    cur = conn.execute(
        "SELECT COUNT(*) FROM raw_fills "
        "WHERE order_as_of_date IS NULL OR TRIM(order_as_of_date) = ''"
    )
    oaod_null = cur.fetchone()[0]
    cur = conn.execute(
        "SELECT COUNT(*) FROM raw_fills "
        "WHERE exchange_exec_time IS NULL OR TRIM(exchange_exec_time) = ''"
    )
    eet_null = cur.fetchone()[0]
    return {"total": total, "oaod_null": oaod_null, "eet_null": eet_null}


def fetch_chunks(conn: sqlite3.Connection, columns: list, where: str, chunk_size: int):
    """按 PK 顺序流式获取需要回填的 raw_fills 块。"""
    sql = f"SELECT {','.join(columns)} FROM raw_fills {where} ORDER BY OrderId, RouteId, FillId, source_date"
    return conn.execute(sql)


def backfill(db_path: Path, batch_size: int, dry_run: bool) -> None:
    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"raw_fills.db not found: {db_path}")

    conn = sqlite3.connect(str(db_path), timeout=Config.SQLITE_CONNECT_TIMEOUT_SEC)
    try:
        before = count_nulls(conn)
        logger.info(
            "回填前: total=%d, oaod_null=%d, eet_null=%d",
            before["total"], before["oaod_null"], before["eet_null"],
        )
        if before["oaod_null"] == 0 and before["eet_null"] == 0:
            logger.info("无需回填，全部已有值。")
            return

        # 选 eet NULL 的行（oaod NULL 必然 eet NULL，所以以 eet 为主键）
        target_count = before["eet_null"]
        if target_count == 0:
            return
        logger.info("将处理 %d 行，分批大小 %d", target_count, batch_size)

        # 流式处理：用 (OrderId, RouteId, FillId, source_date) 分块
        # 为减少内存峰值，每 1000 行 batch 处理一次
        pk_cols = ["OrderId", "RouteId", "FillId", "source_date"]
        derive_cols = pk_cols + ["DateTimeOfFill", "Exchange"]
        sql = f"""
            SELECT {','.join(derive_cols)} FROM raw_fills
            WHERE exchange_exec_time IS NULL OR TRIM(exchange_exec_time) = ''
            ORDER BY OrderId, RouteId, FillId, source_date
        """
        cur = conn.execute(sql)

        processed = 0
        updated = 0
        t0 = time.time()
        while True:
            rows = cur.fetchmany(batch_size)
            if not rows:
                break
            df = None
            import pandas as pd
            df = pd.DataFrame(rows, columns=derive_cols)
            # 派生 oaod/eet
            derived = derive_exchange_times(df.copy())
            oaod_vals = derived["order_as_of_date"].fillna("").astype(str).tolist()
            eet_vals = derived["exchange_exec_time"].fillna("").astype(str).tolist()

            # 逐行 UPDATE（小 batch 用 executemany）
            update_rows = []
            for i, r in enumerate(rows):
                pk = (r[0], r[1], r[2], r[3])
                new_oaod = oaod_vals[i]
                new_eet = eet_vals[i]
                # 仅当新值非空时更新（避免覆盖现有值）
                if new_oaod or new_eet:
                    update_rows.append((new_oaod, new_eet, *pk))

            if update_rows:
                if not dry_run:
                    conn.executemany(
                        "UPDATE raw_fills SET order_as_of_date = ?, exchange_exec_time = ? "
                        "WHERE OrderId = ? AND RouteId = ? AND FillId = ? AND source_date = ?",
                        update_rows,
                    )
                    conn.commit()
                updated += len(update_rows)
            processed += len(rows)

            if processed % (batch_size * 50) == 0 or processed == target_count:
                elapsed = time.time() - t0
                rate = processed / elapsed if elapsed > 0 else 0
                eta = (target_count - processed) / rate if rate > 0 else 0
                logger.info(
                    "进度: %d/%d (%.1f%%), 已更新 %d, 速率 %.0f 行/秒, ETA %.0fs",
                    processed, target_count, processed / target_count * 100,
                    updated, rate, eta,
                )

        if not dry_run:
            conn.commit()
        after = count_nulls(conn)
        elapsed = time.time() - t0
        logger.info(
            "回填完成 (%s): 耗时 %.1fs, 处理 %d 行, 更新 %d 行",
            "DRY-RUN" if dry_run else "APPLIED", elapsed, processed, updated,
        )
        logger.info("回填后: total=%d, oaod_null=%d, eet_null=%d",
                    after["total"], after["oaod_null"], after["eet_null"])
    finally:
        conn.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--db-path", type=Path, default=Config.RAW_FILLS_DB,
        help=f"raw_fills.db 路径 (默认: {Config.RAW_FILLS_DB})",
    )
    p.add_argument(
        "--batch-size", type=int, default=1000,
        help="每批处理行数 (默认 1000)",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="只统计不写入",
    )
    p.add_argument(
        "--execute", action="store_true",
        help="实际执行 UPDATE (默认 dry-run)",
    )
    args = p.parse_args()

    dry_run = not args.execute
    if dry_run:
        logger.warning("DRY-RUN 模式: 不会写入数据库")
    else:
        logger.warning("EXECUTE 模式: 将修改 raw_fills.db, 操作前请确认已备份")

    backfill(args.db_path, args.batch_size, dry_run)


if __name__ == "__main__":
    main()
