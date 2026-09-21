# 027 算法执行质量综合评估报告

**Feature**: `027-algo-eval-report`　**Branch**: `027-algo-eval-report`　**Date**: 2026-09-21　**状态**: 实施中

**定位**：改造 026 阶段三交付的评估层 —— 从「交互式比较工具」改为「按时间范围自动产出的综合评估报告」。

**门控规范**: `docs/spec/plan-design-principles.md`（G0-G3）、`docs/spec/git-workflow.md`、`docs/spec/adr/0700-git-worktree-parallel-workflow.md`

---

## 1. 背景

### 1.1 用户反馈（逐字）

> 查看了前端Evaluation模块，和用户设想的结果有所偏离。比较维度、基准、检验方法等不应该是选择的，用户需要的是全面的综合评估，设想的是增加report模块输出报告的维度和面向，所以必须按照时间范围做评估。当前结果不合题意。
>
> 另外，前端中点击开始评估提示评估失败。

### 1.2 澄清结论（用户已通过选项确认，共四项）

1. **落位形态 = 两者结合**：Report 内嵌评估摘要章节 + 独立 Tab 展示更细的分维度明细。
2. **「面向」= 算法执行质量评估中的「比较维度」** —— 即报告要**自动覆盖全部比较维度**，而不是让用户选一个。
3. **内容领域 = 六项全选**：券商/算法执行质量（含可比置信度）、环境分层表现、时间趋势与稳定性、风险与尾部、市场维度、数据可信度。
4. **可比性处理 = 改为分层内比较**：在同一层内比较（层内 Exchange/时段天然一致），层内样本不足才标注；**不再做整体分布检查**。

### 1.3 重新审视后确认的两个真实问题

**问题 A：形态错位（用户指出）**

026 交付的 `EvaluationView` 是「用户选 1 个维度 + 1 个基准 + 1 种方法 → 出 C(n,2) 两两检验表」。这三点选择本身就是需求错位 —— 用户要的是**一份按时间范围自动产出的综合评估**。

**问题 B：可比性判定在真实数据上必然拒绝（本次实测发现，比 A 更严重）**

拿真实库执行 026 的实现（`20260401`~`20260430`，`cohort=broker`）：

```
comparable = False
reasons    = ["组样本不足 10 条：EQ-BMO, EQ-CICC",
              "分层分布失衡（总变差距离超阈值）：Exchange, time_of_day, liquidity_adv20"]
imbalance  = {"Exchange": 1.0, "time_of_day": 0.9286, "liquidity_adv20": 0.6923}
common_strata = 0
```

两处设计错误：

| # | 错误 | 说明 |
|---|---|---|
| B-1 | 以「两组整体分布一致」作为可比前提 | 真实业务里券商成交**本就横跨多个交易市场**，两个券商的市场分布天然不可能一致 → `Exchange` TVD 恒为 1.0（理论最大值）→ **永远判不可比** |
| B-2 | 要求 5 个维度**交叉**后存在「共同分层」 | 交叉越细层越空，`common_strata = 0` → 精确分层匹配永远无可用样本域 |

**根因**：把教科书里的**前提条件**当成了**门禁**。B3 要求的是「在这些维度足够相似时才具解释力」—— 正确做法是用分层来**控制**（层内比较，剔除构成差异），而不是用来**拒绝**（整体分布不一致就整体不比较）。

### 1.4 故障：前端提示「评估失败」

已完成的诊断（三层）：

| 层 | 验证 | 结论 |
|---|---|---|
| 服务层 | 直接调 `build_evaluation_comparison`（3 case） | ✅ 正常返回，无异常 |
| HTTP 层 | `TestClient` 打真实端点（含模拟前端 filters） | ✅ **200 OK** |
| 前端逻辑 | 比对 `fetchScorecard` 范式 / filters 默认值 | ✅ 无 undefined 风险 |

**剩余最可能原因**：后端进程未加载新路由（未重启 / 或前端 `VITE_API_URL` 指向 #71 之前创建的并行 worktree 后端）→ 404。
**待用户提供**：界面上「评估失败」下方的具体错误文本（`Not Found` / `Failed to fetch` / 其它）。

> 本项作为 P0 第一步：拿到错误文本后定位并修复；若确为「后端未重启」则属环境问题，同时补一条**端点级冒烟用例**（026 遗留 T16 同源，一并解决）。

---

## 2. 目标形态

### 2.1 一句话

> **输入 = 时间范围（+ 作用域过滤）；输出 = 覆盖全部比较维度与六项内容领域的综合评估报告。**

「不应该是选择的」三件事，改为**报告自动执行的内建规则**：

