"""预期成本与 timing risk 模型（057 DL-13）——事前口径的评估标准化分母。

用途边界（K3，继承 cost_model.py 禁项）：
- ✅ 评估标准化的共同分母（z =（预期−实际）÷ timing risk，DL-23）；
- ✅ 盘前单内部「把账算清」展示（DL-14）；
- ❌ 不对外作事前成本预测（docs/report-tca-known-limitations.md K3 仅在
  评估标准化范围内重开）；域外一律 None，不外推。

模型形态：复用 `cost_model.fit_impact_model` 幂律冲击（参与率 × 波动 →
冲击 bps）+ σ√T timing risk；按 Exchange 市场组分别拟合，产物 JSON 落
`models/`（git 跟踪，版本化可复现）。
"""

from __future__ import annotations

import json
import logging
import math
from datetime import date, timedelta
from pathlib import Path
from typing import Optional, Sequence

from CostView.src.evaluation.cost_model import ImpactModel, fit_impact_model

logger = logging.getLogger(__name__)

# 模型版本：口径变更升版（文件名与载荷均带版本；与 platform_data 契约互锁）
COST_MODEL_VERSION = "cost-model-v1"

# 拟合样本窗口（交易日）：近 6 个月，与 DL-05 盘点头寸一致
FIT_WINDOW_DAYS = 180

# 模型产物目录（git 跟踪——可复现、可 diff、可回滚）
MODELS_DIR = Path(__file__).resolve().parent / "models"

# 年化 → 日波动换算（交易日年化）
TRADING_DAYS_PER_YEAR = 252


# ── 纯函数（无 IO，单测覆盖） ─────────────────────────────────────────────────


def timing_risk_bps(
    annual_vol_pct: float | None,
    duration_min: float,
    session_minutes: float,
) -> Optional[float]:
    """σ√T timing risk（bps）：年化波动% ÷ √252 × √(时长 ÷ 会话时长)。

    年化 VOLATILITY_30D 为百分比空间（指南 §10 量纲口径）；返回 bps。
    任一输入非正返回 None。
    """
    if annual_vol_pct is None or annual_vol_pct <= 0 or duration_min <= 0 or session_minutes <= 0:
        return None
    daily_sigma_pct = annual_vol_pct / math.sqrt(TRADING_DAYS_PER_YEAR)
    scaled = daily_sigma_pct * math.sqrt(duration_min / session_minutes)
    return round(scaled * 100, 2)  # % → bps


def required_duration_min(qty: float, participation: float, adv: float | None) -> Optional[float]:
    """按目标参与率所需交易时长（分钟）= qty ÷ (p* × ADV)（会话内速率）。

    participation 为小数（0.1 = 10%）；qty/adv 为股数；adv 缺失或参与率非正返回 None。
    """
    if adv is None or adv <= 0 or participation <= 0 or qty <= 0:
        return None
    return round(qty / (participation * adv), 1)


def close_capacity_pct(close_qty: float, avg_close_auction_vol: float | None) -> Optional[float]:
    """收盘段量 ÷ 日均收盘竞价量（0–100+）；分母缺失返回 None。"""
    if avg_close_auction_vol is None or avg_close_auction_vol <= 0 or close_qty <= 0:
        return None
    return round(close_qty / avg_close_auction_vol * 100, 2)


def expected_cost_bps(
    model: ImpactModel | None,
    participation: float,
    volatility: float,
) -> Optional[float]:
    """预期冲击成本（bps）；模型缺失或域外返回 None（不外推）。"""
    if model is None or participation <= 0 or volatility <= 0:
        return None
    return model.predict_bps(participation, volatility)


# ── 拟合（IO） ────────────────────────────────────────────────────────────────


