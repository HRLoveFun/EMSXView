# 061 — 交易所会话注册表

> 父计划：`specs/057-execution-decision-loop/plan.md`（DL-03）
> 分支：`061-exchange-session-registry` · worktree：`../EMSXView-wt-061-exchange-session-registry`
> 依赖：无 · 消费者：DL-08（收盘后触发）、DL-09（量曲线分段）、DL-10（基线）、DL-17（约束）、DL-18（时间窗）、DL-19（评估分桶）
> 关联：`data_access/common/exchange_tz.py`（时区映射，复用之）、`docs/EMSXDataPipeline-TECHNICAL_GUIDE.md` §5.5/§5.9（管道侧口径）

## 1. 问题

- **时段按统一时钟刻度误判**：CostView 现口径对所有市场统一切 10:30 / 14:30（`CostView/src/tca_utils.py:171-174`）——JP 有午休、LN 08:00 开盘、AU 10:00 开盘、HK/JP 午休，同一刻度在不同市场含义不同（外部依据：流动性窗口必须按市场会话定义）；
- **收盘后作业无触发点**：DL-08 按「各市场收盘 + 缓冲」触发，当前无收盘时刻查询能力；
- **收盘竞价口径不统一**：管道 `closing_auction_times` 34 所 + ADJUST 集合（竞价提前开始）在本侧无镜像，DL-13 收盘容量、DL-18 时间窗都要用。
- **注册表会过期且无更新机制**（2026-10-21 用户补充要求）：市场时段调整（半日市规则变化、竞价窗口变更）、白名单增减、假日表年度轮换都会让注册表静默失真——错误时刻一旦进入基线与约束，下游全部继承错误，必须有更新机制兜底。

## 2. 方案（P2 三栏）

### 2.1 理论依据

流动性窗口必须按市场会话定义，统一时钟刻度会误判时段（熊猫交易员《Trading Skills》）；各市场收盘时刻也是收盘后作业的触发点（tasks.md DL-03）。

### 2.2 技术方案（细化到文件与函数）

**契约数据**（`platform_data/contracts/exchange_session_contracts.py`，新建；纯数据无 IO，与既有 contracts 同风格）：

- `ExchangeSession`（frozen dataclass）：`exchange_code`、`timezone`（IANA）、`market_open` / `market_close`（本地 HH:MM）、`lunch`（可空 `(start, end)`）、`opening_auction`（可空 `(start, end)`，仅对有固定开盘竞价时段的市场填写，不确定留 None + notes 标注）、`closing_auction`（本地 HH:MM）、`early_close_auction`（bool，= 管道 ADJUST 集合）、`notes`
- `SESSION_REGISTRY`：`Config.BDIB_EXCHANGE` 白名单 26 市场的 `ExchangeSession` 表（AU/AV/BB/FH/FP/GA/GR/HK/ID/IJ/IM/IN/JP/KS/LN/MK/NA/NO/PL/SJ/SM/SP/SS/SW/US）；时刻为交易所本地挂钟时间
- `EARLY_CLOSE_AUCTION_EXCHANGES = frozenset({"JP", "PW", "SS", "BZ", "CN", "MM", "US"})`：管道 `EXCHANGE_AUCTION_TIME_ADJUST` 集合镜像（指南 §5.5 明文）
- `SESSION_REGISTRY_VERSION`：注册表版本常量（结构或数据变更时升版，语义同 `INTENT_MAPPING_VERSION`；下游记录所用版本，变更可追溯）
- `TIME_BUCKET_MARKETS = ("US", "AU", "LN", "EU", "JP")` + `SESSION_TIME_BUCKETS`：管道 S9 `assign_time_bucket` 口径镜像——5 桶 open_30m/morning/midday/afternoon/close_30m，JP 额外 lunch_break 11:30–12:30，桶 end 独占；其余市场 None（指南 §5.9）
- `MARKET_CODE_FOLDING`：管道 `derive_market_code` 折叠规则镜像（EUR 一律归 EU；MUMBAI/BOMBAY/INDIA/NSE/BSE → IN；无 Currency 时 11 个欧洲交易所折叠）
- `HALF_DAY_CLOSE_OVERRIDES`：静态半日市收盘覆盖表 `dict[(exchange_code, "MM-DD"), "HH:MM"]`——v0 收录确定性规则条目（如 US 感恩节后一日 13:00、平安夜 13:00 等），完整假日/半日日历与管道 P3 合为一份维护数据（tasks 原文「先以本侧静态表起步」）

