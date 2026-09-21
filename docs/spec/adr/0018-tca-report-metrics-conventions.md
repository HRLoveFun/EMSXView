# ADR-0018: TCA 报告指标口径与异常严重度语义

> 状态: Accepted
> 日期: 2026-09-11
> 标签: costview, analytics, data, frontend, backend

## 背景 (Context)

CostView 报告（HTML 导出 / Monitoring）在评估指标层面暴露出一组口径与呈现缺陷：

1. **加权口径与金额语义不符**：加权均值权重为 `RouteShares × p_avg`（意图规模），而 KPI「总成交金额」为 `SUM(fill × p_avg)`（实际成交额），两者不可互校；低完成率路由的成本被系统性高估。
2. **简单平均与加权体系混用**：`avg_par_rate` / `avg_rpm` / `avg_fill` 用算术平均，被小单主导；大额未成交对完成率不敏感（99 个小单全成 + 1 个巨单零成交 → 显示 99%）。
3. **数据矛盾被展示层掩盖**：`_fmt_pct` 对完成率强制封顶 99.99%；`fill > RouteShares`（overfill）与订单参与率求和 >100% 均不进入异常清单，数据质量问题不可见。
4. **严重度分级缺失**：阈值单档化（ADR-0015）后，`pnl_vwap = 10.1bps` 与 `= 500bps` 在报告中同为单一红色标签，无法分级处置。
5. **截断样本可能有偏**：异常明细渲染截断前 1000 条，但排序按 `pnl_vwap` 升序，与渲染文案「按严重度优先」不符；全量明细无导出通道。
6. **口径脚注漂移**：脚注为硬编码字符串，未随 `sla_coverage`、fx 回填等实现演进而更新。
7. **fx 覆盖率口径误导**：把「USD 路由天然为 1.0」计为缺汇率，导致 USD 占比高的报告覆盖率天然偏低；被排除金额静默从总额消失。
8. **时间范围语义错位**：preset 基于自然日，而 `last=day` 基于数据日期；健康扫描另用 `date.today()`，保留窗口判定与报告期不一致。

## 决策 (Decision)

### 1. 成交额加权为唯一口径

- `_weighted_avg_sql` 权重统一为 `fill × p_avg`，与 KPI notional 同源；KPI / daily_series / rankings / extra_kpis / impact_breakdown 五处复用同一函数。
- `avg_par_rate` / `avg_rpm` 改用同一加权口径；`avg_fill` 改为组合级 `SUM(fill) / SUM(RouteShares)`；新增 `unfilled_notional_usd`。
- **不保留旧口径对比值**（直接切换，代码最简）。

### 2. 数据质量规则显式化

- 新增异常规则 `overfill_pct` 与 `order_par_gt100`（均为 above-strict 100，严格大于；2026-09-15 修订见 §10.4 / §10.5），数据矛盾不再被静默放过。
- 移除展示层封顶；`completion_rate > 1` 单元格附「超成交」标记。
- `order_par_rate` 聚合键改为 `(OrderId, order_as_of_date, Exchange)`，避免跨市场求和失去物理意义。
- 覆盖率服务新增一致性探针 `completion_consistency_pct` / `order_par_consistency_pct`（全量口径，供报告头「数据质量提示」区）。

### 3. 恢复两档严重度（修订 ADR-0015）

- `DEFAULT_THRESHOLDS[key] = {mode, warning, critical, enabled}`；**warning 为进入异常清单的边界（覆盖范围与 ADR-0015 单档时期一致）**，critical 仅用于分级标注。
- `_evaluate_rule` 返回 `none | warning | critical`；hits 增加 `severity` 字段；渲染以双色标签区分。
- 向后兼容 ADR-0015 单档 payload：`threshold` 等价 `warning = critical`（不产生分级）。

### 4. 截断无偏 + 全量导出

- 异常明细排序键改为「严重度优先 + pnl_vwap 升序」，limit 截断发生在排序之后（截断样本必为最严重者）。
- `report["anomaly"]` 分离 `count`（全量）/ `rows`（截断）/ `rows_truncated` / `export_ref`（全量 CSV 相对链接）；HTML 渲染上限取自 `REPORT_SPEC["anomaly_row_limit"]`。

### 5. 口径声明数据化（REPORT_SPEC）

- 新增 `CostView/src/monitoring/report_spec.py` 作为口径唯一真相源；报告脚注由其生成，测试断言其与实现常量一致。

### 6. fx 换算成功率与排除金额

- `fx_coverage` 重定义为换算成功率（有效汇率来自 `COALESCE(tca.fx_rate, fill_bdib 回填)`，或币种本身为 USD）；新增 `notional_usd_excluded`。
- `METRIC_NULL_REASON` 移除 `fx_rate`，并保证与 `COMPUTED_METRICS` 键集合一致（测试断言）。

### 7. as_of_date 全链透传

- `TimeRange` 增加 `as_of_date`；装配脚本 → `build_report(..., as_of_date, preset)` → `BdibHealthService.get_health(..., today=as_of_date)`；报告头展示 preset 与数据截至日。

### 8. 覆盖率与健康度口径统一

- 覆盖率表并排展示原始 / SLA 双口径，单元格 tooltip 标注 NULL 原因，结构性 NULL 以虚线区分，BDIB 缺口日交叉高亮；新增整体 SLA 覆盖率。
- 健康度以缺口 ticker 数精确分级（不再依赖 round 后的百分比），新增 `missing_route_count` / `missing_notional`；`get_health_safe` 降级返回显式 `{"status": "skipped", "reason": ...}`（与「无缺口」可区分）。
- **按日走势不补零**：`daily_series` 仅含有数据交易日，并由 `daily_series_meta.covered_days` + 图表注释披露覆盖天数。理由：0 在成本指标上表示「成本为零」，把无数据日补 0 属数据失真；缺失定位交由覆盖率表与 BDIB 缺口附录交叉核对，不重复造交易日历。

### 9. 异常规则键重命名：`tracking_error_bps` → `pnl_vwap_bps`

