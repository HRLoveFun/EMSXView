# EMSXView — AI 编码代理指南

> **同步机制**：`AGENTS.md` 为规范源；`CODEBUDDY.md` 由 git pre-commit hook（`.githooks/pre-commit`）在提交时自动同步——编辑本文件后**无需**手动同步 `CODEBUDDY.md`。

## 文档阅读顺序（必读）

进入本仓库的 AI 代理 **必须** 按以下顺序阅读文档，再开始任何代码改动：

1. `CODEBUDDY.md` / `AGENTS.md`（本文件）— 工作流与安全规则
2. `.codebuddy/rules/project-context.md` — 技术栈与模块清单
3. `.codebuddy/rules/coding-style.md` — 命名/目录/状态管理
4. `.codebuddy/rules/module-boundary.md` — ★ 模块边界契约
5. `docs/spec/project-structure.md` — 当前仓库结构
6. `docs/spec/data-domain.md` — 数据域所有权
7. `docs/spec/memory.md` — 架构记忆入口（指向 ADR 列表）
8. `docs/spec/module-onboarding.md` — 新增模块流程
9. `docs/spec/anti-patterns.md` — ★ 禁止模式
10. `docs/spec/plan-design-principles.md` — ★ 计划设计原则
11. `docs/spec/refactoring-methodology.md` — ★ 系统性安全重构框架
12. `docs/spec/git-workflow.md` — Git 多任务并行工作流（多任务 / 多 Agent 并行前必读）

## 回复语言约定

所有 AI 编码代理在与用户对话时，**必须使用中文回复**（代码、标识符、技术术语除外）。

## 关键约定

### TypeScript / React 编码规范

- 优先使用 `const`，避免 `let`，禁止 `var`
- 使用箭头函数，除非需要 `this` 绑定
- 优先使用函数式编程范式（map/filter/reduce）
- 每个函数不超过 30 行，使用 early return 减少嵌套
- **所有注释使用中文**
- 使用 `interface` 定义对象类型，使用 `type` 定义联合类型和工具类型
- 为所有函数参数和返回值添加类型注解
- 前端使用 **shadcn/ui** 组件（Radix UI + Tailwind CSS）。新增 UI 组件遵循同一模式——使用 `npx shadcn@latest add <component>` 添加。

### 前端状态管理

- 全局应用状态使用 React Context（通过 `useShellContext()` 访问 ShellContext）
- 实时数据流（订单/路由）使用 Zustand store（`order-stream-store`、`route-stream-store`）
- 跨模块通信：`ModuleRegistry` 注册 + `useHandoffContracts()` hook + `handoff-api.ts` 服务

### Broker ↔ Exchange 映射清单（★ 维护点）

- **唯一数据源**：`frontend/src/shared/lib/broker-exchange-mapping.ts`（导出 `EXCHANGE_FOR_BROKER` / `getBrokerExchangeMapping()` / `EXCHANGE_LIST`）
- **维护方式**：增删交易所或 broker 时**只改 shared 文件**；`frontend/src/modules/execution/data/broker-exchange-mapping.ts` 仅为 re-export 兼容层
- **Report 专有市场**：仅需出现在 Report Exchanges、但不进入授权表的交易所（如 `C1` 沪港通、`HK` 香港），加入 `REPORT_ONLY_EXCHANGES` 常量（挂 `EXCHANGE_LIST`，不挂 `EXCHANGE_FOR_BROKER`）
- **禁止**：在 `modules/execution/data/broker-exchange-mapping.ts` 内直接编辑映射（改此处不生效且会造成漂移）

### 后端约定

- 后端使用 Pydantic v2 模型定义 schema；所有 API 响应包在 `ApiResponse` 中。
- 数据库读写由 `RepositoryProvider` 统一控制，gate 为 `ENABLE_DB_PERSISTENCE` 标志。
- 管道配置为唯一数据源——禁止硬编码数据库路径、表名及运行时参数；一律从 `DataPipeline/config.Config` 导入。
- 后端可选路由器绝不可破坏核心 ExecutionView——使用 `main.py` 中的 `_register_optional` 模式。
- TCA 路由层级指标从 `tca_route_summary` 预计算表读取，禁止在查询时实时聚合。
- Backend 禁止直接 deep import `CostView.src.*` / `DataPipeline.*`；须经由 `platform_data` 桥接入口（如 `register_costview_bridge_dependencies()`）完成 DI 注册（模块边界 AP-01）。
- `platform_data` 中 `CostViewAnalyticsAdapter`、`CostViewDatabaseAdapter`、`ExecutionHistoryAdapter`、`DataPlatformIngestionAdapter`、`build_platform_data_access()` / `PlatformDataAccess` 为**规划中、尚未实现**——禁止按符号 import 使用（见 `docs/spec/adr/0013-platform-data-adapter-current-state.md`）。