**适配器**（`platform_data/adapters/session.py`，新建；查询函数按 module-boundary §2.3 公开无下划线）：

- `ExchangeSessionAdapter`：`get_session(exchange_code) -> ExchangeSession | None`（未注册返回 None 不抛错）、`session_relative_minutes(exchange_code, local_dt) -> int | None`（本地 naive datetime → 相对开盘挂钟分钟，午休计入）、`closing_time_for(exchange_code, trade_date) -> str | None`（半日市覆盖生效）、`is_early_close_auction(exchange_code) -> bool`、`market_code_for(exchange_code) -> str`、`time_bucket_for(exchange_code, local_dt) -> str | None`
- 时区不重复映射：注册表 `timezone` 字段与 `data_access.common.exchange_tz.EXCHANGE_TIMEZONE` 同源，测试交叉验证；UTC 换算在函数内用 `zoneinfo` 完成（DST 自动处理）

**导出**：`platform_data/contracts/__init__.py`、`platform_data/adapters/__init__.py` 增加上述符号（分组注释风格同既有）。

**更新机制**（2026-10-21 用户补充要求；两个触发条件对应两类检查）：

- **触发一定期检查**：`scripts/ops/check_exchange_session_registry.py`（新建，只读）——月度运行（schtasks 注册命令内置 docstring，与 backup_ops_db.py 的「脚本 + 清单」模式一致，不自动注册），检查四项：
  1. 覆盖完整性：`SESSION_REGISTRY` 键 vs `Config.BDIB_EXCHANGE` 差集（白名单增减）；
  2. 时区一致性：注册表 `timezone` vs `EXCHANGE_TIMEZONE` 差集；
  3. 半日市年度覆盖：`HALF_DAY_CLOSE_OVERRIDES` 是否覆盖当前年度与次年度（假日表年度轮换提醒）；
  4. 管道样本核对：US/JP/HK 收竞时刻与指南 §5.5 记载一致。
- **触发二数据不一致**：同脚本的**运行时一致性检查**（读侧只读，不下写）：
  5. 交易记录 vs 注册表：`raw_fills` 按市场聚合最近一个交易日成交的 `MIN/MAX(exec_time)`（NY 时间转本地），落在「开盘 − 15min 至收盘 + 收盘竞价窗口 + 15min」区间外的占比超过阈值（默认 0.5%）→ 该市场标记疑似时段变更；
  6. 市场数据 vs 注册表：从 `bdib_daily_summary` 取每市场最近交易日成交量最大的 1 个 ticker，点查 `raw_bdib` 当日首末 `mkt_timestamp`（每市场 1 个 ticker·日，符合 access-guide 点查上限），超出注册表边界（含 15min 缓冲）→ 标记。
  - 判定逻辑实现为**纯函数**（`judge_fills_bounds` / `judge_bars_bounds` / `judge_out_of_session_ratio`），单测覆盖；IO 组装与报告由 main 负责；退出码 0=无需关注、1=存在待更新项（供计划任务告警）。
- **更新流程**（docstring 内置）：检查报告 → 人工核对交易所公告/管道技术文档 → 修订 `SESSION_REGISTRY` 并升 `SESSION_REGISTRY_VERSION` → PR（契约测试锁定）→ 若为管道侧口径变化，先按指南 §13 更新管道文档再镜像。读取路径（DL-08/10 等）消费时记录所用版本，diff 可查。

**测试**（`backend/api/tests/test_exchange_session_registry.py`，新建；pytest 基建可 import platform_data）：

1. 覆盖完整性：`set(SESSION_REGISTRY) == set(Config.BDIB_EXCHANGE)`（26 个，无遗漏无多余）；
2. 时区一致：每个注册表条目 `timezone == EXCHANGE_TIMEZONE[code]`（双源一致）；
3. 管道样本核对：US/JP/HK 收盘竞价 = 16:00/15:30/16:00（指南 §5.5 明文）；`EARLY_CLOSE_AUCTION_EXCHANGES` 与指南 ADJUST 集合一致；
4. 会话相对时间：US 09:30→0、13:00→210；JP 09:00→0、11:00→120、12:30→210；**夏令时切换日**（2026-03-08 US、2026-03-29 EU/LN、2026-04-05 AU）挂钟相对分钟正确且换算不抛错；
5. 半日市：`HALF_DAY_CLOSE_OVERRIDES` 命中日期 `closing_time_for` 返回覆盖值，未命中返回常规收盘；
6. 时段桶：US 09:45→open_30m、12:00→midday、15:45→close_30m；JP 11:45→lunch_break；未启用市场（HK）→None；桶 end 独占边界（US 10:00 属 open_30m 还是 morning 按管道口径）；
7. 市场码折叠：EUR 系→EU、MUMBAI→IN、US→US；
8. 未知交易所：`get_session`→None、`market_code_for` 有默认折叠、`time_bucket_for`→None（不抛错）。

