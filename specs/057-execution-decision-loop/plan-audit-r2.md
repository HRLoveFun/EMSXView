# 审计整改 R2：A03 状态回滚 + A04 桥接/MarketView 鉴权 + A05 副作用端点权限（子规格）

> 父计划：`specs/057-execution-decision-loop/plan.md`
> 整改卡：`specs/057-execution-decision-loop/audit-remediation-2026-10-25.md` §2 A03 / A04 / A05（A06 已在 A01/076 交付）
> 审计原文：`docs/report-full-audit-2026-10-25.md` M1 / M2 / M3 / M4
> 分支：`audit-r2-security`（worktree `../EMSXView-wt-audit-r2-security`，基线 `8b4a7e2`）
> 子编号：**078**（R2 一个 PR 交付；A06 随 A01/076 已完成）
> 状态：**已确认（2026-10-26，4 个决策点全部按推荐执行）**

---

## 1. 是什么（现状）

### 1.1 A03（M1）：建议单可能永久卡在 CONFIRMING

`backend/api/services/submission_service.py` 先把 `proposal["status"]` 置为 `CONFIRMING`，随后调用注入的 `compliance_check` 与 `authorization_check`——两者在 `try` 块**之外**。以下异常会直接抛出且不回滚：
- 准入策略 JSON 解析失败（`access_policy_service.load_policy_bundle`）；
- 运营库读授权异常（`authorization_service`）。

后果：状态停在 `CONFIRMING`，之后单笔/批量确认一律 409 `already being confirmed`，只能重启进程。

### 1.2 A04（M2）：CostView 桥接与 MarketView 无鉴权

- `backend/api/routers/costview.py` 把 CostView 的 14 个端点 `include_router` 进 core :3000，未挂任何依赖 → 匿名可读全部 TCA 数据、可匿名 `POST /api/tca/recommendations/pin`（写入会出现在 ExecutionView）。
- `MarketView/config.py` 默认 `HOST=0.0.0.0`；`MarketView/main.py` 使用 `allow_origins=["*"] + allow_credentials=True`；`POST /api/marketview/handoff/execution` 匿名可写。

### 1.3 A05（M3）：副作用端点只验登录、不验角色；debug 路由常驻

| 端点 | 位置 | 现状 |
|---|---|---|
| `POST /api/tca/runner/run` | `backend/api/routers/costview.py` | 仅 `verify_token` |
| `POST /api/connection/reconnect` | `backend/api/routers/connection.py:98` | 仅 `verify_token` |
| `POST /api/broker-algorithms/refresh` | `backend/api/routers/broker.py:120` | 仅 `verify_token` |
| `POST /api/executions/handoff/post-trade` | `backend/api/routers/orders_handoff.py:94` | 仅 `verify_token` |
| `POST /api/debug/query-round-lot`（+ `GET /api/debug/round-lot-sizes`） | `backend/api/routers/debug.py` | 仅 `verify_token`；路由在 `main.py:300/314` 无条件注册 |

### 1.4 关联项：每日确认弹窗（R2 新增，A05 范围）

A01 把 `PUT /market-broker-mapping/selection` 收成 admin-only 后，`daily-broker-policy-confirm-modal.tsx` 在 `ExecutionModule` 中对所有角色渲染，trader 每日确认必 403。前端当前无角色信息（`token-service.ts` 只存 token），需补角色读取与 UI 门控；后端权限不变（UI 门控仅避免无效流程，安全边界仍在后端）。

### 1.5 A06（M4）：已在 A01 交付

`market_broker_mapping.py` 全部 `user.get("username")` → `user.get("sub") or "unknown"` 已在 A01（076）完成，证据 `test_market_broker_mapping_authz.py::test_admin_flow_audits_sub`。本 PR 只把 tasks.md A06 标为已完成并注明「随 A01/076 交付」。

---

## 2. 为什么做

