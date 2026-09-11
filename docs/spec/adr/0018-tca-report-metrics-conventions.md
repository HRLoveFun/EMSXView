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

- 新增异常规则 `overfill_pct`（above 100）与 `order_par_gt100`（above 100），数据矛盾不再被静默放过。
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

- 该规则实为 `|pnl_vwap|` 阈值，原名易与「跟踪误差」混淆；展示标签同步改为 `Pnl VWAP bps`。
- **旧键迁移（双向兼容）**：
  - 后端 `anomaly_query._normalize_rule_keys` 接受旧 payload 键并映射为新键（新旧同时出现时新键胜出，不静默丢配置）；
  - 前端 `lib/storage.migrateRuleKeys` 在读取 localStorage 时把旧键配置迁移为新键。
- 迁移由测试护栏守住：`test_report_metrics` 的 `test_legacy_rule_key_migrated`、`storage.test.ts`（两条）与 `thresholds.test.ts` 的兼容用例。

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

## 实施注意事项 (Implementation Notes)

- 涉及的关键文件:
  - `CostView/src/monitoring/report_aggregator.py`（加权口径、组合完成率、未成交金额、样本量 meta、跨日披露、fx 质量）
  - `CostView/src/monitoring/anomaly_query.py`（两档阈值、severity、排序与 limit、overfill / order_par 规则、CSV 导出）
  - `CostView/src/monitoring/metric_coverage.py`（SLA 双口径、整体覆盖率、一致性探针、NULL 原因一致性）
  - `CostView/src/monitoring/bdib_health.py`（精确分级、金额权重、三态降级）
  - `CostView/src/monitoring/tca_report_html.py`（严重度配色、截断与导出提示、覆盖率双口径、样本量、脚注）
  - `CostView/src/monitoring/time_range.py`（as_of_date）
  - `CostView/src/monitoring/report_spec.py`（新增：口径唯一真相源）
  - `scripts/reports/generate_tca_report.py`（as_of 透传、CSV 落盘）
  - 前端 `frontend/src/modules/costview/`（两档阈值、严重度展示、口径与样本标注）
- 配套测试:
  - `CostView/tests/test_report_metrics.py`（新增：逐缺陷针对性断言）
  - `CostView/tests/test_monitoring.py`（口径断言同步更新）
- 回滚策略: 加权口径与严重度属破坏性变更，回滚需同步前后端与测试，不建议局部回滚。
