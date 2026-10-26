# 审计整改 R1：A01 准入写入闭环 + A02 下单前检查收敛（子规格）

> 父计划：`specs/057-execution-decision-loop/plan.md`（057 伞计划）
> 整改卡：`specs/057-execution-decision-loop/audit-remediation-2026-10-25.md` §2 A01 / A02
> 审计原文：`docs/report-full-audit-2026-10-25.md` H1 / H2
> 分支：`audit-r1-security`（worktree `../EMSXView-wt-audit-r1-security`，基线 `origin/main` @ `9e8504e`）
> 子编号：**076**（A01 与 A02 同 PR 交付、共用编号；下一可用编号）
> 状态：**待确认**（确认后按 §3.3 范围锁实施）

---

## 1. 是什么（现状与交付边界）

### 1.1 A01 现状：准入写入没有权限、范围与密码约束

| 问题 | 位置 | 现状 |
|---|---|---|
| selection 写入无角色校验 | `backend/api/routers/market_broker_mapping.py:117` | 仅 `Depends(verify_token)`，viewer 也能改写 |
| selection 不受 roster 约束 | 同文件 :117-141 | 注释明写「由前端负责限制」，后端不校验 |
| 密码默认值 | 同文件 :53 | `os.getenv("EMSX_MAPPING_ADMIN_PASSWORD", "admin")` |
| 密码比较非恒定时间 | 同文件 :147 / :169 | 普通 `!=` |
| 无限速 | 同文件 :142-166 | 可无限次猜密码 |
| 审计操作人恒为 unknown | 同文件 :135/:150/:157/:172/:204 | 读 `user.get("username")`，JWT 字段实际是 `sub` |

后果：任何持有 token 的登录用户（含 viewer）可先放开任意「市场 × 券商」再下单，DL-17a 准入层形同虚设。

### 1.2 A02 现状：四个下单入口各写一套检查，层次不一致

| 入口 | 准入 `evaluate_access` | 订单合规（数量/反向单/算法参数） | 策略注册表 | 通用合规 + 碎股白名单 |
|---|---|---|---|---|
| `orders_crud.route_order`（:129-198） | ✅ | ✅ | ❌ | ✅（含 `fractional_markets`） |
| `route_plans.confirm_proposal`（:579-608 → submission_service） | ✅ | ✅（submission_service :164-198） | ✅（:140-162） | ✅（含 `fractional_markets`） |
| `route_plans.batch_confirm_proposals`（:730-747 → submission_service） | ❌ | ✅（同 core） | ✅（同 core） | ❌（`check_route` 未传 `fractional_markets`） |
| `batch_route_service._evaluate_route_item`（:274-305） | ❌ | ❌ | ❌ | ✅（`check_route` 未传 `fractional_markets`） |

后果：被白名单拦下的订单换成批量提交即可发出；batch-route 还可绕过 DL-17b 同日同券商反向单。

### 1.3 本次交付边界（只做 A01 + A02）

- **做**：selection 写入鉴权 + roster 范围约束；roster/unlock 密码加固 + 限速；审计字段 `sub`（A01 范围内，等价于提前完成 A06 在本文件的四处）。
- **做**：新增 `pre_trade_checks` 并让四个入口全部改调它；批量路径补齐四层；BLOCK/WARN 分级统一。
- **不做**（保持现状，留给对应整改卡）：
  - A03 建议单状态回滚（`submission_service` 的 `CONFIRMING` 回滚问题）；
  - A07「订单不在缓存时拒单」与「准入未配置」默认行为决策（`parent_order is None` 仍跳过需要订单的检查）；
  - A06 其余文件的 `username → sub`；
  - A05 其他副作用端点权限；
  - 前端角色门控（见 §3.6 决策点 3）。

---

## 2. 为什么做（依据与口径）

1. **H1 是可利用的越权**：先写 selection 再下单是两跳攻击链，且写入无角色门槛。仅靠前端限制不构成边界（后端必须自行校验）。
2. **H2 是「同一笔订单换入口即绕过」**：检查分散实现导致同一订单在不同入口得到不同结论，违反「同一决策同一口径」。DL-22（影子运行）要求影子与正式路径同口径，A02 是其前置。
3. **沿用项目既有口径**（不新造语义）：
   - 「未配置 = 部署初期例外（跳过并审计），已配置但未命中 = 阻断转人工」（071/073 已固化）；
   - G2：新增阻断性检查走特性开关且默认关闭 —— **本次不新增任何阻断能力**，只是把既有检查补到缺失入口，故不新增开关；
   - BLOCK 阻断、WARN 记录后放行（071 固化）；
   - 契约一律 `from platform_data.contracts import ...`（AP-08 误判规避）。
