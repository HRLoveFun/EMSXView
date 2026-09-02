"""Single source of truth for all EMSXView pipeline configuration.

Usage::

    from DataPipeline.config import Config

    path = Config.RAW_FILLS_DB
    date_fmt = Config.DATE_FORMAT
    table = Config.PROCESSED_FILLS_TABLE

Data directory resolution (009-external-data-store):

1. ``EMSXVIEW_DATA_DIR`` environment variable (explicit override, wins).
2. Default: project-external ``~/EMSXViewData/data`` — 数据库与代码树解耦，
   worktree/重新 clone 后数据不再丢失。

Legacy layout ``{PROJECT_ROOT}/CostView/data`` is only used when the caller
explicitly sets ``EMSXVIEW_DATA_DIR`` to it. If the legacy directory still
holds ``*.db`` files while the resolved default directory is used, a
``UserWarning`` is emitted at import time to prompt running
``scripts/ops/migrate_data_dir.py``.
"""

from __future__ import annotations

import os
import warnings
from pathlib import Path

import numpy as np

# ═══════════════════════════════════════════════════════════════════════════
# 数据管理重构: 功能开关 (见 data_management_refactoring_plan.md §7.2)
# ═══════════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════════
# DATABASE KEYS (used by ConnectionManager)
# ═══════════════════════════════════════════════════════════════════════════

DB_RAW_FILLS = "raw_fills"
DB_PROCESSED_FILLS = "processed_fills"
DB_RAW_BDIB = "raw_bdib"
DB_PROCESSED_RAW_BDIB = "processed_raw_bdib"
DB_FILL_BDIB = "fill_bdib"
DB_REGIME = "regime"
DB_FETCH_HISTORY = "fill_fetch_history"
DB_BDIB_FETCH_HISTORY = "bdib_fetch_history"
DB_EXECUTION_HISTORY = "execution_history"
DB_TICKER_REGISTRY = "ticker_registry"


