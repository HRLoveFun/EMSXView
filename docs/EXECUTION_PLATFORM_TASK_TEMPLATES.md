# Execution Platform Task Templates

> 面向新对话开工的任务模板
> Last updated: 2026-04-23

---

## 1. Usage

本文件是 `docs/EXECUTION_PLATFORM_WBS.md` 的对话开工配套文档。

使用方式：

1. 在新对话框中选定一个任务模板。
2. 直接复制该任务下的“项目摘要”作为开场白。
3. 在同一条消息中补充本轮具体目标、限制和交付物。
4. 按“第一步先读什么、先搜什么、先验证什么”启动，不要先做宽泛代码漫游。

默认约束：

- 当前正式前端壳：`ExecutionView/frontend/src/App.tsx`
- 当前后端装配层：`ExecutionView/backend/api/main.py`
- 当前共享数据入口：`platform_data/adapters.py`
- 当前 CostView 活跃分析与流水线实现：`CostView/src/`
- Python 后端改动后需要重启 backend
- Bloomberg EMSX 字段必须显式订阅才会收到
- Bloomberg 字段类型必须与解析器类型一致

---

## 2. Template Structure

每个任务模板都包含：

- 项目摘要：用于把长期记忆与当前架构事实传给新对话
- 本任务目标：本轮必须完成的能力面
- 非目标：本轮不应该顺手扩大的范围
- 文件范围：优先改动或阅读的落点
- 依赖：适合开工前先确认的前置任务
- 第一步先读什么：先建立最小正确上下文
- 第一步先搜什么：先定位控制面、入口和测试锚点
- 第一步先验证什么：先确认现状和回归面
- 完成定义：结束条件
- 验收命令：建议在本仓库直接执行的验证命令
- 主要风险：开工时需要盯住的失败模式

---

## 3. Task Templates

### WBS-01 执行历史主脊柱与共享契约

#### 项目摘要

复制下面内容到新对话作为首条消息：

> 当前平台已经收敛为一个正式前端壳 `ExecutionView/frontend/src/App.tsx`、一个后端装配层 `ExecutionView/backend/api/main.py`、一个共享数据入口 `platform_data/adapters.py`、一个活跃分析域 `CostView/src/`。当前缺少的是独立于实时缓存的 execution history spine。ExecutionView 已有 live EMSX 订单和路由订阅、请求响应式交易动作和启动状态分层；MarketView 目前只有基于 `bdib_daily_summary` 的日级快照；CostView 当前是 fills history + BDIB history + TCA query，还不是完整的 order/route history warehouse。本任务要把 shared contract 扩展成 `market reference`、`live execution`、`execution history`、`analytics` 四类边界，定义 execution history 的主键、来源、持久化入口和读取入口，并让后续任务不再默认深层直接导入具体实现。约束是不做物理存储大一统、不打破现有 API 稳定性、不做大爆炸重写。

#### 本任务目标

- 扩展共享数据入口，明确四类数据边界。
- 定义 execution history 的统一主键与来源模型。
- 为后续 MarketView、ExecutionView、CostView 提供稳定读写契约。

#### 非目标

- 不在本任务内完成 Bloomberg 控制面拆分。
- 不在本任务内完成 CostView 历史仓回填。
- 不在本任务内引入新的物理数据库统一方案。

#### 文件范围

- `platform_data/adapters.py`
- `ExecutionView/backend/api/service_provider.py`
- `ExecutionView/backend/api/db.py`
- `ExecutionView/backend/api/schemas.py`
- `ExecutionView/backend/api/tests/test_platform_data_access.py`
- `ExecutionView/backend/api/tests/test_service_provider.py`
- `ExecutionView/backend/api/tests/test_db_bootstrap.py`
- `docs/DATA_DOMAIN.md`

#### 依赖

- 无。该任务是其他任务的前置底座。

#### 第一步先读什么

- `docs/PROJECT_STRUCTURE.md`
- `docs/DATA_DOMAIN.md`
- `docs/MEMORY.md`
- `platform_data/adapters.py`
- `ExecutionView/backend/api/service_provider.py`

