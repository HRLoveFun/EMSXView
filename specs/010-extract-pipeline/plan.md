# 010-extract-pipeline — 数据库迁移 D:\db + 更新维护拆独立 git 仓库

> 状态：P0 实施中。009-external-data-store 已合入 main（`437601d`，含主树工作区改动落盘 `f5e8d1c`：AGENTS 精简 + fill_fetch 归档目录对齐）。
> 用户补充指示：独立仓库远端稍后接入（先本地 `git init`）；独立项目前端 UI 基于当前项目 databaseview 模块重构（见 D13）。
> 用户拍板的关键决策见 §2（D1/D2/D3/D4/D5/D13）。

## 1. 背景与目标

当前 EMSXView 单仓库同时承担两件事：
- **更新维护**：DataPipeline 数据管道（acquisition/ingestion/processing/analysis/storage/orchestration/…）+ CostView/scripts 维护脚本 + scripts/ops 运维 + report_dims 写侧 + pipeline_jobs 触发 + backend/CostView 的 HTTP 触发端点。
- **读取消费**：CostView 查询/报告/monitoring、CostView/api 读 API、backend/api 只读诊断 + 自身 PostgreSQL、frontend 展示。

调研确凿事实：
1. DataPipeline **出向零依赖**（不 import platform_data/CostView/backend），自带 `pyproject.toml`（包名 `emsxview-datapipeline`），`python -m DataPipeline --once` 可用但带 sys.path hack + DeprecationWarning，未 pip 化。
2. 反向依赖集中在：写路径（daily_update/backfill/ops/report_dims 写）、读路径（大量 `from DataPipeline import ConnectionManager/Config`）、触发路径（`pipeline_jobs.py` subprocess 起 `CostView/scripts/daily_update.py --once` ← 前端 POST /api/db/update、/api/tca/trigger-update）。
3. 当前**无独立常驻管道进程**——管道由 HTTP 端点按需 subprocess 触发。
4. backend 持久化 = 独立 PostgreSQL（非 D:\db sqlite 域）+ 本地业务 JSON 配置（broker_algorithms/hand_instruction/market_broker_mapping，活跃自写自读）；`backend/api/data/fill_fetch_history.db`(20KB, 2026-04 后未更新) 与空 `fills/` 为历史残留，源码无写引用。

**目标终态**：
- 数据（SQLite 库 + market/parquet + 清单 JSON）落在 **`D:\db`**，与任何代码树彻底解耦。
- 更新维护抽取为**独立 git 仓库 + 独立运行**：内含 DataPipeline、全部维护/运维脚本、常驻 **HTTP Runner**（`/run`、`/status`），可被前端/外部按需触发并轮询。
- 当前 EMSXView 仓库**只保留读取消费**：全部维护代码移除，读取端通过**自建轻量只读访问层**访问 `D:\db`（不再 import DataPipeline）。

## 2. 关键决策

