# TCA 报告口径缺陷清单（Known Limitations）

> 记录 CostView 导出的 TCA 可视化 HTML 报告（`/api/tca/monitoring/export-html` 与
> `scripts/reports/generate_tca_report.py` 共用渲染器）当前已知的**口径缺陷**。
> 供审计留痕；有数据/算力条件后逐项补齐。
>
> 依据：`docs/textbook/股票交易执行质量与交易成本分析（TCA）：跨时期学术研究综述与方法框架.md`
> （模块 B 指标框架 / D 使用建议），对齐 B1 统一符号与 D2 三重检验（成本/风险/可操作性）。

## 一、硬缺口（当前无数据源，报告应明示而非伪装完整）

| # | 缺陷 | 文献依据 | 说明 / 补齐条件 |
|---|------|---------|----------------|
| K1 | 无显性费用/返佣/税费 | B1 TC 公式、B2-1 | 报告口径为**价格偏离**，不含 fees/rebates/taxes。按 B1，缺费用不应命名"完整实施短缺"。需 Broker/费用数据源。 |
| K2 | 无 L2 订单簿流动性 | B2-5 | 无顶档/多档深度、队列位置、订单簿失衡、撤单率、流动性恢复。需 L2/逐笔订单簿数据。 |
| K3 | 无事前成本预测 | B2-6、B4 预测层 | 无预测成本/预测—实现误差/分位数损失。003 计划明确 B2.6 为 P3 后续。 |
| K4 | 无可操作性维度 | B2-5、D2、B4 可执行层 | 无订单类型/队列/延迟/场所/最小成交单位/取消改单限制/手续费落地校验。003 明确 D2 可操作性范围外。 |

## 二、可补项（已有指标，本次已补齐）

> 以下各项在 006 计划（前端一键导出 HTML 报告）中已纳入报告聚合层，
> 此处保留条目以记录"曾缺失 → 已补齐"的演进，供后续验证。

| # | 缺陷 | 文献依据 | 状态 |
|---|------|---------|------|
| K5 | 决策基准聚合缺失（报告原只有 VWAP 时间基准） | D1、B2-4 | ✅ 已补：KPI 加权 arrival_cost_bps |
| K6 | 风险维度缺失（原只报平均成本） | B2-3、B4 风险层 | ✅ 已补：KPI cost_stddev / cost_cvar + 明细表 cost_cvar |
| K7 | 市场冲击分解缺失 | B2-2 | ✅ 已补：冲击分解表（temp 5/10/30min + perm） |
| K8 | 完成率/机会成本未呈现 | B1、B2-3 | ✅ 已补：KPI 平均完成率 + 明细表 opportunity_cost / 未完成数量 |
| K9 | 逐单复盘明细缺失 | B3 归因分层 | ✅ 已补：异常路由明细表（S6，无上限） |

## 三、报告口径脚注（渲染时已内置，明示边界）

脚注由 `CostView/src/monitoring/report_spec.py::REPORT_SPEC`（口径唯一真相源，
版本号 `SPEC_VERSION`）自动生成；本清单与脚注同源，调整口径需同步两处。

- 价格偏离口径，不含显性费用 / 返佣 / 税费
- 无 L2 订单簿流动性数据；不含事前成本预测
- 机会成本按 (Pn − P0) × 未成交数量 × 方向调整计算
- 到达价 / 决策价 / 收盘价 / VWAP 回答不同问题（D1），报告同时呈现决策基准与市场时间基准
- 加权口径为 **fill × p_avg**（成交额加权，与「总成交金额」同源）；不保留意图规模（RouteShares）加权对比值
- 报告统计范围默认以 **BDIB 白名单**（`Config.BDIB_EXCHANGE`）为界，KPI / 走势 / 排行 / 市场概览 / 异常明细 / 覆盖率 / BDIB 附录**全部小节同口径**；用户显式指定 `exchange` 时切换为用户口径，所选市场含白名单外项时在报告头显式告警（这些市场不拉 BDIB 行情，指标必然为 NULL）
- 加权均值**必须同时披露样本量与权重覆盖率**（条数覆盖 ≠ 权重覆盖）；任一覆盖低于 **90%** 时标注「结论仅供参考」
- 未成交金额缺口按价格回退链 **p_avg → p_arrival → p_decision → p_close** 计价（原仅取 p_avg，零成交路由因 p_avg 为 NULL 而贡献被跳过）；零成交路由计入缺口，并单列「零成交路由 / 委托金额（USD）」卡片；价格全缺的路由条数单列披露（缺口低估规模可见）
- 异常明细的笔数 / 金额下限对**严重未完成**（`fill_pct` 命中 critical，含零成交）路由**豁免**：该档目标样本恰是低完成率路由，用下限过滤会把「完全未执行」整体剔除
- 订单参与率按「仅报告期 + 作用域」**全量聚合**，不受 broker / algo / symbol 维度过滤影响，与覆盖率一致性探针共用同一实现（两处可对账）
- 异常严重度分 **warning / critical 两档**：warning 为进入异常清单的边界，critical 仅作分级标注
- Broker / Algo 排行按**双维门槛**（组样本 n_used ≥ 5 且组成交额占比 ≥ 0.1%，门槛对象为聚合组）输出**最优 / 最差双侧** Top 10；被门槛排除的组数显式披露
- PWP 五档为**成交额加权**（与总成交金额同源）并披露样本/权重覆盖；默认聚合曲线 + Top 6 市场小多图（跨市场混合的逐档值无物理解释，分市场解释由小图承接）
- 异常明细的成交金额(USD)门槛按 **COALESCE(Amount, fill × p_avg) × 汇率**（Amount 缺失的路由不再被门槛误杀）；展示列仍以写入方权威列 Amount 为准，Amount 与 fill×p_avg 的偏差（0.5% 容差）由数据质量区探针披露
- 市场冲击分解的跨日恢复占比分母为**冲击计算样本**（任一冲击指标可计算的路由），随 payload 披露 `impact_sample_count`
- 异常明细 HTML 渲染上限 **1000 条**（按严重度降序排列，截断样本无偏）；全量明细经随附 `anomaly_<hash>.csv` 导出（CLI 侧与 HTML 同目录落盘；API export-html 侧 HTML + CSV 打包为 zip 下载，`export_ref` 不再为空）
- BDIB 缺口附录在扫描超时 / 异常时显式标注「未扫描」，与「无缺口」区分
- USD 换算覆盖率按「可换算路由占比」计（含 USD 路由与 `fill_bdib` 回填汇率），并披露被排除的本币金额
- BDIB 缺口附录的缺口成交金额与 KPI **同源换算**（`fill_bdib` 回填 + 小计价单位修正 + 逐行换算）；缺汇率的路由不计入 USD 金额，其本币金额单列披露为「未换算金额」（缺口低估规模可见）
- 区间内 **TCA 整日缺失**（有成交但无 TCA 汇总，管道 S5.5 未产出）经差集检测自动定位，在报告头数据质量区披露并在覆盖率表橙底行高亮 —— 该情形此前对走势/覆盖率/附录三处交叉验证全体失明
- **SLA 覆盖率分母**对 `bdib_missing` 类指标剔除「BDIB 缺口路由」（有成交但核心 BDIB 依赖指标全 NULL）；纯竞价豁免分母含零成交路由 —— SLA 口径自此隔离管道缺口波动，与原始口径保持区分度
- 按日走势为**双轴 + 零轴 + 真实刻度**（左轴 pnl_vwap 对称含零轴；右轴 par_rate 零锚定；市场金额趋势零锚定）—— 此前各自独立归一且无刻度，负成本区间会得出相反结论；仅含「有数据交易日」（**不补零**），并标注覆盖天数；缺失定位见覆盖率表与数据质量提示
- 异常规则键为 `pnl_vwap_bps`（语义 = `|pnl_vwap|` 阈值；原名 `tracking_error_bps` 已弃用，旧键仍兼容读取）
- 聚合粒度可选 **`day` / `week` / `month`**（默认 `day`）：**周键按 ISO 8601**（周一为首日；跨年周按「该周周四所在年份」归属，如 `2025-12-29`~`2026-01-04` 同属 `2026-W01`）；期间序列**不补零**，仅披露覆盖期间数；`day` 粒度期间键为原始 `order_as_of_date`（既有按日产出逐字节不变）

## 四、维护约定

- 补齐任一 K 项后，在本表更新状态并标注日期/计划编号。
- 新报告功能开发前先查本表，避免重复实现已有缺陷项。
- 口径变更（加权方式 / 严重度档位 / 明细上限 / fx 兜底顺序 / **作用域与覆盖披露**）须同时更新
  `report_spec.py`（含 `SPEC_VERSION`）、本清单与
  [ADR-0018](spec/adr/0018-tca-report-metrics-conventions.md)。
- 同一口径在多个小节出现时，**只允许有一份实现**：作用域 / 加权 / 订单级聚合 / 金额回退
  的实现统一在 `CostView/src/monitoring/report_measure.py`，调用方不得各自重写 SQL 片段。

## 五、口径修复记录

### 2026-09-15 — P0（作用域 / 覆盖披露 / 零成交可见）

| # | 缺陷 | 影响 | 处理 |
|---|------|------|------|
| P0-1 | 加权 KPI 无样本量与权重覆盖披露 | BDIB 缺口集中在大单时，KPI 数值「看起来正常」实为子集均值；跨期对比失效 | ✅ 已修：新增 `report["weight_coverage"]`（样本 + 权重双口径），KPI 卡片 / 冲击分解表逐指标标注，低于 90% 提示结论仅供参考 |
| P0-2 | 零成交路由的机会成本黑洞 | 成本 KPI（无 pnl_vwap）、缺口金额（p_avg 为 NULL）、异常清单（笔数/金额下限）三处同时隐身，「完全未执行」不可见 | ✅ 已修：缺口金额走价格回退链、零成交路由数与委托金额单独成卡、严重未完成豁免下限门槛 |
| P0-3 | 白名单作用域只作用于覆盖率 | 同一报告内 overfill 条数与异常表命中不可对账；直方图样本被 out-of-scope 路由稀释 | ✅ 已修：作用域一次性解析并由 KPI / 覆盖率 / 异常 / 市场概览共用；用户口径下白名单外选择显式告警 |
| P0-4 | 多选过滤在异常清单失效 | 前端多选（逗号拼接）时异常清单静默清空，KPI 却正常，无任何告警 | ✅ 已修：维度过滤与作用域统一经 `report_measure`，`=` 改为 `IN` |
| P0-5 | `order_par_gt100` 探针在维度过滤下失真 | 按 broker 过滤后订单参与率只剩子集，探针系统性低估，与一致性探针不可对账 | ✅ 已修（同批）：订单级聚合改为「仅报告期 + 作用域」全量查询，两处共用同一实现 |

护栏：`CostView/tests/test_report_metrics.py`（`TestReportScopeUnified` / `TestWeightCoverageDisclosure` /
`TestZeroFillVisibility` / `TestMeasureConsistency` / `TestReportSpec.test_report_spec_matches_measure_layer`）。

### 2026-09-15 — P0 复核整改（第二轮）

| # | 复核发现 | 影响 | 处理 |
|---|---------|------|------|
| R1 | `__init__.py` 幽灵导出（`DIM_COLUMNS` / `ensure_schema` / `refresh_dim_values` 已在 `__all__` 但无对应 import） | `from ...monitoring import *` 直接抛 `AttributeError`，公共 API 契约破损 | ✅ 已修：清理导出表并补齐 `ReportScope` / `resolve_scope`；新增「`__all__` 每个符号可解析」护栏测试 |
| R2 | 订单参与率聚合未传作用域（docstring 契约要求「仅报告期 + 作用域」） | 结果当前等价（聚合键含 Exchange），但会无谓聚合白名单外市场；作用域一旦细到 symbol 级即静默分叉 | ✅ 已修：`_load_order_par_sums(..., scope)` 显式传作用域，与一致性探针同契约 |
| R3 | `filter_options` 持久化路径未按白名单过滤，与 docstring 及回退路径不一致 | 市场下拉内容随「维度表是否就绪」漂移 | ✅ 已修：两条路径统一按白名单裁剪（保序、忽略大小写），报告头 `out_of_scope` 告警承接显式越界选择 |
| R4 | `resolve_scope` 大写归一后未去重 | `"US, us"` 产生重复 IN 项与重复作用域文案 | ✅ 已修：归一去重（保序） |
| R5 | 下限豁免的声明 `"fill_pct_critical"` 为字符串拼接，未与实现绑定 | 改规则名时声明层无感 | ✅ 已修：声明改结构化 `{"rule", "severity"}`，实现常量落在 `report_measure`（`FLOOR_EXEMPT_RULE` / `FLOOR_EXEMPT_SEVERITY` / `is_floor_exempt`），测试断言两者一致 |
| R6 | `fill IS NULL` 的零成交路由与 KPI 口径不对称 | KPI 卡（`COALESCE(fill,0)`）能数到，异常清单却隐身 | ✅ 已修：异常侧按零成交处理（`fill` NULL 原因为 `source`，正常数据不触发，仅旧 schema 兜底）+ 护栏测试 |
| R7 | 健康扫描不接受作用域 | 用户按市场过滤时缺口附录仍报出其他市场的缺口，与 KPI / 覆盖率 / 异常「同口径」只是巧合 | ✅ 已修：`get_health(..., scope=)` / `get_health_safe` 透传，CLI 与 export-html 端点传入报告作用域 |
| R8 | `scripts/quality_gate/run.py` 缺 `__main__` 守卫 | `python -m scripts.quality_gate.run` 只 import、不扫描且 exit 0，形成「门禁看似通过」的假信号。**澄清**：该形式从未作为文档入口出现（`docs/spec/quality-gate.md`、`git-workflow.md`、`.githooks/pre-commit` 一致使用平铺入口 `scripts/quality_gate.py`，该入口自带守卫，故门禁一直在执行）；`-m` 形式仅出现在临时手敲的命令里 | ✅ 已修：补守卫，两种入口行为一致 |

### 2026-09-15 — 第三轮复核（前端口径对齐）

| # | 发现 | 影响 | 处理 |
|---|------|------|------|
| F1 | 前端 Report 页未消费 `weight_coverage` / `filters.scope` / 零成交 KPI | HTML 导出已完整披露，网页视图看不到 → **同一报告两个端口径不对账**（与本轮系统性消除的问题同构） | ✅ 已修：补齐 TS 类型（`TcaReportScope` / `TcaWeightCoverage` / 零成交与未计价字段）、新增 `lib/report-format.ts` 展示函数（文案与 HTML 渲染器逐字对齐）、ReportView 的 KPI 卡/报告头接入；10 条单测 |
| F2 | 「文档指向 `python -m` 坏入口」的前提不成立 | 无 | ✅ 已澄清（见 R8 行）；`run.py` 守卫仍保留，消除 `-m` 形式的假信号 |

**产品口径说明（下拉白名单裁剪的副作用）**：`filter_options.exchanges` 按白名单裁剪后，UI 下拉不再能选出白名单外市场，因此 `filters.scope.out_of_scope` 告警路径实际只对 API/CLI 显式传参生效。这与 `build_report` docstring 的既有意图（「受白名单约束」）自洽，作为默认口径成立；若未来产品上希望用户能主动纳入 CN 等市场观察其 BDIB 指标必然 NULL 的表现，需另行开口子，并**同步该 docstring 与本节**，避免重演文档-实现矛盾。

### 2026-09-15 — 第四轮复核（S2 收尾：冲击表接入 + 展示层去封顶）

| # | 发现 | 影响 | 处理 |
|---|------|------|------|
| G1 | 前端冲击分解表未消费 `weight_coverage`（S2 未完成面） | HTML 报告该表逐指标带覆盖披露，网页视图看不到 → 同一张表两端口径不对账 | ✅ 已修：`ImpactBreakdownTable` 增 `coverage` prop，逐行按指标键附「样本/权重覆盖」；新增集成断言 |
| G2 | 前端 `formatPct` 仍封顶 100%（与 ADR-0018 §2「移除展示层封顶」相反） | **不只是外观**：「组合完成率」卡与异常表完成率/参与率列把 overfill 驱动的 >100% 钳成 100.00%，数据矛盾在 web 端被掩盖，而 HTML 端显式暴露 —— 展示层掩盖数据矛盾的原缺陷复发 | ✅ 已修：去掉封顶（与 HTML `_fmt_pct` 同口径），4 个调用点（组合完成率、完成率、路由参与率、订单参与率）同时受益；单测固化 `1.05 → 105.00%` |
| G3 | scope 文案后缀缺失 | HTML 报告头为「统计范围 {label}（全报告统一口径）」，web 端缺后缀 → 关键承诺（全报告同口径）丢失 | ✅ 已修：`formatScopeLabel` 补后缀，与 HTML 逐字对齐 |
| G4 | 「文案与 HTML 渲染器逐字对齐」表述过强 | 实际为核心句逐字对齐 + 四处呈现细节偏差 | ✅ 已处理：把三处**有意偏差**（百分数取整、` · ` 分隔符、零成交 `$` 前缀）在 `lib/report-format.ts` 注释中显式声明，避免未来被单侧「修复」；第 4 处（scope 后缀）改为对齐 |

**登记新增待办**：前端异常明细表未渲染 HTML 侧既有的「超成交 / >100%」标记（`TcaAnomalyRow.overfill` / `order_par_gt100` 字段已具备）。数值信号已由 G2 恢复（>100% 不再被封顶），标记属呈现增强，排 P2。

### 2026-09-15 — 第五轮（异常规则边界与标签修订）

| # | 发现 | 影响 | 处理 |
|---|------|------|------|
| H1 | `overfill_pct` 为 `above 100`（含边界），而 `AnomalyRoute.overfill` 为严格 `fill > RouteShares` | 完成率恰为 100.0%（正常成交满，占多数）的路由带 `Overfill % 100.0%` 标签进入异常清单，但 `overfill` 为 `False` —— 标签语义与实际含义相反，属数据质量探针误报 | ✅ 已修：新增 `above-strict` 模式（严格大于），`overfill_pct` 改用之；100.0% 不再入清单，命中与 `overfill` 布尔标记同界；轻微超成交（100.1%）仍照旧捕获 |
| H2 | 规则标签 `Overfill %` 自带 `%`，渲染层再补单位后缀 | 标签渲染为 `Overfill % 100.0%`（双 `%`），版面噪声且易读错 | ✅ 已修：标签改 `Overfill`，`%` 统一由单位后缀补（后端 `_RULE_LABELS` 与前端 `DEFAULT_RULES` 同改） |

**原登记待办（`order_par_gt100` 边界）与同类标签问题已在第六轮一并收敛**，见下节。

护栏：后端 `CostView/tests/test_report_metrics.py`（`TestOverfillRule.test_exact_full_fill_not_flagged` 与
`test_overfill_flagged_and_hits` 的标签断言）；前端 `lib/thresholds.test.ts`
（「treats overfill boundary as exclusive」，锁定标签、模式与四个边界取值）。

### 2026-09-15 — 第六轮（order_par 边界与规则标签归一）

| # | 发现 | 影响 | 处理 |
|---|------|------|------|
| H3 | `order_par_gt100` 为 `above 100`（含边界），而 `AnomalyRoute.order_par_gt100` 标记与覆盖率一致性探针（`metric_coverage` 的 `par_sum > 1.0`）均为严格大于 | 求和恰为 `100.0%` 的路由进异常清单却不进 `data_quality.order_par_gt100_count` 与 `order_par_consistency_pct` —— 同一份报告内三处口径不一致 | ✅ 已修：改用 `above-strict`（严格大于 100%），与布尔标记、一致性探针同界，命中数自此可对账 |
| H4 | 其余规则标签仍自带单位符号：`Pnl VWAP bps`、`Fill %`、`Vol % ADV20`、`Vol % Interval`、`Order Par >100%` | 渲染出 `Fill % 42.0%`、`Pnl VWAP bps 15.2 bps`、`Order Par >100% 250.0%` 等重复单位标签 | ✅ 已修：标签一律不含单位符号（`Pnl VWAP` / `Fill Rate` / `ADV20 Participation` / `Interval Participation` / `Order Par`），单位由渲染层后缀统一补；Configure 预览样例同步 |
| H5 | 存量配置保存的 `mode: 'above'` 是 v1 代码默认值，随 `thresholds` payload 每次查询下发并覆盖后端新默认（`ThresholdRules.from_payload` 以 payload 为准） | 后端已改 above-strict，老用户网页上完成率恰 100% 的路由仍带 `Overfill 100.0%` 标签 —— 「后端已修、前端仍误报」 | ✅ 已修：配置引入 `ruleSchemaVersion`（v2），读取时仅当存储 mode 仍等于旧默认时迁移为当前默认；用户显式选择不受影响，迁移只执行一次 |

**同批收敛（顺带）**：

- 前端本地配置加载改为「展示元数据（label / description / decimals / unit）以代码为准，用户可编辑字段（mode / warning / critical / enabled）以本地为准」——否则历史 localStorage 会把旧标签长期钉在浏览器里，后端标签已改而网页仍显示旧标签；同时兜住「旧版本只存了部分字段」的规则对象。
- Configure 预览样例中的 `Tracking Error 6.0 bps` 为 014 规则键重命名前的旧标签，同步改为 `Pnl VWAP 6.0 bps`。

护栏：后端 `TestOrderParAggregation.test_exact_full_order_par_not_flagged` 与 `TestRuleLabels`
（逐规则断言渲染后单位符号只出现一次）；前端 `thresholds.test.ts`「keeps unit symbols out of
rule labels」与 `storage.test.ts`（展示元数据刷新 / 部分字段兜底 / stale mode 一次性迁移）。

**质量门报告入库策略（第四轮 §六.1）**：`scripts/reports/quality_gate/report-*.md` 已加入 `.gitignore` —— 生成物可再生，逐轮修复账本以本文件 §五 为准，避免双账本产生「哪份是真相」分叉；历史两份（20260821 / 20260825）保留在库内作为冻结快照。

护栏：`CostView/tests/test_report_metrics.py`（`TestReportScopeUnified` / `TestWeightCoverageDisclosure` /
`TestZeroFillVisibility` / `TestMeasureConsistency` / `TestReviewRemediation` /
`TestReportSpec.test_report_spec_matches_measure_layer`）与
`CostView/tests/test_monitoring.py`（`TestPackageExports` / 市场下拉白名单 / 健康扫描作用域）。

### 2026-09-15 — 第七轮（P0 交叉审计修复：fx 口径 / CSV 闭环 / TCA 缺失 / SLA 分母）

独立深度交叉审计新发现的四项 P0 缺陷（前三轮/四轮台账均未覆盖或仅部分登记）：

| # | 缺陷 | 影响 | 处理 |
|---|------|------|------|
| X1 | BDIB 缺口金额缺小计价单位修正 + 整组粒度回退（原台账只登记了「未接回填」一层） | `_load_ticker_weight` 自行拼 fx SQL：GBp 市场缺口金额高估 100 倍；组内部分路由缺汇率时缺口金额被静默低估且无披露；未接 `fill_bdib` 回填，比 KPI 更易回退本币 | ✅ 已修：换算改经 `report_measure.usd_fx_expr` 单一实现（fill_bdib 回填 CTE + minor-unit ×0.01），逐行换算，缺汇率路由的本币金额单列 `missing_notional_unconvertible` 披露 |
| X2 | 脚注承诺「全量见随附导出 CSV」但 API export-html 从不落盘，`export_ref` 恒为 None | 报告文本承诺不存在的附件；超 1000 条时其余异常无任何获取途径（三处实现各自完好、组合后承诺落空，四轮复核均未捕获） | ✅ 已修：export-html 把全量异常明细落盘 CSV（系统临时目录）并与 HTML 打包为 zip 返回；对报告浅拷贝回填 `export_ref`，不污染 report-summary 共享缓存（前端会渲染该字段） |
| X3 | TCA 整日缺失不可定位 | 走势/覆盖率/缺口附录均源自 `tca_route_summary` 或回答 BDIB 缺口，S5.5 断档日在报告内静默消失，可跨周不被发现 | ✅ 已修：健康扫描输出 `tca_gap_dates`（processed_fills ↔ tca_route_summary 日期差集）；报告头数据质量区披露、覆盖率表橙底行高亮、附录行加「TCA 缺失」标记；日期集不可得时显式降级披露，不静默放行 |
| X4 | SLA 分母结构性错配 | `bdib_missing` 类指标分母为全部路由 —— BDIB 缺口越大 SLA 越低，SLA 口径随管道缺口波动、与原始口径失去区分度；纯竞价判定漏掉 fill=NULL 的零成交路由 | ✅ 已修：`SLA_DENOMINATOR_BY_REASON["bdib_missing"] = "non_bdib_gap"`（有成交但核心 BDIB 依赖指标全 NULL 的路由自 tca 表内探针剔除，无需跨服务注入健康扫描）；纯竞价判定改 `COALESCE(fill,0)=0 OR fill_close >= fill` |

同批：`SPEC_VERSION` → `2026.09.3`；`REPORT_SPEC` 新增 `gap_notional_fx` / `tca_gap_detection` /
`sla_bdib_missing_denominator`（与实现结构化绑定，R5 同款模式）。

护栏：`CostView/tests/test_report_metrics.py`（`TestBdibWeightFxContract` /
`TestTcaGapDetection` / `TestSlaDenominatorStructural` / `TestHtmlExportCsvClosure`）。

#### 第七轮合入后独立复核（post-merge，#29 squash 后）

黄金样本库（`CostView/tests/golden/snapshot/fill_bdib.db`，4668 条路由、20260901~20260904）数值验证：

| 项 | 结论 |
|---|------|
| D8 量级核验 | GBp 市场：旧 17,063,317,081 → 新 170,633,171，比值精确 **0.0100** —— 审计预言的 100× 高估坐实并消除；全样本总金额 −91.24%（GBp 占旧口径 92%）；未换算披露 = 0（黄金样本 fx 全覆盖，逐行回退路径仅由单测覆盖） |
| D14 探针精度 | `bdib_gap` 探针命中 333 条（7.1%），与 p_arrival NULL 集合**完全重合**（SLA 92.87% → 100.00%，分母 4668 → 4335）—— 本样本上无「bdib_cutoff 残余被误豁免」；纯竞价豁免新旧一致（2160/2160，fill 无 NULL，扩展仅旧 schema 兼容路径） |
| D11 端到端 | payload 接线运行正常（4 dates、tca_gap_dates=[]、tca_missing_dates=0）；差集语义由 tmp_path 单测隔离验证（黄金端到端混用了真实 processed_fills，不作为差集数值依据） |
| D16 独立终验 | main 合并代码核验通过：zip 打包（`writestr(html) + write(csv)`）、`export_ref` 浅拷贝回填不污染共享缓存、媒体类型与文件名切换正确 |

复核发现的三项小事项（非阻塞）已同批处理：

| # | 事项 | 处理 |
|---|------|------|
| X5 | 旧 schema 无 fx 列时 `missing_notional` 实为本币合计，读者可能误读作 USD | ✅ 已修：`_load_ticker_weight` 返回 `(权重表, 是否 USD 口径)`，payload 增 `gap_notional_fx_usd`，附录页脚显式提示「缺口金额为本币口径」 |
| X6 | `bdib_gap` 探针豁免规模仅内部分母消费，不可审计 | ✅ 已修：覆盖率行输出 `bdib_gap_routes`，豁免规模可见（探针误豁免边界情形的规模可观测） |
| X7 | D16 交付物（zip/CSV）未随两份核心文件一并核验 | ✅ 已独立终验（见上表）；端到端 zip 响应建议在 P1 批次以 TestClient 集成测试补齐 |

### 2026-09-15 — 第八轮（P1-a 聚合查询层：排行门槛 / PWP 加权 / 金额一致性 / 冲击样本分母）

