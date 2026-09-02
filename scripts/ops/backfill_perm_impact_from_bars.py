"""直接用 raw_bdib 次日最后 bar close 重算 perm_impact_bps（优化 ⑥ 兜底层）。

背景：bdib_daily_summary 对部分路由的次日没有整行（仅 NULL daily_close 已补完），
导致基于 bdib_daily_summary 的回填无法命中。此处对 perm_impact_bps IS NULL
且 p_arrival IS NOT NULL 的路由，若 raw_bdib 存在次日 bars，
以次日最后 bar close 作为 next_close 直接重算：

    perm_impact_bps = (next_close / p_arrival - 1) * side_sign * 10000

不依赖 bdib_daily_summary 行存在性。
"""
from __future__ import annotations
import sqlite3, sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))
from DataPipeline.config import Config  # noqa: E402

DB = str(Config.FILL_BDIB_DB)
RB = str(Config.RAW_BDIB_DB)
TBL = "tca_route_summary"

conn = sqlite3.connect(DB)
conn.execute("ATTACH DATABASE ? AS rb", (RB,))

# ── 构建 (equ_ticker, next_date, next_close) 临时表 ──
conn.execute("DROP TABLE IF EXISTS _need_next")
conn.execute("CREATE TEMP TABLE _need_next AS "
    "SELECT DISTINCT t.equ_ticker, t.order_as_of_date AS order_date "
    "FROM {tbl} t "
    "WHERE t.perm_impact_bps IS NULL AND t.p_arrival IS NOT NULL".format(tbl=TBL))
print("_need_next:", conn.execute("SELECT COUNT(*) FROM _need_next").fetchone()[0], "routes")

conn.execute("DROP TABLE IF EXISTS _nextclose")
conn.execute(
    "CREATE TEMP TABLE _nextclose AS "
    "SELECT r.equ_ticker, r.order_as_of_date AS next_date, r.close AS next_close "
    "FROM raw_bdib r "
    "INNER JOIN _need_next n ON r.equ_ticker = n.equ_ticker AND r.order_as_of_date > n.order_date "
    "WHERE r.mkt_timestamp = ("
    "  SELECT MAX(r2.mkt_timestamp) FROM raw_bdib r2 "
    "  WHERE r2.equ_ticker = r.equ_ticker AND r2.order_as_of_date = r.order_as_of_date"
    ")"
)
nc_cnt = conn.execute("SELECT COUNT(*) FROM _nextclose").fetchone()[0]
print("_nextclose hit:", nc_cnt)

# ── 回填 perm_impact ──
def q(t):
    return t.format(tbl=TBL)
before = conn.execute(q("SELECT COUNT(*) FROM {tbl} WHERE perm_impact_bps IS NULL")).fetchone()[0]
conn.execute(q(
    "UPDATE {tbl} "
    "SET perm_impact_bps = (nc.next_close / {tbl}.p_arrival - 1.0) "
    "    * CASE WHEN {tbl}.Side = 'B' THEN -1 "
    "           WHEN {tbl}.Side = 'S' THEN 1 ELSE 0 END "
    "    * 10000.0 "
    "FROM _nextclose nc "
    "WHERE {tbl}.perm_impact_bps IS NULL "
    "  AND {tbl}.p_arrival IS NOT NULL "
    "  AND nc.equ_ticker = {tbl}.equ_ticker "
    "  AND nc.next_date = ("
    "    SELECT MIN(r.order_as_of_date) FROM raw_bdib r "
    "    WHERE r.equ_ticker = {tbl}.equ_ticker AND r.order_as_of_date > {tbl}.order_as_of_date"
    "  )"
))
conn.commit()
after = conn.execute(q("SELECT COUNT(*) FROM {tbl} WHERE perm_impact_bps IS NULL")).fetchone()[0]
print("perm_impact 回填 (from bars): {} -> {}".format(before, after))

conn.execute("DROP TABLE IF EXISTS _need_next")
conn.execute("DROP TABLE IF EXISTS _nextclose")
conn.close()
