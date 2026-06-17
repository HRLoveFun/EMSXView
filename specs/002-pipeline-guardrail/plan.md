# Implementation Plan: 数据管道护栏机制

**Branch**: `002-pipeline-guardrail` | **Date**: 2026-06-16 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-pipeline-guardrail/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/plan-template.md` for the execution workflow.

## Summary

为 DataPipeline 模块构建数据管道护栏机制（GuardPipeline），以独立编排层包装现有 FinancialPipeline，实现：节点级数据校验与模式检查（Pydantic v2 声明式校验）、三级异常熔断与告警（Info/Error/Critical）、CI 集成的自动化管道完整性测试与基线对比、以及全链路结构化日志追踪。护栏机制对现有 PipelineContext 和各 Stage 类保持零侵入，所有新增功能通过包装模式注入。

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: Pydantic v2（模式校验）、SQLAlchemy 2.0（数据访问）、DuckDB/PyArrow（BDIB K 线数据）、FastAPI（仅在 CI 预检 Webhook 场景涉及）

**Storage**: SQLite（raw_fills.db / processed_fills.db / fill_bdib.db / bdib_daily_summary 等管道数据库）、PostgreSQL（业务持久化层，非管道直接依赖）

**Testing**: pytest（后端单元/集成测试）、pytest-cov（覆盖率）、pytest-benchmark（性能基准）

**Target Platform**: Linux server（生产 Docker Compose 部署）、Windows 11（开发环境）

**Project Type**: 数据管道（批处理 ETL + 分析），护栏机制为一个 Python 子包，无前端组件

**Performance Goals**: 百条记录以下校验在 1 秒内完成；正常数据流下校验+日志额外开销不超过总执行时间的 5%；CI 测试套件 5 分钟内出完整报告

**Constraints**: 不引入新的外部服务依赖；不新增第三方校验框架（使用 Pydantic v2 原生能力）；PipelineContext 和所有 Stage 类签名零改动；S1（外部摄入）使用宽松策略、S2-S10（内部加工）使用严格策略

**Scale/Scope**: 覆盖 10 个管道阶段（S1-S10），约 96 个源文件、120+ 类/函数需添加护栏包装或测试用例

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### I. 模块自治与边界契约 ✅ PASS

- 护栏机制完全在 DataPipeline 模块内部实现，不涉及任何跨模块依赖
- GuardPipeline 通过包装模式注入，不修改其他模块（CostView、MarketView）的代码
- 护栏日志和告警机制限定在 DataPipeline 命名空间内

### II. 分层架构与职责分离 ✅ PASS

- GuardPipeline → Stage Wrapper → 校验/熔断/日志 清晰分层
- `orchestration/guard.py`（编排层）→ `validation/`（校验层）→ `storage/`（日志持久化层）遵循现有分层模式
- 校验逻辑与处理逻辑完全分离（声明式 Schema 定义独立于 Stage 实现）

### III. 类型安全与静态校验 ✅ PASS

- 所有新增类/函数 MUST 使用完整类型注解
- 数据模式使用 Pydantic v2 `BaseModel` 声明，与后端 API 校验保持一致
- 熔断状态枚举和校验违规记录使用 Pydantic 模型

### IV. 配置即契约 ✅ PASS

- 护栏配置项集中到 `DataPipeline/config.py` Config 类：
  - `GUARDRAIL_ENABLED`（总开关）
  - `GUARDRAIL_CIRCUIT_BREAKER_THRESHOLD`（熔断阈值）
  - `GUARDRAIL_VALIDATION_STRICT_MODE`（校验模式）
  - `GUARDRAIL_EMPTY_DATASET_POLICY`（空数据集策略）
  - `GUARDRAIL_VALIDATION_BYPASS_ON_ERROR`（校验降级开关）
  - `GUARDRAIL_LOG_LEVEL`（日志级别）
- 数据库路径和表名不硬编码，引用 Config 类

### V. 实时数据统一管理 ✅ PASS

- N/A — 护栏机制属于批处理管道，不涉及 WebSocket 连接
- 不创建 Zustand store，不涉及 `RealtimeClient`

### 技术栈约束 ✅ PASS

- 不使用新第三方校验框架（Pydantic v2 原生能力满足需求）
- 使用项目已有的 pytest + logging 基础设施
- 遵循项目编码规范（const 优先、箭头函数、中文注释、类型注解）

### Gate 结果: ✅ 全部通过，无违规项。进入 Phase 0。

## Project Structure

### Documentation (this feature)

```text
specs/002-pipeline-guardrail/
├── plan.md              # 本文件 (/speckit.plan 命令输出)
├── research.md          # Phase 0 输出 (/speckit.plan 命令)
├── data-model.md        # Phase 1 输出 (/speckit.plan 命令)
├── quickstart.md        # Phase 1 输出 (/speckit.plan 命令)
├── contracts/           # Phase 1 输出 (/speckit.plan 命令)
└── tasks.md             # Phase 2 输出 (/speckit.tasks 命令 - 本命令不创建)
```

### Source Code (repository root)

```text
DataPipeline/
├── orchestration/
│   ├── guard.py                 # [NEW] GuardPipeline 编排器（包装 FinancialPipeline）
│   ├── guard_stage.py           # [NEW] GuardStage 阶段包装器（注入校验/熔断/日志）
│   └── ... (core.py, base.py, context.py, stages_*.py 保持不变)
├── validation/                   # [NEW] 校验与模式层
│   ├── __init__.py
│   ├── schema_registry.py       # 阶段输入/输出模式注册表
│   ├── schemas/                  # 各阶段 Pydantic 模式定义
│   │   ├── __init__.py
│   │   ├── raw_fills.py         # S1/S2 的 raw_fills 模式
│   │   ├── processed_fills.py   # S2/S3/S4 的 processed_fills 模式
│   │   ├── fill_bdib.py         # S5 的 fill_bdib 模式
│   │   ├── daily_metrics.py     # S7 的 daily_metrics 模式
│   │   ├── regime.py            # S8/S9 的 regime 模式
│   │   └── attribution.py       # S10 的 attribution 模式
│   ├── validator.py             # 校验执行器（Pydantic 校验 + 定制规则）
│   ├── violation.py             # 违规记录数据结构
│   └── contract_checker.py      # 阶段间模式契约兼容性检查
├── circuit_breaker/             # [NEW] 熔断机制
│   ├── __init__.py
│   ├── breaker.py               # 熔断器状态机（闭合/半开/断开）
│   ├── breaker_registry.py      # 每运行 ID 独立的熔断器注册表
│   ├── retry_policy.py          # 重试策略（S1 外部调用专用）
│   └── alert.py                 # 告警通知（结构化日志 + 扩展点）
├── monitoring/                   # [NEW] 监控与日志
│   ├── __init__.py
│   ├── run_logger.py            # 管道运行级结构化日志记录器
│   ├── stage_logger.py          # 阶段级入口/出口日志记录器
│   ├── run_id.py                # 运行 ID 生成器
│   └── summary.py               # 管道执行概要生成器
├── config.py                     # [MODIFY] 新增护栏配置项
└── tests/                        # [NEW/EXTEND] 护栏测试
    ├── guardrail/
    │   ├── __init__.py
    │   ├── conftest.py           # 护栏测试 Fixture（Mock 管道、测试数据）
    │   ├── test_validation.py    # 数据校验单元测试
    │   ├── test_circuit_breaker.py  # 熔断机制单元测试
    │   ├── test_pipeline_integrity.py  # 管道完整性与基线对比测试
    │   ├── test_contract_checker.py   # 契约兼容性检查测试
    │   └── test_logging.py       # 日志记录测试
    ├── baselines/                # 基线快照数据
    │   ├── s1_output.json
    │   ├── s2_output.json
    │   └── ...
    └── fixtures/                 # 测试 Fixture 数据（脱敏样本）
        ├── valid_fills.json
        ├── invalid_fills.json
        └── empty_fills.json
