# Research: 数据管道护栏机制

**Feature**: 002-pipeline-guardrail
**Date**: 2026-06-16
**Phase**: 0 — 技术方案研究

## 研究任务清单

| # | 研究议题 | 来源 | 状态 |
|---|---------|------|------|
| R1 | 批处理管道熔断器模式 | FR-006~FR-011 | ✅ 已解决 |
| R2 | Pydantic v2 声明式数据校验模式 | FR-001~FR-005 | ✅ 已解决 |
| R3 | ETL 管道基线快照测试策略 | FR-012~FR-016, FR-022~FR-023 | ✅ 已解决 |
| R4 | 阶段间模式契约兼容性检查 | FR-002, Clarification Q3 | ✅ 已解决 |
| R5 | 管道结构化日志记录方案 | FR-017~FR-021 | ✅ 已解决 |
| R6 | CI 集成触发策略 | FR-023, Clarification Q2 | ✅ 已解决 |
| R7 | S1 宽松策略 vs S2-S10 严格策略实现 | Clarification Q7 | ✅ 已解决 |

---

## R1: 批处理管道熔断器模式

### Decision
采用**按运行实例隔离的三态状态机（闭合/半开/断开）**，每个 `PipelineContext.run_id` 维护独立的熔断器实例。熔断器内嵌在 `GuardStage` 包装器中，支持三级严重等级（Info/Error/Critical）。

### Rationale

- **为什么不用标准 Circuit Breaker（如 `pybreaker`）**：标准熔断器库（如 `circuitbreaker`、`pybreaker`）面向 HTTP/RPC 调用，统计时间窗口内的失败率。管道阶段是批处理执行（每天一次），不存在高频调用的时间窗口概念。需要定制化的"连续失败计数"模型。
- **为什么按 Run ID 隔离**：不同日期/批次的管道运行相互独立，一天的熔断不应影响另一天。按 `run_id` 隔离熔断器注册表（`breaker_registry`），`GuardPipeline.run()` 创建新的 `run_id` 时自动创建独立熔断器实例。
- **为什么三态而非两态**：闭合→断开→半开 的标准三态模式允许运维排查后安全重试。半开状态允许执行一个探测阶段，成功则恢复闭合，失败则重新断开。

### Alternatives Considered

- **全局单例熔断器**：不支持不同日期独立运行，不适用。
- **仅两态（正常/熔断）**：缺少半开态导致手动恢复后无法自动验证问题是否已修复。
- **基于时间窗口的失败率统计**：管道日批次执行频率低，无足够样本建立统计窗口。

### Key Implementation Details

```python
# 熔断器状态转移：闭合 → (连续失败>=阈值) → 断开 → (手动重置) → 半开 → (探测成功) → 闭合
class CircuitBreakerState(Enum):
    CLOSED = "closed"       # 正常运行
    HALF_OPEN = "half_open" # 探测模式（允许一个阶段执行以验证恢复）
    OPEN = "open"           # 完全阻断

class CircuitBreaker:
    state: CircuitBreakerState = CLOSED
    failure_count: int = 0
    max_failures: int = 3        # 连续失败阈值（Config 可配）
    severity: SeverityLevel = INFO

    def record_failure(self, severity: SeverityLevel) -> None:
        if severity == CRITICAL:
            self.state = OPEN          # Critical 立即熔断
        elif severity == ERROR:
            self.failure_count += 1
            if self.failure_count >= self.max_failures:
                self.state = OPEN      # Error 累计 N 次后熔断
        # Info 不触发熔断

    def before_stage(self) -> bool:
        """返回 False 表示阻断执行"""
        if self.state == OPEN:
            return False
        return True
```

---

## R2: Pydantic v2 声明式数据校验模式

### Decision
使用 **Pydantic v2 `BaseModel`** 为每个阶段的输入/输出数据定义声明式 Schema。校验器（`validator.py`）在阶段写 DB 后和读 DB 前分别调用 Pydantic 的 `model_validate()`，违规记录捕获 `ValidationError` 并转换为 `ViolationRecord`。

### Rationale

