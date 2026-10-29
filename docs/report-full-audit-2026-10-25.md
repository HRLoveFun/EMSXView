# EMSXView 全项目审计报告（2026-10-25）

> L3 | 权威：2026-10-25 全项目审计的发现与整改卡 | 不权威：整改当前状态（见 `specs/057-execution-decision-loop/audit-remediation-2026-10-25.md`）

> **审计基线**：`main` @ `af17240`（feat: 路由决策日志与影子记录 (057-DL-21/075)）
> **审计方式**：自动化门禁（边界审计脚本 + 质量门禁 + 全量测试）+ 人工代码审查（重点覆盖 ExecutionView 下单/合规/鉴权链路）
> **改动范围**：本次审计未修改任何仓库内代码

## 结论摘要

自动化门禁全部通过（AP 违规 0，补齐依赖后 1124 个测试只有 1 个失败，属于环境相关）。人工审查发现 **2 个高危问题**，都出在 ExecutionView 的合规/准入链路上：057-DL-17a 引入的准入白名单可以被绕过。

| 严重度 | 数量 | 编号 |
|---|---|---|
| 🔴 高 | 2 | H1、H2 |
| 🟠 中 | 4 | M1–M4 |
| 🟡 低 | 3 | L1–L3 |
| 工程 / 文档 | 5 | E1–E5 |

---

## 一、自动化基线

| 检查项 | 结果 |
|---|---|
| 边界审计（`audit_cross_imports` / `audit_underscore_access` / `audit_db_paths` / `audit_doc_drift`） | ✅ 全部通过 |
| `python scripts/quality_gate.py --report` | AP 违规 0；OE 技术债 140 项（OE-05 101 / OE-07 20 / OE-02 9 / OE-06 9 / OE-01 1），约 188 小时，OEW 5.8（报告判定为「快速累积期」） |
| 后端 `backend/api/tests/` | ✅ 512 passed（54 个文件） |
| CostView `CostView/tests/` | ✅ 352 passed（13 个文件） |
| MarketView `MarketView/tests/` | ✅ 59 passed（6 个文件） |
| 前端 `typecheck` / `lint` / `lint:modules` | ✅ 通过 |
| 前端 vitest（Node 22） | 201 passed / **1 failed**（`fmtCompact` 随系统语言变化，见 L3） |

**复现说明**：Python 依赖按 `.github/workflows/boundary.yml` 的方式安装（Python 3.12，过滤 `blpapi`，`PYTHONPATH=<repo-root>:<repo-root>/scripts/ci/blpapi_stub`）；另需手动补装 `greenlet`（见 E2）。

---

## 二、安全与正确性问题

### 🔴 H1　准入白名单可被任意登录用户改写（包括 viewer 角色）

- **位置**：`backend/api/routers/market_broker_mapping.py:117`、`backend/api/services/access_policy_service.py:107`
- **现象**：
  - 下单时的券商准入检查 `load_broker_market_policy()` 直接读 `market_broker_mapping.json` 里的 `selection`。
  - 写这个字段的端点 `PUT /api/market-broker-mapping/selection` 只要求 `verify_token`：
    - 不检查角色权限（`require_permission`），也不要密码；
    - 不限制在 roster 范围内（注释写的是"由前端负责限制"）。
- **后果**：任何拿到 token 的人都能先放开任意「市场 × 券商」组合再下单，DL-17a 的准入层形同虚设。
- **相关问题**：修改 roster 的密码默认是 `"admin"`（`market_broker_mapping.py:53`，`EMSX_MAPPING_ADMIN_PASSWORD`），用普通 `!=` 比较（不是常量时间比较），也没有限速。
- **建议**：selection 写入改为要求 `require_permission("admin")`，后端强制限制在 roster 内；取消默认密码，未配置时直接拒绝写入；比较改用 `secrets.compare_digest`。

### 🔴 H2　批量路径漏掉了合规层

- **位置**：`backend/api/services/batch_route_service.py:274`、`backend/api/routers/route_plans.py:730`
- **现象**：单笔路由 `orders_crud.py:108` 和单笔确认 `route_plans.py:579` 都完整调用了准入、订单合规和策略校验，批量路径却缺了几层：

| 路径 | 准入白名单 `evaluate_access` | 订单合规（反向单 / 数量守恒） | 策略注册表 | 碎股白名单 `fractional_markets` |
|---|---|---|---|---|
| `POST /api/orders/batch-route` | ❌ | ❌ | ❌ | ❌ |
| `POST /api/sub-order-proposals/batch-confirm` | ❌ | ✅ | ✅ | ❌ |
| 单笔 `POST /api/orders/route` | ✅ | ✅ | ❌ | ✅ |
| 单笔 `POST /api/sub-order-proposals/{id}/confirm` | ✅ | ✅ | ✅ | ✅ |

