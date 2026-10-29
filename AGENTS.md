# EMSXView — Agent 入口

> **本文只做两件事**：说明「该读哪份文档」与「文档怎么改」。项目事实（定位、架构、成熟度、目录、数据层、构建命令）在 `README.md` 与 `docs/`，此处不复述、不留副本。
> 同一事实只有一个可写的家：发现别处有副本，就地改成指针，不要两边各写一半。

## 1. 现在到哪

- **进度与下一步**：`specs/057-execution-decision-loop/tasks.md` 的「状态总览」——唯一状态源，由各交付 PR 随代码更新。
- **模块成熟度**：`README.md` §0（分级定义 + 当前总表）。
- **已失效的说法**：`docs/archive/2026-10-29/agents-invalidated-claims.md`——写文档或代码注释前先查，勿再引用。

## 2. 文档地图

> 五列缺一不可：「何时读」决定一次读哪几份；「何时改」决定改动后谁必须跟着改。地图是**完整清单**，未指向的 `.md` 只能出现在下方豁免块。

<!-- docmap:begin -->
| 路径 | 层 | 回答什么 | 何时读 | 何时改 |
| --- | --- | --- | --- | --- |
| AGENTS.md | L0 | 我该看哪份？文档怎么改？ | 每次会话开始 | 文档结构变化时 |
| README.md | L1 | 项目是什么、模块怎么分工、怎么跑起来？ | 第一次上手、改对外用法前 | 模块、启动方式、成熟度变化时 |
| QUICKSTART.md | L1 | Windows 一键启动怎么用？ | 第一次起服务时 | 启动菜单变化时 |
| specs/057-execution-decision-loop/tasks.md | L1 | 现在到哪、下一步派哪个 DL？ | 接手任何任务前 | 每批交付 PR 内 |
| docs/index.md | L1 | 文档怎么分层、何时该改哪份、占位符怎么写？ | 写或改文档前 | 文档规则变化时 |
| docs/dev-guide.md | L1 | 本地怎么起、改完怎么验、启动器有哪些硬规则？ | 动手写代码前 | 启动或验证流程变化时 |
| .codebuddy/rules/ | L2 | 编码与文件放置约定、模块边界契约、Agent 作业节奏 | 写第一行代码前 | 约定变化时（4 份规则文件） |
| docs/spec/project-structure.md | L2 | 仓库结构、模块使命与边界、权威实现面 | 判断改动归属哪个模块前 | 模块增删、边界变化时 |
| docs/spec/data-domain.md | L2 | 数据归谁所有、只读取数怎么走 | 碰数据访问前 | 数据所有权、适配层变化时 |
| docs/spec/anti-patterns.md | L2 | 哪些做法被禁止（AP-xx） | 写代码、写计划前 | 新增禁止模式时 |
| docs/spec/quality-gate.md | L2 | 门禁规则（AP/OE）与全仓验证命令 | 提交前、改门禁时 | 规则或验证命令变化时 |
| docs/spec/git-workflow.md | L2 | 多任务、多 Agent 怎么并行 | 开 worktree 前 | 流程变化时 |
| docs/spec/boundary-protection.md | L2 | 边界审计怎么实现、失败怎么修 | CI 边界失败时 | 审计规则变化时 |
| docs/spec/module-onboarding.md | L2 | 新增模块要走哪些步骤 | 新建模块前 | 流程变化时 |
| docs/spec/module-api-contracts.md | L2 | 模块间 API 契约 | 改模块接口前 | 契约变化时 |
| docs/spec/plan-design-principles.md | L2 | 计划写合格要满足什么 | 写 `specs/<id>/plan.md` 前 | 原则变化时 |
| docs/spec/refactoring-methodology.md | L2 | 大改怎么不破坏行为 | 重构前 | 方法变化时 |
| docs/spec/attribution-pitfalls.md | L2 | 归因推理的红线（AT-xx） | 做归因、写结论前 | 新增陷阱时 |
| docs/spec/pipeline-resilience.md | L2 | 取数降级与管道韧性约定 | 碰降级路径时 | 约定变化时 |
| docs/spec/memory.md | L2 | 稳定架构约束与 ADR 索引 | 想推翻既有设计前 | 新增 ADR 时 |
| docs/api-contracts.md | L2 | 后端端点、错误码规范 | 加或改端点前 | 端点变化时 |
| docs/schema-contract.md | L2 | 跨模块 TS↔Python 类型契约 | 改 handoff 载荷前 | 契约变化时 |
| docs/api/ | L2 | Bloomberg EMSX 接口与字段语义 | 查字段、查接口时 | 外部文档更新时 |
| docs/ops/service-management.md | L2 | 服务启停、排障、环境变量清单 | 部署、排障时 | 启停方式或变量变化时 |
| docs/blpapi-api-modules.md | L2 | blpapi 各模块怎么用 | 改 Bloomberg 取数时 | 模块变化时 |
| docs/EMSXDataPipeline-TECHNICAL_GUIDE.md | L2 | 上游管道怎么产数（同步副本） | 查数据链路时 | 上游真相源更新时 |
| docs/milestone-1-pretrade-board.md | L2 | MarketView 节点一的范围与已知限制 | 改盘前板时 | 节点交付或限制变化时 |
| docs/report-tca-known-limitations.md | L2 | TCA 报告口径硬缺口（K1–K9） | 改报告口径、对外解释前 | 口径变化时 |
| docs/handoff-costview-html-report.md | L2 | HTML 报告导出怎么接 | 改导出时 | 实现变化时 |
| backend/README.md | L2 | 后端生产部署 | 部署后端时 | 部署方式变化时 |
| backend/QUICKSTART.md | L2 | 后端最小启动步骤 | 首次起后端时 | 步骤变化时 |
| ExecutionView/README.md | L2 | 执行视图模块细节 | 动该模块前 | 模块变化时 |
| CostView/README.md | L2 | 盘后 TCA 模块细节与端点表 | 动该模块前 | 模块变化时 |
| MarketView/README.md | L2 | 市场走势模块细节 | 动该模块前 | 模块变化时 |
| scripts/README.md | L2 | 自动化脚本参考 | 加或换脚本时 | 脚本增删时 |
| docs/spec/adr/ | L3 | 当初为什么这么选 | 想推翻某个设计前 | 做完取舍时新增一条 |
| specs/ | L3 | 其余计划：在途的实施记录与已交付未归档的 `plan.md` | 接某个 DL 时 | 开计划、收计划时 |
| docs/report-full-audit-2026-10-25.md | L3 | 2026-10-25 全项目审计结论与整改卡 | 追溯审计依据时 | 只追加 |
| docs/report-data-inventory-2026-10.md | L3 | 数据盘点与额度测量结论 | 追溯数据能力时 | 只追加 |
| docs/report-cost-model-calibration.md | L3 | 成本模型未达标的诊断 | 用 DL-18/23 前 | 只追加 |
| docs/report-marketview-live-fields.md | L3 | 实时字段可用性矩阵与复测 SOP | 换实时字段时 | 复测后追加 |
| docs/report-029-reliability-hardening-delivery.md | L3 | 029 可靠性加固交付记录 | 追溯 029 时 | 只追加 |
| docs/textbook/ | L3 | TCA 方法论与学术综述 | 需要理论依据时 | 只追加 |
| docs/archive/ | L3 | 被取代的旧文档与历史快照 | 追历史时 | 文档被取代时移入 |
<!-- docmap:end -->

