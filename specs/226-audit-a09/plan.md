# 226 — 审计 A09：locale 显式化 + 每日确认时区 + token-service 合并

> 来源：`audit-remediation-2026-10-25.md` **A09（L3）**
> 分支：`226-audit-a09`（worktree `../EMSXView-wt-226-audit-a09`，基于 `origin/main`）

## 问题

1. MarketView 的数字格式化使用 `toLocaleString(undefined)` / `Intl.NumberFormat(undefined)`，输出随浏览器 locale 漂移；导出时间也无显式 locale。
2. `needs_daily_confirmation` 用 `datetime.now()`（隐式本机时区），部署时区变化会让 08:00 口径漂移，且无决策记录。
3. `frontend/src/shared/services/handoff-api.ts` 重复实现 `TOKEN_KEY` + `localStorage` 读 token，与 `token-service.ts` 两份真相。

## 方案

- `MarketView/module/marketview-utils.tsx`、`lib/workspace.ts`：显式 `'en-US'`。
- `export-orders-panel.tsx` / `summary-cards.tsx`：`toLocaleString('en-US')`。
- `access_policy_service.py`：新增 `DAILY_CONFIRM_TIMEZONE = ZoneInfo("Asia/Hong_Kong")`；aware datetime 先换算到该时区，naive 视作该时区本地时间（兼容既有调用与测试）。
- `handoff-api.ts`：删除本地 `TOKEN_KEY`，改用 `token-service.getToken()` 单一来源。

## 验收

- `pytest backend/api/tests/test_access_policy.py -q` 通过（新增 UTC→HK 边界两例）。
- `tsc -b frontend` 通过；MarketView 格式化测试在任意 locale 下稳定。
- `python scripts/doc_check.py` 退出码 0。

## 决策记录

每日确认的「当日」按 **Asia/Hong_Kong** 界定。理由：交易机与后端部署在香港，交易员按港时上班；改用交易所本地日会让同一次确认在不同市场日切时重复弹窗。若未来迁移部署时区，改常量并同步用例。

## 范围锁

- `MarketView/module/marketview-utils.tsx`、`lib/workspace.ts`、`components/export-orders-panel.tsx`、`components/summary-cards.tsx`
- `backend/api/services/access_policy_service.py`、`backend/api/tests/test_access_policy.py`
- `frontend/src/shared/services/handoff-api.ts`
- `specs/057-execution-decision-loop/tasks.md`、本计划
