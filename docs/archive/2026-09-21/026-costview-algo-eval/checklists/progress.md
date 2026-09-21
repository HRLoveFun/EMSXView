# 026 进度与检查点

> **特性**：`026-costview-algo-eval`
> **计划**：[`plan.md`](../plan.md)　**证据基线**：[`research.md`](../research.md)
> **维护约定**：每完成一项更新状态与日期；遗留项记录在本文件末尾，计划关闭时转记 `docs/open-todos.md`。

## 状态总览

| 阶段 | 内容 | 状态 | 依赖 | 对应 PR |
|---|---|---|---|---|
| 计划编制 | `plan.md` + `research.md` + 本文件 | ✅ 已交付并归档 | — | #68 |
| 阶段一 | 周度聚合与分市场深化 | ✅ 已交付 | 无 | #68 |
| 阶段二 | 执行环境变量精确化 | ✅ 已交付 | 无硬依赖（与阶段一可并行） | #69 |
| 阶段三 | 科学方法评估层 | ✅ 已交付（模块 + 端点 + 前端视图） | 阶段二 L1（**已具备**） | #70（模块与口径）/ #71（端点 / 门控 / 前端视图） |

> **回写说明（2026-09-21）**：本文件的 Checkpoint 勾选项在阶段二 / 三实施时未同步回写，
> 归档（PR #72）后一次性按**实际交付情况**补齐。回写原则：
> ① 每项勾选都附**具体测试用例**作为依据，不凭印象勾；
> ② **未覆盖项如实标注为未勾选**并转记待办，不以补勾掩盖缺口。

---

## 计划编制阶段

- [x] 现状差距评估（四维度判定 + 证据索引）
- [x] 建立 worktree 与分支 `026-costview-algo-eval`
- [x] `research.md` 落位（证据基线 + 阶段二探测预研结论）
- [x] `plan.md` 落位（总纲 / 范围 / 三阶段详设 / 门控 / 验收矩阵 / 风险 / 不做）
- [x] `checklists/progress.md` 落位（本文件）
- [x] `docs/open-todos.md` 登记在途状态（T14）
- [x] 计划设计定点评审（code-review skill；5 项发现已修：引用路径 / 锚点 / DP-2-4 / 导出护栏）
- [x] 提交并推送分支（`197c812`）

---

## 阶段一：周度聚合与分市场深化

### 开工前（Checkpoint 1-A）

- [x] Q1-1：SQLite 版本与 `strftime` 是否支持 ISO 周格式符 `%G` / `%V` —— 结论：**3.45.3，不支持**（`%G-%V` 返回 `None`；`%Y-%W` 会把跨年周拆成 `2025-52` / `2026-00`），选定路线：**A′ 纯 SQL 算术**（2026-09-21）
- [x] Q1-2：`order_as_of_date` 实际格式与空值情况 —— 结论：**全部 8 位 `YYYYMMDD`，无 NULL / 空串；173,672 行，范围 `20250926` ~ `20260918`**（2026-09-21）
- [x] Q1-3：报告区间内跨年周分布 —— 结论：**存在跨年周，`2025-12-29` ~ `2026-01-04` 同属 `2026-W01`**（2026-09-21）

### 实施

- [x] `report_measure.py` 新增期间键 / 粒度映射（口径单点）（2026-09-21）
- [x] `report_aggregator.py` 走势 / 分市场金额趋势支持粒度（2026-09-21）
      ※ **有意偏差**：市场金额**排名**为 `GROUP BY Exchange`（无时间维度），故无需粒度 ——
        计划 §3.2 所列「市场排名支持粒度」经实现核查后判定为不适用
- [x] 分市场 × 周度交叉（`granularity=week` 下的分市场金额趋势即此视图，不另造查询）（2026-09-21）
- [x] `metric_coverage.py` 分组支持粒度（2026-09-21）
- [x] API Query 参数透传（report-summary / metric-coverage / export-html 三端点 + 缓存 key）（2026-09-21）
- [x] 前端粒度切换控件（ReportView + MonitoringView；`Granularity` 类型 + localStorage 脏值兜底）（2026-09-21）
- [x] `report_spec.py` 口径声明 + `SPEC_VERSION` bump（`2026.09.5` → `2026.09.6`）（2026-09-21）
- [x] 三处口径文档同步（`report_spec` / `report-tca-known-limitations` 第十二轮 / ADR-0018 §10.6）（2026-09-21）

### 合入前（Checkpoint 1-B）

