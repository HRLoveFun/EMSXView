# EMSXView 开发指南

> Last updated: 2026-03-17 | Version: 1.2

## Table of Contents

- [Quick Start](#quick-start)
- [Project Context](#project-context)
- [Verification Checklist](#verification-checklist)
- [Common Tasks](#common-tasks)
- [Error Handling](#error-handling)
- [Session Handoff](#session-handoff)
- [Documentation](#documentation)

---

## Quick Start

### 运行开发服务器

**前置要求**:

```Windows powershell
# 后端 (端口 3000)
.\scripts\deploy\start-backend.ps1

# 或跨平台命令:
cd Execution/backend/api && python -m uvicorn main:app --port 3000

# 前端 (端口 5173)
cd Execution/frontend && npm run dev
```

### 构建与检查

| 命令 | 说明 |
|------|------|
| `npm run build` | 前端构建 |
| `npm run lint` | 前端代码检查 |
| `python -m py_compile Execution/backend/api/main.py` | Python 语法检查 |

---

## Project Context

| 项目 | 技术栈 |
|------|--------|
| 后端 | Python (FastAPI) + blpapi |
| 前端 | React + TypeScript (Vite) + shadcn/ui |
| 数据源 | EMSX API (Bloomberg EMSX API) |
| 端口配置 | 后端: `3000` / 前端: `5173` |

**API 函数**: https://github.com/HRLoveFun/Bloomberg-EMSX-API-Code-Examples — 所有 EMSX API 调用的唯一权威来源

**目标**: 生产级订单执行自动化 (Level 1) → 量化交易 (Level 2)

---

## Verification Checklist

> 完成任务后请手动勾选 ✓

- [ ] 代码遵循 GUIDE 中的 EMSX API 调用规范
- [ ] 前端变更: `npm run lint` 通过
- [ ] 后端变更: `python -m py_compile` 通过
- [ ] API 测试: `http://localhost:3000/api/` 正常响应
- [ ] 新代码包含基本错误处理 (try/except, catch)
- [ ] 前端: 浏览器控制台无报错
- [ ] 后端: 终端日志无异常

---

## Common Tasks

### 添加 EMSX API 字段

1. 在 GUIDE 中查找精确字段名
2. 在 `Execution/backend/api/main.py` 的 `SUBSCRIPTION_FIELDS` 列表中添加
3. 在 `Execution/frontend/src/types/index.ts` 的 `OrderField` 类型中添加
4. 如需显示，更新对应 UI 组件
5. 测试: 访问 `/api/orders` 验证字段存在

### 修改订单表格 UI

1. 编辑 `Execution/frontend/src/sections/OrderTable.tsx`
2. 运行 `npm run lint` 检查类型错误
3. 访问 `http://localhost:5173` 验证

### 调试 Bloomberg 连接

> 根据 `.env` 文件中的实际配置替换 host 和端口，默认端口为 8194

1. 检查日志: `Execution/backend/logs/emsx_api.log` (首次运行后端时自动创建目录)
2. 确认 `.env` 中 `BLOOMBERG_HOST` 和 `BLOOMBERG_PORT` 配置正确
3. 测试连通性:
   ```powershell
   # 测试端口连通性 (替换为 .env 中的实际端口)
   telnet localhost 8194
   
   # 若 telnet 不可用（如 Windows 默认未安装），使用Python命令
   python -c "import socket; s=socket.socket(); s.connect(('localhost', 8194)); print('Connected')"
   ```
4. 健康检查: 访问 `http://localhost:3000/api/health`

---

## Error Handling

遇到错误时，按以下顺序查找解决方案:

1. **`docs/ERROR_PATTERNS.md`** — 使用错误关键词搜索
2. **`HANDOFF.md`** — 检查 "Open Blockers" 章节
3. **`MEMORY.md`** — 了解相关设计决策

### 记录新错误模式

如果解决了满足以下条件的问题:
- 同一错误出现 ≥2 次
- 解决耗时 >30 分钟
- 涉及外部依赖 (EMSX API、网络、配置)
- 解决方案非直觉性

请按 `docs/ERROR_PATTERNS.md` 中的模板格式添加条目（模板包含: 错误现象、原因分析、解决方案、预防措施、相关代码）。

---

## Session Handoff

> 文档位置: 根目录 (`HANDOFF.md`、`MEMORY.md`) 或 `docs/` 目录

| 文档 | 用途 |
|------|------|
| `HANDOFF.md` | 当前待办事项、阻碍、下一步 |
| `MEMORY.md` | 架构决策、技术选型记录 |
| `docs/ERROR_PATTERNS.md` | 常见错误与解决方案 |
| `docs/SESSION_DIGEST.md` | 每周会话总结与趋势 |
| `docs/KNOWLEDGE_WORKFLOW.md` | 完整知识管理流程 |

---

## Documentation

### 知识体系层级 (信息流向)

> 原始会话记录 (HANDOFF.md) → 每周提炼 (SESSION_DIGEST.md) → 结构化知识 (ERROR_PATTERNS.md / MEMORY.md)

```
HANDOFF.md (当前会话)
        ↓
docs/SESSION_DIGEST.md (每周整理)
        ↓
docs/ERROR_PATTERNS.md + MEMORY.md (结构化知识)
```

### 何时查阅

| 场景 | 查阅文档 |
|------|----------|
| 遇到具体报错 | `docs/ERROR_PATTERNS.md` |
| 了解架构决策 | `MEMORY.md` |
| 了解本周工作 | `docs/SESSION_DIGEST.md` |
| 查看当前阻碍 | `HANDOFF.md` |
| 学习完整知识管理流程 | `docs/KNOWLEDGE_WORKFLOW.md` |

---

## 自动化 (内部使用)

> 以下功能由 workbuddy 驱动，仅供内部开发团队使用。workbuddy 配置见 `.workbuddy/` 目录。

### 定时任务

| 时间 | 任务 | 说明 |
|------|------|------|
| 每日 18:00 | session-capture-daily | 生成当天会话摘要 |
| 每日 19:00 | handoff-merge-daily | 合并到 HANDOFF.md |
| 每周一 09:00 | session-digest-weekly | 生成周报 (cron 触发) |
| 每月 1 日 10:00 | knowledge-review-monthly | 月度审核 (cron 触发) |

### 启用/暂停

编辑 `.workbuddy/automations/*/automation.toml` 中的 `status` 字段:
- `status = "ACTIVE"` 启用
- `status = "PAUSED"` 暂停

### 日志目录

首次运行后端时自动创建: `Execution/backend/logs/`
