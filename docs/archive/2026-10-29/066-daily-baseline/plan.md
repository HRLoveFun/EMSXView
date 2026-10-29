# 066 — 日度基线适配器

> 父计划：`specs/057-execution-decision-loop/plan.md`（DL-10，§4.1 R1 交易前检测 A 层）
> 分支：`066-daily-baseline` · worktree：`../EMSXView-wt-066-daily-baseline`
> 依赖：DL-03（061，会话注册表——竞价时段边界）、DL-05（064，盘点结论：BDIB 白名单内零缺口、BDIB 主源）· 消费者：DL-11（事件与状态）、DL-13（预期成本拟合）、DL-14（盘前单）
> 关联：`platform_data/adapters/market.py`（现有全局常数阈值——本任务替换为个股分布口径）

## 1. 问题

- **全局常数阈值不看个股历史**：`market.py` 的量比 2×/5×、日波动 25/40、日内波动 2/3 对所有市场所有股票一刀切——不同市场、不同个股量纲差异大（外部依据），小盘股常态波动被持续误报、大盘股异常被漏报；
- **日度基线无契约产出**：DL-11/13/14 都消费「个股 60 日稳健分布」特征，当前无适配器无契约；
- **DL-09 未就绪**：日快照与日内量曲线表在管道侧（DL-09），v0 须按 access-guide 通道规则直读明细（点查上限 100 ticker·日），并为 DL-09 就绪后的切换留接口。

## 2. 方案（P2 三栏）

### 2.1 理论依据

个股自身历史分布的稳健 z 值优于全局常数（tasks.md DL-10）；不同市场、不同个股量纲差异大（外部依据）。

### 2.2 技术方案（细化到文件与函数）

**契约**（`platform_data/contracts/market_contracts.py` 扩展，与既有 MarketSnapshot 同文件同风格）：

- `MarketBaseline`（frozen dataclass）：逐票日度基线——`equ_ticker`、`as_of`（基线数据截止日）、`log_volume_z`（60 日 log 量 median/MAD z）、`vol_percentile`（日波动分位，0–100）、`intraday_vol_percentile`（日内波动分位）、`overnight_gap_sigma`（隔夜跳空 σ 倍数）、`auction_open_pct` / `auction_close_pct`（开/收盘竞价量占比）、`adv5_adv60_ratio`、`spread_proxy_z`（bar 级价差代理 z）、`n_days`（实际入算天数）、`excluded_dates`（被剔除的特殊日）
- `BASELINE_SCHEMA_VERSION = "market-baseline-v1"`（契约版本，DL-09 切换时升版）
- `MarketStateSnapshot` 日度部分由 `MarketBaseline` 承载（父计划 §4.1 输出契约；盘中部分 DL-15 扩展）

**适配器**（`platform_data/adapters/baseline.py` 新建；公开方法无下划线，登记 `module-boundary.md` §2.3）：

- `DailyBaselineAdapter`：
  - `get_baseline(equ_tickers, *, as_of=None, exclude_dates=None) -> list[MarketBaseline]`：单 ticker 60 个交易窗口（`as_of` 默认数据集中最近交易日）
  - **主源** `bdib_daily_summary`（DL-05 结论：BDIB 主源）：log 量 z（median/MAD）、双口径波动分位、ADV5÷ADV60、隔夜跳空 σ
  - **点查源** `raw_bdib`（每 ticker 每日 1 次点查，遵守「≤100 ticker·日」上限——超限按日期分块并由调用方分批）：开/收盘竞价占比（DL-03 会话注册表竞价窗口）、价差代理（bar 级 (high−low)/close 中位数）
  - `daily_baseline_for_monitor(...)`：批量入口（盘前单/监控板按股票池调用），内部按 100 ticker·日分块
- **纯函数**（同模块，单测覆盖）：
  - `log_volume_z(volumes)`：log 量序列 → (值−median)/(1.4826×MAD)；MAD=0 或 n<20 回落样本 std；序列不足返回 None
  - `percentile_of(value, series)`：分位数（0–100）
  - `overnight_gap_sigma(closes)`：跳空序列 ÷ 跳空 std（σ 倍数）；std=0 → None
  - `auction_share(bars, window)`：窗口内量 ÷ 全日量（DL-03 `ExchangeSession.opening_auction`/`closing_auction`；市场无竞价定义时 None）
  - `spread_proxy(bars)`：bar 级 (high−low)/close 中位数
  - `normalize_volatility(daily_pct, intraday_dec)`：量纲对齐（daily 百分比 / intraday 小数 → 统一百分比；指南 §10 量纲口径）

**端点**（`MarketView/routers/marketview.py` 扩展或新 `routers/baseline.py`；沿用既有 Envelope 风格）：