- [x] 跨年周 / 空周 / 单日周用例通过（`TestGranularityPeriodKeys` 10 条；后端 **230 passed**）
- [x] `granularity="day"` 产出与改动前**逐字节等价**（`period_key_expr("day")` 恒等返回原始列；既有 219 条用例零失败）
- [x] 分市场交叉金额守恒（用例断言各分组之和 = 4 × 900 × 150）
- [x] `EXPLAIN QUERY PLAN` 命中索引（`idx_trs_date` 生效；week 983ms / day 1181ms / month 181ms，**无退化**）
- [x] 周键 SQL 表达式无第二处定义（静态检查：`weekday 1` / `strftime('%Y'` 仅命中 `report_measure.py`）
- [x] 全量 `pytest CostView/tests/` 通过（**230 passed**）
- [x] 前端 vitest 通过（**188 passed**，含新增粒度用例）+ `tsc -b` 通过 + `lint:modules` 通过

---

## 阶段二：执行环境变量精确化

### 开工前（Checkpoint 2-A）

- [x] Q2-1（**阻塞性**）：`fill_bdib.mkt_timestamp` 实际格式 —— 结论：**全部 8 字符 `HH:MM:SS` 纯时间**（6,680,277 行、无 NULL）；计划担心的「全时间戳致静默取到年份前两位」**不成立**（2026-09-21）
- [x] Q2-2：`bdib_daily_summary` 覆盖率 —— 结论：**`adv_20d` 99.39% / `daily_volatility` 99.94%**（217,406 行，`20250915`~`20260907`）；`intraday_volatility` 仅 38.7% → 不作主口径（2026-09-21）
- [x] Q2-3：`fill_bdib` 按路由数据密度 —— 结论：**start_time 可得率 100%**（173,685/173,685）；时段分布 close 106,939 / open 35,909 / mid 30,837（2026-09-21）
- [x] Q2-4（**阻塞性**）：两表 `mkt_timestamp` 是否异格式 —— 结论：**同格式**（均 8 字符纯时间）；跨仓项 **U-2 不触发**（2026-09-21）
- [x] DP-2-1 跨库获取路径确认（选定 A：经 `ConnectionManager` 只读 + 应用层 join；不使用 SQL ATTACH）
- [x] DP-2-2 `liquidity_adv20` 口径变更确认（`fill / adv_20d`）
- [x] DP-2-3 `volatility` 口径变更确认（真实 `daily_volatility`，消除循环论证）

### 实施

- [x] `env_context.py` 新增（`RouteEnvContext` + 派生单点 + 三级降级链 + 可得率披露）（2026-09-21）
- [x] `cohort_key_and_label` / `aggregate_cohorts` 增设可选 `env` / `env_by_route` 参数（DP-2-4，默认 `None` 回退代理）（2026-09-21）
- [x] `monitoring/__init__.py` 同步模块职责清单 docstring 与导出登记（`TestPackageExports` 护栏）（2026-09-21）
- [x] `cohort_key_and_label` 三分支改真实字段（2026-09-21）
- [x] `bucket_time_of_day` 时间戳形态归一化 —— 改由 `env_context.normalize_start_time` 承接，分桶函数保持纯净（2026-09-21）
- [x] `bucket_liquidity` 阈值按 ADV 比率重定 —— **核查后无需改**：其参数名与标签本就是 `volume_pct_adv20`，现状传 `par_rate` 才是口径漂移；改用真实 ADV 占比后阈值语义自然正确（2026-09-21）
- [x] 记分卡装配注入环境上下文（`tca_query_service._build_env_context`；**仅环境 cohort 取数**，非环境 cohort 零额外查询）（2026-09-21）
- [x] 降级标注贯通 API / 前端 —— 后端 payload（`scorecard.filters.env_coverage`）+ 前端 ScorecardView 报告头展示可得率（2026-09-21）
      ※ **无需 HTML 侧改动**：Scorecard 不进 HTML 报告渲染器（`tca_report_html.py` 只渲染 Report 聚合）；CSV 导出保留现状
- [x] `report_spec.py` 口径声明 + `SPEC_VERSION` bump（`2026.09.6` → `2026.09.7`）（2026-09-21）
- [x] 三处口径文档同步（`report_spec` / `report-tca-known-limitations` 第十三轮 / ADR-0018 §10.7）（2026-09-21）

### 合入前（Checkpoint 2-B）