| # | 决策 | 理由 / 备注 |
|---|------|------|
| D1 | **独立 git 仓库**承载管道与维护（用户拍板）。建议本地路径 `C:\Users\hrchen\Documents\EMSXDataPipeline`，远端待用户在 GitHub 创建后接入 | 隔离最彻底、独立 CI/发布 |
| D2 | 数据根默认 **`D:\db`**（管道独立仓库 `Config.DATA_DIR` 与当前项目只读层共享此常量来源）；`EMSXVIEW_DATA_DIR` 仍可覆盖（测试/临时用） | 显式、跨盘、固定；G2 防漂移 |
| D3 | **当前项目自建轻量只读访问层**（用户授权我判断）：从现有只读路径裁剪「sqlite3 `mode=ro` 连接 + `D:\db` 路径 + 库名/表名/关键查询常量」为当前仓库小模块（建议 `data_access/`）；配**契约测试**锁与管道侧 schema/路径一致 | 零第三方依赖、见效快；双份常量的漂移风险用契约测试兜底；若未来常变再升级为共享包（计划中预留） |
| D4 | **常驻 Runner 服务**承载管道运行（用户拍板）：独立项目内自含 HTTP 服务（FastAPI/uvicorn 或等价），提供 `POST /run`、`GET /status`（对齐现有 trigger/update-status 语义与幂等、并发保护、进度）；可由前端/外部调用并轮询 | 替代现有 subprocess 触发体验，读缺数据→提示并跳转 runner |
| D5 | backend 保留自身 PostgreSQL 与业务 JSON 配置；历史残留（`backend/api/data/fill_fetch_history.db`、空 `fills/`）实施时人工确认后清理/归档，**不迁 D:\db** | backend 域不属于行情管道域 |
| D6 | 真实数据跨盘搬迁用 **robocopy**（`CostView/data` → `D:\db`，跨盘不可 rename，robocopy 可续传/保 ACL）+ 逐库 `PRAGMA integrity_check`/行数校验 + 源目录改名留证；泛化 009 迁移脚本为参数化（源/目标可指定） | G0 数据零受损；失败可重入 |
| D7 | 管道 CLI 正式 pip 化：`[project.scripts]` 提供 console scripts，移除 sys.path hack 与 DeprecationWarning | 独立安装/运行前提 |
| D8 | `pipeline_jobs.py` 的 subprocess 触发逻辑迁入独立项目 Runner（进程内或 subprocess 但指向独立仓库自身）；当前仓库删除该模块 | 触发职责归维护侧 |
| D9 | 当前仓库**删除维护代码**：CostView/scripts 维护脚本、scripts/ops、scripts/run_archive.py、report_dims 写侧、`CostView/src/__main__.py` 管道 CLI、trigger 端点、前端触发 UI | 只读化收口 |
| D10 | 前端"缺数据自动触发"改为：优先调 Runner `/run`+轮询 `/status`（保留 UX）；Runner 未配置时仅提示，不再内嵌管道 | 跨项目解耦 |
| D11 | 边界与门禁：module-boundary 增「当前仓库禁止 import DataPipeline/emsxview-datapipeline」；audit/quality_gate 收口；AGENTS/CODEBUDDY、ADR 同步 | CI 硬约束 |
| D12 | 测试随迁：管道侧全部测试迁独立仓库独立跑；当前仓库测试改用只读访问层；契约测试双仓共用 | 回归防线 |
| D13 | **独立项目前端 UI 基于当前项目 `frontend/src/modules/databaseview` 重构**（用户指示）：复用 DatabaseOverviewGrid / DateCoverageTable / IntegrityBanner / SchemaSamplePanel / DatabaseDetailDrawer / UpdateControl 组件形态，API 层改指 Runner（`/run` `/status` 及只读诊断端点），构建为独立 Vite React 应用随独立仓库部署 | 控制台 UX 与现有 databaseview 一致，降低学习成本 |

## 3. 边界定义（迁什么 / 留什么）

### 3.1 迁入独立仓库（更新维护面）
| 代码 | 说明 |
|---|---|
| `DataPipeline/` 全部 | config/storage/orchestration/acquisition/ingestion/processing/analysis/validation/pipeline_guards/circuit_breaker/monitoring/common/tests + pyproject/BUSINESS_FLOW |
| `CostView/scripts/daily_update.py` | 现管道主入口（subprocess 目标）→ 统一为独立仓库 `python -m DataPipeline --once`，文件随迁作兼容壳或删除（验收为准） |
| `CostView/scripts/backfill_bdib_history.py`、`backfill_raw_bdib.py`、`backfill_regime.py`、`fetch_macro_calendar.py`、`seed_macro_events.py`、`run_attribution.py`、`install_scheduler.py` | 维护/回填脚本 |
| `CostView/src/monitoring/report_dims.py` 写侧 | 建表 DDL + WRITE + INSERT/DELETE tca_report_dims（读侧留当前仓库） |
| `CostView/src/__main__.py` 管道命令 | run_full_pipeline/run_process/run_aggregate/run_ingest/fetch/scheduler（保留 query_cli 只读入口） |
| `platform_data/pipeline_jobs.py` | 触发协调 → 迁为 Runner 核心 |
| `scripts/run_archive.py` + `scripts/ops/*`（约 25 个 backfill/manage 脚本） | 归档/回填/迁移/修复/索引 |
| `scripts/health_check.py`、`daily_observation_check.py` | 若依赖管道写侧，随迁或改只读（验收判定） |

