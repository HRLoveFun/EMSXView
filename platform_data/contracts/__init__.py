"""Cross-module data contracts for the EMSX platform.

This package defines the **only legal** data types that may cross module
boundaries (ExecutionView ↔ CostView ↔ MarketView). Each contract is a
pure dataclass or constant — no business logic, no DB imports.

Ownership rule:
  - CostView owns the data; contracts are the projection it publishes.
  - Consumers (ExecutionView, MarketView) import from this package only.
  - When CostView's internal DTOs evolve, contracts are updated here with
    an explicit version bump so downstream breakage is caught early.
"""

# TCA / Scorecard contracts
# 2026-09-16 收敛：TcaOrderSummary / TcaRouteDetail 为 deprecated 类型，双仓库 AST 核查
# 确认零消费者 → 从包入口移除 re-export，**定义仍保留**在 tca_contracts.py，需要时按
# 显式子模块路径导入（from platform_data.contracts.tca_contracts import TcaOrderSummary）。
from .tca_contracts import (
    SCORECARD_COHORTS,
    ScorecardCohortMetrics,
    ScorecardFilters,
    ScorecardReport,
    TcaFilters,
    TcaOrderAggregate,
    TcaReport,
    TcaRouteSummary,
)

# Protocol interfaces
from .protocols import (
    ConfigProtocol,
    ConnectionManagerProtocol,
)

from .tca_service_protocol import (
    TcaQueryServiceProtocol,
)

# Market-view contracts
from .market_contracts import (
    BASELINE_MIN_DAYS,
    BASELINE_SCHEMA_VERSION,
    BASELINE_WINDOW_DAYS,
    COST_MODEL_VERSION,
    REGIME_SCHEMA_VERSION,
    EventFlag,
    MarketAlert,
    MarketBaseline,
    MarketCandidatePayload,
    MarketCandidateRow,
    MarketDailySnapshotRow,
    MarketRegimeState,
    MarketSnapshot,
    MarketSnapshotFilters,
    MarketSnapshotSort,
    MarketStockPool,
    OrderDifficulty,
)

# Intraday-feature contracts
from .intraday_contracts import (
    INTRADAY_BUCKET_OPTIONS,
    INTRADAY_DEFAULT_BUCKET_MINUTES,
    INTRADAY_MAX_TICKERS,
    IntradayFeatureBucket,
    IntradayFeatureSnapshot,
    IntradayTickerFeatures,
)

# Order-intent contracts（057 DL-01：EMSX 导出解析与 PM 意图映射）
from .order_intent_contracts import (
    INTENT_BENCHMARKS,
    INTENT_MAPPING_VERSION,
    INTENT_SOURCE_EMSX_EXPORT,
    BlotterOrderRow,
    OrderIntent,
    PreTradeOrderBoard,
    UnmatchedOrder,
)

# Order-split contracts（057 DL-17b/072：金额拆分、反向单、精确剩余量）
from .order_split import (
    DEFAULT_MAX_NOTIONAL_USD,
    ORDER_SPLIT_VERSION,
    AccountType,
    RemainingQuantity,
    ReverseOrderDecision,
    SplitLeg,
    SplitPlan,
    check_quantity_invariant,
    plan_notional_split,
    reverse_order_decision,
)

# Routing-decision contracts（057 DL-21/075：决策日志，影子方式）
from .routing_decision import (
    CONSTRAINT_MATRIX_VERSION,
    DECISION_SCHEMA_VERSION,
    MODE_ASSIST,
    MODE_SHADOW,
    DecisionCandidate,
    RoutingDecision,
)

# Param-strategy contracts（057 DL-18/074：意图驱动的参数规则）
from .param_strategy import (
    DEFAULT_LIMIT_SIGMA,
    HIGH_VOL_SIGMA,
    MIN_PARTICIPATION_PCT,
    PARAM_TEMPLATE_VERSION,
    THIN_PARTICIPATION_SCALE,
    ParameterPlan,
    build_parameter_plan,
    limit_sigma_multiple,
    participation_pct,
    session_window_minutes,
)

