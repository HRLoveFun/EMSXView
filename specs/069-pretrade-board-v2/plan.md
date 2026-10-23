# 069 — 盘前单与 handoff v2

> 父计划：`specs/057-execution-decision-loop/plan.md`（DL-14）
> 分支：`069-pretrade-board-v2` · worktree：`../EMSXView-wt-069-pretrade-board-v2`
> 依赖：DL-01（058，盘前单解析）、DL-10（066，日度基线）、DL-11（067，市场状态）、DL-13（068，预期成本——校准未达标，消费端标注）· 消费者：DL-17/18（分配引擎输入）
> 关联：`platform_data/contracts/handoff_contracts.py`（v1 契约，WBS-08）

## 1. 问题

- **MV→EV handoff 只带候选名单**：v1 载荷（`ExecutionCandidateHandoff`）无逐单意图、难度、市场状态——EV 侧分配引擎（2a/2b）拿到名单仍要人工查状态；
- **1a–1c 产物未装配**：盘前单（DL-01）、基线（DL-10）、状态（DL-11）、难度（DL-13）四路就绪但无「开战吧」面板汇总；
- **载荷无 schema 版本**：v1 无版本字段，字段演进时消费方无法判别口径。

## 2. 方案（P2 三栏）

### 2.1 理论依据

节点一（MarketView 表格实时监控）的核心交付；handoff 携带决策所需上下文而非裸名单（tasks.md DL-14）。呈现效果与用户反复沟通打磨确定（原则 10）——v1 面板先交付可讨论版本。

### 2.2 技术方案（细化到文件与函数）

**契约**（`platform_data/contracts/handoff_contracts.py` 扩展）：

- `HANDOFF_SCHEMA_VERSION = "market-to-execution-v2"`（v2 载荷版本；v1 载荷无此字段——消费方据缺失判 v1）
- `PreTradeBoardItem`（frozen dataclass，逐单装配产物）：`equ_ticker`、`order_key`、`benchmark`（DL-01 意图）、`close_pct`、`qty`、`log_volume_z`、`vol_percentile`、`adv5_adv60_ratio`（DL-10 摘要）、`market_code`、`liq_regime`、`vol_regime`（DL-11 摘要）、`expected_cost_bps`、`timing_risk_bps`、`in_domain`、`model_version`、`model_calibrated`（bool——**DL-13 v1 未达标的显式标注**）、`data_gaps`（该单缺失的产物列表——如无意图/无基线）
- `MarketToExecutionHandoffV2`：metadata + trade_date + pool_id + `items: list[PreTradeBoardItem]` + `execution_hint` + `schema_version`（v2）；v1 端点载荷**扩展而非替换**（保留 candidate_payload 字段，新增可选 `pretrade_items` + `schema_version`——旧消费方不破）

**装配端点**（`MarketView/routers/pretrade.py` 新建 + `main.py` 接线）：

- `GET /api/marketview/pretrade-board?trade_date=...`：四路装配——
  1. ticker 集合 + 意图：DL-01 盘前单（`export_orders.load_pre_trade_board`，收件箱解析；无收件箱/无导出 → 空盘前单 + message）；
  2. 基线：`DailyBaselineAdapter.get_baseline(tickers)`；
  3. 状态：`EventRegimeAdapter.get_market_states(markets)`（markets = ticker 的 exchange 经 DL-03 `market_code_for` 折叠去重）；
  4. 难度：`load_expected_cost_model(market)` + 每 ticker 点查 ADV20（`bdib_daily_summary`，as_of=基线截止日）→ 意图参与率 = qty ÷ ADV20 → `expected_cost_bps`/`timing_risk_bps`（会话时长经 DL-03 注册表）+ `model_calibrated=False` 标注（DL-13 v1）；
- 任一路产物缺失 → item 的对应字段 None + `data_gaps` 记录（不静默填 0，原则 4）
- `POST /api/marketview/handoff/execution` 扩展：请求体加可选 `include_pretrade_items: bool = False`——true 时载荷带 `pretrade_items` + `schema_version`（单一广播端点不变）

**前端**（MarketView 盘前面板 v1）：

