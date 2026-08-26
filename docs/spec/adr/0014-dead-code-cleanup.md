# ADR-0014: 死代码清理 — 一次性运维脚本与未接线实现移除

> 状态: Accepted
> 日期: 2026-08-26
> 标签: refactoring, cleanup, scripts

## 背景 (Context)

仓库历经多轮已完成的数据治理（S2 跨日修复、BDIB 覆盖率回补、Phase A-D 存储重构、EUR ticker 事故修复、002 管道护栏等），各阶段遗留大量一次性运维脚本与从未接线的实现。2026-08-26 全仓引用图分析（404 个 .py 的 import/subprocess/配置接线扫描 + 前端从 5 个入口的可达性分析）确认：

| 类别 | 数量 | 判定依据 |
|---|---|---|
| 临时调试件（`_debug_*` / `_verify_*` 等） | 7 | 零引用，命名即临时 |
| 已完成使命的一次性脚本（S2 六件套、Phase A-D 批次、ops 迁移/验收件、EUR 事故件、diagnose/devtools） | 35 | AGENTS 记录 gap=0 完成 + git 历史 audit JSON 凭证，全部零引用 |
| 从未接线的实现（`backend/api/errors.py`、`platform_data/execution_history_service.py`、`storage/{access_impl,crypto,write_queue,fetch_history_db}`、`analysis/regime/{sync_macro_calendar,data_source,validate_macro_calendar}`、冗余 CLI ×3） | 12 | InRefs=0；errors.py 与 execution_history_service 均有平行实现顶着 |
| 无活引用的历史归档文档（legacy-costview-frontend、final-refactoring-plan 等） | 19 | git 历史永久可找回 |

合计 73 文件 / 约 15,000 行。另发现根 `.gitignore` 未锚定的 `data/` 规则误伤了 `frontend/src/modules/execution/data/` 兼容层（未被 git 跟踪，fresh clone 会编译失败），已先行锚定修复。

**保留判定**：health_check / daily_update / BDIB 回补四件套 / FX 回填族 / import_excel_fills / cleanup_excluded_exchanges_tickers / quality_gate 与 audit 系列 / bloomberg_adapter 垫片等"休眠运维接口"——它们被产品文案、runbook 或 CI/hook 接线引用，不是死代码。

## 决策 (Decision)

1. **删除上述 73 个文件**；所有被删文件均可从 git 历史恢复（删除前基线提交为界）
2. **文档同步原则**：删除与文档修订同 commit；AGENTS.md/BUSINESS_FLOW.md 中被删脚本改注"已随 2026-08-26 清理归档"；活代码中指向已删脚本的提示文案（如 `stages_process.py` 空 bar 告警）改为指引 git 历史
3. **历史记录豁免**：specs/*、plans/*、docs/archive 被引用件、ADR、SQL 迁移注释中的历史提及不修改——它们是执行记录，不是现状声明
4. **`.gitignore` 锚定规则**：目录忽略模式必须带前导 `/`（仅匹配仓库根），源码树内同名目录需显式列出

## 后果 (Consequences)

### 正面
- scripts/ 目录减半，AI agent 与新成员的探索噪音显著降低
- 消除"报错文案指向不存在脚本"的运维死胡同
- 修正 data-domain.md / project-structure.md 对 `execution_history_service` 的虚假声明

### 负面 / 取舍
- 一次性修复能力不再"开箱即用"，同类问题复发时需先从 git 历史恢复脚本
- `install_scheduler` 类低频 CLI 本轮保留（D 组待确认）；若后续确认无外部依赖可再清理

## 备选方案 (Considered Alternatives)

- 方案 A: 移入 `_archive/` 目录而非删除
  - 否决原因: 归档目录仍会被全文检索命中产生假引用，且与 docs/archive 政策重复
- 方案 B: 仅删零引用 .py，保留归档文档
  - 否决原因: 无活引用的归档文档同样制造检索噪音；git 历史已是更好的归档层

## 相关 ADR

- 关联: [ADR-0012](0012-config-isolation-rule.md)（Config 单一来源——被删脚本多为其历史执行器）

## 实施注意事项

- 分支: `chore/cleanup-dead-code`（自 008-refactoring-workflow-mechanism 基线）
- 门禁基线: backend 207 passed / CostView 284 passed / DataPipeline 217 passed / 前端 vitest 113 passed + build 通过
- 每批独立 commit（B0 .gitignore 修复 → B1 临时件 → B2 一次性脚本 → B3 未接线实现 → B5 前端 → B4 归档文档），批间跑三套 pytest + audit_cross_imports + audit_db_paths + audit_doc_drift
