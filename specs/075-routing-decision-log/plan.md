# 075 — 决策日志与决策时点快照（DL-21）

> 父计划：`specs/057-execution-decision-loop/plan.md`（DL-21，2b 影子方式）
> 分支：`075-routing-decision-log` · worktree：`../EMSXView-wt-075-routing-decision-log`
> 依赖：DL-02（运营库）、DL-17（约束结果）、DL-18（参数计划）· 消费者：DL-22（影子运行）、DL-23/24（得分快照与 lift 回检）

## 1. 问题

- **券商选择无证据链**：`route_engine.generate_proposals` 直接按 route plan 拆分产出提案，不记录「为什么选这些券商/这些数量」——节点二出口判据要求「券商选择有可解释理由与完整决策日志」；
- **决策上下文不可回放**：约束检查（071/072/073）、参数模板（DL-18）、市场状态与难度的组合在提案生成后即丢失，DL-23/24 的得分快照与 lift 回检无法归因；
- **无影子对照**：2c 的 ASSIST 模式上线前需要一个「引擎会怎么决策」的并行记录，才能安全评估接管效果。

## 2. 方案（P2 三栏）

### 2.1 理论依据

决策日志是 057 闭环的脊柱（plan §13.1 `routing_decisions`）；「影子方式」= 记录不改写（D-3 默认人工确认、2b 先并行观察），符合 G2「新能力默认关闭」。

### 2.2 技术方案（细化到文件与函数）

**契约**（`platform_data/contracts/routing_decision.py` 新建；纯数据）：

- `DECISION_SCHEMA_VERSION = "routing-decision-v1"`
- `DecisionCandidate`：`broker`、`quantity`、`participation_pct`、`strategy_params`（摘要）、`rationale`（可读理由）
- `RoutingDecision`：`decision_id`（uuid）、`trace_id`、`order_id`、`ticker`、`side`、`as_of`、`plan_id`、`split_type`、`mode`（SHADOW/ASSIST）、`candidates`、`versions`（dict：registry / constraints / params / decision）、`schema_version`

**运营库**（`backend/api/models/execution_state.py` 扩展）：

- `RoutingDecisionRecord` 表：`id`、`decision_id`（unique）、`trace_id`（index）、`order_id`（index）、`as_of`（index）、`mode`（index）、`schema_version`、`payload`（JSON）、`created_at`

**服务**（`backend/api/services/decision_log_service.py` 新建）：

- `decision_log_enabled() -> bool`：开关 `EMSXVIEW_DECISION_LOG_ENABLED`（默认关闭，G2）
- `build_shadow_decision(order, plan, proposals) -> RoutingDecision`：从 order/plan/proposal dict 组装（纯函数，可单测）
- `record_decision(decision) -> bool`：写运营库；**任何异常返回 False + 日志**（影子记录失败绝不阻断提案）
- `load_decisions(order_id=None, limit=50) -> list[dict]`：只读查询

**接入**（`backend/api/services/route_engine.py`）：

- `generate_proposals` 重构为「分支赋值 + 统一出口」，出口处 `if decision_log_enabled(): await self._record_shadow(...)`（内部 try/except 全吞 + 日志）；
- `_record_shadow` 复用 `build_shadow_decision` + `record_decision`。

**端点**（`backend/api/routers/routing_decisions.py` 新建）：

- `GET /api/routing-decisions?order_id=&limit=`：按订单查决策记录（只读，`ApiResponse` 包装）。

**测试**（`backend/api/tests/test_routing_decision_log.py` 新建）：

1. `build_shadow_decision`：字段完整性（candidates 数量/券商/qty/participation、versions 四键、mode=SHADOW、schema_version）；
2. `record_decision` + `load_decisions`（tmp SQLite 夹具：写入→按 order_id 查询→字段回读）；
3. `record_decision` 降级：DB 不可用 → False 且不抛；
4. 开关：默认关闭 / 各取值开启；
5. `generate_proposals` 影子不改变提案（同输入下提案列表与关闭开关时逐字段一致）；
6. 既有不回归（`test_route_engine_apply.py` 等）。

### 2.3 检验方法（= 验收标准）

1. 决策记录字段完整性（候选集 + 四版本号 + 理由）；
2. 影子模式不改变路由结果（开关开/关的提案一致）；
3. 记录失败不阻断（DB 不可用时提案照常返回）；
4. 查询端点可用；
5. 既有全量不回归。

### 2.4 边界（诚实记录）

- **影子方式不接管**：只记录「引擎会这么分」，不改变既有路由行为（D-3）；
- **约束结果不重复计算**：v0 的 candidates 记录 route plan 已给的分案与参数摘要；071/072/073 的检查结果在提交链路（`evaluate_order_compliance`）——两者的合并留给 DL-22 影子运行（在批量 dry-run 处同时采集），避免本任务重复跑约束引擎；
- **运营库依赖**：`ENABLE_DB_PERSISTENCE` 关闭时 record 返回 False（日志可见）。

## 3. 规模与拆分说明

预估 diff 约 440 行（契约 ~90 + 模型 ~20 + 服务 ~120 + 接入 ~40 + 端点 ~60 + 测试 ~110）。

## 4. 范围锁

| 动作 | 文件 |
|---|---|
| 新建 | `platform_data/contracts/routing_decision.py` |
| 修改 | `platform_data/contracts/__init__.py`（导出） |
| 修改 | `backend/api/models/execution_state.py`（routing_decisions 表） |
| 新建 | `backend/api/services/decision_log_service.py` |
| 修改 | `backend/api/services/route_engine.py`（generate_proposals 收口 + 影子记录） |
| 新建 | `backend/api/routers/routing_decisions.py` + `main.py` 接线 |
| 新建 | `backend/api/tests/test_routing_decision_log.py` |
| 新建 | `specs/075-routing-decision-log/plan.md`（本文件） |

范围外（不碰）：`MarketView/`、`CostView/`、EV 前端决策日志视图、DL-22 影子运行、DL-23/24 得分快照。

## 5. 验收（P4）

| 需求（tasks DL-21） | 覆盖 | 结果 |
|---|---|---|
| 决策日志表与字段完整性 | 契约 + 模型 + 用例 1/2 | 待实施后回填 |
| 决策时点快照（版本三元组） | `versions`（registry/constraints/params/decision） | 待实施后回填 |
| 影子方式（不改写路由） | 用例 5（开关开/关提案一致） | 待实施后回填 |
| 失败降级不阻断 | 用例 3 | 待实施后回填 |
| 查询可用 | 端点 + 用例 2 | 待实施后回填 |
| 既有不回归 | backend 全量 + boundaries | 待实施后回填 |

## 6. 本次不做

- DL-22 影子运行（并行 dry-run 采集 + 差异报表）；
- 约束引擎结果与决策日志的合并（DL-22 在批量 dry-run 处统一采集）；
- EV 前端决策日志视图；
- 历史决策回填（v0 只记新决策）。
