"""
一次性历史数据修复脚本: raw_fills.db Exchange NULL -> 'NA'

背景：
    经手工比对验证，raw_fills.db 中 Exchange IS NULL 的 64,450 行全部是
    荷兰 (Euronext Amsterdam, BBG yellow key = 'NA') 股票成交。
    Bloomberg EMSX API 对欧洲 MTF 成交常常缺失 Exchange 字段，下游
    fill_processor.add_equity_ticker 因 Exchange 空白将 equ_ticker 置 NULL，
    导致 processed_fills 链路与 CostView TCA JOIN 失配。

    用户已手工核实：这批行 100% 为 Currency='EUR' + 28 个荷兰蓝筹 ticker。
    本次操作仅做 NULL -> 'NA' 单值映射，不动其他行。

操作流程（单进程顺序执行）：
    1. 项目根定位 + Config 路径解析
    2. 物理备份 raw_fills.db / processed_fills.db / execution_history.db
    3. SHA-256 记录修改前指纹
    4. 创建排他锁文件 (.migration.lock 等价语义)
    5. 预检断言: NULL 行数 + 全部 Currency=EUR invariant
    6. 动态读取受影响 distinct source_date 列表
    7. BEGIN IMMEDIATE 单事务 UPDATE → 校验 → COMMIT
    8. 清理 processed_fills.db 下游: processed_fills/processing_log 中
       受影响日期的旧行 (供 S2 重跑前清场)
    9. 写 audit JSON (含受影响日期清单、SHA-256、备份路径)
    10. 释放锁
    11. 打印 S2 重跑命令清单 + 回滚命令

用法:
    python scripts/ops/fix_raw_fills_null_exchange.py --dry-run
    python scripts/ops/fix_raw_fills_null_exchange.py --execute
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
from typing import List, Optional

# 确保可 import DataPipeline (仓库根路径)
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from DataPipeline.config import Config  # noqa: E402

# ── 常量 ────────────────────────────────────────────────────────────────────

LOGGER = logging.getLogger("fix_raw_fills_null_exchange")
EXPECTED_FIX_VALUE = "NA"          # 待写入的合法 BBG yellow key
EUR_CCY = "EUR"
RAW_LOCK_TIMEOUT_SEC = 30
RAW_LOCK_RETRY_SEC = 1.0

# 受影响的下游 stage 标记 (S2 / S3 写入)
# 保留 'bdib_integrated' 等 BDIB 阶段不动，避免触发 BBG 重拉
DOWNSTREAM_STAGES_TO_CLEAR = ("processed", "aggregated")

# ── 日志配置 ────────────────────────────────────────────────────────────────


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Windows 默认 cp1252/cp936 控制台对 unicode 字符敏感，强制 stdout 用 utf-8
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass


# ── 工具：SHA-256 ────────────────────────────────────────────────────────────


def _sha256_of_file(path: Path) -> str:
    """计算大文件 SHA-256，分块 8 MiB 读取避免内存爆炸。"""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


# ── 工具：备份 ────────────────────────────────────────────────────────────────


def _backup_db(db_path: Path, timestamp: str) -> Path:
    """创建物理备份: {db}.{timestamp}.bak"""
    if not db_path.exists():
        raise FileNotFoundError(f"数据库不存在: {db_path}")
    backup_path = db_path.with_suffix(db_path.suffix + f".{timestamp}.bak")
    # copy2 保留元数据；DB 3.7GB 约 30~90s
    LOGGER.info("备份中: %s -> %s", db_path, backup_path)
    t0 = time.time()
    shutil.copy2(str(db_path), str(backup_path))
    LOGGER.info("备份完成 (%.1fs, size=%d MB)",
                time.time() - t0, backup_path.stat().st_size / (1024 * 1024))
    return backup_path


# ── 工具：排他锁 ─────────────────────────────────────────────────────────────


class _ExclusiveLock:
    """基于 os.O_CREAT|O_EXCL 的跨进程排他锁。

    与 MigrationRunner._acquire_lock 等价语义：独占锁定 raw_fills.db，
    防止 DataPipeline / MigrationRunner 同时介入。
    """

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


# ── 主体：raw_fills UPDATE ──────────────────────────────────────────────────


def _precheck_raw_fills_null(conn: sqlite3.Connection) -> dict:
    """预检断言: 收集 NULL 行统计 + 受影响日期清单 + invariant 校验。"""
    cur = conn.execute(
        "SELECT COUNT(*) FROM raw_fills WHERE Exchange IS NULL"
    )
    null_count = cur.fetchone()[0]

    cur = conn.execute(
        "SELECT COUNT(*) FROM raw_fills WHERE Exchange IS NULL AND Currency = ?",
        (EUR_CCY,),
    )
    null_eur_count = cur.fetchone()[0]

    cur = conn.execute(
        "SELECT COUNT(*) FROM raw_fills"
    )
    total = cur.fetchone()[0]

    cur = conn.execute(
        "SELECT COUNT(*) FROM raw_fills WHERE Exchange = ?",
        (EXPECTED_FIX_VALUE,),
    )
    na_count_before = cur.fetchone()[0]

    cur = conn.execute(
        "SELECT DISTINCT source_date FROM raw_fills "
        "WHERE Exchange IS NULL AND source_date IS NOT NULL AND source_date != '' "
        "ORDER BY source_date"
    )
    affected_dates = [r[0] for r in cur.fetchall()]

    return {
        "null_count": null_count,
        "null_eur_count": null_eur_count,
        "total_rows": total,
        "na_count_before": na_count_before,
        "affected_dates": affected_dates,
    }


def _raw_update_phase(
    db_path: Path, dry_run: bool, pre_stats: dict,
) -> dict:
    """raw_fills.db 单事务 UPDATE，返回后置统计。"""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA busy_timeout={Config.SQLITE_BUSY_TIMEOUT_MS}")

    try:
        # BEGIN IMMEDIATE 立即获取写锁，避免 concurrency surprise
        conn.execute("BEGIN IMMEDIATE")
        LOGGER.info("BEGIN IMMEDIATE 已获取写锁")

        # 预检 invariant (事务内复检，防止 dry/run 之间状态漂移)
        cur = conn.execute("SELECT COUNT(*) FROM raw_fills WHERE Exchange IS NULL")
        null_in_txn = cur.fetchone()[0]
        if null_in_txn != pre_stats["null_count"]:
            raise RuntimeError(
                f"事务内 NULL 计数漂移: dry-run={pre_stats['null_count']}, "
                f"事务={null_in_txn} — 疑似他进程并发写入"
            )
        cur = conn.execute(
            "SELECT COUNT(*) FROM raw_fills WHERE Exchange IS NULL AND Currency != ?",
            (EUR_CCY,),
        )
        non_eur_null = cur.fetchone()[0]
        if non_eur_null != 0:
            raise RuntimeError(
                f"invariant 破坏: 存在 {non_eur_null} 行非 EUR 且 Exchange IS NULL; "
                "本次修复仅授权 EUR 荷兰股票 → 终止以防误改"
            )

        if dry_run:
            LOGGER.info("[DRY-RUN] 不执行 UPDATE，回滚事务")
            conn.execute("ROLLBACK")
            return {"updated": 0, "skipped": True}

        # 关键 UPDATE
        cur = conn.execute(
            "UPDATE raw_fills SET Exchange = ? WHERE Exchange IS NULL",
            (EXPECTED_FIX_VALUE,),
        )
        updated = cur.rowcount
        LOGGER.info("UPDATE rowcount = %d", updated)
        if updated != pre_stats["null_count"]:
            raise RuntimeError(
                f"UPDATE rowcount 不匹配: 期望 {pre_stats['null_count']}, 实际 {updated}"
            )

        # 后置校验 (事务内)
        cur = conn.execute("SELECT COUNT(*) FROM raw_fills WHERE Exchange IS NULL")
        null_after = cur.fetchone()[0]
        if null_after != 0:
            raise RuntimeError(f"事务内校验失败: 仍有 {null_after} 行 NULL")

        cur = conn.execute(
            "SELECT COUNT(*) FROM raw_fills WHERE Exchange = ?",
            (EXPECTED_FIX_VALUE,),
        )
        na_after = cur.fetchone()[0]
        expected_na = pre_stats["na_count_before"] + pre_stats["null_count"]
        if na_after != expected_na:
            raise RuntimeError(
                f"NA 计数校验失败: 期望 {expected_na}, 实际 {na_after}"
            )

        cur = conn.execute("SELECT COUNT(*) FROM raw_fills")
        total_after = cur.fetchone()[0]
        if total_after != pre_stats["total_rows"]:
            raise RuntimeError(
                f"总行数变化: 修改前 {pre_stats['total_rows']}, 修改后 {total_after}"
            )

        conn.execute("COMMIT")
        LOGGER.info("COMMIT 成功 — raw_fills.db 已修复")

        return {
            "updated": updated,
            "null_after": null_after,
            "na_after": na_after,
            "total_after": total_after,
            "skipped": False,
        }
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        conn.close()


# ── 主体：下游 processed_fills 清场 ────────────────────────────────────────────


def _processed_cleanup_phase(
    db_path: Path, affected_dates: List[str], dry_run: bool,
) -> dict:
    """清理 processed_fills.db 中受影响日期的下游数据，供 S2 重跑。"""
    if dry_run:
        LOGGER.info("[DRY-RUN] 不清理 processed_fills.db")
        return {"deleted_processed_rows": 0, "deleted_log_rows": 0, "skipped": True}

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA busy_timeout={Config.SQLITE_BUSY_TIMEOUT_MS}")
    placeholders = ", ".join("?" * len(affected_dates))

    try:
        conn.execute("BEGIN IMMEDIATE")
        LOGGER.info("清理 processed_fills: %d 个日期", len(affected_dates))

        # 1) processed_fills 表
        cur = conn.execute(
            f"DELETE FROM processed_fills WHERE order_as_of_date IN ({placeholders})",
            affected_dates,
        )
        deleted_rows = cur.rowcount
        LOGGER.info("  processed_fills 删除 %d 行", deleted_rows)

        # 2) processing_log 表 (S2 'processed' / S3 'aggregated')
        stage_placeholders = ", ".join("?" * len(DOWNSTREAM_STAGES_TO_CLEAR))
        cur = conn.execute(
            f"DELETE FROM processing_log "
            f"WHERE order_as_of_date IN ({placeholders}) "
            f"AND stage IN ({stage_placeholders})",
            (*affected_dates, *DOWNSTREAM_STAGES_TO_CLEAR),
        )
        deleted_log = cur.rowcount
        LOGGER.info("  processing_log 删除 %d 行 (stage=%s)",
                    deleted_log, DOWNSTREAM_STAGES_TO_CLEAR)

        conn.execute("COMMIT")
        LOGGER.info("processed_fills 清场完成")
        return {
            "deleted_processed_rows": deleted_rows,
            "deleted_log_rows": deleted_log,
            "skipped": False,
        }
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        conn.close()


# ── 主体：写 audit JSON ────────────────────────────────────────────────────────


def _write_audit(
    audit_path: Path, payload: dict,
) -> None:
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with audit_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    LOGGER.info("audit 已写入: %s", audit_path)


# ── 主体：打印回滚提示 ─────────────────────────────────────────────────────────


def _print_rollback_instructions(
    timestamp: str, raw_bak: Path, proc_bak: Path, exe_bak: Path,
) -> None:
    LOGGER.info("=" * 72)
    LOGGER.info("回滚预案 (如修改后发现问题)")
    LOGGER.info("=" * 72)
    print(f"""