- 该规则实为 `|pnl_vwap|` 阈值，原名易与「跟踪误差」混淆；展示标签同步改为 `Pnl VWAP bps`（2026-09-15 标签归一去掉单位后缀，见 §10.5）。
- **旧键迁移（双向兼容）**：
  - 后端 `anomaly_query._normalize_rule_keys` 接受旧 payload 键并映射为新键（新旧同时出现时新键胜出，不静默丢配置）；
  - 前端 `lib/storage.migrateRuleKeys` 在读取 localStorage 时把旧键配置迁移为新键。
- 迁移由测试护栏守住：`test_report_metrics` 的 `test_legacy_rule_key_migrated`、`storage.test.ts`（两条）与 `thresholds.test.ts` 的兼容用例。

### 10. 报告口径层收敛为单一实现源（2026-09-15 P0 修订）

**背景**：对报告模块的评估指标复查发现一类同源缺陷 —— *同一契约在多个小节各写一份实现，
只有一处随迭代演进*，导致同一份报告内数字不可对账：

| 契约 | 分裂形态 | 后果 |
|---|---|---|
| 市场作用域 | 覆盖率按 `Config.BDIB_EXCHANGE` 白名单、KPI / 异常按全量 | 同报告内 overfill 条数与异常表命中不可对账；直方图样本被 out-of-scope 路由稀释 |
| 加权均值覆盖 | 均值只由「指标非 NULL 且有成交额权重」的子集决定，但只披露条数覆盖（且仅直方图 / 排行有） | 缺口集中在大单时 KPI 实为子样本均值却「看起来正常」 |
| 维度过滤 | 聚合器支持多值 `IN`、异常查询按 `= ?` 单值匹配 | 前端多选（逗号拼接）时异常清单静默清空，KPI 却正常 |
| 订单级聚合 | 异常按维度过滤后的行求和、一致性探针按全量 | 过滤视图下 `order_par_gt100` 探针系统性低估 |
| 金额换算 | 小计价单位 / fx 兜底在聚合器与异常查询各写一份 | 新增币种需多处同步，易漂移 |

**决策**：

1. 新增 `CostView/src/monitoring/report_measure.py` 作为口径**实现**的唯一来源
   （`report_spec.py` 仍是口径**声明**的唯一来源，两者由测试断言一致）：
   - 作用域：`resolve_scope` / `scope_condition`（默认 BDIB 白名单；用户指定 exchange 时为用户口径，
     白名单外选择记入 `out_of_scope` 并在报告头告警）；
   - 加权：`weight_cond` / `weighted_avg_sql` / `weight_coverage_select`（成交额口径唯一入口，
     覆盖披露与均值的纳入条件同源）；
   - 订单级：`order_par_aggregate_sql` / `order_par_key`（仅报告期 + 作用域，禁止含维度过滤）；
   - 金额：`usd_fx_expr` / `minor_unit_expr` / `unfilled_price_expr` / 零成交与未计价表达式。
2. **全报告小节共用同一作用域**：KPI / 直方图 / 走势 / 排行 / PWP / 市场概览 / 异常明细 / 覆盖率
   一律由 `build_report` 一次性解析的 scope 生成条件；`filter_options.exchanges` 仍忽略用户
   exchange（下拉需展示全部可选市场，但受白名单约束）。
3. **加权均值必须披露覆盖**：新增 `report["weight_coverage"]`（每指标 `n_used/n_total`、
   `used_weight/total_weight`、`sample_pct`/`weight_pct`/`insufficient`），渲染层在 KPI 卡片与
   冲击分解表标注；阈值 `SAMPLE_COVERAGE_MIN_PCT = 90`（`report_spec` 与实现由测试断言一致）。
4. **零成交路由必须可见**：
   - 缺口金额价格回退链 `p_avg → p_arrival → p_decision → p_close`，缺口口径改为
     `RouteShares − COALESCE(fill, 0)`（fill 为 NULL 视为零成交）；价格全缺时该路由贡献 NULL
     且条数单列披露；
   - 新增 `zero_fill_routes` / `zero_fill_notional_usd`（KPI 卡片单列「零成交路由」）；
   - 异常明细的笔数 / 金额下限对 `fill_pct` critical（严重未完成，含零成交）**豁免**；
     `fill_count` 列缺失（旧 schema）时下限 fail-open 并记录告警，不静默清空清单。
5. **多选过滤统一**：维度过滤改为 `report_measure.dimension_condition`（多值 `IN`），聚合器与
   异常查询共用；订单级聚合改为独立全量查询后按 `(OrderId, order_as_of_date, Exchange)` 回联。

**版本**：`SPEC_VERSION` `2026.09` → `2026.09.2`；`report_spec` 新增 `weight_coverage_min_pct` /
`scope_modes` / `scope_whitelist_source` / `unfilled_price_fallbacks` / `anomaly_floor_exempt`
并由脚注展示。

### 10.1 复核整改（2026-09-15 第二轮，同批提交）

对 §10 的独立复核确认四项 P0 实质落地，并暴露若干一致性问题，已一并整改：

1. **作用域缺口补齐**：健康扫描此前独立取白名单（与报告作用域只在"恰好同源"时一致），
   现 `BdibHealthService.get_health(..., scope=)` / `get_health_safe` 透传作用域，CLI 与
   `export-html` 端点传入报告作用域 → 「全报告小节同口径」成为结构约束而非巧合；
   `_load_order_par_sums` 亦显式传入作用域（与一致性探针同契约，避免无谓聚合全量市场）。
2. **公共 API 契约修复**：`CostView/src/monitoring/__init__.py` 的 `__all__` 清理幽灵导出
   （维度表写侧符号随 010-extract-pipeline 迁出），并导出 `ReportScope` / `resolve_scope`；
   新增「`__all__` 每个符号可解析」护栏。
3. **下拉口径一致**：`filter_options.exchanges` 两条路径（维度表 / 回退）统一按白名单裁剪，
   消除同一份报告的市场可选集随「维度表是否就绪」漂移；显式越界选择仍由 `out_of_scope` 告警承接。
