# 071 — 准入白名单层（DL-17a）

> 父计划：`specs/057-execution-decision-loop/plan.md`（DL-17 拆分为 071/072/073，2026-10-23 用户决策 A）
> 分支：`071-access-policy-whitelist` · worktree：`../EMSXView-wt-071-access-policy-whitelist`
> 依赖：DL-02（060，运营库）、DL-03（061，市场码与 market_code_for）、DL-04（062，算法族）、DL-16（070，白名单基建）· 消费者：072（订单合规：拆分子路由与反向单）、073（算法参数：白名单转人工、volume cap、release time）
> 交易员意见来源：2026-10-23 约束矩阵 v2（「结构类别 | 约束 | 优先级 | 适用市场范围 | 决策/处理」16 项）

## 1. 问题

- **准入维度缺失**：交易员能交易哪些市场/组合、每个市场能用哪些券商——当前系统无任何准入白名单（`authorization_service` 只管 PM 授权额度，不管交易员准入；`BrokerAlgorithmConfig` 有 broker 列表但无市场维度）；
- **碎股与整手判断口径错误**：既有 `compliance_service` 用 `_DEFAULT_JP_ROUND_LOT = 100` 硬编码兜底，而交易员明确要求「通过彭博 API 查看每个 ticker 的 round lot」——仓库已有 `bloomberg.enrichment._round_lot_sizes`（refdata 批量拉取 + 缓存）与 `ODD_LOT_MARKETS` 检测市场配置，需接线而非重造；
- **券商准入无维护机制**：交易员要求「按市场构建券商准入白名单；部署自动工作流更新」——同时确认 v0 采用「候选自动拉取 + 每日（当地 8 点后）首次打开弹窗确认」的人工确认流程。

## 2. 方案（P2 三栏）

### 2.1 理论依据

硬约束先过滤、软约束后打分（tasks.md DL-17）；「游戏规则」显式化为硬约束（057 plan §理论依据）；交易员准入是机构「能做/该做」边界，必须先于一切容量与成本判断。

### 2.2 技术方案（细化到文件与函数）

**契约**（`platform_data/contracts/access_policy.py` 新建；纯数据 + 纯函数）：

- `TraderMarketPolicy`：`trader → frozenset[market_code]`（DL-03 折叠码）；未列入 = 无准入（HARD）
- `TraderPortfolioPolicy`：`trader → frozenset[portfolio]`；`"*"` = 不限（与 `authorization_service` 的「intent.portfolio 空=不限」语义对齐）
- `BrokerMarketPolicy`：`market → frozenset[broker]` + `confirmed_at` + `confirmed_by`（来源：运营库确认表；未确认市场 = 空集 = 全部不可路由——首次部署需确认）
- `FractionalSharePolicy`：`market → bool`（True=允许碎股常规路由；False/缺失=含碎股转人工）——交易员「碎股常规路由白名单」的规则载体
- `RoundLotProvider`（Protocol）：`round_lot(ticker) -> int | None`——ticker 级整手；实现走既有 Bloomberg 缓存（见下）
- `PolicyBundle`：四类策略打包 + `POLICY_VERSION` + `loaded_at`
- 纯函数：`check_trader_market(trader, market, bundle)` / `check_trader_portfolio(trader, portfolio, bundle)` / `check_broker_market(broker, market, bundle)` / `check_fractional_share(qty, round_lot, market, bundle)`（qty 非整手倍数 → 白名单内放行、白名单外 `manual_review_required`）/ `check_round_lot_multiple(qty, round_lot)`

**策略加载**（`backend/api/services/access_policy_service.py` 新建）：

- `load_policy_bundle() -> PolicyBundle`：
  - 交易员市场/组合白名单：仓库外 **JSON**（`EMSXVIEW_ACCESS_POLICY_FILE`，backend 无 PyYAML 依赖故用标准库 json；缺失时 `configured=False`——准入检查跳过并告警，避免漏配一次即全系统停摆；配置后未准入即阻断）；
  - 券商市场白名单：**复用既有 `market_broker_mapping.json`**（`routers/market_broker_mapping.py` 已实现 rosters/selection/密码门控，2026-10-23 核查后确认无需新建表）——`load_broker_market_policy()` 只读 selection（true=允许），marketKey `EUR→EU` 归一（DL-03 折叠）；
