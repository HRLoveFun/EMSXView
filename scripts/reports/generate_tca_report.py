"""独立 TCA 可视化报告生成 CLI。

生成自包含静态 HTML（内联 CSS + 服务端 SVG 图表，零外部依赖），
浏览器直接打开或邮件分发均可。

时间范围二选一互斥（必须且只能一种，默认 last day）：
    --start YYYYMMDD --end YYYYMMDD   显式区间（start <= end）
    --last day|week|month|quarter|year  相对预设

用法：
    # 最近一个有数据的交易日（默认）
    python scripts/reports/generate_tca_report.py

    # 上周汇总
    python scripts/reports/generate_tca_report.py --last week

    # 显式区间 + 过滤
    python scripts/reports/generate_tca_report.py --start 20260701 --end 20260731 --exchange HK

    # 指标子集 + 自定义输出
    python scripts/reports/generate_tca_report.py --last month --metrics pnl_vwap,par_rate --output report.html
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# ── 路径设置（脚本直接运行时需要仓库根）──
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent.parent
for p in [_PROJECT_ROOT, _SCRIPT_DIR]:
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from CostView.src.monitoring import (  # noqa: E402
    LAST_PRESETS,
    BdibHealthService,
    TcaReportAggregator,
    fetch_latest_tca_date,
    render_report_html,
    resolve_time_range,
)

logger = logging.getLogger(__name__)

#: 默认输出目录
DEFAULT_OUTPUT_DIR = _SCRIPT_DIR / "output"


def generate_report(
    start: Optional[str] = None,
    end: Optional[str] = None,
    last: Optional[str] = None,
    *,
    metrics: Optional[list[str]] = None,
    broker: Optional[str] = None,
    algo: Optional[str] = None,
    symbol: Optional[str] = None,
    exchange: Optional[str] = None,
    output: Optional[Path] = None,
) -> Path:
    """生成 TCA 可视化报告 HTML，返回输出文件路径。

    Raises:
        ValueError: 时间范围互斥校验失败 / metrics 白名单外指标。
    """
    latest = fetch_latest_tca_date() if _needs_latest(start, end, last) else None
    tr = resolve_time_range(start, end, last, latest_data_date=latest)

    report = TcaReportAggregator().build_report(
        tr.start_date, tr.end_date,
        broker=broker, algo=algo, symbol=symbol, exchange=exchange,
        metrics=metrics,
    )
    health = _load_gap_health(tr.start_date, tr.end_date)

    out_path = output or _default_output_path(tr.start_date, tr.end_date, last)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    out_path.write_text(
        render_report_html(report, health, generated_at), encoding="utf-8",
    )
    logger.info("报告已生成: %s (%s ~ %s)", out_path, tr.start_date, tr.end_date)
    return out_path


def _needs_latest(start: Optional[str], end: Optional[str], last: Optional[str]) -> bool:
    """是否需要查询最近数据日期（last=day 或全默认时）。"""
    if start or end:
        return False
    return last in (None, "", "day")


def _load_gap_health(start_date: str, end_date: str) -> Optional[dict[str, Any]]:
    """加载 BDIB 健康数据作附录；失败降级为 None 不阻断报告。"""
    try:
        return BdibHealthService().get_health(start_date, end_date)
    except Exception as exc:
        logger.warning("BDIB 健康附录加载失败（跳过）: %s", exc)
        return None


def _default_output_path(start_date: str, end_date: str, last: Optional[str]) -> Path:
    """默认输出文件名：预设报告带预设名，显式区间带日期范围。"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if last and last in LAST_PRESETS and last != "day":
        return DEFAULT_OUTPUT_DIR / f"tca_{last}_{start_date}_{end_date}_{ts}.html"
    return DEFAULT_OUTPUT_DIR / f"tca_report_{start_date}_{end_date}_{ts}.html"


def _build_parser() -> argparse.ArgumentParser:
    """构建 CLI 参数解析器。"""
    parser = argparse.ArgumentParser(
        description="生成 tca_route_summary 独立 HTML 可视化报告",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--start", help="起始日期 YYYYMMDD（需与 --end 同用）")
    parser.add_argument("--end", help="截止日期 YYYYMMDD（需与 --start 同用）")
    parser.add_argument("--last", choices=LAST_PRESETS,
                        help="相对预设（与 --start/--end 互斥，默认 day）")
    parser.add_argument("--metrics", help="逗号分隔指标子集（默认全部 18 个）")
    parser.add_argument("--broker", help="券商过滤")
    parser.add_argument("--algo", help="算法类型过滤（VWAP/TWAP/POV 等）")
    parser.add_argument("--symbol", help="ticker 过滤")
    parser.add_argument("--exchange", help="市场/交易所过滤（US/HK/JP 等）")
    parser.add_argument("--output", type=Path, help="输出文件路径（默认 scripts/reports/output/）")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    """CLI 入口。校验失败退出码 2，运行失败退出码 1。"""
    # Windows 控制台默认 cp1252/GBK，输出中文前重配 UTF-8（失败则降级 replace）
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = _build_parser().parse_args(argv)
    metrics = [m.strip() for m in args.metrics.split(",") if m.strip()] if args.metrics else None
    try:
        out_path = generate_report(
            args.start, args.end, args.last,
            metrics=metrics, broker=args.broker, algo=args.algo,
            symbol=args.symbol, exchange=args.exchange, output=args.output,
        )
    except ValueError as exc:
        print(f"参数错误: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        logger.error("报告生成失败: %s", exc, exc_info=True)
        return 1
    print(f"报告已生成: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
