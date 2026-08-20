# 003-tca-core-benchmarks 实施进度跟踪

> 每完成一项，更新状态为 ✅；进行中 ⏳；阻塞 🔴
> 每次 checkpoint 通过后更新对应行

## 总览

| 项目 | 状态 |
|------|------|
| 方案落盘 (plan.md) | ✅ |
| Phase 0: config flag | ✅ |
| Phase 0: schema 列 | ✅ |
| Phase 0: 表重建迁移 | ✅ |
| Phase 0: 计算逻辑 | ✅ |
| Phase 0: stage 加载 daily_summary | ✅ |
| Phase 0: 单元测试 | ✅ |
| Phase 0: 回归基线 CP-0a/0b/0c | ✅ |
| Phase 1: config flag | ✅ |
| Phase 1: 计算逻辑 | ✅ |
| Phase 1: 单元测试 | ✅ |
| Phase 1: 一致性 CP-1a/1b/1c/1d | ✅ 四项全部通过（2026-08-19） |
| BDIB 覆盖率调查 | ✅ |
| S7 daily_close 补跑 | ✅ |
| recent 日期重算回填新列 | ✅ |
| 历史日期 BDIB 缺失确认 | ✅（不可回补日期已文档化） |
| Phase 2: order 视图/API | ✅ |
| Phase 2: 前端类型/API | ✅ |
| Phase 2: 前端 UI（表格+切换+详情） | ✅ |
| 监控覆盖扩展 18→38 | ✅ |
| 窗口内 BDIB 缺口回补 | ✅（2 日期 Bloomberg 无数据，文档化） |

## Checkpoint 记录

### CP-0a 表重建迁移后
- [x] 行数不变
- [x] 现有 35 列值不变
- [x] 20 新列全 NULL

### CP-0b Phase 0 计算后回归
- [x] 现有 18 指标容差 1e-6

### CP-0c Phase 0 新指标覆盖率
- [x] arrival_cost_bps 非NULL率 ≥ pnl_vwap 非NULL率
- [x] p_close 非NULL率 ≥ 90%
- [x] 完全成交路由 opportunity_cost = 0

### CP-1a Phase 1 计算后回归
- [x] Phase 0 5 列 + 现有 18 列容差 1e-6（RISK=0 重算对比：20260707/20260615/20260810 完全一致；20260812 首检差异为 daily_summary 漂移，force 重算后一致）

### CP-1b Phase 1 分解一致性
- [x] wagner_is ≈ delay + trading + opportunity（容差 0.01）—— 201,637 行非NULL全部满足，最大偏差 0.0

### CP-1c Phase 1 恢复窗口
- [x] 窗口内（20260501+）truncated=1 行中 temp_impact_30min 非NULL率 92.26% ≥ 90%
- [x] 全表 truncated=1 行中 temp_impact_30min 非NULL率 90.49% ≥ 90%（历史 S7 补跑 + 二次重算后）

### CP-1d Phase 1 风险覆盖率
- [x] cost_stddev 非NULL率 54.36% ≥ pnl_vwap 非NULL率 34.16%（全表，历史 RISK=1 重算后）

### CP-2a order 聚合一致性
- [x] order 值 = 手工聚合

## 执行日志

### 2026-08-14
- 方案终稿落盘 `specs/003-tca-core-benchmarks/plan.md`
- 开始 Phase 0 实施
- config.py: 新增 `TCA_CORE_BENCHMARKS_ENABLED` / `TCA_RISK_IMPACT_ENABLED` / `TCA_ORDER_AGG_ENABLED` 三 flag
- columns.py: `TCA_ROUTE_SUMMARY_COLUMNS` 35→55 列，新增 `TCA_CORE_BENCHMARKS_COLUMNS`(5) + `TCA_RISK_IMPACT_COLUMNS`(15)
- inline_ddl.py: 新增 `_migrate_tca_route_summary_v2` 表重建迁移（幂等，临时库验证通过）
- tca_route_metrics.py: 新增 8 计算函数，`_OUTPUT_COLUMNS` 35→55
- market_data.py: 新增 `get_daily_summary_for_date_range`（区间批量读取）
- stages_process.py: 新增 `_load_daily_summary_for_metrics` helper
- 测试: test_tca_route_metrics.py 33 passed（含 Phase0/1 20 个新用例）

