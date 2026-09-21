# 026 现状基线与证据索引

> **特性**：`026-costview-algo-eval`（CostView 券商算法执行质量评估体系）
> **定位**：`plan.md` 的证据支撑文档。每条现状断言携带 `文件:行号`，供执行阶段抽查复核，避免重复论证。
> **证据来源**：仓库内只读探索（2026-09-21，基线提交 `8c8aeb0`），全程无任何写入。
> **复核要求**：若发现某条断言与当前代码不符，以代码为准并在此文件登记勘误，不得据此直接改方案。

---

## 1. 结论速览

| 目标维度 | 判定 | 一句话差距 |
|---|---|---|
| 按周度频率 | 🟡 部分实现 | 「周」只是查询窗口，未成为聚合维度；所有分组锚在 `order_as_of_date` 日粒度 |
| 分市场 | 🟢 已实现（分组/展示）/ 🔴 未实现（可比性） | Exchange 已是一等维度并被作用域统一；缺市场中性化 / 跨市场可比性对齐 |
| 控制执行环境变量 | 🟡 部分实现（代理式） | 环境分桶全为代理变量（时段恒 `unknown`、ADV 用参与率代理、波动率用成本代理）；缺归一化与控制 |
| 使用科学方法 | 🔴 基本未实现 | 仅描述统计 + 人为样本门槛；无检验、无置信区间、无回归、无对照（代码 0 命中） |

**本质判断**：前三者是**采样与分层维度**，第四者是**推断引擎**。现状 CostView 是描述性报表系统，broker/algo 排行 = 原始均值排序 + 样本门槛，未做可比性控制。按方法论 B3 口径，这已在下比较结论但缺可比性保证，属结论过度自信。本计划的范式转变是：**从「报告系统」转为「评估系统」**。

---

## 2. 维度一：按周度频率

### 2.1 已实现

| 事实 | 证据 |
|---|---|
| 时间窗口预设白名单含 `week` | `CostView/src/monitoring/time_range.py:24-25`：`LAST_PRESETS: tuple[str, ...] = ("day", "week", "month", "quarter", "year")` |
| `week` 解析为「上周一 ~ 上周日」闭区间 | `CostView/src/monitoring/time_range.py:141-146` |
| 预设分派与互斥校验 | `CostView/src/monitoring/time_range.py:47-82`（`resolve_time_range`）、`:112-121`（`_resolve_explicit`）、`:147-157`（month/quarter/year） |
| 前端有「上周」入口 | `CostView/module/components/ReportView.tsx:62-69`、`CostView/module/components/MonitoringView.tsx:33-39` |

### 2.2 缺口

| 事实 | 证据 |
|---|---|
| `TimeRange` 无 granularity / frequency 字段 | `CostView/src/monitoring/time_range.py:30-44`：字段仅 `start_date` / `end_date` / `preset` / `as_of_date` |
| 按时间分组一律锚在日粒度 | `CostView/src/monitoring/report_aggregator.py:579-599`（`_query_daily_series`，`:589` 为 `GROUP BY order_as_of_date`） |
| 覆盖率分层同样锚在日粒度 | `CostView/src/monitoring/metric_coverage.py:257`：`group_cols = "order_as_of_date, Exchange" if group_by_exchange else "order_as_of_date"` |
| 全仓无周分桶 / 周 rollup | `CostView/src` 内 `strftime` / `date_trunc` / 周聚合 0 命中；`frequency` / `频率` / `rolling` / `滚动` 在 `CostView` 下 0 命中 |

### 2.3 可复用资产与设计约束

| 资产 | 证据 | 复用方式 |
|---|---|---|
| 唯一的「分组维度开关」既有范式 | `CostView/src/monitoring/metric_coverage.py:166-171`（`group_by_exchange: bool = False` 形参）、`:257`（据此切换 `group_cols`）；路由层同名 Query：`CostView/api/routers/monitoring.py:193` | 周度粒度参数沿用「显式形参 + SQL 分组列切换」模式，不引入新范式 |
| 聚合粒度枚举先例 | `platform_data/contracts/tca_contracts.py:52`：`aggregation: str = "per_order"  # "per_order" \| "aggregated"` | 粒度参数的命名与默认值风格参照 |
| 口径单点实现约定 | `docs/report-tca-known-limitations.md:68-69`：作用域 / 加权 / 订单级聚合 / 金额回退统一在 `CostView/src/monitoring/report_measure.py`，调用方不得各自重写 SQL 片段 | 周键 SQL 表达式必须落在单点，不得在 KPI / 走势 / 覆盖率各自拼 |