### 文件放置规范（★ 必须遵守）

- **禁止在仓库根目录随意创建文件**。创建任何新文件前，必须先确定其按功能归属的既有目录。
- 根目录仅保留既有约定文件：`AGENTS.md`、`CODEBUDDY.md`、`README.md`、`QUICKSTART.md`、`.emsxview-root`、`.gitignore` 及既有模块目录/配置。
- 功能 → 目录映射：

  | 文件类别 | 归属目录 |
  |---|---|
  | 后端业务代码 | `backend/api/` 分层子目录（`routers/` `services/` `schemas/`） |
  | CostView / MarketView | `CostView/api/`、`CostView/src/`、`CostView/tests/`；`MarketView/` |
  | 数据管道 | `DataPipeline/`（`ingestion/` `processing/` `analysis/`） |
  | 跨模块适配器 | `platform_data/adapters/`、`platform_data/contracts/` |
  | 前端共享代码 | `frontend/src/shared/`（`hooks/` `lib/` `services/` `types/`） |
  | 前端模块代码 | `frontend/src/modules/<module>/`（`components/` `hooks/` `services/`） |
  | 前端共享 UI | `frontend/src/components/`、`frontend/src/components/ui/` |
  | 测试 | 各模块自身 `tests/`（Python）或 `__tests__/`（前端） |
  | 运维/诊断脚本 | `scripts/`（部署启动器归 `scripts/deploy/`） |
  | 规范文档 / 其他文档 | `docs/spec/` / `docs/` |
  | 特性计划与清单 | `specs/<feature-id>/` |
  | 临时调试代码 | 仓库根 `_tmp/`（`.gitignore` 已忽略） |
  | 运行产物（日志、导出、生成图片） | `.gitignore` 覆盖的目录或系统临时目录 |

- **判定原则**：优先复用相邻同类既有路径；无明确归属时先查阅 `docs/spec/project-structure.md` 或征询用户，**不得默认落到根目录**；临时与交付物严格分离，任务结束由创建方清理 `_tmp/`。
- 完整细则见 [`.codebuddy/rules/coding-style.md` → 文件放置规范](.codebuddy/rules/coding-style.md)。

### 启动器与项目根路径（★ 必须遵守）

- 项目根定位**唯一信息源**是仓库根的 `.emsxview-root` marker 文件；新增/修改 `scripts/deploy/` 下启动脚本时**必须**用 `Find-EmsxviewRoot`（向上查找 marker），**禁止**硬编码"向上 N 层"
- 启动器算出项目根后**必须** `Assert-ProjectRootValid` 自检，错路径立即 throw，**禁止**进入 120s 超时黑盒
- VBS 启动器只做 thin wrapper（隐藏窗口 + 调起 PS1），**禁止**在 VBS 内做路径深度计算或业务逻辑
- 详见 [AP-16 启动器路径硬编码 + 跨宿主语义错位](docs/spec/anti-patterns.md#ap-16-启动器路径硬编码--跨宿主语义错位)

### Git 多任务并行工作流（★ [ADR-0700](docs/spec/adr/0700-git-worktree-parallel-workflow.md)）

- **核心方案**：Git Worktree + 独立 Feature 分支 + 每日 rebase origin/main；完整 SOP 见 [`docs/spec/git-workflow.md`](docs/spec/git-workflow.md)
- **一任务一分支一目录**：每个任务在兄弟目录 `../EMSXView-wt-<task>` 检出独立分支，主工作树保持干净（停在 main）；规格化特性任务分支名必须与 `specs/<feature-id>/` 目录名一致
- **同步纪律**：每个活跃任务每天至少一次 `git rebase origin/main`；临时保存用 commit，**禁止跨 worktree 使用 stash**（stash 为仓库级共享，极易拿错）
- **数据零受损**：worktree 内 `CostView/data/` 默认为空（数据不入 git）；数据管道写入类任务同一时间只允许一个 worktree 执行，或各用独立 `EMSXVIEW_DATA_DIR`
- **Agent 隔离**：一个 Agent 绑定一个 worktree，禁止跨 worktree 读写文件或操作其他任务正在使用的分支；功能代码禁止直接提交 main（PR + Squash merge）
- 并行任务启动前必须先读 `docs/spec/git-workflow.md` §6（端口偏移 / 数据目录 / 依赖安装）与 §7（AI Agent 专项规则）
