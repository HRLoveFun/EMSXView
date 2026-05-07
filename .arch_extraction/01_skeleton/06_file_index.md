# 关键文件索引

> 基于 cloc 行数 + 依赖图 + 架构角色综合标注。  
> 标签说明：`🔥超大` ≥500行 | `⚠️超限` >300行(前端)/>500行(后端) | `🧱无内部依赖` | `🔗枢纽` 被多模块依赖

---

## 核心抽象（不能动）⭐⭐⭐

> 跨模块共享的基础设施、API 契约、数据访问唯一入口。修改需全员审批。

| 文件 | 行数 | 标签 | 说明 |
|------|------|------|------|
| `platform_data/adapters.py` | 936 | 🔥超大 🔗枢纽 | 共享适配层——跨域数据访问的唯一合法入口，CostView 后端依赖 |
| `platform_data/repositories.py` | 866 | 🔥超大 🔗枢纽 | 共享仓储层——持久化数据访问，无内部依赖 |
| `platform_data/__init__.py` | 98 | 🧱 | 模块入口，导出 adapters |
| `ExecutionView/backend/api/services/bloomberg_adapter.py` | 2119 | 🔥超大 🔗枢纽 | Bloomberg EMSX 核心适配器：订单/路由/行情订阅、字段解析、事件分发 |
| `ExecutionView/backend/api/schemas.py` | 614 | ⚠️超限 🧱🔗枢纽 | Pydantic API 契约，前后端接口镜像的源头，无内部依赖 |
| `ExecutionView/backend/api/db.py` | 56 | 🧱 | SQLite 初始化 + migration 执行 |
| `ExecutionView/backend/api/deps.py` | 43 | 🔗枢纽 | FastAPI 依赖注入：组装所有 service 单例，审计日志异步持久化 |

## 数据层 ⭐⭐

> 数据库定义、仓储实现、Schema 迁移。

### CostView 数据库

| 文件 | 行数 | 标签 | 说明 |
|------|------|------|------|
| `CostView/src/schema.py` | 215 | 🧱 | 表结构定义（raw_fills / processed_fills / aggregated_fills 等） |
| `CostView/src/database.py` | 98 | 🧱 | 数据库连接工厂 |
| `CostView/src/database_access.py` | 104 | 🧱 | 通用数据访问层基类 |
| `CostView/src/raw_fills_db.py` | 516 | ⚠️超限 | 原始填充 CRUD |
| `CostView/src/processed_fills_db.py` | 685 | ⚠️超限 | 已处理填充 CRUD + 聚合查询 |
| `CostView/src/fill_bdib_db.py` | 100 | | 填充-BDIB 关联数据库 |
| `CostView/src/raw_bdib_db.py` | 272 | | 原始 BDIB 行情存储 |
| `CostView/src/processed_raw_bdib_db.py` | 134 | | 已处理 BDIB 数据 |
| `CostView/src/processed_bdib_db.py` | 13 | | 已处理 BDIB（旧） |
| `CostView/src/regime/schema.py` | 31 | | 市场状态数据库 Schema |
| `CostView/src/storage/regime_reader.py` | 58 | | 市场状态数据读取 |

### ExecutionView 数据库

| 文件 | 行数 | 标签 | 说明 |
|------|------|------|------|
| `ExecutionView/backend/api/models/execution_state.py` | 46 | 🧱 | 执行状态 dataclass 模型 |
| `ExecutionView/backend/api/models/route_plan.py` | 113 | | 路由计划 dataclass 模型 |
| `ExecutionView/backend/api/models/parent_child_orders.py` | 73 | | 父子订单 dataclass 模型 |
| `ExecutionView/backend/api/repositories/orders.py` | 47 | | 订单仓储 |
| `ExecutionView/backend/api/repositories/routes.py` | 48 | | 路由仓储 |
| `ExecutionView/backend/api/repositories/parent_child_repository.py` | 82 | | 父子执行仓储 |
| `ExecutionView/backend/api/repositories/audit.py` | 35 | | 审计日志仓储 |
| `ExecutionView/backend/api/migrations/001_init_execution_schema.sql` | 45 | | 初始化迁移 |
| `ExecutionView/backend/api/migrations/002_parent_child_execution.sql` | 43 | | 父子执行迁移 |
| `ExecutionView/backend/api/migrations/003_route_plan.sql` | 72 | | 路由计划迁移 |

