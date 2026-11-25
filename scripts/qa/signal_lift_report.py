"""信号与规则月度回检 CLI（057 DL-26/221）。

只读聚合 `tca_route_summary`，按规则输出：
每个告警信号的命中 vs 未命中标准化成本差（按日 z、按规模分层、OrderId 聚类 CI）。

用法：
    python scripts/qa/signal_lift_report.py
    python scripts/qa/signal_lift_report.py --month 202611
    python scripts/qa/signal_lift_report.py --start 20261101 --end 20261130 \
        --rules rules.json --cost-field pnl_vwap

输出：`logs/qa/signal_lift/signal_lift_<start>_<end>.json`，并打印可执行信号摘要。

默认区间为**上一个完整自然月**；`--db` 缺省读 `Config.FILL_BDIB_DB`。
"""

from __future__ import annotations

import argparse
import calendar
import json
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _previous_month(today: date) -> tuple[str, str]:
    last_prev = today.replace(day=1) - timedelta(days=1)
    return last_prev.replace(day=1).strftime("%Y%m%d"), last_prev.strftime("%Y%m%d")


def _month_bounds(month: str) -> tuple[str, str]:
    year, mon = int(month[:4]), int(month[4:6])
    last_day = calendar.monthrange(year, mon)[1]
    return f"{year:04d}{mon:02d}01", f"{year:04d}{mon:02d}{last_day:02d}"


def _resolve_period(args: argparse.Namespace) -> tuple[str, str]:
    if args.month:
        if args.start or args.end:
            raise ValueError("--month 与 --start/--end 不能同时使用")
        return _month_bounds(args.month)
    if args.start and args.end:
        return args.start, args.end
    if args.start or args.end:
        raise ValueError("--start 与 --end 必须同时提供（或改用 --month）")
    return _previous_month(date.today())


def _load_rows(db_path: str, start: str, end: str) -> list[dict]:
    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError(f"fill_bdib 不存在: {path}")
    uri = f"file:{path.as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view') "
            "AND name='tca_route_summary'"
        ).fetchone()
        if table is None:
            raise RuntimeError("tca_route_summary 不存在（TCA 汇总尚未生成）")
        cursor = connection.execute(
            "SELECT * FROM tca_route_summary WHERE order_as_of_date BETWEEN ? AND ?",
            (start, end),
        )
        return [dict(row) for row in cursor]
    finally:
        connection.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Signal/rule monthly lift (057 DL-26/221)")
    parser.add_argument("--month", default="", help="YYYYMM（上一个完整月之外的显式区间）")
    parser.add_argument("--start", default="", help="YYYYMMDD")
    parser.add_argument("--end", default="", help="YYYYMMDD")
    parser.add_argument("--db", default="", help="fill_bdib.db（默认 Config.FILL_BDIB_DB）")
    parser.add_argument(
        "--cost-field", default="arrival_cost_bps",
        help="成本列（arrival_cost_bps / pnl_vwap / close_cost_bps / wagner_is_bps）",
    )
    parser.add_argument("--rules", default="", help="阈值规则 JSON（与异常阈值 API 同 payload）")
    parser.add_argument(
        "--out-dir", default=str(_REPO_ROOT / "logs" / "qa" / "signal_lift"),
    )
    parser.add_argument("--size-buckets", type=int, default=5)
    parser.add_argument("--min-stratum-sample", type=int, default=3)
    parser.add_argument("--bootstrap", type=int, default=300)
    parser.add_argument("--seed", type=int, default=2601)
    args = parser.parse_args(argv)

    try:
        start, end = _resolve_period(args)
    except ValueError as exc:
        print(f"signal lift: {exc}", file=sys.stderr)
        return 2

    db_path = args.db
    if not db_path:
        from data_access.config import Config

        db_path = str(Config.FILL_BDIB_DB)

    rules_payload = None
    if args.rules:
        try:
            rules_payload = json.loads(Path(args.rules).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"signal lift: 规则文件读取失败: {exc}", file=sys.stderr)
            return 2

    try:
        rows = _load_rows(db_path, start, end)
    except (OSError, RuntimeError, sqlite3.Error) as exc:
        print(f"signal lift: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    from CostView.src.evaluation.signal_lift import (
        monthly_signal_lift,
        render_summary,
    )

    report = monthly_signal_lift(
        rows,
        cost_field=args.cost_field,
        rules_payload=rules_payload,
        size_buckets=args.size_buckets,
        min_stratum_sample=args.min_stratum_sample,
        bootstrap=args.bootstrap,
        seed=args.seed,
    )
    report["period"] = {"start": start, "end": end}
    report["source"] = {
        "db": str(db_path),
        "generated_by": "scripts/qa/signal_lift_report.py",
    }

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"signal_lift_{start}_{end}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    sample = report.get("sample") or {}
    print(
        "signal lift {start}-{end}: routes={routes} usable={usable} "
        "orders={orders} day_std={day_std} rules={fingerprint} -> {path}".format(
            start=start,
            end=end,
            routes=sample.get("routes"),
            usable=sample.get("usable"),
            orders=sample.get("orders"),
            day_std=sample.get("day_standardized"),
            fingerprint=(report.get("rules") or {}).get("fingerprint"),
            path=path,
        )
    )
    summary = render_summary(report)
    if summary:
        print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
