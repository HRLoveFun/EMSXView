# 审计整改计划（2026-10-25 全项目审计 → 交付序列）

> **审计来源**：`docs/report-full-audit-2026-10-25.md`（基线 `af17240`，已合入 `4f152a3`）
> **本文性质**：把审计 14 项发现（H1–H2 / M1–M4 / L1–L3 / E1–E5）纳入 057 交付序列的可追溯整改计划
> **可追溯约定**：审计编号 `H1` ↔ 整改编号 `A01` ↔ PR 标题带 `(audit/A01)` ↔ 验收证据挂在对应 PR 描述

## 0. 一页结论

| 项 | 结论 |
|---|---|
| 是否改变 DL-17 已完成结论 | **不改变交付事实，但改变可用性判定**——H1/H2 使 DL-17a 准入与 DL-17b 反向单**可被绕过**，在 A01/A02 完成前 DL-17 整体视为「未闭环」 |
| 是否阻塞待办 DL | **DL-22（影子运行）、DL-25（辅助模式）被 H2/A02 阻塞**（影子对比必须与正式路径同口径）；DL-15/DL-19/DL-20 不阻塞 |
| 优先级重排 | 原计划「DL-15 → DL-19/20 → DL-22」调整为 **A01+A02+A10+A11（第 1 轮，安全与工程基线）→ A03–A06（第 2 轮）→ A12–A14（第 3 轮）→ DL-15 → DL-19/20 → DL-22…** |
| 新增事件项 | 无新增业务需求；A01–A14 全部为既有代码的缺陷修复与工程基线，不改变 057 功能范围 |

## 1. 编号映射与时间节点

**轮次定义**：每轮 = 一个 worktree + 一个 PR + 完整 PR 流程（复核 → 实施 → CI 四项 → squash 合并 → 清理）。时间节点以此为准，不按日历天承诺。

| 轮次 | 整改编号 | 审计编号 | 内容 | 预估 |
|---|---|---|---|---|
| **R1** | A01 | H1 | 准入白名单写入闭环（角色 + roster 范围 + 密码） | ~180 行 |
| | A02 | H2 | 下单前检查收敛为共用函数（批量路径补齐四层） | ~260 行 |
| | A10 | E1 | `platform_data` 依赖修正（去 `emsxview-datapipeline`） | ~15 行 |
| | A11 | E2 | `greenlet` 显式声明 | ~5 行 |
| **R2** | A03 | M1 | 建议单状态回滚（CONFIRMING 不再永久卡死） | ~60 行 |
| | A04 | M2 | CostView 桥接与 MarketView 鉴权（token + 角色 + 绑定地址） | ~120 行 |
| | A05 | M3 | 副作用端点补 `require_permission`（5 处） | ~60 行 |
| | A06 | M4 | 审计字段 `username` → `sub`（含断言测试） | ~30 行 |
| **R3** | A12 | E3 | Node 版本固定（engines + .nvmrc，Node 22） | ~10 行 |
| | A13 | E4 | 文档计数去硬编码 + `doc_check.py` 结构对账（方式变更，随 2026-10-29 文档重构提前完成） | ✅ 2026-10-29（#204–#209） |
| | A07 | L1 | 订单不在缓存时拒单 + 准入默认行为明确化 | ~50 行 |
| | A08 | L2 | PM 授权按条件查询（去 limit=5000 全量） | ~90 行 |
| **R4** | A09 | L3 | locale 显式化 + 时区口径确认 + token-service 合并 | ~140 行 |
| | A14 | E5 | 复杂度热点拆分（按需分批，不阻塞交付） | 分批 |
| **回归** | — | — | R1–R3 完成后回归 DL-17 三条链路（单笔/批量/影子）并回填 P4 | 1 轮 |

## 2. 逐项整改卡（验收标准 = 可执行断言）

### A01（H1）准入白名单写入闭环 🔴

- **审计原文**：`market_broker_mapping.py:117` selection 写入仅 `verify_token`、不限 roster、无密码；密码默认 `"admin"`、`!=` 比较、无限速
- **整改**：
  1. `PUT /api/market-broker-mapping/selection` 增加 `require_permission("admin")`；后端强制 `selection ⊆ rosters[market]`（越界拒绝并返回越界项）；
  2. `PUT .../roster` 与 `POST .../unlock` 的密码：移除默认 `"admin"`（未配置 `EMSX_MAPPING_ADMIN_PASSWORD` 直接 403）、改 `secrets.compare_digest`、加简单限速（同进程 5 次/分钟）；
  3. 审计事件写 `sub`（与 A06 合并验证）。
- **验收**：`viewer` 角色 PUT selection → 403；越 roster 项 → 400 且列出越界项；未配置密码 → 403；密码比较走常量时间（代码审查项）；正常 admin 全流程 → 200 且 `audit_log` 含 `sub`。
- **关联**：DL-06/071 契约（docs/ADR 无需改）、DL-22（影子运行使用同一 selection 读路径）。

### A02（H2）下单前检查收敛 🔴

