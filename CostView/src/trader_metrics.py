"""交易员复盘台纯函数层（无 IO；单测主战场）。

口径来源：`specs/210-costview-trader-order-review/实施方案.md`
§0.2 F3（成本符号）、§4.1（完成率 / 多路由聚合语义）、§4.2（时间线分桶）、
§4.3（成本分解）、§4.4（完成轨迹）、§4.5（填充分布）、§4.6（主动/被动拆分）、
§4.9（延迟）、§4.12（质量徽章）、§4.13（KPI 首屏）。
本模块只接收 dict / 标量，禁止碰数据库（实现约束 §3.3）。
"""

from __future__ import annotations

import math
import statistics
from typing import Any, Callable, NamedTuple, Optional

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


def side_sign(side: Optional[str]) -> Optional[float]:
    """F3 方向符号：BUY 价涨为不利 → −1；SELL 价跌为不利 → +1。"""
    if side == "BUY":
        return -1.0
    if side == "SELL":
        return 1.0
    return None


#: FIX 851 严格映射（§4.6）：1/2/4 + 券商扩展 Maker/Taker/Auction；其余取值未知。
#: 映射变更只改本表；`3/0/5/6/Z/P/A/Routed/空` 在 UI 标「映射待业务确认」。
LIQUIDITY_MAP: dict[str, str] = {
    "1": "passive", "2": "aggressive", "4": "auction",
    "Maker": "passive", "Taker": "aggressive", "Auction": "auction",
}
LIQUIDITY_CLASSES: tuple[str, ...] = ("passive", "aggressive", "auction", "unknown")
#: 未知占比 >10% 打 liquidity_unknown 徽章（§4.6）；>30% 为 warn 档（§4.12）
LIQUIDITY_UNKNOWN_BADGE = 0.10
LIQUIDITY_UNKNOWN_WARN = 0.30


def liquidity_class(raw: Optional[str]) -> str:
    """FIX 851 取值 → 分类；未映射取值一律 unknown（不猜）。"""
    return LIQUIDITY_MAP.get((raw or "").strip(), "unknown")


def _class_cost_bps(vwap: Optional[float], p_arrival: Optional[float], sign: Optional[float]) -> Optional[float]:
    """类别成本 bps：(vwap / p_arrival − 1) × side_sign × 10000（F3：负=不利）。"""
    if vwap is None or p_arrival is None or sign is None:
        return None
    return (vwap / p_arrival - 1.0) * sign * 10000.0


def liquidity_split(
    fills: list[dict[str, Any]], p_arrival: Optional[float], side: Optional[str],
) -> dict[str, Any]:
    """主动/被动/竞价/未知拆分（§4.6）：四项股数和 = 总成交股数（误差 0）。"""
    shares_by = {c: 0.0 for c in LIQUIDITY_CLASSES}
    vwap_num = {c: 0.0 for c in LIQUIDITY_CLASSES}
    for fill in fills:
        cls = liquidity_class(fill.get("liquidity_raw"))
        shares = float(fill.get("shares") or 0.0)
        price = fill.get("price")
        shares_by[cls] += shares
        if price is not None:
            vwap_num[cls] += shares * float(price)
    total = sum(shares_by.values())
    sign = side_sign(side)

    def _share(cls: str) -> Optional[float]:
        return (shares_by[cls] / total) if total else None

    def _vwap(cls: str) -> Optional[float]:
        return (vwap_num[cls] / shares_by[cls]) if shares_by[cls] else None

    return {
        "passive_share_strict": _share("passive"),
        "aggressive_share_strict": _share("aggressive"),
        "auction_share": _share("auction"),
        "unknown_share": _share("unknown"),
        "passive_cost_bps": _class_cost_bps(_vwap("passive"), p_arrival, sign),
        "aggressive_cost_bps": _class_cost_bps(_vwap("aggressive"), p_arrival, sign),
        "recognized_share": (1.0 - _share("unknown")) if total else None,
        "total_shares": total,
        "mapping": "fix851_strict",
    }


#: 成本分解残差容差（§4.3 验收：|residual| < 0.5bps，达到即「对账异常」）
COST_RESIDUAL_TOLERANCE_BPS = 0.5