**未找到**：仓库内任何名为 `granularity` / `period` 的粒度枚举或参数（`CostView/`、`backend/api/`、`*.ts` 均 0 匹配）——即本计划为该能力的第一处实现，无既有先例可直接照搬。

---

## 3. 维度二：分市场

### 3.1 已实现（这一维地基完备）

| 事实 | 证据 |
|---|---|
| `Exchange` 是主表一等字段 | `platform_data/contracts/tca_contracts.py:64`：`Exchange: Optional[str]` |
| 市场白名单 | `data_access/config.py:88-100`：`BDIB_EXCHANGE`（28+ 市场） |
| 市场中文名与展示顺序 | `data_access/config.py:107-142`：`MARKET_ORDER`（顺序即报告标签页顺序） |
| 作用域一次性解析并被全报告共用 | `CostView/src/monitoring/report_measure.py:93-119`：`resolve_scope` / `scope_condition` |
| 市场清单 | `CostView/src/monitoring/report_aggregator.py:356-386`：`_query_markets` |
| 分市场金额排名 | `CostView/src/monitoring/report_aggregator.py:388-421`：`_query_market_notional_ranking` |
| 分市场每日金额趋势 | `CostView/src/monitoring/report_aggregator.py:423-452` |
| 分市场 PWP 小多图 | `CostView/src/monitoring/report_aggregator.py:735-768`：`_query_pwp_by_exchange`（Top 6） |
| 覆盖率按市场分层 | `CostView/src/monitoring/metric_coverage.py:257`；API `CostView/api/routers/monitoring.py:187,193` |
| regime 按市场分组 | `platform_data/regime_query.py:52-60`：按 `(date, market_code)` 分组 |

### 3.2 缺口

- **无市场中性化 / 跨市场可比性对齐**：全仓搜索 `中性化` / `market neutral` 无相关实现（命中项均为路径、AST、大小写归一，非成本中性化）。
- 跨市场 bps 数值在报告内直接并列，未剔除各市场自身波动率与流动性差异；分市场 PWP 小多图已共享统一 y 域（`docs/report-tca-known-limitations.md:256`），但那是**视觉可比**，非**统计可比**。

---

## 4. 维度三：执行环境变量

### 4.1 已实现

| 事实 | 证据 |
|---|---|
| regime 三维标签（波动/流动性/趋势） | `platform_data/regime_query.py:29`（维度定义）、`:52-60`（按 `(date, market_code)` 分组） |
| regime 数据源 | `regime.db` 的 `fill_regime_labels` / `audit_regime_config_versions` |
| regime 分布端点 | `CostView/api/routers/costview.py:586-637`：`GET /api/costview/regime-distribution` |
| regime 前端面板 | `CostView/module/components/RegimeDistributionPanel.tsx` |
| 记分卡 cohort 注册表 | `platform_data/contracts/tca_contracts.py:26-34`：`SCORECARD_COHORTS = ("broker", "strategy", "broker_strategy", "asset_class", "time_of_day", "liquidity_adv20", "volatility")` |

### 4.2 代理变量缺陷（本维度核心问题）

`CostView/src/tca_utils.py:179-205`（`cohort_key_and_label`）三个环境分支全为代理：

```python
    if cohort == "time_of_day":
        # TcaRouteSummary 未携带 start_time，默认 unknown
        return ("unknown", "Unknown")
    if cohort == "liquidity_adv20":
        # 使用 par_rate 作为参与率代理（par_rate 为 0-1 小数，bucket 需要百分比）
        return bucket_liquidity(route.par_rate * 100 if route.par_rate is not None else None)
    if cohort == "volatility":
        # TcaRouteSummary 未携带 daily_volatility，使用 pnl_vwap 绝对值代理（bps）
        return bucket_volatility(abs(route.pnl_vwap) if route.pnl_vwap is not None else None)
```

