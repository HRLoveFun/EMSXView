# 219 — 批量路由预填与改写原因（DL-25 第一批）

> 父计划：`specs/057-execution-decision-loop` 的 **DL-25**（2c 辅助模式：预填批量路由，人工确认）
> 分支：`219-batch-prefill`（worktree `../EMSXView-wt-219-batch-prefill`，基于 `origin/main`）
> 依赖：DL-16、DL-22、DL-24 —— 均已完成
> **用户裁决（2026-11-25）**：取消「DL-22 连续 4 周影子周报」硬前置；常规改动不做等待、边改边修。
> 说明：本 PR 交付**预填 + 改写原因 + decision_id 回写**；DL-16 参数注册表 API 迁移与删除两份前端映射拆到后续（220），避免一次改动同时动提交链路与参数编辑器。

---

## 1. 问题

1. 批量路由对话框只能人工从头配置券商/比例/策略，DL-22 已落盘的建议没有入口；
2. 交易员改写建议后没有原因码，周报无法区分「同意/改写」；
3. 提交链路不写 `decision_id`，建议与实际提交无法关联；
4. DL-25 原前置「4 周影子周报」阻塞交付（用户已裁决取消）。

---

## 2. 方案（P2 三栏）

### S1 · 从影子决策预填（只读）

- **理论依据**：人在回路；预填减少重复劳动，交易员保留最终确认（D-3）。
- **技术方案**：
  - 前端新模块 `batch-route-order/prefill.ts`（纯函数）：输入选中订单的影子决策记录 → 聚合券商候选数量为比例（归一化 100）、每券商最常见策略、参数摘要与决策理由；输出 `decisionIds[orderId]`。
  - `use-batch-route-state` 新增 `prefillFromShadow()`：按选中订单逐个 `GET /api/routing-decisions?order_id=`（复用 075/214 端点），调用纯函数后写入 `selectedBrokers/ratios/brokerStrategies`；参数以只读摘要提示，不自动覆盖动态参数字段（避免错位）。
  - 对话框按钮「Prefill from shadow」；无决策/请求失败 → 明确提示，不改变现有配置。
- **检验方法**：纯函数单测：两单两券 → 比例/策略/decisionId 正确；无记录 → 空结果；API 失败 → 空态不抛。

### S2 · 改写原因码 + decision_id 回写

- **理论依据**：改写本身是标签；提交与建议必须可关联（审计）。
- **技术方案**：
  - `BatchRouteOrderItem` 增加 `decisionId`、`rewriteReason`（后端 schema + TS 类型）；
  - 前端在预填后要求选择原因码（`BROKER_CHANGED / QUANTITY_CHANGED / PARAMS_CHANGED / EXTRA_ROUTE / UNCHANGED`），未选择则 `canValidate=false`；`buildRequest` 为每个 item 带上 `decisionId` 与 `rewriteReason`；
  - 批量提交成功（非 dry-run）后，后端调用 `decision_log_service.link_submission(order_id, decision_id, rewrite_reason)`：更新最新决策 payload 的 `submission_decision_id / trader_rewrite_reason / submitted_at`（与 214 的 `actual_routes` 同为允许后更新字段），失败不阻断提交。
- **检验方法**：真实 SQLite：提交后决策 payload 回写正确；dry-run 不回写；无 decision_id 不报错；改写原因只接受枚举值（非法值忽略并披露）。

### S3 · 周报口径

- **技术理论**：改写率应反映交易员主观原因，而非事后路由比对。
- **技术方案**：`shadow_weekly_service` 的原因分布优先取 `trader_rewrite_reason`（缺失回落 214 的 `rewrite_reason`），新增 `trader_reason_coverage`；不改变原有 214 指标。
- **检验方法**：合成决策：一个 trader reason、一个仅实际路由 reason → 分布与覆盖率正确；无 trader reason → 回落。

---

## 3. 范围锁

- `backend/api/schemas/batch.py`（item 字段）
- `backend/api/services/batch_route_service.py`（提交后 link_submission）
- `backend/api/services/decision_log_service.py`（`link_submission`）
- `backend/api/services/shadow_weekly_service.py`（trader reason 优先）
- `ExecutionView/module/components/batch-route-order/prefill.ts`（新增）+ `prefill.test.ts`
- `ExecutionView/module/components/batch-route-order/use-batch-route-state.ts`、`batch-route-toolbar.tsx`、`batch-route-order-dialog.tsx`、`types.ts`
- `ExecutionView/module/services/execution-api.ts`（routing-decisions 查询）
- `ExecutionView/module/types` 的 `BatchRouteOrderItem` 扩展（如定义在此）
- 测试：`backend/api/tests/test_batch_prefill_link.py`（新增）
- 文档：`dl-specs.md` DL-25 依赖行、`plan.md` 2c 行、`tasks.md` DL-25 状态/依赖

**不做**：AUTO / 自动提交；DL-16 注册表 API 迁移与前端映射删除（220）；不改 EMSX 下单字段。

---

## 4. 验收（P4）

1. 预填纯函数与前端按钮可用；无决策/失败降级不改变现有配置。
2. 预填后必须选原因码才能提交；提交成功回写 decision_id/原因，dry-run 不回写，失败不阻断。
3. 周报优先使用交易员原因并披露覆盖率。
4. 回归：`pytest backend/api/tests -q`、前端 vitest/tsc、`python scripts/doc_check.py` 全绿。

---

## 5. 风险

- 动态参数字段无法安全自动填：本 PR 只预填券商/比例/策略，参数以摘要提示，避免错位。
- 预填建议与实际订单不匹配：交易员确认环节保持必经；原因码强制。
- 提交链路改动：只加字段与旁路回写，不改 route_order 请求字段；写失败不阻断。
