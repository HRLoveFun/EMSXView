-- Migration: raw_fills v3 -> v4
-- 收紧 order_as_of_date 字段约束为 NOT NULL (业务语义: 每个订单都必须有执行日期)
--
-- 前置: P1 回填已完成 (2026-07-02), 全表 oaod NULL=0, eet NULL=0
-- 安全保障:
--   1. SQLite CHECK 约束在 CREATE TABLE 时一次性定义
--   2. SQLite 不支持直接 ALTER COLUMN, 使用"重建表"模式
--   3. 单事务, 索引重建
--
-- 影响: 违反约束的 INSERT 会被 DB 拒绝, 必须在 upsert 入口 (upsert_raw_api_data)
--       / clean_emsx_fills 处保证 order_as_of_date 计算成功。
--       已知根因: EXCHANGE_TIMEZONE 必须含 Bloomberg 实际 Exchange code。
--       已修复: 添加 MUMBAI / BSE / NSE 到字典 (2026-07-02)。
--
-- 校验: 操作者执行前应运行以下 SQL 确认无 NULL/空串
--       SELECT COUNT(*) FROM raw_fills
--       WHERE order_as_of_date IS NULL OR TRIM(order_as_of_date) = '';
--       期望: 0

BEGIN;

-- 重建表, order_as_of_date 加 NOT NULL 约束
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
    order_as_of_date      TEXT NOT NULL DEFAULT '',
    exchange_exec_time    TEXT DEFAULT '',
    PRIMARY KEY (OrderId, RouteId, FillId, source_date)
);

INSERT INTO raw_fills_new
SELECT * FROM raw_fills;

DROP TABLE raw_fills;
ALTER TABLE raw_fills_new RENAME TO raw_fills;

CREATE INDEX IF NOT EXISTS idx_raw_source_date ON raw_fills (source_date);
CREATE INDEX IF NOT EXISTS idx_raw_order_date ON raw_fills (order_as_of_date);
CREATE INDEX IF NOT EXISTS idx_raw_ticker ON raw_fills (Ticker);

PRAGMA user_version = 4;

COMMIT;
