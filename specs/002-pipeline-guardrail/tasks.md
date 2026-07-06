# Tasks: 数据管道护栏机制

**Input**: Design documents from `/specs/002-pipeline-guardrail/`

**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md, contracts/guard-pipeline-api.md, quickstart.md

**Tests**: 本功能规范明确要求测试覆盖（US3 管道完整性自动化测试 + quickstart.md 10 个验证场景），所有用户故事均包含测试任务。

**Organization**: 任务按用户故事分组，支持每个故事的独立实现和测试。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行执行（不同文件，无依赖关系）
- **[Story]**: 任务归属的用户故事标签（US1/US2/US3/US4）
- 所有描述包含精确文件路径

## Path Conventions

- 管道护栏机制位于 `DataPipeline/` 目录下
- 新增包: `validation/`、`circuit_breaker/`、`monitoring/`
- 新增编排文件: `orchestration/guard.py`、`orchestration/guard_stage.py`
- 修改文件: `config.py`
- 测试目录: `tests/guardrail/`

---

## Phase 1: Setup（项目初始化）

**Purpose**: 创建护栏机制目录结构和包初始化文件

- [X] T001 创建护栏机制子包目录结构：`DataPipeline/validation/`、`DataPipeline/validation/schemas/`、`DataPipeline/circuit_breaker/`、`DataPipeline/monitoring/`
- [X] T002 [P] 创建 `DataPipeline/validation/__init__.py` 包初始化文件
- [X] T003 [P] 创建 `DataPipeline/validation/schemas/__init__.py` 包初始化文件
- [X] T004 [P] 创建 `DataPipeline/circuit_breaker/__init__.py` 包初始化文件
- [X] T005 [P] 创建 `DataPipeline/monitoring/__init__.py` 包初始化文件
- [X] T006 创建测试目录结构：`DataPipeline/tests/guardrail/`、`DataPipeline/tests/baselines/`、`DataPipeline/tests/fixtures/`
- [X] T007 [P] 创建 `DataPipeline/tests/guardrail/__init__.py` 包初始化文件

---

## Phase 2: Foundational（基础前提）

**Purpose**: 所有用户故事共享的核心基础设施， MUST 在任何用户故事开发前完成

**⚠️ CRITICAL**: 此阶段未完成前，不得开始任何用户故事的实现

- [X] T008 向 `DataPipeline/config.py` Config 类添加护栏配置项：`GUARDRAIL_ENABLED`、`GUARDRAIL_CIRCUIT_BREAKER_THRESHOLD`、`GUARDRAIL_RETRY_MAX`、`GUARDRAIL_LOG_DIR`、`GUARDRAIL_BASELINE_DIR`、`GUARDRAIL_VALIDATION_STRICT_MODE`、`GUARDRAIL_EMPTY_DATASET_POLICY`（值 "reject"|"accept"，默认 "reject"）、`GUARDRAIL_VALIDATION_BYPASS_ON_ERROR`（校验规则异常时降级放行，默认 False）
- [X] T009 [P] 定义所有枚举类型于 `DataPipeline/validation/enums.py`：`RunStatus`、`StageStatus`、`SeverityLevel`、`BreakerState`、`ViolationType`、`ValidationPolicy`、`SchemaDirection`、`ContractCompatibility`（对照 data-model.md 枚举定义章节）
- [X] T010 [P] 创建 `ValidationViolation` 数据类于 `DataPipeline/validation/violation.py`，包含字段：`run_id`、`stage_name`、`record_identifier`、`field_name`、`expected_constraint`、`actual_value`、`severity`、`violation_type`、`violated_at`
- [X] T011 [P] 创建核心结果类型于 `DataPipeline/validation/results.py`：`ValidationResult`（passed/failed/violations/duration_ms/failure_rate）、`GuardStageResult`（violations 字段类型为 `list[ValidationViolation]`）、`GuardRunResult`（参考 contracts/guard-pipeline-api.md StageExecution Result 章节）
- [X] T012 [P] 创建 `ContractCheckResult` 数据类于 `DataPipeline/validation/contract_checker.py`，包含 `compatibility: ContractCompatibility` 和 `issues: list[str]`
- [X] T013 创建护栏测试共享 fixture 于 `DataPipeline/tests/guardrail/conftest.py`：Mock FinancialPipeline、内存 SQLite 数据库连接、样例数据生成工具函数

**Checkpoint**: 基础设施就绪 — 可以开始用户故事实现

---

## Phase 3: User Story 1 — 管道节点数据校验 (Priority: P1) 🎯 MVP

**Goal**: 在每个管道阶段将数据写入 DB 后立即对写入数据执行模式校验，拦截缺失必填字段、类型错误、值域违规的不合规数据，防止错误数据流入下游阶段

