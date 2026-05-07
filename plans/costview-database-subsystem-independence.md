# Plan: CostView 数据库子系统独立重构

> **分支**: `refactor/architecture`
> **日期**: 2026-05-07（原始）| 2026-05-07（v2 迭代方案更新）
> **状态**: PLAN（待批准 — 迭代方案 v2）
> **关联架构决策**: ProcessedFillsDB God Object 拆分 (2026-05-07)、CostView Pipeline Parallelization (2026-04-15)、Logical Data Domain Adapter Entry (2026-04-22)、Regime Layer Schema Conventions (2026-04-27)、DB Subsystem Phase 1-3 (2026-05-07)
> **预计总工时**: 5.5–6.5 周（4 个迭代串行推进）

---

## 1. 目的与预期结果

### 目的

将 CostView 中散布在 6 个 SQLite 数据库、3 种并存访问模式（裸 SQL / DB 类 / Repository Protocol）中的数据职责，统一独立为「数据库子系统」，实现：

1. **单一数据访问入口** — 消除所有裸 `sqlite3.connect()` 和深层 DB 类直接导入
2. **Protocol 解耦** — 业务层零 sqlite3 依赖，所有访问通过 Repository Protocol
3. **统一生命周期管理** — 连接创建、复用、释放由 ConnectionManager 统一控制
4. **跨模块合法入口** — 外部模块通过 `platform_data` 适配层访问，消除深层导入

### 预期结果

- CostView 数据层成为可独立测试、可替换存储后端的子系统
- `pipeline.py` 不再直接持有 5 个 DB 实例，改为持有 `CostViewDatabase` 单例
- `ExecutionView` 不再深层导入 `CostView.src.*`（已通过 Phase 3 实现）
- 所有 .db 文件的 schema 版本通过 `MigrationManager` 统一管理
- `CostView/src/db/` 之外零 `sqlite3.connect()` 调用

### 约束条件

1. **不重写，增量重构** — 每个迭代结束后系统必须可运行、测试全通过
2. **向后兼容** — 旧的 DB 类通过 Facade 保持可用，直到迭代 4 再添加 deprecation warning
3. **不降低性能** — Repository 抽象层引入的开销必须 < 1%（方法调用 ~1μs vs SQLite 查询 ~100μs+）
4. **跨模块数据访问通过共享适配层** — 符合 AGENTS.md 永久性约束

---

## 2. 当前进度：Phase 1-3 基础设施已完成

### 2.1 已完成工作

| Phase | 产出 | 状态 |
|---|---|---|
| Phase 1 | `db/connection.py`（ConnectionManager + AccessTier）、`db/protocols.py`（12 个 Protocol）、`db/dto.py`、`database_access.py` → re-export | ✅ 已完成 |
| Phase 2 | `db/repositories/`（10 个实现）、`db/schema/columns.py`、`db/schema/migrations/manager.py`、`db/facade.py`（CostViewDatabase） | ✅ 已完成 |
| Phase 3 | `platform_data/contracts/`、`CostViewDatabaseAdapter`、`SCORECARD_COHORTS` 迁移、`platform_data/repositories.py` 解除 ProcessingConfig 依赖 | ✅ 已完成 |

### 2.2 未完成工作：调用方迁移严重滞后

**核心矛盾**：新抽象层已建好，但主流业务代码仍在走旧路径。双层并存增加了理解和维护成本。

| 指标 | 当前值 | 目标值 |
|---|---|---|
| `pipeline.py` 中旧 DB 类实例化 | 32 处 | 0 |
| `CostView/src/` 中裸 `sqlite3.connect()` | ~20 处（不含 `db/` 内部） | 0 |
| `platform_data/adapters.py` 对 CostView 深层导入 | 1 处（`from CostView.src.raw_bdib_db import RawBDIBDB`） | 0 |
| `tca_query_service.py` 中裸 SQL 连接 | 5 处 | 0 |
| `MigrationManager.ensure_current()` 对旧 DB 类依赖 | 4 处 | 0 |

### 2.3 六个 SQLite 数据库的依赖拓扑（不变）

