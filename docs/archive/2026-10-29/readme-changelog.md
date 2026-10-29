# README 变更摘要（模块级，2026-08-26 ~ 2026-10-20）

> L3 | 权威：2026-08-26 ~ 2026-10-20 期间模块级变更的追溯记录 | 不权威：当前现状（见 `docs/report-*`、`docs/spec/`）

> 归档于 2026-10-29；原位置 `README.md` §11。README 只留人看的概览，变更追溯改由 ADR + 本文承载。

| 日期 | 变更 | 影响模块 | 依据 |

|------|------|----------|------|

| 2026-08-26 | 清理一次性历史件与 legacy 前端（handoff/migration-baseline/architecture-analysis-report、`CostView/frontend/` 等）；CostView 前端入口此后进一步迁至仓库根级 `CostView/module/` | CostView（前端入口收敛，见 §6）、docs | [ADR-0014](./docs/spec/adr/0014-dead-code-cleanup.md) |

| 2026-09-02 | `CostView/data/` 历史数据迁移至 `${EMSXVIEW_DATA_DIR}` | CostView、data_access | 数据根唯一来源 `data_access/config.py` |

| 2026-09-11 | README 全面审计重写：成熟度分级、能力"已实现/规划中"二分、数据流时序语义、数据规模实测、降级路径、CLI 失效标注 | 全部模块 | 静态代码审计 + 数据目录实测 |

| 2026-09-15 | CostView 冗余清理（删除 FillFetch/Bloomberg 遗产文件与 `requirements.txt`，`pandas` 补入 `pyproject.toml`）；文档去漂移（测试计数、端点表、行号重锚） | CostView、README、docs/spec | 全仓 grep 零引用 + pytest 实测 |

| 2026-09-16 | 删除本地留证目录 `CostView/data.migrated.202609022339/`（约 145 GB），完成 010-extract-pipeline TODO-1 | CostView、docs/spec | 数据根实测一致 |

| 2026-10-20 | **文档合并**：`README.md` 的项目总览与 `CODEBUDDY.md` 的 Agent 规范合并进 `AGENTS.md`（`CODEBUDDY.md` 合并后删除，`AGENTS.md` 成为唯一规范源）；README 精简为人类首页并刷新事实（10 个核心路由、CostView 14 端点、`TCA_ORDER_AGG_ENABLED`/`TCA_EVAL_ENABLED` 默认开启、MarketView 已有测试目录、Redis handoff 三通道 7 天 TTL、golden 快照入库、数据合计 127.8 GB、Compose 6 服务、测试计数 295/305/25） | 全仓库文档 | 静态代码核对 + 端点枚举 + `${EMSXVIEW_DATA_DIR}` 实测 + 测试函数计数 |



---



**Last updated**: 2026-10-20

**Last verified**: 2026-10-20（验证方式：静态代码审计 + 端点清单提取 + `${EMSXVIEW_DATA_DIR}` 文件大小实测 + 测试函数计数。**未做运行时验证**——服务启动、端点实际响应与查询延迟未在本审计中测量。）

