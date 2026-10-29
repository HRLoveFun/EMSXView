# 058 — EMSX 导出解析与 PM 意图映射（只读 MVP）

> 父计划：`specs/057-execution-decision-loop/plan.md`（DL-01，第 11 节第一波）
> 分支：`058-export-intent-parser` · worktree：`../EMSXView-wt-058-export-intent-parser`
> 依赖：无（DL-04 算法族映射、DL-07 导出入库的后置消费者）
> 安全边界：只读收件箱文件、不落库、不碰 Bloomberg、不碰下单路径

## 1. 问题

- **意图只能从 EMSX 手工导出获得**（D-1）：PM 指令前缀（`80 % @Close` 等）只在交易员盘中导出的 PM Note 13 列里；API 的 PM Note 只是订单级 `notes`（`EMSX_NOTES`，仅 `^` 段）。意图决定算法族与评估口径，必须在决策时点取得；导出快照事后无法重建，每份都是时点证据。
- **现状无当日订单簿概念**：MarketView 股票池是 4 个固定池（`platform_data/adapters/market.py:86`），读的是日更 `bdib_daily_summary`；MV→EV handoff 只带候选名单，不携带逐单意图。
- **导出格式不稳定**：列可能增删改名、两列同名（附录 A 样例的 `Day Part Rate %` 出现两次）、6 个基准列 + 2 个参与率列可能显示为 Data Export Restricted；解析必须按列名、缺关键列或字段数错位要报错可见。

## 2. 方案（P2 三栏）

### 2.1 理论依据

意图决定算法族与评估口径（同类比较前提，`docs/textbook/Algo_TCA.md:654`），必须在决策时点取得；PM Note 13 只能从 EMSX 手工导出获得（D-1）。解析规则以附录 A 脱敏样例为金标准，与 DL-07 管道侧实现对齐。

### 2.2 技术方案（细化到文件与函数）

**契约**（`platform_data/contracts/order_intent_contracts.py`，新文件，frozen dataclass，无业务逻辑）：

- `OrderIntent`：`order_key`（PM Note `^` 段连接键）、`benchmark`（`VWAP|CLOSE|MIX|SPECIAL|UNMAPPED`）、`close_pct`（CLOSE=100.0、MIX=导出值）、`raw_note`（原文）、`intent_source`（固定 `emsx-export`）、`valid_from`（该版本意图生效时间 ISO）、`export_ts`（导出快照时间 ISO）、`unmatched_reason`（UNMAPPED/无连接键时的原因码，可映射时为 None）
- `BlotterOrderRow`：`code`、`exch_code`、`name`、`side`、`qty`、`ccy`、`status`、`fill_qty`、`pct_filled`、`q_pct_5d_adv`、`q_pct_tdy`、`rem_bal_pct_avg_cls_auct_vol`、`working_val_usd`、`value_usd`、`chg_pct_dtdy`、`last_px_vs_vwap_bps`、`earn_rpt_time`、`ex_dvd_flag`、`brkr_code`（原值保留，含真实导出的 `EQ-` 前缀，不做映射）、`create_time`、`pm_note`、`intent`；其余导出列原样进 `extra_fields: dict[str, str]`（清洗后），供盘前单展示与后续 DL 复用
- `PreTradeOrderBoard`：`exported_at`、`export_file_name`、`order_count`、`intent_coverage_pct`（有意图且带连接键的占比）、`orders`、`unmatched`（`UnmatchedOrder(code, pm_note, reason)` 列表）
- `INTENT_MAPPING_VERSION = "emsx-pm-note-v1"`（映射表版本，进响应与契约）

`platform_data/contracts/__init__.py` 增加上述符号导出（market/intraday 同款分组注释风格）。

**解析器**（`MarketView/export_parser.py`，新文件，MarketView 领域模块，纯函数 + 标准库 `csv`）：

