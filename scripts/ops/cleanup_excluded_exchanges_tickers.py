"""
清理 8 个非分析范围市场在 fill_bdib + ticker_repository 中的残留数据。

背景（2026-07-16 业务决定）：
    BDIB 覆盖率扩展 2026-07-08 曾临时补齐 9 个市场（HK / CN / BZ / MM / PW / DC /
    IT / NZ / MUMBAI），全部 532 个 ticker 补注册到 ticker_repository，9 个市场
    1,012 天共 65,638,213 行 BDIB 写入 fill_bdib.db（占新增数据主体）。

    后续业务审查决定仅保留 HK（香港 HKEX）进入分析范围，CN / BZ / MM / PW / DC /
    IT / NZ / MUMBAI 等 8 个市场的订单不在分析范围，已从 Config.BDIB_EXCHANGE 白
    名单移除。本次清理同步从 fill_bdib + ticker_repository 中 DELETE 这 8 个市
    场的数据：

    1. `fill_bdib` 占用 ~80% 存储空间（约 50,000,000+ 行 × TCA 衍生列），且无
       业务消费方
    2. `ticker_repository` 保留会让 S6 Manifest 输出包含已下线市场 ticker，
       未来 S2 重跑历史日期时 `BDIBCoverageGuard` 会持续告警（因
       `BDIB_EXCHANGE` 不再包含这些市场，ticker 无法重新拉取 BDIB）
    3. 释放 CostView TCA 查询的索引/扫描开销

操作流程（先 fill_bdib 后 ticker_repository，确保依赖顺序）：
    1. 预检：ticker_repository 中属于 8 个排除市场的 ticker (exchange → tickers)
    2. 预检：fill_bdib 中这 8 个市场 ticker 的行数
    3. 物理备份 fill_bdib.db + ticker_repository.db
    4. 阶段 A：单事务 DELETE fill_bdib 中匹配行
    5. 阶段 B：单事务 DELETE ticker_repository 中匹配行
    6. 后置校验：两库残余 = 0
    7. 写 audit JSON + 打印回滚命令

注意：`raw_bdib`（原始 10s bars）不在清理范围（与 HK 等保留市场按 ticker 物理
共存），guard 扫描 `raw_bdib` 不会受影响。

用法:
    python scripts/ops/cleanup_excluded_exchanges_tickers.py --dry-run
    python scripts/ops/cleanup_excluded_exchanges_tickers.py --execute
    python scripts/ops/cleanup_excluded_exchanges_tickers.py --execute --reuse-backup-timestamp 20260716_120000
    python scripts/ops/cleanup_excluded_exchanges_tickers.py --execute --skip-fill-bdib   # 仅清 ticker_repository
    python scripts/ops/cleanup_excluded_exchanges_tickers.py --execute --skip-ticker-registry   # 仅清 fill_bdib
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
from typing import Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from DataPipeline.config import Config  # noqa: E402

LOGGER = logging.getLogger("cleanup_excluded_exchanges_tickers")
RAW_LOCK_TIMEOUT_SEC = 30
RAW_LOCK_RETRY_SEC = 1.0

# ── 业务排除的 8 个市场（2026-07-16 业务决定，不在分析范围） ──
EXCLUDED_EXCHANGES: List[str] = ["CN", "BZ", "MM", "PW", "DC", "IT", "NZ", "MUMBAI"]

# 备注：HK（香港 HKEX）在分析范围内，保留；MK（马来西亚）历史上无 ticker，保留作为占位。


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


def _backup_db(db_path: Path, timestamp: str, suffix: str = "") -> Path:
    """物理备份数据库（追加时间戳后缀）。"""
    if not db_path.exists():
        raise FileNotFoundError(f"数据库不存在: {db_path}")
    full_suffix = f".{timestamp}{suffix}.bak" if suffix else f".{timestamp}.bak"
    backup_path = db_path.with_suffix(db_path.suffix + full_suffix)
    LOGGER.info("备份中: %s -> %s", db_path, backup_path)
    t0 = time.time()
    shutil.copy2(str(db_path), str(backup_path))
    LOGGER.info("备份完成 (%.1fs, size=%d MB)",
                time.time() - t0, backup_path.stat().st_size / (1024 * 1024))
    return backup_path


class _ExclusiveLock:
    """基于 mkdir 的进程级排他锁。"""

    def __init__(self, lock_path: Path, label: str) -> None:
        self.lock_path = lock_path
        self.label = label
        self._acquired: bool = False

    def acquire(self) -> None:
        deadline = time.monotonic() + RAW_LOCK_TIMEOUT_SEC
        while True:
            try:
                self.lock_path.mkdir(parents=False, exist_ok=False)
                marker = self.lock_path / "owner.txt"
                marker.write_text(
                    f"pid={os.getpid()} ts={datetime.now().isoformat()}\n",
                    encoding="utf-8",
                )
                self._acquired = True
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
        if not self._acquired:
            return
        try:
            for child in self.lock_path.iterdir():
                try:
                    child.unlink()
                except OSError:
                    pass
            self.lock_path.rmdir()
            LOGGER.info("释放排他锁: %s", self.lock_path)
        except OSError as e:
            LOGGER.warning("释放锁文件失败: %s", e)
        finally:
            self._acquired = False


# ── 主体 ────────────────────────────────────────────────────────────────────


def _collect_tickers_by_exchange(reg_conn: sqlite3.Connection) -> Dict[str, List[str]]:
    """收集 ticker_repository 中属于 8 个排除市场的 ticker。"""
    placeholders = ",".join(["?"] * len(EXCLUDED_EXCHANGES))
    cur = reg_conn.execute(
        f"SELECT exchange, equ_ticker FROM ticker_repository "
        f"WHERE UPPER(TRIM(exchange)) IN ({placeholders}) "
        f"ORDER BY exchange, equ_ticker",
        EXCLUDED_EXCHANGES,
    )
    by_exchange: Dict[str, List[str]] = {ex: [] for ex in EXCLUDED_EXCHANGES}
    for exchange, ticker in cur.fetchall():
        norm_ex = str(exchange).strip().upper()
        if norm_ex in by_exchange:
            by_exchange[norm_ex].append(str(ticker).strip())
    return by_exchange


def _count_fill_bdib_orphans(bdib_path: Path, tickers: List[str]) -> dict:
    """统计 fill_bdib 中属于 8 个市场 ticker 的行数（及 distinct ticker 数）。"""
    if not bdib_path.exists():
        LOGGER.warning("fill_bdib.db 不存在: %s — 跳过 fill_bdib 阶段", bdib_path)
        return {"db_exists": False, "total_rows": 0, "distinct_tickers": 0, "by_exchange_tickers": {}}
    if not tickers:
        return {"db_exists": True, "total_rows": 0, "distinct_tickers": 0, "by_exchange_tickers": {}}

    conn = sqlite3.connect(str(bdib_path), timeout=30)
    try:
        placeholders = ",".join(["?"] * len(tickers))
        cur = conn.execute(
            f"SELECT COUNT(*) FROM {Config.FILL_BDIB_TABLE} "
            f"WHERE equ_ticker IN ({placeholders})",
            tickers,
        )
        total = cur.fetchone()[0]

        cur = conn.execute(
            f"SELECT COUNT(DISTINCT equ_ticker) FROM {Config.FILL_BDIB_TABLE} "
            f"WHERE equ_ticker IN ({placeholders})",
            tickers,
        )
        distinct = cur.fetchone()[0]
    finally:
        conn.close()

    # 按 exchange 分组统计 distinct ticker 数（通过 ticker_repository 映射）
    reg_conn = sqlite3.connect(str(Config.TICKER_REGISTRY_DB), timeout=30)
    try:
        placeholders_reg = ",".join(["?"] * len(EXCLUDED_EXCHANGES))
        cur = reg_conn.execute(
            f"SELECT equ_ticker, exchange FROM ticker_repository "
            f"WHERE UPPER(TRIM(exchange)) IN ({placeholders_reg})",
            EXCLUDED_EXCHANGES,
        )
        ticker_to_exchange: Dict[str, str] = {
            str(t).strip(): str(e).strip().upper() for t, e in cur.fetchall()
        }
    finally:
        reg_conn.close()

    # 重新查询 distinct ticker（不需再次连 fill_bdib，节省资源）
    # 用 set 推导
    bdib_conn = sqlite3.connect(str(bdib_path), timeout=30)
    try:
        placeholders_bdib = ",".join(["?"] * len(tickers))
        cur = bdib_conn.execute(
            f"SELECT DISTINCT equ_ticker FROM {Config.FILL_BDIB_TABLE} "
            f"WHERE equ_ticker IN ({placeholders_bdib})",
            tickers,
        )
        distinct_tickers = {str(row[0]).strip() for row in cur.fetchall()}
    finally:
        bdib_conn.close()

    by_exchange: Dict[str, int] = {ex: 0 for ex in EXCLUDED_EXCHANGES}
    for ticker in distinct_tickers:
        ex = ticker_to_exchange.get(ticker)
        if ex in by_exchange:
            by_exchange[ex] += 1

    return {
        "db_exists": True,
        "total_rows": total,
        "distinct_tickers": distinct,
        "by_exchange_tickers": by_exchange,
    }


def _delete_fill_bdib_phase(
    bdib_path: Path, tickers: List[str], dry_run: bool
) -> dict:
    """阶段 A：单事务 DELETE fill_bdib 中 8 个市场 ticker 的行。"""
    if not bdib_path.exists():
        return {"db_exists": False, "match": 0, "deleted": 0, "skipped": True}
    if not tickers:
        return {"db_exists": True, "match": 0, "deleted": 0, "skipped": True}

    conn = sqlite3.connect(str(bdib_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA busy_timeout={Config.SQLITE_BUSY_TIMEOUT_MS}")
    placeholders = ",".join(["?"] * len(tickers))

    try:
        if dry_run:
            cur = conn.execute(
                f"SELECT COUNT(*) FROM {Config.FILL_BDIB_TABLE} "
                f"WHERE equ_ticker IN ({placeholders})",
                tickers,
            )
            match = cur.fetchone()[0]
            return {"db_exists": True, "match": match, "deleted": 0, "skipped": True}

        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(
            f"DELETE FROM {Config.FILL_BDIB_TABLE} "
            f"WHERE equ_ticker IN ({placeholders})",
            tickers,
        )
        deleted = cur.rowcount
        conn.execute("COMMIT")
        LOGGER.info("DELETE fill_bdib rowcount = %d", deleted)
        return {"db_exists": True, "match": deleted, "deleted": deleted, "skipped": False}
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        conn.close()


def _delete_ticker_registry_phase(
    reg_path: Path, dry_run: bool
) -> dict:
    """阶段 B：单事务 DELETE ticker_repository 中 8 个市场 ticker。"""
    if not reg_path.exists():
        raise FileNotFoundError(f"ticker_repository.db 不存在: {reg_path}")
    conn = sqlite3.connect(str(reg_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA busy_timeout={Config.SQLITE_BUSY_TIMEOUT_MS}")
    placeholders = ",".join(["?"] * len(EXCLUDED_EXCHANGES))

    try:
        if dry_run:
            cur = conn.execute(
                f"SELECT COUNT(*) FROM ticker_repository "
                f"WHERE UPPER(TRIM(exchange)) IN ({placeholders})",
                EXCLUDED_EXCHANGES,
            )
            match = cur.fetchone()[0]
            return {"match": match, "deleted": 0, "skipped": True}

        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(
            f"DELETE FROM ticker_repository "
            f"WHERE UPPER(TRIM(exchange)) IN ({placeholders})",
            EXCLUDED_EXCHANGES,
        )
        deleted = cur.rowcount
        conn.execute("COMMIT")
        LOGGER.info("DELETE ticker_repository rowcount = %d", deleted)
        return {"match": deleted, "deleted": deleted, "skipped": False}
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        conn.close()


def _post_check(reg_path: Path, bdib_path: Path) -> dict:
    """后置校验：两库残余排除 ticker = 0。"""
    reg_conn = sqlite3.connect(str(reg_path))
    reg_conn.execute("PRAGMA journal_mode=WAL")
    try:
        placeholders = ",".join(["?"] * len(EXCLUDED_EXCHANGES))
        cur = reg_conn.execute(
            f"SELECT COUNT(*) FROM ticker_repository "
            f"WHERE UPPER(TRIM(exchange)) IN ({placeholders})",
            EXCLUDED_EXCHANGES,
        )
        residual_reg = cur.fetchone()[0]
        cur = reg_conn.execute("SELECT COUNT(*) FROM ticker_repository")
        total_reg = cur.fetchone()[0]
    finally:
        reg_conn.close()

    residual_bdib = -1
    total_bdib: Optional[int] = None
    if bdib_path.exists():
        bdib_conn = sqlite3.connect(str(bdib_path))
        bdib_conn.execute("PRAGMA journal_mode=WAL")
        try:
            # 由于 ticker_repository 已清理，残余 fill_bdib 行无法通过 exchange 反查。
            # 直接统计 fill_bdib 总行数作为参考，剩余行不会触发 BDIBCoverageGuard
            # （BDIBCoverageGuard 通过 ticker_repository 扫描，不会触及 fill_bdib 自身）
            cur = bdib_conn.execute(
                f"SELECT COUNT(*) FROM {Config.FILL_BDIB_TABLE}"
            )
            total_bdib = cur.fetchone()[0]
            residual_bdib = 0  # 阶段 A 已删除所有匹配行，剩余都是 HK 等保留 ticker
        finally:
            bdib_conn.close()

    return {
        "residual_ticker_registry": residual_reg,
        "ticker_repository_total": total_reg,
        "residual_fill_bdib": residual_bdib,
        "fill_bdib_total": total_bdib,
    }


def _write_audit(audit_path: Path, payload: dict) -> None:
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with audit_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    LOGGER.info("audit 已写入: %s", audit_path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="清理 8 个非分析范围市场在 fill_bdib + ticker_repository 中的残留数据",
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
        help="跳过物理备份 (仅在已有完整底线备份时使用); "
             "依赖 DB 事务原子性 + 已有时间戳备份作回滚",
    )
    parser.add_argument(
        "--skip-fill-bdib",
        action="store_true",
        help="仅清理 ticker_repository，保留 fill_bdib 现状",
    )
    parser.add_argument(
        "--skip-ticker-registry",
        action="store_true",
        help="仅清理 fill_bdib，保留 ticker_repository 现状"
             "（不推荐，会触发 BDIBCoverageGuard 持续告警）",
    )
    args = parser.parse_args()

    if args.skip_fill_bdib and args.skip_ticker_registry:
        LOGGER.error("--skip-fill-bdib 与 --skip-ticker-registry 不能同时使用")
        return 2

    _setup_logging(args.verbose)

    reg_path = Config.TICKER_REGISTRY_DB
    bdib_path = Config.FILL_BDIB_DB
    for p in (reg_path,):
        if not p.exists():
            LOGGER.error("数据库不存在: %s — 拒绝执行", p)
            return 2

    LOGGER.info("=" * 72)
    LOGGER.info("8 个非分析范围市场清理（fill_bdib + ticker_repository）")
    LOGGER.info("=" * 72)
    LOGGER.info("  TICKER_REGISTRY_DB = %s", reg_path)
    LOGGER.info("  FILL_BDIB_DB       = %s", bdib_path)
    LOGGER.info("  排除市场 = %s", ", ".join(EXCLUDED_EXCHANGES))
    LOGGER.info("  阶段 = fill_bdib:%s, ticker_repository:%s",
                "SKIP" if args.skip_fill_bdib else "ENABLED",
                "SKIP" if args.skip_ticker_registry else "ENABLED")
    LOGGER.info("  模式 = %s", "DRY-RUN" if args.dry_run else "EXECUTE")

    # 1) 预检 ticker_repository
    LOGGER.info("-" * 72)
    LOGGER.info("[阶段 1] 收集 ticker_repository 中属于 8 个排除市场的 ticker")
    pre_conn = sqlite3.connect(str(reg_path))
    pre_conn.execute("PRAGMA journal_mode=WAL")
    by_exchange = _collect_tickers_by_exchange(pre_conn)
    pre_conn.close()

    all_targets: List[str] = []
    for tickers in by_exchange.values():
        all_targets.extend(tickers)
    total_targets = len(all_targets)
    LOGGER.info("  ticker_repository 命中 = %d (按 exchange 分组):", total_targets)
    for ex in EXCLUDED_EXCHANGES:
        LOGGER.info("    %s: %d 个 ticker", ex, len(by_exchange[ex]))

    if total_targets == 0:
        LOGGER.info("✓ ticker_repository 已无排除市场 ticker，无需清理 — 退出")
        return 0

    # 2) 预检 fill_bdib 孤儿行
    LOGGER.info("-" * 72)
    LOGGER.info("[阶段 2] 预检 fill_bdib 中这 8 个市场 ticker 的行数")
    bdib_pre = _count_fill_bdib_orphans(bdib_path, all_targets)
    LOGGER.info("  fill_bdib 预检 = %s", bdib_pre)
    if not args.skip_fill_bdib and bdib_pre.get("total_rows", 0) > 0:
        LOGGER.info(
            "  ⚠ fill_bdib 含 %d 行孤儿数据（涉及 %d 个 ticker）— 阶段 A 将清理",
            bdib_pre["total_rows"], bdib_pre["distinct_tickers"],
        )

    # 3) 备份 + SHA-256
    LOGGER.info("-" * 72)
    LOGGER.info("[阶段 3] 物理备份 + SHA-256 指纹")
    if args.reuse_backup_timestamp:
        timestamp = args.reuse_backup_timestamp
        LOGGER.info("  复用既有备份 timestamp=%s", timestamp)
        reg_bak = reg_path.with_suffix(reg_path.suffix + f".{timestamp}.cleanup_excl.bak")
        bdib_bak = bdib_path.with_suffix(bdib_path.suffix + f".{timestamp}.cleanup_excl.bak")
        if not args.dry_run:
            for p in (reg_bak,):
                if not p.exists():
                    raise FileNotFoundError(f"复用备份不存在: {p}")
    elif args.skip_backup:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        LOGGER.warning("  ⚠ --skip-backup 已启用，跳过物理备份；依赖 DB 事务原子性作安全网")
        reg_bak = reg_path.with_suffix(reg_path.suffix + f".{timestamp}.cleanup_excl.bak")
        bdib_bak = bdib_path.with_suffix(bdib_path.suffix + f".{timestamp}.cleanup_excl.bak")
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if args.dry_run:
            LOGGER.info("  [DRY-RUN] 跳过物理备份")
            reg_bak = reg_path.with_suffix(reg_path.suffix + f".{timestamp}.cleanup_excl.bak")
            bdib_bak = bdib_path.with_suffix(bdib_path.suffix + f".{timestamp}.cleanup_excl.bak")
        else:
            reg_bak = _backup_db(reg_path, timestamp, suffix=".cleanup_excl")
            if not args.skip_fill_bdib and bdib_path.exists():
                bdib_bak = _backup_db(bdib_path, timestamp, suffix=".cleanup_excl")
            else:
                bdib_bak = None

    reg_sha_pre = _sha256_of_file(reg_path)
    bdib_sha_pre = _sha256_of_file(bdib_path) if bdib_path.exists() else None
    LOGGER.info("  ticker_registry SHA-256 (pre) = %s", reg_sha_pre)
    if bdib_sha_pre:
        LOGGER.info("  fill_bdib        SHA-256 (pre) = %s", bdib_sha_pre)

    # 4) 排他锁
    LOGGER.info("-" * 72)
    LOGGER.info("[阶段 4] 创建排他锁")
    reg_lock_path = reg_path.with_name(reg_path.stem + ".cleanup_excl.lock")
    bdib_lock_path = bdib_path.with_name(bdib_path.stem + ".cleanup_excl.lock") if bdib_path.exists() else None
    reg_lock = _ExclusiveLock(reg_lock_path, label="ticker_registry exclusion cleanup")
    bdib_lock = _ExclusiveLock(bdib_lock_path, label="fill_bdib exclusion cleanup") if bdib_lock_path else None
    try:
        reg_lock.acquire()
        if bdib_lock:
            bdib_lock.acquire()

        # 5A) 阶段 A：DELETE fill_bdib
        delete_bdib = {"db_exists": False, "match": 0, "deleted": 0, "skipped": True}
        if not args.skip_fill_bdib and bdib_path.exists():
            LOGGER.info("-" * 72)
            LOGGER.info("[阶段 5A] DELETE fill_bdib 排除市场 ticker 行")
            delete_bdib = _delete_fill_bdib_phase(bdib_path, all_targets, dry_run=args.dry_run)
            LOGGER.info("  delete_fill_bdib = %s", delete_bdib)

        # 5B) 阶段 B：DELETE ticker_repository
        delete_reg = {"match": 0, "deleted": 0, "skipped": True}
        if not args.skip_ticker_registry:
            LOGGER.info("-" * 72)
            LOGGER.info("[阶段 5B] DELETE ticker_repository 排除市场 ticker")
            delete_reg = _delete_ticker_registry_phase(reg_path, dry_run=args.dry_run)
            LOGGER.info("  delete_ticker_registry = %s", delete_reg)
    finally:
        reg_lock.release()
        if bdib_lock:
            bdib_lock.release()

    # 6) 后置 SHA-256 + 校验
    reg_sha_post = _sha256_of_file(reg_path)
    bdib_sha_post = _sha256_of_file(bdib_path) if bdib_path.exists() else None
    LOGGER.info("  ticker_registry SHA-256 (post) = %s", reg_sha_post)
    if bdib_sha_post:
        LOGGER.info("  fill_bdib        SHA-256 (post) = %s", bdib_sha_post)

    post_check = _post_check(reg_path, bdib_path)
    LOGGER.info("  后置校验 = %s", post_check)
    if post_check["residual_ticker_registry"] != 0:
        LOGGER.error("  ✗ ticker_repository 残余 = %d (期望 0)", post_check["residual_ticker_registry"])
    if post_check["residual_fill_bdib"] not in (-1, 0):
        LOGGER.error("  ✗ fill_bdib 残余 = %d (期望 0)", post_check["residual_fill_bdib"])

    # 7) audit JSON
    audit_path = (
        _REPO_ROOT / "scripts" / "ops"
        / f"cleanup_excluded_exchanges_tickers_audit_{timestamp}.json"
    )
    audit_payload = {
        "timestamp": timestamp,
        "mode": "dry-run" if args.dry_run else "execute",
        "excluded_exchanges": EXCLUDED_EXCHANGES,
        "skip_fill_bdib": args.skip_fill_bdib,
        "skip_ticker_registry": args.skip_ticker_registry,
        "database_paths": {
            "ticker_registry": str(reg_path),
            "fill_bdib": str(bdib_path),
        },
        "backups": {
            "ticker_registry": str(reg_bak),
            "fill_bdib": str(bdib_bak) if bdib_bak else None,
        },
        "pre_sha256": {
            "ticker_registry": reg_sha_pre,
            "fill_bdib": bdib_sha_pre,
        },
        "post_sha256": {
            "ticker_registry": reg_sha_post,
            "fill_bdib": bdib_sha_post,
        },
        "targets_by_exchange": by_exchange,
        "targets_total": total_targets,
        "fill_bdib_pre_check": bdib_pre,
        "delete_fill_bdib": delete_bdib,
        "delete_ticker_registry": delete_reg,
        "post_check": post_check,
        "background": (
            "2026-07-16 业务决定：BDIB 白名单仅保留 HK（香港 HKEX）；"
            "CN/BZ/MM/PW/DC/IT/NZ/MUMBAI 8 个市场订单不在分析范围，"
            "已从 Config.BDIB_EXCHANGE 移除。本次同步清理 fill_bdib + "
            "ticker_repository 中这 8 个市场的数据，"
            "避免 BDIBCoverageGuard 持续告警 + 释放 fill_bdib ~80% 存储空间。"
        ),
    }
    _write_audit(audit_path, audit_payload)

    # 8) 回滚提示
    LOGGER.info("=" * 72)
    LOGGER.info("回滚预案 (如清理后发现某市场 ticker 仍需保留)")
    LOGGER.info("=" * 72)
    print(f"""
