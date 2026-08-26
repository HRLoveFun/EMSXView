# API Contract: GuardPipeline

**Feature**: 002-pipeline-guardrail
**Date**: 2026-06-16
**Contract Type**: Python Class Interface（内部 API）

---

## GuardPipeline

`GuardPipeline` 是 `FinancialPipeline` 的包装器，提供带护栏保护的管道执行能力。

### Constructor

```python
class GuardPipeline:
    def __init__(
        self,
        pipeline: FinancialPipeline,
        *,
        schemas: SchemaRegistry,
        breaker_registry: CircuitBreakerRegistry | None = None,
        logger: PipelineRunLogger | None = None,
        config: Config | None = None,
    ) -> None: ...
```

**参数**:

| 参数 | 类型 | 必填 | 描述 |
|------|------|------|------|
| `pipeline` | `FinancialPipeline` | 是 | 被包装的原始管道实例 |
| `schemas` | `SchemaRegistry` | 是 | 阶段输入/输出模式注册表 |
| `breaker_registry` | `CircuitBreakerRegistry \| None` | 否 | 熔断器注册表（不提供则自动创建） |
| `logger` | `PipelineRunLogger \| None` | 否 | 运行日志记录器（不提供则自动创建） |
| `config` | `Config \| None` | 否 | 配置实例（不提供则使用全局 Config） |

### run()

```python
def run(self, context: PipelineContext) -> GuardRunResult: ...
```

**返回值**: `GuardRunResult` — 包含管道执行结果和护栏报告

**行为**:
1. 生成唯一 `run_id` 并关联到 context
2. 创建熔断器注册表实例（按此 `run_id` 隔离）
3. 顺序执行每个阶段，每阶段执行前：
   a. 检查熔断状态（如断开则跳过）
   b. 检查阶段是否被配置跳过（跳过则不计入统计）
   c. 执行阶段 `execute()`
   d. 阶段成功后执行输出校验
   e. 阶段执行前后记录日志（入口/出口/异常）
4. 管道完成后生成概要日志
5. 返回 `GuardRunResult`

**错误处理**:
- 阶段返回 `False` → 记录 `StageStatus.FAILED`，根据 severity 决定是否熔断
- 阶段抛出未捕获异常 → 同 `False` 处理
- Critical 级异常 → 立即熔断全链路
- S1 阶段宽松策略 → 校验失败触

发重试，不阻断

---

## StageExecution Result

```python
@dataclass
class GuardRunResult:
    """管道护栏执行结果"""
    run_id: str
    status: RunStatus
    started_at: datetime
    ended_at: datetime
    stages: list[GuardStageResult]
    summary: dict[str, Any]
    log_path: str | None

@dataclass
class GuardStageResult:
    """单个阶段的护栏执行结果"""
    stage_name: str
    status: StageStatus
    input_count: int | None
    output_count: int | None
    validation_passed: int
    validation_failed: int
    violations: list[ValidationViolation]
    duration_ms: float
    severity: SeverityLevel | None
    skipped: bool = False
```

---

## SchemaRegistry

```python
class SchemaRegistry:
    """阶段输入/输出模式注册表"""

    def register(
        self,
        stage_name: str,
        direction: SchemaDirection,
        schema: type[BaseModel],
        policy: ValidationPolicy = STRICT,
    ) -> None: ...

    def get_input_schema(self, stage_name: str) -> type[BaseModel] | None: ...
    def get_output_schema(self, stage_name: str) -> type[BaseModel] | None: ...
    def get_policy(self, stage_name: str) -> ValidationPolicy: ...

    def check_contract(
        self,
        upstream_stage: str,
        downstream_stage: str,
    ) -> ContractCheckResult: ...
```

### Schema 注册约定

每个阶段的 Schema 以 Pydantic `BaseModel` 子类形式定义在 `DataPipeline/validation/schemas/` 目录下。Schema 中的字段名 MUST 与 `DataPipeline/storage/schema/columns.py` 中定义的列名一致。

---

## Validator

```python
class Validator:
    """数据校验执行器"""

    def __init__(
        self,
        schema_registry: SchemaRegistry,
        config: Config | None = None,
    ) -> None: ...

    def validate_output(
        self,
        stage_name: str,
        records: list[dict[str, Any]],
    ) -> ValidationResult:
        """
        阶段输出校验 — 在阶段写 DB 后、下游读 DB 前执行。
        
        Args:
            stage_name: 阶段名称
            records: 待校验的记录列表（从 DB 读取的 row dicts）
        
        Returns:
            ValidationResult: 包含通过/失败记录数和违规详情
        """
        ...

    def validate_input(
        self,
        stage_name: str,
        records: list[dict[str, Any]],
    ) -> ValidationResult:
        """
        阶段输入预检 — 在下游阶段读 DB 后、处理前执行。
        
        Args:
            stage_name: 当前阶段名称
            records: 从 DB 读取的输入记录列表
        
        Returns:
            ValidationResult: 包含预检结果
        """
        ...
```

