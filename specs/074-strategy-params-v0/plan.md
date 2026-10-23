# 074 — 参数策略 v0（DL-18）

> 父计划：`specs/057-execution-decision-loop/plan.md`（DL-18）
> 分支：`074-strategy-params-v0` · worktree：`../EMSXView-wt-074-strategy-params-v0`
> 依赖：DL-03（会话）、DL-04（算法族）、DL-10（基线）、DL-11（regime）、DL-13（difficulty）、DL-16（注册表）、DL-17（约束与参数上限）· 消费者：DL-21（决策日志）、DL-22（影子运行）

## 1. 问题

- **参数靠人工与全局常数**：`route_engine` 的参与率取 `plan.participation_rate`（route plan 静态配置）、`strategy_params` 取 `plan.default_strategy_params`——与意图（PM Note 13）、市场状态（regime）、单票难度（DL-13）无关；tasks 4.3 目标状态是「意图驱动、状态感知的参数化」；
- **时间窗无时区**：`_parse_end_time` 注释明写「assume UTC for simplicity」——交易所本地 HH:MM 被当作 UTC，跨市场时间窗系统性错位（JP 15:30 本地 = 06:30 UTC）；
- **无 σ 限价与状态模板**：高波动期仍用同一参与率与限价保护，thin/high 状态无降级路径；
- **VWAP 切片用均匀 profile**（`[1.0] * n`），未接 DL-10 日内量曲线。

## 2. 方案（P2 三栏）

### 2.1 理论依据

意图 → 算法族（DL-04）是「按意图选策略」的契约基础；参与率目标函数取代「18% × 比例」的全局常数（tasks DL-18）；状态切换模板使 thin/high 期自动保守（DL-11 regime 的消费点）；σ 限价保护把波动转成价格边界。

### 2.2 技术方案（细化到文件与函数）

**契约**（`platform_data/contracts/param_strategy.py` 新建；纯数据 + 纯函数）：

- `PARAM_TEMPLATE_VERSION = "param-template-v1"`；`DEFAULT_LIMIT_SIGMA = 2.0`；`THIN_PARTICIPATION_SCALE = 0.5`；`HIGH_VOL_SIGMA = 3.0`
- `ParameterPlan`：`order_key`、`families`（DL-04 细分族，MIX 两段）、`participation_pct`（目标参与率 %，对齐 073 的 18.0/9.0 上限）、`window_start_min`/`window_end_min`（**会话相对分钟**，从开盘算）、`limit_sigma`、`template_id`、`rationale`、`schema_version`
- 纯函数：
  - `participation_pct(intent_ratio_pct, max_cap_pct, regime) -> float`：`min(intent, cap)`，`liq_regime == "thin"` 时 ×0.5；下限 0.1（与 073 精度对齐）
  - `session_window_minutes(session, families, half_day_close=None) -> tuple[int, int]`：
    - `vwap`/`twap`/`pov` 族：开盘后 5 分钟起 → **收盘竞价前 5 分钟止**（不跨竞价）；
    - `auction_close` 族：收盘前 5 分钟 → 收盘（若 `closing_auction` 存在）；
    - 半日市（覆盖表命中）：结束时刻按半日市收盘收缩；
  - `limit_sigma_multiple(vol_regime) -> float`：`high` → 3.0、其余 2.0
  - `build_parameter_plan(order_key, intent_families, session, regime, *, half_day_close=None, max_cap_pct=18.0) -> ParameterPlan`：组合上述规则，`rationale` 记录触发的模板（thin/high/收盘竞价/半日市）
- 时区工具：`session_local_to_utc(session_date, hhmm, exchange_code) -> datetime`（经 `ExchangeSessionAdapter.session_bounds_for` 的 tz 换算）

**路由引擎时区修复**（`backend/api/services/route_engine.py`）：

- `_parse_end_time(time_str, now, *, exchange_code="")`：按 `EXCHANGE_TIMEZONE[exchange_code]` 解释 `time_str` 为交易所本地时间 → 转 UTC；未知交易所回落 UTC + 明确日志（不静默「assume UTC」）；
- 调用点（`_generate_time`/`_generate_hybrid`）：传入订单的 exchange（`order.exchange`）。

**范围说明（诚实边界）**：

