"""监控与报告共享服务层。

供 CostView 监控 API 与独立 HTML 报告脚本复用：
    time_range        — 互斥时间范围解析（--start/--end vs --last 预设）
    bdib_health       — BDIB 数据健康扫描（SQLite 热数据 + Parquet 分区双源）
    metric_coverage   — tca_route_summary 18 项计算指标覆盖率聚合
    report_aggregator — TCA 可视化报告聚合（KPI/分布/走势/排行/PWP）
"""

from .time_range import (
    LAST_PRESETS,
    TimeRange,
    fetch_latest_tca_date,
    resolve_time_range,
)
from .metric_coverage import (
    BDIB_DEPENDENT_METRICS,
    COMPUTED_METRICS,
    MetricCoverageService,
    validate_metrics,
)
from .bdib_health import BdibHealthService, BdibHealthStatus
from .report_aggregator import TcaReportAggregator

__all__ = [
    "LAST_PRESETS",
    "TimeRange",
    "fetch_latest_tca_date",
    "resolve_time_range",
    "BDIB_DEPENDENT_METRICS",
    "COMPUTED_METRICS",
    "MetricCoverageService",
    "validate_metrics",
    "BdibHealthService",
    "BdibHealthStatus",
    "TcaReportAggregator",
]
