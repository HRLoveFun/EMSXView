"""盘中库（intraday store）契约（057 DL-06）——纯数据，无 IO。

Ownership: platform_data 发布；Consumers: EMSXDataPipeline（唯一写入方，DL-07/08/09
按其仓库规范实施）、EMSXView 各模块（DL-07 就绪后经 data_access 只读适配器读）。

本契约是父计划 §4.0「联合开发流程」的「契约先行」产物：盘中库的分文件方式、
表名/列名、manifest 结构、provisional 语义与读侧路由规则在此冻结；管道侧 DDL
与之对齐并经 SchemaDriftGuard 校验（未登记漂移会在管道启动前阻断日更）。

注意：勿与既有 intraday_contracts.py（日内特征契约，MarketView 盘中钻取）混淆——
本文件管「盘中库存储结构」，彼文件管「日内特征查询结果」。
"""

from __future__ import annotations

from dataclasses import dataclass, field

# 契约版本：表结构/规则变更时升版（两仓同步）
INTRADAY_STORE_VERSION = "intraday-store-v1"

# ── 库文件与清单（父计划 §4.0 冻结条款） ──────────────────────────────────────
INTRADAY_DIR_NAME = "intraday"
INTRADAY_DB_FILE_TEMPLATE = "intraday_YYYYMMDD.db"  # 按交易日分文件
INTRADAY_MANIFEST_FILE_NAME = "intraday_manifest.json"  # 原子写

# 保留期：期满整文件清理（WRITE 层禁止 DELETE，不在库内删行；ADR-0023 记录调整条件）
INTRADAY_RETENTION_DAYS = 30

# 读侧路由与守恒审计规则（父计划 §4.0 冻结条款）
READ_ROUTE_RULE = "formal-first"  # 正式库已有该日就用正式数据，否则用盘中库
CONSERVATION_AUDIT_RULE = "diff-to-audit"  # 临时与正式差异进守恒审计（沿用已解释缺口机制）

# 6 张表名（父计划 §4.0 冻结条款，逐字一致）
INTRADAY_TABLES: tuple[str, ...] = (
    "intraday_fills",
    "blotter_snapshots",
    "order_intent",
    "route_params_snapshot",
    "bars_10s_t0",
    "snapshot_t0",
)

# 每张表的列名清单（管道侧 DDL 与之对齐；SchemaDriftGuard 校验基准）
TABLE_COLUMNS: dict[str, tuple[str, ...]] = {
    # J1：GetFills 增量经 S2 清洗 + S3 10 秒聚合产物（processed_fills 列子集）
    "intraday_fills": (
        "OrderId", "RouteId", "FillId", "order_as_of_date",
        "exchange_exec_time", "route_as_of_time",
        "Broker", "StrategyType", "algo", "Exchange", "equ_ticker", "Side",
        "FillShares", "FillPrice", "Amount", "Currency",
        "source_run_id", "ingested_at",
    ),
    # J1：EMSX 导出入库（每份导出 = 一条 snapshot 行；raw_row 留原文 JSON）
    "blotter_snapshots": (
        "export_ts", "file_name", "order_key",
        "code", "exch_code", "name", "side", "qty", "ccy", "status",
        "fill_qty", "pct_filled", "brkr_code", "create_time", "pm_note",
        "raw_row", "file_mtime",
    ),
    # J1：意图入库（DL-01 OrderIntent 契约的入库形态）
    "order_intent": (
        "order_key", "benchmark", "close_pct", "raw_note",
        "intent_source", "valid_from", "export_ts", "unmatched_reason",
        "mapping_version",
    ),
    # J1：运营库采集的路由参数时点快照
    "route_params_snapshot": (
        "order_id", "route_id", "sequence",
        "broker", "strategy_type", "algo", "param_json", "as_of",
    ),
    # J2：收盘后 bar（该市场当日 10 秒 bar，临时）
    "bars_10s_t0": (
        "equ_ticker", "order_as_of_date", "mkt_timestamp",
        "open", "high", "low", "close", "volume", "num_trds", "value",
        "source",
    ),
    # J2：当日快照（与 DL-09 bdib_market_snapshot 同函数产出，临时）
    "snapshot_t0": (
        "equ_ticker", "trade_date",
        "first_bar_time", "last_bar_time",
        "open", "high", "low", "close", "vwap", "volume", "value",
        "gap", "adv_ratio",
    ),
}


@dataclass(frozen=True)
class IntradayDatasetStatus:
    """manifest 每数据集条目（与管道 freshness SLA 同口径）。"""

    dataset: str
    as_of: str
    watermark: str
    row_count: int
    status: str
    last_error: str | None = None


@dataclass(frozen=True)
class IntradayManifest:
    """新鲜度清单（原子写；读侧据此判定盘中库可用性与滞后）。"""

    manifest_version: str
    generated_at: str
    trade_date: str
    datasets: list[IntradayDatasetStatus] = field(default_factory=list)


@dataclass(frozen=True)
class DataFreshness:
    """读侧新鲜度可见性契约（父计划 §4.1 输出契约预留项）。"""

    dataset: str
    as_of: str
    lag_minutes: float
