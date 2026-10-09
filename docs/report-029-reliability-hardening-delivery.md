# 029 交易可靠性加固 — 交付汇报

> 依据：外部审计报告《EMSXView 实用化评估》（基于 `ed4b586`，2026-09-23）与伞计划
> [`specs/029-trading-reliability-hardening/plan.md`](../specs/029-trading-reliability-hardening/plan.md)
> 执行窗口：2026-10-07（单日）；交付形态：13 个独立 PR（#114–#126），全部 CI 全绿 squash 合并。
> Last updated: 2026-10-07

---

## 1. 总览

| 维度 | 数据 |
|---|---|
| 子任务 | 13 个（S1–S13，specs/030–043）+ 实盘验证（044–046） |
| PR | #114–#126（计划内）+ #127–#129（实盘验证与实测修复），全部 squash 合并，main 线性历史 |
| 后端测试 | 226 → **296 passed**（+70 用例，零回归） |
| 既有审计五处阻断项 | **全部闭环**（B1–B5） |
| 引申项 | B6/B7/B8/B9 全部或部分闭环（见 §3） |
| 实盘字段验证 | **已闭环**（5.4，2026-10-08 实测，见 §5.4） |
| 剩余项 | 5.1/5.2/5.3 已搁置（重启条件见各节）；5.5 整日演练待值守安排（见 §5） |

三个波次的定位（对应报告三阶段）：

| 波次 | 报告对应阶段 | 子任务 | 测试 |
|---|---|---|---|
| 第一波·阻断项修复 | 「先修实盘阻断项」 | S1–S5（B1–B5） | 226 → 247 |
| 第二波·风控与状态真相 | 「先修实盘阻断项」深化 | S6–S9（B6/B7/B3 深化/B9） | 247 → 269 |
| 第三波·授权与工作流 | 「再扩展自动化与多人使用」前置 | S10–S13（B8 + PM 授权） | 269 → 290 |

---

## 2. 审计五处阻断项闭环情况（核心交付）

| # | 报告论点 | 修复 | PR |
|---|---|---|---|
| B1 | 路由计划接口与引擎不匹配（await 普通 dict 抛 TypeError，链路整体不可用） | `_engine_repo` 改异步类实例 + 内存 dict → SQLAlchemy 模型转换；`route_engine.py` 零改动 | #114（030） |
| B2 | 建议确认入口绕过风控（同一笔 5,000 万委托普通入口被拦、建议入口直通） | `confirm_proposal` 接入 `compliance_service.check_route`，与单笔路由入口（orders_crud）完全同口径；检查置于 try 外防异常吞噬 | #115（031） |
| B3 | 同一建议可并发重复提交（check-then-act 跨 await） | per-proposal `asyncio.Lock` + `CONFIRMING` 中间态；并发确认恰一次 `route_order`；失败/拦截回退可重试；reject 对中间态 409 | #116（032） |
| B4 | 订阅线程到持久化/推送断链（`get_event_loop` 在 blpapi 线程抛错被静默吞） | lifespan 注入主 loop 引用 + 统一 `_dispatch_to_main_loop`（4 个调用点）；未注入/执行失败均 ERROR 可见 | #117（034） |
| B5 | 父子单调度用模拟仓库（创建 4 切片、查询 0 切片但状态 RUNNING） | 切片存储提升模块级（跨实例共享）+ MOCK 显式标记 + 配置不符告警（S5）；进而接入真实 DB 持久化与驱动循环（S9，见 §3） | #118（035）、#122（039） |

每个阻断项均配「先特征测试锁行为、再改结构」的回归测试；修复点全部有定向用例覆盖。

---

## 3. 已落实改动详述

### 3.1 第一波·阻断项修复（S1–S5）

**S1（030）计划→建议链路打通**
- 问题本质：引擎对仓库方法全部 `await`，仓库侧却是同步 staticmethod；且 repo 返回内存 dict，引擎按属性访问（`plan.priority`、对 ISO 字符串调 `.timestamp()`）。
- 改动：`_EngineRepo` 五方法 `async def`；`_plan_dict_to_model` / `_alloc_dict_to_model` 显式模型转换；模块级单例使两处调用点零改动。
- 验收：5 个新用例（TIME_SCHEDULE 切片数、BROKER_SPLIT 百分比切分 600/400、自动匹配、建议入列、订单缺失 404）。

