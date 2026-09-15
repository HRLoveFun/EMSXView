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
- 异常明细 HTML 渲染上限 **1000 条**（按严重度降序排列，截断样本无偏）；全量明细经随附 `anomaly_<hash>.csv` 导出（CLI 侧与 HTML 同目录落盘；API export-html 侧 HTML + CSV 打包为 zip 下载，`export_ref` 不再为空）
- BDIB 缺口附录在扫描超时 / 异常时显式标注「未扫描」，与「无缺口」区分
- USD 换算覆盖率按「可换算路由占比」计（含 USD 路由与 `fill_bdib` 回填汇率），并披露被排除的本币金额
- BDIB 缺口附录的缺口成交金额与 KPI **同源换算**（`fill_bdib` 回填 + 小计价单位修正 + 逐行换算）；缺汇率的路由不计入 USD 金额，其本币金额单列披露为「未换算金额」（缺口低估规模可见）
- 区间内 **TCA 整日缺失**（有成交但无 TCA 汇总，管道 S5.5 未产出）经差集检测自动定位，在报告头数据质量区披露并在覆盖率表橙底行高亮 —— 该情形此前对走势/覆盖率/附录三处交叉验证全体失明
- **SLA 覆盖率分母**对 `bdib_missing` 类指标剔除「BDIB 缺口路由」（有成交但核心 BDIB 依赖指标全 NULL）；纯竞价豁免分母含零成交路由 —— SLA 口径自此隔离管道缺口波动，与原始口径保持区分度
- 按日走势仅含「有数据交易日」（**不补零**，避免把无数据伪装成零成本），并标注覆盖天数；缺失定位见覆盖率表与数据质量提示
- 异常规则键为 `pnl_vwap_bps`（语义 = `|pnl_vwap|` 阈值；原名 `tracking_error_bps` 已弃用，旧键仍兼容读取）

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

### 仍待处理（P1/P2，不在本次 P0 范围）

- **异常明细节流未披露**：`min_fill_count` / `min_notional_usd` 排除的条数仍未回传，读者无法得知异常样本被截取多少（已对严重未完成豁免，其余仍静默）。
- **金额列未同源**：异常明细金额用 `Amount × fx`，KPI 金额用 `fill × p_avg × fx`；两列缺同一性校验，异常表金额与「总成交金额」可能不可对账。
- **覆盖率与健康度口径**：`overall` 仍为 38 项指标池化平均；健康度仍以 ticker 数为主指标、按日期序渲染（未按缺口金额排序/分级）；`processed_fills` 缺 Exchange 列时回退全量 ticker 且无告警。
- **呈现层可解释性**：按日走势仍各自归一化且无刻度/零轴；排行仍 `ASC + 前 10`（最优在前、无样本门槛）；直方图仍为等宽分桶；PWP 五档仍为简单平均（缺陷 3）。
- **指标命名与标签**：「总成交股数」卡片实为 `SUM(RouteShares)`（委托股数，副标题才澄清）；`intraday_volatility` / `volume_pct_adv20` / `price_movement_pct` 仍是代理字段，用户可见面（HTML / CSV 标签）未附 `metric_field`。
- **币种兜底**：`Currency IS NULL` 时按 USD（fx=1.0）兜底且计入 fx 覆盖率分子 —— 若实为非 USD 币种则金额错、覆盖率虚高。
- **前端缺少超成交标记**：数值信号已恢复（`formatPct` 不再封顶，overfill 的 >100% 可见），但 HTML 报告在完成率单元格附的「超成交」标记与订单参与率的「>100%」标记尚未在网页异常明细表渲染（`TcaAnomalyRow.overfill` / `order_par_gt100` 字段已具备，属呈现增强）。
- **健康扫描信号量饥饿**：`get_health_safe` 超时线程仍阻塞在信号量 acquire 上（P2-5 只防堆积未防排队饥饿）。
