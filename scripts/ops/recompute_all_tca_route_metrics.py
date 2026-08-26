"""全量重算 tca_route_summary（L4b，一天一存 + 断点续跑版）。

复用 ComputeRouteMetricsStage（与 recompute_route_metrics.py 相同核心），
从 fill_bdib 全部日期循环 force 重算。设计要点：
- 一天一存：每算完一天即 INSERT OR REPLACE 落库（execute 内部逐日提交），
  中途中断已算日期不丢失，无需从头再来。
- 断点续跑：重新启动时跳过已完成日期，判据双保险：
  ① checkpoint 文件（_tca_recompute_done.txt）记录的成功日期；
  ② tca_route_summary 该日行数 == fill_bdib 该日 DISTINCT 路由数。
  某天算到一半崩溃时行数必然不齐，不会被误判为完成。
- 逐日日志 + 累计统计 + --limit 分批验证。

用法：
    # 全量（后台）：python scripts/ops/recompute_all_tca_route_metrics.py
    # 仅跑前 10 天（验证）：... --limit 10
    # 强制全部重算（忽略已完成）：... --all
    # 指定日期：... --dates 20260805 20260820
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("recompute_all_tca")

_SCRIPT_DIR = Path(__file__).resolve().parent
_ROOT = _SCRIPT_DIR.parent.parent
sys.path.insert(0, str(_ROOT))

from DataPipeline.config import Config  # noqa: E402
from DataPipeline.orchestration.context import PipelineContext  # noqa: E402
from DataPipeline.orchestration.stages_process import ComputeRouteMetricsStage  # noqa: E402


def _all_dates() -> list[str]:
    conn = sqlite3.connect(str(Config.FILL_BDIB_DB))
    try:
        rows = conn.execute(
            f"SELECT DISTINCT order_as_of_date FROM {Config.FILL_BDIB_TABLE} "
            "ORDER BY order_as_of_date"
        ).fetchall()
        return [str(r[0]) for r in rows]
    finally:
        conn.close()


_CHECKPOINT = _SCRIPT_DIR / "_tca_recompute_done.txt"


def _fx_ready_ratio(date_str: str) -> float:
    """tca_route_summary 中该日 fx_rate 非空比例（0~1）；表不存在/无数据返回 -1。"""
    conn = sqlite3.connect(str(Config.FILL_BDIB_DB))
    try:
        try:
            row = conn.execute(
                f"SELECT COUNT(*), SUM(CASE WHEN fx_rate IS NOT NULL THEN 1 ELSE 0 END) "
                f"FROM {Config.TCA_ROUTE_SUMMARY_TABLE} WHERE order_as_of_date = ?",
                (date_str,),
            ).fetchone()
        except sqlite3.OperationalError:
            return -1.0
        if not row or row[0] == 0:
            return -1.0
        return (row[1] or 0) / row[0]
    finally:
        conn.close()


def _date_is_complete(date_str: str) -> bool:
    """该日是否已完整重算。

    判据：tca_route_summary 该日行数 == fill_bdib 该日 DISTINCT 路由数。
    行数一致说明该日已完整落库（INSERT OR REPLACE 全量写入后逐日提交），
    比 fx_rate 非空率更可靠 —— 某天算到一半崩溃时行数必然不齐，不会误判完成。
    """
    conn = sqlite3.connect(str(Config.FILL_BDIB_DB))
    try:
        try:
            tca = conn.execute(
                f"SELECT COUNT(*) FROM {Config.TCA_ROUTE_SUMMARY_TABLE} WHERE order_as_of_date = ?",
                (date_str,),
            ).fetchone()[0]
            src = conn.execute(
                f"SELECT COUNT(DISTINCT OrderId || '|' || RouteId) FROM {Config.FILL_BDIB_TABLE} "
                "WHERE order_as_of_date = ?",
                (date_str,),
            ).fetchone()[0]
        except sqlite3.OperationalError:
            return False
        return src > 0 and tca >= src
    finally:
        conn.close()


def _load_done_set() -> set[str]:
    """读取 checkpoint 已完成日期集合。"""
    if not _CHECKPOINT.exists():
        return set()
    return {
        line.strip() for line in _CHECKPOINT.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def _mark_done(date_str: str) -> None:
    """追加写入 checkpoint（日期成功算完即落盘，支持断点续跑）。"""
    with open(_CHECKPOINT, "a", encoding="utf-8") as f:
        f.write(f"{date_str}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="全量重算 tca_route_summary")
    parser.add_argument("--limit", type=int, default=0, help="仅处理前 N 个日期（0=全部）")
    parser.add_argument("--all", action="store_true", help="忽略已完成日期，全部重算")
    parser.add_argument("--dates", nargs="+", default=None, help="显式指定日期")
    args = parser.parse_args()

    if args.dates:
        dates = [d for d in args.dates if d]
    else:
        dates = _all_dates()
    # 断点续跑：跳过已完成日期（checkpoint 记录 或 行数与源一致）
    if not args.all and not args.dates:
        done = _load_done_set()
        pending = [
            d for d in dates
            if d not in done and not _date_is_complete(d)
        ]
        logger.info("已完成 %d 个日期，待处理 %d 个", len(dates) - len(pending), len(pending))
        dates = pending
    if not dates:
        logger.info("无待处理日期")
        return 0
    if args.limit > 0:
        dates = dates[: args.limit]
        logger.info("limit=%d：本次仅处理 %d 个日期", args.limit, len(dates))
    logger.info("待重算日期 %d 个: %s~%s", len(dates), dates[0], dates[-1])

    t0 = time.time()
    total_rows = 0
    ok_cnt = 0
    for i, d in enumerate(dates, 1):
        ctx = PipelineContext(target_dates=[d], force=True, config={})
        try:
            ok = ComputeRouteMetricsStage().execute(ctx)
        except Exception as exc:
            logger.error("%s 重算异常: %s", d, exc)
            continue
        # 一天一存：execute 内部已逐日 INSERT OR REPLACE 提交，此处校验落库后记 checkpoint
        rows = ctx.summary.get("route_metrics", {}).get("rows", 0)
        if _date_is_complete(d):
            _mark_done(d)
            ok_cnt += 1
            total_rows += rows
            logger.info("[%d/%d] %s: ok=%s rows=%d 完成（累计 %.0fs）",
                        i, len(dates), d, ok, rows, time.time() - t0)
        else:
            logger.warning("[%d/%d] %s: 行数不齐（%s），未记 checkpoint，下次续跑会重算",
                           i, len(dates), d, d)
    logger.info("完成: %d/%d 日期, 共 %d 行, 耗时 %.0fs", ok_cnt, len(dates), total_rows, time.time() - t0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
