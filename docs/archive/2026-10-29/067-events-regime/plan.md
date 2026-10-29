# 067 — 事件与市场流动性状态

> 父计划：`specs/057-execution-decision-loop/plan.md`（DL-11）
> 分支：`067-events-regime` · worktree：`../EMSXView-wt-067-events-regime`
> 依赖：DL-01（058，意图/导出解析）、DL-10（066，日度基线）· 消费者：DL-17（硬约束）、DL-18（状态切换模板）、DL-23（错位期样本单列）
> 数据源核验：2026-10-23 对 `regime.db` 实测探针（下表「准确性」列均经真实数据验证，非纸面口径）

## 1. 问题

- **流动性错位阶段常规框架失效**：2020-03 型阶段微观流动性丧失，小幅调仓也引发超常波动（外部依据：锦成盛 2020-03）——需单独识别并让下游切换保守参数、错位期样本单列；
- **事件维度无契约**：宏观事件（FOMC 等）、财报/除息、半日市需要统一的 `EventFlag` / `MarketRegimeState` 产出进入 `MarketStateSnapshot`；
- **用户质询（2026-10-23）**：「事件数据来源是什么？信息是否准确？不强求有这些信息」——本规格 §2.2 以实测数据回答，不可得维度显式裁剪而非伪造。

## 2. 方案（P2 三栏）

### 2.1 理论依据

流动性错位阶段常规分析框架失效，需单独识别；涨跌停、半日市等「游戏规则」是硬约束输入（tasks.md DL-11）。数据可信度分级：实测可用 > 尽力而为 > 不做。

### 2.2 技术方案（细化到文件与函数）

**数据来源与准确性（实测结论，2026-10-23 探针）**：

| 维度 | 来源（表/文件） | 实测状态 | 处置 |
|---|---|---|---|
| 市场级流动性状态 | `regime.db::daily_liquidity_regime`（5,710 行 = 23 市场 × 日，`liq_regime` + `turnover_zscore`，阈值 thin<−1/thick>1，带 `config_version` 审计） | ✅ 准确可用 | 主交付 |
| 市场级波动状态 | `regime.db::daily_vol_regime`（5,710 行，vix_absolute 法，low<12/normal<18/high≥25） | ✅ 准确可用 | 主交付 |
| 市场级趋势状态 | `regime.db::daily_trend_regime`（5,710 行，ma_rsi_combo） | ✅ 准确可用 | 随交付 |
| 宏观事件日历 | `regime.db::ref_macro_event_calendar`（131 条，12 类事件含 fomc，带 severity/window_days/market_code） | ✅ 准确可用 | 主交付 |
| 财报/除息 | EMSX 导出 `Exp Earn Rpt Time` / `Ex-Dvd Flag`（DL-01 解析） | ⚠️ 附录 A 样例两列全空/N——真实填充率未经真实导出验证 | **尽力而为**：导出含值则标记，填充率随响应披露；不强求 |
| 半日市 | DL-03 `HALF_DAY_CLOSE_OVERRIDES`（US/LN/GR/HK 2026–27 共 14 条） | ✅ 有限覆盖（v0 静态起步，tasks 既定） | 随交付 |
| 指数生效日 | **无数据源**（DL-03 日历不含；regime.db 无指数调仓表） | ❌ 不可得 | **不做**——子规格原写法「来自会话日历」有误，本次修正；待管道 P3 交易日历或外部指数日历，预留 `EventFlag` 扩展位 |

**契约**（`platform_data/contracts/market_contracts.py` 扩展）：

- `MarketRegimeState`（frozen dataclass）：`market_code`、`as_of`、`liq_regime`（thin/normal/thick）、`vol_regime`（low/normal/high）、`trend_regime`、`macro_events: tuple[EventFlag, ...]`（当日窗口内事件）、`config_version`（regime 配置版本，下游可审计）
- `EventFlag`（frozen dataclass）：`code`（事件类型/代码）、`severity`（high/normal/low）、`window_days`、`source`（macro-calendar/emsx-export/half-day-table）、`evidence`（描述或命中值）
- `REGIME_SCHEMA_VERSION = "market-regime-v1"`

**适配器**（`platform_data/adapters/events.py` 新建；公开方法登记 `module-boundary.md` §2.3）：

- `EventRegimeAdapter`：
  - `get_market_state(market_code, *, as_of=None) -> MarketRegimeState | None`：日级三 regime + 当日宏观事件（窗口内）；
  - `get_market_states(market_codes, *, as_of=None) -> list[MarketRegimeState]`：批量（盘前单按股票池）；
  - `event_flags_for_ticker(equ_ticker, *, export_row=None) -> list[EventFlag]`：逐票事件——半日市（DL-03 日历）+ 导出财报/除息字段（调用方传入 DL-01 解析行；无导出行时仅半日市，`coverage` 披露导出缺失）；
  - 未知市场/无数据返回 None 或空列表（不抛错；降级可见）。
- 市场码折叠复用 DL-03 `market_code_for`（EUR→EU 等，与 regime 库 23 市场码对齐）。

