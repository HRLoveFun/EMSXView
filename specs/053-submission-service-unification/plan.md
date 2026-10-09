# 053 — 提交服务统一与状态真相收敛（第二份审计修复战役）

> 依据：第二份审计报告（基于 `147fcbf`，2026-10-08）——五个阻断项 + 两个接线缺口全部核实成立。
> 形态：伞计划，四个子任务（S14–S17），各自独立分支/PR。
> 关联：`specs/048`（第一轮演练）、`docs/report-029-reliability-hardening-delivery.md`（第一轮交付）。

## 1. 审计发现与根因映射

| # | 审计发现 | 根因 | 子任务 |
|---|---|---|---|
| 1 | 504 超时后建议回退 PENDING_CONFIRM 允许盲目重发 | unknown 语义只进了审计，未进状态机 | S14 |
| 2a | batch-confirm 未接入授权校验（1,500/1,000 实测放行） | S13 只挂单笔入口 | S14 |
| 2b | batch-confirm 无建议锁/持久化回写 + 流 bytes 序列化 TypeError | batch 未继承单笔保护 | S14 |
| 3 | 授权不含手工路由累计量（600+600 两次放行） | 占用仅算父子单承诺量 | S17 |
| 4 | route_plan 只写内存 → 建议 FK 失败回退内存 → 「持久化」名不副实 | S8 只持久化了建议侧 | S15 |
| 5 | 配置正式用户后 DEMO_USERS 仍可认证 | fallback 无生产开关 | S15 |
| 6 | restore_request_seq 无生产调用路径 | S7 只实现未接线 | S16 |
| 7 | 重同步回调未注册 | S7 注入点留空 | S16 |

更正：审计发现 3 中「GET /api/authorizations 500 缺 await」已被 #133 修复（审计基于 147fcbf，早于该修复）。

## 2. 子任务

### S14（053）统一提交服务 + NEEDS_REVIEW 冻结
- **统一提交服务** `services/submission_service.py`：compliance → 授权预检 → 建议锁（CONFIRMING）→ 提交 → 状态迁移 + 持久化回写，单笔与批量共用。
- **NEEDS_REVIEW 冻结**：提交结果未知（504/响应丢失）→ 建议 `NEEDS_REVIEW`（不回退 PENDING_CONFIRM）；重确认/重提被状态机拒绝；新增 `POST /api/sub-order-proposals/{id}/resolve`（人工核对后解除，trade 权限，审计留痕）。
- **batch-confirm 继承全部保护**：授权预检（逐 item，exceeded 整体拒绝）、CONFIRMING 锁、持久化回写、bytes 序列化修复（NDJSON 兼容 str/bytes）。
- 状态机：PENDING_CONFIRM → CONFIRMING → SUBMITTED / NEEDS_REVIEW / REJECTED；NEEDS_REVIEW 仅可经 resolve → SUBMITTED（核对确认已成交）或 → REJECTED/CANCELLED。

### S15（054）route_plan 持久化 + 演示账号生产禁用
- route plan CRUD 写 DB（与 S8 同模式），建议 FK 闭环；启动恢复 route plans。
- `authenticate_user`：`EMSXVIEW_USERS` 配置**非空且解析成功**时不再回落 DEMO_USERS（配置即权威）；空配置回落 + WARNING（现状保留，开发友好）。

### S16（055）序号持久化恢复 + 重同步接线
- 请求序号持久化：每次交易请求后写 `subscription_watermarks`（已有表）；启动时 `restore_request_seq`。
- 重同步回调接线：facade 在连接建立后注册（重发 REQUEST_ORDERS/ROUTES 快照）；跳号触发真实重同步。

### S17（056）授权占用语义增强（待口径确认）
- 占用 = 父子单承诺量 + **手工路由未成交量**（routes 按 symbol+side 聚合）。
- ⏸ 待确认口径：手工路由占用是否含已完成（COMPLETED）的历史量、按日重置还是滚动累计。

## 3. 执行顺序与验收底线

S14 → S15 → S16 → S17（S14 最紧急：504 重发 + batch 无保护直接阻断实盘）。

验收底线（审计原文）：**交易员在任何时刻能明确回答——PM 还授权多少、已送出多少、哪些请求结果未知、重启后这些数字是否仍然一致。**

每子任务：真实 SQLite DB 测试（非内存替身）覆盖外键/写入失败/响应丢失/并发/重启（审计建议第 2 条）。