- [x] 三 cohort 真值抽验（≥3 条路由）一致 —— `test_env_context.TestBuildRouteEnvContext.test_joins_start_time_and_daily_env`（fixture 库比对 join 真值，覆盖 `start_time` / `adv_20d` / `daily_volatility` 三列）
- [x] 双形态时间戳解析回归通过 —— `TestNormalizeStartTime` 3 条（`HH:MM:SS` 原样保留 / 全时间戳取尾 / 空值与 None）；Q2-1 实测现库仅 `HH:MM:SS`，兼容分支为防御性保留
- [x] `volatility` cohort 不再引用 `pnl_vwap`（静态检查）—— `TestRealEnvCohorts.test_volatility_prefers_real_value`
- [x] 三类降级场景标注用例通过 —— `test_unknown_ticker_degrades_per_dimension`（缺 ticker）/ `test_missing_sources_return_empty`（缺源库）/ `test_time_of_day_falls_back_to_unknown`（缺时间戳）
- [x] 各 cohort 覆盖率披露正确 —— `TestAggregateCohortsWithEnv.test_env_coverage_disclosed`
- [x] 全量 `pytest CostView/tests/` + 前端 vitest 通过（2026-09-21，随 PR #69 合入）

---

## 阶段三：科学方法评估层

### 开工前（Checkpoint 3-A，阻塞）

- [x] `scipy` 可安装性验证 —— 结论：**scipy 1.15.3 / numpy 2.3.0 可用**，`ttest_ind` / `ks_2samp` / `chi2_contingency` / `linregress` 齐备（2026-09-21）
- [x] DP-3-1 依赖决策确认 + 两处显式声明位置确认 —— 选定 A（引入 `scipy>=1.11`）；`pyproject.toml` 声明，`api/requirements.txt` 加注释指向（避免两处漂移）；**不引入 statsmodels**（2026-09-21）
- [x] DP-3-2 可比性判定强制位置确认（服务端）—— `assess_comparability` 返回结构化判定，不可比时不输出比较数值（2026-09-21）
- [x] DP-3-3 基准参数不可默认确认 —— `evaluation_metadata(benchmark=…)` 无默认值，缺失即 `ValueError`（2026-09-21）

### 实施

- [x] `evaluation/__init__.py`（`__all__` + 导出护栏测试，对齐 `monitoring` 包约定）（2026-09-21）
- [x] `evaluation/comparability.py`（分层 + 可比性判定；TVD 失衡度量；环境维度复用 `tca_utils` 分桶单点）（2026-09-21）
- [x] `evaluation/stats_tests.py`（t / KS / χ² + bootstrap 可信区间 + 多重比较校正）（2026-09-21）
- [x] `evaluation/power.py`（正态近似功效 / MDE，不引入 statsmodels）（2026-09-21）
- [x] `evaluation/cost_model.py`（幂律冲击函数估计，域外不外推、不作事前预测）（2026-09-21）
- [x] `evaluation/governance.py`（版本锁定 / 基准冻结 / 数据血缘 / 降级披露；基准不可默认）（2026-09-21）
- [x] 新端点 `POST /api/tca/evaluation/compare` + `TCA_EVAL_ENABLED` 门控（2026-09-21）
- [x] `/api/tca/capabilities` 增列 `evaluation` 能力位（对齐 `order_level_tca` 范式）（2026-09-21）
- [x] 编排接入：`TcaQueryService.build_evaluation_comparison`；抽出 `_collect_routes` 与 scorecard 共用取数范式（避免两处分页循环漂移）（2026-09-21）
- [x] `data_access/config.py` 新增 `TCA_EVAL_ENABLED`（默认开启；关闭即显式不可用，不回退未校验比较）（2026-09-21）
- [x] `scipy` 依赖声明 **三处协同**（2026-09-21）：`pyproject.toml` 包级声明 + `api/requirements.txt` 注释指向 + **`.github/workflows/boundary.yml` 补装清单** —— CI 以 `--no-deps` 安装 CostView，pyproject 声明在 CI **不生效**；首次提交漏改该处，由后端测试 `ModuleNotFoundError: scipy` 暴露并修正
- [x] 前端评估视图（`EvaluationView.tsx` + `CostViewModule` 第 7 个 Tab）：不可比时渲染判定与原因而非空表；未校正与校正后 p 值并列；功效给出最小可检测效应（2026-09-21）
- [x] 共享筛选转换抽到 `lib/filters.ts`（消除 `react-refresh/only-export-components` 警告）（2026-09-21）
- [x] `report_spec.py` 评估口径声明 + `SPEC_VERSION` bump（`2026.09.7` → `2026.09.8`）（2026-09-21）
- [x] 三处口径文档同步（`report_spec` / `report-tca-known-limitations` 第十四轮 / ADR-0018 §10.8；**不需新建 ADR** —— 归入既有 0018 口径治理线）（2026-09-21）