```

**Structure Decision**: 护栏机制作为 DataPipeline 的子包实现，新建 3 个核心包（`validation/`、`circuit_breaker/`、`monitoring/`）+ 1 个编排包装器（`orchestration/guard.py`、`orchestration/guard_stage.py`）。遵循项目现有分层模式：编排层→校验层→存储层。所有新增代码仅在 DataPipeline 目录内，不影响其他模块。

**Schema 策略说明**:
- S2/S3/S4 共享 `ProcessedFillsSchema`（基类），S3（AggregateFills）和 S4（GenerateOrderLabels）通过子类扩展各自特有的聚合字段和标签字段，不创建独立模式文件
- S6（WriteManifest）输出为文件系统清单 JSON，非数据库表，因此不需要 Pydantic Schema 校验；其数据完整性由清单文件格式自身的 JSON Schema 保证
- S9（RegimeFillTagger）复用 `RegimeSchema` 不单独定义模式，通过 S8/S9 共享模式声明反映在 `regime.py` 中

## Phase 1 Post-Design Constitution Re-Check

*Re-evaluated after data-model.md, contracts/, and quickstart.md design.*

### I. 模块自治与边界契约 ✅ PASS

- GuardPipeline 及其所有子组件（validation/circuit_breaker/monitoring）仅存在于 `DataPipeline/` 命名空间内
- 不引入 `from CostView.*` 或 `from MarketView.*` 的跨模块 import
- 护栏日志文件存储在 DataPipeline 数据目录下，不涉及其它模块的存储路径

### II. 分层架构与职责分离 ✅ PASS

Phase 1 设计确认了新子包的职责边界清晰：

- `orchestration/guard.py`: 编排层 — 包装 FinancialPipeline，注入护栏行为
- `validation/`: 校验层 — Schema 定义与校验执行，与 Stage 处理逻辑分离
- `circuit_breaker/`: 熔断层 — 状态机、重试策略、告警，独立于数据校验
- `monitoring/`: 日志层 — 运行 ID 生成、结构化日志、概要输出
- 各层之间通过明确的 Python 接口（非隐式依赖）通信

### III. 类型安全与静态校验 ✅ PASS

- 数据模型中所有实体使用 Pydantic v2 `BaseModel` 或 `@dataclass` 定义，含完整类型注解
- 契约文档（`guard-pipeline-api.md`）中所有函数签名包含参数类型和返回值类型
- 枚举类型统一定义（`RunStatus`, `StageStatus`, `SeverityLevel`, `BreakerState` 等）

### IV. 配置即契约 ✅ PASS

设计确认 Config 类新增护栏配置项：

- `GUARDRAIL_ENABLED: bool` — 总开关
- `GUARDRAIL_CIRCUIT_BREAKER_THRESHOLD: int` — 连续失败熔断阈值
- `GUARDRAIL_RETRY_MAX: int` — S1 最大重试次数
- `GUARDRAIL_LOG_DIR: Path` — 日志目录
- `GUARDRAIL_BASELINE_DIR: Path` — 基线快照目录
- `GUARDRAIL_VALIDATION_STRICT_MODE: bool` — 全局严格模式开关
- `GUARDRAIL_EMPTY_DATASET_POLICY: str` — 空数据集处理策略（"reject"|"accept"）
- `GUARDRAIL_VALIDATION_BYPASS_ON_ERROR: bool` — 校验规则异常时降级放行开关
- 所有路径和阈值从 Config 读取，不硬编码

### V. 实时数据统一管理 ✅ N/A

- 护栏机制不涉及 WebSocket、Zustand store 或 RealtimeClient。

### 技术栈约束 ✅ PASS

- 校验层使用 Pydantic v2（项目已有依赖），不引入新第三方校验框架
- 测试层使用 pytest + pytest-cov（项目已有基础设施）
- 日志层使用 Python logging 模块（零新增依赖）
- 代码遵循项目编码规范（const 优先、类型注解、中文注释）

### Re-Check Gate 结果: ✅ 全部通过。进入 Phase 2 (speckit.tasks)。

## Complexity Tracking

> 无宪法违规项，无需记录复杂度偏离。
