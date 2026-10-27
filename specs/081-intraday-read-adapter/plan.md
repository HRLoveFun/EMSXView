# 081 — DL-07 读侧：盘中库只读适配器与新鲜度可见

> 父计划：`specs/057-execution-decision-loop/plan.md`（节点一 · 1b，DL-07 预留接口）
> 分支：`081-intraday-read-adapter`（worktree `../EMSXView-wt-081-intraday-read-adapter`，基线 `e30b748`）
> 依赖：DL-06 契约（`platform_data/contracts/intraday_store_contracts.py`，已冻结）；管道侧 DL-07/08 已落地
> 状态：按目标指令直接实施（用户已设定「抵达第一个验收里程碑」目标）

## 1. 问题（是什么）

盘中库（`intraday_YYYYMMDD.db`）已由管道 J1/J2 写入，新鲜度清单 `intraday_manifest.json` 已按契约原子写；本侧**没有任何读取入口**：

- `data_access` 只有按 DB key 映射的 `ConnectionManager`，盘中库是按交易日分文件，无法用既有 key 打开；
- DL-06 冻结的 `DataFreshness` 契约没有任何实现者——节点一出口判据要求「各数据集新鲜度可见」无法满足；
- MarketView 盘前单仍直读收件箱导出，DL-07 上线后的 `order_intent` 表无人消费。

## 2. 方案（为什么这样做）

只做**读**，且只做一个最小可复用适配器，不碰 MarketView 装配与前端（下一编号做）：

- 以 sqlite3 URI `mode=ro` 打开当日盘中库，不建库、不写、不加锁升级（与 ADR-0016 的 `mode=ro` 口径对称）；
- 六张表按契约 `TABLE_COLUMNS` 逐列 SELECT——列序由契约锁定，避免 `SELECT *` 随管道 DDL 漂移；
- 降级纪律：文件不存在 / 表缺失 / 清单损坏 → 空列表或 `None`，由调用方显式呈现；**不静默当最新**；
- 新鲜度：从 manifest 逐数据集算 `lag_minutes`，`as_of` 不可解析记 `-1.0`（显式未知，不填 0）。

## 3. 落地（范围锁）

| # | 文件 | 类型 | 内容 |
|---|---|---|---|
| 1 | `data_access/storage/intraday_store_reader.py` | 新增 | `IntradayStoreReader`：六表读取 + manifest + freshness |
| 2 | `data_access/__init__.py` | 改 | 导出 `IntradayStoreReader` |
| 3 | `backend/api/tests/test_intraday_store_reader.py` | 新增 | 降级三态、列契约、freshness 计算 |
| 4 | `specs/057-execution-decision-loop/tasks.md` | 改 | DL-07/DL-08 状态回填 + 本条记录 |

预估约 +260 行（含测试）。不新增依赖，不改契约版本。

## 4. 验收（取自 DL-07 检验方法）

1. 缺库/缺表/坏清单三态均返回空且不抛错；
2. 读取列集合与 `TABLE_COLUMNS` 完全一致；
3. `freshness` 按 as_of 计算滞后，未知 as_of 记 -1.0，naive 时间按 UTC；
4. 未知表名显式 `ValueError`（防拼写漂移静默返回空）；
5. 单测 8 例全绿，全量后端测试不回归。
