-- raw_bdib v1 → v2: 删除三个废弃衍生列
-- ═══════════════════════════════════════════════════════════════
-- 
-- 背景：物理表曾残留 vwap / fluctuation / log_chg_pct_10s 三个衍生列。
--       这些列是早期版本 DDL 直接 CREATE TABLE 时包含的，当前代码不再写入。
--       衍生字段现由 compute_derived_fields() 内存即时计算，无需持久化。
--
-- 前提：已完成空 bar 清理（scripts/ops/cleanup_raw_bdib_empty_bars.py），
--       当前 user_version = 1。
--
-- 影响：
--   - 表 ~2.056 亿行，41GB，DROP COLUMN 需要内部表重建（每列约 30-45 分钟）
--   - 需要额外 ~30GB 临时空间（WAL + 临时表）
--   - 需要 SQLite >= 3.35.0 (2021-03 发布)
--
-- 执行方式（维护窗口内手动执行）：
--   python -c "import sqlite3; conn=sqlite3.connect('raw_bdib.db'); [conn.execute(f'ALTER TABLE raw_bdib DROP COLUMN {c}') for c in ['vwap','fluctuation','log_chg_pct_10s'] if c in [r[1] for r in conn.execute('PRAGMA table_info(raw_bdib)')]]; conn.execute('PRAGMA user_version = 2'); conn.commit(); conn.close()"
--
-- 执行状态：已于 2026-07-07 执行完成，user_version=2，12 列对齐代码定义。
--   更新 migration/manager.py EXPECTED_VERSIONS["raw_bdib"] 为 2

-- 注意：SQLite 不支持条件 ALTER TABLE DROP COLUMN IF EXISTS
-- 需要逐列检查，忽略列不存在的错误

ALTER TABLE raw_bdib DROP COLUMN vwap;
ALTER TABLE raw_bdib DROP COLUMN fluctuation;
ALTER TABLE raw_bdib DROP COLUMN log_chg_pct_10s;

-- 更新 schema 版本
PRAGMA user_version = 2;
