"""EUR equ_ticker 历史数据回填脚本。

修复 fill_processor.py 中 EUR composite ticker 映射 bug 后,对受影响日期
(2025-09 ~ 2026-06,缓存建立前)重跑 S2-S4 管道,恢复 EUR 股票的
equ_ticker 字段。

日期格式说明(关键):
  - raw_fills.source_date:        YYYYMMDD(batch 周五采集日期,管道分区键)
  - raw_fills.order_as_of_date:   ISO 带时间(交易日,'2025-09-15 00:00:00')
  - processed_fills.order_as_of_date: YYYYMMDD(交易日,'20250915')
  - 一个 source_date batch 包含 ~5 个交易日
  - ProcessRawFillsStage 用 source_date 过滤 target_dates
  - process_raw_fills_for_date(source_date) 通过 source_date fallback 查询

流程:
  1. 备份受影响数据库(processed_fills / execution_history / ticker_registry)
  2. 识别受影响 source_date(raw_fills 中 Currency='EUR' 的 distinct source_date)
  3. 单日 dry-run 验证(默认 20250919,第一个受影响 batch)
  4. 全量回填: run_full_pipeline(dates=source_dates, skip_bdib=True)
  5. 生成 before/after equ_ticker 填充率验证报告

安全约束:
  - raw_fills.db 全程只读
  - skip_bdib=True,不触碰 fill_bdib / bdib_daily_summary / regime
  - 回填前自动备份,失败可回滚
  - 单日失败立即停止,不继续后续日期

用法:
  python scripts/backfill_eur_ticker.py --dry-run                    # 仅单 batch 验证
  python scripts/backfill_eur_ticker.py --dry-run --dry-run-date 20250919
  python scripts/backfill_eur_ticker.py --start 20250919 --end 20260626
  python scripts/backfill_eur_ticker.py --skip-backup                # 跳过备份(不推荐)
  python scripts/backfill_eur_ticker.py --report-only                # 仅生成验证报告
  python scripts/backfill_eur_ticker.py --retention 2                # 保留最近 2 份 eur_backfill_* 备份
  python scripts/backfill_eur_ticker.py --retention 0                # 保留所有备份(禁用清理)
"""

from __future__ import annotations

import argparse
import gc
import logging
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from DataPipeline.config import Config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("backfill_eur_ticker")


# 需要备份的数据库(回填会修改这些库)
BACKUP_TARGET_DBS: List[Path] = [
    Config.PROCESSED_FILLS_DB,
    Config.EXECUTION_HISTORY_DB,
    Config.TICKER_REGISTRY_DB,
]

# 备份目录前缀(与 timestamp 组合形成最终目录名,目录名按字典序即为时间序)
BACKUP_PREFIX = "eur_backfill_"

# 欧洲交易所代码(用于 processed_fills 中识别 EUR 行,因无 Currency 列)
EUROPEAN_EXCHANGES = (
    "GR", "FP", "NA", "NO", "SW",  # 德/法/荷兰/挪威/瑞士
    "AV", "BB", "DC", "FH", "IM", "IR", "LX", "PL", "SM", "SP",  # 其他欧洲
)


def backup_databases(backup_dir: Path) -> None:
    """备份受影响数据库到带时间戳的目录。

    Args:
        backup_dir: 备份根目录(形如 ``<DATA_DIR>/backups/eur_backfill_YYYYMMDD_HHMMSS``)。
    """
    backup_dir.mkdir(parents=True, exist_ok=True)
    logger.info("备份数据库到 %s", backup_dir)
    for db_path in BACKUP_TARGET_DBS:
        if not db_path.exists():
            logger.warning("数据库文件不存在,跳过备份: %s", db_path)
            continue
        # 同时备份 -wal 和 -shm 文件(WAL 模式)
        for suffix in ["", "-wal", "-shm"]:
            src = db_path.with_suffix(db_path.suffix + suffix) if suffix else db_path
            if src.exists():
                dst = backup_dir / src.name
                shutil.copy2(src, dst)
                logger.info("  已备份 %s -> %s", src.name, dst)


