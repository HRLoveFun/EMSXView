# 048 — 5.5 整日演练：SQLite 演练持久化 + 执行手册

> 父计划：`specs/029-trading-reliability-hardening/plan.md`（剩余项 5.5）
> 分支：`048-rehearsal-sqlite-persistence`
> 前提：5.4 已闭环（#127–#129）；5.3 已搁置（演练覆盖人工路由路径，不含调度驱动提交）

## 1. 演练基础设施（本 PR）

**实测发现并修复的阻塞缺陷**（生产 PG 同样受影响，重要性高）：

| # | 缺陷 | 修复 |
|---|---|---|
| 1 | `db.initialize_database` 仅 import `execution_state` 模型——`route_plans` / `sub_order_proposals` / `authorization_intents` / `parent_executions` 等表**从未被 create_all 创建**（bootstrap 报成功但表缺失） | 显式 import 全部模型模块 |
| 2 | `BigInteger` 主键在 SQLite 不自增（ROWID 自增仅对 Integer 生效）→ INSERT 报 NOT NULL failed | 主键类型 `BigIntPK = BigInteger().with_variant(Integer, "sqlite")`，9 处主键替换 |
| 3 | `JSONB` 为 PG 专用方言，SQLite 无法建列 | 改跨方言 `JSON`（本仓库未用 JSONB 操作符查询；既有 PG 表结构不受影响） |

预检结论：SQLite 建表 10/10、JSON 列读写 roundtrip、`SQLITE PERSISTENCE PATH: OK`；全量 296 passed。

## 2. 演练环境启动（用户执行）

```powershell
# 主树（最新 main），会话内设置演练环境后启动后端
cd C:\Users\hrchen\Documents\EMSXView\backend\api
$env:ENABLE_DB_PERSISTENCE = "true"
$env:DATABASE_URL = "sqlite+aiosqlite:///<repo-root>\_tmp\rehearsal.db"
$env:ENABLE_AUDIT_LOG = "true"
python -m uvicorn main:app --host localhost --port 3000
```

- 演练库独立于任何生产数据（SQLite 文件在 `_tmp/`，gitignore 覆盖）；
- 生产 PG 部署不受影响（既有 PG 表结构不变，新部署将补齐缺失表）；
- `EXECUTION_DRIVER_ENABLED` 保持 **false**（5.3 已搁置）。

## 3. 演练场景（D1–D11）

操作者 = 用户（终端/界面/API）；观测与归因 = AI 会话（API 查询 + 日志 + DB 查询）。

> **场景调整（2026-10-09 用户决策）**：删除 D6（端口阻断模拟超时）、D7（实盘拒单）、
> D8（真实撤单竞争）三个高风险操作场景——均需阻断 Bloomberg 连接或对真实委托
> 施加竞争操作，风险/收益不成比例。其覆盖意图由离线测试与代码审计承接：
> 超时 unknown 语义（test_audit_result_truthful + 504 结构化）、拒单审计 fail、
> 撤单终态一致性（模型状态机）。D9 已于 2026-10-09 实测通过后保留记录。

| # | 场景 | 状态 | 操作 | 观测/判定 | 记录 |
|---|---|---|---|---|---|
| D1 | 开盘基线 | ✅ 通过 | 启动后端 → INIT_PAINT | `orders/status` 200、order_count 对齐、schema initialized | 2026-10-09 |
| D2 | 登记授权 | ✅ 通过 | `POST /api/authorizations` | id=1 持久化、remaining=target | 2026-10-09 |
| D3 | 人工路由全链路 | ✅ 通过（含缺口修复 #133/#134） | 前端批量路由 PPH SJ 182,421 股 | 路由创建、真实成交流通（dayFill 3,195）、batch 三缺口热修 | 2026-10-09 |
| D4 | 授权硬校验 | ✅ 通过 | 超授权请求 | 403 exceeded（requested=500/remaining=100）；not_covered 放行告警 + 安全网 | 2026-10-09 |
| D5 | 终端断线 | ✅ 通过 | 杀 bbcomm（crashmon 4 秒自愈） | 全程 conn=True 零波动；长断线 failed 置位路径未触发（见 §6） | 2026-10-09 |
| D6 | 请求超时 | 🗑️ 已删除 | ~~阻断 EMSX 端口~~ | 高风险（管理员操作 + 影响 Bloomberg 全部连接）；unknown 语义由离线测试承接 | 2026-10-09 |
| D7 | 拒单 | 🗑️ 已删除 | ~~实盘拒单~~ | 高风险；fail 审计路径已由 D4 exceeded 实测覆盖 | 2026-10-09 |
| D8 | 撤单竞争 | 🗑️ 已删除 | ~~真实撤单竞争~~ | 高风险（对真实委托施加竞争操作）；状态机终态一致性由测试承接 | 2026-10-09 |
| D9 | 进程重启 | ✅ 通过 | kill → 重启（同 env） | 授权 2 条从 SQLite 恢复；S8/S12 持久化实测 | 2026-10-09 |
| D10 | 人工切回 EMSX | ⏳ 待终端操作 | 终端直接改量/撤单 | EMSXView 订阅同步、不反向覆盖 | ☐ |
| D11 | 日终对账 | ⏳ 待收盘 | 终端 vs EMSXView 全量核对 | 逐项一致；差异登记 open-todos | ☐ |

### 6. 演练实测记录（2026-10-09）

- **过程热修**：#133（授权端点 async 缺 await 500）、#134（batch 授权预检/审计回填/GET 噪音治理）、#132（bootstrap 缺表/BigIntPK/JSON 跨方言）——演练暴露真实缺陷并当日闭环，296 → 301 passed。
- **实测语义确认**：`lastShares`=最后一笔增量、`dayFill`=累计（#129）；EMSX 存量订单不计授权占用（占用按父子单承诺量）。
- **审计噪音**：GET 轮询 1,079 条 PENDING 已由 050 治理（只读端点不审计）。
- **PPH SJ 大单**：182,421 股 SELL 无授权放行发生于 batch 校验上线前；050 后同请求将被 403 拒绝。该单 PARTFILL 工作中，处置由交易员决定。

## 4. 本次不做

- 调度驱动切片提交场景（5.3 已搁置）；
- 生产 PG 迁移（补缺失表将在生产部署时由修复后的 bootstrap 自动完成）。

## 5. 验收

| 需求 | 结果 |
|---|---|
| SQLite 演练持久化路径打通 | 预检 OK + 296 passed |
| bootstrap 缺表缺陷修复（生产受益） | 代码 + 预检 |
| 演练手册可执行 | D1–D11 清单 |
| 演练执行结果 | 演练日后回填本文件 §6 |
