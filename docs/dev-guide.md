# EMSXView 开发指南

> L1 | 权威：启动与验证流程、常见任务入口、启动器与项目根路径规则 | 不权威：命令完整清单（见 `README.md` §9）、编码与文件放置约定（见 `.codebuddy/rules/coding-style.md`）、项目现状（见 `specs/057-execution-decision-loop/tasks.md`）

> Last updated: 2026-10-29 | Version: 2.3
> 与 [`README.md` §9 Installation & Running](../README.md#9-installation--running) 对齐

## 1. 快速启动

推荐入口：

- 双击 `relaunch_service.bat`（仓库根目录，一键重启 Windows 服务）
- 或使用根目录 `emsxview.bat [start|stop|restart|status]`（默认 `status`）

按模块单独启动：

```powershell
# 后端（Core, :3000）
Set-Location backend/api
python main.py
# 或：uvicorn main:app --port 3000

# 可选：将 CostView 的 /api/tca/* 路由桥接进 core 进程（默认即启用）
$env:EMSXVIEW_OPTIONAL_MODULES = "costview:CostView"
python main.py

# 前端
Set-Location frontend
npm run dev
```

常用检查：

- 健康检查：`<API_BASE_URL>/api/health`（默认 `http://localhost:3000/api/health`）
- 市场快照基线：`<API_BASE_URL>/api/marketview/snapshot?limit=3`
- 前端开发服务：`http://<host>:<FRONTEND_PORT>`（默认 `http://localhost:5173`）
- 完整启动/模块清单见 [README.md §9 Installation & Running](../README.md#9-installation--running)
- 占位符含义见 [docs/index.md §5](index.md#5-占位符与可配置参数约定)

## 2. 当前工程事实

当前仓库不是"三套独立应用"，而是：

- 一个正式前端壳：frontend/src/App.tsx
- 三个业务模块：MarketView、ExecutionView、CostView
- 一个逻辑数据域入口：platform_data/

当前权威实现面：

- 前端壳：frontend/
- 后端装配层：backend/api/
- CostView 分析与管线：CostView/src/
- 共享数据适配层：platform_data/

重要运行语义：

- Python 后端改动后必须重启后端。
- ENABLE_DB_PERSISTENCE=false 时，数据库被视为可选能力；/api/health 会返回 database=disabled。
- Bloomberg 相关字段如果不在订阅列表中，就不会收到。
- Bloomberg 字段类型必须与解析器类型一致。

## 3. 验证清单

前端改动：

- 在 frontend 运行 npm run build

后端改动：

- 优先运行受影响切面的 pytest，而不是只做全量语法检查
- 如修改了运行时行为，重启后端并做一次接口 smoke test

文档改动：

- 先改 `AGENTS.md` 文档地图，再动文件，最后跑 `python scripts/doc_check.py`（退出码 0 才算完）
- 如改变架构表述，同时检查 `docs/spec/project-structure.md`、`docs/spec/data-domain.md`、`docs/spec/memory.md`
- 如改变数据/存储相关语义，同步检查 [`data_access/config.py`](../data_access/config.py) 的 `Config` 类（本仓库运行时参数唯一真相源；写入侧参数归独立仓库 EMSXDataPipeline）
- 如改变跨域类型契约，同步检查 `docs/schema-contract.md`

**本地 git 钩子状态**：仓库自带 `.githooks/`（提交锁校验 + 质量门禁增量快检），但需 `git config core.hooksPath .githooks` 才生效；**当前未启用**（2026-10-29 决定暂不启用）。在此之前，质量门禁与文档对账只在 CI 与手动执行中生效。

## 4. 常见任务入口

### 添加或调整后端能力

优先检查这些位置：

- 路由：backend/api/routers/
- 服务：backend/api/services/
- 数据契约：backend/api/schemas/（子包，按域拆分）
- 共享适配：platform_data/

### 调整跨域数据访问

优先走 `platform_data/`，不要默认新增深层直接导入。

典型顺序：

1. 在 `platform_data/adapters/` 子包下增加或扩展适配器（见 [ADR-0013](spec/adr/0013-platform-data-adapter-current-state.md)）
2. 修改调用方路由或服务
3. 补对应测试
4. 同步前端类型或展示

### 调试 Bloomberg 运行时问题

优先查看：

- `logs/emsx_api.log` 及其轮转文件
- `.github/knowledge/error-patterns.md`
- [`data_access/config.py`](../data_access/config.py) 的 `Config` 类（当前运行时开关）

## 5. 文档入口

「该读哪份文档」只有一处答案：[`AGENTS.md` 文档地图](../AGENTS.md)。本节不再维护第二份清单。

知识库位置：

- 架构决策：`docs/spec/adr/`（索引 `docs/spec/memory.md`）
- 错误模式：`.github/knowledge/error-patterns.md`

> 历史上曾存在 `.github/knowledge/architecture-decisions.md`、`user-needs.md`、`iteration-log.md`，均已下线（前两者在仓库中已不存在，勿再引用）；新的跨阶段总结按 [docs/index.md §3 归档策略](index.md#3-归档策略) 直接放入 `docs/archive/YYYY-MM-DD/`。

## 6. 工作约束

- 不要把 CostView/frontend 当成正式前端入口。
- 不要再用 app/ 或 emsx-backend/ 作为当前结构描述。
- 新的专题总结类文档如果只对应一次性问题或已完成阶段，应放入 docs/archive/ 而不是长期留在 docs 根目录。
- 长期有效的文档才留在 docs 根目录：运行指南、架构说明、数据边界、持续维护的计划文档。

## 7. 启动器与项目根路径（★ 必须遵守）

- 项目根定位**唯一信息源**是仓库根的 `.emsxview-root` marker 文件；新增/修改 `scripts/deploy/` 下启动脚本时**必须**用 `Find-EmsxviewRoot`（向上查找 marker），**禁止**硬编码「向上 N 层」。
- 启动器算出项目根后**必须** `Assert-ProjectRootValid` 自检，错路径立即 throw，**禁止**进入 120s 超时黑盒。
- VBS 启动器只做 thin wrapper（隐藏窗口 + 调起 PS1），**禁止**在 VBS 内做路径深度计算或业务逻辑。
- 详见 [AP-16 启动器路径硬编码 + 跨宿主语义错位](spec/anti-patterns.md#ap-16-启动器路径硬编码--跨宿主语义错位)。