| 缺陷 | 性质 |
|---|---|
| `time_of_day` 恒返回 `("unknown", "Unknown")` | **失效**（非降级）——该 cohort 当前无任何区分能力 |
| `liquidity_adv20` 用 `par_rate` 代理 ADV20 | 代理：参与率与 ADV 相关但不等价 |
| `volatility` 用 `\|pnl_vwap\|` 代理日波动率 | **循环论证风险**：用成本代理环境变量，再按它分层比较成本 |

分桶口径：`CostView/src/tca_utils.py:300-308`（`bucket_liquidity`）、`:311-319`（`bucket_volatility`）。

**注**：`CostView/src/tca_utils.py:158-172` 已有 `bucket_time_of_day(start_time)`（`open` <10:30 / `mid` / `close` ≥14:30），输入 `HH:MM:SS` —— **分桶函数已就绪，缺的只是数据供给与接线**。

### 4.3 字段现状

| 事实 | 证据 |
|---|---|
| 真实环境字段存在于**已弃用**的 `TcaOrderSummary` | `platform_data/contracts/tca_contracts.py:153-184`：含 `volume_pct_adv5/adv20`、`daily_volatility`、`intraday_volatility`、`price_movement_pct` |
| 活跃的 `TcaRouteSummary` **不携带**这些字段 | `platform_data/contracts/tca_contracts.py:57-121`（55 字段：17 源值 + 38 计算指标） |
| 前端已有「代理字段 → 实际列」映射（显式承认代理） | `docs/handoff-costview-html-report.md:65-72`：`volume_pct_adv20 ← par_rate ×100`、`volume_pct_interval ← par_rate_continuous ×100`、`intraday_volatility ← pnl_vwap_continuous ×0.01`、`price_movement_pct ← rpm` |
| 报告口径明确排除项 | `CostView/src/monitoring/report_spec.py:52-54`：`excluded: (explicit_fees, rebates, taxes, L2_liquidity, pre_trade_forecast)` |

### 4.4 阶段二「第 0 步探测」预研结论（★ 本节修正原假设）

原评估假设「三项目标环境变量需跨仓等待上游」。**预研发现它们在只读链路内均有可派生来源**：

| 目标变量 | 可派生来源 | 证据 | 自给可行性 |
|---|---|---|---|
| 交易时段 `start_time` | `fill_bdib.mkt_timestamp` 按 `(OrderId, RouteId, order_as_of_date)` 取 `MIN` | `CostView/tests/test_tca_query_service.py:129-141`（`fill_bdib` DDL 26 列，含 `mkt_timestamp`）；实际消费列 `CostView/src/tca_query_builder.py:66-75` | **高**（分桶函数 `bucket_time_of_day` 已就绪） |
| `adv20` | `bdib_daily_summary.adv_20d`（**已内置，无需计算**） | `CostView/tests/test_tca_query_service.py:212-218`（表 DDL）；表名常量 `platform_data/contracts/db_constants.py:13`、`data_access/config.py:260` | **高** |
| `daily_volatility` | `bdib_daily_summary.daily_volatility`（**已内置**）；日内可用 `intraday_volatility` | 同上 DDL；读取器 `platform_data/adapters/tca_bridge.py:85-140`（`_ConnectionManagerDailySummaryReader`）；市场快照 SQL `platform_data/adapters/market.py:416-424` | **高** |
| 日内波动率替代源 | `fill_bdib` 自带 `cum_interval_volatility` / `standard_cum_interval_volatility` / `log_chg_pct_10s` | `CostView/tests/test_tca_query_service.py:134-139` | 中（口径需定义） |

**派生范式参考**（既有的「从 `fill_bdib` 派生并 join 回主表」写法）：`CostView/src/monitoring/report_measure.py:294-331`（`fbfx_cte`）——按 `(OrderId, RouteId, order_as_of_date)` 以 `fill_volume` 加权聚合 `fx_rate`，再按 `fxf_oad` join 主查询；`BETWEEN ? AND ?` 复用调用方前置的时间参数。

**必须实测的前置项（不得臆测）**：

