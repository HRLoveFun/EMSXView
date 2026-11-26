# 228 — A14 第二批：handoff publish 参数对象化

> 来源：`audit-remediation-2026-10-25.md` **A14（E5）** Top 2
> 分支：`228-a14-handoff`（worktree `../EMSXView-wt-228-a14-handoff`，基于 `origin/main`）

## 问题

`platform_data/adapters/handoff.py` 与 `redis_handoff.py` 的两个 publish 方法分别有 **10 / 12 个关键字参数**（质量门禁 OE-05 阈值 7），调用方需要重复拼装同一组字段，易错且难扩展。

## 方案

- 在 `platform_data/contracts/handoff_contracts.py` 新增两个 frozen dataclass：
  - `ExecutionToCostHandoffRequest`（order_id / parent_execution_id / broker / strategy / asset_class / urgency / route_ids / strategy_params / candidate_trace_id / origin_trace_id）
  - `CostToExecutionHandoffRequest`（cohort / asset_class / broker / strategy / urgency / sample_size / arrival_bps / implementation_bps / severity / rationale / source_report_trace_id / origin_trace_id）
- 两个 adapter 的方法签名改为 `publish_xxx(request)`；内存与 Redis 行为保持一致。
- **顺带修复**：Redis 适配器此前未写入 `candidate_trace_id`，与内存适配器不一致；本次统一透传。
- 更新调用方与测试：`orders_handoff` 路由、CostView `pin` 路由、三份 handoff 测试。

## 验收

- 质量门禁：`redis_handoff.py` / `handoff.py` 不再出现参数个数 OE-05。
- `pytest backend/api/tests`、CostView、MarketView 全绿；handoff 三份测试 14 passed。
- `doc_check.py` 退出码 0。

## 边界

A14 仍余前端三件套（RouteTable 858 行等）拆分，排第三批；本轮不改任何 handoff 报文结构或字段语义。
