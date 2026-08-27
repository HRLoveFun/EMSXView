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
import io
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

# Windows 默认控制台编码为 cp1252，中文字符输出会触发 UnicodeEncodeError；
# 强制 stdout/stderr 使用 UTF-8，避免 progress callback 中的中文 detail 报错。
# 注意：当 stdout 被重定向为管道/文件时（如后端 subprocess.Popen），reconfigure 会抛出
# OSError: [Errno 22] Invalid argument，因此根据流类型选择安全的包装方式。
if sys.stdout.isatty() and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
else:
    # 管道/文件场景：用 TextIOWrapper 重新包装底层 buffer
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True
        )
    if hasattr(sys.stderr, "buffer"):
        sys.stderr = io.TextIOWrapper(
            sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True
        )

# Add EMSX root to path (parent of CostView/ and DataPipeline/)
_SCRIPT_DIR = Path(__file__).resolve().parent
_COSTVIEW_ROOT = _SCRIPT_DIR.parent
_EMSX_ROOT = _COSTVIEW_ROOT.parent
sys.path.insert(0, str(_EMSX_ROOT))

from DataPipeline.config import Config

logger = logging.getLogger("daily_update")


def _run_archive_step() -> None:
    """Phase C1: 管线后自动归档 (非阻塞, 失败不影响管线)."""
    def _on_archive_progress(db_name: str, phase: str, rows: int) -> None:
        # 每个 DB 处理完都输出一次 [STAGE] 心跳，刷新 last_activity_at，
        # 避免 7 个 DB 归档 + VACUUM 整体耗时 > 5 分钟时被前端 watchdog 误判为 stalled
        if phase == "start":
            print(f"[STAGE] archive 50 Archiving {db_name}...", flush=True)
        else:
            print(
                f"[STAGE] archive 80 Archived {db_name} ({rows} rows)",
                flush=True,
            )

    try:
        from scripts.run_archive import _run_archive_auto
        result = _run_archive_auto(progress_callback=_on_archive_progress)
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
                encoding="utf-8", errors="replace",
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


def _run_report_dims_step() -> None:
    """管线后自动刷新报告筛选维度持久化列表（非阻塞，失败仅 warning）。

    从 tca_route_summary 增量抽取市场 / Broker / Algo / Symbol 维度值写入
    tca_report_dims，Report 下拉选项据此读取（时间无关），不再每次请求
    按时间范围对明细表 GROUP BY 去重。
    """
    try:
        from CostView.src.monitoring.report_dims import refresh_dim_values

        print("[STAGE] report_dims 20 Refreshing report dim values...", flush=True)
        result = refresh_dim_values()
        processed = result.get("processed") or {}
        logger.info("报告维度值刷新: %s", result)
        print(
            "[STAGE] report_dims 100 Dim values refreshed: "
            + ", ".join(f"{k}={v}" for k, v in processed.items()),
            flush=True,
        )
    except Exception as e:
        logger.warning("报告维度值刷新跳过: %s", e)
        print(f"[STAGE] report_dims 100 Dim refresh skipped ({e})", flush=True)


def _run_report_step() -> None:
    """管线后自动生成 TCA 可视化报告（非阻塞，失败仅 warning）。

    - 每次日更后生成当日报告（last day = 最近有数据的交易日）；
    - 每周一额外生成上周汇总报告（last week，周一~周日）。
    """
    try:
        from scripts.reports.generate_tca_report import generate_report

        print("[STAGE] report 20 Generating daily TCA report...", flush=True)
        daily_path = generate_report(last="day")
        logger.info("当日 TCA 报告: %s", daily_path)
        print(f"[STAGE] report 60 Daily report: {daily_path.name}", flush=True)

        # 每周一额外生成上周汇总
        if datetime.now().weekday() == 0:
            weekly_path = generate_report(last="week")
            logger.info("每周汇总 TCA 报告: %s", weekly_path)
            print(f"[STAGE] report 80 Weekly report: {weekly_path.name}", flush=True)

        print("[STAGE] report 100 Report generation complete", flush=True)
    except Exception as e:
        # 报告失败不阻断日更主流程
        logger.warning("TCA 报告生成跳过: %s", e)
        print(f"[STAGE] report 100 Report skipped ({e})", flush=True)


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


