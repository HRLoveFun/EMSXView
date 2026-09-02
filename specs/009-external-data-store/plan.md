# 009-external-data-store — 数据库外置项目目录 + 读写职责分离

> 分支 `009-external-data-store`（基于 origin/main）。
> 目标：① SQLite 数据库默认位置迁移到项目目录外；② 读取方与更新维护方的数据库访问职责物理分离（读 = 文件级只读，写 = 管道唯一写入方）。
>
> 关联：ADR-0012（配置单一来源）、ADR-0700（worktree 工作流 §6.1 数据目录隔离）、`docs/spec/data-domain.md`（Data Platform 拥有存储）。

## 背景（现状与痛点）

1. **数据在项目内**：`Config.DATA_DIR` 默认 `{PROJECT_ROOT}/CostView/data`，数据库（约数十 GB）与代码同仓同目录。
   - worktree 场景：每个 worktree 的 `CostView/data` 为空，需手工设置 `EMSXVIEW_DATA_DIR` 指向主树（git-workflow §6.1 的"数据零受损"约束本质是对数据错放项目内的补丁）。
   - 备份/清理/归档等维护操作容易误触代码仓库文件树。
2. **读写未物理分离**：`ConnectionManager.AccessTier.READ/WRITE` 仅做 SQL 文本分类拦截（可被 `raw_connection` 绕过），底层 `sqlite3.connect()` 统一以可写模式打开——读取方（CostView API / monitoring / tca_query / query_cli）的进程一旦有 bug 仍可写坏数据文件，违背 G0 数据零受损的精神。
3. **双真相源残留**：`CostView/api/config.py` 自行计算 `DATA_DIR` 默认值，未从 `DataPipeline.config` 派生（ADR-0012 违例点）。

## 关键决策

| # | 决策 | 理由 |
|---|------|------|
| D1 | 默认数据目录改为项目外：`~/EMSXViewData/data`（`Path.home()` 派生，跨平台一致） | 显眼、可发现、跨平台；与 `.emsxview-root` marker 思路同构（数据独立于代码树） |
| D2 | 优先级链：`EMSXVIEW_DATA_DIR` 环境变量 > 项目外默认值；**显式设置保持原语义** | 已有部署（主树 .env）不受影响；G2 防漂移 |
| D3 | 迁移**显式执行**，不做隐式自动迁移：提供 `scripts/ops/migrate_data_dir.py`（三道安全闸：预检 → 复制校验 → 原目录改名留证） | G0：迁移不可静默；失败可重入（幂等） |
| D4 | 旧目录有数据且新目录为空时，`Config` 打 WARNING 提示运行迁移脚本（不阻塞） | fail-visible 而非 fail-hard，避免破坏现有测试与 CI |
| D5 | READ tier 升级为文件级真只读：`sqlite3.connect("file:...?mode=ro", uri=True)`；只读连接**不创建**不存在的数据库文件（fail-fast，防误建空库） | 损坏风险从"SQL 拦截靠自觉"收敛为"文件系统物理不可能"；READ 打开不存在的库是调用方 bug，应尽早暴露 |
| D6 | READ 连接不执行 `PRAGMA journal_mode=WAL`（只读模式下切换 journal mode 会报错）；保留 `busy_timeout` 与 `foreign_keys` | WAL 由写入方（admin/写连接）设置并持久化在文件头，只读连接直接受益 |
| D7 | `CostView/api/config.py` 的 `DATA_DIR` 改为从 `DataPipeline.config.Config` 派生 | 消除双真相源（ADR-0012） |
| D8 | `scripts/ops/` 运维脚本直接 `sqlite3.connect` 的写入路径**本次不重构** | 它们是合法的维护/回填工具（写方），G3 充分且必要——强行收口属另一任务 |

## 任务

| # | 内容 | 文件 | 状态 |
|---|------|------|------|
| T1 | `Config.DATA_DIR` 默认外置（`~/EMSXViewData/data`）+ 旧目录数据遗留 WARNING | `DataPipeline/config.py` | ✅ |
| T2 | `CostView/api/config.py` DATA_DIR 从 `DataPipeline.config` 派生 | `CostView/api/config.py` | ✅ |
| T3 | 迁移脚本（预检 → 复制 + 行数/体积校验 → 原目录改名 `data.migrated.<ts>` → 重入保护） | `scripts/ops/migrate_data_dir.py` | ✅ |
| T4 | READ tier 真只读（mode=ro + 不建文件 + 不切 WAL） | `DataPipeline/storage/connection.py` | ✅ |
| T5 | 单元测试：config 默认值/优先级、READ 只读拒写/拒建文件、迁移脚本幂等 | `DataPipeline/tests/` | ✅ |
| T6 | 文档：QUICKSTART、AGENTS.md/CODEBUDDY.md 数据目录段落、ADR-0016 | docs + 根文档 | ✅ |

## P2 三性齐备（每步开工前核对）

- T1/T2 理论：单真相源派生，环境变量覆盖优先级不变；技术：`Path.home()` + os.getenv；检验：单测断言默认值 + `EMSXVIEW_DATA_DIR` 覆盖生效。
- T3 理论：复制后校验（文件级体积 + 逐库 PRAGMA integrity_check + 关键表行数对比）；技术：shutil.copy2 + sqlite3 校验；检验：脚本自检 + 人工在真实库上跑 `--dry-run`。
- T4 理论：SQLite URI `mode=ro` 由文件系统层面拒绝写操作；技术：uri=True + pathname2url 处理 Windows 路径；检验：单测断言 READ 连接 INSERT 抛 `readonly database`、打开不存在路径抛 `unable to open`。

## P3 回退路径

- 代码回退：本分支单 PR revert 即回到项目内默认。
- 数据回退：迁移脚本仅复制不删除，原目录改名保留（`data.migrated.<ts>`），确认无误后人工清理；`EMSXVIEW_DATA_DIR` 指回原目录立即恢复旧行为。

## P4 改动-需求双向矩阵

| 需求（用户任务） | 改动覆盖 |
|---|---|
| 迁移数据库到项目外 | T1（默认外置）+ T2（统一派生）+ T3（迁移脚本）+ T6（文档） |
| 分离更新维护数据库和读取数据库 | T4（READ 真只读；写方维持 WRITE/admin，管道 = 唯一写入方）+ T6（ADR 记录职责边界） |
