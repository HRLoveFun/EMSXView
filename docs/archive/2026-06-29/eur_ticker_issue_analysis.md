# processed_fills 表 EUR 股票 equ_ticker 缺失问题分析

> **排查日期**：2026-06-29
> **涉及模块**：`DataPipeline/processing/fill_processor.py`、`DataPipeline/ingestion/fill_ingestion.py`
> **影响数据**：`processed_fills.db` 中 `Currency='EUR'`（raw_fills 侧约 638,491 行）的 `equ_ticker` 字段大面积为 NULL

> **状态（2026-07-02 更新）**：本报告所列 P0~P3 问题已全部解决，详细修复记录见 git log。本文件保留作为 EUR 处理逻辑（Exchange 语义、route_registry 方案）的设计决策参考，不再作为待办清单。

---

## 1. 用户原始问题

> processed fills 没有列 `Side`、`Currency`
>
> 排查"EUR 走缓存优先 + Bloomberg `EU_COMPOSITE_TICKER` 查询回写 `ticker_registry.db`"这一步出现了什么问题，导致 processed fills 中 `Currency == "EUR"` 的行，对应的 `Exchange` 值不是 `"EU"`，且列 `equ_ticker` 的值不是格式 `* EU Equity`。

---

## 2. 数据现状

### 2.1 processed_fills 表 Schema

`processed_fills` 表共 22 列（定义见 `DataPipeline/storage/schema/columns.py:41-48` `PROCESSED_COLUMNS`）：

```
FillId, OrderId, RouteId, mkt_timestamp,
order_as_of_date, local_fill_datetime, exchange_exec_time,
route_as_of_time, DateTimeOfFill, Broker, StrategyType,
algo, TraderName, Exchange, Amount, RouteShares,
is_closing_auction, ExecType, region, equ_ticker,
FillPrice, FillShares
```

- **不含 `Currency` 列** ❌
- **不含 `Side` 列** ❌

但 `AGG_COLUMNS`、`ROUTE_REGISTRY_COLUMNS`、`ROUTE_HISTORY_COLUMNS` 中均包含 `Side`，`AGG_COLUMNS` 还包含 `Currency`。`Side/Currency` 字段被排除在 `PROCESSED_COLUMNS` 之外是 schema 层的**设计选择**，并非字段丢失。

### 2.2 raw_fills 表 Schema（对照）

`raw_fills` 包含完整 35 列，其中含 `Currency`、`Side`、`Ticker`。要对 processed_fills 按 `Currency='EUR'` 筛选，必须通过 `(OrderId, FillId, order_as_of_date)` 回 join `raw_fills.db`。

### 2.3 EUR 行在 processed_fills 中的状态

| 指标 | 数值 |
|------|------|
| raw_fills 中 `Currency='EUR'` 总行数 | 638,491 |
| 唯一 `(Ticker, Exchange)` 组合数 | 299 |
| 缓存 `eur_composite_ticker_cache` 行数 | 231 |
| raw_fills EUR 行应命中缓存的行数 | 535,218 |
| processed_fills 中 `equ_ticker LIKE '% EU Equity'` 实际行数 | **22,936**（仅占应得 4.3%） |
| processed_fills 中 `region='EMEA'` 且 `equ_ticker IS NULL` | 942,912（占 EMEA 总数 96.2%） |

---

## 3. 问题诊断

### 问题 1：processed_fills 缺 `Currency`/`Side` 列

**性质**：schema 设计选择，非 bug。

- `PROCESSED_COLUMNS`（`storage/schema/columns.py:41-48`）刻意只保留 22 列
- 需要按 `Currency` 筛选时，必须 join `raw_fills.db`
- `route_registry` 表含 `ccy_ticker`，可间接判断货币

### 问题 2：EUR 行 `Exchange` 字段未变为 "EU"

**性质**：代码从未设计改写 `Exchange` 字段，非 bug 但与用户预期不符。

- `add_equity_ticker`（`fill_processor.py:142-224`）只修改 `equ_ticker` 列
- `Exchange` 字段始终保留原始 Bloomberg 交易所代码（`FP`/`GR`/`IM`/`SM`/`FH`…）
- ` EU Equity` 格式**只出现在 `equ_ticker` 字段中**，不会出现在 `Exchange` 中
- raw_fills 中 EUR 行的 Exchange 分布：`GR=149825, FP=126308, IM=109037, SM=52580, FH=45710, NA=36186, BB=26438, PL=10086, AV=6453, ID=5811, GA=4908, SS=699, None=64450`