**Independent Test**: 向管道阶段输入包含缺失必填字段、类型错误或越界值的记录，验证系统在阶段输出边界拦截并报告具体违规项（对照 quickstart.md 场景 1-3）

### 阶段 Schema 定义

- [X] T014 [P] [US1] 创建 S1/S2 raw_fills 模式 `RawFillsSchema` 于 `DataPipeline/validation/schemas/raw_fills.py`，字段须与 `DataPipeline/storage/schema/columns.py` 中 `EMSX_FILL_COLUMNS` 一致
- [X] T015 [P] [US1] 创建 `ProcessedFillsSchema` 基类于 `DataPipeline/validation/schemas/processed_fills.py`，字段须与 `PROCESSED_COLUMNS` 一致；在此文件中同时定义 S3 专用子类 `AggregateFillsSchema`（扩展聚合字段）和 S4 专用子类 `OrderLabelsSchema`（扩展标签字段），三者共享基础字段定义
- [X] T016 [P] [US1] 创建 S5 fill_bdib 模式 `FillBdibSchema` 于 `DataPipeline/validation/schemas/fill_bdib.py`，定义 BDIB 集成后的合并字段
- [X] T017 [P] [US1] 创建 S7 daily_metrics 模式 `DailyMetricsSchema` 于 `DataPipeline/validation/schemas/daily_metrics.py`
- [X] T018 [P] [US1] 创建 S8/S9 regime 模式 `RegimeSchema` 于 `DataPipeline/validation/schemas/regime.py`
- [X] T019 [P] [US1] 创建 S10 attribution 模式 `AttributionSchema` 于 `DataPipeline/validation/schemas/attribution.py`
- **注**: S6（WriteManifest）输出为文件系统清单 JSON 而非数据库表，不创建 Pydantic Schema，其完整性由清单文件格式自身的 JSON Schema 保证；S9（RegimeFillTagger）复用 `RegimeSchema`，无独立模式文件

### SchemaRegistry 与 Validator

- [X] T020 [US1] 实现 `SchemaRegistry` 类于 `DataPipeline/validation/schema_registry.py`：`register()`、`get_input_schema()`、`get_output_schema()`、`get_policy()` 方法（对照 contracts/guard-pipeline-api.md SchemaRegistry 章节）
- [X] T021 [US1] 实现 `SchemaRegistry.check_contract()` 方法于 `DataPipeline/validation/schema_registry.py`，委托给 `contract_checker.check_contract_compatibility()`
- [X] T022 [US1] 实现 `Validator.validate_output()` 方法于 `DataPipeline/validation/validator.py`：对记录列表逐条执行 Pydantic `model_validate()`，捕获 `ValidationError` 并转换为 `ValidationViolation` 实例（定义于 `violation.py`），根据阶段策略（STRICT/RELAXED）决定拦截行为
- [X] T023 [US1] 实现 `Validator.validate_input()` 方法于 `DataPipeline/validation/validator.py`：下游阶段读 DB 后执行输入预检，确认数据格式和必填字段符合预期
- [X] T024 [US1] 实现 `check_contract_compatibility()` 函数于 `DataPipeline/validation/contract_checker.py`：基于 Pydantic `model_fields` 元数据执行字段存在性检查、类型兼容性检查、约束兼容性检查，返回 `ContractCheckResult`（对照 research.md R4 实现细节）

### 数据校验测试

- [X] T025 [P] [US1] 创建测试 `test_reject_missing_required_field` 于 `DataPipeline/tests/guardrail/test_validation.py`：输入缺失必填字段的记录，验证输出校验拦截并记录 MISSING_REQUIRED 违规（quickstart.md 场景 1）
- [X] T026 [P] [US1] 创建测试 `test_reject_out_of_range` 于 `DataPipeline/tests/guardrail/test_validation.py`：输入负成交量/零价格记录，验证输出校验拦截并记录 RANGE_VIOLATION 违规（quickstart.md 场景 2）
- [X] T027 [P] [US1] 创建测试 `test_accept_valid_records` 于 `DataPipeline/tests/guardrail/test_validation.py`：输入10条完整合法记录，验证全部通过，校验耗时 < 100ms（quickstart.md 场景 3）
- [X] T028 [P] [US1] 创建测试 `test_type_mismatch_interception` 于 `DataPipeline/tests/guardrail/test_validation.py`：输入字符串值写入数值字段的记录，验证 TYPE_MISMATCH 违规拦截
- [X] T029 [P] [US1] 创建测试 `test_empty_dataset_handling` 于 `DataPipeline/tests/guardrail/test_validation.py`：输入空数据集，验证按 `GUARDRAIL_EMPTY_DATASET_POLICY` 配置决定是否接受（默认 "reject"，校验失败并记录日志）
- [X] T030 [P] [US1] 创建测试 `test_relaxed_policy_s1` 于 `DataPipeline/tests/guardrail/test_validation.py`：验证 S1 宽松策略仅校验类型、不校验值域和必填字段
- [X] T030a [P] [US1] 创建测试 `test_bypass_on_validation_error` 于 `DataPipeline/tests/guardrail/test_validation.py`：启用 `GUARDRAIL_VALIDATION_BYPASS_ON_ERROR` 降级模式后，输入包含必填字段缺失的记录，验证系统记录 WARNING 日志但数据正常放行入库（对应 FR-024）