# 1. 停止 DataPipeline / backend 服务
# 2. 还原三个备份 (raw_fills.db / processed_fills.db / execution_history.db):
cd "{Config.DATA_DIR}"
Move-Item raw_fills.db raw_fills.db.broken.{timestamp} -Force
Move-Item processed_fills.db processed_fills.db.broken.{timestamp} -Force
Move-Item "{raw_bak.name}" raw_fills.db -Force
Move-Item "{proc_bak.name}" processed_fills.db -Force
# execution_history.db 备份未变更，仅在严重事故时还原:
# Move-Item "{exe_bak.name}" execution_history.db -Force
# 3. 重启服务并校验 raw_fills NULL 行已恢复
""")


def _print_replay_instructions(affected_dates: List[str]) -> None:
    LOGGER.info("=" * 72)
    LOGGER.info("S2 重跑命令清单 (逐日执行, 共 %d 日)", len(affected_dates))
    LOGGER.info("=" * 72)
    lines = ["// S2 重跑命令清单 — 修复后逐日复活 processed_fills 链路"]
    for d in affected_dates:
        lines.append(f"python -m DataPipeline --date {d} --skip-bdib --once")
    # 同时写到文件方便后续逐条复制
    replay_path = _REPO_ROOT / "scripts" / "ops" / f"replay_s2_affected_dates.txt"
    replay_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[S2 重跑清单已写入] {replay_path}\n")
    # 打印前 5 行 + 总数摘要
    for ln in lines[1:6]:
        print(f"    {ln}")
    if len(affected_dates) > 5:
        print(f"    ... (共 {len(affected_dates)} 日, 见上述文件)")


# ── 主入口 ───────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description="一次性修复 raw_fills.db Exchange NULL -> 'NA' (仅 EUR 荷兰股票)",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="只做预检/备份，不执行 UPDATE")
    mode.add_argument("--execute", action="store_true", help="执行修复 (包括备份+UPDATE+下游清场)")
    parser.add_argument("--verbose", action="store_true", help="DEBUG 日志")
    parser.add_argument(
        "--reuse-backup-timestamp",
        metavar="YYYYMMDD_HHMMSS",
        help="复用此前 dry-run / execute 产生的时间戳备份，跳过物理备份步骤"
             "（如 dry-run 已备份可传入其 timestamp 避免重复 I/O）",
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
    LOGGER.info("raw_fills.db Exchange NULL -> 'NA' 修复")
    LOGGER.info("=" * 72)
    LOGGER.info("DATA_DIR          = %s", Config.DATA_DIR)
    LOGGER.info("RAW_FILLS_DB      = %s", raw_path)
    LOGGER.info("PROCESSED_FILLS_DB= %s", proc_path)
    LOGGER.info("EXECUTION_HISTORY = %s", exe_path)
    LOGGER.info("模式 = %s", "DRY-RUN" if args.dry_run else "EXECUTE")

    # 1) 预检 (read-only)
    LOGGER.info("-" * 72)
    LOGGER.info("[阶段 1] 预检 raw_fills.db NULL 分布 (read-only)")
    pre_conn = sqlite3.connect(str(raw_path))
    pre_conn.execute("PRAGMA journal_mode=WAL")
    pre_stats = _precheck_raw_fills_null(pre_conn)
    pre_conn.close()
    LOGGER.info("  total_rows       = %d", pre_stats["total_rows"])
    LOGGER.info("  null_count       = %d", pre_stats["null_count"])
    LOGGER.info("  null_eur_count   = %d (invariant: 必须等于 null_count)",
                pre_stats["null_eur_count"])
    LOGGER.info("  na_count_before  = %d (修改前 NA 行数)", pre_stats["na_count_before"])
    LOGGER.info("  affected_dates   = %d 个 source_date", len(pre_stats["affected_dates"]))
    if pre_stats["affected_dates"]:
        LOGGER.info("    min date = %s", pre_stats["affected_dates"][0])
        LOGGER.info("    max date = %s", pre_stats["affected_dates"][-1])

    if pre_stats["null_count"] == 0:
        LOGGER.info("✓ 已无 NULL 行，无需修复 — 退出")
        return 0

    if pre_stats["null_eur_count"] != pre_stats["null_count"]:
        LOGGER.error(
            "✗ invariant 破坏: NULL 中存在非 EUR 行 (%d) — 拒绝执行, 请人工排查",
            pre_stats["null_count"] - pre_stats["null_eur_count"],
        )
        return 3

    # 2) 备份 + SHA-256
    LOGGER.info("-" * 72)
    LOGGER.info("[阶段 2] 物理备份 + SHA-256 指纹")
    if args.reuse_backup_timestamp:
        # 复用此前 dry-run / execute 产生的备份
        timestamp = args.reuse_backup_timestamp
        LOGGER.info("  复用既有备份 timestamp=%s (跳过物理 I/O)", timestamp)
        raw_bak = raw_path.with_suffix(raw_path.suffix + f".{timestamp}.bak")
        proc_bak = proc_path.with_suffix(proc_path.suffix + f".{timestamp}.bak")
        exe_bak = exe_path.with_suffix(exe_path.suffix + f".{timestamp}.bak")
        if not args.dry_run:
            for p in (raw_bak, proc_bak, exe_bak):
                if not p.exists():
                    raise FileNotFoundError(f"复用备份不存在: {p}")
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        # dry-run 不修改数据，跳过物理备份（节省 ~33GB I/O）；execute 才做完整备份
        if args.dry_run:
            LOGGER.info("  [DRY-RUN] 跳过物理备份")
            raw_bak = raw_path.with_suffix(raw_path.suffix + f".{timestamp}.bak")
            proc_bak = proc_path.with_suffix(proc_path.suffix + f".{timestamp}.bak")
            exe_bak = exe_path.with_suffix(exe_path.suffix + f".{timestamp}.bak")
        else:
            raw_bak = _backup_db(raw_path, timestamp)
            proc_bak = _backup_db(proc_path, timestamp)
            exe_bak = _backup_db(exe_path, timestamp)
    raw_sha_pre = _sha256_of_file(raw_path)
    proc_sha_pre = _sha256_of_file(proc_path)
    exe_sha_pre = _sha256_of_file(exe_path)
    LOGGER.info("  raw_fills.db   SHA-256 (pre)  = %s", raw_sha_pre)
    LOGGER.info("  processed_fills SHA-256 (pre) = %s", proc_sha_pre)
    LOGGER.info("  execution_hist SHA-256 (pre) = %s", exe_sha_pre)

    # 3) 排他锁
    LOGGER.info("-" * 72)
    LOGGER.info("[阶段 3] 创建排他锁 (等同 MigrationRunner 文件锁)")
    lock_path = raw_path.with_name(raw_path.stem + ".fix_null_exchange.lock")
    lock = _ExclusiveLock(lock_path, label="raw_fills.db NULL Exchange fix")
    try:
        lock.acquire()

        # 4) 修改 raw_fills.db
        LOGGER.info("-" * 72)
        LOGGER.info("[阶段 4] UPDATE raw_fills.db")
        update_result = _raw_update_phase(raw_path, dry_run=args.dry_run, pre_stats=pre_stats)
        LOGGER.info("  update_result = %s", update_result)

        # 5) 下游 processed_fills.db 清场
        LOGGER.info("-" * 72)
        LOGGER.info("[阶段 5] 清空 processed_fills.db 受影响日期下游数据")
        cleanup_result = _processed_cleanup_phase(
            proc_path, pre_stats["affected_dates"], dry_run=args.dry_run,
        )
        LOGGER.info("  cleanup_result = %s", cleanup_result)

    finally:
        lock.release()

    # 6) 修改后 SHA-256
    raw_sha_post = _sha256_of_file(raw_path)
    proc_sha_post = _sha256_of_file(proc_path)
    LOGGER.info("  raw_fills.db  SHA-256 (post) = %s", raw_sha_post)
    LOGGER.info("  processed_fills SHA-256(post) = %s", proc_sha_post)

    # 7) audit JSON
    audit_path = _REPO_ROOT / "scripts" / "ops" / f"fix_raw_fills_null_exchange_audit_{timestamp}.json"
    audit_payload = {
        "timestamp": timestamp,
        "mode": "dry-run" if args.dry_run else "execute",
        "database_paths": {
            "raw_fills": str(raw_path),
            "processed_fills": str(proc_path),
            "execution_history": str(exe_path),
        },
        "backups": {
            "raw_fills": str(raw_bak),
            "processed_fills": str(proc_bak),
            "execution_history": str(exe_bak),
        },
        "pre_sha256": {
            "raw_fills": raw_sha_pre,
            "processed_fills": proc_sha_pre,
            "execution_history": exe_sha_pre,
        },
        "post_sha256": {
            "raw_fills": raw_sha_post,
            "processed_fills": proc_sha_post,
        },
        "pre_stats": pre_stats,
        "update_result": update_result,
        "cleanup_result": cleanup_result,
        "affected_dates": pre_stats["affected_dates"],
        "expected_fix_value": EXPECTED_FIX_VALUE,
        "eur_invariant": (
            "所有 Exchange IS NULL 行 Currency 已确认 = 'EUR'; "
            "本次操作是用户手工验证后的 NULL -> 'NA' 单值映射"
        ),
    }
    _write_audit(audit_path, audit_payload)

    # 8) 回滚 + S2 重跑提示
    _print_rollback_instructions(timestamp, raw_bak, proc_bak, exe_bak)
    if not args.dry_run:
        _print_replay_instructions(pre_stats["affected_dates"])
    else:
        LOGGER.info("[DRY-RUN] 未修改数据，无需 S2 重跑")

    LOGGER.info("=" * 72)
    LOGGER.info("✓ 完成 (mode=%s)", "DRY-RUN" if args.dry_run else "EXECUTE")
    LOGGER.info("  audit: %s", audit_path)
    LOGGER.info("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())