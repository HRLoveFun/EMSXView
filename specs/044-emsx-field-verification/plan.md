# 044 — 5.4 实盘字段验证（EMSX_REQUEST_SEQ / lastShares）

> 父计划：`specs/029-trading-reliability-hardening/plan.md`（剩余项 5.4）
> 分支：`044-emsx-field-verification`
> 前提（用户已确认 2026-10-08）：Bloomberg 实盘/仿真环境可用
> 安全边界：本任务**不新增真实下单路径**——验证依赖人工发起的路由与成交事件

## 1. 目的

S7/S9 的两个实现依赖真实报文行为验证：
1. RouteEx 请求是否接受 `EMSX_REQUEST_SEQ` 字段（若终端拒绝未知字段需回退）；
2. 路由订阅消息中 `lastShares` 的实际形态与触发时机（成交回填链路依赖）。

## 2. 验证观测增强（本 PR 代码部分）

- `request_handler.route_order`：路由成功日志携带 `emsx_request_seq`；
- `subscriptions._notify_fill_callbacks`：INFO 级记录每次路由消息的
  `lastShares` 实际取值与已注册回调数（`Fill event observed: route=... lastShares=... fill_callbacks=...`）。

既有可观测点（无需新增）：
- RouteEx 被终端拒绝时：`ERROR_MESSAGE` → HTTPException 400 透出，审计记 `fail`；
- 审计事件落库（`ENABLE_DB_PERSISTENCE=true` 时 result 字段真实反映 ok/fail/unknown）。

## 3. 验证步骤清单（实盘时段人工执行）

> 环境：后端连实盘/仿真，`ENABLE_AUDIT_LOG=true`；建议 `ENABLE_DB_PERSISTENCE=true`
> 以便核对审计落库。`EXECUTION_DRIVER_ENABLED` 保持 **false**。

| # | 步骤 | 操作 | 观察点 |
|---|---|---|---|
| V1 | 启动后端 | 连接终端，确认订阅 INIT_PAINT 完成 | 日志 `INIT_PAINT complete` |
| V2 | 发起一笔小额路由 | 前端或 API 对一笔 WORKING 订单 route（最小可行数量） | 成功日志含 `emsx_request_seq: N` |
| V3 | **判定 A（SEQ 字段接受性）** | 检查 V2 结果 | **通过**：路由创建成功（有 route_id）→ 字段被接受；**拒绝**：HTTP 400 且 `ERROR_MESSAGE` 提示字段相关错误 → 需加回退开关 |
| V4 | 等待/观察该路由的成交事件 | 人工在终端执行成交，或观察订阅流 | 日志 `Fill event observed: route=... lastShares=...` |
| V5 | **判定 B（lastShares 形态）** | 检查 V4 日志 | **有值**：lastShares 非零（部分/全部成交事件各一条）→ 成交回填链路可依赖该字段；**恒 0**：字段名或事件时机与假设不符 → 调整 `_notify_fill_callbacks` 取值 |
| V6 | 审计核对 | 查询审计事件（DB 或日志） | V2 对应事件 result=ok；如验证期间人为制造一次失败（可选），result=fail |

## 4. 结果处置

### ✅ 验证已完成（2026-10-08 实盘实测，判定 A/B 均通过）

**判定 A：通过** —— 真实路由 `5018309.1`（CARLB DC Equity SELL 119 @ MKT，TGTCLOSE/EQ-SEB DMA）创建成功：终端接受携带 `EMSX_REQUEST_SEQ` 字段的 RouteEx 请求，无需回退开关。

**判定 B：通过 + 语义修正（#129）** —— 路由 `5018201.1`（GIVN SW Equity BUY 55，PARTFILL）实测：
- `lastShares=1`（有值，字段存在且随成交事件更新）→ 字段前提成立；
- **实测暴露语义问题**：`lastShares` 是**最后一笔**成交量（增量），`dayFill=9` 才是累计——回填链路已改用 dayFill（#129，4 用例回归锁），与 `record_fill` 的 FILLED 判定语义对齐。

**顺带实测修复（#128）**：`GET /api/orders/status` 因 facade 缺 `_init_paint_done`/`_subscription_failed` 代理实测 500——已补代理 + 2 用例。

| 判定 | 实测结果 | 处置 |
|---|---|---|
| A 通过 | RouteEx 接受字段 | 无需改动（实测确认） |
| A 拒绝 | 未发生 | — |
| B 有值 | lastShares 存在（=1） | S9 成交回填字段前提成立；语义修正 #129 |
| B 恒 0 | 未发生 | — |

### 5.4 状态：**闭环**。5.5（整日演练）前置依赖解除。

## 5. 范围锁

- `backend/api/services/bloomberg/request_handler.py`（一行日志）
- `backend/api/services/bloomberg/subscriptions.py`（INFO 日志）
- `specs/044-emsx-field-verification/plan.md`（本文件，含验证手册）

## 6. 验收（P4）

| 需求 | 覆盖 | 结果 |
|---|---|---|
| 验证观测可判定 | V2/V4 日志字段 | 实盘执行后回填 |
| 既有测试不回归 | 全量 pytest | CI |
| 实盘执行边界 | 手册明示人工操作 + 驱动循环保持关闭 | 评审 |
