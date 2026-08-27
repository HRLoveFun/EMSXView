"""跨库行数守恒日检（M2.1, docs/spec/pipeline-resilience.md）。

按 ``order_as_of_date`` 对齐核心库行数，捕获「上游有数据、下游整日缺失」类事故
（A1：360 万行静默缺失于 processed_fills；A3：raw_bdib 停更整日）。

受检不变量（保守版，仅判「整日缺失」而非逐行相等，清洗/聚合减行属正常）：
- ``raw_fills`` 某日有行，但 ``processed_fills`` 同日 0 行 → 疑似 A1 类缺失
- ``raw_bdib`` 某日有行，但 ``fill_bdib`` 同日 0 行 → 疑似 A3 类缺失

该审计**仅告警不阻断**，写入 ``summary["conservation"]``；``per_date_counts``
可注入用于测试，生产路径实时查询各库。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from DataPipeline.config import Config
from DataPipeline.storage.connection import AccessTier, ConnectionManager

logger = logging.getLogger(__name__)

# (库键, 上游列) — 4 库均使用 order_as_of_date
_CONSERVATION_DBS = ("raw_fills", "processed_fills", "raw_bdib", "fill_bdib")


def build_conservation_counts() -> Dict[str, Dict[str, int]]:
    """实时查询 4 库各 ``order_as_of_date`` 行数，合并为 {date: {db: count}}。"""
    mgr = ConnectionManager()
    merged: Dict[str, Dict[str, int]] = {}
    for db_key in _CONSERVATION_DBS:
        try:
            if not mgr.database_exists(db_key):
                continue
            conn = mgr.get_connection(db_key, AccessTier.READ)
            try:
                rows = conn.execute(
                    f"SELECT [order_as_of_date], COUNT(*) FROM [{db_key}] "
                    f"WHERE [order_as_of_date] IS NOT NULL GROUP BY [order_as_of_date]"
                ).fetchall()
            finally:
                conn.close()
        except Exception as e:
            logger.warning("守恒审计跳过 %s: %s", db_key, e)
            continue
        for date_val, cnt in rows:
            d = str(date_val)
            merged.setdefault(d, {})[db_key] = int(cnt)
    return merged


def audit_conservation(per_date_counts: Optional[Dict[str, Dict[str, int]]] = None) -> dict:
    """比对跨库守恒，返回 {gaps, ok, checked_dates}。

    Args:
        per_date_counts: 注入 {date: {db_key: count}}（测试用）；为 None 时
            调用 ``build_conservation_counts`` 实时查询。
    """
    counts = per_date_counts if per_date_counts is not None else build_conservation_counts()
    gaps: list[dict] = []
    for date_val, c in counts.items():
        rf = c.get("raw_fills", 0)
        pf = c.get("processed_fills", 0)
        if rf > 0 and pf == 0:
            gaps.append({
                "date": date_val, "pair": "raw_fills->processed_fills",
                "raw_fills": rf, "processed_fills": pf,
            })
        rb = c.get("raw_bdib", 0)
        fb = c.get("fill_bdib", 0)
        if rb > 0 and fb == 0:
            gaps.append({
                "date": date_val, "pair": "raw_bdib->fill_bdib",
                "raw_bdib": rb, "fill_bdib": fb,
            })

    if gaps:
        logger.warning("跨库守恒审计发现 %d 处整日缺失: %s", len(gaps), gaps[:10])
    return {
        "gaps": gaps,
        "ok": not gaps,
        "checked_dates": len(counts),
    }