4. **审计字段**：操作的追责价值取决于操作人可追溯，`sub` 是 JWT 中唯一可靠的用户标识。

---

## 3. 如何做

### 3.1 A01 设计（`backend/api/routers/market_broker_mapping.py`）

#### 3.1.1 selection 写入

```python
@router.put("/api/market-broker-mapping/selection", response_model=ApiResponse)
async def update_selection(
    payload: SelectionPayload,
    user: dict = Depends(require_permission("admin")),
) -> ApiResponse:
```

写入前校验（在 `_LOCK` 内基于最新 state）：

- **键归一**（复核补强）：市场键先 `strip().upper()`，落盘时 `EU → EUR`（前端口径），校验时 `EUR → EU`（策略码，与 `access_policy_service._normalize_market_key` 一致）；券商键 `strip().upper()`。校验、落盘、读路径使用同一个市场码，杜绝 `us` / `" US "` / `eu` 变体绕过。
- 对归一后**值为 true** 的每一项 `(market, broker)`：
  - 若策略码 **不在** 归一后的 rosters → 该市场 roster 未配置 → 跳过范围校验，记 WARN 审计（§3.6 决策点 1）；
  - 若在 → `broker` 必须属于该市场归一后的 roster；
  - 越界项聚合后整体拒绝：`HTTPException(400, detail={"message": "Selection contains brokers outside roster", "out_of_roster": [{"market": ..., "broker": ...}], ...})`，且**不落盘**；审计在锁外记录。
- 值为 false 的键不做范围校验（不授予任何权限；前端 `mergeWithDefaults` 会带全量 false 矩阵，强校验会误伤正常保存）。
- 校验通过后按归一化结果落盘（true 优先合并同键），`audit_log` 记 `user=user.get("sub") or "unknown"`，details 带 markets 与被忽略的未配置市场清单。

响应：200 返回既有 state 形状（前端已依赖 `data.updatedAt`）。

#### 3.1.2 roster / unlock 密码

```python
def _admin_password() -> str | None:
    value = os.getenv("EMSX_MAPPING_ADMIN_PASSWORD", "").strip()
    return value or None
```

统一校验函数 `_require_admin_password(password, action, user, details)`：

| 步骤 | 行为 |
|---|---|
| 1. 未配置 | `HTTPException(403, "Admin password not configured")` + 审计 `reason=not_configured`；**不再回落到 "admin"** |
| 2. 限速 | 进程内滑动窗口，**按 JWT sub 分桶**：同用户 60 秒内第 6 次**失败** → `HTTPException(429, "Too many password attempts")` + 审计 `reason=rate_limited`（`_password_failures: dict[str, deque[float]]`） |
| 3. 比较 | `secrets.compare_digest(password.encode("utf-8"), expected.encode("utf-8"))`（非 ASCII 不再抛 TypeError；异常回落 False）；失败 → 记录失败 + 403 + 审计 |
| 4. 成功 | 清零该用户失败窗口；审计 `*.ok`（仅 unlock）；roster 更新继续走原去重/夹取逻辑 |

限速只记**失败**、成功即清零；按用户分桶避免 viewer/trader 打满窗口锁死管理员。进程重启即清零（与「同进程」要求一致，多 worker 上限按进程数放大——已记录为已知限制）。

#### 3.1.3 审计字段

五处 `user.get("username", "unknown")` → `user.get("sub") or "unknown"`。

#### 3.1.4 已知影响

- `PUT selection` 变为 admin-only：`market-broker-mapping-section` 的保存与 `daily-broker-policy-confirm-modal` 的每日确认对 trader 会 403（见 §3.6 决策点 3）。

### 3.2 A02 设计

#### 3.2.1 新文件 `backend/api/services/pre_trade_checks.py`

```python
async def pre_trade_checks(
    parent_order: Any,
    proposal: dict,
    bloomberg: Any = None,
) -> list[dict]:
    """下单前检查统一入口（四入口共用）。

    固定顺序：准入白名单 → 订单合规 → 策略注册表 → 通用合规（碎股白名单）。
    返回 [{"code", "message", "severity", "details"}]；仅 severity=BLOCK 阻断。
    """

def split_by_severity(violations: list[dict]) -> tuple[list[dict], list[dict]]:
    """拆 BLOCK / WARN（仅 BLOCK 阻断）。"""
```

