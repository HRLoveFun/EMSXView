# 221 — 信号与规则月度回检（DL-26）

> 父计划：`specs/057-execution-decision-loop` 的 **DL-26**
> 分支：`221-signal-lift`（worktree `../EMSXView-wt-221-signal-lift`，基于 `origin/main`）
> 依赖：DL-14（监控信号）、DL-24（分项得分）、DL-25（辅助模式）—— 均已完成
> 理论依据：每个信号必须自证价值；无增量即下线（`dl-specs.md` DL-26）。

---

## 1. 问题

1. 异常告警（9 条阈值规则）与监控信号已上线，但没有月度回检：**命中告警的路由，成本是否真的更差**、差多少、是否只是规模/市场结构差异，无人回答。
2. 没有「信号 + 规则版本 → lift」归档，规则改阈值后旧结论不可追溯。
3. 缺少可直接用于下线/改版的证据：需要同时给出效应量、可信区间、覆盖率与样本门槛。

---

## 2. 口径（先定清楚再实现）

- **成本**：`arrival_cost_bps`（报告主基准 `PRIMARY_BENCHMARK="arrival"`），正值 = 成本更高；可 `--cost-field` 切换 `pnl_vwap` / `close_cost_bps` / `wagner_is_bps`。
- **标准化**：按交易日做 z 分数 `(cost − 当日均值) / 当日标准差`（当日有效样本 < 5 或标准差为 0 时保留原值并标注），剔除共同市场漂移。
- **控制规模**：按路由名义额 `RouteShares × p_avg × fx_rate`（USD）取全月五分位，与 `Exchange` 组成分层键 `(Exchange, size_bucket)`；层内比较命中 vs 未命中。
- **合并**：复用 `CostView/src/evaluation/stratified.py` 的 `stratified_difference`（层内两侧各 ≥3、样本量加权、层数 <2 退化并披露）。
- **可信区间**：按 `OrderId` 聚类 bootstrap（默认 300 次，固定种子），百分位 95% CI。
- **规则版本**：`ThresholdRules.from_payload` 解析后的完整规则做 SHA-256 指纹 + `SPEC_VERSION`，与月报一起归档。
- **自指规则**：`pnl_vwap_bps`、`intraday_volatility` 的标签本身由成本派生，与成本 lift 机械相关 → 照常输出但标 `cost_derived=true`，不进入 `any_actionable_signal` 汇总。
- **订单级规则**：`order_par_single_gt100` / `route_par_extreme` 需要订单组聚合，v0 不伪造，标 `available=false` 并披露。

---

## 3. 方案

### S1 · 纯计算模块

新增 `CostView/src/evaluation/signal_lift.py`：

- `prepare_routes(routes, *, cost_field)`：成本/名义额清洗、当日 z、五分位分层、`completion_rate` 注入、`RPM` 小写别名、规则命中标签。
- `signal_lift(rows, signal_key, ...)`：单信号分层差 + 聚类 bootstrap CI + 层明细 + 覆盖率。
- `monthly_signal_lift(routes, *, cost_field, rules_payload, ...)`：月度报告（信号字典、`any_actionable_signal`、样本/规则/版本元数据、口径说明）。
- 版本常量 `SIGNAL_LIFT_VERSION = "signal-lift-v1"`。

### S2 · 月度 CLI 与归档

新增 `scripts/qa/signal_lift_report.py`：

- 只读打开 `Config.FILL_BDIB_DB`（`--db` 覆盖），按 `order_as_of_date` 取月；
- `--month YYYYMM` 或 `--start/--end`；`--rules rules.json`（与异常阈值 API 同 payload）；
- 输出 `logs/qa/signal_lift/signal_lift_<start>_<end>.json`，打印各信号 `std_delta / CI / coverage / n_hit`。

### S3 · 测试

`CostView/tests/test_signal_lift.py`：

1. 合成已知 lift 可被回收（+5 bps，CI 不含 0）；
2. 规模混杂：命中集中在高成本大单时，整体差为正、分层差归零；
3. 成本缺失剔除且覆盖率披露；
4. 自指规则标记与 `any_actionable_signal` 排除；
5. 规则指纹稳定、改阈值后变化；
6. 订单级规则标 `available=false`。

### S4 · 文档

`specs/057-execution-decision-loop/tasks.md` DL-26 状态；`scripts/README.md` 脚本清单；`CostView/README.md` 增加回检入口（如模块表已有脚本章节则追加一行）。

---

## 4. 范围锁

- `CostView/src/evaluation/signal_lift.py`（新增）
- `scripts/qa/signal_lift_report.py`（新增）
- `CostView/tests/test_signal_lift.py`（新增）
- `specs/057-execution-decision-loop/tasks.md`、`scripts/README.md`、`CostView/README.md`
- `specs/221-signal-lift/plan.md`

**不做**：不改异常阈值默认值；不改前端；不接 API 端点（月度 CLI + JSON 归档即可）；不做订单级规则聚合（v0 明确不可得）；不做自动下线（只输出证据）。

---

## 5. 验收（P4）

1. 月报可生成并归档，包含每个信号的效应量、95% CI、覆盖率、命中/未命中样本量与规则指纹；
2. 合成数据可回收已知效应；规模混杂构造下分层差显著小于整体差；
3. 缺失成本不补 0，覆盖率与不可得规则明确披露；
4. `pytest CostView/tests -q`、`python scripts/doc_check.py`、边界审计全绿。

---

## 6. 风险

- **自指/后验偏差**：成本派生规则天然与成本相关，已标记并排除出汇总；其余规则用决策前/执行中指标，避免用结果定义信号。
- **规模与市场混杂**：分层键含 `Exchange` + 名义额五分位；仍可能有未观测混杂，报告只给关联强度，不声称因果。
- **小样本**：层内两侧 <3 的层剔除并披露覆盖率；CI 在样本不足时可能跨 0，结论按「无证据」处理。
- **月内制度变化**：按日标准化削弱但不消除；规则指纹保证改阈值后的结论可追溯。
