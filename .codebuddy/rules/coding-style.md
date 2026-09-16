# 编码风格规则

## 语言与框架

| 层 | 语言 | 框架 / 工具 |
|---|---|---|
| 前端 | TypeScript (strict) | React 19、Vite、shadcn/ui (Radix UI + Tailwind CSS)、Zustand、Vitest、ESLint |
| 后端 | Python 3 | FastAPI、Pydantic v2、uvicorn、SQLite/PostgreSQL、Redis |
| 数据访问（只读） | Python 3 | SQLite（mode=ro）、numpy（`data_access/`；写入侧 ETL 归独立仓库 EMSXDataPipeline） |
| 构建/部署 | Docker Compose、Nginx | Prometheus + Grafana（可选） |

---

## 命名规范

### 前端（TypeScript / React）

| 类别 | 规范 | 示例 |
|---|---|---|
| React 组件文件 | PascalCase `.tsx` | `OrderTable.tsx`、`AppShell.tsx` |
| 工具/库文件 | camelCase `.ts` | `formatDate.ts`、`validators.ts` |
| 常量文件 | camelCase `.ts` 或 `constants.ts` | `routeConstants.ts` |
| 类型定义文件 | `types.ts` 或 `types/index.ts` | `ExecutionView/module/types/` |
| React 组件 | PascalCase | `OrderTable`、`RoutePanel` |
| 自定义 Hook | `use` 前缀 + camelCase | `useOrders()`、`useShellContext()` |
| 普通函数 | camelCase | `formatOrderId()`、`parseBrokerResponse()` |
| 变量 | camelCase | `orderList`、`selectedRowId` |
| 常量 | UPPER_SNAKE_CASE | `MAX_RETRY_COUNT`、`DEFAULT_PAGE_SIZE` |
| 布尔变量 | `is`/`has`/`should` 前缀 | `isLoading`、`hasError`、`shouldRefresh` |
| 事件处理器 | `handle` + 事件名 | `handleRowClick`、`handleSortChange` |
| 服务/API 模块 | `*-api.ts` 或 `*-service.ts` | `execution-api.ts`、`handoff-api.ts` |
| Zustand Store | `*-store.ts` | `order-stream-store.ts`、`route-stream-store.ts` |
| 枚举 | PascalCase（值为 UPPER_SNAKE_CASE） | `enum OrderStatus { FILLED, PENDING }` |
| 测试文件 | `*.test.ts` / `*.test.tsx` | `order-table.test.tsx` |

### 后端（Python）

| 类别 | 规范 | 示例 |
|---|---|---|
| 模块/文件 | snake_case `.py` | `order_service.py`、`route_router.py` |
| 类 | PascalCase | `BloombergEMSXService`、`ApiResponse` |
| 函数/方法 | snake_case | `create_order()`、`get_connection_status()` |
| 变量 | snake_case | `order_id`、`broker_list` |
| 常量 | UPPER_SNAKE_CASE | `ENABLE_DB_PERSISTENCE`、`MAX_CONNECTIONS` |
| 私有成员 | `_` 前缀 | `_validate_payload()`、`_cache` |
| Pydantic Schema | PascalCase + `Schema` 后缀 | `OrderCreateSchema`、`RoutePlanSchema` |
| 测试文件 | `test_*.py` | `test_orders.py`、`test_auth.py` |

### 临时代码文件（对话/调试用）

对话过程中为验证、调试、一次性分析等目的创建的临时代码文件，必须能被一眼识别为"非交付物"，且任务结束后可安全清理。

