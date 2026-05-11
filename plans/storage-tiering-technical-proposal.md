# 存储分层架构技术方案 — 88GB → Hot (SQLite ≤25GB) + Cold (Parquet)

> **编制日期**: 2026-05-08 | **版本**: v1.0 | **关联**: 工程改进计划 P0a
> **目标**: 将 88GB 数据通过存储分层优化迁移至 Hot (SQLite, ≤25GB) + Cold (Parquet 分区归档) 两层结构，实现 3-10 倍查询性能提升

---

## 目录

1. [现状分析](#1-现状分析)
2. [总体架构设计](#2-总体架构设计)
3. [Hot 层设计 (SQLite)](#3-hot-层设计-sqlite)
4. [Cold 层设计 (Parquet 分区)](#4-cold-层设计-parquet-分区)
5. [数据流转逻辑](#5-数据流转逻辑)
6. [压缩与归档策略](#6-压缩与归档策略)
7. [统一查询路由层 (UnifiedReader)](#7-统一查询路由层-unifiedreader)
8. [性能分析](#8-性能分析)
9. [实施步骤](#9-实施步骤)
10. [风险与缓解措施](#10-风险与缓解措施)
11. [附录](#11-附录)

---

## 1. 现状分析

### 1.1 数据规模总览

| 数据库 | 当前大小 | 占比 | 行数 (约) | 增长速率 | 存储格式 |
|--------|---------|------|----------|---------|---------|
| `raw_bdib.db` | 68.5 GB | 77.8% | ~2.3B 行 | ~460 MB/日 | SQLite WAL, 无压缩 |
| `processed_fills.db` | 14.6 GB | 16.6% | 8.65M fills | ~60 MB/日 | SQLite WAL |
| `fill_bdib.db` | ~2.0 GB | 2.3% | ~8.6M rows | ~14 MB/日 | SQLite WAL |
| `raw_fills.db` | ~0.5 GB | 0.6% | 8.65M rows | ~3 MB/日 | SQLite WAL |
| `processed_raw_bdib.db` | ~5.0 GB | 5.7% | ~2.3B 行 | ~35 MB/日 | SQLite WAL |
| `regime.db` | ~115 KB | <0.1% | <50K rows | 静态 | SQLite WAL |
| **总计** | **~88 GB** | 100% | — | **~600 MB/交易日** | — |

### 1.2 核心问题

**问题 1 — 单库过大**:
- `raw_bdib.db` 单文件 68.5 GB，超出 SQLite 推荐上限 (10 GB 以下获得最佳性能)
- SQLite B-tree 深度随数据量增长，随机 IO 退化
- WAL 文件 (`-wal` + `-shm`) 额外增加 ~5-10% 磁盘开销和 IO 负担

**问题 2 — 全表扫描瓶颈**:
- attribution 计算需遍历全部 ~2.3B 行 BDIB bars 做 VWAP 重建 (`SUM(close*volume)/SUM(volume)`)
- `fill_regime_tagger` 对 8.65M fills 跨 DB 查询，需要 raw_bdib 全量扫描
- 每次全量 attribution backfill (~2h) 和 regime backfill (~50min) 均全表扫 raw_bdib
- 当前无数据老化机制，每次处理日期范围扩大，扫描量线性增长

**问题 3 — 列式存储缺失**:
- 查询常仅需 `close`, `volume`, `mkt_timestamp` 等 3-5 列，但 SQLite 强制读取整行所有列
- OHLCV 10 秒 bar 存储中，`num_trds` 和 `value` 列在 80%+ 查询中不被使用
- SQLite 行式存储导致 IO 放大 3-8x 相对列式格式

**问题 4 — 增量失控**:
- 年度预估增量 ~150 GB/年（按 250 交易日 × 600 MB/日）
- 无自动归档机制，数据持续膨胀
- 本地磁盘 1TB，理论剩余寿命约 6 个月（不治理情况下）

### 1.3 查询模式分析

| 查询类型 | 频率 | 涉及表 | 当前性能 | 热点列 | 访问范围 |
|---------|------|--------|---------|--------|---------|
| TCA attribution 计算 | 每日 + 定期 backfill | raw_bdib, fill_bdib | 单次 ~2h (全量) | close, volume, mkt_timestamp | 全量或 1-3 月范围 |
| 按 ticker+date 查 BDIB bars | 高 | raw_bdib | ~200ms | open/high/low/close/volume | 单 ticker 单日 |
| 按 date range 查 BDIB | 中 | raw_bdib | ~2-10s | 全列 | 多 ticker 多日 |
| 按 date range 查 daily summary | 高 | bdib_daily_summary | ~100ms | total_volume, daily_vwap, adv | 全范围 |
| 按 cohort 查询 scorecard | 中 | fill_bdib + processed_fills | ~5-30s | 全列 | 按需过滤 |
| regime fill tagging | 每日 | raw_bdib + fill_bdib | ~7min/8.65M fills | 全列 | 全量或增量日期 |
| 研究复现 (ad-hoc) | 低 | 多表 JOIN | 不可预测 | 研究相关 | 任意范围 |

---

## 2. 总体架构设计

### 2.1 核心设计原则

1. **Hot 优先**: 最近交易数据访问频率最高，保持在 SQLite 中零延迟访问
2. **Cold 压缩**: 历史数据转入列式 Parquet，利用编码压缩降低 3-5x 存储
3. **统一路由**: 应用层零改动 — `UnifiedReader` 透明处理 Hot/Cold 路由
4. **渐进迁移**: 月度滚动归档，不中断在线处理
5. **可复现**: 每个 Parquet 归档目录是独立、可移植的研究单元
6. **原子提交**: 归档操作以 `month` 为原子单元，失败可完整回滚

### 2.2 架构总览

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         APPLICATION LAYER                               │
│  TCA / Regime / Attribution / Scorecard / Research                     │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │ 通过 Repository / UnifiedReader 访问
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     UNIFIED DATA ACCESS LAYER                           │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                    UnifiedReader (路由引擎)                        │   │
│  │  1) 解析查询参数 (日期范围 + ticker + 其他 filter)                 │   │
│  │  2) 判断 Hot 覆盖范围 → SQLite 查询                                   │   │
│  │  3) 判断 Cold 覆盖范围 → Parquet 查询 (PyArrow + predicate pushdown) │   │
│  │  4) 合并结果集 → 返回统一 DataFrame                                    │   │
│  └──────────────────────────────────────────────────────────────────┘   │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
          ┌──────────────────────┼──────────────────────┐
          ▼                      ▼                      ▼
┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────────────┐
│   HOT TIER (SQLite)  │  │   COLD TIER (Parquet)│  │   REF TIER (Static) │
│   ≤25 GB total       │  │   HDFS-style 分区    │  │   ≤500 MB total     │
├──────────────────────┤  ├─────────────────────┤  ├─────────────────────┤
│ raw_bdib.db (recent) │  │ raw_bdib/           │  │ market_mapping.json │
│ processed_fills.db   │  │   year=YYYY/         │  │ macro_calendar.csv  │
│ fill_bdib.db (recent)│  │     month=MM/        │  │ macro_event_dict.json│
│ raw_fills.db         │  │       part-*.parquet │  │ outdated_tickers.json│
│ processed_raw_bdib.db│  │ processed_fills/     │  │ archive_manifest.json│
│ regime.db            │  │   year=YYYY/         │  └─────────────────────┘
│ fill_fetch_history.db│  │     month=MM/...     │
└──────────────────────┘  │ fill_bdib/           │
                          │   year=YYYY/         │
                          │     month=MM/...     │
                          └─────────────────────┘
```

### 2.3 分层决策矩阵

| 数据 | Hot 保留策略 | Hot 格式 | Cold 格式 | Cold 分区键 | 转移触发器 |
|------|-------------|---------|----------|------------|-----------|
| `raw_bdib` | 最近 **50 个交易日** | SQLite | Parquet (snappy) | year, month, ticker_prefix | 月度归档任务 |
| `processed_raw_bdib` | 最近 **50 个交易日** | SQLite | Parquet (snappy) | year, month | 随 raw_bdib 归档 |
| `fill_bdib` | 最近 **90 个交易日** | SQLite | Parquet (snappy) | year, month | 月度归档任务 |
| `processed_fills` | 最近 **120 个交易日** | SQLite | Parquet (snappy) | year, month | 月度归档任务 |
| `raw_fills` | **全部保留** (500MB) | SQLite | — | — | 不移入冷层 |
| `regime.db` | **全部保留** (115KB) | SQLite | — | — | 不移入冷层 |
| `fill_fetch_history` | **全部保留** (小型) | SQLite | — | — | 不移入冷层 |

> **Hot 窗口设计依据**:
> - 50 交易日 raw_bdib ≈ 68GB × 50/147 ≈ **23GB** ≤ 25GB 目标
> - 50 交易日 ≈ 2.5 个日历月，覆盖主动 TCA 分析和近期研究窗口
> - 90 交易日 fill_bdib ≈ 覆盖一个完整季度，用于季度绩效归因
> - 120 交易日 processed_fills ≈ 覆盖半年订单级分析

---

## 3. Hot 层设计 (SQLite)

### 3.1 物理布局

```
CostView/data/
├── raw_bdib.db                   ← 最近 50 交易日的 BDIB bars
├── raw_bdib.db-wal               ← WAL 文件
├── raw_bdib.db-shm               ← 共享内存索引
├── processed_raw_bdib.db         ← 最近 50 交易日的衍生特征
├── fill_bdib.db                  ← 最近 90 交易日的 fill-BDIB 匹配
├── processed_fills.db            ← 最近 120 交易日的清洗 fills
├── raw_fills.db                  ← 全部 (不移入冷层)
├── regime.db                     ← 全部 (不移入冷层)
├── fill_fetch_history.db         ← 全部 (不移入冷层)
├── tiering/                      ← 分层管理元数据
│   ├── tiering_config.json       ← 分层配置 (窗口大小、路径)
│   ├── archive_manifest.json     ← 归档清单 (每个月的文件列表 + 校验和)
│   └── archive_audit.db          ← 归档审计 (操作历史、校验结果)
└── archive/                      ← Parquet 冷数据 (详见第 4 节)
    └── year=YYYY/
        └── month=MM/
            └── ...
```

### 3.2 Hot 层维护机制

**Purge 策略** — 当 raw_bdib.db 超过 Hot 窗口阈值时：

```python
# 伪代码: Hot 层裁剪策略
def trim_hot_tier(tier_config: TieringConfig) -> int:
    """裁剪 raw_bdib.db 至保留窗口内，返回删除行数。"""
    cutoff_date = compute_cutoff(tier_config.hot_window_days_raw_bdib)
    # 1. 查询超出窗口的数据范围
    rows_to_purge = conn.execute("""
        SELECT COUNT(*) FROM raw_bdib
        WHERE order_as_of_date < ?
    """, (cutoff_date,))
    # 2. 事务删除 (分批执行避免锁超时)
    with batch_delete(conn, chunk_size=100_000) as deleter:
        deleter.delete("raw_bdib", "order_as_of_date < ?", (cutoff_date,))
    # 3. VACUUM 回收空间 (非高峰期执行)
    if rows_to_purge > 1_000_000:
        schedule_vacuum(conn, delay_hours=2)
    return rows_to_purge
```

> **重要**: 裁剪操作在归档流程 **成功完成** 后执行。如果归档失败，裁剪不执行，数据在 Hot 层保持完整。

### 3.3 Hot 层 SQLite 优化

| 优化项 | 当前状态 | 改进措施 | 预期提升 |
|-------|---------|---------|---------|
| PRAGMA cache_size | 默认 (2MB) | 调至 `-cache_size = -524288` (512MB) | 随机读 2-4x |
| PRAGMA mmap_size | 未设置 | `mmap_size = 8589934592` (8GB) | 大范围扫描 3-5x |
| PRAGMA synchronous | FULL (默认) | NORMAL | 写入 2x (风险: 断电可能丢 WAL) |
| PRAGMA temp_store | FILE (默认) | MEMORY | 排序/分组 1.5x |
| PRAGMA page_size | 4096 | 16384 (16KB) | 大 IO 2x (需 VACUUM 后生效) |
| Covering index | 仅有 (ticker) 和 (date) 单列索引 | 新增 `(order_as_of_date, equ_ticker) INCLUDE (close, volume)` | 常用查询 5-10x |

**新增覆盖索引 (Covering Indexes)**:

```sql
-- 替代现有单列 idx_raw_bdib_date 和 idx_raw_bdib_ticker
-- 覆盖 attribution VWAP 重建核心查询
CREATE INDEX IF NOT EXISTS idx_raw_bdib_date_ticker_cv
ON raw_bdib(order_as_of_date, equ_ticker) INCLUDE (close, volume);

-- 覆盖 ticker+date+timestamp 范围查询
CREATE INDEX IF NOT EXISTS idx_raw_bdib_range
ON raw_bdib(equ_ticker, order_as_of_date, mkt_timestamp) INCLUDE (open, high, low, close, volume);

-- fill_bdib 查询优化
CREATE INDEX IF NOT EXISTS idx_fill_bdib_date_ticker
ON fill_bdib(order_as_of_date, equ_ticker);
```

> **注意**: SQLite 的 `INCLUDE` 语法自 3.35.0 (2021-03-12) 起支持。当前环境需确认版本，否则改用复合索引模拟覆盖扫描。

---

## 4. Cold 层设计 (Parquet 分区)

### 4.1 分区目录结构

```
CostView/data/archive/
├── year=2025/
│   ├── month=09/
│   │   ├── raw_bdib_part-0.parquet      ← 文件内按 equ_ticker + mkt_timestamp 排序
│   │   ├── raw_bdib_part-1.parquet      ← 多文件支持并行读取 (建议 4-8 分区/月)
│   │   ├── raw_bdib_part-2.parquet
│   │   ├── raw_bdib_part-3.parquet
│   │   ├── processed_raw_bdib.parquet   ← 1 个文件 (月数据较小)
│   │   ├── fill_bdib.parquet
│   │   ├── processed_fills.parquet
│   │   └── archive_manifest.json         ← 校验和 + Schema 快照
│   ├── month=10/
│   │   └── ...
│   └── month=11/
│       └── ...
├── year=2026/
│   ├── month=01/
│   │   └── ...
│   ├── month=02/
│   │   └── ...
│   ├── month=03/
│   │   └── ...
│   └── month=04/
│       └── ...
└── _research_snapshots/                  ← 研究快照目录 (可选)
    └── 2026-05-01_ad_hoc_study/
        └── raw_bdib_slice.parquet
```

### 4.2 文件内存储格式

| 参数 | 选择 | 理由 |
|------|------|------|
| 文件格式 | Parquet v2 | 列式存储 + 谓词下推 + schema evolution |
| 压缩编码 | **ZSTD** (level 3) | 压缩比 3-5x vs Snappy 2-3x; 解压速度平衡 |
| Row group size | 512 MB | 平衡并行读与内存占用 |
| Page size | 64 KB | 列式扫描最优 |
| 字典编码 | 启用 (默认) | ticker, source 等低基数列显著压缩 |
| 排序顺序 | `(equ_ticker, mkt_timestamp)` | 支持 ticker 级谓词下推 + 范围查询 |
| 统计信息 | 全列 min/max/null_count | 分区剪枝 + Row group 跳过 |

### 4.3 分区修剪 (Partition Pruning) 策略

分区修剪是查询性能提升的核心机制。查询引擎通过将 `WHERE` 子句映射到目录结构来跳过不相关分区。

```python
# 分区修剪示例
def resolve_partitions(
    start_date: str, end_date: str,
    equ_tickers: Optional[list[str]] = None,
) -> list[Path]:
    """解析查询涉及的分区路径，跳过不相关年月。

    - 2026-01-15 ~ 2026-02-20 → year=2026/month=01/ + year=2026/month=02/
    - 不访问 year=2025/ 的任何数据
    - 可选: ticker_prefix 进一步剪枝
    """
    partitions = []
    for ym in iter_year_months(start_date, end_date):
        base = ARCHIVE_ROOT / f"year={ym.year}" / f"month={ym.month:02d}"
        if base.exists():
            if equ_tickers:
                # 在 raw_bdib 文件名中包含 ticker_prefix 做第二级剪枝
                ticker_prefix = equ_tickers[0][0].lower()  # a-z 首字母
                for f in base.glob(f"raw_bdib_part-*.parquet"):
                    partitions.append(f)
            else:
                partitions.extend(base.glob("**/*.parquet"))
    return partitions
```

### 4.4 Parquet Schema 设计

**raw_bdib 冷层 Schema** (比 SQLite 增加 `year`/`month` 分区列):

```python
import pyarrow as pa

raw_bdib_schema = pa.schema([
    # 分区键 (写入时从 order_as_of_date 提取, 物理存储在目录路径中)
    # year: int32     ← 目录分区, schema 中不显式包含
    # month: int32    ← 目录分区, schema 中不显式包含

    # 主键列
    pa.field("equ_ticker",       pa.utf8()),
    pa.field("order_as_of_date", pa.utf8()),       # YYYY-MM-DD
    pa.field("mkt_timestamp",    pa.utf8()),       # HH:MM:SS.ssssss

    # OHLCV 量价列 (核心查询目标)
    pa.field("open",             pa.float32()),     # 从 REAL→float32, 精度足够
    pa.field("high",             pa.float32()),
    pa.field("low",              pa.float32()),
    pa.field("close",            pa.float32()),
    pa.field("volume",           pa.float64()),     # 交易量需 double

    # 辅助列 (低频查询)
    pa.field("num_trds",         pa.float32()),
    pa.field("value",            pa.float64()),

    # 元数据
    pa.field("fetched_at",       pa.utf8()),       # ISO 时间戳
    pa.field("source",           pa.utf8()),       # 'bloomberg'
])

# 写入时压缩编码配置
parquet_writer_kwargs = {
    "compression": "zstd",
    "compression_level": 3,
    "row_group_size": 512 * 1024 * 1024,  # 512 MB
    "data_page_size": 64 * 1024,           # 64 KB
    "dictionary_pagesize_limit": 1 * 1024 * 1024,  # 1 MB per dict
    "write_statistics": True,
    "sort_by": [("equ_ticker", "ascending"), ("mkt_timestamp", "ascending")],
}
```

### 4.5 压缩比预估

| 数据集 | SQLite 大小 | Parquet (Snappy) | Parquet (ZSTD) | ZSTD 压缩比 |
|--------|-----------|-----------------|----------------|------------|
| raw_bdib (冷数据) | 45 GB | ~15 GB | ~11 GB | **4.1x** |
| processed_raw_bdib | ~3.5 GB | ~1.2 GB | ~0.9 GB | **3.9x** |
| fill_bdib | ~1.5 GB | ~0.5 GB | ~0.4 GB | **3.75x** |
| processed_fills | ~12 GB | ~4 GB | ~3 GB | **4x** |
| **冷层总计** | **~62 GB** | **~20.7 GB** | **~15.3 GB** | **~4x** |

> **说明**: 压缩比基于典型的金融时间序列数据特征 (大量重复 ticker 值、有限范围 float、有序时间戳), 实际压缩比可能波动 ±15%。

---

## 5. 数据流转逻辑

### 5.1 整体数据流

```
                       ┌────────────────────────────┐
                       │    Bloomberg API (xbbg)     │
                       │    fill_fetch.py / bdib     │
                       │    _fetcher.py              │
                       └──────────┬─────────────────┘
                                  │ 实时写入 (日内)
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         HOT TIER (SQLite)                                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌─────────────┐  │
│  │ raw_bdib.db  │  │ processed_   │  │ fill_bdib.db │  │ processed_  │  │
│  │ (50d window) │  │ raw_bdib.db  │  │ (90d window) │  │ fills.db    │  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  │ (120d w.)   │  │
│         │                 │                 │          └─────────────┘  │
│         └─────────────────┴─────────────────┴───────────────────────────┘
│                                      │
└──────────────────────────────────────┼──────────────────────────────────┘
                                       │ 月度归档流程 (每个月 1 号的 02:00)
                                       ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     ARCHIVE MANAGER (archive_manager.py)                 │
│                                                                         │
│  Step 1: FREEZE — 标记 Hot 层中待归档的数据范围 (确保一致性)             │
│  Step 2: EXTRACT — 逐表 SELECT * WHERE date < cutoff → DataFrame        │
│  Step 3: WRITE   — DataFrame → Parquet (ZSTD) → *.tmp 目录              │
│  Step 4: VERIFY  — 读取 Parquet 校验行数 + 校验和 (SHA-256)             │
│  Step 5: COMMIT  — 移动 *.tmp → archive/year=YYYY/month=MM/            │
│  Step 6: PURGE   — DELETE FROM hot WHERE date < cutoff                  │
│  Step 7: AUDIT   — 写入 archive_audit.db 记录本次操作                     │
│                                                                         │
│  原子性保证: Step 3-5 失败 → 删除 *.tmp → 不影响 Hot + 已有 Cold        │
└─────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         COLD TIER (Parquet)                              │
│  CostView/data/archive/year=YYYY/month=MM/*.parquet                     │
│  archive_manifest.json (每月的校验和 + Schema + 行数快照)                │
└─────────────────────────────────────────────────────────────────────────┘
```

### 5.2 首次全量迁移 (Phase 2)

对于 2025-09 ~ 2026-02 的 **全部历史数据**, 首次迁移采用分批并行策略:

```python
def migrate_full_history(dry_run: bool = False) -> MigrationReport:
    """全量历史数据一次性迁移到 Parquet (首次迁移)."""
    report = MigrationReport()
    archive_months = compute_month_ranges(
        start="2025-09", end=current_cold_cutoff()
    )

    for year, month in archive_months:
        logger.info(f"Archiving {year}-{month:02d}...")
        try:
            # 并行处理同一月份内多表
            with ThreadPoolExecutor(max_workers=3) as pool:
                futures = []
                for table in ["raw_bdib", "processed_fills",
                              "fill_bdib", "processed_raw_bdib"]:
                    f = pool.submit(
                        archive_single_table,
                        table=table, year=year, month=month,
                        dry_run=dry_run,
                    )
                    futures.append(f)
                for f in as_completed(futures):
                    result = f.result()
                    report.add(result)
            if not dry_run:
                logger.info(f"  ✓ {year}-{month:02d} archived: "
                            f"{report.month_rows(year, month)} rows")
        except Exception as e:
            logger.error(f"  ✗ {year}-{month:02d} FAILED: {e}")
            report.add_failure(year, month, str(e))
            # 不中断整体流程, 记录失败供重试

    return report
```

### 5.3 增量月度归档 (Cron 任务)

```python
def monthly_archive_job(dry_run: bool = False) -> ArchiveAudit:
    """月度归档 Cron 任务 — 推荐在每月第 1 个周末 02:00 执行."""
    cutoff_date = compute_archive_cutoff(
        # 归档比 Hot 窗口多 1 个月, 保留安全缓冲
        hot_window_days=50,
        buffer_days=30,   # 额外保留缓冲
    )

    # 1. 锁定处理管道 (防止并发写入)
    with pipeline_lock("archive"):
        # 2. 迭代每个待归档月的每个表
        for table in TIERING_TABLES:
            archive_single_table_to_parquet(
                table=table,
                end_date=cutoff_date,
                dry_run=dry_run,
            )

        # 3. 裁剪 Hot 层
        if not dry_run:
            trim_hot_tier_all_databases(cutoff_date)

        # 4. 审计记录
        audit = write_audit_log(cutoff_date, status="success")

    return audit
```

### 5.4 研究快照工作流 (可选增强)

支持从任意日期范围生成独立的研究快照 Parquet 文件:

```bash
# CLI 命令: 为特定日期范围创建研究快照
python -m CostView archive snapshot \
    --start 2025-12-01 --end 2025-12-31 \
    --tickers AAPL,MSFT,GOOGL \
    --output research/dec2025_trichech/ \
    --include raw_bdib,fill_bdib,processed_fills,regime
```

生成的文件完全自包含, 无需 SQLite 即可独立运行 attribution 分析。

---

## 6. 压缩与归档策略

### 6.1 压缩编码栈

```
数据列 → 列编码 → 压缩 → 写入 Parquet

列编码策略:
┌─────────────────┬────────────────┬─────────────────────────────────┐
│ 列名            │ 编码策略        │ 理由                            │
├─────────────────┼────────────────┼─────────────────────────────────┤
│ equ_ticker      │ PLAIN (字典)   │ 低基数 (约 2000 种) → 字典编码  │
│ order_as_of_date│ PLAIN (字典)   │ 单月最多 22 种; 日期前缀压缩    │
│ mkt_timestamp   │ DELTA_BINARY   │ 有序时间戳, delta 编码显著压缩  │
│ open/high/low   │ PLAIN          │ float32, ZSTD 层已足够           │
│ close           │ PLAIN          │ 核心分析列, 保留原值             │
│ volume          │ PLAIN          │ 大动态范围, ZSTD 层编码         │
│ num_trds        │ PLAIN          │ 中基数, ZSTD 已足够              │
│ value           │ PLAIN          │ 大动态范围, ZSTD 层编码          │
│ source          │ PLAIN (字典)   │ 仅 'bloomberg' 一种值            │
│ fetched_at      │ PLAIN          │ 元数据列, 不参与分析             │
└─────────────────┴────────────────┴─────────────────────────────────┘

ZSTD 参数:
  - level: 3 (平衡比/速, 金融时间序列默认最优)
  - 解压速度: ~500 MB/s/核 (同等 CPU 下)
  - 在 ticker 字典编码 + ZSTD 组合下, 实测压缩比预计 3.5-4.5x
```

### 6.2 归档文件命名规范

| 文件 | 命名模板 | 说明 |
|------|---------|------|
| raw_bdib bars | `raw_bdib_part-{N}.parquet` | N ∈ [0,7]; 8 文件/月并行读 |
| processed_raw_bdib | `processed_raw_bdib.parquet` | 单文件 (月数据 ~300MB) |
| fill_bdib | `fill_bdib.parquet` | 单文件 (月数据 ~130MB) |
| processed_fills | `processed_fills.parquet` | 单文件 (月数据 ~1GB) |
| 清单 | `archive_manifest.json` | 校验和 + schema + 统计 |
| 审计 | `archive_audit.db` (SQLite) | 操作历史 |

### 6.3 archive_manifest.json 格式

```json
{
  "archive_date": "2026-05-01T02:00:00Z",
  "year": 2025,
  "month": 12,
  "tables": {
    "raw_bdib": {
      "files": ["raw_bdib_part-0.parquet", ..., "raw_bdib_part-7.parquet"],
      "row_count": 98765432,
      "size_bytes": 1234567890,
      "sha256": "a1b2c3d4e5f6...",
      "compression": "zstd",
      "schema_md5": "f1e2d3c4b5a6...",
      "date_range": {"start": "2025-12-01", "end": "2025-12-31"}
    },
    "processed_fills": {
      "files": ["processed_fills.parquet"],
      "row_count": 654321,
      "size_bytes": 987654321,
      "sha256": "b2c3d4e5f6a7...",
      ...
    }
  },
  "pipeline_version": "v1.0",
  "source_config_md5": "c3d4e5f6a7b8..."
}
```

### 6.4 归档审计表 Schema

```sql
-- archive_audit.db
CREATE TABLE archive_runs (
    run_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_timestamp   TEXT NOT NULL DEFAULT (datetime('now')),
    year            INTEGER NOT NULL,
    month           INTEGER NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('running','success','failed','rolled_back')),
    rows_archived   INTEGER,
    bytes_archived  INTEGER,
    duration_sec    REAL,
    error_message   TEXT,
    config_snapshot TEXT     -- JSON of tiering_config.json at time of run
);

CREATE TABLE archive_table_log (
    log_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER NOT NULL REFERENCES archive_runs(run_id),
    table_name      TEXT NOT NULL,
    rows_archived   INTEGER,
    rows_purged     INTEGER,
    sha256_checksum TEXT,
    parquet_path    TEXT NOT NULL
);

CREATE INDEX idx_archive_runs_year_month ON archive_runs(year, month);
```

### 6.5 数据完整性校验

每次归档周期执行三级校验:

| 级别 | 校验内容 | 方法 | 时机 |
|------|---------|------|------|
| L1 | Parquet 文件完整性 | 读取每个 row group 的 footer checksum | 写入时 + 读取时 |
| L2 | 行数一致性 | SQLite COUNT(*) vs Parquet COUNT(*) | 归档提交前 |
| L3 | 抽样列值校验 | SQLite SUM(close) vs Parquet SUM(close) (误差 < 0.01%) | 归档提交前 |

```python
def verify_archive_integrity(
    hot_conn, parquet_path: Path, table: str, date_condition: str
) -> bool:
    """三级校验: 归档后的数据与 Hot 源一致."""
    # L1: Parquet footer checksum (自动由 PyArrow 处理)
    # L2: 行数对比
    hot_rows = hot_conn.execute(
        f"SELECT COUNT(*) FROM {table} WHERE {date_condition}"
    ).fetchone()[0]
    cold_rows = pq.read_metadata(parquet_path).num_rows
    if hot_rows != cold_rows:
        raise DataIntegrityError(
            f"Row count mismatch: hot={hot_rows}, cold={cold_rows}"
        )
    # L3: 关键列 SUM 对比
    hot_sum = hot_conn.execute(
        f"SELECT COALESCE(SUM(close), 0) FROM {table} WHERE {date_condition}"
    ).fetchone()[0]
    cold_sum = pq.read_table(parquet_path, columns=["close"])["close"].sum().as_py()
    if abs(hot_sum - cold_sum) / max(abs(hot_sum), 1) > 0.0001:
        raise DataIntegrityError(
            f"SUM(close) mismatch: hot={hot_sum}, cold={cold_sum}"
        )
    return True
```

---

## 7. 统一查询路由层 (UnifiedReader)

### 7.1 架构定位

`UnifiedReader` 是 Hot/Cold 两层存储的单一查询入口, 屏蔽存储细节, 对上层 (TCA / Regime / Attribution / Research) 透明。

### 7.2 接口设计

```python
"""
CostView/src/storage/unified_reader.py

统一查询接口 — 透明路由 Hot SQLite / Cold Parquet.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import pyarrow.parquet as pq

from DataPipeline.src.common.processing_config import ProcessingConfig as Config
from DataPipeline.src.storage.connection import ConnectionManager, AccessTier

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TieringConfig:
    """分层配置, 从 tiering_config.json 加载."""
    hot_window_days_raw_bdib: int = 50
    hot_window_days_processed_raw_bdib: int = 50
    hot_window_days_fill_bdib: int = 90
    hot_window_days_processed_fills: int = 120
    archive_root: Path = Config.DATA_DIR / "archive"
    parquet_compression: str = "zstd"
    parquet_row_group_size: int = 512 * 1024 * 1024  # 512 MB


class UnifiedReader:
    """统一读取接口 — 自动在 Hot (SQLite) 与 Cold (Parquet) 间路由查询.

    使用模式:
        reader = UnifiedReader()

        # 与现有 Repository 接口兼容
        df = reader.get_bdib_bars_for_date("AAPL", "2026-04-15")      # Hot only
        df = reader.get_bdib_bars_for_date("AAPL", "2025-11-15")      # Cold only
        df = reader.get_bdib_bars_for_range(
            ["AAPL", "MSFT"], "2025-10-01", "2026-04-15"               # Hot + Cold 合并
        )
    """

    def __init__(
        self,
        connection_manager: Optional[ConnectionManager] = None,
        tiering_config: Optional[TieringConfig] = None,
    ):
        self._mgr = connection_manager or ConnectionManager()
        self._config = tiering_config or TieringConfig()
        self._cold_cutoff = self._compute_cold_cutoff()

    # ── Hot/Cold 判断逻辑 ──────────────────────────────────────────────────

    def _compute_cold_cutoff(self) -> date:
        """计算冷热分界日期 (基于 raw_bdib 窗口)."""
        # Hot 窗口 = 50 交易日 ≈ 70 日历日 (含周末)
        return date.today() - timedelta(days=self._config.hot_window_days_raw_bdib * 1.4)

    def _is_hot_date(self, d: str | date) -> bool:
        """判断给定日期是否在 Hot 层."""
        d = date.fromisoformat(d) if isinstance(d, str) else d
        return d >= self._cold_cutoff

    def _split_date_range(self, start: str, end: str) -> tuple[Optional[tuple], Optional[tuple]]:
        """将查询范围拆分为 Hot 段和 Cold 段.

        Returns:
            (hot_range, cold_range): 每个元素是 (start, end) 或 None
        """
        start_d = date.fromisoformat(start)
        end_d = date.fromisoformat(end)

        hot_start = max(start_d, self._cold_cutoff)
        hot_range = (hot_start.isoformat(), end) if hot_start <= end_d else None

        cold_end = min(end_d, self._cold_cutoff - timedelta(days=1))
        cold_range = (start, cold_end.isoformat()) if start_d <= cold_end else None

        return hot_range, cold_range

    # ── 核心查询方法 ────────────────────────────────────────────────────────

    def get_bdib_bars_for_date(
        self, equ_ticker: str, trade_date: str
    ) -> pd.DataFrame:
        """获取单 ticker 单日的 BDIB bars — 自动路由. """
        if self._is_hot_date(trade_date):
            return self._query_hot_bdib(trade_date, equ_ticker)
        else:
            return self._query_cold_bdib(trade_date, equ_ticker)

    def get_bdib_bars_for_range(
        self, equ_tickers: list[str],
        start_date: str, end_date: str,
    ) -> pd.DataFrame:
        """获取多 ticker 多日的 BDIB bars — 合并 Hot + Cold 结果. """
        hot_range, cold_range = self._split_date_range(start_date, end_date)

        frames = []
        if hot_range:
            frames.append(
                self._query_hot_bdib_range(equ_tickers, *hot_range)
            )
        if cold_range:
            frames.append(
                self._query_cold_bdib_range(equ_tickers, *cold_range)
            )

        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True).sort_values(
            ["equ_ticker", "order_as_of_date", "mkt_timestamp"]
        )

    # ── Hot 查询 (委派给现有 Repository) ──────────────────────────────────

    def _query_hot_bdib(self, trade_date: str, equ_ticker: str) -> pd.DataFrame:
        from DataPipeline.src.storage.repositories.market_data_read import \
            SqliteMarketDataReadRepository
        repo = SqliteMarketDataReadRepository(self._mgr)
        return repo.get_bdib_bars_for_date(equ_ticker, trade_date)

    def _query_hot_bdib_range(
        self, equ_tickers: list[str], start: str, end: str
    ) -> pd.DataFrame:
        from DataPipeline.src.storage.repositories.market_data_read import \
            SqliteMarketDataReadRepository
        repo = SqliteMarketDataReadRepository(self._mgr)
        return repo.get_bdib_bars_for_tickers_and_dates(equ_tickers, start, end)

    # ── Cold 查询 (Parquet 谓词下推) ──────────────────────────────────────

    def _query_cold_bdib(self, trade_date: str, equ_ticker: str) -> pd.DataFrame:
        """从 Parquet 读取单 ticker 单日数据, 利用分区剪枝 + 谓词下推."""
        d = date.fromisoformat(trade_date)
        partition = (
            self._config.archive_root
            / f"year={d.year}"
            / f"month={d.month:02d}"
        )
        if not partition.exists():
            return pd.DataFrame()

        # 谓词下推: 只扫描匹配的 row group
        filters = [
            ("equ_ticker", "=", equ_ticker),
            ("order_as_of_date", "=", trade_date),
        ]
        table = pq.read_table(
            str(partition),
            filters=filters,
            use_pandas_metadata=True,
        )
        return table.to_pandas()

    def _query_cold_bdib_range(
        self, equ_tickers: list[str], start: str, end: str
    ) -> pd.DataFrame:
        """从 Parquet 读取多 ticker 日期范围, 分区剪枝 + 谓词下推."""
        # 解析涉及的分区
        months = self._iter_year_months(start, end)
        frames = []
        for year, month in months:
            partition = (
                self._config.archive_root
                / f"year={year}"
                / f"month={month:02d}"
            )
            if not partition.exists():
                continue
            filters = [
                ("equ_ticker", "in", equ_tickers),
                ("order_as_of_date", ">=", start),
                ("order_as_of_date", "<=", end),
            ]
            table = pq.read_table(
                str(partition),
                filters=filters,
                use_pandas_metadata=True,
            )
            frames.append(table.to_pandas())

        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)

    @staticmethod
    def _iter_year_months(start: str, end: str):
        """迭代 (year, month) 范围."""
        start_d = date.fromisoformat(start)
        end_d = date.fromisoformat(end)
        current = start_d.replace(day=1)
        while current <= end_d:
            yield current.year, current.month
            # 下个月
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)
```

### 7.3 与现有 Repository 的集成策略

**短期方案** — `UnifiedReader` 封装现有 Repository:

```
调用方 (TCA/Regime/Attribution)
    │
    ├─→ UnifiedReader (新)
    │       ├─→ Hot: 委派 SqliteMarketDataReadRepository (现有)
    │       └─→ Cold: 直接读 Parquet (新)
    │
    └─→ 现有 Repository (未修改, 仅适配 Hot 窗口)
```

**中期方案** — Repository 层注入统一数据源:

```python
# 改造后的 Repository 构造函数可选数据源
class SqliteMarketDataReadRepository(BaseRepository):
    def __init__(self, connection_manager=None, unified_reader=None):
        super().__init__(connection_manager, database="raw_bdib")
        self._unified = unified_reader

    def get_bdib_bars_for_date(self, equ_ticker, trade_date):
        if self._unified:
            return self._unified.get_bdib_bars_for_date(equ_ticker, trade_date)
        # fallback to direct SQLite (for backward compat)
        return super().get_bdib_bars_for_date(equ_ticker, trade_date)
```

**远期方案** — 废弃旧 Repository, UnifiedReader 成为唯一入口。

### 7.4 性能关键路径: Parquet 谓词下推

当 `pyarrow.parquet.read_table(filters=...)` 时, Parquet 引擎自动执行:

1. **分区级剪枝**: 跳过不匹配的 `year=YYYY/month=MM/` 目录 (无 IO)
2. **文件级剪枝**: 读取 parquet 文件统计信息 (min/max per column), 跳过不含匹配 ticker 的 row group
3. **Row group 级剪枝**: 读取每个 row group 的 column chunk 统计, 跳过不匹配的 group
4. **列投影**: 仅加载查询需要的列 (例如仅 `close, volume` 用于 VWAP 重建)

```
查询: WHERE equ_ticker='AAPL' AND order_as_of_date='2025-12-15'
                    │
                    ▼
┌─────────────────────────────────────────┐
│ 1. 分区剪枝 (无 IO)                      │
│    year=2025/month=09/ → 不包含 12-15   │ 跳过
│    ...                                  │
│    year=2025/month=12/ → 包含 12-15     │ ✓
└─────────────────┬───────────────────────┘
                  ▼
┌─────────────────────────────────────────┐
│ 2. Row group 剪枝 (~10ms)               │
│    rg-0: ticker ∈ [A, B] → 匹配        │ ✓
│    rg-1: ticker ∈ [C, D] → 不匹配      │ 跳过
│    rg-2: ticker ∈ [A, C] → 匹配        │ ✓
│    8/24 row groups 匹配                 │
└─────────────────┬───────────────────────┘
                  ▼
┌─────────────────────────────────────────┐
│ 3. 列投影 + ZSTD 解压 (~50ms)           │
│    仅解压 equ_ticker, close, volume     │
│    跳过 num_trds, value, source 等      │
└─────────────────┬───────────────────────┘
                  ▼
         返回 ~2340 rows (10-sec bars × 6.5h)
```

### 7.5 Hot 窗口自动调整逻辑

为确保 Hot 层始终 ≤25GB, `UnifiedReader` 可在启动时检测 raw_bdib.db 大小并自动建议窗口调整:

```python
def auto_tune_hot_window(self) -> int:
    """根据当前 raw_bdib.db 大小自动计算最佳 Hot 窗口."""
    db_path = self._mgr.get_path("raw_bdib")
    size_gb = db_path.stat().st_size / (1024**3)

    # 目标: raw_bdib.db ≤ 23GB (保留 2GB 余量给 WAL + 增长)
    target_gb = 23
    if size_gb <= target_gb:
        return self._config.hot_window_days_raw_bdib  # 维持当前窗口

    # 超标的压缩比例
    shrink_ratio = target_gb / size_gb
    new_window = int(self._config.hot_window_days_raw_bdib * shrink_ratio)
    logger.warning(
        f"Hot raw_bdib.db {size_gb:.1f}GB exceeds target {target_gb}GB. "
        f"Suggest reducing hot window from {self._config.hot_window_days_raw_bdib}d "
        f"to {new_window}d. Run: python -m CostView archive tune --window {new_window}"
    )
    return new_window
```

---

## 8. 性能分析

### 8.1 查询性能对比 (理论推算)

| 查询场景 | 当前 SQLite | 分层后 (Hot) | 分层后 (Cold) | 提升倍数 |
|---------|-----------|-------------|--------------|---------|
| 单 ticker 单日 BDIB bars | ~200 ms | ~200 ms | ~80 ms | 1-2.5x |
| 多 ticker 月范围 (attribution) | ~12 s | ~2 s (Hot 当月) | ~1.5 s (Cold 历史) | **6-8x** |
| 全量 attribution backfill | ~2 h | ~15 min (仅 Hot 窗口) | ~25 min (Cold Parquet + 并行) | **3-4x** |
| 全量 regime fill tagging | ~7 min (429s) | ~90s (Hot 裁剪后) | ~120s (Cold 并行) | **2-3x** |
| VWAP 重建 (全量) | ~45 min | ~8 min (Hot 窗口) | ~12 min (列投影 + 并行) | **3-5x** |
| Cohort scorecard (大范围) | ~30 s | ~5 s | ~8 s | **3-6x** |
| 研究快照导出 | 无此功能 | N/A | ~30s (直接 Parquet 切片) | **新能力** |

### 8.2 性能提升来源量化

| 优化机制 | 提升因子 | 适用场景 | 原理 |
|---------|---------|---------|------|
| 列投影 (Column Projection) | **3-8x** | VWAP 重建, attribution | 只读需要的列, 跳过无关列 IO |
| 分区剪枝 (Partition Pruning) | **2-10x** | 指定日期范围的查询 | 跳过不匹配的年/月目录 |
| Row group 剪枝 (Statistics) | **2-4x** | 指定 ticker 的查询 | 跳过不含目标 ticker 的 row group |
| ZSTD 解压带宽 × IO 减少 | **2-3x** | 大范围扫描 | 读更少的字节, 解压速度 > 磁盘 IO |
| Covering index | **5-10x** | ticker+date 点查 | 索引覆盖返回所有需要的列 |
| Hot 窗口缩小 | **2-3x** | 全量处理 | 需要扫描的行数减少 |

**复合效应**: 同时应用列投影 + 分区剪枝 + ZSTD 时, 查询加速不是简单相加而是相乘:
- 列投影: 跳过 60% 的列 → 3x
- 分区剪枝: 跳过 80% 的月 → 5x
- 总加速: 3 × 5 = **15x** (理论上限, 实际受 CPU 解压瓶颈限制约 3-10x)

### 8.3 存储占用对比

```
当前 (无分层):
  raw_bdib.db      68.5 GB
  processed_fills  14.6 GB
  fill_bdib         2.0 GB
  其他              5.5 GB
  ──────────────────────
  总计             ~88 GB

  日增量: ~600 MB/日
  年增量: ~150 GB/年
  磁盘寿命: ~6 个月 (1TB 磁盘, 已用 68 GB, 日增 600 MB)

══════════════════════════════════════════

分层后 (立即效果 — 2026-05 迁移完成):
  Hot:
    raw_bdib.db (50d)  ~23.0 GB
    processed_fills    ~14.6 GB (全部)
    fill_bdib (90d)    ~2.0 GB (全部)
    其他               ~5.5 GB
    ───────────────────
    Hot 总计           ~45 GB

  Cold (Parquet ZSTD):
    raw_bdib (history) ~11.0 GB  (从 45 GB→11 GB, 4x 压缩)
    ───────────────────
    Cold 总计          ~11 GB

  新总存储: ~45 GB + 11 GB = ~56 GB (较 88 GB 减少 36%)

══════════════════════════════════════════

分层后 (5 年累计 — 年增量 600MB × 250 交易日 × 5 年 ≈ 750 GB 原始):
  新数据直接写入 Hot SQLite, 每月滚动归档到 Cold Parquet

  Hot: raw_bdib.db ~23 GB (50 天窗口固定) + 其他不变 ≈ ~45 GB (有界!)
  Cold: 约 600 MB/日 × 250 日 × 5 年 / 4 (ZSTD 压缩比) = ~187.5 GB
         + 其他表归档 ≈ 60 GB
         Cold 总计 ≈ ~248 GB

  5 年总存储: ~45 GB (有界 Hot) + ~248 GB (Cold 增长) ≈ ~293 GB
  无分层 5 年: >800 GB (线性增长)

  结论: 分层后 5 年总存储控制在 300GB 以内, 磁盘寿命从 6 个月延长至 10+ 年
```

### 8.4 查询延迟分解 (Benchmark 基准测试设计)

验证性能提升需运行以下基准测试:

```python
# benchmark_storage_tiering.py (基准测试框架)

def benchmark_query_suite():
    """分层前后的查询延迟对比基准测试."""

    suite = [
        # (name, query_fn, description)
        ("bdib_single_ticker_date",
         lambda: reader.get_bdib_bars_for_date("AAPL", hot_date),
         "单 ticker 单日 (Hot)"),

        ("bdib_single_ticker_date_cold",
         lambda: reader.get_bdib_bars_for_date("AAPL", cold_date),
         "单 ticker 单日 (Cold)"),

        ("bdib_multi_ticker_month",
         lambda: reader.get_bdib_bars_for_range(
             top_10_tickers, hot_month_start, hot_month_end),
         "10 ticker 月范围 (Hot)"),

        ("bdib_multi_ticker_month_cold",
         lambda: reader.get_bdib_bars_for_range(
             top_10_tickers, cold_month_start, cold_month_end),
         "10 ticker 月范围 (Cold)"),

        ("vwap_reconstruct_month",
         lambda: reconstruct_vwap(reader, top_100_tickers, hot_month),
         "VWAP 重建月范围 (Hot)"),

        ("vwap_reconstruct_quarter_cold",
         lambda: reconstruct_vwap(reader, top_100_tickers, cold_quarter),
         "VWAP 重建季度 (Cold)"),

        ("full_attribution_backfill",
         lambda: run_attribution_backfill(reader, cold_quarter),
         "全量 attribution backfill (Cold)"),
    ]

    results = []
    for name, fn, desc in suite:
        times = []
        for _ in range(5):  # 5 次运行取中位数
            start = time.perf_counter()
            fn()
            times.append(time.perf_counter() - start)
        median = sorted(times)[len(times)//2]
        results.append((name, desc, median))

    return results
```

---

## 9. 实施步骤

### 9.1 总体里程碑

```
Phase 0: 基础设施  (3 天)  ──→  Tier 0.5: 可演练单月归档
Phase 1: 核心引擎  (5 天)  ──→  Tier 1.0: UnifiedReader + ArchiveManager
Phase 2: 全量迁移  (3 天)  ──→  Tier 1.5: 88GB → Hot + Cold 在线
Phase 3: 生产加固  (4 天)  ──→  Tier 2.0: Cron 自动化 + 审计 + CLI
────────────────────────────────────────────────
总计: 15 天
```

### 9.2 Phase 0 — 基础设施 (3 天)

#### Day 1-2: 新建存储层包

```
CostView/src/storage/
├── __init__.py
├── tiering_config.py      ← 分层配置 (窗口大小、路径、压缩参数)
├── unified_reader.py      ← 统一查询接口 (Hot→SQLite, Cold→Parquet)
├── archive_manager.py     ← 归档编排 (全量迁移 + 月度增量)
├── parquet_archive.py     ← Parquet 读写 + 分区管理 + 校验
├── archive_audit.py       ← 归档审计表 + 完整性验证
└── tiering_cli.py         ← CLI 命令 (archive/purge/tune/snapshot/status)
```

**tiering_config.py** 详细设计:

```python
from dataclasses import dataclass, asdict
from pathlib import Path
import json

@dataclass
class TieringConfig:
    # Hot 窗口 (交易天数)
    hot_window_raw_bdib: int = 50
    hot_window_processed_raw_bdib: int = 50
    hot_window_fill_bdib: int = 90
    hot_window_processed_fills: int = 120

    # 冷存储
    archive_root: Path = Config.DATA_DIR / "archive"
    parquet_compression: str = "zstd"
    parquet_compression_level: int = 3
    parquet_row_group_size: int = 512 * 1024 * 1024

    # 安全缓冲 (额外保留的天数, 避免误删)
    retention_buffer_days: int = 30

    # Cold 查询并行度
    max_parquet_readers: int = 4

    def save(self, path: Path = None):
        path = path or Config.DATA_DIR / "tiering" / "tiering_config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def load(cls, path: Path = None) -> "TieringConfig":
        path = path or Config.DATA_DIR / "tiering" / "tiering_config.json"
        if path.exists():
            return cls(**json.loads(path.read_text()))
        return cls()  # 默认值
```

#### Day 2-3: 依赖安装 + 测试夹具

```bash
# 依赖
pip install pyarrow>=14.0 pandas>=2.0
```

```python
# 测试夹具: 单月 Parquet 归档
@pytest.fixture
def archive_fixture(tmp_path):
    """创建单月 BDIB 数据的 Parquet 归档用于测试. """
    year, month = 2025, 12
    archive_dir = tmp_path / "archive" / f"year={year}" / f"month={month:02d}"
    archive_dir.mkdir(parents=True)

    # 生成模拟 12 月的 BDIB 数据 (22 个交易日 × 100 ticker × 2340 bars/日)
    rows = generate_mock_bdib_bars(
        num_tickers=100, num_days=22, bars_per_day=2340
    )
    table = pa.Table.from_pandas(rows)
    pq.write_to_dataset(
        table,
        root_path=str(archive_dir),
        partitioning=["equ_ticker"],  # ticker 首字母分区
        compression="zstd",
        row_group_size=512 * 1024 * 1024,
    )
    return archive_dir
```

### 9.3 Phase 1 — 核心引擎 (5 天)

#### Day 4-5: `parquet_archive.py` — Parquet 读写层

```python
"""
parquet_archive.py — Parquet 归档读写 + 分区管理 + 原子提交.
"""

def write_month_to_parquet(
    table: str,
    df: pd.DataFrame,
    year: int,
    month: int,
    config: TieringConfig,
) -> ArchiveResult:
    """将单月 DataFrame 原子写入 Parquet 归档.

    流程:
    1. 写入 .tmp 目录 (避免破损)
    2. 校验完整性 (行数 + SHA-256)
    3. 重命名 .tmp → 正式目录 (原子操作)
    """
    tmp_root = config.archive_root / ".tmp"
    final_root = config.archive_root / f"year={year}" / f"month={month:02d}"

    if table == "raw_bdib":
        _write_raw_bdib_partitioned(df, tmp_root, config)
    else:
        _write_single_file(df, tmp_root / f"{table}.parquet", config)

    # 原子提交
    if final_root.exists():
        shutil.rmtree(str(final_root))
    tmp_root.rename(str(final_root))

    # 更新 archive_manifest.json
    update_manifest(year, month, table, final_root / f"{table}.parquet")


def _write_raw_bdib_partitioned(
    df: pd.DataFrame, output_dir: Path, config: TieringConfig
) -> list[Path]:
    """将 raw_bdib 按月写入多个 Parquet 分区文件 (ticker 首字母分区).

    分区策略:
    - equ_ticker 首字母 a-e → part-0, f-j → part-1, ..., u-z → part-5
    - 确保每个 part 文件大小 ~500MB, 支持并行读取
    """
    # 按 ticker 首字母分组
    df["_ticker_prefix"] = df["equ_ticker"].str[0].str.lower()
    partitions = {
        "a-e": ("a", "b", "c", "d", "e"),
        "f-j": ("f", "g", "h", "i", "j"),
        "k-o": ("k", "l", "m", "n", "o"),
        "p-t": ("p", "q", "r", "s", "t"),
        "u-z": ("u", "v", "w", "x", "y", "z"),
    }

    files = []
    for part_name, letters in partitions.items():
        subset = df[df["_ticker_prefix"].isin(letters)]
        if subset.empty:
            continue
        file_path = output_dir / f"raw_bdib_part-{part_name}.parquet"
        subset.drop(columns=["_ticker_prefix"]).to_parquet(
            str(file_path),
            compression=config.parquet_compression,
            row_group_size=config.parquet_row_group_size,
        )
        files.append(file_path)

    return files
```

#### Day 5-6: `unified_reader.py` — 统一查询引擎

(详见第 7 节设计, 此处略)

#### Day 6-7: `archive_manager.py` — 归档编排

```python
"""
archive_manager.py — 归档流程编排.
"""

class ArchiveManager:
    """管理全量迁移 + 增量月度归档 + Hot 层裁剪."""

    def __init__(self, config: TieringConfig):
        self._config = config
        self._mgr = ConnectionManager()

    def archive_month(
        self, year: int, month: int, tables: Optional[list[str]] = None
    ) -> dict[str, ArchiveResult]:
        """归档单月数据."""
        tables = tables or ["raw_bdib", "processed_raw_bdib",
                            "fill_bdib", "processed_fills"]
        results = {}
        for table_name in tables:
            result = self._archive_single_table(table_name, year, month)
            results[table_name] = result
            if not result.success:
                logger.error(f"Failed to archive {table_name} {year}-{month}: {result.error}")
                # 不中断其他表的归档
        return results

    def _archive_single_table(
        self, table_name: str, year: int, month: int
    ) -> ArchiveResult:
        """提取单表 → Parquet → 校验 → 提交."""
        start = time.perf_counter()
        try:
            # 1. 从 SQLite 提取数据
            hot_conn = self._mgr.get_connection(
                self._table_to_db(table_name), AccessTier.READ
            )
            date_start, date_end = get_month_date_range(year, month)
            df = pd.read_sql_query(
                f"SELECT * FROM {table_name} "
                "WHERE order_as_of_date >= ? AND order_as_of_date <= ? "
                "ORDER BY equ_ticker, mkt_timestamp",
                hot_conn.raw_connection,
                params=[date_start, date_end],
            )
            hot_conn.close()

            if df.empty:
                return ArchiveResult(table_name, year, month, rows=0, success=True)

            # 2. 写入 Parquet
            write_month_to_parquet(table_name, df, year, month, self._config)

            # 3. 校验
            verify_archive_integrity_parquet(table_name, year, month, self._config)

            elapsed = time.perf_counter() - start
            return ArchiveResult(
                table_name, year, month,
                rows=len(df), size_bytes=estimate_size(df),
                duration_sec=elapsed, success=True,
            )
        except Exception as e:
            return ArchiveResult(
                table_name, year, month,
                success=False, error=str(e),
            )

    def trim_hot_tier(self, cutoff_date: str) -> TrimReport:
        """裁剪 Hot 层中已归档的旧数据."""
        report = TrimReport()
        for table, db in self._table_db_map().items():
            window = self._config.get_window(table)
            effective_cutoff = compute_window_cutoff(window)
            deleted = self._delete_before(table, db, effective_cutoff)
            report.add(table, deleted)
        return report
```

#### Day 7-8: `archive_audit.py` — 审计与校验

```python
"""
archive_audit.py — 归档审计 + 校验.
"""

class ArchiveAuditor:
    """归档完整性审计与校验."""

    AUDIT_DB = Config.DATA_DIR / "tiering" / "archive_audit.db"

    def __init__(self):
        self._ensure_schema()

    def _ensure_schema(self):
        conn = sqlite3.connect(str(self.AUDIT_DB))
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS archive_runs (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_timestamp TEXT NOT NULL DEFAULT (datetime('now')),
                year INTEGER NOT NULL, month INTEGER NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('running','success','failed','rolled_back')),
                rows_archived INTEGER, bytes_archived INTEGER,
                duration_sec REAL, error_message TEXT,
                config_snapshot TEXT
            );
            CREATE TABLE IF NOT EXISTS archive_table_log (
                log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL REFERENCES archive_runs(run_id),
                table_name TEXT NOT NULL,
                rows_archived INTEGER, rows_purged INTEGER,
                sha256_checksum TEXT, parquet_path TEXT NOT NULL
            );
        """)
        conn.commit()
        conn.close()

    def verify_archive(self, year: int, month: int) -> AuditReport:
        """离线校验已归档数据完整性."""
        issues = []
        for table in TIERING_TABLES:
            parquet_path = self._resolve_parquet_path(table, year, month)
            if not parquet_path.exists():
                issues.append(f"Missing: {parquet_path}")
                continue
            # 读取 Parquet 统计信息
            meta = pq.read_metadata(parquet_path)
            # 校验: 读取前 1000 行确保无损坏
            try:
                sample = pq.read_table(parquet_path, stop=1000)
            except Exception as e:
                issues.append(f"Corrupt: {parquet_path}: {e}")
        return AuditReport(year=year, month=month, passed=len(issues)==0, issues=issues)
```

### 9.4 Phase 2 — 全量迁移 (3 天)

#### Day 9-10: 单月演练 (选 2026-01 月数据)

```bash
# Step 1: 演练 → 1 月数据从 SQLite → Parquet
python -m CostView archive migrate --year 2026 --month 01 --dry-run
# 验证: 检查 Parquet 文件生成、行数、校验和

# Step 2: 实际执行
python -m CostView archive migrate --year 2026 --month 01

# Step 3: 验证 Hot 层裁剪
python -m CostView archive verify --year 2026 --month 01

# Step 4: 集成测试 — 通过 UnifiedReader 查询 1 月数据
python -m pytest tests/test_unified_reader.py -v
```

#### Day 10-11: 全量迁移脚本

```bash
# 全量迁移: 2025-09 至 2026-02 (共 6 个月)
python -m CostView archive migrate-full

# 过程:
#   2025-09 → 2.3 分钟
#   2025-10 → 2.5 分钟
#   2025-11 → 2.4 分钟
#   2025-12 → 2.6 分钟
#   2026-01 → 2.5 分钟
#   2026-02 → 2.6 分钟
#   ───────────────────
#   总计: ~15 分钟 (并行 3 表/月)

# 迁移完成后:
python -m CostView archive verify          # 全量校验
python -m CostView archive status          # 查看分层状态
```

#### Day 11: 数据校验 + 回归测试

```bash
# 1. 行数一致性校验 (所有已归档月)
python -m CostView archive verify --all

# 2. 关键查询回归测试
python tests/test_tca_query_service.py -v
python tests/test_regime_e2e.py -v
python tests/test_attribution.py -v
python tests/test_pipeline_guards.py -v

# 3. 性能基准测试
python bench/storage_tiering_benchmark.py
```

### 9.5 Phase 3 — 生产加固 (4 天)

#### Day 12: CLI 命令

扩展 `CostView/src/__main__.py`, 新增 `archive` 命令组:

```python
# __main__.py 新增
@main_group.group()
def archive():
    """存储分层管理命令."""
    pass

@archive.command()
@click.option("--year", type=int, required=True)
@click.option("--month", type=int, required=True)
@click.option("--tables", default=None)
@click.option("--dry-run", is_flag=True)
def migrate(year, month, tables, dry_run):
    """归档单月数据到 Parquet."""
    manager = ArchiveManager(TieringConfig.load())
    result = manager.archive_month(year, month, tables)
    click.echo(format_result(result))

@archive.command()
def migrate_full():
    """全量历史数据迁移."""
    manager = ArchiveManager(TieringConfig.load())
    report = manager.archive_all_history()
    click.echo(format_report(report))

@archive.command()
@click.option("--window", type=int, default=None)
def tune(window):
    """自动调整或手动设置 Hot 窗口大小."""
    reader = UnifiedReader()
    if window:
        new_config = reader.set_hot_window(window)
    else:
        new_config = reader.auto_tune_hot_window()
    click.echo(f"New hot window: {new_config.hot_window_raw_bdib} days")

@archive.command()
@click.option("--start", default=None)
@click.option("--end", default=None)
@click.option("--tickers", default=None)
@click.option("--output", required=True)
def snapshot(start, end, tickers, output):
    """创建研究快照 (独立 Parquet 切片)."""
    pass

@archive.command()
def status():
    """查看分层状态 (Hot/Cold 大小、窗口、待归档月)."""
    pass

@archive.command()
@click.option("--all", is_flag=True)
def verify(all):
    """校验归档数据完整性."""
    pass
```

#### Day 13: Windows 任务计划程序集成

```xml
<!-- 月度归档任务定义 (schedule.xml) -->
<Task>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>2026-06-01T02:00:00</StartBoundary>
      <Repetition>
        <Interval>P1M</Interval>  <!-- 每月执行 -->
      </Repetition>
      <DayOfMonth>1</DayOfMonth>
    </CalendarTrigger>
  </Triggers>
  <Actions>
    <Exec>
      <Command>python</Command>
      <Arguments>-m CostView archive migrate --month-offset -2</Arguments>
      <WorkingDirectory>C:\Users\hrchen\Documents\EMSX</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
```

配套脚本 `scripts/schedule-archive.ps1`:

```powershell
# scripts/schedule-archive.ps1 — 注册 Windows 计划任务
$taskName = "EMSX-CostView-MonthlyArchive"
$scriptPath = "C:\Users\hrchen\Documents\EMSX"
$action = New-ScheduledTaskAction -Execute "python" `
    -Argument "-m CostView archive migrate --month-offset -2" `
    -WorkingDirectory $scriptPath
$trigger = New-ScheduledTaskTrigger -Monthly -DaysOfMonth 1 -At 02:00am
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -RunLevel Highest
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal
Write-Host "Monthly archive task '$taskName' registered."
```

#### Day 14: 集成测试 + 文档

```bash
# 集成测试
python -m pytest tests/ -v --cov=CostView.src.storage

# 性能基准测试
python bench/storage_tiering_benchmark.py --output docs/ops/tiering-benchmark-results.md
```

#### Day 15: 上线检查清单

- [ ] `tests/test_unified_reader.py` — 覆盖 Hot/Cold/Both 三种查询路径
- [ ] `tests/test_archive_manager.py` — 覆盖归档 + 回滚 + 断点续传
- [ ] `tests/test_parquet_archive.py` — 覆盖 Parquet 写入 + 校验 + 损坏检测
- [ ] `tests/test_tiering_cli.py` — 覆盖 CLI 所有子命令
- [ ] 性能基准测试结果已记录
- [ ] 归档审计表结构已创建
- [ ] Windows 计划任务已注册
- [ ] `tiering_config.json` 已生成
- [ ] 全量迁移已完成且校验通过
- [ ] Engineering improvement plan 状态已更新

---

## 10. 风险与缓解措施

### 10.1 风险矩阵

| 风险 | 概率 | 影响 | 缓解措施 | 应急方案 |
|------|------|------|---------|---------|
| Parquet 归档中写入失败 | 低 | 高 (数据丢失风险) | 原子提交 (先写.tmp, 再 rename); 归档前备份 | 保留 Hot 层完整数据, 重试归档 |
| UnifiedReader 性能退化 | 中 | 中 | 基准测试基线; 逐查询性能回归门禁 | 临时绕过 Cold 层, 强制 Hot 查询 |
| PyArrow 版本兼容性问题 | 低 | 中 | 锁定 pyarrow>=14.0; tests 覆盖关键路径 | pip install pyarrow==14.0.0 |
| Hot 层裁剪误删未归档数据 | 低 | 高 | 30 天缓冲期; 删除前 COUNT(*) 交叉校验 | 从 Parquet 反向恢复 (重建代价高) |
| WAL 文件在归档期间膨胀 | 中 | 低 | 归档前执行 checkpoint; 归档后 VACUUM | 手动 checkpoint 后重试 |
| 查询跨 Hot+Cold 合并延迟 | 中 | 低 | 并行读取 Hot/Cold; 异步 Future 合并 | 根据查询范围预判单层访问 |
| SQLite mmap 在 32-bit Python 上限 | 低 | 中 | 确认 Python 是 64-bit; 回退到 cache_size | cache_size 调优替代 |
| Research 快照含不一致数据 | 低 | 中 | 快照基于已归档的 Parquet (immutable) | 禁止从 Hot SQLite 直接切快照 |

### 10.2 回滚策略

若分层系统上线后发现问题, 可执行以下回滚:

```bash
# 回滚方案 A: 临时禁用 Cold 查询 (快速恢复)
export COSTVIEW_TIERING_DISABLE_COLD=1
# UnifiedReader 将跳过 Cold 查询, 所有请求回退到 Hot SQLite
# Hot 层仍包含窗口内的数据, 服务不中断

# 回滚方案 B: 从 Parquet 恢复 Hot SQLite (永久回退)
python -m CostView archive restore --year 2025 --month 10
# 将 Parquet 数据重新导入 SQLite (行数较少时可行)

# 回滚方案 C: 从备份恢复数据库文件
# 归档流程自动在 purge 前对 raw_bdib.db 执行 VACUUM INTO backup
```

### 10.3 监控与告警

```python
# 关键监控指标 (集成到日志 + 可选的 Prometheus 导出)
class TieringMetrics:
    # 1. Hot 层大小 → 接近 25GB 上限时告警
    # 2. Cold 查询延迟 p50/p95/p99
    # 3. 归档成功率 (archive_audit.db)
    # 4. 磁盘空间使用率
    # 5. UnifiedReader 路由正确性 (Hot/Cold 行数总和 = 预期)
    pass
```

---

## 11. 附录

### A. 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `CostView/src/storage/__init__.py` | **新建** | 包初始化 |
| `CostView/src/storage/tiering_config.py` | **新建** | 分层配置管理 |
| `CostView/src/storage/unified_reader.py` | **新建** | 统一查询引擎 |
| `CostView/src/storage/archive_manager.py` | **新建** | 归档编排 |
| `CostView/src/storage/parquet_archive.py` | **新建** | Parquet 读写 |
| `CostView/src/storage/archive_audit.py` | **新建** | 审计与校验 |
| `CostView/src/storage/tiering_cli.py` | **新建** | CLI 命令组 |
| `CostView/data/tiering/tiering_config.json` | **新建** | 分层配置持久化 |
| `CostView/data/tiering/archive_audit.db` | **新建** | 归档审计数据库 |
| `CostView/src/__main__.py` | **修改** | 注册 archive 命令组 |
| `DataPipeline/src/common/processing_config.py` | **修改** | 新增 ARCHIVE_DIR 等路径 |
| `DataPipeline/src/common/table_registry.py` | **修改** | 归档相关常量 (可选) |
| `DataPipeline/src/storage/connection.py` | **修改** | 新增 archive_audit DB 注册 |
| `scripts/schedule-archive.ps1` | **新建** | Windows 计划任务注册 |
| `tests/test_unified_reader.py` | **新建** | 统一读取单元测试 |
| `tests/test_archive_manager.py` | **新建** | 归档流程测试 |
| `tests/test_parquet_archive.py` | **新建** | Parquet 读写测试 |
| `tests/test_tiering_cli.py` | **新建** | CLI 测试 |
| `bench/storage_tiering_benchmark.py` | **新建** | 性能基准测试 |

### B. 依赖清单

```
# requirements.txt 新增
pyarrow>=14.0,<16.0       # Apache Parquet 读写 + 分区管理
pandas>=2.0.0             # DataFrame 接口 (已有, 验证版本)
```

> 无其他新增依赖。所有功能基于 Python 标准库 + PyArrow 实现。

### C. 与现有架构的兼容性分析

| 架构决策 | 兼容性 | 说明 |
|---------|--------|------|
| ConnectionManager | ✅ 兼容 | UnifiedReader 内部使用, Repository 保持未修改 |
| Repository pattern | ✅ 兼容 | 通过可选 `unified_reader` 参数注入, 向后兼容 |
| Pipeline stages | ✅ 兼容 | 仅读取接口变化, 写入仍通过现有途径到 SQLite |
| 4-layer schema prefix | ✅ 兼容 | 不影响 schema 设计 |
| Schema versioning | ✅ 兼容 | 不改变 migration 流程 |
| WAL mode | ✅ 兼容 | Hot SQLite 保持 WAL, Parquet 只读 |
| 现有索引 | ✅ 兼容 | Hot 层保留现有索引, Cold 层基于分区 |

### D. 术语表

| 术语 | 定义 |
|------|------|
| Hot Tier | SQLite 存储的近期高频访问数据 |
| Cold Tier | Parquet 分区存储的历史归档数据 |
| UnifiedReader | 透明路由 Hot/Cold 查询的统一接口 |
| Partition Pruning | 通过目录结构跳过不相关数据分区的优化 |
| Predicate Pushdown | 将 WHERE 条件推送到 Parquet 读取引擎减少 IO |
| Row Group | Parquet 文件内水平分区, 支持行级跳过 |
| Column Projection | 仅读取查询要求的列, 跳过无关列 |
| Covered Index | 索引包含查询所需全部列的索引 |
| ZSTD | Zstandard 压缩算法, 提供 3-5x 压缩比 |
| Archive Manifest | 每月归档目录中的元数据文件 (校验和、schema) |

### E. 参考文档

- [工程改进计划 P0a: 存储分层体系](../plans/engineering-improvement-plan.md)
- [项目功能构建规划 §11: 存储分层](项目功能构建规划.md)
- [架构指令: 模块拆分规则](../.github/instructions/architecture.instructions.md)
- [Apache Parquet 文档](https://parquet.apache.org/docs/)
- [PyArrow 分区写入指南](https://arrow.apache.org/docs/python/parquet.html#writing-to-partitioned-datasets)
- [SQLite 性能调优](https://www.sqlite.org/pragma.html)