**Checkpoint**: 数据校验功能完整且可独立测试 — 阶段边界输入/输出校验全部覆盖

---

## Phase 4: User Story 3 — 管道完整性自动化测试 (Priority: P1) 🎯 MVP

**Goal**: 建立管道完整性测试套件，使用 Mock/Fixture 数据验证全链路数据流转正确性，支持基线快照对比和 CI 集成，确保代码变更不意外破坏管道

**Independent Test**: 运行 `pytest DataPipeline/tests/guardrail/` 测试套件，使用已知 Mock 数据执行完整管道流程，验证各阶段输出符合预期（对照 quickstart.md 场景 7-9）

### 测试数据准备

- [X] T031 [US3] 创建合法成交测试数据 `valid_fills.json` 于 `DataPipeline/tests/fixtures/valid_fills.json`：10 条完整且符合所有约束的成交记录（脱敏历史数据样本）
- [X] T032 [P] [US3] 创建非法成交测试数据 `invalid_fills.json` 于 `DataPipeline/tests/fixtures/invalid_fills.json`：包含缺失字段、类型错误、值域违规的记录各若干条
- [X] T033 [P] [US3] 创建空数据测试文件 `empty_fills.json` 于 `DataPipeline/tests/fixtures/empty_fills.json`：空记录列表

### 基线快照

- [X] T034 [US3] 为 S1 阶段生成基线快照 `s1_output.json` 于 `DataPipeline/tests/baselines/s1_output.json`：使用 valid_fills.json 作为输入，执行 S1 处理逻辑，固化为 JSON 快照
- [X] T035 [US3] 为 S2-S7 核心处理阶段生成基线快照于 `DataPipeline/tests/baselines/`：`s2_output.json`、`s3_output.json`、`s4_output.json`、`s5_output.json`、`s7_output.json`（基于上游合法输入产出）
- [X] T036 [US3] 为 S8-S10 分析阶段生成基线快照于 `DataPipeline/tests/baselines/`：`s8_output.json`、`s10_output.json`（可选生成，作为扩展基线）
- [X] T036a [US3] 创建基线更新审批流程于 `DataPipeline/tests/guardrail/baseline_review.py`：提供 CLI 命令 `python -m DataPipeline.tests.guardrail.baseline_review --stage S2 --new-baseline <path>`，生成新旧基线差异报告（JSON diff 格式）；差异报告随 PR 提交，由 Reviewer 在 Code Review 中确认后手动执行 `--approve` 归档为新基线

### 管道完整性测试

- [X] T037 [US3] 实现 `test_full_pipeline_integrity` 于 `DataPipeline/tests/guardrail/test_pipeline_integrity.py`：使用 Fixture 数据执行 S1-S10 全链路，验证所有阶段执行成功且输出通过校验（quickstart.md 场景 7）
- [X] T038 [US3] 实现 `test_baseline_comparison` 于 `DataPipeline/tests/guardrail/test_pipeline_integrity.py`：对比各阶段实际输出与基线快照，数值字段 1% 容差，差异超阈值标记失败（quickstart.md 场景 8）
- [X] T039 [US3] 实现 `test_downstream_impact_detection` 于 `DataPipeline/tests/guardrail/test_pipeline_integrity.py`：修改某阶段逻辑导致输出格式变化，验证受影响下游阶段同步报错（US3 Acceptance Scenario 2）
- [X] T040 [US3] 实现 `test_mock_mode_independence` 于 `DataPipeline/tests/guardrail/test_pipeline_integrity.py`：验证测试套件不依赖真实 Bloomberg API 或外部 DB，仅使用 Mock/Fixture 数据

### 契约检查测试

- [X] T041 [US3] 实现 `test_schema_incompatible_detection` 于 `DataPipeline/tests/guardrail/test_contract_checker.py`：删除上游 Schema 字段后验证下游被标记为 INCOMPATIBLE（quickstart.md 场景 9）
- [X] T042 [P] [US3] 实现 `test_schema_compatible_change` 于 `DataPipeline/tests/guardrail/test_contract_checker.py`：新增可选字段后验证 COMPATIBLE，放宽约束验证 COMPATIBLE