# Algo-params contracts（057 DL-17c/073：volume cap 与 release time）
from .algo_params import (
    ALGO_PARAMS_VERSION,
    DEFAULT_VOLUME_CAP_PARAM,
    MAX_VOLUME_CAP_EUR,
    MAX_VOLUME_CAP_NON_EUR,
    RELEASE_TIME_PARAM,
    VOLUME_CAP_PRECISION,
    allocate_volume_caps,
    check_release_time_present,
    check_volume_cap_present,
    max_cap_for,
    param_name_for,
    release_time_required,
)

# Access-policy contracts（057 DL-17a/071：准入白名单与整手检查）
from .access_policy import (
    ACCESS_POLICY_VERSION,
    BrokerMarketPolicy,
    FractionalSharePolicy,
    PolicyBundle,
    PolicyViolation,
    TraderMarketPolicy,
    TraderPortfolioPolicy,
    check_broker_market,
    check_odd_lot,
    check_trader_market,
    check_trader_portfolio,
)

# Exchange-session contracts（057 DL-03：交易所会话注册表）
from .exchange_session_contracts import (
    EARLY_CLOSE_AUCTION_EXCHANGES,
    HALF_DAY_CLOSE_OVERRIDES,
    MARKET_CODE_FOLDING,
    PIPELINE_CLOSING_AUCTION_SAMPLES,
    SESSION_REGISTRY,
    SESSION_REGISTRY_VERSION,
    TIME_BUCKET_MARKETS,
    ExchangeSession,
)

# Algo taxonomy contracts（057 DL-04：算法族与意图映射）
from .algo_taxonomy import (
    ALGO_FAMILIES,
    ALGO_TAXONOMY_VERSION,
    FAMILY_TO_COARSE,
    INTENT_TO_FAMILIES,
    KNOWN_PIPELINE_GAPS,
    STRATEGY_TYPE_MAP,
    STRATEGY_TYPE_RULES,
    classify_algo,
    coarse_group,
    coverage_of,
    intent_families,
    normalize_strategy_type,
)

# Strategy registry + external algo whitelist（057 DL-16）
from .strategy_registry import (
    REGISTRY_VERSION,
    STRATEGY_REGISTRY,
    WHITELIST_PATH_ENV,
    AlgoWhitelist,
    ComplianceResult,
    StrategySpec,
    compliance_check,
    default_params,
    is_algo_whitelisted,
    load_algo_whitelist,
    normalize_algo_name,
    resolve_family,
    validate_strategy_params,
)

# Intraday store contracts（057 DL-06：盘中库契约，勿与 intraday_contracts 日内特征混淆）
from .intraday_store_contracts import (
    CONSERVATION_AUDIT_RULE,
    INTRADAY_DB_FILE_TEMPLATE,
    INTRADAY_DIR_NAME,
    INTRADAY_MANIFEST_FILE_NAME,
    INTRADAY_RETENTION_DAYS,
    INTRADAY_STORE_VERSION,
    INTRADAY_TABLES,
    READ_ROUTE_RULE,
    TABLE_COLUMNS,
    DataFreshness,
    IntradayDatasetStatus,
    IntradayManifest,
)

# Execution-history contracts
from .execution_contracts import (
    ExecutionHistoryFillRow,
    ExecutionHistoryFillSnapshot,
    ExecutionHistoryOrderSummaryRow,
    ExecutionHistoryOrderSummarySnapshot,
    ExecutionHistoryRouteSummaryRow,
    ExecutionHistoryRouteSummarySnapshot,
)

# Handoff contracts
from .handoff_contracts import (
    HANDOFF_MAX_STRATEGY_PARAMS_BYTES,
    HANDOFF_SCHEMA_VERSION,
    MATURITY_BETA,
    MATURITY_GA,
    MATURITY_SCAFFOLD,
    SOURCE_MODULE_MATURITY,
    BrokerStrategyRecommendation,
    ExecutionCandidateHandoff,
    ExecutionPostTradeHandoff,
    HandoffMetadata,
    PreTradeBoardItem,
    _new_trace_id,
    _now_iso,
)

# Database constants (table names, computational constants)
from .db_constants import (
    BARS_PER_YEAR,
    BDIB_DAILY_SUMMARY_TABLE,
    RAW_BDIB_TABLE,
)