## 业务逻辑 ⭐⭐

> 服务层、路由层、管道编排——系统的核心决策逻辑。

### ExecutionView 后端服务层

| 文件 | 行数 | 标签 | 说明 |
|------|------|------|------|
| `ExecutionView/backend/api/services/route_engine.py` | 333 | 🔗枢纽 | 路由引擎——订单→子单拆分决策、自动路由规则应用 |
| `ExecutionView/backend/api/services/route_service.py` | 209 | 🔗枢纽 | 路由 CRUD + 提交/修改/取消，与 Bloomberg 交互 |
| `ExecutionView/backend/api/services/batch_route_service.py` | 474 | ⚠️超限 🔗枢纽 | 批量路由服务——并发提交、进度追踪、策略费率诊断 |
| `ExecutionView/backend/api/services/compliance_service.py` | 278 | | 合规检查——碎股限制、手动经纪商审批 |
| `ExecutionView/backend/api/services/algo_scheduler.py` | 190 | 🔗枢纽 | 算法调度器——定时/条件触发子单提交 |
| `ExecutionView/backend/api/services/benchmark_engine.py` | 117 | | 基准引擎——VWAP/Arrival 等基准价计算 |
| `ExecutionView/backend/api/services/order_projections.py` | 125 | 🧱 | 订单投影——UI 所需的聚合/计算字段 |
| `ExecutionView/backend/api/services/route_projections.py` | 51 | 🧱 | 路由投影——UI 所需的聚合/计算字段 |
| `ExecutionView/backend/api/services/config_service.py` | 39 | 🧱 | 运行时配置读写（策略费率、风控参数） |

### ExecutionView 后端路由层

| 文件 | 行数 | 标签 | 说明 |
|------|------|------|------|
| `ExecutionView/backend/api/routers/orders.py` | 482 | ⚠️超限 🔗枢纽 | 订单+执行 API（15+ 端点），依赖几乎所有 service |
| `ExecutionView/backend/api/routers/route_plans.py` | 491 | ⚠️超限 🔗枢纽 | 路由计划 + RouteEngine + 子单提案 API |
| `ExecutionView/backend/api/routers/routes.py` | 160 | | 路由操作 API |
| `ExecutionView/backend/api/routers/broker.py` | 192 | | 经纪商/策略/算法查询 API |
| `ExecutionView/backend/api/routers/marketview.py` | 409 | ⚠️超限 🧱 | 市场快照+盘内特征+执行交接 API |
| `ExecutionView/backend/api/routers/costview.py` | 434 | ⚠️超限 🧱 | TCA 分析/记分卡/管道触发 API |
| `ExecutionView/backend/api/routers/market_broker_mapping.py` | 127 | | 经纪商-市场映射 CRUD API |
| `ExecutionView/backend/api/routers/execution_history.py` | 103 | | 执行历史查询 API |
| `ExecutionView/backend/api/routers/_pipeline_jobs.py` | 190 | | CostView 管道子进程管理 |
| `ExecutionView/backend/api/routers/auth.py` | 19 | | 认证 API |
| `ExecutionView/backend/api/routers/connection.py` | 51 | | 连接/健康检查 API |
| `ExecutionView/backend/api/routers/realtime.py` | 57 | | WebSocket 实时推送 |

### CostView 核心管道

