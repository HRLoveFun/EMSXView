"""交易所会话注册表更新机制检查（057 DL-03，2026-10-21 用户补充要求）。

两个触发条件（对应两组检查）：
- 触发一 · 定期：月度运行（建议），检查注册表是否需要更新——
  覆盖完整性（白名单增减）、时区一致性、半日市年度覆盖、管道样本核对；
- 触发二 · 数据不一致：运行时检查——最近交易日成交记录（processed_fills）
  与市场数据（raw_bdib 抽样）是否落在注册表会话边界外。

用法：
    python scripts/ops/check_exchange_session_registry.py [--date YYYYMMDD] [--buffer 15]

    --date    检查的交易日（默认数据集中最近一个交易日）
    --buffer  会话边界缓冲分钟数（默认 15）

退出码：0=无需关注；1=存在待更新项（供计划任务告警接线）。

定期注册（月度，schtasks 示例；与 backup_ops_db.py 的「脚本+清单」模式一致，
不自动注册——部署时由用户决定）：
    schtasks /Create /TN "EMSXView-SessionRegistryCheck" /SC MONTHLY /D 1 /ST 07:00 ^
      /TR "python <repo-root>\\scripts\\ops\\check_exchange_session_registry.py"

更新流程（检查不通过时）：
    1. 人工核对交易所公告 / 管道技术文档（docs/EMSXDataPipeline-TECHNICAL_GUIDE.md）；
    2. 修订 SESSION_REGISTRY 并升 SESSION_REGISTRY_VERSION（契约同步变更）；
    3. 走 PR 合并（契约测试锁定）；若为管道侧口径变化，先更新管道文档再镜像（指南 §13）。
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

# ── 路径设置（脚本直接运行时需要仓库根）──
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from platform_data.adapters import ExchangeSessionAdapter  # noqa: E402
from platform_data.contracts import (  # noqa: E402
    EARLY_CLOSE_AUCTION_EXCHANGES,
    HALF_DAY_CLOSE_OVERRIDES,
    PIPELINE_CLOSING_AUCTION_SAMPLES,
    SESSION_REGISTRY,
    ExchangeSession,
)

logger = logging.getLogger(__name__)

# 成交/bar 落在会话边界外的占比阈值（超过即标记疑似时段变更）
OUT_OF_SESSION_RATIO_THRESHOLD = 0.005

_adapter = ExchangeSessionAdapter()


# ── 纯判定函数（单测覆盖；IO 组装在 main） ─────────────────────────────────────


def check_registry_coverage() -> list[str]:
    """触发一①：注册表覆盖 vs BDIB 白名单（白名单增减）。"""
    from data_access.config import Config

    registered = set(SESSION_REGISTRY)
    whitelist = set(Config.BDIB_EXCHANGE)
    problems: list[str] = []
    for missing in sorted(whitelist - registered):
        problems.append(f"白名单市场 {missing} 未在会话注册表中")
    for extra in sorted(registered - whitelist):
        problems.append(f"注册表市场 {extra} 不在 BDIB 白名单（白名单已变更？）")
    return problems


def check_timezone_consistency() -> list[str]:
    """触发一②：注册表 timezone 与 exchange_tz 映射一致（双源漂移）。"""
    from data_access.common.exchange_tz import EXCHANGE_TIMEZONE

    problems: list[str] = []
    for code, session in SESSION_REGISTRY.items():
        expected = EXCHANGE_TIMEZONE.get(code)
        if expected is None:
            problems.append(f"{code}: exchange_tz 无映射（注册表引用了未知时区源）")
        elif expected != session.timezone:
            problems.append(f"{code}: 注册表 timezone={session.timezone} 与 exchange_tz={expected} 不一致")
    return problems


def check_doc_samples() -> list[str]:
    """触发一③：管道 §5.5 明文样本（US/JP/HK 收盘竞价时刻）核对。"""
    problems: list[str] = []
    for code, expected in sorted(PIPELINE_CLOSING_AUCTION_SAMPLES.items()):
        session = SESSION_REGISTRY.get(code)
        if session is None:
            problems.append(f"{code}: 管道样本市场未在注册表中")
        elif session.closing_auction != expected:
            problems.append(f"{code}: 注册表收盘竞价 {session.closing_auction} 与管道样本 {expected} 不一致")
    for code in sorted(EARLY_CLOSE_AUCTION_EXCHANGES):
        session = SESSION_REGISTRY.get(code)
        if session is not None and not session.early_close_auction:
            problems.append(f"{code}: 管道 ADJUST 集合成员，注册表 early_close_auction=False")
    return problems


def check_half_day_coverage(today: date) -> list[str]:
    """触发一④：半日市静态条目是否覆盖当前年度与次年度（假日表年度轮换）。"""
    years_needed = {today.year, today.year + 1}
    years_present = {int(key[1][:4]) for key in HALF_DAY_CLOSE_OVERRIDES}
    missing = sorted(years_needed - years_present)
    if missing:
        return [f"半日市静态条目缺少年度 {missing}——按更新流程补充交易所日历后升版"]
    return []


def judge_out_of_session_ratio(out_count: int, total_count: int, threshold: float = OUT_OF_SESSION_RATIO_THRESHOLD) -> bool:
    """会话外成交占比是否超阈值（超=True）。total=0 不标记（缺数据 ≠ 不一致）。"""
    if total_count <= 0:
        return False
    return out_count / total_count > threshold


def judge_fills_bounds(
    session: ExchangeSession,
    first_local: str | None,
    last_local: str | None,
    buffer_min: int = 15,
) -> list[str]:
    """成交时间边界判定：首末本地时刻应落在 [开盘−buffer, 收盘+buffer] 内。"""
    if not first_local or not last_local:
        return []
    problems: list[str] = []
    lower = _hhmmss_to_minutes(session.market_open) - buffer_min
    upper = _hhmmss_to_minutes(session.market_close) + buffer_min
    first = _hhmmss_to_minutes(first_local)
    last = _hhmmss_to_minutes(last_local)
    if first is not None and first < lower:
        problems.append(f"最早成交 {first_local} 早于开盘 {session.market_open}（−{buffer_min}min 缓冲）")
    if last is not None and last > upper:
        problems.append(f"最晚成交 {last_local} 晚于收盘 {session.market_close}（+{buffer_min}min 缓冲）")
    return problems


def judge_bars_bounds(
    session: ExchangeSession,
    first_ts: str | None,
    last_ts: str | None,
    buffer_min: int = 15,
) -> list[str]:
    """bar 时间戳边界判定：首末 mkt_timestamp 应落在 [开盘−buffer, 收盘+buffer] 内。"""
    if not first_ts or not last_ts:
        return []
    problems: list[str] = []
    lower = _hhmmss_to_minutes(session.market_open) - buffer_min
    upper = _hhmmss_to_minutes(session.market_close) + buffer_min
    first = _hhmmss_to_minutes(_hms_of(first_ts))
    last = _hhmmss_to_minutes(_hms_of(last_ts))
    if first is not None and first < lower:
        problems.append(f"首根 bar {first_ts} 早于开盘 {session.market_open}（−{buffer_min}min 缓冲）")
    if last is not None and last > upper:
        problems.append(f"末根 bar {last_ts} 晚于收盘 {session.market_close}（+{buffer_min}min 缓冲）")
    return problems


def _hms_of(value: str) -> str:
    """从时间戳字符串提取 HH:MM:SS（兼容 'YYYY-MM-DD HH:MM:SS' 与 'HH:MM:SS'）。"""
    text = str(value).strip()
    if len(text) >= 8 and text[-8:-6].isdigit() and text[-8:-5].count(":") == 1:
        return text[-8:]
    return text


def _hhmmss_to_minutes(value: str | None) -> int | None:
    if value is None:
        return None
    parts = str(value).strip().split(":")
    if not parts or not parts[0].isdigit():
        return None
    hours = int(parts[0])
    minutes = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    return hours * 60 + minutes


# ── IO 组装（data_access 只读） ────────────────────────────────────────────────


def _latest_trade_date() -> str | None:
    """processed_fills 最近交易日（YYYYMMDD）。"""
    from data_access import ConnectionManager
    from data_access.config import Config

    conn = ConnectionManager().get_connection("processed_fills")
    try:
        row = conn.execute(
            f"SELECT MAX(order_as_of_date) FROM {Config.PROCESSED_FILLS_TABLE}"
        ).fetchone()
        return str(row[0]) if row and row[0] else None
    finally:
        conn.close()


def _fills_bounds_by_exchange(trade_date: str) -> dict[str, tuple[str | None, str | None, int]]:
    """每市场聚合：最早/最晚 exchange_exec_time 与成交笔数（单次 GROUP BY）。"""
    from data_access import ConnectionManager
    from data_access.config import Config

    conn = ConnectionManager().get_connection("processed_fills")
    try:
        rows = conn.execute(
            f"SELECT Exchange, MIN(exchange_exec_time), MAX(exchange_exec_time), COUNT(*) "
            f"FROM {Config.PROCESSED_FILLS_TABLE} WHERE order_as_of_date = ? GROUP BY Exchange",
            (trade_date,),
        ).fetchall()
        return {str(r[0]).upper(): (r[1], r[2], int(r[3])) for r in rows if r[0]}
    finally:
        conn.close()


def _fills_out_of_session_count(
    trade_date: str,
    exchange: str,
    lower_minutes: int,
    upper_minutes: int,
) -> tuple[int, int]:
    """单市场会话外成交计数（(区间外, 总数)）；用于 MIN/MAX 超界后的占比确认。

    exchange_exec_time 兼容 'HH:MM:SS' 与 'YYYY-MM-DD HH:MM:SS'（substr 负索引取尾 8 位）。
    """
    from data_access import ConnectionManager
    from data_access.config import Config

    minutes_expr = (
        "CAST(substr(exchange_exec_time, -8, 2) AS INTEGER) * 60 "
        "+ CAST(substr(exchange_exec_time, -5, 2) AS INTEGER)"
    )
    conn = ConnectionManager().get_connection("processed_fills")
    try:
        row = conn.execute(
            f"SELECT COUNT(*), "
            f"SUM(CASE WHEN ({minutes_expr}) < ? OR ({minutes_expr}) > ? THEN 1 ELSE 0 END) "
            f"FROM {Config.PROCESSED_FILLS_TABLE} "
            f"WHERE order_as_of_date = ? AND Exchange = ?",
            (lower_minutes, upper_minutes, trade_date, exchange),
        ).fetchone()
        total = int(row[0] or 0)
        out_count = int(row[1] or 0)
        return out_count, total
    finally:
        conn.close()


def _bars_bounds_samples(trade_date: str) -> dict[str, tuple[str | None, str | None]]:
    """每市场抽 1 个代表 ticker（bdib_daily_summary 当日成交量最大），点查 raw_bdib 首末 bar。

    bdib_daily_summary 为日更小表（~2000 行/日），全表拉取后按 equ_ticker 后缀分组；
    raw_bdib 点查走 (equ_ticker, order_as_of_date) 前导列，每市场 1 个 ticker·日。
    """
    import pandas as pd

    from data_access import ConnectionManager
    from data_access.config import Config
    from platform_data.contracts.db_constants import BDIB_DAILY_SUMMARY_TABLE, RAW_BDIB_TABLE

    mgr = ConnectionManager()
    summary_conn = mgr.get_connection("raw_bdib")
    try:
        summary = pd.read_sql_query(
            f"SELECT equ_ticker, total_volume FROM {BDIB_DAILY_SUMMARY_TABLE} WHERE trade_date = ?",
            summary_conn.raw_connection,
            params=(trade_date,),
        )
    finally:
        summary_conn.close()
    if summary.empty:
        return {}

    summary["_exchange"] = summary["equ_ticker"].astype(str).str.rsplit(" ", n=2).str[-2].str.upper()
    top_by_exchange = (
        summary.sort_values("total_volume", ascending=False)
        .groupby("_exchange", sort=False)
        .first()["equ_ticker"]
        .to_dict()
    )

    bounds: dict[str, tuple[str | None, str | None]] = {}
    for exchange, ticker in top_by_exchange.items():
        bars_conn = mgr.get_connection("raw_bdib")
        try:
            row = bars_conn.execute(
                f"SELECT MIN(mkt_timestamp), MAX(mkt_timestamp) FROM {RAW_BDIB_TABLE} "
                f"WHERE equ_ticker = ? AND order_as_of_date = ?",
                (ticker, trade_date),
            ).fetchone()
        finally:
            bars_conn.close()
        bounds[exchange] = (row[0] if row else None, row[1] if row else None)
    return bounds


def main() -> int:
    parser = argparse.ArgumentParser(description="交易所会话注册表更新机制检查（057 DL-03）")
    parser.add_argument("--date", default="", help="检查的交易日 YYYYMMDD（默认数据集中最近交易日）")
    parser.add_argument("--buffer", type=int, default=15, help="会话边界缓冲分钟数（默认 15）")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    problems: list[str] = []
    # 触发一：定期检查（不依赖数据集中交易日）
    problems += check_registry_coverage()
    problems += check_timezone_consistency()
    problems += check_doc_samples()
    problems += check_half_day_coverage(date.today())

    # 触发二：运行时一致性（读侧只读）
    trade_date = args.date or _latest_trade_date()
    if not trade_date:
        logger.warning("processed_fills 无交易日数据，跳过运行时一致性检查")
    else:
        logger.info("运行时一致性检查：trade_date=%s buffer=%dmin", trade_date, args.buffer)
        fills = _fills_bounds_by_exchange(trade_date)
        from data_access.config import Config

        whitelist = set(Config.BDIB_EXCHANGE)
        for code, (first, last, total) in sorted(fills.items()):
            session = _adapter.get_session(code)
            if session is None:
                # 白名单外市场（如 2026-07-16 移除的 BZ/CN/DC/MM）的历史成交仍在库，
                # 但已非分析范围（config 注释）——记 INFO 不报警；白名单内缺失才是真问题
                if code in whitelist:
                    problems.append(f"{code}: 白名单市场但无会话定义（注册表缺条目）")
                else:
                    logger.info("%s: 白名单外市场的历史成交，跳过", code)
                continue
            boundary_problems = judge_fills_bounds(session, first, last, args.buffer)
            if boundary_problems:
                # MIN/MAX 超界 ≠ 系统性时段变更：用占比阈值二次确认，防偶发错时间戳误报
                lower = _hhmmss_to_minutes(session.market_open) - args.buffer
                upper = _hhmmss_to_minutes(session.market_close) + args.buffer
                out_count, scoped_total = _fills_out_of_session_count(trade_date, code, lower, upper)
                if judge_out_of_session_ratio(out_count, scoped_total):
                    problems += [f"{code}: {p}（会话外 {out_count}/{scoped_total} 笔，超阈值）" for p in boundary_problems]
                else:
                    logger.info(
                        "%s: MIN/MAX 超界但会话外占比 %.4f%% 未超阈值，按偶发噪声跳过",
                        code,
                        (out_count / scoped_total * 100) if scoped_total else 0.0,
                    )
        try:
            bars = _bars_bounds_samples(trade_date)
        except Exception as exc:  # bar 点查失败不阻断其余检查（如库缺失）
            logger.warning("bar 边界抽样失败: %s", exc)
            bars = {}
        for code, (first, last) in sorted(bars.items()):
            session = _adapter.get_session(code)
            if session is None:
                continue
            problems += [f"{code}: {p}" for p in judge_bars_bounds(session, first, last, args.buffer)]

    if problems:
        logger.warning("发现 %d 项待更新/待关注：", len(problems))
        for item in problems:
            logger.warning("  - %s", item)
        logger.warning("更新流程见 docstring（核对公告/文档 → 修订注册表并升 SESSION_REGISTRY_VERSION → PR）")
        return 1

    logger.info("会话注册表检查通过：无需更新")
    return 0


if __name__ == "__main__":
    sys.exit(main())