语义决策点 DP-1~DP-5 定稿后实施（本轮不含 D1 轴策略与 D6 节流披露，属 P1-b）：

| # | 缺陷 | 决策点 | 处理 |
|---|------|--------|------|
| P1-1 | 排行 `ASC + 前 10`、无样本门槛：小样本组把统计噪声伪装成执行能力，且尾部劣者不可见 | DP-1 选 B：组样本 `n_used ≥ 5`（组维度，不复用异常明细 fill_count 的单路由语义）+ 组成交额占比 ≥ 0.1%（经济相关性）双维门槛 | ✅ 已修：双维门槛 + 最优/最差双侧 Top10 + `excluded_by_broker/algo` 排除量披露；声明层 `ranking_min_sample` / `ranking_min_notional_share` 与实现常量结构化绑定 |
| P1-2 | PWP 五档等权 AVG 且跨市场混合：与加权 KPI 不可对账；逐档值跨市场混合无物理解释 | DP-2：纳入成交额加权体系；默认聚合曲线 + Top 6 市场小多图（组合加权趋势合法，分市场解释由小图承接） | ✅ 已修：`_query_pwp_curve` 改 `weighted_avg_sql`；PWP 五档进入 `WEIGHTED_METRICS`（weight_coverage 披露样本/权重覆盖）；新增 `pwp_by_exchange`（按组成交额降序 Top 6）+ 渲染小多图 + 图注声明 |
| P1-3 | 异常表金额（Amount×fx）与 KPI 金额（fill×p_avg×fx）不同源无校验；Amount 缺失路由被金额门槛静默误杀 | DP-3：探针仅披露（Amount 为展示权威列，不静默替换）；门槛口径改 `COALESCE(Amount, fill×p_avg)×汇率`；容差 0.5% | ✅ 已修：一致性探针增 `amount_check/mismatch/consistency_pct`，数据质量区披露；`_anomaly_notional_usd_expr` 改 COALESCE；`anomaly_notional_gate` / `amount_consistency_tolerance_pct` 落 SPEC |
| P1-4 | order_par_gt100 critical=200 档与一致性探针（只统计 >100%）无对应分档 | DP-3 附带 | ✅ 已修：探针增 `order_par_gt200_orders`，数据质量区文案分档「其中 >200% 的 N 个疑重复记账」 |
| P1-5 | 冲击截断 share 分母为 `COUNT(*)`（全量路由）而非冲击计算样本，渗透度被稀释 | DP-4：分母 = 任一冲击指标可计算的路由（truncated 路由冲击值非 NULL，必然落在分子分母内，口径自洽） | ✅ 已修：`impact_sample_count` 随 payload 披露，share 分母改冲击样本，文案改「占冲击计算样本」；`impact_truncated_share_denominator` 落 SPEC 并绑定实现常量 |

附带修复：`anomaly_query.query_anomaly_routes_page` 表缺失 / 库缺失两条路径返回裸 `[]` 而非
`([], 0)` 元组（调用方解包即崩）—— 顺手对齐元组契约。

同批：`SPEC_VERSION` → `2026.09.4`；`_RANKING_MIN_SAMPLE` / `_RANKING_MIN_NOTIONAL_SHARE` /
`IMPACT_TRUNCATED_SHARE_DENOMINATOR` 等实现常量与 SPEC 结构化绑定（R5 模式）。

护栏：`CostView/tests/test_report_metrics.py`（`TestRankingSampleGate` / `TestPwpWeighting` /
`TestAmountConsistency` / `TestImpactTruncatedShare`）；既有
`test_rankings_grouped` / `test_rankings_disclose_sample` / `test_impact_breakdown_counts_truncated`
已对齐新口径（门槛生效 / 双侧输出 / 冲击样本分母）。

#### 第八轮合入后独立复核（post-merge，#31 squash 后）

| # | 发现 | 处置 |
|---|------|------|
| F-a（中） | `_anomaly_notional_usd_expr` 的 COALESCE 单一表达式同时喂给门槛与 USD 展示列 —— Amount 缺失路由的 USD 列被 fill×p_avg 估算值静默替换，与本币权威列（Amount）同行自相矛盾，且与数据质量区「异常表金额以 Amount 为准」文案冲突（DP-3「展示不静默替换」只落了本币列） | ✅ 已修：拆为 `_anomaly_notional_exprs` 返回 (展示, 门槛) 双表达式 —— 展示 = Amount×fx（缺失 → "-"，口径回到 P1-a 之前）、门槛 = COALESCE×fx；护栏固化「Amount 缺失 → notional_usd 为 None」「Amount 在 → 展示忠实 Amount（与 fill×p_avg 解耦）」 |
| F-b（中低） | gt200 阈值两处字面量（探针 `par_sum > 2.0` 与规则 critical=200），改档时探针文案静默脱钩 | ✅ 已修：`report_measure.ORDER_PAR_CRITICAL_SUM = 2.0` 唯一实现源，规则 critical 与探针同引用；SPEC 增 `order_par_critical_gt`，测试断言三处一致 |
| F-c（中低） | `footer_text()` 未随 P0/P1-a 扩展，七项新增 SPEC 声明不进归档脚注，口径自证出现缺口 | ⏩ 归入 P1-b（与 D1 的 `chart_axis` 声明同属脚注/声明层批次），由 SPEC 常量插值生成、护栏断言脚注含各绑定值 |
| F-d（低） | PWP 小多图各面板独立 y 缩放（跨市场视觉比较失效，D1 同族）；聚合 PWP 面板未渲染各档 weight_coverage note（披露断在最后一公里） | ⏩ 归入 P1-b 的 D1 轴工作（小多图共享统一 y 域 + `_weight_note` 接入） |
| F-e（提示） | 排行金额占比分子要求 pnl_vwap 非 NULL、分母为全部可加权成交额，轻微不对称（方向保守，0.1% 下不可达） | ✅ 已修：`_query_rankings` docstring 补口径说明 |
| F-f（提示） | D15 分母自洽依赖写入方不变量「truncated 路由冲击值非 NULL」，不变量破坏时 share 理论可超 1 | ✅ 已修：分母取 `max(impact_sample, truncated_count)` 防御（不静默钳制数值、不掩盖上游违约） |



#### 开放验证项（黄金样本证据 → 生产证据的最后一公里）——✅ 已闭环（2026-09-15 第十轮哨兵触发）

- **D8 逐行回退路径**：✅ 已验证（生产）。哨兵命中历史区间 20250926~20260421 共 2735 条非 USD
  路由缺 `fx_rate`；对该窗口新旧口径对比：旧 270,408,717,327 → 新 USD 34,769,191,285，
  **未换算本币金额 355,449,145,419（占比 91.09%）** —— 旧口径「整组 COALESCE 回退」把这些
  本币金额静默混入/丢弃，新口径全部转为显式披露；minor-unit 修正同时消除（近 10 天窗口
  fx 全覆盖、差异 −86.77% 与黄金样本 −91.24% 同因，均为 GBp 等小计价单位修正）。
- **D14 探针「零误豁免」结论**：✅ 已升级为正式结论。生产样本（哨兵实时校验）：全历史
  bdib_gap 217 条、p_arrival NULL 1182 条（含零成交 / 收盘竞价等其他结构内 NULL），
  **「探针命中但 p_arrival 可计算」的过度豁免计数为 0**（四项全 NULL 蕴含 p_arrival
  NULL，该矛盾计数是方向可靠的告警量）；此前黄金样本 333 条同样零过度豁免。
  *勘误（第十一轮 F-g）*：初版「217 条均落在 1182 条 NULL 集内」的全表基数对比不严谨
  （bdib_missing 四指标各计一条 NULL，两集合基数不可比），校验已改为按日配对
  （逐日探针命中数 ≤ 当日 p_arrival NULL 数，见哨兵脚本）。
  **语义边界（F-h）**：本结论仅覆盖**过度豁免**方向（SLA 被高估）；**豁免不足**方向
  （真实 BDIB 缺口未被探针剔除、SLA 被低估）需要 BDIB 原始数据方可自动校验，超出轻量
  探针边界——该方向的规模由覆盖率行级披露 `bdib_gap_routes` 承接观测，不做自动校验，
  勿将「零过度豁免」读作双向证明。
- 后续由 `scripts/ops/open_validation_sentinel.py` 周期哨兵守护（触发条件再现时提醒复核；
  周期调度的接线方式见第十轮 P2-3 行）。

### 2026-09-15 — 第九轮（P1-b 呈现层：双轴零轴 / 节流披露 / 脚注扩展 / 小多图共享域）

| # | 缺陷 | 处理 |
|---|------|------|
| P1-6 | D1：按日双折线各自独立归一、无零轴、无刻度 —— 负成本区间最优点被映射到底部（读者得出相反结论），离线归档无通道还原真实数值 | ✅ 已修：`_svg_daily_series` 重写为双轴 + 零轴 + 5 档真实刻度（DP-5 硬规则：左轴 pnl_vwap 对称含零、零轴虚线强调；右轴 par_rate 零锚定 [0, max×1.1]）；市场金额趋势改零锚定（min 锚定的 5% 伪波动消除）；`chart_axis` 落 SPEC 并与渲染层 `REPORT_SPEC_CHART_TICKS` 绑定；SVG 产物护栏断言零轴虚线/负刻度/「最负点在底部」 |
| P1-7 | D6：`min_fill_count` / `min_notional_usd` 的排除量发生在循环内不进任何返回字段，读者无从得知异常清单被截取多少 | ✅ 已修：新增 `query_anomaly_routes_page_ex` 返回 `(rows, total, throttle_stats)`（阈值命中 / 笔数剔除 / 金额剔除 / 豁免 / fill_count 缺失标记），旧二元签名保留为兼容包装（一个版本周期）；双解包点（`query_anomaly_routes` 内部、`build_report`）同 PR 改造并同测；payload 增 `anomaly.throttle`，明细 notes 区披露「异常节流：…」 |
| P1-8 | F-c：`footer_text()` 未随 P0/P1 扩展，七项新增 SPEC 声明不进归档脚注，口径自证出现缺口 | ✅ 已修：新增 `_p0_p1_footer_clauses()`，排行门槛 / PWP 加权 / 金额门槛 / gt200 分档 / 冲击分母 / 缺口金额 / TCA 检测 / 轴策略全部由 SPEC 绑定常量插值生成（不手写数值）；护栏断言脚注含各绑定值 |
| P1-9 | F-d：PWP 小多图各面板独立 y 缩放（跨市场视觉比较失效）；聚合面板未渲染 PWP 各档覆盖 note | ✅ 已修：`_svg_pwp_curve` 增可选 `domain` 参数（缺省独立归一，聚合面板不受影响），小多图跨面板共享 y 域；新增 `_pwp_coverage_note`（五档任一覆盖不足即提示最差权重覆盖） |
| 流程 | SPEC_VERSION 未随 F-a 口径修正 bump：#31 与 #33 共用 2026.09.4，#31 归档 HTML 的 USD 展示列与 #33 后产出不同，同版本号不同产出 | ✅ 已修：`SPEC_VERSION` → **2026.09.5**。**#31 归档例外**：该期间归档的 HTML 在 Amount 缺失路由上 USD 展示列为 fill×p_avg 估算值（F-a 修复前口径），#33 起为 Amount 权威口径（缺失显示 "-"）；#31 归档报告无法凭版本号自证该口径，需按生成日期判读 |

护栏：`CostView/tests/test_report_metrics.py`（`TestChartAxisPolicy` / `TestAnomalyThrottleDisclosure` /
`TestReportSpec.test_footer_covers_p0_p1a_p1b_declarations` /
`test_chart_axis_policy_binds_implementation`）；双解包点覆盖：
`test_throttle_stats_counted`（新签名）/ `test_legacy_two_tuple_signature_still_works`（旧签名兼容）/
`test_build_report_discloses_throttle`（第二解包点 + 渲染披露）。

### 2026-09-15 — 第十轮（P2 首批：双端标记对齐 / X7 端到端测试 / 开放验证项主动哨兵）

| # | 事项 | 处理 |
|---|------|------|
| P2-1 | 前端异常明细表未渲染「超成交 / >100%」标记（HTML 端已披露，双端不对账 —— G1/F1 同族，按复核建议提为 P2 首项） | ✅ 已修：`AnomalyTable.tsx` 完成率单元格附「超成交」标记、订单参与率单元格附「>100%」标记（`TcaAnomalyRow.overfill` / `order_par_gt100` 字段既有）；新增 `anomaly-table.test.tsx`（命中渲染 / 未命中不渲染两条断言，文案与 HTML 逐字对齐） |
| P2-2 | X7 悬空承诺：export-html 的 zip 响应缺端到端集成测试 | ✅ 已修：`test_monitoring.py::TestExportHtmlZipClosure` —— 有明细 → 断言 zip 响应（media_type / 文件名 / 包内 HTML+CSV / export_ref 回填 / CSV 内容）；无明细 → 纯 HTML 下载。X7 自此闭环 |
| P2-3 | 开放验证项被动挂账（等数据出现），存在被淡忘风险 | ✅ 已修：新增 `scripts/ops/open_validation_sentinel.py` 只读哨兵（D8 缺 fx 探针 + D14 探针过度豁免比对，`--strict` 供质量门接线），并注册每周定时任务 —— 首轮运行即命中 D8（见上方开放验证项闭环记录） |

本批不涉及口径变更，`SPEC_VERSION` 维持 `2026.09.5`。

### 2026-09-15 — 第十一轮（终验复核：哨兵探针按日配对 / D14 结论语义边界）

| # | 发现 | 处置 |
|---|------|------|
| F-g（中低） | 哨兵 D14 探针为无 GROUP BY 的全表 SUM：bdib_gap 探针要求四项全 NULL，而 bdib_missing 类指标（p_arrival/p_close/arrival_cost_bps/close_cost_bps）各计一条 NULL —— 同一缺口日两集合的全表基数数学上不可比，「217 vs 1182」判读无效（核心告警量 `over_exempt` 方向仍可靠，哨兵功能未受损） | ✅ 已修：探针改按日配对（`GROUP BY order_as_of_date`，逐日「探针命中数 > 当日 p_arrival NULL 数」即告警并列出问题日），台账判读同步勘误；首轮按日校验结果维持零过度豁免 |
| F-h（低） | D14「零误豁免」校验只覆盖过度豁免方向；豁免不足方向（真实缺口未被剔除、SLA 被低估）需 BDIB 原始数据、超出轻量探针边界，当前不可见 | ✅ 已登记：台账开放验证项段补语义边界声明（豁免不足方向由 `bdib_gap_routes` 行级披露承接观测、不做自动校验），防止「零过度豁免」被读作双向证明 |

审计跟踪责任自本轮起正式移交哨兵机制：`SPEC_VERSION = 2026.09.5` 起归档报告可自证完整
口径，开放验证项由 `scripts/ops/open_validation_sentinel.py` 周期守护。

### 2026-09-21 — 第十二轮（026 阶段一：聚合粒度与期间键）

| # | 事项 | 处理 |
|---|---|---|
| G1 | 报告时间维度只有「查询窗口」、无「聚合粒度」：走势与分市场金额趋势锚在日粒度，无法按周观察执行质量 | ✅ 已修：引入 `granularity`（`day`/`week`/`month`，默认 `day`）；`day` 为**恒等映射**（既有按日产出逐字节不变）；`week` 为 ISO 8601 周键且用**纯 SQL 算术**实现 —— 本环境 SQLite 3.45.3 不支持 `%G`/`%V`（返回 NULL），`%Y-%W` 会拆跨年周，故按「当周周一 → 该周周四所在年份 → julianday 差除以 7」计算；期间键单点落在 `report_measure`；`granularity=week` 下的分市场金额趋势即「分市场 × 周度」交叉视图，不另造查询 |
| G2 | 粒度未进入报告自证链：归档 HTML 无法判断横轴是「日」还是「周」 | ✅ 已修：`filters.granularity` + `daily_series_meta.granularity` + `metric_coverage.granularity` 随 payload 披露；脚注由 SPEC 常量插值生成粒度声明（`_granularity_footer_clause`） |
| G3 | 粒度参数缺校验时可能静默按日返回，调用方误以为拿到周度结果 | ✅ 已修：`validate_granularity` 非法值**显式报错**（不静默降级），API 层经 `ValueError` → 422 |

护栏：`CostView/tests/test_report_metrics.py::TestGranularityPeriodKeys`（10 条：跨年周归属 /
空周不补零 / 单日周 / 月键格式 / 分市场 × 周度金额守恒 / `day` 键恒等 / 非法粒度报错 /
覆盖率粒度分组 / SPEC-实现绑定 / 脚注声明）。

同批：`SPEC_VERSION` → **`2026.09.6`**；`REPORT_SPEC` 新增 `granularities` /
`default_granularity` / `week_key_mode` / `period_series_no_fill`；`__init__.py` 导出
`GRANULARITIES` / `DEFAULT_GRANULARITY`（`__all__` 护栏同步）。

**正确性证据**：边界日期 73 个 + 真实库 194 个 distinct 交易日对照 Python `date.isocalendar()`
**零不一致**；真实库聚出 51 个 ISO 周（`2025-W39` ~ `2026-W38`）。

### 2026-09-21 — 第十三轮（026 阶段二：执行环境变量精确化）

| # | 事项 | 处理 |
|---|---|---|
| H1 | `time_of_day` cohort **恒为 `unknown`**（活跃表不带 `start_time`），该维度完全失效 | ✅ 已修：新增 `CostView/src/monitoring/env_context.py`，从 `fill_bdib.mkt_timestamp` 按路由取最早成交时刻；实测可得率 **100%**（173,685 / 173,685），时段分布 close 106,939 / open 35,909 / mid 30,837 —— 分层已真正生效 |
| H2 | `liquidity_adv20` 用 `par_rate`（区间参与率）代理 ADV20 占比 | ✅ 已修：改用 **`fill / bdib_daily_summary.adv_20d`**（`adv_20d` 实测覆盖 **99.39%**）；这是一次**口径变更**，新口径与降级口径均已写入 `report_spec` |
| H3 | `volatility` 用 `\|pnl_vwap\|`（**成本**）代理日波动率 —— 用成本代理环境变量、再按它分层比较成本，构成**循环论证** | ✅ 已修：改用 `bdib_daily_summary.daily_volatility`（实测覆盖 **99.94%**）；成本代理仅保留为 L3 降级兜底 |
| H4 | 环境变量不可得时无任何披露（静默使用代理） | ✅ 已修：三级降级链（L1 真实 / L2 自给 / L3 代理），可得率经 `scorecard.filters.env_coverage` 随 payload 披露；任一维度不可得均为**可见事实** |
| H5 | 计划原判「`raw_bdib` 与 `fill_bdib` 的 `mkt_timestamp` 存在两套值域」为**最高风险** | ✅ 实测**不成立**：两表均为 8 字符 `HH:MM:SS` 纯时间，`bucket_time_of_day` 现有解析可直接工作。**但**测试夹具用全时间戳（`'20260418 10:10:00'`）与生产形态不一致 —— 已新增 `normalize_start_time` 兼容两种形态并加护栏 |

护栏：`CostView/tests/test_env_context.py`（16 条：双形态归一化 / 真实分桶与边界 / 代理回退 /
真实路径不引用成本量 / 三维度独立降级 / 来源缺失不抛错 / 聚合接线 / 可得率披露 / SPEC 绑定）。

同批：`SPEC_VERSION` → **`2026.09.7`**；`REPORT_SPEC` 新增 `env_cohort_sources` /
`env_cohort_fallbacks` / `env_coverage_disclosure`。

**降级链语义**：`env=None` 与「字段为 `None`」等价 —— 参数默认值天然构成降级路径，
无需额外开关（设计决策见 plan §4.2 DP-2-4）。

### 2026-09-21 — 第十四轮（026 阶段三：科学方法评估层）

**背景**：报告此前只有**描述统计 + 人为样本门槛**（`min_sample_size` 默认 10、排行 n ≥ 5 且金额占比 ≥ 0.1%），
**无任何统计推断能力**；broker / algo 排行是**原始均值排序**，未做可比性控制 —— 按 B3 口径属
「结论过度自信」。ADR-0004 规划的 `CostView/src/evaluation/` 目录**此前从未落地**。

**本批交付**（`CostView/src/evaluation/`，5 个模块）：

| 模块 | 内容 |
|---|---|
| `comparability.py` | 可比样本匹配与**可比性判定**（分层键 = 阶段二五个真实维度；失衡度量 = 总变差距离，阈值 0.2）—— **服务端强制**（plan §5.2 DP-3-2） |
| `stats_tests.py` | t（Welch）/ KS / χ² 三类检验 + **bootstrap 可信区间** + **多重比较校正**（BH / Bonferroni） |
| `power.py` | 样本功效、最小可检测效应（正态近似闭式公式；**不引入 statsmodels**） |
| `cost_model.py` | 幂律冲击函数估计（对数空间 OLS；**域外一律不外推**，且不作事前预测 —— K3 不在本计划范围） |
| `governance.py` | 治理元数据（版本锁定 / 基准冻结 / 数据血缘 / 降级披露）；**基准不可默认**（D1） |

**关键约束如何落地**：

- B3「只有在这些维度足够相似时，跨经纪商或跨策略比较才具有解释力」→ `assess_comparability`
  在不可比时返回结构化判定（原因 + 失衡维度 + 共有层数）并**不返回比较数值**；
  若该检查只放 UI 层，直接调 API 仍可取原始均值比较，约束形同虚设。
- D1「而不是事后挑选最有利基准」→ `evaluation_metadata(benchmark=…)` **无默认值**，缺失即报错。
- 检验方法三选一**不得只报最有利者**（与 D1 同源要求，`TestResult` 随 `method` 返回）。

**依赖**：新增 `scipy>=1.11`（plan §5.2 DP-3-1 裁定：检验正确性不可妥协，不自行实现 t / KS / χ²；
不引入 `statsmodels` —— 功效由正态近似闭式公式自实现）。

**护栏**：`CostView/tests/test_evaluation.py`（34 条：导出护栏 / 可比性判定与失衡拒绝 /
三类检验与样本不足披露 / bootstrap 区间 / 多重比较 / 功效与闭式解对照 / 冲击模型参数恢复与域外不外推 /
治理元数据与基准强制 / SPEC 绑定）。

同批：`SPEC_VERSION` → **`2026.09.8`**；`REPORT_SPEC` 新增 `evaluation` 块
（分层键 / 失衡度量与阈值 / 检验方法 / 可信区间 / 多重比较 / 基准强制 / 服务端强制可比性）。

**尚未接入端点**：评估层的 API 端点（`POST /api/tca/evaluation/compare` + `TCA_EVAL_ENABLED` 门控）
与前端评估视图属后续批次；本批交付的模块与测试已可独立使用与审计。

### 2026-09-21 — 第十五轮（026 阶段三收尾：评估端点与门控）

第十四轮交付了评估层模块，但**没有可调用入口** —— 模块只能被测试调用，用户侧仍只能看
原始均值排序，DP-3-2 的「服务端强制」因此**没有落点**。本轮补齐端点、门控与能力位。

| # | 事项 | 处理 |
|---|---|---|
| I1 | 评估层无可调用入口 → 可比性约束无落点 | ✅ 已修：新增 `POST /api/tca/evaluation/compare`；可比性判定在**服务端**执行，不可比时 `verdict.comparable=False` 且 `comparisons` 为空数组，**不返回任何比较数值** |
| I2 | 基准可省略 → 留下「事后挑选最有利基准」的口子（D1） | ✅ 已修：`EvaluationCompareRequest.benchmark` 为**必填**字段（pydantic 校验 → 422），服务端不设默认值 |
| I3 | 关闭评估时若回退到未校验的均值比较，等于放弃可比性约束 | ✅ 已修：`TCA_EVAL_ENABLED=0` 时返回**显式不可用**（`enabled=False` + 说明），**不提供**未校验比较作为回退 |
| I4 | 前端 / 运维无法感知评估能力是否启用 | ✅ 已修：`GET /api/tca/capabilities` 新增 `evaluation` 能力位（对齐 `order_level_tca` 既有范式） |
| I5 | 多重比较的校正代价不可见 | ✅ 已修：每对比较同时返回 `p_value` 与 `p_value_adjusted`（BH / Bonferroni 可选） |
| I6 | 样本不足时只给「不可比」判词，无行动指引 | ✅ 已修：`power` 块给出 `smallest_group_size` / `sufficient` / `minimum_detectable_effect`（「多大差异才可能被检出」） |

护栏：`CostView/tests/test_evaluation.py` 的 `TestEvaluationComparisonOrchestration`（8 条：
基准必填 / 未知基准 / 未知维度 / 不可比不含数值 / 可比含校正后 p / 功效指引 / 治理随结果 /
基准映射封闭）与 `TestEvaluationRequestModel`（3 条）。

**未 bump `SPEC_VERSION`**：本轮为**接入**（把已声明的口径接到端点上），口径本身未变。

### 2026-09-21 — 第十六轮（027 综合评估报告：形态与可比性修正）

**触发**：用户查看前端 Evaluation 模块后反馈「比较维度、基准、检验方法等不应该是选择的，
用户需要的是全面的综合评估」，并报告「点击开始评估提示评估失败」。

**八项问题（均已修）**：

| # | 事项 | 处理 |
|---|---|---|
| J1 | **形态错位**：026 的评估是「用户选 1 个维度 + 1 个基准 + 1 种方法 → C(n,2) 两两检验表」，与「按时间范围自动产出的综合评估」不符 | ✅ 已修：维度**遍历全部**（7 个）、基准**并列**（4 个）、方法**并列**（3 个）；端点改为 `POST /api/tca/evaluation/report`，`/compare` 移除；请求仅接受时间范围与粒度 |
| J2 | **可比性门禁在真实数据上恒为拒绝**：`Exchange` 的 TVD 实测恒等于 1.0（券商成交本就横跨多个市场），且 5 维交叉后 `common_strata = 0` | ✅ 已修：改为**层内比较 + 样本量加权合并**；失衡降为描述性提示；可信度以 `confidence` / `coverage` 披露（结论照出） |
| J3 | 控制维度与分组维度重叠 → 按 `time_of_day` / `liquidity_adv20` / `volatility` 分组时分层退化为 1 层 | ✅ 已修：分层键**排除当前分组维度**（正交）；实测 `time_of_day` 恢复为 21 层 / 0.85 覆盖 |
| J4 | `_chi2_on_buckets` 分桶出现空桶时 `chi2_contingency` 抛 `ValueError`（026 小样本用例未覆盖，真实库首次触发） | ✅ 已修：过滤空桶；退化时 p=1 并由 note 披露 |
| J5 | `_market_section` 用 `cohort_key_and_label` 处理 `Exchange`（非 `SCORECARD_COHORTS` 成员）→ 全部落同一标签，实测仅 1 行 | ✅ 已修：改用 `dimension_label`（实测 29 个市场） |
| J6 | 可信区间与检验方法无关，却被放在方法循环内重复 bootstrap 3 次（真实库 **153 秒**） | ✅ 已修：提取到循环外 + 重采样次数按报告耗时取值（**5.9 秒**，约 26 倍） |
| J7 | 主基准整列缺失时无提示，「无数值」会被读成「无差异」 | ✅ 已修：显式告警，并说明其余基准仍照常给出 |
| J8 | 026 遗留 T16：门控降级分支无端点级用例 | ✅ 已修：`TestEvaluationEndpoint` 覆盖 |

**报告内嵌**：空报告亦带 `evaluation` 键；HTML 新增评估摘要章节（置于覆盖率之前）；
评估失败**不阻断**报告生成（与各小节可独立降级一致）。

**前端**：移除全部选择器；进入视图即按时间范围**自动**评估；改为分维度明细 + 趋势 /
风险 / 市场小节；取数改用 `@shared/hooks/use-async-data`；Report 页内嵌同源摘要。

