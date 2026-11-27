# 236 — 节点三披露补全（D1 / 排名 v2 / 券商分项得分）

> 来源：节点三“运行态/开关”检查（2026-11-27）发现的展示层缺口
> 分支：`236-node3-disclosure`（worktree `../EMSXView-wt-236-node3-disclosure`，基于 `origin/main`）

## 问题

节点三的计算与 API 已完整，但 **EvaluationView 与 HTML 归档只渲染 `sections.dimensions`**：

- D1 配对覆盖率、排名 v2（后验区间 / P(top-k) / 不可区分集合）、券商分项得分只在 API JSON 中；
- `types.ts` 没有对应类型；排名区间字段是 `posterior_ci_*`，不是 `ci_*`；
- 5 天窗口默认 2,000 路由会截断，影响 D1/排名样本。

## 方案（a–d）

- **a. EvaluationView**：新增三块只读卡片
  - `PairingPanel`：可配对订单/组/路由/券商、规则、相对成本统计、券商对检验（不足时显式说明）；
  - `RankingPanel`：Top 10 后验均值、95% 区间（读 `posterior_ci_*`）、P(top-k)、不可区分集合；
  - `BrokerScoresPanel`：Top 10 分项得分（成本/尾部/完成率/机会成本/运营）、`low_sample`/错位标记；信息泄露不可得显式 `—`。
- **b. types**：`EvaluationPairingSection` / `EvaluationRankingSection` / `EvaluationBrokerScoresSection` 及子类型。
- **c. HTML 归档**：`_render_evaluation_section` 追加 D1 / 排名 v2 / 分项得分摘要（Top 5），保留维度摘要。
- **d. 上限可配**：`TCA_EVAL_MAX_ROUTES`（默认 2000）用于评估报告与分项得分端点；长窗口可提高，避免截断。

## 验收

- 生产单日（2026-11-20）报告：3,112 路由；D1 1.2%；排名 25 家；分项 25 个；HTML 含三块摘要。
- `CostView/tests`（含新增披露测试）全绿；后端全量 792 passed / 1 skipped；`tsc` 通过；`doc_check` 0。
- 不改任何计算口径；只做展示与上限配置。

## 边界

- `leakage` 分项仍不可得（S10 未进 CostView 作用域），不填 0。
- 排名区间必须读 `posterior_ci_*`，iid `ci_*` 为空是预期。
- 得分快照的“改变分配比例”仍属 DL-27（已搁置）。
