# 068 — 预期成本与 timing risk 模型

> 父计划：`specs/057-execution-decision-loop/plan.md`（DL-13）
> 分支：`068-expected-cost-model` · worktree：`../EMSXView-wt-068-expected-cost-model`
> 依赖：DL-04（062，算法族）、DL-10（066，日度基线/波动分位）、DL-12（063，p_route_arrival）· 消费者：DL-18（打分）、DL-23（标准化 z 分母）、盘前单（DL-14 展示）
> 关联：`CostView/src/evaluation/cost_model.py`（幂律冲击拟合，026 阶段三，复用不重造）

## 1. 问题

- **z 值评估缺事前模型**：DL-23 的标准化成本 z =（预期 − 实际）÷ timing risk 需要**本侧统一事前模型**，而非券商自报（`Algo_TCA.md:501-519`）；
- **盘前单「把账算清」缺核心输出**：DL-14 需要逐单预期成本、所需交易时长、收盘容量——当前无模型；
- **模型不可复现风险**：拟合若不落盘版本化，下游消费的模型会随进程漂移。

## 2. 方案（P2 三栏）

### 2.1 理论依据

z 值评估需本侧统一事前模型（不用券商自报）；预期成本按实际成交股数计算、未成交部分单列机会成本（`Algo_TCA.md:501-519`、`:517`）。**K3 边界**：模型只用于评估标准化与盘前单内部展示，不对外作事前预测（`docs/report-tca-known-limitations.md` K3 仅在评估标准化范围内重开）。

### 2.2 技术方案（细化到文件与函数）

**拟合与产物**（`CostView/src/evaluation/expected_cost.py` 新建 + `CostView/src/evaluation/models/` 模型目录）：

- `fit_expected_cost_models(mgr, *, start_date, end_date) -> dict[str, ImpactModel]`：从 `tca_route_summary` 取样本 `(par_rate, daily_volatility, impact_bps)`——impact 取 `wagner_is_bps`（Wagner IS 分解的冲击分量；缺失回落 `arrival_cost_bps`）；`daily_volatility` 按 `equ_ticker × order_as_of_date` join `bdib_daily_summary`（DL-10 同源）；按 `Exchange` 市场组分别 `fit_impact_model`（样本 <30 的市场组不产模型并披露）；
- 产物 JSON 落 `CostView/src/evaluation/models/impact_<market>_<COST_MODEL_VERSION>.json`（git 跟踪——可复现、可 diff、可回滚；含 fit 元数据：样本窗口/n/r²/域/生成时间）；
- `load_expected_cost_model(market) -> ImpactModel | None`：按市场加载（无模型返回 None，消费方降级可见）；
- `COST_MODEL_VERSION = "cost-model-v1"`（口径变更升版，文件名与载荷均带版本）。

**timing risk 与难度纯函数**（同模块，无 IO）：

- `timing_risk_bps(annual_vol_pct, duration_min, session_minutes)`：σ√T——年化波动 ÷ √252 得日 σ，× √(duration ÷ session_minutes)；session_minutes 由 DL-03 注册表（开收盘时长）提供；
- `required_duration_min(qty, participation, adv)`：所需交易时长 = qty ÷ (p* × ADV)（分钟，按会话内速率）；
- `close_capacity_pct(close_qty, avg_close_auction_vol)`：收盘段量 ÷ 日均收盘竞价量（阈值按市场校准——v0 用统一阈值 + notes 标注待校准）；
- `expected_cost_bps(model, participation, volatility)`：薄封装 `ImpactModel.predict_bps` + 域检查（域外 None，不外推）。

**契约**（`platform_data/contracts/market_contracts.py` 扩展）：

- `OrderDifficulty`（frozen dataclass）：`expected_cost_bps`、`timing_risk_bps`、`required_duration_min`、`close_capacity_pct`、`model_version`、`in_domain`（域外为 False 且成本字段 None）；
- `COST_MODEL_VERSION` 常量（与 CostView 侧同名常量由契约测试互锁）。

**CLI**（`CostView/src/__main__.py` 增 `--query fit-cost-model`）：一键拟合 + 落盘 + 打印各市场组摘要（n/r²/域）；`--query cost-calibration`：时间切分样本外校准报告。

**测试**（`backend/api/tests/test_expected_cost_model.py` 新建）：

