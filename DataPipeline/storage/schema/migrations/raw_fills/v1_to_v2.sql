-- Migration: raw_fills v1 -> v2
-- 将 LimitPrice/StopPrice 列类型从 TEXT 升级为 REAL
-- 与 inline_ddl._migrate_raw_fills_column_types 逻辑等价
-- （SQLite 不支持 ALTER COLUMN 改类型，需 CREATE NEW + COPY + DROP + RENAME）
--
-- 安全保障：
-- - 空字符串 → NULL（避免 '' 被 SQLite 类型亲和转为 0.0）
-- - 索引重建（DROP TABLE 连带删除索引）
-- - 单事务包裹，全成功或全回滚

BEGIN;

CREATE TABLE IF NOT EXISTS raw_fills_new (
    OrderId               TEXT NOT NULL,
    Account               TEXT,
    SecurityName          TEXT,
    Ticker                TEXT,
    Exchange              TEXT,
    Currency              TEXT,
    Side                  TEXT,
    Amount                TEXT,
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
    RouteShares           TEXT,
    FillId                TEXT NOT NULL,
    ExecType              TEXT,
    DateTimeOfFill        TEXT,
    FillPrice             TEXT,
    FillShares            TEXT,
    LastCapacity          TEXT,
    LastMarket            TEXT,
    Liquidity             TEXT,
    LocalExchangeSymbol   TEXT,
    source_date           TEXT NOT NULL DEFAULT '',
    fetched_at            TEXT DEFAULT (datetime('now')),
    ingested_at           TEXT DEFAULT (datetime('now')),
    order_as_of_date      TEXT DEFAULT '',
    exchange_exec_time    TEXT DEFAULT '',
    PRIMARY KEY (OrderId, RouteId, FillId)
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
    Currency, Side, Amount, NyOrderCreateAsOfDateTime,
    Type,
    CASE WHEN TRIM(LimitPrice)='' OR LimitPrice IS NULL THEN NULL ELSE CAST(LimitPrice AS REAL) END,
    Broker,
    CASE WHEN TRIM(StopPrice)='' OR StopPrice IS NULL THEN NULL ELSE CAST(StopPrice AS REAL) END,
    StrategyType,
    TraderName, TraderUuid, RouteId, NyTranCreateAsOfDateTime,
    RouteShares, FillId, ExecType, DateTimeOfFill,
    FillPrice, FillShares, LastCapacity, LastMarket,
    Liquidity, LocalExchangeSymbol,
    source_date, fetched_at, ingested_at,
    order_as_of_date, exchange_exec_time
FROM raw_fills;

DROP TABLE raw_fills;
ALTER TABLE raw_fills_new RENAME TO raw_fills;

CREATE INDEX IF NOT EXISTS idx_raw_source_date ON raw_fills (source_date);
CREATE INDEX IF NOT EXISTS idx_raw_order_date ON raw_fills (order_as_of_date);
CREATE INDEX IF NOT EXISTS idx_raw_ticker ON raw_fills (Ticker);

PRAGMA user_version = 2;

COMMIT;
