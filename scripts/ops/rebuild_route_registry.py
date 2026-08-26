"""重建 route_registry（L2：根治 ccy_ticker 缺失）。

背景（2026-08-25，KS 市场 16.74B 数量级问题根因链）：
- route_registry 表为空（0 行），导致 S3 列补全失败 →
  agg_fills_10s 的 Ticker/Side/Currency/ccy_ticker 缺失（20260408/20260805/20260824）→
  fill_bdib 集成阶段按 (order_as_of_date, ccy_ticker) merge fx_rates 失败 →
  tca_route_summary.fx_rate 全 NULL → 报告 USD 金额按 1.0 兜底虚高 3 个数量级。

本脚本从原始真相源重建：
- 路由清单：processed_fills DISTINCT (OrderId, RouteId, equ_ticker, Exchange)
- 静态属性：raw_fills 按 (OrderId, RouteId) 聚合多数 Currency / Side / 计数
  （已核查：路由级 Currency 100% 一致，无跨路由冲突）
- ccy_ticker = "USD" + Currency + " Curncy"（USD 恒为 "USD Curncy"）

用法：
    python scripts/ops/rebuild_route_registry.py --dry-run
    python scripts/ops/rebuild_route_registry.py
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from pathlib import Path
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("rebuild_route_registry")

_SCRIPT_DIR = Path(__file__).resolve().parent
_ROOT = _SCRIPT_DIR.parent.parent
sys.path.insert(0, str(_ROOT))

from DataPipeline.config import Config  # noqa: E402


def _ccy_to_ticker(ccy: str) -> Optional[str]:
    """Currency → ccy_ticker（"USD" → "USD Curncy"，其余 → "USD{ccy} Curncy"）。"""
    c = (ccy or "").strip().upper()
    if not c:
        return None
    return "USD Curncy" if c == "USD" else f"USD{c} Curncy"


def _collect_route_ccy(pf: sqlite3.Connection) -> dict[tuple[str, str], str]:
    """从 raw_fills 按 (OrderId, RouteId) 多数 Currency 推导 ccy_ticker。"""
    rows = pf.execute(
        "SELECT OrderId, RouteId, Currency, COUNT(*) AS n FROM raw_fills "
        "WHERE Currency IS NOT NULL AND TRIM(Currency) != '' "
        "GROUP BY OrderId, RouteId, Currency"
    ).fetchall()
    # 多数币种（同路由出现多币种时取出现次数最多者）
    best: dict[tuple[str, str], tuple[int, str]] = {}
    for oid, rid, ccy, n in rows:
        key = (str(oid), str(rid))
        cur_n, cur_ccy = best.get(key, (0, ""))
        if n > cur_n:
            best[key] = (n, str(ccy))
    result: dict[tuple[str, str], str] = {}
    for key, (_, ccy) in best.items():
        ticker = _ccy_to_ticker(ccy)
        if ticker:
            result[key] = ticker
    return result


def _collect_route_stats(pf: sqlite3.Connection) -> dict[tuple[str, str], dict[str, object]]:
    """从 raw_fills 聚合 (OrderId, RouteId) 级 Side 多数与计数。"""
    rows = pf.execute(
        "SELECT OrderId, RouteId, Side, "
        "COUNT(DISTINCT FillId) AS count_fill, "
        "COUNT(DISTINCT Broker) AS count_broker, "
        "COUNT(DISTINCT StrategyType) AS count_algo, "
        "COUNT(DISTINCT TraderName) AS count_trader "
        "FROM raw_fills GROUP BY OrderId, RouteId"
    ).fetchall()
    result: dict[tuple[str, str], dict[str, object]] = {}
    for oid, rid, side, c_fill, c_broker, c_algo, c_trader in rows:
        result[(str(oid), str(rid))] = {
            "Side": str(side) if side else None,
            "count_fill": int(c_fill or 0),
            "count_broker": int(c_broker or 0),
            "count_algo": int(c_algo or 0),
            "count_trader": int(c_trader or 0),
        }
    return result


def _collect_route_list(pf: sqlite3.Connection) -> list[dict[str, str]]:
    """processed_fills DISTINCT 路由清单（含 equ_ticker / Exchange）。"""
    rows = pf.execute(
        "SELECT DISTINCT OrderId, RouteId, equ_ticker, Exchange FROM processed_fills"
    ).fetchall()
    return [
        {
            "OrderId": str(r[0]), "RouteId": str(r[1]),
            "equ_ticker": str(r[2]) if r[2] else None,
            "Exchange": str(r[3]) if r[3] else None,
        }
        for r in rows
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="重建 route_registry")
    parser.add_argument("--dry-run", action="store_true", help="仅预览不写入")
    args = parser.parse_args()

    pf_path = Config.PROCESSED_FILLS_DB
    rf_path = Config.RAW_FILLS_DB
    conn = sqlite3.connect(str(pf_path))
    try:
        # 确保表结构存在
        from DataPipeline.storage.schema.inline_ddl import init_processed_fills_schema
        init_processed_fills_schema(conn)

        logger.info("收集路由清单（processed_fills DISTINCT）...")
        routes = _collect_route_list(conn)
        logger.info("路由数: %d", len(routes))
        if not routes:
            logger.error("processed_fills 无路由，终止")
            return 1

        logger.info("聚合 raw_fills 币种映射（%s）...", rf_path)
        raw_conn = sqlite3.connect(str(rf_path))
        try:
            ccy_map = _collect_route_ccy(raw_conn)
            logger.info("有币种的路由: %d / %d", len(ccy_map), len(routes))
            logger.info("聚合 raw_fills 统计...")
            stats_map = _collect_route_stats(raw_conn)
        finally:
            raw_conn.close()

        if args.dry_run:
            missing_ccy = [r for r in routes if (r["OrderId"], r["RouteId"]) not in ccy_map]
            logger.info(
                "DRY-RUN: 将重建 %d 条路由，其中 %d 条无币种（保持 ccy_ticker NULL）",
                len(routes), len(missing_ccy),
            )
            return 0

        # 组装并写入
        from DataPipeline.storage.repositories.fills import SqliteFillWriteRepository
        import pandas as pd

        records = []
        for r in routes:
            key = (r["OrderId"], r["RouteId"])
            stats = stats_map.get(key, {})
            records.append({
                "OrderId": r["OrderId"], "RouteId": r["RouteId"],
                "equ_ticker": r["equ_ticker"], "Exchange": r["Exchange"],
                "ccy_ticker": ccy_map.get(key),
                "Side": stats.get("Side"),
                "count_fill": stats.get("count_fill", 0),
                "count_broker": stats.get("count_broker", 0),
                "count_algo": stats.get("count_algo", 0),
                "count_trader": stats.get("count_trader", 0),
            })
        df = pd.DataFrame(records)
        from DataPipeline.storage.connection import ConnectionManager
        cm = ConnectionManager(path_overrides={"processed_fills": pf_path})
        written = SqliteFillWriteRepository(cm).upsert_route_registry(df)
        logger.info("route_registry 写入完成: %d 条", written)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
