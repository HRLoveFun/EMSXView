# EMSXView Documentation Guide

> 当前 docs 目录入口与维护规则
> Last updated: 2026-07-02
> 📦 已重组为 spec/api/ops 子目录结构；`docs/roadmap/` 整目录已归档（2026-07-02），详见 [§5 Archive Policy](#5-archive-policy)

---

## 1. Root Principles

docs 根目录只保留入口导航，其余按领域划入子目录：

- docs/spec/ — 架构规范（稳定、真相源）
- docs/api/ — API 接口定义
- docs/ops/ — 运维部署

已完成阶段的实施总结、一次性诊断报告归入 docs/archive/。

> **当前活跃 handoff 入口**：[`AGENTS.md` §data_management_refactoring 分支工作流](../AGENTS.md#data_management_refactoring-分支工作流-已完成归档--2026-07-02)（📦 已归档，运行时参数见 `DataPipeline/config.py`）。无跨日进行中工作项时，docs 根目录不保留 `handoff.md` 占位。

---

## 2. Canonical Docs

| 路径 | 用途 | 何时更新 |
|---|---|---|
| docs/spec/project-structure.md | 当前仓库结构与权威实现面 | 结构调整、模块边界变化时 |
| docs/spec/data-domain.md | 逻辑数据域与适配层边界 | 数据所有权或适配层变化时 |
| docs/spec/memory.md | 稳定架构记忆与长期约束 | 形成新的稳定规则时 |
| docs/dev-guide.md | 开发指南与验证约束 | 开发流程或权威入口变化时 |
| docs/schema-contract.md | 跨域类型契约（前端 TS ↔ 后端 Python） | 跨模块协议变更时 |
| docs/api/bloomberg-emsx-reference.md | Bloomberg EMSX API 参考（第三方权威文档，非公开资源） | 外部分发 |
| docs/ops/service-management.md | 启停、健康检查、日志查看 | 服务管理方式变化时 |
| `DataPipeline/config.py`（Config 类） | 数据/存储/管道运行时参数 | 修改 BDIB/分区/归档参数时 |

---

## 3. Generated And Reference Material

> 时序图已归档至 `docs/archive/2026-06-29/sequence-diagrams.md`（无 CI 保障且与实际代码漂移）。如需新时序图，请从代码生成或显式标注为草稿。

---

## 4. Knowledge Base Outside docs

持续维护的知识库在 .github/knowledge/：

| 文件 | 说明 |
|---|---|
| .github/knowledge/architecture-decisions.md | 架构决策（本仓库 ADR 的对外映射） |
| .github/knowledge/error-patterns.md | 错误模式与解法 |

---

## 5. Archive Policy

满足以下任一条件的文档应归档到 docs/archive/YYYY-MM-DD/：

- 主要描述的功能或阶段已经完成
- 主要内容是一次性诊断或修复报告
- 仍在引用 app/、emsxview-backend/ 等旧路径
- 已被新的 source-of-truth 文档替代

---

## 6. Maintenance Rule Of Thumb

如果某份文档不能回答"现在开发这项功能应该以哪里为准"，它不该留在 docs/ 下。