1. 纯函数：timing_risk（年化→日 σ→√T 手算）、required_duration、close_capacity、域检查（域内/域外 None）；
2. 拟合集成（tmp 库夹具：tca_route_summary 20+ 行 + bdib_daily_summary 波动列）：`fit_expected_cost_models` 按市场分组、样本不足组不产模型、模型落盘 JSON 可回读；
3. **时间切分样本外校准**（真实数据，PR 附输出）：前 4 个月拟合 → 后 2 个月验证——z =（预期 − 实际）÷ timing_risk 的均值 ≈0、std ≈1（分规模档 × 算法族）；分位数覆盖率（预测 10/50/90 分位对实际冲击的覆盖）；
4. 契约互锁：`COST_MODEL_VERSION` 两侧一致 + `OrderDifficulty` 字段完整。

### 2.3 检验方法（= 验收标准）

1. 时间切分样本外：各规模档、算法族 z 均值约 0、标准差约 1（容差内）；
2. 分位数覆盖率报告（校准证据，PR 附）；
3. 域外不外推（`in_domain=False` → 成本 None）+ 校准报告归档 docs/；
4. 用途限定：评估标准化与盘前单展示（K3 对外边界不变，docstring 明示）；
5. 既有全量不回归（backend + CostView 分进程）。

### 2.4 边界与裁剪（诚实记录）

- **K3 边界**：本模型是「评估标准化的共同分母」与「内部盘前算账」，不对外作事前成本预测——`cost_model.py` 的禁项本模块继承并显式传递；
- **市场组粒度**：按 Exchange 分组（非 Exchange × 算法族）——DL-05 盘点显示单元稀疏（355 单元 n≥500 仅 37），族级拟合样本不足；族级细分留待数据积累；
- **参与率口径**：`par_rate`（区间参与率，路由级可得）；`pct_adv`（fill_attribution_metrics）留待 DL-09 后升级；
- **收盘容量阈值**：v0 统一阈值 + 待市场校准标注（DL-13 tasks 原文「阈值按市场校准」需真实竞价量数据，DL-09 后细化）。

## 3. 规模与拆分说明

预估 diff 约 480 行（模块 ~170 + CLI ~40 + 契约 ~30 + 模型产物 ~10 + 测试 ~180）。DL-13 为验收原子单元（拟合 + 契约 + 校准一次交付才能被 DL-18/23 消费），沿用单 PR 先例。

## 4. 范围锁

| 动作 | 文件 |
|---|---|
| 新建 | `CostView/src/evaluation/expected_cost.py` |
| 新建 | `CostView/src/evaluation/models/`（拟合产物 JSON，git 跟踪） |
| 修改 | `CostView/src/__main__.py`（`fit-cost-model` / `cost-calibration` 两个 query） |
| 修改 | `platform_data/contracts/market_contracts.py`（`OrderDifficulty` + `COST_MODEL_VERSION`） |
| 修改 | `platform_data/contracts/__init__.py`（导出） |
| 新建 | `backend/api/tests/test_expected_cost_model.py` |
| 新建 | `specs/068-expected-cost-model/plan.md`（本文件） |

范围外（不碰）：DL-09 快照表、族级拟合细分、`data_access/`、MarketView 端点（DL-14）、DL-18 打分消费、对外预测任何路径（K3 禁项）。

## 5. 验收（P4）

| 需求（057 DL-13 检验方法） | 覆盖 | 结果 |
|---|---|---|
| 时间切分样本外 z 均值≈0/std≈1 | 用例 3（真实数据）+ PR 输出 | 待实施后回填 |
| 分位数覆盖率报告 | 用例 3 + 校准输出 | 待实施后回填 |
| 域外不外推 + 校准报告 | 用例 1/4 + docs 归档 | 待实施后回填 |
| 用途限定（K3 边界） | docstring + 契约 notes | 待实施后回填 |
| 既有测试不回归 | backend + CostView 全量分进程 | 待实施后回填 |

## 6. 本次不做

- 族级（Exchange × 算法族）拟合细分（样本不足，留待数据积累）；
- 收盘容量阈值的市场校准（需 DL-09 竞价量数据）；
- DL-14 盘前单展示消费与 DL-18 打分接入（后续子任务）；
- 任何对外事前预测路径（K3 禁项，长期边界）。
