# 005-bloomberg-quota-pause 实施进度跟踪

> 每完成一项，更新状态为 ✅；进行中 ⏳；阻塞 🔴
> 每次 checkpoint 通过后更新对应行

## 总览

| 项目 | 状态 |
|------|------|
| 方案落盘 (plan.md) | ✅ 2026-08-20 |
| Phase A: 空响应完整性判断 + fetch_log 写 failed | ✅ |
| Phase B: 显式额度错误识别 (EMSXQuotaError) | ✅ |
| Phase C: 持久化暂停标记 + 各入口短路 + 恢复自愈 | ✅ |
| CP-1: 增量更新约束回归（S1/S5/S5.5/S7） | ✅ |
| CP-2: 全量 DataPipeline 回归 + 边界回归 | ✅ |
| PR 合并回 main | ⏳ |

## 实施记录（2026-08-20）

- **Phase A**：`Config.QUOTA_PAUSE_FILE`、`raw_fills.record_fetch_failed`、`fill_fetch` 空响应完整性判断（`_should_treat_empty_as_quota`）+ 写 failed + 置位。
- **Phase B**：`bloomberg_fill_fetcher` `EMSXQuotaError` + `QUOTA_ERROR_TOKENS` 白名单 + `fetch_fills` 不重试配额错误；`fill_fetch` 捕获置位。
- **Phase C**：`common/quota_pause.py` tombstone + 各入口短路（fill/BDIB/日频/FX/regime index/composite ticker）+ 恢复自愈（探测成功清除标记）+ `health_check` 只读状态。
- **测试**：`test_fill_fetch_quota_empty.py`（8）、`test_fetch_scope_audit.py`（+6）、`test_quota_pause.py`（9）。

## Checkpoint 记录

### CP-0 Phase A 单文件验证
- [x] `test_fill_fetch_quota_empty.py` 8 passed
- [x] `fetch_day` / `fetch_range_aggregated` 空分支改造完成
- [x] `record_fetch_failed` 实现 + 不推翻既有 `fetched` 语义

### CP-0 Phase B 单文件验证
- [x] `test_fetch_scope_audit.py` 14 passed（QUOTA_EXCEEDED→EMSXQuotaError / 未知→EMSXRequestError / 不重试）
- [x] `EMSXQuotaError` + 白名单 + fetch_fills 不捕获配额错误

### CP-0 Phase C 单文件验证
- [x] `test_quota_pause.py` 9 passed（读写幂等 / 各入口短路 / 恢复自愈）
- [x] tombstone 读写 + 各入口短路 + 摘要标记 + health_check 只读

### CP-1 增量约束回归
- [x] S1 `determine_fetch_range` 缺口含 `failed` 日期（恢复后重拉）— 语义不变，`failed` 不入 fetched 集合
- [x] S5 quota 期短路不写 `bdib_integrated` — 由 Phase C 短路兜底（quota 期不执行拉取）
- [x] S5.5 / S7 结果表去重兼容（quota 期不写 → 恢复后重跑）

### CP-2 全量回归
- [x] `python -m pytest DataPipeline/tests/guardrail/ -q` → **89 passed**
- [x] `python -m pytest DataPipeline/tests/processing/ DataPipeline/tests/storage/ -q` → **83 passed**
- [x] `python -m pytest backend/api/tests/boundaries/ -q` → **12 passed, 2 skipped**（AP-04/05 为既有基线）
- [x] `python -m pytest CostView/tests/test_repository_market_data.py test_tca_query_service.py -q` → **44 passed**
- [x] `python scripts/audit_cross_imports.py` → **AP-01 通过，无违规**
- [x] `daily_update.py` + `pipeline_jobs` import OK（日更链路未被破坏）
