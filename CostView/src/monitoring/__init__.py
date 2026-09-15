"""监控与报告共享服务层。

供 CostView 监控 API 与独立 HTML 报告脚本复用：
    time_range        — 互斥时间范围解析（--start/--end vs --last 预设）
    bdib_health       — BDIB 数据健康扫描（SQLite 热数据 + Parquet 分区双源）
    metric_coverage   — tca_route_summary 38 项计算指标覆盖率聚合
    report_measure    — 报告口径实现唯一来源（作用域/加权与覆盖/订单级聚合/金额回退）
    report_spec       — 报告口径声明唯一来源（脚注、版本号与测试断言的事实源）
    report_aggregator — TCA 可视化报告聚合（KPI/分布/走势/排行/PWP/冲击/异常明细）
    tca_report_html   — 自包含 HTML 报告渲染器（内联 CSS + SVG 图表，零外部依赖）
    anomaly_query     — 异常路由判定查询与阈值参数化（DEFAULT_THRESHOLDS）
    report_dims       — 报告筛选维度表读取（写侧刷新已随数据管道迁独立项目）

``__all__`` 必须与上方 import 严格对应（由 test_monitoring 的导出清单护栏守住）：
维度表写侧符号（DIM_COLUMNS / ensure_schema / refresh_dim_values）随 010-extract-pipeline
迁出本仓库，不得再出现在导出列表中。
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
    export_anomaly_rows_csv,
    get_default_thresholds,
    query_anomaly_routes,
    query_anomaly_routes_page,
    query_anomaly_routes_page_ex,
)
from .report_measure import (
    ReportScope,
    resolve_scope,
)
from .report_dims import (
    get_filter_options,
)
from .report_spec import REPORT_SPEC, SPEC_VERSION, footer_text

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
    "query_anomaly_routes_page",
    "query_anomaly_routes_page_ex",
    "export_anomaly_rows_csv",
    "ReportScope",
    "resolve_scope",
    "get_filter_options",
    "REPORT_SPEC",
    "SPEC_VERSION",
    "footer_text",
]
