"""Shared process-lifetime pipeline job registry + subprocess runner.

Phase 7b: Merged from backend/api/routers/_pipeline_jobs.py and
CostView/api/routers/_pipeline_jobs.py (eliminated code duplication).

Originally lived inside `routers/costview.py`. Both the DatabaseView router
and CostView aliases share this single in-memory registry — one active
pipeline at a time, reported consistently to both frontends.

PROJECT_ROOT is computed relative to this file (platform_data/ at monorepo root).
"""

from __future__ import annotations

import gc
import json
import logging
import os
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_jobs: dict[str, dict[str, Any]] = {}
_jobs_lock = threading.Lock()

# Project-root anchor: platform_data/ is at the monorepo root
_PROJECT_ROOT = Path(__file__).resolve().parents[1]

_LOCK_FILE = _PROJECT_ROOT / ".pipeline.lock"

# 后端实例唯一标识 — 每次进程启动生成新UUID，用于区分不同进程生命周期的锁文件
_INSTANCE_ID = str(uuid.uuid4())

# ── Watchdog / safety thresholds ────────────────────────────────────────────

_WATCHDOG_INTERVAL_SECS = 15
_STALL_TIMEOUT_SECS = 600       # 10 min without activity → stalled
_MAX_RUNTIME_SECS = 7200        # 2 h total → timeout
_LOCK_STALE_AGE_SECS = 14400    # 4 h → stale even if PID alive
_SUBPROCESS_STARTUP_TIMEOUT_SECS = 120
_MEM_WARN_GB = 12.0

# 阶段分级 stall 阈值（秒）—— 不同阶段合理等待时间不同
# 选择依据：
#   - initialization: 启动快，超时短便于快速发现脚本问题
#   - fill_fetch: Bloomberg EMSX 拉取 3 个日期 × 数千 ticker，单日可能 5-8 分钟
#   - processing: S2-S4 + S5.5 含 33 个交易所 BDIB 整合，3 日期累计可能 20-30 分钟
#   - pipeline: Stage 5 BDIB integration 主导，每日期 5-10 分钟无 stdout
#   - archive: 数据归档，I/O 重但通常 5-10 分钟
#   - completion: 校验 + 收尾，应快速
#   - vacuum: 单线程阻塞操作，已设 3600s
_STAGE_STALL_TIMEOUTS: dict[str, int] = {
    "initialization":  300,
    "fill_fetch":     1500,
    "processing":     1200,
    "pipeline":       1800,
    "archive":         900,
    "completion":      300,
    "vacuum":         3600,
}

# 多信号活动检测的弱活动累积窗口（秒）
# 弱信号: 1% ≤ CPU < 5% / 线程数变化 / 内存变化
# 强信号: stdout 行 / CPU ≥ 5% / I/O 字节数变化
# stall 判定: 强活动 idle > 阶段阈值 AND 弱活动 idle > _WEAK_ACTIVITY_GRACE_SECS
_WEAK_ACTIVITY_GRACE_SECS = 60


# ── Stage definitions ──────────────────────────────────────────────────────

PIPELINE_STAGES = [
    {"name": "initialization", "label": "Initialization"},
    {"name": "fill_fetch",     "label": "Fill Fetch"},
    {"name": "processing",     "label": "Processing"},
    {"name": "pipeline",       "label": "Pipeline"},
    {"name": "archive",        "label": "Archive"},
    {"name": "completion",     "label": "Completion"},
    {"name": "vacuum",         "label": "VACUUM"},
]

_STAGE_WEIGHTS = {
    "initialization":  5,
    "fill_fetch":     35,
    "processing":     50,
    "archive":         5,
    "pipeline":      100,  # single-stage mode
    "completion":      5,
    "vacuum":          3,
}

# VACUUM 阶段专用停滞超时 — VACUUM 是单线程阻塞操作，大库可能持续数十分钟
# （已并入 _STAGE_STALL_TIMEOUTS["vacuum"]，保留此常量供向后兼容）
_VACUUM_STALL_TIMEOUT_SECS = 3600

_STAGE_PREFIX = "[STAGE]"

# 错误检测模式 — 匹配Python traceback / ImportError / 致命日志
_ERROR_PATTERNS = [
    "Traceback (most recent call last)",
    "ImportError",
    "ModuleNotFoundError",
    "SyntaxError",
    "CRITICAL",
    "ERROR",
    "OperationalError",
    "PermissionError",
]


