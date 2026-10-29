# 037 — S7：结果未知语义 + EMSX_REQUEST_SEQ 防重 + 跳号重同步（离线可测部分）

> 父计划：`specs/029-trading-reliability-hardening/plan.md`（第二波 · 风控与状态真相 · S7 / B7）
> 分支：`037-unknown-state-request-dedup`（worktree `../EMSXView-wt-037-unknown-state-request-dedup`）

## 1. 问题（报告三点）

1. 交易请求超时可能意味着券商已收到订单，只是响应未返回——但超时被一律归为失败。
2. 代码未使用 `EMSX_REQUEST_SEQ` 防止故障期间重复请求（Bloomberg 文档明确提供该字段）。
3. `API_SEQ_NUM` 跳号仅记录 warning，无重同步与交易限制动作——缓存可能与终端失配而无人察觉。

## 2. 方案（P2 三栏）

- **理论依据**：请求发出与响应返回之间存在「结果未知」区间；防重需要跨重启单调的请求序号；跳号意味着事件流可能漏事件，必须有后续动作而非仅日志。
- **技术方案**：
  - **请求序号**：`EMSXRequestHandler._next_request_seq()` 单调递增；`RouteEx` 请求携带 `EMSX_REQUEST_SEQ`；`restore_request_seq(last)` 重启恢复（只升不降，防序号回退重放）。
  - **结果未知结构化**：超时 504 的 detail 改为 `{message, outcome: "unknown", correlation}`——上层审计（S6）按 504 归入 unknown 的判断得到结构化支撑。
  - **跳号重同步**：纯函数 `detect_seq_gap`；`_track_api_seq_num` 跳号从 warning 升级 ERROR 并调 `_schedule_resync`；`register_resync_callback` 注入点——真实重同步（重发 REQUEST_ORDERS/ROUTES 快照）需实盘会话，由 facade 连接建立后注册；无回调时 ERROR 提示手动刷新。
- **检验方法**：`test_request_dedup_resync.py` 七用例：序号单调；恢复只升不降；RouteEx 携带序号且递增；504 结构化；gap 边界四例；跳号触发回调；无回调 ERROR。

## 3. 范围锁

- `backend/api/services/bloomberg/request_handler.py`（序号 + 504 结构化）
- `backend/api/services/bloomberg/subscriptions.py`（detect_seq_gap + resync 注入点）
- `backend/api/tests/test_request_dedup_resync.py`（新增）
- `backend/api/tests/test_bloomberg_adapter_routing.py`（既有跳号测试同步升级为 ERROR 断言——预期行为变更）
- `specs/037-unknown-state-request-dedup/plan.md`（本文件）

## 4. 实盘验证边界（与用户确认）

以下两点属**离线未验证**部分，实盘验证另行安排：
- `EMSX_REQUEST_SEQ` 字段在真实 RouteEx 请求中的接受性（若终端拒绝未知字段需回退）。
- 真实重同步回调的注册与执行（`register_resync_callback` 注入点已就绪，等待实盘接线）。

## 5. 验收（P4）

| 需求 | 覆盖 | 结果 |
|---|---|---|
| 重复请求可被终端识别防重 | 序号单调 + RouteEx 携带 + 重启恢复 | CI（离线） |
| 结果未知 ≠ 失败 | 504 结构化 outcome=unknown | CI |
| 跳号有后续动作 | ERROR + resync 回调触发 | CI |
| 既有测试不回归 | 252 → 259 passed | CI |
