# 实施计划: CostView TCA 核心指标补全

**Branch**: `003-tca-core-benchmarks` | **Date**: 2026-08-14 | **状态**: 已完成（2026-08-19，已合并至 `tca` 分支）

**理论依据**: `docs/textbook/股票交易执行质量与交易成本分析（TCA）：跨时期学术研究综述与方法框架.md`（模块 B/D）+ `docs/textbook/Algo_TCA.md`（Kissell, 2014, *The Science of Algorithmic Trading and Portfolio Management*, Chapter 3）

**门控规范**: `docs/spec/plan-design-principles.md`（G0 数据零受损 / G1 三性齐备 / G2 全程防漂移 / G3 充分且必要）

---

## Summary

为 CostView 补齐论文模块 B2.1-B2.4 的核心 TCA 指标缺口：到达价/收盘价基准、实施短缺（IS）、Wagner IS 分解（延迟/交易/机会成本）、成本风险维度（标准差/P95/CVaR）、订单历时、暂时/永久市场冲击分解（4 恢复窗口含跨日次日收盘），以及 route→order 聚合视图/API。所有数据库变更遵循 G0 只增不改原则，采用项目表重建迁移模式；计算逻辑由 feature flag 门控分段上线。

## 已确认设计决策

1. **列合并时机**: Phase 0 + Phase 1 的 20 列一次表重建完成，计算逻辑分 Phase 分步实现
2. **flag 粒度**: `TCA_CORE_BENCHMARKS_ENABLED`（Phase 0）+ `TCA_RISK_IMPACT_ENABLED`（Phase 1）+ `TCA_ORDER_AGG_ENABLED`（order 聚合）
3. **order 聚合实现时点**: 本方案即实现 order 级视图/API（`tca_order_summary` VIEW + `build_order_report()` + 聚合端点）
4. **recovery 窗口**: 5min / 10min / 30min（当日）+ 次日收盘（跨日 `bdib_daily_summary` 下一交易日 `daily_close`）

## 统一技术原则（G0 数据零受损）

| # | 原则 | 落地 |
|---|------|------|
| R1 | 只增不改 | 表重建迁移只追加新列（现有 35 列原样复制，新列填 NULL），不修改/删除现有列 |
| R2 | 备份前置 | 迁移/重算前跑 `scripts/ops/snapshot_guard.py`（复制 DB + 记录清单到 JSON） |
| R3 | 迁移幂等 | `PRAGMA table_info` 检查列已存在即跳过；重复执行无副作用 |
| R4 | flag 门控 | 新列写入 + 计算 + API + 前端全部由 flag 控制，默认关闭，可即时回退 |
| R5 | 写入可重入 | `INSERT OR REPLACE` 保持现有语义，重算安全 |

## 迁移模式（对齐项目 `_migrate_*` 表重建先例）

```
BEGIN;
  DROP TABLE IF EXISTS tca_route_summary_new;
  CREATE TABLE tca_route_summary_new (35现有列 + 20新列, PK (OrderId,RouteId,order_as_of_date));
  INSERT INTO tca_route_summary_new (35现有列, 20新列=NULL)
    SELECT 35现有列, 20个NULL FROM tca_route_summary;
  DROP TABLE tca_route_summary;
  ALTER TABLE tca_route_summary_new RENAME TO tca_route_summary;
  重建 idx_trs_date, idx_trs_ticker;
COMMIT;
```

## 新列清单（20 列，一次表重建）

### Phase 0（5 列）
| 列名 | 类型 | 说明 |
|------|------|------|
| p_arrival | REAL | 到达价 P0（首笔成交前最近 bar close） |
| p_close | REAL | 收盘价 Pn（bdib_daily_summary.daily_close） |
| arrival_cost_bps | REAL | 到达价偏离 = side_sign × (P0/p_avg − 1) × 10⁴ |
| close_cost_bps | REAL | 收盘价偏离 = side_sign × (Pn/p_avg − 1) × 10⁴ |
| opportunity_cost | REAL | 机会成本 = (RouteShares − fill) × (Pn − P0) × side_sign |

