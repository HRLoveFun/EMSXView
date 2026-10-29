# 036 — S6：审计结果真实化（两阶段审计：PENDING → ok/fail/unknown）

> 父计划：`specs/029-trading-reliability-hardening/plan.md`（第二波 · 风控与状态真相 · S6 / B6）
> 分支：`036-audit-result-truthful`（worktree `../EMSXView-wt-036-audit-result-truthful`）

## 1. 问题

`deps.audit_log` 在操作**发生前**记录事件且 `result` 硬编码 `"ok"`（`deps.py:72`）：
操作尚未执行就宣称成功，数据库审计无法表达最终是否成功——报告批评「能留下
有人发起操作的痕迹，却不能可靠表达最终是否成功」。

## 2. 方案（P2 三栏）

- **理论依据**：审计语义必须诚实——操作发起时唯一真实的结论是「尚未完成」（PENDING）；最终结果只有操作结束后才知道，须按关联 ID 回填；超时（504）的结果是「未知」而非失败。
- **技术方案**：
  - `audit_log` 增加 `result="PENDING"` / `correlation_id` 参数（默认值变化：所有未接入回填的入口自动从「假 ok」变为「诚实的 PENDING」）。
  - 新增 `audit_result(correlation_id, result)` → `RepositoryProvider.update_audit_result` → `AuditEventRepository.update_result_by_correlation_id`（SQL UPDATE by correlation_id）。
  - 结果词汇表：`ok`（成功）/ `fail`（明确失败）/ `unknown`（超时 504——券商可能已收到订单）/ `PENDING`（发起，未终态）。
  - 关键下单入口接入：`confirm_proposal`（route_plans）与 `route_order`（orders_crud）——成功 ok、风控拦截 fail、504 unknown、其他异常 fail。
- **检验方法**：`test_audit_result_truthful.py` 五用例：默认 PENDING；回填关联；confirm 成功流 PENDING→ok；route_order 504→unknown；风控拦截→fail。

## 3. 范围锁

- `backend/api/deps.py`（audit_log 两阶段化 + audit_result）
- `backend/api/service_provider.py`（update_audit_result）
- `backend/api/repositories/audit.py`（update_result_by_correlation_id）
- `backend/api/routers/route_plans.py`（confirm_proposal 审计接入）
- `backend/api/routers/orders_crud.py`（route_order 审计接入）
- `backend/api/tests/test_audit_result_truthful.py`（新增）
- `specs/036-audit-result-truthful/plan.md`（本文件）

其余 23 处 audit_log 调用点（查询/配置类操作）本次仅受益于默认 PENDING 语义，
逐入口接入回填按风险优先级另行推进（登记于伞计划）。

## 4. 验收（P4）

| 需求 | 覆盖 | 结果 |
|---|---|---|
| 审计能区分 ok/fail/unknown | 五用例 | CI |
| 发起不再预写 ok | 默认 PENDING 断言 | CI |
| 关联可追溯 | correlation_id 贯穿 persist/update | CI |
| 既有测试不回归 | 247 → 252 passed | CI |