### ValidationResult

```python
@dataclass
class ValidationResult:
    passed: int               # 通过校验的记录数
    failed: int               # 未通过校验的记录数
    violations: list[ValidationViolation]
    duration_ms: float        # 校验耗时

    @property
    def failure_rate(self) -> float:
        """校验失败率"""
        total = self.passed + self.failed
        return self.failed / total if total > 0 else 0.0
```

---

## CircuitBreaker

```python
class CircuitBreaker:
    """按管道运行实例隔离的熔断器"""

    def __init__(
        self,
        run_id: str,
        stage_name: str,
        max_failures: int = 3,
        alert_callback: Callable[[AlertEvent], None] | None = None,
    ) -> None: ...

    @property
    def state(self) -> BreakerState: ...
    @property
    def is_open(self) -> bool: ...

    def before_stage(self) -> bool:
        """阶段执行前检查：返回 False 则阻断"""
        ...

    def record_success(self) -> None:
        """记录执行成功，重置失败计数"""
        ...

    def record_failure(self, severity: SeverityLevel, reason: str) -> bool:
        """
        记录执行失败。
        返回 True 表示需要熔断，False 表示仅记录。
        """
        ...

    def reset(self) -> None:
        """手动重置熔断状态 → HALF_OPEN"""
        ...
```

---

## PipelineRunLogger

```python
class PipelineRunLogger:
    """管道运行级结构化日志记录器"""

    def __init__(
        self,
        run_id: str,
        log_dir: Path | None = None,
    ) -> None: ...

    def start_run(self, target_date: str, stages: list[str]) -> None: ...
    def start_stage(self, stage_name: str, input_count: int | None) -> None: ...
    def end_stage(
        self,
        stage_name: str,
        status: StageStatus,
        output_count: int | None,
        passed: int,
        failed: int,
        duration_ms: float,
    ) -> None: ...
    def log_violation(self, stage_name: str, violation: ValidationViolation) -> None: ...
    def log_exception(self, stage_name: str, exc: Exception) -> None: ...
    def log_circuit_break(self, stage_name: str, reason: str) -> None: ...
    def finish_run(self, result: GuardRunResult) -> None: ...
    def flush(self) -> None:
        """将内存中的日志批量写入文件"""
        ...

    @property
    def log_path(self) -> Path: ...
```

**日志输出格式** — JSONL（每行一条 JSON 记录）:

```json
{"run_id":"20260616-153000-a1b2c3","ts":"2026-06-16T15:30:00","level":"RUN_START","target_date":"2026-06-15","stages":["S1","S2","S3","S4","S5","S6","S7","S8","S9","S10"]}
{"run_id":"20260616-153000-a1b2c3","ts":"2026-06-16T15:30:00","level":"STAGE_START","stage":"S1","input_count":null}
{"run_id":"20260616-153000-a1b2c3","ts":"2026-06-16T15:30:02","level":"STAGE_END","stage":"S1","status":"SUCCESS","output_count":150,"passed":150,"failed":0,"duration_ms":2100}
{"run_id":"20260616-153000-a1b2c3","ts":"2026-06-16T15:31:00","level":"STAGE_END","stage":"S2","status":"FAILED","output_count":0,"passed":0,"failed":1,"duration_ms":1200}
{"run_id":"20260616-153000-a1b2c3","ts":"2026-06-16T15:31:00","level":"VIOLATION","stage":"S2","field":"FillPrice","type":"TYPE_MISMATCH","expected":"float","actual":"N/A","record":"FillId=12345","severity":"ERROR"}
{"run_id":"20260616-153000-a1b2c3","ts":"2026-06-16T15:31:00","level":"CIRCUIT_BREAK","stage":"S2","reason":"连续失败 3 次，触发熔断","state":"OPEN"}
{"run_id":"20260616-153000-a1b2c3","ts":"2026-06-16T15:31:00","level":"RUN_END","status":"CIRCUIT_BROKEN","total_stages":10,"completed":1,"failed":1,"skipped":8,"duration_ms":60000}
```

---

## RetryPolicy (S1 专用)

```python
@dataclass
class RetryConfig:
    max_retries: int = 3
    base_delay_seconds: float = 1.0
    backoff_factor: float = 2.0  # 指数退避乘数

class RetryPolicy:
    """S1 外部数据摄入的重试策略"""

    def __init__(self, config: RetryConfig) -> None: ...

    async def execute_with_retry(
        self,
        fn: Callable[[], Awaitable[T]],
        context: dict[str, Any] | None = None,
    ) -> RetryResult[T]:
        """
        执行带重试的函数调用。
        
        Args:
            fn: 异步可调用对象（如 Bloomberg API 调用）
            context: 可选的上下文信息（用于日志）
        
        Returns:
            RetryResult: 包含结果或错误信息
        """
        ...
```

---

## 交叉引用

- 数据模型定义: [data-model.md](../data-model.md)
- 验证指南: [quickstart.md](../quickstart.md)
- 研究决策: [research.md](../research.md)
