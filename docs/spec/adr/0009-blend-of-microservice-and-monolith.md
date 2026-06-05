# ADR-0009: 单进程/微服务双模部署

> 状态: Accepted
> 日期: 2026-06-03
> 标签: deployment, architecture

## 背景 (Context)

EMSXView 业务模块可独立演进，但同时受限于：
- 开发环境资源有限（单机笔记本跑完整套）
- 演示/培训需要一键启动
- 生产环境需要模块独立扩展、故障隔离

传统方案二选一：
- 强制微服务：开发体验差
- 强制单进程：生产无法扩展

## 决策 (Decision)

通过环境变量 `EMSXVIEW_MERGE_MODULES` 控制部署模式：

| 模式 | 环境变量 | 架构 | 适用场景 |
|---|---|---|---|
| **单进程** | `true` | 所有 router 加载到一个 FastAPI 进程 (:3000) | 开发、演示、培训 |
| **微服务** | `false`（默认） | Core :3000, MarketView :8001, CostView :8002 | 生产 |

跨进程通信通过 `HandoffExchangeAdapter`（ADR-0007）支持 memory/redis 后端：
- memory 模式：单进程内 dict+lock
- redis 模式：跨进程 pub/sub

Backend main.py 模式约定：
- **Core routers** 始终加载：connection, auth, orders, routes, broker, realtime, debug, route_plans, market_broker_mapping
- **Optional routers** 仅合并模式加载：marketview, costview, database, execution_history
- 新增 optional router 必须走 `_register_optional` 模式，**不得影响 Core ExecutionView**

## 后果 (Consequences)

### 正面
- 一套代码同时支持开发与生产
- 演示/培训成本低
- 独立模块可独立扩展（生产）

### 负面 / 取舍
- 代码需保持"可在两种模式运行"（避免硬编码端口/进程）
- 配置多一份（EMSXVIEW_MERGE_MODULES）
- 测试需覆盖两种模式

## 备选方案 (Considered Alternatives)

- 方案 A: 强制单一模式
  - 否决原因: 见背景
- 方案 B: 引入 docker-compose dev/prod
  - 否决原因: Windows 本地体验差；增加开发摩擦
- 方案 C: 使用 K8s 统一管理
  - 否决原因: 当前规模过度工程化

## 相关 ADR

- 引用: [ADR-0007](0007-handoff-exchange-pattern.md)
- 被引用: 无
