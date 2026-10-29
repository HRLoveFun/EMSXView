# EMSXView 交易平台

> L1 | 权威：项目定位、成熟度分级总表、架构图与部署形态、安装与运行命令、文档入口 | 不权威：模块能力清单与目录结构/技术栈（见 `docs/spec/project-structure.md`）、数据层与降级（见 `docs/spec/data-domain.md` 与 `docs/ops/service-management.md`）、文档清单（见 `AGENTS.md` 地图）、批次进度（见 `specs/057-*/tasks.md`）

> 订单执行与交易成本分析（TCA）单体仓库：交易执行视图（ExecutionView）、市场走势视图（MarketView）、盘后 TCA（CostView），共享一个 React 前端壳与一个只读数据访问层。
>
> **文档入口与作业规范见 [AGENTS.md](./AGENTS.md)**：它给出完整文档地图（该读哪份、何时改）与改动协议；编码约定、文件放置、Git Worktree 流程分别在 `.codebuddy/rules/`、`docs/dev-guide.md`、`docs/spec/git-workflow.md`。

---

> **占位符约定**：`<host>` 默认 `localhost`；`<API_BASE_URL>` / `<MARKETVIEW_BASE_URL>` / `<COSTVIEW_BASE_URL>` 默认 `http://localhost:3000` / `:8001` / `:8002`；`<repo-root>` 指仓库根（由 `.emsxview-root` marker 定位）；`${EMSXVIEW_DATA_DIR}` 指数据根。完整约定见 [docs/index.md §5](./docs/index.md#5-占位符与可配置参数约定)。

> **本 README 的可验证性原则**：每项能力描述均标注「入口（文件/端点）+ 验证方式（测试/命令）」。标注「实测」的数据来自静态代码审计与本机数据目录测量，未含运行时验证；过期的描述请在变更时同步更新 §11。

---

## 0. 模块成熟度分级（契约定义）

本仓库所有模块使用以下统一分级，**禁止**在无证据的情况下宣称"production-ready"等无判定标准的形容词：

| 等级 | 含义 | 必须满足的证据 |
|------|------|----------------|
| **GA / 生产就绪** | 已在真实交易流程中使用 | 真实交易数据持续入库 + 自动化测试覆盖核心路径 + 运维手册存在 |
| **Beta** | 功能完整但未全量 | 单元/集成测试 + 已知限制清单（known limitations）公开发布 |
| **Scaffold / 骨架** | 仅有接口与占位 | README 明确列出"未实现"清单 |

### 当前分级总表（2026-10-20 复核）

| 模块 | 等级 | 判定证据 | 已知欠缺 |
|------|------|----------|----------|
| **ExecutionView**（`backend/api/` + `ExecutionView/module/`） | **GA** | 真实成交数据持续入库（`raw_fills.db` 7.15 GB、`execution_history.db` 6.54 GB，实测 2026-10-20）；订单/路由/合规/调度均有测试（`cd backend/api && python -m pytest tests/ -q`）；运维手册 [docs/ops/service-management.md](./docs/ops/service-management.md) | 无正式 SLA 文档；无独立端到端集成测试套件（依赖 mock Bloomberg）；执行区间量价视图已实现（DL-30），待用户复核 |
| **CostView**（`CostView/` + `CostView/module/`） | **Beta** | 测试含 CLI 入口与黄金样本回归（`python -m pytest CostView/tests/ -q`）；14 个 API 端点全部可追溯到代码；已知限制清单 [docs/report-tca-known-limitations.md](./docs/report-tca-known-limitations.md) | 覆盖率未量化（已配 coverage 但未设 `--cov-fail-under`）；无本模块专项运维手册（`docs/ops/` 未覆盖，故不进 GA） |
| **MarketView**（`MarketView/`） | **Beta** | 8 个端点（快照 / 盘中特征 / handoff / 盘前单导出 / 盘前单装配 / 日度基线 / 事件与状态 / pool-board）；测试见 `python -m pytest MarketView/tests/ -q`；已知限制见 [节点一交付说明](docs/milestone-1-pretrade-board.md) | 池内量价/难度/成本同屏已实现（DL-29，待用户复核）；SLA/运维文档未实现；实时列依赖开关 |
| **frontend/**（React 壳） | **Beta** | vitest 覆盖壳层与三模块（`npm test`）；三模块注册完整 | 覆盖率未量化 |
| **data_access/**（只读数据层） | **Beta** | 契约测试锁定两仓常量一致（`data_access/config.py` 模块 docstring）；`mode=ro` 连接层 | 无自身测试目录 |
| **platform_data/**（跨模块适配层） | **Beta（部分规划中）** | handoff/contracts/tests 均有实现 | 部分 Adapter 为规划中、尚未实现，见 [ADR-0013](./docs/spec/adr/0013-platform-data-adapter-current-state.md)，禁止按符号 import |

---

## 1. Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                         EMSXView Trading Platform                             │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐          │
│  │   MarketView     │──▶│  ExecutionView   │──▶│    CostView      │          │
│  │ (Market Trend)   │   │(Order Execution) │   │  (Post-Trade)    │          │
│  │  [Beta]          │   │  [GA]            │   │  [Beta]          │          │
│  │ :<MARKETVIEW_PORT>│  │  :<API_PORT>     │   │ :<COSTVIEW_PORT> │          │
│  └────────┬─────────┘   └───────┬──────────┘   └───────┬──────────┘          │
│           │                     │                      │                     │
│           ▼                     ▼                      ▼                     │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                      Shared Infrastructure                           │   │
│  │  frontend/ [Beta] (React shell) · platform_data/ [Beta] (adapters)   │   │
│  │  data_access/ [Beta] (read-only) · SQLite (只读, ~128GB) ·            │   │
│  │  PostgreSQL (可选) · Redis (可选) · Nginx                              │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┄┄┄ 仓库外（独立仓库 EMSXDataPipeline）┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄   │
│  数据管道 Runner（唯一写入方，本机 :8100）──写入──▶ ${EMSXVIEW_DATA_DIR}      │
└──────────────────────────────────────────────────────────────────────────────┘
```

> 图中方框均携带成熟度标签（定义见 §0）。箭头仅表示数据流向，**不表示能力对等**（MarketView 与 CostView 完成度不对等）。MarketView 与 ExecutionView 共享同一批行情/基线数据，但观察轴不同：前者按「标的 × 交易日」看市场走势，后者按「订单/路由 × 执行区间」看执行质量，两种视图并存。

### Deployment Modes

| Mode | 控制方式 | Architecture |
|------|----------|--------------|
| **Microservice**（默认） | 无需配置 | Core `<API_PORT>`、CostView `<COSTVIEW_PORT>` 独立进程 |
| **CostView 路由桥接**（可选） | `EMSXVIEW_OPTIONAL_MODULES`（默认 `costview:CostView`） | CostView 的 `/api/tca/*` 路由挂载进 core 进程（`backend/api/routers/costview.py`），前端经 `:3000` 单入口访问，无需启动 `:8002` |

- 可选模块由 `backend/api/main.py` 的 `_register_optional` 加载（`*`/`all` 加载全部，置空禁用）；MarketView **没有**桥接路径，仅独立运行，由 `emsxview.bat start` 一并拉起（未启动时前端 Market View 标签页所有面板报 500）。
- 跨模块 handoff 后端由 `EMSXVIEW_HANDOFF_BACKEND` 选择：`memory`（默认，进程内 dict + 锁）或 `redis`（跨进程）；非法值启动即 `ValueError`。
- 已失效的历史机制（`EMSXVIEW_MERGE_MODULES`、`VITE_USE_MOCK`、`CORS_ORIGINS` 等）汇总见 [已失效声明归档](./docs/archive/2026-10-29/agents-invalidated-claims.md)（原 `AGENTS.md` §14）。

---

## 2. Directory Structure

权威目录结构只有一份：[`docs/spec/project-structure.md` §3](./docs/spec/project-structure.md)
（各目录职责、模块根级布局、构建产物分离、legacy 面）。此处不复制。

## 3. 跨模块数据流（方向 · 时序 · 一致性）

Handoff 三通道的容量 / TTL / last-write-wins 语义、ETL 触发链与载荷限制见
[`docs/schema-contract.md`](./docs/schema-contract.md)「运行时语义」；跨模块类型契约同文件
Contract 1–4。

## 4. Module Descriptions（最小完整描述）

模块使命与边界、逐模块能力清单（已实现 / 规划中，每条带入口 + 验证）见
[`docs/spec/project-structure.md`](./docs/spec/project-structure.md) §1 与 §8。此处不复制。

## 5. 数据层（规模实测 · 选型理由 · 已知瓶颈）

- 存储规模、选型理由、已知瓶颈、只读访问通道：[`docs/spec/data-domain.md`](./docs/spec/data-domain.md)「Storage scale & selection」
- 主路径失败时的降级行为与用户可见影响：[`docs/ops/service-management.md`](./docs/ops/service-management.md)「降级路径」

## 6. 前端入口唯一表

见 [`docs/spec/project-structure.md`](./docs/spec/project-structure.md)「前端入口唯一表」。

## 7. Technology Stack

见 [`docs/spec/project-structure.md`](./docs/spec/project-structure.md)「Technology Stack」。

## 8. 降级路径（Degradation Paths）

见 [`docs/ops/service-management.md`](./docs/ops/service-management.md)「降级路径」。

## 9. Installation & Running

### Quick Start（Windows）

```batch
emsxview.bat start        :: 启动（默认即 status；另有 stop / restart）
relaunch_service.bat      :: 双击重启：等待前端就绪并打开页面
```

完整交互说明见 [`QUICKSTART.md`](./QUICKSTART.md)；服务启停与排障见
[`docs/ops/service-management.md`](./docs/ops/service-management.md)。

### Prerequisites

- **Bloomberg Terminal** 且已启用 API（MarketView / CostView 无此依赖）
- **Python 3.11+**（后端与 CostView）
- **Node.js 20+**（前端；本机实测 22）
- **Docker Desktop 4.x**（容器化部署）

### 前端

```bash
cd <repo-root>                  # npm workspaces 根（frontend + ExecutionView 共用依赖树）
npm install                     # 依赖只需在仓库根安装一次

cd frontend
npm run dev                     # http://<host>:<FRONTEND_PORT>（VITE_API_URL 为空则 mock）
npm run build                   # → frontend/dist/
npm run typecheck && npm run lint && npm run lint:modules && npm test

# 独立模块构建（→ frontend/dist-modules/<module>/，与主应用 dist/ 分离，ADR-0020）
npm run build:execution | build:costview | build:marketview | build:all-modules
```

### 后端与微服务

```bash
cd <repo-root>/backend/api && pip install -r requirements.txt && python main.py   # Core :<API_PORT>
cd <repo-root>/MarketView && pip install -r requirements.txt && python main.py    # :<MARKETVIEW_PORT>
cd <repo-root>/CostView/api && pip install -r ../requirements.txt && python main.py  # :<COSTVIEW_PORT>

# CostView 只读巡检 CLI（退出码 0 / 2 数据源不可用 / 3 空结果）
python -m CostView.src --query summary --date 20260408
```

### 测试与门禁

全仓验证矩阵（后端 / CostView / MarketView / 前端 / 审计脚本 / 质量门禁）见
[`docs/spec/quality-gate.md`](./docs/spec/quality-gate.md)「全仓验证矩阵」。

### Docker（生产）

```bash
cd <repo-root>/backend
docker compose up -d                                  # 全栈
docker compose -f docker-compose.host.yml up -d       # host-network（本地 Bloomberg 终端）
docker compose --profile monitoring up -d             # 追加 Prometheus + Grafana
```

### 端口与环境变量

端口表、后端 / 前端环境变量清单见
[`docs/ops/service-management.md`](./docs/ops/service-management.md)「环境变量清单」。
数据根解析优先级：`${EMSXVIEW_DATA_DIR}` > `Config.DEFAULT_DATA_DIR`（`data_access/config.py`）。

## 10. 文档入口

文档清单只有一处：**[`AGENTS.md` 文档地图](./AGENTS.md)**（五列：路径 / 层 / 回答什么 / 何时读 / 何时改）。本节不维护第二份清单；新增或移动文档只改那张表。

> 主从关系：`AGENTS.md` 负责路由（该读哪份、何时改）与改动协议；本 README 面向人类读者给出概览与可验证证据；`docs/` 下的文档按 L2/L3 承担实现细节与历史。文档规则（分层预算、写入时机、归档、占位符）见 [docs/index.md](./docs/index.md)。

## 11. 变更摘要（模块级，可追溯记录）

2026-08-26 ~ 2026-10-20 的模块级变更记录已归档：
[`docs/archive/2026-10-29/readme-changelog.md`](./docs/archive/2026-10-29/readme-changelog.md)。
新增变更不再回写本 README，按 `docs/index.md` §2 写入时机表处理（取舍进 ADR）。

---

**Last updated**: 2026-10-29（结构下沉：模块能力 / 数据层 / 降级 / 技术栈归入 `docs/spec/` 与 `docs/ops/`）