### 合入前（Checkpoint 3-B / 3-C）

- [x] 数值对照通过 —— `TestStatsTests.test_t_test_detects_clear_difference` / `test_ks_and_chi2_available` / `test_small_samples_declare_unusable`
      ※ **实现偏差**：DP-3-1 选定直接使用 `scipy.stats` 而非自实现，故不存在「独立实现对照」对象，对照转为验证 scipy 语义下的行为契约（检出明显差异 / 小样本声明不可用）
- [x] 可信区间覆盖率通过 —— `test_bootstrap_ci_brackets_zero_for_same_distribution`（同分布时 CI 跨越 0，即「不该显著时不显著」）+ `test_bootstrap_ci_requires_two_samples_each`
      ※ **实现偏差**：以「同分布判定」替代计划所列「全量蒙特卡洛覆盖率模拟」（成本更低且能捕获同源错误）
- [x] 可比性拒绝用例通过（不返回数值）—— `TestComparability.test_undersized_group_is_not_comparable` / `test_imbalanced_dimension_blocks_comparison`，及编排层 `TestEvaluationComparisonOrchestration.test_incomparable_returns_no_numbers`（断言 `comparisons == []`）
- [x] 基准强制用例通过 —— `TestGovernance.test_benchmark_is_mandatory` + 请求模型 `TestEvaluationRequestModel.test_benchmark_required_by_schema`（schema 层即拒绝）
- [x] 多重比较校正生效 —— `test_adjust_pvalues_bh_and_bonferroni`；编排层断言每对同时带 `p_value` 与 `p_value_adjusted`
- [x] 功效与理论公式对照通过 —— `test_required_sample_matches_closed_form` / `test_achieved_power_is_inverse_of_required` / `test_minimum_detectable_effect_round_trip`（三向自洽）
- [x] 冲击模型参数恢复通过 —— `TestCostModel.test_recovers_known_parameters` / `test_no_extrapolation_outside_domain` / `test_payload_discloses_no_forecast_note`
- [ ] **门控关闭 / 无 scipy 时降级可见 —— 未加自动化用例（如实标注，不补勾）**
      现状：`TCA_EVAL_ENABLED=0` 的早返回分支位于 `CostView/api/routers/costview.py` 的 `evaluation_compare` 内，**无端点级测试覆盖**；「无 scipy」场景依赖 import 期失败，亦无用例。已转记 `docs/open-todos.md` T16。
- [x] 既有 Report / Monitoring 产出零变化 —— 全量 291 passed（含既有 scope / 加权 / 零填充 / 排行门槛 / 图表轴策略等护栏）；`granularity="day"` 与改动前逐字节等价（`period_key_expr("day")` 恒等返回原始列）
- [x] 全量 `pytest CostView/tests/` + 前端 vitest 通过（2026-09-21，**291 + 188**；随 PR #70 / #71 合入，CI 8/8 全绿）

---

## 遗留项登记

> 计划关闭时，本区未收尾项转记 `docs/open-todos.md`。

| # | 事项 | 来源 | 状态 | 备注 |
|---|---|---|---|---|
| 026-L1 | 上游可选物化：`adv_20d` / `daily_volatility` 落 `tca_route_summary` 列 | `plan.md` §6 U-1 | ⏳ 待触发 | 仅当阶段二 L1 覆盖率或查询开销不可接受时启用（实测覆盖率 99.39% / 99.94%，未触发）；已转记 `docs/open-todos.md` **T15** |
| 026-L2 | `fill_bdib` 与 `raw_bdib` 的 `mkt_timestamp` 格式口径统一 | `plan.md` §6 U-2 | ✅ **不触发** | Q2-4 实测两表**同格式**（均 8 字符纯时间），无上游改动需求；已转记 **T15**（标注不触发） |
| 026-L3 | 评估端点的门控降级分支（`TCA_EVAL_ENABLED=0` / 无 scipy）缺自动化用例 | 本文件 Checkpoint 3-C 回写 | ⏳ | 2026-09-21 回写时如实标注；已转记 **T16** |

---

## 勘误记录

> `research.md` / `plan.md` 中与**代码核查或实测**不符的断言在此登记（一律以代码与实测为准）。