| 文件 | 行数 | 标签 | 说明 |
|------|------|------|------|
| `CostView/src/pipeline.py` | 808 | ⚠️超限 🔗枢纽 | **管道编排器**——依赖几乎所有 CostView 模块，协调 fetch→process→aggregate→BDIB→attribution |
| `CostView/src/tca_query_service.py` | 1082 | 🔥超大 | TCA 查询服务——多维度归因分析、聚合查询 |
| `CostView/src/fill_fetch.py` | 773 | ⚠️超限 🔗枢纽 | Bloomberg EMSX 填充数据获取，含增量/历史模式 |
| `CostView/src/fill_ingestion.py` | 321 | | 填充摄入——清洗→处理→入库编排 |
| `CostView/src/fill_processor.py` | 168 | | 填充处理——字段映射、计算 |
| `CostView/src/fill_cleaner.py` | 168 | | 填充清洗——去重、时区、异常值 |
| `CostView/src/fill_aggregator.py` | 123 | | 填充聚合——日度/策略级汇总 |
| `CostView/src/daily_metrics_calculator.py` | 257 | | BDIB 每日指标计算（ADV/VWAP 等） |
| `CostView/src/validate_raw_fills.py` | 405 | ⚠️超限 | 原始填充完整性验证 |
| `CostView/src/__main__.py` | 246 | | CostView CLI 入口（fetch/process/aggregate/pipeline/query/schedule） |

### CostView 归因分析

| 文件 | 行数 | 标签 | 说明 |
|------|------|------|------|
| `CostView/src/attribution/writer.py` | 288 | | 归因结果写入 |
| `CostView/src/attribution/aggregator.py` | 212 | | 归因聚合计算 |
| `CostView/src/attribution/benchmarks.py` | 129 | | 基准价计算（VWAP/Arrival/TWAP） |
| `CostView/src/attribution/recommender.py` | 71 | | 执行建议生成 |
| `CostView/src/attribution/metrics.py` | 39 | | 归因指标定义 |
| `CostView/src/attribution/config.py` | 70 | | 归因配置（算法/Benchmark/期限） |

### CostView 市场状态（Regime）

| 文件 | 行数 | 标签 | 说明 |
|------|------|------|------|
| `CostView/src/regime/fill_regime_tagger.py` | 175 | | 填充→市场状态标签映射 |
| `CostView/src/regime/vol_regime.py` | 122 | | 波动率状态判定 |
| `CostView/src/regime/trend_regime.py` | 87 | | 趋势状态判定 |
| `CostView/src/regime/liquidity_regime.py` | 75 | | 流动性状态判定 |
| `CostView/src/regime/market_index_loader.py` | 141 | | 市场指数数据加载 |
| `CostView/src/regime/time_bucket.py` | 66 | | 时间桶划分 |
| `CostView/src/regime/market_code.py` | 33 | | 市场代码映射 |
| `CostView/src/regime/config.py` | 83 | | 市场状态配置 |
| `CostView/src/regime/migrations/apply.py` | 71 | | 数据库迁移执行器 |
| `CostView/src/regime/migrations/v0_to_v1.sql` | 179 | | 迁移 v0→v1 |
| `CostView/src/regime/migrations/v1_to_v2.sql` | 55 | | 迁移 v1→v2 |
| `CostView/src/regime/migrations/v2_to_v3.sql` | 89 | | 迁移 v2→v3 |

## 集成层 ⭐

> 外部系统接口、实时通信网关、事件序列化。

| 文件 | 行数 | 标签 | 说明 |
|------|------|------|------|
| `ExecutionView/backend/api/services/bloomberg_interface.py` | 41 | 🧱 | Bloomberg API 底层封装（blpapi Session 管理） |
| `ExecutionView/backend/api/services/realtime_gateway.py` | 80 | 🔗枢纽 | WebSocket 推送网关——订单/路由变更广播 |
| `ExecutionView/backend/api/services/event_serializers.py` | 41 | 🧱 | Bloomberg 事件→Pydantic 序列化 |
| `ExecutionView/backend/api/auth.py` | 122 | | JWT 认证中间件 |
| `ExecutionView/backend/api/services/auth_service.py` | 29 | | 认证服务（Bloomberg UUID 校验） |
| `CostView/src/emsx_client.py` | 239 | | Bloomberg EMSX SOAP/REST 客户端 |
| `CostView/src/bdib_fetcher.py` | 301 | | Bloomberg BDIB 行情数据获取 |
| `CostView/src/fill_bdib_integrated.py` | 207 | | 填充-BDIB 联合获取 |
| `CostView/src/downstream_interface.py` | 97 | | 下游系统接口（查询/导出） |
| `CostView/src/execution_history_service.py` | 122 | | 执行历史查询服务 |