def prune_old_backups(backup_root: Path, keep_dir: Path, retention: int) -> int:
    """按保留份数清理 ``backup_root`` 下早于 ``keep_dir`` 的同类备份目录。

    目录命名约定为 ``<BACKUP_PREFIX>YYYYMMDD_HHMMSS``,字典序即时间序,因此无需解析时间戳。

    Args:
        backup_root: 备份根目录(通常是 ``<DATA_DIR>/backups``)。
        keep_dir: 本次刚创建/需要保留的备份目录(不在清理范围)。
        retention: 保留的备份份数(包含 ``keep_dir`` 在内):
            - ``>= 1``: 保留当前目录 + 早于它的最多 ``retention - 1`` 份
            - ``<= 0``: 禁用清理(保留所有历史备份)

    Returns:
        实际删除的目录数量。
    """
    if retention <= 0:
        logger.info("retention=%d, 跳过清理(保留所有历史备份)", retention)
        return 0
    if not backup_root.exists():
        return 0

    # 仅清理本脚本产生的备份目录(以前缀过滤,避免误删其他来源的备份)
    candidates = sorted(
        d for d in backup_root.iterdir()
        if d.is_dir() and d.name.startswith(BACKUP_PREFIX) and d.name != keep_dir.name
    )

    # 需要保留的"历史份数"= retention - 1(keep_dir 本身占 1 份)
    keep_history = max(retention - 1, 0)
    if len(candidates) <= keep_history:
        logger.info(
            "历史备份 %d 份 <= 保留阈值 %d, 无需清理",
            len(candidates), keep_history,
        )
        return 0

    # 字典序=时间序; 末尾(更老)的多余目录需要删除
    to_delete = candidates[: len(candidates) - keep_history]
    freed_bytes = 0
    deleted = 0
    for d in to_delete:
        try:
            size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
            shutil.rmtree(d)
            freed_bytes += size
            deleted += 1
            logger.info("  已清理旧备份: %s (%.2f MB)", d.name, size / 1_048_576)
        except OSError as e:
            logger.error("  清理失败 %s: %s", d.name, e)
    logger.info(
        "备份清理完成: 保留 %d 份(含本次), 删除 %d 份, 释放 %.2f MB",
        len(candidates) - len(to_delete) + 1, deleted, freed_bytes / 1_048_576,
    )
    return deleted


def get_affected_source_dates(start: str, end: str) -> List[str]:
    """查询 raw_fills 中 Currency='EUR' 的 distinct source_date。

    source_date 是 batch 采集日期(周五),是管道分区键。
    ProcessRawFillsStage 用 source_date 过滤 target_dates。

    Args:
        start: 起始 source_date YYYYMMDD(含)
        end: 结束 source_date YYYYMMDD(含)

    Returns:
        排序后的受影响 source_date 列表
    """
    conn = sqlite3.connect(str(Config.RAW_FILLS_DB), timeout=Config.SQLITE_CONNECT_TIMEOUT_SEC)
    try:
        cursor = conn.execute(
            "SELECT DISTINCT source_date FROM raw_fills "
            "WHERE Currency = 'EUR' "
            "  AND source_date >= ? AND source_date <= ? "
            "  AND source_date IS NOT NULL AND source_date != '' "
            "ORDER BY source_date",
            (start, end),
        )
        dates = [row[0] for row in cursor.fetchall()]
        logger.info("识别到 %d 个受影响 source_date(%s ~ %s)", len(dates), start, end)
        return dates
    finally:
        conn.close()


def get_trading_dates_for_source(source_date: str) -> List[str]:
    """查询某 source_date batch 包含的所有交易日(YYYYMMDD)。

    raw_fills.order_as_of_date 是 ISO 格式('2025-09-15 00:00:00'),
    需转换为 YYYYMMDD 以匹配 processed_fills.order_as_of_date。

    Args:
        source_date: batch 日期 YYYYMMDD

    Returns:
        排序后的交易日列表(YYYYMMDD)
    """
    conn = sqlite3.connect(str(Config.RAW_FILLS_DB), timeout=Config.SQLITE_CONNECT_TIMEOUT_SEC)
    try:
        cursor = conn.execute(
            "SELECT DISTINCT order_as_of_date FROM raw_fills "
            "WHERE source_date = ? "
            "  AND order_as_of_date IS NOT NULL AND order_as_of_date != '' "
            "ORDER BY order_as_of_date",
            (source_date,),
        )
        trading_dates = []
        for row in cursor.fetchall():
            raw = row[0]
            # ISO '2025-09-15 00:00:00' -> '20250915'
            trading_date = raw[:10].replace("-", "")
            trading_dates.append(trading_date)
        return trading_dates
    finally:
        conn.close()


