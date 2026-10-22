"""算法族映射覆盖率检查（057 DL-04）——只读统计，发布前/月度运行。

检验方法（tasks.md DL-04）：
- 近 6 个月路由映射覆盖率 ≥95%；
- 与管道 algo 列逐路由一致（coarse_group(classify()) vs 管道 algo，差异 ⊆ 已知缺口）；
- UNMAPPED 清单进报告。

用法：
    python scripts/ops/check_algo_taxonomy_coverage.py [--days 180] [--min-coverage 95]

    --days            统计回溯天数（默认 180，近 6 个月）
    --min-coverage    覆盖率门槛（默认 95，百分比）

退出码：0=覆盖率达标且无新差异；1=覆盖率不足或存在已知缺口外的新差异
（新差异 = 管道侧口径变化，需先更新契约再排查）。

管道侧协作：命中 KNOWN_PIPELINE_GAPS 的组合属已知差异（管道 mapping 未覆盖），
由 EMSXDataPipeline 补映射后复核（DL-06 契约冻结时对齐删除）。
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

# ── 路径设置（脚本直接运行时需要仓库根）──
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from platform_data.contracts import (  # noqa: E402
    KNOWN_PIPELINE_GAPS,
    classify_algo,
    coarse_group,
    coverage_of,
)

logger = logging.getLogger(__name__)


def _load_aggregates(since_date: str) -> list[tuple[str, str | None, int]]:
    """tca_route_summary 按 (Broker, StrategyType) 聚合 count（近 N 天）。"""
    from data_access import ConnectionManager
    from data_access.config import Config

    conn = ConnectionManager().get_connection("fill_bdib")
    try:
        rows = conn.execute(
            f"SELECT Broker, StrategyType, COUNT(*) FROM {Config.TCA_ROUTE_SUMMARY_TABLE} "
            f"WHERE order_as_of_date >= ? GROUP BY Broker, StrategyType",
            (since_date,),
        ).fetchall()
        return [(str(r[0]), r[1], int(r[2])) for r in rows if r[0]]
    finally:
        conn.close()


def _load_pipeline_algo(since_date: str) -> dict[tuple[str, str], str]:
    """(Broker, normalized StrategyType) → 管道 algo（逐路由一致性的比对基准）。"""
    from data_access import ConnectionManager
    from data_access.config import Config
    from platform_data.contracts import normalize_strategy_type

    conn = ConnectionManager().get_connection("fill_bdib")
    try:
        rows = conn.execute(
            f"SELECT Broker, StrategyType, algo FROM {Config.TCA_ROUTE_SUMMARY_TABLE} "
            f"WHERE order_as_of_date >= ? GROUP BY Broker, StrategyType, algo",
            (since_date,),
        ).fetchall()
        mapping: dict[tuple[str, str], str] = {}
        for broker, strategy, algo in rows:
            if not broker or not algo:
                continue
            mapping[((str(broker).upper(), normalize_strategy_type(strategy)))] = str(algo)
        return mapping
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="算法族映射覆盖率检查（057 DL-04）")
    parser.add_argument("--days", type=int, default=180, help="统计回溯天数（默认 180）")
    parser.add_argument("--min-coverage", type=float, default=95.0, help="覆盖率门槛（默认 95）")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    since = (date.today() - timedelta(days=args.days)).strftime("%Y%m%d")
    aggregates = _load_aggregates(since)
    if not aggregates:
        logger.error("tca_route_summary 近 %d 天无数据（since=%s）", args.days, since)
        return 1

    stats = coverage_of(aggregates)
    logger.info(
        "细分族覆盖率：%s%%（covered=%d / total=%d，unmapped=%d，近 %d 天）",
        stats["coverage_pct"], stats["covered"], stats["total"], stats["unmapped"], args.days,
    )
    for broker, strategy, count in stats["unmapped_list"]:
        logger.warning("  UNMAPPED: (%s, %r) x%d —— 请补 STRATEGY_TYPE_MAP 或规则", broker, strategy, count)

    # 与管道 algo 逐组合比对：差异须 ⊆ 已知缺口
    pipeline = _load_pipeline_algo(since)
    new_gaps: list[tuple[tuple[str, str], str, str, str]] = []
    known_gap_total = 0
    for key, pipeline_algo in pipeline.items():
        family = classify_algo(*key)
        mine = coarse_group(family)
        if mine == pipeline_algo:
            continue
        if key in KNOWN_PIPELINE_GAPS:
            known_gap_total += 1
            continue
        new_gaps.append((key, family, mine, pipeline_algo))
    for key, family, mine, pipeline_algo in new_gaps:
        logger.warning(
            "  新差异: (%s, %r) 本侧 %s→%s vs 管道 %s —— 先更新契约/规则再排查管道口径",
            key[0], key[1], family, mine, pipeline_algo,
        )

    ok = stats["coverage_pct"] >= args.min_coverage and not new_gaps
    if stats["gap_counts"]:
        logger.info("已知管道缺口（交管道侧补映射，DL-06 对齐）：")
        for key, count in sorted(stats["gap_counts"].items()):
            logger.info("  - (%s, %r) x%d", key[0], key[1], count)
    if ok:
        logger.info("算法族覆盖率检查通过（覆盖率 %.2f%% ≥ %.1f%%，新差异 0）", stats["coverage_pct"], args.min_coverage)
        return 0
    logger.warning("算法族覆盖率检查未通过（覆盖率/新差异不达标）")
    return 1


if __name__ == "__main__":
    sys.exit(main())