## 配置/工具 ⭐

> 配置单例、静态数据、前端服务/类型/hook、运维脚本。

### 后端配置与装配

| 文件 | 行数 | 标签 | 说明 |
|------|------|------|------|
| `ExecutionView/backend/api/config.py` | 48 | 🧱 | 后端全局配置单例（Bloomberg/DB/JWT/CORS/风控） |
| `ExecutionView/backend/api/service_provider.py` | 187 | 🔗枢纽 | 服务工厂——组装所有仓储+服务实例，DI 容器 |
| `ExecutionView/backend/api/main.py` | 254 | 🔗枢纽 | FastAPI 应用入口：路由注册、生命周期、Bloomberg 异步连接 |
| `ExecutionView/backend/api/start_server.py` | 18 | | 备用启动器 |
| `CostView/src/processing_config.py` | 102 | 🧱🔗枢纽 | CostView 管道中心化配置——目录/DB路径/参数 |
| `CostView/src/secure_config.py` | 218 | | Bloomberg 凭据管理（UUID + 环境变量/JSON） |
| `CostView/src/exchange_tz.py` | 99 | | 交易所时区映射 |
| `CostView/src/mapping.py` | 177 | | 通用字段映射工具 |
| `CostView/src/order_label.py` | 69 | | 订单标签生成 |
| `CostView/src/query_cli.py` | 175 | | 交互式 TCA 查询 CLI |

### 静态数据文件

| 文件 | 行数 | 标签 | 说明 |
|------|------|------|------|
| `ExecutionView/backend/api/data/broker_algorithms.json` | 16819 | 🔥超大 | 经纪商算法配置（~300 算法），启动时加载 |
| `ExecutionView/backend/api/data/market_broker_mapping.json` | 360 | | 市场-经纪商默认映射 |
| `ExecutionView/backend/api/data/broker_hand_instruction.json` | 8 | | 手动执行指令配置 |

### 前端——服务层

| 文件 | 行数 | 标签 | 说明 |
|------|------|------|------|
| `ExecutionView/frontend/src/services/api.ts` | 587 | ⚠️超限 🔗枢纽 | 核心 HTTP 客户端——所有后端 API 调用 |
| `ExecutionView/frontend/src/services/realtime.ts` | 201 | | WebSocket 客户端 |
| `ExecutionView/frontend/src/services/strategy-data-service.ts` | 243 | ⚠️超限 | 策略数据管理服务 |
| `ExecutionView/frontend/src/services/handoff-api.ts` | 149 | | 交接 API 服务 |
| `ExecutionView/frontend/src/modules/costview/services/api.ts` | 143 | | CostView 专用 API |
| `ExecutionView/frontend/src/modules/marketview/services/api.ts` | 87 | | MarketView 专用 API |
| `ExecutionView/frontend/src/modules/databaseview/services/api.ts` | 88 | | DatabaseView 专用 API |

### 前端——类型定义

| 文件 | 行数 | 标签 | 说明 |
|------|------|------|------|
| `ExecutionView/frontend/src/types/index.ts` | 533 | ⚠️超限 🔗枢纽 | 全局 TypeScript 类型——须与后端 schemas.py 镜像一致 |
| `ExecutionView/frontend/src/modules/costview/types.ts` | 198 | | CostView 类型 |
| `ExecutionView/frontend/src/modules/marketview/types.ts` | 148 | | MarketView 类型 |
| `ExecutionView/frontend/src/modules/databaseview/types.ts` | 124 | | DatabaseView 类型 |

