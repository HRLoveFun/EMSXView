# Scope A/B 对比报告: TradingSystem vs Team=18080

**调查日期**: 2026-07-02
**Team**: `18080`
**结论**: Team scope 当前 **无权限**，无法对比

---

## 调查背景

用户要求对比 TradingSystem 与 Team scope 在 4/6 和 4/7 两天的数据异同。
fetch_log 显示 4/7 曾用 Team scope 拉取 20260305（5,331 行）和 20260406（2,416 行），
行数显著少于 TradingSystem scope 的典型量级（20k-100k）。

## 关键发现

### 1. Team scope 当前返回 ERROR_PERMISSION

Bloomberg API 对 Team=18080 scope 请求返回明确错误：

```
ErrorResponse: ErrorCode=ERROR_PERMISSION, ErrorMsg=User not permissioned to view fills.
```

**当前 Bloomberg 登录用户已无 Team scope 权限**。
4/7 时 Team scope 可用（返回了 5,331 行），说明权限在 4/7 之后被撤销或 EMSS 配置变更。

### 2. 4/6-4/7 数据已过期（数据保留窗口）

| 日期 | TradingSystem | Team=18080 | 说明 |
|------|--------------|------------|------|
| 2026-04-06 | 0 rows | 0 rows | 距今 87 天，超出 EMSX History 保留窗口 |
| 2026-04-07 | 0 rows | 0 rows | 距今 86 天，超出 EMSX History 保留窗口 |
| 2026-06-29 | 114,999 rows | 0 rows (ERROR_PERMISSION) | TS 正常，Team 无权限 |
| 2026-06-30 | 45,535 rows | 0 rows (ERROR_PERMISSION) | TS 正常，Team 无权限 |

**Bloomberg EMSX History API 数据保留窗口约 85-90 天**。
4/6-4/7 的数据已无法重新拉取，只能依赖 raw_fills.db 中已有的历史数据。

### 3. `_fetch_fills_once` 存在静默吞错 bug

`DataPipeline/acquisition/bloomberg_fill_fetcher.py:196-227` 的 `_fetch_fills_once` 方法
只处理 `GET_FILLS_RESPONSE` 消息类型，**静默忽略 `ErrorResponse` 消息**：

```python
# bloomberg_fill_fetcher.py:202-218
elif et == blpapi.Event.PARTIAL_RESPONSE:
    for msg in event:
        if msg.messageType() == GET_FILLS_RESPONSE:  # 只处理 fills 响应
            try:
                fills.extend(_parse_fill_messages(msg))
            except Exception:
                pass  # 解析异常也被吞掉
        # ← ErrorResponse 消息到达后无任何处理，静默丢弃
elif et == blpapi.Event.RESPONSE:
    for msg in event:
        if msg.messageType() == GET_FILLS_RESPONSE:
            # 同上
    done = True
```

**影响**：当 Team scope 因权限不足返回 `ErrorResponse` 时，
`fetch_fills()` 返回空列表 `[]`，调用方无法区分"当天无 fills"和"权限错误"。
4/7 之后如果有人再用 Team scope 拉取，会静默得到 0 行数据并写入 fetch_log，
与"当天无交易"不可区分。

### 4. 字段 NULL 率说明

报告中 `exchange_exec_time` 和 `order_as_of_date` 在 TS 数据上显示 100% NULL 是预期行为 —
这两个是 `clean_emsx_fills()` 生成的派生字段，不存在于 Bloomberg API 原始响应中。
本对比脚本直接使用 API 原始数据，未经过清洗管道。

## 无法完成原始 A/B 对比目标

| 目标 | 状态 | 原因 |
|------|------|------|
| TradingSystem 拉取 4/6-4/7 | ❌ | 数据保留窗口过期（87 天） |
| Team 拉取 4/6-4/7 | ❌ | 同上 + Team 权限已撤销 |
| TradingSystem 拉取近期 6/29-6/30 | ✅ 114,999 / 45,535 行 | 正常 |
| Team 拉取近期 6/29-6/30 | ❌ | ERROR_PERMISSION |

## 对 scope 锁定方案的影响

此发现进一步验证了 **锁定 TradingSystem** 的正确性：

1. **Team scope 依赖 EMSS 权限**，权限可随时被撤销，导致静默 0 行数据
2. **`_fetch_fills_once` 静默吞错** 是必须修复的 bug — 无论锁定哪个 scope，
   ErrorResponse 都不应被静默忽略
3. 若选择 Team scope，权限一旦变更将导致全量数据静默丢失，且 fetch_log 无法区分

## 建议补充修复项

在 scope 锁定计划中新增：

1. **修复 `_fetch_fills_once` 错误处理**：检测 `ErrorResponse` 消息并抛出 `EMSXRequestError`
2. **fetch_log 增加 error_message 列**：记录 Bloomberg 返回的错误码和消息
3. **0 行数据告警**：拉取返回 0 行时检查是否为错误响应，避免静默写入 "fetched" 状态
