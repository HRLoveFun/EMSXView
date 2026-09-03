"""监控与报告共享服务层。

供 CostView 监控 API 与独立 HTML 报告脚本复用：
    time_range        — 互斥时间范围解析（--start/--end vs --last 预设）
    bdib_health       — BDIB 数据健康扫描（SQLite 热数据 + Parquet 分区双源）
    metric_coverage   — tca_route_summary 38 项计算指标覆盖率聚合
    report_aggregator — TCA 可视化报告聚合（KPI/分布/走势/排行/PWP/冲击/异常明细）
    tca_report_html   — 自包含 HTML 报告渲染器（内联 CSS + SVG 图表，零外部依赖）
    anomaly_query     — 异常路由判定查询与阈值参数化（DEFAULT_THRESHOLDS）
    report_dims       — 报告筛选维度持久化列表（市场/Broker/Algo/Symbol 刷新与读取）
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
from .bdib_health import BdibHealthService, BdibHealthStatus, get_health_safe
from .report_aggregator import TcaReportAggregator
from .tca_report_html import render_report_html
from .anomaly_query import (
    ANOMALY_RULE_META,
    DEFAULT_THRESHOLDS,
    AnomalyRoute,
    ThresholdRules,
    evaluate_route_thresholds,
    get_default_thresholds,
    query_anomaly_routes,
)
from .report_dims import (
    get_filter_options,
)

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
    "get_health_safe",
    "TcaReportAggregator",
    "render_report_html",
    "DEFAULT_THRESHOLDS",
    "AnomalyRoute",
    "ThresholdRules",
    "evaluate_route_thresholds",
    "get_default_thresholds",
    "ANOMALY_RULE_META",
    "query_anomaly_routes",
    "DIM_COLUMNS",
    "ensure_schema",
    "get_filter_options",
    "refresh_dim_values",
]
