"""参数策略契约（057 DL-18/074）——纯数据 + 纯函数，无 IO。

意图驱动的路由参数规则（tasks DL-18）：
1. 意图 → 算法族（复用 DL-04 `intent_families`，MIX 拆两段）；
2. 参与率目标函数取代「18% × 比例」全局常数——`min(意图比例, 上限)`，
   状态为 thin 时 ×0.5（状态切换模板）；
3. 会话相对时间窗——VWAP/TWAP/POV 族在**收盘竞价前结束**，auction_close
   族落收盘竞价窗口；半日市按 DL-03 覆盖表收缩；
4. σ 限价保护——高波动状态放宽到 3σ，其余 2σ。

诚实边界（v0）：只产出参数计划（`ParameterPlan`），不自动改写既有
route plan 参数、不写回订单限价；volume profile 接线待 DL-09 日内曲线。
"""

from __future__ import annotations

from dataclasses import dataclass

PARAM_TEMPLATE_VERSION = "param-template-v1"

# 限价保护倍数（σ）
DEFAULT_LIMIT_SIGMA = 2.0
HIGH_VOL_SIGMA = 3.0

# 状态切换模板：thin 流动性下参与率降半（保守）
THIN_PARTICIPATION_SCALE = 0.5

# 参与率下限（与 073 的 0.1 精度对齐）
MIN_PARTICIPATION_PCT = 0.1

# 连续执行族的窗口边界（相对收盘竞价/收盘的提前量，分钟）
_AUCTION_GUARD_MINUTES = 5
_OPEN_GUARD_MINUTES = 5

# 连续执行族（不落收盘竞价）
_CONTINUOUS_FAMILIES = frozenset({"vwap", "twap", "pov", "is", "dma", "liquidity", "close", "other"})


@dataclass(frozen=True)
class ParameterPlan:
    """逐单参数计划（意图 + 状态 + 会话 → 可解释参数）。

    participation_pct：目标参与率（百分数，对齐 073 的 18.0/9.0 上限）；
    window_start_min/window_end_min：**会话相对分钟**（从开盘 0 起算）；
    rationale：触发规则的可读记录（thin/high/收盘竞价/半日市）。
    """

    order_key: str
    families: tuple[str, ...]
    participation_pct: float
    window_start_min: int
    window_end_min: int
    limit_sigma: float
    template_id: str = PARAM_TEMPLATE_VERSION
    rationale: tuple[str, ...] = ()
    schema_version: str = PARAM_TEMPLATE_VERSION


def participation_pct(
    intent_ratio_pct: float | None,
    max_cap_pct: float,
    liq_regime: str | None = None,
) -> float:
    """参与率目标：min(意图比例, 上限)，thin 时 ×0.5，下限 0.1。

    intent 缺失（无法估算意图比例）→ 取上限（保守上限即目标）；
    上限与 073 的 volume cap 一致（18.0 非 EUR / 9.0 EUR）。
    """
    cap = max(float(max_cap_pct), 0.0)
    base = cap if intent_ratio_pct is None else min(float(intent_ratio_pct), cap)
    if (liq_regime or "").strip().lower() == "thin":
        base *= THIN_PARTICIPATION_SCALE
    return max(round(base, 1), MIN_PARTICIPATION_PCT)


def _hhmm_to_minutes(value: str) -> int:
    hours, _, minutes = value.partition(":")
    return int(hours) * 60 + int(minutes or 0)


def session_window_minutes(
    session,
    families: tuple[str, ...] | list[str],
    half_day_close: str | None = None,
) -> tuple[int, int, list[str]]:
    """会话相对分钟窗口（start, end, rationale）。

    session：DL-03 `ExchangeSession`（market_open/market_close/closing_auction）；
    half_day_close：半日市当日收盘（HH:MM，DL-03 覆盖表），命中则 end 收缩。

    - 连续族（vwap/twap/pov/is/dma/liquidity/close/other）：开盘 +5min 起，
      **收盘竞价（或收盘）前 5min 止**——VWAP 段不跨竞价（tasks DL-18）；
    - auction_close 族：收盘前 5min 起至收盘；
    - auction_open 族：开盘至开盘 +5min（开盘竞价窗口）。
    """
    open_min = _hhmm_to_minutes(session.market_open)
    close_hhmm = half_day_close or session.market_close
    close_min = _hhmm_to_minutes(close_hhmm)
    # 半日市时收盘竞价随收盘提前（竞价时刻跟随半日市收盘，而非常规 16:00）
    if half_day_close:
        auction_min = close_min
    else:
        auction_min = _hhmm_to_minutes(session.closing_auction) if session.closing_auction else close_min
    rationale: list[str] = []
    if half_day_close:
        rationale.append(f"half_day_close={half_day_close}")

    family_set = {str(f).strip().lower() for f in families}
    if "auction_open" in family_set:
        return (
            max(open_min - _OPEN_GUARD_MINUTES, 0),
            open_min + _OPEN_GUARD_MINUTES,
            [*rationale, "auction_open_window"],
        )
    if "auction_close" in family_set:
        start = min(auction_min - _AUCTION_GUARD_MINUTES, close_min)
        return start - open_min, close_min - open_min, [*rationale, "auction_close_window"]
    if family_set & _CONTINUOUS_FAMILIES:
        start = open_min + _OPEN_GUARD_MINUTES
        end = max(auction_min - _AUCTION_GUARD_MINUTES, start + 1)
        return start - open_min, end - open_min, [*rationale, "ends_before_closing_auction"]
    # 未知族：整段会话（可见兜底）
    return (
        open_min + _OPEN_GUARD_MINUTES - open_min,
        max(close_min - _AUCTION_GUARD_MINUTES, 1) - open_min,
        [*rationale, "unknown_family_full_session"],
    )


def limit_sigma_multiple(vol_regime: str | None) -> float:
    """σ 限价保护倍数：高波动 → 3σ，其余 2σ。"""
    if (vol_regime or "").strip().lower() == "high":
        return HIGH_VOL_SIGMA
    return DEFAULT_LIMIT_SIGMA


def build_parameter_plan(
    *,
    order_key: str,
    families: tuple[str, ...] | list[str],
    session,
    liq_regime: str | None = None,
    vol_regime: str | None = None,
    intent_ratio_pct: float | None = None,
    max_cap_pct: float = 18.0,
    half_day_close: str | None = None,
) -> ParameterPlan:
    """组合规则产出参数计划（rationale 逐条可解释）。"""
    family_tuple = tuple(str(f) for f in families)
    rationale: list[str] = []
    participation = participation_pct(intent_ratio_pct, max_cap_pct, liq_regime)
    if (liq_regime or "").lower() == "thin":
        rationale.append("liq=thin→participation×0.5")
    if intent_ratio_pct is not None and intent_ratio_pct > max_cap_pct:
        rationale.append(f"intent {intent_ratio_pct:.1f}% capped at {max_cap_pct:.1f}%")

    window_start, window_end, window_rationale = session_window_minutes(
        session, family_tuple, half_day_close
    )
    rationale.extend(window_rationale)

    sigma = limit_sigma_multiple(vol_regime)
    if (vol_regime or "").lower() == "high":
        rationale.append("vol=high→limit 3σ")
    return ParameterPlan(
        order_key=order_key,
        families=family_tuple,
        participation_pct=participation,
        window_start_min=window_start,
        window_end_min=window_end,
        limit_sigma=sigma,
        rationale=tuple(rationale),
    )
