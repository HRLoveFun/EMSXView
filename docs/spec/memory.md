# Project Memory

> 架构记忆入口
> 详细决策见 `docs/spec/adr/`，本文件仅作索引与高频速查
> Last updated: 2026-06-03

---

## 1. 关键入口（高频引用）

| 用途 | 路径 |
|---|---|
| 前端壳 | `frontend/src/app/AppShell.tsx` |
| 后端装配 | `backend/api/main.py` |
| 数据入口 | `platform_data/adapters/` |
| 流水线配置 | `DataPipeline/config.py` |
| 平台契约 | `platform_data/contracts/` |
| 共享规范 | `AGENTS.md`（仓库根） |
| Agent 编码规则 | `.codebuddy/rules/coding-style.md` |
| Agent 上下文 | `.codebuddy/rules/project-context.md` |
| 模块边界 | `.codebuddy/rules/module-boundary.md` |

---

## 2. 已稳定的架构决定（ADR 索引）

> AI agent 进入仓库必读：按编号顺序阅读 Accepted 状态的 ADR
> 完整 ADR 列表见 `docs/spec/adr/README.md`

| 编号 | 标题 | 状态 |
|---|---|---|
| [ADR-0001](adr/0001-one-logical-data-domain.md) | 一个逻辑数据域，多种存储技术 | Accepted |
| [ADR-0002](adr/0002-platform-data-adapter-pattern.md) | platform_data 适配器模式 | Accepted |
| [ADR-0003](adr/0003-executionview-owns-operational-state.md) | ExecutionView 拥有 operational state | Accepted |
| [ADR-0004](adr/0004-costview-focused-on-evaluation.md) | CostView 聚焦算法评估与分析 | Accepted |
| [ADR-0005](adr/0005-data-pipeline-extraction.md) | Data Platform 子域从 CostView 抽取 | Accepted |
| [ADR-0006](adr/0006-dataplatform-as-independent-subdomain.md) | Data Platform 作为独立子域 | Accepted |
| [ADR-0007](adr/0007-handoff-exchange-pattern.md) | Handoff 跨模块交换模式 | Accepted |
| [ADR-0008](adr/0008-frontend-module-registry-pattern.md) | 前端模块自注册模式 | Accepted |
| [ADR-0009](adr/0009-blend-of-microservice-and-monolith.md) | 单进程/微服务双模部署 | Accepted |
| [ADR-0010](adr/0010-bloomberg-session-model.md) | Bloomberg 会话模型 | Accepted |
| [ADR-0011](adr/0011-fx-rate-handling-rules.md) | FX 汇率处理规则 | Accepted |
| [ADR-0012](adr/0012-config-isolation-rule.md) | 配置隔离：DataPipeline/config 单一来源 | Accepted |
| [ADR-0013](adr/0013-platform-data-adapter-current-state.md) | platform_data 适配器现状与 data-domain.md 偏差 | Accepted |

---

## 3. 阅读顺序（Agent 速查）

**新进入 agent**（按此顺序阅读 9 份文档）：
1. `AGENTS.md` — 工作流与安全规则
2. `.codebuddy/rules/project-context.md` — 技术栈与模块清单
3. `.codebuddy/rules/coding-style.md` — 命名/目录/状态管理
4. `.codebuddy/rules/module-boundary.md` — ★ 模块边界契约
5. `docs/spec/project-structure.md` — 当前仓库结构
6. `docs/spec/data-domain.md` — 数据域所有权
7. **本文件 `memory.md`** — 架构记忆入口
8. `docs/spec/module-onboarding.md` — 新增模块流程
9. `docs/spec/anti-patterns.md` — ★ 禁止模式

**涉及数据/存储/管道改动时**额外阅读：
- `data_management_refactoring_control.md` — 重构进度
- `data_management_refactoring_plan.md` — 重构实施

---

## 4. 数据持久化语义（运行时规则）

- `ENABLE_DB_PERSISTENCE=true` 时，后端启动会执行数据库 bootstrap
- `ENABLE_DB_PERSISTENCE=false` 时，数据库视为可选能力
- 可选模式下 `/api/health` 应返回 `database.status=disabled`，而非 `disconnected`

---

## 5. Bloomberg 会话与字段规则

- 订阅、请求响应、市场数据/RefData 已分离，避免 `nextEvent` 竞争
- RefData pending 必须与对应 correlation id 精确绑定，不能全局粗暴清零
- Bloomberg 字段必须进入订阅列表才会收到
- Bloomberg 字段类型必须与解析器类型一致

---

## 6. FX 汇率处理

- direct 与 inverse 同时存在时，inverse 更可靠
- 已知 10x/100x/1000x 缩放报价应视为报价约定，而非持续 WARNING
- 只有缩放归一化后仍显著偏离的 direct/inverse 差异才保留 WARNING

---

## 7. 文档维护规则

- 决策类内容 → `docs/spec/adr/NNNN-*.md`
- 运行时模式 → 本文件 `memory.md`（保持简短，仅作速查）
- 一次性诊断报告 → `docs/archive/YYYY-MM-DD/`
- 阶段性总结 → `docs/roadmap/` 或 `docs/handoff.md`
- Agent 总则 → `.github/agent.md`
- 错误模式 → `.github/knowledge/error-patterns.md`
- 架构决策摘要 → `.github/knowledge/architecture-decisions.md`（本仓库 ADR 的对外映射）