### 问题 3：EUR 行 `equ_ticker` 不是 `* EU Equity` — ★ 真实 bug

**根因定位**：`DataPipeline/processing/fill_processor.py:215-222`

```python
# ④ 合并结果, 映射: 未命中 → NaN（dict 中不存在的 key 自动映射为 NaN）
composite_map = {**cache_hit, **bbg_results}
if composite_map:
    df.loc[eur_mask, "equ_ticker"] = df.loc[eur_mask, "equ_ticker"].map(composite_map)
else:
    # BBG 完全不可用且无缓存 → 全部设为 NaN
    df.loc[eur_mask, "equ_ticker"] = np.nan
```

#### Bug A — `Series.map(dict)` 对未命中 key 返回 NaN

验证脚本输出：

```
输入: ['AAA FP Equity', 'BBB IM Equity', 'CCC XX Equity']
composite_map keys: ['AAA FP Equity', 'BBB IM Equity']
map 结果: ['AAA EU Equity', 'BBB EU Equity', nan]
未命中的 "CCC XX Equity" → nan (NaN 表示丢失原始值)
```

当 EUR ticker 缓存 miss + BBG 不可用/超时/未返回时，**原始已拼接的 `XXX FP Equity` 被丢弃变成 NaN**，没有任何 fallback。

源码注释 ④ 甚至明确写了 "未命中 → NaN（dict 中不存在的 key 自动映射为 NaN）" —— 这是被显式接受的错误行为。

#### Bug B — `else` 分支把所有 EUR 行 `equ_ticker` 全部 NaN

当 `composite_map` 为空（缓存空 + BBG 失败）时：

```python
df.loc[eur_mask, "equ_ticker"] = np.nan
```

直接丢弃了已经拼接好的原始 `XXX FP Equity` 值。正确行为应保留原值 + 记录 warning。

---

## 4. 时间线证据（决定性）

### 4.1 缓存创建时间

`eur_composite_ticker_cache` 表 `created_at` 分布：

| 日期 | 新增条数 |
|------|---------|
| 2026-06-16 | 152 |
| 2026-06-17 | 29 |
| 2026-06-18 | 23 |
| 2026-06-25 | 23 |
| 2026-06-26 | 2 |
| 2026-06-29 | 2 |

**缓存最早建立于 2026-06-16**，此前任何 `process_raw_fills_for_date` 调用都会走 `composite_map={}` 的 else 分支 → 全部 NaN。

### 4.2 processed_fills 按月份的 EUR equ_ticker NULL 率

| 月份 | EMEA 总数 | NULL 率 | EU Equity 行数 |
|------|----------|---------|---------------|
| 2025-09 | 57,084 | **100.0%** | 0 |
| 2025-10 | 103,165 | **100.0%** | 0 |
| 2025-11 | 105,243 | **100.0%** | 0 |
| 2025-12 | 87,844 | **100.0%** | 0 |
| 2026-01 | 97,705 | **100.0%** | 0 |
| 2026-02 | 79,187 | **100.0%** | 0 |
| 2026-03 | 128,000 | **100.0%** | 0 |
| 2026-04 | 79,903 | 97.6% | 1,495 |
| 2026-05 | 173,415 | **100.0%** | 0 |
| 2026-06 | 68,448 | 48.6% | 21,441 |

- processed_fills 全表 `order_as_of_date` 范围：`20250915 ~ 20260626`
- processed_fills 中 `equ_ticker LIKE '% EU Equity'` 的日期范围：`20260416 ~ 20260626`
- **2025-09 ~ 2026-05 期间（9 个月）的 EUR 行 equ_ticker 100% 为 NULL** — 与缓存建立时间完全吻合

### 4.3 数据规模对比

- raw_fills `Currency='EUR'`：**638,491 行**（271 个唯一 ticker）
- 缓存命中应得：**535,218 行**
- processed_fills 实际 `equ_ticker LIKE '% EU Equity'`：**22,936 行**（仅占应得 4.3%）
- 丢失：约 **51 万行** EUR 的 `equ_ticker` 被错误设为 NULL

---

## 5. 额外异常：非 EUR 的 EMEA 行也大量 NULL

### 5.1 各 Exchange 的 Currency 与 equ_ticker 状态