### CI 集成

- [X] T043 [US3] 创建 CI 测试运行脚本于 `DataPipeline/tests/guardrail/run_ci_tests.py`：支持 `--ci-mode` 参数，通过 Git diff 识别变更文件判定受影响阶段，仅运行受影响阶段及下游的增量测试
- [X] T044 [US3] 在 `DataPipeline/tests/guardrail/` 下创建 `pytest.ini` 或 `conftest.py` 中的 CI 配置：设置 junitxml 输出、覆盖率目标（validation/circuit_breaker/monitoring ≥ 80%）、5 分钟超时

**Checkpoint**: 管道完整性测试套件就绪 — 全链路测试、基线对比、契约检查、CI 集成均可运行

---

## Phase 5: User Story 2 — 管道异常熔断与告警 (Priority: P2)

**Goal**: 实现三级（Info/Error/Critical）异常熔断机制，当校验失败率超阈值或 Critical 异常发生时自动阻断下游阶段执行并告警，支持手动重置恢复

**Independent Test**: 模拟阶段连续校验失败触发熔断，验证下游阶段被阻断执行（对照 quickstart.md 场景 4-6）

### 熔断器核心实现

- [X] T045 [US2] 实现 `CircuitBreaker` 三态状态机于 `DataPipeline/circuit_breaker/breaker.py`：状态转移逻辑 — CLOSED→(连续失败≥阈值)→OPEN，CLOSED→(Critical异常)→OPEN，OPEN→(手动重置)→HALF_OPEN，HALF_OPEN→(探测成功)→CLOSED，HALF_OPEN→(探测失败)→OPEN（对照 research.md R1 实现细节）
- [X] T046 [US2] 实现 `CircuitBreaker.before_stage()` 于 `DataPipeline/circuit_breaker/breaker.py`：返回 False 表示阻断当前阶段执行
- [X] T047 [US2] 实现 `CircuitBreaker.record_failure()` 于 `DataPipeline/circuit_breaker/breaker.py`：按严重等级分路由 — Critical 立即设 OPEN，Error 累加失败计数达阈值设 OPEN，Info 仅记录不触发熔断
- [X] T048 [US2] 实现 `CircuitBreaker.record_success()` 和 `CircuitBreaker.reset()` 于 `DataPipeline/circuit_breaker/breaker.py`：成功时重置失败计数，reset() 将状态置为 HALF_OPEN
- [X] T049 [US2] 实现 `CircuitBreakerRegistry` 于 `DataPipeline/circuit_breaker/breaker_registry.py`：按 `run_id` 隔离的熔断器注册表，`get_or_create(run_id, stage_name)` 返回独立的熔断器实例

### 重试与告警

- [X] T050 [US2] 实现 `RetryConfig` 和 `RetryPolicy` 于 `DataPipeline/circuit_breaker/retry_policy.py`：S1 外部数据摄入专用重试策略，支持指数退避（base_delay_seconds=1.0, backoff_factor=2.0, max_retries=3）
- [X] T051 [US2] 实现 `RetryPolicy.execute_with_retry()` 于 `DataPipeline/circuit_breaker/retry_policy.py`：异步重试包装器，超过重试上限返回降级结果
- [X] T052 [US2] 实现告警机制于 `DataPipeline/circuit_breaker/alert.py`：`AlertEvent` 数据类和 `send_alert()` 函数（初期以结构化日志形式输出告警，保留外部通知渠道扩展点）

### 熔断机制测试

- [X] T053 [P] [US2] 创建测试 `test_critical_trigger_immediate_break` 于 `DataPipeline/tests/guardrail/test_circuit_breaker.py`：模拟 Critical 异常，验证立即熔断且下游阶段被阻断（quickstart.md 场景 4）
- [X] T054 [P] [US2] 创建测试 `test_error_accumulation_break` 于 `DataPipeline/tests/guardrail/test_circuit_breaker.py`：连续 3 次 Error 失败后验证状态从 CLOSED 变 OPEN（quickstart.md 场景 5）
- [X] T055 [P] [US2] 创建测试 `test_manual_reset_recovery` 于 `DataPipeline/tests/guardrail/test_circuit_breaker.py`：手动重置后验证 HALF_OPEN → 探测成功 → CLOSED 恢复流程（quickstart.md 场景 6）
- [X] T056 [P] [US2] 创建测试 `test_info_does_not_trigger_break` 于 `DataPipeline/tests/guardrail/test_circuit_breaker.py`：Info 级异常不触发熔断
- [X] T057 [P] [US2] 创建测试 `test_skipped_stage_not_counted` 于 `DataPipeline/tests/guardrail/test_circuit_breaker.py`：被跳过的阶段不计入熔断统计
- [X] T058 [P] [US2] 创建测试 `test_breaker_isolation_by_run_id` 于 `DataPipeline/tests/guardrail/test_circuit_breaker.py`：不同 run_id 的熔断状态相互隔离