### 2026-08-17
- **G0 迁移**: 生产 fill_bdib.db 表重建 35→55 列，行数 216,531 不变，现有 35 列 SHA-256 抽样哈希一致
- **BDIB 覆盖率调查**: p_arrival 低覆盖率根因 = raw_bdib 日内 bar 覆盖缺口（20260421 有成交 406 ticker，raw_bdib 仅 371；非代码缺陷，pnl_vwap 同受影响 2.6%）
- **S7 daily_close 补跑**: 新增 `scripts/ops/backfill_daily_metrics.py`；修复 `_get_active_tickers_for_date` 回退 processed_fills 查询 + 新增 `get_distinct_tickers_for_date`；73 日期补跑 50,996 行
- **p_close 回退**: `_compute_close_price` 新增 raw_bdib 末 bar close 回退（S7 未跑时），覆盖率 0%→89.9%（20260812）
- **recent 日期重算**: 2026-05-01~08-12 全量重算，p_arrival/p_close/wagner_is 84.6%/99.8%/84.6%；perm_impact 77.5%
- **历史日期 BDIB 缺口确认**: 168 日期 p_arrival<50%（多为 2025-09~2026-04 旧数据，超出 180 天保留窗口，无法回补；文档化）

## BDIB 覆盖缺口记录（回补后终态）

| 日期 | 有成交 ticker | 回补后覆盖 | 可回补? |
|------|-------------|-----------|--------|
| 20250915~20260430 | ~1300 | 0% | ❌ 超保留窗口 |
| 20260421 | 406 | 4% (route级) | ⚠️ 窗口边缘，未回补 |
| 20260511/12 | 912/786 | 3.7% / 7.9% | ❌ Bloomberg 无数据（根因调查确认） |
| 20260706/07 | 606/731 | 99.5% / 100% | ✅ 已回补 |
| 20260720/20260810 | 1601/637 | 96.1% / 100% | ✅ 已回补 |
| 其余窗口内缺口日期 | - | 84-100% | ✅ 已回补（13/15 恢复） |
| 20260812 (最新) | 705 | 89.9% | ✅ |

## 窗口内 BDIB 缺口回补（已完成 2026-08-18）

15 个缺口日期已通过 `scripts/ops/backfill_bdib_gaps.py` 精准回补完成（详见执行日志）。
13/15 日期恢复至 84-100% p_arrival 覆盖率；20260511/12 经根因调查确认为
Bloomberg 侧数据缺失（见执行日志 2026-08-18 根因调查），无法回补，已文档化。

### 2026-08-17 (Phase 2 完成)
- **contracts**: `TcaRouteSummary` 扩展 20 新字段；新增 `TcaOrderAggregate`（order 级聚合契约）；`__init__.py`/`adapters/__init__.py` re-export
- **查询服务**: `TcaQueryService.build_order_report()` + `_aggregate_order()` 实现聚合策略（货币成本 SUM / bps 成交额加权 / 价格基准取首 / 风险取 max / 速率重算）
- **API**: `POST /api/tca/analyze-orders` 新端点（`TCA_ORDER_AGG_ENABLED` 门控）+ `_serialize_order_aggregate` + `_serialize_route` 扩展 20 字段
- **前端**: `types.ts` 新增 `TcaOrderAggregate` + `TcaRouteSummary` 扩展 20 可选字段；`services/api.ts` 新增 `analyzeTcaOrders()` + `TcaOrderReport`
- **测试**: `CostView/tests/test_order_aggregation.py` 8 用例（SUM/加权/求和比/max/首route/重算/NaN清理）；全 CostView 测试通过；前端 costview 20 测试通过；tsc/eslint 无 costview 错误
- **端到端验证**: `build_order_report(20260812)` 返回 4 订单，多 route 订单 5237109 正确聚合（routes=2, wagner_is 合并, arrival_bps 加权）