def fit_expected_cost_models(
    mgr,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    min_observations: int = 30,
) -> dict[str, ImpactModel]:
    """按 Exchange 市场组拟合幂律冲击模型。

    样本口径（2026-10-23 实测诊断后确定，均经真实数据验证）：
    - **参与率 = 意图参与率** `RouteShares ÷ ADV20`（订单层面，决策时点可得、
      外生）——不用实现参与率 par_rate：实测其与冲击负相关（算法内生调速：
      大冲击单被 POV 自动降速，simultaneity），且违反原则 4「评估只用决策前
      变量」；另实测 13.98% 的 par_rate >1（bar 覆盖缺失退化为成交量原值）；
    - 目标 = `temp_impact_30min_bps`（瞬时冲击 30 分钟，带符号——E[冲击]口径，
      行业标准；正负各半为正常观测），缺失回落 `arrival_cost_bps`；
    - 目标 winsorize 1%/99% 分位（每市场组）——实测成本分布极度左偏且被
      极端值主导（US ≥5% 意图参与率档均值 −149bps），不截断则拟合被个别
      超大单绑架；
    - 波动 = `daily_volatility`（按 equ_ticker × date join，DL-10 同源）。
    样本不足不产模型；r² < 0.01 弱模型落盘但告警（消费方可知悉模型强度）。
    """
    from data_access.config import Config
    from platform_data.contracts.db_constants import BDIB_DAILY_SUMMARY_TABLE

    end = end_date or date.today().strftime("%Y%m%d")
    start = start_date or (date.today() - timedelta(days=FIT_WINDOW_DAYS)).strftime("%Y%m%d")

    conn = mgr.get_connection("fill_bdib")
    try:
        rows = conn.execute(
            f"SELECT Exchange, equ_ticker, order_as_of_date, RouteShares, "
            f"temp_impact_30min_bps, arrival_cost_bps FROM {Config.TCA_ROUTE_SUMMARY_TABLE} "
            f"WHERE order_as_of_date BETWEEN ? AND ? AND RouteShares > 0",
            (start, end),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        return {}

    # 波动与 ADV20 join：(equ_ticker, date) → (daily_volatility, adv_20d)
    vol_conn = mgr.get_connection("raw_bdib")
    try:
        vol_rows = vol_conn.execute(
            f"SELECT equ_ticker, trade_date, daily_volatility, adv_20d FROM {BDIB_DAILY_SUMMARY_TABLE} "
            f"WHERE trade_date BETWEEN ? AND ? AND daily_volatility > 0 AND adv_20d > 0",
            (start, end),
        ).fetchall()
    finally:
        vol_conn.close()
    vol_map = {(str(r[0]), str(r[1])): (float(r[2]), float(r[3])) for r in vol_rows if r[2] and r[3]}

    by_market: dict[str, list[tuple[float, float, float]]] = {}
    for exchange, ticker, trade_date, shares, impact, arrival in rows:
        joined = vol_map.get((str(ticker), str(trade_date)))
        if joined is None:
            continue
        vol, adv20 = joined
        target = impact if impact is not None else arrival
        if target is None:
            continue
        intent_participation = float(shares) / adv20
        if intent_participation <= 0:
            continue
        by_market.setdefault(str(exchange or "unknown"), []).append(
            (intent_participation, vol, float(target))
        )

    models: dict[str, ImpactModel] = {}
    for market, samples in sorted(by_market.items()):
        samples = _winsorize_targets(samples)
        model = fit_impact_model(samples, min_observations=min_observations)
        if model is not None:
            if model.r_squared < 0.01:
                logger.warning("%s: 模型弱（r²=%.4f），落盘但 note 标注", market, model.r_squared)
            models[market] = model
        else:
            logger.warning("%s: 样本不足 %d（< %d），不产模型", market, len(samples), min_observations)
    return models


def _winsorize_targets(
    samples: list[tuple[float, float, float]],
    *,
    lower_q: float = 0.01,
    upper_q: float = 0.99,
) -> list[tuple[float, float, float]]:
    """目标变量（第三元）按分位截断（每市场组）；防御极端值绑架拟合。"""
    targets = sorted(s[2] for s in samples)
    lo = targets[min(len(targets) - 1, int(lower_q * len(targets)))]
    hi = targets[min(len(targets) - 1, int(upper_q * len(targets)))]
    return [(p, v, min(max(t, lo), hi)) for p, v, t in samples]


def model_path(market: str) -> Path:
    """模型产物路径（版本化文件名）。"""
    return MODELS_DIR / f"impact_{market.upper()}_{COST_MODEL_VERSION}.json"


def save_models(models: dict[str, ImpactModel], *, window: str) -> list[Path]:
    """落盘模型产物（含 fit 元数据）；返回写入的文件列表。"""
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for market, model in sorted(models.items()):
        payload = {
            "model_version": COST_MODEL_VERSION,
            "market": market,
            "fit_window": window,
            **model.to_payload(),
        }
        path = model_path(market)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        written.append(path)
    return written


def load_expected_cost_model(market: str) -> ImpactModel | None:
    """按市场加载模型；无产物返回 None（降级可见）。"""
    path = model_path(market)
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("model_version") != COST_MODEL_VERSION:
        logger.warning("%s: 模型版本 %s 与当前 %s 不一致，忽略", market, payload.get("model_version"), COST_MODEL_VERSION)
        return None
    return ImpactModel(
        intercept=payload["intercept"],
        slope_participation=payload["slope_participation"],
        slope_volatility=payload["slope_volatility"],
        n_observations=payload["n_observations"],
        r_squared=payload["r_squared"],
        participation_domain=tuple(payload["participation_domain"]),
        volatility_domain=tuple(payload["volatility_domain"]),
        note=payload.get("note", ""),
    )


def _session_minutes(market: str) -> Optional[float]:
    """市场会话时长（分钟，DL-03 注册表；未注册回落 390）。"""
    from platform_data.contracts.exchange_session_contracts import SESSION_REGISTRY

    session = SESSION_REGISTRY.get(market.upper())
    if session is None:
        return 390.0
    open_min = int(session.market_open[:2]) * 60 + int(session.market_open[3:5])
    close_min = int(session.market_close[:2]) * 60 + int(session.market_close[3:5])
    return float(close_min - open_min)


def calibrate_models(
    mgr,
    *,
    fit_days: int = 120,
    val_days: int = 60,
) -> dict:
    """时间切分样本外校准：前 fit_days 拟合 → 后 val_days 验证。

    每市场输出：n、z 均值/std（z =（预期−实际）÷ timing risk，timing risk 用
    order_duration_sec × 日波动经 _session_minutes 缩放）、分位数覆盖率
    （预期 10/50/90 分位对实际冲击的覆盖比例）。
    """
    from data_access.config import Config
    from platform_data.contracts.db_constants import BDIB_DAILY_SUMMARY_TABLE

    end = date.today()
    fit_end = (end - timedelta(days=val_days)).strftime("%Y%m%d")
    fit_start = (end - timedelta(days=val_days + fit_days)).strftime("%Y%m%d")
    val_start = fit_end
    val_end = end.strftime("%Y%m%d")

    models = fit_expected_cost_models(mgr, start_date=fit_start, end_date=fit_end)
    if not models:
        return {"message": "拟合期样本不足", "markets": {}}

    # 验证期样本（与 fit 同参与率口径：RouteShares/ADV20；目标不截断——样本外保真）
    conn = mgr.get_connection("fill_bdib")
    try:
        rows = conn.execute(
            f"SELECT Exchange, equ_ticker, order_as_of_date, RouteShares, "
            f"temp_impact_30min_bps, arrival_cost_bps, order_duration_sec "
            f"FROM {Config.TCA_ROUTE_SUMMARY_TABLE} "
            f"WHERE order_as_of_date > ? AND order_as_of_date <= ? AND RouteShares > 0",
            (val_start, val_end),
        ).fetchall()
    finally:
        conn.close()
    vol_conn = mgr.get_connection("raw_bdib")
    try:
        vol_rows = vol_conn.execute(
            f"SELECT equ_ticker, trade_date, daily_volatility, adv_20d FROM {BDIB_DAILY_SUMMARY_TABLE} "
            f"WHERE trade_date > ? AND trade_date <= ? AND daily_volatility > 0 AND adv_20d > 0",
            (val_start, val_end),
        ).fetchall()
    finally:
        vol_conn.close()
    vol_map = {(str(r[0]), str(r[1])): (float(r[2]), float(r[3])) for r in vol_rows if r[2] and r[3]}

    per_market: dict[str, list[tuple[float, float, float, float]]] = {}
    # market → [(expected, actual, vol, duration_min)]
    for exchange, ticker, trade_date, shares, impact, arrival, duration_sec in rows:
        market = str(exchange or "unknown")
        model = models.get(market)
        if model is None:
            continue
        joined = vol_map.get((str(ticker), str(trade_date)))
        if joined is None:
            continue
        vol, adv20 = joined
        target = impact if impact is not None else arrival
        if target is None:
            continue
        participation = float(shares) / adv20
        if participation <= 0:
            continue
        expected = model.predict_bps(participation, vol)
        if expected is None:
            continue  # 域外样本不计入校准（不外推）
        duration_min = float(duration_sec) / 60 if duration_sec else 0.0
        per_market.setdefault(market, []).append((expected, float(target), vol, duration_min))

    report: dict[str, dict] = {}
    for market, samples in sorted(per_market.items()):
        n = len(samples)
        if n < 30:
            report[market] = {"n": n, "message": "验证样本不足"}
            continue
        session_min = _session_minutes(market)
        # z =（预期−实际）÷ timing risk（timing risk 用逐路由 duration × 日波动）
        zs = []
        for expected, actual, vol, duration_min in samples:
            risk = timing_risk_bps(vol, duration_min, session_min)
            if risk:
                zs.append((expected - actual) / risk)
        expecteds = sorted(e for e, _, _, _ in samples)
        q10, q50, q90 = _quantiles(expecteds, (0.1, 0.5, 0.9))
        cover = {
            "q10": round(sum(1 for _, a, _, _ in samples if a <= q10) / n, 4),
            "q50": round(sum(1 for _, a, _, _ in samples if a <= q50) / n, 4),
            "q90": round(sum(1 for _, a, _, _ in samples if a <= q90) / n, 4),
        }
        report[market] = {
            "n": n,
            "z_mean": round(sum(zs) / len(zs), 4) if zs else None,
            "z_std": round(_pstdev(zs), 4) if len(zs) > 1 else None,
            "coverage": cover,
        }
    return {"fit_window": f"{fit_start}~{fit_end}", "val_window": f"{val_start}~{val_end}", "markets": report}


def _pstdev(values: Sequence[float]) -> float:
    """总体标准差（校准 z 统计用）。"""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((x - mean) ** 2 for x in values) / len(values))


def _quantiles(sorted_values: Sequence[float], qs: Sequence[float]) -> list[float]:
    """简化分位数（最近秩法）。"""
    out: list[float] = []
    for q in qs:
        idx = min(len(sorted_values) - 1, max(0, int(q * len(sorted_values))))
        out.append(sorted_values[idx])
    return out


def _median(sorted_values: Sequence[float]) -> float:
    if not sorted_values:
        return 0.0
    n = len(sorted_values)
    mid = n // 2
    return sorted_values[mid] if n % 2 else (sorted_values[mid - 1] + sorted_values[mid]) / 2