- `broker_candidates(market) -> list[str]`：候选券商——**内部系统接口预留**（2026-10-23 用户决策：「通过内部系统获取按市场候选券商列表，后续开发」）：定义 `BrokerCandidateSource` Protocol，v0 实现 `BrokerAlgorithmStorageSource`（EMSX 策略菜单缓存清单作临时源，docstring 标注「内部系统接口就绪后替换」）；确认流程（弹窗 + 落库）本任务完整交付，仅候选数据源待替换；
- `confirm_broker_policy(market, brokers, trader)`：写运营库确认表（upsert + confirmed_at/confirmed_by）；
- `needs_daily_confirmation(now) -> bool`：当地 08:00 后且当日未确认（`last_confirmed_date` 存运营库/配置文件 mtime）→ true。

**端点复用**（不新建路由）：

- 候选与确认全部复用既有 `market_broker_mapping` 端点：`GET /api/market-broker-mapping`（rosters+selection+updatedAt）、`PUT /api/market-broker-mapping/selection`（确认即回写，刷新 updatedAt）；
- 每日确认判定在服务层（`needs_daily_confirmation`，当地 08:00 后且 `updatedAt` 非当日）。

**整手/碎股（接线既有基建，不重造）**：

- `RoundLotService`（`backend/api/services/round_lot_service.py` 新建）：`round_lot(ticker, market) -> int | None`——优先 `bloomberg.enrichment._round_lot_sizes` 缓存（refdata 批量拉取，已有）；市场在 `ODD_LOT_MARKETS` 且缓存缺失时触发拉取（复用 `_maybe_query_round_lot_sizes` 路径）；最终兜底 `None`（不猜 100，改由 `check_fractional_share` 判 manual_review）；
- `compliance_service` 的 JP 整手检查改为经 `RoundLotService`（去掉 `_DEFAULT_JP_ROUND_LOT=100` 硬编码兜底，round lot 不可得时转人工而不是按 100 判）。

**前端**（`ExecutionView/module`）：

- 每日首次打开弹窗：`GET /api/policy/status` 返回 `needs_confirmation` + 候选市场 → Modal 列出「市场 × 候选券商」勾选 → `POST confirm`；已确认当日不再弹（原则 10：呈现效果可迭代）。

**测试**（`backend/api/tests/test_access_policy.py` + `test_round_lot_service.py` 新建）：

1. 五类检查纯函数正反例（交易员市场/组合、券商市场、碎股白名单内/外、整手倍数）；
2. 策略加载：YAML 缺失 → 空 bundle + 全阻断；YAML 解析（trader/portfolio/碎股白名单）；运营库确认表读写；
3. `needs_daily_confirmation`：08:00 前/后 × 当日已确认/未确认四象限；
4. `RoundLotService`：缓存命中（fake）、`ODD_LOT_MARKETS` 内缺失触发（fake）、不可得返回 None（不猜 100）；
5. 端点：候选列表、确认落库、状态摘要（TestClient + fake）；
6. 既有 `compliance_service` 回归（JP 整手改接线后行为）。

### 2.3 检验方法（= 验收标准）

1. 交易员市场/组合准入检查单测（未准入 → HARD 阻断，理由含 trader/market）；
2. 券商市场准入：未确认市场 = 全阻断可见；确认后候选内放行、候选外阻断；每日确认流程（四象限）单测；
3. 碎股：白名单内市场放行、白名单外 `manual_review_required`；整手倍数用 **ticker 级 round lot**（非 100 硬编码），round lot 不可得转人工；
4. 既有 compliance_service / 提交链路不回归（backend 全量 + boundaries）。

### 2.4 边界（诚实记录）

