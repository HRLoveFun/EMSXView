"""回填 fill_bdib.ccy_ticker 与 fx_rate 的 NULL 缺口（L4d）。

背景（2026-08-28）：fill_bdib 中 68,724 行（1,931 个 OrderId，集中於
20260824~20260825 两个交易日）的 ccy_ticker 为 NULL，导致 fx_rate 同为 NULL，
整体 fx_rate 覆盖率被拖到 98.8%。经核查，这些订单在 raw_fills 中 100% 都有
Currency 值（0 缺失），缺口纯粹发生在「raw_fills.Currency → fill_bdib.ccy_ticker」
推导链，且呈整批失败特征（疑似该批次 ingestion 的 ccy enrichment 被跳过）。

方案：
  1. 从 raw_fills.Currency（经 OrderId 关联）反推 fill_bdib.ccy_ticker：
       - USD            -> 'USD Curncy'
       - 其他（含 GBp/ZAr/ILs 等异常大小写）-> 'USD' + Currency.upper() + ' Curncy'
     ccy_ticker 大小写归一化后与 fx_rates 表键（如 USDGBP CURNCY）UPPER 匹配，
     复用既有的 add_currency_columns 推导约定，与已正常入库的 6 万+ GBp 行行为一致。
  2. 回填 fx_rate：
       - 'USD Curncy' -> 直接置 1.0（USD 无需换算）
       - 非 USD -> 查 fx_rates 表精确命中 (UPPER(ccy), order_as_of_date)；
         缺失则回退 ≤ 目标日期 最近已知汇率。29/31 个 (ccy,日期) 组合已实测有汇率。
  3. （默认开启）顺带用 fill_bdib 按 (OrderId,RouteId,order_as_of_date) fill_volume
     加权聚合，回填 tca_route_summary.fx_rate 的 NULL 行，使报告层 notional_usd /
     fx_coverage 对受影响订单一致。

约束（对齐 test_tca_fx_backfill 契约）：
  - 仅 UPDATE ccy_ticker IS NULL（或对应 tca fx_rate IS NULL）的行，已填充行不动。
  - 写入前自动备份 fill_bdib.db（tca_route_summary 同库，一次备份覆盖）。
  - 幂等：可重复运行，已填充行不受影响。

用法：
    # 备份 + 预览（推荐先跑）
    python scripts/ops/backfill_ccy_fx_for_null.py --dry-run

    # 执行回填（含 tca_route_summary）
    python scripts/ops/backfill_ccy_fx_for_null.py

    # 仅回填 fill_bdib，不动 tca_route_summary
    python scripts/ops/backfill_ccy_fx_for_null.py --no-tca

    # 指定受影响日期范围（缺省=全部 ccy_ticker 为 NULL 的行）
    python scripts/ops/backfill_ccy_fx_for_null.py --start-date 20260824 --end-date 20260825
"""
from __future__ import annotations

import argparse
import logging
import shutil
import sqlite3
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("backfill_ccy_fx_for_null")

_SCRIPT_DIR = Path(__file__).resolve().parent
_ROOT = _SCRIPT_DIR.parent.parent
sys.path.insert(0, str(_ROOT))

from DataPipeline.config import Config  # noqa: E402


def _backup(db_path: Path) -> Path:
    """回填前备份 fill_bdib.db（tca_route_summary 同库，一次覆盖）。"""
    ts = time.strftime("%Y%m%d_%H%M%S")
    backup = db_path.parent / "backups" / f"fill_bdib_pre_ccyfxbackfill_{ts}.db"
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(db_path), str(backup))
    logger.info("已备份 fill_bdib.db -> %s", backup)
    return backup


def _derive_ccy_sql() -> str:
    """ccy_ticker 反推表达式（大小写归一化，USD 特例）。"""
    return (
        "CASE WHEN r.Currency = 'USD' THEN 'USD Curncy' "
        "ELSE 'USD' || UPPER(r.Currency) || ' Curncy' END"
    )


