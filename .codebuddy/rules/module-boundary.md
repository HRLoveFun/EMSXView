# 模块边界契约

> AI agent 改 import 前必读
> 配套检测：`tests/boundaries/test_cross_module_imports.py`
> 配套规范：[ADR-0002](../docs/spec/adr/0002-platform-data-adapter-pattern.md)、[ADR-0003](../docs/spec/adr/0003-executionview-owns-operational-state.md)、[ADR-0005](../docs/spec/adr/0005-data-pipeline-extraction.md)
> Last updated: 2026-06-03

---

## 规则格式

每条规则用五元组表达：

```
CAN:         允许的调用
CANNOT:      禁止的调用
DETECT:      可执行的检测命令
TEST:        配套的边界测试
RATIONALE:   决策理由（链接到对应 ADR）
```

---

## 1. 前端模块间边界

### 1.1 execution ↔ costview

**CAN**:
- 触发 "view TCA report" 导航：`navigateTo('costview')`
- 通过 `useHandoffContracts()` 接收 costview 推送的合约
- 共享 `@shared/types` 中的纯类型定义

**CANNOT**:
- 直接 `import` `@costview/*`（除公共类型 re-export）
- 共享 Zustand store 状态
- 直接读取/修改对方模块的 services/ 内部方法

**DETECT**:
```bash
rg "from ['\"]@costview" frontend/src/modules/execution/
rg "useOrderStreamStore|useRouteStreamStore" frontend/src/modules/costview/
```

**TEST**: `tests/boundaries/test_cross_module_imports.py::test_execution_no_costview_imports`

**RATIONALE**: execution 与 costview 是独立 lazy chunk，跨模块 import 会导致打包体积泄漏与循环依赖。[ADR-0008](../docs/spec/adr/0008-frontend-module-registry-pattern.md)

---

### 1.2 costview ↔ marketview / databaseview

**CAN**:
- 同上，通过 `navigateTo` / `useHandoffContracts` 交互
- 共享 `@shared/types` 类型

**CANNOT**:
- 任何 `import @marketview/*` / `import @databaseview/*`

**DETECT**:
```bash
rg "from ['\"]@(marketview|databaseview)" frontend/src/modules/costview/
```

**TEST**: `tests/boundaries/test_cross_module_imports.py::test_cross_module_no_direct_imports`

---

### 1.3 execution ↔ marketview

**CAN**:
- 通过 `navigateTo('marketview')` 触发导航
- 通过 `useHandoffContracts()` 接收 marketview 推送的候选合约
- 共享 `@shared/types` 中的纯类型定义

**CANNOT**:
- 直接 `import @marketview/*`
- 共享 Zustand store 状态

**DETECT**:
```bash
rg "from ['\"]@marketview" frontend/src/modules/execution/
```

---

### 1.4 execution ↔ database (id='database', 目录名 databaseview)

**CAN**:
- 通过 `navigateTo('database')` 触发导航

**CANNOT**:
- 直接 `import @databaseview/*`
- 在 execution 模块中调用 DatabaseView 的内部方法

**DETECT**:
```bash
rg "from ['\"]@databaseview" frontend/src/modules/execution/
```

---

### 1.5 costview ↔ database

**CAN**:
- 通过 `navigateTo('database')` 触发导航
- 通过 `platform_data.database.*` 读取 CostView SQLite 库诊断（database 视图暴露后端只读 API）

**CANNOT**:
- 直接 `import @databaseview/*`

**DETECT**:
```bash
rg "from ['\"]@databaseview" frontend/src/modules/costview/
```

---

### 1.3 任何模块 → shared

**CAN**: 自由 `import @shared/*`、`import @/components/*`

**CANNOT**: 跨模块的私有 hooks/services/stores

**RATIONALE**: `@shared/` 是契约层，只能放跨模块通用代码。

---

## 2. 后端模块间边界

### 2.1 backend/api (Core :3000) ↔ CostView/src (Analytics :8002)

**CAN**:
- 通过 `platform_data.analytics.*` 读取 TCA 报告
- 通过 `platform_data.execution_history.*` 读取成交历史
- 通过 `platform_data.database.*` 读取 regime 分布

**CANNOT**:
- 直接 `from CostView.src.* import ...`（任何子模块）
- 跨域写 `processed_fills.db` / `regime.db`
- 把 `CostView/src/db/` 当持久化层

**DETECT**:
```bash
rg "from CostView\.src" backend/api/
rg "from CostView\.src" platform_data/
```

**TEST**: `tests/boundaries/test_cross_module_imports.py::test_no_costview_deep_imports`

**RATIONALE**: CostView 已重构为分析层，不再暴露内部数据访问。[ADR-0004](../docs/spec/adr/0004-costview-focused-on-evaluation.md)、[ADR-0005](../docs/spec/adr/0005-data-pipeline-extraction.md)

