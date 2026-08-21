# 实施计划: Bloomberg 额度爆满感知与自动暂停/恢复

**Branch**: `005-bloomberg-quota-pause` | **Date**: 2026-08-20 | **状态**: 已立项

**背景**: 数据更新模块（`CostView/scripts/daily_update.py` → `DataPipeline` 管道）在 Bloomberg API 额度爆满时存在**"误以为数据成功拉取"**的风险：额度受限时 Bloomberg 可能返回空 `GetFillsResponse` / 空 BDIB 或抛出额度类错误，当前代码会把空响应当"正常无成交日"（`fill_fetch.py:321-325`、`:434-440`），或把未知错误当普通错误重试，既不报错也不留痕，导致缺数据且额度恢复后不重拉。

**门控规范**: `docs/spec/plan-design-principles.md`（G0 数据零受损 / G1 三性齐备 / G2 全程防漂移 / G3 充分且必要）

---

## Summary

在数据管道 `DataPipeline` 域内引入**额度感知**能力，形成「正确识别 → 明确记录 → 自动暂停 → 恢复后重拉」闭环，核心目标是**绝不把额度爆满导致的空/残缺数据当作成功**。方案收敛为三个正交组件（无关键词兜底、无冷却窗口、无独立探测线程——保持最小充分）：

1. **空响应完整性判断**（防"空=成功"）：S1 `fetch_day` / `fetch_range_aggregated` 收到空 `fills` 时，不再无条件 `success=True`；依据 `fetch_log` 既有记录 + 日期合法性判断是否"预期有数据但未拉到"，预期有则写 `fetch_log.status='failed'` 并置位暂停标记。
2. **显式额度错误识别**（识别明确报错）：`BloombergFillFetcher._build_request_error` 增加**额度类错误码白名单**（只匹配明确信号，不做关键词猜测），命中即抛 `EMSXQuotaError`，由调用方置位暂停标记；未命中白名单的未知错误按既有普通错误处理（不触发暂停）。
3. **持久化暂停标记 + 各入口短路 + 恢复自愈**（状态传播）：命中额度时写 `QUOTA_PAUSE_FILE` tombstone（JSON，仿 `permanent_gap_dates.json`）；fill / BDIB / 日频 / FX / regime 各入口统一检查，置位即短路并打 `quota_paused` 标记；下一次运行开头做一次真实 fetch 探测，成功即清除标记并自然按增量缺口重拉。

**设计决策（已确认）**：
- **不**新增 DB 表 / DB 文件——只用 JSON tombstone + 复用现有 `fetch_log.status='failed'`（schema 已含该状态且 CHECK 约束允许，当前生产路径从不写入，见 `inline_ddl.py:116`、`raw_fills.py:288-319`）。
- **不**新增 `platform_data` 适配器 / 不改后端实时订单侧（`backend/api/services/bloomberg/`）——额度场景不涉及 ExecutionView 实时路径。
- 暂停标记放在管道内，对后端 `:3000` 的 `DatabaseView` / `CostView` 触发入口（`platform_data.pipeline_jobs.trigger_pipeline`）透明。

---

## 统一技术原则（G0 数据零受损 / G2 防漂移）

| # | 原则 | 落地 |
|---|------|------|
| R1 | 零 DB 结构变更 | 不加表、不加列、不加 DB 文件；复用 `fetch_log.status='failed'`（既有 CHECK 约束内），不触发任何 schema 迁移 |
| R2 | 状态可回退 | 暂停标记是独立 JSON 文件，删除即恢复；所有改动由日志可见，不做不可逆操作 |
| R3 | 幂等可重入 | tombstone 写入幂等；`fetch_log` 写 `failed` 走 INSERT OR REPLACE，重复执行无副作用 |
| R4 | 范围锁 | 只改 `DataPipeline` 域内文件 + 对应测试；不触碰 backend / CostView / platform_data 边界 |
| R5 | 最小充分 | 无关键词兜底、无冷却窗口、无独立探测线程——仅保留"识别→记录→短路→自愈"最简闭环 |

---

## 现状锚点（改造前基准，供回退对照）