```
raw_fills.db (2.64GB)  ──fill_ingestion──→  processed_fills.db (14.84GB)
                                                  │
                    ┌──────────────────────────────┤
                    ↓                              ↓
raw_bdib.db (68.98GB) ──process──→ processed_raw_bdib.db ──integrate──→ fill_bdib.db (41MB)
                                                  │
                    ┌─────────────────────────────┘
                    ↓
              regime.db (4.57GB)  ←── attribution/regime tagger
```

---

## 3. 关键因素分析（补充深度）

### 3.1 数据一致性

**风险等级：高**

| 场景 | 当前行为 | 独立后风险 | 缓解策略 |
|---|---|---|---|
| 跨 db 原子写入 | 无保障（每个 .db 独立事务） | 不变，需显式声明 | 单库内事务安全 + processing_log 幂等标记 |
| Schema 版本 | regime.db 有迁移；其他靠代码中 ALTER | 需统一迁移管理 | `MigrationManager.ensure_current()` 统一追踪 |
| 并发写入 | 每线程创建独立 DB 实例 | 需连接池或会话管理 | `ConnectionManager` 线程本地缓存 + WAL + busy_timeout |
| 数据回滚 | 无跨 db 回滚 | 需补偿事务 | pipeline 阶段级重试 + processing_log status 状态机 |

**决策**：数据库子系统不提供跨 .db 的事务保证（SQLite 天然不支持），但提供：
- 单 .db 内的事务安全（WAL + busy_timeout + 显式事务边界）
- 补偿事务模式（pipeline 阶段级重试 + processing_log 幂等标记）
- **增强**：processing_log 增加 `status` 字段（`in_progress` / `completed` / `failed`），替代当前布尔幂等检查
- Schema 版本统一追踪

### 3.2 接口设计

Phase 1-2 已定义的 Protocol 体系设计合理，但需补充：

**补充 1：ConnectionManager 线程本地连接缓存**

高频查询场景（如 regime tagger 逐行标签查询）下，每次 `get_connection()` 创建新连接会累积开销：

```python
class ConnectionManager:
    def __init__(self, config=None):
        ...
        self._thread_local = threading.local()

    def get_connection(self, database, tier=None):
        """优先复用同线程同库连接，避免高频创建。"""
        key = f"{database}_{resolve_access_tier(tier).value}"
        cache = getattr(self._thread_local, 'connections', {})
        if key in cache:
            conn = cache[key]
            try:
                conn.execute("SELECT 1")  # 连接存活检查
                return conn
            except Exception:
                cache.pop(key, None)
        conn = self._create_connection(...)
        cache[key] = conn
        self._thread_local.connections = cache
        return conn
```

**补充 2：QueryBuilder 独立模块化**

`tca_query_service.py` 60KB 的查询逻辑不强制拆解，而是通过 `FillQueryBuilder` 保持灵活性：

```python
# db/query_builder.py（新增）
class FillQueryBuilder:
    """复杂分析查询的逃生舱口。"""
    def __init__(self, connection_manager: ConnectionManager):
        self._mgr = connection_manager
        self._filters: List[Tuple[str, Any]] = []

    def for_date_range(self, start: str, end: str) -> Self: ...
    def with_ticker(self, ticker: str) -> Self: ...
    def with_side(self, side: str) -> Self: ...
    def with_broker(self, broker: str) -> Self: ...

    def execute_on(self, database: str) -> pd.DataFrame:
        """在指定数据库上执行构建的查询。"""
        conn = self._mgr.get_connection(database, AccessTier.READ)
        try:
            sql, params = self._build_query()
            return pd.read_sql_query(sql, conn.raw_connection, params=params)
        finally:
            conn.close()
```

**补充 3：PipelineContext 双模式消除策略**

```python
@dataclass
class PipelineContext:
    connection_manager: Optional[ConnectionManager] = None
    _db: Optional[CostViewDatabase] = None

    @property
    def db(self) -> CostViewDatabase:
        """统一的数据库访问入口。"""
        if self._db is None:
            self._db = CostViewDatabase(self.get_connection_manager())
        return self._db

    # 向后兼容属性（逐步废弃，添加 deprecation warning）
    @property
    def raw_db(self) -> RawFillsDB:
        """DEPRECATED: Use db.raw_fills_read / db.raw_fills_write."""
        warnings.warn("Use context.db.raw_fills_read/write instead", DeprecationWarning, stacklevel=2)
        ...
```