- **为何 Pydantic v2 而非自定义校验框架**：项目 Constitution 要求"技术栈约束"——后端已使用 Pydantic v2，管道层复用可降低维护成本。Pydantic v2 在 Rust 核心上运行（`pydantic-core`），性能远优于纯 Python 校验（百条记录 <100ms）。
- **为何声明式而非命令式校验**：声明式 Schema（Pydantic model）与处理逻辑分离，上游输出变更时只需对比 Schema 定义即可检测下游兼容性，实现 FR-002 的"自动校验下游输入期望"。
- **为何 `model_validate()` 而非 `TypeAdapter`**：`BaseModel` 提供字段级错误报告（`ValidationError.errors()`），可直接映射到 FR-003 要求的"违规行号/字段名/期望值/实际值"格式。
- **性能考虑**：百条记录以下的 `model_validate()` 调用在 10-50ms 内完成（Rust 核心），满足 SC-001（1 秒内完成）和 SC-008（<5% 额外开销）。

### Alternatives Considered

- **Marshmallow**：非 Rust 实现，性能较低；项目未使用，引入新依赖违反 Constitution。
- **自定义校验装饰器**：灵活性高但无类型推导支持，需自行维护字段类型映射，与 DB schema 列定义存在二义性风险。
- **SQL CHECK 约束**：直接在 SQLite 层校验，但无法区分 Info/Error/Critical 等级，也无法在 S1 宽松策略中跳过部分校验。

### Key Implementation Details

```python
from pydantic import BaseModel, Field, model_validator

class RawFillsOutput(BaseModel):
    """S1/S2 的 raw_fills 输出模式"""
    fill_id: int = Field(gt=0)
    order_id: int = Field(gt=0)
    route_id: int = Field(gt=0)
    fill_price: float = Field(ge=0, le=1_000_000)
    fill_qty: float = Field(ge=0)
    fill_time: str  # ISO format datetime
    security_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def check_qty_nonzero_for_executed(self):
        """定制业务约束：已执行成交的 qty 必须 >0"""
        ...

# Schema 按阶段独立定义，存储在 validation/schemas/ 目录
# 每个阶段有 INPUT_SCHEMA 和 OUTPUT_SCHEMA
```

---

## R3: ETL 管道基线快照测试策略

### Decision
使用 **JSON 文件存储基线快照**，通过 `pytest` + `snapshot` 风格对比实现基线测试。基线数据基于历史真实数据的脱敏固定样本（不随日常管道运行变化），更新需在 Code Review 中人工确认后归档。

### Rationale

- **为何 JSON 而非数据库 dump**：JSON 文件易于 Git 版本控制、diff 审查和 CI 集成。数据库 dump 包含二进制数据和无关元信息，diff 不可读。
- **为何 pytest 而非专用工具（如 dbt tests）**：项目已使用 pytest 基础设施，引入 `pytest-snapshot` 或 `snapshottest` 增加不必要的依赖。自定义简单的 JSON 对比逻辑即可满足需求。
- **为何固定样本而非动态采样**：动态采样导致基线随数据变化频繁漂移，增加误报率。固定脱敏样本保证基线稳定，仅在逻辑变更时更新。
- **基线更新流程**：
  1. 开发者在 PR 中提议基线更新（附带 diff 说明）
  2. Reviewer 在 Code Review 中确认变更合理性
  3. 合并 PR 时新基线生效
  4. 自动化脚本校验基线文件完整性（防止意外覆盖）

### Alternatives Considered

- **pytest-snapshot / snapshottest**：额外依赖，且对 Pandas DataFrame 输出支持有限。
- **Great Expectations**：功能过于庞大（数据质量监控套件），超出护栏需求范围，引入复杂度远大于收益。
- **dbt test**：面向 dbt 工作流，项目不使用 dbt。

### Key Implementation Details

```python
# tests/guardrail/conftest.py
@pytest.fixture
def baseline_snapshots():
    """加载所有阶段的基线快照"""
    baseline_dir = Path(__file__).parent.parent / "baselines"
    return {f.stem: json.loads(f.read_text()) for f in baseline_dir.glob("*.json")}

def assert_baseline_match(stage_name: str, actual_output: list[dict], baseline: dict, tolerance: float = 0.01):
    """对比实际输出与基线，数值字段使用容差"""
    expected = baseline[stage_name]
    # 字段完整性对比 + 数值容差对比 + 差异报告
    ...
```

---

## R4: 阶段间模式契约兼容性检查

### Decision
基于 Pydantic Schema 定义，实现**静态契约兼容性检查器**（`contract_checker.py`）。当上游阶段输出 Schema 发生变更时，自动检
查所有下游阶段的输入 Schema 是否仍兼容。检查策略分为三级：字段兼容（新增/删除/重命名）、类型兼容（类型变更）、约束兼容（新增约束/收紧约束）。

### Rationale