class Config:
    _PROJECT_ROOT: Path = Path(__file__).resolve().parents[1]

    # ── 数据目录解析（009-external-data-store）────────────────────────────
    # 优先级：EMSXVIEW_DATA_DIR 环境变量 > 项目外默认值 ~/EMSXViewData/data。
    # 旧布局 {PROJECT_ROOT}/CostView/data 仅在显式设置环境变量指回时生效。
    DEFAULT_DATA_DIR: Path = Path.home() / "EMSXViewData" / "data"
    LEGACY_DATA_DIR: Path = _PROJECT_ROOT / "CostView" / "data"
    DATA_DIR: Path = Path(os.getenv("EMSXVIEW_DATA_DIR", str(DEFAULT_DATA_DIR)))
    LOGGING_DIR: Path = _PROJECT_ROOT / "logs" / "pipeline"

    FETCH_HISTORY_DB: Path = DATA_DIR / "fill_fetch_history.db"
    BDIB_FETCH_HISTORY_DB: Path = DATA_DIR / "bdib_fetch_history.db"
    RAW_FILLS_DB: Path = DATA_DIR / "raw_fills.db"
    PROCESSED_FILLS_DB: Path = DATA_DIR / "processed_fills.db"
    RAW_BDIB_DB: Path = DATA_DIR / "raw_bdib.db"
    PROCESSED_RAW_BDIB_DB: Path = DATA_DIR / "processed_raw_bdib.db"
    FILL_BDIB_DB: Path = DATA_DIR / "fill_bdib.db"
    EXECUTION_HISTORY_DB: Path = DATA_DIR / "execution_history.db"
    TICKER_REGISTRY_DB: Path = DATA_DIR / "ticker_registry.db"

    LOG_FILE: Path = LOGGING_DIR / "fillfetch.log"
    LOG_DEBUG_FILE: Path = LOGGING_DIR / "fillfetch_debug.log"
    MARKET_FETCH_MANIFEST: Path = DATA_DIR / "market_fetch_manifest.json"
    OUTDATED_TICKERS_FILE: Path = DATA_DIR / "outdated_tickers.json"
    PERMANENT_GAP_DATES_FILE: Path = DATA_DIR / "permanent_gap_dates.json"
    # Bloomberg 额度爆满暂停标记（005-bloomberg-quota-pause）
    # 命中额度类错误/预期有数据但拉取为空时置位，各拉取入口短路；恢复后清除。
    QUOTA_PAUSE_FILE: Path = DATA_DIR / "quota_pause.json"

    DATE_FORMAT: str = "%Y%m%d"
    DATE_FORMAT_DASH: str = "%Y-%m-%d"
    TIME_FORMAT: str = "%H:%M:%S"
    DATETIME_FORMAT: str = "%Y-%m-%d %H:%M:%S"
    EMSX_DATETIME_FORMATS: list = [
        "%Y-%m-%d %H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%d %H:%M:%S%z",    "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S.%f",   "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",      "%Y-%m-%dT%H:%M:%S",
    ]

    LOG_FORMAT: str = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    LOG_DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"

    FLOAT_TYPE: type = np.float32
    INT_TYPE: type = np.int32
    EXECTYPE_FILTER_OUT: set = {"DFD"}
    FIRST_RUN_LOOKBACK_DAYS: int = 60
    BDIB_EXCHANGE: list[str] = [
        "AU", "AV", "BB", "FH", "FP", "GA", "GR", "HK", "ID", "IJ", "IM",
        "IN", "JP", "KS", "LN", "MK", "NA", "NO", "PL", "SJ", "SM",
        "SP", "SS", "SW", "US",
        # ── 2026-07-16 调整：2026-07-08 曾临时补齐 9 个交易所（424 个 ticker 无 BDIB 行情）。
        # 业务决定仅保留 HK（香港 HKEX）进入分析范围；以下 8 个市场的订单不在分析范围，
        # 从白名单移除：CN（加拿大 TSX）、BZ（巴西 B3）、MM（墨西哥 BMV）、PW（波兰 WSE）、
        # DC（丹麦 Nasdaq Copenhagen）、IT（以色列 TASE）、NZ（新西兰 NZX）、
        # MUMBAI（印度 BSE）。这些 ticker 在 S2 阶段会被排除，不再拉取 BDIB 行情、
        # 也不进入 processed_fills / fill_bdib。
        # ── 2026-08-03 调整：新增 C1（Nth SSE-SEHK，沪港通），其行情代码映射为 CH。
        "C1",
    ]

    # ── 报告市场配置（007-costview-report-filters）─────────────────────────
    # HTML 报告 / 前端分市场标签页的市场顺序与白名单（唯一真相源）。
    # 键为 Bloomberg Exchange 代码（与 tca_route_summary.Exchange 一致），
    # 值为显示名。仅列出的市场会出现在报告标签页；未列出的 Exchange 归入"其他"。
    # 顺序即标签页展示顺序（常用优先）。
    MARKET_ORDER: dict[str, str] = {
        "US": "美国",
        "JP": "日本",
        "LN": "伦敦",
        "HK": "香港",
        "C1": "沪港通",
        "AU": "澳洲",
        "GR": "德国",
        "IN": "印度",
        "CN": "加拿大",
        "FP": "法国",
        "SW": "瑞士",
        "SS": "瑞典",
        "KS": "韩国",
        "NA": "荷兰",
        "IM": "意大利",
        "SM": "西班牙",
        "BZ": "巴西",
        "DC": "丹麦",
        "FH": "芬兰",
        "SP": "新加坡",
        "BB": "比利时",
        "SJ": "南非",
        "NO": "挪威",
        "IJ": "印尼",
        "MM": "墨西哥",
        "MK": "马来西亚",
        "AV": "奥地利",
        "PL": "葡萄牙",
        "PW": "波兰",
        "ID": "爱尔兰",
        "IT": "以色列",
        "GA": "希腊",
        "NZ": "新西兰",
        "MUMBAI": "印度孟买",
    }

    MAX_PARALLEL_DATES: int = 1
    MAX_PARALLEL_TICKERS: int = 1
    SQLITE_CONNECT_TIMEOUT_SEC: int = 30
    SQLITE_BUSY_TIMEOUT_MS: int = 30_000
    BDIB_LATEST_READY_HOUR_LOCAL: int = 8
    # BBG EU_COMPOSITE_TICKER 查询超时（秒），防止 blp.bdp() 无限挂起
    BBG_COMPOSITE_QUERY_TIMEOUT_SEC: int = 45

    # ── 数据管理重构: BDIB存储引擎 (Phase A) ──
    BDIB_PARQUET_ENABLED: bool = os.getenv("BDIB_PARQUET_ENABLED", "0") == "1"
    BDIB_QUERY_ENGINE: str = os.getenv("BDIB_QUERY_ENGINE", "duckdb")
    BDIB_PARQUET_DIR: Path = DATA_DIR / "market" / "bdib_10s"
    BDIB_HOT_RETENTION_MONTHS: int = int(os.getenv("BDIB_HOT_RETENTION_MONTHS", "3"))

    # Bloomberg BDIB API 历史数据保留窗口（天）
    # US/LN/JP/KS 等主要市场约 9 个月，HK/NZ/CN/BZ 等市场约 6 个月
    # 取最保守值 180 天（6 个月），确保所有市场都在窗口内
    BDIB_API_RETENTION_DAYS: int = 180

    # 新鲜度 SLA（M2.2, docs/spec/pipeline-resilience.md）
    # 以「交易日（工作日）」为计量单位（规避周末误判）：核心库最新交易日与
    # today 之间缺失的交易日数超过阈值即视为数据缺失：
    # - WARN_BUSINESS_DAYS: 仅告警并记录进 summary（用于人工排查，如长周末）
    # - FAIL_BUSINESS_DAYS: 升级为日更最终状态失败（status=failed + exit 1），
    #   配额暂停期间（is_quota_paused）跳过，避免合法跳过被误判
    FRESHNESS_WARN_BUSINESS_DAYS: int = int(os.getenv("FRESHNESS_WARN_BUSINESS_DAYS", "1"))
    FRESHNESS_FAIL_BUSINESS_DAYS: int = int(os.getenv("FRESHNESS_FAIL_BUSINESS_DAYS", "2"))

    # ── 数据管理重构: 分区双写/读 (Phase B) ──
    PARTITION_DUAL_WRITE: bool = os.getenv("PARTITION_DUAL_WRITE", "0") == "1"
    PARTITION_READ_NEW: bool = os.getenv("PARTITION_READ_NEW", "0") == "1"
    DB_EXECUTION_HISTORY: str = "execution_history"
    DB_TICKER_REGISTRY: str = "ticker_registry"

    # ── 数据管理重构: processed_raw_bdib退役 (Phase A8 观察期已通过 2026-06-15) ──
    # 衍生字段 (vwap, fluctuation, log_chg_pct_10s) 通过 compute_derived_fields() 内存计算
    # 可重现性验证 0.0429% (< 0.1% 阈值), 观察期 6 天 all_pass, 见 retire_a8_*.log
    # 重新启用需: env PROCESSED_RAW_BDIB_ENABLED=1
    PROCESSED_RAW_BDIB_ENABLED: bool = (
        os.getenv("PROCESSED_RAW_BDIB_ENABLED", "0") == "1"
    )

    LOG_RETENTION_DAYS: int = 30
    LOG_DEBUG_RETENTION_DAYS: int = 7

    # ── 管道护栏机制 (GuardPipeline) ──
    # 护栏总开关，设为 False 可完全关闭所有护栏行为
    GUARDRAIL_ENABLED: bool = os.getenv("GUARDRAIL_ENABLED", "1") == "1"
    # 连续失败触发熔断的阈值（Error 级异常累计 N 次后 OPEN）
    GUARDRAIL_CIRCUIT_BREAKER_THRESHOLD: int = int(
        os.getenv("GUARDRAIL_CIRCUIT_BREAKER_THRESHOLD", "3")
    )
    # S1 外部数据摄入最大重试次数
    GUARDRAIL_RETRY_MAX: int = int(os.getenv("GUARDRAIL_RETRY_MAX", "3"))
    # 护栏日志目录（JSONL 文件存放位置）
    GUARDRAIL_LOG_DIR: Path = Path(
        os.getenv("GUARDRAIL_LOG_DIR", str(LOGGING_DIR / "guardrail"))
    )
    # 基线快照目录（用于管道完整性对比测试）
    GUARDRAIL_BASELINE_DIR: Path = Path(
        os.getenv("GUARDRAIL_BASELINE_DIR", str(Path(__file__).resolve().parent / "tests" / "baselines"))
    )
    # 全局严格模式开关（False 时所有阶段使用宽松策略）
    GUARDRAIL_VALIDATION_STRICT_MODE: bool = (
        os.getenv("GUARDRAIL_VALIDATION_STRICT_MODE", "1") == "1"
    )
    # 空数据集处理策略："reject" 拒绝空数据通过，"accept" 接受空数据
    GUARDRAIL_EMPTY_DATASET_POLICY: str = os.getenv(
        "GUARDRAIL_EMPTY_DATASET_POLICY", "reject"
    )
    # 校验降级开关：启用时校验规则异常仅记录 WARNING 日志后放行，不拒绝入库
    GUARDRAIL_VALIDATION_BYPASS_ON_ERROR: bool = (
        os.getenv("GUARDRAIL_VALIDATION_BYPASS_ON_ERROR", "0") == "1"
    )
    # 缺失 Ticker/Exchange 时是否直接报错（用于 S2 阶段阻止空 equ_ticker 流入下游）
    STRICT_MISSING_TICKER_VALIDATION: bool = (
        os.getenv("STRICT_MISSING_TICKER_VALIDATION", "0") == "1"
    )

    # ── TCA 核心指标补全 (003-tca-core-benchmarks) ──
    # Phase 0: 核心基准（到达价/收盘价/机会成本），默认开启（可经环境变量即时回退为 0）
    TCA_CORE_BENCHMARKS_ENABLED: bool = (
        os.getenv("TCA_CORE_BENCHMARKS_ENABLED", "1") == "1"
    )
    # Phase 1: Wagner IS 分解 + 风险维度 + 冲击分解，默认开启
    TCA_RISK_IMPACT_ENABLED: bool = (
        os.getenv("TCA_RISK_IMPACT_ENABLED", "1") == "1"
    )
    # Phase 2: route→order 聚合视图/API，默认关闭
    TCA_ORDER_AGG_ENABLED: bool = (
        os.getenv("TCA_ORDER_AGG_ENABLED", "0") == "1"
    )

    EXECUTION_HISTORY_SOURCE_POLICY: dict[str, tuple[str, ...]] = {
        "fills": ("emsx.history:GetFills",),
        "orders": ("costview.fill-rollup", "executionview.orders_projection"),
        "routes": ("costview.fill-rollup", "executionview.routes_projection"),
        "route_events": ("emsx.history:GetFills", "executionview.audit_events"),
    }
    EXECUTION_HISTORY_REFRESH_POLICY: dict[str, str] = {
        "fills": "incremental-per-fetch",
        "orders": "rebuild-per-processed-date;patch-from-executionview-when-available",
        "routes": "rebuild-per-processed-date;patch-from-executionview-when-available",
        "route_events": "append-per-fill;patch-from-executionview-audit-when-available",
    }

    RAW_FILLS_TABLE: str = "raw_fills"
    PROCESSED_FILLS_TABLE: str = "processed_fills"
    AGG_10S_TABLE: str = "agg_fills_10s"
    AGG_1MIN_TABLE: str = "agg_fills_1min"
    ORDER_HISTORY_TABLE: str = "order_history"
    ROUTE_HISTORY_TABLE: str = "route_history"
    ROUTE_EVENT_HISTORY_TABLE: str = "route_event_history"
    RAW_BDIB_TABLE: str = "raw_bdib"
    BDIB_DAILY_SUMMARY_TABLE: str = "bdib_daily_summary"
    PROCESSED_RAW_BDIB_TABLE: str = "processed_raw_bdib"
    FILL_BDIB_TABLE: str = "fill_bdib"
    TCA_ROUTE_SUMMARY_TABLE: str = "tca_route_summary"
    # 报告筛选维度持久化列表（存于 fill_bdib.db）：市场/Broker/Algo/Symbol 全量值，
    # 由 daily_update 每日增量刷新，report 查询不再按时间范围对明细表 GROUP BY。
    TCA_REPORT_DIMS_TABLE: str = "tca_report_dims"
    TCA_REPORT_DIMS_META_TABLE: str = "tca_report_dims_meta"
    # fx-rate-persistence: 币种 × 交易日汇率唯一真相源（存于 fill_bdib.db）
    FX_RATES_TABLE: str = "fx_rates"
    AGG_PROCESSED_FILLS_TABLE: str = "agg_processed_fills"
    PROCESSED_FILLS_1MIN_TABLE: str = "processed_fills_1min"
    ORDER_LABEL_TABLE: str = "order_label"
    PROCESSING_LOG_TABLE: str = "processing_log"
    TICKER_DATE_MAPPING_TABLE: str = "ticker_date_mapping"
    EQU_TICKER_REGISTRY_TABLE: str = "equ_ticker_registry"
    CCY_TICKER_REGISTRY_TABLE: str = "ccy_ticker_registry"
    ORDER_FETCH_LOG_TABLE: str = "order_fetch_log"
    FETCH_LOG_TABLE: str = "fetch_log"
    INGESTION_LOG_TABLE: str = "ingestion_log"
    FETCH_HISTORY_TABLE: str = "fill_fetch_history"
    BDIB_FETCH_HISTORY_TABLE: str = "bdib_fetch_history"

    @classmethod
    def initialize_directories(cls) -> None:
        directories = [cls.DATA_DIR, cls.LOGGING_DIR]
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)