**Checkpoint**: 熔断机制完整 — 三级严重等级、状态转移、重试降级、告警通知均可独立验证

---

## Phase 6: User Story 4 — 数据流转日志追踪 (Priority: P2)

**Goal**: 为每次管道执行生成唯一运行 ID，在每个阶段边界记录结构化日志，支持按日期/运行 ID/阶段名称检索，管道结束时输出执行概要

**Independent Test**: 执行一次管道运行后检查日志输出是否包含阶段入口/出口摘要、数据量统计、异常记录（对照 quickstart.md 场景 10）

### 日志核心实现

- [X] T059 [US4] 实现运行 ID 生成器于 `DataPipeline/monitoring/run_id.py`：格式 `YYYYMMDD-HHMMSS-xxxxxx`，保证唯一性
- [X] T060 [US4] 实现 `PipelineRunLogger` 类于 `DataPipeline/monitoring/run_logger.py`：`start_run()`、`start_stage()`、`end_stage()`、`log_violation(stage_name, violation: ValidationViolation)`、`log_exception()`、`log_circuit_break()`、`finish_run()` 方法（对照 contracts/guard-pipeline-api.md PipelineRunLogger 章节）
- [X] T061 [US4] 实现 JSONL 格式化和 `flush()` 于 `DataPipeline/monitoring/run_logger.py`：内存缓冲批量写入文件，日志文件路径 `{log_dir}/{run_id}.jsonl`
- [X] T062 [US4] 实现阶段日志辅助模块于 `DataPipeline/monitoring/stage_logger.py`：封装阶段级日志条目的构建和写入逻辑
- [X] T063 [US4] 实现管道执行概要生成器于 `DataPipeline/monitoring/summary.py`：汇总整条管道的执行状态（total_stages/completed/failed/skipped/duration_ms）和数据流转统计

### 日志测试

- [X] T064 [P] [US4] 创建测试 `test_complete_run_log` 于 `DataPipeline/tests/guardrail/test_logging.py`：验证日志包含 RUN_START、每阶段 STAGE_START/STAGE_END、RUN_END 条目，所有条目关联相同 run_id（quickstart.md 场景 10）
- [X] T065 [P] [US4] 创建测试 `test_violation_logging` 于 `DataPipeline/tests/guardrail/test_logging.py`：校验失败时日志包含 VIOLATION 条目，含字段名、期望约束、实际值
- [X] T066 [P] [US4] 创建测试 `test_exception_logging` 于 `DataPipeline/tests/guardrail/test_logging.py`：阶段异常时日志包含异常类型、消息、堆栈跟踪
- [X] T067 [P] [US4] 创建测试 `test_log_retrieval_by_run_id` 于 `DataPipeline/tests/guardrail/test_logging.py`：按 run_id 检索日志文件，验证可按日期和阶段名称过滤

**Checkpoint**: 日志追踪完整 — 结构化 JSONL 日志、运行 ID 关联、概要汇总均可独立验证

---

## Phase 7: Polish & Cross-Cutting Concerns（集成与完善）

**Purpose**: 将所有护栏组件编织为完整的 GuardPipeline 编排器，端到端集成验证

### GuardPipeline 编排器

- [X] T068 实现 `GuardStage` 阶段包装器于 `DataPipeline/orchestration/guard_stage.py`：包装单个阶段的执行，注入 pre-execution 校验钩子（输入预检）、post-execution 校验钩子（输出校验）、熔断检查、日志记录
- [X] T069 实现 `GuardPipeline.__init__()` 构造器于 `DataPipeline/orchestration/guard.py`：接收 `FinancialPipeline`、`SchemaRegistry`、`CircuitBreakerRegistry`（可选）、`PipelineRunLogger`（可选）、`Config`（可选）参数（对照 contracts/guard-pipeline-api.md GuardPipeline Constructor 章节）
- [X] T070 实现 `GuardPipeline.run()` 编排逻辑于 `DataPipeline/orchestration/guard.py`：生成 run_id → 创建独立熔断器注册表 → 顺序执行阶段 → 每阶段前后执行校验钩子 → 熔断检查 → 日志记录 → 返回 GuardRunResult
- [X] T071 在 `GuardPipeline.run()` 中实现阶段跳过检测：被配置跳过的阶段（skip_ingest/skip_bdib）完全排除在护栏之外，不执行校验、不计入熔断统计
- [X] T072 在 `GuardPipeline.run()` 中实现 S1 宽松策略 vs S2-S10 严格策略差异化处理：S1 校验失败触发重试+降级不熔断，S2-S10 按严重等级触发熔断
- [X] T073 在 `GuardPipeline.run()` 中接入告警通知：Critical 级熔断触发时调用 `alert.send_alert()`，Error 级连续失败触发时记录告警