#### 第一步先搜什么

- 搜 `build_platform_data_access`
- 搜 `operational`
- 搜 `analytics`
- 搜 `persist_order|persist_route|persist_audit_event`
- 搜 `load_orders|load_routes`

#### 第一步先验证什么

- 当前 `platform_data` 是否只暴露粗粒度入口。
- 当前 DB 可选模式下 execution history 是否仍能定义清晰契约。
- 当前测试是否已经覆盖 adapter 与 repository provider 的最小行为。

#### 完成定义

- 四类数据边界在代码和文档中都明确可见。
- execution history 的主键、读取入口和写入入口可被后续任务直接复用。
- 现有 live execution 与 analytics 入口不被破坏。

#### 验收命令

```powershell
Push-Location ExecutionView/backend/api
python -m pytest tests/test_platform_data_access.py tests/test_service_provider.py tests/test_db_bootstrap.py tests/test_projection_repositories.py -q
Pop-Location
```

#### 主要风险

- 抽象层先行但没有真实消费者，导致接口空转。
- execution history 主键方案与 live projection 主键不一致。
- 可选数据库模式与历史持久化目标互相牵扯。

---

### WBS-02 ExecutionView 的 Bloomberg 控制面拆分

#### 项目摘要

复制下面内容到新对话作为首条消息：

> 当前 `ExecutionView/backend/api/services/bloomberg_adapter.py` 已经把 EMSX 订阅、请求响应、市场数据 enrichment、FX/refdata 和 startup-status 跑通，方向是正确的，但职责过于集中。本任务要在不破坏现有 API 和前端调用面的前提下，把 Bloomberg 控制面拆成更清晰的内部边界：`session manager`、`blotter projector`、`command service`、`market/refdata enrichment`、`startup status service`。必须继续遵守 EMSX 官方文档关于 request/response 与 subscription 分离、correlation id 绑定、ADMIN 事件监控的约束，不能重新引入 `nextEvent()` 竞争。

#### 本任务目标

- 减小 Bloomberg 适配器耦合度。
- 保持订阅、请求响应和启动状态三个平面清晰分离。
- 为后续 route contract 和 execution history 沉淀创造稳定内部结构。

#### 非目标

- 不改前端壳结构。
- 不在本任务内扩展 broker strategy catalog 持久化。
- 不在本任务内做 CostView 历史仓建设。

#### 文件范围

- `ExecutionView/backend/api/services/bloomberg_adapter.py`
- `ExecutionView/backend/api/services/bloomberg_interface.py`
- `ExecutionView/backend/api/services/realtime_gateway.py`
- `ExecutionView/backend/api/routers/connection.py`
- `ExecutionView/backend/api/routers/realtime.py`
- `ExecutionView/backend/api/main.py`
- `ExecutionView/backend/api/tests/test_bloomberg_adapter_refdata.py`
- `ExecutionView/backend/api/tests/test_connection_router.py`
- `ExecutionView/backend/api/tests/test_realtime_gateway.py`

#### 依赖

- 建议先完成 WBS-01。

#### 第一步先读什么

- `docs/EMSX API Developer's Guide.md` 中 sessions、request/response、subscriptions 相关章节
- `ExecutionView/backend/api/services/bloomberg_adapter.py`
- `ExecutionView/backend/api/routers/connection.py`
- `ExecutionView/backend/api/routers/realtime.py`

#### 第一步先搜什么

- 搜 `get_startup_status`
- 搜 `_subscription_loop`
- 搜 `_send_request|_send_request_async`
- 搜 `_mktdata_subscription_loop`
- 搜 `CorrelationId|nextEvent|ADMIN`

#### 第一步先验证什么

- 当前 request/response 和 subscription 是否已使用独立 session。
- 当前 startup-status 是否仍然准确反映 backend、Bloomberg、subscription 三层。
- 当前 refdata 与 realtime 测试是否覆盖最脆弱路径。

#### 完成定义

- Bloomberg 控制面拆分为清晰的内部服务边界。
- 对外路由和前端行为不变。
- startup-status、realtime、refdata 回归测试通过。

#### 验收命令

