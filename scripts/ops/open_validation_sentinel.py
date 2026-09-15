"""开放验证项主动哨兵 — 台账两条「开放验证项」的轻量检查（只读）。

背景：台账 §五「开放验证项」两条挂账原为被动触发（等真实数据出现），
本脚本把触发条件变成主动哨兵 —— 定期（建议每周，或挂质量门）对生产库跑
一次只读探针，命中条件即输出提醒，避免挂账项随时间被淡忘。

检查项：
- D8 回退路径：存在「非 USD 币种且缺 fx_rate」的路由 → 逐行回退与
  fill_bdib 回填路径已被真实数据触发，提醒回补数值验证（回补前后缺口
  金额对比，见台账 §五 第八轮开放验证项）。
- D14 探针精度：比对「bdib_gap 探针命中集」与「bdib_missing 类指标
  （p_arrival）NULL 集」——两者重合则零误豁免结论可保持，出现探针 >
  NULL 集（过度豁免）即提醒重跑生产校验并更新台账结论。

用法：
    python scripts/ops/open_validation_sentinel.py [--strict]

    --strict  命中任一提醒时退出码 1（供质量门 / 定时任务告警接线）；
              默认退出码恒为 0，仅打印提醒。
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# ── 路径设置（脚本直接运行时需要仓库根）──
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent.parent
for _p in [_PROJECT_ROOT, _SCRIPT_DIR.parent]:
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from data_access.config import Config  # noqa: E402
from data_access.storage.connection import AccessTier, ConnectionManager  # noqa: E402
from CostView.src.monitoring import report_measure as rm  # noqa: E402

logger = logging.getLogger(__name__)

#: D14 生产校验的探针（与 metric_coverage.BDIB_GAP_PROBE_METRICS 保持一致的
#: SQL 形态；此处独立成串便于与 p_arrival NULL 集做集合级比对）
_BDIB_GAP_PROBE = (
    "COALESCE(fill, 0) > 0 AND par_rate IS NULL AND pnl_vwap IS NULL "
    "AND p_arrival IS NULL AND p_close IS NULL"
)


def _check_d8_backfill(conn) -> tuple[bool, str]:
    """D8 回退路径触发探测：非 USD 路由缺 fx_rate 的条数。"""
    try:
        n_missing = conn.execute(
            f"SELECT COUNT(*) FROM {Config.TCA_ROUTE_SUMMARY_TABLE} "
            "WHERE Currency IS NOT NULL AND Currency <> 'USD' "
            "AND fx_rate IS NULL"
        ).fetchone()[0]
    except Exception as exc:  # 表/列缺失 → 未触发，注明原因
        return False, f"D8 探针不可用（{exc}），视为未触发"
    if not n_missing:
        return False, "D8 回退路径未触发（非 USD 路由 fx 全覆盖）"
    return True, (
        f"D8 回退路径已被真实数据触发：{n_missing} 条非 USD 路由缺 fx_rate —— "
        "请回补缺口金额数值验证（回补前后对比），并更新台账开放验证项"
    )


def _check_d14_probe(conn, scope: rm.ReportScope) -> tuple[bool, str]:
    """D14 探针精度探测：bdib_gap 命中集是否与 p_arrival NULL 集重合。"""
    condition, scope_params = rm.scope_condition(scope)
    where = "COALESCE(fill, 0) > 0"
    params: list = []
    if condition:
        where = f"{where} AND {condition}"
        params.extend(scope_params)
    try:
        row = conn.execute(
            f"SELECT "
            f"SUM(CASE WHEN {_BDIB_GAP_PROBE} THEN 1 ELSE 0 END), "
            f"SUM(CASE WHEN p_arrival IS NULL THEN 1 ELSE 0 END), "
            f"SUM(CASE WHEN {_BDIB_GAP_PROBE} AND p_arrival IS NOT NULL "
            "THEN 1 ELSE 0 END) "
            f"FROM {Config.TCA_ROUTE_SUMMARY_TABLE} WHERE {where}",
            params,
        ).fetchone()
    except Exception as exc:
        return False, f"D14 探针不可用（{exc}），视为未触发"
    gap_routes, arrival_null, over_exempt = (int(v or 0) for v in row)
    if over_exempt:
        return True, (
            f"D14 探针出现过度豁免：{over_exempt} 条路由被探针剔除但 p_arrival "
            "可计算（bdib_cutoff 残余量级超预期）—— 请在生产数据上重跑 SLA 校验，"
            "并更新台账「零误豁免」结论"
        )
    return False, (
        f"D14 探针无过度豁免（生产样本）：bdib_gap {gap_routes} 条均落在 "
        f"p_arrival NULL 集内（NULL 共 {arrival_null} 条，其余为其他结构内 NULL，"
        "如零成交 / 收盘竞价）"
    )


def main(argv: list[str] | None = None) -> int:
    """哨兵入口：两条探针顺序执行，命中即输出提醒。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    parser = argparse.ArgumentParser(
        description="台账开放验证项主动哨兵（只读探针，--strict 命中即退出码 1）",
    )
    parser.add_argument("--strict", action="store_true", help="命中提醒时退出码 1")
    args = parser.parse_args(argv)

    mgr = ConnectionManager()
    conn = None
    triggered: list[str] = []
    try:
        conn = mgr.get_connection("fill_bdib", AccessTier.READ)
        for name, (hit, message) in (
            ("D8", _check_d8_backfill(conn)),
            ("D14", _check_d14_probe(conn, rm.resolve_scope(None))),
        ):
            prefix = "[哨兵][命中]" if hit else "[哨兵][正常]"
            print(f"{prefix} {message}")
            if hit:
                triggered.append(name)
    except FileNotFoundError:
        print("[哨兵][跳过] fill_bdib.db 不可得（只读模式），本次不校验")
    except Exception as exc:
        print(f"[哨兵][跳过] 数据访问失败：{exc}")
        logger.debug("哨兵数据访问失败", exc_info=True)
    finally:
        if conn is not None:
            conn.close()

    if triggered and args.strict:
        print(f"[哨兵] --strict：命中 {', '.join(triggered)}，退出码 1")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
