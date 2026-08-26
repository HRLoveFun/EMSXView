"""
FX Rate Fetcher — fetch daily PX_LAST from Bloomberg for ccy_tickers.

Usage:
    fx_rates = fetch_fx_rates_for_date(["USDJPY Curncy", "USDGBP Curncy"], "20260408")
    # -> {"USDJPY Curncy": 0.00697, "USDGBP Curncy": 1.2658}

fx-rate-persistence: 汇率持久化到 fill_bdib.db 的 fx_rates 表（唯一真相源）。
注入 fx_repo（SqliteFxRatesRepository）后拉取链为：
    ① fx_rates 表精确命中（零 Bloomberg 配额消耗，先于额度暂停检查）
    ② miss 且未暂停 → Bloomberg 拉取，成功即落表（幂等 REPLACE）
    ③ 暂停/失败/空数据 → fx_rates 表 ≤目标日期 最近已知回退 → 内存缓存 → 1.0
fx_repo=None 时保持原有行为（仅内存缓存降级），向后兼容。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Optional

import pandas as pd

from DataPipeline.common.quota_pause import is_quota_paused

if TYPE_CHECKING:
    # 仅类型标注用，避免运行时引入 storage 依赖（测试/无 Bloomberg 环境可独立导入）
    from DataPipeline.storage.repositories.fx_rates import SqliteFxRatesRepository

logger = logging.getLogger(__name__)

_BLOOMBERG_FIELD = "PX_LAST"

#: 最近已知 FX 汇率缓存（007-costview-report-filters）：
#: 末级回退（无日期维度，优先级低于 fx_rates 表的 ≤目标日期有界回退），
#: 避免 USD 成交额在暂停期被系统性低估。键为规范化大写 ccy_ticker。
_RECENT_RATES: dict[str, float] = {}


def _norm_key(ccy_ticker: str) -> str:
    """规范化 ccy_ticker 键（大写 + 去首尾空白）。"""
    return (ccy_ticker or "").upper().strip()


def _is_usd(ccy_ticker: str) -> bool:
    """USD（或空值/未知）无需换算，fx_rate 恒为 1.0。"""
    key = _norm_key(ccy_ticker)
    return not key or key in ("USD Curncy", "USD")


def _remember_rate(ccy_ticker: str, fx_rate: float) -> None:
    """记录最近一次成功拉取/回退的汇率（规范化键）。"""
    if fx_rate and fx_rate > 0:
        _RECENT_RATES[_norm_key(ccy_ticker)] = fx_rate


# ── Bloomberg 纯拉取 ────────────────────────────────────────────────────────


def _fetch_px_last(ccy_ticker: str, date_str: str) -> Optional[float]:
    """从 Bloomberg 拉取单日 PX_LAST 原始逆报价；空数据/非正值返回 None。

    xbbg 延迟导入，保持无 Bloomberg 环境下模块可导入。
    异常由调用方捕获统一走降级链。
    """
    from xbbg import blp

    dt = datetime.strptime(date_str, "%Y%m%d")
    df = blp.bdh(ccy_ticker, _BLOOMBERG_FIELD, dt, dt)
    if df is not None and not df.empty:
        raw_px = float(df.iloc[0, 0])
        if raw_px > 0:
            return raw_px
    return None


# ── fx_rates 表访问（容错：读失败视为 miss，写失败仅 warning） ───────────────


def _table_get_rate(
    fx_repo: Optional["SqliteFxRatesRepository"], ccy_ticker: str, date_str: str,
) -> Optional[float]:
    """查 fx_rates 表精确命中；repo 缺失/异常容错为 miss。"""
    if fx_repo is None:
        return None
    try:
        return fx_repo.get_rate(ccy_ticker, date_str)
    except Exception as exc:
        logger.warning("fx_rates 表查询失败（视为 miss）: %s @ %s: %s", ccy_ticker, date_str, exc)
        return None


def _table_get_rates(
    fx_repo: Optional["SqliteFxRatesRepository"],
    ccy_tickers: list[str],
    date_str: str,
) -> dict[str, float]:
    """批量查 fx_rates 表精确命中；repo 缺失/异常容错为空 dict。"""
    if fx_repo is None or not ccy_tickers:
        return {}
    try:
        return fx_repo.get_rates_for_date(ccy_tickers, date_str)
    except Exception as exc:
        logger.warning("fx_rates 表批量查询失败（视为全部 miss）@ %s: %s", date_str, exc)
        return {}


def _table_recent_rate(
    fx_repo: Optional["SqliteFxRatesRepository"], ccy_ticker: str, date_str: str,
) -> Optional[float]:
    """查 fx_rates 表 ≤目标日期 最近已知汇率；repo 缺失/异常容错为 miss。"""
    if fx_repo is None:
        return None
    try:
        return fx_repo.get_recent_rate(ccy_ticker, date_str)
    except Exception as exc:
        logger.warning("fx_rates 表回退查询失败（视为 miss）: %s @ %s: %s", ccy_ticker, date_str, exc)
        return None


def _table_upsert(
    fx_repo: Optional["SqliteFxRatesRepository"],
    ccy_ticker: str,
    date_str: str,
    fx_rate: float,
    px_last: Optional[float],
) -> None:
    """成功拉取值落表（source='bloomberg'）；写失败仅 warning 不阻断拉取链。"""
    if fx_repo is None:
        return
    try:
        fx_repo.upsert_rate(ccy_ticker, date_str, fx_rate, px_last, source="bloomberg")
    except Exception as exc:
        logger.warning("fx_rates 表写入失败（不阻断拉取链）: %s @ %s: %s", ccy_ticker, date_str, exc)


# ── 降级链：表有界回退 → 内存缓存 → 1.0 ────────────────────────────────────


def _degraded_rate(
    ccy_ticker: str,
    date_str: str,
    fx_repo: Optional["SqliteFxRatesRepository"] = None,
    reason: str = "",
) -> float:
    """降级链：fx_rates 表 ≤目标日期 回退 → _RECENT_RATES 内存缓存 → 1.0 兜底。

    表回退带日期上界（防回填旧日期时泄漏未来汇率），优先于无日期维度的
    内存缓存；降级值只返回不落表。
    """
    recent = _table_recent_rate(fx_repo, ccy_ticker, date_str)
    if recent is not None:
        logger.info("FX %s @ %s 降级（%s）: fx_rates 表回退 -> %s", ccy_ticker, date_str, reason, recent)
        _remember_rate(ccy_ticker, recent)
        return recent
    mem = _RECENT_RATES.get(_norm_key(ccy_ticker))
    if mem is not None:
        logger.info("FX %s @ %s 降级（%s）: 内存缓存回退 -> %s", ccy_ticker, date_str, reason, mem)
        return mem
    logger.info("FX %s @ %s 降级（%s）: 无可用回退，默认 1.0", ccy_ticker, date_str, reason)
    return 1.0


# ── 对外接口 ────────────────────────────────────────────────────────────────


def fetch_fx_rate_for_ccy(
    ccy_ticker: str,
    date_str: str,
    fx_repo: Optional["SqliteFxRatesRepository"] = None,
) -> float:
    """Fetch daily PX_LAST for a single ccy_ticker on a given date.

    Bloomberg returns inverse quotes for USD{ccy} Curncy, e.g.
    PX_LAST of "USDJPY Curncy" = 143.50 -> fx_rate = 1/143.50 = 0.00697.

    Returns fx_rate as USD per 1 unit of currency.
    Degradation policy (007 + fx-rate-persistence): on quota pause / fetch
    failure / missing data, fall back to fx_rates 表 ≤目标日期 最近已知值，
    then in-memory recent rate (not 1.0). Only USD (and unknown tickers)
    default to 1.0 (= no FX impact).
    """
    if _is_usd(ccy_ticker):
        return 1.0

    # ① 表精确命中：零配额消耗，先于 quota_pause 检查
    cached = _table_get_rate(fx_repo, ccy_ticker, date_str)
    if cached is not None:
        _remember_rate(ccy_ticker, cached)
        return cached

    # ② miss：额度暂停时不再消耗 Bloomberg 配额，直接走降级链
    if is_quota_paused():
        return _degraded_rate(ccy_ticker, date_str, fx_repo, reason="quota paused")

    try:
        raw_px = _fetch_px_last(ccy_ticker, date_str)
    except Exception as exc:
        return _degraded_rate(ccy_ticker, date_str, fx_repo, reason=f"fetch error: {exc}")

    if raw_px is None:
        return _degraded_rate(ccy_ticker, date_str, fx_repo, reason="no PX_LAST data")

    fx_rate = 1.0 / raw_px
    _remember_rate(ccy_ticker, fx_rate)
    _table_upsert(fx_repo, ccy_ticker, date_str, fx_rate, raw_px)
    return fx_rate


def fetch_fx_rates_for_date(
    ccy_tickers: list[str],
    date_str: str,
    fx_repo: Optional["SqliteFxRatesRepository"] = None,
) -> dict[str, float]:
    """Fetch daily PX_LAST for a list of ccy_tickers on a given date.

    Returns {ccy_ticker: fx_rate}. USD Curncy and unknown tickers
    default to 1.0 (= no FX impact on TCA).

    fx-rate-persistence: 注入 fx_repo 时先批量查表（单 SQL，命中零配额），
    仅 miss 币种逐个走拉取链。
    """
    results: dict[str, float] = {}
    non_usd: list[str] = []
    for ccy in ccy_tickers:
        if _is_usd(ccy):
            results[ccy] = 1.0
        else:
            non_usd.append(ccy)
    if not non_usd:
        return results

    # 批量查表：命中直接返回，miss 才走逐币种拉取链
    cached = _table_get_rates(fx_repo, non_usd, date_str)
    for ccy in non_usd:
        if ccy in cached:
            results[ccy] = cached[ccy]
            _remember_rate(ccy, cached[ccy])
        else:
            results[ccy] = fetch_fx_rate_for_ccy(ccy, date_str, fx_repo=fx_repo)
    return results


def fx_rates_to_dataframe(
    results: dict[str, float],
    date_str: str,
) -> pd.DataFrame:
    """Convert {ccy_ticker: fx_rate} dict to DataFrame with date column."""
    return pd.DataFrame([
        {"ccy_ticker": k, "fx_rate": v, "order_as_of_date": date_str}
        for k, v in results.items()
    ])
