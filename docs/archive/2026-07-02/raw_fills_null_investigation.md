# raw_fills 空字段调查 + fetch_log scope 切换根因分析

> 调查日期：2026-07-02
> 数据规模：raw_fills 11,057,958 行，fetch_log 85 条记录
> 前置：Phase A (PK 改造) + Phase B (NATL BK Ticker 回填) 已完成验收

---

## 一、raw_fills 等位空字段分布

### 全表 NULL/空字符串统计

| 字段 | NULL 数 | NULL 率 | 空串数 | 空串率 | 分类 |
|------|---------|---------|--------|--------|------|
| Account | 5,974,268 | 54.03% | 0 | 0% | 历史数据 |
| LastMarket | 5,974,318 | 54.03% | 10,700 | 0.10% | 历史数据 |
| LimitPrice | 6,390,388 | 57.79% | 0 | 0% | 与 LastCapacity 同簇（忽略） |
| TraderUuid | 6,390,388 | 57.79% | 0 | 0% | 与 LastCapacity 同簇（忽略） |
| LocalExchangeSymbol | 6,390,388 | 57.79% | 233,679 | 2.11% | 与 LastCapacity 同簇（忽略） |
| StopPrice | 8,140,998 | 73.62% | 0 | 0% | 业务合理 |
| exchange_exec_time | 4,610,231 | 41.69% | 57,339 | 0.52% | **代码 bug** |
| Liquidity | 834,101 | 7.54% | 586,814 | 5.31% | 上游数据特点 |
| StrategyType | 8,257 | 0.07% | 190 | 0.00% | 极少量 |
| order_as_of_date | 240 | 0.00% | 0 | 0% | 极少量 |
| ingested_at | 11,000,619 | 99.48% | 0 | 0% | schema 升级 |
| SecurityName | 0 | 0% | 0 | 0% | OK |
| Currency | 0 | 0% | 0 | 0% | OK |
| Broker | 0 | 0% | 0 | 0% | OK |
| Side | 0 | 0% | 0 | 0% | OK |
| Amount | 0 | 0% | 0 | 0% | OK |
| Type | 0 | 0% | 0 | 0% | OK |
| StrategyType | 0 | 0% | 0 | 0% | OK |
| TraderName | 0 | 0% | 0 | 0% | OK |
| RouteShares | 0 | 0% | 0 | 0% | OK |
| ExecType | 0 | 0% | 0 | 0% | OK |
| DateTimeOfFill | 0 | 0% | 0 | 0% | OK |
| FillPrice | 0 | 0% | 0 | 0% | OK |
| FillShares | 0 | 0% | 0 | 0% | OK |
| fetched_at | 0 | 0% | 0 | 0% | OK |

### 需要修复的问题

#### 问题 1：exchange_exec_time NULL（代码 bug）★

- **影响**：4,610,231 行 (41.69%) 的 `exchange_exec_time` 为 NULL
- **根因**：`upsert_raw_api_data`（`raw_fills.py` L207）调用了 `derive_exchange_times` 计算
  了 `exchange_exec_time`，但写入 cols 列表遗漏了该字段：

  ```python
  # 当前代码（有 bug）
  cols = list(EMSX_FILL_COLUMNS) + ["order_as_of_date", "source_date", "fetched_at"]
  # exchange_exec_time 在 DERIVED_COLUMNS 中，不在 EMSX_FILL_COLUMNS 中
  # derive_exchange_times 已计算 df["exchange_exec_time"]，但未被写入 DB
  ```

- **交叉验证**：
  - `exchange_exec_time` 有值的 6,390,388 行与 `ingested_at` 有值的 57,339 行 **零重叠**
  - 说明有值的数据来自 Excel 导入路径（`upsert_fills`），NULL 的来自 API 路径（`upsert_raw_api_data`）
- **修复**：cols 添加 `"exchange_exec_time"` + 回填历史数据

#### 问题 2：Account / LastMarket NULL（历史数据，无法回填）

- **影响**：5,974,268 行 (54.03%)，涉及 56 个日期 (20250919 ~ 20260220)
- **根因**：这 56 个日期的数据通过 Excel 导入（fetch_log 建立之前），Excel 源文件不包含
  Account 和 LastMarket 字段