**检查脚本纯函数单测**（`backend/api/tests/test_exchange_session_check.py`，新建）：

9. `judge_fills_bounds` / `judge_bars_bounds`：边界内（含 15min 缓冲）不标记、超界标记；空数据不标记（缺数据 ≠ 不一致）；
10. `judge_out_of_session_ratio`：阈值边界（0.5% 阈值，等于不超、超过才标记）；
11. `check_half_day_coverage`：条目缺当前年度 → 提醒；覆盖当前 + 次年度 → 通过；
12. `check_registry_coverage` / `check_timezone_consistency` / `check_doc_samples`：注入构造的差集/一致场景。

### 2.3 数据来源与边界（诚实记录）

- 26 市场会话时刻按公开市场规则构建，与指南 §5.5/§5.9 记载样本核对；管道 `closing_auction_times` **完整 34 表**（管道仓库私有、指南未列全表）在 DL-06 契约冻结时替换为管道权威镜像并加两仓契约测试——DL-03 交付结构 + 函数 + 白名单数据 + 样本级核对；
- 开盘竞价字段「不确定留 None」优先于猜测填充（防把错误时刻当下一步契约冻结）；
- 假日/半日完整日历属管道 P3，v0 只做确定性规则条目。

### 2.4 检验方法（= 验收标准）

1. 覆盖 BDIB 白名单全部市场（用例 1）；
2. 夏令时切换日与半日市单测（用例 4/5）；
3. 与管道 closing_auction_times 的契约测试（用例 3 样本级；完整镜像 DL-06 冻结）；
4. 既有测试不回归（backend 全量 + boundaries）。

## 3. 规模与拆分说明

预估 diff 约 630 行（注册表数据 ~230 + 适配器 ~90 + 检查脚本 ~120 + 测试 ~190）。DL-03 为验收原子单元（数据 + 函数 + 更新机制 + 测试一次交付——没有更新机制的注册表是半成品，用户 2026-10-21 补充要求），沿用 DL-01/DL-02 经用户确认的单 PR 先例。

## 4. 范围锁

| 动作 | 文件 |
|---|---|
| 新建 | `platform_data/contracts/exchange_session_contracts.py` |
| 修改 | `platform_data/contracts/__init__.py`（导出） |
| 新建 | `platform_data/adapters/session.py` |
| 修改 | `platform_data/adapters/__init__.py`（导出） |
| 新建 | `backend/api/tests/test_exchange_session_registry.py` |
| 新建 | `backend/api/tests/test_exchange_session_check.py` |
| 新建 | `scripts/ops/check_exchange_session_registry.py` |
| 新建 | `specs/061-exchange-session-registry/plan.md`（本文件） |

范围外（不碰）：`CostView/src/tca_utils.py` 时段分桶改造（DL-19）、`route_engine._parse_end_time` 时区修复（DL-18）、管道侧权威镜像与两仓契约（DL-06）、完整假日日历（管道 P3）、MarketView 端点（DL-10 起）、`data_access/common/exchange_tz.py`（只复用不修改）。

## 5. 验收（P4）

| 需求（057 DL-03 检验方法） | 覆盖 | 结果 |
|---|---|---|
| 覆盖 BDIB 白名单全部市场 | 用例 1 | 待实施后回填 |
| 夏令时切换日与半日市单测 | 用例 4/5 | 待实施后回填 |
| 与管道 closing_auction_times 契约测试 | 用例 3（样本级） | 待实施后回填 |
| 既有测试不回归 | backend 全量 + boundaries | 待实施后回填 |

## 6. 本次不做

- CostView 统一切法改造（DL-19 按会话相对分桶时消费本注册表）；
- 路由引擎时区修复（DL-18，复用 `session_relative_minutes` 与收盘查询）；
- 管道权威镜像同步（DL-06 契约冻结动作）；
- 完整假日日历（管道 P3 后接入，静态表继续承担半日市规则条目）。