4. **声明-实现绑定**：`anomaly_floor_exempt` 由字符串改为结构化 `{"rule", "severity"}`，
   实现常量（`report_measure.FLOOR_EXEMPT_RULE` / `FLOOR_EXEMPT_SEVERITY` / `is_floor_exempt`）
   与声明由测试断言一致。
5. **口径对称性**：异常判定对 `fill IS NULL` 按零成交处理（与 KPI 的 `COALESCE(fill, 0)` 同口径），
   消除「KPI 数得到、异常清单看不到」的不对称；`resolve_scope` 大写归一后去重。
6. **工具修正**：`scripts/quality_gate/run.py` 补 `__main__` 守卫（`python -m` 形式此前只 import
   不扫描且 exit 0）。pre-commit 使用的是平铺入口 `scripts/quality_gate.py`（本身有守卫），
   故门禁实际一直在执行。

### 10.2 前端口径对齐（2026-09-15 第三轮）

HTML 导出已完整披露加权覆盖与统计范围，而网页 Report 页看不到 → **同一报告两个端口径不对账**，
与 §10 消除的问题同构，故一并闭合：

1. **类型契约补齐**：`types.ts` 新增 `TcaReportScope` / `TcaWeightCoverage` / `TcaWeightCoverageEntry`，
   `TcaReportSummaryFilters` 增 `scope`（及 `as_of_date` / `preset`），`TcaReportExtraKpis` 增
   `zero_fill_routes` / `zero_fill_notional_usd` / `unfilled_notional_unpriced_routes`，
   `MetricCoverageReport` 增 `scope`，`TcaReportSummary` 增 `weight_coverage`。
2. **展示唯一实现**：前端展示函数集中在 `lib/report-format.ts`
   （`formatWeightCoverage` / `appendNote` / `formatScopeLabel` / `formatScopeWarning` /
   `formatUnfilledSub` / `formatZeroFillSub`），**文案与 HTML 渲染器逐字对齐**（含「样本/权重覆盖不足，
   结论仅供参考」与白名单外市场告警），避免两端各自措辞再次分叉。
3. **接入点**：`ReportView` 的 KPI 卡（加权 pnl_vwap / par_rate / RPM / arrival / IS / 风险逐卡附披露）、
   新增「零成交路由」卡、未成交缺口副标题附价格回退链与未计价条数、报告头显示统计范围与数据截至日、
   白名单外选择渲染告警条。
4. **测试**：新增 `lib/report-format.test.ts`（10 条）；`npx vitest run src/modules/costview` → 49 passed，
   `npx tsc --noEmit` 通过。

### 10.3 前端展示层收尾（2026-09-15 第四轮复核）

1. **冲击分解表接入覆盖披露**：`ImpactBreakdownTable` 增 `coverage` prop，逐行按指标键附
   「样本 / 权重覆盖」，与 HTML 报告同一张表同措辞（此前该表是 S2 唯一未接入面）。
2. **移除 `formatPct` 封顶（回归本 ADR §2）**：前端 `formatPct` 此前仍把完成率 / 参与率钳制在
   100%，与 §2「移除展示层封顶；completion_rate > 1 单元格附超成交标记」相反 ——
   「组合完成率」卡与异常表的 overfill 数据矛盾在网页被掩盖、在 HTML 报告被暴露，属**展示层
   掩盖数据矛盾的原缺陷复发（方向相反）**。现改为不封顶（与 HTML `_fmt_pct` 同口径），
   4 个调用点（组合完成率 / 完成率 / 路由参与率 / 订单参与率）同时受益，单测固化 `1.05 → 105.00%`。
3. **有意偏差显式声明**：把三处 web 与 HTML 的呈现细节差异（百分数取整、` · ` 分隔符、
   零成交金额 `$` 前缀）写入 `lib/report-format.ts` 注释，防止未来被单侧「修复」；
   第四处（scope 文案缺「（全报告统一口径）」后缀）改为对齐，因该后缀承载「全报告同口径」承诺。
4. **质量门报告入库策略**：`scripts/reports/quality_gate/report-*.md` 加入 `.gitignore`
   （生成物可再生；逐轮账本以 `known-limitations` §五 为准，避免双账本）。

**仍待处理（前端）**：异常明细表未渲染 HTML 侧既有的「超成交 / >100%」标记
（`overfill` / `order_par_gt100` 字段已具备；数值信号已由本节第 2 条恢复），已登记进
`docs/report-tca-known-limitations.md` §五待办。

### 10.4 异常规则边界与标签修订（2026-09-15 第五轮）

**背景**：`overfill_pct` 自 §2 起为 `above 100`（含边界），而 `AnomalyRoute.overfill`
布尔标记为严格 `fill > RouteShares`。两者在 100% 这个点上**语义不一致**：完成率恰为
100.0%（正常成交满，占大多数）的路由既会带着 `Overfill % 100.0%` 标签进入异常清单，
`overfill` 又为 `False` —— 标签语义与实际含义相反，属「数据质量探针误报」。
另：该规则标签自带 `%`，渲染层再补单位后缀，输出为 `Overfill % 100.0%`（双 `%`）。

**决策**：

1. **新增 `above-strict` 模式**（严格大于，边界值不算越界）：`_VALID_MODES` 与前端
   `ThresholdMode` 同步扩展，`_evaluate_rule` / `evaluateThreshold` 经同一「越界判定」
   分支处理，不写第二份比较逻辑；Configure 的模式下拉新增 `Above (strict)`
   （模式仍是用户可改的公开契约，改回 `above` 即恢复含边界语义，属显式选择）。
2. **`overfill_pct` 改用 `above-strict`**（warning 100 / critical 110 不变）：完成率恰为
   100.0% 不再入清单，其命中与 `AnomalyRoute.overfill` 布尔标记**同界**；
   `fill > RouteShares` 的轻微超成交（如 100.1%）仍照旧捕获，临界档位不变。
3. **标签 `Overfill %` → `Overfill`**：`%` 由渲染层的单位后缀统一补，消除双 `%`。
   后端 `_RULE_LABELS` 与前端 `DEFAULT_RULES` 两处同改（后端为阈值真相源，前端保留
   本地标签，故必须同步）。

