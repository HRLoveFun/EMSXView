"""用 raw_bdib 最后 bar 的 close 回填 bdib_daily_summary 缺失的 daily_close（优化 ⑥ 第二层）。

背景：bdib_daily_summary 在 20260302~20260417 的若干日期有行但 daily_close 为空，
导致 perm_impact_bps 无法计算。Bloomberg daily_history (PX_LAST) 未能落笔，
但 raw_bdib 日内 bars 完整，且 close 与 PX_LAST 同源。用当日最后 bar close 兜底，
与 tca_route_metrics._compute_close_price 的 fallback 逻辑一致。

范围：仅 _perm_impact_pending_s7.csv 中 pending 的 (equ_ticker, next_trade_date)。
幂等：仅更新 daily_close IS NULL 的行。
"""
from __future__ import annotations
import csv, sqlite3, sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))
from DataPipeline.config import Config  # noqa: E402

PENDING = Path(_ROOT) / "scripts" / "ops" / "_perm_impact_pending_s7.csv"
ROWS = list(csv.DictReader(open(PENDING, encoding="utf-8")))
NEED = sorted({(r["equ_ticker"], r["next_trade_date"])
               for r in ROWS if r["next_trade_date"] not in ("", "NO_NEXT_DATE")})
print(f"需回填 daily_close 的 (ticker, date) 组合: {len(NEED)}")

TBL = "bdib_daily_summary"
DB = str(Config.FILL_BDIB_DB)
RB = str(Config.RAW_BDIB_DB)

conn = sqlite3.connect(DB)
conn.execute("ATTACH DATABASE ? AS rb", (RB,))

# ── 建临时表装载待补清单 ──
conn.execute("DROP TABLE IF EXISTS _need")
conn.execute("CREATE TEMP TABLE _need (equ_ticker TEXT, trade_date TEXT)")
conn.executemany("INSERT INTO _need VALUES (?,?)", NEED)
print(f"_need 已写入 {len(NEED)} 行")

# ── 从 raw_bdib 取每个 (equ_ticker, date) 当日最后 bar 的 close ──
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
print(f"_lastclose 命中: {lc_cnt} / {len(NEED)}")

def q(tmpl, **kw):
    return tmpl.format(tbl=TBL, **kw)

# ── 回填 bdib_daily_summary（仅 daily_close IS NULL） ──
before = conn.execute(
    q("SELECT COUNT(*) FROM {tbl} bd "
      "WHERE bd.daily_close IS NULL "
      "AND EXISTS (SELECT 1 FROM _need n WHERE n.equ_ticker=bd.equ_ticker AND n.trade_date=bd.trade_date)")
).fetchone()[0]
conn.execute(
    q("UPDATE {tbl} "
      "SET daily_close = ("
      "  SELECT lc.close FROM _lastclose lc "
      "  WHERE lc.equ_ticker={tbl}.equ_ticker AND lc.trade_date={tbl}.trade_date"
      ") "
      "WHERE daily_close IS NULL "
      "AND EXISTS (SELECT 1 FROM _need n WHERE n.equ_ticker={tbl}.equ_ticker AND n.trade_date={tbl}.trade_date)")
)
conn.commit()
after = conn.execute(
    q("SELECT COUNT(*) FROM {tbl} bd "
      "WHERE bd.daily_close IS NULL "
      "AND EXISTS (SELECT 1 FROM _need n WHERE n.equ_ticker=bd.equ_ticker AND n.trade_date=bd.trade_date)")
).fetchone()[0]
print(f"daily_close 回填: {before} -> {after} (剩余仍 NULL)")

# cleanup
conn.execute("DROP TABLE IF EXISTS _need")
conn.execute("DROP TABLE IF EXISTS _lastclose")
conn.close()
