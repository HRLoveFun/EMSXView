# 215 — DL-22 影子周报与并排 UI（PR 2）

> 父计划：`specs/057-execution-decision-loop` 的 **DL-22**（2b 影子模式与周报）
> 分支：`215-shadow-weekly`（worktree `../EMSXView-wt-215-shadow-weekly`，基于 `origin/main`，含 214）
> 依赖：214（影子运行核心，已合并）、DL-19/DL-20（实现成本对照参考）
> 关联规范：`docs/spec/plan-design-principles.md`（P2/P4）、`docs/spec/attribution-pitfalls.md`

---

## 1. 问题

214 已能记录影子决策与实际路由，但还缺：

1. **周报**：一致率、预期成本差、改写率与原因分布、覆盖率、硬约束违例数，按周输出；
2. **并排 UI**：交易员只能查 JSON，看不到「建议 vs 实际」的只读对照；
3. **连续 4 周观察**需要一个可重复运行的报告入口与归档路径。

---

## 2. 方案（P2 三栏）

### S1 · 周报聚合服务与端点

- **理论依据**：影子期结论必须可复现、可审计；指标定义固定、缺失显式披露（AT 红线：不把不可得当 0）。
- **技术方案**：
  - `backend/api/services/shadow_weekly_service.py`：只读查询 `routing_decisions`（按 `created_at` 落在 `[start, end]`），按 ISO 周分组，输出：
    - `coverage`：decisions / orders / 来源分布 / 实际关联率 / 无建议数；
    - `agreement`：实际 broker→quantity 映射与建议完全一致的比例（仅对有实际路由的记录）；
    - `rewrite`：改写率 + `rewrite_reason` 分布（UNCLASSIFIED 计入「未改/不可判定」并单列）；
    - `constraints`：`BLOCK` 硬违例数（目标 0）；
    - `expected_cost`：仅在候选带 `estimated_cost_bps` 时给出建议侧加权均值；实际侧缺同源估计时 `available=false` 并披露（不拿别的成本口径冒充）。
  - 端点 `GET /api/routing-decisions/weekly?start_date=&end_date=`（🔒，只读）。
  - CLI `scripts/qa/shadow_weekly_report.py`：调用同一服务，写 `logs/qa/shadow/shadow_weekly_<start>_<end>.json`，供 4 周观察归档。
- **检验方法**：合成 SQLite 决策：一致/改写/无实际/硬违例各一组 → 指标逐项断言；空区间不抛错；周分组边界（周一/周日）；避免把 `estimated_cost` 缺失当 0。

### S2 · 并排 UI（只读）

- **理论依据**：影子期需要交易员能一眼看到「引擎建议 vs 我的实际路由」，但不改变下单路径（D-3）。
- **技术方案**：
  - 新组件 `ExecutionView/module/components/shadow-decision-panel.tsx`：按 `order_id` 拉取 `GET /api/routing-decisions?order_id=&limit=1`，左右两栏渲染：
    - 左：建议（broker/quantity/participation/strategy_params、intent/source、决策时点价差、约束违例）；
    - 右：实际路由（broker/quantity/status/filled、route_id）；
    - 头部：改写原因、`as_of`、`schema_version`；无记录时显示「暂无影子决策」。
  - `ExecutionBoard` 增加一个可折叠的 **Shadow** 面板（与 Sub-Orders 同模式）；当恰好选中 1 个订单时展示该订单，未选中时提示先选择订单。
  - 只读：不引入任何提交/修改动作；API 失败降级为空态。
- **检验方法**：组件测试（mock fetch）：有建议+实际 → 两栏字段正确；无记录 → 空态；API 失败 → 空态且不抛；`ExecutionBoard` 渲染不回归（现有测试全绿）。

---

## 3. 范围锁

- `backend/api/services/shadow_weekly_service.py`（新增）
- `backend/api/routers/routing_decisions.py`（weekly 端点）
- `scripts/qa/shadow_weekly_report.py`（新增）
- `ExecutionView/module/components/shadow-decision-panel.tsx`（新增）
- `ExecutionView/module/views/ExecutionBoard.tsx`（Shadow 折叠面板）
- 测试：`backend/api/tests/test_shadow_weekly.py`（新增）、`ExecutionView/module/components/shadow-decision-panel.test.tsx`（新增）、必要时 `ExecutionModule.test.tsx`
- `docs/api-contracts.md`（weekly 端点）
- `specs/057-execution-decision-loop/tasks.md`（DL-22 → 已完成 214/215）

**不做**：不改下单/提交路径；不实现 ASSIST（2c/DL-25）；预期成本模型未接线前不伪造 `expected_cost`；不做历史回填。

---

## 4. 验收（P4）

1. 周报指标定义固定且可复现；空数据/缺实际路由/缺估计均显式披露，不以 0 填充。
2. UI 只读并排显示建议与实际；无记录/API 失败降级为空态；不改任何执行行为。
3. 4 周观察：`shadow_weekly_*.json` 可按周归档；连续 4 周报告 + 硬违例数为 0（实现交付后开始观察）。
4. 回归：`pytest backend/api/tests -q`、`pytest CostView/tests -q`、前端 `npm test` / `tsc`、`python scripts/doc_check.py` 全绿。

---

## 5. 风险

- **实际路由稀疏**：影子期实际关联率可能低于 100%；报告必须披露分母，不把缺失当一致。
- **预期成本差**：214 未填 `estimated_cost_bps` 时不可计算；报告 `available=false`，待成本模型接线后补齐。
- **UI 只读**：任何「按建议下单」动作都不在本 PR；避免误触。

---

## 6. 交付

- 分支 `215-shadow-weekly`；PR 标题 `feat: 影子周报与并排 UI (057-DL-22/215)`；合并后 DL-22 状态改为「已完成」。
