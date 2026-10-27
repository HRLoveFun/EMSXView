# 086 — 日度基线优先读 DL-09 快照表（省去当日 10 秒 bar 扫描）

> 父计划：`specs/057-execution-decision-loop/plan.md`（DL-10 预留接口：DL-09 快照表就绪后替换 bar 级近似）
> 分支：`086-baseline-snapshot-source`（基线 `origin/main`）
> 依赖：管道 DL-09 第二批（`4db9670`，快照表已含 `auction_open_pct` / `auction_close_pct` / `spread_proxy_bps`）

## 1. 问题（是什么）

`DailyBaselineAdapter` 每票每天都扫一次 `raw_bdib` 的当日 10 秒 bar（约 2,340 行）来算竞价占比与价差代理。盘前单 40 票 × 每 5 分钟刷新 → 每轮 ~9 万行；DL-09 已把同口径结果写进 `bdib_market_snapshot`，读侧却没用上。

## 2. 方案（为什么这样做）

- 新增 `_load_snapshot_features(mgr, ticker, trade_date)`：点查 `bdib_market_snapshot` 的 `(auction_open_pct, auction_close_pct, spread_proxy_bps)`；
- `_baseline_for` 先查快照：命中 → 直接用；表不存在（旧数据目录）或该票无行 → 回退原 bar 扫描路径，**行为不变**；
- 快照三列本身可为 NULL（US 无开盘竞价窗口、有效 bar < 5 根），此时原样返回 NULL 而不回退——与 bar 路径的判定一致；
- 其余字段（log 量 z、波动分位、ADV5/60、跳空 σ）数据源不变（`bdib_daily_summary`），避免样本窗口变化改变数值。

## 3. 落地（范围锁）

| # | 文件 | 类型 | 内容 |
|---|---|---|---|
| 1 | `platform_data/contracts/db_constants.py` | 改 | 新增 `BDIB_MARKET_SNAPSHOT_TABLE` 常量 |
| 2 | `platform_data/adapters/baseline.py` | 改 | `_load_snapshot_features` + 快照优先分支 |
| 3 | `backend/api/tests/test_baseline_snapshot_source.py` | 新增 | 快照优先 / 无表回退 / 无行空基线 |
| 4 | `specs/057-execution-decision-loop/tasks.md` | 改 | DL-10 注记 086 |

## 4. 验收

1. 快照行存在 → 三列取快照值（测试用与 bar 明显不同的 7.5 / 12.5 / 33.3）；
2. 无快照表 → 回退 bar：US 开盘 `None`、收盘 60.0%、价差 `None`（3 根 < 5）；
3. 快照表在但票无行 → 空基线（`n_days=0`）；
4. `pytest test_baseline_snapshot_source.py test_daily_baseline.py` → 15 passed；边界测试 24 passed；DB 路径与跨模块 import 审计通过。