def cost_decomposition(
    *,
    delay_cost: Optional[float],
    trading_cost: Optional[float],
    opportunity_cost: Optional[float],
    wagner_is_bps: Optional[float],
    route_shares: Optional[float],
    p_decision: Optional[float],
    arrival_cost_bps: Optional[float] = None,
    completion: Optional[float] = None,
) -> dict[str, Any]:
    """订单级 IS 成本分解（§4.3）：D = RouteShares × p_decision，与 wagner_is_bps 同源。

    p_decision 缺失时只回货币成本、不画 bps（标 IS 分解不可用，禁止 NaN/Infinity）。
    residual 是**对账项**：|residual| ≥ 0.5bps 标「对账异常」，不写「归因不全」。
    """
    denom = (route_shares * p_decision) if (route_shares and p_decision) else None

    def _bps(cost: Optional[float]) -> Optional[float]:
        return (cost / denom * 10000.0) if (denom and cost is not None) else None

    delay_bps, trading_bps, opp_bps_v = _bps(delay_cost), _bps(trading_cost), _bps(opportunity_cost)
    parts = (delay_bps, trading_bps, opp_bps_v)
    residual = None
    if wagner_is_bps is not None and all(p is not None for p in parts):
        residual = wagner_is_bps - sum(parts)  # type: ignore[arg-type]
    opp_dominant = (
        opp_bps_v is not None and arrival_cost_bps is not None
        and abs(opp_bps_v) > abs(arrival_cost_bps)
    )
    return {
        "denominator": denom,
        "delay_bps": delay_bps,
        "trading_bps": trading_bps,
        "opportunity_bps": opp_bps_v,
        # 货币成本原值：p_decision 缺失时 bps 全为 None，UI 只能回退展示这三项
        # （§4.3「只展示原始货币成本」），故随 payload 一并下发，避免前端另开接口
        "delay_cost": delay_cost,
        "trading_cost": trading_cost,
        "opportunity_cost": opportunity_cost,
        "wagner_is_bps": wagner_is_bps,
        "residual_bps": residual,
        "residual_flag": (
            "对账异常" if residual is not None and abs(residual) >= COST_RESIDUAL_TOLERANCE_BPS else None
        ),
        "arrival_cost_bps": arrival_cost_bps,
        "opportunity_dominant": bool(opp_dominant),
        "opportunity_highlight": bool(completion is not None and completion < 1.0),
        "note": None if denom else "IS 分解不可用（无 BDIB/决策价）",
    }


def _kpi(value: Optional[float], n: Optional[int], **extra: Any) -> dict[str, Any]:
    """KPI 卡结构：value / n / scope（口径见 §4.13；n=0 时 value 置 None）。"""
    payload: dict[str, Any] = {"value": value, "n": n, "scope": extra.pop("scope", "full")}
    payload.update(extra)
    return payload


#: 异常摘要展示条数（§4.11：按规则计数 + 订单 Top 5）
ANOMALY_TOP_N = 5

#: 异常摘要口径说明（订单级 vs 路由级；UI 与文档同源）
ANOMALY_SCOPE_NOTE = (
    "订单级口径（成交股数加权 pnl_vwap / 完成率 / 组内最大路由参与率）；"
    "逐笔与区间类规则（区间参与率、日内波动、价格移动、订单参与率汇总）"
    "依赖路由或逐笔字段，订单层不评估，其命中见 Report → 异常路由明细；"
    "订单聚合后成交量占比普遍高于路由级，volume_pct_adv20 会主导计数，"
    "该档应读作「大单 / 高参与」而非数据质量缺陷"
)


#: 订单级严重度排序（critical 在前）
_SEVERITY_RANK: dict[str, int] = {"critical": 0, "warning": 1, "none": 2}


def _worst_of(hits: list[dict[str, Any]]) -> str:
    """命中项里最严重的档（取档位极值，不与 anomaly_query._worst_severity 重复实现）。"""
    return min(
        (str(hit.get("severity") or "warning") for hit in hits),
        key=lambda value: _SEVERITY_RANK.get(value, 9),
    )


def _record_by_rule(
    by_rule: dict[str, dict[str, Any]], hits: list[dict[str, Any]],
) -> None:
    """按规则累加命中订单数（一次命中一张订单只计一次）。"""
    for hit in hits:
        entry = by_rule.setdefault(hit["key"], {
            "key": hit["key"], "label": hit["label"], "count": 0, "critical": 0,
        })
        entry["count"] += 1
        if hit.get("severity") == "critical":
            entry["critical"] += 1


def _order_key(row: dict[str, Any]) -> tuple[str, str]:
    """订单键（OrderId + 日期；跨日同号是不同订单）。

    兼容两种行形态：SQL 聚合行（``OrderId``）与模型行（``order_id``），
    两种形态都由 `compute_anomaly_summary` 的调用方传入。
    """
    order_id = row.get("OrderId") or row.get("order_id")
    return (str(order_id or ""), str(row.get("order_as_of_date") or ""))


