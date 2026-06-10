<!--
Sync Impact Report
==================
Version change: [initial] → 1.0.0
Type: INITIAL — first fill of constitution template

Modified principles: N/A (all new)
Added sections:
  - I. 模块自治与边界契约 (Module Autonomy & Boundary Contracts)
  - II. 分层架构与职责分离 (Layered Architecture & Responsibility Separation)
  - III. 类型安全与静态校验 (Type Safety & Static Validation)
  - IV. 配置即契约 (Configuration as Contract)
  - V. 实时数据统一管理 (Unified Realtime Management)
  - 技术栈约束 (Technology Stack Constraints)
  - 开发工作流 (Development Workflow)
  - Governance
Removed sections: N/A

Templates requiring updates:
  - .specify/templates/plan-template.md → ✅ no update needed (Constitution Check gate filled dynamically)
  - .specify/templates/spec-template.md → ✅ no update needed (no constitution references)
  - .specify/templates/tasks-template.md → ✅ no update needed (no constitution references)
  - .specify/templates/checklist-template.md → ✅ no update needed (no constitution references)
  - .specify/templates/commands/ → ✅ not present

Follow-up TODOs: none
-->

# EMSXView Constitution

## Core Principles

### I. 模块自治与边界契约 (Module Autonomy & Boundary Contracts)

每个业务模块 MUST 是独立可部署的单元，通过显式契约进行跨模块交互。不允许隐式跨模块依赖。

**规则**:
- 跨模块通信 MUST 通过 `ModuleRegistry`（前端）或 `platform_data` 适配器（后端）
- 前端模块间禁止直接 `import` 对方模块的 services/hooks/stores（`@execution/*`/`@costview/*`/`@marketview/*`/`@databaseview/*`）
- 后端模块间禁止直接 `from CostView.src.*` 或 `from DataPipeline.src.*`
- 跨模块数据交换 MUST 通过 `HandoffExchangeAdapter`（memory/redis 可配置后端）
- 适配器 MUST 显式区分公开/私有方法（`_` 前缀为私有，禁止跨域调用）
- 所有新增跨模块依赖 MUST 在模块边界契约文档（`.codebuddy/rules/module-boundary.md`）中登记
- 跨模块 store 访问 MUST NOT 发生（如 `useOrderStreamStore`/`useRouteStreamStore` 仅限所属模块）

**理由**: 模块独立可部署性是微服务架构的核心保障。隐式依赖导致打包体积泄漏、循环依赖和生产部署不一致。
相关 ADR: [ADR-0002](../docs/spec/adr/0002-platform-data-adapter-pattern.md)、[ADR-0008](../docs/spec/adr/0008-frontend-module-registry-pattern.md)

### II. 分层架构与职责分离 (Layered Architecture & Responsibility Separation)

代码 MUST 遵循严格的分层架构，每层有明确的职责边界。

**规则**:
- **后端**: Router → Service → Repository 三层 MUST 严格遵守
  - Router 层只处理 HTTP 请求/响应转换，禁止直接执行 SQL
  - Service 层编排业务逻辑，禁止创建 SQLAlchemy session
  - Repository 层封装数据访问，通过 `RepositoryProvider` 统一门控（`ENABLE_DB_PERSISTENCE`）
- **前端**: Module → View → Component → UI Element
  - API 调用 MUST 封装在 `services/` 层，组件不得直接使用 fetch/axios
  - 状态管理通过 Context（全局 ShellContext）和 Zustand（实时流），禁止 prop drilling 超过 3 层
  - 模块内部私有代码（hooks/services/stores）不得被其他模块 import
- **数据管道**: Acquisition → Ingestion → Processing → Analysis 阶段顺序执行

**理由**: 分层架构保证变更影响范围可控，每层可独立测试和替换。违反分层将导致逻辑泄漏和维护熵增。

### III. 类型安全与静态校验 (Type Safety & Static Validation)

所有代码 MUST 有完整的类型注解，编译/校验阶段发现类型错误。

**规则**:
- **前端**: TypeScript strict mode MUST 开启（`strictNullChecks`、`noUnusedLocals`、`noUnusedParameters`、`erasableSyntaxOnly`）
  - 对象类型使用 `interface`，联合类型和工具类型使用 `type`
  - 所有函数参数和返回值 MUST 有类型注解
  - 禁止使用 `any`，优先使用 `unknown` 或具体类型
- **后端**: 所有 API 请求/响应 MUST 使用 Pydantic v2 模型校验
  - 方法签名 MUST 包含返回值和参数类型注解
  - `Optional[X]` 表示可为 `None` 的类型
- **响应格式**: 所有 API 响应 MUST 封装在 `ApiResponse` 统一格式（success/data/message/error_code）

**理由**: 类型安全消除一整类运行时错误，静态校验提供即时反馈循环。Strict mode 是安全网而非可选项。

### IV. 配置即契约 (Configuration as Contract)

所有配置路径、环境依赖 MUST 集中管理，禁止硬编码。

**规则**:
- 数据管道配置 MUST 从 `DataPipeline/config.Config` 类读取
- 数据库路径 MUST NOT 在业务代码中硬编码（禁止 `*.db` 路径字符串）
- 表名字面量 MUST NOT 出现在业务代码中
- 部署模式 MUST 通过环境变量门控: `EMSXVIEW_MERGE_MODULES`、`EMSXVIEW_HANDOFF_BACKEND`、`ENABLE_DB_PERSISTENCE`
- 功能开关 MUST 在 Config 类中统一声明（如 `BDIB_PARQUET_ENABLED`、`BDIB_QUERY_ENGINE`）
- 新增配置项 MUST 遵循 Config 声明模式，不可散落各处