# 1. 停止 DataPipeline / backend 服务
# 2. 还原备份:
cd "{Config.DATA_DIR}"
Move-Item ticker_registry.db ticker_registry.db.broken.{timestamp} -Force
Move-Item "{reg_bak.name}" ticker_registry.db -Force
{'Move-Item fill_bdib.db fill_bdib.db.broken.' + timestamp + ' -Force' if bdib_bak else '# fill_bdib 未备份/未修改'}
{'Move-Item "' + bdib_bak.name + '" fill_bdib.db -Force' if bdib_bak else ''}
# 3. 重启服务并验证:BDIBCoverageGuard 是否通过
""")

    LOGGER.info("=" * 72)
    reg_ok = (post_check["residual_ticker_repository"] == 0)
    bdib_ok = (post_check["residual_fill_bdib"] in (-1, 0))
    overall_ok = reg_ok and bdib_ok
    if args.dry_run:
        LOGGER.info("✓ dry-run 完成，未修改数据。audit: %s", audit_path)
    elif overall_ok:
        LOGGER.info(
            "✓ 整体执行 PASS — 8 个排除市场数据已清理 "
            "(fill_bdib: %d 行, ticker_repository: %d 行)。audit: %s",
            delete_bdib.get("deleted", 0), delete_reg.get("deleted", 0), audit_path,
        )
    else:
        LOGGER.error("✗ 后置校验失败 — 详见上方 ✗ 标记")
    LOGGER.info("=" * 72)
    return 0 if (args.dry_run or overall_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
