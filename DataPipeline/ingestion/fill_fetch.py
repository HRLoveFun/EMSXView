"""
FillFetch Module — Bloomberg EMSX History API data retrieval.

Pipeline:
    1. Fetches fill data via Bloomberg EMSX History API (blpapi, TradingSystem scope)
    2. Computes SHA-256 hash for duplicate detection
    3. Deduplicates via in-memory hash index (O(1)) with DB fallback
    4. Upserts raw API data to raw_fills.db (primary storage)
    5. Tracks fetch history in fetch_log table

Optimizations:
    - Session reuse: single Bloomberg connection for entire date range
    - In-memory hash preload: O(1) per-day dedup without DB round-trip
    - Exponential back-off retry on transient failures
    - Schema migration: auto-adds missing derived columns to old DB files

Note on parallelism:
    Parallel Bloomberg sessions do NOT improve throughput because the bottleneck is
    the server-side PARTIAL_RESPONSE streaming (~4000 rows/s fixed rate). Multiple
    sessions share the same server bandwidth. This has been verified by benchmarking.

BloombergFillFetcher extracted to DataPipeline.acquisition.bloomberg_fill_fetcher.
SQLAlchemy FillFetchDatabase replaced with ConnectionManager-based FillFetchDatabase.
"""

import io
import os
import sys
import logging
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Callable, List, Dict, Any, Optional, Tuple, Set
from collections import defaultdict

import pandas as pd
from dotenv import load_dotenv

from DataPipeline.storage.connection import ConnectionManager, AccessTier
from DataPipeline.storage.schema.columns import EMSX_FILL_COLUMNS
from DataPipeline.storage.repositories.fetch_history import SqliteFetchHistoryRepository, compute_data_hash
from DataPipeline.acquisition._constants import (
    FILL_FIELD_EXTRACTORS,
)
from DataPipeline.acquisition.bloomberg_fill_fetcher import (
    BloombergFillFetcher,
    EMSXSessionError,
    EMSXServiceError,
    EMSXRequestError,
    EMSXQuotaError,
)
from DataPipeline.common.quota_pause import (
    is_quota_paused,
    set_quota_pause,
    clear_quota_pause,
)

def _configure_console_encoding() -> None:
    """配置控制台 stdout/stderr 为 UTF-8（仅独立运行时调用）。

    Windows 默认控制台编码为 cp1252，中文字符输出会触发 UnicodeEncodeError；
    强制 stdout/stderr 使用 UTF-8，避免日志中的中文消息编码失败。
    注意：当 stdout 被重定向为管道/文件时（如后端 subprocess.Popen），reconfigure 会抛出
    OSError: [Errno 22] Invalid argument，因此根据流类型选择安全的包装方式。

    禁止在模块级调用：import 时替换 sys.stdout 会破坏 pytest fd capture 的
    tmpfile 生命周期，导致 session 清理阶段 "I/O operation on closed file" 崩溃。
    """
    if sys.stdout.isatty() and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    else:
        if hasattr(sys.stdout, "buffer"):
            sys.stdout = io.TextIOWrapper(
                sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True
            )
        if hasattr(sys.stderr, "buffer"):
            sys.stderr = io.TextIOWrapper(
                sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True
            )

# 显式指定 UTF-8 读取 .env，避免 Windows 默认 locale 编码（cp1252）
# 对包含中文字符的配置值解码失败。
load_dotenv(encoding="utf-8")

logger = logging.getLogger(__name__)

def get_previous_weekday(today: Optional[date] = None) -> date:
    """Return the most recent completed weekday (not including today).

    Rules:
        - Mon-Fri -> yesterday
        - Saturday -> Friday
        - Sunday -> Friday
    """
    if today is None:
        today = date.today()
    candidate = today - timedelta(days=1)
    while candidate.weekday() >= 5:  # Sat=5, Sun=6
        candidate -= timedelta(days=1)
    return candidate

# ── Bloomberg EMSX Constants ─────────────────────────────────────────────

# 校验 FILL_FIELD_EXTRACTORS 与 EMSX_FILL_COLUMNS 的字段一致性
_MISSING_FIELDS = set(FILL_FIELD_EXTRACTORS.keys()) - set(EMSX_FILL_COLUMNS)
_EXTRA_FIELDS = set(EMSX_FILL_COLUMNS) - set(FILL_FIELD_EXTRACTORS.keys())
if _MISSING_FIELDS or _EXTRA_FIELDS:
    raise RuntimeError(
        f"FILL_FIELD_EXTRACTORS keys out of sync with EMSX_FILL_COLUMNS. "
        f"Missing: {_MISSING_FIELDS}, Extra: {_EXTRA_FIELDS}"
    )

EXPECTED_FILL_COLUMNS: List[str] = EMSX_FILL_COLUMNS

def fills_so_far_str(count: int) -> str:
    """Return a human-readable description of partial fetch progress."""
    return f"{count} fill(s) received so far"