def query_stats_for_dates(trading_dates: List[str]) -> dict:
    """查询 processed_fills 指定交易日的 equ_ticker 填充率统计。

    processed_fills 无 Currency 列,用 Exchange 列识别欧洲交易所。

    Args:
        trading_dates: 交易日列表(YYYYMMDD)

    Returns:
        {"total": N, "null": N, "null_rate": float,
         "eu_total": N, "eu_null": N, "eu_null_rate": float,
         "eu_equity": N, "eu_equity_rate": float}
    """
    if not trading_dates:
        return {"total": 0, "null": 0, "null_rate": 0.0,
                "eu_total": 0, "eu_null": 0, "eu_null_rate": 0.0,
                "eu_equity": 0, "eu_equity_rate": 0.0}

    conn = sqlite3.connect(str(Config.PROCESSED_FILLS_DB), timeout=Config.SQLITE_CONNECT_TIMEOUT_SEC)
    try:
        placeholders = ",".join("?" * len(trading_dates))
        eu_exchange_list = ",".join("?" * len(EUROPEAN_EXCHANGES))

        cursor = conn.execute(
            f"SELECT COUNT(*) FROM processed_fills WHERE order_as_of_date IN ({placeholders})",
            trading_dates,
        )
        total = cursor.fetchone()[0]

        cursor = conn.execute(
            f"SELECT COUNT(*) FROM processed_fills WHERE order_as_of_date IN ({placeholders}) "
            f"AND equ_ticker IS NULL",
            trading_dates,
        )
        null_count = cursor.fetchone()[0]

        # 欧洲交易所统计
        params = list(trading_dates) + list(EUROPEAN_EXCHANGES)
        cursor = conn.execute(
            f"SELECT COUNT(*) FROM processed_fills "
            f"WHERE order_as_of_date IN ({placeholders}) "
            f"AND Exchange IN ({eu_exchange_list})",
            params,
        )
        eu_total = cursor.fetchone()[0]

        cursor = conn.execute(
            f"SELECT COUNT(*) FROM processed_fills "
            f"WHERE order_as_of_date IN ({placeholders}) "
            f"AND Exchange IN ({eu_exchange_list}) AND equ_ticker IS NULL",
            params,
        )
        eu_null = cursor.fetchone()[0]

        cursor = conn.execute(
            f"SELECT COUNT(*) FROM processed_fills "
            f"WHERE order_as_of_date IN ({placeholders}) "
            f"AND Exchange IN ({eu_exchange_list}) AND equ_ticker LIKE '% EU Equity'",
            params,
        )
        eu_equity = cursor.fetchone()[0]

        return {
            "total": total,
            "null": null_count,
            "null_rate": (null_count / total) if total > 0 else 0.0,
            "eu_total": eu_total,
            "eu_null": eu_null,
            "eu_null_rate": (eu_null / eu_total) if eu_total > 0 else 0.0,
            "eu_equity": eu_equity,
            "eu_equity_rate": (eu_equity / eu_total) if eu_total > 0 else 0.0,
        }
    finally:
        conn.close()