def compute_anomaly_summary(
    rows: list[dict[str, Any]],
    evaluate: Callable[[dict[str, Any]], list[dict[str, Any]]],
) -> dict[str, Any]:
    """订单级异常摘要（§4.11）：命中订单数 / 分档 / 按规则计数 / 订单 Top N。

    ``evaluate`` 由调用方注入（唯一规则实现见 ``anomaly_query.evaluate_metrics``
    与 ``order_rule_values``），本函数只做聚合，**不复制阈值常量**。

    计数口径（§4.13）：异常订单 = 命中 ≥1 条阈值规则 **或** ``overfill`` /
    ``cost_missing`` 的订单；``par_suspect`` 只进全局横幅，不混入。
    因此 ``orders_total`` 是三类集合的并集，``rule_orders`` / ``quality_orders``
    分别披露两个来源，避免并集把「为什么异常」掩盖掉。``overfill``（成交超过
    委托）属数据矛盾，按 critical 计（与 KPI 旧口径一致）。
    """
    overfill_keys = {_order_key(r) for r in rows if _flag(r, "flag_overfill")}
    quality_keys = {
        _order_key(r) for r in rows
        if _flag(r, "flag_overfill") or _flag(r, "flag_cost_missing")
    }
    by_rule: dict[str, dict[str, Any]] = {}
    hit_rows: list[tuple[dict[str, Any], list[dict[str, Any]], str]] = []
    hit_severity: dict[tuple[str, str], str] = {}
    for row in rows:
        hits = evaluate(row)
        if hits:
            severity = _worst_of(hits)
            hit_rows.append((row, hits, severity))
            hit_severity[_order_key(row)] = severity
            _record_by_rule(by_rule, hits)

    total = set(hit_severity) | quality_keys
    critical_orders = {
        key for key in total
        if hit_severity.get(key) == "critical" or key in overfill_keys
    }
    top_orders = sorted(
        hit_rows,
        key=lambda item: (
            _SEVERITY_RANK.get(item[2], 9),
            -len(item[1]),
            str(item[0].get("order_id")),
        ),
    )[:ANOMALY_TOP_N]
    return {
        "orders_total": len(total),
        "critical": len(critical_orders),
        "warning": len(total) - len(critical_orders),
        "rule_orders": len(hit_severity),
        "quality_orders": len(quality_keys),
        "by_rule": sorted(by_rule.values(), key=lambda item: (-item["count"], item["key"])),
        "top_orders": [
            {
                "order_id": _order_key(row)[0],
                "order_as_of_date": str(row.get("order_as_of_date")),
                "ticker": row.get("equ_ticker"),
                "side": row.get("side"),
                "severity": severity,
                "reasons": [
                    {"key": hit["key"], "label": hit["label"],
                     "severity": hit["severity"], "value": hit["value"],
                     "unit": hit["unit"]}
                    for hit in hits
                ],
            }
            for row, hits, severity in top_orders
        ],
        "scope": "order-level",
        "note": ANOMALY_SCOPE_NOTE,
    }


def compute_kpi(
    rows: list[dict[str, Any]], anomaly: Optional[dict[str, Any]] = None,
) -> dict[str, Optional[dict[str, Any]]]:
    """KPI 首屏（§4.13）；``anomaly`` 为 ``compute_anomaly_summary`` 结果。"""
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
        "anomaly_orders": _anomaly_kpi(anomaly, rows, total),
        "peer_small_orders": _kpi(None, total, note="peer 样本量随 peer 端点（PR-2）接入"),
    }


def _anomaly_kpi(
    anomaly: Optional[dict[str, Any]], rows: list[dict[str, Any]], total: int,
) -> dict[str, Any]:
    """异常订单 KPI（§4.13）：有订单级摘要时用并集口径，否则退回质量旗标口径。

    并集口径 = 命中阈值规则 ∪ overfill ∪ cost_missing；``critical`` / ``warning``
    为订单内最严重档计数（overfill 按 critical 计）。
    """
    if anomaly is None:
        overfill = sum(1 for r in rows if _flag(r, "flag_overfill"))
        cost_missing = sum(1 for r in rows if _flag(r, "flag_cost_missing"))
        return _kpi(
            float(overfill + cost_missing - _both_flagged(rows)), total,
            critical=overfill, warning=cost_missing,
            note="未接入阈值规则（仅 overfill/cost_missing）",
        )
    return _kpi(
        float(anomaly["orders_total"]), total,
        critical=anomaly["critical"], warning=anomaly["warning"],
        note="命中阈值规则或 overfill/cost_missing（订单级口径）",
    )


def _both_flagged(rows: list[dict[str, Any]]) -> int:
    """同时命中 overfill 与 cost_missing 的订单数（避免 anomaly 计数重复）。"""
    return sum(
        1 for r in rows if _flag(r, "flag_overfill") and _flag(r, "flag_cost_missing")
    )


