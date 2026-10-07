# 029 — 交易可靠性加固（Trading Reliability Hardening）

> 特性（伞）：`029-trading-reliability-hardening`
> 范围依据：外部审计报告《EMSXView 实用化评估》（基于 `ed4b586`，2026-09-23），五处问题在当前 `main` 上全部复现成立。
> 落地形态：**伞计划**——本文件为总纲，含共性决策、阶段划分与子任务清单；各子任务各自开 `specs/<子编号>/` + 独立分支 + 独立 PR，遵循 git-workflow §2「一任务一分支一目录」与 §4「单次 PR ≤ 200 行 diff」。
> 关联规范：`docs/spec/plan-design-principles.md`（G0–G3）、`docs/spec/refactoring-methodology.md`（行为保全优先）、`docs/spec/anti-patterns.md`、`docs/spec/git-workflow.md`。

---

## 1. 问题

报告定位：项目已具备有价值的买方交易员工作台基础，但 `main` 不适合视为可独立承担资金风险的执行系统。最大距离在**执行可靠性、风控一致性、交易流程闭环**。已离线复现的五处阻断项（代码位置均已在当前 `main` 核实）：

| # | 问题 | 源码位置 | 根因 |
|---|---|---|---|
| B1 | 路由引擎接口与实现不匹配，`apply_route_engine` 链路整体不可用 | `backend/api/routers/route_plans.py:43-56`（`_engine_repo` 五个方法为普通 staticmethod/lambda）+ `backend/api/services/route_engine.py:346/352/368/388`（全部 `await`） | 引擎对非协程返回值执行 `await` → `TypeError` → 被 `route_plans.py:352-355` `except` 吞成通用错误 |
| B2 | 风控入口不统一，建议确认入口绕过 notional 上限 | `backend/api/routers/route_plans.py:382-416`（`confirm_proposal` 直接 `bloomberg.route_order`，未调 `compliance_service`）；对照 `backend/api/routers/orders_crud.py:118`、`routes.py:69`、`services/batch_route_service.py:274/365` 均过 `check_route/check_modify` | 建议（proposal）确认路径未接入既有 pre-trade 合规 |
| B3 | 同一建议可重复提交（重复委托风险） | `route_plans.py:394`（状态检查）与 `:411`（状态更新）之间存在 `await route_order`（`:407`） | check-then-act 非原子，并发确认均可通过检查并各自提交 |
| B4 | 订阅线程到持久化/WebSocket 推送断链 | `backend/api/services/bloomberg/subscriptions.py:800-838`（`_schedule_persist_order/_route` 用 `asyncio.get_event_loop()`，blpapi SDK 线程中抛 `RuntimeError` 后 `:803-804` 静默 return） | 取不到主 loop 即静默跳过 DB 写与广播，无日志，前端轮询掩盖推送失效 |
| B5 | 父子单调度仍用模拟仓库，查询返回 0 切片但状态 RUNNING | `backend/api/routers/orders_execution.py:47-92`（`_MockParentChildRepo` 切片存实例本地 `self._slices`）+ `:164`（启动建实例写 4 切片）+ `:218`（查询新建实例 → 0 切片） | 每次请求新建 repo 实例，切片列表实例局部；调度器无真实存储与驱动循环 |

引申项（报告同源，纳入本计划但分波次）：

| # | 问题 | 源码位置 |
|---|---|---|
| B6 | 审计先写后知，`result` 固定 `ok` | `backend/api/deps.py:62-75`（操作前记录、`:72` `result="ok"` 硬编码） |
| B7 | 超时语义缺失「结果未知」态、`API_SEQ_NUM` 跳号仅 warning、未用 `EMSX_REQUEST_SEQ` 防重 | `backend/api/services/bloomberg/request_handler.py`（超时归失败）；`subscriptions.py:851-862`（跳号仅 warning） |
| B8 | 风控未服务化、授权用 `DEMO_USERS` | `backend/api/auth.py:46`（`DEMO_USERS` 硬编码，仅 trader/admin 两级）；compliance 仅覆盖 notional 与整手 |
| B9 | 路由计划/建议/父子单全部内存 dict，重启即失 | `route_plans.py:30-34`、`orders_execution.py:37-38` |

---

## 2. 决策

### 2.1 不做「大爆炸」——伞下分波次、子任务独立上链

