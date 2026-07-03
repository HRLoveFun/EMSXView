# EMSXView 开发指南

> Last updated: 2026-07-02 | Version: 2.2
> 与 `CODEBUDDY.md` 的 Build & Run Commands 章节对齐

## 1. 快速启动

推荐入口：

- 双击 `relaunch_service.bat`（仓库根目录，一键重启 Windows 服务）
- 或使用 `scripts/` 下的 `start-all.bat` / `restart-all.bat` / `check-status.bat`

按模块单独启动：

```powershell
# 后端（Core, :3000）
Set-Location backend/api
python main.py
# 或：uvicorn main:app --port 3000

# 单进程模式（dev/demo，含 MarketView + CostView 路由）
$env:EMSXVIEW_MERGE_MODULES = "true"
python main.py

# 前端
Set-Location frontend
npm run dev
```

常用检查：

- 健康检查：http://localhost:3000/api/health
- 市场快照基线：http://localhost:3000/api/marketview/snapshot?limit=3
- 前端开发服务：http://localhost:5173
- 完整启动/模块清单见 [CODEBUDDY.md Build & Run Commands](../CODEBUDDY.md#build--run-commands)

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

- 更新 `docs/index.md` 中的文档分层或入口说明
- 如改变架构表述，同时检查 `docs/spec/project-structure.md`、`docs/spec/data-domain.md`、`docs/spec/memory.md`
- 如改变数据/存储/管道相关语义，同步检查 [data_management_refactoring_control.md §二 可调参数](../data_management_refactoring_control.md#二可调参数)
- 如改变跨域类型契约，同步检查 `docs/schema-contract.md`

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

1. 在 `platform_data/adapters/` 子包下增加或扩展适配器（见 [ADR-0013](../spec/adr/0013-platform-data-adapter-current-state.md)）
2. 修改调用方路由或服务
3. 补对应测试
4. 同步前端类型或展示

### 调试 Bloomberg 运行时问题

优先查看：

- `logs/emsx_api.log` 及其轮转文件
- `.github/knowledge/error-patterns.md`
- [data_management_refactoring_control.md §二 可调参数](../data_management_refactoring_control.md#二可调参数)（当前运行时开关）

## 5. 当前文档地图

优先阅读顺序：

1. `docs/index.md`：文档入口与分类
2. `docs/spec/project-structure.md`：当前仓库结构与权威实现面
3. `docs/spec/data-domain.md`：逻辑数据域边界
4. `docs/spec/memory.md`：稳定架构记忆与工作约束
5. `CODEBUDDY.md` Build & Run Commands 章节：启动/运行/部署命令（与本文档 §1 等价）

知识库位置：

- 架构决策：`.github/knowledge/architecture-decisions.md`
- 错误模式：`.github/knowledge/error-patterns.md`

> 历史上曾存在 `.github/knowledge/user-needs.md` 与 `iteration-log.md`，已下线；新的跨阶段/跨需求总结请按 [docs/index.md §5 Archive Policy](index.md#5-archive-policy) 直接放入 `docs/archive/YYYY-MM-DD/`。

## 6. 工作约束

- 不要把 CostView/frontend 当成正式前端入口。
- 不要再用 app/ 或 emsx-backend/ 作为当前结构描述。
- 新的专题总结类文档如果只对应一次性问题或已完成阶段，应放入 docs/archive/ 而不是长期留在 docs 根目录。
- 长期有效的文档才留在 docs 根目录：运行指南、架构说明、数据边界、当前 handoff、持续维护的计划文档。
