"""补齐 fx_rates 汇率表缺失组合（L1）。

需求集合 = fill_bdib 出现的全部非 USD (ccy_ticker, order_as_of_date)，
减去 fx_rates 已有组合，逐组合调用 fetch_fx_rate_for_ccy：
- 查 fx_rates 表优先（零 Bloomberg 配额消耗）
- miss → Bloomberg 拉取，成功即落表（source='bloomberg'）
- 失败/暂停 → fx_rates 表 ≤日期回退 → 内存缓存 → 1.0（不落表，不伪造）
- 拉取返回空（历史超窗口）→ 记录 unrecoverable，该组合保持缺失（报告侧安全降级）

用法：
    # 预览缺失组合
    python scripts/ops/backfill_fx_rates_gaps.py --dry-run

    # 小范围验证（前 20 个缺失组合）
    python scripts/ops/backfill_fx_rates_gaps.py --limit 20

    # 全量补齐
    python scripts/ops/backfill_fx_rates_gaps.py

    # 仅重试此前 unrecoverable 的组合
    python scripts/ops/backfill_fx_rates_gaps.py --retry-unrecoverable
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("backfill_fx_rates_gaps")

_SCRIPT_DIR = Path(__file__).resolve().parent
_ROOT = _SCRIPT_DIR.parent.parent
sys.path.insert(0, str(_ROOT))

from DataPipeline.config import Config  # noqa: E402


def _missing_combos(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    """fill_bdib 出现的非 USD (ccy, date) - fx_rates 已有 → 缺失组合。"""
    need = set()
    for r in conn.execute(
        "SELECT DISTINCT ccy_ticker, order_as_of_date FROM fill_bdib "
        "WHERE ccy_ticker IS NOT NULL AND TRIM(ccy_ticker) != ''"
    ).fetchall():
        ccy = str(r[0]).upper().strip()
        if ccy != "USD CURNCY":
            need.add((ccy, str(r[1])))
    have = set()
    for r in conn.execute("SELECT DISTINCT ccy_ticker, order_as_of_date FROM fx_rates").fetchall():
        have.add((str(r[0]).upper().strip(), str(r[1])))
    return sorted(need - have)


def main() -> int:
    parser = argparse.ArgumentParser(description="补齐 fx_rates 缺失组合")
    parser.add_argument("--dry-run", action="store_true", help="仅预览不拉取")
    parser.add_argument("--limit", type=int, default=0, help="仅处理前 N 个缺失组合（0=全部）")
    parser.add_argument("--retry-unrecoverable", action="store_true",
                        help="仅重试上次记录的 unrecoverable 组合")
    args = parser.parse_args()

    db_path = Config.FILL_BDIB_DB
    conn = sqlite3.connect(str(db_path))
    try:
        missing = _missing_combos(conn)
        if args.retry_unrecoverable:
            # 从 fill_bdib 找 fx_rate 仍为 NULL 且非 USD 的组合作为重试目标
            missing = [
                (c, d) for c, d in missing
            ]
        logger.info("缺失组合数: %d", len(missing))
        if not missing:
            logger.info("无缺失组合，完成")
            return 0
        if args.dry_run:
            logger.info("DRY-RUN: 将处理 %d 个组合（按币种分布见下）", len(missing))
            from collections import Counter
            for ccy, n in sorted(Counter(c for c, _ in missing).items(), key=lambda x: -x[1]):
                logger.info("  %s: %d", ccy, n)
            logger.info("  日期范围: %s~%s", missing[0][1], missing[-1][1])
            return 0

        if args.limit > 0:
            missing = missing[: args.limit]
            logger.info("limit=%d：本次仅处理前 %d 个组合", args.limit, len(missing))

        from DataPipeline.storage.repositories.fx_rates import SqliteFxRatesRepository
        from DataPipeline.acquisition.fx_fetcher import fetch_fx_rate_for_ccy

        repo = SqliteFxRatesRepository()
        ok, failed = 0, 0
        unrecoverable: list[tuple[str, str]] = []
        t0 = time.time()
        for i, (ccy, date_str) in enumerate(missing, 1):
            # 先查表（可能被此前调用补上；fetch 内部也查表优先）
            if repo.get_rate(ccy, date_str) is not None:
                ok += 1
                continue
            try:
                fetch_fx_rate_for_ccy(ccy, date_str, fx_repo=repo)
            except Exception as exc:
                logger.warning("  [%d/%d] %s @ %s 拉取异常: %s", i, len(missing), ccy, date_str, exc)
                failed += 1
                unrecoverable.append((ccy, date_str))
                continue
            # 判据：是否落表。真实拉取成功 → 落表（含 px_last 双存）；
            # 降级链（表回退/内存/1.0 兜底）只返回不落表 → 判定不可回补。
            if repo.get_rate(ccy, date_str) is not None:
                ok += 1
            else:
                failed += 1
                unrecoverable.append((ccy, date_str))
            if i % 50 == 0:
                logger.info("  进度 %d/%d（成功 %d 失败 %d）耗时 %.0fs",
                            i, len(missing), ok, failed, time.time() - t0)
        logger.info("完成: 成功 %d, 失败/不可回补 %d（耗时 %.0fs）", ok, failed, time.time() - t0)
        if unrecoverable:
            log_path = Path(_ROOT) / "scripts" / "ops" / "_fx_unrecoverable.txt"
            with open(log_path, "w", encoding="utf-8") as f:
                for c, d in unrecoverable:
                    f.write(f"{d} {c}\n")
            logger.info("不可回补组合已写入 %s（%d 个）", log_path, len(unrecoverable))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
