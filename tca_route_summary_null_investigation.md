# tca_route_summary 空值调查报告

生成时间: 2026-07-20

## 总体统计

- 总行数: 198,940
- 交易日: 214 个（20250915 .. 20260715）
- `par_rate` 为 NULL: 165,897 行（83.4%）
- `par_rate_close` 为 NULL: 154,790 行（77.8%）

## 空值原因分类

### 1. 2025 年日期无 raw_bdib 数据

- 行数: 86,326
- raw_bdib 仅覆盖 2026-01-01 至 2026-07-15（137 个交易日）
- 2025 年共 77 个交易日，全部无 intraday bars
- 涉及指标: par_rate、par_rate_continuous、par_rate_close、p_avg_continuous、pnl_vwap、pnl_vwap_continuous、RPM、RPM_continuous、PWP 全部为空

### 2. 2026 年有 raw_bdib 但部分 route 无 bars 匹配

- 行数: par_rate 空 79,571 行；par_rate_close 空 68,464 行
- 2026 年总行数: 112,614
- par_rate 空比例: 70.7%
- par_rate_close 空比例: 60.8%

主要原因:

1. **fills 时间戳超出 bdib 覆盖范围**
   - 部分 closing auction fills 的本地时间戳晚于 bdib 末行时间（例如 US 市场 16:00:00 收盘，但 fill 时间戳在 16:00:00 及之后，bdib 末行仅到 15:59:50）。
   - 已修复 `par_rate` 的分母终点为 `min(末笔 fill 时间, bdib 末行时间)`，避免窗口越界。

2. **收盘集合竞价 fills 无法匹配到 bars**
   - 旧逻辑使用 closing auction fills 的首末时间戳切 bars；当 fill 时间戳晚于 bdib 末行时，close_window 为空，导致 `par_rate_close` 为空。
   - 已修复为使用交易所固定收盘集合竞价时段（由 `closing_auction_times` 定义）取 bars，不再依赖 fill 时间戳。

3. **ticker 级别 BDIB 缺失**
   - 2026 年 1-2 月尤其严重，因 Bloomberg BDIB API 6-9 个月保留窗口限制，无法回补历史数据。

## 修复记录

### 2026-07-20: par_rate / par_rate_close 计算逻辑修正

- **问题**: closing auction fills 的时间戳经常比 bdib 更晚，导致 `par_rate_close` 按 fill 时间戳切片时得到空窗口。
- **修复**:
  - `par_rate` 分母终点改为 `min(末笔 fill 成交时间, bdib 末行时间)`。
  - `par_rate_close` 分母改为交易所固定收盘集合竞价时段，使用 `DataPipeline/common/mapping.py` 中的 `closing_auction_times` 与 `EXCHANGE_AUCTION_TIME_ADJUST` 定义，与 `fill_processor` 的 `is_closing_auction` 判定规则保持一致。
  - `par_rate_continuous` 保持不变。
- **代码改动**:
  - `DataPipeline/processing/tca_route_metrics.py`
  - `DataPipeline/tests/processing/test_tca_route_metrics.py`（新增 2 个回归测试）
- **回填**:
  - `scripts/recompute_route_metrics.py --start-date 20260105 --end-date 20260715 --force`
  - 处理 137 个交易日，写入 112,614 行，错误 0
- **效果示例（20260305）**:
  - 修复前 par_rate_close 空值: 1,445 / 1,515（95.4%）
  - 修复后 par_rate_close 空值: 705 / 1,515（46.5%）

## 按交易所空值比例（2026 年）

见 `trs_null_by_exchange.csv`。

## 结论

- 2025 年数据无 bdib，空值为预期。
- 2026 年空值比例仍然较高，主要由 fills 时间戳超出 bdib 范围、收盘集合竞价特性、以及部分 ticker 缺失 BDIB 导致。
- 本次修复显著降低了 `par_rate_close` 的空值率（以 20260305 为例，从 95.4% 降至 46.5%）。

## 输出文件

- 按日期汇总: `tca_route_summary_summary.csv`
- 全量明细: `tca_route_summary_export.csv`
- 按交易所空值分布: `trs_null_by_exchange.csv`
