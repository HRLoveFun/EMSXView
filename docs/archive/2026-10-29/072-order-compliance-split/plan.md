# 072 — 订单合规层（DL-17b）

> 父计划：`specs/057-execution-decision-loop/plan.md`（DL-17 拆分，2026-10-23 用户决策）
> 分支：`072-order-compliance-split` · worktree：`../EMSXView-wt-072-order-compliance-split`
> 依赖：071（准入层，已合并 #155）、DL-02（运营库）、DL-03（会话/市场码）、DL-11（状态）· 消费者：073（算法参数合规）、DL-21（决策日志）
> 交易员意见（2026-10-23 修订版）第 4/10 项 + 现金账户口径（用户 2026-10-23 补充）

## 1. 问题

- **路由金额上限只检查不处理**：`compliance_service` 对 >49M 直接硬阻断，交易员要求「超上限需拆分路由」——检查机制、拆分方式与上限参数均待建；
- **反向单无检测**：同日同券商反向单（甲1 买入被券商 A 执行、甲2 卖出的剩余部分）不得再路由 A——当前系统无此判定；
- **剩余量精度无保障**：交易员明确「剩余订单数量必须精确，不仅服务反向单，也服务常规多次路由」——`Order.remainingQuantity`/`filledQuantity` 与运营库 `parent_child_orders.filled_quantity` 双源并存但无一致性保障；
- **现金账户纪律未固化**（用户补充）：「完全遵照订单数量执行，禁止自行创建订单」——需要不变量防止引擎为满足约束而拆单/改量。

## 2. 方案（P2 三栏）

### 2.1 理论依据

硬约束先过滤、软约束后打分（tasks.md DL-17）；现金账户纪律 = 「订单数量是唯一真相，引擎只做路由决策不做订单创建」（用户 2026-10-23）。

### 2.2 技术方案（细化到文件与函数）

**契约**（`platform_data/contracts/order_split.py` 新建；纯数据 + 纯函数）：

- `AccountType`（枚举：`CASH` 默认 / `MARGIN` 预留）——所有组合默认 CASH（用户：默认所有组合都是现金账户；不引入现金/持仓数据源）
- `SplitLeg`（`quantity`、`broker`、`reason`）、`SplitPlan`（`order_id`、`remaining_qty`、`legs`、`max_notional_usd`、`conserved`）
- `ReverseOrderDecision`（`allowed: bool`、`needs_manual: bool`、`reason`、`executed_on_broker`、`new_order_remaining`）
- **纯函数**：
  - `plan_notional_split(remaining_qty, price, fx_rate, max_notional_usd) -> list[int]`：按金额上限拆分为若干数量（每段 ≤ 上限；**sum == remaining_qty 守恒**；price/fx 不可得 → 返回空 + 原因）；
  - `check_quantity_invariant(original_qty, leg_quantities) -> list[str]`：拆分不变量——sum(legs) == original_qty 且每 leg > 0；违反即阻断（**禁止自行创建订单/改量**）；
  - `reverse_order_decision(executed_qty_on_broker, new_order_remaining) -> ReverseOrderDecision`：轧差基数 = 甲1 在券商 A 的**已执行量**（精确剩余量口径）；`new_order_remaining > 0 且券商 A 已执行 > 0` → allowed=False（该券商不可再用），needs_manual=False（可改路由其它券商）；若已执行量不可得 → needs_manual=True。

**RemainingQuantityService**（`backend/api/services/remaining_quantity_service.py` 新建）：

- `remaining_quantity(order_id) -> RemainingQuantity`（`qty`、`source`、`consistent`）：
  - 订阅源：`bloomberg._orders[order_id].remainingQuantity`（内存实时）；
  - 落盘源：运营库 `parent_child_orders`（`quantity − filled_quantity`，DL-02 已落盘）；
  - **双源不一致** → 取保守值（min）+ `consistent=False`（暴露给审计），并日志告警——精度要求是「可解释」而非静默选一边；
  - 两源皆不可得 → `qty=None`（调用方转人工，不猜）。
- `executed_on_broker(order_id, broker) -> int | None`：运营库 slices 按 broker 聚合 `filled_quantity`；不可得 None（转人工）。

**反向单判定**（`backend/api/services/order_compliance_service.py` 新建）：

- `evaluate_reverse_order(parent_order, broker) -> ReverseOrderDecision`：
  - 查同日同 symbol 反向 parent orders（运营库 `parent_child_orders` + 内存 orders）；
  - 对每笔反向单取 `executed_on_broker(甲1, broker)`；
  - 命中 → 返回禁止该券商 + 证据（甲1 id/已执行量/甲2 剩余量）；无可用券商 → needs_manual=True。

**接入**（既有链路，特性开关默认关闭）：

- `route_plans._compliance_check` / `orders_crud.route_order`：新增两项——
  1. `check_quantity_invariant`：proposal 的 `quantity` 必须 ≤ `remaining_quantity(order_id)`（**禁止超量路由 = 不造单**），超量 BLOCK；
  2. `evaluate_reverse_order`：命中反向单禁止 → BLOCK（理由含「不得再路由该券商」），needs_manual → WARN；
