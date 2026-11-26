# 230 执行简报（Execution Brief）

> L3 | 权威：执行简报的范围、口径与边界 | 不权威：TCA 报告口径缺口（见 `docs/report-tca-known-limitations.md`）

## 1. 目标

在 CostView 内新增「执行简报」，供交易员 / 交易主管按 **每日 / 每周 / 每月 /
每季 / 每年 / 自定义区间** 查看订单级执行摘要：

- 委托与执行概览：订单数、标的数、委托股数/金额、成交股数/金额、买卖拆分；
- 完成状态：完全成交 / 部分成交 / 零成交 / 超成交的笔数与金额占比；
- 成本：加权 arrival / IS / VWAP、延迟 / 交易 / 机会成本、未成交金额缺口；
- 待处理订单：成本最不利 / 未成交金额最大 / 机会成本最不利 Top N；
- 异常摘要与数据缺口。

与既有产物分层：

| 产物 | 颗粒度 | 用途 |
| --- | --- | --- |
| `Report`（TCA 报告） | route / 期间 / 全台 | 审计、排名、可复现归档 |
| `Trader`（复盘台） | order / 分页明细 / 单笔 | 逐单复盘与 peer 分位 |
| `Brief`（本计划） | order / 期间聚合 | 每日执行管理与投资经理沟通 |

## 2. 口径

- 作用域：默认全部市场；`exchange` 显式过滤。BDIB 白名单外市场的成本指标可能为
  NULL，按「不可得」展示，不以 0 代替。
- 委托金额 = `Σ(RouteShares × 价格回退链 × fx)`；价格回退链与报告同源
  （`report_measure.UNFILLED_PRICE_FALLBACKS`）。
- 成交金额 = `Σ(fill × p_avg × fx)`；权重口径为成交额加权（`fill × p_avg`）。
- 完成率 = `Σfill / ΣRouteShares`；分桶按订单级聚合后的完成率。
- 成本符号：负 = 不利（`trader_metrics.adverse_bps` 同一约定）。
- 机会成本沿用上游有符号原值；待处理订单按**绝对规模**排序，不改变符号，也不套用
  arrival/IS 的红绿语义（实测 BUY/SELL 的正负混合，无法从现有文档稳定反推方向）。
- 多路由订单维度取成交股数最大路由（dominant route）。
- 异常：复用 `trader_metrics.compute_anomaly_summary` + `anomaly_query` 的同一套
  阈值引擎；订单级仅评估 `pnl_vwap_bps` / `fill_pct` / `overfill_pct` /
  `volume_pct_adv20` 四条，其余规则在 Report 的路由级明细中。

## 3. 数据边界（必须显式披露）

| 项 | 状态 | 原因 |
| --- | --- | --- |
| 组合 / 账户维度 | 未覆盖 | `tca_route_summary` 无 Portfolio / Account 列 |
| TIF | 未覆盖 | 无 TimeInForce 列 |
| 撤销 / 拒单状态 | 未覆盖 | 汇总表只含已路由订单，状态在 EMSX / 运营库 |
| 未成交原因分类 | 未覆盖 | 无订单状态与算法暂停事件；不做无证据的事后推断 |
| 有效价差 | 未覆盖 | 无报价级数据（K2） |
| 显性费用 / 返佣 / 税费 | 未覆盖 | 价格偏离口径（K1） |
| 订单级异常规则覆盖 | 部分覆盖 | 仅 4 条订单级可评估规则 |
| USD 换算 | 部分覆盖 | 非 USD 缺汇率时不计入 USD 合计，条数随附披露 |

## 4. 实现

- 服务：`CostView/src/execution_brief.py`
- 路由：`CostView/api/routers/brief.py`（`GET /api/tca/brief`）
- 桥接：`CostView/api/main.py` + `backend/api/routers/costview.py`
- 前端：`CostView/module/components/brief/`，CostView 页签 `Brief`
- 时间范围：复用 `CostView/src/monitoring/time_range.py`（与报告/CLI 同一套 last 预设）

## 5. 验收

- `python -m pytest CostView/tests/test_execution_brief.py -q` 全绿；
- `python -m pytest CostView/tests/test_trader_*.py CostView/tests/test_monitoring.py -q` 无回归；
- `npm run typecheck` 通过；新增前端测试通过；
- 手动：`GET /api/tca/brief?last=day` 返回 `success=true`，期间、概览、买卖拆分、
  完成分桶、数据缺口齐全；`last=custom` 返回 422。

## 6. 后续（不在本批）

- 组合 / 账户维度（需上游管道补字段）；
- 未成交原因分类（需订单状态与算法暂停事件，且须以「诊断」而非「原因」表述）；
- 次日处理计划（需运营库轻量标注表或 `routing_decisions` 对接）；
- 操作 / 系统事件（拒单、延迟、撤单失败）接入；
- 有效价差与显性费用（K1/K2）。
