"""数据校验与模式层 — 管道护栏机制的校验核心。

提供 Pydantic v2 声明式 Schema 定义、阶段级数据校验执行、Schema 注册表
以及阶段间契约兼容性检查。
"""

from DataPipeline.validation.enums import (
    BreakerState,
    ContractCompatibility,
    RunStatus,
    SchemaDirection,
    SeverityLevel,
    StageStatus,
    ValidationPolicy,
    ViolationType,
)
from DataPipeline.validation.violation import ValidationViolation
from DataPipeline.validation.results import GuardRunResult, GuardStageResult, ValidationResult
from DataPipeline.validation.schema_registry import SchemaRegistry
from DataPipeline.validation.validator import Validator
from DataPipeline.validation.contract_checker import ContractCheckResult, check_contract_compatibility

__all__ = [
    # 枚举
    "BreakerState",
    "ContractCompatibility",
    "RunStatus",
    "SchemaDirection",
    "SeverityLevel",
    "StageStatus",
    "ValidationPolicy",
    "ViolationType",
    # 数据结构
    "ValidationViolation",
    "ValidationResult",
    "GuardStageResult",
    "GuardRunResult",
    "ContractCheckResult",
    # 核心类
    "SchemaRegistry",
    "Validator",
    # 函数
    "check_contract_compatibility",
]