# ── 超时降级分窗口拉取（2026-08-24 日更失败修复）──────────────────────────
# 根因：raw fill 数据量过大时，全天单次 GetFills 请求无法在 event 超时
# 窗口（3 consecutive timeouts，约 90s 无事件）内完成流式返回，被误判为
# "bbcomm may be unresponsive"。实测将全天拆为 6 个时间窗口（4h/窗口）
# 后可成功获取，故将该降级机制固化到获取流程：
#   全天请求超时 → 拆 SPLIT_WINDOW_HOURS 小时窗口；窗口级仍超时 →
#   二分降级（4h → 2h → 1h → …），直至 MIN_SPLIT_WINDOW_SECONDS 下限。
SPLIT_WINDOW_HOURS = 4
MIN_SPLIT_WINDOW_SECONDS = 1800


def _is_timeout_error(exc: Exception) -> bool:
    """判断异常是否为超时类错误（可安全降级为分时间窗口拉取）。

    关键词与 BloombergFillFetcher.fetch_fills 内部的超时重连判定保持
    一致；EMSXQuotaError 消息不含这些关键词，由调用方先于本函数排除。
    """
    text = str(exc).lower()
    return (
        "timeout" in text
        or "not responding" in text
        or "timed out" in text
    )

# ── Main FillFetch Class ─────────────────────────────────────────────────

