# ADR-0003: ExecutionView 拥有 operational state

> 状态: Accepted
> 日期: 2026-06-03
> 标签: data, backend, execution

## 背景 (Context)

ExecutionView 是实时订单/路由管理模块，对应 Bloomberg EMSX 的订单生命周期。
其状态特征：
- 强事务：订单状态变更需要原子性
- 低延迟：API 响应需 < 100ms
- 温启动：服务重启后需快速恢复运行中订单的投影
- 审计：合规要求保留所有状态变更历史

如果把 operational state 放到 CostView 的 analytical store（SQLite）中：
- 事务隔离级别冲突（CostView 用批量写入优化）
- 写锁竞争影响 BDIB 行情查询
- 审计事件混入 analytical 流，难以独立导出

## 决策 (Decision)

ExecutionView 拥有以下 operational state：

| 数据类型 | 存储 | 备份策略 |
|---|---|---|
| 实时订单投影 | PostgreSQL（in-memory fallback） | WAL + 周期 snapshot |
| 实时路由投影 | 同上 | 同上 |
| 审计事件 | 同上 | append-only，季度归档 |
| 温启动缓存 | 同上 + 内存 | 启动时从 DB 加载 |

- 数据访问入口：`backend/api/db.py` + `service_provider.RepositoryProvider`
- 跨域对外暴露：`platform_data.operational.*` Adapter
- 门控开关：`ENABLE_DB_PERSISTENCE`（true/false）
- **禁止**ExecutionView 把 CostView analytical store（processed_fills.db / regime.db）当作主持久化层

## 后果 (Consequences)

### 正面
- operational 与 analytical workload 物理隔离
- 事务性能不受批量分析写入影响
- 审计事件可独立导出满足合规

### 负面 / 取舍
- 需要维护两套持久化基础设施
- 跨域 join 需走 Adapter（增加一跳）

## 备选方案 (Considered Alternatives)

- 方案 A: 全部放到 CostView analytical store
  - 否决原因: 事务/审计/性能均冲突
- 方案 B: 全部放到内存（不持久化）
  - 否决原因: 重启丢单违反合规
- 方案 C: 共用 PostgreSQL 但 schema 分离
  - 当前方案即是此选项的演进

## 相关 ADR

- 引用: [ADR-0001](0001-one-logical-data-domain.md), [ADR-0002](0002-platform-data-adapter-pattern.md)
- 被引用: 无