**版本**：`SPEC_VERSION` `2026.09.8` → `2026.09.9`（评估口径整体重写）。

**待观察（如实登记，不视为已解决）**：`volatility` 维度的 `daily_volatility` 分桶几乎全部
落 `Stressed` 一档（实测 1998 / 2000 条），导致该维度分层退化 —— 分桶阈值口径待核实
（`report_spec` 目前未覆盖该项）。

### 2026-09-21 — 第十七轮（028：波动率量纲统一与分桶阈值修正）

**触发**：027 收尾时实测 `volatility` 维度分层退化（`Stressed` 占 83%、`Typical` 仅 0.61%）。

| # | 事项 | 处理 |
|---|---|---|
| K1 | `bucket_volatility` 用**日**波动率阈值（1.5/3.5）解读**年化**列 —— 反推公式 = std(日对数收益率) × √252 × 100（12/12 个月比值 ≈ √252），实测中位 26.075 | ✅ 已修：阈值对齐年化空间（**25 / 40**，与 `market.py:50-51` 解读同一列的既有口径一致），标签同步（`<25% ann.` 等） |
| K2 | 同一列两种量纲：上游在 **202603/202604** 区间写入**年化小数**（同标的跨时段跳变 ≈ 100 倍，如 `1942 JP` 43.566 → 0.435 → 45.917 → 恢复） | ✅ 数据入口归一化：`env_context.normalize_volatility_to_percent`（< 3.0 判为小数 → ×100）；命中数经 `env_coverage.volatility_scale_fixed` 披露，**不得静默修数** |

**修复后实测**（全量 217,269 行）：calm **30.82%** / typical **35.65%** / stressed **33.53%**
（恢复区分度）；归一化命中 **16.79%**（36,480 行）。

**未解决（跨仓项，如实登记）**：上游 202603/202604 的量纲不一致需在写入侧修正；本侧归一化
是过渡措施。`daily_volatility` 的权威定义（年化百分比）来自统计反推（比值 ≈ √252），
**需上游确认**。

**日内波动率字段核实**：`bdib_daily_summary.intraday_volatility`（值域 0~15.27，非空率
38.7%）与 `fill_bdib.cum_interval_volatility` / `standard_cum_interval_volatility`（非空率
31.8%）的量纲判定**于 2026-09-22 被上游纠正**：`intraday_volatility` **已年化，但为
小数形态**（`std(10 秒对数收益率) × sqrt(BARS_PER_YEAR)`）。我最初按 `intraday/daily`
得到 0.0149 并判为「未年化」，**属单位未对齐**（daily 为百分比、intraday 为小数）；
正确判据 `intraday/(daily/100)` 实测中位 **1.25** ≈ 1.3，即两列同为年化。

推论更正：若以该列做分层，须先 ×100 转百分比后再套年化阈值（25/40），
而不是套日波动率阈值。详见第十八轮与本轮勘误。

**版本**：`SPEC_VERSION` `2026.09.9` → `2026.09.10`。证据全文：
`docs/archive/2026-09-21/028-volatility-scale-fix/research.md`（含 8 个探测脚本清单与两次误判的修正记录）。

### 2026-09-22 — 第十八轮（028b：波动率量纲跨仓闭环；归一化下线改纯监测）

**上游答复（2026-09-22）**：跨仓请求已闭环，`daily_volatility` 的权威定义与根因均已明确：

| 项 | 结论 |
|---|---|
| 权威定义 | **直取 Bloomberg `VOLATILITY_30D`**（30 交易日年化历史波动率，**百分比单位**），非本地计算 —— 本侧反推结论成立 |
| 写入路径 | 全仓库仅一条（无第二条计算路径） |
| 根因 | **单次运行批次** `computed_at = 2026-04-22`，覆盖 `20260302~20260420`：36,547 行中 36,372 行为小数写法（÷100）；属**抽取（2026-09-02）之前**的旧版写入产物 |
| 已修复 | 回填 36,372 行 ×100（含备份与幂等保护）+ 新增**批次级中位数守卫**（3 项配置、6 例单测）防复发 |

**本侧复核（只读，与上游报告完全吻合）**：

| 项 | 上游报 | 本侧复核 |
|---|---|---|
| 月均值 202603 / 202604 | 53.11 / 50.85 | **53.11 / 50.85** |
| `1942 JP Equity` 202603 | 34.4~72.0 | **34.428~72.012**（逐日一致）|
| `daily_volatility < 3` | 36,372+ → 残余 | **36,480 → 112**（降 99.7%）|

**关键变更（本轮）**：028 引入的「小数写法归一化」**已下线**，改为**只检测不修改**。

理由是复核发现残余 112 行 `< 3` 经核对为**真实低波动标的**（`K US Equity` 1.16~1.46、
`ITRK LN Equity` 1.43~1.46、`6201 JP Equity` 1.23），其中 **63 行来自完全正常的
`2026-08-19` 批次**，`2026-04-22` 批次仅剩 4 行。即 `< 3` 已不再等价于「量纲错误」，
继续 ×100 会把这些真实值**误放大 100 倍**（年化 1.16% → 116%）—— 这正是 028
风险评估中预告的情形，现按上游建议收敛。

| 变更 | 前（028） | 后（028b） |
|---|---|---|
| 函数 | `normalize_volatility_to_percent`（×100） | `volatility_scale_suspect`（返回 `bool`）|
| 路由字段 | `volatility_normalized` | `volatility_scale_suspect` |
| 披露键 | `env_coverage.volatility_scale_fixed` | `env_coverage.volatility_scale_suspect` |
| 数据 | **被修改** | **原值直传**（登记不修改）|

**不变**：`bucket_volatility` 阈值（25 / 40）—— 它按年化百分比解读，与上游确认的权威定义
一致，028 的该项修复继续有效。`report_spec` 新增 `volatility_source` 字段记录来源。

**版本**：`SPEC_VERSION` `2026.09.10` → **`2026.09.11`**。

**待办**：上游该批次 168 行 `≥3` 的边界清单核对（本侧按需抽查）；上游下次管道运行后复查
守卫未误触发。

### 2026-09-22 — 第十九轮（跨仓二次往返：一处本侧结论被上游纠正 + 清单抽查）

**① 上游已提交推送**：commit `266e131`（7 files, +359/−5），修复与防复发守卫进入版本历史与远端 ——
「改动只在工作区」的风险已消除。

**② 本侧一处结论被上游纠正（已在文档就地更正）**

| 项 | 本侧原结论 | 上游核实 | 正误 |
|---|---|---|---|
| `intraday_volatility` 量纲 | **未年化**（据 `intraday/daily` 中位 0.0149） | **已年化，小数形态**（`std(10 秒对数收益率) × sqrt(BARS_PER_YEAR)`，`BARS_PER_YEAR ≈ 589,680`）；正确判据 `intraday/(daily/100)` 中位 **1.28** | **上游正确** |

**错因**：我用了 `intraday / daily` 直接相除，但 `daily_volatility` 是**百分比**口径
（Bloomberg `VOLATILITY_30D`）、`intraday_volatility` 是**小数**口径 —— 0.0149 只是
「百分比 ÷ 小数」的单位差，与年化与否无关。本侧复测对齐后中位 **1.2501**，与上游 1.28 一致。

已在 3 处就地更正并保留错误推理原文（`028 research.md` §5、`028 plan.md`、本文件第十七轮）。
**推论更正**：该列若用于分层须先 ×100（而非套日波动率阈值）。

**③ 168 行 `≥3` 清单抽查（上游提供，32 标的 / 168 行）**

按上游建议抽查 5 个「批次内自洽但与该标的 8 月批次相差 3~10 倍」的标的，
用同表 `daily_close` 自算 20 日年化百分比 ÷ 列值（**≈1 表示列值正确**）：

| 标的 | 4-22 批次 | 8 月批次 | 观察 |
|---|---|---|---|
| `BUMI IJ Equity` | **20.361** | 2.176 | 两批均偏离 1 |
| `MTLNEUR EU Equity` | **8.767** | — | 偏离 |
| `GOTO IJ Equity` | **3.813** | — | 偏离 |
| `EMN SJ Equity` | **3.767** | — | 偏离 |
| `EUROBEUR EU Equity` | 0.567 | 1.292 | 方向相反（列值偏大） |

**结论（如实报告，未下确定性判断）**：比值区间 **0.567~20.4**，**方向与幅度都不一致**
—— **不支持**「这些行统一漏了一个 ×100」的简单结论（若漏 ×100，×100 后比值应落到 ≈1 附近，
但 3.767→0.038、20.361→0.204 都远离 1）。更可能是这些标的的 `daily_close` 与其
Bloomberg `VOLATILITY_30D` 口径不适配（停牌 / 货币单位 / 拆股 / 稀疏报价），
需上游结合其**原始 Bloomberg 取值**核对，本侧仅凭 `raw_bdib` 无法定论。

**④ 守卫改进已获采纳**：上游在原判据上加 p90 辅助判据 —— `中位数 < 5.0` **且**
`p90 < 10.0` 才拒绝入库；仅中位数偏低而 p90 ≥ 10 时记 WARNING 放行。这消除了本侧指出的
「混合域小批次」误伤路径。本侧的量化依据（p25/p50/p75 = 17.31/26.08/37.90）已写入其配置注释。

**⑤ T18 观测方式已明确**：触发时写入侧产出可 grep 的日志
（`daily_volatility 量纲守卫触发` = ERROR 拒绝 / `daily_volatility 批次分布偏低` = WARNING 放行），
位置 `<REPO_ROOT>/logs/pipeline/`；下次日更（每日 10:00）或手动 `--once` 后告知结果。

**⑥ 兼容性**：本次修复**只改数据、不改 schema** —— 既有只读连接与查询无需调整；
`202603/202604` 的值已在库内更新，重新拉取即可。

### 2026-09-22 — 第二十轮（跨仓第三轮：权威核对完成，4-22 批次待覆盖授权）

**① 上游 Bloomberg 取数故障已定位并修复**（与本侧无直接依赖，但是 T18 观测的前提）：根因是
`blpapi 3.26.7.1` 把 `Session` 内部 handle 属性改名，而 `xbbg 0.10.3` 仍按旧名判断会话有效性
→ 会话缓存永不命中、单次 `blp.bdp` 触发 176 次建连 → BTE control channel 端口耗尽
（`errno 10048`）。上游新增 `bloomberg_compat.py` 注入兼容属性，7 处调用点统一改经该入口。

**② 168 行权威核对完成，结论与本侧抽查方向不一致（以权威源为准）**

上游用**列内值 ÷ Bloomberg 原始 `VOLATILITY_30D`** 核对 4-22 批次全部 36,367 个可配对行：

| 范围 | `ratio` 统计 | 结论 |
|---|---|---|
| 全批次（1,732 标的） | p25 52.1 / **中位 74.6** / p75 101.0；落在 80~125（即 ×100 精确成立）**仅 32.1%** | **该批次不是常数缩放** |
| 168 行（原值 ≥3） | 中位 **10.78**（p25 5.08 / p75 17.81）；落在 1 附近 **0 行**、落在 100 附近 **0 行** | 既不缺 ×100，也不是正确值 |

**与本人上一轮抽查的差异**：我用 `daily_close` 自算 20 日年化百分比 ÷ 列值，得到
`EMN SJ` = 3.767（指向「列值偏小」）；而上游用权威源得到该标的**库内偏大 2.0~3.5 倍**
（方向相反）。**原因**：本侧自算是 20 日窗口、且与 Bloomberg `VOLATILITY_30D`（30 日）
的计算细节不同，**方法精度不足以判定方向** —— 权威源核对为准。已确认的对应关系：
`JDEPEUR 20260410`（库内偏大 2.9 倍）、`EMN SJ` / `GOTO IJ`（偏大 2.0~3.5 倍）、
`AKZA EU 20260408` 同属这类异质值。

**③ 4-22 批次数据现状（`bdib_daily_summary.daily_volatility`，覆盖 20260302~20260420）**

| 行数 | 现状 |
|---|---|
| 36,372 | 已 `×100`，为**近似**年化百分比 —— 约 32% 精确（±25% 内）、约 56% **偏高 1.25~5 倍**、约 12% 偏低 |
| 168 | 保持原值，相对权威值**偏小约 10.8 倍**（中位）|
| 7 | NULL |

**④ 上游建议**：用 Bloomberg 原始值**覆盖**整批 36,367 行
（`verify_volatility_against_bloomberg.py --apply`，覆盖前自动备份、仅匹配有返回的行、
169 行无返回者不动），**等待本侧授权后执行**。

**⑤ `fill_bdib` 两列量纲已核实**（详见 `028 research.md` §5 更新）：`log_chg_pct_10s` 实为
**小数**对数收益；`cum_interval_volatility` 为**未年化** expanding std；`standard_cum_interval_volatility`
为前者 ÷ 批次全表非零均值 → **无量纲且跨批次不可比**。上游另登记一个**潜在缺陷**：
`log_chg_pct_10s` 用**未分组** `shift(1)`，多 ticker 合并输入下每个 ticker 首 bar 会与
上一个 ticker 末 bar 相除，且结果**依赖 chunk 划分（不可复现）**。

**⑥ 消费层建议（上游提出，本侧接受）**：覆盖完成前，若分析涉及 202603~202604 按
`daily_volatility` 分层/打标/阈值判定，应对该区间加敏感性说明或暂时排除。

**版本**：本侧代码未变（`SPEC_VERSION` 仍 `2026.09.11`）—— 本轮为文档与跨仓记录。

### 2026-09-22 — 第二十一轮（4-22 批次权威覆盖完成；本侧三项独立验证通过）

**执行**（本侧授权后由上游执行）：`verify_volatility_against_bloomberg.py --apply --min-value 0`

| 项 | 结果 |
|---|---|
| 覆盖写入 | **36,371 行** |
| 跳过 | 169 行（Bloomberg 未返回该 `(ticker, date)` 的 `VOLATILITY_30D`） |
| NULL | 7 行 |
| `ratio`（Bloomberg ÷ 库内） | median **0.750 → 1.000**；落 1 附近比例 **32.1% → 100.0%** |
| 168 行（原值 ≥3） | 覆盖前 median 10.780 / 落 1 附近 **0 行** → 覆盖后**全部 = 1.000（165 行，另 3 行无返回）** |

**本侧三项独立验证（上游请求用本侧口径复核）**

| 验证 | 本侧结果 | 判定 |
|---|---|---|
| 1 月均值与相邻月对齐 | 202602~202608 = 37.03 / **41.62 / 43.07** / 40.13 / 42.05 / 43.52 / 39.46 | ✅ 完全对齐 |
| 2 分桶分布（**本侧阈值 25/40**） | 全表 **33.18% / 37.70% / 29.11%**；4-22 批次 **19.81% / 40.13% / 40.06%** | ✅ 三分合理 |
| 3 `volatility_scale_suspect` 命中 | **168 行**（4-22 批次内 **60 行**） | ✅ 与上游预测**精确一致** |

验证 2 是上游无法自行复算的一项 —— 它按猜测阈值（15/35）得到 3.9%/57.7%/38.4%，
与本侧无关；用真实阈值 25/40 得到的是上表的合理分布。**本侧此前期望的「月均值 ≈50」
应作废**：那是覆盖前近似 ×100 的值（53.11/50.85），权威值 41.62/43.07 更贴近相邻月。

**净增 56 行的性质（重要，且验证了一个决策）**

覆盖前后全表 `< 3` 行数：**112 → 168**，净增 56 行，可完全对账
（`112 − 4 + 60 = 168`）。这 56 行的性质是：**真实年化波动率本就 < 3%，但覆盖前被 `×100`
抬进 ≥3 区间而被掩盖**；权威覆盖后回归真实值，因此**正确显形**。

> 这恰好验证了 028b「只检测不修改」的决策 —— 若本侧仍在执行 ×100 归一化，
> 这 168 个真实低波动值会被**误放大 100 倍**。本侧阈值 3.0 的登记语义正确。

**状态收敛**：该列现已与 Bloomberg 权威源**逐行一致**（除 169 行无返回者），
**不再需要任何下游归一化**。本侧 `volatility_scale_suspect` 保留为纯监测（不修改数据），
命中数从此反映的**就是**真实低波动标的。

**可回滚性**：上游提供三层备份（批次原始值 / 覆盖前库内值 / 逐行核对明细），本次变动可审计可回退。

### 2026-09-22 — 第二十二轮（T18 关闭：重启后守卫未触发；附带修复 9 交易日空窗）

**① 上游长驻进程重启（本侧授权）**

上游排查发现：日更调度器（PID 36116）与 Runner（PID 16968）均于 **9/21 08:18 启动**，
加载的是**修复前**的旧代码 → 9/22 10:00 的日更持续失败，且 session 序号累积到
`{5522020}`（约 552 万次建连尝试，正是缓存失效导致的资源泄漏）。

按本侧授权执行 `stop-data.ps1` + `start-data.ps1`：

| 项 | 重启前（旧进程） | 重启后（新进程） |
|---|---|---|
| 进程 | 36116 / 16968（9/21 08:18） | **46484 / 59224**（9/22 12:53:52） |
| `errno = 10048` | 累计 **82 条** | **0 条** |
| `Cannot connect to Bloomberg` | 累计 **83 条** | **0 条** |
| Health | — | `{"ok":true,"state":"idle"}` |

**数据未被污染**：`run_for_date` 在取数返回空表时直接返回 0、**不写库** —— 代价是该轮
日更空跑，而非脏数据。

**② T18 关闭：守卫未触发，判定常规运行**

重启后手动运行 S7 两日期（新代码路径）：

| 日期 | n | 批次中位数 | p90 | min | 判定 |
|---|---|---|---|---|---|
| `20260428` | 351 | **34.178** | **59.057** | 9.775 | 远高于拒绝阈值（中位<5 **且** p90<10）→ **放行** |
| `20260429` | 317 | **34.232** | **62.901** | 9.819 | 同上 |

写入行中 `daily_volatility < 3` 为 **0**，量纲为正常年化百分比。**T18 关闭。**

上游另改进（commit `e5253ad`）：守卫在**放行时也记录**批次 `n` / 中位数 / p90 ——
今后每次运行都可核验，不必只依赖触发时的日志。

**③ 额外交付：修复 9 个交易日的 S7 空窗（本侧独立复核通过）**

上游发现 `bdib_daily_summary` 在 **20260908~20260918 共 9 个交易日完全缺失**
（`raw_bdib` 有 bars 但 S7 无行），系 xbbg 故障期间日更 S7 全程失败所致；已补跑：

```
本侧复核（逐日吻合）：20260908 1252 / 09 1167 / 10 1162 / 11 414 / 14 1085
                      15 1274 / 16 508 / 17 525 / 18 1054     合计 8441 行 ✅
中位数 24.280~29.627   p90 48.377~63.914   min 1.470~1.722   <3 每日 1~2 行
```

补跑后 `202609` 已覆盖 `20260901~20260918` 全部有 bars 的日期，缺口消除；属**新增行**、
不覆盖既有数据。

**④ 运维经验（值得长期留档）**

> **修复型改动合并后，必须重启长驻进程才生效** —— 仅「代码已合并/已推送」不等于
> 「修复已部署」。

本轮这条经验已造成**两次症状**：

1. 上游：日更调度器与 Runner 未重启 → 修复在运行态等于未部署，日更持续失败并泄漏资源；
2. 本侧：backend API 为长驻进程，027/028/028b 的新端点与口径改动在旧进程内不存在
   → 用户报告「点击开始评估提示评估失败」（**注意**：本侧复核时 `127.0.0.1:8002` 亦
   无响应，故也可能是服务未启动或运行在其它端口，需确认）。

**本侧待办（已于同轮完成核对，结论与上两段判断不同 —— 见下）**

**⑤ 本侧实测更正：「评估失败」根因不在 backend（2026-09-22 实测）**

上游提供了一条端口旁证（其同机观测到本侧 backend 监听 **3000**、PID 14944、启动于
9/21 15:04:59）。据此刻本侧实测：

| 项 | 实测结果 |
|---|---|
| `GET http://127.0.0.1:3000/api/tca/capabilities` | `{"order_level_tca":true,"core_benchmarks":true,"risk_impact":true,"evaluation":**true**}` |
| `POST http://127.0.0.1:3000/api/tca/evaluation/report` | **HTTP 200**（端点存在且可用）|
| `127.0.0.1:8002` / `:3100` | 均无响应（actively refused）|
| `frontend/.env` | `VITE_API_URL=`（**空值**）→ 前端走相对路径 `/api/...` |
| `frontend/vite.config.ts:9` | `env.VITE_API_URL \|\| 'http://localhost:3000'` → 空值回退 **3000** |

**因此更正前文的两处判断**：

1. ~~「8002 无响应」表示服务未启动~~ → 实为**端口不匹配**，服务实际监听 3000；
2. ~~「backend 为长驻旧进程、新端点不存在导致 404」~~ → **不成立**：3000 上的 backend
   **已是新代码**（`evaluation` 位为真、新端点返回 200）。

**「评估失败」的真正嫌疑**：**前端侧** —— dev server 或浏览器仍加载改动前的前端 bundle
（仍调用 027 已移除的 `/api/tca/evaluation/compare` → 404）。

**验证步骤（T21，已执行完毕，2026-09-22）**

**⑥ 前端 dev server 残留导致「评估失败」（T21 执行结果，已闭环）**

静态确认：`CostView/module/` 中**已无任何 `/compare` 残留**（仅剩文档历史记录与
`data_access/config.py` 的一处过期注释），源码侧正确。

动态排查发现**两个残留 dev server**：

| 来源 | 日志 | 状态 |
|---|---|---|
| 9/15 20:31 启动 | `logs/service/frontend-20260915-203143.log` | 曾正常（5173），最后一条为今日 16:52 `vite.config.ts changed, restarting server...` |
| 9/22 13:58 启动 | `logs/service/frontend-20260922-135838.log` | 因 5173 被占用改起 **5174**，但**未成功监听** |

两者均**未监听端口**（`Get-NetTCPConnection` 无 node LISTEN），浏览器因此连到异常实例。
清理 9 个残留进程后单起一个 dev server，端到端验证**全部通过**：

| 验证 | 结果 |
|---|---|
| `GET http://localhost:5173/` | **200** |
| `POST /api/tca/evaluation/report`（**经前端代理**） | **200**，响应 5,383 字节 |
| `POST /api/tca/evaluation/compare`（已移除） | **404**（符合预期） |
| `GET /api/tca/capabilities` | `evaluation: true` |

**一个容易误判的坑**：dev server 监听 `localhost`，在本机**只绑 IPv6 `::1`** ——
用 `127.0.0.1:5173` 探测会得到「actively refused」而被误读为「服务未启动」。
**探测须用 `localhost`**，这一点在本次排查中差点造成第四次误判。

**剩余动作（需用户在浏览器侧完成）**：硬刷新浏览器以丢弃旧 bundle，然后确认
「Evaluation」页不再报错。

> 教训补充：本次「评估失败」先后被误判为①backend 未重启、②端口不匹配、③backend 旧代码，
> 三次都与实测不符，第四次（`127.0.0.1` 探测）亦差一步。**先实测再归因** ——
> 上游那条「同机观测到进程与端口」的旁证是第一个决定性线索，而**检查服务日志与
> 端口监听列表**才是最终定位手段。

### 2026-09-22 — 第二十三轮（T20 启动：实测证实 `log_chg_pct_10s` 跨 ticker 相除）

**背景**：上游在第三轮通知中登记了 `fill_bdib` 的一个缺陷（`compute_derived_fields` 的
`log_chg_pct_10s` 用**未分组** `shift(1)`），但未改动，约定「待本侧确有启用需求时再排期」。
本侧本轮**启动 T20**：先独立实测证实缺陷（避免凭上游描述转述），再据此提出排期请求。

**本侧实测（`fill_bdib` 只读，6,680,277 行）**

| # | 证据 | 数值 |
|---|---|---|
| 1 | `log_chg_pct_10s` 值域 | **−9.695 ~ +7.411** —— 10 秒对数收益不可能达到该量级 |
| 2 | 极端值行数 | `\|x\|>0.05` 11,629；`>0.1` 11,325；`>0.5` 9,373；`>1.0` 7,149；`>2.0` 3,669；`>5.0` 307 |
| 3 | 时间分布 | 极端行**全部落在 09:30 开盘首 bar**（抽样 12 条明细均为 `09:30:00` / `09:30:40`） |
| 4 | 受影响范围 | 抽样 3,000 个 (ticker, 日期) 组合，首 bar **可检出**异常率 3.3%（※ 第二十四轮修正：这是「可检出」比例，非污染率） |
| 5 | **rowid 相邻归因** | 每条极端行的 `rowid−1` 均为**另一 ticker 的 16:00 收盘 bar**：`NSC 09:30` ← `FTV 16:00`、`LIN 09:30` ← `BALL 16:00`、`ZM 09:30` ← `CBRE 16:00`、`DOV 09:30` ← `ZM 16:00` … |

第 5 条说明极端行是**序列首行**（其后邻行恰为另一 ticker 的末 bar），与上游描述一致。
（※ 第二十四轮修正：该相邻性是**插入顺序的产物、非契约**，也**不能**据以断定缺陷发生时
的实际配对 —— 详见下方「一处未能对上」。）

**一处未能对上，已由上游作答**：`ln(fill_px_本行 / fill_px_前一行)` 与列值**不吻合**
（10 条抽查 0 条吻合，如 `NSC` 列值 −5.718 vs 重算 +1.608）。当时判断为原计算基准价格列
在这些行**为 NULL**（`close` 非空率 64.4%、`vwap` 34.5%，仅 `fill_px` 100%）。
**上游第二十四轮给出准确答案**：计算时的相邻关系由 Python 侧 `pd.concat(chunk_dfs)` 的
拼接顺序决定，**与 rowid 无关**，故用 rowid 反推必然不吻合。
结论不变（该缺陷的精确数值无法从现存数据还原 —— 正是「不可复现」的体现），但**证据强度
需下调**：rowid 归因只能证明「数据排列形态」，属**间接**证据，此前称「铁证」不准确。

**下游后果（可直接观测）**：`cum_interval_volatility` 最大值 **37.7687**
（`GRAB US Equity 20260427`）—— 未年化 expanding std 达到 37.77 意味着累计区间内
存在极端对数收益，属该缺陷污染。对照 `standard_cum_interval_volatility` 同行为 0.0161，
说明其「除以批次全表非零均值」的归一化**恰好把异常压平**，反而掩盖了污染。

**本侧处置**：已按既定边界维持 —— 修复前**不启用** `cum_interval_volatility` /
`standard_cum_interval_volatility`（后者分母为批次内全局均值，跨批次不可比）。
T20 状态由 ⏳ 改为 🔄「本侧已启动排期请求」。

**请求要点（已发上游）**：修 `shift(1)` 的分组、说明是否回填历史、明确修复后的
可复现性验证方式。

### 2026-09-22 — 第二十四轮（T20 上游答复：修复已推送，存量回填待决定）

上游对本侧第二十三轮的实测证据作出答复并推送修复 `b153808`。本轮记录答复要点、
**本侧的独立验证**，以及**三处本侧认识被上游纠正**（诚实标注，避免错误结论留在文档里）。

**一、上游答复要点**