报告「先修实盘阻断项」阶段含五处修复 + 风控统一 + 请求去重/未知状态/持久化，量级超出单 PR。按 refactoring-methodology「渐进式演进」与 git-workflow §4「小步提交」，拆为三波，每波含若干独立子任务（独立 `specs/<子编号>/` + 分支 + PR）：

| 波次 | 目标 | 子任务 | 验收门 |
|---|---|---|---|
| **第一波·阻断项修复** | 五处问题逐一闭环，行为可观测 | S1–S5（B1–B5） | 每子任务既有测试不回归 + 新增定向测试覆盖修复点 |
| **第二波·风控与状态真相** | 风控统一服务化、操作幂等键、未知态、审计结果真实化、持久化打通 | S6–S9（B2 深化/B3 深化/B6/B7/B9） | 任何入口过同一规则；重启可恢复；审计能区分 ok/fail/unknown |
| **第三波·授权与流程闭环** | `DEMO_USERS` 替换、账户/台席/动作级授权、PM 授权量与剩余量跟踪 | S10–S11（B8 + 报告「买方工作流延伸」） | 多人场景下权限可粒度控制；订单/路由/成交/剩余量一致可对账 |

本计划**承诺交付第一波**（S1–S5），并登记第二/三波为后续 specs。第二/三波依赖第一波使链路可用、可观测后再开工。

### 2.2 行为保全优先（refactoring-methodology 阶段 2）

第一波每个子任务开工前先补「特征测试」锁死当前可观测行为，再改结构。`backend/api/tests/` 已有 91 项基线全绿，子任务须保持全绿并新增定向用例。

### 2.3 范围锁（G2 P3）

每个子任务只改其声明文件集；`git diff --stat` 超出声明范围即拒绝提交。共性改动（如 `compliance_service` 新增导出）归到对应子任务内，不顺手改无关字段。

### 2.4 不引入外部依赖

幂等键用仓库内既有序列与状态机；风控服务化复用 `compliance_service`；持久化复用 `RepositoryProvider`。不引入 redis / sqlalchemy-migrations / 新 ORM。

---

## 3. 落地（第一波 S1–S5，每项三性齐备）

> 子任务编号待执行时分配（接续归档 028/028b，下一可用编号 029 本伞占用，子任务自 030 起）。下表「分支」列为执行时建议名，须与 `specs/<子编号>/` 目录名一致。

### S1 · 修复 `_engine_repo` await 不匹配（B1）

- **分支**：`030-fix-engine-await-mismatch`
- **理论依据**：`RouteEngine` 把 repo 方法当协程 `await`，但 `_engine_repo` 用 `staticmethod(lambda)` 提供普通函数；`await <dict>` 抛 `TypeError`，整条计划→建议链路失败。
- **技术方案**：二选一（取更小者）——
  - 方案 A（推荐，改 repo 侧）：把 `_engine_repo` 五个方法改为 `async def`（或返回 `asyncio.sleep(0)` 的协程），保持 `route_engine.py` 不动；`route_plans.py:43-56` 重写为带 `async def` 方法的类实例。
  - 方案 B（改引擎侧）：去掉 `route_engine.py` 中对 repo 方法的 `await`，改为同步调用；但 `RouteEngine` 类文档注释承诺 repo 为协程接口，改引擎会影响未来真实异步 repo 适配。
  - 选 A：改动局部、不破坏引擎契约。
- **检验方法**：新增 `tests/test_route_engine_apply.py`：构造 plan + AUTO 订单 → `apply_route_engine` 返回非空 proposals、状态 `PENDING_CONFIRM`；既有 `test_route_plans_endpoints.py` 全绿；`route_engine.py` 不改一行。
- **文件集**：`backend/api/routers/route_plans.py`、`backend/api/tests/test_route_engine_apply.py`（新增）。

### S2 · `confirm_proposal` 接入风控（B2）