`proposal` 统一键（各入口负责映射，检查层只认这一份）：

| 键 | 类型 | 说明 |
|---|---|---|
| `broker` | str | 券商 |
| `quantity` | int | 本次路由量 |
| `limit_price` | float \| None | 限价 |
| `stop_price` | float \| None | 止损价 |
| `order_type` | str | LIMIT / MARKET / STOP / STOP_LIMIT |
| `strategy_params` | dict | 算法参数 |
| `parent_order_id` | str \| None | 仅用于日志/透传 |

内部四步（每步一个私有函数，保持函数 ≤30 行）：

| 步 | 调用 | 输出映射 |
|---|---|---|
| 1 | `access_policy_service.evaluate_access(parent_order, proposal)` | `PolicyViolation` → `severity = "WARN" if manual_review_required else "BLOCK"`，`details.source="access_policy"` |
| 2 | `await order_compliance_service.evaluate_order_compliance(parent_order, route_qty=quantity, broker=broker, bloomberg=bloomberg, strategy_params=strategy_params)` | 原样透传（`details.source="order_compliance"`） |
| 3 | `strategy_registry.validate_route_submission(broker, strategy_name, strategy_params)` | `errors` → `STRATEGY_PARAM_INVALID` / `STRATEGY_NOT_ALLOWED`（BLOCK）；`warnings` → `STRATEGY_WARNING`（WARN） |
| 4 | `compliance_service.check_route(parent_order, route_qty=..., limit_price=..., stop_price=..., order_type=..., fractional_markets=access_policy_service.fractional_markets())` | `Violation` → dict，`details.source="route_compliance"` |

`parent_order is None` 时：第 1/2/4 步跳过（三者本就对 None 返回空），**第 3 步仍执行** —— 与现 confirm 路径一致（策略校验不依赖订单缓存）；「订单缺失即拒单」留给 A07。

#### 3.2.2 四个入口改造

| 入口 | 改动 |
|---|---|
| `orders_crud.route_order` | 删除 :129-198 三段内联检查（`check_route` / `evaluate_access` / `evaluate_order_compliance`），改为一次 `await pre_trade_checks(parent_order, {...}, bloomberg)`；BLOCK → 400 `detail={"message": "Pre-trade compliance check failed", "violations": blocking}`；WARN 逐条 logger.warning；PM 授权段不变 |
| `route_plans.confirm_proposal` | `_compliance_check` 改 async：解析 parent_order 后调 `pre_trade_checks`；注入 `submit_proposal_core` |
| `route_plans.batch_confirm_proposals` | 同上，替换 :730-747 的独立闭包（补准入 + 碎股白名单） |
| `batch_route_service._evaluate_route_item` | 由 sync 改 async：`check_route` → `await pre_trade_checks`；BLOCK 逐条 `status="BLOCKED"`；WARN 挂 SUCCESS 结果；`dry_run_batch_route` / `stream_batch_route` 改为顺序 `await` 求值（保持输入顺序） |

#### 3.2.3 `submission_service` 收敛

- `compliance_check` 约定改为 **async 可调用**：`violations = await compliance_check(proposal)`；
- 删除文件内 :140-162（`validate_route_submission`）与 :164-198（`evaluate_order_compliance`）两段直接调用 —— 这两层已由 `pre_trade_checks` 提供，避免重复执行与「双份真相」；
- BLOCK 时仍按既有语义回滚 `PENDING_CONFIRM` 并 `audit_result(fail)`（**不改** A03 的状态机）；
- BLOCK 由「抛 HTTPException」改为返回 `SubmissionResult(outcome="BLOCKED", http_status=400)`：单笔端点据此转 400（响应形状不变），批量流据此按条输出 `BLOCKED` 而不中断整批（A02 批量收敛的必要条件）；
- `authorization_check` 保持原位置与语义（PM 授权不在本次收敛范围）。

**顺序变化说明**：单笔确认原先顺序为「compliance → 授权 → 策略 → 订单合规」，收敛后为「准入 → 订单合规 → 策略 → 通用合规 → 授权」。多条违规同时命中时，先报出的那条可能变化；每条检查的阈值、文案、开关语义均不变。

#### 3.2.4 `Violation` 枚举扩展（`backend/api/schemas/batch.py`）

批量结果 `BatchOperationItemResult.violations: List[Violation]` 的 `code` 是 Literal，新增 3 个：

