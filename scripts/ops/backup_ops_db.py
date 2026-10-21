"""运营库（SQLite）在线热备脚本（DL-02/060）。

用法：
    python scripts/ops/backup_ops_db.py [--db <path>] [--dest <dir>]

    --db    运营库文件路径；默认按 backend/api/config.py 解析
            （EMSXVIEW_OPS_DB_DIR 或用户主目录 .emsxview/ops/emsx_ops.db）
    --dest  备份输出目录；默认取环境变量 EMSXVIEW_OPS_DB_BACKUP_DIR，
            未设则取库文件同级 backups/ 目录

输出：emsx_ops_YYYYMMDD_HHMMSS.db（sqlite3 在线备份 API，WAL 模式下安全，
不阻塞后端写入）。退出码 0=成功、1=失败（供计划任务告警接线）。

月度恢复演练清单（docstring 常驻，演练结果回填 ADR-0022）：
    1. 复制最近一份备份到演练目录；
    2. sqlite3 <备份> "PRAGMA integrity_check;" 应返回 ok；
    3. 以副本为 DATABASE_URL 启动后端：
       DATABASE_URL=sqlite+aiosqlite:///<演练目录>/emsx_ops_YYYYMMDD_HHMMSS.db
       ENABLE_DB_PERSISTENCE=true；
    4. 抽查 orders/routes 行数与备份前一日一致、授权记录可读；
    5. 在 ADR-0022「验证记录」节登记演练日期与结论。
"""

from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# 备份脚本不需要 JWT——import backend config 前显式 bypass，避免启动校验拦截
os.environ.setdefault("BYPASS_AUTH", "true")

# ── 路径设置（脚本直接运行时需要仓库根与 backend/api）──
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent.parent
_API_ROOT = _PROJECT_ROOT / "backend" / "api"
for _p in [_API_ROOT, _PROJECT_ROOT]:
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from config import resolve_ops_db_dir, settings  # noqa: E402

logger = logging.getLogger(__name__)


def default_db_path() -> Path:
    """运营库默认路径（与 db.get_database_url 的 SQLite 分支同源）。"""
    return Path(resolve_ops_db_dir()) / settings.OPS_DB_FILE_NAME


def backup(db_path: Path, dest_dir: Path) -> Path:
    """在线热备：sqlite3 backup API，WAL 安全；返回备份文件路径。"""
    if not db_path.exists():
        raise FileNotFoundError(f"运营库不存在: {db_path}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = dest_dir / f"emsx_ops_{stamp}.db"

    source = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        target_conn = sqlite3.connect(str(target))
        try:
            source.backup(target_conn)
        finally:
            target_conn.close()
    finally:
        source.close()
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="运营库 SQLite 在线热备（DL-02/060）")
    parser.add_argument("--db", default="", help="运营库文件路径（默认按 config 解析）")
    parser.add_argument("--dest", default="", help="备份目录（默认 EMSXVIEW_OPS_DB_BACKUP_DIR 或库同级 backups/）")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    db_path = Path(args.db) if args.db else default_db_path()
    dest_dir = Path(args.dest) if args.dest else Path(os.getenv("EMSXVIEW_OPS_DB_BACKUP_DIR", "")) or db_path.parent / "backups"

    try:
        target = backup(db_path, dest_dir)
    except Exception as exc:
        logger.error("备份失败: %s", exc)
        return 1

    size_mb = target.stat().st_size / (1024 * 1024)
    logger.info("备份完成: %s (%.2f MB)", target, size_mb)
    logger.info("恢复演练见脚本 docstring 清单（月度，结果回填 ADR-0022）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
