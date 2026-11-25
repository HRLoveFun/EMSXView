# 216 — 聚类推断与收缩排名（DL-23）

> 父计划：`specs/057-execution-decision-loop` 的 **DL-23**（3b 评估 v2）
> 分支：`216-cluster-ranking`（worktree `../EMSXView-wt-216-cluster-ranking`，基于 `origin/main`）
> 依赖：DL-13（预期成本）、DL-20（配对评估）——均已完成
> 关联规范：`docs/spec/plan-design-principles.md`（P2/P4）、`docs/spec/attribution-pitfalls.md`

---

## 1. 问题

027 的组间比较把路由当 iid 样本：**同交易日路由共享冲击**，标准误被低估、显著性被高估；小样本单元（新券商/新市场）排名不稳定。DL-23 要求：

1. 交易日**聚类稳健**标准误与**块 bootstrap**；
2. DerSimonian–Laird **收缩**（仅 numpy）与分级回退；
3. **P(top-k)** 模拟与**不可区分集合**；
4. 排名只用**正式数据**（当日临时版不计入）；
5. 与 027 结果并排对照并解释差异。

---

## 2. 方案（P2 三栏）

### S1 · 聚类稳健推断与块 bootstrap

- **理论依据**：同交易日路由受共同市场冲击，残差组内相关；iid SE 低估方差。按交易日聚类（cluster-robust sandwich）或按块重采样（block bootstrap）才能接近名义覆盖率。
- **技术方案**：新模块 `CostView/src/evaluation/ranking.py`：
  - `cluster_robust_mean(values, clusters)`：按交易日聚类的均值方差（G/(G-1) 修正），G<2 回退 iid 并标记；
  - `block_bootstrap_ci(values, clusters, n_boot, alpha, seed)`：按交易日整块有放回重采样，百分位区间；固定 seed 保证可复现。
- **检验方法**：构造日内相关、日间独立的合成数据：cluster SE ≥ iid SE；已知均值落入区间；同一 seed 两次结果一致。

### S2 · DL 收缩与分级回退

- **理论依据**：小样本单元需部分汇总到父层（券商/全局），避免「3 笔成交就排名」。
- **技术方案**：
  - `dersimonian_laird(estimates, variances)`：随机效应合并（Q、tau²、权重），numpy 实现；
  - `shrink_estimates(units)`：经验贝叶斯后验均值/方差（`tau²=0` 时退化为合并均值）；
  - 分级回退：单元样本 < `MIN_UNIT_SAMPLE`（默认 10）→ `low_sample=True`；无有效单元 → 全局合并均值并标 `fallback=True`。
- **检验方法**：已知单元真值 + 方差的模拟：后验均值位于单元值与合并均值之间；tau²=0 时全部等于合并均值；小样本单元被拉向父层。

### S3 · P(top-k) 与不可区分集合

- **理论依据**：排名要给「前 k 的概率」而不是单点名次；区间重叠的券商不可区分。
- **技术方案**：
  - 从后验 `Normal(posterior_mean, posterior_sd)` 抽样（固定 seed）；统计每单元进入前 k 的频率 = `p_top_k`；
  - `indistinguishable`：95% 区间与最优单元区间重叠、或 `p_top_k ≥ 0.1` 的单元；
  - 输出后验均值、区间、P(top-k)、不可区分集合，供 DL-24 快照与 DL-27 轮换候选。
- **检验方法**：已知差距大的单元 P(top-k) ≈ 1；接近的单元 P 分散且进入不可区分集合；`sum(p_top_k)=k`。

### S4 · 正式数据与报告接线

- **理论依据**：当日临时版（provisional）不进排名（口径冻结）。
- **技术方案**：
  - `is_formal_route(route)`：排除 `is_provisional=True` 或 `source` 非 `formal/daily` 的路由；TCA 日汇总默认正式。
  - `report.build_evaluation_report` 新增 `"ranking"` 章节（券商排名 v2）：方法、样本/交易日覆盖、后验均值与区间、P(top-k)、不可区分集合、与 027 的 `dimensions[broker]` 并排对照字段（均值/样本）。
  - `SPEC_VERSION` 升为 **`2026.11.25d`**。
- **检验方法**：报告含 `ranking`；provisional 路由被排除且披露；排名 payload 可复现；与 027 的 broker 维度对照字段一致。

---

## 3. 范围锁

- `CostView/src/evaluation/ranking.py`（新增）
- `CostView/src/evaluation/report.py`（ranking 章节）
- `CostView/src/monitoring/report_spec.py`（版本）
- 测试：`CostView/tests/test_ranking.py`（新增）、`test_evaluation.py`（section/版本）
- `specs/057-execution-decision-loop/tasks.md`（DL-23 → 已完成 216）

**不做**：不改 SQL/取数口径；不引入 statsmodels/scikit；不做 DL-24 的 BrokerScoreSnapshot（下一 DL）。

---

## 4. 验收（P4）

1. 模拟研究：已知真值、20 个交易日、6 券商 → 后验排序正确、区间覆盖接近名义（≥85% 的宽松下界，记录实测值）、P(top-k) 方向正确。
2. 聚类 vs iid：日内相关数据下 cluster SE ≥ iid SE；G<2 回退且标记。
3. 收缩：小样本单元被拉向父层；tau²=0 退化正确。
4. 可复现：同输入同 seed → 完全一致的 payload。
5. 回归：`pytest CostView/tests -q`、`pytest backend/api/tests -k contract -q` 全绿；golden 0 指标漂移；`python scripts/doc_check.py` 退出码 0。

---

## 5. 风险

- 交易日数过少（<10）时 cluster/bootstrap 不稳：披露 `days` 与 `low_sample`，不把区间当强结论。
- 单元（券商）日样本不均：DL 收缩吸收，但 tau² 估计可能为 0（完全合并）——显式返回。
- 正式数据判定：TCA 日汇总默认正式；若上游引入 provisional 标志，按 `is_provisional` 排除。

---

## 6. 交付

- 分支 `216-cluster-ranking`；PR 标题 `feat: 聚类推断与收缩排名 (057-DL-23/216)`；合并后接 DL-24。