**S2（031）风控入口统一**
- `confirm_proposal` 补齐与 `orders_crud.route_order` 完全相同的 compliance 口径（含 `USD_NOTIONAL_MAX=49,000,000` 硬拦截）；拦截后 `route_order` 适配器零调用（测试断言）。

**S3（032）并发幂等（进程内）**
- `CONFIRMING` 中间态在跨 await 期间对外可见；锁对象随 proposal 生命周期保留（不 pop，避免新建锁竞态）。

**S4（034）订阅持久化/推送修复**
- 主 loop 由 lifespan 注入一次（`set_main_loop`），dispatch 未就绪时 `logger.error` 且 `coro.close()`；协程执行失败经 `add_done_callback` 记 ERROR——此前 persist/broadcast 异常**完全静默**。
- 真实后台线程（blpapi 回调线程场景）有专项用例。

**S5（035）切片查询修复**
- `_slices_store` 模块级按 parent_id 分桶；切片 id 全局唯一；`ENABLE_DB_PERSISTENCE=true` 但用 MOCK 时 `logger.warning`——「配置开启 ≠ 持久化发生」不再静默。

### 3.2 第二波·风控与状态真相（S6–S9）

**S6（036）审计两阶段化**
- `audit_log` 默认 `result="PENDING"`（此前操作前硬编码 `"ok"`——审计语义说谎）；新增 `audit_result(correlation_id, result)` 按主键回填。
- 结果词汇表：`ok` / `fail` / **`unknown`**（请求超时 504——券商可能已收到订单）/ `PENDING`。
- 关键下单入口（`confirm_proposal`、`route_order`）已接入；其余 23 处调用点自动受益于诚实的 PENDING 语义，逐入口接入按风险优先级另行推进。

**S7（037）请求防重 + 未知态 + 跳号重同步**
- `EMSX_REQUEST_SEQ`：交易请求携带单调递增序号（Bloomberg 文档防故障期间重复请求）；`restore_request_seq` 重启恢复**只升不降**（防序号回退重放）。
- 超时 504 结构化：`detail={message, outcome:"unknown", correlation}`。
- `API_SEQ_NUM` 跳号从 warning 升级 ERROR 并触发 `_schedule_resync`；`register_resync_callback` 注入点就绪（真实重同步需实盘会话）。

**S8（038）建议持久化幂等键**
- 幂等键 = `SubOrderProposal` 数据库主键；create/confirm/reject **先落库再应答**（消除「应答成功 + 落库失败」的重复确认窗口）；lifespan 启动恢复（DB 状态为真相源）；持久化不可用回退内存 id（既有行为零破坏）。

**S9（039）调度持久化 + 驱动循环 + 成交反馈 + 重启恢复**
- repo 扩展：`create_parent` / `list_active_parents` / `list_due_slices` / `get_slice_by_route_id` / `update_slice_fill` 等。
- `ExecutionDriver`：tick 提交到期 PENDING 切片（**submit_slice 注入式——未接线时不提交且 ERROR，绝不静默自动下单**）；`record_fill` 按路由 id 回填切片并汇总父单成交量；`run_forever` lifespan 任务。
- 重启恢复：ACTIVE/PAUSED 父单与切片重建内存 store + 调度器 registry（`register_active_execution` 幂等）。
- 成交反馈接线：订阅路由消息带 `lastShares` 时经主 loop 调度回调。
- 开关 `EXECUTION_DRIVER_ENABLED` 默认 **false**。

### 3.3 第三波·授权与工作流（S10–S13）

**S10（040）可配置用户源**
- `EMSXVIEW_USERS`（JSON：username / password_hash(bcrypt) / full_name / role）替代硬编码 `DEMO_USERS`；回退路径诚实可见（未配置 WARNING、坏 JSON ERROR）；现有部署零破坏。

**S11（041）动作级授权**
- `ROLE_PERMISSIONS`：admin 全权 / trader（trade+modify）/ viewer（view）；**未知角色 fail-closed（空集）**。
- `deps.require_permission` 依赖工厂；**17 个写路径端点**接入（trade：路由/建议确认/批量/父子单启动控制；modify：修改/撤单/批量更新；admin：路由计划 CRUD + apply）；bypass 身份升级 admin（本地终端操作者全权）。
- 17 端点接线契约测试防回归。

