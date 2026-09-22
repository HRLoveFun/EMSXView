# 028b 波动率量纲：归一化下线，改为只检测不修改

**Feature**: `028b-volatility-scale-monitor`　**Branch**: `028b-volatility-scale-monitor`　**Date**: 2026-09-22　**状态**: ✅ 已完成并归档（PR #78；2026-09-22 归档）

**定位**：028 引入的「小数写法归一化」在上游修复根因后**必须下线** —— 继续修数会把
**真实低波动标的误放大 100 倍**。本计划将其收敛为纯监测。

**前序**：`docs/archive/2026-09-21/028-volatility-scale-fix/`（问题定位与本侧过渡措施）

---

## 1. 上游闭环结果（2026-09-22，跨仓请求已答复）

| 项 | 上游结论 |
|---|---|
| **权威定义** | `daily_volatility` **不是**本地计算，而是直取 Bloomberg **`VOLATILITY_30D`**（30 交易日年化历史波动率，**百分比单位**，`26.0` = 26%）—— 本侧反推结论成立 |
| **写入路径** | 全仓库仅一条（`CalculateDailyMetrics` → `upsert_daily_summary`），无第二条计算路径 |
| **根因** | 异常精确定位到**单次运行批次**：`computed_at = 2026-04-22`（08:21~10:17），覆盖 `20260302~20260420`，36,547 行中 36,372 行为小数写法（÷100）；属**抽取（2026-09-02）之前**的旧版写入产物（该批 `intraday_volatility` 全 NULL 佐证） |
| **已修复** | 回填 36,372 行 ×100（含 CSV 备份与幂等保护；`scripts/ops/fix_daily_volatility_scale.py`） |
| **已加守卫** | 批次级中位数守卫（`GUARDRAIL_DAILY_VOLATILITY_SCALE_CHECK` 等 3 项配置 + 6 例单测），防复发 |
| **未改动** | 该批次 **168 行 ≥ 3**（批次内异质/脏点）—— 无法用统一缩放还原，边界清单已落盘 |

## 2. 本侧复核（2026-09-22，只读实测，与上游报告完全吻合）

| 项 | 上游报 | 本侧复核 |
|---|---|---|
| 月均值 202603 / 202604 | 53.11 / 50.85 | **53.11 / 50.85** ✅ |
| `1942 JP Equity` 202603 | 34.4~72.0 | **34.428~72.012**（逐日一致）✅ |
| `daily_volatility < 3` 行数 | 36,372+ → 残余 | **36,480 → 112**（降 99.7%）✅ |

**残余 112 行的性质（决定本计划的关键）**：经逐条核对为**真实低波动标的** ——
`K US Equity` 1.16~1.46、`ITRK LN Equity` 1.43~1.46、`6201 JP Equity` 1.23；
批次分布为 `2026-08-19`（63 行）、`2026-08-17`（25 行）、`2026-04-22`（**仅 4 行**）等
—— 即绝大多数来自**完全正常的批次**。

> 结论：`< 3` 已不再等价于「量纲错误」。继续 ×100 会把这 112 个真实低波动值
> **误放大 100 倍**（年化 1.16% → 116%），方向性错误比不处理更严重。

## 3. 改动

| # | 改动 | 位置 |
|---|---|---|
| D1 | `normalize_volatility_to_percent`（修改值）→ **`volatility_scale_suspect`**（返回 `bool`，**不修改数据**） | `env_context.py` |
| D2 | `RouteEnvContext.volatility_normalized` → **`volatility_scale_suspect`**；`daily_volatility` **原值直传** | 同上 |
| D3 | `env_coverage.volatility_scale_fixed` → **`volatility_scale_suspect`**（登记数，非修改数） | 同上 |
| D4 | 口径声明：新增 `volatility_source`（Bloomberg `VOLATILITY_30D`）；披露键更名；`SPEC_VERSION` → **`2026.09.11`** | `report_spec.py` |

**不改**：`bucket_volatility` 阈值（25 / 40）保持不变 —— 它按年化百分比解读，与上游
确认的权威定义一致，028 的该项修复**继续有效**。

**不做**：不触碰上游数据；不代为修正未改动的 168 行（清单由上游提供）。

## 4. 检验

| 项 | 标准 |
|---|---|
| 检测语义 | 0.8 / 2.0 → 登记；26.075 / 80.0 → 不登记；None / NaN → 不登记 |
| **不修改原值** | 夹具 ORCL `0.8` 进入上下文后仍为 **0.8**（非 80.0），且 `volatility_scale_suspect is True` |
| 真实低波动被登记但不改 | `1.16` / `1.43` 登记为可疑（宁可多登记也不误改） |
| 登记数披露 | `env_coverage.volatility_scale_suspect == 1` |
| 常量与 spec 一致 | `VOLATILITY_SCALE_CUT` / `VOLATILITY_UNIT` ↔ `report_spec` |
| 回归 | `pytest CostView/tests/` 全绿（028b 后 **311 passed**） |

## 5. 风险与回退

- **风险**：若未来又出现小数量纲批次，本侧只登记不修正 → 该维度分层会失真。
  缓解：登记数随 payload 披露（可见）+ 上游已加批次级守卫（写入侧拦截）；
  两者叠加后「静默失真」的窗口很窄。
- **回退**：如需恢复修数语义，改回 `value * 100` 即可（单函数），但须先确认
  残余 `< 3` 行仍属量纲错误。

## 6. 关联

- 上游闭环记录：见本文 §1（跨仓请求的答复，2026-09-22）
- 前序 spec：`docs/archive/2026-09-21/028-volatility-scale-fix/`
- 口径治理：`docs/report-tca-known-limitations.md` 第十八轮、ADR-0018 §10.12