| 项 | 内容 |
|---|---|
| 根因 | **不是 schema 问题**，是「计算函数隐式依赖数据物理/返回顺序」的**契约缺陷**。正确性依赖三件不受控的事：① SQL 无 `ORDER BY` 时的返回顺序；② Python 侧 `pd.concat(chunk_dfs)` 的拼接顺序；③ `ticker_chunk_size` 的 chunk 划分 |
| 是否改 schema | **不需要**。`ALTER TABLE` 解决不了；`raw_bdib` 表结构无缺陷（PK 满足唯一性与时序查询，两个索引覆盖主要访问路径） |
| 修复 | `b153808`：① 新增 `_log_return_10s`（按 `(equ_ticker, order_as_of_date)` 分组 + 组内按 `mkt_timestamp` **稳定排序**取前值，按原索引对齐**不改变调用方行顺序**，首 bar 记 0）；② `stages_process` 回补路径 `raw_bdib` 查询加 `ORDER BY equ_ticker, mkt_timestamp`；③ 7 例单测（其中 4 例专证可复现性，**修复前必失败**） |
| 关键补充事实 | `raw_bdib` 是 rowid 表，**物理顺序 = 插入顺序 ≠ PK 顺序**；`(equ_ticker, order_as_of_date, mkt_timestamp)` 是独立索引。本侧观测到的「按 ticker 分组、组内时间有序」是**当前优化器 + 插入顺序的巧合产物**，随时可能变化 —— 把它当契约用正是本缺陷的根源 |
| 同类扫描 | 全仓 `.shift / .diff / .cumsum / .expanding / .rolling` 逐处核查，**仅 `log_chg_pct_10s` 一处未分组**（其余均按 `OrderId` / `market_code` 分组或作用于单标的序列）；同类错误在本仓**未成组出现** |
| **调用契约** | **同一 `(ticker, 日期)` 的当日完整 bar 序列必须落在同一批输入内**。生产路径按 **ticker** 切 chunk、回补路径一次读整日 —— 均天然满足。若按**行**切 chunk，断点行记 **0**（「前值不在本批次」的正确表达），不再伪造跨标的收益 |
| 对 `standard_cum_interval_volatility` 的提醒 | **确认并采纳**：它不具备检出此类异常的能力，不能用于质量检查；分母随批次变化、跨批次不可比 |
| 回填 | **未执行**（本轮仅代码 + 测试，未动任何存量数据）；成本已量化，待本侧决定 |
| 回归 | 144 passed；另有 3 例 `test_fill_fetch_timeout_split` 失败，上游以暂存对照确认为**预先存在**、与本次改动无关 |

**二、本侧独立验证**（不采信声明）

| 项 | 方式 | 结果 |
|---|---|---|
| 上游修复单测 | 本侧在 `EMSXDataPipeline` 仓库**自行复跑** `pytest DataPipeline/tests/guardrail/test_compute_derived_fields.py -q` | **7 passed**（含 4 例可复现性用例） |
| 污染日期分布 | 本侧查 `fill_bdib` | **73 / 194 天**含可检出污染，与上游数字**一致** |
| 污染上界 | 本侧查 (ticker, 日期) 组合数 | **113,685** 个组合 —— 即「每个组合的首 bar 都可能受影响」的上界 |
| 修复是否已作用于存量 | 查最近 5 天（`20260914`~`20260918`） | **每天仍有**极端值（49 / 63 / 58 / 35 / 52 行）→ 存量确未改动，与上游声明一致 |

**三、本侧认识被纠正的三处（重要，如实标注）**

| # | 本侧第二十三轮的表述 | 上游纠正 / 正确认识 |
|---|---|---|
| C1 | 「数据的物理排列是**按 ticker 分组、组内按时间有序**」（隐含当作可依赖的性质） | 那是**插入顺序 + 当前优化器**的巧合产物，**不是契约**，随时可能变化。**把它当契约正是本缺陷的根源** —— 本侧不该把它描述为数据的稳定属性 |
| C2 | 「抽样 3.3% 首 bar 异常 **≈ chunk 边界率**」 | 3.3% 是**可检出**比例（两标的价格量级差异大才显著），**不是**污染率。真实污染面更大：每个 chunk 内**非首位 ticker 的当日首 bar** 均受影响，价位接近时数值不极端、事后**无法识别**。因此可检出 11,325 行只是**下界**，上界为 113,685 个组合的首 bar |
| C3 | 称 rowid 归因是「**铁证**」 | 证据强度**应下调为间接证据**。计算时的相邻关系由 `pd.concat` 拼接顺序决定、**与 rowid 无关**，故用 rowid 反推必然不吻合 —— 这**恰好解释了**本侧「`ln(fill_px 本行/前一行)` 与列值对不上」的疑点（本侧当时归因于价格列为 NULL，是**次因**；主因是 rowid 与计算顺序无关） |

C3 不推翻结论（「分母跨 ticker」仍由多条证据支持，且上游从代码侧确认了根因），
但**它说明本侧的证据链有一处推理跳跃** —— 记录下来以便今后同类归因不再犯。

**四、存量回填：三个选项与本侧倾向**

| 选项 | 内容 | 评价 |
|---|---|---|
| A | 等本侧真正启用这两列前再做 | 上游建议。成本最低（不占用上游算力），但**污染长期留在库里** |
| B | 现在全量重算 194 天（0.5~3 小时，纯本地，无需 Bloomberg，可分批中断续跑） | 一次消除污染。**本侧倾向此项**，理由见下 |
| C | 只重算 73 个可检出日期 | 上游与本侧**均不建议** —— 部分重算会让「哪些日期是可信值」**无法从数据自证**，反而制造更隐蔽的信任问题 |

**本侧倾向 B 的理由**（与「本侧是否启用」不完全重合）：

1. **「部分脏」比「全脏」更危险**：修复已上线 → 新数据正确、存量错误。这个中间状态最容易被误信 ——
   数据看起来可用，且绝大多数行确实正确，但少数行的值荒谬而不自知（不查不会发现）；
2. **风险不在本侧是否启用**，而在**任何消费者是否误用** —— `cum_interval_volatility` 就在库里，
   任何模块 / 临时查询 / 后续需求都可能读到它，而它们不会先来读 T20；
3. **成本随时间单调上升**：现在 194 天，将来只会更多；且 0.5~3 小时、纯本地、可分批、无需稀缺配额，
   属低成本高确定性；
4. **有明确的可验证验收标准**：回填后 `|log_chg_pct_10s| > 1` 的计数应为 **0**（10 秒对数收益
   达 ±1 即涨跌 ~170%，物理上不可能）；`> 0.1` 可保留少量真实市场极端事件。

**决策：选 B（现在全量重算 194 天）** —— 2026-09-22 用户确定。
护栏策略：**不**在 CostView 侧加显式拦截（本侧当前无任何代码路径读这两列），
仅以文档标注「回填完成前该列存量不可信」。

**已向上游提出回填请求（要点）**：

1. **范围**：全量 194 天（`20250926`~`20260918`），**不采用**只重算 73 个可检出日期的部分方案
   —— 部分重算会让「哪些日期可信」无法从数据自证；
2. **验收标准（可验证，须回报自检结果）**：

   | 指标 | 期望 |
   |---|---|
   | `\|log_chg_pct_10s\| > 1` 计数 | **0**（10 秒对数收益达 ±1 即涨跌 ~170%，物理上不可能） |
   | `\|log_chg_pct_10s\| > 0.1` 计数 | 由 **11,325** 大幅下降，仅保留少量真实市场极端事件 |
   | `cum_interval_volatility` 最大值 | 由 **37.7687** 降至合理区间（正常日内 < 5） |
   | 行数 | 保持 **6,680,277** 不变（只改派生列取值，不改行集） |
   | 受影响列之外 | `fill_bdib` 其余列取值**不应变化**（若因重算而变，须说明原因） |

3. **回填前后快照**：请保留可对比的前后快照（上游此前有「三层备份」做法），
   便于事后核查是否有预期外的列变更；
4. **可分批**：可中断续跑，本侧不设截止时间（这两列本侧当前未启用），按上游节奏排期；
5. **本侧将独立复验**：完成后本侧按**同一口径**复查上述指标（不采信自检结论，
   与本次「自行复跑上游单测」同一原则）。

**若上游答复回填完成**，本侧复验项：① 上述五项指标；② 抽查若干 (ticker, 日期) 序列的
首 bar 是否已为 **0**（上游修复明确首 bar 记 0，这是最直观的形态特征）。

### 2026-09-22 — 第二十五轮（T20 回填完成：本侧独立复验 + 三处测量修正）

上游已执行全量回填（82 天 / 更新 2,195,505 行，脚本 `1f9983a`）。本轮为**本侧独立复验**
（按第二十四轮承诺，不采信自检结论），并如实记录**本侧自己在复验中犯的三处测法错误**。

**一、五项验收：独立复验全部对上**

| # | 验收项 | 上游报 | 本侧实测 | 结论 |
|---|---|---|---|---|
| 1 | `\|log_chg_pct_10s\| > 1` | 690 | **690** | ✅ 一致 |
| 2 | `\|log_chg_pct_10s\| > 0.1` | 1,078 | **1,078** | ✅ 一致 |
| 3 | `cum_interval_volatility` 最大 | 0.025778 | **0.0257778** | ✅ 一致 |
| 4 | 总行数 | 6,680,277 | **6,680,277** | ✅ 一致 |
| — | `max\|log\|` | 7.3593 | **7.35930** | ✅ 一致 |
| 5 | 代表列聚合 | 前后一致 | 结构性保证：脚本仅 `UPDATE` 三列 | ✅ |

**核心结论复核通过**：**2026 年及以后 `|log_chg_pct_10s| > 0.1` 计数 = 0** ✅
（残留 690 行 100% 集中在 5 个 2025 年日期：`20251124` 557 / `20251205` 52 /
`20251212` 41 / `20251128` 25 / `20251121` 15）。

**首 bar 契约复核**：抽查 `20260904` 的 6 个 (ticker) 表内首条，均**有 `raw_bdib` 更早 bar**
（142~1,241 根），故非 0 属正确 —— **违反契约 0 条** ✅。

**二、本侧复验中犯的三处测法错误（如实记录）**

| # | 错误 | 现象 | 修正 |
|---|---|---|---|
| M1 | `MAX(ABS(?))` 把**绑定参数**当列引用 | 测出 `max\|log\| = 0.0`，与上游 7.3593 不符 | 改为 `MAX(ABS(log_chg_pct_10s))` → 7.35930 ✅ |
| M2 | 「首 bar 应为 0」判据未考虑 `fill_bdib` 是**成交采样表** | 抽到 3 个非 0 值，一度疑为契约违反 | 表内首条 ≠ `raw_bdib` 完整序列首根；须对照 `raw_bdib` 判定 → 0 违反 ✅ |
| M3 | 拿**备份 CSV 行数**当 BEFORE 非空数 | 得出「逐日普遍下降」的假象 | 备份是「三列中任一非空」的行；须逐列 `notna().sum()` 计数 |

三处都是**测量侧**问题，非上游数据问题。这与 [`attribution-pitfalls.md`](../spec/attribution-pitfalls.md)
AT-03 同源：**反常信号先假设自己的假设错了**（M1/M3 的"不符"实际是我算错）。

**三、`journal_mode` 实为 `wal`（实测：当前无影响，不断言变更时点）**

上游明确说明「脚本刻意不设 `WAL`，以免影响你们 `?mode=ro` 的只读消费」，但本侧实测
`fill_bdib.db` **当前是 `wal` 模式**。实测影响：

| 检查 | 结果 |
|---|---|
| `fill_bdib.db-wal` | **0 字节** → 已完全 checkpoint，无未落盘数据 |
| 只读查询（`mode=ro`） | ✅ 成功（count = 6,680,277） |
| 本侧只读消费路径测试（`test_env_context` + `test_monitoring`） | ✅ **79 passed** |

`-shm` 文件存在**不能**作为归因依据（本侧只读连接自身也会创建）。**本侧无 BEFORE 快照，
无法确定 WAL 是本次变更还是此前既有 —— 故不作归因、不提出改动要求**（按 AT-02：跨层/跨时点
配对须有显式传递链）。仅登记事实，并在「仍待处理」中提示复制数据库时须用 `VACUUM INTO`
或确认 `-wal` 已 checkpoint。

**四、被置 NULL 的 73,628 行：已定位，属合理行为**

用上游逐日备份 CSV 与本侧实测交叉核对：**非空数下降只发生在 8 个日期**（净 60,471 行），
且**全部可归因于 `raw_bdib` 输入不足** —— 不是无谓丢弃：

| 日期 | 备份非空 → 现有非空 | `raw_bdib` 规模 |
|---|---|---|
| `20260421` | 24,661 → 1,233 | **402,930 行 / 371 ticker**（正常日 ~3,000,000 / ~2,160） |
| `20260408` | 24,710 → 1,523 | 2,630,597 行 / 2,148 ticker（规模正常，**下降原因待上游说明**） |
| `20260420` | 13,399 → 1,529 | **510,319 行 / 431 ticker** |
| `20260422`~`20260428` | 降 301~684 | 正常（旧值本就含跨 ticker 污染，重算后消除） |

抽样证据：`NVDA US Equity` 在 `20260421` 的 `fill_bdib` 有 638 个时点，而 `raw_bdib`
**0 个** —— 该 ticker 当天无 bars，重算必为空。**按「算不出即置 NULL，不保留不可信旧值」
的规则，这是正确行为。**

**五、新发现（本侧实测，请上游核实）：`raw_bdib` 存在 ticker 级缺口**

`20260420` / `20260421` 的 `raw_bdib` 只有 **431 / 371** 个 ticker，而相邻正常日为
**2,157~2,172** 个 —— 约 1/5。这不是「整天缺失」（那样重算会全部为 NULL），
而是**部分 ticker 缺失**，因此**无法从 `fill_bdib` 侧察觉**（只能看到结果 NULL）。
本侧已登记为新待办（见 `docs/open-todos.md` **T22**）。

**六、2025 年段的精确范围（修正上游「5 天」的表述）**

| 项 | 实测 |
|---|---|
| `fill_bdib` 有、`raw_bdib` 无的日期 | **20 天，全部在 2025 年**（`20250926`~`20251231`） |
| 上游所称「5 个日期」 | 只是其中**有 `log` 值**的 5 天（`20251121/1124/1128/1205/1212`） |
| 其余 15 天 | `log_chg_pct_10s` **本就全 NULL** |
| `cum_interval_volatility` | **20 天全部为 NULL** → **无需处置** |
| `log_chg_pct_10s` 有值的行 | **388,681**（仅那 5 天） |

**故处置范围应精确为：那 5 天的 388,681 行**（而非 20 天）。本侧建议 **A（置 NULL）**：

1. 这 388,681 个值**无法验证**（无 bars 可重算）；
2. 且它们与 2026 年段**同源**（同一份计算代码）→ **同样含跨 ticker 污染**，
   只是可检出的仅 690 行（`|log|>1`），其余因价位接近**不可检出、无法区分**；
3. 「看起来正常但无法验证」正是第二十五轮开头所述「**部分脏比全脏更危险**」；
4. 处置代价小：`cum` 本就 NULL，置 NULL 仅影响该列；该 5 天其余列仍可用于其它分析。

**七、待用户决策 / 待上游说明**

1. **2025 年那 5 天的处置** —— 本侧建议 A（置 NULL，388,681 行），待用户确认后回复上游；
2. **`20260408` 下降原因** —— 该日 `raw_bdib` 规模正常（2,630,597 行 / 2,148 ticker），
   但 `log` 非空由 24,710 降至 1,523。本侧未查明，请上游说明；
3. **`raw_bdib` 的 ticker 级缺口**（`20260420` / `20260421`）—— 属上游数据完整性问题，
   本侧已登记 **T22**。

### 2026-09-22 — 第二十六轮（T20 收官：五项验收达成，本侧复验通过）

上游执行 2025 段处置（`UPDATE ... WHERE order_as_of_date IN (5 天) AND
log_chg_pct_10s IS NOT NULL` → rowcount **388,681**，提交 `b3987b7`）后，本轮为**收官复验**
与三项决策登记。

**一、收官复验：五项验收全部达成**（本侧独立实测）

| 指标 | 结果 | 验收要求 | 结论 |
|---|---|---|---|
| `\|log_chg_pct_10s\| > 1` | **0** | 0 | ✅ |
| `\|log_chg_pct_10s\| > 0.1` | **0** | 大幅下降 | ✅ |
| `cum_interval_volatility` 最大 | **0.0257779** | < 5 | ✅ |
| 总行数 | **6,680,277** | 不变 | ✅ |
| 2025 年 5 天三列 | log / cum 全 **NULL** | — | ✅ |

**一个比指标更有说服力的旁证**：回填后 `max|log_chg_pct_10s| = **0.0606**`
（回填前 9.6955）。10 秒最大对数收益 6.1%，对低流动性标的（墨西哥 / 新西兰小盘）
是**合理量级** —— 说明修复是**彻底**的（把分布还原到真实形态），而非仅把极端值压到
阈值以下。

处置备份：`backup/t20_interval_vol/fill_bdib_log_chg_pct_10s_2025_days_before_null.csv`
（24.6 MB，含 388,681 行旧值，可回滚）。

**二、上游诊断的采纳与核实**

| 上游诊断 | 本侧核实 |
|---|---|
| `20260408`：fill 行仅 **18.3%**（6,264/34,309）能在 `raw_bdib` 找到同 `(ticker, ts)` 桶，正常日（`20260904`）为 **88.1%**；双方时点均 100% 落在 10 秒网格；非 ticker 缺失、非整天缺 bars | 接受。本侧第五轮实测该日 `raw_bdib` 规模正常（2,630,597 行 / 2,148 ticker），与此诊断一致 |
| `20260408` 新线索：`:00` 秒桶异常偏多（644,629 vs 其它秒位 ~396,000，**高 63%**；正常日各秒位均匀） | 接受 —— 提示该日**部分 bar 的桶对齐基准不同**（疑似被归并到整分钟） |
| **T22**：`raw_bdib` 按**市场**分批采集/写入，`20260420` 只完成 **9 个市场**（431 ticker）、`20260421` 完成 **7 个**（371 ticker）；保留市场的 ticker 数与正常日**逐一完全相同**（HK 215、CN 97、BZ 44…）→ 非抽样、非过滤、非 A8 清理残留 | 接受。**此归因的形态论证很强**：「按市场整块保留 + ticker 数精确一致」把随机性与过滤都排除了 |
| 首 bar 契约的准确表述：判定对象是 **`raw_bdib` 的当日完整序列**，不是 `fill_bdib` 的采样行 | **采纳**，已记入本节 §4 |

**三、三项决策**

| # | 事项 | 本侧决策 | 理由 |
|---|---|---|---|
| 1 | `20260408` 的 23,187 行置 NULL | **接受现状，不深挖恢复** | ① 语义正确（fill 时点无对应 bar，无法定义该 bar 的收益率）；② **该日 `raw_bdib` 的桶对齐基准本身异常**（`:00` 偏多 63%）—— 强行重算得到的是「基于可疑基准的值」，可信度不如 NULL 明确；③ 成本收益不划算（需追溯 A8 退役前的采集/清洗路径，收益仅 1 天 23,187 行） |
| 2 | T22 后续（核对市场清单 + 增加市场级告警） | **两项都请求**：① 核对 `backfill_bdib_by_market.py` 的市场清单/顺序（把「形态吻合」做成**实锤**）；② **为 `raw_bdib` 增加市场级完整性告警**（治本） | ②是**真正的修复** —— 本次缺口的发现路径是「下游实测 → 结果 NULL」，而这类缺口的表现是**低估而非报错**，属最危险的失败模式。写入侧告警能让它在**产生时**暴露 |
| 3 | T20 状态 | **闭环** | 五项验收全达成、2025 段已处置、本侧复验通过；`20260408` 与 T22 作为**独立问题**跟踪 |

**四、首 bar 契约的最终表述**（采纳上游措辞）

> 契约的判定对象是 **`raw_bdib` 的当日完整序列**，不是 `fill_bdib` 的采样行。
> 即：同一 `(equ_ticker, order_as_of_date)` 的 `raw_bdib` 全部 bar 必须落在同一批输入内。
> 因此「`fill_bdib` 表内首条 `log` 是否为 0」**不是**有效判据。

本侧第五轮的 6 个 ticker 抽查（各有 142~1,241 根更早 bar、违反 0 条）依据的正是该表述。

**五、遗留登记**

| 项 | 说明 |
|---|---|
| `20260408` 数据质量 | 该日 `raw_bdib` 的 10 秒桶对齐基准**与其它日不同**（`:00` 秒桶高 63%）。影响**不止 `log_chg_pct_10s`** —— 任何依赖 10 秒桶对齐的分析（含本侧若将来用 `cum_interval_volatility`）在该日都需注意。已登记 **T22** |
| `raw_bdib` 市场级缺口 | `20260420` / `20260421` 分别缺至 9 / 7 个市场（正常日 23 个）。**表现是低估而非报错**，故只能从下游结果侧或专门校验发现。已登记 **T22** |

### 2026-09-22 — 第二十七轮（T22 实锤 + 告警上线 + 补拉窗口决策）

上游落实第二十六轮的两项请求（提交 `840204b`，6 files / +445 −12）。本轮为**本侧独立复验**
与**补拉窗口决策**登记。

**一、三（1）市场清单核对：实锤指向 2026-07-08 的补拉（本侧独立复验一致）**

上游用 `raw_bdib.fetched_at` 坐实写入批次。本侧独立查得**完全一致**：

| 日期 | 主要写入批次（`fetched_at`） | 总行数 |
|---|---|---|
| `20260417` | 2026-04-21 → 2,644,947（82.9%）\| 2026-07-08 → 542,770（17.0%） | 3,188,623 |
| `20260420` | **2026-07-08 → 504,542（98.9%）** \| 2026-04-22 → 5,777（1.1%） | 510,319 |
| `20260421` | **2026-07-08 → 402,385（99.9%）** \| 2026-04-24 → 545（0.1%） | 402,930 |
| `20260904` | 2026-09-07 → 2,878,584（**100%，单批**） | 2,878,584 |

**归因修正（采纳上游）**：本侧第二十五轮/二十六轮的表述「按市场分批采集、该两日只完成
前 8~9 个市场」**不准确**。准确表述是两因叠加：

1. 该两日的**日更从未把主流市场写入 `raw_bdib`**（仅留下几个 ticker 的残余）；
2. 后一次**补拉受当时临时白名单限制**，只补进了那 8~9 个市场。

保留市场的 ticker 数与正常日逐一相同（HK 215/216、CN 97、BZ 44…），正说明补拉是
**按当时白名单整块执行**的，而非随机或中断。

**二、三（2）市场级完整性告警：已上线，本侧独立复验通过**

| 项 | 内容 |
|---|---|
| 落点 | `pipeline_guards/bdib_coverage_guard.py` **同模块内扩展**（不另建文件）—— 与既有 `BDIBCoverageGuard` 的**库存级全表差集**并存 |
| 为何必须新增 | 库存级检查**发现不了**本类缺口：`20260420/0421` 缺失的 EU/JP/KS ticker 在其它日期都有数据，**不落在差集内** |
| 判据 1（市场级） | 显著市场（ticker ≥ 20）缺失占比 > **30%** |
| 判据 2（ticker 级） | ticker 覆盖率 < **50%**（兜住「市场都在但大面积无数据」） |
| 行为 | **仅告警不阻断**（已落库数据本身有效）；总开关 `GUARDRAIL_BDIB_COVERAGE_CHECK` |
| 单测 | `test_bdib_daily_coverage.py` **12 例** —— 本侧**自行复跑 12 passed** |

**本侧独立实弹复验**（用真实库数据，非构造；基线取 `20260417` 的 16 个显著市场）：

| 日期 | 显著市场缺失 | 判定 |
|---|---|---|
| `20260417` | 0/16 = **0.0%** | PASS |
| `20260420` | 11/16 = **68.8%** | **FAIL（告警）** |
| `20260421` | 12/16 = **75.0%** | **FAIL（告警）** |
| `20260422` | 0/16 = **0.0%** | PASS |
| `20260904` | 3/16 = **18.8%** | PASS |

**余量充足**：正常日最高 18.8% vs 阈值 30%；异常日 68.8% / 75%。单市场休市亦不会误报。

**一处值得记录的设计取舍（上游主动说明）**：若按「全部市场」算缺失占比，**正常日就已经
6/22 ≈ 27%** —— 因为白名单里 CH/SM/IM/GR/NA/ID 六个市场**长期无 BDIB 数据**，会把判据
推到阈值边缘、随时误报。改为只统计「显著市场（≥20 ticker）」后正常日降到 1/14 ≈ 7%。
**这说明数据质量判据的基线必须来自写入侧自身的白名单知识**，不能由消费方提供
（本侧第二十六轮曾提议"提供基线数据"，上游正确地指出无需 —— 本侧认可）。

**三、⭐ 补拉窗口：`20260420` / `20260421` 的主流市场行情将于 25 / 26 天后永久缺失**

上游附带发现（**本侧未问、上游主动提供**）：`Config.BDIB_API_RETENTION_DAYS = 180`。

| 日期 | 窗口关闭日 | 距今（2026-09-22） |
|---|---|---|
| `20260420` | **2026-10-17** | **25 天** |
| `20260421` | **2026-10-18** | **26 天** |

**若不补拉，这两日的主流市场（US / EU / JP / KS / IN / AU …）行情将永久无法获取。**
该两日的 `fill_bdib` 侧**是完整的**（fill 采集正常），因此补拉 bars 后可完整重算出
`log_chg_pct_10s` / `cum_interval_volatility`。

**本侧倾向：在窗口内补拉**（理由见下），但需消耗 Bloomberg 终端与配额，**待用户决策**。

**四、本侧独立复验的其他结果**

| 项 | 结果 |
|---|---|
| `20260921` | `raw_bdib` 与 `fill_bdib` **均 0 行**，最新为 `20260918` → 确认是**日更未运行**（非缺口） |
| 告警是否会把「整天无数据」误报 | 否 —— 守卫仅在 `date_raw_rows > 0` 时判定 |
| 上游 3 例既有测试失败 | `test_fill_fetch_timeout_split.py`（mock 缺 `on_retry`）；确认**与本次改动无关**，但位于 `guardrail/` 目录 |

**关于那 3 例失败（本侧建议）**：虽与 T22 无关，但它在 **guardrail 目录**里 —— 若该目录
长期有红灯，会削弱**新增告警的可信度**（告警的价值取决于「红灯 = 真问题」的信念）。
建议修（上游称一行 mock 签名），但不属本侧决策范围。

### 2026-09-22 — 第二十八轮（T22 闭环 + T23 补拉决策：在窗口内补）

**一、T22 闭环**

T22 的**技术部分已完整闭环**：「归因已实锤（`fetched_at`）+ 告警已上线并经本侧独立复验」。
「是否补拉存量」属**独立的数据决策**，单独立项为 **T23**，不影响 T22 关闭。

**二、T23 决策：在窗口内补拉（2026-09-22 用户确定）**

| 日期 | 窗口关闭日 | 距今 | 决策 |
|---|---|---|---|
| `20260420` | **2026-10-17** | 25 天 | **补拉** |
| `20260421` | **2026-10-18** | 26 天 | **补拉** |

**本侧的决策理由（记录要点：不是「本侧需要」，而是「不可逆」）**：

1. **不可逆性是决定性的** —— 这不是「现在做还是以后做」，而是「做还是永远不做」。
   用一次低成本操作换掉一个永久数据缺口，在信息价值上几乎总是划算的；
2. **`raw_bdib` 是公共资产**，不只服务 CostView。将来任何需求想回溯这两天都会撞上
   「永久缺失」；
3. **该两日的 `fill_bdib` 侧完整**（采集正常），缺的只是 bars —— 是「差一步可补齐」的缺口；
4. 25 天对等待终端在线是充裕的。

**已知前提（执行条件）**：

| 项 | 状态 |
|---|---|
| Bloomberg 终端 | **当前未连接** —— 需在线时执行 |
| 配额消耗 | 约 **600 万行 bars**（对照正常日约 300 万行/天） |
| 市场指定 | 需**临时指定市场**（当前 `BDIB_EXCHANGE` 已不含那 8 个市场） |
| 执行方 | 上游（写入侧）；本侧负责协调与验收 |