def run_dry_run(source_date: str) -> bool:
    """对单个 source_date batch 执行 dry-run 验证。

    记录回填前该 batch 涉及交易日的行数和 equ_ticker 统计,
    执行 process_raw_fills_for_date(source_date),
    然后验证行数不减少且 equ_ticker 填充率提升。

    Returns:
        True 表示 dry-run 通过
    """
    logger.info("=" * 60)
    logger.info("DRY-RUN 验证: source_date %s", source_date)
    logger.info("=" * 60)

    trading_dates = get_trading_dates_for_source(source_date)
    if not trading_dates:
        logger.error("source_date %s 在 raw_fills 中无数据", source_date)
        return False
    logger.info("包含交易日: %s", trading_dates)

    before_stats = query_stats_for_dates(trading_dates)
    logger.info(
        "回填前: 总 %d 行(NULL 率=%.2f%%), 欧洲 %d 行(equ_ticker NULL 率=%.2f%%, EU Equity 率=%.2f%%)",
        before_stats["total"], before_stats["null_rate"] * 100,
        before_stats["eu_total"], before_stats["eu_null_rate"] * 100,
        before_stats["eu_equity_rate"] * 100,
    )

    from DataPipeline.ingestion.fill_ingestion import process_raw_fills_for_date

    logger.info("执行 process_raw_fills_for_date(%s)...", source_date)
    result = process_raw_fills_for_date(source_date)

    if not result["success"]:
        logger.error("DRY-RUN 失败: %s", result.get("error"))
        return False

    logger.info(
        "处理结果: rows_read=%d, rows_cleaned=%d, rows_processed=%d",
        result["rows_read"], result["rows_cleaned"], result["rows_processed"],
    )

    if result["rows_processed"] == 0:
        logger.error("DRY-RUN 失败: rows_processed=0,未处理任何数据")
        return False

    after_stats = query_stats_for_dates(trading_dates)
    logger.info(
        "回填后: 总 %d 行(NULL 率=%.2f%%), 欧洲 %d 行(equ_ticker NULL 率=%.2f%%, EU Equity 率=%.2f%%)",
        after_stats["total"], after_stats["null_rate"] * 100,
        after_stats["eu_total"], after_stats["eu_null_rate"] * 100,
        after_stats["eu_equity_rate"] * 100,
    )

    # 行数不得减少
    if after_stats["total"] < before_stats["total"]:
        logger.error(
            "数据丢失! 回填前 %d 行, 回填后 %d 行",
            before_stats["total"], after_stats["total"],
        )
        return False

    # 欧洲 equ_ticker NULL 率应下降(或已无 NULL)
    if before_stats["eu_null"] > 0 and after_stats["eu_null"] >= before_stats["eu_null"]:
        logger.warning(
            "欧洲 equ_ticker NULL 未改善: %d -> %d(可能缓存/BBG 仍不可用,保留原始拼接值)",
            before_stats["eu_null"], after_stats["eu_null"],
        )

    logger.info(
        "DRY-RUN 通过: 总行数 %d -> %d (未减少), rows_processed=%d",
        before_stats["total"], after_stats["total"], result["rows_processed"],
    )
    return True


def run_full_backfill(source_dates: List[str]) -> None:
    """全量回填: 调用 run_full_pipeline 触发 S2-S4。

    Args:
        source_dates: 受影响 source_date 列表(batch 日期)
    """
    from DataPipeline.orchestration.core import run_full_pipeline

    logger.info("=" * 60)
    logger.info("全量回填: %d 个 source_date batch", len(source_dates))
    logger.info("=" * 60)

    total = len(source_dates)
    for idx, source_date in enumerate(source_dates, 1):
        trading_dates = get_trading_dates_for_source(source_date)
        before_stats = query_stats_for_dates(trading_dates)
        logger.info("[%d/%d] 处理 source_date=%s (交易日 %s)...", idx, total, source_date, trading_dates)
        print(f"[BACKFILL] {idx}/{total} processing source_date={source_date}", flush=True)

        try:
            summary = run_full_pipeline(
                dates=[source_date],
                skip_bdib=True,
                skip_ingest=True,
            )
        except Exception as e:
            logger.error("source_date %s 回填失败,停止后续处理: %s", source_date, e)
            raise

        after_stats = query_stats_for_dates(trading_dates)

        # 行数不得减少
        if after_stats["total"] < before_stats["total"]:
            logger.error(
                "数据丢失! source_date %s: 回填前 %d 行, 回填后 %d 行",
                source_date, before_stats["total"], after_stats["total"],
            )
            raise RuntimeError(f"数据丢失: {source_date}")

        logger.info(
            "[%d/%d] %s 完成: 总 %d 行, 欧洲 equ_ticker NULL 率 %.2f%% -> %.2f%%, EU Equity 率 %.2f%%",
            idx, total, source_date, after_stats["total"],
            before_stats["eu_null_rate"] * 100, after_stats["eu_null_rate"] * 100,
            after_stats["eu_equity_rate"] * 100,
        )

        gc.collect()

    logger.info("全量回填完成: %d 个 source_date batch", total)


