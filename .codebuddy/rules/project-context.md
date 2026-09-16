# 项目上下文

## 技术栈版本

### 前端（frontend/）
- **React** 19.2 — UI 框架
- **TypeScript** 5.9 — 类型系统（strict mode 开启）
- **Vite** 7.2 — 构建工具
- **Tailwind CSS** 3.4 — 样式框架
- **shadcn/ui** — UI 组件库（基于 Radix UI）
- **Zustand** — 实时数据流状态管理（订单/路由）
- **React Hook Form** 7.70 + **Zod** 4.3 — 表单与校验
- **Recharts** 2.15 — 图表
- **Vitest** 3.2 + **Testing Library** 16.3 — 测试
- **date-fns** 4.1 — 日期处理
- **lucide-react** — 图标

### 后端（backend/api/）
- **Python** 3.x
- **FastAPI** 0.109 — Web 框架
- **Uvicorn** 0.27 — ASGI 服务器
- **Pydantic** 2.5 — 数据校验与序列化
- **SQLAlchemy** 2.0 — ORM（PostgreSQL 持久化）
- **blpapi** 3.23 — Bloomberg API 集成
- **Pytest** 7.4 — 测试

### 数据访问（data_access/，只读消费者）
- **SQLite（mode=ro）** — 分析库主存储；数据根由 `Config.DATA_DIR` 决定（`${EMSXVIEW_DATA_DIR}` 环境变量覆盖）
- **DuckDB + PyArrow + Parquet** — 高频 K 线数据读取（写入与维护归独立仓库 EMSXDataPipeline）
- **PostgreSQL** — 后端持久化（Docker 环境）

### 基础设施
- **Docker Compose** — 生产环境容器编排
- **Nginx** — 前端反向代理（`/api/*` → :3000）
- **Redis** — 跨模块通信（微服务模式）
- **Prometheus + Grafana** — 可选监控

## 重要约定

### 状态管理
- **全局应用状态**：React Context（`ShellContext`，通过 `useShellContext()` 访问）
- **实时数据流**：Zustand store（`order-stream-store`、`route-stream-store`）
- **跨模块通信**：`ModuleRegistry` 注册 + `useHandoffContracts()` hook + `handoff-api.ts` 服务
- **模块动态发现**：每个模块导出 `module.registry.ts`，通过 `moduleRegistry.register()` 自注册，`AppShell` 通过 `moduleRegistry.getAll()` 动态渲染标签页

### 数据获取
- 前端通过 Vite 代理 `/api/*` 和 `/ws/*` 到后端 `http://localhost:3000`
- 各模块 API 客户端服务位于模块 `services/` 目录（如 `ExecutionView/module/services/execution-api.ts`、`modules/costview/services/*`）
- 开发模式支持 Mock 模式（`VITE_USE_MOCK=true`），不依赖后端运行

### 表单处理
- 使用 **React Hook Form** 管理表单状态
- 使用 **Zod** 定义校验 Schema
- 通过 `@hookform/resolvers` 集成两者

### UI 组件
- 统一使用 **shadcn/ui**（Radix UI + Tailwind CSS）
- 新增 shadcn 组件时使用 CLI：`npx shadcn@latest add <component>`
- 共享组件位于 `frontend/src/components/`
- 模块特定组件位于各自模块目录内

### 图标
- 统一使用 **lucide-react** 图标库
- 不再引入其他图标库

### 模块架构
- 前端壳 `frontend/src/app/AppShell.tsx` — 根布局编排器，包含工具栏、模块标签页和 Toast 容器
- 懒加载 React 模块：`frontend/src/modules/costview/`、`frontend/src/modules/marketview/`；**ExecutionView 已独立为仓库根级 `ExecutionView/module/`**（与 `frontend/` 平级）
- 包管理：npm workspaces（根 `package.json` 成员 `frontend` + `ExecutionView`），lockfile 唯一在仓库根，安装入口为仓库根 `npm ci`；依赖提升到根 `node_modules`，`resolve.dedupe` 保证单实例 React（ADR-0020）
- Vite 手工分块确保各模块独立打包（`module-costview`、`module-marketview`、`module-execution` 等）
- 构建产物：主应用 `frontend/dist/`；独立模块 `frontend/dist-modules/<module>/`（两者分离，互不覆盖）
- 后端分层：Core Router（始终加载） + Optional Router（合并模式加载） + 独立服务

## API 约定

### RESTful 风格
- 使用 FastAPI 构建 RESTful API
- 所有 API 响应封装在 `ApiResponse` 统一格式中
- 请求/响应模型使用 **Pydantic v2** 定义

### 统一响应格式
```json
{
  "success": true,
  "data": {},
  "message": "",
  "error_code": ""
}
```

### 核心 API 端点

| 端点 | 方法 | 说明 |
|------|:----:|------|
| `/api/orders` | GET/POST | 订单管理 |
| `/api/routes` | GET/POST | 路由管理 |
| `/api/broker/*` | GET | Bloomberg 经纪商 |
| `/api/realtime` | WS | 实时数据推送 |
| `/api/tca/analyze` | POST | TCA 交易成本分析 |
| `/api/tca/scorecard` | POST | 评分卡查询 |
| `/api/health` | GET | 健康检查 |
| `/api/connection` | GET | Bloomberg 连接状态 |

### 依赖注入
- 使用 FastAPI `Depends()` 进行依赖注入（参见 `deps.py`）
- `RepositoryProvider` 统一控制数据库读写，受 `ENABLE_DB_PERSISTENCE` 门控

### 错误处理
- 业务错误通过 `ApiResponse` 中的 `error_code` 和 `message` 返回
- HTTP 状态码遵循 REST 惯例（200 成功，4xx 客户端错误，5xx 服务端错误）
- 可选路由器不得影响核心 ExecutionView（使用 `_register_optional` 模式）

## 语言与回复规范

### Agent 对话语言
- **回复语言**：所有 Agent 回复使用**简体中文**
- **代码保持原样**：代码片段、文件名、变量名、函数名、类名、接口名保持英文原样，不做翻译
- **路径和命令保持原样**：文件路径、URL、终端命令、环境变量名保持原样
- **技术术语保留英文**：框架名、库名、协议名、设计模式名等技术专有名词保留英文（如 React、FastAPI、DuckDB、WebSocket、RESTful）
- **书面表达**：回复正文使用书面表达，避免口语化或网络用语
- **项目内术语一致**：遵循项目已有的术语翻译（如"order execution""post-trade TCA""route management"等）

### 文档编辑
- 编辑 `.md` 文档时保持原有格式风格（缩进、表格对齐、链接语法）
- 新增内容遵循文档已有层级结构