**已向上游提出的请求**：请在**窗口内预留排期**（不必现在执行，但要放进计划而非待定）；
若本侧最终无法执行，会在窗口前明确告知，不让上游等待。

**补拉完成后的本侧验收项**（届时执行）：

| 验收项 | 期望 |
|---|---|
| `raw_bdib` 两日的显著市场数 | 由 4 / 3 恢复至 **16**（基线为 `20260417`） |
| `raw_bdib` 两日 ticker 数 | 由 431 / 371 恢复至 **~2,160** |
| `fill_bdib` 两日 `log_chg_pct_10s` 非空数 | 由 1,523 / 1,233 恢复至接近 `20260422` 的量级（15,985） |
| `cum_interval_volatility` | 两日该列由 NULL 变为有值 |
| 告警复跑 | 两日 `evaluate_daily_coverage` 由 FAIL 转为 **PASS** |
| 其它日期 | 不受影响（补拉应只触及这两天） |

**注**：本侧当前**不启用** `log_chg_pct_10s` / `cum_interval_volatility`（后者跨批次不可比），
故补拉**不阻塞**本侧任何在途工作 —— 其价值在于**消除永久缺口**与恢复该两日的分析完备性。

### 2026-09-23 — 第二十九轮（T23 方案决策：选方案 2 全市场补拉）

上游修复 guardrail 红灯、登记 T23 排期（提交 `02b15e2`），并 dry-run 揭示两项执行前提修正。
本轮为**本侧独立复验**与**方案决策**。

**一、guardrail 红灯已清（本侧复验）**

上游说明实际是**两层**问题（不止「一行 mock 签名」）：① `fake_fetch` 缺 `on_retry`（3 处）；
② 修掉后暴露 `_make_fill_fetch` 用 `FillFetch.__new__` 手工构造、漏了 `ff._on_stage = None`，
导致 `fetch_day` 走到心跳发射器即 `AttributeError`。

**本侧复跑整个 guardrail 目录**：`159 passed`（0 失败）✅

**二、T23 方案决策：选方案 2（全市场补拉，≈600 万行）**

上游 dry-run 给出两个方案的实测成本与效果：

| | 方案 1：按 fills 缺口补 | **方案 2：全市场补（选定）** |
|---|---|---|
| 命令 | `backfill_bdib_gaps.py --dates 20260420 20260421` | `backfill_bdib_by_market.py --markets ALL --start 2026-04-20 --end 2026-04-21` |
| 规模 | 733 ticker-date | ≈ 4,320 ticker-date / ≈ **600 万行** |
| 补后 `raw_bdib` ticker | 431 → ~778；371 → ~760 | → **~2,160** |
| 补后市场数 | 9 → 21；7 → 17 | → **22~23** |

**决策理由**：

1. **不可逆的机会应用足** —— 补拉窗口只开一次（`20260420` 至 10-17、`20260421` 至 10-18）。
   若选方案 1，`raw_bdib` 这两天将**永久停留在不完整状态**（~778 / ~760 ticker），
   而事后无法再补。用一次操作把机会用足，与「不可逆性」这一原始决策理由一致；
2. **本侧原始理由即「`raw_bdib` 是公共资产」** —— 该理由对应的正是全市场完整性；
3. **600 万行是本侧自己预估并已接受的量**（第二十八轮登记的执行条件之一）；
4. 方案 1 的隐患：它只补 `processed_fills` 当日成交 ticker → `bdib_daily_summary` 在该两日
   只会覆盖这 733 个，而正常日覆盖 **1,759** —— **不完整会延续**；
5. 相对 `raw_bdib` 现有体量（**92 GB**），600 万行约 1 GB（约 1%）—— 增量很小。

**三、本侧实际影响澄清（重要，避免高估补拉对本侧的收益）**

本侧的环境变量分层来源是 `raw_bdib.db` 内的 `bdib_daily_summary` 表
（`CostView/src/monitoring/env_context.py:9`）。本侧实测：

| 日期 | `bdib_daily_summary` ticker | **fill 涉及的 ticker 中有环境值的比例** |
|---|---|---|
| `20260417`（正常） | 1,759 | **100%**（241/241） |
| `20260420` | **397** | **100%**（385/385） |
| `20260421` | **406** | **100%**（406/406） |
| `20260422` | 252 | 100%（252/252） |

**结论**：本侧的环境变量分层在该两日**已经是完整可用的** —— 补拉的收益**不在**本侧当前分析，
而在 `raw_bdib` 作为独立资产的完整性，以及该两日**全市场日汇总**（1,759 vs 397/406）的缺失。

**因此本侧纠正一处可能的误读**：补拉**不会**改善本侧任何现有分析（那些分析已可用）；
它的价值有两条，均为**资产层面**而非**本侧需求层面**：① 消除 `raw_bdib` 的永久缺口；
② 恢复该两日 `bdib_daily_summary` 的全市场覆盖，供**将来**可能出现的全市场分析使用。

**四、复验上游的两项执行前提修正（本侧接受，均为本侧理解有误）**

| # | 本侧第二十八轮的表述 | 上游修正 | 本侧复验 |
|---|---|---|---|
| P1 | 「需临时指定市场（当前 `BDIB_EXCHANGE` 已不含那 8 个市场）」 | **不需要**：缺的是**主流市场**，它们**本来就在白名单里**；而 `backfill_bdib_gaps.py` 的 ticker 来源是 `processed_fills` 的当日成交 ticker，**完全不受白名单约束** | 接受 —— 本侧把「已补进来的 8 个市场」误当成「缺失的市场」，方向理解反了 |
| P2 | 「配额约 600 万行 bars」 | 那是**方案 2** 的量；**方案 1 只要 733 ticker-date** | 接受 —— 本侧给出的是上界而非唯一成本 |

**交集复验**（本侧独立查，与上游一致）：

| 日期 | `raw_bdib` ticker | `fill_bdib` ticker | 交集 |
|---|---|---|---|
| `20260417`（正常） | 2,164 | 241 | **240**（几乎完全相交） |
| `20260420` | 431 | 385 | **38** |
| `20260421` | 371 | 406 | **17** |

正常日交集 240/241 与异常日 38/17 的强烈对比，**直接坐实**「2026-07-08 补的是另一个市场集合」
—— 这也是方案 1 必须按 fills 侧重新走一遍的原因。

**五、基线口径差异说明（不影响结论）**

上游按 `BDIB_EXCHANGE` 全量 ticker 得 1/14、12/14…；本侧按 `20260417` 当日实测有数据的市场
得 0/16、11/16…。**数字差异只源于基线集合不同，告警判定与余量结论完全一致**（异常日均
远超 30% 阈值、正常日均有充足余量）。

### 2026-09-23 — 第三十轮（T23 执行安全：`--force` 必需 + 静默失效机制）

上游在执行前发现一个**会让补拉静默失效**的坑（提交 `ed70186`）。本轮为**本侧独立读代码复验**，
并据此新增 `AT-04`（见 [`attribution-pitfalls.md`](../spec/attribution-pitfalls.md)）。

**一、`--force` 是必需项：本侧读代码后的机制比 docstring 更严**

上游指出「增量模式按日期跳过，不加 `--force` 会整日跳过（等于没跑）」。本侧读
`scripts/backfill_raw_bdib.py:560-564` 后确认，并发现**两处加重危险性的细节**：

```python
if not force and latest_existing and date_str <= latest_existing:
    logger.debug(f"  SKIP {date_display}: already in raw_bdib.db (<= {latest_existing})")
    summary["skipped_already_exists"] += 1
```

| # | 细节 | 后果 |
|---|---|---|
| 1 | `latest_existing = market_data_read.get_latest_order_as_of_date()` —— 是**全表最新日期**（实测 `20260918`），跳过判据为 `date_str <= latest_existing` | **与「该日是否已有数据」无关**：任何**早于最新日期**的补拉都会被跳过，**哪怕该日期完全为空**。这比「因为这两天已有 7-08 补的 431/371 个 ticker 才跳过」更强 |
| 2 | 跳过日志用 **`logger.debug`** | 默认 INFO 级别下**根本不打印**，只体现在 summary 的 `skipped_already_exists: 2` —— 而这个计数**看起来正像「已存在所以正常跳过」** |

**合起来的失败形态**：跑完报告「0 天成功、0 行写入」，**看起来像正常结束**；
只有最后 summary 里一个语义歧义的计数，且要等到窗口关闭后才会被察觉。

**固化后的执行命令唯一形式**（上游 `docs/open-todos.md`）：

```bash
python scripts/ops/backfill_bdib_by_market.py \
    --markets ALL --start 2026-04-20 --end 2026-04-21 --force
```

**二、本侧独立探测终端：离线（与上游结论一致）**

```
ConnectionError: Cannot connect to Bloomberg
```

本侧与上游在**同一台机器**上，故结论一致。T23 本轮**未执行**，剩余窗口：
`20260420` → **24 天**（10-17）、`20260421` → **25 天**（10-18）。

**三、其余确认（上游）**

| 项 | 内容 |
|---|---|
| `--markets ALL` | = 当前白名单 **26 个市场**；脚本按市场逐个执行、逐个临时收窄白名单，天然控制单批 API 压力；**白名单一个字都不用改** |
| 执行预期 | 26 市场 × 2 天，**小时级**；某市场失败会记录 `failed_days` 并继续下一个市场 → **可重跑且幂等**（有 `--force` 时重跑只覆盖这两天），不必要求一次跑完 |
| 上游检查点 | 已标注 **2026-10-05**（截止前 12 天），与本侧「10-10 前检查」对应 |
| 定时提醒 | **双方环境都不支持**创建定时任务（接口不存在，非配置问题）→ 均改为文档硬登记 |
| 本侧探终端 | 一行命令即可（离线会立刻报错，不会挂死）：`python -c "from xbbg import blp; print(blp.bdp(['AAPL US Equity'], ['PX_LAST']))"` |

**四、上游把本侧的「收益定位」澄清原文保留在其文档中**

上游未复述、而是**原文引用**了本侧第二十九轮的那句：

> 补拉的收益在**数据资产**层面，不在**下游应用需求**层面。下游现有分析在这两天已完整可用
> （`bdib_daily_summary` 对 fills 涉及 ticker 覆盖率 100%）。

并补记「记录此点是为避免将来有人误认为『补拉是为了修 CostView 的某个功能』」。
本侧认同这一处置：**把「为什么做」写准，比把「做了什么」写全更难，也更值得留档。**

**五、本轮新增 `AT-04`（沉淀到归因陷阱清单）**

「执行完成」必须用**产出变化**验证，不能靠退出码 / 日志 / summary —— 三者都是**过程**信号。
自检核心是**反事实检验**：**如果这次执行什么都没做，我能否从输出中看出来？**
本案例的答案是「不能」，故必须比对目标日期的产出（ticker 数 / 行数）本身。

### 2026-09-23 — 第三十一轮（`--force` 静默失效已修：本侧实证复验 + 新增 AT-05）

上游修正了 `--force` 的静默失败形态（提交 `0df3e67`）。本轮为**本侧实证复验**，并据此新增
`AT-05`（见 [`attribution-pitfalls.md`](../spec/attribution-pitfalls.md)）。

**一、上游的根因自述（重要）：误导源自文案本身，而非转述**

上游指出：他上轮写「增量模式会跳过**已有数据**的日期」，是**照抄 `--force` 的 help 文案**
（`Re-fetch even if data already exists in raw_bdib.db`）。而他是在本侧指出判据差异后才发现
**原始 help 与 docstring 本身就是错的**。

> **误导不只存在于转述，原始文案就在误导，而它是下游。**

故上游的处置不是「记住正确判据」，而是**修正文案本身**（help / docstring / 日志三处）——
这才是正确形态：**文档的下游不止一个，只让自己知道等于让下一个读者继续踩。**

**二、三处修改（本侧读代码确认）**

| 位置 | 改动 |
|---|---|
| 跳过路径（`backfill_raw_bdib.py:563-575`） | `logger.debug` → **`logger.info`**，文案含三要素：判据（不晚于最新日期）+ 澄清（与「该日是否已有数据」无关）+ 逃生开关（如需强制重拉请加 `--force`）；并补了 7 行注释说明该判据不显式化时的隐蔽失败形态 |
| 汇总输出 | `Skipped (exists)` → **`Skipped (<=latest)`** + 判据说明；`skipped_already_exists > 0` 且未加 `--force` 时**额外输出显式提示** |
| help / docstring | `run_backfill` 的 `force` 参数、`backfill_raw_bdib.py --force`、`backfill_bdib_by_market.py --force` 共三处，由「即使已有数据」改为准确判据 |

**三、本侧实证复验（实跑 dry-run，非读代码推断）**

不加 `--force`（`backfill_raw_bdib.py --start 2026-04-20 --end 2026-04-21 --dry-run`）：

```
Incremental mode: raw_bdib has data through 20260918
  SKIP 2026-04-20: 不晚于 raw_bdib 最新日期 (20260918) —— 增量判据与「该日是否已有数据」无关；如需强制重拉请加 --force
  SKIP 2026-04-21: 不晚于 raw_bdib 最新日期 (20260918) —— ...
  Skipped (<=latest): 2  # 判据：不晚于 raw_bdib 最新日期，与「该日是否已有数据」无关
  Fetched: 0 | Total rows: 0
  提示: 有 2 个日期因「不晚于 raw_bdib 最新日期 (20260918)」被跳过。该判据与「该日是否已有数据」无关
        ——整天缺失的历史日期也会被跳过；如需强制重拉请加 --force。
```

加 `--force`：`[DRY-RUN] PROCESSING 2026-04-20/21`、`Skipped (<=latest): 0`、**`Fetched: 2`** ✅

**四、`AT-04` 在该路径上现已成立（改动前是失效的）**

| 层 | 改动前 | 改动后 |
|---|---|---|
| 逐日 | 静默（`debug`） | INFO，含判据与逃生开关 |
| 汇总 | `Skipped (exists)`（语义歧义，像正常跳过） | `Skipped (<=latest)` + 判据说明 |
| 末尾 | 无 | 有 `skipped > 0` 且未加 `--force` 时的显式提示 |

即：**「如果这次执行什么都没做，能否从输出看出来」→ 现在能。**

**五、一处本侧的测量修正（再次是自己错）**

本侧首次复验时看到提示文案显示为 `\u4e0d\u665a\u4e8e...` 转义，一度疑为上游代码问题；
用 `python -X utf8` 重跑后中文完全正常 —— **是本侧终端的输出编码问题**。
（这是本侧在 T20/T22/T23 系列中的第 4 次「先怀疑上游、结果是自己测量错」，
与 AT-03 同源。记录以备后续同类误判。）

**六、上游附带产出的「同一坑入口表」（本侧登记）**

上游把相关脚本都过了一遍，避免将来从别的入口踩到同一判据：

| 入口 | 受 `latest_existing` 判据影响 | 补历史缺口的正确用法 |
|---|---|---|
| `backfill_raw_bdib.py` | ✅ **受影响**（判据在此） | 必须 `--force` |
| `backfill_bdib_by_market.py` | ✅ **受影响**（转发给 `run_backfill`） | 必须 `--force`（= T23 命令） |
| `backfill_bdib_gaps.py` | ❌ 不受影响 —— 自实现 **ticker 级**判据（`_already_has_bdib`，按 `(ticker, date)` 判 close 非空） | 默认即可 |
| `backfill_bdib_history.py` | ❌ 不受影响 —— 自算 `missing_dates` **差集** | 默认即可 |

**T23 之所以必须带 `--force`**，正是因为走的是 `backfill_bdib_by_market.py → run_backfill`
这条受影响路径。本侧已将该表记入 `open-todos.md` 的 T23，避免将来误用。

### 2026-09-23 — 第三十二轮（本侧「误报」命中上游真实缺陷；新增 AT-06）

**一、由本侧一次误报引出的真实缺陷（上游已修，提交 `8fa7433`）**

本侧第三十一轮把「中文转义」报告为**本侧终端编码问题**（误报）。上游据此去查了一个**反向问题**：
「如果真是 cp1252 控制台，我方代码会不会更糟？」结果发现**真实缺陷**：

`backfill_raw_bdib.py` 的 `_setup_logging` 中 `console = logging.StreamHandler(sys.stdout)`
**无 `encoding` 参数**；而该脚本日志**原本刻意全用英文**（避开 cp1252）。上游上一轮为修本侧
提出的问题而**新增的中文日志**，恰好放进了一个没有安全网的位置：

> cp1252 下含中文的日志行触发 `UnicodeEncodeError` → logging **内部吞掉** →
> 打印一行 `--- Logging error ---` 到 stderr → **该条日志静默丢失**。

**反讽处**：那条日志的内容是「显式化静默跳过」，而**它自己会变成静默的** ——
与 T22/T23 主题是同一种病（**失败时不报错，只是少了一条本该看到的信息**）。

**上游的总结**（原文保留）：

> 你们这次的「误报」有实际产出：它的价值不在结论，而在于你们把它说出来 ——
> 如果你们只在自己那边默默用 `-X utf8` 绕过，我就不会去查我方代码在同一情形下的行为。
> 这和 AT-05 是同一件事的两面：**错误信息也要往上走，因为下游的误报可能命中上游的真问题**。

**二、本侧复验（读代码 + 两种场景实测）**

| 项 | 结果 |
|---|---|
| 修复位置 | `backfill_raw_bdib.py:47-56`，**模块顶部、配置 handler 之前**，注释含原因说明，模式对齐 `backfill_bdib_by_market.py` / `backfill_bdib_gaps.py` |
| 修复内容 | `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` + 同 stderr，`except: pass` 兜底 |
| 实测 ①（cp1252 + 管道输出） | 中文**正常输出**，无 `Logging error` |
| 实测 ②（cp1252 + **重定向到文件**） | 文件 1,920 字节；中文完整（**4 处**「不晚于」）；`Logging error` / `UnicodeEncodeError` **0 处** |

**三、一处「更完善模式」的登记（不是缺陷，是可选加固）**

搜索时发现 `daily_update.py:34-46` 用了**更细的模式**，其注释指出：

> 当 stdout 被重定向为管道/文件时（如后端 subprocess.Popen），reconfigure 会抛出
> `OSError: [Errno 22] Invalid argument`，因此根据流类型选择安全的包装方式。

即 `daily_update.py` 按 `sys.stdout.isatty()` 分支：TTY 走 `reconfigure`，
管道/文件走 `io.TextIOWrapper(sys.stdout.buffer, ...)`。

**本侧实测结论**：`backfill_raw_bdib.py` 的简单版在**管道**与**文件**两种场景下**均有效**
（见上表实测 ①②）。故这**不是缺陷**，仅是「若将来该脚本被 `subprocess.Popen` 调用，
可考虑对齐 `daily_update.py` 的分支模式」—— 属**可选加固**，本侧**不请求**改动。
（此处的克制是有意的：按 AT-06 的平衡点，未证实的场景不应升级为结论。）

**四、上游的「待核」处置：本侧认为这是正确的工程判断**

上游由本次**已证实的触发**修了 `backfill_raw_bdib.py`，但**没有**顺手改另外几个同样
无编码保护的脚本（`daily_update.py` / `daily_observation_check.py` / `backfill_bdib_history.py` /
`fill_fetch.py` 等），而是登记入其 `docs/open-todos.md` 的「待核」段，判定标准为
「该脚本是否会输出含中文的日志/help」，并明确：

> 这次是我引入的中文日志造成的**已知**触发，而那些位置是**未验证**的假设；
> 把未验证的假设当缺陷批量改，比不改更糟。

本侧认同并已记入 AT-06 的「平衡点」：**上报线索，但不要把线索升级成结论。**
这条与本侧第五轮那次「建议上游提供基线数据」（后被上游指出属写入侧白名单知识、
消费方拿不到）是同一类判断——**克制不是不做，是不越界。**

**五、双方的自纠账（形状不同但同源）**

| 侧 | 记录 | 内容 |
|---|---|---|
| 本侧 | **4 次「先怀疑对方、结果是自己测量错」** | ① `MAX(ABS(?))` 把绑定参数当列；② 「首 bar 应为 0」忽略 `fill_bdib` 是采样表；③ 拿备份 CSV 行数当 BEFORE 非空数；④ 终端编码 |
| 上游 | **2 次「来源未核实」** | ① `--force` 照抄 help 文案；② T22 归因先说「按市场分批未完成」，后经 `fetched_at` 实锤修正 |

上游的概括准确：**两种偏差形状不同但同源 —— 都是在没回到原始事实（代码 / `fetched_at` /
实测输出）之前就给出了结论。** 本侧的纠偏动作是「回代码看判据」，上游的是「回数据看实锤」。

**六、新增 `AT-06`（见 [`attribution-pitfalls.md`](../spec/attribution-pitfalls.md)）**

> 排查过程（含误报与自纠）也要上报 —— 它可能命中对方的真实缺陷。

与 AT-05 互为两面：**AT-05 说别把文档当事实（信息自上而下时可能已失真）；
AT-06 说别把误报憋在手里（症状自下而上时也有价值）。**
合起来即：**信息在两个方向上都不能因为「看起来没价值」而被截留。**

### 2026-09-23 — 第三十三轮（更正：本侧第三十一轮的「误报」判断是错的）

**一、必须更正第三十一轮的结论**

第三十一轮本侧写道：中文转义「**是本侧终端的输出编码问题**，不是上游的代码」，并记入
「本侧第 4 次自纠」。**这个判断是错的。**

本侧事后复验（不设任何编码变量）：

```
stdout.encoding = cp1252      utf8_mode = 0
PYTHONIOENCODING = None       PYTHONUTF8 = None
print('中文')  →  UnicodeEncodeError (cp1252.py:19)
```

**本机默认就是 cp1252** —— 不是「本侧的终端特殊」，而是**真实运行条件本身**。
本侧当时用 `python -X utf8` 重跑得到「正常」，**是自己补上了可见性条件**，
然后据此把一个**真实缺陷**贴上了「误报」的标签。

**后果的严重性**：若上游接受了「是你们终端的问题」，**编码保护修复就不会发生** ——
而该缺陷的位置尤其糟糕：**它让「显式化静默跳过」的那条日志自己静默**，
正是 T22/T23 一路在消除的失败模式。**本侧差点亲手关闭了自己发现的缺陷。**

**修正后的账**：本侧「先怀疑对方、结果自己错」的自纠记录由 **4 次更正为 3 次**
（`MAX(ABS(?))` 绑定参数 / 采样表当全序列 / 备份 CSV 行数当非空数）；
编码那次**不是本侧错**，而是**本侧把一个真实缺陷归错了**。

**二、上游同轮的对应发现（本侧复验一致）**

上游由本侧「是否要对齐 `daily_update.py` 分支模式」的线索出发，实测三场景
（`subprocess.PIPE` / 重定向文件 / `python -u` + DEVNULL）：

- `reconfigure` 在管道/文件场景**本环境均可用** → `daily_update.py:36-37` 注释所述
  `OSError: [Errno 22]` **未复现**，简单版够用（与本侧结论一致）；
- **但该分支不是白写的**，只是理由不同：其 `TextIOWrapper(..., line_buffering=True)`
  提供**行缓冲** —— 管道默认全缓冲，而不设行缓冲会让 `[STAGE]` 进度**延迟到缓冲区满才出现**。
  **即：注释里的理由（OSError）与它实际承担的作用（行缓冲 + 防御）不是同一件事。**
  （这与 AT-05 同源：**文档写的理由可能与代码实际的作用不同**。）

**三、上游的核实结果（待核 → 已核，本侧登记）**

| 分类 | 内容 |
|---|---|
| **已保护** | `backfill_raw_bdib.py`（本项触发点）、`ops/backfill_bdib_by_market.py`、`ops/backfill_bdib_gaps.py`、`daily_update.py`（isatty 双分支，且在 `_setup_logging()` **之前**执行，顺序正确）、`ops/fix_daily_volatility_scale.py`、`ops/verify_volatility_against_bloomberg.py`、`ops/backfill_fill_bdib_interval_vol.py` |
| **生产主路径安全** | `runner/app.py` 用 `subprocess.Popen(..., text=True, encoding="utf-8")` 读子进程输出，而 `daily_update.py` 已重包装 stdout/stderr 为 UTF-8 → 两端匹配。**顺带暴露一处隐性契约**：被 runner 调用的任何脚本都必须输出 UTF-8，否则父进程拿到乱码 |
| **对 T23 最相关** | T23 的两条命令（`backfill_bdib_by_market.py` / `backfill_bdib_gaps.py`）**都自保护** → 执行时**不需要任何环境变量** |
| **未保护（已列明未改动）** | `scripts/ops/` 下约 20 个含中文日志的脚本、`daily_observation_check.py`、`fill_fetch.py` 的独立运行路径 |
| **从待核划掉** | `backfill_bdib_history.py` 经核实**无中文日志** |

**四、上游的处置建议（未执行，等定）**

**不逐脚本打补丁**；优先在启动层设 `PYTHONUTF8=1`（一次覆盖，但三种入口都要覆盖），
或抽一个共用 `ensure_utf8_stdio()` 供各入口调用，而非复制 `reconfigure` 代码块。
本侧认同该方向：**逐点补丁会随脚本增长而失效，启动层/共用函数才能覆盖新入口。**

**五、新增 `AT-07`（见 [`attribution-pitfalls.md`](../spec/attribution-pitfalls.md)）**

> 自纠必须基于**真实运行条件** —— 否则是另一种失实。

「是否复现」是判断责任归属的**唯一事实依据**。AT-01~06 是「过早归因于对方」，
AT-07 是「过早归因于自己」—— **方向相反，机制相同**。

**与 AT-06 合起来的规则**：**「是谁的问题」必须由「真实条件下能否复现」决定，
而不是由「谁更愿意认错」决定。**

### 2026-09-23 — 第三十四轮（AT-07 行动化与边界；AT-04 扩例「验证未触达路径」）

上游补做了本侧第三十二轮「发现漂移源却未消除它」的那一步（提交 `1c18b68`），
并就 AT-07 提出两条必要补充。本轮为**本侧复验 + 清单增补**。

**一、上游的自我指认：「登记 ≠ 消除漂移源」**

上游原话（值得原文保留）：

> 你们上轮记下「文档解释了『为什么』，而解释错了 —— 代码行为是对的，没人会去质疑」。
> 我当时**发现**了 `daily_update.py` 这个不符，写进了 `open-todos.md`……**然后就停在那里了**。
> **登记 ≠ 消除漂移源。** `open-todos.md` 是给跟踪用的；而**注释是给下一个读者用的** ——
> 下一个读那段代码的人不会先来翻待办清单，他会直接读注释、然后照抄。

**即：他上一轮批评的正是「照抄文档」，却把一个仍在生效的漂移源留在了代码里。**
已修（**代码一行未动，只改注释**）：

| 改动 | 内容 |
|---|---|
| 事实 | cp1252 默认写成**实测事实**（含 `sys.stdout.encoding == "cp1252"`、`utf8_mode == 0`、print 中文即报错） |
| 真正的理由 | 写明非 TTY 分支的**主要价值是 `line_buffering=True`** —— 管道默认全缓冲，`[STAGE]` 进度会滞留到缓冲满，前端误判 stalled |
| 历史报告 | OSError 防御明确标注为「**本机实测未复现**、保留为防御」，不再当作当前必要条件 |
| 隐性契约 | `runner/app.py` 以 `encoding="utf-8"` 读本脚本输出 → 被 runner 调用的脚本必须输出 UTF-8 |

**二、本侧复验：上游的验证「通过了」，但没有验证到目标**

上游的验证是 `python scripts/daily_update.py --help` → `rc=0`、输出正常。本侧在**真实条件**
（不设任何编码变量，实测 `enc = cp1252`、`PYTHONIOENCODING = None`）下复跑，同样通过。