| 类别 | 规范 | 示例 |
|---|---|---|
| 存放位置 | 统一放在仓库根的 `_tmp/` 目录下（已在 `.gitignore` 中忽略） | `_tmp/check_null_count.py` |
| 文件名前缀 | `_tmp_` + 动词/名词描述 | `_tmp_verify_schema.py`、`_tmp_analyze_fills.py` |
| Python 临时脚本 | snake_case，`_tmp_*.py` | `_tmp_inspect_route_registry.py` |
| TypeScript 临时脚本 | kebab-case，`_tmp-*.ts` | `_tmp-check-types.ts`、`_tmp-dump-state.ts` |
| 一次性 SQL | `_tmp_*.sql` | `_tmp_count_gap.sql` |
| 多次迭代版本 | 追加 `_v2`、`_v3` 后缀，避免覆盖 | `_tmp_verify_schema_v2.py` |
| 输出/产物 | `_tmp_*_output.*` 或 `_tmp/output/` 目录 | `_tmp_fills_count_output.csv` |

约定：

- 临时文件**禁止**放入业务目录（`backend/`、`frontend/src/`、`data_access/` 等），避免污染模块结构
- 临时文件**禁止**被生产代码 import / require
- 任务完成后由创建方负责清理；若需保留作为参考，应迁移到 `scripts/ops/`（运维脚本）或 `docs/`（分析笔记），并去除 `_tmp_` 前缀
- 命名必须体现用途，禁止使用 `_tmp_1.py`、`_tmp_test.py` 这类无意义命名

---

## 代码风格

### 通用

- 优先使用 `const`，避免 `let`，禁止 `var`
- 使用箭头函数，除非需要 `this` 绑定
- 优先使用函数式编程范式（`map` / `filter` / `reduce`）
- 使用解构赋值提取对象和数组属性
- 每个函数不超过 30 行，使用 early return 减少嵌套
- 不使用的变量/参数必须移除（`noUnusedLocals` / `noUnusedParameters`）

### TypeScript / React 专项

- 开启 strict mode（`strictNullChecks`、`erasableSyntaxOnly`）
- 使用路径别名导入，禁止深层相对路径（别名映射见 `vite.config.ts` 与 `tsconfig.app.json`）
- React 组件使用函数组件 + Hooks，不使用 class 组件
- 一个文件仅导出一个组件（默认导出），辅助类型/工具可命名导出
- 事件处理函数与 JSX 属性保持一致命名
- **表单/对话框的「打开或切换目标时重置」一律用「调用方 `key` 重挂载 + state 初值取自 props」**，
  禁止在 `useEffect` 内同步 `setState` 回填；同理「某 prop 变化 ⇒ 同步本地 state」应改为派生值或 key。
  反例与修法见 `specs/021-t10-form-reset-refactor/plan.md`；`react-hooks/set-state-in-effect` 已在
  CI 硬阻断（`npm run lint` + `npm run lint:modules`），新增即失败
- **取数一律走 `@shared/hooks/use-async-data`**（`useAsyncData(key, loader, onData?)`）：
  loading 由 key 派生、setState 只发生在 Promise 回调内。禁止在 `useEffect` 内手写
  `setIsLoading(true) + void load()`；loader 必须是**纯取数**（内部不得 setState）。
  示例与迁移记录见 `specs/022-t11-async-data-layer/plan.md`

### Python / FastAPI 专项

- 遵循 PEP 8，使用 4 空格缩进
- 所有 API 响应必须用 Pydantic v2 模型封装在 `ApiResponse` 中
- 使用 `Depends()` 进行依赖注入（参考 `backend/api/deps.py`）
- 可选路由器使用 `_register_optional` 模式，不得影响核心 ExecutionView
- 数据配置统一从 `data_access/config.Config` 导入（`Config.DATA_DIR` 由环境变量 `EMSXVIEW_DATA_DIR` 覆盖），禁止硬编码路径/表名

### PowerShell / 运维脚本专项

- `scripts/**/*.ps1` 若含非 ASCII 内容，**必须保存为 UTF-8 with BOM**
- 原因：Windows PowerShell 5.1 对**无 BOM** 文件按 ANSI(cp1252) 解码，中文会被误解析
  （字节 `0x93`/`0x94` → 智能引号，被当作字符串定界符 ⇒ `ParserError`）。仓库内每日同步计划任务
  （`wt-sync.ps1`）与 `.bat` 启动器（`service-manager.ps1`）都以 `powershell`（5.1）调用；
  PowerShell Core 下正常，故该问题不会在开发机上自发暴露
