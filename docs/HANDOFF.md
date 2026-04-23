# Session Handoff Log

> 当前工作面 handoff。只保留仍影响后续开发与排障的状态，不再堆积历史会话流水。

---

## Current Session (2026-04-22)

### Status

- 已完成文档主干收口：docs 根目录只保留当前有效的运行、架构、数据域和 handoff 文档。
- 已完成平台结构对齐：单前端壳、三业务模块、一个逻辑数据域入口。
- 已完成运行面告警治理：SENT 状态解析、FX duplicate correlation id、可选数据库 bootstrap 告警、FX 缩放报价噪音。
- MarketView 当前只保留日级市场快照基线，后续扩展已暂停。

### Current Runtime State

- 前端正式入口：Execution/frontend/src/App.tsx
- 后端正式入口：Execution/backend/api/main.py
- CostView 分析与管线：CostView/src/
- 逻辑数据域入口：platform_data/
- /api/health 当前会在 ENABLE_DB_PERSISTENCE=false 时返回 database.status=disabled

### Open Blockers

| Priority | Issue | Context | Next Step |
|---|---|---|---|
| 🟡 Medium | 无效证券订阅仍存在 | TVSLIN/P Pfd 仍会触发 market data subscription failure WARNING | 清点订阅源并在生成或订阅前剔除无效证券 |
| 🟡 Medium | 仍有少量跨域直接导入 | 共享数据入口已建立，但调用方迁移未完成 | 继续把跨域访问逐步迁到 platform_data/ |
| 🟢 Low | 本地 PostgreSQL 持久化未启用 | 当前 Windows 本地运行模式下 DB persistence 是可选能力 | 仅在需要 warm-start / projection persistence 时再配置 DATABASE_URL 与 ENABLE_DB_PERSISTENCE |

### Next Tasks

1. 处理 TVSLIN/P Pfd 无效订阅源。
2. 继续减少跨域深层导入，优先迁到 platform_data/。
3. 继续清理遗留原型与剩余过时文档。
4. 评估 INIT_PAINT 类 WARNING 是否应降级或收敛。

### Recently Completed

- 重写 docs/PROJECT_STRUCTURE.md 以匹配当前仓库结构。
- 新增 docs/DATA_DOMAIN.md，明确逻辑数据域与适配层边界。
- 归档 CostView 旧前端原型源码并明确降级状态。
- 新增 /api/marketview/snapshot 与 MarketView 壳内真实快照展示。
- 修复 SENT 枚举缺项与 FX duplicate correlation id。
- 调整数据库可选启动语义与 FX 缩放报价告警级别。

### Quick Checks

- 健康检查：GET http://localhost:3000/api/health
- 市场快照：GET http://localhost:3000/api/marketview/snapshot?limit=3
- 后端日志：logs/emsx_api.log
- 聚焦后端测试目录：Execution/backend/api/tests/