- `submission_service`：`AccountType` 默认 CASH 透传审计（无余额/持仓比对——用户口径：不引入数据源、由券商侧校验兜底）；
- 金额上限拆分：`plan_notional_split` 作为**服务能力**交付，`batch_route_service` 的拆分接入留开关 `EMSXVIEW_NOTIONAL_SPLIT_ENABLED`（默认关闭；拆分是唯一允许的拆单场景，且必须过守恒检查）。

**测试**（`backend/api/tests/test_order_compliance_split.py` 新建）：

1. `plan_notional_split`：整除/余数/price 不可得/单段即超限（返回空+原因）/守恒断言；
2. `check_quantity_invariant`：sum 相等通过、sum 不等阻断、含 0/负数阻断、超剩余量阻断；
3. `reverse_order_decision`：已执行>0 且剩余>0 → 禁止该券商；已执行=0 → 允许（甲1 未被该券商执行）；已执行不可得 → needs_manual；剩余=0 → 允许（全被轧差）；
4. `RemainingQuantityService`：双源一致/不一致取 min 且 consistent=False/单源缺失/双源缺失 None；
5. 接入：超量路由 → BLOCK（不造单）；反向单命中 → BLOCK 该券商；开关关闭时拆分不激活；
6. 既有路由链路不回归。

### 2.3 检验方法（= 验收标准）

1. 金额拆分守恒（sum == 剩余量）与上限边界单测；
2. 反向单三态（禁止/允许/转人工）单测 + 证据字段完整；
3. 剩余量双源一致性与保守取值单测；
4. 现金账户不变量：超量路由阻断、拆分守恒阻断、`AccountType` 默认 CASH 写入审计；
5. 既有路由/提交不回归（backend 全量 + boundaries）。

### 2.4 边界（诚实记录）

- **不引入现金/持仓数据源**（用户口径）：杠杆禁止/卖空限制不做余额比对，由券商侧（EMSX）校验兜底；`AccountType.CASH` 作为默认值与审计字段；
- **拆分仅限金额上限**：唯一允许的拆单场景，「禁止自行创建订单」指不得为其它约束（含现金/卖空）拆单或改量——守恒不变量强制；
- **反向单券商集合**：v0 用运营库 slices 的 broker（已知），「其它可用券商」由 071 的券商准入白名单给出（两者叠加）；
- **订阅实时性**：`remainingQuantity` 精度取决于 Bloomberg 订阅状态；双源不一致时保守取值并标记，不静默。

## 3. 规模与拆分说明

预估 diff 约 430 行（契约 ~110 + 两个服务 ~150 + 接入 ~50 + 测试 ~120）。072 为验收原子单元，沿用单 PR 先例。

## 4. 范围锁

| 动作 | 文件 |
|---|---|
| 新建 | `platform_data/contracts/order_split.py` |
| 修改 | `platform_data/contracts/__init__.py`（导出） |
| 新建 | `backend/api/services/remaining_quantity_service.py` |
| 新建 | `backend/api/services/order_compliance_service.py` |
| 修改 | `backend/api/services/submission_service.py`（数量不变量 + AccountType 审计） |
| 修改 | `backend/api/routers/orders_crud.py`、`routers/route_plans.py`（反向单与不变量接入） |
| 修改 | `backend/api/schemas/batch.py`（Violation code 扩展：QUANTITY_EXCEEDS_REMAINING / REVERSE_ORDER_BROKER_BLOCKED） |
| 新建 | `backend/api/tests/test_order_compliance_split.py` |
| 新建 | `specs/072-order-compliance-split/plan.md`（本文件） |

范围外（不碰）：`MarketView/`、`CostView/`、073（volume cap / release time / 白名单转人工）、现金/持仓数据源、涨跌停距离。

## 5. 验收（P4）

| 需求（交易员意见 071 范围外部分） | 覆盖 | 结果 |
|---|---|---|
| 路由金额上限拆分（守恒） | `plan_notional_split` + 用例 1 | 待实施后回填 |
| 禁止同日同券商反向单 | `evaluate_reverse_order` + 用例 3/5 | 待实施后回填 |
| 剩余订单数量精确（双源） | `RemainingQuantityService` + 用例 4 | 待实施后回填 |
| 现金账户纪律（不造单/不改量） | `check_quantity_invariant` + `AccountType` + 用例 2/5 | 待实施后回填 |
| 既有不回归 | backend 全量 + boundaries | 待实施后回填 |

## 6. 本次不做

- 073（券商算法白名单转人工、volume cap 必带/命名映射/分配、收盘拍卖 release time）；
- 现金余额/持仓数据源接入与余额比对（用户口径：默认 CASH、券商侧兜底）；
- 涨跌停距离（待 DL-15）、融资对冲额度、禁投清单（v0 不做）；
- 反向单的自动改路由（v0 只判定与阻断，改路由由交易员/分配引擎处理）。