| Exchange | EMEA total | null | eu_eq | other | raw 主 Currency |
|----------|-----------|------|-------|-------|----------------|
| GR | 151,665 | 143,205 (94.4%) | 8,460 | 0 | EUR |
| LN | 132,008 | 129,693 (98.2%) | 0 | 2,315 | **GBp** |
| FP | 128,655 | 123,827 (96.2%) | 4,828 | 0 | EUR |
| IM | 109,958 | 106,466 (96.8%) | 3,492 | 0 | EUR |
| (空) | 66,590 | 66,590 (100.0%) | 0 | 0 | — |
| PW | 57,381 | 49,148 (85.7%) | 0 | 8,233 | **PLN** |
| SJ | 57,279 | 56,072 (97.9%) | 0 | 1,207 | **ZAr** |
| SM | 52,970 | 52,197 (98.5%) | 773 | 0 | EUR |
| FH | 46,167 | 45,068 (97.6%) | 1,099 | 0 | EUR |
| NA | 36,072 | 33,221 (92.1%) | 2,851 | 0 | EUR |
| SW | 33,916 | 33,198 (97.9%) | 0 | 718 | **CHF** |
| SS | 30,508 | 29,784 (97.6%) | 2 | 722 | **SEK** |
| BB | 27,503 | 26,728 (97.2%) | 775 | 0 | EUR |
| DC | 11,231 | 11,006 (98.0%) | 0 | 225 | **DKK** |
| NO | 10,530 | 9,804 (93.1%) | 0 | 726 | **NOK** |
| PL | 10,153 | 9,757 (96.1%) | 396 | 0 | EUR |
| AV | 6,578 | 6,376 (96.9%) | 202 | 0 | EUR |
| ID | 5,825 | 5,767 (99.0%) | 58 | 0 | EUR |
| GA | 5,005 | 5,005 (100.0%) | 0 | 0 | EUR |

### 5.2 异常点

- **LN（GBp）132,008 行中 129,693 NULL（98%）**
- **PW（PLN）57,381 行中 49,148 NULL（86%）**
- **SJ（ZAr）57,279 行中 56,072 NULL（98%）**
- **SW（CHF）/ SS（SEK）/ DC（DKK）/ NO（NOK）也几乎全部 NULL**

这些货币**不是 EUR**，代码逻辑 `eur_mask = df["Currency"]=="EUR"` 不会触发 BBG 查询分支，应保留原始 `XXX LN Equity` 等拼接值。

但实际数据中这些非 EUR EMEA 行也大量 NULL，仅少量保留原值（如 LN 有 2,315 行 `other`）。这说明：

1. **早期版本代码逻辑可能与当前不同**（历史数据污染）
2. 或 `add_equity_ticker` 之外的其他阶段（如 `clean_emsx_fills` 的 `normalize_fill_columns`）对某些 EMEA 行的 `Ticker/Exchange` 做了意外清洗导致 `blank_mask` 命中 → `equ_ticker = NaN`
3. 需要查 `git log` / `git blame` 确认 `fill_processor.py:142-224` 的历史变更

### 5.3 验证 blank_mask 的可能性

`fill_processor.py:166-183` 的 `blank_mask` 逻辑：

```python
exchange_blank = (
    df["Exchange"].isna()
    | (df["Exchange"].astype(str).str.strip() == "")
    | (df["Exchange"].astype(str).str.lower().isin(["nan", "none"]))
)
ticker_blank = (
    df["_processed_ticker"].isna()
    | (df["_processed_ticker"].astype(str).str.strip() == "")
    | (df["_processed_ticker"].astype(str).str.lower().isin(["nan", "none"]))
)
blank_mask = exchange_blank | ticker_blank
df.loc[blank_mask, "equ_ticker"] = np.nan
```

raw_fills EUR 行中 `Exchange IS NULL` 的有 64,450 行 — 这部分被 `blank_mask` 正确设为 NaN 是合理行为。但 LN/PW/SJ 等 Exchange 非空的行 NULL 率仍达 86-98%，**不能完全用 blank_mask 解释**，需进一步排查历史代码版本。

---

## 6. 数据完整性影响

### 6.1 受影响表（衍生链路）

processed_fills 是下游多个表的数据源：

```
raw_fills.db
  → processed_fills.db（★ equ_ticker 缺失）
    → agg_fills_10s（S3 AggregateFillsStage，复制 equ_ticker）
    → order_label（S4 GenerateOrderLabelsStage）
    → route_registry / route_history / route_event_history
  → fill_bdib.db（S5 通过 equ_ticker 关联 BDIB 市场数据）
  → bdib_daily_summary（S7 通过 equ_ticker 计算 ADV/波动率）
```