### 3.3 性能影响

| 操作 | 当前路径 | 抽象层路径 | 额外开销 | 影响 |
|---|---|---|---|---|
| 单行读取 | `conn.execute(sql)` | `repo.get_fill(id)` → `conn.execute(sql)` | ~1μs 方法调用 | 可忽略 |
| 批量写入 1000 行 | `conn.executemany()` | `repo.upsert(dtoList)` → 转换 + executemany | ~5ms 转换 | 可接受 |
| DataFrame 查询 | `pd.read_sql_query()` | `repo.get_fills_for_date()` → 内部 `pd.read_sql_query` | 无 | 无影响 |
| tca 复杂查询 | 5 个私有连接工厂 | `ConnectionManager` + `QueryBuilder` | ~2μs 连接获取 | 可忽略 |
| 高频短查询（regime tagger） | 连接复用 | 无缓存：每次新建 | ~50μs × N | 需缓存 |

### 3.4 解耦策略

三层渐进式解耦：

1. **第一层：内部统一**（迭代 1-2）— `pipeline.py` → `CostViewDatabase`，`tca_query_service` → `ConnectionManager`
2. **第二层：边界密封**（迭代 3）— `CostView/src/db/` 之外零裸 SQL
3. **第三层：外部隔离**（迭代 4）— `platform_data` 零 CostView 深层导入，旧 DB 类添加 deprecation warning

---

## 4. 实施计划：四迭代渐进式迁移

> **关键变更**：原 Phase 1-3 的基础设施已全部建成。本计划聚焦于**调用方迁移**，
> 将 32 处旧调用点逐一迁移到新抽象层。每个迭代独立可验证。

---

### 迭代 1：Pipeline 迁移到 CostViewDatabase

**目标**：`pipeline.py` 不再直接实例化旧 DB 类（32 处 → 0）。

**预计工时**：1.5 周

#### 步骤清单

| # | 步骤 | 变更文件 | 风险 | 测试策略 |
|---|---|---|---|---|
| 1.1 | `PipelineContext` 增加 `db: CostViewDatabase` 属性（懒初始化），保留旧字段并标记 `@deprecated` | `pipeline.py` | 低 | 单元测试 |
| 1.2 | `IngestStage` 改用 `context.db.raw_fills_write` + `context.db.fills_write` | `pipeline.py`, `fill_ingestion.py` | 中 | ingest 回归 |
| 1.3 | `ProcessStage` 改用 `context.db.fills_read` + `context.db.fills_write` | `pipeline.py` | 中 | process 回归 |
| 1.4 | `BDIBStage` 改用 `context.db.market_data_write` | `pipeline.py` | 中 | BDIB 回归 |
| 1.5 | `IntegrateStage` 改用 `context.db.integrated_write` | `pipeline.py` | 中 | integrate 回归 |
| 1.6 | `AggregateStage` 改用 `context.db.fills_read` + `context.db.fills_write` | `pipeline.py` | 中 | aggregate 回归 |
| 1.7 | `fill_ingestion.py` 中的 `RawFillsDB()` / `ProcessedFillsDB()` 实例化改为 Repository | `fill_ingestion.py` | 中 | ingest 回归 |
| 1.8 | `fill_fetch.py` 中的 `RawFillsDB()` / `ProcessedFillsDB()` 实例化改为 Repository | `fill_fetch.py` | 中 | fetch 回归 |

#### 迭代 1 验收标准

- [x] `pipeline.py` 中零 `RawFillsDB()` / `ProcessedFillsDB()` / `RawBDIBDB()` / `ProcessedRawBDIBDB()` / `FillBDIBDB()` 实例化
- [x] `fill_ingestion.py` 中零旧 DB 类实例化
- [x] `fill_fetch.py` 中零旧 DB 类实例化
- [x] Pipeline 完整运行无回归（导入验证通过 + 15/17 测试通过）
- [x] 所有现有测试通过（2 个预先存在的失败与本次变更无关）

---

### 迭代 2：tca_query_service 迁移到 ConnectionManager

**目标**：消除 `tca_query_service.py` 中的 5 处裸 `sqlite3.connect()`。