def _step1_ccy(conn: sqlite3.Connection, affected: set, dry_run: bool) -> tuple[int, int]:
    """回填 ccy_ticker：从 raw_fills 经 OrderId 反推。返回 (匹配行数, 写回行数)。"""
    conn.execute("ATTACH ? AS raw", (str(Config.RAW_FILLS_DB),))
    matched = conn.execute(
        f"""
        SELECT COUNT(*) FROM {Config.FILL_BDIB_TABLE} f
        WHERE f.ccy_ticker IS NULL
          AND EXISTS (SELECT 1 FROM raw.raw_fills r WHERE r.OrderId = f.OrderId)
        """
    ).fetchone()[0]

    written = 0
    if not dry_run and matched:
        conn.execute(
            f"""
            UPDATE {Config.FILL_BDIB_TABLE}
            SET ccy_ticker = (
                SELECT {_derive_ccy_sql()}
                FROM raw.raw_fills r
                WHERE r.OrderId = {Config.FILL_BDIB_TABLE}.OrderId
                LIMIT 1
            )
            WHERE ccy_ticker IS NULL
              AND OrderId IN (SELECT OrderId FROM raw.raw_fills)
            """
        )
        conn.commit()
        if affected:
            ph = ",".join("?" * len(affected))
            written = conn.execute(
                f"SELECT COUNT(*) FROM {Config.FILL_BDIB_TABLE} "
                f"WHERE OrderId IN ({ph}) AND ccy_ticker IS NOT NULL",
                tuple(affected),
            ).fetchone()[0]
    conn.execute("DETACH raw")
    return matched, written


def _step2_fx(conn: sqlite3.Connection, affected: set, dry_run: bool) -> tuple[int, int, int]:
    """回填 fx_rate：USD=1.0，非 USD 查 fx_rates（精确+≤日期回退）。"""
    tgt = Config.FILL_BDIB_TABLE

    # USD 直接置 1.0
    usd_matched = conn.execute(
        f"SELECT COUNT(*) FROM {tgt} WHERE ccy_ticker='USD Curncy' AND fx_rate IS NULL"
    ).fetchone()[0]
    if not dry_run and usd_matched:
        conn.execute(
            f"UPDATE {tgt} SET fx_rate=1.0 WHERE ccy_ticker='USD Curncy' AND fx_rate IS NULL"
        )
        conn.commit()

    # 非 USD：精确命中当天
    exact_sql = f"""
        UPDATE {tgt}
        SET fx_rate = (
            SELECT f.fx_rate FROM fx_rates f
            WHERE UPPER(f.ccy_ticker) = UPPER({tgt}.ccy_ticker)
              AND f.order_as_of_date = {tgt}.order_as_of_date
            LIMIT 1
        )
        WHERE ccy_ticker IS NOT NULL AND ccy_ticker <> 'USD Curncy'
          AND fx_rate IS NULL
          AND EXISTS (
              SELECT 1 FROM fx_rates f
              WHERE UPPER(f.ccy_ticker) = UPPER({tgt}.ccy_ticker)
                AND f.order_as_of_date = {tgt}.order_as_of_date
          )
    """
    exact_fill = 0
    if not dry_run:
        cur = conn.execute(exact_sql)
        conn.commit()
        exact_fill = cur.rowcount

    # 非 USD：回退 ≤ 目标日期 最近已知汇率
    fb_sql = f"""
        UPDATE {tgt}
        SET fx_rate = (
            SELECT f.fx_rate FROM fx_rates f
            WHERE UPPER(f.ccy_ticker) = UPPER({tgt}.ccy_ticker)
              AND f.order_as_of_date <= {tgt}.order_as_of_date
            ORDER BY f.order_as_of_date DESC LIMIT 1
        )
        WHERE ccy_ticker IS NOT NULL AND ccy_ticker <> 'USD Curncy'
          AND fx_rate IS NULL
          AND EXISTS (
              SELECT 1 FROM fx_rates f
              WHERE UPPER(f.ccy_ticker) = UPPER({tgt}.ccy_ticker)
                AND f.order_as_of_date <= {tgt}.order_as_of_date
          )
    """
    fb_fill = 0
    if not dry_run:
        cur = conn.execute(fb_sql)
        conn.commit()
        fb_fill = cur.rowcount

    still = conn.execute(
        f"SELECT COUNT(*) FROM {tgt} WHERE ccy_ticker IS NOT NULL "
        f"AND ccy_ticker <> 'USD Curncy' AND fx_rate IS NULL"
    ).fetchone()[0]
    return usd_matched + exact_fill + fb_fill, exact_fill + fb_fill, still


