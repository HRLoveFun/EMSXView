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

> **当前活跃 handoff 入口**：[`AGENTS.md` §data_management_refactoring 分支工作流](../AGENTS.md#data_management_refactoring-分支工作流-已完成归档--2026-07-02)（📦 已归档，运行时参数见 [`data_access/config.py`](../data_access/config.py) 的 `Config`）。无跨日进行中工作项时，docs 根目录不保留 `handoff.md` 占位。

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
| [`data_access/config.py`](../data_access/config.py)（`Config` 类） | 数据根、库/表常量等只读侧运行时参数（写入侧参数归独立仓库 EMSXDataPipeline） | 修改数据根/库表常量时 |

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

---

## 7. 占位符与可配置参数约定

文档（含 `README.md`、`QUICKSTART.md`、`AGENTS.md`/`CODEBUDDY.md`、`docs/**`）中禁止写入与具体机器绑定的硬编码值，统一使用下列占位符。**本仓库内部文件一律以仓库相对路径引用**，确保文档自包含（不依赖仓库外路径或资源）。

### 7.1 路径占位

| 占位符 | 含义 | 说明 |
|---|---|---|
| `<repo-root>` | 仓库根 | 由仓库根 `.emsxview-root` marker 定位；脚本中用 `Find-EmsxviewRoot` 解析，禁止硬编码"向上 N 层" |
| `${EMSXVIEW_DATA_DIR}` | 数据根 | 环境变量显式覆盖优先；默认值见 `data_access/config.py` 的 `Config.DEFAULT_DATA_DIR` |
| `<data-dir>` | 泛指某个数据目录 | 用于示例命令，实际取值即 `${EMSXVIEW_DATA_DIR}` |
| `<pipeline-repo>` | 独立数据管道仓库 EMSXDataPipeline 的本地检出路径 | **仓库外资源**：仅在说明归属时使用，文档中不得出现其具体磁盘路径 |

### 7.2 主机与端口占位

| 占位符 | 默认值 | 覆盖环境变量 |
|---|---|---|
| `<host>` | `localhost` | — |
| `<API_PORT>` / `<API_BASE_URL>` | `3000` / `http://<host>:3000` | `API_HOST`、`API_PORT` |
| `<MARKETVIEW_PORT>` / `<MARKETVIEW_BASE_URL>` | `8001` / `http://<host>:8001` | `MARKETVIEW_HOST`、`MARKETVIEW_PORT` |
| `<COSTVIEW_PORT>` / `<COSTVIEW_BASE_URL>` | `8002` / `http://<host>:8002` | `COSTVIEW_HOST`、`COSTVIEW_PORT` |
| `<FRONTEND_PORT>` | `5173`（开发态），容器态 `80` | `vite --port`、`VITE_API_URL`、`FRONTEND_PORT` |
| `<POSTGRES_PORT>` / `<PROMETHEUS_PORT>` / `<GRAFANA_PORT>` | `5432` / `9090` / `3001` | `backend/.env` 同名变量 |

### 7.3 仓库外引用处理原则

数据管道的 ETL 写入方已迁独立仓库 EMSXDataPipeline，本仓库仅保留只读访问层 `data_access/`：

- 文档需要指向"原 `DataPipeline/xxx` 文件"时，**改写为本仓库的对应路径**（`data_access/xxx`）；本仓库无对应物时只说明归属（"由独立仓库 EMSXDataPipeline 维护"），不写磁盘路径。
- 历史文档（`docs/archive/**`、`specs/**` 已完成计划）中的旧路径**保留原样作为历史记录**，但如出现用户目录等机器绑定路径，须替换为占位符。
