# Plan: CostView 数据库子系统独立重构

> **分支**: `refactor/architecture`
> **日期**: 2026-05-07
> **状态**: PLAN（待批准）
> **关联架构决策**: ProcessedFillsDB God Object 拆分 (2026-05-07)、CostView Pipeline Parallelization (2026-04-15)、Logical Data Domain Adapter Entry (2026-04-22)、Regime Layer Schema Conventions (2026-04-27)
> **预计总工时**: 5–8 周（3 个 Phase 串行推进）

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
- `pipeline.py` 不再直接持有 5 个 DB 实例，改为持有 `ConnectionManager` + 注入的 Repository
- `ExecutionView` 不再深层导入 `CostView.src.tca_query_service` 中的常量
- 所有 .db 文件的 schema 版本通过 `MigrationManager` 统一管理

### 约束条件

1. **不重写，增量重构** — 每个 Phase 结束后系统必须可运行、测试全通过
2. **向后兼容** — 旧的 DB 类通过 Facade 保持可用，直到 Phase 3 末期再移除
3. **不降低性能** — Repository 抽象层引入的开销必须 < 1%（方法调用 ~1μs vs SQLite 查询 ~100μs+）
4. **跨模块数据访问通过共享适配层** — 符合 AGENTS.md 永久性约束

---

## 2. 现状诊断

### 2.1 三层访问模式共存

| 层级 | 模式 | 代表文件 | 问题 |
|---|---|---|---|
| L0: 裸 SQL | 直接 `sqlite3.connect()` | `costview.py` 路由(~L437)、`scripts/*.py`、`tca_query_service.py` | 无访问控制、无抽象、无迁移保护 |
| L1: DB 类 | 单一巨型类管理整个 .db | `RawFillsDB`(37KB)、`ProcessedFillsDB`→Facade(46KB→已拆) | DDL+CRUD+业务逻辑混杂（ProcessedFillsDB 已拆分，RawFillsDB 未拆） |
| L2: Repository | Protocol 解耦 + DTO 传输 | `attribution/protocols.py`+`repositories.py`、`processed_fills_db/` 子包 | 最成熟，但仅覆盖 attribution 和 processed_fills 部分 |

### 2.2 六个 SQLite 数据库的依赖拓扑

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

关键问题：`processed_fills.db` 的 `init_processed_fills_schema()` 函数同时定义了 15+ 张表（包括 `ticker_repository`、`equ_ticker_registry` 等被 BDIB 层读取的表），造成 schema 变更时牵一发动全身。

### 2.3 PipelineContext 的紧耦合

```python
# CostView/src/pipeline.py L46-66
@dataclass
class PipelineContext:
    raw_db: Optional[RawFillsDB] = None
    proc_db: Optional[ProcessedFillsDB] = None
    raw_bdib_db: Optional[RawBDIBDB] = None
    processed_raw_bdib_db: Optional[ProcessedRawBDIBDB] = None
    proc_bdib_db: Optional[ProcessedBDIBDB] = None
    # Attribution Repository 注入（解耦后新增，但新旧共存）
    fill_repo: Optional[Any] = None
    bar_repo: Optional[Any] = None
    regime_repo: Optional[Any] = None
    config_repo: Optional[Any] = None
```

新旧两种模式在同一个 `PipelineContext` 中共存，清晰表明重构只完成了一半。

### 2.4 跨模块违规

```
ExecutionView/backend/api/routers/costview.py
  ├── from platform_data import build_platform_data_access     ← 正确：通过共享适配层
  ├── from CostView.src.tca_query_service import SCORECARD_COHORTS  ← 违规：深层导入
  └── sqlite3.connect(str(db_path))                           ← 违规：裸 SQL 访问 regime.db

platform_data/repositories.py
  └── from CostView.src.processing_config import ProcessingConfig  ← 依赖 CostView 配置
```

---

## 3. 关键因素分析

### 3.1 数据一致性

**风险等级：高**

