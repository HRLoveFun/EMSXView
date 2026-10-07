# 034 — S4：订阅线程持久化/推送修复（主 loop 注入 + 失败可见化）

> 父计划：`specs/029-trading-reliability-hardening/plan.md`（第一波 · 阻断项修复 · S4 / B4）
> 分支：`034-subscription-persist-loop-fix`（worktree `../EMSXView-wt-034-subscription-persist-loop-fix`）

## 1. 问题

`EMSXSubscriptionEngine` 的 `_schedule_persist_order` / `_schedule_persist_route`
（及订单/路由删除广播）逐次调用 `asyncio.get_event_loop()` 取主循环。blpapi SDK
回调线程中该调用抛 `RuntimeError`，被 `except RuntimeError: pass` **静默吞掉**：
DB 写与 WebSocket 广播整体跳过、无任何日志。前端轮询掩盖推送失效；持久化能力
不能仅凭配置开启来判断。

## 2. 方案（P2 三栏）

- **理论依据**：后台线程没有事件循环，跨线程调度协程必须持有主 loop 引用（lifespan startup 时注入一次），而非逐次探测；静默丢弃持久化属于「状态语义说谎」，必须 ERROR 可见化。
- **技术方案**：
  - 引擎新增 `_main_loop` + `set_main_loop()`；统一 `_dispatch_to_main_loop(coro)`：未注入或已关闭 → `logger.error` 并 `coro.close()`；否则 `run_coroutine_threadsafe` + `add_done_callback` 记录协程执行异常（此前 persist/broadcast 失败完全静默）。
  - 四个调用点（订单删除广播、路由删除广播、`_schedule_persist_order/_route`）全部改走 dispatch。
  - `BloombergEMSXService.set_main_loop` 代理；`main.py` lifespan startup 注入 `asyncio.get_running_loop()`。
- **检验方法**：`test_subscription_persist_thread.py` 五用例：主 loop 注入后 order/route 持久化与广播执行；**真实后台线程**调用仍回主 loop；未注入 loop 时 ERROR 且不执行；协程执行失败记 ERROR。

## 3. 范围锁

- `backend/api/services/bloomberg/subscriptions.py`（dispatch 方法 + 四调用点）
- `backend/api/services/bloomberg/adapter.py`（set_main_loop 代理）
- `backend/api/main.py`（lifespan 注入一行）
- `backend/api/tests/test_subscription_persist_thread.py`（新增）
- `specs/034-subscription-persist-loop-fix/plan.md`（本文件）

## 4. 验收（P4）

| 需求 | 覆盖 | 结果 |
|---|---|---|
| 订阅事件能落库 | test_persist_dispatched_to_injected_loop / test_route_persist… | CI |
| 订阅事件能推送 | broadcast 断言 + 后台线程用例 | CI |
| 失败不再静默 | test_missing_loop_logs_error / test_dispatch_failure_is_visible | CI |
| 既有测试不回归 | 238 → 243 passed | CI |
