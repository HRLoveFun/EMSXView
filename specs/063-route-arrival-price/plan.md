# 063 — 路由到达价与延迟拆分（本侧自给 + 上游请求）

> 父计划：`specs/057-execution-decision-loop/plan.md`（DL-12，批次 1c 分析计算）
> 分支：`063-route-arrival-price` · worktree：`../EMSXView-wt-063-route-arrival-price`
> 依赖：无（自给输入均已就绪）；上游请求（EMSXDataPipeline 物化 `tca_route_summary` 四列）并行推进
> 消费者：DL-13（预期成本拟合目标）、DL-19（时段分桶与控制变量去后验化）、DL-20（D1 配对）
> 关联：`docs/archive/2026-09-16/003-tca-core-benchmarks/plan.md`（P0/Pd 口径家族）、`CostView/src/monitoring/env_context.py`（同层模式：只读取数 + 应用层 join + 三级降级链）、`docs/EMSXDataPipeline-TECHNICAL_GUIDE.md` §5.1/§5.4/§7.3/§10.3（`route_as_of_time` 派生、`arrival_slippage_bps` 口径、`raw_bdib` 结构与取数纪律）

## 1. 问题

- **到达价锚点错位**：现行主口径（003）P0 = 首笔成交前最近 bar——算法等待期（下达 → 首笔）的漂移不计入 arrival cost；管道 `fill_bdib.arrival_slippage_bps` 以**订单首 bar VWAP** 为锚（指南 §5.4），是订单级锚点且把交易员延迟混在里面；
- **交易员延迟与算法延迟混同**：003 的 `delay_cost` = RouteShares × (P0 − Pd)（Pd 锚订单创建时刻，`tca_route_summary` 已有）把「决策 → 下达」与「下达 → 首笔」压在一个数里，无法分开归因（父计划 §2.3、§4.3）；
- **路由级到达价缺失**：`tca_route_summary` 56 列无「路由下达时刻」锚点的价格（`p_arrival` 锚首笔、`p_decision` 锚订单创建），R3 的到达类诊断全部需要 `p_route_arrival`；
- **自给输入已齐**：`processed_fills.route_as_of_time`（S2 时区转换派生，交易所本地时间，指南 §5.1）、`raw_bdib` 10 秒 bar（`mkt_timestamp` 为本地 `HH:MM:SS`）、`processed_fills.exchange_exec_time`（秒级成交时刻，同批时区转换产物）——本侧不必等上游即可自给（tasks.md DL-12 技术方案原文）。

## 2. 方案（P2 三栏）

### 2.1 理论依据

到达价应锚定路由下达时刻，首笔前漂移属于算法行为；交易员延迟与算法延迟需分开归因（tasks.md DL-12）。现行管道口径以订单首 bar 的 VWAP 为锚（指南 §5.4），路由级无对应字段。到达类诊断（z 值拟合、D1 配对、时段分桶）是 R3 全部评估设计的前置，必须先有可复算的锚点口径。

### 2.2 技术方案（细化到文件与函数）

**口径定义**（本模块 docstring 即金标准，供管道侧物化对齐；价格口径与 003 `p_arrival`/`p_decision` 家族一致，仅锚点不同）：

- `p_route_arrival`：`route_as_of_time`（路由下达时刻，交易所本地）之前最近一根 `raw_bdib` 10 秒 bar 的 **close**；当日该时刻之前无 bar（盘前下达）时取当日首 bar 的 **open**（003 `p_decision` 盘前处理同口径）；bar 的 `close IS NULL` 跳过（指南 §10.3）；
- `algo_latency_sec`：该路由首笔成交时刻（`processed_fills` 同路由 `MIN(exchange_exec_time)`，秒级）− `route_as_of_time`，同日差秒；首笔早于下达（数据异常）或不可得时为 None；
- 上游物化请求四列的拆分保持 **sum 守恒**：`trader_delay_cost = RouteShares × (p_route_arrival − p_decision) × side_sign`，`algo_delay_cost = RouteShares × (p_arrival − p_route_arrival) × side_sign`，两者之和恰为 003 既有 `delay_cost = RouteShares × (P0 − Pd) × side_sign`（可作上游对账的额外校验）。

**模块**（`CostView/src/monitoring/route_arrival.py`，新建；模式同 `env_context.py`：纯函数 + 只读取数 + 应用层 join，不新增库键、不改既有表）：