- **券商候选 v0 来源**：内部系统接口「后续开发」——v0 用 `BrokerAlgorithmStorage` 缓存清单作临时源并预留 `BrokerCandidateSource` 接口；确认流程（每日弹窗）本任务完整交付；
- **本层不含**：金额拆分路由与反向单（072）、白名单转人工语义与 volume cap/release time（073）、**现金账户约束（杠杆禁止/卖空限制——新增 HARD，依赖现金/持仓数据源，随内部系统开发落 072 或独立子号）**；
- **交易员身份来源**：`OrderProjection.trader`（运营库已落盘）；v0 不做交易员登录体系改造。

## 3. 规模与拆分说明

预估 diff 约 520 行（契约 ~110 + 策略服务 ~140 + round lot 服务 ~60 + 端点 ~90 + 前端弹窗 ~80 + 测试 ~150）。071 为验收原子单元（准入四类 + round lot 接线一次交付才能被 072/073 消费），沿用单 PR 先例。

## 4. 范围锁

| 动作 | 文件 |
|---|---|
| 新建 | `platform_data/contracts/access_policy.py`（四类策略 + 检查纯函数 + configured 语义） |
| 新建 | `backend/api/services/access_policy_service.py`（JSON 加载 + 既有 mapping 只读 + 每日确认判定 + `evaluate_access` 接入入口） |
| 修改 | `backend/api/services/compliance_service.py`（`_check_odd_lot` 通用化：ticker 级 round lot、不猜 100、碎股白名单；两处调用 + `fractional_markets` 参数） |
| 修改 | `backend/api/services/submission_service.py`（按 severity 区分：仅 BLOCK 阻断，WARN 记录放行） |
| 修改 | `backend/api/routers/orders_crud.py`、`routers/route_plans.py`（准入检查接入 + BLOCK/WARN 区分） |
| 修改 | `backend/api/schemas/batch.py`（Violation code 扩展：ROUND_LOT_UNKNOWN / ODD_LOT_MANUAL_REVIEW / 三类准入） |
| 新建 | `ExecutionView/module/components/daily-broker-policy-confirm-modal.tsx` + `ExecutionModule.tsx` 接入 |
| 新建 | `backend/api/tests/test_access_policy.py`（13 用例） |
| 修改 | `backend/api/tests/test_compliance_service.py`（round lot 不猜 100 的语义更新） |
| 新建 | `specs/071-access-policy-whitelist/plan.md`（本文件） |

范围外（不碰）：`MarketView/`、`CostView/`、金额拆分/反向单/volume cap（072/073）、交易员登录体系、`bloomberg/enrichment.py` 的 round lot 拉取逻辑（只读复用）。

## 5. 验收（P4）

| 需求（交易员意见 16 项中的 071 范围） | 覆盖 | 结果 |
|---|---|---|
| 交易员市场准入 HARD | `check_trader_market` + 用例 1 | 待实施后回填 |
| 交易员组合准入 HARD | `check_trader_portfolio` + 用例 1 | 待实施后回填 |
| 券商市场准入 HARD（候选+每日确认） | `broker_candidates`/`confirm_broker_policy`/`needs_daily_confirmation` + 用例 2/3/5 | 待实施后回填 |
| 碎股常规路由白名单 | `FractionalSharePolicy` + `check_fractional_share` + 用例 1/3 | 待实施后回填 |
| 子订单整手倍数（ticker 级 round lot） | `RoundLotService` + `check_round_lot_multiple` + 用例 4/6 | 待实施后回填 |
| 既有不回归 | backend 全量 + boundaries | 待实施后回填 |

## 6. 本次不做

- 金额超限拆分路由与同日同券商反向单（072，反向单轧差基数「已执行量 vs 订单量」待用户确认）；
- 券商算法白名单「未知转人工」语义修订、volume cap 必带/命名映射/分配、收盘拍卖 release time（073）；
- 涨跌停距离（待 DL-15 实时行情）、融资对冲额度、禁投清单（v0 不做，用户确认）；
- EMSX API 按市场拉取候选券商的自动能力（v0 用缓存清单 + 人工确认）。