- **为何 Pydantic Field 而非接口协议**：Pydantic model 的 `model_fields` 提供结构化的字段元数据（type, annotation, constraints），可直接用于兼容性分析。无需额外定义 IDL 或协议。
- **为何静态检查而非运行时发现**：运行时发现意味着问题要在生产环境中暴露。静态检查在开发阶段（CI 预检）即可捕获，成本最低。
- **兼容性判断逻辑**：
  - **向前兼容**（可自动通过）：新增可选字段、放宽约束（如增大取值范围）
  - **向后不兼容**（需拒绝）：删除字段、重命名字段、变更类型、收紧约束、新增必填字段

### Alternatives Considered

- **Protobuf/Avro Schema Registry**：为管道引入序列化格式开销过大，管道数据通过 SQLite 表传递，不需要二进制编码。
- **手动在 Config 中定义契约关系**：维护成本高，容易遗漏，不支持自动检测。

### Key Implementation Details

```python
class ContractCompatibility(Enum):
    COMPATIBLE = "compatible"           # 完全兼容
    COMPATIBLE_WITH_WARNING = "warning"  # 向前兼容但有下游需要注意的变更
    INCOMPATIBLE = "incompatible"        # 阻断性变更

def check_contract_compatibility(
    upstream: type[BaseModel],  # 上游输出 Schema
    downstream: type[BaseModel] # 下游输入 Schema
) -> tuple[ContractCompatibility, list[str]]:
    """检查上游输出 Schema 变更后是否仍满足下游输入期望"""
    issues = []
    downstream_fields = downstream.model_fields

    for field_name, field_info in downstream_fields.items():
        if field_name not in upstream.model_fields:
            issues.append(f"下游必需字段 '{field_name}' 在上游输出中不存在")
            continue
        upstream_field = upstream.model_fields[field_name]
        if upstream_field.annotation != field_info.annotation:
            issues.append(f"字段 '{field_name}' 类型不匹配: 下游期望 {field_info.annotation}, 上游输出 {upstream_field.annotation}")

    if issues:
        return ContractCompatibility.INCOMPATIBLE, issues
    return ContractCompatibility.COMPATIBLE, []
```

---

## R5: 管道结构化日志记录方案

### Decision
使用 Python **`logging` 模块 + 自定义 JSON 格式化器**，按运行 ID 输出结构化日志到文件。日志包含阶段级入口/出口记录、校验违规详情、异常堆栈、执行概要。支持按日期/运行 ID/阶段名称检索。

### Rationale

- **为何 logging 而非专用框架（如 structlog）**：项目已使用 `logging` 模块，零新增依赖。JSON 格式化器可满足结构化需求。
- **为何文件日志而非数据库日志**：数据库日志增加写入开销（每阶段边界写一次），且可能因数据库故障丢失日志。文件追加写入最可靠，管道完成后的概要日志也可选择写入数据库供查询。
- **日志分层设计**：
  - **运行级** (`run_logger`): `{run_id}.log` — 包含所有阶段的概要记录
  - **阶段级** (`stage_logger`): 内嵌在运行日志中，标记阶段名称
  - **违规级**: 内嵌在阶段日志中，包含违规详情
- **检索能力**：日志文件按 `{run_id}.jsonl` 格式存储，每行一条 JSON 记录，支持 `jq` 或 `grep` 检索。

### Alternatives Considered

- **Elasticsearch + Kibana**：生产级日志方案，但对开发环境和单机部署过重，违反"不引入新外部服务依赖"约束。
- **SQLite 日志表**：可 SQL 查询但增加写入路径的循环依赖风险（管道日志→数据库→如果数据库就是被处理对象）。
- **structlog**：优秀的结构化日志库，但需要新增依赖。

### Key Implementation Details

```python
# monitoring/run_logger.py
class PipelineRunLogger:
    def __init__(self, run_id: str, log_dir: Path):
        self.run_id = run_id
        self.log_path = log_dir / f"{run_id}.jsonl"
        self._entries: list[dict] = []

    def log_stage_start(self, stage_name: str, input_count: int) -> None: ...
    def log_stage_end(self, stage_name: str, output_count: int, duration_ms: float,
                      passed: int, failed: int) -> None: ...
    def log_violation(self, stage_name: str, violation: ViolationRecord) -> None: ...
    def log_exception(self, stage_name: str, exc: Exception) -> None: ...
    def flush(self) -> None:
        """将内存中的日志批量写入文件"""

# 日志输出格式（JSONL）:
# {"run_id":"20260616-001","ts":"2026-06-16T10:30:00","level":"STAGE_START","stage":"S2","input_count":150}
# {"run_id":"20260616-001","ts":"2026-06-16T10:30:02","level":"STAGE_END","stage":"S2","output_count":150,"duration_ms":2100,"passed":150,"failed":0}
```

