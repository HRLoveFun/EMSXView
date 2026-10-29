# 060 — SQLite 持久化开启与加固

> 父计划：`specs/057-execution-decision-loop/plan.md`（DL-02，第 11 节第一波）
> 分支：`060-sqlite-persistence-hardening` · worktree：`../EMSXView-wt-060-sqlite-persistence-hardening`
> 依赖：D-4 已定（2026-10-20 用户决策：运营库用 SQLite，048 路径已彩排）；与 DL-01（058）无文件重叠
> 关联：`specs/048-rehearsal-sqlite-persistence/plan.md`（SQLite 三缺陷修复：bootstrap 全模型导入、BigIntPK、JSON 跨方言）

## 1. 问题

- **持久化关闭时路由参数事后无法重建**：`routes_projection` 只存最新状态且受 `ENABLE_DB_PERSISTENCE`（默认 false）门控；路由参数（起止时间、参与率上限）每天随进程丢失，DL-21 决策日志与 DL-07 管道采集都以此为前置。
- **PM 授权检查被静默跳过**：`authorization_service.py:155` 在 provider 不可用时返回 None（检查跳过），下单入口的授权校验形同虚设。
- **熔断不可见**：写入失败累计 10 次即回退内存（`service_provider.py:64`），`/api/health` 只测连接、不报熔断状态与失败计数——数据不落盘但界面显示正常。
- **开启即用需要加固**：048 演练验证了 SQLite 可建表可恢复，但未设 WAL / busy_timeout / foreign_keys，也未定义库文件位置、备份与恢复演练。

## 2. 方案（P2 三栏）

### 2.1 理论依据

持久化关闭时路由参数事后无法重建、PM 授权检查跳过、建议单与路由计划重启即丢（tasks.md DL-02）。单人单机下 SQLite 够用、免安装、048 已彩排（D-4）；出现多机/多进程同时写、IT 要求托管、需要远程访问或按时间点恢复、锁冲突反复熔断时再切 PostgreSQL（条件写入 ADR）。

### 2.2 技术方案（细化到文件与函数）

**配置**（`backend/api/config.py`）：

- 新增 `EMSXVIEW_OPS_DB_DIR: str = os.getenv("EMSXVIEW_OPS_DB_DIR", "")`——运营库目录（仓库外，未配置时取用户主目录下固定路径 `<home>/.emsxview/ops`，解析函数 `default_ops_db_dir()` 与库名常量 `OPS_DB_FILE_NAME = "emsx_ops.db"` 同放 config.py，遵守 AP-04 的 config.py 例外）；
- `_validate_settings` 增一行日志：运营库类型（SQLite/PG）与路径（开启持久化时可见，关闭时也打印解析值备用）。

**连接**（`backend/api/db.py`）：

- `get_database_url()` 优先级：env `DATABASE_URL` 显式值 → SQLite（`sqlite+aiosqlite:///{ops_dir}/emsx_ops.db`）→ 现 PG 默认（兜底，docker-compose 场景由 compose 显式设 `DATABASE_URL`，见下「部署核对」）；
- `create_engine()`：URL 以 `sqlite` 开头时注入 SQLite 专项参数——`connect_args={"timeout": 30}`（aiosqlite 层）+ `event.listens_for(engine.sync_engine, "connect")` 设置 `PRAGMA journal_mode=WAL`、`PRAGMA busy_timeout=30000`、`PRAGMA synchronous=NORMAL`、`PRAGMA foreign_keys=ON`（FK 锚点闭环在 SQLite 上默认关闭，必须显式启用）；
- `initialize_database()` / `check_database_connection()` 逻辑不变（048 修复已覆盖）。

**熔断可见**（`backend/api/service_provider.py` + `backend/api/routers/connection.py`）：

- `RepositoryProvider` 新增三个只读公开属性：`write_error_count`、`max_write_errors`、`circuit_open`（`_write_errors >= _max_write_errors`）；
- `/api/health` 的 `database` 字段在 `ENABLE_DB_PERSISTENCE` 开启时增报 `write_errors` / `circuit_open` / `max_write_errors`；`healthy` 判定**不变**（熔断是降级保护而非连接故障，改判定会误报服务不健康——处置是告警 + 排查写入失败原因）。

**备份**（`scripts/ops/backup_ops_db.py`，新建）：Python 脚本，用 `sqlite3.Connection.backup()` 在线热备（WAL 模式下安全，不阻塞后端写入）；参数 `--db` / `--dest`（默认 `EMSXVIEW_OPS_DB_BACKUP_DIR`，未设取库同级 `backups/`）；输出 `emsx_ops_YYYYMMDD_HHMMSS.db`；非零退出码供计划任务告警；docstring 内置月度恢复演练清单（复制备份 → `PRAGMA integrity_check` → 以副本为 `DATABASE_URL` 启动 → 抽查 orders/routes 行数与昨日一致）。收盘后由 Windows 计划任务或人工触发（本次只交付脚本与清单，不注册计划任务）。

**部署核对**（`backend/docker-compose.yml`）：确认 compose 的 backend 服务显式设置 `DATABASE_URL`（PG 连接串）。未显式设置则补上——否则容器部署会因新的 URL 解析默认值悄悄切到 SQLite（容器内 home 目录），属行为漂移。host-network 模式（`docker-compose.host.yml`）同样核对。

**测试**（`backend/api/tests/test_sqlite_persistence_hardening.py`，新建，沿用 `test_route_plan_persistence.py` 的真实 SQLite + reload + monkeypatch 模式）：