- **不自动改写 route plan 既有参数**：v0 交付「`build_parameter_plan` 能力 + 时区修复」；参数落库/下发仍走既有 `plan.participation_rate`/`default_strategy_params` 链路（与 073「不自动改写」一致），接入开关留 DL-22 影子运行后评估；
- **VWAP 切片接入日内曲线**：DL-10 提供日度基线（不含日内曲线），DL-09 快照表未就绪——v0 以「会话相对时间等分 + 收盘竞价前结束」为窗口规则，`volume_profile` 接线登记为 DL-09 就绪后的增强；
- **tasks 原写「时区修复单独一个 PR」**：本任务合并交付——时间窗规则（会话相对分钟）与本地时间解析是同一正确性链条，拆开会让窗口规则在时区错误上失效；PR 描述明确记录该决策。

**测试**（`backend/api/tests/test_param_strategy.py` 新建）：

1. `participation_pct`：cap 生效、thin ×0.5、下限 0.1、EUR 9.0 上限；
2. `session_window_minutes`：VWAP 族在收盘竞价前结束（US 09:35–15:50）、auction_close 族（15:50–16:00）、半日市收缩（US 13:00 → 12:50 起）、JP 午休不改窗口边界；
3. `limit_sigma_multiple`：high → 3.0、normal → 2.0；
4. `build_parameter_plan`：MIX 两段（families 含 vwap + auction_close）、rationale 记录（thin/high/半日市）；
5. `session_local_to_utc`：US 16:00 本地 → 21:00 UTC（EDT）/ 20:00 UTC（EST，DST 切换日）；JP 15:30 → 06:30 UTC；
6. `_parse_end_time` 回归：US 16:00 → UTC 21:00（EDT 当日）、未知交易所回落 UTC 且日志；
7. 既有 route_engine 测试不回归（`test_route_engine_apply.py` 等）。

### 2.3 检验方法（= 验收标准）

1. 规则表单测（意图 × 状态 × 半日市矩阵）；
2. 时区修复回归（多市场本地→UTC，含 DST）；
3. `build_parameter_plan` 的 rationale 可解释（每条规则触发可见）；
4. 既有路由链路不回归（backend 全量 + boundaries）。

### 2.4 边界（诚实记录）

- **不自动改写参数**（同上）；
- **日内量曲线未接**（DL-09 就绪后增强）；
- **σ 限价只出目标值**：实际限价下发仍由既有订单字段决定（v0 不写回 `order.price`）；
- **半日市依赖 DL-03 静态表**（14 条 2026–27 覆盖）。

## 3. 规模与拆分说明

预估 diff 约 460 行（契约 ~200 + 时区修复 ~35 + 测试 ~200 + 子规格 ~25）。DL-18 为验收原子单元（参数规则 + 时区正确性一次交付）。

## 4. 范围锁

| 动作 | 文件 |
|---|---|
| 新建 | `platform_data/contracts/param_strategy.py` |
| 修改 | `platform_data/contracts/__init__.py`（导出） |
| 修改 | `backend/api/services/route_engine.py`（`_parse_end_time` 时区修复 + 调用点传 exchange） |
| 新建 | `backend/api/tests/test_param_strategy.py` |
| 修改 | `specs/057-execution-decision-loop/tasks.md`（DL-18 状态） |
| 新建 | `specs/074-strategy-params-v0/plan.md`（本文件） |

范围外（不碰）：`MarketView/`、`CostView/`、EV 前端参数预填、DL-19/20、DL-21 决策日志、volume profile 接线。

## 5. 验收（P4）

| 需求（tasks DL-18） | 覆盖 | 结果 |
|---|---|---|
| 意图 → 算法族（MIX 两段） | `build_parameter_plan` + 用例 4 | 待实施后回填 |
| 参与率目标函数取代 18% × 比例 | `participation_pct` + 用例 1 | 待实施后回填 |
| 会话相对时间窗（VWAP 段在收盘竞价前结束） | `session_window_minutes` + 用例 2 | 待实施后回填 |
| σ 限价保护 | `limit_sigma_multiple` + 用例 3 | 待实施后回填 |
| 状态切换模板 | thin ×0.5 / high σ 3.0 + rationale | 待实施后回填 |
| `_parse_end_time` 时区修复 | 用例 5/6/7 | 待实施后回填 |
| VWAP 切片接入日内曲线 | **范围外**（DL-09 就绪后） | 记录边界 |

## 6. 本次不做

- 参数自动下发/改写（DL-22 后评估）；
- 日内量曲线 volume profile（DL-09）；
- EV 前端参数预填与展示；
- DL-19/20 评估口径与配对。
