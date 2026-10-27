# 082 — DL-07 读侧接线：盘前单意图来源切换与覆盖率/未匹配/新鲜度透出

> 父计划：`specs/057-execution-decision-loop/plan.md`（节点一 · 1b，DL-07 «DL-01 直读路径退役»）
> 分支：`082-marketview-intraday`（worktree `../EMSXView-wt-082-marketview-intraday`，基线 081 合并后的 main）
> 依赖：081（`IntradayStoreReader`，已合并 ce4bc6b）
> 状态：按目标指令直接实施（用户已设定「抵达第一个验收里程碑」目标）

## 1. 问题（是什么）

DL-01 的盘前单只读收件箱导出，DL-07 上线后 `order_intent` 表已经是意图的正式来源，但无人消费；节点一出口判据要求「意图覆盖率、未匹配清单与各数据集新鲜度可见」，而 `GET /api/marketview/pretrade-board` 只返回 items，三个聚合信息全部丢失。

## 2. 方案（为什么这样做）

- **来源优先级**：盘中库 `order_intent`（有行即用）> 收件箱导出（回落）；`meta.intent_source` 显式标注 `intraday | export | none`，不静默混用。
- **同键多版本**：按 `order_key` 取 `valid_from` 最新一行（同日多份导出留版本），旧版本不参与装配。
- **未匹配清单三源合一**：盘中库 `unmatched_reason`、导出解析的 `unmatched`、以及「订单有导出但盘中库无意图行」的 `no_intent_row`——都进同一个可见列表，带 `order_key/equ_ticker/pm_note/reason`。
- **覆盖率**：`matched ÷ 订单总数 × 100`，与 DL-01 定义一致；无订单时 0。
- **新鲜度**：逐数据集透出 `dataset/as_of/lag_minutes`（081 已实现计算），端点只做序列化。
- **快照来源**：按契约 `READ_ROUTE_RULE = formal-first`，正式库（`bdib_daily_summary`）有该日即 `formal`，否则盘中 `snapshot_t0` 非空即 `intraday`，都没有 `none`；正式库探查失败不阻断盘中路径。
- 保留 `assemble_items()` 作为兼容包装，避免既有调用方与测试断裂。

## 3. 落地（范围锁）

| # | 文件 | 类型 | 内容 |
|---|---|---|---|
| 1 | `MarketView/routers/pretrade.py` | 改 | `assemble_board` + `_apply_intraday_intents` / `_latest_intents` / `_intent_from_row` / `_snapshot_source`；payload 扩 6 字段 |
| 2 | `MarketView/tests/test_pretrade_board_intraday.py` | 新增 | 来源切换、覆盖率、未匹配三源、新鲜度、formal-first |
| 3 | `MarketView/tests/test_pretrade_board.py` | 改 | 端点错误注入目标改为 `assemble_board` |
| 4 | `specs/057-execution-decision-loop/tasks.md` | 改 | DL-07 行补 082 |

## 4. 验收（取自节点一出口判据）

1. 有盘中库意图时 `intent_source=intraday` 且意图覆盖导出行（含 close_pct 类型化）；
2. 盘中库无行时整体回落导出，覆盖率沿用导出统计；
3. 三类未匹配均有明确 reason；同键取最新 `valid_from`；
4. `freshness` 与 `snapshot_source` 在端点 payload 中可见；
5. MarketView 全量测试 79 例全绿（71 既有 + 8 新增）。
