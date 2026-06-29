# 模块 API 契约

> 跨域 API 真相源
> 配套规范：`.codebuddy/rules/module-boundary.md`、`.codebuddy/rules/coding-style.md` §API 约定
> 配套反模式：[anti-patterns.md §AP-05](../anti-patterns.md)
> Last updated: 2026-06-03

---

## 通用约定

所有 HTTP 响应统一封装：

```json
{
  "success": true,
  "data": { ... },
  "message": "",
  "error_code": ""
}
```

错误码规范：

| 状态码 | 含义 |
|---|---|
| 200 | 成功 |
| 400 | 请求参数错误 |
| 401 | 未认证 |
| 403 | 无权限 |
| 404 | 资源不存在 |
| 422 | 验证失败 |
| 500 | 服务器内部错误 |

所有响应 Pydantic 模型必须继承 `BaseModel`（v2），使用 `ApiResponse[T]` 泛型包装。

---

## ExecutionView API（Core :3000）

### 订单管理

| 端点 | 方法 | 描述 |
|---|---|---|
| `/api/orders` | GET | 列出订单 |
| `/api/orders` | POST | 创建订单 |
| `/api/orders/{id}` | GET | 查询订单 |
| `/api/orders/{id}` | PUT | 修改订单 |
| `/api/orders/{id}` | DELETE | 取消订单 |
| `/api/orders/{id}/fill` | GET | 查询订单成交 |

### 路由管理

| 端点 | 方法 | 描述 |
|---|---|---|
| `/api/routes` | GET | 列出路由 |
| `/api/routes` | POST | 创建路由 |
| `/api/routes/{id}` | GET | 查询路由 |
| `/api/routes/{id}/cancel` | POST | 取消路由 |

### 经纪商与连接

| 端点 | 方法 | 描述 |
|---|---|---|
| `/api/broker/list` | GET | 经纪商列表 |
| `/api/broker/algorithms` | GET | 算法列表 |
| `/api/connection` | GET | Bloomberg 连接状态 |
| `/api/health` | GET | 健康检查（含 `database.status`） |

### 实时推送

| 端点 | 协议 | 描述 |
|---|---|---|
| `/ws/orders` | WebSocket | 订单状态实时推送 |
| `/ws/routes` | WebSocket | 路由状态实时推送 |

### 路由计划

| 端点 | 方法 | 描述 |
|---|---|---|
| `/api/route-plans` | GET/POST | 路由计划 CRUD |

### 调试

| 端点 | 方法 | 描述 |
|---|---|---|
| `/api/debug/*` | GET | 调试信息（仅开发模式） |

---

## CostView API（Optional / :8002）

### TCA 分析

| 端点 | 方法 | 描述 |
|---|---|---|
| `/api/tca/analyze` | POST | TCA 交易成本分析 |
| `/api/tca/scorecard` | POST | 评分卡查询 |

### 执行历史

| 端点 | 方法 | 描述 |
|---|---|---|
| `/api/execution-history/fills` | GET | 历史 fill 查询 |
| `/api/execution-history/orders` | GET | 历史 order 查询 |
| `/api/execution-history/routes` | GET | 历史 route 查询 |

### Regimes

| 端点 | 方法 | 描述 |
|---|---|---|
| `/api/regime/distribution` | GET | Regime 分布查询 |
| `/api/regime/classify` | POST | Regime 分类 |

---

## DatabaseView API（Optional / 仅合并模式）

| 端点 | 方法 | 描述 |
|---|---|---|
| `/api/database/tables` | GET | 表清单 |
| `/api/database/tables/{name}/stats` | GET | 表统计 |
| `/api/database/tables/{name}/rows` | GET | 表行查询 |
| `/api/database/dates` | GET | 数据库日期覆盖 |
| `/api/database/health` | GET | 数据库健康检查 |

