"""交易员复盘台纯函数层（无 IO；单测主战场）。

口径来源：`specs/210-costview-trader-order-review/实施方案.md`
§0.2 F3（成本符号）、§4.1（完成率 / 多路由聚合语义）、§4.12（质量徽章）、
§4.13（KPI 首屏）。本模块只接收 dict / 标量，禁止碰数据库（实现约束 §3.3）。
"""

from __future__ import annotations

from typing import Any, Optional

#: 完成率分桶（§3.4.1 completion_bucket 枚举）
COMPLETION_BUCKETS: tuple[str, ...] = ("lt50", "50to80", "80to100", "eq100", "gt100")

#: 质量筛选枚举（§3.4.1 quality 参数）
QUALITY_FILTERS: tuple[str, ...] = (
    "all", "clean", "overfill", "cost_missing", "par_suspect", "single_fill",
)

#: 订单级 `|Amount − ΣRouteShares| / max(Amount,1)` 容差（§4.12 amount_qty_mismatch）
AMOUNT_QTY_TOLERANCE = 0.005

#: par_suspect 的 critical 档（§4.12：>10 为 bad；与 report_measure 同值）
PAR_SUSPECT_BAD_RATE = 10.0


def adverse_bps(value: Optional[float]) -> Optional[float]:
    """F3：成本符号统一 —— 上游有符号值（负 = 劣），adverse = -value（正 = 差）。

    规则/提示内部一律用 adverse 比较，避免阈值写成负数；展示层仍用上游原值。
    """
    return None if value is None else -value


def completion_bucket(completion: Optional[float]) -> Optional[str]:
    """完成率分桶：lt50 / 50to80 / 80to100 / eq100 / gt100（不可得返回 None）。"""
    if completion is None:
        return None
    if completion > 1.0:
        return "gt100"
    if completion == 1.0:
        return "eq100"
    if completion >= 0.8:
        return "80to100"
    if completion >= 0.5:
        return "50to80"
    return "lt50"


def amount_qty_mismatch(amount_shares: Optional[float], shares_sum: Optional[float]) -> bool:
    """订单级委托股数口径校验（§4.12）：|Amount − ΣRouteShares| / max(Amount,1) > 0.5%。"""
    if amount_shares is None or shares_sum is None:
        return False
    denom = max(abs(amount_shares), 1.0)
    return abs(amount_shares - shares_sum) / denom > AMOUNT_QTY_TOLERANCE


def quality_flags(row: dict[str, Any]) -> tuple[str, list[str]]:
    """订单行质量徽章（§4.12 中可由订单级聚合直接判定的部分）。

    返回 (level, flags)：level ∈ bad/warn/info/clean；flags 为徽章 id 列表。
    liquidity_unknown / peer_small / latency_anomaly / fx_missing 需要逐笔、
    peer 或汇率上下文，随 PR-2 起接入，不在本批伪造。
    """
    flags: list[str] = []
    if _flag(row, "flag_overfill"):
        flags.append("overfill")
    if _flag(row, "flag_amount_mismatch"):
        flags.append("amount_qty_mismatch")
    if _flag(row, "flag_cost_missing"):
        flags.append("cost_missing")
    max_par = row.get("max_par_rate")
    if max_par is not None and max_par > 1.0:
        flags.append("par_suspect")
    if _flag(row, "flag_single_fill"):
        flags.append("single_fill")
    return (_level_of(row, max_par), flags)


def _flag(row: dict[str, Any], key: str) -> bool:
    return bool(row.get(key))


def _level_of(row: dict[str, Any], max_par: Optional[float]) -> str:
    """徽章级别归并：overfill 或 par>10 为 bad；其余 warn/info 逐级回落。"""
    if _flag(row, "flag_overfill") or (max_par is not None and max_par > PAR_SUSPECT_BAD_RATE):
        return "bad"
    if _flag(row, "flag_amount_mismatch") or _flag(row, "flag_cost_missing") or (
        max_par is not None and max_par > 1.0
    ):
        return "warn"
    if _flag(row, "flag_single_fill"):
        return "info"
    return "clean"


