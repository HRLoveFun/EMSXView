# 062 — 算法族与意图映射

> 父计划：`specs/057-execution-decision-loop/plan.md`（DL-04）
> 分支：`062-algo-taxonomy` · worktree：`../EMSXView-wt-062-algo-taxonomy`
> 依赖：DL-01（058，已完成：`OrderIntent.benchmark` 五值）· 消费者：DL-13（预期成本分组）、DL-18（意图→算法族）、DL-19/20（同类比较）
> 关联：管道 S2 `add_algo_column`（`Broker × StrategyType` → vwap/twap/pov/close/other，指南 §5.2）；`docs/textbook/Algo_TCA.md:654`（同类比较）

## 1. 问题

- **收盘类与 VWAP 类不可同用 arrival 排名**（tasks.md DL-04）：评估必须先按「意图 × 算法族」分组，否则跨族比较把算法类型差异当券商差异；
- **管道五组粒度不足以做同类比较**：`algo` 只有 vwap/twap/pov/close/other；`other` 里混着交叉盘（CROSSING 2,851 条）、管道未命中的 POV（EQ-BOCI/CICC/ICBCI 404 条）、SmartMOC/OnOpen/Close（345 条）——不细分就无法把「同为收盘竞价」的路由放进同一比较单元；
- **意图（DL-01 已产出）与算法族之间无映射**：VWAP/CLOSE/MIX/SPECIAL 该落到哪一族、如何拆分，当前无契约。

## 2. 方案（P2 三栏）

### 2.1 理论依据

同类比较：先按「意图 × 算法族」分组（VWAP 对 VWAP、收盘对收盘），再比券商；跨族比较只回答「这类订单该用哪类算法」（`Algo_TCA.md:654`、`:826-832`）。收盘类与 VWAP 类算法不可同用 arrival 排名（tasks.md DL-04）。

### 2.2 技术方案（细化到文件与函数）

**契约数据**（`platform_data/contracts/algo_taxonomy.py`，新建；纯映射数据 + 纯函数，无 IO）：

- **细分族**：`ALGO_FAMILIES = ("vwap", "twap", "pov", "close", "auction_close", "auction_open", "is", "dma", "liquidity", "other", "unmapped")`
  - 说明：vwap/twap/pov 为管道三组的直接细分；close 与 auction_close 区分「收盘类算法」与「明确的收盘竞价」（MOC/AUCTION/QMOC 等）；auction_open（OnOpen 等开盘竞价）；is（Implementation Shortfall，当前数据 0 样本）；dma（直接市场接入）；liquidity（交叉盘/暗池：CROSSING）；unmapped 为未命中（显式，不静默归 other）
- `FAMILY_TO_COARSE`：细分族 → 管道五组（vwap / twap / pov / close / other）——`coarse_group()` 保证「细分族可映射回五组」；is/dma/liquidity/auction_open/unmapped → other（管道无对应组，差异登记见下）
- `ALGO_TAXONOMY_VERSION`：映射表版本（结构或规则变更升版，语义同前两个版本常量）
- `STRATEGY_TYPE_MAP`：`(broker, strategy_type_normalized) → family` 精确表——种子取自 2026-04-22 至 2026-10-20 真实数据（42 个 distinct StrategyType 全覆盖，Top 组合 30+ 条，如 `(EQ-MS, CLOSE)→auction_close`、`(EQ-GS, AUCTION)→auction_close`、`(EQ-BARCLAY, VWAP-EU)→vwap`、`(EQ-HSBC, POV.)→pov`、`(EQ-GS, PARTCIPTE)→pov`、`(CROSSING, "")→liquidity`）
- 归一化：`normalize_strategy_type()`——upper + 去首尾空白/尾点；空/None 保持空
- 兜底规则（`STRATEGY_TYPE_RULES`，有序）：含 `VWAP`→vwap；含 `TWAP`→twap；含 `POV|PART|VOLINLINE|WITH-VOL`→pov；含 `MOC|CLOSE|AUCTION`→auction_close（`ONOPEN|OPEN` 优先→auction_open）；含 `IS`/`SHORTFALL`/`ARRIVAL`→is；含 `DMA|DIRECT`→dma；含 `LIQ|DARK|CROSS`→liquidity；均未命中→unmapped
- `INTENT_TO_FAMILIES`：意图 → 算法族列表（VWAP→["vwap"]；CLOSE→["auction_close"]；MIX→["auction_close", "vwap"]（两段）；SPECIAL→[]（不映射）；UNMAPPED→[]）——供 DL-18 拆段与 DL-19 分组
- `KNOWN_PIPELINE_GAPS`：本侧细分与管道 algo 列**已知差异清单**（如 EQ-BOCI/EQ-CICC/EQ-ICBCI 的 POV 管道归 other、SmartMOC/OnOpen/Close 管道归 other）——tasks「映射扩展先改管道侧」：本清单供管道侧补映射，DL-06 契约冻结时对齐；本侧契约测试断言「差异集合 ⊆ 已知缺口」（新差异即失败）

**函数**（同文件，纯计算）：

- `classify_algo(broker, strategy_type) -> str`：精确表 → 规则兜底 → unmapped
- `coarse_group(family) -> str`：细分族 → 管道五组
- `intent_families(benchmark) -> tuple[str, ...]`：意图 → 族列表
- `coverage_of(rows) -> dict`：输入预聚合的 `[(broker, strategy_type, count)]`，返回覆盖统计（细分覆盖/未映射清单/与管道差异计数）

