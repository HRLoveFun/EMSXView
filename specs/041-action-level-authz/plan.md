# 041 — S11：动作级授权（角色权限矩阵 + require_permission 依赖）

> 父计划：`specs/029-trading-reliability-hardening/plan.md`（第三波 · 授权与流程闭环 · S11 / B8）
> 分支：`041-action-level-authz`（worktree `../EMSXView-wt-041-action-level-authz`）
> 依赖：S10（#123）——用户源可配置后，角色由配置驱动

## 1. 问题

报告：「谁可以操作哪个账户、组合、市场和券商？谁可以修改计划？」——当前写路径
端点仅有认证（verify_token）无动作级授权：viewer 角色也能下单、trader 也能改
路由计划。响应三档定位中「多交易员、多账户的机构级平台」的权限层要求。

## 2. 方案（P2 三栏）

- **理论依据**：授权检查必须 fail-closed（未知角色无任何写权限）；权限检查放在依赖注入层（认证之后、业务之前），业务代码零感知。
- **技术方案**：
  - `auth.ROLE_PERMISSIONS`：admin 全权 / trader（trade+modify）/ viewer（view）/**未知角色空集 fail-closed**。
  - `deps.require_permission(*actions)` 依赖工厂：认证之上检查矩阵，无权 403（detail 含动作与角色）。
  - `bypass` 身份升级 role=admin——本地终端操作者全权（既有部署零破坏）。
  - **17 个写路径端点接入**：trade（route/batch-route/confirm/batch-confirm/reject/executions create+command）、modify（modify/cancel/batch-update/routes cancel+modify+batch-modify）、admin（route-plans CRUD + apply）。
- **检验方法**：`test_action_authz.py` 六用例：矩阵语义；未知角色 fail-closed；bypass 全权；require_permission 403；viewer 确认建议被拒（端点集成）；**17 端点接线契约检查**（防回归）。

## 3. 范围锁

- `backend/api/auth.py`（ROLE_PERMISSIONS + user_has_permission）
- `backend/api/deps.py`（require_permission）
- `backend/api/services/auth_service.py`（bypass 身份升级）
- `backend/api/routers/orders_crud.py`、`routes.py`、`route_plans.py`、`orders_execution.py`（写端点接入）
- `backend/api/tests/test_action_authz.py`（新增）、`test_auth_policy.py`（bypass 断言同步）
- `specs/041-action-level-authz/plan.md`（本文件）+ 伞计划 §7 收官登记

账户/组合/市场维度授权需上游 OMS 提供持仓与授权数据，属报告「买方工作流
延伸」的后续演进（权限矩阵已为多维度扩展预留动作词汇表）。

## 4. 验收（P4）

| 需求 | 覆盖 | 结果 |
|---|---|---|
| 谁可以执行哪类动作 | 17 端点按 trade/modify/admin 分级 | CI |
| 未知角色 fail-closed | 矩阵用例 | CI |
| viewer 不可下单 | 端点集成 403 用例 | CI |
| 既有部署零破坏 | bypass 全权 + 既有测试同步 | CI |
| 既有测试不回归 | 274 → 280 passed | CI |
