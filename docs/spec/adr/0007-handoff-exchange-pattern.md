# ADR-0007: Handoff 跨模块交换模式

> 状态: Accepted
> 日期: 2026-06-03
> 标签: integration, frontend, backend

## 背景 (Context)

业务模块间存在两类数据交换：

1. **同步查询**：ExecutionView 拉取 CostView 的 TCA 报告
2. **异步交接**：MarketView 准备好的执行计划交接给 ExecutionView

第一类已通过 `platform_data.analytics.*` 适配器解决（ADR-0002）。
第二类（异步交接）需要：
- MarketView 不知道 ExecutionView 是否在线
- ExecutionView 启动后才需要消费
- 数据需持久化（重启不丢）
- 跨进程支持（单进程 vs 微服务模式）

## 决策 (Decision)

引入 **`HandoffExchangeAdapter`** 作为跨模块异步交接的统一通道：

- **后端**（`platform_data/adapters.py`）：暴露 `publish` / `consume_pending` / `acknowledge`
- **存储后端**：
  - `HANDOFF_BACKEND=memory`（默认）：进程内 dict + threading.Lock
  - `HANDOFF_BACKEND=redis`：Redis pub/sub（微服务模式）
- **契约**：`platform_data/contracts/handoff_contracts.py` 定义 `HandoffContract` 类型
- **前端**：`useHandoffContracts()` hook + `handoff-api.ts` 服务
- **消费者标识**：消费方按 `moduleId` 过滤属于自己的合约

## 后果 (Consequences)

### 正面
- 单一交接通道，避免每个业务模块自己实现消息队列
- 部署模式可切换（memory / redis）无需改业务代码
- 交接有持久化保证（redis 后端）

### 负面 / 取舍
- 引入 Redis 依赖（生产模式）
- HandoffContract 类型演进需前后端同步

## 备选方案 (Considered Alternatives)

- 方案 A: 每个模块自己实现消息队列
  - 否决原因: 重复实现，无统一契约
- 方案 B: 用 Kafka/Pulsar
  - 否决原因: 部署复杂度与当前规模不匹配
- 方案 C: 通过数据库表做交接
  - 否决原因: 与 Operational/Analytical 边界冲突（ADR-0001）

## 相关 ADR

- 引用: [ADR-0002](0002-platform-data-adapter-pattern.md)
- 被引用: [ADR-0008](0008-frontend-module-registry-pattern.md)
