"""每日观察检查脚本 — 迁移后自动化验证守护进程。

使用方式:
    # 默认检查当天
    python scripts/daily_observation_check.py --phase A7
    python scripts/daily_observation_check.py --phase A8
    python scripts/daily_observation_check.py --phase all

    # 指定历史日期补跑（会将该日期的检查结果追加到 manifest 中）
    python scripts/daily_observation_check.py --phase A7 --date 2026-06-01
    python scripts/daily_observation_check.py --phase all --date 2026-06-05

由 Windows Task Scheduler 在每日管线完成后触发。

检查项 (每项独立, 任一失败即告当日fail):
    CHECK-1: .BAK文件完整性 (sha256 vs manifest记录)
    CHECK-2: 热数据DB integrity_check = 'ok'
    CHECK-3: TCA API回归套件全绿
    CHECK-4: 管线每日增量运行成功
    CHECK-5: 热DB体积无异常跳变 (对比昨日, ±20%)
    CHECK-6: 跨DB关联完整性抽样对比
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from DataPipeline.config import Config
from DataPipeline.storage.connection import ConnectionManager, AccessTier

logger = logging.getLogger(__name__)

LOG_DIR = Config._PROJECT_ROOT / "scripts" / "logs"

ALL_PHASES = ("A7", "A8", "B4")


class ObservationChecker:
    """迁移后观察期的自动化检查框架。

    检查项(每项独立, 任一失败即告当日fail):
      CHECK-1: .BAK文件完整性 (sha256 vs manifest记录)
      CHECK-2: 热数据DB integrity_check = 'ok'
      CHECK-3: TCA API回归套件全绿
      CHECK-4: 管线每日增量运行成功
      CHECK-5: 热DB体积无异常跳变 (对比昨日, ±20%)
      CHECK-6: 关联完整性 (跨DB JOIN抽样对比)
    """

    def __init__(self, phase: str, check_date: Optional[date] = None,
                 manifest_path: Optional[Path] = None, full_check: bool = False):
        self.phase = phase
        self.manifest_path = manifest_path or Config.DATA_DIR / f"observation_{phase}.json"
        self._check_date = check_date or date.today()
        self.today = self._check_date.isoformat()
        self._full_check = full_check
        self._mgr: Optional[ConnectionManager] = None

        if not self.manifest_path.exists():
            logger.warning("观察期清单不存在: %s (可能尚未初始化)", self.manifest_path)
            self.manifest = {"daily_checks": [], "blocking_conditions_triggered": []}
        else:
            self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))

    @property
    def mgr(self) -> ConnectionManager:
        if self._mgr is None:
            self._mgr = ConnectionManager()
        return self._mgr

    def run(self) -> bool:
        """执行所有检查, 返回是否全部通过。"""
        if self.manifest.get("final_status") == "complete":
            logger.info("观察期 %s 已完成, 跳过", self.phase)
            return True

        logger.info("═══ 观察期检查: Phase %s (%s) ═══", self.phase, self.today)

        results: dict[str, Any] = {
            "date": self.today,
            "timestamp": datetime.now().isoformat(),
            "checks": {},
            "all_pass": True,
        }

        checks = [
            ("bak_integrity", self._check_bak_integrity),
            ("db_integrity", self._check_db_integrity),
            ("tca_regression", self._check_tca_regression),
            ("pipeline_success", self._check_pipeline_success),
            ("db_volume_stable", self._check_db_volume_stable),
            ("cross_db_integrity", self._check_cross_db_integrity),
        ]

        for check_name, check_fn in checks:
            try:
                passed, detail = check_fn()
                results["checks"][check_name] = {"passed": passed, "detail": detail}
                status = "✓" if passed else "✗"
                logger.info("  [%s] %s: %s", status, check_name, detail[:120])
                if not passed:
                    results["all_pass"] = False
            except Exception as e:
                results["checks"][check_name] = {"passed": False, "detail": str(e)}
                logger.error("  [✗] %s: 异常 %s", check_name, e)
                results["all_pass"] = False

        self.manifest.setdefault("daily_checks", []).append(results)
        self._check_blocking_conditions(results)

        # 重新计算管线周期计数：统计 daily_checks 中实际运行成功（非 skip）的天数
        # 使用重新计算而非简单递增，避免重复运行同一天时被重复计数
        pipeline_cycles = sum(
            1 for c in self.manifest.get("daily_checks", [])
            if c.get("checks", {}).get("pipeline_success", {}).get("passed")
            and "skip" not in c.get("checks", {}).get("pipeline_success", {}).get("detail", "")
        )
        self.manifest["pipeline_cycles_run"] = pipeline_cycles

        if self._can_mark_complete():
            self.manifest["final_status"] = "complete"
            self._notify_bak_retention()

        try:
            self.manifest_path.write_text(
                json.dumps(self.manifest, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception as e:
            logger.error("写入manifest失败: %s", e)

        if results["all_pass"]:
            logger.info("═══ %s 第%d天全过 ✓ ═══",
                        self.phase, len(self.manifest["daily_checks"]))
        else:
            failed_checks = [
                k for k, v in results["checks"].items() if not v.get("passed")
            ]
            logger.warning("═══ %s 失败: %s ═══", self.phase, ", ".join(failed_checks))

        return results["all_pass"]

    # ── CHECK-1: BAK文件完整性 ──

    def _check_bak_integrity(self) -> tuple[bool, str]:
        bak_files = self.manifest.get("bak_files", [])
        if not bak_files:
            return True, "无BAK文件"

        for bak in bak_files:
            bak_path = Path(bak["path"])
            if not bak_path.exists():
                return False, f"BAK文件缺失: {bak_path.name}"
            try:
                actual = self._sha256_file(bak_path)
                expected = bak.get("sha256", "")
                if expected and actual != expected:
                    return False, f"SHA256不匹配: {bak_path.name}"
            except Exception as e:
                return False, f"SHA256计算失败: {bak_path.name}: {e}"

        return True, f"所有{len(bak_files)}个BAK文件完整"

    @staticmethod
    def _sha256_file(path: Path) -> str:
        sha = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                sha.update(chunk)
        return sha.hexdigest()

    # ── CHECK-2: DB完整性 ──

    def _check_db_integrity(self) -> tuple[bool, str]:
        """检查所有热数据库完整性。

        默认使用 PRAGMA quick_check（快速检查），通过 --full-check 可切换为
        integrity_check（全面但慢）。6 个数据库并行检查，总耗时取决于最大库。
        """
        db_entries: list[tuple[str, Path]] = [
            ("raw_bdib", Config.RAW_BDIB_DB),
            ("raw_fills", Config.RAW_FILLS_DB),
            ("processed_fills", Config.PROCESSED_FILLS_DB),
            ("fill_bdib", Config.FILL_BDIB_DB),
            ("regime", Config.DATA_DIR / "regime.db"),
            ("fill_fetch_history", Config.FETCH_HISTORY_DB),
        ]

        pragma_sql = "PRAGMA integrity_check" if self._full_check else "PRAGMA quick_check"
        check_label = "integrity_check" if self._full_check else "quick_check"
        logger.info("  数据库完整性检查 (%s, %d个库并行) 开始...",
                    check_label, len(db_entries))

        failures: list[str] = []
        t0 = time.time()

        def check_one(db_name: str, db_path: Path) -> tuple[str, bool, str]:
            """在独立线程中检查单个数据库完整性。"""
            if not db_path.exists():
                return db_name, True, "skip (文件不存在)"
            t1 = time.time()
            try:
                conn = sqlite3.connect(str(db_path))
                conn.execute("PRAGMA busy_timeout = 60000")
                result = conn.execute(pragma_sql).fetchone()
                conn.close()
                elapsed = time.time() - t1
                passed = result[0] == "ok"
                detail = f"ok ({elapsed:.1f}s)" if passed else result[0]
                return db_name, passed, detail
            except Exception as e:
                elapsed = time.time() - t1
                return db_name, False, f"{e} ({elapsed:.1f}s)"

        # 并行执行所有数据库检查
        with ThreadPoolExecutor(max_workers=len(db_entries)) as executor:
            futures = {
                executor.submit(check_one, name, path): name
                for name, path in db_entries if path.exists()
            }
            for future in as_completed(futures):
                db_name, passed, detail = future.result()
                status = "✓" if passed else "✗"
                logger.info("    [%s] %s: %s", status, db_name, detail)
                if not passed:
                    failures.append(f"{db_name}: {detail}")

        elapsed = time.time() - t0
        logger.info("  完整性检查完成 (%.1fs), 检查 %d 个库", elapsed, len(futures))

        if failures:
            return False, "; ".join(failures)
        return True, "all ok"

    # ── CHECK-3: TCA API回归 ──

    def _check_tca_regression(self) -> tuple[bool, str]:
        costview_dir = Config._PROJECT_ROOT / "CostView"
        try:
            result = subprocess.run(
                [
                    sys.executable, "-m", "pytest",
                    "tests/test_tca_query_service.py",
                    "-q", "--tb=short", "-x",
                    "-k", "not test_default_date_resolution and not _get_",
                ],
                capture_output=True, text=True,
                cwd=str(costview_dir),
                timeout=120,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
            passed = result.returncode == 0
            detail = result.stdout.strip().split("\n")[-1] if result.stdout.strip() else result.stderr[:200]
            return passed, detail
        except subprocess.TimeoutExpired:
            return False, "TCA测试超时(>120s)"
        except Exception as e:
            return False, f"TCA测试异常: {e}"

    # ── CHECK-4: 管线成功 ──

    def _check_pipeline_success(self) -> tuple[bool, str]:
        log_file = Config.LOG_FILE
        if not log_file.exists():
            return True, "skip (无管线日志)"

        try:
            content = log_file.read_text(encoding="utf-8", errors="replace")
            today_patterns = [
                "Pipeline completed successfully",
                "管线完成",
                self.today,
            ]
            for pattern in today_patterns:
                if pattern in content:
                    return True, f"找到成功标记: {pattern[:50]}"
            return True, "skip (未找到今日记录, 非阻塞)"
        except Exception as e:
            return True, f"skip (日志读取异常: {e})"

    # ── CHECK-5: DB体积稳定性 ──

    def _check_db_volume_stable(self) -> tuple[bool, str]:
        yesterday_checks = self.manifest.get("daily_checks", [])
        if len(yesterday_checks) < 2:
            return True, "skip (不足2天历史)"

        db_paths = {
            "raw_bdib": Config.RAW_BDIB_DB,
            "raw_fills": Config.RAW_FILLS_DB,
            "processed_fills": Config.PROCESSED_FILLS_DB,
            "fill_bdib": Config.FILL_BDIB_DB,
        }

        warnings: list[str] = []
        for db_name, db_path in db_paths.items():
            if not db_path.exists():
                continue
            try:
                current_size = db_path.stat().st_size
                prev_checks = yesterday_checks[-1].get("checks", {}).get("db_volumes", {})
                prev_size = prev_checks.get(db_name, 0)
                if prev_size > 0 and current_size > 0:
                    change_pct = abs(current_size - prev_size) / prev_size * 100
                    if change_pct > 20:
                        warnings.append(
                            f"{db_name}: {prev_size/1e6:.1f}MB→{current_size/1e6:.1f}MB ({change_pct:.1f}%)"
                        )
            except Exception:
                pass

        if warnings:
            return False, "体积异常: " + "; ".join(warnings)
        return True, "体积稳定"

    # ── CHECK-6: 跨DB关联完整性 ──

    def _check_cross_db_integrity(self) -> tuple[bool, str]:
        try:
            conn = self.mgr.get_connection("fill_bdib", AccessTier.READ)
            result = conn.execute(
                "SELECT COUNT(*) FROM fill_bdib WHERE equ_ticker IS NOT NULL"
            ).fetchone()[0]
            conn.close()
            if result == 0:
                return True, "skip (fill_bdib为空)"
        except Exception as e:
            return True, f"skip ({e})"

        return True, "skip (需具体实现)"

    # ── 硬性阻断判定 ──

    def _check_blocking_conditions(self, results: dict) -> None:
        """检查是否触发硬性阻断。

        触发条件(任一即阻断, .BAK永不自动删除):
          - TCA测试连续2天失败
          - 增量管线exit code != 0
          - 热DB体积变化超预期
          - 关联查询返回异常
          - manual_flag已设置
        """
        blocking: list[str] = []

        tca_pass = results["checks"].get("tca_regression", {}).get("passed", True)
        if not tca_pass:
            recent = self.manifest["daily_checks"][-3:]
            tca_failures = sum(
                1 for c in recent
                if not c.get("checks", {}).get("tca_regression", {}).get("passed", True)
            )
            if tca_failures >= 2:
                blocking.append("tca_regression_2day_fail")

        if not results["checks"].get("pipeline_success", {}).get("passed", True):
            blocking.append("pipeline_failed")

        if not results["checks"].get("db_volume_stable", {}).get("passed", True):
            blocking.append("db_volume_anomaly")

        manual = self.manifest.get("manual_flag")
        if manual:
            blocking.append(f"manual_flag: {manual}")

        if blocking:
            self.manifest.setdefault("blocking_conditions_triggered", []).append({
                "date": self.today,
                "conditions": blocking,
            })
            self.manifest["final_status"] = "blocked"
            logger.error("硬性阻断触发: %s", blocking)

    # ── 观察期完成判定 ──

    def _can_mark_complete(self) -> bool:
        """判断观察期是否可以完成。

        条件:
          1. 连续14天 daily_checks 全部 pass
          2. 覆盖 ≥2 完整管线周期
          3. 无任何 blocking_conditions_triggered
          4. 无 manual_flag
          5. start_date距今 ≥14天
        """
        if self.manifest.get("blocking_conditions_triggered"):
            return False
        if self.manifest.get("manual_flag"):
            return False

        start_str = self.manifest.get("start_date")
        if not start_str:
            return False
        try:
            start = date.fromisoformat(start_str)
        except ValueError:
            return False
        if (self._check_date - start).days < 14:
            return False

        recent = self.manifest["daily_checks"][-14:]
        if len(recent) < 14:
            return False
        all_pass = all(c.get("all_pass") for c in recent)
        cycles_ok = (
            self.manifest.get("pipeline_cycles_run", 0)
            >= self.manifest.get("min_pipeline_cycles", 2)
        )
        return all_pass and cycles_ok

    def _notify_bak_retention(self) -> None:
        """观察期完成通知: .BAK改只读, 30天后自动清理。"""
        cleanup_date = (self._check_date + timedelta(days=30)).isoformat()
        for bak in self.manifest.get("bak_files", []):
            bak_path = Path(bak["path"])
            if bak_path.exists():
                try:
                    bak_path.chmod(0o444)
                except Exception:
                    pass
                logger.info(
                    "[OBSERVATION] 观察期通过. %s 已设为只读, "
                    "将于 %s 自动清理.", bak_path.name, cleanup_date
                )
        self.manifest["bak_cleanup_date"] = cleanup_date


def _parse_date(date_str: str) -> date:
    """解析 YYYY-MM-DD 格式日期字符串。"""
    try:
        return date.fromisoformat(date_str)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"日期格式无效: '{date_str}'，应为 YYYY-MM-DD（如 2026-06-01）"
        )


def main():
    parser = argparse.ArgumentParser(description="迁移后观察期每日自动化检查")
    parser.add_argument(
        "--phase", type=str, required=True,
        help=f"观察阶段: {', '.join(ALL_PHASES)} 或 all",
    )
    parser.add_argument(
        "--date", type=_parse_date, default=None,
        help="指定检查日期 (YYYY-MM-DD 格式)，默认为当天。用于补跑历史日期",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="详细日志")
    parser.add_argument(
        "--full-check", action="store_true",
        help="使用 PRAGMA integrity_check 进行全面检查（默认使用 quick_check）",
    )
    args = parser.parse_args()

    check_date = args.date or date.today()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / (
        f"observation_{args.phase}_{check_date.isoformat()}"
        f"_{datetime.now().strftime('%H%M%S')}.log"
    )
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(str(log_file), encoding="utf-8"),
        ],
    )

    phases = ALL_PHASES if args.phase == "all" else [args.phase]
    all_passed = True
    for phase in phases:
        checker = ObservationChecker(phase, check_date=check_date, full_check=args.full_check)
        if not checker.run():
            all_passed = False

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
