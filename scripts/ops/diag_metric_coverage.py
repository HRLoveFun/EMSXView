"""一次性诊断脚本：测量 tca_route_summary 各字段覆盖率，并初步归因 NULL 原因。"""
from __future__ import annotations
import sqlite3
from pathlib import Path

DB = Path("CostView/data/fill_bdib.db")

METRICS = [
    "fill_count", "fill", "fill_continuous", "fill_close",
    "par_rate", "par_rate_continuous", "par_rate_close",
    "p_avg", "p_avg_continuous",
    "pnl_vwap", "pnl_vwap_continuous",
    "RPM", "RPM_continuous",
    "pwp_5", "pwp_10", "pwp_15", "pwp_20", "pwp_25",
    "p_arrival", "p_close", "arrival_cost_bps", "close_cost_bps",
    "opportunity_cost",
    "p_decision", "delay_cost", "trading_cost", "wagner_is", "wagner_is_bps",
    "cost_stddev", "cost_p95", "cost_cvar",
    "order_duration_sec", "exec_rate_shares_per_min",
    "temp_impact_5min_bps", "temp_impact_10min_bps", "temp_impact_30min_bps",
    "perm_impact_bps", "recovery_truncated",
    "fx_rate",
]

# 依赖 BDIB 日内行情的指标
BDIB = {
    "par_rate", "par_rate_continuous", "par_rate_close", "pnl_vwap", "pnl_vwap_continuous",
    "p_arrival", "p_close", "arrival_cost_bps", "close_cost_bps", "opportunity_cost",
    "p_decision", "delay_cost", "trading_cost", "wagner_is", "wagner_is_bps",
    "temp_impact_5min_bps", "temp_impact_10min_bps", "temp_impact_30min_bps", "perm_impact_bps",
}
# 依赖次日 daily_close
NEXT_DAY = {"perm_impact_bps"}
# 需 >=2 笔成交
MULTI_FILL = {"cost_stddev", "cost_p95", "cost_cvar", "order_duration_sec", "exec_rate_shares_per_min"}
# PWP 需达到量阈值，小单可能永不命中
PWP = {"pwp_5", "pwp_10", "pwp_15", "pwp_20", "pwp_25"}
# 依赖 side
SIDE = {"RPM", "RPM_continuous"}
# 依赖 fx 回填
FX = {"fx_rate"}


def main() -> None:
    c = sqlite3.connect(str(DB))
    total = c.execute("SELECT COUNT(*) FROM tca_route_summary").fetchone()[0]
    if total == 0:
        print("tca_route_summary 为空")
        return
    print(f"总路由数: {total}\n")
    print(f"{'字段':<28}{'NULL数':>10}{'覆盖率%':>10}  依赖/原因类别")
    print("-" * 80)
    for m in METRICS:
        nn = c.execute(f"SELECT COUNT(*) FROM tca_route_summary WHERE {m} IS NOT NULL").fetchone()[0]
        nulls = total - nn
        pct = round(nn / total * 100, 2)
        cats = []
        if m in FX:
            cats.append("fx回填")
        elif m in NEXT_DAY:
            cats.append("次日daily_close")
        elif m in MULTI_FILL:
            cats.append(">=2笔成交")
        elif m in PWP:
            cats.append("BDIB+量阈值")
        elif m in SIDE:
            cats.append("side方向")
        elif m in BDIB:
            cats.append("BDIB日内行情")
        else:
            cats.append("源值/fill")
        flag = " <--" if pct < 100 else ""
        print(f"{m:<28}{nulls:>10}{pct:>10}  {','.join(cats)}{flag}")
    c.close()


if __name__ == "__main__":
    main()
