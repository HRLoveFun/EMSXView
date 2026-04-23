# EMSX Documentation Guide

> 当前 docs 目录入口与维护规则
> Last updated: 2026-04-22

---

## 1. Root Principles

docs 根目录只保留两类文档：

- 当前仍有效、会被持续维护的 source-of-truth 文档
- 当前运行和交接必须依赖的操作文档

以下内容不再长期留在 docs 根目录：

- 已完成阶段的实施总结
- 一次性故障诊断报告
- 明确引用旧路径或旧架构的历史说明

这些文档统一进入 docs/archive/ 下按日期归档。

---

## 2. Canonical Docs

| 文档 | 用途 | 何时更新 |
|---|---|---|
| docs/CLAUDE.md | 当前开发指南与验证约束 | 开发流程或权威入口变化时 |
| docs/PROJECT_STRUCTURE.md | 当前仓库结构与权威实现面 | 结构调整、模块边界变化时 |
| docs/DATA_DOMAIN.md | 逻辑数据域与适配层边界 | 数据所有权或适配层变化时 |
| docs/MEMORY.md | 稳定架构记忆与长期约束 | 形成新的稳定规则时 |
| docs/HANDOFF.md | 当前阻塞、运行状态、下一步 | 每次阶段性收尾时 |
| docs/SERVICE_MANAGEMENT.md | 启停、健康检查、日志查看 | 服务管理方式变化时 |
| docs/EXECUTION_PLATFORM_WBS.md | 活跃路线图与阶段拆解 | 路线图变更时 |
| docs/MODULAR_SEQUENCE_DIAGRAMS.md | 当前模块级时序说明 | 关键调用链改变时 |

---

## 3. Generated And Reference Material

| 位置 | 说明 |
|---|---|
| docs/generated/ | 自动生成的状态快照与 handoff 工件 |
| docs/modular_sequence_diagrams/ | 时序图的 Mermaid 源文件与图片 |

---

## 4. Knowledge Base Outside docs

持续维护的知识库不在 docs/ 下，而在 .github/knowledge/：

| 文件 | 说明 |
|---|---|
| .github/knowledge/architecture-decisions.md | 架构决策 |
| .github/knowledge/error-patterns.md | 错误模式与解法 |
| .github/knowledge/user-needs.md | 高频用户需求 |
| .github/knowledge/iteration-log.md | 迭代日志 |

---

## 5. Archive Policy

满足以下任一条件的文档应归档：

- 主要描述的功能或阶段已经完成
- 主要内容是一次性诊断或修复报告
- 仍在引用 app/、emsx-backend/ 等旧路径
- 已被新的 source-of-truth 文档替代

归档位置：

- docs/archive/按日期目录/

本轮归档索引：

- docs/archive/2026-04-22/README.md

---

## 6. Maintenance Rule Of Thumb

如果某份文档不能回答“现在开发这项功能应该以哪里为准”，它大概率不该继续留在 docs 根目录。