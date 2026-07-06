"""
Fill Ingestion — bridge between raw fetched data and the processing pipeline.

Provides two modes:

    Mode 1 (DEPRECATED — v2.0 移除): Excel -> clean -> raw_fills.db
        ingest_excel_file() / ingest_all_excel_files()
        ⚠️ **DEPRECATED**: 数据已不再从 Excel 获取，本路径将于 v2.0 移除。
        请使用 Mode 2 + Bloomberg API 摄入（fill_fetch.py）替代。
        Kept for backward compatibility with historical Excel archives.

    Mode 2 (ACTIVE): raw_fills.db -> clean -> process -> processed_fills.db
        process_raw_fills_for_date()
        LAYER 1 entry point: reads raw_fills from DB, runs cleaning + enrichment,
        upserts to processed_fills.db with a fixed 27-column schema.

"""

from __future__ import annotations

import logging
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

RawFillsDB = Any  # backward compat alias; was CostView/src/raw_fills_db.py

import pandas as pd

from DataPipeline.processing.fill_cleaner import clean_emsx_fills
from DataPipeline.processing.fill_processor import process_fills
from DataPipeline.config import Config
from DataPipeline.storage.repositories.raw_fills import SqliteRawFillReadRepository
from DataPipeline.storage.facade import DatabaseFacade
from DataPipeline.storage.repositories.fetch_history import compute_data_hash

logger = logging.getLogger(__name__)

def _first_non_empty(series: pd.Series) -> Optional[str]:
    for value in series:
        if pd.isna(value) or value is None:
            continue
        text = str(value).strip()
        if not text or text.lower() in {"nan", "none"}:
            continue
        return text
    return None

def _weighted_average(frame: pd.DataFrame, value_col: str, weight_col: str) -> Optional[float]:
    if value_col not in frame.columns or weight_col not in frame.columns:
        return None
    values = pd.to_numeric(frame[value_col], errors="coerce")
    weights = pd.to_numeric(frame[weight_col], errors="coerce")
    valid = values.notna() & weights.notna() & (weights > 0)
    if not valid.any():
        return None
    total_weight = float(weights[valid].sum())
    if total_weight <= 0:
        return None
    return float((values[valid] * weights[valid]).sum() / total_weight)

def _first_last_event_time(group: pd.DataFrame) -> tuple[Optional[str], Optional[str]]:
    """返回 group 中最早的 first_fill_time / 最新的 last_fill_time (ISO8601 字符串)。

    v2 修复：
    ① 统一只取 `local_fill_datetime` 列（已经过 NY→local exchange tz 转换，字符串无 tz 后缀），
       不再兜底使用 `DateTimeOfFill`（NY tz 含 tz 后缀），避免字符串比较时混用两种 tz 语义。
    ② 用 `pd.to_datetime` 解析为 datetime 对象后再 `min/max`，避免跨日/跨午时字符串字典序
       与时间序不一致的 bug（如 `"16:03:01" < "9:30:00"`）。
    ③ 输出统一 `YYYY-MM-DDTHH:MM:SS` 格式（无 tz 后缀），与原 schema 兼容。
    """
    if "local_fill_datetime" not in group.columns:
        return None, None
    raw = group["local_fill_datetime"]
    parsed = pd.to_datetime(raw, errors="coerce")
    valid = parsed.dropna()
    if valid.empty:
        return None, None
    return (
        valid.min().strftime("%Y-%m-%dT%H:%M:%S"),
        valid.max().strftime("%Y-%m-%dT%H:%M:%S"),
    )

