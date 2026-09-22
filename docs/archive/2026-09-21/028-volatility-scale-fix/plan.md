# 028 波动率量纲统一与分桶阈值修正

**Feature**: `028-volatility-scale-fix`　**Branch**: `028-volatility-scale-fix`　**Date**: 2026-09-21　**状态**: ✅ 已完成并归档（PR #76；2026-09-21 归档）

**定位**：修复 `volatility` 环境维度的两处口径问题 —— 单位统一与分桶阈值错配。
证据全文见 [`research.md`](research.md)（只读实测，8 个探测脚本）。

---

## 1. 问题（两条，均有实测证据）

| # | 问题 | 证据 |
|---|---|---|
| P1 | `bucket_volatility` 阈值（1.5/3.5）是**日**波动率空间，而 `bdib_daily_summary.daily_volatility` 是**年化**百分比（中位 26.075）→ 82.9% 落 `stressed`、`typical` 仅 0.61%，维度失效 | 反推比值 ≈ √252（12/12 个月）；`market.py:50-51` 用 25/40 解读同一列 |
| P2 | 上游在 **202603/202604** 区间把该列写成**年化小数**（同标的跳变 ≈ 100 倍后恢复，如 `1942 JP` 43.566 → 0.435 → 45.917） | 同标的跨月序列；`<1.5` 行占比 54.8% / 58.5% 集中于该区间 |

另核实（**结论经上游纠正，2026-09-22**）：`intraday_volatility`（`bdib_daily_summary`，
非空 38.7%）**已年化，但为小数形态**（`std(10 秒对数收益率) × sqrt(BARS_PER_YEAR)`，
`BARS_PER_YEAR ≈ 589,680`）。我最初按 `intraday / daily` 得到 0.0149 并判为「未年化」，
**属单位未对齐**（daily 是百分比、intraday 是小数）；正确判据为
`intraday / (daily / 100)`，实测中位 **1.25** ≈ 1.3，即两列同为年化。

推论更正：旧阈值 1.5/3.5 对该列**不适用**（它按百分比空间定义）；若将来启用
`intraday_volatility` 做分层，须先 ×100 转百分比。`fill_bdib` 两列的量纲本次未再核实。

---

## 2. 改动（三点）

| 改动 | 位置 | 内容 |
|---|---|---|
| D1 单位统一 | `env_context.py` | `normalize_volatility_to_percent`（界值 `VOLATILITY_SCALE_CUT = 3.0`：正常年化百分比 ≥ 5、正常年化小数 ≤ 2，中间为空档）；`RouteEnvContext.volatility_normalized` 标志；命中数经 `env_coverage.volatility_scale_fixed` **披露**，不得静默修数 |
| D2 阈值对齐 | `tca_utils.bucket_volatility` | 阈值 1.5/3.5 → **25/40**（与 `market.py:50-51` 解读同一列的口径一致），标签同步（`<25% ann.` 等）；入参语义改为年化百分比，小数归一化**不在分桶层兜底**（分桶保持纯函数） |
| D3 口径声明 | `report_spec.py` | `volatility_unit` / `volatility_scale_cut` / `volatility_scale_fixed_disclosure`；`SPEC_VERSION` → `2026.09.10`；三处同步（`known-limitations` 第十七轮 / ADR-0018 §10.11） |

**不做**：不改上游数据（跨仓项：请上游确认权威定义 + 修正 202603/202604，见 progress L1/L2）；
不给日内列做年化（它的口径本就是日内，配日内阈值即可）。

---

## 3. 检验

| 项 | 结果 |
|---|---|
| 归一化判别 | 小数 0.8→80、2.0→200；百分比 26.075 原样；None / NaN 不动 |
| 命中披露 | `env_coverage.volatility_scale_fixed == 1`（夹具含一行小数写法） |
| 界值与 spec 一致 | `VOLATILITY_SCALE_CUT` / `VOLATILITY_UNIT` ↔ `report_spec` |
| 分桶边界 | 20→calm / 30→typical / 50→stressed / None→unknown |
| 全量分布（真实库） | calm 30.82% / typical 35.65% / stressed 33.53%（修复前 16.47% / 0.61% / 82.92%） |
| 回归 | `pytest CostView/tests/` **310 passed** |

---

## 4. 风险与回退

- 归一化界值 3.0 属启发式：若上游未来产出真实的年化 <3% 标的（极端低波），会被误放大 ——
  由命中披露暴露，且跨仓确认后可收紧或移除；
- 阈值 25/40 沿用 `market.py` 既有常量（仓库内一致性），权威数值待上游确认后校准；
- 回退：revert 单个 commit 即可（无数据迁移、无 Schema 变更）。

---

## 5. 关联

- 前序：`docs/archive/2026-09-21/026-costview-algo-eval/`（阶段二引入该列）、
  `docs/archive/2026-09-21/027-algo-eval-report/`（实测暴露该维度退化）
- 口径治理：`docs/report-tca-known-limitations.md` 第十七轮、ADR-0018 §10.11
- 待办：progress L1~L3（跨仓确认与上游修正）
