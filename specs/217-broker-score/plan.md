# 217 — BrokerScoreSnapshot 与分项得分（DL-24）

> 父计划：`specs/057-execution-decision-loop` 的 **DL-24**（3b 评估 v2）
> 分支：`217-broker-score`（worktree `../EMSXView-wt-217-broker-score`，基于 `origin/main`，含 DL-23/216）
> 依赖：DL-23（聚类推断与收缩排名，已合并）
> 关联规范：`docs/spec/plan-design-principles.md`（P2/P4）、`docs/spec/attribution-pitfalls.md`

---

## 1. 问题

DL-23 只给券商成本的后验排名；分配引擎与轮换需要**分项得分快照**（成本、尾部风险、完成率/机会成本、信息泄露、运营质量），且必须可复现、可审计。当前没有 `BrokerScoreSnapshot` 契约、拉取 API、CUSUM 漂移告警与错位样本披露；综合评分按 D-5 不排期，不得偷偷合成。

---

## 2. 方案（P2 三栏）

### S1 · BrokerScoreSnapshot 契约

- **理论依据**：排名同时覆盖成本、风险、完成率、信息泄露与运营质量（三重检验）；只出分项、不合成，避免黑箱分数。
- **技术方案**：`platform_data/contracts/broker_score.py`：
  - `BROKER_SCORE_VERSION = "broker-score-v1"`；
  - `ScoreComponent(name, value, unit, sample_size, available, note)`；
  - `BrokerScoreSnapshot(broker, as_of, window_start, window_end, spec_version, components, weights={}, composite=None, cusum, misaligned_samples, low_sample)`；
  - 契约导出到 `platform_data.contracts`。
- **检验方法**：契约字段/默认值单测；`asdict` 序列化稳定。

### S2 · 分项得分与 CUSUM

- **理论依据**：分项必须同源、可解释；漂移用 CUSUM 监控成本均值偏移。
- **技术方案**：`CostView/src/evaluation/broker_score.py`：
  - 输入：正式路由（DL-23 `is_formal_route` 同源）+ DL-23 ranking payload；
  - 分项：
    - `cost`：ranking 的 `posterior_mean`（arrival bps），样本量与 low_sample；
    - `tail_risk`：路由成本的**当日截面 z** 的 95% CVaR（尾部均值，正 = 更差）；
    - `completion`：`fill / RouteShares` 均值（缺失回退 `fill / Amount`）；
    - `opportunity_cost`：`opportunity_cost` 均值；
    - `leakage`：**不可得**（管道 S10 `reversal_30m_bps` 尚未进 CostView 作用域），`available=false` + note，不伪造；
    - `operational`：`fill_count > 0` 的路由占比（运营质量代理）。
  - `misaligned_samples`：缺交易日/缺成本的路由数（单列、不参与分项）；`low_sample`：n < DL-23 `MIN_UNIT_SAMPLE`。
  - `cusum`：按交易日排序的券商日成本均值序列，目标 = 全样本均值、σ = 全样本标准差；上/下 CUSUM，`alert = max(|CUSUM|) > 5`，返回峰値、方向与日数。
  - `weights={}`、`composite=None`（D-5 预留，不合成）。
- **检验方法**：合成数据：已知成本/完成率/尾部；分项方向正确；CUSUM 在对已知漂移的序列上告警、平稳序列不告警；缺 leakage 显式不可得；错位样本单列。

### S3 · 报告与拉取 API

- **理论依据**：分配引擎与轮换需要稳定快照接口；报告需并排展示分项。
- **技术方案**：
  - `report.build_evaluation_report` 新增 `"broker_scores"` 章节（复用同一次 `rank_brokers` 结果，避免重复计算），含 `governance`（`evaluation_metadata` + `assert_governance_complete`）。
  - `CostView/api/routers/costview.py` 新增 `GET /api/tca/broker-scores?start_date=&end_date=&broker=&algo=`，返回同一 payload；`TcaQueryService.build_broker_scores(filters)` 复用 `_collect_routes`。
  - `SPEC_VERSION` 升为 **`2026.11.25e`**。
- **检验方法**：同输入同输出可复现；`assert_governance_complete` 通过；端点参数校验；空数据 `available=false`。

---

## 3. 范围锁

- `platform_data/contracts/broker_score.py`（新增）+ `platform_data/contracts/__init__.py`
- `CostView/src/evaluation/broker_score.py`（新增）
- `CostView/src/evaluation/report.py`（broker_scores 章节，复用 ranking）
- `CostView/src/tca_query_service.py`（`build_broker_scores`）
- `CostView/api/routers/costview.py`（GET 端点）
- `CostView/src/monitoring/report_spec.py`（版本）
- 测试：`CostView/tests/test_broker_score.py`（新增）、`test_evaluation.py`（section/版本）
- `docs/api-contracts.md`（端点）、`specs/057-execution-decision-loop/tasks.md`（DL-24 → 已完成 217）

**不做**：不合成综合评分（D-5）；不引入 `reversal_30m_bps` 跨仓字段（显式不可得）；不改下单/轮换路径。

---

## 4. 验收（P4）

1. 分项方向正确、同输入同输出可复现；`governance` 完整（`assert_governance_complete` 通过）。
2. CUSUM 合成漂移告警、平稳不告警；错位样本单列。
3. `leakage` 缺失显式 `available=false`，不伪造。
4. 回归：`pytest CostView/tests -q`、`pytest backend/api/tests -k contract -q` 全绿；golden 0 指标漂移；`python scripts/doc_check.py` 退出码 0。

---

## 5. 风险

- 分项代理口径：运营质量用 `fill_count>0` 占比、完成率用 fill/RouteShares；都是可得代理，报告注明，不声称完整运营 KPI。
- 小样本券商：`low_sample=true`，分项照出但标注；不参与轮换（DL-27 决定）。
- 错位期定义：以缺交易日/缺成本为准；后续若上游提供 provisional 标志，按同一函数扩展。

---

## 6. 交付

- 分支 `217-broker-score`；PR 标题 `feat: BrokerScoreSnapshot 与分项得分 (057-DL-24/217)`；合并后 DL-24 完成，下一无依赖项仅剩 DL-25（需 4 周观察 + 用户确认）。
