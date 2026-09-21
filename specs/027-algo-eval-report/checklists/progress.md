# 027 进度与检查点

> **特性**：`027-algo-eval-report`
> **计划**：[`plan.md`](../plan.md)
> **维护约定**：每完成一项更新状态与日期；**勾选必须附测试用例依据**，未覆盖项如实标注不补勾。

## 状态总览

| 阶段 | 内容 | 状态 | 对应 PR |
|---|---|---|---|
| P0 | 故障定位（「评估失败」） | 🟡 三层诊断完成，待用户提供错误文本 | — |
| P1 | 分层内比较（`stratified.py` + `comparability` 改造） | ✅ 完成（含 3 项实测缺陷修复） | — |
| P2 | 综合评估编排（`report.py` + 端点 + 门控用例 T16） | ✅ 完成 | — |
| P3 | Report 内嵌章节（HTML + CSV） | ⏳ | — |
| P4 | 前端重构（EvaluationView 去选择器 + ReportView 内嵌） | ⏳ | — |
| P5 | 口径治理与文档（三处同步 + SPEC_VERSION） | 🟡 `report_spec` 已更（`2026.09.9`），三处文档待同步 | — |

---

## P0：故障定位（「评估失败」）

已完成的三层诊断（2026-09-21）：

- [x] 服务层：直接调 `build_evaluation_comparison`（3 case，真实库）→ **无异常**，正常返回
- [x] HTTP 层：`TestClient` 打 `/api/tca/evaluation/compare`（含模拟前端 filters）→ **200 OK**
- [x] 前端逻辑：比对 `fetchScorecard` 范式与 `localStorage` 默认值补齐 → 无 undefined 风险
- [ ] **待用户提供**：界面「评估失败」下方的具体错误文本
- [ ] 依文本定位并修复；若确为「后端未重启」则同时补端点级冒烟用例（与 T16 合并）

> 诊断脚本：`_tmp/repro_eval.py`（服务层）、`_tmp/repro_endpoint.py`（HTTP 层），均只读。

---

## P1：分层内比较

- [ ] `evaluation/stratified.py`（层内效应 + 样本量加权合并 + 层可用性披露 + 置信度分档）
- [ ] `comparability.py` 改造：`assess_comparability` 门禁语义 → 分层可用性描述；TVD 降为描述指标
- [ ] `power.py` 层内样本量指引复用
- [ ] `__init__.py` 导出登记（导出护栏）
- [ ] 用例：合并正确性 / 层不足跳过 / 无可用层退化 / 覆盖率披露

## P2：综合评估编排

- [ ] `evaluation/report.py`：遍历全部维度（broker / strategy / broker_strategy / asset_class / Exchange / 环境三维）
- [ ] 每组 vs 其余（层内）的检验：三基准并列（`arrival` 主检验）、三方法并列（t / KS / χ²）、BH 校正
- [ ] `sections`：credibility / dimensions / trend / risk / market
- [ ] `TcaQueryService.build_evaluation_report`（一次取数、一次环境上下文）
- [ ] 端点 `POST /api/tca/evaluation/report`；移除 `/compare`
- [ ] **门控降级端点级用例**（T16）
- [ ] 真实库端到端：`broker` 维度**不再返回「不可比/无结论」**

## P3：Report 内嵌章节

- [ ] `report_aggregator.build_report` 增加 `evaluation` 摘要键（同一 payload 切片）
- [ ] `tca_report_html.py` 新增 `_render_evaluation_section`
- [ ] CSV 导出对齐

## P4：前端重构

- [ ] `EvaluationView` 移除全部选择器（维度 / 基准 / 方法 / alpha / correction / 最小样本）
- [ ] 改为分维度折叠明细 + 趋势 / 风险 / 市场 / 可信度小节
- [ ] 取数改用 `@shared/hooks/use-async-data`
- [ ] `ReportView` 内嵌评估摘要卡片（与 HTML 章节文案对齐）
- [ ] 契约类型 / API 封装更新

## P5：口径治理

- [ ] `report_spec.py` 评估口径声明 + `SPEC_VERSION` bump
- [ ] 三处同步（`report_spec` / `report-tca-known-limitations` / ADR-0018）
- [ ] `docs/open-todos.md`：T16 关闭；026 的评估形态偏差补记

---

## 遗留项登记

| # | 事项 | 来源 | 状态 | 备注 |
|---|---|---|---|---|
| — | （暂无） | — | — | — |