### 前端——Hooks（状态层）

| 文件 | 行数 | 标签 | 说明 |
|------|------|------|------|
| `ExecutionView/frontend/src/hooks/use-execution-view-data.ts` | 375 | ⚠️超限 🔗枢纽 | 主数据 hook——订单/路由/执行状态聚合 |
| `ExecutionView/frontend/src/hooks/use-broker-algorithms.ts` | 294 | | 经纪商算法 hook |
| `ExecutionView/frontend/src/hooks/use-market-broker-mapping.ts` | 94 | | 经纪商映射 hook |
| `ExecutionView/frontend/src/hooks/use-app-shell-state.ts` | 153 | | 应用壳状态 hook |
| `ExecutionView/frontend/src/hooks/use-startup-status.ts` | 148 | | 启动状态 hook |
| `ExecutionView/frontend/src/hooks/use-handoff-contracts.tsx` | 117 | | 交接合约 hook |
| `ExecutionView/frontend/src/hooks/use-trade-hotkeys.tsx` | 133 | | 交易快捷键 hook |
| `ExecutionView/frontend/src/hooks/use-orders-stream.ts` | 41 | | 订单流 hook |
| `ExecutionView/frontend/src/hooks/use-routes-stream.ts` | 41 | | 路由流 hook |
| `ExecutionView/frontend/src/hooks/use-mobile.ts` | 15 | | 移动端检测 hook |

### 前端——数据/映射

| 文件 | 行数 | 标签 | 说明 |
|------|------|------|------|
| `ExecutionView/frontend/src/data/broker-exchange-mapping.ts` | 338 | | 经纪商-交易所映射 |
| `ExecutionView/frontend/src/data/exchange-region-mapping.ts` | 44 | | 交易所-区域映射 |

### 前端——工具库

| 文件 | 行数 | 标签 | 说明 |
|------|------|------|------|
| `ExecutionView/frontend/src/lib/cache-manager.ts` | 205 | | LocalStorage 缓存管理 |
| `ExecutionView/frontend/src/lib/monitor-conditions.ts` | 174 | | 监控条件定义 |
| `ExecutionView/frontend/src/lib/health-palette.ts` | 88 | | 健康状态配色 |
| `ExecutionView/frontend/src/lib/format-utils.ts` | 29 | | 格式化工具 |
| `ExecutionView/frontend/src/lib/reconcile-settings.ts` | 29 | | 设置对账工具 |
| `ExecutionView/frontend/src/lib/table-constants.ts` | 57 | | 表格常量 |
| `ExecutionView/frontend/src/lib/utils.ts` | 5 | | 通用工具 |

### 前端——核心 UI 组件（业务复杂度高）

| 文件 | 行数 | 标签 | 说明 |
|------|------|------|------|
| `ExecutionView/frontend/src/components/batch-route-order-dialog.tsx` | 1247 | 🔥超大 ⚠️超限 | 批量路由对话框——最复杂的前端组件 |
| `ExecutionView/frontend/src/sections/SettingsBoard.tsx` | 1102 | 🔥超大 ⚠️超限 | 设置面板 |
| `ExecutionView/frontend/src/components/route-modify-dialogs.tsx` | 893 | ⚠️超限 | 路由修改对话框组 |
| `ExecutionView/frontend/src/sections/RouteTable.tsx` | 866 | ⚠️超限 | 路由表格 |
| `ExecutionView/frontend/src/sections/OrderTable.tsx` | 681 | ⚠️超限 | 订单表格 |
| `ExecutionView/frontend/src/components/ui/sidebar.tsx` | 661 | ⚠️超限 | 侧边栏导航 |
| `ExecutionView/frontend/src/components/route-plan-manager.tsx` | 617 | ⚠️超限 | 路由计划管理器 |
| `ExecutionView/frontend/src/sections/MonitorBoard.tsx` | 574 | ⚠️超限 | 监控面板 |
| `ExecutionView/frontend/src/components/batch-operation-dialogs.tsx` | 497 | ⚠️超限 | 批量操作对话框 |
| `ExecutionView/frontend/src/components/unified-modify-route-dialog.tsx` | 486 | ⚠️超限 | 统一路由修改对话框 |
| `ExecutionView/frontend/src/sections/BatchOperationPanel.tsx` | 308 | | 批量操作面板 |
| `ExecutionView/frontend/src/components/market-broker-mapping-section.tsx` | 285 | | 经纪商映射配置区 |
| `ExecutionView/frontend/src/components/algo-launch-dialog.tsx` | 283 | | 算法启动对话框 |
| `ExecutionView/frontend/src/components/order-modify-dialog.tsx` | 270 | | 订单修改对话框 |
| `ExecutionView/frontend/src/sections/ExecutionBoard.tsx` | 268 | | 执行面板 |
| `ExecutionView/frontend/src/components/rate-diagnostic-dialog.tsx` | 266 | | 策略费率诊断对话框 |
| `ExecutionView/frontend/src/components/strategy-data-manager.tsx` | 255 | | 策略数据管理器 |
| `ExecutionView/frontend/src/components/sub-order-review-panel.tsx` | 240 | | 子单审核面板 |

