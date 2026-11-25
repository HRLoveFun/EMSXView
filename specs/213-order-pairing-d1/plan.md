# 213 — 订单内配对评估 D1（DL-20）

> 父计划：`specs/057-execution-decision-loop` 的 **DL-20**（3a 口径修正与配对）
> 分支：`213-order-pairing-d1`（worktree `../EMSXView-wt-213-order-pairing-d1`，基于 `origin/main`，含 DL-19 的 211/212）
> 依赖：DL-04（算法族）、DL-05（数据盘点 / D1 候选口径）、DL-12（路由到达价）——均已完成
> 关联规范：`docs/spec/plan-design-principles.md`（P2 三栏 / P4 验收）、`docs/spec/attribution-pitfalls.md`

---

## 1. 问题

当前 CostView 的跨券商比较是**不同订单之间**的横截面比较：市场漂移、个股当日难度、时段差异无法剔除。DL-05 盘点已确认「同一 OrderId、同日、≥2 券商且路由下达时差 ≤5min」的样本存在（`data_inventory.PAIR_MIN_BROKERS=2`、`PAIR_MAX_SPREAD_MINUTES=5.0`），这构成 D1 配对设计的数据基础：

> 同一订单内、同一批次窗口内的多券商路由共享相同的市场与个股冲击（`Algo_TCA.md:567-651`）；组内相对成本可以把共同漂移消掉，只留下券商执行差异。

**本 DL 不改变下单路径**，只新增评估章节与统计口径。

---

## 2. 方案（P2 三栏）

### S1 · 配对分组（新模块 `CostView/src/evaluation/pairing.py`）

- **理论依据**：配对单元必须是「同单、同批、同窗、多券商」；窗口以内生决策时点 `route_as_of_time` 定义（211 已把该列接入环境上下文），不用成交时刻。
- **技术方案**：
  - 常量 `PAIR_MIN_BROKERS = 2`、`PAIR_MAX_SPREAD_MINUTES = 5.0`（与 DL-05 的 `data_inventory` 同值，单测断言两处一致）。
  - `pair_groups(routes, route_times)`：按 `(OrderId, order_as_of_date)` 分组；组内按 `route_as_of_time`（`env_by_route` 的 `start_time`）升序，贪心切分为「跨度 ≤5min」的窗口；只保留**不同 Broker 数 ≥2** 的窗口；组 ID 形如 `"{OrderId}|{date}|{window_start}"`。
  - 时间缺失/不可解析的路由不参与分组；覆盖率按「候选订单 / 总订单、配对组 / 路由、券商数」披露。
- **检验方法**：合成数据：同单 2 券商、时差 1min → 1 组；时差 6min → 0 组；3 券商 → 1 组；缺时间 → 不计入；组 ID 稳定。

### S2 · 相对成本

- **理论依据**：组内共同冲击用**成交额加权均值**吸收；相对成本 = 路由成本 − 组内加权均值（成本语义，越低越好）。
- **技术方案**：
  - 成本列默认 `arrival_cost_bps`（报告主基准，`PRIMARY_BENCHMARK="arrival"`），由报告层显式传入，不在 pairing 内硬编码。
  - 权重 `fill × p_avg`（与 `report_spec.weight_expression` 同源）；权重缺失/≤0 的路由不参与组均值，但仍可计算其相对成本（若成本可得）；组内无有效权重 → 该组跳过并计入排除原因。
  - 输出每路由 `pair_group_id`、`relative_cost_bps`（保留六位），以及组级均值/样本量。
- **检验方法**：合成组两路由成本 5/10bps、权重 1:1 → 相对成本 −2.5/+2.5，组内加权均值 7.5；权重 3:1 → 均值 6.25、相对成本 −1.25/+3.75；权重缺失 → 组跳过并披露。

### S3 · 配对检验与订单固定效应回归

