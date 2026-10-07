# 032 — S3：`confirm_proposal` 并发幂等（per-proposal 锁 + CONFIRMING 中间态）

> 父计划：`specs/029-trading-reliability-hardening/plan.md`（第一波 · 阻断项修复 · S3 / B3）
> 分支：`032-confirm-proposal-idempotent`（worktree `../EMSXView-wt-032-confirm-proposal-idempotent`）
> 依赖：S2（#115 已合并）——风控块随本改造移入锁内

## 1. 问题

`confirm_proposal` 的状态检查（L394）与状态更新（L411）之间存在 `await route_order`，
check-then-act 非原子：并发两次确认同一 PENDING_CONFIRM 建议，均可通过检查并各自
调用下单适配器 → 重复委托风险。

## 2. 方案（P2 三栏）

- **理论依据**：跨 await 的读-改-写必须用锁保护，且在 await 前先置中间态，使「锁外观察者」与「后续持锁者」都能看到非 PENDING_CONFIRM 状态。
- **技术方案**：
  - 模块级 `_confirm_locks: dict[int, asyncio.Lock]`，per-proposal 互斥；**不 pop 清理**（随 proposal 生命周期保留，避免「pop 后第三者新建锁」竞态）。
  - 锁内：重读 proposal → `CONFIRMING` 给 409（防御崩溃遗留中间态）→ 非 `PENDING_CONFIRM` 给 400 → 置 `CONFIRMING` → 风控 → 提交 → `SUBMITTED`。
  - 风控拦截（400）与提交异常均回退 `PENDING_CONFIRM`（可重试）；「响应丢失 = 结果未知」的完整语义属第二波 S7，已在代码注释与本计划明示。
  - `reject_proposal` 对 `CONFIRMING` 返回 409，防止并发 reject 覆盖中间态。
- **检验方法**：`test_confirm_proposal_concurrency.py` 四用例：`asyncio.gather` 并发确认恰一次 `route_order`；提交失败回退后重试成功；风控拦截回退且异常传播；遗留 `CONFIRMING` 态 confirm/reject 均 409。

## 3. 范围锁

- `backend/api/routers/route_plans.py`（`confirm_proposal` 重构、`reject_proposal` 防御、锁字典、asyncio 导入）
- `backend/api/tests/test_confirm_proposal_concurrency.py`（新增）
- `specs/032-confirm-proposal-idempotent/plan.md`（本文件）

## 4. 验收（P4）

| 需求 | 覆盖 | 结果 |
|---|---|---|
| 重复操作只产生一次有效提交 | test_concurrent_confirm_single_submission（`route_order.assert_awaited_once`） | CI |
| 失败可安全重试 | test_confirm_retries_after_submission_failure / after_compliance_block | CI |
| 中间态不可被并发破坏 | test_confirm_conflicting_state_returns_409 | CI |
| S1/S2 行为不回归 | 既有 8 用例 + 全量 pytest（234 → 238） | CI |