### 前端——业务模块

| 文件 | 行数 | 标签 | 说明 |
|------|------|------|------|
| `ExecutionView/frontend/src/modules/marketview/MarketViewModule.tsx` | 795 | ⚠️超限 | MarketView 模块壳 |
| `ExecutionView/frontend/src/modules/costview/CostViewModule.tsx` | 265 | | CostView 模块壳 |
| `ExecutionView/frontend/src/modules/costview/components/ScorecardView.tsx` | 447 | ⚠️超限 | TCA 记分卡视图 |
| `ExecutionView/frontend/src/modules/costview/components/AnalysisView.tsx` | 223 | | 归因分析视图 |
| `ExecutionView/frontend/src/modules/costview/components/ConfigureView.tsx` | 193 | | 配置视图 |
| `ExecutionView/frontend/src/modules/costview/components/OverviewView.tsx` | 178 | | 总览视图 |
| `ExecutionView/frontend/src/modules/costview/components/PriceDynamicsChart.tsx` | 133 | | 价格动态图 |
| `ExecutionView/frontend/src/modules/costview/components/RegimeDistributionPanel.tsx` | 110 | | 市场状态分布面板 |
| `ExecutionView/frontend/src/modules/costview/components/VolumeDynamicsChart.tsx` | 109 | | 成交量动态图 |
| `ExecutionView/frontend/src/modules/costview/lib/export.ts` | 276 | | CostView 导出功能 |
| `ExecutionView/frontend/src/modules/costview/lib/thresholds.ts` | 222 | | TCA 阈值逻辑 |
| `ExecutionView/frontend/src/modules/costview/lib/storage.ts` | 124 | | CostView LocalStorage |
| `ExecutionView/frontend/src/modules/databaseview/DatabaseViewModule.tsx` | 134 | | DatabaseView 模块壳 |
| `ExecutionView/frontend/src/modules/databaseview/components/SchemaSamplePanel.tsx` | 289 | | Schema 采样面板 |
| `ExecutionView/frontend/src/modules/databaseview/components/DatabaseDetailDrawer.tsx` | 151 | | 数据库详情抽屉 |
| `ExecutionView/frontend/src/modules/marketview/lib/workspace.ts` | 29 | | MarketView 工作区 |

### 前端——应用壳