1. **A03 是可用性缺陷**：一次坏 JSON/DB 抖动就把建议单永久锁死，且错误信息是 409（误导为并发冲突）。
2. **A04 是数据暴露与写入暴露**：桥接把 CostView 14 个端点搬到 core 端口后，等于在交易端口上开了匿名读写；pin 的内容会进入 ExecutionView，属跨模块写入。
3. **A05 是「登录即可产生副作用」**：viewer 能触发 ETL、重连 Bloomberg、刷新券商缓存、写 handoff；debug 端点还能阻塞会话 5 秒。
4. **每日确认弹窗**：安全收紧不应把日常交易流程变成必然失败的流程；UI 需与后端权限一致。
5. 沿用既有口径：`require_permission` 角色矩阵、fail-closed、G2（不新增阻断能力，仅补权限）、契约从 `platform_data.contracts` 导入。

---

## 3. 如何做

### 3.1 A03：状态回滚（`submission_service.py`）

- 把 `compliance_check` 与 `authorization_check` 移入 `try` 块（`route_order` 之前）；
- 增加 `route_attempted = False` 标志 + `finally` 兜底：
  ```python
  finally:
      if not route_attempted and proposal.get("status") == CONFIRMING:
          proposal["status"] = PENDING_CONFIRM
          if persist_result: await persist_result(proposal_id, status=PENDING_CONFIRM)
  ```
- 既有 except 分支（504 → NEEDS_REVIEW；其他 → PENDING_CONFIRM + re-raise；Exception → FAILED）保持，finally 只兜未被覆盖的路径；
- 语义不变：只有真正走到 `bloomberg.route_order` 才可能进入 `NEEDS_REVIEW`。

### 3.2 A04：桥接鉴权 + MarketView 收紧

**CostView 桥接（`backend/api/routers/costview.py`）**
- 新增 `_bridge_guard(request, user=Depends(verify_token))`：所有请求要求 token；非 `GET/HEAD/OPTIONS` 且无 `trade` 权限 → 403；
- `router.include_router(_tca_router, dependencies=[Depends(_bridge_guard)])`，monitoring 同样；
- 14 端点因此全部 401（无 token），pin（POST）viewer → 403。

**MarketView**
- `config.py`：`HOST` 默认 `127.0.0.1`；
- `main.py`：CORS `allow_origins` 读 `MARKETVIEW_ALLOWED_ORIGINS`（默认 `http://localhost:5173,http://localhost:3000`），`allow_credentials=False`；文档字符串同步；
- 新增 `MarketView/auth.py`：PyJWT HS256 校验 `JWT_SECRET`（env，未配置即 401），`require_token` 依赖；
- `POST /api/marketview/handoff/execution` 挂 `Depends(require_token)`；
- `requirements.txt` 增 `pyjwt==2.10.1`（与 backend 同版本）。

### 3.3 A05：副作用端点权限 + debug 条件注册 + 弹窗门控

| 端点 | 依赖 |
|---|---|
| `POST /api/tca/runner/run` | `require_permission("admin")` |
| `POST /api/connection/reconnect` | `require_permission("admin")` |
| `POST /api/broker-algorithms/refresh` | `require_permission("admin")` |
| `POST /api/executions/handoff/post-trade` | `require_permission("trade")` |
| `POST /api/debug/query-round-lot` | `require_permission("admin")`（且仅 DEBUG 注册） |

- `main.py`：`if settings.DEBUG: app.include_router(debug_router)`；
- 前端：`token-service.ts` 增 `getTokenRole()`（解码 JWT payload，不验签，仅 UI 用）；`DailyBrokerPolicyConfirmModal` 在非 admin 时直接 `return null`（仍保留后端 admin 强制）。

### 3.4 A06 收尾

仅 `tasks.md`：A06 → 已完成 / 076，备注「随 A01 交付」。

---

## 4. 范围锁

