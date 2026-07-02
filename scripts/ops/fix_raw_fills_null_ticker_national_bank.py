"""
一次性历史数据修复脚本: raw_fills.db Ticker NULL -> 'NA'
仅限 National Bank of Canada (CAD/CN/NATL BK CANADA)

背景:
    经手工比对验证, raw_fills.db 中 Ticker IS NULL 的 144 行全部对应
    Currency='CAD' + Exchange='CN' + SecurityName='NATL BK CANADA'
    (National Bank of Canada, BBG ticker mnemonic = 'NA', 即 'NA CN Equity').
    Bloomberg EMSX API 在某些 fetch 周期对这批成交整体缺失 Ticker 与
    LocalExchangeSymbol 字段. 144 行 raw 数据是最新版本 (无跨日覆盖, 与
    fix_raw_fills_null_exchange 处理的 64,450 行不同源, 也与 cleanup_orphan
    processed_fills 处理的 209 行孤儿不同根因), 纯属 fetch 当时空缺.

    94 行同 security 正常行 100% 使用 Ticker='NA', canonical 值已被全表反
    查唯一确认. 下游 processed_fills/route_history/route_event_history 中
    对应 144 行 equ_ticker 均为 NULL, order_history 中 35 单完全缺失,
    导致 CostView TCA JOIN 失配.

操作流程 (与 fix_raw_fills_null_exchange.py 11 阶段一致, 差异注明):
    1. 项目根定位 + Config 路径解析
    2. 物理备份 raw_fills.db / processed_fills.db / execution_history.db
    3. SHA-256 记录修改前指纹
    4. 创建排他锁文件
    5. 预检断言: Ticker NULL 行数 + invariant (CAD/CN/NATL BK CANADA 100% 命中)
    6. 动态读取受影响 distinct source_date 列表 + OrderId 清单
    7. BEGIN IMMEDIATE 单事务 UPDATE -> 校验 -> COMMIT
    8. 清理下游: processed_fills + processing_log + execution_history
       (新增 route_history / route_event_history 清场, 与 null_exchange 差异)
    9. 写 audit JSON
    10. 释放锁
    11. 打印 S2 重跑命令清单 + 回滚命令

用法:
    python scripts/ops/fix_raw_fills_null_ticker_national_bank.py --dry-run
    python scripts/ops/fix_raw_fills_null_ticker_national_bank.py --execute
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

LOGGER = logging.getLogger("fix_raw_fills_null_ticker_national_bank")
EXPECTED_FIX_VALUE = "NA"          # National Bank of Canada BBG ticker mnemonic
INVARIANT_CCY = "CAD"
INVARIANT_EXCH = "CN"
INVARIANT_SECNAME = "NATL BK CANADA"
RAW_LOCK_TIMEOUT_SEC = 30
RAW_LOCK_RETRY_SEC = 1.0

# 下游 S2/S3 stage 标记, 仅清这部分避免误触发 BDIB
DOWNSTREAM_STAGES_TO_CLEAR = ("processed", "aggregated")


# ── 日志配置 ────────────────────────────────────────────────────────────────


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


# ── 工具: SHA-256 / 备份 / 排他锁 (完整复刻 null_exchange) ──────────────────


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
    """基于 os.O_CREAT|O_EXCL 的跨进程排他锁, 与 MigrationRunner 等价语义."""

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
                        f"排他锁等待超时 ({RAW_LOCK_TIMEOUT_SEC}s) - {self.label}; "
                        f"请确认 DataPipeline 已停止后删除 {self.lock_path}"
                    )
                LOGGER.warning("锁被占用, 等待 %.1fs...", RAW_LOCK_RETRY_SEC)
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


# ── 主体: 预检 ───────────────────────────────────────────────────────────────


def _precheck_raw_fills_null_ticker(conn: sqlite3.Connection) -> dict:
    """预检: 收集 Ticker NULL 行统计 + invariant 校验 + 受影响 source_date / OrderId."""
    null_count = conn.execute("SELECT COUNT(*) FROM raw_fills WHERE Ticker IS NULL").fetchone()[0]

    # invariant 谓词: Ticker IS NULL 必然对应 (CAD, CN, 'NATL BK CANADA')
    null_invariant_count = conn.execute(
        "SELECT COUNT(*) FROM raw_fills WHERE Ticker IS NULL "
        "AND Currency=? AND Exchange=? AND SecurityName=?",
        (INVARIANT_CCY, INVARIANT_EXCH, INVARIANT_SECNAME),
    ).fetchone()[0]
    null_violation = conn.execute(
        "SELECT COUNT(*) FROM raw_fills WHERE Ticker IS NULL "
        "AND NOT (Currency=? AND Exchange=? AND SecurityName=?)",
        (INVARIANT_CCY, INVARIANT_EXCH, INVARIANT_SECNAME),
    ).fetchone()[0]

    total = conn.execute("SELECT COUNT(*) FROM raw_fills").fetchone()[0]
    na_ticker_before = conn.execute(
        "SELECT COUNT(*) FROM raw_fills WHERE Ticker=?", (EXPECTED_FIX_VALUE,)
    ).fetchone()[0]

    affected_dates = [r[0] for r in conn.execute(
        "SELECT DISTINCT source_date FROM raw_fills "
        "WHERE Ticker IS NULL AND source_date IS NOT NULL AND source_date != '' "
        "ORDER BY source_date"
    ).fetchall()]
    affected_orders = [r[0] for r in conn.execute(
        "SELECT DISTINCT OrderId FROM raw_fills WHERE Ticker IS NULL ORDER BY OrderId"
    ).fetchall()]

    return {
        "null_count": null_count,
        "null_invariant_count": null_invariant_count,
        "null_violation": null_violation,
        "total_rows": total,
        "na_ticker_before": na_ticker_before,
        "affected_dates": affected_dates,
        "affected_orders": affected_orders,
    }


# ── 主体: raw_fills UPDATE ───────────────────────────────────────────────────


def _raw_update_phase(db_path: Path, dry_run: bool, pre_stats: dict) -> dict:
    """单事务 UPDATE raw_fills SET Ticker=NA WHERE invariant 谓词."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA busy_timeout={Config.SQLITE_BUSY_TIMEOUT_MS}")

    try:
        conn.execute("BEGIN IMMEDIATE")
        LOGGER.info("BEGIN IMMEDIATE 已获取写锁")

        # 事务内复检 invariant
        null_in_txn = conn.execute("SELECT COUNT(*) FROM raw_fills WHERE Ticker IS NULL").fetchone()[0]
        if null_in_txn != pre_stats["null_count"]:
            raise RuntimeError(
                f"事务内 NULL 计数漂移: dry={pre_stats['null_count']}, txn={null_in_txn}"
            )
        violation = conn.execute(
            "SELECT COUNT(*) FROM raw_fills WHERE Ticker IS NULL "
            "AND NOT (Currency=? AND Exchange=? AND SecurityName=?)",
            (INVARIANT_CCY, INVARIANT_EXCH, INVARIANT_SECNAME),
        ).fetchone()[0]
        if violation != 0:
            raise RuntimeError(
                f"invariant 破坏: {violation} 行非 CAD/CN/NATL BK CANADA 且 Ticker NULL - 终止"
            )

        if dry_run:
            LOGGER.info("[DRY-RUN] 不执行 UPDATE, 回滚事务")
            conn.execute("ROLLBACK")
            return {"updated": 0, "skipped": True}

        # 关键 UPDATE - 严格按 invariant 谓词限定, 绝不误伤其他行
        cur = conn.execute(
            "UPDATE raw_fills SET Ticker=? WHERE Ticker IS NULL "
            "AND Currency=? AND Exchange=? AND SecurityName=?",
            (EXPECTED_FIX_VALUE, INVARIANT_CCY, INVARIANT_EXCH, INVARIANT_SECNAME),
        )
        updated = cur.rowcount
        LOGGER.info("UPDATE rowcount = %d", updated)
        if updated != pre_stats["null_count"]:
            raise RuntimeError(
                f"UPDATE rowcount 不匹配: 期望 {pre_stats['null_count']}, 实际 {updated}"
            )

        # 后置校验
        null_after = conn.execute("SELECT COUNT(*) FROM raw_fills WHERE Ticker IS NULL").fetchone()[0]
        if null_after != 0:
            raise RuntimeError(f"事务内校验失败: 仍有 {null_after} 行 NULL")
        na_after = conn.execute(
            "SELECT COUNT(*) FROM raw_fills WHERE Ticker=?", (EXPECTED_FIX_VALUE,)
        ).fetchone()[0]
        expected_na = pre_stats["na_ticker_before"] + pre_stats["null_count"]
        if na_after != expected_na:
            raise RuntimeError(f"NA 计数校验失败: 期望 {expected_na}, 实际 {na_after}")
        total_after = conn.execute("SELECT COUNT(*) FROM raw_fills").fetchone()[0]
        if total_after != pre_stats["total_rows"]:
            raise RuntimeError(
                f"总行数变化: {pre_stats['total_rows']} -> {total_after}"
            )
        conn.execute("COMMIT")
        LOGGER.info("COMMIT 成功 - raw_fills.db 已修复")
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