1. **`fill_bdib.mkt_timestamp` 的实际格式**。本地测试夹具为 `'20260418 10:10:00'`（`CostView/tests/test_tca_query_service.py:146`、`CostView/tests/test_monitoring.py:95`）；而 `raw_bdib.mkt_timestamp` 在历史文档中被记录为**纯时间 `HH:MM:SS`（8 字符）**（`docs/archive/2026-08-26/002-pipeline-guardrail/optimization_plan.md:38,324-325`），`platform_data/adapters/market.py:445-448,463-465` 亦按 `HH:MM:SS` 解析（`fb[:5]` / `split(":")`）。
   → 两套值域并存，**必须先跑格式校验**，沿用该项目既有的前置验证范式（`docs/archive/2026-08-26/002-pipeline-guardrail/optimization_plan.md:324-326` 给出的 `SELECT DISTINCT length(mkt_timestamp) FROM <表> LIMIT 10`）。
2. `bdib_daily_summary` 的 `adv_20d` / `daily_volatility` 实际覆盖率（NULL 比例）——决定降级口径的触发阈值。
3. `fill_bdib` 在报告期内的数据密度——决定时段派生（按路由取 `MIN(mkt_timestamp)`）是否在多数路由上可得。

**对「跨仓协作项」的修正**：三项目标变量均可自给，因此上游字段产出需求**不再是阶段二的硬前置**。可行形态转为：本侧先自给 → 若实测证明 join 开销或覆盖率不可接受，再评估「请上游将 `adv20` / `daily_volatility` 物化到 `tca_route_summary` 列」作为**性能优化型**协作项（非正确性前置）。

---

## 5. 维度四：使用科学方法

### 5.1 已实现（描述统计 + 人为门槛）

| 事实 | 证据 |
|---|---|
| 描述统计纯函数 | `CostView/src/tca_utils.py:110`（`mean_numeric`）、`:128`（`std`）、`:138`（`safe_percentile`） |
| cohort 聚合的均值/中位数/p95/stddev | `CostView/src/tca_utils.py:224-231` |
| 样本量门槛与告警 | `CostView/src/tca_utils.py:251`、`:286`（`sample_size_warning`）；门槛注入点 `CostView/src/tca_query_service.py:182`、`CostView/api/routers/costview.py:112`（默认 10） |
| 排行双维门槛 | `CostView/src/monitoring/report_aggregator.py:46,49`：`_RANKING_MIN_SAMPLE = 5`、`_RANKING_MIN_NOTIONAL_SHARE = 0.001`；实现在 `:647-654` |
| 覆盖披露（样本 + 权重双口径） | `CostView/src/monitoring/report_measure.py:188-203`（`weight_coverage_entry`） |
| 数据质量探针 | `CostView/src/monitoring/anomaly_query.py:97-118`（8 条阈值规则 + warning/critical 两档） |

### 5.2 缺口

全仓（`CostView` + `docs`）搜索 `t-test|显著性|置信区间|confidence interval|significance|regression|回归分析|控制组|control group|ttest|scipy|statsmodels|p_value|hypothesis`：**代码中 0 命中**；唯一命中为方法论文档（第 6 节）。

具体缺失：

- 统计显著性检验（t / KS / χ²）、置信区间、p 值
- 成本回归 / 市场冲击函数估计（现有 `temp_impact_*` / `perm_impact_bps` 是**度量值**，不是估计出的冲击函数，见 `platform_data/contracts/tca_contracts.py:115-119`）
- 对照组 / 因果识别 / 可比样本匹配
- 样本功效分析（仅有硬编码 `min_sample_size`，无功效依据）
- 异常值的统计学处理（仅阈值告警，无修剪 / 截尾统计）

---

## 6. 方法论规格来源（库内已有，直接作为实现规格）

### 6.1 `docs/textbook/Algo_TCA.md`（Kissell 2014）