### 3.2 保留在当前仓库（读取面）
| 代码 | 改动 |
|---|---|
| `CostView/src` 查询/报告/monitoring 读侧 | import 改只读访问层 |
| `CostView/api` 读 API | config 改读侧配置；移除 trigger/auto_trigger |
| `backend/api` | PostgreSQL 保留；D:\db 只读诊断保留；移除 POST /api/db/update trigger；业务 JSON 保留；清理残留 |
| `platform_data` 读适配器（tca_bridge/database_diagnostics/regime_query/config_bridge/market/handoff） | import 改只读访问层 |
| `frontend` | 移除内嵌触发，改调 Runner（可选）/提示 |
| `scripts/start-all.bat`/service-manager | 编排（可选加入 Runner 探测/说明） |

### 3.3 数据资产归属（目标 D:\db）
- 迁移：`raw_fills` `processed_fills` `raw_bdib` `processed_raw_bdib` `fill_bdib` `regime` `execution_history` `ticker_registry` + `fill_fetch_history`/`bdib_fetch_history`（若由管道维护）+ `market/bdib_10s` parquet + `*.json`（manifest/outdated/permanent_gap/quota_pause/market_mapping 等随写方）。
- 留原处：backend 自身 PostgreSQL、业务 JSON、backend 诊断缓存。
- 明确剔除：`backend/api/data/fill_fetch_history.db` 与空 `fills/`（历史残留，人工确认归档）。

## 4. 目标架构

```
C:\Users\hrchen\Documents\EMSXDataPipeline\      ← 独立 git 仓库（D1）
  DataPipeline/  (pip: emsxview-datapipeline, console scripts D7)
  runner/        HTTP Runner：POST /run, GET /status（D4）
  scripts/       daily_update 兼容壳/回填/ops 迁移（随迁）
  pyproject.toml / venv / README / tests
  数据默认 D:\db（D2）
        ▲ mode=ro 只读 + HTTP /run /status
C:\Users\hrchen\Documents\EMSXView\             ← 当前仓库（纯读取）
  CostView/src|api（读）  backend/api（读+自身 PG）
  platform_data 读适配器   frontend（只读展示）
  data_access/  轻量只读层（sqlite mode=ro + D:\db 路径/常量）D3
D:\db\  9 个 sqlite + market/parquet + *.json      （数据资产 3.3）
```

## 5. 实施阶段

| 阶段 | 内容 | 验收 |
|---|---|---|
| P0 | 建独立仓库骨架：git init/远端接入、拷贝 DataPipeline 全树、pyproject console scripts、独立 venv、`Config.DATA_DIR=D:\db`、Runner 骨架 `/run /status` hello | `python -m DataPipeline --help` 无 sys.path hack；Runner 本地起服务返回 OK |
| P1 | 迁移代码树：维护脚本/ops/report_dims 写侧/__main__ 管道命令/pipeline_jobs→Runner；管道在独立仓库全测试绿（DataPipeline 自测） | 独立仓库 pytest 全绿；无外部 import |
| P2 | 当前仓库只读访问层 `data_access/` + 剥离全部 `import DataPipeline`（CostView/src、CostView/api、platform_data、backend）；契约测试锁路径/schema | grep 清零 + 边界测试禁入 + 当前仓库测试绿 |
| P3 | 当前仓库移除维护：删维护脚本/ops/trigger 端点/pipeline_jobs/report_dims 写/__main__ 管道命令/前端触发 UI（改 Runner/提示）；清理 backend 残留 | module-boundary/audit 通过；读 API 回归绿 |
| P4 | 真实数据搬移：停写入方 → robocopy `CostView/data`→`D:\db` → 校验 → 源改名留证；`EMSXVIEW_DATA_DIR=D:\db` 生效验证 | integrity_check 通过；读端连 D:\db 正常 |
| P5 | Runner 常驻化 + 调度：uvicorn 服务、任务计划（可选兜底）、部署编排/健康检查、前端触发接通 `/run /status` | 端到端：前端触发→runner 拉取→状态轮询→新数据可见 |
| P6 | 门禁/文档/收尾：module-boundary 更新、quality_gate baseline、ADR 新纪录、AGENTS/QUICKSTART/启动说明、009 遗留 WARNING 迁移提示改指 D:\db | 文档漂移审计 OK；两仓 CI 绿 |