### 2026-08-18 (Phase 2 前端 UI)
- **TcaOrderTable**: 新增 7 列（Arrival Cost / Close Cost / Wagner IS / Cost SD / Duration / Temp Imp 5m / Perm Imp），min-width 1160→1640px，含 tooltip（P₀/Pn/wagner bps/恢复截断）
- **OrderAggregateTable**（新组件）: Order 级聚合视图，调用 `/api/tca/analyze-orders`，展示 SUM/加权 bps/风险 max 等聚合指标
- **AnalysisView**: 新增 Route View / Order View 切换按钮；Selected Route Detail 增加 8 个新指标卡片（Arrival/Close/Wagner IS/Cost StdDev/Duration/Temp/Perm/PnlVWAP Cont）
- **CostViewModule**: 新增 `orderReport`/`viewMode` state + `fetchOrderReport()`（调用 analyzeTcaOrders）+ 切换逻辑
- **测试**: `order-aggregate-table.test.tsx` 5 用例；全 costview 25 测试通过；eslint 通过；tsc 无 costview 错误；`build:costview` 成功

### 2026-08-18 (监控覆盖扩展 18→38)
- **后端** `CostView/src/monitoring/metric_coverage.py`: `COMPUTED_METRICS` 18→38（新增 Phase 0 5 项 + Phase 1 15 项）；`BDIB_DEPENDENT_METRICS` 10→24（新增到达/决策/收盘价、IS 分解、冲击指标）
- **前端** `frontend/src/modules/costview/lib/monitoring-metrics.ts`: `ALL_TCA_METRICS` 18→38 + `METRIC_LABELS` 新增 20 项中文标签 + `BDIB_DEPENDENT_METRICS` 扩展
- **测试** `CostView/tests/test_monitoring.py`: `_TCA_DDL` 补全 20 新列（测试 fixture 对齐生产 schema）
- **验证**: 后端 test_monitoring 34 passed；前端 vitest 25 passed；eslint/tsc 通过
- **生产验证**: `get_coverage(20260812)` 返回 38 指标，p_arrival/p_close/wagner_is 89.93%、cost_stddev 58.3%、order_duration 37.59%、perm_impact 0%（最新日期无次日收盘，预期）

### 2026-08-18 (窗口内 BDIB 缺口回补)
- **新增** `scripts/ops/backfill_bdib_gaps.py`：针对缺口日期的精准回补脚本（只拉取当日有成交的 ticker，避免全市场 2120 ticker 的浪费；跳过 close 为 NULL 的空 bar）
- **执行**: 15 个缺口日期、4,275 个 ticker-date、4,057,940 行写入 raw_bdib（全部成功，0 失败）
- **重算**: 15 日期 recompute_route_metrics --force，15,037 路由重算
- **结果**: 13/15 缺口日期恢复到 84-100% p_arrival；全窗口 (20260501-0812) p_arrival 84.6%→**92.7%**、p_close 99.8%、wagner_is 92.7%
- **不可修复日期**（文档化）: 20260511 (3.7%) / 20260512 (7.9%) — 根因调查确认 Bloomberg 侧数据缺失，无法通过回补解决
- **20260511/12 根因调查**（Bloomberg 侧数据缺失，非代码缺陷）:
  - 回补实际写入成功：20260511 写入 551,976 行 / 433 ticker（有成交 912）、20260512 写入 533,932 行 / 429 ticker（有成交 786）
  - 按交易所分析 20260511：US 504 个有成交 ticker 仅 1 个有 BDIB bar（99.8% 缺口）；KS/AU/GR/FP/SW/NA 全部 100% 缺口；JP 93% 缺口；仅 CN 22/22 全覆盖（亚洲市场有数据）
  - 直接调用 `fetch_bdib_for_ticker_date("CICT SP Equity", "20260511")` 返回空，确认 Bloomberg API 本身无数据
  - 结论：2026-05-11/12 为合法交易日（周一/周二，raw_fills 分别 38,252 行），Bloomberg BDIB 对欧美/日韩/澳市场该两日无日内 bar（仅中国等亚洲市场有），属 Bloomberg 数据源缺口，无法回补
- **20260511/12 重新回补尝试**（2026-08-18，二次确认）: 再次运行 `backfill_bdib_gaps.py --dates 20260511 20260512`，1607 个 ticker-date 全部返回空、0 行写入。Bloomberg 数据源缺口结论维持不变，此两日期最终判定为不可修复

