-- Migration: raw_fills v2 -> v3
-- 合并两项修复:
--   1. raw_fills PK 从 (OrderId, RouteId, FillId) -> (OrderId, RouteId, FillId, source_date)
--      修复 Bloomberg 跨日 fetch 覆盖早期行 (209 个孤儿行根因)
--   2. fetch_log 软状态机制: CHECK 约束 + 历史重复行 soft-supersede
--
-- 安全保障:
-- - 实测 0 个新 PK 冲突 (11M 行预检 GROUP BY OrderId,RouteId,FillId,source_date HAVING COUNT(*)>1 = 0)
-- - 0 行 source_date IS NULL / '' (NOT NULL 约束安全)
-- - 单事务 BEGIN/COMMIT 包裹, 全成功或全回滚
-- - 索引重建 (DROP TABLE 连带删除原索引)
--
-- 关于 user_version 历史断链:
--   raw_fills.db 实际 user_version = 0, 但代码 _EXPECTED_CURRENT v2=2 (因 inline_ddl
--   历史已等价完成 LimitPrice/StopPrice TEXT->REAL 升级), 故执行前手动伪造
--   PRAGMA user_version = 2, 跳过 v0_to_v1 / v1_to_v2 无谓回溯, 仅应用本 v2_to_v3。

BEGIN;

-- ═══════════════════════════════════════════════════════════════════════
-- Part 1: raw_fills PK 升级
-- ═══════════════════════════════════════════════════════════════════════
-- SQLite 不支持 ALTER PRIMARY KEY, 需 CREATE NEW + COPY + DROP + RENAME

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
    Currency, Side, Amount, NyOrderCreateAsOfDateTime,
    Type, LimitPrice, Broker, StopPrice, StrategyType,
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

-- ═══════════════════════════════════════════════════════════════════════
-- Part 2: fetch_log 软状态机制升级
-- ═══════════════════════════════════════════════════════════════════════
-- 重建 fetch_log 表添加 CHECK 约束; 历史同 source_date 多行保留最新一行 'fetched',
-- 其余标 'deprecated' 审计保留. 业务允许 late fills / scope 切换 / BBG 修正 在
-- 同 source_date 多次拉取 (latest-wins), 但通过软标记避免被 get_last_fetch_date
-- 等只看 'fetched' 的查询重复计数.

CREATE TABLE IF NOT EXISTS fetch_log_new (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    source_date           TEXT NOT NULL,
    fetch_timestamp       TEXT DEFAULT (datetime('now')),
    row_count             INTEGER NOT NULL,
    data_hash             TEXT NOT NULL,
    file_path             TEXT,
    status                TEXT NOT NULL DEFAULT 'fetched'
                          CHECK (status IN ('fetched','deprecated','superseded','failed')),
    UNIQUE(source_date, data_hash)
);

-- 复制历史行; 同 source_date 多行时仅最新一行(id 最大)保持 'fetched', 其余 'deprecated'
INSERT INTO fetch_log_new
    (id, source_date, fetch_timestamp, row_count, data_hash, file_path, status)
SELECT
    f.id, f.source_date, f.fetch_timestamp, f.row_count, f.data_hash, f.file_path,
    CASE
        WHEN f.id = (
            SELECT MAX(f2.id) FROM fetch_log f2
            WHERE f2.source_date = f.source_date
              AND f2.status = 'fetched'
        ) THEN 'fetched'
        ELSE 'deprecated'
    END
FROM fetch_log f;

DROP TABLE fetch_log;
ALTER TABLE fetch_log_new RENAME TO fetch_log;

CREATE INDEX IF NOT EXISTS idx_fetch_log_date_status ON fetch_log (source_date, status);

PRAGMA user_version = 3;

COMMIT;