```powershell
Push-Location ExecutionView/backend/api
python -m pytest tests/test_bloomberg_adapter_refdata.py tests/test_connection_router.py tests/test_realtime_gateway.py -q
Pop-Location
```

#### 主要风险

- 重新引入 `nextEvent()` 竞争。
- correlation id 过滤逻辑回退。
- startup-status 被拆坏，影响 launcher 和 frontend startup gate。

---

### WBS-03 EMSX 路由契约统一与 Broker Strategy Catalog

#### 项目摘要

复制下面内容到新对话作为首条消息：

> 当前仓库已经支持 `RouteEx`、`ModifyRouteEx`、`CancelRouteEx`、`GetAssetClass`、`GetBrokerStrategiesWithAssetClass`、`GetBrokerStrategyInfoWithAssetClass`，但路由规则、字段 reset、strategy 参数顺序和 asset class 链路还没有完全收敛到一个唯一规则层。官方文档明确要求 strategy fields 顺序以 broker 返回的元数据为准。本任务要让 `ExecutionView/backend/api/services/route_service.py` 成为真正的唯一路由规则层，并补齐 broker、asset class、strategy、field order 组成的 catalog，以保证前端、后端和 Bloomberg 对 strategy payload 的理解一致。

#### 本任务目标

- 统一 RouteEx 与 ModifyRouteEx 的 preflight、字段 reset 和 strategy payload 组装。
- 建立 broker strategy catalog。
- 对齐前后端 strategy contract。

#### 非目标

- 不拆 MarketView。
- 不建设完整 execution history warehouse。
- 不做推荐模型。

#### 文件范围

- `ExecutionView/backend/api/services/route_service.py`
- `ExecutionView/backend/api/services/bloomberg_adapter.py`
- `ExecutionView/backend/api/routers/orders.py`
- `ExecutionView/backend/api/routers/routes.py`
- `ExecutionView/backend/api/routers/broker.py`
- `ExecutionView/backend/api/schemas.py`
- `ExecutionView/frontend/src/types/index.ts`
- `ExecutionView/backend/api/tests/test_bloomberg_adapter_routing.py`
- `ExecutionView/backend/api/tests/test_parent_child_execution.py`

#### 依赖

- 建议先完成 WBS-02。

#### 第一步先读什么

- `docs/EMSX API Developer's Guide.md` 中 `CreateOrderAndRouteEx`、`GetBrokerStrategiesWithAssetClass`、`GetBrokerStrategyInfoWithAssetClass`
- `ExecutionView/backend/api/services/route_service.py`
- `ExecutionView/backend/api/services/bloomberg_adapter.py` 中 `route_order` 与 `modify_route`
- `ExecutionView/backend/api/tests/test_bloomberg_adapter_routing.py`

#### 第一步先搜什么

- 搜 `RouteEx|ModifyRouteEx|CancelRouteEx`
- 搜 `GetAssetClass`
- 搜 `GetBrokerStrategiesWithAssetClass|GetBrokerStrategyInfoWithAssetClass`
- 搜 `strategyParams`
- 搜 `build_strategy_elements|validate_route_request`

#### 第一步先验证什么

- 当前 RouteEx/ModifyRouteEx 请求组装逻辑是否重复散落。
- 当前 strategy field 顺序是否只依赖前端状态。
- 当前测试是否覆盖 sentinel reset、asset class fallback 和 strategy name 传递。

#### 完成定义

- route_service 成为唯一规则层。
- broker strategy catalog 可以被前后端稳定消费。
- 路由回归测试和前端构建通过。

#### 验收命令

```powershell
Push-Location ExecutionView/backend/api
python -m pytest tests/test_bloomberg_adapter_routing.py tests/test_parent_child_execution.py -q
Pop-Location

Push-Location ExecutionView/frontend
npm run build
Pop-Location
```

#### 主要风险

- strategy field 顺序错误导致 live broker rejection。
- reset sentinel 语义处理不当导致错误改单。
- catalog 缓存过期造成前后端 contract 漂移。

---

### WBS-04 MarketView 股票池与日级盘前工作台

