# 031 — S2：`confirm_proposal` 接入 pre-trade 合规，统一风控入口

> 父计划：`specs/029-trading-reliability-hardening/plan.md`（第一波 · 阻断项修复 · S2 / B2）
> 分支：`031-confirm-proposal-compliance`（worktree `../EMSXView-wt-031-confirm-proposal-compliance`）
> 依赖：S1（`specs/030-fix-engine-await-mismatch/plan.md`，已合并 #114）——建议链路可用后方可测确认入口

## 1. 问题

`confirm_proposal`（`route_plans.py`）是事实上的下单入口（调用 `bloomberg.route_order`），
却完全绕过 `compliance_service.check_route`。普通路由入口（`orders_crud.route_order:118`）
有 `USD_NOTIONAL_MAX=49,000,000` 硬拦截，建议确认入口没有——同一笔 5,000 万美元委托，
普通入口被拦、建议确认入口直接提交，本地风控因操作入口不同而失效。

## 2. 方案（P2 三栏）

- **理论依据**：建议确认 = 单笔路由的另一入口，风控必须与 `orders_crud.route_order` 完全同口径，否则存在「合规绕过通道」。
- **技术方案**：在 `confirm_proposal` 的 `try` 块**之前**插入风控块——从订阅缓存取 `parent_order`（与 `orders_crud` 相同的 `_orders` + `_data_lock` 模式），调用 `compliance_service.check_route`；任何 violation（含软告警 `NOTIONAL_TOO_SMALL`，与 `orders_crud` 一律 400 的口径一致）抛 `HTTPException(400, detail={message, violations})`。置于 `try` 之外是关键：`HTTPException` 必须原样传播，不得被现有 `except Exception → "Failed to submit proposal"` 吞掉。订单不在缓存时跳过检查（与 `orders_crud` 同口径）。
- **检验方法**：新增 `test_confirm_proposal_compliance.py` 三用例：超上限拦截且 `route_order` 未被调用；边界值（49,000,000 == max，非 `>`）放行；订单不在缓存时跳过检查直接路由。

## 3. 范围锁

- `backend/api/routers/route_plans.py`（仅 `confirm_proposal` 区块 + 一行导入）
- `backend/api/tests/test_confirm_proposal_compliance.py`（新增）
- `specs/031-confirm-proposal-compliance/plan.md`（本文件）

## 4. 验收（P4）

| 需求 | 覆盖 | 结果 |
|---|---|---|
| 所有单笔下单入口过同一风控 | test_confirm_blocked_above_notional_max | CI |
| 边界口径与 orders_crud 一致 | test_confirm_allowed_at_notional_max | CI |
| 拦截不得触碰下单适配器 | `route_order.assert_not_awaited` | CI |
| 既有测试不回归 | 231 → 234 passed | CI |