- `ExportParseError(ValueError)`：缺关键列 / 字段数与表头不符（detail 带行号与列名）
- `scan_latest_export(inbox_dir: str) -> ScannedExport | None`：目录不存在或无 `.csv` 返回 None；按 mtime 取最新一份；返回 `file_name`、`exported_at`（mtime ISO）、`size_bytes`（不返回目录路径，目录在仓库外）
- `parse_export_csv(text: str, *, file_name: str) -> ParsedExport`：`csv.reader` 逐行严格校验（行宽 ≠ 表头宽即抛 `ExportParseError`，不用会静默错位的 `DictReader`）；重名列按出现顺序加 ` (2)` 后缀；遮蔽值（`***`、`MASKED`、空串）与 `Data Export Restricted` 经 `_clean_value` 统一按 None 处理；数值列经 `_to_optional_float`
- `parse_pm_note(raw_note: str, *, export_ts: str) -> OrderIntent`：按第一个 `^` 切开——前缀空 → VWAP；前缀匹配 `^(\d+(?:\.\d+)?)\s*%\s*@Close$` → 100 为 CLOSE、其余为 MIX；前缀 `Spec.Instr.` → SPECIAL；其余 → UNMAPPED（reason=`unknown_prefix`）；空前缀 note → UNMAPPED（reason=`empty_pm_note`）；无 `^` 段 → 意图可映射但 `order_key=""`、reason=`missing_order_key`。保留 `raw_note`；正则与规则集中在模块常量，映射表版本随每条意图的 `intent_source` 透出
- `build_pre_trade_board(parsed: ParsedExport, scanned: ScannedExport) -> PreTradeOrderBoard`：逐行解析意图、统计覆盖率、收集未匹配清单

**端点**（`MarketView/routers/export_orders.py`，新文件；`MarketView/main.py` 增加 `include_router`）：

- `GET /api/marketview/pre-trade-orders`：读 `config.EXPORT_INBOX_DIR`；未配置或无导出 → `success=true` + 空盘前单 + message 说明（与 snapshot 的 unavailable 模式一致，不抛 500）；解析错误 → 400（`ExportParseError`）/ 500（未预期，AP-13 包裹）
- Response 模型按 `marketview.py` 既有风格（`*Envelope` + `*Response` + `_serialize_*` 私有函数），包 `ApiResponse` 同款信封字段（`success/data/message`）

**配置**（`MarketView/config.py`）：`EXPORT_INBOX_DIR: str = os.getenv("EMSXVIEW_EXPORT_INBOX_DIR", "")`，空字符串表示未配置（仓库外路径，不设默认值、不提交 `.env`）。

**前端**（MarketView 盘前单 v0 展示，直接展示导出现成字段，不做任何计算）：

- `MarketView/module/types.ts`：`OrderIntentBenchmark` 联合类型、`OrderIntent`、`ExportOrderRow`、`UnmatchedOrder`、`PreTradeOrdersPayload`（interface，遵守 §7.1）
- `MarketView/module/services/api.ts`：`fetchPreTradeOrders()`（三态由组件消费）
- `MarketView/module/components/ExportOrdersPanel.tsx`：新组件——导出元信息（文件名、导出时间、订单数、意图覆盖率、未匹配数）+ 订单表（现成字段 + 意图徽标）+ 未匹配清单；取数按 `.codebuddy/rules/coding-style.md` 走 `@shared/hooks/use-async-data`，覆盖加载/错误/空三态
- `MarketView/module/MarketViewModule.tsx`：在工作台 section 之后接入 `<ExportOrdersPanel />`（只增不改现有逻辑）

**测试**（`MarketView/tests/`，夹具只用虚构/脱敏数据）：

- `MarketView/tests/fixtures/emsx_export_golden.csv`：以附录 A 脱敏样例为底稿——PM Note 13 填虚构连接键，覆盖五种写法（空前缀 `^7000001^0` → VWAP、`100 % @Close^7000002^0` → CLOSE、`80 % @Close^7000003^0` → MIX、`Spec.Instr.^7000004^0` → SPECIAL、未知前缀 `FOO^7000005^0` → UNMAPPED）；`***` 数值列填虚构数值；刻意保留两列同名 `Day Part Rate %` 与一列 `Data Export Restricted` 受限值
- `MarketView/tests/fixtures/emsx_export_masked.csv`：原样遮蔽版（PM Note 13 整列 `MASKED`），用于验证遮蔽值/受限值按缺失处理、空 PM Note 行进未匹配清单
- `test_export_parser.py`：五种意图映射单测；重名列后缀；遮蔽/受限清洗；缺关键列抛错（带列名）；字段数错位抛错（带行号）；列序变化可解析（表头乱序 fixtures 或内存构造）；空目录/无 csv 返回 None；`scan_latest_export` 按 mtime 取最新
- `test_export_orders.py`：沿用 `test_marketview_router.py` 的 TestClient + monkeypatch 模式——未配置收件箱返回空盘前单；解析成功返回信封（覆盖率、未匹配清单可见）；解析错误映射 400；`_get_*` 单例 fixture 清理
- `MarketView/module/marketview-utils.test.tsx`（既有文件）或新 `export-orders-panel.test.tsx`：意图徽标与未匹配清单渲染（纯函数部分进 utils 测试）