# ── 主体: 下游清场 (processed_fills + processing_log) ──────────────────────────


def _processed_cleanup_phase(
    db_path: Path, affected_dates: List[str], dry_run: bool,
) -> dict:
    """清理 processed_fills.db 中受影响日期的下游数据."""
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

        cur = conn.execute(
            f"DELETE FROM processed_fills WHERE order_as_of_date IN ({placeholders})",
            affected_dates,
        )
        deleted_rows = cur.rowcount
        LOGGER.info("  processed_fills 删除 %d 行", deleted_rows)

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


# ── 主体: 下游清场 (execution_history - 本 Phase 差异新增) ────────────────


def _execution_history_cleanup_phase(
    db_path: Path, order_ids: List[str], dry_run: bool,
) -> dict:
    """清理 execution_history.db 中 35 OrderId 的 route_history / route_event_history 旧行.

    与 fix_raw_fills_null_exchange.py 不同: 本场景 route_history 已写入 NULL equ_ticker
    行 (35 单), route_event_history 已写入 144 行; 必须清理后由 S2 重跑重建.
    order_history 是 VIEW (派生于 route_history), route_history 清场即等同清场.
    """
    if dry_run:
        LOGGER.info("[DRY-RUN] 不清理 execution_history.db")
        return {"deleted_route_history": 0, "deleted_route_event": 0, "skipped": True}

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA busy_timeout={Config.SQLITE_BUSY_TIMEOUT_MS}")
    placeholders = ", ".join("?" * len(order_ids))

    try:
        conn.execute("BEGIN IMMEDIATE")
        LOGGER.info("清理 execution_history: %d 个 OrderId", len(order_ids))

        cur = conn.execute(
            f"DELETE FROM route_history WHERE OrderId IN ({placeholders})",
            order_ids,
        )
        del_route = cur.rowcount
        LOGGER.info("  route_history 删除 %d 行", del_route)

        cur = conn.execute(
            f"DELETE FROM route_event_history WHERE OrderId IN ({placeholders})",
            order_ids,
        )
        del_evt = cur.rowcount
        LOGGER.info("  route_event_history 删除 %d 行", del_evt)

        conn.execute("COMMIT")
        LOGGER.info("execution_history 清场完成")
        return {
            "deleted_route_history": del_route,
            "deleted_route_event": del_evt,
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


# ── 主体: audit / 回滚 / replay 提示 (复刻 null_exchange) ──────────────────


def _write_audit(audit_path: Path, payload: dict) -> None:
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with audit_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    LOGGER.info("audit 已写入: %s", audit_path)


def _print_rollback_instructions(
    timestamp: str, raw_bak: Path, proc_bak: Path, exe_bak: Path,
) -> None:
    LOGGER.info("=" * 72)
    LOGGER.info("回滚预案 (如修改后发现问题)")
    LOGGER.info("=" * 72)
    print(f"""
# 1. 停止 DataPipeline / backend 服务
# 2. 还原备份 (raw_fills.db / processed_fills.db / execution_history.db):
cd "{Config.DATA_DIR}"
Move-Item raw_fills.db raw_fills.db.broken.{timestamp} -Force
Move-Item processed_fills.db processed_fills.db.broken.{timestamp} -Force
Move-Item execution_history.db execution_history.db.broken.{timestamp} -Force
Move-Item "{raw_bak.name}" raw_fills.db -Force
Move-Item "{proc_bak.name}" processed_fills.db -Force
Move-Item "{exe_bak.name}" execution_history.db -Force
# 3. 重启服务并校验 raw_fills Ticker NULL 行已恢复 (<NATL BK CANADA 144 行重新 NULL>)
""")


def _print_replay_instructions(affected_dates: List[str]) -> None:
    LOGGER.info("=" * 72)
    LOGGER.info("S2 重跑命令清单 (逐日执行, 共 %d 日)", len(affected_dates))
    LOGGER.info("=" * 72)
    lines = [
        "// S2 重跑命令清单 - 修复后逐日复活 processed_fills / execution_history 链路",
        "// 元帅命令: 用下列每条按顺序执行, 或合并至 shell 循环",
    ]
    for d in affected_dates:
        lines.append(f"python -m DataPipeline --date {d} --skip-bdib --once")
    replay_path = _REPO_ROOT / "scripts" / "ops" / "replay_s2_affected_dates_national_bank.txt"
    replay_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[S2 重跑清单已写入] {replay_path}\n")
    for ln in lines[1:6]:
        print(f"    {ln}")
    if len(affected_dates) > 5:
        print(f"    ... (共 {len(affected_dates)} 日, 见上述文件)")


# ── 主入口 ───────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description="一次性修复 raw_fills.db Ticker NULL -> 'NA' (仅 CAD/CN/NATL BK CANADA)",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="只做预检/备份, 不执行 UPDATE")
    mode.add_argument("--execute", action="store_true", help="执行修复 (含备份+UPDATE+下游清场)")
    parser.add_argument("--verbose", action="store_true", help="DEBUG 日志")
    parser.add_argument(
        "--reuse-backup-timestamp",
        metavar="YYYYMMDD_HHMMSS",
        help="复用此前 dry-run/execute 的时间戳备份, 跳过物理备份步骤",
    )
    args = parser.parse_args()

    _setup_logging(args.verbose)

    raw_path = Config.RAW_FILLS_DB
    proc_path = Config.PROCESSED_FILLS_DB
    exe_path = Config.EXECUTION_HISTORY_DB
    for p in (raw_path, proc_path, exe_path):
        if not p.exists():
            LOGGER.error("数据库不存在: %s - 拒绝执行", p)
            return 2

    LOGGER.info("=" * 72)
    LOGGER.info("raw_fills.db Ticker NULL -> 'NA' 修复 (NATL BK CANADA only)")
    LOGGER.info("=" * 72)
    LOGGER.info("RAW_FILLS_DB      = %s", raw_path)
    LOGGER.info("PROCESSED_FILLS_DB= %s", proc_path)
    LOGGER.info("EXECUTION_HISTORY = %s", exe_path)
    LOGGER.info("invariant         = (Currency=%s, Exchange=%s, SecurityName=%s)",
                INVARIANT_CCY, INVARIANT_EXCH, INVARIANT_SECNAME)
    LOGGER.info("expected Ticker   = %r", EXPECTED_FIX_VALUE)
    LOGGER.info("模式 = %s", "DRY-RUN" if args.dry_run else "EXECUTE")

    # 1) 预检
    LOGGER.info("-" * 72)
    LOGGER.info("[阶段 1] 预检 raw_fills.db Ticker NULL 分布 (read-only)")
    pre_conn = sqlite3.connect(str(raw_path))
    pre_conn.execute("PRAGMA journal_mode=WAL")
    pre_stats = _precheck_raw_fills_null_ticker(pre_conn)
    pre_conn.close()
    LOGGER.info("  total_rows            = %d", pre_stats["total_rows"])
    LOGGER.info("  null_count            = %d", pre_stats["null_count"])
    LOGGER.info("  null_invariant_count  = %d (必等于 null_count)",
                pre_stats["null_invariant_count"])
    LOGGER.info("  null_violation        = %d (必为 0)", pre_stats["null_violation"])
    LOGGER.info("  na_ticker_before      = %d (修改前 Ticker='NA' 总数)",
                pre_stats["na_ticker_before"])
    LOGGER.info("  affected source_dates = %d", len(pre_stats["affected_dates"]))
    LOGGER.info("  affected OrderIds     = %d", len(pre_stats["affected_orders"]))
    if pre_stats["affected_dates"]:
        LOGGER.info("    min date = %s", pre_stats["affected_dates"][0])
        LOGGER.info("    max date = %s", pre_stats["affected_dates"][-1])

    if pre_stats["null_count"] == 0:
        LOGGER.info("OK 已无 NULL 行 - 退出")
        return 0

    if pre_stats["null_violation"] != 0:
        LOGGER.error(
            "FAIL invariant 破坏: %d 行 Ticker NULL 但不满足 (CAD/CN/NATL BK CANADA) - 拒绝执行",
            pre_stats["null_violation"],
        )
        return 3
    if pre_stats["null_invariant_count"] != pre_stats["null_count"]:
        LOGGER.error("FAIL invariant 计数不一致 - 拒绝执行")
        return 3

    # 2) 备份 + SHA-256
    LOGGER.info("-" * 72)
    LOGGER.info("[阶段 2] 物理备份 + SHA-256 指纹")
    if args.reuse_backup_timestamp:
        timestamp = args.reuse_backup_timestamp
        LOGGER.info("  复用既有备份 timestamp=%s", timestamp)
        raw_bak = raw_path.with_suffix(raw_path.suffix + f".{timestamp}.national_bank.bak")
        proc_bak = proc_path.with_suffix(proc_path.suffix + f".{timestamp}.national_bank.bak")
        exe_bak = exe_path.with_suffix(exe_path.suffix + f".{timestamp}.national_bank.bak")
        if not args.dry_run:
            for p in (raw_bak, proc_bak, exe_bak):
                if not p.exists():
                    raise FileNotFoundError(f"复用备份不存在: {p}")
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if args.dry_run:
            LOGGER.info("  [DRY-RUN] 跳过物理备份")
            raw_bak = raw_path.with_suffix(raw_path.suffix + f".{timestamp}.national_bank.bak")
            proc_bak = proc_path.with_suffix(proc_path.suffix + f".{timestamp}.national_bank.bak")
            exe_bak = exe_path.with_suffix(exe_path.suffix + f".{timestamp}.national_bank.bak")
        else:
            raw_bak = _backup_db(raw_path, timestamp + ".national_bank")
            proc_bak = _backup_db(proc_path, timestamp + ".national_bank")
            exe_bak = _backup_db(exe_path, timestamp + ".national_bank")

    raw_sha_pre = _sha256_of_file(raw_path)
    proc_sha_pre = _sha256_of_file(proc_path)
    exe_sha_pre = _sha256_of_file(exe_path)
    LOGGER.info("  raw_fills.db   SHA-256 (pre) = %s", raw_sha_pre)
    LOGGER.info("  processed_fills SHA-256 (pre) = %s", proc_sha_pre)
    LOGGER.info("  execution_hist SHA-256 (pre) = %s", exe_sha_pre)

    # 3) 排他锁
    LOGGER.info("-" * 72)
    LOGGER.info("[阶段 3] 创建排他锁")
    lock_path = raw_path.with_name(raw_path.stem + ".fix_null_ticker_national_bank.lock")
    lock = _ExclusiveLock(lock_path, label="raw_fills.db NULL Ticker fix (NATL BK CANADA)")
    try:
        lock.acquire()

        # 4) 修改 raw_fills.db
        LOGGER.info("-" * 72)
        LOGGER.info("[阶段 4] UPDATE raw_fills.db Ticker")
        update_result = _raw_update_phase(raw_path, dry_run=args.dry_run, pre_stats=pre_stats)
        LOGGER.info("  update_result = %s", update_result)

        # 5) 下游 processed_fills 清场
        LOGGER.info("-" * 72)
        LOGGER.info("[阶段 5] 清空 processed_fills.db 受影响日期下游数据")
        proc_cleanup = _processed_cleanup_phase(
            proc_path, pre_stats["affected_dates"], dry_run=args.dry_run,
        )
        LOGGER.info("  proc_cleanup = %s", proc_cleanup)

        # 6) 下游 execution_history 清场 (本 Phase B 关键差异)
        LOGGER.info("-" * 72)
        LOGGER.info("[阶段 6] 清空 execution_history.db 中 35 OrderId 的历史行")
        exe_cleanup = _execution_history_cleanup_phase(
            exe_path, pre_stats["affected_orders"], dry_run=args.dry_run,
        )
        LOGGER.info("  exe_cleanup = %s", exe_cleanup)
    finally:
        lock.release()

    # 7) 修改后 SHA-256
    raw_sha_post = _sha256_of_file(raw_path)
    proc_sha_post = _sha256_of_file(proc_path)
    exe_sha_post = _sha256_of_file(exe_path)
    LOGGER.info("  raw_fills.db  SHA-256 (post) = %s", raw_sha_post)
    LOGGER.info("  processed_fills SHA-256(post) = %s", proc_sha_post)
    LOGGER.info("  execution_hist SHA-256(post) = %s", exe_sha_post)

    # 8) audit JSON
    audit_path = _REPO_ROOT / "scripts" / "ops" / (
        f"fix_raw_fills_null_ticker_national_bank_audit_{timestamp}.json"
    )
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
            "raw_fills": raw_sha_pre, "processed_fills": proc_sha_pre,
            "execution_history": exe_sha_pre,
        },
        "post_sha256": {
            "raw_fills": raw_sha_post, "processed_fills": proc_sha_post,
            "execution_history": exe_sha_post,
        },
        "pre_stats": pre_stats,
        "update_result": update_result,
        "proc_cleanup": proc_cleanup,
        "exe_cleanup": exe_cleanup,
        "affected_dates": pre_stats["affected_dates"],
        "affected_orders": pre_stats["affected_orders"],
        "expected_ticker_value": EXPECTED_FIX_VALUE,
        "invariant_predicate": (
            f"Ticker IS NULL AND Currency='{INVARIANT_CCY}' AND Exchange='{INVARIANT_EXCH}' "
            f"AND SecurityName='{INVARIANT_SECNAME}'"
        ),
        "background": (
            "144 行 raw 数据是 BBG fetch 当时 Ticker 字段缺失的快照, 非跨日覆盖孤儿. "
            "94 行同 security 正常行 100% 使用 Ticker='NA', canonical 值已全表反查唯一确认."
        ),
    }
    _write_audit(audit_path, audit_payload)

    # 9) 回滚 + S2 重跑提示
    _print_rollback_instructions(timestamp, raw_bak, proc_bak, exe_bak)
    if not args.dry_run:
        _print_replay_instructions(pre_stats["affected_dates"])
    else:
        LOGGER.info("[DRY-RUN] 未修改数据, 无需 S2 重跑")

    LOGGER.info("=" * 72)
    LOGGER.info("OK 完成 (mode=%s)", "DRY-RUN" if args.dry_run else "EXECUTE")
    LOGGER.info("  audit: %s", audit_path)
    LOGGER.info("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())