def _validate_config() -> None:
    """校验关键配置参数边界 (M6)。

    非法值在模块导入时即抛 ValueError — 配置错误 fail-fast,
    禁止静默降级 (如非法 BDIB_QUERY_ENGINE 静默走 sqlite 分支)。
    """
    engine = Config.BDIB_QUERY_ENGINE.strip().lower()
    if engine not in ("sqlite", "duckdb"):
        raise ValueError(
            f"BDIB_QUERY_ENGINE 非法值: {Config.BDIB_QUERY_ENGINE!r} "
            f"(允许: sqlite, duckdb)"
        )
    Config.BDIB_QUERY_ENGINE = engine  # 归一化大小写

    if Config.BDIB_HOT_RETENTION_MONTHS < 1:
        raise ValueError(
            f"BDIB_HOT_RETENTION_MONTHS 必须 >= 1, "
            f"收到 {Config.BDIB_HOT_RETENTION_MONTHS}"
        )
    if Config.BDIB_API_RETENTION_DAYS < 1:
        raise ValueError(
            f"BDIB_API_RETENTION_DAYS 必须 >= 1, 收到 {Config.BDIB_API_RETENTION_DAYS}"
        )
    if Config.GUARDRAIL_EMPTY_DATASET_POLICY not in ("reject", "accept"):
        raise ValueError(
            f"GUARDRAIL_EMPTY_DATASET_POLICY 非法值: "
            f"{Config.GUARDRAIL_EMPTY_DATASET_POLICY!r} (允许: reject, accept)"
        )
    if Config.GUARDRAIL_CIRCUIT_BREAKER_THRESHOLD < 1:
        raise ValueError(
            f"GUARDRAIL_CIRCUIT_BREAKER_THRESHOLD 必须 >= 1, "
            f"收到 {Config.GUARDRAIL_CIRCUIT_BREAKER_THRESHOLD}"
        )


