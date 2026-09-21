"""样本功效与最小可检测效应 —— 026 阶段三。

实现口径：**正态近似闭式公式**，不引入 `statsmodels`（DP-3-1 明确只引入 `scipy`）。

```
n_per_group = 2 (z_{1-α/2} + z_{1-β})² σ² / Δ²
```

与既有「人为门槛」的关系：`min_sample_size`（默认 10）与排行双维门槛（n ≥ 5）是
**人为阈值**；本模块给出**统计依据**，报告中并列呈现二者差异（plan §5.5）——
样本不足时应给出「还差多少」，而不是只给一个不通过判词。
"""

from __future__ import annotations

import math

from scipy import stats as _stats

#: 默认显著性水平 / 目标功效（行业常规，可由调用方覆盖）
DEFAULT_ALPHA: float = 0.05
DEFAULT_POWER: float = 0.8


def _z(probability: float, name: str) -> float:
    if not 0 < probability < 1:
        raise ValueError(f"{name} 必须落在 (0, 1)，收到 {probability!r}")
    return float(_stats.norm.ppf(probability))


def required_sample_per_group(
    effect_size: float,
    *,
    alpha: float = DEFAULT_ALPHA,
    power: float = DEFAULT_POWER,
    stddev: float = 1.0,
) -> int:
    """两组均值比较所需**每组**样本量（正态近似，向上取整）。

    Args:
        effect_size: 待检测的均值差 Δ（与 ``stddev`` 同量纲，必须为正）。
        alpha: 显著性水平（双侧）。
        power: 目标功效 1-β。
        stddev: 组内标准差 σ。

    Raises:
        ValueError: ``effect_size`` 非正，或 alpha / power 越界。
    """
    if effect_size <= 0:
        raise ValueError("effect_size 必须为正：无可检测差异时样本量无定义")
    if stddev <= 0:
        raise ValueError("stddev 必须为正")
    z_alpha = _z(1 - alpha / 2, "alpha")
    z_beta = _z(power, "power")
    return int(math.ceil(2 * (z_alpha + z_beta) ** 2 * stddev ** 2 / effect_size ** 2))


def achieved_power(
    n_per_group: int,
    effect_size: float,
    *,
    alpha: float = DEFAULT_ALPHA,
    stddev: float = 1.0,
) -> float:
    """给定每组样本量能达到的功效（与 ``required_sample_per_group`` 互逆）。

    用于回答「现有数据够不够下结论」，而非只给通过 / 不通过的判词。
    """
    if n_per_group <= 0:
        raise ValueError("n_per_group 必须为正")
    if effect_size <= 0:
        raise ValueError("effect_size 必须为正")
    if stddev <= 0:
        raise ValueError("stddev 必须为正")
    z_alpha = _z(1 - alpha / 2, "alpha")
    noncentral = effect_size / (stddev * math.sqrt(2 / n_per_group))
    return float(_stats.norm.cdf(noncentral - z_alpha))


def minimum_detectable_effect(
    n_per_group: int,
    *,
    alpha: float = DEFAULT_ALPHA,
    power: float = DEFAULT_POWER,
    stddev: float = 1.0,
) -> float:
    """给定样本量下**可检测的最小效应**（MDE）。

    样本不足时的可执行指引：与其说「样本不够」，不如说「以当前样本量，只有大于
    该幅度的差异才可能被检出」。
    """
    if n_per_group <= 0:
        raise ValueError("n_per_group 必须为正")
    if stddev <= 0:
        raise ValueError("stddev 必须为正")
    z_alpha = _z(1 - alpha / 2, "alpha")
    z_beta = _z(power, "power")
    return float((z_alpha + z_beta) * stddev * math.sqrt(2 / n_per_group))


def power_summary(
    n_per_group: int,
    effect_size: float,
    *,
    alpha: float = DEFAULT_ALPHA,
    power: float = DEFAULT_POWER,
    stddev: float = 1.0,
) -> dict[str, object]:
    """一次给出「是否足够 / 还差多少 / 可检测下限」三项，供报告直接展示。"""
    required = required_sample_per_group(
        effect_size, alpha=alpha, power=power, stddev=stddev,
    )
    achieved = achieved_power(n_per_group, effect_size, alpha=alpha, stddev=stddev)
    return {
        "n_per_group": n_per_group,
        "required_per_group": required,
        "shortfall": max(0, required - n_per_group),
        "achieved_power": round(achieved, 4),
        "target_power": power,
        "sufficient": achieved >= power,
        "minimum_detectable_effect": round(
            minimum_detectable_effect(
                n_per_group, alpha=alpha, power=power, stddev=stddev,
            ),
            6,
        ),
    }
