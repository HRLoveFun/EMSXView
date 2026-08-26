# Quickstart: 数据管道护栏机制验证指南

**Feature**: 002-pipeline-guardrail
**Date**: 2026-06-16

本文档提供管道护栏机制的可运行验证场景，覆盖核心数据流转路径。

---

## 前置条件

### 环境要求

- Python 3.11+
- DataPipeline 包已安装: `pip install -e DataPipeline`
- 测试依赖: `pytest`, `pytest-cov`

### 环境配置

```powershell
# Windows 开发环境
$env:EMSXVIEW_MERGE_MODULES = "true"
$env:EMSXVIEW_DATA_DIR = "C:\path\to\EMSXView\CostView\data"

# Linux / macOS
export EMSXVIEW_MERGE_MODULES=true
export EMSXVIEW_DATA_DIR=/path/to/EMSXView/CostView/data
```

### 测试数据准备

```bash
# 确保护栏测试目录存在
mkdir -p DataPipeline/tests/guardrail/baselines
mkdir -p DataPipeline/tests/guardrail/fixtures

# 生成基线快照（首次运行或基线更新时）
python -m pytest DataPipeline/tests/guardrail/test_pipeline_integrity.py --generate-baselines
```

---

## 验证场景

### 场景 1: 数据校验 — 字段缺失拦截

**目的**: 验证阶段输出校验能拦截缺失必填字段的记录

**命令**:
```bash
python -m pytest DataPipeline/tests/guardrail/test_validation.py::test_reject_missing_required_field -v
```

**预期输出**:
```
PASSED: test_reject_missing_required_field
  输入 1 条记录（缺失 FillPrice 字段）
  → 阶段 S2 输出校验拒绝该记录
  → 违规记录包含: field_name="FillPrice", violation_type=MISSING_REQUIRED, severity=ERROR
  → validation_passed=0, validation_failed=1
```

---

### 场景 2: 数据校验 — 值域违规拦截

**目的**: 验证阶段输出校验能拦截越界值的记录

**命令**:
```bash
python -m pytest DataPipeline/tests/guardrail/test_validation.py::test_reject_out_of_range -v
```

**预期输出**:
```
PASSED: test_reject_out_of_range
  输入 1 条记录（FillShares=-100，FillPrice=0）
  → 阶段 S2 输出校验拒绝该记录
  → 违规记录包含: field_name="FillShares", violation_type=RANGE_VIOLATION, actual_value=-100
  → 违规记录包含: field_name="FillPrice", violation_type=RANGE_VIOLATION, actual_value=0
  → validation_passed=0, validation_failed=1
```

---

### 场景 3: 数据校验 — 正常数据通过

**目的**: 验证合法数据能正常通过校验

**命令**:
```bash
python -m pytest DataPipeline/tests/guardrail/test_validation.py::test_accept_valid_records -v
```

**预期输出**:
```
PASSED: test_accept_valid_records
  输入 10 条合法记录（所有字段完整且符合约束）
  → 校验全部通过
  → validation_passed=10, validation_failed=0
  → 校验耗时 < 100ms
```

---

### 场景 4: 熔断机制 — Critical 异常立即熔断

**目的**: 验证 Critical 级异常触发全链路立即熔断

**命令**:
```bash
python -m pytest DataPipeline/tests/guardrail/test_circuit_breaker.py::test_critical_trigger_immediate_break -v
```

**预期输出**:
```
PASSED: test_critical_trigger_immediate_break
  模拟 S2 阶段抛出 CRITICAL 异常
  → CircuitBreaker 状态从 CLOSED 变为 OPEN
  → 后续阶段 S3-S10 被阻断执行
  → 日志包含 CIRCUIT_BREAK 事件
  → 检查 breaker.is_open == True
```

---

### 场景 5: 熔断机制 — Error 累计触发熔断

**目的**: 验证连续 Error 失败后触发熔断

**命令**:
```bash
python -m pytest DataPipeline/tests/guardrail/test_circuit_breaker.py::test_error_accumulation_break -v
```

**预期输出**:
```
PASSED: test_error_accumulation_break
  模拟 S2 阶段连续 3 次 ERROR 失败（阈值 = 3）
  → 前 2 次: 记录失败但不熔断
  → 第 3 次: CircuitBreaker 状态从 CLOSED 变为 OPEN
  → breaker.failure_count == 3
```

---

### 场景 6: 熔断机制 — 手动重置恢复

**目的**: 验证运维手动重置后管道可恢复执行

**命令**:
```bash
python -m pytest DataPipeline/tests/guardrail/test_circuit_breaker.py::test_manual_reset_recovery -v
```

**预期输出**:
```
PASSED: test_manual_reset_recovery
  设置熔断状态为 OPEN
  → 调用 breaker.reset()
  → 状态变为 HALF_OPEN
  → 执行探测阶段成功 → 状态恢复为 CLOSED
  → breaker.failure_count == 0
```

---

### 场景 7: 管道完整性 — 全链路测试

**目的**: 验证端到端管道执行（使用 Mock 数据）

**命令**:
```bash
python -m pytest DataPipeline/tests/guardrail/test_pipeline_integrity.py::test_full_pipeline_integrity -v
```

