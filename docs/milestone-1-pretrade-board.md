# 节点一交付说明：交易前实时监控表（057 · 2026-10-27）

> 依据：`specs/057-execution-decision-loop/plan.md` 第 5 节节点一出口判据
> 覆盖：1a–1d（DL-01 至 DL-15）+ DL-07/08 读侧接线
> 状态：代码侧完成；呈现定稿（D-6）待用户反馈后收口

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

## 5. 已知限制

- 实时列默认开启（D-6 定稿）；设 `EMSXVIEW_INTRADAY_STATE_ENABLED=false` 时列仍在、值为 `n/a`，面板会给出开关提示。
- 盘中库由管道 J1/J2 写入；本仓只读。当日无盘中库时，意图回落到收件箱导出（`intent_source=export`）。
- 日度基线的竞价占比/价差代理已切到 `bdib_market_snapshot`（086）；无表或无行时回退 `raw_bdib` 明细，行为不变。
- `bdib_market_snapshot.adv_ratio` 覆盖有限（分母 `adv_20d` 只对当日有成交的票计算，实测 548/2143）；读取方不得把 NULL 当 0。
