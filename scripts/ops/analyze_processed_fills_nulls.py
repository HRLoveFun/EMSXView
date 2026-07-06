"""统计 processed_fills.db 中各表每列的 NULL / 空字符串数量。

默认分析主表 processed_fills；可通过命令行参数指定其他表。
所有 SQL 均为只读 SELECT，不修改数据。
"""
import sys

# 强制 UTF-8 stdout，规避 Windows 控制台 cp1252 编码导致的中文/特殊字符报错
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

import sqlite3
from pathlib import Path

DB_PATH = Path(r"c:/Users/hrchen/Documents/EMSXView/CostView/data/processed_fills.db")
TARGET_TABLES = sys.argv[1:] or ["processed_fills"]


def analyze(conn: sqlite3.Connection, table: str) -> None:
    """打印指定表的列级 NULL / 空字符串统计。"""
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    )
    if cur.fetchone() is None:
        print(f"[跳过] 表 {table} 不存在\n")
        return

    cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
    rows_total = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    if rows_total == 0:
        print(f"[空表] {table}\n")
        return

    # 拼接单条聚合 SQL，减少 PRAGMA 查询
    null_parts: list[str] = []
    empty_parts: list[str] = []
    for cid, name, typ, *_ in cols:
        safe = name.replace('"', '""')
        null_parts.append(f'SUM(CASE WHEN "{safe}" IS NULL THEN 1 ELSE 0 END)')
        if typ.upper() == "TEXT":
            empty_parts.append(f'SUM(CASE WHEN "{safe}" = \'\' THEN 1 ELSE 0 END)')
        else:
            empty_parts.append("0")

    sql = f"SELECT {', '.join(null_parts + empty_parts)} FROM {table}"
    row = conn.execute(sql).fetchone()

    print(f"=== {table} ({rows_total:,} 行, {len(cols)} 列) ===")
    print(f"  {'列名':<25} {'类型':<8} {'NULL':>14} {'空字符串':>14} {'合计缺失':>14} {'占比':>9}")
    print("  " + "-" * 90)
    idx = 0
    for cid, name, typ, *_ in cols:
        null_count = int(row[idx])
        idx += 1
        empty_count = int(row[idx]) if typ.upper() == "TEXT" else None
        idx += 1
        if typ.upper() == "TEXT":
            total_missing = null_count + (empty_count or 0)
            pct = f"{total_missing / rows_total * 100:.2f}%"
            print(
                f"  {name:<25} {typ:<8} {null_count:>14,} {empty_count:>14,} "
                f"{total_missing:>14,} {pct:>9}"
            )
        else:
            pct = f"{null_count / rows_total * 100:.2f}%"
            print(
                f"  {name:<25} {typ:<8} {null_count:>14,} {'-':>14} "
                f"{null_count:>14,} {pct:>9}"
            )
    print()


def main() -> None:
    if not DB_PATH.exists():
        print(f"[错误] 数据库文件不存在: {DB_PATH}")
        sys.exit(1)

    print(f"数据库: {DB_PATH}")
    conn = sqlite3.connect(str(DB_PATH))
    try:
        # 全表行数一览
        all_tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        ]
        print("数据库内全部物理表:")
        for t in all_tables:
            n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"  - {t:<32} {n:>14,} 行")
        print()

        for table in TARGET_TABLES:
            analyze(conn, table)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
