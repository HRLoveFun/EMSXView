"""报告筛选维度值持久化服务 — tca_report_dims 维度表维护与读取。

背景：Report 的筛选下拉（市场 / Broker / Algo / Symbol）此前每次请求都按
时间范围对 tca_route_summary 明细表执行 GROUP BY 去重查询（大表扫描 + 随
时间范围变化）。本服务把四类维度值抽取为持久化列表：

    tca_report_dims        — dim_type(值类别) × value 唯一，累计出现次数
                             （occurrences，用于下拉排序与截断）
    tca_report_dims_meta   — 增量刷新水位（last_processed_date）

刷新策略（daily_update 管线后自动执行，亦可 CLI 手动触发）：
    - 增量：仅扫描 order_as_of_date > 水位 的新增交易日，UPSERT 新值；
    - 全量：--full 清空重建，保证与源表一致（首次部署或数据回填后使用）。

查询策略（report_aggregator 使用）：维度表可用时直接读取（与时间范围、
其他过滤完全解耦，稳定且快）；不可用（未刷新/表不存在）时由调用方回退
原时间范围查询，保证向后兼容。
"""

from __future__ import annotations

import argparse
import logging
from typing import Any, Optional

from DataPipeline.config import Config, DB_FILL_BDIB
from DataPipeline.storage.connection import AccessTier, ConnectionManager

logger = logging.getLogger(__name__)

#: dim_type → tca_route_summary 源列名（列名大小写不敏感）
DIM_COLUMNS: dict[str, str] = {
    "exchange": "Exchange",
    "broker": "Broker",
    "algo": "algo",
    "symbol": "equ_ticker",
}

#: 下拉输出键 → (dim_type, 截断上限；0 = 不截断)
_OPTION_SPECS: list[tuple[str, str, int]] = [
    ("brokers", "broker", 100),
    ("algos", "algo", 50),
    ("symbols", "symbol", 200),
    ("exchanges", "exchange", 0),
]

#: 水位初始值（增量扫描起点）；全量重建亦从该值开始
_EPOCH_DATE = "00000000"


# ═══════════════════════════════════════════════════════════════════════════
# Schema
# ═══════════════════════════════════════════════════════════════════════════


