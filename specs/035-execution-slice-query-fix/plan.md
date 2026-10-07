# 035 — S5：父子单执行切片查询修复（模块级切片存储 + MOCK 显式标记）

> 父计划：`specs/029-trading-reliability-hardening/plan.md`（第一波 · 阻断项修复 · S5 / B5）
> 分支：`035-execution-slice-query-fix`（worktree `../EMSXView-wt-035-execution-slice-query-fix`）

## 1. 问题

`orders_execution.py` 的 `_MockParentChildRepo` 把切片存在**实例本地** `self._slices`：
`create_parent_execution`（`:164`）新建 repo 实例写入 4 个切片，`get_parent_execution`
（`:218`）**再新建**实例查询 → 切片列表为空，`get_execution_state` 返回
`totalSlices=0` 但父单状态仍 ACTIVE/RUNNING——「执行已启动」不能证明任何真实执行。

## 2. 方案（P2 三栏）

- **理论依据**：跨请求共享的状态必须存于比请求生命周期更长的载体；同时按报告要求，模拟实现必须显式标记、不得让配置开启造成「已持久化」的错觉。
- **技术方案**：
  - 新增模块级 `_slices_store: dict[int, list]`（按 parent_id 分桶）与全局 `_slice_id_counter`；`_MockParentChildRepo` 的 create/list/update 改读写共享桶，跨实例/请求一致。
  - 类 docstring 显式标记 `MOCK — 非生产实现`，指明真实实现属 029 第二波 S9。
  - `create_parent_execution` 在 `settings.ENABLE_DB_PERSISTENCE=true` 时 `logger.warning`（配置声称持久化但实际用内存仓库——第一波仅告警不阻断，避免破坏既有部署）。
  - `algo_scheduler` 契约不变（`slice_dicts` 已含 `parent_id`，L116），调度器零改动。
- **检验方法**：`test_execution_slice_query.py` 四用例：create→get 切片数一致且 ACTIVE；新建 repo 实例查询切片可见且 id 全局唯一；多 parent 切片分桶隔离；持久化开启时告警可见。

## 3. 范围锁

- `backend/api/routers/orders_execution.py`（repo 类 + 告警 + 导入）
- `backend/api/tests/test_execution_slice_query.py`（新增）
- `specs/035-execution-slice-query-fix/plan.md`（本文件）
- `specs/029-trading-reliability-hardening/plan.md`（§7 登记表更新——第一波收官）

## 4. 验收（P4）

| 需求 | 覆盖 | 结果 |
|---|---|---|
| 调度状态可查询（切片一致） | test_create_then_query_returns_same_slices | CI |
| 切片跨实例/请求可见 | test_query_across_new_repo_instance | CI |
| 多 parent 隔离 | test_multiple_parents_slices_isolated | CI |
| 配置与实现不符可观测 | test_mock_repo_warns_when_persistence_enabled | CI |
| 既有测试不回归 | 243 → 247 passed | CI |