- `GET /api/marketview/daily-baseline?tickers=...&as_of=...`：返回逐票 `MarketBaseline` + 数据截止日 + 每条特征的 `n_days`/缺失原因

**测试**（`backend/api/tests/test_daily_baseline.py` 新建）：

1. 纯函数：z 值（含 MAD=0 回落、n<20 None）、分位、跳空 σ（std=0 None）、竞价占比（窗口边界/无定义 None）、价差代理、量纲对齐；
2. 集成（tmp 三库夹具：bdib_daily_summary 60 日 + raw_bdib 当日 bar + DL-03 注册表）：`get_baseline` 输出字段完整、z 值与手算一致、特殊日剔除生效、点查分块（>100 ticker·日触发分块路径）；
3. 端点：TestClient + fake adapter 单例（`test_marketview_router.py` 同款模式）——信封字段、缺失 ticker 报告；
4. 与现有 snapshot 抽样对账（用真实数据的既有口径交叉验证——z 值方向与全局常数告警不矛盾）。

**DL-09 切换预留**：适配器内部「主源/点查源」经 `BaselineSource` 协议隔离——DL-09 日快照表就绪后新增实现类切换，`BASELINE_SCHEMA_VERSION` 升版；v0 只用 bdib_daily_summary + raw_bdib 点查。

### 2.3 检验方法（= 验收标准）

1. 与现有 snapshot 抽样对账（z 值口径下既有告警样本的排序一致）；
2. 日内曲线对后 20 日拟合误差报告（v0 交付 ADV/量 z 的稳定性说明；完整日内量曲线在 DL-09）；
3. 核心路径测试覆盖（纯函数 + 集成 + 端点）；
4. `module-boundary.md` §2.3 适配器登记 + ADR 无需（适配器属既有模式，无新决策）；
5. 既有测试不回归（backend + CostView + MarketView 全量，分进程）。

### 2.4 范围裁剪（诚实记录）

- **日内量曲线**（父计划 A 层的「个股日内累计量曲线」）依赖 DL-09 的 `bdib_volume_profile`——v0 只交付竞价占比（点查可得），完整曲线留 DL-09；
- **T−1 临时快照**（DL-08 J2 产物）未就绪——v0 主源为正式 `bdib_daily_summary`，盘中库 T−1 优先级切换在 DL-08 后接入；
- **特殊日剔除清单**（指数调仓日）v0 支持调用方传入 `exclude_dates`，内置清单随 DL-11 事件日历补齐。

## 3. 规模与拆分说明

预估 diff 约 500 行（契约 ~40 + 适配器 ~180 + 纯函数内嵌 + 端点 ~90 + 测试 ~190）。DL-10 为验收原子单元（契约 + 适配器 + 端点一次交付才能被 DL-11/13/14 消费），沿用单 PR 先例。

## 4. 范围锁

| 动作 | 文件 |
|---|---|
| 修改 | `platform_data/contracts/market_contracts.py`（`MarketBaseline` + 版本常量） |
| 修改 | `platform_data/contracts/__init__.py`（导出） |
| 新建 | `platform_data/adapters/baseline.py` |
| 修改 | `platform_data/adapters/__init__.py`（导出） |
| 修改 | `.codebuddy/rules/module-boundary.md` §2.3（适配器登记） |
| 新建 | `MarketView/routers/baseline.py`（或扩展 `marketview.py`） |
| 修改 | `MarketView/main.py`（接线，一行） |
| 新建 | `backend/api/tests/test_daily_baseline.py` |
| 新建 | `MarketView/tests/test_baseline_router.py` |
| 新建 | `specs/066-daily-baseline/plan.md`（本文件） |

范围外（不碰）：`backend/`（除 tests）、`CostView/`、`data_access/`（只读消费不改）、DL-09 快照表切换（预留接口）、盘中状态（DL-15）。

## 5. 验收（P4）

| 需求（057 DL-10 检验方法） | 覆盖 | 结果 |
|---|---|---|
| 与现有 snapshot 抽样对账 | 用例 4 + PR 描述说明 | 待实施后回填 |
| 日内曲线拟合误差报告 | §2.4 裁剪说明 + 稳定性输出 | 待实施后回填 |
| 核心路径测试覆盖 | 用例 1/2/3 | 待实施后回填 |
| 适配器登记 + 无回归 | module-boundary §2.3 + 全量分进程 | 待实施后回填 |

## 6. 本次不做

- DL-09 日快照表与日内量曲线切换（预留 `BaselineSource` 协议）；
- DL-08 盘中库 T−1 临时快照优先级；
- 事件日历与特殊日内置清单（DL-11）；
- 盘前单装配与 handoff v2（DL-14）。
