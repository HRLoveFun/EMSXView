# ADR-0015: 异常路由（Anomaly Routes）筛选与阈值归并

> 状态: Accepted
> 日期: 2026-08-28
> 标签: costview, analytics, frontend, backend

## 背景 (Context)

CostView 报告（Report / Monitoring）中的「异常路由」清单用于把算法执行偏离度超过阈值的路由挑出来供盘后复盘。原设计存在三处待优化：

1. **阈值分档冗余**：每条指标（tracking error / fill % / vol % ADV20）同时配置 Warning 与 Critical 两档阈值，但实际只用 Warning 档判定是否进入异常清单，Critical 档从未参与筛选，反而给用户造成「两档各自生效」的误解。
2. **缺少样本噪声与规模过滤**：低填充笔数的路由（如试探单、拆单残留）与低成交金额（USD）的路由混入异常清单，噪声大、复盘价值低，且无法按成交规模收敛关注范围。
3. **表格可读性问题**：异常表格带「严重度」列，但因已归并单档阈值，「严重度」失去区分意义；用户更关心「具体超了多少」而非等级标签。

上述问题在 2026-08 的 CostView-Report / CostView-Configue 优化中落地，本 ADR 固化其设计决策。

## 决策 (Decision)

### 1. 阈值单档化
- 每条指标仅保留**单个阈值 `threshold`**（原 `warning` 值）。越阈即判为异常（`evaluateThreshold` 返回 `critical` / `normal` / `none`）。
- 前端 `ThresholdRule` 与后端 `DEFAULT_THRESHOLDS` 均由 `{warning, critical}` 合并为 `{threshold}`。
- 合并时取原 `warning` 边界，**不改变现有异常清单的覆盖范围**（仅去除无效的 Critical 档）。

### 2. 两道筛选闸门（filter gates）
异常清单在「阈值命中」之后、渲染之前，再经过两道可配置过滤：

| 参数 | 默认 | 生效范围 | 语义 |
|---|---|---|---|
| `min_fill_count` | 10 | 仅 `algo <> "close"` | 填充笔数低于下限的路由视为样本噪声，不计入异常清单 |
| `min_notional_usd` | 10000 | 全部路由 | 无法换算 USD（FX 缺失）或成交金额(USD)低于下限的路由不计入异常清单 |

- `algo = "close"` 不受 `min_fill_count` 限制（收盘单通常笔数少但必须保留）。
- 两参数均为 0 时表示「关闭该闸门」；`min_notional_usd = 0` 同时允许无法换算 USD 的路由通过。
- 参数由 Configure 面板「Anomaly Route Filters」卡片配置，经 `report-summary` 与 `export-html` 端点下发到 `build_report` → `query_anomaly_routes`。

### 3. 表格与 KPI 呈现
- 移除异常表格「严重度」列与 `AnomalyRoute.severity` 字段。
- 「命中规则」列移至第一列，并在标签后输出**具体超限数值**（如 `Vol % ADV20 15.0%`、`Tracking Error 30.0 bps`）；单位由后端 `_RULE_UNITS` 统一给出（`bps` / `percent`）。
- KPI 副标题由 `critical N` 改为 `见下方明细`（异常条数在主卡直接展示）。

## 后果 (Consequences)

### 正面
- 配置模型与展示对齐：单档阈值 + 两道显式过滤，用户心智模型一致。
- 噪声收敛：低笔数 / 低金额路由默认被过滤，异常清单聚焦高价值复盘对象。
- 表格信息密度提升：首列即「超了多少」，无需再映射到等级。

### 负面 / 取舍
- `min_notional_usd` 依赖 `tca_route_summary.fx_rate` 或 `fill_bdib` 汇率；历史未回填 `fx_rate` 的日期（见 AGENTS.md 007 遗留）在默认下限下会被排除——这是预期行为（无法确认达标的金额不计入）。
- 移除 `critical` 档后，前端其余视图（Overview / Analysis / Scorecard 的 `getHighestOrderSeverity` / `countAlertOrders`）仍保留 `'critical'` 着色逻辑，与异常表格的单档语义并存，二者不冲突（订单级仍可有严重度分层）。

### 对其他 ADR 的影响
- 引用: [ADR-0004](0004-costview-focused-on-evaluation.md)（聚焦评估，异常路由属评估产出）
- 引用: [ADR-0011](0011-fx-rate-handling-rules.md)（USD 换算依赖 FX 规则）
- 被引用: 未来若调整异常路由口径，需同步本 ADR

## 备选方案 (Considered Alternatives)

- **保留 Warning/Critical 双档，Critical 作为二次排序权重**：未采纳。双档从未作用于筛选，仅增加配置负担；单档 + 数值展示已覆盖「超多少」信息。
- **仅按 `fill_count` 单维过滤，不引入 `min_notional_usd`**：未采纳。用户明确需要按成交金额(USD)收敛规模，且 FX 规则（ADR-0011）已能支撑换算。
- **在异常表格保留「严重度」列并标 normal/warning/critical**：未采纳。单档阈值下等级失去区分度，数值化呈现更直接。

## 实施注意事项 (Implementation Notes)

- 涉及的关键文件:
  - 后端: `CostView/src/monitoring/anomaly_query.py`（`DEFAULT_THRESHOLDS` 单档、`_RULE_UNITS`、`query_anomaly_routes` 两道过滤、`AnomalyRoute` 去 `severity`）
  - 后端: `CostView/src/monitoring/report_aggregator.py`（`build_report` 增加 `min_fill_count` / `min_notional_usd`）
  - 后端: `CostView/api/routers/monitoring.py`（`report-summary` / `export-html` 端点透传两参数）
  - 后端: `CostView/src/monitoring/tca_report_html.py`（KPI 副标题、异常表去严重度列 + 命中规则前移 + 数值化）
  - 前端: `frontend/src/modules/costview/types.ts`（`ThresholdRule` 单档、`CostViewConfig` 加 `minFillCount` / `minNotionalUsd`）
  - 前端: `frontend/src/modules/costview/lib/thresholds.ts`（`DEFAULT_RULES` 单档、`createDefaultCostViewConfig` 默认 `minFillCount:10` / `minNotionalUsd:10000`）
  - 前端: `frontend/src/modules/costview/components/ConfigureView.tsx`（Anomaly Route Filters 卡片，全英文）
  - 前端: `frontend/src/modules/costview/components/report/AnomalyTable.tsx`（去严重度列、命中规则首列、数值化）
  - 前端: `frontend/src/modules/costview/components/ReportView.tsx` + `services/api.ts`（`buildQuery` 透传两参数）
- 配套测试:
  - 后端 `CostView/tests/test_monitoring.py`：`test_anomaly_routes_detected`、`test_anomaly_min_fill_count_excludes_low_fill`、`test_anomaly_min_fill_count_skips_close_algo`、`test_anomaly_notional_usd_missing_fx`、`test_anomaly_min_notional_usd_excludes_low_value`（新增，验证 `min_notional_usd` 对全部路由生效）。
  - 阈值测试以 `min_fill_count=0, min_notional_usd=0` 解耦默认下限（测试基数据 `fill_bdib_db` 无 `fx_rate` 列，`notional_usd` 恒为 NULL）。
  - 前端 `thresholds.test.ts` / `monitoring-view.test.tsx` 已随单档阈值与默认配置同步更新。
- 回滚策略: 阈值单档化与字段移除为破坏性变更；若需回退，需同步回退前后端类型与测试，不建议局部回滚。
