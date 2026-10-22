"""盘中/收盘后时效探测（057 DL-05）——只读，交易机按清单运行。

为 DL-07（盘中作业 J1）/DL-08（收盘后 bar J2）提供额度与缓冲的实测输入：
1. 收盘后 bar 就绪度：按 DL-03 会话注册表各市场收盘时刻，探测 raw_bdib
   当日 bar（收盘后 15/30/60/120 分钟各跑一次）；
2. GetFills 当日可得性：processed_fills 当日最新成交时刻 vs 当前时刻；
3. 日更耗时与请求数：processing_log / fetch_log 只读统计 + quota_pause 命中。

用法（仓库根执行；建议收盘后按清单在 15/30/60/120 分钟各跑一次）：
    python scripts/ops/probe_intraday_freshness.py [--date YYYYMMDD] [--buffer 15]

退出码：0=探测完成（无论是否就绪——就绪度是数据不是判定）；2=数据源不可用。

实测状态约定（指南 §3.3）：本脚本输出的缓冲建议值标注「实测状态：待 DL-05
回填」——交易机实测数据回填 docs/report-data-inventory-2026-10.md 后方可
作为 DL-07/08 的预算依据。
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from data_access import ConnectionManager  # noqa: E402
from data_access.config import Config  # noqa: E402
from platform_data.contracts import SESSION_REGISTRY  # noqa: E402

logger = logging.getLogger(__name__)


def _top_ticker_per_exchange(mgr, trade_date: str) -> dict[str, str]:
    """bdib_daily_summary 当日每市场成交量最大的 1 个 ticker（点查代表）。"""
    import pandas as pd

    from platform_data.contracts.db_constants import BDIB_DAILY_SUMMARY_TABLE

    conn = mgr.get_connection("raw_bdib")
    try:
        frame = pd.read_sql_query(
            f"SELECT equ_ticker, total_volume FROM {BDIB_DAILY_SUMMARY_TABLE} WHERE trade_date = ?",
            conn.raw_connection,
            params=(trade_date,),
        )
    finally:
        conn.close()
    if frame.empty:
        return {}
    frame["_exchange"] = frame["equ_ticker"].astype(str).str.rsplit(" ", n=2).str[-2].str.upper()
    top = (
        frame.sort_values("total_volume", ascending=False)
        .groupby("_exchange", sort=False)
        .first()["equ_ticker"]
        .to_dict()
    )
    return {ex: str(t) for ex, t in top.items() if ex in SESSION_REGISTRY}


def probe_bars(mgr, trade_date: str, buffer_min: int) -> list[dict]:
    """各市场收盘后 bar 就绪度（代表 ticker 点查）。"""
    from platform_data.contracts.db_constants import RAW_BDIB_TABLE

    results: list[dict] = []
    top = _top_ticker_per_exchange(mgr, trade_date)
    conn = mgr.get_connection("raw_bdib")
    try:
        for exchange, session in sorted(SESSION_REGISTRY.items()):
            ticker = top.get(exchange)
            row = None
            if ticker:
                row = conn.execute(
                    f"SELECT COUNT(*), MIN(mkt_timestamp), MAX(mkt_timestamp) FROM {RAW_BDIB_TABLE} "
                    f"WHERE equ_ticker = ? AND order_as_of_date = ?",
                    (ticker, trade_date),
                ).fetchone()
            bar_count = int(row[0]) if row else 0
            results.append(
                {
                    "exchange": exchange,
                    "close": session.market_close,
                    "buffer_min": buffer_min,
                    "ticker": ticker,
                    "bar_count": bar_count,
                    "first_bar": row[1] if row else None,
                    "last_bar": row[2] if row else None,
                    "ready": bar_count > 0,
                }
            )
    finally:
        conn.close()
    return results


def probe_fills_delay(mgr, trade_date: str) -> list[dict]:
    """当日成交最新时刻 vs 当前时刻（GetFills 当日可得性代理）。"""
    conn = mgr.get_connection("processed_fills")
    try:
        rows = conn.execute(
            f"SELECT Exchange, MAX(exchange_exec_time) FROM {Config.PROCESSED_FILLS_TABLE} "
            f"WHERE order_as_of_date = ? GROUP BY Exchange",
            (trade_date,),
        ).fetchall()
    finally:
        conn.close()

    now = datetime.now()
    results: list[dict] = []
    for exchange, latest in rows:
        if not exchange or not latest:
            continue
        text = str(latest)
        try:
            hours = int(text[-8:-6])
            minutes = int(text[-5:-3])
            latest_dt = now.replace(hour=hours, minute=minutes, second=0, microsecond=0)
        except (TypeError, ValueError):
            continue
        results.append(
            {
                "exchange": str(exchange).upper(),
                "latest_fill": text,
                "lag_minutes": round((now - latest_dt).total_seconds() / 60, 1),
            }
        )
    return sorted(results, key=lambda r: r["exchange"])


def probe_pipeline_costs(mgr) -> dict:
    """日更耗时/请求数/quota 命中（processing_log + fetch_log 只读）。"""
    costs: dict = {"quota_pause_active": Path(Config.QUOTA_PAUSE_FILE).exists()}
    conn = mgr.get_connection("processed_fills")
    try:
        costs["processing_log_rows"] = int(
            conn.execute(f"SELECT COUNT(*) FROM {Config.PROCESSING_LOG_TABLE}").fetchone()[0]
        )
    except Exception as exc:  # 表缺失/库不可用不阻断其余探测
        costs["processing_log_error"] = str(exc)
    finally:
        conn.close()
    try:
        conn = mgr.get_connection("processed_fills")
        try:
            costs["fetch_log_rows"] = int(
                conn.execute(f"SELECT COUNT(*) FROM {Config.FETCH_LOG_TABLE}").fetchone()[0]
            )
        finally:
            conn.close()
    except Exception as exc:
        costs["fetch_log_error"] = str(exc)
    return costs


def main() -> int:
    parser = argparse.ArgumentParser(description="盘中/收盘后时效探测（057 DL-05）")
    parser.add_argument("--date", default="", help="目标交易日 YYYYMMDD（默认今日）")
    parser.add_argument("--buffer", type=int, default=15, help="收盘后缓冲分钟数（默认 15）")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    trade_date = args.date or date.today().strftime("%Y%m%d")

    try:
        mgr = ConnectionManager()
    except Exception as exc:
        logger.error("ConnectionManager 不可用: %s", exc)
        return 2

    bars = probe_bars(mgr, trade_date, args.buffer)
    ready = sum(1 for b in bars if b["ready"])
    logger.info("bar 就绪度：%d/%d 市场（trade_date=%s buffer=%dmin）", ready, len(bars), trade_date, args.buffer)
    for b in bars:
        logger.info(
            "  %s close=%s ready=%s bars=%d [%s..%s] ticker=%s",
            b["exchange"], b["close"], b["ready"], b["bar_count"], b["first_bar"], b["last_bar"], b["ticker"],
        )

    fills = probe_fills_delay(mgr, trade_date)
    logger.info("当日成交延迟（GetFills 可得性代理）：")
    for f in fills:
        logger.info("  %s latest=%s lag=%.1fmin", f["exchange"], f["latest_fill"], f["lag_minutes"])

    costs = probe_pipeline_costs(mgr)
    logger.info("管道成本基线：%s", costs)
    logger.info("实测状态：缓冲建议值待交易机四次探测（15/30/60/120）回填报告后方可作为 DL-07/08 预算依据")
    return 0


if __name__ == "__main__":
    sys.exit(main())