| 规格 | 位置 | 内容 |
|---|---|---|
| χ² 检验分步算法 | `:726-767` | 列联表构造 → 期望频数 → 统计量计算 |
| Kolmogorov-Smirnov 检验分步算法 | `:789-793` | 累积分布最大差 |
| **可比性前置要求**（逐字） | `:764`、`:789` | 「Trade a large enough number of orders in each algorithm in order to generate a representative sample size. **Ensure that the orders traded in each algorithm have similar characteristics such as side, size, volatility, trade time, and market cap, and were traded in similar market conditions.**」 |
| 分桶构造口径 | `:766` | 10~20 桶；按标准差（`<-3σ … >3σ`）或百分位切点（5%/10% 阶梯） |
| 隐性成本的回归口径（逐字） | `:116` | 「market impact costs are often estimated via **non-linear regression estimation**」 |

### 6.2 `docs/textbook/股票交易执行质量与交易成本分析（TCA）：跨时期学术研究综述与方法框架.md`

| 规格 | 位置 | 内容要点 |
|---|---|---|
| B2 八类指标框架 | `:92-103` | 含第 7 类「算法市场环境」、第 8 类「智能策略治理」 |
| **B3 分层归因与可比性条件**（逐字关键句） | `:105-109` | 「归因不宜只报告一个总bps数字。建议将总成本分解为显性费用、价差成本、市场冲击、延迟/等待成本、机会成本和路由成本，并按股票流动性、订单规模/ADV、交易方向、时段、波动状态、紧迫度和执行算法分层。**只有在这些维度足够相似时，跨经纪商或跨策略比较才具有解释力。**」 |
| B4 五层评价矩阵 | `:111-119` | 预测层 / 策略层 / 风险层 / 可执行层 / 治理层（治理层含版本锁定、数据血缘、基准冻结、压力测试、漂移监测、人工停机、实盘小规模验证） |
| D1 基准冻结 | `:160` | 「建议报告同时呈现至少一个决策基准和一个市场时间基准，而不是事后挑选最有利基准」 |
| D2 三重检验 | `:162-164` | 成本 / 风险 / 可操作性，任一维度不满足不得表述为「执行质量改善」 |
| D4 分层与门槛 | `:170-172` | 「还应按照股票流动性、订单规模/ADV、波动状态、时段和**市场制度**分层，因为平均预测效果往往掩盖低流动性尾部状态的失败」 |

---

## 7. 结构性空白（ADR 已规划、目录实际不存在）

`docs/spec/adr/0004-costview-focused-on-evaluation.md`：

- `:17-29`：CostView 应只负责「① 算法评估模型管理（`CostView/src/evaluation/`, `models/`）② 分析报告生成 ③ 归因与 regime 分析（`CostView/src/attribution/`, `regime/`）④ 执行历史查询」
- `:50`：「评估层建设需要持续投入（**待补 `evaluation/`, `models/` 目录**）」

**实际状态**：`CostView/src/` 下不存在 `evaluation/`、`models/`、`attribution/`、`regime/` 任何目录 —— 即本计划阶段三要建的层从未落地。

---

## 8. 口径治理与护栏（改动强约束）

### 8.1 三处同步要求

`docs/report-tca-known-limitations.md:61-69`：口径变更须**同时**更新

1. `CostView/src/monitoring/report_spec.py`（含 `SPEC_VERSION` bump）
2. `docs/report-tca-known-limitations.md`
3. `docs/spec/adr/0018-tca-report-metrics-conventions.md`

以及 `:68-69`：**同一口径在多个小节出现时只允许有一份实现**，作用域 / 加权 / 订单级聚合 / 金额回退统一在 `CostView/src/monitoring/report_measure.py`。

### 8.2 已知缺陷清单

| 编号 | 内容 | 本次是否处理 |
|---|---|---|
| K1 | 无显性费用 / 返佣 / 税费（`docs/report-tca-known-limitations.md:14`） | **不纳入**（用户已确认，费用口径另立计划） |
| K2 | 无 L2 订单簿流动性（`:15`） | 不纳入 |
| K3 | 无事前成本预测（`:16`） | 不纳入（003 已列为 P3 后续） |
| K4 | 无可操作性维度（`:17`） | 不纳入 |

`docs/report-tca-known-limitations.md:285-292`（仍待处理 P2）中与本计划直接相关：

- 「`intraday_volatility` / `volume_pct_adv20` / `price_movement_pct` 仍是代理字段，用户可见面（HTML / CSV 标签）未附 `metric_field`」→ 阶段二的代理标注工作直接承接此项。

