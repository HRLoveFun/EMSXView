# ADR-0004: CostView 聚焦算法评估与分析

> 状态: Accepted
> 日期: 2026-06-03
> 标签: data, costview, analytics

## 背景 (Context)

历史 CostView 是一个"什么都管"的模块：BDIB 抓取、fill 清洗、聚合、TCA、regime、归因、UI。
导致：
- 模块边界模糊，难以界定"CostView 的职责是什么"
- 新人 on boarding 成本高（要先理解所有子模块才能改一个 TCA 算法）
- 数据采集/处理基础设施与算法逻辑耦合，改 BDIB fetcher 可能影响 TCA 报告

## 决策 (Decision)

CostView 重构后**只负责**：

1. **算法评估模型管理**（`CostView/src/evaluation/`, `models/`）
   - 模型注册与生命周期
   - 模型驱动的 TCA / scorecard 计算
2. **分析报告生成**（`CostView/src/tca_query_service.py`）
   - 跨数据源的查询组装
   - 输出格式封装
3. **归因与 regime 分析**（`CostView/src/attribution/`, `regime/`）
   - 业绩归因
   - regime 分类
4. **执行历史查询**（`CostView/src/execution_history_service.py`）
   - 历史 fill/order/route 读取

**CostView 不再负责**（已迁移到 `DataPipeline/`）：
- BDIB 行情抓取
- fill 摄取与清洗
- 数据库连接管理
- 迁移管理
- 数据 schema 定义

CostView 调用数据统一通过 `platform_data.analytics` / `platform_data.execution_history` / `platform_data.database`。

## 后果 (Consequences)

### 正面
- 模块职责清晰，新人可独立理解算法层
- 改 BDIB fetcher 不影响 TCA 报告（已物理分离）
- 算法模型可独立单元测试

### 负面 / 取舍
- `CostView/src/db/` 现为 re-export 薄层，需保留过渡期
- 跨域调用增加一跳（CostView → Adapter → DataPipeline）
- 评估层建设需要持续投入（待补 `evaluation/`, `models/` 目录）

## 备选方案 (Considered Alternatives)

- 方案 A: 保留 CostView 全部职责
  - 否决原因: 边界模糊，债务累计
- 方案 B: 把 CostView 整个合并到 DataPipeline
  - 否决原因: 失去算法层独立演进空间；UI 依赖路径变长
- 方案 C: 把 DataPipeline 合并回 CostView
  - 否决原因: 反向回退，违背 ADR-0005

## 相关 ADR

- 引用: [ADR-0001](0001-one-logical-data-domain.md), [ADR-0002](0002-platform-data-adapter-pattern.md), [ADR-0005](0005-data-pipeline-extraction.md)
- 被引用: 无