- **验证**：
  - fetch_log 记录从 20260304 开始（84 个日期）
  - raw_fills 中有 63 个日期 (20250919 ~ 20260303) 在 fetch_log 之前
  - 20250919 Account 100% NULL，20260303 Account 0% NULL → 2026-02 期间 Excel 格式变更
- **修复**：无法回填（Excel 源文件已无此数据），建议下游对 Account NULL 做降级处理

### 不需要修复的字段

| 字段 | 原因 |
|------|------|
| StopPrice (73.6%) | 非止损单没有止损价，业务合理 |
| LimitPrice/TraderUuid/LocalExchangeSymbol (57.8%) | 与 LastCapacity 同簇，用户已指示忽略 |
| ingested_at (99.5%) | schema 升级前的旧数据无此字段，不影响业务 |
| Liquidity (7.5% NULL + 5.3% 空串) | Bloomberg API 部分返回，上游数据特点 |
| StrategyType (0.075%) | 极少量数据质量问题，影响可忽略 |
| order_as_of_date (0.002%) | 极少量 DateTimeOfFill 解析失败，240 行 |

---

## 二、fetch_log 66144→5331 行 scope 切换根因

### 现象

20260305 在 fetch_log 中有两条记录（唯一一个有多条记录的 source_date）：

| id | fetch_timestamp | row_count | data_hash | status |
|----|-----------------|-----------|-----------|--------|
| 2 | 2026-04-06T17:04:30 | 66,144 | 4a346408... | deprecated |
| 46 | 2026-04-07T16:47:09 | 5,331 | 1866be9b... | fetched |

### 根因

**scope 切换**：第一次用 TradingSystem scope（login-based，全系统），第二次用 Team scope（指定团队）。

- `TradingSystem` scope: 拉取当前登录用户整个 TradingSystem 的所有 fills → 66,144 行
- `Team` scope: 仅拉取指定 team 的 fills → 5,331 行
- 行数差异 12.4x 符合全系统 vs 单团队的比例

代码依据（`bloomberg_fill_fetcher.py` L185-191）：
```python
scope = request.getElement("Scope")
if team:
    scope.setChoice("Team")
    scope.setElement("Team", team)
else:
    scope.setChoice("TradingSystem")
    scope.setElement("TradingSystem", True)
```

### 时间线还原

1. **2026-04-06 17:04**：全量回填，用 TradingSystem scope 拉取 20260304~20260331（id=1~20）
2. **2026-04-07 16:47**：发现 20260305 数据异常（行数过多），用 Team scope 重新拉取（id=46）
3. **之后**：日常增量拉取均使用 Team scope

### 数据覆盖分析

raw_fills 中 20260305 实际 62,434 行（≠ 66,144 也 ≠ 5,331）：

- 5,331 行在旧 PK (OrderId, RouteId, FillId) 下覆盖了 66,144 行中的对应行
- 66,144 - 62,434 = 3,710 行被后续日期的同 OrderId 覆盖（跨日覆盖问题）
- 跨日覆盖问题已通过 Phase A PK 改造修复（PK 加入 source_date 维度）

### 结论

- scope 切换是一次性配置变更，不是 bug
- **但 fetch_log 表未记录 scope/team 信息**，无法审计哪次拉取用了什么 scope

### 修复建议

**fetch_log 审计增强**：添加 `scope` 列记录每次拉取的 scope：

```sql
ALTER TABLE fetch_log ADD COLUMN scope TEXT DEFAULT '';
-- 值: 'TradingSystem' 或 'Team:<team_name>'
```

同步修改 `add_fetch_log_record` 方法签名，传入 scope 参数。

---

## 三、修复优先级

| 优先级 | 问题 | 修复方式 | 影响范围 |
|--------|------|----------|----------|
| P1 | exchange_exec_time NULL（代码 bug） | 修改 `upsert_raw_api_data` cols + 回填脚本 | 4.6M 行 |
| P2 | fetch_log 审计增强（scope 列） | DDL migration + 代码修改 | fetch_log 表 |
| — | Account/LastMarket NULL（历史数据） | 无法回填，下游降级处理 | 5.9M 行（仅历史日期） |