- docstring：口径定义、三级降级链、数据来源与已知边界（本节内容收敛于此，作为管道侧对齐金标准）；
- `RouteArrivalContext`（frozen dataclass）：`route_as_of_time`、`first_fill_time`、`p_route_arrival`、`arrival_bar_time`（所用 bar 时刻，供审计）、`algo_latency_sec`；字段 None = 该维度不可得；
- 纯函数（无 IO，单测直接覆盖）：
  - `arrival_price_from_bars(bars: Sequence[tuple[str, float | None, float | None]], as_of_hms: str | None) -> float | None`：bars 为当日升序 `(mkt_timestamp, close, open)`；取 `mkt_timestamp <= as_of` 的最后一根 close；无则首根 open；空/不可解析 → None；
  - `latency_seconds(as_of_hms: str | None, first_fill_hms: str | None) -> float | None`：同日 `HH:MM:SS` 差秒；首笔早于下达（负值，数据异常）→ None；解析失败 → None；
  - `resolve_arrival_fields(upstream: float | None, selfsup: float | None) -> tuple[float | None, str]`：L1 上游非 None → `(upstream, "upstream")`；否则自给非 None → `(selfsup, "self")`；都 None → `(None, "missing")`；
  - `reconcile_arrival(upstream_map: Mapping[tuple[str, str, str], float | None], selfsup_map: Mapping[tuple[str, str, str], float | None]) -> dict`：逐路由相对差异 bps = `|up − self| / self × 1e4`（self 为 None/0 的路由跳过，不除零）；返回 `compared / within_1bp / pct_within_1bp / max_diff_bps / top_examples`；上游全缺时 `compared=0`；
- IO 函数（只读；库/表缺失 → 空映射降级不抛错，同 `env_context` 的 `FileNotFoundError` 约定）：
  - `load_route_as_of_and_first_fill(mgr, start_date, end_date) -> dict[route_key, tuple[str | None, str | None]]`：`processed_fills` 一次查询按 `(OrderId, RouteId, order_as_of_date)` 分组取 `MIN(route_as_of_time)` 与 `MIN(exchange_exec_time)`（`WHERE order_as_of_date BETWEEN ? AND ?`，PK 前导列）；
  - `load_arrival_bars(mgr, ticker_dates: Iterable[tuple[str, str]]) -> dict[tuple[str, str], list[tuple[str, float | None, float | None]]]`：`raw_bdib` 按 `(equ_ticker, order_as_of_date)` 分组查询（前导列齐全，符合指南 §10.3 取数纪律），`ORDER BY mkt_timestamp`；
  - `load_upstream_arrival(mgr, start_date, end_date) -> dict[route_key, dict]`：`tca_route_summary` 经 `PRAGMA table_info` 检测 `p_route_arrival` / `algo_latency_sec` 列——列不存在即上游未就绪，返回空 dict（不报错）；存在则按路由键读取两列；
- 装配与披露：
  - `build_route_arrival_context(mgr, routes, start_date, end_date) -> dict[route_key, RouteArrivalContext]`：路由键与 `equ_ticker` 取自调用方路由对象（`getattr` 防御，同 `build_route_env_context`），应用层 join 三来源；
  - `arrival_coverage(routes, ctx_by_route) -> dict`：`p_route_arrival` / `algo_latency_sec` 两维度可得率（「不可得」必须可见，同 `env_coverage`）。

**对账 CLI**（`scripts/ops/reconcile_route_arrival.py`，新建，只读）：`--start` / `--end`（默认最近一个交易日）→ 拉上游列 + 本侧自给 → 调 `reconcile_arrival` 打印报告（compared、within_1bp、pct、max_diff_bps、top_examples、自给覆盖率）；退出码 0 = 上游未就绪（仅披露）或 ≥99% 通过，1 = 低于阈值（供切换门禁与计划任务告警）；docstring 内置口径说明与「上游就绪 + 对账通过后才切换 L1」的操作约定。

**上游请求**（EMSXDataPipeline，并行；本仓库不含管道侧改动）：请管道在 `tca_route_summary` 物化四列——`p_route_arrival`（口径同上）、`algo_latency_sec`（口径同上）、`trader_delay_cost` 与 `algo_delay_cost`（sum 守恒口径如上）；本侧以本模块 docstring 与子规格为金标准，管道侧按其规范实施（tasks.md 开工规程第 8 步之外的口径协作）；到位后由对账 CLI 执行逐路由对账，通过即经 `resolve_arrival_fields` 完成 L1 切换（消费方 DL-19/DL-20 引用本模块口径）。

### 2.3 数据来源与边界（诚实记录）

