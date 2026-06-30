"""
清理 processed_fills.db 中 209 条孤儿行
(Exchange='NA' 且 equ_ticker 为空，对应 raw_fills 已不存在的 FillId)

背景：
    经 fix_raw_fills_null_exchange.py 修复后，processed_fills.db 中残留 209 行
    Exchange='NA' 且 equ_ticker 为空。深度调查发现：
    - raw_fills 表 PK 为 (OrderId, RouteId, FillId) 不含 source_date
    - 对同一 OrderId，Bloomberg 在后续 fetch 周期会因 API 返回变化 INSERT OR REPLACE
      覆盖早期 fetch 已写入的行，导致 raw 中某些 FillId 被覆盖丢失
      (如 OrderId=5139003 raw 中 FillId 跳过 76, 87)
    - 但 processed_fills 在早期 S2 处理时已写入这些 FillId 行，残留至今

    严格比对：209 个 (OrderId, RouteId, FillId) 元组在 raw_fills 中 100% 不存在
    (已通过 orphan 检测验证)，且无关 route_history / route_event_history
    (route_history 按 order 维度聚合，route_event_history 中无这些 FillId 事件)。

    这些孤儿行不应作为 NA 修复遗产继续存在；本次操作直接从 processed_fills
    中 DELETE 它们，恢复数据一致性。

操作流程：
    1. 预检：列出 (OrderId, RouteId, FillId, order_as_of_date) 元组
    2. invariant 断言：每个元组在 raw_fills 中必须 0 命中（保证真孤儿）
    3. 物理备份 processed_fills.db + execution_history.db
    4. 单事务 DELETE 209 行 + route_event_history 同 PK 行（已知 0，留保护）
    5. 后置校验：processed_fills Exchange='NA' AND equ_ticker 空 = 0
    6. 写 audit JSON + 打印回滚命令

用法:
    python scripts/ops/cleanup_orphan_processed_fills.py --dry-run
    python scripts/ops/cleanup_orphan_processed_fills.py --execute
    python scripts/ops/cleanup_orphan_processed_fills.py --execute --reuse-backup-timestamp 20260630_145302
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
from typing import List, Optional, Tuple

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from DataPipeline.config import Config  # noqa: E402

LOGGER = logging.getLogger("cleanup_orphan_processed_fills")
RAW_LOCK_TIMEOUT_SEC = 30
RAW_LOCK_RETRY_SEC = 1.0


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
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
    if not db_path.exists():
        raise FileNotFoundError(f"数据库不存在: {db_path}")
    backup_path = db_path.with_suffix(db_path.suffix + f".{timestamp}.bak")
    LOGGER.info("备份中: %s -> %s", db_path, backup_path)
    t0 = time.time()
    shutil.copy2(str(db_path), str(backup_path))
    LOGGER.info("备份完成 (%.1fs, size=%d MB)",
                time.time() - t0, backup_path.stat().st_size / (1024 * 1024))
    return backup_path


class _ExclusiveLock:
    def __init__(self, lock_path: Path, label: str) -> None:
        self.lock_path = lock_path
        self.label = label
        self._fd: Optional[int] = None

    def acquire(self) -> None:
        deadline = time.monotonic() + RAW_LOCK_TIMEOUT_SEC
        while True:
            try:
                self._fd = os.open(
                    str(self.lock_path),
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                )
                os.write(self._fd, f"pid={os.getpid()} ts={datetime.now().isoformat()}\n".encode())
                LOGGER.info("获取排他锁: %s", self.lock_path)
                return
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        f"排他锁等待超时 ({RAW_LOCK_TIMEOUT_SEC}s) — {self.label}; "
                        f"请确认 DataPipeline 已停止后删除 {self.lock_path}"
                    )
                LOGGER.warning("锁被占用，等待 %.1fs...", RAW_LOCK_RETRY_SEC)
                time.sleep(RAW_LOCK_RETRY_SEC)

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
            except OSError as e:
                LOGGER.warning("释放锁文件失败: %s", e)


# ── 主体 ────────────────────────────────────────────────────────────────────


def _collect_orphans(proc_conn: sqlite3.Connection) -> List[Tuple[str, str, str, str]]:
    """收集 processed_fills 中 Exchange='NA' 且 equ_ticker 空的孤儿行。"""
    cur = proc_conn.execute("""
        SELECT OrderId, RouteId, FillId, order_as_of_date
        FROM processed_fills
        WHERE Exchange = 'NA' AND (equ_ticker IS NULL OR equ_ticker = '')
    """)
    return cur.fetchall()


def _assert_orphans_in_raw(
    raw_conn: sqlite3.Connection, orphans: List[Tuple[str, str, str, str]]
) -> dict:
    """invariant 断言：每个孤儿 (OrderId, RouteId, FillId) 在 raw_fills 中必须 0 命中。"""
    hit_in_raw = 0
    orphans_verified = 0
    for oid, rid, fid, oad in orphans:
        cur = raw_conn.execute(
            "SELECT 1 FROM raw_fills WHERE OrderId=? AND RouteId=? AND FillId=? LIMIT 1",
            (oid, rid, fid),
        )
        if cur.fetchone() is not None:
            hit_in_raw += 1
            LOGGER.warning("  ⚠ 非 orphan 命中: O=%s R=%s F=%s oad=%s", oid, rid, fid, oad)
        else:
            orphans_verified += 1
    return {
        "orphans_total": len(orphans),
        "orphans_verified_in_raw_absent": orphans_verified,
        "hit_in_raw": hit_in_raw,
    }


def _delete_phase(
    proc_path: Path, exe_path: Path, dry_run: bool,
    orphans: List[Tuple[str, str, str, str]],
) -> dict:
    """单事务 DELETE processed_fills + route_event_history 中的孤儿行。"""
    proc_conn = sqlite3.connect(str(proc_path))
    proc_conn.execute("PRAGMA journal_mode=WAL")
    proc_conn.execute(f"PRAGMA busy_timeout={Config.SQLITE_BUSY_TIMEOUT_MS}")
    exe_conn = sqlite3.connect(str(exe_path))
    exe_conn.execute("PRAGMA journal_mode=WAL")
    exe_conn.execute(f"PRAGMA busy_timeout={Config.SQLITE_BUSY_TIMEOUT_MS}")

    try:
        # 备齐参数 (Order, Route, Fill, oad) × N
        placeholder_block = "(?,?,?,?)"
        block_list = ",".join([placeholder_block] * len(orphans))
        flat_params = []
        for oid, rid, fid, oad in orphans:
            flat_params.extend([oid, rid, fid, oad])

        if dry_run:
            LOGGER.info("[DRY-RUN] 不执行 DELETE")
            # 仅预检实际匹配行数
            cur = proc_conn.execute(
                f"SELECT COUNT(*) FROM processed_fills "
                f"WHERE (OrderId, RouteId, FillId, order_as_of_date) IN ({block_list})",
                flat_params,
            )
            proc_match = cur.fetchone()[0]
            cur = exe_conn.execute(
                f"SELECT COUNT(*) FROM route_event_history "
                f"WHERE (OrderId, RouteId, FillId, order_as_of_date) IN ({block_list})",
                flat_params,
            )
            exe_match = cur.fetchone()[0]
            return {
                "processed_match": proc_match,
                "route_event_match": exe_match,
                "deleted_processed": 0,
                "deleted_route_event": 0,
                "skipped": True,
            }

        # processed_fills 事务
        proc_conn.execute("BEGIN IMMEDIATE")
        cur = proc_conn.execute(
            f"DELETE FROM processed_fills "
            f"WHERE (OrderId, RouteId, FillId, order_as_of_date) IN ({block_list})",
            flat_params,
        )
        deleted_proc = cur.rowcount
        proc_conn.execute("COMMIT")
        LOGGER.info("DELETE processed_fills rowcount = %d", deleted_proc)

        # route_event_history 事务 (预期 0，但为了 idempotent 保护性 DELETE)
        exe_conn.execute("BEGIN IMMEDIATE")
        cur = exe_conn.execute(
            f"DELETE FROM route_event_history "
            f"WHERE (OrderId, RouteId, FillId, order_as_of_date) IN ({block_list})",
            flat_params,
        )
        deleted_evt = cur.rowcount
        exe_conn.execute("COMMIT")
        LOGGER.info("DELETE route_event_history rowcount = %d", deleted_evt)

        return {
            "deleted_processed": deleted_proc,
            "deleted_route_event": deleted_evt,
            "skipped": False,
        }
    except Exception:
        try:
            proc_conn.execute("ROLLBACK")
        except Exception:
            pass
        try:
            exe_conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        proc_conn.close()
        exe_conn.close()


def _post_check(proc_conn: sqlite3.Connection) -> dict:
    cur = proc_conn.execute("""
        SELECT COUNT(*) FROM processed_fills
        WHERE Exchange='NA' AND (equ_ticker IS NULL OR equ_ticker='')
    """)
    return {"residual_orphans": cur.fetchone()[0]}


def _write_audit(audit_path: Path, payload: dict) -> None:
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with audit_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    LOGGER.info("audit 已写入: %s", audit_path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="清理 processed_fills.db 中 209 条孤儿行 (raw 已不存在的 FillId)",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--execute", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--reuse-backup-timestamp",
        metavar="YYYYMMDD_HHMMSS",
        help="复用此前 dry-run/execute 的时间戳备份，跳过物理备份步骤",
    )
    parser.add_argument(
        "--skip-backup",
        action="store_true",
        help="跳过物理备份 (仅在磁盘空间不足且已有完整底线备份时使用); "
             "依赖 DB 事务原子性 + 已有时间戳备份作回滚",
    )
    args = parser.parse_args()

    _setup_logging(args.verbose)

    raw_path = Config.RAW_FILLS_DB
    proc_path = Config.PROCESSED_FILLS_DB
    exe_path = Config.EXECUTION_HISTORY_DB
    for p in (raw_path, proc_path, exe_path):
        if not p.exists():
            LOGGER.error("数据库不存在: %s — 拒绝执行", p)
            return 2

    LOGGER.info("=" * 72)
    LOGGER.info("processed_fills.db 孤儿行清理 (209 个 NA 空白 equ_ticker)")
    LOGGER.info("=" * 72)
    LOGGER.info("  RAW_FILLS_DB      = %s", raw_path)
    LOGGER.info("  PROCESSED_FILLS_DB= %s", proc_path)
    LOGGER.info("  EXECUTION_HISTORY = %s", exe_path)
    LOGGER.info("  模式 = %s", "DRY-RUN" if args.dry_run else "EXECUTE")

    # 1) 预检收集
    LOGGER.info("-" * 72)
    LOGGER.info("[阶段 1] 收集 processed_fills 中 Exchange='NA' 且 equ_ticker 空的行")
    pre_proc = sqlite3.connect(str(proc_path))
    pre_proc.execute("PRAGMA journal_mode=WAL")
    orphans = _collect_orphans(pre_proc)
    pre_proc.close()
    LOGGER.info("  孤儿数 = %d", len(orphans))
    if not orphans:
        LOGGER.info("✓ 无孤儿行，无需清理 — 退出")
        return 0

    # 2) invariant 断言
    LOGGER.info("-" * 72)
    LOGGER.info("[阶段 2] invariant 断言：每孤儿 PK 在 raw_fills 必须 0 命中")
    pre_raw = sqlite3.connect(str(raw_path))
    pre_raw.execute("PRAGMA journal_mode=WAL")
    invariant = _assert_orphans_in_raw(pre_raw, orphans)
    pre_raw.close()
    LOGGER.info("  orphans_total = %d, raw 中已不存在 = %d, 命中反面 = %d",
                invariant["orphans_total"],
                invariant["orphans_verified_in_raw_absent"],
                invariant["hit_in_raw"])
    if invariant["hit_in_raw"] != 0:
        LOGGER.error("✗ invariant 破坏：%d 个孤儿在 raw 中实际存在 — 拒绝执行，需人工排查",
                     invariant["hit_in_raw"])
        return 3
    if invariant["orphans_verified_in_raw_absent"] != invariant["orphans_total"]:
        LOGGER.error("✗ 计数不一致 — 拒绝执行")
        return 3

    # 3) 备份 + SHA-256
    LOGGER.info("-" * 72)
    LOGGER.info("[阶段 3] 物理备份 + SHA-256 指纹")
    if args.reuse_backup_timestamp:
        timestamp = args.reuse_backup_timestamp
        LOGGER.info("  复用既有备份 timestamp=%s", timestamp)
        proc_bak = proc_path.with_suffix(proc_path.suffix + f".{timestamp}.cleanup_orphan.bak")
        exe_bak = exe_path.with_suffix(exe_path.suffix + f".{timestamp}.cleanup_orphan.bak")
        if not args.dry_run:
            for p in (proc_bak, exe_bak):
                if not p.exists():
                    raise FileNotFoundError(f"复用备份不存在: {p}")
    elif args.skip_backup:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        LOGGER.warning("  ⚠ --skip-backup 已启用，跳过物理备份；依赖 DB 事务原子性作安全网")
        proc_bak = proc_path.with_suffix(proc_path.suffix + f".{timestamp}.cleanup_orphan.bak")
        exe_bak = exe_path.with_suffix(exe_path.suffix + f".{timestamp}.cleanup_orphan.bak")
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if args.dry_run:
            LOGGER.info("  [DRY-RUN] 跳过物理备份")
            proc_bak = proc_path.with_suffix(proc_path.suffix + f".{timestamp}.cleanup_orphan.bak")
            exe_bak = exe_path.with_suffix(exe_path.suffix + f".{timestamp}.cleanup_orphan.bak")
        else:
            # 仅备份 processed_fills + execution_history (raw 不动)
            proc_bak = _backup_db(proc_path, timestamp + ".cleanup_orphan")
            exe_bak = _backup_db(exe_path, timestamp + ".cleanup_orphan")

    proc_sha_pre = _sha256_of_file(proc_path)
    exe_sha_pre = _sha256_of_file(exe_path)
    LOGGER.info("  processed_fills SHA-256 (pre) = %s", proc_sha_pre)
    LOGGER.info("  execution_hist  SHA-256 (pre) = %s", exe_sha_pre)

    # 4) 排他锁
    LOGGER.info("-" * 72)
    LOGGER.info("[阶段 4] 创建排他锁")
    lock_path = proc_path.with_name(proc_path.stem + ".cleanup_orphan.lock")
    lock = _ExclusiveLock(lock_path, label="processed_fills orphan cleanup")
    try:
        lock.acquire()

        # 5) DELETE
        LOGGER.info("-" * 72)
        LOGGER.info("[阶段 5] DELETE 孤儿行")
        delete_result = _delete_phase(proc_path, exe_path, dry_run=args.dry_run, orphans=orphans)
        LOGGER.info("  delete_result = %s", delete_result)
    finally:
        lock.release()

    # 6) 后置 SHA-256 + 校验
    proc_sha_post = _sha256_of_file(proc_path)
    exe_sha_post = _sha256_of_file(exe_path)
    LOGGER.info("  processed_fills SHA-256 (post) = %s", proc_sha_post)
    LOGGER.info("  execution_hist  SHA-256 (post) = %s", exe_sha_post)

    post_proc = sqlite3.connect(str(proc_path))
    post_proc.execute("PRAGMA journal_mode=WAL")
    post_check = _post_check(post_proc)
    post_proc.close()
    LOGGER.info("  后置残余孤儿 = %d (期望 0)", post_check["residual_orphans"])

    # 7) audit JSON
    audit_path = _REPO_ROOT / "scripts" / "ops" / f"cleanup_orphan_processed_fills_audit_{timestamp}.json"
    audit_payload = {
        "timestamp": timestamp,
        "mode": "dry-run" if args.dry_run else "execute",
        "database_paths": {
            "processed_fills": str(proc_path),
            "execution_history": str(exe_path),
            "raw_fills_for_invariant": str(raw_path),
        },
        "backups": {
            "processed_fills": str(proc_bak),
            "execution_history": str(exe_bak),
        },
        "pre_sha256": {
            "processed_fills": proc_sha_pre,
            "execution_history": exe_sha_pre,
        },
        "post_sha256": {
            "processed_fills": proc_sha_post,
            "execution_history": exe_sha_post,
        },
        "orphan_count": len(orphans),
        "orphans_sample": orphans[:10],
        "invariant_check": invariant,
        "delete_result": delete_result,
        "post_check_residual_orphans": post_check["residual_orphans"],
        "background": (
            "raw_fills 表 PK 为 (OrderId, RouteId, FillId) 不含 source_date；"
            "Bloomberg 重复 fetch 同 OrderId 时新数据 INSERT OR REPLACE 跨日覆盖早期写入行，"
            "导致某些 FillId 在 raw 中丢失但 processed_fills 中残留。"
            "本次清理是删除这些孤儿行，恢复数据一致性。"
        ),
    }
    _write_audit(audit_path, audit_payload)

    # 8) 回滚提示
    LOGGER.info("=" * 72)
    LOGGER.info("回滚预案 (如清理后发现 TCA 缺失该成交)")
    LOGGER.info("=" * 72)
    print(f"""
# 1. 停止 DataPipeline / backend 服务
# 2. 还原备份:
cd "{Config.DATA_DIR}"
Move-Item processed_fills.db processed_fills.db.broken.{timestamp} -Force
Move-Item "{proc_bak.name}" processed_fills.db -Force
# execution_history 通常 0 行实际被 DELETE，仅在严重事故时还原:
# Move-Item "{exe_bak.name}" execution_history.db -Force
# 3. 重启服务并验证:TCA 查询是否恢复 (建议同时联系 Bloomberg 重新拉取缺失 FillId)
""")

    LOGGER.info("=" * 72)
    overall_ok = (post_check["residual_orphans"] == 0)
    if args.dry_run:
        LOGGER.info("✓ dry-run 完成，未修改数据。audit: %s", audit_path)
    elif overall_ok:
        LOGGER.info("✓ 整体执行 PASS — 孤儿行已全部清理。audit: %s", audit_path)
    else:
        LOGGER.error("✗ 后置校验失败 — residual_orphans = %d", post_check["residual_orphans"])
    LOGGER.info("=" * 72)
    return 0 if (args.dry_run or overall_ok) else 1


if __name__ == "__main__":
    sys.exit(main())