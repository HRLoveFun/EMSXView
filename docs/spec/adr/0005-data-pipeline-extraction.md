# ADR-0005: Data Platform 子域从 CostView 抽取

> 状态: Accepted
> 日期: 2026-05-07
> 标签: refactoring, data, architecture

## 背景 (Context)

历史 `CostView/src/` 包含数据采集、处理、存储基础设施：
- `fill_fetch.py` / `fill_ingestion.py` — fill 摄取
- `fill_cleaner.py` / `fill_processor.py` / `fill_aggregator.py` — 清洗与聚合
- `bdib_fetcher.py` — BDIB 行情抓取
- `raw_fills_db.py` / `raw_bdib_db.py` / `fill_bdib_db.py` / `processed_raw_bdib_db.py` / `processed_fills_db/` — 数据库类
- `daily_metrics_calculator.py` — 日线指标
- `pipeline.py` — 流水线编排
- `db/connection.py` / `db/repositories/` / `db/schema/` / `db/protocols.py` / `db/dto.py` — DB 子系统

这些**不属于**"算法评估"职责（ADR-0004），却占用 `CostView.src.*` 命名空间，导致：
- ExecutionView 误把 CostView 内部当持久化层
- 跨域 deep import 泛滥
- "CostView 是什么"无法一句话回答

## 决策 (Decision)

将上述所有数据基础设施**抽取到独立子域** `DataPipeline/`，组织结构：

```
DataPipeline/
├── acquisition/      # BDIB / EMSX 数据采集
├── ingestion/        # 入库
├── processing/       # 清洗、聚合、衍生指标
├── analysis/         # TCA、regime、归因
├── storage/          # DB schema、连接、repository
├── orchestration/    # 流水线编排
├── common/           # 公共工具（配置、时区、映射）
└── config.py         # 配置中心
```

- `CostView/src/db/` 保留为**薄 re-export 层**，逐步废弃
- 所有 DataPipeline 模块 import 限定在 `DataPipeline.*` 内部
- 跨域访问通过 `platform_data.data_platform.*` 暴露
- `Config` 单一来源：所有 DB 路径、表名从 `DataPipeline/config.py` 读取

## 后果 (Consequences)

### 正面
- CostView 命名空间干净，只剩算法与分析
- DataPipeline 独立版本演进（pip `-e .` 安装）
- 跨域 deep import 物理上不可能（包路径不同）

### 负面 / 取舍
- 需要维护 `CostView/src/db/` re-export 过渡层
- 已有调用方需迁移 import 路径（已分批完成）
- 包安装复杂度（多个 `-e .` 安装）

## 备选方案 (Considered Alternatives)

- 方案 A: 保留在 CostView 内部但用目录隔离
  - 否决原因: import 路径仍可绕过；命名空间污染未根除
- 方案 B: 直接合并到 `platform_data/`
  - 否决原因: `platform_data` 应保持"轻适配层"职责，避免成为大杂烩
- 方案 C: 引入 K8s/Argo 等外部编排器
  - 否决原因: 改造成本与复杂度不成正比

## 相关 ADR

- 引用: [ADR-0001](0001-one-logical-data-domain.md), [ADR-0004](0004-costview-focused-on-evaluation.md)
- 被引用: [ADR-0006](0006-dataplatform-as-independent-subdomain.md), [ADR-0012](0012-config-isolation-rule.md)

## 实施注意事项

- 配套规范: `docs/spec/data-domain.md` 抽取状态章节
- 配套测试: `tests/boundaries/test_cross_module_imports.py` 检测 `from CostView.src.db.* import` 残留
- 回滚策略: 通过 `CostView/src/db/` re-export 维持向后兼容