**理由**: 集中配置防止"多源真实"问题，环境变量门控使部署模式可切换，功能开关支持渐进式灰度。
相关 ADR: [ADR-0012](../docs/spec/adr/0012-config-isolation-rule.md)

### V. 实时数据统一管理 (Unified Realtime Management)

WebSocket 连接 MUST 由 Shell 统一管理，业务模块不得自行创建 WebSocket 连接。

**规则**:
- Shell 通过单一 `RealtimeClient` 统一管理 WS 连接生命周期和重连策略
- 模块 MUST 通过 `module.registry.ts` 声明 `realtimeWsPath`
- 业务模块 MUST NOT 在内部使用 `new WebSocket(...)` 自行连接
- 实时数据状态 MUST 使用 Zustand store 管理（`order-stream-store`、`route-stream-store`）
- Zustand store MUST NOT 被非所属模块直接访问

**理由**: 单一 WS 连接管理确保重连策略一致、资源可控。跨模块 store 访问破坏模块独立性。
相关 ADR: [ADR-0007](../docs/spec/adr/0007-handoff-exchange-pattern.md)、[ADR-0008](../docs/spec/adr/0008-frontend-module-registry-pattern.md)

## 技术栈约束 (Technology Stack Constraints)

项目采用双语言（TypeScript + Python）架构，技术选型 MUST 统一以降低维护成本。

**前端（TypeScript）**:
- React 19 + Vite + Tailwind CSS + shadcn/ui (Radix UI)
- Zustand 用于实时数据流，React Context 用于全局应用状态
- Zod + React Hook Form 用于表单校验
- Vitest + Testing Library 用于测试

**后端（Python）**:
- FastAPI + Pydantic v2 + SQLAlchemy 2.0
- Uvicorn ASGI 服务器
- Bloomberg EMSX API 集成（blpapi 3.23）仅限 Core Service (:3000)

**数据管道（Python）**:
- SQLite（主存储）+ DuckDB + PyArrow/Parquet（高频 K 线数据）
- PostgreSQL（业务持久化）
- Redis（跨模块通信，微服务模式）

**新技术引入规则**:
- 新第三方库 MUST 通过团队评审，避免功能重复的依赖
- 图标统一使用 lucide-react，不再引入其他图标库
- UI 组件统一使用 shadcn/ui，通过 `npx shadcn@latest add <component>` 添加

## 开发工作流 (Development Workflow)

### 编码规范

- 优先使用 `const`，避免 `let`，禁止 `var`（TypeScript）
- 使用箭头函数（除非需要 `this` 绑定）
- 优先使用函数式编程范式（`map`/`filter`/`reduce`）
- 每个函数不超过 30 行，使用 early return 减少嵌套
- 所有注释使用中文
- 使用路径别名导入（`@/*`, `@shared/*`, `@execution/*` 等），禁止深层相对路径

### 测试规范

- 边界测试 MUST 覆盖模块间契约（`tests/boundaries/`）
- 前端测试: Vitest → `npx vitest run` 或按文件/名称匹配运行
- 后端测试: Pytest → `pytest -v` 或按名称/文件匹配运行
- 重构涉及数据库的变更前 MUST 查阅 `AGENTS.md`（含 .BAK 安全确认流程）

### 代码审查

- 所有跨模块 import MUST 通过模块边界契约检查
- 不得引入跨模块的私有 hooks/services/stores 依赖
- DB 路径硬编码检查、适配器下划线访问检查 MUST 通过

### 构建与部署

- 生产部署使用 Docker Compose，Nginx 反向代理 `/api/*` → :3000
- 微服务模式（`EMSXVIEW_MERGE_MODULES=false`，默认）: Core :3000、MarketView :8001、CostView :8002
- 单进程模式（`EMSXVIEW_MERGE_MODULES=true`）: 开发/演示用，所有模块在一个进程
- 前端独立模块构建: `npm run build:execution`、`build:costview`、`build:marketview`、`build:databaseview`

## Governance

本宪法是项目架构和编码实践的最高准则，所有代码变更 MUST 遵守上述原则。

**修订流程**:
1. 任何宪法修订 MUST 以 ADR（Architecture Decision Record）形式记录在 `docs/spec/adr/`
2. 修订 MUST 在团队内达成共识后才能生效
3. 修订后 MUST 更新版本号和 Last Amended 日期
4. MAJOR 变更 MUST 附带迁移计划和影响评估

**版本策略**:
- MAJOR: 向后不兼容的原则删除或重新定义
- MINOR: 新增原则/章节或实质性扩展现有指导
- PATCH: 措辞澄清、拼写修正、非语义改进

**合规审查**:
- 每次 PR MUST 通过模块边界检测脚本（`scripts/audit_cross_imports.py`）
- 数据库路径硬编码检测（`scripts/audit_db_paths.py`）
- 适配器访问检测（`scripts/audit_underscore_access.py`）
- 文档漂移检测（`scripts/audit_doc_drift.py`）
- CODEBUDDY.md 和 `.codebuddy/rules/` 中的项目规则与本宪法 MUST 保持一致

**运行时开发指导**: 参考 `CODEBUDDY.md` 获取构建/运行命令、目录结构和最新重构上下文（当前分支: `data_management_refactoring`）。

**Version**: 1.0.0 | **Ratified**: 2026-06-08 | **Last Amended**: 2026-06-08