1. PRAGMA 生效：引擎连接后断言 `journal_mode=wal`、`busy_timeout=30000`、`foreign_keys=1`；
2. 订单 upsert 与重启恢复：同一 tmp 库 persist_order 两次（第二次同 sequence 更新）→ 新 `RepositoryProvider` `load_orders()` 读到最新值；
3. 路由 upsert 与重启恢复：persist_route 两次 → `load_routes()` 读到最新值；
4. 锁冲突下 busy_timeout 等待：后台线程持写事务 0.5s 后释放，前台 provider 写在 1s 内成功（证明等待而非立即 `database is locked`）；
5. 熔断：monkeypatch session 工厂连续 11 次抛错 → `is_active` False、`write_error_count` 11、`circuit_open` True；`mark_db_ready(True)` 后计数清零、`is_active` 恢复；
6. health 上报：TestClient 打 `/api/health`（`ENABLE_DB_PERSISTENCE=true` + 注入 provider），`database` 含三个新字段；关闭时字段不出现。

**文档同步**：

- `AGENTS.md` §11.5 环境变量表：`ENABLE_DB_PERSISTENCE` 行「PostgreSQL 订单/路由持久化开关」改为「SQLite 运营库订单/路由持久化开关（路径 `EMSXVIEW_OPS_DB_DIR`）」并新增 `EMSXVIEW_OPS_DB_DIR` 行；§5.1 架构图「PostgreSQL (可选)」改「SQLite 运营库（可选）」。注：tasks.md 原文写的「§13.3」经核对无 PostgreSQL 字样（§13.3 是分析库降级路径，SQLite mode=ro 口径，与运营库无关），实际落点为 §11.5 与 §5.1；
- 新建 `docs/spec/adr/0022-operational-db-sqlite.md`（D-4 正式记录）：选型、URL 解析优先级、PRAGMA 口径、备份与恢复演练责任、切换 PostgreSQL 的四项条件。

### 2.3 检验方法（= 验收标准）

1. 真实 SQLite 测试：订单、路由 upsert 与重启恢复（用例 2/3）；
2. 人为制造锁冲突，验证 busy_timeout 等待与熔断上报（用例 1/4/5/6）；
3. 连续一周运行无熔断、恢复演练能还原前一日数据——开启后由用户实际运行验证，PR 交付脚本与清单，结果回填 ADR（本次不阻塞合并）；
4. `AGENTS.md` 口径同步 + ADR 评审通过（PR diff）；
5. 既有测试不回归：backend 全量（本地跑 `pytest tests/ -q`，超时则按模块分批）、frontend 不涉及。

## 3. 规模与拆分说明

预估 diff 约 400 行（ADR ~80 + 测试 ~150 + 备份脚本 ~70 + db/config/provider/connection ~80 + AGENTS ~20）。超出单 PR ≤200 行建议线：DL-02 是验收原子单元（开启、加固、熔断可见、备份可恢复须同一 PR 才可验收），沿用 DL-01（058）经用户 2026-10-21 确认的单 PR 先例。

## 4. 范围锁

| 动作 | 文件 |
|---|---|
| 修改 | `backend/api/config.py`（`EMSXVIEW_OPS_DB_DIR`、`OPS_DB_FILE_NAME`、默认目录解析、启动日志） |
| 修改 | `backend/api/db.py`（URL 解析优先级、SQLite PRAGMA 注入） |
| 修改 | `backend/api/service_provider.py`（三个只读公开属性） |
| 修改 | `backend/api/routers/connection.py`（health 增字段） |
| 修改 | `backend/docker-compose.yml` / `backend/docker-compose.host.yml`（核对/补显式 `DATABASE_URL`） |
| 新建 | `scripts/ops/backup_ops_db.py` |
| 新建 | `backend/api/tests/test_sqlite_persistence_hardening.py` |
| 新建 | `docs/spec/adr/0022-operational-db-sqlite.md` |
| 修改 | `AGENTS.md`（§11.5 表、§5.1 架构图） |
| 新建 | `specs/060-sqlite-persistence-hardening/plan.md`（本文件） |

范围外（不碰）：MarketView、CostView、platform_data、data_access、任何 Bloomberg 代码、前端、`specs/057-execution-decision-loop/tasks.md`（状态行留待交付 PR 内更新）、AGENTS.md §12 中 MarketView「1 个测试文件」的既存漂移（DL-01 后实为 3 个文件——登记由用户另决，不夹带）。

## 5. 验收（P4）

| 需求（057 DL-02 检验方法） | 覆盖 | 结果 |
|---|---|---|
| 订单/路由 upsert 与重启恢复 | 用例 2/3 | 待实施后回填 |
| 锁冲突下 busy_timeout 等待 + 熔断上报 | 用例 1/4/5/6 | 待实施后回填 |
| 备份脚本可在线热备 + 恢复演练清单 | `backup_ops_db.py` + 首次演练回填 ADR | 待实施后回填 |
| AGENTS.md 口径同步 + ADR | diff + 评审 | 待实施后回填 |
| 既有测试不回归 | backend 全量 + boundaries | 待实施后回填 |

## 6. 本次不做

- 生产 PostgreSQL 迁移（条件见 ADR，触发后再议）；
- 注册 Windows 计划任务（脚本就绪，触发方式由用户部署时决定）；
- 连续一周无熔断的运行观察（开启后由实际使用验证，回填 ADR）；
- DL-21 决策日志表（依赖本任务的持久化开启，另立子任务）。