- **理论依据**：配对差值用 Wilcoxon 符号秩（不依赖正态）与符号检验（稳健性）；订单固定效应回归用组内变换吸收订单效应，份额作协变量，估计券商调整效应。
- **技术方案**：
  - `wilcoxon_signed_rank(diffs)` 用 `scipy.stats.wilcoxon(zero_method="wilcox", alternative="two-sided")`；`sign_test(diffs)` 用 `scipy.stats.binomtest`（scipy 已是既有依赖，不新增包）。
  - `broker_pair_tests(groups)`：对每对券商、在每个共同配对组内取相对成本差，样本 ≥10 才出检验；输出统计量、p 值、样本数、差值中位数。
  - `fixed_effects_broker_effects(groups, share_key)`：构 row = (pair_group_id, broker, relative_cost_bps, share)；组内去均值（`relative_cost − group_mean`、`share − group_mean`），再加券商哑变量（留一基准），`numpy.linalg.lstsq` 求 OLS；输出每券商相对基准的系数、标准误、样本量、组数。**不引入 statsmodels**。
  - 份额定义：`RouteShares / Σ组内 RouteShares`（决策时点变量，211 后可用），缺失记 `unknown` 并从回归协变量中剔除（披露）。
- **检验方法**：合成数据注入已知券商效应（A 优于 B 5bps，含噪声）→ ① Wilcoxon 显著且差值中位数为负；② 符号检验同向；③ FE 回归的 B−A 系数 ≈ +5bps（±1bps 容差）且 share 协变量可估；④ 无配对/单组/零方差 → 返回空结果并披露，不抛错。

### S4 · 报告接线与披露

- **理论依据**：评估结论必须可审计：配对覆盖率、排除原因、检验方法、样本量随结果披露。
- **技术方案**：
  - `report.build_evaluation_report` 新增 `"pairing"` 章节（D1），输入 `routes` + `env_by_route`（`start_time` 即 `route_as_of_time`）；不改变既有 `dimensions`/`trend`/`risk`/`market` 章节。
  - 章节 payload：`coverage`（候选订单/配对组/配对路由/券商数/总路由）、`excluded`（缺时间/缺成本/无权重/单券商）、`relative_cost` 分布、`broker_tests`、`fixed_effects`、`pair_group_id` 与 `relative_cost_bps` 的样本行（供 DL-22/DL-23）。
  - `SPEC_VERSION` 升为 **`2026.11.25c`**；治理元数据 `scope` 记录 D1 覆盖率与配对组数。
- **检验方法**：报告 payload 含 `pairing`；覆盖率为 0 时章节可读且不抛错；`governance.spec_version=2026.11.25c`；既有评估章节不变。

---

## 3. 范围锁

- `CostView/src/evaluation/pairing.py`（新增）
- `CostView/src/evaluation/report.py`（新增 section 接线）
- `CostView/src/monitoring/report_spec.py`（版本）
- `CostView/src/tca_query_service.py`（如需要透传/参数；默认不改）
- 测试：`CostView/tests/test_pairing.py`（新增）、`test_evaluation.py`（section/版本）、必要时 `test_tca_query_service.py`
- `specs/057-execution-decision-loop/tasks.md`（DL-20 状态 + 子编号 213）

**不做**：不改下单/路由路径；不新增外部依赖（scipy/numpy 已存在）；不做跨日配对；不做 D2（跨订单/同标的配对，属后续）。

---

## 4. 验收（P4）

1. **合成回收**：已知券商效应可被 Wilcoxon / 符号检验 / FE 回归回收，系数误差 ≤1bps；组内相对成本加权和≈0。
2. **边界**：单券商、超窗、缺时间、缺成本、零权重、全重复券商 → 明确排除并披露，不抛错。
3. **真实数据**：D1 候选覆盖率与 DL-05 的盘点口径一致（同 `PAIR_MIN_BROKERS`/`PAIR_MAX_SPREAD_MINUTES`）；报告中逐项披露。
4. **回归**：`pytest CostView/tests -q`、`pytest backend/api/tests -k contract -q` 全绿；golden 0 指标漂移；`python scripts/doc_check.py` 退出码 0。

---

## 5. 风险

- **样本稀疏**：D1 要求同单同窗多券商；真实覆盖率可能较低。章节必须披露覆盖率，不把稀疏样本当强结论。
- **成本列选择**：默认 arrival；若某券商/路由缺 arrival，该组降级为「无成本」并披露，不换用其他基准（D1 基准冻结）。
- **回归自由度**：单组券商数少时 FE 估计不稳；样本 <10 的券商对不出检验，只出描述统计。

---

## 6. 交付

- 分支 `213-order-pairing-d1`；PR 标题 `feat: 订单内配对评估 D1 (057-DL-20/213)`；PR 描述逐条对照 §4；同一 PR 内把 `tasks.md` DL-20 改为「已完成」并填 213。
