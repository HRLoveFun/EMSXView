"""清理 processed_fills 中的孤儿行与日期不匹配行。

诊断并删除两类问题数据：
1. 孤儿行：processed_fills 中存在，但 raw_fills 中无对应 (OrderId, RouteId, FillId) 的记录。
2. 日期不匹配行：processed_fills 的 order_as_of_date 与 raw_fills 计算出的本地交易日不一致。

执行前会自动备份 processed_fills.db 与 raw_fills.db，清理后自动重跑受影响日期。
"""

from __future__ import annotations

import argparse
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Set, Tuple

from DataPipeline.config import Config
from DataPipeline.storage.connection import ConnectionManager

logger = logging.getLogger(__name__)


def _backup_db(db_path: Path, backup_dir: Optional[Path] = None) -> Path:
    """为数据库创建时间戳备份。"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if backup_dir is None:
        backup_dir = db_path.parent
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{db_path.stem}.bak.{ts}{db_path.suffix}"
    shutil.copy2(db_path, backup_path)
    logger.info("已备份 %s -> %s", db_path, backup_path)
    return backup_path



def _get_problematic_dates(cm: ConnectionManager) -> Tuple[Set[str], Set[str]]:
    """返回 (孤儿日期集合, 日期不匹配日期集合)。"""
    processed_conn = cm.get_connection("processed_fills")
    raw_fills_path = Path(Config.RAW_FILLS_DB).resolve()
    try:
        # 使用 ATTACH 将 raw_fills.db 附加到当前连接，实现跨库 JOIN
        raw_conn = processed_conn.raw_connection
        raw_conn.execute(f"ATTACH DATABASE ? AS raw_db", (str(raw_fills_path),))

        # 1. 孤儿行：processed_fills 中 (OrderId, RouteId, FillId) 不存在于 raw_fills
        orphan_dates = {
            r[0] for r in raw_conn.execute(
                """
                SELECT DISTINCT p.order_as_of_date
                FROM processed_fills p
                LEFT JOIN raw_db.raw_fills r
                  ON p.OrderId = r.OrderId
                 AND p.RouteId = r.RouteId
                 AND p.FillId = r.FillId
                WHERE r.OrderId IS NULL
                """
            ).fetchall()
            if r[0]
        }

        # 2. 日期不匹配行：processed_fills 与 raw_fills 的 order_as_of_date 不一致
        # 注意：raw_fills 的 order_as_of_date 可能为空（上游 Exchange 缺失），此时不视为不匹配。
        mismatch_dates = set()
        cursor = raw_conn.execute(
            """
            SELECT DISTINCT p.order_as_of_date
            FROM processed_fills p
            JOIN raw_db.raw_fills r
              ON p.OrderId = r.OrderId
             AND p.RouteId = r.RouteId
             AND p.FillId = r.FillId
            WHERE r.order_as_of_date IS NOT NULL
              AND r.order_as_of_date != ''
              AND p.order_as_of_date != r.order_as_of_date
            """
        )
        for row in cursor.fetchall():
            if row[0]:
                mismatch_dates.add(row[0])

        # 3. order_as_of_date 为空或格式无效
        invalid_dates = {
            r[0] for r in raw_conn.execute(
                """
                SELECT DISTINCT order_as_of_date
                FROM processed_fills
                WHERE order_as_of_date IS NULL
                   OR order_as_of_date = ''
                   OR order_as_of_date GLOB '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]' = 0
                """
            ).fetchall()
            if r[0]
        }

        return orphan_dates, mismatch_dates | invalid_dates
    finally:
        processed_conn.close()


def _cleanup_dates(cm: ConnectionManager, dates: Set[str]) -> None:
    """删除指定日期在 processed_fills 及下游表中的数据。"""
    if not dates:
        return

    date_list = sorted(dates)
    logger.info("开始清理 %d 个日期: %s", len(date_list), date_list[:10])

    processed_conn = cm.get_connection("processed_fills")
    try:
        raw_conn = processed_conn.raw_connection
        # 删除 processed_fills 中问题日期的行
        raw_conn.execute(
            "DELETE FROM processed_fills WHERE order_as_of_date IN ({})".format(
                ",".join(["?"] * len(date_list))
            ),
            date_list,
        )
        # 删除 agg_fills_10s
        raw_conn.execute(
            "DELETE FROM agg_fills_10s WHERE order_as_of_date IN ({})".format(
                ",".join(["?"] * len(date_list))
            ),
            date_list,
        )
        # 删除 agg_fills_1min
        raw_conn.execute(
            "DELETE FROM agg_fills_1min WHERE order_as_of_date IN ({})".format(
                ",".join(["?"] * len(date_list))
            ),
            date_list,
        )
        # 删除 processing_log 中对应日期的 processed / aggregated 标记
        raw_conn.execute(
            "DELETE FROM processing_log WHERE order_as_of_date IN ({}) AND stage IN ('processed', 'aggregated')".format(
                ",".join(["?"] * len(date_list))
            ),
            date_list,
        )
        raw_conn.commit()
        logger.info("已清理 processed_fills / agg_fills / processing_log 中 %d 个日期", len(date_list))
    finally:
        processed_conn.close()

    # route_history / route_event_history 已迁至 execution_history.db，按 order_as_of_date 删除
    execution_history_conn = cm.get_connection("execution_history")
    try:
        eh_raw_conn = execution_history_conn.raw_connection
        eh_raw_conn.execute(
            "DELETE FROM route_history WHERE order_as_of_date IN ({})".format(
                ",".join(["?"] * len(date_list))
            ),
            date_list,
        )
        eh_raw_conn.execute(
            "DELETE FROM route_event_history WHERE order_as_of_date IN ({})".format(
                ",".join(["?"] * len(date_list))
            ),
            date_list,
        )
        eh_raw_conn.commit()
        logger.info("已清理 execution_history.db 中 %d 个日期", len(date_list))
    finally:
        execution_history_conn.close()



def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="清理 processed_fills 孤儿/日期不匹配行")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="仅诊断，不执行删除",
    )
    parser.add_argument(
        "--dates", type=str, default="",
        help="逗号分隔的指定日期 (YYYYMMDD)，优先于自动检测",
    )
    parser.add_argument(
        "--backup-dir", type=str, default="",
        help="备份目录（默认与数据库同目录）",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format=Config.LOG_FORMAT)

    cm = ConnectionManager()

    # 备份
    backup_dir = Path(args.backup_dir) if args.backup_dir else None
    processed_db_path = Path(Config.PROCESSED_FILLS_DB)
    raw_db_path = Path(Config.RAW_FILLS_DB)
    if processed_db_path.exists():
        _backup_db(processed_db_path, backup_dir)
    if raw_db_path.exists():
        _backup_db(raw_db_path, backup_dir)


    if args.dates:
        dates = {d.strip() for d in args.dates.split(",") if d.strip()}
        orphan_dates: Set[str] = set()
        mismatch_dates = dates
    else:
        orphan_dates, mismatch_dates = _get_problematic_dates(cm)

    all_dates = orphan_dates | mismatch_dates
    logger.info(
        "诊断结果: 孤儿日期 %d 个, 不匹配/无效日期 %d 个, 合计 %d 个",
        len(orphan_dates), len(mismatch_dates), len(all_dates),
    )

    if not all_dates:
        logger.info("未发现需要清理的日期")
        return 0

    if args.dry_run:
        logger.info("DRY-RUN 模式: 将清理以下日期: %s", sorted(all_dates))
        return 0

    _cleanup_dates(cm, all_dates)
    cleanup_dates_str = ",".join(sorted(all_dates))
    logger.info("CLEANUP_DATES:%s", cleanup_dates_str)
    # 将日期列表写入固定文件，便于 reprocess_affected_dates.py 读取
    cleanup_dates_file = Path(Config.LOGGING_DIR) / ".cleanup_dates.txt"
    cleanup_dates_file.parent.mkdir(parents=True, exist_ok=True)
    cleanup_dates_file.write_text(cleanup_dates_str, encoding="utf-8")
    logger.info("日期列表已写入 %s", cleanup_dates_file)
    logger.info("清理完成，共 %d 个日期", len(all_dates))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
