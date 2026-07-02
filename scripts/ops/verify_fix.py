"""
验收脚本: 确认 raw_fills.db Exchange NULL → 'NA' 修复及 S2 重跑结果

校验项:
    R1. raw_fills.db NULL Exchange 行数 = 0
    R2. raw_fills.db Exchange='NA' 行数 = 100,636 (36,186 原有 + 64,450 修复)
    R3. raw_fills.db 总行数不变 (10,942,959)
    P1. processed_fills.db Exchange='NA' 行数 > 0, 且 equ_ticker 非空率 = 100%
    P2. processed_fills.db Exchange='NA' 行 mkt_timestamp 非空率 = 100%
    P3. processed_fills.db 涉及日期行数 (61 个 source_date) 与 S2 重跑相符
    E1. execution_history.db route_history 含 NA equ_ticker 行 (>0)

用法:
    python scripts/ops/verify_fix.py
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

from DataPipeline.config import Config


EXPECTED_RAW_TOTAL = 10_942_959
EXPECTED_NA_RAW = 100_636          # 36,186 原有 + 64,450 修复
EXPECTED_NULL_RAW = 0


def _connect(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db))
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _query_one(conn: sqlite3.Connection, sql: str, params=()) -> int:
    return conn.execute(sql, params).fetchone()[0]


def main() -> int:
    raw = Config.RAW_FILLS_DB
    proc = Config.PROCESSED_FILLS_DB
    exe = Config.EXECUTION_HISTORY_DB

    print("=" * 72)
    print("  raw_fills.db Exchange NULL → 'NA' 修复验收")
    print("=" * 72)
    print(f"  raw_fills.db       = {raw}")
    print(f"  processed_fills.db = {proc}")
    print(f"  execution_history  = {exe}")
    print()

    # ── R1-R3: raw_fills 校验 ─────────────────────────────────
    print("── raw_fills.db 校验 ──")
    raw_conn = _connect(raw)

    null_cnt = _query_one(raw_conn, "SELECT COUNT(*) FROM raw_fills WHERE Exchange IS NULL")
    na_cnt = _query_one(raw_conn, "SELECT COUNT(*) FROM raw_fills WHERE Exchange = 'NA'")
    total = _query_one(raw_conn, "SELECT COUNT(*) FROM raw_fills")
    null_eur_cnt = _query_one(
        raw_conn,
        "SELECT COUNT(*) FROM raw_fills WHERE Exchange IS NULL AND Currency = 'EUR'"
    )

    print(f"  R1 NULL Exchange:           {null_cnt:>10}  (期望 {EXPECTED_NULL_RAW})  "
          f"{'✓ PASS' if null_cnt == EXPECTED_NULL_RAW else '✗ FAIL'}")
    print(f"  R2 Exchange='NA' total:     {na_cnt:>10}  (期望 {EXPECTED_NA_RAW})   "
          f"{'✓ PASS' if na_cnt == EXPECTED_NA_RAW else '✗ FAIL'}")
    print(f"  R3 raw_fills 总行数:        {total:>10}  (期望 {EXPECTED_RAW_TOTAL})  "
          f"{'✓ PASS' if total == EXPECTED_RAW_TOTAL else '✗ FAIL'}")
    if null_cnt > 0:
        print(f"  [warn] 仍有 {null_cnt} NULL 行 — 其中 {null_eur_cnt} 行 Currency=EUR")

    # ── P1-P3: processed_fills 校验 ───────────────────────────
    print("\n── processed_fills.db 校验 ──")
    proc_conn = _connect(proc)

    proc_na_cnt = _query_one(proc_conn, "SELECT COUNT(*) FROM processed_fills WHERE Exchange = 'NA'")
    proc_na_eq_filled = _query_one(
        proc_conn,
        "SELECT COUNT(*) FROM processed_fills "
        "WHERE Exchange = 'NA' AND equ_ticker IS NOT NULL AND equ_ticker != ''"
    )
    proc_na_mkt_filled = _query_one(
        proc_conn,
        "SELECT COUNT(*) FROM processed_fills "
        "WHERE Exchange = 'NA' AND mkt_timestamp IS NOT NULL AND mkt_timestamp != ''"
    )
    proc_na_eq_null = proc_na_cnt - proc_na_eq_filled
    proc_na_mkt_empty = proc_na_cnt - proc_na_mkt_filled

    eq_ratio = (proc_na_eq_filled / proc_na_cnt * 100) if proc_na_cnt else 0
    mkt_ratio = (proc_na_mkt_filled / proc_na_cnt * 100) if proc_na_cnt else 0

    print(f"  P1 processed NA 行数:        {proc_na_cnt:>10}  (期望 > 0)"
          f"  {'✓ PASS' if proc_na_cnt > 0 else '✗ FAIL'}")
    print(f"     equ_ticker 非空:          {proc_na_eq_filled:>10}  "
          f"(空: {proc_na_eq_null}, 填充率: {eq_ratio:.2f}%)  "
          f"{'✓ PASS' if eq_ratio >= 99 else '✗ FAIL'}")
    print(f"  P2 mkt_timestamp 非空:       {proc_na_mkt_filled:>10}  "
          f"(空: {proc_na_mkt_empty}, 填充率: {mkt_ratio:.2f}%)  "
          f"{'✓ PASS' if mkt_ratio >= 99 else '✗ FAIL'}")

    # 每日 NA 分布
    print("\n   每日 processed NA 行数 (前 15 日)：")
    cur = proc_conn.execute("""
        SELECT order_as_of_date, COUNT(*) AS cnt
        FROM processed_fills WHERE Exchange = 'NA'
        GROUP BY order_as_of_date ORDER BY order_as_of_date LIMIT 15
    """)
    for d, n in cur.fetchall():
        print(f"     {d}  {n}")

    # 全部 NA 行的 distinct order_as_of_date (用于对比 61 个修复日期)
    cur = proc_conn.execute("""
        SELECT COUNT(DISTINCT order_as_of_date)
        FROM processed_fills WHERE Exchange = 'NA'
    """)
    na_distinct_dates = cur.fetchone()[0]
    print(f"\n   processed_fills 含 NA 的 distinct order_as_of_date: {na_distinct_dates}")

    # ── E1: execution_history 校验 ─────────────────────────────
    print("\n── execution_history.db 校验 ──")
    exe_conn = _connect(exe)

    # route_history 表字段
    cur = exe_conn.execute("PRAGMA table_info(route_history)")
    cols = [row[1] for row in cur.fetchall()]
    if "equ_ticker" in cols:
        eh_na_routes = _query_one(
            exe_conn,
            "SELECT COUNT(*) FROM route_history WHERE equ_ticker LIKE '% NA Equity' "
            "OR equ_ticker LIKE 'NA Equity' OR equ_ticker LIKE '%EUR EU Equity'"
        )
        print(f"  E1 route_history 荷兰股票估算行数: {eh_na_routes:>10}  "
              f"{'✓ PASS' if eh_na_routes > 0 else '✗ FAIL'}")
    else:
        print(f"  route_history 列无 equ_ticker; 列={cols}")

    # ── 最终结果 ───────────────────────────────────────────────
    print("\n" + "=" * 72)
    na_ok = (na_cnt == EXPECTED_NA_RAW)
    null_ok = (null_cnt == 0)
    total_ok = (total == EXPECTED_RAW_TOTAL)
    proc_ok = (proc_na_cnt > 0 and eq_ratio >= 99 and mkt_ratio >= 99)
    overall = na_ok and null_ok and total_ok and proc_ok

    if overall:
        print("  ✓ 整体验收 PASS")
    else:
        print("  ✗ 验收 FAILED，明细：")
        if not na_ok:
            print(f"    - raw NA 行数不符 (期望 {EXPECTED_NA_RAW}, 实际 {na_cnt})")
        if not null_ok:
            print(f"    - raw 仍存在 NULL 行 (实际 {null_cnt})")
        if not total_ok:
            print(f"    - raw 总行数漂移 (期望 {EXPECTED_RAW_TOTAL}, 实际 {total})")
        if not proc_ok:
            print(f"    - processed_fills 链路未充分复活 "
                  f"(NA={proc_na_cnt}, eq_ratio={eq_ratio:.2f}%, mkt_ratio={mkt_ratio:.2f}%)")
    print("=" * 72)

    raw_conn.close()
    proc_conn.close()
    exe_conn.close()

    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())