---

## R6: CI 集成触发策略

### Decision
在代码提交/Pull Request 时通过 **GitHub Actions（或其他 CI 工具）自动触发管道完整性测试**。CI 脚本运行 `pytest tests/guardrail/`，执行"受影响阶段及下游全链路对比测试"，测试未通过则**阻止代码合并**。

### Rationale

- **为何 CI 预检而非部署后检查**：Clarification Q2 明确要求在 CI 预检阶段触发，以"尽早发现改了 A 处没改 B 处"的问题。部署后检查的问题修复成本远高于 CI 阶段。
- **增量测试策略**：通过 Git diff 识别变更涉及的文件，判断受影响的管道阶段，仅运行受影响阶段及下游的测试（而非全量 10 阶段），控制 CI 时间在 5 分钟内（SC-002）。
- **CI 脚本设计**：
  1. 检出代码 + 设置 Python 环境
  2. 安装 DataPipeline 包（`pip install -e DataPipeline`）
  3. 运行 `python -m pytest tests/guardrail/test_pipeline_integrity.py -v --cov --junitxml=report.xml`
  4. 解析测试报告，失败则返回非零退出码

### Alternatives Considered

- **Pre-commit Hook**：在 `git commit` 时运行，但需要开发者本地安装完整依赖，且无法强制（可 `--no-verify` 跳过）。
- **定时全量检查（Cron）**：仅在发现问题后通知，无法阻挡问题代码合入主分支。
- **GitHub Check Run API**：可以，但需额外的 CI 平台集成；GitHub Actions 标准工作流已足够。

---

## R7: S1 宽松策略 vs S2-S10 严格策略

### Decision
在 `schema_registry.py` 中为每个阶段注册**策略等级**（`ValidationPolicy`），`validator.py` 根据策略等级调整校验行为：
- **S1（宽松策略）**：仅校验数据类型，不校验值域约束和必填字段；校验失败触发重试+降级，不熔断。
- **S2-S10（严格策略）**：完整校验（类型+值域+必填+定制约束）；按严重等级（Info/Error/Critical）触发熔断。

### Rationale

- **S1 特殊性**：S1 处理外部数据摄入（Bloomberg EMSX / Excel），数据源不可控。网络波动、Bloomberg API 限流、数据格式偶发性变化都是正常运维场景，不应因临时数据问题导致全链路熔断。
- **S2-S10 的数据是内部生成的**：数据质量问题意味着代码 Bug，应严格拦截。
- **宽松策略具体行为**：
  - 数据类型错误：仍然拦截（如 `"abc"` 写入 int 字段）
  - 必填字段缺失：记录 Info 级别违规，允许通过
  - 值域违规（如负成交量）：记录 Error 级别违规，触发重试但不断熔
  - 外部 API 调用失败：记录 Error 级别，执行重试（最多 3 次，指数退避），重试失败后降级（跳过当日处理）

### Alternatives Considered

- **S1 也使用严格策略**：Bloomberg API 偶发性超时会导致每日管道中断，运维负担过重。
- **S1 不使用任何校验**：可能导致格式错误的数据写入 raw_fills.db，下游 S2 处理时崩溃且难以定位根因。

---

## 总结：技术决策矩阵

| # | 技术决策 | 选用方案 | 关键理由 |
|---|---------|---------|---------|
| R1 | 熔断器模式 | 按 Run ID 隔离的三态状态机 | 批处理场景不适用时间窗口熔断；需按日期独立隔离 |
| R2 | 数据校验 | Pydantic v2 BaseModel + model_validate() | 复用项目技术栈，Rust 核心性能高，错误报告结构化 |
| R3 | 基线测试 | JSON 文件 + pytest 自定义对比 | Git 可版本控制，diff 可审查，零新增依赖 |
| R4 | 契约检查 | Pydantic model_fields 静态分析 | 声明式 Schema 直接提供元数据，无需额外 IDL |
| R5 | 日志记录 | logging + JSONL 格式化器 | 零新增依赖，追加写入可靠，jq/grep 可检索 |
| R6 | CI 集成 | GitHub Actions + pytest 增量测试 | 阻止问题代码合入，≤5 分钟反馈 |
| R7 | S1 vs S2-S10 | 策略模式（宽松 vs 严格） | S1 外部不可控数据需容错，S2-S10 内部数据需严格 |