`docs/archive/2026-09-16/003-tca-core-benchmarks/plan.md:164`：「范围外：D2 可操作性、B2.5 订单簿流动性、B2.6 事前预测（P3 后续）」。

`docs/open-todos.md`：**无**「周度 / 市场中性 / 科学方法」相关条目（现有 T9 / T13 与本计划无关）—— 缺专项 roadmap 正是本计划要补的空白。

### 8.3 护栏测试（改动须保持通过）

`CostView/tests/test_report_metrics.py` —— 31 个 Test 类（按行号）：

```
TestTradedWeighting:153        TestCompletionRate:209      TestOrderParAggregation:241
TestRuleLabels:283             TestOverfillRule:305        TestCoverageConsistency:366
TestAnomalySeverity:400        TestAnomalyExport:495       TestDisplayFormatting:547
TestMetricReasonConsistency:562 TestCoverageSla:580        TestBdibHealthPrecision:621
TestSampleDisclosure:686       TestImpactRecoveryDisclosure:754  TestTimeRangeAsOf:784
TestReportSpec:809             TestReportScopeUnified:912   TestWeightCoverageDisclosure:961
TestZeroFillVisibility:996     TestMeasureConsistency:1065  TestReviewRemediation:1103
TestBdibWeightFxContract:1159  TestTcaGapDetection:1246     TestSlaDenominatorStructural:1309
TestHtmlExportCsvClosure:1375  TestRankingSampleGate:1403   TestPwpWeighting:1464
TestAmountConsistency:1506     TestImpactTruncatedShare:1606 TestChartAxisPolicy:1631
TestAnomalyThrottleDisclosure:1719
```

`CostView/tests/test_monitoring.py` —— 7 个 Test 类：

```
TestPackageExports:126  TestResolveTimeRange:152  TestValidateMetrics:195
TestMetricCoverageService:208  TestBdibHealthService:341  TestTcaReportAggregator:440
TestExportHtmlZipClosure:962
```

### 8.4 测试夹具与规范（扩展用例时遵循）

| 项 | 证据 |
|---|---|
| 命名规范 | 类 `Test<域>`；方法 `test_<行为>_<条件>`；每用例带中文 docstring 说明断言意图（如 `CostView/tests/test_report_metrics.py:154-155`） |
| 临时库工厂夹具 | `CostView/tests/test_report_metrics.py:111-139`（`tca_mgr_factory`，按给定路由行造临时 `fill_bdib.db` 并返回 `ConnectionManager`） |
| 最小表结构 | `CostView/tests/test_report_metrics.py:67-90`（`_TCA_DDL`，含全部 38 项指标列） |
| 置 NULL 辅助 | `CostView/tests/test_report_metrics.py:93-108`（`_insert_route` 支持 `overrides`） |
| `parametrize` 使用情况 | `test_report_metrics.py` **未使用**；全 `CostView/tests/` 仅 `test_golden_samples.py` 与 `test_cli_entrypoint.py` 各 1 处 |
| 黄金样本夹具结构 | `CostView/tests/golden/README.md`、`golden/20260901_20260904.json`（基线）、`golden/snapshot/fill_bdib.db`（1.48 MB 冻结输入快照） |
| 黄金样本用法 | `CostView/tests/test_golden_samples.py:24-32`（快照目录解析，`EMSXVIEW_GOLDEN_DATA_DIR` 可覆盖）、`:34-37`（无基线即 skip）、`:46`（逐 JSON parametrize）、`:74-83`（`pytest.approx(rel=tol)` 比对） |
| **黄金样本覆盖边界（★）** | `CostView/tests/golden/README.md:57-62`：golden 只走 `gen_golden.py → build_tca_report` 的 per_order 链路，**不覆盖 monitoring 侧**（含 `fbfx_cte`）——「改 monitoring 口径必须全量跑 `pytest CostView/tests/`」 |

---

## 9. 可选特性门控模式（阶段三新端点必须沿用）