### Phase 1（15 列）
| 列名 | 类型 | 说明 |
|------|------|------|
| p_decision | REAL | 决策价 Pd（NyOrderCreateAsOfDateTime 前最近 bar close；盘前取首 bar open） |
| delay_cost | REAL | 延迟成本 = RouteShares × (P0 − Pd) × side_sign |
| trading_cost | REAL | 交易成本 = total_fill × (p_avg − P0) × side_sign |
| wagner_is | REAL | Wagner IS = delay + trading + opportunity |
| wagner_is_bps | REAL | = wagner_is / (RouteShares × Pd) × 10⁴ |
| cost_stddev | REAL | fill_bdib cum_slippage_bps 标准差 |
| cost_p95 | REAL | cum_slippage_bps 95 分位 |
| cost_cvar | REAL | 超过 P95 的均值（条件风险价值） |
| order_duration_sec | REAL | 历时 = last_fill − route_as_of_time |
| exec_rate_shares_per_min | REAL | 执行速率 = total_fill / (duration/60) |
| temp_impact_5min_bps | REAL | 暂时冲击 = (P_recov_5min/p_avg − 1) × side_sign × 10⁴（窗口越界时 P_recov 取次日收盘价） |
| temp_impact_10min_bps | REAL | 同 10min（越界同上） |
| temp_impact_30min_bps | REAL | 同 30min（越界同上） |
| perm_impact_bps | REAL | 永久冲击 = (Pn/P0 − 1) × side_sign × 10⁴ |
| recovery_truncated | INTEGER | 恢复窗口越界标记（1=越界窗口改用次日收盘价作跨日恢复价格） |

## route → order 聚合策略

所有新指标在 route 层计算并存储于 `tca_route_summary`。order 层值通过 `tca_order_summary` VIEW + `build_order_report()` 由 route 值聚合：

| 指标类别 | 具体指标 | 聚合方式 |
|---------|---------|---------|
| 货币成本 | delay/trading/opportunity/wagner_is | SUM 求和 |
| 价格基准 | p_arrival/p_decision/p_close | 最早 route 取值（按 route_as_of_time） |
| bps 绩效 | arrival/close/temp/perm_impact_bps | 成交额加权平均 Σ(route_bps × fill × p_avg)/Σ(fill × p_avg) |
| 完成率 | fill/fill_continuous/fill_close | 求和比 Σfill / Σroute_shares |
| 参与率 | par_rate | 成交额加权平均 |
| 风险 | cost_stddev/p95/cvar | 各 route 独立 + order 取 max（保守） |
| 时点 | order_duration_sec | min(route_as_of_time) → max(last_fill_time) |
| 执行速率 | exec_rate | order 层重算 Σfill / (duration/60) |

**特殊语义**：p_arrival/perm_impact/opportunity_cost 在 order 层重查/重算（统一基准），不简单加权。

## 实施阶段

### Phase 0：核心基准补全（p_arrival / p_close / arrival_cost / close_cost / opportunity_cost）

**理论依据**:
- Perold (1988), "The Implementation Shortfall: Paper versus Reality", *Journal of Portfolio Management* 14(3)
- Keim & Madhavan (1998), "The Cost of Institutional Equity Trades", *Financial Analysts Journal* 54(4)
- Almgren & Chriss (1999), "Optimal Execution of Portfolio Transactions", *The Journal of Risk*
- Kissell (2014), *The Science of Algorithmic Trading and Portfolio Management*, §3.11 / §3.13 / §3.8

**改动文件**:
1. `DataPipeline/config.py` — flag `TCA_CORE_BENCHMARKS_ENABLED` + `_validate_config`
2. `DataPipeline/storage/schema/columns.py` — TCA_ROUTE_SUMMARY_COLUMNS + COLUMN_TYPE_MAP 追加
3. `DataPipeline/storage/schema/inline_ddl.py` — 表重建迁移 `_migrate_tca_route_summary_v2`
4. `DataPipeline/processing/tca_route_metrics.py` — `_compute_arrival_price` + `_compute_close_price` + 签名变更
5. `DataPipeline/orchestration/stages_process.py` — 加载 daily_summary
6. `DataPipeline/tests/processing/test_tca_route_metrics.py` — +8 用例

