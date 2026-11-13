# 跨仓契约采用记录（Consumer Adoption Log）

> L2 | 权威：上游契约在本仓库的采用状态、消费者改动与门禁证据 | 不权威：契约正文（见上游 EMSXDataPipeline `docs/spec/contracts/`）

本表只记录**本仓库作为消费方**已接入的上游契约。每接入一条，追加一行；
`adopted` 的收口证据 = 本仓库代码 commit + 消费者门禁结果。契约正文与上下游
状态机的真相源在上游，本文件不复制表结构。

| contract id | class | 上游状态 | 本仓库状态 | 接入 commit | 消费者门禁证据 |
|---|---|---|---|---|---|
| `sqlite.tca_route_summary` | A | `expanded`（上游 `b476836`） | `adopted`（2026-11-13） | `db5baf21` | `pytest CostView/tests -q` → `514 passed`；`pytest backend/api/tests -k contract -q` → `37 passed, 1 skipped, 667 deselected` |

## `sqlite.tca_route_summary` — adv_20d / daily_volatility

- **上游变更**：`CCP-20261112-sqlite.tca_route_summary`（A 类增量）在
  `tca_route_summary` 新增两个可空列：
  - `adv_20d` REAL — 20 交易日平均日成交量（shares），口径同
    `bdib_daily_summary.adv_20d`；
  - `daily_volatility` REAL — 年化历史波动率（百分比，`26.0` = 26%），口径同
    `bdib_daily_summary.daily_volatility`。
- **缺失语义**：两列均可空。当日行情缺失、样本不足或旧 schema 无列时，全链路
  保持 `None` / `NULL`，**禁止 0 填充**；前端显示「—」并在悬停提示
  「行情未就绪」。
- **消费者路径**：
  - 查询：`CostView/src/tca_query_builder.get_tca_route_summaries` 使用
    `SELECT *`，新列自动进入行字典；旧 schema 无列时按未知列容忍，不报错。
  - 接口：`TcaRouteSummary`（`platform_data/contracts/tca_contracts.py`）新增
    两字段；`CostView/api/routers/costview.py::_serialize_route` 原样下发。
  - 展示：`CostView/module/components/TcaOrderTable.tsx`（路由表两列）与
    `AnalysisView.tsx`（Selected Route Detail 两卡）；交易员详情
    `trader_service._routes_payload` 同步下发。
- **契约测试**：
  - `CostView/tests/test_tca_route_summary_contract.py`：临时 SQLite 造
    「新 schema 有列 / 旧 schema 无列 / 新 schema 但 NULL」三种情况，覆盖
    查询、服务映射、API 序列化与 NULL≠0；
  - `backend/api/tests/test_tca_route_summary_contract.py`：跨层形状与
    `None` 序列化镜像（随 `-k contract` 门禁执行）。
- **上游回报**：请上游在 `docs/spec/contracts/HANDOFF.md` 将该契约下游状态置
  `adopted`，并在 `docs/spec/contracts/CHANGELOG.md` 登记本仓库 commit
  `db5baf21` 与上述门禁结果。本仓库按任务约束未修改 EMSXDataPipeline。