<!-- docmap:exclude:begin -->
# 一行一个 glob，相对仓库根。只放工具自带、夹具局部说明与第三方模板——不放本仓库自己的规范文档。
.codebuddy/skills/**
.codebuddy/commands/**
.codebuddy/plans/**
.specify/**
.opencode/**
.github/**
scripts/reports/**
backend/api/tests/boundaries/README.md
CostView/tests/golden/README.md
backend/config/grafana/dashboards/README.md
frontend/public/strategy-data/README.md
<!-- docmap:exclude:end -->

## 3. 元规则

只放两类：路由（读什么）与文档维护（怎么改）。

1. 按地图「何时读」列取文档，一次只读需要的那 1–3 份，不全量读。
2. 同一事实只在一处可写，其余位置只留指针；发现副本就地改成指针。
3. 改文档结构：**先**改本文件地图 → 再动文件 → 跑 `python scripts/doc_check.py`；退出码 0 才算做完。
4. 文档与代码冲突：描述性文档（现状/结构/进度）改文档；规范性文档（约定/契约/安全）改代码或记例外；分不清就进冲突清单问用户，禁止两边各改一半。
5. 回复用户一律中文；代码、标识符、技术术语保持英文；代码注释用中文。

## 4. 改动协议

| 事件 | 必改（按顺序） | 不用改 |
| --- | --- | --- |
| 一批任务收尾 | `tasks.md` 状态行 + 子编号/证据 + 日期 | `README.md`（结构没变时） |
| 新增/删除模块 | `project-structure.md` 模块表 → 本文件地图 → 新 L2 | `QUICKSTART.md` |
| 做了取舍 | 新 ADR → `memory.md` 索引 → 相关 L1 加指针 | `tasks.md` 只记结果 |
| 文档结构变化 | **先**本文件地图 → 再动文件 → `doc_check.py` | 其余 |

完整写入时机表、分层预算、归档策略见 `docs/index.md` §1–§3。验收：`python scripts/doc_check.py` 退出码 0；契约级漂移另跑 `python scripts/audit_doc_drift.py`。