def _build_execution_history_frames(
    processed_df: pd.DataFrame,
    route_reg_df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """构建 route_history / route_event_history 写入 DataFrame。

    v2 修复：
    ① **移除 route_attrs 二次 merge**：原实现先从 `route_reg_df` 取出 (OrderId, RouteId, equ_ticker,
       ccy_ticker, Side) 五列，再 left join 回 `processed_df`。但 `route_reg_df` 本身是由 processed
       衍生的 (line 389)，导致 `equ_ticker` 等字段依赖 `processed.equ_ticker`；一旦 processed 列为空
       (因 add_equity_ticker 拼接出空字符串等)，route_history 也会继承空值。
       改为直接遍历 `processed_df`，所有字段（equ_ticker / ccy_ticker / Side / Broker / algo / TraderName /
       Exchange）从 processed 自身取，与 `event_records` 同源。
    ② **统一用 local_fill_datetime** 作 `event_timestamp`，移除 DateTimeOfFill 兜底（避免混用 NY tz
       与 local tz 字符串）。
    ③ **source_refreshed_at 改 UTC 带 +00:00 后缀**：`datetime.now(timezone.utc).isoformat()` 输出
       `2026-06-17T00:52:10+00:00`，比 `datetime.utcnow()` (naive UTC) 更明确。
    ④ `route_reg_df` 参数保留以保持调用方 API 兼容，但不再使用（line 388 仍可保留构造）。
    """
    # v2: 移除 route_attrs 二次 merge —— 不再使用 route_reg_df
    enriched_df = processed_df

    # v2: UTC 带 tz 后缀（datetime.now(timezone.utc)），不再使用 datetime.utcnow() (naive)
    refreshed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    order_lineage = " > ".join(Config.EXECUTION_HISTORY_SOURCE_POLICY["orders"])
    route_lineage = " > ".join(Config.EXECUTION_HISTORY_SOURCE_POLICY["routes"])
    event_lineage = " > ".join(Config.EXECUTION_HISTORY_SOURCE_POLICY["route_events"])

    # PR-1: 不再生成 order_records — order_history 是 route_history 的 VIEW 派生
    # 保留 Config.EXECUTION_HISTORY_SOURCE_POLICY["orders"] 仅用于 lineage 文档
    route_records: list[dict[str, Any]] = []
    groupby_cols = ["OrderId", "RouteId", "order_as_of_date"]
    for (order_id, route_id, order_as_of_date), group in enriched_df.groupby(groupby_cols, dropna=False, sort=False):
        first_fill_time, last_fill_time = _first_last_event_time(group)
        route_records.append(
            {
                "OrderId": str(order_id),
                "RouteId": str(route_id),
                "order_as_of_date": str(order_as_of_date),
                # v2: 字段全部从 processed 自身取（不再依赖 route_reg_df merge）
                "equ_ticker": _first_non_empty(group.get("equ_ticker", pd.Series(dtype=object))),
                "ccy_ticker": _first_non_empty(group.get("ccy_ticker", pd.Series(dtype=object))),
                "Side": _first_non_empty(group.get("Side", pd.Series(dtype=object))),
                "Broker": _first_non_empty(group.get("Broker", pd.Series(dtype=object))),
                "algo": _first_non_empty(group.get("algo", pd.Series(dtype=object))),
                "TraderName": _first_non_empty(group.get("TraderName", pd.Series(dtype=object))),
                "Exchange": _first_non_empty(group.get("Exchange", pd.Series(dtype=object))),
                "fill_count": int(group["FillId"].astype(str).nunique()),
                "total_fill_shares": pd.to_numeric(group.get("FillShares"), errors="coerce").sum(min_count=1),
                "order_amount": pd.to_numeric(group.get("Amount"), errors="coerce").max(),
                "route_shares": pd.to_numeric(group.get("RouteShares"), errors="coerce").max(),
                "average_fill_price": _weighted_average(group, "FillPrice", "FillShares"),
                "first_fill_time": first_fill_time,
                "last_fill_time": last_fill_time,
                "primary_source": Config.EXECUTION_HISTORY_SOURCE_POLICY["routes"][0],
                "source_priority": route_lineage,
                "refresh_strategy": Config.EXECUTION_HISTORY_REFRESH_POLICY["routes"],
                "source_refreshed_at": refreshed_at,
                "source_lineage": "processed_fills -> route_history",
            }
        )

    event_records: list[dict[str, Any]] = []
    for row in enriched_df.itertuples(index=False):
        row_map = row._asdict()
        order_id = str(row_map.get("OrderId"))
        route_id = str(row_map.get("RouteId"))
        fill_id = str(row_map.get("FillId"))
        order_as_of_date = str(row_map.get("order_as_of_date"))
        # v2: 统一用 local_fill_datetime，不再兜底 DateTimeOfFill
        event_timestamp = row_map.get("local_fill_datetime")
        event_records.append(
            {
                "event_id": f"fill:{order_id}:{route_id}:{fill_id}:{order_as_of_date}",
                "OrderId": order_id,
                "RouteId": route_id,
                "FillId": fill_id,
                "order_as_of_date": order_as_of_date,
                "event_timestamp": None if event_timestamp is None or pd.isna(event_timestamp) else str(event_timestamp),
                "event_type": "FILL",
                "event_source": Config.EXECUTION_HISTORY_SOURCE_POLICY["route_events"][0],
                "event_action": row_map.get("ExecType") or "FILL",
                "ExecType": row_map.get("ExecType"),
                "Broker": row_map.get("Broker"),
                "algo": row_map.get("algo"),
                "TraderName": row_map.get("TraderName"),
                "Exchange": row_map.get("Exchange"),
                "equ_ticker": row_map.get("equ_ticker"),
                "ccy_ticker": row_map.get("ccy_ticker"),
                "Side": row_map.get("Side"),
                "FillPrice": row_map.get("FillPrice"),
                "FillShares": row_map.get("FillShares"),
                "Amount": row_map.get("Amount"),
                "RouteShares": row_map.get("RouteShares"),
                "source_refreshed_at": refreshed_at,
                "refresh_strategy": Config.EXECUTION_HISTORY_REFRESH_POLICY["route_events"],
                "source_lineage": event_lineage,
            }
        )

    return (
        pd.DataFrame(route_records),
        pd.DataFrame(event_records),
    )

# -- Legacy: Excel -> raw_fills.db (kept for backward compatibility) --

def _extract_date_from_filename(filename: str) -> Optional[str]:
    """Extract YYYYMMDD date from filename like fills_20260408.xlsx."""
    if not filename:
        return None
    parts = Path(filename).stem.split("_")
    for p in parts:
        if p.isdigit() and len(p) == 8:
            return p
    return None

def ingest_excel_file(
    file_path: Path,
    db: Optional[RawFillsDB] = None,
) -> Dict[str, Any]:
    """Ingest a single FillFetch Excel file into raw_fills.db (legacy).

    .. deprecated::
        `ingest_excel_file()` is deprecated and will be removed in v2.0.
        Data must be ingested from Bloomberg API via `fill_fetch.py`, not from Excel.

    Steps:
        1. Read Excel -> List[Dict]
        2. Compute hash for duplicate detection
        3. Check ingestion_log for prior ingestion with same date + hash
        4. Clean via clean_emsx_fills()
        5. Upsert into raw_fills table
        6. Record in ingestion_log
    """
    warnings.warn(
        "ingest_excel_file() is deprecated and will be removed in v2.0. "
        "Data must be ingested from Bloomberg API via fill_fetch.py, not from Excel.",
        DeprecationWarning,
        stacklevel=2,
    )

    file_path = Path(file_path)
    result: Dict[str, Any] = {
        "file": str(file_path),
        "success": False,
        "skipped": False,
        "total_rows": 0,
        "new_rows": 0,
        "error": None,
    }

    if not file_path.exists():
        result["error"] = f"File not found: {file_path}"
        return result

    if db is None:
        db = DatabaseFacade().raw_db

    try:
        df_raw = pd.read_excel(file_path, engine="openpyxl")
        fills = df_raw.to_dict(orient="records")
        result["total_rows"] = len(fills)

        if not fills:
            result["success"] = True
            result["skipped"] = True
            logger.info(f"Empty file: {file_path.name}")
            return result

        hash_value = compute_data_hash(fills)
        source_date = _extract_date_from_filename(file_path.name)

        if source_date and db.check_ingestion_duplicate(source_date, hash_value):
            result["success"] = True
            result["skipped"] = True
            logger.info(f"Duplicate detected for {file_path.name} (date={source_date}), skipping")
            return result

        cleaned_df = clean_emsx_fills(fills)
        new_count = db.upsert_fills(cleaned_df)
        result["new_rows"] = new_count

        if source_date:
            db.add_ingestion_record(
                source_date=source_date,
                row_count=len(cleaned_df),
                new_row_count=new_count,
                hash_value=hash_value,
                source_file=file_path.name,
            )

        result["success"] = True
        logger.info(
            f"Ingested {file_path.name}: {len(cleaned_df)} rows "
            f"({new_count} new)"
        )

    except Exception as e:
        result["error"] = str(e)
        logger.error(f"Error ingesting {file_path.name}: {e}")

    return result

def ingest_all_excel_files(
    excel_dir: Optional[Path] = None,
    db: Optional[RawFillsDB] = None,
) -> List[Dict[str, Any]]:
    """Ingest all FillFetch Excel files from a directory (legacy).

    .. deprecated::
        `ingest_all_excel_files()` is deprecated and will be removed in v2.0.
        Data must be ingested from Bloomberg API via `fill_fetch.py`, not from Excel.
    """
    warnings.warn(
        "ingest_all_excel_files() is deprecated and will be removed in v2.0. "
        "Data must be ingested from Bloomberg API via fill_fetch.py, not from Excel.",
        DeprecationWarning,
        stacklevel=2,
    )

    if excel_dir is None:
        excel_dir = Path(Config.DATA_DIR)
    else:
        excel_dir = Path(excel_dir)

    if db is None:
        db = DatabaseFacade().raw_db

    if not excel_dir.exists():
        logger.warning(f"Excel directory not found: {excel_dir}")
        return []

    files = sorted(excel_dir.glob("fills_*.xlsx"))
    if not files:
        logger.info(f"No FillFetch Excel files found in {excel_dir}")
        return []

    results = []
    for file_path in files:
        result = ingest_excel_file(file_path, db)
        results.append(result)

    return results

# -- Active: raw_fills.db -> processed_fills.db --

def process_raw_fills_for_date(
    date_str: str,
    db: Optional[DatabaseFacade] = None,
    raw_db: Optional[SqliteRawFillReadRepository] = None,
    skip_if_processed: bool = True,
) -> Dict[str, Any]:
    """Read raw fills for date, clean+process, upsert to processed_fills.db.

    This is the LAYER 1 entry point of the processing pipeline.

    Args:
        date_str: YYYYMMDD date string.
        db: DatabaseFacade facade (or None to create default).
        raw_db: RawFillsDB instance (or None to use db.raw_db).
        skip_if_processed: If True, skip dates that already have processed data.

    Returns:
        Dict with keys: date, success, rows_read, rows_cleaned, rows_processed,
        error (if any).
    """
    if db is None:
        db = DatabaseFacade()
    if raw_db is None:
        raw_db = SqliteRawFillReadRepository()

    result: Dict[str, Any] = {
        "date": date_str,
        "success": False,
        "rows_read": 0,
        "rows_cleaned": 0,
        "rows_processed": 0,
        "error": None,
    }

    try:
        # Step 1: Read raw fills
        raw_fills = raw_db.get_fills_for_date(date_str)
        if raw_fills is None or raw_fills.empty:
            logger.info(f"No raw fills found for {date_str}")
            result["success"] = True
            return result

        result["rows_read"] = len(raw_fills)

        # Step 2: Clean
        cleaned = clean_emsx_fills(raw_fills)
        result["rows_cleaned"] = len(cleaned)

        if cleaned.empty:
            logger.warning(f"All fills filtered out during cleaning for {date_str}")
            result["success"] = True
            return result

        # Step 3: Process (enrich)
        processed = process_fills(cleaned)
        result["rows_processed"] = len(processed)

        # Step 3.5: S2 日期一致性校验
        # processed_fills 的 order_as_of_date 必须与输入 date_str 一致；
        # 不一致意味着时区转换或 source_date 解析存在 bug，必须阻止入库。
        if "order_as_of_date" in processed.columns and not processed.empty:
            mismatch_mask = processed["order_as_of_date"].astype(str) != date_str
            mismatch_count = int(mismatch_mask.sum())
            if mismatch_count > 0:
                mismatched_dates = processed.loc[mismatch_mask, "order_as_of_date"].unique().tolist()
                logger.error(
                    "%s: %d 行 order_as_of_date 与输入日期 %s 不一致 (实际: %s)",
                    date_str, mismatch_count, date_str, mismatched_dates[:10],
                )
                raise ValueError(
                    f"{date_str}: {mismatch_count} 行 order_as_of_date 与输入日期不一致"
                )

        # Step 4: Upsert to processed_fills.db
        logger.info("%s: 写入 %d 行至 processed_fills.db...", date_str, len(processed))
        print(f"[PROGRESS] {date_str}: writing {len(processed)} rows to processed_fills.db", flush=True)
        t0 = datetime.now()
        db.fills_write.upsert_processed_fills(processed)
        elapsed1 = (datetime.now() - t0).total_seconds()
        logger.info("%s: upsert_processed_fills 完成 (%.1fs)", date_str, elapsed1)
        print(f"[PROGRESS] {date_str}: processed_fills written ({len(processed)} rows, {elapsed1:.1f}s)", flush=True)

        t0 = datetime.now()
        # v2 修复: 在 upsert_route_registry 之前按 (OrderId, RouteId) groupby 计算 4 个 count_* 列
        # （ROUTE_REGISTRY_COLUMNS 中的 count_fill / count_broker / count_algo / count_trader）。
        # 原实现：upsert_route_registry(processed) 时 DataFrame 没有这 4 列，
        #         _upsert_fixed_schema 按 expected_columns 过滤后不写入 → DB 永远 NULL。
        # 修复后：assign 4 个 nunique 列到 processed 副本，_upsert 正常插入。
        processed_for_registry = processed.copy()
        if {"OrderId", "RouteId"}.issubset(processed_for_registry.columns):
            counts = (
                processed_for_registry.groupby(["OrderId", "RouteId"], dropna=False, sort=False)
                .agg(
                    count_fill=("FillId", lambda s: s.astype(str).nunique()),
                    count_broker=("Broker", lambda s: s.dropna().astype(str).nunique()),
                    count_algo=("algo", lambda s: s.dropna().astype(str).nunique()),
                    count_trader=("TraderName", lambda s: s.dropna().astype(str).nunique()),
                )
                .reset_index()
            )
            processed_for_registry = processed_for_registry.merge(
                counts, on=["OrderId", "RouteId"], how="left",
            )
        db.fills_write.upsert_route_registry(processed_for_registry)
        db.fills_write.mark_date_processed(
            date_str=date_str, stage="processed",
            row_count=len(processed),
        )
        elapsed2 = (datetime.now() - t0).total_seconds()
        logger.info("%s: route_registry 完成 (%.1fs)", date_str, elapsed2)

        # Populate execution history tables
        logger.info("%s: 构建执行历史记录...", date_str)
        print(f"[PROGRESS] {date_str}: building execution history", flush=True)
        t0 = datetime.now()
        # B4迁移后 route_registry 在 execution_history.db，无法跨库JOIN；
        # 直接从内存中的 processed DataFrame 提取 route 属性
        route_reg_df = processed[["OrderId", "RouteId", "equ_ticker", "ccy_ticker", "Side"]].drop_duplicates()
        # PR-1: order_history 是 route_history 的 VIEW，不再生成 order_df
        route_df, event_df = _build_execution_history_frames(processed, route_reg_df)
        db.fills_write.upsert_execution_history(route_df, event_df)
        elapsed3 = (datetime.now() - t0).total_seconds()
        logger.info("%s: 执行历史记录完成 (%.1fs)", date_str, elapsed3)
        print(f"[PROGRESS] {date_str}: execution history built ({elapsed3:.1f}s)", flush=True)

        result["success"] = True
        logger.info(
            f"Processed {date_str}: {len(processed)} rows "
            f"(from {len(raw_fills)} raw)"
        )

    except Exception as e:
        result["error"] = str(e)
        logger.error(f"Error processing {date_str}: {e}")

    return result