def _fetch_failure_detail(fetch_result: Any) -> Optional[str]:
    """从 Stage A fetch 摘要中提取失败描述；无失败返回 None。

    静默失败修复（2026-08-21）：fill fetch 失败此前不会传导到最终 status，
    导致前端显示绿色 completed 而实际 fill 数据缺失（fill 失败 + BDIB 成功
    仍报 success）。失败判定（任一命中即视为失败）：
    - ``success`` 为 False（存在 error_days —— API 错误 / 空响应 quota 判定）
    - ``quota_paused`` 为 True（额度暂停短路，跳过了全部日期）
    """
    if not isinstance(fetch_result, dict):
        return None
    if fetch_result.get("status") == "up-to-date":
        return None
    error_days = int(fetch_result.get("days_error", 0) or 0)
    quota_paused = bool(fetch_result.get("quota_paused"))
    if error_days == 0 and not quota_paused and fetch_result.get("success", True):
        return None
    parts: list[str] = []
    if error_days:
        parts.append(f"{error_days} day(s) errored")
    if quota_paused:
        parts.append("quota paused — fetch skipped")
    detail = "; ".join(parts) if parts else "unknown failure"
    return (
        f"Fill fetch failed for {fetch_result.get('start_date')}~"
        f"{fetch_result.get('end_date')} ({detail})"
    )


def _stage_failure_detail(pipeline_result: Any) -> Optional[str]:
    """从管道阶段 summary 中提取显式短路/失败归因；无则返回 None。

    M1.2/M1.4 失败显式化（docs/spec/pipeline-resilience.md）：历史事故 A3 中 S5
    BDIB 因 ticker 映射为空静默短路，summary 报 completed=true 而前端显示绿色、
    raw_bdib 停更 2 天无人感知。约定：**任一阶段** summary 携带
    ``short_circuit_reason``（含嵌套子字典），日更最终状态必须标记 failed 并
    传导 exit code。M1.4 将早期仅针对 bdib 的判定推广为对所有阶段通用扫描。
    """
    if not isinstance(pipeline_result, dict):
        return None
    found = _scan_short_circuit(pipeline_result)
    if found:
        stage_key, reason = found
        return f"{stage_key} stage short-circuited: {reason}"
    return None


def _scan_short_circuit(node: Any, prefix: str = "pipeline") -> Optional[tuple[str, str]]:
    """递归扫描阶段 summary 中任意 ``short_circuit_reason``；返回 (阶段键, 原因)。"""
    if isinstance(node, dict):
        if node.get("short_circuit_reason"):
            return (prefix, str(node["short_circuit_reason"]))
        for key, val in node.items():
            if isinstance(val, dict):
                hit = _scan_short_circuit(val, key)
                if hit:
                    return hit
    return None


# M2.2 新鲜度 SLA 受检核心库：(库键, 日期列)。库文件不存在或表缺失视为尚未填充，跳过。
_FRESHNESS_CHECK_DBS: tuple[tuple[str, str], ...] = (
    ("raw_fills", "order_as_of_date"),
    ("processed_fills", "order_as_of_date"),
    ("raw_bdib", "order_as_of_date"),
    ("fill_bdib", "order_as_of_date"),
)


def _safe_max_date(db_key: str, col: str) -> Optional[str]:
    """读取核心库某列 MAX 值；库/表缺失或异常返回 None。"""
    try:
        from DataPipeline.storage.connection import AccessTier, ConnectionManager
        mgr = ConnectionManager()
        conn = mgr.get_connection(db_key, AccessTier.READ)
        try:
            row = conn.execute(f"SELECT MAX([{col}]) FROM [{db_key}]").fetchone()
            return row[0] if row and row[0] is not None else None
        finally:
            conn.close()
    except Exception:
        return None


