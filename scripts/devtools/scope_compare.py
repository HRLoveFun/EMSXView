"""诊断脚本：获取 EMSX Teams 列表 + TradingSystem/Team scope A/B 对比。

用法:
    python scripts/devtools/scope_compare.py --discover-teams
    python scripts/devtools/scope_compare.py --team "TeamName" --dates 2026-04-06 2026-04-07
"""
import argparse
import logging
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import blpapi
from DataPipeline.acquisition.bloomberg_fill_fetcher import BloombergFillFetcher

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

EMSX_API_SERVICE_BETA = "//blp/emapisvc_beta"
GET_TEAMS = "GetTeamsResponse"
ERROR_INFO = "ErrorInfo"


def discover_teams() -> List[str]:
    """直接发送 GetTeams 请求，打印原始响应以发现可用 team 名称。"""
    host = blpapi.SessionOptions().serverHost() if False else "localhost"
    opts = blpapi.SessionOptions()
    opts.setServerHost("localhost")
    opts.setServerPort(8194)
    session = blpapi.Session(opts)
    if not session.start():
        print("ERROR: 无法启动 Bloomberg session")
        return []
    print("Bloomberg session 已启动")
    if not session.openService(EMSX_API_SERVICE_BETA):
        print(f"ERROR: 无法打开 service {EMSX_API_SERVICE_BETA}")
        session.stop()
        return []
    print(f"Service {EMSX_API_SERVICE_BETA} 已打开")
    svc = session.getService(EMSX_API_SERVICE_BETA)
    request = svc.createRequest("GetTeams")
    session.sendRequest(request)
    teams: List[str] = []
    done = False
    while not done:
        event = session.nextEvent(10000)
        et = event.eventType()
        for msg in event:
            mt = msg.messageType()
            print(f"  [event={et}] messageType={mt}")
            if mt == GET_TEAMS:
                try:
                    teams_elem = msg.getElement("TEAMS")
                    for t in teams_elem.values():
                        teams.append(t.getValueAsString())
                except Exception as e:
                    print(f"  解析 TEAMS 失败: {e}")
                    # 打印整个消息结构
                    print(f"  消息内容: {msg}")
            elif mt == ERROR_INFO or "rror" in str(mt):
                # 安全地提取错误信息
                try:
                    elems = []
                    el = msg.asElement()
                    for i in range(el.numElements()):
                        sub = el.getElement(i)
                        elems.append(f"{sub.name()}={sub.getValueAsString()}")
                    print(f"  错误详情: {', '.join(elems)}")
                except Exception:
                    print(f"  原始消息: {msg}")
        if et == blpapi.Event.RESPONSE:
            done = True
    session.stop()
    print(f"\n发现 {len(teams)} 个 team: {teams}")
    return teams


def fetch_with_scope_raw(target_date: date, team: Optional[str] = None) -> tuple:
    """直接用 blpapi 拉取一天数据，捕获所有消息类型（含错误）。

    返回 (fills, messages_log)
    """
    start = datetime.combine(target_date, datetime.min.time())
    end = datetime.combine(target_date, datetime.max.time().replace(microsecond=0))
    scope_label = f"Team={team}" if team else "TradingSystem"
    print(f"  拉取 {target_date} ({scope_label})...")

    opts = blpapi.SessionOptions()
    opts.setServerHost("localhost")
    opts.setServerPort(8194)
    session = blpapi.Session(opts)
    if not session.start():
        return [], ["ERROR: 无法启动 session"]
    if not session.openService("//blp/emsx.history"):
        session.stop()
        return [], ["ERROR: 无法打开 emsx.history service"]

    svc = session.getService("//blp/emsx.history")
    request = svc.createRequest("GetFills")
    request.set("FromDateTime", start.strftime('%Y-%m-%dT%H:%M:%S.000+00:00'))
    request.set("ToDateTime", end.strftime('%Y-%m-%dT%H:%M:%S.000+00:00'))
    scope = request.getElement("Scope")
    if team:
        scope.setChoice("Team")
        scope.setElement("Team", team)
    else:
        scope.setChoice("TradingSystem")
        scope.setElement("TradingSystem", True)
    session.sendRequest(request)

    fills: List[Dict[str, Any]] = []
    msg_log: List[str] = []
    done = False
    while not done:
        try:
            event = session.nextEvent(30000)
        except Exception as e:
            msg_log.append(f"TIMEOUT: {e}")
            break
        et = event.eventType()
        for msg in event:
            mt = str(msg.messageType())
            if mt == "GetFillsResponse":
                try:
                    from DataPipeline.acquisition.bloomberg_fill_fetcher import _parse_fill_messages
                    fills.extend(_parse_fill_messages(msg))
                except Exception as e:
                    msg_log.append(f"PARSE_ERROR: {e}")
            elif "rror" in mt.lower() or "Error" in mt:
                # 捕获错误消息全部字段
                try:
                    el = msg.asElement()
                    fields = []
                    for i in range(el.numElements()):
                        sub = el.getElement(i)
                        fields.append(f"{sub.name()}={sub.getValueAsString()}")
                    msg_log.append(f"ERROR_MSG [{mt}]: {', '.join(fields)}")
                except Exception:
                    msg_log.append(f"ERROR_MSG [{mt}]: {msg}")
            else:
                msg_log.append(f"OTHER_MSG [{mt}]: {msg}")
        if et == blpapi.Event.RESPONSE:
            done = True

    session.stop()
    print(f"    -> {len(fills)} rows" + (f", messages: {msg_log}" if msg_log else ""))
    return fills, msg_log