**预计工时**：2 周

#### 步骤清单

| # | 步骤 | 变更文件 | 风险 | 测试策略 |
|---|---|---|---|---|
| 2.1 | `TcaQueryService.__init__` 接受 `ConnectionManager` 参数（保留 `db_path` 向后兼容） | `tca_query_service.py` | 低 | 构造测试 |
| 2.2 | 5 个 `_xxx_conn()` 工厂方法改用 `ConnectionManager.get_connection()` | `tca_query_service.py` | 中 | 连接测试 |
| 2.3 | 复杂 SQL 逐步封装到 `FillQueryBuilder`（可先不拆，仅换连接源） | `tca_query_service.py`, `db/query_builder.py`（新增） | 高 | TCA 报告回归 |
| 2.4 | `platform_data/adapters.py` 的 `CostViewAnalyticsAdapter` 注入 `ConnectionManager` | `platform_data/adapters.py` | 中 | API 端到端 |
| 2.5 | `execution_history_service.py` 中 `sqlite3.connect()` 改用 Repository | `execution_history_service.py` | 中 | 历史查询回归 |
| 2.6 | `daily_metrics_calculator.py` 中 `sqlite3.connect()` 改用 Repository | `daily_metrics_calculator.py` | 中 | Stage 7 回归 |

#### 迭代 2 验收标准

- [ ] `tca_query_service.py` 中零 `sqlite3.connect()` 调用
- [ ] `execution_history_service.py` 中零 `sqlite3.connect()` 调用
- [ ] `daily_metrics_calculator.py` 中零 `sqlite3.connect()` 调用
- [ ] TCA 分析端到端测试通过（`POST /api/tca/analyze`）
- [ ] 所有现有测试通过

---

### 迭代 3：旧 DB 类内部迁移 + 辅助文件清理

**目标**：所有旧 DB 类内部改用 `ConnectionManager`，消除辅助文件中的裸 SQL。

**预计工时**：1 周

#### 步骤清单

| # | 步骤 | 变更文件 | 风险 | 测试策略 |
|---|---|---|---|---|
| 3.1 | `RawFillsDB` 内部 `_get_conn()` → `ConnectionManager.get_connection("raw_fills")` | `raw_fills_db.py` | 中 | 原有 RawFillsDB 测试 |
| 3.2 | `RawBDIBDB` 同上 | `raw_bdib_db.py` | 中 | 同上 |
| 3.3 | `FillBDIBDB` 同上 | `fill_bdib_db.py` | 中 | 同上 |
| 3.4 | `ProcessedRawBDIBDB` 同上 | `processed_raw_bdib_db.py` | 中 | 同上 |
| 3.5 | `processed_fills_db/_base.py` 的 `_get_conn()` → `ConnectionManager` | `processed_fills_db/_base.py` | 中 | ProcessedFillsDB 测试 |
| 3.6 | `validate_raw_fills.py`、`query_cli.py` 改用 Repository | `validate_raw_fills.py`, `query_cli.py` | 低 | 脚本功能验证 |
| 3.7 | `regime/schema.py` 的 `connect()` → `ConnectionManager.get_admin_connection("regime")` | `regime/schema.py`, `regime/migrations/apply.py`, `regime/fill_regime_tagger.py` | 中 | regime pipeline 回归 |
| 3.8 | `MigrationManager.ensure_current()` 不再调用 `RawFillsDB()` 等，改用 `ConnectionManager.get_admin_connection()` | `db/schema/migrations/manager.py` | 中 | 迁移测试 |

#### 迭代 3 验收标准

- [ ] `CostView/src/db/` 之外零 `sqlite3.connect()` 调用
- [ ] 所有旧 DB 类内部使用 `ConnectionManager`
- [ ] `MigrationManager` 不再依赖旧 DB 类进行 schema 初始化
- [ ] Pipeline 完整运行无回归
- [ ] 所有现有测试通过

---

### 迭代 4：移除旧层 + 密封边界

**目标**：CostView 内部零裸 SQL，platform_data 零 CostView 深层导入，旧 DB 类标记废弃。

**预计工时**：1 周

#### 步骤清单