| # | 断言位置 | 原断言 | 核查结论 | 处置 |
|---|---|---|---|---|
| E1 | `plan.md` §3.2 | 「市场金额**排名**支持粒度」 | **不适用**：排名查询无时间维度（详见下方专项说明） | 仅「趋势」与「覆盖率」加粒度；排名保持区间聚合语义 |
| E2 | `plan.md` §4.4 | 「`bucket_liquidity` 阈值按 ADV 比率重定」 | **无需改**：该函数参数名与标签本就是 `volume_pct_adv20`，现状传 `par_rate` 才是口径漂移源；换真实 ADV 占比后阈值语义自然正确 | 不改阈值，只改数据来源 |
| E3 | `plan.md` §4.4 | 「`tca_report_html.py` / `report_aggregator.py` 输出降级标注」 | **一半不适用**：`tca_report_html.py` 只渲染 Report 聚合，Scorecard **不进** HTML 报告 | 降级标注落在 API payload + 前端 ScorecardView；CSV 保留现状 |
| E4 | `plan.md` §5.9 | 「可能新增 ADR 留痕（DP-3-1 依赖决策）」 | **未新建**：评估层口径归入既有 ADR-0018 治理线 | 记于 ADR-0018 §10.8 / §10.9 |
| E5 | `plan.md` §6 U-2 | 「两表 `mkt_timestamp` 格式口径统一（跨仓协作项）」 | **不触发**：Q2-4 实测两表同格式 | 跨仓项降为不触发；本侧归一化仅为防御性保留 |
| E6 | `plan.md` §4.1.2 / R-1 | 「`mkt_timestamp` 可能为 `YYYYMMDD HH:MM:SS` 全时间戳，致 `bucket_time_of_day` 静默取到年份前两位」（列为**阻塞性**风险） | **不成立**：Q2-1 实测 6,680,277 行全部为 8 字符 `HH:MM:SS`，无 NULL | 阻塞性风险解除；`normalize_start_time` 双形态兼容保留为防御 |
| E7 | `plan.md` §5.10 | 「可信区间覆盖率**蒙特卡洛**」 | **降级实现**：改为「同分布时 CI 需跨越 0」的判定式用例 | 已在 Checkpoint 3-B 处标注 |

### E1 专项说明：「市场金额排名支持粒度」为何不适用

**原断言的来源**：计划 §3.2 在阶段一改动落点中，把「市场金额排名」与「分市场金额趋势」并列为「需支持粒度」的两处。

**代码核查结论**：这两个查询的时间语义**根本不同**：

| | `_query_market_notional_ranking` | `_query_market_notional_trend` |
|---|---|---|
| 位置 | `CostView/src/monitoring/report_aggregator.py:404-437` | 同文件 `:439-464` |
| 分组 | `GROUP BY Exchange`（`:424`） | `GROUP BY {period_expr}, Exchange`（`:459`） |
| SELECT 时间列 | **无** | `{period_expr} AS date`（`:454`） |
| ORDER BY | 按有效成交额降序（`:425`） | 按期间升序（`:460`） |
| 语义 | **整个报告区间的单一汇总** | **时间序列**（每个期间一行） |

排名查询的 SELECT / GROUP BY / ORDER BY **三处都不含时间列** —— 报告期是一个已由 `where` 收窄的输入参数，时间在聚合前就已被「消耗」掉，粒度参数**没有可作用的位置**。

**为什么强行加会错**：要让排名「按周」，必须同时改变语义 —— 从「区间排名」变成「某一周的排名」，于是需要额外回答「看哪一周」。这不是加一个 `granularity` 参数，而是新增一个「期间选择器 + 期间内排名」的组件，属于范围扩张而非粒度化。

**所需能力其实已经存在**：`granularity=week` 下的**趋势**查询返回的就是 `(period, Exchange, notional_usd)` 的完整交叉数据 —— 前端要「按周看市场排名」，在趋势数据上按 `period` 切片后排序即可，**无需第二个查询**。这也正是计划 §3.2 里「分市场 × 周度交叉视图」的落点（见阶段一实施记录）。

**同类的还有一处**：`_query_market_overview`（`report_aggregator.py:385-402`，`GROUP BY Exchange` 于 `:390`）同样是区间聚合，故一并保持无粒度。

**结论**：这是**计划断言与代码语义不符**，不是实现缩水 —— 排名不需要粒度，趋势已提供按期间的完整数据。