#### 项目摘要

复制下面内容到新对话作为首条消息：

> 当前 MarketView 只是基于 `bdib_daily_summary` 的只读快照页，后端入口在 `ExecutionView/backend/api/routers/marketview.py`，前端入口在 `ExecutionView/frontend/src/modules/marketview/MarketViewModule.tsx`。日级市场数据生产链已经存在，核心来源是 CostView Stage 7 和 `RawBDIBDB` 的 `bdib_daily_summary`。本任务要把 MarketView 升级为股票池驱动的盘前工作台，先做股票池、筛选、排序、流动性和波动率告警，不引入第二套抓数路径，也不直接做订单感知推荐。

#### 本任务目标

- 引入股票池定义和读取。
- 在 MarketView 中提供日级筛选、排序和风险提示。
- 为后续 handoff 到 ExecutionView 形成 candidate payload。

#### 非目标

- 不做实时行情流。
- 不做推荐模型。
- 不做日内特征服务的完整展开。

#### 文件范围

- `ExecutionView/frontend/src/modules/marketview/MarketViewModule.tsx`
- `ExecutionView/frontend/src/modules/marketview/services/api.ts`
- `ExecutionView/backend/api/routers/marketview.py`
- `platform_data/adapters.py`
- `CostView/src/raw_bdib_db.py`
- `MarketView/README.md`

#### 依赖

- 建议先完成 WBS-01。

#### 第一步先读什么

- `MarketView/README.md`
- `ExecutionView/frontend/src/modules/marketview/MarketViewModule.tsx`
- `ExecutionView/backend/api/routers/marketview.py`
- `CostView/src/raw_bdib_db.py` 中 `bdib_daily_summary` 相关方法

#### 第一步先搜什么

- 搜 `MarketViewModule`
- 搜 `fetchMarketSnapshot`
- 搜 `get_market_snapshot|get_latest_daily_summary`
- 搜 `adv_5d|adv_20d|daily_volatility|intraday_volatility`

#### 第一步先验证什么

- 当前 MarketView 是否完全依赖固定 snapshot 表格。
- 当前 API 是否只暴露最新交易日快照。
- 当前前端是否没有股票池和 handoff 结构。

#### 完成定义

- MarketView 具备股票池驱动的日级工作台。
- 日级流动性和波动率告警可读、可筛选、可排序。
- 为 ExecutionView 传递候选标的预留清晰 contract。

#### 验收命令

```powershell
Push-Location ExecutionView/backend/api
python -m pytest tests/test_platform_data_access.py -q
Pop-Location

Push-Location ExecutionView/frontend
npm run build
npm test
Pop-Location

Invoke-RestMethod "http://localhost:3000/api/marketview/snapshot?limit=3"
```

#### 主要风险

- 把日级 snapshot 误当作实时行情。
- 股票池 ownership 散落在多个层面。
- 仅做前端本地状态而没有可复用 contract。

---

### WBS-05 MarketView 日内走势、流动性与波动率特征服务

#### 项目摘要

复制下面内容到新对话作为首条消息：

> 当前仓库已经有 BDIB 原始库、日更流水线和 xbbg 抓取能力，但 MarketView 还没有独立的 intraday feature service。项目目标要求 MarketView 关注股票池内标的的日内走势、流动性和波动率。本任务要在复用现有 BDIB 数据底座的前提下，建设一层专门给 MarketView 用的日内特征服务，输出 volume curve、区间波动率、区间 VWAP、开收盘流动性和相对 ADV 压力等特征，而不是把 MarketView 变成第二个 CostView。

#### 本任务目标

- 建立面向股票池的 intraday feature API。
- 让前端可下钻到单标的日内特征视图。
- 保持对现有 BDIB 流水线和存储层的复用。

#### 非目标

- 不建设 execution history warehouse。
- 不做 broker recommendation。
- 不改 ExecutionView 路由控制面。

#### 文件范围

- `CostView/src/raw_bdib_db.py`
- `CostView/src/pipeline.py`
- `CostView/src/daily_metrics_calculator.py`
- `platform_data/adapters.py`
- `ExecutionView/backend/api/routers/marketview.py`
- `ExecutionView/frontend/src/modules/marketview/MarketViewModule.tsx`
- `CostView/test_pipeline_guards.py`