| 场景 | 当前行为 | 独立后风险 |
|---|---|---|
| 跨 db 原子写入 | 无保障（每个 .db 独立事务） | 不变，但需显式声明这一约束 |
| Schema 版本 | `regime.db` 有迁移系统；其他 db 靠代码中 ALTER TABLE | 需统一迁移管理 |
| 并发写入 | 每个线程创建独立 DB 实例 | 需要连接池或会话管理器 |
| 数据回滚 | 无跨 db 回滚机制 | 需在子系统中实现补偿事务 |

**决策**：数据库子系统不提供跨 .db 的事务保证（SQLite 天然不支持），但提供：
- 单 .db 内的事务安全（WAL + busy_timeout + 显式事务边界）
- 补偿事务模式（pipeline 阶段级重试 + processing_log 幂等标记）
- Schema 版本统一追踪

### 3.2 接口设计

**以 `attribution/` 模块的 Protocol + DTO + Repository 三件套为模板推广**：

```python
# 读写分离 Protocol
class FillRepository(Protocol):       # 只读
    def get_fills_for_date(self, yyyymmdd: str) -> pd.DataFrame: ...
    def get_distinct_dates_in_range(self, start: str, end: str) -> List[str]: ...

class FillWriteRepository(Protocol):  # 只写
    def upsert_raw_fills(self, rows: List[RawFillDTO]) -> int: ...
    def upsert_processed_fills(self, rows: List[ProcessedFillDTO]) -> int: ...

# 分析型逃生舱口
class FillRepository(Protocol):
    def get_fills_for_date(self, yyyymmdd: str) -> pd.DataFrame: ...
    def query(self) -> FillQueryBuilder: ...  # 允许复杂查询组合

class FillQueryBuilder:
    def for_date_range(self, start: str, end: str) -> Self: ...
    def with_ticker(self, ticker: str) -> Self: ...
    def execute(self) -> pd.DataFrame: ...
```

理由：
- 读写分离与 `AccessTier` 体系自然对齐
- `QueryBuilder` 保持 SQL 封装在 Repository 层内的同时提供灵活组合能力（tca_query_service 60KB 查询逻辑无法拆解为固定签名方法）

### 3.3 性能影响

| 操作 | 当前路径 | 引入抽象层后 | 额外开销 |
|---|---|---|---|
| 单行读取 | `conn.execute(sql)` | `repo.get_fill(id)` → 内部 `conn.execute(sql)` | 方法调用 ~1μs，可忽略 |
| 批量写入 (1000行) | `conn.executemany(sql, rows)` | `repo.upsert_fills(dtoList)` → 内部转换+executemany | DTO→tuple 转换 ~5ms |
| DataFrame 查询 | `pd.read_sql_query(sql, conn)` | `repo.get_fills_for_date(d)` → 内部 `pd.read_sql_query` | 无额外开销 |

### 3.4 解耦策略

**逐步替换，保持系统可运行**：
1. Phase 1: 新增抽象层，旧代码改为内部使用新层，外部接口不变
2. Phase 2: 逐步迁移调用点到新 Protocol 接口
3. Phase 3: 移除旧代码（仅保留 Facade），跨模块依赖通过 platform_data 消除

---

## 4. 实施计划：三阶段渐进式独立

### Phase 1：统一连接管理 + Protocol 定义

**目标**：消除裸 `sqlite3.connect()`，统一连接生命周期，定义所有 Repository Protocol。

#### 产出文件结构

```
CostView/src/db/
├── __init__.py
├── connection.py         # 从 database_access.py 迁入并增强
│   ├── AccessTier (保留)
│   ├── AccessControlledConnection (保留)
│   ├── ConnectionManager  ← 新增：连接池 + 会话管理
│   └── resolve_access_tier (保留)
├── protocols.py          # 定义所有 Repository Protocol
└── dto.py                # 纯数据传输对象
```

#### 核心设计：ConnectionManager

