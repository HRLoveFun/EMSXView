# 211 — 评估控制变量去后验化（DL-19 / PR 1）

> 父计划：`specs/057-execution-decision-loop` 的 **DL-19**（3a 口径修正与配对）
> 分支：`211-evaluation-lookahead-removal`（worktree `../EMSXView-wt-211-evaluation-lookahead-removal`，基于 `origin/main`）
> 依赖：DL-01（意图契约）、DL-03（会话注册表）、DL-04（算法族）、DL-12（路由到达价）——均已完成
> 拆分：本 PR 只做 **S1–S3 + S5**（控制变量与口径版本）；**S4「意图 × 算法族」分组**拆到 **212**，待本 PR 合并后开工
> 关联规范：`docs/spec/plan-design-principles.md`（P2 三栏 / P4 验收）、`docs/spec/anti-patterns.md`、`docs/spec/attribution-pitfalls.md`

---

## 1. 问题

当前 TCA 评估的**控制变量**里混入了决策后才产生的量（后验变量），会把算法差异吸收进分层：

| # | 后验变量 | 现状（代码位置） | 后果 |
|---|---|---|---|
| B1 | 订单规模用**成交量** | `CostView/src/monitoring/env_context.py:240`：`adv20_ratio = fill / adv_20d` | 成交越多的算法被分到更大的规模层；规模层吸收算法表现 |
| B2 | 时段用**首笔成交时刻** | `env_context.load_start_times()` 读 `fill_bdib.MIN(mkt_timestamp)` | 慢启动/晚启动的算法被判成不同时段 |
| B3 | 流动性缺失回退 `par_rate` | `CostView/src/tca_utils.py:_env_cohort_key`（`liquidity_adv20`） | `par_rate` = 成交/ADV，后验；缺失分层被静默替换成结果变量 |
| B4 | 波动率缺失回退 `|pnl_vwap|` | 同上（`volatility`） | 用被解释变量当解释变量，循环论证 |
| B5 | 分组前按结果过滤样本 | `tca_utils.aggregate_cohorts()`：`if route.pnl_vwap is None and route.par_rate is None: continue` | 无成交/无基准的路由被静默剔除，样本选择偏差 |

依据：`docs/textbook/Algo_TCA.md` 的配对/分层原则与 `docs/spec/attribution-pitfalls.md`——分层键必须是**决策前可得**变量。

---

## 2. 方案（P2 三栏）

### S1 · 规模改为 `RouteShares ÷ ADV20`（B1）

- **理论依据**：订单规模是决策时点已知的委托量；成交量是算法执行的结果。用委托量分层才与算法绩效正交。
- **技术方案**：`env_context.RouteEnvContext.adv20_ratio` 改为 `RouteShares / adv_20d`（`RouteShares` 在 `TcaRouteSummary` 已有，缺省 `None`）；`load_env` 传入 `RouteShares` 而非 `fill`；docstring 同步。`adv_20d` 仍优先取路由行、缺失回退 `bdib_daily_summary`。
- **检验方法**：单测：`RouteShares=1000, fill=500, adv=10000` → 10%（不是 5%）；`RouteShares=None` → `unknown`；`adv=0/None` → `unknown`。

### S2 · 时段改为 `route_as_of_time` + 会话相对分桶（B2）

- **理论依据**：路由下达时刻是决策时点变量；首笔成交时刻是执行结果。时段必须按**交易所会话**定义（开盘/午休/收盘竞价），不能用统一的 10:30/14:30 挂钟切分。
- **技术方案**：
  - `env_context` 新增 `load_route_as_of_times()`：从 `processed_fills` 按 `(OrderId, RouteId, order_as_of_date)` 取 `MIN(route_as_of_time)`（交易所本地 `HH:MM:SS`，DL-12 同一来源）；`RouteEnvContext.start_time` 改存该值；旧 `load_start_times()` 不再参与环境分层（保留给其它调用或删除，按 grep 结果决定）。
  - `tca_utils._env_cohort_key(time_of_day)`：用 `platform_data.adapters.session.ExchangeSessionAdapter`：
    - 优先 `time_bucket_for(exchange, local_dt)`（管道 S9 镜像：`open_30m/morning/midday/afternoon/close_30m`，JP 含 `lunch_break`）；
    - 非 `TIME_BUCKET_MARKETS` 的市场用 `session_relative_minutes()` + 会话跨度派生 `open/mid/close`；
    - 市场未知/时刻不可解析 → `unknown`；**绝不回退首笔成交时刻**。
  - 分桶来源（`s9` / `session-relative` / `unknown`）在 `env_coverage` 的 `time_bucket_source` 计数与治理 `degradations` 中披露。