**但那不是有效验证**：`--help` 的输出**全是英文**（`usage:` / `CostView Daily Update Scheduler`），
**它根本不会走到那条中文日志路径** —— 即使编码保护完全失效，这个验证也会通过。

本侧改用能真正触发的**对照验证**：

| 组 | 方式 | 结果 |
|---|---|---|
| 对照 | 真实条件（无环境变量）直接 `print` 中文 | `UnicodeEncodeError: 'charmap' codec can't encode characters in position 8-15` ✅ **复现** |
| 实验 | 应用 `daily_update.py:52-63` 的同一保护模式后再输出中文 | `encoding = utf-8`、`isatty = False`（走非 TTY 分支）、`line_buffering = True`、**中文输出成功** ✅ |

**结论：保护模式确实生效、注释修改正确** —— 但上游的验证方式未触达被测路径。
已作为 **AT-04 的误用形态**记入清单：

> **自检**：验证前先问 —— **如果被测的机制完全失效，我这次的输入还能通过吗？**
> 若能通过，说明这个输入**没有触达被测路径**，验证无效。

**三、AT-07 的两条补充（本侧采纳并写入清单）**

**补充 1 —— AT-07 是例行动作，不是「警惕心态」**：

上游在验证时**顺手写了句中文 `print`**，在真实条件下**直接抛错**。他对此的自述：

> 我刚碰到的这一次 —— 写测试代码时顺手写句中文 —— **没有任何动机**。
> 我没有想证明什么，也没觉得自己在辅助位置，纯粹是「写句人话方便看」。
> 这说明：**根因不在动机，而在「默认不检查条件」本身**。动机只是让它更容易发生。

本侧认同并已写入：**把 AT-07 降成一句每次都要问的话** ——
「给出任何结论前：我刚才有没有改过运行条件？把条件改回去还能复现吗？」
心态无法实时自省，动作可以。**把规则写成修养，它就无法执行。**

**补充 2 —— AT-07 的边界（防反向滥用）**：

> 「真实条件」不是一个点，而是一个集合（手动 TTY / 调度器 / runner / CI / 管道 / 重定向）。
> 若要求「所有入口都复现」才算真缺陷，那几乎不可能有人能认错。
> **可操作判据：只要在至少一个主要入口下可复现，即判定为真实缺陷。**

本侧采纳。AT-07 的目的是**防止真缺陷被误关**，不是**要求举证到不可能** ——
判据过严会让规则失去可执行性，与 AT-04 的「反事实检验」同理，都要求判据**当场可判**。

**四、待决定项（本侧表态）**

上游指出：`scripts/ops/` 下约 20 个含中文日志的脚本仍停在「已核实、未处置」，
需在**启动层设 `PYTHONUTF8=1`** 与**抽 `ensure_utf8_stdio()` 逐入口调用**之间选一个，
并表示「不自行替你们做，因为它会改变运维方式，而不只是改代码」。

**本侧意见**（供上游决定，不代做）：

1. **两者不替代**：`PYTHONUTF8=1` 由调用方设置 → **无法覆盖"有人直接 `python script.py`"**；
   而脚本内 `reconfigure` 是**自主保证**，不依赖外部环境。故**不是二选一**；
2. **推荐组合**：启动层/调度器/runner 三处设 `PYTHONUTF8=1` 作为**兜底**
   （覆盖所有入口与未来新增脚本）；同时抽 `ensure_utf8_stdio()` 作为**新脚本的模板**，
   在**确实要输出中文**的入口显式调用；
3. **不建议**对现有 20 个脚本逐个打补丁（与上游判断一致）——
   **逐点补丁会随脚本增长而失效**；
4. **本侧不催办**：这是上游仓库的运维决策，且当前无已知触发（T23 两条命令均自保护）。
   本侧只需要知道结论，以便将来引用其脚本时心里有数。

### 2026-09-23 — 第三十五轮（T23 终端诊断：界面在线但 API 网关未就绪）

**一、⭐ 用户报告「终端在线」，本侧实测仍离线 —— 已定位原因**

| 进程 | 启动时间 | 状态 |
|---|---|---|
| `bbcomm`（Bloomberg **API 网关**，PID 32840） | **2026-09-21 08:18:33** | 已运行 ~2 天、CPU 8910 秒、内存 62.2 MB，**但无任何监听端口** ❌ |
| `wintrv`（终端**主界面**进程） | **2026-09-23 07:16:12** | 正常 |
| `blpwtk2_subprocess` / `blpsmarthost` / `blptcserver` 等 | 今日 07:16 / 08:58 | 正常（GUI 侧） |

**根因**：**`bbcomm` 比终端主进程早启动一天** —— 终端今天 07:16 重启过，而 `bbcomm`
**未跟随重启**，因此 API 网关未重新监听（实测 `Get-NetTCPConnection` 中该 PID 无任何
监听端口，默认 8194 亦无）。

**这解释了「界面在线但 API 离线」**：用户看到的是 `wintrv` 的终端界面正常，而本侧脚本走的是
`bbcomm` 的 API 通道 —— 两者是**独立的进程与生命周期**。

**修复方式**（待用户确认后执行，因涉及终止进程）：
① 结束 `bbcomm`（PID 32840）→ 终端会自动拉起新的；或
② 重启 Bloomberg 终端。

**顺带记录一个排查要点**：`xbbg` 的 `Cannot connect to Bloomberg` **不区分**
「终端未安装」「终端未登录」「`bbcomm` 未就绪」三种情形 —— 报错文本相同。
网上的排查建议多指向「终端没开」，而本例是**终端开着、网关僵死**。
故今后遇此错误应直接查 `bbcomm` **进程与监听端口**，而不是只看终端界面。

**二、T18 的一处追溯**：上游第二十四轮提到「旧进程 PID 16968/36116 于 9/21 08:18 启动、
加载修复前代码」—— 本侧本轮观察到的 `bbcomm` **同为 9/21 08:18:33 启动**（PID 不同）。
两者时间戳一致，提示 **9/21 08:18 是本机的一次整体启动/重启时点**，
该时点启动的进程群都需要警惕「加载的是修复前代码」。

**三、上游 `ensure_utf8_stdio` 复验（提交 `3ed2a60`）**

本侧独立复跑其对照式测试：`6 passed` ✅。实现质量评估：

| 设计点 | 评价 |
|---|---|
| 抽为共用函数 `DataPipeline/common/encoding.py` | 原理单点维护（原两处内联各写一遍） |
| **返回 `mode` 字段**（`reconfigure` / `textiowrapper` / `already_ok` / `noop`） | **⭐ 这是对本侧第三十四轮「验证未触达路径」批评的结构性解决** —— 调用方**可以断言实际走了哪条分支**，而不必靠「跑一遍没报错」推断 |
| `_REPLACED_STREAMS` 保活被替换的流 | 修复了**因抽函数才暴露**的真实缺陷（见下） |
| `already_ok` 短路 | 区分「已保护」与「刚保护」 |
| 不抛异常 + `errors` 列表 + WARNING | 编码保护失败不应让调用方崩溃 |
| docstring | 含「为什么需要」「两条路径各自的理由」「OSError 历史说明」「隐性契约」「用法」 |

**四、抽共用函数时暴露的真实缺陷（上游自我指认，值得原文保留）**

上游的幂等性测试第一次跑就失败：`ValueError: I/O operation on closed file` / `lost sys.stderr`。
原因：`io.TextIOWrapper` 析构时会 `close()` 底层 buffer，而**重复包装共享同一个 buffer**
—— 旧对象被 GC 后新包装立即失效，连 stderr 都丢。

上游的因果说明很关键：

> **这个缺陷是我「抽共用函数」这个动作本身引入的。** 原内联版本在 `daily_update.py`
> 顶层只可能执行一次，所以不会暴露；抽成函数之后，「脚本调用 + 被 import 的模块也调用」
> 就有了二次调用的可能。

**即：重构（而非新功能）会引入新缺陷，因为重构改变了「同一段代码被执行的次数」这一隐含前提。**
本侧将其补入 AT-04 的案例集（它同时也说明：**只有能触达二次调用路径的测试才会发现它** ——
`--help` 那种验证连一次包装都没触及）。

**五、上游承认其验证「不可证伪」——本侧认为这是本轮最有价值的一段自述**

上游原话：

> 我的逻辑实际是：观察到 `rc=0` → 推断「保护生效」。而真相是 `rc=0` **也可能**因为
> 「根本没输出中文」。**两种原因产生同一观测，我的验证无法区分它们** —— 更糟的是，
> 我当时还把同一次运行里「我的测试代码因中文 print 而炸」当成了旁证。那件事本身是真的
> （证实了 cp1252），但它同时正好说明：**同一环境下，输出中文的地方确实会炸** ——
> 所以被测脚本没炸，只能说明它**没输出中文**，而我把这读成了「保护生效」。

**这段自述精确命名了一种失败**：不是「验证没触达路径」（本侧的批评），
而是**「验证无法区分假设与替代解释」** —— 本侧的批评只说了症状，他补上了判据（**可证伪性**）。
本侧采纳并补充进 AT-04：**验证必须能区分「机制有效」与「路径未触发」两种解释。**

**六、上游本轮的分层验证表（本侧认为这是正确形态，值得照做）**

| 验证手段 | 覆盖了什么 | **未**覆盖什么 |
|---|---|---|
| 单元测试（6 例，子进程 + 强制 cp1252；**断言对照组必须失败**） | 保护**机制本身**（含机制失效时对照组失败） | `daily_update.py` 的实际接入 |
| 管道调用 `daily_update.py --help` | **接入正确 + 无回归** | 该脚本的**中文日志输出路径**（`--help` 全英文） |
| 模块探测（同条件） | 分支实测：`mode=textiowrapper enc=utf-8 lb=True errs=0` | — |

其自述：「**「`daily_update.py` 的中文日志实际输出路径」本轮仍未直接验证** ——
它由上面第一行的单元测试按机制覆盖，两者互补。我不打算用一个间接观测再冒充直接证据。」

**对照组必须失败这一设计尤其重要**：若宿主环境变成 UTF-8，对照组会「意外成功」，
测试将**显式失败**并报出「实验组的通过不能证明保护有效」，而非静默降级为
「什么都没验证」。**这使测试本身具备了自我保护。**

### 2026-09-23 — 第三十六轮（更正：bbcomm 未僵死；根因是 xbbg/blpapi 版本不兼容）

**一、⚠️ 更正第三十五轮的诊断结论 —— 本侧错了，上游是对的**

第三十五轮本侧判定「`bbcomm` 无任何监听端口 → API 网关僵死」，并据此建议终止该进程。
**该结论错误。** 上游用 `netstat` 复核后指出：`bbcomm`（PID 32840）**正在监听 `127.0.0.1:8194`**，
有 **8 个 ESTABLISHED** 本地连接，另有到 Bloomberg 服务器的外网连接（`192.168.17.109:8201 → 69.184.76.114:8194`）。

**本侧用 `netstat -ano` 复核，完全确认上游的观察**：

```
TCP  127.0.0.1:8194   0.0.0.0:0        LISTENING    32840
TCP  127.0.0.1:8194   127.0.0.1:57031  ESTABLISHED  32840
...（8 个 ESTABLISHED）
TCP  192.168.17.109:8201 → 69.184.76.114:8194 ESTABLISHED 32840
```

**连接 8194 的进程**：`bbcomm` + `wintrv` + `bplus64` + **2 个 python**（PID 46484 / 68580，均 9/22 启动）。

**二、本侧诊断错在哪里 —— 又是 AT-04，而且是自己刚立下的判据**

第三十五轮本侧用的探测是：

```powershell
Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.OwningProcess -eq 32840 }
```

**返回 0 条** → 本侧据此下结论「无任何监听端口」。但当去掉 `-ErrorAction SilentlyContinue`
后，被吞掉的错误是：

```
No MSFT_NetTCPConnection objects found with property 'State' equal to 'Listen'.
Verify the value of the property and retry.
```

即：**该 cmdlet 在本环境返回 0 条（不管筛选条件），而 `-ErrorAction SilentlyContinue`
把「工具没工作」这个事实静默掉了** —— 本侧把「我没看到」读成了「不存在」。

**这是 AT-04 的教科书案例，而且是最难堪的一种**：本侧在第三十四轮**刚刚**用同一判据
（「如果被测机制完全失效，我这次的输入还能通过吗？」）批评上游的 `--help` 验证，
随后**自己立刻犯了同构错误**（探测工具恒返回空 → 我用它的空结果断言存在性）。
已作为 AT-04 的核心案例记入清单，并补一条更硬的判据：
**「零结果」必须通过第二种独立手段确认，才能当作「不存在」。**

**三、⭐ 根因：`xbbg 0.10.3` 与 `blpapi 3.26.7.1` 版本不兼容（用户方向正确）**

按用户要求调查 xbbg / blpapi 版本冲突，本侧做了**同进程对照**（这是决定性的一步）：

| 路径 | 结果 |
|---|---|
| 裸 `blpapi.Session`（`localhost` 或 `127.0.0.1`） | **`start() = True`** ✅ |
| `xbbg.blp.bdp(...)`（紧接其后，同进程） | **失败**：`ConnectionError: Cannot connect to Bloomberg` ❌ |

底层错误（本侧捕获，与上游报的一致）：

```
ERROR btemt_tcptimereventmanager.cpp:2038 BTE event manager control channel open failed: rc = -5, errno = 10048
WARN  blpapi_apicmadapter.cpp:172  Failed to start TcpTimerEventManager, error = -1
ERROR blpapi_sessionimpl.cpp:2857  Failed to start session: PlatformController failed to start
```

**版本证据**：

| 包 | 本机版本 | 安装时间 | PyPI 最新 |
|---|---|---|---|
| `xbbg` | **0.10.3** | **2026-04-09** | **1.4.12** |
| `blpapi` | **3.26.7.1** | **2026-09-08** | — |

**`xbbg` 从 0.10.3 到 1.4.12 是主版本跨越（0 → 1）**，而 `blpapi` 在 9/8 被单独升级过
（xbbg 是 4 月的版本，未跟随）。**API 变更的直接证据**：本侧尝试注册 blpapi 日志回调时
`blpapi.Logger.LEVEL_WARNING` **不存在**（blpapi 3.26 已移除该常量）。

**隔离验证（`pip install --target` 到临时目录，不动现有环境）**：

```
xbbg 1.4.12 → blp.bdp(['AAPL US Equity','MSFT US Equity'], ['PX_LAST'])
            → 成功，返回 AAPL=339.75 / MSFT=498
```

**结论：升级 `xbbg` 至 1.4.x 后连接恢复。** 根因确认为**版本不兼容**，与 `bbcomm`、
终端、blpapi 本身、端口占用**均无关** —— 这些在对照实验中都被排除。

**四、附带发现：新版 xbbg 是破坏性升级**

`xbbg 1.4.12` 返回的是 **Narwhals DataFrame**（非 pandas）—— 故 `.iloc` 等 pandas 接口
不可用，`AttributeError: 'DataFrame' object has no attribute 'iloc'`。

**这意味着**：上游的 `bdib_fetcher.py` 等依赖 xbbg 的代码**需要适配新版 API**，
不是「升级即可用」。**从 0.10.3 到 1.4.12 属破坏性升级，须由写入侧评估与改造。**

**五、对用户指令的处理说明（重要）**

用户基于本侧**错误**的第三十五轮诊断，指示「结束 `bbcomm`（PID 32840）让它重拉」。
本侧在收到上游复核证据后**未执行该操作**，理由：

1. `bbcomm` **健康**（LISTENING + 8 ESTABLISHED + 外网活动连接）；
2. 其上挂着 **5 个进程**的活动连接（含 2 个 9/22 启动的 python，可能是上游在跑的任务），
   终止会**中断**它们；
3. **即使终止也不解决问题** —— 根因在 xbbg 客户端层，与网关无关。

**本侧的处理**：先纠正自己的错误信息（而非执行基于错误信息的指令），再重新给出结论。
（这是 AT-07 的一次正向应用：**纠正结论的依据是证据，不是「谁先说的」。**）

**六、T23 现状与下一步**

| 项 | 状态 |
|---|---|
| `bbcomm` / 终端 | **健康，无需处理** |
| 根因 | `xbbg 0.10.3` × `blpapi 3.26.7.1` 不兼容 |
| 修复方向 | ① 升级 `xbbg` 至 1.4.x（**破坏性**，须适配 `bdib_fetcher` 等）；② 或将 `blpapi` 回退至与 0.10.3 兼容的版本 |
| T23 能否执行 | **暂不能** —— 上游的取数路径依赖 xbbg |
| 剩余窗口 | `20260420` → **24 天**、`20260421` → **25 天** |

**决策归属**：升级 xbbg 会改变上游的依赖版本并需要改造其代码 → 属**写入侧决策**；
本侧可提供验证支持（如隔离环境验证、回归对照），但不代做。

**七、本侧记录一处方法论自省**

本轮的排查过程是：**本侧错误诊断（AT-04 复犯）→ 上游用第二种手段复核并推翻 → 本侧复核确认
→ 重新定位真因**。其中值得记录的是：**若没有上游的复核，本侧会基于错误诊断执行一个
有破坏性的操作（终止健康进程），且该操作不会解决问题** —— 错误的诊断会导向**错误的动作**，
而不只是错误的结论。这是 AT-04 在本项目里代价最高的一次。

### 2026-09-23 — 第三十七轮（根因二次更正：不是版本不兼容，是探测没走仓库自己的补丁）

**一、⚠️ 更正第三十六轮：本侧「版本不兼容」的根因判断也是错的**

上游进一步排查后发现：**仓库里早已存在补丁** `DataPipeline/common/bloomberg_compat.py`
（提交 `8d3ad6b`，**2026-09-22 11:58:39**），且**所有生产调用点均已接入**
（`bdib_fetcher.py:175` 正是 T23 的路径）。该模块的根因描述**远比本侧精确**：

> blpapi 3.26 重构了 `Session` 的 Python 实现，内部 handle 属性由 `_Session__handle`
> 改名为 `_Session__abstractSessionHandle` / `_handle`。xbbg 0.10.3 的 `SessionManager`
> 仍以 `getattr(session, "_Session__handle", None) is None` 判断会话是否有效 →
> 在新版 blpapi 下该判断**恒为 True** → **缓存永不命中** → 单次 `blp.bdh` 期间
> 反复新建 blpapi 会话（实测一次引用新建 **20+ 个**）→ 未释放的会话持续占用 BTE
> control channel 端口 → 最终 `errno 10048` 令 `PlatformController` 启动失败。

**处置**：在 `import xbbg` **之前**调用 `import_blp()`。

**所以：`xbbg 0.10.3` + 补丁完全可行，既不需要升级到 1.4.x，也不需要回退 blpapi。**
本侧第三十六轮把它归因于「版本不兼容」并列出「升级 / 回退」两条路，**两条都是不必要的**。

**二、⚠️ 更正第三十五轮之后的整条链条：起点是一次没走既定用法的探测**

| 轮次 | 本侧结论 | 实际 |
|---|---|---|
| 第三十五 | 「`bbcomm` 僵死」（据 `Get-NetTCPConnection` 返回 0 条） | `bbcomm` 健康 —— **上游用 netstat 复核拦下**（见第三十六轮更正） |
| 第三十六 | 「`xbbg` × `blpapi` 版本不兼容」 | 真因是**探测未走 `import_blp()` 补丁** —— 上游进一步排查拦下（本轮更正） |

**值得记录的是**：这两次错误都源于**本侧和上游同时用了裸 `from xbbg import blp` 探测**
（上游 9/22 那句 `RESULT: OFFLINE` 即由此而来）。**整条「终端离线 → 网关僵死 → 版本不兼容」
的链条，起点是一次没走既定用法的探测。** 上游已明确认账这一点。

**三、本侧复验（本轮实测）**

| 复验项 | 结果 |
|---|---|
| 补丁模块存在与内容 | ✅ `bloomberg_compat.py` 精确描述 `_Session__handle` 改名 → 缓存永不命中 → 20+ 会话 → `errno 10048`；`import_blp()` = `ensure_xbbg_blpapi_compat()` + `from xbbg import blp` |
| 裸 `from xbbg import blp` | ❌ `ConnectionError: Cannot connect to Bloomberg`（本侧复现，与上游一致） |
| **今日日更日志**（`logs/pipeline/fillfetch.log`） | ✅ `run_timestamp 2026-09-23T10:00:54`；`fetch.days_fetched=2 / days_error=0`；**`bdib.raw_bdib_rows=5,350,653` / `failed_dates=[]` / `failed_chunks=0`**；`_guardrail.status=success` |

**即：补丁在生产上早已生效** —— 若未生效，BDIB 阶段会整体失败，不可能有 535 万行 / 0 失败。

**四、本侧当前临时会话仍失败 —— 原因与补丁无关（如实记录）**

本侧试图用 `import_blp()` 复验时**仍失败**（同一 `errno 10048`）。排查发现：

| 检查 | 结果 |
|---|---|
| 8194 连接数 | **21 个 ESTABLISHED**（此前 8 个） |
| TIME_WAIT | 0 |
| 连接方 PID | `bbcomm` + **2 个长期 python（46484 / 68580，9/22 启动）** + `wintrv` + `bplus64` |

**即：已有生产会话占着控制通道**，本侧的**临时新会话**建不起来 ——
这与补丁无关（补丁防的是「反复新建」，而这里是「已有会话占用」）。
**生产路径不受影响**（上游实测 `fetch_bdib_for_fills` 成功拉到 2340 根 10s bar）。
本侧登记此现象，以免将来有人据此再次误判「补丁失效」。

**五、T23：可执行**（本侧确认）

- 终端 / 网关 / API / xbbg + 补丁 **全链路正常**（日更 535 万行为铁证）；
- 命令不变（含 `--force`）：`backfill_bdib_by_market.py --markets ALL --start 2026-04-20 --end 2026-04-21 --force`；
- 剩余窗口：`20260420` → **24 天**（10-17）、`20260421` → **25 天**（10-18）；
- **本侧已答复上游：执行**（用户先前已授权补拉）。

**六、T18 有答案：日期级守卫未触发**

今日日更 `_guardrail.status = success`、`bdib.raw_bdib_rows = 5,350,653`、`failed_dates = []`
→ 说明上游新增的**日期级市场完整性守卫在 `20260921` / `20260922` 两次写入中未触发**，
即这两天市场覆盖完整。**T18 可闭环。**

**七、新增 `AT-08`（见 [`attribution-pitfalls.md`](../spec/attribution-pitfalls.md)）**

> **修复有效 ≠ 根因正确 —— 别让 workaround 终止追问。**

本侧的 `xbbg 1.4.12` 隔离验证**确实成功**，但它的正确含义是「**若**需要升级，那条路是通的」，
**不是**「根因是版本不兼容」。据此得出的「升级 xbbg」方案会引入 **Narwhals 适配面**（破坏性）——
**本侧的 workaround 差点导向一个不必要的改造。**

**八、附带发现（上游提供，本侧登记）：`conservation.gaps` 约 18 个日期**

形态为 **`raw_bdib` 有数据而 `fill_bdib` 为空**（与 T23 的缺口方向相反），例如
`20260101/0102`、`20260414/0415`、`20260511/0512`、`20260527`、`20260602~0604`、`20260706~0708`。
本侧在日更日志中**独立确认**该清单存在（`checked_dates: 386`、`ok: false`）。
上游未查原因、仅登记；本侧亦未查。**登记为新待办 T24。**

**九、上游提出的结构性建议（本侧表态）**

上游建议评估「**把 blpapi 降到 `3.25.11.1`**」（`xbbg/_sdk.py` 记载的配对版本）——
降级后**裸 import 也能工作**，补丁从「必需」变成「保险」，未来任何新脚本、任何人的临时探测
都不会再踩。上游明确表示不自行动手（属环境变更）。

**本侧意见**：
1. **认同问题本质** —— 「只有按正确方式调用才不出错」的契约，**迟早会被踩第二次**；
    本次双方同时踩中就是证据；
2. **但优先级不高** —— 现有补丁 + 全部生产调用点已接入，生产路径无风险；
    而环境降级需评估与当前终端/其它依赖的兼容性，**成本与风险不对称**；
3. **建议**：列入评估但不急于执行；若要降低复发概率，**更轻的办法**是在
    `DataPipeline/common/` 提供**唯一入口**（`import_blp`）并在 `AGENTS.md` / `CODEBUDDY.md`
    写明「禁止裸 `from xbbg import blp`」—— **成本近零，且与 AT-05 同源（把契约写在读者会看的地方）**；
4. **本侧不催办**（属上游环境决策）。

### 2026-09-23 — 第三十八轮（T23 部分执行：实际窗口 ≈154 天，非配置的 180 天）

**一、T23 执行结果：部分恢复（未达验收口径）**

上游执行 T23（36 天次成功 / 894,849 行写入 / 0 天失败）。**本侧独立复验**：

| 日期 | ticker（前后） | 市场（前后） | 正常日对照 |
|---|---|---|---|
| `20260420` | 431 → **599** | 9 → **21** | 2,164 / 23 |
| `20260421` | 371 → **538** | 7 → **19** | 2,157 / 22 |

**未达本侧登记的口径**（ticker → ~2,160、市场 → 22~23）。**原因不是执行问题。**

**二、⭐ 真因：实际保留窗口 ≈154 天，配置写成 180 天**

上游单 ticker（AAPL）多日期探测 + **本侧独立复核（库内证据）**：

| 日期 | 距今天数 | US ticker | **AAPL bar** |
|---|---|---|---|
| `20260420` | 156 | 58 | **0** ❌ |
| `20260421` | 155 | 53 | **0** ❌ |
| `20260422` | 154 | 673 | **2340** ✅ |
| `20260520` | 126 | 679 | 2340 ✅ |
| `20260904` | 22 | 723 | 2340 ✅ |

**本侧的独立贡献**：AAPL 在 `20260421` 为 0、`20260422` 完整 → **边界精确落在 155 / 154 天之间**，
即**实际窗口 ≈154 天**，比 `BDIB_API_RETENTION_DAYS = 180` **短 26 天**。

**后果**：窗口在 **8 月底前后就已关闭**，比双方推算的截止日（10-17 / 10-18）**早约 7 周**。
T23 只能在残存范围内捞回部分。

**三、本侧必须认领的判断错误**

本侧第二十七~三十七轮**反复核对「还剩 24 / 25 天」**，并据此推动「在窗口内补拉」。
**但从头到尾没有实测「4/20 到底还能不能拉到」。**

**而本侧手里早就有探测能力** —— 第三十轮就用 `blp.bdp(['AAPL US Equity'], ['PX_LAST'])`
探过**终端状态**，只是**用它探终端，没用它探目标数据**。
**「我有能力验证」与「我实际验证了」是两件事。**

**四、上游同轮修正的两处真实缺陷**

| 缺陷 | 内容 |
|---|---|
| `sys.path` 缺口（**已修** `5fe6be3`） | `backfill_bdib_by_market.py` 只把**仓库根**加入 `sys.path`，而 `_run_market_backfill` 里 `from backfill_raw_bdib import run_backfill` 需要 **`scripts/`** 目录 → 首次启动时 **26 个市场全部立即失败**（`No module named 'backfill_raw_bdib'`）。**即：该命令的执行路径此前从未真正跑通。** |
| 一处错误注释（**已修**） | 同文件注释称「其下模块从未被本脚本 import」——**与实际不符**，而这正是导致 `sys.path` 缺 `scripts/` 的**判断依据**。**又一处「注释写错了理由，代码照着它走」**（与 AT-05 同源）。 |