**覆盖率脚本**（`scripts/ops/check_algo_taxonomy_coverage.py`，新建；只读）：

- 读 `tca_route_summary` 按 `(Broker, StrategyType, algo)` 聚合（近 6 个月，默认 180 天前起）→ `coverage_of` → 输出：细分族覆盖率、unmapped 清单、`coarse_group ≠ 管道 algo` 的差异清单（分类到已知缺口/新缺口）→ 退出码 0/1（1=覆盖率 <95% 或存在新差异）。
- 与 DL-03 检查脚本同模式（docstring 内置月度/发布前运行说明，脚本 + 清单，不注册计划任务）。

**测试**（`backend/api/tests/test_algo_taxonomy.py`，新建；夹具用虚拟 broker 名 + 公开算法名，不提交真实业务数据）：

1. 精确表命中：`(EQ-MS, CLOSE)`、`(EQ-GS, AUCTION)`、`(EQ-BARCLAY, VWAP-EU)`、`(EQ-HSBC, POV.)`、`(EQ-GS, PARTCIPTE)`、`(CROSSING, "")` 各族正确；
2. 归一化：`VWAP.`→`VWAP`、`Close`↔`close`、None/'' 不抛错；
3. 兜底规则：新 broker（虚拟名）的 `SMARTVWAP`→vwap、`TARGET_MOC`→auction_close、`ONOPEN`→auction_open、`LIQ_SWEEP`→liquidity、`MYSTERY`→unmapped；
4. `coarse_group`：每个细分族都映射到五组之一（全枚举断言）；vwap→vwap、auction_close→close、liquidity→other、unmapped→other；
5. `intent_families`：VWAP/CLOSE/MIX/SPECIAL/UNMAPPED 五值；
6. `KNOWN_PIPELINE_GAPS` 一致性：对种子中的已知缺口组合，`coarse_group(classify(...)) != 管道 algo` 且差异在清单内；非缺口组合 coarse 必须等于管道 algo（用夹具内的管道 algo 标注）；
7. `coverage_of`：注入构造的计数行 → 覆盖率/未映射/差异统计正确；阈值判定边界。

### 2.3 检验方法（= 验收标准）

1. **近 6 个月路由映射覆盖率 ≥95%**：`check_algo_taxonomy_coverage.py` 实跑（2026-04-22 至 2026-10-20 共 127,569 路由），PR 描述附运行输出；
2. **与管道 algo 列逐路由一致**：`coarse_group(classify())` vs 管道 algo，差异集合 ⊆ `KNOWN_PIPELINE_GAPS`（契约测试锁定）；已知缺口清单交管道侧补映射（DL-06 冻结时对齐）；
3. **UNMAPPED 清单进报告**：覆盖率脚本输出 unmapped 明细（broker/strategy/count）；
4. 既有测试不回归（backend 全量 + boundaries）。

### 2.4 管道侧协作边界（诚实记录）

本任务只交付**本侧契约镜像**（策略命名种子、规则、已知缺口清单）。tasks 原文「映射扩展先改管道侧」的管道改动（补 EQ-BOCI/CICC/ICBCI 的 POV、SmartMOC/OnOpen/Close 映射）在 EMSXDataPipeline 仓库按其规范实施——本侧以 `KNOWN_PIPELINE_GAPS` 作为协作输入，DL-06 契约冻结时复核并删除已对齐项。

## 3. 规模与拆分说明

预估 diff 约 480 行（契约数据 ~200 + 函数 ~110 + 覆盖率脚本 ~90 + 测试 ~180）。DL-04 为验收原子单元（契约 + 映射 + 覆盖率证据一次交付），沿用 DL-01/02/03 经用户确认的单 PR 先例。

## 4. 范围锁

| 动作 | 文件 |
|---|---|
| 新建 | `platform_data/contracts/algo_taxonomy.py` |
| 修改 | `platform_data/contracts/__init__.py`（导出） |
| 新建 | `scripts/ops/check_algo_taxonomy_coverage.py` |
| 新建 | `backend/api/tests/test_algo_taxonomy.py` |
| 新建 | `specs/062-algo-taxonomy/plan.md`（本文件） |

范围外（不碰）：管道仓库（映射扩展由管道侧实施）、CostView 消费改造（DL-19 分组、DL-13 成本分组）、ExecutionView（DL-18 意图→族）、`docs/textbook/Algo_TCA.md`、任何评估/报告口径变更。

## 5. 验收（P4）

| 需求（057 DL-04 检验方法） | 覆盖 | 结果 |
|---|---|---|
| 近 6 个月路由映射覆盖率 ≥95% | 覆盖率脚本实跑 + PR 输出 | 待实施后回填 |
| 与管道 algo 列逐路由一致（可映射回五组） | 契约测试 6（差异 ⊆ 已知缺口） | 待实施后回填 |
| UNMAPPED 清单进报告 | 脚本输出 + 用例 7 | 待实施后回填 |
| 既有测试不回归 | backend 全量 + boundaries | 待实施后回填 |

## 6. 本次不做

- 管道侧映射补全（`KNOWN_PIPELINE_GAPS` 交管道侧，DL-06 对齐）；
- CostView 评估分组改造（DL-19）、预期成本分组（DL-13）、建议单分组（DL-18）；
- 把 algo 族接入任何报告/排名口径（DL-19 起）。