| 项 | 证据 |
|---|---|
| 开关定义（环境变量，默认开启） | `data_access/config.py:223-237`：`TCA_CORE_BENCHMARKS_ENABLED` / `TCA_RISK_IMPACT_ENABLED` / `TCA_ORDER_AGG_ENABLED`，形态均为 `os.getenv("<NAME>", "1") == "1"` |
| 路由层门控写法 | `CostView/api/routers/costview.py:217`（端点）、`:247`（`if not DataAccessConfig.TCA_ORDER_AGG_ENABLED:`）、`:257`（返回 `order_agg_enabled: False`）、`message` 明示「为空不代表无匹配数据」 |
| 服务层二次门控 | `CostView/src/tca_query_service.py:247-248` |
| 能力可见性端点（前端据此提示降级） | `CostView/api/routers/costview.py:547-560`：`GET /api/tca/capabilities` 返回 `order_level_tca` / `core_benchmarks` / `risk_impact` |
| Router 级桥接门控 | `backend/api/config.py:96-99`（`EMSXVIEW_OPTIONAL_MODULES`）、`backend/api/main.py:273-280`、`:283-308`、`:311-324`（`_register_optional`） |
| 规范约束 | `docs/spec/anti-patterns.md:156-166`（AP-09：新增 router 必须走 `_register_optional`，不得直接 `app.include_router`）；`docs/spec/module-onboarding.md:198-240` |

---

## 10. 依赖现状（阶段三的 scipy 决策依据）

| 项 | 证据 | 结论 |
|---|---|---|
| CostView 依赖声明 | `CostView/pyproject.toml:1-41`：`pydantic>=2.5` / `pandas>=2.0.0` / `emsxview-platform-data`（注释明确「`emsxview-datapipeline` 已移除（AP-01：禁止 import `DataPipeline.*`）」） | 未声明 scipy |
| **scipy 全仓检索** | `search_content "scipy"` → **0 匹配**（无声明、无 import） | 引入属新增依赖，需显式理由 |
| numpy 现状 | 无直接声明，由 pandas 传递带入；实际 import：`data_access/config.py:19`、`platform_data/adapters/market.py:490` | 可用但未显式声明 |
| platform_data 依赖 | `platform_data/pyproject.toml:10-14`：`pydantic>=2.5` / `python-dateutil>=2.8` / `emsxview-datapipeline` | 不含 scipy / numpy |
| 后端依赖载体 | `CostView/api/requirements.txt`（FastAPI / pydantic / redis / sqlalchemy）、`backend/api/requirements.txt` | 均无 scipy / numpy |

---

## 11. 数据层与上游边界

### 11.1 读取的表（全部只读，`mode=ro`）

| 表 | 库 | 用途 | 证据 |
|---|---|---|---|
| `tca_route_summary` | `fill_bdib.db` | TCA 主表（55 字段） | `data_access/config.py:263` |
| `fill_bdib` | `fill_bdib.db` | 时序（价格 / 成交量 / VWAP / slippage / 波动率累计列） | `data_access/config.py:262` |
| `tca_report_dims` / `_meta` | `fill_bdib.db` | 过滤下拉维度值 | `data_access/config.py:266-267` |
| `fx_rates` | `fill_bdib.db` | 币种 × 日期汇率 | `data_access/config.py:269` |
| `processed_fills` | `processed_fills.db` | TCA 整日缺失差集检测 | `data_access/config.py:253` |
| `bdib_daily_summary` | `raw_bdib.db` | 次日收盘价（`p_close` / `perm_impact`）；**另含 `adv_20d` / `daily_volatility` / `intraday_volatility`** | `data_access/config.py:260`、`platform_data/contracts/db_constants.py:13` |
| `fill_regime_labels` / `audit_regime_config_versions` | `regime.db` | regime 分布 | `platform_data/regime_query.py:52-60` |

### 11.2 硬边界

- EMSXView 为**只读消费者**：连接经 `data_access.storage.connection.ConnectionManager` 的 `AccessTier.READ`（sqlite URI `mode=ro`），文件系统层面拒绝写；数据更新维护的**唯一写入方**是独立仓库 EMSXDataPipeline（`docs/spec/git-workflow.md:193`）。
- 本仓库**禁止 import `DataPipeline.*`**（`docs/spec/anti-patterns.md` AP-01；`CostView/pyproject.toml` 注释同源）。
- 文档中**不写上游仓库磁盘路径**；需引用时只说明归属（`docs/index.md:101-104`）。
- `platform_data` 中 `CostViewAnalyticsAdapter` / `CostViewDatabaseAdapter` / `ExecutionHistoryAdapter` / `DataPlatformIngestionAdapter` / `build_platform_data_access()` / `PlatformDataAccess` 为**规划中、尚未实现**，禁止按符号 import（`docs/spec/adr/0013-platform-data-adapter-current-state.md`）。