| 文件 | 位置 | 现状 |
|------|------|------|
| `DataPipeline/ingestion/fill_fetch.py` | `:321-325`（fetch_day 空分支）、`:434-440`（fetch_range_aggregated 空分支） | `not fills` → `success=True` / status=`empty`，**不写 fetch_log** |
| `fill_fetch.py` | `:203-210`（determine_fetch_range fetched 集合） | 只收集 `status='fetched'` |
| `fill_fetch.py` | `:226-248`（缺口扫描） | 依据 fetched 集合判断缺口 |
| `DataPipeline/acquisition/bloomberg_fill_fetcher.py` | `:238-255`（`_build_request_error`） | 只取 ErrorCode/ErrorMsg 字符串，无语义白名单 |
| `DataPipeline/orchestration/stages_process.py` | `:222-231`（S5 need_bdib_fetch） | `latest_raw_date` 锚点推进，可能掩盖 quota 空数据 |
| `DataPipeline/orchestration/stages_process.py` | `:343`（S5 mark_date_processed） | 集成成功即打 `bdib_integrated`，quota 残缺数据会被当完成 |
| `DataPipeline/storage/repositories/raw_fills.py` | `:288-319`（add_fetch_log_record） | 只写 `'fetched'`，从不写 `'failed'` |
| `DataPipeline/config.py` | 类属性区 | 无暂停标记路径 |

---

## 分步实施（每步含 P2 三栏：理论依据 / 技术方案 / 检验方法）

### Phase A: 空响应完整性判断 + fetch_log 写 `failed`（核心，防"空=成功"）

**理论依据**: 额度爆满最常见的表现是"没报错但返回空"。`fill_fetch.py` 现状把空当正常，必须区分"真无成交日"与"预期有数据但没拉到"。判别依据：①该 `source_date` 是否曾在 `fetch_log` 中 `status='fetched'`（曾拉到→本次空=异常）；②日期是否为合理交易日（周一~周五、非未来、非永久空缺豁免）。仅当两者都指向"应重拉"时才写 `failed`，否则维持 `empty` 语义（避免把法定节假日误判为失败）。

**技术方案**:
- `DataPipeline/config.py` 新增：
  - `QUOTA_PAUSE_FILE: Path = DATA_DIR / "quota_pause.json"`
  - `QUOTA_REASON_FILL_EMPTY = "empty_fill_response"`（常量）
- `DataPipeline/storage/repositories/raw_fills.py` 新增 `record_fetch_failed(source_date, reason, detail=None)`：
  - `INSERT OR REPLACE INTO fetch_log (source_date, row_count, data_hash, file_path, status) VALUES (?, 0, ?, NULL, 'failed')`（`data_hash` 用确定性占位如 `"failed:"+reason`，保证可重入）
  - 不触发同 `source_date` 旧 `fetched` 行 `deprecated`（只标记失败，不推翻既有成功记录）
- `fill_fetch.py` 新增辅助 `_should_treat_empty_as_quota(date_compact)`：
  - 返回 True 当：`fetch_log` 中该日期无 `fetched` 记录（或该日曾出现失败/缺口）**且**日期为合法工作日（非周末、非未来、不在 `permanent_gap_dates`）
- `fetch_day`（`:321-325`）与 `fetch_range_aggregated`（`:434-440`）空分支改造：
  - `if not fills:` 后先 `_should_treat_empty_as_quota(date_compact)`；True → `record_fetch_failed` + 置位暂停标记 + 记日志 `reason=quota_paused(fill_empty)` + `result['success']=False` / summary status=`failed`；False → 维持 `empty` / success
- `determine_fetch_range`（`:203-248`）**无需改**：`fetched` 集合只认 `'fetched'`，`failed` 不会被计入，缺口扫描自动把失败日期留在缺口 → 恢复后自动重拉。✅（增量入口天然成立）

**检验方法**:
- 新增测试 `DataPipeline/tests/ingestion/test_fill_fetch_quota_empty.py`：
  - 构造 mock `raw_fill_read` 使某日期 `get_fetch_log_stats()` 无 `fetched` 记录 → `fetch_day` 返回空时 → 断言写 `fetch_log` status=`failed`、summary `success=False`
  - 该日期已有 `fetched` 记录 → 空 → 维持 `empty`（不覆写成功）
  - 周末/未来日期/永久空缺 → 空 → 维持 `empty`
- 运行：`python -m pytest DataPipeline/tests/ingestion/test_fill_fetch_quota_empty.py -q` → 全绿

---

### Phase B: 显式额度错误识别（`EMSXQuotaError`，识别明确报错）

**理论依据**: 仓库后端已有 `[MKTDATA PERMFAIL]` "不重试、回退"先例（`enrichment.py:245`），但数据管道侧 `_build_request_error` 无语义层。额度类错误必须与普通错误（timeout / 网络 / 权限）区分开：普通错误走既有指数退避重试，额度类错误**不应重试**（重试只会反复打爆额度），直接触发暂停。只匹配**明确白名单**，不做关键词猜测，避免误判（如 `limit` 撞 `LimitPrice`）。