### 端到端集成验证

- [X] T074 创建端到端集成测试 `test_guard_pipeline_full_integration` 于 `DataPipeline/tests/guardrail/test_pipeline_integrity.py`：使用 Mock FinancialPipeline + 真实 SchemaRegistry + CircuitBreaker + Logger 执行完整 GuardPipeline.run()
- [X] T075 创建集成测试 `test_s1_retry_on_failure` 于 `DataPipeline/tests/guardrail/test_pipeline_integrity.py`：模拟 S1 外部调用失败，验证重试 3 次后退避降级，不触发熔断
- [X] T076 创建集成测试 `test_critical_breaks_entire_pipeline` 于 `DataPipeline/tests/guardrail/test_pipeline_integrity.py`：S2 阶段触发 Critical 异常，验证全链路立即熔断且日志包含 CIRCUIT_BREAK 事件
- [X] T076a [P] 创建性能基准测试 `test_guardrail_overhead` 于 `DataPipeline/tests/guardrail/test_pipeline_integrity.py`：使用合法数据分别执行启用和未启用护栏的完整管道流程，验证校验+日志额外开销不超过纯业务执行时间的 5%（对应 SC-008）；使用 `pytest-benchmark` 工具记录基线耗时
- [X] T076b 在 `GuardPipeline.run()` 中接入校验降级逻辑：当 `GUARDRAIL_VALIDATION_BYPASS_ON_ERROR` 启用时，校验拦截行为降级为仅记录 WARNING 日志后放行数据，不拒绝入库（对应 FR-024）

### 文档与验证

- [X] T077 为 `DataPipeline/config.py` 新增护栏配置项添加中文 docstring 说明（每个配置项的用途、类型、默认值）
- [X] T078 运行 quickstart.md 全部 10 个验证场景，确保所有场景通过
- [X] T079 运行完整护栏测试套件 `pytest DataPipeline/tests/guardrail/ -v --cov`，验证覆盖率 ≥ 80%
- [X] T080 在 `DataPipeline/validation/schemas/__init__.py` 中添加所有 Schema 类的公开导出列表

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 无依赖 — 可立即开始
- **Foundational (Phase 2)**: 依赖 Setup 完成 — **阻塞所有用户故事**
- **User Story 1 (Phase 3)**: 依赖 Foundational 完成 — P1 优先级
- **User Story 3 (Phase 4)**: 依赖 US1 完成（需要 Schema 定义和 Validator 实现）— P1 优先级，但可在 US1 完成后并行于 US2/US4
- **User Story 2 (Phase 5)**: 依赖 Foundational 完成 — P2 优先级，可与 US3/US4 并行
- **User Story 4 (Phase 6)**: 依赖 Foundational 完成 — P2 优先级，可与 US3/US2 并行
- **Polish (Phase 7)**: 依赖 ALL 用户故事完成 — GuardPipeline 编排器集成所有组件

### User Story Dependencies

```
Phase 1: Setup
    ↓
Phase 2: Foundational (BLOCKS ALL)
    ↓
    ├─ Phase 3: US1 (P1) — 数据校验 ←──── 必须先于 US3
    │       ↓
    ├─ Phase 4: US3 (P1) — 完整性测试 ← 依赖 US1 Schema/Validator
    │
    ├─ Phase 5: US2 (P2) — 熔断告警 ←── 可与 US3/US4 并行
    │
    └─ Phase 6: US4 (P2) — 日志追踪 ←── 可与 US3/US2 并行
              ↓
Phase 7: Polish & Integration ← 依赖 US1+US2+US3+US4
```

### Within Each User Story

- Schema/Entity 定义 → 核心类实现 → 集成注册 → 测试
- 测试 MUST 在实现完成后验证（非 TDD，但验证步骤不可省略）
- 故事内 [P] 标记的任务可并行

### Parallel Opportunities

- **Phase 1**: T002-T007 全部可并行（不同包的 __init__.py）
- **Phase 2**: T009-T012 可并行（不同文件，无相互依赖）
- **Phase 3**: T014-T019 可并行（6 个 Schema 文件互不依赖），T025-T030a 可并行（7 个独立测试）
- **Phase 4**: T032-T033 可并行，T041-T042 可并行
- **Phase 5**: T053-T058 可并行（6 个独立测试）
- **Phase 6**: T064-T067 可并行（4 个独立测试）
- **Phase 5 和 Phase 6 之间**：US2（熔断）与 US4（日志）完全独立，可并行实现
- **Phase 3+4（P1）与 Phase 5+6（P2）之间**：P1 优先但可在团队多人时并行推进