- **后果**：被白名单拦下的单笔订单，换成批量提交就能发出去；batch-route 还能绕过 DL-17b 的同日反向单拦截。
- **建议**：把这几层检查收进一个共用函数（例如 `pre_trade_checks(parent_order, proposal, bloomberg)`），所有下单入口都调它；补边界测试，确保批量路径会被白名单拦下。

### 🟠 M1　建议单可能永久卡在 CONFIRMING

- **位置**：`backend/api/services/submission_service.py:96`、`:103`、`:127`
- **现象**：先把状态置为 `CONFIRMING`，但 `compliance_check` 和 `authorization_check` 都在 `try` 块**外面**。下面两种情况会抛普通异常：
  - 策略文件 JSON 写坏了（`access_policy_service.py:62` 没有 try）；
  - 运营库读授权出错（`authorization_service.py:157`）。
- **后果**：状态不会回滚。之后每次确认（包括批量确认）都返回 409 "already being confirmed"，只能重启进程才能恢复。
- **建议**：把检查调用挪进 `try`，或者用 `finally` 兜底：只要还没走到 `route_order`，就回滚到 `PENDING_CONFIRM`。

### 🟠 M2　CostView 路由挂到 :`<API_PORT>` 后完全没有鉴权

- **位置**：`CostView/api/routers/costview.py`、`CostView/api/routers/monitoring.py`、`backend/api/routers/costview.py:49`
- **现象**：CostView 的 14 个端点都没有 `Depends(verify_token)`，经桥接挂进核心进程后，等于在核心端口上开放了匿名访问，其中包括：
  - `POST /api/tca/recommendations/pin`（`CostView/api/routers/costview.py:518`）：这是**写入**接口，写进去的内容会出现在 ExecutionView 的 `GET /api/broker-recommendations` 里；
  - 能读到全部 TCA 成交数据。
- **相关问题**：MarketView 默认监听 `0.0.0.0`（`MarketView/config.py:11`；CostView 默认是 `127.0.0.1`），同时配置了 `CORS *` 加 `allow_credentials=True`（`MarketView/main.py:36`），handoff 的 POST 同样匿名。
- **建议**：桥接挂载时统一加上 `include_router(..., dependencies=[Depends(verify_token)])`，写端点再加 `require_permission`；MarketView 默认改为 `127.0.0.1`，和 CostView 保持一致。

### 🟠 M3　有副作用的端点只要求登录，不检查角色

以下端点 viewer 也能调用：

| 端点 | 副作用 |
|---|---|
| `POST /api/tca/runner/run`（`backend/api/routers/costview.py:73`） | 触发 ETL |
| `POST /api/connection/reconnect`（`backend/api/routers/connection.py:98`） | 重连 Bloomberg 会话 |
| `POST /api/broker-algorithms/refresh`（`backend/api/routers/broker.py:120`） | 刷新券商算法缓存 |
| `POST /api/executions/handoff/post-trade`（`backend/api/routers/orders_handoff.py:94`） | 写跨模块 handoff |
| `POST /api/debug/query-round-lot`（`backend/api/routers/debug.py:65`） | 同步阻塞 Bloomberg 会话最多 5 秒（`debug.py:94` 的轮询循环） |

- **建议**：按动作补 `require_permission`（admin / trade）；debug 路由默认不挂载，只在 `DEBUG=true` 时注册。

### 🟠 M4　准入相关的审计日志记不到用户名

- **位置**：`backend/api/routers/market_broker_mapping.py:135`、`:150`、`:157`、`:172`
- **现象**：这里用的是 `user.get("username")`，但 JWT payload 里的字段叫 `sub`（其他路由都用 `user.get("sub")`）。
- **后果**：白名单和 roster 的修改日志里，操作人一律显示 `unknown`，偏偏这是最需要留痕的操作。
- **建议**：改用 `user.get("sub")`，并补一个断言审计用户字段的测试。

### 🟡 L1　检查在订单不在缓存时直接放行

- **位置**：`backend/api/routers/route_plans.py:585`、`backend/api/routers/orders_crud.py:125`
- **现象**：只要 `parent_order` 不在 Bloomberg 缓存里，合规、准入、PM 授权全部跳过。
- **相关问题**：`access_policy_service.py:30` 的注释写着"未配置 = 全阻断安全默认"，实际代码（`evaluate_access`，约 `:149`）是未配置就跳过检查，注释和行为相反。
- **建议**：订单找不到时直接拒绝；准入策略的默认行为（fail-open 还是 fail-closed）需要明确决策并统一注释。

### 🟡 L2　PM 授权的计算口径有隐患

