# 227 — A14 首批：`get_intraday_features` 特征化测试 + 拆分

> 来源：`audit-remediation-2026-10-25.md` **A14（E5）** Top 1 复杂度热点
> 分支：`227-a14-intraday`（worktree `../EMSXView-wt-227-a14-intraday`，基于 `origin/main`）

## 问题

`platform_data/adapters/market.py` 的 `get_intraday_features`：**218 行 / CC 66 / 嵌套 5**，且该适配器此前**没有任何测试**。直接拆无法证明行为不变。

## 方案（测试先行）

1. 新增 `MarketView/tests/test_market_adapter_intraday.py`：固定 2 ticker + 缺失 ticker 的最小 BDIB 夹具，逐字段锁定
   桶、累计量、VWAP、开/收盘 10 分钟窗口、ADV20 占比与校验/空路径。
2. 拆分（行为不变）：
   - `_validate_intraday_request` / `_empty_intraday_snapshot`
   - `_query_raw_bdib_bars` / `_query_daily_summary`
   - `_time_to_seconds` / `_bar_time_range` / `_daily_vwap` / `_summary_values`
   - `_realized_vol` / `_bucket_vwap` / `_bucket_extremes` / `_bucket_realized_vol` / `_make_bucket` / `_build_buckets`
   - `_window_volume_vwap` / `_window_share` / `_window_stats`
   - `_build_ticker_features`；顶层只做校验 → 早退 → 查询 → 逐 ticker 组装 → snapshot。
3. 质量门禁验证：`get_intraday_features` 与新增 helper 均不再出现在 OE-05 报告中。

## 验收

- 特征化测试在拆分前后均 2 passed；
- `MarketView/tests` 94 passed；
- 质量门禁中 `market.py` 仅剩既有的 `get_market_snapshot`（本轮未动）；
- 全仓测试与 `doc_check.py` 全绿。

## 边界（A14 仍为多批次）

A14 的 Top 3 中，本轮只处理 #1 `get_intraday_features`；`redis_handoff` 参数对象化与前端三件套拆分仍待后续批次。
