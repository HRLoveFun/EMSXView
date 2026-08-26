# Data Model: 数据管道护栏机制

**Feature**: 002-pipeline-guardrail
**Date**: 2026-06-16
**Phase**: 1 — 数据模型设计

## 实体关系图

```
PipelineRun (1) ────< (N) StageExecution
     │                       │
     │                       ├──< (N) ValidationViolation
     │                       │
     │                       └──< (1) CircuitBreakerState
     │
     └──< (1) PipelineSchema (每个阶段的输入/输出模式定义)
              │
              └──< (N) SchemaContract (阶段间兼容性关系)
```

---

## 实体定义

### 1. 管道运行记录 (PipelineRun)

代表一次完整的管道执行实例。

| 字段 | 类型 | 约束 | 描述 |
|------|------|------|------|
| `run_id` | `str` | 必填，唯一 | 运行唯一标识，格式 `YYYYMMDD-HHMMSS-xxxxxx` |
| `target_date` | `str` | 必填 | 目标数据日期，格式 `YYYY-MM-DD` |
| `started_at` | `datetime` | 必填 | 管道开始执行时间 |
| `ended_at` | `datetime \| None` | 可选 | 管道结束执行时间 |
| `status` | `RunStatus` | 必填 | 枚举: `RUNNING \| SUCCESS \| PARTIAL_FAILURE \| CIRCUIT_BROKEN \| ABORTED` |
| `stages_total` | `int` | 必填，>=0 | 计划执行的阶段总数（排除跳过的阶段） |
| `stages_completed` | `int` | 必填，>=0 | 成功完成的阶段数 |
| `stages_failed` | `int` | 必填，>=0 | 失败的阶段数 |
| `stages_skipped` | `int` | 必填，>=0 | 被跳过的阶段数（如 skip_ingest/skip_bdib） |
| `total_duration_ms` | `float` | 必填，>=0 | 总执行耗时（毫秒） |
| `log_path` | `str \| None` | 可选 | 日志文件路径 |

**状态转换**:

```
RUNNING → SUCCESS          (全部阶段成功完成)
RUNNING → PARTIAL_FAILURE  (部分阶段失败但未触发熔断)
RUNNING → CIRCUIT_BROKEN   (触发全链路熔断)
RUNNING → ABORTED          (外部中断或未捕获异常)
```

**验证规则**:
- `stages_completed + stages_failed + stages_skipped == stages_total`
- `ended_at >= started_at`
- `status != RUNNING` 时 `ended_at` 不得为 None

---

### 2. 阶段执行记录 (StageExecution)

代表管道中单个阶段的执行实例。

| 字段 | 类型 | 约束 | 描述 |
|------|------|------|------|
| `run_id` | `str` | 必填 | 所属管道运行 ID |
| `stage_name` | `str` | 必填 | 阶段名称（S1-S10） |
| `stage_order` | `int` | 必填，>=1 | 执行顺序编号 |
| `started_at` | `datetime` | 必填 | 阶段开始执行时间 |
| `ended_at` | `datetime \| None` | 可选 | 阶段结束执行时间 |
| `duration_ms` | `float \| None` | 可选 | 阶段执行耗时（毫秒） |
| `input_record_count` | `int \| None` | 可选 | 输入记录数 |
| `output_record_count` | `int \| None` | 可选 | 输出记录数 |
| `validation_passed` | `int` | 默认 0 | 校验通过记录数 |
| `validation_failed` | `int` | 默认 0 | 校验失败记录数 |
| `status` | `StageStatus` | 必填 | 枚举: `PENDING \| RUNNING \| SUCCESS \| FAILED \| CIRCUIT_BROKEN \| TIMEOUT \| SKIPPED` |
| `severity` | `SeverityLevel` | 可选 | 异常严重等级: `INFO \| ERROR \| CRITICAL`（仅异常时设置） |

**状态转换**:

```
PENDING → RUNNING → SUCCESS
PENDING → RUNNING → FAILED (Error 级异常，当前阶段阻断)
PENDING → RUNNING → TIMEOUT (超时)
PENDING → RUNNING → CIRCUIT_BROKEN (Critical 级异常，全链路熔断)
PENDING → SKIPPED (阶段被配置跳过)
```

**验证规则**:
- `validation_passed + validation_failed <= output_record_count`（宽松策略下部分失败记录可能被排除）
- `status == SUCCESS` 时 `validation_failed` SHOULD 为 0

---

### 3. 校验违规记录 (ValidationViolation)

代表单条数据校验失败的具体信息。