**影响面**：异常清单条数下降（此前被误报的「成交满」路由退出），是**收敛性**变更；
`order_par_gt100` 的边界与其余规则标签由 §10.5 同批收敛。

**护栏**：后端 `TestOverfillRule.test_exact_full_fill_not_flagged`（100% 不命中）+
`test_overfill_flagged_and_hits` 的标签断言；前端 `thresholds.test.ts`
「treats overfill boundary as exclusive」锁定标签、模式与四个边界取值。

### 10.5 订单参与率边界与规则标签归一（2026-09-15 第六轮）

**背景**：§10.4 只收敛了 `overfill_pct`，留下两类同源问题：

1. **`order_par_gt100` 边界与同源实现不一致**：规则为 `above 100`（含边界），而
   `AnomalyRoute.order_par_gt100` 布尔标记（`order_par_rate > 1.0`）与覆盖率一致性探针
   （`metric_coverage` 的 `par_sum > 1.0`，产出 `order_par_consistency_pct` 供报告头展示）
   均为**严格大于** —— 求和恰为 100.0% 的路由「进异常清单但不进数据质量计数」，
   同一份报告内三处口径不可对账。
2. **其余规则标签仍自带单位符号**：`Pnl VWAP bps`、`Fill %`、`Vol % ADV20`、
   `Vol % Interval`、`Order Par >100%` 与渲染层的单位后缀叠加，输出
   `Fill % 42.0%`、`Pnl VWAP bps 15.2 bps`、`Order Par >100% 250.0%`。

**决策**：

1. **`order_par_gt100` 改用 `above-strict`**（warning 100 / critical 200 不变）：与布尔标记、
   一致性探针同界，`data_quality.order_par_gt100_count` 与异常命中数自此可对账。
2. **标签一律不含单位符号**，单位由 `_RULE_UNITS` 后缀统一补（`_RULE_LABELS` 与前端
   `DEFAULT_RULES` 同改）：

   | 规则键 | 旧标签 | 新标签 | 渲染结果示例 |
   |---|---|---|---|
   | `pnl_vwap_bps` | `Pnl VWAP bps` | `Pnl VWAP` | `Pnl VWAP 15.2 bps` |
   | `fill_pct` | `Fill %` | `Fill Rate` | `Fill Rate 42.0%` |
   | `volume_pct_adv20` | `Vol % ADV20` | `ADV20 Participation` | `ADV20 Participation 12.3%` |
   | `volume_pct_interval` | `Vol % Interval` | `Interval Participation` | `Interval Participation 21.5%` |
   | `order_par_gt100` | `Order Par >100%` | `Order Par` | `Order Par 250.0%` |
   | `overfill_pct` | `Overfill %` | `Overfill`（§10.4） | `Overfill 103.5%` |

   命名沿用规则既有描述中的词汇（`Fill Rate` / `Participation`）；异常明细表头与其他视图的
   列名不改动 —— 列名是「指标名」而非「命中规则标签」，不追加单位后缀，无重复问题。
3. **前端本地配置以代码为准刷新展示元数据**：`loadCostViewConfig` 用当前默认值覆盖
   `label` / `description` / `decimals` / `unit`，仅保留用户可编辑的 `mode` / `warning` /
   `critical` / `enabled`。否则历史 localStorage 会把旧标签长期钉住（后端已改而网页仍显示
   `Fill %`），同时兜住「旧版本只存了部分字段」的规则对象。
4. **Configure 预览样例同步**：`Tracking Error 6.0 bps`（014 规则键重命名前的旧标签）改为
   `Pnl VWAP 6.0 bps`，与另两条样例一起对齐新标签。
5. **存量配置的一次性模式迁移（2026-09-15 补记）**：本 ADR 合入后，老用户 localStorage 中仍保存
   `overfill_pct: { mode: 'above' }` —— 那是**当时的代码默认值**而非用户显式选择，且会随
   `thresholds` payload 每次查询下发、覆盖后端新默认（`ThresholdRules.from_payload` 以 payload
   为准），表现为「后端已修、完成率 100% 的路由仍带 Overfill 标签」。修复：配置引入
   `ruleSchemaVersion`（当前 2）；读取时仅当存储 mode 仍等于旧默认（`above`）时迁移为当前默认
   （`above-strict`），用户显式选择的其他 mode 不动；版本号随保存写回，迁移只执行一次，
   此后用户改回 `above` 属显式选择、不再被覆盖。

**影响面**：异常清单条数小幅下降（恰好 100% 订单参与率的路由退出）；标签与本地配置刷新均为
展示层变更，不动报告数值口径。

**护栏**：后端 `TestOrderParAggregation.test_exact_full_order_par_not_flagged`（100% 不命中）+
`TestRuleLabels.test_rendered_hit_has_single_unit_symbol`（逐规则断言渲染后单位符号只出现
一次，任一规则把单位写回标签即失败）；前端 `thresholds.test.ts`
「keeps unit symbols out of rule labels」与 `storage.test.ts`（展示元数据刷新 / 部分字段兜底 /
stale mode 一次性迁移三条用例）。

**有意未改**：`volume_pct_adv20` / `volume_pct_interval` / `intraday_volatility` /
`price_movement_pct` 仍为 `above`（含边界）—— 其阈值是「参与率 / 波动进入观察区间」的业务
阈值，边界相等不构成数据矛盾，严格化只会无理由缩小清单。

### 10.6 聚合粒度与期间键（2026-09-21，026 阶段一）

**背景**：报告的时间维度此前只有「查询窗口」没有「聚合粒度」—— `TimeRange` 仅承载
`start/end/preset`，所有按时间分组都锚在 `order_as_of_date` 日粒度
（`report_aggregator` 的走势与分市场金额趋势、`metric_coverage` 的分组列），
无法按周观察执行质量，也没有周度 rollup。

**决策**：