def _warn_legacy_data_dir() -> None:
    """旧项目内数据目录仍有数据库文件时提示迁移 (009-external-data-store)。

    仅告警不阻塞 (fail-visible 而非 fail-hard)：
    - 调用方显式设置 EMSXVIEW_DATA_DIR 指回旧目录 → 尊重选择，不告警；
    - 旧目录存在但已无 *.db 文件（已迁移/清理）→ 不告警；
    - 旧目录仍有 *.db 且当前走项目外默认值 → 提示运行迁移脚本。
    """
    if Config.DATA_DIR == Config.LEGACY_DATA_DIR:
        return
    if not Config.LEGACY_DATA_DIR.is_dir():
        return
    legacy_dbs = list(Config.LEGACY_DATA_DIR.glob("*.db"))
    if not legacy_dbs:
        return
    warnings.warn(
        f"检测到旧数据目录 {Config.LEGACY_DATA_DIR} 仍包含 {len(legacy_dbs)} 个数据库文件"
        f"（如 {legacy_dbs[0].name}），而当前数据目录为 {Config.DATA_DIR}。"
        f"若为首次升级，请运行: python scripts/ops/migrate_data_dir.py --dry-run "
        f"(009-external-data-store, 详见 specs/009-external-data-store/plan.md)",
        UserWarning,
        stacklevel=2,
    )


_validate_config()
_warn_legacy_data_dir()
