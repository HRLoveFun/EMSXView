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

## 3. 演练场景（D1–D10）

操作者 = 用户（终端/界面/API）；观测与归因 = AI 会话（API 查询 + 日志 + DB 查询）。

| # | 场景 | 操作 | 观测/判定 | 记录 |
|---|---|---|---|---|
| D1 | 开盘基线 | 启动后端 → 确认 INIT_PAINT | `GET /api/orders/status` 200 且 order_count 与终端一致；日志 `Restored ... proposals`、`schema initialized` | ☐ |
| D2 | 登记授权 | `POST /api/authorizations`（某标的 BUY 小数量） | 返回 id；`GET /api/authorizations` remainingQuantity = target | ☐ |
| D3 | 人工路由全链路 | route → modify → 部分成交 | 订单/路由与终端一致；审计 result=ok；授权 remaining 减少 | ☐ |
| D4 | 授权硬校验 | 新增请求超剩余授权 | 403 + remainingQuantity；适配器零调用（audit fail） | ☐ |
| D5 | 终端断线 | 停 bbcomm 1–2 分钟 | subscription_failed 可见；恢复后重同步无漂移 | ☐ |
| D6 | 请求超时 | 阻断 EMSX 端口后发起请求 | 504 → 审计 result=**unknown**；恢复后人工核对实际状态 | ☐ |
| D7 | 拒单 | 发起必被拒请求 | 400/明确错误；审计 fail；无假成功 | ☐ |
| D8 | 撤单竞争 | 成交瞬间并发 cancel | 终态一致（FILLED 或 CANCELLED）；审计双留痕 | ☐ |
| D9 | 进程重启 | kill → 重启（同 env） | warm-start：订单/路由/建议/父子单恢复；无重复确认（S8 幂等）；日志 `Restored ...` | ☐ |
| D10 | 人工切回 EMSX | 终端直接改量/撤单 | EMSXView 订阅同步、不反向覆盖 | ☐ |
| D11 | 日终对账 | 终端 vs EMSXView 全量核对 | 逐项一致；差异登记 open-todos | ☐ |

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