**金标准对齐**：附录 A 样例（057 plan.md）即 DL-01 与 DL-07 的共同金标准；两份夹具由其改写，PR 描述附对照说明。**本仓库公开，禁止提交任何真实订单数据。**

### 2.3 检验方法（= 验收标准）

1. 金标准夹具：五种写法全部映射正确，连接键与 `^` 段一致，`raw_note` 原文保留；
2. 遮蔽版：遮蔽值与 `Data Export Restricted` 按缺失处理，空 PM Note 单行进未匹配清单且不阻断其余行；
3. 异常用例：缺列、字段数错位、列序变化、空 PM Note 四类行为符合 §2.2 设计；
4. 连接覆盖率与未匹配清单在盘前单（端点响应 + 前端面板）可见；
5. 新能力默认只读、无写入路径；`AGENTS.md` §4.2 MarketView 成熟度行在 PR 描述中给出更新建议（晋级 Beta 留待 DL-14）。

## 3. 规模与拆分说明

预估 diff 约 450–550 行（契约 ~70 + 解析器 ~200 + 端点 ~120 + 前端 ~180 + 测试与夹具 ~250+），超出单 PR ≤200 行建议线。**2026-10-21 用户决策：单 PR 交付**——DL-01 是 tasks.md 的验收原子单元（契约、解析、端点、盘前单可见性缺一不可），拆成两个子编号会破坏 DL 编号体系与状态总览。压缩手段：`BlotterOrderRow` 非关键列走 `extra_fields` 字典、前端面板只用现成字段不做计算、夹具以数据文件承载。

## 4. 范围锁

| 动作 | 文件 |
|---|---|
| 新增 | `platform_data/contracts/order_intent_contracts.py` |
| 修改 | `platform_data/contracts/__init__.py`（导出新契约） |
| 新增 | `MarketView/export_parser.py` |
| 修改 | `MarketView/config.py`（`EXPORT_INBOX_DIR`） |
| 新增 | `MarketView/routers/export_orders.py` |
| 修改 | `MarketView/main.py`（`include_router`，一行） |
| 新增 | `MarketView/tests/test_export_parser.py`、`MarketView/tests/test_export_orders.py` |
| 新增 | `MarketView/tests/fixtures/emsx_export_golden.csv`、`MarketView/tests/fixtures/emsx_export_masked.csv` |
| 修改 | `MarketView/module/types.ts`、`MarketView/module/services/api.ts`、`MarketView/module/MarketViewModule.tsx` |
| 新增 | `MarketView/module/components/ExportOrdersPanel.tsx` |
| 新增 | `specs/058-export-intent-parser/plan.md`（本文件） |

范围外（不碰）：`platform_data/adapters/`、`backend/`、`ExecutionView/`、`CostView/`、`data_access/`、任何 Bloomberg 代码、任何下单/提交路径、`tasks.md`（状态行留待交付 PR 内更新）。

## 5. 验收（P4）

| 需求（057 DL-01 检验方法） | 覆盖 | 结果 |
|---|---|---|
| 五种意图映射正确（金标准夹具） | `parse_pm_note` 单测 +  fixtures | 待实施后回填 |
| 遮蔽值/受限值按缺失处理 | masked 夹具 + `_clean_value` 单测 | 待实施后回填 |
| 缺列/错位/列序/空 PM Note 异常行为 | 解析器异常单测 | 待实施后回填 |
| 连接覆盖率与未匹配清单可见 | 端点响应 + 前端面板测试 | 待实施后回填 |
| 只读边界（无写入、无 Bloomberg、无下单路径） | 范围锁 + PR diff 审查 | 待实施后回填 |
| 既有测试不回归 | `MarketView/tests/` 全量 + 前端 vitest | 待实施后回填 |

## 6. 本次不做

- DL-07 管道入库（`blotter_snapshots` / `order_intent`）与改读表路径；
- 与运营库订单 `notes` 的连接核对（DL-02 持久化开启后进行）；
- `Brkr Code` 的 `EQ-` 前缀与 API 券商代码映射（解析保留原值，映射关系留待 DL-16 或真实导出核对时登记）；
- 日度基线、事件状态、预期成本等 1c 能力（DL-10/11/13）。