| 现状（错） | 改为 |
|---|---|
| 用户选 1 个**比较维度** | **遍历全部维度**（broker / strategy / broker_strategy / asset_class / Exchange / 环境三维） |
| 用户选 1 个**基准** | **多个基准并列**（决策基准 `arrival` + 市场时间基准 `vwap` + 收盘 `close`；D1 本就要求同时呈现） |
| 用户选 1 种**检验方法** | **三种方法都跑**（t / KS / χ² 各回答不同问题，并列呈现） |
| 不可比 → 拒绝输出 | **分层内比较** + 层覆盖率/置信度标注（结论照出，可信度显式） |

### 2.2 界面分工（两处同一数据源）

| 位置 | 内容 | 约束 |
|---|---|---|
| **Report 报告内嵌章节**（`tca_report_html.py` + `ReportView`） | **评估摘要**：各维度 Top/Bottom、关键告警、可信度概览 | 总行数受限（沿用既有渲染上限约定），随报告一起导出 |
| **独立 Tab**（`EvaluationView` 重构） | **分维度明细**：完整分组表、分层比较、趋势、风险、市场、可信度 | 输入仅时间范围，无选择器 |

**硬约束**：两处消费**同一编排函数**的同一份 payload，禁止各自拼装（`docs/report-tca-known-limitations.md:68-69`）。

---

## 3. 设计决策

### DP-1：比较的组织方式 —— 从 C(n,2) 全组合改为「每组 vs 总体中位数」

26 个 broker 的 C(26,2) = 325 对检验，对**报告**没有可读性。改为：

- 每个维度内，对每个分组做**一次**检验：该组成本 vs **该维度全样本中位数**（非参数基准，不假设分布）；
- 输出「成本水平 + 样本量 + 可信区间 + 是否显著偏离中位数 + 校正后 p」；
- 可选附「最优组 vs 最差组」一对（报告摘要用）。

依据：报告读者的真实问题是「谁偏离常态、偏多少、可信吗」，不是「枚举所有对」。

### DP-2：分层内比较（替代整体分布判定）

**算法**：对每个比较，先在**共同层**内计算效应量，再按层样本量**加权合并**。

- **分层键**（控制变量）：`Exchange` + 环境三维（`time_of_day` / `liquidity_adv20` / `volatility`）。**不含** `asset_class`（与 Exchange 高度共线，且多数为 equity）。
- **层内准入**：层内两侧样本均 ≥ `MIN_STRATUM_SAMPLE`（默认 3）才纳入；不足则该层记入「未纳入层数」并在 payload 披露；
- **合并**：样本量加权（固定效应）；同时给出**层间异质性**（层效应极差 + 纳入层数），让读者看到「结论是否依赖某一层」；
- **退化**：纳入层数 < 2 → 退化为整体比较，并**显式标注 `stratified: false` + 原因**（不是静默，也不是拒绝）；
- **披露**：`层覆盖率 = 纳入层样本量 / 总样本量`，低于阈值时告警。

删除：`assess_comparability` 的「门禁」语义（不再因整体 TVD 超阈值而拒绝输出）。TVD 保留为**描述性指标**（可作 `confidence` 标注输入），不再是阻断条件。

### DP-3：基准不选，并列呈现

- 计算三个基准：`arrival`（决策基准）/ `vwap`（市场时间基准）/ `close`（收盘基准）；
- **检验只在主基准上做**（固定 `arrival`，不暴露选择器）—— 三个基准各做一遍会使结果膨胀 3 倍，无益于可读性；
- 三个基准的**均值 / 中位数 / 尾部**并列显示（这是 D1「同时呈现决策基准与市场时间基准」的落点）。

### DP-4：方法不选，三种并列

每个比较同时给出 t / KS / χ² 结果（分布差异 vs 均值差异语义不同）。
多重比较校正（BH）仍保留 —— DP-1 下每个维度内做 N 次「vs 中位数」检验，必须校正。

### DP-5：唯一输入 = 时间范围

- 复用 Report 的筛选器（日期预设 / 自定义区间 / 市场 / broker / 算法 / 标的）；
- 移除维度、基准、方法、alpha、correction 等全部选择器；
- 周度粒度复用 026 阶段一能力（`granularity=week` 用于趋势与稳定性分析）。

### DP-6：026 资产的复用 / 改造 / 废弃