### 6.2 下游影响

- `fill_bdib` 通过 `equ_ticker` join BDIB 市场数据 → EUR 股票约 51 万行无法关联市场数据
- `bdib_daily_summary` 计算 ADV/波动率时 EUR 股票缺失
- TCA（CostView）分析中 EUR 股票的 benchmark/vwap 对照失效
- route_history 中 EUR 行的 `equ_ticker` 也为 NULL（`_build_execution_history_frames` 直接从 processed_df 取值）

### 6.3 不可通过 join 修复

processed_fills 主表 `equ_ticker` 为 NULL 的行无法通过 SQL `UPDATE ... FROM` 简单回填，因为：
1. raw_fills 中 EUR 行的 `Ticker/Exchange` 可重建原始拼接值
2. 但要判断 BBG composite ticker 映射，仍需走 Python 缓存 + BBG 查询逻辑
3. 最稳妥方案是**重跑 `process_raw_fills_for_date`**（缓存现已建立，90%+ 可命中）

---

## 7. 修复建议

### 7.1 代码修复（优先级 P0）

**位置**：`DataPipeline/processing/fill_processor.py:215-222`

**当前代码**：

```python
composite_map = {**cache_hit, **bbg_results}
if composite_map:
    df.loc[eur_mask, "equ_ticker"] = df.loc[eur_mask, "equ_ticker"].map(composite_map)
else:
    # BBG 完全不可用且无缓存 → 全部设为 NaN
    df.loc[eur_mask, "equ_ticker"] = np.nan
```

**建议修复**：

```python
composite_map = {**cache_hit, **bbg_results}
if composite_map:
    # 未命中的 ticker 保留原始拼接值（fallback），不再丢弃为 NaN
    mapped = df.loc[eur_mask, "equ_ticker"].map(composite_map)
    df.loc[eur_mask, "equ_ticker"] = mapped.fillna(df.loc[eur_mask, "equ_ticker"])
else:
    # BBG 完全不可用且无缓存 → 保留原始拼接值，仅记录 warning
    logger.warning(
        "EUR composite ticker 缓存为空且 BBG 查询失败，%d 行保留原始拼接 equ_ticker",
        int(eur_mask.sum()),
    )
```

### 7.2 历史数据回填（优先级 P0）

对 `order_as_of_date` 在 `20250915 ~ 20260615` 范围内、`region='EMEA'` 的日期重跑 `process_raw_fills_for_date`：

```python
from DataPipeline.ingestion.fill_ingestion import process_raw_fills_for_date
# 缓存已建立（231 条），重跑后 90%+ EUR 行可命中缓存
for date_str in ["20250915", "20250916", ...]:
    process_raw_fills_for_date(date_str)
```

或在 `run_full_pipeline(force=True, dates=[...])` 中用 `force=True` 强制重处理。

### 7.3 非 EUR EMEA 行的 NULL 异常（优先级 P1）

需进一步排查：

1. `git log --follow DataPipeline/processing/fill_processor.py` 查 `add_equity_ticker` 历史变更
2. `git log --follow DataPipeline/processing/fill_cleaner.py` 查 `normalize_fill_columns` 是否曾把 LN/PW/SJ 等 Exchange 误转为 "nan" → "NA"（`fill_cleaner.py:221` 有 `replace("nan", "NA")`，可能历史版本逻辑不同）
3. 对 LN 行抽样重跑 `process_raw_fills_for_date` 看是否能复现 NULL

### 7.4 Exchange 字段语义澄清（优先级 P2）

用户期望 `Exchange='EU'` 与代码设计不符。如确实需要"欧洲统一市场"标识字段，建议：

- **方案 A**：新增 `composite_exchange` 列，对成功命中 BBG composite 的行设为 `"EU"`，保留 `Exchange` 原值
- **方案 B**：在 `add_equity_ticker` 命中 composite 后，额外写 `df.loc[eur_mask & hit_mask, "Exchange"] = "EU"`（破坏原 Exchange 语义，不推荐）
- **方案 C**：在 `route_registry` 表中已有 `ccy_ticker`，前端按需 join 判断货币即可

### 7.5 Schema 增强（优先级 P3）

若经常需要按 `Currency`/`Side` 筛选 processed_fills：

- 将 `Currency`、`Side` 加入 `PROCESSED_COLUMNS`（`storage/schema/columns.py:41`）
- 走 `inline_ddl.py` 的 schema 迁移框架加列
- 或在 `route_registry` 表（已含 `ccy_ticker`、`Side`）中按 `(OrderId, RouteId)` join 查询