- `MarketView/module/components/ExportOrdersPanel.tsx` 扩展：新增列——量 z、波动分位、ADV 比、市场状态徽标（liq/vol）、预期成本徽标（带「模型未达标」tooltip）、数据缺口标记；列显隐由面板顶部开关控制（呈现效果可讨论迭代——原则 10）；
- `types.ts`/`services/api.ts` 增 `PreTradeBoardItem`/`fetchPreTradeBoard()`。

**测试**（`MarketView/tests/test_pretrade_board.py` 新建 + `backend/api/tests/` 契约测试扩充）：

1. 装配单测（fake 四适配器 + fake ADV 点查）：全产物装配、部分缺失（无意图/无基线/无模型→data_gaps）、`model_calibrated=False` 标注、exchange 折叠去重；
2. 契约测试：`HANDOFF_SCHEMA_VERSION` 常量 + `PreTradeBoardItem` 字段完整 + v1 载荷扩展后向兼容（旧字段保留）；
3. 端点测试：TestClient + monkeypatch 单例（信封/空盘前单 message/装配结果序列化）。

### 2.3 检验方法（= 验收标准）

1. handoff v2 载荷 schema 版本与契约测试（v1 兼容）；
2. 装配单测覆盖四路产物 + 缺失降级（`data_gaps` 可见）；
3. 前端面板展示（量 z/状态/成本徽标 + 未达标标注 + 列开关）；
4. 既有 handoff v1 端点与前端不回归（MarketView 全量 + 前端 vitest）；
5. `module-boundary.md` §2.3 无需新适配器（复用四个既有适配器——确认无新增）。

### 2.4 边界（诚实记录）

- **DL-13 模型未达标**：面板与 handoff 的预期成本列带 `model_calibrated=False` + tooltip「v1 校准未达标（系统性低估），仅作内部参考」——消费端诚实标注，不作为可靠决策依据；
- **EV 侧消费**（分配引擎读取 v2 载荷）属 DL-17/18，本任务只交付载荷与 MarketView 面板；
- **盘中刷新**（DL-15 后补盘中字段）不在范围。

## 3. 规模与拆分说明

预估 diff 约 500 行（契约 ~60 + 装配端点 ~150 + handoff 扩展 ~30 + 前端 ~180 + 测试 ~120）。DL-14 为验收原子单元（装配 + 载荷 + 面板一次交付才能被 DL-17/18 消费），沿用单 PR 先例。

## 4. 范围锁

| 动作 | 文件 |
|---|---|
| 修改 | `platform_data/contracts/handoff_contracts.py`（`HANDOFF_SCHEMA_VERSION` + `PreTradeBoardItem` + v2 载荷） |
| 修改 | `platform_data/contracts/__init__.py`（导出） |
| 新建 | `MarketView/routers/pretrade.py` + `MarketView/main.py` 接线 |
| 修改 | `MarketView/routers/marketview.py`（handoff 端点扩展 `include_pretrade_items`） |
| 修改 | `MarketView/module/types.ts`、`MarketView/module/services/api.ts`、`MarketView/module/components/ExportOrdersPanel.tsx` |
| 新建 | `MarketView/tests/test_pretrade_board.py` |
| 新建 | `specs/069-pretrade-board-v2/plan.md`（本文件） |

范围外（不碰）：`backend/`（除 tests 无新增）、EV 侧消费（DL-17/18）、盘中刷新（DL-15）、`data_access/`、既有 v1 handoff 语义（只扩展不改写）。

## 5. 验收（P4）

| 需求（057 DL-14 检验方法） | 覆盖 | 结果 |
|---|---|---|
| handoff v2 载荷 schema 版本与契约测试 | 用例 2 | 待实施后回填 |
| 装配单测（四路产物 + 缺失降级） | 用例 1/3 | 待实施后回填 |
| 前端面板展示（含未达标标注） | 面板 + vitest | 待实施后回填 |
| v1 端点不回归 | MarketView 全量 + 前端 vitest | 待实施后回填 |

## 6. 本次不做

- EV 侧读取 v2 载荷的分配引擎改造（DL-17/18）；
- 盘中字段刷新（DL-15 后）；
- 模型改进（DL-13 改进方向，另立轮次）；
- handoff v1 移除（v2 为扩展，v1 兼容保留）。