- 守卫：`backend/api/tests/boundaries/test_ps1_encoding.py`（CI 边界测试内执行，规则 ID `PS1-ENC`）
- 参考：[`docs/spec/adr/`]，实测记录见 `specs/016-wt-finish-robustness/plan.md`

---

## 类型定义

### TypeScript

- 使用 `interface` 定义对象类型，不使用 `type` 定义对象结构
- 使用 `type` 定义联合类型、交叉类型和工具类型
- 为所有函数参数和返回值添加类型注解
- 导出所有在其他文件中使用的类型（`export interface`）
- 避免使用 `any`，优先使用 `unknown` 或具体类型
- 泛型参数使用有意义的名称（如 `TItem` 优于 `T`）

```typescript
// ✅ 推荐
interface OrderItem {
  id: string;
  status: OrderStatus;
  quantity: number;
}

type OrderFilter = (item: OrderItem) => boolean;
type ResultState = 'idle' | 'loading' | 'success' | 'error';
```

### Python

- 所有 Pydantic 模型通过 `BaseModel` 继承
- 方法签名需添加类型注解（返回值和参数）
- 使用 `Optional[X]` 表示可为 `None` 的类型
- 复杂数据结构使用 `TypedDict` 或 Pydantic 模型

---

## 错误处理

### 前端

- API 调用统一在 service 层处理错误，组件层只消费数据
- 使用 try-catch 包裹异步操作，向用户展示 toast 提示
- 空状态/加载状态/错误状态必须在组件中覆盖（三态处理）
- 使用 early return + 边界条件检查替代深层 if-else

```typescript
// ✅ 推荐：三态覆盖
if (isLoading) return <LoadingSkeleton />;
if (error) return <ErrorBanner message={error} />;
if (!orders.length) return <EmptyState />;
return <OrderTable orders={orders} />;
```

### 后端

- 使用 FastAPI `HTTPException` 返回标准错误响应
- 所有 HTTPException 必须包含有意义的 `detail` 消息
- 服务层异常由路由层统一捕获并转换为 HTTP 响应
- 外部服务调用（Bloomberg EMSX、Redis、PostgreSQL）必须包裹 try-except 并提供降级方案
- 数据库操作失败不得影响 API 基础可用性（`ENABLE_DB_PERSISTENCE` 门控）

```python
# ✅ 推荐
from fastapi import HTTPException

@router.get("/orders/{order_id}")
async def get_order(order_id: str):
    order = await order_service.get_by_id(order_id)
    if not order:
        raise HTTPException(status_code=404, detail=f"订单 {order_id} 不存在")
    return ApiResponse(data=order)
```

---

## 文件放置规范（★ 强制）

创建任何新文件前，**必须先确定其按功能归属的既有目录**，禁止图省事直接落到仓库根目录。

### 根目录白名单

仓库根**只允许**存在以下既有约定文件，新增任何文件（含脚本、文档、临时产物）均不得置于根目录：

`AGENTS.md`、`CODEBUDDY.md`、`README.md`、`QUICKSTART.md`、`.emsxview-root`、`.gitignore`、各模块目录与其他既有配置。

### 功能 → 目录映射