```python
class ConnectionManager:
    """统一的数据库连接管理器。
    
    职责：
    1. 按数据库名提供受控连接
    2. 管理连接生命周期（创建、复用、释放）
    3. 统一 Pragma 三件套配置
    4. 强制访问层级
    """
    
    def __init__(self, config: Optional[ProcessingConfig] = None):
        self._config = config or ProcessingConfig()
        self._registry: Dict[str, Path] = {
            "raw_fills": self._config.RAW_FILLS_DB,
            "processed_fills": self._config.PROCESSED_FILLS_DB,
            "raw_bdib": self._config.RAW_BDIB_DB,
            "processed_raw_bdib": self._config.PROCESSED_RAW_BDIB_DB,
            "fill_bdib": self._config.FILL_BDIB_DB,
            "regime": self._config.REGIME_DB_PATH,
        }
    
    def get_connection(
        self, database: str, tier: AccessTier = AccessTier.READ
    ) -> AccessControlledConnection: ...
    
    def get_admin_connection(self, database: str) -> sqlite3.Connection: ...
```

#### 步骤清单

| # | 步骤 | 变更文件 | 风险 | 测试策略 |
|---|---|---|---|---|
| 1.1 | 创建 `db/connection.py`，迁入 `database_access.py` 并新增 `ConnectionManager` | 新增 `db/`，删除 `database_access.py` | 中 | 单元测试 `ConnectionManager` |
| 1.2 | 创建 `db/protocols.py` 定义所有 Protocol（6 个读 + 6 个写 + QueryBuilder） | 新增 | 低 | 类型检查通过 |
| 1.3 | 创建 `db/dto.py` 定义纯数据容器 | 新增 | 低 | 数据类测试 |
| 1.4 | 改造 `PipelineContext` 使用 `ConnectionManager` 替代 5 个 DB 实例 | `pipeline.py` | 中 | pipeline 回归测试 |
| 1.5 | 旧 DB 类内部改用 `ConnectionManager` | `raw_fills_db.py` 等 | 中 | 单元测试 |
| 1.6 | 消除 `costview.py` 路由中的裸 SQL | `ExecutionView/backend/api/routers/costview.py` | 高 | API 端到端测试 |
| 1.7 | 更新所有 `from CostView.src.database_access import` 为新路径 | 全局 grep 替换 | 低 | 导入验证 |

#### Phase 1 验收标准

- [ ] 零 `sqlite3.connect()` 出现在 `costview.py` 路由和 `attribution/` 模块中
- [ ] `ConnectionManager` 单元测试通过
- [ ] Pipeline 完整运行无回归
- [ ] 所有旧 DB 类内部使用 `ConnectionManager`

---

### Phase 2：Repository 实现迁移 + Schema 统一管理

**目标**：将所有 DB 类重构为 Repository 实现，统一 schema 管理。

#### 产出文件结构

```
CostView/src/db/
├── ... (Phase 1 文件)
├── repositories/
│   ├── __init__.py
│   ├── fills_read.py         # 对应 FillRepository Protocol
│   ├── fills_write.py        # 对应 FillWriteRepository Protocol
│   ├── market_data_read.py   # 对应 MarketDataRepository Protocol
│   ├── market_data_write.py  # 对应 MarketDataWriteRepository Protocol
│   ├── integrated.py         # 对应 IntegratedRepository Protocol
│   └── regime.py             # 对应 RegimeRepository Protocol（从 attribution/repositories.py 合并）
├── schema/
│   ├── __init__.py
│   ├── columns.py            # 从当前 schema.py 迁入列定义
│   └── migrations/
│       ├── __init__.py
│       ├── manager.py        # 统一迁移管理器
│       ├── raw_fills/
│       ├── processed_fills/
│       ├── raw_bdib/
│       ├── processed_raw_bdib/
│       ├── fill_bdib/
│       └── regime/           # 从 regime/migrations 迁入
└── facade.py                 # 向后兼容的门面
```

#### 关键设计决策

**决策 1：读写分离 Protocol**

```python
class FillRepository(Protocol):       # 只读
    def get_fills_for_date(self, yyyymmdd: str) -> pd.DataFrame: ...

class FillWriteRepository(Protocol):  # 只写
    def upsert_raw_fills(self, rows: List[RawFillDTO]) -> int: ...

class FillAdminRepository(Protocol):  # 仅限维护操作
    def backup_database(self) -> Path: ...
    def rebuild_indexes(self) -> None: ...
```

**决策 2：分析查询的逃生舱口**

