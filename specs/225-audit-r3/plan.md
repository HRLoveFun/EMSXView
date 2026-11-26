# 225 — 审计 R3：A07 父单缺失拒单 + A08 授权查询优化

> 来源：`audit-remediation-2026-10-25.md` **A07（L1）/ A08（L2）**
> 分支：`225-audit-r3`（worktree `../EMSXView-wt-225-audit-r3`，基于 `origin/main`）

## 问题

1. **A07 失败开放**：单笔确认/批量确认的授权闭包在父单不在订阅缓存时 `return None`（跳过检查）；`orders_crud.route_order` 同样把 `None` 交给 pre-trade 检查，等于跳过合规。缓存缺失时本应拒绝并要求刷新订单簿。
2. **A08 全量扫描**：`enforce_for_order` 为构造授权占用明细调用 `load_orders(limit=5000)`，批量预检对每条建议重复加载；授权只需要 `list_active_parents` 涉及的那几个父单投影。

## 方案

- `route_plans.py`：授权闭包父单缺失返回 `{"outcome": "parent_missing"}`；批量预检收集缺失项并整体 **409**。
- `orders_crud.py`：`route_order` 父单缺失 → 审计 fail + **409**（消息含 "subscription cache"）。
- `submission_service.py`：`parent_missing` → 409（`exceeded` 仍 403），状态回滚 `PENDING_CONFIRM`。
- `service_provider.py`：新增 `load_order_payloads_by_ids(order_ids)`，按 `OrderProjection.order_id IN (...)` 精准取投影。
- `authorization_service.py`：`_load_parent_payloads` 优先精准加载（旧 provider/测试替身回落 `load_orders`）；新增 `load_authorization_context`，批量预检一次加载。
- 测试：A07 单笔/批量/route_order 缺失 409；A08 只按父单 id 加载且不调用 `load_orders`，批量预检 `load_authorizations` 仅一次。
- 既有测试夹具补父单缓存与 AsyncMock provider 方法。

## 验收

- `pytest backend/api/tests -q` 全绿（新增用例覆盖 A07/A08）。
- 缺失父单：409 + 可读消息 + 审计 fail；不触达 `route_order`。
- A08：`load_orders` 不再被授权路径调用；批量 N 条预检只加载一次授权上下文。
- `doc_check.py` 退出码 0。

## 范围锁

- `backend/api/routers/route_plans.py`、`orders_crud.py`
- `backend/api/services/submission_service.py`、`authorization_service.py`
- `backend/api/service_provider.py`
- 相关测试与 `specs/057-execution-decision-loop/tasks.md`、本计划

**不做**：不改变 `not_covered` 放行策略；不改授权表结构；不把批量逐条提交的授权检查改为快照（提交时仍需新鲜剩余量）。
