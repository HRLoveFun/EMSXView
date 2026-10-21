# ADR-0022: 运营库采用 SQLite（ExecutionView 持久化）

> 状态: Accepted
> 日期: 2026-10-21
> 标签: architecture, data, backend, deployment

## 背景 (Context)

057 执行决策闭环计划 DL-02（D-4，2026-10-20 决策）需要开启 `ENABLE_DB_PERSISTENCE` 并加固。持久化关闭时存在三个已验证的问题：

1. 路由参数（起止时间、参与率上限）只存内存，每天随进程丢失——事后无法重建，DL-21 决策日志与 DL-07 管道采集均以此为前置；
2. PM 授权检查被静默跳过（`authorization_service` 在 provider 不可用时返回 None），下单入口授权校验形同虚设；
3. 写入失败累计 10 次即熔断回退内存，但 `/api/health` 只测连接、不报熔断——数据不落盘而界面显示正常。

048 整日演练已彩排 SQLite 持久化路径（修复 bootstrap 缺表、BigIntPK、JSON 跨方言三缺陷，10/10 建表、恢复验证通过），单人单机场景成立。

## 决策 (Decision)

1. **运营库用 SQLite**，库文件放仓库外固定目录：`EMSXVIEW_OPS_DB_DIR` 显式指定，未配置取用户主目录 `.emsxview/ops/emsx_ops.db`；不与管道分析库（`${EMSXVIEW_DATA_DIR}`）混放。
2. **连接串解析优先级**：env `DATABASE_URL` 显式值 → SQLite（上述路径）→ PostgreSQL 默认兜底。docker-compose 已显式设置 `DATABASE_URL`（PG），容器部署行为不变；host 模式 compose 同步显式化兜底，防止隐式默认漂移。
3. **SQLite 连接加固**：`journal_mode=WAL`（库级持久，读写不互斥）、`busy_timeout=30000`（与 data_access 分析库同口径；aiosqlite 层 connect timeout 同步设 30s 双保险）、`synchronous=NORMAL`（WAL 下推荐）、`foreign_keys=ON`（SQLite 默认 OFF，建议单 FK 锚点依赖它）。
4. **熔断可见**：`RepositoryProvider` 公开 `write_error_count` / `max_write_errors` / `circuit_open` 只读属性；`/api/health` 在持久化开启时增报。healthy 判定不变（熔断是降级保护，非连接故障）。
5. **备份与恢复演练**：`scripts/ops/backup_ops_db.py` 用 sqlite3 在线备份 API 热备（WAL 安全、不阻塞写入）；月度恢复演练清单内置脚本 docstring，结果回填本 ADR「验证记录」节。
6. **开启方式**：`ENABLE_DB_PERSISTENCE=true`，开启当天起路由参数落盘、PM 授权检查生效。

## 后果 (Consequences)

### 正面

- 路由参数、授权、建议单、决策日志（DL-21）获得可恢复的持久化底座；
- 写入失败从「静默回退」变为「health 可见 + 告警可接线」；
- 免安装、免运维，备份脚本与演练清单闭环数据安全（G0）。

### 负面 / 取舍

- SQLite 单写者：后端多实例并发写不适用（当前单人单机，可接受）；
- 备份与恢复演练成为运维责任（脚本已交付，计划任务注册由部署时决定）；
- WAL 模式产生 `-wal` / `-shm` 伴生文件，复制库文件时须用 backup API 或同拷贝三件套。

### 对其他 ADR 的影响

- 引用: ADR-0003（ExecutionView owns operational state）、ADR-0016（外部数据存储只读拆分，本 ADR 管运营库写入侧，与只读分析库对称）、D-4（057 决策记录）
- 被引用: 后续 ADR（DL-21 决策日志表、运营库切换 PostgreSQL 时的再决策）

## 备选方案 (Considered Alternatives)

- 方案 A: 继续用 PostgreSQL（docker-compose 已有 postgres 服务）
  - 否决原因: 单人单机场景需常驻容器运维，与 048 已验证的 SQLite 路径重复建设；D-4 已明确「出现多机/多进程同时写、IT 要求托管、需要远程访问或按时间点恢复、锁冲突反复熔断时再切 PostgreSQL」
- 方案 B: 纯内存 + 每日导出归档
  - 否决原因: 路由参数事后不可重建，直接违背 DL-02 目标与 057 原则 2
- 方案 C: SQLite 放仓库内 `_tmp/`
  - 否决原因: 违反 tasks.md「库文件放仓库外固定目录」；`_tmp/` 有 30 天在途清理策略，会误删运营库

## 实施注意事项 (Implementation Notes)

- 涉及的关键文件: `backend/api/config.py`（`EMSXVIEW_OPS_DB_DIR` / `OPS_DB_FILE_NAME` / `resolve_ops_db_dir`）、`backend/api/db.py`（URL 优先级 + SQLite PRAGMA + 目录创建）、`backend/api/service_provider.py`（熔断三属性）、`backend/api/routers/connection.py`（health 增报）、`backend/docker-compose.host.yml`（显式 DATABASE_URL 兜底）、`scripts/ops/backup_ops_db.py`（热备 + 演练清单）
- 配套测试: `backend/api/tests/test_sqlite_persistence_hardening.py`（PRAGMA 断言、订单/路由 upsert 重启恢复、锁冲突等待、熔断、health 上报）+ `test_db_bootstrap.py`（默认 URL 语义随决策更新）
- 切换 PostgreSQL 条件（触发后再立 ADR）: 多机/多进程同时写、IT 要求托管、需要远程访问或按时间点恢复、锁冲突反复熔断
- 回滚策略: `ENABLE_DB_PERSISTENCE=false` 即回退内存模式（既有行为）；库文件保留可随时重新开启

## 验证记录 (Verification Log)

> 以下两项由开启后实际运行验证，通过后回填：

- [ ] 连续一周运行无熔断（起始日期、观察结论）
- [ ] 恢复演练：备份副本 integrity_check ok + 行数与备份前一日一致（演练日期、结论）