---

## Parallel Example: User Story 1

```bash
# 并行启动所有 Schema 定义:
Task: "T014 创建 RawFillsSchema 于 DataPipeline/validation/schemas/raw_fills.py"
Task: "T015 创建 ProcessedFillsSchema 于 DataPipeline/validation/schemas/processed_fills.py"
Task: "T016 创建 FillBdibSchema 于 DataPipeline/validation/schemas/fill_bdib.py"
Task: "T017 创建 DailyMetricsSchema 于 DataPipeline/validation/schemas/daily_metrics.py"
Task: "T018 创建 RegimeSchema 于 DataPipeline/validation/schemas/regime.py"
Task: "T019 创建 AttributionSchema 于 DataPipeline/validation/schemas/attribution.py"

# Schema 完成后，并行启动所有校验测试:
Task: "T025 test_reject_missing_required_field"
Task: "T026 test_reject_out_of_range"
Task: "T027 test_accept_valid_records"
Task: "T028 test_type_mismatch_interception"
Task: "T029 test_empty_dataset_handling"
Task: "T030 test_relaxed_policy_s1"
Task: "T030a test_bypass_on_validation_error"
```

---

## Parallel Example: Phase 5 + Phase 6 (Cross-Story)

```bash
# US2 和 US4 完全独立，可同时开发:
Developer A: Phase 5 (US2) — CircuitBreaker → BreakerRegistry → RetryPolicy → Alert → Tests
Developer B: Phase 6 (US4) — run_id → PipelineRunLogger → StageLogger → Summary → Tests
```

---

## Implementation Strategy

### MVP First（仅 User Story 1 + User Story 3）

1. 完成 Phase 1: Setup
2. 完成 Phase 2: Foundational（**关键阻塞点**）
3. 完成 Phase 3: User Story 1 — 数据校验
4. 完成 Phase 4: User Story 3 — 完整性测试
5. **STOP and VALIDATE**: 独立验证数据校验和管道完整性测试
6. 如就绪可演示/部署 MVP（校验 + 测试已有护栏价值）

### Incremental Delivery（增量交付）

1. Setup + Foundational → 基础设施就绪
2. US1（数据校验）→ 独立测试 → **MVP 交付点 1**
3. US3（完整性测试）→ 独立测试 → **MVP 交付点 2**（含 CI 集成）
4. US2（熔断告警）→ 独立测试 → 管道具备自动阻断能力
5. US4（日志追踪）→ 独立测试 → 管道具备完整可观测性
6. Phase 7（集成编排）→ GuardPipeline 包装完整 → **完整交付**

### Parallel Team Strategy（多人协作）

多开发者场景：

1. 团队共同完成 Setup + Foundational
2. Foundational 完成后：
   - **Developer A**: US1（数据校验，Phase 3）
   - **Developer B**: US2（熔断告警，Phase 5）— 可与 A 并行
   - **Developer C**: US4（日志追踪，Phase 6）— 可与 A/B 并行
3. US1 完成后：
   - **Developer A**: US3（完整性测试，Phase 4）
4. 全部用户故事完成后：
   - **团队共同**: Phase 7（集成编排 + 端到端验证）

---

## Notes

- [P] 标记 = 不同文件、无依赖关系，可并行执行
- [Story] 标签将任务映射到特定用户故事以追踪进度
- 每个用户故事应可独立完成和测试
- 每完成一个任务或逻辑任务组后提交代码
- 在每个 Checkpoint 处停止以独立验证当前故事
- 所有 Pydantic Schema 字段名 MUST 与 `DataPipeline/storage/schema/columns.py` 中定义的列名一致
- 所有新增配置项 MUST 遵循 Config 类声明模式，不得硬编码路径和阈值
- 护栏机制仅存在于 `DataPipeline/` 命名空间内，不引入跨模块依赖
- 统一命名约定：违规记录实体名称为 `ValidationViolation`（不可使用 `ViolationRecord`），在所有任务、代码、合约文档中保持一致
- 避免：模糊任务描述、同文件冲突、破坏故事独立性的跨故事依赖
---

## Phase 8: 追加任务 — S2 跨日维度回归修复（2026-07-03）

**Purpose**: 在护栏机制全部完成（Phase 1-7 共 80 个 tasks 全部勾选）后，发现 S2 `target_dates` 维度错误使用了 `source_date`（拉取日）而非 `order_as_of_date`（真实交易日），导致 13 个 `source_date`（覆盖 69 个 OAD）共 3,600,000+ 行 raw_fills 未被处理。补录修复与回归任务。

