# EMSXView 开发指南

> Last updated: 2026-05-06 | Version: 2.1

## 1. 快速启动

推荐入口：

- 双击 重启服务.bat（一键重启）
- 或使用 scripts 下的 start-all.bat / restart-all.bat / check-status.bat

按模块单独启动：

```powershell
# 后端
Set-Location backend/api
python start_server.py

# 前端
Set-Location frontend
npm run dev
```

常用检查：

- 健康检查：http://localhost:3000/api/health
- 市场快照基线：http://localhost:3000/api/marketview/snapshot?limit=3
- 前端开发服务：http://localhost:5173

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

- 更新 docs/index.md 中的文档分层或入口说明
- 如改变架构表述，同时检查 docs/spec/project-structure.md、docs/spec/data-domain.md、docs/spec/memory.md
- 如改变当前运行状态或阻塞面，同时检查 docs/handoff.md

## 4. 常见任务入口

### 添加或调整后端能力

优先检查这些位置：

- 路由：backend/api/routers/
- 服务：backend/api/services/
- 数据契约：backend/api/schemas.py
- 共享适配：platform_data/

### 调整跨域数据访问

优先走 platform_data/，不要默认新增深层直接导入。

典型顺序：

1. 在 platform_data/adapters.py 增加或扩展适配器
2. 修改调用方路由或服务
3. 补对应测试
4. 同步前端类型或展示

### 调试 Bloomberg 运行时问题

优先查看：

- logs/emsx_api.log 及其轮转文件
- .github/knowledge/error-patterns.md
- docs/handoff.md 中的当前运行状态

## 5. 当前文档地图

优先阅读顺序：

1. docs/index.md：文档入口与分类
2. docs/spec/project-structure.md：当前仓库结构与权威实现面
3. docs/spec/data-domain.md：逻辑数据域边界
4. docs/spec/memory.md：稳定架构记忆与工作约束
5. docs/handoff.md：当前阻塞、运行状态、下一步

知识库位置：

- 架构决策：.github/knowledge/architecture-decisions.md
- 错误模式：.github/knowledge/error-patterns.md
- 用户需求：.github/knowledge/user-needs.md
- 迭代日志：.github/knowledge/iteration-log.md

## 6. 工作约束

- 不要把 CostView/frontend 当成正式前端入口。
- 不要再用 app/ 或 emsx-backend/ 作为当前结构描述。
- 新的专题总结类文档如果只对应一次性问题或已完成阶段，应放入 docs/archive/ 而不是长期留在 docs 根目录。
- 长期有效的文档才留在 docs 根目录：运行指南、架构说明、数据边界、当前 handoff、持续维护的计划文档。
