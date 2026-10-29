# 064 — 数据盘点与额度测量

> 父计划：`specs/057-execution-decision-loop/plan.md`（DL-05）
> 分支：`064-data-inventory-quota-probe` · worktree：`../EMSXView-wt-064-data-inventory-quota-probe`
> 依赖：DL-01（058，盘前单意图覆盖率已交付）、DL-04（062，算法族契约已交付）· 消费者：DL-07/08（额度预算与缓冲）、DL-10（基线回退）、DL-20/23（配对与单元粒度）
> 关联：`CostView/src/evaluation/power.py`（MDE 闭式公式，复用）、DL-03（061，会话注册表——收盘时刻探测的地基）

## 1. 问题

- **评估设计缺样本结构依据**：D1 订单内配对与 D2 模型调整的主次、排名单元粒度（券商 × 算法族 × 市场组 × 规模档）取决于样本结构——先算功效再下结论，否则把稀疏单元当结论；
- **盘中作业（DL-07/08）的额度预算没有实测值**：GetFills 当日成交可得性与延迟、各市场收盘后 bar 完整所需缓冲、日更各阶段耗时与请求数——指南均未记载，须在交易机实测；
- **「下达时刻状态可由 BDIB 事后还原」这一前提未核实**（tasks.md DL-05）：BDIB 10 秒 bar 是否覆盖当日订单簿全部证券（含无成交证券）未知。

## 2. 方案（P2 三栏）

### 2.1 理论依据

评估设计的主次与单元粒度取决于样本结构，先算功效再下结论；盘中作业的额度预算要先有实测（tasks.md DL-05）。

### 2.2 技术方案（细化到文件与函数）

**盘点 CLI**（`CostView/src/monitoring/data_inventory.py` 新建 + 接入 `CostView/src/__main__.py` 的 `--query inventory`；只读，退出码沿用 0/2/3 语义）：

1. **D1 配对候选占比**：`tca_route_summary` 按 `(OrderId, order_as_of_date, Exchange, algo)` 聚合——组内 `COUNT(DISTINCT Broker) >= 2` 且 `MAX(route_as_of_time) - MIN(route_as_of_time) <= 5min` 判为配对候选；输出总体占比 + 按市场 × 算法族（algo 组用 DL-04 `coarse_group`）拆分；
2. **单元样本量与 MDE**：按（Exchange × algo 细分族 × 规模档 pct_adv）分组计数，配合 `power.required_sample_per_group` 反解各单元「可检测的最小 Δ（标准化 z 单位，σ=1）」；输出样本充足/不足单元清单与「还差多少」；
3. **BDIB 覆盖**：当日订单簿证券（`processed_fills` 当日 distinct `equ_ticker`）vs `raw_bdib` 当日有 bar 的 equ_ticker 集合 → 覆盖率 + 未覆盖清单（含无成交证券）；
4. **PM 意图覆盖率**：由 DL-01 盘前单端点承载（MarketView 域，`GET /api/marketview/pre-trade-orders` 的 `intent_coverage_pct` / `unmatched`）——本 CLI 不重复实现收件箱解析（范围裁剪说明见 §2.4）。

**额度/时效探测脚本**（`scripts/ops/probe_intraday_freshness.py` 新建；只读，交易机按清单运行）：

5. **收盘后 bar 就绪度**：按 DL-03 会话注册表各市场收盘时刻，探测 `raw_bdib` 当日（`order_as_of_date` = 目标日）bar 行数与首末 `mkt_timestamp`——在收盘后 15/30/60/120 分钟各跑一次（`--offset-minutes` 参数或人工四次），输出「各市场 × 各时点就绪矩阵」；
6. **GetFills 当日可得性**：探测 `processed_fills` 当日最新 `exchange_exec_time` 与当前时刻的差（成交入库延迟），按市场输出；
7. **日更耗时与请求数**：读 `processing_log` / `fetch_log`（`Config` 表常量已有）输出各阶段耗时、请求数、`quota_pause` 历史命中次数——为 DL-07/08 额度预算提供基线。

**报告与实测清单**（`docs/report-data-inventory-2026-10.md` 归档，PR 内交付首版）：

- 盘点 CLI 首跑输出（近 6 个月）归档；
- 交易机人工实测清单（GetFills 当日可得性、收盘后 bar 缓冲四次探测、日更耗时观察）——用户在交易机执行后回填；
- 结论落点：D1/D2 主次、排名单元粒度、DL-10 回退口径、DL-07/08 额度预算与缓冲值的**建议值**（标注「待实测确认」的项）。

### 2.3 检验方法（= 验收标准）

1. 盘点 CLI 实跑（近 6 个月）输出四项结果，归档 `docs/`；
2. 探测脚本在交易机按清单运行，输出就绪矩阵与延迟数据；
3. 实测值按指南 §3.3「实测状态」注释约定写入相关常量（探测脚本内的缓冲默认值标注「实测状态：待 DL-05 回填」）；
4. 盘点结论（D1/D2 主次、单元粒度、额度预算）作为 DL-07/08/10/20/23 的输入登记在报告「结论」节；
5. 既有测试不回归（backend 全量 + CostView 全量）。

### 2.4 范围裁剪说明（诚实记录）

- **PM 意图覆盖率**：DL-01 盘前单端点已交付该能力（MarketView 域），本任务不重复实现收件箱解析——盘点报告引用其输出；
- **交易机实测**：本任务交付「可脚本化的探测」+「人工实测清单」，实测执行由用户在交易机完成（GetFills 行为无法在 CI 复现），回填后常量方可脱离「待回填」状态；
- 管道侧「日更各阶段耗时」以本侧 `processing_log` 只读统计为代理（管道仓库私有，精确阶段耗时可另由管道侧按指南 §13 补充）。

## 3. 规模与拆分说明

预估 diff 约 450 行（盘点模块 ~200 + CLI 接线 ~20 + 探测脚本 ~100 + 测试 ~130）。DL-05 为验收原子单元（盘点 + 探测 + 报告一次交付才有结论价值），沿用单 PR 先例。

## 4. 范围锁

| 动作 | 文件 |
|---|---|
| 新建 | `CostView/src/monitoring/data_inventory.py` |
| 修改 | `CostView/src/__main__.py`（`--query inventory` 接线） |
| 新建 | `scripts/ops/probe_intraday_freshness.py` |
| 新建 | `CostView/tests/test_data_inventory.py` |
| 新建 | `docs/report-data-inventory-2026-10.md`（首版报告） |
| 新建 | `specs/064-data-inventory-quota-probe/plan.md`（本文件） |

范围外（不碰）：`backend/`、`platform_data/`、管道仓库、MarketView 盘前单（DL-01 已交付）、任何评估口径变更（DL-19 起）、真实下单路径。

## 5. 验收（P4）

| 需求（057 DL-05 检验方法） | 覆盖 | 结果 |
|---|---|---|
| 盘点报告归档 docs/ | 报告 + CLI 首跑输出 | 待实施后回填 |
| 确定 D1/D2 主次、单元粒度、DL-10 回退、额度预算 | 报告「结论」节 | 待实施后回填 |
| 实测值按指南 §3.3 写入常量 | 探测脚本注释状态 | 待交易机实测回填 |
| 既有测试不回归 | backend 全量 + CostView 全量 | 待实施后回填 |

## 6. 本次不做

- 交易机实测执行（人工清单已交付，执行与回填由用户完成）；
- 管道侧改动（耗时/请求数精确口径由管道侧按指南 §13 补充）；
- 依据盘点结论的后续改造（D1/D2 主次落地在 DL-20/23，单元粒度在 DL-23，回退口径在 DL-10）。