| 字段 | 类型 | 约束 | 描述 |
|------|------|------|------|
| `run_id` | `str` | 必填 | 所属管道运行 ID |
| `stage_name` | `str` | 必填 | 发生违规的阶段名称 |
| `record_identifier` | `str \| None` | 可选 | 违规记录的主键或行号标识 |
| `field_name` | `str` | 必填 | 违规字段名 |
| `expected_constraint` | `str` | 必填 | 期望约束描述（如 "type=int, gt=0"） |
| `actual_value` | `Any` | 必填 | 实际值 |
| `severity` | `SeverityLevel` | 必填 | 违规严重等级: `INFO \| ERROR \| CRITICAL` |
| `violation_type` | `ViolationType` | 必填 | 违规类型: `MISSING_REQUIRED \| TYPE_MISMATCH \| RANGE_VIOLATION \| ENUM_VIOLATION \| CUSTOM_CONSTRAINT` |
| `violated_at` | `datetime` | 必填 | 违规发生时间 |

**严重等级映射**:

| 违规类型 | 默认严重等级 | 可配置覆盖 |
|---------|------------|-----------|
| `MISSING_REQUIRED` | ERROR | 是（S1 降级为 INFO） |
| `TYPE_MISMATCH` | ERROR | 否 |
| `RANGE_VIOLATION` | ERROR | 是（负成交量可升级为 CRITICAL） |
| `ENUM_VIOLATION` | ERROR | 否 |
| `CUSTOM_CONSTRAINT` | ERROR | 是 |

---

### 4. 熔断状态 (CircuitBreakerState)

代表管道或阶段的熔断状态。

| 字段 | 类型 | 约束 | 描述 |
|------|------|------|------|
| `run_id` | `str` | 必填 | 所属管道运行 ID |
| `stage_name` | `str` | 必填 | 被熔断的阶段名称 |
| `state` | `BreakerState` | 必填 | 枚举: `CLOSED \| HALF_OPEN \| OPEN` |
| `failure_count` | `int` | 默认 0 | 连续失败计数 |
| `max_failures` | `int` | 必填 | 连续失败阈值（Config 配置） |
| `triggered_at` | `datetime \| None` | 可选 | 熔断触发时间 |
| `trigger_reason` | `str \| None` | 可选 | 触发原因描述 |
| `last_failure_detail` | `str \| None` | 可选 | 最近一次失败的详情 |
| `reset_at` | `datetime \| None` | 可选 | 熔断重置时间（手动操作） |

**状态转换**:

```
CLOSED ──(连续失败>=阈值)──→ OPEN
CLOSED ──(Critical 异常)───→ OPEN  (立即熔断，不计失败次数)
OPEN   ──(手动重置)────────→ HALF_OPEN
HALF_OPEN ──(探测成功)─────→ CLOSED
HALF_OPEN ──(探测失败)─────→ OPEN
```

**验证规则**:
- `state == CLOSED` 时 `failure_count` SHOULD 为 0
- `triggered_at` 仅在 `state == OPEN` 时不为 None
- `reset_at` 仅在 `state == HALF_OPEN` 时不为 None

---

### 5. 管道模式定义 (PipelineSchema)

代表某个管道阶段输入/输出的数据模式（声明式定义）。

| 字段 | 类型 | 约束 | 描述 |
|------|------|------|------|
| `schema_id` | `str` | 必填，唯一 | 模式唯一标识，格式 `{stage_name}_{input\|output}`，如 `S2_output` |
| `stage_name` | `str` | 必填 | 所属阶段名称 |
| `direction` | `SchemaDirection` | 必填 | 枚举: `INPUT \| OUTPUT` |
| `fields` | `list[SchemaField]` | 必填，非空 | 字段定义列表 |
| `pydantic_model` | `type[BaseModel]` | 必填 | 对应的 Pydantic v2 模型类引用 |
| `validation_policy` | `ValidationPolicy` | 必填 | 校验策略: `STRICT \| RELAXED` |
| `created_at` | `datetime` | 必填 | 模式创建时间 |
| `updated_at` | `datetime` | 必填 | 模式最后更新时间 |

**SchemaField 子结构**:

| 字段 | 类型 | 约束 | 描述 |
|------|------|------|------|
| `field_name` | `str` | 必填 | 字段名（与 DB 列名一致） |
| `field_type` | `str` | 必填 | Python 类型标注，如 `int`, `float`, `str` |
| `is_required` | `bool` | 默认 True | 是否必填 |
| `constraints` | `dict` | 可选 | 值域约束: `{"gt": 0}`, `{"ge": 0, "le": 1000000}`, `{"enum": ["BUY", "SELL"]}` |
| `default_value` | `Any` | 可选 | 默认值 |

**验证规则**:
- `fields` 中的 `field_name` 在同一个 `schema_id` 内不得重复
- `pydantic_model` 的字段必须与 `fields` 列表一一对应
- 下游阶段输入模式的字段应是上游阶段输出模式的子集（契约兼容性检查）

---

### 6. 模式契约关系 (SchemaContract)

代表两个阶段之间的模式兼容性关系。

