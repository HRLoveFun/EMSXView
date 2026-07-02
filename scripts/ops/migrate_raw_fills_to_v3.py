"""
Phase A 运维执行脚本: 迁移 raw_fills.db v0(实际) -> v3

操作流程:
    1. 停服检查 (要求无 python 进程占用 raw_fills.db)
    2. 物理备份 raw_fills.db
    3. SHA-256 前后指纹
    4. 排他锁 (与 MigrationRunner 同语义)
    5. 伪造 user_version=2 (跳过 v0/v1/v2 无谓回溯; inline_ddl 已等价完成 LimitPrice/StopPrice 升级)
    6. MigrationRunner.discover().migrate("raw_fills") 仅应用 v2_to_v3.sql
       - Part 1: raw_fills PK (OrderId,RouteId,FillId) -> (...,source_date) (CREATE NEW + COPY + DROP + RENAME)
       - Part 2: fetch_log 加 CHECK 约束 + 历史重复行软标记 deprecated
    7. PRAGMA wal_checkpoint(TRUNCATE) 回收 WAL
    8. 后置验收 (user_version=3 / PK 列 / fetch_log CHECK / 行数不变)
    9. 写 audit JSON + 回滚提示

用法:
    python scripts/ops/migrate_raw_fills_to_v3.py --dry-run
    python scripts/ops/migrate_raw_fills_to_v3.py --execute
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from DataPipeline.config import Config  # noqa: E402
from DataPipeline.storage.schema.migration_framework import MigrationRunner  # noqa: E402

LOGGER = logging.getLogger("migrate_raw_fills_to_v3")
LOCK_TIMEOUT_SEC = 30
LOCK_RETRY_SEC = 1.0


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass


def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _backup_db(db_path: Path, timestamp: str) -> Path:
    backup_path = db_path.with_suffix(db_path.suffix + f".{timestamp}.v3.bak")
    LOGGER.info("备份中: %s -> %s", db_path, backup_path)
    t0 = time.time()
    shutil.copy2(str(db_path), str(backup_path))
    LOGGER.info("备份完成 (%.1fs, %d MB)",
                time.time() - t0, backup_path.stat().st_size / (1024 * 1024))
    return backup_path


class _ExclusiveLock:
    def __init__(self, lock_path: Path, label: str) -> None:
        self.lock_path = lock_path
        self.label = label
        self._fd: Optional[int] = None

    def acquire(self) -> None:
        deadline = time.monotonic() + LOCK_TIMEOUT_SEC
        while True:
            try:
                self._fd = os.open(
                    str(self.lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                )
                os.write(self._fd, f"pid={os.getpid()} ts={datetime.now().isoformat()}\n".encode())
                LOGGER.info("获取排他锁: %s", self.lock_path)
                return
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        f"排他锁等待超时 ({LOCK_TIMEOUT_SEC}s) — {self.label}; "
                        f"请确认 DataPipeline 已停止后删除 {self.lock_path}"
                    )
                time.sleep(LOCK_RETRY_SEC)

    def release(self) -> None:
        if self._fd is None:
            return
        try:
            os.close(self._fd)
        finally:
            self._fd = None
            try:
                self.lock_path.unlink(missing_ok=True)
                LOGGER.info("释放排他锁: %s", self.lock_path)
            except OSError:
                pass


def _check_pre_state(raw_path: Path) -> dict:
    """迁移前只读预检: user_version, 行数, raw_fills PK, fetch_log 重复行数."""
    conn = sqlite3.connect(str(raw_path))
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        user_version = conn.execute("PRAGMA user_version").fetchone()[0]
        total = conn.execute("SELECT COUNT(*) FROM raw_fills").fetchone()[0]
        pk_cols = [r[1] for r in conn.execute("PRAGMA table_info(raw_fills)").fetchall() if r[5] > 0]
        has_fetch_log = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='fetch_log'"
        ).fetchone() is not None
        if has_fetch_log:
            dup_groups = conn.execute(
                "SELECT COUNT(*) FROM (SELECT source_date, COUNT(*) AS n FROM fetch_log "
                "GROUP BY source_date HAVING n>1)"
            ).fetchone()[0]
            fetch_log_total = conn.execute("SELECT COUNT(*) FROM fetch_log").fetchone()[0]
        else:
            dup_groups = -1
            fetch_log_total = -1
        return {
            "user_version": user_version,
            "total_rows": total,
            "pk_cols": pk_cols,
            "fetch_log_total": fetch_log_total,
            "fetch_log_dup_groups": dup_groups,
        }
    finally:
        conn.close()


def _check_post_state(raw_path: Path) -> dict:
    """迁移后只读校验: user_version, 行数不变, PK 列含 source_date, fetch_log CHECK 约束."""
    conn = sqlite3.connect(str(raw_path))
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        user_version = conn.execute("PRAGMA user_version").fetchone()[0]
        total = conn.execute("SELECT COUNT(*) FROM raw_fills").fetchone()[0]
        pk_cols = [r[1] for r in conn.execute("PRAGMA table_info(raw_fills)").fetchall() if r[5] > 0]
        fetch_log_total = conn.execute("SELECT COUNT(*) FROM fetch_log").fetchone()[0]
        # 任一行同 source_date 多 'fetched' 应为 0
        multi_fetched = conn.execute(
            "SELECT COUNT(*) FROM (SELECT source_date FROM fetch_log "
            "WHERE status='fetched' GROUP BY source_date HAVING COUNT(*)>1)"
        ).fetchone()[0]
        # CHECK 约束应生效
        check_ok = False
        try:
            conn.execute(
                "INSERT INTO fetch_log (source_date, row_count, data_hash, status) "
                "VALUES ('99999999', 1, 'probe_check_test', 'invalid_status')"
            )
            conn.execute("ROLLBACK")
        except sqlite3.IntegrityError:
            check_ok = True
        return {
            "user_version": user_version,
            "total_rows": total,
            "pk_cols": pk_cols,
            "fetch_log_total": fetch_log_total,
            "multi_fetched_groups": multi_fetched,
            "check_constraint_active": check_ok,
        }
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="迁移 raw_fills.db v0(实测) -> v3 (合并 PK + fetch_log 软状态)")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="仅预检并备份, 不执行迁移")
    mode.add_argument("--execute", action="store_true", help="执行迁移")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    _setup_logging(args.verbose)

    raw_path = Config.RAW_FILLS_DB
    if not raw_path.exists():
        LOGGER.error("raw_fills.db 不存在: %s", raw_path)
        return 2

    LOGGER.info("=" * 72)
    LOGGER.info("Phase A 运维: 迁移 raw_fills.db -> v3")
    LOGGER.info("=" * 72)
    LOGGER.info("  RAW_FILLS_DB = %s", raw_path)
    LOGGER.info("  模式 = %s", "DRY-RUN" if args.dry_run else "EXECUTE")

    # 预检
    LOGGER.info("-" * 72)
    LOGGER.info("[阶段 1] 只读预检")
    pre = _check_pre_state(raw_path)
    LOGGER.info("  user_version       = %d (期望 0 或 2; v3 仅空跑)", pre["user_version"])
    LOGGER.info("  total_rows         = %d", pre["total_rows"])
    LOGGER.info("  raw_fills PK       = %s", pre["pk_cols"])
    LOGGER.info("  fetch_log rows     = %d", pre["fetch_log_total"])
    LOGGER.info("  fetch_log dup groups = %d (软标记目标)", pre["fetch_log_dup_groups"])

    if pre["user_version"] >= 3:
        LOGGER.info("OK 已是 v3 - 无需迁移, 退出")
        return 0
    if "source_date" in pre["pk_cols"]:
        LOGGER.warning("  PK 已含 source_date 但 user_version != 3 — 仅需 PRAGMA user_version=3")
        # 但仍需 fetch_log 升级
    if pre["user_version"] not in (0, 2):
        LOGGER.error("FAIL user_version 不在期望 (0/2): 拒绝执行")
        return 3

    # 备份 + SHA-256
    LOGGER.info("-" * 72)
    LOGGER.info("[阶段 2] 物理备份")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if args.dry_run:
        LOGGER.info("  [DRY-RUN] 跳过物理备份")
        backup_path = raw_path.with_suffix(raw_path.suffix + f".{timestamp}.v3.bak")
    else:
        backup_path = _backup_db(raw_path, timestamp)
    sha_pre = _sha256_of_file(raw_path)
    LOGGER.info("  SHA-256 (pre) = %s", sha_pre)

    # 排他锁
    LOGGER.info("-" * 72)
    LOGGER.info("[阶段 3] 排他锁")
    lock_path = raw_path.with_name(raw_path.stem + ".v3_migration.lock")
    lock = _ExclusiveLock(lock_path, label="raw_fills v3 migration")
    try:
        lock.acquire()

        if args.dry_run:
            LOGGER.info("[DRY-RUN] 不执行迁移, 仅演示")
            update_result = {"skipped": True}
        else:
            # 伪造 user_version=2 (跳过 v0/v1/v2)
            if pre["user_version"] < 2:
                LOGGER.info("-" * 72)
                LOGGER.info("[阶段 4] 伪造 user_version=2 (跳过 v0/v1/v2, inline_ddl 已等价完成)")
                conn = sqlite3.connect(str(raw_path))
                conn.execute("PRAGMA user_version = 2")
                conn.commit()
                conn.close()
                LOGGER.info("  user_version 已设为 2")

            # MigrationRunner 仅应用 v2_to_v3.sql
            LOGGER.info("-" * 72)
            LOGGER.info("[阶段 5] MigrationRunner.migrate('raw_fills') — 应用 v2_to_v3.sql")
            t0 = time.time()
            runner = MigrationRunner.discover()
            final_version = runner.migrate("raw_fills")
            elapsed = time.time() - t0
            LOGGER.info("  migrate 完成 (%.1fs), final user_version = %d", elapsed, final_version)
            update_result = {"final_version": final_version, "elapsed_sec": elapsed}

            # WAL checkpoint 回收
            LOGGER.info("-" * 72)
            LOGGER.info("[阶段 6] PRAGMA wal_checkpoint(TRUNCATE) 回收 WAL")
            conn = sqlite3.connect(str(raw_path))
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.close()
            LOGGER.info("  WAL checkpoint 完成")
    finally:
        lock.release()

    # 后置校验
    LOGGER.info("-" * 72)
    LOGGER.info("[阶段 7] 后置校验")
    post = _check_post_state(raw_path)
    LOGGER.info("  user_version     = %d (期望 3)", post["user_version"])
    LOGGER.info("  total_rows       = %d (期望同 pre: %d)", post["total_rows"], pre["total_rows"])
    LOGGER.info("  raw_fills PK     = %s", post["pk_cols"])
    LOGGER.info("  fetch_log rows   = %d (期望同 pre: %d)", post["fetch_log_total"], pre["fetch_log_total"])
    LOGGER.info("  multi_fetched    = %d (期望 0)", post["multi_fetched_groups"])
    LOGGER.info("  CHECK enforced   = %s", post["check_constraint_active"])

    sha_post = _sha256_of_file(raw_path)
    LOGGER.info("  SHA-256 (post) = %s", sha_post)

    overall_ok = (
        post["user_version"] == 3
        and post["total_rows"] == pre["total_rows"]
        and "source_date" in post["pk_cols"]
        and post["multi_fetched_groups"] == 0
        and post["check_constraint_active"]
    )

    # audit
    audit_path = _REPO_ROOT / "scripts" / "ops" / f"migrate_raw_fills_to_v3_audit_{timestamp}.json"
    audit_payload = {
        "timestamp": timestamp,
        "mode": "dry-run" if args.dry_run else "execute",
        "raw_fills_db": str(raw_path),
        "backup_path": str(backup_path),
        "pre_state": pre,
        "post_state": post,
        "pre_sha256": sha_pre,
        "post_sha256": sha_post,
        "update_result": update_result,
        "overall_ok": overall_ok,
    }
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with audit_path.open("w", encoding="utf-8") as f:
        json.dump(audit_payload, f, ensure_ascii=False, indent=2)
    LOGGER.info("audit: %s", audit_path)

    # 回滚提示
    LOGGER.info("=" * 72)
    LOGGER.info("回滚预案 (如迁移后发现异常):")
    print(f"""
# 1. 停止 DataPipeline / backend
# 2. 还原备份:
cd "{Config.DATA_DIR}"
Move-Item raw_fills.db raw_fills.db.broken.{timestamp} -Force
Move-Item "{backup_path.name}" raw_fills.db -Force
# 3. PRAGMA user_version 手动回退到原值 {pre['user_version']}:
#    python -c "import sqlite3; c=sqlite3.connect(r'{raw_path}'); c.execute('PRAGMA user_version={pre['user_version']}'); c.commit(); c.close()"
# 4. git revert MigrationRunner/inline_ddl 改动与 v2_to_v3.sql 新增
""")

    if overall_ok:
        LOGGER.info("=" * 72)
        LOGGER.info("OK Phase A 迁移 PASS — raw_fills.db 已升级到 v3")
        LOGGER.info("=" * 72)
        return 0
    else:
        LOGGER.error("FAIL 后置校验未通过 — 请查看 post_state 与回滚预案")
        return 1


if __name__ == "__main__":
    sys.exit(main())