# 079 — DL-15 盘中市场状态（后端 C 层实时特征，特性开关默认关闭）

> 父计划：`specs/057-execution-decision-loop/plan.md`（节点一 · 1d，DL-15）
> 分支：`079-intraday-market-state`（worktree `../EMSXView-wt-079-intraday-market-state`，基线 `53bc1a4`）
> 依赖：DL-10（已完成的 `MarketBaseline` / `DailyBaselineAdapter`）
> 状态：按目标指令直接实施（用户已设定「抵达第一个验收里程碑」目标）

## 1. 问题（是什么）

节点一（交易前实时监控表）覆盖 1a–1d；1a–1c 已完成，1d（DL-15）未开始。现状：
- 行情订阅只有 `CHG_PCT_1D / VOLUME_AVG_5D / VWAP / PX_ROUND_LOT_SIZE` 四个字段，没有 BID/ASK/LAST_PRICE/VOLUME/HIGH/LOW；
- 没有 `MarketStateSnapshot` 契约与服务（C 层实时特征：价差 vs 基线、实际累计量 ÷ 预期曲线、σ 位移、参与率）；
- MonitorBoard 的告警阈值是前端 localStorage 全局常数（`monitor-conditions.ts`），不是服务端统一 z 值。

## 2. 方案（为什么这样做）

按 DL-15 技术方案拆两个子编号交付，控制单 PR 规模：
- **079（本 PR，后端）**：`MarketStateSnapshot` 契约 v1 + 行情订阅扩字段 + 解析入缓存 + 状态服务（价差 bps、相对基线、服务端版本化阈值）+ REST `GET /api/market-state/snapshot` + WS `/ws/market-state`（5s 推送）。全部由 `EMSXVIEW_INTRADAY_STATE_ENABLED` 控制，默认关闭——关闭时订阅字段、现有端点与前端行为均不变。
- **080（后续 PR，前端）**：MonitorBoard 接服务端阈值（替代 localStorage 常数）与 WS 消费；呈现效果按 D-6 与用户打磨。

预期曲线（DL-09）、到达价 σ 位移（DL-12）、参与率（路由缓存）在本期留 `None` 并在契约中预留字段——数据不可得不猜（计划原则），DL-09/12 落地后回填。

## 3. 落地（范围锁）

| # | 文件 | 类型 | 内容 |
|---|---|---|---|
| 1 | `platform_data/contracts/market_contracts.py` | 改 | `MarketStateThresholds / MarketStateFlag / MarketStateTickerState / MarketStateSnapshot`（`market-state-v1`） |
| 2 | `platform_data/contracts/__init__.py` | 改 | 导出新增契约 |
| 3 | `backend/api/config.py` | 改 | `EMSXVIEW_INTRADAY_STATE_ENABLED`（默认 false） |
| 4 | `backend/api/services/bloomberg/enrichment.py` | 改 | `mktdata_fields()` / `parse_intraday_quote()` 纯函数；`_intraday_quotes` 缓存；开关开启时订阅与解析 |
| 5 | `backend/api/services/market_state_service.py` | 新增 | 快照构建 + 服务端阈值（`thresholds-v1`） |
| 6 | `backend/api/routers/market_state.py` | 新增 | REST + WS 端点 |
| 7 | `backend/api/services/realtime_gateway.py` | 改 | `broadcast_market_state` |
| 8 | `backend/api/main.py` | 改 | 挂载路由 |
| 9 | `backend/api/tests/test_market_state_service.py` | 新增 | 服务与解析单测 |
| 10 | `backend/api/tests/test_market_state_endpoint.py` | 新增 | 端点开关两态 + 鉴权 |

预估约 +650 行（含测试）。

## 4. 验收（P4，取自 DL-15 检验方法）

1. 字段解析单测：`parse_intraday_quote` 对缺失/异常字段不抛错、只取存在的字段；
2. 开关关闭：`mktdata_fields(False)` 与现状一致；`GET /api/market-state/snapshot` 返回 `enabled:false`，现有端点与订阅行为不变（全量测试回归）；
3. 开关开启：订阅字段含六个新字段；快照含逐票 spread_bps 与相对基线差值；超阈值产生版本化 flag（thresholds-v1）；
4. WS：连接后按 5s 推送 `market_state` 事件；断连清理；
5. 推送延迟与丢包观测、阈值变更审计属部署期观测项（交易机），记录于 PR 描述的已知限制。

## 5. 已知限制

- `cumulative_volume_ratio` / `price_sigma_vs_arrival` / 参与率本期为 `None`（DL-09/DL-12 未就绪）；
- 前端消费与 MonitorBoard 服务端阈值在 080；
- 呈现效果定稿需用户反馈（D-6）。