def compute_probes(
    rows: list[dict[str, Any]],
    fill_quality: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    """全局可信度横幅 4 类检查（§4.12）：始终返回 4 条，0 触发也可见、不伪装通过。

    ``fill_quality`` 由逐笔层提供 ``{checked, triggered, note}``；缺省（无逐笔
    上下文 / 范围 >31 天）返回 checked=false + 明示原因。
    """
    quantity = sum(
        1 for r in rows if _flag(r, "flag_overfill") or _flag(r, "flag_amount_mismatch")
    )
    participation = sum(
        1 for r in rows if r.get("max_par_rate") is not None and r["max_par_rate"] > 1.0
    )
    cost_missing = sum(1 for r in rows if _flag(r, "flag_cost_missing"))
    fq = fill_quality or {
        "checked": False, "triggered": None,
        "note": "逐笔上下文缺失，未检查（不伪装通过）",
    }
    return [
        {"id": "quantity", "checked": True, "triggered": quantity,
         "affected_kpis": ["completion", "opportunity_cost"], "note": None},
        {"id": "participation", "checked": True, "triggered": participation,
         "affected_kpis": ["par_rate"],
         "note": "多路由求和不计（F2）；>1000% 见质量徽章 par_suspect"},
        {"id": "cost_missing", "checked": True, "triggered": cost_missing,
         "affected_kpis": ["arrival", "wagner_is", "opportunity_cost"], "note": None},
        {"id": "fill_quality", "checked": bool(fq.get("checked")),
         "triggered": fq.get("triggered"),
         "affected_kpis": ["passive_ratio", "peerpercentile", "release_delay"],
         "note": fq.get("note")},
    ]


def latency_block(
    *,
    order_to_route_sec: Optional[float],
    route_to_first_fill_sec: Optional[float],
    first_continuous_fill_sec: Optional[float],
    algo: Optional[str],
    first_fill_is_auction: bool,
) -> dict[str, Any]:
    """延迟三段（§4.9）：收盘/竞价单标 scheduled；负延迟 <1s 钳 0、<−1s 标异常。"""
    anomaly = (
        first_continuous_fill_sec is not None and first_continuous_fill_sec < -1.0
    )
    cont = first_continuous_fill_sec
    if cont is not None and -1.0 <= cont < 0:
        cont = 0.0
    order_to_first = (
        order_to_route_sec + route_to_first_fill_sec
        if (order_to_route_sec is not None and route_to_first_fill_sec is not None)
        else None
    )
    return {
        "order_to_route_sec": order_to_route_sec,
        "route_to_first_fill_sec": route_to_first_fill_sec,
        "order_to_first_fill_sec": order_to_first,
        "first_continuous_fill_sec": cont,
        "scheduled": bool(algo == "close" or first_fill_is_auction),
        "latency_anomaly": bool(anomaly),
    }


# ── 时间线分桶 / 完成轨迹 / 填充分布（§4.2/§4.4/§4.5）────────────────────────

#: 时间线最大桶数（§4.2：超过自动加宽桶并披露）
MAX_TIMELINE_BUCKETS = 240
#: 默认时间桶宽（分钟；可切 15）
DEFAULT_BUCKET_MIN = 5
#: 时间桶白名单（路由参数）
BUCKET_MINUTES: tuple[int, ...] = (5, 15)


def _hms(sec: Optional[float]) -> Optional[str]:
    """当日秒 → HH:MM（分钟截断；None 原样返回）。"""
    if sec is None:
        return None
    total = int(sec) // 60
    return f"{total // 60:02d}:{total % 60:02d}"


def _auto_bucket_min(span_sec: float, bucket_min: int) -> tuple[int, bool]:
    """桶数 ≤240：超宽自动加宽（向上取整到分钟）并披露。"""
    buckets = math.floor(span_sec / 60.0 / bucket_min) + 1
    if buckets <= MAX_TIMELINE_BUCKETS:
        return bucket_min, False
    widened = max(1, math.ceil(span_sec / 60.0 / MAX_TIMELINE_BUCKETS))
    return widened, True


def bucket_fills(
    fills: list[dict[str, Any]],
    bucket_min: int,
    route_shares: Optional[float],
    bars: list[dict[str, Any]],
) -> dict[str, Any]:
    """时间线分桶（§4.2）：桶从首笔成交起按固定宽度切，空桶补 0。

    fills 须含 ts_sec / shares / price / is_closing_auction；bars 为当日 raw_bdib
    聚合单位的市场量（``ts_sec`` / ``volume``），按同一 t_first/桶宽归桶 ——
    收盘竞价桶 / 无 bar 桶 participation_status = unavailable（不画 0%）。
    """
    if not fills:
        return {"bucket_min": bucket_min, "auto_widened": False, "buckets": []}
    ts_list = [float(f["ts_sec"]) for f in fills if f.get("ts_sec") is not None]
    t_first = min(ts_list)
    bucket_min, widened = _auto_bucket_min(max(ts_list) - t_first, bucket_min)
    span = math.floor((max(ts_list) - t_first) / (bucket_min * 60.0)) + 1
    acc = [{"fill": 0.0, "count": 0, "num": 0.0, "auction": 0} for _ in range(span)]
    for fill in fills:
        idx = min(int((float(fill["ts_sec"]) - t_first) // (bucket_min * 60)), span - 1)
        shares = float(fill.get("shares") or 0.0)
        acc[idx]["fill"] += shares
        acc[idx]["count"] += 1
        if fill.get("price") is not None:
            acc[idx]["num"] += shares * float(fill["price"])
        if fill.get("is_closing_auction"):
            acc[idx]["auction"] += 1
    market: dict[int, float] = {}
    for bar in bars:
        bar_ts = bar.get("ts_sec")
        if bar_ts is None or bar_ts < t_first:
            continue
        idx = min(int((float(bar_ts) - t_first) // (bucket_min * 60)), span - 1)
        market[idx] = market.get(idx, 0.0) + float(bar.get("volume") or 0.0)
    return {
        "bucket_min": bucket_min,
        "auto_widened": widened,
        "buckets": _bucket_rows(acc, t_first, bucket_min, route_shares, market),
    }


def _bucket_rows(
    acc: list[dict[str, Any]], t_first: float, bucket_min: int,
    route_shares: Optional[float], market_by_bucket: dict[int, float],
) -> list[dict[str, Any]]:
    """组装逐桶行：参与率 / 累计完成率 / 速度 / 加速度（首桶 accel=None）。"""
    rows: list[dict[str, Any]] = []
    cum, prev_speed = 0.0, None
    for idx, item in enumerate(acc):
        start = t_first + idx * bucket_min * 60.0
        speed = item["fill"] / bucket_min
        volume = market_by_bucket.get(idx)
        cum += item["fill"]
        rows.append({
            "start": _hms(start), "end": _hms(start + bucket_min * 60.0),
            "fill": item["fill"], "fill_count": item["count"],
            "vwap": (item["num"] / item["fill"]) if item["fill"] else None,
            "market_volume": volume,
            "participation": (item["fill"] / volume) if volume else None,
            # 无 bar（收盘竞价桶 / 行情缺失）→ unavailable，不画 0%
            "participation_status": "ok" if volume else "unavailable",
            "cum_completion": (cum / route_shares) if route_shares else None,
            "speed_shares_per_min": speed,
            "accel": None if prev_speed is None else speed - prev_speed,
        })
        prev_speed = speed
    return rows


def fill_span_stats(
    fills: list[dict[str, Any]], buckets: list[dict[str, Any]], fill_total: float,
) -> dict[str, Any]:
    """完成轨迹（§4.4）：span = 末笔 − 首笔；单笔成交 → 全部 None（不是 0）。

    ``speed_cv`` 分母为**非零桶**速度（API 注明）；同时披露零成交桶数。
    """
    ts = [float(f["ts_sec"]) for f in fills if f.get("ts_sec") is not None]
    if len(fills) < 2 or len(ts) < 2:
        return {
            "fill_span_sec": None, "speed_shares_per_min": None,
            "speed_cv": None, "max_speed_ratio": None,
            "zero_bucket_count": 0, "speed_cv_basis": "non_zero_buckets",
        }
    span_sec = max(ts) - min(ts)
    speeds = [b["speed_shares_per_min"] for b in buckets]
    nonzero = [s for s in speeds if s > 0]
    mean = (sum(nonzero) / len(nonzero)) if nonzero else None
    return {
        "fill_span_sec": span_sec,
        "speed_shares_per_min": (fill_total / (span_sec / 60.0)) if span_sec else None,
        "speed_cv": (
            (statistics.pstdev(nonzero) / mean) if (mean and len(nonzero) > 1) else None
        ),
        "max_speed_ratio": (max(nonzero) / mean) if (mean and nonzero) else None,
        "zero_bucket_count": sum(1 for s in speeds if s == 0),
        "speed_cv_basis": "non_zero_buckets",
    }


def fill_distribution(fills: list[dict[str, Any]], route_shares: Optional[float]) -> dict[str, Any]:
    """单次填充量分布（§4.5）：单笔不计算 CV/top3；top3 在 <3 笔时 N/A。"""
    shares = [float(f.get("shares") or 0.0) for f in fills]
    n = len(shares)
    if n == 0:
        return {"median": None, "p90": None, "cv": None,
                "max_fill_ratio": None, "top3_share": None, "fills_per_min": None}
    mean = sum(shares) / n
    cv = (statistics.pstdev(shares) / mean) if (n > 1 and mean) else None
    top3 = (sum(sorted(shares, reverse=True)[:3]) / sum(shares)) if n >= 3 and sum(shares) else None
    ts = [float(f["ts_sec"]) for f in fills if f.get("ts_sec") is not None]
    span_min = ((max(ts) - min(ts)) / 60.0) if (len(ts) >= 2) else None
    return {
        "median": statistics.median(shares),
        "p90": percentile(shares, 90.0),
        "cv": cv,
        "max_fill_ratio": (max(shares) / route_shares) if route_shares else None,
        "top3_share": top3,
        "fills_per_min": (n / span_min) if span_min else None,
    }


def percentile(values: list[float], q: float) -> Optional[float]:
    """线性插值分位数（pandas 禁用，纯函数实现）。"""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q / 100.0
    low = math.floor(pos)
    high = math.ceil(pos)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


def percentile_rank(value: Optional[float], peers: list[float]) -> Optional[float]:
    """分位公式（§4.7）：p = (count< + 0.5×count=) / n；空样本 / 值缺失 → None。"""
    if value is None or not peers:
        return None
    below = sum(1 for p in peers if p < value)
    equal = sum(1 for p in peers if p == value)
    return (below + 0.5 * equal) / len(peers)


def mad_z(value: Optional[float], peers: list[float]) -> Optional[float]:
    """稳健 z 分数（§4.7）：MAD=0 时退化 IQR/1.349，仍为 0 → None。"""
    if value is None or not peers:
        return None
    median = statistics.median(peers)
    mad = statistics.median([abs(p - median) for p in peers])
    if mad == 0:
        q1, q3 = percentile(peers, 25.0), percentile(peers, 75.0)
        mad = ((q3 - q1) / 1.349) if (q1 is not None and q3 is not None) else 0.0
    return ((value - median) / mad) if mad else None

# ── 210 §4.7：算法特征指纹（8 维 peer 分位）────────────────────────────────


class PeerDimension(NamedTuple):
    """单个指纹维度：取值口径 + 方向 + 不可得时的原因。"""

    key: str
    label: str
    #: higher_better：分位越高越好；lower_better：分位越低越好
    direction: str
    #: 取值函数（None = 该维度在当前数据口径下不可得，直接标 N/A）
    loader: Optional[Callable[[dict[str, Any]], Optional[float]]]
    note: Optional[str] = None


def _avg_fill_ratio(row: dict[str, Any]) -> Optional[float]:
    """单次成交量 / 委托股数（越小切片越细）。"""
    fill, count, shares = row.get("fill"), row.get("fill_count"), row.get("route_shares")
    if not fill or not count or not shares:
        return None
    return (float(fill) / float(count)) / float(shares)


def order_opp_bps(row: dict[str, Any]) -> Optional[float]:
    """订单级机会成本 bps：cost / (RouteShares × p_decision) × 10000（§3.8）。"""
    cost, shares, decision = (
        row.get("opportunity_cost"), row.get("route_shares"), row.get("p_decision"),
    )
    if cost is None or not shares or not decision:
        return None
    return float(cost) / (float(shares) * float(decision)) * 10000.0


#: 8 维指纹（顺序即展示顺序）；逐笔类维度在订单级不可得，显式标 N/A 而非跳过
PEER_DIMENSIONS: tuple[PeerDimension, ...] = (
    PeerDimension("completion", "完成率", "higher_better", lambda r: r.get("completion")),
    PeerDimension("duration", "订单历时", "lower_better", lambda r: r.get("order_duration_sec")),
    PeerDimension(
        "speed", "成交速度", "higher_better",
        lambda r: r.get("exec_rate_shares_per_min"),
    ),
    PeerDimension(
        "fill_cv", "单笔 CV", "lower_better", None,
        "需逐笔填充量分布（180 天窗口内跨库聚合超 peer 预算）",
    ),
    PeerDimension(
        "passive_ratio", "被动占比", "higher_better", None,
        "需逐笔 Liquidity（同上，逐笔级口径见详情「主动/被动拆分」）",
    ),
    PeerDimension("avg_fill_ratio", "单笔 / 委托", "lower_better", _avg_fill_ratio),
    PeerDimension(
        "arrival_cost_bps", "arrival", "higher_better",
        lambda r: r.get("arrival_cost_bps"),
    ),
    PeerDimension(
        "opportunity_cost_bps", "机会成本", "higher_better", order_opp_bps,
    ),
)

#: 分位偏离中位的阈值（|p−0.5| > 0.4 记一次偏离，§4.7 只作线索不判好坏）
PEER_DEVIATION_BAND = 0.4


def compute_peer_metrics(
    current: dict[str, Any], peers: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """8 维 peer 分位（§4.7）：每维给出原值 / 中位 / 分位 / 方向 / 有效样本数。

    - 该维度在**当前订单**缺失，或 peer 侧没有可用值 → `available=false` + `note`，
      UI 显示 N/A（禁止把 null 当 0）；
    - 分位用 §4.7 的中位名次公式（`trader_metrics.percentile_rank`），
      中位用 `statistics.median`；同一维度 peer 值缺失的行不计入 n。
    """
    metrics: list[dict[str, Any]] = []
    for dim in PEER_DIMENSIONS:
        if dim.loader is None:
            metrics.append({
                "key": dim.key, "label": dim.label, "direction": dim.direction,
                "value": None, "median": None, "percentile": None,
                "p25": None, "p75": None, "p90": None,
                "n": 0, "available": False, "note": dim.note,
            })
            continue
        value = dim.loader(current)
        values = [v for v in (dim.loader(row) for row in peers) if v is not None]
        available = value is not None and bool(values)
        metrics.append({
            "key": dim.key, "label": dim.label, "direction": dim.direction,
            "value": value,
            "median": statistics.median(values) if values else None,
            "percentile": percentile_rank(value, values),
            # 分位点随 metrics 下发：H1 用 p25（adverse 方向的 p75 等价量）、
            # H2 若日后落地用 median+MAD，UI 也可直接标注四分位
            "p25": percentile(values, 25.0) if values else None,
            "p75": percentile(values, 75.0) if values else None,
            "p90": percentile(values, 90.0) if values else None,
            "n": len(values), "available": available, "note": None,
        })
    return metrics


def fingerprint_deviation(metrics: list[dict[str, Any]]) -> int:
    """偏离维度数：|分位 − 0.5| > 0.4 的维度个数（线索，不直接判好坏）。"""
    return sum(
        1 for item in metrics
        if item.get("available") and item.get("percentile") is not None
        and abs(float(item["percentile"]) - 0.5) > PEER_DEVIATION_BAND
    )


def _hms_sec(value: Any) -> Optional[float]:
    """``HH:MM:SS`` → 当日秒（peer 延迟：路由下达 → 首笔连续成交）。"""
    if not value:
        return None
    parts = str(value).strip().split(":")
    if len(parts) < 2:
        return None
    try:
        secs = [float(part) for part in parts[:3]]
    except ValueError:
        return None
    while len(secs) < 3:
        secs.append(0.0)
    return secs[0] * 3600 + secs[1] * 60 + secs[2]


def latency_seconds(row: dict[str, Any]) -> Optional[float]:
    """单行「路由下达 → 首笔连续成交」秒数（负值视为非法 → None）。"""
    delta = _latency_delta(row)
    return delta if (delta is not None and delta >= 0) else None


def peer_latency_p90(rows: list[dict[str, Any]]) -> Optional[float]:
    """peer 的「路由下达 → 首笔连续成交」p90（秒；§4.9 H4 证据用）。"""
    deltas = [
        delta for row in rows if (delta := latency_seconds(row)) is not None
    ]
    return percentile(deltas, 90.0) if deltas else None


def _latency_delta(row: dict[str, Any]) -> Optional[float]:
    """单行延迟秒差（路由时刻缺失或异常 → None）。"""
    route = _hms_sec(row.get("route_first"))
    first = _hms_sec(row.get("first_continuous"))
    if route is None or first is None:
        return None
    return first - route


# ── 210 §4.8：条件化改进提示规则引擎 ───────────────────────────────────────

#: 置信度门槛（n≥50 高 / n≥20 中 / 否则低；H4 要求 n≥20 才触发）
HINT_HIGH_SAMPLE = 50
HINT_MIN_SAMPLE = 20
#: H4 的绝对门槛：延迟必须 >60s 才值得提示（否则与噪声不可分）
HINT_DELAY_SEC = 60.0
#: H1 的低完成率界（§4.8：completion<0.8）
HINT_LOW_COMPLETION = 0.8
#: H7 的完成率界（§4.8：completion<0.95）
HINT_SINGLE_FILL_COMPLETION = 0.95
#: H4 适用的连续算法（收盘/竞价单的延迟是排程，不是延迟）
HINT_CONTINUOUS_ALGOS: tuple[str, ...] = ("vwap", "pov", "twap")

#: 未落地的规则及原因（随 peer payload 的 degraded 一起披露，不静默省略）
HINT_SKIPPED_RULES: dict[str, str] = {
    "H2": "被动逆向选择需 peer 被动成本分布（180 天逐笔 Liquidity 聚合超预算）",
    "H5": "尾盘未完成需各市场收盘时刻表（本模块无该口径来源）",
    "H6": "集中扫单已在「单次填充量分布」面板作为线索标签展示，不重复出卡",
}


def hint_confidence(sample: int) -> str:
    """置信度分档（§4.8）：n≥50 high / n≥20 medium / 否则 low。"""
    if sample >= HINT_HIGH_SAMPLE:
        return "high"
    return "medium" if sample >= HINT_MIN_SAMPLE else "low"


def _metric_p(peer: dict[str, Any], key: str, field: str) -> Optional[float]:
    """取 peer 指标的分位值（缺失 → None，规则据此不触发）。"""
    for item in peer.get("metrics") or []:
        if item.get("key") == key and item.get("available"):
            value = item.get(field)
            return float(value) if value is not None else None
    return None


def _cost_suppressed(current: dict[str, Any]) -> bool:
    """坏数据（overfill / cost_missing）时抑制成本类提示（§4.8 输出约束）。"""
    return str(current.get("quality_level") or "") == "bad"


def _hint(
    rule_id: str, title: str, evidence: dict[str, Any],
    peer_n: int, confidence: str, action: str,
) -> Optional[dict[str, Any]]:
    """组装一条提示；任一证据缺失则返回 None（不渲染凑数卡片）。"""
    if any(value is None for value in evidence.values()):
        return None
    return {
        "rule_id": rule_id,
        "title": title,
        "evidence": evidence,
        "peer_n": peer_n,
        "confidence": confidence,
        "action": action,
    }


def _opportunity_evidence(
    current: dict[str, Any], peer: dict[str, Any],
) -> Optional[tuple[float, float, float, float]]:
    """H1 证据四元组 (completion, opp, arrival, peer_p25)；任一缺失 → None。"""
    completion = current.get("completion")
    opp = current.get("opp_bps")
    arrival = current.get("arrival_cost_bps")
    p25 = _metric_p(peer, "opportunity_cost_bps", "p25")
    if None in (completion, opp, arrival, p25):
        return None
    return float(completion), float(opp), float(arrival), float(p25)


def _hint_opportunity(current: dict[str, Any], peer: dict[str, Any]) -> Optional[dict[str, Any]]:
    """H1 机会成本主导（线索）。

    `adverse(opp) > peer_p75(adverse(opp))` 等价于 `opp < peer_p25(opp)`（adverse 取负后
    分位方向翻转）；「机会成本比 arrival 更差」（负 = 劣）即 `opp < arrival`。
    """
    if _cost_suppressed(current):
        return None
    evidence = _opportunity_evidence(current, peer)
    if evidence is None:
        return None
    completion, opp, arrival, p25 = evidence
    if completion >= HINT_LOW_COMPLETION or opp >= p25 or opp >= arrival:
        return None
    sample = int(peer.get("n") or 0)
    return _hint(
        "H1", "机会成本主导（线索）",
        {"completion": completion, "opp_bps": opp, "peer_p25_opp_bps": p25,
         "arrival_bps": arrival},
        sample, hint_confidence(sample), "复核未成交原因",
    )


def _delay_not_triggered(
    algo: str, delay: Any, p90: Any, sample: int,
) -> bool:
    """H4 不触发的条件（单一谓词列表，避免分支散落）。"""
    return (
        algo not in HINT_CONTINUOUS_ALGOS
        or delay is None or p90 is None
        or sample < HINT_MIN_SAMPLE
        or float(delay) <= float(p90)
        or float(delay) <= HINT_DELAY_SEC
    )


def _hint_delay(current: dict[str, Any], peer: dict[str, Any]) -> Optional[dict[str, Any]]:
    """H4 释放延迟：连续算法且「路由→首笔」超过 peer p90 且 >60s。"""
    if _cost_suppressed(current):
        return None
    latency = peer.get("latency") or {}
    delay = current.get("first_continuous_fill_sec")
    p90 = latency.get("p90_sec")
    sample = int(latency.get("n") or 0)
    algo = str(current.get("algo") or "").lower()
    if _delay_not_triggered(algo, delay, p90, sample):
        return None
    return _hint(
        "H4", "释放延迟偏高（线索）",
        {"route_to_first_fill_sec": float(delay), "peer_p90_sec": float(p90)},
        sample, hint_confidence(sample), "复核路由下达→首笔",
    )


def _hint_single_fill(current: dict[str, Any]) -> Optional[dict[str, Any]]:
    """H7 单笔成交：节奏类指标不可评估（自身样本，无 peer）。"""
    fill_count = current.get("fill_count")
    completion = current.get("completion")
    if fill_count is None or completion is None:
        return None
    if int(fill_count) > 1 or float(completion) >= HINT_SINGLE_FILL_COMPLETION:
        return None
    return _hint(
        "H7", "单笔成交，节奏不可评估",
        {"fill_count": int(fill_count), "completion": completion},
        0, "self", "确认是否本应拆分执行",
    )


def evaluate_hints(current: dict[str, Any], peer: dict[str, Any]) -> list[dict[str, Any]]:
    """条件化改进提示（§4.8）：H1 / H4 / H7，语气是「线索 / 需复核」。

    ``current`` 由服务层从订单聚合行与延迟样本拼装（见 ``build_order_peer``），
    ``peer`` 是 peer payload 本身（含 metrics 分位与 latency.p90）。未落地的规则见
    ``HINT_SKIPPED_RULES``，由调用方并入 ``degraded`` 披露。
    """
    candidates = [
        _hint_opportunity(current, peer),
        _hint_delay(current, peer),
        _hint_single_fill(current),
    ]
    return [hint for hint in candidates if hint is not None]

