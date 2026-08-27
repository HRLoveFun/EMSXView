"""交易所白名单 ↔ 实际分布 diff 审计（M3.2, docs/spec/pipeline-resilience.md）。

对比 ``Config.BDIB_EXCHANGE``（BDIB 抓取白名单，单一真相源）与实际成交数据
（``processed_fills.Exchange`` 去重）的分布，识别：

- ``outside_whitelist``：数据中出现、但白名单遗漏的交易所 —— 这些交易所的 ticker
  永远不会被 BDIB 抓取，静默丢失行情（B1 事故：9 个交易所 424 个 ticker 因此长期
  缺失，原可由此审计提前发现）。
- ``whitelisted_no_data``：白名单配置但当前无成交数据的交易所（信息项，用于清理
  僵尸白名单条目，避免 B4 式永久容忍漂移）。

该审计**仅告警不阻断**（WARN 级）写入 ``summary["exchange_diff"]``，不计入
``terminal_failure``，避免误杀合法配置；但持续暴露漂移供人工闭环。
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Optional, Set

from DataPipeline.config import Config

logger = logging.getLogger(__name__)


def _distinct_exchanges_from_db(proc_db: str) -> Set[str]:
    """查询 processed_fills 实际成交交易所去重集合（大写）。"""
    from pathlib import Path

    db_path = Path(proc_db)
    if not db_path.exists():
        return set()
    conn = sqlite3.connect(str(db_path), timeout=30)
    try:
        rows = conn.execute(
            f"SELECT DISTINCT [Exchange] FROM [{Config.PROCESSED_FILLS_TABLE}] "
            f"WHERE [Exchange] IS NOT NULL AND TRIM([Exchange]) != ''"
        ).fetchall()
        return {str(r[0]).strip().upper() for r in rows if r[0]}
    finally:
        conn.close()


def audit_exchange_coverage(
    actual_exchanges: Optional[Set[str]] = None,
    proc_db: Optional[str] = None,
) -> dict:
    """对比白名单与实际交易所分布，返回 diff 字典。

    Args:
        actual_exchanges: 注入实际成交交易所集合（测试用）；为 None 时从
            ``proc_db``（默认 ``Config.PROCESSED_FILLS_DB``）实时查询。
        proc_db: processed_fills.db 路径（生产路径）。

    Returns:
        ``{"outside_whitelist": [...], "whitelisted_no_data": [...]}``
        均为大写交易所代码列表（排序）。
    """
    whitelist = {str(e).strip().upper() for e in Config.BDIB_EXCHANGE if str(e).strip()}
    if actual_exchanges is None:
        actual_exchanges = _distinct_exchanges_from_db(
            proc_db or str(Config.PROCESSED_FILLS_DB)
        )
    actual = {str(e).strip().upper() for e in actual_exchanges}

    outside = sorted(actual - whitelist)
    no_data = sorted(whitelist - actual)

    if outside:
        logger.warning(
            "交易所白名单漂移（M3.2）：数据中出现但白名单遗漏 %d 个交易所 %s "
            "—— 这些交易所 ticker 的 BDIB 行情将静默缺失，建议补全 BDIB_EXCHANGE",
            len(outside), outside,
        )
    return {"outside_whitelist": outside, "whitelisted_no_data": no_data}
