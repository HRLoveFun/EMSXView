# 模块 API 契约

> 跨域 API 真相源
> 配套规范：`.codebuddy/rules/module-boundary.md`、`.codebuddy/rules/coding-style.md` §API 约定
> 配套反模式：[anti-patterns.md §AP-05](../anti-patterns.md)
> Last updated: 2026-09-11（端点表与 `api/routers/` 源码逐行核对：移除已不存在的 `/api/execution-history/*`、`/api/regime/*`，补 CostView monitoring 端点与 analyze-orders，修正 MarketView 端点路径，刷新契约文件清单）

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

> 端点源码定位与验证方式见主 [README.md §4.2](../../README.md#42-costviewcostview--beta) 与 [CostView/README.md](../../CostView/README.md)。

### TCA 分析

| 端点 | 方法 | 描述 |
|---|---|---|
| `/api/tca/analyze` | POST | TCA 交易成本分析（route 级，读 `tca_route_summary` 预计算表） |
| `/api/tca/analyze-orders` | POST | TCA 订单聚合查询（`TCA_ORDER_AGG_ENABLED` 默认关闭） |
| `/api/tca/scorecard` | POST | 评分卡查询 |
| `/api/tca/recommendations/pin` | POST | 券商推荐 pin（写入 handoff，ExecutionView 经 `GET /api/broker-recommendations` 读取） |
| `/api/tca/handoff/post-trade/{order_id}` | GET | 查看 ExecutionView → CostView post-trade handoff |
| `/api/costview/regime-distribution` | GET | Regime 分布查询（`regime_dim` ∈ {vol_regime, liq_regime, trend_regime}；regime.db 未就绪返回 503） |

### 监控与报告

| 端点 | 方法 | 描述 |
|---|---|---|
| `/api/tca/monitoring/bdib-health` | GET | BDIB 数据健康扫描 |
| `/api/tca/monitoring/metric-coverage` | GET | 计算指标非 NULL 覆盖率 |
| `/api/tca/monitoring/report-summary` | GET | TCA 报告聚合（KPI/图表/排名） |
| `/api/tca/monitoring/anomaly-thresholds` | GET | 异常路由过滤阈值 |
| `/api/tca/monitoring/export-html` | GET | 自包含 HTML 报告一键导出 |

### 数据管道触发（backend 鉴权代理，非 CostView 服务端点）

| 端点 | 方法 | 描述 |
|---|---|---|
| `/api/tca/runner/run` | POST | 代理独立仓库 EMSXDataPipeline Runner（本机 `:8100`，单任务模型；已在运行返回 409 幂等受理） |
| `/api/tca/runner/status` | GET | 查询当前管道任务状态 |

#### `POST /api/tca/analyze` 响应结构

返回 `ApiResponse[TcaReport]`，其中 `data` 为扁平路由汇总报告。

```json
{
  "success": true,
  "data": {
    "filters": { "start_date": "20260418", "end_date": "20260418", ... },
    "total_orders": 1,
    "offset": 0,
    "limit": 50,
    "orders": [
      {
        "OrderId": "O1",
        "RouteId": "R1",
        "order_as_of_date": "20260418",
        "Exchange": "US",
        "Account": null,
        "equ_ticker": "AAPL US Equity",
        "Currency": "USD",
        "Side": "Buy",
        "Amount": 1000.0,
        "RouteShares": 500.0,
        "Type": null,
        "LimitPrice": null,
        "StopPrice": null,
        "Broker": "BrokerA",
        "StrategyType": "VWAP",
        "algo": "VWAP",
        "TraderName": "Trader1",
        "fill": 100.0,
        "fill_continuous": 100.0,
        "fill_close": 0.0,
        "par_rate": 0.000217,
        "par_rate_continuous": 0.000217,
        "par_rate_close": null,
        "p_avg": 50.25,
        "p_avg_continuous": 50.25,
        "pnl_vwap": -28.0,
        "pnl_vwap_continuous": -28.0,
        "RPM": 0.20,
        "RPM_continuous": 0.0,
        "pwp_5": null,
        "pwp_10": null,
        "pwp_15": null,
        "pwp_20": null,
        "pwp_25": null,
        "time_series": []
      }
    ],
    "generated_at": "2026-07-16T08:55:00",
    "data_source_warning": null
  },
  "message": "",
  "error_code": ""
}
```

字段说明：

| 字段 | 类型 | 说明 |
|---|---|---|
| `OrderId` | `string` | 订单 ID |
| `RouteId` | `string` | 路由 ID |
| `order_as_of_date` | `string` | 交易日 `YYYYMMDD` |
| `Exchange` | `string \| null` | Bloomberg 交易所代码 |
| `Account` | `string \| null` | 账户 |
| `equ_ticker` | `string \| null` | 股票代码，如 `AAPL US Equity` |
| `Currency` | `string \| null` | 币种 |
| `Side` | `string \| null` | 买卖方向 |
| `Amount` | `float \| null` | 订单数量 |
| `RouteShares` | `float \| null` | 路由股数 |
| `Type` | `string \| null` | 订单类型 |
| `LimitPrice` | `float \| null` | 限价 |
| `StopPrice` | `float \| null` | 止损价 |
| `Broker` | `string \| null` | 经纪商 |
| `StrategyType` | `string \| null` | 策略类型 |
| `algo` | `string \| null` | 算法名称 |
| `TraderName` | `string \| null` | 交易员 |
| `fill` | `float \| null` | 成交百分比（0-100）|
| `fill_continuous` | `float \| null` | 连续交易时段成交百分比 |
| `fill_close` | `float \| null` | 收盘时段成交百分比 |
| `par_rate` | `float \| null` | 参与率（0-1 小数）|
| `par_rate_continuous` | `float \| null` | 连续时段参与率 |
| `par_rate_close` | `float \| null` | 收盘时段参与率 |
| `p_avg` | `float \| null` | 成交均价 |
| `p_avg_continuous` | `float \| null` | 连续时段成交均价 |
| `pnl_vwap` | `float \| null` | 相对 VWAP 的盈亏（bps）|
| `pnl_vwap_continuous` | `float \| null` | 连续时段相对 VWAP 盈亏（bps）|
| `RPM` | `float \| null` | 日价格波动代理指标 |
| `RPM_continuous` | `float \| null` | 连续时段 RPM |
| `pwp_5` ... `pwp_25` | `string \| float \| null` | 5/10/15/20/25 分钟 PWP |
| `time_series` | `list[dict]` | 时序数据，供前端图表使用 |

> **Schema 变更说明**：2026-07-15 重构后，`/api/tca/analyze` 从嵌套订单结构
> (`TcaOrderSummary` → `TcaRouteDetail`) 迁移为扁平路由结构 (`TcaRouteSummary`)，
> 34 个字段严格对应数据库 `tca_route_summary` 表列。`TcaOrderSummary` 与
> `TcaRouteDetail` 已标记为 deprecated，仅用于兼容旧归档代码。
>
> 2026-09-15 收敛：`CostView/src/tca_query_service.py` 中的兼容 re-export
> （`from platform_data.contracts import TcaOrderSummary, TcaRouteDetail`）已移除 ——
> 双仓库（本仓库 + EMSXDataPipeline）AST 核查确认零消费者。
>
> 2026-09-16 收敛：`platform_data/contracts/__init__.py` 的包入口 re-export 亦已移除。
> 两个类型的**定义仍保留**在 `platform_data/contracts/tca_contracts.py`（观察一个周期后再评估
> 删除），需要时按显式子模块路径导入：
> `from platform_data.contracts.tca_contracts import TcaOrderSummary, TcaRouteDetail`。

### 执行历史（已移除）

> 010-extract-pipeline：`/api/execution-history/*` 端点已移除（数据库维护迁独立仓库
> EMSXDataPipeline）。执行历史读取现由 `CostView/src/tca_query_builder.py` 直接 SQL JOIN
> `route_registry` 提供（原 `execution_history_service.py` 已于 2026-08-26 移除，见 ADR-0014）。

### Regimes

> 原 `/api/regime/distribution`、`/api/regime/classify` 端点不存在（2026-09-11 核实）。
> 实际端点为 CostView 服务的 `GET /api/costview/regime-distribution`，见上文 TCA 分析表。

---

## DatabaseView API（已迁出）

> 010-extract-pipeline：DatabaseView 已迁独立项目 EMSXDataPipeline Runner，
> 本仓库不再提供 `/api/database/*` 端点；数据库维护走 Runner（`POST /run`、`GET /status`）。
> 历史契约见 `docs/archive/2026-06-29/database.md`（已归档）。

---

## MarketView API（独立 :8001）

| 端点 | 方法 | 描述 |
|---|---|---|
| `/api/marketview/snapshot` | GET | 市场快照（`MarketView/routers/marketview.py:146`） |
| `/api/marketview/intraday-features` | GET | 日内特征（`marketview.py:341`；注意路径是 `intraday-features` 而非 `intraday`） |
| `/api/marketview/handoff/execution` | POST | 发布 Market → Execution handoff（`marketview.py:457`） |

> MarketView 当前是只读基线（Scaffold），新端点需走 ADR 决策。

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

实际文件清单（2026-09-11 逐文件核实）：

| 文件 | 内容 |
|---|---|
| `tca_contracts.py` | `SCORECARD_COHORTS` 等 TCA 类型（原 `fill_contracts.py` 内容并入此处，该文件已不存在） |
| `market_contracts.py` | `MarketCandidatePayload`, `MarketCandidateRow` |
| `execution_contracts.py` | `ExecutionHistoryFillRow`, `ExecutionHistoryOrderSummaryRow`, `ExecutionHistoryRouteSummaryRow` 等 |
| `handoff_contracts.py` | `HandoffMetadata`, `ExecutionCandidateHandoff`, `ExecutionPostTradeHandoff`, `BrokerStrategyRecommendation` |
| `intraday_contracts.py` | 日内特征契约（bucket 选项/上限等常量） |
| `db_constants.py` | 库常量定义 |
| `data_access.py` | 数据访问契约 |
| `protocols.py` | `ConnectionManagerProtocol`, `ConfigProtocol`（数据访问层集成协议，实现见 `data_access/`） |
| `tca_service_protocol.py` | TCA 查询服务协议 |
| `boundary_registry.py` | 模块边界注册 |

> 历史说明：v2026-07-16 前列出的 `regime_contracts.py`、`data_platform_contracts.py`（`IngestionConfig`/`PipelineState`/`IngestionResult`）、`evaluation_contracts.py` 均已不存在（详见 [data-domain.md v3.4](data-domain.md) Contract layer 一节）。

**规则**：跨模块数据类型**只**从 `platform_data.contracts` 导入。

> 2026-09-16 收敛：`platform_data/adapters/__init__.py` 曾以「向后兼容」为名 re-export
> 27 个契约类型与 8 个下划线私有符号，与本规则及 `.codebuddy/rules/module-boundary.md` §2.3
> 冲突，现已移除（实现全部保留）。受影响的两处违规消费者
> （`MarketView/routers/marketview.py`、`CostView/api/routers/costview.py`）已迁至本包导入。

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

> 2026-09-16 复核：上表 6 个符号由 `platform_data/__init__.py` **顶层 re-export** 提供，
> 属文档化公开入口，**保留不动**。其中 `get_tca_query_service()` /
> `register_tca_service_impl()` 静态零消费者（DI 注册表由 `register_costview_bridge_dependencies()`
> 驱动），按「零调用方的公开 API 依然是 API」保留；同批仅移除
> `platform_data/adapters/__init__.py` 侧对**契约类型与私有符号**的 re-export
> （见上文「跨域数据契约」规则）。

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
