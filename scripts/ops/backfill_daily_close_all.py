"""全量回填 bdib_daily_summary 缺失的 daily_close（用 raw_bdib 当日最后 bar close）。

背景：bdib_daily_summary 在 34 个日期（20260302~20260420）共 29,948 行
daily_close 为空（Bloomberg daily_history / PX_LAST 未能落笔）。
raw_bdib 日内 bars 完整且 close 同源，用当日最后 bar close 兜底，
与 tca_route_metrics._compute_close_price 的 fallback 逻辑一致。

仅填充当前 daily_close IS NULL 且 raw_bdib 有对应 bars 的行。
"""
from __future__ import annotations
import sqlite3, sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))
from DataPipeline.config import Config  # noqa: E402

DB = str(Config.FILL_BDIB_DB)
RB = str(Config.RAW_BDIB_DB)
TBL = "bdib_daily_summary"

conn = sqlite3.connect(DB)
conn.execute("ATTACH DATABASE ? AS rb", (RB,))

# ── 待补清单：bdib_daily_summary 中 daily_close IS NULL 的 (equ_ticker, trade_date) ──
conn.execute("DROP TABLE IF EXISTS _need")
conn.execute("CREATE TEMP TABLE _need AS SELECT equ_ticker, trade_date FROM {} WHERE daily_close IS NULL".format(TBL))
need_cnt = conn.execute("SELECT COUNT(*) FROM _need").fetchone()[0]
print(f"_need: {need_cnt} 行")

# ── raw_bdib 每个 (equ_ticker, date) 最后 bar 的 close ──
conn.execute("DROP TABLE IF EXISTS _lastclose")
conn.execute(
    "CREATE TEMP TABLE _lastclose AS "
    "SELECT r.equ_ticker, r.order_as_of_date AS trade_date, r.close "
    "FROM raw_bdib r "
    "INNER JOIN _need n ON r.equ_ticker = n.equ_ticker AND r.order_as_of_date = n.trade_date "
    "WHERE r.mkt_timestamp = ("
    "  SELECT MAX(r2.mkt_timestamp) FROM raw_bdib r2 "
    "  WHERE r2.equ_ticker = r.equ_ticker AND r2.order_as_of_date = r.order_as_of_date"
    ")"
)
lc_cnt = conn.execute("SELECT COUNT(*) FROM _lastclose").fetchone()[0]
print(f"_lastclose 命中: {lc_cnt} / {need_cnt}")

# ── 回填（仅 daily_close IS NULL） ──
def q(t):
    return t.format(tbl=TBL)
before = conn.execute(q("SELECT COUNT(*) FROM {tbl} WHERE daily_close IS NULL")).fetchone()[0]
conn.execute(q(
    "UPDATE {tbl} SET daily_close = ("
    "  SELECT lc.close FROM _lastclose lc "
    "  WHERE lc.equ_ticker={tbl}.equ_ticker AND lc.trade_date={tbl}.trade_date"
    ") "
    "WHERE daily_close IS NULL "
    "AND EXISTS (SELECT 1 FROM _need n WHERE n.equ_ticker={tbl}.equ_ticker AND n.trade_date={tbl}.trade_date)"
))
conn.commit()
after = conn.execute(q("SELECT COUNT(*) FROM {tbl} WHERE daily_close IS NULL")).fetchone()[0]
print(f"daily_close 回填: {before} -> {after} (剩余仍 NULL)")

conn.execute("DROP TABLE IF EXISTS _need")
conn.execute("DROP TABLE IF EXISTS _lastclose")
conn.close()