| 文件 | 行数 | 标签 | 说明 |
|------|------|------|------|
| `ExecutionView/frontend/src/App.tsx` | 345 | | 应用根组件 |
| `ExecutionView/frontend/src/main.tsx` | 9 | | React 入口 |
| `ExecutionView/frontend/src/index.css` | 137 | | 全局样式 |
| `ExecutionView/frontend/src/sections/WorkspaceModuleTabs.tsx` | 123 | | 工作区模块标签 |
| `ExecutionView/frontend/src/sections/ExecutionViewTabs.tsx` | 100 | | 执行视图标签 |
| `ExecutionView/frontend/src/sections/Toolbar.tsx` | 203 | | 工具栏 |
| `ExecutionView/frontend/src/sections/ToastContainer.tsx` | 86 | | 消息提示容器 |
| `ExecutionView/frontend/src/sections/LazyOrderBoard.tsx` | 133 | | 懒加载订单面板 |
| `ExecutionView/frontend/src/components/startup-gate.tsx` | 112 | | 启动门控组件 |

### 前端——Stream Store

| 文件 | 行数 | 标签 | 说明 |
|------|------|------|------|
| `ExecutionView/frontend/src/stores/order-stream-store.ts` | 39 | | 订单流状态存储 |
| `ExecutionView/frontend/src/stores/route-stream-store.ts` | 39 | | 路由流状态存储 |

### 运维脚本（关键）

| 文件 | 行数 | 标签 | 说明 |
|------|------|------|------|
| `scripts/workflow/auto_runner.py` | 582 | ⚠️超限 | CI 自动化 CLI——run-step/check-step/run-all |
| `scripts/import_excel_fills.py` | 590 | ⚠️超限 | Excel 填充导入（含 HK→NY 时区转换） |
| `scripts/service-manager.ps1` | 519 | ⚠️超限 | 核心服务管理器（start/stop/restart/status/logs） |
| `scripts/fetch_and_inspect.py` | 211 | | 获取+逐步检查填充数据 |
| `scripts/mcp/knowledge-server.py` | 149 | | MCP 知识服务器 |
| `scripts/deploy/deploy.sh` | 193 | | Docker Compose 生产部署 |
| `scripts/workflow/sync_execution_status.py` | 202 | | 交付状态同步 |
| `scripts/workflow/validate_phase_gate.py` | 154 | | 冲刺门验证 |

## Legacy / 待清理 ⚠️

| 文件 | 行数 | 标签 | 说明 |
|------|------|------|------|
| `CostView/frontend/src/README.md` | 8 | | 遗留 CostView 前端占位，已废弃 |
| `CostView/src/outdated_tickers.py` | 68 | | 过时股票代码检测——名称暗示待清理 |
| `CostView/src/regime/sync_macro_calendar.py` | 79 | | 参照数据同步脚本——应合并到统一加载流程 |
| `CostView/src/regime/sync_market_mapping.py` | 72 | | 参照数据同步脚本——应合并 |
| `CostView/src/regime/sync_macro_event_dict.py` | 46 | | 参照数据同步脚本——应合并 |
| `ExecutionView/backend/api/routers/database.py` | 49 | | 数据库管理路由——180 行注释，调试/运维用途 |
| `ExecutionView/backend/api/routers/debug.py` | 92 | | 调试路由——仅开发环境使用 |
| `ExecutionView/backend/api/.pytest_cache/README.md` | 5 | | 应加入 .gitignore |
| `scripts/_archive/2026-04-28/*` | — | | 已归档诊断脚本，可删除 |
| `scripts/diagnose/diagnose_orders_display.py` | 177 | | 一次性诊断脚本 |
| `scripts/diagnose/diagnose_exchange_ticker_issue.py` | 171 | | 一次性诊断脚本 |
| `scripts/diagnose/diagnose_odd_lot.py` | 80 | | 一次性诊断脚本 |
| `scripts/diagnose/diagnose_market_data.py` | 63 | | 一次性诊断脚本 |
| `scripts/diagnose/diagnose_order.py` | 96 | | 一次性诊断脚本 |
| `$null` | 0 | | 空文件，应删除 |

## 测试