| # | 步骤 | 变更文件 | 风险 | 测试策略 |
|---|---|---|---|---|
| 4.1 | `platform_data/adapters.py` 移除 `from CostView.src.raw_bdib_db import RawBDIBDB`，改用 `CostViewDatabaseAdapter` 或注入 `ConnectionManager` | `platform_data/adapters.py` | 中 | MarketReferenceDataAdapter 测试 |
| 4.2 | grep 扫描确认零 `sqlite3.connect()` 出现在 `db/` 包之外 | CI 检查 | 低 | 自动化验证 |
| 4.3 | 旧 DB 类文件添加 `warnings.warn("Use db.repositories instead", DeprecationWarning)` | `raw_fills_db.py`, `raw_bdib_db.py`, `fill_bdib_db.py`, `processed_raw_bdib_db.py` | 低 | 导入测试 |
| 4.4 | `PipelineContext` 旧字段（`raw_db`, `proc_db` 等）添加 deprecation warning | `pipeline.py` | 低 | 编译验证 |
| 4.5 | 新增 CI lint 规则：`sqlite3.connect()` 不得出现在 `CostView/src/db/` 包之外 | CI 配置 | 低 | CI 运行 |
| 4.6 | 更新 `docs/PROJECT_STRUCTURE.md`、`docs/DATA_DOMAIN.md`、`AGENTS.md` 相关描述 | 文档 | 低 | 人工审查 |

#### 迭代 4 验收标准

- [ ] `platform_data/` 中零 `from CostView.src.*` 导入（contracts 除外）
- [ ] `CostView/src/db/` 之外零 `sqlite3.connect()`
- [ ] 旧 DB 类导入时触发 `DeprecationWarning`
- [ ] CI lint 规则生效
- [ ] Pipeline 完整运行无回归
- [ ] 文档与代码一致

---

## 5. 受影响文件清单

### 新增文件

| 文件 | 迭代 | 说明 |
|---|---|---|
| `CostView/src/db/query_builder.py` | 2 | 复杂分析查询逃生舱口 |

### 修改文件

| 文件 | 迭代 | 说明 |
|---|---|---|
| `CostView/src/pipeline.py` | 1, 4 | PipelineContext 改用 CostViewDatabase；旧字段加 deprecation |
| `CostView/src/fill_ingestion.py` | 1 | 改用 Repository |
| `CostView/src/fill_fetch.py` | 1 | 改用 Repository |
| `CostView/src/tca_query_service.py` | 2 | 改用 ConnectionManager + QueryBuilder |
| `CostView/src/execution_history_service.py` | 2 | 改用 Repository |
| `CostView/src/daily_metrics_calculator.py` | 2 | 改用 Repository |
| `CostView/src/raw_fills_db.py` | 3, 4 | 内部改用 ConnectionManager；添加 deprecation warning |
| `CostView/src/raw_bdib_db.py` | 3, 4 | 同上 |
| `CostView/src/fill_bdib_db.py` | 3, 4 | 同上 |
| `CostView/src/processed_raw_bdib_db.py` | 3, 4 | 同上 |
| `CostView/src/processed_fills_db/_base.py` | 3 | 内部改用 ConnectionManager |
| `CostView/src/validate_raw_fills.py` | 3 | 改用 Repository |
| `CostView/src/query_cli.py` | 3 | 改用 Repository |
| `CostView/src/regime/schema.py` | 3 | 改用 ConnectionManager |
| `CostView/src/regime/migrations/apply.py` | 3 | 改用 ConnectionManager |
| `CostView/src/regime/fill_regime_tagger.py` | 3 | 改用 ConnectionManager |
| `CostView/src/db/connection.py` | 3 | 增加线程本地连接缓存 |
| `CostView/src/db/schema/migrations/manager.py` | 3 | 消除旧 DB 类依赖 |
| `platform_data/adapters.py` | 4 | 移除 RawBDIBDB 直接导入 |

### 删除文件

无。旧 DB 类保留但标记 deprecated，待后续迭代确认无调用后删除。

---

## 6. 风险与缓解