**端点**（`MarketView/routers/` 扩展或并入 `baseline.py` 同款风格新文件 `routers/regime.py`）：

- `GET /api/marketview/market-regime?markets=US,JP&as_of=...`：返回逐市场 `MarketRegimeState` + 宏观事件 + `config_version`；未配置/无数据市场以空状态 + message 说明。

**测试**（`backend/api/tests/test_event_regime.py` 新建）：

1. 适配器集成（tmp 库夹具：`daily_*_regime` + `ref_macro_event_calendar` 最小表）：三状态读取、事件窗口命中（window_days 内/外）、`config_version` 透传、未知市场 None；
2. `event_flags_for_ticker`：半日市命中（DL-03 条目）、导出含财报时间 → 标记 + source=emsx-export、无导出行 → 仅半日市且 coverage 披露；
3. 端点：TestClient + fake 单例（信封/未知市场/错误映射 500）；
4. **状态切换点与历史压力日对照**：以真实 `regime.db` 抽样——取 `liq_regime='thin'` 的日期集合与已知压力期对照（如 2020-03 不在数据范围内则取数据内 thin 日期分布说明），PR 描述附输出。

**DL-03 双源差异（本次实测发现，登记协作项）**：管道 `ref_market_mapping`（23 市场，带 source_file_version/synced_at 审计）与 DL-03 `SESSION_REGISTRY` 有 6 处实质差异——AU close 16:00 vs **16:10**、LN 16:30 vs **16:35**、MK 17:00 vs **16:50**、NO 16:30 vs **16:25**、SP 17:00 vs **17:04**、IJ 午休 无 vs **12:00-13:30**（SP 午休本侧有/管道无待核）。管道表更可能权威（有审计字段且 AU/LN/IJ 细节本侧确有错）——**不在本任务修改**（严守范围锁），登记为 DL-03 修订项：走 DL-06 契约流程或单独小 PR，以管道 `ref_market_mapping` 为基准对齐并升 `SESSION_REGISTRY_VERSION`；DL-18 时间窗消费前须先对齐（消费方导言）。

### 2.3 检验方法（= 验收标准）

1. 事件命中抽检（夹具事件日期 → 标记正确，窗口边界）；
2. 状态切换点与历史压力日对照（真实数据 thin 日期抽样，PR 附输出）；
3. 填充率披露（财报/除息维度随响应给 coverage，不静默）；
4. `module-boundary.md` §2.3 登记；既有全量不回归（backend + CostView + MarketView 分进程）。

### 2.4 范围裁剪（诚实记录，对用户质询的直接回应）

- **指数生效日不做**（无数据源）——原写法修正；
- **财报/除息不强求**——导出字段尽力而为 + 填充率披露；
- **盘中截面叠加**（价差/量/波动 z 的实时部分）属 DL-15，本任务只做日级；
- **DL-03 双源差异不修**（范围外），只登记。

## 3. 规模与拆分说明

预估 diff 约 400 行（契约 ~50 + 适配器 ~140 + 端点 ~80 + 测试 ~130）。DL-11 为验收原子单元，沿用单 PR 先例。

## 4. 范围锁

| 动作 | 文件 |
|---|---|
| 修改 | `platform_data/contracts/market_contracts.py`（`MarketRegimeState` / `EventFlag` / 版本常量） |
| 修改 | `platform_data/contracts/__init__.py`（导出） |
| 新建 | `platform_data/adapters/events.py` |
| 修改 | `platform_data/adapters/__init__.py`（导出） |
| 新建 | `MarketView/routers/regime.py` + `MarketView/main.py` 接线 |
| 修改 | `.codebuddy/rules/module-boundary.md` §2.3（适配器登记） |
| 新建 | `backend/api/tests/test_event_regime.py` |
| 新建 | `specs/067-events-regime/plan.md`（本文件） |

范围外（不碰）：`regime.db`（只读消费）、DL-03 注册表修订（双源差异，另立）、`CostView/`、`data_access/`、DL-15 盘中叠加、DL-17/18 消费方。

## 5. 验收（P4）

| 需求（057 DL-11 检验方法） | 覆盖 | 结果 |
|---|---|---|
| 事件命中抽检 | 用例 1/2 | 待实施后回填 |
| 状态切换点与历史压力日对照 | 用例 4（真实数据抽样）+ PR 输出 | 待实施后回填 |
| 状态标签交给执行侧 | 契约 + 端点（DL-17/18 消费预告） | 待实施后回填 |
| 填充率披露 + 适配器登记 + 无回归 | §2.4 + module-boundary + 全量 | 待实施后回填 |

## 6. 本次不做

- DL-03 注册表与管道 `ref_market_mapping` 的双源对齐（另立修订项，消费前必须完成）；
- 指数生效日（无数据源，预留 `EventFlag` 扩展位）；
- 盘中截面状态叠加（DL-15）；
- 错位期样本单列的报表改造（DL-23，本任务只提供状态标签）。
