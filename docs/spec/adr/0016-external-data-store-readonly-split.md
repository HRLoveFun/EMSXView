# ADR-0016: 数据目录外置项目外 + 读写职责物理分离

> 状态: Accepted
> 日期: 2026-09-02
> 标签: data, storage, sqlite, configuration, refactoring
> 特性: specs/009-external-data-store（分支 `009-external-data-store`）

## 背景 (Context)

1. **数据错放项目内**：SQLite 数据库默认位于 `{PROJECT_ROOT}/CostView/data`，与代码同仓同目录：
   - worktree 场景（ADR-0700）：每个 worktree 的 `CostView/data` 为空，需手工 `EMSXVIEW_DATA_DIR` 指向主树；
   - 备份/清理/归档等维护操作容易误触代码仓库文件树；
   - 重新 clone 后数据"消失"，排查成本高。
2. **读写未物理分离**：`ConnectionManager.AccessTier.READ/WRITE` 仅做 SQL 文本分类拦截，
   可被 `raw_connection` 绕过；底层 `sqlite3.connect()` 统一以可写模式打开——
   读取方（CostView API / monitoring / tca_query）进程的 bug 仍可能写坏数据文件，
   违背 G0 数据零受损精神。
3. **双真相源残留**：`CostView/api/config.py` 自行计算 `DATA_DIR` 默认值，未从
   `DataPipeline.config` 派生（ADR-0012 违例点）。

## 决策 (Decision)

1. **数据目录外置**（`DataPipeline/config.py`）：
   - 解析优先级：`EMSXVIEW_DATA_DIR` 环境变量（显式覆盖）> **默认值 `~/EMSXViewData/data`**（项目外，`Path.home()` 派生）；
   - 旧布局 `CostView/data` 仅在显式设置环境变量指回时生效；
   - 旧目录仍有 `*.db` 且走外置默认时，import 期发 `UserWarning` 提示迁移（fail-visible 不 fail-hard）；
   - 迁移**显式执行**：`scripts/ops/migrate_data_dir.py`（三道安全闸：预检 → 复制 + `PRAGMA quick_check` 校验 → 原目录改名 `data.migrated.<ts>` 留证；幂等可重入）。
2. **READ tier 文件级只读**（`DataPipeline/storage/connection.py`）：
   - READ 连接以 SQLite URI `mode=ro` 打开——文件系统层面拒绝写操作，
     即使经 `raw_connection` 绕过 SQL 拦截也无法写坏数据；
   - READ 连接**不创建**不存在的库（缺失抛 `FileNotFoundError`，fail-fast 防误建空库）；
     优雅降级方（TCA 报告 / monitoring / tca_bridge）自行捕获并回退为空结果；
   - READ 连接不执行 `PRAGMA journal_mode=WAL`（由写入方设置并持久化在文件头）；
   - 写入方维持 WRITE tier（WAL）与 admin 连接（DDL/迁移）——**数据管道与维护脚本 = 唯一写入通道**，
     API/查询/监控进程 = 只读消费者。
3. **消除双真相源**：`CostView/api/config.py` 的 `DATA_DIR` 改为从 `DataPipeline.config.Config` 派生。
4. **运维脚本豁免**：`scripts/ops/*` 回填与运维工具直接 `sqlite3.connect` 属合法维护（写方）通道，本次不收口。

## 后果 (Consequences)

### 正面
- 数据与代码树解耦：重新 clone / worktree / 部署不再"数据消失"；备份维护不触碰仓库。
- 读取方数据损坏风险从"SQL 拦截靠自觉"收敛为"文件系统物理不可能"（G0 强化）。
- READ fail-fast 使"静默空库掩盖数据缺失"类问题在连接期即暴露。
- 配置真相源唯一（ADR-0012 补完）。

### 负面 / 取舍
- 已有部署需**显式执行一次迁移脚本**（或设置 `EMSXVIEW_DATA_DIR` 指回旧目录）；
- READ 打开缺失库抛 `FileNotFoundError` 是行为变化，调用方须有降级（本次已收口 TCA/monitoring/tca_bridge）；
- 依赖"隐式建空库"的低保真测试需自建库或 skip（本次已修：test_pipeline_stages / test_fill_aggregator_no_mult / test_data_quality）。

## 备选方案 (Considered Alternatives)

- 方案 A: 默认值不变，仅文档引导设置 `EMSXVIEW_DATA_DIR`
  - 否决原因: 不构成"迁移到项目外"，每个新环境仍需手工配置。
- 方案 B: Config 解析时自动把旧目录数据迁移到新目录
  - 否决原因: 违背 G0（迁移不可静默）；数十 GB 隐式复制不可接受。
- 方案 C: READ 连接仍可写打开，仅加强 SQL 拦截
  - 否决原因: `raw_connection` 逃逸口仍在，物理只读才是真正防线。

## 相关 ADR

- 引用: [ADR-0012](0012-config-isolation-rule.md)（配置单一来源，本 ADR 补完其默认值并消除残留违例）、[ADR-0700](0700-git-worktree-parallel-workflow.md)（worktree 数据目录约束随之简化）
- 被引用: 无

## 实施注意事项

- 配套迁移: `python scripts/ops/migrate_data_dir.py --dry-run` 预检 → 去掉 `--dry-run` 执行；
- 配套测试: `DataPipeline/tests/storage/test_connection_readonly.py`、`DataPipeline/tests/test_config_data_dir.py`；
- worktree 说明更新见 `docs/spec/git-workflow.md` §6.1。
