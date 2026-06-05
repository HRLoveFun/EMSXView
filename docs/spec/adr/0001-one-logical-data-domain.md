# ADR-0001: 一个逻辑数据域，多种存储技术

> 状态: Accepted
> 日期: 2026-06-03
> 标签: architecture, data

## 背景 (Context)

EMSXView 数据量达 134GB（8 个 SQLite 数据库文件），跨订单/行情/分析多种 workload。
单一 SQLite 已不堪重负（`raw_bdib.db` 单文件 78.7GB），但统一迁移到 PostgreSQL 也不合理
（BDIB 查询场景 DuckDB 列存引擎明显更快）。

需要在"数据所有权清晰"和"按 workload 选存储"之间取得平衡。

## 决策 (Decision)

- 一个逻辑数据域（logical data domain），但**不强求一个物理数据库**
- 四个数据子域（subdomain）按 workload 特征选择存储：
  - Execution operational state → PostgreSQL（强事务）
  - CostView analytical → SQLite + DuckDB/Parquet（列存 + OLAP）
  - 实时订单/路由投影 → in-memory fallback + 可选持久化
- 跨域访问**优先走 `platform_data/` 适配器**，避免深层直接 import

## 后果 (Consequences)

### 正面
- 各 workload 使用最合适的存储引擎
- 适配器模式隔离跨域耦合，演进某一域不影响其他域
- 数据所有权清晰（ADR-0003, 0004, 0006）

### 负面 / 取舍
- 学习成本：新人需理解"逻辑域 ≠ 物理存储"
- 适配器维护成本（每个跨域点需维护一个适配方法）
- 备份/恢复需按子域分别处理

## 备选方案 (Considered Alternatives)

- 方案 A: 全部迁 PostgreSQL
  - 否决原因: BDIB 列查询性能不及 DuckDB；事务开销对 analytical 场景浪费
- 方案 B: 全部 DuckDB
  - 否决原因: operational state 需要强事务 + 行级锁，DuckDB 弱于此场景
- 方案 C: 统一 TimeSeriesDB（TimescaleDB/QuestDB）
  - 否决原因: 改造成本过高；BDIB 数据迁移风险大

## 相关 ADR

- 引用: 无（基础决策）
- 被引用: [ADR-0002](0002-platform-data-adapter-pattern.md), [ADR-0003](0003-executionview-owns-operational-state.md), [ADR-0004](0004-costview-focused-on-evaluation.md), [ADR-0005](0005-data-pipeline-extraction.md), [ADR-0006](0006-dataplatform-as-independent-subdomain.md)

## 实施注意事项

- 配套规范: `docs/spec/data-domain.md`（数据子域详细边界）
- 配套规范: `.codebuddy/rules/module-boundary.md` §2.2（适配器可见性表）
- 配套偏差: 见 [ADR-0013](0013-platform-data-adapter-current-state.md)（docs 与实际代码偏差）