| 026 资产 | 处置 |
|---|---|
| 粒度期间键（`report_measure`） | **复用** |
| 环境上下文（`env_context`） | **复用**（分层键来源） |
| 检验与区间（`stats_tests`） | **复用**，新增「vs 中位数」与分层合并的调用方式 |
| 功效（`power`） | **复用**（层内样本量指引） |
| 冲击模型（`cost_model`） | **复用**（作为独立小节） |
| 治理（`governance`） | **复用** |
| `comparability.assess_comparability` | **改造**：门禁 → 分层可用性描述 |
| `build_evaluation_comparison` + `/api/tca/evaluation/compare` | **废弃**：改为报告编排的内部单维度比较函数；端点由 `/api/tca/evaluation/report` 取代 |
| `EvaluationView` 的选择器形态 | **废弃**：重构为分维度明细视图 |

> 废弃理由：这三项正是「需求错位」的载体。保留它们等于保留错误形态，且会形成两套口径（违反单点实现约定）。`/compare` 于 026 收尾（PR #71）引入、尚无外部消费者，移除成本最低。

---

## 4. 后端设计

### 4.1 新增模块

```
CostView/src/evaluation/
├── stratified.py      # [NEW] 分层内效应 + 加权合并 + 层可用性披露
├── report.py          # [NEW] 综合评估编排（遍历维度 → 组装 sections）
├── comparability.py   # [改造] 门禁 → 分层可用性描述；TVD 降为描述指标
└── __init__.py        # [改造] 导出登记（TestEvaluationExport 护栏）
```

### 4.2 输出结构（草案）

```jsonc
{
  "period":   { "start_date": "...", "end_date": "...", "granularity": "week" },
  "scope":    { "...": "..." },
  "benchmarks": ["arrival", "vwap", "close"],
  "primary_benchmark": "arrival",
  "governance": { "...": "..." },
  "sections": {
    "credibility": { "coverage": {}, "env_coverage": {}, "degradations": [] },
    "dimensions": [
      { "dimension": "broker",
        "groups":      [ { "label": "EQ-CITI", "sample_size": 151,
                           "benchmarks": { "arrival": {...}, "vwap": {...}, "close": {...} },
                           "vs_median":  { "difference": -1.2, "ci": [-2.1, -0.3],
                                           "tests": { "t-test": {...}, "ks": {...}, "chi2": {...} },
                                           "p_adjusted": 0.004, "confidence": "high" } } ],
        "stratification": { "strata_used": 6, "strata_skipped": 3,
                            "coverage": 0.92, "stratified": true },
        "highlights": { "best": "...", "worst": "...", "alerts": [] } }
    ],
    "trend":  { "by_week": [ { "period": "2026-W14", "mean": ..., "std": ..., "n": ... } ] },
    "risk":   { "cost_volatility": ..., "cvar": ..., "p95": ..., "anomaly_share": ... },
    "market": { "by_exchange": [ { "exchange": "US", "n": ..., "arrival_bps": ... } ] }
  }
}
```

### 4.3 编排入口

`TcaQueryService.build_evaluation_report(filters, *, granularity=..., max_routes=...)`

- 一次取数（复用 `_collect_routes`），一次环境上下文构建，供全部维度与全部小节消费（避免 N 次取数）；
- 逐维度调用分层比较；组装 `sections`；
- 移除 `build_comparison`（原 `build_evaluation_comparison`）的对外暴露。

### 4.4 端点

- **新增** `POST /api/tca/evaluation/report`（输入：时间范围 + 作用域过滤；无维度/基准/方法参数）；
- **移除** `POST /api/tca/evaluation/compare`；
- 门控 `TCA_EVAL_ENABLED` 保留（语义不变：关闭返回**显式不可用**）；
- `GET /api/tca/capabilities` 的 `evaluation` 位保留；
- **补齐门控降级用例**（026 遗留 T16）。

### 4.5 Report 内嵌

- `report_aggregator.build_report(...)` 增加 `evaluation` 键（**同一份 payload 的摘要切片**）；
- `tca_report_html.py` 新增 `_render_evaluation_section(...)`，插入到覆盖率小节之前。

---

## 5. 前端设计

### 5.1 `EvaluationView` 重构

- **移除**：维度 / 基准 / 方法 / alpha / correction / 最小样本 等全部选择器；
- **保留**：时间范围（复用 Report 的筛选状态）+ 刷新按钮；
- **新增**：分维度折叠面板（每个维度一节：分组表 + 分层披露 + 高亮）；趋势 / 风险 / 市场 / 可信度四个小节；
- 取数改用仓库统一取数层 `@shared/hooks/use-async-data`（对齐 `ReportView` 与 T11 约定，替代 026 的手写 `useState` + `fetch`）。

### 5.2 `ReportView` 内嵌摘要

- 报告末尾（覆盖率小节前）插入「算法执行质量评估」摘要卡片：各维度 Top/Bottom + 告警 + 可信度；
- 与 HTML 报告章节**逐字对齐**（既有约定：前端文案与 HTML 渲染器对齐）。