class FillFetch:
    """Main FillFetch class that orchestrates the fetch process.

    Pipeline:
        1. Given a date, fetch fill data (TradingSystem scope)
        2. Compute the SHA-256 hash
        3. Check for duplicate via in-memory hash index + DB fallback
        4. Upsert raw API data to raw_fills.db
        5. Record in fetch_log
        6. Optionally save Excel file as archive
    """

    def __init__(self, data_dir: Optional[str] = None, db_path: Optional[str] = None):
        self.data_dir = Path(data_dir or os.getenv('FILLFETCH_DATA_DIR', './data/fills'))
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Primary DB access via repositories
        self.raw_fill_read = None
        self.raw_fill_write = None
        try:
            from DataPipeline.storage.repositories.raw_fills import SqliteRawFillReadRepository
            from DataPipeline.storage.repositories.raw_fills import SqliteRawFillWriteRepository
            cm = ConnectionManager()
            self.raw_fill_read = SqliteRawFillReadRepository(cm)
            self.raw_fill_write = SqliteRawFillWriteRepository(cm)
        except Exception as e:
            logger.warning(f"raw_fill_read/raw_fill_write init unavailable: {e}")

        # 拉取历史审计数据库
        self.db: Optional[SqliteFetchHistoryRepository] = None
        try:
            if db_path is not None:
                p = Path(db_path).resolve()
                p.parent.mkdir(parents=True, exist_ok=True)
                mgr = ConnectionManager(path_overrides={"fill_fetch_history": p})
                self.db = SqliteFetchHistoryRepository(connection_manager=mgr)
            else:
                self.db = SqliteFetchHistoryRepository()
            logger.info("fill_fetch_history 数据库已初始化")
        except Exception as e:
            logger.warning(
                "fill_fetch_history 数据库初始化失败: %s — 拉取审计记录将不可用",
                e,
            )

        self._known_hashes: Dict[str, Set[str]] = defaultdict(set)
        self._preload_known_hashes()

        logger.info(f"FillFetch initialized: data_dir={self.data_dir}, "
                     f"preloaded_hashes={sum(len(s) for s in self._known_hashes.values())}")

    def _preload_known_hashes(self):
        if self.raw_fill_read is not None:
            try:
                stats = self.raw_fill_read.get_fetch_log_stats()
                for record in stats:
                    date_key = record.get('source_date', '')
                    h = record.get('data_hash', '')
                    if date_key and h:
                        self._known_hashes[date_key].add(h)
                logger.debug(f"Preloaded {sum(len(s) for s in self._known_hashes.values())} hash entries")
            except Exception as e:
                logger.debug(f"Could not preload hashes (non-fatal): {e}")

    def _is_duplicate_in_memory(self, date_compact: str, hash_value: str) -> bool:
        return hash_value in self._known_hashes.get(date_compact, set())

    def _record_hash_in_memory(self, date_compact: str, hash_value: str):
        self._known_hashes[date_compact].add(hash_value)

    def _has_fetched_record(self, date_compact: str) -> bool:
        """该 source_date 是否曾在 fetch_log 中以 status='fetched' 记录过。

        用于空响应完整性判断：若预期有数据（合法工作日）但本次拉取为空，
        且从未成功拉取过，则判定为"应拉未拉"（可能是额度受限），写 failed。
        """
        if self.raw_fill_read is None:
            return False
        try:
            stats = self.raw_fill_read.get_fetch_log_stats()
            for record in stats:
                if (
                    record.get("source_date") == date_compact
                    and record.get("status") == "fetched"
                ):
                    return True
        except Exception as e:
            logger.debug(f"Could not check fetch_log for {date_compact}: {e}")
        return False

    def _is_expectable_trading_day(self, date_compact: str) -> bool:
        """判断某日期是否为预期应有数据的工作日（用于空响应完整性判断）。

        规则:
        - 非未来日期
        - 非周末 (周一~周五)
        - 不在 permanent_gap_dates（永久空缺豁免）中
        """
        try:
            from DataPipeline.common.permanent_gap_dates import load_permanent_gap_set
            permanent_gaps = load_permanent_gap_set()
            if date_compact in permanent_gaps:
                return False
        except Exception:
            pass
        try:
            target = datetime.strptime(date_compact, "%Y%m%d").date()
        except ValueError:
            return False
        if target > datetime.now().date():
            return False
        if target.weekday() >= 5:  # Sat=5, Sun=6
            return False
        return True

    def _should_treat_empty_as_quota(self, date_compact: str) -> bool:
        """空响应完整性判断：本次拉取为空是否应视为"应拉未拉"（额度受限）。

        返回 True 当且仅当：预期应有数据（合法工作日）且该日期从未成功拉取过。
        两者皆满足才写 failed + 置位暂停，避免把法定节假日误判为失败。
        """
        if not self._is_expectable_trading_day(date_compact):
            return False
        if self._has_fetched_record(date_compact):
            # 已成功拉取过：本次空更可能是"真无新增成交"或非交易日，维持 empty
            return False
        return True

    def _record_quota_failure(
        self, date_compact: str, reason: str, detail: Optional[str] = None,
    ) -> None:
        """额度受限统一处理：写 fetch_log failed + 置位暂停标记。"""
        if self.raw_fill_write is not None:
            try:
                self.raw_fill_write.record_fetch_failed(
                    date_compact, reason, detail=detail
                )
            except Exception as e:
                logger.error(
                    f"Failed to record fetch failure for {date_compact}: {e}"
                )
        set_quota_pause(reason, detail=detail)
        logger.warning(
            "QUOTA: %s %s — 置位暂停标记，额度恢复后自动重拉",
            date_compact, detail or reason,
        )

    def determine_fetch_range(self) -> Optional[Tuple[date, date]]:
        """计算增量拉取窗口。

        缺口扫描策略（2026-08-12 重设计）：
            - 不使用交易日历，不考虑任何假期；周一至周五一律视为需要拉取的
              交易日（全球市场）。
            - 从最早已拉取日期到上一工作日，逐日枚举所有 weekday，
              start = 第一个「未成功拉取」的工作日，end = 上一工作日。
            - 任何原因（拉取失败、进程中断、历史锚点跳过）造成的缺口，
              都会在下一次运行时从缺口起点重新尝试拉取，不会 silently 跳过。
            - 已拉取日期由 fetch_range_aggregated 的 hash 去重跳过，重复安全。
            - 被标记为「永久空缺」（如 Bloomberg 保留窗口已过）的日期从缺口
              集合中剔除，不再尝试拉取、不再告警。
        """
        from DataPipeline.config import Config as Cfg
        today = date.today()
        prev_wd = get_previous_weekday(today)
        fetched: Set[str] = set()
        if self.raw_fill_read is not None:
            try:
                stats = self.raw_fill_read.get_fetch_log_stats()
                for record in stats:
                    if record.get("status") == "fetched" and record.get("source_date"):
                        fetched.add(record["source_date"])
            except Exception as e:
                logger.debug(f"Could not read fetch_log: {e}")
        # 永久空缺豁免：Bloomberg 保留窗口已过、确认无法拉取的日期
        permanent_gaps: Set[str] = set()
        try:
            from DataPipeline.common.permanent_gap_dates import load_permanent_gap_set
            permanent_gaps = load_permanent_gap_set()
        except Exception as e:
            logger.debug(f"Could not read permanent gap dates (non-fatal): {e}")
        if not fetched:
            first_day = today - timedelta(days=Cfg.FIRST_RUN_LOOKBACK_DAYS)
            logger.info(f"FIRST RUN: fetching {first_day} -> {prev_wd}")
            return first_day, prev_wd
        earliest = datetime.strptime(min(fetched), "%Y%m%d").date()
        start: Optional[date] = None
        current = earliest
        while current <= prev_wd:
            ds = current.strftime("%Y%m%d")
            if current.weekday() < 5 and ds not in fetched and ds not in permanent_gaps:
                start = current
                break
            current += timedelta(days=1)
        if start is None:
            logger.info("Already up-to-date (no missing trading weekdays)")
            return None
        # 收集缺口列表用于日志告警
        missing: List[str] = []
        current = start
        while current <= prev_wd:
            ds = current.strftime("%Y%m%d")
            if current.weekday() < 5 and ds not in fetched and ds not in permanent_gaps:
                missing.append(ds)
            current += timedelta(days=1)
        logger.warning(
            "检测到 %d 个缺失交易日（未成功拉取）：%s — 将自 %s 起补齐",
            len(missing),
            ", ".join(missing),
            start.strftime("%Y%m%d"),
        )
        logger.info(f"INCREMENTAL (gap-fill): {start} -> {prev_wd}")
        return start, prev_wd

    def _get_date_range(self, target_date: date) -> Tuple[datetime, datetime]:
        start = datetime.combine(target_date, datetime.min.time())
        end = datetime.combine(target_date, datetime.max.time().replace(microsecond=0))
        return start, end

    def _fetch_fills_with_split_fallback(
        self,
        client: "BloombergFillFetcher",
        from_dt: datetime,
        to_dt: datetime,
        order_date: str,
    ) -> List[Dict[str, Any]]:
        """拉取 fills 的统一入口：全天请求超时自动降级为分时间窗口拉取。

        数据量过大时，全天 GetFills 请求在 event 超时窗口内无法完成流式
        返回（3 consecutive timeouts），此时拆分为 4h 窗口分批请求。
        额度类错误（EMSXQuotaError）不降级，直接上抛由调用方置位暂停。
        """
        try:
            return client.fetch_fills(from_dt, to_dt)
        except EMSXQuotaError:
            raise
        except EMSXRequestError as exc:
            if not _is_timeout_error(exc):
                raise
            logger.warning(
                "%s 全天请求超时（数据量过大），降级为 %dh 窗口分批拉取",
                order_date, SPLIT_WINDOW_HOURS,
            )
            return self._fetch_fills_split(
                client, from_dt, to_dt, hours=SPLIT_WINDOW_HOURS
            )

    def _fetch_fills_split(
        self,
        client: "BloombergFillFetcher",
        from_dt: datetime,
        to_dt: datetime,
        hours: int = 4,
    ) -> List[Dict[str, Any]]:
        """将大时间范围拆分为多个小时窗口分别拉取，用于规避后端 TIMEOUT。"""
        all_fills: List[Dict[str, Any]] = []
        window_start = from_dt
        while window_start < to_dt:
            window_end = min(window_start + timedelta(hours=hours), to_dt)
            logger.info(
                "拉取窗口 %s -> %s",
                window_start.strftime("%Y-%m-%d %H:%M:%S"),
                window_end.strftime("%Y-%m-%d %H:%M:%S"),
            )
            window_fills = self._fetch_window_with_bisect(
                client, window_start, window_end
            )
            all_fills.extend(window_fills)
            window_start = window_end
        return all_fills

    def _fetch_window_with_bisect(
        self,
        client: "BloombergFillFetcher",
        window_start: datetime,
        window_end: datetime,
    ) -> List[Dict[str, Any]]:
        """拉取单个时间窗口，超时（数据量极大）时二分降级重试。

        4h → 2h → 1h → … 逐级二分，直至 MIN_SPLIT_WINDOW_SECONDS 下限；
        降至最小窗口仍超时则抛出原始异常。非超时错误不降级直接上抛。
        """
        try:
            return client.fetch_fills(window_start, window_end)
        except EMSXQuotaError:
            raise
        except EMSXRequestError as exc:
            if not _is_timeout_error(exc):
                raise
            duration = (window_end - window_start).total_seconds()
            if duration <= MIN_SPLIT_WINDOW_SECONDS:
                raise
            mid = window_start + (window_end - window_start) / 2
            logger.warning(
                "窗口 %s -> %s 超时，二分降级重试",
                window_start.strftime("%Y-%m-%d %H:%M:%S"),
                window_end.strftime("%Y-%m-%d %H:%M:%S"),
            )
            left = self._fetch_window_with_bisect(client, window_start, mid)
            right = self._fetch_window_with_bisect(client, mid, window_end)
            return left + right

    def _save_to_excel(self, data: List[Dict[str, Any]], file_path: Path) -> bool:
        try:
            df = pd.DataFrame(data)
            for col in EXPECTED_FILL_COLUMNS:
                if col not in df.columns:
                    df[col] = None
            df.to_excel(file_path, index=False, engine='openpyxl')
            logger.info(f"Saved {len(data)} records to {file_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to save Excel: {e}")
            return False

    def fetch_day(self, target_date: date,
                  skip_duplicates: bool = True, force: bool = False,
                  archive_excel: bool = False) -> Dict[str, Any]:
        if force:
            skip_duplicates = False
        order_date = target_date.strftime('%Y-%m-%d')
        date_compact = target_date.strftime('%Y%m%d')
        scope_desc = "TradingSystem (login-based)"
        logger.info(f"Fetching fills for {order_date} ({scope_desc})")
        result: Dict[str, Any] = {
            'order_date': order_date, 'success': False,
            'skipped': False, 'rows_fetched': 0, 'hash_value': None,
            'rows_upserted': 0, 'file_path': None, 'error': None,
        }
        try:
            from_dt, to_dt = self._get_date_range(target_date)
            with BloombergFillFetcher() as client:
                try:
                    fills = self._fetch_fills_with_split_fallback(
                        client, from_dt, to_dt, order_date
                    )
                except EMSXQuotaError as exc:
                    # 005-bloomberg-quota-pause: 额度类错误不重试，直接记录并置位暂停
                    self._record_quota_failure(
                        date_compact,
                        "fill_api_error",
                        detail=f"quota-class API error: {exc}",
                    )
                    result['success'] = False
                    result['error'] = f"Bloomberg quota likely exhausted: {exc}"
                    return result
            if not fills:
                # 005-bloomberg-quota-pause: 空响应完整性判断。
                # 额度受限时 Bloomberg 可能返回空 GetFillsResponse，不能被当"无成交日"。
                if self._should_treat_empty_as_quota(date_compact):
                    self._record_quota_failure(
                        date_compact,
                        "fill_empty_response",
                        detail="expected fills but API returned empty (possible quota exhaustion)",
                    )
                    result['success'] = False
                    result['error'] = "Quota likely exhausted: empty fill response for a trading day with no prior fetch"
                    return result
                logger.info(f"No fills found for {order_date}")
                result['success'] = True
                result['message'] = "No fills found"
                return result
            hash_value = compute_data_hash(fills)
            result['hash_value'] = hash_value
            result['rows_fetched'] = len(fills)
            logger.info(f"Fetched {len(fills)} fills, hash={hash_value[:16]}...")
            if skip_duplicates:
                if self._is_duplicate_in_memory(date_compact, hash_value):
                    logger.info(f"Duplicate data found for {order_date} (memory), skipping")
                    result['skipped'] = True; result['success'] = True
                    result['message'] = f"Duplicate (hash={hash_value[:16]}...)"
                    return result
                if self.raw_fill_read is not None:
                    if self.raw_fill_write.check_fetch_duplicate(date_compact, hash_value):
                        logger.info(f"Duplicate data found for {order_date} (DB), skipping")
                        self._record_hash_in_memory(date_compact, hash_value)
                        result['skipped'] = True; result['success'] = True
                        result['message'] = f"Duplicate (hash={hash_value[:16]}...)"
                        return result
            try:
                from DataPipeline.processing.validate_raw_fills import validate_fill_data, save_anomaly_report
                val_result = validate_fill_data(fills, source_date=date_compact)
                result['validation'] = {
                    'success': val_result.success, 'total_orders': val_result.total_orders,
                    'failed_orders': val_result.failed_orders, 'pass_rate': f"{val_result.pass_rate:.2%}",
                }
                if not val_result.success and not val_result.anomalies_df.empty:
                    logger.warning(f"Validation FAILED for {order_date}: {val_result.failed_orders}/{val_result.total_orders}")
                    report_path = save_anomaly_report(val_result)
                    if report_path:
                        result['anomaly_report'] = str(report_path)
            except Exception as val_err:
                logger.warning(f"Fill-share validation skipped (error): {val_err}")
                result['validation'] = {'error': str(val_err)}
            rows_upserted = 0
            if self.raw_fill_read is not None:
                rows_upserted = self.raw_fill_write.upsert_raw_api_data(fills, source_date=date_compact)
            result['rows_upserted'] = rows_upserted
            if self.raw_fill_read is not None:
                self.raw_fill_write.add_fetch_log_record(source_date=date_compact, row_count=len(fills), data_hash=hash_value)
                self.raw_fill_write.upsert_order_fetch_log(fills, source_date=date_compact)
                self._record_hash_in_memory(date_compact, hash_value)
            if archive_excel:
                file_name = f"fills_{date_compact}.xlsx"
                file_path = self.data_dir / file_name
                if self._save_to_excel(fills, file_path):
                    result['file_path'] = str(file_path)
            # 写入 fill_fetch_history 审计记录
            if self.db is not None:
                try:
                    fetch_time = f"{from_dt.strftime('%H:%M:%S')}-{to_dt.strftime('%H:%M:%S')}"
                    self.db.add_fetch_record(order_date=order_date, fetch_time=fetch_time,
                                              row_count=len(fills), hash_value=hash_value,
                                              file_path=result.get('file_path'))
                    logger.debug("fill_fetch_history 审计记录已写入: %s", order_date)
                except Exception as e:
                    logger.error(
                        "fill_fetch_history 审计记录写入失败 (%s): %s",
                        order_date, e,
                    )
            result['success'] = True
            result['message'] = f"Fetched {len(fills)} fills, upserted {rows_upserted} to raw_fills.db"
            logger.info(f"Fetch completed for {order_date}: {result['message']}")
        except Exception as e:
            logger.error(f"Error fetching fills for {order_date}: {e}")
            result['error'] = str(e)
        return result

    def fetch_range(self, start_date: date, end_date: date,
                    force: bool = False,
                    archive_excel: bool = False) -> List[Dict[str, Any]]:
        results = []
        current = start_date
        while current <= end_date:
            result = self.fetch_day(current, force=force, archive_excel=archive_excel)
            results.append(result)
            current += timedelta(days=1)
        return results

    def fetch_range_aggregated(self, start_date: date, end_date: date,
                               skip_duplicates: bool = True, force: bool = False,
                               archive_excel: bool = False,
                               progress_callback: Optional[Callable[[int, int, str, int, str], None]] = None) -> Dict[str, Any]:
        if force:
            skip_duplicates = False
        scope_desc = "TradingSystem (login-based)"
        logger.info(f"Starting aggregated fetch: {start_date} to {end_date} ({scope_desc})")
        all_records: List[Dict[str, Any]] = []
        day_summaries: List[Dict[str, Any]] = []
        saved_files: List[str] = []
        total_days = (end_date - start_date).days + 1
        skipped_days = 0; no_fill_days = 0; error_days = 0
        with BloombergFillFetcher() as client:
            current = start_date
            day_idx = 0
            # 005-bloomberg-quota-pause: 置位暂停时，先用首个工作日做一次真实探测。
            # 成功即清除标记并继续正常拉取；失败则保持置位并短路剩余日期。
            # quota_shortcircuited: 短路发生时 summary.success 必须为 False —
            # 否则日更层会把"额度暂停跳过全部日期"误判为拉取成功（静默失败）。
            quota_shortcircuited = False
            if is_quota_paused():
                probe_date = current
                while probe_date.weekday() >= 5:
                    probe_date += timedelta(days=1)
                if probe_date > end_date:
                    logger.warning("QUOTA paused — no probe day in range; skipping fetch")
                    current = end_date + timedelta(days=1)
                    quota_shortcircuited = True
                else:
                    try:
                        probe_from, probe_to = self._get_date_range(probe_date)
                        probe_fills = self._fetch_fills_with_split_fallback(
                            client, probe_from, probe_to,
                            probe_date.strftime("%Y-%m-%d"),
                        )
                        clear_quota_pause()
                        logger.warning(
                            "QUOTA probe SUCCESS on %s — quota recovered, resuming fetch",
                            probe_date.strftime("%Y%m%d"),
                        )
                        current = probe_date
                    except EMSXQuotaError as exc:
                        logger.warning(
                            "QUOTA probe FAILED on %s (%s) — staying paused, skipping fetch",
                            probe_date.strftime("%Y%m%d"), exc,
                        )
                        current = end_date + timedelta(days=1)
                        quota_shortcircuited = True
                    except Exception as exc:
                        logger.warning(
                            "QUOTA probe error on %s (%s) — staying paused, skipping fetch",
                            probe_date.strftime("%Y%m%d"), exc,
                        )
                        current = end_date + timedelta(days=1)
                        quota_shortcircuited = True
            while current <= end_date:
                if current.weekday() >= 5:
                    current += timedelta(days=1)
                    continue
                day_idx += 1
                order_date = current.strftime('%Y-%m-%d')
                date_compact = current.strftime('%Y%m%d')
                weekdays_in_range = max(1, sum(1 for i in range((end_date - start_date).days + 1)
                                               if (start_date + timedelta(days=i)).weekday() < 5))
                logger.info(f"[{day_idx}/{weekdays_in_range}] Processing {order_date}...")
                if progress_callback:
                    progress_callback(day_idx - 1, weekdays_in_range, order_date, 0, "Fetching from EMSX/Bloomberg…")
                try:
                    from_dt, to_dt = self._get_date_range(current)
                    fills = self._fetch_fills_with_split_fallback(
                        client, from_dt, to_dt, order_date
                    )
                    if not fills:
                        # 005-bloomberg-quota-pause: 空响应完整性判断
                        if self._should_treat_empty_as_quota(date_compact):
                            self._record_quota_failure(
                                date_compact,
                                "fill_empty_response",
                                detail="expected fills but API returned empty (possible quota exhaustion)",
                            )
                            day_summaries.append({
                                'order_date': order_date, 'rows': 0,
                                'status': 'failed',
                                'error': 'quota_paused(fill_empty)',
                            })
                            error_days += 1
                            if progress_callback:
                                progress_callback(
                                    day_idx, weekdays_in_range, order_date, 0,
                                    "Quota paused (empty response)",
                                )
                            current += timedelta(days=1)
                            continue
                        day_summaries.append({'order_date': order_date, 'rows': 0, 'status': 'empty'})
                        no_fill_days += 1
                        if progress_callback:
                            progress_callback(day_idx, weekdays_in_range, order_date, 0, "No fills found")
                        current += timedelta(days=1)
                        continue
                    hash_value = compute_data_hash(fills)
                    if skip_duplicates:
                        if self._is_duplicate_in_memory(date_compact, hash_value):
                            day_summaries.append({'order_date': order_date, 'rows': len(fills), 'status': 'skipped'})
                            skipped_days += 1
                            if progress_callback:
                                progress_callback(day_idx, weekdays_in_range, order_date, len(fills), "Duplicate (memory)")
                            current += timedelta(days=1)
                            continue
                        if self.raw_fill_read is not None:
                            if self.raw_fill_write.check_fetch_duplicate(date_compact, hash_value):
                                self._record_hash_in_memory(date_compact, hash_value)
                                day_summaries.append({'order_date': order_date, 'rows': len(fills), 'status': 'skipped'})
                                skipped_days += 1
                                if progress_callback:
                                    progress_callback(day_idx, weekdays_in_range, order_date, len(fills), "Duplicate (DB)")
                                current += timedelta(days=1)
                                continue
                    all_records.extend(fills)
                    try:
                        from DataPipeline.processing.validate_raw_fills import validate_fill_data, save_anomaly_report
                        val_result = validate_fill_data(fills, source_date=date_compact)
                        if not val_result.success and not val_result.anomalies_df.empty:
                            logger.warning(f"Validation FAILED for {order_date}: {val_result.failed_orders}/{val_result.total_orders}")
                            report_path = save_anomaly_report(val_result)
                            if report_path:
                                logger.warning(f"Anomaly report saved: {report_path}")
                    except Exception as val_err:
                        logger.warning(f"Fill-share validation skipped (error): {val_err}")
                    rows_upserted = 0
                    if self.raw_fill_read is not None:
                        rows_upserted = self.raw_fill_write.upsert_raw_api_data(fills, source_date=date_compact)
                        self.raw_fill_write.add_fetch_log_record(source_date=date_compact, row_count=len(fills), data_hash=hash_value)
                        self.raw_fill_write.upsert_order_fetch_log(fills, source_date=date_compact)
                        self._record_hash_in_memory(date_compact, hash_value)
                    if archive_excel:
                        day_file_name = f"fills_{date_compact}.xlsx"
                        day_file_path = self.data_dir / day_file_name
                        if self._save_to_excel(fills, day_file_path):
                            saved_files.append(str(day_file_path))
                    day_summaries.append({'order_date': order_date, 'rows': len(fills), 'rows_upserted': rows_upserted, 'status': 'fetched'})
                    logger.info(f"  Fetched {len(fills)} fills for {order_date} (upserted {rows_upserted})")
                    if progress_callback:
                        detail = f"{len(fills)} rows, upserted {rows_upserted}" if rows_upserted else f"{len(fills)} rows"
                        progress_callback(day_idx, weekdays_in_range, order_date, len(fills), detail)
                    if self.db is not None:
                        try:
                            fetch_time = f"{from_dt.strftime('%H:%M:%S')}-{to_dt.strftime('%H:%M:%S')}"
                            self.db.add_fetch_record(order_date=order_date, fetch_time=fetch_time,
                                                      row_count=len(fills), hash_value=hash_value,
                                                      file_path=saved_files[-1] if saved_files else None)
                            logger.debug("fill_fetch_history 审计记录已写入: %s", order_date)
                        except Exception as e:
                            logger.error(
                                "fill_fetch_history 审计记录写入失败 (%s): %s",
                                order_date, e,
                            )
                except EMSXQuotaError as exc:
                    # 005-bloomberg-quota-pause: 额度类错误置位暂停并记录 failed
                    self._record_quota_failure(
                        date_compact,
                        "fill_api_error",
                        detail=f"quota-class API error: {exc}",
                    )
                    day_summaries.append({
                        'order_date': order_date, 'rows': 0,
                        'status': 'failed',
                        'error': f'quota_paused(fill_api_error): {exc}',
                    })
                    error_days += 1
                    if progress_callback:
                        progress_callback(
                            day_idx, weekdays_in_range, order_date, 0,
                            f"Quota paused: {exc}",
                        )
                except Exception as e:
                    logger.error(f"  Error fetching {order_date}: {e}")
                    day_summaries.append({'order_date': order_date, 'rows': 0, 'status': 'error', 'error': str(e)})
                    error_days += 1
                    if progress_callback:
                        progress_callback(day_idx, weekdays_in_range, order_date, 0, f"Error: {e}")
                current += timedelta(days=1)
        summary = {
            'start_date': start_date.strftime('%Y%m%d'),
            'end_date': end_date.strftime('%Y%m%d'),
            'scope': scope_desc, 'total_days': total_days,
            'days_fetched': len([s for s in day_summaries if s['status'] == 'fetched']),
            'days_skipped': skipped_days, 'days_empty': no_fill_days, 'days_error': error_days,
            'total_rows': len(all_records), 'files': saved_files,
            # quota 短路（probe 失败/无 probe 日）跳过全部日期时必须报失败，
            # 不能因 error_days == 0 而伪装成功（静默失败修复 2026-08-21）
            'success': error_days == 0 and not quota_shortcircuited,
            # 005-bloomberg-quota-pause: 摘要标记
            'quota_paused': is_quota_paused(),
        }
        logger.info(f"Range fetch complete: {summary['total_rows']} rows across {summary['days_fetched']} days")
        return summary

    def get_history(self, order_date: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        if self.raw_fill_read is not None:
            try:
                stats = self.raw_fill_read.get_fetch_log_stats()
                if order_date:
                    stats = [s for s in stats if s.get('source_date') == order_date.replace('-', '')]
                return stats[:limit]
            except Exception:
                pass
        if self.db is not None:
            return self.db.get_fetch_history(order_date, limit)
        return []

    def get_stats(self) -> Dict[str, Any]:
        stats: Dict[str, Any] = {}
        if self.raw_fill_read is not None:
            try:
                stats['raw_fills_rows'] = self.raw_fill_read.get_row_count()
                stats['raw_fills_dates'] = self.raw_fill_read.get_date_row_counts()
            except Exception:
                pass
        if self.db is not None:
            try:
                stats['legacy'] = self.db.get_stats()
            except Exception:
                pass
        try:
            from DataPipeline.storage.facade import DatabaseFacade
            proc_db = DatabaseFacade()
            stats['execution_history'] = proc_db.fills_read.get_execution_history_stats()
        except Exception:
            pass
        return stats

    def close(self):
        if self.db is not None and hasattr(self.db, 'close'):
            self.db.close()

def setup_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    if root.handlers:
        return
    handlers: List[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    # 独立运行时同时写入日志文件，避免控制台输出丢失导致无法排查问题
    log_dir = Path("logs/pipeline")
    log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(
        log_dir / "fill_fetch_direct.log", encoding="utf-8", mode="a"
    )
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    handlers.append(file_handler)
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=handlers,
    )

def main():
    import argparse
    parser = argparse.ArgumentParser(description='FillFetch - EMSX Fill Data Fetcher')
    parser.add_argument('--date', type=str, help='Date to fetch (YYYY-MM-DD)')
    parser.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD)')
    parser.add_argument('--force', action='store_true', help='Force re-fetch')
    parser.add_argument('--aggregate', action='store_true', help='Aggregate range fetch')
    parser.add_argument('--data-dir', type=str, help='Data directory')
    parser.add_argument('--db-path', type=str, help='Legacy database path')
    parser.add_argument('--history', action='store_true', help='Show fetch history')
    parser.add_argument('--stats', action='store_true', help='Show statistics')
    parser.add_argument('--get-teams', action='store_true', help='List EMSX teams')
    parser.add_argument('--get-trade-desks', action='store_true', help='List EMSX trade desks')
    parser.add_argument('--log-level', type=str, default='INFO', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'])
    parser.add_argument('--auto', action='store_true', help='Auto mode')
    parser.add_argument('--archive-excel', action='store_true', help='Save Excel archives')
    args = parser.parse_args()
    _configure_console_encoding()
    setup_logging(args.log_level)
    if args.get_teams or args.get_trade_desks:
        from DataPipeline.acquisition.emsx_client import EMSXHistoryClient
        with EMSXHistoryClient() as client:
            if args.get_trade_desks:
                desks = client.get_trade_desks()
                print("\n=== EMSX Trade Desks ===")
                for d in desks: print(f"  {d}")
            if args.get_teams:
                teams = client.get_teams()
                print("\n=== EMSX Teams ===")
                for t in teams: print(f"  {t}")
        return
    fetcher = FillFetch(data_dir=args.data_dir, db_path=args.db_path)
    try:
        if args.auto:
            fetch_range = fetcher.determine_fetch_range()
            if fetch_range is None:
                print("Already up-to-date. Nothing to fetch.")
                return
            start, end = fetch_range
            print(f"Auto mode: fetching {start} -> {end}")
            summary = fetcher.fetch_range_aggregated(start, end, force=args.force, archive_excel=args.archive_excel)
        elif args.date:
            d = datetime.strptime(args.date, '%Y-%m-%d').date()
            result = fetcher.fetch_day(d, force=args.force, archive_excel=args.archive_excel)
            _print_result(result)
            return
        elif args.start_date and args.end_date:
            start = datetime.strptime(args.start_date, '%Y-%m-%d').date()
            end = datetime.strptime(args.end_date, '%Y-%m-%d').date()
            if args.aggregate:
                summary = fetcher.fetch_range_aggregated(start, end, force=args.force, archive_excel=args.archive_excel)
                _print_summary(summary)
            else:
                results = fetcher.fetch_range(start, end, force=args.force, archive_excel=args.archive_excel)
                for r in results:
                    _print_result(r)
            return
        elif args.history:
            history = fetcher.get_history()
            print(f"\nFetch History ({len(history)} records):")
            for h in history:
                print(f"  {h}")
            return
        elif args.stats:
            stats = fetcher.get_stats()
            print("\nFillFetch Statistics:")
            for k, v in stats.items():
                print(f"  {k}: {v}")
            return
        else:
            parser.print_help()
    finally:
        fetcher.close()

def _print_result(result: Dict[str, Any]):
    print(f"\n=== Fetch Result: {result['order_date']} ===")
    print(f"  Success: {result['success']}")
    print(f"  Skipped: {result.get('skipped', False)}")
    print(f"  Rows: {result['rows_fetched']} fetched, {result['rows_upserted']} upserted")
    if result.get('error'):
        print(f"  Error: {result['error']}")
    if result.get('validation'):
        print(f"  Validation: {result['validation']}")

def _print_summary(summary: Dict[str, Any]):
    print(f"\n=== Range Fetch Summary ===")
    print(f"  Range: {summary['start_date']} -> {summary['end_date']}")
    print(f"  Total days: {summary['total_days']}")
    print(f"  Fetched: {summary['days_fetched']}, Skipped: {summary['days_skipped']}")
    print(f"  Empty: {summary['days_empty']}, Errors: {summary['days_error']}")
    print(f"  Total rows: {summary['total_rows']}")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.exception("fill_fetch 主程序异常退出: %s", e)
        print(f"FATAL: fill_fetch 异常退出: {e}", file=sys.stderr, flush=True)
        raise
