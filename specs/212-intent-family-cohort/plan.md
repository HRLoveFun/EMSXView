# 212 — 意图 × 算法族分组（DL-19 / PR 2）

> 父计划：`specs/057-execution-decision-loop` 的 **DL-19**（3a 口径修正与配对）
> 分支：`212-intent-family-cohort`（worktree `../EMSXView-wt-212-intent-family-cohort`，基于 `origin/main`，含 211）
> 依赖：211（已合并：控制变量去后验化）、DL-04（algo_taxonomy）
> 关联规范：`docs/spec/plan-design-principles.md`（P2 三栏 / P4 验收）、`docs/spec/anti-patterns.md`

---

## 1. 问题

当前 `SCORECARD_COHORTS` 只有 broker / strategy / env 维度，跨券商比较会把 **VWAP 族与收盘竞价族**混在同一组：两类算法的目标函数与基准不同（`Algo_TCA.md:654`），混排排名没有解释力；报告也未披露分组的意图来源。

**用户裁定（2026-11-25）**：**意图是可选的**——它只表达订单到达交易员手上时的指令，**不要求关联到路由**。因此：
- 有意图就用，无意图记 `UNKNOWN`；
- **不做算法族 → 意图的反推**（不臆造指令）；
- 分组在意图缺失时退化为「按算法族比较」，这正是同类比较需要的最小口径。

---

## 2. 方案（P2 三栏）

### S4 · 新增 `intent_family` cohort

- **理论依据**：同类比较必须先按算法族分组；意图是可选的上层标签，不参与反推。MIX 的两段（收盘段 + VWAP 段）在算法族维度上天然分开；SPECIAL 单列。
- **技术方案**：
  - `platform_data/contracts/tca_contracts.py`：`SCORECARD_COHORTS` 增加 `intent_family`；`ScorecardFilters.cohort` 默认改为 `intent_family`；`ScorecardCohortMetrics` 增加 `intent_source: str = ""` 与 `algo_family: str = ""`（向后兼容默认空）。
  - `CostView/src/tca_utils.py`：
    - 新增 `intent_family_key(route)`：`algo_family = classify_algo(route.Broker, route.algo)`；`intent = getattr(route, "intent", None) or "UNKNOWN"`（大写）；`intent_source = getattr(route, "intent_source", None) or "unknown"`；key = `"{intent}|{algo_family}"`，label 在 `UNKNOWN` 时只显示 `family.upper()`，否则 `"{intent} | {family.upper()}"`；
    - `cohort_key_and_label` 增加 `intent_family` 分支；
    - `aggregate_cohorts` 为 `intent_family` 组填充 `intent_source` / `algo_family`；组内来源不一致时 `intent_source="mixed"`。
  - `CostView/src/monitoring/report_spec.py`：`SPEC_VERSION` 升为 **`2026.11.25b`** 并登记 212。
- **检验方法**：
  - 单测：无意图 → `UNKNOWN|vwap`、label `VWAP`；有意图 `MIX` + `algo=MOC`/`VWAP` → `MIX|auction_close` 与 `MIX|vwap` 两组；`SPECIAL` 单列；`intent_source` 入 payload；`ScorecardFilters()` 默认 `intent_family`；`build_scorecard(cohort="intent_family")` 不报错。
  - 既有 `broker`/`strategy`/`broker_strategy` 行为不变。

---

## 3. 范围锁

- `platform_data/contracts/tca_contracts.py`
- `CostView/src/tca_utils.py`
- `CostView/src/monitoring/report_spec.py`
- 测试：`CostView/tests/test_env_context.py`（cohort 断言）、`test_tca_query_service.py`（默认 cohort / 构造）、`test_evaluation.py`（版本与维度）
- `specs/057-execution-decision-loop/tasks.md`（DL-19 → 已完成 211/212）

**不做**：不改前端页面结构（API 接受 cohort 字符串即可）；不引入意图关联键；不反推意图。

---

## 4. 验收（P4）

1. 单测覆盖 S4 全部分支；`intent_source`/`algo_family` 在 scorecard payload 可见。
2. `pytest CostView/tests -q`、`pytest backend/api/tests -k contract -q` 全绿；golden 0 指标漂移。
3. `python scripts/doc_check.py` 退出码 0。
4. `SPEC_VERSION=2026.11.25b`；报告治理元数据同源。

---

## 5. 风险

- 默认 cohort 变更会影响 API 默认视图；已同步测试，前端按字符串消费无需改代码。
- 历史路由大多没有意图，`UNKNOWN|family` 是预期主形态；不把缺失当缺陷，`intent_source="unknown"` 明示。

---

## 6. 交付

- 分支 `212-intent-family-cohort`；PR 标题 `feat: 意图×算法族分组 (057-DL-19/212)`；合并后 DL-19 状态改为「已完成」。