| 字段 | 类型 | 约束 | 描述 |
|------|------|------|------|
| `contract_id` | `str` | 必填，唯一 | 契约唯一标识，格式 `{上游输出}_{下游输入}` |
| `upstream_schema_id` | `str` | 必填 | 上游阶段输出模式 ID |
| `downstream_schema_id` | `str` | 必填 | 下游阶段输入模式 ID |
| `compatibility` | `ContractCompatibility` | 必填 | 枚举: `COMPATIBLE \| COMPATIBLE_WITH_WARNING \| INCOMPATIBLE` |
| `last_checked_at` | `datetime` | 必填 | 最后一次兼容性检查时间 |
| `issues` | `list[str]` | 默认 [] | 不兼容项列表（兼容时为空） |

**兼容性判断规则**:

| 上游变更类型 | 兼容性结果 | 说明 |
|------------|-----------|------|
| 新增可选字段 | COMPATIBLE | 下游不依赖新字段，安全 |
| 新增必填字段 | INCOMPATIBLE | 下游不消费该字段的数据会不完整 |
| 删除字段 | INCOMPATIBLE | 下游输入可能引用该字段 |
| 重命名字段 | INCOMPATIBLE | 等价于删除+新增 |
| 类型变更 (int→float) | COMPATIBLE_WITH_WARNING | 可能损失精度 |
| 类型变更 (float→str) | INCOMPATIBLE | 类型不兼容 |
| 放宽约束 (ge=0→ge=-100) | COMPATIBLE | 下游约束是上游约束的子集 |
| 收紧约束 (ge=0→ge=1) | INCOMPATIBLE | 上游可能输出不满足下游约束的值 |

---

## 阶段数据流与 Schema 映射

| 阶段 | 输入来源 | 输入 Schema | 输出目标 | 输出 Schema | 策略 |
|------|---------|------------|---------|------------|------|
| S1: IngestExcel | 外部 Excel 文件 | 外部源（无预检） | raw_fills.db | S1_output (EMSX_FILL_COLUMNS) | RELAXED |
| S2: ProcessRawFills | raw_fills.db | S2_input (=S1_output) | processed_fills.db | S2_output (PROCESSED_COLUMNS) | STRICT |
| S3: AggregateFills | processed_fills.db | S3_input (=S2_output) | processed_fills.db (agg) | S3_output (AGG_COLUMNS) | STRICT |
| S4: GenerateOrderLabels | processed_fills.db | S4_input (=S2_output) | processed_fills.db (labels) | S4_output (ORDER 扩展) | STRICT |
| S5: IntegrateBDIB | fill_bdib (外部) | S5_input (BDIB columns) | fill_bdib.db | S5_output (BDIB integrated) | STRICT |
| S6: WriteManifest | 聚合数据 | S6_input (manifest 元数据) | 文件系统（清单文件） | S6_output (manifest JSON) | STRICT |
| S7: CalculateDailyMetrics | fill_bdib.db | S7_input (=S5_output) | bdib_daily_summary | S7_output (metrics) | STRICT |
| S8: RegimeDailyFeatures | bdib_daily_summary | S8_input (=S7_output) | regime 表 | S8_output (regime features) | STRICT |
| S9: RegimeFillTagger | fill_bdib.db + regime | S9_input (fills+regime) | fill_bdib.db (tags) | S9_output (tagged fills) | STRICT |
| S10: AttributionMetrics | fill_bdib.db | S10_input (=S9_output) | attribution 表 | S10_output (IS/VWAP/reversal) | STRICT |

---

## 枚举定义

```python
from enum import Enum

class RunStatus(str, Enum):
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL_FAILURE = "partial_failure"
    CIRCUIT_BROKEN = "circuit_broken"
    ABORTED = "aborted"

class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CIRCUIT_BROKEN = "circuit_broken"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"

class SeverityLevel(str, Enum):
    INFO = "info"        # 记录可恢复异常，不阻断
    ERROR = "error"      # 阻断当前阶段，不熔断下游
    CRITICAL = "critical" # 立即熔断全链路并告警

class BreakerState(str, Enum):
    CLOSED = "closed"         # 正常运行
    HALF_OPEN = "half_open"   # 探测模式
    OPEN = "open"             # 熔断阻断

class ViolationType(str, Enum):
    MISSING_REQUIRED = "missing_required"
    TYPE_MISMATCH = "type_mismatch"
    RANGE_VIOLATION = "range_violation"
    ENUM_VIOLATION = "enum_violation"
    CUSTOM_CONSTRAINT = "custom_constraint"

class ValidationPolicy(str, Enum):
    STRICT = "strict"     # 完整校验（类型+值域+必填+定制）
    RELAXED = "relaxed"   # 仅校验类型，允许重试降级

class SchemaDirection(str, Enum):
    INPUT = "input"
    OUTPUT = "output"

class ContractCompatibility(str, Enum):
    COMPATIBLE = "compatible"
    COMPATIBLE_WITH_WARNING = "compatible_with_warning"
    INCOMPATIBLE = "incompatible"
```