1. **粒度参数**：为报告装配与覆盖率服务引入 `granularity`（`day` / `week` / `month`，
   默认 `day`），经 API Query 暴露（`report-summary` / `metric-coverage` / `export-html`），
   并纳入报告 `filters.granularity` 与缓存 key（不同粒度各自缓存，互不串味）。
2. **`day` 为恒等映射**：`day` 粒度下期间键**直接返回原始列**
   （`report_measure.period_key_expr("day") == "order_as_of_date"`），不经任何日期函数转换，
   保证既有按日产出逐字节不变。
3. **周键为 ISO 8601 的纯 SQL 算术实现**：本环境 SQLite **3.45.3 不支持** `%G` / `%V`
   （返回 NULL），而 `%Y-%W` 会把跨年周拆成 `2025-52` / `2026-00` 两个键 —— 故改用算术实现：
   当周周一 = `date(d, '-6 days', 'weekday 1')`；ISO 周年份 = 该周周四所在年份
   （`strftime('%Y', monday, '+3 days')`）；周号 = `(julianday(monday) − julianday(w01_monday))/7 + 1`。
   实测：边界日期 73 个 + 真实库 194 个 distinct 交易日对照 `date.isocalendar()` **零不一致**。
4. **期间序列不补零**：延续 §8「按日走势不补零」的既有理由（0 在成本指标上表示「成本为零」，
   把无数据期间补 0 属数据失真），周 / 月粒度同样只含有数据的期间，并由 `daily_series_meta`
   披露覆盖期间数与粒度。
5. **口径单点**：期间键 SQL 与粒度映射只允许一处定义（`report_measure`），由走势 / 分市场金额
   趋势 / 覆盖率共用；`granularity=week` 下的「分市场金额趋势」即「分市场 × 周度」交叉视图，
   **不另造查询**。

**版本**：`SPEC_VERSION` `2026.09.5` → `2026.09.6`；`report_spec` 新增 `granularities` /
`default_granularity` / `week_key_mode` / `period_series_no_fill` 并由脚注展示
（`_granularity_footer_clause`）。

**影响面**：新增参数默认 `day`，既有调用方零改动，`day` 粒度下报告数值不变；
payload 为**追加式**变更（`filters.granularity`、`daily_series_meta.granularity`、
`metric_coverage.granularity`），旧消费者忽略未知键即可。

**护栏**：`CostView/tests/test_report_metrics.py::TestGranularityPeriodKeys`（10 条：
跨年周归属 / 空周不补零 / 单日周 / 月键格式 / 分市场 × 周度金额守恒 / day 键恒等 /
非法粒度报错 / 覆盖率粒度分组 / SPEC-实现绑定 / 脚注声明）。

### 10.7 执行环境 cohort 精确化（2026-09-21，026 阶段二）

**背景**：三个环境 cohort 此前均为**代理口径**（`tca_utils.cohort_key_and_label`）：
`time_of_day` 恒 `unknown`（活跃表不带 `start_time`，该维度完全失效）、
`liquidity_adv20` 用 `par_rate`（区间参与率）代 ADV 占比、`volatility` 用 `|pnl_vwap|`
（**成本**）代日波动率 —— 最后一项用成本代理环境变量、再按它分层比较成本，属**循环论证**。

**决策**：

1. **新增环境上下文派生单点** `CostView/src/monitoring/env_context.py`：从
   `fill_bdib.mkt_timestamp`（按路由取最早成交时刻）与 `raw_bdib` 的 `bdib_daily_summary`
   （`adv_20d` / `daily_volatility`，**已内置无需计算**）取数，在应用层按
   `(ticker, 交易日)` join。跨库**不使用 SQL `ATTACH`**（会引入第二数据文件依赖、
   破坏连接单点）。
2. **注入方式**（plan §4.2 DP-2-4）：`cohort_key_and_label(route, cohort, env=None)` 与
   `aggregate_cohorts(..., env_by_route=None)` 增设**可选**参数 —— 不触碰
   `TcaRouteSummary` 的「严格匹配 55 字段」契约，且 `env=None` 与「字段为 `None`」等价，
   **参数默认值天然构成降级路径**，无需额外开关。
3. **三级降级链**：L1 真实 / L2 自给 / L3 代理；任一维度不可得均为**可见事实** ——
   可得率经 `scorecard.filters.env_coverage` 披露（延续「降级必须可见」的既有原则）。
4. **仅环境 cohort 取数**：`build_scorecard` 按 cohort 判定，非环境 cohort **零额外查询**。
5. **两处口径变更**：`liquidity_adv20` 由 `par_rate` 改为 `fill / adv_20d`（语义修正，
   两者不可互换）；`volatility` 由 `|pnl_vwap|` 改为真实 `daily_volatility`。

**版本**：`SPEC_VERSION` `2026.09.6` → `2026.09.7`；`report_spec` 新增 `env_cohort_sources` /
`env_cohort_fallbacks` / `env_coverage_disclosure`（与 `env_context.ENV_DIMENSIONS`
由测试断言一致）。

**实测依据**（Checkpoint 2-A）：`fill_bdib.mkt_timestamp` 与 `raw_bdib.mkt_timestamp` 均为
8 字符 `HH:MM:SS` 纯时间（原判「两套值域并存」**不成立**，`bucket_time_of_day` 现有解析
可直接工作）；start_time 可得率 **100%**；`adv_20d` 覆盖 **99.39%**、`daily_volatility`
**99.94%**（`intraday_volatility` 仅 38.7%，故不作主口径）。

**影响面**：环境 cohort 的**分层结果会变化**（此前 `time_of_day` 全落 `unknown`），
跨期比较该维度时需注意口径切换；非环境 cohort 与报告 HTML / 监控页**零影响**。

**护栏**：`CostView/tests/test_env_context.py`（16 条：双形态归一化 / 真实分桶与边界 /
代理回退 / 真实路径不引用成本量 / 三维度独立降级 / 来源缺失不抛错 / 聚合接线 /
可得率披露 / SPEC 绑定）。

### 10.8 科学方法评估层（2026-09-21，026 阶段三）

