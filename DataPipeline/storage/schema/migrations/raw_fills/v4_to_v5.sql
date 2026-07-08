-- Migration: raw_fills v4 -> v5
-- 将 Amount/FillPrice/FillShares/RouteShares 列类型从 TEXT 升级为数值类型
-- ═══════════════════════════════════════════════════════════════════════
--
-- 背景：
--   raw_fills 表中 4 个数值列历史上定义为 TEXT，导致数值比较/聚合需运行时 CAST，
--   且无法利用 SQLite 类型亲和性优化存储。
--   v1_to_v2 已迁移 LimitPrice/StopPrice，本迁移补齐剩余 4 列。
--
-- 类型变更：
--   Amount      TEXT → REAL   (订单总股数)
--   FillPrice   TEXT → REAL   (成交价)
--   FillShares  TEXT → INTEGER (成交股数)
--   RouteShares TEXT → INTEGER (路由股数)
--
-- 安全保障：
--   1. 空字符串 → NULL（避免 '' 被 SQLite 类型亲和转为 0）
--   2. 索引重建（DROP TABLE 连带删除索引）
--   3. 单事务包裹，全成功或全回滚
--
-- 执行前校验（操作者应确认）：
--   SELECT COUNT(*) FROM raw_fills
--   WHERE FillPrice IS NOT NULL AND TRIM(FillPrice) != ''
--     AND CAST(FillPrice AS REAL) IS NULL;
--   期望: 0（无无法转为 REAL 的脏数据）
--
-- 执行方式（维护窗口，需停管道）：
--   sqlite3 raw_fills.db < v4_to_v5.sql

BEGIN;

CREATE TABLE IF NOT EXISTS raw_fills_new (
    OrderId               TEXT NOT NULL,
    Account               TEXT,
    SecurityName          TEXT,
    Ticker                TEXT,
    Exchange              TEXT,
    Currency              TEXT,
    Side                  TEXT,
    Amount                REAL,
    NyOrderCreateAsOfDateTime TEXT,
    Type                  TEXT,
    LimitPrice            REAL,
    Broker                TEXT,
    StopPrice             REAL,
    StrategyType          TEXT,
    TraderName            TEXT,
    TraderUuid            TEXT,
    RouteId               TEXT NOT NULL,
    NyTranCreateAsOfDateTime TEXT,
    RouteShares           INTEGER,
    FillId                TEXT NOT NULL,
    ExecType              TEXT,
    DateTimeOfFill        TEXT,
    FillPrice             REAL,
    FillShares            INTEGER,
    LastCapacity          TEXT,
    LastMarket            TEXT,
    Liquidity             TEXT,
    LocalExchangeSymbol   TEXT,
    source_date           TEXT NOT NULL DEFAULT '',
    fetched_at            TEXT DEFAULT (datetime('now')),
    ingested_at           TEXT DEFAULT (datetime('now')),
    order_as_of_date      TEXT NOT NULL DEFAULT '',
    exchange_exec_time    TEXT DEFAULT '',
    PRIMARY KEY (OrderId, RouteId, FillId, source_date)
);

INSERT INTO raw_fills_new (
    OrderId, Account, SecurityName, Ticker, Exchange,
    Currency, Side, Amount, NyOrderCreateAsOfDateTime,
    Type, LimitPrice, Broker, StopPrice, StrategyType,
    TraderName, TraderUuid, RouteId, NyTranCreateAsOfDateTime,
    RouteShares, FillId, ExecType, DateTimeOfFill,
    FillPrice, FillShares, LastCapacity, LastMarket,
    Liquidity, LocalExchangeSymbol,
    source_date, fetched_at, ingested_at,
    order_as_of_date, exchange_exec_time
)
SELECT
    OrderId, Account, SecurityName, Ticker, Exchange,
    Currency, Side,
    CASE WHEN TRIM(Amount)='' OR Amount IS NULL THEN NULL ELSE CAST(Amount AS REAL) END,
    NyOrderCreateAsOfDateTime,
    Type, LimitPrice, Broker, StopPrice, StrategyType,
    TraderName, TraderUuid, RouteId, NyTranCreateAsOfDateTime,
    CASE WHEN TRIM(RouteShares)='' OR RouteShares IS NULL THEN NULL ELSE CAST(RouteShares AS INTEGER) END,
    FillId, ExecType, DateTimeOfFill,
    CASE WHEN TRIM(FillPrice)='' OR FillPrice IS NULL THEN NULL ELSE CAST(FillPrice AS REAL) END,
    CASE WHEN TRIM(FillShares)='' OR FillShares IS NULL THEN NULL ELSE CAST(FillShares AS INTEGER) END,
    LastCapacity, LastMarket,
    Liquidity, LocalExchangeSymbol,
    source_date, fetched_at, ingested_at,
    order_as_of_date, exchange_exec_time
FROM raw_fills;

DROP TABLE raw_fills;
ALTER TABLE raw_fills_new RENAME TO raw_fills;

CREATE INDEX IF NOT EXISTS idx_raw_source_date ON raw_fills (source_date);
CREATE INDEX IF NOT EXISTS idx_raw_order_date ON raw_fills (order_as_of_date);
CREATE INDEX IF NOT EXISTS idx_raw_ticker ON raw_fills (Ticker);

PRAGMA user_version = 5;

COMMIT;