### 11.3 上游协作项登记形式

沿用 `docs/open-todos.md` 既有行式登记（参照 T13 行），只写「需要什么字段 / 为什么 / 触发条件」，不写上游磁盘路径。

---

## 12. 计划文档体例参考

`docs/archive/2026-09-16/003-tca-core-benchmarks/plan.md` 章节骨架：

```
# 实施计划: <标题>
## Summary
## 已确认设计决策
## 统一技术原则（G0 数据零受损）
## 迁移模式
## 新列清单
### Phase 0 / Phase 1
## route → order 聚合策略
## 实施阶段
### Phase 0 / Phase 1 / Phase 2
## 全流程防漂移检查（G2）
## 改动-需求双向矩阵（G3）
```

文首元信息体例（`:3-7`）：`**Branch** | **Date** | **状态**` + `**理论依据**` + `**门控规范**`。

同目录附属文件：`checklists/progress.md`（003 仅此一件；004/005/006/007/008、009~025 多为 `plan.md` + `checklists/progress.md` 两件套）。本计划额外增加 `research.md`，参照 `docs/archive/2026-08-26/002-pipeline-guardrail/` 的更完整形态。

归档约定（`docs/index.md:55-65`）：归档后**保留原编号与目录名**，落 `docs/archive/YYYY-MM-DD/<feature-id>/`；`specs/` 只承载在途计划。

---

## 13. 证据索引速查

| 主题 | 关键位置 |
|---|---|
| 周窗口预设 | `CostView/src/monitoring/time_range.py:24-25,47-82,141-146` |
| 日粒度分组 | `CostView/src/monitoring/report_aggregator.py:579-599`、`CostView/src/monitoring/metric_coverage.py:257` |
| 分组开关范式 | `CostView/src/monitoring/metric_coverage.py:166-171`、`CostView/api/routers/monitoring.py:193` |
| 市场维度全链 | `platform_data/contracts/tca_contracts.py:64`、`data_access/config.py:88-100,107-142`、`CostView/src/monitoring/report_measure.py:93-119` |
| regime | `platform_data/regime_query.py:29,52-60`、`CostView/api/routers/costview.py:586-637` |
| cohort 代理缺陷 | `CostView/src/tca_utils.py:158-172,179-205,300-319` |
| 环境字段真相 | `platform_data/contracts/tca_contracts.py:57-121,153-184`、`docs/handoff-costview-html-report.md:65-72` |
| 阶段二数据源 | `CostView/tests/test_tca_query_service.py:129-141,212-218`、`platform_data/adapters/tca_bridge.py:85-140` |
| 派生 join 范式 | `CostView/src/monitoring/report_measure.py:294-331` |
| 描述统计与门槛 | `CostView/src/tca_utils.py:110,128,138,224-231,251,286`、`CostView/src/monitoring/report_aggregator.py:46,49` |
| 方法论规格 | `docs/textbook/Algo_TCA.md:116,726-793`、`docs/textbook/股票交易执行质量与交易成本分析（TCA）：跨时期学术研究综述与方法框架.md:92-119,160-172` |
| 结构性空白 | `docs/spec/adr/0004-costview-focused-on-evaluation.md:17-29,50` |
| 口径治理 | `docs/report-tca-known-limitations.md:10-17,61-69,285-292` |
| 门控模式 | `data_access/config.py:223-237`、`CostView/api/routers/costview.py:217-263,547-560`、`docs/spec/anti-patterns.md:156-166` |
| 测试与夹具 | `CostView/tests/test_report_metrics.py:67-139`、`CostView/tests/golden/README.md:57-62` |
| 上游边界 | `docs/spec/git-workflow.md:193`、`docs/index.md:101-104`、`docs/spec/adr/0013-platform-data-adapter-current-state.md` |
