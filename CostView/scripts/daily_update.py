"""
Daily Update Scheduler — automated CostView pipeline execution.

Runs the full FillFetch + processing pipeline on a configurable schedule.
Designed for post-market-close execution (default: 18:00 local time).

Usage:
    # Run once and exit
    python daily_update.py --once

    # Enter schedule loop (runs daily at 18:00)
    python daily_update.py

    # Custom time
    python daily_update.py --time 17:30
"""

from __future__ import annotations

import argparse
import gc
import json
import logging
import logging.handlers
import os
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Add EMSX root to path (parent of CostView/ and DataPipeline/)
_SCRIPT_DIR = Path(__file__).resolve().parent
_COSTVIEW_ROOT = _SCRIPT_DIR.parent
_EMSX_ROOT = _COSTVIEW_ROOT.parent
sys.path.insert(0, str(_EMSX_ROOT))

from DataPipeline.config import Config

logger = logging.getLogger("daily_update")


def _run_archive_step() -> None:
    """Phase C1: 管线后自动归档 (非阻塞, 失败不影响管线)."""
    try:
        from scripts.run_archive import _run_archive_auto
        result = _run_archive_auto()
        archived = result.get("archived", {})
        if archived:
            total_rows = sum(
                sum(v.values()) if isinstance(v, dict) else 0
                for v in archived.values()
            )
            logger.info("归档完成: %d个DB, %d行", len(archived), total_rows)
            print(f"[STAGE] archive 100 Archived {total_rows} rows from {len(archived)} DBs")
        else:
            logger.info("归档: 无需归档的数据")
            print("[STAGE] archive 100 No data to archive")
    except Exception as e:
        logger.warning("归档跳过: %s", e)


def _run_b4_observation_step() -> None:
    """B4 观察期检查: 在管线完成后执行，确保每条检查记录捕获当天的管线完成标记。

    非阻塞 — 失败仅记录 warning，不影响管线。
    仅当 observation_B4.json 存在且状态为 pending 时才执行。

    注意: 使用 stdout/stderr 输出到临时文件而非 capture_output=True，
    避免 Windows 上管道缓冲区满导致的 _readerthread 死锁。
    """
    manifest_path = Config.DATA_DIR / "observation_B4.json"
    if not manifest_path.exists():
        return

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("final_status") in ("complete", "blocked"):
            return
    except Exception:
        pass

    import tempfile
    tmp_path = None
    try:
        script_path = Config._PROJECT_ROOT / "scripts" / "daily_observation_check.py"
        # 使用临时文件接收输出，避免 Windows 管道缓冲区溢出
        with tempfile.NamedTemporaryFile(
            mode="w+", suffix=".log", delete=False,
            encoding="utf-8", errors="replace",
        ) as tmp:
            tmp_path = tmp.name

        with open(tmp_path, "w", encoding="utf-8", errors="replace") as out_f:
            result = subprocess.run(
                [sys.executable, str(script_path), "--phase", "B4"],
                stdout=out_f, stderr=subprocess.STDOUT,
                timeout=180,
                cwd=str(Config._PROJECT_ROOT),
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )

        if result.returncode == 0:
            logger.info("B4 观察检查: 通过 ✓")
            print("[STAGE] observation 100 B4 observation check passed")
        else:
            logger.warning("B4 观察检查: 存在失败项 (exit=%d)", result.returncode)
            print("[STAGE] observation 100 B4 observation check completed (with warnings)")
    except subprocess.TimeoutExpired:
        logger.warning("B4 观察检查: 超时跳过")
    except Exception as e:
        logger.warning("B4 观察检查: 跳过 (%s)", e)
    finally:
        # 清理临时文件
        if tmp_path and Path(tmp_path).exists():
            try:
                Path(tmp_path).unlink()
            except OSError:
                pass


_KNOWN_DBS = [
    "raw_fills.db",
    "processed_fills.db",
    "raw_bdib.db",
    "fill_bdib.db",
    "regime.db",
    "execution_history.db",
    "ticker_registry.db",
]


