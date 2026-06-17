"""一次性迁移脚本: 修复 BDIB 集成链路上的 schema 问题。

修复内容:
  1. 初始化 processed_raw_bdib.db 表结构 (4KB 空文件, 0 表)
  2. 给 ticker_registry.db.order_label 补 equ_ticker 列 (Stage 4 写入失败根因)

用法:
  python scripts/fix_bdib_schema_mismatch.py --dry-run   # 预演
  python scripts/fix_bdib_schema_mismatch.py --apply      # 执行修复
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from DataPipeline.config import Config
from DataPipeline.storage.schema.inline_ddl import (
    init_processed_raw_bdib_schema,
)


def _ensure_order_label_equ_ticker(db_path: Path) -> tuple[bool, str]:
    """确保 ticker_registry.db.order_label 包含 equ_ticker 列。"""
    if not db_path.exists():
        return False, f"DB not found: {db_path}"

    conn = sqlite3.connect(str(db_path))
    try:
        # 表存在性检查
        cur = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='order_label'"
        )
        if cur.fetchone() is None:
            return False, "order_label table does not exist"

        # 列存在性检查
        cols = {row[1] for row in conn.execute("PRAGMA table_info(order_label)").fetchall()}
        if "equ_ticker" in cols:
            return True, "equ_ticker column already present (no-op)"

        conn.execute('ALTER TABLE order_label ADD COLUMN "equ_ticker" TEXT')
        conn.commit()
        return True, "ADD COLUMN equ_ticker"
    finally:
        conn.close()


def _ensure_processed_raw_bdib_schema(db_path: Path) -> tuple[bool, str]:
    """初始化 processed_raw_bdib.db 表结构。"""
    if not db_path.exists():
        return False, f"DB not found: {db_path}"

    conn = sqlite3.connect(str(db_path))
    try:
        # 检查是否已有表
        cur = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='processed_raw_bdib'"
        )
        if cur.fetchone() is not None:
            return True, "processed_raw_bdib table already present (no-op)"

        init_processed_raw_bdib_schema(conn)
        return True, "CREATE TABLE processed_raw_bdib + indexes"
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Fix BDIB schema mismatches")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="Show what would change")
    group.add_argument("--apply", action="store_true", help="Apply fixes")
    args = parser.parse_args()

    print("=" * 70)
    print(f"BDIB schema fix — mode: {'DRY-RUN' if args.dry_run else 'APPLY'}")
    print("=" * 70)

    prb_path = Path(Config.PROCESSED_RAW_BDIB_DB)
    tr_path = Path(Config.TICKER_REGISTRY_DB)

    print(f"\n[1/2] processed_raw_bdib.db: {prb_path}")
    print(f"      size: {prb_path.stat().st_size if prb_path.exists() else 'N/A'} bytes")
    ok, msg = _ensure_processed_raw_bdib_schema(prb_path)
    print(f"      result: {msg}")

    print(f"\n[2/2] ticker_registry.db.order_label: {tr_path}")
    print(f"      size: {tr_path.stat().st_size if tr_path.exists() else 'N/A'} bytes")
    ok2, msg2 = _ensure_order_label_equ_ticker(tr_path)
    print(f"      result: {msg2}")

    if args.dry_run:
        print("\n[DRY-RUN] No changes applied.")
    else:
        print("\n[APPLIED] Schema fixes completed.")

    return 0 if (ok and ok2) else 1


if __name__ == "__main__":
    sys.exit(main())
