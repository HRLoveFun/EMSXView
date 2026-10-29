# 已失效声明（原 `AGENTS.md` §14）

> L3 | 权威：「曾经成立、现已被推翻」的说法清单，用于判定旧文档/旧注释能否再引用 | 不权威：当前现状（见 `README.md` 与 `docs/spec/`）

> 归档于 2026-10-29；原位置 `AGENTS.md` §14。下沉原因：L0 预算 120 行，changelog 型内容不再常驻入口。**发现旧文出现下表条目时，按「现状」列改正或删除，并在本表追加新行。**

以下说法曾出现在旧文档或代码注释中，现已不成立，**不得**写回文档或代码注释：

| 失效项 | 现状 |
|---|---|
| `EMSXVIEW_MERGE_MODULES` 环境变量 / 「所有模块合并进单进程」 | 无消费点；可选模块用 `EMSXVIEW_OPTIONAL_MODULES`，且仅 CostView 可桥接（MarketView 无桥接路径） |
| `VITE_USE_MOCK` | 无消费点；mock 行为由 `VITE_API_URL` 是否为空决定 |
| `CORS_ORIGINS` | 实际变量名是 `ALLOWED_ORIGINS` |
| `tca_fallback.py`（独立降级模块） | 已删除；职责由各查询层内置空结果降级取代 |
| `CostView/requirements.txt`、`CostView/frontend/` | 分别于 2026-09-15、2026-08-26 删除；依赖见 `CostView/pyproject.toml` + `CostView/api/requirements.txt` |
| `frontend/src/modules/<module>/` | 业务模块已迁至仓库根级 `<Module>/module/`（`frontend/src/` 只放壳层与共享层） |
| `plans/` 目录 | 已不存在；计划统一放 `specs/<feature-id>/`，完成即归档至 `docs/archive/YYYY-MM-DD/` |
| `DataPipeline/`（本仓内目录 / import） | 已迁独立仓库 EMSXDataPipeline，本仓库禁止 import |
| 「Redis handoff 后端未实现 TTL」 | 已修：三通道均设 7 天 TTL（与内存后端 `_HANDOFF_TTL` 对齐） |
| 「黄金样本回归需外部冻结快照」 | 已修：`CostView/tests/golden/snapshot/fill_bdib.db` 随基线入库，`EMSXVIEW_GOLDEN_DATA_DIR` 仅为可选覆盖 |
| 「CostView 13 个端点」/「`TCA_ORDER_AGG_ENABLED` 默认关闭」 | 现状为 14 个端点，`TCA_ORDER_AGG_ENABLED`、`TCA_EVAL_ENABLED` 默认开启（置 `0` 显式降级） |
| 「MarketView 无自身测试目录」 | `MarketView/tests/` 已存在 |
| 「MarketView 3 个端点 / 1 个测试文件 / Scaffold」 | 现状 8 个端点；2026-10-27 节点一交付后升 **Beta**（证据与已知限制见 `docs/milestone-1-pretrade-board.md`） |
| 「后端 9 个核心路由 / 约 180 个测试函数」 | 现状 11 个核心路由（含 `authorizations`、`interval_series`）；用例数不写死，跑 `cd backend/api && python -m pytest tests/ -q` |
| 「MarketView 只是盘前视图 / ExecutionView 只做订单管理」 | 现状：MarketView = **市场走势视图**（股票池检查、意图/难度/成本提示，盘前+盘中，只读、不碰下单路径）；ExecutionView = **交易执行视图**（意图获取、下单/改单、执行区间量价）。定义见 `docs/spec/project-structure.md` §1 模块使命 |
| `.github/knowledge/architecture-decisions.md`、`user-needs.md`、`iteration-log.md` | 均已下线；ADR 见 `docs/spec/adr/`，索引 `docs/spec/memory.md` |
| 「文档清单见 docs/index.md / README §10」 | 2026-10-29 起清单只有一处：`AGENTS.md` 文档地图；其余位置改指针 |
| 「测试计数 45 文件 / 295 函数」「CostView 10 文件 / 305」「MarketView 8 文件 / 74 例」 | 2026-10-29 起文档不写用例数（会漂移），只给可复跑命令；历史数字以本表记录 |
