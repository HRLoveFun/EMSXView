r"""报告筛选维度值读取（只读） — tca_report_dims 维度表读取。

010-extract-pipeline：维度表的**刷新（写侧）已随数据管道迁独立项目
EMSXDataPipeline**（scripts/report_dims.py）。本仓库仅保留读取侧
``get_filter_options``，供 report_aggregator / CostView API 拉取筛选下拉值。

读取策略：维度表可用时直接读取（与时间范围、其他过滤完全解耦，稳定且快）；
不可用（未刷新 / 表不存在 / fill_bdib.db 缺失）时返回 None，由调用方回退
原时间范围查询，保证向后兼容（009 mode=ro 下缺失库亦返回 None）。
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from data_access.config import Config, DB_FILL_BDIB
from data_access.storage.connection import AccessTier, ConnectionManager

logger = logging.getLogger(__name__)

#: 下拉输出键 → (dim_type, 截断上限；0 = 不截断)
_OPTION_SPECS: list[tuple[str, str, int]] = [
    ("brokers", "broker", 100),
    ("algos", "algo", 50),
    ("symbols", "symbol", 200),
    ("exchanges", "exchange", 0),
]


def get_filter_options(
    mgr: Optional[ConnectionManager] = None,
    *,
    conn: Optional[Any] = None,
) -> Optional[dict[str, list[str]]]:
    """从维度表读取全量下拉选项（时间无关）。

    返回 {brokers, algos, symbols, exchanges}，各按累计次数降序、值升序，
    并按配置上限截断（exchanges 不截断）。维度表不可用（不存在/为空/fill_bdib
    缺失）时返回 None，调用方回退原时间范围查询。

    Args:
        mgr: 连接管理器（conn 为 None 时用于新建连接）。
        conn: 外部传入的 fill_bdib READ 连接（复用调用方连接，不管理其
            生命周期——避免关闭 ConnectionManager 线程级缓存连接）。
    """
    owns_conn = conn is None
    if conn is None:
        mgr = mgr or ConnectionManager()
        try:
            conn = mgr.get_connection(DB_FILL_BDIB, AccessTier.READ)
        except FileNotFoundError:
            # 只读模式下 fill_bdib.db 缺失 → 维度表不可用，调用方回退（009）
            return None
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