### 2026-08-18 (pytest capture 崩溃修复)
- **问题**: pytest 默认 capture 模式运行 import `DataPipeline.ingestion` 的测试文件时崩溃（`ValueError: I/O operation on closed file`，"no tests ran"）
- **根因**: `DataPipeline/ingestion/fill_fetch.py` 模块级 `sys.stdout` 重包装代码（`io.TextIOWrapper`）在 import 时替换 stdout，连带关闭 pytest fd capture 的 tmpfile；非 pytest 版本问题（最小复现证明任何版本均触发）
- **修复**: 重包装逻辑提取为 `_configure_console_encoding()` 函数，仅由 `main()` 调用（独立运行编码修复仍生效），import 零副作用
- **验证**: CostView 全套 249 passed + DataPipeline 42 passed（均默认 capture 模式，无需 `--capture=no`）

### 2026-08-18/19 (CP-1 四项一致性检查)

**首检结果（重算前）**:
- CP-1a: 20260707/20260615 完全一致；20260812 有 434 行 p_close 差异 → 根因调查确认 **daily_summary 漂移**（08-17 重算后 S7 更新 daily_close：363 行重算值 100% == 当前 daily_close + 71 行生产 NULL/重算有值），非 Phase 1 污染
- CP-1b: ✅ 65,599 行 wagner_is 全部满足分解恒等式，最大偏差 0.0
- CP-1c: ❌ 截断率 73.57%（旧口径）。根因：97.4% 截断路由含收盘竞价成交，恢复窗口以全部成交末笔为基准必然越界
- CP-1d: 窗口内 ✅（cost_stddev 57.98% ≥ pnl_vwap 38.62%）；全表 ❌（历史日期 Phase 1 未重算）

**修复决策（用户确认）**:
- CP-1c: 恢复窗口定义不变（订单成交时刻客观真实），越界时恢复价格改用**次日 daily_close**（跨日/隔夜恢复，Almgren & Chriss 1999 / Obizhaeva & Wang 2013）；`recovery_truncated` 语义改为"使用跨日恢复价格"标记；plan.md 通过标准更新为"truncated=1 行中 temp_impact_30min 非NULL率 ≥ 90%"
- CP-1d: 历史日期重算 RISK=1
- CP-1a: 20260812 force 重算修复漂移

**实施**:
- `tca_route_metrics.py` `_compute_impact_metrics`: 越界窗口恢复价格从"当日最后 bar close"改为"次日 daily_close"（`_get_next_day_close` 复用，无新增数据加载）
- 测试: `test_temp_impact_truncated` 更新 + 新增 `test_temp_impact_truncated_no_next_close`；DataPipeline 149 passed、CostView 249 passed
- 快照: `snapshot_guard.py --create --label pre-cp1-recovery-fix`（1.3 GB）
- 窗口重算: 20260501~0812 force（73 日期、71,451 行、0 错误，2h35m）
- 历史重算: 20250915~20260430 force（161 日期、145,804 行、0 错误，4h38m）
- 历史 S7 补跑: `backfill_daily_metrics.py --start-date 20250915 --end-date 20260430`（161 日期、114,481 行、0 错误，1h39m）—— daily_close 来自 Bloomberg 日频 PX_LAST（不受 BDIB 180 天限制，已实测可回溯）
- 历史二次重算: 161 日期 force 完成（5h59m），truncated=1 行获得跨日恢复价格

**终检结果（2026-08-19，四项全部通过）**:
- CP-1a: ✅ 20260812/20260707/20260615 三日期 23 列全部一致（RISK=0 重算对比，容差 1e-6）
- CP-1b: ✅ 201,637 行（含历史 135,442）全部满足 wagner_is ≈ delay+trading+opportunity，最大偏差 0.0
- CP-1c: ✅ 全表 truncated=1 行中 temp_impact_30min 非NULL率 **90.49%**（155,435/171,771）≥ 90%；窗口内 92.26%
- CP-1d: ✅ 全表 cost_stddev 非NULL率 54.36% ≥ pnl_vwap 非NULL率 34.16%