---

### 2.2 backend/api ↔ DataPipeline

**CAN**:
- 通过 `platform_data.data_platform.*` 触发 ingestion、查询 pipeline 状态
- 通过 `DataPipeline.config.Config` 读取 DB 路径（仅配置层）

**CANNOT**:
- 直接 `from DataPipeline.src.* import ...`（任何内部子模块）
- 绕过 `Config` 硬编码 `.db` 路径

**DETECT**:
```bash
rg "from DataPipeline\.src" backend/api/
rg "\.db['\"]" backend/api/ | rg -v "config\.py"
```

**TEST**: `tests/boundaries/test_db_path_from_config.py`

**RATIONALE**: Data Platform 是独立子域，跨域必须经适配器或配置桥接。[ADR-0006](../docs/spec/adr/0006-dataplatform-as-independent-subdomain.md)、[ADR-0012](../docs/spec/adr/0012-config-isolation-rule.md)

---

### 2.3 platform_data 内部适配器可见性

> **状态说明**：`platform_data.adapters` 已拆分为子包（`handoff.py` / `market.py` / `redis_handoff.py` / `tca_bridge.py`）。`ExecutionOperationalDataAdapter`、`CostViewAnalyticsAdapter`、`CostViewDatabaseAdapter`、`ExecutionHistoryAdapter`、`DataPlatformIngestionAdapter` 与 `PlatformDataAccess` / `build_platform_data_access()` **为规划中、尚未实现**，禁止跨域 import 使用（详见 `docs/spec/adr/0013-platform-data-adapter-current-state.md`）。后续若实现新适配器，按 [module-onboarding.md §B](../docs/spec/module-onboarding.md) 流程补登本表。

每个 Adapter 类**显式区分**外部可见方法与内部私有方法。
约定：内部方法以 `_` 开头，跨域**禁止**调用 `_` 前缀方法。

#### 实际存在的适配器

| 适配器 | 文件 | 外部可见方法 | 内部私有（禁止跨域调用） |
|---|---|---|---|
| `HandoffExchangeAdapter` | `platform_data/adapters/handoff.py` | `publish_market_to_execution`, `get_market_to_execution`, `clear_market_to_execution`, `publish_execution_to_cost`, `get_execution_to_cost`, `list_execution_to_cost`, `publish_cost_to_execution`, `list_cost_to_execution`, `clear_cost_to_execution`, `describe` | `_lock`, `_market_to_execution`, `_execution_to_cost`, `_cost_to_execution` |
| `RedisHandoffExchangeAdapter` | `platform_data/adapters/redis_handoff.py` | 同 HandoffExchangeAdapter 公开方法 | `_redis_pool` 等所有内部 |
| `MarketReferenceDataAdapter` | `platform_data/adapters/market.py` | `get_market_snapshot`, `get_intraday_features` 等 | `_DEFAULT_STOCK_POOLS`, `_liquidity_severity`, `_round_or_none`, `_severity_at_least`, `_sort_market_rows`, `_to_optional_float`, `_volatility_severity` |

#### 平台级函数（适配器工厂）

| 函数 | 文件 | 用途 |
|---|---|---|
| `get_shared_handoff_exchange()` | `platform_data/adapters/handoff.py` | 进程级 handoff 适配器单例（依据 `EMSXVIEW_HANDOFF_BACKEND` 选 memory / redis） |
| `get_tca_query_service()` | `platform_data/adapters/tca_bridge.py` | TCA 查询服务工厂 |
| `register_tca_service_impl(impl)` | `platform_data/adapters/tca_bridge.py` | TCA 实现注入（避免直接 import CostView 内部） |

**DETECT**:
```bash
rg "platform_data\..*\._" backend/ frontend/src/
```

**TEST**: `tests/boundaries/test_cross_module_imports.py::test_no_underscore_adapter_access`

**RATIONALE**: 公开/私有分界防止内部实现细节泄漏到跨域调用方。

---

## 3. 前端 ↔ 后端边界

### 3.1 跨域调用方式

**CAN**:
- 前端通过 `/api/*` REST + `/ws/*` WebSocket
- 通过 Vite 代理（同源开发，`/api` → `http://localhost:3000`）
- 通过 `import.meta.env.VITE_API_URL` 配置后端地址

**CANNOT**:
- 前端代码 `import` `backend/api/*` Python 模块
- 后端代码 `import` `frontend/src/*` TypeScript 模块
- 前端直接连接 `:8001` / `:8002`（必须走 Nginx 或 Vite 代理）
- 前端 `fetch('http://localhost:8001/...')`（绕过 Vite 代理）