def _business_days_between(start: date, end: date) -> int:
    """[start, end] 区间内工作日（周一~周五）天数，含端点。"""
    if end < start:
        return 0
    return sum(1 for i in range((end - start).days + 1)
               if (start + timedelta(days=i)).weekday() < 5)


def _freshness_failure_detail(max_dates: Optional[dict] = None) -> Optional[str]:
    """M2.2 新鲜度 SLA：核心库最新交易日与 today 间缺失的「交易日」超阈值即失败。

    历史事故 A1(360 万行静默缺失) / A3(raw_bdib 停更 2 个交易日报绿色) 均无
    自动新鲜度校验，靠人工对账才发现。此处强制在日更收尾校验各库新鲜度，
    以「交易日」为单位（规避周末 / 法定节假日误判，周一跑批数据到周五属正常）：

    - 缺失交易日 > FRESHNESS_WARN_BUSINESS_DAYS：记 WARNING 进 summary
    - 缺失交易日 > FRESHNESS_FAIL_BUSINESS_DAYS：返回失败描述，日更标记 failed
    - 配额暂停期间（is_quota_paused）跳过失败判定，避免合法跳过被误判

    ``max_dates`` 仅用于测试注入，生产路径为 None 时实时查询各库。
    """
    if max_dates is None:
        try:
            from DataPipeline.common.quota_pause import is_quota_paused
            if is_quota_paused():
                return None
        except Exception:
            pass
        max_dates = {
            db: _safe_max_date(db, col) for db, col in _FRESHNESS_CHECK_DBS
        }

    ref = date.today()
    stale_warn: list[str] = []
    stale_fail: list[str] = []
    for db, md in max_dates.items():
        if not md:
            continue  # 库缺失/未填充 → 跳过，不误判
        try:
            d = datetime.strptime(str(md), "%Y%m%d").date()
        except ValueError:
            continue
        gap = _business_days_between(d, ref) - 1  # 含端点的工作日数 -1 = 缺失交易日
        if gap >= Config.FRESHNESS_FAIL_BUSINESS_DAYS:
            stale_fail.append(f"{db}={md}({gap}交易日)")
        elif gap >= Config.FRESHNESS_WARN_BUSINESS_DAYS:
            stale_warn.append(f"{db}={md}({gap}交易日)")

    if stale_warn:
        logger.warning("新鲜度 SLA 告警（缺失>%d交易日）: %s",
                       Config.FRESHNESS_WARN_BUSINESS_DAYS, ", ".join(stale_warn))
    if stale_fail:
        return (
            f"数据新鲜度校验失败：以下库最新交易日缺失超过 "
            f"{Config.FRESHNESS_FAIL_BUSINESS_DAYS} 个交易日 — " + ", ".join(stale_fail)
        )
    return None