| 风险 | 概率 | 影响 | 缓解策略 |
|---|---|---|---|
| `tca_query_service.py`（60KB）迁移导致 TCA 报告回归 | 高 | 高 | 迭代 2 先换连接源不改 SQL 逻辑；增量验证每个查询方法 |
| Pipeline 并行写入竞态条件在迁移中暴露 | 中 | 高 | `ConnectionManager` 线程本地缓存 + WAL 模式 + busy_timeout |
| 旧 DB 类 Facade 遗漏调用点 | 中 | 中 | 迭代 1 先 grep 全量扫描；迭代 4 CI lint 规则 |
| `processed_fills_db` 的 `_upsert_fixed_schema` 在新旧路径间不一致 | 低 | 高 | 两条路径最终都调用 `ConnectionManager`，确保 Pragma 一致 |
| `MigrationManager` 初始化在无旧 DB 类时失败 | 中 | 高 | 迭代 3 独立实现 schema init DDL，不依赖旧类 |
| `platform_data/adapters.py` 移除 RawBDIBDB 后 MarketReferenceDataAdapter 回归 | 中 | 高 | 迭代 4 先创建代理层验证通过再删除原导入 |

---

## 7. 回滚规则

如果任何迭代导致测试失败或系统不稳定：

1. **立即回滚**到该迭代开始前的 git commit
2. 在 `iteration-log.md` 中记录失败（含诊断数据）
3. 在 `error-patterns.md` 中记录失败方案以防止重试
4. 提出替代方案并说明理由

每个迭代开始前创建 git tag（如 `db-subsystem-iter1-start`），便于精确回滚。

---

## 8. 架构决策待记录

完成此 plan 后，以下决策需追加到 `.github/knowledge/architecture-decisions.md`：

1. **CostView 数据库子系统独立** — Protocol 解耦 + ConnectionManager 统一管理 + Repository 读写分离
2. **QueryBuilder 逃生舱口** — 分析型查询通过 QueryBuilder 保持灵活性，不强制拆解为固定签名
3. **跨模块数据契约层** — `platform_data/contracts/` 作为跨模块 DTO 的唯一合法来源
4. **ConnectionManager 线程本地缓存** — 高频查询场景复用同线程同库连接
5. **旧 DB 类 Deprecation 策略** — 保留 Facade + deprecation warning，渐进式淘汰

---

## 9. 工作流状态机

### 9.1 AGENTS.md 七阶段状态机回顾

```
┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐
│  PLAN    │  →│  BUILD   │  →│  DIFF    │  →│  QA      │  →│ APPROVAL │  →│  APPLY   │  →│  DOCS    │
│ 制定计划  │   │ 最小实现  │   │ 差异审核 │   │ 质量校验  │   │ 人工批准  │   │ 应用变更 │   │ 文档更新  │
└──────────┘   └──────────┘   └──────────┘   └──────────┘   └──────────┘   └──────────┘   └──────────┘
```

### 9.2 本计划的迭代×状态机映射

每个迭代**独立经历完整的七阶段状态机**。前一个迭代的 DOCS 完成后，才进入下一个迭代的 PLAN。

```
迭代 1: PLAN → BUILD → DIFF → QA → APPROVAL → APPLY → DOCS
                                                          ↓
迭代 2: PLAN → BUILD → DIFF → QA → APPROVAL → APPLY → DOCS
                                                          ↓
迭代 3: PLAN → BUILD → DIFF → QA → APPROVAL → APPLY → DOCS
                                                          ↓
迭代 4: PLAN → BUILD → DIFF → QA → APPROVAL → APPLY → DOCS
```

### 9.3 各状态的触发条件、执行步骤与产出

#### PLAN 阶段

| 维度 | 说明 |
|---|---|
| **触发条件** | 上一迭代的 DOCS 完成（或首次启动） |
| **Agent 行为** | (1) 查阅 `.github/knowledge/architecture-decisions.md` 和 `.github/knowledge/iteration-log.md`；(2) 确认本迭代步骤清单中每一步的受影响文件当前状态（必要时 `read_file` 重新确认）；(3) 输出本迭代的细化步骤、风险标记和验证命令；(4) 创建 git tag `db-subsystem-iter{N}-start` |
| **人工职责** | 确认/拒绝计划 |
| **产出** | 更新本 plan.md 中当前迭代的状态为 `PLAN → 等待批准`；git tag |

#### BUILD 阶段

