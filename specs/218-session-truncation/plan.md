# 218 — 订阅会话过滤与优先级截断（DL-31 补全）

> 父计划：`specs/057-execution-decision-loop` 的 **DL-31**（指数成分股池与订阅范围）
> 分支：`218-session-truncation`（worktree `../EMSXView-wt-218-session-truncation`，基于 `origin/main`）
> 依赖：DL-03（会话注册表）、DL-15、DL-29 —— 均已完成
> 说明：DL-31 的池契约、配置池 `dev-validation`、市场码规范化与 `subscribe_tickers` 下发已由 100 交付；本 PR 补 **会话窗口过滤** 与 **订阅截断** 两处缺口。指数成分股表仍待管道。

---

## 1. 问题

`POST /api/market-state/subscribe` 目前把池成员**无条件**加入额外 mktdata 订阅：

1. 已收盘/远离开盘的池成员也订阅，浪费额度；
2. 超过 `EMSXVIEW_MKTDATA_MAX_EXTRA_TICKERS` 时按到达顺序拒绝，**不按异常严重度/池权重截断**，也不返回 `subscription_truncated`，属静默丢。

---

## 2. 方案（P2 三栏）

### S1 · 会话窗口过滤

- **理论依据**：池成员只在「会话 open 或距开盘 ≤60 分钟」时订阅才有实时意义；未注册市场不得静默丢弃。
- **技术方案**：新模块 `backend/api/services/market_session.py`：
  - `exchange_for_ticker`：`GY→GR`、`CH→C1`，其余用 ticker 后缀；
  - `is_session_open_or_soon(ticker, now_utc, lead_minutes=60)`：`ExchangeSessionAdapter` + `ZoneInfo(session.timezone)`；未注册 → True（保留）；周末 → False；时刻不可解析 → True（保守保留）。
  - `enrichment._add_mktdata_tickers` 在加入前过滤，统计 `session_filtered` / `session_filtered_tickers`。
- **检验方法**：US/JP 的 open/soon/closed、周末、未知市场、GY/CH 别名；纯函数固定 `now`。

### S2 · 优先级截断与披露

- **理论依据**：额度不足时按「异常严重度 → 池权重 → ticker」接受，结果必须可见。
- **技术方案**：
  - `add_mktdata_tickers_with_stats(tickers, now=, priorities=)`：候选按 `(-severity, -weight, ticker)` 排序；超过 `EMSXVIEW_MKTDATA_MAX_EXTRA_TICKERS` 的计入 `rejected`，返回 `subscription_truncated=true` 与 `limit`；
  - 保留原 `add_mktdata_tickers` 三元组签名（向后兼容）；
  - 端点 `SubscribeRequest` 增加可选 `priorities`；响应加 `session_filtered`、`subscription_truncated`（旧 facade 替身走兼容分支）。
- **检验方法**：limit=1 时 severity 高者被接受、低者 rejected 且 flag=true；会话过滤与截断互不混淆；既有 4 个订阅测试不回归。

---

## 3. 范围锁

- `backend/api/services/market_session.py`（新增）
- `backend/api/services/bloomberg/enrichment.py`（过滤/截断）
- `backend/api/services/bloomberg/adapter.py`（代理）
- `backend/api/routers/market_state.py`（请求/响应字段）
- 测试：`backend/api/tests/test_market_session.py`（新增）、`test_market_state_subscribe.py`（扩展）
- `docs/api-contracts.md`、`specs/057-execution-decision-loop/tasks.md`

**不做**：不改池契约/配置池（100 已交付）；指数成分股表（管道依赖）不在本 PR；不改下单路径。

---

## 4. 验收（P4）

1. 会话过滤：open/soon 接受、closed/周末拒绝、未知市场保留，`session_filtered` 计数可见。
2. 截断：超限按严重度/权重/ticker 接受，`subscription_truncated=true`，不静默丢。
3. 回归：`pytest backend/api/tests -q` 全绿；`python scripts/doc_check.py` 退出码 0。
4. DL-31 状态更新为「部分完成（100 + 218；指数成分股表待管道）」。

---

## 5. 风险

- 交易所周末/假日：注册表不含假日，按 Mon–Fri + 会话窗口判定；假日多订阅一档池成员，不影响正确性。
- 优先级元数据：前端当前不传 `priorities`，此时按 ticker 稳定排序；后续由 MarketView 池响应补齐 severity/weight。
