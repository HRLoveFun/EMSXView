# 030 — S1：修复 `_engine_repo` await 不匹配，打通计划→建议链路

> 父计划：`specs/029-trading-reliability-hardening/plan.md`（第一波 · 阻断项修复 · S1 / B1）
> 分支：`030-fix-engine-await-mismatch`（worktree `../EMSXView-wt-030-fix-engine-await-mismatch`）

## 1. 问题

`route_plans.py` 的 `_engine_repo` 用 `staticmethod(lambda)` 提供五个仓库方法（普通函数），
而 `route_engine.py` 对全部五个方法执行 `await`（`:346/:352/:368/:388`）→ 首次调用即抛
`TypeError: object dict can't be used in 'await' expression`，被 `apply_route_engine` 的
`except` 吞成通用错误（success=False），整条「路由计划 → 生成建议」链路不可用。

连带缺陷（修复 await 后即暴露）：`get_allocations_for_plan` 返回内存 dict 列表，
引擎按属性访问 `a.allocation_type`；`get_plan` 返回 dict，`match_plans` 访问
`plan.priority` 并对 `plan.created_at`（ISO 字符串）调 `.timestamp()`。

## 2. 方案（P2 三栏）

- **理论依据**：引擎契约要求 repo 方法为协程且返回模型对象（属性访问）；仓库侧补齐契约比改引擎（会影响未来真实异步 repo）更局部、更安全。
- **技术方案**：`_EngineRepo` 改为普通类，五方法 `async def`；新增 `_plan_dict_to_model` / `_alloc_dict_to_model` 把内存 dict 转为 SQLAlchemy `RoutePlan` / `RoutePlanAllocation`（ISO 时间 → datetime，allocation 过滤 model_dump 残留的 camelCase 键）；模块级单例 `_engine_repo = _EngineRepo()`，两处 `RouteEngine(_engine_repo)` 调用点零改动。
- **检验方法**：新增 `backend/api/tests/test_route_engine_apply.py` 五用例（TIME_SCHEDULE 切片数、BROKER_SPLIT 百分比切分、自动匹配、建议入列、订单缺失 404）。

## 3. 范围锁

- `backend/api/routers/route_plans.py`（仅 `_engine_repo` 区块 + 导入）
- `backend/api/tests/test_route_engine_apply.py`（新增）
- `specs/029-trading-reliability-hardening/plan.md`（父伞计划文档，随本 PR 入库）
- `specs/030-fix-engine-await-mismatch/plan.md`（本文件）

`route_engine.py` 不改一行。

## 4. 验收（P4）

| 需求 | 覆盖 | 结果 |
|---|---|---|
| apply 端点返回真实建议 | test_apply_time_schedule / broker_split / auto_match | CI |
| 建议状态 PENDING_CONFIRM 且可列出 | test_generated_proposals_listed | CI |
| 引擎零改动、契约闭合 | diff 无 route_engine.py | 评审 |
| 既有测试不回归 | 全量 pytest | CI |