def _extract_error_from_output(lines: list[str]) -> str:
    """从捕获的子进程输出中提取关键错误信息。

    优先返回: traceback 块 > 包含 CRITICAL/ERROR 的行 > 最后5行。
    """
    filtered = [l for l in lines if l and not l.startswith(_STAGE_PREFIX)]
    if not filtered:
        return ""

    # 查找 traceback 块 — 捕获更多行以确保包含实际异常消息
    tb_start = -1
    for i, line in enumerate(filtered):
        if line.startswith("Traceback"):
            tb_start = i
            break
    if tb_start >= 0:
        return "\n".join(filtered[tb_start:tb_start + 20])

    # 查找包含关键错误模式的行
    error_lines = [
        l for l in filtered
        if any(pat in l for pat in _ERROR_PATTERNS[1:])  # 排除 Traceback
    ]
    if error_lines:
        return "\n".join(error_lines[-5:])

    # 兜底: 最后5行
    return "\n".join(filtered[-5:])


def _compute_progress(stage_name: str, stage_pct: int) -> int:
    stage_names = [stage["name"] for stage in PIPELINE_STAGES]
    try:
        current_index = stage_names.index(stage_name)
    except ValueError:
        current_index = 0
    prior = sum(
        _STAGE_WEIGHTS.get(PIPELINE_STAGES[i]["name"], 0)
        for i in range(current_index)
    )
    return min(100, prior + int(_STAGE_WEIGHTS.get(stage_name, 0) * stage_pct / 100))


def _mark_job_activity(job_id: str) -> None:
    if job_id in _jobs:
        _jobs[job_id]["last_activity_at"] = datetime.now().isoformat()


def _parse_stage_line(line: str):
    line = line.strip()
    if not line.startswith(_STAGE_PREFIX):
        return None
    rest = line[len(_STAGE_PREFIX):].strip()
    parts = rest.split()
    if len(parts) >= 2:
        detail = " ".join(parts[2:]) if len(parts) > 2 else None
        try:
            pct = min(100, max(0, int(parts[1])))
        except ValueError:
            pct = 0
        return parts[0], pct, detail
    if len(parts) == 1:
        return parts[0], 0, None
    return None


# ── Lock file helpers ────────────────────────────────────────────────────────

def _write_lock(job_id: str) -> Path:
    payload = {
        "pid": os.getpid(),
        "job_id": job_id,
        "started_at": datetime.now().isoformat(),
        "instance_id": _INSTANCE_ID,
    }
    _LOCK_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    logger.info("Lock file written: %s (pid=%s, job=%s)", _LOCK_FILE, os.getpid(), job_id)
    return _LOCK_FILE


def _remove_lock() -> None:
    try:
        if _LOCK_FILE.exists():
            _LOCK_FILE.unlink()
            logger.info("Lock file removed: %s", _LOCK_FILE)
    except PermissionError:
        logger.warning("Could not remove lock file (permission): %s", _LOCK_FILE)


