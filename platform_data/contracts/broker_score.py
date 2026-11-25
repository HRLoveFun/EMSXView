"""BrokerScoreSnapshot 契约（057 DL-24/217）——纯数据，无 IO。

只出**分项**：成本、尾部风险、完成率、机会成本、信息泄露、运营质量。
综合评分按 D-5 不排期：`weights`/`composite` 保留字段，默认空/None，
任何消费方不得把空权重当 0 加权。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

#: 快照 schema 版本（字段结构变更时升版）
BROKER_SCORE_VERSION = "broker-score-v1"

#: 分项名称（顺序即展示顺序）
SCORE_COMPONENTS: tuple[str, ...] = (
    "cost",
    "tail_risk",
    "completion",
    "opportunity_cost",
    "leakage",
    "operational",
)


@dataclass(frozen=True)
class ScoreComponent:
    """单个分项得分；`available=False` 时 `value` 必须为 None（不填 0）。"""

    name: str
    value: Optional[float]
    unit: str
    sample_size: int
    available: bool
    note: str = ""


@dataclass(frozen=True)
class BrokerScoreSnapshot:
    """单个券商在给定窗口内的分项得分快照（不可变）。"""

    broker: str
    as_of: str
    window_start: str
    window_end: str
    spec_version: str = BROKER_SCORE_VERSION
    components: tuple[ScoreComponent, ...] = ()
    #: 综合评分权重与版本（D-5 预留；默认空，不合成）
    weights: dict = field(default_factory=dict)
    composite: Optional[float] = None
    #: CUSUM 漂移：{up_peak, down_peak, alert, direction, days}
    cusum: dict = field(default_factory=dict)
    #: 错位期样本（缺交易日/缺成本）单列，不参与分项
    misaligned_samples: int = 0
    #: 单元样本不足（DL-23 MIN_UNIT_SAMPLE）
    low_sample: bool = False