def ensure_schema(conn) -> None:
    """确保维度表与水位表存在（幂等；WRITE 连接可执行 CREATE）。"""
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {Config.TCA_REPORT_DIMS_TABLE} (
            dim_type TEXT NOT NULL,
            value TEXT NOT NULL,
            first_seen_date TEXT NOT NULL,
            last_seen_date TEXT NOT NULL,
            occurrences INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (dim_type, value)
        )
    """)
    conn.execute(f"""
        CREATE INDEX IF NOT EXISTS idx_report_dims_type
        ON {Config.TCA_REPORT_DIMS_TABLE} (dim_type, occurrences DESC)
    """)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {Config.TCA_REPORT_DIMS_META_TABLE} (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)


# ═══════════════════════════════════════════════════════════════════════════
# 刷新（抽取 → UPSERT）
# ═══════════════════════════════════════════════════════════════════════════


def refresh_dim_values(
    mgr: Optional[ConnectionManager] = None,
    *,
    full: bool = False,
) -> dict[str, Any]:
    """从 tca_route_summary 增量（默认）/全量（full=True）刷新维度值列表。

    Args:
        mgr: 连接管理器；None 时新建（默认数据库路径）。
        full: True 时清空维度表后全量重建（首次部署/历史回填后使用）。

    Returns:
        统计字典：refreshed / reason（源表缺失时）/ watermark / processed。
        源表不存在时不抛异常，返回 refreshed=False（调用方非阻塞处理）。
    """
    mgr = mgr or ConnectionManager()
    write = mgr.get_connection(DB_FILL_BDIB, AccessTier.WRITE)
    try:
        ensure_schema(write)
        if not _source_table_exists(write):
            return {"refreshed": False, "reason": "tca_route_summary 不存在"}
        if full:
            _clear_dims(mgr)
        watermark = _EPOCH_DATE if full else _read_watermark(write)
        processed: dict[str, int] = {}
        max_date = watermark
        for dim_type, column in DIM_COLUMNS.items():
            rows = _scan_source(write, column, watermark)
            processed[dim_type] = _upsert_dim(write, dim_type, rows)
            batch_max = max((d for _, d, _ in rows), default="")
            if batch_max and batch_max > max_date:
                max_date = batch_max
        _write_watermark(write, max_date)
        write.commit()
        _checkpoint(write)
        logger.info(
            "维度值刷新完成: %s (watermark=%s, %s)",
            "full" if full else "incremental", max_date, processed,
        )
        return {"refreshed": True, "watermark": max_date, "processed": processed}
    finally:
        write.close()


def _source_table_exists(conn) -> bool:
    """tca_route_summary 表是否存在。"""
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ? LIMIT 1",
        [Config.TCA_ROUTE_SUMMARY_TABLE],
    ).fetchone()
    return row is not None


def _clear_dims(mgr: ConnectionManager) -> None:
    """清空维度表（维护操作，走 admin 连接以绕过 WRITE 层的 DELETE 拦截）。"""
    admin = mgr.get_admin_connection(DB_FILL_BDIB)
    try:
        admin.execute(f"DELETE FROM {Config.TCA_REPORT_DIMS_TABLE}")
        admin.commit()
    finally:
        admin.close()


def _read_watermark(conn) -> str:
    """读取增量处理水位；meta 表/记录缺失时返回初始水位。"""
    try:
        row = conn.execute(
            f"SELECT value FROM {Config.TCA_REPORT_DIMS_META_TABLE} "
            "WHERE key = 'last_processed_date'",
        ).fetchone()
    except Exception:
        return _EPOCH_DATE
    return str(row[0]) if row else _EPOCH_DATE


def _write_watermark(conn, watermark: str) -> None:
    """更新增量处理水位。"""
    conn.execute(
        f"INSERT INTO {Config.TCA_REPORT_DIMS_META_TABLE} (key, value) "
        "VALUES ('last_processed_date', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        [watermark],
    )


def _scan_source(conn, column: str, watermark: str) -> list[tuple[str, str, int]]:
    """扫描源表中 > 水位 的路由，按 (维度值, 交易日) 聚合并去重。

    返回 [(value, order_as_of_date, route_count), ...]；NULL 归为 '(unknown)'
    （与既有 filter_options/markets 的 COALESCE 口径一致）。
    """
    sql = f"""
        SELECT COALESCE({column}, '(unknown)') AS v, order_as_of_date, COUNT(*) AS n
        FROM {Config.TCA_ROUTE_SUMMARY_TABLE}
        WHERE order_as_of_date > ?
        GROUP BY {column}, order_as_of_date
    """
    return [
        (str(r[0]), str(r[1]), int(r[2]))
        for r in conn.execute(sql, [watermark]).fetchall()
    ]


def _upsert_dim(conn, dim_type: str, rows: list[tuple[str, str, int]]) -> int:
    """批量 UPSERT 维度值：新值写入首见日期，存量累加次数并推进末见日期。"""
    sql = f"""
        INSERT INTO {Config.TCA_REPORT_DIMS_TABLE}
            (dim_type, value, first_seen_date, last_seen_date, occurrences)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(dim_type, value) DO UPDATE SET
            last_seen_date = MAX(tca_report_dims.last_seen_date, excluded.last_seen_date),
            occurrences = tca_report_dims.occurrences + excluded.occurrences
    """
    params = [
        (dim_type, value, seen_date, seen_date, count)
        for value, seen_date, count in rows
    ]
    if not params:
        return 0
    conn.executemany(sql, params)
    return len(params)


def _checkpoint(conn) -> None:
    """WAL checkpoint：确保刷新后的数据对后续只读连接立即可见（失败不阻断）。"""
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception as exc:
        logger.warning("维度表 WAL checkpoint 失败（忽略）: %s", exc)


# ═══════════════════════════════════════════════════════════════════════════
# 读取（下拉选项）
# ═══════════════════════════════════════════════════════════════════════════


def get_filter_options(
    mgr: Optional[ConnectionManager] = None,
    *,
    conn: Optional[Any] = None,
) -> Optional[dict[str, list[str]]]:
    """从维度表读取全量下拉选项（时间无关）。

    返回 {brokers, algos, symbols, exchanges}，各按累计次数降序、值升序，
    并按配置上限截断（exchanges 不截断）。维度表不可用（不存在/为空）时
    返回 None，调用方回退原时间范围查询。

    Args:
        mgr: 连接管理器（conn 为 None 时用于新建连接）。
        conn: 外部传入的 fill_bdib READ 连接（复用调用方连接，不管理其
            生命周期——避免关闭 ConnectionManager 线程级缓存连接）。
    """
    owns_conn = conn is None
    if conn is None:
        mgr = mgr or ConnectionManager()
        conn = mgr.get_connection(DB_FILL_BDIB, AccessTier.READ)
    try:
        if not _dims_table_ready(conn):
            return None
        result: dict[str, list[str]] = {}
        for key, dim_type, limit in _OPTION_SPECS:
            sql = (
                f"SELECT value FROM {Config.TCA_REPORT_DIMS_TABLE} "
                "WHERE dim_type = ? ORDER BY occurrences DESC, value ASC"
            )
            params: list[Any] = [dim_type]
            if limit:
                sql += " LIMIT ?"
                params.append(limit)
            result[key] = [str(r[0]) for r in conn.execute(sql, params).fetchall()]
        return result
    finally:
        if owns_conn:
            conn.close()


def _dims_table_ready(conn) -> bool:
    """维度表存在且非空（空表视为未初始化，由调用方回退）。"""
    try:
        row = conn.execute(
            f"SELECT 1 FROM {Config.TCA_REPORT_DIMS_TABLE} LIMIT 1",
        ).fetchone()
    except Exception:
        return False
    return row is not None


# ═══════════════════════════════════════════════════════════════════════════
# CLI（手动刷新入口）
# ═══════════════════════════════════════════════════════════════════════════


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="刷新 Report 筛选维度持久化列表（tca_report_dims）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python -m CostView.src.monitoring.report_dims --refresh   # 增量刷新（默认）\n"
            "  python -m CostView.src.monitoring.report_dims --full      # 全量重建\n"
        ),
    )
    parser.add_argument("--refresh", action="store_true", help="增量刷新（默认行为）")
    parser.add_argument("--full", action="store_true", help="清空后全量重建")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    """CLI 入口。"""
    # Windows 控制台默认 cp1252/GBK，输出中文前重配 UTF-8（失败则降级 replace）
    import sys

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    args = _build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    result = refresh_dim_values(full=args.full)
    if not result.get("refreshed"):
        logger.warning("维度值刷新跳过: %s", result.get("reason", "未知原因"))
        return 0
    processed = result.get("processed", {})
    print(
        f"维度值刷新完成（{result.get('watermark')}）: "
        + ", ".join(f"{k}={v}" for k, v in processed.items())
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
