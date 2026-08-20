"""CP-1 四项一致性检查（003-tca-core-benchmarks）。

用法:
    python scripts/ops/check_cp1_consistency.py [--dates 20260812 20260707 20260615]
    python scripts/ops/check_cp1_consistency.py --skip-cp1a   # 仅只读 1b/1c/1d

检查项（对应 specs/003-tca-core-benchmarks/plan.md G2 防漂移矩阵）:
- CP-1a: Phase 1 计算后 23 列回归 —— RISK=0 内存重算抽样日期，与生产值对比（容差 1e-6）
- CP-1b: wagner_is ≈ delay + trading + opportunity（容差 0.01）
- CP-1c: truncated=1 行中 temp_impact_30min 非NULL率 ≥ 90%（跨日恢复价格可得率）
- CP-1d: cost_stddev 非NULL率 ≥ pnl_vwap 非NULL率

只读生产库 + 内存重算，不写任何 DB。
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# flag 必须在 import Config 前设置：CORE=1（生产同款）、RISK=0（CP-1a 回退语义）
os.environ["TCA_CORE_BENCHMARKS_ENABLED"] = "1"
os.environ["TCA_RISK_IMPACT_ENABLED"] = "0"

_SCRIPT_DIR = Path(__file__).resolve().parent
_EMSX_ROOT = _SCRIPT_DIR.parent.parent
sys.path.insert(0, str(_EMSX_ROOT))

import numpy as np
import pandas as pd

from DataPipeline.config import Config
from DataPipeline.storage.connection import AccessTier, ConnectionManager
from DataPipeline.storage.facade import DatabaseFacade
from DataPipeline.processing.tca_route_metrics import (
    compute_route_metrics_for_date,
    load_raw_bdib_for_date,
)
from DataPipeline.orchestration.stages_process import _load_daily_summary_for_metrics

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# 23 列 = 现有 18 计算列 + Phase 0 5 列
EXISTING_18 = [
    "fill_count", "fill", "fill_continuous", "fill_close",
    "par_rate", "par_rate_continuous", "par_rate_close",
    "p_avg", "p_avg_continuous", "pnl_vwap", "pnl_vwap_continuous",
    "RPM", "RPM_continuous",
    "pwp_5", "pwp_10", "pwp_15", "pwp_20", "pwp_25",
]
PHASE0_5 = ["p_arrival", "p_close", "arrival_cost_bps", "close_cost_bps", "opportunity_cost"]
CP1A_COLS = EXISTING_18 + PHASE0_5

TABLE = Config.TCA_ROUTE_SUMMARY_TABLE


def _report(section: str) -> None:
    print("\n" + "=" * 72)
    print(f" {section}")
    print("=" * 72)


# ─────────────────────────────────────────────────────────────────────
# CP-1b / CP-1c / CP-1d：生产库只读查询
# ─────────────────────────────────────────────────────────────────────
def check_cp1b(conn) -> None:
    """wagner_is ≈ delay + trading + opportunity（容差 0.01）。"""
    _report("CP-1b Phase 1 分解一致性（容差 0.01）")
    sql = f"""
        SELECT
            SUM(CASE WHEN wagner_is IS NOT NULL THEN 1 ELSE 0 END) AS wagner_nonnull,
            SUM(CASE WHEN wagner_is IS NOT NULL
                     AND ABS(wagner_is - (delay_cost + trading_cost + opportunity_cost)) <= 0.01
                     THEN 1 ELSE 0 END) AS consistent,
            SUM(CASE WHEN wagner_is IS NOT NULL
                     AND ABS(wagner_is - (delay_cost + trading_cost + opportunity_cost)) > 0.01
                     THEN 1 ELSE 0 END) AS inconsistent,
            MAX(CASE WHEN wagner_is IS NOT NULL
                     THEN ABS(wagner_is - (delay_cost + trading_cost + opportunity_cost)) END) AS max_abs_diff
        FROM {TABLE}
    """
    row = conn.execute(sql).fetchone()
    wagner_nonnull, consistent, inconsistent, max_diff = row
    print(f"  wagner_is 非NULL 行数        : {wagner_nonnull}")
    print(f"  分解一致（|diff| ≤ 0.01）    : {consistent}")
    print(f"  分解不一致（|diff| > 0.01）  : {inconsistent}")
    print(f"  最大绝对偏差                : {max_diff}")
    ok = wagner_nonnull and inconsistent == 0
    print(f"  => {'✅ PASS' if ok else '❌ FAIL'}（全部非NULL行满足 wagner_is ≈ delay+trading+opportunity）")


def check_cp1c(conn) -> None:
    """truncated=1 行中 temp_impact_30min_bps 非NULL率 ≥ 90%（跨日恢复价格可得率）。"""
    _report("CP-1c Phase 1 跨日恢复覆盖率（≥ 90%）")
    sql = f"""
        SELECT
            SUM(CASE WHEN recovery_truncated = 1 THEN 1 ELSE 0 END) AS truncated_cnt,
            SUM(CASE WHEN recovery_truncated = 1 AND temp_impact_30min_bps IS NOT NULL
                     THEN 1 ELSE 0 END) AS with_recovery,
            SUM(CASE WHEN recovery_truncated = 1 AND temp_impact_30min_bps IS NULL
                     THEN 1 ELSE 0 END) AS missing_recovery
        FROM {TABLE}
    """
    truncated, with_recovery, missing = conn.execute(sql).fetchone()
    ratio = (with_recovery / truncated * 100.0) if truncated else None
    print(f"  recovery_truncated = 1 行数      : {truncated}")
    print(f"  有跨日恢复价格（30min 非NULL）  : {with_recovery}")
    print(f"  缺跨日恢复价格（30min NULL）    : {missing}")
    print(f"  跨日恢复覆盖率                 : {ratio:.4f}%" if ratio is not None else "  覆盖率: N/A（无截断行）")
    ok = ratio is not None and ratio >= 90.0
    print(f"  => {'✅ PASS' if ok else '❌ FAIL'}（truncated=1 行中 temp_impact_30min 非NULL率 ≥ 90%）")


def check_cp1d(conn) -> None:
    """cost_stddev 非NULL率 ≥ pnl_vwap 非NULL率。"""
    _report("CP-1d Phase 1 风险覆盖率（cost_stddev ≥ pnl_vwap）")
    sql = f"""
        SELECT COUNT(*),
               SUM(CASE WHEN cost_stddev IS NOT NULL THEN 1 ELSE 0 END),
               SUM(CASE WHEN pnl_vwap IS NOT NULL THEN 1 ELSE 0 END)
        FROM {TABLE}
    """
    total, stddev_nonnull, pnl_nonnull = conn.execute(sql).fetchone()
    stddev_rate = stddev_nonnull / total * 100.0 if total else None
    pnl_rate = pnl_nonnull / total * 100.0 if total else None
    print(f"  总行数                      : {total}")
    print(f"  cost_stddev 非NULL率        : {stddev_rate:.4f}%")
    print(f"  pnl_vwap 非NULL率           : {pnl_rate:.4f}%")
    ok = stddev_nonnull >= pnl_nonnull
    print(f"  => {'✅ PASS' if ok else '❌ FAIL'}（cost_stddev 非NULL率 ≥ pnl_vwap 非NULL率）")


def _window_cp1cd(conn) -> None:
    """窗口内（20260501-20260812）CP-1c / CP-1d 参考值。"""
    _report("窗口内参考（20260501 ≤ order_as_of_date ≤ 20260812）")
    sql = f"""
        SELECT COUNT(*),
               SUM(CASE WHEN recovery_truncated = 1 THEN 1 ELSE 0 END),
               SUM(CASE WHEN recovery_truncated = 1 AND temp_impact_30min_bps IS NOT NULL
                        THEN 1 ELSE 0 END),
               SUM(CASE WHEN cost_stddev IS NOT NULL THEN 1 ELSE 0 END),
               SUM(CASE WHEN pnl_vwap IS NOT NULL THEN 1 ELSE 0 END),
               SUM(CASE WHEN wagner_is IS NOT NULL THEN 1 ELSE 0 END)
        FROM {TABLE}
        WHERE order_as_of_date BETWEEN '20260501' AND '20260812'
    """
    total, tr_one, tr_recovered, sd, pnl, wagner = conn.execute(sql).fetchone()
    print(f"  窗口行数                : {total}")
    print(f"  truncated=1 行数        : {tr_one}")
    print(f"  跨日恢复覆盖率          : {tr_recovered / tr_one * 100:.4f}%" if tr_one else "  跨日恢复覆盖率: N/A")
    print(f"  cost_stddev 非NULL率    : {sd / total * 100:.4f}%")
    print(f"  pnl_vwap 非NULL率       : {pnl / total * 100:.4f}%")
    print(f"  wagner_is 非NULL率      : {wagner / total * 100:.4f}%")


# ─────────────────────────────────────────────────────────────────────
# CP-1a：RISK=0 内存重算对比（23 列，容差 1e-6）
# ─────────────────────────────────────────────────────────────────────
def _load_prod_rows(conn, date_str: str) -> pd.DataFrame:
    cols_sql = ", ".join(CP1A_COLS)
    sql = f"""
        SELECT OrderId, RouteId, order_as_of_date, {cols_sql}
        FROM {TABLE} WHERE order_as_of_date = ?
    """
    return pd.read_sql_query(sql, conn.raw_connection, params=[date_str])


def check_cp1a(cm: ConnectionManager, dates: list[str]) -> None:
    _report(f"CP-1a Phase 1 计算后 23 列回归（RISK=0 重算，容差 1e-6）")
    print(f"  flag: CORE=1, RISK=0 | 抽样日期: {dates}")
    db = DatabaseFacade(cm)
    read_conn = cm.get_connection("fill_bdib", AccessTier.READ)

    overall_fail = 0
    for date_str in dates:
        print(f"\n  ── 日期 {date_str} ──")
        # 生产当前值（RISK=1 计算后落库）
        prod = _load_prod_rows(read_conn, date_str)
        if prod.empty:
            print("    生产 tca_route_summary 无该日期数据，跳过")
            continue

        # 数据源加载（与 ComputeRouteMetricsStage 相同路径）
        raw_fills_df = db.raw_fills_read.get_fills_for_date(date_str)
        processed_fills_df = db.fills_read.get_fills_for_date(date_str)
        if processed_fills_df.empty or raw_fills_df.empty:
            print("    processed/raw_fills 为空，跳过")
            continue
        equ_tickers = (
            processed_fills_df["equ_ticker"].dropna().unique().tolist()
            if "equ_ticker" in processed_fills_df.columns else []
        )
        raw_bdib_df = load_raw_bdib_for_date(date_str, equ_tickers=equ_tickers)
        daily_summary_df = _load_daily_summary_for_metrics(cm, date_str, equ_tickers)

        # RISK=0 重算
        computed = compute_route_metrics_for_date(
            raw_fills_df, processed_fills_df, raw_bdib_df, date_str,
            daily_summary_df=daily_summary_df,
        )
        print(f"    生产行数: {len(prod)} | 重算行数: {len(computed)}")

        merged = prod.merge(
            computed[["OrderId", "RouteId"] + CP1A_COLS],
            on=["OrderId", "RouteId"],
            how="inner",
            suffixes=("_prod", "_calc"),
        )
        if len(merged) != len(prod):
            print(f"    ⚠ merge 行数 {len(merged)} ≠ 生产 {len(prod)}（部分路由重算缺失）")

        date_fail = 0
        for col in CP1A_COLS:
            p = merged[f"{col}_prod"]
            c = merged[f"{col}_calc"]
            both_null = p.isna() & c.isna()
            only_prod = p.isna() & ~c.isna()
            only_calc = ~p.isna() & c.isna()
            both_val = ~p.isna() & ~c.isna()
            if col == "fill_count":
                # 整数列：精确比较
                mismatch = both_val & (p.astype("Int64") != c.astype("Int64"))
            else:
                tol = 1e-6 * np.maximum(1.0, c.abs())
                mismatch = both_val & ((p - c).abs() > tol)
            fail_cnt = int(only_prod.sum() + only_calc.sum() + mismatch.sum())
            if fail_cnt:
                date_fail += fail_cnt
                print(f"    ❌ {col}: {fail_cnt} 行不一致（prod-only {int(only_prod.sum())}, "
                      f"calc-only {int(only_calc.sum())}, 数值超差 {int(mismatch.sum())}）")
        if date_fail == 0:
            print(f"    ✅ 23 列全部一致（{len(merged)} 行 × 23 列，容差 1e-6）")
        overall_fail += date_fail

    print(f"\n  => {'✅ PASS' if overall_fail == 0 else '❌ FAIL'}（CP-1a 总体 {'通过' if overall_fail == 0 else f'{overall_fail} 处不一致'}）")


def main() -> int:
    parser = argparse.ArgumentParser(description="CP-1 四项一致性检查")
    parser.add_argument(
        "--dates", nargs="+",
        default=["20260812", "20260707", "20260615"],
        help="CP-1a 抽样日期（默认 20260812 20260707 20260615）",
    )
    parser.add_argument(
        "--skip-cp1a", action="store_true",
        help="跳过 CP-1a 重算（仅执行只读 1b/1c/1d）",
    )
    args = parser.parse_args()

    print(f"数据库: {Config.FILL_BDIB_DB}")
    print(f"表名  : {TABLE}")

    cm = ConnectionManager()
    conn = cm.get_connection("fill_bdib", AccessTier.READ)
    try:
        check_cp1b(conn)
        check_cp1c(conn)
        check_cp1d(conn)
        _window_cp1cd(conn)
    finally:
        conn.close()

    if not args.skip_cp1a:
        check_cp1a(cm, args.dates)

    return 0


if __name__ == "__main__":
    sys.exit(main())