def fetch_with_scope(client: BloombergFillFetcher, target_date: date,
                     team: Optional[str] = None) -> List[Dict[str, Any]]:
    """用指定 scope 拉取一天数据（不写 DB），兼容旧调用。"""
    fills, _ = fetch_with_scope_raw(target_date, team)
    return fills


def compare_fills(ts_fills: List[Dict[str, Any]], team_fills: List[Dict[str, Any]],
                  team_name: str, target_date: date) -> Dict[str, Any]:
    """对比两组 fills 数据。"""
    # OrderId 集合对比
    def get_order_ids(fills):
        return set(str(f.get("OrderId", "")) for f in fills if f.get("OrderId") is not None)

    ts_ids = get_order_ids(ts_fills)
    team_ids = get_order_ids(team_fills)

    # 主键对比（OrderId + FillNumber 或类似）
    def get_pk(f):
        oid = str(f.get("OrderId", ""))
        fn = str(f.get("FillNumber", f.get("fillNumber", "")))
        return f"{oid}-{fn}"

    ts_pks = set(get_pk(f) for f in ts_fills)
    team_pks = set(get_pk(f) for f in team_fills)

    # 关键字段 NULL 率
    key_cols = ["Account", "LastMarket", "exchange_exec_time", "order_as_of_date",
                "Liquidity", "Broker", "SecurityName", "Currency", "Ticker",
                "FillShares", "FillPrice", "Side"]

    def null_stats(fills, col):
        total = len(fills)
        if total == 0:
            return 0, 0, 0.0
        null_count = sum(1 for f in fills if f.get(col) is None or str(f.get(col, "")).strip() == "")
        return null_count, total, 100.0 * null_count / total

    result = {
        "date": str(target_date),
        "team_name": team_name,
        "ts_rows": len(ts_fills),
        "team_rows": len(team_fills),
        "ratio": len(ts_fills) / max(1, len(team_fills)),
        "ts_unique_orderids": len(ts_ids),
        "team_unique_orderids": len(team_ids),
        "orderid_intersection": len(ts_ids & team_ids),
        "team_orderid_subset_of_ts": team_ids.issubset(ts_ids),
        "ts_unique_pks": len(ts_pks),
        "team_unique_pks": len(team_pks),
        "pk_intersection": len(ts_pks & team_pks),
        "team_pk_subset_of_ts": team_pks.issubset(ts_pks),
        "ts_only_pks": len(ts_pks - team_pks),
        "team_only_pks": len(team_pks - ts_pks),
        "field_null_rates": {},
    }

    for col in key_cols:
        ts_null, ts_total, ts_pct = null_stats(ts_fills, col)
        team_null, team_total, team_pct = null_stats(team_fills, col)
        result["field_null_rates"][col] = {
            "ts": f"{ts_null}/{ts_total} ({ts_pct:.1f}%)",
            "team": f"{team_null}/{team_total} ({team_pct:.1f}%)",
        }

    # 字段值差异检查（对交集 PK 行）
    common_pks = ts_pks & team_pks
    if common_pks:
        ts_map = {get_pk(f): f for f in ts_fills}
        team_map = {get_pk(f): f for f in team_fills}
        diff_fields: Dict[str, int] = {}
        for pk in common_pks:
            ts_f = ts_map.get(pk, {})
            team_f = team_map.get(pk, {})
            for col in key_cols:
                tv = str(ts_f.get(col, "")).strip()
                ev = str(team_f.get(col, "")).strip()
                if tv != ev:
                    diff_fields[col] = diff_fields.get(col, 0) + 1
        result["common_pks"] = len(common_pks)
        result["field_diffs_in_common"] = {k: v for k, v in sorted(diff_fields.items(), key=lambda x: -x[1])}

    return result


def run_comparison(team_name: str, dates: List[str]):
    """运行完整 A/B 对比。"""
    target_dates = [datetime.strptime(d, "%Y-%m-%d").date() for d in dates]
    print(f"\n{'='*70}")
    print(f"Scope A/B 对比: TradingSystem vs Team={team_name}")
    print(f"日期: {dates}")
    print(f"{'='*70}\n")

    results = []
    for td in target_dates:
        print(f"\n--- {td} ---")
        ts_fills, ts_msgs = fetch_with_scope_raw(td, team=None)
        team_fills, team_msgs = fetch_with_scope_raw(td, team=team_name)
        cmp = compare_fills(ts_fills, team_fills, team_name, td)
        cmp["ts_messages"] = ts_msgs
        cmp["team_messages"] = team_msgs
        results.append(cmp)
        _print_result(cmp)

    _print_summary(results)
    # 保存报告
    report_path = PROJECT_ROOT / "docs" / "archive" / "2026-07-02" / "scope_ab_comparison.md"
    _save_report(results, team_name, report_path)
    print(f"\n报告已保存: {report_path}")