def _log_mem(stage_label: str = "") -> None:
    """Log current RSS memory usage for OOM diagnosis."""
    try:
        import psutil
        proc = psutil.Process(os.getpid())
        rss_gb = proc.memory_info().rss / (1024 ** 3)
        logger.info("[MEM] %s — RSS=%.2f GB", stage_label, rss_gb)
        print(f"[MEM] {stage_label} — RSS={rss_gb:.2f} GB", flush=True)
    except ImportError:
        pass  # psutil not installed — skip memory logging


def _checkpoint_wal() -> None:
    """强制提交所有已知 CostView 数据库的 WAL 日志。

    子进程写入后，数据可能仅驻留 WAL 文件而对 ``?mode=ro`` 只读连接不可见
    (如 ``repositories.py`` 使用的模式)。执行 ``wal_checkpoint(TRUNCATE)``
    将所有 WAL 页面写入主库文件并重置 WAL, 确保后续读取看到最新数据。

    v4.0-p4: 新增文件大小日志 + processed_fills.db 条件 VACUUM + 体积告警
    """
    data_dir = _COSTVIEW_ROOT / "data"
    # 体积告警阈值 (GB)
    SIZE_WARNING_GB = 5.0
    VACUUM_THRESHOLD_GB = 10.0

    for db_name in _KNOWN_DBS:
        db_path = data_dir / db_name
        if not db_path.exists():
            continue
        try:
            pre_size_mb = db_path.stat().st_size / (1024 ** 2)

            conn = sqlite3.connect(str(db_path), timeout=5.0)
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.close()

            post_size_mb = db_path.stat().st_size / (1024 ** 2)
            post_size_gb = post_size_mb / 1024

            if abs(post_size_mb - pre_size_mb) > 0.1:
                logger.info(
                    "WAL checkpoint %s: %.1f MB → %.1f MB",
                    db_name, pre_size_mb, post_size_mb,
                )

            # 文件大小告警
            if post_size_gb >= SIZE_WARNING_GB:
                logger.warning(
                    "⚠ DB 体积告警: %s = %.2f GB (阈值: %.0f GB)",
                    db_name, post_size_gb, SIZE_WARNING_GB,
                )

            _mtime = datetime.fromtimestamp(os.path.getmtime(db_path))
            logger.info(
                "DB state: %s size=%.2f GB modified=%s",
                db_name, post_size_gb, _mtime,
            )

        except Exception as exc:
            logger.warning("WAL checkpoint failed for %s: %s", db_name, exc)

    # ── processed_fills.db 条件 VACUUM (Phase 4) ──
    _vacuum_processed_fills_if_needed(data_dir, VACUUM_THRESHOLD_GB)


def _vacuum_processed_fills_if_needed(data_dir: Path, threshold_gb: float) -> None:
    """条件 VACUUM processed_fills.db 以回收间歇填充产生的膨胀空间。

    安全措施:
      - 仅在文件大小超过阈值时执行
      - VACUUM 前做 PRAGMA integrity_check 验证数据完整性
      - 操作失败不影响管线 (非阻塞, 仅记录日志)
      - 不操作其他任何数据库文件, 保护现有数据完整性
    """
    db_path = data_dir / "processed_fills.db"
    if not db_path.exists():
        return

    size_gb = db_path.stat().st_size / (1024 ** 3)
    if size_gb < threshold_gb:
        return

    # 在 VACUUM 阻塞操作前立即输出 [STAGE] 标记，确保 watchdog 先识别到 vacuum 阶段
    # 再执行阻塞操作，避免大库 VACUUM 被 watchdog 误杀
    print(
        f"[STAGE] vacuum 10 Starting VACUUM on {size_gb:.1f}GB database "
        f"(this may take several minutes)",
        flush=True,
    )
    logger.warning(
        "processed_fills.db 体积 %.2f GB 超过阈值 %.0f GB, 准备 VACUUM...",
        size_gb, threshold_gb,
    )

    try:
        conn = sqlite3.connect(str(db_path), timeout=30.0)

        # 安全检查: 数据完整性验证
        integrity_result = conn.execute("PRAGMA integrity_check").fetchone()
        if integrity_result[0] != "ok":
            logger.error(
                "VACUUM 中止: processed_fills.db integrity_check 失败 — %s",
                integrity_result[0],
            )
            conn.close()
            return

        # VACUUM 是单线程阻塞操作，执行期间无法输出任何日志
        t0 = datetime.now()
        conn.execute("VACUUM")
        conn.close()
        elapsed = (datetime.now() - t0).total_seconds()

        new_size_gb = db_path.stat().st_size / (1024 ** 3)
        saved_gb = size_gb - new_size_gb
        logger.info(
            "VACUUM 完成: %.2f GB → %.2f GB (回收 %.2f GB, 耗时 %.1fs)",
            size_gb, new_size_gb, saved_gb, elapsed,
        )
        print(
            "[STAGE] vacuum 100 VACUUM completed: "
            f"{size_gb:.1f}GB → {new_size_gb:.1f}GB "
            f"(reclaimed {saved_gb:.1f}GB, took {elapsed:.0f}s)",
            flush=True,
        )

    except Exception as e:
        logger.error("VACUUM 失败 (非阻塞, 管线继续): %s", e)


