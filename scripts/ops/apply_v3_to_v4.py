"""应用 raw_fills v3 -> v4 migration (oaod NOT NULL 约束)。

执行前校验: oaod NULL/空串数 = 0 (P1 回填已完成)
"""
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from DataPipeline.config import Config
from DataPipeline.storage.schema.migration_framework import MigrationRunner


def precheck(db_path: Path) -> None:
    """前置校验: oaod NULL/空串必须为 0。"""
    conn = sqlite3.connect(str(db_path))
    try:
        r = conn.execute(
            "SELECT COUNT(*) FROM raw_fills "
            "WHERE order_as_of_date IS NULL OR TRIM(order_as_of_date) = ''"
        ).fetchone()
        n_null = r[0]
        if n_null > 0:
            raise RuntimeError(
                f"oaod 仍有 {n_null} 行 NULL/空串, 必须先运行 "
                f"scripts/ops/backfill_raw_fills_oaod_eet.py --execute"
            )
        print(f"✓ 前置校验通过: oaod NULL/空串 = 0")
    finally:
        conn.close()


def main():
    runner = MigrationRunner.discover()
    db_path = runner._plans["raw_fills"].db_path
    print(f"raw_fills db: {db_path}")
    precheck(db_path)
    cur = runner.get_current_version("raw_fills")
    print(f"当前 user_version = {cur}, 期望 v4")
    if cur == 4:
        print("已是 v4, 无需迁移")
        return
    t0 = time.time()
    ver = runner.migrate("raw_fills")
    print(f"迁移完成: v{cur} -> v{ver}, 耗时 {time.time()-t0:.1f}s")

    # 验收
    conn = sqlite3.connect(str(db_path))
    try:
        # 1. user_version
        r = conn.execute("PRAGMA user_version").fetchone()
        print(f"✓ user_version = {r[0]}")
        # 2. PK 列
        cols = [row[1] for row in conn.execute("PRAGMA table_info(raw_fills)").fetchall()
                if row[5] > 0]
        print(f"✓ PK = {cols}")
        # 3. order_as_of_date NOT NULL
        r = conn.execute(
            "SELECT [notnull] FROM pragma_table_info('raw_fills') "
            "WHERE name='order_as_of_date'"
        ).fetchone()
        print(f"✓ order_as_of_date notnull = {r[0]}")
        # 4. oaod 仍有 NULL?
        r = conn.execute(
            "SELECT COUNT(*) FROM raw_fills "
            "WHERE order_as_of_date IS NULL OR TRIM(order_as_of_date) = ''"
        ).fetchone()
        print(f"✓ oaod NULL/空串 = {r[0]}")
        # 5. 总行数
        r = conn.execute("SELECT COUNT(*) FROM raw_fills").fetchone()
        print(f"✓ total rows = {r[0]:,}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