**S12（042）PM 授权意图与剩余量跟踪**
- `AuthorizationIntent` 表（symbol+side+portfolio 数量上限；`create_all` 自动建表，无迁移）。
- `compute_remaining`：剩余 = 授权目标 − 执行占用（父单承诺量，**含计划中切片**）；父单经 orders_projection payload 关联维度，投影缺失排除并告警。
- API：`POST /api/authorizations`（admin）/ `GET /api/authorizations`（view，含剩余量视图）。

**S13（043）下单入口授权硬校验**
- `route_order` / `confirm_proposal` 挂接 `enforce_for_order`：
  - **exceeded → 403 硬拒绝**（detail 含剩余量与授权 id）+ 审计 fail + 不触达下单适配器；
  - **not_covered → 放行并 warning**（未登记授权不阻断，严格模式由部署策略决定）；
  - 持久化不可用 → 跳过（降级纪律一致）。

报告场景现已闭环：*PM 授权买 60 万股 → 父单承诺 55 万 → 剩余授权 5 万 → 新增 6 万的请求被 403 拒绝且不触碰券商*。

---

## 4. 行为变更与部署注意事项

| 项 | 变更 | 部署动作 |
|---|---|---|
| 审计默认语义 | 操作发起记录 `result="PENDING"`（不再预写 ok）；未接入回填的入口将永远 PENDING | 无需动作；如需终态接入 `audit_result` 可参照两个下单入口 |
| 用户源 | 未配置 `EMSXVIEW_USERS` 时启动 WARNING，DEMO_USERS 仍生效 | 生产部署**必须**配置（bcrypt 生成命令见 `config.py` 注释） |
| bypass 身份 | role 由 trader → admin（动作级全权） | 开发模式语义变化；`BYPASS_AUTH=true` 不得用于生产 |
| 授权校验 | 存在匹配授权时超量硬拒 403；无匹配授权放行+告警 | PM 授权未登记的标的不会阻断——是否收紧由部署方决策 |
| 驱动循环 | `EXECUTION_DRIVER_ENABLED` 默认 false；未接线 submit 时 tick 仅 ERROR | **默认不会真实下单**；开启前必须完成 submit 接线与评估（见 §5.3） |
| 跳号处理 | `API_SEQ_NUM` 跳号日志 warning → ERROR | 运维告警规则如匹配 warning 级别需同步 |

---

## 5. 剩余项与所需条件

以下项在伞计划中明确登记为「不在 029 范围」。其中 **5.1 / 5.2 / 5.3 已搁置**
（2026-10-07/08 用户决策，重启条件见各节）；**5.4 已闭环**；5.5 待值守安排：

### 5.1 上游授权源接入（LDAP/AD）— ⏸️ 已搁置（2026-10-07 用户决策）

- **现状**：`EMSXVIEW_USERS`（JSON 配置）已替代硬编码；接入点收敛在 `auth._load_config_users` 单函数。
- **搁置理由**：依赖上游基础设施信息，当前无接入计划；`EMSXVIEW_USERS` 配置源已可支撑中小规模多人使用。
- **重启条件**（全部具备时再启动）：
  1. LDAP/AD 服务器地址、端口、TLS 策略；
  2. 服务账号（bind DN/密码）或匿名可读目录；
  3. 用户条目 schema 映射（username / 显示名 / 角色 字段名）；
  4. 角色来源约定（AD 组名 → EMSXView role 映射表）。
- **重启后本侧工作量**：替换 `_load_config_users` 为 LDAP 查询实现 + 登录时 bind 验证；authenticate_user 优先级结构不变。

### 5.2 账户/组合/市场维度授权 — ⏸️ 已搁置（2026-10-07 用户决策）

- **现状**：`check_authorization` 仅覆盖 symbol+side+portfolio 维度的数量约束。
- **搁置理由**：依赖 OMS/上游持仓与账户归属数据，当前无数据源；symbol+side+portfolio 数量授权已覆盖报告场景主路径。
- **重启条件**（全部具备时再启动）：
  1. OMS/上游系统的持仓数据接口（可卖数量、组合归属）；
  2. PM 授权的账户归属与市场范围数据（或确认由 EMSXView 本地登记）；
  3. 禁限买名单的数据源与更新频率。