```python
class FillRepository(Protocol):
    def get_fills_for_date(self, yyyymmdd: str) -> pd.DataFrame: ...
    def query(self) -> FillQueryBuilder: ...
```

**决策 3：Schema 迁移统一**

```python
class MigrationManager:
    """统一管理所有 .db 文件的 schema 版本和迁移。"""
    SUPPORTED_DATABASES = [
        "raw_fills", "processed_fills", "raw_bdib",
        "processed_raw_bdib", "fill_bdib", "regime"
    ]
    def ensure_current(self, database: str) -> None: ...
    def get_version(self, database: str) -> int: ...
    def apply_pending(self, database: str) -> None: ...
```

#### 步骤清单

| # | 步骤 | 变更文件 | 风险 | 测试策略 |
|---|---|---|---|---|
| 2.1 | 实现 `repositories/fills_read.py` | 新增 | 低 | 对照现有 `ProcessedFillsRepository` + `SqliteFillRepository` |
| 2.2 | 实现 `repositories/fills_write.py` | 新增 | 中 | 写入后读取验证 |
| 2.3 | 实现 `repositories/market_data_*.py` | 新增 | 中 | BDIB pipeline 回归 |
| 2.4 | 实现 `repositories/integrated.py` | 新增 | 中 | fill_bdib 集成测试 |
| 2.5 | 合并 `attribution/repositories.py` → `repositories/regime.py` | 重构 | 高 | attribution 全量测试 |
| 2.6 | 统一 schema 管理 | `schema.py` → `db/schema/` | 高 | 所有 .db 重建验证 |
| 2.7 | 创建 `facade.py` 向后兼容 | 新增 | 低 | Facade 代理测试 |
| 2.8 | 逐文件迁移 pipeline 阶段使用新 Repository | `pipeline.py` | 高 | 全 pipeline 回归 |

#### Phase 2 验收标准

- [ ] 所有 6 个 .db 有对应的 Repository 实现
- [ ] `attribution/` 模块不再直接导入 sqlite3（仅 `repositories/regime.py` 保留 SQL 知识）
- [ ] `MigrationManager` 可追踪所有 .db 的 `user_version`
- [ ] `ProcessedFillsDB` Facade 100% 向后兼容
- [ ] Pipeline 完整运行无回归

---

### Phase 3：跨模块解耦 + 数据子系统独立

**目标**：CostView 数据层成为可独立部署的子系统，通过 `platform_data` 对外暴露。

#### 产出文件结构

```
platform_data/
├── adapters.py                         # 增强
│   ├── CostViewAnalyticsAdapter        # 保留
│   ├── ExecutionOperationalDataAdapter # 保留
│   ├── CostViewDatabaseAdapter         ← 新增：数据库子系统的外部接口
│   └── ...
├── repositories.py                     # 保留（面向 DatabaseView 的诊断查询）
└── contracts/                          ← 新增
    ├── __init__.py
    ├── fill_contracts.py               # FillDTO 的跨模块版本
    ├── market_data_contracts.py
    └── regime_contracts.py
```

#### 关键变更

1. **消除 ExecutionView 对 CostView 的深层导入**：
   - 当前：`from CostView.src.tca_query_service import SCORECARD_COHORTS`
   - 目标：`from platform_data.contracts import SCORECARD_COHORTS`

2. **消除 `costview.py` 路由中的裸 SQL**（如 Phase 1 未完成）：
   - 当前：直接 `sqlite3.connect(str(db_path))` 查询 `regime.db`
   - 目标：通过 `CostViewDatabaseAdapter.get_regime_distribution()` 调用

3. **`platform_data/repositories.py` 解除对 `CostView.src.processing_config` 的依赖**：
   - 将数据库路径配置迁入 `platform_data` 的配置层

#### 步骤清单