#### 依赖

- 建议先完成 WBS-04。

#### 第一步先读什么

- `CostView/src/raw_bdib_db.py`
- `CostView/src/pipeline.py` 中 BDIB 相关 stage
- `CostView/src/daily_metrics_calculator.py`
- `ExecutionView/backend/api/routers/marketview.py`

#### 第一步先搜什么

- 搜 `bdib_daily_summary`
- 搜 `get_bdib_bars_for_date|get_bdib_bars_for_tickers_and_dates`
- 搜 `IntegrateBDIBStage|CalculateDailyMetricsStage`
- 搜 `daily_volatility|intraday_volatility|total_volume`

#### 第一步先验证什么

- 当前是否只有日级快照，没有日内特征 API。
- 当前 BDIB 原始存储能否支持股票池批量读取。
- 当前测试是否已覆盖时区、Stage 7 和 BDIB 安全边界。

#### 完成定义

- MarketView 可以读取稳定的日内特征接口。
- 单标的日内走势和流动性特征可视化落地。
- 现有 BDIB 流水线和保护性测试不回归。

#### 验收命令

```powershell
Push-Location CostView
python -m pytest tests/test_tca_query_service.py test_pipeline_guards.py -q
Pop-Location

Push-Location ExecutionView/frontend
npm run build
Pop-Location
```

#### 主要风险

- 日内数据量放大带来查询与渲染性能问题。
- 时区与交易所本地时间对齐错误污染特征。
- MarketView 与 CostView 之间职责边界被重新混淆。

---

### WBS-06 CostView 的订单、路由、事件历史仓

#### 项目摘要

复制下面内容到新对话作为首条消息：

> 当前 CostView 的核心历史输入仍然是 EMSX fills history，入口是 `CostView/src/emsx_client.py` 和 `CostView/src/fill_fetch.py`；分析层核心是 `CostView/src/tca_query_service.py`。这意味着 CostView 目前更像 fill-centric TCA，而不是完整 execution history warehouse。项目目标要求使用 EMSX API 获取订单路由历史记录，并结合 Bloomberg 市场历史做成本分析和经纪商算法评估。本任务要补齐 `order history`、`route history`、`route event history` 三层历史脊柱；若 Bloomberg 历史接口拿不到完整粒度，就从 ExecutionView 的持久化投影和 request journal 沉淀。

#### 本任务目标

- 把 CostView 从 fill-centric 提升为 execution-history-aware。
- 明确历史数据的来源优先级与刷新策略。
- 为 broker and strategy 评估提供完整历史底座。

#### 非目标

- 不在本任务内完成 scorecard 和排名逻辑。
- 不在本任务内改造 MarketView。
- 不在本任务内做推荐回灌。

#### 文件范围

- `CostView/src/emsx_client.py`
- `CostView/src/fill_fetch.py`
- `CostView/src/raw_fills_db.py`
- `CostView/src/processed_fills_db.py`
- `CostView/src/pipeline.py`
- `CostView/src/tca_query_service.py`
- `ExecutionView/backend/api/service_provider.py`
- `ExecutionView/backend/api/db.py`
- `CostView/tests/test_fill_fetch.py`

#### 依赖

- 建议先完成 WBS-01。

#### 第一步先读什么

- `CostView/src/emsx_client.py`
- `CostView/src/fill_fetch.py`
- `CostView/src/tca_query_service.py`
- `ExecutionView/backend/api/service_provider.py`
- `docs/EMSX API Developer's Guide.md` 中 fills / subscriptions / route semantics 相关部分

#### 第一步先搜什么

- 搜 `GetFills|history`
- 搜 `OrderId|RouteId|FillId`
- 搜 `fetch_fills|get_history|get_stats`
- 搜 `persist_order|persist_route|persist_audit_event`

#### 第一步先验证什么

- 当前 CostView 是否只有 fills history 作为历史输入。
- 当前 route 与 order 生命周期是否只能由 fills 反推。
- 当前 ExecutionView persistence 是否足以作为历史补源。