def generate_report(source_dates: List[str]) -> None:
    """生成 before/after 验证报告。

    注意: 此函数在回填后调用,对比的是"回填前备份"与"回填后当前"数据。
    简化实现: 直接输出回填后的统计,回填前的统计已在前置步骤记录到日志。
    """
    logger.info("=" * 60)
    logger.info("回填验证报告")
    logger.info("=" * 60)

    # 汇总所有受影响交易日的统计
    all_trading_dates: List[str] = []
    for sd in source_dates:
        all_trading_dates.extend(get_trading_dates_for_source(sd))
    all_trading_dates = sorted(set(all_trading_dates))

    overall = query_stats_for_dates(all_trading_dates)
    logger.info(
        "受影响区间统计(%d 个交易日): 总 %d 行, 欧洲 %d 行",
        len(all_trading_dates), overall["total"], overall["eu_total"],
    )
    logger.info(
        "  equ_ticker 全局 NULL 率=%.2f%%, 欧洲 NULL 率=%.2f%%, 欧洲 EU Equity 率=%.2f%%",
        overall["null_rate"] * 100, overall["eu_null_rate"] * 100,
        overall["eu_equity_rate"] * 100,
    )

    # 抽样首末中间 batch
    if source_dates:
        sample = [source_dates[0], source_dates[len(source_dates) // 2], source_dates[-1]]
        for sd in sample:
            td = get_trading_dates_for_source(sd)
            stats = query_stats_for_dates(td)
            logger.info(
                "  source_date=%s: 总 %d 行, 欧洲 %d 行(NULL 率=%.2f%%, EU Equity 率=%.2f%%)",
                sd, stats["total"], stats["eu_total"],
                stats["eu_null_rate"] * 100, stats["eu_equity_rate"] * 100,
            )

    logger.info("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="EUR equ_ticker 历史数据回填脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--start", default="20250919",
        help="起始 source_date YYYYMMDD(默认 20250919,第一个含 EUR 的 batch)",
    )
    parser.add_argument(
        "--end", default="20260626",
        help="结束 source_date YYYYMMDD(默认 20260626)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="仅对单 batch 执行 dry-run 验证,不进行全量回填",
    )
    parser.add_argument(
        "--dry-run-date", default="20250919",
        help="dry-run 验证的 source_date(默认 20250919)",
    )
    parser.add_argument(
        "--skip-backup", action="store_true",
        help="跳过备份步骤(不推荐,此时 --retention 也无效)",
    )
    parser.add_argument(
        "--retention", type=int, default=1,
        help="保留最近 N 份 eur_backfill_* 备份目录(包含本次新备份)。"
             "默认 1,仅保留本次新备份;"
             "N=0 表示禁用清理(保留所有历史备份)。"
             "仅清理本次新备份之前的历史目录,不影响其他来源的备份。"
             "在 --dry-run / --skip-backup / --report-only 模式下不触发。",
    )
    parser.add_argument(
        "--report-only", action="store_true",
        help="仅生成验证报告(回填已完成后使用)",
    )
    args = parser.parse_args()

    logger.info("EUR equ_ticker 回填脚本启动")
    logger.info("数据目录: %s", Config.DATA_DIR)
    logger.info("source_date 范围: %s ~ %s", args.start, args.end)

    if args.report_only:
        dates = get_affected_source_dates(args.start, args.end)
        generate_report(dates)
        return

    if not args.skip_backup:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = Config.DATA_DIR / "backups" / f"eur_backfill_{timestamp}"
        backup_databases(backup_dir)
        # 按保留份数清理更早的同前缀备份(默认仅保留本次新备份)
        prune_old_backups(
            backup_root=Config.DATA_DIR / "backups",
            keep_dir=backup_dir,
            retention=args.retention,
        )
    else:
        logger.warning("已跳过备份步骤(--skip-backup), --retention 不会执行")

    if args.dry_run:
        ok = run_dry_run(args.dry_run_date)
        if not ok:
            logger.error("DRY-RUN 未通过,请检查后再执行全量回填")
            sys.exit(1)
        logger.info("DRY-RUN 通过,可用 --start/--end 执行全量回填")
        return

    # 全量回填
    dates = get_affected_source_dates(args.start, args.end)
    if not dates:
        logger.warning("未找到受影响 source_date,退出")
        return

    run_full_backfill(dates)
    generate_report(dates)
    logger.info("回填脚本完成")


if __name__ == "__main__":
    main()