- **重启后本侧工作量**：动作词汇表与权限矩阵已预留扩展位，需增加维度字段与检查规则；涉及新表（无加列迁移问题）。

### 5.3 驱动循环实盘 submit 接线 — ⏸️ 已搁置（2026-10-08 用户决策）

- **这是什么**：调度器把大单拆成时间表切片后**自动**发到市场。当前开关（`EXECUTION_DRIVER_ENABLED`）默认关闭——系统内所有下单均为人工发起，此功能闲置且无任何风险。
- **搁置影响**：零影响。人工路由、监控、成交反馈、TCA、PM 授权、审计全部正常；系统定位维持报告的「人工确认 + EMSX 券商算法」工作台，自动切片执行属后续演进。
- **重启条件**（全部具备时再启动）：
  1. 业务上确实需要自动切片执行（当前人工路由 + 券商算法已覆盖日常流程）；
  2. 切片下单产品语义确认（推荐默认：RouteEx 直接路由、失败标 FAILED 不自动重试）；
  3. 显式开启 `EXECUTION_DRIVER_ENABLED=true` 并完成 `submit_slice` 接线（约半天代码 + 小额灰度 G1–G6，方案已在本文件 git 历史版本）。
- **安全保证**：搁置期间驱动循环代码保持关闭；即使误开，submit 未接线时 tick 仅 ERROR 告警、不会真实下单。

### 5.4 EMSX_REQUEST_SEQ / lastShares 实盘验证 — ✅ 已闭环（2026-10-08 实盘实测）

- **判定 A 通过**：真实路由 `5018309.1`（CARLB DC Equity SELL 119 @ MKT）创建成功——终端接受携带 `EMSX_REQUEST_SEQ` 字段的 RouteEx 请求，无需回退开关。
- **判定 B 通过 + 语义修正（#129）**：路由 `5018201.1`（GIVN SW Equity，PARTFILL）实测 `lastShares=1`、`dayFill=9`——`lastShares` 是最后一笔增量、`dayFill` 是累计；成交回填链路已改用 dayFill（与 FILLED 判定语义对齐），4 用例回归锁。
- **顺带实测修复（#128）**：`GET /api/orders/status` 因 facade 缺 `_init_paint_done`/`_subscription_failed` 代理实测 500——已修复。
- 验证手册与结果：[`specs/044-emsx-field-verification/plan.md`](../specs/044-emsx-field-verification/plan.md)。

### 5.5 报告阶段二验收：单交易台完整交易日闭环 — 🟢 演练进行中（2026-10-09 启动）

- **演练基础设施**：SQLite 演练持久化打通（#132，实测修复 bootstrap 缺表/BigIntPK/JSON 跨方言三缺陷——生产 PG 启用持久化时同样受益）；演练手册 `specs/048`。
- **已实测通过**：D1 基线、D2 授权登记、D3 人工路由全链路（真实成交流通，暴露 batch 三缺口并热修 #133/#134）、D4 授权硬校验、D5 短断线（crashmon 4 秒自愈、零漂移）、D9 重启恢复。
- **已删除（2026-10-09 用户决策，高风险操作）**：D6 端口阻断模拟超时、D7 实盘拒单、D8 真实撤单竞争——覆盖意图由离线测试承接。
- **待完成**：D10 终端人工操作同步、D11 日终对账（收盘后）。
- **5.3 已搁置**：演练覆盖人工路由路径，不含调度驱动切片提交。

---

## 6. 验证边界声明（诚实披露）

- 本计划全部验证为**离线测试 + 模拟适配器**（与审计报告的验证边界一致），**未连接 Bloomberg 实盘**，未发送真实委托；
- 「重复操作只产生一次有效提交」等结论证明的是**应用层调用行为**（适配器调用计数），不能据此断言实盘零重复成交；
- 涉及真实报文字段（`EMSX_REQUEST_SEQ`、`lastShares`）与真实下单（驱动循环 submit）的路径，须按 §5.3/§5.4 完成实盘验证后方可视为生产就绪。
