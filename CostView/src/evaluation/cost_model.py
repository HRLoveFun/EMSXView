"""成本回归与市场冲击函数估计 —— 026 阶段三。

依据 `docs/textbook/Algo_TCA.md:116`：

> market impact costs are often estimated via **non-linear regression estimation**

采用经典幂律形式（取对数后线性化）：

```
impact_bps = a · participation^b · volatility^c
ln(impact) = ln(a) + b·ln(participation) + c·ln(volatility)
```

**与现有指标的区别（关键）**：`temp_impact_5min_bps` / `temp_impact_10min_bps` /
`temp_impact_30min_bps` / `perm_impact_bps` 是**逐路由的度量值**；本模块估计的是
**冲击函数**（成本对规模与波动的响应曲面），两者不可互相替代。

**禁项**：拟合值**不得**作为「事前成本预测」对外输出 —— K3（事前预测）明确不在
本计划范围（`docs/report-tca-known-limitations.md:16`）；`predict_bps` 仅用于诊断，
且**超出估计域一律返回 None**，不做外推。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Optional, Sequence

import numpy as np

#: 拟合所需最小样本量（低于此值不产出模型 —— 3 参数的幂律在小样本上不稳定）
DEFAULT_MIN_OBSERVATIONS: int = 30


@dataclass(frozen=True)
class ImpactModel:
    """幂律冲击模型的参数估计（含拟合优度与适用域）。"""

    intercept: float
    slope_participation: float
    slope_volatility: float
    n_observations: int
    r_squared: float
    #: 估计样本的 (参与率, 波动率) 取值域 —— 超出即不外推
    participation_domain: tuple[float, float]
    volatility_domain: tuple[float, float]
    note: str = ""

    def can_predict(self, participation: float, volatility: float) -> bool:
        """是否落在估计域内（域外一律不预测）。"""
        return (
            self.participation_domain[0] <= participation <= self.participation_domain[1]
            and self.volatility_domain[0] <= volatility <= self.volatility_domain[1]
        )

    def predict_bps(
        self, participation: float, volatility: float,
    ) -> Optional[float]:
        """模型内诊断值；**超出估计域返回 None**（不外推、不作事前预测）。"""
        if participation <= 0 or volatility <= 0:
            return None
        if not self.can_predict(participation, volatility):
            return None
        exponent = (
            self.intercept
            + self.slope_participation * math.log(participation)
            + self.slope_volatility * math.log(volatility)
        )
        return math.exp(exponent)

    def to_payload(self) -> dict[str, Any]:
        return {
            "intercept": self.intercept,
            "slope_participation": self.slope_participation,
            "slope_volatility": self.slope_volatility,
            "n_observations": self.n_observations,
            "r_squared": self.r_squared,
            "participation_domain": list(self.participation_domain),
            "volatility_domain": list(self.volatility_domain),
            "note": self.note,
        }


def _clean_samples(
    samples: Iterable[Sequence[Optional[float]]],
) -> list[tuple[float, float, float]]:
    """剔除非正 / 非有限样本（对数变换要求三项严格为正）。"""
    rows: list[tuple[float, float, float]] = []
    for sample in samples:
        values = list(sample)[:3]
        if len(values) < 3 or any(v is None for v in values):
            continue
        participation, volatility, impact = (float(v) for v in values)  # type: ignore[arg-type]
        if not all(math.isfinite(v) and v > 0 for v in (participation, volatility, impact)):
            continue
        rows.append((participation, volatility, impact))
    return rows


def fit_impact_model(
    samples: Iterable[Sequence[Optional[float]]],
    *,
    min_observations: int = DEFAULT_MIN_OBSERVATIONS,
) -> Optional[ImpactModel]:
    """拟合幂律冲击模型（对数空间 OLS）。

    Args:
        samples: ``(participation, volatility, impact_bps)`` 三元组序列。
        min_observations: 最小样本量；不足则返回 ``None``（不产出不可靠模型）。

    Returns:
        ``ImpactModel``，或样本不足时为 ``None``。
    """
    rows = _clean_samples(samples)
    if len(rows) < min_observations:
        return None

    log_impact = np.log([row[2] for row in rows])
    design = np.column_stack([
        np.ones(len(rows)),
        np.log([row[0] for row in rows]),
        np.log([row[1] for row in rows]),
    ])
    coefficients, *_ = np.linalg.lstsq(design, log_impact, rcond=None)

    fitted = design @ coefficients
    residual = float(((log_impact - fitted) ** 2).sum())
    total = float(((log_impact - log_impact.mean()) ** 2).sum())
    r_squared = 1.0 - residual / total if total else 0.0

    participations = [row[0] for row in rows]
    volatilities = [row[1] for row in rows]
    return ImpactModel(
        intercept=round(float(coefficients[0]), 6),
        slope_participation=round(float(coefficients[1]), 6),
        slope_volatility=round(float(coefficients[2]), 6),
        n_observations=len(rows),
        r_squared=round(r_squared, 4),
        participation_domain=(min(participations), max(participations)),
        volatility_domain=(min(volatilities), max(volatilities)),
        note="对数空间 OLS 拟合；域外不外推，且不作为事前成本预测（K3 不在本计划范围）",
    )
