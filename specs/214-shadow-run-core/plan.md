# 214 — DL-22 影子运行核心（PR 1）

> 父计划：`specs/057-execution-decision-loop` 的 **DL-22**（2b 影子模式与周报）
> 分支：`214-shadow-run-core`（worktree `../EMSXView-wt-214-shadow-run-core`，基于 `origin/main`）
> 依赖：DL-13、DL-21（075 已交付）、A02；实现成本对照用 DL-19/DL-20 —— 均已完成
> 拆分：本 PR 只做**影子运行核心**（触发、决策增强、实际路由关联、约束检查、覆盖率）；**周报 + 并排 UI 拆到 215**
> 关联规范：`docs/spec/plan-design-principles.md`（P2/P4）、`docs/spec/attribution-pitfalls.md`、`docs/archive/2026-10-29/075-routing-decision-log/plan.md`

---

## 1. 问题

075 只解决了「**交易员主动调用引擎时**记录影子决策」。DL-22 要求 2b 影子运行：

1. **每个路由订单**（有路由行为的订单）都要有决策记录，而不是只在 `apply_route_engine` 被调用时；
2. 记录**决策时点上下文**：意图、来源（MANUAL/PLAN/ENGINE）、决策时点报价价差、逐项约束结果；
3. 从**路由订阅**捕获交易员的实际选择，关联到决策并回填 `route_ids`（实际券商/数量/参数）；
4. 记录**改写原因**（实际 vs 建议的差异），为周报的「改写率与原因分布」提供数据；
5. 建议单**零硬约束违例**（复用 A02 `pre_trade_checks`），并披露覆盖率。

现状：`RoutingDecisionRecord` 只有候选集/四版本号；无实际路由、无报价价差、无约束结果、无覆盖率；路由订阅只有 fill 回调，没有 route/order 回调。

---

## 2. 方案（P2 三栏）

### S1 · 影子运行触发（每个路由订单）

- **理论依据**：影子运行的样本必须是「实际发生的路由订单」，而不是交易员是否点了引擎。触发点应在上游订单/路由事件，且**不改下单入口**（D-3）。
- **技术方案**：
  - 在 `backend/api/services/bloomberg/subscriptions.py` 增加 `register_order_callback(cb)` 与 `register_route_callback(cb)`（与既有 fill/resync 回调同模式；`_dispatch_to_main_loop` 投递到主循环）。
  - 新服务 `backend/api/services/shadow_run_service.py`：
    - `on_order(order)`：仅处理“路由订单”（有活跃 route plan 或能匹配到 auto plan；无 plan 时写 `ENGINE_DEFAULT` 的**无建议**记录（不臆造计划），覆盖率披露）；按 `(order_id, symbol, side, remainingQuantity)` 去重，避免 INIT_PAINT/UPDATE 重复触发；调用 `RouteEngine.generate_proposals` 的**只读变体**（不落 proposal 表）生成建议；逐提案跑 `pre_trade_checks`；组装增强决策并 `record_decision`。
    - `on_route(route)`：按 `order_id` 取最新决策，追加实际路由（broker、quantity、price、params、status、route_id），回填 `route_ids`；只对“新路由/关键字段变化”更新，避免高频 UPDATE 刷写。
    - 失败一律 `try/except` + 日志，**不阻断**订单/路由主流程。
  - 开关 `EMSXVIEW_SHADOW_RUN_ENABLED`（默认关闭，G2）；关闭时零副作用。
- **检验方法**：单测：order 事件触发一次决策；重复/UPDATE 不重复；无 plan → 默认计划且 `source=ENGINE_DEFAULT`；路由主流程无异常；开关关闭时不写库。

### S2 · 决策增强（契约 v2 + 约束结果 + 报价价差）

- **理论依据**：决策日志必须自证「在什么状态下、按什么约束、为什么这么分」；否则周报无法归因。
- **技术方案**：
  - `platform_data/contracts/routing_decision.py`（`DECISION_SCHEMA_VERSION` → **`routing-decision-v2`**，新增字段全部可选默认，向后兼容）：
    - `RoutingDecision`：`intent`、`intent_source`、`source`（MANUAL/PLAN/ENGINE/ENGINE_DEFAULT）、`quote_spread_bps`、`market_state`（dict）、`constraint_violations`（tuple）、`actual_routes`（tuple）、`rewrite_reason`、`updated_at`；
    - `DecisionCandidate`：`quote_spread_bps`、`estimated_cost_bps`（如可得）。
  - `decision_log_service.build_shadow_decision` 接受 `context`（意图/来源/价差/约束结果）；`record_decision` 写 v2 payload；`RoutingDecisionRecord` 增加 `source`（index）、`updated_at`（可空）列，payload 保留全量；075 的不可变语义对 `actual_routes/rewrite_reason/updated_at` 例外（只追加/更新这几个字段），在注释与文档中显式说明。
  - 报价价差：通过 `bloomberg` 的 quote 缓存/`pre_trade_checks` 同源接口取 `best_bid/best_ask`；不可得 → `None` 并披露。