**技术方案**:
- `DataPipeline/acquisition/bloomberg_fill_fetcher.py`：
  - 新增异常类 `class EMSXQuotaError(EMSXRequestError)`（语义细分，不新增 import 依赖）
  - 新增 `_QUOTA_ERROR_TOKENS` 白名单（**由 Bloomberg EMSX 文档/实测确认后填，不臆造**）：初始为空/最小集，如 `QUOTA_EXCEEDED`、`RATE_LIMIT`、`MKT_LIMIT`；白名单不命中时维持 `EMSXRequestError`（普通错误）
  - `_build_request_error` 中：解析 `ErrorCode`/`ErrorMsg`，若命中白名单 → `raise EMSXQuotaError(...)`；否则维持现有 `EMSXRequestError`
  - `fetch_fills` 的 `except EMSXRequestError` 重试循环**不捕获 `EMSXQuotaError`**（让配额错误直达调用方）——即 `is_timeout` 判断前加 `except EMSXQuotaError: raise`（或调整异常顺序，额度类先于普通类）
- `fill_fetch.py`：`fetch_day` / `fetch_range_aggregated` 捕获 `EMSXQuotaError` → `record_fetch_failed` + 置位暂停标记 + `result['success']=False` + 日志 `reason=quota_paused(api_error)`

**检验方法**:
- 扩展 `DataPipeline/tests/storage/test_fetch_scope_audit.py`（既有 `_build_request_error` 测试）：
  - ErrorCode=`QUOTA_EXCEEDED` → `EMSXQuotaError`
  - ErrorCode=`ERROR_PERMISSION` / 未知 → 仍 `EMSXRequestError`
  - `fetch_fills` 遇 `EMSXQuotaError` 不重试（attempt 计数=1）
- 运行：`python -m pytest DataPipeline/tests/storage/test_fetch_scope_audit.py -q` → 全绿

---

### Phase C: 持久化暂停标记 + 各入口短路 + 恢复自愈

**理论依据**: 一次额度命中应同步通知所有拉取入口（fill / BDIB / 日频 / FX / regime），避免各自重试再打爆额度。用一个 JSON tombstone（仿 `permanent_gap_dates.json` / `outdated_tickers.json` 既有模式）承载跨进程持久状态。恢复策略极简：**下一次 fetch 本身就是探测**——置位后各入口短路跳过，到下次运行开始自然做一次真实请求，成功即清除标记，缺口扫描随后自动重拉（依赖 Phase A 已写 `failed` 的日期）。

**技术方案**:
- 新增 `DataPipeline/common/quota_pause.py`（仿 `permanent_gap_dates.py` 结构，`threading.Lock` + 原子写）：
  - `load_quota_pause() -> dict | None`：读 `Config.QUOTA_PAUSE_FILE`，不存在/解析失败返回 None
  - `set_quota_pause(reason, detail=None) -> dict`：幂等写入 `{reason, detail, first_seen_at, last_seen_at, hit_count}`（首次/重复更新语义与 `permanent_gap_dates` 一致）
  - `clear_quota_pause() -> bool`：删除标记
  - `is_quota_paused() -> bool`：`load_quota_pause() is not None`
- 各入口短路（每个入口开头 `if is_quota_paused(): logger.warning("quota_paused ...") ; 返回空/跳过`）：
  - `fill_fetch.py` `fetch_day` / `fetch_range_aggregated`（若 Phase A 已置位则直接跳过，避免再试）
  - `bdib_fetcher.py` `fetch_bdib_for_ticker_date`（`_fetch_bdib_once` 前置检查）
  - `daily_metrics_calculator.py` `_fetch_daily_history`（前置检查）
  - `fx_fetcher.py` `fetch_fx_rates_for_date`（前置检查）
  - regime `data_source.py` / `market_index_loader.py`（`bdh` 调用前置检查）
- 恢复自愈：
  - 置位期间 `daily_update.py` 主流程不改——各 stage 短路后 `run_incremental` 正常结束（summary 带 `quota_paused`），不报 fatal
  - **清除点**：置位状态下，下一次 `fetch_day`/`fetch_range_aggregated` 开头先做一次真实探测（`client.connect()` + 最小 `fetch_fills` 单日）；成功 → `clear_quota_pause()` 并继续正常拉取；失败 → 保持置位、短路
- 摘要标记：`fill_fetch.py` summary / `daily_update.py` summary 增加 `quota_paused: true/false` 字段；`scripts/health_check.py` 增加 quota 状态读取（只读，不改健康判定）