#### 完成定义

- CostView 拥有 fills、orders、routes、route events 四类历史事实表或等价读模型。
- 历史来源、主键和刷新策略被明确下来。
- TCA 查询层可以稳定引用新增历史主数据。

#### 验收命令

```powershell
Push-Location CostView
python -m pytest tests/test_fill_fetch.py tests/test_tca_query_service.py test_pipeline_guards.py -q
Pop-Location

Push-Location ExecutionView/backend/api
python -m pytest tests/test_service_provider.py tests/test_db_bootstrap.py -q
Pop-Location
```

#### 主要风险

- Bloomberg 历史接口拿不到完整 order/route 粒度。
- live projection 与历史抓取主键不一致。
- 历史回填导致 SQLite 存储与批处理压力上升。

---

### WBS-07 CostView 的经纪商算法执行表现评估

#### 项目摘要

复制下面内容到新对话作为首条消息：

> 当前 CostView 已能输出单订单与单路由的 TCA 指标，但项目目标要求进一步评估 broker and strategy 的执行表现。这意味着分析维度要从单笔 TCA 扩展到 broker、strategy、asset class、ticker liquidity bucket、volatility bucket、time of day 等 cohort。本任务要在完整 execution history 的基础上，做可解释的 scorecard、稳定性分析、样本量约束和异常识别，而不是只增加几张图或简单排名。

#### 本任务目标

- 构建 broker and strategy scorecard。
- 引入 cohort 视角与样本量约束。
- 让 CostView 支持经纪商算法表现评估而非仅显示明细。

#### 非目标

- 不做黑盒推荐模型。
- 不改变 EMSX 路由控制面。
- 不在本任务内做三模块 handoff。

#### 文件范围

- `CostView/src/tca_query_service.py`
- `CostView/src/daily_metrics_calculator.py`
- `ExecutionView/frontend/src/modules/costview/CostViewModule.tsx`
- `ExecutionView/frontend/src/modules/costview/components/AnalysisView.tsx`
- `ExecutionView/frontend/src/modules/costview/components/TcaOrderTable.tsx`
- `ExecutionView/frontend/src/modules/costview/types.ts`
- `ExecutionView/frontend/src/modules/costview/services/api.ts`
- `CostView/tests/test_tca_query_service.py`
- `ExecutionView/frontend/src/modules/costview/lib/thresholds.test.ts`

#### 依赖

- 需要先完成 WBS-06。
- 最好已完成 WBS-03，以便使用 broker strategy catalog 做标准化。

#### 第一步先读什么

- `CostView/src/tca_query_service.py`
- `ExecutionView/frontend/src/modules/costview/CostViewModule.tsx`
- `ExecutionView/frontend/src/modules/costview/components/AnalysisView.tsx`
- `docs/EMSX API Developer's Guide.md` 中 route 和 order 生命周期说明

#### 第一步先搜什么

- 搜 `tracking_error_bps|volume_pct_adv20|daily_volatility`
- 搜 `broker|algo|strategy`
- 搜 `TcaOrderSummary|TcaRouteDetail|TcaReport`
- 搜 `thresholds|alert`

#### 第一步先验证什么

- 当前 CostView 是否只能按订单和路由明细展示，不能按 cohort 稳定比较。
- 当前前端结构是否只围绕 report 明细，没有 scorecard 汇总层。
- 当前测试是否覆盖核心 TCA 指标语义。

#### 完成定义

- 可以按 broker、strategy 和 market regime 维度生成 scorecard。
- 分析结果有样本量约束和异常提示。
- 前后端展示和聚合口径一致。

#### 验收命令

```powershell
Push-Location CostView
python -m pytest tests/test_tca_query_service.py test_pipeline_guards.py -q
Pop-Location

Push-Location ExecutionView/frontend
npm run build
npm test
Pop-Location
```

#### 主要风险

- 样本量不足导致排名失真。
- 前后端聚合口径漂移导致不可解释。
- 过度聚合掩盖 route-level 异常。

---

