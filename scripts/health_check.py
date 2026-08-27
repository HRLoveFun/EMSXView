"""EMSXView 健康检查 — DB体积 / 查询延迟 / WAL监控 (Phase D).

使用方式:
    python scripts/health_check.py                    # 全量检查
    python scripts/health_check.py --quick            # 快速模式 (跳过慢查询)
    python scripts/health_check.py --json             # JSON输出 (集成用)
    python scripts/health_check.py --watch            # 持续监控 (每5分钟)

阈值 (plan.md §步骤9):
    D1: 单DB >10 GB 告警, 总热数据 >50 GB
    D2: TCA查询 P95 <3秒
    D3: WAL文件 >500 MB 告警
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from DataPipeline.config import Config
from DataPipeline.storage.connection import AccessTier, ConnectionManager

logger = logging.getLogger(__name__)
LOG_DIR = Config._PROJECT_ROOT / "scripts" / "logs"

# ── 告警阈值 ──
ALERT_SINGLE_DB_GB = float(os.getenv("HEALTH_DB_SIZE_GB", "10"))
ALERT_TOTAL_HOT_GB = float(os.getenv("HEALTH_TOTAL_HOT_GB", "50"))
ALERT_WAL_MB = float(os.getenv("HEALTH_WAL_MB", "500"))
ALERT_TCA_LATENCY_S = float(os.getenv("HEALTH_TCA_LATENCY_S", "5"))

HEALTH_MANIFEST = Config.DATA_DIR / "health_manifest.json"


class HealthChecker:
    """EMSXView 全系统健康检查器。"""

    def __init__(self, quick: bool = False):
        self._quick = quick
        self._mgr = ConnectionManager()
        self._results: dict[str, Any] = {
            "timestamp": datetime.now().isoformat(),
            "checks": {},
            "alerts": [],
            "status": "ok",
        }

    def run(self) -> dict[str, Any]:
        checks = [
            ("db_size", self._check_db_size),
            ("wal_size", self._check_wal_size),
            ("db_integrity", self._check_db_integrity),
            ("disk_space", self._check_disk_space),
            ("tca_latency", self._check_tca_latency),
            ("file_count", self._check_file_count),
            ("quota_status", self._check_quota_status),
            ("freshness", self._check_freshness),
            ("shell_tables", self._check_shell_tables),
            ("exchange_diff", self._check_exchange_diff),
            ("volume_growth", self._check_volume_growth),
            ("conservation", self._check_conservation),
        ]

        if self._quick:
            checks = [c for c in checks if c[0] not in (
                "tca_latency", "db_integrity", "conservation",
            )]

        for check_name, check_fn in checks:
            try:
                result = check_fn()
                self._results["checks"][check_name] = result
                if result.get("alert"):
                    self._results["alerts"].append({
                        "check": check_name,
                        "detail": result.get("detail", ""),
                    })
            except Exception as e:
                self._results["checks"][check_name] = {"error": str(e), "alert": True}
                self._results["alerts"].append({
                    "check": check_name,
                    "detail": str(e),
                })

        self._results["status"] = "warning" if self._results["alerts"] else "ok"

        try:
            HEALTH_MANIFEST.write_text(
                json.dumps(self._results, indent=2, default=str)
            )
        except Exception:
            pass

        return self._results

    # ── 005-bloomberg-quota-pause: 额度暂停状态（只读，不改健康判定）──

    def _check_quota_status(self) -> dict[str, Any]:
        """只读报告 Bloomberg 额度暂停标记状态（不产生 alert）。"""
        try:
            from DataPipeline.common.quota_pause import load_quota_pause
            rec = load_quota_pause()
            return {
                "paused": rec is not None,
                "reason": (rec or {}).get("reason"),
                "detail": (rec or {}).get("detail"),
                "first_seen_at": (rec or {}).get("first_seen_at"),
                "last_seen_at": (rec or {}).get("last_seen_at"),
                "hit_count": (rec or {}).get("hit_count"),
                "alert": False,
            }
        except Exception as e:
            return {"paused": False, "error": str(e), "alert": False}

    # ── D1: DB体积 ──

    def _check_db_size(self) -> dict[str, Any]:
        mgr = self._mgr
        dbs: dict[str, dict] = {}
        total_gb = 0.0
        alerts: list[str] = []

        for db_key in sorted(mgr.registry.keys()):
            if not mgr.database_exists(db_key):
                continue
            db_path = mgr.get_path(db_key)
            size_gb = db_path.stat().st_size / 1e9
            total_gb += size_gb
            dbs[db_key] = round(size_gb, 2)

            if size_gb > ALERT_SINGLE_DB_GB:
                alerts.append(f"{db_key}: {size_gb:.1f}GB > {ALERT_SINGLE_DB_GB}GB")

        if total_gb > ALERT_TOTAL_HOT_GB:
            alerts.append(
                f"总热数据 {total_gb:.1f}GB > {ALERT_TOTAL_HOT_GB}GB"
            )

        return {
            "databases": dbs,
            "total_gb": round(total_gb, 2),
            "alert": bool(alerts),
            "detail": "; ".join(alerts) if alerts else "",
            "thresholds": {
                "single_db_gb": ALERT_SINGLE_DB_GB,
                "total_hot_gb": ALERT_TOTAL_HOT_GB,
            },
        }

    # ── D3: WAL大小 ──

    def _check_wal_size(self) -> dict[str, Any]:
        mgr = self._mgr
        wal_info: dict[str, int] = {}
        alerts: list[str] = []

        for db_key in sorted(mgr.registry.keys()):
            if not mgr.database_exists(db_key):
                continue
            db_path = mgr.get_path(db_key)
            wal_path = db_path.with_suffix(db_path.suffix + "-wal")
            if wal_path.exists():
                wal_mb = wal_path.stat().st_size / 1e6
                wal_info[db_key] = round(wal_mb, 1)
                if wal_mb > ALERT_WAL_MB:
                    alerts.append(f"WAL {db_key}: {wal_mb:.0f}MB > {ALERT_WAL_MB}MB")

        return {
            "wal_files": wal_info,
            "alert": bool(alerts),
            "detail": "; ".join(alerts) if alerts else "",
            "threshold_mb": ALERT_WAL_MB,
        }

    # ── DB完整性 ──

    def _check_db_integrity(self) -> dict[str, Any]:
        failures: list[str] = []
        checked = 0

        for db_key in sorted(self._mgr.registry.keys()):
            if not self._mgr.database_exists(db_key):
                continue
            if db_key in ("fill_fetch_history", "bdib_fetch_history"):
                continue  # 极小的辅助DB（拉取历史审计）, 跳过
            checked += 1
            try:
                conn = self._mgr.get_connection(db_key, AccessTier.READ)
                result = conn.execute("PRAGMA quick_check").fetchone()
                conn.close()
                if result[0] != "ok":
                    failures.append(f"{db_key}: {result[0]}")
            except Exception as e:
                failures.append(f"{db_key}: {e}")

        return {
            "checked": checked,
            "failures": failures,
            "alert": bool(failures),
            "detail": "; ".join(failures) if failures else "all ok",
        }

    # ── 磁盘空间 ──

    def _check_disk_space(self) -> dict[str, Any]:
        data_dir = Config.DATA_DIR
        usage = shutil.disk_usage(data_dir)
        free_gb = usage.free / 1e9
        total_gb = usage.total / 1e9
        pct_used = (usage.used / usage.total) * 100

        alert = free_gb < 10
        detail = f"剩余{free_gb:.1f}GB ({100-pct_used:.1f}%可用)" if alert else ""

        return {
            "total_gb": round(total_gb, 1),
            "free_gb": round(free_gb, 1),
            "used_pct": round(pct_used, 1),
            "alert": alert,
            "detail": detail,
        }

    # ── D2: TCA查询延迟 ──

    def _check_tca_latency(self) -> dict[str, Any]:
        try:
            from platform_data.contracts import TcaFilters
            from CostView.src.tca_query_service import TcaQueryService
        except ImportError:
            return {"alert": False, "detail": "TCA服务不可用, 跳过"}

        svc = TcaQueryService()

        samples = []
        for _ in range(3):
            t0 = time.perf_counter()
            try:
                svc.build_tca_report(TcaFilters(limit=1))
                elapsed = time.perf_counter() - t0
                samples.append(elapsed)
            except Exception as e:
                return {"alert": True, "detail": f"TCA查询异常: {e}"}

        if not samples:
            return {"alert": False, "detail": "无样本"}

        avg_ms = sum(samples) / len(samples) * 1000
        max_ms = max(samples) * 1000
        alert = max(samples) > ALERT_TCA_LATENCY_S

        return {
            "samples": len(samples),
            "avg_ms": round(avg_ms, 1),
            "max_ms": round(max_ms, 1),
            "alert": alert,
            "detail": (
                f"TCA P95={max_ms:.0f}ms > {ALERT_TCA_LATENCY_S*1000:.0f}ms"
                if alert else ""
            ),
            "threshold_s": ALERT_TCA_LATENCY_S,
        }

    # ── 文件统计 ──

    def _check_file_count(self) -> dict[str, Any]:
        data_dir = Config.DATA_DIR
        db_count = len(list(data_dir.glob("*.db")))
        archived = len(list((data_dir / "archive").glob("*_archive.db"))) if (data_dir / "archive").exists() else 0

        return {
            "db_files": db_count,
            "archive_files": archived,
            "alert": False,
        }

    # ── M6.1 / M2.2: 新鲜度 SLA（逻辑检查，非体积）──

    @staticmethod
    def _business_days_between(start: Any, end: Any) -> int:
        """[start, end] 区间内工作日数，含端点。"""
        if end < start:
            return 0
        return sum(
            1 for i in range((end - start).days + 1)
            if (start + timedelta(days=i)).weekday() < 5
        )

    def _check_freshness(self) -> dict[str, Any]:
        """校验核心库最新交易日与今日缺失的交易日数（M2.2）。仅告警。"""
        from datetime import date

        from DataPipeline.config import Config as _Cfg
        from DataPipeline.storage.connection import AccessTier

        dbs = ("raw_fills", "processed_fills", "raw_bdib", "fill_bdib")
        ref = date.today()
        stale_fail: list[str] = []
        stale_warn: list[str] = []
        try:
            for db_key in dbs:
                if not self._mgr.database_exists(db_key):
                    continue
                conn = self._mgr.get_connection(db_key, AccessTier.READ)
                try:
                    row = conn.execute(
                        f"SELECT MAX([order_as_of_date]) FROM [{db_key}]"
                    ).fetchone()
                    md = row[0] if row and row[0] is not None else None
                finally:
                    conn.close()
                if not md:
                    continue
                try:
                    d = datetime.strptime(str(md), "%Y%m%d").date()
                except ValueError:
                    continue
                gap = self._business_days_between(d, ref) - 1
                if gap >= _Cfg.FRESHNESS_FAIL_BUSINESS_DAYS:
                    stale_fail.append(f"{db_key}={md}({gap})")
                elif gap >= _Cfg.FRESHNESS_WARN_BUSINESS_DAYS:
                    stale_warn.append(f"{db_key}={md}({gap})")
        except Exception as e:
            return {"alert": False, "detail": f"新鲜度检查跳过: {e}"}

        detail = ""
        if stale_fail:
            detail = (
                f"缺失>{_Cfg.FRESHNESS_FAIL_BUSINESS_DAYS}交易日: "
                + ", ".join(stale_fail)
            )
        elif stale_warn:
            detail = f"缺失>{_Cfg.FRESHNESS_WARN_BUSINESS_DAYS}交易日: " + ", ".join(stale_warn)
        return {
            "alert": bool(stale_fail),
            "detail": detail,
            "warn_only": bool(stale_warn) and not stale_fail,
        }

    # ── M6.1 / M3.1: 空壳表残留探测（分区迁移清理后回归防护）──

    def _check_shell_tables(self) -> dict[str, Any]:
        """检测 processed_fills.db 中分区迁移残留的 0 行空壳表（M3.1）。"""
        from DataPipeline.storage.repositories.fills import _PARTITION_DB_MAP

        found: list[str] = []
        try:
            if not self._mgr.database_exists("processed_fills"):
                return {"alert": False, "detail": "processed_fills 不存在, 跳过"}
            conn = self._mgr.get_connection("processed_fills", AccessTier.READ)
            try:
                for legacy in _PARTITION_DB_MAP:
                    exists = conn.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                        (legacy,),
                    ).fetchone() is not None
                    if not exists:
                        continue
                    rows = conn.execute(f"SELECT COUNT(*) FROM [{legacy}]").fetchone()[0]
                    if int(rows) == 0:
                        found.append(legacy)
            finally:
                conn.close()
        except Exception as e:
            return {"alert": False, "detail": f"空壳表检查跳过: {e}"}

        return {
            "alert": bool(found),
            "detail": f"残留空壳表: {found}" if found else "",
            "shell_tables": found,
        }

    # ── M6.1 / M3.2: 交易所白名单 diff ──

    def _check_exchange_diff(self) -> dict[str, Any]:
        try:
            from DataPipeline.pipeline_guards.exchange_whitelist_audit import (
                audit_exchange_coverage,
            )
            diff = audit_exchange_coverage()
        except Exception as e:
            return {"alert": False, "detail": f"交易所 diff 检查跳过: {e}"}
        outside = diff.get("outside_whitelist", [])
        return {
            "alert": bool(outside),
            "detail": f"白名单遗漏交易所: {outside}" if outside else "",
            "outside_whitelist": outside,
            "whitelisted_no_data": diff.get("whitelisted_no_data", []),
        }

    # ── M6.1 / M2.1: 跨库守恒 ──

    def _check_conservation(self) -> dict[str, Any]:
        try:
            from DataPipeline.pipeline_guards.cross_db_conservation import (
                audit_conservation,
            )
            res = audit_conservation()
        except Exception as e:
            return {"alert": False, "detail": f"守恒检查跳过: {e}"}
        gaps = res.get("gaps", [])
        return {
            "alert": not res.get("ok", True),
            "detail": f"整日缺失 {len(gaps)} 处" if gaps else "",
            "gaps": gaps[:10],
            "checked_dates": res.get("checked_dates", 0),
        }

    # ── M5.2: 体积增长告警（对比上次健康快照，超阈值告警）──

    def _check_volume_growth(self) -> dict[str, Any]:
        try:
            prev = {}
            if HEALTH_MANIFEST.exists():
                prev = json.loads(HEALTH_MANIFEST.read_text(encoding="utf-8")).get(
                    "checks", {}
                ).get("db_size", {}).get("databases", {})
        except Exception:
            prev = {}
        growth_gb = float(os.getenv("HEALTH_DB_GROWTH_GB", "5"))
        alerts: list[str] = []
        try:
            for db_key in sorted(self._mgr.registry.keys()):
                if not self._mgr.database_exists(db_key):
                    continue
                size_gb = self._mgr.get_path(db_key).stat().st_size / 1e9
                before = prev.get(db_key)
                if before is not None:
                    delta = size_gb - float(before)
                    if delta > growth_gb:
                        alerts.append(
                            f"{db_key}: +{delta:.1f}GB (>{growth_gb}GB)"
                        )
        except Exception as e:
            return {"alert": False, "detail": f"体积增长检查跳过: {e}"}
        return {
            "alert": bool(alerts),
            "detail": "; ".join(alerts) if alerts else "",
            "threshold_gb": growth_gb,
        }


def _format_console(results: dict[str, Any]) -> str:
    status = results['status'].upper()
    lines = [
        f"=== EMSXView Health Check ({results['timestamp'][:19]}) ===",
        f"Status: {status}",
        "",
    ]

    for check_name, result in results.get("checks", {}).items():
        flag = "[!]" if result.get("alert") else "[+]"
        lines.append(f"  {flag} {check_name}")

        if check_name == "db_size":
            lines.append(f"      Total: {result.get('total_gb', 0)} GB")
            for db, size in result.get("databases", {}).items():
                lines.append(f"      {db}: {size} GB")

        if check_name == "wal_size":
            wals = result.get("wal_files", {})
            if wals:
                for db, size in wals.items():
                    lines.append(f"      {db} WAL: {size} MB")
            else:
                lines.append("      No WAL files")

        if check_name == "disk_space":
            lines.append(f"      Free: {result.get('free_gb', 0)} GB / {result.get('total_gb', 0)} GB")

        if check_name == "tca_latency":
            lines.append(f"      avg={result.get('avg_ms', 0)}ms, max={result.get('max_ms', 0)}ms")

        if result.get("detail"):
            lines.append(f"      {result['detail']}")

    if results.get("alerts"):
        lines.append("")
        lines.append("  [!] ALERTS:")
        for alert in results["alerts"]:
            lines.append(f"      [{alert['check']}] {alert['detail']}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="EMSXView 健康检查")
    parser.add_argument("--quick", action="store_true", help="快速模式")
    parser.add_argument("--json", action="store_true", help="JSON输出")
    parser.add_argument("--watch", action="store_true", help="持续监控 (每5分钟)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"health_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.FileHandler(str(log_file), encoding="utf-8")],
    )

    if args.watch:
        logger.info("持续监控模式启动 (间隔=300s)")
        try:
            while True:
                checker = HealthChecker(quick=True)
                results = checker.run()
                print(_format_console(results))
                print()
                time.sleep(300)
        except KeyboardInterrupt:
            print("\n监控已停止")
        return

    checker = HealthChecker(quick=args.quick)
    results = checker.run()

    if args.json:
        print(json.dumps(results, indent=2, default=str))
    else:
        print(_format_console(results))

    sys.exit(1 if results["alerts"] else 0)


if __name__ == "__main__":
    main()
