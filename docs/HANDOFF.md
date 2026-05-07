# Session Handoff Log

> 当前工作面 handoff。只保留仍影响后续开发与排障的状态，不再堆积历史会话流水。

---

## Current Session (2026-05-06)

### Status

- 已完成文档路径统一：6 份 docs 文件中 `Execution/` 全部修正为 `ExecutionView/`。
- 已完成文档过时度审计：建立 5 维度评分体系，识别 3 份废弃文件、8 份过时文件。
- 已完成 P3-S6 全部 issue（benchmark engine + algo scheduler + frontend controls + tests）。
- 当前分支 `refactor/architecture` 上有 compliance violation、batch route order 等功能开发中。
- MarketView 当前只保留日级市场快照基线，后续扩展已暂停。

### Current Runtime State

- 前端正式入口：ExecutionView/frontend/src/App.tsx
- 后端正式入口：ExecutionView/backend/api/main.py
- CostView 分析与管线：CostView/src/
- 逻辑数据域入口：platform_data/
- /api/health 当前会在 ENABLE_DB_PERSISTENCE=false 时返回 database.status=disabled

### Open Blockers

| Priority | Issue | Context | Next Step |
|---|---|---|---|
| 🟡 Medium | 无效证券订阅仍存在 | TVSLIN/P Pfd 仍会触发 market data subscription failure WARNING | 清点订阅源并在生成或订阅前剔除无效证券 |
| 🟡 Medium | 仍有少量跨域直接导入 | 共享数据入口已建立，但调用方迁移未完成 | 继续把跨域访问逐步迁到 platform_data/ |
| 🟢 Low | 本地 PostgreSQL 持久化未启用 | 当前 Windows 本地运行模式下 DB persistence 是可选能力 | 仅在需要 warm-start / projection persistence 时再配置 DATABASE_URL 与 ENABLE_DB_PERSISTENCE |
| 🟢 Low | P3-S6 sprint 状态未关闭 | plans/execution-platform-status.yaml 中 P3-S6 所有 issue 已 completed 但 sprint 仍标 in_progress | 运行 sync_execution_status.py 更新 ledger 并推进到 P4 |

### Next Tasks

1. 处理 TVSLIN/P Pfd 无效订阅源。
2. 继续减少跨域深层导入，优先迁到 platform_data/。
3. 继续清理遗留原型与剩余过时文档（归档 target_state.md 和 generated/ 快照）。
4. 将 P3-S6 sprint 标记为 completed，推进 Phase 4 规划。
5. 在 refactor/architecture 分支上推进 compliance 和 batch-route 功能开发。

### Recently Completed

- 文档路径统一：CLAUDE.md、PROJECT_STRUCTURE.md、MEMORY.md、HANDOFF.md、DATA_DOMAIN.md、SERVICE_MANAGEMENT.md 中 `Execution/` → `ExecutionView/`。
- 文档过时度审计与 5 维度评分体系建立。
- P3-S6 全部 4 个 issue 完成（benchmark engine、algo scheduler、frontend controls、tests）。
- 归档 CostView 旧前端原型源码并明确降级状态。
- 新增 /api/marketview/snapshot 与 MarketView 壳内真实快照展示。
- 修复 SENT 枚举缺项与 FX duplicate correlation id。

### Quick Checks

- 健康检查：GET http://localhost:3000/api/health
- 市场快照：GET http://localhost:3000/api/marketview/snapshot?limit=3
- 后端日志：logs/emsx_api.log
- 聚焦后端测试目录：ExecutionView/backend/api/tests/