def _step3_tca(conn: sqlite3.Connection, affected: set, dry_run: bool) -> tuple[int, int]:
    """顺带用 fill_bdib 加权聚合回填 tca_route_summary.fx_rate 的 NULL 行。"""
    if not affected:
        return 0, 0
    placeholders = ",".join("?" * len(affected))
    tgt = Config.TCA_ROUTE_SUMMARY_TABLE
    t = Config.FILL_BDIB_TABLE

    fillable = conn.execute(
        f"""
        SELECT COUNT(*) FROM {tgt}
        WHERE fx_rate IS NULL AND OrderId IN ({placeholders})
          AND EXISTS (
              SELECT 1 FROM {t} b
              WHERE b.OrderId = {tgt}.OrderId AND b.RouteId = {tgt}.RouteId
                AND b.order_as_of_date = {tgt}.order_as_of_date AND b.fx_rate IS NOT NULL
          )
        """, tuple(affected)
    ).fetchone()[0]
    if not fillable:
        return fillable, 0
    if dry_run:
        # 回滚方式模拟，避免持久化（依赖 Step1/Step2 已在 fill_bdib 落库）
        conn.execute("BEGIN")
        cur = conn.execute(
            f"""
            UPDATE {tgt}
            SET fx_rate = (
                SELECT SUM(b.fill_volume * b.fx_rate) / NULLIF(SUM(b.fill_volume), 0)
                FROM {t} b
                WHERE b.OrderId = {tgt}.OrderId AND b.RouteId = {tgt}.RouteId
                  AND b.order_as_of_date = {tgt}.order_as_of_date AND b.fx_rate IS NOT NULL
            )
            WHERE fx_rate IS NULL AND OrderId IN ({placeholders})
              AND EXISTS (
                  SELECT 1 FROM {t} b
                  WHERE b.OrderId = {tgt}.OrderId AND b.RouteId = {tgt}.RouteId
                    AND b.order_as_of_date = {tgt}.order_as_of_date AND b.fx_rate IS NOT NULL
              )
            """, tuple(affected)
        )
        written = cur.rowcount
        conn.rollback()
        return fillable, written

    cur = conn.execute(
        f"""
        UPDATE {tgt}
        SET fx_rate = (
            SELECT SUM(b.fill_volume * b.fx_rate) / NULLIF(SUM(b.fill_volume), 0)
            FROM {t} b
            WHERE b.OrderId = {tgt}.OrderId AND b.RouteId = {tgt}.RouteId
              AND b.order_as_of_date = {tgt}.order_as_of_date AND b.fx_rate IS NOT NULL
        )
        WHERE fx_rate IS NULL AND OrderId IN ({placeholders})
          AND EXISTS (
              SELECT 1 FROM {t} b
              WHERE b.OrderId = {tgt}.OrderId AND b.RouteId = {tgt}.RouteId
                AND b.order_as_of_date = {tgt}.order_as_of_date AND b.fx_rate IS NOT NULL
          )
        """, tuple(affected)
    )
    conn.commit()
    still = conn.execute(
        f"SELECT COUNT(*) FROM {tgt} WHERE fx_rate IS NULL AND OrderId IN ({placeholders})",
        tuple(affected),
    ).fetchone()[0]
    return fillable, fillable - still