| 文件 | 行数 | 标签 | 说明 |
|------|------|------|------|
| `ExecutionView/backend/api/tests/test_parent_child_execution.py` | 324 | | 父子执行集成测试 |
| `ExecutionView/backend/api/tests/test_algo_scheduler.py` | 319 | | 算法调度器测试 |
| `ExecutionView/backend/api/tests/test_bloomberg_adapter_routing.py` | 293 | | Bloomberg 适配器路由测试 |
| `ExecutionView/backend/api/tests/test_batch_route_endpoints.py` | 289 | | 批量路由端点测试 |
| `ExecutionView/backend/api/tests/test_benchmark_engine.py` | 295 | | 基准引擎测试 |
| `ExecutionView/backend/api/tests/test_compliance_service.py` | 142 | | 合规服务测试 |
| `ExecutionView/backend/api/tests/test_platform_data_access.py` | 231 | | 跨域数据访问测试 |
| `ExecutionView/backend/api/tests/test_bloomberg_adapter_refdata.py` | 39 | | Bloomberg 参照数据测试 |
| `ExecutionView/backend/api/tests/test_realtime_gateway.py` | 103 | | 实时推送网关测试 |
| `ExecutionView/backend/api/tests/test_service_provider.py` | 69 | | 服务工厂测试 |
| `ExecutionView/backend/api/tests/test_config_service.py` | 89 | | 配置服务测试 |
| `ExecutionView/backend/api/tests/test_auth_policy.py` | 66 | | 认证策略测试 |
| `ExecutionView/backend/api/tests/test_db_bootstrap.py` | 32 | | 数据库初始化测试 |
| `ExecutionView/backend/api/tests/test_connection_router.py` | 97 | | 连接路由测试 |
| `ExecutionView/backend/api/tests/test_marketview_router.py` | 143 | | MarketView 路由测试 |
| `ExecutionView/backend/api/tests/test_execution_history_router.py` | 131 | | 执行历史路由测试 |
| `ExecutionView/backend/api/tests/test_projection_repositories.py` | 20 | | 投影仓储测试 |
| `ExecutionView/frontend/src/services/realtime.test.ts` | 226 | | WebSocket 客户端测试 |
| `ExecutionView/frontend/src/modules/costview/lib/thresholds.test.ts` | 113 | | 阈值逻辑测试 |
| `ExecutionView/frontend/src/modules/costview/lib/report-state.test.ts` | 71 | | 报告状态测试 |
| `ExecutionView/frontend/src/modules/marketview/lib/workspace.test.ts` | 136 | | 工作区逻辑测试 |

---

## 统计摘要

| 分类 | 文件数 | 代码行 | 占比 |
|------|--------|--------|------|
| 核心抽象 ⭐⭐⭐ | 7 | 4,732 | 6.5% |
| 数据层 ⭐⭐ | 21 | 3,734 | 5.1% |
| 业务逻辑 ⭐⭐ | 46 | 16,855 | 23.0% |
| 集成层 ⭐ | 10 | 1,277 | 1.7% |
| 配置/工具 ⭐ | 68 | 18,712 | 25.5% |
| Legacy/待清理 ⚠️ | 13 | 1,053 | 1.4% |
| 测试 | 21 | 2,957 | 4.0% |
| UI 基础组件 (ui/*) | ~40 | ~3,500 | 4.8% |
| 其他（未列出的小文件） | — | ~21,443 | 28.0% |
| **总计** | **331** | **73,263** | **100%** |

> **⚠️ 超限文件汇总**（需拆分）：`bloomberg_adapter.py`(2119), `batch-route-order-dialog.tsx`(1247), `SettingsBoard.tsx`(1102), `tca_query_service.py`(1082), `adapters.py`(936), `route-modify-dialogs.tsx`(893), `repositories.py`(866), `RouteTable.tsx`(866), `pipeline.py`(808), `fill_fetch.py`(773), `processed_fills_db.py`(685), `OrderTable.tsx`(681), `MarketViewModule.tsx`(795), `raw_fills_db.py`(516), `api.ts`(587), `import_excel_fills.py`(590), `auto_runner.py`(582), `service-manager.ps1`(519), `batch_route_service.py`(474), `route_plans.py`(491), `orders.py`(482), `marketview.py`(409), `costview.py`(434), `validate_raw_fills.py`(405)