### Phase 1：Wagner IS + 风险 + 冲击分解

**理论依据**:
- Perold (1988), "The Implementation Shortfall: Paper versus Reality"
- Bertsimas & Lo (1998), "Optimal Control of Execution Costs", *Journal of Financial Markets* 1(1)
- Obizhaeva & Wang (2013), "Optimal Trading Strategy and Supply/Demand Dynamics", *Journal of Financial Markets* 16(1)
- Gatheral (2010), "No-Dynamic-Arbitrage and Market Impact", *Quantitative Finance* 10(7)
- Kissell (2014), *The Science of Algorithmic Trading and Portfolio Management*, §3.7

**改动文件**:
1. `DataPipeline/config.py` — flag `TCA_RISK_IMPACT_ENABLED`
2. `DataPipeline/processing/tca_route_metrics.py` — `_compute_decision_price` + `_compute_risk_metrics` + `_compute_recovery_price` + `_get_next_day_close` + `_compute_order_duration`
3. `DataPipeline/tests/processing/test_tca_route_metrics.py` — +12 用例

### Phase 2：order 级视图/API + 前端

**改动文件**:
1. `DataPipeline/config.py` — flag `TCA_ORDER_AGG_ENABLED`
2. `DataPipeline/storage/schema/inline_ddl.py` — `tca_order_summary` VIEW
3. `CostView/src/tca_query_service.py` — `build_order_report()`
4. `CostView/src/tca_query_builder.py` — order 聚合查询
5. `CostView/api/routers/costview.py` — aggregation 分支 + order 端点
6. `platform_data/contracts/tca_contracts.py` — TcaOrderSummary
7. `frontend/src/modules/costview/types.ts` + AnalysisView 聚合切换

## 全流程防漂移检查（G2）

| CP | 触发点 | 检查 | 通过标准 | 回退 |
|----|--------|------|---------|------|
| CP-0a | 表重建后 | 行数/字段/日期 | COUNT 不变; 35 列值不变 | snapshot_guard 恢复 |
| CP-0b | Phase 0 计算后 | 18 指标回归 | 容差 1e-6 | CORE=0 + 恢复快照 |
| CP-0c | Phase 0 新指标 | 覆盖率 | arrival ≥ pnl_vwap | 修复计算 |
| CP-1a | Phase 1 计算后 | 23 列回归 | 容差 1e-6 | RISK=0 + 恢复快照 |
| CP-1b | Phase 1 分解 | 一致性 | wagner_is ≈ Σ | 修复计算 |
| CP-1c | Phase 1 恢复 | 跨日恢复 | truncated=1 行中 temp_impact_30min 非NULL率 ≥ 90% | 修复计算 |
| CP-1d | Phase 1 风险 | 覆盖率 | stddev ≥ pnl_vwap | 修复计算 |
| CP-2a | order 聚合后 | 一致性 | order 值 = 手工聚合 | 修复聚合 |

## 改动-需求双向矩阵（G3）

| 改动 | 论文缺口 | 需求 |
|------|---------|------|
| p_arrival + arrival_cost_bps | B2.4 到达价基准 | D1 统一定义 |
| p_close + close_cost_bps | B2.4 收盘价基准 | D1 统一定义 |
| opportunity_cost | B2.1 机会成本 | D1 统一定义 |
| p_decision + delay_cost | B2.1 Wagner IS | D2 成本 |
| trading_cost + wagner_is | B2.1 实施短缺 | D2 成本 |
| cost_stddev/p95/cvar | B2.3 风险 | D2 风险 |
| order_duration/exec_rate | B2.3 风险 | D2 风险 |
| temp/perm_impact（4窗口） | B2.2 市场冲击 | D2 成本 |
| order 视图/API | B3 归因分层 | G3 验收 |
| snapshot_guard / flag / 索引 | 工程支撑 | G0/G2 |

**范围外（明确标注）**: D2 可操作性（订单类型/队列/费用）、B2.5 订单簿流动性（无 L2 数据）、B2.6 事前预测（P3 后续）