def main() -> int:
    parser = argparse.ArgumentParser(description="回填 fill_bdib ccy_ticker/fx_rate 的 NULL 缺口")
    parser.add_argument("--dry-run", action="store_true", help="仅预览不写入（在临时副本上模拟）")
    parser.add_argument("--start-date", default=None, help="受影响起始日 YYYYMMDD（限定 ccy 回填范围）")
    parser.add_argument("--end-date", default=None, help="受影响结束日 YYYYMMDD")
    parser.add_argument("--no-tca", action="store_true", help="跳过 tca_route_summary 回填")
    parser.add_argument("--no-backup", action="store_true", help="跳过备份（不推荐）")
    args = parser.parse_args()

    real_db = Config.FILL_BDIB_DB
    if args.dry_run:
        # 在临时副本上真实执行各步骤（含 Step1/Step2 落库），使 Step3 预览准确，结束即丢弃
        import tempfile
        tmp = Path(tempfile.gettempdir()) / "fill_bdib_dryrun_copy.db"
        if tmp.exists():
            tmp.unlink()
        shutil.copy2(str(real_db), str(tmp))
        Config.FILL_BDIB_DB = tmp
        working_db = tmp
        logger.info("DRY-RUN: 在临时副本 %s 上模拟执行，真实数据库不会被改动", tmp)
    else:
        working_db = real_db
        if not args.no_backup:
            _backup(real_db)

    conn = sqlite3.connect(str(working_db))
    try:
        # 受影响 OrderId 集合（回填前锁定，用于 tca 步骤与校验）
        where = ["ccy_ticker IS NULL"]
        params: list = []
        if args.start_date:
            where.append("order_as_of_date >= ?"); params.append(args.start_date)
        if args.end_date:
            where.append("order_as_of_date <= ?"); params.append(args.end_date)
        affected = {
            r[0] for r in conn.execute(
                f"SELECT DISTINCT OrderId FROM {Config.FILL_BDIB_TABLE} WHERE {' AND '.join(where)}",
                params,
            )
        }
        logger.info("受影响 OrderId 数: %d（ccy_ticker 为 NULL）", len(affected))

        # dry-run 在副本上真实写入以串联各步；非 dry-run 直接写入真实库
        m_ccy, w_ccy = _step1_ccy(conn, affected, dry_run=False)
        logger.info("Step1 ccy_ticker: 可回填 %d 行，已写 %d", m_ccy, w_ccy)

        fx_fill, fx_non_usd, fx_still = _step2_fx(conn, affected, dry_run=False)
        logger.info("Step2 fx_rate: 回填 %d 行（非USD精确+回退 %d），仍缺失(非USD) %d",
                    fx_fill, fx_non_usd, fx_still)

        if not args.no_tca:
            tca_fill, tca_done = _step3_tca(conn, affected, dry_run=False)
            logger.info("Step3 tca_route_summary: 可回填 %d 行，已写 %d", tca_fill, tca_done)

        # 校验：受影响范围内剩余缺口
        if affected:
            ph = ",".join("?" * len(affected))
            ccy_null, fx_null = conn.execute(
                f"SELECT SUM(ccy_ticker IS NULL), SUM(fx_rate IS NULL) "
                f"FROM {Config.FILL_BDIB_TABLE} WHERE OrderId IN ({ph})", tuple(affected)
            ).fetchone()
            logger.info("校验 fill_bdib（受影响订单）：ccy_null=%s fx_null=%s",
                        int(ccy_null or 0), int(fx_null or 0))
    finally:
        conn.close()
        if args.dry_run and Path(str(working_db)).exists():
            Path(str(working_db)).unlink()
            logger.info("DRY-RUN: 已删除临时副本")
    return 0


if __name__ == "__main__":
    sys.exit(main())
