# AGENTS.md

This file provides guidance to coding agents (Claude Code, Copilot, Cursor, etc.) when working in this repository.

## 文档阅读顺序（必读）

进入本仓库的 AI agent **必须**按以下顺序阅读文档，再开始任何代码改动：

1. `AGENTS.md`（本文件）— 工作流与安全规则
2. `.codebuddy/rules/project-context.md` — 技术栈与模块清单
3. `.codebuddy/rules/coding-style.md` — 命名/目录/状态管理
4. `.codebuddy/rules/module-boundary.md` — ★ 模块边界契约
5. `docs/spec/project-structure.md` — 当前仓库结构
6. `docs/spec/data-domain.md` — 数据域所有权
7. `docs/spec/memory.md` — 架构记忆入口（指向 ADR 列表）
8. `docs/spec/module-onboarding.md` — 新增模块流程
9. `docs/spec/anti-patterns.md` — ★ 禁止模式

涉及数据/存储/管道改动时**额外**阅读：
- `data_management_refactoring_control.md` — 重构进度
- `data_management_refactoring_plan.md` — 重构实施

## Project Overview

EMSXView is a Bloomberg EMSX-integrated trading platform covering pre-trade analysis, order execution, and post-trade TCA analytics. It is a monorepo with a single React frontend shell (TypeScript + Vite + shadcn/ui), a Python FastAPI backend, and a multi-stage data pipeline. The backend can run in microservice mode (Core :3000, MarketView :8001, CostView :8002) or single-process merge mode (`EMSXVIEW_MERGE_MODULES=true`).

## Key Conventions (Must Follow)

### General
- **所有注释使用中文**
- 优先使用 `const`，避免 `let`，禁止 `var`
- 每个函数不超过 30 行，使用 early return 减少嵌套

### TypeScript / React
- 使用 `interface` 定义对象类型，使用 `type` 定义联合类型和工具类型
- 为所有函数参数和返回值添加类型注解
- TypeScript strict mode 已开启 (`noUnusedLocals`, `noUnusedParameters`, `erasableSyntaxOnly`)
- UI 组件使用 shadcn/ui（Radix UI + Tailwind CSS），新增组件用 `npx shadcn@latest add <component>`
- 路径别名: `@/` → `src/`, `@shared/` → `src/shared/`, `@execution/` → `src/modules/execution/` 等

### Python / FastAPI
- 所有 API 响应必须用 Pydantic v2 模型封装在 `ApiResponse` 中
- 数据库读写由 `RepositoryProvider` 统一控制，gate 为 `ENABLE_DB_PERSISTENCE` 标志
- 可选路由器使用 `_register_optional` 模式，不得影响核心 ExecutionView
- 流水线配置从 `DataPipeline/config.py` 导入，禁止硬编码 DB 路径或表名

## data_management_refactoring 分支工作流

> **仅在 `data_management_refactoring` 分支生效。**

当用户要求执行重构步骤时：
1. 必须先读 `data_management_refactoring_control.md` 了解当前进度
2. 必须读 `data_management_refactoring_plan.md` 中对应节的实施方案
3. 包含 `.BAK` 操作的步骤（A7/A8/B4）必须先陈述计划，等待用户确认
4. 每步完成后必须更新 `control.md` 中对应任务的状态