- `STRATEGY_PARAM_INVALID`（BLOCK，注册表参数错误）
- `STRATEGY_NOT_ALLOWED`（BLOCK，算法白名单已配置但未命中）
- `STRATEGY_WARNING`（WARN，未映射族 / 白名单未配置）

#### 3.2.5 不改变语义的声明

- 不修改 `evaluate_access` / `evaluate_order_compliance` / `validate_route_submission` / `check_route` 的**内部逻辑、阈值、文案与开关**（`EMSXVIEW_ALGO_PARAMS_ENFORCED` 行为不变）；
- 不新增阻断性开关（G2：本次无新增阻断能力）；
- `parent_order is None` 的跳过语义不变（A07）；
- 「准入策略文件未配置 = 跳过」不变（A07）；
- PM 授权判定（`enforce_for_order`）不变；
- 批量提交的并发/流式语义不变（仅求值阶段由 sync 改 async，提交仍走原并发池）。

### 3.3 范围锁（只改/新增以下文件）

| # | 文件 | 类型 | 预估行数 |
|---|---|---|---|
| 1 | `backend/api/routers/market_broker_mapping.py` | 改 | +90 / −20 |
| 2 | `backend/api/services/pre_trade_checks.py` | **新增** | ~130 |
| 3 | `backend/api/routers/orders_crud.py` | 改 | −70 / +25 |
| 4 | `backend/api/routers/route_plans.py` | 改 | −45 / +30 |
| 5 | `backend/api/services/submission_service.py` | 改 | −65 / +20 |
| 6 | `backend/api/services/batch_route_service.py` | 改 | −25 / +35 |
| 7 | `backend/api/schemas/batch.py` | 改 | +3 |
| 8 | `backend/api/tests/test_market_broker_mapping_authz.py` | **新增** | ~200 |
| 9 | `backend/api/tests/test_pre_trade_checks.py` | **新增** | ~260 |
| 10 | `backend/api/tests/boundaries/test_pre_trade_checks_single_entry.py` | **新增** | ~45 |
| 11 | `specs/057-execution-decision-loop/tasks.md` | 改 | 2 行 |
| 12 | `specs/057-execution-decision-loop/plan-audit-a01-a02.md` | **新增（本文件）** | — |

合计约 **+830 / −225**（含测试）。超出「单 PR ≤200 行」建议值 —— 本轮按整改卡 R1 的 A01+A02 合并要求交付，测试占比约 60%；若要求严格拆分，需退回为两个 PR（A01 / A02 各一），请确认（§3.6 决策点 5）。

范围外（明确不做）：前端任何文件、`platform_data/`、`docs/handover-*`、`AGENTS.md` 数字、其他路由。

### 3.4 验收对照（逐条断言 → 证据）

| # | 验收断言（整改卡 / 派工） | 证据（测试文件 :: 用例） |
|---|---|---|
| 1 | `viewer` PUT selection → 403 | `test_market_broker_mapping_authz.py::test_selection_requires_admin` |
| 2 | 越 roster 的 true 项 → 400 且响应列出越界项 | `...::test_selection_out_of_roster_rejected`（断言 `detail["out_of_roster"]` 含 market/broker，文件未改） |
| 3 | 未配置 `EMSX_MAPPING_ADMIN_PASSWORD` → unlock/roster → 403（`admin` 也不放行） | `...::test_password_not_configured_denies` |
| 4 | 密码比较走 `secrets.compare_digest` | `...::test_password_uses_compare_digest`（monkeypatch 计数） |
| 5 | 密码错误 5 次后第 6 次 → 429 | `...::test_password_rate_limited` |
| 6 | 正常 admin：selection + roster + unlock → 200，`audit_log` 的 user 为 `sub` | `...::test_admin_flow_audits_sub` |
| 7 | 同一「被白名单拒绝」订单：四入口全部拒绝（单笔 400；批量逐条 BLOCKED） | `test_pre_trade_checks.py::test_four_entries_blocked_by_access_policy` |
| 8 | 同日同券商反向单在 batch-route 被拦 | `...::test_batch_route_blocked_by_reverse_order` |
| 9 | WARN 不阻断（四入口均放行且记录） | `...::test_warn_does_not_block` |
| 10 | 无入口绕过 `pre_trade_checks` 直接调用检查函数 | `tests/boundaries/test_pre_trade_checks_single_entry.py`（AST 扫描 `backend/api/**`，白名单仅 `pre_trade_checks.py`） |
| 11 | 既有后端 512+ 全绿不减 | 全量 pytest 输出（§3.5 命令 1） |