**背景**：报告口径层直到 §10.7 都在做「描述得更准确」，但**比较本身**仍是原始均值排序 ——
没有统计推断、没有可比性控制。ADR-0004 规划的 `CostView/src/evaluation/` 目录从未落地。

**决策**：新建 `CostView/src/evaluation/`（5 个模块），并把两条方法学约束做成**结构性不可绕过**：

1. **可比性由服务端强制**（DP-3-2）：`assess_comparability` 输出 `ComparabilityVerdict`；
   不可比时调用方**不得**输出比较数值。分层键取 `(Exchange, asset_class, time_of_day,
   liquidity_adv20, volatility)` —— 后三者来自 §10.7 的真实环境变量；**禁止**用成本量作分层键。
   失衡度量用**总变差距离**（TVD）而非卡方：TVD 对期望频数无下限要求（小样本稳定），
   且可直接解读为「概率质量不重叠比例」。环境维度取值**复用 `tca_utils` 分桶单点**，不重复实现。
2. **基准不可默认**（DP-3-3，依据 D1）：`evaluation_metadata(benchmark=…)` 无默认值，缺失即报错。

**模块与依据**：`comparability`（B3）、`stats_tests`（`Algo_TCA.md:726-793` 的 χ²/KS 规格 +
bootstrap 区间 + 多重比较校正）、`power`（正态近似闭式，不引入 statsmodels）、
`cost_model`（`Algo_TCA.md:116` 幂律非线性回归估计；域外不外推、不作事前预测）、
`governance`（B4 治理层）。

**依赖**：新增 `scipy>=1.11`（DP-3-1）；`CostView/api/requirements.txt` 只加注释指向
`pyproject.toml`，避免两处漂移。

**包依赖方向**：`evaluation → monitoring.env_context / tca_utils`（单向）。
`report_spec` **刻意不 import** `evaluation`（否则构成
`evaluation → monitoring.env_context → monitoring/__init__ → report_spec` 的包级循环），
故 `REPORT_SPEC["evaluation"]` 为字面量，由 `tests/test_evaluation.py::TestSpecBinding` 断言一致。

**版本**：`SPEC_VERSION` `2026.09.7` → `2026.09.8`。

**影响面**：纯新增模块，既有报告 / 监控 / 记分卡产出**零变化**（端点接入见后续批次）。

**护栏**：`CostView/tests/test_evaluation.py`（34 条）。

### 10.9 评估层端点接入与门控（2026-09-21，026 阶段三收尾）

**背景**：§10.8 交付了评估层模块，但**没有可调用入口** —— DP-3-2「可比性由服务端强制」
因此没有落点（模块只能被测试调用，用户侧仍只能看原始均值排序）。

**决策**：

1. **新端点** `POST /api/tca/evaluation/compare`：服务端执行可比性判定，
   不可比时 `verdict.comparable=False` 且 `comparisons` 为空数组，**不返回比较数值**。
2. **基准必填**（DP-3-3 / D1）：`benchmark` 为 pydantic 必填字段，缺失即 422；
   基准 → 指标列映射为封闭集合 `BENCHMARK_METRICS`（`vwap` / `arrival` / `close` / `is`），
   新增基准必须显式登记。
3. **门控 `TCA_EVAL_ENABLED`**（默认开启，形态对齐 `TCA_ORDER_AGG_ENABLED`）：
   关闭时返回**显式不可用**，**不**回退到未校验的均值比较 —— 回退到未校验比较等于
   放弃可比性约束，与关闭意图相反。
4. **能力位**：`GET /api/tca/capabilities` 新增 `evaluation`。
5. **取数复用**：抽出 `TcaQueryService._collect_routes`，scorecard 与评估层共用同一取数范式
   （原先内联在 `build_scorecard`，避免两处分页循环漂移）。

**版本**：`SPEC_VERSION` **不变**（`2026.09.8`）—— 本轮是**接入**，口径本身未变。

**影响面**：纯新增端点与新增模块；既有 Report / Monitoring / Scorecard 产出与行为零变化
（`_collect_routes` 抽取为等价重构，由既有 291 条测试守护）。

**护栏**：`CostView/tests/test_evaluation.py`（`TestEvaluationComparisonOrchestration` 8 条 +
`TestEvaluationRequestModel` 3 条）。

### 10.10 综合评估报告（027：形态与可比性修正，2026-09-21）

**背景**：§10.8 / §10.9 的评估形态是「用户选择维度 / 基准 / 方法」，与「按时间范围自动
产出的综合评估」需求不符；且可比性门禁在真实数据上恒为拒绝（`Exchange` TVD 恒等于 1.0，
5 维交叉后 `common_strata = 0`）。

**决策**：

1. **无可选项**：遍历 `SCORECARD_COHORTS` 全部七个维度；基准（`arrival` / `vwap` /
   `close` / `is`）与方法（t / KS / χ²）**全部并列**；检验固定在主基准 `arrival`
   （三个基准各做一遍会使结果膨胀 3 倍，无益于可读性）。
2. **比较形态**：每组 vs 其余（**层内加权合并**），而非 C(n,2) 全组合 ——
   26 个券商的 325 对检验对报告无可读性。
3. **控制维度**：`Exchange` + `time_of_day` / `liquidity_adv20` / `volatility`；
   **不含 `asset_class`**（与 Exchange 共线，纳入只使层更稀疏）；分层键**排除当前
   分组维度**（必须正交，否则层内取值恒定、分层退化为 1 层）。
4. **可比性**：TVD 降为**描述性提示**（`imbalance_alert_threshold = 0.2`），**不阻断**
   输出；可信度以 `confidence` / `coverage` 披露。026 的
   `comparability_enforced_server_side = True` 改为 `False`。
5. **端点**：`POST /api/tca/evaluation/report`（仅接受 `filters` + `granularity`）；
   `POST /api/tca/evaluation/compare` **移除**（该形态的载体）。
6. **报告内嵌**：`report["evaluation"]` 与独立端点消费**同一编排函数**的同一份
   payload；评估失败不阻断报告生成。

**版本**：`SPEC_VERSION` `2026.09.9`。

