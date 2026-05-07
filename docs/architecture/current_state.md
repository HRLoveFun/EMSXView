# 子系统身份卡

## 子系统 1: ExecutionView
- **业务职责**：实时交易执行与平台装配 — 订单/路由管理、Bloomberg EMSX 实时连接、市场快照服务、TCA 查询桥接、数据库运维接口
- **典型用户任务**：批量路由订单；选择算法策略并监控执行进度；查看市场快照和盘中特征辅助决策；触发 TCA 分析和盘后交接
- **主要入口**：
  - Web 服务：`ExecutionView/backend/api/main.py`（FastAPI 装配入口，唯一后端实例）
  - Web 备用启动：`ExecutionView/backend/api/start_server.py`
  - 前端壳：`ExecutionView/frontend/src/App.tsx`（唯一浏览器入口）
  - Shell 入口：`start-services.bat` / `scripts/service-manager.ps1`
- **主要代码路径**：`ExecutionView/`
- **关键依赖**：Bloomberg EMSX API（实时交易数据网关）、CostView（TCA 查询和管道触发）、platform_data（跨域数据适配层）

## 子系统 2: CostView
- **业务职责**：交易后分析与数据管道 — Fill 数据采集/清洗/聚合、BDIB 行情数据采集、市场状态（regime）分类、TCA 归因分析、评分卡、每日指标计算
- **典型用户任务**：每日 18:00 定时抓取 fill 数据并跑完整管道；回填历史 BDIB 数据；按 broker/算法维度运行归因分析；查询 TCA 报告和评分卡
- **主要入口**：
  - CLI 主入口：`CostView/src/__main__.py`（`python -m src`，30+ 参数）
  - 定时调度：`CostView/scripts/daily_update.py`
  - 计划任务安装：`CostView/scripts/install_scheduler.py`
  - 数据工具：`CostView/scripts/backfill_raw_bdib.py`、`CostView/scripts/run_attribution.py`
- **主要代码路径**：`CostView/`
- **关键依赖**：Bloomberg EMSX API（fill 数据抓取）、Bloomberg BDIB API（历史行情数据）、platform_data（CostViewAnalyticsAdapter 暴露给外部）

## 子系统 3: platform_data
- **业务职责**：共享逻辑数据域的适配层 — 统一跨域数据访问入口，维护 Execution 运营数据、CostView 分析数据、MarketView 参考数据之间的所有权边界
- **典型用户任务**：（非面向终端用户）ExecutionView 后端通过 `build_platform_data_access()` 获取运营数据适配器；MarketView 路由通过 `market.get_market_snapshot()` 获取市场快照；CostView 分析结果通过 `analytics.build_tca_report()` 暴露给平台
- **主要入口**：`platform_data/__init__.py`（公开 API 类型）、`platform_data/adapters.py`（4 个适配器实现）、`platform_data/repositories.py`（底层数据访问）
- **主要代码路径**：`platform_data/`
- **关键依赖**：ExecutionView 后端（运营数据仓储提供者）、CostView（分析数据源）

---

## 模块级身份卡

### MarketView（宿主于 ExecutionView 壳内）
- **业务职责**：盘前市场环境监测与标的筛选，为交易执行提供前置决策依据
- **典型用户任务**：查看日本大盘股的日内波动率/涨跌幅/成交量；按流动性预警和波动性预警筛选标的；将选中标的交接给 Execution 下单
- **主要入口**：
  - API：`GET /api/marketview/snapshot`、`GET /api/marketview/intraday-features`、`POST /api/marketview/handoff/execution`
  - 前端：`ExecutionView/frontend/src/modules/marketview/MarketViewModule.tsx`
- **主要代码路径**：`ExecutionView/backend/api/routers/marketview.py`、`ExecutionView/frontend/src/modules/marketview/`
- **关键依赖**：platform_data（MarketReferenceDataAdapter）、CostView 管道（bdib_daily_summary 数据源）
- **实现状态**：Shell anchor + 后端路由已就位，独立数据和业务逻辑尚待建设。所有运行时代码宿主于 ExecutionView。

---