- `route_as_of_time` / `exchange_exec_time` 是 S2 同一批时区转换产物（交易所本地 naive 时间），与 `raw_bdib.mkt_timestamp`（本地 `HH:MM:SS`）同本地时钟可比；S2 对空/未知 Exchange 直接抛错（指南 §5.1），故本地时间列恒存在；
- 跨日/盘前下达（下达时刻早于当日首 bar）按「当日首 bar open」处理（003 `p_decision` 同口径），对账时该部分差异需人工核对——上游物化须用同一口径，否则差异会超 1bp；
- `algo_latency_sec` 首笔取自 `processed_fills.exchange_exec_time`（秒级）而非 `fill_bdib.mkt_timestamp`（10 秒 floor）——S5 未处理的日期无 `fill_bdib` 行，且 floor 会系统性提前最多 10 秒；上游请求同口径；
- `raw_bdib` 偶发 `close IS NULL`（指南 §10.3），bar 过滤；查询按 `(equ_ticker, order_as_of_date)` 带前导列，点查组数 = distinct (ticker, 日期) 数，不做全表扫描；
- 上游列就绪前 `load_upstream_arrival` 返回空（列不存在即未就绪），对账 CLI 只披露自给覆盖率——「上游未就绪」与「对账失败」是两种退出语义，不得混淆；
- 价格取 bar **close** 而非 vwap：与 003 `p_arrival`/`p_decision` 家族一致，且 `raw_bdib` 无 vwap 衍生列（指南 §10.3），无成交时段 bar 的 vwap 亦不可得。

### 2.4 检验方法（= 验收标准）

1. 自给口径单测：`arrival_price_from_bars` / `latency_seconds` 纯函数用例 + 三库集成（`build_route_arrival_context` 得期望值、维度独立降级）；
2. 三级降级链：`resolve_arrival_fields` 三分支 + `load_upstream_arrival` 列存在性检测（有列读到值、无列返回空）；
3. 对账机制：`reconcile_arrival` 纯函数（<1bp 判定、占比统计、max 差异、上游全缺、self 为 0/None 跳过）；
4. **上游值与本侧自给值逐路由对账：差异 <1bp 占比 ≥99%**——上游物化后由 `reconcile_route_arrival.py` 在真实数据执行，作为 L1 切换门禁；上游请求并行推进，本次交付口径定义与对账机制，真实对账结果待上游到位后回填（PR 描述如实标注）；
5. 既有测试不回归：CostView 全量（`pytest CostView/tests -q`）+ 边界测试（新模块只 import `data_access` 与本包，无跨域违规）。

## 3. 规模与拆分说明

预估 diff 约 590 行（模块 ~190 + 测试 ~190 + 对账 CLI ~75 + 子规格 ~130 + tasks.md 1 行）。超出单 PR ≤200 行建议线：DL-12 是验收原子单元——自给口径、三级降级链、对账机制与口径文档（上游对齐金标准）须同一 PR 交付，拆开则管道侧无可对齐口径、对账无门禁；沿用 DL-01（058）、DL-02（060）、DL-03（061）经用户确认的单 PR 先例。

## 4. 范围锁

| 动作 | 文件 |
|---|---|
| 新建 | `CostView/src/monitoring/route_arrival.py` |
| 新建 | `CostView/tests/test_route_arrival.py` |
| 新建 | `scripts/ops/reconcile_route_arrival.py` |
| 新建 | `specs/063-route-arrival-price/plan.md`（本文件） |
| 修改 | `specs/057-execution-decision-loop/tasks.md`（状态总览 DL-12 行：状态改「已完成」、子编号填 063） |

范围外（不碰）：`platform_data/contracts/tca_contracts.py` 的 `TcaRouteSummary` 加字段（上游列定稿并对账通过后，随切换动作或 DL-19/DL-20 消费时再入契约，避免未定稿字段进契约造成漂移）；`trader_delay_cost` / `algo_delay_cost` 计算（上游请求四列之二，本侧按 tasks 原文不自给）；`tca_route_summary` schema 迁移（管道侧）；`env_context.py`（只复用其路由键约定，不修改）；CostView 报告/API 接线（DL-19/DL-20 消费时）；`docs/EMSXDataPipeline-TECHNICAL_GUIDE.md` 副本（管道侧更新后按 057 §4.0 联合开发流程同步）。

## 5. 验收（P4）

| 需求（057 DL-12 检验方法） | 覆盖 | 结果 |
|---|---|---|
| 上游值与本侧自给值逐路由对账：差异 <1bp 占比 ≥99% | 对账 CLI + `reconcile_arrival` 单测；真实对账待上游物化后执行（第 4 条如实标注） | 待实施后回填 |
| 本侧自给口径正确（`p_route_arrival` / `algo_latency_sec`） | 纯函数 + 集成用例 | 待实施后回填 |
| 三级降级链（L1 上游 → L2 自给 → L3 不可得） | `resolve_arrival_fields` + `load_upstream_arrival` 列检测 | 待实施后回填 |
| 既有测试不回归 | CostView 全量 + boundaries | 待实施后回填 |

## 6. 本次不做

- 上游未就绪期间的真实数据对账（上游请求并行，到位后执行并回填本节验收表）；
- L1 切换动作本身（上游列就绪 + 对账 CLI 退出码 0 后才切，由届时动作执行；本 PR 只交付切换机制与门禁）；
- `p_route_arrival` 进 `TcaRouteSummary` 契约字段与 CostView 报告展示（随切换或 DL-19/DL-20 消费）。
