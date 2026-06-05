# ADR-0006: Data Platform 作为独立子域

> 状态: Accepted
> 日期: 2026-06-03
> 标签: architecture, data

## 背景 (Context)

ADR-0005 把数据基础设施从 CostView 抽取到 `DataPipeline/`，但 `DataPipeline` 现在是否仍"归 CostView 拥有"是模糊的：
- 一方面 DataPipeline 物理上是独立 Python 包（`pip install -e .`）
- 另一方面业务上仍由 CostView 团队维护
- 其他模块（ExecutionView、MarketView）也在消费 DataPipeline 的数据

需要明确**Data Platform 的所有权定位**，避免：
- ExecutionView 把 DataPipeline 当 ExecutionView 的子模块
- CostView 把 DataPipeline 当 CostView 的私产拒绝其他域访问
- 双方互相推诿维护责任

## 决策 (Decision)

**Data Platform 是独立子域，不归任何业务模块所有**：

| 维度 | 定位 |
|---|---|
| 组织上 | 独立 Python 包，独立维护节奏 |
| 业务上 | 为所有模块提供"清洁、可靠的数据" |
| 责任上 | 数据采集、处理、存储基础设施；不含分析算法 |
| 对外暴露 | `platform_data.data_platform.*` 适配器（数据交付） |
| 禁止 | 内嵌领域特定分析逻辑 |

具体边界：

- Data Platform 职责止于"清洗、结构化、可查询的数据交付"
- 算法评估、regime 分类、TCA 报告归 CostView
- 订单/路由 operational state 归 ExecutionView
- MarketView 消费 Data Platform 数据做盘前展示

## 后果 (Consequences)

### 正面
- Data Platform 可被三个业务模块平等消费
- 维护责任明确（Data Platform 团队 vs 业务模块团队）
- 避免业务模块把基础设施"私有化"

### 负面 / 取舍
- 业务模块需求变更需走 Data Platform 团队评审
- Data Platform 抽象成本（要服务三类不同消费者）

## 备选方案 (Considered Alternatives)

- 方案 A: Data Platform 归 CostView 拥有
  - 否决原因: ExecutionView/MarketView 消费受阻；ADR-0004 范围被侵蚀
- 方案 B: Data Platform 归 ExecutionView 拥有
  - 否决原因: CostView 失去自主性
- 方案 C: Data Platform 完全独立成公司/部门
  - 否决原因: 当前阶段组织规模不匹配，抽象为独立包+子域足够

## 相关 ADR

- 引用: [ADR-0005](0005-data-pipeline-extraction.md)
- 被引用: 无