- **分支**：`031-confirm-proposal-compliance`
- **理论依据**：`confirm_proposal` 是事实上的下单入口，却绕过 `compliance_service.check_route`，导致 notional 上限（`config.USD_NOTIONAL_MAX=49000000`）在建议路径失效。
- **技术方案**：在 `route_plans.py:396-407` 构造 `route_req` 后、调用 `bloomberg.route_order` 前，调用 `compliance_service.check_route(...)`（与 `orders_crud.py:118` 同签名）；硬阻断违例（`NOTIONAL_TOO_LARGE`/`NOTIONAL_UNKNOWN`）返回 `ApiResponse(success=False, error=..., data={"violations": [...]})`，软告警（`NOTIONAL_TOO_SMALL`）放行但记入 audit。复用 `batch_route_service._evaluate_route_item` 的 fx/last price 注入逻辑以保证与批量入口同口径。
- **检验方法**：新增 `tests/test_confirm_proposal_compliance.py`：① 5,000 万美元委托建议确认 → 被拦（`NOTIONAL_TOO_LARGE`）；② 4,900 万通过；③ 软告警放行且 audit 含 violation。与 `orders_crud` 同输入对照结果一致。
- **文件集**：`backend/api/routers/route_plans.py`、`backend/api/tests/test_confirm_proposal_compliance.py`（新增）。依赖 S1（建议链路需先可用）。

### S3 · `confirm_proposal` 并发幂等（B3，第一波做短期、第二波做持久化）

- **分支**：`032-confirm-proposal-idempotent`
- **理论依据**：check-then-act 跨 `await`，并发确认同一 proposal 双双通过。第一波用「状态中间态 + 锁」做进程内原子；持久化幂等键（重启仍可识别）列入第二波 S8。
- **技术方案**：
  - 引入 `CONFIRMING` 中间态：`proposal["status"]` 由 `PENDING_CONFIRM` → `CONFIRMING` 必须原子；用 `asyncio.Lock` per proposal_id（`_confirm_locks: dict[int, asyncio.Lock]`）保护整段 check→submit→update。
  - `CONFIRMING` 态在 `confirm_proposal` 重入时返回 409「已在确认中」；`route_order` 失败回退为 `PENDING_CONFIRM`（可重试），成功转 `SUBMITTED`。
  - `list_sub_order_proposals` 把 `CONFIRMING` 也列出（供前端展示「提交中」）。
- **检验方法**：新增 `tests/test_confirm_proposal_concurrency.py`：用 `asyncio.gather` 并发两次确认同一 proposal → 恰好一次 `route_order` 被调用、一次 200 一次 409；`route_order` 抛异常后状态回退 `PENDING_CONFIRM` 可重试。
- **文件集**：`backend/api/routers/route_plans.py`、`backend/api/tests/test_confirm_proposal_concurrency.py`（新增）。依赖 S2（风控在前更安全）。

### S4 · 订阅线程持久化/推送修复（B4）

- **分支**：`034-subscription-persist-loop-fix`
- **理论依据**：blpapi 回调线程无 event loop，`asyncio.get_event_loop()` 抛 `RuntimeError` 被 `:803-804` 静默吞，DB 写与广播整体跳过。
- **技术方案**：
  - 在 `BloombergEMSXService` 启动时（`main.py` `init_services`）捕获主 loop 引用存为 `self._main_loop`，`_schedule_persist_order/_route` 改用 `asyncio.run_coroutine_threadsafe(coro, self._main_loop)`，不再每调一次取 loop。
  - 取不到 `self._main_loop`（未初始化）时 `logger.error(...)` 并返回，不得静默。
  - `run_coroutine_threadsafe` 返回的 future 用 `add_done_callback` 记录异常（避免协程失败仍静默）。
  - 同时审计 `_schedule_persist_*` 调用计数（`metrics` 或 logger 计数器），便于与订阅事件数对比发现丢事件。
- **检验方法**：新增 `tests/test_subscription_persist_thread.py`：用 `threading.Thread` 模拟非主线程调用 `_schedule_persist_order` → 断言 `persist_order` 被调用、`broadcast_order` 被调用；`_main_loop=None` 时断言 `logger.error` 被触发。既有订阅测试全绿。
- **文件集**：`backend/api/services/bloomberg/subscriptions.py`、`backend/api/services/bloomberg/__init__.py` 或 `main.py`（注入 loop）、`backend/api/tests/test_subscription_persist_thread.py`（新增）。

### S5 · 父子单调度查询 bug + 模拟仓库显式标记（B5，第一波修 bug、第二波接真实存储）