- **检验方法**：契约字段默认值/序列化；v1 payload 仍可读；报价价差缺失不抛错；约束结果结构（code/severity）与 `pre_trade_checks` 一致。

### S3 · 实际路由关联与改写原因

- **理论依据**：周报的「一致率 / 改写率 / 原因分布」必须基于同一订单的建议与实际；关联键只能是 `order_id`（路由订阅的 `EMSX_SEQUENCE`）。
- **技术方案**：
  - `on_route` 追加实际路由并回填 `route_ids`；同一 `route_id` 更新则替换对应项。
  - 改写原因：若实际与建议的 broker/quantity/params 不一致，按可判定规则打码：`BROKER_CHANGED` / `QUANTITY_CHANGED` / `PARAMS_CHANGED` / `EXTRA_ROUTE` / `UNCLASSIFIED`；原因是**事后归类**，不臆造交易员主观原因（AT 红线）。
  - 覆盖率端点：`GET /api/routing-decisions/coverage?start=&end=` 返回订单数/决策数/覆盖率、按来源分布、硬约束违例数、实际关联数；只读。
- **检验方法**：合成 order→decision→route 事件：建议 A/B，实际 A/C → 关联成功、`route_ids` 回填、改写原因 `BROKER_CHANGED`；重复 route 事件不重复追加；无决策的 route 忽略。

### S4 · 约束检查与零硬违例

- **理论依据**：影子建议若违反硬约束，说明引擎/参数有问题；必须在写库前发现并计数。
- **技术方案**：S1 的 `on_order` 对每个 proposal 调用 A02 `pre_trade_checks(order, proposal, bloomberg)`；`severity=hard` 计入 `constraint_violations`，周报目标为 0；检查异常不阻断决策写入，记 `check_error` 并在覆盖率披露。
- **检验方法**：mock `pre_trade_checks` 返回硬违例 → 决策记录包含违例且 `coverage.hard_violations` 计数 +1；返回异常 → 决策仍写入、`check_error` 可见。

---

## 3. 范围锁

- `platform_data/contracts/routing_decision.py`（v2 字段）
- `backend/api/models/execution_state.py`（`source`/`updated_at` 列）
- `backend/api/services/decision_log_service.py`（context / 增强 payload / 更新实际路由）
- `backend/api/services/shadow_run_service.py`（新增）
- `backend/api/services/bloomberg/subscriptions.py`（order/route 回调）
- `backend/api/services/route_engine.py`（只读提案生成入口；不改现有 `apply_route_engine` 行为）
- `backend/api/routers/routing_decisions.py`（coverage 端点）
- `backend/api/main.py`（回调注册/生命周期）
- 测试：`backend/api/tests/test_shadow_run.py`（新增）、`test_routing_decision_log.py`（v2 兼容）
- `specs/057-execution-decision-loop/tasks.md`（DL-22 → 进行中，子编号 214/215）

**不做（拆到 215）**：周报脚本/端点、并排 UI、4 周观察报表、实现成本对照表；不改下单/提交路径（2c 的 `decision_id` 写提交属 DL-25）。

---

## 4. 验收（P4）

1. **覆盖率**：有 plan/auto plan 的路由订单 100% 有决策记录；无 plan 的走默认计划并标 `ENGINE_DEFAULT`；覆盖率端点按来源/原因披露。
2. **关联**：实际路由按 `order_id` 关联，`route_ids` 回填；重复事件不重复；改写原因五类可判定。
3. **约束**：影子建议硬违例数为 0（测试用 mock 验证计数路径）；检查异常可见且不阻断。
4. **降级**：DB 不可用、quote 缺失、order/route 回调异常 → 不阻断主流程，日志可见。
5. **回归**：`pytest backend/api/tests -q`、`pytest CostView/tests -q`、`python scripts/doc_check.py` 全绿；现有 075 决策日志测试不回归。

---

## 5. 风险

- **order 回调频率**：INIT_PAINT + 每次 UPDATE 都可能触发；必须按订单版本去重，且影子引擎调用要轻量（只读、不落 proposal）。
- **quote 价差来源**：实时 quote 可能缺失；缺失即 `None`，不以 0 填充。
- **不可变语义例外**：`actual_routes/rewrite_reason/updated_at` 允许更新；在契约/模型注释中写明，避免后续误以为全量可变。
- **引擎依赖 plan**：无 plan 时用 DL-18 默认计划；若默认计划也生成失败，记录 `no_suggestion` 并计入覆盖率，不静默丢单。

---

## 6. 交付

- 分支 `214-shadow-run-core`；PR 标题 `feat: 影子运行核心 (057-DL-22/214)`；合并后 215 做周报 + UI，最终 DL-22 收口。
