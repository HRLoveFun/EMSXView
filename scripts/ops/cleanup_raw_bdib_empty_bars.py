"""清理 raw_bdib 中的完全空 bar 行（轻量备份版）。

删除满足以下条件的行：
1. OHLC 全部为 NULL（open/high/low/close）
2. volume 为 0 或 NULL
3. value 为 0 或 NULL

这类空 bar 是早期写入路径的历史残留（28,591 行，2026-04-08，600 个 ticker，
全部 source='bloomberg'），已于 2026-07-07 通过本脚本 --apply 清理。
当前 _validate_bdib_response 已能过滤，不会再产生。

备份策略：轻量备份（不全库备份 41GB）
- 将待删除行的完整数据导出到独立小 SQLite snapshot 文件（几 MB）
- 配套 manifest.json 记录操作元数据
- 内置 --restore 子命令可从 snapshot 回填

dry-run 三道安全闸（防误删）：
1. 行级统计闸：COUNT / DISTINCT ticker / DISTINCT date / source 分布
2. 列特征闸：抽样 20 行逐行断言 6 个空值条件
3. 异常源闸：source 白名单仅允许 'bloomberg'

清理后自动将 PRAGMA user_version 设为 1。
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from DataPipeline.config import Config

logger = logging.getLogger(__name__)

# 空 bar DELETE 条件（统一使用，确保 snapshot/DELETE/dry-run 一致）
EMPTY_BAR_WHERE = (
    "open IS NULL AND high IS NULL AND low IS NULL AND close IS NULL "
    "AND COALESCE(volume, 0) = 0 AND COALESCE(value, 0) = 0"
)

# source 白名单：仅允许 bloomberg（防止误删未来新增的 source）
_ALLOWED_SOURCES = {"bloomberg"}


def _get_db_path() -> Path:
    """获取 raw_bdib.db 路径。"""
    return Path(Config.RAW_BDIB_DB).resolve()


def _get_columns(db_path: Path, table_name: str = "") -> List[str]:
    """获取指定表的所有列名（动态，兼容废弃衍生列）。"""
    table = table_name or Config.RAW_BDIB_TABLE
    conn = sqlite3.connect(str(db_path))
    try:
        return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
    finally:
        conn.close()


def _count_empty_bars(db_path: Path) -> int:
    """统计待删除的空 bar 行数。"""
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(
            f"SELECT COUNT(*) FROM {Config.RAW_BDIB_TABLE} WHERE {EMPTY_BAR_WHERE}"
        ).fetchone()[0]
    finally:
        conn.close()


def _gate1_row_stats(db_path: Path) -> Dict[str, Any]:
    """安全闸 1：行级统计。返回统计信息字典。"""
    conn = sqlite3.connect(str(db_path))
    try:
        total = conn.execute(f"SELECT COUNT(*) FROM {Config.RAW_BDIB_TABLE}").fetchone()[0]
        empty = conn.execute(
            f"SELECT COUNT(*) FROM {Config.RAW_BDIB_TABLE} WHERE {EMPTY_BAR_WHERE}"
        ).fetchone()[0]
        distinct_ticker = conn.execute(
            f"SELECT COUNT(DISTINCT equ_ticker) FROM {Config.RAW_BDIB_TABLE} WHERE {EMPTY_BAR_WHERE}"
        ).fetchone()[0]
        distinct_date = conn.execute(
            f"SELECT COUNT(DISTINCT order_as_of_date) FROM {Config.RAW_BDIB_TABLE} WHERE {EMPTY_BAR_WHERE}"
        ).fetchone()[0]
        date_range = conn.execute(
            f"SELECT MIN(order_as_of_date), MAX(order_as_of_date) "
            f"FROM {Config.RAW_BDIB_TABLE} WHERE {EMPTY_BAR_WHERE}"
        ).fetchone()
        source_dist = conn.execute(
            f"SELECT source, COUNT(*) FROM {Config.RAW_BDIB_TABLE} "
            f"WHERE {EMPTY_BAR_WHERE} GROUP BY source"
        ).fetchall()
        return {
            "total_rows": total,
            "empty_rows": empty,
            "distinct_ticker": distinct_ticker,
            "distinct_date": distinct_date,
            "min_date": date_range[0],
            "max_date": date_range[1],
            "source_distribution": {s: c for s, c in source_dist},
            "pct": (empty / total * 100) if total > 0 else 0,
        }
    finally:
        conn.close()


def _gate2_column_assertion(db_path: Path, sample_size: int = 20) -> Tuple[bool, List[Dict]]:
    """安全闸 2：列特征断言。抽样 sample_size 行逐行检查。返回 (全部通过, 抽样数据)。"""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            f"SELECT * FROM {Config.RAW_BDIB_TABLE} WHERE {EMPTY_BAR_WHERE} LIMIT ?",
            (sample_size,),
        ).fetchall()
        samples = [dict(r) for r in rows]
        for r in samples:
            if not _is_truly_empty(r):
                return False, samples
        return True, samples
    finally:
        conn.close()


def _is_truly_empty(row: Dict) -> bool:
    """判断单行是否满足空 bar 条件（6 个断言）。"""
    return (
        row.get("open") is None
        and row.get("high") is None
        and row.get("low") is None
        and row.get("close") is None
        and (row.get("volume") is None or row.get("volume") == 0)
        and (row.get("value") is None or row.get("value") == 0)
    )


def _gate3_source_whitelist(db_path: Path) -> Tuple[bool, set]:
    """安全闸 3：异常源检查。仅允许 bloomberg。返回 (全部通过, 实际 source 集合)。"""
    conn = sqlite3.connect(str(db_path))
    try:
        sources = {
            r[0] for r in conn.execute(
                f"SELECT DISTINCT source FROM {Config.RAW_BDIB_TABLE} WHERE {EMPTY_BAR_WHERE}"
            ).fetchall()
        }
        return sources.issubset(_ALLOWED_SOURCES), sources
    finally:
        conn.close()


def _run_dry_run(db_path: Path) -> bool:
    """执行 dry-run 三道安全闸。返回是否全部通过。"""
    empty_count = _count_empty_bars(db_path)
    if empty_count == 0:
        logger.info("未发现空 bar 行，无需清理")
        return True

    # 闸 1：行级统计
    stats = _gate1_row_stats(db_path)
    logger.info("【安全闸 1 - 行级统计】")
    logger.info("  待删行数: %s / 总行数 %s (%.6f%%)",
                f"{stats['empty_rows']:,}", f"{stats['total_rows']:,}", stats["pct"])
    logger.info("  涉及 ticker: %d 个", stats["distinct_ticker"])
    logger.info("  涉及日期: %d 个 (%s ~ %s)",
                stats["distinct_date"], stats["min_date"], stats["max_date"])
    logger.info("  source 分布: %s", stats["source_distribution"])

    # 闸 2：列特征断言
    passed2, samples = _gate2_column_assertion(db_path)
    logger.info("【安全闸 2 - 列特征断言】抽样 %d 行", len(samples))
    for i, s in enumerate(samples[:5]):
        logger.info("  样本 %d: ticker=%s date=%s time=%s source=%s volume=%s value=%s",
                    i + 1, s.get("equ_ticker"), s.get("order_as_of_date"),
                    s.get("mkt_timestamp"), s.get("source"),
                    s.get("volume"), s.get("value"))
    if not passed2:
        logger.error("  ✗ 列特征断言失败：存在不满足空 bar 条件的行，强制 abort")
        return False
    logger.info("  ✓ 列特征断言通过")

    # 闸 3：异常源
    passed3, sources = _gate3_source_whitelist(db_path)
    logger.info("【安全闸 3 - 异常源白名单】允许: %s, 实际: %s", _ALLOWED_SOURCES, sources)
    if not passed3:
        logger.error("  ✗ 异常源检查失败：存在非 bloomberg 的 source，强制 abort")
        return False
    logger.info("  ✓ 异常源检查通过")

    logger.info("dry-run 三道安全闸全部通过，共 %s 行待删除", f"{empty_count:,}")
    return True


def _sha256_file(path: Path) -> str:
    """计算文件 SHA-256。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _create_lightweight_backup(db_path: Path, backup_dir: Path) -> Tuple[Path, Path]:
    """创建轻量备份：snapshot.db + manifest.json。返回 (snapshot_path, manifest_path)。"""
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    snapshot_path = backup_dir / f"raw_bdib_empty_bars_{ts}.db"
    manifest_path = backup_dir / "manifest.json"

    columns = _get_columns(db_path)
    col_list = ", ".join(columns)

    # 通过 ATTACH 在主库连接中创建 snapshot 表（几 MB，不复制 41GB 主库）
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("ATTACH DATABASE ? AS backup", (str(snapshot_path),))
        conn.execute(
            f"CREATE TABLE backup.empty_bars_snapshot AS "
            f"SELECT {col_list} FROM {Config.RAW_BDIB_TABLE} WHERE {EMPTY_BAR_WHERE}"
        )
        count = conn.execute("SELECT COUNT(*) FROM backup.empty_bars_snapshot").fetchone()[0]
        conn.execute("DETACH DATABASE backup")
        conn.commit()
    finally:
        conn.close()

    sha256 = _sha256_file(snapshot_path)
    stat = db_path.stat()
    orig_conn = sqlite3.connect(str(db_path))
    try:
        user_version = orig_conn.execute("PRAGMA user_version").fetchone()[0]
        journal_mode = orig_conn.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        orig_conn.close()

    stats = _gate1_row_stats(db_path)
    manifest = {
        "apply_timestamp": ts,
        "operator": getpass.getuser(),
        "source_db": str(db_path),
        "source_db_size_mb": round(stat.st_size / (1024 * 1024), 2),
        "source_db_mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "source_db_user_version": user_version,
        "source_db_journal_mode": journal_mode,
        "snapshot_file": snapshot_path.name,
        "snapshot_sha256": sha256,
        "snapshot_size_mb": round(snapshot_path.stat().st_size / (1024 * 1024), 4),
        "deleted_row_count": count,
        "columns": columns,
        "empty_bar_stats": stats,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("轻量备份完成: %s (%.2f MB, %d 行)",
                snapshot_path.name, manifest["snapshot_size_mb"], count)
    logger.info("manifest: %s", manifest_path.name)
    return snapshot_path, manifest_path


def _restore(db_path: Path, snapshot_db: Path) -> int:
    """从 snapshot 文件回填空 bar 行。返回回填行数。"""
    if not snapshot_db.exists():
        logger.error("snapshot 文件不存在: %s", snapshot_db)
        return -1

    columns = _get_columns(snapshot_db, table_name="empty_bars_snapshot")
    col_list = ", ".join(columns)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("ATTACH DATABASE ? AS snap", (str(snapshot_db),))
        before = conn.execute(f"SELECT COUNT(*) FROM {Config.RAW_BDIB_TABLE}").fetchone()[0]
        conn.execute(
            f"INSERT OR IGNORE INTO {Config.RAW_BDIB_TABLE} ({col_list}) "
            f"SELECT {col_list} FROM snap.empty_bars_snapshot"
        )
        after = conn.execute(f"SELECT COUNT(*) FROM {Config.RAW_BDIB_TABLE}").fetchone()[0]
        conn.execute("DETACH DATABASE snap")
        conn.commit()
        restored = after - before
        logger.info("回填完成: %d 行 (before=%d, after=%d)", restored, before, after)
        return restored
    finally:
        conn.close()


def _set_user_version(db_path: Path, version: int) -> None:
    """设置 PRAGMA user_version。"""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(f"PRAGMA user_version = {version}")
        conn.commit()
        logger.info("user_version 已设为 %d", version)
    finally:
        conn.close()


def _apply_cleanup(db_path: Path, backup_dir: Path) -> int:
    """执行清理：三道安全闸 → 轻量备份 → DELETE → 验证 → 设 user_version。返回删除行数。"""
    if not _run_dry_run(db_path):
        logger.error("安全闸未通过，abort")
        return -1

    empty_count = _count_empty_bars(db_path)
    if empty_count == 0:
        logger.info("无空 bar 行，仅设 user_version=1")
        _set_user_version(db_path, 1)
        return 0

    # 轻量备份
    snapshot_path, _ = _create_lightweight_backup(db_path, backup_dir)

    # 执行删除
    conn = sqlite3.connect(str(db_path))
    try:
        before = conn.execute(f"SELECT COUNT(*) FROM {Config.RAW_BDIB_TABLE}").fetchone()[0]
        conn.execute("BEGIN")
        cursor = conn.execute(
            f"DELETE FROM {Config.RAW_BDIB_TABLE} WHERE {EMPTY_BAR_WHERE}"
        )
        deleted = cursor.rowcount
        conn.execute("COMMIT")
        after = conn.execute(f"SELECT COUNT(*) FROM {Config.RAW_BDIB_TABLE}").fetchone()[0]
    finally:
        conn.close()

    if deleted != empty_count:
        logger.error("预期删除 %d 行，实际删除 %d 行，正在从 snapshot 回填...", empty_count, deleted)
        _restore(db_path, snapshot_path)
        return -1

    logger.info("删除成功: %d 行 (before=%d, after=%d, 差值=%d)",
                deleted, before, after, before - after)

    # 设 user_version = 1
    _set_user_version(db_path, 1)

    # 验证无残留
    remaining = _count_empty_bars(db_path)
    if remaining > 0:
        logger.warning("清理后仍残留 %d 行空 bar", remaining)
    else:
        logger.info("验证通过：无空 bar 残留")
    return deleted


def main(argv: Optional[List[str]] = None) -> int:
    """主入口：解析参数并分发到 dry-run / apply / restore。"""
    parser = argparse.ArgumentParser(
        description="清理 raw_bdib 中的完全空 bar 行（轻量备份版）",
    )
    parser.add_argument("--dry-run", action="store_true", help="三道安全闸预检，不执行删除")
    parser.add_argument("--apply", action="store_true", help="执行删除（轻量备份 + 三道安全闸）")
    parser.add_argument("--backup-dir", type=str, default="",
                        help="备份目录（默认 CostView/data/_cleanup_backups/raw_bdib_empty_bars_<ts>/）")
    parser.add_argument("--restore", type=str, default="", metavar="SNAPSHOT_DB",
                        help="从 snapshot 文件回填空 bar 行")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format=Config.LOG_FORMAT)
    db_path = _get_db_path()

    # restore 模式
    if args.restore:
        snapshot_db = Path(args.restore).resolve()
        logger.info("restore 模式: 从 %s 回填到 %s", snapshot_db, db_path)
        result = _restore(db_path, snapshot_db)
        return 0 if result >= 0 else 1

    if not db_path.exists():
        logger.error("数据库不存在: %s", db_path)
        return 1

    db_size_mb = db_path.stat().st_size / (1024 * 1024)
    logger.info("数据库: %s (%.0f MB)", db_path, db_size_mb)
    logger.info("SQLite 版本: %s", sqlite3.sqlite_version)

    if args.dry_run:
        return 0 if _run_dry_run(db_path) else 1

    if args.apply:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = Path(args.backup_dir) if args.backup_dir else (
            db_path.parent / "_cleanup_backups" / f"raw_bdib_empty_bars_{ts}"
        )
        result = _apply_cleanup(db_path, backup_dir)
        return 0 if result >= 0 else 1

    logger.info("请使用 --dry-run 预览 / --apply 执行 / --restore <snapshot> 回填")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