- **审计原文**：`batch_route_service.py:274`、`route_plans.py:730` 的批量路径缺准入/订单合规/策略/碎股四层；单笔路径也不一致
- **整改**：
  1. 新增 `backend/api/services/pre_trade_checks.py::pre_trade_checks(parent_order, proposal, bloomberg) -> list[dict]`，内部按固定顺序调用：`evaluate_access`（071）→ `evaluate_order_compliance`（072，含数量守恒/反向单/volume cap/release time 开关）→ `validate_route_submission`（070）→ `fractional_markets`（071）；
  2. 四个下单入口全部改调该函数（`orders_crud.route_order`、`route_plans.confirm`、`batch_route_service.dry_run_batch_route` 与 `batch-confirm`）；
  3. BLOCK/WARN 分级统一（仅 BLOCK 阻断，WARN 记录），删除各处重复实现。
- **验收**：四入口对同一「被白名单拒绝」的订单均 400（批量路径逐条 result 为 failed）；反向单在批量路径被拦（`test_batch_route_blocked_by_reverse_order`）；WARN 不阻断；既有 512+ 测试全绿；`grep` 确认无入口绕过（除 `pre_trade_checks` 外无直接调用 `evaluate_access`/`evaluate_order_compliance`）。
- **关联**：DL-22 前置（影子对比需与正式路径同口径）；DL-25 前置。

### A03（M1）建议单状态回滚 🟠

- **整改**：`submission_service` 把 `compliance_check`/`authorization_check` 纳入 `try`，`finally` 兜底——未走到 `route_order` 前一律回滚 `PENDING_CONFIRM`。
- **验收**：策略文件 JSON 写坏 → 状态回滚且下次可确认（不再 409）；授权库异常 → 同上；既有提交测试全绿。

### A04（M2）桥接与 MarketView 鉴权 🟠

- **整改**：`backend/api/routers/costview.py:49` 桥接挂载 `include_router(..., dependencies=[Depends(verify_token)])`；写端点（如 `/api/tca/recommendations/pin`）补 `require_permission("trade")`；`MarketView/config.py:11` 默认 `127.0.0.1`；`MarketView/main.py:36` CORS 收紧（不用 `allow_credentials=True` + `*` 组合）。
- **验收**：无 token 访问 CostView 14 端点任一 → 401；viewer pin → 403；MarketView 默认绑定地址断言；handoff POST 未带 token → 401。

### A05（M3）副作用端点补权限 🟠

- **整改**：`tca/runner/run`、`connection/reconnect`、`broker-algorithms/refresh`、`handoff/post-trade` → `require_permission("admin")`（handoff 可 `trade`）；`debug` 路由仅 `DEBUG=true` 时注册。另（A01 回归）：`daily-broker-policy-confirm-modal` 按角色渲染——前端解码 JWT `role`，非 `admin` 不弹确认框（后端 admin 强制不变）。
- **验收**：5 个端点 viewer → 403；`DEBUG` 未设时 `/api/debug/*` 404；非 admin 不渲染每日确认弹窗。

### A06（M4）审计字段修正 🟠

- **整改**：`market_broker_mapping.py` 四处（`:135/:150/:157/:172` 及 roster 处）`user.get("username")` → `user.get("sub")`。
- **验收**：审计断言测试——admin 改 roster 后日志 `user == "admin"`（token sub）；无 token 字段时回落 `unknown`。

### A07（L1）订单缺失与默认行为 🟡

- **整改**：`route_plans.py:585`、`orders_crud.py:125` 的 `parent_order is None` 分支由「跳过全部检查」改为「拒绝（404/409 + 明确消息）」；`access_policy_service.py:30` 注释与 `evaluate_access` 行为统一（明确写入「策略未配置 = 跳过准入检查（部署初期例外）+ 审计日志」）。
- **验收**：订单不在缓存 → 400/404 且消息可读；策略未配置 → 检查跳过但 `audit_log` 留痕（非静默）。

### A08（L2）PM 授权查询优化 🟡

- **整改**：`authorization_service.enforce_for_order` 改按 `symbol/side/portfolio` 过滤查询；批量路径一次请求复用加载结果。
- **验收**：>5000 订单夹具下已用额度仍准确（构造 6000 单回归）；批量 N 条只加载 1 次（mock 计数断言）。

### A09（L3）三小项 🟡

- **整改**：`marketview-utils.ts` 的 `toLocaleString(undefined)`/`Intl.NumberFormat(undefined)` → 显式 `"en-US"`；`needs_daily_confirmation` 时区口径先出决策（建议用交易所本地日期，需用户确认部署时区）；两份 token-service 合并为 `frontend/src/shared/services/token-service.ts` 单一来源。
- **验收**：`marketview-utils.test.tsx` 在 zh-CN 环境通过；时区决策记录到子规格；EV 侧删除重复实现且 import 全部指向 shared。

### A10–A14（E1–E5）工程与文档

