# EMSXView 最终重构方案

> 版本：2.0 | 日期：2026-05-27 | 基于分支 `refactor/architecture`  
> 合并自：架构分析报告 + 重构计划验证 + 代码洁癖审查

---

## 目录

- [1. 执行状态总览](#1-执行状态总览)
- [2. 阶段一：紧急清理（✅ 已完成）](#2-阶段一紧急清理-已完成)
- [3. 阶段二：机制性文件拆分（✅ 已完成）](#3-阶段二机制性文件拆分-已完成)
- [4. 阶段三：复杂拆分与适配器简化（⚠️ 待执行，1-2周）](#4-阶段三复杂拆分与适配器简化️-待执行1-2周)
- [5. 阶段四：后端域包组装（⚠️ 待执行，1周）](#5-阶段四后端域包组装️-待执行1周)
- [6. 阶段五：前端模块边界加固（⚠️ 待执行，1-2周）](#6-阶段五前端模块边界加固️-待执行1-2周)
- [7. 阶段六：Shell 与入口收敛（⚠️ 待执行，1周）](#7-阶段六shell-与入口收敛️-待执行1周)
- [8. 阶段七：DataPipeline 存储简化（⚠️ 待执行，1周）](#8-阶段七datapipeline-存储简化️-待执行1周)
- [9. 汇总与里程碑](#9-汇总与里程碑)

---

## 1. 执行状态总览

```
阶段一  紧急清理        ✅ 完成  Day 1
阶段二  机制性文件拆分   ✅ 完成  Day 1
阶段三  复杂拆分+适配器  ⚠️ 待执行  Week 1-2
阶段四  后端域包组装     ⚠️ 待执行  Week 2-3
阶段五  前端边界加固     ⚠️ 待执行  Week 3-4
阶段六  Shell收敛       ⚠️ 待执行  Week 4-5
阶段七  DataPipeline    ⚠️ 待执行  Week 5-6
```

**已完成合计**：4个超大文件 → 24个合理模块，`tsc --noEmit` + `pytest` 全部通过，零回退。

---

## 2. 阶段一：紧急清理 ✅ 已完成

### 执行内容

| # | 操作 | 文件 | 结果 |
|---|------|------|------|
| 1 | 删除 `DataPlatformIngestionAdapter` + 3个辅助类型 | `platform_data/adapters.py` | -110行 |
| 2 | 删除6个向后兼容别名 (`FillHistoryRow` 等) | `platform_data/adapters.py` | -10行 |
| 3 | 修复返回类型注释 (3处) | `platform_data/adapters.py` | 零lint |
| 4 | 清理 `contracts/__init__.py` 过时注释 | `platform_data/contracts/__init__.py` | -2行 |
| 5 | 更新 `platform_data/__init__.py` 导出 | `platform_data/__init__.py` | 移除死适配器 |
| 6 | 清理未使用的 `Enum`、`Optional` 导入 | `platform_data/adapters.py` | -2行 |

### 验证

```bash
grep -r "DataPlatformIngestionAdapter\|FillHistoryRow\|PipelineState" --include="*.py"  # 零引用
python -c "import platform_data"  # 导入正常
```

---

## 3. 阶段二：机制性文件拆分 ✅ 已完成

> **策略**：本次仅拆分"机械可拆"文件——即接口清晰、可按导出边界直接切割的文件。  
> 需要深入理解业务逻辑的 4 个文件移至阶段三。

### 3.1 `schemas.py` (789行 → 9个文件)

```
schemas.py (删除)
schemas/
├── __init__.py           # 聚合重导出（保持 import schemas 兼容）
├── common.py             # 枚举 + ApiResponse (74行)
├── orders.py             # Order, OrderFilters, ModifyOrderRequest (86行)
├── routes.py             # Route 系列 (117行)
├── batch.py              # 批量操作请求/响应 (138行)
├── execution.py          # 父订单执行 (28行)
├── history.py            # 执行历史记录 (106行)
├── infra.py              # 连接/启动/认证 (48行)
├── broker.py             # 经纪商算法配置 (36行)
└── route_plans.py        # 路由计划 (124行)
```

**验证**：27个消费文件的 `from schemas import X` 完全兼容，`pytest` 通过。

### 3.2 `execution-api.ts` (768行 → 6个文件)

```
execution-api.ts (变为 barrel 重导出)
services/
├── http-client.ts       # 通用 HTTP 客户端 + fetchOrders/fetchRoutes (88行)
├── orders-api.ts        # 订单 CRUD (80行)
├── routes-api.ts        # 路由 CRUD (110行)
├── broker-api.ts        # 经纪商算法接口 (65行)
└── route-plans-api.ts   # 路由计划 CRUD (60行)
```

**验证**：所有旧 `import ... from '../services/execution-api'` 路径不变，`tsc --noEmit` 通过。

### 3.3 `route-modify-dialogs.tsx` (1012行 → 6个文件)

```
route-modify-dialogs.tsx (变为 barrel 重导出)
components/
├── cancel-route-dialog.tsx       # 取消路由对话框
├── modify-amount-dialog.tsx      # 修改数量对话框
├── modify-order-type-dialog.tsx  # 修改订单类型对话框
├── modify-limit-price-dialog.tsx # 修改限价对话框
└── broker-strategy-dialog.tsx    # 经纪商策略对话框
```

**验证**：所有旧导入路径不变，`tsc --noEmit` 通过。

### 3.4 `MarketViewModule.tsx` (852行 → 3个文件)

```
MarketViewModule.tsx (精简主组件，删除函数/子面板定义)
marketview/
├── marketview-utils.tsx          # fmtNumber, fmtCompact, fmtPercent, 严重度渲染工具
└── intraday-feature-panel.tsx   # IntradayFeaturePanel 子组件 + SummaryCard
```

**验证**：`tsc --noEmit` 通过。

### 检查清单

| # | 文件 | 拆分结果 | 验证 |
|---|------|---------|------|
| 1 | schemas.py (789行) | 9个文件，最大138行 | pytest 通过 |
| 2 | execution-api.ts (768行) | 5个文件+barrel | tsc --noEmit 通过 |
| 3 | route-modify-dialogs.tsx (1012行) | 5个文件+barrel | tsc --noEmit 通过 |
| 4 | MarketViewModule.tsx (852行) | utils + panel + 精简主组件 | tsc --noEmit 通过 |

**合计**：4个文件 → 24个合理模块，零回退。

---

## 4. 阶段三：复杂拆分与适配器简化 ⚠️ 待执行，1-2周

### 目标

将阶段二未能机械拆分的 4 个复杂文件与适配器层简化合并执行。这8项任务都需要对业务逻辑有深入理解，统一分配 1-2 周。

### 4.1 复杂文件拆分（4个，需业务分析）

| # | 文件 | 当前大小 | 无法机械拆分的原因 | 建议策略 |
|---|------|---------|-------------------|---------|
| 1 | `batch-route-order-dialog.tsx` | 78KB | 单一巨型组件，所有批量操作逻辑深度耦合，无可独立子组件 | 拆为 `batch-route-order/` 子目录，按对话框类型分离：BatchCreateRouteDialog / BatchModifyRouteDialog / BatchCancelRouteDialog / BatchOrderDialog，提取共享的 RouteSelectionTable 和 BrokerSelector |
| 2 | `bloomberg_adapter.py` | 135KB (~3500行) | 单一超大类，按关注点拆分需要设计 Mixin 继承或委托模式 | 拆为 `bloomberg/connection.py` + `subscriptions.py` + `order_ops.py` + `route_ops.py` + `data_query.py`，主类组合委托 |
| 3 | `RouteTable.tsx` | 42KB | 列定义在 JSX 中内联，排序/筛选/渲染与表格状态深度交织 | 提取 `route-columns.tsx`（列定义）、`use-route-sort.ts`（排序）、`use-route-filter.ts`（筛选） |
| 4 | `OrderTable.tsx` | 36KB | 同上，且含订单特定的父子关系逻辑 | 同 RouteTable 策略：`order-columns.tsx` + `use-order-sort.ts` + `use-order-filter.ts` |

#### 4.1.1 `batch-route-order-dialog.tsx` 拆分目标

```
modules/execution/components/batch-route-order/
├── index.ts                    # 统一导出（保持旧 import 兼容）
├── types.ts                    # 共享类型
├── BatchRouteOrderDialog.tsx   # 主入口（<5KB）
├── BatchCreateRouteDialog.tsx
├── BatchModifyRouteDialog.tsx
├── BatchCancelRouteDialog.tsx
├── BatchOrderDialog.tsx
└── shared/
    ├── RouteSelectionTable.tsx
    ├── BrokerSelector.tsx
    └── StrategyParamsForm.tsx
```

#### 4.1.2 `bloomberg_adapter.py` 拆分目标

```
backend/api/services/bloomberg/
├── __init__.py              # 导出 BloombergEMSXService（保持旧 import 兼容）
├── connection.py            # 连接管理、心跳、会话状态
├── subscriptions.py         # 订单/路由/执行报告订阅管理
├── order_ops.py             # 创建/修改/取消订单
├── route_ops.py             # 创建/修改/取消路由
└── data_query.py            # 历史数据查询、参考数据
```

#### 4.1.3 `RouteTable.tsx` / `OrderTable.tsx` 拆分目标

```
modules/execution/views/
├── RouteTable.tsx           # 主组件（<15KB，仅表格壳 + 使用钩子）
├── route-columns.tsx        # 列定义（纯配置）
├── use-route-sort.ts        # 排序逻辑
├── use-route-filter.ts      # 筛选逻辑
├── OrderTable.tsx           # 主组件（<15KB）
├── order-columns.tsx        # 列定义
├── use-order-sort.ts        # 排序逻辑
└── use-order-filter.ts      # 筛选逻辑
```

### 4.2 薄透传适配器删除（3个）

与原始阶段三内容一致，但标记为"需业务分析"因为需要确认调用方后直接删除。

#### 4.2.1 `CostViewAnalyticsAdapter` → 直接导入

```python
# 旧（routers/costview.py）
from platform_data import CostViewAnalyticsAdapter
adapter = CostViewAnalyticsAdapter()
report = adapter.build_tca_report(filters)

# 新（routers/costview.py）
from CostView.src.tca_query_service import TcaQueryService
service = TcaQueryService()
report = service.build_tca_report(filters)
```

#### 4.2.2 `ExecutionHistoryAdapter` → 直接导入

```python
# 旧（routers/execution_history.py）
from platform_data import ExecutionHistoryAdapter
adapter = ExecutionHistoryAdapter()
history = adapter.list_fill_history(filters)

# 新（routers/execution_history.py）
from platform_data.execution_history_service import ExecutionHistoryQueryService
service = ExecutionHistoryQueryService()
history = service.list_fill_history(filters)
```

#### 4.2.3 `CostViewDatabaseAdapter` → 合并到 `database_diagnostics.py`

将 `get_regime_distribution()` 方法移到 `database_diagnostics.py`，删除适配器类（约90行）。

### 4.3 Factory Callable 注入简化

```python
# 旧
@dataclass(frozen=True)
class MarketReferenceDataAdapter:
    reader_factory: Callable[[], Any] = field(default_factory=_default_reader_factory)

# 新
@dataclass(frozen=True)
class MarketReferenceDataAdapter:
    _reader: Any = field(default=None, repr=False)
    
    def _get_reader(self):
        if self._reader is None:
            from .adapters import _ConnectionManagerDailySummaryReader
            object.__setattr__(self, '_reader', _ConnectionManagerDailySummaryReader())
        return self._reader
```

### 检查清单

| # | 操作 | 预计影响 | 验证 |
|---|------|---------|------|
| 1 | 拆分 batch-route-order-dialog.tsx | 4个新对话框 + 共享组件 | tsc --noEmit, npm test |
| 2 | 拆分 bloomberg_adapter.py | 5个子模块 + 委托主类 | pytest, Bloomberg 连接测试 |
| 3 | 拆分 RouteTable.tsx | columns + sort + filter 提取 | tsc --noEmit |
| 4 | 拆分 OrderTable.tsx | columns + sort + filter 提取 | tsc --noEmit |
| 5 | 删除 CostViewAnalyticsAdapter | `adapters.py`, `costview.py` | TCA 端点可用 |
| 6 | 删除 ExecutionHistoryAdapter | `adapters.py`, `execution_history.py` | 历史端点可用 |
| 7 | 合并 CostViewDatabaseAdapter | `adapters.py`, `database_diagnostics.py` | 制度端点可用 |
| 8 | 简化 Factory Callable | `adapters.py` | MarketView 端点可用 |

---

## 5. 阶段四：后端域包组装 ⚠️ 待执行，1周

### 目标

将后端按业务域组织，实现 Router + Service + Model + Repository 的域内聚合。13个路由文件 → 4个域包。

### 目标目录结构

```
backend/api/
├── main.py (<200行，仅应用工厂 + 路由注册)
├── config.py
├── db.py
├── deps.py
├── schemas/          # 阶段二已完成拆分
│   ├── __init__.py
│   ├── common.py
│   ├── orders.py
│   ├── routes.py
│   ├── batch.py
│   ├── execution.py
│   ├── history.py
│   ├── infra.py
│   ├── broker.py
│   └── route_plans.py
│
├── domains/
│   ├── core/         # 认证、连接、实时、调试
│   │   ├── __init__.py
│   │   ├── router.py          # 合并 auth + connection + realtime + debug
│   │   └── services/
│   │       ├── auth_service.py
│   │       └── realtime_gateway.py
│   │
│   ├── execution/    # 订单、路由、经纪商、合规、计划
│   │   ├── __init__.py
│   │   ├── router.py          # 合并 orders + routes + broker + route_plans
│   │   ├── services/
│   │   │   ├── bloomberg_client.py     # 阶段三已拆分的主入口
│   │   │   ├── route_service.py
│   │   │   ├── compliance_service.py
│   │   │   ├── benchmark_engine.py
│   │   │   └── algo_scheduler.py
│   │   ├── repositories/
│   │   │   ├── orders.py
│   │   │   ├── routes.py
│   │   │   └── audit.py
│   │   └── models/
│   │       ├── execution_state.py
│   │       └── parent_child_orders.py
│   │
│   ├── costview/     # TCA、数据库诊断
│   │   ├── __init__.py
│   │   ├── router.py          # 合并 costview + database + execution_history
│   │   └── services/
│   │       └── tca_service.py
│   │
│   └── marketview/   # 市场数据、经纪商映射
│       ├── __init__.py
│       ├── router.py          # 合并 marketview + market_broker_mapping
│       └── services/
│           └── market_data_service.py
```

### 迁移策略

#### Step 1：创建域包骨架

```bash
mkdir -p backend/api/domains/{core,execution,costview,marketview}/services
mkdir -p backend/api/domains/execution/{repositories,models}
```

#### Step 2：移动文件（保留原路径重导出）

| 原路径 | 新路径 |
|--------|--------|
| `routers/auth.py` | `domains/core/router.py`（合并） |
| `routers/connection.py` | `domains/core/router.py`（合并） |
| `routers/realtime.py` | `domains/core/router.py`（合并） |
| `routers/debug.py` | `domains/core/router.py`（合并） |
| `routers/orders.py` | `domains/execution/router.py`（合并） |
| `routers/routes.py` | `domains/execution/router.py`（合并） |
| `routers/broker.py` | `domains/execution/router.py`（合并） |
| `routers/route_plans.py` | `domains/execution/router.py`（合并） |
| `routers/costview.py` | `domains/costview/router.py`（合并） |
| `routers/database.py` | `domains/costview/router.py`（合并） |
| `routers/execution_history.py` | `domains/costview/router.py`（合并） |
| `routers/marketview.py` | `domains/marketview/router.py`（合并） |
| `routers/market_broker_mapping.py` | `domains/marketview/router.py`（合并） |

每个原文件保留一个重导出桩：
```python
# routers/orders.py（过渡期保留）
from backend.api.domains.execution.router import router  # noqa
```

#### Step 3：更新 main.py 路由注册

```python
# main.py 简化为
from domains.core.router import router as core_router
from domains.execution.router import router as execution_router
from domains.costview.router import router as costview_router
from domains.marketview.router import router as marketview_router

app.include_router(core_router)
app.include_router(execution_router)
app.include_router(costview_router, _register_optional)
app.include_router(marketview_router)
```

#### Step 4：删除旧路由文件

确认所有测试通过后，删除 `routers/` 目录下的旧文件（保留 `routers/__init__.py` 为空）。

### 检查清单

| # | 操作 | 验证 |
|---|------|------|
| 1 | 创建域包骨架 | 目录结构确认 |
| 2 | 移动并合并路由文件 | pytest（每个域包移动后） |
| 3 | 更新 main.py 路由注册 | 所有端点路径不变，pytest |
| 4 | 删除旧路由文件 | 构建通过，pytest 100% |
| 5 | 运行完整集成测试 | pytest + 手动冒烟测试 |

---

## 6. 阶段五：前端模块边界加固 ⚠️ 待执行，1-2周

### 目标

统一前端模块的路径别名、分包策略，建立清晰的模块边界检查。

### 6.1 统一路径别名

**添加缺失的别名**（`vite.config.ts` + `tsconfig.app.json`）：

```typescript
// vite.config.ts
resolve: {
  alias: {
    '@': path.resolve(__dirname, './src'),
    '@app': path.resolve(__dirname, './src/app'),
    '@shared': path.resolve(__dirname, './src/shared'),
    '@execution': path.resolve(__dirname, './src/modules/execution'),
    '@costview': path.resolve(__dirname, './src/modules/costview'),    // 新增
    '@marketview': path.resolve(__dirname, './src/modules/marketview'), // 新增
    '@databaseview': path.resolve(__dirname, './src/modules/databaseview'), // 新增
  }
}
```

### 6.2 为 execution 模块添加独立 chunk

```typescript
// vite.config.ts manualChunks 中添加
if (id.includes('/src/modules/execution/')) {
  return 'module-execution';
}
```

### 6.3 统一所有模块内部导入路径

将 CostView、MarketView、DatabaseView 中的相对导入（`../../shared/...`）替换为别名导入：

```typescript
// 旧
import { formatCurrency } from '../../shared/lib/format-utils';

// 新
import { formatCurrency } from '@shared/lib/format-utils';
```

### 6.4 建立模块依赖边界规则

**文件**：`scripts/check-module-imports.py`

```python
# 允许的跨模块导入规则
ALLOWED_IMPORTS = {
    '@execution': {'@shared', '@app', 'react', 'react-dom'},
    '@costview':   {'@shared', '@app', 'react', 'react-dom'},
    '@marketview': {'@shared', '@app', 'react', 'react-dom'},
    '@databaseview': {'@shared', '@app', 'react', 'react-dom'},
    '@shared':    {'react', 'react-dom'},  # 共享层不能导入任何模块
    '@app':       {'@shared', 'react', 'react-dom'},  # 壳层可以导入共享
}

# 禁止规则：
# - execution 不能导入 costview / marketview / databaseview
# - costview 不能导入 execution / marketview / databaseview
# - 任何模块不能导入另一个模块的内部实现
```

### 检查清单

| # | 操作 | 验证 |
|---|------|------|
| 1 | 添加 @costview, @marketview, @databaseview 别名 | `npm run dev` 启动正常 |
| 2 | execution 模块独立 chunk | `npm run build` 产物包含 `module-execution.*.js` |
| 3 | 统一模块内部导入为别名 | `tsc --noEmit` 通过 |
| 4 | 创建边界检查脚本 | `npm run lint:modules` 通过（初始 warning 模式） |
| 5 | 清理旧路径导入 | grep 确认零旧路径残留，`npm run build && npm test` 通过 |

---

## 7. 阶段六：Shell 与入口收敛 ⚠️ 待执行，1周

### 目标

将 `App.tsx` 拆分为纯粹的 Provider 嵌套入口和独立的布局壳，Execution 模块完全自包含。

### 7.1 目标文件结构

```
src/
├── app/
│   ├── App.tsx            # <30行，仅Provider嵌套
│   ├── AppShell.tsx        # <150行，布局壳 + Toast + 模块Tab
│   ├── providers/
│   │   ├── RealtimeProvider.tsx
│   │   └── AuthProvider.tsx
│   └── hooks/
│       └── use-module-navigation.ts
│
├── modules/
│   ├── execution/
│   │   ├── ExecutionModule.tsx  # 自包含入口，props: {onToast, onNavigate}
│   │   ├── hooks/
│   │   │   └── use-execution-state.ts  # 从 useAppShellState 提取
│   │   ├── services/
│   │   │   ├── execution-api.ts
│   │   │   └── realtime.ts
│   │   ├── stores/
│   │   │   ├── order-stream-store.ts
│   │   │   └── route-stream-store.ts
│   │   └── data/
```

### 7.2 App.tsx 目标代码

```tsx
// app/App.tsx — <30行
import { HandoffContractsProvider } from '@shared/hooks/use-handoff-contracts';
import { AuthProvider } from './providers/AuthProvider';
import { RealtimeProvider } from './providers/RealtimeProvider';
import { AppShell } from './AppShell';

export default function App() {
  return (
    <AuthProvider>
      <RealtimeProvider>
        <HandoffContractsProvider>
          <AppShell />
        </HandoffContractsProvider>
      </RealtimeProvider>
    </AuthProvider>
  );
}
```

### 7.3 AppShell.tsx 目标代码

```tsx
// app/AppShell.tsx — <150行
// 职责：
// 1. Toolbar（认证状态、连接状态）
// 2. StartupGate（后端就绪检查）
// 3. WorkspaceModuleTabs（4个Tab + 懒加载 + 预加载）
// 4. ToastContainer
// 5. Footer（状态栏）
// 移除：Execution-specific 状态（移入 ExecutionModule）
```

### 7.4 迁移步骤

1. **创建 Provider 组件**：从 App.tsx 提取 `AuthProvider`、`RealtimeProvider`
2. **拆分 AppShell**：从 App.tsx 提取布局壳，移除 execution 特定逻辑
3. **创建 ExecutionModule**：将执行相关状态和逻辑封装到入口组件
4. **更新 main.tsx**：指向新的 `app/App.tsx`
5. **保留旧 App.tsx 为重导出**：`export { default } from './app/App'`

### 验证

```bash
npm run dev                # 开发服务器启动
# 手动验证：WebSocket 连接成功、4个Tab切换正常、Toast 正常工作
npm run build              # 生产构建
npm test                   # 单元测试全部通过
```

---

## 8. 阶段七：DataPipeline 存储简化 ⚠️ 待执行，1周

### 目标

减少 DataPipeline 存储层的过度抽象，从 5 层简化为 2 层。

### 8.1 删除 `DatabaseFacade`

```python
# 旧
context = PipelineContext(...)
context.initialize_databases()
data = context.db.fills_read.get_fills(date)

# 新
context = PipelineContext(...)
context.initialize_databases()
fills_repo = FillsRepository(context.connection_manager)
data = fills_repo.get_fills(date)
```

### 8.2 删除 `AccessTier`

SQLite 单文件模式下读写分离无意义 → 删除 `AccessTier` 枚举，`ConnectionManager` 直接按数据库名管理连接。

### 8.3 删除 `dto.py`

DTO 与 Repository 返回的字典/数据类重复 → 删除 `dto.py`，Repository 直接返回字典或 dataclass。

### 8.4 目标存储层结构

```
storage/
├── connection.py         # ConnectionManager（保留）
├── repositories/         # 按域划分的仓库（保留）
│   ├── _base.py
│   ├── fills.py
│   ├── raw_fills.py
│   ├── market_data.py
│   ├── integrated.py
│   ├── regime.py
│   └── fetch_history.py
└── schema/               # DDL管理（保留）
    ├── columns.py
    ├── inline_ddl.py
    └── migrations/
```

### 检查清单

| # | 操作 | 影响文件 | 验证 |
|---|------|---------|------|
| 1 | 删除 DatabaseFacade | `facade.py`, `context.py`, 所有阶段文件 | `python -m DataPipeline --once` 全管道执行通过 |
| 2 | 删除 AccessTier | `connection.py` | 同上 |
| 3 | 删除 dto.py | `dto.py`, 使用DTO的文件 | 同上 |
| 4 | 更新 __init__.py 导出 | `storage/__init__.py` | import 检查 |

---

## 9. 汇总与里程碑

### 9.1 执行路线图

```
Day 1           Week 1-2        Week 2-3        Week 3-4        Week 4-5         Week 5-6
├───────────────┼───────────────┼───────────────┼───────────────┼────────────────┼───────────────┤
│ 阶段一 ✅       │ 阶段三         │ 阶段四         │ 阶段五         │ 阶段六          │ 阶段七         │
│ 紧急清理        │ 复杂拆分+      │ 后端域包组装    │ 前端边界加固    │ Shell收敛       │ DataPipeline   │
│               │ 适配器简化      │               │               │                │ 存储简化        │
│ 阶段二 ✅       │ (8项任务)       │ (1周)          │ (1-2周)         │ (1周)           │ (1周)          │
│ 机制性拆分      │ (1-2周)        │               │               │                │                │
└───────────────┴───────────────┴───────────────┴───────────────┴────────────────┴───────────────┘
```

### 9.2 里程碑与交付物

| 里程碑 | 完成标准 | 状态 |
|--------|---------|------|
| **M1: 紧急清理** | 死代码删除，-130行，零外部引用 | ✅ 完成 |
| **M2: 机制性拆分** | 4个超大文件 → 24个合理模块，tsc+pytest 全通过 | ✅ 完成 |
| **M3: 复杂拆分+适配器** | 4个剩余文件拆分完毕 + 3个薄透传适配器删除 + FactoryCallable简化 | ⚠️ 待执行 |
| **M4: 后端域包化** | 13个路由 → 4个域包，main.py <200行 | ⚠️ 待执行 |
| **M5: 前端边界清晰** | 4个模块统一别名+chunk，边界检查脚本就绪 | ⚠️ 待执行 |
| **M6: Shell收敛** | App.tsx <30行，AppShell <150行，ExecutionModule自包含 | ⚠️ 待执行 |
| **M7: 存储简化** | 5层 → 2层，全管道通过 | ⚠️ 待执行 |

### 9.3 成功指标

| 指标 | 当前 | 目标 |
|------|------|------|
| 最大文件大小 | 78KB (batch-route-order-dialog) | <25KB |
| 25KB+ 文件数 | 8 | 0 |
| platform_data/adapters.py | 1393行 | ~600行 |
| backend/api/main.py | 289行 | <200行 |
| frontend App.tsx | ~250行 | <30行 |
| 死代码行数 | 0 | 0 ✅ |
| 后端路由文件数 | 13 | 4 (域包合并) |
| 存储抽象层数 | 5 | 2 |
| 跨模块导入违规 | 未知 | 0 (通过lint:modules) |

### 9.4 风险回滚策略

每个阶段都有独立的回滚路径：

- **阶段一-三**：`git revert` 单个commit即可回滚
- **阶段四**：保留 `routers/` 旧文件的重新导出桩，出问题即恢复直接导入
- **阶段五**：边界检查脚本初始设为 warning 模式，不阻塞CI
- **阶段六**：旧 `App.tsx` 保留为重新导出桩，出问题恢复旧入口
- **阶段七**：全管道 `--once` 执行作为回归测试

---

*方案 v2.0，基于 2026-05-27 实际执行进度更新。*
