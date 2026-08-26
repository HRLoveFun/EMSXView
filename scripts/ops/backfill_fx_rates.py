"""fx_rates 汇率表回填/刷新脚本（fx-rate-persistence）。

两种模式（互斥）：
  --seed      从 fill_bdib 历史数据反推汇率（source='fill_bdib_seed'，
              零 Bloomberg 调用）。已有 'bloomberg' 来源的键不覆盖。
  --refetch   按日期范围从 Bloomberg 重拉刷新（先删旧行强制 miss，
              再走正常拉取链落表，幂等 latest-wins）。

seed 排除规则：
  - USD（'USD Curncy' / 'USD' / 空值）—— fetcher 本就不落表
  - fx_rate = 1.0 的非 USD 行 —— 旧版 1.0 兜底残留，不进真相源

用法：
    # 预览 seed 结果（不写入）
    python backfill_fx_rates.py --seed --dry-run

    # 执行 seed
    python backfill_fx_rates.py --seed

    # 重拉 2026 Q1 全部币种（币种缺省从 fill_bdib 推导）
    python backfill_fx_rates.py --refetch --start-date 20260101 --end-date 20260331

    # 仅重拉指定币种
    python backfill_fx_rates.py --refetch --start-date 20260101 --end-date 20260331 --ccy "USDJPY Curncy"
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── 路径设置 ──
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from DataPipeline.acquisition.fx_fetcher import _is_usd, fetch_fx_rate_for_ccy
from DataPipeline.common.quota_pause import is_quota_paused
from DataPipeline.config import Config
from DataPipeline.storage.schema.inline_ddl import init_fx_rates_schema

logger = logging.getLogger(__name__)

_SEED_SOURCE = "fill_bdib_seed"


def _open_fill_bdib() -> sqlite3.Connection:
    """打开 fill_bdib.db 并确保 fx_rates 表存在（幂等）。"""
    db_path = Config.FILL_BDIB_DB
    if not db_path.exists():
        logger.error("fill_bdib.db 不存在: %s", db_path)
        sys.exit(1)
    conn = sqlite3.connect(str(db_path), timeout=30)
    init_fx_rates_schema(conn)
    return conn


# ── seed 模式 ───────────────────────────────────────────────────────────────


def _collect_seed_rows(conn: sqlite3.Connection) -> List[Tuple[str, str, float]]:
    """从 fill_bdib 反推 (ccy_ticker, order_as_of_date, fx_rate) 种子行。

    同 (ccy, date) 出现多个 fx_rate（历史重拉残留）时取覆盖行数最多的
    值（最近一次全量重写的代理）并告警；USD 与 1.0 兜底残留排除。
    """
    rows = conn.execute(
        f"SELECT ccy_ticker, order_as_of_date, fx_rate, COUNT(*) AS n "
        f"FROM {Config.FILL_BDIB_TABLE} "
        f"WHERE fx_rate IS NOT NULL AND fx_rate > 0 AND fx_rate != 1.0 "
        f"  AND ccy_ticker IS NOT NULL AND TRIM(ccy_ticker) != '' "
        f"GROUP BY ccy_ticker, order_as_of_date, fx_rate "
        f"ORDER BY ccy_ticker, order_as_of_date, n DESC"
    ).fetchall()

    # (ccy, date) -> (fx_rate, 覆盖行数, 不同值个数)；首行即覆盖最多
    best: Dict[Tuple[str, str], Tuple[float, int, int]] = {}
    for ccy, oad, rate, n in rows:
        ccy_str = str(ccy).strip().upper()
        if _is_usd(ccy_str):
            continue
        key = (ccy_str, str(oad))
        if key in best:
            rate0, n0, cnt = best[key]
            best[key] = (rate0, n0, cnt + 1)
        else:
            best[key] = (float(rate), int(n), 1)

    result: List[Tuple[str, str, float]] = []
    for (ccy, oad), (rate, n, cnt) in sorted(best.items()):
        if cnt > 1:
            logger.warning(
                "seed 多值异常: %s @ %s 有 %d 个不同汇率，取覆盖 %d 行的值 %s",
                ccy, oad, cnt, n, rate,
            )
        result.append((ccy, oad, rate))
    return result


def _apply_seed(
    conn: sqlite3.Connection,
    rows: List[Tuple[str, str, float]],
    dry_run: bool,
) -> Tuple[int, int]:
    """写入种子行：跳过已有 'bloomberg' 来源的键，其余 REPLACE。返回 (写入, 跳过)。"""
    existing = {
        (str(r[0]).strip().upper(), str(r[1])): str(r[2])
        for r in conn.execute(
            f"SELECT ccy_ticker, order_as_of_date, source FROM {Config.FX_RATES_TABLE}"
        ).fetchall()
    }
    written = skipped = 0
    for ccy, oad, rate in rows:
        if existing.get((ccy, oad)) == "bloomberg":
            skipped += 1
            continue
        if not dry_run:
            conn.execute(
                f"INSERT OR REPLACE INTO {Config.FX_RATES_TABLE} "
                "(ccy_ticker, order_as_of_date, fx_rate, px_last, source) "
                "VALUES (?, ?, ?, NULL, ?)",
                (ccy, oad, rate, _SEED_SOURCE),
            )
        written += 1
    if not dry_run:
        conn.commit()
    return written, skipped


# ── refetch 模式 ────────────────────────────────────────────────────────────


def _expand_weekdays(start: date, end: date) -> List[str]:
    """展开 [start, end] 为工作日 YYYYMMDD 列表（FX 周末无报价）。"""
    out: List[str] = []
    cur = start
    while cur <= end:
        if cur.weekday() < 5:
            out.append(cur.strftime("%Y%m%d"))
        cur += timedelta(days=1)
    return out


def _collect_refetch_ccys(
    conn: sqlite3.Connection, ccy_args: Optional[List[str]],
) -> List[str]:
    """refetch 币种：显式指定优先（规范化大写），缺省从 fill_bdib DISTINCT 推导。"""
    if ccy_args:
        ccys = [c.upper().strip() for c in ccy_args if c and c.strip()]
        return [c for c in ccys if not _is_usd(c)]
    rows = conn.execute(
        f"SELECT DISTINCT ccy_ticker FROM {Config.FILL_BDIB_TABLE} "
        f"WHERE ccy_ticker IS NOT NULL AND TRIM(ccy_ticker) != ''"
    ).fetchall()
    return sorted({str(r[0]).strip().upper() for r in rows if not _is_usd(str(r[0]))})


def _delete_range_rows(
    conn: sqlite3.Connection, start: str, end: str, ccys: List[str],
) -> int:
    """删除范围内目标币种的旧行，强制拉取链走 Bloomberg 而非表命中。"""
    placeholders = ", ".join(["?"] * len(ccys))
    deleted = conn.execute(
        f"DELETE FROM {Config.FX_RATES_TABLE} "
        f"WHERE order_as_of_date BETWEEN ? AND ? AND ccy_ticker IN ({placeholders})",
        [start, end, *ccys],
    ).rowcount
    conn.commit()
    return deleted


def _run_refetch(
    conn: sqlite3.Connection,
    start: str, end: str, ccys: List[str], dry_run: bool,
) -> None:
    """按日期范围逐币种重拉 Bloomberg 并落表（幂等 REPLACE，latest-wins）。"""
    from DataPipeline.storage.repositories.fx_rates import SqliteFxRatesRepository

    dates = _expand_weekdays(
        datetime.strptime(start, "%Y%m%d").date(),
        datetime.strptime(end, "%Y%m%d").date(),
    )
    logger.info("refetch 计划: %d 个工作日 × %d 个币种 = %d 次拉取",
                len(dates), len(ccys), len(dates) * len(ccys))
    if dry_run:
        for c in ccys:
            logger.info("  [dry-run] 币种: %s", c)
        logger.info("[dry-run] 仅预览，不调用 Bloomberg、不写入。")
        return

    deleted = _delete_range_rows(conn, start, end, ccys)
    logger.info("已删除范围内目标币种旧行 %d（强制重拉）", deleted)

    repo = SqliteFxRatesRepository()
    written = 0
    for date_str in dates:
        before = repo.get_rates_for_date(ccys, date_str)
        for ccy in ccys:
            fetch_fx_rate_for_ccy(ccy, date_str, fx_repo=repo)
        after = repo.get_rates_for_date(ccys, date_str)
        changed = sum(1 for k, v in after.items() if before.get(k) != v)
        written += changed
        logger.info("  %s: 新增/更新 %d/%d 个币种", date_str, changed, len(ccys))
    logger.info("refetch 完成: 共写入 %d 行（source='bloomberg'）", written)


def _validate_refetch_args(args: argparse.Namespace) -> None:
    """refetch 模式参数校验，非法即退出。"""
    if not args.start_date or not args.end_date:
        logger.error("--refetch 需要 --start-date 与 --end-date（YYYYMMDD）")
        sys.exit(1)
    try:
        datetime.strptime(args.start_date, "%Y%m%d")
        datetime.strptime(args.end_date, "%Y%m%d")
    except ValueError:
        logger.error("日期格式应为 YYYYMMDD，收到 start=%s end=%s",
                     args.start_date, args.end_date)
        sys.exit(1)
    if args.start_date > args.end_date:
        logger.error("start-date 不能晚于 end-date")
        sys.exit(1)


# ── 入口 ────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="fx_rates 汇率表回填/刷新")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--seed", action="store_true",
                      help="从 fill_bdib 历史反推（零 Bloomberg 调用）")
    mode.add_argument("--refetch", action="store_true",
                      help="按日期范围从 Bloomberg 重拉刷新")
    parser.add_argument("--start-date", type=str, help="refetch 起始日期 YYYYMMDD（含）")
    parser.add_argument("--end-date", type=str, help="refetch 结束日期 YYYYMMDD（含）")
    parser.add_argument("--ccy", action="append", type=str,
                        help="refetch 币种，可多次指定（缺省从 fill_bdib 推导）")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不写入")
    parser.add_argument("--verbose", "-v", action="store_true", help="调试日志")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    conn = _open_fill_bdib()
    try:
        if args.seed:
            rows = _collect_seed_rows(conn)
            logger.info("seed: 从 fill_bdib 反推出 %d 条 (ccy, date) 汇率", len(rows))
            written, skipped = _apply_seed(conn, rows, args.dry_run)
            logger.info("%sseed 完成: 写入 %d 行（source=%s），跳过 bloomberg 来源 %d 行",
                        "[dry-run] " if args.dry_run else "", written, _SEED_SOURCE, skipped)
            return

        _validate_refetch_args(args)
        if is_quota_paused():
            logger.error("额度暂停中（quota_pause.json 已置位），refetch 将全部降级空跑；"
                         "请先恢复额度或清除暂停标记")
            sys.exit(1)
        ccys = _collect_refetch_ccys(conn, args.ccy)
        if not ccys:
            logger.error("无可重拉币种")
            sys.exit(1)
        _run_refetch(conn, args.start_date, args.end_date, ccys, args.dry_run)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