| # | 步骤 | 变更文件 | 风险 | 测试策略 |
|---|---|---|---|---|
| 3.1 | 创建 `platform_data/contracts/` | 新增 | 低 | 类型兼容测试 |
| 3.2 | 迁移 `SCORECARD_COHORTS` 到 contracts | `platform_data/`, `tca_query_service.py` | 中 | API 测试 |
| 3.3 | 新增 `CostViewDatabaseAdapter` | `platform_data/adapters.py` | 中 | 集成测试 |
| 3.4 | 消除 `platform_data/repositories.py` 对 `CostView` 的依赖 | `platform_data/` | 高 | 跨模块端到端 |
| 3.5 | 移除旧 DB 类（保留 Facade 用于内部兼容） | 删除 `raw_fills_db.py` 等原始文件 | 高 | 全量回归 |
| 3.6 | 更新 `docs/PROJECT_STRUCTURE.md` 和 `docs/DATA_DOMAIN.md` | 文档 | 低 | 人工审查 |

#### Phase 3 验收标准

- [ ] 零 `from CostView.src.*` 出现在 `ExecutionView/` 中（`platform_data` 除外）
- [ ] `platform_data/repositories.py` 不再依赖 `CostView.src.processing_config`
- [ ] `CostViewDatabaseAdapter` 提供 regime / fills / market data 的只读查询接口
- [ ] Pipeline 完整运行无回归
- [ ] DatabaseView 前端模块正常工作

---

## 5. 受影响文件清单

### 新增文件

| 文件 | Phase | 说明 |
|---|---|---|
| `CostView/src/db/__init__.py` | 1 | 数据库子系统入口 |
| `CostView/src/db/connection.py` | 1 | 连接管理器（从 database_access.py 迁入） |
| `CostView/src/db/protocols.py` | 1 | 所有 Repository Protocol 定义 |
| `CostView/src/db/dto.py` | 1 | 纯数据传输对象 |
| `CostView/src/db/repositories/__init__.py` | 2 | Repository 实现入口 |
| `CostView/src/db/repositories/fills_read.py` | 2 | 填充读取 Repository |
| `CostView/src/db/repositories/fills_write.py` | 2 | 填充写入 Repository |
| `CostView/src/db/repositories/market_data_read.py` | 2 | 市场数据读取 |
| `CostView/src/db/repositories/market_data_write.py` | 2 | 市场数据写入 |
| `CostView/src/db/repositories/integrated.py` | 2 | 集成数据 Repository |
| `CostView/src/db/repositories/regime.py` | 2 | Regime Repository（合并 attribution/） |
| `CostView/src/db/schema/__init__.py` | 2 | Schema 管理入口 |
| `CostView/src/db/schema/columns.py` | 2 | 列定义（从 schema.py 迁入） |
| `CostView/src/db/schema/migrations/manager.py` | 2 | 统一迁移管理器 |
| `CostView/src/db/schema/migrations/{db_name}/*.sql` | 2 | 各 .db 迁移脚本 |
| `CostView/src/db/facade.py` | 2 | 向后兼容 Facade |
| `platform_data/contracts/__init__.py` | 3 | 跨模块契约入口 |
| `platform_data/contracts/fill_contracts.py` | 3 | 填充跨模块 DTO |
| `platform_data/contracts/market_data_contracts.py` | 3 | 市场数据跨模块 DTO |
| `platform_data/contracts/regime_contracts.py` | 3 | Regime 跨模块 DTO |

### 修改文件

| 文件 | Phase | 说明 |
|---|---|---|
| `CostView/src/pipeline.py` | 1, 2 | PipelineContext 改用 ConnectionManager + Repository |
| `CostView/src/raw_fills_db.py` | 1 | 内部改用 ConnectionManager |
| `CostView/src/raw_bdib_db.py` | 1, 2 | 内部改用 ConnectionManager → 迁移到 Repository |
| `CostView/src/processed_fills_db/` | 2 | 子仓库内部改用 ConnectionManager，迁移 DDL 到 schema/ |
| `CostView/src/attribution/repositories.py` | 2 | 合并到 `db/repositories/regime.py` |
| `CostView/src/attribution/__init__.py` | 2 | 更新 Repository 导入路径 |
| `CostView/src/attribution/writer.py` | 2 | 改用新 Repository Protocol |
| `CostView/src/attribution/aggregator.py` | 2 | 改用新 Repository Protocol |
| `CostView/src/attribution/config.py` | 2 | 改用新 Repository Protocol |
| `CostView/src/attribution/recommender.py` | 2 | 改用新 Repository Protocol |
| `CostView/src/attribution/benchmarks.py` | 2 | 已部分解耦，确认完整性 |
| `CostView/src/tca_query_service.py` | 2, 3 | 改用 QueryBuilder；常量迁入 contracts |
| `CostView/src/execution_history_service.py` | 2 | 改用新 Repository |
| `CostView/src/downstream_interface.py` | 2 | 改用新 Repository |
| `CostView/scripts/run_attribution.py` | 2 | 更新 Repository 注入 |
| `ExecutionView/backend/api/routers/costview.py` | 1, 3 | 消除裸 SQL + 消除深层导入 |
| `platform_data/adapters.py` | 3 | 新增 CostViewDatabaseAdapter |
| `platform_data/repositories.py` | 3 | 解除 CostView 依赖 |