- **检验方法**：单测：路由 10:00 下达、首笔 15:59 → 按 10:00 分桶（Open），不再落 Close；JP 午休 → `lunch_break`；非 S9 市场 → session-relative 桶；缺 `route_as_of_time` → `unknown`；`bucket_time_of_day` 不再出现在真实分层路径（grep/单测）。

### S3 · 删除 `par_rate` / `|pnl_vwap|` 兜底，缺失计 unknown（B3/B4/B5）

- **理论依据**：缺失维度的正确处置是「未知 + 披露」，不是用结果变量顶替（AT 红线）。
- **技术方案**：
  - `_env_cohort_key`：`liquidity_adv20` 缺 `env.adv20_ratio` → `("unknown","Unknown")`；`volatility` 缺 `env.daily_volatility` → `unknown`；两条后验兜底删除。
  - `aggregate_cohorts` 删除 `pnl_vwap/par_rate` 双缺失的 `continue`；无基准的路由仍入层，指标按 `None` 跳过，样本量如实计数。
  - `env_coverage()` 增加每维 `known/unknown` 计数与 `time_bucket_source`；`report_spec.REPORT_SPEC` 增加 `posterior_fallbacks: "removed"` 声明，报告可信度区与治理元数据披露。
- **检验方法**：单测：缺流动性/波动率 → `unknown`，且**不再**读取 `route.par_rate`/`route.pnl_vwap`（把两字段置哨兵值，断言不被使用）；`aggregate_cohorts` 对 `pnl_vwap=None` 的路由仍纳入 `sample_size`；`env_coverage` 的 `known+unknown=total`。

### S5 · 口径版本与报告元数据

- **理论依据**：口径变更必须可追溯（治理层：版本锁定 / 降级披露）。
- **技术方案**：`CostView/src/monitoring/report_spec.py` 的 `SPEC_VERSION` 升为 **`2026.11.25`** 并登记 DL-19 变更；报告治理元数据的 `scope`/`degradations` 带 `posterior_fallbacks_removed` 与覆盖率 known/unknown。
- **检验方法**：报告 payload 的 `governance.spec_version == "2026.11.25"`；脚注与常量一致（既有断言模式）。

---

## 3. 范围锁

- `CostView/src/monitoring/env_context.py`
- `CostView/src/tca_utils.py`
- `CostView/src/monitoring/report_spec.py`
- `CostView/src/evaluation/report.py`（仅覆盖率/治理透传；不改分组逻辑）
- 测试：`CostView/tests/test_env_context.py`、`test_tca_utils.py`、`test_evaluation_report.py`、`test_report_spec.py`（按实际文件名）
- `CostView/tests/golden/`（预期 0 指标漂移；仅在确有变化时按 SOP 重生成并逐条归因）

**不做**：不改上游管道、不加数据库列、不改前端页面结构；**S4 意图 × 算法族分组不在本 PR**（见 212）。

---

## 4. 验收（P4）

1. **单测**：S1–S3 + S5 各至少 1 例；重点断言「后验字段即使有值也不被读取」。
2. **覆盖率披露**：`env_coverage` 每维 `known+unknown=total`；`time_bucket_source` 计数可见；与改动前对比逐项解释（规模/时段覆盖率应持平或上升；流动性去掉 `par_rate` 兜底后 `unknown` 上升必须显式披露）。
3. **Golden**：`python -m pytest CostView/tests/test_golden_samples.py -q` 全绿；预期 0 指标漂移（本次不改 per_order 指标）。
4. **全量回归**：`pytest CostView/tests -q`、`pytest backend/api/tests -k contract -q` 全绿；`python scripts/doc_check.py` 退出码 0。
5. **治理**：`governance.spec_version=2026.11.25`、覆盖率 known/unknown 齐备。

---

## 5. 风险与不做的事

1. **时段回退口径**：非 S9 市场的 `session-relative` 桶是通用三段，与 S9 五桶不完全同精度；来源明示，后续由 DL-06 补注册表后收敛。
2. **覆盖率数字变化**：移除 `par_rate` 兜底会让流动性层的 `unknown` 上升；这是**真实披露**，不得用结果变量换数字。
3. **意图**：本次不涉及意图关联；意图是可选的订单到达指令，S4 仅在有意图时使用，无意图记 `UNKNOWN`，不做算法族反推（见 212）。

---

## 6. 交付

- 分支：`211-evaluation-lookahead-removal`；单 PR，标题 `feat: 评估控制变量去后验化 (057-DL-19/211)`。
- PR 描述逐条对照 §4 给证据；同一 PR 内把 `tasks.md` 的 DL-19 状态行补子编号 211（212 待后续）。