## 6. 风险与对策

| 风险 | 对策 |
|---|---|
| 读路径 import 面广漏改 | P2 grep 清单化 + 边界测试硬禁 import |
| 双份路径/schema 常量漂移 | 契约测试（读侧连接 D:\db 各库 + 关键表存在/列名快照对比管道声明）；预留升级共享包 |
| 跨盘大数据搬迁中断 | robocopy 可续传 + 预检容量 + 逐库校验 + 源留证（G0） |
| 前端触发 UX 回归 | Runner /run /status 语义对齐现有 trigger/update-status；未就绪则优雅提示 |
| 管道写 vs 当前仓库读并发 | 009 mode=ro 已物理隔离（保留） |
| 多 worktree/.env 指向 | 全部统一 `D:\db`；AGENTS/git-workflow 同步 |
| 门禁/审计断裂 | P6 专项收口，含 module-boundary、audit_cross_imports 豁免清单更新 |
| 独立仓库缺远端权限 | P0 本地可先行；远端 URL 由用户在 GitHub 创建后接入，remote 抽象隔离 |

## 7. 回退路径

- 代码回退：独立仓库与当前仓库改动均按阶段分批 PR；任一阶段不达验收即停，不回滚已合入段。
- 数据回退：搬迁仅复制不删，源目录改名留证，`EMSXVIEW_DATA_DIR` 指回源目录即可全量还原。
- 触发回退：Runner 未就绪期间，前端走"仅提示"分支；管道仍可经独立仓库 CLI 手动执行，不阻塞数据更新。

## 8. 关联与待办

- 依赖：ADR-0016（009，mode=ro）、ADR-0012（配置单一来源——独立后两仓各自 Config 需新 ADR 描述共享契约）、ADR-0700（worktree §6.1 数据目录隔离段落更新为 D:\db + 双仓拓扑）。
- 新增 ADR：独立管道仓库与只读访问层契约（库名/表名/路径单一来源与契约测试）。
- specs/009-external-data-store/plan.md：P4 落地后其迁移脚本与 WARNING 文案改指 D:\db。

## 9. 待办事项（清理与收尾）

| # | 事项 | 触发条件 | 说明 |
|---|------|---------|------|
| TODO-1 | **清理留证目录** `EMSXView\CostView\data.migrated.202609022339`（约 145 GB） | 确认 `D:\db` 运行稳定后（建议观察 1–2 个日更周期） | P4 数据迁移的源目录留证；删除即释放 145GB，删除前确认双仓读取均指向 `D:\db` |
| TODO-2 | 配置 `PIPELINE_REPORT_CMD`（每日/每周 TCA 报告钩子） | Runner 常驻部署时 | 报告生成属 EMSXView 读侧（依赖 CostView 读侧聚合），未配置时管道跳过报告步骤并打印提示 |
| TODO-3 | 独立仓库 Runner 常驻化部署 | 运维接入 | `emsx-runner`（:8100）；可配合 Windows 计划任务做每日兜底 |
| TODO-4 | 独立仓库 CI（管道回归测试） | 独立仓库推送后 | 原 EMSXView `pipeline-tests` job 已移除，管道回归需在 EMSXDataPipeline 重建 |
| TODO-5 | `.codebuddy/rules/module-boundary.md` 双仓边界更新 | 双仓稳定后 | 补 data_access 只读层与“禁 import DataPipeline”契约条目 |
| TODO-6 | 主树/其他分支设 `EMSXVIEW_DATA_DIR=D:\db` | PR #5 合并前 | 010 合并后默认值即为 `D:\db`；合并前其他分支需显式设置 |