详见 `docs/archive/2026-06-29/database.md`（已归档，内容部分过时；当前真相源以 `backend/api/routers/database.py` 为准）。

---

## MarketView API（独立 :8001）

| 端点 | 方法 | 描述 |
|---|---|---|
| `/api/marketview/snapshot` | GET | 市场快照 |
| `/api/marketview/intraday` | GET | 日内特征 |

> MarketView 当前是只读基线，新端点需走 ADR 决策。

---

## WebSocket 契约

### 通用消息格式

```json
{
  "type": "order.update",
  "ts": 1717400000.123,
  "data": { ... }
}
```

### 已知消息类型

| type | 方向 | 描述 |
|---|---|---|
| `order.update` | 服务端 → 客户端 | 订单状态变更 |
| `route.update` | 服务端 → 客户端 | 路由状态变更 |
| `connection.status` | 服务端 → 客户端 | Bloomberg 连接状态 |
| `handoff.new` | 服务端 → 客户端 | 新 handoff 合约 |

---

## 跨域数据契约（`platform_data/contracts/`）

| 文件 | 内容 |
|---|---|
| `fill_contracts.py` | `SCORECARD_COHORTS` 等 fill 类型 |
| `market_contracts.py` | `MarketCandidatePayload`, `MarketCandidateRow` |
| `execution_contracts.py` | `ExecutionHistoryFillRow`, `ExecutionHistoryOrderSummaryRow`, `ExecutionHistoryRouteSummaryRow` 等 |
| `handoff_contracts.py` | `HandoffMetadata`, `ExecutionCandidateHandoff`, `ExecutionPostTradeHandoff`, `BrokerStrategyRecommendation` |
| `regime_contracts.py` | regime 类型 |
| `data_platform_contracts.py` | `IngestionConfig`, `PipelineState`, `IngestionResult` |
| `evaluation_contracts.py` | （planned）算法模型元数据 |
| `protocols.py` | `ConnectionManagerProtocol`, `ConfigProtocol`（DataPipeline 集成协议） |

**规则**：跨模块数据类型**只**从 `platform_data.contracts` 导入。

---

## 平台适配器入口（`platform_data/`）

> **当前实现 (2026-06-03)**：没有统一 `PlatformDataAccess` / `build_platform_data_access()`
> 入口。**实际入口**为下列符号，分别从 `platform_data` 直接 import。

| 入口 | 用途 |
|---|---|
| `HandoffExchangeAdapter` | 跨模块 handoff（in-memory 单进程） |
| `RedisHandoffExchangeAdapter` | 跨模块 handoff（Redis 微服务模式） |
| `get_shared_handoff_exchange()` | 工厂函数（依据 `EMSXVIEW_HANDOFF_BACKEND` 选择后端） |
| `MarketReferenceDataAdapter` | 市场快照与日内特征 |
| `get_tca_query_service()` | TCA 查询服务工厂 |
| `register_tca_service_impl(impl)` | TCA 实现注入（避免直接 import CostView 内部） |

详细公开/私有方法分界见 `.codebuddy/rules/module-boundary.md` §2.3。

---

## 跨域 Handoff 契约

| 字段 | 类型 | 描述 |
|---|---|---|
| `id` | str | 唯一 ID |
| `source_module` | str | 生产方模块 ID |
| `target_module` | str | 消费方模块 ID |
| `payload` | Any | 业务数据 |
| `created_at` | float | Unix 时间戳 |
| `acknowledged` | bool | 是否已消费 |

存储后端：`memory`（默认） / `redis`（生产）。

---

## 维护规则

1. **任何端点变更必须同步本文件**——CI 会用 `audit_doc_drift.py` 检测 OpenAPI vs 本文档的差异
2. **新增端点必须先在 ADR 中决策**（如涉及架构变化）
3. **删除端点标记 `Deprecated: true`，保留 1 个版本周期**
4. **破坏性变更必须 bump URL prefix**（如 `/api/v2/...`）