**上游的验证盲区与本侧同构**（其自述）：先用 `--help` 试（不触达）→ 再用 `--dry-run` 试
（在拉取前就 `return`，**同样不触达**那个延迟导入）→ **两次都是 AT-04 的「输入没触达路径」**，
真正触达的只有**真实执行**。

**五、新增 `AT-09`（见 [`attribution-pitfalls.md`](../spec/attribution-pitfalls.md)）**

> **不可逆约束的边界必须实测，不能只取配置值 —— 且假设要系统性偏保守。**

上游的判据（原文保留）：

> 窗口这类**不可逆**的约束，假设必须取得**比配置值更保守**。我们都用了配置里的 180 天去算
> 倒计时，于是谁都没有紧迫感；而乐观假设的代价是永久失去数据，保守假设的代价只是多花一点
> API 配额 —— **两者不对等**。

**六、本侧的三项处置决定**

| # | 事项 | 本侧决定 | 理由 |
|---|---|---|---|
| 1 | `BDIB_API_RETENTION_DAYS` 配置值 | **建议改为 120**（并在注释标注「实测边界 ≈154，取 120 留安全余量；180 是名义上限而非实测」） | 该值影响 `backfill_bdib_by_market.py` 的默认起点与 `backfill_bdib_gaps.py` 的「是否在窗口内」判定 → 会把 127~180 天前的日期**误判为可补**。属上游仓库配置，本侧给意见不代改 |
| 2 | 为重跑 `fill_bdib` 集成（恢复 log/cum） | **不做** | 当前每 ticker 仅 **~75% 时点覆盖**（与正常日不同）→ 基于不完整 bars 算出的 log/cum **与正常日不可比**，属「看起来正常但实际不可比」，**正是本项目一路在消除的问题**。保持 NULL 语义明确（「该两日 bars 覆盖不全，故不予派生」）。**若将来确有需求再评估，成本不高** |
| 3 | 复跑日期级守卫（验收第 5 项） | **可做**（低成本） | 用于确认 T23 补入后这两日的市场缺失占比是否已降到阈值以下 —— 但**预期仍是 FAIL**（21/19 个市场 vs 基线 16 个显著市场的缺失比例，需实测） |

**七、验收口径的诚实对照（上游提供，本侧确认）**

| 验收项 | 状态 |
|---|---|
| `raw_bdib` ticker 431/371 → ~2,160 | ✗ **599 / 538**（窗口限制，物理不可达） |
| 市场 9/7 → 22~23 | △ **21 / 19** |
| `fill_bdib` log 非空 → 接近 15,985 | ⏳ **不计划做**（见上 §6-2） |
| `cum_interval_volatility` NULL → 有值 | ⏳ 同上 |
| 守卫 FAIL → PASS | ⏳ 可做（预期仍 FAIL） |
| 其它日期不受影响 | ✓ |

**八、T23 最终定性**

**部分完成，且其价值不在数据本身，而在暴露了两个假定错误**（窗口值、脚本执行路径）。
按 AT-09 的判据，**本次的「永久损失」已发生**（4/20、4/21 的主流市场 bar 无法再获取）——
这是一次**不可逆**的代价。

### 2026-09-23 — 第三十九轮（T23 收尾：配置已修；本侧两处结论被更正）

上游执行了本侧的三项决定（① 配置值、③ 守卫复跑；② 尊重本侧判断不做），并回传两个观测 ——
**其中第一个直接反驳了本侧第三十八轮的一处推理前提。**

**一、① 配置收敛：已修（提交 `89482e6`）**

| 项 | 内容 |
|---|---|
| 值 | `BDIB_API_RETENTION_DAYS` **180 → 120**，注释写入完整实测依据（156/155 天 0 行、154 天完整、126 天完整、77 天及以后完整） |
| **漂移源收敛** | **另三处写死天数的引用**（`backfill_bdib_by_market.py` docstring、`backfill_raw_bdib.py` usage、`backfill_bdib_gaps.py` 默认窗口注释）改为指向 `Config`（**全仓唯一来源**） |
| 删除未验证断言 | 删掉了那句「**US/LN/JP/KS 约 9 个月、HK 约 6 个月**」—— **实测约 5 个月**，该句本身是一处未经验证的断言 |
| 验证 | `BDIB_API_RETENTION_DAYS = 120`，默认 `--start` 实测算成 `2026-05-26` |

**本侧注**：把三处写死的天数改为引用 `Config`，与 026 时本侧「口径单点」的做法同源 ——
**数字只在唯一来源维护，才不会各自漂移**。

**二、③ 守卫复跑：仍 FAIL，但给出了 T23 的可量化价值**

```
[FAIL] 20260420: ticker 覆盖 599/2174 = 27.6% | 显著市场缺失  5/14
[FAIL] 20260421: ticker 覆盖 538/2174 = 24.7% | 显著市场缺失  5/14
[PASS] 20260422: ticker 覆盖 2157/2174 = 99.2% | 显著市场缺失 1/14
[PASS] 20260904: ticker 覆盖 2129/2174 = 97.9% | 显著市场缺失 0/14
```

**关键数字：缺失的显著市场从 T23 前的 12/14 降到 5/14** —— 补入后
`EU/JP/IN/KS/LN/SS/SP/NO` 已覆盖，仍缺 `AU/SW/SJ/MK/IJ`。

**所以本侧第三十八轮的定性需要修正**：T23 **不只是**「暴露了两个假定错误」，
它还有**可量化的部分成果 —— 缺口中的显著市场有 58% 被补上**。本侧此前把它写得过于消极。

**三、⚠️ 更正：本侧「AAPL 为 0 ⇒ 整个美国市场不可得」是错的**

本侧第三十八轮写：

> （AAPL 是最活跃标的，若它在某日 0 行，说明该日对整个市场都不可得）

**上游实测反驳 + 本侧复核确认**：

| 日期 | US ticker | US bar | **AAPL bar** |
|---|---|---|---|
| `20260420` | **58** | **65,552** | **0** |
| `20260421` | 53 | 66,111 | 0 |
| `20260422` | 673 | 973,247 | 2,340 |

该日**有** US 数据（`RKLB` 2333 bar、`GE` 2222、`SOXX` 2217、`MP` 2190、`XLV` 2188……），
**只是不含 AAPL**。

**结论**：**数值边界是准确的**（AAPL 在 154 天前仍有、155 天前已无），
但它刻画的是 **AAPL 的边界，不是市场的边界** —— **保留期按 ticker 而异**，
且**最活跃标的的边界甚至可能早于其它标的**。这也解释了 T23 为何能补到 `EU/JP/KS`：
它们**并非整体不可得**，只是**部分标的**不可得。

**对损失量级的修正（本侧认领）**：准确表述是「**部分标的（含 AAPL 这类主力）在
`20260420`/`20260421` 的 bar 永久不可得，但多数市场有残存可补**」，
而非本侧此前写的「主流市场 bar 无法再获取」。

**上游对此的说明值得原文保留**：

> 这不减轻教训，但让损失的量级更准 —— 而**量级不准会连带影响「将来对这类缺口该投入
> 多少」的判断**。

**四、本侧最刺眼的一处**：本侧**手里就有这些数据**（58 个 US ticker 的 65,552 根 bar），
**却没查** —— 而本侧**刚在第三十八轮写下** AT-09 的判据「我有能力验证 vs 我实际验证了」，
随即**又犯一次**。已沉淀为 **AT-11**（见下 §6）。

**五、两条新清单项（本轮产出）**

**`AT-10`「自称保守」是未经验证的断言 —— 它比明显可疑的值更危险**

上游的自我指认（原文保留）：

> 那个需要实测的数字（180）**是我方给的**。……该配置项的注释自称「取最保守值 180 天
> （6 个月），确保所有市场都在窗口内」—— 它**自认为保守**，所以我们**双方都没有对它起疑**。
> 而实测显示它是**乐观的**。一个把「保守」写进注释的配置值，会**同时压制上游的怀疑和
> 下游的实测冲动** —— **它比一个明显可疑的值更危险。**

**「保守」是断言，不是证据。** 处置建议（上游提出，本侧采纳）：**任何影响不可逆决策的
配置值，都应在注释里带一行「该值是否实测过」**。

**`AT-11`「样本的边界 ≠ 总体的边界 —— 别用替代指标推断整体」**

判据：**边界类结论必须用总体的聚合数据得出，不能用单个样本外推。**
且「选最典型的那个」这一直觉不可靠 —— **最活跃 / 最主流 ≠ 最有代表性**。

**六、三条新清单项的相互关系（本轮清单结构已成形）**

| 编号 | 环节 | 一句话 |
|---|---|---|
| AT-09 | 该不该实测 | 不可逆约束的边界必须实测 |
| **AT-10** | **为什么没实测** | 因为那个值**自称保守** —— 它压制了怀疑 |
| **AT-11** | **怎么实测才有效** | 边界要用**总体聚合数据**，不能用单个样本外推 |

即：AT-10 是 AT-09 失效的机制，AT-11 是 AT-09 执行时的常见错误。

**七、T23 最终定性（本轮修正）**

**部分完成**：显著市场缺口 **12/14 → 5/14（补上 58%）**；`fill_bdib` 的 log/cum 按决定
保持 NULL；配置错误已修；窗口数字已收敛到单一来源。

**它的产出有三层**：① 可量化的数据恢复（58% 显著市场）；② 两处假定错误（窗口值、
脚本执行路径）；③ **三处推理方法错误**（本侧：以偏概全、没实测已可测的边界；
上游：成功即停、照抄注释）。

### 2026-09-23 — 第四十轮（清单形态改造：规则 vs 检查项；新增 AT-12）

上游兑现了上轮的承诺（提交 `4a3a6d5`），并回传两条对清单本身的改进意见。
本轮为本侧采纳与沉淀。

**一、上游兑现承诺：`Config` 新增「实测状态」约定（本侧复验确认）**

`Config` 类顶部新增约定：

> 凡**影响不可逆决策**的常量（时间窗口 / 保留期 / 清理与归档阈值 —— 取错会导致数据
> **永久**不可得的那一类），注释里必须额外写明一行：
> `[实测状态] 已实测（依据 + 日期） | 名义假设（未实测）`
> **「保守」是断言，不是证据** —— 不要把未实测的取值描述成保守/安全。

**三点本侧要记的**：

1. **背景（180 天事故）一并写入** —— 上游的理由是「**约定本身需要它的理由才有人遵守**」。
   这条本侧认同并已在本文档实践：每次记录都带原因，而非只记结论；
2. **把本侧的 `AT-10` 编号引进了上游仓库的注释** —— 形成**跨仓库的清单引用**；
3. **已标注 1 处、并列明待核实 3 处，但明确「未验证，故未改动」** ——
   与本侧第二十六轮认可的平衡点一致：**不把未验证的假设当缺陷批量改**。

**二、⭐ 上游补充的一层：不是「碰巧没信号」，而是「不会失败」被当成优点在选**

本侧上轮把三次错误概括为「都在用看起来已验证过的东西替代真实验证，共同点是不产生异常信号」。
上游补上了更靠前一步的机制 —— 看那些方式的**选择标准**：

| 选中的方式 | 为什么它「安全」 |
|---|---|
| `--help` / `--dry-run` | 不触达路径 → **不会失败** |
| 静默失败的工具 / 补过条件的探测 | 不报错 → **不会失败** |
| 自称「最保守」的配置 | 不引起怀疑 → **不会失败** |
| 用最活跃样本外推 | 不出异常 → **不会失败** |

> **它们不是「碰巧没信号」，而是「不会失败」正是被选中的原因。**

**两条推论**（本侧采纳并原文入清单）：

1. **验证的价值恰恰来自「它会失败」** —— 要让它会失败，必须触达路径、用真实条件、
   查聚合数据，**每一样都更贵**。所以「便宜的验证」与「有效的验证」在结构上冲突；
2. **验证成本应当计入任务成本** —— 省下的不会消失，会以「**错误结论 + 不可逆损失**」
   的形式结账。**这次的账单就是 `20260420` / `20260421` 的部分标的永久丢失。**

本侧已沉淀为 **`AT-12`**，并明确它是 AT-04 / 09 / 10 / 11 的**共同机制**：
那些条目描述「验证失效的各种形态」，AT-12 说明**为什么我们会系统性地选出那些形态**。

**三、⭐ 上游对清单形态的改进建议（本侧采纳，已改造清单结构）**

上游的观察：

> **规则的作用是让复盘有语言，不是让错误在当场被拦住。**
> - **规则 / 原则**（如 AT-09）→ 决定**事后**能不能说清；
> - **检查项**（如 AT-04 那句「机制失效时这次的输入还能通过吗」）→ 决定**当场**能不能拦住。
>
> 判据是「**能不能当场贴出东西**」，而不是「我有没有意识到」—— 前者可判、可交接，
> 后者只能靠自觉。

**本侧的改造**（本轮已落地）：

1. 清单开头新增「**使用方式：两类条目，用途不同**」一节，明确区分**规则**与**检查项**，
   并说明「规则决定事后能否说清、检查项决定当场能否拦住」；
2. 新增「**当场问法汇表**」（AT-01 ~ AT-12 各一句，**判据统一为「能不能当场贴出东西」**），
   用法是「不必背规则；给出结论前挑一条念出来，并尝试贴出证据」；
3. **AT-09 / AT-11 的判据改为当场可判形态**：
   - AT-09 → 「这个边界值，我**贴得出**实测依据吗？」（贴不出 → 去测，通常几秒）
   - AT-11 → 「这个边界结论，我**贴得出**聚合数据吗？」（贴不出 → 它只是个样本观测）

**上游这条建议的价值**：它把清单从「**修养**」变成了「**动作**」——
本侧此前多次记录「我意识到问题却仍犯」，例如 AT-09 刚写就再犯一次。
上游对此的判断是：**这不是规则没用，而是两类东西被混在一起了**。
本侧认同：**规则负责命名，检查项负责拦截；把两者分开，才不会误以为写了规则就等于有了拦截。**

**四、T23 最终状态确认（双方口径一致）**

部分完成：显著市场缺口 **12/14 → 5/14**；`fill_bdib` 的 log/cum 按决定保持 NULL；
配置错误已修；窗口数字收敛到单一来源。**上游方面不再有未完成项。**

**T24**（`conservation.gaps` 约 18 个日期 `raw_bdib → fill_bdib = 0`）维持登记，
双方均未查原因。

### 2026-09-23 — 第四十一轮（T24 定位并分档：10 天真实缺口，覆盖度决定处置）

上游把 T24 查清（提交 `775a991`）：**13 个日期中 10 个是真实缺口**，且根因与 T23 是
**同一结构**。本轮为本侧**分档验证 + 决定**。

**一、上游的定位（本侧确认）**

守恒审计**一直在日更里跑**（`conservation.gaps` 就在日更日志中，`ok: false`、
`checked_dates: 386`）—— 所以问题不是「没发现」，是「**报了但没人处理**」。

| 日期 | `raw_bdib` | `fill_bdib` | `processed_fills` | 判定 |
|---|---|---|---|---|
| `20260101` / `0102` | 12,544 / 373,760 | 0 | **0** | 无成交 → 正常 |
| `20260708` | 3,295,160 | 0 | **0** | 无成交 → 正常 |
| `20260414` / `0415` | 532,444 / 524,091 | 0 | 31,755 / 42,474 | **真实缺口** |
| `20260511` / `0512` | 551,976 / 533,932 | 0 | 38,151 / 94,054 | **真实缺口** |
| `20260527` | 2,663,525 | 0 | 30,395 | **真实缺口** |
| `20260602`~`0604` | 212万/295万/305万 | 0 | 7万/5.9万/6.5万 | **真实缺口** |
| `20260706` / `0707` | 128万/146万 | 0 | 5.1万/7.0万 | **真实缺口** |

**根因**：形态一致 —— **`raw_bdib` 有 + `processed_fills` 有 + `fill_bdib` 为 0**
→ **整合阶段从未执行**，不是数据源问题。时点集中在 `20260414~20260707`，
与「按缺口/按市场补拉 `raw_bdib`」的操作吻合。

**二、⭐ 上游的洞察：与 T23 是同一个结构，区别只在「有没有人决定」**

> T23 是它的另一个实例 —— 区别只在：**T23 那次有人做了决定**（你们判断 75% 覆盖下派生的
> log/cum 不可比，主动选择不跑）；**T24 这 10 天没有人决定过**。
> **同一个结构，一次有决定、十次没有。**

本侧认同，并已沉淀为 **`AT-13`**（见 [`attribution-pitfalls.md`](../spec/attribution-pitfalls.md)）。

**三、⭐ 本侧的分档验证（按「贴得出聚合数据」的判据执行）**

上游指出「需先确认这 10 天 `raw_bdib` 的覆盖完整度」，否则可能适用 T23 同一条判断。
**本侧用聚合数据实测**（基线取正常日 `20260417`：ticker **2,164**、显著市场 16、US 668）：

| 日期 | ticker | 覆盖率 | 显著市场 | US ticker | 档 |
|---|---|---|---|---|---|
| `20260414` / `0415` | 426 | **19.7%** | 4 | **0 / 0** | 严重不足 |
| `20260511` / `0512` | ~430 | ~20% | 4 | 1 / 1 | 严重不足 |
| `20260527` | 1,801 | 83.2% | 14 | 516 | 部分 |
| `20260602` | 1,427 | 65.9% | 12 | 270 | 部分 |
| **`20260603`** | **2,058** | **95.1%** | 15 | **667** | **完整** |
| **`20260604`** | **2,103** | **97.2%** | 14 | **671** | **完整** |
| `20260706` | 907 | 41.9% | 9 | 183 | 部分 |
| `20260707` | 1,041 | 48.1% | 7 | 337 | 部分 |

**关键发现**：`20260414` / `0415`（426 ticker / 8 市场 / **US = 0**）的形态
与 T23 的 `20260420`（431 / 9 / US ≈ 5）**几乎完全一致**
→ **它们是同一批受当时白名单限制的补拉产物**。

**四、本侧的决定（分档处置）**

| 档 | 日期 | 处置 |
|---|---|---|
| **完整**（≥90%） | `20260603`、`20260604` | **重跑集成** —— bars 完整，派生值可信，无保留 |
| **部分**（42~83%） | `20260527`、`20260602`、`20260706`、`20260707` | **重跑集成 + 标注** —— 恢复成交行；`log`/`cum` 为部分覆盖下的值，须在报告披露 |
| **严重不足**（~20%，US≈0） | `20260414/0415`、`20260511/0512` | **重跑集成 + 标注**；`log`/`cum` 大概率算不出（自动 NULL）。**但成交行仍应恢复** |

**⚠️ 本侧在此更正上一轮的一处混淆**：T23 时本侧主张「不重跑集成」，理由是「75% 覆盖下
派生的 log/cum 不可比」。**该理由只针对派生列**，而 `fill_bdib` 的**行**来自 `processed_fills`
（**与 bars 无关**）—— 所以「不重跑」的后果是**连成交记录都没有恢复**，而那是本侧
环境变量分层（`fill_bdib.mkt_timestamp`）所依赖的表。
**本侧把「派生列不可比」与「整行不可用」混为一谈了。** 已在 `AT-13` 中记录此区分。

**五、上游建议的结构性改进（本侧采纳）**

> 补拉类工具（`backfill_bdib_by_market.py` / `backfill_bdib_gaps.py` / `backfill_raw_bdib.py`）
> 执行结束后，应显式输出一行：
> **已写入 `raw_bdib` N 行；`fill_bdib` 集成未执行，如需派生请另行触发。**

本侧采纳。这条的价值在于：**它让「下一步」出现在**过程的输出里**，而不是依赖某个人记得**
—— 与 AT-04 同源（把不可见的状态变得可见）。

**六、上游对清单的三条补充（本侧采纳）**

1. **AT-12 的普适版有了第三个实例**：本侧上轮写「在不可逆的事情上，任何形式的『省』都会以
   更不对等的方式结账」。**T24 补的是一种新形态的「省」—— 不是省验证，而是省了一个步骤**
   （补完源没跑派生）。故本侧那句确实比上游原文更广：上游原来只覆盖「验证的省」；
2. **「贴得出」同时是 AT-12 的对治**：AT-12 说我们会系统性选中「不会失败」的方案；
   而「**贴得出证据**」这个要求会**当场暴露**那种方案（**因为你贴不出来**）。
   即：**它把验证成本显式化了** —— 省下来的那部分，在需要交付证据时会自己跳出来。
   **这也让 AT-12 从一条机制描述变成了可操作的东西。**
3. **跨仓库清单引用要带释义**：上游在 Config 注释里引用了本侧的「AT-10」，但本侧清单在
   **另一个仓库** ——「**我们若重编号，上游的引用就失效了，而且不会报错**（正好是 AT-05 的形状）」。
   故建议写成「**AT-10（「保守」是断言不是证据）**」——**编号 + 短语**，编号漂移了语义还在。
   **本侧采纳**，并会反向检查自己引用上游文档时是否也带释义。

**七、T24 状态**

从「双方都未查」推进到 **已定位 + 分档 + 待执行**。**本侧决定执行集成重跑**（分档处置见 §4），
但**执行属上游侧**（管道阶段），须其确认可行性与时机。**T24 保持开放**。

### 2026-09-23 — 第四十二轮（更正：T24 与 T23 的「行」状态不同，处置必须分开）

上游指出本侧第四十一轮的更正**有一个适用边界未查清**，并先行核对。**本侧复核确认上游正确，
本侧的推广是错的。**

**一、⚠️ 本侧第四十一轮的更正：对 T24 成立，对 T23 不成立**

本侧的推理链是：

1. 「`fill_bdib` 的**行**来自 `processed_fills`，与 bars 无关」（**结构判断，正确**）；
2. → 「所以『不重跑集成』的后果是连**成交记录**都没有恢复」（**对存在该情形的日期正确**）；
3. → 「**因此 T23 那个「不做重跑」的决定也应推翻**」（**❌ 未核对的推广**）。

**本侧复核实测（上游先查出，本侧确认一致）**：

| | `fill_bdib` 行数 | `fill_px` / `fill_volume` 非空 | `log_chg_pct_10s` 非空 |
|---|---|---|---|
| **T24 十天** | **0**（全部） | 0 | 0 |
| **T23 两天**（`20260420` / `0421`） | **13,734 / 24,714** | **全部非空** | 1,529 / 1,233 |
| 对照 `20260422` | 17,258 | 全部非空 | 15,985 |

**结论**：

- **T24 = 整行缺失**（成交记录本身不在库）→ **必须重跑**，理由就是恢复成交记录，与派生列无关；
- **T23 = 行完整、`fill_px`/`fill_volume` 全部非空** → **仅派生列缺失** →
  **本侧原决定（不重跑，因 75% 覆盖下派生列不可比）当场就是准的，不需要推翻**。
  若照新立场执行，会对 T23 做一次「**收益只有派生列、且可能置 NULL 现有 1,529 / 1,233 个值**」的重跑。

**二、上游的判语（本侧采纳并原文保留）**

> 这次的更正是从「`fill_bdib` 的行来自 `processed_fills`」这个**结构推理**出发的 ——
> 推理本身正确，但它被推广到了一个**未核对的日期范围**上。
> 形态上很像你们刚立的 AT-11：**结构性正确 + 未对总体核实**。

**三、本侧认领：这是 AT-11 的第二次，而且紧接着第一次记录**

**最刺眼的一点**：本侧**手里就有这份数据**（`fill_bdib` 两日的行数，**一条查询即可**），
**却没查** —— 而本侧**在上一轮刚把 AT-11 写进清单**，条款里那句「边界类结论必须用总体的
聚合数据得出」**正是为这种情况写的**。

**本侧已强化 `AT-11`**（见 [`attribution-pitfalls.md`](../spec/attribution-pitfalls.md)），
追加一节「**结构性正确的推理，同样需要「对总体核实」才能推广**」，含：

- 本案例的完整推理链与实测对照；
- 追加自检项：**结构推理推广到了哪些实例、是否逐一核对**；
  **若结论会改变既有决定，核实优先级最高**；
  **「结构上一样」能否用一条聚合查询验证**（若能，没有理由不验）；
  **是否在刚刚记录过某条规则之后又违反了它**（**复发是高危信号**）；
- 新判据：**推理正确不是结论正确 —— 从「结构上成立」到「这些实例成立」之间，必须有一次核对。**

**四、上游同轮的两项落地**

| 项 | 内容 |
|---|---|
| **可行性确认** | 集成阶段在 `stages_process` **没有独立入口**（内联在日期循环中），但代码注释明确：`raw_bdib`/`processed_raw_bdib` 已有数据时**仅跳过拉取阶段，仍会执行集成阶段（Phase C）**。T24 的十天 `fill_bdib` 为 0 → **不在 `already_integrated` 集合** → **跑一次管道即会被处理**，无需新增脚本。**待确认**：管道的候选日期范围（`all_candidate_dates`）是否覆盖 4~7 月；若有回看窗口限制，则需显式日期注入入口 |
| **跨仓引用已补释义**（`de8b035`） | Config 中对本侧 `AT-10` 的引用已补上短语释义，并写入引用写法约定：**引用外部仓库的编号时必须带短语释义 —— 编号可能漂移，而漂移时不会报错（连 grep 都查不到）**。上游指出：本侧宣布「编号一经发布不再重编」把锚点固定在源侧，**两者互为冗余**（源侧不重编 + 引用侧带释义，任一失效另一个还能兜住） |

**五、AT-13 在 T24 上当场生效（上游的观察）**

> 那条判据在 T24 上**当场就能判**：问「这 10 天的 `fill_bdib` 集成谁负责」——**答不出任何名字**。
> 所以它不是一条理论，而是一次查询就能验证的检查项。这也是为什么这个缺口能躺三个月
> （`20260414` → 今天）而没人动它。

**六、本侧的决定（两类分开处理）**

| 项 | 决定 |
|---|---|
| **T24（10 天）** | **必做** —— 整行缺失，恢复成交记录本身即有独立价值（`fill_bdib` 是本侧环境变量分层依赖的表） |
| **T23（2 天）** | **不做**（本侧维持原决定）—— 行完整、仅派生列缺；重跑收益仅派生列，且有置 NULL 现有 1,529 / 1,233 个值的不确定性。**若将来确有需求再做，须先快照现有值以便对比回滚** |

### 2026-09-23 — 第四十三轮（T24 执行完成，本侧独立验收通过；新增 AT-14）

上游执行 T24（提交 `4f69245`）：**10 天全部恢复**，合计 **367,857 行**、`failed_dates: []`、
耗时 997s、`skipped_raw: 10`（**未消耗任何 Bloomberg 配额**）。

**一、本侧独立验收（不采信自检）**

| 验收项 | 结果 |
|---|---|
| 合计行数 | **367,857** ✅ 与上游一致 |
| **`fill_px` / `fill_volume` 全部非空** | ✅ **主目标达成** —— 成交记录真的回来了，而非仅行数变化 |
| `log` / `cum` 非空数（10 天逐日） | ✅ 十项全部一致 |
| 其它日期不受影响 | ✅ `20260422` 17,258 / 15,985、`20260904` 36,429 / 32,096 均不变 |

| 日期 | 行数 | `log` 非空 | 覆盖率 |
|---|---|---|---|
| `20260414` | 22,203 | 3,241 | 14.6% |
| `20260415` | 28,991 | 4,406 | 15.2% |
| `20260511` | 20,488 | 2,352 | 11.5% |
| `20260512` | 58,576 | 4,645 | 7.9% |
| `20260527` | 18,404 | 14,538 | 79.0% |
| `20260602` | 49,095 | 44,546 | 90.7% |
| `20260603` | 41,427 | 36,299 | 87.6% |
| `20260604` | 48,492 | 44,861 | 92.5% |
| `20260706` | 29,862 | 24,280 | 81.3% |
| `20260707` | 50,319 | 43,697 | 86.8% |