**影响面**：评估层为纯新增 + 形态重写；既有 Report / Monitoring 数值口径不变
（`granularity=day` 产出仍与改动前逐字节等价）。

**护栏**：`CostView/tests/test_evaluation.py`（`TestStrataDescription` / `TestStratified` /
`TestEvaluationReportOrchestration` / `TestEvaluationEndpoint` / `TestEvaluationReportSection`）；
`TestSpecBinding` 断言 `report_spec` 声明与实现常量一致。

### 10.11 波动率量纲统一与分桶阈值修正（028，2026-09-21）

**背景**：`tca_utils.bucket_volatility` 的阈值（1.5/3.5）是日波动率空间，而
`bdib_daily_summary.daily_volatility` 实为**年化百分比**（反推公式 =
std(日对数收益率) × √252 × 100，实测中位 26.075）→ 82.9% 落 `stressed`、`typical`
仅 0.61%，维度失效。且上游在 202603/202604 区间写入**年化小数**（同标的跨时段跳变
≈ 100 倍后恢复），列内量纲不统一。

**决策**：

1. `bucket_volatility` 阈值对齐**年化空间**（25 / 40，与 `market.py:50-51` 解读同一列的
   既有口径一致），标签同步（`<25% ann.` 等）；
2. 量纲统一在**数据入口单点**：`env_context.normalize_volatility_to_percent`
   （界值 `VOLATILITY_SCALE_CUT = 3.0` —— 正常年化百分比 ≥ 5、正常年化小数 ≤ 2，
   中间为空档）；命中数经 `env_coverage.volatility_scale_fixed` 披露，**不得静默修数**；
3. `RouteEnvContext` 新增 `volatility_normalized` 标志；
4. 上游 202603/202604 的量纲不一致登记为**跨仓项**，本侧归一化为过渡措施。

**版本**：`2026.09.10`。

**护栏**：`test_env_context.TestVolatilityScaleNormalization`（归一化判别 / 界值与 spec 一致 /
命中披露）与 `TestSpecBinding`（`volatility_scale_cut` / `volatility_unit` 与实现常量一致）。
证据全文见 `docs/archive/2026-09-21/028-volatility-scale-fix/research.md`。

## 后果 (Consequences)

### 正面

- 报告口径自洽可校：加权成本可由总成交金额反推；数据矛盾进入异常清单与质量提示区。
- 严重度可分级处置；截断样本无偏且有全量导出，满足离线审计。
- 口径脚注与实现同源，消除文档-实现漂移；归档报告可自证报告期与口径版本。

### 负面 / 取舍

- **破坏性变更**：加权口径切换使报告数值与历史报告不可比（本决策明确不保留旧口径对比值）。
- 前端需同步：`ThresholdRule` 恢复 `warning` / `critical` 并新增两条规则键。
- 异常清单条数可能上升（overfill 与订单参与率规则新纳入）。
- 规则键重命名为破坏性变更，前后端需同步升级；已提供旧 payload 与旧 localStorage 配置的兼容层，但第三方直连 API 的消费者若硬编码旧键需自行迁移。
- **（2026-09-15 P0）报告数值随作用域收窄而变化**：白名单外市场不再进入 KPI / 走势 / 排行 /
  市场概览 / 异常明细（此前仅覆盖率剔除），与旧版本报告数值不可直接比较；需要纳入时应显式传
  `exchange`，此时报告头会告警该市场 DBIB 依赖指标必然为 NULL。
- **（2026-09-15 P0）异常清单条数进一步上升**：严重未完成（`fill_pct` critical，含零成交）路由
  豁免笔数 / 金额下限；同时多选过滤修复后，此前「意外为空」的筛选组合会恢复出明细。
- **（2026-09-15 P0）payload 为追加式变更**：新增 `weight_coverage`、`filters.scope`、
  `metric_coverage.scope`、`extra_kpis.zero_fill_routes` / `zero_fill_notional_usd` /
  `unfilled_notional_unpriced_routes`，旧消费者只需忽略未知键。

### 对其他 ADR 的影响

- 修订: [ADR-0015](0015-anomaly-route-filter.md)（阈值单档化 → 恢复两档严重度；入清单覆盖范围不变）
- 引用: [ADR-0011](0011-fx-rate-handling-rules.md)（fx 兜底顺序）
- 引用: [ADR-0004](0004-costview-focused-on-evaluation.md)（CostView 聚焦评估）
- 被引用: 未来调整报告指标口径需同步 `report_spec.py` 与本 ADR

## 备选方案 (Considered Alternatives)

- **双口径并出、默认保持旧口径**：否决。用户决策为直接切换新口径，代码最简；旧口径对比值不保留。
- **保留 ADR-0015 单档 + 仅展示数值**：否决。数值化无法支撑分级处置（容忍 vs 立即停单）。
- **异常明细一次性全量内嵌 HTML**：否决。报告体积曾达 5MB+，改为渲染截断 + CSV 导出。
- **健康度继续以 round 后覆盖率分级**：否决。浮点精度可把 99.995% 误判为 ok。
- **（2026-09-15）保留全量 KPI + 并列「白名单内」对照卡**：否决。把口径选择推给读者，且异常明细
  与覆盖率的对齐问题未解决；改为默认白名单 + 用户口径显式切换 + 报告头告警。
- **（2026-09-15）零成交路由按原缺口口径补 0**：否决。补 0 会把「无价格可估」伪装成
  「无机会成本」，与「不补零」原则冲突；改为价格回退链 + 未计价条数披露。
- **（2026-09-15）旧 schema 缺 `fill_count` 列时抛错**：否决。旧库应仍可导出报告，
  故取 fail-open + 日志告警（不静默清空清单），而非中断导出。

## 实施注意事项 (Implementation Notes)