**预期输出**:
```
PASSED: test_full_pipeline_integrity
  使用 Fixture 数据执行 S1-S10 全链路
  → 所有阶段执行完成
  → 每阶段输出通过校验
  → 返回 GuardRunResult(status=SUCCESS)
  → summary 包含各阶段耗时和数据量统计
```

---

### 场景 8: 管道完整性 — 基线对比测试

**目的**: 验证阶段输出与基线快照的差异检测

**命令**:
```bash
python -m pytest DataPipeline/tests/guardrail/test_pipeline_integrity.py::test_baseline_comparison -v
```

**预期输出**:
```
PASSED: test_baseline_comparison
  执行 S2 阶段
  → 对比 S2 输出与基线快照 baselines/s2_output.json
  → 所有字段值和记录数匹配（数值字段在 1% 容差内）
  → 差异报告为空
```

---

### 场景 9: 契约检查 — 模式兼容性

**目的**: 验证上游输出变更时能检测下游不兼容

**命令**:
```bash
python -m pytest DataPipeline/tests/guardrail/test_contract_checker.py::test_schema_incompatible_detection -v
```

**预期输出**:
```
PASSED: test_schema_incompatible_detection
  修改 S1 输出 Schema（删除 FillPrice 字段）
  → 调用 contract_checker.check(S1_output, S2_input)
  → 返回 ContractCompatibility.INCOMPATIBLE
  → issues 包含: "下游必需字段 'FillPrice' 在上游输出中不存在"
```

---

### 场景 10: 日志记录 — 全链路追踪

**目的**: 验证结构化日志包含完整的运行记录

**命令**:
```bash
python -m pytest DataPipeline/tests/guardrail/test_logging.py::test_complete_run_log -v
```

**预期输出**:
```
PASSED: test_complete_run_log
  执行一次完整管道运行
  → 日志文件包含 RUN_START 条目
  → 每个阶段有 STAGE_START 和 STAGE_END 条目
  → 日志文件以 RUN_END 条目结束
  → 所有条目包含相同的 run_id
  → RUN_END 的 summary 字段包含: total_stages, completed, failed, skipped, duration_ms
```

---

## 批量验证

运行所有护栏测试:

```bash
# 运行全部护栏测试
python -m pytest DataPipeline/tests/guardrail/ -v

# 带覆盖率报告
python -m pytest DataPipeline/tests/guardrail/ -v --cov=DataPipeline.validation --cov=DataPipeline.circuit_breaker --cov=DataPipeline.monitoring --cov-report=term

# 生成 JUnit XML 报告（CI 使用）
python -m pytest DataPipeline/tests/guardrail/ -v --junitxml=guardrail-report.xml
```

**预期通过率**: 100%（所有核心数据流转路径覆盖）

---

## CI 集成验证

模拟 CI 预检行为:

```bash
# 模拟 CI 增量测试：检测 Git diff，运行受影响阶段的测试
python -m pytest DataPipeline/tests/guardrail/test_pipeline_integrity.py -v --ci-mode

# 输出 CI 状态（退出码: 0=通过, 1=失败）
echo $?
```

CI 脚本（GitHub Actions）示例:
```yaml
- name: Run Pipeline Guardrail Tests
  run: |
    pip install -e DataPipeline
    python -m pytest DataPipeline/tests/guardrail/ -v \
      --junitxml=reports/guardrail.xml \
      --cov=DataPipeline.validation \
      --cov=DataPipeline.circuit_breaker \
      --cov=DataPipeline.monitoring \
      --cov-report=term \
      -W error::FutureWarning
```

---

## 故障验证清单

以下场景预期应触发护栏机制:

| # | 故障场景 | 预期护栏行为 | 对应 Acceptance Scenario |
|---|---------|-------------|------------------------|
| 1 | 上游输出缺少必填字段 | 输出校验拦截，记录 MISSING_REQUIRED 违规 | US1-S1 |
| 2 | 数值字段越界（负成交量） | 输出校验拦截，记录 RANGE_VIOLATION 违规 | US1-S2 |
| 3 | 字段类型错误（字符串写入数值列） | 输出校验拦截，记录 TYPE_MISMATCH 违规 | US1-S1 |
| 4 | 外部 Bloomberg API 不可用 | S1 重试 3 次后退避降级，记录 ERROR 不熔断 | US2-S4, S1 宽松策略 |
| 5 | S2 连续 3 次校验失败 | 触发 Error 熔断，下游 S3-S10 不执行 | US2-S1 |
| 6 | 单次 Critical 级数据损坏 | 立即熔断全链路，发送告警 | US2-S1 |
| 7 | CI 检测到阶段输出与基线不匹配 | 测试失败，阻止代码合并 | US3-S5 |
| 8 | 上游删除字段后下游未更新 | 契约检查工具报 INCOMPATIBLE | FR-002 |
| 9 | 阶段被配置跳过 | 护栏不校验该阶段，不计入统计 | Clarification Q8 |
| 10 | 运维手动重置熔断 | 状态恢复 HALF_OPEN，探测成功→CLOSED | US2-S3 |