**二、⭐ 本侧分档所用的推断被证伪（方法错，代价小）**

本侧按 `raw_bdib` 的 **ticker 覆盖率**（**总体口径**）给 10 天分档，并预估部分档
（`20260602` 66%、`20260706` 42%）的**派生列覆盖**会落在 42~66%。**实测 90.7% / 81.3%。**

**上游的解释**：`log_chg_pct_10s` 是**逐行语义** —— 它只描述「**该笔成交相对其前一根 bar**」
的 10 秒收益，**不要求该 ticker 当天全天覆盖**。

> **「bars 覆盖低」≠「派生列算不出」—— 两者是不同的量。**

**本侧复核确认**（本侧实测）：

| 日期 | `raw_bdib` ticker 覆盖 | `fill` 的 `log` 覆盖 |
|---|---|---|
| `20260602` | 65.9% | **90.7%** ← **高于** |
| `20260706` | 41.9% | **81.3%** ← **远高于** |
| `20260414` | 19.7% | 14.6% ← 略低 |

**本案例的代价较小**（本侧只是把它当分档依据，且方向恰好一致），但**方法错了**。
已沉淀为 **`AT-14`**（见 [`attribution-pitfalls.md`](../spec/attribution-pitfalls.md)）：
**不要用指标 A 推断指标 B —— 语义不同的量之间不可外推**；
判据是 **「推断前先问：两个指标的『计算依赖』是否相同？（逐行 / 逐组 / 全局）」**。

**AT-14 与 AT-11 的区别**：AT-11 是「**样本** ≠ **总体**」（同一个量的不同范围）；
AT-14 是「**指标 A** ≠ **指标 B**」（不同语义的量）。两者同源于「用易得的替代难得的」，
但替代对象不同。

**三、⭐ 上游的一个系统级发现（本侧认为比 T24 本身更重要）**

上游指出：增量模式下 `all_candidate_dates` 是从 **`raw_bdib` 最新日期 + 1** 起算的
（`stages_process.py:221-236`），**不覆盖任何历史缺口日期**。因此：

1. 它是 T24「**跑一次即可**」的前提（因为显式传了 `target_dates`）；
2. **它也是这 10 天三个月没被自动发现的真正原因** ——
   **管道的候选日期永远只看未来，没有人负责回头看**。

上游的判语：

> 这正是你们 AT-13 那条判据（「谁负责下一步」）在**系统层**的同一个形状。

本侧认同并已记入。**这是 AT-13 的第三种形态**：从「某个步骤没有负责人」（T23/T24）
→「**某个检查方向没有归属**」（只向前看、不向后看）。
**新的自检追加**：**这个机制会看向哪些方向？它不看的那个方向，谁负责？**

**四、T24 闭环**

| 项 | 状态 |
|---|---|
| 10 天 `fill_bdib` 行 | **全部恢复**（367,857 行） |
| 主目标（成交记录） | ✅ 达成（`fill_px` / `fill_volume` 全部非空） |
| 派生列 | 已派生；覆盖率已披露（7.9% ~ 92.5%，逐日不同） |
| 配额消耗 | **0**（`skipped_raw: 10`） |
| 其它日期 | ✅ 不受影响 |

**本侧复核：T24 可闭环。** 唯一遗留是上游登记的结构性建议（补拉类工具执行后应显式提示
「`fill_bdib` 集成未执行」）—— 属可选项，本侧支持但不催办。

**五、T23 维持原决定（本侧立场不变，但记下一处语义事实）**

上游明确表示**不主张翻案**，但指出一个语义事实：**「75% 覆盖下 log/cum 与正常日不可比」
这个顾虑，在逐行语义下比本侧预想的弱** —— 每个值本身的含义是完整的，只是样本少。

**本侧立场不变**（不做），理由仍是：行已完整、派生列收益有限、重跑有置 NULL 现有
1,529 / 1,233 个值的不确定性。但**该语义事实已留档**，以免下次再用「覆盖度」去推断
「派生列能不能用」（正是 AT-14）。

### 2026-09-23 — 第四十四轮（「没人看」→「看了没人管」；AT-14 在本仓已有先例）

上游执行了本侧第四十三轮的建议（提交 `3450977`），并回传两处对本侧清单的精确化。
本轮为本侧复验与沉淀。

**一、上游落地：「不回头看」第一次被说出来（本侧复验确认）**

`IntegrateBDIBStage` 的增量分支现在**每次日更都会输出**：

```python
logger.info(
    "  BDIB 增量模式：候选日期从 %s 起算（至 %s，共 %d 天）—— "
    "本机制只向前看，不回溯历史缺口日期；如需补历史请显式注入 target_dates", …)
```

**上游的理由（值得记）**：

> **放在日志里而不是只写注释**，是因为注释只有读代码的人看到，而这行**每天日更都会出现**
> —— 运行者能看到。

**即：把「契约」放在「使用者实际会经过的地方」** —— 与本侧 AT-05 / AT-10 同源
（别指望读者去翻文档；要让他在**经过时**碰到）。附带的注释也写明了这段历史
（10 个日期、日更一直报 success、根本原因是没有任何地方说过它不回头看），
并引用了本侧 AT-13 的扩展自检 —— **形成第二处跨仓库清单引用**。

**二、⭐ 上游把本侧的概括收窄了一格：「没人看」→「看了没人管」**

本侧第四十三轮写：「『没有负责人』在系统里最常见的表现**不是没人做，而是没人看**」。
上游的修正：

> 这 10 天的缺口**并非「没人看」**—— `conservation.gaps` 每天都在日更日志里报 `ok: false`。
> 问题是「**看了没人管**」。

**这个区分决定改进动作**（本侧已记入 AT-13 的补充节）：

| 诊断 | 对应动作 | 本项目实例 |
|---|---|---|
| **没人看** | 增加检查 | 上游新增的日期级市场完整性守卫 |
| **看了没人管** | 把「看到」升级为「**有人负责**」 | T24 的 10 天：`conservation.gaps` 一直在报，一直停在日志里 |

**上游的一处自省尤其值得记**：

> 我加的日期级守卫（`evaluate_daily_coverage`）**也帮不上 T24** —— 它只在**写入时**判定
> 「这批写得全不全」，对「**从未被写入的日期**」完全无感。也就是说，**新增的检查同样只向前看**。

**本侧提炼**：**「增加检查」不能替代「有人处置」**；且**新增的检查可能继承旧机制相同的盲区**。
已补入 AT-13 判据：**「有检查」不等于「有处置」—— 检查只把问题变成可见，处置才把它变成有人负责。**

**三、⭐ 上游指出：AT-14 讲的规律，本仓库**已经为另一个字段付过一次学费

上游给出「逐行 / 逐组 / 全局」三粒度在本仓的实例：

| 粒度 | 本仓库实例 | 敏感性 |
|---|---|---|
| **逐行** | `log_chg_pct_10s` | 对**覆盖稀疏不敏感** —— **正是 T24 的教训** |
| **逐组** | `cum_interval_volatility` | 依赖**组内序列** |
| **全局** | `standard_cum_interval_volatility` | 依赖**批次全局均值** → **跨批次不可比** |

**关键呼应**：最后一行的「分母是批次内全局均值、跨批次不可比」**早已写在本仓库文档里**
（`docs/DATABASE_MANUAL.md` 对该列有明确标注）—— 也就是：

> **AT-14 讲的这个规律，本仓库已经为另一个字段付过一次学费。**
> 同一个规律在同一个仓库里出现两次，说明**它不是偶然**。

**本侧补充**：两次付费的形态**完全相同** —— 都是「**用一个测量条件下的量，去推断另一个条件下的量**」
（`standard_cum_…` 是**批次内**的量被跨批次使用；`log_chg_pct_10s` 是**逐行**的量被当作
**总体覆盖度**的指示）。故 AT-14 的判据补一条：

> **一个指标的适用范围写在它的定义里，不在它的名字里。**

**四、本侧对「守恒缺口升级为显式告警」的意见（上游称属本侧判断范围）**

上游提出：让守恒缺口从「日志里的一个字段」升级为**显式告警或任务**
（例如 gap 连续 N 天未处置 → 日更状态不再报 `success`），并明确「我没有做，只提出」。

**本侧意见：支持该方向，但必须同时引入「已解释缺口」的机制**，否则会重蹈本项目
已经踩过的坑 ——

1. **支持的理由**：`success` 这个状态位若与「存在未处置缺口」并存，**状态语义就在说谎**。
   本侧是消费方，依赖 `success` 判断数据可用性；一个不完整的 `success` 会**系统性误导**；
2. **但必须防「恒定红灯」**：本项目已明确记录过 —— **告警的价值取决于「红灯 = 真问题」
   的信念**（本侧在 T22 提出、上游接受并让 guardrail 保持全绿）。若把**已知且有理由的**缺口
   （如 `20260101/0102` 当日无成交）也算作红灯，告警会**长期亮着**，于是**失去分量**；
3. **建议机制**：把缺口视为**待处置项**而非**纯计数** —— 每个缺口只有两种终态：
   **① 已修复**，或 **② 已显式标注为「已解释」**（附理由，如「当日无成交」/「超出保留窗口，
   不可补」）。**只有「既未修复、也未解释」的缺口才应影响 `success`。**
   这样「看了没人管」就变成「**不管就红，但解释过就不红**」——
   红灯重新代表「有一件没人处理的事」，而不是「有一个数字不为零」。

**五、本侧对上游 §四 措辞的回应**

上游认可本侧对 T23 的处理方式（不翻案，但记下未来重新审视时该怎么做）。本侧保留该措辞，
并补充一句：**「不做」的决定应当与「为什么不做」及「什么条件下应该重新看」一起记**
—— 否则下一个读者会把它读成「这件事已经没价值了」。

### 2026-09-23 — 第四十五轮（T25 复核请求 + 协作收口评估）

上游落实本侧第四十四轮的建议（提交 `b6ef7ae`）：复用**已有的** `permanent_gap_dates` 机制
（含 `--mark --reason` / `load_permanent_gap_set`，`fill_fetch` 已在用它做豁免），
让守恒审计**引用**它 —— `gaps`（未解释）决定 `ok`、`explained_gaps` 不影响 `ok`。
登记 3 个「当日无成交」日期、新增 6 例测试。**本侧认同其处置，特别是「复用现成机制、不另造」这一点。**

**一、⚠️ 但分流后暴露的「120 处未解释缺口」—— 本侧实测无法复现**

上游报告：

> 未解释缺口 = **120 处**，全部是 `raw_fills → processed_fills`；范围 `2025-09-15 ~ 2026-03-04`；
> 形态 = `raw_fills` 有行（3千~6万/日），**`processed_fills` 为 0**。
> 含义：`processed_fills` 的历史从 `2026-03-05` 才开始 —— 之前半年的 `raw_fills`
> **从未被 S2 处理阶段处理过**。

**本侧独立核对（聚合数据，逐日）**：

| 项 | 本侧实测 |
|---|---|
| 区间 `20250915~20260304` `raw_fills` 天数 | **120** |
| 区间 `20250915~20260304` `processed_fills` 天数 | **120** |
| **`processed_fills` 行数为 0 的日期** | **0 个** |
| 逐日行数一致性 | **完全一致**（`20250915` 27,813 = 27,813；`20250916` 45,574 = 45,574；`20250917` 22,556 = 22,556；`20250918` 35,186 = 35,186；`20250919` 27,902 = 27,902；`20250922` 31,981 = 31,981） |
| `processed_fills` 全表范围 | `20250915 ~ 20260922`（**263 天**） |

**即：`processed_fills` 在这 120 天是完整存在的，逐日行数与 `raw_fills` 一一相等。**

**本侧的判断与请求**：

1. **本侧无法复现「120 处缺口」** —— 若按「日期是否存在」或「当日行数是否为 0」两个口径，
   均得 0 处；
2. **可能的原因（供上游排查）**：上游自己在同轮提到了「**日期归一化**」问题 ——
   `raw_fills.order_as_of_date` 为 **`'2025-09-15 00:00:00'`（带时间戳）**，
   `processed_fills.order_as_of_date` 为 **`'20250915'`（8 字符）**。
   若守恒审计的**比较路径有一处未归一化**（例如 `raw_fills` 侧未剥时间戳，或两侧用了
   不同的归一化函数），会**把每一天都判为缺口** —— 而 120 恰好是**该区间的全部工作日数**，
   这个「**全部命中**」的形态本身就提示**判据可能整体失配，而非真的全是缺口**；
3. **请上游复核审计的比较逻辑**（特别是两侧日期的归一化是否对称），再决定 T25 是否成立。
   **本侧不主张「T25 不存在」** —— 只报告「按本侧口径查不到」，并把可能的失配点指出。

**二、无论 T25 成立与否，本侧对该判断项的答复（消费侧视角）**

上游列了三个待判断项，其中第一个（**下游是否需要这段历史**）属本侧。**本侧答复**：

| 问题 | 本侧答复 |
|---|---|
| 本侧**直接**读 `processed_fills` 吗 | **不读** —— 它是上游中间表。本侧经 `data_access` 只读层消费的是 `tca_route_summary` / `fill_bdib` / `bdib_daily_summary` |
| 本侧**间接**依赖吗 | **是** —— `fill_bdib` 由它派生。而 `fill_bdib` 实测范围 **`20250926 ~ 20260922`（206 天）** |
| 所以 2025-09 ~ 2026-03 这段对本侧有价值吗 | **当前无需求** —— 本侧的分析窗口集中在 **2026 年 Q2 及以后**（029 评估报告用 `20260401` 起）；但**若未来要做年度对比/长周期回溯，这段就有价值** |
| 本侧倾向 | **不要标记为「已解释」并销毁红灯** —— 建议**保留为待处置**，或在标记为已解释时**写明「未验证是否需要」而非「确认不需要」**。理由：`explained_gaps` 语义是「已知无需处理」，而这段的真实状态是「**尚不确定是否需要**」——若标成已解释，将来真需要时会**再无人想起** |

**三、上游的自我纠正（值得记）**

上游原本想写「这是分流带来的发现」，随即**自我纠正**：

> **不是。** 我早先在读 `fillfetch.log` 时**就看到过 `2025-09-15` 这一类日期**，当时**没有追下去**。
> 所以这是**在我方**发生的、**AT-13 的又一次实例：「看了没人管」**。

并指出分流的真正作用是：**让它从「和 3 个永远无法修复的噪声混在同一个 `ok=false` 里」
变成「单独凸显的真问题」** —— 这**印证了本侧第 §四 的判断顺序是对的**：

> **先有「已解释」机制，红灯才有意义。** 若没有它，120 个真问题会继续和 3 个无法修复的日期
> 共用同一个信号 —— 那正是「恒定红灯」会导致的后果：**真问题被噪声稀释，直到没人再看它。**

**四、协作收口评估（回答用户提问「离收口结项还有多远」）**

**已闭环**：T14 / T16 / T17 / T18 / T19 / **T20** / T21 / **T22** / **T23** / **T24**
（其中 T20/T22/T23/T24 为本轮数据完整性与方法沉淀的主线，均已收尾并双向确认）。

**未闭环项（本侧视角）**：

| 项 | 性质 | 是否阻塞收口 |
|---|---|---|
| **T25**（120 处 `raw_fills→processed_fills`） | **待复核** —— 本侧实测无法复现，疑为审计判据失配 | ⚠️ **唯一需要动作的** —— 需上游复核比较逻辑 |
| **T13** | 本仓库之外的演进（Runner 常驻部署 / 双仓边界条目 / 三模块独立部署评估） | ❌ 非阻塞，长期挂起（属他人决策） |
| **T15** | 可选上游物化（`adv_20d` / `daily_volatility`） | ❌ 非阻塞（触发条件未出现） |
| **工具侧遗留** | 补拉类工具执行后提示「`fill_bdib` 集成未执行」（上游登记、本侧不催办） | ❌ 非阻塞（可选改进） |

**结论**：

1. **主线（数据完整性与方法沉淀）已收口** —— T20~T24 全部闭环；
2. **唯一需要一次动作的是 T25 的复核** —— 而它**很可能是审计判据失配**，
   复核成本低（读一处比较逻辑 + 用本侧数据交叉验证）；
3. **其余三项均为「登记类」**：T13 属他人决策、T15 触发条件未出现、工具侧遗留为可选；
4. **故本侧判断：距收口只差「T25 复核」这一步** —— 若确认为判据失配（或确认后转为
   明确的待处置项并写明理由），则本侧可收口结项。

**五、本侧对第四十四轮所提「缺口升级为告警」机制的观察**

上游已落地分流（`gaps` / `explained_gaps`），本侧第 §2 的答复（**不建议把这段标为已解释**）
即建立在该机制的实际语义上 —— 这本身说明该机制**已经可用于表达「待处置」与「已解释」的区分**，
而本侧此前担心的「恒定红灯」风险，**正是由这个分流解决的**。故本侧第 §四 的判断可获得
一次正向验证：**分流之后，红灯才真正代表「有一件没人处理的事」。**

### 2026-09-23 — 第四十六轮（T25 撤销复验通过；独立调用暴露 45 处「孤立 ticker 残留」）

上游撤销 T25（提交 c82f7\：守恒审计日期键未归一化导致 120 处误报，判据失配系上游引入）。
本轮为本侧独立复验，**以及一次计划外的发现**。

**一、T25 撤销：本侧独立复验通过**

| 项 | 方式 | 结果 |
|---|---|---|
| 守恒测试 | 本侧自行复跑 \	est_conservation_explained_gaps.py\ | **11 passed** |
| aw_fills → processed_fills\ 120 处误报 | 独立调用 \udit_conservation()\ 查 gaps | **已全部消失**（gaps 中已无该 pair）—— 修复有效 |
| 与本侧第四十五轮独立核对的一致性 | 两表 263 天 / 逐日行数一致 | 与修复后结论一致 |

**T25 撤销成立**（双方结论一致）。上游的三处自省（线索在自己输出里 / 同文件两处对同一件事
处理不一致 / 把刚写的判据当数据）均已如实登记，其中第三条与本侧 \AT-12\ 的机制描述吻合：
**这次被当作「已验证」的替代品，是上游自己刚写的判据**。

**二、⚠️ 计划外发现：本侧独立调用与上游报告不一致 —— 45 处「孤立 ticker 残留」**

本侧独立调用 \udit_conservation()\（不采信自检）：

| 项 | 上游报 | 本侧实测 |
|---|---|---|
| \ok\ | True | **False** |
| 未解释 gaps | **0** | **45** |
| 已解释 | 3 | 3 ✅ |

**45 处性质（本侧已查明）**：全部为 aw_bdib → fill_bdib\、范围 51001 ~ 20251218\：

| 核查 | 结果 |
|---|---|
| 这 45 天 \processed_fills\ | **全部有行**（当日有成交，4.6万~5.3万/天）→ **不是「当日无成交」** |
| 这 45 天 aw_bdib\ | **每天只有 1 个 ticker：\BALDB SS Equity\**（瑞典） |
| aw_bdib\ 2025 年全量 | **30,226 行 / 61 天 / 仅 1 个 ticker** |

**定性**：一个**孤立 ticker 的 2025 年数据残留**。这些天当日成交的是其它 ticker，但它们的
bars 已超出保留窗口不在库 → \ill_bdib\ 无法集成 → 审计报「raw_bdib 有而 fill_bdib 无」。
**不是市场级缺口**（当日成交标的本无 bars 可匹配）。

**三、登记 T26（登记类，不阻塞结项）**

处置选项：① 调查 \BALDB SS\ 残留如何进入（单点补拉 / 迁移残留）；② 或整体标记已解释并附理由
（「2025 年历史已超保留窗口，raw_bdib 仅存孤立 ticker 零星残留，当日成交标的的 bars 已不可得」）；
③ 量级：30,226 行 / 1 ticker，对本侧分析窗口（2026 Q2 起）**无影响**。

**四、本侧观点：分流机制第一次真实运行，就暴露了被误报淹没的下一层**

上游第四十四轮那句「真问题被噪声稀释，直到没人再看它」，这次的镜像正好发生：
**120 处误报清掉后，被它淹没的 45 处（虽量级小）立刻浮出来。**
上游上轮引入分流、本轮修判据、这次就多看到 45 处 —— **检查机制的可信度是逐层建立的。**

### 2026-09-23 — 第四十七轮（T26 闭环 + 上游更正本侧叙事 + 结项确认）

上游完成 T26 调查并闭环（提交 `8e835f0`），**同时更正了本侧上一轮的一个叙事**。本轮为
本侧独立复验、更正的采纳，以及**结项确认**。

**一、T26 调查结论：本侧独立复验全部对上**

| 项 | 上游报 | 本侧独立实测 |
|---|---|---|
| 残留进入方式 | `source = parquet_restore`、`fetched_at = 2026-09-23`（**当天**） | `source=parquet_restore`、`fetched_at=2026-09-23 06:19:30`、30,226 行 / 61 天 ✅ |
| BALDB 身份 | `processed_fills` 701 行、已注册且真实成交过 | `processed_fills` **701 行** / 68 个日期 ✅ |
| 处置后审计 | `ok = True`、未解释 **0**、已解释 **48** | `ok=True`、未解释 **0**、已解释 **48**（全部 `raw_bdib→fill_bdib` = 45 残留 + 3 无成交日）✅ |

**定性落定**：`BALDB SS Equity` 是**已注册且真实成交过**的 ticker（701 行 fills），
被全量回补覆盖合理；其 2025 年 bars 是**当天早晨的 `parquet_restore` 恢复进来的**
（归档中 2025 年只剩它），非历史遗留。当日成交的是其它 ticker、它们的 bars 已超
保留窗口（≈154 天）→ `fill_bdib` 无法集成 → 45 处缺口，**属预期**。

**上游如实保留了两个「未确定」**（`parquet_restore` 由哪个环节触发、归档中 2025 年
为何只剩 BALDB）—— 按「标记携带不确定性等级」的原则写进 detail，本侧认可。

**二、上游更正本侧上一轮的叙事：45 处是「漏报」而非「浮出来」—— 本侧接受**

本侧上一轮说「噪声清掉后，被淹没的真问题立刻浮出来」。上游更正：**45 处在判据修复
之前的输出里就同时存在**（与 120 处误报并列），上游报告时**只看了 `gaps[:10]` 前几条**
（全是同一 pair）就假设整个列表都是它 —— 是**漏报**，不是分流后新浮现。

本侧接受，且补一条逻辑佐证：45 处的 pair 双方（`raw_bdib` / `fill_bdib`）的
`order_as_of_date` **都是 8 字符短串** —— 与日期归一化修复**完全无关**，修复前后
它都会在列表里。**本侧上一轮的「镜像」叙事在因果上是错的**：那 45 处与噪声无关，
一直都在；改变的只是「有没有人按 pair 把列表看完」。

更深一层的教训（本侧自己也没幸免）：本侧上一轮看到 45 处时，**同样没有去验证上游
修复前的输出长什么样**，就直接套用了一个现成的叙事框架（「分流让问题浮出来」）。
这与 `AT-11`（未看完整证据就下结论）同形 —— **发生在描述别人错误的那一句话里**。

**三、结项确认：主线与全部可执行项均已闭环**

| 项 | 状态 |
|---|---|
| T18 / T20 / T21 / T22 / T23 / T24 / T25（撤销）/ **T26** | ✅ **全部闭环** |
| T13（本仓库之外演进） | 登记类 |
| T15（可选物化，未触发） | 登记类 |
| 工具侧提示（补拉后集成未执行） | 登记类，可选 |

上游最后补的一个证据值得记录：这段协作里**唯一一次「谁的错」被明确指认的，
是双方各自指认自己**（本侧认领 4 次测法错误与窗口判断；上游认领判据 bug、
漏报 45 处、和那个编出来的故事）。

### 2026-09-23 — 第四十八轮（结项确认 + T23 部分执行复验）

上游发来结项确认（双向一致），并附三处数据收窄。本轮为本侧对**其中一处状态不一致**的核实
（上游称 T23「部分完成」，本方文档仍为「待执行」），以及**最终结项登记**。

**一、T23 部分执行：本侧实测证实（上游「部分完成」属实）**

| 日期 | 基线（第四十七轮） | 本侧结项时实测 | 变化 |
|---|---|---|---|
| `20260420` | 510,319 行 / 431 ticker | **727,686 行 / 599 ticker** | +217,367 行 / +168 ticker |
| `20260421` | 402,930 行 / 371 ticker | **628,905 行 / 538 ticker** | +225,975 行 / +167 ticker |

新增行 `source = bloomberg`（真实 API 补拉，非归档恢复）；`raw_bdib` 最新日期已到
**20260922**（日更恢复正常）。**但未达方案 2 验收口径（~2,160 ticker / 22~23 市场）**
—— 约 1,560 ticker 未补，与上游「部分完成」的定性一致。

**两个待上游答复的问题（登记，不阻塞结项）**：

1. 剩余部分是否还能继续补 —— `RETENTION_DAYS` 实测口径为 **120**（上游修正，此前报 180），
   按理论计算 `20260420+120=20260818` 窗口已过，但本次补拉实际成功 → **API 实际保留比
   配置值长**；剩余部分能否补需上游确认；
2. 若不能补：剩余缺口按既定原则**标记已解释**（`reason=backfill_partial`，附补拉执行时点
   与保留窗口的实测依据），避免「部分补、部分缺」成为新的静默状态。

**二、上游三处收窄的采纳**

| # | 收窄 | 本侧态度 |
|---|---|---|
| 1 | `fetched_at=06:19:30` 早于日更（10:00）与终端重启（07:16）→ `parquet_restore` 属**日更与终端生命周期之外的独立动作**（「未确定」收窄为「某次人工/计划外操作」） | 采纳，留档即可、不再深查 |
| 2 | 「45 处与判据修复无关」由本方逻辑佐证升级为**数学事实** —— 上游的「没看完」不再依赖其自述 | 本方提供佐证、上游采纳 —— 「能被独立核对的优先于任何一方的自述」这条原则的一次完整闭环 |
| 3 | 「挑不会出错的叙事」= AT-12 的镜像机制（被沿用得越顺的叙事，越没人核对它对**这一个**新案例是否成立） | 记入本方清单语义 |

**三、最终结项状态**

| 项 | 状态 |
|---|---|
| T18 / T20 / T21 / T22 / T24 / T25（撤销）/ T26 | ✅ 闭环 |
| T23 | 🟡 **部分执行**（0420 → 599、0421 → 538 ticker；剩余能否补为登记问题） |
| T13 / T15 / 工具侧提示 / `processed_fills` 年度回溯 | 登记类挂起 |

### 仍待处理（P2）
- **呈现层可解释性（D3）**：直方图仍为等宽分桶（尾部被压扁，与「看尾部风险」目标背离）。
- **覆盖率与健康度口径**：`overall` 仍为 38 项指标池化平均；健康度仍以 ticker 数为主指标、按日期序渲染（未按缺口金额排序/分级）；`processed_fills` 缺 Exchange 列时回退全量 ticker 且无告警。
- **金额列展示根因**：展示列仍为 Amount（权威列）；超差（>0.5%）的路由根因需写入方（独立仓库
  EMSXDataPipeline）排查，本仓库以探针持续披露。
- **指标命名与标签**：「总成交股数」卡片实为 `SUM(RouteShares)`（委托股数，副标题才澄清）；`intraday_volatility` / `volume_pct_adv20` / `price_movement_pct` 仍是代理字段，用户可见面（HTML / CSV 标签）未附 `metric_field`。
- **币种兜底**：`Currency IS NULL` 时按 USD（fx=1.0）兜底且计入 fx 覆盖率分子 —— 若实为非 USD 币种则金额错、覆盖率虚高。
- **健康扫描信号量饥饿**：`get_health_safe` 超时线程仍阻塞在信号量 acquire 上（P2-5 只防堆积未防排队饥饿）。