---

## 6. 改动落点

| 文件 | 性质 |
|---|---|
| `CostView/src/evaluation/stratified.py` | **新增** |
| `CostView/src/evaluation/report.py` | **新增** |
| `CostView/src/evaluation/comparability.py` | 改造（门禁 → 分层可用性） |
| `CostView/src/evaluation/__init__.py` | 改造（导出登记） |
| `CostView/src/tca_query_service.py` | 改造（`build_evaluation_report`；移除单维度比较的对外暴露） |
| `CostView/api/routers/costview.py` | 改造（新端点 + 移除 `/compare` + 门控用例） |
| `CostView/src/monitoring/report_aggregator.py` | 改造（report 增加 `evaluation` 摘要键） |
| `CostView/src/monitoring/tca_report_html.py` | 改造（评估章节渲染） |
| `CostView/src/monitoring/report_spec.py` | 修改（评估口径声明；`SPEC_VERSION` bump） |
| `CostView/module/components/EvaluationView.tsx` | 重构（去选择器 + 分维度明细） |
| `CostView/module/components/ReportView.tsx` | 改造（内嵌摘要） |
| `CostView/module/services/api.ts`、`types.ts`、`lib/filters.ts` | 改造（契约更新） |
| `CostView/tests/test_evaluation.py`、`test_report_metrics.py` | 改造 / 新增 |
| `docs/report-tca-known-limitations.md`、`docs/spec/adr/0018-tca-report-metrics-conventions.md` | 修改（口径同步） |

---

## 7. 检验方式

| 检验项 | 方法 | 通过标准 |
|---|---|---|
| 分层合并正确性 | 合成数据：已知层效应 + 已知层权重 | 合并值 = 手算加权结果 |
| 层内样本不足 | 构造某层一侧仅 2 条 | 该层不纳入，`strata_skipped` 增加，覆盖率下降 |
| 无可用层退化 | 构造层数 = 1 | `stratified=false` + 原因，**仍输出**整体比较结果 |
| vs 中位数检验 | 构造已知偏离/不偏离的组 | 结论正确；BH 校正生效 |
| 真实数据端到端 | 真实库跑 `broker` 维度 | **不再返回「不可比/无结论」**，26 组均有水平 + 置信度 |
| 报告渲染 | 生成 HTML + CSV | 章节存在、行数受限、与前端文案一致 |
| 门控降级 | `TCA_EVAL_ENABLED=0` | 显式不可用；**端点级用例覆盖**（T16） |
| 回归 | 全量 `pytest` + vitest + lint | 全绿；既有 Report / Monitoring 产出零变化 |

---

## 8. 风险与回退

| # | 风险 | 缓解 | 回退 |
|---|---|---|---|
| R-1 | 分层合并引入方法学复杂度，读者难以理解 | 报告同时披露层数 / 覆盖率 / 层间异质性；文案解释「为什么要分层」 | 置 `stratified=false` 走整体比较（已实现退化路径） |
| R-2 | 报告 payload 变大 → 生成变慢 | 一次取数、全部小节共用；`EXPLAIN QUERY PLAN` 校验；摘要层限行 | 关闭评估门控 |
| R-3 | 移除 `/compare` 造成破坏 | 该端点于 PR #71 引入、尚无外部消费者；移除与新增同 PR，避免中间态 | 保留旧端点一个版本（如确需） |
| R-4 | `SPEC_VERSION` 与三处口径文档不一致 | 三处同步 + `TestReportSpec` 护栏 | — |

---

## 9. 不做事项

- K1 显性费用 / K2 L2 订单簿 / K3 事前预测 / K4 可操作性（沿用 026 与 003 的范围外标注）；
- 不改 026 已交付的粒度能力与环境变量派生（复用）；
- 不引入新依赖（分层合并用 numpy / 标准库即可，`scipy` 已具备）。

---

## 10. 关联

- 前序计划：`docs/archive/2026-09-21/026-costview-algo-eval/plan.md`（阶段三评估层；本计划改造其形态与可比性设计）
- 方法论：`docs/textbook/Algo_TCA.md`、`docs/textbook/股票交易执行质量与交易成本分析（TCA）：跨时期学术研究综述与方法框架.md`（B3 分层归因 / B4 评价矩阵 / D1 基准冻结）
- 口径治理：`docs/report-tca-known-limitations.md`、`docs/spec/adr/0018-tca-report-metrics-conventions.md`
- 评估层定位：[ADR-0004](../../../docs/spec/adr/0004-costview-focused-on-evaluation.md)
- 待办：`docs/open-todos.md` T16（门控降级用例，本计划一并解决）
