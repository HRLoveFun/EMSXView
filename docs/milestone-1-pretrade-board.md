# 节点一交付说明：交易前实时监控表（057 · 2026-10-27）

> L2 | 权威：MarketView 节点一的范围、交付证据与已知限制 | 不权威：当前成熟度定级（见 `README.md` §0）、全模块进度（见 `specs/057-execution-decision-loop/tasks.md`）

> 依据：`specs/057-execution-decision-loop/plan.md` 第 5 节节点一出口判据
> 覆盖：1a–1d（DL-01 至 DL-15）+ DL-07/08 读侧接线
> 状态：代码侧完成；呈现定稿（D-6）待用户反馈后收口

> **节点一已于 2026-10-28 重定义**（见 `specs/057-execution-decision-loop/plan.md` 第 5 节）：新的节点一是 MarketView 监控台——高亮信息面板（Liquidity / Volatility / Risk notes）+ 监控表（14 列）+ 行点击三联图详情，证券范围由指数池成分股决定（开发验证 9 个 ticker）。本页保留为 **1a–1d 的交付记录**；1e 的新范围改为 `tasks.md` 的 DL-31（指数池与订阅范围）、DL-32（监控台聚合端点）、DL-33（行详情三联图）。原 DL-29 前端池板退役、DL-30 移出节点一。

## 1. 出口判据对照

| 判据 | 实现 | 证据 |
|---|---|---|
| 表格在所辖首个市场开盘前 30 分钟可用 | 盘中库按交易日分文件，J2 收盘后写 `snapshot_t0`、次日 S5 复用；盘前单读 `order_intent` 不依赖当日行情拉取 | 管道 DL-07 #9/#10、DL-08 #11 + cba5629；本侧 081 |
| 盘中随作业刷新 | 面板每 5 分钟重取盘前单（跟随 J1 轮次），实时列 30 秒 | 083 `BOARD_REFRESH_MS` / `LIVE_REFRESH_MS` |
| 静态列与实时指标列分界清晰 | 四组表头：Order (static) / Daily baseline / Live intraday / Estimate，组间竖线 | 083 面板 |
| 意图覆盖率可见 | `intent_source · coverage%` chip；<100% 琥珀 | 082 后端 + 083 前端 |
| 未匹配清单可见 | 可折叠表格（Code / Order key / PM note / Reason），三源合一（盘中库 reason、导出 unmatched、no_intent_row） | 082 `assemble_board` |
| 各数据集新鲜度可见 | 逐数据集 `dataset · 5m` chip，滞后 >30 分钟或未知标琥珀，tooltip 给 as_of | 081 `freshness()` + 083 |
| 呈现效果经用户打磨定稿 | 待定（见第 4 节清单） | — |

## 2. 交付清单（本仓）

| 编号 | 内容 | 状态 |
|---|---|---|
| 081 | `IntradayStoreReader`：六表只读 + manifest + freshness（mode=ro，降级为空） | 已合并 #167 |
| 082 | `assemble_board`：意图主来源切到 `order_intent`、导出回落；payload 扩 6 字段 | 已合并 #168 |
| 083 | 盘前单表格重排：四组列、实时列、覆盖率/新鲜度/未匹配可见、5 分钟随作业刷新 | 已合并 #169 |
| 086 | 日度基线优先读 DL-09 快照表：竞价占比与价差代理由单行点查替代当日 bar 扫描 | 已合并 #172 |

管道侧交付：

- DL-07（#9/#10）、DL-08（#11 + cba5629）与 DL-08 修复（#13）。
- DL-09 第一批（#12）：两表 DDL 与列清单登记、S7.5 阶段（S7 之后、manifest 之前，水位=表内已有日期、首次回填 60 日）、共享聚合函数（`snapshot_t0` 与正式表同口径）、`probe_parquet_channel` 与默认关闭的分区写入。
- DL-09 第二批（#14）：`auction_open_volume/pct`、`auction_close_volume/pct`、`spread_proxy_bps`、`bar_count` 六列；窗口按交易所（镜像本侧 26 项会话注册表，逐项核对一致）；旧库经 admin 连接幂等补列。
- DL-08 修复（#13）：J2 就绪判定改用市场本地交易日——原用服务器日期拼水位键，日期差一天时已完成市场每轮重复拉取全市场 bar。

独立复验：`pytest test_market_snapshot.py test_market_snapshot_auction.py test_market_snapshot_parquet.py DataPipeline/tests/intraday -q --ignore=.../test_jobs.py` → 43 passed。


## 3. 验收证据