def _cleanup_stale_lock_on_startup() -> None:
    """启动时清理其他实例遗留的过期锁文件，放行新任务。

    判断条件：
    - 无锁文件 → 无事可做
    - 锁文件存在但 instance_id 缺失（旧格式）→ 清理
    - 锁文件的 instance_id 与当前 _INSTANCE_ID 不匹配 → 其他实例遗留 → 清理
    - 锁文件的 instance_id 匹配 → 本进程锁，保留不动
    """
    if not _LOCK_FILE.exists():
        return
    try:
        payload = json.loads(_LOCK_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.info("Startup cleanup: corrupt lock file detected — removing")
        try:
            _LOCK_FILE.unlink()
        except OSError:
            pass
        return

    lock_instance = payload.get("instance_id")
    if lock_instance is None:
        logger.info("Startup cleanup: lock file has no instance_id (old format) — removing")
        _remove_lock()
        return
    if lock_instance != _INSTANCE_ID:
        logger.info(
            "Startup cleanup: lock file from different instance (%s) != current (%s) — removing",
            lock_instance[:8], _INSTANCE_ID[:8],
        )
        _remove_lock()
        return
    logger.info("Startup cleanup: lock file belongs to current instance — keeping")


def _log_subprocess_mem(proc: Optional[subprocess.Popen], label: str = "") -> None:
    if proc is None or proc.pid is None:
        return
    try:
        import psutil
        p = psutil.Process(proc.pid)
        rss_gb = p.memory_info().rss / (1024 ** 3)
        if rss_gb >= _MEM_WARN_GB:
            logger.warning("[RSS] subprocess pid=%s %s — %.2f GB (>= %.1f GB threshold)",
                           proc.pid, label, rss_gb, _MEM_WARN_GB)
        else:
            logger.info("[RSS] subprocess pid=%s %s — %.2f GB", proc.pid, label, rss_gb)
    except ImportError:
        pass
    except Exception:
        pass


def _check_lock() -> Optional[str]:
    if not _LOCK_FILE.exists():
        return None
    try:
        payload = json.loads(_LOCK_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("Corrupt lock file — removing: %s", _LOCK_FILE)
        _remove_lock()
        return None

    pid = payload.get("pid")
    job_id = payload.get("job_id")

    started_at_str = payload.get("started_at")
    if started_at_str:
        try:
            started_at = datetime.fromisoformat(started_at_str)
            age_secs = (datetime.now() - started_at).total_seconds()
            if age_secs > _LOCK_STALE_AGE_SECS:
                logger.warning("Stale lock file — age %.0fs exceeds %ss threshold, removing. pid=%s job=%s",
                               age_secs, _LOCK_STALE_AGE_SECS, pid, job_id)
                _remove_lock()
                return None
        except (ValueError, TypeError):
            logger.warning("Could not parse lock started_at=%s, ignoring age check", started_at_str)

    if pid and _is_pid_alive(pid):
        logger.info("Lock file valid: pid=%s job=%s", pid, job_id)
        return job_id

    logger.warning("Stale lock file — pid %s not alive, removing", pid)
    _remove_lock()
    return None


def _is_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


# ── 多信号活动检测器 ────────────────────────────────────────────────────────

class _ActivityDetector:
    """通过多维度信号检测子进程是否真的"卡住"。

    仅依赖 stdout 行（行缓冲、管道断开、长 IO 调用）容易误判 stall。
    整合以下信号源:
      - 强活动: stdout 收到新行、CPU% ≥ 5%、I/O 字节数变化
      - 弱活动: 1% ≤ CPU% < 5%、线程数变化、内存 RSS 变化 ≥ 1MB

    判定规则（watchdog 调用）:
      - 强活动 idle > 阶段阈值 AND 弱活动 idle > grace  → 真 stall
      - 其它情况 → 视作"在干活"，重置计时

    设计权衡:
      - psutil.cpu_percent(interval=0.3) 引入 ~0.3s 阻塞，watchdog 15s 周期可接受
      - I/O 计数器在 Windows 上同样可用 (psutil 5.x)
      - 进程退出/权限不足时所有信号返回 0，不误报为活跃
    """

    _CPU_STRONG_THRESHOLD = 5.0    # CPU% ≥ 此值视为强活动
    _CPU_WEAK_THRESHOLD = 1.0      # CPU% ≥ 此值视为弱活动
    _MEM_DELTA_BYTES = 1024 * 1024  # 1MB 内存变化视为弱活动

    def __init__(self, proc: "subprocess.Popen"):
        self._proc = proc
        self._p = None
        self._init_psutil()
        self._last_io_read = 0
        self._last_io_write = 0
        self._last_threads = 0
        self._last_rss = 0
        self._last_strong_at: float = time.monotonic()
        self._last_any_at: float = time.monotonic()
        self._strong_count = 0
        self._weak_count = 0

    def _init_psutil(self) -> None:
        try:
            import psutil  # noqa: F401
            self._p = psutil.Process(self._proc.pid)
            # 首次 cpu_percent 永远是 0.0（psutil 文档明确），先采集一次建立基线
            self._p.cpu_percent(interval=None)
            try:
                io = self._p.io_counters()
                self._last_io_read = io.read_bytes
                self._last_io_write = io.write_bytes
            except (AttributeError, NotImplementedError):
                pass
            self._last_threads = self._p.num_threads()
            self._last_rss = self._p.memory_info().rss
        except Exception:
            self._p = None

    def mark_stdout(self) -> None:
        """在主循环 readline() 收到行时调用 —— 强活动。"""
        now = time.monotonic()
        self._last_strong_at = now
        self._last_any_at = now
        self._strong_count += 1

    def probe(self) -> dict[str, Any]:
        """采集一次进程级信号。

        Returns:
            dict 包含:
              - available: psutil 是否可用
              - cpu_pct: CPU 占用百分比（0.3s 采样窗口）
              - io_active: I/O 字节数是否变化
              - thread_change: 线程数是否变化
              - mem_active: RSS 是否变化 ≥ 1MB
              - strong_now: 本次采样是否产生强活动
              - weak_now: 本次采样是否产生弱活动
              - last_strong_idle_secs: 距上次强活动秒数
              - last_any_idle_secs: 距上次任何活动秒数
        """
        result: dict[str, Any] = {
            "available": False,
            "cpu_pct": 0.0,
            "io_active": False,
            "thread_change": False,
            "mem_active": False,
            "strong_now": False,
            "weak_now": False,
            "last_strong_idle_secs": 0.0,
            "last_any_idle_secs": 0.0,
        }
        if self._p is None:
            return result
        try:
            # 0.3s 阻塞采样 —— 平衡精度与开销
            cpu = self._p.cpu_percent(interval=0.3)
            result["cpu_pct"] = cpu
            result["available"] = True

            try:
                io = self._p.io_counters()
                if io.read_bytes != self._last_io_read or io.write_bytes != self._last_io_write:
                    result["io_active"] = True
                self._last_io_read = io.read_bytes
                self._last_io_write = io.write_bytes
            except (AttributeError, NotImplementedError, OSError):
                pass

            try:
                nt = self._p.num_threads()
                if nt != self._last_threads:
                    result["thread_change"] = True
                self._last_threads = nt
            except (OSError, AttributeError):
                pass

            try:
                rss = self._p.memory_info().rss
                if abs(rss - self._last_rss) >= self._MEM_DELTA_BYTES:
                    result["mem_active"] = True
                self._last_rss = rss
            except (OSError, AttributeError):
                pass
        except (OSError, ProcessLookupError, AttributeError):
            # 进程已退出 —— 让 watchdog 走正常退出分支
            return result

        now = time.monotonic()
        # 强活动判定
        if cpu >= self._CPU_STRONG_THRESHOLD or result["io_active"]:
            self._last_strong_at = now
            self._last_any_at = now
            result["strong_now"] = True
            self._strong_count += 1
        # 弱活动判定
        elif (
            cpu >= self._CPU_WEAK_THRESHOLD
            or result["thread_change"]
            or result["mem_active"]
        ):
            self._last_any_at = now
            result["weak_now"] = True
            self._weak_count += 1

        result["last_strong_idle_secs"] = now - self._last_strong_at
        result["last_any_idle_secs"] = now - self._last_any_at
        return result

    @property
    def strong_count(self) -> int:
        return self._strong_count

    @property
    def weak_count(self) -> int:
        return self._weak_count


# ── Watchdog ─────────────────────────────────────────────────────────────────

def _watchdog_loop(
    job_id: str,
    proc: subprocess.Popen,
    stop_event: threading.Event,
    detector: _ActivityDetector,
    detector_lock: threading.Lock,
) -> None:
    started_at = datetime.now()
    logger.info("Watchdog started for job %s (multi-signal: stdout+CPU+I/O+threads)", job_id)

    last_weak_warning_at: float = 0.0  # 节流弱活动告警频率

    while not stop_event.is_set():
        stop_event.wait(_WATCHDOG_INTERVAL_SECS)
        if stop_event.is_set():
            break
        if proc.poll() is not None:
            logger.info("Watchdog: subprocess for job %s has exited (rc=%s)", job_id, proc.returncode)
            break

        with _jobs_lock:
            job = _jobs.get(job_id)
        if job is None:
            logger.warning("Watchdog: job %s vanished from registry", job_id)
            break

        # ── 多信号活动采集 ──
        # 加锁避免与主循环 mark_stdout() 竞争
        with detector_lock:
            signals = detector.probe()
        last_activity_str = job.get("last_activity_at")
        if last_activity_str:
            try:
                last_ts = datetime.fromisoformat(last_activity_str)
                stdout_idle_secs = (datetime.now() - last_ts).total_seconds()
            except ValueError:
                stdout_idle_secs = 0
        else:
            stdout_idle_secs = 0

        runtime_secs = (datetime.now() - started_at).total_seconds()

        if int(runtime_secs) % 30 < _WATCHDOG_INTERVAL_SECS:
            _log_subprocess_mem(proc, f"job={job_id} runtime={runtime_secs:.0f}s")

        # ── 阶段分级 stall 阈值 ──
        current_stage_name = (job.get("stage") or {}).get("name")
        effective_stall_timeout = _STAGE_STALL_TIMEOUTS.get(
            current_stage_name, _STALL_TIMEOUT_SECS
        )

        # ── stall 判定（多信号融合）──
        #
        # 真 stall 条件: stdout/CPU 强活动 idle 超过阶段阈值
        #                AND 任意弱活动 idle 超过 grace 窗口
        # 设计意图:
        #   - 强活动 idle 大 → 进程至少在 stdout 维度无活动（可能是 Stage 5 BDIB）
        #   - 但只要弱活动（CPU/线程/内存）还在变化 → 视作"在干活"
        #   - 只有强 + 弱双 idle 都超时才判定 stall
        strong_idle = max(stdout_idle_secs, signals["last_strong_idle_secs"])
        weak_idle = signals["last_any_idle_secs"]

        reason = None
        if runtime_secs > _MAX_RUNTIME_SECS:
            reason = f"Pipeline exceeded max runtime of {_MAX_RUNTIME_SECS // 60} minutes"
        elif (
            strong_idle > effective_stall_timeout
            and weak_idle > _WEAK_ACTIVITY_GRACE_SECS
        ):
            signal_diag = (
                f"cpu={signals['cpu_pct']:.1f}% io={'Y' if signals['io_active'] else 'N'} "
                f"thr={'Y' if signals['thread_change'] else 'N'} "
                f"mem={'Y' if signals['mem_active'] else 'N'}"
            )
            reason = (
                f"No strong activity for {strong_idle:.0f}s "
                f"(stage={current_stage_name} threshold={effective_stall_timeout}s) "
                f"AND no weak activity for {weak_idle:.0f}s "
                f"(grace={_WEAK_ACTIVITY_GRACE_SECS}s) — subprocess stalled. "
                f"Signals: {signal_diag}"
            )

        # ── 弱活动告警（不 kill，只 INFO）—— 便于运维识别"低活动但还在跑"的阶段 ──
        if (
            not reason
            and stdout_idle_secs > effective_stall_timeout * 0.6
            and signals["available"]
            and (time.monotonic() - last_weak_warning_at) > 60
        ):
            with detector_lock:
                strong_n = detector.strong_count
                weak_n = detector.weak_count
            logger.info(
                "Watchdog: job %s stdout idle %.0fs (stage=%s threshold=%ds), "
                "but weak signals active: cpu=%.1f%% io=%s thr=%s mem=%s "
                "(strong=%d, weak=%d) — NOT killing",
                job_id, stdout_idle_secs, current_stage_name,
                effective_stall_timeout,
                signals["cpu_pct"],
                signals["io_active"], signals["thread_change"], signals["mem_active"],
                strong_n, weak_n,
            )
            last_weak_warning_at = time.monotonic()

        if reason:
            logger.warning("Watchdog killing subprocess (job=%s): %s", job_id, reason)
            try:
                proc.kill()
                proc.wait(timeout=10)
            except Exception:
                pass
            with _jobs_lock:
                if job_id in _jobs:
                    _jobs[job_id]["status"] = "failed"
                    _jobs[job_id]["completed_at"] = datetime.now().isoformat()
                    _jobs[job_id]["error"] = reason
                    _jobs[job_id]["overall_progress"] = job.get("overall_progress", 0)
                    _mark_job_activity(job_id)
            _remove_lock()
            logger.info("Watchdog: job %s marked as failed (stalled)", job_id)
            break

    logger.info("Watchdog stopped for job %s", job_id)


def _run_pipeline_subprocess(job_id: str) -> None:
    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id]["status"] = "running"
            _jobs[job_id]["stage"] = {
                "name": "initialization", "label": "Initialization",
                "progress": 0, "detail": None,
            }
            _jobs[job_id]["overall_progress"] = 0
            _mark_job_activity(job_id)

    proc: Optional[subprocess.Popen] = None
    captured_lines: list[str] = []
    stop_event = threading.Event()
    watchdog_thread: Optional[threading.Thread] = None
    lock_written = False
    started_at = datetime.now()
    have_seen_first_output = False
    startup_timeout_hit = False
    # 共享的 stdout 强活动探测器 —— 主循环在收到行时调用 mark_stdout()，
    # watchdog 在 _ActivityDetector.probe() 内部读 last_strong_idle_secs
    # 使用 threading.Lock 保护跨线程读写
    detector: Optional[_ActivityDetector] = None
    detector_lock = threading.Lock()
    try:
        proc = subprocess.Popen(
            [sys.executable, "-u", str(_PROJECT_ROOT / "CostView" / "scripts" / "daily_update.py"), "--once"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=str(_PROJECT_ROOT),
        )
        logger.info("Pipeline subprocess launched: pid=%s job=%s", proc.pid, job_id)

        detector = _ActivityDetector(proc)
        watchdog_thread = threading.Thread(
            target=_watchdog_loop,
            args=(job_id, proc, stop_event, detector, detector_lock),
            daemon=True,
        )
        watchdog_thread.start()

        try:
            _write_lock(job_id)
            lock_written = True
        except Exception:
            logger.exception("Failed to write pipeline lock file")

        while True:
            if not have_seen_first_output:
                elapsed = (datetime.now() - started_at).total_seconds()
                if elapsed > _SUBPROCESS_STARTUP_TIMEOUT_SECS:
                    reason = f"Subprocess pid={proc.pid} produced no output within {_SUBPROCESS_STARTUP_TIMEOUT_SECS}s — killed"
                    logger.warning("Pipeline startup timeout (%s)", reason)
                    try:
                        proc.kill()
                        proc.wait(timeout=10)
                    except Exception:
                        pass
                    status = "failed"
                    if captured_lines:
                        tail_output = "\n".join(captured_lines[-10:])
                        error = (
                            f"Pipeline startup timeout ({_SUBPROCESS_STARTUP_TIMEOUT_SECS}s) — "
                            f"subprocess produced no [STAGE] output. "
                            f"Check for import errors below:\n{tail_output}"
                        )
                    else:
                        error = (
                            f"Pipeline startup timeout ({_SUBPROCESS_STARTUP_TIMEOUT_SECS}s) — "
                            f"subprocess produced no output at all. "
                            f"Possible causes: missing dependency, syntax error, or import crash."
                        )
                    startup_timeout_hit = True
                    break

            line = proc.stdout.readline() if proc.stdout else ""
            if not line and proc.poll() is not None:
                break
            if not line:
                continue
            if not have_seen_first_output:
                have_seen_first_output = True
                logger.info("Pipeline first output received (job=%s, pid=%s): %.80s", job_id, proc.pid, line.rstrip())
            captured_lines.append(line.rstrip())
            if len(captured_lines) > 400:
                captured_lines = captured_lines[-400:]
            # 标记 stdout 强活动 —— 让 watchdog 知道进程在产生输出
            if detector is not None:
                with detector_lock:
                    detector.mark_stdout()
            parsed = _parse_stage_line(line)
            if parsed:
                stage_name, stage_pct, stage_detail = parsed
                label = next((s["label"] for s in PIPELINE_STAGES if s["name"] == stage_name), stage_name)
                overall = _compute_progress(stage_name, stage_pct)
                with _jobs_lock:
                    if job_id in _jobs:
                        _jobs[job_id]["stage"] = {
                            "name": stage_name, "label": label,
                            "progress": stage_pct, "detail": stage_detail,
                        }
                        _jobs[job_id]["overall_progress"] = overall
                        _mark_job_activity(job_id)
            else:
                with _jobs_lock:
                    if job_id in _jobs:
                        _mark_job_activity(job_id)

        if not startup_timeout_hit:
            # 手动排空 stdout 残留数据，避免 proc.communicate() 的 _readerthread
            # 在 Windows 上因管道断开而崩溃（fh.read() 抛出 OSError）
            tail_parts: list[str] = []
            try:
                if proc.stdout and not proc.stdout.closed:
                    # 先尝试读取所有残留行
                    for remaining in proc.stdout:
                        tail_parts.append(remaining.rstrip())
            except (OSError, ValueError, IOError) as pipe_err:
                logger.warning("Pipe read error while draining stdout: %s", pipe_err)
            except Exception:
                logger.debug("Unexpected error draining stdout", exc_info=True)

            # 等待进程完全结束
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                logger.warning("Process did not exit within 30s after pipeline end — force killing")
                try:
                    proc.kill()
                    proc.wait(timeout=10)
                except Exception:
                    pass

            tail = "\n".join(tail_parts) if tail_parts else ""
        else:
            tail = None
        if tail:
            for t_line in tail.splitlines():
                captured_lines.append(t_line)
        if not startup_timeout_hit:
            status = "completed" if proc.returncode == 0 else "failed"
            error = None
            if proc.returncode != 0:
                error_detail = _extract_error_from_output(captured_lines)
                if error_detail:
                    error = f"Pipeline exit code {proc.returncode}:\n{error_detail}"
                else:
                    error = (
                        f"Pipeline exited with code {proc.returncode} "
                        f"(no traceback in output — last 5 lines: "
                        f"{chr(10).join(captured_lines[-5:])})"
                    )
    except subprocess.TimeoutExpired:
        if proc is not None:
            try:
                proc.kill()
            except Exception:
                pass
        status = "failed"
        error = "Pipeline timed out after 3600 seconds"
    except Exception as exc:
        status = "failed"
        error = str(exc)
    finally:
        stop_event.set()
        if lock_written:
            _remove_lock()

    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id]["status"] = status
            _jobs[job_id]["completed_at"] = datetime.now().isoformat()
            # Bug #1 fix: 保留看门狗已写入的精确死因（如 stall/max runtime），
            # 避免被 "Pipeline exit code" 兜底信息覆写而丢失真实原因。
            existing_error = _jobs[job_id].get("error")
            if not existing_error:
                _jobs[job_id]["error"] = error
            elif error and not startup_timeout_hit:
                # 看门狗已写入死因时，附上 subprocess exit code 作为补充诊断信息
                _jobs[job_id]["error"] = (
                    f"{existing_error}\n\n[subprocess exit code: "
                    f"{proc.returncode if proc else 'N/A'}]"
                )
            _mark_job_activity(job_id)
            if status == "completed":
                _jobs[job_id]["overall_progress"] = 100
                existing = _jobs[job_id].get("stage", {}) or {}
                _jobs[job_id]["stage"] = {
                    "name": "completion", "label": "Completion",
                    "progress": 100,
                    "detail": existing.get("detail") or None,
                }
    gc.collect()
    logger.info("Pipeline job %s finished: %s", job_id, status)


def trigger_pipeline(client_host: str) -> dict[str, Any]:
    """Spawn a daily-update pipeline job. Idempotent."""
    with _jobs_lock:
        for existing_id, existing_job in _jobs.items():
            if existing_job.get("status") in ("started", "running"):
                logger.info("Returning existing active job %s (status=%s)", existing_id, existing_job["status"])
                return {
                    "job_id": existing_id,
                    "status": existing_job["status"],
                    "message": "Pipeline already running — returning existing job",
                }

    existing_job_id = _check_lock()
    if existing_job_id:
        with _jobs_lock:
            if existing_job_id not in _jobs:
                _jobs[existing_job_id] = {
                    "status": "running",
                    "started_at": datetime.now().isoformat(),
                    "completed_at": None,
                    "error": None,
                    "stage": {"name": "initialization", "label": "Initialization", "progress": 0, "detail": None},
                    "overall_progress": 0,
                    "last_activity_at": datetime.now().isoformat(),
                }
        return {
            "job_id": existing_job_id,
            "status": "running",
            "message": "Pipeline already running (lock file) — returning existing job",
        }

    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _jobs[job_id] = {
            "status": "started",
            "started_at": datetime.now().isoformat(),
            "completed_at": None,
            "error": None,
            "stage": {"name": "initialization", "label": "Initialization", "progress": 0, "detail": None},
            "overall_progress": 0,
            "last_activity_at": datetime.now().isoformat(),
        }

    threading.Thread(target=_run_pipeline_subprocess, args=(job_id,), daemon=True).start()
    logger.info("Pipeline triggered: job_id=%s (caller=%s)", job_id, client_host)
    return {"job_id": job_id, "status": "started", "message": "Daily update pipeline started."}


def get_job(job_id: str) -> Optional[dict[str, Any]]:
    with _jobs_lock:
        job = _jobs.get(job_id)
    return dict(job) if job is not None else None


def list_jobs() -> list[dict[str, Any]]:
    with _jobs_lock:
        return [{"job_id": k, **v} for k, v in _jobs.items()]


# ── 模块加载时清理其他实例遗留的过期锁 ──
_cleanup_stale_lock_on_startup()

__all__ = [
    "PIPELINE_STAGES",
    "get_job",
    "list_jobs",
    "trigger_pipeline",
]