- 涉及的关键文件:
  - `CostView/src/monitoring/report_measure.py`（新增：口径实现唯一来源 —— 作用域 / 加权与覆盖 /
    订单级聚合 / 金额回退与零成交；2026-09-15 P0。2026-09-21 增补：聚合粒度与期间键 ——
    `GRANULARITIES` / `DEFAULT_GRANULARITY` / `period_key_expr` / `iso_week_expr` / `month_expr`）
  - `CostView/src/monitoring/report_aggregator.py`（加权口径、组合完成率、未成交金额、样本量 meta、跨日披露、fx 质量、作用域与权重覆盖；2026-09-21 增：`granularity` 透传与走势 / 分市场趋势按期间分组）
  - `CostView/src/monitoring/anomaly_query.py`（两档阈值、severity、排序与 limit、overfill / order_par 规则、CSV 导出）
  - `CostView/src/monitoring/metric_coverage.py`（SLA 双口径、整体覆盖率、一致性探针、NULL 原因一致性；2026-09-21 增：粒度分组与 payload 回显）
  - `CostView/src/monitoring/bdib_health.py`（精确分级、金额权重、三态降级）
  - `CostView/src/monitoring/tca_report_html.py`（严重度配色、截断与导出提示、覆盖率双口径、样本量、脚注）
  - `CostView/src/monitoring/time_range.py`（as_of_date）
  - `CostView/src/monitoring/report_spec.py`（新增：口径唯一真相源）
  - `CostView/src/monitoring/__init__.py`（导出契约：清理幽灵导出、导出 scope API；2026-09-15；2026-09-21 增：导出 `GRANULARITIES` / `DEFAULT_GRANULARITY`）
  - `scripts/reports/generate_tca_report.py`（as_of 透传、CSV 落盘、健康扫描作用域透传）
  - `CostView/api/routers/monitoring.py`（export-html 端点向健康扫描透传作用域；2026-09-21 增：`granularity` Query 透传与缓存 key 纳入，覆盖 report-summary / metric-coverage / export-html 三端点）
  - `scripts/quality_gate/run.py`（补 `__main__` 守卫，使 `python -m` 形式不再空跑）
  - 前端 `frontend/src/modules/costview/`（两档阈值、严重度展示、口径与样本标注）
- 配套测试:
  - `CostView/tests/test_report_metrics.py`（新增：逐缺陷针对性断言）
  - `CostView/tests/test_monitoring.py`（口径断言同步更新）
  - `CostView/tests/test_golden_samples.py`（指标锁定回归；改用仓库内置冻结快照，SOP 见 `CostView/tests/golden/README.md`）
- 验证记录（2026-09-11）:
  - 后端 `CostView/tests/` → 170 passed, 0 skipped（含 golden）
  - 前端 `vitest run src/modules/costview` → 39 passed；`tsc --noEmit` 通过
  - golden 回归：冻结快照 4668 行与基线 `total_routes` 一致，锁定 200 条路由 × 18 项指标全部落在容差内
  - 结论：本次口径变更仅作用于报告聚合 / 渲染层，**订单级指标计算链路零漂移**
- 验证记录（2026-09-15，P0 修订）:
  - 后端 `CostView/tests/` → 182 passed, 0 skipped（含 golden；新增 11 条护栏）
  - 新增护栏分布：作用域统一（3）、加权覆盖披露（2）、零成交可见性（4）、
    过滤与订单级口径一致性（2）+ 口径声明-实现一致性（1）
  - 破坏面：`test_monitoring.test_kpi_notional_usd_minor_unit` 的夹具使用了白名单外市场代码
    `IT`（意大利 Bloomberg 代码应为 `IM`），作用域统一后该路由不再计入 KPI；已修正夹具代码
  - 结论：变更集中在报告聚合 / 口径层，golden 快照零漂移（订单级指标计算链路未触碰）
- 验证记录（2026-09-15，复核整改第二轮）:
  - 后端 `CostView/tests/` → **191 passed**（+9：`TestPackageExports` 3、市场下拉白名单 1、
    健康扫描作用域 1、`TestReviewRemediation` 4）
  - `from CostView.src.monitoring import *` 复验通过（整改前抛 `AttributeError: DIM_COLUMNS`）
  - 质量门（平铺入口 `python scripts/quality_gate.py`）→ AP 违规 0 / OE 新增 0 / 存量 187
  - 未改口径数值：本轮仅修一致性与契约，报告数值与第一轮一致
- 验证记录（2026-09-15，第三轮：前端口径对齐）:
  - 前端 `npx vitest run src/modules/costview` → **49 passed**（7 文件；新增 `report-format.test.ts` 10 条）
  - 前端 `npx tsc --noEmit` → 通过
  - 后端 `CostView/tests` → 191 passed（未触碰）；质量门 AP 0 / OE 新增 0
  - 结论：本轮为展示层对齐，后端口径与数值零变化
- 验证记录（2026-09-15，第四轮：S2 收尾）:
  - 前端 `npx vitest run src/modules/costview` → **52 passed**（+3：`formatPct` 去封顶 1、
    ReportView 覆盖披露与去封顶集成 2）
  - 前端 `npx tsc --noEmit` → 通过
  - 后端 `CostView/tests` → 191 passed（未触碰）
  - 质量门 / 文档漂移审计 → AP 0 / OE 新增 0 / 存量持平；`[OK] No documentation drift detected.`
- 验证记录（2026-09-21，026 阶段一：聚合粒度与期间键）:
  - 后端 `CostView/tests/` → **230 passed**（+11：`TestGranularityPeriodKeys` 10 条 +
    `TestReportSpec` 粒度声明-实现绑定断言）
  - `day` 粒度等价：`period_key_expr("day")` 恒等返回原始列，既有 219 条用例零失败
  - 周键正确性：边界日期 73 个 + 真实库 194 个 distinct 交易日对照 `date.isocalendar()` 零不一致
  - golden 快照：订单级指标计算链路未触碰，零漂移
  - 结论：新增参数默认 `day`，既有报告数值与 payload 语义不变（payload 为追加式）
- CI 常态化: `.github/workflows/boundary.yml` 新增「Golden snapshot 回归」步骤（硬阻断）；
  快照随基线入库（`CostView/tests/golden/snapshot/`，`.gitignore` 显式例外），
  CI 无需生产数据即可执行
- 回滚策略: 加权口径与严重度属破坏性变更，回滚需同步前后端与测试，不建议局部回滚。