### 删除文件

| 文件 | Phase | 说明 |
|---|---|---|
| `CostView/src/database_access.py` | 1 | 迁入 `db/connection.py` |
| `CostView/src/processed_fills_db._legacy_backup.py` | 3 | 清理遗留备份 |
| `CostView/src/raw_fills_db.py`（原始） | 3 | 被 `db/repositories/fills_*.py` + Facade 替代 |
| `CostView/src/raw_bdib_db.py`（原始） | 3 | 被 `db/repositories/market_data_*.py` + Facade 替代 |

---

## 6. 风险与缓解

| 风险 | 概率 | 影响 | 缓解策略 |
|---|---|---|---|
| `tca_query_service.py`（60KB）拆解导致分析逻辑回归 | 高 | 高 | Phase 2 用 `QueryBuilder` 逃生舱口，不强制拆解分析 SQL |
| Pipeline 并行写入的竞态条件在重构中暴露 | 中 | 高 | Phase 1 先统一连接管理，引入 `ConnectionManager` 的线程安全设计 |
| Schema 迁移在多个 .db 间不一致 | 中 | 高 | Phase 2 统一 `MigrationManager`，每个 .db 的 `user_version` 独立追踪 |
| `platform_data` 变更影响 ExecutionView 现有功能 | 低 | 高 | Phase 3 增量迁移，保留旧接口直到新接口完全验证 |
| 旧 DB 类的大量调用点遗漏 | 中 | 中 | Phase 1 先用 grep 扫描所有 `RawFillsDB()`、`ProcessedFillsDB()` 等实例化点 |
| `attribution/repositories.py` 合并到 `db/repositories/regime.py` 引入回归 | 中 | 高 | 先创建 regime.py 作为代理，验证通过后再删除原文件 |

---

## 7. 回滚规则

如果任何 Phase 导致测试失败或系统不稳定：

1. **立即回滚**到该 Phase 开始前的 git commit
2. 在 `iteration-log.md` 中记录失败（含诊断数据）
3. 在 `error-patterns.md` 中记录失败方案以防止重试
4. 提出替代方案并说明理由

每个 Phase 开始前创建 git tag（如 `db-subsystem-phase1-start`），便于精确回滚。

---

## 8. 架构决策待记录

完成此 plan 后，以下决策需追加到 `.github/knowledge/architecture-decisions.md`：

1. **CostView 数据库子系统独立** — Protocol 解耦 + ConnectionManager 统一管理 + Repository 读写分离
2. **QueryBuilder 逃生舱口** — 分析型查询通过 QueryBuilder 保持灵活性，不强制拆解为固定签名
3. **跨模块数据契约层** — `platform_data/contracts/` 作为跨模块 DTO 的唯一合法来源

---

## 9. 工作流状态机位置

```
当前: PLAN → 等待人工批准
下一步: 批准后进入 BUILD (Phase 1)
```

批准后执行顺序：
1. 创建 git tag `db-subsystem-phase1-start`
2. 按 Phase 1 步骤 1.1–1.7 依次实施
3. 每步完成后运行对应测试策略
4. Phase 1 全部完成后进入 DIFF → QA → APPROVAL → APPLY → DOCS