| 文件类别 | 归属目录 |
|---|---|
| 后端业务代码（FastAPI / 服务 / 路由 / Schema） | `backend/api/` 下对应分层子目录 |
| CostView 服务与逻辑 | `CostView/api/`、`CostView/src/`、`CostView/tests/` |
| MarketView 服务 | `MarketView/` |
| 只读数据访问层 | `data_access/`（写入侧 ETL 已迁独立仓库 EMSXDataPipeline，本仓库不承载） |
| 跨模块适配器 | `platform_data/adapters/`、`platform_data/contracts/` |
| 前端共享代码 | `frontend/src/shared/`（`hooks/` `lib/` `services/` `types/`） |
| 前端模块代码 | **仓库根级独立模块**（与 `frontend/` 平级）：`ExecutionView/module/`、`CostView/module/`、`MarketView/module/`，各带 `standalone/` 独立构建入口（见 `specs/012-executionview-root-extract/plan.md`、`specs/018-costview-marketview-root-extract/plan.md`）。`frontend/src/` **只保留壳层与共享层**（`app/`、`shared/`、`components/`），不再存放业务模块 |
| 前端包管理 | npm workspaces 根 `package.json`（成员 `frontend` + `ExecutionView`）；lockfile **唯一在仓库根**，安装入口为仓库根 `npm install` / `npm ci`（ADR-0020） |
| 前端共享 UI 组件 | `frontend/src/components/`、`frontend/src/components/ui/` |
| 测试 | 各模块自身 `tests/`（Python）或 `__tests__/`（前端） |
| 运维/诊断脚本 | `scripts/`（部署启动器归 `scripts/deploy/`） |
| 规范类文档 | `docs/spec/` |
| 其他文档（分析笔记、操作记录） | `docs/` |
| 特性计划与清单 | `specs/<feature-id>/` |
| 临时调试代码 | 仓库根 `_tmp/`（已在 `.gitignore` 中忽略，见「临时代码文件」一节） |
| 运行产物（日志、导出、生成图片等） | 被 `.gitignore` 覆盖的目录，或系统临时目录 |

### 判定原则

1. **先查既有目录**：优先复用相邻同类的既有路径，不新建平级目录。
2. **无明确归属时先确认**：若某类文件尚无约定目录，应先征询用户或查阅 `docs/spec/project-structure.md`，**不得默认落到根目录**。
3. **临时与交付物分离**：验证、调试、一次性分析产物一律走 `_tmp/`，禁止混入业务目录，任务结束由创建方清理。
4. **跨模块共享上移**：被两个及以上模块引用的配置或工具，按 `module-boundary.md §7` 上移至 `frontend/src/shared/` 或 `platform_data/`，不得在模块内各存一份。

---

---

## 状态管理与数据流

### 前端

- **全局应用状态**：React Context（`ShellContext`，通过 `useShellContext()` 访问）
- **实时数据流（订单/路由）**：Zustand store（`order-stream-store`、`route-stream-store`）
- **跨模块通信**：`ModuleRegistry` 注册 + `useHandoffContracts()` hook + `handoff-api.ts` 服务
- **模块内部状态**：优先使用 `useState` / `useReducer`，跨组件共享提取为自定义 Hook
- **服务端状态**：模块内 `services/` 目录封装 API 调用，组件不直接使用 fetch/axios

### 后端

- **依赖注入**：通过 FastAPI `Depends()` 链式注入服务实例
- **数据库门控**：所有读写走 `RepositoryProvider`，由 `ENABLE_DB_PERSISTENCE` 标志统一控制
- **跨模块数据交换**：`HandoffExchangeAdapter`（memory/redis 两种后端，通过 `HANDOFF_BACKEND` 配置）

---

## API 约定

### 后端 API 设计

- RESTful 风格
- 统一响应格式：Pydantic `ApiResponse` 模型封装

```json
{
  "success": true,
  "data": { ... },
  "message": "",
  "error_code": null
}
```

- 错误码规范：
  - 400：请求参数错误
  - 401：未认证
  - 403：无权限
  - 404：资源不存在
  - 422：验证失败（Pydantic 校验）
  - 500：服务器内部错误
- WebSocket 端点：`/ws/*` 用于实时数据推送（Bloomberg 订单/路由更新）
- 部署模式隔离：通过 `EMSXVIEW_MERGE_MODULES` 环境变量控制路由加载范围