---

## 8. 验证脚本

以下脚本存放于 `%TEMP%\opencode\` 目录，可用于复现本次排查：

| 脚本 | 用途 |
|------|------|
| `probe_eur.py` | 初步探测 processed_fills schema、region 分布 |
| `probe_eur2.py` | equ_ticker 含 `EU Equity` 的 Exchange 分布 |
| `probe_eur3.py` | ticker_registry.db 缓存表状态 |
| `probe_eur4.py` | raw_fills EUR 唯一 ticker vs 缓存命中 |
| `probe_eur5.py` | 缓存命中行数 vs processed_fills 实际 EU Equity 行数 |
| `probe_eur6.py` | EMEA 各 Exchange 的 equ_ticker 状态细分 + 跨表 join 验证 |
| `probe_eur7.py` | Series.map 行为验证 + 时间线证据 |

---

## 9. 总结

| 问题 | 性质 | 严重度 | 修复优先级 |
|------|------|-------|----------|
| processed_fills 缺 `Currency`/`Side` 列 | schema 设计选择 | 低 | P3 |
| EUR 行 `Exchange` 未变 "EU" | 代码未设计改写 | 低 | P2 |
| EUR 行 `equ_ticker` 非 `* EU Equity` | **真实 bug**（`Series.map` 丢值 + else 分支全 NaN） | **高** | **P0** |
| 非 EUR EMEA 行大量 NULL | 历史代码污染（已修复） | 中 | ~~P1~~ 已解决 |
| 历史数据 51 万行 equ_ticker 缺失 | 数据回填 | **高** | **P0** |

**核心结论**：`fill_processor.py:215-222` 的 EUR composite ticker 映射逻辑存在两个 bug，叠加缓存建立时间晚（2026-06-16），导致 2025-09 ~ 2026-05 期间约 51 万行 EUR 股票的 `equ_ticker` 被错误设为 NULL，并影响下游 `agg_fills_10s`、`fill_bdib`、`bdib_daily_summary`、TCA 分析等整条衍生链路。

---

## 10. P0 修复后状态（2026-06-30 验证）

### 10.1 代码修复

`fill_processor.py:214-233` 的两个 bug 已修复（见提交记录）：

- **Bug A 修复**：`Series.map(composite_map)` 未命中的行用 `mapped.fillna(original_values)` 保留原始拼接值
- **Bug B 修复**：`else` 分支（缓存空 + BBG 失败）保留原始拼接值并记录 warning，不再设为 NaN

### 10.2 历史数据回填

对 142 个受影响 `source_date` batch（20250919 ~ 20260626）执行 `run_full_pipeline(dates=[...], skip_bdib=True)`，重跑 S2-S4。

### 10.3 回填后关键指标（Currency='EUR'，JOIN raw_fills 统计）

| 指标 | 回填前（备份） | 回填后（当前） | 变化 |
|------|-------------|-------------|------|
| EUR 总行数（raw_fills） | 638,491 | 638,491 | 不变（只读） |
| JOIN 匹配行数 | 636,389 | 636,389 | 一致 |
| equ_ticker NULL | 592,945（93.17%） | 64,450（10.13%） | **-83.04pp** |
| EU Equity 率 | 43,444（6.83%） | 564,789（88.75%） | **+81.92pp** |
| Exchange='EU' 率 | 0（0.00%） | 0（0.00%） | 无变化（设计如此，见 P2） |

残留 EUR NULL 64,450 行 = raw_fills 中 `Exchange IS NULL` 的行（`blank_mask` 命中，合理行为）。

---

## 11. P1 — 非 EUR EMEA 行 NULL 异常排查结论

### 11.1 排查结果

报告 5.1 节显示回填前非 EUR EMEA 行 NULL 率极高（LN 98.2%、PW 85.7%、SJ 97.9% 等）。P0 回填后重新统计：

| Currency | Exchange | 回填前 NULL 率 | 回填后 NULL 率 | 状态 |
|----------|---------|-------------|-------------|------|
| GBp | LN | 98.2% | 0.03% | 已修复 |
| PLN | PW | 85.7% | 0.00% | 已修复 |
| ZAr | SJ | 97.9% | 0.00% | 已修复 |
| CHF | SW | 97.9% | 0.00% | 已修复 |
| SEK | SS | 97.6% | 0.00% | 已修复 |
| DKK | DC | 98.0% | 0.23% | 已修复 |
| NOK | NO | 93.1% | 0.00% | 已修复 |

**结论**：非 EUR EMEA 行的 NULL 异常**已被 P0 回填修复**。报告 5.3 推测的"历史代码污染"正确 — 旧版本代码可能对非 EUR EMEA 行有不同处理逻辑，当前代码（`fill_processor.py:179-183`）对非 EUR 行正确保留原始拼接值 `Ticker + " " + Exchange + " Equity"`。

### 11.2 残留 60 行修复

P0 回填后仅残留 60 行 NULL（GBp 35 行 + DKK 25 行），全部来自 `source_date=20260501`（五一劳动节）。

**根因**：回填脚本 `get_affected_source_dates` 查询 `Currency='EUR'` 的 `source_date`，20260501 仅有 GBp/DKK 行（无 EUR），未被回填覆盖。

**修复**：对 `source_date=20260501` 单独执行 `process_raw_fills_for_date('20260501')`，处理后 11,906 行，残留 NULL 降至 0。

### 11.3 最终状态（2026-06-30）

| Currency | Total | NULL | NULL% |
|----------|-------|------|-------|
| EUR | 636,389 | 64,450 | 10.13%（Exchange 为空的行，合理） |
| GBp | 130,887 | 0 | 0.00% |
| ZAr | 56,839 | 0 | 0.00% |
| PLN | 56,331 | 0 | 0.00% |
| CHF | 33,406 | 0 | 0.00% |
| SEK | 29,674 | 0 | 0.00% |
| DKK | 11,089 | 0 | 0.00% |
| NOK | 10,461 | 0 | 0.00% |

---

## 12. P2 — Exchange 字段语义澄清（不做改动）

### 12.1 设计决策

`processed_fills.Exchange` 字段**始终保留原始 Bloomberg 交易所代码**（`GR`/`FP`/`IM`/`LN`/`PW`/`SJ`/`SW` 等），不含 `"EU"` 值。

- `add_equity_ticker`（`fill_processor.py:142-235`）只修改 `equ_ticker` 列，**从不改写 `Exchange`**
- `" EU Equity"` 复合代码格式**只出现在 `equ_ticker` 字段中**（如 `BMW EU Equity`）
- `Exchange` 字段语义：具体交易所代码（微观），不是区域聚合（宏观）

### 12.2 不做改动

确认此为设计决策，非 bug。如需"欧洲统一市场"标识，通过 `equ_ticker LIKE '% EU Equity'` 判断即可，无需新增字段或改写 `Exchange`。

---

## 13. P3 — Schema 增强（route_registry 方案，零迁移风险）

### 13.1 方案

不向 `processed_fills` 加列。`route_registry` 表（`execution_history.db`）已含 `ccy_ticker`/`Side` 列，按 `(OrderId, RouteId)` JOIN 查询即可。

### 13.2 现有基础设施（已就绪）

| 层级 | 状态 | 位置 |
|------|------|------|
| 表结构 | ✅ 已有 `ccy_ticker`/`Side` 列 | `columns.py:51-52` `ROUTE_REGISTRY_COLUMNS` |
| DDL | ✅ `PRIMARY KEY (OrderId, RouteId)` | `inline_ddl.py:418-422` |
| 数据填充 | ✅ 100% 填充（187,985 行） | `fill_ingestion.py:419` `upsert_route_registry` |
| 后端 JOIN | ✅ 已 LEFT JOIN route_registry | `tca_query_builder.py:183-196` SELECT `rr.equ_ticker, rr.ccy_ticker, rr.Side` |
| 后端 JOIN | ✅ 已 LEFT JOIN route_registry | `execution_history_service.py:85-97` SELECT `rr.Side, rr.equ_ticker, rr.ccy_ticker` |

### 13.3 route_registry ccy_ticker 格式

| ccy_ticker | 行数 |
|-----------|------|
| USD Curncy | 70,330 |
| USDEUR Curncy | 25,709 |
| USDJPY Curncy | 22,699 |
| USDGBP Curncy | 12,553 |
| ... | ... |

### 13.4 前端使用方式

前端无需直接查 DB。后端 API（`/api/tca/analyze` 等）已通过 JOIN route_registry 返回 `ccy_ticker`/`Side`/`equ_ticker`。如 CostView 前端需展示 Currency，只需在 `TcaOrderSummary` 类型中增加 `ccy_ticker` 字段并在组件中渲染即可，零迁移风险。