- 后端：`pytest backend/api/tests/test_intraday_store_reader.py test_intraday_store_contract.py test_platform_data_access.py` → 22 passed。
- MarketView 后端：`pytest MarketView/tests` → 71 passed（含新增 8 例意图来源/覆盖率/未匹配/新鲜度/formal-first）。
- 前端：`npm run test` → 214 passed；面板单测 6 例；`npm run typecheck` 无错误。
- 真实产物：用管道 `D:\db\intraday\intraday_manifest.json` 实跑 `IntradayStoreReader`，6 个数据集全部解析、lag 计算正常（`intraday_fills` 18.4m、`bars_10s_t0` 2.6m、`route_params_snapshot` 1430.6m 为旧水位）。
- CI：三个 PR 各 8 项检查全绿。

## 4. 呈现定稿（D-6，2026-10-27 用户确认）

| # | 项 | 定稿 |
|---|---|---|
| 1 | 实时列取舍 | 保持三列 Last / Spread bps / Vol vs base（未显式要求增加 Bid/Ask、High/Low、参与率，按默认） |
| 2 | 列顺序 | Order → Daily baseline → Live → Estimate，Qty 不前移、Gaps 保持行内 |
| 3 | 覆盖率口径 | 按订单数（与 DL-01 定义一致） |
| 4 | 未匹配清单 | 表格上方折叠区 |
| 5 | 新鲜度阈值 | 统一 30 分钟（未知与超阈值标琥珀） |
| 6 | 实时开关 | `EMSXVIEW_INTRADAY_STATE_ENABLED` **默认开启**；设 `false` 回到四字段 |

> 用户备注：以上均可在后续实际使用中调整。第 6 项由 090 落地（含默认值测试）。

## 5. 前端验收步骤（本地）

前提：MarketView 与前端壳同时启动；core 后端不挂载 `/api/marketview/*`，Vite dev 代理已指向 `:8001`。

```powershell
# 1) MarketView（默认 :8001）
cd MarketView; python main.py

# 2) core 后端（可选；实时列需要它）
cd backend/api; python main.py

# 3) 前端壳（默认 :5173；VITE_MARKETVIEW_URL 留空即 http://localhost:8001）
cd frontend; npm run dev
```

数据前提：

| 检查项 | 需要什么 | 缺失时表现 |
|---|---|---|
| 盘前单 | `EMSXVIEW_EXPORT_INBOX_DIR` 指向 EMSX 导出收件箱 | 面板提示 No pre-trade board，`intent_source=none` |
| 意图覆盖率/未匹配 | 当日盘中库 `order_intent`（管道 J1 写入）或导出解析 | 回落导出：`intent_source=export` |
| 新鲜度 chips | `intraday_manifest.json` | 无清单则不显示该行 |
| 实时列 | core 后端 + `EMSXVIEW_INTRADAY_STATE_ENABLED`（默认 true）+ Bloomberg 会话 | 显示 `n/a` 与开启提示 |

检查点（Market View 标签页底部的 Pre-trade board 面板）：

1. 顶部 chip：`intent {intraday|export|none} · N%`、`snapshot {formal|intraday|none}`、`live off|N live`；
2. 新鲜度行：逐数据集 `dataset · 5m`，滞后 >30 分钟或未知为琥珀色；
3. 未匹配：有则显示 `N unmatched intent(s)`，可展开表（Code / Order key / PM note / Reason）；
4. 表头四组：Order (static) / Daily baseline / Live intraday / Estimate，组间竖线；
5. 实时列：Last / Spread bps / Vol vs base；关闭开关时列仍在、值为 `n/a`；
6. 预期成本带 `*` 表示 v1 模型未校准。

## 6. 已知限制

- 实时列默认开启（D-6 定稿）；设 `EMSXVIEW_INTRADAY_STATE_ENABLED=false` 时列仍在、值为 `n/a`，面板会给出开关提示。
- 盘中库由管道 J1/J2 写入；本仓只读。当日无盘中库时，意图回落到收件箱导出（`intent_source=export`）。
- 日度基线的竞价占比/价差代理已切到 `bdib_market_snapshot`（086）；无表或无行时回退 `raw_bdib` 明细，行为不变。
- `bdib_market_snapshot.adv_ratio` 覆盖有限（分母 `adv_20d` 只对当日有成交的票计算，实测 548/2143）；读取方不得把 NULL 当 0。

## 7. 1e 实现记录（2026-10-27）

按模块使命（[`docs/spec/project-structure.md` §1](spec/project-structure.md)），节点一补入 1e 批次；本页既有列含义不变：

- **DL-29**：MarketView 固定筛选池池板（`GET /api/marketview/pool-board` + `PoolBoardPanel`）——量价指标、执行难度分位与成本参考值同屏；仅用 4 个固定筛选池，不引入意图池/观察名单。
- **DL-30**：ExecutionView 执行区间量价（`GET /api/execution/interval-series` + `IntervalSeriesPanel`）——区间价格/累计量、区间 VWAP vs 成交均价 vs 到达价，可对照全天走势；缺 bar 显式 gap、不插值。
- 两项均为只读；成本为「100 万美元名义额 → qty ÷ ADV20」参考值，不是订单级预测（K3）。
