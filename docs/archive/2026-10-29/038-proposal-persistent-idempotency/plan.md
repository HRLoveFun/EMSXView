# 038 — S8：建议持久化幂等键（write-through + 重启恢复）

> 父计划：`specs/029-trading-reliability-hardening/plan.md`（第二波 · 风控与状态真相 · S8 / B3 深化）
> 分支：`038-proposal-persistent-idempotency`（worktree `../EMSXView-wt-038-proposal-persistent-idempotency`）
> 依赖：S3（#116，进程内幂等）——本任务把幂等性延伸到「跨重启」

## 1. 问题

建议（proposal）及其确认状态机全部存内存 dict，重启即失：进程重启后无法知道
某建议已提交——报告要求「每次交易操作有持久化的唯一标识，重复点击、网络重试
和进程重启能够关联到同一操作」。S3 解决了进程内并发，本任务补跨重启幂等。

## 2. 方案（P2 三栏）

- **理论依据**：幂等键必须比进程生命周期长——`SubOrderProposal` 数据库主键是唯一候选；确认状态迁移必须先落库再应答，否则「应答成功 + 落库失败」会在恢复后产生重复确认窗口。
- **技术方案**：
  - `repositories/proposal.py`（新增）：`create_many`（INSERT 取主键）/`update_result`（按主键回写状态）/`load_all`；内存 ISO 字符串 ↔ 模型 datetime 转换。
  - `RepositoryProvider`：`persist_proposals_bulk` / `update_proposal_result` / `load_proposals`（模型 → 内存 dict 形态）；失败降级路径全部可见（warning/error）。
  - `route_plans.py`：`_create_proposals` 改 async——persist 成功用 DB 主键为 id，失败回退内存自增（回退时 warning：该批建议重启不可恢复）；confirm/reject 经 `_persist_proposal_result` **先落库再应答**；`init_proposals_from_db` 启动恢复（DB 状态为真相源）。
  - `main.py` lifespan：DB ready 后调用恢复。
  - `deps.get_repo_provider()` 访问器——模块级内存缓存无法走 Depends。
- **检验方法**：`test_proposal_persistence.py` 五用例：创建落库且 id 一致；确认 write-through；模拟重启恢复 + 已 SUBMITTED 拒绝重复确认（幂等核心）；无 provider 回退内存 id；拒绝落库。

## 3. 范围锁

- `backend/api/repositories/proposal.py`（新增）
- `backend/api/service_provider.py`（三方法 + `_iso`）
- `backend/api/deps.py`（get_repo_provider 访问器）
- `backend/api/routers/route_plans.py`（_create_proposals/_persist_proposal_result/init_proposals_from_db + confirm/reject 接入）
- `backend/api/main.py`（lifespan 恢复调用）
- `backend/api/tests/test_proposal_persistence.py`（新增）
- `specs/038-proposal-persistent-idempotency/plan.md`（本文件）

## 4. 验收（P4）

| 需求 | 覆盖 | 结果 |
|---|---|---|
| 交易操作有持久化唯一标识 | DB 主键幂等键 + 用例断言 | CI |
| 进程重启能关联同一操作 | test_restart_recovery_and_duplicate_confirm_rejected | CI |
| 状态迁移先落库再应答 | confirm/reject write-through 用例 | CI |
| 持久化不可用不破坏现状 | test_fallback_to_inmemory_id_without_provider | CI |
| 既有测试不回归 | 259 → 264 passed | CI |