### 代码修复

- [X] T081 [US3] 修复 `DataPipeline/orchestration/stages_ingest.py::ProcessRawFillsStage`：将 `raw_reader.get_all_source_dates()` 改为 `raw_reader.get_distinct_order_as_of_dates()`，使 S2 按真实交易日语义增量处理
- [X] T082 [US3] 在 `DataPipeline/storage/repositories/raw_fills.py` 新增 `SqliteRawFillReadRepository.get_distinct_order_as_of_dates()`：查询 `DISTINCT order_as_of_date`，规范化为 `YYYYMMDD` 短格式
- [X] T083 [US3] 增强 `SqliteRawFillReadRepository.get_fills_for_date()`：接受 `YYYYMMDD` 输入，新增 `substr(order_as_of_date, 1, 10)` 匹配 `YYYY-MM-DD` ISO 日期的回退路径
- [X] T084 [P] [US3] 补 `DataPipeline/orchestration/core.py` 缺失的 `import pandas as pd`（避免后续 S2 引用 `pd` 时 ImportError）

### 回归测试

- [X] T085 [P] [US3] 在 `DataPipeline/tests/guardrail/test_data_quality.py` 新增 `TestStage2CrossDayProcessing` 类：3 个 case 覆盖 `get_distinct_order_as_of_dates` 返回 `YYYYMMDD`、`get_fills_for_date` 接受 `YYYYMMDD`、回填后 `processed_fills` 完全覆盖 `raw_fills` 非 DFD 行（gap=0）。3/3 通过

### 数据回填

- [X] T086 [P] [US3] 备份 `CostView/data/{raw_fills,processed_fills}.db.<ts>` 至 `.bak.<ts>`
- [X] T087 [P] [US3] 运行 `scripts/ops/reprocess_affected_dates.py --missing-source-dates --no-s5`：13 个 `source_date` → 69 个 `order_as_of_date`，重跑 S2/S3/S4
- [X] T088 [P] [US3] 验证：`raw_fills` 非 DFD 11,112,677 = `processed_fills` 11,112,677，gap=0；增量 `agg_fills_10s` 1,997,504 行；增量 `order_label` 71,435 条覆盖 69/69 OAD

### 配套运维

- [X] T089 [P] [US3] 新增 `scripts/ops/cleanup_processed_fills_mismatches.py`：检测/删除 `processed_fills` 中孤儿行、日期不匹配行、无效 `order_as_of_date` 行；自动备份、`--dry-run` 与 `--dates` 参数
- [X] T090 [P] [US3] 新增 `scripts/ops/reprocess_affected_dates.py`：支持 `--dates` / `--from-cleanup` / `--missing-source-dates` / `--no-s5` 四种回填模式
- [X] T091 [P] [US3] 新增 `scripts/ops/analyze_processed_fills_nulls.py`：每列 NULL/空字符串统计（只读），用于修复前后健康度对比
- [X] T092 [P] [US3] 新增 `Config.STRICT_MISSING_TICKER_VALIDATION` 配置（默认 `false`）：启用时 `process_fills` 阶段 Exchange/equ_ticker 缺失直接抛 `ValueError`，阻止空 `equ_ticker` 流入下游

### 文档同步

- [X] T093 [P] [US3] 更新 `DataPipeline/BUSINESS_FLOW.md`：新增 §3.1.1 "S2 跨日维度修复" 章节、§6 横切关注点补 "S2 target_date 维度"、§11 运维脚本补 `analyze_processed_fills_nulls.py` 与 2 个新清理脚本说明
- [X] T094 [P] [US3] 更新 `CODEBUDDY.md`：把 `001-architecture-module-completion` 状态置为完成，Current Plan 追加 "S2 跨日维度修复记录" 章节
- [X] T095 [P] [US3] 更新 `specs/002-pipeline-guardrail/spec.md`：Status 由 `Draft` 改为 `Implemented (2026-06-25)`，追加 S2 跨日维度修复状态描述
- [X] T096 [P] [US3] 更新本 `tasks.md`：追加 Phase 8 "S2 跨日维度回归修复" 章节，登记 T081-T096 共 16 个追加任务

---

## 总结

| 维度 | 数量 |
| --- | --- |
| Phase 1-7 原始任务 | 80（全部完成） |
| Phase 8 追加任务 | 16（全部完成） |
| 总任务 | **96** |
| 实现完成度 | **100%** |
| 回归测试通过率 | **3/3（S2 跨日）+ 原 7 个质量测试** |
| 数据回填验证 | raw 11,112,677 = processed 11,112,677（gap=0） |

