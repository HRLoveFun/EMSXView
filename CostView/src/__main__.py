"""CostView CLI 入口 — 恢复 ``python -m CostView.src`` 查询用法。

此前 __main__.py 缺失，query_cli.py docstring 引用的入口全部失效（README
§4.2「入口失效」）。本模块用 argparse 包装 QueryEngine，为盘后巡检 / CI
提供只读查询命令。

用法（仓库根执行）：
    python -m CostView.src --query fills --date 20260408
    python -m CostView.src --query raw-fills --order-id 12345
    python -m CostView.src --query log --last 10
    python -m CostView.src --query summary --date 20260408
    python -m CostView.src --query tickers --ticker-type equ_ticker

退出码语义（区分"系统不可用"与"业务为空"，供 CI/巡检判定）：
    0 — 查询成功（空结果且未加 --fail-on-empty 亦为 0）
    2 — 数据源不可用（库文件缺失 / SQLite 错误）
    3 — 结果为空且指定 --fail-on-empty（CI 断言"必须有数据"）
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from typing import Any, Optional

from .query_cli import QueryEngine

logger = logging.getLogger(__name__)

_EXIT_OK = 0
_EXIT_DATA_UNAVAILABLE = 2
_EXIT_EMPTY_WITH_FAIL_FLAG = 3

_QUERIES = (
    "fills", "raw-fills", "log", "order-log", "orders", "tickers", "summary",
)


def _build_parser() -> argparse.ArgumentParser:
    """构建 CLI 参数解析器。"""
    parser = argparse.ArgumentParser(
        prog="python -m CostView.src",
        description="CostView 只读数据查询 CLI（raw_fills / processed_fills 巡检）",
    )
    parser.add_argument(
        "--query", required=True, choices=_QUERIES,
        help="查询类型",
    )
    parser.add_argument("--date", default=None, help="交易日 YYYYMMDD")
    parser.add_argument("--order-id", default=None, help="订单 ID 过滤")
    parser.add_argument("--ticker", default=None, help="ticker 过滤 (fills)")
    parser.add_argument("--ticker-type", default="all", help="ticker 类型 (tickers)")
    parser.add_argument("--limit", type=int, default=100, help="行数上限 (默认 100)")
    parser.add_argument("--offset", type=int, default=0, help="分页偏移")
    parser.add_argument("--last", type=int, default=10, help="最近 N 条日志 (log/order-log)")
    parser.add_argument(
        "--output", choices=["table", "json"], default="table",
        help="输出格式",
    )
    parser.add_argument(
        "--fail-on-empty", action="store_true",
        help="结果为空时以退出码 3 结束（CI/巡检断言用）",
    )
    return parser


def _frame_to_output(frame: Any, output: str) -> str:
    """DataFrame → table 字符串或 JSON 字符串。"""
    if output == "json":
        return frame.to_json(orient="records", force_ascii=False, indent=2)
    return frame.to_string(index=False)


def _rows_to_output(rows: list[dict[str, Any]], output: str) -> str:
    """dict 列表 → table 字符串或 JSON 字符串。"""
    if output == "json":
        return json.dumps(rows, ensure_ascii=False, indent=2, default=str)
    if not rows:
        return "(no rows)"
    return json.dumps(rows, ensure_ascii=False, indent=2, default=str)


def _run_query(engine: QueryEngine, args: argparse.Namespace) -> Any:
    """按 --query 分发到 QueryEngine 对应方法，返回原始结果。"""
    if args.query == "fills":
        return engine.query_fills(
            date=args.date, order_id=args.order_id, ticker=args.ticker,
            limit=args.limit, offset=args.offset,
        )
    if args.query == "raw-fills":
        return engine.query_raw_fills(
            date=args.date, order_id=args.order_id,
            limit=args.limit, offset=args.offset,
        )
    if args.query == "log":
        return engine.query_fetch_log(last=args.last)
    if args.query == "order-log":
        return engine.query_order_fetch_log(date=args.date, last=args.last)
    if args.query == "orders":
        return engine.query_orders(date=args.date)
    if args.query == "tickers":
        return engine.query_tickers(ticker_type=args.ticker_type)
    return engine.query_summary(date=args.date)


def _result_to_text(result: Any, output: str) -> str:
    """把查询结果统一序列化为输出文本。"""
    import pandas as pd
    if isinstance(result, pd.DataFrame):
        return _frame_to_output(result, output)
    if isinstance(result, dict):
        return json.dumps(result, ensure_ascii=False, indent=2, default=str)
    return _rows_to_output(list(result), output)


def _force_utf8_stdio() -> None:
    """Windows 控制台默认 cp1252/cp936，中文 help/结果会 UnicodeEncodeError。"""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except (OSError, ValueError):
                pass  # 管道/重定向场景可能不可重配，忽略


def main(argv: Optional[list[str]] = None) -> int:
    """CLI 主入口；返回进程退出码。"""
    _force_utf8_stdio()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    args = _build_parser().parse_args(argv)
    engine = QueryEngine()

    try:
        result = _run_query(engine, args)
    except FileNotFoundError as exc:
        # 数据源不可用 — 与"业务为空"在退出码上区分（P0 降级语义）
        print(f"[ERROR] data source unavailable: {exc}", file=sys.stderr)
        return _EXIT_DATA_UNAVAILABLE
    except sqlite3.OperationalError as exc:
        print(f"[ERROR] database error: {exc}", file=sys.stderr)
        return _EXIT_DATA_UNAVAILABLE

    text = _result_to_text(result, args.output)
    if not text.strip() or text.strip() == "(no rows)":
        print("[WARN] query returned no data", file=sys.stderr)
        if args.fail_on_empty:
            return _EXIT_EMPTY_WITH_FAIL_FLAG

    print(text)
    return _EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