def opp_bps(row: dict[str, Any]) -> Optional[float]:
    """机会成本 bps：opportunity_cost / (ΣRouteShares × p_decision) × 10000（F3 同源分母）。"""
    cost = row.get("opportunity_cost")
    shares = row.get("route_shares")
    p_decision = row.get("p_decision")
    if cost is None or not shares or p_decision is None:
        return None
    return cost / (shares * p_decision) * 10000.0


def _kpi(value: Optional[float], n: Optional[int], **extra: Any) -> dict[str, Any]:
    """KPI 卡结构：value / n / scope（口径见 §4.13；n=0 时 value 置 None）。"""
    payload: dict[str, Any] = {"value": value, "n": n, "scope": extra.pop("scope", "full")}
    payload.update(extra)
    return payload


def compute_kpi(rows: list[dict[str, Any]]) -> dict[str, Optional[dict[str, Any]]]:
    """KPI 首屏（§4.13，PR-1 可算子集）；passive_ratio / release_delay_p90 / peer 随后续 PR 接入。"""
    total = len(rows)
    completions = [r.get("completion") for r in rows if r.get("completion") is not None]
    low = sum(1 for c in completions if c < 0.8)
    pairs = [
        (r.get("arrival_cost_bps"), opp_bps(r), r.get("completion")) for r in rows
    ]
    opp_rows = [p for p in pairs if p[0] is not None and p[1] is not None]
    opp_dominant = sum(
        1 for a, o, c in opp_rows
        if c is not None and c < 1.0
        and (adverse_bps(o) or 0.0) > (adverse_bps(a) or 0.0)
    )
    overfill = sum(1 for r in rows if _flag(r, "flag_overfill"))
    cost_missing = sum(1 for r in rows if _flag(r, "flag_cost_missing"))
    return {
        "orders": _kpi(float(total), total),
        "low_completion_ratio": _kpi(
            (low / len(completions)) if completions else None,
            len(completions), denominator=len(completions),
        ),
        "opp_dominant_ratio": _kpi(
            (opp_dominant / len(opp_rows)) if opp_rows else None,
            len(opp_rows), denominator=len(opp_rows),
        ),
        "passive_ratio": _kpi(None, None, scope="current_page", note="逐笔 Liquidity 未接入（PR-2）"),
        "release_delay_p90": _kpi(None, None, scope="continuous_only", note="释放延迟随逐笔时间戳接入（PR-2）"),
        "anomaly_orders": _kpi(
            float(overfill + cost_missing - _both_flagged(rows)), total,
            critical=overfill, warning=cost_missing,
            note="本批按 overfill/cost_missing 计；阈值规则联动随异常摘要（PR-5）",
        ),
        "peer_small_orders": _kpi(None, total, note="peer 样本量随 peer 端点（PR-2）接入"),
    }


def _both_flagged(rows: list[dict[str, Any]]) -> int:
    """同时命中 overfill 与 cost_missing 的订单数（避免 anomaly 计数重复）。"""
    return sum(
        1 for r in rows if _flag(r, "flag_overfill") and _flag(r, "flag_cost_missing")
    )


def compute_probes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """全局可信度横幅 4 类检查（§4.12）：始终返回 4 条，0 触发也可见、不伪装通过。"""
    quantity = sum(
        1 for r in rows if _flag(r, "flag_overfill") or _flag(r, "flag_amount_mismatch")
    )
    participation = sum(
        1 for r in rows if r.get("max_par_rate") is not None and r["max_par_rate"] > 1.0
    )
    cost_missing = sum(1 for r in rows if _flag(r, "flag_cost_missing"))
    return [
        {"id": "quantity", "checked": True, "triggered": quantity,
         "affected_kpis": ["completion", "opportunity_cost"], "note": None},
        {"id": "participation", "checked": True, "triggered": participation,
         "affected_kpis": ["par_rate"],
         "note": "多路由求和不计（F2）；>1000% 见质量徽章 par_suspect"},
        {"id": "cost_missing", "checked": True, "triggered": cost_missing,
         "affected_kpis": ["arrival", "wagner_is", "opportunity_cost"], "note": None},
        {"id": "fill_quality", "checked": False, "triggered": None,
         "affected_kpis": ["passive_ratio", "peer_percentile", "release_delay"],
         "note": "逐笔质量检查待逐笔查询接入（PR-2），当前未检查（不伪装通过）"},
    ]