补充说明（§3.6 决策点 2）：批量入口的 HTTP 状态是 200 + NDJSON 逐条 `status=BLOCKED`（流式协议在首字节后无法改状态码）；`dryRun=true` 时 `blocked>0`。单笔入口为 400。

### 3.5 验证与门禁执行计划

按坑位 1 分进程执行：

```bash
# 1) 后端全量（含新增）
cd backend/api && python -m pytest tests/ -q --ignore=tests/boundaries
# 2) 后端边界（含新增单入口守卫）
cd backend/api && python -m pytest tests/boundaries/ -q
# 3) 其余域（未改动，按分进程纪律复核）
python -m pytest MarketView/tests/ -q
python -m pytest CostView/tests/ -q
# 4) 门禁预检
python scripts/audit_doc_drift.py
python scripts/audit_db_paths.py
python scripts/audit_cross_imports.py
python scripts/audit_underscore_access.py
python scripts/quality_gate.py --staged
```

前端未改动，不本地跑 tsc/vitest（坑位 2），交 CI。

交付：单提交 `fix(audit/A01+A02): 准入白名单写入闭环与下单前检查收敛 (audit/A01+A02/076)`；PR 标题 `fix(audit/A01+A02): 准入写入闭环与下单检查收敛`；同一 PR 更新 `tasks.md` A01/A02 行为「已完成 / 076」。

### 3.6 需确认的决策点

1. **roster 未配置（market 不在 rosters）时的 selection 范围校验**：建议**跳过并审计 WARN**（沿用「未配置 = 部署初期例外」口径）。理由：仓库内无 `backend/api/data/market_broker_mapping.json`（运行期文件），全新部署 rosters 为空；若按严格子集，任何 selection 写入都 400，前端自动落库与每日确认全部失效，且 selection 为空会让 `load_broker_market_policy` 全阻断券商。**若要求严格子集（空 roster 也拒绝），请明确，我按严格版实现。**
2. **批量入口的「400」语义**：建议单笔 400、批量 200+逐条 BLOCKED（与既有流式协议一致）。若要求批量整体 400，需要改流式协议（影响前端批量面板），建议不做。
3. **每日确认弹窗**：admin-only 后，trader 打开弹窗点击确认会 403。前端角色门控不在本 PR 范围；建议登记为 R2/A05 的后续项（或单独前端 PR）。请确认是否接受。
4. **`Violation` 枚举新增 3 个 code**：为让批量结果能承载策略层违规（Literal 限制），需扩展 `schemas/batch.py`。是否同意？
5. **子编号与拆分**：A01/A02 同 PR、共用 076，diff 约 830 行（测试约 60%），超 200 行建议值。接受合并，还是拆两个 PR（076 A01 / 077 A02）？

### 3.7 风险与回滚

| 风险 | 影响 | 处置 |
|---|---|---|
| admin-only 使每日确认对 trader 失效 | 交易台无法自助确认白名单 | 决策点 3；后端行为本身是审计要求 |
| roster 未配置时仍可写 selection | 未配置市场的范围约束不生效 | 决策点 1（用户已确认）；admin 门槛已关闭 H1 的越权主体；市场键归一后无法借大小写变体混入已配置市场 |
| 限速为进程内、按用户分桶 | 多 worker 时上限按进程数放大；同一 token 仍可自限 | 与整改卡「同进程」要求一致；已记录已知限制 |
| submission_service 注入签名改 async | 仅 2 个调用点（单笔/批量确认） | 同步改动 + 既有 `test_submission_unified.py` / `test_confirm_proposal_compliance.py` 回归 |
| 批量求值由 sync 改 async | 大批量求值耗时略增 | 顺序 await（不并发压 SQLite）；提交阶段并发不变 |
| 检查顺序变化导致首个报错不同 | 前端展示的 message 可能变化 | §3.2.3 已声明；仅影响多违规并存场景 |

回滚：单提交 revert（无数据迁移、无配置变更、无新文件被运行期依赖）。

---

## 4. 实施顺序

1. `pre_trade_checks.py` + `Violation` 枚举 → 单测（纯函数/注入 fake）。
2. 四入口改造 → 既有 `test_confirm_proposal_compliance.py` / `test_submission_unified.py` / `test_batch_route_endpoints.py` 回归。
3. A01 router 改造 + 测试。
4. 边界单入口守卫。
5. 全量 + 门禁预检 + tasks.md 状态 + 提交/PR。