| 编号 | 整改 | 验收 |
|---|---|---|
| A10（E1） | 删除 `platform_data/pyproject.toml` 的 `emsxview-datapipeline`，补 `openpyxl` | 干净环境 `pip install -e platform_data` 成功（CI job 验证） |
| A11（E2） | `backend/api/requirements.txt` 加 `greenlet` | 无缓存的 CI 后端测试无 greenlet 报错 |
| A12（E3） | 根与 `frontend` 的 `package.json` 加 `engines: {"node": ">=20.19 <23"}` + `.nvmrc`（22） | `npm ci` 在 Node 22 通过；README 注明 |
| A13（E4） | **方式变更（2026-10-29 完成）**：原动作「更新 AGENTS §4.2/§6/§12/§14 的数字」已失效——那几节随文档重构下沉，且**测试计数改为不写数字、只给可复跑命令**（7 处硬编码全部消除）。替代物：新增 `scripts/doc_check.py` 做结构对账（地图覆盖 / 元信息头 / 状态枚举 / 死链与 `#锚点` / 失效词表），接入 `doc-drift-report.yml` 周报 | `python scripts/doc_check.py` 退出码 0（当前 0 FAIL / 0 WARN）；全仓 `grep "295 个测试函数"` = 0 命中 |
| A14（E5） | 复杂度热点分批拆分：`get_intraday_features`（66）、`_mktdata_subscription_loop`（58）、`_process_subscription_message`（55）优先；前端三件套（RouteTable 858 行等）排技术债 | 每拆一个函数圈复杂度降 ≥30% 且测试全绿；OEW 下降可量化 |

## 3. 对既有开发任务的影响评估

| 待办任务 | 影响 | 处置 |
|---|---|---|
| **DL-15**（盘中市场状态） | 无直接冲突；新增端点须遵守 A04/A05 的鉴权基线 | 排在 R1–R3 之后，避免返工 |
| **DL-19/DL-20**（3a 评估口径） | 纯 CostView 离线分析，与安全整改无交集 | **可与 R1 并行**（不同 worktree） |
| **DL-22**（影子运行） | **被 A02 阻塞**：影子对比要求正式/影子同口径 | A02 完成后立即解锁，排 R4 后 |
| **DL-23/24**（排名与得分快照） | 依赖 DL-20/22 | 顺延，无额外影响 |
| **DL-25**（辅助模式） | 依赖 A01/A02（准入与检查收敛）与 A04（鉴权） | R1–R2 完成后 |
| **DL-07/08/09**（管道仓库任务） | 不受影响（另一仓库） | 可随时移交管道侧 |
| **DL-17 已完成结论** | 交付事实不变，但**闭环判定改为「A01+A02 完成后生效」** | tasks.md 的 DL-17 备注追加该条件 |

## 4. 可追溯矩阵（审计 → 整改 → 验收 → PR）

| 审计 | 整改 | 轮次 | PR 标题约定 | 验收证据位置 |
|---|---|---|---|---|
| H1 | A01 | R1 | `fix(audit/A01): 准入白名单写入闭环` | PR 描述「验收对照」+ `test_market_broker_mapping_authz.py` |
| H2 | A02 | R1 | `fix(audit/A02): 下单前检查收敛` | PR + `test_pre_trade_checks.py`（四入口矩阵） |
| E1 | A10 | R1 | `fix(audit/A10): platform_data 依赖修正` | CI 安装日志 |
| E2 | A11 | R1 | `fix(audit/A11): 声明 greenlet` | CI 后端 job |
| M1 | A03 | R2 | `fix(audit/A03): 建议单状态回滚` | `test_submission_state_rollback.py` |
| M2 | A04 | R2 | `fix(audit/A04): 桥接与 MarketView 鉴权` | `test_costview_authz.py` |
| M3 | A05 | R2 | `fix(audit/A05): 副作用端点权限` | 权限矩阵测试 |
| M4 | A06 | R2 | `fix(audit/A06): 审计字段 sub` | 审计断言测试 |
| E3 | A12 | R3 | `chore(audit/A12): 固定 Node 22` | CI 矩阵 |
| E4 | A13 | R3 | `docs(audit/A13): 去硬编码 + doc_check` | `python scripts/doc_check.py` 输出（0 FAIL / 0 WARN） |
| L1 | A07 | R3 | `fix(audit/A07): 订单缺失拒单` | 回归测试 |
| L2 | A08 | R3 | `fix(audit/A08): PM 授权查询优化` | 6000 单夹具 + mock 计数 |
| L3 | A09 | R4 | `fix(audit/A09): locale/时区/token 合并` | 前端测试 + 决策记录 |
| E5 | A14 | R4+ | `refactor(audit/A14): 复杂度拆分` | 质量门禁 OEW 对比 |

## 5. 状态与回填规则

- 每轮完成后在本文 §1 表格追加「状态 / PR / 合并提交」三列；
- tasks.md 的「审计整改」区与本文双向对应（本文件 §1 为准，tasks.md 只放状态行）；
- R1–R3 全部完成后，在 `specs/057-execution-decision-loop/tasks.md` 的 DL-17 行追加备注：「闭环以 A01/A02 完成为准」。