- **位置**：`backend/api/services/authorization_service.py:162`
- **现象**：`enforce_for_order` 每次确认都会全量加载 `load_orders(limit=5000)`。
- **后果**：
  - 订单超过 5000 条后，已用额度会算少，可能超授权放行；
  - 批量提交时 N 个条目就要做 N 次全表加载。
- **建议**：改为按 symbol / side / portfolio 过滤查询；批量路径在一次请求内复用加载结果。

### 🟡 L3　其他小问题

- **数字格式随系统语言变化**：`MarketView/module/marketview-utils.ts` 的 `fmtCompact` / `fmtNumber` 用 `toLocaleString(undefined)` / `Intl.NumberFormat(undefined)`，中文系统显示 `1.1亿`；`marketview-utils.test.tsx:24` 在本机失败、在 CI（en-US）上通过。建议显式指定 locale。
- **每日确认的时区口径（待确认）**：`needs_daily_confirmation` 拿 UTC 的 `updatedAt`（`last_mapping_update_date`）和本地日期比较。如果交易台在 UTC 以西，晚间确认会被算成次日已确认。需要先确认部署时区再决定是否修。
- **前端有两份 token-service**：`frontend/src/shared/services/token-service.ts` 和 `ExecutionView/module/services/http-client.ts:93`，建议合并为 shared 单一来源。

---

## 三、工程与文档问题

| 编号 | 问题 | 位置 | 建议 |
|---|---|---|---|
| E1 | `platform_data` 还依赖已迁出的 `emsxview-datapipeline`（CostView 那边已于 2026-09-16 删掉），结果普通 `pip install -e platform_data` 直接失败，CI 靠 `--no-deps` 才绕过去 | `platform_data/pyproject.toml:13` | 删除该依赖，补齐真实依赖（如 `openpyxl`） |
| E2 | `greenlet` 没有显式声明。SQLAlchemy async 需要它，在 macOS arm64 上不会自动安装，导致 20 个持久化测试报错 | `backend/api/requirements.txt` | 显式加入 `greenlet` |
| E3 | 本机 Node 20.18 跑不了 vitest（jsdom 依赖要求 ≥20.19，`ERR_REQUIRE_ESM`）；Node 26 又因内置 `localStorage` 冲突导致 43 个用例失败 | `package.json`、`frontend/package.json` | 加 `engines` 字段或 `.nvmrc`，固定 Node 22 |
| E4 | AGENTS.md 的数字已经过时，`audit_doc_drift` 没检查出来（见下表） | `AGENTS.md` §4.2 / §6 / §12 / §14 | 统一更新数字；考虑把测试计数纳入 doc-drift 审计 |
| E5 | 复杂度热点 | 见下表 | 优先拆分 Bloomberg 订阅处理与 market adapter |

**E4 数字漂移对照**：

| 项目 | 文档写的 | 实际 |
|---|---|---|
| 后端测试 | 45 个文件 / 295 个测试 | 54 / 512 |
| CostView 测试 | 10 / 305 | 13 / 352 |
| MarketView | 3 个端点 / 1 个测试文件 | 7 / 6 |
| 前端测试文件 | 25 | 27 |

**E5 复杂度热点**（质量门禁 Top 5，圈复杂度）：

| 函数 | 位置 | 圈复杂度 |
|---|---|---|
| `get_intraday_features` | `platform_data/adapters/market.py:367` | 66 |
| `_mktdata_subscription_loop` | `backend/api/services/bloomberg/enrichment.py:152` | 58 |
| `_process_subscription_message` | `backend/api/services/bloomberg/subscriptions.py:289` | 55 |
| `get_market_snapshot` | `platform_data/adapters/market.py:185` | 48 |
| `enrich_orders` / `submit_proposal_core` | `backend/api/services/order_projections.py:18` / `submission_service.py:50` | 45 |

前端超长组件：`RouteTable.tsx`（858 行，18 个 useState）、`route-plan-manager.tsx`（633 行，23 个 useState）、`use-batch-route-state.ts`（924 行）。

---

## 四、建议修复顺序

1. **H1 + H2**（同一个主题：准入层闭环）：selection 写入改为要求 `admin` 权限并限制在 roster 内；把下单前的全部检查收敛成一个函数，所有下单入口共用；补测试，确保批量路径会被白名单拦下。
2. **M1**：把检查调用挪进 `try`，或者加 `finally` 兜底回滚状态。
3. **M2 / M3 / M4**：桥接挂载时统一加上 `dependencies=[Depends(verify_token)]`，写端点补 `require_permission`，审计字段改用 `sub`。
4. **E1–E4**：修复 pyproject、greenlet、Node 版本声明，再统一更新 AGENTS.md 里的数字。
5. **L1–L3、E5**：纳入常规技术债清偿。