def run_daily_pipeline(
    generate_report: bool = True,
    freshness_check: Optional[Callable[[], Optional[str]]] = None,
    exchange_audit: Optional[Callable[[], dict]] = None,
    conservation_audit: Optional[Callable[[], dict]] = None,
) -> dict:
    """Execute the full daily pipeline: fetch + process + aggregate + labels.

    Args:
        generate_report: 管线成功后是否自动生成 TCA 可视化报告（默认开启，
            ``--no-report`` 关闭）。报告失败不影响管线状态。
        freshness_check: M2.2 新鲜度校验器（默认 ``_freshness_failure_detail``），
            返回失败描述或 None。测试可注入以隔离真实 DB 状态。
        exchange_audit: M3.2 交易所白名单 diff 审计器（默认
            ``audit_exchange_coverage``），返回 diff 字典，仅告警不阻断。
        conservation_audit: M2.1 跨库守恒审计器（默认 ``audit_conservation``），
            返回 {gaps, ok} 字典，仅告警不阻断。

    Returns:
        Summary dict with fetch and pipeline results.
    """
    summary = {
        "run_timestamp": datetime.now().isoformat(),
        "fetch": None,
        "pipeline": None,
        "status": "unknown",
    }
    # Stage A 失败描述（None = 无失败）。失败不中断后续阶段（BDIB / 聚合仍
    # 处理存量数据），但最终 status 会标记 failed 并经 exit code 传导至前端。
    fetch_failure: Optional[str] = None
    # 阶段级短路/失败描述（None = 无），与 fetch_failure 同型传导（M1.2）
    stage_failure: Optional[str] = None

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
                fetch_failure = _fetch_failure_detail(fetch_result)
                if fetch_failure:
                    # 静默失败修复：显式输出 ERROR 行（供 pipeline_jobs 的
                    # _extract_error_from_output 提取），管线继续跑完存量处理，
                    # 最终 status 标记 failed 并以 exit code 1 传导前端。
                    logger.error("%s — 后续阶段继续，本次日更将标记为 failed", fetch_failure)
                    print(f"ERROR: {fetch_failure}")
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
        stage_failure = _stage_failure_detail(pipeline_result)
        if stage_failure:
            # M1.2：阶段短路归因显式输出（供 pipeline_jobs 提取），管线继续跑完，
            # 最终 status 标记 failed 并以 exit code 1 传导前端。
            logger.error("%s — 后续阶段继续，本次日更将标记为 failed", stage_failure)
            print(f"ERROR: {stage_failure}")

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

        # M2.2 新鲜度 SLA：置于 WAL checkpoint 之后，确保只读连接看到最新落盘数据。
        # 日更收尾校验各核心库最新交易日，落后超阈值即标记 failed
        # （配额暂停期间由 _freshness_failure_detail 内部跳过）。
        freshness_failure = (freshness_check or _freshness_failure_detail)()
        summary["freshness"] = freshness_failure
        if freshness_failure:
            logger.error("%s — 后续步骤继续，本次日更将标记为 failed", freshness_failure)
            print(f"ERROR: {freshness_failure}")

        # M3.2 交易所白名单 ↔ 实际分布 diff 审计（仅告警不阻断，写 summary）
        try:
            from DataPipeline.pipeline_guards.exchange_whitelist_audit import (
                audit_exchange_coverage,
            )
            summary["exchange_diff"] = (exchange_audit or audit_exchange_coverage)()
        except Exception as e:  # 审计异常绝不影响日更主流程
            logger.warning("交易所白名单审计跳过: %s", e)
            summary["exchange_diff"] = {"outside_whitelist": [], "whitelisted_no_data": []}

        # M2.1 跨库行数守恒日检（仅告警不阻断，写 summary）
        try:
            from DataPipeline.pipeline_guards.cross_db_conservation import (
                audit_conservation,
            )
            summary["conservation"] = (conservation_audit or audit_conservation)()
        except Exception as e:  # 审计异常绝不影响日更主流程
            logger.warning("跨库守恒审计跳过: %s", e)
            summary["conservation"] = {"gaps": [], "ok": True, "checked_dates": 0}

        # ── 报告筛选维度值持久化列表刷新（非阻塞，供 Report 下拉时间无关读取）──
        print("[STAGE] report_dims 10")
        _run_report_dims_step()

        # ── TCA 可视化报告（非阻塞，--no-report 可关闭）──
        if generate_report:
            print("[STAGE] report 10")
            _run_report_step()

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

        terminal_failure = fetch_failure or stage_failure or (freshness_failure or None)
        if terminal_failure:
            # 静默失败修复：fetch / 阶段短路任一失败 → status=failed → exit 1，
            # pipeline_jobs 据此把 job 标记 failed，前端显示红色错误详情。
            summary["status"] = "failed"
            summary["error"] = terminal_failure
            print(f"[STAGE] completion 100 FAILED — {terminal_failure}")
        else:
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
    parser.add_argument(
        "--no-report", action="store_true",
        help="Skip automatic TCA report generation after the pipeline",
    )
    args = parser.parse_args()

    _setup_logging()

    if args.once:
        logger.info("Running once (--once mode)")
        result = run_daily_pipeline(generate_report=not args.no_report)
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
    schedule.every().day.at(args.time).do(
        run_daily_pipeline, generate_report=not args.no_report
    )

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
