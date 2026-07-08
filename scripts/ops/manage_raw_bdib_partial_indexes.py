"""raw_bdib 月度部分索引管理工具。

为 raw_bdib 表创建按月的部分索引（partial index），优化热数据查询。
raw_bdib 有 2 亿+行，全表索引 B-tree 过深、缓存命中率低。
管道运行时通常只查询最近几个月的数据，部分索引可显著提速。

用法::

    # 预览：显示将创建/删除的索引
    python -m scripts.ops.manage_raw_bdib_partial_indexes --dry-run

    # 执行：创建最近 3 个月的部分索引
    python -m scripts.ops.manage_raw_bdib_partial_indexes --apply

    # 自定义月数
    python -m scripts.ops.manage_raw_bdib_partial_indexes --apply --months 6

索引命名规范: idx_raw_bdib_partial_YYYYMM

设计要点:
    - SQLite 部分索引需要静态 WHERE 条件，无法使用 date() 函数
    - 脚本动态生成 SQL，每月一个索引
    - 旧索引通过 --cleanup 自动删除（超过 --months 的）
    - 索引列为 (equ_ticker, mkt_timestamp)，覆盖 TCA 查询模式
"""

from __future__ import annotations

import argparse
import calendar
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

from DataPipeline.config import Config

logger = logging.getLogger(__name__)


def _month_range(year: int, month: int) -> Tuple[str, str, str]:
    """返回月份的 YYYYMM, 起始日, 结束日。"""
    yyyymm = f"{year:04d}{month:02d}"
    first_day = f"{year:04d}{month:02d}01"
    last_day_num = calendar.monthrange(year, month)[1]
    last_day = f"{year:04d}{month:02d}{last_day_num:02d}"
    return yyyymm, first_day, last_day


def _generate_months(count: int) -> List[Tuple[str, str, str]]:
    """生成最近 count 个月的 (yyyymm, first_day, last_day) 列表，从当前月向前。"""
    now = datetime.now()
    months: List[Tuple[str, str, str]] = []
    year, month = now.year, now.month
    for _ in range(count):
        months.append(_month_range(year, month))
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return months


def _get_existing_partial_indexes(conn: sqlite3.Connection) -> List[str]:
    """获取已存在的部分索引名。"""
    rows = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='index' AND name LIKE 'idx_raw_bdib_partial_%'"
    ).fetchall()
    return [r[0] for r in rows]


def _build_create_sql(yyyymm: str, first_day: str, last_day: str) -> str:
    """构建创建部分索引的 SQL。"""
    return (
        f"CREATE INDEX IF NOT EXISTS idx_raw_bdib_partial_{yyyymm} "
        f"ON {Config.RAW_BDIB_TABLE} (equ_ticker, mkt_timestamp) "
        f"WHERE order_as_of_date >= '{first_day}' "
        f"AND order_as_of_date <= '{last_day}'"
    )


def _build_drop_sql(yyyymm: str) -> str:
    """构建删除部分索引的 SQL。"""
    return f"DROP INDEX IF EXISTS idx_raw_bdib_partial_{yyyymm}"


def main(argv: list[str] | None = None) -> int:
    """主入口。"""
    parser = argparse.ArgumentParser(
        description="raw_bdib 月度部分索引管理工具",
    )
    parser.add_argument("--dry-run", action="store_true", help="预览将创建/删除的索引")
    parser.add_argument("--apply", action="store_true", help="执行索引创建/删除")
    parser.add_argument(
        "--months", type=int, default=3,
        help="保留最近 N 个月的部分索引（默认 3）",
    )
    parser.add_argument(
        "--cleanup", action="store_true",
        help="清理超过 --months 范围的旧索引",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format=Config.LOG_FORMAT)

    if not args.dry_run and not args.apply:
        logger.info("请使用 --dry-run 预览 / --apply 执行")
        return 0

    db_path = Path(Config.RAW_BDIB_DB).resolve()
    if not db_path.exists():
        logger.error("数据库不存在: %s", db_path)
        return 1

    db_size_gb = db_path.stat().st_size / (1024 ** 3)
    logger.info("数据库: %s (%.1f GB)", db_path, db_size_gb)
    logger.info("SQLite 版本: %s", sqlite3.sqlite_version)

    target_months = _generate_months(args.months)
    target_yyyymms = {m[0] for m in target_months}

    conn = sqlite3.connect(str(db_path))
    try:
        existing = set(_get_existing_partial_indexes(conn))

        # 需要创建的索引
        to_create: List[Tuple[str, str]] = []
        for yyyymm, first_day, last_day in target_months:
            idx_name = f"idx_raw_bdib_partial_{yyyymm}"
            if idx_name not in existing:
                to_create.append((yyyymm, _build_create_sql(yyyymm, first_day, last_day)))

        # 需要删除的旧索引
        to_drop: List[str] = []
        if args.cleanup:
            for idx_name in existing:
                yyyymm = idx_name.replace("idx_raw_bdib_partial_", "")
                if yyyymm not in target_yyyymms:
                    to_drop.append(idx_name)

        logger.info("计划: 创建 %d 个索引, 删除 %d 个旧索引", len(to_create), len(to_drop))
        for yyyymm, sql in to_create:
            logger.info("  [CREATE] %s", yyyymm)
        for idx_name in to_drop:
            logger.info("  [DROP]   %s", idx_name)

        if args.dry_run:
            logger.info("dry-run 模式，不执行修改")
            return 0

        # 执行
        for _, sql in to_create:
            logger.info("执行: %s", sql[:80])
            conn.execute(sql)

        for idx_name in to_drop:
            sql = _build_drop_sql(idx_name.replace("idx_raw_bdib_partial_", ""))
            logger.info("执行: %s", sql)
            conn.execute(sql)

        conn.commit()
        logger.info("完成: 创建 %d, 删除 %d", len(to_create), len(to_drop))

        # 显示索引统计
        total_indexes = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND tbl_name = ?",
            (Config.RAW_BDIB_TABLE,),
        ).fetchone()[0]
        logger.info("raw_bdib 当前总索引数: %d", total_indexes)

    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
