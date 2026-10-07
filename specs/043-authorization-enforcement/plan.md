# 043 — S13：下单入口授权硬校验（exceeded 拒绝 / not_covered 放行并告警）

> 父计划：`specs/029-trading-reliability-hardening/plan.md`（第三波补充 · 买方工作流延伸）
> 分支：`043-authorization-enforcement`（worktree `../EMSXView-wt-043-authorization-enforcement`）
> 依赖：S12（#125，授权数据与剩余量计算）

## 1. 问题

S12 只提供了授权登记与剩余量查询——下单入口尚未消费：报告要求的
「数量与敞口：已成交、在途委托和本次新增合计后，是否超出 PM 授权」
仍无执行点。

## 2. 方案（P2 三栏）

- **理论依据**：授权约束必须在提交前检查且失败处理语义明确——超授权是硬拒绝（403），未登记授权不阻断但必须告警可见（部署方可后续收紧），持久化不可用时跳过（与仓库降级纪律一致）。
- **技术方案**：
  - `authorization_service.enforce_for_order(provider, ...)`：async 包装（组装 intents/parents/payloads → `check_authorization`）；provider 不可用返回 None（跳过）。
  - **挂接点**：`route_order`（orders_crud）与 `confirm_proposal`（route_plans）——compliance 检查之后、下单调用之前；`exceeded` → `HTTPException(403, detail={message, outcome, remainingQuantity, authorizationId})` + 审计 `fail`（confirm 场景回退可重试态）；`not_covered` → `logger.warning` 放行。
- **检验方法**：`test_authorization_enforcement.py` 四用例：exceeded；not_covered；无 provider 跳过；端点集成（route_order 超授权 403 且 `route_order` 适配器未被调用）。

## 3. 范围锁

- `backend/api/services/authorization_service.py`（enforce_for_order）
- `backend/api/routers/orders_crud.py`、`backend/api/routers/route_plans.py`（挂接）
- `backend/api/tests/test_authorization_enforcement.py`（新增）
- `specs/043-authorization-enforcement/plan.md`（本文件）

## 4. 验收（P4）

| 需求 | 覆盖 | 结果 |
|---|---|---|
| 超授权硬拒绝 | 端点集成 403 + 适配器未调用断言 | CI |
| 失败处理语义明确 | 三态分支 + not_covered 告警 | CI |
| 降级不阻断 | 无 provider 跳过用例 | CI |
| 既有测试不回归 | 286 → 290 passed | CI |
