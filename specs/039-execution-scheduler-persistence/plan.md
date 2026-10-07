# 039 — S9：父子单调度持久化 + 驱动循环 + 成交反馈 + 重启恢复

> 父计划：`specs/029-trading-reliability-hardening/plan.md`（第二波 · 风控与状态真相 · S9 / B5+B9 深化）
> 分支：`039-execution-scheduler-persistence`（worktree `../EMSXView-wt-039-execution-scheduler-persistence`）
> 依赖：S5（#118）、S8（#121）

## 1. 问题

报告指出：「调度器主要管理内存状态和切片计划，没有找到持续驱动切片提交、
接收成交反馈、重启恢复的完整运行链路」——创建时 4 个切片、查询 0 个切片
只是症状，本质是调度器没有真实存储与驱动循环。

## 2. 方案（P2 三栏）

- **理论依据**：调度状态真相源必须是 DB（比进程生命周期长）；切片提交是真实下单路径，驱动循环必须显式接线而非隐式自动；成交反馈以路由 id 反查切片。
- **技术方案**：
  - **repo 扩展**（`parent_child_repository.py`）：`create_parent` / `update_parent_filled` / `list_active_parents`（重启恢复）/ `list_due_slices`（到期提交）/ `get_slice_by_route_id` / `update_slice_fill`。
  - **provider**：`run_parent_child_op(op_name, ...)` 通用会话封装（每调用一事务，DB 不可用返回 None）；`parent_child_available()`。
  - **orders_execution**：`_ProviderRepoAdapter`（duck-type 与 Mock 同接口，调度器零改动）；`persist_parent`（DB 主键锚点，失败回退内存 id + 告警）；`restore_active_executions`（重建 store + 调度器 registry，`register_active_execution` 新增于 algo_scheduler，幂等）。
  - **驱动循环**（`services/execution_driver.py` 新增）：`ExecutionDriver.tick()` 提交到期 PENDING 切片（submit_slice 注入式）；`record_fill(route_id, qty)` 成交回填 + 父单汇总；`run_forever` lifespan 任务。**submit 默认 None——未接线时不提交且 ERROR 可见，绝不静默自动下单**。
  - **成交反馈接线**：订阅引擎路由消息带 `lastShares` 时经 `_dispatch_to_main_loop` 通知回调（S4 主 loop 机制复用）。
  - **开关**：`EXECUTION_DRIVER_ENABLED`（默认 false）——开启驱动循环但 submit 接线仍须显式注入，实盘验证边界见 §4。
- **检验方法**：`test_execution_driver.py` 五用例：到期提交（SENT+route_id）；未接线不提交且 ERROR；未到期/PAUSED 跳过；成交回填（部分→WORKING、足额→FILLED、人工路由 False）；重启恢复（store + registry next_index）。

## 3. 范围锁

- `backend/api/repositories/parent_child_repository.py`、`backend/api/service_provider.py`
- `backend/api/routers/orders_execution.py`、`backend/api/services/algo_scheduler.py`（register_active_execution）
- `backend/api/services/execution_driver.py`（新增）、`backend/api/services/bloomberg/subscriptions.py`（fill 回调）
- `backend/api/config.py`（EXECUTION_DRIVER_ENABLED）、`backend/api/main.py`（恢复 + 驱动任务）
- `backend/api/tests/test_execution_driver.py`（新增）
- `specs/039-execution-scheduler-persistence/plan.md`（本文件）+ 伞计划 §7 收官登记

## 4. 实盘验证边界（与用户确认）

- `submit_slice` 的实盘接线（切片 → RouteEx/algo 单映射）未实现——驱动循环当前**不会真实下单**，须显式接线后启用。
- 成交反馈的订阅侧解析依赖 `lastShares` 字段真实报文形态，实盘验证另行安排。

## 5. 验收（P4）

| 需求（报告） | 覆盖 | 结果 |
|---|---|---|
| 持续驱动切片提交 | tick + 到期提交用例 | CI（离线） |
| 接收成交反馈 | record_fill 三态用例 + 订阅回调接线 | CI |
| 重启恢复 | restore 用例（store + registry） | CI |
| 绝不静默自动下单 | 未接线 ERROR 用例 + 默认关闭开关 | CI |
| 既有测试不回归 | 264 → 269 passed | CI |