**检验方法**:
- 新增 `DataPipeline/tests/guardrail/test_quota_pause.py`：
  - `set_quota_pause` / `clear_quota_pause` / `is_quota_paused` 读写与幂等
  - `is_quota_paused=True` 时 `fetch_bdib_for_ticker_date` / `_fetch_daily_history` / `fetch_fx_rates_for_date` 短路（不产生 Bloomberg 调用 mock）
  - 恢复：置位后模拟下一次真实 fetch 成功 → 标记清除
- 运行：`python -m pytest DataPipeline/tests/guardrail/test_quota_pause.py -q` → 全绿

---

## 增量更新约束适配（关键检查点）

| 增量判定 | 现状 | 改造后 | 是否满足 |
|---|---|---|---|
| S1 `determine_fetch_range` fetched 集合 | 只认 `'fetched'` | 不变；`failed` 不入集合 → quota 失败日期留在缺口 | ✅ 恢复后自动重拉 |
| S2/S3 `processing_log` stage 判定 | INSERT OR REPLACE | 不变（quota 期 S2/S3 正常处理本地已有 fills，不涉及拉取） | ✅ |
| S5 `need_bdib_fetch`（`latest_raw_date`） | 可能掩盖 quota 空数据 | **改造**：quota 置位或该日期处于 quota 期 → 跳过 `mark_date_processed` 且不推进 `latest_raw_date` 感知（Phase C 短路天然保证，S5 在 quota 期不执行拉取也就不会写 `bdib_integrated`） | ✅ 需 Phase C 短路兜底 |
| S5 `mark_date_processed` | 集成成功即打标 | quota 期短路 → 不打标 | ✅ |
| S5.5 / S7 结果表去重 | 按 `tca_route_summary` / `bdib_daily_summary` 有无该日期 | 不变（quota 期不写 → 恢复后自然重跑） | ✅ |

---

## 验收清单（G3 充分且必要 — 改动↔需求双向矩阵）

| # | 需求 | 改动 | 必要 | 充分 |
|---|------|------|:---:|:---:|
| RQ-1 | 空响应不得被当成功 | Phase A 空响应完整性判断 + `fetch_log` 写 `failed` | ✅ | ✅ |
| RQ-2 | 明确额度错误可识别 | Phase B `EMSXQuotaError` + 白名单 | ✅ | ✅ |
| RQ-3 | 额度状态跨进程持久化 | Phase C tombstone | ✅ | ✅ |
| RQ-4 | 各拉取入口统一短路 | Phase C 入口检查 | ✅ | ✅ |
| RQ-5 | 恢复后自动重拉 | Phase A `failed` + `determine_fetch_range` 缺口 + Phase C 自愈 | ✅ | ✅ |
| RQ-6 | 不影响实时订单/后端 | 范围锁 R4（不改 backend/CostView/platform_data） | ✅ | ✅ |

**验收命令**:
```bash
python -m pytest DataPipeline/tests/ingestion/test_fill_fetch_quota_empty.py -q
python -m pytest DataPipeline/tests/storage/test_fetch_scope_audit.py -q
python -m pytest DataPipeline/tests/guardrail/test_quota_pause.py -q
python -m pytest DataPipeline/tests/guardrail/ -q   # 回归护栏
python -m pytest backend/api/tests/boundaries/ -q   # 边界回归（确认零越界）
```

---

## 回退路径（G0 / G2）

- **代码回退**: 本计划全为增量改动，分支独立；回退 = 撤销 `005-bloomberg-quota-pause` 合并，无 DB 结构变更需回滚。
- **数据回退**: 若误置位暂停，删除 `QUOTA_PAUSE_FILE` 即恢复；`fetch_log` 的 `failed` 记录可通过既有 latest-wins 语义被后续 `fetched` 覆盖（`add_fetch_log_record` 不把它当成功，但 `record_fetch_failed` 不推翻既有 `fetched`——需确认交互：见 Phase A 实现，`record_fetch_failed` 不改旧 `fetched` 行）。
- **checkpoint**: Phase A → B → C 各自独立可验证（各自测试文件），可分段合并。

---

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| 白名单误判（把非额度错误当额度触发暂停） | 白名单最小化 + 只匹配明确信号；未知错误维持普通重试；错误码先经实测确认再入白名单 |
| 法定节假日被误判为"应拉未拉"写 `failed` | `_should_treat_empty_as_quota` 显式排除周末/未来/永久空缺日期 |
| 暂停期间日更被判定失败 | 各 stage 短路后 `run_incremental` 正常结束，summary 带 `quota_paused`，不 fatal |
| 与既有 `permanent_gap_dates` 语义混淆 | 独立 tombstone 文件 + 独立 reason 语义（permanent=永久豁免，quota=临时暂停） |