| # | 文件 | 类型 | 预估 |
|---|---|---|---|
| 1 | `backend/api/services/submission_service.py` | 改 | +45 / −20 |
| 2 | `backend/api/tests/test_submission_state_rollback.py` | 新增 | ~150 |
| 3 | `backend/api/routers/costview.py` | 改 | +30 / −5 |
| 4 | `backend/api/tests/test_costview_authz.py` | 新增 | ~130 |
| 5 | `backend/api/routers/connection.py` | 改 | +2 |
| 6 | `backend/api/routers/broker.py` | 改 | +2 |
| 7 | `backend/api/routers/orders_handoff.py` | 改 | +2 |
| 8 | `backend/api/routers/debug.py` | 改 | +2 |
| 9 | `backend/api/main.py` | 改 | +3 / −2 |
| 10 | `backend/api/tests/test_side_effect_authz.py` | 新增 | ~140 |
| 11 | `MarketView/config.py` | 改 | +3 / −1 |
| 12 | `MarketView/main.py` | 改 | +8 / −4 |
| 13 | `MarketView/auth.py` | 新增 | ~40 |
| 14 | `MarketView/routers/marketview.py` | 改 | +3 / −1 |
| 15 | `MarketView/requirements.txt` | 改 | +1 |
| 16 | `MarketView/tests/test_marketview_auth.py` | 新增 | ~90 |
| 17 | `frontend/src/shared/services/token-service.ts` | 改 | +20 |
| 18 | `ExecutionView/module/components/daily-broker-policy-confirm-modal.tsx` | 改 | +5 |
| 19 | `frontend/src/shared/services/__tests__/token-service.test.ts` | 新增/改 | ~60 |
| 20 | `specs/.../tasks.md`、`audit-remediation-2026-10-25.md` | 改 | 4 行 |

合计约 **+730 / −35**（测试约 55%）。范围外：A07 及之后、platform_data、CostView 业务逻辑、handoff 语义。

---

## 5. 验收对照

| 断言 | 证据（计划） |
|---|---|
| A03：策略 JSON/授权异常 → 状态回滚 PENDING_CONFIRM，下次可确认 | `test_submission_state_rollback.py::test_check_exception_rolls_back` |
| A03：回滚写库 + audit fail | `...::test_rollback_persists_and_audits` |
| A04：14 个 CostView 端点无 token → 401 | `test_costview_authz.py::test_bridge_requires_token`（参数化） |
| A04：viewer pin → 403 | `...::test_pin_requires_trade` |
| A04：MarketView 默认绑定 127.0.0.1 | `MarketView/tests/test_marketview_auth.py::test_default_host_loopback` |
| A04：handoff POST 无 token → 401 | `...::test_handoff_post_requires_token` |
| A05：5 端点 viewer → 403 | `test_side_effect_authz.py`（参数化） |
| A05：DEBUG 未设 → /api/debug/* 404 | `test_side_effect_authz.py::test_debug_routes_hidden_without_debug` |
| A05：非 admin 不渲染每日确认弹窗 | `token-service.test.ts` + 组件测试（如无组件测试则仅 UI 层，注明） |
| A06：审计字段 sub | 既有 `test_admin_flow_audits_sub`（A01） |
| 既有测试不减 | 后端/CostView/MarketView 分进程全量 |

---

## 6. 需确认的决策点

1. **MarketView 鉴权粒度**：仅「POST handoff 要求有效 token（401）」，不复制后端角色矩阵（角色校验只在 core）；GET 快照靠 127.0.0.1 绑定 + CORS 收紧。是否接受？
2. **每日确认门控方式**：前端解码 JWT `role`（不验签，仅控制是否渲染弹窗），不新增 `/api/auth/me` 端点。是否接受？
3. **R2 交付形态**：A03+A04+A05 一个 worktree / 一个 PR、子编号 078（整改文档「每轮一个 PR」）；A06 标记随 A01/076 完成。是否接受，还是拆 3 个 PR？
4. **debug 路由**：`DEBUG=true` 才注册（默认 404）；本地调试需显式开环境变量。是否接受？

---

## 7. 验证与门禁

分进程执行：`backend/api/tests/`、`MarketView/tests/`、`CostView/tests/`；前端 `npm run typecheck`（本地可跳过，交 CI）；四项审计 + `quality_gate --staged`；提交 `fix(audit/A03-A05): ...`，PR 标题 `fix(audit/A03+A04+A05): 状态回滚与桥接/副作用端点鉴权`。