### WBS-08 MarketView、ExecutionView、CostView 三模块闭环联动

#### 项目摘要

复制下面内容到新对话作为首条消息：

> 当前三个业务域已经在同一个前端壳里并存，但它们之间仍然更像并列模块，而不是闭环平台。项目目标是形成从盘前候选到执行到事后反馈的闭环：MarketView 负责股票池与市场上下文，ExecutionView 负责 EMSX 实时执行与控制，CostView 负责事后分析与 broker/strategy 评估。本任务要定义并落地三条 handoff contract：`MarketView -> ExecutionView` 的候选标的与执行上下文，`ExecutionView -> CostView` 的执行日志与策略上下文，`CostView -> ExecutionView` 的 broker and strategy 建议回灌。要求通过共享契约实现，而不是页面间硬编码传值。

#### 本任务目标

- 打通三个业务域的 handoff chain。
- 明确跨模块 payload 结构与来源。
- 形成 pre-trade、execution、post-trade 的闭环工作流。

#### 非目标

- 不做黑盒推荐模型。
- 不引入第二个前端壳。
- 不在本任务内重构 CostView 或 MarketView 基础数据生产链。

#### 文件范围

- `ExecutionView/frontend/src/App.tsx`
- `ExecutionView/frontend/src/sections/WorkspaceModuleTabs.tsx`
- `ExecutionView/frontend/src/modules/marketview/MarketViewModule.tsx`
- `ExecutionView/frontend/src/modules/costview/CostViewModule.tsx`
- `platform_data/adapters.py`
- `ExecutionView/backend/api/routers/marketview.py`
- `ExecutionView/backend/api/routers/orders.py`
- `ExecutionView/backend/api/routers/broker.py`
- `ExecutionView/backend/api/routers/costview.py`

#### 依赖

- 需要先完成 WBS-03、WBS-05、WBS-07。

#### 第一步先读什么

- `docs/PROJECT_STRUCTURE.md`
- `docs/DATA_DOMAIN.md`
- `ExecutionView/frontend/src/App.tsx`
- `ExecutionView/frontend/src/sections/WorkspaceModuleTabs.tsx`
- `platform_data/adapters.py`

#### 第一步先搜什么

- 搜 `marketview|costview|execution`
- 搜 `WorkspaceModuleTabs|use-app-shell-state`
- 搜 `strategyParams|broker algorithms|assetClass`
- 搜 `MarketViewModule|CostViewModule`

#### 第一步先验证什么

- 当前三个模块之间是否完全没有明确 handoff payload。
- 当前跨模块状态是否仍主要靠前端局部状态维持。
- 当前共享适配层能否承接跨模块 contract。

#### 完成定义

- 三条 handoff contract 清晰落地。
- MarketView 候选可进入 ExecutionView。
- ExecutionView 执行上下文能进入 CostView。
- CostView 的 broker and strategy 结论能回灌给 ExecutionView。

#### 验收命令

```powershell
Push-Location ExecutionView/backend/api
python -m pytest tests/test_platform_data_access.py tests/test_connection_router.py -q
Pop-Location

Push-Location ExecutionView/frontend
npm run build
npm test
Pop-Location

Invoke-RestMethod "http://localhost:3000/api/marketview/snapshot?limit=3"
Invoke-RestMethod "http://localhost:3000/api/health"
```

#### 主要风险

- 同壳多模块的共享状态过度耦合。
- handoff payload 缺少版本和来源信息，难以排障。
- 没有先定义 contract 就直接堆 UI 交互，退化为硬编码传值。

---

## 4. Recommended Launch Order

1. `WBS-01` 先做数据边界与 execution history spine。
2. `WBS-02` 与 `WBS-04` 可在 `WBS-01` 之后并行。
3. `WBS-03` 跟在 `WBS-02` 之后。
4. `WBS-05` 跟在 `WBS-04` 之后。
5. `WBS-06` 在 `WBS-01` 之后即可开始。
6. `WBS-07` 在 `WBS-06` 之后开始，并尽量利用 `WBS-03` 产出的 strategy catalog。
7. `WBS-08` 最后串起三模块闭环。