def _print_result(r: Dict[str, Any]):
    print(f"\n  === {r['date']} 对比结果 ===")
    print(f"  TradingSystem rows: {r['ts_rows']}")
    print(f"  Team rows:          {r['team_rows']}")
    print(f"  倍率 (TS/Team):     {r['ratio']:.2f}x")
    print(f"  OrderId 交集:       {r['orderid_intersection']} (TS={r['ts_unique_orderids']}, Team={r['team_unique_orderids']})")
    print(f"  Team OrderId ⊆ TS:  {r['team_orderid_subset_of_ts']}")
    print(f"  PK 交集:            {r['pk_intersection']} (TS={r['ts_unique_pks']}, Team={r['team_unique_pks']})")
    print(f"  Team PK ⊆ TS:       {r['team_pk_subset_of_ts']}")
    print(f"  TS-only PKs:        {r['ts_only_pks']}")
    print(f"  Team-only PKs:      {r['team_only_pks']}")
    if r.get("common_pks"):
        print(f"  共同 PK 行数:       {r['common_pks']}")
        if r.get("field_diffs_in_common"):
            print(f"  共同行字段差异:")
            for col, cnt in r["field_diffs_in_common"].items():
                print(f"    {col}: {cnt}/{r['common_pks']} 行不同")
        else:
            print(f"  共同行字段差异:     无（完全一致）")
    print(f"  字段 NULL 率:")
    for col, stats in r["field_null_rates"].items():
        print(f"    {col:25s} TS={stats['ts']:20s}  Team={stats['team']}")


def _print_summary(results: List[Dict[str, Any]]):
    print(f"\n{'='*70}")
    print("汇总")
    print(f"{'='*70}")
    for r in results:
        print(f"  {r['date']}: TS={r['ts_rows']:>7d}  Team={r['team_rows']:>7d}  "
              f"倍率={r['ratio']:.2f}x  Team⊆TS={r['team_pk_subset_of_ts']}")


def _save_report(results: List[Dict[str, Any]], team_name: str, path: Path):
    lines = [
        "# Scope A/B 对比报告: TradingSystem vs Team",
        f"\n**Team**: `{team_name}`",
        f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## 汇总",
        "",
        "| 日期 | TradingSystem | Team | 倍率 | Team ⊆ TS |",
        "|------|--------------|------|------|-----------|",
    ]
    for r in results:
        lines.append(f"| {r['date']} | {r['ts_rows']} | {r['team_rows']} | {r['ratio']:.2f}x | {r['team_pk_subset_of_ts']} |")
    lines.append("")
    for r in results:
        lines.append(f"## {r['date']}")
        lines.append("")
        lines.append(f"- TradingSystem rows: **{r['ts_rows']}**")
        lines.append(f"- Team rows: **{r['team_rows']}**")
        lines.append(f"- 倍率: **{r['ratio']:.2f}x**")
        lines.append(f"- OrderId 交集: {r['orderid_intersection']} (TS={r['ts_unique_orderids']}, Team={r['team_unique_orderids']})")
        lines.append(f"- Team OrderId ⊆ TS: **{r['team_orderid_subset_of_ts']}**")
        lines.append(f"- PK 交集: {r['pk_intersection']}")
        lines.append(f"- Team PK ⊆ TS: **{r['team_pk_subset_of_ts']}**")
        lines.append(f"- TS-only PKs: {r['ts_only_pks']}")
        lines.append(f"- Team-only PKs: {r['team_only_pks']}")
        if r.get("common_pks"):
            lines.append(f"- 共同 PK 行数: {r['common_pks']}")
            if r.get("field_diffs_in_common"):
                lines.append("- 共同行字段差异:")
                for col, cnt in r["field_diffs_in_common"].items():
                    lines.append(f"  - `{col}`: {cnt}/{r['common_pks']} 行不同")
            else:
                lines.append("- 共同行字段差异: **无（完全一致）**")
        lines.append("")
        lines.append("### 字段 NULL 率对比")
        lines.append("")
        lines.append("| 字段 | TradingSystem | Team |")
        lines.append("|------|--------------|------|")
        for col, stats in r["field_null_rates"].items():
            lines.append(f"| {col} | {stats['ts']} | {stats['team']} |")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="EMSX Scope A/B 对比工具")
    parser.add_argument("--discover-teams", action="store_true", help="发现可用 EMSX teams")
    parser.add_argument("--team", type=str, help="Team 名称（Team scope 拉取用）")
    parser.add_argument("--dates", nargs="+", default=["2026-04-06", "2026-04-07"],
                        help="要对比的 source date 列表 (YYYY-MM-DD)")
    args = parser.parse_args()

    if args.discover_teams:
        discover_teams()
        return

    if not args.team:
        print("ERROR: 需要 --team 参数或先运行 --discover-teams 发现 team 名称")
        parser.print_help()
        return

    run_comparison(args.team, args.dates)


if __name__ == "__main__":
    main()