**DETECT**:
```bash
rg "fetch\(['\"]http://localhost:(8001|8002)" frontend/src/
rg "from ['\"].*backend/api" frontend/src/
```

**RATIONALE**: 跨语言 import 在物理上不可能，但端口绕过会导致 CORS 与生产部署不一致。[ADR-0009](../docs/spec/adr/0009-blend-of-microservice-and-monolith.md)

---

## 4. 数据访问边界

### 4.1 后端业务数据访问

**CAN**:
- 业务数据 CRUD → `repositories/` 层方法
- 跨 repository 组合 → service 层编排
- 跨域数据 → `platform_data` 适配器
- 数据库连接 → `db.py` + `service_provider.RepositoryProvider`

**CANNOT**:
- 在 `routers/` 直接执行 SQL
- 硬编码 `*.db` 路径
- 绕过 `ENABLE_DB_PERSISTENCE` 门控
- 在 service 层新建 SQLAlchemy session（应走 repository）

**DETECT**:
```bash
rg "SELECT|INSERT|UPDATE|DELETE" backend/api/routers/
rg "create_engine|sessionmaker" backend/api/routers/ backend/api/services/
rg "\.db['\"]" backend/api/ | rg -v "config\.py"
```

**TEST**: `tests/boundaries/test_db_path_from_config.py`

**RATIONALE**: 三层架构（router → service → repository）是分层原则的直接体现。

---

### 4.2 CostView 分析数据访问

**CAN**:
- 通过 `platform_data.adapters.get_tca_query_service()` 调用 TCA / scorecard 查询（读取 `tca_route_summary` 汇总表）
- 通过 `platform_data.execution_history_service` 读取执行历史
- （`CostViewDatabaseAdapter` / `CostViewAnalyticsAdapter` / `platform_data.database.*` / `platform_data.analytics.*` 为规划中，尚未实现）

**CANNOT**:
- 直接 `from CostView.src.db.repositories.* import ...`（应走适配器）

**RATIONALE**: 见 [ADR-0002](../docs/spec/adr/0002-platform-data-adapter-pattern.md)。

---

## 5. 配置与环境变量

**CAN**:
- 通过 `DataPipeline.config.Config` 读取所有 DB 路径
- 通过 `backend/api/config.py` 读取应用级配置
- 通过 `os.getenv('EMSXVIEW_*')` 读取环境变量门控

**CANNOT**:
- 业务代码硬编码 `*.db` 路径字符串
- 业务代码硬编码表名字面量
- 业务代码绕过 `Config` 直接 `os.path.join(BASE_DIR, 'data', 'raw_fills.db')`

**DETECT**:
```bash
rg "['\"][^'\"]*\.db['\"]" backend/ DataPipeline/ | rg -v "config\.py"
```

**TEST**: `tests/boundaries/test_db_path_from_config.py`

**RATIONALE**: [ADR-0012](../docs/spec/adr/0012-config-isolation-rule.md)。

---

## 6. 实时通信

### 6.1 WebSocket 端点声明

**CAN**:
- 模块在 `module.registry.ts` 中声明 `realtimeWsPath`
- Shell 通过 `moduleRegistry.getAll()` 发现 WS 端点
- 单一 `RealtimeClient` 由 Shell 管理

**CANNOT**:
- 业务模块在内部 `new WebSocket(...)` 自行连接
- 业务模块注册多个 WS 端点

**DETECT**:
```bash
rg "new WebSocket\(" frontend/src/modules/
```

**RATIONALE**: Shell 统一管理 WS 连接生命周期与重连。[ADR-0008](../docs/spec/adr/0008-frontend-module-registry-pattern.md)

---

## 7. 跨模块状态共享

**CAN**:
- 跨模块的只读配置 → `@shared/types` + `@shared/lib`
- 跨模块的临时事件 → `useHandoffContracts()`（[ADR-0007](../docs/spec/adr/0007-handoff-exchange-pattern.md)）
- Shell 全局状态 → `ShellContext` (`useShellContext()`)

**CANNOT**:
- 业务模块读取/修改其他模块的 Zustand store
- 通过 props drilling 跨 3 层以上传递模块级数据

**DETECT**:
```bash
rg "useOrderStreamStore|useRouteStreamStore" frontend/src/modules/costview/ frontend/src/modules/marketview/ frontend/src/modules/databaseview/
```

**RATIONALE**: 跨模块 store 访问会破坏模块独立性。

---

## 附录 A：检测脚本一键运行

```bash
# 跨域 deep import 检测
python scripts/audit_cross_imports.py

# DB 路径硬编码检测
python scripts/audit_db_paths.py

# 适配器下划线访问检测
python scripts/audit_underscore_access.py

# 文档漂移检测
python scripts/audit_doc_drift.py
```

详细脚本见 `scripts/` 目录。