- **分支**：`035-execution-slice-query-fix`
- **理论依据**：`_MockParentChildRepo._slices` 实例局部，查询时新建实例 → 0 切片。第一波把切片存储提升到模块级（与 `_parent_store` 同级）修复查询 bug，并显式标记模拟仓库不可用于生产；真实持久化与驱动循环列入第二波 S9。
- **技术方案**：
  - 新增模块级 `_slices_store: dict[int, list[object]]`（key=parent_id），`_MockParentChildRepo` 的 `create_slices_bulk/list_slices_for_parent/update_slice_status` 改读写 `_slices_store[parent_id]`，所有实例共享。
  - 类 docstring 加「MOCK — 生产环境须由 `RepositoryProvider` 提供；`ENABLE_DB_PERSISTENCE=true` 时启动检查拒绝使用本类」；`create_parent_execution` 在 `settings.ENABLE_DB_PERSISTENCE=true` 时 `logger.warning`（第一波仅告警，不阻断，避免破坏既有部署）。
  - `get_parent_execution` 复用 `_slices_store` 返回真实切片数。
- **检验方法**：新增 `tests/test_execution_slice_query.py`：create 4 切片 → get 返回 4 切片、状态一致；list 返回该 parent。既有 `test_orders_execution.py` 全绿。
- **文件集**：`backend/api/routers/orders_execution.py`、`backend/api/tests/test_execution_slice_query.py`（新增）。

---

## 4. 依赖与执行顺序

```
S1 (B1 引擎) ──┐
               ├─► S2 (B2 风控接入) ─► S3 (B3 幂等)
S4 (B4 订阅)  ──┤   （独立，可与 S1 并行）
S5 (B5 切片)  ──┘   （独立，可与 S1 并行）
```

- S1 最先：修复后 S2/S3 才有可用链路可测。
- S4、S5 与 S1 无文件重叠，可并行 worktree（git-workflow §6 重叠评估）。
- S2 → S3 串行（S3 在 S2 风控之后更安全）。
- 每个子任务完成后：`wt-sync` → 跑 `pytest backend/api/tests/` + 前端 `npm test` → push → PR（squash）→ CI 全绿后合并（按既有纪律，boundary-protection 工作流全绿即合并，无需二次确认）。

---

## 5. 验收（G3 P4 双向矩阵）

| 需求（报告） | 覆盖子任务 | 验收方法 |
|---|---|---|
| 计划→建议链路可用 | S1 | `apply_route_engine` 返回非空 proposals |
| 所有下单入口过同一风控 | S2 | `confirm_proposal` 与 `orders_crud` 同输入同结果 |
| 重复操作只产生一次有效提交 | S3 | 并发确认恰一次 `route_order` |
| 订阅事件能落库与推送 | S4 | 非主线程调用 → persist/broadcast 被调用 |
| 调度状态可查询 | S5 | create 后 get 返回一致切片 |
| 既有 91 项测试不回归 | 全部 | 每子任务 PR CI 全绿 |
| 审计能留痕（B6，第二波） | S6 | result 反映真实 ok/fail/unknown |
| 重启可恢复（B9，第二波） | S9 | 重启后父子单/建议状态可读 |

每子任务 PR 描述须含「改动-需求」映射，无冗余项（必要）、无遗漏项（充分）。

---

## 6. 本次不做（边界）

- **B7 未知态 / `EMSX_REQUEST_SEQ` / `API_SEQ_NUM` 重同步**：第二波 S7，需协调 Bloomberg 文档语义与 request_handler 改造，不混入第一波。
- **B8 风控服务化 + `DEMO_USERS` 替换 + 账户/台席授权**：第三波 S10/S11，需上游授权源（LDAP/AD 或 OMS），不阻塞第一波。
- **B9 真实持久化与驱动循环**：第二波 S9，依赖 `RepositoryProvider` 扩展与调度器重写。
- **TCA 事前成本预测、PM 决策时点记录、对账佣金税费**：报告第四/五点，属产品扩展非阻断项，不在本计划。
- **不引入 redis / 新 ORM / 新外部依赖**。
- **不改前端**（除 S3 的 `CONFIRMING` 态展示可选，列为 S3 可选项）。

---

## 7. 子任务登记（执行时填）

| 子编号 | 分支 | 状态 | PR | 备注 |
|---|---|---|---|---|
| 030 | `030-fix-engine-await-mismatch` | ⏳ 待办 | — | S1 |
| 031 | `031-confirm-proposal-compliance` | ⏳ 待办 | — | S2，依赖 S1 |
| 032 | `032-confirm-proposal-idempotent` | ⏳ 待办 | — | S3，依赖 S2 |
| 034 | `034-subscription-persist-loop-fix` | ⏳ 待办 | — | S4 |
| 035 | `035-execution-slice-query-fix` | ⏳ 待办 | — | S5 |

第二波（S6–S9）、第三波（S10–S11）子编号待第一波收尾后分配。