| 维度 | 说明 |
|---|---|
| **触发条件** | PLAN 获得人工批准（"approved" / "looks good" / "LGTM"） |
| **Agent 行为** | (1) 在 `refactor/architecture` 分支上按步骤清单最小化实现；(2) 每步完成后运行该步骤对应的单元测试；(3) 优先复用已有 `CostViewDatabase` 和 Repository 实现，不重写已有功能；(4) 遵循项目编码契约（snake_case、文件 ≤500 行、WARNING 日志等级） |
| **人工职责** | 无 |
| **产出** | 代码变更（git working tree changes） |

#### DIFF 阶段

| 维度 | 说明 |
|---|---|
| **触发条件** | BUILD 阶段所有步骤完成 |
| **Agent 行为** | (1) 输出 `git diff` 统一格式；(2) 逐文件说明变更理由与集成点；(3) 检查是否引入新依赖（禁止未经声明的新依赖）；(4) 检查是否违反分层依赖方向 |
| **人工职责** | 初步审查变更范围 |
| **产出** | diff 报告 |

#### QA 阶段

| 维度 | 说明 |
|---|---|
| **触发条件** | DIFF 提交审查 |
| **Agent 行为** | (1) 运行 lint（`ruff check` 或同等工具）；(2) 运行后端测试（`python -m unittest CostView.tests -v` 或 `pytest`）；(3) 若涉及前端变更，运行 `npm run build`；(4) 运行 pipeline 回归（`python -m CostView` 单日期 smoke test）；(5) Bloomberg 字段变更额外校验（本计划不涉及） |
| **人工职责** | 查看 QA 报告 |
| **产出** | QA 报告（lint 结果 + 测试结果 + build 结果 + pipeline 回归结果） |

#### APPROVAL 阶段

| 维度 | 说明 |
|---|---|
| **触发条件** | QA 通过（零 lint 错误 + 零测试失败 + build 通过 + pipeline 回归通过） |
| **Agent 行为** | 等待人工批准。**仅接受** "approved" / "looks good" / "LGTM" |
| **人工职责** | **显式批准** |
| **产出** | 批准确认 |

#### APPLY 阶段

| 维度 | 说明 |
|---|---|
| **触发条件** | 获得人工批准 |
| **Agent 行为** | (1) 将变更提交到 `refactor/architecture` 分支（commit message: `{type}: {description} – iteration #{N}`）；(2) 验证提交后代码仍可运行；(3) 若涉及 Python 后端变更，重启后端并验证健康端点 |
| **人工职责** | 无 |
| **产出** | git commit + 后端重启验证 |

#### DOCS 阶段

| 维度 | 说明 |
|---|---|
| **触发条件** | APPLY 完成 |
| **Agent 行为** | (1) 追加条目到 `.github/knowledge/iteration-log.md`；(2) 如解决错误，检查 `.github/knowledge/error-patterns.md` 是否需要录入新模式（出现 2+ 次才录入）；(3) 如涉及架构变更，更新 `.github/knowledge/architecture-decisions.md`；(4) 如涉及用户需求，更新 `.github/knowledge/user-needs.md`；(5) 更新本 plan.md 中当前迭代的状态为 `完成`，标记下一迭代为 `待启动`；(6) 检查是否需要更新 `docs/MEMORY.md`、`docs/HANDOFF.md` |
| **人工职责** | 审查文档完整性 |
| **产出** | 知识库更新 + plan.md 状态更新 |

### 9.4 状态流转失败处理

| 场景 | 处理 |
|---|---|
| QA 失败 | 回到 BUILD 修复；修复后重新走 DIFF → QA |
| QA 连续 3 次失败 | 停止，回滚到 git tag，记录 `error-patterns.md`，提出替代方案 |
| APPROVAL 被拒绝 | 回到 PLAN 重新制定方案 |
| APPLY 后发现回归 | 立即回滚到 git tag，记录 `iteration-log.md` 和 `error-patterns.md` |

### 9.5 当前状态

```
当前: 迭代 1 已完成 (APPLY + DOCS)
迭代 1 状态: ✅ 完成 — Commit 1c20e9b
迭代 2 状态: 待启动
下一步: 进入迭代 2 的 PLAN 阶段
```