def _setup_logging() -> None:
    """Configure logging for the scheduler."""
    Config.initialize_directories()
    fmt = logging.Formatter(Config.LOG_FORMAT, datefmt=Config.LOG_DATE_FORMAT)
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    if Config.LOG_FILE.parent.exists():
        fh = logging.handlers.TimedRotatingFileHandler(
            str(Config.LOG_FILE),
            when="midnight",
            backupCount=Config.LOG_RETENTION_DAYS,
            encoding="utf-8",
        )
        fh.setFormatter(fmt)
        root.addHandler(fh)


def run_daily_pipeline() -> dict:
    """Execute the full daily pipeline: fetch + process + aggregate + labels.

    Returns:
        Summary dict with fetch and pipeline results.
    """
    summary = {
        "run_timestamp": datetime.now().isoformat(),
        "fetch": None,
        "pipeline": None,
        "status": "unknown",
    }

    # ── Stage marker: Initialization ──
    print("[STAGE] initialization 50")
    _log_mem("initialization")
    gc.collect()

    try:
        # Stage A: Auto-fetch new fills
        print("[STAGE] fill_fetch 10")
        _log_mem("fill_fetch_before")
        from DataPipeline.ingestion.fill_fetch import FillFetch

        logger.info("=" * 60)
        logger.info("DAILY UPDATE: Starting auto-fetch")
        logger.info("=" * 60)

        fetcher = FillFetch()
        try:
            print("[STAGE] fill_fetch 30")
            fetch_range = fetcher.determine_fetch_range()
            if fetch_range is None:
                logger.info("Already up-to-date. Nothing to fetch.")
                summary["fetch"] = {"status": "up-to-date"}
                print("[STAGE] fill_fetch 100")
            else:
                start, end = fetch_range
                total_calendar_days = (end - start).days + 1
                logger.info(f"Auto-fetch: {start} -> {end} ({total_calendar_days} calendar days)")

                def _on_fetch_progress(day_idx: int, total_days: int, date_str: str, rows: int, detail: str) -> None:
                    # Map per-day progress to fill_fetch stage percentage (range 40–95)
                    pct = 40 + int((day_idx / total_days) * 55) if total_days > 0 else 95
                    pct = min(95, max(40, pct))
                    print(f"[STAGE] fill_fetch {pct} Day {day_idx}/{total_days}: {date_str} — {detail}")

                print(f"[STAGE] fill_fetch 40 Total: {total_calendar_days} calendar days to scan")
                fetch_result = fetcher.fetch_range_aggregated(start, end, progress_callback=_on_fetch_progress)
                summary["fetch"] = fetch_result
                print("[STAGE] fill_fetch 100 Fill fetch complete")
        finally:
            fetcher.close()

        gc.collect()
        _log_mem("fill_fetch_after")

        # Stage B: Run incremental pipeline (with BDIB integration enabled)
        print("[STAGE] processing 10")
        _log_mem("processing_before")
        from DataPipeline.orchestration.core import run_incremental

        logger.info("=" * 60)
        logger.info("DAILY UPDATE: Running incremental pipeline (BDIB enabled)")
        logger.info("=" * 60)

        fetch_status = summary.get("fetch")
        if fetch_status is None:
            logger.info("fetch_range returned None — no new fills beyond last fetched date")
        elif isinstance(fetch_status, dict):
            logger.info("Fetch result: %s", json.dumps(fetch_status, default=str))

        print("[STAGE] processing 50")
        _log_mem("pipeline_before")
        pipeline_result = run_incremental(
            skip_bdib=False,
            stage_marker_name="processing",
            stage_marker_start=55,
            stage_marker_end=95,
        )
        gc.collect()
        _log_mem("pipeline_after")
        summary["pipeline"] = pipeline_result
        logger.info("Pipeline result: %s", json.dumps(pipeline_result, default=str))

        # Stage C: Write downstream manifest and flush databases to disk
        print("[STAGE] completion 20")
        try:
            from DataPipeline.analysis.downstream_interface import write_manifest
            write_manifest()
            logger.info("Downstream manifest updated")
        except Exception as e:
            logger.warning(f"Manifest write skipped: {e}")

        # Stage D: Archive expired data (Phase C1 — non-blocking)
        print("[STAGE] archive 10")
        _run_archive_step()

        # B4 观察期检查: 管线后置步骤，确保每条检查记录捕获当天管线完成标记
        _run_b4_observation_step()

        # ── Force WAL checkpoint so /api/db/overview sees fresh data ──
        _checkpoint_wal()
        gc.collect()
        _log_mem("completion_before_checkpoint")

        # ── Build human-readable completion detail for the frontend ──
        fetch_result = summary.get("fetch") or {}
        if isinstance(fetch_result, dict) and fetch_result.get("status") == "up-to-date":
            detail = "Already up to date — no new fills to fetch"
        else:
            fetch_rows = fetch_result.get("total_rows", 0) if isinstance(fetch_result, dict) else 0
            pipeline_processing = (pipeline_result or {}).get("processing", {}) if isinstance(pipeline_result, dict) else {}
            pipeline_rows = pipeline_processing.get("rows_processed", 0) if isinstance(pipeline_processing, dict) else 0
            agg_result = (pipeline_result or {}).get("aggregation", {}) if isinstance(pipeline_result, dict) else {}
            agg_dates = agg_result.get("dates", 0) if isinstance(agg_result, dict) else 0
            if fetch_rows or pipeline_rows:
                detail = f"Fetched {fetch_rows} fills · processed {pipeline_rows} rows · aggregated {agg_dates} dates"
            else:
                detail = "Pipeline ran with no data changes"

        summary["status"] = "success"
        print(f"[STAGE] completion 100 {detail}")
        logger.info(f"DAILY UPDATE complete: {json.dumps(summary, indent=2, default=str)}")
        gc.collect()
        _log_mem("completion_done")

    except Exception as e:
        summary["status"] = "failed"
        summary["error"] = str(e)
        logger.critical(f"DAILY UPDATE FAILED: {e}", exc_info=True)
        gc.collect()
        _log_mem("failed")

    # Write structured summary to log
    logger.info(f"pipeline.summary: {json.dumps(summary, default=str)}")
    return summary


def main():
    parser = argparse.ArgumentParser(description="CostView Daily Update Scheduler")
    parser.add_argument(
        "--once", action="store_true",
        help="Run the pipeline once and exit (no scheduling loop)",
    )
    parser.add_argument(
        "--time", type=str, default="18:00",
        help="Time to run daily (HH:MM format, default: 18:00)",
    )
    args = parser.parse_args()

    _setup_logging()

    if args.once:
        logger.info("Running once (--once mode)")
        result = run_daily_pipeline()
        sys.exit(0 if result["status"] == "success" else 1)

    # Schedule loop
    try:
        import schedule
    except ImportError:
        logger.error(
            "The 'schedule' package is required for scheduling mode. "
            "Install it with: pip install schedule\n"
            "Alternatively, use --once with Windows Task Scheduler."
        )
        sys.exit(1)

    logger.info(f"Scheduling daily pipeline at {args.time}")
    schedule.every().day.at(args.time).do(run_daily_pipeline)

    logger.info("Scheduler started. Press Ctrl+C to stop.")
    try:
        while True:
            schedule.run_pending()
            import time
            time.sleep(60)
    except KeyboardInterrupt:
        logger.info("Scheduler stopped by user")


if __name__ == "__main__":
    main()
